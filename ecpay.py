"""ECPay (綠界) AIO credit-card payment helpers.

Card data is always collected by ECPay's hosted checkout.  This module only
builds signed form fields and verifies signed server callbacks.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
from typing import Any, Optional
from urllib.parse import quote_plus


def _cfg(config: Optional[dict], key: str, default: str = "") -> str:
    cfg = config or {}
    return str(cfg.get(key) or os.environ.get(key) or default).strip()


def ecpay_configured(config: Optional[dict] = None) -> bool:
    return bool(
        _cfg(config, "ECPAY_MERCHANT_ID")
        and _cfg(config, "ECPAY_HASH_KEY")
        and _cfg(config, "ECPAY_HASH_IV")
    )


def _encoded_mac_source(params: dict, hash_key: str, hash_iv: str) -> str:
    pairs = [
        f"{key}={params[key]}"
        for key in sorted(params, key=lambda value: str(value).lower())
        if str(key).lower() != "checkmacvalue"
    ]
    raw = f"HashKey={hash_key}&{'&'.join(pairs)}&HashIV={hash_iv}"
    encoded = quote_plus(raw, safe="").lower()
    replacements = {
        "%2d": "-",
        "%5f": "_",
        "%2e": ".",
        "%21": "!",
        "%2a": "*",
        "%28": "(",
        "%29": ")",
    }
    for source, replacement in replacements.items():
        encoded = encoded.replace(source, replacement)
    return encoded


def generate_check_mac(params: dict, config: Optional[dict] = None) -> str:
    if not ecpay_configured(config):
        raise RuntimeError("ecpay_not_configured")
    source = _encoded_mac_source(
        params,
        _cfg(config, "ECPAY_HASH_KEY"),
        _cfg(config, "ECPAY_HASH_IV"),
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest().upper()


def verify_check_mac(params: dict, config: Optional[dict] = None) -> bool:
    supplied = str(params.get("CheckMacValue") or "").strip().upper()
    if not supplied:
        return False
    try:
        expected = generate_check_mac(params, config)
    except RuntimeError:
        return False
    return hmac.compare_digest(expected, supplied)


def _checkout_url(config: Optional[dict] = None) -> str:
    if _cfg(config, "ECPAY_STAGE", "sandbox").lower() == "prod":
        return "https://payment.ecpay.com.tw/Cashier/AioCheckOut/V5"
    return "https://payment-stage.ecpay.com.tw/Cashier/AioCheckOut/V5"


def _clean_text(value: Any, max_length: int) -> str:
    cleaned = re.sub(r"[^\w\u3400-\u9fff ]+", " ", str(value or "每日平安"))
    return re.sub(r"\s+", " ", cleaned).strip()[:max_length] or "每日平安"


def _base_checkout_form(order: dict, config: Optional[dict]) -> dict:
    public_url = _cfg(config, "APP_PUBLIC_URL").rstrip("/")
    trade_no = str(order.get("order_id") or "").strip()[:20]
    if not trade_no:
        raise ValueError("order_id is required")
    amount = int(order.get("amount") or 0)
    if amount <= 0:
        raise ValueError("amount must be positive")
    return {
        "MerchantID": _cfg(config, "ECPAY_MERCHANT_ID"),
        "MerchantTradeNo": trade_no,
        "MerchantTradeDate": time.strftime("%Y/%m/%d %H:%M:%S", time.localtime()),
        "PaymentType": "aio",
        "TotalAmount": amount,
        "TradeDesc": _clean_text(order.get("display_name") or order.get("plan"), 200),
        "ItemName": _clean_text(order.get("display_name") or order.get("plan"), 400),
        "ReturnURL": f"{public_url}/api/payment/ecpay/notify" if public_url else "",
        "ChoosePayment": "Credit",
        "EncryptType": 1,
        "ClientBackURL": f"{public_url}/pricing" if public_url else "",
        "OrderResultURL": f"{public_url}/payment-success" if public_url else "",
        "NeedExtraPaidInfo": "Y",
    }


def build_checkout(order: dict, config: Optional[dict] = None) -> dict:
    if not ecpay_configured(config):
        return {
            "mode": "manual",
            "checkout_url": None,
            "form": None,
            "message": "付款服務尚未設定；訂單保留為待付款，不會假裝付款成功。",
            "todo": ["ECPAY_MERCHANT_ID", "ECPAY_HASH_KEY", "ECPAY_HASH_IV"],
        }
    form = _base_checkout_form(order, config)
    form["CheckMacValue"] = generate_check_mac(form, config)
    return {
        "mode": "ecpay",
        "checkout_url": _checkout_url(config),
        "form": form,
        "message": "正在前往安全付款頁面。",
    }


def build_period_checkout(order: dict, config: Optional[dict] = None) -> dict:
    if not ecpay_configured(config):
        return {
            "mode": "manual",
            "checkout_url": None,
            "form": None,
            "message": "自動續費服務尚未設定；不會建立或假裝啟用自動續費。",
        }
    cycle = str(order.get("billing_cycle") or "").strip().lower()
    if cycle not in {"monthly", "yearly"}:
        raise ValueError("billing_cycle must be monthly or yearly")
    form = _base_checkout_form(order, config)
    public_url = _cfg(config, "APP_PUBLIC_URL").rstrip("/")
    form.update(
        {
            "PeriodAmount": int(order.get("amount") or 0),
            "PeriodType": "M" if cycle == "monthly" else "Y",
            "Frequency": 1,
            "ExecTimes": int(_cfg(config, "ECPAY_PERIOD_TIMES", "99") or 99),
            "PeriodReturnURL": (
                f"{public_url}/api/payment/ecpay/period-notify" if public_url else ""
            ),
        }
    )
    form["CheckMacValue"] = generate_check_mac(form, config)
    return {
        "mode": "ecpay_period",
        "checkout_url": _checkout_url(config),
        "form": form,
        "message": "正在前往安全付款頁面建立自動續費。",
    }


def parse_notify_payload(
    form: dict, config: Optional[dict] = None
) -> tuple[Optional[dict], Optional[str]]:
    data = {str(key): value for key, value in dict(form or {}).items()}
    if not verify_check_mac(data, config):
        return None, "invalid_check_mac"
    try:
        amount = int(data.get("TradeAmt") or data.get("PeriodAmount") or 0)
    except (TypeError, ValueError):
        amount = 0
    return {
        "status": str(data.get("RtnCode") or ""),
        "message": str(data.get("RtnMsg") or ""),
        "order_id": str(data.get("MerchantTradeNo") or ""),
        "transaction_id": str(data.get("TradeNo") or ""),
        "amount": amount,
        "simulated": str(data.get("SimulatePaid") or "0") == "1",
        "period_type": str(data.get("PeriodType") or ""),
        "frequency": str(data.get("Frequency") or ""),
        "exec_times": str(data.get("ExecTimes") or ""),
        "process_date": str(data.get("ProcessDate") or data.get("PaymentDate") or ""),
        "raw": data,
    }, None


def notify_success(
    parsed: Optional[dict], config: Optional[dict] = None
) -> bool:
    production = _cfg(config, "ECPAY_STAGE", "sandbox").lower() == "prod"
    return bool(
        parsed
        and str(parsed.get("status")) == "1"
        and not (production and bool(parsed.get("simulated")))
    )


def build_credit_action(
    *,
    merchant_trade_no: str,
    trade_no: str,
    amount: int,
    action: str,
    config: Optional[dict] = None,
) -> dict:
    if not ecpay_configured(config):
        raise RuntimeError("ecpay_not_configured")
    normalized_action = str(action or "").strip().upper()
    if normalized_action not in {"C", "R", "E", "N"}:
        raise ValueError("action must be C, R, E or N")
    if (
        normalized_action == "R"
        and _cfg(config, "ECPAY_STAGE", "sandbox").lower() != "prod"
    ):
        raise RuntimeError("ecpay_refund_requires_production")
    total = int(amount or 0)
    if total <= 0:
        raise ValueError("amount must be positive")
    form = {
        "MerchantID": _cfg(config, "ECPAY_MERCHANT_ID"),
        "MerchantTradeNo": str(merchant_trade_no or "").strip(),
        "TradeNo": str(trade_no or "").strip(),
        "Action": normalized_action,
        "TotalAmount": total,
    }
    if not form["MerchantTradeNo"] or not form["TradeNo"]:
        raise ValueError("merchant_trade_no and trade_no are required")
    form["CheckMacValue"] = generate_check_mac(form, config)
    return {
        "url": "https://payment.ecpay.com.tw/CreditDetail/DoAction",
        "form": form,
    }


def build_period_action(
    *,
    merchant_trade_no: str,
    action: str,
    config: Optional[dict] = None,
) -> dict:
    if not ecpay_configured(config):
        raise RuntimeError("ecpay_not_configured")
    normalized_action = str(action or "").strip()
    if normalized_action not in {"Cancel", "ReAuth"}:
        raise ValueError("action must be Cancel or ReAuth")
    order_no = str(merchant_trade_no or "").strip()
    if not order_no:
        raise ValueError("merchant_trade_no is required")
    form = {
        "MerchantID": _cfg(config, "ECPAY_MERCHANT_ID"),
        "MerchantTradeNo": order_no,
        "Action": normalized_action,
        "TimeStamp": int(time.time()),
    }
    form["CheckMacValue"] = generate_check_mac(form, config)
    base = (
        "https://payment.ecpay.com.tw"
        if _cfg(config, "ECPAY_STAGE", "sandbox").lower() == "prod"
        else "https://payment-stage.ecpay.com.tw"
    )
    return {
        "url": f"{base}/Cashier/CreditCardPeriodAction",
        "form": form,
    }


def parse_action_response(
    response: Any,
    config: Optional[dict] = None,
) -> tuple[Optional[dict], Optional[str]]:
    from urllib.parse import parse_qs

    if isinstance(response, bytes):
        response = response.decode("utf-8", errors="replace")
    if isinstance(response, str):
        data = {key: values[0] for key, values in parse_qs(response).items()}
    elif isinstance(response, dict):
        data = dict(response)
    else:
        return None, "invalid_gateway_response"
    if not data:
        return None, "empty_gateway_response"
    if not verify_check_mac(data, config):
        return None, "invalid_check_mac"
    return {
        "status": str(data.get("RtnCode") or ""),
        "message": str(data.get("RtnMsg") or ""),
        "order_id": str(data.get("MerchantTradeNo") or ""),
        "transaction_id": str(data.get("TradeNo") or ""),
        "raw": data,
    }, None
