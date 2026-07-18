# 簡訊王 API 文件研究 v0.1

> **狀態**:Draft v0.1
> **建立日期**:2026-07-17 17:37
> **作者**:小龍蝦
> **目標**:把「簡訊王 SMS API」的 endpoint / auth / encoding 整理出來

---

## 0. TL;DR — 重要發現

| 項目 | 結論 |
|---|---|
| **簡訊王 = kotsms.com.tw** | ✅ 確認。公司名「簡訊王數位媒體股份有限公司」 |
| **smsking.com.tw** | ❌ 不存在(404,多次 web_fetch 都失敗) |
| **公開 API 文件** | ❌ 抓不到(全站 JS-rendered,web_fetch 只回 SPA shell) |
| **客服電話** | **(02)27923939** |
| **聯絡地址** | 台北市中山區南京東路一段 52 號 3 樓 |

**結論**:必須跟業務索取,沒辦法靠 web 抓。

---

## 1. 為什麼抓不到 API 文件

### 1.1 嘗試過的 URL

| URL | 結果 |
|---|---|
| `https://www.smsking.com.tw/` | ❌ fetch failed |
| `https://www.smsking.com.tw/api` | ❌ fetch failed |
| `https://docs.smsking.com.tw/` | ❌ ENOTFOUND(子網域不存在) |
| `https://www.smsking.com.tw/service/api` | ❌ fetch failed |
| `https://www.kotsms.com.tw/` | ✅ 200 OK(但內容只有「簡訊王」+ 公司資訊) |
| `https://www.kotsms.com.tw/api/` | ✅ 200 OK(但內容同上,SPA shell) |
| `https://www.kotsms.com.tw/price/` | ✅ 200 OK(但內容同上) |
| `https://www.kotsms.com.tw/help/` | ✅ 200 OK(但內容同上) |

### 1.2 原因
全站 JavaScript SPA(單頁應用),所有內容都是 client-side render。`web_fetch` 的 readability extractor 抓不到實質內容。

### 1.3 替代方案(蝦董要選一個)

| 方案 | 動作 | 預估時間 |
|---|---|---|
| **A. 業務索取** | 打 (02)27923939 跟業務要 API doc PDF 或 URL | 1-3 天 |
| **B. 註冊後台帳號** | 註冊會員 → 登入後台 → 看會員專區 API 教學 | 30 分鐘 |
| **C. Google 搜尋** | 「kotsms API」「簡訊王 API 文件」找 github 範例或 blog 教學 | 1-2 小時 |

**推薦 A + B 並行**:B 最快拿到完整文件;A 順便談牌價。

---

## 2. 從訓練資料 / 業界知識整理的常見規格(需驗證)

> ⚠️ **這是台灣 SMS API 的常見 pattern,不是簡訊王的確定規格**。要等業務確認。

### 2.1 一般台灣 SMS API 共通特徵

| 項目 | 常見做法 |
|---|---|
| 通訊協定 | HTTP POST(表單編碼)或 HTTPS GET |
| Auth 方式 | username + password(form 欄位) |
| 編碼 | Big5(預設)或 UTF-8(新一點的商) |
| 電話格式 | `09xxxxxxxx`(台灣行動號碼,11 碼) |
| 簡訊長度 | Big5 70 字 / ASCII 160 字(超過切多則) |
| 回傳格式 | URL-encoded string 或 JSON |

### 2.2 簡訊王可能的 endpoint(從業界 pattern 推估)

> ⚠️ **這是估計值**,實際要看業務文件

| 可能 endpoint | 用法 |
|---|---|
| `https://api.kotsms.com.tw/kotsmsapi-1.php` | 最常見的台灣簡訊 API 路徑 pattern |
| `https://www.kotsms.com.tw/api_send.php` | 另一個常見變體 |
| `https://api.kotsms.com.tw/sms/send` | RESTful 風格 |

### 2.3 簡訊王可能的 request 格式

> ⚠️ **這是估計值**

```
POST https://api.kotsms.com.tw/kotsmsapi-1.php
Content-Type: application/x-www-form-urlencoded

username=YOUR_USERNAME&password=YOUR_PASSWORD&dstphone=0912345678&smbody=Hello+Big5
```

**可能欄位**:
| 欄位 | 說明 |
|---|---|
| `username` | 帳號 |
| `password` | 密碼 |
| `dstphone` | 收件人手機(09xxxxxxxx) |
| `smbody` | 簡訊內容(已編碼) |
| `encoding` | `big5`(預設)或 `utf8` |
| `response` | `json` 或 `xml` 或 `string` |

### 2.4 簡訊王可能的 response 格式

> ⚠️ **這是估計值**

```
# 成功
kotsms_status=OK&msgid=xxxxxx

# 失敗
kotsms_status=ERROR&error_code=-10&error_msg=餘額不足
```

**常見 error code**:
| Code | 意義 |
|---|---|
| 0 / OK | 成功 |
| -1 / ERROR | 通用錯誤 |
| -2 | 帳號密碼錯誤 |
| -5 | 餘額不足 |
| -10 | 號碼格式錯誤 |
| -20 | 簡訊內容為空 |
| -99 | 系統錯誤 |

---

## 3. 我們 spec v0.1 的對應(已寫)

`docs/sms_integration_spec.md` 寫的是 placeholder:

```python
SMSKING_API_URL = os.getenv('SMSKING_API_URL', 'https://api.kotsms.com.tw/kotsmsapi-1.php')
```

這個 URL **要用業務確認後的真實 endpoint 替換**。

---

## 4. 蝦董行動清單(本週內)

- [ ] 打 (02)27923939 跟業務談:
  - 索取當下 API 文件
  - 確認 NT$0.85/則 是否當下有效牌價
  - 問最小儲值金額(決定要不要先儲值測試)
  - 問每月發送量級優惠(>1000 則/月的折扣)
- [ ] 註冊會員 → 拿到測試帳號密碼
- [ ] 用測試帳號打一次 API,確認 endpoint/auth/encoding 真的能用
- [ ] 回報業務文件內容,我更新 spec v0.2

---

## 5. 給小龍蝦(我自己)的後續

拿到真實 API 文件後,我會:
1. 把 `docs/sms_integration_spec.md` v0.1 改成 v0.2:
   - `SMSKING_API_URL` 換成真實 endpoint
   - `SendResult` 結構對齊真實 response
   - 錯誤碼對照表對齊真實 error code
2. 實作 `_map_smsking_response(resp) -> SendResult` 對齊真實格式
3. 在 dev 環境(Task 5-4)用測試帳號真的發一則簡訊驗證

---

## 6. 風險與緩解

| 風險 | 緩解 |
|---|---|
| 簡訊王牌價可能不是 NT$0.85 | 業務確認前不上 799,損益模型用「最高 NT$1.5/則」做壓力測試 |
| 編碼 Big5 → 罕用字 / emoji 顯示問號 | 業務確認是否支援 UTF-8;UTF-8 較貴但品質好 |
| 簡訊到達率 < 95% | 加 簡訊到達 callback、3 次重試、發送狀態查詢 API |
| 業務文件沒公開,只給後台會員 | 註冊後台會員 → 後台取得文件 → 我讀後寫 spec v0.2 |
| 簡訊王沒有 webhook / 狀態 callback | 改用「發送後 5 秒查 status API」補救 |

---

## 7. 變更紀錄

| 版本 | 日期 | 作者 | 變更 |
|---|---|---|---|
| v0.1 | 2026-07-17 17:37 | 小龍蝦 | 初版:確認 簡訊王 = kotsms.com.tw、API 文件需業務索取 |