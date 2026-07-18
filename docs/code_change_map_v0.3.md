# Code Change Map v0.3 — 3 個 P0 Bug 實作計畫

> **狀態**:Draft v0.3(從 v0.2 補上「實作方式」)
> **建立日期**:2026-07-17 18:38
> **作者**:小龍蝦
> **目的**:把 v0.2 識別的 3 個 P0 bug 寫成「可開工」的程式碼藍圖

---

## 0. 摘要

| Bug | 嚴重度 | 預估工作量 | commit 順序 |
|---|---|---|---|
| #1 `bind_emergency_contact` 雙重同意 | 🔴 個資法 | 4-6 小時 | 第 1 個 |
| #2 `trigger_sos` 3 層防護 | 🔴 安全 + UX | 6-8 小時 | 第 2 個 |
| #3 `send_due_reminders` 實際送 SMS | 🔴 合約違約 | 3-4 小時 | 第 3 個 |
| **總計** | | **13-18 小時** | 約 2 個工作天 |

**每個 bug 拆 4 個段落**:
1. **State / Schema 變更** — JSON 新欄位 / DB 新表
2. **函式改寫藍圖** — 偽代碼級別
3. **測試情境** — 至少 5 個
4. **Migration / Edge cases** — 老用戶怎麼辦

---

# 🐛 Bug #1: `bind_emergency_contact` 雙重同意

## 1.1 現狀 vs 目標

| 階段 | 現狀 | 目標 |
|---|---|---|
| 用戶邀請 | `consent_status: "accepted"` 🐛 | `consent_status: "pending"` |
| 守護人收到 | 簡訊「測試提醒」 | Flex Message「是否同意成為緊急聯絡人」+ 同意/拒絕按鈕 |
| 守護人按同意 | N/A | `consent_status: "accepted"` + 通知邀請方 |
| 守護人按拒絕 | N/A | 從 contacts 移除 + 通知邀請方 |
| 7 天未回應 | N/A | 自動標 expired + 從 contacts 移除 |

## 1.2 State 變更

```python
# profile.contacts[] 新欄位(已有,但預設值改了)
contact = {
    ...
    "consent_status": "pending",        # 🐛 從 "accepted" 改成 "pending"
    "consent_invited_at": None,         # 🆕 ISO8601
    "consent_responded_at": None,       # 🆕 ISO8601
    "consent_expires_at": None,         # 🆕 ISO8601, 7 天後過期
}

# 🆕 state 全域:追蹤所有 pending 的邀請(快速查找用)
state["consent_pending"] = {
    "<contact_line_user_id>": {
        "inviter_line_user_id": "...",
        "invited_at": "ISO8601",
        "expires_at": "ISO8601",
    },
    ...
}
```

**PostgreSQL 對應**:
- `contact.consent_status` 加 index(查詢過濾 pending 用)
- `consent_pending` 拆成獨立 table(Join 查詢)

## 1.3 函式改寫藍圖

### 1.3.1 `bind_emergency_contact` 改寫

```python
def bind_emergency_contact(data_file, payload, config=None):
    inviter_id = ...
    contact_line_user_id = ...
    
    state = load_state(data_file)
    inviter = get_profile(state, inviter_id)
    contact_user = get_profile(state, contact_line_user_id)
    
    # 1. 檢查是否已綁定 + 檢查上限
    contacts = list(inviter.get("contacts") or [])
    existing = next((c for c in contacts if c.get("line_id") == contact_line_user_id), None)
    
    if existing:
        if existing.get("consent_status") == "accepted":
            return {"already_bound": True, "consent_status": "accepted"}, 200
        # pending → 重發邀請
    else:
        limit = plan_rules(inviter)["contact_limit"]
        if len([c for c in contacts if c.get("consent_status") == "accepted"]) >= limit:
            return {"error": f"contact_limit exceeded: {limit}"}, 400
        # append 新 contact (consent_status="pending")
        contacts.append({
            "id": f"line-{contact_line_user_id}",
            "name": contact_display_name,
            "relationship": "受邀緊急聯絡人",
            "phone": "",
            "line_id": contact_line_user_id,
            "email": "",
            "notify_methods": ["line"],
            "priority": len(contacts) + 1,
            "consent_status": "pending",          # 🐛 改了
            "consent_invited_at": now_iso(),
            "consent_expires_at": now_plus_7d_iso(),
            "note": "LINE 一鍵授權綁定",
        })
    
    # 2. 寫入 state["consent_pending"]
    state.setdefault("consent_pending", {})[contact_line_user_id] = {
        "inviter_line_user_id": inviter_id,
        "invited_at": now_iso(),
        "expires_at": now_plus_7d_iso(),
    }
    
    # 3. 🆕 發 LINE Flex Message 邀請(取代原本的「測試提醒」)
    if config and token:
        _send_consent_invite_flex(
            token,
            contact_line_user_id,
            inviter.get("display_name") or "有人",
        )
    
    save_state(data_file, state)
    return {"pending": True, "expires_at": now_plus_7d_iso()}, 200
```

### 1.3.2 🆕 `_send_consent_invite_flex(token, contact_line_id, inviter_name)`

```python
def _send_consent_invite_flex(token, contact_line_id, inviter_name):
    flex_message = {
        "type": "flex",
        "altText": f"{inviter_name} 想加你為緊急聯絡人",
        "contents": {
            "type": "bubble",
            "header": {
                "type": "box",
                "layout": "vertical",
                "contents": [{
                    "type": "text",
                    "text": "🛡️ 緊急聯絡人邀請",
                    "weight": "bold",
                    "size": "lg",
                }],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": f"{inviter_name} 想加你為緊急聯絡人。"},
                    {"type": "text", "text": " ", "size": "sm"},
                    {"type": "text", "text": "如果對方沒有按時簽到,系統會通知你。這不代表任何財務責任。", "wrap": True, "size": "sm", "color": "#666666"},
                ],
            },
            "footer": {
                "type": "box",
                "layout": "horizontal",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "button",
                        "style": "primary",
                        "color": "#2ECC71",
                        "action": {
                            "type": "postback",
                            "label": "同意",
                            "data": f"action=consent_response&response=accept",
                        },
                    },
                    {
                        "type": "button",
                        "style": "secondary",
                        "action": {
                            "type": "postback",
                            "label": "拒絕",
                            "data": f"action=consent_response&response=decline",
                        },
                    },
                ],
            },
        },
    }
    LineBotApi(token).push_message(contact_line_id, flex_message)
```

### 1.3.3 🆕 `process_consent_response(data_file, payload, config)`

```python
def process_consent_response(data_file, payload, config):
    """
    payload = {
        "contact_line_user_id": "Uxxxxx",  # 守護人
        "response": "accept" | "decline",
        # inviter_line_user_id 從 state["consent_pending"] 查
    }
    """
    contact_line_user_id = payload.get("contact_line_user_id")
    response = payload.get("response")
    
    state = load_state(data_file)
    pending = state.get("consent_pending", {}).get(contact_line_user_id)
    if not pending:
        return {"error": "no pending consent"}, 404
    
    inviter_id = pending["inviter_line_user_id"]
    inviter = state["users"].get(inviter_id)
    
    # 從 consent_pending 移除
    del state["consent_pending"][contact_line_user_id]
    
    if response == "accept":
        # 更新 contact.consent_status
        for contact in inviter.get("contacts", []):
            if contact.get("line_id") == contact_line_user_id:
                contact["consent_status"] = "accepted"
                contact["consent_responded_at"] = now_iso()
                break
        
        # 通知邀請方
        _send_line_push(token, inviter_id, f"✅ {contact_display_name} 已同意成為你的緊急聯絡人。")
    
    elif response == "decline":
        # 從 inviter.contacts 移除
        inviter["contacts"] = [
            c for c in inviter.get("contacts", [])
            if c.get("line_id") != contact_line_user_id
        ]
        
        # 通知邀請方
        _send_line_push(token, inviter_id, f"ℹ️ {contact_display_name} 已拒絕你的邀請。")
    
    save_state(data_file, state)
    return {"success": True, "consent_status": "accepted" if response == "accept" else "removed"}
```

### 1.3.4 🆕 `/api/consent/respond` 路由

```python
@app.post("/api/consent/respond")
def consent_respond_api():
    data, code = process_consent_response(
        app.config["DATA_FILE"],
        request.get_json(silent=True) or {},
        app.config,
    )
    return jsonify(data), code
```

### 1.3.5 🆕 LINE Bot postback handler(在 `line_callback` 加)

```python
@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    parsed = dict(item.split("=") for item in data.split("&"))
    if parsed.get("action") == "consent_response":
        process_consent_response(
            app.config["DATA_FILE"],
            {
                "contact_line_user_id": event.source.user_id,
                "response": parsed.get("response"),
            },
            app.config,
        )
```

### 1.3.6 🆕 7 天過期清理(在 `cleanup_expired_data` 加)

```python
def cleanup_expired_data(config):
    # 既有清理邏輯
    ...
    
    # 🆕 清理過期的 consent_pending
    now = current_app_time(config)
    state = load_state(config["DATA_FILE"])
    expired = [
        cid for cid, info in state.get("consent_pending", {}).items()
        if parse_datetime(info.get("expires_at")) and parse_datetime(info["expires_at"]) < now
    ]
    for cid in expired:
        pending_info = state["consent_pending"][cid]
        inviter_id = pending_info["inviter_line_user_id"]
        inviter = state["users"].get(inviter_id, {})
        inviter["contacts"] = [
            c for c in inviter.get("contacts", [])
            if c.get("line_id") != cid
        ]
        del state["consent_pending"][cid]
        # 通知邀請方
        _send_line_push(
            token,
            inviter_id,
            f"⏰ 您的緊急聯絡人邀請已過期(7 天未回應)。請重新邀請。",
        )
    save_state(config["DATA_FILE"], state)
```

## 1.4 測試情境

| # | 情境 | 預期 |
|---|---|---|
| 1 | A 邀請 B → B 收到 Flex → B 按同意 | B.consent_status=accepted,A 收到通知 ✅ |
| 2 | A 邀請 B → B 收到 Flex → B 按拒絕 | B 從 A.contacts 移除,A 收到通知 ✅ |
| 3 | A 邀請 B → B 7 天未回應 | 自動移除,通知 A ✅ |
| 4 | A 邀請 B(已綁)→ 系統跳過邀請,回 `already_bound` | ✅ |
| 5 | A 邀請 B(pending 狀態)→ 重發邀請,token 不變 | ✅ |
| 6 | A 邀請 C(已達方案上限)→ 回 `contact_limit exceeded` | ✅ |
| 7 | B 在 A 處為 pending,但 B 也是另一用戶 D 的核心守護人 | 不衝突,各自獨立 ✅ |
| 8 | A 觸發預警,B 還是 pending | 預警不發給 B(complete_guardian_contact False) ✅ |
| 9 | LINE push 失敗(token 過期) | 寫 log,return error,但不擋流程 ✅ |

## 1.5 Migration

- 既有 `consent_status: "accepted"` 的聯絡人:**保持原狀**(已經同意過了)
- 新加 `consent_invited_at` / `consent_responded_at` 預設 = bind 當下時間
- `consent_pending` 對老用戶來說是空 `{}`,不影響

## 1.6 Edge cases

- 守護人刪除 LINE 帳號 → 7 天過期自動清理
- 守護人封鎖 Bot → 訊息送不到,但 `consent_pending` 仍記錄,等 7 天過期
- 用戶在 7 天內解除綁定 → 直接從 contacts 移除,同時清掉 consent_pending

---

# 🐛 Bug #2: `trigger_sos` 3 層防護

## 2.1 現狀 vs 目標

| 機制 | 現狀 | 目標 |
|---|---|---|
| 5 秒內可取消 | ❌ | ✅ pending token + expires_at |
| 每日上限 3 次 | ❌ | ✅ sos_daily_count + 跨日重置 |
| 5 分鐘冷卻 | ❌ | ✅ sos_last_attempt_at + 5min check |
| 799 發 SMS | ❌ | ✅ 對 SMS 守護人 call `send_sms` |
| 超限引導 119 | ❌ | ✅ 回「請撥打 119」訊息 |
| 超限 admin alert | ❌ | ✅ 後台收到 alert |

## 2.2 State 變更

```python
profile = {
    ...
    # 🆕 SOS 3 層防護狀態
    "sos_daily_count": 0,           # 當日觸發次數(過 00:00 重置)
    "sos_last_reset_date": None,    # 上次重置日期(YYYY-MM-DD)
    "sos_last_attempt_at": None,    # 上次嘗試時間(ISO8601)
    "sos_today_history": [],       # 當日詳細歷史 [{at, status: sent/cancelled/denied/expired, recipients: int}]
    "sos_pending": None,            # 待確認的 SOS
        # 或 = {
        #     "token": "uuid",
        #     "expires_at": "ISO8601",
        #     "message_preview": "...",
        # }
}
```

## 2.3 函式改寫藍圖

### 2.3.1 整體架構

```
現有 trigger_sos (L968-1058) 🐛 整個砍掉

取代為 3 個新函式:
  trigger_sos_pending() → 發 5 秒確認
  confirm_sos_send()    → 真的送
  cancel_sos_pending()  → 取消
```

### 2.3.2 🆕 `trigger_sos_pending(data_file, payload, config)`

```python
def trigger_sos_pending(data_file, payload, config):
    line_user_id = payload.get("line_user_id")
    state = load_state(data_file)
    profile = state["users"].get(line_user_id)
    
    # 1. 方案檢查(399/799 才有 SOS)
    rules = plan_rules(profile)
    if not rules.get("sos_enabled"):
        return {"error": "sos is not available for this plan"}, 403
    
    # 2. 每日上限檢查
    allowed, count = _check_sos_daily_limit(profile, limit=3)
    if not allowed:
        # 觸發 admin alert(寫 log)
        append_notification_log(state, "sos_overlimit_alert", "admin", 
                                 "sent", f"用戶 {line_user_id} 今日已 {count} 次 SOS,請關懷", "")
        return {
            "error": "daily_limit_reached",
            "message": "您今日的 SOS 緊急求救次數已達上限(3 次)。若您真的需要協助,請直接撥打 119 或聯絡您的緊急聯絡人。明日 00:00 後將恢復 SOS 功能。",
        }, 429
    
    # 3. 冷卻檢查
    allowed, last = _check_sos_cooldown(profile, minutes=5)
    if not allowed:
        last_minutes_ago = (datetime.now() - parse_datetime(last)).total_seconds() / 60
        return {
            "error": "cooldown",
            "message": f"請於 5 分鐘後再試(上次嘗試:{last_minutes_ago:.1f} 分鐘前)",
        }, 429
    
    # 4. 產生 pending token
    token = str(uuid.uuid4())
    expires_at = (datetime.now() + timedelta(seconds=5)).isoformat(timespec="seconds")
    
    # 5. 寫入 profile["sos_pending"]
    profile["sos_pending"] = {
        "token": token,
        "expires_at": expires_at,
        "message_preview": "🆘 SOS 緊急求救 — 點擊下方「確認送出」立即通知所有守護人",
    }
    profile["sos_last_attempt_at"] = datetime.now().isoformat(timespec="seconds")
    
    # 6. 發 LINE 確認訊息給用戶本人(用 Quick Reply)
    token_esc = config.get("LINE_CHANNEL_ACCESS_TOKEN")
    sender = config.get("LINE_PUSH_SENDER") or line_push_message
    if token_esc:
        confirm_flex = _build_sos_confirm_flex(expires_at=expires_at)
        sender(token_esc, line_user_id, [confirm_flex])
    
    save_state(data_file, state)
    return {
        "pending": True,
        "token": token,
        "expires_at": expires_at,
        "count_after": count + 1,  # 確認後會變這樣
    }, 200
```

### 2.3.3 🆕 `confirm_sos_send(data_file, payload, config)`

```python
def confirm_sos_send(data_file, payload, config):
    line_user_id = payload.get("line_user_id")
    state = load_state(data_file)
    profile = state["users"].get(line_user_id)
    
    pending = profile.get("sos_pending")
    if not pending:
        return {"error": "no pending SOS"}, 404
    
    # 1. 驗證 token
    if payload.get("token") != pending["token"]:
        return {"error": "invalid token"}, 403
    
    # 2. 驗證沒過期
    expires = parse_datetime(pending["expires_at"])
    if datetime.now() > expires:
        # 過期 → 視為取消
        profile["sos_pending"] = None
        _record_sos_attempt(profile, "expired", 0)
        save_state(data_file, state)
        return {"error": "expired"}, 410
    
    # 3. 過 daily limit 檢查(雙重保險)
    allowed, count = _check_sos_daily_limit(profile, limit=3)
    if not allowed:
        return {"error": "daily_limit_reached"}, 429
    
    # 4. 組裝訊息(原有邏輯)
    rules = plan_rules(profile)
    limit = int(rules.get("core_guardian_alert_limit") or 1)
    contacts = sorted(profile.get("contacts") or [], key=lambda c: int(c.get("priority") or 9999))
    
    location = profile.get("location") or {}
    location_text = ""
    if location.get("latitude") is not None:
        # ... (原有邏輯)
        pass
    line_message = f"【SOS 緊急求助】{...} 發出緊急求助,請立即聯絡本人並確認安全。若有立即危險,請撥打 119。{location_text}"
    
    # 5. LINE 守護人(原有邏輯)
    token = config["LINE_CHANNEL_ACCESS_TOKEN"]
    sender = config.get("LINE_PUSH_SENDER") or line_push_message
    line_contacts = [c for c in contacts if c.get("line_id") and "line" in (c.get("notify_methods") or ["line"])][:limit]
    line_sent = 0
    line_failed = 0
    for contact in line_contacts:
        try:
            sender(token, contact["line_id"], line_message)
            line_sent += 1
        except Exception as exc:
            line_failed += 1
            append_notification_log(state, "sos", contact["line_id"], "failed", line_message, str(exc))
    
    # 6. 🆕 SMS 守護人(對 799 用戶,phone 有填,plan 有 sms)
    sms_sent = 0
    sms_skipped = 0
    if "sms" in rules.get("channels", []):
        sms_contacts = [c for c in contacts[:limit] if c.get("phone") and "sms" in (c.get("notify_methods") or [])]
        sms_message = line_message.replace("【SOS 緊急求助】", "[SOS]")  # SMS 簡化版,不加 emoji / 超連結
        for contact in sms_contacts:
            result = send_sms(  # ← Task #2 的函式
                phone=contact["phone"],
                message=sms_message,
                user_id=line_user_id,
            )
            if result["success"]:
                sms_sent += 1
            else:
                sms_skipped += 1
                append_notification_log(state, "sos_sms", contact["phone"], result["status"], sms_message, result.get("reason"))
    
    # 7. 🆕 守護群(原有邏輯)
    group_sent = 0
    group_failed = 0
    # ... (原有 guardian_group_ids 邏輯)
    
    # 8. 更新狀態
    profile["sos_pending"] = None
    profile["sos_daily_count"] = count + 1
    profile["sos_last_reset_date"] = today_string()
    _record_sos_attempt(profile, "sent", line_sent + sms_sent + group_sent)
    
    save_state(data_file, state)
    return {
        "sent": line_sent + sms_sent,
        "line_sent": line_sent,
        "sms_sent": sms_sent,
        "group_sent": group_sent,
        "failed": line_failed + group_failed + sms_skipped,
    }, 200
```

### 2.3.4 🆕 `cancel_sos_pending(data_file, payload, config)`

```python
def cancel_sos_pending(data_file, payload, config):
    line_user_id = payload.get("line_user_id")
    state = load_state(data_file)
    profile = state["users"].get(line_user_id)
    
    pending = profile.get("sos_pending")
    if not pending:
        return {"success": True, "already_cancelled": True}
    
    profile["sos_pending"] = None
    _record_sos_attempt(profile, "cancelled", 0)
    
    save_state(data_file, state)
    return {"success": True, "cancelled": True}, 200
```

### 2.3.5 🆕 Helper 函式

```python
def _check_sos_daily_limit(profile, limit=3):
    """跨日重置 + 計數"""
    today = today_string()
    last_reset = profile.get("sos_last_reset_date")
    if last_reset != today:
        # 跨日 → 重置
        profile["sos_daily_count"] = 0
        profile["sos_last_reset_date"] = today
        profile["sos_today_history"] = []
        return (True, 0)
    
    count = profile.get("sos_daily_count", 0)
    return (count < limit, count)


def _check_sos_cooldown(profile, minutes=5):
    last = profile.get("sos_last_attempt_at")
    if not last:
        return (True, None)
    last_dt = parse_datetime(last)
    if not last_dt:
        return (True, None)
    elapsed = (datetime.now() - last_dt).total_seconds() / 60
    return (elapsed >= minutes, last)


def _record_sos_attempt(profile, status, recipients):
    history = profile.get("sos_today_history", [])
    history.append({
        "at": datetime.now().isoformat(timespec="seconds"),
        "status": status,  # "sent" / "cancelled" / "expired" / "denied"
        "recipients": recipients,
    })
    profile["sos_today_history"] = history[-10:]  # 只保留最近 10 筆


def _build_sos_confirm_flex(expires_at):
    """Flex Message with 確認 / 取消 按鈕"""
    return {
        "type": "flex",
        "altText": "🆘 SOS 確認",
        "contents": {
            "type": "bubble",
            "header": {"type": "text", "text": "🆘 SOS 緊急求救", "weight": "bold", "color": "#E74C3C"},
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "⚠️ 您已請求發送 SOS 緊急求救。", "wrap": True},
                    {"type": "text", "text": " ", "size": "sm"},
                    {"type": "text", "text": "5 秒內可取消。過期將自動取消。", "wrap": True, "color": "#666666", "size": "sm"},
                ],
            },
            "footer": {
                "type": "box",
                "layout": "horizontal",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "button",
                        "style": "primary",
                        "color": "#E74C3C",
                        "action": {
                            "type": "postback",
                            "label": "立即確認",
                            "data": "action=sos_confirm",
                        },
                    },
                    {
                        "type": "button",
                        "style": "secondary",
                        "action": {
                            "type": "postback",
                            "label": "取消",
                            "data": "action=sos_cancel",
                        },
                    },
                ],
            },
        },
    }
```

### 2.3.6 🆕 路由

```python
@app.post("/api/sos/pending")
def sos_pending_api():
    data, code = trigger_sos_pending(app.config["DATA_FILE"], request.get_json(silent=True) or {}, app.config)
    return jsonify(data), code

@app.post("/api/sos/confirm")
def sos_confirm_api():
    data, code = confirm_sos_send(app.config["DATA_FILE"], request.get_json(silent=True) or {}, app.config)
    return jsonify(data), code

@app.post("/api/sos/cancel")
def sos_cancel_api():
    data, code = cancel_sos_pending(app.config["DATA_FILE"], request.get_json(silent=True) or {}, app.config)
    return jsonify(data), code
```

### 2.3.7 🆕 Postback handler(在 `line_callback` 加)

```python
@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    parsed = dict(item.split("=") for item in data.split("&"))
    
    if parsed.get("action") == "sos_confirm":
        confirm_sos_send(app.config["DATA_FILE"], {"line_user_id": event.source.user_id}, app.config)
    elif parsed.get("action") == "sos_cancel":
        cancel_sos_pending(app.config["DATA_FILE"], {"line_user_id": event.source.user_id}, app.config)
    elif parsed.get("action") == "consent_response":
        process_consent_response(...)
```

## 2.4 測試情境

| # | 情境 | 預期 |
|---|---|---|
| 1 | 用戶點 SOS → 收到 Flex → 5 秒內按確認 | 守護人收到 LINE(+ 799 用戶收到 SMS) ✅ |
| 2 | 用戶點 SOS → 5 秒內按取消 | 不送,寫 cancelled ✅ |
| 3 | 用戶點 SOS → 5 秒內無動作 → 過期 | 自動取消,寫 expired ✅ |
| 4 | 用戶點 SOS → 每日第 4 次 | 收到「已達上限,請撥打 119」+ admin 收到 alert ✅ |
| 5 | 用戶點 SOS → 5 分鐘內第 2 次 | 收到「冷卻中」訊息 ✅ |
| 6 | 跨日 00:00 後 | sos_daily_count 自動重置為 0 ✅ |
| 7 | 399 用戶點 SOS | LINE 守護人收到(沒 SMS) ✅ |
| 8 | 799 用戶點 SOS | LINE + SMS 都送 ✅ |
| 9 | 守護人為 pending 狀態(未同意) | 不送(complete_guardian_contact False) ✅ |
| 10 | LINE token 過期 | 寫 log,return error,sos_daily_count 仍 +1(意圖觸發算) ✅ |

## 2.5 Migration

- 既有用戶加新欄位:`sos_daily_count=0, sos_last_reset_date=today, sos_today_history=[], sos_pending=None`
- 不影響既有 `trigger_sos` 行為(函式整個砍掉)
- 但短期內會有「user 點 Rich Menu SOS 沒反應」— **部署前要先在 LINE OA Manager 把 SOS 按鈕 disable**

## 2.6 Edge cases

- 多用戶同時點(併發) → sos_pending token 鎖定
- LINE push 失敗 → 仍記 daily count(因為意圖觸發了)
- 用戶點 SOS 後斷網 → 5 秒後前端 UI 自動取消,後端過期記 expired
- token 過期但用戶還按確認 → return 410 expired
- admin 收到 alert 但 alert 也是 LINE push → 配額計算要排除 admin

---

# 🐛 Bug #3: `send_due_reminders` 實際送 SMS

## 3.1 現狀 vs 目標

| 階段 | 現狀 | 目標 |
|---|---|---|
| 對 LINE 守護人 | ✅ 真的送 | ✅ 維持 |
| 對 SMS 守護人 | 🐛 **只 log pending**(L1454-1456)| ✅ 真的送 `send_sms()` |
| 對 Phone 守護人 | 🐛 只 log pending | ⏸️ 延後(等需求) |
| LINE 配額追蹤 | ❌ | ✅ 全局 + per-user |
| 連續預警降頻 | ❌ | ✅ 1/2/3 不同強度 |
| 旅遊模式 | ❌ | ✅ skip |

## 3.2 State 變更

- 用既有 `outbound_sms_log` 表(Task #2 SMS 通道的 schema)
- 新加 `line_push_log` 表(LINE Push 配額追蹤)
- 用戶加 `travel_mode_enabled`, `travel_mode_started_at`, `travel_mode_expires_at`(已加在 DEFAULT_PROFILE)

## 3.3 函式改寫藍圖

### 3.3.1 `send_due_reminders(config)` 改寫

```python
def send_due_reminders(config):
    token = config.get("LINE_CHANNEL_ACCESS_TOKEN")
    if not token:
        return {"sent": 0, "skipped": 0, "error": "..."}, 400
    
    # 1. 🆕 LINE 全局配額檢查
    line_used_this_month = _get_monthly_line_push_count(config["DATA_FILE"])
    line_quota_exceeded = line_used_this_month >= config.get("LINE_PUSH_QUOTA_MONTHLY", 3000)
    
    summary = admin_summary(config["DATA_FILE"])
    state = load_state(config["DATA_FILE"])
    sender = config.get("LINE_PUSH_SENDER") or line_push_message
    
    sent = 0
    skipped = 0
    quota_skipped = 0
    travel_skipped = 0
    results = []
    
    for user in summary["users"]:
        if not user["is_overdue"]:
            continue
        
        profile = state["users"].get(user["line_user_id"], user)
        
        # 2. 🆕 旅遊模式檢查
        if _is_in_travel_mode(profile):
            travel_skipped += 1
            results.append({"line_user_id": user["line_user_id"], "skipped": "travel_mode"})
            continue
        
        # 3. 🆕 連續預警計數 + 強度切換
        consecutive = _count_recent_alerts(profile, hours=24)
        intensity = _get_alert_intensity(consecutive)
        # intensity: "full" (1st), "line_only" (2nd), "notify_only" (3rd+)
        
        location = profile.get("location") or {}
        location_link = ""
        if profile.get("attach_location_on_alert") and location.get("latitude"):
            location_link = f"\n最後位置:https://www.google.com/maps?q={location['latitude']},{location['longitude']}"
        
        # 4. 對用戶本人推播(走 LINE 配額)
        if not line_quota_exceeded or intensity == "full":
            line_message = f"寶寶,該回來簽到囉 ♡\n點一下「我還活著」,讓大家安心。{location_link}"
            try:
                sender(token, user["line_user_id"], line_message)
                _log_line_push(state, "overdue", user["line_user_id"], line_message)
                sent += 1
            except Exception as exc:
                skipped += 1
                _log_line_push(state, "overdue", user["line_user_id"], line_message, status="failed", error=str(exc))
        
        # 5. 對每位守護人
        rules = plan_rules(profile)
        contact_message = (
            f"{profile.get('display_name') or '使用者'} 已超過平安簽到時間,請協助確認。"
            f"{location_link}"
        )
        sms_message = (
            f"[緊急] {profile.get('display_name') or '使用者'} 已超過平安簽到時間,請聯繫確認。"
            # SMS 簡化,不含 emoji 跟超連結
        )
        
        for contact in (profile.get("contacts") or [])[: rules["contact_limit"]]:
            if contact.get("consent_status") != "accepted":  # 🆕 只送給已同意的
                continue
            
            methods = contact.get("notify_methods") or ["line"]
            
            # 5a. LINE 守護人
            if "line" in methods and contact.get("line_id"):
                if not line_quota_exceeded or intensity == "full":
                    try:
                        sender(token, contact["line_id"], contact_message)
                        _log_line_push(state, "contact_alert", contact["line_id"], contact_message)
                        sent += 1
                    except Exception as exc:
                        skipped += 1
                        _log_line_push(state, "contact_alert", contact["line_id"], contact_message, status="failed", error=str(exc))
            
            # 5b. 🆕 SMS 守護人(原本只 log pending,現在真的送)
            if "sms" in methods and contact.get("phone") and "sms" in rules.get("channels", []):
                if intensity in ("full", "line_only"):
                    # 連續降頻邏輯:notify_only 不送 SMS
                    result = send_sms(
                        phone=contact["phone"],
                        message=sms_message,
                        user_id=profile["line_user_id"],
                    )
                    if result["success"]:
                        sent += 1
                        results.append({"contact": contact["phone"], "channel": "sms", "status": "sent"})
                    else:
                        skipped += 1
                        results.append({"contact": contact["phone"], "channel": "sms", "status": result["status"]})
            
            # 5c. Phone 守護人(暫不實作)
            # if "phone" in methods and contact.get("phone") and profile.get("phone_addon_enabled"):
            #     # TODO: Phase 2
            #     pass
        
        # 6. 寫入 alert 歷史
        _record_alert(profile, intensity, location_link)
    
    save_state(config["DATA_FILE"], state)
    return {
        "sent": sent,
        "skipped": skipped,
        "quota_skipped": quota_skipped,
        "travel_skipped": travel_skipped,
        "results": results,
    }, 200
```

### 3.3.2 🆕 Helper 函式

```python
def _is_in_travel_mode(profile):
    if not profile.get("travel_mode_enabled"):
        return False
    expires = parse_datetime(profile.get("travel_mode_expires_at"))
    if expires and expires < datetime.now():
        # 過期 → 自動關閉
        profile["travel_mode_enabled"] = False
        return False
    return True


def _get_alert_intensity(consecutive_count):
    """
    1 次: 全管道(full)
    2 次(24hr 內): 僅 LINE(line_only)
    3 次(24hr 內): 僅通知守護人(notify_only)
    """
    if consecutive_count == 0:
        return "full"
    elif consecutive_count == 1:
        return "line_only"
    else:
        return "notify_only"


def _count_recent_alerts(profile, hours=24):
    """算 24 小時內已發幾次"""
    history = profile.get("alert_history", [])
    cutoff = datetime.now() - timedelta(hours=hours)
    return sum(1 for h in history if parse_datetime(h.get("at")) and parse_datetime(h["at"]) > cutoff)


def _record_alert(profile, intensity, location_link):
    history = profile.get("alert_history", [])
    history.append({
        "at": datetime.now().isoformat(timespec="seconds"),
        "intensity": intensity,
        "location": bool(location_link),
    })
    profile["alert_history"] = history[-50:]  # 只保留 50 筆


def _log_line_push(state, kind, target_id, message, status="sent", error=None):
    log = state.setdefault("line_push_log", [])
    log.append({
        "at": datetime.now().isoformat(timespec="seconds"),
        "kind": kind,  # "overdue" / "contact_alert" / "sos" / "transactional"
        "target_id": target_id,
        "status": status,
        "message_len": len(message),
        "error": error,
    })
    state["line_push_log"] = log[-1000:]  # 最多 1000 筆


def _get_monthly_line_push_count(data_file):
    """LINE Push 配額:這個月已用幾則"""
    state = load_state(data_file)
    log = state.get("line_push_log", [])
    cutoff_month = datetime.now().strftime("%Y-%m")
    return sum(1 for item in log if item.get("at", "").startswith(cutoff_month) and item.get("status") == "sent")
```

### 3.3.3 🆕 `set_travel_mode` 路由

```python
@app.post("/api/travel-mode")
def travel_mode_api():
    data, code = set_travel_mode(app.config["DATA_FILE"], request.get_json(silent=True) or {}, app.config)
    return jsonify(data), code


def set_travel_mode(data_file, payload, config):
    line_user_id = payload.get("line_user_id")
    enabled = payload.get("enabled", False)
    duration_days = int(payload.get("duration_days", 7))
    
    state = load_state(data_file)
    profile = state["users"].get(line_user_id)
    
    if enabled:
        profile["travel_mode_enabled"] = True
        profile["travel_mode_started_at"] = datetime.now().isoformat(timespec="seconds")
        profile["travel_mode_expires_at"] = (datetime.now() + timedelta(days=duration_days)).isoformat(timespec="seconds")
    else:
        profile["travel_mode_enabled"] = False
        profile["travel_mode_expires_at"] = None
    
    save_state(data_file, state)
    return {"travel_mode_enabled": profile["travel_mode_enabled"], "expires_at": profile.get("travel_mode_expires_at")}, 200
```

## 3.4 測試情境

| # | 情境 | 預期 |
|---|---|---|
| 1 | 799 用戶逾期 → 守護人有 phone + 勾簡訊 | LINE + SMS 都送 ✅ |
| 2 | 199 用戶逾期 → 守護人有 phone + 勾簡訊 | 只 LINE,不送 SMS ✅ |
| 3 | 用戶本月已 100 則 SMS → 守護人有 phone | SMS 跳過(send_sms 內部配額檢查)+ LINE 照送 ✅ |
| 4 | 用戶開旅遊模式 → 逾期 | 整個 skip,沒 LINE 沒 SMS ✅ |
| 5 | 連續 2 次預警(24hr 內)→ 第 2 次 | 只 LINE,不 SMS ✅ |
| 6 | LINE Push 配額用完(3000/月)→ 緊急預警 | 仍送(emergency priority) ✅ |
| 7 | LINE 配額用完 → 行銷訊息 | skip(但 send_due_reminders 不是行銷,只算緊急) ✅ |
| 8 | 守護人 consent_status=pending | 不送任何管道 ✅ |
| 9 | SMS 守護人電話格式錯 | send_sms 內部回 invalid_phone,跳過 ✅ |
| 10 | send_sms 5xx 失敗 | retry 3 次後 failed,寫 log,LINE 仍送 ✅ |

## 3.5 Migration

- 既有 `outbound_sms_log`(從 Task #2):沒資料,不需遷移
- 既有 LINE push 沒 log:從這次 cron 開始累積
- 既有 `pending` log(L1454-1456 的 `f"{method}_contact_alert"`):**保留**,不補發(避免騷擾)

## 3.6 Edge cases

- 守護人電話是空字串 → 不送 SMS
- 守護人同時有 LINE + phone + 都勾 → 都送(設計選擇,不去重)
- 用戶方案是 399 → channels=["line"],SMS 邏輯直接跳過
- 用戶方案是 799_year 但 channels 還沒改 → PLAN_LIMITS bug,要先修
- send_sms 自己 retry 3 次都失敗 → 整個 send_due_reminders 不擋,繼續跑

---

# 📋 Commit 順序(最終版)

```
1. fix(bind): 守護人雙重同意 + consent_respond API
   - bind_emergency_contact 改寫
   - process_consent_response 新增
   - _send_consent_invite_flex 新增
   - /api/consent/respond 路由
   - Postback handler
   - cleanup_expired_data 加 7 天過期邏輯
   
2. fix(plan): PLAN_LIMITS 修正(399 sos_enabled, 799_year 移除 phone)
   - 純常數修改
   - 測試既有 trigger_sos 不被擋

3. fix(sos): trigger_sos 拆 pending + confirm + cancel
   - trigger_sos 整個砍掉
   - 3 個新函式 + 4 helper
   - /api/sos/pending, /confirm, /cancel
   - Postback handler
   - DEFAULT_PROFILE 加 sos_* 欄位
   - 測試 10 個情境

4. feat(sms): send_due_reminders 實際送 SMS + LINE 配額 + 連續降頻 + 旅遊模式
   - send_due_reminders 改寫
   - 6 helper 函式
   - /api/travel-mode 路由
   - outbound_sms_log 整合(假設 Task #2 已完成)
   - line_push_log 新增
   - 測試 10 個情境
```

---

# ⏭️ 開工前確認(給蝦董)

請蝦董針對以下確認,確認後我就開始寫 code:

| # | 確認事項 | 你的決定 |
|---|---|---|
| 1 | Bug #1 同意流程:同意後保留「測試提醒」訊息?或移除? | |
| 2 | Bug #1 7 天過期後:**自動移除 contact** 或 **保留但標 expired**? | |
| 3 | Bug #2 連續預警降頻:`alert_history` 存 50 筆夠嗎? | |
| 4 | Bug #2 admin alert 也要走 LINE Push 嗎?會佔配額嗎? | |
| 5 | Bug #3 連續降頻的「3 次」後:**完全停止通知** 還是 **24hr 後重置**? | |
| 6 | Bug #3 LINE 配額用完後:緊急預警**也降級**還是**保留**? | |
| 7 | Bug #3 旅遊模式預設時長 7 天,合理嗎? | |

---

# 變更紀錄

| 版本 | 日期 | 作者 | 變更 |
|---|---|---|---|
| v0.1 | 2026-07-17 17:37 | 小龍蝦 | 50 函式總覽 |
| v0.2 | 2026-07-17 18:30 | 小龍蝦 | 3 核心函式差距對照 |
| v0.3 | 2026-07-17 18:38 | 小龍蝦 | **3 P0 bug 完整實作計畫 + 測試情境 + migration** |