"""SOS 求救流程(2026-07-21 patch 21)。

設計(簡化版):
- 按 3 次 SOS 才發送(連續 3 次,每次間隔 ≤ 10 秒)
- 每次按都有「取消」按鈕可中止
- 第 3 次按下去 → **立即發送**(不再等 10 分鐘)
- 發送後仍有 10 分鐘取消期(cron 提醒 + 可手動取消)

state 結構:
    state["sos_pending"][user_id] = {
        "stage": "warning_1" | "warning_2" | "warning_3" | "sent" | "cancelled",
        "tap_count": 0-3,
        "first_tap_at": iso,
        "last_tap_at": iso,
        "sent_at": iso | None,
        "event_id": str | None,
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

# 三次連按的「連續」視窗(秒)
SOS_TAP_WINDOW_SEC = 10
# 第 3 次按下去後,cron 還允許取消的時間(分)
SOS_POST_SEND_CANCEL_MIN = 10


# ────────────────────────────────────────────────────────────
# Flex Message 構建器
# ────────────────────────────────────────────────────────────

def sos_emergency_flex(family_tel: str | None = None, family_label: str | None = None, liff_sos_uri: str | None = None):
    """需要幫忙入口卡：先撥打 110/119／家人，再連按通知家人。

    人人可看、不依 799。通知家人走 message「通知家人」進入 3 連按。
    """
    dial_family_label = (family_label or "第一聯絡人")[:16]
    family_uri = f"tel:{family_tel}" if family_tel else (liff_sos_uri or "https://liff.line.me/2010674803-rK98c0lo/?open=call")
    family_btn_label = f"📞 打給{dial_family_label}" if family_tel else "📞 聯絡家人"
    panel_uri = liff_sos_uri or "https://liff.line.me/2010674803-rK98c0lo/?open=sos"

    return {
        "type": "bubble",
        "size": "mega",
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
                    "text": "🆘 需要幫忙",
                    "color": "#FFFFFF",
                    "size": "xxl",
                    "weight": "bold",
                    "align": "center",
                },
                {
                    "type": "text",
                    "text": "先打電話，必要時再通知家人",
                    "color": "#FFFFFF",
                    "size": "md",
                    "align": "center",
                    "margin": "sm",
                    "wrap": True,
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
                    "text": "有立即危險請先撥打 119 或 110。本服務不是報警系統。",
                    "size": "md",
                    "color": GRAY,
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": "若要通知家人，請點下方「通知家人」並連按 3 次確認。",
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
                    "action": {"type": "uri", "label": "撥打 119", "uri": "tel:119"},
                    "style": "primary",
                    "color": RED,
                    "height": "md",
                },
                {
                    "type": "button",
                    "action": {"type": "uri", "label": "撥打 110", "uri": "tel:110"},
                    "style": "primary",
                    "color": ORANGE,
                    "height": "md",
                },
                {
                    "type": "button",
                    "action": {"type": "uri", "label": family_btn_label[:20], "uri": family_uri},
                    "style": "secondary",
                    "color": GREEN_DARK,
                    "height": "md",
                },
                {
                    "type": "button",
                    "action": {
                        "type": "message",
                        "label": "通知家人（連按 3 次）",
                        "text": "通知家人",
                    },
                    "style": "primary",
                    "color": RED,
                    "height": "md",
                },
                {
                    "type": "button",
                    "action": {"type": "uri", "label": "開啟完整求助頁", "uri": panel_uri},
                    "style": "link",
                    "color": GRAY,
                    "height": "sm",
                },
            ],
        },
    }


def sos_warning_flex(tap_count: int, window_sec: int = SOS_TAP_WINDOW_SEC):
    """第 N 次「需要幫忙」警告:還能取消 + 再按一次確認。"""
    remaining = tap_count - 2  # 第 1 次顯示 1/3, 第 2 次顯示 2/3
    bg = ORANGE if tap_count <= 2 else RED
    title = f"🚨 需要幫忙 ({tap_count}/3)"
    subtitle = "再按一次才會發送" if tap_count <= 2 else "⚠️ 最後一次,再按就會立刻發送!"

    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": bg,
            "paddingTop": "lg",
            "paddingBottom": "lg",
            "paddingStart": "lg",
            "paddingEnd": "lg",
            "contents": [
                {
                    "type": "text",
                    "text": title,
                    "color": "#FFFFFF",
                    "size": "xxl",
                    "weight": "bold",
                    "align": "center",
                },
                {
                    "type": "text",
                    "text": subtitle,
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
                    "text": f"⏰ {window_sec} 秒內不按 = 自動取消(防止誤觸)",
                    "size": "lg",
                    "color": ORANGE,
                    "weight": "bold",
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": "⚠️ 第 3 次按下去會立刻通知所有守護人",
                    "size": "md",
                    "color": GRAY,
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": "🚨 119 永遠是最快的求助方式",
                    "size": "md",
                    "color": RED,
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
                        "label": f"再按一次 ({tap_count}/3 → {tap_count + 1 if tap_count < 3 else '發送'})",
                        "text": "通知家人",
                    },
                    "style": "primary",
                    "color": bg,
                    "height": "md",
                },
                {
                    "type": "button",
                    "action": {
                        "type": "message",
                        "label": "❌ 取消需要幫忙",
                        "text": "取消需要幫忙",
                    },
                    "style": "link",
                    "color": GRAY,
                    "height": "sm",
                },
            ],
        },
    }


def sos_cancelled_flex():
    """需要幫忙已取消(任意階段)。"""
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
                    "text": "✅ 已取消需要幫忙",
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
                    "text": "通知沒有發送出去,守護人沒有被通知",
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


def sos_sent_flex(cancel_min: int = SOS_POST_SEND_CANCEL_MIN):
    """需要幫忙已實際發送 + 10 分鐘可取消。"""
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
                    "text": "🚨 已通知家人需要幫忙",
                    "color": "#FFFFFF",
                    "size": "xxl",
                    "weight": "bold",
                    "align": "center",
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": f"{cancel_min} 分鐘內可取消",
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
                    "text": "已通知所有守護人與守護群",
                    "size": "lg",
                    "weight": "bold",
                    "color": RED,
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
                        "label": f"❌ 取消通知 ({cancel_min} 分鐘內)",
                        "text": "取消需要幫忙",
                    },
                    "style": "link",
                    "color": RED,
                    "height": "md",
                },
            ],
        },
    }


# ────────────────────────────────────────────────────────────
# State 管理
# ────────────────────────────────────────────────────────────

def sos_get_pending(state, user_id):
    return (state.get("sos_pending") or {}).get(user_id)


def sos_tap(state, user_id) -> dict:
    """用戶按了一次 SOS。回傳 {action: "warning"|"sent"|"expired"|"cooldown"} 與更新後的 entry。"""
    pending = state.setdefault("sos_pending", {})
    now = datetime.now()
    existing = pending.get(user_id)
    window = timedelta(seconds=SOS_TAP_WINDOW_SEC)

    if existing and existing.get("stage") == "sent":
        # 已發送,不再累加 tap,但顯示 sent Flex
        return {"action": "sent", "entry": existing}

    if existing and existing.get("stage") == "cancelled":
        # 已取消,清掉並重新開始
        del pending[user_id]
        existing = None

    if existing:
        last_tap = datetime.fromisoformat(existing["last_tap_at"])
        if now - last_tap <= window:
            existing["tap_count"] = existing.get("tap_count", 0) + 1
            existing["last_tap_at"] = now.isoformat(timespec="seconds")
            if existing["tap_count"] >= 3:
                existing["stage"] = "warning_3"  # 準備發送
            else:
                existing["stage"] = f"warning_{existing['tap_count']}"
        else:
            # 過了 window,重置
            existing["tap_count"] = 1
            existing["first_tap_at"] = now.isoformat(timespec="seconds")
            existing["last_tap_at"] = now.isoformat(timespec="seconds")
            existing["stage"] = "warning_1"
    else:
        pending[user_id] = {
            "stage": "warning_1",
            "tap_count": 1,
            "first_tap_at": now.isoformat(timespec="seconds"),
            "last_tap_at": now.isoformat(timespec="seconds"),
            "sent_at": None,
            "event_id": None,
        }
        existing = pending[user_id]

    return {"action": "warning", "entry": existing}


def sos_mark_sent(state, user_id, event_id: str | None = None):
    pending = state.setdefault("sos_pending", {})
    if user_id in pending:
        pending[user_id]["stage"] = "sent"
        pending[user_id]["sent_at"] = datetime.now().isoformat(timespec="seconds")
        if event_id:
            pending[user_id]["event_id"] = event_id
        return True
    return False


def sos_cancel_pending(state, user_id) -> bool:
    pending = state.setdefault("sos_pending", {})
    if user_id in pending:
        pending[user_id]["stage"] = "cancelled"
        pending[user_id]["cancelled_at"] = datetime.now().isoformat(timespec="seconds")
        return True
    return False


def sos_purge_old(state, keep_minutes: int = 60):
    """清理過期的 warning / sent / cancelled 紀錄。"""
    pending = state.get("sos_pending") or {}
    now = datetime.now()
    cutoff = now - timedelta(minutes=keep_minutes)
    removed = []
    for uid, entry in list(pending.items()):
        ts_str = entry.get("sent_at") or entry.get("cancelled_at") or entry.get("last_tap_at")
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


def sos_get_recently_sent(state, now=None, within_min: int = SOS_POST_SEND_CANCEL_MIN):
    """找出最近送出但還沒過取消期的 SOS(供 cron 提醒)。"""
    now = now or datetime.now()
    pending = state.get("sos_pending") or {}
    out = []
    for uid, entry in pending.items():
        if entry.get("stage") != "sent":
            continue
        sent_at = entry.get("sent_at")
        if not sent_at:
            continue
        try:
            ts = datetime.fromisoformat(sent_at)
            if now - ts <= timedelta(minutes=within_min):
                out.append((uid, entry))
        except Exception:
            continue
    return out