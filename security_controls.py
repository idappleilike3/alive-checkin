"""Central, side-effect-free security controls and release readiness evidence."""

from __future__ import annotations

from datetime import datetime


SENSITIVE_KEYS = {
    "token", "access_token", "id_token", "authorization", "cookie", "password",
    "secret", "api_key", "hash_key", "hash_iv", "latitude", "longitude",
    "address", "coordinates", "request_body",
}


EVIDENCE_SOURCES = {
    "automated_test",
    "formal_http_probe",
    "dependency_scan",
    "render_postgres_setting",
    "backup_restore_drill",
    "incident_response_drill",
}


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


def _valid_checked_at(value):
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return text


def _item(config, number, name, default_evidence, remediation, *, prerequisite=True, blocking="operation"):
    prefix = f"SECURITY_CHECK_{number:02d}"
    requested_status = str(config.get(f"{prefix}_STATUS") or "").strip().lower()
    source = str(config.get(f"{prefix}_SOURCE") or "").strip()
    checked_at = _valid_checked_at(config.get(f"{prefix}_CHECKED_AT"))
    evidence = str(config.get(f"{prefix}_EVIDENCE") or "").strip()
    evidence_complete = source in EVIDENCE_SOURCES and bool(checked_at and evidence)
    if requested_status == "failed" and evidence_complete:
        status = "failed"
    elif requested_status == "passed" and evidence_complete and prerequisite:
        status = "passed"
    else:
        status = "not_checked"
    return {
        "number": number,
        "name": name,
        "status": status,
        "checked_at": checked_at or None,
        "evidence_source": source if source in EVIDENCE_SOURCES else None,
        "evidence": evidence or default_evidence,
        "blocking": blocking,
        "remediation": "" if status == "passed" else remediation,
    }


def security_readiness(config, now=None):
    current = now or datetime.now()
    required_secrets = all([
        len(str(config.get("ADMIN_SESSION_SECRET") or "").encode()) >= 32,
        bool(str(config.get("ADMIN_PASSWORD") or "").strip()),
        len(str(config.get("LINE_CHANNEL_SECRET") or "").encode()) >= 16,
        len(str(config.get("CRON_SECRET") or "").encode()) >= 32,
    ])
    database_ready = bool(str(config.get("DATABASE_URL") or "").strip())
    items = [
        _item(config, 1, "機密與供應鏈", "尚無具日期的機密與供應鏈掃描證據", "執行機密掃描並記錄不含機密值的結果、來源與日期", prerequisite=required_secrets),
        _item(config, 2, "輸入、輸出與檔案安全", "尚無具日期的負向測試證據", "執行 XSS、危險 URL、路徑與邊界負向測試並保存結果"),
        _item(config, 3, "身分驗證與工作階段", "尚無具日期的驗證與工作階段測試證據", "完成未登入、逾時、CSRF、Cookie 與 fail-closed 測試", prerequisite=required_secrets),
        _item(config, 4, "物件授權與隱私", "尚無具日期的越權測試證據", "完成角色及跨會員、訂單與守護關係越權測試"),
        _item(config, 5, "資料庫與資料保護", "尚無正式資料庫最小權限與加密證據", "由資料庫平台確認最小權限、傳輸加密及備份加密", prerequisite=database_ready),
        _item(config, 6, "瀏覽器、網路與 API 防護", "尚無正式 HTTPS 與安全標頭探針證據", "對正式站執行 HTTPS、安全標頭、no-store 及未授權探針"),
        _item(config, 7, "頻率限制與濫用防護", "尚無具日期的濫用限制負向測試證據", "完成登入、推播、SOS、邀請、重綁及高成本通道限制測試", blocking="test"),
        _item(config, 8, "日誌、稽核與偵測", "尚無正式告警收件證據", "以不含會員敏感資料的測試事件確認告警可收件", blocking="test"),
        _item(config, 9, "備份、復原與事故應變", "尚無備份還原與事故演練證據", "完成隔離還原、筆數核對、復原時間及事故手冊演練", blocking="test"),
        _item(config, 10, "驗證與上線門檻", "尚無具日期的依賴掃描及發布驗證證據", "完成固定版本依賴掃描、回歸、啟動與健康探針", blocking="test"),
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
