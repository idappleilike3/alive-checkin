"""NewebPay (藍新) checkout + notify scaffolding.

When NEWEBPAY_MERCHANT_ID / HASH_KEY / HASH_IV are set, checkout payloads are
built for MPG. Otherwise the API returns a pending_manual order for admin
confirm. Notify webhook verifies TradeInfo when keys exist.

NotifyURL（擇一，兩者等效）:
  - {APP_PUBLIC_URL}/api/payment/newebpay/notify  （checkout 預設）
  - {APP_PUBLIC_URL}/webhook/newebpay

ReturnURL:
  - {APP_PUBLIC_URL}/payment-success  （接受 GET/POST）
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from binascii import unhexlify
from typing import Any, Optional

try:
    from Crypto.Cipher import AES  # type: ignore
except Exception:  # pragma: no cover - optional until keys present
    AES = None


def newebpay_configured(config: Optional[dict] = None) -> bool:
    cfg = config or {}
    mid = (cfg.get("NEWEBPAY_MERCHANT_ID") or os.environ.get("NEWEBPAY_MERCHANT_ID") or "").strip()
    key = (cfg.get("NEWEBPAY_HASH_KEY") or os.environ.get("NEWEBPAY_HASH_KEY") or "").strip()
    iv = (cfg.get("NEWEBPAY_HASH_IV") or os.environ.get("NEWEBPAY_HASH_IV") or "").strip()
    return bool(mid and key and iv and AES is not None)


def _cfg(config: Optional[dict], key: str, default: str = "") -> str:
    cfg = config or {}
    return str(cfg.get(key) or os.environ.get(key) or default).strip()


def _pad(text: str) -> bytes:
    raw = text.encode("utf-8")
    pad_len = 32 - (len(raw) % 32)
    return raw + bytes([pad_len] * pad_len)


def _unpad(raw: bytes) -> bytes:
    if not raw:
        return raw
    pad_len = raw[-1]
    if pad_len < 1 or pad_len > 32:
        return raw
    return raw[:-pad_len]


def aes_encrypt(plain: str, hash_key: str, hash_iv: str) -> str:
    if AES is None:
        raise RuntimeError("pycryptodome is required for NewebPay AES")
    cipher = AES.new(hash_key.encode("utf-8"), AES.MODE_CBC, hash_iv.encode("utf-8"))
    return cipher.encrypt(_pad(plain)).hex()


def aes_decrypt(hex_cipher: str, hash_key: str, hash_iv: str) -> str:
    if AES is None:
        raise RuntimeError("pycryptodome is required for NewebPay AES")
    cipher = AES.new(hash_key.encode("utf-8"), AES.MODE_CBC, hash_iv.encode("utf-8"))
    return _unpad(cipher.decrypt(unhexlify(hex_cipher))).decode("utf-8")


def sha256_trade_sha(trade_info: str, hash_key: str, hash_iv: str) -> str:
    raw = f"HashKey={hash_key}&{trade_info}&HashIV={hash_iv}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()


def build_checkout(order: dict, config: Optional[dict] = None) -> dict:
    """Return checkout descriptor for LIFF/UI.

    Shape:
      {
        "mode": "newebpay" | "manual",
        "mpg_url": "...",
        "form": {...} | None,
        "message": "..."
      }
    """
    if not newebpay_configured(config):
        return {
            "mode": "manual",
            "mpg_url": None,
            "form": None,
            "message": "藍新金流尚未設定環境變數；訂單已建立為 pending，請後台人工確認或補齊 NEWEBPAY_* 後重試。",
            "todo": [
                "NEWEBPAY_MERCHANT_ID",
                "NEWEBPAY_HASH_KEY",
                "NEWEBPAY_HASH_IV",
                "NEWEBPAY_MPG_URL (optional)",
            ],
        }

    merchant_id = _cfg(config, "NEWEBPAY_MERCHANT_ID")
    hash_key = _cfg(config, "NEWEBPAY_HASH_KEY")
    hash_iv = _cfg(config, "NEWEBPAY_HASH_IV")
    public_url = _cfg(config, "APP_PUBLIC_URL").rstrip("/")
    stage = _cfg(config, "NEWEBPAY_STAGE", "sandbox")
    default_mpg = (
        "https://ccore.newebpay.com/MPG/mpg_gateway"
        if stage != "prod"
        else "https://core.newebpay.com/MPG/mpg_gateway"
    )
    mpg_url = _cfg(config, "NEWEBPAY_MPG_URL", default_mpg)

    trade = {
        "MerchantID": merchant_id,
        "RespondType": "JSON",
        "TimeStamp": str(int(time.time())),
        "Version": "2.0",
        "MerchantOrderNo": order.get("order_id"),
        "Amt": int(order.get("amount") or 0),
        "ItemDesc": str(order.get("plan") or "alive-checkin")[:50],
        "NotifyURL": f"{public_url}/api/payment/newebpay/notify" if public_url else "",
        # NotifyURL 亦可填 /webhook/newebpay（與上列路徑等效，見 app.py）
        "ReturnURL": f"{public_url}/payment-success" if public_url else "",
        "ClientBackURL": f"{public_url}/pricing" if public_url else "",
        "Email": "",
        "LoginType": 0,
    }
    trade_info = aes_encrypt(urllib_query(trade), hash_key, hash_iv)
    trade_sha = sha256_trade_sha(trade_info, hash_key, hash_iv)
    return {
        "mode": "newebpay",
        "mpg_url": mpg_url,
        "form": {
            "MerchantID": merchant_id,
            "TradeInfo": trade_info,
            "TradeSha": trade_sha,
            "Version": "2.0",
        },
        "message": "請以表單 POST 至藍新 MPG 完成付款。",
    }


def _period_gateway_url(config: Optional[dict] = None) -> str:
    stage = _cfg(config, "NEWEBPAY_STAGE", "sandbox")
    default = (
        "https://core.newebpay.com/MPG/period"
        if stage == "prod"
        else "https://ccore.newebpay.com/MPG/period"
    )
    return _cfg(config, "NEWEBPAY_PERIOD_URL", default)


def _clean_period_description(value: Any) -> str:
    # NDNP permits Chinese, letters, numbers, spaces and underscores.
    cleaned = re.sub(r"[^\w\u3400-\u9fff ]+", " ", str(value or "每日平安"))
    return re.sub(r"\s+", " ", cleaned).strip()[:100] or "每日平安"


def build_period_checkout(
    order: dict,
    *,
    payer_email: str,
    config: Optional[dict] = None,
) -> dict:
    """Build an NDNP 1.0.7 recurring-payment form without handling card data."""
    if not newebpay_configured(config):
        return {
            "mode": "manual",
            "period_url": None,
            "form": None,
            "message": "藍新定期定額尚未設定；不會建立或假裝啟用自動續費。",
        }
    email = str(payer_email or "").strip()
    if not email:
        raise ValueError("payer_email is required for NewebPay period checkout")

    billing_cycle = str(order.get("billing_cycle") or "").strip().lower()
    if billing_cycle not in {"monthly", "yearly"}:
        raise ValueError("billing_cycle must be monthly or yearly")

    now = time.localtime()
    period_type = "M" if billing_cycle == "monthly" else "Y"
    period_point = (
        f"{now.tm_mday:02d}"
        if period_type == "M"
        else f"{now.tm_mon:02d}{now.tm_mday:02d}"
    )
    cau_enabled = _cfg(config, "NEWEBPAY_CAU_ENABLED").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    configured_times = _cfg(config, "NEWEBPAY_PERIOD_TIMES", "12")
    if not configured_times.isdigit() or not 1 <= int(configured_times) <= 99:
        configured_times = "12"
    public_url = _cfg(config, "APP_PUBLIC_URL").rstrip("/")
    trade = {
        "RespondType": "JSON",
        "TimeStamp": str(int(time.time())),
        "Version": "1.5",
        "LangType": "zh-Tw",
        "MerOrderNo": str(order.get("order_id") or ""),
        "ProdDesc": _clean_period_description(
            order.get("display_name") or order.get("plan") or "每日平安"
        ),
        "PeriodAmt": int(order.get("amount") or 0),
        "PeriodType": period_type,
        "PeriodPoint": period_point,
        "PeriodStartType": 2,
        # Official NDNP: NE is allowed only when the shop has CAU permission.
        "PeriodTimes": "NE" if cau_enabled else configured_times,
        "PayerEmail": email,
        "PaymentInfo": "Y",
        "OrderInfo": "N",
        "EmailModify": 1,
        "NotifyURL": (
            f"{public_url}/api/payment/newebpay/period-notify"
            if public_url
            else ""
        ),
        "ReturnURL": f"{public_url}/payment-success" if public_url else "",
        "BackURL": f"{public_url}/pricing" if public_url else "",
    }
    hash_key = _cfg(config, "NEWEBPAY_HASH_KEY")
    hash_iv = _cfg(config, "NEWEBPAY_HASH_IV")
    return {
        "mode": "newebpay_period",
        "period_url": _period_gateway_url(config),
        "form": {
            "MerchantID_": _cfg(config, "NEWEBPAY_MERCHANT_ID"),
            "PostData_": aes_encrypt(urllib_query(trade), hash_key, hash_iv),
        },
        "message": "請以表單 POST 至藍新定期定額頁完成信用卡委託。",
    }


def parse_period_payload(
    form: dict,
    config: Optional[dict] = None,
) -> tuple[Optional[dict], Optional[str]]:
    """Decrypt the ``Period`` field used by establish and charge notifications."""
    if not newebpay_configured(config):
        return None, "newebpay_not_configured"
    encrypted = str(form.get("Period") or form.get("period") or "").strip()
    if not encrypted:
        return None, "missing_period_field"
    try:
        plain = aes_decrypt(
            encrypted,
            _cfg(config, "NEWEBPAY_HASH_KEY"),
            _cfg(config, "NEWEBPAY_HASH_IV"),
        )
        data = json.loads(plain)
    except Exception:
        return None, "period_decrypt_failed"
    result = data.get("Result") or {}
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            result = {"raw": result}
    card_no = str(result.get("CardNo") or "")
    return {
        "status": str(data.get("Status") or ""),
        "message": str(data.get("Message") or ""),
        "order_id": str(
            result.get("MerchantOrderNo") or result.get("MerOrderNo") or ""
        ),
        "period_no": str(result.get("PeriodNo") or ""),
        "transaction_id": str(result.get("TradeNo") or ""),
        "amount": result.get("PeriodAmt") or result.get("AuthAmt"),
        "payment_method_last4": re.sub(r"\D", "", card_no)[-4:],
        "raw": data,
    }, None


def build_period_status_change(
    *,
    merchant_order_no: str,
    period_no: str,
    action: str,
    config: Optional[dict] = None,
) -> dict:
    """Build NPA-B051 request for suspend, restart or irreversible terminate."""
    normalized_action = str(action or "").strip().lower()
    if normalized_action not in {"suspend", "restart", "terminate"}:
        raise ValueError("action must be suspend, restart or terminate")
    if not newebpay_configured(config):
        raise RuntimeError("newebpay_not_configured")
    trade = {
        "RespondType": "JSON",
        "TimeStamp": str(int(time.time())),
        "Version": "1.0",
        "MerOrderNo": str(merchant_order_no or "").strip(),
        "PeriodNo": str(period_no or "").strip(),
        "AlterType": normalized_action,
    }
    if not trade["MerOrderNo"] or not trade["PeriodNo"]:
        raise ValueError("merchant_order_no and period_no are required")
    return {
        "url": f"{_period_gateway_url(config).rstrip('/')}/AlterStatus",
        "form": {
            "MerchantID_": _cfg(config, "NEWEBPAY_MERCHANT_ID"),
            "PostData_": aes_encrypt(
                urllib_query(trade),
                _cfg(config, "NEWEBPAY_HASH_KEY"),
                _cfg(config, "NEWEBPAY_HASH_IV"),
            ),
        },
        "action": normalized_action,
    }


def build_credit_card_refund(
    *,
    merchant_order_no: str,
    trade_no: str,
    amount: int,
    config: Optional[dict] = None,
) -> dict:
    """Build NPA-B032 credit-card refund request (not cancel-refund)."""
    if not newebpay_configured(config):
        raise RuntimeError("newebpay_not_configured")
    refund_amount = int(amount or 0)
    if refund_amount <= 0:
        raise ValueError("refund amount must be positive")
    order_no = str(merchant_order_no or "").strip()
    gateway_trade_no = str(trade_no or "").strip()
    if not order_no or not gateway_trade_no:
        raise ValueError("merchant_order_no and trade_no are required")
    stage = _cfg(config, "NEWEBPAY_STAGE", "sandbox")
    default_url = (
        "https://core.newebpay.com/API/CreditCard/Close"
        if stage == "prod"
        else "https://ccore.newebpay.com/API/CreditCard/Close"
    )
    trade = {
        "RespondType": "String",
        "Version": "1.1",
        "Amt": refund_amount,
        "MerchantOrderNo": order_no,
        "TimeStamp": str(int(time.time())),
        # TradeNo is less ambiguous than the merchant order number.
        "IndexType": 2,
        "TradeNo": gateway_trade_no,
        "CloseType": 2,
    }
    return {
        "url": _cfg(config, "NEWEBPAY_CREDIT_CLOSE_URL", default_url),
        "form": {
            "MerchantID_": _cfg(config, "NEWEBPAY_MERCHANT_ID"),
            "PostData_": aes_encrypt(
                urllib_query(trade),
                _cfg(config, "NEWEBPAY_HASH_KEY"),
                _cfg(config, "NEWEBPAY_HASH_IV"),
            ),
        },
    }


def parse_credit_card_close_response(
    response: Any,
) -> tuple[Optional[dict], Optional[str]]:
    """Parse NPA-B031~34 JSON, query-string, bytes, or mapping response."""
    from urllib.parse import parse_qs

    if isinstance(response, bytes):
        response = response.decode("utf-8", errors="replace")
    if isinstance(response, str):
        text = response.strip()
        if not text:
            return None, "empty_gateway_response"
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = {key: values[0] for key, values in parse_qs(text).items()}
    elif isinstance(response, dict):
        data = dict(response)
    else:
        return None, "invalid_gateway_response"
    result = data.get("Result") or {}
    if not isinstance(result, dict):
        result = {}
    merged = {**data, **result}
    try:
        amount = int(merged.get("Amt") or 0)
    except (TypeError, ValueError):
        amount = 0
    return {
        "status": str(data.get("Status") or ""),
        "message": str(data.get("Message") or ""),
        "amount": amount,
        "order_id": str(merged.get("MerchantOrderNo") or ""),
        "transaction_id": str(merged.get("TradeNo") or ""),
        "raw": data,
    }, None


def urllib_query(data: dict) -> str:
    from urllib.parse import urlencode

    return urlencode({k: v for k, v in data.items() if v is not None and v != ""})


def parse_notify_payload(form: dict, config: Optional[dict] = None) -> tuple[Optional[dict], Optional[str]]:
    """Decrypt/verify NewebPay NotifyURL payload. Returns (trade_result, error)."""
    if not newebpay_configured(config):
        return None, "newebpay_not_configured"

    hash_key = _cfg(config, "NEWEBPAY_HASH_KEY")
    hash_iv = _cfg(config, "NEWEBPAY_HASH_IV")
    trade_info = str(form.get("TradeInfo") or "").strip()
    trade_sha = str(form.get("TradeSha") or "").strip().upper()
    if not trade_info or not trade_sha:
        return None, "missing_trade_fields"
    expected = sha256_trade_sha(trade_info, hash_key, hash_iv)
    if expected != trade_sha:
        return None, "invalid_trade_sha"
    try:
        plain = aes_decrypt(trade_info, hash_key, hash_iv)
        data = json.loads(plain)
    except Exception:
        return None, "decrypt_failed"

    status = str(data.get("Status") or "")
    result = data.get("Result") or {}
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            result = {"raw": result}
    return {
        "status": status,
        "order_id": str(result.get("MerchantOrderNo") or ""),
        "transaction_id": str(result.get("TradeNo") or ""),
        "amount": result.get("Amt"),
        "raw": data,
    }, None


def notify_success(parsed: dict) -> bool:
    return str(parsed.get("status") or "").upper() == "SUCCESS"
