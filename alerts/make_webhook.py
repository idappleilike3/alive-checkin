"""
alerts/make_webhook.py — Python 端接收 MAKE webhook

用途:
- Python cron 每天跑,判斷誰要月費到期、Email 寄失敗
- Python 呼叫 MAKE webhook(POST)
- MAKE 用 HTTP module 打 kotsms API 發 SMS
- 本檔:展示 Python 怎麼 call MAKE webhook

⚠️ 注意:這是「Python → MAKE → kotsms」的非緊急路徑
失聯預警不走這條(走 alerts.core.process_alert_waves)
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger("alerts.make_webhook")

# 從 .env 讀 MAKE webhook URL
# 您在 MAKE 建好 webhook scenario 後,把 URL 填進 .env
# 範例:MAKE_SMS_WEBHOOK_URL=https://hook.us1.make.com/abc123xyz
MAKE_SMS_WEBHOOK_URL = os.environ.get("MAKE_SMS_WEBHOOK_URL", "")


def trigger_make_sms(
    user_id: str,
    phone: str,
    message: str,
    reason: str = "reminder",
    timeout_sec: int = 10,
) -> Dict[str, Any]:
    """
    觸發 MAKE webhook 發 SMS。

    Args:
        user_id: 用戶的 line_user_id
        phone: 09xxxxxxxx 格式手機號碼
        message: SMS 內容(≤ 70 中文字)
        reason: 用途標記("reminder" / "verification" / "marketing")

    Returns:
        {"ok": bool, "trace_id": str, "error": str or None}
    """
    if not MAKE_SMS_WEBHOOK_URL:
        return {"ok": False, "trace_id": "", "error": "MAKE_SMS_WEBHOOK_URL not set"}

    trace_id = uuid.uuid4().hex[:12]
    payload = {
        "trace_id": trace_id,
        "user_id": user_id,
        "phone": phone,
        "message": message,
        "reason": reason,
    }

    try:
        resp = requests.post(
            MAKE_SMS_WEBHOOK_URL,
            json=payload,
            timeout=timeout_sec,
        )
        resp.raise_for_status()
        logger.info(
            f"MAKE webhook ok trace_id={trace_id} user={user_id} "
            f"status={resp.status_code}"
        )
        return {
            "ok": True,
            "trace_id": trace_id,
            "error": None,
            "status_code": resp.status_code,
        }
    except requests.RequestException as e:
        logger.error(
            f"MAKE webhook failed trace_id={trace_id} user={user_id} err={e}"
        )
        return {
            "ok": False,
            "trace_id": trace_id,
            "error": str(e),
        }


# ============================================================================
# 範例:cron job 用法(整合到您現有的 send_due_reminders)
# ============================================================================

def send_due_reminder_via_make(state: Dict[str, Any]) -> Dict[str, int]:
    """
    把現有 send_due_reminders 改成走 MAKE。

    使用方式(在 app.py 裡):
        from alerts.make_webhook import send_due_reminder_via_make
        result = send_due_reminder_via_make(state)
        # result = {"sent": 5, "failed": 0}
    """
    from .utils import get_profile, append_log

    sent = 0
    failed = 0
    today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")

    # 假設 state["users"] 是 dict,每個用戶有 "phone" 和 "reminder_message"
    for uid, profile in state.get("users", {}).items():
        phone = profile.get("phone")
        message = profile.get("reminder_message")
        if not phone or not message:
            continue

        result = trigger_make_sms(
            user_id=uid,
            phone=phone,
            message=message,
            reason="reminder",
        )
        if result["ok"]:
            sent += 1
        else:
            failed += 1

        append_log(state, "make_sms_triggered", {
            "user_id": uid,
            "trace_id": result["trace_id"],
            "ok": result["ok"],
        })

    return {"sent": sent, "failed": failed}