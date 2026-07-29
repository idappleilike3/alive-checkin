Warning: truncated output (original token count: 210567)
Total output lines: 20485

import copy
import base64
import calendar
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import smtplib
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from flask import Flask, Response, jsonify, redirect, request, send_from_directory, session
except ModuleNotFoundError:
    Flask = None
    Response = None
    redirect = None
    session = None

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
        PostbackEvent,
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
    PostbackEvent = None

# 守護群 Flex 構建器(2026-07-21 patch 11)
try:
    from guardian_group_flex import (
        guardian_group_intro_flex,
        guardian_group_status_flex,
        guardian_group_bind_confirm_flex,
        guardian_group_bind_fail_flex,
        guardian_group_member_joined_flex,
        guardian_group_setup_nudge_text,
        guardian_group_user_guide_flex,
        guardian_group_admin_setup_flex,
        welcome_flex,
        welcome_greeting_text,
        liff_entry_url,
        get_liff_id,
        share_invite_liff_url,
        share_invite_flex,
        line_native_share_url,
        guardian_invite_share_text,
    )
except Exception:
    guardian_group_intro_flex = None
    guardian_group_status_flex = None
    guardian_group_bind_confirm_flex = None
    guardian_group_bind_fail_flex = None
    guardian_group_member_joined_flex = None
    guardian_group_setup_nudge_text = None
    guardian_group_user_guide_flex = None
    guardian_group_admin_setup_flex = None
    welcome_flex = None
    welcome_greeting_text = None
    liff_entry_url = None
    get_liff_id = None
    share_invite_liff_url = None
    share_invite_flex = None
    line_native_share_url = None
    guardian_invite_share_text = None

# 註:patch 15 的全域白名單機制(GROUP_ADMINS / is_group_admin / deny_if_not_admin)
# 已於 2026-07-21 移除。「管理員」= 每個守護群的 owner_line_user_id(在 guardian_groups 裡)。
# patch 16 加強 self-intro 顯示 owner 狀態。

# SOS 求救流程(2026-07-21 patch 20):3 次確認 + 10 分鐘取消期
try:
    import sos_flow
except Exception:
    sos_flow = None

try:
    from line_auth import (
        extract_id_token,
        resolve_line_user_id,
        verify_line_id_token_for_channel,
    )
except Exception:  # pragma: no cover
    extract_id_token = None
    resolve_line_user_id = None
    verify_line_id_token_for_channel = None

try:
    import newebpay
except Exception:  # pragma: no cover
    newebpay = None

try:
    import ecpay
except Exception:  # pragma: no cover
    ecpay = None

try:
    from Crypto.Cipher import AES
except Exception:  # pragma: no cover
    AES = None

try:
    import holidays_tw
except Exception:  # pragma: no cover
    holidays_tw = None

from push_delivery import (
    classify_push_exception,
    push_attempt_allowed,
    record_push_failure,
)


DEFAULT_LIFF_ID = "2010848330-UAiqPPYD"
DEFAULT_LEGACY_LIFF_ID = "2010674803-rK98c0lo"
DEFAULT_LINE_LOGIN_CHANNEL_ID = "2010848330"


# 逾時未報平安：會員可選 24／48／72 小時（取代舊固定 36h 主流程）
ALLOWED_GRACE_HOURS = (24, 48, 72)
DEFAULT_GRACE_HOURS = 48
# 滿 N 小時後另有短暫可取消預警緩衝（分鐘）；通知實際在 deadline + 此值之後
DEFAULT_WARNING_CANCEL_MINUTES = 15
# 每日提醒發出後，等待本人回應的時間。新流程以此值通知第一順位守護人，
# 第二、第三順位分別為 2 倍、3 倍；舊 grace_hours 僅保留資料相容。
ALLOWED_OVERDUE_WAIT_MINUTES = (15, 30, 60)
DEFAULT_OVERDUE_WAIT_MINUTES = 30


def normalize_grace_hours(value, default=DEFAULT_GRACE_HOURS):
    """Clamp／對齊到允許的 24／48／72；舊值（如 36）就近對齊。"""
    try:
        hours = int(value)
    except (TypeError, ValueError):
        return int(default)
    if hours in ALLOWED_GRACE_HOURS:
        return hours
    # 就近；並列時偏向產品預設 48
    return min(ALLOWED_GRACE_HOURS, key=lambda h: (abs(h - hours), abs(h - int(default))))


def normalize_overdue_wait_minutes(value, default=DEFAULT_OVERDUE_WAIT_MINUTES):
    """對齊到 15／30／60 分鐘；無效值使用 30 分鐘預設。"""
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return int(default)
    if minutes in ALLOWED_OVERDUE_WAIT_MINUTES:
        return minutes
    return min(
        ALLOWED_OVERDUE_WAIT_MINUTES,
        key=lambda item: (abs(item - minutes), abs(item - int(default))),
    )


DEFAULT_PROFILE = {
    "last_check_in": None,
    "history": [],
    "checkin_records": [],
    "contact_email": "",
    "grace_hours": DEFAULT_GRACE_HOURS,
    "overdue_wait_minutes": DEFAULT_OVERDUE_WAIT_MINUTES,
    "reminder_time": "12:00",
    "reminder_times": ["12:00", "18:00"],
    "checkin_mode": "manual",
    "auto_checkin_on_open": False,
    "warning_cancel_minutes": DEFAULT_WARNING_CANCEL_MINUTES,
    "alert_channels": ["line"],
    "attach_location_on_alert": False,
    "contacts": [],
    "contact_capacity_reminder_enabled": False,
    "contact_reminder_sent_dates": [],
    "checkin_reminder_sent_dates": [],
    "checkin_reminder_sent_slots": {},
    "active_overdue_event": None,
    "daily_checkin_reminder_enabled": True,
    "guardian_details_reminder_enabled": True,
    "guardian_details_reminder_sent_at": "",
    "plan": "trial",
    "membership_source": "",
    "free_eligibility_source": "",
    "free_eligibility_used_at": "",
    "trial_started_at": None,
    "trial_end": None,
    "trial_policy_version": "",
    "trial_notice_days_sent": [],
    # 舊版相容欄位；新政策固定為 0，邀請不再延長體驗。
    "trial_bonus_days": 0,
    "payment_status": "trial",
    "paid_until": "",
    "billing_cycle": "trial",
    "payment_provider": "",
    "payment_method_last4": "",
    "next_billing_date": "",
    "auto_renew_requested": False,
    "auto_renew_enabled": False,
    "auto_renew_status": "off",
    "newebpay_period_no": "",
    "newebpay_period_order_no": "",
    # 舊版相容欄位；現行政策不設自動刪除期限，排程會清除舊倒數並還原舊封存。
    "plan_expired_at": "",
    "contacts_retain_until": "",
    "contacts_archived": [],
    "friends": [],
    "location": {},
    "guardian_group_ids": [],
    "calendar_notes": {},
    "smart_reminders": [],
    "smart_reminder_sent_keys": [],
    "smart_reminder_defaults": {"notify_private": True, "notify_group": False},
    "guarding_for": [],
    "invited_by": "",
    "guarding_details": [],
    # 試用／方案到期提醒（≤3 天或已到期）；opt-out 後不再催
    "expiry_remind_opt_out": False,
    "expiry_remind_sent_date": "",
}

PLAN_RANK = {
    "trial": 0,
    "paid_199": 1,
    "paid_199_year": 1,
    "paid_399": 2,
    "paid_399_year": 2,
    "paid_799": 3,
    "paid_799_year": 3,
}

# 試用／付費方案剩餘 ≤ 此天數（含已到期）才推到期提醒；每日最多一次
EXPIRY_REMIND_WITHIN_DAYS = 3
WEEKDAY_SHORT_ZH = ("一", "二", "三", "四", "五", "六", "日")

# 正式新會員與既有 free 過渡會員皆為一次性 14 天體驗。
PUBLIC_TRIAL_DAYS = 14
BETA_TRIAL_DAYS = 21
BETA_COHORT_LIMITS = {"A": 10, "B399": 20, "B799": 10}
BETA_COHORT_PLAN = {
    "A": "paid_799_year",
    "B399": "paid_399_year",
    "B799": "paid_799_year",
}
LAUNCH_SCENARIO_STEPS = {
    "payment": {
        "success", "failure", "cancel", "callback_idempotent", "order_synced"
    },
    "expiry": {"expired", "paused", "renewed"},
}
TRIAL_POLICY_VERSION = "2026-07-no-invite-reward-v1"
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
    "line_message_usage": [],
    "friend_invites": {},
    "contact_rewards": [],
    "support_tickets": [],
    "privacy_requests": [],
    "beta_program_members": [],
    "backup_exports": [],
    "r2_backup_exports": [],
    "guardian_groups": {},
    "orders": [],
    "account_migration_tickets": {},
    "account_migration_aliases": {},
    "account_migration_audit": [],
    "account_migration_snapshots": {},
}

PLAN_LIMITS = {
    # 最終方案總覽（2026-07）：
    # core_guardian_alert_limit＝核心守護人；emergency_contact_limit＝緊急聯絡人；
    # contact_limit＝兩者合計（相容舊欄位）；daily_reminders＝LINE 私聊預警／日；
    # 不賣簡訊／免提／好友地圖／軌跡；199＝15 分鐘；399＝1/3 小時；799＝1/3/6/8 小時
    "free": {
        "contact_limit": 3,
        "emergency_contact_limit": 2,
        "friend_location_limit": 0,
        "daily_reminders": 1,
        "channels": ["line"],
        "core_guardian_alert_limit": 1,
        "realtime_tracking": False,
        "trajectory_days": 0,
        "offline_sync_days": 0,
        "sos_enabled": True,
        "guardian_group_limit": 0,
        "safety_guard_hours": [],
        "safety_guard_daily_limit": 0,
    },
    "trial": {
        # 14 天免費體驗固定比照 199 活著版（月方案）。
        "contact_limit": 6,
        "emergency_contact_limit": 4,
        "friend_location_limit": 0,
        "daily_reminders": 1,
        "channels": ["line"],
        "location_mode": "snapshot_24h",
        "core_guardian_alert_limit": 2,
        "realtime_tracking": False,
        "trajectory_days": 0,
        "offline_sync_days": 0,
        "sos_enabled": True,
        "guardian_group_limit": 0,
        "safety_guard_hours": [0.25],
        "safety_guard_daily_limit": 2,
    },
    "paid_199": {
        "contact_limit": 6,
        "emergency_contact_limit": 4,
        "friend_location_limit": 0,
        "daily_reminders": 1,
        "channels": ["line"],
        "location_mode": "snapshot_24h",
        "core_guardian_alert_limit": 2,
        "realtime_tracking": False,
        "trajectory_days": 0,
        "offline_sync_days": 0,
        "sos_enabled": True,
        "guardian_group_limit": 0,
        "safety_guard_hours": [0.25],
        "safety_guard_daily_limit": 2,
    },
    "paid_199_year": {
        "contact_limit": 13,
        "emergency_contact_limit": 10,
        "friend_location_limit": 0,
        "daily_reminders": 2,
        "channels": ["line"],
        "location_mode": "snapshot_24h",
        "core_guardian_alert_limit": 3,
        "realtime_tracking": False,
        "trajectory_days": 0,
        "offline_sync_days": 0,
        "sos_enabled": True,
        "guardian_group_limit": 0,
        "safety_guard_hours": [0.25],
        "safety_guard_daily_limit": 2,
    },
    "paid_399": {
        "contact_limit": 20,
        "emergency_contact_limit": 15,
        "friend_location_limit": 0,
        "daily_reminders": 2,
        "channels": ["line"],
        "location_mode": "realtime",
        "core_guardian_alert_limit": 5,
        "realtime_tracking": False,
        "trajectory_days": 0,
        "offline_sync_days": 0,
        "sos_enabled": True,
        "guardian_group_limit": 0,
        "safety_guard_hours": [1, 3],
        "safety_guard_daily_limit": 3,
    },
    "paid_399_year": {
        "contact_limit": 32,
        "emergency_contact_limit": 25,
        "friend_location_limit": 0,
        "daily_reminders": 2,
        "channels": ["line"],
        "location_mode": "realtime",
        "core_guardian_alert_limit": 7,
        "realtime_tracking": False,
        "trajectory_days": 0,
        "offline_sync_days": 0,
        "sos_enabled": True,
        "guardian_group_limit": 0,
        "realtime_trial_days": 30,
        "safety_guard_hours": [1, 3],
        "safety_guard_daily_limit": 3,
    },
    "paid_799": {
        "contact_limit": 45,
        "emergency_contact_limit": 35,
        "friend_location_limit": 0,
        "daily_reminders": 3,
        "channels": ["line"],
        "location_mode": "full_guard",
        "core_guardian_alert_limit": 10,
        "realtime_tracking": False,
        "trajectory_days": 0,
        "offline_sync_days": 0,
        "sos_enabled": True,
        "guardian_group_limit": 1,
        "guardian_group_member_limit": 50,
        "safety_guard_hours": [1, 3, 6, 8],
        "safety_guard_daily_limit": 5,
    },
    "paid_799_year": {
        "contact_limit": 65,
        "emergency_contact_limit": 50,
        "friend_location_limit": 0,
        "daily_reminders": 3,
        "channels": ["line"],
        "location_mode": "full_guard",
        "core_guardian_alert_limit": 15,
        "realtime_tracking": False,
        "trajectory_days": 0,
        "offline_sync_days": 0,
        "sos_enabled": True,
        "guardian_group_limit": 3,
        "guardian_group_member_limit": 50,
        "safety_guard_hours": [1, 3, 6, 8],
        "safety_guard_daily_limit": 5,
    },
}

PAYMENT_PRODUCTS = {
    # 產品政策：SOS 全方案開放；799 賣「更完整守護」（更多核心／緊急、早中晚、守護群等）
    "paid_199": {"amount": 199, "billing_cycle": "monthly", "duration_days": 30, "display_name": "199 平安版(月)", "tagline": "2 位核心守護人＋15 分鐘安全守護（每日 2 次）"},
    "paid_199_year": {"amount": 1990, "billing_cycle": "yearly", "duration_days": 365, "display_name": "199 平安版(年)", "tagline": "付 10 個月送 2 個月：3 位核心守護人＋每日 2 次 LINE 預警"},
    "paid_399": {"amount": 399, "billing_cycle": "monthly", "duration_days": 30, "display_name": "399 安心版(月)", "tagline": "5 位核心守護人＋安全守護 1／3 小時"},
    "paid_399_year": {"amount": 3990, "billing_cycle": "yearly", "duration_days": 365, "display_name": "399 安心版(年)", "tagline": "付 10 個月送 2 個月：7 位核心守護人＋安全守護 1／3 小時"},
    "paid_799": {"amount": 799, "billing_cycle": "monthly", "duration_days": 30, "display_name": "799 守護版(月)", "tagline": "更完整守護：10 位核心＋早中晚＋守護群"},
    "paid_799_year": {"amount": 7990, "billing_cycle": "yearly", "duration_days": 365, "display_name": "799 守護版(年)", "tagline": "付 10 個月送 2 個月：15 位核心＋最多 3 個守護群"},
}

RICH_MENU_COMMANDS = [
    "今日簽到",
    "綁定守護人",
    "我的狀態",
    "查看方案",
    "問與答",
    "聯絡客服",
]

CHECKIN_KEYWORDS = {"簽到", "打卡", "報平安", "今日簽到", "我平安", "✅ 我平安", "今日已平安"}
CONTACT_KEYWORDS = {"綁定守護人", "聯絡人", "緊急聯絡人", "填聯絡人", "修改電話", "守護人"}
STATUS_KEYWORDS = {"狀態", "我的狀態", "查詢紀錄"}
# 管理員查詢今日誰還沒報平安（私訊或守護群皆可）
DAILY_ROSTER_KEYWORDS = {
    "今日狀態",
    "今日平安狀態",
    "誰沒報平安",
    "未報平安",
    "誰還沒簽到",
    "今天誰還沒報平安",
    "誰還沒報平安",
}
# 守護群通知偏好：逾期／平安狀態預設只私訊核心守護人；群組為選用（預設關）
DEFAULT_GUARDIAN_GROUP_PREFERENCES = {
    "notify_private_guardians": True,
    "notify_group_on_overdue": False,
    "notify_admin_only": True,
    "daily_admin_summary": False,
}
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
    liff_id = (os.environ.get("LIFF_ID") or DEFAULT_LIFF_ID).strip()
    return f"https://liff.line.me/{liff_id}?open={open_action}"


def public_page_url(path=""):
    public_url = (os.environ.get("APP_PUBLIC_URL") or "https://alive-checkin.onrender.com/").strip().rstrip("/")
    path = str(path or "").lstrip("/")
    return f"{public_url}/{path}" if path else f"{public_url}/"


def pricing_direct_url():
    """方案頁 LIFF 直連（避免跳出 LINE 開瀏覽器，跟其他按鈕一致）。"""
    liff_id = (os.environ.get("LIFF_ID") or DEFAULT_LIFF_ID).strip() or DEFAULT_LIFF_ID
    return f"https://liff.line.me/{liff_id}?open=pricing"


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
    lid = (os.environ.get("LIFF_ID") or DEFAULT_LIFF_ID).strip() or DEFAULT_LIFF_ID
    if open_action and not params:
        return f"https://liff.line.me/{lid}?open={open_action}"
    if open_action:
        params["open"] = open_action
    if params:
        return f"https://liff.line.me/{lid}?{urllib.parse.urlencode(params)}"
    return f"https://liff.line.me/{lid}"

def line_app_invite_url(*, invite_from="", friend_invite="", open_action=None):
    """Force-open-in-LINE URL (https://line.me/R/app/...) — more reliable on Android Chrome.

    Use ``?`` not ``/?`` — the slash-before-query form can make LIFF/OAuth return 400.
    """
    lid = (os.environ.get("LIFF_ID") or DEFAULT_LIFF_ID).strip() or DEFAULT_LIFF_ID
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
    return f"https://line.me/R/app/{lid}?{urllib.parse.urlencode(params)}"

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
        if status and status.get("is_today_checked"):
            return build_checkin_success_text(status)
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
            "目前以 LINE 通知已綁定「守護人」為主（逾期未報平安、SOS、安全守護）。\n"
            "守護群僅用於安全事件通知。\n"
            "「緊急聯絡人」是電話備援（手動撥打），不會自動群發。"
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
            "「每日平安」幫你每日報平安；逾時未報或 SOS 時，用 LINE 私訊通知已綁定的核心守護人。\n\n"
            "Q：未報平安多久會通知？\n"
            "A：可在會員中心選 15／30／60 分鐘（預設 30）。系統先再提醒本人一次，之後依第一、第二、第三順位逐步通知守護人。\n\n"
            "Q：核心守護人跟緊急聯絡人差在哪？\n"
            "A：核心＝可收 LINE 通知；緊急聯絡人＝電話備援，不會自動推播／簡訊。\n\n"
            "Q：守護人一定要註冊嗎？\n"
            "A：不用，對方加入官方帳號並點邀請同意即可。\n\n"
            f"完整問與答：{faq_url}\n"
            f"查看方案：{pricing_url}"
        )
    if any(keyword in text for keyword in SUPPORT_KEYWORDS):
        faq_url = line_liff_url("faq")
        return (
            "客服在這裡。請直接在此 LINE 留言你的問題，我們會協助你設定簽到、守護人與方案。\n\n"
            "📩 已收到的問題會在 1–3 個工作天內回覆。\n\n"
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
        DAILY_ROSTER_KEYWORDS,
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


def database_url():
    """External Postgres URL (survives Free web redeploys when disk unavailable)."""
    return (os.environ.get("DATABASE_URL") or os.environ.get("STATE_DATABASE_URL") or "").strip()


def _normalize_database_url(url):
    text = str(url or "").strip()
    if text.startswith("postgres://"):
        return "postgresql://" + text[len("postgres://") :]
    return text


def _pg_connect():
    """Open a short-lived Postgres connection; raises if DATABASE_URL missing/broken."""
    import psycopg

    url = _normalize_database_url(database_url())
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    # External Render host needs SSL; internal hostname usually does not.
    if "render.com" in url and "sslmode=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}sslmode=require"
    return psycopg.connect(url, connect_timeout=10)


def _ensure_pg_kv():
    with _pg_connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS kv_store ("
            "  key TEXT PRIMARY KEY,"
            "  value TEXT NOT NULL,"
            "  revision BIGINT NOT NULL DEFAULT 0,"
            "  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
            ")"
        )
        conn.execute(
            "ALTER TABLE kv_store "
            "ADD COLUMN IF NOT EXISTS revision BIGINT NOT NULL DEFAULT 0"
        )
        conn.commit()


def resolve_data_file(explicit=None):
    """Pick durable state path when a mounted disk is available.

    Render free plan local disk is ephemeral. Prefer:
    1) explicit DATA_FILE / argument
    2) ``/var/data/state.json`` when that mount exists and is writable
    3) repo-local ``data/state.json`` (ephemeral on free Render)

    When ``DATABASE_URL`` is set, SQLite is still used as a local cache mirror;
    authoritative state lives in Postgres ``kv_store``.
    """
    candidates = []
    if explicit:
        candidates.append(str(explicit).strip())
    env_path = (os.environ.get("DATA_FILE") or "").strip()
    if env_path:
        candidates.append(env_path)
    candidates.append("/var/data/state.json")
    candidates.append(str(Path(__file__).resolve().parent / "data" / "state.json"))

    seen = set()
    for raw in candidates:
        if not raw or raw in seen:
            continue
        seen.add(raw)
        path = Path(raw)
        parent = path.parent
        try:
            if parent.exists() and os.access(parent, os.W_OK):
                return str(path)
            # Allow creating repo-local data/ ; do not mkdir /var/data without mount
            if str(parent) in {".", "data"} or str(parent).endswith(os.sep + "data") or parent.name == "data":
                if not str(parent).startswith("/var/"):
                    parent.mkdir(parents=True, exist_ok=True)
                    if os.access(parent, os.W_OK):
                        return str(path)
        except OSError:
            continue
    return str(Path(__file__).resolve().parent / "data" / "state.json")


def persistence_info(data_file):
    """Describe whether the active state path looks durable (disk or Postgres)."""
    path = str(data_file or "")
    db_path = _resolve_db_path(path)
    has_pg = bool(database_url())
    durable = (
        has_pg
        or path.startswith("/var/data")
        or bool(os.environ.get("RENDER_DISK_MOUNT_PATH"))
    )
    backend = "postgres" if has_pg else ("disk" if path.startswith("/var/data") else "ephemeral")
    warning = ""
    if not durable:
        warning = (
            "資料可能因重啟遺失請掛磁碟。"
            "Render Free 本機磁碟會在 redeploy／重啟清空；"
            "請升級 Starter 後掛 Persistent Disk（/var/data）並設 DATA_FILE=/var/data/state.json，"
            "或設定 DATABASE_URL 使用外部 Postgres。"
        )
    return {
        "data_file": path,
        "db_path": db_path,
        "durable": durable,
        "backend": backend,
        "database_url_configured": has_pg,
        "ephemeral_warning": warning,
    }


def get_contact_line_id(contact):
    """LINE user id on a contact (supports legacy line_id + line_user_id)."""
    if not isinstance(contact, dict):
        return ""
    return str(contact.get("line_user_id") or contact.get("line_id") or "").strip()


def contact_is_profile_complete(contact):
    """聯絡人基本資料：姓名 +（手機或信箱）."""
    if not isinstance(contact, dict):
        return False
    name = str(contact.get("name") or "").strip()
    phone = str(contact.get("phone") or "").strip()
    email = str(contact.get("email") or "").strip()
    return bool(name and (phone or email))


def _ensure_db(db_path):
    """Create the SQLite database and kv_store table if missing."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS kv_store ("
            "  key TEXT PRIMARY KEY,"
            "  value TEXT NOT NULL,"
            "  revision INTEGER NOT NULL DEFAULT 0,"
            "  updated_at TEXT NOT NULL DEFAULT (datetime('now'))"
            ")"
        )
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(kv_store)").fetchall()
        }
        if "revision" not in columns:
            conn.execute(
                "ALTER TABLE kv_store "
                "ADD COLUMN revision INTEGER NOT NULL DEFAULT 0"
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


class StateConflictError(RuntimeError):
    pass


def _hydrate_state(saved, revision=None):
    state = {**DEFAULT_STATE, **(saved or {})}
    state["history"] = sorted(set(state.get("history") or []))
    state["users"] = state.get("users") or {}
    state["notification_logs"] = state.get("notification_logs") or []
    state["friend_invites"] = state.get("friend_invites") or {}
    state["contact_rewards"] = state.get("contact_rewards") or []
    state["support_tickets"] = state.get("support_tickets") or []
    state["backup_exports"] = state.get("backup_exports") or []
    state["guardian_groups"] = state.get("guardian_groups") or {}
    state["orders"] = state.get("orders") or []
    state["account_migration_tickets"] = (
        state.get("account_migration_tickets") or {}
    )
    state["account_migration_aliases"] = (
        state.get("account_migration_aliases") or {}
    )
    state["account_migration_audit"] = (
        state.get("account_migration_audit") or []
    )
    state["account_migration_snapshots"] = (
        state.get("account_migration_snapshots") or {}
    )
    if revision is not None:
        state["_state_revision"] = int(revision)
    return state


def _load_state_sqlite(data_file):
    """Load state from SQLite (auto-migrates legacy state.json on first call)."""
    db_path = _resolve_db_path(data_file)
    if not Path(db_path).exists():
        _ensure_db(db_path)
        _migrate_legacy_json(data_file, db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT value, revision FROM kv_store WHERE key = ?", ("default",)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return _hydrate_state({}, revision=0)
    try:
        saved = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return _hydrate_state({}, revision=row[1])
    return _hydrate_state(saved, revision=row[1])


def _save_state_sqlite(data_file, state, force=False):
    db_path = _resolve_db_path(data_file)
    _ensure_db(db_path)
    conn = sqlite3.connect(str(db_path), timeout=30)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT revision FROM kv_store WHERE key = ?",
            ("default",),
        ).fetchone()
        current_revision = int(row[0]) if row else 0
        expected_revision = (state or {}).get("_state_revision")
        if (
            row
            and not force
            and expected_revision is not None
            and int(expected_revision) != current_revision
        ):
            raise StateConflictError("state_conflict")
        if (
            not row
            and not force
            and expected_revision not in (None, 0)
        ):
            raise StateConflictError("state_conflict")

        next_revision = (
            int(expected_revision)
            if force and expected_revision is not None
            else current_revision + 1
        )
        persisted = {**(state or {}), "_state_revision": next_revision}
        payload = json.dumps(persisted, ensure_ascii=False, indent=2)
        if row:
            cursor = conn.execute(
                "UPDATE kv_store "
                "SET value = ?, revision = ?, updated_at = datetime('now') "
                "WHERE key = ? AND revision = ?",
                (payload, next_revision, "default", current_revision),
            )
            if cursor.rowcount != 1:
                raise StateConflictError("state_conflict")
        else:
            conn.execute(
                "INSERT INTO kv_store (key, value, revision, updated_at) "
                "VALUES (?, ?, ?, datetime('now'))",
                ("default", payload, next_revision),
            )
        conn.commit()
        if isinstance(state, dict):
            state["_state_revision"] = next_revision
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _load_state_postgres():
    _ensure_pg_kv()
    with _pg_connect() as conn:
        row = conn.execute(
            "SELECT value, revision FROM kv_store WHERE key = %s", ("default",)
        ).fetchone()
    if not row:
        return _hydrate_state({}, revision=0)
    try:
        return _hydrate_state(json.loads(row[0]), revision=row[1])
    except (json.JSONDecodeError, TypeError, IndexError):
        return _hydrate_state({}, revision=row[1] if len(row) > 1 else 0)


def _save_state_postgres(state):
    _ensure_pg_kv()
    with _pg_connect() as conn:
        row = conn.execute(
            "SELECT revision FROM kv_store WHERE key = %s FOR UPDATE",
            ("default",),
        ).fetchone()
        current_revision = int(row[0]) if row else 0
        expected_revision = (state or {}).get("_state_revision")
        if (
            row
            and expected_revision is not None
            and int(expected_revision) != current_revision
        ):
            raise StateConflictError("state_conflict")
        next_revision = current_revision + 1
        persisted = {**(state or {}), "_state_revision": next_revision}
        payload = json.dumps(persisted, ensure_ascii=False, indent=2)
        if row:
            updated = conn.execute(
                "UPDATE kv_store "
                "SET value = %s, revision = %s, updated_at = NOW() "
                "WHERE key = %s AND revision = %s RETURNING revision",
                (payload, next_revision, "default", current_revision),
            ).fetchone()
            if not updated:
                raise StateConflictError("state_conflict")
            next_revision = int(updated[0])
        else:
            inserted = conn.execute(
                "INSERT INTO kv_store (key, value, revision, updated_at) "
                "VALUES (%s, %s, %s, NOW()) RETURNING revision",
                ("default", payload, next_revision),
            ).fetchone()
            if inserted:
                next_revision = int(inserted[0])
        conn.commit()
        if isinstance(state, dict):
            state["_state_revision"] = next_revision


def _state_user_count(state):
    users = (state or {}).get("users") or {}
    return len(users) if isinstance(users, dict) else 0


def _prefer_richer_state(primary, secondary):
    """Prefer the snapshot that still has per-user records (avoid empty wipe)."""
    p_count = _state_user_count(primary)
    s_count = _state_user_count(secondary)
    if p_count == 0 and s_count > 0:
        return secondary
    if s_count > p_count and p_count == 0:
        return secondary
    return primary if primary is not None else secondary


def load_state(data_file):
    """Load state from Postgres (preferred) or SQLite local cache.

    Never let an empty Postgres row / empty local cache clobber the richer side.
    """
    if database_url():
        try:
            pg_state = _load_state_postgres()
            local = None
            try:
                local = _load_state_sqlite(data_file)
            except Exception:
                local = None

            if pg_state is not None and _state_user_count(pg_state) > 0:
                # Keep a local mirror for ops/debug; never wipe Postgres on mirror fail.
                try:
                    _save_state_sqlite(data_file, pg_state, force=True)
                except Exception:
                    pass
                return pg_state

            # PG empty / missing: seed from local if it has users (first boot after attach).
            if local and (
                _state_user_count(local) > 0
                or local.get("orders")
                or local.get("guardian_groups")
            ):
                try:
                    _save_state_postgres(local)
                except Exception:
                    pass
                return local

            if pg_state is not None:
                # Empty durable row — still authoritative once seeded intentionally.
                return pg_state
            return _hydrate_state({})
        except Exception:
            # PG down → last-resort local cache (may be stale after redeploy)
            return _load_state_sqlite(data_file)
    return _load_state_sqlite(data_file)


def save_state(data_file, state):
    """Persist state to Postgres when configured; always mirror to SQLite when possible.

    Guard: refuse to overwrite a richer Postgres snapshot with an empty users dict
    (common after ephemeral disk wipe + auto-register of a single visitor).
    """
    if database_url():
        try:
            existing = None
            try:
                existing = _load_state_postgres()
            except Exception:
                existing = None
            expected_revision = (state or {}).get("_state_revision")
            existing_revision = (existing or {}).get("_state_revision")
            if (
                expected_revision is not None
                and existing_revision is not None
                and int(expected_revision) != int(existing_revision)
            ):
                raise StateConflictError("state_conflict")
            if (
                existing is not None
                and _state_user_count(existing) > 0
                and _state_user_count(state) == 0
            ):
                # Keep durable users; still allow intentional clears only when callers
                # pass through delete_account paths that remove one user at a time.
                merged = _prefer_richer_state(state, existing)
                if _state_user_count(merged) > 0 and merged is existing:
                    # Merge any non-user top-level keys from the new write.
                    for key, value in (state or {}).items():
                        if key == "users":
                            continue
                        if value not in (None, "", [], {}):
                            existing[key] = value
                    state = existing
            _save_state_postgres(state)
        except StateConflictError:
            raise
        except Exception:
            # Still try local write so the request does not silently discard mutations.
            _save_state_sqlite(data_file, state)
            raise
        try:
            _save_state_sqlite(data_file, state, force=True)
        except Exception:
            pass
        return
    _save_state_sqlite(data_file, state)


def _account_migration_serialize_state(state):
    return json.dumps(state, ensure_ascii=False, indent=2)


def _account_migration_state_from_row(row):
    if not row:
        return _hydrate_state({})
    try:
        revision = row[1] if len(row) > 1 else 0
        return _hydrate_state(json.loads(row[0]), revision=revision)
    except (json.JSONDecodeError, TypeError, IndexError):
        return _hydrate_state({})


def mutate_state_atomically(data_file, mutator):
    """Mutate the authoritative state under a database transaction."""
    if database_url():
        _ensure_pg_kv()
        conn = _pg_connect()
        try:
            conn.execute("BEGIN")
            row = conn.execute(
                "SELECT value, revision FROM kv_store WHERE key = %s FOR UPDATE",
                ("default",),
            ).fetchone()
            state = _account_migration_state_from_row(row)
            working = copy.deepcopy(state)
            result = mutator(working)
            current_revision = (
                int(row[1])
                if row and len(row) > 1
                else int(working.get("_state_revision") or 0)
            )
            next_revision = current_revision + 1
            working["_state_revision"] = next_revision
            payload = _account_migration_serialize_state(working)
            if row:
                conn.execute(
                    "UPDATE kv_store "
                    "SET value = %s, revision = %s, updated_at = NOW() "
                    "WHERE key = %s AND revision = %s",
                    (payload, next_revision, "default", current_revision),
                )
            else:
                conn.execute(
                    "INSERT INTO kv_store (key, value, revision, updated_at) "
                    "VALUES (%s, %s, %s, NOW())",
                    ("default", payload, next_revision),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        try:
            _save_state_sqlite(data_file, working, force=True)
        except Exception:
            pass
        return result

    db_path = _resolve_db_path(data_file)
    _ensure_db(db_path)
    conn = sqlite3.connect(str(db_path), timeout=30)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT value, revision FROM kv_store WHERE key = ?",
            ("default",),
        ).fetchone()
        state = _account_migration_state_from_row(row)
        working = copy.deepcopy(state)
        result = mutator(working)
        current_revision = (
            int(row[1])
            if row and len(row) > 1
            else int(working.get("_state_revision") or 0)
        )
        next_revision = current_revision + 1
        working["_state_revision"] = next_revision
        payload = _account_migration_serialize_state(working)
        if row:
            cursor = conn.execute(
                "UPDATE kv_store "
                "SET value = ?, revision = ?, updated_at = datetime('now') "
                "WHERE key = ? AND revision = ?",
                (payload, next_revision, "default", current_revision),
            )
            if cursor.rowcount != 1:
                raise StateConflictError("state_conflict")
        else:
            conn.execute(
                "INSERT INTO kv_store (key, value, revision, updated_at) "
                "VALUES (?, ?, ?, datetime('now'))",
                ("default", payload, next_revision),
            )
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def current_app_time(config=None):
    """App-local now, default Asia/Taipei (naive). Never use bare datetime.now() for calendar days."""
    config = config or {}
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


def today_string(config=None):
    """YYYY-MM-DD in APP_TIMEZONE (Asia/Taipei). Used for history / is_today_checked."""
    return current_app_time(config).strftime("%Y-%m-%d")


def parse_last_checkin(value):
    if not value:
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def date_string_in_taipei(value):
    """Calendar date (Asia/Taipei) for a datetime / ISO string.

    Naive timestamps are interpreted as UTC first (Render default), then as
    already-Taipei local — either matching today counts as checked-in.
    """
    dt = parse_last_checkin(value) if not isinstance(value, datetime) else value
    if not dt:
        return ""
    try:
        tz = ZoneInfo("Asia/Taipei")
        candidates = []
        if dt.tzinfo is None:
            candidates.append(dt.replace(tzinfo=timezone.utc).astimezone(tz))
            candidates.append(dt.replace(tzinfo=tz))
        else:
            candidates.append(dt.astimezone(tz))
        return candidates[0].strftime("%Y-%m-%d")
    except Exception:
        return dt.strftime("%Y-%m-%d")


def profile_is_today_checked(profile, config=None, now=None):
    """True when user already 報平安 for the Taipei calendar day.

    Prefer history[]; also accept last_check_in landing on today in Taipei
    (covers UTC/Taipei mismatch that caused 鬼打牆 re-prompts).
    """
    now = now or current_app_time(config)
    today = now.strftime("%Y-%m-%d")
    history = set(profile.get("history") or [])
    if today in history:
        return True
    last = profile.get("last_check_in")
    if not last:
        return False
    dt = parse_last_checkin(last)
    if not dt:
        return str(last)[:10] == today
    try:
        tz = ZoneInfo("Asia/Taipei")
        dates = set()
        if dt.tzinfo is None:
            dates.add(dt.replace(tzinfo=timezone.utc).astimezone(tz).strftime("%Y-%m-%d"))
            dates.add(dt.replace(tzinfo=tz).strftime("%Y-%m-%d"))
            dates.add(dt.strftime("%Y-%m-%d"))
        else:
            dates.add(dt.astimezone(tz).strftime("%Y-%m-%d"))
        return today in dates
    except Exception:
        return str(last)[:10] == today


def format_md_weekday(dt):
    """Asia/Taipei 顯示：7/25（六）"""
    try:
        return f"{int(dt.month)}/{int(dt.day)}（{WEEKDAY_SHORT_ZH[dt.weekday()]}）"
    except Exception:
        return ""


def format_hm(dt):
    try:
        return dt.strftime("%H:%M")
    except Exception:
        return ""


def checkin_blessing_text(now):
    """節日祝福優先，否則輪播正向短句（holidays_tw）。"""
    if holidays_tw is not None:
        try:
            holiday = holidays_tw.holiday_for(now)
            blessing = str((holiday or {}).get("blessing") or "").strip()
            if blessing:
                return blessing
            quote = str(holidays_tw.positive_quote_for(now) or "").strip()
            if quote:
                return quote
        except Exception:
            pass
    return "每一天的平安，都是給家人最好的禮物。"


def next_checkin_reminder_info(profile, config=None, now=None):
    """Next daily 報平安 reminder slot after now (or tomorrow first slot if already checked).

    Product rule: once 報平安成功 for Taipei today, remaining same-day slots are skipped
    — next_reminder jumps to tomorrow's first slot.
    """
    now = now or current_app_time(config)
    times = reminder_times_for_profile(profile) or ["12:00"]
    checked = profile_is_today_checked(profile, config=config, now=now)

    def _parse_hm(text):
        try:
            hour, minute = [int(part) for part in str(text).split(":", 1)]
            return hour, minute
        except Exception:
            return 12, 0

    if not checked:
        for slot in times:
            hour, minute = _parse_hm(slot)
            candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate > now:
                return {
                    "next_reminder_at": candidate.isoformat(timespec="seconds"),
                    "next_reminder_time": slot,
                    "next_reminder_text": f"下次提醒 {format_md_weekday(candidate)} {slot}",
                    "next_reminder_label": f"今天 {slot}",
                }
    # Already checked today, or all of today's slots passed → tomorrow first
    hour, minute = _parse_hm(times[0])
    tomorrow = (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return {
        "next_reminder_at": tomorrow.isoformat(timespec="seconds"),
        "next_reminder_time": times[0],
        "next_reminder_text": f"下次提醒 {format_md_weekday(tomorrow)} {times[0]}",
        "next_reminder_label": f"明天 {times[0]}",
    }


def build_checkin_success_text(status, *, now=None, config=None):
    """報平安成功回覆：星期、報到時間、祝福語、下次提醒。"""
    now = now or current_app_time(config)
    duplicate = bool(status.get("already_checked_today") or status.get("is_duplicate"))
    header = "✅ 今天已經報過平安了，不用再點一次。" if duplicate else "✅ 報平安成功！"
    check_dt = parse_last_checkin(status.get("last_check_in")) or now
    if getattr(check_dt, "tzinfo", None) is not None:
        try:
            check_dt = check_dt.astimezone(ZoneInfo("Asia/Taipei")).replace(tzinfo=None)
        except Exception:
            check_dt = check_dt.replace(tzinfo=None)
    blessing = checkin_blessing_text(now)
    lines = [
        header,
        f"📅 今天是 {format_md_weekday(now)}｜報到時間 {format_hm(check_dt)}",
        f"💌 {blessing}",
    ]
    next_text = str(status.get("next_reminder_text") or "").strip()
    if next_text:
        lines.append(f"⏰ {next_text}" if next_text.startswith("下次提醒") else f"⏰ 下次提醒 {next_text}")
    return "\n".join(lines)


def membership_expiry_info(profile, now=None):
    """試用／付費到期資訊；無需提醒時回 None。"""
    if not isinstance(profile, dict):
        return None
    now = now or current_app_time({})
    plan = str(profile.get("plan") or "trial")
    if str(profile.get("membership_source") or "") == "beta":
        beta_end = parse_datetime(profile.get("beta_ends_at"))
        if not beta_end:
            return None
        days = (beta_end.date() - now.date()).days
        return {
            "plan": plan,
            "label": "21 天封測",
            "days_left": days,
            "expired": days <= 0,
            "near": days <= EXPIRY_REMIND_WITHIN_DAYS,
        }
    if plan == "trial":
        started = parse_datetime(profile.get("trial_started_at"))
        total = trial_total_days(profile)
        if started:
            try:
                days = max(0, total - (now - started).days)
            except Exception:
                days = trial_days_left(profile)
        else:
            days = total
        return {
            "plan": plan,
            "label": "14 天安心體驗",
            "days_left": days,
            "expired": days <= 0,
            "near": days <= EXPIRY_REMIND_WITHIN_DAYS,
        }
    if plan.startswith("paid_"):
        paid_until = parse_datetime(str(profile.get("paid_until") or "").strip())
        if not paid_until:
            return None
        days = (paid_until.date() - now.date()).days
        return {
            "plan": plan,
            "label": plan_type_label(profile),
            "days_left": days,
            "expired": days < 0,
            "near": days <= EXPIRY_REMIND_WITHIN_DAYS,
        }
    if plan == "free":
        # 僅對「曾到期降級」或曾開過試用的會員催促，避免全新 free 被洗版
        if not (
            str(profile.get("plan_expired_at") or "").strip()
            or str(profile.get("trial_started_at") or "").strip()
        ):
            return None
        return {
            "plan": plan,
            "label": "未訂閱",
            "days_left": 0,
            "expired": True,
            "near": True,
        }
    return None


def should_offer_expiry_remind(profile, now=None):
    """是否應推方案到期提醒（opt-out／當日已推過則否）。"""
    if bool(profile.get("expiry_remind_opt_out")):
        return False
    now = now or current_app_time({})
    today = now.strftime("%Y-%m-%d")
    if str(profile.get("expiry_remind_sent_date") or "").strip() == today:
        return False
    info = membership_expiry_info(profile, now)
    if not info:
        return False
    return bool(info.get("expired") or info.get("near"))


def build_expiry_remind_flex(profile, now=None):
    """到期／即將到期 Flex：繼續每日問候 → 方案頁；不再提醒我 → opt-out postback。"""
    now = now or current_app_time({})
    info = membership_expiry_info(profile, now) or {}
    label = info.get("label") or "方案"
    days = info.get("days_left")
    if info.get("expired") or (isinstance(days, int) and days <= 0):
        title = f"你的{label}已到期"
        body = (
            "續用後可繼續每日問候與守護提醒，家人也能安心。"
            "升級時補差額即可，不必重設聯絡人；對方也有 7 天考慮期可慢慢決定。"
        )
    else:
        title = f"你的{label}即將到期"
        body = (
            f"還剩約 {days} 天。續用後可繼續每日問候，守護不中斷。"
            "升級補差額即可；另有 7 天考慮期，方便家人一起決定。"
        )
    pricing_uri = pricing_direct_url()
    return {
        "type": "flex",
        "altText": title,
        "contents": {
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#0F766E",
                "paddingAll": "lg",
                "contents": [
                    {
                        "type": "text",
                        "text": "方案提醒",
                        "color": "#FFFFFF",
                        "size": "sm",
                        "wrap": True,
                    },
                    {
                        "type": "text",
                        "text": title,
                        "color": "#FFFFFF",
                        "size": "lg",
                        "weight": "bold",
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
                        "text": body,
                        "size": "md",
                        "color": "#334155",
                        "wrap": True,
                    }
                ],
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "paddingAll": "lg",
                "contents": [
                    {
                        "type": "button",
                        "action": {
                            "type": "uri",
                            "label": "升級後繼續每日問候",
                            "uri": pricing_uri,
                        },
                        "style": "primary",
                        "color": "#0F766E",
                        "height": "md",
                    },
                    {
                        "type": "button",
                        "action": {
                            "type": "postback",
                            "label": "不再提醒我",
                            "data": "action=expiry_opt_out",
                            "displayText": "不再提醒我方案到期",
                        },
                        "style": "secondary",
                        "height": "md",
                    },
                ],
            },
        },
    }


def mark_expiry_remind_sent(profile, now=None):
    now = now or current_app_time({})
    profile["expiry_remind_sent_date"] = now.strftime("%Y-%m-%d")


def handle_expiry_opt_out_postback(data_file, line_user_id):
    if not line_user_id:
        return "請先加入每日平安好友。"
    state = load_state(data_file)
    profile = get_profile(state, line_user_id)
    profile["expiry_remind_opt_out"] = True
    save_state(data_file, state)
    return "好的，之後不會再提醒方案到期。若要續用，隨時點「查看方案」即可。"


def maybe_attach_expiry_remind(messages, profile, *, now=None, state=None, data_file=None):
    """若符合條件，附加到期 Flex 並標記今日已推（寫入 profile；呼叫端負責 save）。"""
    now = now or current_app_time({})
    if not should_offer_expiry_remind(profile, now):
        return messages
    messages = list(messages or [])
    messages.append(build_expiry_remind_flex(profile, now))
    mark_expiry_remind_sent(profile, now)
    if state is not None and data_file:
        save_state(data_file, state)
    return messages


def normalize_line_reply_items(reply):
    """把 postback／關鍵字回覆正規成 list（text str 或 flex dict）。"""
    if reply is None:
        return []
    if isinstance(reply, list):
        return [item for item in reply if item is not None]
    return [reply]


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


# Fields that must survive re-login / upsert and must never be replaced by defaults.
_PROFILE_PERSIST_KEYS = (
    "membership_source",
    "free_eligibility_source",
    "free_eligibility_used_at",
    "trial_started_at",
    "trial_end",
    "trial_policy_version",
    "trial_notice_days_sent",
    "trial_bonus_days",
    "plan_expired_at",
    "contacts_retain_until",
    "contacts_archived",
    "contacts",
    "history",
    "last_check_in",
    "friends",
    "guardian_group_ids",
    "guarding_for",
    "guarding_details",
    "invited_by",
    "plan",
    "payment_status",
    "paid_until",
    "is_onboarding_completed",
    "interaction_state",
    "calendar_notes",
    "smart_reminders",
    "smart_reminder_sent_keys",
    "smart_reminder_defaults",
)


class AccountMigratedError(Exception):
    """Raised when a disabled Provider identity attempts profile access."""


def account_migrated_response():
    return {
        "ok": False,
        "error": "account_migrated",
        "action": "open_current_liff",
    }


def migrated_account_webhook_guidance(
    registration_result,
    liff_id=DEFAULT_LIFF_ID,
):
    """Return safe LINE guidance when an old Provider identity is disabled."""
    data, status = registration_result or ({}, 0)
    if (
        status == 409
        and isinstance(data, dict)
        and data.get("error") == "account_migrated"
    ):
        return (
            "此帳號已移轉到新版 LINE 登入，舊入口已停用。\n"
            "請由新版入口繼續使用：\n"
            f"https://liff.line.me/{str(liff_id or DEFAULT_LIFF_ID).strip()}"
        )
    return ""


def get_profile(state, line_user_id=None, *, start_public_trial=True):
    """Load or create per-user profile keyed by line_user_id.

    Existing records are merged (setdefault only). ``trial_started_at`` is set
    once on first create and never restarted on later visits.
    """
    if line_user_id:
        alias = (state.get("account_migration_aliases") or {}).get(line_user_id)
        if isinstance(alias, dict) and alias.get("status") == "disabled":
            raise AccountMigratedError("account_migrated")
        users = state.setdefault("users", {})
        is_new = line_user_id not in users
        user = users.setdefault(
            line_user_id,
            {**DEFAULT_PROFILE, "line_user_id": line_user_id, "display_name": "LINE 使用者"},
        )
        for key, value in DEFAULT_PROFILE.items():
            # Never clobber persisted collections / trial clock with empty defaults.
            if key in _PROFILE_PERSIST_KEYS and key in user:
                continue
            user.setdefault(key, value)
        if start_public_trial and (is_new or not user.get("trial_started_at")):
            # First sight of this user: start trial clock once.
            if not user.get("trial_started_at"):
                user["trial_started_at"] = datetime.now().isoformat(timespec="seconds")
        if is_new and start_public_trial:
            ensure_membership_trial(user, source="public_trial")
        user["line_user_id"] = line_user_id
        return user
    return state


def get_calendar_notes(data_file, line_user_id=None):
    line_user_id = (line_user_id or "").strip()
    if not line_user_id:
        return {"ok": False, "error": "missing line_user_id", "notes": {}}
    state = load_state(data_file)
    profile = get_profile(state, line_user_id)
    if not plan_has_smart_reminders(profile):
        return {
            "ok": False,
            "error": "calendar_notes_require_799",
            "required_plan": "paid_799",
            "notes": {},
        }
    notes = profile.get("calendar_notes")
    if not isinstance(notes, dict):
        notes = {}
    return {"ok": True, "notes": public_calendar_notes(notes)}


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
    if not plan_has_smart_reminders(profile):
        return {
            "ok": False,
            "error": "calendar_notes_require_799",
            "required_plan": "paid_799",
        }, 403
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
    return {"ok": True, "notes": public_calendar_notes(notes)}, 200


def calendar_note_entries(note):
    return note if isinstance(note, list) else [note]


def calendar_note_content(note):
    if isinstance(note, list):
        contents = [
            calendar_note_content(item)
            for item in note
        ]
        return "\n".join(content for content in contents if content)
    if isinstance(note, dict):
        return str(note.get("content") or "").strip()
    return str(note or "").strip()


def calendar_note_birthdays(note):
    birthdays = []
    for entry in calendar_note_entries(note):
        if not isinstance(entry, dict):
            continue
        birthday_name = str(entry.get("birthday_name") or "").strip()
        if not birthday_name:
            continue
        birthdays.append(
            {
                "birthday_name": birthday_name,
                "birthday_relationship": str(
                    entry.get("birthday_relationship") or ""
                ).strip(),
                "birthday_date": str(entry.get("birthday_date") or "").strip(),
                "birthday_yearly": bool(entry.get("birthday_yearly", True)),
                "birthday_remind_days": int(entry.get("birthday_remind_days") or 1),
            }
        )
    return birthdays


def calendar_note_birthday(note):
    birthdays = calendar_note_birthdays(note)
    return birthdays[0] if birthdays else None


def public_calendar_note(note):
    if not isinstance(note, list):
        if not isinstance(note, dict):
            return copy.deepcopy(note)
        return {
            key: copy.deepcopy(value)
            for key, value in note.items()
            if key not in {"id", "migration_event_id"}
            and not str(key).startswith("_migration")
        }
    public_note = {"content": calendar_note_content(note)}
    birthdays = calendar_note_birthdays(note)
    if birthdays:
        public_note.update(birthdays[0])
        public_note["birthdays"] = birthdays
    return public_note


def public_calendar_notes(notes):
    return {
        note_date: public_calendar_note(note)
        for note_date, note in (notes or {}).items()
    }


def birthday_occurs_on(birthday, target_date):
    try:
        source = datetime.strptime(birthday.get("birthday_date", ""), "%Y-%m-%d").date()
    except ValueError:
        return False
    if birthday.get("birthday_yearly", True):
        return source.month == target_date.month and source.day == target_date.day
    return source == target_date


def plan_rules(profile, now=None):
    return plan_rules_for_effective_entitlement(profile, now)


def allowed_safety_guard_hours(profile):
    """依方案回傳可選安全守護時數（小時）；0.25 代表 15 分鐘。"""
    raw = plan_rules(profile).get("safety_guard_hours", [1])
    hours = []
    for item in raw:
        try:
            value = float(item)
        except (TypeError, ValueError):
            continue
        if value.is_integer():
            value = int(value)
        if value > 0 and value not in hours:
            hours.append(value)
    return hours


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
        return normalize_reminder_times([single], max_count) or default_reminder_times_for_count(min(max_count, 2))
    return default_reminder_times_for_count(min(max_count, 2))


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
        normalized = default_reminder_times_for_count(min(max_count, 2))
    profile["reminder_times"] = normalized
    profile["reminder_time"] = normalized[0]
    return normalized


def ensure_active_overdue_event(profile, reminder_time, now):
    """Start one missed-check-in workflow; later reminder slots never duplicate it."""
    today = now.strftime("%Y-%m-%d")
    current = profile.get("active_overdue_event")
    if (
        isinstance(current, dict)
        and current.get("date") == today
        and not current.get("resolved_at")
    ):
        return current
    event = {
        "event_id": f"overdue-{profile.get('line_user_id') or 'member'}-{today}",
        "date": today,
        "reminder_time": str(reminder_time or ""),
        "started_at": now.isoformat(timespec="seconds"),
        "self_followup_sent_at": "",
        "guardian_stage": 0,
        "notified_guardian_ids": [],
        "resolved_at": "",
    }
    profile["active_overdue_event"] = event
    return event


def ranked_overdue_guardians(profile):
    """Return up to the plan limit in notification priority order."""
    owner_id = str(profile.get("line_user_id") or "")
    limit = max(1, int(plan_rules(profile).get("core_guardian_alert_limit") or 1))
    contacts = sorted(
        profile.get("contacts") or [],
        key=lambda item: (
            0 if bool((item or {}).get("is_primary")) else 1,
            int((item or {}).get("priority") or 9999),
        ),
    )
    rows = []
    seen = set()
    for contact in contacts:
        if not contact_is_notifiable_line_guardian(contact, owner_id):
            continue
        target = get_contact_line_id(contact)
        if not target or target in seen:
            continue
        seen.add(target)
        rows.append(contact)
        if len(rows) >= limit:
            break
    return rows


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


def contact_is_bound_guardian(contact, owner_line_user_id=None):
    """對方是否已透過 LINE 邀請（invite_from）綁定／同意成為守護人。

    表單新增聯絡人時 payload 常帶本人 line_user_id（僅供 API 認證），
    不可把「本人 ID 誤寫進聯絡人」當成已綁定守護人。
    """
    if not isinstance(contact, dict):
        return False
    lid = get_contact_line_id(contact)
    owner = str(owner_line_user_id or "").strip()
    if lid and owner and lid == owner:
        return False
    if contact.get("binding_status") == "accepted" or contact.get("consent_status") == "accepted":
        return bool(lid) and (not owner or lid != owner)
    return False


def contact_is_notifiable_line_guardian(contact, owner_line_user_id=None):
    """可收安全守護／SOS 等 LINE 推播的「守護人」。

    排除：緊急聯絡人（僅電話備援）、本人 ID、未綁定、未勾選 line 通知。
    """
    if not isinstance(contact, dict):
        return False
    if resolve_contact_role(contact) == "emergency":
        return False
    if not contact_is_bound_guardian(contact, owner_line_user_id):
        return False
    methods = contact.get("notify_methods")
    if methods is not None and len(methods) == 0:
        methods = ["line"]
    if "line" not in (methods or ["line"]):
        return False
    lid = get_contact_line_id(contact)
    owner = str(owner_line_user_id or "").strip()
    if not lid or (owner and lid == owner):
        return False
    return True


def contact_has_guardian_profile(contact):
    """是否已填寫守護人基本資料（姓名＋關係）。"""
    if not isinstance(contact, dict):
        return False
    return bool((contact.get("name") or "").strip() and (contact.get("relationship") or "").strip())


def scrub_self_line_ids_on_contacts(profile):
    """清除誤把本人 line_user_id 寫進聯絡人的假綁定（表單 add 污染）。回傳是否有變更。"""
    if not isinstance(profile, dict):
        return False
    owner = str(profile.get("line_user_id") or "").strip()
    if not owner:
        return False
    changed = False
    for contact in profile.get("contacts") or []:
        if not isinstance(contact, dict):
            continue
        lid = get_contact_line_id(contact)
        if not lid or lid != owner:
            continue
        # 本人 ID 不應出現在守護人 LINE 欄；真正綁定只走 bind_emergency_contact
        if contact.get("line_user_id"):
            contact["line_user_id"] = ""
            changed = True
        if contact.get("line_id"):
            contact["line_id"] = ""
            changed = True
        if contact.get("binding_status") in ("accepted", "pending"):
            contact["binding_status"] = "unbound"
            changed = True
        if contact.get("consent_status") == "accepted":
            contact["consent_status"] = "pending"
            changed = True
    return changed


def deduplicate_contact_line_bindings(profile):
    """同一個 LINE 帳號在單一會員名下只能保留一筆聯絡關係。"""
    if not isinstance(profile, dict):
        return False
    contacts = list(profile.get("contacts") or [])
    unique = []
    by_line_id = {}
    changed = False
    for contact in contacts:
        if not isinstance(contact, dict):
            unique.append(contact)
            continue
        line_id = get_contact_line_id(contact)
        if not line_id:
            unique.append(contact)
            continue
        existing = by_line_id.get(line_id)
        if existing is None:
            by_line_id[line_id] = contact
            unique.append(contact)
            continue
        changed = True
        for key, value in contact.items():
            if key not in existing or existing.get(key) in (None, "", [], {}):
                existing[key] = copy.deepcopy(value)
        if contact.get("binding_status") == "accepted":
            existing["binding_status"] = "accepted"
        if contact.get("consent_status") == "accepted":
            existing["consent_status"] = "accepted"
        if bool(contact.get("is_primary")):
            existing["is_primary"] = True
        if resolve_contact_role(contact) == "guardian":
            existing["contact_role"] = "guardian"
    if changed:
        profile["contacts"] = unique
    return changed


def profile_has_guardian(profile):
    """使用者是否已有至少 1 位守護人（資料或 LINE 綁定）。"""
    contacts = (profile or {}).get("contacts") or []
    owner = str((profile or {}).get("line_user_id") or "").strip()
    return any(
        contact_has_guardian_profile(c) or contact_is_bound_guardian(c, owner)
        for c in contacts
    )


def profile_has_bound_line_guardian(profile):
    """是否已有 ≥1 位可 LINE 通知的守護人（安全守護／SOS 閘門；不含緊急聯絡人）。"""
    contacts = (profile or {}).get("contacts") or []
    owner = str((profile or {}).get("line_user_id") or "").strip()
    return any(contact_is_notifiable_line_guardian(c, owner) for c in contacts)


def pending_guardian_invite_count(state, inviter_line_user_id, now=None):
    """分享邀請只算等待中；受邀人填資料並同意後才算完成綁定。"""
    inviter_id = str(inviter_line_user_id or "").strip()
    if not inviter_id:
        return 0
    current = now or current_app_time({})
    count = 0
    for row in (state or {}).get("guardian_invites") or []:
        if (
            not isinstance(row, dict)
            or row.get("inviter_line_user_id") != inviter_id
            or row.get("status") != "pending"
        ):
            continue
        expires_at = parse_datetime(row.get("expires_at"))
        if expires_at:
            comparable_now, comparable_expiry = _comparable_datetimes(
                current, expires_at
            )
            if comparable_expiry <= comparable_now:
                continue
        count += 1
    return count


def contact_is_reciprocal_core_guardian(state, owner_id, contact):
    """Require a live, bilateral core-guardian relationship."""
    if (
        resolve_contact_role(contact) != "guardian"
        or not bool(contact.get("is_primary"))
        or not contact_is_bound_guardian(contact, owner_id)
    ):
        return False
    peer_id = get_contact_line_id(contact)
    peer = ((state or {}).get("users") or {}).get(peer_id) or {}
    return any(
        get_contact_line_id(peer_contact) == owner_id
        and resolve_contact_role(peer_contact) == "guardian"
        and bool(peer_contact.get("is_primary"))
        and contact_is_bound_guardian(peer_contact, peer_id)
        for peer_contact in (peer.get("contacts") or [])
    )


def member_access_state(profile):
    """Return only server-authoritative readiness for a member session.

    Historical onboarding flags and ordinary contact records describe prior UI
    progress; they do not prove that a LINE-reachable core guardian is bound.
    Optional blockers are emitted only when this persisted profile explicitly
    records them, never inferred from browser state.
    """
    profile = profile if isinstance(profile, dict) else {}
    home_ready = profile_has_bound_line_guardian(profile)
    state = {
        "guardian_required": not home_ready,
        "home_ready": home_ready,
    }
    for key in ("friend_required", "login_required", "migration_pending"):
        if profile.get(key) is True:
            state[key] = True
    return state


def onboarding_status_payload(data_file, line_user_id, *, allow_missing_profile=False):
    """Build the onboarding API payload from the same authoritative gate."""
    line_user_id = str(line_user_id or "").strip()
    if not line_user_id:
        return {"ok": False, "error": "missing line_user_id"}, 400
    state = load_state(data_file)
    profile = state.get("users", {}).get(line_user_id)
    if not profile and not allow_missing_profile:
        return {"ok": False, "error": "user not registered"}, 404
    profile = profile or {}
    if profile and ensure_onboarding_completed_flag(profile):
        save_state(data_file, state)
    access = member_access_state(profile)
    contacts = profile.get("contacts") or []
    has_guardian = profile_has_guardian(profile)
    times = (
        reminder_times_for_profile(profile)
        if profile
        else default_reminder_times_for_count(1)
    )
    daily_reminders = int(plan_rules(profile).get("daily_reminders") or 1) if profile else 1
    return {
        "ok": True,
        **access,
        "line_user_id": line_user_id,
        "is_onboarding_completed": access["home_ready"],
        "setup_completed": access["home_ready"],
        "has_guardian": has_guardian,
        "guardian_count": len(contacts),
        "pending_guardian_invite_count": pending_guardian_invite_count(
            state, line_user_id
        ),
        "onboarding_reminder_configured": bool(
            profile.get("onboarding_reminder_configured")
        ),
        "reminder_time": times[0] if times else "12:00",
        "reminder_times": times,
        "daily_reminders": daily_reminders,
        "daily_checkin_reminder_enabled": bool(
            profile.get("daily_checkin_reminder_enabled", True)
        ),
        # 首次綁定不強迫 799 填滿 3 次；399／799 未選時皆預設 12:00、18:00。
        "default_reminder_times": default_reminder_times_for_count(min(daily_reminders, 2)),
        "grace_hours": normalize_grace_hours(profile.get("grace_hours")),
        "overdue_wait_minutes": normalize_overdue_wait_minutes(
            profile.get("overdue_wait_minutes")
        ),
        "warning_cancel_minutes": int(
            profile.get("warning_cancel_minutes") or DEFAULT_WARNING_CANCEL_MINUTES
        ),
        "allowed_grace_hours": list(ALLOWED_GRACE_HOURS),
        "plan": profile.get("plan", "trial"),
        "display_name": profile.get("display_name", ""),
    }, 200


def profile_setup_completed(profile):
    """Compatibility alias for server-authoritative home readiness."""
    return member_access_state(profile)["home_ready"]


def ensure_onboarding_completed_flag(profile):
    """若已有守護人但旗標未寫入，補上 durable flag（回傳是否有變更）。"""
    if not profile:
        return False
    if profile.get("is_onboarding_completed") and (
        isinstance(profile.get("interaction_state"), dict)
        and profile["interaction_state"].get("onboarding_completed")
    ):
        return False
    if not profile_has_bound_line_guardian(profile) and not profile.get("is_onboarding_completed"):
        return False
    changed = False
    if profile_has_bound_line_guardian(profile) or profile.get("is_onboarding_completed"):
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



def trial_bonus_days(profile):
    """舊版相容欄位；邀請核心守護人不再增加體驗天數。"""
    return 0


def trial_total_days(profile):
    """公開或過渡體驗固定 14 天，不因邀請延長。"""
    return PUBLIC_TRIAL_DAYS


def ensure_membership_trial(profile, now=None, source="public_trial"):
    """給予目前政策的一次性 14 天體驗；同一版本永不重啟。"""
    if not isinstance(profile, dict):
        return False
    if free_eligibility_source(profile):
        return False
    if profile.get("trial_policy_version") == TRIAL_POLICY_VERSION:
        return False
    plan = str(profile.get("plan") or "trial")
    if plan.startswith("paid_"):
        return False
    now = now or current_app_time({})
    profile["membership_source"] = source
    profile["free_eligibility_source"] = source
    profile["free_eligibility_used_at"] = now.isoformat(timespec="seconds")
    profile["trial_started_at"] = now.isoformat(timespec="seconds")
    profile["trial_end"] = (now + timedelta(days=PUBLIC_TRIAL_DAYS)).isoformat(
        timespec="seconds"
    )
    profile["trial_policy_version"] = TRIAL_POLICY_VERSION
    profile["trial_notice_days_sent"] = []
    profile["trial_bonus_days"] = 0
    profile["plan"] = "trial"
    profile["payment_status"] = "trial"
    clear_contacts_retain_window(profile)
    return True


def free_eligibility_source(profile):
    """Return the permanent first free entitlement source, including legacy data."""
    if not isinstance(profile, dict):
        return ""
    recorded = str(profile.get("free_eligibility_source") or "").strip()
    if recorded:
        return recorded
    cohort = str(profile.get("beta_cohort") or "").strip().upper()
    if cohort and (
        profile.get("beta_started_at")
        or str(profile.get("membership_source") or "") == "beta"
    ):
        return f"beta_{cohort}"
    return ""


def migrate_existing_free_members(config):
    """Cron 可重跑遷移：同一時間批次給 legacy free 一次過渡體驗。"""
    data_file = config["DATA_FILE"]
    state = load_state(data_file)
    now = current_app_time(config)
    migrated = []
    paid_sources_normalized = 0
    changed = False
    for profile in (state.get("users") or {}).values():
        plan = str(profile.get("plan") or "")
        source = str(profile.get("membership_source") or "")
        if plan.startswith("paid_"):
            if source != "beta":
                normalized = False
                if source != "paid":
                    profile["membership_source"] = "paid"
                    normalized = True
                if profile.get("trial_policy_version") != TRIAL_POLICY_VERSION:
                    # 既有付費會員不可在未來到期後被誤判為 legacy free 再領一次。
                    profile["trial_policy_version"] = TRIAL_POLICY_VERSION
                    profile["trial_bonus_days"] = 0
                    normalized = True
                if normalized:
                    paid_sources_normalized += 1
                    changed = True
            continue
        if plan != "free":
            continue
        if source == "expired" and profile.get("plan_expired_at"):
            # 到期會員不是 legacy free；Cron 重跑不得再次發放體驗。
            continue
        if ensure_membership_trial(profile, now=now, source="transition_trial"):
            migrated.append(str(profile.get("line_user_id") or ""))
            changed = True
    if changed:
        save_state(data_file, state)
    return {
        "migrated": len(migrated),
        "line_user_ids": migrated,
        "paid_sources_normalized": paid_sources_normalized,
        "migration_time": now.isoformat(timespec="seconds"),
    }, 200


def _comparable_datetimes(left, right):
    if left.tzinfo is None and right.tzinfo is not None:
        right = right.astimezone(ZoneInfo("Asia/Taipei")).replace(tzinfo=None)
    elif left.tzinfo is not None and right.tzinfo is None:
        left = left.astimezone(ZoneInfo("Asia/Taipei")).replace(tzinfo=None)
    return left, right


def membership_access_active(profile, now=None):
    """會員權益是否有效；free 僅代表未訂閱，SOS 安全政策另行判斷。"""
    if not isinstance(profile, dict):
        return False
    now = now or current_app_time({})
    if profile.get("membership_source") == "beta":
        if profile.get("beta_revoked_at"):
            return False
        started = parse_datetime(profile.get("beta_started_at"))
        ends = parse_datetime(profile.get("beta_ends_at"))
        if not started or not ends:
            return False
        comparable_now, comparable_start = _comparable_datetimes(now, started)
        comparable_now, comparable_end = _comparable_datetimes(comparable_now, ends)
        return comparable_start <= comparable_now < comparable_end
    plan = str(profile.get("plan") or "free")
    if plan == "trial":
        trial_end = parse_datetime(profile.get("trial_end"))
        if trial_end:
            comparable_now, comparable_end = _comparable_datetimes(now, trial_end)
            return comparable_now < comparable_end
        started_at = parse_datetime(profile.get("trial_started_at"))
        return bool(started_at and now < started_at + timedelta(days=PUBLIC_TRIAL_DAYS))
    if plan.startswith("paid_"):
        paid_until = parse_datetime(profile.get("paid_until"))
        return paid_until is None or now < paid_until
    return False


def beta_access_active(profile, now=None):
    """Return whether a closed-beta entitlement is currently usable."""
    if not isinstance(profile, dict) or profile.get("membership_source") != "beta":
        return False
    if profile.get("beta_revoked_at"):
        return False
    now = now or current_app_time({})
    started = parse_datetime(profile.get("beta_started_at"))
    ends = parse_datetime(profile.get("beta_ends_at"))
    if not started or not ends:
        return False
    comparable_now, comparable_start = _comparable_datetimes(now, started)
    comparable_now, comparable_end = _comparable_datetimes(comparable_now, ends)
    return comparable_start <= comparable_now < comparable_end


def effective_entitlement_plan(profile, now=None):
    """Active public/transition trials receive the paid 199 monthly rights."""
    now = now or current_app_time({})
    if str(profile.get("plan") or "") == "trial" and membership_access_active(profile, now):
        return "paid_199"
    if beta_access_active(profile, now):
        return BETA_COHORT_PLAN.get(str(profile.get("beta_cohort") or ""), "paid_399")
    if str(profile.get("membership_source") or "") == "beta":
        return "free"
    return str(profile.get("plan") or "free")


def plan_rules_for_effective_entitlement(profile, now=None):
    rules = copy.deepcopy(
        PLAN_LIMITS.get(effective_entitlement_plan(profile, now), PLAN_LIMITS["free"])
    )
    if str(profile.get("plan") or "") == "trial":
        # The 199-equivalent trial never unlocks guardian groups.
        rules["guardian_group_limit"] = 0
        # Keep the same 15-minute Safety Guard rights and quota as paid 199.
        rules["safety_guard_hours"] = (
            [0.25] if membership_access_active(profile, now) else []
        )
        rules["safety_guard_daily_limit"] = (
            2 if membership_access_active(profile, now) else 0
        )
    return rules


def claim_trial_group_test(profile, group_id, now=None):
    now = now or current_app_time({})
    if effective_entitlement_plan(profile, now) != "paid_399":
        return {"claimed": False, "reason": "not_eligible"}
    if profile.get("trial_group_test_used_at"):
        delivery = dict(profile.get("trial_group_test_delivery") or {})
        if (
            delivery.get("group_id") == str(group_id or "").strip()
            and delivery.get("status") in {"pending", "failed"}
        ):
            return {
                "claimed": True,
                "recovered": True,
                "message": "這是測試通知：守護群綁定與推播流程已完成",
                "retry_key": delivery.get("retry_key"),
            }
        return {"claimed": False, "reason": "already_used"}
    retry_key = _line_retry_key(
        f"trial-group-test:{profile.get('line_user_id')}:{str(group_id or '').strip()}"
    )
    profile["trial_group_test_used_at"] = now.isoformat(timespec="seconds")
    profile["trial_group_test_group_id"] = str(group_id or "").strip()
    profile["trial_group_test_delivery"] = {
        "group_id": str(group_id or "").strip(),
        "status": "pending",
        "retry_key": retry_key,
        "claimed_at": now.isoformat(timespec="seconds"),
    }
    return {
        "claimed": True,
        "message": "這是測試通知：守護群綁定與推播流程已完成",
        "retry_key": retry_key,
    }


def consume_labeled_test_action(profile, action, now=None):
    """Limit explicit test actions without changing real SOS emergency access."""
    action = str(action or "").strip().lower()
    if action not in {"sos", "location", "push"}:
        return {"allowed": False, "reason": "invalid_action"}
    now = now or current_app_time({})
    today = now.strftime("%Y-%m-%d")
    ledger = profile.setdefault("labeled_test_actions", {})
    rows = [
        row for row in (ledger.get(action) or [])
        if str(row.get("at") or "").startswith(today)
    ]
    if len(rows) >= 2:
        return {"allowed": False, "reason": "daily_limit", "used": len(rows)}
    if rows:
        last = parse_datetime(rows[-1].get("at"))
        if last and (now - last).total_seconds() < 600:
            return {
                "allowed": False,
                "reason": "cooldown",
                "retry_after_seconds": int(600 - (now - last).total_seconds()),
            }
    rows.append({"at": now.isoformat(timespec="seconds")})
    ledger[action] = rows
    return {
        "allowed": True,
        "used": len(rows),
        "remaining": 2 - len(rows),
        "event_id": f"trial-test:{action}:{now.isoformat(timespec='seconds')}",
        "message": f"這是測試通知（{action.upper()}）：未觸發真正緊急求助或持續定位。",
    }


def authorize_labeled_test_action(data_file, line_user_id, action, now=None):
    """Atomically consume a bounded explicit test action for the verified member."""
    clock = now or current_app_time({})

    def mutate(state):
        profile = (state.get("users") or {}).get(str(line_user_id or "").strip())
        if not isinstance(profile, dict):
            raise ValueError("member_not_found")
        if str(profile.get("plan") or "") != "trial" or not membership_access_active(
            profile, clock
        ):
            return {"allowed": False, "reason": "not_eligible"}
        return consume_labeled_test_action(profile, action, now=clock)

    try:
        result = mutate_state_atomically(data_file, mutate)
    except ValueError:
        return {"allowed": False, "reason": "member_not_found"}, 404
    return result, 200 if result.get("allowed") else 429


def assign_beta_cohort(
    state,
    line_user_id,
    cohort,
    *,
    now=None,
    recruitment_source="",
):
    """Assign one real member to a capped 21-day beta cohort without an order."""
    cohort = str(cohort or "").strip().upper()
    if cohort not in BETA_COHORT_LIMITS:
        raise ValueError("invalid_cohort")
    users = state.setdefault("users", {})
    profile = users.get(str(line_us…160567 tokens truncated…須至少有 1 位守護人)。"""
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        result, code = complete_onboarding_for_user(
            app.config["DATA_FILE"], line_user_id, payload
        )
        return jsonify(result), code

    @app.get("/api/emergency-contact/invite-preview")
    def emergency_contact_invite_preview_api():
        line_user_id, err = _authenticated_line_user({}, use_args=True)
        if err:
            return jsonify(err[0]), err[1]
        payload = {
            "invite_from": request.args.get("invite_from") or request.args.get("from") or "",
            "invite_token": request.args.get("invite_token") or "",
            "line_user_id": line_user_id,
        }
        data, code = invite_bind_preview(app.config["DATA_FILE"], payload)
        return jsonify(data), code

    @app.post("/api/emergency-contact/invite")
    def emergency_contact_invite_create_api():
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        data, code = create_guardian_invite(
            app.config["DATA_FILE"], line_user_id, payload
        )
        return jsonify(data), code

    @app.post("/api/emergency-contact/bind")
    def emergency_contact_bind_api():
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        payload["contact_line_user_id"] = line_user_id
        data, code = bind_emergency_contact(app.config["DATA_FILE"], payload, app.config)
        return jsonify(data), code

    @app.post("/api/guardian-groups/bind")
    def guardian_groups_bind_api():
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        payload["line_user_id"] = line_user_id
        data, code = bind_guardian_group(app.config["DATA_FILE"], payload)
        if code == 200 and data.get("trial_test_message"):
            token = app.config.get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get(
                "LINE_CHANNEL_ACCESS_TOKEN", ""
            )
            if not token:
                return jsonify({
                    **data,
                    "trial_test_delivery": "failed",
                    "error": "LINE_CHANNEL_ACCESS_TOKEN is not set",
                }), 503
            sender = app.config.get("LINE_PUSH_SENDER") or line_push_message
            retry_key = data.get("trial_test_retry_key") or _line_retry_key(
                f"trial-group-test:{line_user_id}:{payload.get('group_id')}"
            )
            try:
                _send_line_with_retry_key(
                    sender,
                    token,
                    payload.get("group_id"),
                    data["trial_test_message"],
                    retry_key,
                )
                data["trial_test_delivery"] = "sent"
                mutate_state_atomically(
                    app.config["DATA_FILE"],
                    lambda state: (
                        (state.get("users") or {}).get(line_user_id, {}).setdefault(
                            "trial_group_test_delivery", {}
                        ).update({
                            "status": "sent",
                            "sent_at": current_app_time(app.config).isoformat(
                                timespec="seconds"
                            ),
                        }),
                        record_line_message_usage(
                            state,
                            category="trial_group_test",
                            owner_line_user_id=line_user_id,
                            recipient_count=1,
                            event_id=retry_key,
                        ),
                    )[-1],
                )
            except Exception as exc:
                data["trial_test_delivery"] = "failed"
                data["error"] = "測試通知暫時無法送出，請稍後再試。"
                mutate_state_atomically(
                    app.config["DATA_FILE"],
                    lambda state: (state.get("users") or {}).get(
                        line_user_id, {}
                    ).setdefault("trial_group_test_delivery", {}).update({
                        "status": "failed",
                        "last_error": str(exc)[:200],
                    }),
                )
                app.logger.warning("trial group test delivery failed: %s", exc)
                return jsonify(data), 502
        return jsonify(data), code

    @app.post("/api/guardian-groups/unbind")
    def guardian_groups_unbind_api():
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        payload["line_user_id"] = line_user_id
        data, code = unbind_guardian_group(app.config["DATA_FILE"], payload)
        return jsonify(data), code

    @app.post("/api/guardian-groups/preferences")
    def guardian_groups_preferences_api():
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        payload["line_user_id"] = line_user_id
        data, code = update_guardian_group_preferences(
            app.config["DATA_FILE"], payload
        )
        return jsonify(data), code

    @app.get("/api/guardian-groups/settings")
    def guardian_groups_settings_api():
        line_user_id, err = _authenticated_line_user({}, use_args=True)
        if err:
            return jsonify(err[0]), err[1]
        data, code = guardian_group_settings_for_user(
            app.config["DATA_FILE"], line_user_id
        )
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
        data, code = update_location(
            app.config["DATA_FILE"],
            request.get_json(silent=True) or {},
            app.config,
        )
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

    @app.post("/api/trial/test-action")
    def trial_test_action_api():
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        data, code = authorize_labeled_test_action(
            app.config["DATA_FILE"],
            line_user_id,
            payload.get("action"),
        )
        if code == 200 and data.get("allowed"):
            token = app.config.get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get(
                "LINE_CHANNEL_ACCESS_TOKEN", ""
            )
            if not token:
                return jsonify({
                    **data,
                    "allowed": False,
                    "reason": "push_unavailable",
                }), 503
            sender = app.config.get("LINE_PUSH_SENDER") or line_push_message
            retry_key = _line_retry_key(data["event_id"])
            try:
                _send_line_with_retry_key(
                    sender, token, line_user_id, data["message"], retry_key
                )
                mutate_state_atomically(
                    app.config["DATA_FILE"],
                    lambda state: record_line_message_usage(
                        state,
                        category=f"trial_{payload.get('action')}_test",
                        owner_line_user_id=line_user_id,
                        recipient_count=1,
                        event_id=data["event_id"],
                    ),
                )
                data["delivery"] = "sent"
            except Exception as exc:
                app.logger.warning("trial test delivery failed: %s", exc)
                data["delivery"] = "failed"
                data["reason"] = "push_failed"
                return jsonify(data), 502
        return jsonify(data), code

    @app.post("/api/sos/cancel")
    def sos_cancel_api():
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        payload["line_user_id"] = line_user_id
        data, code = cancel_sos_event(app.config["DATA_FILE"], payload, app.config)
        return jsonify(data), code

    @app.post("/api/sos/retry")
    def sos_retry_api():
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        payload["line_user_id"] = line_user_id
        data, code = retry_sos_event(app.config["DATA_FILE"], payload, app.config)
        return jsonify(data), code

    @app.get("/api/sos/status")
    def sos_status_api():
        payload = {"line_user_id": request.args.get("line_user_id", "")}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        data, code = get_sos_event_status(
            app.config["DATA_FILE"],
            line_user_id,
            request.args.get("event_id", ""),
        )
        return jsonify(data), code

    @app.post("/api/sos/respond")
    def sos_respond_api():
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        payload["line_user_id"] = line_user_id
        data, code = respond_to_sos_event(
            app.config["DATA_FILE"], payload, app.config
        )
        return jsonify(data), code

    @app.post("/api/sos/safe")
    def sos_safe_api():
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        payload["line_user_id"] = line_user_id
        data, code = close_sos_as_safe(
            app.config["DATA_FILE"], payload, app.config
        )
        return jsonify(data), code

    @app.get("/api/bot/guardian-groups")
    def bot_guardian_groups_api():
        """2026-07-21 patch 22: 返回所有守護群清單(供 bot_admin.html)。"""
        denied = _admin_guard()
        if denied:
            return denied

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
        """Return SOS progress, delivery events and graded safety restrictions."""
        denied = _admin_guard()
        if denied:
            return denied

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
        events = []
        for event in (state.get("sos_events") or {}).values():
            owner = str(event.get("owner_line_user_id") or "")
            deliveries = event.get("deliveries") or []
            events.append({
                "event_id": event.get("event_id"),
                "owner_id": owner[:6] + "..." + owner[-4:] if owner else None,
                "owner_display_name": event.get("owner_display_name"),
                "status": event.get("status"),
                "sent_at": event.get("sent_at"),
                "cancelled_at": event.get("cancelled_at"),
                "sent": sum(1 for item in deliveries if item.get("status") == "sent"),
                "failed": sum(1 for item in deliveries if item.get("status") == "failed"),
                "abuse_mode": event.get("abuse_mode") or "normal",
            })
        events.sort(key=lambda item: item.get("sent_at") or "", reverse=True)
        abuse = {"observation": 0, "restricted": 0}
        for profile in (state.get("users") or {}).values():
            mode = sos_abuse_state(profile, current_app_time(app.config)).get("mode")
            if mode in abuse:
                abuse[mode] += 1
        return jsonify({
            "pending": out,
            "total": len(out),
            "events": events[:50],
            "event_total": len(events),
            "abuse": abuse,
        })

    @app.get("/api/bot/recent-events")
    def bot_recent_events_api():
        """2026-07-21 patch 22: 返回最近的 webhook 事件(使用 notification_log)。"""
        denied = _admin_guard()
        if denied:
            return denied

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

    def _migration_verified_subject(payload, channel_key):
        if not account_migration_ready(app.config):
            return None, ({"ok": False, "error": "migration_unavailable"}, 503)
        if extract_id_token is None or verify_line_id_token_for_channel is None:
            return None, ({"ok": False, "error": "migration_unavailable"}, 503)
        token = extract_id_token(
            {key: value for key, value in request.headers.items()},
            payload,
            {},
        )
        subject = verify_line_id_token_for_channel(
            token,
            app.config.get(channel_key),
        )
        if not subject:
            return None, ({"ok": False, "error": "invalid_token"}, 401)
        return subject, None

    @app.after_request
    def _disable_account_migration_response_caching(response):
        if request.path.startswith("/api/account-migration/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/account-migration/start")
    def account_migration_start_api():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "error": "invalid_request"}), 400
        old_line_user_id, err = _migration_verified_subject(
            payload,
            "LEGACY_LINE_LOGIN_CHANNEL_ID",
        )
        if err:
            return jsonify(err[0]), err[1]
        data, code = create_account_migration_ticket(
            app.config["DATA_FILE"],
            old_line_user_id,
            app.config,
        )
        return jsonify(data), code

    @app.get("/api/account-migration/status")
    def account_migration_status_api():
        old_line_user_id, err = _migration_verified_subject(
            {},
            "LEGACY_LINE_LOGIN_CHANNEL_ID",
        )
        if err:
            return jsonify(err[0]), err[1]
        data = account_migration_ticket_status(
            app.config["DATA_FILE"],
            old_line_user_id,
            app.config,
        )
        return jsonify(data)

    @app.post("/api/account-migration/redeem")
    def account_migration_redeem_api():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "error": "invalid_request"}), 400
        new_line_user_id, err = _migration_verified_subject(
            payload,
            "LINE_LOGIN_CHANNEL_ID",
        )
        if err:
            return jsonify(err[0]), err[1]
        data, code = redeem_account_migration_ticket(
            app.config["DATA_FILE"],
            payload.get("migration_code"),
            new_line_user_id,
            app.config,
        )
        return jsonify(data), code

    @app.post("/api/account/privacy-request")
    def account_privacy_request_api():
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        payload["line_user_id"] = line_user_id
        data, code = create_privacy_request(app.config["DATA_FILE"], payload)
        return jsonify(data), code

    @app.get("/api/admin/summary")
    def admin_summary_api():
        denied = _admin_guard()
        if denied:
            return denied
        return jsonify(admin_summary(app.config["DATA_FILE"], app.config))

    @app.get("/api/admin/test-center")
    def admin_test_center_api():
        denied = _admin_guard()
        if denied:
            return denied
        return jsonify(admin_test_center_status(app.config["DATA_FILE"], app.config))

    @app.post("/api/admin/test-center/run")
    def admin_test_center_run_api():
        denied = _admin_guard(write=True)
        if denied:
            return denied
        data, code = run_admin_test(
            app.config["DATA_FILE"],
            app.config,
            request.get_json(silent=True) or {},
        )
        append_admin_audit(
            app.config["DATA_FILE"],
            f"test_center.{data.get('test_id') or 'unknown'}",
            "success" if code < 400 else "failed",
            {"http_status": code, "test_mode": True},
        )
        return jsonify(data), code

    @app.get("/api/admin/account-migrations")
    def admin_account_migrations_api():
        denied = _admin_guard()
        if denied:
            return denied
        return jsonify(
            admin_account_migrations(
                app.config["DATA_FILE"],
                app.config,
            )
        )

    @app.get("/api/admin/beta-members")
    def admin_beta_members_api():
        denied = _admin_guard()
        if denied:
            return denied
        return jsonify(beta_members_snapshot(load_state(app.config["DATA_FILE"])))

    @app.get("/api/admin/line-acceptance")
    def admin_line_acceptance_api():
        denied = _admin_guard()
        if denied:
            return denied
        return jsonify(
            line_acceptance_snapshot(load_state(app.config["DATA_FILE"]))
        )

    @app.post("/api/admin/line-acceptance")
    def admin_line_acceptance_create_api():
        denied = _admin_guard(write=True)
        if denied:
            return denied
        payload = request.get_json(silent=True) or {}
        try:
            result = mutate_state_atomically(
                app.config["DATA_FILE"],
                lambda state: create_line_acceptance_case(state, payload),
            )
        except ValueError as exc:
            return _admin_mutation_response(
                "line_acceptance.create",
                {"ok": False, "error": str(exc)},
                400,
            )
        return _admin_mutation_response(
            "line_acceptance.create",
            {"ok": True, **result},
        )

    @app.patch("/api/admin/line-acceptance/<case_id>")
    def admin_line_acceptance_review_api(case_id):
        denied = _admin_guard(write=True)
        if denied:
            return denied
        payload = request.get_json(silent=True) or {}
        try:
            result = mutate_state_atomically(
                app.config["DATA_FILE"],
                lambda state: review_line_acceptance_case(
                    state, case_id, payload
                ),
            )
        except ValueError as exc:
            error = str(exc)
            return _admin_mutation_response(
                "line_acceptance.review",
                {"ok": False, "error": error},
                404 if error == "acceptance_case_not_found" else 400,
            )
        return _admin_mutation_response(
            "line_acceptance.review",
            {"ok": True, **result},
        )

    @app.get("/api/admin/business-dashboard")
    def admin_business_dashboard_api():
        denied = _admin_guard()
        if denied:
            return denied
        return jsonify(admin_business_dashboard(app.config["DATA_FILE"], app.config))

    @app.get("/api/admin/beta-program")
    def admin_beta_program_api():
        denied = _admin_guard(permission="beta.manage")
        if denied:
            return denied
        return jsonify(admin_beta_summary(app.config["DATA_FILE"]))

    @app.post("/api/admin/beta-program/assign")
    def admin_beta_program_assign_api():
        denied = _admin_guard(write=True, permission="beta.manage")
        if denied:
            return denied
        data, code = assign_beta_member(
            app.config["DATA_FILE"], request.get_json(silent=True) or {}
        )
        return _admin_mutation_response("beta.assign", data, code)

    @app.post("/api/admin/beta-members")
    def admin_beta_member_assign_api():
        denied = _admin_guard(write=True)
        if denied:
            return denied
        data, code = admin_assign_beta_member(
            app.config["DATA_FILE"], request.get_json(silent=True) or {}
        )
        return _admin_mutation_response("beta.assign", data, code)

    @app.delete("/api/admin/beta-members/<line_user_id>")
    def admin_beta_member_revoke_api(line_user_id):
        denied = _admin_guard(write=True)
        if denied:
            return denied
        data, code = admin_revoke_beta_member(
            app.config["DATA_FILE"], line_user_id
        )
        return _admin_mutation_response("beta.revoke", data, code)

    @app.get("/api/admin/launch-readiness")
    def admin_launch_readiness_api():
        denied = _admin_guard()
        if denied:
            return denied
        return jsonify(
            launch_readiness_snapshot(load_state(app.config["DATA_FILE"]))
        )

    @app.post("/api/admin/launch-validation")
    def admin_launch_validation_api():
        denied = _admin_guard(write=True)
        if denied:
            return denied
        payload = request.get_json(silent=True) or {}
        try:
            scenario = mutate_state_atomically(
                app.config["DATA_FILE"],
                lambda state: record_launch_validation_step(
                    state,
                    payload.get("scenario_id"),
                    payload.get("kind"),
                    payload.get("step"),
                    line_user_id=payload.get("line_user_id") or "",
                ),
            )
        except ValueError as exc:
            return _admin_mutation_response(
                "launch_validation.record",
                {"ok": False, "error": str(exc)},
                400,
            )
        return _admin_mutation_response(
            "launch_validation.record",
            {"ok": True, "scenario": scenario},
            200,
        )

    @app.post("/api/admin/beta-program/update")
    def admin_beta_program_update_api():
        denied = _admin_guard(write=True, permission="beta.manage")
        if denied:
            return denied
        data, code = update_beta_member(
            app.config["DATA_FILE"], request.get_json(silent=True) or {}
        )
        return _admin_mutation_response("beta.update", data, code)

    @app.get("/api/admin/privacy-requests")
    def admin_privacy_requests_api():
        denied = _admin_guard(permission="privacy.manage")
        if denied:
            return denied
        return jsonify(admin_privacy_requests(app.config["DATA_FILE"]))

    @app.post("/api/admin/privacy-requests/update")
    def admin_privacy_requests_update_api():
        denied = _admin_guard(write=True, permission="privacy.manage")
        if denied:
            return denied
        data, code = update_privacy_request(
            app.config["DATA_FILE"],
            request.get_json(silent=True) or {},
            str(session.get("admin_role") or "viewer"),
        )
        return _admin_mutation_response("privacy.update", data, code)

    @app.get("/api/admin/support-tickets")
    def admin_support_tickets_api():
        denied = _admin_guard()
        if denied:
            return denied
        return jsonify(admin_support_tickets(app.config["DATA_FILE"]))

    @app.get("/api/support/tickets")
    def member_support_tickets_api():
        line_user_id, err = _authenticated_line_user({}, use_args=True)
        if err:
            return jsonify(err[0]), err[1]
        data, code = member_support_tickets(
            app.config["DATA_FILE"], line_user_id
        )
        return jsonify(data), code

    @app.post("/api/support/tickets")
    def member_support_ticket_create_api():
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        payload["line_user_id"] = line_user_id
        data, code = create_support_ticket(app.config["DATA_FILE"], payload)
        return jsonify(data), code

    @app.get("/api/admin/backups")
    def admin_backups_list_api():
        denied = _admin_guard()
        if denied:
            return denied
        return jsonify(list_admin_backups(app.config["DATA_FILE"]))

    @app.post("/api/admin/backups")
    def admin_backups_create_api():
        denied = _admin_guard(write=True, permission="backup.manage")
        if denied:
            return denied
        data, code = create_admin_backup(app.config["DATA_FILE"])
        return _admin_mutation_response("backup.create", data, code)

    @app.post("/api/admin/backups/r2")
    def admin_r2_backup_create_api():
        denied = _admin_guard(write=True)
        if denied:
            return denied
        data, code = create_r2_encrypted_backup(app.config)
        return _admin_mutation_response("backup.r2.create", data, code)

    @app.get("/api/admin/backups/<backup_id>")
    def admin_backups_download_api(backup_id):
        denied = _admin_guard()
        if denied:
            return denied
        data, code = read_admin_backup(app.config["DATA_FILE"], backup_id)
        return jsonify(data), code

    @app.post("/api/admin/support-reply")
    def admin_support_reply_api():
        denied = _admin_guard(write=True, permission="support.manage")
        if denied:
            return denied
        data, code = admin_reply_support_ticket(app.config["DATA_FILE"], request.get_json(silent=True) or {}, app.config)
        return _admin_mutation_response("support.reply", data, code)

    @app.post("/api/admin/send-reminders")
    def send_reminders_api():
        denied = _admin_guard(write=True, permission="notification.manage")
        if denied:
            return denied
        data, code = send_due_reminders(app.config)
        return _admin_mutation_response("reminder.send", data, code)

    @app.post("/api/admin/send-contact-reminders")
    def send_contact_reminders_api():
        denied = _admin_guard(write=True, permission="notification.manage")
        if denied:
            return denied
        data, code = send_missing_contact_reminders(app.config)
        return _admin_mutation_response("contact_reminder.send", data, code)

    @app.post("/api/admin/send-renewal-reminders")
    def send_renewal_reminders_api():
        denied = _admin_guard(write=True, permission="notification.manage")
        if denied:
            return denied
        data, code = send_renewal_reminders(app.config)
        return _admin_mutation_response("renewal_reminder.send", data, code)

    @app.post("/api/admin/send-birthday-reminders")
    def send_birthday_reminders_api():
        denied = _admin_guard(write=True, permission="notification.manage")
        if denied:
            return denied
        data, code = send_birthday_reminders(app.config)
        return _admin_mutation_response("birthday_reminder.send", data, code)

    @app.post("/api/admin/payments/confirm")
    def admin_payment_confirm_api():
        denied = _admin_guard(write=True, permission="order.manage")
        if denied:
            return denied
        data, code = confirm_payment_order(app.config["DATA_FILE"], request.get_json(silent=True) or {}, app.config)
        return _admin_mutation_response("payment.confirm", data, code)

    @app.post("/api/admin/payments/refund")
    def admin_payment_refund_api():
        denied = _admin_guard(write=True)
        if denied:
            return denied
        payload = request.get_json(silent=True) or {}
        payload["requested_by"] = "admin_session"
        data, code = refund_payment_order(
            app.config["DATA_FILE"], payload, app.config
        )
        return _admin_mutation_response("payment.refund", data, code)

    @app.post("/api/cron/tick")
    def cron_tick_api():
        secret = request.headers.get("X-Cron-Secret", "")
        if not cron_allowed(app.config, secret):
            return jsonify({"error": "unauthorized"}), 401
        data, code = run_cron_tick(app.config)
        return jsonify(data), code

    @app.route("/api/cron/contact-reminders", methods=["GET", "POST"])
    def cron_contact_reminders_api():
        secret = request.headers.get("X-Cron-Secret", "")
        if not cron_allowed(app.config, secret):
            return jsonify({"error": "unauthorized"}), 401
        data, code = send_missing_contact_reminders(app.config)
        return jsonify(data), code

    @app.route("/api/cron/checkin-reminders", methods=["GET", "POST"])
    def cron_checkin_reminders_api():
        secret = request.headers.get("X-Cron-Secret", "")
        if not cron_allowed(app.config, secret):
            return jsonify({"error": "unauthorized"}), 401
        # ?mode=broadcast 或 force=1 → 重新推播給全部已註冊會員（含今日已簽到）
        mode = str(request.args.get("mode") or "").strip().lower()
        force = str(request.args.get("force") or "").strip().lower() in {"1", "true", "yes", "on"}
        if mode in {"broadcast", "repush", "all"} or force:
            data, code = broadcast_checkin_reminders(app.config)
        else:
            data, code = send_checkin_reminders(app.config)
        return jsonify(data), code

    @app.route("/api/cron/checkin-broadcast", methods=["GET", "POST"])
    def cron_checkin_broadcast_api():
        """重新推播專用：對有 line_user_id 的會員送新版每日平安 Flex。"""
        secret = request.headers.get("X-Cron-Secret", "")
        if not cron_allowed(app.config, secret):
            return jsonify({"error": "unauthorized"}), 401
        data, code = broadcast_checkin_reminders(app.config)
        return jsonify(data), code

    @app.route("/api/cron/overdue-alerts", methods=["GET", "POST"])
    def cron_overdue_alerts_api():
        secret = request.headers.get("X-Cron-Secret", "")
        if not cron_allowed(app.config, secret):
            return jsonify({"error": "unauthorized"}), 401
        data, code = send_due_reminders(app.config)
        daily, _daily_code = send_guardian_group_daily_summaries(app.config)
        if isinstance(data, dict):
            data = dict(data)
            data["daily_group_summary"] = daily
        return jsonify(data), code

    @app.route("/api/cron/renewal-reminders", methods=["GET", "POST"])
    def cron_renewal_reminders_api():
        secret = request.headers.get("X-Cron-Secret", "")
        if not cron_allowed(app.config, secret):
            return jsonify({"error": "unauthorized"}), 401
        data, code = send_renewal_reminders(app.config)
        return jsonify(data), code

    @app.route("/api/cron/birthday-reminders", methods=["GET", "POST"])
    def cron_birthday_reminders_api():
        secret = request.headers.get("X-Cron-Secret", "")
        if not cron_allowed(app.config, secret):
            return jsonify({"error": "unauthorized"}), 401
        data, code = send_birthday_reminders(app.config)
        return jsonify(data), code

    @app.route("/api/cron/smart-reminders", methods=["GET", "POST"])
    def cron_smart_reminders_api():
        secret = request.headers.get("X-Cron-Secret", "")
        if not cron_allowed(app.config, secret):
            return jsonify({"error": "unauthorized"}), 401
        data, code = send_smart_reminders(app.config)
        return jsonify(data), code

    @app.get("/api/smart-reminders")
    def smart_reminders_get():
        line_user_id, err = _authenticated_line_user({}, use_args=True)
        if err:
            return jsonify(err[0]), err[1]
        return jsonify(get_smart_reminders_payload(app.config["DATA_FILE"], line_user_id))

    @app.post("/api/smart-reminders")
    def smart_reminders_post():
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        payload["line_user_id"] = line_user_id
        data, code = save_smart_reminder(app.config["DATA_FILE"], payload)
        return jsonify(data), code

    @app.delete("/api/smart-reminders/<reminder_id>")
    def smart_reminders_delete(reminder_id):
        line_user_id, err = _authenticated_line_user({}, use_args=True)
        if err:
            # Also accept JSON body for clients that send line_user_id there
            payload = request.get_json(silent=True) or {}
            line_user_id, err = _authenticated_line_user(payload)
            if err:
                return jsonify(err[0]), err[1]
        data, code = delete_smart_reminder(app.config["DATA_FILE"], line_user_id, reminder_id)
        return jsonify(data), code

    @app.route("/api/cron/membership-expiry", methods=["GET", "POST"])
    def cron_membership_expiry_api():
        secret = request.headers.get("X-Cron-Secret", "")
        if not cron_allowed(app.config, secret):
            return jsonify({"error": "unauthorized"}), 401
        data, code = apply_expired_plan_downgrades(app.config)
        return jsonify(data), code

    @app.route("/api/cron/data-cleanup", methods=["GET", "POST"])
    def cron_data_cleanup_api():
        secret = request.headers.get("X-Cron-Secret", "")
        if not cron_allowed(app.config, secret):
            return jsonify({"error": "unauthorized"}), 401
        data, code = cleanup_expired_data(app.config)
        return jsonify(data), code

    @app.route("/api/cron/backfill-bind-notify", methods=["GET", "POST"])
    def cron_backfill_bind_notify_api():
        """One-shot: 補發歷史已綁定雙方的綁定成功 LINE（冪等 bind_notify_sent_at）。"""
        secret = request.headers.get("X-Cron-Secret", "")
        if not cron_allowed(app.config, secret):
            return jsonify({"error": "unauthorized"}), 401
        payload = request.get_json(silent=True) or {}
        dry_run = str(
            request.args.get("dry_run")
            or payload.get("dry_run")
            or ""
        ).strip().lower() in {"1", "true", "yes", "on"}
        try:
            limit = int(request.args.get("limit") or payload.get("limit") or 0)
        except (TypeError, ValueError):
            limit = 0
        data, code = backfill_bind_notify(app.config, dry_run=dry_run, limit=limit)
        return jsonify(data), code

    @app.get("/api/admin/rich-menu")
    def admin_rich_menu_inspect_api():
        """查詢目前預設圖文選單（含一鍵邀請 URI）。不回傳 token。"""
        denied = _admin_guard()
        if denied:
            return denied
        data, code = inspect_default_rich_menu(app.config)
        return jsonify(data), code

    @app.post("/api/admin/rich-menu/deploy")
    def admin_rich_menu_deploy_api():
        """用 Render 上的 LINE_CHANNEL_ACCESS_TOKEN 上傳並設為預設圖文選單。"""
        denied = _admin_guard(write=True, permission="system.manage")
        if denied:
            return denied
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
        return _admin_mutation_response("rich_menu.deploy", data, code)

    @app.post("/api/admin/push-welcome")
    def admin_push_welcome_api():
        """管理員補推歡迎 Flex（需已加好友）。body: {line_user_id, display_name?}"""
        denied = _admin_guard(write=True, permission="notification.manage")
        if denied:
            return denied
        if LineBotApi is None or FlexSendMessage is None or welcome_flex is None:
            return _admin_mutation_response(
                "welcome.push",
                {"ok": False, "error": "line sdk or welcome_flex unavailable"},
                503,
            )
        payload = request.get_json(silent=True) or {}
        line_user_id = str(payload.get("line_user_id") or "").strip()
        if not line_user_id:
            return _admin_mutation_response(
                "welcome.push",
                {"ok": False, "error": "missing line_user_id"},
                400,
            )
        token = (
            app.config.get("LINE_CHANNEL_ACCESS_TOKEN")
            or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
            or ""
        ).strip()
        if not token:
            return _admin_mutation_response(
                "welcome.push",
                {"ok": False, "error": "LINE_CHANNEL_ACCESS_TOKEN not set"},
                503,
            )
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
            return _admin_mutation_response(
                "welcome.push",
                {
                    "ok": True,
                    "line_user_id": line_user_id,
                    "display_name": resolved,
                    "greeting": greeting,
                },
            )
        except LineBotApiError as exc:
            detail = str(exc)
            try:
                detail = getattr(exc, "error", None) or detail
            except Exception:
                pass
            app.logger.exception("admin push-welcome LINE error: %s", detail)
            return _admin_mutation_response(
                "welcome.push",
                {"ok": False, "error": "line_api_error", "detail": str(detail)},
                502,
            )
        except Exception as exc:
            app.logger.exception("admin push-welcome failed: %s", exc)
            return _admin_mutation_response(
                "welcome.push",
                {"ok": False, "error": str(exc)},
                500,
            )

    @app.post("/api/admin/user-plan")
    def admin_user_plan_api():
        denied = _admin_guard(write=True, permission="member.manage")
        if denied:
            return denied
        data, code = admin_update_user_plan(app.config["DATA_FILE"], request.get_json(silent=True) or {})
        return _admin_mutation_response("user_plan.update", data, code)

    @app.post("/api/admin/set-core-guardian")
    def admin_set_core_guardian_api():
        denied = _admin_guard(write=True, permission="member.manage")
        if denied:
            return denied
        data, code = admin_set_core_guardian(app.config["DATA_FILE"], request.get_json(silent=True) or {})
        return _admin_mutation_response("core_guardian.set", data, code)

    @app.post("/api/admin/incidents/resolve")
    def admin_incident_resolve_api():
        denied = _admin_guard(write=True, permission="incident.manage")
        if denied:
            return denied
        payload = request.get_json(silent=True) or {}
        data, code = resolve_admin_incident(
            app.config["DATA_FILE"],
            payload,
            session.get("admin_role"),
        )
        return _admin_mutation_response(
            "incident.resolve",
            data,
            code,
        )

    return app


class MiniResponse:
    def __init__(self, data, status_code=200, headers=None):
        self._data = data
        self.status_code = status_code
        self.headers = headers or {}

    def get_json(self):
        return self._data

    def close(self):
        return None

    def get_data(self, as_text=False):
        if isinstance(self._data, bytes):
            return self._data.decode("utf-8") if as_text else self._data
        if isinstance(self._data, str):
            return self._data if as_text else self._data.encode("utf-8")
        rendered = json.dumps(self._data, ensure_ascii=False)
        return rendered if as_text else rendered.encode("utf-8")


class MiniClient:
    def __init__(self, app):
        self.app = app

    def get(self, path, headers=None):
        route, _, query = path.partition("?")
        if route == "/api/admin" or route.startswith("/api/admin/"):
            return MiniResponse({"error": "admin_not_configured"}, 503)
        params = dict(urllib.parse.parse_qsl(query))
        headers = headers or {}
        if route == "/api/config":
            return MiniResponse(app_config(self.app.config))
        if route == "/health":
            return MiniResponse({"ok": True})
        if route in ("/robots.txt", "/sitemap.xml"):
            filename = route.lstrip("/")
            path_obj = Path(__file__).resolve().parent / filename
            if path_obj.exists():
                return MiniResponse(path_obj.read_text(encoding="utf-8"))
            return MiniResponse({"error": "not found"}, 404)
        if route in ("/terms", "/privacy"):
            return MiniResponse({"ok": True})
        if route == "/liff/migrate.html":
            return MiniResponse({"ok": True})
        if route == "/liff/onboarding":
            liff_id = str(self.app.config.get("LIFF_ID") or DEFAULT_LIFF_ID).strip()
            return MiniResponse(
                {"ok": True},
                302,
                {"Location": f"https://liff.line.me/{liff_id}?open=onboarding"},
            )
        if route == "/api/status":
            line_user_id, err = authenticated_line_user(
                {}, args=params, headers=headers, config=self.app.config
            )
            if err:
                return MiniResponse(err[0], err[1])
            body, code = status_for_user(
                self.app.config["DATA_FILE"],
                line_user_id,
                params.get("display_name"),
            )
            return MiniResponse(body, code)
        if route == "/api/onboarding":
            line_user_id, err = authenticated_line_user(
                {}, args=params, headers=headers, config=self.app.config
            )
            if err:
                return MiniResponse(err[0], err[1])
            body, code = onboarding_status_payload(
                self.app.config["DATA_FILE"], line_user_id
            )
            return MiniResponse(body, code)
        if route == "/api/onboarding/state":
            line_user_id, err = authenticated_line_user(
                {}, args=params, headers=headers, config=self.app.config
            )
            if err:
                return MiniResponse(err[0], err[1])
            body, code = onboarding_status_payload(
                self.app.config["DATA_FILE"],
                line_user_id,
                allow_missing_profile=True,
            )
            return MiniResponse(body, code)
        if route == "/api/guardian-groups/settings":
            line_user_id, err = authenticated_line_user(
                {}, args=params, headers=headers, config=self.app.config
            )
            if err:
                return MiniResponse(err[0], err[1])
            body, code = guardian_group_settings_for_user(
                self.app.config["DATA_FILE"], line_user_id
            )
            return MiniResponse(body, code)
        if route == "/api/admin/summary":
            denied = admin_auth_error_payload(self.app.config, params.get("password", ""))
            if denied:
                payload, code = denied
                return MiniResponse(payload, code)
            return MiniResponse(admin_summary(self.app.config["DATA_FILE"], self.app.config))
        if route == "/api/admin/support-tickets":
            if not admin_allowed(self.app.config, params.get("password", "")):
                return MiniResponse({"error": "unauthorized"}, 401)
            return MiniResponse(admin_support_tickets(self.app.config["DATA_FILE"]))
        if route == "/api/support/tickets":
            line_user_id, err = authenticated_line_user(
                {}, args=params, headers=headers, config=self.app.config
            )
            if err:
                return MiniResponse(err[0], err[1])
            body, code = member_support_tickets(
                self.app.config["DATA_FILE"], line_user_id
            )
            return MiniResponse(body, code)
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
        if route == "/api/emergency-contact/invite-preview":
            line_user_id, err = authenticated_line_user(
                {}, args=params, headers=headers, config=self.app.config
            )
            if err:
                return MiniResponse(err[0], err[1])
            body, code = invite_bind_preview(
                self.app.config["DATA_FILE"],
                {
                    "invite_from": params.get("invite_from") or params.get("from") or "",
                    "invite_token": params.get("invite_token") or "",
                    "line_user_id": line_user_id,
                },
            )
            return MiniResponse(body, code)
        if route == "/api/calendar-notes":
            line_user_id, err = authenticated_line_user(
                {}, args=params, headers=headers, config=self.app.config
            )
            if err:
                return MiniResponse(err[0], err[1])
            body = get_calendar_notes(self.app.config["DATA_FILE"], line_user_id)
            return MiniResponse(body, 200 if body.get("ok") else 403)
        if route == "/api/smart-reminders":
            line_user_id, err = authenticated_line_user(
                {}, args=params, headers=headers, config=self.app.config
            )
            if err:
                return MiniResponse(err[0], err[1])
            return MiniResponse(
                get_smart_reminders_payload(
                    self.app.config["DATA_FILE"], line_user_id
                )
            )
        if route == "/api/friends/locations":
            return MiniResponse(friend_locations(self.app.config["DATA_FILE"], params.get("line_user_id")))
        if route == "/api/location/status":
            line_user_id = params.get("line_user_id")
            if not line_user_id:
                return MiniResponse({"error": "missing line_user_id"}, 400)
            profile = get_profile(load_state(self.app.config["DATA_FILE"]), line_user_id)
            return MiniResponse({"ok": True, "safety_guard": safety_guard_snapshot(profile)})
        return MiniResponse({"error": "not found"}, 404)

    def post(self, path, data=None, content_type=None, headers=None, **kwargs):
        route, _, query = path.partition("?")
        if route == "/api/admin" or route.startswith("/api/admin/"):
            return MiniResponse({"error": "admin_not_configured"}, 503)
        params = dict(urllib.parse.parse_qsl(query))
        headers = headers or {}
        cron_secret = (
            headers.get("X-Cron-Secret")
            or headers.get("x-cron-secret")
            or ""
        )
        payload = {}
        json_payload = kwargs.get("json")
        if isinstance(json_payload, dict):
            payload = dict(json_payload)
        elif data and content_type == "application/json":
            payload = json.loads(data)
        if route == "/api/line/register":
            body, code = register_line_user(self.app.config["DATA_FILE"], payload)
            return MiniResponse(body, code)
        if route == "/api/checkin":
            line_user_id, err = authenticated_line_user(
                payload, args=params, headers=headers, config=self.app.config
            )
            if err:
                return MiniResponse(err[0], err[1])
            result, code = checkin_for_user(
                self.app.config["DATA_FILE"], line_user_id, payload, self.app.config
            )
            return MiniResponse(result, code)
        if route == "/api/onboarding/reminder":
            line_user_id, err = authenticated_line_user(
                payload, args=params, headers=headers, config=self.app.config
            )
            if err:
                return MiniResponse(err[0], err[1])
            result, code = update_onboarding_reminder(
                self.app.config["DATA_FILE"], line_user_id, payload
            )
            return MiniResponse(result, code)
        if route == "/api/onboarding/complete":
            line_user_id, err = authenticated_line_user(
                payload, args=params, headers=headers, config=self.app.config
            )
            if err:
                return MiniResponse(err[0], err[1])
            result, code = complete_onboarding_for_user(
                self.app.config["DATA_FILE"], line_user_id, payload
            )
            return MiniResponse(result, code)
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
        if route in {"/api/payment/ecpay/notify", "/api/payment/ecpay/period-notify"}:
            form = dict(data) if isinstance(data, dict) else payload
            if ecpay is None:
                return MiniResponse("0|payment module missing", 503)
            parsed, error = ecpay.parse_notify_payload(form, self.app.config)
            if error:
                return MiniResponse(f"0|{error}", 400)
            if not ecpay.notify_success(parsed, self.app.config):
                return MiniResponse("1|OK", 200)
            if route.endswith("/period-notify"):
                parsed.update({"status": "SUCCESS", "provider": "ecpay"})
                body, code = process_period_notification(
                    self.app.config["DATA_FILE"], parsed, self.app.config
                )
            else:
                body, code = confirm_payment_order(
                    self.app.config["DATA_FILE"],
                    {
                        "order_id": parsed.get("order_id"),
                        "transaction_id": parsed.get("transaction_id"),
                        "amount": parsed.get("amount"),
                        "provider": "ecpay",
                    },
                    self.app.config,
                )
            if code >= 400:
                return MiniResponse(
                    f"0|{body.get('error', 'order update failed')}", code
                )
            return MiniResponse("1|OK", 200)
        if route == "/api/contacts":
            body, code = save_contacts(self.app.config["DATA_FILE"], payload)
            return MiniResponse(body, code)
        if route == "/api/calendar-notes":
            line_user_id, err = authenticated_line_user(
                payload, args=params, headers=headers, config=self.app.config
            )
            if err:
                return MiniResponse(err[0], err[1])
            payload["line_user_id"] = line_user_id
            body, code = save_calendar_note(self.app.config["DATA_FILE"], payload)
            return MiniResponse(body, code)
        if route == "/api/smart-reminders":
            line_user_id, err = authenticated_line_user(
                payload, args=params, headers=headers, config=self.app.config
            )
            if err:
                return MiniResponse(err[0], err[1])
            payload["line_user_id"] = line_user_id
            body, code = save_smart_reminder(self.app.config["DATA_FILE"], payload)
            return MiniResponse(body, code)
        if route in {"/api/cron/smart-reminders", "/api/cron/birthday-reminders"}:
            if not cron_allowed(self.app.config, cron_secret):
                return MiniResponse({"error": "unauthorized"}, 401)
            task = (
                send_smart_reminders
                if route.endswith("smart-reminders")
                else send_birthday_reminders
            )
            body, code = task(self.app.config)
            return MiniResponse(body, code)
        if route == "/api/emergency-contact/bind":
            line_user_id, err = authenticated_line_user(payload, args=params, headers=headers, config=self.app.config)
            if err:
                return MiniResponse(err[0], err[1])
            payload["contact_line_user_id"] = line_user_id
            body, code = bind_emergency_contact(self.app.config["DATA_FILE"], payload, self.app.config)
            return MiniResponse(body, code)
        if route == "/api/emergency-contact/invite":
            line_user_id, err = authenticated_line_user(
                payload, args=params, headers=headers, config=self.app.config
            )
            if err:
                return MiniResponse(err[0], err[1])
            body, code = create_guardian_invite(
                self.app.config["DATA_FILE"], line_user_id, payload
            )
            return MiniResponse(body, code)
        if route == "/api/guardian-groups/bind":
            line_user_id, err = authenticated_line_user(
                payload, args=params, headers=headers, config=self.app.config
            )
            if err:
                return MiniResponse(err[0], err[1])
            payload["line_user_id"] = line_user_id
            body, code = bind_guardian_group(self.app.config["DATA_FILE"], payload)
            return MiniResponse(body, code)
        if route == "/api/guardian-groups/preferences":
            line_user_id, err = authenticated_line_user(
                payload, args=params, headers=headers, config=self.app.config
            )
            if err:
                return MiniResponse(err[0], err[1])
            payload["line_user_id"] = line_user_id
            body, code = update_guardian_group_preferences(
                self.app.config["DATA_FILE"], payload
            )
            return MiniResponse(body, code)
        if route == "/api/guardian-groups/unbind":
            line_user_id, err = authenticated_line_user(
                payload, args=params, headers=headers, config=self.app.config
            )
            if err:
                return MiniResponse(err[0], err[1])
            payload["line_user_id"] = line_user_id
            body, code = unbind_guardian_group(self.app.config["DATA_FILE"], payload)
            return MiniResponse(body, code)
        if route == "/api/friends/invite":
            body, code = create_friend_invite(self.app.config["DATA_FILE"], payload)
            return MiniResponse(body, code)
        if route == "/api/friends/accept":
            body, code = accept_friend_invite(self.app.config["DATA_FILE"], payload)
            return MiniResponse(body, code)
        if route == "/api/location/update":
            body, code = update_location(self.app.config["DATA_FILE"], payload, self.app.config)
            return MiniResponse(body, code)
        if route == "/api/location/stop":
            body, code = stop_location_sharing(self.app.config["DATA_FILE"], payload)
            return MiniResponse(body, code)
        if route == "/api/sos":
            body, code = trigger_sos(self.app.config["DATA_FILE"], payload, self.app.config)
            return MiniResponse(body, code)
        if route == "/api/sos/cancel":
            body, code = cancel_sos_event(self.app.config["DATA_FILE"], payload, self.app.config)
            return MiniResponse(body, code)
        if route == "/api/sos/retry":
            body, code = retry_sos_event(self.app.config["DATA_FILE"], payload, self.app.config)
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
        if route == "/api/cron/tick":
            if not cron_allowed(self.app.config, cron_secret):
                return MiniResponse({"error": "unauthorized"}, 401)
            body, code = run_cron_tick(self.app.config)
            return MiniResponse(body, code)
        if route == "/api/cron/contact-reminders":
            if not cron_allowed(self.app.config, cron_secret):
                return MiniResponse({"error": "unauthorized"}, 401)
            body, code = send_missing_contact_reminders(self.app.config)
            return MiniResponse(body, code)
        if route == "/api/cron/checkin-reminders":
            if not cron_allowed(self.app.config, cron_secret):
                return MiniResponse({"error": "unauthorized"}, 401)
            mode = str(params.get("mode", "") or "").strip().lower()
            force = str(params.get("force", "") or "").strip().lower() in {"1", "true", "yes", "on"}
            if mode in {"broadcast", "repush", "all"} or force:
                body, code = broadcast_checkin_reminders(self.app.config)
            else:
                body, code = send_checkin_reminders(self.app.config)
            return MiniResponse(body, code)
        if route == "/api/cron/checkin-broadcast":
            if not cron_allowed(self.app.config, cron_secret):
                return MiniResponse({"error": "unauthorized"}, 401)
            body, code = broadcast_checkin_reminders(self.app.config)
            return MiniResponse(body, code)
        if route == "/api/cron/renewal-reminders":
            if not cron_allowed(self.app.config, cron_secret):
                return MiniResponse({"error": "unauthorized"}, 401)
            body, code = send_renewal_reminders(self.app.config)
            return MiniResponse(body, code)
        if route == "/api/cron/data-cleanup":
            if not cron_allowed(self.app.config, cron_secret):
                return MiniResponse({"error": "unauthorized"}, 401)
            body, code = cleanup_expired_data(self.app.config)
            return MiniResponse(body, code)
        if route == "/api/cron/backfill-bind-notify":
            if not cron_allowed(self.app.config, cron_secret):
                return MiniResponse({"error": "unauthorized"}, 401)
            dry_run = str(params.get("dry_run") or payload.get("dry_run") or "").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            try:
                limit = int(params.get("limit") or payload.get("limit") or 0)
            except (TypeError, ValueError):
                limit = 0
            body, code = backfill_bind_notify(self.app.config, dry_run=dry_run, limit=limit)
            return MiniResponse(body, code)
        if route == "/api/admin/user-plan":
            if not admin_allowed(self.app.config, params.get("password", "")):
                return MiniResponse({"error": "unauthorized"}, 401)
            body, code = admin_update_user_plan(self.app.config["DATA_FILE"], payload)
            return MiniResponse(body, code)
        if route == "/api/admin/set-core-guardian":
            if not admin_allowed(self.app.config, params.get("password", "")):
                return MiniResponse({"error": "unauthorized"}, 401)
            body, code = admin_set_core_guardian(self.app.config["DATA_FILE"], payload)
            return MiniResponse(body, code)
        if route == "/api/admin/support-reply":
            if not admin_allowed(self.app.config, params.get("password", "")):
                return MiniResponse({"error": "unauthorized"}, 401)
            body, code = admin_reply_support_ticket(self.app.config["DATA_FILE"], payload, self.app.config)
            return MiniResponse(body, code)
        if route == "/api/support/tickets":
            line_user_id, err = authenticated_line_user(
                payload, args=params, headers=headers, config=self.app.config
            )
            if err:
                return MiniResponse(err[0], err[1])
            payload["line_user_id"] = line_user_id
            body, code = create_support_ticket(
                self.app.config["DATA_FILE"], payload
            )
            return MiniResponse(body, code)
        return MiniResponse({"error": "not found"}, 404)

    def delete(self, path, headers=None):
        route, _, query = path.partition("?")
        params = dict(urllib.parse.parse_qsl(query))
        headers = headers or {}
        if route.startswith("/api/smart-reminders/"):
            line_user_id, err = authenticated_line_user(
                {}, args=params, headers=headers, config=self.app.config
            )
            if err:
                return MiniResponse(err[0], err[1])
            reminder_id = route.rsplit("/", 1)[-1]
            body, code = delete_smart_reminder(
                self.app.config["DATA_FILE"], line_user_id, reminder_id
            )
            return MiniResponse(body, code)
        return MiniResponse({"error": "not found"}, 404)


class MiniApp:
    def __init__(self, config=None):
        self.config = {
            "DATA_FILE": resolve_data_file(os.environ.get("DATA_FILE")),
            "ADMIN_PASSWORD": os.environ.get("ADMIN_PASSWORD", ""),
            "ADMIN_SESSION_SECRET": os.environ.get("ADMIN_SESSION_SECRET", ""),
            "ALLOW_OPEN_ADMIN": os.environ.get("ALLOW_OPEN_ADMIN", ""),
            "ADMIN_OPEN": os.environ.get("ADMIN_OPEN", ""),
            "LINE_CHANNEL_ACCESS_TOKEN": os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", ""),
            "LINE_CHANNEL_SECRET": os.environ.get("LINE_CHANNEL_SECRET", ""),
            "LIFF_ID": os.environ.get("LIFF_ID") or DEFAULT_LIFF_ID,
            "LINE_LOGIN_CHANNEL_ID": (
                os.environ.get("LINE_LOGIN_CHANNEL_ID")
                or (os.environ.get("LIFF_ID") or DEFAULT_LIFF_ID).split("-", 1)[0]
                or DEFAULT_LINE_LOGIN_CHANNEL_ID
            ),
            "LEGACY_LINE_LOGIN_CHANNEL_ID": os.environ.get(
                "LEGACY_LINE_LOGIN_CHANNEL_ID", "2010674803"
            ),
            "LEGACY_LIFF_ID": os.environ.get("LEGACY_LIFF_ID", DEFAULT_LEGACY_LIFF_ID),
            "ACCOUNT_MIGRATION_SECRET": os.environ.get("ACCOUNT_MIGRATION_SECRET", ""),
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

            def cron_secret(handler):
                return handler.headers.get("X-Cron-Secret", "")

            def route(handler):
                return urllib.parse.urlsplit(handler.path).path

            def authenticated_user(handler, payload=None, params=None):
                return authenticated_line_user(
                    payload or {},
                    args=params or {},
                    headers=dict(handler.headers.items()),
                    config=config,
                )

            def do_GET(handler):
                route = handler.route()
                if route == "/api/admin" or route.startswith("/api/admin/"):
                    return handler.send_json({"error": "admin_not_configured"}, 503)
                params = handler.query()
                if route == "/api/config":
                    return handler.send_json(app_config(config))
                if route == "/health":
                    return handler.send_json({"ok": True})
                if route == "/api/status":
                    line_user_id, err = handler.authenticated_user(params=params)
                    if err:
                        return handler.send_json(err[0], err[1])
                    data, code = status_for_user(
                        data_file,
                        line_user_id,
                        params.get("display_name"),
                    )
                    return handler.send_json(data, code)
                if route == "/api/onboarding":
                    line_user_id, err = handler.authenticated_user(params=params)
                    if err:
                        return handler.send_json(err[0], err[1])
                    data, code = onboarding_status_payload(data_file, line_user_id)
                    return handler.send_json(data, code)
                if route == "/api/onboarding/state":
                    line_user_id, err = handler.authenticated_user(params=params)
                    if err:
                        return handler.send_json(err[0], err[1])
                    data, code = onboarding_status_payload(
                        data_file,
                        line_user_id,
                        allow_missing_profile=True,
                    )
                    return handler.send_json(data, code)
                if route == "/api/admin/summary":
                    denied = admin_auth_error_payload(config, params.get("password", ""))
                    if denied:
                        payload, code = denied
                        return handler.send_json(payload, code)
                    return handler.send_json(admin_summary(data_file, config))
                if route == "/api/contacts":
                    return handler.send_json(get_contacts(data_file, params.get("line_user_id")))
                if route == "/api/emergency-contact/invite-preview":
                    line_user_id, err = handler.authenticated_user({}, params)
                    if err:
                        return handler.send_json(err[0], err[1])
                    data, code = invite_bind_preview(
                        data_file,
                        {
                            "invite_from": params.get("invite_from") or params.get("from") or "",
                            "invite_token": params.get("invite_token") or "",
                            "line_user_id": line_user_id,
                        },
                    )
                    return handler.send_json(data, code)
                if route == "/api/calendar-notes":
                    line_user_id, err = handler.authenticated_user(params=params)
                    if err:
                        return handler.send_json(err[0], err[1])
                    body = get_calendar_notes(data_file, line_user_id)
                    return handler.send_json(
                        body, status=200 if body.get("ok") else 403
                    )
                if route == "/api/smart-reminders":
                    line_user_id, err = handler.authenticated_user(params=params)
                    if err:
                        return handler.send_json(err[0], err[1])
                    return handler.send_json(
                        get_smart_reminders_payload(data_file, line_user_id)
                    )
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
                    if not cron_allowed(config, handler.cron_secret()):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    data, code = send_missing_contact_reminders(config)
                    return handler.send_json(data, code)
                if route == "/api/cron/checkin-reminders":
                    if not cron_allowed(config, handler.cron_secret()):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    mode = str(params.get("mode", "") or "").strip().lower()
                    force = str(params.get("force", "") or "").strip().lower() in {"1", "true", "yes", "on"}
                    if mode in {"broadcast", "repush", "all"} or force:
                        data, code = broadcast_checkin_reminders(config)
                    else:
                        data, code = send_checkin_reminders(config)
                    return handler.send_json(data, code)
                if route == "/api/cron/checkin-broadcast":
                    if not cron_allowed(config, handler.cron_secret()):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    data, code = broadcast_checkin_reminders(config)
                    return handler.send_json(data, code)
                if route == "/api/cron/data-cleanup":
                    if not cron_allowed(config, handler.cron_secret()):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    data, code = cleanup_expired_data(config)
                    return handler.send_json(data, code)
                if route == "/api/cron/backfill-bind-notify":
                    if not cron_allowed(config, handler.cron_secret()):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    dry_run = str(params.get("dry_run") or "").strip().lower() in {
                        "1",
                        "true",
                        "yes",
                        "on",
                    }
                    try:
                        limit = int(params.get("limit") or 0)
                    except (TypeError, ValueError):
                        limit = 0
                    data, code = backfill_bind_notify(config, dry_run=dry_run, limit=limit)
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
                if route == "/api/admin" or route.startswith("/api/admin/"):
                    return handler.send_json({"error": "admin_not_configured"}, 503)
                params = handler.query()
                payload = handler.read_payload()
                if route == "/api/line/register":
                    data, code = register_line_user(data_file, payload)
                    return handler.send_json(data, code)
                if route == "/api/checkin":
                    line_user_id, err = handler.authenticated_user(payload, params)
                    if err:
                        return handler.send_json(err[0], err[1])
                    data, code = checkin_for_user(
                        data_file, line_user_id, payload, config
                    )
                    return handler.send_json(data, code)
                if route == "/api/onboarding/reminder":
                    line_user_id, err = handler.authenticated_user(payload, params)
                    if err:
                        return handler.send_json(err[0], err[1])
                    data, code = update_onboarding_reminder(
                        data_file, line_user_id, payload
                    )
                    return handler.send_json(data, code)
                if route == "/api/onboarding/complete":
                    line_user_id, err = handler.authenticated_user(payload, params)
                    if err:
                        return handler.send_json(err[0], err[1])
                    data, code = complete_onboarding_for_user(
                        data_file, line_user_id, payload
                    )
                    return handler.send_json(data, code)
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
                    line_user_id, err = handler.authenticated_user(payload, params)
                    if err:
                        return handler.send_json(err[0], err[1])
                    payload["line_user_id"] = line_user_id
                    data, code = save_calendar_note(data_file, payload)
                    return handler.send_json(data, code)
                if route == "/api/smart-reminders":
                    line_user_id, err = handler.authenticated_user(payload, params)
                    if err:
                        return handler.send_json(err[0], err[1])
                    payload["line_user_id"] = line_user_id
                    data, code = save_smart_reminder(data_file, payload)
                    return handler.send_json(data, code)
                if route in {
                    "/api/cron/smart-reminders",
                    "/api/cron/birthday-reminders",
                }:
                    if not cron_allowed(config, handler.cron_secret()):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    task = (
                        send_smart_reminders
                        if route.endswith("smart-reminders")
                        else send_birthday_reminders
                    )
                    data, code = task(config)
                    return handler.send_json(data, code)
                if route == "/api/emergency-contact/bind":
                    line_user_id, err = handler.authenticated_user(payload, params)
                    if err:
                        return handler.send_json(err[0], err[1])
                    payload["contact_line_user_id"] = line_user_id
                    data, code = bind_emergency_contact(data_file, payload, config)
                    return handler.send_json(data, code)
                if route == "/api/emergency-contact/invite":
                    line_user_id, err = handler.authenticated_user(payload, params)
                    if err:
                        return handler.send_json(err[0], err[1])
                    data, code = create_guardian_invite(
                        data_file, line_user_id, payload
                    )
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
                    data, code = update_location(data_file, payload, config)
                    return handler.send_json(data, code)
                if route == "/api/location/stop":
                    data, code = stop_location_sharing(data_file, payload)
                    return handler.send_json(data, code)
                if route == "/api/sos":
                    data, code = trigger_sos(data_file, payload, config)
                    return handler.send_json(data, code)
                if route == "/api/sos/cancel":
                    data, code = cancel_sos_event(data_file, payload, config)
                    return handler.send_json(data, code)
                if route == "/api/sos/retry":
                    data, code = retry_sos_event(data_file, payload, config)
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
                if route == "/api/cron/tick":
                    if not cron_allowed(config, handler.cron_secret()):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    data, code = run_cron_tick(config)
                    return handler.send_json(data, code)
                if route == "/api/cron/contact-reminders":
                    if not cron_allowed(config, handler.cron_secret()):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    data, code = send_missing_contact_reminders(config)
                    return handler.send_json(data, code)
                if route == "/api/cron/checkin-reminders":
                    if not cron_allowed(config, handler.cron_secret()):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    mode = str(params.get("mode", "") or "").strip().lower()
                    force = str(params.get("force", "") or "").strip().lower() in {"1", "true", "yes", "on"}
                    if mode in {"broadcast", "repush", "all"} or force:
                        data, code = broadcast_checkin_reminders(config)
                    else:
                        data, code = send_checkin_reminders(config)
                    return handler.send_json(data, code)
                if route == "/api/cron/checkin-broadcast":
                    if not cron_allowed(config, handler.cron_secret()):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    data, code = broadcast_checkin_reminders(config)
                    return handler.send_json(data, code)
                if route == "/api/cron/renewal-reminders":
                    if not cron_allowed(config, handler.cron_secret()):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    data, code = send_renewal_reminders(config)
                    return handler.send_json(data, code)
                if route == "/api/cron/data-cleanup":
                    if not cron_allowed(config, handler.cron_secret()):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    data, code = cleanup_expired_data(config)
                    return handler.send_json(data, code)
                if route == "/api/cron/backfill-bind-notify":
                    if not cron_allowed(config, handler.cron_secret()):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    dry_run = str(
                        params.get("dry_run") or payload.get("dry_run") or ""
                    ).strip().lower() in {"1", "true", "yes", "on"}
                    try:
                        limit = int(params.get("limit") or payload.get("limit") or 0)
                    except (TypeError, ValueError):
                        limit = 0
                    data, code = backfill_bind_notify(config, dry_run=dry_run, limit=limit)
                    return handler.send_json(data, code)
                if route == "/api/admin/user-plan":
                    if not admin_allowed(config, params.get("password", "")):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    data, code = admin_update_user_plan(data_file, payload)
                    return handler.send_json(data, code)
                if route == "/api/admin/set-core-guardian":
                    if not admin_allowed(config, params.get("password", "")):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    data, code = admin_set_core_guardian(data_file, payload)
                    return handler.send_json(data, code)
                handler.send_json({"error": "not found"}, 404)

        print("Flask is not installed. Using the built-in fallback server.")
        print(f"Open http://{host}:{port}")
        ThreadingHTTPServer((host, port), Handler).serve_forever()


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=True)
