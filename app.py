import json
import os
import re
import secrets
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from flask import Flask, jsonify, redirect, request, send_from_directory
except ModuleNotFoundError:
    Flask = None
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
        liff_entry_url,
        get_liff_id,
    )
except Exception:
    guardian_group_intro_flex = None
    guardian_group_status_flex = None
    guardian_group_bind_confirm_flex = None
    guardian_group_bind_fail_flex = None
    guardian_group_user_guide_flex = None
    guardian_group_admin_setup_flex = None
    welcome_flex = None
    liff_entry_url = None
    get_liff_id = None

# 註:patch 15 的全域白名單機制(GROUP_ADMINS / is_group_admin / deny_if_not_admin)
# 已於 2026-07-21 移除。「管理員」= 每個守護群的 owner_line_user_id(在 guardian_groups 裡)。
# patch 16 加強 self-intro 顯示 owner 狀態。

# SOS 求救流程(2026-07-21 patch 20):3 次確認 + 10 分鐘取消期
try:
    import sos_flow
except Exception:
    sos_flow = None


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
    "free": {"contact_limit": 1, "friend_location_limit": 1, "daily_reminders": 1, "channels": ["line"], "realtime_tracking": False, "trajectory_days": 0, "offline_sync_days": 0, "sos_enabled": False, "guardian_group_limit": 0},
    "trial": {"contact_limit": 1, "friend_location_limit": 1, "daily_reminders": 1, "channels": ["line"], "realtime_tracking": False, "trajectory_days": 0, "offline_sync_days": 0, "sos_enabled": False, "guardian_group_limit": 0},
    "paid_199": {"contact_limit": 4, "friend_location_limit": 4, "daily_reminders": 1, "channels": ["line"], "location_mode": "snapshot_24h", "core_guardian_alert_limit": 3, "realtime_tracking": False, "trajectory_days": 0, "offline_sync_days": 0, "sos_enabled": False, "guardian_group_limit": 0},
    "paid_199_year": {"contact_limit": 6, "friend_location_limit": 6, "daily_reminders": 2, "channels": ["line"], "location_mode": "snapshot_24h", "core_guardian_alert_limit": 3, "realtime_tracking": False, "trajectory_days": 3, "offline_sync_days": 0, "sos_enabled": False, "guardian_group_limit": 0},
    "paid_399": {"contact_limit": 15, "friend_location_limit": 15, "daily_reminders": 2, "channels": ["line"], "location_mode": "realtime", "core_guardian_alert_limit": 3, "realtime_tracking": True, "trajectory_days": 5, "offline_sync_days": 1, "sos_enabled": False, "guardian_group_limit": 0},
    "paid_399_year": {"contact_limit": 25, "friend_location_limit": 25, "daily_reminders": 3, "channels": ["line"], "location_mode": "realtime", "core_guardian_alert_limit": 3, "realtime_tracking": True, "trajectory_days": 7, "offline_sync_days": 1, "sos_enabled": False, "guardian_group_limit": 0, "realtime_trial_days": 30},
    "paid_799": {"contact_limit": 25, "friend_location_limit": 25, "daily_reminders": 3, "channels": ["line", "sms"], "location_mode": "full_guard", "core_guardian_alert_limit": 3, "realtime_tracking": True, "trajectory_days": 14, "offline_sync_days": 7, "sos_enabled": True, "guardian_group_limit": 1},
    "paid_799_year": {"contact_limit": 50, "friend_location_limit": 50, "daily_reminders": 3, "channels": ["line", "sms"], "location_mode": "full_guard", "core_guardian_alert_limit": 5, "realtime_tracking": True, "trajectory_days": 30, "offline_sync_days": 7, "sos_enabled": True, "guardian_group_limit": 3},
}

PAYMENT_PRODUCTS = {
    # 🔴 v0.5 P0 更新:依蝦董 2026-07-17 最終版 16 章規格
    "paid_199": {"amount": 199, "billing_cycle": "monthly", "duration_days": 30, "display_name": "199 平安版(月)", "tagline": "每天提醒自己簽到,讓自己安心"},
    "paid_199_year": {"amount": 1680, "billing_cycle": "yearly", "duration_days": 365, "display_name": "199 平安版(年)", "tagline": "每天提醒自己簽到,讓自己安心"},
    "paid_399": {"amount": 399, "billing_cycle": "monthly", "duration_days": 30, "display_name": "399 安心版(月)", "tagline": "讓家人隨時知道你在哪,即時追蹤定位"},
    "paid_399_year": {"amount": 3680, "billing_cycle": "yearly", "duration_days": 365, "display_name": "399 安心版(年)", "tagline": "讓家人隨時知道你在哪,即時追蹤定位"},
    "paid_799": {"amount": 799, "billing_cycle": "monthly", "duration_days": 30, "display_name": "799 守護版(月)", "tagline": "全家守護網絡 + LINE+簡訊預警 + SOS 緊急求救"},
    "paid_799_year": {"amount": 7200, "billing_cycle": "yearly", "duration_days": 365, "display_name": "799 守護版(年)", "tagline": "全家 50 人守護網絡 + LINE+簡訊預警 + SOS 緊急求救 + 守護群"},
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


def line_plan_message():
    return (
        "目前方案重點整理：\n"
        "199 平安版：月費 4 位、年費 6 位，LINE 通知 3 位核心守護人。\n"
        "399 安心版：月費 15 位、年費 25 位，LINE 通知 3 位核心守護人；年費含 30 天即時追蹤體驗。\n"
        "799 守護版：月費 NT$799，25 位緊急聯絡人、軌跡回放 14 天、離線同步 7 天、LINE + 簡訊。\n\n"
        "年費方案都有明確折扣；799 月費可建立 1 個守護群，年費可建立 3 個守護群。"
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
            "電子發票／收據說明：\n"
            "付款完成後，電子發票或付款證明會以你結帳時留下的 Email 為主。\n"
            "MVP 測試階段若使用藍新或綠界付款連結，後台會先人工核對付款狀態，再幫你開通方案。"
        )
    if any(keyword in text for keyword in GROUP_KEYWORDS):
        return (
            "守護群功能說明：\n"
            "守護群適合家人、親友或社區關懷小組一起接收平安狀態。\n"
            "有效的 799 月費會員可建立 1 群，年費會員最多可建立 3 群。\n"
            "請把「平安守護助理」加入群組後，由方案本人輸入「綁定平安守護助理」。若資格不符，「平安守護助理」會說明原因並退出群組。\n"
            "「平安守護助理」只處理簽到、預警與守護指令，不會把一般聊天內容存進會員資料。"
        )
    if any(keyword in text for keyword in ALERT_CHANNEL_KEYWORDS):
        return (
            "緊急通知方式說明：\n"
            "199／399 以 LINE 通知為主。\n"
            "799 月費可用 LINE + 簡訊通知 3 位核心守護人，年費可通知 5 位。\n"
            "簡訊會產生成本，正式上線前會設定每位使用者的發送上限，避免誤報造成費用增加。"
        )
    if any(keyword in text for keyword in LARGE_TEXT_KEYWORDS):
        return (
            "大字模式規劃中：\n"
            "這個功能會讓長輩看到更大的文字、更少的選項，以及更明顯的簽到按鈕。\n"
            "目前可先使用手機瀏覽器或 LINE 內建的文字縮放功能。"
        )
    if any(keyword in text for keyword in FAQ_KEYWORDS):
        return (
            "常見問題：\n"
            "Q：守護人一定要註冊嗎？\n"
            "A：不用，對方點 LINE 授權同意後即可接收提醒。\n\n"
            "Q：定位會一直被追蹤嗎？\n"
            "A：預設是 24 小時快照分享；即時追蹤需使用者自行開啟。\n\n"
            "Q：真的緊急怎麼辦？\n"
            "A：若有立即危險，請優先撥打 119。"
        )
    if any(keyword in text for keyword in SUPPORT_KEYWORDS):
        return (
            "客服在這裡。你可以直接回覆你的問題，我們會協助你設定簽到、守護人與方案。\n\n"
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

    state = load_state(data_file)
    profile = get_profile(state, line_user_id)
    notes = dict(profile.get("calendar_notes") or {})
    if content:
        notes[note_date] = content
    else:
        notes.pop(note_date, None)
    profile["calendar_notes"] = notes
    save_state(data_file, state)
    return {"ok": True, "notes": notes}, 200


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


def build_status(profile):
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
            and paid_membership_is_active(profile)
        ),
        "dedicated_support": bool(plan_rules(profile).get("dedicated_support", False)),
        "realtime_trial_days": int(plan_rules(profile).get("realtime_trial_days", 0)),
        "core_guardian_alert_limit": plan_rules(profile).get("core_guardian_alert_limit", 1),
        "guardian_group_limit": plan_rules(profile).get("guardian_group_limit", 0),
        "guardian_group_ids": profile.get("guardian_group_ids", []),
        "is_today_checked": is_today_checked,
        "is_prealert": prealert,
        "is_overdue": overdue,
        "remaining_ms": remaining_ms,
        "cancel_remaining_ms": cancel_remaining_ms,
        "alert_at": alert_at.isoformat(timespec="seconds") if alert_at else None,
        "status_text": status_text,
        "status_class": status_class,
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
    return {"order": order}, 201


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
        req = urllib.request.Request(url, headers={"Authorization": "***" + token})
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
        req = urllib.request.Request(url, headers={"Authorization": "***" + token})
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
        req = urllib.request.Request(url, method="POST", headers={"Authorization": "***" + token})
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
                        f"此群目前有 {mc} 位成員(不含「平安守護助理」)。\n"
                        f"守護群上限 {GROUP_MEMBER_LIMIT} 人,請把群縮到 {GROUP_MEMBER_LIMIT} 人內再重新邀請「平安守護助理」。"
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
            "我已綁定守護群\n"
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
    public_url = (
        payload.get("public_url")
        or os.environ.get("APP_PUBLIC_URL", "")
        or "https://liff.line.me"
    ).rstrip("/")
    invite_url = f"{public_url}/?friend_invite={code}"
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


def update_location(data_file, payload):
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

    share_hours = max(1, min(24, int(payload.get("share_hours") or 24)))
    now = datetime.now()
    state = load_state(data_file)
    profile = get_profile(state, line_user_id)
    profile["location"] = {
        "latitude": round(latitude, 6),
        "longitude": round(longitude, 6),
        "city": str(payload.get("city") or "").strip(),
        "updated_at": now.isoformat(timespec="seconds"),
        "expires_at": (now + timedelta(hours=share_hours)).isoformat(timespec="seconds"),
        "sharing": True,
    }
    save_state(data_file, state)
    return {"ok": True, "location": profile["location"]}, 200


def stop_location_sharing(data_file, payload):
    line_user_id = str(payload.get("line_user_id") or "").strip()
    if not line_user_id:
        return {"error": "missing line_user_id"}, 400
    state = load_state(data_file)
    profile = get_profile(state, line_user_id)
    location = profile.get("location") or {}
    location["sharing"] = False
    location["expires_at"] = datetime.now().isoformat(timespec="seconds")
    profile["location"] = location
    save_state(data_file, state)
    return {"ok": True}, 200


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

    rules = plan_rules(profile)
    if not rules.get("sos_enabled"):
        return {"error": "sos is not available for this plan"}, 403
    if not paid_membership_is_active(profile):
        return {"error": "sos membership is not active"}, 403

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
    if not line_contacts:
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

    active_group_ids = []
    if rules.get("guardian_group_limit"):
        groups = state.get("guardian_groups", {})
        active_group_ids = [
            group_id for group_id in (profile.get("guardian_group_ids") or [])
            if groups.get(group_id, {}).get("owner_line_user_id") == line_user_id
            and groups.get(group_id, {}).get("status") == "active"
        ][: int(rules.get("guardian_group_limit") or 0)]
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
        expires_at = parse_datetime(location.get("expires_at"))
        if not location.get("sharing") or not expires_at or expires_at < now:
            continue
        friends.append(
            {
                "line_user_id": friend_id,
                "display_name": friend.get("display_name", "LINE 使用者"),
                "latitude": location.get("latitude"),
                "longitude": location.get("longitude"),
                "city": location.get("city", ""),
                "updated_at": location.get("updated_at"),
                "expires_at": location.get("expires_at"),
            }
        )
    return {"friends": friends}


def admin_update_user_plan(data_file, payload):
    line_user_id = str(payload.get("line_user_id") or "").strip()
    if not line_user_id:
        return {"error": "missing line_user_id"}, 400
    plan = str(payload.get("plan") or "trial")
    if plan not in PLAN_LIMITS:
        return {"error": "unknown plan"}, 400
    state = load_state(data_file)
    profile = get_profile(state, line_user_id)
    profile["plan"] = plan
    profile["payment_status"] = str(payload.get("payment_status") or ("trial" if plan == "trial" else "active"))
    profile["paid_until"] = str(payload.get("paid_until") or profile.get("paid_until") or "")
    save_state(data_file, state)
    return build_status(profile), 200


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


def admin_allowed(config, password):
    expected = os.environ.get("ADMIN_PASSWORD") or config.get("ADMIN_PASSWORD", "")
    if not expected:
        return False
    return secrets.compare_digest(str(expected), str(password or ""))


def cron_allowed(config, secret):
    expected = config.get("CRON_SECRET") or os.environ.get("CRON_SECRET", "")
    return not expected or secret == expected


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
    body = json.dumps(
        {"to": line_user_id, "messages": [{"type": "text", "text": message}]},
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
    logs.append(
        {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "kind": kind,
            "line_user_id": line_user_id,
            "status": status,
            "message": message[:120],
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
    sent = 0
    skipped = 0
    results = []
    for user in summary["users"]:
        if not user["is_overdue"]:
            continue
        profile = state.get("users", {}).get(user["line_user_id"], user)
        location = profile.get("location") or {}
        location_link = ""
        if profile.get("attach_location_on_alert") and location.get("latitude") and location.get("longitude"):
            location_link = f"\n最後位置：https://www.google.com/maps?q={location['latitude']},{location['longitude']}"
        message = f"該回來簽到囉 ♡\n點一下「我已平安」，讓重要的人放心。{location_link}"
        try:
            result = sender(token, user["line_user_id"], message)
            log_notification(config["DATA_FILE"], "overdue", user["line_user_id"], "sent", message, json.dumps(result, ensure_ascii=False))
            sent += 1
            results.append({"line_user_id": user["line_user_id"], "result": result})
        except Exception as exc:
            log_notification(config["DATA_FILE"], "overdue", user["line_user_id"], "failed", message, str(exc))
            skipped += 1
            results.append({"line_user_id": user["line_user_id"], "error": str(exc)})

        contact_message = (
            f"{profile.get('display_name') or '使用者'} 已超過平安簽到時間，請協助確認。"
            f"{location_link}"
        )
        for contact in (profile.get("contacts") or [])[: plan_rules(profile)["contact_limit"]]:
            methods = contact.get("notify_methods") or ["line"]
            if "line" in methods and contact.get("line_id"):
                try:
                    result = sender(token, contact["line_id"], contact_message)
                    log_notification(config["DATA_FILE"], "contact_alert", contact["line_id"], "sent", contact_message, json.dumps(result, ensure_ascii=False))
                    sent += 1
                    results.append({"line_user_id": contact["line_id"], "result": result})
                except Exception as exc:
                    log_notification(config["DATA_FILE"], "contact_alert", contact["line_id"], "failed", contact_message, str(exc))
                    skipped += 1
                    results.append({"line_user_id": contact["line_id"], "error": str(exc)})
            for method in methods:
                if method in {"sms", "phone"}:
                    detail = contact.get("phone") or "missing phone"
                    log_notification(config["DATA_FILE"], f"{method}_contact_alert", user["line_user_id"], "pending", contact_message, detail)
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
            link_text = f"\n前往我的守護資料：{public_url}/?page=profile" if public_url else ""
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
        link_text = f"\n一鍵邀請守護人：{public_url}/?page=guardian" if public_url else ""
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
    state = load_state(data_file)
    now = current_app_time(config)
    invite_cutoff = now - timedelta(days=7)
    notification_cutoff = now - timedelta(days=90)
    expired_locations_removed = 0

    for profile in state.get("users", {}).values():
        location = profile.get("location") or {}
        expires_at = parse_datetime(location.get("expires_at"))
        if expires_at and expires_at < now:
            profile["location"] = {}
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
        link_text = f"\n打開簽到：{public_url}/" if public_url else ""
        message = (
            f"今天還在嗎 ✨\n"
            f"到你設定的簽到時間（{target_time}）囉，點一下完成今日平安簽到。{link_text}"
        )
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
        # Both token and secret are required for LINE webhook / messaging.
        "line_enabled": bool(token and secret),
    }


def create_app(config=None):
    if Flask is None:
        return MiniApp(config)

    app = Flask(__name__, static_folder=".", static_url_path="")
    app._start_time = datetime.now()  # 2026-07-21 patch 17: 供 /api/bot/status 計算 uptime
    app.config.update(
        DATA_FILE=os.environ.get("DATA_FILE", str(Path(__file__).resolve().parent / "data" / "state.json")),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", ""),
        LINE_CHANNEL_ACCESS_TOKEN=os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", ""),
        LINE_CHANNEL_SECRET=os.environ.get("LINE_CHANNEL_SECRET", ""),
        LIFF_ID=os.environ.get("LIFF_ID", ""),
        APP_PUBLIC_URL=os.environ.get("APP_PUBLIC_URL", ""),
        APP_TIMEZONE=os.environ.get("APP_TIMEZONE", "Asia/Taipei"),
        CRON_SECRET=os.environ.get("CRON_SECRET", ""),
    )
    if config:
        app.config.update(config)

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/health")
    def health():
        return jsonify({"ok": True})

    @app.get("/admin")
    def admin():
        return send_from_directory(app.static_folder, "admin.html")

    @app.get("/test_bind")
    def test_bind():
        return send_from_directory(app.static_folder, "test_bind.html")

    @app.get("/terms")
    def terms():
        return send_from_directory(app.static_folder, "terms.html")

    @app.get("/privacy")
    def privacy():
        return send_from_directory(app.static_folder, "privacy.html")

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
                target += f"?open={open_action}"
            if fragment:
                target += f"#{fragment.lstrip('#')}"
        if redirect is not None:
            return redirect(target, code=302)
        return jsonify({"redirect": target}), 302

    # 圖文選單 / 舊連結：導向 liff.line.me 內嵌（單一 Endpoint = index.html）
    @app.get("/liff/checkin")
    def liff_checkin():
        return _liff_embed_redirect(fragment="home")

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
            - bot_name: 平安守護助理
            - uptime_seconds: 進程啟動後秒數
            - users_total: 註冊人數
            - guardian_groups_total: 守護群綁定總數
            - guardian_groups_active: 有效的守護群數
            - timestamp: 當下時間
        """
        state = load_state(app.config["DATA_FILE"])
        groups = state.get("guardian_groups", {})
        active_groups = sum(1 for g in groups.values() if g.get("status") == "active")
        now = datetime.now()
        proc_start = getattr(app, "_start_time", None)
        uptime = (now - proc_start).total_seconds() if proc_start else None
        return jsonify({
            "service": "alive-checkin",
            "bot_name": "平安守護助理",
            "uptime_seconds": round(uptime, 1) if uptime else None,
            "users_total": len(state.get("users", {})),
            "guardian_groups_total": len(groups),
            "guardian_groups_active": active_groups,
            "timestamp": now.isoformat(timespec="seconds"),
        })

    @app.get("/api/status")
    def status():
        line_user_id = (request.args.get("line_user_id") or "").strip()
        if not line_user_id:
            return jsonify({"ok": False, "error": "missing line_user_id"}), 400
        state = load_state(app.config["DATA_FILE"])
        profile = state.get("users", {}).get(line_user_id)
        if not profile:
            return jsonify({"ok": False, "error": "user not registered", "line_user_id": line_user_id}), 404
        return jsonify(build_status(profile))

    @app.post("/api/line/register")
    def line_register():
        data, code = register_line_user(app.config["DATA_FILE"], request.get_json(silent=True) or {})
        return jsonify(data), code

    @app.post("/api/checkin")
    def checkin():
        payload = request.get_json(silent=True) or {}
        line_user_id = (payload.get("line_user_id") or "").strip()
        if not line_user_id:
            return jsonify({"ok": False, "error": "missing line_user_id"}), 400
        state = load_state(app.config["DATA_FILE"])
        if line_user_id not in state.get("users", {}):
            return jsonify({"ok": False, "error": "user not registered", "line_user_id": line_user_id}), 404
        status = record_checkin(app.config["DATA_FILE"], payload)
        status["ok"] = True
        return jsonify(status)

    @app.post("/callback")
    def line_callback():
        if LineBotApi is None or WebhookHandler is None:
            return jsonify({"error": "line-bot-sdk is not installed"}), 503
        token = app.config.get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get("CHANNEL_ACCESS_TOKEN", "")
        secret = app.config.get("LINE_CHANNEL_SECRET") or os.environ.get("CHANNEL_SECRET", "")
        if not token or not secret:
            return jsonify({"error": "LINE credentials are not configured"}), 503

        line_bot_api = LineBotApi(token)
        handler = WebhookHandler(secret)

        def _sos_handle(line_bot_api, line_user_id, command):
            """2026-07-21 patch 21: SOS 3 次連按流程(快速發送版)。

            command:
              - 'SOS' / 'sos'         : 按一次 SOS(累計 tap_count)
              - 'SOS 取消'           : 取消 pending SOS
            """
            state = load_state(app.config["DATA_FILE"])
            profile = get_profile(state, line_user_id) if line_user_id else None

            def reply(flex, alt_text=""):
                if FlexSendMessage is not None and flex is not None:
                    line_bot_api.push_message(
                        line_user_id,
                        FlexSendMessage(alt_text=alt_text, contents=flex),
                    )
                else:
                    line_bot_api.push_message(
                        line_user_id,
                        TextSendMessage(text=alt_text or "SOS"),
                    )

            # === Plan 檢查 ===
            rules = plan_rules(profile) if profile else {}
            sos_enabled = bool(rules.get("sos_enabled", False))
            _plan_map = {"paid_799": "799 月費", "paid_799_year": "799 年費"}
            plan_label = _plan_map.get((profile or {}).get("plan", ""), (profile or {}).get("plan") or "尚未訂閱")

            if not sos_enabled:
                reply(None, (
                    f"🛡️ SOS 求救 是 799 方案限定功能\n\n"
                    f"你目前的方案:{plan_label or '尚未訂閱'}\n\n"
                    f"升級 799 守護版(月費/年費)才能使用 SOS 求救\n"
                    f"在主選單點「查看方案」了解详情"
                ))
                return

            if command == "SOS 取消":
                if sos_flow.sos_cancel_pending(state, line_user_id):
                    save_state(app.config["DATA_FILE"], state)
                    reply(sos_flow.sos_cancelled_flex(), "✅ SOS 已取消")
                else:
                    reply(None, "沒有待取消的 SOS")
                return

            # command == 'SOS' / 'sos':記錄一次點選
            result = sos_flow.sos_tap(state, line_user_id)
            entry = result.get("entry", {})
            action = result.get("action")
            tap_count = entry.get("tap_count", 1)

            if action == "sent":
                # 已送過的,顯示 sent Flex(並有取消按鈕)
                reply(sos_flow.sos_sent_flex(), "🚨 SOS 已發送")
                save_state(app.config["DATA_FILE"], state)
                return

            # 第 3 次按 → 立刻發送
            if tap_count >= 3:
                # 實際呼叫 trigger_sos
                try:
                    res, code = trigger_sos(
                        app.config["DATA_FILE"],
                        {"line_user_id": line_user_id, "via": "3tap"},
                        app.config,
                    )
                    event_id = res.get("event_id") if isinstance(res, dict) else None
                    sos_flow.sos_mark_sent(state, line_user_id, event_id)
                    reply(sos_flow.sos_sent_flex(), "🚨 SOS 已發送")
                except Exception as exc:
                    # 發送失敗也要讓用戶知道
                    sos_flow.sos_cancel_pending(state, line_user_id)
                    reply(None, f"⚠️ SOS 發送失敗:{str(exc)[:200]}")
                save_state(app.config["DATA_FILE"], state)
                return

            # 第 1 / 2 次按 → 顯示警告卡
            reply(sos_flow.sos_warning_flex(tap_count), f"🚨 SOS 求救 ({tap_count}/3)")
            save_state(app.config["DATA_FILE"], state)

        @handler.add(JoinEvent)
        def handle_group_join(event):
            line_user_id = getattr(event.source, "user_id", None)
            group_id = getattr(event.source, "group_id", None)
            outcome, _status = guardian_group_join_outcome(
                app.config["DATA_FILE"], line_user_id, group_id
            )
            try:
                # 2026-07-21 patch 27: 計算 owner_info 供 intro_flex 顯示管理員狀態
                owner_info = {"bound": False, "is_owner": False, "owner_id": None,
                              "is_active": False, "owner_plan": None}
                state = load_state(app.config["DATA_FILE"])
                existing_group = state.get("guardian_groups", {}).get(group_id or "", {})
                if existing_group.get("status") == "active":
                    owner_id = existing_group.get("owner_line_user_id")
                    owner_profile = state.get("users", {}).get(owner_id, {})
                    owner_plan = owner_profile.get("plan")
                    is_active = bool(owner_profile) and paid_membership_is_active(owner_profile)
                    owner_info = {
                        "bound": True,
                        "is_owner": (line_user_id == owner_id),
                        "owner_id": owner_id,
                        "is_active": is_active,
                        "owner_plan": owner_plan,
                    }

                # 2026-07-21 patch 27: 一律先自我介紹(讓所有用戶都看到 bot 是什麼)
                # 不論綁定成功或失敗,都先送 intro Flex(8 區塊)
                # 如果未綁定,owner_info.bound=False → 不顯示 owner 區塊
                # 在 footer 加 CTA 提示用戶對應動作
                if FlexSendMessage is not None and guardian_group_intro_flex is not None:
                    line_bot_api.reply_message(
                        event.reply_token,
                        FlexSendMessage(
                            alt_text="🛡️ 守護群已就緒,管理員可一鍵綁定",
                            contents=guardian_group_intro_flex(owner_info),
                        ),
                    )
                    # 如果資格不符(需 799 但用戶不是),在自我介紹後補一張「如何啟用」Flex
                    if _status != 200 and outcome.get("should_leave") is False:
                        # 資格不符但不是「已被佔用」,發提醒
                        reason = outcome.get("reply_text", "需要 799 守護版才能建立守護群")
                        # 簡短文字提醒(因為剛才已送了 intro Flex)
                        try:
                            line_bot_api.push_message(
                                group_id,
                                TextSendMessage(text=(
                                    f"💡 {reason}\n\n"
                                    "升級 799 守護版(月費/年費)即可在群裡綁定守護群\n"
                                    "在 LINE 主選單點「查看方案」了解更多"
                                )),
                            )
                        except Exception:
                            pass
                else:
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text=outcome["reply_text"]),
                    )
            finally:
                # 已被其他會員佔用 → 直接離開(沒辦法搶別人的群)
                # 資格不符 → 保留在群(讓用戶升級後可以綁)
                # 2026-07-21 patch 27: 只在被佔用時離開
                if group_id and _status == 409:
                    line_bot_api.leave_group(group_id)

        @handler.add(FollowEvent)
        def handle_follow(event):
            """加好友歡迎：優先回 Flex(Exact 歡迎文案 + 立即綁定守護人)。

            不再用純文字為主、對使用者文案不出現機器人字眼。Flex 失敗時才 fallback 短文案。
            """
            line_user_id = getattr(event.source, "user_id", None)
            display_name = None
            if line_user_id:
                try:
                    profile = line_bot_api.get_profile(line_user_id)
                    display_name = getattr(profile, "display_name", None) or None
                except Exception:
                    display_name = None
            name = (display_name or "").strip() or "您"
            welcome_fallback = (
                f"👋 {name} 您好，歡迎加入今天還在嗎\n\n"
                "我是您的每日平安小助手，會在您設定的時間提醒您報平安，"
                "只有超過時間仍未報平安，才會通知您指定的守護人\n\n"
                "開始使用前，請先完成 1 位守護人綁定，並設定每日提醒時間\n\n"
                "🎁 完成設定即享 7 天免費安心體驗\n\n"
                "🚨 緊急狀況請直接撥打 119，聊天訊息可能因網路延遲\n\n"
                f"請開啟：{(liff_entry_url(open_action='onboarding') if liff_entry_url else 'https://liff.line.me/2010674803-rK98c0lo?open=onboarding')}"
            )
            alt_text = f"👋 {name} 您好，歡迎加入今天還在嗎 — 完成設定即享 7 天免費安心體驗"
            flex_contents = welcome_flex(display_name) if welcome_flex is not None else None
            try:
                if FlexSendMessage is not None and flex_contents is not None:
                    line_bot_api.reply_message(
                        event.reply_token,
                        FlexSendMessage(
                            alt_text=alt_text,
                            contents=flex_contents,
                        ),
                    )
                else:
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text=welcome_fallback),
                    )
            except Exception:
                try:
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text=welcome_fallback),
                    )
                except Exception:
                    # reply_token 可能已用過：改 push
                    if line_user_id and FlexSendMessage is not None and flex_contents is not None:
                        try:
                            line_bot_api.push_message(
                                line_user_id,
                                FlexSendMessage(
                                    alt_text=alt_text,
                                    contents=flex_contents,
                                ),
                            )
                        except Exception:
                            pass

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
                        f"⚠️ 「平安守護助理」不是此群管理員,另有 {result['bot_not_admin_count']} 位無法請出。"
                        "請把「平安守護助理」設為管理員後再試,或管理員手動退出超額成員。"
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

            # 2026-07-21 patch 20: SOS 求救流程(3 次確認 + 10 分鐘取消期)
            # 在 BOT 狀態前面 — SOS 生死大事必須最先判斷
            if sos_flow is not None and stripped in ("SOS", "sos", "SOS 確認 2", "SOS 確認 3", "SOS 取消"):
                _sos_handle(line_bot_api, line_user_id, stripped)
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
                    f"🤖 我是「平安守護助理」\\n"
                    f"屬於「今天還在嗎」這個服務\\n\\n"
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
                # 1) 綁定守護群(保留「綁定平安守護助理」alias)
                if stripped in ("綁定守護群", "綁定平安守護助理"):
                    result, code = bind_guardian_group(
                        app.config["DATA_FILE"],
                        {"line_user_id": line_user_id, "group_id": group_id},
                    )
                    if FlexSendMessage is not None and guardian_group_bind_confirm_flex is not None:
                        if code == 200:
                            line_bot_api.reply_message(
                                event.reply_token,
                                FlexSendMessage(
                                    alt_text="✅ 我已綁定守護群",
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
                        # fallback 純文字：成功回覆固定「我已綁定守護群」
                        if code == 200:
                            reply_text = (
                                "我已綁定守護群\n"
                                f"目前已綁定 {result.get('guardian_group_count', 1)}/"
                                f"{result.get('guardian_group_limit', 3)} 個群組。"
                            )
                        elif result.get("should_leave"):
                            reply_text = (
                                "這個群組目前無法啟用守護功能。守護群限有效的 799 月費或年費會員建立；月費最多 1 群，年費最多 3 群。\n"
                                "請先完成升級，再重新邀請「平安守護助理」；我現在會退出群組。"
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
                                alt_text="📊 守護群狀態",
                                contents=guardian_group_status_flex(profile, state),
                            ),
                        )
                    else:
                        # fallback
                        owned_count = len(profile.get("guardian_group_ids") or [])
                        line_bot_api.reply_message(
                            event.reply_token,
                            TextSendMessage(text=f"目前已綁定 {owned_count} 個守護群"),
                        )
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
                            TextSendMessage(text="使用說明:1.升級 799 → 2.建群 → 3.邀「平安守護助理」 → 4.設管理員 → 5.打「綁定平安守護助理」"),
                        )
                    return

                # 4) 管理員設定 / 怎麼設管理員
                if stripped in ("管理員設定", "設管理員", "怎麼設管理員", "6步驟"):
                    if FlexSendMessage is not None and guardian_group_admin_setup_flex is not None:
                        line_bot_api.reply_message(
                            event.reply_token,
                            FlexSendMessage(
                                alt_text="⚙️ 設定「平安守護助理」為管理員 6 步驟",
                                contents=guardian_group_admin_setup_flex(),
                            ),
                        )
                    else:
                        line_bot_api.reply_message(
                            event.reply_token,
                            TextSendMessage(text="管理員設定 6 步驟:1.群右上「≡」→ 2.選成員 → 3.長按「平安守護助理」 → 4.設為管理員 → 5.確定 → 6.完成"),
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
        body = request.get_data(as_text=True)
        try:
            handler.handle(body, signature)
        except InvalidSignatureError:
            return jsonify({"error": "invalid signature"}), 400
        except LineBotApiError as exc:
            return jsonify({"error": "line api error", "detail": str(exc)}), 502
        return jsonify({"ok": True})

    @app.post("/api/warning/cancel")
    def warning_cancel_api():
        return jsonify(cancel_warning(app.config["DATA_FILE"], request.get_json(silent=True) or {}, app.config))

    @app.post("/api/settings")
    def settings():
        return jsonify(save_settings_for_profile(app.config["DATA_FILE"], request.get_json(silent=True) or {}))

    @app.post("/api/billing/preferences")
    def billing_preferences_api():
        data, code = save_billing_preferences(app.config["DATA_FILE"], request.get_json(silent=True) or {})
        return jsonify(data), code

    @app.post("/api/payments/orders")
    def payment_orders_api():
        data, code = create_payment_order(app.config["DATA_FILE"], request.get_json(silent=True) or {}, app.config)
        return jsonify(data), code

    @app.get("/api/contacts")
    def contacts_get():
        return jsonify(get_contacts(app.config["DATA_FILE"], request.args.get("line_user_id")))

    @app.post("/api/contacts")
    def contacts_post():
        data, code = save_contacts(app.config["DATA_FILE"], request.get_json(silent=True) or {})
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
        line_user_id = (payload.get("line_user_id") or "").strip()
        if not line_user_id:
            return jsonify({"ok": False, "error": "missing line_user_id"}), 400
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
        line_user_id = (payload.get("line_user_id") or "").strip()
        if not line_user_id:
            return jsonify({"ok": False, "error": "missing line_user_id"}), 400
        data, code = update_single_contact(app.config["DATA_FILE"], line_user_id, contact_id, payload)
        if code == 200:
            response = {"ok": True, "contact": data["contact"], "contacts": data["contacts"]}
        else:
            response = {"ok": False, "error": data.get("error"), "fields": data.get("fields")}
        return jsonify(response), code

    @app.delete("/api/contacts/<contact_id>")
    def contacts_delete(contact_id):
        """刪除單一守護人聯絡人。"""
        line_user_id = (request.args.get("line_user_id") or "").strip()
        if not line_user_id:
            return jsonify({"ok": False, "error": "missing line_user_id"}), 400
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
        data, code = trigger_sos(app.config["DATA_FILE"], request.get_json(silent=True) or {}, app.config)
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
        data, code = delete_account(app.config["DATA_FILE"], request.get_json(silent=True) or {})
        return jsonify(data), code

    @app.post("/api/account/export")
    def account_export_api():
        data, code = export_account_data(app.config["DATA_FILE"], request.get_json(silent=True) or {})
        return jsonify(data), code

    @app.post("/api/account/history/delete")
    def account_history_delete_api():
        data, code = delete_personal_history(app.config["DATA_FILE"], request.get_json(silent=True) or {})
        return jsonify(data), code

    @app.get("/api/admin/summary")
    def admin_summary_api():
        password = request.args.get("password") or request.headers.get("X-Admin-Password", "")
        if not admin_allowed(app.config, password):
            return jsonify({"error": "unauthorized"}), 401
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

    @app.route("/api/cron/renewal-reminders", methods=["GET", "POST"])
    def cron_renewal_reminders_api():
        secret = request.args.get("secret") or request.headers.get("X-Cron-Secret", "")
        if not cron_allowed(app.config, secret):
            return jsonify({"error": "unauthorized"}), 401
        data, code = send_renewal_reminders(app.config)
        return jsonify(data), code

    @app.route("/api/cron/data-cleanup", methods=["GET", "POST"])
    def cron_data_cleanup_api():
        secret = request.args.get("secret") or request.headers.get("X-Cron-Secret", "")
        if not cron_allowed(app.config, secret):
            return jsonify({"error": "unauthorized"}), 401
        data, code = cleanup_expired_data(app.config)
        return jsonify(data), code

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
            if not admin_allowed(self.app.config, params.get("password", "")):
                return MiniResponse({"error": "unauthorized"}, 401)
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
                    state = load_state(data_file)
                    return handler.send_json(build_status(get_profile(state, params.get("line_user_id"))))
                if route == "/api/admin/summary":
                    if not admin_allowed(config, params.get("password", "")):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    return handler.send_json(admin_summary(data_file))
                if route == "/api/contacts":
                    return handler.send_json(get_contacts(data_file, params.get("line_user_id")))
                if route == "/api/calendar-notes":
                    return handler.send_json(get_calendar_notes(data_file, params.get("line_user_id")))
                if route == "/api/friends/locations":
                    return handler.send_json(friend_locations(data_file, params.get("line_user_id")))
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
