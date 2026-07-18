# Code Change Map v0.4 — 失聯預警「重試 + 升級」閉環設計

> **狀態**:Draft v0.4
> **建立日期**:2026-07-17 19:06
> **作者**:小龍蝦
> **目的**:實作「失聯預警」的多波升級機制,從「發出就結束」變成「確保被處理」

---

## 0. 為什麼這個設計救命

**現有問題**:用戶失聯 → 系統發 LINE 給守護人 → 守護人沒看到 LINE(睡著/手機靜音/已讀不回)→ **沒人知道,真的出事**

**新設計**:3 波升級 + 確認機制,**確保一定有人接收到並回應**

```
T+0      LINE 給 5 位核心守護人 + 「我會去聯絡他」按鈕
         ↓ 若 15 分鐘內無人確認
T+15     LINE 重發 + SMS(799 用戶)
         ↓ 若 30 分鐘內仍無人確認
T+30     通知所有聯護人(不限核心 5)+ 管理員告警
         ↓ 若任一時刻有人按確認 → 立即終止所有後續
```

---

## 1. State 結構

```python
# state["alerts"][alert_id] = {
#     "alert_id": "alert_<uuid>",
#     "line_user_id": "Uxxxxx",           # 失聯本人
#     "display_name": "...",
#     "trigger": "missed_checkin",        # 未來可能 "manual_sos"
#     "created_at": "ISO8601",
#     "status": "pending" | "confirmed" | "expired" | "auto_cancelled",
#     "confirmed_by": "Uxxxxx" | None,    # 哪個守護人按確認
#     "confirmed_at": "ISO8601" | None,
#     "cancelled_reason": None | "user_checked_in" | "user_cancelled_warning",
#     "waves": [
#         {
#             "wave_number": 1,
#             "scheduled_at": "ISO8601",
#             "sent_at": "ISO8601" | None,
#             "channels": ["line"],
#             "contacts": [
#                 {"line_id": "Uxxxxx", "phone": "09xxxxxxxx", "name": "...", "priority": 1},
#                 ...
#             ],
#             "results": [
#                 {"contact": "Uxxxxx", "channel": "line", "status": "sent", "at": "ISO8601"},
#                 {"contact": "Uxxxxx", "channel": "line", "status": "failed", "error": "...", "at": "ISO8601"},
#             ],
#             "confirmations": [
#                 {"confirmer_line_id": "Uyyyyy", "at": "ISO8601"},
#             ],
#         },
#         {"wave_number": 2, "channels": ["line", "sms"], ...},
#         {"wave_number": 3, "channels": ["line", "sms", "admin_alert"], ...},
#     ],
#     "admin_alerted_at": "ISO8601" | None,
# }
```

### PostgreSQL 對應

```sql
CREATE TABLE alerts (
    id              TEXT PRIMARY KEY,         -- "alert_<uuid>"
    line_user_id    TEXT NOT NULL,
    trigger         TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status          TEXT NOT NULL DEFAULT 'pending',
    confirmed_by    TEXT,
    confirmed_at    TIMESTAMPTZ,
    cancelled_reason TEXT,
    admin_alerted_at TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ NOT NULL,     -- created_at + 30 min
    
    INDEX idx_alerts_status_expires (status, expires_at)
        WHERE status = 'pending',           -- cron 查詢用 partial index
);

CREATE TABLE alert_waves (
    id              BIGSERIAL PRIMARY KEY,
    alert_id        TEXT NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
    wave_number     INT NOT NULL,
    scheduled_at    TIMESTAMPTZ NOT NULL,
    sent_at         TIMESTAMPTZ,
    channels        TEXT[] NOT NULL,
    
    UNIQUE (alert_id, wave_number)
);

CREATE TABLE alert_contacts (
    id              BIGSERIAL PRIMARY KEY,
    alert_id        TEXT NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
    wave_id         BIGINT NOT NULL REFERENCES alert_waves(id) ON DELETE CASCADE,
    contact_line_id TEXT NOT NULL,
    contact_phone   TEXT,
    contact_name    TEXT,
    priority        INT NOT NULL,
    send_status     TEXT,  -- "pending" / "sent" / "failed" / "confirmed"
    confirmed_at    TIMESTAMPTZ,
    error           TEXT,
    
    INDEX idx_alert_contacts_alert (alert_id),
    INDEX idx_alert_contacts_confirmed (alert_id, confirmed_at) WHERE confirmed_at IS NOT NULL,
);

CREATE TABLE admin_alerts (
    id              BIGSERIAL PRIMARY KEY,
    alert_id        TEXT NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
    channel         TEXT NOT NULL,  -- "line" / "email"
    target          TEXT NOT NULL,
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status          TEXT,           -- "sent" / "failed"
    error           TEXT,
);
```

---

## 2. 函式設計

### 2.1 新增函式清單

| 函式 | 用途 | 觸發時機 |
|---|---|---|
| `create_missing_person_alert(data_file, payload, config)` | T+0: 建立 alert,送 wave 1 | `send_due_reminders` 觸發 |
| `confirm_alert(data_file, payload, config)` | 守護人按 Postback 確認 | Postback handler |
| `process_alert_waves(config)` | Cron: 檢查待送的下一波 | 每 1-5 分鐘 |
| `send_alert_wave(alert, wave_number, config)` | 送指定 wave | process_alert_waves 內部呼叫 |
| `cancel_pending_alerts(data_file, line_user_id, reason)` | 使用者簽到/取消 → 自動取消所有 pending alerts | record_checkin / cancel_warning |
| `cleanup_expired_alerts(config)` | 清掉 30 天前的 alerts | cleanup_expired_data 內呼叫 |

### 2.2 `create_missing_person_alert(data_file, payload, config)`

```python
def create_missing_person_alert(data_file, payload, config):
    """
    payload = {
        "line_user_id": "Uxxxxx",
        "trigger": "missed_checkin",
    }
    
    回傳: alert_id
    """
    line_user_id = payload.get("line_user_id")
    state = load_state(data_file)
    profile = state["users"].get(line_user_id)
    
    if not profile:
        return {"error": "user not found"}, 404
    
    # 1. 檢查是否已有 active alert(防止 alert spam)
    for existing_alert in state.get("alerts", {}).values():
        if existing_alert.get("line_user_id") == line_user_id and existing_alert.get("status") == "pending":
            return {"error": "已有進行中的失聯預警", "alert_id": existing_alert["alert_id"]}, 409
    
    # 2. 取 5 位核心守護人(按 priority)
    rules = plan_rules(profile)
    core_limit = int(rules.get("core_guardian_alert_limit") or 5)
    all_contacts = sorted(profile.get("contacts") or [], key=lambda c: int(c.get("priority") or 9999))
    core_contacts = [
        c for c in all_contacts
        if c.get("consent_status") == "accepted" and c.get("line_id")
    ][:core_limit]
    
    if not core_contacts:
        return {"error": "no bound guardians"}, 400
    
    # 3. 建立 alert 記錄
    alert_id = f"alert_{uuid.uuid4().hex[:12]}"
    now = datetime.now()
    alert = {
        "alert_id": alert_id,
        "line_user_id": line_user_id,
        "display_name": profile.get("display_name", ""),
        "trigger": payload.get("trigger", "missed_checkin"),
        "created_at": now.isoformat(timespec="seconds"),
        "status": "pending",
        "confirmed_by": None,
        "confirmed_at": None,
        "expires_at": (now + timedelta(minutes=30)).isoformat(timespec="seconds"),
        "waves": [
            {
                "wave_number": 1,
                "scheduled_at": now.isoformat(timespec="seconds"),
                "sent_at": None,
                "channels": ["line"],
                "contacts": [
                    {"line_id": c["line_id"], "phone": c.get("phone", ""), "name": c.get("name", ""), "priority": int(c.get("priority") or 999)}
                    for c in core_contacts
                ],
                "results": [],
                "confirmations": [],
            },
            {
                "wave_number": 2,
                "scheduled_at": (now + timedelta(minutes=15)).isoformat(timespec="seconds"),
                "sent_at": None,
                "channels": ["line", "sms"],
                "contacts": [...],   # 同上
                "results": [],
                "confirmations": [],
            },
            {
                "wave_number": 3,
                "scheduled_at": (now + timedelta(minutes=30)).isoformat(timespec="seconds"),
                "sent_at": None,
                "channels": ["line", "sms", "admin_alert"],
                "contacts": [        # Wave 3 用所有聯護人
                    {"line_id": c["line_id"], "phone": c.get("phone", ""), "name": c.get("name", ""), "priority": int(c.get("priority") or 999)}
                    for c in sorted(
                        [c for c in all_contacts if c.get("consent_status") == "accepted" and c.get("line_id")],
                        key=lambda c: int(c.get("priority") or 9999),
                    )
                ],
                "results": [],
                "confirmations": [],
            },
        ],
    }
    state.setdefault("alerts", {})[alert_id] = alert
    
    # 4. 立即送 wave 1
    send_alert_wave(alert, 1, config)
    
    save_state(data_file, state)
    return {"alert_id": alert_id, "wave_1_sent": True}, 200
```

### 2.3 `send_alert_wave(alert, wave_number, config)`

```python
def send_alert_wave(alert, wave_number, config):
    """送指定 wave 的通知"""
    wave = next(w for w in alert["waves"] if w["wave_number"] == wave_number)
    state = load_state(config["DATA_FILE"])
    
    # 1. 檢查 alert 是否還 pending(可能已被確認/取消)
    if alert.get("status") != "pending":
        return  # 不送
    
    # 2. 根據 wave 決定訊息強度
    if wave_number == 1:
        message = (
            f"🛡️ 【失聯預警】{alert['display_name'] or '您的親友'} 沒有按時簽到報平安。\n"
            f"請您撥個電話或傳 LINE 給對方確認安全。\n"
            f"如果您已經聯絡到本人,請按下方按鈕讓我們知道。"
        )
    elif wave_number == 2:
        message = (
            f"⚠️ 【緊急】{alert['display_name'] or '您的親友'} 仍未回應簽到,已超過 15 分鐘。\n"
            f"請您立即聯絡本人,或請鄰居/家人協助查看。\n"
            f"如有立即危險,請撥打 119。\n"
            f"如果您已經聯絡到本人,請按下方按鈕。"
        )
    elif wave_number == 3:
        message = (
            f"🚨 【最後通知】{alert['display_name'] or '您的親友'} 已失聯超過 30 分鐘。\n"
            f"請所有親友立即協助查看,或撥打 119。\n"
            f"如已聯絡到本人,請按下方按鈕。"
        )
    
    token = config.get("LINE_CHANNEL_ACCESS_TOKEN")
    sender = config.get("LINE_PUSH_SENDER") or line_push_message
    
    # 3. 對每位聯護人發送
    for contact in wave["contacts"]:
        # LINE
        if "line" in wave["channels"] and contact["line_id"]:
            flex = _build_alert_flex_message(message, alert["alert_id"], wave_number)
            try:
                sender(token, contact["line_id"], flex)
                wave["results"].append({"contact": contact["line_id"], "channel": "line", "status": "sent"})
                _log_line_push(state, "alert_wave", contact["line_id"], f"alert:{alert['alert_id']}/wave:{wave_number}")
            except Exception as exc:
                wave["results"].append({"contact": contact["line_id"], "channel": "line", "status": "failed", "error": str(exc)})
        
        # SMS
        if "sms" in wave["channels"] and contact["phone"]:
            sms_text = message.replace("【失聯預警】", "[失聯預警]").replace("【緊急】", "[緊急]").replace("【最後通知】", "[最後通知]")
            # 簡化 SMS,不含 emoji / 超連結
            result = send_sms(
                phone=contact["phone"],
                message=sms_text,
                user_id=alert["line_user_id"],
            )
            wave["results"].append({"contact": contact["phone"], "channel": "sms", "status": result["status"]})
    
    # 4. Wave 3 額外:admin alert
    if wave_number == 3 and "admin_alert" in wave["channels"]:
        _send_admin_alert(alert, wave, config)
        alert["admin_alerted_at"] = datetime.now().isoformat(timespec="seconds")
    
    # 5. 更新狀態
    wave["sent_at"] = datetime.now().isoformat(timespec="seconds")
    save_state(config["DATA_FILE"], state)
```

### 2.4 `confirm_alert(data_file, payload, config)`

```python
def confirm_alert(data_file, payload, config):
    """
    payload = {
        "alert_id": "alert_xxxxx",
        "confirmer_line_user_id": "Uyyyyy",
    }
    """
    alert_id = payload.get("alert_id")
    confirmer_id = payload.get("confirmer_line_user_id")
    
    state = load_state(data_file)
    alert = state.get("alerts", {}).get(alert_id)
    if not alert:
        return {"error": "alert not found"}, 404
    
    # 1. 檢查 confirmer 是否在 alert 的聯護人名單中
    is_guardian = any(
        c["line_id"] == confirmer_id
        for w in alert["waves"] for c in w["contacts"]
    )
    if not is_guardian:
        return {"error": "not authorized"}, 403
    
    # 2. 標記已確認
    if alert["status"] == "pending":
        alert["status"] = "confirmed"
        alert["confirmed_by"] = confirmer_id
        alert["confirmed_at"] = datetime.now().isoformat(timespec="seconds")
        
        # 3. 對所有 waves 加 confirmation
        for wave in alert["waves"]:
            wave["confirmations"].append({
                "confirmer_line_id": confirmer_id,
                "at": alert["confirmed_at"],
            })
        
        save_state(data_file, state)
        
        # 4. 通知用戶本人(如果他回來看 LINE 會看到)
        _notify_user_confirmed(alert, confirmer_id, config)
        
        # 5. 通知其他守護人「有人接手了」
        _notify_other_guardians_confirmed(alert, confirmer_id, config)
    
    return {"confirmed": True, "confirmed_at": alert["confirmed_at"]}, 200
```

### 2.5 `process_alert_waves(config)`(Cron job)

```python
def process_alert_waves(config):
    """每 1-5 分鐘跑一次,檢查是否有待送的下一波"""
    state = load_state(config["DATA_FILE"])
    now = datetime.now()
    
    for alert in list(state.get("alerts", {}).values()):
        if alert.get("status") != "pending":
            continue
        
        # 找出下一個待送的 wave
        for wave in alert["waves"]:
            if wave["sent_at"] is not None:
                continue
            
            scheduled = parse_datetime(wave["scheduled_at"])
            if scheduled and scheduled <= now:
                # 該送了
                send_alert_wave(alert, wave["wave_number"], config)
                break  # 一輪只送一個 wave
    
    save_state(config["DATA_FILE"], state)
```

### 2.6 `cancel_pending_alerts(data_file, line_user_id, reason)`

```python
def cancel_pending_alerts(data_file, line_user_id, reason):
    """使用者簽到或主動取消 → 取消所有 pending alerts"""
    state = load_state(data_file)
    cancelled = []
    
    for alert_id, alert in state.get("alerts", {}).items():
        if alert.get("line_user_id") == line_user_id and alert.get("status") == "pending":
            alert["status"] = "auto_cancelled"
            alert["cancelled_reason"] = reason
            cancelled.append(alert_id)
    
    save_state(data_file, state)
    return cancelled
```

### 2.7 在既有函式加 hook

#### `record_checkin`(簽到)

```python
def record_checkin(data_file, payload=None):
    # ... 既有邏輯 ...
    
    # 🆕 簽到成功 → 取消所有 pending alerts
    line_user_id = ...
    if is_new_checkin:  # 今天第一次簽到
        cancelled = cancel_pending_alerts(data_file, line_user_id, "user_checked_in")
        if cancelled:
            # 通知所有守護人「已平安」
            for alert_id in cancelled:
                alert = state["alerts"][alert_id]
                _notify_guardians_user_ok(alert, config)
    
    return ...
```

#### `cancel_warning`(使用者按取消預警)

```python
def cancel_warning(data_file, payload=None, config=None):
    # ... 既有邏輯 ...
    
    # 🆕 同時取消對應 alerts
    cancelled = cancel_pending_alerts(data_file, line_user_id, "user_cancelled_warning")
    
    return ...
```

### 2.8 Postback handler(在 `line_callback` 加)

```python
@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    parsed = dict(item.split("=") for item in data.split("&"))
    
    if parsed.get("action") == "alert_confirm":
        confirm_alert(
            app.config["DATA_FILE"],
            {
                "alert_id": parsed.get("alert_id"),
                "confirmer_line_user_id": event.source.user_id,
            },
            app.config,
        )
        # 立即回一個確認訊息給守護人
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="✅ 感謝您!已記錄您的確認,我們會暫停後續通知。如果您聯絡到本人,也歡迎隨時更新狀況。")
        )
    
    elif parsed.get("action") == "alert_status_update":
        # 守護人回報聯絡結果
        # TODO: Phase 2
        pass
    
    # 既有 SOS / consent handlers ...
```

### 2.9 🆕 `_build_alert_flex_message(message, alert_id, wave_number)`

```python
def _build_alert_flex_message(message, alert_id, wave_number):
    """Flex Message with 確認按鈕"""
    urgency_color = {
        1: "#F39C12",   # 橘(警告)
        2: "#E67E22",   # 深橘(緊急)
        3: "#E74C3C",   # 紅(最高)
    }.get(wave_number, "#999999")
    
    return {
        "type": "flex",
        "altText": "🛡️ 失聯預警",
        "contents": {
            "type": "bubble",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": urgency_color,
                "contents": [{
                    "type": "text",
                    "text": "🛡️ 失聯預警" if wave_number == 1 else ("⚠️ 緊急通知" if wave_number == 2 else "🚨 最後通知"),
                    "color": "#FFFFFF",
                    "weight": "bold",
                    "size": "lg",
                }],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": message, "wrap": True, "size": "sm"},
                ],
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "button",
                        "style": "primary",
                        "color": "#2ECC71",
                        "action": {
                            "type": "postback",
                            "label": "✅ 我會去聯絡他",
                            "data": f"action=alert_confirm&alert_id={alert_id}",
                        },
                    },
                    {
                        "type": "button",
                        "style": "secondary",
                        "action": {
                            "type": "uri",
                            "label": "撥打 119",
                            "uri": "tel:119",
                        },
                    },
                ],
            },
        },
    }
```

---

## 3. 路由

### 3.1 新增

```python
@app.post("/api/cron/process-alert-waves")
def cron_alert_waves_api():
    data, code = process_alert_waves(app.config)
    return jsonify(data), code

@app.post("/api/alert/confirm")
def alert_confirm_api():
    """給前端或 API 呼叫(非 Postback)"""
    data, code = confirm_alert(
        app.config["DATA_FILE"],
        request.get_json(silent=True) or {},
        app.config,
    )
    return jsonify(data), code
```

### 3.2 環境變數新增

```python
ALERT_WAVE_2_DELAY_MINUTES = 15       # 可調
ALERT_WAVE_3_DELAY_MINUTES = 30       # 可調
ALERT_AUTO_CANCEL_ON_CHECKIN = True    # 簽到自動取消
ADMIN_LINE_USER_ID = "Uxxxxx"         # 管理員 LINE ID
ADMIN_EMAIL = "alivecheckin.tw@gmail.com"
```

---

## 4. 測試情境

| # | 情境 | 預期 |
|---|---|---|
| 1 | 用戶失聯 → 5 位核心守護人收到 wave 1 LINE + 按鈕 | alert 建立,5 則 LINE 送達 ✅ |
| 2 | Wave 1 送出後 15 分鐘內無人確認 | process_alert_waves cron 送 wave 2(LINE + SMS)✅ |
| 3 | Wave 2 送出後 15 分鐘內無人確認 | 送 wave 3(所有聯護人 + admin alert)✅ |
| 4 | Wave 1 後 5 分鐘,守護人按確認 | alert 標 confirmed,wave 2/3 不送 ✅ |
| 5 | Wave 2 後,守護人按確認 | wave 3 不送 ✅ |
| 6 | 多位守護人同時按確認 | 第一位贏,其他收到「已有人接手」通知 ✅ |
| 7 | 使用者簽到(wave 1 之後) | alert 自動取消,守護人收到「已平安」通知 ✅ |
| 8 | 使用者簽到(wave 3 之後) | alert 自動取消(雖然太遲)✅ |
| 9 | Admin 收到 wave 3 alert | LINE Push + Email 雙送 ✅ |
| 10 | 守護人按確認但不是 alert 的聯護人 | return 403 not authorized ✅ |
| 11 | 同一用戶短時間內 2 次失聯 | 第 2 次 return 409(已有 pending alert)✅ |
| 12 | LINE 發送失敗但 SMS 成功 | 該守護人 SMS 收到 ✅ |
| 13 | 30 分鐘後沒人確認也沒人簽到 | alert 標 expired,保留 30 天後清掉 ✅ |

---

## 5. Migration

- 既有 send_due_reminders 的單次發送邏輯:**保留,但呼叫 create_missing_person_alert 取代**
- 既有 alert 沒有 state["alerts"]:初始為空 dict
- 不影響既有 trigger_sos(獨立流程)

---

## 6. Edge cases

| 情境 | 處理 |
|---|---|
| Cron process_alert_waves 失敗(5 分鐘沒跑)| 下次跑時一次送多個 wave(不會漏) |
| LINE bot webhook 延遲 | alert 狀態最終一致,只是守護人收到確認較慢 |
| 使用者改 plan(降級)期間 alert 在跑 | alert 繼續用建立時的 plan 規則 |
| 守護人刪除 LINE 帳號 | 訊息送不到,status=failed,不影響 alert 流程 |
| 守護人封鎖 Bot | 同上 |
| Cron 跨日執行 | 用 `expires_at` 而非 `now() > scheduled + 24h`,不受影響 |
| Admin LINE 帳號停用 | Email 後備仍送,但 LINE 失敗要 log 警告 |

---

## 7. Commit 順序

```
1. feat(state): alerts state 結構 + PostgreSQL schema
2. feat(alert): create_missing_person_alert + send_alert_wave
3. feat(alert): process_alert_waves cron + /api/cron/process-alert-waves
4. feat(postback): alert_confirm handler + confirm_alert 函式
5. feat(alert): cancel_pending_alerts + 整合到 record_checkin / cancel_warning
6. feat(alert): admin_alert + email 後備
7. test(alert): 13 個情境全綠
```

---

## 8. 開放問題(等蝦董確認)

| # | 問題 | 預設 |
|---|---|---|
| 1 | T+15 / T+30 時長可從 config 調? | ✅ 是 |
| 2 | Wave 3 「所有聯護人」= plan 的 contact_limit? | ✅ 是(預設) |
| 3 | Admin alert 走 LINE Push + Email 雙通道? | ✅ 是 |
| 4 | 同一用戶一天最多 1 個 active alert? | ✅ 是 |
| 5 | Alert 歷史保留 30 天後清理? | ✅ 是 |
| 6 | Wave 2/3 失敗要不要重試? | LINE 3 次、SMS 用 send_sms 內建 retry |
| 7 | 守護人按確認後,是否要發「您是第 N 位確認者」訊息? | 否(只有第一位) |
| 8 | Admin 是否也要能「確認」(代表已聯絡警方)? | Phase 2 |

---

## 9. 變更紀錄

## 10. 守護群整合(蝦董 19:29 欽定補上)

### 10.1 規格確認

| 項目 | 規格 |
|---|---|
| 創建權限 | **僅 799 年費**(`paid_799_year`) |
| 群組數量上限 | **最多 3 個**守護群組 |
| 群組人數上限 | 每群最多 50 人(LINE 群本身限制,DB 不存人數) |
| 預警方式 | **群內 1 條統一群訊息**,不單獨私發給每位成員 |
| 雙重通知開關 | 799 用戶可選「5 核心 + 守護群」/「只守護群」/「只 5 核心」 |
| 年費到期 | Bot **不會自動退群**,僅停止推送,續費後立即恢復 |

### 10.2 與 3 波的整合

| Wave | 對象 |
|---|---|
| Wave 1 (T+0) | **5 位核心聯護人(個別 LINE)+ 守護群(1 條群訊息)** |
| Wave 2 (T+15) | **5 位核心聯護人(個別 LINE 重發)+ 守護群(1 條群訊息)** |
| Wave 3 (T+30) | **所有聯護人(個別 LINE)+ 守護群(1 條群訊息)+ 管理員告警** |

### 10.3 State 變更

```python
# profile 新欄位
profile["guardian_group_notification_enabled"] = True   # 🆕 預設 True
profile["core_contact_in_group_mode"] = "both"          # 🆕 "both" / "group_only" / "individual_only"

# alert.wave 新欄位
wave["guardian_group_targets"] = [
    {"group_id": "Cxxxxx", "name": "家人群"},
    ...
]
wave["guardian_group_results"] = [
    {"group_id": "Cxxxxx", "status": "sent", "at": "ISO8601"},
    {"group_id": "Cyyyyy", "status": "failed", "error": "..."},
]
```

### 10.4 新增函式

```python
def _send_alert_to_guardian_groups(alert, wave_number, config):
    """
    送 1 條統一群訊息到每個 active 守護群
    - 用 LINE Group API 的 push_message(group_id, ...)
    - 每群 1 條訊息(不是每位成員 1 條)
    - 含 Flex Message + ✅ 我會去聯絡他 postback 按鈕
    """


def _is_guardian_group_eligible(profile, plan_rules):
    """
    檢查 plan 是否啟用守護群 + 用戶開啟通知 + 年費有效
    """
    return (
        profile.get("guardian_group_notification_enabled", True)
        and plan_rules.get("guardian_group_limit", 0) > 0
        and profile.get("plan") == "paid_799_year"
        and paid_membership_is_active(profile)
    )


def _get_active_guardian_groups(state, profile):
    """
    取用戶所有 active 守護群
    """
    return [
        {"group_id": gid, "name": state["guardian_groups"][gid].get("name", "")}
        for gid in (profile.get("guardian_group_ids") or [])
        if state.get("guardian_groups", {}).get(gid, {}).get("status") == "active"
    ]


def _build_alert_group_message(alert_id, wave_number, display_name):
    """守護群訊息 Flex Message(同 §2.9,但用 group 顏色)"""
```

### 10.5 群訊息範本

**Wave 1 群訊息**:
```
🛡️ 【失聯預警】家人/朋友 {name} 沒有按時簽到報平安。
請大家協助撥個電話或傳 LINE 給對方確認安全。
如已聯絡到本人,請按下方按鈕。
```

**Wave 2 群訊息**:
```
⚠️ 【緊急】家人/朋友 {name} 仍未回應簽到,已超過 15 分鐘。
請大家立即聯絡本人,或請鄰居/家人協助查看。
如有立即危險,請撥打 119。
如已聯絡到本人,請按下方按鈕。
```

**Wave 3 群訊息**:
```
🚨 【最後通知】家人/朋友 {name} 已失聯超過 30 分鐘。
請所有群成員立即協助查看,或撥打 119。
如已聯絡到本人,請按下方按鈕。
```

### 10.6 群 Postback 確認邏輯

```python
# 在 line_callback 加
@handler.add(PostbackEvent)
def handle_postback(event):
    parsed = parse_postback_data(event.postback.data)
    
    if parsed.get("action") == "alert_confirm":
        source_type = getattr(event.source, "type", "user")  # "user" / "group" / "room"
        source_group_id = getattr(event.source, "group_id", None)
        
        confirm_alert(
            app.config["DATA_FILE"],
            {
                "alert_id": parsed.get("alert_id"),
                "confirmer_line_user_id": event.source.user_id,
                "confirm_source": source_type,  # "individual" / "group"
                "confirm_group_id": source_group_id,
            },
            app.config,
        )
```

### 10.7 `confirm_alert` 改寫:支援群組驗證

```python
def confirm_alert(data_file, payload, config):
    alert_id = payload.get("alert_id")
    confirmer_id = payload.get("confirmer_line_user_id")
    confirm_source = payload.get("confirm_source", "individual")
    confirm_group_id = payload.get("confirm_group_id")
    
    state = load_state(data_file)
    alert = state.get("alerts", {}).get(alert_id)
    if not alert:
        return {"error": "alert not found"}, 404
    
    # 驗證:confirmer 必須在 alert 對象名單內
    is_authorized = False
    
    if confirm_source == "group" and confirm_group_id:
        # 群組成員按確認:確認該群是否在 alert 對象中
        for wave in alert["waves"]:
            if any(g["group_id"] == confirm_group_id for g in wave.get("guardian_group_targets", [])):
                is_authorized = True
                break
    else:
        # 個人按確認:確認是核心/所有聯護人之一
        for wave in alert["waves"]:
            if any(c["line_id"] == confirmer_id for c in wave.get("contacts", [])):
                is_authorized = True
                break
    
    if not is_authorized:
        return {"error": "not authorized"}, 403
    
    # ... 既有確認邏輯(標 confirmed + 通知)
```

### 10.8 去重邏輯(避免重複通知)

如果某個 LINE User 同時是「5 位核心之一」+「守護群成員」,**不能重複發送**:

```python
def _dedupe_alert_recipients(wave):
    """
    回傳去重後的發送清單
    """
    sent_user_ids = set()
    deduped_contacts = []
    
    for contact in wave.get("contacts", []):
        if contact["line_id"] in sent_user_ids:
            continue  # 已發過個人訊息
        deduped_contacts.append(contact)
        sent_user_ids.add(contact["line_id"])
    
    wave["deduped_contacts"] = deduped_contacts
    return deduped_contacts
```

**群訊息發送邏輯**:LINE Group API 是 `push_message(group_id, ...)`,發送給**整個群**;即使群裡有 50 人,也只算 1 個 LINE Push(計入配額)。LINE 自己在群裡面對 50 個用戶,所以**使用者端**只看到 1 條群訊息。

### 10.9 年費到期的處理

```python
def _should_send_to_guardian_groups(profile, plan_rules):
    """年費到期 → 不送群訊息,但不退群"""
    if not _is_guardian_group_eligible(profile, plan_rules):
        return False
    
    # 額外檢查:年費是否仍然有效
    paid_until = parse_datetime(profile.get("paid_until"))
    if paid_until and paid_until < datetime.now():
        # 年費到期:Bot 不退群,但停送
        return False
    
    return True
```

### 10.10 守護群測試情境(新增 9 個)

| # | 情境 | 預期 |
|---|---|---|
| 1 | 799 用戶有 1 個守護群 → 失聯 → Wave 1 | 5 核心收 LINE + 群收 1 條群訊息 ✅ |
| 2 | 群成員按確認(在群訊息按按鈕)| alert resolved ✅ |
| 3 | 多個群成員同時按確認 | 第一位贏 ✅ |
| 4 | 5 位核心中某人也在守護群內 | 不重複發(去重邏輯) ✅ |
| 5 | 199 用戶有守護群(PLAN_LIMITS 防呆)| 不送群訊息 ✅ |
| 6 | 守護群被刪除/封鎖/owner 退群 | 該群 status=failed,繼續送其他群 ✅ |
| 7 | 守護群 owner 年費到期 | Bot 不退群,但所有 wave 不送群訊息 ✅ |
| 8 | 守護群 owner 續費成功 | 下一波恢復群訊息 ✅ |
| 9 | 群訊息 + 個人訊息,個人先確認 | 群訊息不再送(連鎖 cancel)✅ |

### 10.11 Migration

- 既有 `guardian_groups` state + `guardian_group_ids` profile 欄位:**不變**
- 新加 `guardian_group_notification_enabled`(預設 True,既有 799 用戶會自動開啟)
- 新加 `core_contact_in_group_mode`(預設 "both",既有行為)

### 10.12 Commit 順序補上

```
8. feat(guardian-group): 守護群年費資格 + notification_enabled
9. feat(alert): create_missing_person_alert 加守護群 targets
10. feat(alert): send_alert_wave 加 _send_alert_to_guardian_groups
11. feat(alert): confirm_alert 支援群組驗證 + 去重邏輯
12. test(guardian-group): 9 個新測試情境全綠
```

---

## 11. 蝦董 19:29 4 點實作細節(欽定)

1. **時間計算採「T+0 後 X 分鐘」絕對時間**,**不依賴發送成功與否**
   - 含意:即使 wave 1 送出失敗,T+15 仍然送 wave 2(不看 wave 1 結果)
   - 實作:`scheduled_at = created_at + 15min`(絕對值),process_alert_waves 看現在時間對比
2. **Wave 2/3 訊息範本採遞增語氣版本**(已寫在 §2.3.4)
3. **同用戶一天最多 1 個 active alert**(已確認)
4. **使用者補簽到 → 自動取消所有 pending alerts + 通知守護人「已平安」**(已寫在 §2.6)

---

## 12. 變更紀錄

| 版本 | 日期 | 作者 | 變更 |
|---|---|---|---|
| v0.4 | 2026-07-17 19:06 | 小龍蝦 | 初版:5 點設計完整實作 + state + 13 個測試情境 |
| v0.4 + §10 | 2026-07-17 19:29 | 小龍蝦 | 🆕 守護群功能整合:9 個新測試 + 群 Postback + 去重 |
| v0.4 + §11 | 2026-07-17 19:29 | 小龍蝦 | 🆕 4 點實作細節(時間計算、語氣、自動取消) |