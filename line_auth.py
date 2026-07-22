"""LINE LIFF id_token verification helpers."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional


VerifyFn = Callable[[str, str], Optional[dict]]


def line_login_channel_id(config: Optional[dict] = None) -> str:
    cfg = config or {}
    explicit = (
        cfg.get("LINE_LOGIN_CHANNEL_ID")
        or os.environ.get("LINE_LOGIN_CHANNEL_ID")
        or ""
    ).strip()
    if explicit:
        return explicit
    liff_id = (cfg.get("LIFF_ID") or os.environ.get("LIFF_ID") or "").strip()
    if "-" in liff_id:
        return liff_id.split("-", 1)[0]
    return liff_id


def verify_line_id_token(
    id_token: str,
    client_id: str,
    *,
    opener: Optional[Callable[..., Any]] = None,
) -> Optional[dict]:
    """Verify a LIFF/LINE Login id_token via LINE OAuth2 verify endpoint.

    Returns the decoded claims dict (must include ``sub``) or None on failure.
    """
    token = (id_token or "").strip()
    cid = (client_id or "").strip()
    if not token or not cid:
        return None

    body = urllib.parse.urlencode({"id_token": token, "client_id": cid}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.line.me/oauth2/v2.1/verify",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(req, timeout=8) as res:
            payload = json.loads(res.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None

    sub = str(payload.get("sub") or "").strip()
    if not sub:
        return None
    return payload


def extract_id_token(headers: dict, payload: Optional[dict] = None, args: Optional[dict] = None) -> str:
    payload = payload or {}
    args = args or {}
    auth = str(headers.get("Authorization") or headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        bearer = auth[7:].strip()
        if bearer:
            return bearer
    for source in (
        headers.get("X-Line-Id-Token"),
        headers.get("x-line-id-token"),
        payload.get("id_token"),
        args.get("id_token"),
    ):
        text = str(source or "").strip()
        if text:
            return text
    return ""


def require_liff_auth(config: Optional[dict] = None) -> bool:
    cfg = config or {}
    raw = cfg.get("REQUIRE_LIFF_AUTH")
    if raw is None:
        raw = os.environ.get("REQUIRE_LIFF_AUTH", "0")
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def resolve_line_user_id(
    *,
    headers: dict,
    payload: Optional[dict] = None,
    args: Optional[dict] = None,
    config: Optional[dict] = None,
    verify_fn: Optional[VerifyFn] = None,
) -> tuple[Optional[str], Optional[tuple[dict, int]]]:
    """Resolve authenticated LINE user id.

    When REQUIRE_LIFF_AUTH is on, id_token is mandatory and overrides any client
    ``line_user_id``. When off, falls back to claimed line_user_id (tests/dev).
    """
    payload = payload or {}
    args = args or {}
    claimed = str(payload.get("line_user_id") or args.get("line_user_id") or "").strip()
    token = extract_id_token(headers, payload, args)
    must_auth = require_liff_auth(config)
    client_id = line_login_channel_id(config)
    verifier = verify_fn or verify_line_id_token

    if token:
        claims = verifier(token, client_id)
        if not claims:
            return None, ({"ok": False, "error": "invalid id_token"}, 401)
        sub = str(claims.get("sub") or "").strip()
        if claimed and claimed != sub:
            return None, ({"ok": False, "error": "line_user_id mismatch"}, 403)
        return sub, None

    if must_auth:
        return None, ({"ok": False, "error": "missing id_token"}, 401)
    if claimed:
        return claimed, None
    return None, ({"ok": False, "error": "missing line_user_id"}, 400)
