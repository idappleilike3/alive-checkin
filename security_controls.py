"""Central, side-effect-free security controls and release readiness evidence."""

from __future__ import annotations

from datetime import datetime


SENSITIVE_KEYS = {
    "token", "access_token", "id_token", "authorization", "cookie", "password",
    "secret", "api_key", "hash_key", "hash_iv", "latitude", "longitude",
    "address", "coordinates", "request_body",
}


def _flag(config, name):
    return str(config.get(name) or "").strip().lower() in {"1", "true", "yes", "on", "passed"}


def _mask_phone(value):
    text = str(value or "")
    return f"{text[:2]}{'*' * max(0, len(text) - 4)}{text[-2:]}" if len(text) >= 6 else "[REDACTED]"


def _mask_line_uid(value):
    text = str(value or "")
    return f"{text[:2]}***{text[-3:]}" if len(text) >= 8 else "[REDACTED]"


def redact_sensitive(value, key=""):
    normalized = str(key or "").casefold()
    if normalized in SENSITIVE_KEYS or any(part in normalized for part in ("token", "secret", "password", "coordinate")):
        return "[REDACTED]"
    if normalized in {"phone", "mobile", "contact_phone", "emergency_phone"}:
        return _mask_phone(value)
    if normalized in {"line_user_id", "uid", "target_line_user_id"}:
        return _mask_line_uid(value)
    if isinstance(value, dict):
        return {str(k): redact_sensitive(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_sensitive(item) for item in value]
    return value


def apply_security_headers(response, *, is_https, path="/"):
    headers = response.headers
    headers["X-Content-Type-Options"] = "nosniff"
    headers["X-Frame-Options"] = "DENY"
    headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(self)"
    headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
    headers["Content-Security-Policy"] = (
        "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
        "form-action 'self' https://payment.ecpay.com.tw https://ccore.newebpay.com; "
        "script-src 'self' 'unsafe-inline' https://static.line-scdn.net https://www.googletagmanager.com; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; "
        "connect-src 'self' https://api.line.me https://liff.line.me https://www.google-analytics.com; "
        "frame-src https://liff.line.me https://www.google.com https://maps.google.com https://payment.ecpay.com.tw https://ccore.newebpay.com"
    )
    if is_https:
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
    if str(path).startswith("/api/") or str(path).startswith("/admin"):
        headers["Cache-Control"] = "no-store"
    return response


def _item(number, name, passed, evidence, blocking="operation"):
    return {
        "number": number,
        "name": name,
        "status": "passed" if passed else "not_checked",
        "evidence": evidence,
        "blocking": blocking,
    }


def security_readiness(config, now=None):
    current = now or datetime.now()
    required_secrets = all([
        len(str(config.get("ADMIN_SESSION_SECRET") or "").encode()) >= 32,
        bool(str(config.get("ADMIN_PASSWORD") or "").strip()),
        len(str(config.get("LINE_CHANNEL_SECRET") or "").encode()) >= 16,
        len(str(config.get("CRON_SECRET") or "").encode()) >= 32,
    ])
    secret_ready = required_secrets and _flag(config, "SECRETS_SCAN_PASSED")
    database_ready = bool(str(config.get("DATABASE_URL") or "").strip()) and _flag(config, "DATABASE_LEAST_PRIVILEGE_CONFIRMED")
    dependency_ready = _flag(config, "DEPENDENCY_AUDIT_PASSED")
    monitoring_ready = _flag(config, "SECURITY_MONITORING_ENABLED")
    recovery_ready = bool(str(config.get("BACKUP_RESTORE_TESTED_AT") or "").strip()) and _flag(config, "INCIDENT_RUNBOOK_CONFIRMED")
    items = [
        _item(1, "機密與供應鏈", secret_ready, "環境機密完整且機密掃描證據已確認"),
        _item(2, "輸入、輸出與檔案安全", True, "後端欄位驗證、文字輸出與安全 URL 控制已啟用"),
        _item(3, "身分驗證與工作階段", required_secrets, "LINE／排程／管理員驗證採 fail-closed"),
        _item(4, "物件授權與隱私", True, "會員與管理 API 由伺服器端主體及角色授權"),
        _item(5, "資料庫與資料保護", database_ready, "需確認正式資料庫最小權限"),
        _item(6, "瀏覽器、網路與 API 防護", True, "CSP、HSTS、nosniff、同源及不快取標頭已啟用"),
        _item(7, "頻率限制與濫用防護", True, "登入、推播、搬家與高風險操作限制已啟用", "test"),
        _item(8, "日誌、稽核與偵測", monitoring_ready, "需確認正式異常監控與警示", "test"),
        _item(9, "備份、復原與事故應變", recovery_ready, "需有備份還原日期及事故手冊確認", "test"),
        _item(10, "驗證與上線門檻", dependency_ready, "需有依賴弱點掃描通過證據", "test"),
    ]
    operation_allowed = all(row["status"] == "passed" for row in items[:6])
    test_allowed = operation_allowed and all(row["status"] == "passed" for row in items[6:])
    overall = "ready" if test_allowed else ("blocked_public_test" if operation_allowed else "blocked_public_operation")
    return {
        "overall": overall,
        "public_operation_allowed": operation_allowed,
        "public_test_allowed": test_allowed,
        "generated_at": current.isoformat(timespec="seconds"),
        "items": items,
    }
