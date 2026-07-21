# Code Change Map — alive_checkin 正式版改造

> **狀態**:Draft v0.1
> **建立日期**:2026-07-17 17:37
> **作者**:小龍蝦(顧問)
> **目標對象**:`app.py` (107 KB / 2345 行 / 60+ 函式 / 45+ 路由)

---

## 0. 摘要

`app.py` 是 Flask 單體後端,**所有商業邏輯 + 所有路由 + 所有資料存取都在這裡**。改造影響:
- **常數修改** × 4 個(`DEFAULT_PROFILE` / `PLAN_LIMITS` / `PAYMENT_PRODUCTS` / `RICH_MENU_COMMANDS`)
- **既有函式修改** × ~35 個
- **新函式新增** × ~12 個
- **新路由新增** × ~6 個
- **環境變數新增** × ~8 個

正式版改造不是「加 feature」,是**重塑商業邏輯核心**。建議**逐 task 提交 commit**,不要一次合併。

---

## 1. 既有的 5 大 bug / 不一致(開工前必知)

| # | 問題 | 位置 | 影響 |
|---|---|---|---|
| 🐛 1 | `paid_399` 設 `sos_enabled: False`,但新 spec 要 SOS | line 76 | 399 用戶目前點 SOS 會被擋 |
| 🐛 2 | `paid_799_year` 含 `phone` channel | line 81 | 違反新決策(電話改加購) |
| 🐛 3 | `trigger_sos` 沒 5 秒取消 + 沒每日上限 + 沒 SMS | line 968-1058 | 違反 SOS 3 層防護 |
| 🐛 4 | `bind_emergency_contact` 立即設 `consent_status: "accepted"` | line 720 | 違反守護人雙重同意 |
| 🐛 5 | `send_due_reminders` 對 SMS/phone 只 log `pending`,沒實際發送 | line 1452-1454 | 799 用戶 SMS 通知永遠不會送達 |
| 🐛 6 | `trial_days_left` 寫死 7 天 | line 315 | 試用期長度不可設定 |
| 🐛 7 | 沒有 `phone_addon_*` 任何欄位 | 全檔 | 電話加購功能沒有基礎建設 |
| 🐛 8 | `state.json` 單檔 + Flask multi-worker race condition | 全檔 | 規模上去必 corrupt |

---

## 2. 常數修改(L 30-111)

### 2.1 `DEFAULT_PROFILE` (line 30)
**現況**:基礎預設值,缺新欄位

**新增欄位**:
```python
DEFAULT_PROFILE = {
    ...
    # 新增
    "phone_addon_enabled": False,
    "phone_addon_consent_at": None,
    "phone_addon_started_at": None,
    "phone_addon_expires_at": None,
    "sos_daily_count": 0,
    "sos_last_reset_date": None,
    "sos_last_attempt_at": None,
    "sos_today_history": [],     # [(timestamp, status: "sent"/"cancelled"/"denied")]
    "travel_mode_enabled": False,
    "travel_mode_started_at": None,
    "travel_mode_expires_at": None,
    "consent_pending": [],       # [contact_line_user_id] 待守護人同意
}
```

### 2.2 `PLAN_LIMITS` (line 73-82)
**現況**:7 種方案,但與新 spec 不一致

**修正清單**:
```python
PLAN_LIMITS = {
    "free": {...},  # 不變
    "trial": {...},  # 不變(7 天試用)
    "paid_199": {...},  # contact_limit 改 4(原本就是 4),其他不變
    "paid_199_year": {...},
    "paid_399": {
        # 🐛 修正:sos_enabled: False → True
        # 🐛 修正:contact_limit 15 不變
        # 新增 daily_reminders: 2(原本就是)
        "sos_enabled": True,   # 🐛 新 spec 399 有 SOS
    },
    "paid_399_year": {
        "sos_enabled": True,   # 🐛 修正
    },
    "paid_799": {
        # 保留 channels: ["line", "sms"],移除 phone
        # 🐛 修正:dedicated_support: True(原本 False)
        "dedicated_support": True,
    },
    "paid_799_year": {
        # 🐛 修正:channels 移除 "phone"
        "channels": ["line", "sms"],   # 🐛 移除 phone
        # 🐛 新增:guardian_group_limit: 3(原本就有)
        # 🐛 修正:dedicated_support: True
        "dedicated_support": True,
    },
}
```

### 2.3 `PAYMENT_PRODUCTS` (line 84-91)
**現況**:舊價(NT$1,990 / 3,990 / 7,990)

**修改成新價**:
```python
PAYMENT_PRODUCTS = {
    "paid_199": {"amount": 199, "billing_cycle": "monthly", "duration_days": 30},
    "paid_199_year": {"amount": 1680, "billing_cycle": "yearly", "duration_days": 365},  # 🆕 1990 → 1680
    "paid_399": {"amount": 399, "billing_cycle": "monthly", "duration_days": 30},
    "paid_399_year": {"amount": 3680, "billing_cycle": "yearly", "duration_days": 365},  # 🆕 3990 → 3680
    "paid_799": {"amount": 799, "billing_cycle": "monthly", "duration_days": 30},
    "paid_799_year": {"amount": 7200, "billing_cycle": "yearly", "duration_days": 365},  # 🆕 7990 → 7200
    # 🆕 新增電話加購 SKU
    "phone_addon_monthly": {"amount": 200, "billing_cycle": "monthly", "duration_days": 30, "addon": "phone"},
}
```

### 2.4 `RICH_MENU_COMMANDS` (line 93)
**不變**(`"SOS 緊急求救"` 是另一個入口,不是 Rich Menu 命令)

### 2.5 `ALERT_CHANNEL_KEYWORDS` (line 110)
**修正**:移除 `"電話"` 關鍵字(已改加購)
```python
ALERT_CHANNEL_KEYWORDS = {"簡訊", "全渠道", "全通道", "自動撥號"}  # 🐛 移除 "電話"
```

---

## 3. 既有的 50+ 函式:改動方向

### A. 試用期 + 方案(Task #4 + #8)

| 函式 | 位置 | 改動方向 |
|---|---|---|
| `trial_days_left` | L315 | 從 `config["TRIAL_DAYS"]` 讀,不再寫死 7 |
| `trial_active` | L323 | 沿用,但配合 D-7/D-3/D-1 排程看 trial 變化 |
| `plan_rules` | L310 | 配合 PLAN_LIMITS 修正 |
| `build_status` | L327 | 新增欄位:`phone_addon_enabled` / `sos_daily_count` / `sos_last_attempt_at` / `travel_mode_enabled` / `pending_consent_count` |

### B. 用戶註冊 + 設定(Task #3 + #5)

| 函式 | 位置 | 改動方向 |
|---|---|---|
| `register_line_user` | L413 | 註冊時初始化 SOS counter / travel_mode / phone_addon 欄位 |
| `save_settings_for_profile` | L478 | 新增支援 `travel_mode_enabled` / `travel_mode_expires_at` 儲存 |
| `save_billing_preferences` | L498 | 新增支援 `phone_addon_enabled` toggle |

### C. 付款(Task #6 藍新)

| 函式 | 位置 | 改動方向 |
|---|---|---|
| `create_payment_order` | L516 | 改:寫訂單到 DB、新增 phone_addon 訂單類型、串 藍新 CheckOut 產生 URL |
| `confirm_payment_order` | L547 | 改:不再寫死手動確認,改成 藍新 webhook 呼叫 |
| `send_renewal_reminders` | L586 | 改:用新價計算剩餘天數對應的金額 |

### D. 守護人綁定(Task #3 雙重同意)

| 函式 | 位置 | 改動方向 |
|---|---|---|
| `bind_emergency_contact` | L686 | 🐛 **大改**:現流程立即設 `consent_status: "accepted"` → 改為 `"pending"`,傳 LINE 邀請給守護人,等守護人按同意才 `"accepted"` |
| `bind_guardian_group` | L779 | 不改主流程,但要驗證 owner 同意狀態 |
| `unbind_guardian_group` | L840 | 不變 |
| `normalize_contact` | L624 | 加 `consent_status` 預設值 `"pending"` |
| `complete_guardian_contact` | L643 | 改判斷:`consent_status == "accepted"` 才算「完成」 |
| `save_contacts` | L665 | 不變(只是 list 操作) |
| `get_contacts` | L652 | 過濾掉 `consent_status != "accepted"` 的(對外顯示) |

### E. 朋友 + 位置(不在本輪改造,但要小心)

| 函式 | 位置 | 改動方向 |
|---|---|---|
| `create_friend_invite` | L866 | 不變(獨立模組) |
| `accept_friend_invite` | L885 | 不變 |
| `update_location` | L926 | 不變 |
| `stop_location_sharing` | L954 | 不變 |
| `friend_locations` | L1062 | 不變 |

### F. SOS(Task #5a 3 層防護)

| 函式 | 位置 | 改動方向 |
|---|---|---|
| `trigger_sos` | L968 | 🐛 **大改**:1) 拆成 `trigger_sos_pending`(回傳 5 秒取消 token)+ `confirm_sos_send`(真的送)2) 加 `check_sos_daily_limit` 3) 加 `check_sos_cooldown` 4) 對 799 用戶加 `send_sms(...)` 5) 超限時回警告 + admin alert |

### G. 後台 + 客服(部分要改)

| 函式 | 位置 | 改動方向 |
|---|---|---|
| `admin_summary` | L1269 | 新增:`total_pending_consent` / `sos_daily_usage_stats` / `sms_quota_warnings` |
| `admin_update_user_plan` | L1089 | 新增支援 `phone_addon_enabled` / `travel_mode_enabled` toggle |
| `admin_reply_support_ticket` | L1137 | 不變 |
| `admin_support_tickets` | L1131 | 不變 |
| `admin_allowed` | L1259 | 不變 |

### H. 帳號 + 個資(合規)

| 函式 | 位置 | 改動方向 |
|---|---|---|
| `export_account_data` | L1159 | 新增欄位 `phone_addon_*` / `sos_*` / `travel_mode_*` / `consent_*` |
| `delete_account` | L1188 | 連動刪除守護人同意紀錄(LGPD 個資法) |
| `delete_personal_history` | L1233 | 連動刪除 outbound_sms_log 的內容 |
| `create_support_ticket` | L1105 | 不變 |

### I. LINE 推播(Task:LINE Push 配額)

| 函式 | 位置 | 改動方向 |
|---|---|---|
| `line_push_message` | L1369 | 包裝 LINE API 呼叫,加 quota tracking(寫進 `line_push_log`)|
| `append_notification_log` | L1387 | 增加 `quota_category: "emergency" / "marketing" / "transactional"` 欄位 |
| `log_notification` | L1402 | 同上 |

### J. 提醒 + 預警(Task #5 + #5b + SMS)

| 函式 | 位置 | 改動方向 |
|---|---|---|
| `send_due_reminders` | L1408 | 🐛 **大改**:1) 加旅遊模式檢查(skip)2) 加 連續預警降頻邏輯(第 1/2/3 次不同強度)3) **對 799 用戶實際送 SMS**(call `send_sms`)4) 加 電話加購用戶實際送電話(Phase 2) |
| `send_missing_contact_reminders` | L1461 | 加旅遊模式檢查 |
| `send_checkin_reminders` | L1579 | 加旅遊模式檢查 |
| `cleanup_expired_data` | L1533 | 新增清理 `outbound_sms_log` / `sos_today_history` / `consent_pending` 過期資料 |
| `reminder_time_due` | L1571 | 不變 |

### K. App 建立 + 設定

| 函式 | 位置 | 改動方向 |
|---|---|---|
| `create_app` | L1633 | 🐛 **加 env vars**:`SMSKING_USERNAME` / `SMSKING_PASSWORD` / `SMSKING_API_URL` / `SMSKING_ENCODING` / `SMSKING_TIMEOUT_SEC` / `SMSKING_COST_PER_SMS_NTD` / `SMS_QUOTA_PER_USER_PER_MONTH` / `PHONE_ADDON_RATE_NTD` |
| `app_config` | L1625 | 加上對應 config keys |

---

## 4. 新函式(本輪要新增的 ~12 個)

| 新函式 | 對應 Task | 用途 |
|---|---|---|
| `send_sms(phone, message, user_id, *, feature_flag, dry_run) -> SendResult` | #2 | SMS 通道,從 spec v0.1 實作 |
| `_check_user_sms_quota(user_id, limit) -> (allowed, count)` | #2 | 配額檢查 |
| `_write_outbound_sms_log(user_id, phone, content, result)` | #2 | 寫 SMS log |
| `_map_smsking_response(resp) -> SendResult` | #2 | 簡訊王回應映射 |
| `_check_sos_daily_limit(profile, limit=3) -> (allowed, count)` | #5a | SOS 每日 3 次上限 |
| `_check_sos_cooldown(profile, minutes=5) -> (allowed, last_attempt)` | #5a | SOS 5 分鐘冷卻 |
| `_record_sos_attempt(profile, status)` | #5a | 記錄 SOS 嘗試 |
| `_reset_sos_daily_count_if_new_day(profile)` | #5a | 跨日重置 |
| `trigger_sos_pending(data_file, payload, config)` | #5a | SOS 第一階段:回傳 5 秒取消 token |
| `confirm_sos_send(data_file, payload, config)` | #5a | SOS 第二階段:確認送出 |
| `cancel_sos_pending(data_file, payload, config)` | #5a | SOS 取消 |
| `_check_travel_mode(profile) -> bool` | #5 | 旅遊模式檢查 helper |
| `set_travel_mode(data_file, payload, config)` | #5 | 開/關旅遊模式 |
| `process_consent_response(data_file, payload, config)` | #3 | 守護人按同意後更新狀態 |
| `convert_trial_users(config)` | #4 | D-7/D-3/D-1/D-Day 提醒排程 |
| `admin_sms_quota_status(config)` | #2 | 後台查詢 SMS 用量 |

---

## 5. 新路由(本輪要新增的 ~6 個)

| Method | Path | 用途 | 對應 Task |
|---|---|---|---|
| `POST` | `/api/sos/confirm` | SOS 第二階段確認 | #5a |
| `POST` | `/api/sos/cancel` | SOS 5 秒內取消 | #5a |
| `POST` | `/api/travel-mode` | 開關旅遊模式 | #5 |
| `POST` | `/api/consent/respond` | 守護人按同意按鈕 | #3 |
| `POST` | `/api/phone-addon/toggle` | 電話加購 on/off | #5b |
| `GET` | `/api/admin/sms-quota` | 後台查 SMS 配額 | #2 |
| `POST` | `/api/cron/trial-conversion` | 試用期轉化提醒 cron | #4 |
| `POST` | `/webhook/newebpay` | 藍新付款 webhook | #6 |

---

## 6. 環境變數新增(~8 個)

| 變數 | 用途 | 預設值 |
|---|---|---|
| `SMSKING_USERNAME` | 簡訊王帳號 | (必填) |
| `SMSKING_PASSWORD` | 簡訊王密碼 | (必填,*** redact) |
| `SMSKING_API_URL` | 簡訊王 API endpoint | 待蝦董索取業務文件 |
| `SMSKING_ENCODING` | BIG5 / UTF-8 | `BIG5` |
| `SMSKING_TIMEOUT_SEC` | HTTP timeout | `10` |
| `SMSKING_COST_PER_SMS_NTD` | 單則成本 | `0.85` |
| `SMS_QUOTA_PER_USER_PER_MONTH` | 用戶配額 | `100` |
| `PHONE_ADDON_RATE_NTD` | 電話加購月費 | `200` |
| `TRIAL_DAYS` | 試用期天數 | `7` |
| `NEWEBPAY_MERCHANT_ID` | 藍新商店代號 | (待申請) |
| `NEWEBPAY_HASH_KEY` | 藍新 HashKey | (待申請,*** redact) |
| `NEWEBPAY_HASH_IV` | 藍新 HashIV | (待申請,*** redact) |
| `LINE_PUSH_QUOTA_MONTHLY` | LINE Push 方案額度 | `3000` |
| `FEATURE_FLAG_799_ENABLED` | 799 全域開關 | `false`(預設關) |

---

## 7. 既有路由的細部改動

| 路由 | 位置 | 改動 |
|---|---|---|
| `/api/emergency-contact/bind` | L1783 | 改:不再立即設 `accepted`,回 `pending` + 傳 LINE 邀請 |
| `/callback` | L1689 | 新增 SOS / consent / travel-mode / phone-addon 關鍵字 handler |
| `/api/admin/summary` | L1842 | 新增欄位輸出(見 §3.G) |
| `/api/admin/user-plan` | L1951 | 加 phone_addon / travel_mode toggle |
| `/api/cron/*` | L1919-1946 | 不變,但要加新 `/api/cron/trial-conversion` |
| `/api/sos` | L1822 | 🐛 改為只處理「pending 確認」,不直接送 |

---

## 8. PostgreSQL 遷移影響範圍(Task #7)

**所有 `state = load_state(data_file)` 和 `save_state(...)` 都要改**:

- ~30 個函式直接呼叫 `load_state` / `save_state`
- 從「整個 JSON 讀寫」改為「函式級 SQL query」
- 效能提升 + 並發安全 + 不用一次寫整包

**影響函式清單(全部要改 I/O)**:
- `register_line_user` / `record_checkin` / `cancel_warning`
- `save_settings_for_profile` / `save_billing_preferences`
- `create_payment_order` / `confirm_payment_order`
- `bind_emergency_contact` / `bind_guardian_group` / `unbind_guardian_group`
- `create_friend_invite` / `accept_friend_invite`
- `update_location` / `stop_location_sharing` / `trigger_sos`
- `admin_summary` / `admin_update_user_plan`
- `create_support_ticket` / `admin_support_tickets` / `admin_reply_support_ticket`
- `export_account_data` / `delete_account` / `delete_personal_history`
- `send_due_reminders` / `send_missing_contact_reminders` / `send_checkin_reminders`
- `cleanup_expired_data`
- 4 個 cron endpoints

**這是 Task #7 的範圍,跟 Task #2~#6 是並行推進,不能混著做**。

---

## 9. Commit 順序建議(給蝦董參考)

蝦董你可以挑一種:

### 方案 A:依業務邏輯(推薦)
1. `fix(constants): PLAN_LIMITS / PAYMENT_PRODUCTS 新價 + 799 修正`
2. `feat(profile): SOS counter / travel_mode / phone_addon 預設欄位`
3. `feat(bind): 守護人雙重同意機制`
4. `feat(sos): 3 層防護(5 秒取消 + 每日 3 次 + 5 分鐘冷卻)`
5. `feat(sms): 簡訊王 send_sms + outbound_sms_log`
6. `feat(alert): 連續預警降頻 + 旅遊模式 + 實際 SMS 送出`
7. `feat(payment): 藍新 CheckOut + webhook`
8. `feat(trial): 7 天試用期 D-7/D-3/D-1/D-Day 轉化提醒`
9. `feat(phone-addon): 加購 toggle + 加購 SOP`
10. `refactor(db): 從 state.json 遷 PostgreSQL`

### 方案 B:依優先級
1. P0 修正:`PLAN_LIMITS` bug + 新價
2. P0 修正:`bind_emergency_contact` 雙重同意
3. P0 修正:`trigger_sos` 3 層防護
4. P0 修正:`send_due_reminders` 實際送 SMS
5. P1 加:`send_sms` + `outbound_sms_log`
6. P1 加:藍新 webhook
7. P1 加:旅遊模式 + 連續降頻
8. P1 加:7 天試用期轉化
9. P1 加:電話加購
10. P2 重構:PostgreSQL

---

## 10. 開工前必備(蝦董白天要先處理)

- [ ] 簡訊王 API 文件(從業務索取)
- [ ] 簡訊王帳號密碼(放 Render env vars)
- [ ] 藍新金流測試帳號 + merchant_id + HashKey + HashIV
- [ ] 會計師稅務回覆(不開發票下如何認列營收)
- [ ] PostgreSQL hosting(Render Postgres / Railway / Supabase)

---

## 11. 變更紀錄

| 版本 | 日期 | 作者 | 變更 |
|---|---|---|---|
| v0.1 | 2026-07-17 17:37 | 小龍蝦 | 初版:50 函式 + 12 新函式 + 6 新路由 + 8 環境變數 |