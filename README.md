# 今天還在嗎

一個每日平安簽到小工具。可以直接開 `index.html` 使用瀏覽器儲存，也可以啟動 Flask 後端，把資料存到本機 JSON 檔，並支援 LINE LIFF 內嵌、推播提醒、緊急聯絡人與後台管理。

完整操作與上線流程請看：`流程說明.md`  
定位功能與方案權限請看：`定位功能規格.md`

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

## 自動推播

- 未填緊急聯絡人：每天台灣時間 09:00 自動檢查，沒有至少 1 位聯絡人就推 LINE Bot 提醒。
- 每日簽到提醒：系統每 15 分鐘檢查一次，到了用戶自己設定的提醒時間，且今天還沒簽到，就推 LINE Bot 提醒。
- 資料清理：每天台灣時間 02:30 清除過期位置、超過 7 天的好友邀請碼與超過 90 天的通知紀錄，不會刪除訂單。
- `CRON_SECRET` 是排程呼叫用密鑰，web service 和三個 cron job 要填同一組值。
- 後台的「提醒填聯絡人」仍可手動補發，平常不用每天自己按。
- `/health` 提供 Render 健康檢查；每 15 分鐘的簽到提醒排程也會定期呼叫服務。

## 方案與緊急聯絡人

目前內建 7 天安心體驗與 6 種月費／年費方案：

- 199 月費：4 位守護人與好友定位、每日提醒 1 次、24 小時快照定位、LINE 通知 3 位核心守護人
- 199 年費：6 位守護人與好友定位、每日提醒 2 次、軌跡回放 3 天、LINE 通知 3 位核心守護人
- 399 月費：15 位守護人與好友定位、每日提醒 2 次、即時追蹤、軌跡回放 5 天、LINE 通知 3 位核心守護人
- 399 年費：20 位守護人與好友定位、每日提醒 3 次、軌跡回放 7 天、30 天即時追蹤體驗、LINE 通知 3 位核心守護人
- 799 月費：25 位守護人與好友定位、每日提醒 3 次、一鍵 SOS、軌跡回放 14 天、LINE＋簡訊通知 3 位核心守護人
- 799 年費：50 位守護人與好友定位、每日提醒 5 次、一鍵 SOS、軌跡回放 30 天、LINE＋簡訊＋電話通知 5 位核心守護人

年付方案採 10 個月價，送 2 個月：

- 199 年付：NT$1,990 / 年
- 399 年付：NT$3,990 / 年，另送 30 天即時追蹤體驗
- 799 年付：NT$7,990 / 年

前台可新增緊急聯絡人，系統會依目前方案限制數量。後台可手動調整使用者方案，方便 MVP 階段先用藍新金流付款連結收款後，再人工開通。

## API

- `GET /api/status`：取得目前狀態
- `POST /api/checkin`：完成簽到
- `POST /api/settings`：儲存聯絡人、寬限時間、提醒時間
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
- `POST /api/admin/user-plan`：後台調整使用者方案
- `POST /api/admin/send-reminders`：推播逾期提醒
- `POST /api/admin/send-contact-reminders`：手動提醒未填緊急聯絡人的用戶
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
