"""Financial reporting helpers for the authenticated admin console."""

from __future__ import annotations

import math
import re
import secrets
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP


MONEY = Decimal("0.01")
ALLOWED_CATEGORIES = {
    "hosting", "database", "line", "payment", "domain", "security",
    "backup", "marketing", "support", "email", "accounting", "other",
}
ALLOWED_EXPENSE_TYPES = {"fixed", "usage", "one_time"}


class FinanceValidationError(ValueError):
    pass


def _decimal(value, *, minimum=Decimal("0"), maximum=Decimal("100000000")):
    try:
        number = Decimal(str(value))
    except Exception as exc:
        raise FinanceValidationError("金額或費率格式錯誤") from exc
    if not number.is_finite() or number < minimum or number > maximum:
        raise FinanceValidationError("金額或費率超出允許範圍")
    return number


def _money(value):
    number = _decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)
    return int(number) if number == number.to_integral() else float(number)


def _safe_text(value, label, max_length):
    text = str(value or "").strip()
    if not text or len(text) > max_length or re.search(r"[<>\x00-\x1f]", text):
        raise FinanceValidationError(f"{label}格式錯誤")
    return text


def _month(value):
    text = str(value or "")
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", text):
        raise FinanceValidationError("月份格式錯誤")
    return text


def _date(value, label="日期"):
    text = str(value or "")
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise FinanceValidationError(f"{label}格式錯誤") from exc
    return text


def _finance(state):
    finance = state.setdefault("finance", {})
    finance.setdefault("expenses", [])
    finance.setdefault("audit", [])
    settings = finance.setdefault("settings", {})
    settings.setdefault("tax_enabled", True)
    settings.setdefault("tax_rate_percent", "5")
    settings.setdefault("gateway_fees", {
        "ecpay": {"percent": "2.75", "fixed": "0"},
        "newebpay": {"percent": "2.8", "fixed": "0"},
    })
    settings.setdefault("break_even_prices", {"199": 199, "399": 399, "799": 799})
    return finance


def _audit(finance, action, actor, now, target_id=""):
    finance["audit"].append({
        "id": f"FA{secrets.token_hex(8).upper()}",
        "action": action,
        "actor_role": str(actor or "unknown")[:40],
        "target_id": str(target_id or "")[:80],
        "created_at": now.isoformat(timespec="seconds"),
    })


def create_expense(state, payload, actor, now=None):
    current = now or datetime.now()
    finance = _finance(state)
    category = str(payload.get("category") or "other")
    expense_type = str(payload.get("expense_type") or "one_time")
    if category not in ALLOWED_CATEGORIES or expense_type not in ALLOWED_EXPENSE_TYPES:
        raise FinanceValidationError("支出分類或類型錯誤")
    has_invoice = payload.get("has_tax_invoice") is True
    deductible = has_invoice and payload.get("input_tax_deductible") is True
    expense = {
        "id": f"EXP{secrets.token_hex(6).upper()}",
        "name": _safe_text(payload.get("name"), "費用名稱", 100),
        "vendor": str(payload.get("vendor") or "").strip()[:100],
        "category": category,
        "expense_type": expense_type,
        "amount": _money(payload.get("amount")),
        "incurred_on": _date(payload.get("incurred_on") or current.strftime("%Y-%m-%d")),
        "next_billing_on": _date(payload["next_billing_on"], "下次扣款日") if payload.get("next_billing_on") else "",
        "has_tax_invoice": has_invoice,
        "input_tax_deductible": deductible,
        "status": "active",
        "note": str(payload.get("note") or "").strip()[:500],
        "created_at": current.isoformat(timespec="seconds"),
    }
    finance["expenses"].append(expense)
    _audit(finance, "expense.create", actor, current, expense["id"])
    return expense


def update_finance_settings(state, payload, actor, now=None):
    current = now or datetime.now()
    finance = _finance(state)
    settings = finance["settings"]
    if "tax_enabled" in payload:
        settings["tax_enabled"] = payload.get("tax_enabled") is True
    if "tax_rate_percent" in payload:
        settings["tax_rate_percent"] = str(_decimal(payload["tax_rate_percent"], maximum=Decimal("20")))
    if "gateway_fees" in payload:
        incoming = payload.get("gateway_fees")
        if not isinstance(incoming, dict):
            raise FinanceValidationError("金流費率格式錯誤")
        for provider in ("ecpay", "newebpay"):
            if provider not in incoming:
                continue
            row = incoming[provider]
            if not isinstance(row, dict):
                raise FinanceValidationError("金流費率格式錯誤")
            settings["gateway_fees"][provider] = {
                "percent": str(_decimal(row.get("percent", 0), maximum=Decimal("20"))),
                "fixed": str(_decimal(row.get("fixed", 0), maximum=Decimal("1000"))),
            }
    _audit(finance, "settings.update", actor, current)
    return settings


def _gateway_fee(amount, provider, settings):
    row = (settings.get("gateway_fees") or {}).get(provider) or {"percent": 0, "fixed": 0}
    value = _decimal(amount) * _decimal(row.get("percent", 0), maximum=Decimal("20")) / Decimal("100")
    value += _decimal(row.get("fixed", 0), maximum=Decimal("1000"))
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def _is_yearly(order):
    return str(order.get("billing_cycle") or "").lower() == "year" or str(order.get("plan") or "").endswith("_year")


def _month_index(text):
    year, month = (int(part) for part in text.split("-"))
    return year * 12 + month - 1


def finance_dashboard(state, month, now=None):
    selected = _month(month)
    finance = _finance(state)
    settings = finance["settings"]
    current_orders = []
    gross_collected = refunds = Decimal("0")
    gateway_fees = Decimal("0")
    recognized = Decimal("0")
    target_index = _month_index(selected)
    for order in state.get("orders") or []:
        if str(order.get("status") or "") not in {"paid", "partially_refunded", "refunded"}:
            continue
        paid_month = str(order.get("paid_at") or "")[:7]
        if not re.fullmatch(r"\d{4}-\d{2}", paid_month):
            continue
        amount = _decimal(order.get("amount") or 0)
        refunded = min(amount, _decimal(order.get("refunded_amount") or 0))
        net = amount - refunded
        provider = str(order.get("provider") or "ecpay")
        if paid_month == selected:
            gross_collected += amount
            refunds += refunded
            gateway_fees += _gateway_fee(net, provider, settings) if net > 0 else Decimal("0")
            current_orders.append(order)
        paid_index = _month_index(paid_month)
        if _is_yearly(order):
            if paid_index <= target_index < paid_index + 12:
                recognized += net / Decimal("12")
        elif paid_month == selected:
            recognized += net

    expenses = [
        row for row in finance["expenses"]
        if row.get("status") == "active" and str(row.get("incurred_on") or "")[:7] == selected
    ]
    expense_gross = sum((_decimal(row.get("amount") or 0) for row in expenses), Decimal("0"))
    tax_rate = _decimal(settings.get("tax_rate_percent") or 5, maximum=Decimal("20"))
    tax_factor = Decimal("1") + tax_rate / Decimal("100")
    input_credit = sum((
        _decimal(row.get("amount") or 0) - _decimal(row.get("amount") or 0) / tax_factor
        for row in expenses
        if row.get("has_tax_invoice") and row.get("input_tax_deductible")
    ), Decimal("0"))
    net_collected = gross_collected - refunds
    output_tax = net_collected - net_collected / tax_factor if settings.get("tax_enabled") else Decimal("0")
    payable_tax = max(Decimal("0"), output_tax - input_credit)
    cash_profit = net_collected - gateway_fees - expense_gross - payable_tax
    accrual_profit = recognized - expense_gross
    monthly_fixed = expense_gross + gateway_fees + payable_tax
    break_even = {}
    for code, price in (settings.get("break_even_prices") or {}).items():
        price_value = _decimal(price)
        net_price = price_value / tax_factor if settings.get("tax_enabled") else price_value
        break_even[str(code)] = math.ceil(float(monthly_fixed / net_price)) if net_price > 0 else 0
    return {
        "month": selected,
        "cash": {
            "gross_collected": _money(gross_collected),
            "refunds": _money(refunds),
            "net_collected": _money(net_collected),
            "gateway_fees": _money(gateway_fees),
            "profit": _money(cash_profit),
        },
        "accrual": {"recognized_gross": _money(recognized), "profit": _money(accrual_profit)},
        "tax": {
            "output_tax": _money(output_tax),
            "input_tax_credit": _money(input_credit),
            "estimated_payable": _money(payable_tax),
        },
        "expenses": {"gross": _money(expense_gross), "items": expenses},
        "break_even_members": break_even,
        "orders_count": len(current_orders),
        "settings": settings,
    }
