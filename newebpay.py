"""NewebPay (藍新) checkout + notify scaffolding.

When NEWEBPAY_MERCHANT_ID / HASH_KEY / HASH_IV are set, checkout payloads are
built for MPG. Otherwise the API returns a pending_manual order for admin
confirm. Notify webhook verifies TradeInfo when keys exist.
"""

from __future__ import annotations

import hashlib
import json
import os
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
