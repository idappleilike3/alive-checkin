"""SOS 求救流程(2026-07-21 patch 20)。

設計:
- 3 次確認防誤觸(stage 1 / 2 / 3)
- 確認後進入 10 分鐘取消期
- cron 每分鐘掃一次,過期自動發送
- 用戶可手動取消

state 結構:
    state["sos_pending"][user_id] = {
        "stage": "pending",      # pending / confirmed / sent / cancelled
        "scheduled_at": iso8601,  # 確認完進入的時間
        "expires_at": iso8601,    # 10 分鐘後
        "contacts_snapshot": [...],
        "guardian_groups_snapshot": [...],
    }
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


GREEN_DARK = "#00B900"
GREEN_SOFT = "#E8F8EE"
GRAY = "#555555"
GRAY_LIGHT = "#888888"
ORANGE = "#E08E00"
RED = "#D6322C"
RED_SOFT = "#FDECEA"

SOS_CANCEL_WINDOW_MIN = 10  # 確認後 10 分鐘可取消
SOS_REMINDER_AT_MIN = 5  # 過 5 分鐘提醒一次


# ────────────────────────────────────────────────────────────
# Flex Message 構建器
# ────────────────────────────────────────────────────────────

def sos_stage_1_flex():
    """第 1 次確認:再按一次確認繼續。"""
    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": ORANGE,
            "paddingTop": "lg",
            "paddingBottom": "lg",
            "paddingStart": "lg",
            "paddingEnd": "lg",
            "contents": [
                {
                    "type": "text",
                    "text": "🚨 SOS 求救 (1/3)",
                    "color": "#FFFFFF",
                    "size": "xxl",
                    "weight": "bold",
                    "align": "center",
                },
                {
                    "type": "text",
                    "text": "你按了求救按鈕",
                    "color": "#FFFFFF",
                    "size": "md",
                    "align": "center",
                    "margin": "sm",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "paddingAll": "lg",
            "contents": [
                {
                    "type": "text",
                    "text": "再按一次「確認繼續」才會進入下一步",
                    "size": "md",
                    "color": GRAY,
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": "⚠️ 確認到底的話,會通知所有守護人並傳 SMS",
                    "size": "md",
                    "color": ORANGE,
                    "wrap": True,
                },
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "paddingAll": "md",
            "backgroundColor": "#FAFAFA",
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "message",
                        "label": "確認繼續 (1/3)",
                        "text": "SOS 確認 2",
                    },
                    "style": "primary",
                    "color": ORANGE,
                    "height": "md",
                },
                {
                    "type": "button",
                    "action": {
                        "type": "message",
                        "label": "❌ 取消",
                        "text": "SOS 取消",
                    },
                    "style": "link",
                    "color": GRAY,
                    "height": "sm",
                },
            ],
        },
    }


def sos_stage_2_flex():
    """第 2 次確認:再次確認。"""
    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": RED,
            "paddingTop": "lg",
            "paddingBottom": "lg",
            "paddingStart": "lg",
            "paddingEnd": "lg",
            "contents": [
                {
                    "type": "text",
                    "text": "🚨 SOS 求救 (2/3)",
                    "color": "#FFFFFF",
                    "size": "xxl",
                    "weight": "bold",
                    "align": "center",
                },
                {
                    "type": "text",
                    "text": "真的要發送求救嗎?",
                    "color": "#FFFFFF",
                    "size": "md",
                    "align": "center",
                    "margin": "sm",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "paddingAll": "lg",
            "contents": [
                {
                    "type": "text",
                    "text": "⚠️ 按下「真的要送出」就會進入 10 分鐘取消期",
                    "size": "lg",
                    "weight": "bold",
                    "color": RED,
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": "• 通知所有守護人(LINE)\n• 傳 SMS 給緊急聯絡人\n• 在守護群發出求救訊息",
                    "size": "md",
                    "color": GRAY,
                    "wrap": True,
                },
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "paddingAll": "md",
            "backgroundColor": "#FAFAFA",
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "message",
                        "label": "真的要送出 (2/3)",
                        "text": "SOS 確認 3",
                    },
                    "style": "primary",
                    "color": RED,
                    "height": "md",
                },
                {
                    "type": "button",
                    "action": {
                        "type": "message",
                        "label": "❌ 取消",
                        "text": "SOS 取消",
                    },
                    "style": "link",
                    "color": GRAY,
                    "height": "sm",
                },
            ],
        },
    }


def sos_stage_3_flex(plan_label: str, contacts_count: int, guardian_groups_count: int, cancel_min: int = SOS_CANCEL_WINDOW_MIN):
    """第 3 次確認:進入 10 分鐘取消期。"""
    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": RED,
            "paddingTop": "lg",
            "paddingBottom": "lg",
            "paddingStart": "lg",
            "paddingEnd": "lg",
            "contents": [
                {
                    "type": "text",
                    "text": "🚨 SOS 預備發送 (3/3)",
                    "color": "#FFFFFF",
                    "size": "xxl",
                    "weight": "bold",
                    "align": "center",
                },
                {
                    "type": "text",
                    "text": f"{cancel_min} 分鐘後自動發送,可取消",
                    "color": "#FFFFFF",
                    "size": "md",
                    "align": "center",
                    "margin": "sm",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "paddingAll": "lg",
            "contents": [
                {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "xs",
                    "backgroundColor": RED_SOFT,
                    "cornerRadius": "md",
                    "paddingAll": "md",
                    "contents": [
                        {
                            "type": "text",
                            "text": "📡 即將通知",
                            "size": "lg",
                            "weight": "bold",
                            "color": RED,
                        },
                        {
                            "type": "text",
                            "text": f"• 你目前的方案:{plan_label}\n• {contacts_count} 位緊急聯絡人(LINE + SMS)\n• {guardian_groups_count} 個守護群",
                            "size": "md",
                            "color": GRAY,
                            "wrap": True,
                        },
                    ],
                },
                {
                    "type": "text",
                    "text": f"⏰ {cancel_min} 分鐘內可按「取消 SOS 預約」撤銷",
                    "size": "md",
                    "color": ORANGE,
                    "wrap": True,
                },
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "paddingAll": "md",
            "backgroundColor": "#FAFAFA",
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "message",
                        "label": f"❌ 取消 SOS 預約 ({cancel_min} 分鐘內可取消)",
                        "text": "SOS 取消",
                    },
                    "style": "link",
                    "color": RED,
                    "height": "md",
                },
            ],
        },
    }


def sos_reminder_flex(remaining_min: int):
    """5 分鐘提醒:SOS 即將在 X 分鐘後送出。"""
    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": ORANGE,
            "paddingTop": "lg",
            "paddingBottom": "lg",
            "paddingStart": "lg",
            "paddingEnd": "lg",
            "contents": [
                {
                    "type": "text",
                    "text": "⏰ SOS 即將送出",
                    "color": "#FFFFFF",
                    "size": "xxl",
                    "weight": "bold",
                    "align": "center",
                },
                {
                    "type": "text",
                    "text": f"還剩 {remaining_min} 分鐘",
                    "color": "#FFFFFF",
                    "size": "md",
                    "align": "center",
                    "margin": "sm",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "paddingAll": "lg",
            "contents": [
                {
                    "type": "text",
                    "text": "這是真的要發送嗎?如誤觸請立即取消",
                    "size": "lg",
                    "color": ORANGE,
                    "weight": "bold",
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": "⚠️ 119 仍是最快的求助方式",
                    "size": "md",
                    "color": GRAY,
                    "wrap": True,
                },
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "paddingAll": "md",
            "backgroundColor": "#FAFAFA",
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "message",
                        "label": "❌ 取消 SOS 預約",
                        "text": "SOS 取消",
                    },
                    "style": "primary",
                    "color": RED,
                    "height": "md",
                },
            ],
        },
    }


def sos_cancelled_flex():
    """SOS 已取消。"""
    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": GRAY,
            "paddingTop": "lg",
            "paddingBottom": "lg",
            "paddingStart": "lg",
            "paddingEnd": "lg",
            "contents": [
                {
                    "type": "text",
                    "text": "✅ SOS 已取消",
                    "color": "#FFFFFF",
                    "size": "xxl",
                    "weight": "bold",
                    "align": "center",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "paddingAll": "lg",
            "contents": [
                {
                    "type": "text",
                    "text": "求救訊息沒有發送出去,守護人沒有被通知",
                    "size": "md",
                    "color": GRAY,
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": "⚠️ 如果是真的緊急狀況,請直接撥打 119",
                    "size": "md",
                    "color": ORANGE,
                    "wrap": True,
                },
            ],
        },
    }


def sos_sent_flex():
    """SOS 已實際發送。"""
    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": RED,
            "paddingTop": "lg",
            "paddingBottom": "lg",
            "paddingStart": "lg",
            "paddingEnd": "lg",
            "contents": [
                {
                    "type": "text",
                    "text": "🚨 SOS 已發送",
                    "color": "#FFFFFF",
                    "size": "xxl",
                    "weight": "bold",
                    "align": "center",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "paddingAll": "lg",
            "contents": [
                {
                    "type": "text",
                    "text": "已通知所有守護人 + SMS + 守護群",
                    "size": "lg",
                    "color": RED,
                    "weight": "bold",
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": "守護人收到訊息後會盡快聯絡你或派人協助",
                    "size": "md",
                    "color": GRAY,
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": "⚠️ 緊急狀況請同步撥打 119",
                    "size": "md",
                    "color": ORANGE,
                    "wrap": True,
                },
            ],
        },
    }


# ────────────────────────────────────────────────────────────
# State 管理
# ────────────────────────────────────────────────────────────

def sos_get_pending(state, user_id):
    return (state.get("sos_pending") or {}).get(user_id)


def sos_create_pending(state, user_id, contacts_snapshot, guardian_groups_snapshot, plan_label):
    """建立 SOS 預約(stage 3 已確認),計時 10 分鐘。"""
    pending = state.setdefault("sos_pending", {})
    now = datetime.now()
    pending[user_id] = {
        "stage": "confirmed",
        "scheduled_at": now.isoformat(timespec="seconds"),
        "expires_at": (now + timedelta(minutes=SOS_CANCEL_WINDOW_MIN)).isoformat(timespec="seconds"),
        "reminded_at": None,  # 5 min reminder
        "contacts_count": len(contacts_snapshot or []),
        "guardian_groups_count": len(guardian_groups_snapshot or []),
        "plan_label": plan_label,
        "created_at": now.isoformat(timespec="seconds"),
    }
    return pending[user_id]


def sos_cancel_pending(state, user_id):
    pending = state.setdefault("sos_pending", {})
    if user_id in pending:
        pending[user_id]["stage"] = "cancelled"
        pending[user_id]["cancelled_at"] = datetime.now().isoformat(timespec="seconds")
        return True
    return False


def sos_mark_sent(state, user_id, event_id):
    """cron 標記 SOS 已實際送出。"""
    pending = state.setdefault("sos_pending", {})
    if user_id in pending:
        pending[user_id]["stage"] = "sent"
        pending[user_id]["sent_at"] = datetime.now().isoformat(timespec="seconds")
        pending[user_id]["event_id"] = event_id
        return True
    return False


def sos_purge_old(state, keep_minutes: int = 60):
    """清理超過 keep_minutes 的紀錄(已 sent / cancelled)。"""
    pending = state.get("sos_pending") or {}
    now = datetime.now()
    cutoff = now - timedelta(minutes=keep_minutes)
    removed = []
    for uid, entry in list(pending.items()):
        ts_str = entry.get("sent_at") or entry.get("cancelled_at") or entry.get("expires_at")
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str)
            if ts < cutoff:
                del pending[uid]
                removed.append(uid)
        except Exception:
            continue
    return removed


def sos_get_expirable(state, now=None):
    """找出所有 stage=confirmed 且已過 expires_at 的 SOS。"""
    now = now or datetime.now()
    pending = state.get("sos_pending") or {}
    out = []
    for uid, entry in pending.items():
        if entry.get("stage") != "confirmed":
            continue
        expires = entry.get("expires_at")
        if not expires:
            continue
        try:
            if datetime.fromisoformat(expires) <= now:
                out.append((uid, entry))
        except Exception:
            continue
    return out


def sos_get_remindable(state, now=None):
    """找出 stage=confirmed,還沒提醒過,且 scheduled_at 超過 5 分鐘的。"""
    now = now or datetime.now()
    pending = state.get("sos_pending") or {}
    out = []
    for uid, entry in pending.items():
        if entry.get("stage") != "confirmed":
            continue
        if entry.get("reminded_at"):
            continue
        scheduled = entry.get("scheduled_at")
        if not scheduled:
            continue
        try:
            sched_dt = datetime.fromisoformat(scheduled)
            if now - sched_dt >= timedelta(minutes=SOS_REMINDER_AT_MIN):
                out.append((uid, entry))
        except Exception:
            continue
    return out