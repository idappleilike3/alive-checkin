import json
import os
import re
import secrets
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from flask import Flask, Response, jsonify, redirect, request, send_from_directory
except ModuleNotFoundError:
    Flask = None
    Response = None
    redirect = None

try:
    from linebot import LineBotApi, WebhookHandler
    from linebot.exceptions import InvalidSignatureError, LineBotApiError
    from linebot.models import (
        JoinEvent,
        MessageEvent,
        TextMessage,
        TextSendMessage,
        MemberJoinedEvent,
        FlexSendMessage,
        FollowEvent,
    )
except ModuleNotFoundError:
    LineBotApi = None
    WebhookHandler = None
    InvalidSignatureError = Exception
    LineBotApiError = Exception
    JoinEvent = None
    MessageEvent = None
    TextMessage = None
    TextSendMessage = None
    MemberJoinedEvent = None
    FlexSendMessage = None
    FollowEvent = None

# 守護群 Flex 構建器(2026-07-21 patch 11)
try:
    from guardian_group_flex import (
        guardian_group_intro_flex,
        guardian_group_status_flex,
        guardian_group_bind_confirm_flex,
        guardian_group_bind_fail_flex,
        guardian_group_user_guide_flex,
        guardian_group_admin_setup_flex,
        welcome_flex,
        welcome_greeting_text,
        liff_entry_url,
        get_liff_id,
        share_invite_liff_url,
    )
except Exception:
    guardian_group_intro_flex = None
    guardian_group_status_flex = None
    guardian_group_bind_confirm_flex = None
    guardian_group_bind_fail_flex = None
    guardian_group_user_guide_flex = None
    guardian_group_admin_setup_flex = None
    welcome_flex = None
    welcome_greeting_text = None
    liff_entry_url = None
    get_liff_id = None
    share_invite_liff_url = None

# 註:patch 15 的全域白名單機制(GROUP_ADMINS / is_group_admin / deny_if_not_admin)
# 已於 2026-07-21 移除。「管理員」= 每個守護群的 owner_line_user_id(在 guardian_groups 裡)。
# patch 16 加強 self-intro 顯示 owner 狀態。

# SOS 求救流程(2026-07-21 patch 20):3 次確認 + 10 分鐘取消期
try:
    import sos_flow
except Exception:
    sos_flow = None

try:
    from line_auth import resolve_line_user_id
except Exception:  # pragma: no cover
    resolve_line_user_id = None

try:
    import newebpay
except Exception:  # pragma: no cover
    newebpay = None


DEFAULT_PROFILE = {
    "last_check_in": None,
    "history": [],
    "contact_email": "",
    "grace_hours": 36,
    "reminder_time": "12:00",
    "reminder_times": ["12:00"],
    "checkin_mode": "manual",
    "auto_checkin_on_open": False,
    "warning_cancel_minutes": 15,
    "alert_channels": ["line"],
    "attach_location_on_alert": False,
    "contacts": [],
    "contact_capacity_reminder_enabled": False,
    "contact_reminder_sent_dates": [],
    "checkin_reminder_sent_dates": [],
    "checkin_reminder_sent_slots": {},
    "guardian_details_reminder_enabled": True,
    "guardian_details_reminder_sent_at": "",
    "plan": "trial",
    "trial_started_at": None,
    "payment_status": "trial",
    "paid_until": "",
    "billing_cycle": "trial",
    "payment_provider": "",
    "payment_method_last4": "",
    "next_billing_date": "",
    "auto_renew_requested": False,
    "auto_renew_enabled": False,
    "auto_renew_status": "off",
    "friends": [],
    "location": {},
    "guardian_group_ids": [],
    "calendar_notes": {},
}

# 依每日提醒次數的預設時段(使用者未自訂時使用)
DEFAULT_REMINDER_TIMES_BY_COUNT = {
    1: ["12:00"],
    2: ["12:00", "18:00"],
    3: ["12:00", "18:00", "22:00"],
}
REMINDER_TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
DEFAULT_STATE = {
    **DEFAULT_PROFILE,
    "users": {},
    "notification_logs": [],
    "friend_invites": {},
    "contact_rewards": [],
    "support_tickets": [],
    "backup_exports": [],
    "guardian_groups": {},
    "orders": [],
}

PLAN_LIMITS = {
    "free": {"contact_limit": 1, "friend_location_limit": 1, "daily_reminders": 1, "channels": ["line"], "realtime_tracking": False, "trajectory_days": 0, "offline_sync_days": 0, "sos_enabled": True, "guardian_group_limit": 0},
    "trial": {"contact_limit": 1, "friend_location_limit": 1, "daily_reminders": 1, "channels": ["line"], "realtime_tracking": False, "trajectory_days": 0, "offline_sync_days": 0, "sos_enabled": True, "guardian_group_limit": 0},
    "paid_199": {"contact_limit": 4, "friend_location_limit": 4, "daily_reminders": 2, "channels": ["line"], "location_mode": "snapshot_24h", "core_guardian_alert_limit": 3, "realtime_tracking": False, "trajectory_days": 0, "offline_sync_days": 0, "sos_enabled": True, "guardian_group_limit": 0},
    "paid_199_year": {"contact_limit": 6, "friend_location_limit": 6, "daily_reminders": 2, "channels": ["line"], "location_mode": "snapshot_24h", "core_guardian_alert_limit": 3, "realtime_tracking": False, "trajectory_days": 0, "offline_sync_days": 0, "sos_enabled": True, "guardian_group_limit": 0},
    "paid_399": {"contact_limit": 15, "friend_location_limit": 15, "daily_reminders": 2, "channels": ["line"], "location_mode": "realtime", "core_guardian_alert_limit": 3, "realtime_tracking": False, "trajectory_days": 0, "offline_sync_days": 0, "sos_enabled": True, "guardian_group_limit": 0},
    "paid_399_year": {"contact_limit": 25, "friend_location_limit": 25, "daily_reminders": 2, "channels": ["line"], "location_mode": "realtime", "core_guardian_alert_limit": 3, "realtime_tracking": False, "trajectory_days": 0, "offline_sync_days": 0, "sos_enabled": True, "guardian_group_limit": 0, "realtime_trial_days": 30},
    "paid_799": {"contact_limit": 25, "friend_location_limit": 25, "daily_reminders": 3, "channels": ["line", "sms"], "location_mode": "full_guard", "core_guardian_alert_limit": 3, "realtime_tracking": False, "trajectory_days": 0, "offline_sync_days": 0, "sos_enabled": True, "guardian_group_limit": 1},
    "paid_799_year": {"contact_limit": 50, "friend_location_limit": 50, "daily_reminders": 3, "channels": ["line", "sms"], "location_mode": "full_guard", "core_guardian_alert_limit": 5, "realtime_tracking": False, "trajectory_days": 0, "offline_sync_days": 0, "sos_enabled": True, "guardian_group_limit": 3},
}

PAYMENT_PRODUCTS = {
    # 🔴 v0.5 P0 更新:依蝦董 2026-07-17 最終版 16 章規格
    "paid_199": {"amount": 199, "billing_cycle": "monthly", "duration_days": 30, "display_name": "199 平安版(月)", "tagline": "每天提醒自己簽到,讓自己安心"},
    "paid_199_year": {"amount": 1680, "billing_cycle": "yearly", "duration_days": 365, "display_name": "199 平安版(年)", "tagline": "每天提醒自己簽到,讓自己安心"},
    "paid_399": {"amount": 399, "billing_cycle": "monthly", "duration_days": 30, "display_name": "399 安心版(月)", "tagline": "讓家人隨時知道你在哪,即時追蹤定位"},
    "paid_399_year": {"amount": 3680, "billing_cycle": "yearly", "duration_days": 365, "display_name": "399 安心版(年)", "tagline": "讓家人隨時知道你在哪,即時追蹤定位"},
    "paid_799": {"amount": 799, "billing_cycle": "monthly", "duration_days": 30, "display_name": "799 守護版(月)", "tagline": "全家守護網絡 + LINE 預警 + SOS 緊急求救"},
    "paid_799_year": {"amount": 7200, "billing_cycle": "yearly", "duration_days": 365, "display_name": "799 守護版(年)", "tagline": "全家 50 人守護網絡 + LINE 預警 + SOS 緊急求救 + 守護群"},
}

RICH_MENU_COMMANDS = [
    "今日簽到",
    "綁定守護人",
    "我的狀態",
    "查看方案",
    "問與答",
    "聯絡客服",
]

CHECKIN_KEYWORDS = {"簽到", "打卡", "報平安", "今日簽到"}
CONTACT_KEYWORDS = {"綁定守護人", "聯絡人", "緊急聯絡人", "填聯絡人", "修改電話", "守護人"}
STATUS_KEYWORDS = {"狀態", "我的狀態", "查詢紀錄"}
PLAN_KEYWORDS = {"方案", "價格", "收費", "升級", "查看方案", "多少錢"}
FAQ_KEYWORDS = {"問與答", "FAQ", "常見問題"}
SUPPORT_KEYWORDS = {"客服", "人工", "幫助", "找不到", "問題", "聯絡客服"}
INVOICE_KEYWORDS = {"發票", "收據", "付款證明"}
GROUP_KEYWORDS = {"守護群", "群組", "拉人"}
ALERT_CHANNEL_KEYWORDS = {"電話", "簡訊", "全渠道", "全通道", "自動撥號"}
LARGE_TEXT_KEYWORDS = {"大字", "老人模式", "字體太小", "長輩模式"}


def line_status_summary(status):
    if not status:
        return "目前還沒有查到你的簽到紀錄。請先點「今日簽到」，建立第一筆平安紀錄。"
    last_checkin = status.get("last_check_in") or "尚未簽到"
    contacts = len(status.get("contacts") or [])
    contact_limit = status.get("contact_limit", 1)
    plan = status.get("plan") or "trial"
    reminder_times = status.get("reminder_times") or [status.get("reminder_time") or "12:00"]
    if not isinstance(reminder_times, list):
        reminder_times = [str(reminder_times)]
    times_text = "、".join(str(t) for t in reminder_times if t)
    return (
        "你的近期狀態如下：\n"
        f"最後簽到：{last_checkin}\n"
        f"目前方案：{plan}\n"
        f"守護人：{contacts}/{contact_limit} 位\n"
        f"每日提醒時間：{times_text or '12:00'}\n\n"
        "若守護人還沒綁定，請點「綁定守護人」，把 LINE 邀請連結傳給身邊重要的人。"
    )


def line_liff_url(open_action):
    if liff_entry_url is not None:
        return liff_entry_url(open_action=open_action)
    liff_id = (os.environ.get("LIFF_ID") or "2010674803-rK98c0lo").strip()
    return f"https://liff.line.me/{liff_id}/?open={open_action}"


def public_page_url(path=""):
    public_url = (os.environ.get("APP_PUBLIC_URL") or "https://alive-checkin.onrender.com/").strip().rstrip("/")
    path = str(path or "").lstrip("/")
    return f"{public_url}/{path}" if path else f"{public_url}/"


def pricing_direct_url():
    """方案頁直連（勿走 LIFF Endpoint 首頁再 client redirect，會很慢）。"""
    return public_page_url("liff/pricing.html")


def permanent_liff_invite_url(*, invite_from="", friend_invite="", open_action=None):
    """Android-friendly permanent LIFF invite URL (never a bare onrender SPA link)."""
    params = {}
    invite_from = str(invite_from or "").strip()
    friend_invite = str(friend_invite or "").strip()
    if invite_from:
        params["invite_from"] = invite_from
    if friend_invite:
        params["friend_invite"] = friend_invite
    if liff_entry_url is not None:
        return liff_entry_url(open_action=open_action, **params)
    lid = (os.environ.get("LIFF_ID") or "2010674803-rK98c0lo").strip() or "2010674803-rK98c0lo"
    if open_action and not params:
        return f"https://liff.line.me/{lid}/?open={open_action}"
    if open_action:
        params["open"] = open_action
    if params:
        return f"https://liff.line.me/{lid}/?{urllib.parse.urlencode(params)}"
    return f"https://liff.line.me/{lid}"


def line_app_invite_url(*, invite_from="", friend_invite="", open_action=None):
    """Force-open-in-LINE URL (https://line.me/R/app/...) — more reliable on Android Chrome."""
    lid = (os.environ.get("LIFF_ID") or "2010674803-rK98c0lo").strip() or "2010674803-rK98c0lo"
    params = {}
    invite_from = str(invite_from or "").strip()
    friend_invite = str(friend_invite or "").strip()
    if invite_from:
        params["invite_from"] = invite_from
    if friend_invite:
        params["friend_invite"] = friend_invite
    if open_action:
        params["open"] = str(open_action).strip()
    if not params:
        params["open"] = "onboarding"
    return f"https://line.me/R/app/{lid}/?{urllib.parse.urlencode(params)}"


def public_invite_landing_url(*, invite_from="", friend_invite="", open_action=None):
    """Public /invite landing — shows「用 LINE 開啟」when opened outside LINE."""
    params = {}
    invite_from = str(invite_from or "").strip()
    friend_invite = str(friend_invite or "").strip()
    if invite_from:
        params["from"] = invite_from
    if friend_invite:
        params["friend_invite"] = friend_invite
    if open_action:
        params["open"] = str(open_action).strip()
    base = public_page_url("invite")
    if not params:
        return base
    return f"{base}?{urllib.parse.urlencode(params)}"


def line_plan_message():
    pricing_url = pricing_direct_url()
    return (
        "可以，升級方案請點這裡：\n"
        f"{pricing_url}\n\n"
        "裡面會看到 199／399／799 的月費、年費與守護權益。"
    )


def line_auto_reply_text(text, status=None):
    text = (text or "").strip()
    if any(keyword in text for keyword in CHECKIN_KEYWORDS):
        return "今天平安簽到成功。系統已幫你留下紀錄，守護人不用擔心。"
    if any(keyword in text for keyword in CONTACT_KEYWORDS):
        return (
            "綁定守護人設定說明\n\n"
            "請先綁定至少 1 位守護人，緊急時系統才能透過 LINE 通知對方。\n\n"
            "操作方式：\n"
            "1. 點「一鍵邀請守護人」\n"
            "2. 輸入對方暱稱\n"
            "3. 用 LINE 分享邀請連結\n"
            "4. 對方點同意後，就能收到測試提醒\n\n"
            "守護人無須註冊，也能接收警報。"
        )
    if any(keyword in text for keyword in STATUS_KEYWORDS):
        return line_status_summary(status)
    if any(keyword in text for keyword in PLAN_KEYWORDS):
        return line_plan_message()
    if any(keyword in text for keyword in INVOICE_KEYWORDS):
        return (
            "目前尚未提供線上電子發票／收據查詢。\n"
            "若需要付款證明，請透過客服留言，我們會人工協助核對訂單。"
        )
    if any(keyword in text for keyword in GROUP_KEYWORDS):
        return (
            "守護群功能說明：\n"
            "守護群適合家人、親友或社區關懷小組一起接收平安狀態。\n"
            "有效的 799 月費會員可建立 1 群，年費會員最多可建立 3 群。\n"
            "請把「每日平安」官方帳號加入群組後，由方案本人輸入「點我綁定守護群」。若資格不符，「每日平安」會說明原因並退出群組。\n"
            "「每日平安」只處理簽到、預警與守護指令，不會把一般聊天內容存進會員資料。"
        )
    if any(keyword in text for keyword in ALERT_CHANNEL_KEYWORDS):
        return (
            "緊急通知方式說明：\n"
            "199／399 以 LINE 通知為主。\n"
            "799 月費可用 LINE 通知 3 位核心守護人，年費可通知 5 位。\n"
            "簡訊預警尚未開放；目前以 LINE 與守護群通知為主。"
        )
    if any(keyword in text for keyword in LARGE_TEXT_KEYWORDS):
        return (
            "大字模式規劃中：\n"
            "這個功能會讓長輩看到更大的文字、更少的選項，以及更明顯的簽到按鈕。\n"
            "目前可先使用手機瀏覽器或 LINE 內建的文字縮放功能。"
        )
    if any(keyword in text for keyword in FAQ_KEYWORDS):
        faq_url = line_liff_url("faq")
        pricing_url = line_liff_url("pricing")
        return (
            "常見問題：\n"
            "Q：守護人一定要註冊嗎？\n"
            "A：不用，對方點 LINE 授權同意後即可接收提醒。\n\n"
            "Q：定位會一直被追蹤嗎？\n"
            "A：預設是 24 小時快照分享；即時追蹤需使用者自行開啟。\n\n"
            "Q：真的緊急怎麼辦？\n"
            "A：若有立即危險，請優先撥打 119。\n\n"
            f"完整問與答：{faq_url}\n"
            f"查看方案：{pricing_url}"
        )
    if any(keyword in text for keyword in SUPPORT_KEYWORDS):
        faq_url = line_liff_url("faq")
        return (
            "客服在這裡。你可以直接回覆你的問題，我們會協助你設定簽到、守護人與方案。\n\n"
            f"也可以先看問與答：{faq_url}\n\n"
            "提醒：若是立即危險或醫療緊急狀況，請先撥打 119。"
        )
    return (
        "我看到了。你可以點下方選單：今日簽到、綁定守護人、我的狀態、查看方案、問與答、聯絡客服。\n\n"
        "若是立即危險，請優先撥打 119。"
    )


def should_create_support_ticket(text):
    text = (text or "").strip()
    if len(text) <= 5:
        return False
    keyword_groups = [
        CHECKIN_KEYWORDS,
        CONTACT_KEYWORDS,
        STATUS_KEYWORDS,
        PLAN_KEYWORDS,
        FAQ_KEYWORDS,
        SUPPORT_KEYWORDS,
        INVOICE_KEYWORDS,
        GROUP_KEYWORDS,
        ALERT_CHANNEL_KEYWORDS,
        LARGE_TEXT_KEYWORDS,
    ]
    return not any(keyword in text for group in keyword_groups for keyword in group)


def _resolve_db_path(data_file):
    """Resolve SQLite database path from configured data file path.

    Accepts legacy ``state.json`` paths and returns ``state.db`` sibling.
    Also accepts explicit ``.db`` paths unchanged.
    """
    text = str(data_file)
    if text.endswith(".json"):
        return text[: -len(".json")] + ".db"
    return text


def _ensure_db(db_path):
    """Create the SQLite database and kv_store table if missing."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS kv_store ("
            "  key TEXT PRIMARY KEY,"
            "  value TEXT NOT NULL,"
            "  updated_at TEXT NOT NULL DEFAULT (datetime('now'))"
            ")"
        )
        conn.commit()
    finally:
        conn.close()


def _migrate_legacy_json(data_file, db_path):
    """One-shot migration: read legacy state.json, write into SQLite, rename to .bak."""
    json_path = Path(str(data_file))
    if not json_path.exists():
        return
    try:
        legacy = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT OR REPLACE INTO kv_store (key, value) VALUES (?, ?)",
            ("default", json.dumps(legacy, ensure_ascii=False, indent=2)),
        )
        conn.commit()
    finally:
        conn.close()
    try:
        json_path.rename(str(json_path) + ".bak")
    except OSError:
        pass


def load_state(data_file):
    """Load state from SQLite (auto-migrates legacy state.json on first call)."""
    db_path = _resolve_db_path(data_file)
    if not Path(db_path).exists():
        _ensure_db(db_path)
        _migrate_legacy_json(data_file, db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT value FROM kv_store WHERE key = ?", ("default",)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return {**DEFAULT_STATE, "users": {}}
    try:
        saved = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return {**DEFAULT_STATE, "users": {}}

    state = {**DEFAULT_STATE, **saved}
    state["history"] = sorted(set(state.get("history") or []))
    state["users"] = state.get("users") or {}
    state["notification_logs"] = state.get("notification_logs") or []
    state["friend_invites"] = state.get("friend_invites") or {}
    state["contact_rewards"] = state.get("contact_rewards") or []
    state["support_tickets"] = state.get("support_tickets") or []
    state["backup_exports"] = state.get("backup_exports") or []
    state["guardian_groups"] = state.get("guardian_groups") or {}
    state["orders"] = state.get("orders") or []
    return state


def save_state(data_file, state):
    """Persist state to SQLite with an atomic transaction."""
    db_path = _resolve_db_path(data_file)
    _ensure_db(db_path)
    payload = json.dumps(state, ensure_ascii=False, indent=2)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT OR REPLACE INTO kv_store (key, value, updated_at) "
            "VALUES (?, ?, datetime('now'))",
            ("default", payload),
        )
        conn.commit()
    finally:
        conn.close()


def today_string():
    return datetime.now().strftime("%Y-%m-%d")


def current_app_time(config):
    fixed_now = config.get("CRON_NOW") if config else None
    if fixed_now:
        return fixed_now
    timezone_name = (config.get("APP_TIMEZONE") if config else None) or os.environ.get("APP_TIMEZONE", "Asia/Taipei")
    try:
        return datetime.now(ZoneInfo(timezone_name)).replace(tzinfo=None)
    except Exception:
        if timezone_name == "Asia/Taipei":
            return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=8)
        return datetime.now()


def parse_last_checkin(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def parse_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def get_profile(state, line_user_id=None):
    if line_user_id:
        user = state.setdefault("users", {}).setdefault(
            line_user_id,
            {**DEFAULT_PROFILE, "line_user_id": line_user_id, "display_name": "LINE 使用者"},
        )
        for key, value in DEFAULT_PROFILE.items():
            user.setdefault(key, value)
        if not user.get("trial_started_at"):
            user["trial_started_at"] = datetime.now().isoformat(timespec="seconds")
        user["line_user_id"] = line_user_id
        return user
    return state


def get_calendar_notes(data_file, line_user_id=None):
    line_user_id = (line_user_id or "").strip()
    if not line_user_id:
        return {"ok": False, "error": "missing line_user_id", "notes": {}}
    state = load_state(data_file)
    profile = get_profile(state, line_user_id)
    notes = profile.get("calendar_notes")
    if not isinstance(notes, dict):
        notes = {}
    return {"ok": True, "notes": dict(notes)}


def save_calendar_note(data_file, payload):
    line_user_id = (payload.get("line_user_id") or "").strip()
    note_date = (payload.get("date") or "").strip()
    content = str(payload.get("content") or "").strip()
    birthday_name = str(payload.get("birthday_name") or "").strip()
    birthday_relationship = str(payload.get("birthday_relationship") or "").strip()
    birthday_date = str(payload.get("birthday_date") or note_date).strip()
    birthday_yearly = bool(payload.get("birthday_yearly", True))
    try:
        birthday_remind_days = int(payload.get("birthday_remind_days", 1))
    except (TypeError, ValueError):
        birthday_remind_days = 1
    if birthday_remind_days not in (0, 1, 3, 7):
        birthday_remind_days = 1
    if not line_user_id:
        return {"ok": False, "error": "missing line_user_id"}, 400
    try:
        parsed_date = datetime.strptime(note_date, "%Y-%m-%d")
    except ValueError:
        return {"ok": False, "error": "invalid date"}, 400
    if parsed_date.strftime("%Y-%m-%d") != note_date:
        return {"ok": False, "error": "invalid date"}, 400
    if len(content) > 500:
        return {"ok": False, "error": "note too long"}, 400
    if birthday_name:
        try:
            parsed_birthday = datetime.strptime(birthday_date, "%Y-%m-%d")
        except ValueError:
            return {"ok": False, "error": "invalid birthday date"}, 400
        if parsed_birthday.strftime("%Y-%m-%d") != birthday_date:
            return {"ok": False, "error": "invalid birthday date"}, 400

    state = load_state(data_file)
    profile = get_profile(state, line_user_id)
    notes = dict(profile.get("calendar_notes") or {})
    if content or birthday_name:
        if birthday_name:
            notes[note_date] = {
                "content": content,
                "birthday_name": birthday_name,
                "birthday_relationship": birthday_relationship,
                "birthday_date": birthday_date,
                "birthday_yearly": birthday_yearly,
                "birthday_remind_days": birthday_remind_days,
            }
        else:
            notes[note_date] = content
    else:
        notes.pop(note_date, None)
    profile["calendar_notes"] = notes
    save_state(data_file, state)
    return {"ok": True, "notes": notes}, 200


def calendar_note_content(note):
    if isinstance(note, dict):
        return str(note.get("content") or "").strip()
    return str(note or "").strip()


def calendar_note_birthday(note):
    if not isinstance(note, dict) or not str(note.get("birthday_name") or "").strip():
        return None
    return {
        "birthday_name": str(note.get("birthday_name") or "").strip(),
        "birthday_relationship": str(note.get("birthday_relationship") or "").strip(),
        "birthday_date": str(note.get("birthday_date") or "").strip(),
        "birthday_yearly": bool(note.get("birthday_yearly", True)),
        "birthday_remind_days": int(note.get("birthday_remind_days") or 1),
    }


def birthday_occurs_on(birthday, target_date):
    try:
        source = datetime.strptime(birthday.get("birthday_date", ""), "%Y-%m-%d").date()
    except ValueError:
        return False
    if birthday.get("birthday_yearly", True):
        return source.month == target_date.month and source.day == target_date.day
    return source == target_date


def plan_rules(profile):
    plan = profile.get("plan") or "trial"
    return PLAN_LIMITS.get(plan, PLAN_LIMITS["trial"])


def default_reminder_times_for_count(count):
    """依提醒次數回傳預設時段:1→12:00、2→12/18、3→12/18/22。"""
    try:
        count = int(count or 1)
    except (TypeError, ValueError):
        count = 1
    count = max(1, min(3, count))
    return list(DEFAULT_REMINDER_TIMES_BY_COUNT.get(count, DEFAULT_REMINDER_TIMES_BY_COUNT[1]))


def normalize_reminder_times(raw_times, max_count=1):
    """驗證並正規化 HH:MM 清單,去重後依時間排序,截斷至方案上限。"""
    try:
        max_count = max(1, min(3, int(max_count or 1)))
    except (TypeError, ValueError):
        max_count = 1
    if isinstance(raw_times, str):
        raw_times = [raw_times]
    if not isinstance(raw_times, (list, tuple)):
        return []
    cleaned = []
    seen = set()
    for item in raw_times:
        text = str(item or "").strip()
        if not REMINDER_TIME_PATTERN.match(text) or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    cleaned.sort()
    return cleaned[:max_count]


def reminder_times_for_profile(profile):
    """取得使用者提醒時段:自訂 reminder_times > 單一 reminder_time > 方案預設。"""
    max_count = int(plan_rules(profile).get("daily_reminders") or 1)
    raw = profile.get("reminder_times")
    if isinstance(raw, (list, tuple)) and raw:
        normalized = normalize_reminder_times(raw, max_count)
        if normalized:
            return normalized
    single = str(profile.get("reminder_time") or "").strip()
    if REMINDER_TIME_PATTERN.match(single):
        return normalize_reminder_times([single], max_count) or default_reminder_times_for_count(max_count)
    return default_reminder_times_for_count(max_count)


def apply_reminder_times_to_profile(profile, times=None, single=None):
    """寫入 reminder_times,並同步第一個時段到 reminder_time(相容舊欄位)。"""
    max_count = int(plan_rules(profile).get("daily_reminders") or 1)
    if times is not None:
        normalized = normalize_reminder_times(times, max_count)
    elif single is not None and str(single).strip():
        normalized = normalize_reminder_times([single], max_count)
    else:
        normalized = []
    if not normalized:
        normalized = default_reminder_times_for_count(max_count)
    profile["reminder_times"] = normalized
    profile["reminder_time"] = normalized[0]
    return normalized


# === D01: 互動狀態(防每日重複相同內容) ===
def default_interaction_state():
    return {
        "last_interaction_at": "",
        "last_interaction_summary": "",
        "completed_steps": [],
        "pending_steps": [],
        "dismissed_prompts": {},
        "next_reminder_at": "",
        "last_closing_message": "",
        "onboarding_completed": False,
        "guardian_prompt_status": "pending",  # pending / accepted / snoozed / dismissed
        "guardian_reminder_preference": "",  # now / tomorrow / dismiss_7d / dismissed
        "guardian_reminder_snoozed_until": "",
        "guardian_last_prompted_at": "",
    }


def get_or_create_interaction_state(profile):
    """讀取或初始化 profile.interaction_state。"""
    if "interaction_state" not in profile or not isinstance(profile.get("interaction_state"), dict):
        profile["interaction_state"] = default_interaction_state()
    # 補齊缺漏欄位(往後加新欄位時不會壞舊資料)
    defaults = default_interaction_state()
    for k, v in defaults.items():
        if k not in profile["interaction_state"]:
            profile["interaction_state"][k] = v
    return profile["interaction_state"]


def contact_is_bound_guardian(contact):
    """對方是否已透過 LINE 綁定／同意成為守護人。"""
    if not isinstance(contact, dict):
        return False
    return bool(
        contact.get("line_user_id")
        or contact.get("line_id")
        or contact.get("binding_status") == "accepted"
        or contact.get("consent_status") == "accepted"
    )


def contact_has_guardian_profile(contact):
    """是否已填寫守護人基本資料（姓名＋關係）。"""
    if not isinstance(contact, dict):
        return False
    return bool((contact.get("name") or "").strip() and (contact.get("relationship") or "").strip())


def profile_has_guardian(profile):
    """使用者是否已有至少 1 位守護人（資料或 LINE 綁定）。"""
    contacts = (profile or {}).get("contacts") or []
    return any(contact_has_guardian_profile(c) or contact_is_bound_guardian(c) for c in contacts)


def profile_setup_completed(profile):
    """首次設定是否已完成：以伺服器 durable flag／守護人為準（不用只靠 localStorage）。"""
    if not profile:
        return False
    if profile.get("is_onboarding_completed"):
        return True
    istate = profile.get("interaction_state") or {}
    if isinstance(istate, dict) and istate.get("onboarding_completed"):
        return True
    return profile_has_guardian(profile)


def ensure_onboarding_completed_flag(profile):
    """若已有守護人但旗標未寫入，補上 durable flag（回傳是否有變更）。"""
    if not profile:
        return False
    if profile.get("is_onboarding_completed") and (
        isinstance(profile.get("interaction_state"), dict)
        and profile["interaction_state"].get("onboarding_completed")
    ):
        return False
    if not profile_has_guardian(profile) and not profile.get("is_onboarding_completed"):
        return False
    changed = False
    if profile_has_guardian(profile) or profile.get("is_onboarding_completed"):
        if not profile.get("is_onboarding_completed"):
            profile["is_onboarding_completed"] = True
            changed = True
        istate = get_or_create_interaction_state(profile)
        if not istate.get("onboarding_completed"):
            istate["onboarding_completed"] = True
            changed = True
        if "add_first_guardian" not in (istate.get("completed_steps") or []):
            istate.setdefault("completed_steps", []).append("add_first_guardian")
            changed = True
    return changed


def should_show_guardian_prompt(profile, contact_count):
    """判斷是否該彈守護人完成度提示卡。

    規則:
    - 已是 399/799 會員才顯示(免費/體驗只強制 1 位,不再催)
    - contact_count >= limit → 不顯示
    - contact_count < limit:
      - 沒問過 OR last_prompted_at 超過 1 天前 → 顯示
      - guardian_reminder_preference == 'tomorrow' 且 snoozed_until > now → 不顯示
      - guardian_reminder_preference == 'dismiss_7d' 且 snoozed_until > now → 不顯示
    """
    plan = profile.get("plan") or "trial"
    if plan not in ("paid_399", "paid_399_year", "paid_799", "paid_799_year"):
        return False
    limit = plan_rules(profile)["contact_limit"]
    if contact_count >= limit:
        return False
    state = get_or_create_interaction_state(profile)
    pref = state.get("guardian_reminder_preference", "")
    now_iso = datetime.now().isoformat(timespec="seconds")
    if pref == "tomorrow" and state.get("guardian_reminder_snoozed_until", "") > now_iso:
        return False
    if pref == "dismiss_7d" and state.get("guardian_reminder_snoozed_until", "") > now_iso:
        return False
    if pref == "dismissed":
        return False
    last = state.get("guardian_last_prompted_at", "")
    if last and last > now_iso:  # safety:未來時間就不顯示
        return False
    return True



def trial_days_left(profile):
    started_at = parse_datetime(profile.get("trial_started_at"))
    if not started_at:
        return 7
    elapsed_days = (datetime.now() - started_at).days
    return max(0, 7 - elapsed_days)


def trial_active(profile):
    return (profile.get("plan") or "trial") == "trial" and trial_days_left(profile) > 0


def compute_streak_days(history, today):
    """計算連續簽到天數(以 Asia/Taipei 為主)。

    規則:
    - 今天有簽到 → 從今天往前連續算
    - 今天沒簽到但昨天有簽到 → 從昨天往前算(代表昨天還平安)
    - 中間缺一天就中斷
    - history 重複日期不影響(set 化)
    """
    if not history:
        return 0
    history_set = set(history)
    if today in history_set:
        start = today
    else:
        from datetime import datetime as _dt, timedelta as _td
        try:
            yesterday = (_dt.strptime(today, "%Y-%m-%d") - _td(days=1)).strftime("%Y-%m-%d")
        except ValueError:
            return 0
        if yesterday in history_set:
            start = yesterday
        else:
            return 0
    streak = 0
    from datetime import datetime as _dt, timedelta as _td
    cur = _dt.strptime(start, "%Y-%m-%d")
    while cur.strftime("%Y-%m-%d") in history_set:
        streak += 1
        cur -= _td(days=1)
    return streak


def build_status(profile, state=None):
    profile = {**DEFAULT_PROFILE, **profile}
    now = datetime.now()
    last = parse_last_checkin(profile.get("last_check_in"))
    grace_hours = int(profile.get("grace_hours") or 36)
    warning_cancel_minutes = int(profile.get("warning_cancel_minutes") or 15)
    deadline = last + timedelta(hours=grace_hours) if last else None
    alert_at = deadline + timedelta(minutes=warning_cancel_minutes) if deadline else None
    remaining_ms = max(0, int((deadline - now).total_seconds() * 1000)) if deadline else 0
    cancel_remaining_ms = max(0, int((alert_at - now).total_seconds() * 1000)) if alert_at and now > deadline else 0
    prealert = bool(deadline and alert_at and deadline < now <= alert_at)
    overdue = bool(alert_at and now > alert_at)
    today = today_string()
    is_today_checked = today in (profile.get("history") or [])

    if not last:
        status_text = "還沒有簽到紀錄"
        status_class = "gray"
    elif prealert:
        status_text = "預警取消期，可一鍵取消"
        status_class = "warning"
    elif overdue:
        status_text = "已超過寬限時間"
        status_class = "danger"
    elif remaining_ms <= 6 * 60 * 60 * 1000:
        status_text = "快到提醒時間了"
        status_class = "warning"
    else:
        status_text = "狀態正常"
        status_class = "highlight"

    _reminder_times = reminder_times_for_profile(profile) or ["12:00"]
    guardian_groups = []
    if state is not None:
        groups = state.get("guardian_groups", {}) or {}
        for group_id in profile.get("guardian_group_ids", []) or []:
            group = groups.get(group_id)
            if group and group.get("owner_line_user_id") == profile.get("line_user_id"):
                guardian_groups.append(group)

    return {
        "ok": True,
        "line_user_id": profile.get("line_user_id"),
        "display_name": profile.get("display_name", ""),
        "picture_url": profile.get("picture_url", ""),
        "streak_days": compute_streak_days(profile.get("history") or [], today),
        "last_check_in": profile.get("last_check_in"),
        "history": sorted(set(profile.get("history") or [])),
        "contact_email": profile.get("contact_email", ""),
        "grace_hours": grace_hours,
        "reminder_time": _reminder_times[0],
        "reminder_times": _reminder_times,
        "checkin_mode": profile.get("checkin_mode", "manual"),
        "auto_checkin_on_open": bool(profile.get("auto_checkin_on_open", False)),
        "warning_cancel_minutes": warning_cancel_minutes,
        "alert_channels": profile.get("alert_channels", ["line"]),
        "attach_location_on_alert": bool(profile.get("attach_location_on_alert", False)),
        "contacts": profile.get("contacts", []),
        "contact_capacity_reminder_enabled": bool(profile.get("contact_capacity_reminder_enabled", False)),
        "guardian_details_reminder_enabled": bool(profile.get("guardian_details_reminder_enabled", True)),
        "guardian_details_complete": any(complete_guardian_contact(contact) for contact in (profile.get("contacts") or [])),
        "plan": profile.get("plan", "trial"),
        "payment_status": profile.get("payment_status", "trial"),
        "paid_until": profile.get("paid_until", ""),
        "billing_cycle": profile.get("billing_cycle", "trial"),
        "payment_provider": profile.get("payment_provider", ""),
        "payment_method_last4": profile.get("payment_method_last4", ""),
        "next_billing_date": profile.get("next_billing_date", ""),
        "auto_renew_requested": bool(profile.get("auto_renew_requested", False)),
        "auto_renew_enabled": bool(profile.get("auto_renew_enabled", False)),
        "auto_renew_status": profile.get("auto_renew_status", "off"),
        "trial_started_at": profile.get("trial_started_at"),
        "trial_days_left": trial_days_left(profile),
        "trial_active": trial_active(profile),
        "contact_limit": plan_rules(profile)["contact_limit"],
        "daily_reminders": plan_rules(profile)["daily_reminders"],
        "channels": plan_rules(profile)["channels"],
        "location_mode": plan_rules(profile).get("location_mode", "snapshot_24h"),
        "friend_location_limit": plan_rules(profile).get("friend_location_limit", 1),
        "realtime_tracking": bool(plan_rules(profile).get("realtime_tracking", False)),
        "trajectory_days": int(plan_rules(profile).get("trajectory_days", 0)),
        "offline_sync_days": int(plan_rules(profile).get("offline_sync_days", 0)),
        "sos_enabled": bool(
            plan_rules(profile).get("sos_enabled", False)
            and (
                (profile.get("plan") or "trial") in ("free", "trial")
                or paid_membership_is_active(profile)
                or trial_active(profile)
            )
        ),
        "dedicated_support": bool(plan_rules(profile).get("dedicated_support", False)),
        "realtime_trial_days": int(plan_rules(profile).get("realtime_trial_days", 0)),
        "core_guardian_alert_limit": plan_rules(profile).get("core_guardian_alert_limit", 1),
        "guardian_group_limit": plan_rules(profile).get("guardian_group_limit", 0),
        "guardian_group_ids": profile.get("guardian_group_ids", []),
        "guardian_groups": guardian_groups,
        "is_today_checked": is_today_checked,
        "is_prealert": prealert,
        "is_overdue": overdue,
        "remaining_ms": remaining_ms,
        "cancel_remaining_ms": cancel_remaining_ms,
        "alert_at": alert_at.isoformat(timespec="seconds") if alert_at else None,
        "status_text": status_text,
        "status_class": status_class,
        "safety_guard": safety_guard_snapshot(profile),
    }


def register_line_user(data_file, payload):
    line_user_id = str(payload.get("line_user_id") or "").strip()
    if not line_user_id:
        return {"error": "missing line_user_id"}, 400
    state = load_state(data_file)
    user = get_profile(state, line_user_id)
    user["display_name"] = str(payload.get("display_name") or user.get("display_name") or "LINE 使用者")
    user["picture_url"] = str(payload.get("picture_url") or user.get("picture_url") or "")
    save_state(data_file, state)
    return build_status(user), 200


_WELCOME_NAME_PLACEHOLDERS = frozenset(
    {"", "您", "LINE 使用者", "LINE 會員", "LINE 聯絡人", "使用者"}
)


def extract_line_display_name(profile_obj) -> str | None:
    """從 line-bot-sdk Profile / dict 取出可用的 displayName。"""
    if profile_obj is None:
        return None
    candidates = []
    for attr in ("display_name", "displayName"):
        val = getattr(profile_obj, attr, None)
        if val:
            candidates.append(str(val).strip())
    if isinstance(profile_obj, dict):
        for key in ("displayName", "display_name"):
            if profile_obj.get(key):
                candidates.append(str(profile_obj.get(key)).strip())
    elif hasattr(profile_obj, "as_json_dict"):
        try:
            data = profile_obj.as_json_dict() or {}
            for key in ("displayName", "display_name"):
                if data.get(key):
                    candidates.append(str(data.get(key)).strip())
        except Exception:
            pass
    for name in candidates:
        if name and name not in _WELCOME_NAME_PLACEHOLDERS:
            return name
    return None


def resolve_welcome_display_name(
    line_bot_api=None,
    data_file=None,
    line_user_id=None,
    hint=None,
    logger=None,
) -> str | None:
    """Follow /「開始」共用：優先 LINE profile，其次 hint / 本地 users，失敗回 None。"""
    hint_clean = (hint or "").strip()
    if hint_clean and hint_clean not in _WELCOME_NAME_PLACEHOLDERS:
        return hint_clean

    uid = (line_user_id or "").strip()
    if uid and line_bot_api is not None:
        try:
            profile = line_bot_api.get_profile(uid)
            name = extract_line_display_name(profile)
            if name:
                return name
            if logger:
                logger.warning(
                    "welcome profile missing displayName user=%s",
                    uid[:8],
                )
        except Exception as exc:
            if logger:
                logger.warning(
                    "welcome get_profile failed user=%s err=%s",
                    uid[:8],
                    exc,
                )

    if uid and data_file:
        try:
            stored = (get_profile(load_state(data_file), uid) or {}).get("display_name") or ""
            stored = str(stored).strip()
            if stored and stored not in _WELCOME_NAME_PLACEHOLDERS:
                return stored
        except Exception as exc:
            if logger:
                logger.warning("welcome stored name lookup failed user=%s err=%s", uid[:8], exc)
    return None


def record_checkin(data_file, payload=None):
    payload = payload or {}
    state = load_state(data_file)
    profile = get_profile(state, payload.get("line_user_id"))
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    history = set(profile.get("history") or [])
    already_checked = today in history
    if not already_checked:
        history.add(today)
        profile["history"] = sorted(history)
    profile["last_check_in"] = now.isoformat(timespec="seconds")
    profile["last_warning_cancelled_at"] = None
    save_state(data_file, state)
    status = build_status(profile)
    status["already_checked_today"] = already_checked
    status["is_duplicate"] = already_checked
    return status


def cancel_warning(data_file, payload=None, config=None):
    payload = payload or {}
    state = load_state(data_file)
    profile = get_profile(state, payload.get("line_user_id"))
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    history = set(profile.get("history") or [])
    history.add(today)
    profile["history"] = sorted(history)
    profile["last_check_in"] = now.isoformat(timespec="seconds")
    profile["last_warning_cancelled_at"] = now.isoformat(timespec="seconds")
    if config:
        token = config.get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
        sender = config.get("LINE_PUSH_SENDER") or line_push_message
        if token:
            message = f"{profile.get('display_name') or '使用者'} 已取消本次平安預警，本次為誤觸，請不用擔心。"
            for contact in (profile.get("contacts") or [])[: plan_rules(profile)["contact_limit"]]:
                methods = contact.get("notify_methods") or ["line"]
                if "line" not in methods or not contact.get("line_id"):
                    continue
                try:
                    result = sender(token, contact["line_id"], message)
                    append_notification_log(state, "warning_cancelled", contact["line_id"], "sent", message, json.dumps(result, ensure_ascii=False))
                except Exception as exc:
                    append_notification_log(state, "warning_cancelled", contact["line_id"], "failed", message, str(exc))
    save_state(data_file, state)
    return build_status(profile)


def normalized_alert_channels(payload_value):
    allowed = {"line", "sms", "phone"}
    channels = payload_value or ["line"]
    if isinstance(channels, str):
        channels = [channels]
    selected = [channel for channel in channels if channel in allowed]
    return selected or ["line"]


def save_settings_for_profile(data_file, payload):
    state = load_state(data_file)
    profile = get_profile(state, payload.get("line_user_id"))
    profile["contact_email"] = str(payload.get("contact_email", "")).strip()
    profile["grace_hours"] = max(1, min(168, int(payload.get("grace_hours") or 36)))
    if "reminder_times" in payload:
        apply_reminder_times_to_profile(profile, times=payload.get("reminder_times"))
    elif "reminder_time" in payload:
        apply_reminder_times_to_profile(profile, single=payload.get("reminder_time"))
    checkin_mode = str(payload.get("checkin_mode") or profile.get("checkin_mode") or "manual")
    profile["checkin_mode"] = checkin_mode if checkin_mode in {"manual", "voice", "auto_open"} else "manual"
    profile["auto_checkin_on_open"] = bool(payload.get("auto_checkin_on_open", False))
    profile["warning_cancel_minutes"] = max(1, min(60, int(payload.get("warning_cancel_minutes") or 15)))
    profile["alert_channels"] = normalized_alert_channels(payload.get("alert_channels"))
    profile["attach_location_on_alert"] = bool(payload.get("attach_location_on_alert", False))
    if "contact_capacity_reminder_enabled" in payload:
        profile["contact_capacity_reminder_enabled"] = bool(payload.get("contact_capacity_reminder_enabled"))
    if "guardian_details_reminder_enabled" in payload:
        profile["guardian_details_reminder_enabled"] = bool(payload.get("guardian_details_reminder_enabled"))
    save_state(data_file, state)
    return build_status(profile)


def save_billing_preferences(data_file, payload):
    line_user_id = str(payload.get("line_user_id") or "").strip()
    if not line_user_id:
        return {"error": "missing line_user_id"}, 400
    state = load_state(data_file)
    profile = get_profile(state, line_user_id)
    requested = bool(payload.get("auto_renew_requested", False))
    profile["auto_renew_requested"] = requested
    if requested:
        profile["auto_renew_status"] = "active" if profile.get("auto_renew_enabled") else "pending_gateway"
    elif profile.get("auto_renew_enabled"):
        profile["auto_renew_status"] = "cancellation_pending"
    else:
        profile["auto_renew_status"] = "off"
    save_state(data_file, state)
    return build_status(profile), 200


def create_payment_order(data_file, payload, config=None):
    line_user_id = str(payload.get("line_user_id") or "").strip()
    plan = str(payload.get("plan") or "").strip()
    product = PAYMENT_PRODUCTS.get(plan)
    if not line_user_id:
        return {"error": "missing line_user_id"}, 400
    if not product:
        return {"error": "unknown payment plan"}, 400

    state = load_state(data_file)
    profile = get_profile(state, line_user_id)
    now = current_app_time(config or {})
    order = {
        "order_id": f"AC{now.strftime('%Y%m%d%H%M%S')}{secrets.token_hex(3).upper()}",
        "line_user_id": line_user_id,
        "display_name": profile.get("display_name") or "LINE 會員",
        "plan": plan,
        "amount": product["amount"],
        "currency": "TWD",
        "billing_cycle": product["billing_cycle"],
        "provider": "newebpay",
        "status": "pending",
        "created_at": now.isoformat(timespec="seconds"),
        "paid_at": "",
        "transaction_id": "",
    }
    state.setdefault("orders", []).append(order)
    save_state(data_file, state)
    checkout = None
    if newebpay is not None:
        checkout = newebpay.build_checkout(order, config or {})
    else:
        checkout = {
            "mode": "manual",
            "mpg_url": None,
            "form": None,
            "message": "藍新模組未載入；訂單已建立，請後台人工確認。",
        }
    return {"order": order, "checkout": checkout}, 201


def confirm_payment_order(data_file, payload, config=None):
    order_id = str(payload.get("order_id") or "").strip()
    if not order_id:
        return {"error": "missing order_id"}, 400

    state = load_state(data_file)
    order = next((item for item in state.setdefault("orders", []) if item.get("order_id") == order_id), None)
    if not order:
        return {"error": "order not found"}, 404
    profile = get_profile(state, order.get("line_user_id"))
    if order.get("status") == "paid":
        return {"order": order, "member": build_status(profile), "already_confirmed": True}, 200

    product = PAYMENT_PRODUCTS.get(order.get("plan"))
    if not product:
        return {"error": "unknown payment plan"}, 400
    now = current_app_time(config or {})
    current_until = parse_datetime(profile.get("paid_until"))
    start_at = current_until if current_until and current_until > now else now
    paid_until = start_at + timedelta(days=product["duration_days"])

    order["status"] = "paid"
    order["paid_at"] = now.isoformat(timespec="seconds")
    order["transaction_id"] = str(payload.get("transaction_id") or "").strip()
    profile["plan"] = order["plan"]
    profile["payment_status"] = "active"
    profile["paid_until"] = paid_until.isoformat(timespec="seconds")
    profile["billing_cycle"] = product["billing_cycle"]
    profile["payment_provider"] = "newebpay"
    profile["payment_method_last4"] = str(payload.get("payment_method_last4") or "").strip()[-4:]
    profile["next_billing_date"] = profile["paid_until"]
    profile["renewal_reminder_sent_for"] = ""
    if payload.get("auto_renew_enabled") is not None:
        profile["auto_renew_enabled"] = bool(payload.get("auto_renew_enabled"))
        profile["auto_renew_status"] = "active" if profile["auto_renew_enabled"] else "off"
    save_state(data_file, state)
    return {"order": order, "member": build_status(profile), "already_confirmed": False}, 200


def apply_expired_plan_downgrades(config):
    """Downgrade paid members whose paid_until has passed.

    若 paid_until 為空（後台剛改方案尚未寫到期日），不要當成過期清掉方案。
    降級只改 plan／付款欄位，绝不清空 contacts／friends／guardian_group_ids。
    """
    data_file = config["DATA_FILE"]
    state = load_state(data_file)
    now = current_app_time(config)
    downgraded = []
    for profile in state.get("users", {}).values():
        plan = str(profile.get("plan") or "")
        if not plan.startswith("paid_"):
            continue
        paid_until = parse_datetime(profile.get("paid_until"))
        if not paid_until:
            # 無到期日：保留現況，避免誤降級並讓使用者以為好友被清掉
            continue
        if paid_until >= now:
            continue
        # 已過期：只降方案，保留所有綁定
        preserved_contacts = list(profile.get("contacts") or [])
        preserved_friends = list(profile.get("friends") or [])
        preserved_groups = list(profile.get("guardian_group_ids") or [])
        if profile.get("payment_status") == "active" or paid_until:
            profile["plan"] = "free"
            profile["payment_status"] = "expired"
            profile["billing_cycle"] = ""
            profile["auto_renew_enabled"] = False
            profile["auto_renew_status"] = "off"
            profile["next_billing_date"] = ""
            profile["contacts"] = preserved_contacts
            profile["friends"] = preserved_friends
            profile["guardian_group_ids"] = preserved_groups
            downgraded.append(profile.get("line_user_id"))
            append_notification_log(
                state,
                "plan_expired",
                profile.get("line_user_id"),
                "downgraded",
                f"plan expired -> free (was {plan}); contacts kept={len(preserved_contacts)}",
            )
    if downgraded:
        save_state(data_file, state)
    return {"downgraded": len(downgraded), "line_user_ids": downgraded}, 200


def send_renewal_reminders(config):
    token = config.get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        return {"sent": 0, "skipped": 0, "error": "LINE_CHANNEL_ACCESS_TOKEN is not set"}, 400

    state = load_state(config["DATA_FILE"])
    sender = config.get("LINE_PUSH_SENDER") or line_push_message
    now = current_app_time(config)
    sent = 0
    skipped = 0
    for profile in state.get("users", {}).values():
        if profile.get("payment_status") != "active":
            continue
        paid_until_text = str(profile.get("paid_until") or "").strip()
        paid_until = parse_datetime(paid_until_text)
        if not paid_until:
            continue
        days_left = (paid_until.date() - now.date()).days
        if days_left < 0 or days_left > 7:
            continue
        if profile.get("renewal_reminder_sent_for") == paid_until_text:
            skipped += 1
            continue
        if profile.get("auto_renew_enabled"):
            message = f"你的守護方案將在 {days_left} 天後續扣。若付款方式有異動，記得先到會員中心確認。"
        else:
            message = f"你的守護方案即將到期，還剩 {days_left} 天。可到會員中心查看方案並續費，避免守護提醒中斷。"
        try:
            sender(token, profile.get("line_user_id"), message)
            profile["renewal_reminder_sent_for"] = paid_until_text
            append_notification_log(state, "renewal", profile.get("line_user_id"), "sent", message)
            sent += 1
        except Exception as exc:
            append_notification_log(state, "renewal", profile.get("line_user_id"), "failed", message, str(exc))
    save_state(config["DATA_FILE"], state)
    return {"sent": sent, "skipped": skipped}, 200


def normalize_contact(contact, index):
    """正規化守護人聯絡人資料,包含穩定 id 與時間戳。

    規則:
    - id 一旦建立就不變(沒給就用 f"contact-{index+1}")
    - is_primary 從 contact.get("is_primary") 讀,沒給就看 priority 是否 = 1
    - binding_status: unbound / pending / accepted / declined
    - line_user_id 跟 line_id 同義(新欄位優先)
    - created_at 與 updated_at 為 ISO 8601 字串
    """
    methods = contact.get("notify_methods") or contact.get("methods") or ["line"]
    if isinstance(methods, str):
        methods = [methods]
    contact_id = str(contact.get("id") or f"contact-{index + 1}")
    priority = int(contact.get("priority") or index + 1)
    is_primary = bool(contact.get("is_primary", priority == 1))
    line_user_id = str(
        contact.get("line_user_id")
        or contact.get("line_id")
        or ""
    ).strip()
    return {
        "id": contact_id,
        "name": str(contact.get("name") or "").strip(),
        "relationship": str(contact.get("relationship") or "").strip(),
        "phone": str(contact.get("phone") or "").strip(),
        "email": str(contact.get("email") or "").strip(),
        "line_user_id": line_user_id,
        "binding_status": str(contact.get("binding_status") or ("accepted" if line_user_id else "unbound")),
        "is_primary": is_primary,
        "notify_methods": methods,
        "priority": priority,
        "consent_status": str(contact.get("consent_status") or "pending"),
        "available_time": str(contact.get("available_time") or "").strip(),
        "note": str(contact.get("note") or "").strip(),
        "created_at": str(contact.get("created_at") or ""),
        "updated_at": str(contact.get("updated_at") or ""),
    }


def validate_contact_payload(contact, existing=None, contact_limit=10):
    """驗證單筆 contact payload。回傳 (ok, errors_list, cleaned_contact_or_None)。

    規則:
    - name 必填
    - relationship 必填
    - phone OR email 至少一個
    - phone 格式基本驗證(台灣手機 09 開頭或國際格式)
    - email 格式基本驗證
    - 不允許完全重複(同 user 既有 contacts 比對 name+phone+email)
    - 超過方案上限 → contact_limit_exceeded
    """
    import re
    name = str(contact.get("name") or "").strip()
    relationship = str(contact.get("relationship") or "").strip()
    phone = str(contact.get("phone") or "").strip()
    email = str(contact.get("email") or "").strip()

    errors = []
    if not name:
        errors.append("name_required")
    if not relationship:
        errors.append("relationship_required")
    if not phone and not email:
        errors.append("phone_or_email_required")

    # phone format: 接受 09xxxxxxxx(台灣)、9xxxxxxxx(去 0)、+8869xxxxxxxx、8869xxxxxxxx
    if phone:
        digits = re.sub(r"\D", "", phone.lstrip("+"))
        if digits.startswith("0"):
            digits = digits[1:]
        if digits.startswith("886"):
            digits = digits[3:]
        if not re.match(r"^9\d{8}$", digits):
            errors.append("phone_format_invalid")

    # email format
    if email:
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            errors.append("email_format_invalid")

    # duplicate check (排除自己 by id)
    if existing and not errors:
        contact_id = str(contact.get("id") or "")
        for c in existing:
            if str(c.get("id") or "") == contact_id:
                continue
            same_name = c.get("name") == name
            same_phone = c.get("phone") == phone and phone
            same_email = c.get("email") == email and email
            if same_name and (same_phone or same_email):
                errors.append("duplicate_contact")
                break

    if errors:
        return False, errors, None

    cleaned = {
        "name": name,
        "relationship": relationship,
        "phone": phone,
        "email": email,
        "line_user_id": str(contact.get("line_user_id") or "").strip(),
        "binding_status": str(contact.get("binding_status") or "unbound"),
        "is_primary": bool(contact.get("is_primary", False)),
        "notify_methods": contact.get("notify_methods") or ["line"],
        "available_time": str(contact.get("available_time") or "").strip(),
        "note": str(contact.get("note") or "").strip(),
    }
    return True, [], cleaned


def iso_now():
    """回傳當下時間的 ISO 8601 字串(Asia/Taipei)。"""
    from datetime import datetime, timezone, timedelta
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def complete_guardian_contact(contact):
    return bool(
        str(contact.get("name") or "").strip()
        and str(contact.get("relationship") or "").strip()
        and str(contact.get("phone") or "").strip()
        and (str(contact.get("line_id") or "").strip() or contact.get("consent_status") == "accepted")
    )


def get_contacts(data_file, line_user_id=None):
    state = load_state(data_file)
    profile = get_profile(state, line_user_id)
    return {
        "line_user_id": profile.get("line_user_id"),
        "contacts": profile.get("contacts", []),
        "contact_limit": plan_rules(profile)["contact_limit"],
        "plan": profile.get("plan", "trial"),
        "guardian_details_complete": any(complete_guardian_contact(contact) for contact in (profile.get("contacts") or [])),
        "guardian_details_reminder_enabled": bool(profile.get("guardian_details_reminder_enabled", True)),
    }


def add_single_contact(data_file, line_user_id, contact_payload):
    """新增單一聯絡人,回傳 (status_code, response_dict)。"""
    state = load_state(data_file)
    profile = state.get("users", {}).get(line_user_id)
    if not profile:
        return {"error": "user not registered", "line_user_id": line_user_id}, 404
    existing = profile.get("contacts") or []
    limit = plan_rules(profile)["contact_limit"]
    if len(existing) >= limit:
        return {
            "error": "contact_limit_exceeded",
            "contact_limit": limit,
            "current_count": len(existing),
            "message": f"目前方案最多 {limit} 位聯絡人,請升級方案或刪除現有聯絡人"
        }, 400
    ok, errors, cleaned = validate_contact_payload(contact_payload, existing=existing)
    if not ok:
        return {"error": "validation_failed", "fields": errors}, 400
    now = iso_now()
    # generate new id
    used_ids = {str(c.get("id") or "") for c in existing}
    new_id = f"contact-{len(existing) + 1}"
    suffix = 1
    while new_id in used_ids:
        suffix += 1
        new_id = f"contact-{len(existing) + suffix}"
    cleaned["id"] = new_id
    cleaned["created_at"] = now
    cleaned["updated_at"] = now
    # primary 邏輯:設為主要時自動取消其他
    if cleaned["is_primary"]:
        for c in existing:
            c["is_primary"] = False
            c["updated_at"] = now
    existing.append(cleaned)
    profile["contacts"] = existing
    save_state(data_file, state)
    return {"contact": cleaned, "contacts": existing, "contact_limit": limit}, 200


def update_single_contact(data_file, line_user_id, contact_id, contact_payload):
    """更新單一聯絡人,回傳 (status_code, response_dict)。"""
    state = load_state(data_file)
    profile = state.get("users", {}).get(line_user_id)
    if not profile:
        return {"error": "user not registered", "line_user_id": line_user_id}, 404
    existing = profile.get("contacts") or []
    idx = None
    for i, c in enumerate(existing):
        if str(c.get("id") or "") == contact_id:
            idx = i
            break
    if idx is None:
        return {"error": "contact_not_found", "contact_id": contact_id}, 404
    # 合併:保留 id 跟 created_at,其他從 payload
    merged_payload = dict(contact_payload)
    merged_payload["id"] = contact_id
    merged_payload["created_at"] = existing[idx].get("created_at") or iso_now()
    # 驗證(排除自己)
    other = [c for i, c in enumerate(existing) if i != idx]
    ok, errors, cleaned = validate_contact_payload(merged_payload, existing=other)
    if not ok:
        return {"error": "validation_failed", "fields": errors}, 400
    now = iso_now()
    cleaned["id"] = contact_id
    cleaned["created_at"] = merged_payload["created_at"]
    cleaned["updated_at"] = now
    # primary 邏輯
    if cleaned["is_primary"]:
        for i, c in enumerate(existing):
            if i != idx:
                c["is_primary"] = False
                c["updated_at"] = now
    existing[idx] = cleaned
    profile["contacts"] = existing
    save_state(data_file, state)
    return {"contact": cleaned, "contacts": existing}, 200


def delete_single_contact(data_file, line_user_id, contact_id):
    """刪除單一聯絡人,回傳 (status_code, response_dict)。"""
    state = load_state(data_file)
    profile = state.get("users", {}).get(line_user_id)
    if not profile:
        return {"error": "user not registered", "line_user_id": line_user_id}, 404
    existing = profile.get("contacts") or []
    new_contacts = [c for c in existing if str(c.get("id") or "") != contact_id]
    if len(new_contacts) == len(existing):
        return {"error": "contact_not_found", "contact_id": contact_id}, 404
    profile["contacts"] = new_contacts
    save_state(data_file, state)
    return {"deleted": True, "contact_id": contact_id, "contacts": new_contacts}, 200




def save_contacts(data_file, payload):
    state = load_state(data_file)
    profile = get_profile(state, payload.get("line_user_id"))
    contacts = [normalize_contact(contact, index) for index, contact in enumerate(payload.get("contacts") or [])]
    contacts.sort(key=lambda contact: contact.get("priority", 9999))
    for index, contact in enumerate(contacts):
        contact["priority"] = index + 1
    limit = plan_rules(profile)["contact_limit"]
    if len(contacts) > limit:
        return {"error": f"contact_limit exceeded: {limit}", "contact_limit": limit}, 400
    if payload.get("require_complete_guardian") and profile.get("plan") in {"paid_799", "paid_799_year"}:
        if not any(complete_guardian_contact(contact) for contact in contacts):
            return {
                "error": "799 plan requires at least one bound guardian with name, relationship and phone",
                "required_fields": ["name", "relationship", "phone"],
            }, 400
    profile["contacts"] = contacts
    save_state(data_file, state)
    return get_contacts(data_file, payload.get("line_user_id")), 200


def bind_emergency_contact(data_file, payload, config=None):
    inviter_id = str(payload.get("inviter_line_user_id") or "").strip()
    contact_line_user_id = str(payload.get("contact_line_user_id") or "").strip()
    contact_display_name = str(payload.get("contact_display_name") or "LINE 聯絡人").strip()
    if not inviter_id or not contact_line_user_id:
        return {"error": "missing inviter_line_user_id or contact_line_user_id"}, 400
    if inviter_id == contact_line_user_id:
        return {"error": "cannot bind yourself"}, 400

    state = load_state(data_file)
    inviter = get_profile(state, inviter_id)
    contact_user = get_profile(state, contact_line_user_id)
    contact_user["display_name"] = contact_display_name or contact_user.get("display_name") or "LINE 聯絡人"

    contacts = list(inviter.get("contacts") or [])
    existing = next((contact for contact in contacts if contact.get("line_id") == contact_line_user_id), None)
    already_bound = bool(existing)
    already_accepted = bool(
        existing
        and (
            existing.get("consent_status") == "accepted"
            or existing.get("binding_status") == "accepted"
        )
    )

    # LIFF 點擊授權即視為守護人本人同意綁定（不需再回「同意」）
    if existing:
        existing["name"] = existing.get("name") or contact_display_name or "LINE 聯絡人"
        existing["line_id"] = contact_line_user_id
        existing["consent_status"] = "accepted"
        existing["binding_status"] = "accepted"
        existing["accepted_at"] = datetime.now().isoformat(timespec="seconds")
        existing["notify_methods"] = list(dict.fromkeys([*(existing.get("notify_methods") or []), "line"]))
    else:
        limit = plan_rules(inviter)["contact_limit"]
        if len(contacts) >= limit:
            return {"error": f"contact_limit exceeded: {limit}", "contact_limit": limit}, 400
        contacts.append(
            {
                "id": f"line-{contact_line_user_id}",
                "name": contact_display_name or "LINE 聯絡人",
                "relationship": "受邀緊急聯絡人",
                "phone": "",
                "line_id": contact_line_user_id,
                "email": "",
                "available_time": "",
                "notify_methods": ["line"],
                "priority": len(contacts) + 1,
                "consent_status": "accepted",
                "binding_status": "accepted",
                "accepted_at": datetime.now().isoformat(timespec="seconds"),
                "note": "LINE 一鍵授權綁定",
            }
        )
        inviter["contacts"] = contacts

    rewards = state.setdefault("contact_rewards", [])
    reward = next((item for item in rewards if item.get("inviter_line_user_id") == inviter_id), None)
    if not reward:
        reward = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "inviter_line_user_id": inviter_id,
            "contact_line_user_id": contact_line_user_id,
            "status": "available",
            "reward_options": ["trial_7_days", "extra_contact_30_days"],
            "selected_reward": "",
        }
        rewards.append(reward)

    sent = 0
    if config and not already_accepted:
        token = config.get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
        sender = config.get("LINE_PUSH_SENDER") or line_push_message
        if token:
            inviter_name = inviter.get("display_name") or "使用者"
            guardian_name = contact_display_name or "守護人"
            inviter_notice = (
                f"✅ 綁定完成\n\n"
                f"{guardian_name} 已成為你的守護人。\n"
                f"之後若你未準時報平安或發出 SOS，系統會通知對方。"
            )
            guardian_notice = (
                f"✅ 綁定完成\n\n"
                f"你已成為 {inviter_name} 的守護人。\n"
                f"對方未準時報平安或緊急求助時，你會收到 LINE 通知。"
            )
            messages = [
                (inviter_id, inviter_notice),
                (contact_line_user_id, guardian_notice),
            ]
            for line_user_id, message in messages:
                try:
                    result = sender(token, line_user_id, message)
                    append_notification_log(
                        state,
                        "binding_complete",
                        line_user_id,
                        "sent",
                        message,
                        json.dumps(result, ensure_ascii=False),
                    )
                    sent += 1
                except Exception as exc:
                    append_notification_log(state, "binding_complete", line_user_id, "failed", message, str(exc))

    save_state(data_file, state)
    return {
        "bound": True,
        "already_bound": already_bound,
        "binding_complete": not already_accepted,
        "contact": next((contact for contact in contacts if contact.get("line_id") == contact_line_user_id), None),
        "reward": reward,
        "consent_request_sent": sent,
        "test_messages_sent": sent,  # 向下相容
        "inviter_notified": sent > 0,
    }, 200


def paid_membership_is_active(profile):
    if profile.get("payment_status") != "active":
        return False
    paid_until = str(profile.get("paid_until") or "").strip()
    if not paid_until:
        return True
    expires_at = parse_datetime(paid_until)
    return bool(expires_at and expires_at >= datetime.now())


# ============================================================
# 2026-07-20 蝦董 added: 守護群 50 人上限 + evict 邏輯
# ============================================================
GROUP_MEMBER_LIMIT = 50


def get_group_member_count(token, group_id):
    """呼叫 LINE API 查 group 成員數。失敗回 None(不擋,只 log warn)。"""
    if not token or not group_id:
        return None
    url = f"https://api.line.me/v2/bot/group/{group_id}/members/count"
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=5) as r:
            body = json.loads(r.read().decode("utf-8"))
            return int(body.get("count", 0))
    except Exception:
        return None


def get_group_member_ids(token, group_id, max_count=200):
    """呼叫 LINE API 拿 group 成員 userIds。失敗回 None。"""
    if not token or not group_id:
        return None
    url = f"https://api.line.me/v2/bot/group/{group_id}/members/ids?limit={max_count}"
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=8) as r:
            body = json.loads(r.read().decode("utf-8"))
            return list(body.get("memberIds") or [])
    except Exception:
        return None


def kick_group_member(token, group_id, user_id):
    """踢 userId 出 group(bot 必須是 admin)。失敗:回 None / HTTPError code。"""
    if not token or not group_id or not user_id:
        return None
    url = f"https://api.line.me/v2/bot/group/{group_id}/member/{user_id}/leave"
    try:
        req = urllib.request.Request(url, method="POST", headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:
        return None


def enforce_group_member_limit(group_id, config=None, simulated_new_ids=None):
    """超 50 人時 evict 新成員(用 bind 時的 member snapshot 對比)。"""
    state_path = (config or {}).get("DATA_FILE") if config else None
    state_path = state_path or os.environ.get("DATA_FILE")
    if not state_path:
        return {"error": "no DATA_FILE"}, 500
    state = load_state(state_path)
    group_info = state.get("guardian_groups", {}).get(group_id)
    if not group_info:
        return {"error": "not bound", "group_id": group_id}, 404
    if group_info.get("status") != "active":
        return {"error": "group inactive"}, 409
    token = (config or {}).get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        return {"error": "no token"}, 503
    current_count = get_group_member_count(token, group_id)
    if current_count is None:
        return {"error": "API fail to read count"}, 502
    if current_count <= GROUP_MEMBER_LIMIT:
        return {"ok": True, "enforced": False, "current_count": current_count,
                "limit": GROUP_MEMBER_LIMIT, "kicked": [], "failed": [],
                "group_id": group_id}, 200
    bind_ids = set(group_info.get("member_ids_at_bind") or [])
    if simulated_new_ids is not None:
        candidate_ids = list(simulated_new_ids)
        current_ids = None
    else:
        candidate_ids = []
        current_ids = get_group_member_ids(token, group_id)
        if current_ids is None:
            return {"error": "API fail to read member ids"}, 502
        candidate_ids = [uid for uid in current_ids if uid not in bind_ids]
    if not candidate_ids:
        return {"ok": True, "enforced": False, "current_count": current_count,
                "limit": GROUP_MEMBER_LIMIT, "kicked": [], "failed": [],
                "note": "no new joiners to kick", "group_id": group_id}, 200
    overflow = current_count - GROUP_MEMBER_LIMIT
    to_kick = candidate_ids[:overflow] if overflow > 0 else candidate_ids[:1]
    if not to_kick and candidate_ids:
        to_kick = candidate_ids[:1]
    kicked, failed, failed_403 = [], [], []
    for uid in to_kick:
        if simulated_new_ids is not None:
            kicked.append(uid)
            continue
        status = kick_group_member(token, group_id, uid)
        if isinstance(status, int) and 200 <= status < 300:
            kicked.append(uid)
        else:
            failed.append(uid)
            if status == 403:
                failed_403.append(uid)
    return {"ok": True, "enforced": True, "current_count": current_count,
            "limit": GROUP_MEMBER_LIMIT, "overflow": overflow,
            "candidate_count": len(candidate_ids), "kicked": kicked,
            "failed": failed, "bot_not_admin_count": len(failed_403),
            "simulated": simulated_new_ids is not None,
            "group_id": group_id}, 200


def bind_guardian_group(data_file, payload):
    line_user_id = str(payload.get("line_user_id") or "").strip()
    group_id = str(payload.get("group_id") or "").strip()
    if not line_user_id or not group_id:
        return {"error": "missing line_user_id or group_id", "should_leave": True}, 400

    state = load_state(data_file)
    profile = get_profile(state, line_user_id)
    groups = state.setdefault("guardian_groups", {})
    existing_group = groups.get(group_id)
    if existing_group:
        if existing_group.get("owner_line_user_id") == line_user_id:
            return {
                "bound": True,
                "already_bound": True,
                "group_id": group_id,
                "guardian_group_limit": plan_rules(profile).get("guardian_group_limit", 0),
                "should_leave": False,
            }, 200
        return {
            "error": "group is already bound to another member",
            "should_leave": False,
        }, 409

    eligible = profile.get("plan") in {"paid_799", "paid_799_year"} and paid_membership_is_active(profile)
    if not eligible:
        return {
            "error": "guardian groups require an active paid_799 membership",
            "required_plan": "paid_799",
            "should_leave": True,
        }, 403

    group_ids = list(dict.fromkeys(profile.get("guardian_group_ids") or []))
    group_limit = plan_rules(profile).get("guardian_group_limit", 0)
    if len(group_ids) >= group_limit:
        return {
            "error": f"guardian_group_limit exceeded: {group_limit}",
            "guardian_group_limit": group_limit,
            "should_leave": True,
        }, 409

    # 50 人/群 驗證(若 token 提供)
    member_count_at_bind = None
    member_ids_at_bind = None
    if isinstance(data_file, dict) or True:
        token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
        if token:
            mc = get_group_member_count(token, group_id)
            if mc is not None and mc > GROUP_MEMBER_LIMIT:
                return {
                    "error": f"group_size_exceeds_{GROUP_MEMBER_LIMIT}",
                    "member_count": mc,
                    "limit": GROUP_MEMBER_LIMIT,
                    "should_leave": True,
                    "reply_text": (
                        f"此群目前有 {mc} 位成員(不含「每日平安」)。\n"
                        f"守護群上限 {GROUP_MEMBER_LIMIT} 人,請把群縮到 {GROUP_MEMBER_LIMIT} 人內再重新邀請「每日平安」。"
                    ),
                }, 413
            member_count_at_bind = mc
            if mc is not None:
                member_ids_at_bind = get_group_member_ids(token, group_id)

    now = datetime.now().isoformat(timespec="seconds")
    groups[group_id] = {
        "group_id": group_id,
        "owner_line_user_id": line_user_id,
        "status": "active",
        "created_at": now,
        "member_count_at_bind": member_count_at_bind,
        "member_ids_at_bind": member_ids_at_bind,
        "preferences": {
            "notify_private_guardians": True,
            "notify_group_on_overdue": True,
            "notify_admin_only": True,
            "daily_admin_summary": True,
        },
    }
    group_ids.append(group_id)
    profile["guardian_group_ids"] = group_ids
    save_state(data_file, state)
    return {
        "bound": True,
        "already_bound": False,
        "group_id": group_id,
        "guardian_group_count": len(group_ids),
        "guardian_group_limit": group_limit,
        "should_leave": False,
    }, 200


def update_guardian_group_preferences(data_file, payload):
    line_user_id = str(payload.get("line_user_id") or "").strip()
    group_id = str(payload.get("group_id") or "").strip()
    if not line_user_id or not group_id:
        return {"error": "missing line_user_id or group_id"}, 400

    state = load_state(data_file)
    group = state.get("guardian_groups", {}).get(group_id)
    if not group:
        return {"error": "guardian group not found"}, 404
    if group.get("owner_line_user_id") != line_user_id:
        return {"error": "not guardian group owner"}, 403

    preferences = group.setdefault("preferences", {})
    for key in ("notify_private_guardians", "notify_group_on_overdue", "notify_admin_only", "daily_admin_summary"):
        if key in payload:
            preferences[key] = bool(payload.get(key))
    save_state(data_file, state)
    return {"ok": True, "group_id": group_id, "preferences": preferences}, 200


def guardian_group_daily_status_text(data_file, line_user_id, group_id):
    if not line_user_id or not group_id:
        return "目前無法確認你的身分，請稍後再試。", 400

    state = load_state(data_file)
    group = state.get("guardian_groups", {}).get(group_id)
    if not group or group.get("status") != "active":
        return "此群尚未完成守護群綁定。請由有效的 799 會員在群裡輸入「點我綁定守護群」。", 404
    prefs = group.get("preferences") or {}
    if prefs.get("notify_admin_only", True) and group.get("owner_line_user_id") != line_user_id:
        return "為了保護成員隱私，今日平安名單只有守護群管理員可以查看。", 403

    users = state.get("users", {}) or {}
    member_ids = [group.get("owner_line_user_id")]
    for uid in group.get("member_ids_at_bind") or []:
        if uid not in member_ids and uid in users:
            member_ids.append(uid)
    today = datetime.now().strftime("%Y-%m-%d")
    checked = []
    unchecked = []
    for uid in member_ids:
        profile = users.get(uid) or {}
        name = profile.get("display_name") or profile.get("name") or "LINE 成員"
        history = profile.get("history") or []
        is_checked = today in history or any(str(item.get("date", "")) == today for item in history if isinstance(item, dict))
        (checked if is_checked else unchecked).append(name)

    lines = [
        "📊 今日平安狀態",
        f"已報平安：{', '.join(checked) if checked else '尚無'}",
        f"尚未報平安：{', '.join(unchecked) if unchecked else '目前都已完成'}",
        "",
        "群組隱私設定：",
        f"群內逾期提醒：{'開啟' if prefs.get('notify_group_on_overdue', True) else '關閉'}",
        f"詳細名單：{'僅管理員可看' if prefs.get('notify_admin_only', True) else '群內可看'}",
        f"核心守護人私訊：{'開啟' if prefs.get('notify_private_guardians', True) else '關閉'}",
    ]
    return "\n".join(lines), 200


def guardian_group_join_outcome(data_file, line_user_id, group_id):
    if not line_user_id or not group_id:
        return {
            "reply_text": (
                "目前無法確認邀請人的會員身分，因此不能啟用守護群。\n"
                "請由有效的 799 守護版會員重新邀請我加入；我會先退出這個群組。"
            ),
            "should_leave": True,
        }, 400

    result, status = bind_guardian_group(
        data_file,
        {"line_user_id": line_user_id, "group_id": group_id},
    )
    outcome = dict(result)
    if status == 200:
        outcome["reply_text"] = (
            "我已完成守護群設定\n"
            f"目前已綁定 {result.get('guardian_group_count', 1)}/"
            f"{result.get('guardian_group_limit', 1)} 個守護群。"
        )
    elif result.get("should_leave"):
        outcome["reply_text"] = (
            "這個群組目前無法啟用守護功能。守護群只開放給有效的 799 守護版會員；"
            "月費最多 1 群，年費最多 3 群。\n"
            "我會先退出群組，完成升級後再重新邀請即可。"
        )
    else:
        outcome["reply_text"] = "這個群組已綁定其他會員，請由原建立者管理守護設定。"
    return outcome, status


def unbind_guardian_group(data_file, payload):
    line_user_id = str(payload.get("line_user_id") or "").strip()
    group_id = str(payload.get("group_id") or "").strip()
    if not line_user_id or not group_id:
        return {"error": "missing line_user_id or group_id"}, 400

    state = load_state(data_file)
    profile = state.get("users", {}).get(line_user_id)
    group = state.get("guardian_groups", {}).get(group_id)
    if not profile or not group:
        return {"error": "guardian group not found"}, 404
    if group.get("owner_line_user_id") != line_user_id:
        return {"error": "not guardian group owner"}, 403

    state.setdefault("guardian_groups", {}).pop(group_id, None)
    profile["guardian_group_ids"] = [
        saved_id for saved_id in (profile.get("guardian_group_ids") or []) if saved_id != group_id
    ]
    save_state(data_file, state)
    return {
        "unbound": True,
        "group_id": group_id,
        "guardian_group_ids": profile["guardian_group_ids"],
    }, 200


def create_friend_invite(data_file, payload):
    """產生好友邀請碼。回傳包含 invite_code / invite_url / status / expires_at / inviter / invited_guardian。"""
    line_user_id = str(payload.get("line_user_id") or "").strip()
    if not line_user_id:
        return {"error": "missing line_user_id"}, 400
    state = load_state(data_file)
    profile = get_profile(state, line_user_id)
    if not profile:
        return {"error": "user not registered", "line_user_id": line_user_id}, 404
    code = str(payload.get("invite_code") or secrets.token_urlsafe(5)).replace("-", "").replace("_", "")[:8].upper()
    now = datetime.now()
    expires_at = (now + timedelta(days=7)).isoformat(timespec="seconds")
    state.setdefault("friend_invites", {})[code] = {
        "line_user_id": line_user_id,
        "created_at": now.isoformat(timespec="seconds"),
        "expires_at": expires_at,
        "accepted_by": None,
        "accepted_at": None,
        "status": "pending",
    }
    save_state(data_file, state)
    # 邀約對象必須走永久 LIFF 入口；勿回傳 onrender 裸網址或含 OAuth code/state 的連結
    invite_url = permanent_liff_invite_url(friend_invite=code)
    return {
        "invite_code": code,
        "invite_url": invite_url,
        "status": "pending",
        "expires_at": expires_at,
        "inviter": {
            "line_user_id": line_user_id,
            "display_name": profile.get("display_name", "LINE 使用者"),
        },
        "invited_guardian": None,
    }, 200


def accept_friend_invite(data_file, payload):
    line_user_id = str(payload.get("line_user_id") or "").strip()
    invite_code = str(payload.get("invite_code") or "").strip().upper()
    if not line_user_id or not invite_code:
        return {"error": "missing line_user_id or invite_code"}, 400
    state = load_state(data_file)
    invite = state.get("friend_invites", {}).get(invite_code)
    if not invite:
        return {"error": "invite not found"}, 404
    inviter_id = invite.get("line_user_id")
    if inviter_id == line_user_id:
        return {"error": "cannot add yourself"}, 400

    user = get_profile(state, line_user_id)
    inviter = get_profile(state, inviter_id)
    user_friends = set(user.get("friends") or [])
    inviter_friends = set(inviter.get("friends") or [])
    user_limit = int(plan_rules(user).get("friend_location_limit", 1))
    inviter_limit = int(plan_rules(inviter).get("friend_location_limit", 1))
    if inviter_id not in user_friends and len(user_friends) >= user_limit:
        return {
            "error": f"friend_location_limit exceeded: {user_limit}",
            "friend_location_limit": user_limit,
        }, 400
    if line_user_id not in inviter_friends and len(inviter_friends) >= inviter_limit:
        return {
            "error": f"inviter friend_location_limit exceeded: {inviter_limit}",
            "friend_location_limit": inviter_limit,
        }, 400
    user["friends"] = sorted(user_friends | {inviter_id})
    inviter["friends"] = sorted(inviter_friends | {line_user_id})
    save_state(data_file, state)
    return {
        "ok": True,
        "friend": {
            "line_user_id": inviter_id,
            "display_name": inviter.get("display_name", "LINE 使用者"),
        },
    }, 200


def _parse_safety_guard_duration(payload):
    """Parse duration for 安全守護: 1h / 3h / 6h / until_stop. Returns (hours|None, until_stop)."""
    raw = payload.get("duration")
    if raw is None or raw == "":
        raw = payload.get("share_hours")
    text = str(raw or "").strip().lower().replace(" ", "")
    if text in ("until_stop", "until-stop", "untilstop", "stop", "manual"):
        return None, True
    try:
        hours = int(float(text.replace("h", "").replace("hr", "").replace("小時", "") or 0))
    except (TypeError, ValueError):
        hours = 0
    if hours in (1, 3, 6):
        return hours, False
    # Legacy callers may still send 24; clamp to allowed windows (no continuous trail).
    if hours > 0:
        if hours <= 1:
            return 1, False
        if hours <= 3:
            return 3, False
        return 6, False
    return 1, False


def _location_session_active(location, now=None):
    """True when 安全守護 session is active (sharing + not expired)."""
    location = location or {}
    if not location.get("sharing") and not location.get("active"):
        return False
    now = now or datetime.now()
    if location.get("until_stop"):
        return True
    expires_at = parse_datetime(location.get("expires_at"))
    return bool(expires_at and expires_at >= now)


def safety_guard_snapshot(profile, now=None):
    """Public snapshot of the user's 安全守護 session (single-shot location, not a trail)."""
    now = now or datetime.now()
    location = profile.get("location") or {}
    active = _location_session_active(location, now)
    today = now.date().isoformat()
    last_check_in = profile.get("last_check_in")
    is_today_checked = bool(last_check_in and str(last_check_in)[:10] == today)
    if is_today_checked:
        safety_status = "今日已簽到・狀態正常"
    elif last_check_in:
        safety_status = "今日尚未簽到"
    else:
        safety_status = "尚無簽到紀錄"
    return {
        "active": active,
        "sharing": active,
        "started_at": location.get("started_at") or "",
        "expires_at": location.get("expires_at") or "",
        "ended_at": location.get("ended_at") or "",
        "until_stop": bool(location.get("until_stop")),
        "duration_hours": location.get("duration_hours"),
        "latitude": location.get("latitude") if active else None,
        "longitude": location.get("longitude") if active else None,
        "city": location.get("city", "") if active else "",
        "updated_at": location.get("updated_at") or "",
        "mode": "safety_guard",
        "safety_status": safety_status,
        "is_today_checked": is_today_checked,
        "last_check_in": last_check_in,
    }


def update_location(data_file, payload):
    """Start or refresh 安全守護: one location snapshot within a timed session (not continuous track)."""
    line_user_id = str(payload.get("line_user_id") or "").strip()
    if not line_user_id:
        return {"error": "missing line_user_id"}, 400
    try:
        latitude = float(payload.get("latitude"))
        longitude = float(payload.get("longitude"))
    except (TypeError, ValueError):
        return {"error": "missing latitude or longitude"}, 400
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return {"error": "invalid location"}, 400

    now = datetime.now()
    state = load_state(data_file)
    profile = get_profile(state, line_user_id)
    existing = dict(profile.get("location") or {})
    refresh_only = bool(payload.get("refresh_only"))
    city = str(payload.get("city") or "").strip()

    if refresh_only:
        # Update last known coords; keep an active session as-is, do not invent a new share window.
        if _location_session_active(existing, now):
            existing.update(
                {
                    "latitude": round(latitude, 6),
                    "longitude": round(longitude, 6),
                    "city": city or existing.get("city", ""),
                    "updated_at": now.isoformat(timespec="seconds"),
                    "active": True,
                    "sharing": True,
                    "mode": "safety_guard",
                }
            )
            profile["location"] = existing
        else:
            profile["location"] = {
                **existing,
                "latitude": round(latitude, 6),
                "longitude": round(longitude, 6),
                "city": city or existing.get("city", ""),
                "updated_at": now.isoformat(timespec="seconds"),
                "sharing": False,
                "active": False,
                "mode": "safety_guard",
            }
        save_state(data_file, state)
        return {
            "ok": True,
            "location": profile["location"],
            "safety_guard": safety_guard_snapshot(profile, now),
        }, 200

    duration_hours, until_stop = _parse_safety_guard_duration(payload)
    started_at = (
        existing.get("started_at")
        if _location_session_active(existing, now)
        else now.isoformat(timespec="seconds")
    )
    if until_stop:
        expires_at = ""
    else:
        expires_at = (now + timedelta(hours=duration_hours)).isoformat(timespec="seconds")

    profile["location"] = {
        "latitude": round(latitude, 6),
        "longitude": round(longitude, 6),
        "city": city,
        "updated_at": now.isoformat(timespec="seconds"),
        "started_at": started_at,
        "expires_at": expires_at,
        "ended_at": "",
        "until_stop": until_stop,
        "duration_hours": duration_hours,
        "sharing": True,
        "active": True,
        "mode": "safety_guard",
    }
    save_state(data_file, state)
    return {
        "ok": True,
        "location": profile["location"],
        "safety_guard": safety_guard_snapshot(profile, now),
    }, 200


def stop_location_sharing(data_file, payload):
    """Stop 安全守護 immediately."""
    line_user_id = str(payload.get("line_user_id") or "").strip()
    if not line_user_id:
        return {"error": "missing line_user_id"}, 400
    state = load_state(data_file)
    profile = get_profile(state, line_user_id)
    now = datetime.now()
    location = dict(profile.get("location") or {})
    location["sharing"] = False
    location["active"] = False
    location["ended_at"] = now.isoformat(timespec="seconds")
    location["expires_at"] = now.isoformat(timespec="seconds")
    location["until_stop"] = False
    profile["location"] = location
    save_state(data_file, state)
    return {"ok": True, "safety_guard": safety_guard_snapshot(profile, now)}, 200


def sos_user_facing_error(err) -> str:
    """把 SOS API 內部英文錯誤轉成聊天室可讀中文（不露出技術字串、不用句號）。"""
    text = str(err or "").strip()
    lower = text.lower()
    if "no bound line guardians" in lower:
        return "還沒綁定守護人喔 先去邀請家人加入再試；有危險請先打 119 或 110"
    if "cooldown" in lower:
        return "剛剛已送過需要幫忙，請稍候再試；有危險請先打 119 或 110"
    if "daily sos limit" in lower or "daily limit" in lower:
        return "今天需要幫忙通知已達上限，請明天再試；有危險請先打 119 或 110"
    if "not available" in lower or "not active" in lower:
        return "目前暫時無法用系統通知家人；有危險請先打 119 或 110，並直接聯絡親友"
    if "member not found" in lower:
        return "還認不到你的會員資料，請先完成設定；有危險請先打 119 或 110"
    if "line_channel_access_token" in lower or "missing line_user_id" in lower:
        return "系統暫時無法送出通知，請稍後再試；有危險請先打 119 或 110"
    return "暫時通知不到家人，有危險請先打 119 或 110，並直接聯絡親友"


def trigger_sos(data_file, payload, config=None):
    """
    🔴 P0 FIX v0.5:加 3 層防護
    1. 每日上限 3 次(profile.sos_daily_count 累加,>3 拒絕)
    2. 5 分鐘冷卻(profile.last_sos_at + 300 秒內拒絕)
    3. 過量 alert:記錄 + admin 收到告警(但不發送 SOS)
    """
    line_user_id = str(payload.get("line_user_id") or "").strip()
    if not line_user_id:
        return {"error": "missing line_user_id"}, 400

    state = load_state(data_file)
    profile = state.get("users", {}).get(line_user_id)
    if not profile:
        return {"error": "member not found"}, 404

    # SOS 不依方案／價格分級：所有會員皆可用（仍受每日上限／冷卻防護）
    rules = plan_rules(profile)
    if not rules.get("sos_enabled", True):
        return {"error": "sos is not available for this plan"}, 403

    # === P0 FIX:3 層防護 ===
    now_dt = current_app_time(config or {})
    today_str = now_dt.strftime("%Y-%m-%d")

    # 防護 1:每日上限 3 次
    SOS_DAILY_LIMIT = 3
    sos_log = profile.get("sos_daily_log") or {}
    if sos_log.get("date") != today_str:
        sos_log = {"date": today_str, "count": 0}
    if sos_log.get("count", 0) >= SOS_DAILY_LIMIT:
        # 過量使用,記錄 + alert admin(但不發送)
        profile.setdefault("sos_abuse_log", []).append({
            "at": now_dt.isoformat(timespec="seconds"),
            "reason": "daily_limit_exceeded",
            "count_today": sos_log.get("count", 0),
        })
        # admin 告警(發 LINE 給 ADMIN_LINE_USER_ID)
        admin_id = os.environ.get("ADMIN_LINE_USER_ID", "")
        if admin_id:
            try:
                token_admin = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
                sender_admin = (config or {}).get("LINE_PUSH_SENDER") or line_push_message
                sender_admin(token_admin, admin_id, (
                    f"🚨 [SOS 異常] 用戶 {profile.get('display_name') or line_user_id} "
                    f"今日已按 SOS {sos_log.get('count', 0)} 次(上限 {SOS_DAILY_LIMIT})，請聯繫確認。"
                ))
            except Exception:
                pass
        save_state(data_file, state)
        return {
            "error": f"daily SOS limit reached ({SOS_DAILY_LIMIT})",
            "limit": SOS_DAILY_LIMIT,
            "resets_at": f"{today_str}T23:59:59+08:00",
        }, 429

    # 防護 2:5 分鐘冷卻
    SOS_COOLDOWN_SEC = 300
    last_sos_str = profile.get("last_sos_at")
    if last_sos_str:
        try:
            last_sos_dt = datetime.fromisoformat(last_sos_str)
            elapsed = (now_dt - last_sos_dt).total_seconds()
            if elapsed < SOS_COOLDOWN_SEC:
                wait_sec = int(SOS_COOLDOWN_SEC - elapsed)
                save_state(data_file, state)
                return {
                    "error": f"SOS cooldown active, wait {wait_sec}s",
                    "cooldown_remaining_sec": wait_sec,
                }, 429
        except (ValueError, TypeError):
            pass

    token = (config or {}).get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        return {"error": "LINE_CHANNEL_ACCESS_TOKEN is not set"}, 400

    limit = int(rules.get("core_guardian_alert_limit") or 1)
    contacts = sorted(profile.get("contacts") or [], key=lambda item: int(item.get("priority") or 9999))
    line_contacts = [
        contact for contact in contacts
        if contact.get("line_id") and "line" in (contact.get("notify_methods") or ["line"])
    ][:limit]

    active_group_ids = []
    if rules.get("guardian_group_limit"):
        groups = state.get("guardian_groups", {})
        active_group_ids = [
            group_id for group_id in (profile.get("guardian_group_ids") or [])
            if groups.get(group_id, {}).get("owner_line_user_id") == line_user_id
            and groups.get(group_id, {}).get("status") == "active"
            and (groups.get(group_id, {}).get("preferences") or {}).get("notify_group_on_overdue", True)
        ][: int(rules.get("guardian_group_limit") or 0)]

    # 個人守護人或守護群任一可送；兩者都沒有才拒絕（方案本身不會自動綁定對象）
    if not line_contacts and not active_group_ids:
        return {"error": "no bound LINE guardians", "sent": 0}, 400

    location = profile.get("location") or {}
    location_text = ""
    if location.get("latitude") is not None and location.get("longitude") is not None:
        city = str(location.get("city") or "").strip()
        place = f"（{city}）" if city else ""
        location_text = (
            f"\n目前位置{place}："
            f"https://www.google.com/maps?q={location['latitude']},{location['longitude']}"
        )
    import uuid
    sos_event_id = f"sos-{uuid.uuid4().hex[:10]}"
    message = (
        f"🚨【SOS 緊急求助】{profile.get('display_name') or '你的親友'} 發出緊急求助，\n"
        f"請立即聯絡本人並確認安全。若有立即危險，請撥打 119。{location_text}\n\n"
        "本通知不會自動聯絡警消，請依現場狀況主動求助。"
    )

    sender = (config or {}).get("LINE_PUSH_SENDER") or line_push_message
    sent = 0
    failed = 0
    group_sent = 0
    group_failed = 0
    results = []
    for contact in line_contacts:
        target = contact["line_id"]
        try:
            result = sender(token, target, message)
            append_notification_log(state, "sos", target, "sent", message, json.dumps(result, ensure_ascii=False))
            sent += 1
            results.append({"line_user_id": target, "status": "sent"})
        except Exception as exc:
            append_notification_log(state, "sos", target, "failed", message, str(exc))
            failed += 1
            results.append({"line_user_id": target, "status": "failed"})

    for group_id in active_group_ids:
        try:
            result = sender(token, group_id, message)
            append_notification_log(state, "sos_guardian_group", group_id, "sent", message, json.dumps(result, ensure_ascii=False))
            sent += 1
            group_sent += 1
            results.append({"group_id": group_id, "status": "sent"})
        except Exception as exc:
            append_notification_log(state, "sos_guardian_group", group_id, "failed", message, str(exc))
            failed += 1
            group_failed += 1
            results.append({"group_id": group_id, "status": "failed"})

    profile["last_sos_at"] = current_app_time(config or {}).isoformat(timespec="seconds")
    # 🔴 P0 FIX:累計今日 SOS 計數
    sos_log["count"] = sos_log.get("count", 0) + 1
    profile["sos_daily_log"] = sos_log
    profile["last_sos_event_id"] = sos_event_id
    save_state(data_file, state)
    code = 200 if sent else 502
    return {
        "sent": sent,
        "failed": failed,
        "group_sent": group_sent,
        "group_failed": group_failed,
        "guardian_limit": limit,
        "results": results,
        "location_attached": bool(location_text),
    }, code


def friend_locations(data_file, line_user_id):
    state = load_state(data_file)
    profile = get_profile(state, line_user_id)
    now = datetime.now()
    friends = []
    for friend_id in profile.get("friends") or []:
        friend = state.get("users", {}).get(friend_id)
        if not friend:
            continue
        location = friend.get("location") or {}
        if not _location_session_active(location, now):
            continue
        snap = safety_guard_snapshot(friend, now)
        friends.append(
            {
                "line_user_id": friend_id,
                "display_name": friend.get("display_name", "LINE 使用者"),
                "latitude": location.get("latitude"),
                "longitude": location.get("longitude"),
                "city": location.get("city", ""),
                "updated_at": location.get("updated_at"),
                "expires_at": location.get("expires_at"),
                "started_at": location.get("started_at"),
                "until_stop": bool(location.get("until_stop")),
                "safety_status": snap.get("safety_status"),
                "is_today_checked": snap.get("is_today_checked"),
                "mode": "safety_guard",
            }
        )
    return {"friends": friends}


def admin_update_user_plan(data_file, payload):
    """後台調整方案：只改方案／付款欄位，绝不清空守護人、好友或守護群。"""
    line_user_id = str(payload.get("line_user_id") or "").strip()
    if not line_user_id:
        return {"error": "missing line_user_id"}, 400
    plan = str(payload.get("plan") or "trial")
    if plan not in PLAN_LIMITS:
        return {"error": "unknown plan"}, 400
    state = load_state(data_file)
    profile = get_profile(state, line_user_id)

    # 升級前快照：確保後續邏輯不會誤清綁定資料
    preserved_contacts = list(profile.get("contacts") or [])
    preserved_friends = list(profile.get("friends") or [])
    preserved_groups = list(profile.get("guardian_group_ids") or [])
    preserved_onboarding = bool(profile.get("is_onboarding_completed"))
    preserved_reminder_times = list(profile.get("reminder_times") or [])
    preserved_reminder_time = profile.get("reminder_time")

    profile["plan"] = plan
    profile["payment_status"] = str(
        payload.get("payment_status") or ("trial" if plan == "trial" else "active")
    )

    paid_until = str(payload.get("paid_until") or "").strip()
    if not paid_until:
        paid_until = str(profile.get("paid_until") or "").strip()
    # 後台改成付費方案但未填到期日時，自動補合理到期日，避免被過期降級排程立刻打回 free
    if plan.startswith("paid_") and not paid_until:
        product = PAYMENT_PRODUCTS.get(plan) or {}
        days = int(product.get("duration_days") or (365 if "year" in plan else 30))
        paid_until = (datetime.now() + timedelta(days=days)).isoformat(timespec="seconds")
        profile["billing_cycle"] = product.get("billing_cycle") or (
            "yearly" if "year" in plan else "monthly"
        )
    if paid_until:
        profile["paid_until"] = paid_until
        profile["next_billing_date"] = paid_until
    elif plan in ("trial", "free"):
        # 明確降為試用／免費時才清到期日；付費升級絕不因空字串清掉
        if "paid_until" in payload:
            profile["paid_until"] = ""

    # 明確寫回綁定資料（防止任何中間步驟誤改）
    profile["contacts"] = preserved_contacts
    profile["friends"] = preserved_friends
    profile["guardian_group_ids"] = preserved_groups
    if preserved_onboarding:
        profile["is_onboarding_completed"] = True
    if preserved_reminder_times:
        profile["reminder_times"] = preserved_reminder_times
    if preserved_reminder_time:
        profile["reminder_time"] = preserved_reminder_time

    save_state(data_file, state)
    status = build_status(profile, state)
    status["preserved_contacts"] = len(preserved_contacts)
    status["preserved_friends"] = len(preserved_friends)
    status["preserved_guardian_groups"] = len(preserved_groups)
    return status, 200


def create_support_ticket(data_file, payload):
    line_user_id = str(payload.get("line_user_id") or "").strip()
    message = str(payload.get("message") or "").strip()
    if not line_user_id or not message:
        return {"error": "missing line_user_id or message"}, 400
    state = load_state(data_file)
    profile = get_profile(state, line_user_id)
    ticket = {
        "id": secrets.token_urlsafe(8),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "line_user_id": line_user_id,
        "display_name": str(payload.get("display_name") or profile.get("display_name") or "LINE 使用者"),
        "message": message[:1000],
        "status": "open",
        "plan": profile.get("plan", "trial"),
        "last_check_in": profile.get("last_check_in"),
        "reply": "",
        "replied_at": "",
    }
    tickets = state.setdefault("support_tickets", [])
    tickets.append(ticket)
    state["support_tickets"] = tickets[-200:]
    save_state(data_file, state)
    return {"ticket": ticket}, 200


def admin_support_tickets(data_file):
    state = load_state(data_file)
    tickets = list(reversed(state.get("support_tickets", [])[-100:]))
    return {"tickets": tickets}


def admin_reply_support_ticket(data_file, payload, config=None):
    ticket_id = str(payload.get("ticket_id") or "").strip()
    message = str(payload.get("message") or "").strip()
    if not ticket_id or not message:
        return {"error": "missing ticket_id or message"}, 400
    state = load_state(data_file)
    ticket = next((item for item in state.get("support_tickets", []) if item.get("id") == ticket_id), None)
    if not ticket:
        return {"error": "ticket not found"}, 404
    token = (config or {}).get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    sender = (config or {}).get("LINE_PUSH_SENDER") or line_push_message
    if not token:
        return {"error": "LINE_CHANNEL_ACCESS_TOKEN is not set"}, 400
    result = sender(token, ticket["line_user_id"], message)
    ticket["status"] = "replied"
    ticket["reply"] = message[:1000]
    ticket["replied_at"] = datetime.now().isoformat(timespec="seconds")
    append_notification_log(state, "support_reply", ticket["line_user_id"], "sent", message, json.dumps(result, ensure_ascii=False))
    save_state(data_file, state)
    return {"ticket": ticket, "result": result}, 200


def export_account_data(data_file, payload):
    line_user_id = str(payload.get("line_user_id") or "").strip()
    if not line_user_id:
        return {"error": "missing line_user_id"}, 400
    state = load_state(data_file)
    profile = state.get("users", {}).get(line_user_id)
    if profile is None:
        return {"error": "user not found"}, 404

    return {
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "member": profile,
        "orders": [order for order in state.get("orders", []) if order.get("line_user_id") == line_user_id],
        "support_tickets": [ticket for ticket in state.get("support_tickets", []) if ticket.get("line_user_id") == line_user_id],
        "guardian_groups": [
            group for group in state.get("guardian_groups", {}).values()
            if group.get("owner_line_user_id") == line_user_id
        ],
        "contact_rewards": [
            reward for reward in state.get("contact_rewards", [])
            if line_user_id in {reward.get("inviter_line_user_id"), reward.get("contact_line_user_id")}
        ],
        "notification_logs": [
            log for log in state.get("notification_logs", [])
            if line_user_id in {log.get("line_user_id"), log.get("target")}
        ],
    }, 200


def delete_account(data_file, payload):
    line_user_id = str(payload.get("line_user_id") or "").strip()
    if not line_user_id:
        return {"error": "missing line_user_id"}, 400
    state = load_state(data_file)
    removed = state.get("users", {}).pop(line_user_id, None)
    if removed is None:
        return {"deleted": False, "line_user_id": line_user_id}, 200

    for profile in state.get("users", {}).values():
        profile["friends"] = [friend_id for friend_id in (profile.get("friends") or []) if friend_id != line_user_id]
        for contact in profile.get("contacts") or []:
            if contact.get("line_id") == line_user_id:
                contact["line_id"] = ""
                contact["consent_status"] = "revoked"
                contact["note"] = "對方已刪除平台帳號"

    state["friend_invites"] = {
        code: invite for code, invite in state.get("friend_invites", {}).items()
        if invite.get("line_user_id") != line_user_id
    }
    state["guardian_groups"] = {
        group_id: group for group_id, group in state.get("guardian_groups", {}).items()
        if group.get("owner_line_user_id") != line_user_id
    }
    state["contact_rewards"] = [
        reward for reward in state.get("contact_rewards", [])
        if line_user_id not in {reward.get("inviter_line_user_id"), reward.get("contact_line_user_id")}
    ]
    state["support_tickets"] = [
        ticket for ticket in state.get("support_tickets", []) if ticket.get("line_user_id") != line_user_id
    ]
    state["notification_logs"] = [
        log for log in state.get("notification_logs", [])
        if line_user_id not in {log.get("line_user_id"), log.get("target")}
    ]
    for order in state.get("orders", []):
        if order.get("line_user_id") == line_user_id:
            order["line_user_id"] = "deleted-user"
            order["display_name"] = "已刪除會員"
            order["personal_data_removed_at"] = datetime.now().isoformat(timespec="seconds")
    save_state(data_file, state)
    return {"deleted": bool(removed), "line_user_id": line_user_id}, 200


def delete_personal_history(data_file, payload):
    line_user_id = str(payload.get("line_user_id") or "").strip()
    record_type = str(payload.get("record_type") or "checkins").strip()
    if not line_user_id:
        return {"error": "missing line_user_id"}, 400
    if record_type != "checkins":
        return {"error": "unsupported record_type"}, 400

    state = load_state(data_file)
    profile = state.get("users", {}).get(line_user_id)
    if profile is None:
        return {"error": "user not found"}, 404

    removed_count = len(profile.get("history") or [])
    profile["history"] = []
    profile["last_check_in"] = None
    profile["last_warning_cancelled_at"] = None
    save_state(data_file, state)
    return {
        "deleted": True,
        "record_type": record_type,
        "removed_count": removed_count,
        "line_user_id": line_user_id,
    }, 200


def _normalize_admin_password(value):
    """Strip whitespace / paste junk so env file CRLF and zero-width chars don't break login."""
    text = str(value or "")
    for ch in ("\ufeff", "\u200b", "\u200c", "\u200d", "\u2060"):
        text = text.replace(ch, "")
    # Normalize common unicode dashes to ASCII hyphen (copy/paste from chat)
    for ch in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\ufe58", "\ufe63", "\uff0d"):
        text = text.replace(ch, "-")
    return text.strip()


def _env_flag_on(name, config=None):
    raw = os.environ.get(name)
    if raw is None and config is not None:
        raw = config.get(name, "")
    return str(raw or "").strip().lower() in ("1", "true", "yes", "on")


def admin_open_mode(config=None):
    """Open admin (no password) when ALLOW_OPEN_ADMIN/ADMIN_OPEN is on, or ADMIN_PASSWORD is empty.

    WARNING: public URL with open admin is insecure — intentional for owner convenience.
    """
    cfg = config or {}
    if _env_flag_on("ALLOW_OPEN_ADMIN", cfg) or _env_flag_on("ADMIN_OPEN", cfg):
        return True
    expected = _normalize_admin_password(
        os.environ.get("ADMIN_PASSWORD") or cfg.get("ADMIN_PASSWORD", "")
    )
    return not expected


def admin_allowed(config, password):
    if admin_open_mode(config):
        return True
    expected = _normalize_admin_password(
        os.environ.get("ADMIN_PASSWORD") or config.get("ADMIN_PASSWORD", "")
    )
    got = _normalize_admin_password(password)
    if not expected:
        return False
    # compare_digest raises (→ HTTP 500) when lengths differ on some Python builds
    if len(expected) != len(got):
        return False
    return secrets.compare_digest(expected, got)


def admin_auth_error_payload(config, password):
    """Return (payload, http_status) when auth fails; None when allowed."""
    if admin_open_mode(config):
        return None
    expected = _normalize_admin_password(
        os.environ.get("ADMIN_PASSWORD") or config.get("ADMIN_PASSWORD", "")
    )
    if not expected:
        # Should not reach here (empty password ⇒ open mode); keep safe fallback.
        return None
    if not admin_allowed(config, password):
        return {"error": "unauthorized"}, 401
    return None


def _line_channel_access_token(config=None):
    cfg = config or {}
    return (
        cfg.get("LINE_CHANNEL_ACCESS_TOKEN")
        or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
        or os.environ.get("CHANNEL_ACCESS_TOKEN")
        or ""
    ).strip()


def deploy_default_rich_menu(config=None, root_dir=None):
    """用伺服器上的 LINE_CHANNEL_ACCESS_TOKEN 建立並設為預設圖文選單。

    不回傳／不 log token。成功回 (payload, 200)；失敗回 (error, http_code)。
    """
    token = _line_channel_access_token(config)
    if not token:
        return {"ok": False, "error": "LINE_CHANNEL_ACCESS_TOKEN not configured"}, 503

    root = Path(root_dir) if root_dir else Path(__file__).resolve().parent
    config_path = root / "line-rich-menu-config.json"
    image_path = root / "line-rich-menu.png"
    if not config_path.exists():
        return {"ok": False, "error": f"missing {config_path.name}"}, 500
    if not image_path.exists():
        return {"ok": False, "error": f"missing {image_path.name}"}, 500

    menu_config = json.loads(config_path.read_text(encoding="utf-8"))

    def _request(method, url, body=None, content_type="application/json"):
        data = None
        headers = {"Authorization": f"Bearer {token}"}
        if body is not None:
            if content_type == "application/json":
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            else:
                data = body
            headers["Content-Type"] = content_type
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                code = int(getattr(resp, "status", 200) or 200)
                parsed = json.loads(raw) if raw.strip() else {}
                return code, parsed
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            return int(exc.code), {"error": err_body}

    code, created = _request("POST", "https://api.line.me/v2/bot/richmenu", menu_config)
    if code != 200 or not created.get("richMenuId"):
        return {
            "ok": False,
            "step": "create",
            "http": code,
            "error": created.get("error") or created,
        }, 502

    rich_menu_id = created["richMenuId"]
    code, uploaded = _request(
        "POST",
        f"https://api-data.line.me/v2/bot/richmenu/{rich_menu_id}/content",
        image_path.read_bytes(),
        content_type="image/png",
    )
    if code not in (200, 204):
        return {
            "ok": False,
            "step": "upload_image",
            "richMenuId": rich_menu_id,
            "http": code,
            "error": uploaded.get("error") or uploaded,
        }, 502

    code, defaulted = _request(
        "POST",
        f"https://api.line.me/v2/bot/user/all/richmenu/{rich_menu_id}",
    )
    if code not in (200, 204):
        return {
            "ok": False,
            "step": "set_default",
            "richMenuId": rich_menu_id,
            "http": code,
            "error": defaulted.get("error") or defaulted,
        }, 502

    return {
        "ok": True,
        "richMenuId": rich_menu_id,
        "name": menu_config.get("name"),
        "chatBarText": menu_config.get("chatBarText"),
        "image_bytes": image_path.stat().st_size,
        "areas": [
            {
                "label": (area.get("action") or {}).get("label"),
                "type": (area.get("action") or {}).get("type"),
                "uri": (area.get("action") or {}).get("uri"),
                "text": (area.get("action") or {}).get("text"),
            }
            for area in (menu_config.get("areas") or [])
        ],
    }, 200


def inspect_default_rich_menu(config=None):
    """查詢目前預設圖文選單（含各區塊 URI）。不回傳 token。"""
    token = _line_channel_access_token(config)
    if not token:
        return {"ok": False, "error": "LINE_CHANNEL_ACCESS_TOKEN not configured"}, 503

    def _request(method, url):
        req = urllib.request.Request(
            url, method=method, headers={"Authorization": f"Bearer {token}"}
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                code = int(getattr(resp, "status", 200) or 200)
                parsed = json.loads(raw) if raw.strip() else {}
                return code, parsed
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            return int(exc.code), {"error": err_body}

    code, default = _request("GET", "https://api.line.me/v2/bot/user/all/richmenu")
    if code != 200 or not isinstance(default, dict) or not default.get("richMenuId"):
        return {
            "ok": False,
            "step": "get_default",
            "http": code,
            "error": default.get("error") if isinstance(default, dict) else default,
        }, 502

    rich_menu_id = default["richMenuId"]
    code, detail = _request("GET", f"https://api.line.me/v2/bot/richmenu/{rich_menu_id}")
    if code != 200 or not isinstance(detail, dict):
        return {
            "ok": False,
            "step": "get_detail",
            "richMenuId": rich_menu_id,
            "http": code,
            "error": detail.get("error") if isinstance(detail, dict) else detail,
        }, 502

    areas = []
    invite_uri = None
    for area in detail.get("areas") or []:
        action = area.get("action") or {}
        item = {
            "label": action.get("label"),
            "type": action.get("type"),
            "uri": action.get("uri"),
            "text": action.get("text"),
        }
        areas.append(item)
        if action.get("label") == "一鍵邀請":
            invite_uri = action.get("uri")

    return {
        "ok": True,
        "richMenuId": rich_menu_id,
        "name": detail.get("name"),
        "chatBarText": detail.get("chatBarText"),
        "areas": areas,
        "invite_uri": invite_uri,
        "invite_uri_ok": bool(
            invite_uri
            and "share-invite.html" in invite_uri
            and "open=share" not in invite_uri
        ),
    }, 200


def cron_allowed(config, secret):
    expected = (config.get("CRON_SECRET") or os.environ.get("CRON_SECRET", "") or "").strip()
    provided = str(secret or "").strip()
    # Empty CRON_SECRET must never authorize — fail closed.
    if not expected:
        return False
    return secrets.compare_digest(expected, provided)


def admin_summary(data_file):
    state = load_state(data_file)
    users = []
    for user in state.get("users", {}).values():
        users.append(build_status(user))
    users.sort(key=lambda item: (not item["is_overdue"], item.get("display_name") or ""))
    guardian_groups = list(state.get("guardian_groups", {}).values())
    guardian_groups.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    orders = list(reversed(state.get("orders", [])[-100:]))
    paid_orders = [order for order in orders if order.get("status") == "paid"]
    county_rows = {}

    def county_row(county):
        return county_rows.setdefault(
            county or "未提供",
            {"county": county or "未提供", "members": 0, "orders": 0, "paid_orders": 0, "revenue": 0},
        )

    for profile in state.get("users", {}).values():
        county = str((profile.get("location") or {}).get("city") or "未提供").strip()
        county_row(county)["members"] += 1

    for order in orders:
        profile = state.get("users", {}).get(order.get("line_user_id"), {})
        county = str((profile.get("location") or {}).get("city") or "未提供").strip()
        row = county_row(county)
        row["orders"] += 1
        if order.get("status") == "paid":
            row["paid_orders"] += 1
            row["revenue"] += int(order.get("amount") or 0)

    county_stats = sorted(
        county_rows.values(),
        key=lambda item: (-item["revenue"], -item["members"], item["county"]),
    )
    return {
        "total_users": len(users),
        "overdue_users": sum(1 for user in users if user["is_overdue"]),
        "warning_users": sum(1 for user in users if user["status_class"] == "warning"),
        "checked_today": sum(1 for user in users if user["is_today_checked"]),
        "guardian_group_count": len(guardian_groups),
        "guardian_groups": guardian_groups,
        "orders": orders,
        "paid_order_count": len(paid_orders),
        "paid_revenue": sum(int(order.get("amount") or 0) for order in paid_orders),
        "pending_order_count": sum(1 for order in orders if order.get("status") == "pending"),
        "county_stats": county_stats,
        "users": users,
        "contact_rewards": list(reversed(state.get("contact_rewards", [])[-20:])),
        "notification_logs": list(reversed(state.get("notification_logs", [])[-20:])),
    }


def backup_root(data_file):
    return Path(data_file).parent / "backups"


def create_admin_backup(data_file):
    state = load_state(data_file)
    created_at = datetime.now().isoformat(timespec="seconds")
    backup_id = f"backup-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"
    filename = f"{backup_id}.json"
    snapshot = {key: value for key, value in state.items() if key != "backup_exports"}
    backup = {
        "id": backup_id,
        "created_at": created_at,
        "filename": filename,
        "user_count": len(snapshot.get("users", {})),
    }
    root = backup_root(data_file)
    root.mkdir(parents=True, exist_ok=True)
    (root / filename).write_text(
        json.dumps({"backup": backup, "snapshot": snapshot}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    state.setdefault("backup_exports", []).append(backup)
    state["backup_exports"] = state["backup_exports"][-50:]
    save_state(data_file, state)
    return {"backup": backup}, 200


def list_admin_backups(data_file):
    state = load_state(data_file)
    return {"backups": list(reversed(state.get("backup_exports", [])))}


def read_admin_backup(data_file, backup_id):
    state = load_state(data_file)
    backup = next((item for item in state.get("backup_exports", []) if item.get("id") == backup_id), None)
    if not backup:
        return {"error": "backup not found"}, 404
    path = backup_root(data_file) / backup.get("filename", "")
    if not path.exists():
        return {"error": "backup file missing"}, 404
    try:
        return json.loads(path.read_text(encoding="utf-8")), 200
    except (json.JSONDecodeError, OSError):
        return {"error": "backup file unreadable"}, 500


def line_push_message(token, line_user_id, message):
    """推訊息給單一 LINE 用戶。

    message 可以是:
    - str: 純文字訊息
    - dict 且帶 "type" key: 直接作為 LINE message object (例如 flex)
    """
    if isinstance(message, dict) and message.get("type"):
        msg_obj = message
    else:
        msg_obj = {"type": "text", "text": str(message)}
    body = json.dumps(
        {"to": line_user_id, "messages": [msg_obj]},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.line.me/v2/bot/message/push",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        return {"ok": 200 <= res.status < 300, "status": res.status}


def append_notification_log(state, kind, line_user_id, status, message, detail=None):
    logs = state.setdefault("notification_logs", [])
    if isinstance(message, dict):
        message_text = str(message.get("altText") or message.get("type") or message)[:120]
    else:
        message_text = str(message or "")[:120]
    logs.append(
        {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "kind": kind,
            "line_user_id": line_user_id,
            "status": status,
            "message": message_text,
            "detail": detail or "",
        }
    )
    state["notification_logs"] = logs[-100:]


def log_notification(data_file, kind, line_user_id, status, message, detail=None):
    state = load_state(data_file)
    append_notification_log(state, kind, line_user_id, status, message, detail)
    save_state(data_file, state)


def send_due_reminders(config):
    token = config.get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        return {"sent": 0, "skipped": 0, "error": "LINE_CHANNEL_ACCESS_TOKEN is not set"}, 400

    summary = admin_summary(config["DATA_FILE"])
    sender = config.get("LINE_PUSH_SENDER") or line_push_message
    state = load_state(config["DATA_FILE"])
    now = current_app_time(config)
    today = now.strftime("%Y-%m-%d")
    sent = 0
    skipped = 0
    results = []
    for user in summary["users"]:
        if not user["is_overdue"]:
            continue
        profile = state.get("users", {}).get(user["line_user_id"])
        if not profile:
            continue
        if profile.get("last_overdue_alert_date") == today:
            skipped += 1
            continue
        location = profile.get("location") or {}
        location_link = ""
        if profile.get("attach_location_on_alert") and location.get("latitude") and location.get("longitude"):
            location_link = f"\n最後位置：https://www.google.com/maps?q={location['latitude']},{location['longitude']}"
        message = f"❤️ 今天一切都好嗎？\n點一下「我平安」，讓家人放心。{location_link}"
        try:
            result = sender(token, user["line_user_id"], message)
            append_notification_log(state, "overdue", user["line_user_id"], "sent", message, json.dumps(result, ensure_ascii=False))
            sent += 1
            results.append({"line_user_id": user["line_user_id"], "result": result})
        except Exception as exc:
            append_notification_log(state, "overdue", user["line_user_id"], "failed", message, str(exc))
            skipped += 1
            results.append({"line_user_id": user["line_user_id"], "error": str(exc)})

        contact_message = (
            f"【需要幫忙】{profile.get('display_name') or '家人'} 超過時間尚未回報平安，請協助確認是否一切都好。"
            f"{location_link}"
        )
        rules = plan_rules(profile)
        alert_limit = int(rules.get("core_guardian_alert_limit") or 1)
        contacts = sorted(profile.get("contacts") or [], key=lambda item: int(item.get("priority") or 9999))
        line_contacts = [
            contact for contact in contacts
            if (contact.get("line_id") or contact.get("line_user_id"))
            and "line" in (contact.get("notify_methods") or ["line"])
        ][:alert_limit]
        for contact in line_contacts:
            target = contact.get("line_id") or contact.get("line_user_id")
            try:
                result = sender(token, target, contact_message)
                append_notification_log(state, "contact_alert", target, "sent", contact_message, json.dumps(result, ensure_ascii=False))
                sent += 1
                results.append({"line_user_id": target, "result": result})
            except Exception as exc:
                append_notification_log(state, "contact_alert", target, "failed", contact_message, str(exc))
                skipped += 1
                results.append({"line_user_id": target, "error": str(exc)})
            for method in (contact.get("notify_methods") or ["line"]):
                if method in {"sms", "phone"}:
                    detail = contact.get("phone") or "missing phone"
                    append_notification_log(
                        state,
                        f"{method}_contact_alert",
                        user["line_user_id"],
                        "skipped_not_live",
                        contact_message,
                        detail,
                    )

        group_limit = int(rules.get("guardian_group_limit") or 0)
        if group_limit > 0:
            groups = state.get("guardian_groups", {})
            active_group_ids = [
                group_id for group_id in (profile.get("guardian_group_ids") or [])
                if groups.get(group_id, {}).get("owner_line_user_id") == user["line_user_id"]
                and groups.get(group_id, {}).get("status") == "active"
                and (groups.get(group_id, {}).get("preferences") or {}).get("notify_group_on_overdue", True)
            ][:group_limit]
            group_message = (
                f"【失聯預警】{profile.get('display_name') or '成員'} 已超過平安簽到時間，"
                f"請群內協助確認。{location_link}"
            )
            for group_id in active_group_ids:
                try:
                    result = sender(token, group_id, group_message)
                    append_notification_log(
                        state,
                        "overdue_guardian_group",
                        group_id,
                        "sent",
                        group_message,
                        json.dumps(result, ensure_ascii=False),
                    )
                    sent += 1
                    results.append({"group_id": group_id, "result": result})
                except Exception as exc:
                    append_notification_log(
                        state,
                        "overdue_guardian_group",
                        group_id,
                        "failed",
                        group_message,
                        str(exc),
                    )
                    skipped += 1
                    results.append({"group_id": group_id, "error": str(exc)})

        profile["last_overdue_alert_date"] = today

    save_state(config["DATA_FILE"], state)
    return {"sent": sent, "skipped": skipped, "results": results}, 200


def send_missing_contact_reminders(config):
    token = config.get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        return {"sent": 0, "skipped": 0, "error": "LINE_CHANNEL_ACCESS_TOKEN is not set"}, 400

    state = load_state(config["DATA_FILE"])
    sender = config.get("LINE_PUSH_SENDER") or line_push_message
    public_url = (config.get("APP_PUBLIC_URL") or os.environ.get("APP_PUBLIC_URL", "")).rstrip("/")
    today = current_app_time(config).strftime("%Y-%m-%d")
    sent = 0
    skipped = 0
    results = []
    for user in state.get("users", {}).values():
        line_user_id = user.get("line_user_id")
        if not line_user_id:
            skipped += 1
            continue
        contact_count = len(user.get("contacts") or [])
        contact_limit = plan_rules(user)["contact_limit"]
        reminder_enabled = bool(user.get("contact_capacity_reminder_enabled", False))
        is_799 = user.get("plan") in {"paid_799", "paid_799_year"}
        guardian_details_complete = any(complete_guardian_contact(contact) for contact in (user.get("contacts") or []))
        if is_799 and not guardian_details_complete:
            if not user.get("guardian_details_reminder_enabled", True) or user.get("guardian_details_reminder_sent_at"):
                continue
            link_text = (
                f"\n前往我的守護資料：{liff_entry_url(open_action='member') if liff_entry_url else 'https://liff.line.me/2010674803-rK98c0lo/?open=member'}"
            )
            message = (
                "你的 799 守護方案還少一份必要資料。請在『我的守護資料』完成至少 1 位守護人的姓名、關係與電話，"
                f"緊急時系統才能正確聯絡對方。這則提醒只會傳送一次。{link_text}"
            )
            try:
                result = sender(token, line_user_id, message)
                user["guardian_details_reminder_sent_at"] = current_app_time(config).isoformat(timespec="seconds")
                append_notification_log(state, "guardian_details", line_user_id, "sent", message, json.dumps(result, ensure_ascii=False))
                sent += 1
                results.append({"line_user_id": line_user_id, "result": result})
            except Exception as exc:
                append_notification_log(state, "guardian_details", line_user_id, "failed", message, str(exc))
                skipped += 1
                results.append({"line_user_id": line_user_id, "error": str(exc)})
            continue
        if contact_count >= contact_limit or (contact_count > 0 and not reminder_enabled):
            continue
        sent_dates = set(user.get("contact_reminder_sent_dates") or [])
        if today in sent_dates:
            continue
        link_text = (
            f"\n一鍵邀請守護人：{share_invite_liff_url() if share_invite_liff_url else 'https://liff.line.me/2010674803-rK98c0lo/liff/share-invite.html'}"
        )
        if contact_count == 0:
            message = (
                "你目前還沒有綁定守護人（緊急聯絡人）。請至少邀請 1 位信任的親友完成 LINE 綁定，"
                f"緊急時系統才知道要聯絡誰。{link_text}"
            )
        else:
            message = (
                f"你的方案可綁定 {contact_limit} 位守護人，目前已完成 {contact_count}/{contact_limit} 位。"
                f"若想補齊守護名額，可點下方繼續邀請；也能在提醒設定中關閉這則每日提醒。{link_text}"
            )
        try:
            result = sender(token, line_user_id, message)
            sent_dates.add(today)
            user["contact_reminder_sent_dates"] = sorted(sent_dates)[-30:]
            append_notification_log(state, "missing_contact", line_user_id, "sent", message, json.dumps(result, ensure_ascii=False))
            sent += 1
            results.append({"line_user_id": line_user_id, "result": result})
        except Exception as exc:
            append_notification_log(state, "missing_contact", line_user_id, "failed", message, str(exc))
            skipped += 1
            results.append({"line_user_id": line_user_id, "error": str(exc)})
    save_state(config["DATA_FILE"], state)
    return {"sent": sent, "skipped": skipped, "results": results}, 200


def cleanup_expired_data(config):
    data_file = config["DATA_FILE"]
    downgrade_result, _ = apply_expired_plan_downgrades(config)
    state = load_state(data_file)
    now = current_app_time(config)
    invite_cutoff = now - timedelta(days=7)
    notification_cutoff = now - timedelta(days=90)
    expired_locations_removed = 0

    for profile in state.get("users", {}).values():
        location = profile.get("location") or {}
        if not location:
            continue
        # Keep until_stop sessions until the user stops; expire timed sessions by clock.
        if location.get("until_stop") and (location.get("sharing") or location.get("active")):
            continue
        expires_at = parse_datetime(location.get("expires_at"))
        if expires_at and expires_at < now:
            profile["location"] = {
                **location,
                "sharing": False,
                "active": False,
                "ended_at": location.get("ended_at") or now.isoformat(timespec="seconds"),
            }
            expired_locations_removed += 1

    invites_before = len(state.get("friend_invites", {}))
    state["friend_invites"] = {
        code: invite for code, invite in state.get("friend_invites", {}).items()
        if not parse_datetime(invite.get("created_at"))
        or parse_datetime(invite.get("created_at")) >= invite_cutoff
    }

    logs_before = len(state.get("notification_logs", []))
    state["notification_logs"] = [
        log for log in state.get("notification_logs", [])
        if not parse_datetime(log.get("created_at"))
        or parse_datetime(log.get("created_at")) >= notification_cutoff
    ][-100:]
    save_state(data_file, state)
    return {
        "cleaned_at": now.isoformat(timespec="seconds"),
        "expired_locations_removed": expired_locations_removed,
        "expired_invites_removed": invites_before - len(state["friend_invites"]),
        "old_notification_logs_removed": logs_before - len(state["notification_logs"]),
        "orders_removed": 0,
        "plans_downgraded": downgrade_result.get("downgraded", 0),
    }, 200


def reminder_time_due(reminder_time, now):
    try:
        hour, minute = [int(part) for part in str(reminder_time or "12:00").split(":", 1)]
    except ValueError:
        hour, minute = 12, 0
    return (now.hour, now.minute) >= (hour, minute)


def send_checkin_reminders(config):
    token = config.get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        return {"sent": 0, "skipped": 0, "error": "LINE_CHANNEL_ACCESS_TOKEN is not set"}, 400

    data_file = config["DATA_FILE"]
    state = load_state(data_file)
    sender = config.get("LINE_PUSH_SENDER") or line_push_message
    public_url = (config.get("APP_PUBLIC_URL") or os.environ.get("APP_PUBLIC_URL", "")).rstrip("/")
    now = current_app_time(config)
    today = now.strftime("%Y-%m-%d")
    sent = 0
    skipped = 0
    results = []

    for user in state.get("users", {}).values():
        line_user_id = user.get("line_user_id")
        if not line_user_id:
            skipped += 1
            continue
        if today in (user.get("history") or []):
            continue

        times = reminder_times_for_profile(user)
        sent_slots = dict(user.get("checkin_reminder_sent_slots") or {})
        sent_today = set(sent_slots.get(today) or [])

        # 相容舊版:當天已用單一日期標記送過 → 視為本輪已提醒
        legacy_dates = set(user.get("checkin_reminder_sent_dates") or [])
        if today in legacy_dates and not sent_today:
            continue

        due_unsent = [t for t in times if reminder_time_due(t, now) and t not in sent_today]
        if not due_unsent:
            continue

        # 補跑時只推一次(取最晚已到點的時段),並把所有已到點未送時段標為已處理
        target_time = due_unsent[-1]
        # 每日平安推播：❤️ 今天一切都好嗎？＋我平安 / 安全守護 / 需要幫忙
        from datetime import datetime as _dt
        weekday_zh = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"][now.weekday()]
        checkin_uri = liff_entry_url(open_action="checkin") if liff_entry_url else "https://liff.line.me/2010674803-rK98c0lo/?open=checkin"
        guard_uri = liff_entry_url(open_action="guard") if liff_entry_url else "https://liff.line.me/2010674803-rK98c0lo/?open=guard"
        sos_uri = liff_entry_url(open_action="sos") if liff_entry_url else "https://liff.line.me/2010674803-rK98c0lo/?open=sos"
        message = {
            "type": "flex",
            "altText": f"❤️ 今天一切都好嗎？ {today} {target_time}",
            "contents": {
                "type": "bubble",
                "size": "mega",
                "header": {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "xs",
                    "backgroundColor": "#00B900",
                    "paddingTop": "lg",
                    "paddingBottom": "lg",
                    "paddingStart": "lg",
                    "paddingEnd": "lg",
                    "contents": [
                        {"type": "text", "text": "每日平安", "color": "#FFFFFF", "size": "lg", "weight": "bold", "wrap": True},
                        {"type": "text", "text": f"📅 {today} {weekday_zh} {target_time}", "color": "#FFFFFF", "size": "xl", "weight": "bold", "wrap": True},
                    ],
                },
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "md",
                    "paddingAll": "lg",
                    "contents": [
                        {"type": "text", "text": "❤️ 今天一切都好嗎？", "size": "xl", "weight": "bold", "color": "#1a1a1a", "wrap": True},
                        {"type": "text", "text": "點下面按鈕回報平安，或需要幫忙時求助", "size": "lg", "color": "#555555", "wrap": True},
                    ],
                },
                "footer": {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "sm",
                    "paddingAll": "lg",
                    "backgroundColor": "#FAFAFA",
                    "contents": [
                        {"type": "button", "action": {"type": "uri", "label": "✅ 我平安", "uri": checkin_uri}, "style": "primary", "color": "#16A34A", "height": "md"},
                        {"type": "button", "action": {"type": "uri", "label": "🛡️ 安全守護", "uri": guard_uri}, "style": "primary", "color": "#2563EB", "height": "md"},
                        {"type": "button", "action": {"type": "uri", "label": "需要幫忙", "uri": sos_uri}, "style": "primary", "color": "#DC2626", "height": "md"},
                    ],
                },
            },
        }
        try:
            result = sender(token, line_user_id, message)
            sent_today.update(due_unsent)
            sent_slots[today] = sorted(sent_today)
            # 只保留近 30 天的 slot 紀錄
            keep_dates = sorted(sent_slots.keys())[-30:]
            user["checkin_reminder_sent_slots"] = {d: sent_slots[d] for d in keep_dates}
            # 舊欄位：當日所有時段都處理完才標記，避免挡住後續時段
            if set(times).issubset(sent_today):
                legacy_dates.add(today)
                user["checkin_reminder_sent_dates"] = sorted(legacy_dates)[-30:]
            append_notification_log(state, "checkin", line_user_id, "sent", message, json.dumps(result, ensure_ascii=False))
            sent += 1
            results.append({"line_user_id": line_user_id, "reminder_time": target_time, "result": result})
        except Exception as exc:
            append_notification_log(state, "checkin", line_user_id, "failed", message, str(exc))
            skipped += 1
            results.append({"line_user_id": line_user_id, "error": str(exc)})

    save_state(data_file, state)
    return {"sent": sent, "skipped": skipped, "results": results}, 200


def send_birthday_reminders(config):
    token = config.get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        return {"sent": 0, "skipped": 0, "error": "LINE_CHANNEL_ACCESS_TOKEN is not set"}, 400

    data_file = config["DATA_FILE"]
    state = load_state(data_file)
    sender = config.get("LINE_PUSH_SENDER") or line_push_message
    now = current_app_time(config)
    today_date = now.date()
    today_key = today_date.strftime("%Y-%m-%d")
    sent = 0
    skipped = 0
    results = []

    for user in state.get("users", {}).values():
        line_user_id = user.get("line_user_id")
        if not line_user_id:
            skipped += 1
            continue
        notes = user.get("calendar_notes") or {}
        if not isinstance(notes, dict):
            continue
        sent_keys = set(user.get("birthday_reminder_sent_keys") or [])
        for note_date, note in notes.items():
            birthday = calendar_note_birthday(note)
            if not birthday:
                continue
            try:
                remind_days = int(birthday.get("birthday_remind_days") or 1)
            except (TypeError, ValueError):
                remind_days = 1
            target_date = today_date + timedelta(days=remind_days)
            if not birthday_occurs_on(birthday, target_date):
                continue
            sent_key = f"{today_key}:{note_date}:{remind_days}"
            if sent_key in sent_keys:
                continue
            who = birthday.get("birthday_relationship") or birthday.get("birthday_name") or "家人"
            when_text = "今天" if remind_days == 0 else ("明天" if remind_days == 1 else f"{remind_days} 天後")
            message = f"{when_text}是{who}生日，記得跟他說聲生日快樂。也可以順手確認他今天平安。"
            try:
                result = sender(token, line_user_id, message)
                sent_keys.add(sent_key)
                user["birthday_reminder_sent_keys"] = sorted(sent_keys)[-80:]
                append_notification_log(state, "birthday", line_user_id, "sent", message, json.dumps(result, ensure_ascii=False))
                sent += 1
                results.append({"line_user_id": line_user_id, "birthday": who, "remind_days": remind_days})
            except Exception as exc:
                append_notification_log(state, "birthday", line_user_id, "failed", message, str(exc))
                skipped += 1
                results.append({"line_user_id": line_user_id, "birthday": who, "error": str(exc)})

    save_state(data_file, state)
    return {"sent": sent, "skipped": skipped, "results": results}, 200


def app_config(config):
    token = (
        config.get("LINE_CHANNEL_ACCESS_TOKEN")
        or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
        or os.environ.get("CHANNEL_ACCESS_TOKEN")
        or ""
    ).strip()
    secret = (
        config.get("LINE_CHANNEL_SECRET")
        or os.environ.get("LINE_CHANNEL_SECRET")
        or os.environ.get("CHANNEL_SECRET")
        or ""
    ).strip()
    return {
        "liff_id": config.get("LIFF_ID") or os.environ.get("LIFF_ID", ""),
        "public_url": config.get("APP_PUBLIC_URL") or os.environ.get("APP_PUBLIC_URL", ""),
        # Visible deploy stamp for verifying Render actually rolled the welcome Flex.
        "deploy_version": os.environ.get("DEPLOY_VERSION") or "W250723ac",
        # Both token and secret are required for LINE webhook / messaging.
        "line_enabled": bool(token and secret),
        "require_liff_auth": str(
            config.get("REQUIRE_LIFF_AUTH")
            if config.get("REQUIRE_LIFF_AUTH") is not None
            else os.environ.get("REQUIRE_LIFF_AUTH", "0")
        ).strip().lower()
        in {"1", "true", "yes", "on"},
        "newebpay_ready": bool(newebpay and newebpay.newebpay_configured(config)),
        "sms_live": bool(
            (config.get("SMSKING_USERNAME") or os.environ.get("SMSKING_USERNAME") or "").strip()
            and (config.get("SMSKING_PASSWORD") or os.environ.get("SMSKING_PASSWORD") or "").strip()
        ),
    }


def create_app(config=None):
    if Flask is None:
        return MiniApp(config)

    app = Flask(__name__, static_folder=".", static_url_path="")
    app._start_time = datetime.now()  # 2026-07-21 patch 17: 供 /api/bot/status 計算 uptime
    app.config.update(
        DATA_FILE=os.environ.get("DATA_FILE", str(Path(__file__).resolve().parent / "data" / "state.json")),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", ""),
        ALLOW_OPEN_ADMIN=os.environ.get("ALLOW_OPEN_ADMIN", ""),
        ADMIN_OPEN=os.environ.get("ADMIN_OPEN", ""),
        LINE_CHANNEL_ACCESS_TOKEN=(
            os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
            or os.environ.get("CHANNEL_ACCESS_TOKEN")
            or ""
        ),
        LINE_CHANNEL_SECRET=(
            os.environ.get("LINE_CHANNEL_SECRET")
            or os.environ.get("CHANNEL_SECRET")
            or ""
        ),
        # Accept odd casing from Render UI typos (LINE_Login_Channel_ID etc.)
        LINE_LOGIN_CHANNEL_ID=(
            os.environ.get("LINE_LOGIN_CHANNEL_ID")
            or os.environ.get("LINE_Login_Channel_ID")
            or ""
        ),
        LINE_LOGIN_CHANNEL_SECRET=(
            os.environ.get("LINE_LOGIN_CHANNEL_SECRET")
            or os.environ.get("LINE_Login_CHANNEL_SECRET")
            or ""
        ),
        LIFF_ID=os.environ.get("LIFF_ID", ""),
        APP_PUBLIC_URL=os.environ.get("APP_PUBLIC_URL", ""),
        APP_TIMEZONE=os.environ.get("APP_TIMEZONE", "Asia/Taipei"),
        CRON_SECRET=os.environ.get("CRON_SECRET", ""),
        REQUIRE_LIFF_AUTH=os.environ.get("REQUIRE_LIFF_AUTH", "0"),
        NEWEBPAY_MERCHANT_ID=os.environ.get("NEWEBPAY_MERCHANT_ID", ""),
        NEWEBPAY_HASH_KEY=os.environ.get("NEWEBPAY_HASH_KEY", ""),
        NEWEBPAY_HASH_IV=os.environ.get("NEWEBPAY_HASH_IV", ""),
        NEWEBPAY_STAGE=os.environ.get("NEWEBPAY_STAGE", "sandbox"),
        NEWEBPAY_MPG_URL=os.environ.get("NEWEBPAY_MPG_URL", ""),
        SMSKING_USERNAME=os.environ.get("SMSKING_USERNAME", ""),
        SMSKING_PASSWORD=os.environ.get("SMSKING_PASSWORD", ""),
    )
    if config:
        app.config.update(config)

    def _authenticated_line_user(payload=None, *, use_args=False):
        """Resolve LINE user from verified id_token when required."""
        payload = payload if payload is not None else (request.get_json(silent=True) or {})
        args = request.args if use_args else {}
        if resolve_line_user_id is None:
            claimed = str(
                (payload or {}).get("line_user_id")
                or (args.get("line_user_id") if use_args else "")
                or ""
            ).strip()
            if not claimed:
                return None, ({"ok": False, "error": "missing line_user_id"}, 400)
            return claimed, None
        headers = {key: value for key, value in request.headers.items()}
        return resolve_line_user_id(
            headers=headers,
            payload=payload or {},
            args=args,
            config=app.config,
        )

    def _should_keep_liff_endpoint_spa():
        """LIFF Endpoint MUST always serve the SPA that runs liff.init().

        Never 302 `/?invite_from=` (or friend_invite) away from `/`:
        - LINE opens Endpoint with query / liff.state
        - LINE Login returns `code`/`state` on the same Endpoint URL
        Redirecting those to `/invite` strips OAuth params → iOS+Android login dies.
        External-browser invitees should use explicit `/invite` short links instead.
        """
        return True

    @app.get("/")
    def index():
        # Always serve SPA on LIFF Endpoint `/` (see _should_keep_liff_endpoint_spa).
        _ = _should_keep_liff_endpoint_spa()
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/invite")
    def invite_short_link():
        """Invite landing for external browsers only (not the LIFF Endpoint)."""
        return send_from_directory(app.static_folder, "invite.html")

    @app.get("/health")
    def health():
        return jsonify({"ok": True})

    @app.get("/admin")
    def admin():
        resp = send_from_directory(app.static_folder, "admin.html")
        # Avoid stale cached admin UI (login bar / password UX) after deploys
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        return resp

    @app.get("/test_bind")
    def test_bind():
        return send_from_directory(app.static_folder, "test_bind.html")

    @app.get("/terms")
    def terms():
        return send_from_directory(app.static_folder, "terms.html")

    @app.get("/privacy")
    def privacy():
        return send_from_directory(app.static_folder, "privacy.html")

    @app.get("/faq")
    def faq():
        return send_from_directory(app.static_folder, "faq.html")

    @app.get("/help")
    def help_page():
        return send_from_directory(app.static_folder, "help.html")

    @app.get("/pricing")
    def pricing_page():
        # 直出方案頁，避免 pricing.html → liff/pricing.html 雙重轉跳
        return send_from_directory(app.static_folder, "liff/pricing.html")

    def _liff_embed_redirect(open_action=None, fragment=""):
        """舊 /liff/* HTTPS 連結改導永久內嵌入口，避免外開瀏覽器。"""
        if liff_entry_url is not None:
            target = liff_entry_url(open_action=open_action, fragment=fragment)
        else:
            lid = (
                app.config.get("LIFF_ID")
                or os.environ.get("LIFF_ID")
                or "2010674803-rK98c0lo"
            ).strip()
            target = f"https://liff.line.me/{lid}"
            if open_action:
                target += f"/?open={open_action}"
            elif fragment:
                target += f"#{fragment.lstrip('#')}"
        if redirect is not None:
            return redirect(target, code=302)
        return jsonify({"redirect": target}), 302

    # 圖文選單 / 舊連結：導向 liff.line.me 內嵌（單一 Endpoint = index.html）
    @app.get("/liff/share-invite")
    @app.get("/liff/share-invite.html")
    def liff_share_invite_page():
        """專用一鍵分享頁（給 LIFF 子路徑直連；不經 SPA home）。"""
        return send_from_directory(app.static_folder, "liff/share-invite.html")

    # 2026-07-21 patch 24: Onboarding 流程 API
    @app.get("/liff/onboarding")
    def liff_onboarding():
        return _liff_embed_redirect(open_action="onboarding")

    @app.get("/api/onboarding/state")
    def onboarding_state_api():
        """取得使用者 onboarding 狀態(守護人是否綁定 + 提醒時間)。"""
        line_user_id = request.args.get("line_user_id", "").strip()
        if not line_user_id:
            return jsonify({"ok": False, "error": "missing line_user_id"}), 400
        state = load_state(app.config["DATA_FILE"])
        profile = state.get("users", {}).get(line_user_id, {})
        contacts = profile.get("contacts") or []
        if profile and ensure_onboarding_completed_flag(profile):
            save_state(app.config["DATA_FILE"], state)
        has_guardian = profile_has_guardian(profile)
        setup_done = profile_setup_completed(profile)
        times = reminder_times_for_profile(profile) if profile else default_reminder_times_for_count(1)
        daily_reminders = int(plan_rules(profile).get("daily_reminders") or 1) if profile else 1
        return jsonify({
            "ok": True,
            "line_user_id": line_user_id,
            "has_guardian": has_guardian,
            "guardian_count": len(contacts),
            "reminder_time": times[0] if times else None,
            "reminder_times": times,
            "daily_reminders": daily_reminders,
            "default_reminder_times": default_reminder_times_for_count(daily_reminders),
            "plan": profile.get("plan"),
            "is_onboarding_completed": setup_done,
            "setup_completed": setup_done,
        })

    @app.post("/api/onboarding/reminder")
    def onboarding_reminder_api():
        """設定使用者每日提醒時間(支援單一或多時段)。"""
        data = request.get_json(silent=True) or {}
        line_user_id = (data.get("line_user_id") or "").strip()
        if not line_user_id:
            return jsonify({"ok": False, "error": "missing line_user_id"}), 400
        state = load_state(app.config["DATA_FILE"])
        profile = get_profile(state, line_user_id)
        max_count = int(plan_rules(profile).get("daily_reminders") or 1)
        if "reminder_times" in data:
            raw = data.get("reminder_times")
            if not isinstance(raw, list) or not raw:
                return jsonify({"ok": False, "error": "reminder_times must be a non-empty list"}), 400
            normalized = normalize_reminder_times(raw, max_count)
            if not normalized:
                return jsonify({"ok": False, "error": "invalid reminder_times format, use HH:MM"}), 400
            times = apply_reminder_times_to_profile(profile, times=normalized)
        else:
            reminder_time = (data.get("reminder_time") or "").strip()
            if not REMINDER_TIME_PATTERN.match(reminder_time):
                return jsonify({"ok": False, "error": "invalid reminder_time format, use HH:MM"}), 400
            times = apply_reminder_times_to_profile(profile, single=reminder_time)
        save_state(app.config["DATA_FILE"], state)
        return jsonify({
            "ok": True,
            "reminder_time": times[0],
            "reminder_times": times,
            "daily_reminders": max_count,
        })

    @app.get("/liff/guardian")
    def liff_guardian():
        # 永久入口應是 liff.line.me；此路徑保留相容，導向內嵌 onboarding（守護人→提醒）
        return _liff_embed_redirect(open_action="onboarding")

    @app.get("/liff/member")
    def liff_member():
        return _liff_embed_redirect(open_action="member")

    @app.get("/liff/guardian-groups")
    def liff_guardian_groups():
        return _liff_embed_redirect(open_action="guardians")

    @app.get("/api/config")
    def config_api():
        return jsonify(app_config(app.config))

    @app.get("/api/bot/status")
    def bot_status_api():
        """2026-07-21 patch 17: Bot 整體健康狀態(給虱董看)。

        Returns:
            - service: alive-checkin
            - bot_name: 每日平安
            - uptime_seconds: 進程啟動後秒數
            - users_total: 註冊人數
            - guardian_groups_total: 守護群綁定總數
            - guardian_groups_active: 有效的守護群數
            - timestamp: 當下時間
            - line_token_has_value / line_secret_has_value: env 是否有值（不回傳內容）
            - line_token_ok / line_token_http: 用 /v2/bot/info 探測 token 是否被 LINE 接受
        """
        state = load_state(app.config["DATA_FILE"])
        groups = state.get("guardian_groups", {})
        active_groups = sum(1 for g in groups.values() if g.get("status") == "active")
        now = datetime.now()
        proc_start = getattr(app, "_start_time", None)
        uptime = (now - proc_start).total_seconds() if proc_start else None
        token = (
            app.config.get("LINE_CHANNEL_ACCESS_TOKEN")
            or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
            or os.environ.get("CHANNEL_ACCESS_TOKEN")
            or ""
        ).strip()
        secret = (
            app.config.get("LINE_CHANNEL_SECRET")
            or os.environ.get("LINE_CHANNEL_SECRET")
            or os.environ.get("CHANNEL_SECRET")
            or ""
        ).strip()
        line_token_ok = None
        line_token_http = None
        if token:
            try:
                import urllib.request

                req = urllib.request.Request(
                    "https://api.line.me/v2/bot/info",
                    headers={"Authorization": f"Bearer {token}"},
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    line_token_http = int(getattr(resp, "status", 200) or 200)
                    line_token_ok = line_token_http == 200
            except Exception as exc:
                code = getattr(getattr(exc, "code", None), "real", None) or getattr(exc, "code", None)
                try:
                    line_token_http = int(code) if code is not None else None
                except Exception:
                    line_token_http = None
                line_token_ok = False
                app.logger.warning(
                    "line token probe failed http=%s err=%s",
                    line_token_http,
                    type(exc).__name__,
                )
        return jsonify({
            "service": "alive-checkin",
            "bot_name": "每日平安",
            "deploy_version": os.environ.get("DEPLOY_VERSION") or "W250723ae",
            "uptime_seconds": round(uptime, 1) if uptime else None,
            "users_total": len(state.get("users", {})),
            "guardian_groups_total": len(groups),
            "guardian_groups_active": active_groups,
            "timestamp": now.isoformat(timespec="seconds"),
            "line_token_has_value": bool(token),
            "line_secret_has_value": bool(secret),
            "line_token_ok": line_token_ok,
            "line_token_http": line_token_http,
        })

    @app.get("/api/status")
    def status():
        """LIFF 首載：有有效身分就 upsert，避免 DB 被 ephemeral disk 清掉後卡 404。"""
        line_user_id, err = _authenticated_line_user({}, use_args=True)
        if err:
            return jsonify(err[0]), err[1]
        display_name = (request.args.get("display_name") or "").strip()
        state = load_state(app.config["DATA_FILE"])
        profile = state.get("users", {}).get(line_user_id)
        if not profile:
            data, code = register_line_user(
                app.config["DATA_FILE"],
                {
                    "line_user_id": line_user_id,
                    "display_name": display_name or "LINE 使用者",
                },
            )
            if code != 200:
                return jsonify(data), code
            if isinstance(data, dict):
                data["auto_registered"] = True
            return jsonify(data)
        return jsonify(build_status(profile, state))

    @app.post("/api/line/register")
    def line_register():
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        payload["line_user_id"] = line_user_id
        data, code = register_line_user(app.config["DATA_FILE"], payload)
        return jsonify(data), code

    @app.post("/api/checkin")
    def checkin():
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        payload["line_user_id"] = line_user_id
        state = load_state(app.config["DATA_FILE"])
        if line_user_id not in state.get("users", {}):
            # 與 /api/status 相同：已驗證身分即可補註冊，避免 wipe 後無法簽到
            register_line_user(
                app.config["DATA_FILE"],
                {
                    "line_user_id": line_user_id,
                    "display_name": str(payload.get("display_name") or "LINE 使用者"),
                },
            )
        status = record_checkin(app.config["DATA_FILE"], payload)
        status["ok"] = True
        return jsonify(status)

    @app.post("/callback")
    def line_callback():
        if LineBotApi is None or WebhookHandler is None:
            return jsonify({"error": "line-bot-sdk is not installed"}), 503
        token = (
            app.config.get("LINE_CHANNEL_ACCESS_TOKEN")
            or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
            or os.environ.get("CHANNEL_ACCESS_TOKEN")
            or ""
        ).strip()
        secret = (
            app.config.get("LINE_CHANNEL_SECRET")
            or os.environ.get("LINE_CHANNEL_SECRET")
            or os.environ.get("CHANNEL_SECRET")
            or ""
        ).strip()
        if not token or not secret:
            return jsonify({"error": "LINE credentials are not configured"}), 503

        line_bot_api = LineBotApi(token)
        handler = WebhookHandler(secret)

        def _sos_handle(line_bot_api, line_user_id, command, reply_token=None, group_id=None):
            """需要幫忙：先回緊急求助 Flex；通知家人走 3 連按。

            command:
              - '需要幫忙' / 'SOS' / 'sos' / '緊急求助' : 入口卡（撥打 + 通知家人）
              - '通知家人' : 3 連按累計
              - '取消需要幫忙' / 'SOS 取消' : 取消 pending
            """
            state = load_state(app.config["DATA_FILE"])
            profile = get_profile(state, line_user_id) if line_user_id else None
            app.logger.info(
                "sos_handle command=%s user=%s group=%s",
                command,
                (line_user_id or "")[:8],
                (group_id or "")[:8],
            )

            def reply(flex, alt_text=""):
                messages = []
                if FlexSendMessage is not None and flex is not None:
                    messages.append(FlexSendMessage(alt_text=alt_text, contents=flex))
                else:
                    messages.append(TextSendMessage(text=alt_text or "需要幫忙"))
                try:
                    if reply_token:
                        line_bot_api.reply_message(reply_token, messages)
                        return
                except Exception as exc:
                    app.logger.exception("sos reply_message failed: %s", exc)
                # reply_token 失敗或未提供 → push 到同一個對話
                push_target = group_id or line_user_id
                if not push_target:
                    app.logger.error("sos send aborted: no push target")
                    return
                try:
                    line_bot_api.push_message(push_target, messages)
                except Exception as exc:
                    app.logger.exception("sos push_message failed: %s", exc)

            entry_commands = ("需要幫忙", "SOS", "sos", "緊急求助")
            notify_commands = (
                "通知家人",
                "聯絡家人連按3次",
                "需要幫忙確認",
                "SOS 確認 2",
                "SOS 確認 3",
            )
            cancel_commands = ("SOS 取消", "取消需要幫忙")

            if command in cancel_commands:
                if sos_flow.sos_cancel_pending(state, line_user_id):
                    save_state(app.config["DATA_FILE"], state)
                    reply(sos_flow.sos_cancelled_flex(), "✅ 已取消需要幫忙")
                else:
                    reply(None, "沒有待取消的需要幫忙通知")
                return

            # 入口卡：一律回緊急 Flex（不擋方案；實際通知再檢查）
            pending = sos_flow.sos_get_pending(state, line_user_id) if line_user_id else None
            pending_active = bool(
                pending
                and pending.get("stage") not in ("cancelled", "sent")
                and int(pending.get("tap_count") or 0) > 0
            )
            if command in entry_commands and not pending_active:
                family_tel = None
                family_label = None
                if profile:
                    contacts = sorted(
                        (profile.get("contacts") or []),
                        key=lambda c: int(c.get("priority") or 9999),
                    )
                    for contact in contacts:
                        phone = str(contact.get("phone") or contact.get("mobile") or "").strip()
                        digits = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
                        if digits:
                            family_tel = digits
                            family_label = contact.get("name") or contact.get("relationship") or "家人"
                            break
                liff_sos = (
                    liff_entry_url(open_action="sos")
                    if liff_entry_url
                    else "https://liff.line.me/2010674803-rK98c0lo/?open=sos"
                )
                reply(
                    sos_flow.sos_emergency_flex(
                        family_tel=family_tel,
                        family_label=family_label,
                        liff_sos_uri=liff_sos,
                    ),
                    "🆘 需要幫忙 — 連按 3 次通知家人",
                )
                return

            if command not in notify_commands and command not in entry_commands:
                reply(None, "請傳送「需要幫忙」開啟求助選項")
                return

            # === 通知家人：SOS 不依價格分級，全員可用 ===
            rules = plan_rules(profile) if profile else PLAN_LIMITS.get("trial", {})
            sos_enabled = bool(rules.get("sos_enabled", True))

            if not sos_enabled:
                liff_sos = (
                    liff_entry_url(open_action="sos")
                    if liff_entry_url
                    else "https://liff.line.me/2010674803-rK98c0lo/?open=sos"
                )
                reply(
                    sos_flow.sos_emergency_flex(liff_sos_uri=liff_sos),
                    "目前可先打電話求助；系統暫時無法通知家人，請稍後再試",
                )
                return

            # 記錄一次點選（3 連按）
            result = sos_flow.sos_tap(state, line_user_id)
            entry = result.get("entry", {})
            action = result.get("action")
            tap_count = entry.get("tap_count", 1)

            if action == "sent":
                reply(sos_flow.sos_sent_flex(), "🚨 已通知家人需要幫忙")
                save_state(app.config["DATA_FILE"], state)
                return

            if tap_count >= 3:
                try:
                    res, code = trigger_sos(
                        app.config["DATA_FILE"],
                        {"line_user_id": line_user_id, "via": "3tap"},
                        app.config,
                    )
                    if code >= 400:
                        sos_flow.sos_cancel_pending(state, line_user_id)
                        err = (res or {}).get("error") if isinstance(res, dict) else "send failed"
                        app.logger.error("trigger_sos failed code=%s err=%s", code, err)
                        if "no bound line guardians" in str(err).lower():
                            invite_uri = (
                                share_invite_liff_url()
                                if share_invite_liff_url
                                else "https://liff.line.me/2010674803-rK98c0lo/liff/share-invite.html"
                            )
                            reply(
                                sos_flow.sos_no_guardians_flex(invite_uri),
                                sos_user_facing_error(err),
                            )
                        else:
                            reply(None, sos_user_facing_error(err))
                    else:
                        event_id = res.get("event_id") if isinstance(res, dict) else None
                        sos_flow.sos_mark_sent(state, line_user_id, event_id)
                        reply(sos_flow.sos_sent_flex(), "🚨 已通知家人需要幫忙")
                except Exception as exc:
                    app.logger.exception("trigger_sos exception")
                    sos_flow.sos_cancel_pending(state, line_user_id)
                    reply(None, sos_user_facing_error(exc))
                save_state(app.config["DATA_FILE"], state)
                return

            reply(sos_flow.sos_warning_flex(tap_count), f"🚨 需要幫忙 ({tap_count}/3)")
            save_state(app.config["DATA_FILE"], state)

        def _send_welcome(line_bot_api, reply_token=None, line_user_id=None, display_name=None, trigger=None):
            """Follow / 關鍵字共用：送 welcome_flex，失敗寫 log 並 push fallback。"""
            # 每次發送前再取一次真實暱稱（避免 Follow 當下 profile 失敗變成空白／「您」）
            resolved = resolve_welcome_display_name(
                line_bot_api=line_bot_api,
                data_file=app.config["DATA_FILE"],
                line_user_id=line_user_id,
                hint=display_name,
                logger=app.logger,
            )
            if welcome_greeting_text is not None:
                greeting = welcome_greeting_text(resolved)
            elif resolved:
                greeting = f"👋 {resolved} 您好，歡迎加入「每日平安」"
            else:
                greeting = "👋 您好，歡迎加入「每日平安」"
            app.logger.info(
                "welcome_flex start trigger=%s user=%s name=%r has_reply=%s",
                trigger or "unknown",
                (line_user_id or "")[:8],
                resolved or "",
                bool(reply_token),
            )
            setup_uri = (
                liff_entry_url(open_action="onboarding")
                if liff_entry_url
                else "https://liff.line.me/2010674803-rK98c0lo/?open=onboarding"
            )
            pricing_uri = (
                pricing_direct_url()
                if pricing_direct_url
                else "https://alive-checkin.onrender.com/liff/pricing.html"
            )
            welcome_fallback = (
                f"{greeting}\n\n"
                "每天 10 秒，報個平安\n"
                "平常不打擾，有事才通知守護人\n\n"
                "開始使用前兩個步驟：\n"
                "① 新增 1 位守護人\n"
                "② 設定每日提醒時間\n\n"
                "🎁 完成設定即可享 7 天免費安心體驗\n"
                "緊急狀況請直接撥打 119 或 110\n\n"
                f"立即開始設定：{setup_uri}\n"
                f"查看方案：{pricing_uri}\n"
                "傳「開始」可重拿歡迎卡"
            )
            alt_text = (
                f"每日平安｜{resolved} 您好，歡迎加入"
                if resolved
                else "每日平安｜您好，歡迎加入"
            )
            flex_contents = welcome_flex(resolved) if welcome_flex is not None else None
            if flex_contents is None:
                app.logger.error("welcome_flex contents is None — check import")
            try:
                if FlexSendMessage is not None and flex_contents is not None and reply_token:
                    line_bot_api.reply_message(
                        reply_token,
                        FlexSendMessage(alt_text=alt_text, contents=flex_contents),
                    )
                    app.logger.info("welcome_flex reply ok name=%r", resolved or "")
                    return
                if reply_token:
                    line_bot_api.reply_message(reply_token, TextSendMessage(text=welcome_fallback))
                    app.logger.warning("welcome text reply fallback")
                    return
            except Exception as exc:
                app.logger.exception("welcome reply failed: %s", exc)
            if line_user_id and FlexSendMessage is not None and flex_contents is not None:
                try:
                    line_bot_api.push_message(
                        line_user_id,
                        FlexSendMessage(alt_text=alt_text, contents=flex_contents),
                    )
                    app.logger.info("welcome_flex push ok name=%r", resolved or "")
                    return
                except Exception as exc:
                    app.logger.exception("welcome push flex failed: %s", exc)
                    try:
                        # Capture exact LINE error body when available
                        err_body = getattr(exc, "error", None) or getattr(exc, "response", None)
                        app.logger.error("welcome push flex LINE detail: %s", err_body)
                    except Exception:
                        pass
            if line_user_id:
                try:
                    line_bot_api.push_message(line_user_id, TextSendMessage(text=welcome_fallback))
                    app.logger.warning("welcome text push fallback")
                except Exception as exc:
                    app.logger.exception("welcome push text failed: %s", exc)

        @handler.add(JoinEvent)
        def handle_group_join(event):
            """Bot 被邀進群 → 必送守護群歡迎卡（不依賴自動綁定成功）。"""
            line_user_id = getattr(event.source, "user_id", None)
            group_id = getattr(event.source, "group_id", None)
            room_id = getattr(event.source, "room_id", None)
            target_id = group_id or room_id
            app.logger.info(
                "JoinEvent group=%s room=%s inviter=%s",
                (group_id or "")[:12],
                (room_id or "")[:12],
                (line_user_id or "")[:8],
            )

            # JoinEvent 通常沒有 user_id；不要因無法自動綁定就拒送歡迎卡
            outcome, _status = {"reply_text": "歡迎加入守護群", "should_leave": False}, 200
            if line_user_id and group_id:
                try:
                    outcome, _status = guardian_group_join_outcome(
                        app.config["DATA_FILE"], line_user_id, group_id
                    )
                except Exception as exc:
                    app.logger.exception("guardian_group_join_outcome failed: %s", exc)
                    outcome, _status = {"reply_text": "歡迎加入守護群", "should_leave": False}, 200

            owner_info = {
                "bound": False,
                "is_owner": False,
                "owner_id": None,
                "is_active": False,
                "owner_plan": None,
            }
            try:
                state = load_state(app.config["DATA_FILE"])
                existing_group = state.get("guardian_groups", {}).get(group_id or "", {})
                if existing_group.get("status") == "active":
                    owner_id = existing_group.get("owner_line_user_id")
                    owner_profile = state.get("users", {}).get(owner_id, {})
                    owner_plan = owner_profile.get("plan")
                    is_active = bool(owner_profile) and paid_membership_is_active(owner_profile)
                    owner_info = {
                        "bound": True,
                        "is_owner": (line_user_id == owner_id) if line_user_id else False,
                        "owner_id": owner_id,
                        "is_active": is_active,
                        "owner_plan": owner_plan,
                    }
            except Exception as exc:
                app.logger.exception("join owner_info load failed: %s", exc)

            sent = False
            try:
                if FlexSendMessage is not None and guardian_group_intro_flex is not None:
                    flex = guardian_group_intro_flex(owner_info)
                    line_bot_api.reply_message(
                        event.reply_token,
                        FlexSendMessage(
                            alt_text="❤️ 每日平安｜歡迎加入守護群",
                            contents=flex,
                        ),
                    )
                    sent = True
                else:
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text=outcome.get("reply_text") or "歡迎加入守護群，請管理員點「點我綁定守護群」"),
                    )
                    sent = True
            except Exception as exc:
                app.logger.exception("JoinEvent reply intro failed: %s", exc)

            if not sent and target_id:
                try:
                    if FlexSendMessage is not None and guardian_group_intro_flex is not None:
                        line_bot_api.push_message(
                            target_id,
                            FlexSendMessage(
                                alt_text="❤️ 每日平安｜歡迎加入守護群",
                                contents=guardian_group_intro_flex(owner_info),
                            ),
                        )
                    else:
                        line_bot_api.push_message(
                            target_id,
                            TextSendMessage(text="歡迎加入守護群，請管理員傳送「點我綁定守護群」完成設定"),
                        )
                except Exception as exc:
                    app.logger.exception("JoinEvent push intro failed: %s", exc)

            # 僅在群已被其他會員佔用時離開
            if group_id and _status == 409:
                try:
                    line_bot_api.leave_group(group_id)
                except Exception as exc:
                    app.logger.exception("leave_group failed: %s", exc)

        @handler.add(FollowEvent)
        def handle_follow(event):
            """加好友歡迎：優先回 Flex(真實暱稱問候 + 立即開始設定)。"""
            line_user_id = getattr(event.source, "user_id", None)
            display_name = resolve_welcome_display_name(
                line_bot_api=line_bot_api,
                data_file=app.config["DATA_FILE"],
                line_user_id=line_user_id,
                logger=app.logger,
            )
            if line_user_id:
                # Follow 當下就寫入 users，之後開 LIFF 不會因缺 row 而 404
                try:
                    register_line_user(
                        app.config["DATA_FILE"],
                        {
                            "line_user_id": line_user_id,
                            "display_name": display_name or "LINE 使用者",
                        },
                    )
                except Exception as exc:
                    app.logger.exception("FollowEvent register failed: %s", exc)
            app.logger.info(
                "FollowEvent welcome trigger user=%s name=%r",
                (line_user_id or "")[:8],
                display_name or "",
            )
            _send_welcome(
                line_bot_api,
                reply_token=event.reply_token,
                line_user_id=line_user_id,
                display_name=display_name,
                trigger="follow",
            )

        @handler.add(MemberJoinedEvent)
        def handle_member_joined(event):
            # 2026-07-20 蝦董 added: 超過 50 人上限時,請出新成員
            # 2026-07-21 patch 11: 額外提示「記得把 Bot 設為管理員」
            if getattr(event.source, "type", None) != "group":
                return
            group_id = getattr(event.source, "group_id", None)
            if not group_id:
                return
            try:
                new_ids = [m.user_id for m in (event.joined.members or []) if getattr(m, "user_id", None)]
                result, code = enforce_group_member_limit(group_id, dict(app.config))
                if code != 200 or not result.get("enforced"):
                    return
                msg_lines = [
                    f"⚠️ 守護群超過 {GROUP_MEMBER_LIMIT} 人上限。",
                    f"目前成員數:{result.get('current_count')}/{GROUP_MEMBER_LIMIT}",
                ]
                if result.get("kicked"):
                    msg_lines.append(f"已請出 {len(result['kicked'])} 位新成員。")
                if result.get("bot_not_admin_count"):
                    msg_lines.append(
                        f"⚠️ 「每日平安」不是此群管理員,另有 {result['bot_not_admin_count']} 位無法請出。"
                        "請把「每日平安」設為管理員後再試,或管理員手動退出超額成員。"
                    )
                if result.get("failed") and not result.get("bot_not_admin_count"):
                    msg_lines.append(f"請出失敗:{len(result['failed'])} 位。")
                # 2026-07-21 patch 11: 額外提醒把 Bot 設為管理員
                msg_lines.append("💡 在群裡打「管理員設定」可看 6 步驟教學")
                line_bot_api.push_message(group_id, TextSendMessage(text="\n".join(msg_lines)))
            except Exception:
                pass

        @handler.add(MessageEvent, message=TextMessage)
        def handle_text_message(event):
            text = event.message.text
            line_user_id = getattr(event.source, "user_id", None)
            group_id = getattr(event.source, "group_id", None)
            stripped = text.strip()

            # 歡迎詞關鍵字（已是好友也可重拿歡迎卡；不需取消好友）
            # 純關鍵字或「開始！」等標點也可觸發，避免 OA 打招呼舊訊造成誤會
            welcome_keys = ("開始", "歡迎", "說明", "歡迎詞")
            if stripped in welcome_keys or stripped.rstrip("！!。.~～ ") in welcome_keys:
                app.logger.info(
                    "welcome keyword hit text=%r user=%s",
                    stripped[:20],
                    (line_user_id or "")[:8],
                )
                display_name = resolve_welcome_display_name(
                    line_bot_api=line_bot_api,
                    data_file=app.config["DATA_FILE"],
                    line_user_id=line_user_id,
                    logger=app.logger,
                )
                if line_user_id:
                    try:
                        register_line_user(
                            app.config["DATA_FILE"],
                            {
                                "line_user_id": line_user_id,
                                "display_name": display_name or "LINE 使用者",
                            },
                        )
                    except Exception as exc:
                        app.logger.exception("welcome keyword register failed: %s", exc)
                _send_welcome(
                    line_bot_api,
                    reply_token=event.reply_token,
                    line_user_id=line_user_id,
                    display_name=display_name,
                    trigger=f"keyword:{stripped[:20]}",
                )
                return

            # 需要幫忙 / 緊急求助 / 通知家人（3 連按）
            if sos_flow is not None and stripped in (
                "需要幫忙",
                "SOS",
                "sos",
                "緊急求助",
                "通知家人",
                "聯絡家人連按3次",
                "需要幫忙確認",
                "SOS 確認 2",
                "SOS 確認 3",
                "SOS 取消",
                "取消需要幫忙",
            ):
                _sos_handle(
                    line_bot_api,
                    line_user_id,
                    stripped,
                    reply_token=event.reply_token,
                    group_id=group_id,
                )
                return

            # 2026-07-21 patch 17: BOT 狀態查詢(DM + 群組都可用)
            if stripped in ("BOT 狀態", "bot 狀態", "機器人狀態", "機器人狀況"):
                state = load_state(app.config["DATA_FILE"])
                groups = state.get("guardian_groups", {})
                active_groups = sum(1 for g in groups.values() if g.get("status") == "active")
                uptime_sec = (datetime.now() - app._start_time).total_seconds()
                hours = int(uptime_sec // 3600)
                minutes = int((uptime_sec % 3600) // 60)
                status_text = (
                    f"🤖 我是「每日平安」\\n"
                    f"屬於「每日平安」這個服務\\n\\n"
                    f"✅ 目前啟用中(已連續 {hours} 小時 {minutes} 分)\\n"
                    f"👥 已註冊人數:{len(state.get('users', {}))}\\n"
                    f"🛡️ 守護群:{active_groups} 群有效綁定\\n\\n"
                    f"🔧 可用指令(私訊):\\n"
                    f"• 簽到 / 報平安\\n"
                    f"• 綁定守護人\\n"
                    f"• 查看方案 / 我的狀態\\n\\n"
                    f"👥 群組指令:管理員設定 / 使用說明 / 守護群狀態"
                )
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=status_text))
                return

            # 2026-07-21 patch 11: 守護群相關 4 個 Flex 指令(群組限定)
            if group_id:
                # 1) 綁定守護群(保留舊指令 alias)
                if stripped in ("點我綁定守護群", "綁定守護群", "綁定平安守護助理"):
                    result, code = bind_guardian_group(
                        app.config["DATA_FILE"],
                        {"line_user_id": line_user_id, "group_id": group_id},
                    )
                    if FlexSendMessage is not None and guardian_group_bind_confirm_flex is not None:
                        if code == 200:
                            line_bot_api.reply_message(
                                event.reply_token,
                                FlexSendMessage(
                                    alt_text="✅ 我已完成守護群設定",
                                    contents=guardian_group_bind_confirm_flex(result),
                                ),
                            )
                        else:
                            reason = result.get(
                                "reply_text",
                                "這個群組目前無法啟用守護功能,請檢查 799 訂閱狀態或由原建立者操作",
                            )
                            line_bot_api.reply_message(
                                event.reply_token,
                                FlexSendMessage(
                                    alt_text="❌ 無法綁定此群",
                                    contents=guardian_group_bind_fail_flex(reason),
                                ),
                            )
                    else:
                        # fallback 純文字：成功回覆固定「我已完成守護群設定」
                        if code == 200:
                            reply_text = (
                                "我已完成守護群設定\n"
                                f"目前已綁定 {result.get('guardian_group_count', 1)}/"
                                f"{result.get('guardian_group_limit', 3)} 個群組。"
                            )
                        elif result.get("should_leave"):
                            reply_text = (
                                "這個群組目前無法啟用守護功能。守護群限有效的 799 月費或年費會員建立；月費最多 1 群，年費最多 3 群。\n"
                                "請先完成升級，再重新邀請「每日平安」；我現在會退出群組。"
                            )
                        else:
                            reply_text = "這個群組已綁定其他會員，請由原建立者管理守護設定。"
                        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
                    if result.get("should_leave"):
                        line_bot_api.leave_group(group_id)
                    return

                # 2) 守護群狀態
                if stripped in ("守護群狀態", "群狀態", "狀態"):
                    state = load_state(app.config["DATA_FILE"])
                    profile = get_profile(state, line_user_id) or {}
                    if FlexSendMessage is not None and guardian_group_status_flex is not None:
                        line_bot_api.reply_message(
                            event.reply_token,
                            FlexSendMessage(
                                alt_text="守護群狀態",
                                contents=guardian_group_status_flex(profile, state),
                            ),
                        )
                    else:
                        reply_text = f"守護群數量：{len(profile.get('guardian_group_ids') or [])}"
                        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
                    return

                # 2-1) 今日平安名單：只有群組建立者/管理員可看詳細資料
                if stripped in ("今日狀態", "今日平安狀態", "誰沒報平安", "未報平安", "誰還沒簽到"):
                    reply_text, _status = guardian_group_daily_status_text(
                        app.config["DATA_FILE"], line_user_id, group_id
                    )
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
                    return

                # 3) 使用說明 / 使用者說明
                if stripped in ("使用說明", "使用者說明", "教學", "怎麼用"):
                    if FlexSendMessage is not None and guardian_group_user_guide_flex is not None:
                        line_bot_api.reply_message(
                            event.reply_token,
                            FlexSendMessage(
                                alt_text="📖 守護群使用說明",
                                contents=guardian_group_user_guide_flex(),
                            ),
                        )
                    else:
                        line_bot_api.reply_message(
                            event.reply_token,
                            TextSendMessage(text="使用說明:1.升級 799 → 2.建群 → 3.邀「每日平安」 → 4.設管理員 → 5.輸入「點我綁定守護群」"),
                        )
                    return

                # 4) 管理員設定 / 怎麼設管理員
                if stripped in ("管理員設定", "設管理員", "怎麼設管理員", "6步驟"):
                    if FlexSendMessage is not None and guardian_group_admin_setup_flex is not None:
                        line_bot_api.reply_message(
                            event.reply_token,
                            FlexSendMessage(
                                alt_text="⚙️ 設定「每日平安」為管理員 6 步驟",
                                contents=guardian_group_admin_setup_flex(),
                            ),
                        )
                    else:
                        line_bot_api.reply_message(
                            event.reply_token,
                            TextSendMessage(text="管理員設定 6 步驟:1.群右上「≡」→ 2.選成員 → 3.長按「每日平安」 → 4.設為管理員 → 5.確定 → 6.完成"),
                        )
                    return

            status = None
            if any(keyword in text for keyword in CHECKIN_KEYWORDS):
                status = record_checkin(app.config["DATA_FILE"], {"line_user_id": line_user_id})
            elif any(keyword in text for keyword in STATUS_KEYWORDS):
                state = load_state(app.config["DATA_FILE"])
                status = build_status(get_profile(state, line_user_id))
            if should_create_support_ticket(text):
                create_support_ticket(
                    app.config["DATA_FILE"],
                    {
                        "line_user_id": line_user_id,
                        "message": text,
                    },
                )
                reply_text = "你的問題已經記錄下來，客服人員會盡快回覆你。若是立即危險，請先撥打 119。"
            else:
                reply_text = line_auto_reply_text(text, status)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

        signature = request.headers.get("X-Line-Signature", "")
        # Use raw bytes then decode so HMAC matches LINE's signed body exactly
        body_bytes = request.get_data(cache=True, as_text=False) or b""
        try:
            body = body_bytes.decode("utf-8")
        except UnicodeDecodeError:
            # LINE Console Verify must never see non-200
            app.logger.error("callback body not utf-8 len=%s", len(body_bytes))
            return jsonify({"ok": True, "verify": True})

        # Soft-accept: empty / no-events payloads always 200 (LINE Verify button)
        stripped = (body or "").strip()
        if not stripped:
            return jsonify({"ok": True, "verify": True})
        try:
            probe = json.loads(stripped)
            if isinstance(probe, dict) and not (probe.get("events") or []):
                # Still run handler when signature is valid; on mismatch return 200
                try:
                    handler.handle(body, signature)
                except InvalidSignatureError:
                    app.logger.warning(
                        "LINE verify/empty events bad signature body_len=%s secret_len=%s",
                        len(body_bytes),
                        len(secret or ""),
                    )
                except Exception as exc:  # noqa: BLE001
                    app.logger.warning("LINE verify/empty handle skip: %s", type(exc).__name__)
                return jsonify({"ok": True, "verify": True})
        except Exception:
            pass

        try:
            handler.handle(body, signature)
        except InvalidSignatureError:
            # LINE docs: always return 200 to the platform; do not process bad-sig events
            app.logger.warning(
                "invalid LINE signature ignored body_len=%s sig_len=%s secret_len=%s",
                len(body_bytes),
                len(signature or ""),
                len(secret or ""),
            )
            return jsonify({"ok": True, "signature": "ignored"})
        except LineBotApiError as exc:
            app.logger.exception("callback LineBotApiError: %s", exc)
            # Still 200 so LINE does not disable webhook / fail Verify-like probes
            return jsonify({"ok": True, "line_api_error": True})
        except Exception as exc:  # noqa: BLE001
            app.logger.exception("callback unexpected: %s", exc)
            return jsonify({"ok": True, "error_ignored": True})
        return jsonify({"ok": True})

    @app.post("/api/warning/cancel")
    def warning_cancel_api():
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        payload["line_user_id"] = line_user_id
        return jsonify(cancel_warning(app.config["DATA_FILE"], payload, app.config))

    @app.post("/api/settings")
    def settings():
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        payload["line_user_id"] = line_user_id
        return jsonify(save_settings_for_profile(app.config["DATA_FILE"], payload))

    @app.post("/api/billing/preferences")
    def billing_preferences_api():
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        payload["line_user_id"] = line_user_id
        data, code = save_billing_preferences(app.config["DATA_FILE"], payload)
        return jsonify(data), code

    @app.post("/api/payments/orders")
    def payment_orders_api():
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        payload["line_user_id"] = line_user_id
        data, code = create_payment_order(app.config["DATA_FILE"], payload, app.config)
        return jsonify(data), code

    @app.post("/webhook/newebpay")
    @app.post("/api/payment/newebpay/notify")
    def newebpay_webhook():
        """藍新 NotifyURL — 驗簽後自動開通方案（冪等 confirm）。

        兩個路徑等效，擇一填入商店後台即可：
        - /api/payment/newebpay/notify（checkout 預設）
        - /webhook/newebpay
        成功時回傳純文字 SUCCESS（藍新偏好）。
        """
        form = request.form.to_dict() if request.form else (request.get_json(silent=True) or {})
        if newebpay is None:
            return jsonify({"error": "newebpay module missing"}), 503
        parsed, error = newebpay.parse_notify_payload(form, app.config)
        if error:
            return jsonify({"error": error}), 400
        if not newebpay.notify_success(parsed):
            return Response("SUCCESS", mimetype="text/plain"), 200
        data, code = confirm_payment_order(
            app.config["DATA_FILE"],
            {
                "order_id": parsed.get("order_id"),
                "transaction_id": parsed.get("transaction_id"),
            },
            app.config,
        )
        if code >= 400:
            return jsonify(data), code
        return Response("SUCCESS", mimetype="text/plain"), 200

    @app.route("/payment-success", methods=["GET", "POST"])
    def payment_success_page():
        # 藍新 ReturnURL 常以 POST 帶回付款結果；與 GET 同樣回傳 SPA。
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/api/contacts")
    def contacts_get():
        line_user_id, err = _authenticated_line_user({}, use_args=True)
        if err:
            return jsonify(err[0]), err[1]
        return jsonify(get_contacts(app.config["DATA_FILE"], line_user_id))

    @app.post("/api/contacts")
    def contacts_post():
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        payload["line_user_id"] = line_user_id
        data, code = save_contacts(app.config["DATA_FILE"], payload)
        return jsonify(data), code

    @app.get("/api/calendar-notes")
    def calendar_notes_get():
        return jsonify(get_calendar_notes(app.config["DATA_FILE"], request.args.get("line_user_id")))

    @app.post("/api/calendar-notes")
    def calendar_notes_post():
        data, code = save_calendar_note(app.config["DATA_FILE"], request.get_json(silent=True) or {})
        return jsonify(data), code

    @app.post("/api/contacts/add")
    def contacts_add():
        """新增單一守護人聯絡人。"""
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        data, code = add_single_contact(app.config["DATA_FILE"], line_user_id, payload)
        if code == 200:
            response = {"ok": True, "contact": data["contact"], "contacts": data["contacts"], "contact_limit": data["contact_limit"]}
        else:
            response = {"ok": False, "error": data.get("error"), "fields": data.get("fields"), "contact_limit": data.get("contact_limit"), "current_count": data.get("current_count"), "message": data.get("message")}
        return jsonify(response), code

    @app.put("/api/contacts/<contact_id>")
    def contacts_update(contact_id):
        """更新單一守護人聯絡人。"""
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        data, code = update_single_contact(app.config["DATA_FILE"], line_user_id, contact_id, payload)
        if code == 200:
            response = {"ok": True, "contact": data["contact"], "contacts": data["contacts"]}
        else:
            response = {"ok": False, "error": data.get("error"), "fields": data.get("fields")}
        return jsonify(response), code

    @app.delete("/api/contacts/<contact_id>")
    def contacts_delete(contact_id):
        """刪除單一守護人聯絡人。"""
        line_user_id, err = _authenticated_line_user({}, use_args=True)
        if err:
            return jsonify(err[0]), err[1]
        data, code = delete_single_contact(app.config["DATA_FILE"], line_user_id, contact_id)
        if code == 200:
            response = {"ok": True, "deleted": True, "contact_id": data["contact_id"], "contacts": data["contacts"]}
        else:
            response = {"ok": False, "error": data.get("error"), "contact_id": data.get("contact_id")}
        return jsonify(response), code

    @app.get("/api/onboarding")
    def onboarding_get():
        """回傳使用者 onboarding 狀態。"""
        line_user_id = (request.args.get("line_user_id") or "").strip()
        if not line_user_id:
            return jsonify({"ok": False, "error": "missing line_user_id"}), 400
        state = load_state(app.config["DATA_FILE"])
        profile = state.get("users", {}).get(line_user_id)
        if not profile:
            return jsonify({"ok": False, "error": "user not registered"}), 404
        if ensure_onboarding_completed_flag(profile):
            save_state(app.config["DATA_FILE"], state)
        contacts = profile.get("contacts") or []
        has_guardian = profile_has_guardian(profile)
        setup_done = profile_setup_completed(profile)
        times = reminder_times_for_profile(profile)
        return jsonify({
            "ok": True,
            "line_user_id": line_user_id,
            "is_onboarding_completed": setup_done,
            "setup_completed": setup_done,
            "has_guardian": has_guardian,
            "guardian_count": len(contacts),
            "reminder_time": times[0] if times else "12:00",
            "reminder_times": times,
            "daily_reminders": int(plan_rules(profile).get("daily_reminders") or 1),
            "default_reminder_times": default_reminder_times_for_count(
                plan_rules(profile).get("daily_reminders") or 1
            ),
            "plan": profile.get("plan", "trial"),
            "display_name": profile.get("display_name", ""),
        })

    @app.get("/api/interaction-state")
    def interaction_state_get():
        """讀取使用者互動狀態(防每日重複相同內容用)。"""
        line_user_id = (request.args.get("line_user_id") or "").strip()
        if not line_user_id:
            return jsonify({"ok": False, "error": "missing line_user_id"}), 400
        state = load_state(app.config["DATA_FILE"])
        profile = state.get("users", {}).get(line_user_id)
        if not profile:
            return jsonify({"ok": False, "error": "user not registered"}), 404
        istate = get_or_create_interaction_state(profile)
        save_state(app.config["DATA_FILE"], state)
        return jsonify({"ok": True, "line_user_id": line_user_id, "interaction_state": istate})

    @app.post("/api/interaction-state")
    def interaction_state_post():
        """更新使用者互動狀態(completed_steps / dismissed_prompts / last_closing_message 等)。"""
        payload = request.get_json(silent=True) or {}
        line_user_id = (payload.get("line_user_id") or "").strip()
        if not line_user_id:
            return jsonify({"ok": False, "error": "missing line_user_id"}), 400
        state = load_state(app.config["DATA_FILE"])
        profile = state.get("users", {}).get(line_user_id)
        if not profile:
            return jsonify({"ok": False, "error": "user not registered"}), 404
        istate = get_or_create_interaction_state(profile)
        # 合併允許更新的欄位
        for field in ("last_interaction_at", "last_interaction_summary",
                      "next_reminder_at", "last_closing_message",
                      "onboarding_completed", "guardian_prompt_status"):
            if field in payload:
                istate[field] = payload[field]
        if "completed_steps" in payload and isinstance(payload["completed_steps"], list):
            istate["completed_steps"] = list(set(istate.get("completed_steps", []) + payload["completed_steps"]))
        if "pending_steps" in payload and isinstance(payload["pending_steps"], list):
            istate["pending_steps"] = payload["pending_steps"]
        if "dismissed_prompts" in payload and isinstance(payload["dismissed_prompts"], dict):
            merged = istate.get("dismissed_prompts", {})
            merged.update(payload["dismissed_prompts"])
            istate["dismissed_prompts"] = merged
        istate["last_interaction_at"] = datetime.now().isoformat(timespec="seconds")
        save_state(app.config["DATA_FILE"], state)
        return jsonify({"ok": True, "interaction_state": istate})

    @app.post("/api/guardian-reminder/dismiss")
    def guardian_reminder_dismiss():
        """使用者對守護人完成度提示的回應。

        body.preference: 'now' | 'tomorrow' | 'dismiss_7d' | 'dismissed'
        """
        payload = request.get_json(silent=True) or {}
        line_user_id = (payload.get("line_user_id") or "").strip()
        pref = (payload.get("preference") or "").strip()
        if not line_user_id:
            return jsonify({"ok": False, "error": "missing line_user_id"}), 400
        if pref not in ("now", "tomorrow", "dismiss_7d", "dismissed"):
            return jsonify({"ok": False, "error": "invalid preference"}), 400
        state = load_state(app.config["DATA_FILE"])
        profile = state.get("users", {}).get(line_user_id)
        if not profile:
            return jsonify({"ok": False, "error": "user not registered"}), 404
        istate = get_or_create_interaction_state(profile)
        istate["guardian_reminder_preference"] = pref
        istate["guardian_last_prompted_at"] = datetime.now().isoformat(timespec="seconds")
        now = datetime.now()
        if pref == "tomorrow":
            istate["guardian_reminder_snoozed_until"] = (now + timedelta(days=1)).isoformat(timespec="seconds")
        elif pref == "dismiss_7d":
            istate["guardian_reminder_snoozed_until"] = (now + timedelta(days=7)).isoformat(timespec="seconds")
        else:
            istate["guardian_reminder_snoozed_until"] = ""
        save_state(app.config["DATA_FILE"], state)
        return jsonify({"ok": True, "interaction_state": istate})



    # Production 完全不註冊 dev endpoint(gunicorn 不跑 app.run(),debug 是 False)
    _is_dev = (
        os.environ.get("DEV_MODE", "").lower() in ("1", "true", "yes")
        or os.environ.get("FLASK_ENV", "").lower() in ("development", "dev")
        or app.debug
    )

    if _is_dev:
        @app.post("/api/dev/upgrade-plan")
        def dev_upgrade_plan():
            """DEV ONLY: 升級 plan (測試用)。

        Production 一律回 404。只有以下情況才允許呼叫:
        1. request.remote_addr 是 127.0.0.1 / ::1 (本機)
        2. 或 env DEV_MODE=true 明確啟用
        3. 或 host header 是 localhost / 127.0.0.1
        """
        # 1. 本機 IP 允許
        remote = (request.remote_addr or "").strip()
        host = (request.host or "").lower()
        is_local = remote in ("127.0.0.1", "::1", "localhost") or host.startswith("localhost") or host.startswith("127.")
        # 2. env 明確啟用
        dev_mode_enabled = os.environ.get("DEV_MODE", "").lower() in ("1", "true", "yes")
        if not (is_local or dev_mode_enabled):
            # Production 環境,拒絕存取(不透露 endpoint 存在)
            return jsonify({"ok": False, "error": "not_found"}), 404
        # 通過檢查,執行 dev 邏輯
        payload = request.get_json(silent=True) or {}
        line_user_id = (payload.get("line_user_id") or "").strip()
        plan = (payload.get("plan") or "paid_799_year").strip()
        if not line_user_id:
            return jsonify({"ok": False, "error": "missing line_user_id"}), 400
        state = load_state(app.config["DATA_FILE"])
        profile = state.get("users", {}).get(line_user_id)
        if not profile:
            return jsonify({"ok": False, "error": "user not registered"}), 404
        profile["plan"] = plan
        save_state(app.config["DATA_FILE"], state)
        return jsonify({"ok": True, "plan": plan}), 200

    @app.post("/api/onboarding/complete")
    def onboarding_complete():
        """標記 onboarding 完成(必須至少有 1 位守護人)。"""
        payload = request.get_json(silent=True) or {}
        line_user_id = (payload.get("line_user_id") or "").strip()
        if not line_user_id:
            return jsonify({"ok": False, "error": "missing line_user_id"}), 400
        state = load_state(app.config["DATA_FILE"])
        profile = state.get("users", {}).get(line_user_id)
        if not profile:
            return jsonify({"ok": False, "error": "user not registered"}), 404
        contacts = profile.get("contacts") or []
        has_guardian = profile_has_guardian(profile)
        if not has_guardian:
            return jsonify({
                "ok": False,
                "error": "guardian_required",
                "message": "必須先新增至少 1 位守護人"
            }), 400
        profile["is_onboarding_completed"] = True
        # 儲存提醒時段(多時段優先;未提供則套用方案預設)
        if "reminder_times" in payload or payload.get("reminder_time"):
            apply_reminder_times_to_profile(
                profile,
                times=payload.get("reminder_times"),
                single=payload.get("reminder_time"),
            )
        else:
            apply_reminder_times_to_profile(profile)
        # 初始化互動狀態,標記完成步驟
        istate = get_or_create_interaction_state(profile)
        istate["onboarding_completed"] = True
        if "add_first_guardian" not in istate["completed_steps"]:
            istate["completed_steps"].append("add_first_guardian")
        if "set_reminder_time" not in istate["completed_steps"]:
            istate["completed_steps"].append("set_reminder_time")
        if not istate.get("pending_steps"):
            istate["pending_steps"] = ["explore_app", "read_help", "add_more_guardians_if_paid"]
        istate["last_interaction_at"] = datetime.now().isoformat(timespec="seconds")
        save_state(app.config["DATA_FILE"], state)
        times = reminder_times_for_profile(profile)
        return jsonify({
            "ok": True,
            "is_onboarding_completed": True,
            "setup_completed": True,
            "reminder_time": times[0],
            "reminder_times": times,
            "interaction_state": istate,
        }), 200

    @app.post("/api/emergency-contact/bind")
    def emergency_contact_bind_api():
        data, code = bind_emergency_contact(app.config["DATA_FILE"], request.get_json(silent=True) or {}, app.config)
        return jsonify(data), code

    @app.post("/api/guardian-groups/bind")
    def guardian_groups_bind_api():
        data, code = bind_guardian_group(app.config["DATA_FILE"], request.get_json(silent=True) or {})
        return jsonify(data), code

    @app.post("/api/guardian-groups/unbind")
    def guardian_groups_unbind_api():
        data, code = unbind_guardian_group(app.config["DATA_FILE"], request.get_json(silent=True) or {})
        return jsonify(data), code

    @app.post("/api/guardian-groups/preferences")
    def guardian_groups_preferences_api():
        data, code = update_guardian_group_preferences(app.config["DATA_FILE"], request.get_json(silent=True) or {})
        return jsonify(data), code

    # ===== 2026-07-20 蝦董 added: 測試頁 endpoints =====
    TEST_USER_PREFIX = "U_TEST_"

    @app.get("/api/guardian-groups/test-users")
    def guardian_groups_test_users_api():
        state = load_state(app.config["DATA_FILE"])
        users = []
        for uid, profile in (state.get("users") or {}).items():
            if not uid.startswith(TEST_USER_PREFIX):
                continue
            plan = profile.get("plan") or "trial"
            is_year = plan == "paid_799_year"
            is_month = plan == "paid_799"
            eligible = (is_year or is_month) and paid_membership_is_active(profile)
            users.append({
                "line_user_id": uid,
                "display_name": profile.get("display_name", ""),
                "plan": plan,
                "paid_until": profile.get("paid_until", ""),
                "payment_status": profile.get("payment_status", ""),
                "bind_count": len(profile.get("guardian_group_ids") or []),
                "max_groups": (3 if is_year else 1) if eligible else 0,
                "eligible": eligible,
                "status": "eligible" if eligible else "ineligible",
                "guardian_group_ids": profile.get("guardian_group_ids", []),
            })
        groups = [
            {"group_id": gid, **ginfo}
            for gid, ginfo in (state.get("guardian_groups") or {}).items()
        ]
        return jsonify({"users": users, "groups": groups, "prefix": TEST_USER_PREFIX})

    @app.post("/api/guardian-groups/test-reset")
    def guardian_groups_test_reset_api():
        state = load_state(app.config["DATA_FILE"])
        uids = [uid for uid in state.get("users", {}).keys() if uid.startswith(TEST_USER_PREFIX)]
        for uid in uids:
            state["users"].pop(uid, None)
        for profile in state.get("users", {}).values():
            if isinstance(profile.get("contacts"), list):
                profile["contacts"] = [c for c in profile["contacts"] if c.get("line_id") not in uids]
            if isinstance(profile.get("friends"), list):
                profile["friends"] = [f for f in profile["friends"] if f not in uids]
        for gid in list(state.get("guardian_groups", {}).keys()):
            owner = state["guardian_groups"][gid].get("owner_line_user_id", "")
            if owner.startswith(TEST_USER_PREFIX):
                state["guardian_groups"].pop(gid, None)
        for profile in state.get("users", {}).values():
            if isinstance(profile.get("guardian_group_ids"), list):
                profile["guardian_group_ids"] = []
        save_state(app.config["DATA_FILE"], state)
        defaults = [
            ("U_TEST_yearly_001", "paid_799_year", "測試-年費999", "2099-12-31T00:00:00", "active"),
            ("U_TEST_monthly_001", "paid_799", "測試-月費", "2099-12-31T00:00:00", "active"),
            ("U_TEST_399_001", "paid_399", "測試-399 不符資格", "2099-12-31T00:00:00", "active"),
            ("U_TEST_trial_001", "trial", "測試-trial", "", "trial"),
        ]
        created = []
        for uid, plan, name, paid_until, payment_status in defaults:
            if uid in state["users"]:
                continue
            state["users"][uid] = {
                "line_user_id": uid, "display_name": name, "plan": plan,
                "paid_until": paid_until, "payment_status": payment_status,
                "guardian_group_ids": [], "contacts": [], "friends": [],
            }
            created.append(uid)
        save_state(app.config["DATA_FILE"], state)
        return jsonify({"reset": True, "deleted_users": len(uids), "created": created})

    @app.post("/api/guardian-groups/test-enforce")
    def guardian_groups_test_enforce_api():
        body = request.get_json(silent=True) or {}
        group_id = str(body.get("group_id") or "").strip()
        simulated_count = body.get("simulated_count")
        simulated_new_ids = body.get("simulated_new_ids") or []
        if not group_id:
            return jsonify({"error": "missing group_id"}), 400
        state = load_state(app.config["DATA_FILE"])
        group_info = state.get("guardian_groups", {}).get(group_id)
        if not group_info:
            return jsonify({"error": "group not bound"}), 404
        if group_info.get("status") != "active":
            return jsonify({"error": "group inactive"}), 409
        if simulated_count is None:
            return jsonify({"error": "simulated_count required"}), 400
        current_count = int(simulated_count)
        if current_count <= GROUP_MEMBER_LIMIT:
            return jsonify({
                "ok": True, "enforced": False,
                "current_count": current_count, "limit": GROUP_MEMBER_LIMIT,
                "kicked": [], "failed": [],
                "group_id": group_id,
                "note": "未超過上限,不需 evict",
            }), 200
        bind_ids = set(group_info.get("member_ids_at_bind") or [])
        candidate_ids = list(simulated_new_ids)
        overflow = current_count - GROUP_MEMBER_LIMIT
        to_kick = candidate_ids[:overflow] if overflow > 0 else (candidate_ids[:1] if candidate_ids else [])
        kicked = list(to_kick)
        return jsonify({
            "ok": True, "enforced": True,
            "current_count": current_count, "limit": GROUP_MEMBER_LIMIT,
            "overflow": overflow,
            "candidate_count": len(candidate_ids),
            "bind_snapshot_count": len(bind_ids),
            "kicked": kicked, "failed": [],
            "group_id": group_id,
            "note": "測試模擬(not實際打 LINE API)",
        }), 200

    @app.post("/api/friends/invite")
    def friends_invite_api():
        data, code = create_friend_invite(app.config["DATA_FILE"], request.get_json(silent=True) or {})
        return jsonify(data), code

    @app.post("/api/friends/accept")
    def friends_accept_api():
        data, code = accept_friend_invite(app.config["DATA_FILE"], request.get_json(silent=True) or {})
        return jsonify(data), code

    @app.get("/api/friends/locations")
    def friends_locations_api():
        return jsonify(friend_locations(app.config["DATA_FILE"], request.args.get("line_user_id")))

    @app.get("/api/location/status")
    def location_status_api():
        line_user_id = str(request.args.get("line_user_id") or "").strip()
        if not line_user_id:
            return jsonify({"error": "missing line_user_id"}), 400
        state = load_state(app.config["DATA_FILE"])
        profile = get_profile(state, line_user_id)
        return jsonify({"ok": True, "safety_guard": safety_guard_snapshot(profile)})

    @app.post("/api/location/update")
    def location_update_api():
        data, code = update_location(app.config["DATA_FILE"], request.get_json(silent=True) or {})
        return jsonify(data), code

    @app.post("/api/location/stop")
    def location_stop_api():
        data, code = stop_location_sharing(app.config["DATA_FILE"], request.get_json(silent=True) or {})
        return jsonify(data), code

    @app.post("/api/sos")
    def sos_api():
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        payload["line_user_id"] = line_user_id
        data, code = trigger_sos(app.config["DATA_FILE"], payload, app.config)
        return jsonify(data), code

    @app.get("/api/bot/guardian-groups")
    def bot_guardian_groups_api():
        """2026-07-21 patch 22: 返回所有守護群清單(供 bot_admin.html)。"""
        password = request.args.get("password") or request.headers.get("X-Admin-Password", "")
        if not admin_allowed(app.config, password):
            return jsonify({"error": "unauthorized"}), 401

        state = load_state(app.config["DATA_FILE"])
        groups = state.get("guardian_groups", {})
        users = state.get("users", {})
        out = []
        for gid, g in groups.items():
            owner_id = g.get("owner_line_user_id", "")
            owner_profile = users.get(owner_id, {})
            out.append({
                "group_id": gid,
                "owner_id": owner_id[:6] + "..." + owner_id[-4:] if owner_id else None,
                "owner_plan": owner_profile.get("plan"),
                "member_count_at_bind": g.get("member_count_at_bind"),
                "created_at": g.get("created_at"),
                "status": g.get("status"),
            })
        return jsonify({"groups": out, "total": len(out)})

    @app.get("/api/bot/sos-pending")
    def bot_sos_pending_api():
        """2026-07-21 patch 22: 返回所有 SOS 預約狀態。"""
        password = request.args.get("password") or request.headers.get("X-Admin-Password", "")
        if not admin_allowed(app.config, password):
            return jsonify({"error": "unauthorized"}), 401

        state = load_state(app.config["DATA_FILE"])
        pending = state.get("sos_pending", {})
        out = []
        for uid, p in pending.items():
            out.append({
                "user_id": uid[:6] + "..." + uid[-4:],
                "stage": p.get("stage"),
                "tap_count": p.get("tap_count"),
                "first_tap_at": p.get("first_tap_at"),
                "last_tap_at": p.get("last_tap_at"),
                "sent_at": p.get("sent_at"),
                "event_id": p.get("event_id"),
                "cancelled_at": p.get("cancelled_at"),
            })
        # active 在前(警告/warning),sent,cancelled 在後
        out.sort(key=lambda x: (x.get("stage", "") not in ("warning_1", "warning_2", "warning_3"), x.get("last_tap_at") or ""))
        return jsonify({"pending": out, "total": len(out)})

    @app.get("/api/bot/recent-events")
    def bot_recent_events_api():
        """2026-07-21 patch 22: 返回最近的 webhook 事件(使用 notification_log)。"""
        password = request.args.get("password") or request.headers.get("X-Admin-Password", "")
        if not admin_allowed(app.config, password):
            return jsonify({"error": "unauthorized"}), 401

        state = load_state(app.config["DATA_FILE"])
        log = state.get("notification_log", [])
        recent = log[-20:]  # 最近 20 條
        recent.reverse()
        return jsonify({"recent": recent, "total": len(log)})

    @app.post("/api/sos/check-scheduled")
    def sos_check_scheduled_api():
        """2026-07-21 patch 21: Cron 端點 — 清理過期 SOS 紀錄。

        3-tap 流程會立即發送,所以這個 cron 只負責:
        1. 清掉 1 小時以前的 sent/cancelled 紀錄(避免 state 膨脵)
        未來可加:在 sent_at 後 5 分鐘提醒「可以取消了」等
        """
        from sos_flow import sos_purge_old
        from datetime import datetime

        state = load_state(app.config["DATA_FILE"])
        now = datetime.now()
        removed = sos_purge_old(state, keep_minutes=60)
        save_state(app.config["DATA_FILE"], state)
        return jsonify({
            "checked_at": now.isoformat(timespec="seconds"),
            "purged": len(removed),
        })

    @app.post("/api/account/delete")
    def account_delete_api():
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        payload["line_user_id"] = line_user_id
        data, code = delete_account(app.config["DATA_FILE"], payload)
        return jsonify(data), code

    @app.post("/api/account/export")
    def account_export_api():
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        payload["line_user_id"] = line_user_id
        data, code = export_account_data(app.config["DATA_FILE"], payload)
        return jsonify(data), code

    @app.post("/api/account/history/delete")
    def account_history_delete_api():
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        payload["line_user_id"] = line_user_id
        data, code = delete_personal_history(app.config["DATA_FILE"], payload)
        return jsonify(data), code

    @app.get("/api/admin/summary")
    def admin_summary_api():
        password = request.args.get("password") or request.headers.get("X-Admin-Password", "")
        denied = admin_auth_error_payload(app.config, password)
        if denied:
            payload, code = denied
            return jsonify(payload), code
        return jsonify(admin_summary(app.config["DATA_FILE"]))

    @app.get("/api/admin/support-tickets")
    def admin_support_tickets_api():
        password = request.args.get("password") or request.headers.get("X-Admin-Password", "")
        if not admin_allowed(app.config, password):
            return jsonify({"error": "unauthorized"}), 401
        return jsonify(admin_support_tickets(app.config["DATA_FILE"]))

    @app.get("/api/admin/backups")
    def admin_backups_list_api():
        password = request.args.get("password") or request.headers.get("X-Admin-Password", "")
        if not admin_allowed(app.config, password):
            return jsonify({"error": "unauthorized"}), 401
        return jsonify(list_admin_backups(app.config["DATA_FILE"]))

    @app.post("/api/admin/backups")
    def admin_backups_create_api():
        password = request.args.get("password") or request.headers.get("X-Admin-Password", "")
        if not admin_allowed(app.config, password):
            return jsonify({"error": "unauthorized"}), 401
        data, code = create_admin_backup(app.config["DATA_FILE"])
        return jsonify(data), code

    @app.get("/api/admin/backups/<backup_id>")
    def admin_backups_download_api(backup_id):
        password = request.args.get("password") or request.headers.get("X-Admin-Password", "")
        if not admin_allowed(app.config, password):
            return jsonify({"error": "unauthorized"}), 401
        data, code = read_admin_backup(app.config["DATA_FILE"], backup_id)
        return jsonify(data), code

    @app.post("/api/admin/support-reply")
    def admin_support_reply_api():
        password = request.args.get("password") or request.headers.get("X-Admin-Password", "")
        if not admin_allowed(app.config, password):
            return jsonify({"error": "unauthorized"}), 401
        data, code = admin_reply_support_ticket(app.config["DATA_FILE"], request.get_json(silent=True) or {}, app.config)
        return jsonify(data), code

    @app.post("/api/admin/send-reminders")
    def send_reminders_api():
        password = request.args.get("password") or request.headers.get("X-Admin-Password", "")
        if not admin_allowed(app.config, password):
            return jsonify({"error": "unauthorized"}), 401
        data, code = send_due_reminders(app.config)
        return jsonify(data), code

    @app.post("/api/admin/send-contact-reminders")
    def send_contact_reminders_api():
        password = request.args.get("password") or request.headers.get("X-Admin-Password", "")
        if not admin_allowed(app.config, password):
            return jsonify({"error": "unauthorized"}), 401
        data, code = send_missing_contact_reminders(app.config)
        return jsonify(data), code

    @app.post("/api/admin/send-renewal-reminders")
    def send_renewal_reminders_api():
        password = request.args.get("password") or request.headers.get("X-Admin-Password", "")
        if not admin_allowed(app.config, password):
            return jsonify({"error": "unauthorized"}), 401
        data, code = send_renewal_reminders(app.config)
        return jsonify(data), code

    @app.post("/api/admin/send-birthday-reminders")
    def send_birthday_reminders_api():
        password = request.args.get("password") or request.headers.get("X-Admin-Password", "")
        if not admin_allowed(app.config, password):
            return jsonify({"error": "unauthorized"}), 401
        data, code = send_birthday_reminders(app.config)
        return jsonify(data), code

    @app.post("/api/admin/payments/confirm")
    def admin_payment_confirm_api():
        password = request.args.get("password") or request.headers.get("X-Admin-Password", "")
        if not admin_allowed(app.config, password):
            return jsonify({"error": "unauthorized"}), 401
        data, code = confirm_payment_order(app.config["DATA_FILE"], request.get_json(silent=True) or {}, app.config)
        return jsonify(data), code

    @app.route("/api/cron/contact-reminders", methods=["GET", "POST"])
    def cron_contact_reminders_api():
        secret = request.args.get("secret") or request.headers.get("X-Cron-Secret", "")
        if not cron_allowed(app.config, secret):
            return jsonify({"error": "unauthorized"}), 401
        data, code = send_missing_contact_reminders(app.config)
        return jsonify(data), code

    @app.route("/api/cron/checkin-reminders", methods=["GET", "POST"])
    def cron_checkin_reminders_api():
        secret = request.args.get("secret") or request.headers.get("X-Cron-Secret", "")
        if not cron_allowed(app.config, secret):
            return jsonify({"error": "unauthorized"}), 401
        data, code = send_checkin_reminders(app.config)
        return jsonify(data), code

    @app.route("/api/cron/overdue-alerts", methods=["GET", "POST"])
    def cron_overdue_alerts_api():
        secret = request.args.get("secret") or request.headers.get("X-Cron-Secret", "")
        if not cron_allowed(app.config, secret):
            return jsonify({"error": "unauthorized"}), 401
        data, code = send_due_reminders(app.config)
        return jsonify(data), code

    @app.route("/api/cron/renewal-reminders", methods=["GET", "POST"])
    def cron_renewal_reminders_api():
        secret = request.args.get("secret") or request.headers.get("X-Cron-Secret", "")
        if not cron_allowed(app.config, secret):
            return jsonify({"error": "unauthorized"}), 401
        data, code = send_renewal_reminders(app.config)
        return jsonify(data), code

    @app.route("/api/cron/birthday-reminders", methods=["GET", "POST"])
    def cron_birthday_reminders_api():
        secret = request.args.get("secret") or request.headers.get("X-Cron-Secret", "")
        if not cron_allowed(app.config, secret):
            return jsonify({"error": "unauthorized"}), 401
        data, code = send_birthday_reminders(app.config)
        return jsonify(data), code

    @app.route("/api/cron/membership-expiry", methods=["GET", "POST"])
    def cron_membership_expiry_api():
        secret = request.args.get("secret") or request.headers.get("X-Cron-Secret", "")
        if not cron_allowed(app.config, secret):
            return jsonify({"error": "unauthorized"}), 401
        data, code = apply_expired_plan_downgrades(app.config)
        return jsonify(data), code

    @app.route("/api/cron/data-cleanup", methods=["GET", "POST"])
    def cron_data_cleanup_api():
        secret = request.args.get("secret") or request.headers.get("X-Cron-Secret", "")
        if not cron_allowed(app.config, secret):
            return jsonify({"error": "unauthorized"}), 401
        data, code = cleanup_expired_data(app.config)
        return jsonify(data), code

    @app.get("/api/admin/rich-menu")
    def admin_rich_menu_inspect_api():
        """查詢目前預設圖文選單（含一鍵邀請 URI）。不回傳 token。"""
        password = request.args.get("password") or request.headers.get("X-Admin-Password", "")
        if not admin_allowed(app.config, password):
            return jsonify({"error": "unauthorized"}), 401
        data, code = inspect_default_rich_menu(app.config)
        return jsonify(data), code

    @app.post("/api/admin/rich-menu/deploy")
    def admin_rich_menu_deploy_api():
        """用 Render 上的 LINE_CHANNEL_ACCESS_TOKEN 上傳並設為預設圖文選單。"""
        password = request.args.get("password") or request.headers.get("X-Admin-Password", "")
        if not admin_allowed(app.config, password):
            return jsonify({"error": "unauthorized"}), 401
        data, code = deploy_default_rich_menu(app.config)
        if data.get("ok"):
            app.logger.info(
                "rich menu deployed richMenuId=%s name=%s",
                data.get("richMenuId"),
                data.get("name"),
            )
        else:
            app.logger.warning(
                "rich menu deploy failed step=%s http=%s",
                data.get("step"),
                data.get("http"),
            )
        return jsonify(data), code

    @app.post("/api/admin/push-welcome")
    def admin_push_welcome_api():
        """管理員補推歡迎 Flex（需已加好友）。body: {line_user_id, display_name?}"""
        password = request.args.get("password") or request.headers.get("X-Admin-Password", "")
        if not admin_allowed(app.config, password):
            return jsonify({"error": "unauthorized"}), 401
        if LineBotApi is None or FlexSendMessage is None or welcome_flex is None:
            return jsonify({"ok": False, "error": "line sdk or welcome_flex unavailable"}), 503
        payload = request.get_json(silent=True) or {}
        line_user_id = str(payload.get("line_user_id") or "").strip()
        if not line_user_id:
            return jsonify({"ok": False, "error": "missing line_user_id"}), 400
        token = (
            app.config.get("LINE_CHANNEL_ACCESS_TOKEN")
            or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
            or ""
        ).strip()
        if not token:
            return jsonify({"ok": False, "error": "LINE_CHANNEL_ACCESS_TOKEN not set"}), 503
        line_bot_api = LineBotApi(token)
        hint = str(payload.get("display_name") or "").strip() or None
        resolved = resolve_welcome_display_name(
            line_bot_api=line_bot_api,
            data_file=app.config["DATA_FILE"],
            line_user_id=line_user_id,
            hint=hint,
            logger=app.logger,
        )
        try:
            register_line_user(
                app.config["DATA_FILE"],
                {"line_user_id": line_user_id, "display_name": resolved or "LINE 使用者"},
            )
        except Exception as exc:
            app.logger.warning("admin push-welcome register failed: %s", exc)
        contents = welcome_flex(resolved)
        greeting = (
            welcome_greeting_text(resolved)
            if welcome_greeting_text is not None
            else (f"👋 {resolved} 您好，歡迎加入「每日平安」" if resolved else "👋 您好，歡迎加入「每日平安」")
        )
        alt_text = (
            f"每日平安｜{resolved} 您好，歡迎加入"
            if resolved
            else "每日平安｜您好，歡迎加入"
        )
        try:
            line_bot_api.push_message(
                line_user_id,
                FlexSendMessage(alt_text=alt_text, contents=contents),
            )
            app.logger.info(
                "admin push-welcome ok user=%s name=%r",
                line_user_id[:8],
                resolved or "",
            )
            return jsonify(
                {
                    "ok": True,
                    "line_user_id": line_user_id,
                    "display_name": resolved,
                    "greeting": greeting,
                }
            )
        except LineBotApiError as exc:
            detail = str(exc)
            try:
                detail = getattr(exc, "error", None) or detail
            except Exception:
                pass
            app.logger.exception("admin push-welcome LINE error: %s", detail)
            return jsonify({"ok": False, "error": "line_api_error", "detail": str(detail)}), 502
        except Exception as exc:
            app.logger.exception("admin push-welcome failed: %s", exc)
            return jsonify({"ok": False, "error": str(exc)}), 500

    @app.post("/api/admin/user-plan")
    def admin_user_plan_api():
        password = request.args.get("password") or request.headers.get("X-Admin-Password", "")
        if not admin_allowed(app.config, password):
            return jsonify({"error": "unauthorized"}), 401
        data, code = admin_update_user_plan(app.config["DATA_FILE"], request.get_json(silent=True) or {})
        return jsonify(data), code

    return app


class MiniResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def get_json(self):
        return self._data


class MiniClient:
    def __init__(self, app):
        self.app = app

    def get(self, path):
        route, _, query = path.partition("?")
        params = dict(urllib.parse.parse_qsl(query))
        if route == "/api/config":
            return MiniResponse(app_config(self.app.config))
        if route == "/health":
            return MiniResponse({"ok": True})
        if route in ("/terms", "/privacy"):
            return MiniResponse({"ok": True})
        if route == "/api/status":
            return MiniResponse(self.app.status(params.get("line_user_id")))
        if route == "/api/admin/summary":
            denied = admin_auth_error_payload(self.app.config, params.get("password", ""))
            if denied:
                payload, code = denied
                return MiniResponse(payload, code)
            return MiniResponse(admin_summary(self.app.config["DATA_FILE"]))
        if route == "/api/admin/support-tickets":
            if not admin_allowed(self.app.config, params.get("password", "")):
                return MiniResponse({"error": "unauthorized"}, 401)
            return MiniResponse(admin_support_tickets(self.app.config["DATA_FILE"]))
        if route == "/api/admin/backups":
            if not admin_allowed(self.app.config, params.get("password", "")):
                return MiniResponse({"error": "unauthorized"}, 401)
            return MiniResponse(list_admin_backups(self.app.config["DATA_FILE"]))
        if route.startswith("/api/admin/backups/"):
            if not admin_allowed(self.app.config, params.get("password", "")):
                return MiniResponse({"error": "unauthorized"}, 401)
            backup_id = route.rsplit("/", 1)[-1]
            body, code = read_admin_backup(self.app.config["DATA_FILE"], backup_id)
            return MiniResponse(body, code)
        if route == "/api/contacts":
            return MiniResponse(get_contacts(self.app.config["DATA_FILE"], params.get("line_user_id")))
        if route == "/api/calendar-notes":
            return MiniResponse(get_calendar_notes(self.app.config["DATA_FILE"], params.get("line_user_id")))
        if route == "/api/friends/locations":
            return MiniResponse(friend_locations(self.app.config["DATA_FILE"], params.get("line_user_id")))
        if route == "/api/location/status":
            line_user_id = params.get("line_user_id")
            if not line_user_id:
                return MiniResponse({"error": "missing line_user_id"}, 400)
            profile = get_profile(load_state(self.app.config["DATA_FILE"]), line_user_id)
            return MiniResponse({"ok": True, "safety_guard": safety_guard_snapshot(profile)})
        return MiniResponse({"error": "not found"}, 404)

    def post(self, path, data=None, content_type=None):
        route, _, query = path.partition("?")
        params = dict(urllib.parse.parse_qsl(query))
        payload = {}
        if data and content_type == "application/json":
            payload = json.loads(data)
        if route == "/api/line/register":
            body, code = register_line_user(self.app.config["DATA_FILE"], payload)
            return MiniResponse(body, code)
        if route == "/api/checkin":
            return MiniResponse(record_checkin(self.app.config["DATA_FILE"], payload))
        if route == "/api/warning/cancel":
            return MiniResponse(cancel_warning(self.app.config["DATA_FILE"], payload, self.app.config))
        if route == "/api/settings":
            return MiniResponse(save_settings_for_profile(self.app.config["DATA_FILE"], payload))
        if route == "/api/billing/preferences":
            body, code = save_billing_preferences(self.app.config["DATA_FILE"], payload)
            return MiniResponse(body, code)
        if route == "/api/payments/orders":
            body, code = create_payment_order(self.app.config["DATA_FILE"], payload, self.app.config)
            return MiniResponse(body, code)
        if route == "/api/contacts":
            body, code = save_contacts(self.app.config["DATA_FILE"], payload)
            return MiniResponse(body, code)
        if route == "/api/calendar-notes":
            body, code = save_calendar_note(self.app.config["DATA_FILE"], payload)
            return MiniResponse(body, code)
        if route == "/api/emergency-contact/bind":
            body, code = bind_emergency_contact(self.app.config["DATA_FILE"], payload, self.app.config)
            return MiniResponse(body, code)
        if route == "/api/guardian-groups/bind":
            body, code = bind_guardian_group(self.app.config["DATA_FILE"], payload)
            return MiniResponse(body, code)
        if route == "/api/guardian-groups/unbind":
            body, code = unbind_guardian_group(self.app.config["DATA_FILE"], payload)
            return MiniResponse(body, code)
        if route == "/api/friends/invite":
            body, code = create_friend_invite(self.app.config["DATA_FILE"], payload)
            return MiniResponse(body, code)
        if route == "/api/friends/accept":
            body, code = accept_friend_invite(self.app.config["DATA_FILE"], payload)
            return MiniResponse(body, code)
        if route == "/api/location/update":
            body, code = update_location(self.app.config["DATA_FILE"], payload)
            return MiniResponse(body, code)
        if route == "/api/location/stop":
            body, code = stop_location_sharing(self.app.config["DATA_FILE"], payload)
            return MiniResponse(body, code)
        if route == "/api/sos":
            body, code = trigger_sos(self.app.config["DATA_FILE"], payload, self.app.config)
            return MiniResponse(body, code)
        if route == "/api/account/delete":
            body, code = delete_account(self.app.config["DATA_FILE"], payload)
            return MiniResponse(body, code)
        if route == "/api/account/export":
            body, code = export_account_data(self.app.config["DATA_FILE"], payload)
            return MiniResponse(body, code)
        if route == "/api/account/history/delete":
            body, code = delete_personal_history(self.app.config["DATA_FILE"], payload)
            return MiniResponse(body, code)
        if route == "/api/admin/send-reminders":
            if not admin_allowed(self.app.config, params.get("password", "")):
                return MiniResponse({"error": "unauthorized"}, 401)
            body, code = send_due_reminders(self.app.config)
            return MiniResponse(body, code)
        if route == "/api/admin/send-contact-reminders":
            if not admin_allowed(self.app.config, params.get("password", "")):
                return MiniResponse({"error": "unauthorized"}, 401)
            body, code = send_missing_contact_reminders(self.app.config)
            return MiniResponse(body, code)
        if route == "/api/admin/send-renewal-reminders":
            if not admin_allowed(self.app.config, params.get("password", "")):
                return MiniResponse({"error": "unauthorized"}, 401)
            body, code = send_renewal_reminders(self.app.config)
            return MiniResponse(body, code)
        if route == "/api/admin/payments/confirm":
            if not admin_allowed(self.app.config, params.get("password", "")):
                return MiniResponse({"error": "unauthorized"}, 401)
            body, code = confirm_payment_order(self.app.config["DATA_FILE"], payload, self.app.config)
            return MiniResponse(body, code)
        if route == "/api/admin/backups":
            if not admin_allowed(self.app.config, params.get("password", "")):
                return MiniResponse({"error": "unauthorized"}, 401)
            body, code = create_admin_backup(self.app.config["DATA_FILE"])
            return MiniResponse(body, code)
        if route == "/api/cron/contact-reminders":
            secret = params.get("secret", "")
            if not cron_allowed(self.app.config, secret):
                return MiniResponse({"error": "unauthorized"}, 401)
            body, code = send_missing_contact_reminders(self.app.config)
            return MiniResponse(body, code)
        if route == "/api/cron/checkin-reminders":
            secret = params.get("secret", "")
            if not cron_allowed(self.app.config, secret):
                return MiniResponse({"error": "unauthorized"}, 401)
            body, code = send_checkin_reminders(self.app.config)
            return MiniResponse(body, code)
        if route == "/api/cron/renewal-reminders":
            secret = params.get("secret", "")
            if not cron_allowed(self.app.config, secret):
                return MiniResponse({"error": "unauthorized"}, 401)
            body, code = send_renewal_reminders(self.app.config)
            return MiniResponse(body, code)
        if route == "/api/cron/data-cleanup":
            secret = params.get("secret", "")
            if not cron_allowed(self.app.config, secret):
                return MiniResponse({"error": "unauthorized"}, 401)
            body, code = cleanup_expired_data(self.app.config)
            return MiniResponse(body, code)
        if route == "/api/admin/user-plan":
            if not admin_allowed(self.app.config, params.get("password", "")):
                return MiniResponse({"error": "unauthorized"}, 401)
            body, code = admin_update_user_plan(self.app.config["DATA_FILE"], payload)
            return MiniResponse(body, code)
        if route == "/api/admin/support-reply":
            if not admin_allowed(self.app.config, params.get("password", "")):
                return MiniResponse({"error": "unauthorized"}, 401)
            body, code = admin_reply_support_ticket(self.app.config["DATA_FILE"], payload, self.app.config)
            return MiniResponse(body, code)
        return MiniResponse({"error": "not found"}, 404)


class MiniApp:
    def __init__(self, config=None):
        self.config = {
            "DATA_FILE": os.environ.get("DATA_FILE", str(Path(__file__).resolve().parent / "data" / "state.json")),
            "ADMIN_PASSWORD": os.environ.get("ADMIN_PASSWORD", ""),
            "ALLOW_OPEN_ADMIN": os.environ.get("ALLOW_OPEN_ADMIN", ""),
            "ADMIN_OPEN": os.environ.get("ADMIN_OPEN", ""),
            "LINE_CHANNEL_ACCESS_TOKEN": os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", ""),
            "LINE_CHANNEL_SECRET": os.environ.get("LINE_CHANNEL_SECRET", ""),
            "LIFF_ID": os.environ.get("LIFF_ID", ""),
            "APP_PUBLIC_URL": os.environ.get("APP_PUBLIC_URL", ""),
            "APP_TIMEZONE": os.environ.get("APP_TIMEZONE", "Asia/Taipei"),
            "CRON_SECRET": os.environ.get("CRON_SECRET", ""),
        }
        if config:
            self.config.update(config)

    def test_client(self):
        return MiniClient(self)

    def status(self, line_user_id=None):
        state = load_state(self.config["DATA_FILE"])
        return build_status(get_profile(state, line_user_id))

    def run(self, host="127.0.0.1", port=5000, debug=False):
        data_file = self.config["DATA_FILE"]
        config = self.config
        static_root = Path(__file__).resolve().parent

        class Handler(BaseHTTPRequestHandler):
            def send_json(handler, payload, status=200):
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                handler.send_response(status)
                handler.send_header("Content-Type", "application/json; charset=utf-8")
                handler.send_header("Content-Length", str(len(body)))
                handler.end_headers()
                handler.wfile.write(body)

            def read_payload(handler):
                length = int(handler.headers.get("Content-Length") or 0)
                if not length:
                    return {}
                try:
                    return json.loads(handler.rfile.read(length).decode("utf-8"))
                except json.JSONDecodeError:
                    return {}

            def query(handler):
                return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(handler.path).query))

            def route(handler):
                return urllib.parse.urlsplit(handler.path).path

            def do_GET(handler):
                route = handler.route()
                params = handler.query()
                if route == "/api/config":
                    return handler.send_json(app_config(config))
                if route == "/health":
                    return handler.send_json({"ok": True})
                if route == "/api/status":
                    line_user_id = (params.get("line_user_id") or "").strip()
                    if not line_user_id:
                        return handler.send_json({"ok": False, "error": "missing line_user_id"}, 400)
                    state = load_state(data_file)
                    if line_user_id not in state.get("users", {}):
                        data, code = register_line_user(
                            data_file,
                            {
                                "line_user_id": line_user_id,
                                "display_name": params.get("display_name") or "LINE 使用者",
                            },
                        )
                        if isinstance(data, dict):
                            data["auto_registered"] = True
                        return handler.send_json(data, code)
                    return handler.send_json(build_status(state["users"][line_user_id], state))
                if route == "/api/admin/summary":
                    denied = admin_auth_error_payload(config, params.get("password", ""))
                    if denied:
                        payload, code = denied
                        return handler.send_json(payload, code)
                    return handler.send_json(admin_summary(data_file))
                if route == "/api/contacts":
                    return handler.send_json(get_contacts(data_file, params.get("line_user_id")))
                if route == "/api/calendar-notes":
                    return handler.send_json(get_calendar_notes(data_file, params.get("line_user_id")))
                if route == "/api/friends/locations":
                    return handler.send_json(friend_locations(data_file, params.get("line_user_id")))
                if route == "/api/location/status":
                    line_user_id = params.get("line_user_id")
                    if not line_user_id:
                        return handler.send_json({"error": "missing line_user_id"}, 400)
                    return handler.send_json({
                        "ok": True,
                        "safety_guard": safety_guard_snapshot(get_profile(load_state(data_file), line_user_id)),
                    })
                if route == "/api/cron/contact-reminders":
                    if not cron_allowed(config, params.get("secret", "")):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    data, code = send_missing_contact_reminders(config)
                    return handler.send_json(data, code)
                if route == "/api/cron/checkin-reminders":
                    if not cron_allowed(config, params.get("secret", "")):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    data, code = send_checkin_reminders(config)
                    return handler.send_json(data, code)
                if route == "/api/cron/data-cleanup":
                    if not cron_allowed(config, params.get("secret", "")):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    data, code = cleanup_expired_data(config)
                    return handler.send_json(data, code)

                file_name = "index.html" if route == "/" else route.lstrip("/")
                if route == "/admin":
                    file_name = "admin.html"
                if route == "/terms":
                    file_name = "terms.html"
                if route == "/privacy":
                    file_name = "privacy.html"
                file_path = static_root / file_name
                if not file_path.exists() or not file_path.is_file():
                    handler.send_response(404)
                    handler.end_headers()
                    return
                body = file_path.read_bytes()
                content_type = "text/html; charset=utf-8" if file_path.suffix == ".html" else "text/plain; charset=utf-8"
                handler.send_response(200)
                handler.send_header("Content-Type", content_type)
                handler.send_header("Content-Length", str(len(body)))
                if route == "/admin":
                    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                    handler.send_header("Pragma", "no-cache")
                handler.end_headers()
                handler.wfile.write(body)

            def do_POST(handler):
                route = handler.route()
                params = handler.query()
                payload = handler.read_payload()
                if route == "/api/line/register":
                    data, code = register_line_user(data_file, payload)
                    return handler.send_json(data, code)
                if route == "/api/checkin":
                    return handler.send_json(record_checkin(data_file, payload))
                if route == "/api/warning/cancel":
                    return handler.send_json(cancel_warning(data_file, payload, config))
                if route == "/api/settings":
                    return handler.send_json(save_settings_for_profile(data_file, payload))
                if route == "/api/billing/preferences":
                    data, code = save_billing_preferences(data_file, payload)
                    return handler.send_json(data, code)
                if route == "/api/payments/orders":
                    data, code = create_payment_order(data_file, payload, config)
                    return handler.send_json(data, code)
                if route == "/api/contacts":
                    data, code = save_contacts(data_file, payload)
                    return handler.send_json(data, code)
                if route == "/api/calendar-notes":
                    data, code = save_calendar_note(data_file, payload)
                    return handler.send_json(data, code)
                if route == "/api/emergency-contact/bind":
                    data, code = bind_emergency_contact(data_file, payload, config)
                    return handler.send_json(data, code)
                if route == "/api/guardian-groups/bind":
                    data, code = bind_guardian_group(data_file, payload)
                    return handler.send_json(data, code)
                if route == "/api/guardian-groups/unbind":
                    data, code = unbind_guardian_group(data_file, payload)
                    return handler.send_json(data, code)
                if route == "/api/friends/invite":
                    data, code = create_friend_invite(data_file, payload)
                    return handler.send_json(data, code)
                if route == "/api/friends/accept":
                    data, code = accept_friend_invite(data_file, payload)
                    return handler.send_json(data, code)
                if route == "/api/location/update":
                    data, code = update_location(data_file, payload)
                    return handler.send_json(data, code)
                if route == "/api/location/stop":
                    data, code = stop_location_sharing(data_file, payload)
                    return handler.send_json(data, code)
                if route == "/api/sos":
                    data, code = trigger_sos(data_file, payload, config)
                    return handler.send_json(data, code)
                if route == "/api/account/delete":
                    data, code = delete_account(data_file, payload)
                    return handler.send_json(data, code)
                if route == "/api/account/export":
                    data, code = export_account_data(data_file, payload)
                    return handler.send_json(data, code)
                if route == "/api/account/history/delete":
                    data, code = delete_personal_history(data_file, payload)
                    return handler.send_json(data, code)
                if route == "/api/admin/send-reminders":
                    if not admin_allowed(config, params.get("password", "")):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    data, code = send_due_reminders(config)
                    return handler.send_json(data, code)
                if route == "/api/admin/send-contact-reminders":
                    if not admin_allowed(config, params.get("password", "")):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    data, code = send_missing_contact_reminders(config)
                    return handler.send_json(data, code)
                if route == "/api/admin/send-renewal-reminders":
                    if not admin_allowed(config, params.get("password", "")):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    data, code = send_renewal_reminders(config)
                    return handler.send_json(data, code)
                if route == "/api/admin/payments/confirm":
                    if not admin_allowed(config, params.get("password", "")):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    data, code = confirm_payment_order(data_file, payload, config)
                    return handler.send_json(data, code)
                if route == "/api/cron/contact-reminders":
                    if not cron_allowed(config, params.get("secret", "")):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    data, code = send_missing_contact_reminders(config)
                    return handler.send_json(data, code)
                if route == "/api/cron/checkin-reminders":
                    if not cron_allowed(config, params.get("secret", "")):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    data, code = send_checkin_reminders(config)
                    return handler.send_json(data, code)
                if route == "/api/cron/renewal-reminders":
                    if not cron_allowed(config, params.get("secret", "")):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    data, code = send_renewal_reminders(config)
                    return handler.send_json(data, code)
                if route == "/api/cron/data-cleanup":
                    if not cron_allowed(config, params.get("secret", "")):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    data, code = cleanup_expired_data(config)
                    return handler.send_json(data, code)
                if route == "/api/admin/user-plan":
                    if not admin_allowed(config, params.get("password", "")):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    data, code = admin_update_user_plan(data_file, payload)
                    return handler.send_json(data, code)
                handler.send_json({"error": "not found"}, 404)

        print("Flask is not installed. Using the built-in fallback server.")
        print(f"Open http://{host}:{port}")
        ThreadingHTTPServer((host, port), Handler).serve_forever()


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=True)
