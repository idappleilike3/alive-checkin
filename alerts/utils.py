"""
alerts/utils.py — 工具函式(狀態 IO / 時間 / ID / 日誌)

獨立模組,不依賴 app.py。
所有 datetime 用 ISO8601 字串儲存(JSON-friendly)。
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional


# ============================================================================
# Time
# ============================================================================

def now_utc() -> datetime:
    """回傳 timezone-aware UTC now"""
    return datetime.now(timezone.utc)


def now_local(tz_offset_hours: int = 8) -> datetime:
    """預設 Asia/Taipei (+8)"""
    return datetime.now(timezone(timedelta(hours=tz_offset_hours)))


def now_iso(dt: Optional[datetime] = None) -> str:
    """ISO8601,秒精度"""
    if dt is None:
        dt = now_local()
    return dt.isoformat(timespec="seconds")


def today_string(dt: Optional[datetime] = None) -> str:
    """YYYY-MM-DD"""
    if dt is None:
        dt = now_local()
    return dt.strftime("%Y-%m-%d")


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """
    解析 ISO8601 字串 → datetime。
    容錯:空字串、None、格式錯誤 → 回 None(不 raise)。
    """
    if not value or not isinstance(value, str):
        return None
    try:
        # 處理 "2026-07-17T10:30:00+08:00" 或 "2026-07-17T10:30:00"
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def minutes_between(start_iso: str, end_iso: str) -> float:
    """算兩個 ISO 時間的分鐘差"""
    s = parse_datetime(start_iso)
    e = parse_datetime(end_iso)
    if not s or not e:
        return 0.0
    return (e - s).total_seconds() / 60.0


def is_expired(expires_at: str, now: Optional[datetime] = None) -> bool:
    """T+X 過期判斷"""
    exp = parse_datetime(expires_at)
    if not exp:
        return True
    n = now or now_local()
    return n > exp


# ============================================================================
# IDs
# ============================================================================

def new_alert_id() -> str:
    """alert_<12-char-hex>"""
    return f"alert_{uuid.uuid4().hex[:12]}"


# ============================================================================
# State IO(JSON-based,不耦合 app.py 的 load_state/save_state)
# ============================================================================

def load_state(data_file: str) -> Dict[str, Any]:
    """讀取整包 JSON state"""
    if not data_file or not os.path.exists(data_file):
        return {"users": {}, "alerts": {}, "guardian_groups": {}, "consent_pending": {}}
    try:
        with open(data_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"users": {}, "alerts": {}, "guardian_groups": {}, "consent_pending": {}}


def save_state(data_file: str, state: Dict[str, Any]) -> bool:
    """寫入整包 JSON state(原樣覆蓋,不做 lock — 由 caller 決定並發策略)"""
    if not data_file:
        return False
    try:
        # 確保目錄存在
        Path(data_file).parent.mkdir(parents=True, exist_ok=True)
        # 原子寫入(寫到 tmp 再 rename)
        tmp = f"{data_file}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, data_file)
        return True
    except OSError:
        return False


# ============================================================================
# 電話格式驗證
# ============================================================================

PHONE_PATTERN = re.compile(r"^09\d{8}$")


def normalize_phone(raw: Any) -> Optional[str]:
    """E.164 / 09xxxxxxxx 都接受;輸出 09xxxxxxxx 格式"""
    if not raw or not isinstance(raw, str):
        return None
    cleaned = re.sub(r"[\s\-\(\)\+]", "", raw)
    if cleaned.startswith("886"):
        cleaned = "0" + cleaned[3:]
    if PHONE_PATTERN.match(cleaned):
        return cleaned
    return None


def is_valid_phone(raw: Any) -> bool:
    return normalize_phone(raw) is not None


# ============================================================================
# Profile helpers(只讀,不修改)
# ============================================================================

def get_profile(state: Dict[str, Any], line_user_id: Optional[str]) -> Dict[str, Any]:
    """容錯版 get_profile"""
    if not line_user_id:
        return {}
    return state.get("users", {}).get(line_user_id, {})


def get_consented_contacts(profile: Dict[str, Any], limit: Optional[int] = None) -> list:
    """
    過濾已同意的聯護人 + 排序 by priority。
    limit=None 表示不限數。
    """
    contacts = profile.get("contacts") or []
    consented = [
        c for c in contacts
        if c.get("consent_status") == "accepted" and c.get("line_id")
    ]
    consented.sort(key=lambda c: int(c.get("priority") or 9999))
    if limit is not None:
        return consented[:limit]
    return consented


def get_active_guardian_groups(state: Dict[str, Any], profile: Dict[str, Any]) -> list:
    """
    取用戶所有 active 守護群。
    回傳 [{"group_id": ..., "name": ...}, ...]
    """
    owner_id = profile.get("line_user_id")
    if not owner_id:
        return []
    group_ids = profile.get("guardian_group_ids") or []
    groups = state.get("guardian_groups", {})
    result = []
    for gid in group_ids:
        g = groups.get(gid, {})
        if g.get("owner_line_user_id") == owner_id and g.get("status") == "active":
            result.append({"group_id": gid, "name": g.get("name", "")})
    return result


# ============================================================================
# Plan rules(簡化版,避免依賴 app.py)
# ============================================================================

PLAN_LIMITS_FALLBACK = {
    "free":                {"contact_limit": 1,  "core_guardian_alert_limit": 1, "channels": ["line"],         "guardian_group_limit": 0},
    "trial":               {"contact_limit": 1,  "core_guardian_alert_limit": 1, "channels": ["line"],         "guardian_group_limit": 0},
    "paid_199":            {"contact_limit": 4,  "core_guardian_alert_limit": 3, "channels": ["line"],         "guardian_group_limit": 0},
    "paid_199_year":       {"contact_limit": 6,  "core_guardian_alert_limit": 3, "channels": ["line"],         "guardian_group_limit": 0},
    "paid_399":            {"contact_limit": 15, "core_guardian_alert_limit": 3, "channels": ["line"],         "guardian_group_limit": 0},
    "paid_399_year":       {"contact_limit": 20, "core_guardian_alert_limit": 3, "channels": ["line"],         "guardian_group_limit": 0},
    "paid_799":            {"contact_limit": 25, "core_guardian_alert_limit": 3, "channels": ["line", "sms"],   "guardian_group_limit": 0},
    "paid_799_year":       {"contact_limit": 50, "core_guardian_alert_limit": 5, "channels": ["line", "sms"],   "guardian_group_limit": 3},
}


def plan_rules(profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    從 profile.plan 取對應 PLAN_LIMITS。
    若 plan 沒對應 → fallback "trial"。
    這是 app.py.plan_rules 的精簡版,只取 alerts 模組需要的欄位。
    """
    plan = profile.get("plan") or "trial"
    return PLAN_LIMITS_FALLBACK.get(plan, PLAN_LIMITS_FALLBACK["trial"])


def paid_membership_is_active(profile: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    """檢查 paid_until 仍在有效期(對應 app.paid_membership_is_active)"""
    if profile.get("payment_status") != "active":
        return False
    paid_until = parse_datetime(profile.get("paid_until"))
    if not paid_until:
        return False
    n = now or now_local()
    return paid_until > n


def is_guardian_group_eligible(
    profile: Dict[str, Any],
    rules: Dict[str, Any],
    now: Optional[datetime] = None,
) -> bool:
    """
    守護群資格檢查(對應 v0.4 §10.9):
    - 用戶主動開啟通知
    - plan 有 guardian_group_limit
    - plan 是 paid_799_year
    - 年費仍在有效期
    """
    if not profile.get("guardian_group_notification_enabled", True):
        return False
    if int(rules.get("guardian_group_limit", 0)) <= 0:
        return False
    if profile.get("plan") != "paid_799_year":
        return False
    if not paid_membership_is_active(profile, now):
        return False
    return True


# ============================================================================
# 日誌(寫進 state,不額外存檔)
# ============================================================================

def append_log(state: Dict[str, Any], kind: str, payload: Dict[str, Any]) -> None:
    """
    寫一筆 alert 相關 log 到 state["alert_logs"]。
    用於事後 audit / debug,不上 production analytics。
    """
    log = state.setdefault("alert_logs", [])
    log.append({
        "at": now_iso(),
        "kind": kind,  # "alert_created" / "wave_sent" / "alert_confirmed" / "alert_cancelled" / ...
        **payload,
    })
    # 只保留最近 1000 筆,避免 state.json 膨脹
    state["alert_logs"] = log[-1000:]


def append_line_push(state: Dict[str, Any], target_id: str, message_id: str, kind: str) -> None:
    """記錄 LINE Push 用量(配合 v0.4 LINE Push 配額)"""
    log = state.setdefault("line_push_log", [])
    log.append({
        "at": now_iso(),
        "kind": kind,
        "target_id": target_id,
        "message_id": message_id,
    })
    state["line_push_log"] = log[-1000:]


def append_sms_log(state: Dict[str, Any], user_id: str, phone: str, content_hash: str,
                   cost: float, status: str, reason: Optional[str] = None,
                   trace_id: Optional[str] = None) -> None:
    """對應 SMS spec v0.1 的 outbound_sms_log"""
    log = state.setdefault("outbound_sms_log", [])
    log.append({
        "at": now_iso(),
        "user_id": user_id,
        "phone": phone,
        "content_hash": content_hash,
        "cost_ntd": cost,
        "status": status,
        "reason": reason,
        "trace_id": trace_id or uuid.uuid4().hex,
    })
    state["outbound_sms_log"] = log[-1000:]


# ============================================================================
# 重複簽到防護(P0 決策 - v0.5)
# ============================================================================

def check_in_idempotency(
    state: Dict[str, Any],
    user_id: str,
    date_str: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Server 端 idempotency check:同一天 (user_id, date_taipei) 只能簽到一次。

    為什麼要這個:
    - iOS Safari + LINE WebView 按鈕延遲,用戶連點 3 次 → 3 筆簽到 → 額度扣 3 次
    - 用戶手機網路慢,按鈕卡住,連點 5 次 → 5 筆重複
    - 自動重整頁面 → 重複觸發
    - 前端 disabled 按鈕會被繞過(改 HTML / 直接打 API)

    Returns:
        {
            "is_duplicate": bool,
            "existing_check_in": {簽到紀錄} or None,
            "today_str": "YYYY-MM-DD",
            "should_record": bool,  # True = 可以寫;False = 不要寫
        }

    使用方式(app.py 改寫):
        from alerts.utils import check_in_idempotency

        result = check_in_idempotency(state, line_user_id)
        if result["should_record"]:
            # 寫簽到紀錄
            ...
        else:
            # 重複,回覆用戶「今日已簽到」
            return "您今天已簽到,不需要重複"
    """
    from typing import Any as _Any

    today = date_str or today_string()
    check_ins = state.setdefault("check_ins", [])

    # 找今天這位用戶的簽到紀錄
    existing = None
    for ci in check_ins:
        if (ci.get("user_id") == user_id
                and ci.get("date") == today):
            existing = ci
            break

    return {
        "is_duplicate": existing is not None,
        "existing_check_in": existing,
        "today_str": today,
        "should_record": existing is None,
    }


def record_check_in(
    state: Dict[str, Any],
    user_id: str,
    method: str = "liff_button",
    trace_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    寫一筆簽到紀錄(搭配 check_in_idempotency 使用)。

    Returns:
        {"ok": True/False, "duplicate": bool, "record": {...}}

    注意:
    - 若 (user_id, date_taipei) 已存在 → 拒絕寫入,回 duplicate=True
    - 寫入後會 append_log
    - 真實的 unique constraint 應在 DB 層做(JSON 階段僅做邏輯檢查)
    """
    idem = check_in_idempotency(state, user_id)
    if idem["is_duplicate"]:
        append_log(state, "check_in_blocked_duplicate", {
            "user_id": user_id,
            "today": idem["today_str"],
            "existing_at": (idem["existing_check_in"] or {}).get("at"),
            "trace_id": trace_id,
            "idempotency_key": idempotency_key,
        })
        return {
            "ok": False,
            "duplicate": True,
            "record": idem["existing_check_in"],
        }

    record = {
        "user_id": user_id,
        "date": idem["today_str"],
        "at": now_iso(),
        "method": method,
        "trace_id": trace_id,
        "idempotency_key": idempotency_key or uuid.uuid4().hex,
    }
    state.setdefault("check_ins", []).append(record)

    append_log(state, "check_in_recorded", {
        "user_id": user_id,
        "date": idem["today_str"],
        "method": method,
    })
    return {
        "ok": True,
        "duplicate": False,
        "record": record,
    }