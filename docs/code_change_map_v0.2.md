# Code Change Map v0.2 — 三大核心函式差距分析

> **狀態**:Draft v0.2(從 v0.1 補充深度分析)
> **建立日期**:2026-07-17 18:30
> **作者**:小龍蝦
> **範圍**:`trigger_sos` / `bind_emergency_contact` / `send_due_reminders` 三個核心函式的「現有邏輯 vs 新 spec」逐行對照

---

## 0. 摘要

| 函式 | 現有行數 | 新 spec 影響 | 改動規模 |
|---|---|---|---|
| `trigger_sos` | L968-1058(91 行) | SOS 3 層防護 + SMS for 799 | 🐛 **大改**(拆成 2 函式 + 加 4 helper) |
| `bind_emergency_contact` | L686-768(83 行) | 守護人雙重同意 | 🐛 **中改**(加 pending 狀態 + LINE 邀請 callback) |
| `send_due_reminders` | L1408-1459(52 行) | LINE Push 配額 + 實際 SMS + 連續降頻 + 旅遊模式 | 🐛 **大改**(加 4 helper + 配額整合) |

---

## 1. `trigger_sos` 差距表(L968-1058)

### 1.1 現有邏輯(逐段)

| 段 | 程式碼位置 | 功能 |
|---|---|---|
| §A 輸入驗證 | L968-971 | 檢查 `line_user_id` |
| §B 載入 profile | L973-977 | `load_state` + 取 user profile |
| §C 方案檢查 | L979-982 | `if not rules.get("sos_enabled"): return 403` |
| §D 守護人過濾 | L984-996 | 排序 by priority + 只取 LINE 守護人 + 限數 |
| §E 訊息組裝 | L998-1010 | 含位置連結的 SOS 訊息 |
| §F 發送迴圈 | L1012-1028 | 對每位 LINE 守護人 `sender(token, line_id, message)` |
| §G 守護群迴圈 | L1030-1051 | 對每位 active group 同樣發送 |
| §H 寫 log + return | L1053-1058 | 寫 `last_sos_at` + save_state + return counts |

### 1.2 新 spec 要求的行為

| Spec | 來源決策 | 邏輯 |
|---|---|---|
| ✅ **5 秒內可取消** | 5:46 v3 決策 #2 | 第一次呼叫 → 回 pending token + 不送 → 5 秒內第二次 confirm 才送 |
| ✅ **每日上限 3 次** | 5:46 SOS 3 層防護 #2 | 跨 00:00 重置;超限 → 回警告 + admin alert |
| ✅ **5 分鐘內不重複** | 5:46 SOS 3 層防護 #3 | 第二次觸發若 < 5 分鐘 → 自動 skip |
| ✅ **799 用戶加發 SMS** | 5:46 v3 決策 #2 | 對 phone 有填的守護人 call `send_sms(...)` |
| ✅ **超限引導 119** | 5:46 SOS 3 層防護 | 超 3 次 → 回「請撥打 119」訊息 |
| ✅ **超限觸發 admin alert** | 5:46 SOS 3 層防護 | 超 3 次 → 後台收到一條「該用戶今日已 3 次 SOS,請關懷」 |

### 1.3 差距對照(逐 spec 對齊)

| Spec | 現有 | 差距 | 嚴重度 |
|---|---|---|---|
| 5 秒內可取消 | ❌ **完全沒有** — 立刻送出去,無法取消 | 加 `pending_token` + `expires_at` 狀態機,加 confirm/cancel 路由 | 🔴 P0(安全) |
| 每日上限 3 次 | ❌ **完全沒有** — 可以無限次按 | 加 `sos_daily_count` + `sos_last_reset_date` + 跨日重置邏輯 | 🔴 P0(防止誤觸) |
| 5 分鐘冷卻 | ❌ **完全沒有** | 加 `sos_last_attempt_at` + 5 分鐘比較 | 🟡 P1(UX) |
| 799 加發 SMS | ❌ 只有 LINE | 加 `if rules["channels"] contains "sms": send_sms(...)` 迴圈 | 🟡 P1(付費功能) |
| 超限引導 119 | ❌ 完全沒實作 | 加 `if count >= 3: return warning_message_119` | 🟡 P1(UX) |
| 超限 admin alert | ❌ 完全沒實作 | 加 `append_notification_log(state, "sos_overlimit_alert", admin_id, "sent", ...)` | 🟡 P1(客服) |

### 1.4 改動方案:拆 2 函式

**新架構**:

```
sos_api (line 1822) 入口
    ↓
trigger_sos_pending()  ← 新函式,只負責「檢查 + 發 pending」
    ↓ 5 秒內
confirm_sos_send()    ← 新函式,只負責「確認 + 真的送」
    ↓
sos 5 秒外沒確認 → 自動 cancel,寫 log
```

**新 helper 函式(4 個)**:

| Helper | 用途 |
|---|---|
| `_check_sos_daily_limit(profile, limit=3) -> (allowed, count)` | 跨日重置 + 計數 |
| `_check_sos_cooldown(profile, minutes=5) -> (allowed, last_attempt)` | 冷卻檢查 |
| `_record_sos_attempt(profile, status)` | 寫進 `sos_today_history` |
| `_send_sos_to_799_sms_contacts(profile, message)` | 799 用戶 SMS 發送(用 `send_sms`) |

### 1.5 改動行數估算

| 動作 | 新增 | 修改 | 刪除 |
|---|---|---|---|
| trigger_sos_pending(新)| ~60 行 | — | — |
| confirm_sos_send(新)| ~50 行 | — | — |
| 4 helper 函式 | ~40 行 | — | — |
| 現有 trigger_sos | — | — | 91 行(整個砍掉) |
| 新路由 /api/sos/confirm, /cancel | ~30 行 | — | — |
| **小計** | **~180 行新增** | — | **91 行刪除** |

---

## 2. `bind_emergency_contact` 差距表(L686-768)

### 2.1 現有邏輯(逐段)

| 段 | 程式碼位置 | 功能 |
|---|---|---|
| §A 輸入驗證 | L686-692 | 檢查 inviter_id / contact_line_user_id / 不自綁 |
| §B 載入 + 更新 contact 顯示名 | L694-697 | get_profile + 改 contact_user.display_name |
| §C 加入 contact list | L699-720 | 檢查現有 + 檢查上限 + append(注意 L720:`consent_status: "accepted"` 🐛) |
| §D reward 機制 | L722-737 | 加 contact_rewards(trial_7_days / extra_contact_30_days) |
| §E 雙方測試訊息 | L739-759 | LINE 推播給雙方(僅測試提醒,不算正式同意) |
| §F 寫 state + return | L760-768 | save_state + return bound 狀態 |

### 2.2 新 spec 要求的行為

| Spec | 來源決策 | 邏輯 |
|---|---|---|
| ✅ **守護人雙重同意** | 04:55 P0 #4 | 加入 → `consent_status: "pending"` → 守護人收到 LINE 邀請 → 按同意 → `consent_status: "accepted"` |
| ✅ **未同意不生效** | 04:55 P0 #4 | `complete_guardian_contact()` 改成檢查 `consent_status == "accepted"` |
| ✅ **守護人收到邀請訊息** | 04:55 P0 #4 | 不只是「測試提醒」,要明確寫「我是 X 的緊急聯絡人,請按同意」+ 按鈕 |
| ✅ **邀請不等於同意** | 04:55 P0 #4 | 「LINE 一鍵授權綁定」這句話對守護人來說是「同意」的隱含,但個資法要求明確 |

### 2.3 差距對照(逐 spec 對齊)

| Spec | 現有 | 差距 | 嚴重度 |
|---|---|---|---|
| 守護人雙重同意 | 🐛 **立即設 `consent_status: "accepted"`**(L720)| 改成 `consent_status: "pending"` | 🔴 P0(個資法) |
| 未同意不生效 | `complete_guardian_contact` 已經檢查 `consent_status == "accepted"`(L650)| 已經對,但前提是 L720 要先設成 pending | 🔴 P0(配合上面) |
| 守護人收到邀請訊息 | ⚠️ 有發「測試提醒」訊息,但不是「明確同意邀請」 | 改訊息內容:加「請按同意」Flex Message 按鈕 | 🔴 P0(個資法) |
| 守護人按同意 | ❌ **完全沒有** callback 處理 | 新增 `/api/consent/respond` 路由 + handler | 🔴 P0(個資法) |
| 守護人拒絕 | ❌ 完全沒有 | 新增「拒絕」按鈕 → 從 inviter 的 contacts list 移除 | 🟡 P1(UX) |

### 2.4 改動方案

**新架構**:

```
sos_api → POST /api/emergency-contact/bind (L1783)
    ↓
bind_emergency_contact() 改寫
    ↓
1. 加 contact 到 inviter.contacts (consent_status: "pending")
2. 加進 state["consent_pending"][contact_line_user_id] = {inviter_id, expires_at}
3. 發 LINE Flex Message 給守護人:
   「X 想加你為緊急聯絡人。
    請按 [同意] 或 [拒絕]」
4. return {pending: True, expires_at: ...}
    ↓ 守護人按按鈕
callback handler 接收到 "consent_respond" postback
    ↓
process_consent_response()  ← 新函式
    ↓
1. 更新 contact.consent_status = "accepted" 或刪除
2. 從 consent_pending 移除
3. 發通知給 inviter 「守護人已同意/拒絕」
4. save_state
```

**新 helper / 函式**:

| 函式 | 用途 |
|---|---|
| `process_consent_response(data_file, payload, config)` | 處理守護人同意/拒絕 |
| `_send_consent_invite_flex(token, contact_line_id, inviter_name)` | 發 Flex Message 邀請 |

**新路由**:

| 路由 | 用途 |
|---|---|
| `/api/consent/respond` | 守護人按同意/拒絕 |
| `/api/consent/pending` | 查詢目前 pending 的邀請(給前端用) |

### 2.5 改動行數估算

| 動作 | 新增 | 修改 | 刪除 |
|---|---|---|---|
| bind_emergency_contact 改寫 | — | ~30 行 | — |
| process_consent_response(新)| ~50 行 | — | — |
| _send_consent_invite_flex(新)| ~30 行 | — | — |
| 3 新路由 + handlers | ~60 行 | — | — |
| normalize_contact 加 consent_at 預設 | — | ~5 行 | — |
| **小計** | **~140 行新增** | **~35 行修改** | — |

---

## 3. `send_due_reminders` 差距表(L1408-1459)

### 3.1 現有邏輯(逐段)

| 段 | 程式碼位置 | 功能 |
|---|---|---|
| §A token 驗證 | L1408-1410 | 讀 LINE_CHANNEL_ACCESS_TOKEN |
| §B 載入 state + summary | L1412-1414 | load_state + admin_summary |
| §C 對每位 overdue 用戶 | L1415 | 迴圈跑 `summary["users"]` |
| §D 對用戶本人推播 | L1417-1432 | 「寶寶,該回來簽到囉 ♡」+ 位置 |
| §E 對守護人推播(只 LINE) | L1434-1453 | 過濾 LINE 守護人,`sender(token, contact_id, msg)` |
| §F SMS/phone 守護人(只 log pending) | L1454-1456 | ⚠️ **只 log 不送** — 「missing phone」或「pending」 |
| §G return | L1458 | 回 sent / skipped / results |

### 3.2 新 spec 要求的行為

| Spec | 來源決策 | 邏輯 |
|---|---|---|
| ✅ **LINE Push 配額控管** | 17:37 LINE Push 規格 | 每月 3,000 則(中用量),超額降級非緊急 |
| ✅ **實際送 SMS(799 用戶)** | 04:55 P1 #5 | 對 phone 有填 + 守護人有勾簡訊 → 真的送 |
| ✅ **連續預警降頻** | 04:55 P1 #8 | 第 1 次全管道、第 2 次(24hr 內)只 LINE、第 3 次(24hr 內)只通知守護人 |
| ✅ **旅遊模式** | 04:55 P1 #8 | 用戶開啟旅遊模式 → 整個 `send_due_reminders` skip 該用戶 |
| ✅ **單帳號 SMS 100 則/月上限** | 04:55 P1 #5 | 從 `outbound_sms_log` 查本月 sent count;>= 100 跳過 + 通知 admin |
| ✅ **LINE 配額降級** | 17:37 LINE Push 規格 | 全月用超過 3,000 → 緊急預警保留,行銷/提醒降級 |
| ✅ **手機加購電話** | 17:37 v3 #5b | 對 phone_addon_enabled=True 的用戶,守護人有 phone 就發電話 |

### 3.3 差距對照(逐 spec 對齊)

| Spec | 現有 | 差距 | 嚴重度 |
|---|---|---|---|
| LINE Push 配額控管 | ❌ 沒追蹤 quota | 加 `line_push_log` model + 配額檢查 + 降級邏輯 | 🔴 P0(LINE 月費保護) |
| 實際送 SMS(799)| 🐛 **只 log pending**(L1454-1456)| 加 `send_sms(...)` 呼叫,對 phone 有填 + plan 有 sms channel 的守護人 | 🔴 P0(付費功能合約) |
| 連續預警降頻 | ❌ 完全沒有 | 加 `alert_count_24h` 計數 + 對應強度切換 | 🟡 P1(防止擾民) |
| 旅遊模式 | ❌ 完全沒有 | 加 `if user["travel_mode_enabled"]: continue` | 🟡 P1(UX) |
| SMS 100/月上限 | ❌ 完全沒有 | 加 `_check_user_sms_quota(...)` + skip + admin notify | 🔴 P0(成本控管) |
| LINE 配額降級 | ❌ 完全沒有 | 加全局 quota check,超限只保留 emergency | 🔴 P0(月費保護) |
| 電話加購 | ❌ 完全沒有 | 加 `if user["phone_addon_enabled"]` 邏輯 + `make_phone_call(...)` | ⏸️ 延後(等市場需求) |

### 3.4 改動方案

**新架構**:

```
send_due_reminders(config)
    ↓
1. 檢查 LINE 全局配額(這個月用多少?)
    ↓ 超限 → 只保留 emergency,其餘 skip
2. 載入 state + summary
3. 對每位 overdue 用戶:
    a. 旅遊模式檢查 → skip
    b. 計算連續預警次數 → 決定訊息強度
    c. 推播給用戶本人(走 LINE 配額)
    d. 對每位守護人:
       - LINE 守護人:走 LINE 配額
       - SMS 守護人:檢查配額 → 走 send_sms
       - Phone 守護人:檢查加購 → (延後)
4. 寫 outbound_sms_log
5. 寫 line_push_log
6. return sent / skipped / quota_exceeded
```

**新 helper / 函式**:

| 函式 | 用途 |
|---|---|
| `_check_global_line_quota(month_count, limit=3000) -> bool` | 全局 LINE 配額 |
| `_check_user_sms_quota(user_id, limit=100) -> (allowed, count)` | 單用戶 SMS 配額 |
| `_count_consecutive_alerts(user_id, hours=24) -> int` | 連續預警計數 |
| `_get_alert_intensity(count) -> "full" / "line_only" / "notify_only"` | 強度判斷 |
| `_should_use_sms(contact, plan_channels) -> bool` | 守護人是否走 SMS |
| `_send_alert_to_contacts(profile, message, intensity)` | 主發送邏輯 |

### 3.5 改動行數估算

| 動作 | 新增 | 修改 | 刪除 |
|---|---|---|---|
| send_due_reminders 主流程改寫 | — | ~30 行 | — |
| 6 helper 函式 | ~80 行 | — | — |
| 新增 outbound_sms_log 寫入邏輯 | ~30 行 | — | — |
| 新增 line_push_log 追蹤 | ~30 行 | — | — |
| **小計** | **~140 行新增** | **~30 行修改** | — |

---

## 4. 改動優先級矩陣

| 優先級 | 項目 | 理由 | 對應函式 |
|---|---|---|---|
| 🔴 **P0 必改** | bind_emergency_contact 雙重同意 | 個資法,被投訴就上新聞 | L686 |
| 🔴 **P0 必改** | trigger_sos 5 秒取消 + 每日上限 | 安全 + UX 必要 | L968 |
| 🔴 **P0 必改** | send_due_reminders 實際送 SMS | 799 付費功能合約 | L1408 |
| 🔴 **P0 必改** | LINE Push 配額控管 | 月費保護,不控會爆 | 新 |
| 🟡 **P1 應改** | SOS 5 分鐘冷卻 | 防止連續誤觸 | L968 |
| 🟡 **P1 應改** | 連續預警降頻 | 防止擾民,家人不會關掉通知 | L1408 |
| 🟡 **P1 應改** | 旅遊模式 | 出差 / 旅遊不要被打擾 | L1408 |
| 🟡 **P1 應改** | 守護人拒絕按鈕 | UX 完整 | L686 |
| 🟢 **P2 可改** | 電話加購功能 | 等市場需求 | L1408 |
| 🟢 **P2 可改** | 超限 admin alert webhook | 等客服能量起來 | L968 |

### 4.1 推薦 commit 順序

1. `fix(bind): 守護人雙重同意(P0)`— 只動 bind_emergency_contact + 加 consent_respond 路由
2. `fix(sos): trigger_sos 拆 pending + confirm,加每日 3 次上限(P0)`
3. `feat(sms): send_due_reminders 實際送 SMS(P0)`
4. `feat(quota): LINE Push 配額 + SMS 配額控管(P0)`
5. `feat(sos): 5 分鐘冷卻 + 連續降頻 + 旅遊模式(P1)`
6. `feat(consent): 守護人拒絕按鈕(P1)`

---

## 5. 連帶影響(其他檔案 / 函式)

| 影響 | 位置 | 為什麼 |
|---|---|---|
| `DEFAULT_PROFILE` 加新欄位 | L30 | 註冊時初始化 SOS counter / travel_mode / phone_addon |
| `PLAN_LIMITS` 修 399 sos_enabled | L73 | 跟 trigger_sos 配合 |
| `build_status` 加新欄位 | L327 | 前端要顯示 SOS count / travel mode / pending consent |
| `clean_expired_data` 加新清理項 | L1533 | 清理 outbound_sms_log / sos_today_history / consent_pending |
| `line_callback` 加新 keyword handler | L1689 | 「SOS」「同意」「拒絕」「旅遊模式」 |
| `create_app` 加新 env vars | L1633 | SMSKING_* / LINE_PUSH_QUOTA / PHONE_ADDON_RATE |

---

## 6. 待辦(下一輪)

- [ ] 讀 `outbound_sms_log` 的 schema 設計 → 配合 Task #2 SMS 通道
- [ ] 讀 `sos_daily_count` / `travel_mode` 的 state 結構 → 配合 PostgreSQL 遷移
- [ ] 設計 LINE Push 配額降級的優先級對照表
- [ ] 寫 sos_3layer_spec.md(SOS 完整狀態機)— 蝦董已欽定細節,直接寫

---

## 7. 變更紀錄

| 版本 | 日期 | 作者 | 變更 |
|---|---|---|---|
| v0.1 | 2026-07-17 17:37 | 小龍蝦 | 初版:50 函式總覽 |
| v0.2 | 2026-07-17 18:30 | 小龍蝦 | 深度分析 3 個核心函式 + 改動優先級矩陣 |