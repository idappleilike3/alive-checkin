# SMS 通道整合規格 — 簡訊王 (smsking.com.tw)

> **狀態**:Draft v0.1
> **作者**:小龍蝦(顧問)+ 蝦董(專案負責人)
> **建立日期**:2026-07-17
> **生效前提**:Task 5-1 完成 — 蝦董本人申請簡訊王帳號後填入 `SMSKING_*` 環境變數

---

## 0. 文件目的

定義「今天還在嗎」預警流程中,**簡訊通道(透過簡訊王)** 的:

1. 環境變數清單
2. Python 介面契約(`send_sms`)
3. 資料庫記錄表(`outbound_sms_log`)
4. 成本控管邏輯(每月 100 則上限)
5. 重試機制(3 次,1s/2s/4s)
6. 錯誤處理(`SendResult` 結構)

**範圍之外**(留到對應規格書):
- LINE Push(走 `line_push_message` 既有函式)
- 語音電話(PChome 語音快遞,Task 5-2,獨立規格)
- 預警整體觸發邏輯(三段升級 + 連續降頻,Task 5-3 獨立規格)

---

## 1. 環境變數清單

> ⚠️ **正式環境從 Render Environment Variables 注入**,**不可寫進程式碼 / .env.example**。

| 變數名 | 必填 | 範例值 | 說明 |
|---|---|---|---|
| `SMSKING_USERNAME` | ✅ | `your-account@example.com` | 簡訊王帳號(申請後由簡訊王客服提供) |
| `SMSKING_PASSWORD` | ✅ | `(申請後由業務提供)` | 簡訊王密碼(**不可明文 log**) |
| `SMSKING_API_URL` | ✅ | `https://api.smsking.com.tw/sms/send` | **需跟業務索取當下正確端點**(規格書預留,實作前確認) |
| `SMSKING_ENCODING` | ✅ | `BIG5` | `BIG5` 或 `UTF-8`,預設 BIG5(中文標準);改 UTF-8 須業務確認支援 |
| `SMSKING_TIMEOUT_SEC` | ❌ | `10` | 單次 HTTP timeout,預設 10 |
| `SMSKING_COST_PER_SMS_NTD` | ✅ | `0.85` | 蝦董報價;若業務回報不同,**改這裡 + 重啟服務** |
| `SMS_QUOTA_PER_USER_PER_MONTH` | ✅ | `100` | 單用戶單月上限,Task 5-3 欽定 |
| `SMS_ADMIN_NOTIFY_WEBHOOK` | ❌ | `https://admin.alivecheckin.tw/api/internal/quota-alert` | 超限時通知後台的 webhook URL(可選,沒設就只 log 不推) |

### 1.1 安全規則
- 密碼變數在 log 輸出時必須 redact:`***`
- 環境變數缺失時 → 啟動失敗(非悄悄 fallback)
- 不可在 commit message、錯誤訊息、Slack 推播中露出密碼

---

## 2. Python 介面契約

```python
# chatflow/v1/sms/__init__.py(或 app.py 內獨立 module)
from typing import TypedDict, Literal
from datetime import datetime

SendStatus = Literal[
    'sent',                  # 簡訊商已收到且送出
    'failed',                # 送出失敗(已重試 3 次仍失敗)
    'skipped_quota',         # 超過單用戶單月上限
    'skipped_invalid_phone', # 電話格式不合法
    'skipped_disabled',      # 開關未啟(799 預設關閉期間)
]


class SendResult(TypedDict):
    success: bool                # True = 簡訊商收到,False = 任何失敗/略過
    status: SendStatus           # 細分類別,給 log / 監控 / dashboard 用
    vendor_message_id: str | None   # 簡訊王回傳的 tracking ID(sent 才有值)
    reason: str | None              # 失敗原因的人類可讀字串(e.g. 'auth_failed','timeout')
    cost_ntd: float                 # 這次送出的成本(0 表示沒送出)
    trace_id: str                   # 內部追蹤 ID,UUID4,用於跨服務 log 對齊
    attempted_at: str               # ISO 8601 timestamp
    retry_count: int                # 0 = 第一次就成功/失敗,3 = 用盡重試


def send_sms(
    phone: str,           # E.164 或台灣 09xxxxxxxx 格式
    message: str,         # 已編碼完成的簡訊內容(Big5/UTF-8)
    user_id: str,         # LINE user ID,作為 quota 主鍵
    *,
    feature_flag: str = 'sms_enabled',   # 預設看 SMSKING_ENABLED,預留多開關
    dry_run: bool = False,               # dev 測試用,True = 不真發,只 log
) -> SendResult:
    """發送簡訊給指定電話。

    必須依序執行:
    1. 輸入驗證(電話格式 / 訊息長度)
    2. 開關檢查(feature_flag)
    3. 配額檢查(本月已發 < 100)
    4. 重試發送(最多 3 次,backoff 1s/2s/4s)
    5. 寫 outbound_sms_log
    6. 超限時可選觸發 admin webhook

    任何步驟失敗都要 return SendResult,不 raise(避免 webhook retry storm)。
    """
    ...
```

### 2.1 設計決策

| 選擇 | 理由 |
|---|---|
| `send_sms` **不 raise** | LINE Webhook handler 已經在 try/except 外層;raise 會被吃掉,不如明確 return |
| `user_id` 一定要傳 | 配額是用戶級別,不能從 phone 反推(同一個人可能換門號) |
| `dry_run` 預留 | Task 5-4 dev 環境 E2E 測試必用,**不污染真實配額** |
| `feature_flag` 預留 | Task 5-1 的「799 預設關閉」對應這裡;`SMSKING_ENABLED=false` 就全部 `skipped_disabled` |

---

## 3. 資料庫 Schema — `outbound_sms_log`

> ⚠️ 從 `data/state.json` 遷到 PostgreSQL 後(Task #7)用此 schema。**MVP 階段先用 SQLite,但 schema 一樣。**

```sql
CREATE TABLE outbound_sms_log (
    id              BIGSERIAL PRIMARY KEY,
    
    -- 業務欄位
    user_id         TEXT NOT NULL,              -- LINE user ID(U...)
    phone           TEXT NOT NULL,              -- 收件人手機(已 normalize 為 09xxxxxxxx)
    content         TEXT NOT NULL,              -- 簡訊內容(已編碼後)
    content_hash    TEXT NOT NULL,              -- SHA256(content),用於 dedupe
    
    -- 廠商欄位
    vendor          TEXT NOT NULL DEFAULT 'smsking',
    vendor_message_id TEXT,                     -- 簡訊王回傳的 tracking ID
    
    -- 結果欄位
    status          TEXT NOT NULL,              -- 對應 SendStatus
    cost_ntd        NUMERIC(10,4) NOT NULL DEFAULT 0,
    retry_count     INT NOT NULL DEFAULT 0,
    error_reason    TEXT,                       -- 失敗原因(sent 為 NULL)
    
    -- 追蹤欄位
    trace_id        UUID NOT NULL,
    
    -- 時間欄位
    sent_at         TIMESTAMPTZ,                -- 真正送出的時間(skipped 為 NULL)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- 索引
    CONSTRAINT outbound_sms_log_status_check
        CHECK (status IN ('sent','failed','skipped_quota',
                          'skipped_invalid_phone','skipped_disabled'))
);

-- 用戶配額查詢優化(每月 + 用戶)
CREATE INDEX idx_outbound_sms_user_month
    ON outbound_sms_log (user_id, date_trunc('month', created_at))
    WHERE status = 'sent';

-- trace 對齊(log 查詢)
CREATE INDEX idx_outbound_sms_trace
    ON outbound_sms_log (trace_id);

-- admin dashboard 查詢
CREATE INDEX idx_outbound_sms_status_created
    ON outbound_sms_log (status, created_at DESC);

-- dedupe(同用戶 + 同內容 + 5 分鐘內不重發,防呆)
CREATE INDEX idx_outbound_sms_dedupe
    ON outbound_sms_log (user_id, content_hash, created_at);
```

### 3.1 欄位說明

| 欄位 | 用途 | 備註 |
|---|---|---|
| `phone` | 已驗證格式,統一 `09xxxxxxxx` | 寫入前 normalize |
| `content` | 已編碼(Big5/UTF-8),**不存原文** | 個資保護:原文若含個資,編碼後難還原 |
| `content_hash` | dedupe 鍵 | 同用戶同訊息 5 分鐘內只發一次 |
| `cost_ntd` | 即使 failed 也要記 0 | 月底對帳用 |
| `trace_id` | 跨 LINE / SMS / Voice 三通道對齊 | UUID4,每個 send_sms call 一個 |

---

## 4. 成本控管邏輯

### 4.1 流程

```
send_sms() 被呼叫
    ↓
1. 開關檢查(SMSKING_ENABLED)
    ↓ False → return skipped_disabled
2. 電話格式驗證(正則 /^09\d{8}$/)
    ↓ Invalid → return skipped_invalid_phone
3. 訊息長度檢查(<= 70 中文字 或 <= 160 ASCII)
    ↓ Too long → truncated + 警告(> 70 中文字拆多則,Task 5-1.5 處理)
4. 配額檢查:
   SELECT COUNT(*) FROM outbound_sms_log
   WHERE user_id = ? AND status = 'sent'
     AND created_at >= date_trunc('month', NOW())
    ↓ count >= 100 → 
        - 寫 log(status=skipped_quota)
        - 可選:POST SMS_ADMIN_NOTIFY_WEBHOOK
        - return skipped_quota
5. 重試發送(見 §5)
    ↓
6. 寫 outbound_sms_log
7. return SendResult
```

### 4.2 配額常數

```python
# config.py
SMS_QUOTA_PER_USER_PER_MONTH = int(os.getenv('SMS_QUOTA_PER_USER_PER_MONTH', '100'))
SMS_ADMIN_NOTIFY_THRESHOLD = 0.8  # 用到 80% 就先通知
```

### 4.3 Admin 通知觸發點

| 觸發 | 動作 |
|---|---|
| 用戶配額到 80% | 推 LINE 給 admin:「用戶 X 本月已用 80 則」 |
| 用戶配額到 100% | 推 LINE 給 admin:「用戶 X 已達上限,本訊息略過」+ 略過原因 |
| 全平台單日發送 > 5000 則 | 推 LINE 給 admin:「今日用量異常,請查核」 |

> **Admin 通知目前只 log + webhook**,**不用 LINE Push**(admin 自己有用戶,不要被自己產品打擾)

---

## 5. 重試機制

### 5.1 規則

- 最多 **3 次嘗試**
- 間隔指數退避:**1s → 2s → 4s**
- 只重試**可恢復錯誤**,不重試**永久錯誤**

### 5.2 錯誤分類

```python
class SMSPermanentError(Exception):
    """不重試,直接 failed。例:auth 失敗、餘額不足、電話黑名單"""

class SMSRetryableError(Exception):
    """可重試。例:5xx、timeout、connection error"""

class SMSQuotaExceeded(Exception):
    """配額超限,不重試,走 skipped_quota"""
```

### 5.3 重試實作(pseudocode)

```python
from tenacity import (
    retry, stop_after_attempt, wait_exponential,
    retry_if_exception_type, RetryError
)
import requests


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),  # 1s, 2s, 4s
    retry=retry_if_exception_type(SMSRetryableError),
    reraise=True,
)
def _post_to_smsking(payload: dict, trace_id: str) -> dict:
    """底層 HTTP call,只處理 transport 層重試。"""
    try:
        resp = requests.post(
            SMSKING_API_URL,
            data=payload,
            timeout=SMSKING_TIMEOUT_SEC,
            headers={'X-Trace-Id': trace_id},
        )
    except (requests.Timeout, requests.ConnectionError) as e:
        raise SMSRetryableError(f'transport:{type(e).__name__}') from e

    if 500 <= resp.status_code < 600:
        raise SMSRetryableError(f'smsking_5xx:{resp.status_code}')

    if resp.status_code in (401, 403):
        raise SMSPermanentError(f'smsking_auth:{resp.status_code}')

    if resp.status_code == 429:
        raise SMSRetryableError('smsking_rate_limited')

    return resp.json()
```

### 5.4 重試結果記錄

```python
def send_sms(...) -> SendResult:
    ...
    try:
        vendor_resp = _post_to_smsking(payload, trace_id)
        result = _map_vendor_response(vendor_resp, trace_id)
    except SMSPermanentError as e:
        result = SendResult(success=False, status='failed',
                            reason=str(e), retry_count=0, ...)
    except SMSRetryableError as e:
        # tenacity 用盡 3 次仍失敗 → RetryError 包 RetryCallState
        result = SendResult(success=False, status='failed',
                            reason=f'retry_exhausted:{e}',
                            retry_count=3, ...)
    except RetryError as e:
        result = SendResult(success=False, status='failed',
                            reason=f'retry_exhausted:{e.last_attempt.exception()}',
                            retry_count=3, ...)
    
    _write_outbound_sms_log(user_id, phone, content, result)
    return result
```

---

## 6. 錯誤處理 — `SendResult` 結構對照表

| 情境 | success | status | retry_count | reason | cost_ntd |
|---|---|---|---|---|---|
| 簡訊商收到並送出 | True | `sent` | 0 | NULL | 0.85 |
| 簡訊商收到但 5xx,3 次後失敗 | False | `failed` | 3 | `retry_exhausted:smsking_5xx:503` | 0 |
| Auth 失敗(密碼錯) | False | `failed` | 0 | `smsking_auth:401` | 0 |
| 餘額不足 | False | `failed` | 0 | `smsking_insufficient_balance` | 0 |
| 用戶本月已 100 則 | False | `skipped_quota` | 0 | `monthly_quota_reached:100` | 0 |
| 電話格式不合法 | False | `skipped_invalid_phone` | 0 | `phone_format_invalid:09xx-xxx-xxx` | 0 |
| 簡訊通道尚未開通(799 關閉) | False | `skipped_disabled` | 0 | `feature_flag_disabled` | 0 |
| 訊息太長,自動截斷 | True | `sent` | 0 | NULL + warning log | 0.85 |
| 網路 timeout,1 次後恢復 | True | `sent` | 1 | NULL | 0.85 |
| 同用戶同內容 5 分鐘內重複 | False | `skipped_invalid_phone` ❌ → 新增 `skipped_duplicate` | 0 | `dedupe_hit:{trace_id_old}` | 0 |

> ❌ 發現漏洞:dedupe 要新增 `skipped_duplicate` 狀態。→ **規格 v0.2 待補**

---

## 7. 與現有程式碼的整合點

| 既有函式 | 整合方式 |
|---|---|
| `bind_emergency_contact(app.py:686)` | 守護人綁定後,**新增** `send_welcome_sms(phone, user_id)`(歡迎簡訊,可關閉) |
| `trigger_sos(app.py:968)` | SOS 觸發時,**插入** `send_sms(...)` 呼叫,在 LINE 之後、語音之前 |
| `cancel_warning(app.py:440)` | 用戶按取消 → **取消所有待發簡訊 / 語音**,需設計 cancel state machine |
| `append_notification_log(app.py:1387)` | 把 `outbound_sms_log` 的寫入 **redirect 到 DB**,JSON 留 log summary |
| `admin_update_user_plan(app.py:1089)` | admin 後台加「用戶配額查詢」endpoint |

---

## 8. 開放問題(待蝦董確認)

1. [ ] **簡訊王當下 API 端點** — 上線前跟業務索取官方 API doc,確認 `SMSKING_API_URL` 路徑
2. [ ] **編碼 BIG5 vs UTF-8** — 預設 BIG5,但若簡訊王已支援 UTF-8 就改(emoji / 罕用字支援)
3. [ ] **超長訊息拆則** — 超過 70 中文字要拆成多則,**成本按則數算**,要設計 splitter
4. [ ] **dedupe 視窗** — 預設 5 分鐘,可調
5. [ ] **admin 通知走 webhook 還是 LINE Push** — 規格預設 webhook,但 admin 可能會想用 LINE 看
6. [ ] **簡訊發送時段** — 深夜(00:00-07:00)是否暫停?(避免擾民)
7. [ ] **`skipped_duplicate` 狀態** — 規格 §6 表格發現漏,待 v0.2 補進 schema
8. [ ] **iOS 預覽字元** — 簡訊王可能會在 iOS 顯示預覽,**個資暴露風險**,是否要 `***` 遮罩?

---

## 9. 待辦(蝦董本人要先做才能開工)

- [ ] 申請簡訊王帳號 + 索取當下牌價(確認 NT$0.85 是否當下有效)
- [ ] 索取官方 API doc(確認 endpoint、auth、編碼、回傳格式)
- [ ] 提供帳號密碼給 Render Environment Variables
- [ ] 確認是否要做 `skipped_duplicate` dedupe

---

## 10. 變更紀錄

| 版本 | 日期 | 作者 | 變更 |
|---|---|---|---|
| v0.1 | 2026-07-17 | 小龍蝦 + 蝦董 | 初版 |
| v0.2 | TBD | TBD | 補 `skipped_duplicate` 狀態、超長訊息 splitter |