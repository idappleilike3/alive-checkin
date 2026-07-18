"""
alerts/core.py — 失聯預警核心邏輯

對應 Code change map v0.4:
- §2 失聯預警「重試 + 升級」閉環
- §10 守護群整合

公開 API:
    - create_missing_person_alert():建立失聯預警
    - confirm_alert():守護人按 postback「我會去聯絡他」
    - cancel_pending_alerts():用戶補簽到 → 取消未發送的 wave
    - process_alert_waves():cron job 觸發,發送 T+X 的 wave
    - is_alert_active():檢查用戶是否已有 active alert

依賴注入:外部傳入 line_headers / kotsms client / data_file
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .kotsms_client import KotsmsClient
from .messages import build_alert_flex, build_alert_group_flex
from .models import AlertStatus, AlertTrigger, ChannelName, WaveNumber
from .sender import (
    send_admin_alert_email,
    send_admin_alert_line,
    send_wave_to_contacts,
)
from .utils import (
    append_log,
    get_active_guardian_groups,
    get_consented_contacts,
    is_guardian_group_eligible,
    minutes_between,
    new_alert_id,
    now_iso,
    now_local,
    paid_membership_is_active,
    plan_rules,
)


# ============================================================================
# 設定常數(從外面傳入或從 .env 讀)
# ============================================================================

DEFAULT_ALERT_CONFIG = {
    "wave_2_delay_minutes": 15,
    "wave_3_delay_minutes": 30,
    "admin_line_user_id": "",     # .env: ADMIN_LINE_USER_ID
    "admin_email": "",             # .env: ADMIN_EMAIL
    "smtp_config": {},             # .env: SMTP_HOST, SMTP_USERNAME, ...
    "active_alerts_per_user_per_day": 1,
    "alert_history_retention_days": 30,
}


# ============================================================================
# 建立失聯預警
# ============================================================================

def create_missing_person_alert(
    state: Dict[str, Any],
    user_id: str,
    trigger: AlertTrigger = "missed_checkin",
    note: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    建立失聯預警(對應 v0.4 §2.1)。
    
    Args:
        state: 整包 state dict
        user_id: 用戶的 line_user_id
        trigger: "missed_checkin" / "manual_sos"
        note: 備註(可選)
    
    Returns:
        新建的 Alert dict(寫入 state["alerts"]),若已存在 active alert 則回傳 None
    
    Side effects:
        - 寫進 state["alerts"][alert_id]
        - 寫進 state.alert_logs
    """
    # 規則 1:同時只能 1 個 active alert / 用戶 / 日(對應 v0.4 §3.1)
    existing = _find_active_alert_for_user_today(state, user_id)
    if existing is not None:
        append_log(state, "alert_create_blocked_existing", {
            "user_id": user_id,
            "existing_alert_id": existing["alert_id"],
        })
        return None

    profile = state.get("users", {}).get(user_id, {})
    if not profile:
        append_log(state, "alert_create_failed_no_profile", {"user_id": user_id})
        return None

    # 規則 2:必須有 paid membership 才發(對應 v0.4 §2.1)
    # ⚠️ 注意:這個會讓 free trial / 試用期用戶完全沒失聯預警
    # 商業決策:是否要 free trial 也享有基本預警?若要,移除此檢查
    if not paid_membership_is_active(profile):
        # 例外:已綁定守護人但 plan 過期 → 仍然發(降級為 LINE-only,不分 SMS)
        contacts = get_consented_contacts(profile)
        if not contacts:
            append_log(state, "alert_create_no_contacts", {"user_id": user_id})
            return None

    # 抓守護人 + 守護群
    rules = plan_rules(profile)
    core_contacts = get_consented_contacts(profile, limit=rules.get("core_guardian_alert_limit", 3))

    guardian_groups: List[Dict[str, Any]] = []
    if is_guardian_group_eligible(profile, rules):
        guardian_groups = get_active_guardian_groups(state, profile)

    alert_id = new_alert_id()
    now = now_iso()
    alert: Dict[str, Any] = {
        "alert_id": alert_id,
        "line_user_id": user_id,
        "display_name": profile.get("display_name", ""),
        "created_at": now,
        "updated_at": now,
        "status": "active",  # active / confirmed / cancelled / expired
        "trigger": trigger,
        "note": note,
        "profile_snapshot": {
            "plan": profile.get("plan", "trial"),
            "contact_count": len(core_contacts),
            "guardian_group_count": len(guardian_groups),
        },
        "waves": [],          # List of {wave_number, scheduled_at, sent_at, results}
        "contacts_notified": [],  # 記錄已通知對象(供「已平安」通知用)
        "confirmations": [],  # 守護人按 postback 紀錄
    }
    state.setdefault("alerts", {})[alert_id] = alert

    append_log(state, "alert_created", {
        "alert_id": alert_id,
        "user_id": user_id,
        "trigger": trigger,
        "contact_count": len(core_contacts),
        "guardian_group_count": len(guardian_groups),
    })
    return alert


def _find_active_alert_for_user_today(
    state: Dict[str, Any], user_id: str
) -> Optional[Dict[str, Any]]:
    """找今天還 active 的 alert。"""
    today = now_local().strftime("%Y-%m-%d")
    alerts = state.get("alerts", {})
    for aid, a in alerts.items():
        if a.get("line_user_id") != user_id:
            continue
        if a.get("status") != "active":
            continue
        created = a.get("created_at", "")
        if created.startswith(today):
            return a
    return None


# ============================================================================
# 守護人確認(按 postback)
# ============================================================================

def confirm_alert(
    state: Dict[str, Any],
    alert_id: str,
    confirmer_line_id: str,
    confirmer_name: str,
    confirmer_phone: Optional[str] = None,
    source: str = "individual",  # "individual" / "group"
) -> Dict[str, Any]:
    """
    守護人按「我會去聯絡他」postback 確認。
    
    效果:
        1. 標記 alert 為 confirmed
        2. 記錄 confirmer
        3. 後續 wave 不再發送(由 process_alert_waves 檢查 status 自動跳過)
    
    Returns:
        更新後的 alert dict
    """
    alert = state.get("alerts", {}).get(alert_id)
    if not alert:
        append_log(state, "alert_confirm_not_found", {"alert_id": alert_id})
        return {}

    if alert.get("status") not in ("active",):
        append_log(state, "alert_confirm_already_resolved", {
            "alert_id": alert_id,
            "current_status": alert.get("status"),
        })
        return alert

    now = now_iso()
    alert["status"] = "confirmed"
    alert["confirmed_by"] = {
        "line_id": confirmer_line_id,
        "name": confirmer_name,
        "phone": confirmer_phone,
        "source": source,
        "at": now,
    }
    alert.setdefault("confirmations", []).append({
        "line_id": confirmer_line_id,
        "name": confirmer_name,
        "source": source,
        "at": now,
    })
    alert["updated_at"] = now

    append_log(state, "alert_confirmed", {
        "alert_id": alert_id,
        "confirmer_line_id": confirmer_line_id,
        "source": source,
    })
    return alert


# ============================================================================
# 取消(用戶補簽到)
# ============================================================================

def cancel_pending_alerts(
    state: Dict[str, Any],
    user_id: str,
    reason: str = "user_checked_in",
) -> List[Dict[str, Any]]:
    """
    用戶補簽到 → 取消所有 pending 的 wave。

    ⚠️ 只取消尚未發送的 wave。已發送的 wave 無法收回(只能發「已平安」通知)。

    Returns:
        取消的 alert list
    """
    cancelled: List[Dict[str, Any]] = []
    alerts = state.get("alerts", {})
    now = now_iso()

    for aid, alert in alerts.items():
        if alert.get("line_user_id") != user_id:
            continue
        if alert.get("status") != "active":
            continue

        alert["status"] = "cancelled"
        alert["cancelled_reason"] = reason
        alert["updated_at"] = now

        # 標記未送的 wave 為 cancelled
        for wave in alert.get("waves", []):
            if wave.get("sent_at") is None:
                wave["cancelled"] = True
                wave["cancelled_reason"] = reason

        cancelled.append(alert)
        append_log(state, "alert_cancelled", {
            "alert_id": aid,
            "reason": reason,
        })

    return cancelled


# ============================================================================
# 用戶主動按「已平安,取消警報」(v0.5 P0 決策)
# ============================================================================

def cancel_alert_by_user(
    state: Dict[str, Any],
    user_id: str,
    reason: str = "user_pressed_cancel",
    source: str = "line_postback",
    note: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    用戶主動按「我已平安,請取消警報」postback(從 LINE)。

    與 cancel_pending_alerts 的差別:
    - cancel_pending_alerts: 用戶補簽到 → 自動觸發(reason=user_checked_in)
    - cancel_alert_by_user: 用戶主動按 postback → **不需要補簽到**(reason=user_pressed_cancel)

    使用情境:
    - 用戶在旅遊,不想因為沒簽到被家人狂叩
    - 用戶身體不適在睡覺,主動通知 Bot「我很好,不要發警報」
    - 用戶手機壞掉借別人手機登入按取消

    Bot 收到 postback 後:
    1. 標記 alert 為 cancelled
    2. 取消未送的 wave
    3. 主動發「已平安」通知給所有已通知的聯絡人 + 守護群
    """
    cancelled = cancel_pending_alerts(state, user_id, reason=reason)

    # 額外記錄:用戶主動按(區別於補簽到)
    for alert in cancelled:
        alert["cancelled_source"] = source
        if note:
            alert["cancelled_note"] = note

    append_log(state, "alert_cancelled_by_user", {
        "user_id": user_id,
        "cancelled_count": len(cancelled),
        "reason": reason,
        "source": source,
    })
    return cancelled


# ============================================================================
# Cron job:處理 T+X 的 wave
# ============================================================================

def process_alert_waves(
    state: Dict[str, Any],
    config: Dict[str, Any],
    line_headers: Dict[str, str],
    kotsms: Optional[KotsmsClient] = None,
    now: Optional[Any] = None,  # datetime,測試用可注入
) -> List[Dict[str, Any]]:
    """
    Cron job 主流程。應每分鐘跑一次。
    
    對每個 active alert:
        1. 計算是否到 T+0 / T+15 / T+30 的時間點
        2. 若到 → 發送該 wave
        3. 若 alert 已被 confirmed / cancelled → 跳過
    
    Returns:
        本次執行發送的 wave list(供 cron log)
    """
    from datetime import datetime as _dt

    current = now or now_local()
    cfg = {**DEFAULT_ALERT_CONFIG, **(config or {})}
    wave_2_delay = int(cfg.get("wave_2_delay_minutes", 15))
    wave_3_delay = int(cfg.get("wave_3_delay_minutes", 30))

    sent_waves: List[Dict[str, Any]] = []
    alerts = state.get("alerts", {})

    for aid, alert in alerts.items():
        if alert.get("status") != "active":
            continue

        created = alert.get("created_at")
        if not created:
            continue

        try:
            created_dt = _dt.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            continue

        elapsed_min = (current - created_dt).total_seconds() / 60.0

        # Wave 1: T+0
        if not _wave_sent(alert, 1) and elapsed_min >= 0:
            _dispatch_wave(state, alert, 1, cfg, line_headers, kotsms)
            sent_waves.append({"alert_id": aid, "wave": 1})

        # Wave 2: T+15
        elif not _wave_sent(alert, 2) and elapsed_min >= wave_2_delay:
            _dispatch_wave(state, alert, 2, cfg, line_headers, kotsms)
            sent_waves.append({"alert_id": aid, "wave": 2})

        # Wave 3: T+30
        elif not _wave_sent(alert, 3) and elapsed_min >= wave_3_delay:
            _dispatch_wave(state, alert, 3, cfg, line_headers, kotsms)
            sent_waves.append({"alert_id": aid, "wave": 3})

            # Wave 3 同時送 admin alert
            _send_admin_alerts(state, alert, cfg, line_headers)

    if sent_waves:
        append_log(state, "process_waves_run", {
            "sent_count": len(sent_waves),
            "at": now_iso(),
        })
    return sent_waves


def _wave_sent(alert: Dict[str, Any], wave_number: int) -> bool:
    return any(
        w.get("wave_number") == wave_number and w.get("sent_at")
        for w in alert.get("waves", [])
    )


def _dispatch_wave(
    state: Dict[str, Any],
    alert: Dict[str, Any],
    wave_number: int,
    cfg: Dict[str, Any],
    line_headers: Dict[str, str],
    kotsms: Optional[KotsmsClient],
) -> None:
    """實際發送單個 wave 並記錄。"""
    user_id = alert["line_user_id"]
    profile = state.get("users", {}).get(user_id, {})
    rules = plan_rules(profile)

    # 守護人數量:Wave 1/2 用 core_guardian_alert_limit,Wave 3 用 contact_limit(全推)
    if wave_number == 3:
        contacts = get_consented_contacts(profile, limit=rules.get("contact_limit", 50))
    else:
        contacts = get_consented_contacts(profile, limit=rules.get("core_guardian_alert_limit", 3))

    guardian_groups: List[Dict[str, Any]] = []
    if is_guardian_group_eligible(profile, rules):
        guardian_groups = get_active_guardian_groups(state, profile)

    # 各 wave 的 channels
    channels: List[str]
    if wave_number == 1:
        channels = ["line"]
    elif wave_number == 2:
        # 加入 SMS(若 plan 有)
        channels = ["line", "sms"] if "sms" in rules.get("channels", []) else ["line"]
    else:  # wave 3
        channels = ["line", "sms"] if "sms" in rules.get("channels", []) else ["line"]

    results = send_wave_to_contacts(
        state=state,
        alert=alert,
        contacts=contacts,
        wave_number=wave_number,
        channels=channels,
        line_headers=line_headers,
        kotsms=kotsms,
        guardian_groups=guardian_groups,
    )

    # 記錄到 alert.waves
    now = now_iso()
    alert.setdefault("waves", []).append({
        "wave_number": wave_number,
        "scheduled_at": alert["created_at"],
        "sent_at": now,
        "results_count": len(results),
        "success_count": sum(1 for r in results if r.success),
        "channels": channels,
        "contact_count": len(contacts),
        "guardian_group_count": len(guardian_groups),
    })

    # 記錄已通知對象(供「已平安」通知用)
    notified = alert.setdefault("contacts_notified", [])
    for c in contacts:
        if not any(n.get("line_id") == c.get("line_id") for n in notified):
            notified.append({
                "line_id": c.get("line_id"),
                "phone": c.get("phone"),
                "name": c.get("name"),
            })

    alert["updated_at"] = now


def _send_admin_alerts(
    state: Dict[str, Any],
    alert: Dict[str, Any],
    cfg: Dict[str, Any],
    line_headers: Dict[str, str],
) -> None:
    """Wave 3 同時送 admin alert。"""
    admin_line_id = cfg.get("admin_line_user_id")
    admin_email = cfg.get("admin_email")
    smtp = cfg.get("smtp_config") or {}

    if admin_line_id:
        send_admin_alert_line(state, admin_line_id, alert, line_headers)
    if admin_email and smtp:
        send_admin_alert_email(state, admin_email, alert, smtp)

    append_log(state, "admin_alert_sent", {"alert_id": alert["alert_id"]})


# ============================================================================
# 查詢
# ============================================================================

def is_alert_active(state: Dict[str, Any], user_id: str) -> bool:
    """檢查用戶是否已有 active alert(防止重複建立)。"""
    return _find_active_alert_for_user_today(state, user_id) is not None


def get_active_alert(state: Dict[str, Any], user_id: str) -> Optional[Dict[str, Any]]:
    return _find_active_alert_for_user_today(state, user_id)