# 簡訊王 kotsms 申請教學

> 給蝦董明早照著做。
> 預計時間:30-40 分鐘(含打電話)。

---

## 一、為什麼選 kotsms(簡訊王)

| 項目 | kotsms | 其他家 |
|---|---|---|
| 單則成本 | NT$0.85 | NT$1.5-2.5 |
| 公司 | 簡訊王數位媒體股份有限公司 | 國際大廠 |
| 中文支援 | ✅ 完全 | 英文為主 |
| 業務接電話 | ✅ 會通 | 客服為主 |
| API 文件 | ✅ 中文 | 英文 |
| 個人戶申請 | ✅ 可 | 多需公司戶 |

---

## 二、申請流程

### 步驟 1:網站註冊(5 分鐘)

1. 開瀏覽器 → https://www.kotsms.com.tw/
2. 右上角「免費註冊」
3. 填寫:
   - **帳號**:自訂(用 email 或公司名)
   - **密碼**:強密碼
   - **姓名**:您真名
   - **Email**:常用 email
   - **手機**:09xxxxxxxx
4. 收驗證信 → 點連結啟用
5. 登入後台

### 步驟 2:儲值(10 分鐘)

1. 後台 → 左邊「儲值」或「線上儲值」
2. **首次建議儲值 NT$500-1,000**(可發 588-1,176 則)
3. 付款方式:
   - **信用卡**:即時入帳
   - **ATM**:1-2 工作天
   - **超商代碼**:1-2 工作天
4. 完成後後台會顯示「點數剩餘」

### 步驟 3:申請 API 權限(5 分鐘)

1. 後台 → 「API 設定」或「開發者中心」
2. 啟用 API 功能
3. 設定 **API 密碼**(跟登入密碼分開)
4. 設定 **IP 白名單**(選配):
   - Render 給的 IP:`<render 出發 IP>`(後台查)
   - 或直接關閉 IP 白名單(預設)
5. 下載 API 文件 PDF(後台「文件下載」)

### 步驟 4:打電話確認(15-20 分鐘)

**業務電話**:(02)27923939
**業務時間**:09:00-18:00(平日)

**電話要問的事**(逐字稿):

```
您好,我是 alive_checkin 的工程師,想要申請 kotsms API。

請問幾個問題:
1. 個人戶可以申請 API 嗎?(確認)
2. 預付儲值最少多少?(問清楚)
3. API 密碼設定後,可以隨時改嗎?(應該可以)
4. 有沒有 IP 白名單限制?(預設關閉)
5. 簡訊長度限制?(中文 70 / 英文 160,確認)
6. 發送失敗的錯誤代碼表,可以在哪裡看到?
7. 月結 vs 預付,哪個划算?(個人戶應該預付)
8. API 流量上限是多少?(每秒/每分鐘)
9. 有沒有測試環境可以先用?
10. 大量(每月 5,000 則以上)有沒有更便宜的方案?
```

**記得問**:能不能拿到「測試帳號」(避免上線後出問題扣真錢)。

---

## 三、API 文件確認

下載的 PDF 文件,我幫您驗證我們的 `kotsms_client.py` 是否符合:

```
預期欄位:
- URL:https://api.kotsms.com.tw/ 或 https://api.kotsms.com.tw/sendMsg.php
- Method:POST
- 表單欄位:username / password / phone / msg / dstmsgid
- 回應:HTML 內含「傳送成功」「點數剩餘 N」
- Encoding:BIG5(中文必用)

如果有不同,我會立刻修 kotsms_client.py
```

---

## 四、把帳號密碼填進 .env

把拿到的資料填進 `alive_checkin/.env`:

```
SMSKING_USERNAME=您註冊的帳號
SMSKING_PASSWORD=您 API 密碼(不是網站登入密碼)
```

**注意**:
- 不要 commit `.env` 到 Git(已 .gitignore)
- 給我看(貼進對話,我幫您確認格式)

---

## 五、整合測試

填完後,執行:

```bash
cd alive_checkin
python -c "
from alerts.kotsms_client import KotsmsClient
c = KotsmsClient(
    username='您的帳號',
    password='***'
)
r = c.send_sms('0912345678', '測試簡訊 from alive_checkin')
print('成功:', r.success)
print('點數剩餘:', r.points_remaining)
print('錯誤:', r.error_message)
"
```

⚠️ **用您自己的手機測試**,不要用客戶的。

---

## 六、上線 SOP

1. ✅ kotsms 帳號 + 密碼
2. ✅ `.env` 填好
3. ✅ `KotsmsClient` 測試成功
4. ✅ Render 環境變數設定好
5. ✅ Render Cron Job 啟用:`python -m alerts.cron`
6. ✅ 上線初期一週,每天看 `state.outbound_sms_log`
7. ✅ 點數 < 100 時自動提醒(我會寫進 `sender.py`)

---

## 七、客服聯絡(出問題時)

- **電話**:(02)27923939
- **Email**:service@kotsms.com.tw
- **回應時間**:工作日 4 小時內

---

**預計明早完成時間:30-40 分鐘**。先就寢!🌙