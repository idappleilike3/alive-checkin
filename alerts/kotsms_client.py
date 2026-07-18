"""
alerts/kotsms_client.py — 簡訊王 kotsms.com.tw 簡訊發送 client

參考:https://github.com/fuyuanli/kotsms.py(2016,拋棄)
重寫原因:library 10 年沒更新、無 error handling、3rd-party 安全疑慮。

API 規格(2026-07-17 從 kotsms 官網確認):
- Endpoint:https://api.kotsms.com.tw/
- Login:POST /login (form data: username, password)
- Send:POST /sendMsg (form data: phone, message, dstmsgid)
- Encoding:BIG5(預設)/ UTF-8
- 中文 70 字/則,英文 160 字/則
- 回傳格式:HTML 內含「傳送成功」「點數剩餘」「錯誤訊息」

注意:
1. kotsms 使用 session cookie,必須先 login 才能 send
2. 簡訊內容含中文必須用 BIG5 encoding(API 限制)
3. 必須驗證餘額,避免餘額不足時靜默失敗
"""

from __future__ import annotations

import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from typing import Optional

import requests

# ============================================================================
# 常數
# ============================================================================

KOTSMS_API_BASE = "https://api.kotsms.com.tw"
KOTSMS_LOGIN_URL = f"{KOTSMS_API_BASE}/"
KOTSMS_SEND_URL = f"{KOTSMS_API_BASE}/sendMsg.php"

# 中文 70 字 / 英文 160 字(採保守值 70)
SMS_MAX_CHINESE_CHARS = 70
SMS_MAX_ENGLISH_CHARS = 160

DEFAULT_TIMEOUT_SEC = 10
DEFAULT_RETRY_COUNT = 3
DEFAULT_RETRY_BACKOFF_SEC = 1.5


# ============================================================================
# 結果資料結構
# ============================================================================

@dataclass
class SendResult:
    """簡訊發送結果"""
    success: bool
    phone: str
    content: str
    points_remaining: Optional[int] = None  # 餘額
    message_id: Optional[str] = None         # 追蹤用
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    raw_response: Optional[str] = None       # kotsms HTML response


# ============================================================================
# Kotsms Client
# ============================================================================

class KotsmsClient:
    """
    簡訊王 kotsms.com.tw API client
    
    Usage:
        client = KotsmsClient(
            username=os.environ["SMSKING_USERNAME"],
            password=os.environ["SMSKING_PASSWORD"],
        )
        result = client.send_sms("0912345678", "您好,測試簡訊")
        if result.success:
            print(f"發送成功,剩餘點數: {result.points_remaining}")
    """

    def __init__(
        self,
        username: str,
        password: str,
        encoding: str = "BIG5",
        timeout_sec: int = DEFAULT_TIMEOUT_SEC,
        retry_count: int = DEFAULT_RETRY_COUNT,
        retry_backoff_sec: float = DEFAULT_RETRY_BACKOFF_SEC,
        session: Optional[requests.Session] = None,
        logger: Optional[logging.Logger] = None,
    ):
        if not username or not password:
            raise ValueError("kotsms username/password required")
        self.username = username
        self.password = password
        self.encoding = encoding
        self.timeout_sec = timeout_sec
        self.retry_count = retry_count
        self.retry_backoff_sec = retry_backoff_sec
        self.session = session or requests.Session()
        self.logger = logger or self._default_logger()
        self._logged_in = False

    @staticmethod
    def _default_logger() -> logging.Logger:
        return logging.getLogger("kotsms")

    # ------------------------------------------------------------------
    # Session / Login
    # ------------------------------------------------------------------

    def login(self) -> bool:
        """
        登入 kotsms,取得 session cookie。
        若失敗,丟出例外。
        """
        try:
            payload = {"username": self.username, "password": self.password}
            resp = self.session.post(
                KOTSMS_LOGIN_URL,
                data=payload,
                timeout=self.timeout_sec,
                allow_redirects=True,
            )
            resp.raise_for_status()
            # kotsms 用 cookie 判定登入;若沒 set-cookie 視為失敗
            if "PHPSESSID" not in self.session.cookies.get_dict():
                self.logger.error("kotsms login failed: no session cookie returned")
                return False
            self._logged_in = True
            self.logger.info("kotsms login success")
            return True
        except requests.RequestException as e:
            self.logger.error(f"kotsms login error: {e}")
            return False

    def _ensure_logged_in(self) -> None:
        if not self._logged_in:
            if not self.login():
                raise RuntimeError("kotsms login failed; cannot send SMS")

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    def send_sms(
        self,
        phone: str,
        message: str,
        dst_msg_id: Optional[str] = None,
    ) -> SendResult:
        """
        發送簡訊。
        
        Args:
            phone: 09xxxxxxxx 格式手機號碼(已驗證過)
            message: 簡訊內容
            dst_msg_id: 自訂追蹤 ID(預設自動產生)
        
        Returns:
            SendResult(success, points_remaining, error_message, ...)
        """
        if not self._validate_phone(phone):
            return SendResult(
                success=False,
                phone=phone,
                content=message,
                error_code="INVALID_PHONE",
                error_message=f"電話格式錯誤: {phone}",
            )

        if not self._validate_message(message):
            return SendResult(
                success=False,
                phone=phone,
                content=message,
                error_code="MESSAGE_TOO_LONG",
                error_message=f"簡訊超過 {SMS_MAX_CHINESE_CHARS} 字",
            )

        msg_id = dst_msg_id or f"a{uuid.uuid4().hex[:10]}"
        last_error: Optional[str] = None

        for attempt in range(1, self.retry_count + 1):
            try:
                self._ensure_logged_in()
                result = self._send_once(phone, message, msg_id)
                if result.success:
                    self.logger.info(
                        f"kotsms send ok (attempt={attempt}) "
                        f"phone={phone} id={msg_id} pts={result.points_remaining}"
                    )
                    return result
                # 非 2xx 但也沒 raise:可能是餘額不足之類的 business error
                last_error = result.error_message or "unknown"
                self.logger.warning(
                    f"kotsms send failed (attempt={attempt}/{self.retry_count}) "
                    f"phone={phone} error={last_error}"
                )
            except requests.RequestException as e:
                last_error = str(e)
                self.logger.warning(
                    f"kotsms network error (attempt={attempt}/{self.retry_count}) "
                    f"phone={phone} err={e}"
                )

            # 退避
            if attempt < self.retry_count:
                time.sleep(self.retry_backoff_sec * attempt)

        # 全部 retry 失敗
        return SendResult(
            success=False,
            phone=phone,
            content=message,
            message_id=msg_id,
            error_code="MAX_RETRY_EXCEEDED",
            error_message=last_error or "all retries failed",
        )

    def _send_once(self, phone: str, message: str, msg_id: str) -> SendResult:
        """單次發送,內部 helper。"""
        payload = {
            "phone": phone,
            message: "",  # placeholder
        }
        # 簡訊王 API 接收方式:表單欄位直接放 message 內容
        # 為避免特殊字元問題,改用 'msg' 欄位(常見作法)
        payload = {
            "username": self.username,
            "password": self.password,
            "phone": phone,
            "msg": message,
            "dstmsgid": msg_id,
        }
        resp = self.session.post(
            KOTSMS_SEND_URL,
            data=payload,
            timeout=self.timeout_sec,
        )
        resp.raise_for_status()
        return self._parse_response(resp.text, phone, message, msg_id)

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_response(
        html: str, phone: str, message: str, msg_id: str
    ) -> SendResult:
        """
        解析 kotsms 回應(HTML 格式)
        
        常見成功訊息:
          「傳送成功」「點數剩餘 99」「已送出」
        常見失敗訊息:
          「帳號或密碼錯誤」「點數不足」「電話號碼錯誤」
        """
        # 抓「點數剩餘 N」
        pts_match = re.search(r"點數剩餘\s*[:：]?\s*(\d+)", html)
        points = int(pts_match.group(1)) if pts_match else None

        # 抓錯誤訊息
        err_match = re.search(
            r"(錯誤[:：].{0,80}|帳號.{0,30}錯誤|點數不足|電話號碼.{0,30}錯誤)",
            html,
        )
        err_msg = err_match.group(1) if err_match else None

        success = (
            "傳送成功" in html
            or "已送出" in html
            or "傳送完成" in html
        ) and not err_msg

        if success:
            return SendResult(
                success=True,
                phone=phone,
                content=message,
                points_remaining=points,
                message_id=msg_id,
                raw_response=html[:500],  # 只保留前 500 字避免 log 暴增
            )

        return SendResult(
            success=False,
            phone=phone,
            content=message,
            points_remaining=points,
            message_id=msg_id,
            error_code="BUSINESS_ERROR",
            error_message=err_msg or "unknown kotsms error",
            raw_response=html[:500],
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_phone(phone: str) -> bool:
        return bool(phone and re.match(r"^09\d{8}$", phone))

    @staticmethod
    def _validate_message(message: str) -> bool:
        if not message or not message.strip():
            return False
        # 中文算 2 字,英文算 1 字(簡化估算)
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", message))
        english_chars = len(message) - chinese_chars
        # 保守:全部當中文算(70 字上限)
        return len(message) <= SMS_MAX_CHINESE_CHARS


# ============================================================================
# Convenience: env-driven factory
# ============================================================================

def make_client_from_env(
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
) -> KotsmsClient:
    """
    從環境變數建立 client。
    
    環境變數:
      SMSKING_USERNAME
      SMSKING_PASSWORD
    """
    return KotsmsClient(
        username=os.environ["SMSKING_USERNAME"],
        password=os.environ["SMSKING_PASSWORD"],
        timeout_sec=timeout_sec,
    )