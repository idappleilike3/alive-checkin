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

## 會員資料與一次性安全搬家

新、舊 Provider 對同一位 LINE 使用者核發不同 user ID。新 LIFF 第一次開啟時不得只建立空白會員，也不得依顯示名稱、電話或頭像猜測合併。

### 雙邊身分證明

安全搬家必須由同一個人先後完成兩次有效 LIFF 登入：

1. 舊 LIFF 使用舊 Channel 完成身分驗證。
2. 後端產生 10 分鐘有效、只能使用一次的隨機搬家碼。
3. 後端只保存搬家碼的雜湊、舊 user ID、建立時間、到期時間與使用狀態。
4. 舊 LIFF 導向新 LIFF時只攜帶搬家碼，不得攜帶舊 user ID、access token 或 ID token。
5. 新 LIFF 使用新 Channel 完成身分驗證後，以新 user ID 兌換搬家碼。
6. 後端在同一個資料鎖／交易範圍內完成搬移、稽核與搬家碼作廢。

搬家碼不得寫入應用程式日誌、管理員稽核 metadata、錯誤追蹤或分析事件。

### 搬移範圍

下列資料由舊會員身分搬到新會員身分：

- 會員方案、試用狀態與到期日。
- 報平安設定、提醒時段與簽到紀錄。
- 核心守護人、緊急聯絡人與守護群關聯。
- 位置共享授權、有效期限與安全設定；已過期位置不搬移。
- 通知偏好、日曆／備忘錄、客服與隱私權申請紀錄。
- 訂單、付款對帳關聯與後台備註。

通知、稽核與 SOS 歷史保留原始事件內容，但索引會員改為新 user ID，並記錄匿名化的 migration event id。

### 衝突規則

- 新帳號只有自動建立的空白資料時，由舊資料完整取代。
- 新帳號已有真實資料時不得靜默覆蓋；以舊帳號為主體，合併不重複的紀錄，採用較晚更新的偏好設定，保留較高且仍有效的付費權益。
- 同一筆守護關係、訂單或簽到紀錄以穩定業務 ID 去重，不以姓名去重。
- 新、舊 user ID 相同時拒絕搬家。
- 搬家碼過期、已使用、來源會員不存在或目標衝突無法安全合併時，不改動任何資料。

### 搬家後狀態

- 舊 user ID 保存為不可登入的遷移別名，避免舊 webhook 事件重新建立另一份會員。
- 新 user ID 成為唯一可登入主身分。
- 已有守護人關係會保留，但因守護人也可能仍是舊 Provider 身分，畫面必須標示「等待守護人完成新版綁定」。
- 守護人完成新版綁定後，會員與守護人各收到一則確認訊息；任一推播失敗時顯示具體原因。
- 搬家完成頁顯示搬移的方案、提醒、紀錄與守護關係數量，不顯示任何 LINE user ID。

### 失敗與復原

- 搬家採先建立加密前快照、再原子更新；任一步失敗即回復原狀。
- 每次嘗試寫入 `account_migration_audit`，只記錄事件 ID、結果、時間與非敏感計數。
- 管理後台只能查看搬家結果與重試原因，不能手動輸入兩個 LINE user ID 強制合併。
- 原始帳號資料至少保留 30 天的可復原快照，期滿後依隱私與保存政策處理。

## 一鍵分享

一鍵邀請按鈕直接呼叫新 LIFF 的 `shareTargetPicker`，讓使用者選擇 LINE 好友，不先跳回首頁。分享內容中的接受網址使用新 LIFF ID，並保留 `invite_from`。

若不在 LINE App、未授權或分享選擇器失敗，只顯示重新從 LINE 開啟的提示；不以剪貼簿或不明外部分享作為靜默備援。

## 發布順序

1. 部署同時支援舊、新 LIFF 驗證與一次性安全搬家的程式版本。
2. 在舊 LIFF Endpoint 啟用搬家起點，但不轉送舊 user ID。
3. 在 Render 設定並儲存 `LINE_LOGIN_CHANNEL_ID` 與 `LIFF_ID`。
4. 以測試會員驗證搬家前後的方案、提醒、紀錄與守護關係計數。
5. 驗證新 LIFF 登入、狀態 API、報平安、一鍵分享與守護人新版綁定。
6. 以新 LIFF URL 重新發布 LINE 圖文選單。
7. 驗證安全守護能向完成新版綁定的守護人推播。
8. 保留舊 LIFF 搬家入口至少 30 天；確認無待搬會員後，再另行決定是否下架。

## 驗證

- 程式碼與設定中不得殘留正式入口使用舊 LIFF ID。
- ID token audience 使用新 Channel ID。
- 各 deep link 的功能參數在換 ID 後仍正確。
- 一鍵邀請直接打開 shareTargetPicker。
- 新會員與重新授權會員可以登入。
- 搬家碼只能使用一次，10 分鐘後失效，且網址與日誌中沒有舊 user ID。
- 搬家失敗不會留下半套資料；搬家成功後舊身分不能重新建立重複會員。
- 方案、提醒、簽到、守護關係、訂單及申請紀錄依規則完整搬移。
- 新邀請完成後，會員及守護人的雙向通知成功。
- 安全守護的目標數、成功數、失敗對象與 LINE 錯誤原因正確顯示。
- 舊 user ID 不會被錯誤當成新 Provider user ID。
- 全部 Python 與前端行為測試通過後才建立 PR、合併及部署。
