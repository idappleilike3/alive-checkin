# 完整推播管理中心與會員期限設計

## 1. 目標

本次建立可正式使用的推播管理中心，讓最高管理員安全地建立、修改、排程、取消及查閱推播，同時保留不可覆寫的版本、收件人快照、發送結果與中文錯誤原因。

推播資格必須使用同一套會員有效期限規則。因此本次也會修正付費方案、封測方案與人工贈送方案的時間模型，並保證簽到天數、簽到紀錄、會員等級及累積資料不會因方案升級而歸零。

## 2. 範圍

### 2.1 會員期限規則

- 14 天體驗轉為付費方案時，以付款或後台升級成功時間作為付費方案開始時間。
- 399 付費方案升級為 799 付費方案時，以升級成功時間重新起算完整月繳或年繳期限。
- 其他付費方案互換也使用相同規則：新方案期限從該次成功異動時間重新起算。
- 月繳期限為開始時間加 30 天；年繳期限為開始時間加 365 天，沿用現有 `PAYMENT_PLANS` 定義。
- B399／B799 封測沿用原本 `beta_started_at` 與 `beta_ends_at`，修改顯示方案或後台資料時不得重新起算。
- 新增 G799 人工贈送來源，使用管理員明確設定的 `gift_started_at` 與 `gift_ends_at`。
- 既有會員缺少付費到期日時，依序使用付款紀錄、方案異動稽核紀錄及可信任的方案開始時間補算。
- 找不到可靠異動時間時，不猜測、不自動補日期；列入後台「期限待確認」名單，由最高管理員補上生效時間。
- 方案異動必須寫入修改人、修改時間、修改前方案、修改後方案、開始時間與到期時間。

### 2.2 不會被重設的會員資料

- 第一天開始簽到、第七天升級方案，隔天仍為第八天。
- `checkin_history`、最後簽到時間、連續簽到天數、會員等級、累積資料及既有守護關係全部保留。
- 第 7 天提醒使用原本首次有效啟用／簽到時鐘，不因付費升級再次發送。
- B399／B799 的 Day 1～21 一律以原本封測開始日計算。

### 2.3 推播管理中心

- 後台新增「安全與通知 → 推播管理」，網址為 `/admin?page=push-management`。
- 支援純文字內容及系統核准的 Flex 模板，不允許管理員直接輸入任意 Flex JSON。
- 支援多個方案分類與指定個別會員，兩者合併後依 LINE UID 去重。
- 不建立「立即發送」按鈕，也不提供繞過排程的管理 API。
- 儲存、修改、複製舊版本及查看預覽都不會觸發 LINE 發送。

## 3. 權限與安全

- 只有 `super_admin` 可以建立、修改、準備排程、確認排程及取消推播。
- `operations`、`finance`、`viewer` 只能查看推播資料、版本、事件及發送紀錄。
- 所有寫入路由沿用管理 Session、HTTPS、CSRF、登入速率限制及 `admin_audit_logs`。
- 後端必須在每次寫入時重新檢查 `session["admin_role"] == "super_admin"`，不能只依前端隱藏按鈕。
- 使用者輸入一律以文字方式呈現並套用既有 `escapeHtml`，不得插入未清理 HTML。
- 推播主檔、版本、事件及發送紀錄都不提供刪除 API。

## 4. 架構

### 4.1 模組邊界

新增 `push_management.py`，集中處理：

- 推播主檔驗證與狀態轉換。
- 不可變版本建立與讀取。
- 方案分類、個別會員與實際收件人解析。
- 發送當下資格判斷與收件人快照。
- 排程租約、投遞唯一鍵、固定 LINE Retry Key 及重試次數。
- 發送結果彙整與最終狀態。

`app.py` 只負責：

- 註冊管理 API。
- 將現有管理 Session、CSRF、資料讀寫與 LINE sender 傳給推播模組。
- 在現有 `/api/cron/tick` 呼叫推播排程處理器。
- 將現有系統推播紀錄轉成統一查詢格式。

`admin.html` 只負責固定白名單頁面、表單、預覽、篩選、詳細資料及唯讀權限呈現。

### 4.2 沿用現有儲存

沿用目前 `load_state`／`save_state` 與 PostgreSQL 持久化，不新增 Redis 或額外 Worker。所有新資料放在獨立集合，並使用現有交易／租約模式避免多程序重複執行。

## 5. 資料模型

### 5.1 `push_campaigns`

以 `campaign_id` 為鍵，保存：

- `campaign_id`
- `name`
- `status`
- `current_version_id`
- `audience_plan_codes`
- `audience_member_ids`
- `scheduled_at`
- `created_by_role`
- `created_at`
- `updated_by_role`
- `updated_at`
- `cancelled_by_role`
- `cancelled_at`
- `cancel_reason_zh`
- `lease_owner`
- `lease_expires_at`
- `recipient_snapshot_created_at`
- `success_count`
- `failure_count`
- `total_count`

### 5.2 `push_campaign_versions`

以 `version_id` 為鍵，保存完整不可變快照：

- `version_id`
- `campaign_id`
- `version_number`
- `name`
- `content_type`：`text` 或 `approved_template`
- `message_text`
- `template_key`
- `template_parameters`
- `audience_plan_codes`
- `audience_member_ids`
- `scheduled_at`
- `created_by_role`
- `created_at`
- `source_version_id`：從舊版本複製時記錄來源

每次儲存都新增版本，不修改舊版本。查看或複製舊版本不會改變原資料；複製後儲存會建立新的版本編號。

### 5.3 `push_campaign_deliveries`

以 `delivery_id` 為鍵，保存發送當下的不可變快照：

- `delivery_id`
- `campaign_id`
- `version_id`
- `line_user_id`
- `recipient_display_name`
- `recipient_type`
- `plan`
- `membership_source`
- `beta_cohort`
- `scheduled_at`
- `first_attempt_at`
- `last_attempt_at`
- `sent_at`
- `status`：`pending`、`sent`、`retrying`、`failed`
- `attempt_count`
- `retry_key`
- `failure_kind`
- `failure_reason_zh`
- `failure_action_zh`
- `technical_detail`

同一個 `campaign_id + version_id + line_user_id` 只能有一筆 delivery，避免重複建立收件人。

### 5.4 `push_campaign_events`

保存 `created`、`saved`、`prepared`、`scheduled`、`schedule_invalidated`、`sending_started`、`completed`、`partially_failed`、`fully_failed`、`cancelled`、`late_cancelled` 等事件，以及操作者、時間與中文說明。

### 5.5 會員期限欄位

- 付費：`paid_started_at`、`paid_until`、`membership_source="paid"`。
- 封測：`beta_started_at`、`beta_ends_at`、`beta_cohort`、`membership_source="beta"`。
- G799 贈送：`gift_started_at`、`gift_ends_at`、`gift_code="G799"`、`membership_source="gift"`。
- 期限待確認：`membership_expiry_review_required=true` 與 `membership_expiry_review_reason_zh`。

## 6. 方案分類

推播受眾代碼固定為：

- `free`
- `trial_14`
- `paid_199`
- `paid_199_year`
- `paid_399`
- `paid_399_year`
- `paid_799`
- `paid_799_year`
- `beta_B399`
- `beta_B799`
- `gift_G799`

實際發送前，系統重新讀取會員並依當下有效期限分類。指定個別會員仍須具備有效 LINE UID、未被標記為永久封鎖，且會員資料仍存在。方案分類名單與指定會員採聯集，最後依完整 LINE UID 去重。

## 7. 狀態機

主要流程：

`草稿 → 待排程 → 已排程 → 發送中 → 已完成／部分失敗／全部失敗`

規則：

- 新增時為 `draft`（草稿）。
- 必填資料完整且通過驗證後，最高管理員可轉為 `pending_schedule`（待排程）。
- 再次確認內容、對象與時間後，轉為 `scheduled`（已排程）。
- 到期並成功取得租約後，轉為 `sending`（發送中）。
- 全部成功為 `completed`（已完成）。
- 同時有成功與失敗為 `partially_failed`（部分失敗）。
- 全部失敗為 `fully_failed`（全部失敗）。
- 尚未進入 `sending` 的推播可轉為 `cancelled`（已取消）。
- 已排程內容只要被修改，原排程失效、建立新版本並退回 `pending_schedule`，必須重新確認。
- 已進入 `sending` 後禁止修改內容、對象與預定時間。
- 狀態轉換必須由固定白名單驗證，非法跳轉回傳 409 與自然繁中原因。

## 8. 排程、補送與重試

- 使用現有五分鐘排程器掃描到期推播。
- 預定時間後 24 小時內仍可補送；超過 24 小時且尚未開始時，自動轉為 `cancelled`，原因為「已超過 24 小時補送期限，系統未再發送」。
- 取得推播租約後才建立收件人快照；租約逾時可由下一個排程程序接手。
- 每筆 delivery 使用由 campaign、version、LINE UID 推導的穩定 Retry Key。
- 暫時性錯誤最多嘗試三次；永久失敗不重試。
- 系統設定錯誤（例如 LINE token 無效）停止該輪後續發送，保留 pending delivery 給下一輪處理。
- 額度限制視為暫時性錯誤，但仍受三次上限與 24 小時補送期限約束。
- 發送與結算中斷後，下一輪必須重用相同 delivery 與 Retry Key，不得重新產生收件人或重複計費。

## 9. 系統推播紀錄整合

SOS、取消 SOS、綁定通知、逾時提醒、生日提醒、第 7 天置頂提醒、封測訊息及其他既有系統推播不建立 campaign，也不進入自訂推播狀態機。

既有 `notification_logs` 保持原資料不變，統一查詢 API 將它們轉成與 campaign delivery 相同的唯讀欄位：收件人、LINE UID、當時方案、預定時間、實際時間、成功／失敗、中文原因及技術訊息。

## 10. 管理 API

唯讀 API 對所有已登入後台角色開放：

- `GET /api/admin/push-campaigns`
- `GET /api/admin/push-campaigns/<campaign_id>`
- `GET /api/admin/push-campaigns/<campaign_id>/versions`
- `GET /api/admin/push-campaigns/<campaign_id>/deliveries`
- `GET /api/admin/push-campaigns/<campaign_id>/events`
- `GET /api/admin/push-templates`
- `POST /api/admin/push-campaigns/audience-preview`：只計算預估人數，不建立 delivery、不發送
- `GET /api/admin/membership-expiry-reviews`

只有 `super_admin` 可使用的寫入 API：

- `POST /api/admin/push-campaigns`
- `PUT /api/admin/push-campaigns/<campaign_id>`
- `POST /api/admin/push-campaigns/<campaign_id>/prepare`
- `POST /api/admin/push-campaigns/<campaign_id>/schedule`
- `POST /api/admin/push-campaigns/<campaign_id>/cancel`
- `POST /api/admin/push-campaigns/<campaign_id>/copy-version`
- `POST /api/admin/membership-expiry-reviews/<line_user_id>/resolve`

不存在任何 send-now 或立即發送路由。

## 11. 後台介面

### 11.1 清單

顯示名稱、內容摘要、適用方案、指定會員數、預定時間、建立人、建立時間、目前版本、成功／失敗數量與狀態。提供狀態、日期、方案及關鍵字篩選。

### 11.2 編輯

- 純文字模式提供字數提示與實際文字預覽。
- 模板模式只能選核准模板及填入模板允許的參數。
- 受眾可複選方案及搜尋個別會員。
- 排程確認前顯示目前預估人數，並清楚提示「實際名單會在發送當下重新確認」。
- 儲存按鈕文案為「儲存草稿」或「儲存新版本」，不能使用容易誤解為發送的文字。

### 11.3 詳細資料

分成「推播資料、修改歷程、發送紀錄、事件紀錄」四區。舊版本只能查看或複製成新版本，不能覆蓋、刪除或直接恢復。

### 11.4 期限待確認

顯示會員姓名、LINE UID、目前方案、可用的歷史依據與缺少原因。最高管理員輸入可信任的生效時間後，系統依方案週期計算到期日並留下稽核紀錄。

## 12. 錯誤呈現

錯誤分類沿用並擴充 `push_delivery.py`：

- 永久失敗：無效 UID、封鎖或非好友、訊息格式不合法。
- 暫時失敗：逾時、LINE 5xx、短期限流。
- 系統設定：Token 無效、必要環境變數缺少。
- 額度限制：月額度或發送頻率限制。

後台先顯示自然繁中原因與處理方式；原始英文技術訊息放在可展開區塊，不直接當作主要錯誤文字。

## 13. 遷移

- 新集合採惰性初始化，不清空或重寫現有狀態。
- 既有 `notification_logs` 保持原順序與內容。
- 付費期限回填只使用可證明的付款或異動時間。
- 無可靠時間者只加上待確認標記，不改動現有到期日與方案。
- G799 只在管理員明確設定起訖時間後生效。
- 遷移可重複執行，相同會員不得重複新增異動事件。

## 14. 測試與驗收

### 14.1 會員期限

- 14 天體驗在第 7 天升級 799，付費期限從升級時間起算，但隔天簽到仍是第 8 天。
- 399 升級 799 時，月繳／年繳期限從升級成功時間重新起算。
- 升級不清除簽到紀錄、連續天數、會員等級、守護人或提醒設定。
- B399／B799 維持原封測起訖與 Day 1～21。
- G799 依管理員設定起訖生效。
- 缺少可靠時間的既有會員進入待確認名單，且不自動猜日期。

### 14.2 推播核心

- 每個合法與非法狀態轉換都有測試。
- 每次儲存建立新版本，舊版本內容完全不變。
- 草稿、儲存、預覽、複製版本不會呼叫 LINE sender。
- 已排程內容修改後退回待排程。
- 發送當下重新判斷方案，方案名單與指定會員依 UID 去重。
- 收件人快照保存姓名、UID、當時方案與預定時間。
- 租約競爭、程序中斷與重跑不會重複發送。
- 24 小時內補送；超過 24 小時自動取消。
- 暫時錯誤最多三次，永久錯誤不重試。
- 全部成功、部分失敗、全部失敗得到正確最終狀態。

### 14.3 API、權限與介面

- `super_admin` 可寫入，其他角色所有寫入路由皆為 403。
- 所有寫入路由要求有效 CSRF。
- 不存在立即發送按鈕、函式或 API。
- 管理頁支援固定白名單網址、手機抽屜、鍵盤操作及至少 16px 主要文字。
- 所有伺服器資料在插入畫面前完成 escaping。
- 系統推播與自訂 campaign delivery 都能在發送紀錄查詢。

### 14.4 基準測試政策

建立分支時 `origin/main@c502423` 已有既存失敗：JavaScript 106 項中 8 項失敗；本機 Python 3.14 執行 722 項時有 84 項失敗、18 項錯誤，部分來自專案 Python 3.11 與本機依賴／編碼差異。這些既存失敗不納入本功能修復範圍。

本次新增與直接相關測試必須全部通過，且不得增加新的既存失敗。Python 語法、Git 差異檢查及 Render Python 3.11 部署建置必須通過。

## 15. 部署與安全驗證

- 合併前備份正式 PostgreSQL 狀態。
- 先合併至 GitHub `main`，由 Render 自動部署。
- 確認 `/health` 為 200、PostgreSQL 持久化正常、最新 commit 為 live。
- 正式站只驗證登入、清單、草稿、版本、預覽、排程前狀態及唯讀紀錄，不建立會觸發真實會員推播的到期排程。
- 實際 LINE 驗收只能使用白名單測試帳號，並由最高管理員另行建立未到期測試排程。

## 16. 不在本次範圍

- 任意 Flex JSON 編輯器。
- 立即發送。
- 手動重送失敗收件人按鈕。
- 刪除推播、版本或發送紀錄。
- Redis、Celery 或額外背景 Worker。
- 修復 `origin/main@c502423` 已存在且與本功能無關的測試失敗。
