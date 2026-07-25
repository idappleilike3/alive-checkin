from dataclasses import dataclass
from datetime import datetime
import urllib.error


@dataclass(frozen=True)
class PushFailure:
    kind: str
    status_code: int | None
    retry_after_seconds: int | None = None


def _status_code(exc):
    return getattr(exc, "status_code", None) or getattr(exc, "code", None)


def classify_push_exception(exc):
    code = _status_code(exc)
    headers = getattr(exc, "headers", None) or {}
    retry_after = headers.get("Retry-After") if hasattr(headers, "get") else None
    try:
        retry_after = int(retry_after) if retry_after else None
    except (TypeError, ValueError):
        retry_after = None
    text = str(exc or "").lower()
    if code in {400, 404} or "not a friend" in text or "blocked" in text:
        return PushFailure("permanent", code)
    if code in {401, 403}:
        return PushFailure("system", code)
    if code == 429:
        return PushFailure("rate_limited", code, retry_after)
    return PushFailure("transient", code)


def push_attempt_allowed(user, delivery_key):
    if user.get("line_push_blocked"):
        return False
    attempts = user.get("push_delivery_attempts") or {}
    return int((attempts.get(delivery_key) or {}).get("count") or 0) < 3


def record_push_failure(user, delivery_key, exc, now=None):
    now = now or datetime.now()
    failure = classify_push_exception(exc)
    if failure.kind == "permanent":
        user["line_push_blocked"] = True
        user["line_push_blocked_at"] = now.isoformat(timespec="seconds")
        return {"status": "blocked", "retry": False, "kind": failure.kind}
    attempts = dict(user.get("push_delivery_attempts") or {})
    entry = dict(attempts.get(delivery_key) or {})
    entry["count"] = int(entry.get("count") or 0) + 1
    entry["last_failed_at"] = now.isoformat(timespec="seconds")
    entry["kind"] = failure.kind
    entry["retry_after_seconds"] = failure.retry_after_seconds
    attempts[delivery_key] = entry
    user["push_delivery_attempts"] = dict(list(attempts.items())[-120:])
    retry = failure.kind in {"transient", "rate_limited"} and entry["count"] < 3
    return {
        "status": (
            "retrying"
            if retry
            else ("system_error" if failure.kind == "system" else "failed")
        ),
        "retry": retry,
        "kind": failure.kind,
        "attempt": entry["count"],
    }
