# 今天還在嗎

一個每日平安簽到小工具。可以直接開 `index.html` 使用瀏覽器儲存，也可以啟動 Flask 後端，把資料存到本機 JSON 檔，並支援 LINE LIFF 內嵌、推播提醒、緊急聯絡人與後台管理。

完整操作與上線流程請看：`流程說明.md`  
定位功能與方案權限請看：`定位功能規格.md`

## 商業後台、GA4 與 SEO

正式後台位於 `/admin.html`，包含會員、守護營運、訂單、客服、站內轉換漏斗、LINE 推播成功率與公開頁 SEO 稽核。

管理員權限採最小權限原則。既有 `ADMIN_PASSWORD` 維持超級管理員，不設定其他角色密碼也不影響原部署：

```text
ADMIN_OPERATIONS_PASSWORD=營運客服密碼
ADMIN_FINANCE_PASSWORD=財務人員密碼
ADMIN_VIEWER_PASSWORD=唯讀人員密碼
LINE_MONTHLY_MESSAGE_LIMIT=200
LINE_MESSAGE_WARNING_PERCENT=80
LINE_MESSAGE_HARD_STOP_PERCENT=100
```

- 超級管理員：全部權限
- 營運客服：會員、通知、客服與事件結案
- 財務人員：訂單與付款操作
- 唯讀人員：只可查看

所有寫入操作仍需 Session 與 CSRF；權限不足會回傳 `403 forbidden` 並寫入去識別化稽核紀錄。事件中心可將 SOS 或通知失敗標記結案，處理摘要不會寫進稽核 metadata。

後台另提供 21 天封測 `10／20／10` 固定名額、隱私權申請處理佇列，以及 LINE 月用量預警與非緊急推播硬上限。達到 `LINE_MESSAGE_HARD_STOP_PERCENT` 時，系統停止每日一般提醒、補資料提醒、續費提醒與批次重送；SOS 與安全事件不受此限制。後台用量是依系統推播紀錄估算，正式用量與費用仍以 LINE 官方後台為準。

若要讓後台辨識 GA4 報表串接已完成，請在 Render 設定：

```text
GA4_PROPERTY_ID=properties/你的資源編號
GA4_SERVICE_ACCOUNT_JSON=完整服務帳號 JSON
```

後台只回傳「是否已設定」，不會把 Property ID、私鑰或 LINE token 傳到瀏覽器。未設定時會顯示「GA4 尚未連接」，不會用假數據代替正式流量。

## 直接開啟

雙擊 `index.html` 就能用。這個模式會用瀏覽器的 localStorage 存資料。

## 啟動後端

```bash
pip install -r requirements.txt
python app.py
```

開啟：

```text
http://127.0.0.1:5000
```

資料會存在：

```text
data/state.json
```

（實際會自動遷移為 SQLite `data/state.db`。）

## Render Free：磁碟與環境變數注意

Render **free** web service 的本機磁碟是 **ephemeral（暫存）**：

- 每次 redeploy / 休眠喚醒 / 重啟，`data/` 下的 SQLite 可能被清掉 → `users_total` 變 0
- LIFF 會以為「帳號壞了」，其實只是 DB row 消失；LINE userId / token 通常沒壞
- `/callback` webhook 若回 `LINE credentials are not configured`，代表 **Render Environment Variables 被清空**（比磁碟更嚴重）

建議：

1. 升級方案並掛 **Persistent Disk**（例如掛在 `/var/data`），設 `DATA_FILE=/var/data/state.json`
2. 絕對不要整批清空 Render env；`LINE_CHANNEL_ACCESS_TOKEN` / `LINE_CHANNEL_SECRET` / `LIFF_ID` 缺一不可
3. 程式已支援：LIFF `/api/status` 在身分驗證通過時會 **auto-register**；Follow /「開始」也會寫入 users

## LINE 內嵌與推播

需要在 LINE Developers 建好：

- Messaging API Channel：拿 `Channel access token`
- LIFF App：把 endpoint 設成你的公開網址，例如 `https://你的網域/`

啟動前設定環境變數：

```bash
set LIFF_ID=你的 LIFF ID
set LINE_CHANNEL_ACCESS_TOKEN=你的 Channel access token
set APP_PUBLIC_URL=https://你的網域
set ADMIN_PASSWORD=你的後台密碼
set APP_TIMEZONE=Asia/Taipei
set CRON_SECRET=你的排程密鑰
python app.py
```

前台網址：

```text
/
```

後台網址：

```text
/admin
```

LINE 推播提醒可由後台按鈕手動送出，也可由 Render Cron Job 自動送出。使用者必須先加你的 LINE 官方帳號好友，且曾經從 LIFF 頁面進來完成註冊。

## LIFF Provider 遷移與正式驗收

安全帳號搬家必須先部署後端，再切換舊 LIFF。合併到 `main` 並確認
Render 已完成含搬家 API 的部署後，在 `alive-checkin` Web Service →
**Environment** 逐一新增或確認：

```text
ACCOUNT_MIGRATION_SECRET=至少 32 bytes 的獨立隨機密鑰
LEGACY_LINE_LOGIN_CHANNEL_ID=舊 LINE Login Channel ID
LINE_LOGIN_CHANNEL_ID=2010848330
LEGACY_LIFF_ID=舊 LIFF ID
LIFF_ID=2010848330-UAiqPPYD
```

`ACCOUNT_MIGRATION_SECRET` 不可沿用 LINE token、Channel Secret、管理員密碼，
也不可寫入 git、日誌或交接文件。不要使用「Clear all」或先刪除整批環境
變數的方式更新。`LINE_CHANNEL_ACCESS_TOKEN` 與 `LINE_CHANNEL_SECRET` 是既有
Messaging API 憑證，**不可替換、不可清空**；其餘既有 Render 變數也必須
保留。儲存後只重啟／部署這個 web service，等待健康檢查成功，再進行下列
smoke test：

搬家資料會在一般操作與 maintenance cleanup 中自動整理：已完成／過期
ticket 保留 30 天（每來源最多 20、全域最多 2,000），去識別 audit 保留
90 天（全域最多 1,000），snapshot 依既有 `purge_after` 保留 30 天；
disabled alias 不自動刪除。每個來源 10 分鐘最多建立 5 次，無效兌換全域
10 分鐘最多 30 次；超限固定回 `429 rate_limited`，不揭露帳號或代碼。

正式人工驗收請由兩個已加入官方帳號好友的 LINE 帳號完成：

1. 在瀏覽器或 Render Shell 確認 `https://alive-checkin.onrender.com/api/config` 回傳的 `liff_id` 是 `2010848330-UAiqPPYD`，且 `legacy_liff_id` 是預期舊入口。
2. 在舊 LIFF App 將 Endpoint URL 指向 `https://alive-checkin.onrender.com/liff/migrate.html`。
3. 以一個非正式／非生產會員走完舊 LIFF 產生代碼、新 LIFF 兌換與重新開啟流程。
4. 在 session-authenticated 後台確認「帳號搬家」成功數與 moved-record counts 增加，且舊帳號再次進入時只收到開啟目前 LIFF 的安全導引。
5. 在 LINE 開啟 `https://liff.line.me/2010848330-UAiqPPYD`，授權後確認可到帶有 `open` 參數的目標畫面，例如 `https://liff.line.me/2010848330-UAiqPPYD?open=guard`。
6. 由會員選「一鍵邀請」，確認直接開啟 LINE 的 `shareTargetPicker`，再由第二個帳號完成守護人綁定；兩個帳號都必須收到「綁定成功」訊息。
7. 以已綁定且可推播的單一守護人帳號開啟「安全守護」，允許定位；回應／後台紀錄必須顯示 `target_count=1`、`sent=1`，守護人必須收到含位置連結的通知。
8. 使用正式的 Messaging API token 發布目前圖文選單（token 不寫入檔案或命令歷史）：

   ```bash
   read -rsp 'LINE Messaging API token: ' RICH_MENU_TOKEN; printf '\n'
   LINE_CHANNEL_ACCESS_TOKEN="$RICH_MENU_TOKEN" \
     /tmp/alive-checkin-sos-venv/bin/python scripts/setup_line_rich_menu.py
   unset RICH_MENU_TOKEN
   ```

舊 LIFF 至少保留 30 天，不可在 rollout 當天刪除。開啟舊連結時，handoff
只可帶轉 `open`、`page`、`friend_invite`；不得轉送 `invite_from`、舊
Provider user ID、access token、ID token 或其他登入憑證。

若 smoke test 或正式切換失敗，將 Render 恢復到上一個成功 deploy；**不要**
刪除 migration tickets、aliases、snapshots 或 audit state，也不要輪替
`ACCOUNT_MIGRATION_SECRET`，直到工程人員確認未完成代碼的處理方式。

## 自動推播

- 未填緊急聯絡人：每天台灣時間 09:00 自動檢查，沒有至少 1 位聯絡人就推 LINE Bot 提醒。
- 每日簽到提醒：系統每 15 分鐘檢查一次，到了用戶自己設定的提醒時間，且今天還沒簽到，就推 LINE Bot 提醒。
- 資料清理：每天台灣時間 02:30 清除過期位置、超過 7 天的好友邀請碼與超過 90 天的通知紀錄，不會刪除訂單。
- `CRON_SECRET` 是排程呼叫用密鑰，web service 和三個 cron job 要填同一組值。
- 後台的「提醒填聯絡人」仍可手動補發，平常不用每天自己按。
- `/health` 提供 Render 健康檢查；每 15 分鐘的簽到提醒排程也會定期呼叫服務。

## 方案與緊急聯絡人

目前內建 14 天安心體驗與 6 種月費／年費方案：

- 199 月費：核心守護人 2 位、緊急聯絡人 4 位、每日提醒 1 次、安全守護 1 小時
- 199 年費：核心守護人 3 位、緊急聯絡人 10 位、每日提醒 2 次、安全守護 1 小時
- 399 月費／年費：每日可選 1～2 次；預設 12:00、18:00
- 799 月費／年費：每日可選 1～3 次；預設 12:00、18:00，第 3 次預設 22:00
- 399 提供安全守護 1／3 小時；799 提供 1／3／6／8 小時
- 所有方案完成今日簽到後，當天剩餘提醒自動停止

年付方案採 10 個月價，送 2 個月：

- 199 年付：NT$1,990 / 年
- 399 年付：NT$3,990 / 年，另送 30 天即時追蹤體驗
- 799 年付：NT$7,990 / 年

前台可新增緊急聯絡人，系統會依目前方案限制數量。後台可手動調整使用者方案，方便 MVP 階段先用藍新金流付款連結收款後，再人工開通。

## API

- `GET /api/status`：取得目前狀態
- `POST /api/checkin`：完成簽到
- `POST /api/settings`：儲存聯絡人、逾時未報平安時數（`grace_hours`：24／48／72，預設 48）、提醒時間；`warning_cancel_minutes` 預設 15（滿 N 小時後短暫可取消緩衝）
- `GET /api/contacts`：取得緊急聯絡人
- `POST /api/contacts`：儲存緊急聯絡人，會依方案限制數量
- `POST /api/friends/invite`：產生好友邀請碼
- `POST /api/friends/accept`：接受好友邀請碼
- `GET /api/friends/locations`：取得好友目前分享中的位置
- `POST /api/location/update`：主動分享目前位置
- `POST /api/location/stop`：停止分享目前位置
- `POST /api/account/export`：匯出會員完整個人資料與相關紀錄
- `POST /api/account/delete`：刪除會員資料與關聯，付款訂單會去識別化留存
- `POST /api/sos`：依方案通知核心守護人與有效守護群
- `POST /api/guardian-groups/unbind`：會員解除自己建立的守護群
- `POST /api/line/register`：註冊 LINE 使用者
- `GET /api/admin/summary`：後台總覽
- `GET /api/admin/account-migrations`：session-authenticated、唯讀且去識別化的帳號搬家 totals／最近事件
- `POST /api/admin/user-plan`：後台調整使用者方案
- `POST /api/admin/send-reminders`：推播逾期提醒
- `POST /api/admin/send-contact-reminders`：手動提醒未填緊急聯絡人的用戶
- `GET /api/admin/beta-program`：查看 21 天封測三組名額與名單
- `POST /api/admin/beta-program/assign`：將既有會員加入封測
- `POST /api/admin/beta-program/update`：更新封測完成／退出狀態
- `POST /api/account/privacy-request`：會員建立資料匯出、刪除、更正或查詢申請
- `GET /api/admin/privacy-requests`：後台查看隱私權申請
- `POST /api/admin/privacy-requests/update`：更新隱私申請處理狀態
- `POST /api/cron/contact-reminders`：排程提醒未填緊急聯絡人的用戶
- `POST /api/cron/checkin-reminders`：排程推播每日簽到提醒
- `POST /api/cron/data-cleanup`：排程清理過期暫存資料

Email 通知需要另外接 SMTP 或寄信服務，這版先保留欄位和 API。LINE 推播已先接好後端流程。
## LINE 圖文選單 6 格

新版圖文選單已改成這 6 格，第二格正式改為「綁定守護人」：

1. 今日簽到
2. 綁定守護人
3. 我的狀態
4. 查看方案
5. 問與答
6. 聯絡客服

相關檔案：

- `line-rich-menu.png`：可上傳到 LINE 官方帳號的圖文選單圖片
- `line-rich-menu-config.json`：LINE Rich Menu API 設定檔
- `scripts/generate_rich_menu_image.py`：重新產生圖片
- `scripts/setup_line_rich_menu.py`：用 `LINE_CHANNEL_ACCESS_TOKEN` 建立並設成預設圖文選單

LINE Webhook 網址請填：

```text
https://你的網域/callback
```

需要設定的環境變數：

```text
LINE_CHANNEL_ACCESS_TOKEN=你的 Channel access token
LINE_CHANNEL_SECRET=你的 Channel secret
```
