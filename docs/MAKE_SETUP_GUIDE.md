# MAKE 設定教學(alive_checkin 用)

> 給蝦董明早照著點。
> 預計時間:15 分鐘。

---

## 一、MAKE 是什麼 / 為什麼要用

**MAKE**(前身 Integromat)是一個「無程式碼自動化」平台。透過「trigger → 動作 → 條件」的視覺化流程,讓不同服務串接。

**alive_checkin 用 MAKE 做什麼**:
- ✅ 每日 Bot 健康檢查 Email(失聯預警之外的輔助)
- ✅ 月費到期提醒(預備)
- ✅ 客服通知 Email(預備)

**alive_checkin 不用 MAKE 做什麼**:
- ❌ 失聯預警 Wave 1/2/3(安全路徑,**必須 Python 直接打**)
- ❌ SMS 發送(直接打 kotsms API)
- ❌ LINE 推播(直接打 LINE API)

---

## 二、登入 MAKE(您已經登入了)

1. 開瀏覽器 → https://us1.make.com/
2. 點右上角「Sign in」
3. 用 Google 帳號登入
4. 進入後台,看到左邊「Scenarios / Credentials / Webhooks / Templates」

---

## 三、建立第一個 Scenario:每日 Bot 健康檢查 Email

### 步驟 1:新增 scenario

1. 左邊點「Scenarios」
2. 右上角點「+ Create scenario」
3. 進入空白畫布(一個大大的「+」)

### 步驟 2:加 Schedule trigger(排程)

1. 點中間那個「+」
2. 搜尋「Schedule」
3. 選「Schedule」(內建)
4. 設定:
   - **Interval**:Every day
   - **Time**:09:00(台北時間)
   - **Timezone**:Asia/Taipei
5. 點「OK」

### 步驟 3:加 HTTP 模組(打 Bot)

1. 在 Schedule 模組右邊,點「+」
2. 搜尋「HTTP」
3. 選「Make an HTTP request」
4. 設定:
   - **Method**:GET
   - **URL**:`https://alive-checkin.onrender.com/health`
5. 點「OK」

### 步驟 4:加 Email 模組

1. 在 HTTP 模組右邊,點「+」
2. 搜尋「Email」
3. 選「Send an Email」(Gmail)
4. **第一次會跳出授權視窗**:
   - 點「Add」
   - 選「Gmail」
   - **登入您的 Gmail**(`alivecheckin.tw@gmail.com` 或您常用那個)
   - **點「允許」**(授權 MAKE 寄信)
5. 回到 Email 模組設定:
   - **To**:您的 email(同 Gmail)
   - **Subject**:`[alive_checkin] 每日健康檢查 - {{formatDate(now; "YYYY-MM-DD")}}`
   - **Body**:
     ```
     Bot 狀態檢查報告
     日期: {{formatDate(now; "YYYY-MM-DD HH:mm")}}

     HTTP Status: {{1.statusCode}}
     Response: {{1.body}}

     {% if 1.statusCode != 200 %}
     ⚠️ Bot 異常,請立即檢查 Render dashboard
     {% else %}
     ✅ Bot 正常運作
     {% endif %}
     ```
6. 點「OK」

### 步驟 5:儲存 + 啟用

1. 左下角儲存(磁片 icon)
2. 把左下角開關「OFF」→「ON」(變綠色)
3. 命名:「每日健康檢查 Email」

---

## 四、測試

### 方法 1:手動觸發

1. scenario 畫面左下角,點「Run once」
2. 看是否有紅色錯誤
3. 檢查您 Gmail 信箱

### 方法 2:等到明天 09:00

會自動寄到您信箱。

---

## 五、其他場景(明後天再做)

### 月費到期提醒 Email(每天 09:30)

**Trigger**: Schedule(每天 09:30)
**HTTP**: GET https://alive-checkin.onrender.com/api/expiring-users?days=30
**Iterator**:對每個用戶
**Email**: 寄給 admin
   ```
   用戶 {{user.name}} 的 NT$199 月費將於 {{user.days_left}} 天後到期。
   請在後台查看是否需要主動聯繫。
   ```

⚠️ 注意:這個 scenario 需要 alive_checkin 先實作 `/api/expiring-users` 端點。我會寫進 app.py(明後天做)。

---

## 六、MAKE 配額

**Free plan**:1,000 ops/月
**本場景用量**:每執行 1 次 = 3 ops(Schedule + HTTP + Email)
**每月用量**:30 ops(假設每天跑)
**剩餘**:970 ops(還可以做 32 個類似場景)

---

## 七、如果您卡住

1. **OAuth 跳不出來**:換瀏覽器或清 cookie 重來
2. **HTTP 模組 timeout**:Render free tier 會 spin down,首請求可能 30 秒
3. **Email 沒收到**:檢查 Gmail 垃圾信夾
4. **Scenario 變 OFF**:檢查左下角開關
5. **想要我(Debug)**:截圖畫面給我,我告訴您哪裡點錯

---

## 八、安全聲明

- MAKE 內建 OAuth,**不存您的 Gmail 密碼**
- 取消授權:Google 帳號 → 第三方應用 → Make → 移除
- 場景隨時可以 OFF(左下開關)

---

**預計明早完成時間:15 分鐘**。先就寢!🌙