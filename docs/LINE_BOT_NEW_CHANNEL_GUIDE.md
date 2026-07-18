# LINE Bot 新頻道申請教學

> 給蝦董明早照著做。
> 預計時間:15 分鐘。
>
> ⚠️ **重要**:alive_checkin 不能用 emotion-bridge 的 Bot(會 postback 衝突)。**必須新開一個**。

---

## 一、為什麼要新開 Bot

| 風險 | 後果 |
|---|---|
| Postback data 衝突 | 失聯預警按鈕跟情緒分析按鈕一樣的 key |
| 訊息額度混用 | 失聯預警被情緒分析吃掉 |
| 用戶混淆 | 同一個 Bot 出現兩種用途的訊息 |
| Webhook 路由複雜 | 一個 Bot 處理兩個業務邏輯 |

---

## 二、申請流程

### 步驟 1:登入 LINE Developers

1. 開瀏覽器 → https://developers.line.biz/console/
2. 用您 emotion-bridge 同一個 LINE 帳號登入
3. 進入 Provider 列表

### 步驟 2:建立新 Channel

1. 找到您現有的 Provider(可能是「情感解碼」或您公司名)
2. 點進去 → 右上角「Create a new channel」
3. 選 **「Messaging API」**
4. 填寫:
   - **Channel name**:`alive_checkin` 或 `今天還在嗎 - 安全守護`
   - **Channel description**:`台灣用戶每日 LINE 簽到安全守護 Bot`
   - **Category**:選「生活風格」或「健康」
   - **Subcategory**:隨意
5. 同意條款 → 「Create」

### 步驟 3:設定 Channel

1. **Channel 基本設定**:
   - **Channel icon**:上傳 Bot 頭像(建議深紫/暖金)
   - **Privacy Policy URL**:可暫時填您的網站
   - **Terms of Use URL**:可暫時填您的網站

2. **Messaging API 設定**:
   - **Channel access token**:
     - 點「Issue」產生 token
     - **複製保存**(只顯示一次)
     - 放進 `.env` 的 `LINE_CHANNEL_ACCESS_TOKEN=...`
   - **Channel secret**:
     - 在「Basic settings」頁
     - 複製保存
     - 放進 `.env` 的 `LINE_C…RET=...`
   - **Webhook URL**:**先不填**(等部署到 Render 再回來設)
   - **Use webhook**:開啟
   - **Auto-reply messages**:關閉(我們自己處理)
   - **Greeting messages**:關閉(我們自己送歡迎)

### 步驟 4:加 Bot 為好友(測試用)

1. 在 Channel 頁面找「**Messaging API**」標籤
2. 找到 QR Code
3. 用您自己的 LINE 掃描加好友
4. 確認 Bot 出現在您的好友列表

---

## 三、把 Token / Secret 給我看

把這兩段給我,我幫您:

```
LINE_CHANNEL_ACCESS_TOKEN=很長的字串...(從 Messaging API 設定頁)
LINE_C…RET=另一段字串...(從 Basic settings 頁)
```

**不會 commit 到 Git**(已 .gitignore),只是填進 `.env`。

---

## 四、暫時不能做的(等部署完才能做)

### 4.1 Webhook URL 設定

要等您部署 `app.py` 到 Render,拿到公開網址(像 `https://alive-checkin-2026-07-xx.onrender.com`)後才能設。

### 4.2 LINE Official Account 申請

如果您還沒申請 LINE OA(就是把 Bot 變成「官方帳號」,有 Basic ID 如 `@xxx`),需要另外到 https://www.linebiz.com/ 申請。

**申請需要**:
- Email(已用過的)
- 公司 / 行號(個人戶也可,但功能受限)
- 手機號碼

---

## 五、費用

LINE Bot **本身免費**,但有「訊息則數」分級:

| 方案 | 月費 | 訊息則數 |
|---|---|---|
| 輕用量 | 免費 | 500 |
| 中用量 | NT$800 | 15,000 |
| 高用量 | NT$2,400 | 45,000 |

**alive_checkin 起步建議**:
- **中用量 NT$800/月**(15,000 則)
- 100 用戶 × 5 則/天 × 30 天 = 15,000 則 → 剛好

**升級時機**:用戶數 > 200 → 改高用量 NT$2,400。

---

## 六、Channel 命名建議

| 用途 | 命名 |
|---|---|
| Channel name | `alive_checkin` 或 `今天還在嗎` |
| Channel icon | 深紫 / 暖金(跟 emotion-bridge 一致) |
| Bot 顯示名稱 | `今天還在嗎` |
| Bot 自我介紹 | `我是您的每日安全守護助手,有任何問題傳「客服」給我` |

---

## 七、測試清單

申請完後確認:

- [ ] Channel 已建立
- [ ] `LINE_CHANNEL_ACCESS_TOKEN` 已取得
- [ ] `LINE_C…RET` 已取得
- [ ] 兩個值已填進 `.env`
- [ ] 已加 Bot 為好友
- [ ] 給我兩個 token 我幫您驗證

---

**預計明早完成時間:15 分鐘**。先就寢!🌙