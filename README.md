# 還活著嗎

一個每日平安簽到小工具。可以直接開 `index.html` 使用瀏覽器儲存，也可以啟動 Flask 後端，把資料存到本機 JSON 檔，並支援 LINE LIFF 內嵌、推播提醒、緊急聯絡人與後台管理。

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

LINE 推播提醒會從後台按鈕送出，只有「已逾期」的 LINE 使用者會收到。使用者必須先加你的 LINE 官方帳號好友，且曾經從 LIFF 頁面進來完成註冊。

## 方案與緊急聯絡人

目前內建 7 天免費體驗與 4 種方案限制：

- 免費 / 體驗：1 位緊急聯絡人、每日 1 次提醒、LINE 通知
- 199 元：2 位緊急聯絡人、每日 2 次提醒、LINE 通知
- 399 元：5 位緊急聯絡人、每日 2 次提醒、LINE 通知
- 799 元：10 位緊急聯絡人、每日 2 次提醒、LINE + SMS + 電話

前台可新增緊急聯絡人，系統會依目前方案限制數量。後台可手動調整使用者方案，方便 MVP 階段先用藍新金流付款連結收款後，再人工開通。

## API

- `GET /api/status`：取得目前狀態
- `POST /api/checkin`：完成簽到
- `POST /api/settings`：儲存聯絡人、寬限時間、提醒時間
- `GET /api/contacts`：取得緊急聯絡人
- `POST /api/contacts`：儲存緊急聯絡人，會依方案限制數量
- `POST /api/line/register`：註冊 LINE 使用者
- `GET /api/admin/summary`：後台總覽
- `POST /api/admin/user-plan`：後台調整使用者方案
- `POST /api/admin/send-reminders`：推播逾期提醒

Email 通知需要另外接 SMTP 或寄信服務，這版先保留欄位和 API。LINE 推播已先接好後端流程。
