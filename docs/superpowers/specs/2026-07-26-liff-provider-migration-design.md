# LIFF Provider 遷移設計

## 背景

目前正式 Messaging API Channel「每日平安」位於 Provider「今天你在嗎｜每日簽到」，舊 LINE Login／LIFF 位於另一個 Provider「還活著嗎」。LINE 會依 Provider 核發 user ID，因此同一位使用者在兩個 Provider 取得不同 ID，造成網站顯示守護人已綁定，但 Messaging API 推播回覆「未加入官方帳號好友」。

新的 LINE Login Channel 已建立在正式 Messaging API 相同的 Provider：

- LINE Login Channel ID：`2010848330`
- LIFF ID：`2010848330-UAiqPPYD`
- LIFF URL：`https://liff.line.me/2010848330-UAiqPPYD`
- Endpoint：`https://alive-checkin.onrender.com/`
- 狀態：Published
- Linked LINE Official Account：每日平安
- shareTargetPicker：Enabled

## 目標

所有正式入口改用新 LIFF，確保 LINE Login 與 Messaging API 對同一使用者取得相同 user ID。保留舊資料與舊入口的可恢復性，不把不同 Provider 的 user ID 當成同一人自動合併。

## 系統設定

正式環境使用：

- `LINE_LOGIN_CHANNEL_ID=2010848330`
- `LIFF_ID=2010848330-UAiqPPYD`

若後端有 ID token audience 驗證，必須使用新的 LINE Login Channel ID。Messaging API 的 access token 與 channel secret 維持「每日平安」正式 Channel，不得改用舊 Provider 的 Messaging API 憑證。

## 入口更新

下列位置統一改用新 LIFF ID，不得保留正式流量指向舊 LIFF：

- 網站的 `liff.init()`。
- LINE 圖文選單。
- 歡迎訊息與主功能 Flex。
- 一鍵邀請守護人。
- 守護群建立、綁定、狀態與教學卡片。
- SOS、報平安、安全守護與會員中心捷徑。
- 好友分享、邀請 QR Code 及原生 LINE 分享內容。
- 後端產生的 LIFF deep link。
- 文件、環境範例與產品規則測試。

所有 deep link 保留原有查詢參數，例如 `open`、`page`、`invite_from`、`friend_invite`，只替換 LIFF host ID。

## 舊連結相容

舊 LIFF 仍暫時保留，不立即刪除。舊入口載入時顯示明確更新提示並導向新 LIFF，且保留安全的功能參數。不得在兩個 LIFF 之間傳送 access token、ID token、舊 user ID 或其他登入憑證。

若 LINE 平台或瀏覽器限制自動 LIFF-to-LIFF 導向，畫面顯示單一大按鈕「開啟新版每日平安」，由使用者點擊新 LIFF URL。

## 會員資料與重新綁定

- 新 LIFF 第一次開啟時，使用者重新授權並以新 Provider user ID 建立或取得會員資料。
- 不依顯示名稱、電話或頭像自動合併舊、新帳號，避免把不同人合併。
- 舊資料保留，不因新登入而刪除。
- 若未來需要搬移歷史資料，另做具備雙邊身分證明的帳號遷移流程，不納入本次。
- 已有核心守護人須由會員重新發送一次新邀請；守護人從新 LIFF 接受後，保存與 Messaging API 相容的 user ID。
- 綁定成功後立即向會員與守護人各發一則確認訊息；任一推播失敗時顯示具體原因。

## 一鍵分享

一鍵邀請按鈕直接呼叫新 LIFF 的 `shareTargetPicker`，讓使用者選擇 LINE 好友，不先跳回首頁。分享內容中的接受網址使用新 LIFF ID，並保留 `invite_from`。

若不在 LINE App、未授權或分享選擇器失敗，只顯示重新從 LINE 開啟的提示；不以剪貼簿或不明外部分享作為靜默備援。

## 發布順序

1. 部署支援新 LIFF ID 與舊連結提示的程式版本。
2. 在 Render 設定並儲存 `LINE_LOGIN_CHANNEL_ID` 與 `LIFF_ID`。
3. 驗證新 LIFF 登入、狀態 API、報平安、一鍵分享與重新綁定。
4. 以新 LIFF URL 重新發布 LINE 圖文選單。
5. 驗證安全守護能向重新綁定的守護人推播。
6. 保留舊 LIFF 一段遷移期；在確認無正式入口使用後，再另行決定是否下架。

## 驗證

- 程式碼與設定中不得殘留正式入口使用舊 LIFF ID。
- ID token audience 使用新 Channel ID。
- 各 deep link 的功能參數在換 ID 後仍正確。
- 一鍵邀請直接打開 shareTargetPicker。
- 新會員與重新授權會員可以登入。
- 新邀請完成後，會員及守護人的雙向通知成功。
- 安全守護的目標數、成功數、失敗對象與 LINE 錯誤原因正確顯示。
- 舊 user ID 不會被錯誤當成新 Provider user ID。
- 全部 Python 與前端行為測試通過後才建立 PR、合併及部署。

