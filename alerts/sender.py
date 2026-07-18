"""
alerts/sender.py — 統一發送介面

負責對外發送:LINE Push、SMS(kotsms)、守護群 Flex Message、Admin Alert。
所有發送動作走這層,失聯預警邏輯層(core.py)不直接呼叫 LINE API / kotsms API。

設計:
- Dependency Injection:外部傳入 LINE headers / kotsms client / state io
- 不耦合 app.py 的全域變數或 config
- 發送結果寫進 state.outbound_sms_log + state.line_push_log(供 audit)
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .kotsms_client import KotsmsClient, SendResult
from .messages import (
    build_admin_alert_text,
    build_alert_flex,
    build_alert_group_flex,
    build_alert_group_text,
    build_alert_text,
    build_user_ok_text,
)
from .utils import append_line_push, append_log, append_sms_log, now_iso


# ============================================================================
# 結果資料結構
# ============================================================================

@dataclass
class DeliveryResult:
    """單筆訊息發送結果(給上層判斷是否要 fallback / retry)"""
    channel: str            # "line_individual" | "line_group" | "sms" | "admin_line" | "admin_email"
    target_id: str          # line_user_id / phone / group_id / email
    success: bool
    error: Optional[str] = None
    cost_ntd: float = 0.0
    message_id: Optional[str] = None  # LINE message_id 或 SMS dstmsgid


# ============================================================================
# LINE Push(個人 + 守護群 + Admin)
# ============================================================================

def send_line_push_individual(
    state: Dict[str, Any],
    line_user_id: str,
    flex_message: Dict[str, Any],
    alert_id: str,
    wave_number: int,
    line_headers: Dict[str, str],
    line_push_url: str = "https://api.line.me/v2/bot/message/push",
    timeout_sec: int = 10,
) -> DeliveryResult:
    """
    對單一 LINE user 推播 Flex Message。
    
    line_headers:從外面注入的 {"Authorization": "Bearer xxx", "Content-Type": "application/json"}
    """
    import requests  # 延遲 import,避免 unit test 不需要 requests

    body = {
        "to": line_user_id,
        "messages": [flex_message],
    }
    try:
        resp = requests.post(
            line_push_url,
            headers=line_headers,
            json=body,
            timeout=timeout_sec,
        )
        resp.raise_for_status()
        message_id = (resp.json() or {}).get("sentMessages", [{}])[0].get("id") if resp.text else None
        append_line_push(
            state,
            target_id=line_user_id,
            message_id=message_id or uuid.uuid4().hex,
            kind=f"alert_wave{wave_number}_individual",
        )
        return DeliveryResult(
            channel="line_individual",
            target_id=line_user_id,
            success=True,
            message_id=message_id,
        )
    except Exception as e:
        append_log(state, "line_push_failed", {
            "alert_id": alert_id,
            "wave": wave_number,
            "target": line_user_id,
            "error": str(e),
        })
        return DeliveryResult(
            channel="line_individual",
            target_id=line_user_id,
            success=False,
            error=str(e),
        )


def send_line_push_group(
    state: Dict[str, Any],
    group_id: str,
    flex_message: Dict[str, Any],
    alert_id: str,
    wave_number: int,
    line_headers: Dict[str, str],
    line_push_url: str = "https://api.line.me/v2/bot/message/push",
    timeout_sec: int = 10,
) -> DeliveryResult:
    """對守護群推播。"""
    return send_line_push_individual(
        state=state,
        line_user_id=group_id,
        flex_message=flex_message,
        alert_id=alert_id,
        wave_number=wave_number,
        line_headers=line_headers,
        line_push_url=line_push_url,
        timeout_sec=timeout_sec,
    )


def send_admin_alert_line(
    state: Dict[str, Any],
    admin_line_user_id: str,
    alert: Dict[str, Any],
    line_headers: Dict[str, str],
    line_push_url: str = "https://api.line.me/v2/bot/message/push",
) -> DeliveryResult:
    """Wave 3 給管理員的 LINE 告警。"""
    text = build_admin_alert_text(alert)
    return send_line_push_individual(
        state=state,
        line_user_id=admin_line_user_id,
        flex_message={"type": "text", "text": text},
        alert_id=alert.get("alert_id", ""),
        wave_number=3,
        line_headers=line_headers,
        line_push_url=line_push_url,
    )


def send_admin_alert_email(
    state: Dict[str, Any],
    admin_email: str,
    alert: Dict[str, Any],
    smtp_config: Dict[str, Any],
) -> DeliveryResult:
    """
    Wave 3 給管理員的 Email 告警。
    
    smtp_config = {
        "host": "smtp.gmail.com",
        "port": 587,
        "username": "...",
        "password": "...",
        "use_tls": True,
    }
    """
    import smtplib
    from email.mime.text import MIMEText

    text = build_admin_alert_text(alert)
    subject = f"[alive_checkin] Wave 3 失聯預警 - {alert.get('display_name', '用戶')}"
    msg = MIMEText(text, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = smtp_config.get("username", "")
    msg["To"] = admin_email

    try:
        host = smtp_config["host"]
        port = int(smtp_config.get("port", 587))
        use_tls = bool(smtp_config.get("use_tls", True))
        with smtplib.SMTP(host, port, timeout=10) as server:
            if use_tls:
                server.starttls()
            server.login(smtp_config["username"], smtp_config["password"])
            server.sendmail(msg["From"], [admin_email], msg.as_string())
        append_log(state, "admin_email_sent", {"alert_id": alert.get("alert_id")})
        return DeliveryResult(channel="admin_email", target_id=admin_email, success=True)
    except Exception as e:
        append_log(state, "admin_email_failed", {
            "alert_id": alert.get("alert_id"),
            "error": str(e),
        })
        return DeliveryResult(
            channel="admin_email",
            target_id=admin_email,
            success=False,
            error=str(e),
        )


# ============================================================================
# SMS(Kotsms)
# ============================================================================

def send_sms_to_contact(
    state: Dict[str, Any],
    user_id: str,
    contact_phone: str,
    wave_number: int,
    alert_id: str,
    kotsms: KotsmsClient,
    cost_per_sms_ntd: float = 0.85,
) -> DeliveryResult:
    """
    透過 kotsms 發送 SMS 給緊急聯絡人。
    
    cost_per_sms_ntd:每則簡訊成本,記錄到 outbound_sms_log 供月底對帳。
    """
    text = build_alert_text(wave_number, display_name="您的親友")

    result: SendResult = kotsms.send_sms(contact_phone, text)

    # 寫進 outbound_sms_log(配合 SMS spec v0.1)
    append_sms_log(
        state,
        user_id=user_id,
        phone=contact_phone,
        content_hash=hash(text),
        cost=cost_per_sms_ntd if result.success else 0.0,
        status="sent" if result.success else "failed",
        reason=result.error_message,
        trace_id=alert_id,
    )

    return DeliveryResult(
        channel="sms",
        target_id=contact_phone,
        success=result.success,
        error=result.error_message,
        cost_ntd=cost_per_sms_ntd if result.success else 0.0,
        message_id=result.message_id,
    )


# ============================================================================
# 高階:發送整個 Wave
# ============================================================================

def send_wave_to_contacts(
    state: Dict[str, Any],
    alert: Dict[str, Any],
    contacts: List[Dict[str, Any]],
    wave_number: int,
    channels: List[str],
    line_headers: Dict[str, str],
    kotsms: Optional[KotsmsClient] = None,
    guardian_groups: Optional[List[Dict[str, Any]]] = None,
) -> List[DeliveryResult]:
    """
    發送一整個 Wave。
    
    Args:
        alert:從 state["alerts"][alert_id]
        contacts:已過濾+排序的核心聯絡人清單
        wave_number:1 / 2 / 3
        channels:每個聯絡人要用的 channels list(["line", "sms"])
        guardian_groups:守護群 list(僅 paid_799_year 才會有)
    
    Returns:
        List[DeliveryResult]
    """
    results: List[DeliveryResult] = []
    display_name = alert.get("display_name", "您的親友")
    alert_id = alert.get("alert_id", "")
    user_id = alert.get("line_user_id", "")

    # 1. 個人 LINE + SMS
    for contact in contacts:
        line_id = contact.get("line_id")
        phone = contact.get("phone")
        contact_name = contact.get("name", "")

        if "line" in channels and line_id:
            flex = build_alert_flex(wave_number, display_name, alert_id, source="individual")
            r = send_line_push_individual(
                state=state,
                line_user_id=line_id,
                flex_message=flex,
                alert_id=alert_id,
                wave_number=wave_number,
                line_headers=line_headers,
            )
            results.append(r)

        if "sms" in channels and phone and kotsms is not None:
            r = send_sms_to_contact(
                state=state,
                user_id=user_id,
                contact_phone=phone,
                wave_number=wave_number,
                alert_id=alert_id,
                kotsms=kotsms,
            )
            results.append(r)

    # 2. 守護群(若有)
    if guardian_groups and "line" in channels:
        for g in guardian_groups:
            gid = g.get("group_id")
            if not gid:
                continue
            flex = build_alert_group_flex(wave_number, display_name, alert_id)
            r = send_line_push_group(
                state=state,
                group_id=gid,
                flex_message=flex,
                alert_id=alert_id,
                wave_number=wave_number,
                line_headers=line_headers,
            )
            results.append(r)

    append_log(state, "wave_dispatched", {
        "alert_id": alert_id,
        "wave": wave_number,
        "results_count": len(results),
        "success_count": sum(1 for r in results if r.success),
    })
    return results


# ============================================================================
# 已平安通知
# ============================================================================

def send_user_ok_notifications(
    state: Dict[str, Any],
    alert: Dict[str, Any],
    line_headers: Dict[str, str],
    kotsms: Optional[KotsmsClient] = None,
) -> List[DeliveryResult]:
    """
    用戶補簽到 → 通知守護人「已平安」。
    對先前收到 Wave 1/2/3 的所有聯絡人都發一份「已平安」訊息。
    """
    results: List[DeliveryResult] = []
    display_name = alert.get("display_name", "您的親友")
    alert_id = alert.get("alert_id", "")

    # 從 alert.contacts_notified 拿先前已通知的人
    notified = alert.get("contacts_notified") or []
    text = build_user_ok_text(display_name)
    flex = {
        "type": "flex",
        "altText": "已平安通知",
        "contents": {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [{"type": "text", "text": text, "wrap": True, "size": "sm"}],
            },
        },
    }

    for entry in notified:
        line_id = entry.get("line_id")
        phone = entry.get("phone")
        if line_id:
            r = send_line_push_individual(
                state=state,
                line_user_id=line_id,
                flex_message=flex,
                alert_id=alert_id,
                wave_number=0,  # 0 = 已平安
                line_headers=line_headers,
            )
            results.append(r)
        if phone and kotsms is not None:
            result = kotsms.send_sms(phone, text)
            append_sms_log(
                state, user_id=alert.get("line_user_id", ""),
                phone=phone, content_hash=hash(text),
                cost=0.85 if result.success else 0.0,
                status="sent" if result.success else "failed",
                reason=result.error_message, trace_id=alert_id,
            )

    append_log(state, "user_ok_notified", {
        "alert_id": alert_id,
        "notified_count": len(results),
    })
    return results