"""Financial reporting helpers for the authenticated admin console."""

from __future__ import annotations

import math
import re
import secrets
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlparse


MONEY = Decimal("0.01")
ALLOWED_CATEGORIES = {
    "hosting", "database", "line", "payment", "domain", "security",
    "backup", "marketing", "support", "email", "accounting", "other",
}
ALLOWED_EXPENSE_TYPES = {"fixed", "usage", "one_time"}
ALLOWED_ESSENTIAL_SERVICE_STATUSES = {"pending", "due_soon", "paid", "overdue", "pausable"}
ALLOWED_ESSENTIAL_SERVICE_PRIORITIES = {"critical", "required", "optional"}
ALLOWED_ESSENTIAL_SERVICE_BILLING_CYCLES = {"monthly", "yearly", "one_time"}
ESSENTIAL_SERVICE_REMINDER_NODES = (30, 14, 7, 3, 1)
RENDER_ESSENTIAL_SERVICE_ID = "render-postgresql-alive-checkin-state"


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


def _safe_optional_text(value, label, max_length):
    text = str(value or "").strip()
    if len(text) > max_length or re.search(r"[<>\x00-\x1f]", text):
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


def _https_url(value):
    text = _safe_text(value, "付款網址", 500)
    try:
        parsed = urlparse(text)
    except ValueError as exc:
        raise FinanceValidationError("付款網址格式錯誤") from exc
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise FinanceValidationError("付款網址格式錯誤")
    return text


def _currency(value):
    text = str(value or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", text):
        raise FinanceValidationError("原幣幣別格式錯誤")
    return text


def _reminder_days(value):
    if value is None:
        return list(ESSENTIAL_SERVICE_REMINDER_NODES)
    if not isinstance(value, (list, tuple, set)):
        raise FinanceValidationError("提醒天數格式錯誤")
    days = set()
    for item in value:
        if isinstance(item, bool) or not re.fullmatch(r"\d+", str(item).strip()):
            raise FinanceValidationError("提醒天數格式錯誤")
        day = int(str(item).strip())
        if day not in ESSENTIAL_SERVICE_REMINDER_NODES:
            raise FinanceValidationError("提醒天數格式錯誤")
        days.add(day)
    return [day for day in ESSENTIAL_SERVICE_REMINDER_NODES if day in days]


def _finance(state):
    finance = state.setdefault("finance", {})
    finance.setdefault("expenses", [])
    finance.setdefault("audit", [])
    finance.setdefault("essential_services", [])
    settings = finance.setdefault("settings", {})
    settings.setdefault("tax_enabled", True)
    settings.setdefault("tax_rate_percent", "5")
    settings.setdefault("gateway_fees", {
        "ecpay": {"percent": "2.75", "fixed": "0"},
        "newebpay": {"percent": "2.8", "fixed": "0"},
    })
    settings.setdefault("break_even_prices", {"199": 199, "399": 399, "799": 799})
    return finance


def _render_essential_service(current):
    timestamp = current.isoformat(timespec="seconds")
    return {
        "id": RENDER_ESSENTIAL_SERVICE_ID,
        "vendor": "Render",
        "name": "alive-checkin-state",
        "category": "database",
        "billing_cycle": "monthly",
        "currency": "USD",
        "original_amount": 6.3,
        "payment_url": "https://dashboard.render.com/d/dpg-d9hn1guq1p3s73a7atr0-a/plan",
        "status": "pending",
        "priority": "critical",
        "monthly_usd": 6.3,
        "monthly_twd": 210,
        "annual_twd": 2500,
        "annual_budget_override": 2500,
        "deadline": "2026-08-23",
        "next_renewal_on": "2026-08-23",
        "reminder_days": list(ESSENTIAL_SERVICE_REMINDER_NODES),
        "risk": "尚未扣款，若未在期限前升級可能造成資料庫服務中斷。",
        "note": "目前尚未扣款，應在期限前附近升級方案。",
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def _normalize_persisted_service(service, current):
    is_render = str(service.get("id") or "") == RENDER_ESSENTIAL_SERVICE_ID
    category = str(service.get("category") or ("database" if is_render else "other"))
    if category not in ALLOWED_CATEGORIES:
        raise FinanceValidationError("必要服務分類錯誤")
    billing_cycle = str(service.get("billing_cycle") or "monthly")
    if billing_cycle not in ALLOWED_ESSENTIAL_SERVICE_BILLING_CYCLES:
        raise FinanceValidationError("必要服務計費週期錯誤")
    inferred_currency = "USD" if "monthly_usd" in service else "TWD"
    currency = _currency(service.get("currency") or inferred_currency)
    if "original_amount" in service:
        original_amount = _money(service["original_amount"])
    elif currency == "USD" and "monthly_usd" in service:
        original_amount = _money(service.get("monthly_usd"))
    else:
        original_amount = _money(service.get("monthly_twd", 0))
    monthly_twd = _money(service.get("monthly_twd", 0))
    annual_override = 2500 if is_render else None
    annual_twd = annual_override if annual_override is not None else _money(_decimal(monthly_twd) * 12)
    deadline = _date(service.get("deadline"), "期限")
    timestamp = current.isoformat(timespec="seconds")
    service.update({
        "category": category,
        "billing_cycle": billing_cycle,
        "currency": currency,
        "original_amount": original_amount,
        "monthly_usd": _money(service.get("monthly_usd", original_amount if currency == "USD" and billing_cycle == "monthly" else 0)),
        "monthly_twd": monthly_twd,
        "annual_twd": annual_twd,
        "annual_budget_override": annual_override,
        "deadline": deadline,
        "next_renewal_on": _date(service.get("next_renewal_on") or deadline, "下次續費日"),
        "reminder_days": _reminder_days(service.get("reminder_days")),
        "created_at": str(service.get("created_at") or timestamp),
        "updated_at": str(service.get("updated_at") or service.get("created_at") or timestamp),
    })
    return service


def _essential_services(finance, current, actor="system"):
    services = finance.setdefault("essential_services", [])
    if not isinstance(services, list):
        raise FinanceValidationError("必要服務資料格式錯誤")
    seed = next((
        row for row in services
        if isinstance(row, dict) and str(row.get("id") or "") == RENDER_ESSENTIAL_SERVICE_ID
    ), None)
    if seed is None:
        seed = _render_essential_service(current)
        services.append(seed)
    for service in services:
        if not isinstance(service, dict):
            raise FinanceValidationError("必要服務資料格式錯誤")
        _normalize_persisted_service(service, current)
    seed_audited = any(
        row.get("action") == "essential_service.create"
        and str(row.get("target_id") or "") == RENDER_ESSENTIAL_SERVICE_ID
        for row in finance.get("audit") or []
        if isinstance(row, dict)
    )
    if not seed_audited:
        _audit(finance, "essential_service.create", actor, current, RENDER_ESSENTIAL_SERVICE_ID)
    return services


def _essential_service_values(payload, current, existing=None):
    source = existing or {}
    values = {}
    for field, label, maximum in (("vendor", "供應商", 100), ("name", "服務名稱", 100)):
        if field in payload or not existing:
            values[field] = _safe_text(payload.get(field, source.get(field)), label, maximum)
    if "payment_url" in payload or not existing:
        values["payment_url"] = _https_url(payload.get("payment_url", source.get("payment_url")))
    for field, allowed, label in (
        ("status", ALLOWED_ESSENTIAL_SERVICE_STATUSES, "必要服務狀態"),
        ("priority", ALLOWED_ESSENTIAL_SERVICE_PRIORITIES, "必要服務優先度"),
    ):
        if field in payload or not existing:
            value = str(payload.get(field, source.get(field)) or "")
            if value not in allowed:
                raise FinanceValidationError(f"{label}錯誤")
            values[field] = value
    if "category" in payload or not existing:
        category = str(payload.get("category", source.get("category") or "other") or "")
        if category not in ALLOWED_CATEGORIES:
            raise FinanceValidationError("必要服務分類錯誤")
        values["category"] = category
    if "billing_cycle" in payload or not existing:
        billing_cycle = str(payload.get("billing_cycle", source.get("billing_cycle") or "monthly") or "")
        if billing_cycle not in ALLOWED_ESSENTIAL_SERVICE_BILLING_CYCLES:
            raise FinanceValidationError("必要服務計費週期錯誤")
        values["billing_cycle"] = billing_cycle
    effective_cycle = values.get("billing_cycle", source.get("billing_cycle") or "monthly")
    if "currency" in payload or not existing:
        inferred_currency = "USD" if "monthly_usd" in payload else "TWD"
        values["currency"] = _currency(payload.get("currency", source.get("currency") or inferred_currency))
    effective_currency = values.get("currency", source.get("currency") or "TWD")
    legacy_original_update = "monthly_usd" in payload and "original_amount" not in payload
    if "original_amount" in payload or legacy_original_update or not existing:
        if "original_amount" in payload:
            raw_original = payload["original_amount"]
        elif effective_currency == "USD" and "monthly_usd" in payload:
            raw_original = payload["monthly_usd"]
        else:
            raw_original = payload.get("monthly_twd", source.get("monthly_twd"))
        values["original_amount"] = _money(raw_original)
    effective_original = values.get("original_amount", source.get("original_amount", 0))
    if "monthly_twd" in payload or not existing:
        values["monthly_twd"] = _money(payload.get("monthly_twd", source.get("monthly_twd")))
    effective_monthly_twd = values.get("monthly_twd", source.get("monthly_twd", 0))
    annual_override = source.get("annual_budget_override") if existing else None
    derived_annual = _money(_decimal(effective_monthly_twd) * 12)
    annual_twd = _money(annual_override) if annual_override is not None else derived_annual
    if "annual_twd" in payload and _money(payload["annual_twd"]) != annual_twd:
        raise FinanceValidationError("年預算必須由月預算乘以 12")
    if "monthly_twd" in payload or "annual_twd" in payload or not existing:
        values["annual_twd"] = annual_twd
        values["annual_budget_override"] = _money(annual_override) if annual_override is not None else None
    if any(field in payload for field in ("currency", "billing_cycle", "original_amount", "monthly_usd")) or not existing:
        values["monthly_usd"] = _money(
            effective_original if effective_currency == "USD" and effective_cycle == "monthly" else 0
        )
    if "deadline" in payload or not existing:
        values["deadline"] = _date(payload.get("deadline", source.get("deadline")), "期限")
    effective_deadline = values.get("deadline", source.get("deadline"))
    if "next_renewal_on" in payload or not existing:
        values["next_renewal_on"] = _date(
            payload.get("next_renewal_on", source.get("next_renewal_on") or effective_deadline),
            "下次續費日",
        )
    if "reminder_days" in payload or not existing:
        values["reminder_days"] = _reminder_days(payload.get("reminder_days", source.get("reminder_days")))
    for field, label, maximum in (("risk", "風險說明", 500), ("note", "備註", 500)):
        if field in payload:
            values[field] = _safe_optional_text(payload[field], label, maximum) if existing else _safe_text(payload[field], label, maximum)
        elif not existing:
            values[field] = str(source.get(field) or "").strip()[:maximum]
    values["updated_at"] = current.isoformat(timespec="seconds")
    return values


def _service_with_remaining_days(service, current):
    row = dict(service)
    deadline = datetime.strptime(row["deadline"], "%Y-%m-%d").date()
    row["days_remaining"] = (deadline - current.date()).days
    paid = row.get("status") == "paid"
    row["reminder_history"] = []
    for days_before_deadline in row.get("reminder_days") or []:
        scheduled_on = deadline - timedelta(days=days_before_deadline)
        if paid:
            status = "suppressed"
        elif scheduled_on < current.date():
            status = "missed"
        elif scheduled_on == current.date():
            status = "due"
        else:
            status = "upcoming"
        row["reminder_history"].append({
            "days_before_deadline": days_before_deadline,
            "scheduled_on": scheduled_on.isoformat(),
            "status": status,
        })
    return row


def create_essential_service(state, payload, actor, now=None):
    current = now or datetime.now()
    if not isinstance(payload, dict):
        raise FinanceValidationError("必要服務資料格式錯誤")
    finance = _finance(state)
    services = _essential_services(finance, current)
    service = {
        "id": f"ESS{secrets.token_hex(6).upper()}",
        **_essential_service_values(payload, current),
        "created_at": current.isoformat(timespec="seconds"),
    }
    services.append(service)
    _audit(finance, "essential_service.create", actor, current, service["id"])
    return _service_with_remaining_days(service, current)


def update_essential_service(state, service_id, payload, actor, now=None):
    current = now or datetime.now()
    if not isinstance(payload, dict):
        raise FinanceValidationError("必要服務資料格式錯誤")
    finance = _finance(state)
    services = _essential_services(finance, current)
    service = next((row for row in services if str(row.get("id") or "") == str(service_id or "")), None)
    if service is None:
        raise FinanceValidationError("必要服務不存在")
    service.update(_essential_service_values(payload, current, service))
    _audit(finance, "essential_service.update", actor, current, service["id"])
    return _service_with_remaining_days(service, current)


def essential_service_summary(state, now=None):
    current = now or datetime.now()
    finance = _finance(state)
    services = [_service_with_remaining_days(row, current) for row in _essential_services(finance, current)]
    status_counts = {status: 0 for status in ALLOWED_ESSENTIAL_SERVICE_STATUSES}
    for service in services:
        status_counts[service.get("status")] += 1
    return {
        "items": services,
        "services": services,
        "total_monthly_usd": _money(sum((_decimal(row.get("monthly_usd") or 0) for row in services), Decimal("0"))),
        "total_monthly_twd": _money(sum((_decimal(row.get("monthly_twd") or 0) for row in services), Decimal("0"))),
        "total_annual_twd": _money(sum((_decimal(row.get("annual_twd") or 0) for row in services), Decimal("0"))),
        "status_counts": status_counts,
        "reminder_nodes": list(ESSENTIAL_SERVICE_REMINDER_NODES),
    }


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
    current = now or datetime.now()
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
        "essential_services": essential_service_summary(state, current),
        "break_even_members": break_even,
        "orders_count": len(current_orders),
        "settings": settings,
    }
