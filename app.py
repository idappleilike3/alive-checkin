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


# 逾時未報平安：會員可選 24／36／48／72 小時，預設 48 小時。
ALLOWED_GRACE_HOURS = (24, 36, 48, 72)
DEFAULT_GRACE_HOURS = 48
# 滿 N 小時後另有短暫可取消預警緩衝（分鐘）；通知實際在 deadline + 此值之後
DEFAULT_WARNING_CANCEL_MINUTES = 15
# 連續未報平安滿 grace_hours 後，等待本人回應的時間；之後才通知第一順位，
# 第二、第三順位分別再依此分鐘數遞進。
ALLOWED_OVERDUE_WAIT_MINUTES = (15, 30, 60)
DEFAULT_OVERDUE_WAIT_MINUTES = 15


def normalize_grace_hours(value, default=DEFAULT_GRACE_HOURS):
    """Clamp／對齊到允許的 24／36／48／72 小時。"""
    try:
        hours = int(value)
    except (TypeError, ValueError):
        return int(default)
    if hours in ALLOWED_GRACE_HOURS:
        return hours
    # 就近；並列時偏向產品預設 48
    return min(ALLOWED_GRACE_HOURS, key=lambda h: (abs(h - hours), abs(h - int(default))))


def normalize_overdue_wait_minutes(value, default=DEFAULT_OVERDUE_WAIT_MINUTES):
    """對齊到 15／30／60 分鐘；無效值使用 15 分鐘預設。"""
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
            "A：可在會員中心選 24／36／48／72 小時（預設 48 小時）。滿設定時數才再提醒本人；15 分鐘仍未回報，之後依第一、第二、第三順位逐步通知守護人。\n\n"
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
    pending_invites = pending_guardian_invite_count(state, line_user_id)
    completed_steps = {
        # 此 API 只有完成 LINE 登入並建立後端會員後才能取得。
        "line_login": bool(profile),
        "profile_and_reminder": bool(
            profile.get("onboarding_reminder_configured")
        ),
        # 後端確實有待接受邀請，或已完成綁定，才算分享步驟完成。
        "guardian_invite_sent": bool(pending_invites or access["home_ready"]),
        "guardian_bound": bool(access["home_ready"]),
    }
    if not completed_steps["profile_and_reminder"]:
        current_step = 2
    elif not completed_steps["guardian_invite_sent"]:
        current_step = 3
    else:
        current_step = 4
    binding_status = (
        "bound"
        if completed_steps["guardian_bound"]
        else "waiting_for_guardian"
        if completed_steps["guardian_invite_sent"]
        else "waiting_for_invite"
    )
    return {
        "ok": True,
        **access,
        "line_user_id": line_user_id,
        "is_onboarding_completed": access["home_ready"],
        "setup_completed": access["home_ready"],
        "has_guardian": has_guardian,
        "guardian_count": len(contacts),
        "pending_guardian_invite_count": pending_invites,
        "completed_steps": completed_steps,
        "current_step": current_step,
        "binding_status": binding_status,
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
    profile = users.get(str(line_user_id or "").strip())
    if not isinstance(profile, dict):
        raise ValueError("member_not_found")
    if (
        profile.get("membership_source") == "beta"
        and profile.get("beta_cohort") == cohort
        and not profile.get("beta_revoked_at")
    ):
        return {
            "assigned": False,
            "idempotent": True,
            "cohort": cohort,
            "line_user_id": line_user_id,
        }
    used_source = free_eligibility_source(profile)
    # A public 14-day trial is the 199-plan preview. If the same member later
    # joins a capped 21-day beta cohort, upgrade the existing profile in place:
    # keep guardians/settings/history and replace only the active entitlement.
    # Previous beta participation and other free entitlements remain one-time.
    beta_upgrade_sources = {"public_trial", "transition_trial"}
    if used_source and used_source not in beta_upgrade_sources:
        raise ValueError("free_eligibility_already_used")
    active_count = sum(
        1
        for row in users.values()
        if isinstance(row, dict)
        and row.get("membership_source") == "beta"
        and row.get("beta_cohort") == cohort
        and not row.get("beta_revoked_at")
    )
    if active_count >= BETA_COHORT_LIMITS[cohort]:
        raise ValueError("cohort_full")
    now = now or current_app_time({})
    profile["membership_source"] = "beta"
    profile["free_eligibility_source"] = f"beta_{cohort}"
    profile["free_eligibility_used_at"] = now.isoformat(timespec="seconds")
    profile["plan"] = BETA_COHORT_PLAN[cohort]
    profile["payment_status"] = "beta"
    profile["beta_cohort"] = cohort
    profile["beta_started_at"] = now.isoformat(timespec="seconds")
    profile["beta_ends_at"] = (
        now + timedelta(days=BETA_TRIAL_DAYS)
    ).isoformat(timespec="seconds")
    if not profile.get("reminder_times"):
        apply_reminder_times_to_profile(profile)
    profile["beta_recruitment_source"] = str(recruitment_source or "").strip()[:80]
    profile["beta_feedback_status"] = "pending"
    profile["beta_revoked_at"] = None
    profile["trial_bonus_days"] = 0
    state.setdefault("beta_audit", []).append({
        "action": "assign",
        "line_user_id": str(line_user_id),
        "cohort": cohort,
        "at": now.isoformat(timespec="seconds"),
    })
    return {
        "assigned": True,
        "idempotent": False,
        "cohort": cohort,
        "line_user_id": line_user_id,
        "ends_at": profile["beta_ends_at"],
    }


def claim_beta_link(state, line_user_id, cohort, *, now=None):
    """Claim a public capped beta link once; never switch an active member's cohort."""
    member_id = str(line_user_id or "").strip()
    normalized = str(cohort or "").strip().upper()
    profile = (state.get("users") or {}).get(member_id)
    if not isinstance(profile, dict):
        raise ValueError("member_not_found")
    existing = str(profile.get("beta_cohort") or "").strip().upper()
    if (
        existing
        and existing != normalized
        and not profile.get("beta_revoked_at")
    ):
        raise ValueError("already_in_other_cohort")
    return assign_beta_cohort(
        state,
        member_id,
        normalized,
        now=now,
        recruitment_source=f"public-link-{normalized.lower()}",
    )


def revoke_beta_cohort(state, line_user_id, *, now=None):
    """Revoke beta rights while retaining member and guardian data."""
    profile = (state.get("users") or {}).get(str(line_user_id or "").strip())
    if not isinstance(profile, dict):
        raise ValueError("member_not_found")
    now = now or current_app_time({})
    if profile.get("beta_revoked_at"):
        return {"revoked": False, "idempotent": True}
    profile["beta_revoked_at"] = now.isoformat(timespec="seconds")
    profile["membership_source"] = "expired"
    profile["payment_status"] = "expired"
    profile["plan"] = "free"
    mark_entitlement_lapsed(profile, now)
    state.setdefault("beta_audit", []).append({
        "action": "revoke",
        "line_user_id": str(line_user_id),
        "cohort": profile.get("beta_cohort"),
        "at": now.isoformat(timespec="seconds"),
    })
    return {"revoked": True, "idempotent": False}


def beta_members_snapshot(state, now=None):
    """Sanitized beta roster and exact cohort counters for the admin UI."""
    now = now or current_app_time({})
    rows = []
    counts = {key: 0 for key in BETA_COHORT_LIMITS}
    for profile in (state.get("users") or {}).values():
        cohort = str(profile.get("beta_cohort") or "")
        if cohort not in BETA_COHORT_LIMITS:
            continue
        if beta_access_active(profile, now):
            counts[cohort] += 1
        ends = parse_datetime(profile.get("beta_ends_at"))
        started = parse_datetime(profile.get("beta_started_at"))
        remaining = max(0, int(((ends - now).total_seconds() + 86399) // 86400)) if ends else 0
        current_day = (
            min(BETA_TRIAL_DAYS, max(1, (now.date() - started.date()).days + 1))
            if started else 0
        )
        rows.append({
            "line_user_id": str(profile.get("line_user_id") or ""),
            "display_name": str(profile.get("display_name") or "未命名會員"),
            "cohort": cohort,
            "plan": str(profile.get("plan") or ""),
            "source": str(profile.get("beta_recruitment_source") or ""),
            "started_at": profile.get("beta_started_at"),
            "ends_at": profile.get("beta_ends_at"),
            "remaining_days": remaining,
            "current_day": current_day,
            "milestones": {
                "day_1": current_day >= 1,
                "day_7": current_day >= 7,
                "day_14": current_day >= 14,
                "day_21": current_day >= 21,
            },
            "feedback_status": str(profile.get("beta_feedback_status") or "pending"),
            "feedback_last_day": int(profile.get("beta_feedback_last_day") or 0),
            "feedback_last_at": str(profile.get("beta_feedback_last_at") or ""),
            "guardian_count": len([
                item for item in (profile.get("contacts") or [])
                if contact_is_bound_guardian(item)
            ]),
            "reminder_setup": bool(profile.get("reminder_times") or profile.get("reminder_time")),
            "push_result": str(profile.get("beta_push_result") or ""),
            "sos_test_status": str(profile.get("beta_sos_test_status") or ""),
            "revoked": bool(profile.get("beta_revoked_at")),
            "active": beta_access_active(profile, now),
        })
    return {
        "limits": dict(BETA_COHORT_LIMITS),
        "counts": counts,
        "total_active": sum(counts.values()),
        "members": sorted(rows, key=lambda row: (row["cohort"], row["display_name"])),
        "notice": "封閉測試不會建立訂單，也不會自動扣款",
    }


def _beta_feedback_task(cohort, day):
    common = {
        1: "完成一次「我平安」，確認本人與守護人都看到正確結果",
        7: "檢查提醒時間、逾時通知與守護人收訊是否清楚",
        14: "測試 SOS 的送出、取消及收件人提示",
        21: "提交整體心得，告訴我們最想保留與改善的功能",
    }
    if int(day or 0) in common:
        return common[int(day)]
    if str(cohort or "").upper() == "B799":
        return "測試家庭群組、多人守護、安全守護或 SOS，並確認通知對象正確"
    return "使用一次報平安、提醒、守護人或 SOS，留意操作是否容易理解"


def build_beta_feedback_flex(profile, day):
    """Build one daily beta question with five explicit reply paths."""
    day = max(1, min(BETA_TRIAL_DAYS, int(day or 1)))
    cohort = str((profile or {}).get("beta_cohort") or "B399").upper()
    buttons = [
        ("使用正常", "normal", "#168C65"),
        ("發現問題", "issue", "#C2413A"),
        ("使用心得", "insight", "#3178C6"),
        ("不會操作", "help", "#8A5A16"),
        ("稍後提醒", "later", "#6B7280"),
    ]
    return {
        "type": "flex",
        "altText": f"每日平安封測 Day {day} 使用狀況詢問",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#168C65",
                "contents": [
                    {"type": "text", "text": f"21 天封測 Day {day}", "color": "#FFFFFF",
                     "weight": "bold", "size": "xl"},
                    {"type": "text", "text": "今天使用上有遇到問題嗎？",
                     "color": "#EAF8F1", "margin": "sm"},
                ],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "今日建議任務", "weight": "bold",
                     "color": "#168C65"},
                    {"type": "text", "text": _beta_feedback_task(cohort, day),
                     "wrap": True, "margin": "sm", "color": "#33443F"},
                    {"type": "text", "text": "點選下方最符合的狀況即可回報",
                     "wrap": True, "margin": "lg", "size": "sm", "color": "#6B7773"},
                ],
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "button",
                        "style": "primary",
                        "color": color,
                        "height": "sm",
                        "action": {
                            "type": "postback",
                            "label": label,
                            "data": f"beta_feedback:{kind}:{day}",
                            "displayText": label,
                        },
                    }
                    for label, kind, color in buttons
                ],
            },
        },
    }


def send_beta_daily_feedback(config, now=None):
    """At 19:00 Taipei time, push one beta question per active member per day."""
    clock = now or current_app_time(config)
    if clock.strftime("%H:%M") != "19:00":
        return {"sent": 0, "skipped": 0, "reason": "not_1900"}, 200
    token = config.get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get(
        "LINE_CHANNEL_ACCESS_TOKEN", ""
    )
    if not token:
        return {"sent": 0, "skipped": 0, "error": "LINE_CHANNEL_ACCESS_TOKEN is not set"}, 400
    sender = config.get("LINE_PUSH_SENDER") or line_push_message
    state = load_state(config["DATA_FILE"])
    today = clock.date().isoformat()
    sent = 0
    skipped = 0
    for profile in (state.get("users") or {}).values():
        target = str(profile.get("line_user_id") or "").strip()
        if (
            not target
            or not beta_access_active(profile, clock)
            or profile.get("beta_feedback_last_push_date") == today
        ):
            skipped += 1
            continue
        started = parse_datetime(profile.get("beta_started_at"))
        day = min(BETA_TRIAL_DAYS, max(1, (clock.date() - started.date()).days + 1))
        message = build_beta_feedback_flex(profile, day)
        try:
            result = sender(token, target, message)
            profile["beta_feedback_last_push_date"] = today
            profile["beta_feedback_last_push_at"] = clock.isoformat(timespec="seconds")
            profile["beta_feedback_last_push_day"] = day
            append_notification_log(
                state, "beta_daily_feedback", target, "sent",
                message.get("altText"), json.dumps(result, ensure_ascii=False),
            )
            sent += 1
        except Exception as exc:
            append_notification_log(
                state, "beta_daily_feedback", target, "failed",
                message.get("altText"), str(exc)[:400],
            )
            skipped += 1
    save_state(config["DATA_FILE"], state)
    return {"sent": sent, "skipped": skipped, "date": today}, 200


def handle_beta_feedback_postback(data_file, line_user_id, data, now=None):
    parts = str(data or "").split(":")
    if len(parts) != 3 or parts[0] != "beta_feedback":
        return None
    kind = parts[1]
    if kind not in {"normal", "issue", "insight", "help", "later"}:
        return None
    try:
        day = max(1, min(BETA_TRIAL_DAYS, int(parts[2])))
    except (TypeError, ValueError):
        return None
    clock = now or current_app_time({})
    state = load_state(data_file)
    profile = (state.get("users") or {}).get(str(line_user_id or ""))
    if not profile or str(profile.get("membership_source") or "") != "beta":
        return "此回報只提供給目前的封測會員"
    profile["beta_feedback_status"] = kind
    profile["beta_feedback_last_day"] = day
    profile["beta_feedback_last_at"] = clock.isoformat(timespec="seconds")
    state.setdefault("beta_feedback_reports", []).append({
        "line_user_id": str(line_user_id),
        "cohort": str(profile.get("beta_cohort") or ""),
        "day": day,
        "kind": kind,
        "created_at": profile["beta_feedback_last_at"],
    })
    state["beta_feedback_reports"] = state["beta_feedback_reports"][-2000:]
    save_state(data_file, state)
    if kind == "issue":
        return (
            "已記錄「發現問題」。請直接在這個聊天室傳送：\n"
            "1. 問題截圖\n2. 發生時間\n3. 操作步驟\n"
            "4. 手機型號\n5. LINE 版本"
        )
    if kind == "insight":
        return "已記錄「使用心得」。請直接告訴我們哪裡好用、哪裡想改善"
    if kind == "help":
        return "已記錄「不會操作」。請告訴我們卡在哪個畫面，客服會協助你"
    if kind == "later":
        return "好的，今天不再重複推播；你方便時再回到這個聊天室告訴我們"
    return "謝謝回報，已記錄今天使用正常"


LINE_ACCEPTANCE_KINDS = (
    "direct_message",
    "family_group",
    "sos",
    "sos_cancel",
    "sos_escalation",
    "sos_retry",
    "abuse_block",
    "group_member_change",
)
LINE_ACCEPTANCE_REQUIREMENTS = {
    "A": list(LINE_ACCEPTANCE_KINDS),
    "B399": ["direct_message", "sos", "sos_cancel", "sos_retry", "abuse_block"],
    "B799": list(LINE_ACCEPTANCE_KINDS),
}


def _masked_line_ref(value):
    raw = str(value or "").strip()
    if len(raw) <= 6:
        return "***"
    return f"{raw[:3]}…{raw[-3:]}"


def line_acceptance_snapshot(state, now=None):
    rows = []
    counts = {"pending": 0, "passed": 0, "failed": 0}
    for stored in state.get("line_acceptance_cases") or []:
        if not isinstance(stored, dict):
            continue
        row = dict(stored)
        row.pop("line_user_id", None)
        status = str(row.get("manual_status") or "pending")
        if status not in counts:
            status = "pending"
            row["manual_status"] = status
        counts[status] += 1
        rows.append(row)
    rows.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return {
        "kinds": list(LINE_ACCEPTANCE_KINDS),
        "requirements": copy.deepcopy(LINE_ACCEPTANCE_REQUIREMENTS),
        "counts": counts,
        "cases": rows,
        "notice": "本工具只記錄既有 LINE 測試證據，不會主動發送訊息",
    }


def create_line_acceptance_case(state, payload, now=None):
    payload = dict(payload or {})
    line_user_id = str(payload.get("line_user_id") or "").strip()
    kind = str(payload.get("kind") or "").strip()
    if kind not in LINE_ACCEPTANCE_KINDS:
        raise ValueError("invalid_acceptance_kind")
    profile = (state.get("users") or {}).get(line_user_id)
    if not profile or not beta_access_active(profile, now):
        raise ValueError("beta_member_required")
    cohort = str(profile.get("beta_cohort") or "")
    if kind not in LINE_ACCEPTANCE_REQUIREMENTS.get(cohort, []):
        raise ValueError("kind_not_required_for_cohort")
    clock = now or datetime.now()
    case = {
        "case_id": f"line-acceptance-{uuid.uuid4().hex}",
        "line_user_id": line_user_id,
        "member_ref": _masked_line_ref(line_user_id),
        "display_name": str(profile.get("display_name") or "封測會員")[:80],
        "cohort": cohort,
        "kind": kind,
        "system_status": "awaiting_evidence",
        "manual_status": "pending",
        "note": "",
        "created_at": clock.isoformat(timespec="seconds"),
        "reviewed_at": None,
    }
    state.setdefault("line_acceptance_cases", []).append(case)
    state["line_acceptance_cases"] = state["line_acceptance_cases"][-500:]
    return {"created": True, "case": {k: v for k, v in case.items() if k != "line_user_id"}}


def review_line_acceptance_case(state, case_id, payload, now=None):
    manual_status = str((payload or {}).get("manual_status") or "").strip()
    if manual_status not in {"passed", "failed"}:
        raise ValueError("invalid_manual_status")
    note = str((payload or {}).get("note") or "").strip()
    if len(note) > 500:
        raise ValueError("note_too_long")
    target = next(
        (
            row for row in state.get("line_acceptance_cases") or []
            if isinstance(row, dict) and row.get("case_id") == case_id
        ),
        None,
    )
    if target is None:
        raise ValueError("acceptance_case_not_found")
    clock = now or datetime.now()
    target["manual_status"] = manual_status
    target["note"] = note
    target["reviewed_at"] = clock.isoformat(timespec="seconds")
    public = dict(target)
    public.pop("line_user_id", None)
    return {"reviewed": True, "case": public}


def admin_assign_beta_member(data_file, payload, now=None):
    try:
        result = mutate_state_atomically(
            data_file,
            lambda state: {
                **assign_beta_member_with_release_gate(
                    state,
                    payload.get("line_user_id"),
                    payload.get("cohort"),
                    now=now,
                    recruitment_source=payload.get("source") or "",
                ),
                "beta": beta_members_snapshot(state, now),
            },
        )
    except ValueError as exc:
        error = str(exc)
        conflict_errors = {
            "cohort_full",
            "a_cohort_incomplete",
            "a_cohort_not_mature",
            "readiness_blocked",
            "first_release_max_10",
            "wait_until_next_day",
            "remaining_release_max_20",
            "second_stage_max_30",
        }
        return {"ok": False, "error": error}, (
            404 if error == "member_not_found" else 409 if error in conflict_errors else 400
        )
    return {"ok": True, **result}, 200


def admin_revoke_beta_member(data_file, line_user_id, now=None):
    try:
        result = mutate_state_atomically(
            data_file,
            lambda state: {
                **revoke_beta_cohort(state, line_user_id, now=now),
                "beta": beta_members_snapshot(state, now),
            },
        )
    except ValueError:
        return {"ok": False, "error": "member_not_found"}, 404
    return {"ok": True, **result}, 200


def launch_readiness_snapshot(state, now=None):
    """Quantified launch gates used to stop unsafe beta expansion."""
    metrics = dict(state.get("launch_metrics") or {})
    launch_events = [
        row for row in (state.get("launch_events") or [])
        if isinstance(row, dict)
    ]
    checkin_events = [
        row for row in launch_events if row.get("kind") == "checkin"
    ]
    if checkin_events:
        metrics["checkin_attempts"] = len(checkin_events)
        metrics["checkin_successes"] = sum(
            1 for row in checkin_events if row.get("success")
        )
    reminder_logs = [
        row for row in (state.get("notification_logs") or [])
        if isinstance(row, dict)
        and row.get("kind") in {"checkin", "overdue", "contact_alert"}
    ]
    if reminder_logs:
        reminder_keys = {
            (
                row.get("kind"),
                row.get("line_user_id"),
                str(row.get("message") or ""),
            )
            for row in reminder_logs
        }
        sent_keys = {
            (
                row.get("kind"),
                row.get("line_user_id"),
                str(row.get("message") or ""),
            )
            for row in reminder_logs
            if row.get("status") == "sent"
        }
        metrics["required_reminders"] = len(reminder_keys)
        metrics["sent_required_reminders"] = len(sent_keys)
    delivery_events = [
        row for row in (state.get("launch_delivery_events") or {}).values()
        if isinstance(row, dict) and row.get("expected")
    ]
    if delivery_events:
        metrics["required_reminders"] = len(delivery_events)
        metrics["sent_required_reminders"] = sum(
            1 for row in delivery_events if int(row.get("sent_count") or 0) == 1
        )
        metrics["duplicate_alerts"] = sum(
            1 for row in delivery_events if int(row.get("sent_count") or 0) > 1
        )
    invites = [
        row for row in (state.get("guardian_invites") or [])
        if isinstance(row, dict)
    ]
    if invites:
        metrics["guardian_bind_attempts"] = len(invites)
        metrics["guardian_bind_successes"] = sum(
            1 for row in invites if row.get("status") == "used"
        )
    beta_profiles = [
        profile for profile in (state.get("users") or {}).values()
        if isinstance(profile, dict) and profile.get("membership_source") == "beta"
    ]
    sos_results = [
        str(profile.get("beta_sos_test_status") or "")
        for profile in beta_profiles
        if str(profile.get("beta_sos_test_status") or "")
    ]
    if sos_results:
        metrics["sos_tests"] = len(sos_results)
        metrics["sos_test_successes"] = sum(
            1 for value in sos_results if value in {"sent", "passed", "success"}
        )
    scenarios = state.get("launch_validation_scenarios") or {}
    payment_ok = any(
        row.get("kind") == "payment"
        and LAUNCH_SCENARIO_STEPS["payment"] <= set(row.get("steps") or [])
        for row in scenarios.values()
        if isinstance(row, dict)
    )
    expiry_ok = any(
        row.get("kind") == "expiry"
        and row.get("line_user_id")
        and LAUNCH_SCENARIO_STEPS["expiry"] <= set(row.get("steps") or [])
        for row in scenarios.values()
        if isinstance(row, dict)
    )
    # Payment and expiry are launch blockers.  Only correlated scenario
    # evidence is authoritative; legacy/manual summary booleans must not
    # bypass the acceptance ledger.
    metrics["payment_flow_passed"] = payment_ok
    metrics["expiry_flow_passed"] = expiry_ok
    checkin_attempts = max(0, int(metrics.get("checkin_attempts") or 0))
    checkin_successes = max(0, int(metrics.get("checkin_successes") or 0))
    required = max(0, int(metrics.get("required_reminders") or 0))
    sent_required = max(0, int(metrics.get("sent_required_reminders") or 0))
    sos_tests = max(0, int(metrics.get("sos_tests") or 0))
    sos_successes = max(0, int(metrics.get("sos_test_successes") or 0))
    bind_attempts = max(0, int(metrics.get("guardian_bind_attempts") or 0))
    bind_successes = max(0, int(metrics.get("guardian_bind_successes") or 0))
    failures = [
        {
            "category": str(row.get("category") or ""),
            "reason": str(row.get("reason") or "")[:200],
            "critical": bool(row.get("critical")),
        }
        for row in (state.get("push_failures") or [])
        if isinstance(row, dict)
    ]
    for row in reminder_logs:
        if row.get("status") not in {"failed", "retry", "blocked"}:
            continue
        failures.append({
            "category": str(row.get("kind") or ""),
            "reason": str(row.get("detail") or row.get("status") or "")[:200],
            "critical": True,
        })
    for row in delivery_events:
        if not row.get("failed") and int(row.get("sent_count") or 0) == 1:
            continue
        failures.append({
            "category": str(row.get("kind") or ""),
            "reason": (
                "duplicate_delivery"
                if int(row.get("sent_count") or 0) > 1
                else "required_delivery_failed_or_missing"
            ),
            "critical": True,
        })
    checkin_rate = checkin_successes / checkin_attempts if checkin_attempts else 0.0
    sos_rate = sos_successes / sos_tests if sos_tests else 0.0
    bind_rate = bind_successes / bind_attempts if bind_attempts else 0.0
    missed = max(0, required - sent_required)
    duplicate_alerts = max(0, int(metrics.get("duplicate_alerts") or 0))
    critical_miss = missed > 0 or any(row["critical"] for row in failures)
    payment_ok = metrics.get("payment_flow_passed") is True
    expiry_ok = metrics.get("expiry_flow_passed") is True
    ready = all([
        checkin_rate >= 0.99,
        missed == 0,
        duplicate_alerts == 0,
        sos_rate >= 1.0,
        bind_rate >= 0.95,
        payment_ok,
        expiry_ok,
        not critical_miss,
    ])
    return {
        "checkin_success_rate": round(checkin_rate, 4),
        "missed_required_reminders": missed,
        "duplicate_alerts": duplicate_alerts,
        "sos_test_success_rate": round(sos_rate, 4),
        "guardian_bind_success_rate": round(bind_rate, 4),
        "payment_flow_passed": payment_ok,
        "expiry_flow_passed": expiry_ok,
        "push_failures": failures,
        "critical_notification_miss": critical_miss,
        "ready": ready,
    }


def record_launch_validation_step(
    state, scenario_id, kind, step, *, line_user_id="", now=None
):
    scenario_id = str(scenario_id or "").strip()
    kind = str(kind or "").strip()
    step = str(step or "").strip()
    if not scenario_id or kind not in LAUNCH_SCENARIO_STEPS:
        raise ValueError("invalid_launch_scenario")
    if step not in LAUNCH_SCENARIO_STEPS[kind]:
        raise ValueError("invalid_launch_step")
    scenarios = state.setdefault("launch_validation_scenarios", {})
    row = scenarios.setdefault(scenario_id, {
        "kind": kind,
        "line_user_id": str(line_user_id or "").strip(),
        "steps": [],
    })
    if row.get("kind") != kind:
        raise ValueError("launch_scenario_kind_conflict")
    if kind == "expiry" and not (
        str(line_user_id or "").strip() or row.get("line_user_id")
    ):
        raise ValueError("line_user_id_required")
    if line_user_id:
        if row.get("line_user_id") not in {"", str(line_user_id)}:
            raise ValueError("launch_scenario_member_conflict")
        row["line_user_id"] = str(line_user_id)
    row["steps"] = sorted(set(row.get("steps") or []) | {step})
    row["updated_at"] = (now or current_app_time({})).isoformat(timespec="seconds")
    return copy.deepcopy(row)


def beta_release_allowed(state, requested_count, now=None):
    now = now or current_app_time({})
    requested_count = max(0, int(requested_count or 0))
    snapshot = launch_readiness_snapshot(state, now)
    if not snapshot["ready"]:
        return False, "readiness_blocked"
    released = sum(
        1
        for profile in (state.get("users") or {}).values()
        if isinstance(profile, dict)
        and profile.get("membership_source") == "beta"
        and profile.get("beta_cohort") in {"B399", "B799"}
        and not profile.get("beta_revoked_at")
    )
    remaining = max(0, 30 - released)
    return (
        (True, "second_stage_allowed")
        if 0 < requested_count <= remaining
        else (False, "second_stage_max_30")
    )


def assign_beta_member_with_release_gate(
    state,
    line_user_id,
    cohort,
    *,
    now=None,
    recruitment_source="",
):
    """Apply the A-day-7 and quantified rollout gates before any B activation."""
    clock = now or current_app_time({})
    cohort = str(cohort or "").strip().upper()
    profile = (state.get("users") or {}).get(str(line_user_id or "").strip())
    if (
        isinstance(profile, dict)
        and profile.get("membership_source") == "beta"
        and profile.get("beta_cohort") == cohort
        and not profile.get("beta_revoked_at")
    ):
        return assign_beta_cohort(
            state,
            line_user_id,
            cohort,
            now=clock,
            recruitment_source=recruitment_source,
        )
    if cohort in {"B399", "B799"}:
        a_started = [
            parse_datetime(profile.get("beta_started_at"))
            for profile in (state.get("users") or {}).values()
            if isinstance(profile, dict)
            and profile.get("membership_source") == "beta"
            and profile.get("beta_cohort") == "A"
            and not profile.get("beta_revoked_at")
        ]
        valid_a_started = [value for value in a_started if value]
        if len(valid_a_started) < BETA_COHORT_LIMITS["A"]:
            raise ValueError("a_cohort_incomplete")
        if min(valid_a_started) > clock - timedelta(days=7):
            raise ValueError("a_cohort_not_mature")
        allowed, reason = beta_release_allowed(state, 1, now=clock)
        if not allowed:
            raise ValueError(reason)
    result = assign_beta_cohort(
        state,
        line_user_id,
        cohort,
        now=clock,
        recruitment_source=recruitment_source,
    )
    if cohort in {"B399", "B799"} and result.get("assigned"):
        state.setdefault("beta_release_history", []).append({
            "batch": "B",
            "cohort": cohort,
            "count": 1,
            "line_user_id": str(line_user_id),
            "released_at": clock.isoformat(timespec="seconds"),
        })
    return result


def trial_days_left(profile, now=None):
    trial_end = parse_datetime(profile.get("trial_end"))
    if trial_end:
        remaining_seconds = (trial_end - (now or current_app_time({}))).total_seconds()
        return max(0, int((remaining_seconds + 86399) // 86400))
    started_at = parse_datetime(profile.get("trial_started_at"))
    total = trial_total_days(profile)
    if not started_at:
        return total
    elapsed_days = ((now or current_app_time({})) - started_at).days
    return max(0, total - elapsed_days)


def trial_active(profile):
    return membership_access_active(profile)


def clear_contacts_retain_window(profile):
    """Restore service pause flags while keeping every relationship."""
    if not isinstance(profile, dict):
        return
    profile["plan_expired_at"] = ""
    profile["contacts_retain_until"] = ""
    was_paused = bool(profile.get("membership_paused") or profile.get("scheduled_notifications_paused"))
    profile["membership_paused"] = False
    profile["scheduled_notifications_paused"] = False
    if was_paused:
        profile["daily_checkin_reminder_enabled"] = True


def mark_entitlement_lapsed(profile, now):
    """Pause paid services at expiry while retaining relationships indefinitely."""
    if not isinstance(profile, dict):
        return
    stamp = now.isoformat(timespec="seconds")
    if not str(profile.get("plan_expired_at") or "").strip():
        profile["plan_expired_at"] = stamp
    if "daily_checkin_reminder_enabled_before_expiry" not in profile:
        profile["daily_checkin_reminder_enabled_before_expiry"] = bool(
            profile.get("daily_checkin_reminder_enabled", True)
        )
    profile["contacts_retain_until"] = ""
    profile["membership_paused"] = True
    profile["daily_checkin_reminder_enabled"] = False
    profile["scheduled_notifications_paused"] = True
    location = dict(profile.get("location") or {})
    if location:
        location["active"] = False
        location["sharing"] = False
        location["ended_at"] = stamp
        profile["location"] = location


def contacts_retain_days_left(profile, now=None):
    retain_until = parse_datetime(profile.get("contacts_retain_until"))
    if not retain_until:
        return None
    clock = now or datetime.now()
    return max(0, (retain_until.date() - clock.date()).days)


def soft_archive_contacts_past_retain(profile, now):
    """Relationships are never auto-archived merely because a plan expired."""
    return False


def restore_legacy_auto_archived_contacts(profile):
    """Migrate legacy expiry archives back to permanent active storage."""
    if not isinstance(profile, dict):
        return False
    archived = profile.get("contacts_archived") or []
    had_deadline = bool(str(profile.get("contacts_retain_until") or "").strip())
    if archived:
        profile["contacts"] = _merge_migration_records(
            profile.get("contacts"),
            archived,
            ("id", "accepted_invite_id", "invite_id"),
            "contact",
        )
    profile["contacts_retain_until"] = ""
    profile["contacts_archived"] = []
    return bool(archived or had_deadline)


def restore_membership_after_renewal(profile, plan, paid_until, now=None):
    """Restore paid service flags without requiring guardian re-invitation."""
    now = now or current_app_time({})
    profile["plan"] = str(plan)
    profile["membership_source"] = "paid"
    profile["payment_status"] = "active"
    profile["paid_until"] = (
        paid_until.isoformat(timespec="seconds")
        if isinstance(paid_until, datetime)
        else str(paid_until or "")
    )
    profile["membership_paused"] = False
    profile["scheduled_notifications_paused"] = False
    profile["daily_checkin_reminder_enabled"] = bool(
        profile.pop("daily_checkin_reminder_enabled_before_expiry", True)
    )
    profile["renewed_at"] = now.isoformat(timespec="seconds")
    clear_contacts_retain_window(profile)
    return profile


def process_verified_privacy_request(
    state,
    line_user_id,
    request_type,
    *,
    peer_line_user_id="",
    now=None,
):
    """Process a verified unlink/delete request and retain minimal legal audit."""
    now = now or current_app_time({})
    line_user_id = str(line_user_id or "").strip()
    request_type = str(request_type or "").strip()
    peer_line_user_id = str(peer_line_user_id or "").strip()
    request_key = hashlib.sha256(
        f"{line_user_id}:{request_type}:{peer_line_user_id}".encode("utf-8")
    ).hexdigest()
    requests = state.setdefault("privacy_requests", [])
    if any(row.get("request_key") == request_key for row in requests):
        return {"processed": True, "idempotent": True, "request_key": request_key}
    if line_user_id not in (state.get("users") or {}):
        raise ValueError("member_not_found")
    if request_type == "unlink_guardian":
        if not peer_line_user_id:
            raise ValueError("peer_required")
        for owner_id, peer_id in (
            (line_user_id, peer_line_user_id),
            (peer_line_user_id, line_user_id),
        ):
            profile = (state.get("users") or {}).get(owner_id)
            if not isinstance(profile, dict):
                continue
            profile["contacts"] = [
                row for row in (profile.get("contacts") or [])
                if not (
                    get_contact_line_id(row) == peer_id
                    and resolve_contact_role(row) == "guardian"
                )
            ]
    elif request_type == "delete_account":
        state["users"].pop(line_user_id, None)
        for profile in state["users"].values():
            profile["friends"] = [
                value for value in (profile.get("friends") or [])
                if value != line_user_id
            ]
            profile["guarding_for"] = [
                value for value in (profile.get("guarding_for") or [])
                if value != line_user_id
            ]
            profile["contacts"] = [
                row for row in (profile.get("contacts") or [])
                if get_contact_line_id(row) != line_user_id
            ]
        for group_id, group in list((state.get("guardian_groups") or {}).items()):
            if str(group.get("owner_line_user_id") or "") == line_user_id:
                state["guardian_groups"].pop(group_id, None)
                continue
            for field in ("admin_line_user_ids", "member_ids_at_bind", "member_line_user_ids"):
                if isinstance(group.get(field), list):
                    group[field] = [
                        value for value in group[field] if value != line_user_id
                    ]
        for key in (
            "guardian_invites",
            "friend_invites",
            "contact_rewards",
            "support_tickets",
            "notification_logs",
            "sos_logs",
            "checkin_warnings",
            "checkin_warning_logs",
        ):
            collection = state.get(key)
            if isinstance(collection, list):
                state[key] = [
                    row for row in collection
                    if not _account_migration_record_references(row, line_user_id)
                ]
            elif isinstance(collection, dict):
                state[key] = {
                    record_id: row for record_id, row in collection.items()
                    if not _account_migration_record_references(row, line_user_id)
                    and record_id != line_user_id
                }
        for key in ("sos_pending", "location_grants", "location_grant_index"):
            collection = state.get(key)
            if isinstance(collection, dict):
                state[key] = {
                    record_id: row for record_id, row in collection.items()
                    if record_id != line_user_id
                    and not _account_migration_record_references(row, line_user_id)
                }
        for order in state.get("orders") or []:
            if str(order.get("line_user_id") or "") == line_user_id:
                order["line_user_id"] = "deleted-user"
                order["display_name"] = "已刪除會員"
                order["personal_data_removed_at"] = now.isoformat(timespec="seconds")
        def contains_deleted_identity(value):
            if isinstance(value, dict):
                return any(
                    str(key) == line_user_id
                    or contains_deleted_identity(item)
                    for key, item in value.items()
                )
            if isinstance(value, (list, tuple, set)):
                return any(contains_deleted_identity(item) for item in value)
            return isinstance(value, str) and value == line_user_id

        # Final graph sweep: operational records have no legal retention basis.
        # Orders and the hashed privacy audit are handled separately above/below.
        for key, collection in list(state.items()):
            if key in {"users", "orders", "privacy_requests"}:
                continue
            if isinstance(collection, list):
                state[key] = [
                    row for row in collection
                    if not contains_deleted_identity(row)
                ]
            elif isinstance(collection, dict):
                state[key] = {
                    record_id: row
                    for record_id, row in collection.items()
                    if str(record_id) != line_user_id
                    and not contains_deleted_identity(row)
                }
    else:
        raise ValueError("unsupported_request_type")
    requests.append({
        "id": f"privacy-{uuid.uuid4().hex[:12]}",
        "request_key": request_key,
        "request_type": request_type,
        "status": "completed",
        "completed_at": now.isoformat(timespec="seconds"),
    })
    return {"processed": True, "idempotent": False, "request_key": request_key}


def apply_invite_trial_reward(inviter, reward, *, accepted_at):
    """記錄守護人綁定，但不提供任何體驗天數獎勵。"""
    if not isinstance(inviter, dict) or not isinstance(reward, dict):
        return False
    if reward.get("status") == "not_applicable":
        return False
    inviter["trial_bonus_days"] = 0
    reward["selected_reward"] = "none"
    reward["status"] = "not_applicable"
    reward["applied_at"] = accepted_at
    reward["reward_days"] = 0
    return False


def plan_type_label(profile):
    plan = str(profile.get("plan") or "trial")
    return {
        "trial": "14 天安心體驗",
        "free": "未訂閱",
        "paid_199": "199 月費",
        "paid_199_year": "199 年費",
        "paid_399": "399 月費",
        "paid_399_year": "399 年費",
        "paid_799": "799 月費",
        "paid_799_year": "799 年費",
    }.get(plan, plan)


def compute_plan_expires_at(profile):
    """回傳方案到期 ISO 字串（試用結束日或付費 paid_until）；未訂閱回空字串。"""
    if str(profile.get("membership_source") or "") == "beta":
        return str(profile.get("beta_ends_at") or "").strip()
    plan = str(profile.get("plan") or "trial")
    if plan.startswith("paid"):
        return str(profile.get("paid_until") or "").strip()
    if plan == "free":
        return ""
    trial_end = str(profile.get("trial_end") or "").strip()
    if trial_end:
        return trial_end
    # 舊資料相容：沒有 trial_end 時，以 trial_started_at + 14 天計算。
    started = parse_datetime(profile.get("trial_started_at"))
    if not started:
        started = datetime.now()
    return (started + timedelta(days=trial_total_days(profile))).isoformat(timespec="seconds")


def plan_expires_text(profile):
    plan = str(profile.get("plan") or "trial")
    label = plan_type_label(profile)
    expires = compute_plan_expires_at(profile)
    if plan == "free":
        return f"{label}｜無到期日"
    if not expires:
        return f"{label}｜尚未設定到期日"
    try:
        dt = parse_datetime(expires) or datetime.fromisoformat(str(expires)[:19])
        date_part = dt.strftime("%Y/%m/%d")
    except Exception:
        date_part = str(expires)[:10].replace("-", "/")
    if plan == "trial":
        days = trial_days_left(profile)
        return f"{label}｜到期 {date_part}（剩 {days} 天）"
    return f"{label}｜到期 {date_part}"


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


def build_status(profile, state=None, now=None):
    profile = {**DEFAULT_PROFILE, **profile}
    scrub_self_line_ids_on_contacts(profile)
    owner_id = str(profile.get("line_user_id") or "").strip()
    # 正規化 contacts：補 contact_role，並去掉會與「核心／一般」混淆的 role 欄
    normalized_contacts = []
    for i, raw in enumerate(profile.get("contacts") or []):
        if not isinstance(raw, dict):
            continue
        row = normalize_contact(raw, i)
        for key, value in raw.items():
            if key == "role":
                continue
            if key not in row and value not in (None, ""):
                row[key] = value
        row["contact_role"] = resolve_contact_role(
            {"contact_role": raw.get("contact_role") or row.get("contact_role")}
        )
        if state is not None:
            enrich_contact_peer_picture(state, row)
            enrich_contact_peer_display_name(state, row)
        normalized_contacts.append(row)
    profile["contacts"] = normalized_contacts
    access = member_access_state(profile)
    now = now or current_app_time({})
    last = parse_last_checkin(profile.get("last_check_in"))
    grace_hours = normalize_grace_hours(profile.get("grace_hours"))
    overdue_wait_minutes = normalize_overdue_wait_minutes(
        profile.get("overdue_wait_minutes")
    )
    warning_cancel_minutes = int(
        profile.get("warning_cancel_minutes") or DEFAULT_WARNING_CANCEL_MINUTES
    )
    active_overdue = profile.get("active_overdue_event")
    overdue_started_at = (
        parse_datetime(active_overdue.get("started_at"))
        if isinstance(active_overdue, dict) and not active_overdue.get("resolved_at")
        else None
    )
    if overdue_started_at and now.tzinfo is None and overdue_started_at.tzinfo is not None:
        overdue_started_at = overdue_started_at.replace(tzinfo=None)
    elif overdue_started_at and now.tzinfo is not None and overdue_started_at.tzinfo is None:
        overdue_started_at = overdue_started_at.replace(tzinfo=now.tzinfo)
    grace_at = (
        overdue_started_at + timedelta(hours=grace_hours)
        if overdue_started_at else None
    )
    deadline = (
        grace_at + timedelta(minutes=overdue_wait_minutes)
        if grace_at else None
    )
    alert_at = deadline
    remaining_ms = max(0, int((deadline - now).total_seconds() * 1000)) if deadline else 0
    cancel_remaining_ms = 0
    prealert = bool(
        grace_at and deadline and grace_at <= now < deadline
    )
    overdue = bool(alert_at and now >= alert_at)
    today = now.strftime("%Y-%m-%d")
    is_today_checked = profile_is_today_checked(profile, now=now)
    # Heal history if last_check_in proves today but history missed the Taipei day
    if is_today_checked and today not in (profile.get("history") or []):
        history = set(profile.get("history") or [])
        history.add(today)
        profile["history"] = sorted(history)

    if prealert:
        status_text = "已提醒本人，等待平安回報"
        status_class = "warning"
    elif overdue:
        status_text = "已進入守護人順位通知"
        status_class = "danger"
    elif not last:
        status_text = "還沒有簽到紀錄"
        status_class = "gray"
    elif deadline and remaining_ms <= 6 * 60 * 60 * 1000:
        status_text = "快到提醒時間了"
        status_class = "warning"
    else:
        status_text = "狀態正常"
        status_class = "highlight"

    _reminder_times = reminder_times_for_profile(profile) or ["12:00"]
    _next_reminder = next_checkin_reminder_info(profile, now=now)
    guardian_groups = []
    today_safety_roster = None
    if state is not None:
        # 雙向對齊：避免群已綁定但 profile.guardian_group_ids 遺失 → LIFF 顯示「尚未綁定」
        sync_owned_guardian_group_ids(state, profile)
        groups = state.get("guardian_groups", {}) or {}
        for group_id in profile.get("guardian_group_ids", []) or []:
            group = groups.get(group_id)
            if group and group.get("owner_line_user_id") == profile.get("line_user_id"):
                row = dict(group)
                row["group_id"] = group_id
                row["preferences"] = normalize_guardian_group_preferences(group.get("preferences"))
                guardian_groups.append(row)
        if guardian_groups or plan_includes_guardian_group(profile):
            today_safety_roster = build_owner_today_safety_roster(
                state, profile, now=now
            )

    guarding_details = []
    for raw_detail in profile.get("guarding_details") or []:
        if not isinstance(raw_detail, dict):
            continue
        detail = dict(raw_detail)
        peer_id = str(detail.get("line_user_id") or "").strip()
        peer = ((state or {}).get("users") or {}).get(peer_id) or {}
        peer_times = reminder_times_for_profile(peer) if peer else []
        detail["reminder_times"] = peer_times
        detail["today_status"] = (
            "已報平安" if peer and profile_is_today_checked(peer, now=now)
            else "尚未報平安"
        )
        detail["latest_sos_status"] = ""
        if state is not None and peer_id:
            peer_events = [
                event
                for event in ((state.get("sos_events") or {}).values())
                if isinstance(event, dict)
                and str(event.get("owner_line_user_id") or "") == peer_id
                and any(
                    str(delivery.get("target") or "") == owner_id
                    for delivery in (event.get("deliveries") or [])
                    if isinstance(delivery, dict)
                )
            ]
            if peer_events:
                peer_events.sort(
                    key=lambda event: str(
                        event.get("updated_at")
                        or event.get("sent_at")
                        or event.get("created_at")
                        or ""
                    ),
                    reverse=True,
                )
                detail["latest_sos_status"] = str(
                    peer_events[0].get("status") or "sent"
                )
        guarding_details.append(detail)

    return {
        "ok": True,
        **access,
        "line_user_id": profile.get("line_user_id"),
        "display_name": profile.get("display_name", ""),
        "picture_url": profile.get("picture_url", ""),
        "streak_days": compute_streak_days(profile.get("history") or [], today),
        "last_check_in": profile.get("last_check_in"),
        "history": sorted(set(profile.get("history") or [])),
        "checkin_records": sorted(
            [
                {
                    "date": str(row.get("date") or "")[:10],
                    "checked_at": str(row.get("checked_at") or ""),
                    "area": str(row.get("area") or "未提供位置")[:40],
                }
                for row in (profile.get("checkin_records") or [])
                if isinstance(row, dict) and row.get("date")
            ],
            key=lambda row: row["checked_at"] or row["date"],
        ),
        "contact_email": profile.get("contact_email", ""),
        "grace_hours": grace_hours,
        "allowed_grace_hours": list(ALLOWED_GRACE_HOURS),
        "overdue_wait_minutes": overdue_wait_minutes,
        "allowed_overdue_wait_minutes": list(ALLOWED_OVERDUE_WAIT_MINUTES),
        "overdue_guardian_stage": int(
            (active_overdue or {}).get("guardian_stage") or 0
        ) if isinstance(active_overdue, dict) else 0,
        "reminder_time": _reminder_times[0],
        "reminder_times": _reminder_times,
        "daily_checkin_reminder_enabled": bool(profile.get("daily_checkin_reminder_enabled", True)),
        "checkin_mode": profile.get("checkin_mode", "manual"),
        "auto_checkin_on_open": bool(profile.get("auto_checkin_on_open", False)),
        "warning_cancel_minutes": warning_cancel_minutes,
        "alert_channels": profile.get("alert_channels", ["line"]),
        "attach_location_on_alert": bool(profile.get("attach_location_on_alert", False)),
        "contacts": profile.get("contacts", []),
        "contact_count": len(profile.get("contacts") or []),
        "bound_guardian_count": sum(
            1
            for c in (profile.get("contacts") or [])
            if contact_is_notifiable_line_guardian(c, owner_id)
        ),
        "core_guardian_count": sum(
            1
            for c in (profile.get("contacts") or [])
            if contact_is_notifiable_line_guardian(c, owner_id) and bool(c.get("is_primary"))
        ),
        # Legacy field retained for old clients; user-facing "一般" guardians no
        # longer exist. Accepted LINE guardians are presented as core guardians.
        "general_guardian_count": 0,
        "bound_guardians": [
            {
                "id": str(c.get("id") or "").strip(),
                "name": str(c.get("name") or "").strip(),
                "display_name": str(
                    c.get("display_name") or c.get("line_display_name") or c.get("name") or ""
                ).strip(),
                "line_display_name": str(
                    c.get("line_display_name") or c.get("display_name") or ""
                ).strip(),
                "line_user_id": get_contact_line_id(c),
                "relationship": str(c.get("relationship") or "").strip(),
                "binding_status": str(c.get("binding_status") or "").strip() or "accepted",
                "official_line_friend": bool(c.get("official_line_friend") or c.get("official_line_friend_verified_at")),
                "official_line_friend_verified_at": str(c.get("official_line_friend_verified_at") or "").strip(),
                "phone": str(c.get("phone") or "").strip(),
                "email": str(c.get("email") or "").strip(),
                "is_primary": bool(c.get("is_primary")),
                "accepted_at": str(c.get("accepted_at") or c.get("created_at") or "").strip(),
                "picture_url": str(c.get("picture_url") or c.get("pictureUrl") or "").strip(),
                "bind_notify_status": copy.deepcopy(c.get("bind_notify_status") or {}),
                "bind_notify_sent_at": str(c.get("bind_notify_sent_at") or "").strip(),
                "role": "核心守護人",
                "contact_role": resolve_contact_role(c),
            }
            for c in (profile.get("contacts") or [])
            if contact_is_notifiable_line_guardian(c, owner_id)
        ],
        "profile_contact_count": sum(
            1 for c in (profile.get("contacts") or []) if contact_is_profile_complete(c)
        ),
        "guarding_for": list(profile.get("guarding_for") or []),
        "guarding_details": guarding_details,
        "invited_by": str(profile.get("invited_by") or "").strip(),
        "contact_capacity_reminder_enabled": bool(profile.get("contact_capacity_reminder_enabled", False)),
        "guardian_details_reminder_enabled": bool(profile.get("guardian_details_reminder_enabled", True)),
        "guardian_details_complete": any(complete_guardian_contact(contact) for contact in (profile.get("contacts") or [])),
        "pending_guardian_invite_count": (
            pending_guardian_invite_count(state, owner_id, now)
            if state is not None else 0
        ),
        "plan": profile.get("plan", "trial"),
        "membership_source": str(profile.get("membership_source") or ""),
        "beta_cohort": str(profile.get("beta_cohort") or ""),
        "beta_started_at": str(profile.get("beta_started_at") or ""),
        "beta_ends_at": str(profile.get("beta_ends_at") or ""),
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
        "trial_policy_version": str(profile.get("trial_policy_version") or ""),
        "trial_bonus_days": trial_bonus_days(profile),
        "trial_total_days": trial_total_days(profile),
        "trial_days_left": trial_days_left(profile),
        "trial_active": trial_active(profile),
        "plan_expired_at": str(profile.get("plan_expired_at") or ""),
        "contacts_retain_until": str(profile.get("contacts_retain_until") or ""),
        "contacts_retain_days_left": contacts_retain_days_left(profile),
        "contact_limit": plan_rules(profile)["contact_limit"],
        "emergency_contact_limit": int(plan_rules(profile).get("emergency_contact_limit") or 2),
        "daily_reminders": plan_rules(profile)["daily_reminders"],
        "channels": plan_rules(profile)["channels"],
        "location_mode": plan_rules(profile).get("location_mode", "snapshot_24h"),
        "friend_location_limit": plan_rules(profile).get("friend_location_limit", 0),
        "realtime_tracking": bool(plan_rules(profile).get("realtime_tracking", False)),
        "trajectory_days": int(plan_rules(profile).get("trajectory_days", 0)),
        "offline_sync_days": int(plan_rules(profile).get("offline_sync_days", 0)),
        "sos_enabled": bool(plan_rules(profile).get("sos_enabled", True)),
        "dedicated_support": bool(plan_rules(profile).get("dedicated_support", False)),
        "realtime_trial_days": int(plan_rules(profile).get("realtime_trial_days", 0)),
        "core_guardian_alert_limit": plan_rules(profile).get("core_guardian_alert_limit", 1),
        "guardian_group_limit": plan_rules(profile).get("guardian_group_limit", 0),
        "guardian_group_member_limit": int(plan_rules(profile).get("guardian_group_member_limit") or 0),
        "calendar_notes_enabled": plan_has_smart_reminders(profile),
        "smart_reminders_enabled": plan_has_smart_reminders(profile),
        "safety_guard_hours": allowed_safety_guard_hours(profile),
        "guardian_group_ids": profile.get("guardian_group_ids", []),
        "guardian_groups": guardian_groups,
        "today_safety_roster": today_safety_roster,
        "is_today_checked": is_today_checked,
        "is_prealert": prealert,
        "is_overdue": overdue,
        "remaining_ms": remaining_ms,
        "cancel_remaining_ms": cancel_remaining_ms,
        "alert_at": alert_at.isoformat(timespec="seconds") if alert_at else None,
        "status_text": status_text,
        "status_class": status_class,
        "next_reminder_at": _next_reminder.get("next_reminder_at") or "",
        "next_reminder_time": _next_reminder.get("next_reminder_time") or "",
        "next_reminder_text": _next_reminder.get("next_reminder_text") or "",
        "next_reminder_label": _next_reminder.get("next_reminder_label") or "",
        "safety_guard": safety_guard_snapshot(profile),
        "membership_label": _membership_label(profile),
        "upgrade_status": _upgrade_status(profile),
        "trial_days_text": _trial_days_text(profile),
        "plan_type_label": plan_type_label(profile),
        "plan_expires_at": compute_plan_expires_at(profile),
        "trial_end": (
            compute_plan_expires_at(profile)
            if str(profile.get("plan") or "trial") == "trial"
            else ""
        ),
        "plan_expires_text": plan_expires_text(profile),
    }


def _membership_label(profile):
    plan = str(profile.get("plan") or "trial")
    labels = {
        "trial": "14 天安心體驗",
        "free": "未訂閱",
        "paid_199": "已升級 199 月費",
        "paid_199_year": "已升級 199 年費",
        "paid_399": "已升級 399 月費",
        "paid_399_year": "已升級 399 年費",
        "paid_799": "已升級 799 月費",
        "paid_799_year": "已升級 799 年費",
    }
    return labels.get(plan, plan)


def _trial_days_text(profile):
    if str(profile.get("membership_source") or "") == "beta":
        beta_end = parse_datetime(profile.get("beta_ends_at"))
        if not beta_end:
            return "21 天封測（尚未設定到期日）"
        now = current_app_time({})
        comparable_now, comparable_end = _comparable_datetimes(now, beta_end)
        seconds = (comparable_end - comparable_now).total_seconds()
        days = max(0, int((seconds + 86399) // 86400))
        return f"21 天封測剩 {days} 天" if days > 0 else "21 天封測已結束"
    plan = str(profile.get("plan") or "trial")
    if plan == "trial":
        days = trial_days_left(profile)
        return f"體驗剩 {days} 天" if days > 0 else "體驗已結束"
    if plan == "free":
        return "未訂閱（無體驗倒數）"
    return "已升級（非試用）"


def _upgrade_status(profile):
    plan = str(profile.get("plan") or "trial")
    payment = str(profile.get("payment_status") or "")
    if plan.startswith("paid"):
        active = payment == "active" or paid_membership_is_active(profile)
        return f"{_membership_label(profile)}｜{'使用中' if active else paymentLabel_zh(payment)}"
    if plan == "trial":
        days = trial_days_left(profile)
        return f"體驗中｜剩 {days} 天" if days > 0 else "體驗已結束｜尚未升級"
    if plan == "free":
        return "未訂閱｜尚未升級"
    return _membership_label(profile)


def paymentLabel_zh(status):
    return {
        "trial": "試用中",
        "free": "未訂閱",
        "active": "已付款",
        "pending": "待付款",
        "expired": "已到期",
        "failed": "付款失敗",
        "cancelled": "已取消",
    }.get(status, status or "未付費")


def paid_membership_is_active(profile, now=None):
    if profile.get("payment_status") != "active":
        return False
    paid_until = str(profile.get("paid_until") or "").strip()
    if not paid_until:
        return True
    expires_at = parse_datetime(paid_until)
    if not expires_at:
        return False
    comparable_expires, comparable_now = _comparable_datetimes(
        expires_at, now or current_app_time({})
    )
    return comparable_expires >= comparable_now


_WELCOME_NAME_PLACEHOLDERS = frozenset(
    {
        "",
        "您",
        "LINE 使用者",
        "LINE使用者",
        "LINE 會員",
        "LINE會員",
        "LINE 聯絡人",
        "LINE聯絡人",
        "使用者",
    }
)


def is_placeholder_display_name(name) -> bool:
    s = str(name or "").strip()
    if s in _WELCOME_NAME_PLACEHOLDERS:
        return True
    # 相容「LINE使用者」等無空白寫法
    return s.replace(" ", "").replace("\u3000", "") in {
        "LINE使用者",
        "LINE會員",
        "LINE聯絡人",
    }


def fetch_line_profile_dict(token: str, line_user_id: str) -> dict | None:
    """用 Messaging API 取 profile；失敗回 None。"""
    token = (token or "").strip()
    uid = str(line_user_id or "").strip()
    if not token or not uid:
        return None
    url = f"https://api.line.me/v2/bot/profile/{uid}"
    try:
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def ensure_user_display_name(profile, *, token="", hint="", force_fetch=False) -> str:
    """確保 profile 有真實 displayName；必要時打 LINE profile API 並寫回。"""
    if not isinstance(profile, dict):
        return ""
    hint_clean = str(hint or "").strip()
    current = str(profile.get("display_name") or "").strip()
    if hint_clean and not is_placeholder_display_name(hint_clean):
        profile["display_name"] = hint_clean
        if hint_clean != current:
            profile["display_name_updated_at"] = datetime.now().isoformat(timespec="seconds")
        return hint_clean
    if current and not is_placeholder_display_name(current) and not force_fetch:
        return current
    fetched = fetch_line_profile_dict(token, profile.get("line_user_id"))
    name = extract_line_display_name(fetched) if fetched else None
    if name:
        profile["display_name"] = name
        if fetched.get("pictureUrl"):
            profile["picture_url"] = str(fetched.get("pictureUrl") or profile.get("picture_url") or "")
        profile["display_name_updated_at"] = datetime.now().isoformat(timespec="seconds")
        return name
    if current:
        return current
    profile["display_name"] = "LINE 使用者"
    return profile["display_name"]


def register_line_user(data_file, payload):
    """Upsert LINE user: merge into existing record, never reset trial/bindings."""
    line_user_id = str(payload.get("line_user_id") or "").strip()
    if not line_user_id:
        return {"error": "missing line_user_id"}, 400
    state = load_state(data_file)
    alias = (state.get("account_migration_aliases") or {}).get(line_user_id)
    if isinstance(alias, dict) and alias.get("status") == "disabled":
        return account_migrated_response(), 409
    existing = (state.get("users") or {}).get(line_user_id)
    preserved = {}
    if isinstance(existing, dict):
        for key in _PROFILE_PERSIST_KEYS:
            if key in existing and existing.get(key) not in (None,):
                preserved[key] = existing.get(key)
        # Deep-copy mutable collections so accidental mutation cannot blank them.
        for key in ("contacts", "history", "friends", "guardian_group_ids", "guarding_for", "guarding_details"):
            if key in preserved and isinstance(preserved[key], list):
                preserved[key] = list(preserved[key])
        if isinstance(preserved.get("calendar_notes"), dict):
            preserved["calendar_notes"] = dict(preserved["calendar_notes"])
        if isinstance(preserved.get("interaction_state"), dict):
            preserved["interaction_state"] = dict(preserved["interaction_state"])

    requested_beta = str(payload.get("beta_cohort") or "").strip().upper()
    guardian_only = bool(payload.get("guardian_only"))
    activate_own_trial = bool(payload.get("activate_own_trial"))
    if requested_beta and requested_beta not in {"B399", "B799"}:
        return {"ok": False, "error": "invalid_beta_link"}, 400
    user = get_profile(
        state,
        line_user_id,
        start_public_trial=not bool(requested_beta) and not guardian_only,
    )
    # Re-apply preserved fields after get_profile defaults (merge, don't replace).
    for key, value in preserved.items():
        if key == "trial_started_at" and value:
            user["trial_started_at"] = value
        elif key in ("contacts", "history", "friends", "guardian_group_ids", "guarding_for", "guarding_details"):
            if value:
                user[key] = value
        elif key in ("calendar_notes", "interaction_state"):
            if value:
                user[key] = value
        elif value not in (None, ""):
            user[key] = value

    if isinstance(existing, dict) and str(user.get("plan") or "") == "free":
        ensure_membership_trial(user, source="transition_trial")
    own_trial_activated = False
    if activate_own_trial:
        used_source = free_eligibility_source(user)
        if used_source and not membership_access_active(user):
            return {
                "ok": False,
                "error": "free_eligibility_already_used",
                "message": "你已使用過免費體驗；請選擇正式方案繼續使用報平安。",
            }, 409
        if not used_source:
            own_trial_activated = ensure_membership_trial(
                user,
                source="public_trial",
            )

    token = (
        (payload.get("access_token") if isinstance(payload, dict) else None)
        or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    )
    ensure_user_display_name(
        user,
        token=token,
        hint=str(payload.get("display_name") or ""),
    )
    picture = str(payload.get("picture_url") or "").strip()
    if picture:
        user["picture_url"] = picture
    if requested_beta:
        try:
            claim_beta_link(state, line_user_id, requested_beta)
        except ValueError as exc:
            reason = str(exc)
            messages = {
                "cohort_full": "這一組封測名額已滿",
                "already_in_other_cohort": "你已加入另一個封測組別",
                "free_eligibility_already_used": "你已使用過免費體驗或封測資格",
            }
            return {
                "ok": False,
                "error": reason,
                "message": messages.get(reason, "無法加入封測"),
            }, 409
    save_state(data_file, state)
    status = build_status(user, state)
    status["beta_cohort"] = str(user.get("beta_cohort") or "")
    status["existing_user"] = bool(existing)
    status["guardian_only"] = guardian_only
    status["own_trial_activated"] = bool(own_trial_activated)
    return status, 200


def reactivate_line_push_for_follow(data_file, line_user_id):
    """A new FollowEvent proves this user can receive LINE pushes again."""
    line_user_id = str(line_user_id or "").strip()
    if not line_user_id:
        return False
    state = load_state(data_file)
    user = (state.get("users") or {}).get(line_user_id)
    if not isinstance(user, dict):
        return False
    blocked_keys = (
        "line_push_blocked",
        "line_push_blocked_at",
        "push_delivery_attempts",
    )
    changed = False
    for key in blocked_keys:
        if key in user:
            user.pop(key, None)
            changed = True
    for owner in (state.get("users") or {}).values():
        if not isinstance(owner, dict):
            continue
        for contact in owner.get("contacts") or []:
            if not isinstance(contact, dict):
                continue
            target = contact.get("line_id") or contact.get("line_user_id")
            if str(target or "").strip() != line_user_id:
                continue
            for key in blocked_keys:
                if key in contact:
                    contact.pop(key, None)
                    changed = True
    if changed:
        save_state(data_file, state)
    return changed


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


def notify_guardians_of_checkin(data_file, line_user_id, config=None, now=None):
    """報平安成功後，私訊已完成 LINE 綁定的核心守護人。"""
    cfg = config or {}
    token = (
        cfg.get("LINE_CHANNEL_ACCESS_TOKEN")
        or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    )
    if not token:
        return {"sent": 0, "failed": 0, "skipped": True, "reason": "missing_token"}
    state = load_state(data_file)
    profile = (state.get("users") or {}).get(str(line_user_id or "").strip())
    if not isinstance(profile, dict):
        return {"sent": 0, "failed": 0, "skipped": True, "reason": "member_not_found"}

    owner_id = str(profile.get("line_user_id") or line_user_id or "").strip()
    limit = max(1, int(plan_rules(profile).get("core_guardian_alert_limit") or 1))
    contacts = sorted(
        profile.get("contacts") or [],
        key=lambda item: (
            0 if bool((item or {}).get("is_primary")) else 1,
            int((item or {}).get("priority") or 9999),
        ),
    )
    recipients = []
    seen = set()
    for contact in contacts:
        if not contact_is_notifiable_line_guardian(contact, owner_id):
            continue
        target = get_contact_line_id(contact)
        if not target or target in seen:
            continue
        seen.add(target)
        recipients.append((target, contact))
        if len(recipients) >= limit:
            break
    if not recipients:
        return {"sent": 0, "failed": 0, "skipped": True, "reason": "no_guardians"}

    sent = 0
    failed = 0
    checked_at = now or current_app_time(cfg)
    owner_name = str(profile.get("display_name") or "您的親友").strip()
    message = (
        f"✅ {owner_name} 已報平安\n"
        f"時間：{checked_at.strftime('%Y/%m/%d %H:%M')}\n"
        "今日平安回報已完成，請放心。"
    )
    sender = cfg.get("LINE_PUSH_SENDER") or line_push_message
    for target, _contact in recipients:
        try:
            result = sender(token, target, message)
            append_notification_log(
                state, "checkin_guardian", target, "sent", message,
                json.dumps(result, ensure_ascii=False),
            )
            sent += 1
        except Exception as exc:
            append_notification_log(
                state, "checkin_guardian", target, "failed", message, str(exc)
            )
            failed += 1
    record_line_message_usage(
        state,
        category="checkin",
        owner_line_user_id=owner_id,
        recipient_count=sent,
        event_id=f"checkin_guardian:{owner_id}:{checked_at.strftime('%Y%m%d')}",
        sent_at=checked_at,
    )
    save_state(data_file, state)
    return {
        "sent": sent,
        "failed": failed,
        "skipped": False,
        "reason": "",
    }


def record_checkin(data_file, payload=None, config=None):
    payload = payload or {}
    state = load_state(data_file)
    profile = get_profile(state, payload.get("line_user_id"))
    now = current_app_time(config or {})
    today = now.strftime("%Y-%m-%d")
    history = set(profile.get("history") or [])
    already_checked = profile_is_today_checked(profile, config=config, now=now)
    if today not in history:
        history.add(today)
        profile["history"] = sorted(history)
    # Persist as Taipei-local naive ISO so [:10] matches today_string()
    checked_at = now.isoformat(timespec="seconds")
    profile["last_check_in"] = checked_at
    area = str(payload.get("area") or payload.get("city") or "").strip()
    if not area:
        area = str((profile.get("location") or {}).get("city") or "").strip()
    area = area[:40] or "未提供位置"
    records = [
        dict(row)
        for row in (profile.get("checkin_records") or [])
        if isinstance(row, dict) and str(row.get("date") or "") != today
    ]
    records.append({"date": today, "checked_at": checked_at, "area": area})
    profile["checkin_records"] = sorted(
        records, key=lambda row: str(row.get("checked_at") or row.get("date") or "")
    )[-365:]
    profile["last_warning_cancelled_at"] = None
    active_overdue = profile.get("active_overdue_event")
    if isinstance(active_overdue, dict) and not active_overdue.get("resolved_at"):
        active_overdue["resolved_at"] = checked_at
        active_overdue["status"] = "checked_in"
        profile["last_overdue_event"] = copy.deepcopy(active_overdue)
    profile["active_overdue_event"] = None
    # Product rule: 今日已報平安 → 略過同日剩餘排程提醒（標記所有 slots）
    times = reminder_times_for_profile(profile) or ["12:00"]
    _mark_checkin_reminder_slots(profile, today, times, times)
    save_state(data_file, state)
    guardian_notify = {
        "sent": 0,
        "failed": 0,
        "skipped": True,
        "reason": "already_checked_today" if already_checked else "not_configured",
    }
    if not already_checked:
        guardian_notify = notify_guardians_of_checkin(
            data_file,
            str(profile.get("line_user_id") or payload.get("line_user_id") or ""),
            config=config,
            now=now,
        )
    status = build_status(profile, state)
    status["already_checked_today"] = already_checked
    status["is_duplicate"] = already_checked
    status["guardian_notify"] = guardian_notify
    return status


def cancel_warning(data_file, payload=None, config=None):
    payload = payload or {}
    state = load_state(data_file)
    profile = get_profile(state, payload.get("line_user_id"))
    now = current_app_time(config or {})
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
    return build_status(profile, state)


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
    if "grace_hours" in payload:
        profile["grace_hours"] = normalize_grace_hours(payload.get("grace_hours"))
    else:
        profile["grace_hours"] = normalize_grace_hours(profile.get("grace_hours"))
    if "overdue_wait_minutes" in payload:
        profile["overdue_wait_minutes"] = normalize_overdue_wait_minutes(
            payload.get("overdue_wait_minutes")
        )
    else:
        profile["overdue_wait_minutes"] = normalize_overdue_wait_minutes(
            profile.get("overdue_wait_minutes")
        )
    if "reminder_times" in payload:
        apply_reminder_times_to_profile(profile, times=payload.get("reminder_times"))
    elif "reminder_time" in payload:
        apply_reminder_times_to_profile(profile, single=payload.get("reminder_time"))
    checkin_mode = str(payload.get("checkin_mode") or profile.get("checkin_mode") or "manual")
    profile["checkin_mode"] = checkin_mode if checkin_mode in {"manual", "voice", "auto_open"} else "manual"
    profile["auto_checkin_on_open"] = bool(payload.get("auto_checkin_on_open", False))
    profile["warning_cancel_minutes"] = max(
        1,
        min(60, int(payload.get("warning_cancel_minutes") or DEFAULT_WARNING_CANCEL_MINUTES)),
    )
    profile["alert_channels"] = normalized_alert_channels(payload.get("alert_channels"))
    profile["attach_location_on_alert"] = bool(payload.get("attach_location_on_alert", False))
    if "contact_capacity_reminder_enabled" in payload:
        profile["contact_capacity_reminder_enabled"] = bool(payload.get("contact_capacity_reminder_enabled"))
    if "guardian_details_reminder_enabled" in payload:
        profile["guardian_details_reminder_enabled"] = bool(payload.get("guardian_details_reminder_enabled"))
    if "daily_checkin_reminder_enabled" in payload:
        profile["daily_checkin_reminder_enabled"] = bool(payload.get("daily_checkin_reminder_enabled"))
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
    recurring_requested = bool(profile.get("auto_renew_requested"))
    payer_email = str(
        profile.get("contact_email") or payload.get("payer_email") or ""
    ).strip()
    if recurring_requested and not payer_email:
        return {"error": "payer_email_required_for_auto_renew"}, 400
    now = current_app_time(config or {})
    cfg = config or {}
    use_legacy_newebpay = bool(
        newebpay is not None
        and newebpay.newebpay_configured(cfg)
        and not (ecpay is not None and ecpay.ecpay_configured(cfg))
    )
    provider = "newebpay" if use_legacy_newebpay else "ecpay"
    order = {
        "order_id": f"AC{now.strftime('%Y%m%d%H%M%S')}{secrets.token_hex(2).upper()}",
        "line_user_id": line_user_id,
        "display_name": profile.get("display_name") or "LINE 會員",
        "plan": plan,
        "amount": product["amount"],
        "currency": "TWD",
        "billing_cycle": product["billing_cycle"],
        "provider": provider,
        "status": "pending",
        "created_at": now.isoformat(timespec="seconds"),
        "paid_at": "",
        "transaction_id": "",
        "recurring_requested": recurring_requested,
        "subscription_status": (
            "pending" if profile.get("auto_renew_requested") else "not_requested"
        ),
        "period_no": "",
        "processed_transaction_ids": [],
    }
    state.setdefault("orders", []).append(order)
    save_state(data_file, state)
    checkout = None
    if provider == "newebpay" and newebpay is not None:
        if order["recurring_requested"]:
            checkout = newebpay.build_period_checkout(
                order,
                payer_email=payer_email,
                config=cfg,
            )
        else:
            checkout = newebpay.build_checkout(order, cfg)
    elif ecpay is not None:
        if order["recurring_requested"]:
            checkout = ecpay.build_period_checkout(
                order,
                config=cfg,
            )
        else:
            checkout = ecpay.build_checkout(order, cfg)
    else:
        checkout = {
            "mode": "manual",
            "checkout_url": None,
            "form": None,
            "message": "安全付款模組未載入；訂單已建立，請稍後再試。",
        }
    return {"order": order, "checkout": checkout}, 201


def validate_payment_confirmation(state, order, parsed, now):
    """Reject mismatched or replayed gateway confirmations before entitlement changes."""
    transaction_id = str(parsed.get("transaction_id") or "").strip()
    received_amount = parsed.get("amount")
    if received_amount not in (None, ""):
        try:
            received_amount = int(received_amount)
        except (TypeError, ValueError):
            received_amount = -1
        expected_amount = int(order.get("amount") or 0)
        if received_amount != expected_amount:
            order.update({
                "status": "anomaly",
                "anomaly_code": "amount_mismatch",
                "expected_amount": expected_amount,
                "received_amount": received_amount,
                "anomaly_transaction_id": transaction_id,
                "anomaly_detected_at": now.isoformat(timespec="seconds"),
            })
            append_notification_log(
                state,
                "payment_anomaly",
                order.get("line_user_id") or "",
                "blocked",
                f"{order.get('order_id')} amount mismatch",
            )
            return {
                "error": "payment_amount_mismatch",
                "order_id": order.get("order_id"),
            }, 409

    if transaction_id:
        duplicate = next(
            (
                item
                for item in state.get("orders", [])
                if item is not order
                and str(item.get("transaction_id") or "").strip() == transaction_id
            ),
            None,
        )
        if duplicate:
            order.update({
                "status": "anomaly",
                "anomaly_code": "duplicate_transaction_id",
                "anomaly_transaction_id": transaction_id,
                "duplicate_of_order_id": duplicate.get("order_id"),
                "anomaly_detected_at": now.isoformat(timespec="seconds"),
            })
            append_notification_log(
                state,
                "payment_anomaly",
                order.get("line_user_id") or "",
                "blocked",
                f"{order.get('order_id')} duplicate transaction",
            )
            return {
                "error": "duplicate_transaction_id",
                "order_id": order.get("order_id"),
                "duplicate_of_order_id": duplicate.get("order_id"),
            }, 409
    return None


def process_period_notification(data_file, parsed, config=None):
    """Apply one verified NewebPay period notification exactly once."""
    order_id = str(parsed.get("order_id") or "").strip()
    transaction_id = str(parsed.get("transaction_id") or "").strip()
    if str(parsed.get("status") or "").upper() != "SUCCESS":
        return {"accepted": True, "activated": False}, 200
    if not order_id:
        return {"error": "missing order_id"}, 400

    state = load_state(data_file)
    order = next(
        (
            item
            for item in state.setdefault("orders", [])
            if item.get("order_id") == order_id
        ),
        None,
    )
    if not order:
        return {"error": "order not found"}, 404
    now = current_app_time(config or {})
    integrity_error = validate_payment_confirmation(state, order, parsed, now)
    if integrity_error:
        save_state(data_file, state)
        return integrity_error
    processed = order.setdefault("processed_transaction_ids", [])
    event_key = transaction_id or f"period:{parsed.get('period_no') or ''}:initial"
    if event_key in processed:
        return {"order": order, "already_processed": True}, 200

    profile = get_profile(state, order.get("line_user_id"))
    product = PAYMENT_PRODUCTS.get(order.get("plan"))
    if not product:
        return {"error": "unknown payment plan"}, 400
    current_until = parse_datetime(profile.get("paid_until"))
    start_at = current_until if current_until and current_until > now else now
    profile["plan"] = order["plan"]
    profile["membership_source"] = "paid"
    profile["payment_status"] = "active"
    profile["billing_cycle"] = product["billing_cycle"]
    provider = str(
        parsed.get("provider")
        or (
            "newebpay"
            if parsed.get("period_no")
            and newebpay is not None
            and newebpay.newebpay_configured(config or {})
            else ""
        )
        or order.get("provider")
        or "ecpay"
    )
    profile["payment_provider"] = provider
    profile["paid_until"] = (
        start_at + timedelta(days=product["duration_days"])
    ).isoformat(timespec="seconds")
    profile["next_billing_date"] = profile["paid_until"]
    profile["payment_method_last4"] = str(
        parsed.get("payment_method_last4") or ""
    )[-4:]
    profile["auto_renew_requested"] = True
    profile["auto_renew_enabled"] = True
    profile["auto_renew_status"] = "active"
    profile["payment_period_order_no"] = order_id
    if provider == "newebpay":
        profile["newebpay_period_no"] = str(parsed.get("period_no") or "")
        profile["newebpay_period_order_no"] = order_id
    else:
        profile["ecpay_period_order_no"] = order_id
    profile["renewal_reminder_sent_for"] = ""
    order["status"] = "paid"
    order["subscription_status"] = "active"
    order["period_no"] = str(parsed.get("period_no") or "")
    order["transaction_id"] = transaction_id
    order["paid_at"] = now.isoformat(timespec="seconds")
    processed.append(event_key)
    clear_contacts_retain_window(profile)
    ensure_guardian_group_admin_for_user(state, profile)
    save_state(data_file, state)
    return {"order": order, "member": build_status(profile, state), "already_processed": False}, 200


def _newebpay_post(url, form):
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen

    request_obj = Request(
        url,
        data=urlencode(form).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(request_obj, timeout=15) as response:  # nosec B310
        raw = response.read().decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        from urllib.parse import parse_qs

        return {key: values[0] for key, values in parse_qs(raw).items()}


def cancel_recurring_subscription(data_file, payload, config=None):
    """Terminate a recurring mandate; local state changes only after gateway success."""
    line_user_id = str(payload.get("line_user_id") or "").strip()
    if not line_user_id:
        return {"error": "missing line_user_id"}, 400
    state = load_state(data_file)
    profile = state.get("users", {}).get(line_user_id)
    if not profile:
        return {"error": "user not found"}, 404
    if not profile.get("auto_renew_enabled"):
        return {"cancelled": False, "already_off": True}, 200
    provider = str(
        profile.get("payment_provider")
        or (
            "newebpay"
            if profile.get("newebpay_period_order_no")
            or profile.get("newebpay_period_no")
            else "ecpay"
        )
    )
    cfg = config or {}
    if provider == "newebpay":
        try:
            gateway_request = newebpay.build_period_status_change(
                merchant_order_no=profile.get("newebpay_period_order_no"),
                period_no=profile.get("newebpay_period_no"),
                action="terminate",
                config=cfg,
            )
        except (RuntimeError, ValueError) as exc:
            return {"error": str(exc)}, 400
        poster = cfg.get("NEWEBPAY_HTTP_POSTER") or _newebpay_post
        try:
            response_form = poster(gateway_request["url"], gateway_request["form"])
        except Exception:
            return {"error": "payment_period_cancel_failed"}, 502
        parsed, error = newebpay.parse_period_payload(response_form or {}, cfg)
        result = (parsed or {}).get("raw", {}).get("Result") or {}
        accepted = bool(
            not error
            and str((parsed or {}).get("status") or "").upper() == "SUCCESS"
            and str(result.get("AlterType") or "").lower() == "terminate"
        )
    else:
        try:
            gateway_request = ecpay.build_period_action(
                merchant_trade_no=(
                    profile.get("ecpay_period_order_no")
                    or profile.get("payment_period_order_no")
                ),
                action="Cancel",
                config=cfg,
            )
        except (RuntimeError, ValueError) as exc:
            return {"error": str(exc)}, 400
        poster = cfg.get("ECPAY_HTTP_POSTER") or _newebpay_post
        try:
            response_form = poster(gateway_request["url"], gateway_request["form"])
        except Exception:
            return {"error": "payment_period_cancel_failed"}, 502
        parsed, error = ecpay.parse_action_response(response_form, cfg)
        accepted = bool(
            not error and str((parsed or {}).get("status") or "") == "1"
        )
    if not accepted:
        return {"error": "payment_period_cancel_rejected", "gateway": parsed}, 502

    now = current_app_time(config or {}).isoformat(timespec="seconds")
    profile["auto_renew_enabled"] = False
    profile["auto_renew_requested"] = False
    profile["auto_renew_status"] = "terminated"
    profile["auto_renew_cancelled_at"] = now
    for order in state.get("orders", []):
        if (
            order.get("order_id")
            in {
                profile.get("newebpay_period_order_no"),
                profile.get("ecpay_period_order_no"),
                profile.get("payment_period_order_no"),
            }
            or order.get("period_no") == profile.get("newebpay_period_no")
        ):
            order["subscription_status"] = "terminated"
            order["subscription_terminated_at"] = now
    save_state(data_file, state)
    return {"cancelled": True, "effective_until": profile.get("paid_until")}, 200


def refund_payment_order(data_file, payload, config=None):
    """Issue a bounded credit-card refund and retain an immutable audit entry."""
    order_id = str(payload.get("order_id") or "").strip()
    try:
        amount = int(payload.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0
    reason = str(payload.get("reason") or "").strip()
    requested_by = str(payload.get("requested_by") or "admin").strip()
    if not order_id or amount <= 0 or not reason:
        return {"error": "order_id, positive amount and reason are required"}, 400

    state = load_state(data_file)
    order = next(
        (
            item
            for item in state.setdefault("orders", [])
            if item.get("order_id") == order_id
        ),
        None,
    )
    if not order:
        return {"error": "order not found"}, 404
    if order.get("status") not in {"paid", "partially_refunded"}:
        return {"error": "only paid orders can be refunded"}, 409
    paid_amount = int(order.get("amount") or 0)
    refunded_amount = int(order.get("refunded_amount") or 0)
    remaining = max(0, paid_amount - refunded_amount)
    if amount > remaining:
        return {
            "error": "refund amount exceeds remaining amount",
            "remaining_amount": remaining,
        }, 400
    if not str(order.get("transaction_id") or "").strip():
        return {"error": "order transaction_id is missing"}, 409

    cfg = config or {}
    provider = str(
        order.get("provider")
        or (
            "newebpay"
            if newebpay is not None
            and newebpay.newebpay_configured(cfg)
            and not (ecpay is not None and ecpay.ecpay_configured(cfg))
            else "ecpay"
        )
    )
    try:
        if provider == "newebpay":
            gateway_request = newebpay.build_credit_card_refund(
                merchant_order_no=order_id,
                trade_no=order.get("transaction_id"),
                amount=amount,
                config=cfg,
            )
        else:
            gateway_request = ecpay.build_credit_action(
                merchant_trade_no=order_id,
                trade_no=order.get("transaction_id"),
                amount=amount,
                action="R",
                config=cfg,
            )
    except (RuntimeError, ValueError) as exc:
        return {"error": str(exc)}, 400
    poster = (
        cfg.get("NEWEBPAY_HTTP_POSTER")
        if provider == "newebpay"
        else cfg.get("ECPAY_HTTP_POSTER")
    ) or _newebpay_post
    try:
        gateway_response = poster(
            gateway_request["url"], gateway_request["form"]
        )
    except Exception:
        return {"error": "payment_refund_failed"}, 502
    parsed, error = (
        newebpay.parse_credit_card_close_response(gateway_response)
        if provider == "newebpay"
        else ecpay.parse_action_response(gateway_response, cfg)
    )
    if error:
        return {"error": error}, 502
    success_status = (
        str(parsed.get("status") or "").upper() == "SUCCESS"
        if provider == "newebpay"
        else str(parsed.get("status") or "") == "1"
    )
    if not success_status:
        return {"error": "payment_refund_rejected", "gateway": parsed}, 502

    now = current_app_time(config or {}).isoformat(timespec="seconds")
    refund = {
        "refund_id": f"RF{secrets.token_hex(6).upper()}",
        "amount": amount,
        "reason": reason[:500],
        "requested_by": requested_by[:100],
        "status": "accepted",
        "gateway_status": parsed.get("status"),
        "gateway_message": parsed.get("message"),
        "created_at": now,
    }
    order.setdefault("refunds", []).append(refund)
    order["refunded_amount"] = refunded_amount + amount
    order["status"] = (
        "refunded"
        if order["refunded_amount"] >= paid_amount
        else "partially_refunded"
    )
    order["last_refunded_at"] = now
    profile = state.get("users", {}).get(order.get("line_user_id"))
    if profile is not None and order["status"] == "refunded":
        profile["payment_status"] = "refunded"
        profile["last_refunded_order_id"] = order_id
    append_notification_log(
        state,
        "payment_refund",
        order.get("line_user_id") or "",
        "accepted",
        f"{order_id} refund {amount}",
        json.dumps(refund, ensure_ascii=False),
    )
    save_state(data_file, state)
    return {
        "refund": refund,
        "order": order,
        "remaining_amount": max(0, paid_amount - order["refunded_amount"]),
    }, 200


def confirm_payment_order(data_file, payload, config=None):
    order_id = str(payload.get("order_id") or "").strip()
    if not order_id:
        return {"error": "missing order_id"}, 400

    state = load_state(data_file)
    order = next((item for item in state.setdefault("orders", []) if item.get("order_id") == order_id), None)
    if not order:
        return {"error": "order not found"}, 404
    profile = get_profile(state, order.get("line_user_id"))
    now = current_app_time(config or {})
    integrity_error = validate_payment_confirmation(state, order, payload, now)
    if integrity_error:
        save_state(data_file, state)
        return integrity_error
    if order.get("status") == "paid":
        return {"order": order, "member": build_status(profile), "already_confirmed": True}, 200
    if payload.get("amount") is not None:
        try:
            notified_amount = int(payload.get("amount"))
        except (TypeError, ValueError):
            notified_amount = 0
        if notified_amount != int(order.get("amount") or 0):
            return {"error": "payment amount mismatch"}, 400

    product = PAYMENT_PRODUCTS.get(order.get("plan"))
    if not product:
        return {"error": "unknown payment plan"}, 400
    current_until = parse_datetime(profile.get("paid_until"))
    start_at = current_until if current_until and current_until > now else now
    paid_until = start_at + timedelta(days=product["duration_days"])

    order["status"] = "paid"
    order["paid_at"] = now.isoformat(timespec="seconds")
    order["transaction_id"] = str(payload.get("transaction_id") or "").strip()
    reminder_enabled_before_expiry = bool(
        profile.pop(
            "daily_checkin_reminder_enabled_before_expiry",
            profile.get("daily_checkin_reminder_enabled", True),
        )
    )
    profile["plan"] = order["plan"]
    profile["membership_source"] = "paid"
    profile["trial_policy_version"] = TRIAL_POLICY_VERSION
    profile["trial_bonus_days"] = 0
    profile["payment_status"] = "active"
    profile["paid_until"] = paid_until.isoformat(timespec="seconds")
    profile["billing_cycle"] = product["billing_cycle"]
    profile["payment_provider"] = str(
        payload.get("provider") or order.get("provider") or "ecpay"
    )
    profile["payment_method_last4"] = str(payload.get("payment_method_last4") or "").strip()[-4:]
    profile["next_billing_date"] = profile["paid_until"]
    profile["renewal_reminder_sent_for"] = ""
    clear_contacts_retain_window(profile)
    profile["daily_checkin_reminder_enabled"] = reminder_enabled_before_expiry
    if payload.get("auto_renew_enabled") is not None:
        profile["auto_renew_enabled"] = bool(payload.get("auto_renew_enabled"))
        profile["auto_renew_status"] = "active" if profile["auto_renew_enabled"] else "off"
    # 升級含守護群方案：自動把建立者設為守護群管理員（不必再走管理員設定）
    admin_granted = ensure_guardian_group_admin_for_user(state, profile)
    save_state(data_file, state)
    return {
        "order": order,
        "member": build_status(profile, state),
        "already_confirmed": False,
        "guardian_group_admin_granted": admin_granted,
    }, 200


def _apply_expired_plan_downgrades_to_state(state, now):
    downgraded = []
    for profile in state.get("users", {}).values():
        plan = str(profile.get("plan") or "")
        preserved_contacts = list(profile.get("contacts") or [])
        preserved_friends = list(profile.get("friends") or [])
        preserved_groups = list(profile.get("guardian_group_ids") or [])

        beta_end = parse_datetime(profile.get("beta_ends_at"))
        if (
            profile.get("membership_source") == "beta"
            and beta_end
            and not membership_access_active(profile, now)
            and not profile.get("beta_revoked_at")
        ):
            profile["plan"] = "free"
            profile["membership_source"] = "expired"
            profile["payment_status"] = "expired"
            profile["contacts"] = preserved_contacts
            profile["friends"] = preserved_friends
            profile["guardian_group_ids"] = preserved_groups
            mark_entitlement_lapsed(profile, now)
            downgraded.append(profile.get("line_user_id"))
            append_notification_log(
                state,
                "plan_expired",
                profile.get("line_user_id"),
                "downgraded",
                "beta expired -> free; relationships retained",
            )
            continue

        # 試用到期 → 未訂閱；資料與守護關係不自動刪除
        if plan == "trial" and not membership_access_active(profile, now):
            profile["plan"] = "free"
            profile["membership_source"] = "expired"
            profile["payment_status"] = "expired"
            profile["billing_cycle"] = ""
            profile["contacts"] = preserved_contacts
            profile["friends"] = preserved_friends
            profile["guardian_group_ids"] = preserved_groups
            mark_entitlement_lapsed(profile, now)
            downgraded.append(profile.get("line_user_id"))
            append_notification_log(
                state,
                "plan_expired",
                profile.get("line_user_id"),
                "downgraded",
                f"trial expired -> free; contacts kept={len(preserved_contacts)}; "
                f"retain_until={profile.get('contacts_retain_until')}",
            )
            continue

        if not plan.startswith("paid_"):
            continue
        paid_until = parse_datetime(profile.get("paid_until"))
        if not paid_until:
            # 無到期日：保留現況，避免誤降級並讓使用者以為好友被清掉
            continue
        comparable_until, comparable_now = _comparable_datetimes(paid_until, now)
        if comparable_until >= comparable_now:
            continue
        # 已過期：暫停付費服務，但保留所有綁定直到驗證後申請解除
        if profile.get("payment_status") == "active" or paid_until:
            profile["plan"] = "free"
            profile["membership_source"] = "expired"
            profile["payment_status"] = "expired"
            profile["billing_cycle"] = ""
            profile["auto_renew_enabled"] = False
            profile["auto_renew_status"] = "off"
            profile["next_billing_date"] = ""
            profile["contacts"] = preserved_contacts
            profile["friends"] = preserved_friends
            profile["guardian_group_ids"] = preserved_groups
            mark_entitlement_lapsed(profile, now)
            downgraded.append(profile.get("line_user_id"))
            append_notification_log(
                state,
                "plan_expired",
                profile.get("line_user_id"),
                "downgraded",
                f"plan expired -> free (was {plan}); contacts kept={len(preserved_contacts)}; "
                f"retain_until={profile.get('contacts_retain_until')}",
            )
    return downgraded


def apply_expired_plan_downgrades(config):
    """試用／付費到期：降為 free，並在同一資料庫交易保留帳戶資料。"""
    data_file = config["DATA_FILE"]
    now = current_app_time(config)
    downgraded = mutate_state_atomically(
        data_file,
        lambda state: _apply_expired_plan_downgrades_to_state(state, now),
    )
    return {"downgraded": len(downgraded), "line_user_ids": downgraded}, 200


def _claim_trial_milestone_notices(state, clock):
    claims = []
    lease_cutoff = clock - timedelta(minutes=15)
    for profile in (state.get("users") or {}).values():
        if str(profile.get("plan") or "") != "trial":
            continue
        started = parse_datetime(profile.get("trial_started_at"))
        target = str(profile.get("line_user_id") or "").strip()
        if not started or not target:
            continue
        elapsed_days = max(0, (clock.date() - started.date()).days)
        completed = {
            int(day)
            for day in (
                profile.get("trial_notice_days_sent")
                or profile.pop("trial_milestone_notices_sent", [])
            )
            if str(day).isdigit()
        }
        profile["trial_notice_days_sent"] = sorted(completed)
        active_claims = dict(profile.get("trial_notice_claims") or {})
        for day in (7, 12, 14):
            if elapsed_days < day or day in completed:
                continue
            existing = active_claims.get(str(day)) or {}
            claimed_at = parse_datetime(existing.get("claimed_at"))
            if claimed_at and claimed_at > lease_cutoff:
                continue
            claim_token = uuid.uuid4().hex
            active_claims[str(day)] = {
                "token": claim_token,
                "claimed_at": clock.isoformat(timespec="seconds"),
            }
            claims.append({
                "line_user_id": target,
                "day": day,
                "trial_started_at": started.isoformat(timespec="seconds"),
                "claim_token": claim_token,
            })
        profile["trial_notice_claims"] = active_claims
    return claims


def _finish_trial_milestone_notice(
    state, claim, message, status, detail=""
):
    profile = (state.get("users") or {}).get(claim["line_user_id"])
    if not isinstance(profile, dict):
        return False
    day_key = str(claim["day"])
    active_claims = dict(profile.get("trial_notice_claims") or {})
    current = active_claims.get(day_key) or {}
    if current.get("token") != claim.get("claim_token"):
        return False
    active_claims.pop(day_key, None)
    profile["trial_notice_claims"] = active_claims
    if status == "sent":
        completed = {
            int(day) for day in (profile.get("trial_notice_days_sent") or [])
            if str(day).isdigit()
        }
        completed.add(int(claim["day"]))
        profile["trial_notice_days_sent"] = sorted(completed)
    append_notification_log(
        state,
        "trial_milestone",
        claim["line_user_id"],
        status,
        message,
        detail,
    )
    return True


def membership_notice_milestones(profile, now=None):
    """Return notice milestones due now for trial, beta, or paid membership."""
    now = now or current_app_time({})
    plan = str(profile.get("plan") or "")
    if str(profile.get("membership_source") or "") == "beta":
        started = parse_datetime(profile.get("beta_started_at"))
        if not started:
            return []
        elapsed = max(0, (now.date() - started.date()).days)
        return [day for day in (18, 20, 21) if elapsed == day]
    if plan == "trial":
        started = parse_datetime(profile.get("trial_started_at"))
        if not started:
            return []
        elapsed = max(0, (now.date() - started.date()).days)
        return [day for day in (7, 12, 14) if elapsed == day]
    if plan.startswith("paid_"):
        paid_until = parse_datetime(profile.get("paid_until"))
        if not paid_until:
            return []
        days_left = (paid_until.date() - now.date()).days
        return [day for day in (7, 3, 1, 0) if days_left == day]
    return []


def _membership_notice_key(profile, milestone):
    if str(profile.get("membership_source") or "") == "beta":
        return f"beta:{profile.get('beta_started_at', '')}:{milestone}"
    if str(profile.get("plan") or "") == "trial":
        return f"trial:{profile.get('trial_started_at', '')}:{milestone}"
    return f"paid:{profile.get('paid_until', '')}:{milestone}"


def send_membership_lifecycle_notices(config, now=None):
    """Push one-button lifecycle reminders once per due membership milestone."""
    token = config.get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get(
        "LINE_CHANNEL_ACCESS_TOKEN", ""
    )
    if not token:
        return {
            "sent": 0,
            "skipped": 0,
            "error": "LINE_CHANNEL_ACCESS_TOKEN is not set",
        }, 400
    clock = now or current_app_time(config)
    sender = config.get("LINE_PUSH_SENDER") or line_push_message
    state = load_state(config["DATA_FILE"])
    sent = 0
    skipped = 0
    results = []
    for profile in (state.get("users") or {}).values():
        target = str(profile.get("line_user_id") or "").strip()
        if (
            not target
            or bool(profile.get("expiry_remind_opt_out"))
            or (
                str(profile.get("plan") or "") == "trial"
                and str(profile.get("membership_source") or "") != "beta"
            )
        ):
            continue
        completed = set(profile.get("membership_notice_keys_sent") or [])
        for milestone in membership_notice_milestones(profile, now=clock):
            notice_key = _membership_notice_key(profile, milestone)
            if notice_key in completed:
                skipped += 1
                continue
            message = build_expiry_remind_flex(profile, now=clock)
            message["altText"] = (
                "每日問候方案即將到期"
                if milestone not in (0, 14, 21)
                else "每日問候方案今天到期"
            )
            retry_key = _line_retry_key(
                f"membership-lifecycle:{target}:{notice_key}"
            )
            status = "sent"
            detail = ""
            try:
                _send_line_with_retry_key(sender, token, target, message, retry_key)
                completed.add(notice_key)
                sent += 1
            except Exception as exc:
                status = "failed"
                detail = str(exc)[:400]
                skipped += 1
            append_notification_log(
                state,
                "membership_lifecycle",
                target,
                status,
                message.get("altText") or "方案到期提醒",
                detail,
            )
            results.append({
                "line_user_id": target,
                "milestone": milestone,
                "status": status,
            })
        profile["membership_notice_keys_sent"] = sorted(completed)
    save_state(config["DATA_FILE"], state)
    return {"sent": sent, "skipped": skipped, "results": results}, 200


def send_trial_milestone_notices(config, now=None):
    """Claim, deliver and atomically finalize each 14-day experience milestone."""
    token = config.get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get(
        "LINE_CHANNEL_ACCESS_TOKEN", ""
    )
    if not token:
        return {
            "sent": 0,
            "skipped": 0,
            "error": "LINE_CHANNEL_ACCESS_TOKEN is not set",
        }, 400
    clock = now or current_app_time(config)
    sender = config.get("LINE_PUSH_SENDER") or line_push_message
    sent = 0
    skipped = 0
    results = []
    claims = mutate_state_atomically(
        config["DATA_FILE"],
        lambda state: _claim_trial_milestone_notices(state, clock),
    )
    for claim in claims:
        target = claim["line_user_id"]
        day = claim["day"]
        state = load_state(config["DATA_FILE"])
        profile = (state.get("users") or {}).get(target) or {}
        message = build_expiry_remind_flex(profile, now=clock)
        if day == 7:
            message["altText"] = "14 天安心體驗已進行 7 天"
        elif day == 12:
            message["altText"] = "14 天安心體驗還剩 2 天"
        else:
            message["altText"] = "14 天安心體驗今天到期"
        retry_key = _line_retry_key(
            f"trial-milestone:{target}:{claim['trial_started_at']}:{day}"
        )
        status = "sent"
        detail = ""
        try:
            _send_line_with_retry_key(sender, token, target, message, retry_key)
            sent += 1
        except Exception as exc:
            status = "failed"
            detail = str(exc)[:400]
            skipped += 1
        mutate_state_atomically(
            config["DATA_FILE"],
            lambda saved_state, current_claim=claim,
            current_status=status, current_detail=detail:
                _finish_trial_milestone_notice(
                    saved_state,
                    current_claim,
                    message.get("altText") or "14 天體驗提醒",
                    current_status,
                    current_detail,
                ),
        )
        results.append({
            "line_user_id": target,
            "day": day,
            "status": status,
        })
    return {"sent": sent, "skipped": skipped, "results": results}, 200


def send_renewal_reminders(config):
    """Scheduled beta/paid expiry reminders with a single upgrade CTA."""
    return send_membership_lifecycle_notices(
        config, now=current_app_time(config)
    )


def resolve_contact_role(contact):
    """守護人 vs 緊急聯絡人。

    只用 ``contact_role``（或明確的 type / kind）。
    **不可**讀 ``role``：該欄在 bound_guardians 表示「核心／一般」層級，
    若誤當成 contact_role 會把守護人列濾空，出現 count≥1 但列表空白。
    """
    if not isinstance(contact, dict):
        return "guardian"
    raw = str(
        contact.get("contact_role")
        or contact.get("type")
        or contact.get("kind")
        or ""
    ).strip().lower()
    if raw in ("emergency", "emergency_contact", "聯絡人", "緊急聯絡人"):
        return "emergency"
    return "guardian"


def normalize_contact(contact, index):
    """正規化守護人聯絡人資料,包含穩定 id 與時間戳。

    規則:
    - id 一旦建立就不變(沒給就用 f"contact-{index+1}")
    - is_primary 從 contact.get("is_primary") 讀,沒給就看 priority 是否 = 1
    - binding_status: unbound / pending / accepted / declined
    - line_user_id 跟 line_id 同義(新欄位優先)
    - created_at 與 updated_at 為 ISO 8601 字串
    - contact_role: guardian（核心守護人）| emergency（聯絡人）
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
    contact_role = resolve_contact_role(contact)
    return {
        "id": contact_id,
        "name": str(contact.get("name") or "").strip(),
        "relationship": str(contact.get("relationship") or "").strip(),
        "phone": str(contact.get("phone") or "").strip(),
        "email": str(contact.get("email") or "").strip(),
        # Keep both keys so bind / SOS / admin all see the same LINE id
        "line_user_id": line_user_id,
        "line_id": line_user_id,
        "binding_status": str(contact.get("binding_status") or ("accepted" if line_user_id else "unbound")),
        "is_primary": is_primary,
        "contact_role": contact_role,
        "notify_methods": methods,
        "priority": priority,
        "consent_status": str(contact.get("consent_status") or "pending"),
        "available_time": str(contact.get("available_time") or "").strip(),
        "note": str(contact.get("note") or "").strip(),
        "created_at": str(contact.get("created_at") or ""),
        "updated_at": str(contact.get("updated_at") or ""),
        "accepted_at": str(contact.get("accepted_at") or "").strip(),
        "invited_by": str(contact.get("invited_by") or "").strip(),
        # LINE 暱稱（綁定時自 profile 寫入；列表主標籤用，勿顯示 raw userId）
        "display_name": str(
            contact.get("display_name")
            or contact.get("line_display_name")
            or ""
        ).strip(),
        "line_display_name": str(
            contact.get("line_display_name")
            or contact.get("display_name")
            or ""
        ).strip(),
        # LINE 頭像（綁定／register 寫入；列表 UI 顯示用，不是後台內部 UID）
        "picture_url": str(contact.get("picture_url") or contact.get("pictureUrl") or "").strip(),
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

    # 注意：payload 的 line_user_id 多半是「會員本人」認證欄，不是守護人 LINE。
    # 表單新增／編輯不可由此寫入 LINE 綁定；真正綁定只走 bind_emergency_contact(invite_from)。
    cleaned = {
        "name": name,
        "relationship": relationship,
        "phone": phone,
        "email": email,
        "is_primary": bool(contact.get("is_primary", False)),
        "contact_role": resolve_contact_role(contact),
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
        and (get_contact_line_id(contact) or contact.get("consent_status") == "accepted")
    )


def enrich_contact_peer_picture(state, contact):
    """用對方 LINE 會員 profile 補齊聯絡人 picture_url（缺圖時）。回傳是否變更。"""
    if not isinstance(contact, dict):
        return False
    lid = get_contact_line_id(contact)
    if not lid:
        return False
    current = str(contact.get("picture_url") or contact.get("pictureUrl") or "").strip()
    if current:
        if contact.get("picture_url") != current:
            contact["picture_url"] = current
            return True
        return False
    peer = (state.get("users") or {}).get(lid) if isinstance(state, dict) else None
    if not isinstance(peer, dict):
        return False
    pic = str(peer.get("picture_url") or "").strip()
    if not pic:
        return False
    contact["picture_url"] = pic
    return True


def enrich_contact_peer_display_name(state, contact):
    """用對方 LINE 會員 profile 補齊聯絡人 display_name／line_display_name。回傳是否變更。"""
    if not isinstance(contact, dict):
        return False
    lid = get_contact_line_id(contact)
    if not lid:
        return False
    current = str(
        contact.get("line_display_name") or contact.get("display_name") or ""
    ).strip()
    if current and not is_placeholder_display_name(current):
        # 正規化雙欄位
        changed = False
        if contact.get("display_name") != current:
            contact["display_name"] = current
            changed = True
        if contact.get("line_display_name") != current:
            contact["line_display_name"] = current
            changed = True
        return changed
    peer = (state.get("users") or {}).get(lid) if isinstance(state, dict) else None
    if not isinstance(peer, dict):
        return False
    nick = str(peer.get("display_name") or "").strip()
    if not nick or is_placeholder_display_name(nick):
        return False
    contact["display_name"] = nick
    contact["line_display_name"] = nick
    return True


def get_contacts(data_file, line_user_id=None):
    state = load_state(data_file)
    profile = get_profile(state, line_user_id)
    if scrub_self_line_ids_on_contacts(profile):
        save_state(data_file, state)
    raw_contacts = list(profile.get("contacts") or [])
    contacts = []
    changed = False
    for index, contact in enumerate(raw_contacts):
        if not isinstance(contact, dict):
            continue
        normalized = normalize_contact(contact, index)
        for key, value in contact.items():
            if key in ("role",):
                continue  # 核心／一般，不可寫回混淆 contact_role
            if key not in normalized and value not in (None, ""):
                normalized[key] = value
        normalized["contact_role"] = resolve_contact_role(
            {"contact_role": contact.get("contact_role") or normalized.get("contact_role")}
        )
        if contact.get("contact_role") != normalized["contact_role"] or "contact_role" not in contact:
            changed = True
        if enrich_contact_peer_picture(state, normalized):
            # 回寫到原始列，之後列表／會員中心就能看到頭像
            contact["picture_url"] = normalized["picture_url"]
            changed = True
        if enrich_contact_peer_display_name(state, normalized):
            contact["display_name"] = normalized["display_name"]
            contact["line_display_name"] = normalized["line_display_name"]
            changed = True
        contacts.append(normalized)
    if changed:
        profile["contacts"] = contacts
        save_state(data_file, state)
    return {
        "line_user_id": profile.get("line_user_id"),
        "contacts": contacts,
        "contact_limit": plan_rules(profile)["contact_limit"],
        "plan": profile.get("plan", "trial"),
        "guardian_details_complete": any(complete_guardian_contact(contact) for contact in contacts),
        "guardian_details_reminder_enabled": bool(profile.get("guardian_details_reminder_enabled", True)),
    }


def add_single_contact(data_file, line_user_id, contact_payload):
    """新增單一聯絡人,回傳 (status_code, response_dict)。"""
    state = load_state(data_file)
    profile = state.get("users", {}).get(line_user_id)
    if not profile:
        return {"error": "user not registered", "line_user_id": line_user_id}, 404
    existing = profile.get("contacts") or []
    rules = plan_rules(profile)
    limit = int(rules.get("contact_limit") or 1)
    core_limit = int(rules.get("core_guardian_alert_limit") or 1)
    emergency_limit = int(rules.get("emergency_contact_limit") or 2)
    role_hint = resolve_contact_role(contact_payload or {})
    guardians = [c for c in existing if resolve_contact_role(c) == "guardian"]
    emergencies = [c for c in existing if resolve_contact_role(c) == "emergency"]
    if role_hint == "emergency":
        if len(emergencies) >= emergency_limit:
            return {
                "error": "contact_limit_exceeded",
                "code": "contact_limit",
                "contact_limit": emergency_limit,
                "current_count": len(emergencies),
                "message": (
                    f"緊急聯絡人已達方案上限 {emergency_limit} 位。"
                    f"升級可新增更多緊急聯絡人。"
                ),
            }, 400
    elif len(guardians) >= core_limit:
        return {
            "error": "contact_limit_exceeded",
            "code": "contact_limit",
            "contact_limit": core_limit,
            "current_count": len(guardians),
            "message": (
                f"你已經有 {len(guardians)} 位核心守護人囉（目前方案上限 {core_limit} 位）。"
                f"升級可新增更多守護人。"
            ),
        }, 400
    if len(existing) >= limit:
        return {
            "error": "contact_limit_exceeded",
            "code": "contact_limit",
            "contact_limit": limit,
            "current_count": len(existing),
            "message": (
                f"聯絡人名額已滿（目前方案上限 {limit} 位）。"
                f"升級可新增更多聯絡人。"
            ),
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
    # 表單路徑：绝不写入 LINE 绑定栏（避免把本人 line_user_id 当成守护人）
    cleaned["line_user_id"] = ""
    cleaned["line_id"] = ""
    cleaned["binding_status"] = "unbound"
    cleaned["consent_status"] = "pending"
    # primary 邏輯:設為主要時自動取消其他
    if cleaned["is_primary"]:
        for c in existing:
            c["is_primary"] = False
            c["updated_at"] = now
    existing.append(cleaned)
    profile["contacts"] = existing
    ensure_onboarding_completed_flag(profile)
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
    # 保留既有 LINE 邀請綁定欄；表單編輯不可覆寫／不可把本人 ID 寫入
    prev = existing[idx]
    for key in (
        "line_user_id",
        "line_id",
        "binding_status",
        "consent_status",
        "accepted_at",
        "invited_by",
        "notify_methods",
    ):
        if key in prev and key not in cleaned:
            cleaned[key] = prev.get(key)
        elif key in ("line_user_id", "line_id", "binding_status", "consent_status", "accepted_at", "invited_by"):
            cleaned[key] = prev.get(key)
    owner = str(line_user_id or "").strip()
    if get_contact_line_id(cleaned) == owner:
        cleaned["line_user_id"] = ""
        cleaned["line_id"] = ""
        if cleaned.get("binding_status") == "accepted":
            cleaned["binding_status"] = "unbound"
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
    """Atomically remove a contact and the reciprocal guardian relationship."""
    result = {}

    def remove_relationship(state):
        profile = (state.get("users") or {}).get(line_user_id)
        if not isinstance(profile, dict):
            result.update(
                {"error": "user not registered", "line_user_id": line_user_id}
            )
            return
        existing = list(profile.get("contacts") or [])
        removed = next(
            (
                contact
                for contact in existing
                if str(contact.get("id") or "") == contact_id
            ),
            None,
        )
        if removed is None:
            result.update(
                {"error": "contact_not_found", "contact_id": contact_id}
            )
            return

        peer_id = get_contact_line_id(removed)
        is_reciprocal_guardian = bool(
            peer_id
            and resolve_contact_role(removed) == "guardian"
            and contact_is_bound_guardian(removed, line_user_id)
        )
        profile["contacts"] = [
            contact
            for contact in existing
            if str(contact.get("id") or "") != contact_id
        ]
        if profile["contacts"] and not any(
            bool(contact.get("is_primary"))
            for contact in profile["contacts"]
            if resolve_contact_role(contact) == "guardian"
        ):
            next_guardian = next(
                (
                    contact
                    for contact in profile["contacts"]
                    if resolve_contact_role(contact) == "guardian"
                ),
                None,
            )
            if next_guardian is not None:
                next_guardian["is_primary"] = True

        if is_reciprocal_guardian:
            profile["guarding_for"] = [
                value
                for value in (profile.get("guarding_for") or [])
                if str(value or "") != peer_id
            ]
            profile["guarding_details"] = [
                row
                for row in (profile.get("guarding_details") or [])
                if str((row or {}).get("line_user_id") or "") != peer_id
            ]
            peer = (state.get("users") or {}).get(peer_id)
            if isinstance(peer, dict):
                peer["contacts"] = [
                    contact
                    for contact in (peer.get("contacts") or [])
                    if get_contact_line_id(contact) != line_user_id
                ]
                peer["guarding_for"] = [
                    value
                    for value in (peer.get("guarding_for") or [])
                    if str(value or "") != line_user_id
                ]
                peer["guarding_details"] = [
                    row
                    for row in (peer.get("guarding_details") or [])
                    if str((row or {}).get("line_user_id") or "") != line_user_id
                ]
                if peer["contacts"] and not any(
                    bool(contact.get("is_primary"))
                    for contact in peer["contacts"]
                    if resolve_contact_role(contact) == "guardian"
                ):
                    next_peer_guardian = next(
                        (
                            contact
                            for contact in peer["contacts"]
                            if resolve_contact_role(contact) == "guardian"
                        ),
                        None,
                    )
                    if next_peer_guardian is not None:
                        next_peer_guardian["is_primary"] = True

                if (
                    str(peer.get("profile_completion_peer_line_user_id") or "")
                    == line_user_id
                ):
                    peer["profile_completion_required"] = False
                    peer["profile_completion_cancelled_at"] = iso_now()
                    for key in (
                        "profile_completion_peer_line_user_id",
                        "profile_completion_bound_at",
                        "profile_completion_reminder_days",
                    ):
                        peer.pop(key, None)

            if (
                str(profile.get("profile_completion_peer_line_user_id") or "")
                == peer_id
            ):
                profile["profile_completion_required"] = False
                profile["profile_completion_cancelled_at"] = iso_now()
                for key in (
                    "profile_completion_peer_line_user_id",
                    "profile_completion_bound_at",
                    "profile_completion_reminder_days",
                ):
                    profile.pop(key, None)

        result.update(
            {
                "deleted": True,
                "contact_id": contact_id,
                "contacts": copy.deepcopy(profile["contacts"]),
            }
        )

    mutate_state_atomically(data_file, remove_relationship)
    if result.get("error") == "user not registered":
        return result, 404
    if result.get("error") == "contact_not_found":
        return result, 404
    return result, 200




def _merge_contact_binding_fields(incoming, previous):
    """Merge LINE bind fields from stored contact when payload omits them."""
    if not isinstance(incoming, dict):
        return incoming
    prev = previous if isinstance(previous, dict) else {}
    for key in (
        "line_user_id",
        "line_id",
        "binding_status",
        "consent_status",
        "accepted_at",
        "invited_by",
        "created_at",
        "is_primary",
        "contact_role",
    ):
        new_val = incoming.get(key)
        old_val = prev.get(key)
        if key in ("line_user_id", "line_id"):
            if not str(new_val or "").strip() and str(old_val or "").strip():
                incoming[key] = old_val
        elif key in ("binding_status", "consent_status"):
            # Don't downgrade accepted → unbound when client omits bind state.
            if (not new_val or new_val == "unbound" or new_val == "pending") and old_val == "accepted":
                if key == "binding_status" and not get_contact_line_id(incoming) and get_contact_line_id(prev):
                    incoming["line_user_id"] = get_contact_line_id(prev)
                    incoming["line_id"] = get_contact_line_id(prev)
                incoming[key] = old_val
            elif not new_val and old_val:
                incoming[key] = old_val
        elif not new_val and old_val not in (None, ""):
            incoming[key] = old_val
    # Keep both LINE id keys in sync after merge.
    lid = get_contact_line_id(incoming)
    if lid:
        incoming["line_user_id"] = lid
        incoming["line_id"] = lid
        if incoming.get("binding_status") in (None, "", "unbound") and prev.get("binding_status") == "accepted":
            incoming["binding_status"] = "accepted"
    return incoming


def save_contacts(data_file, payload):
    """Replace contact list but merge bind fields per id — never wipe LINE binds."""
    state = load_state(data_file)
    profile = get_profile(state, payload.get("line_user_id"))
    previous = list(profile.get("contacts") or [])
    by_id = {str(c.get("id") or ""): c for c in previous if isinstance(c, dict)}
    by_line = {}
    for c in previous:
        if not isinstance(c, dict):
            continue
        lid = get_contact_line_id(c)
        if lid:
            by_line[lid] = c

    contacts = []
    for index, contact in enumerate(payload.get("contacts") or []):
        normalized = normalize_contact(contact, index)
        prev = by_id.get(str(normalized.get("id") or ""))
        if not prev:
            prev = by_line.get(get_contact_line_id(normalized))
        contacts.append(_merge_contact_binding_fields(normalized, prev))
    contacts.sort(key=lambda contact: contact.get("priority", 9999))
    for index, contact in enumerate(contacts):
        contact["priority"] = index + 1
    limit = plan_rules(profile)["contact_limit"]
    if len(contacts) > limit:
        return {
            "error": "contact_limit_exceeded",
            "code": "contact_limit",
            "contact_limit": limit,
            "message": (
                f"你已經有 {limit} 位守護人囉（目前方案上限）。"
                f"升級可新增更多守護人。"
            ),
        }, 400
    if payload.get("require_complete_guardian") and profile.get("plan") in {"paid_799", "paid_799_year"}:
        if not any(complete_guardian_contact(contact) for contact in contacts):
            return {
                "error": "799 plan requires at least one bound guardian with name, relationship and phone",
                "required_fields": ["name", "relationship", "phone"],
            }, 400
    profile["contacts"] = contacts
    save_state(data_file, state)
    return get_contacts(data_file, payload.get("line_user_id")), 200


ALREADY_BOUND_MESSAGE = "這位好友已經綁定，不能重複綁定；請返回並改選其他好友"
CONTACT_LIMIT_MESSAGE = "對方的守護人名額已滿，請請對方升級方案後再邀請你"


def detect_reverse_invite(state, inviter_id, invitee_id):
    """對方是否已單向守護邀請人（反向互綁情境）。

    True when:
    - invitee already has inviter as an accepted LINE guardian contact, OR
    - invitee is already listed in inviter.guarding_for
    """
    inviter_id = str(inviter_id or "").strip()
    invitee_id = str(invitee_id or "").strip()
    if not inviter_id or not invitee_id or inviter_id == invitee_id:
        return False
    users = (state or {}).get("users") or {}
    invitee = users.get(invitee_id) if isinstance(users.get(invitee_id), dict) else {}
    inviter = users.get(inviter_id) if isinstance(users.get(inviter_id), dict) else {}

    for contact in invitee.get("contacts") or []:
        if get_contact_line_id(contact) == inviter_id and contact_is_bound_guardian(
            contact, invitee_id
        ):
            return True

    guarding = [
        str(x or "").strip()
        for x in (inviter.get("guarding_for") or [])
        if str(x or "").strip()
    ]
    return invitee_id in guarding


def apply_is_primary_to_contact_line(profile, contact_line_user_id, *, make_core=True):
    """Set/unset is_primary for a contact by LINE id; enforce core_guardian_alert_limit.

    Returns True if a matching contact row was found and updated.
    """
    if not isinstance(profile, dict):
        return False
    target_lid = str(contact_line_user_id or "").strip()
    if not target_lid:
        return False
    contacts = list(profile.get("contacts") or [])
    target_idx = None
    for i, contact in enumerate(contacts):
        if get_contact_line_id(contact) == target_lid:
            target_idx = i
            break
    if target_idx is None:
        return False

    limit = int(plan_rules(profile).get("core_guardian_alert_limit") or 1)
    now = iso_now()
    if make_core:
        contacts[target_idx]["is_primary"] = True
        contacts[target_idx]["updated_at"] = now
        core_idxs = [i for i, c in enumerate(contacts) if bool(c.get("is_primary"))]
        if len(core_idxs) > limit:
            core_idxs_sorted = sorted(
                core_idxs,
                key=lambda i: int(contacts[i].get("priority") or 9999),
            )
            keep = set(core_idxs_sorted[:limit])
            if target_idx not in keep:
                keep = set(core_idxs_sorted[: max(0, limit - 1)] + [target_idx])
                keep = set(list(keep)[:limit])
            for i, c in enumerate(contacts):
                if bool(c.get("is_primary")) and i not in keep:
                    c["is_primary"] = False
                    c["updated_at"] = now
    else:
        contacts[target_idx]["is_primary"] = False
        contacts[target_idx]["updated_at"] = now
        if contacts and not any(bool(c.get("is_primary")) for c in contacts):
            ranked = sorted(
                range(len(contacts)),
                key=lambda i: int(contacts[i].get("priority") or 9999),
            )
            contacts[ranked[0]]["is_primary"] = True
            contacts[ranked[0]]["updated_at"] = now

    profile["contacts"] = contacts
    return True


GUARDIAN_INVITE_EXPIRY_DAYS = 7
PROFILE_COMPLETION_REMINDER_DAYS = (0, 1, 3, 7)


def create_guardian_invite(data_file, inviter_line_user_id, payload, now=None):
    """Persist only the pre-share nickname/relationship; no contact is bound here."""
    inviter_id = str(inviter_line_user_id or "").strip()
    if not inviter_id:
        return {"ok": False, "error": "missing inviter", "code": "missing_ids"}, 400
    payload = payload if isinstance(payload, dict) else {}
    display_name = str(payload.get("display_name") or payload.get("contact_display_name") or "親友").strip()
    relationship = str(payload.get("relationship") or "守護人").strip()
    now = now or current_app_time({})
    state = load_state(data_file)
    get_profile(state, inviter_id)
    invite_token = secrets.token_urlsafe(32)
    invite = {
        "id": secrets.token_urlsafe(12),
        "invite_token": invite_token,
        "inviter_line_user_id": inviter_id,
        "display_name": display_name,
        "relationship": relationship,
        "status": "pending",
        "created_at": now.isoformat(timespec="seconds"),
        "expires_at": (now + timedelta(days=GUARDIAN_INVITE_EXPIRY_DAYS)).isoformat(timespec="seconds"),
    }
    state.setdefault("guardian_invites", []).append(invite)
    state["guardian_invites"] = state["guardian_invites"][-100:]
    save_state(data_file, state)
    return {"ok": True, **invite}, 201


def _guardian_invite_for_token(state, inviter_id, invite_token, now=None):
    """Resolve exactly one invite token and normalize its lifecycle state."""
    now = now or current_app_time({})
    token = str(invite_token or "").strip()
    if not token:
        return None, "invalid"
    for invite in reversed(state.get("guardian_invites") or []):
        if not isinstance(invite, dict):
            continue
        if invite.get("inviter_line_user_id") != inviter_id:
            continue
        if not secrets.compare_digest(str(invite.get("invite_token") or ""), token):
            continue
        if invite.get("status") == "accepted":
            return invite, "used"
        if invite.get("status") == "expired":
            return invite, "expired"
        try:
            expiry = datetime.fromisoformat(str(invite.get("expires_at") or ""))
        except ValueError:
            expiry = now
        if expiry <= now:
            invite["status"] = "expired"
            return invite, "expired"
        if invite.get("status") != "pending":
            return invite, "invalid"
        return invite, "pending"
    return None, "invalid"


def _pending_guardian_invite(state, inviter_id, now=None, invite_token=""):
    now = now or current_app_time({})
    if str(invite_token or "").strip():
        invite, status = _guardian_invite_for_token(
            state, inviter_id, invite_token, now
        )
        return invite if status == "pending" else None
    rows = state.get("guardian_invites") or []
    for invite in reversed(rows):
        if not isinstance(invite, dict) or invite.get("inviter_line_user_id") != inviter_id:
            continue
        if invite.get("status") != "pending":
            continue
        try:
            expiry = datetime.fromisoformat(str(invite.get("expires_at") or ""))
        except ValueError:
            expiry = now
        if expiry <= now:
            invite["status"] = "expired"
            continue
        return invite
    return None


def invite_bind_preview(data_file, payload):
    """Preview guardian invite: is_reverse_invite + inviter display name for LIFF modal."""
    inviter_id = str(
        payload.get("invite_from")
        or payload.get("inviter_line_user_id")
        or payload.get("from")
        or ""
    ).strip()
    invitee_id = str(
        payload.get("line_user_id")
        or payload.get("contact_line_user_id")
        or ""
    ).strip()
    if not inviter_id or not invitee_id:
        return {"ok": False, "error": "缺少邀請人或本人資料", "code": "missing_ids"}, 400
    if inviter_id == invitee_id:
        return {"ok": False, "error": "不能綁定自己成為守護人", "code": "self_bind"}, 400

    state = load_state(data_file)
    users = state.get("users") or {}
    inviter = users.get(inviter_id) if isinstance(users.get(inviter_id), dict) else {}
    invitee = users.get(invitee_id) if isinstance(users.get(invitee_id), dict) else {}
    is_reverse = detect_reverse_invite(state, inviter_id, invitee_id)
    inviter_name = str(inviter.get("display_name") or "").strip() or "親友"
    inviter_rules = plan_rules(inviter or {"plan": "trial"})
    invitee_rules = plan_rules(invitee or {"plan": "trial"})
    inviter_invites = [
        row for row in (state.get("guardian_invites") or [])
        if isinstance(row, dict) and row.get("inviter_line_user_id") == inviter_id
    ]
    invite_token = str(payload.get("invite_token") or "").strip()
    pending = None
    if inviter_invites:
        matched, invite_status = _guardian_invite_for_token(
            state, inviter_id, invite_token
        )
        if invite_status == "used":
            save_state(data_file, state)
            return {"ok": False, "error": "邀請已使用", "code": "invite_used"}, 410
        if invite_status == "expired":
            save_state(data_file, state)
            return {"ok": False, "error": "邀請已超過七天，請對方重新分享", "code": "invite_expired"}, 410
        if invite_status != "pending":
            return {"ok": False, "error": "邀請連結無效", "code": "invalid_invite_token"}, 403
        pending = matched
    return {
        "ok": True,
        "is_reverse_invite": is_reverse,
        "inviter_line_user_id": inviter_id,
        "inviter_display_name": inviter_name,
        "invitee_line_user_id": invitee_id,
        "mutual_core_available": is_reverse,
        "inviter_core_guardian_alert_limit": int(
            inviter_rules.get("core_guardian_alert_limit") or 1
        ),
        "invitee_core_guardian_alert_limit": int(
            invitee_rules.get("core_guardian_alert_limit") or 1
        ),
        "invite_status": (pending or {}).get("status") or "legacy",
        "guardian_purpose": "你會收到對方的報平安、逾時未報平安、SOS 與安全守護通知。",
        "privacy_explanation": "定位只在對方主動求助或啟用安全守護時通知；你可隨時解除綁定，資料只用於守護通知。",
        "requires_reciprocal_consent": False,
        "message": (
            f"{inviter_name} 已是你的守護人；本次邀請仍需你另外同意，才會新增另一方向的守護關係。"
            if is_reverse
            else "您收到一位親友的守護邀請"
        ),
    }, 200


def build_bind_success_notices(inviter, contacts, inviter_id, guardian_name, *, invite_reward_applied=False):
    """Same bind-success LINE copy used by live bind + historical backfill."""
    inviter_name = (inviter or {}).get("display_name") or "使用者"
    guardian_name = guardian_name or "守護人"
    bound_rows = [c for c in (contacts or []) if contact_is_bound_guardian(c, inviter_id)]
    core_n = sum(1 for c in bound_rows if c.get("is_primary"))
    if bound_rows and core_n == 0:
        core_n = 1
    inviter_notice = (
        "✅ 綁定成功\n\n"
        f"對方：{guardian_name}（已成為你的守護人）\n"
        f"目前：核心守護人 {len(bound_rows)} 位。\n\n"
        "之後若你逾時未報平安或發出 SOS，系統會透過 LINE 私訊通知對方。\n"
        "請點「完成資料」補齊自己的聯絡資料；LINE 通知已立即啟用。"
    )
    guardian_notice = (
        f"✅ 綁定成功\n\n"
        f"對方：{inviter_name}\n"
        f"你已成為對方的守護人。\n\n"
        f"之後會在以下情況透過 LINE 私訊通知你：\n"
        f"⚠️ 對方在提醒後仍未報平安（依第一、第二、第三順位逐步通知）\n"
        f"🚨 對方發出 SOS 緊急求助\n\n"
        f"謝謝你願意成為對方最安心的依靠。"
    )
    return inviter_notice, guardian_notice


def pair_already_dual_bind_notified(state, inviter_id, guardian_id):
    """Detect recent dual bind-success pushes from notification_logs (post-bn)."""
    inviter_id = str(inviter_id or "").strip()
    guardian_id = str(guardian_id or "").strip()
    if not inviter_id or not guardian_id:
        return False
    inviter_ok = False
    guardian_ok = False
    for log in state.get("notification_logs") or []:
        if not isinstance(log, dict):
            continue
        if log.get("kind") != "binding_complete" or log.get("status") != "sent":
            continue
        uid = str(log.get("line_user_id") or "").strip()
        msg = str(log.get("message") or "")
        if uid == inviter_id and (
            "守護人綁定完成" in msg
            or "感謝邀請成功" in msg
            or ("綁定成功" in msg and "已成為你的守護人" in msg)
        ):
            inviter_ok = True
        if uid == guardian_id and (
            "你已接受邀請" in msg
            or "你已成為對方的守護人" in msg
            or ("綁定成功" in msg and "守護人" in msg)
        ):
            guardian_ok = True
        if inviter_ok and guardian_ok:
            return True
    return False


def iter_accepted_line_bind_pairs(state):
    """Yield (inviter_id, inviter_profile, contact_row, guardian_id) for accepted LINE binds."""
    for inviter_id, inviter in (state.get("users") or {}).items():
        inviter_id = str(inviter_id or "").strip()
        if not inviter_id or not isinstance(inviter, dict):
            continue
        for contact in inviter.get("contacts") or []:
            if not isinstance(contact, dict):
                continue
            if not contact_is_bound_guardian(contact, inviter_id):
                continue
            guardian_id = get_contact_line_id(contact)
            if not guardian_id or guardian_id == inviter_id:
                continue
            yield inviter_id, inviter, contact, guardian_id


def backfill_bind_notify(config, *, dry_run=False, limit=0):
    """One-shot: resend bind-success LINE to both sides for historical accepted binds.

    Idempotent via contact.bind_notify_sent_at; also skips pairs already dual-notified
    in recent notification_logs (post W250724bn dual notify).
    """
    token = (
        (config.get("LINE_CHANNEL_ACCESS_TOKEN") if hasattr(config, "get") else None)
        or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
        or os.environ.get("CHANNEL_ACCESS_TOKEN", "")
    )
    if not token and not dry_run:
        return {"ok": False, "error": "LINE_CHANNEL_ACCESS_TOKEN is not set", "pairs_notified": 0}, 400

    data_file = config["DATA_FILE"]
    state = load_state(data_file)
    sender = (config.get("LINE_PUSH_SENDER") if hasattr(config, "get") else None) or line_push_message
    now_stamp = current_app_time(config).isoformat(timespec="seconds")
    try:
        limit_n = int(limit or 0)
    except (TypeError, ValueError):
        limit_n = 0

    pairs_total = 0
    pairs_notified = 0
    pairs_skipped = 0
    pairs_failed = 0
    pairs_marked_only = 0
    pairs_attempted = 0
    results = []

    for inviter_id, inviter, contact, guardian_id in iter_accepted_line_bind_pairs(state):
        pairs_total += 1
        if limit_n > 0 and pairs_attempted >= limit_n:
            break

        if str(contact.get("bind_notify_sent_at") or "").strip():
            pairs_skipped += 1
            results.append(
                {
                    "inviter_line_user_id": inviter_id,
                    "guardian_line_user_id": guardian_id,
                    "status": "skipped_already_flagged",
                }
            )
            continue

        if pair_already_dual_bind_notified(state, inviter_id, guardian_id):
            if not dry_run:
                contact["bind_notify_sent_at"] = now_stamp
            pairs_marked_only += 1
            pairs_attempted += 1
            results.append(
                {
                    "inviter_line_user_id": inviter_id,
                    "guardian_line_user_id": guardian_id,
                    "status": "marked_already_notified",
                }
            )
            continue

        guardian_name = (
            str(contact.get("name") or "").strip()
            or ((state.get("users") or {}).get(guardian_id) or {}).get("display_name")
            or "守護人"
        )
        inviter_notice, guardian_notice = build_bind_success_notices(
            inviter,
            inviter.get("contacts") or [],
            inviter_id,
            guardian_name,
            invite_reward_applied=False,
        )

        if dry_run:
            pairs_notified += 1
            pairs_attempted += 1
            results.append(
                {
                    "inviter_line_user_id": inviter_id,
                    "guardian_line_user_id": guardian_id,
                    "status": "dry_run_would_notify",
                    "guardian_name": guardian_name,
                }
            )
            continue

        pairs_attempted += 1
        inviter_ok = False
        guardian_ok = False
        errors = []
        for line_user_id, message, who in (
            (inviter_id, inviter_notice, "inviter"),
            (guardian_id, guardian_notice, "guardian"),
        ):
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
                if who == "inviter":
                    inviter_ok = True
                else:
                    guardian_ok = True
            except Exception as exc:
                append_notification_log(
                    state, "binding_complete", line_user_id, "failed", message, str(exc)[:400]
                )
                errors.append({"who": who, "error": str(exc)[:400]})

        if inviter_ok and guardian_ok:
            contact["bind_notify_sent_at"] = now_stamp
            pairs_notified += 1
            results.append(
                {
                    "inviter_line_user_id": inviter_id,
                    "guardian_line_user_id": guardian_id,
                    "status": "notified",
                }
            )
        else:
            pairs_failed += 1
            results.append(
                {
                    "inviter_line_user_id": inviter_id,
                    "guardian_line_user_id": guardian_id,
                    "status": "failed",
                    "inviter_ok": inviter_ok,
                    "guardian_ok": guardian_ok,
                    "errors": errors,
                }
            )

    if not dry_run:
        save_state(data_file, state)

    return {
        "ok": True,
        "dry_run": bool(dry_run),
        "pairs_total_seen": pairs_total,
        "pairs_notified": pairs_notified,
        "pairs_skipped": pairs_skipped,
        "pairs_marked_only": pairs_marked_only,
        "pairs_failed": pairs_failed,
        "results": results,
    }, 200


def retry_pending_bind_notifications(config):
    """Retry only the failed side of a recent guardian bind, up to 3 attempts."""
    token = (
        config.get("LINE_CHANNEL_ACCESS_TOKEN")
        or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
        or os.environ.get("CHANNEL_ACCESS_TOKEN", "")
    )
    if not token:
        return {
            "sent": 0,
            "failed": 0,
            "skipped": 0,
            "error": "LINE_CHANNEL_ACCESS_TOKEN is not set",
        }, 400
    data_file = config["DATA_FILE"]
    state = load_state(data_file)
    sender = config.get("LINE_PUSH_SENDER") or line_push_message
    now = current_app_time(config)
    outcomes = []

    for inviter_id, inviter, contact, guardian_id in iter_accepted_line_bind_pairs(
        state
    ):
        if inviter.get("membership_paused") or not membership_access_active(
            inviter, now
        ):
            continue
        status_map = contact.get("bind_notify_status")
        if not isinstance(status_map, dict):
            continue
        guardian_name = (
            str(contact.get("name") or "").strip()
            or ((state.get("users") or {}).get(guardian_id) or {}).get(
                "display_name"
            )
            or "守護人"
        )
        inviter_notice, guardian_notice = build_bind_success_notices(
            inviter,
            inviter.get("contacts") or [],
            inviter_id,
            guardian_name,
            invite_reward_applied=False,
        )
        for who, target, message in (
            ("inviter", inviter_id, inviter_notice),
            ("guardian", guardian_id, guardian_notice),
        ):
            entry = status_map.get(who) or {}
            attempts = int(entry.get("attempts") or 0)
            if (
                entry.get("status") == "sent"
                or not entry.get("retryable")
                or attempts >= 3
            ):
                continue
            try:
                result = sender(token, target, message)
                outcomes.append(
                    {
                        "inviter_id": inviter_id,
                        "guardian_id": guardian_id,
                        "who": who,
                        "target": target,
                        "status": "sent",
                        "detail": json.dumps(result, ensure_ascii=False),
                    }
                )
            except Exception as exc:
                failure = classify_push_exception(exc)
                outcomes.append(
                    {
                        "inviter_id": inviter_id,
                        "guardian_id": guardian_id,
                        "who": who,
                        "target": target,
                        "status": "failed",
                        "detail": str(exc)[:400],
                        "retryable": failure.kind
                        in {"transient", "rate_limited"},
                    }
                )

    now_stamp = current_app_time(config).isoformat(timespec="seconds")

    def merge_retry_results(latest):
        for outcome in outcomes:
            latest_inviter = (latest.get("users") or {}).get(
                outcome["inviter_id"]
            ) or {}
            latest_contact = next(
                (
                    row
                    for row in (latest_inviter.get("contacts") or [])
                    if get_contact_line_id(row) == outcome["guardian_id"]
                ),
                None,
            )
            if latest_contact is None:
                continue
            latest_status = latest_contact.setdefault("bind_notify_status", {})
            entry = dict(latest_status.get(outcome["who"]) or {})
            entry["attempts"] = int(entry.get("attempts") or 0) + 1
            entry["status"] = outcome["status"]
            if outcome["status"] == "failed":
                entry["retryable"] = bool(outcome.get("retryable"))
            else:
                entry["retryable"] = False
                entry["sent_at"] = now_stamp
            latest_status[outcome["who"]] = entry
            append_notification_log(
                latest,
                "binding_complete",
                outcome["target"],
                outcome["status"],
                "綁定完成通知補送",
                outcome["detail"],
            )
            if all(
                (latest_status.get(key) or {}).get("status") == "sent"
                for key in ("inviter", "guardian")
            ):
                latest_contact["bind_notify_sent_at"] = now_stamp

    if outcomes:
        mutate_state_atomically(data_file, merge_retry_results)
    sent = sum(1 for row in outcomes if row["status"] == "sent")
    failed = sum(1 for row in outcomes if row["status"] == "failed")
    return {
        "sent": sent,
        "failed": failed,
        "skipped": 0,
        "results": outcomes,
    }, 200


def bind_emergency_contact(
    data_file, payload, config=None, *, _state_conflict_retries=1
):
    inviter_id = str(payload.get("inviter_line_user_id") or "").strip()
    contact_line_user_id = str(payload.get("contact_line_user_id") or "").strip()
    contact_display_name = str(payload.get("contact_display_name") or "LINE 聯絡人").strip()
    contact_relationship = str(payload.get("contact_relationship") or "").strip()
    contact_phone = str(payload.get("contact_phone") or "").strip()
    contact_picture_url = str(
        payload.get("contact_picture_url") or payload.get("picture_url") or ""
    ).strip()
    activate_trial = bool(payload.get("activate_trial"))
    legacy_reciprocal = "activate_trial" not in payload
    # 每一個守護方向都必須有自己的邀請與同意紀錄；舊客戶端即使傳入
    # mutual_core=true，也不能跳過第二次同意直接改成雙向核心守護。
    mutual_core = False
    if not inviter_id or not contact_line_user_id:
        return {"ok": False, "error": "缺少邀請人或守護人資料", "code": "missing_ids"}, 400
    if inviter_id == contact_line_user_id:
        return {"ok": False, "error": "不能綁定自己成為守護人", "code": "self_bind"}, 400

    # 核心守護人必須先加入「每日平安」官方 LINE；否則不能標記為綁定完成。
    friend_token = (
        ((config or {}).get("LINE_CHANNEL_ACCESS_TOKEN") if hasattr(config or {}, "get") else None)
        or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
        or os.environ.get("CHANNEL_ACCESS_TOKEN", "")
    )
    friend_profile = fetch_line_profile_dict(friend_token, contact_line_user_id) if friend_token else None
    if config and friend_token and not friend_profile:
        return {
            "ok": False,
            "bound": False,
            "error": "請先加入「每日平安」官方 LINE，再回來接受核心守護人邀請",
            "code": "official_line_friend_required",
            "official_line_friend": False,
        }, 409
    official_line_friend_verified_at = (
        datetime.now().isoformat(timespec="seconds") if friend_profile else ""
    )

    state = load_state(data_file)
    invite_token = str(payload.get("invite_token") or "").strip()
    inviter_invites = [
        row for row in (state.get("guardian_invites") or [])
        if isinstance(row, dict) and row.get("inviter_line_user_id") == inviter_id
    ]
    pending_invite = None
    invite_status = "legacy"
    if inviter_invites:
        pending_invite, invite_status = _guardian_invite_for_token(
            state,
            inviter_id,
            invite_token,
            current_app_time(config or {}),
        )
        if invite_status == "used":
            return {"ok": False, "error": "邀請已使用", "code": "invite_used"}, 410
        if invite_status == "expired":
            save_state(data_file, state)
            return {"ok": False, "error": "邀請已超過七天，請對方重新分享", "code": "invite_expired"}, 410
        if invite_status != "pending":
            return {"ok": False, "error": "邀請連結無效", "code": "invalid_invite_token"}, 403
    expired_invite = next(
        (
            row for row in (state.get("guardian_invites") or [])
            if isinstance(row, dict)
            and row.get("inviter_line_user_id") == inviter_id
            and row.get("status") == "expired"
        ),
        None,
    )
    if not inviter_invites and not pending_invite and expired_invite:
        save_state(data_file, state)
        return {"ok": False, "error": "邀請已超過七天，請對方重新分享", "code": "invite_expired"}, 410
    if pending_invite and not bool(payload.get("recipient_consent")):
        save_state(data_file, state)
        return {"ok": False, "error": "請先閱讀說明並同意成為核心守護人", "code": "consent_required"}, 409
    if pending_invite and "activate_trial" in payload and (
        not contact_display_name
        or contact_display_name == "LINE 聯絡人"
        or not contact_relationship
        or not contact_phone
    ):
        return {
            "ok": False,
            "error": "請填寫姓名、與邀請人的關係及電話後再完成綁定",
            "code": "guardian_profile_required",
            "required_fields": ["name", "relationship", "phone"],
        }, 400
    # 綁定前偵測反向：綁定後 guarding_for 一定會寫入，不可事後判斷
    is_reverse_invite = detect_reverse_invite(state, inviter_id, contact_line_user_id)
    inviter = get_profile(state, inviter_id)
    deduplicate_contact_line_bindings(inviter)
    # A person may remain a free guardian without consuming their one lifetime
    # trial/beta eligibility. Only explicit trial opt-in may claim it.
    contact_user = get_profile(
        state,
        contact_line_user_id,
        start_public_trial=bool(activate_trial or legacy_reciprocal),
    )
    contact_user["display_name"] = contact_display_name or contact_user.get("display_name") or "LINE 聯絡人"
    if contact_picture_url:
        contact_user["picture_url"] = contact_picture_url
    peer_picture = str(contact_picture_url or contact_user.get("picture_url") or "").strip()

    contacts = list(inviter.get("contacts") or [])
    guarding = list(contact_user.get("guarding_for") or [])
    already_guarding = inviter_id in guarding

    existing = next(
        (
            contact
            for contact in contacts
            if get_contact_line_id(contact) == contact_line_user_id
        ),
        None,
    )
    # A guardian relationship is unique per inviter/invitee pair. Collapse
    # legacy duplicate rows before applying the accepted invitation.
    duplicate_rows = [
        contact
        for contact in contacts
        if get_contact_line_id(contact) == contact_line_user_id
    ]
    if len(duplicate_rows) > 1:
        keep = existing
        for duplicate in duplicate_rows[1:]:
            for key, value in duplicate.items():
                if key not in keep or keep.get(key) in (None, "", [], {}):
                    keep[key] = value
        contacts = [
            contact
            for contact in contacts
            if contact is keep
            or get_contact_line_id(contact) != contact_line_user_id
        ]
    # 名額已滿時：優先把 LINE 綁到尚未綁定的聯絡人資料列（避免 Android 看到 contact_limit exceeded）
    unbound_slot = None
    if not existing:
        unbound_slot = next(
            (contact for contact in contacts if not get_contact_line_id(contact)),
            None,
        )

    already_accepted = bool(
        existing
        and (
            existing.get("consent_status") == "accepted"
            or existing.get("binding_status") == "accepted"
        )
    )
    # 反向索引已存在＝先前綁過，視為已完成（勿再當新綁定狂推）
    if already_guarding and not existing and not unbound_slot:
        already_accepted = True
    # 凍結「這次是否為重複綁定」——unbound_slot 合併後 existing 會變 truthy，不可再拿來當 already_bound
    was_duplicate = bool(already_accepted)

    accepted_at = datetime.now().isoformat(timespec="seconds")

    def _apply_line_bind_fields(row, *, is_new_accept):
        row["name"] = row.get("name") or contact_display_name or "LINE 聯絡人"
        # 綁定時持久化對方 LINE 暱稱（列表主標籤用，勿露出 raw userId）
        if contact_display_name and not is_placeholder_display_name(contact_display_name):
            row["display_name"] = contact_display_name
            row["line_display_name"] = contact_display_name
        elif not str(row.get("display_name") or row.get("line_display_name") or "").strip():
            peer_nick = str(contact_user.get("display_name") or "").strip()
            if peer_nick and not is_placeholder_display_name(peer_nick):
                row["display_name"] = peer_nick
                row["line_display_name"] = peer_nick
        row["line_id"] = contact_line_user_id
        row["line_user_id"] = contact_line_user_id
        row["consent_status"] = "accepted"
        row["binding_status"] = "accepted"
        if is_new_accept or not row.get("accepted_at"):
            row["accepted_at"] = row.get("accepted_at") or accepted_at
        row["invited_by"] = inviter_id
        row["notify_methods"] = list(dict.fromkeys([*(row.get("notify_methods") or []), "line"]))
        row["contact_role"] = "guardian"
        if official_line_friend_verified_at:
            row["official_line_friend"] = True
            row["official_line_friend_verified_at"] = official_line_friend_verified_at
        if peer_picture:
            row["picture_url"] = peer_picture
        elif not str(row.get("picture_url") or "").strip():
            row["picture_url"] = ""

    # LIFF 點擊授權即視為守護人本人同意綁定（不需再回「同意」）
    if existing:
        _apply_line_bind_fields(existing, is_new_accept=not was_duplicate)
    elif unbound_slot is not None:
        # 合併到既有未綁 LINE 的聯絡人列（常見：邀請人先填資料再分享邀請）
        _apply_line_bind_fields(unbound_slot, is_new_accept=True)
        unbound_slot["accepted_at"] = accepted_at
        existing = unbound_slot
    else:
        core_limit = int(plan_rules(inviter).get("core_guardian_alert_limit") or 1)
        guardian_count = sum(
            1 for c in contacts if resolve_contact_role(c) == "guardian"
        )
        if guardian_count >= core_limit:
            # 已是這位邀請人的守護人：當成功／已綁定，不要 400 英文錯誤
            if already_guarding:
                ensure_onboarding_completed_flag(inviter)
                save_state(data_file, state)
                return {
                    "ok": True,
                    "bound": True,
                    "already_bound": True,
                    "binding_complete": False,
                    "message": ALREADY_BOUND_MESSAGE,
                    "contact": None,
                    "reward": None,
                    "consent_request_sent": 0,
                    "test_messages_sent": 0,
                    "inviter_notified": False,
                    "guardian_notified": False,
                    "persistence": persistence_info(data_file),
                }, 200
            return {
                "ok": False,
                "error": CONTACT_LIMIT_MESSAGE,
                "code": "contact_limit",
                "contact_limit": core_limit,
                "message": CONTACT_LIMIT_MESSAGE,
            }, 400
        contacts.append(
            {
                "id": f"line-{contact_line_user_id}",
                "name": contact_display_name or "LINE 聯絡人",
                "display_name": contact_display_name or "",
                "line_display_name": contact_display_name or "",
                "relationship": contact_relationship or "守護人",
                "phone": contact_phone,
                "line_id": contact_line_user_id,
                "line_user_id": contact_line_user_id,
                "picture_url": peer_picture,
                "email": "",
                "available_time": "",
                "notify_methods": ["line"],
                "priority": len(contacts) + 1,
                "consent_status": "accepted",
                "binding_status": "accepted",
                "accepted_at": accepted_at,
                "invited_by": inviter_id,
                "contact_role": "guardian",
                "official_line_friend": bool(official_line_friend_verified_at),
                "official_line_friend_verified_at": official_line_friend_verified_at,
                "note": "LINE 一鍵授權綁定",
            }
        )
    # Always write back so shallow-list mutations + new rows both persist
    # 首位守護人自動設為核心（is_primary）
    if existing is not None:
        existing["contact_role"] = "guardian"
        existing["is_primary"] = True
    elif contacts:
        contacts[-1]["is_primary"] = True
    inviter["contacts"] = contacts

    # Reverse index on invitee: who they guard (admin + home can show 邀請人)
    if inviter_id not in guarding:
        guarding.append(inviter_id)
    contact_user["guarding_for"] = guarding
    contact_user["invited_by"] = inviter_id
    # Mirror inviter details onto invitee so admin can see「守護誰」without only counting users
    details = list(contact_user.get("guarding_details") or [])
    detail_row = next((d for d in details if str(d.get("line_user_id") or "") == inviter_id), None)
    inviter_name = inviter.get("display_name") or "邀請人"
    inviter_picture = str(inviter.get("picture_url") or "").strip()
    if detail_row:
        detail_row["display_name"] = inviter_name
        detail_row["accepted_at"] = detail_row.get("accepted_at") or accepted_at
        detail_row["role"] = "guardian"
        if inviter_picture:
            detail_row["picture_url"] = inviter_picture
    else:
        details.append(
            {
                "line_user_id": inviter_id,
                "display_name": inviter_name,
                "accepted_at": accepted_at,
                "role": "guardian",
                "picture_url": inviter_picture,
            }
        )
    contact_user["guarding_details"] = details

    # New verified invitations are genuinely reciprocal: validate the other half
    # before saving either side, then mutate both profiles in this one state write.
    # 接受邀請只建立「受邀者守護邀請人」；申請 14 天體驗也不自動互綁。
    reciprocal = False
    reciprocal_contact = None
    if reciprocal:
        if activate_trial:
            used_source = free_eligibility_source(contact_user)
            active_trial_source = used_source in {
                "public_trial",
                "transition_trial",
                "guardian_invite_opt_in",
            } and membership_access_active(contact_user)
            if used_source and not active_trial_source:
                return {
                    "ok": False,
                    "error": "你已使用過免費體驗或封測資格",
                    "code": "free_eligibility_already_used",
                }, 409
            if not used_source:
                ensure_membership_trial(
                    contact_user,
                    source="guardian_invite_opt_in",
                )
        invitee_contacts = list(contact_user.get("contacts") or [])
        reciprocal_contact = next(
            (row for row in invitee_contacts if get_contact_line_id(row) == inviter_id), None
        )
        if reciprocal_contact is None:
            invitee_limit = int(plan_rules(contact_user).get("core_guardian_alert_limit") or 1)
            invitee_guardians = sum(1 for row in invitee_contacts if resolve_contact_role(row) == "guardian")
            if invitee_guardians >= invitee_limit:
                return {"ok": False, "error": CONTACT_LIMIT_MESSAGE, "code": "contact_limit", "message": CONTACT_LIMIT_MESSAGE}, 400
            reciprocal_contact = {
                "id": f"line-{inviter_id}", "name": inviter_name, "display_name": inviter_name,
                "line_display_name": inviter_name, "relationship": "守護人", "phone": "", "line_id": inviter_id,
                "line_user_id": inviter_id, "picture_url": inviter_picture, "email": "", "available_time": "",
                "notify_methods": ["line"], "priority": len(invitee_contacts) + 1,
                "consent_status": "accepted", "binding_status": "accepted", "accepted_at": accepted_at,
                "invited_by": contact_line_user_id, "contact_role": "guardian", "note": "雙方同意核心守護綁定",
            }
            invitee_contacts.append(reciprocal_contact)
        reciprocal_contact["is_primary"] = True
        for row in invitee_contacts:
            if row is not reciprocal_contact and get_contact_line_id(row) == inviter_id:
                row["is_primary"] = True
        contact_user["contacts"] = invitee_contacts
        if contact_line_user_id not in (inviter.get("guarding_for") or []):
            inviter["guarding_for"] = [*(inviter.get("guarding_for") or []), contact_line_user_id]
        bound_owner = next((row for row in contacts if get_contact_line_id(row) == contact_line_user_id), None)
        if bound_owner is not None:
            bound_owner["is_primary"] = True
        pending_invite["status"] = "accepted"
        pending_invite["accepted_at"] = accepted_at
        pending_invite["invitee_line_user_id"] = contact_line_user_id
        for profile in (inviter, contact_user):
            profile["profile_completion_required"] = True
            profile["profile_completion_bound_at"] = accepted_at
            profile["profile_completion_reminder_days"] = []
        inviter["profile_completion_peer_line_user_id"] = contact_line_user_id
        contact_user["profile_completion_peer_line_user_id"] = inviter_id
    elif pending_invite:
        pending_invite["status"] = "accepted"
        pending_invite["accepted_at"] = accepted_at
        pending_invite["invitee_line_user_id"] = contact_line_user_id

    # 反向邀請完成時，本次只建立新的單向關係；不修改另一方向的核心順位。
    mutual_core_applied = False
    if is_reverse_invite and mutual_core:
        inviter_core_ok = apply_is_primary_to_contact_line(
            inviter, contact_line_user_id, make_core=True
        )
        invitee_core_ok = apply_is_primary_to_contact_line(
            contact_user, inviter_id, make_core=True
        )
        mutual_core_applied = bool(inviter_core_ok and invitee_core_ok)
        contacts = list(inviter.get("contacts") or [])

    ensure_onboarding_completed_flag(inviter)

    rewards = state.setdefault("contact_rewards", [])
    reward = next(
        (
            item
            for item in rewards
            if item.get("inviter_line_user_id") == inviter_id
            and item.get("contact_line_user_id") == contact_line_user_id
        ),
        None,
    )
    if not reward:
        reward = {
            "created_at": accepted_at,
            "inviter_line_user_id": inviter_id,
            "contact_line_user_id": contact_line_user_id,
            "inviter_display_name": inviter.get("display_name") or "",
            "contact_display_name": contact_display_name or "",
            "status": "available",
            "reward_options": [],
            "selected_reward": "",
        }
        rewards.append(reward)
    else:
        reward["inviter_display_name"] = inviter.get("display_name") or reward.get("inviter_display_name") or ""
        reward["contact_display_name"] = contact_display_name or reward.get("contact_display_name") or ""

    invite_reward_applied = False
    if not was_duplicate:
        invite_reward_applied = apply_invite_trial_reward(
            inviter, reward, accepted_at=accepted_at
        )

    # Relationship and consumed invite must be durable before either party sees
    # a success notification. Notification attempts are logged in a second save.
    try:
        save_state(data_file, state)
    except StateConflictError:
        if _state_conflict_retries <= 0:
            return {
                "ok": False,
                "error": "綁定狀態剛剛有更新，請重新開啟邀請連結",
                "code": "state_conflict",
            }, 409
        return bind_emergency_contact(
            data_file,
            payload,
            config,
            _state_conflict_retries=_state_conflict_retries - 1,
        )

    inviter_notified = False
    guardian_notified = False
    sent = 0
    notify_errors = []
    notify_hint = ""
    notification_log_start = len(state.get("notification_logs") or [])
    usage_start = len(state.get("line_message_usage") or [])
    # 首次綁定成功：一定推播雙方（重複綁定不狂推）
    if config and not was_duplicate:
        token = (
            (config.get("LINE_CHANNEL_ACCESS_TOKEN") if hasattr(config, "get") else None)
            or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
            or os.environ.get("CHANNEL_ACCESS_TOKEN", "")
        )
        sender = (config.get("LINE_PUSH_SENDER") if hasattr(config, "get") else None) or line_push_message
        if not token:
            append_notification_log(
                state,
                "binding_complete",
                inviter_id,
                "failed",
                "綁定完成通知未送出",
                "LINE_CHANNEL_ACCESS_TOKEN missing",
            )
            notify_hint = "系統推播憑證未設定，綁定完成通知未送出。"
        else:
            guardian_name = contact_display_name or "守護人"
            inviter_notice, guardian_notice = build_bind_success_notices(
                inviter,
                contacts,
                inviter_id,
                guardian_name,
                invite_reward_applied=invite_reward_applied,
            )
            print(
                f"[bind] dual_notify start inviter={inviter_id[:8]} guardian={contact_line_user_id[:8]}",
                flush=True,
            )
            for line_user_id, message, who in (
                (inviter_id, inviter_notice, "inviter"),
                (contact_line_user_id, guardian_notice, "guardian"),
            ):
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
                    if who == "inviter":
                        inviter_notified = True
                    else:
                        guardian_notified = True
                    print(f"[bind] dual_notify ok who={who} uid={line_user_id[:8]}", flush=True)
                except Exception as exc:
                    hint = classify_line_push_error(exc)
                    notify_errors.append({"who": who, "error": str(exc)[:400], "hint": hint})
                    append_notification_log(
                        state, "binding_complete", line_user_id, "failed", message, str(exc)
                    )
                    print(
                        f"[bind] dual_notify FAIL who={who} uid={line_user_id[:8]} err={str(exc)[:180]}",
                        flush=True,
                    )
            if inviter_notified and guardian_notified:
                bound_row = next(
                    (
                        contact
                        for contact in contacts
                        if get_contact_line_id(contact) == contact_line_user_id
                    ),
                    None,
                )
                if bound_row is not None:
                    bound_row["bind_notify_sent_at"] = accepted_at
            elif notify_errors:
                notify_hint = notify_errors[0].get("hint") or classify_line_push_error("")
            elif not inviter_notified and not guardian_notified:
                notify_hint = "雙方 LINE 通知皆未送出；請確認已加入「每日平安」官方帳號好友。"

    if sent:
        record_line_message_usage(
            state,
            category="binding",
            owner_line_user_id=inviter_id,
            recipient_count=sent,
            event_id=str((pending_invite or {}).get("id") or f"{inviter_id}:{contact_line_user_id}:{accepted_at}"),
            sent_at=parse_datetime(accepted_at) or current_app_time(config or {}),
        )
    delivery_logs = copy.deepcopy(
        (state.get("notification_logs") or [])[notification_log_start:]
    )
    delivery_usage = copy.deepcopy(
        (state.get("line_message_usage") or [])[usage_start:]
    )
    bind_notify_status = None
    if config and not was_duplicate:
        failed_by_who = {
            str(row.get("who") or ""): row
            for row in notify_errors
            if isinstance(row, dict)
        }
        bind_notify_status = {
            "inviter": {
                "status": "sent" if inviter_notified else "failed",
                "attempts": 1,
                "retryable": (
                    classify_push_exception(
                        RuntimeError(
                            (failed_by_who.get("inviter") or {}).get("error") or ""
                        )
                    ).kind in {"transient", "rate_limited"}
                ),
            },
            "guardian": {
                "status": "sent" if guardian_notified else "failed",
                "attempts": 1,
                "retryable": (
                    classify_push_exception(
                        RuntimeError(
                            (failed_by_who.get("guardian") or {}).get("error") or ""
                        )
                    ).kind in {"transient", "rate_limited"}
                ),
            },
        }

    if (
        delivery_logs
        or delivery_usage
        or bind_notify_status
        or (inviter_notified and guardian_notified)
    ):
        def merge_delivery_results(latest):
            if delivery_logs:
                logs = list(latest.get("notification_logs") or [])
                logs.extend(delivery_logs)
                latest["notification_logs"] = logs[-100:]
            if delivery_usage:
                ledger = list(latest.get("line_message_usage") or [])
                known_keys = {
                    str(row.get("key") or "")
                    for row in ledger
                    if isinstance(row, dict)
                }
                for row in delivery_usage:
                    key = str(row.get("key") or "")
                    if key and key not in known_keys:
                        ledger.append(row)
                        known_keys.add(key)
                latest["line_message_usage"] = ledger[-10000:]
            if inviter_notified and guardian_notified:
                latest_inviter = (latest.get("users") or {}).get(inviter_id) or {}
                latest_contact = next(
                    (
                        row
                        for row in (latest_inviter.get("contacts") or [])
                        if get_contact_line_id(row) == contact_line_user_id
                    ),
                    None,
                )
                if latest_contact is not None:
                    latest_contact["bind_notify_sent_at"] = accepted_at
            latest_inviter = (latest.get("users") or {}).get(inviter_id) or {}
            latest_contact = next(
                (
                    row
                    for row in (latest_inviter.get("contacts") or [])
                    if get_contact_line_id(row) == contact_line_user_id
                ),
                None,
            )
            if latest_contact is not None and bind_notify_status:
                latest_contact["bind_notify_status"] = copy.deepcopy(
                    bind_notify_status
                )

        mutate_state_atomically(data_file, merge_delivery_results)
    bound_contact = next(
        (contact for contact in contacts if get_contact_line_id(contact) == contact_line_user_id),
        None,
    )
    bind_message = ALREADY_BOUND_MESSAGE if was_duplicate else "綁定完成！你已成為對方的守護人。"
    if is_reverse_invite and not was_duplicate:
        bind_message = f"綁定完成！你現在也會守護「{inviter_name}」。雙方的兩個守護方向均已各自同意。"
    owner_notice = {"status": "sent" if inviter_notified else "failed"}
    invitee_notice = {"status": "sent" if guardian_notified else "failed"}
    return {
        "ok": True,
        "bound": True,
        "already_bound": was_duplicate,
        "binding_complete": not was_duplicate,
        "is_reverse_invite": is_reverse_invite,
        "mutual_core_requested": mutual_core,
        "mutual_core_applied": mutual_core_applied,
        "trial_opted_in": activate_trial,
        "reciprocal": reciprocal,
        "owner_guardian": bound_contact if reciprocal else None,
        "invitee_guardian": reciprocal_contact if reciprocal else None,
        "owner_notice": owner_notice,
        "invitee_notice": invitee_notice,
        "inviter_display_name": inviter_name,
        "message": bind_message,
        "contact": bound_contact,
        "reward": reward,
        "invite_reward_applied": invite_reward_applied,
        "trial_bonus_days": trial_bonus_days(inviter),
        "trial_days_left": trial_days_left(inviter),
        "consent_request_sent": sent,
        "test_messages_sent": sent,  # 向下相容
        "inviter_notified": inviter_notified,
        "guardian_notified": guardian_notified,
        "notify_errors": notify_errors,
        "notify_hint": notify_hint,
        "persistence": persistence_info(data_file),
    }, 200



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


def refresh_guardian_group_member_snapshot(data_file, group_id, token=None):
    """進群／查狀態時刷新群組成員數快照（與「已綁定守護人」無關）。

    Returns:
        dict | None: 更新後的 group 資料；群不存在或 API 失敗時回傳現有值／None。
    """
    group_id = str(group_id or "").strip()
    if not group_id:
        return None
    state = load_state(data_file)
    groups = state.get("guardian_groups") or {}
    group = groups.get(group_id)
    if not group or group.get("status") != "active":
        return group
    access_token = token or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not access_token:
        return group
    mc = get_group_member_count(access_token, group_id)
    if mc is None:
        return group
    group["member_count_at_bind"] = mc
    group["member_count_updated_at"] = datetime.now().isoformat(timespec="seconds")
    ids = get_group_member_ids(access_token, group_id)
    if ids is not None:
        group["member_ids_at_bind"] = ids
    groups[group_id] = group
    state["guardian_groups"] = groups
    save_state(data_file, state)
    return group


def refresh_all_guardian_groups_count(data_file, token=None):
    """排程器用：刷新所有 active 守護群的成員數快照（每 5 分鐘跑一次）。

    - 跳過非 active 的群
    - 個別群 API 失敗不會中斷其他群
    - 寫入 member_count_at_bind / member_ids_at_bind / member_count_updated_at
    """
    access_token = token or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not access_token:
        return
    try:
        state = load_state(data_file)
    except Exception:
        return
    groups = state.get("guardian_groups") or {}
    updated = False
    for gid, group in list(groups.items()):
        if not isinstance(group, dict) or group.get("status") != "active":
            continue
        try:
            mc = get_group_member_count(access_token, gid)
            if mc is not None:
                group["member_count_at_bind"] = mc
                group["member_count_updated_at"] = datetime.now().isoformat(timespec="seconds")
                updated = True
            ids = get_group_member_ids(access_token, gid)
            if ids is not None:
                group["member_ids_at_bind"] = ids
                updated = True
            if updated:
                groups[gid] = group
        except Exception:
            continue
    if updated:
        state["guardian_groups"] = groups
        try:
            save_state(data_file, state)
        except Exception:
            pass


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


def plan_includes_guardian_group(profile) -> bool:
    """方案是否含守護群（目前為 799 月／年）。"""
    return int(plan_rules(profile or {}).get("guardian_group_limit") or 0) > 0


def guardian_group_entitlement_active(profile, now=None):
    if not plan_includes_guardian_group(profile):
        return False
    if str((profile or {}).get("membership_source") or "") == "beta":
        return membership_access_active(profile, now)
    return paid_membership_is_active(profile)


def normalize_guardian_group_preferences(raw=None):
    """Product defaults: 私訊提醒 ON、群組提醒 OFF、每日群組摘要 OFF。"""
    prefs = dict(DEFAULT_GUARDIAN_GROUP_PREFERENCES)
    if isinstance(raw, dict):
        for key in DEFAULT_GUARDIAN_GROUP_PREFERENCES:
            if key in raw:
                prefs[key] = bool(raw.get(key))
        summary_time = str(raw.get("daily_summary_time") or "").strip()
        if REMINDER_TIME_PATTERN.match(summary_time):
            prefs["daily_summary_time"] = summary_time
    prefs.setdefault("daily_summary_time", "21:00")
    return prefs


def guardian_group_preference(group, key, default=None):
    prefs = normalize_guardian_group_preferences((group or {}).get("preferences"))
    if key in prefs:
        return prefs[key]
    if default is not None:
        return default
    return DEFAULT_GUARDIAN_GROUP_PREFERENCES.get(key)


def sync_owned_guardian_group_ids(state, profile):
    """把 guardian_groups 裡「此會員為 owner 且 active」的群同步回 profile.guardian_group_ids。

    修常見不一致：群已綁定成功（guardian_groups 有資料），但 LIFF 讀 profile 仍顯示未綁定。
    """
    if not isinstance(profile, dict):
        return []
    owner_id = str(profile.get("line_user_id") or "").strip()
    groups = (state or {}).get("guardian_groups") or {}
    owned_ids = []
    if owner_id:
        for gid, group in groups.items():
            if not isinstance(group, dict):
                continue
            if group.get("status") != "active":
                continue
            if str(group.get("owner_line_user_id") or "").strip() != owner_id:
                continue
            owned_ids.append(str(gid))
    # 保留既有順序，再補上遺漏的 owned 群
    existing = [str(x) for x in (profile.get("guardian_group_ids") or []) if str(x).strip()]
    owned_set = set(owned_ids)
    merged = [gid for gid in existing if gid in owned_set]
    for gid in owned_ids:
        if gid not in merged:
            merged.append(gid)
    if merged != list(profile.get("guardian_group_ids") or []):
        profile["guardian_group_ids"] = merged
    return list(profile.get("guardian_group_ids") or [])


def owned_active_guardian_groups(state, profile):
    """回傳此會員擁有且啟用的守護群列表（含 ids 與 groups 雙向對齊）。"""
    owner_id = str((profile or {}).get("line_user_id") or "").strip()
    if not owner_id:
        return []
    sync_owned_guardian_group_ids(state, profile)
    groups = (state or {}).get("guardian_groups") or {}
    out = []
    for group_id in (profile or {}).get("guardian_group_ids") or []:
        group = groups.get(group_id)
        if not isinstance(group, dict):
            continue
        if str(group.get("owner_line_user_id") or "").strip() != owner_id:
            continue
        if group.get("status") != "active":
            continue
        row = dict(group)
        row["group_id"] = group_id
        row["preferences"] = normalize_guardian_group_preferences(group.get("preferences"))
        out.append(row)
    return out


def guardian_group_settings_for_user(data_file, line_user_id):
    """Return the signed-in member's editable guardian-group settings."""
    state = load_state(data_file)
    profile = (state.get("users") or {}).get(str(line_user_id or "").strip())
    if not profile:
        return {"error": "user not registered"}, 404
    groups = []
    for group in owned_active_guardian_groups(state, profile):
        groups.append({
            "group_id": group["group_id"],
            "group_name": str(group.get("group_name") or "LINE 守護群"),
            "member_count": group.get("member_count_last_refresh")
            or group.get("member_count_at_bind"),
            "status": group.get("status"),
            "preferences": normalize_guardian_group_preferences(
                group.get("preferences")
            ),
        })
    return {
        "ok": True,
        "plan": profile.get("plan") or "trial",
        "guardian_group_limit": int(
            plan_rules(profile).get("guardian_group_limit") or 0
        ),
        "guardian_group_count": len(groups),
        "groups": groups,
    }, 200


def should_notify_private_guardians(state, profile):
    """無守護群 → 永遠私訊；有群 → 任一群勾選私訊即發送（預設勾選）。"""
    owned = owned_active_guardian_groups(state, profile)
    if not owned:
        return True
    return any(guardian_group_preference(g, "notify_private_guardians") for g in owned)


def is_guardian_group_admin(group, line_user_id) -> bool:
    """守護群管理員＝建立者（owner）或 admin_line_user_ids 名單。"""
    uid = str(line_user_id or "").strip()
    if not uid or not isinstance(group, dict):
        return False
    if str(group.get("owner_line_user_id") or "").strip() == uid:
        return True
    admins = group.get("admin_line_user_ids") or []
    return uid in {str(x).strip() for x in admins if str(x).strip()}


def grant_guardian_group_admin(group, line_user_id) -> bool:
    """把用戶寫入守護群管理員名單；必要時補 owner。回傳是否有變更。"""
    uid = str(line_user_id or "").strip()
    if not uid or not isinstance(group, dict):
        return False
    changed = False
    owner = str(group.get("owner_line_user_id") or "").strip()
    if not owner:
        group["owner_line_user_id"] = uid
        owner = uid
        changed = True
    admins = [
        str(x).strip()
        for x in (group.get("admin_line_user_ids") or [])
        if str(x).strip()
    ]
    for candidate in (owner, uid):
        if candidate and candidate not in admins:
            admins.append(candidate)
            changed = True
    if changed:
        group["admin_line_user_ids"] = list(dict.fromkeys(admins))
        group["admin_granted_at"] = datetime.now().isoformat(timespec="seconds")
    return changed


def ensure_guardian_group_admin_for_user(state, profile) -> int:
    """升級含守護群方案後：對其已綁定／擁有的群自動授予管理員（不必再走「管理員設定」）。"""
    if not plan_includes_guardian_group(profile):
        return 0
    uid = str((profile or {}).get("line_user_id") or "").strip()
    if not uid:
        return 0
    groups = state.setdefault("guardian_groups", {})
    granted = 0
    for gid in list(dict.fromkeys((profile or {}).get("guardian_group_ids") or [])):
        group = groups.get(gid)
        if not isinstance(group, dict):
            continue
        owner = str(group.get("owner_line_user_id") or "").strip()
        if owner and owner != uid:
            continue
        if grant_guardian_group_admin(group, uid):
            granted += 1
        groups[gid] = group
    return granted


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
            # 建立者重新綁定／已綁定：自動確保管理員身分，並補回 profile.guardian_group_ids
            grant_guardian_group_admin(existing_group, line_user_id)
            groups[group_id] = existing_group
            group_ids = list(dict.fromkeys(profile.get("guardian_group_ids") or []))
            if group_id not in group_ids:
                group_ids.append(group_id)
            profile["guardian_group_ids"] = group_ids
            sync_owned_guardian_group_ids(state, profile)
            save_state(data_file, state)
            response = {
                "bound": True,
                "already_bound": True,
                "group_id": group_id,
                "guardian_group_count": len(profile.get("guardian_group_ids") or []),
                "guardian_group_limit": plan_rules(profile).get("guardian_group_limit", 0),
                "guardian_group_ids": list(profile.get("guardian_group_ids") or []),
                "is_group_admin": True,
                "should_leave": False,
            }
            delivery = dict(profile.get("trial_group_test_delivery") or {})
            if (
                bool(payload.get("trial_test"))
                and delivery.get("group_id") == group_id
                and delivery.get("status") in {"pending", "failed"}
            ):
                response.update({
                    "trial_test": True,
                    "trial_test_message": "這是測試通知：守護群綁定與推播流程已完成",
                    "trial_test_retry_key": delivery.get("retry_key"),
                    "trial_test_recovered": True,
                })
            return response, 200
        return {
            "error": "group is already bound to another member",
            "should_leave": False,
        }, 409

    trial_test = bool(payload.get("trial_test"))
    trial_test_eligible = (
        trial_test
        and str(profile.get("plan") or "") == "trial"
        and membership_access_active(profile)
        and effective_entitlement_plan(profile) == "paid_399"
    )
    trial_claim = None
    if trial_test_eligible:
        def claim_group_test(current_state):
            current_profile = (current_state.get("users") or {}).get(line_user_id)
            if not isinstance(current_profile, dict):
                raise ValueError("member_not_found")
            if (
                str(current_profile.get("plan") or "") != "trial"
                or not membership_access_active(current_profile)
                or effective_entitlement_plan(current_profile) != "paid_399"
            ):
                raise ValueError("trial_group_test_not_eligible")
            claim = claim_trial_group_test(current_profile, group_id)
            if not claim.get("claimed"):
                raise ValueError("trial_group_test_already_used")
            return claim

        try:
            trial_claim = mutate_state_atomically(data_file, claim_group_test)
        except ValueError as exc:
            return {"error": str(exc), "should_leave": True}, 409
        state = load_state(data_file)
        profile = get_profile(state, line_user_id)
        groups = state.setdefault("guardian_groups", {})
    eligible = guardian_group_entitlement_active(profile) or trial_test_eligible
    if not eligible:
        return {
            "error": "guardian groups require an active paid_799 membership",
            "required_plan": "paid_799",
            "should_leave": True,
        }, 403

    group_ids = list(dict.fromkeys(profile.get("guardian_group_ids") or []))
    group_limit = 1 if trial_test_eligible else plan_rules(profile).get("guardian_group_limit", 0)
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
        "admin_line_user_ids": [line_user_id],
        "admin_granted_at": now,
        "status": "active",
        "created_at": now,
        "member_count_at_bind": member_count_at_bind,
        "member_ids_at_bind": member_ids_at_bind,
        "preferences": normalize_guardian_group_preferences({
            "notify_private_guardians": True,
            "notify_group_on_overdue": False,
            "notify_admin_only": True,
            "daily_admin_summary": False,
        }),
    }
    group_ids.append(group_id)
    profile["guardian_group_ids"] = group_ids
    sync_owned_guardian_group_ids(state, profile)
    save_state(data_file, state)
    response = {
        "bound": True,
        "already_bound": False,
        "group_id": group_id,
        "guardian_group_count": len(profile.get("guardian_group_ids") or group_ids),
        "guardian_group_limit": group_limit,
        "guardian_group_ids": list(profile.get("guardian_group_ids") or group_ids),
        "is_group_admin": True,
        "should_leave": False,
    }
    if trial_claim and trial_claim.get("claimed"):
        response["trial_test"] = True
        response["trial_test_message"] = trial_claim["message"]
        response["trial_test_retry_key"] = trial_claim.get("retry_key")
        response["trial_test_recovered"] = bool(trial_claim.get("recovered"))
    return response, 200


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

    preferences = normalize_guardian_group_preferences(group.get("preferences"))
    for key in DEFAULT_GUARDIAN_GROUP_PREFERENCES:
        if key in payload:
            preferences[key] = bool(payload.get(key))
    if "daily_summary_time" in payload:
        summary_time = str(payload.get("daily_summary_time") or "").strip()
        if not REMINDER_TIME_PATTERN.match(summary_time):
            return {"error": "invalid daily_summary_time format, use HH:MM"}, 400
        preferences["daily_summary_time"] = summary_time
    group["preferences"] = preferences
    save_state(data_file, state)
    return {"ok": True, "group_id": group_id, "preferences": preferences}, 200


def _member_checked_today(profile, today):
    if not profile:
        return False
    history = profile.get("history") or []
    if today in history:
        return True
    return any(str(item.get("date", "")) == today for item in history if isinstance(item, dict))


def eligible_guardian_group_summary_members(state, group, current_member_ids):
    """Return current LINE group members who still belong to the owner's safety circle.

    The owner is eligible while present in the LINE group. Other rows require a
    live reciprocal core-guardian relationship at send time; a historical group
    snapshot or mere LINE group membership is never enough.
    """
    users = (state or {}).get("users") or {}
    owner_id = str((group or {}).get("owner_line_user_id") or "").strip()
    owner = users.get(owner_id) or {}
    if (
        not owner_id
        or not guardian_group_entitlement_active(owner)
    ):
        return []

    current_ids = {
        str(uid or "").strip()
        for uid in (current_member_ids or [])
        if str(uid or "").strip()
    }
    eligible_ids = {owner_id}
    for contact in owner.get("contacts") or []:
        if (
            resolve_contact_role(contact) != "guardian"
            or not bool(contact.get("is_primary"))
            or not contact_is_bound_guardian(contact, owner_id)
        ):
            continue
        peer_id = get_contact_line_id(contact)
        peer = users.get(peer_id) or {}
        reciprocal = any(
            get_contact_line_id(peer_contact) == owner_id
            and resolve_contact_role(peer_contact) == "guardian"
            and bool(peer_contact.get("is_primary"))
            and contact_is_bound_guardian(peer_contact, peer_id)
            for peer_contact in (peer.get("contacts") or [])
        )
        if reciprocal:
            eligible_ids.add(peer_id)

    rows = []
    for uid in current_member_ids or []:
        uid = str(uid or "").strip()
        if not uid or uid not in current_ids or uid not in eligible_ids:
            continue
        profile = users.get(uid)
        if not isinstance(profile, dict):
            continue
        rows.append({
            "line_user_id": uid,
            "name": profile.get("display_name") or profile.get("name") or "LINE 成員",
            "profile": profile,
        })
    return rows


def build_owner_today_safety_roster(state, profile, config=None, now=None):
    """管理員用：今天誰已報／尚未報平安（私訊／LIFF；不依賴群組提醒開關）。"""
    now = now or current_app_time(config or {})
    today = now.strftime("%Y-%m-%d")
    users = (state or {}).get("users") or {}
    owner_id = str((profile or {}).get("line_user_id") or "").strip()
    checked = []
    unchecked = []
    seen = set()

    def add_uid(uid, fallback_name="LINE 成員"):
        uid = str(uid or "").strip()
        if not uid or uid in seen:
            return
        seen.add(uid)
        row = users.get(uid) or {}
        name = row.get("display_name") or row.get("name") or fallback_name
        if uid == owner_id:
            name = f"{name}（我）"
        target = checked if _member_checked_today(row if row else profile, today) else unchecked
        if uid == owner_id and not row:
            target = checked if _member_checked_today(profile, today) else unchecked
        target.append({"line_user_id": uid, "name": name})

    # 本人
    if owner_id:
        add_uid(owner_id, (profile or {}).get("display_name") or "我")

    # 已綁定核心／一般守護人（報平安對象是會員本人；此處列出「家人圈」狀態用群內／綁定成員）
    for contact in (profile or {}).get("contacts") or []:
        if not contact_is_bound_guardian(contact, owner_id):
            continue
        gid = get_contact_line_id(contact)
        if gid:
            add_uid(gid, contact.get("name") or contact.get("display_name") or "守護人")

    # 守護群綁定當下成員快照（799）
    for group in owned_active_guardian_groups(state, profile):
        for uid in group.get("member_ids_at_bind") or []:
            add_uid(uid)

    return {
        "date": today,
        "checked": checked,
        "unchecked": unchecked,
        "checked_count": len(checked),
        "unchecked_count": len(unchecked),
    }


def owner_today_safety_roster_text(data_file, line_user_id, config=None):
    state = load_state(data_file)
    profile = get_profile(state, line_user_id) or {}
    if not profile.get("line_user_id"):
        return "目前無法確認你的身分，請稍後再試。", 400
    roster = build_owner_today_safety_roster(state, profile, config=config)
    checked_names = [x["name"] for x in roster["checked"]]
    unchecked_names = [x["name"] for x in roster["unchecked"]]
    owned = owned_active_guardian_groups(state, profile)
    group_hint = ""
    if owned:
        flags = []
        for g in owned:
            prefs = g.get("preferences") or {}
            flags.append(
                f"・私訊提醒：{'開' if prefs.get('notify_private_guardians') else '關'}／"
                f"群組提醒：{'開' if prefs.get('notify_group_on_overdue') else '關'}／"
                f"群組每日摘要：{'開' if prefs.get('daily_admin_summary') else '關'}"
            )
        group_hint = "\n\n守護群通知設定：\n" + "\n".join(flags)
    else:
        group_hint = "\n\n（尚未綁定守護群時，逾期預警預設只私訊核心守護人。）"
    lines = [
        "📊 今天誰還沒報平安",
        f"日期：{roster['date']}",
        f"已報平安：{', '.join(checked_names) if checked_names else '尚無'}",
        f"尚未報平安：{', '.join(unchecked_names) if unchecked_names else '目前都已完成'}",
        group_hint,
        "",
        "說明：私訊報平安成功＝今日完成，不必再另外做群組簽到。",
        "生日／生活提醒只會私訊本人，不會發到守護群。",
    ]
    return "\n".join(lines), 200


def guardian_group_daily_status_text(data_file, line_user_id, group_id):
    if not line_user_id or not group_id:
        return "目前無法確認你的身分，請稍後再試。", 400

    state = load_state(data_file)
    group = state.get("guardian_groups", {}).get(group_id)
    if not group or group.get("status") != "active":
        return "此群尚未完成守護群綁定。請由有效的 799 會員在群裡輸入「點我綁定守護群」。", 404
    prefs = normalize_guardian_group_preferences(group.get("preferences"))
    if prefs.get("notify_admin_only", True) and not is_guardian_group_admin(group, line_user_id):
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
        is_checked = _member_checked_today(profile, today)
        (checked if is_checked else unchecked).append(name)

    total_count = len(checked) + len(unchecked)
    lines = [
        f"📊 {group.get('group_name') or '守護群'}今日平安狀態",
        f"共 {total_count} 位成員",
        f"✅ {len(checked)} 位已報平安",
        f"⚠️ {len(unchecked)} 位未報平安",
        f"未報平安：{'、'.join(unchecked) if unchecked else '目前都已完成'}",
        "",
        "群組隱私設定：",
        f"私訊提醒（核心守護人）：{'開啟' if prefs.get('notify_private_guardians') else '關閉'}（預設建議開啟）",
        f"群組提醒：{'開啟' if prefs.get('notify_group_on_overdue') else '關閉'}（選用，預設關閉）",
        f"群組每日摘要：{'開啟' if prefs.get('daily_admin_summary') else '關閉'}（選用，預設關閉）",
        f"詳細名單：{'僅管理員可看' if prefs.get('notify_admin_only') else '群內可看'}",
        "",
        "私訊報平安成功＝今日完成，不必再另外做群組簽到。",
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


def _parse_safety_guard_duration(payload, allowed_hours=None):
    """Parse duration for 安全守護 by plan.

    Allowed windows: 1 / 3 / 6 / 8 hours (plan-gated). until_stop is no longer offered.
    Returns (hours, until_stop=False) or raises ValueError for unauthorized duration.
    """
    allowed = [float(h) for h in (allowed_hours or [1, 3, 6, 8]) if float(h) > 0]
    if not allowed:
        allowed = [1]
    allowed_set = set(allowed)
    known = {0.25, 1, 3, 6, 8}
    raw = payload.get("duration")
    if raw is None or raw == "":
        raw = payload.get("share_hours")
    text = str(raw or "").strip().lower().replace(" ", "")
    if text in ("until_stop", "until-stop", "untilstop", "stop", "manual"):
        raise ValueError("until_stop is not available; choose a timed duration for your plan")
    try:
        hours = float(text.replace("h", "").replace("hr", "").replace("小時", "") or 0)
    except (TypeError, ValueError):
        hours = 0
    if hours in allowed_set:
        return hours, False
    # Explicit known option outside this plan → entitlement error (do not silently upgrade/downgrade).
    if hours in known and hours not in allowed_set:
        raise ValueError(f"duration {hours}h is not available on this plan")
    if hours > 0:
        # Legacy callers (e.g. 24): clamp down to the largest allowed window that fits.
        candidates = [h for h in allowed if h <= hours]
        if candidates:
            return max(candidates), False
        return min(allowed), False
    return min(allowed), False


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
    now = now or current_app_time({})
    location = profile.get("location") or {}
    active = _location_session_active(location, now)
    today = now.strftime("%Y-%m-%d")
    last_check_in = profile.get("last_check_in")
    is_today_checked = profile_is_today_checked(profile, now=now)
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
        "guardian_line_user_ids": list(location.get("guardian_line_user_ids") or []),
        "latitude": location.get("latitude") if active else None,
        "longitude": location.get("longitude") if active else None,
        "city": location.get("city", "") if active else "",
        "updated_at": location.get("updated_at") or "",
        "mode": "safety_guard",
        "safety_status": safety_status,
        "is_today_checked": is_today_checked,
        "last_check_in": last_check_in,
        "today": today,
    }


def notify_safety_guard_started(
    state,
    profile,
    line_user_id,
    duration_hours,
    config=None,
    selected_guardian_ids=None,
):
    """Notify bound LINE guardians that 安全守護 started. Mutates notification_logs on state.

    Returns a small status dict for the LIFF UI (sent / failed / no_guardians / reason).
    Never raises — caller already started the guard session.
    """
    location = profile.get("location") or {}
    name = (profile.get("display_name") or "").strip() or "你的親友"
    city = str(location.get("city") or "").strip()
    hours = float(duration_hours or 1)
    duration_label = "15 分鐘" if hours == 0.25 else f"{int(hours)} 小時"
    place = f"（{city}）" if city else ""
    map_url = ""
    try:
        lat = location.get("latitude")
        lng = location.get("longitude")
        if lat is not None and lng is not None:
            map_url = f"https://www.google.com/maps?q={lat},{lng}"
    except (TypeError, ValueError):
        map_url = ""
    message = (
        f"🛡️【安全守護】{name} 已開啟安全守護（{duration_label}）\n"
        f"目前大致位置{place}"
        + (f"：\n{map_url}" if map_url else "：已分享定位")
        + "\n時間到會自動結束；若對方提前結束，你就不會再看到這次分享。"
    )

    contacts = sorted(
        profile.get("contacts") or [],
        key=lambda item: (0 if item.get("is_primary") else 1, int(item.get("priority") or 9999)),
    )
    eligible_targets = []
    for contact in contacts:
        if not contact_is_notifiable_line_guardian(contact, line_user_id):
            continue
        if not bool(contact.get("is_primary")):
            continue
        target = get_contact_line_id(contact)
        if target and target not in eligible_targets:
            eligible_targets.append(target)
    selected_set = {
        str(target).strip()
        for target in (selected_guardian_ids or [])
        if str(target).strip()
    }
    targets = (
        [target for target in eligible_targets if target in selected_set]
        if selected_guardian_ids is not None
        else eligible_targets
    )

    if not targets:
        # 進一步診斷：分辨「完全沒聯絡人」、「只有緊急聯絡人」、「有聯絡人但未走 LINE 綁定」
        all_contacts = list(profile.get("contacts") or [])
        has_any_contact = bool(all_contacts)
        only_emergency = has_any_contact and all(
            resolve_contact_role(c) == "emergency" for c in all_contacts
        )
        # 有「核心守護人」(is_primary) 但還沒拿到對方的 LINE userId
        core_missing_line = has_any_contact and not any(
            (get_contact_line_id(c) or "").strip() for c in all_contacts
        )

        if not has_any_contact:
            reason = "尚未新增任何守護人。請到「守護人」頁籤新增 1 位家人"
            reason_code = "no_contacts"
        elif only_emergency:
            reason = "目前只有緊急聯絡人（電話備援），安全守護需先「一鍵邀請」LINE 守護人"
            reason_code = "emergency_only"
        elif core_missing_line:
            reason = (
                "已新增守護人，但對方尚未完成 LINE 綁定。"
                "請把 LINE 邀請連結傳給守護人，讓他加入「每日平安」官方帳號並點連結同意，"
                "完成後下次開啟安全守護就會通知到他"
            )
            reason_code = "guardian_not_bound_line"
        else:
            reason = "尚未綁定可通知的守護人。請先一鍵邀請家人完成 LINE 綁定，且對方需加入官方帳號好友"
            reason_code = "no_guardians"
        return {
            "sent": 0,
            "failed": 0,
            "target_count": 0,
            "no_guardians": True,
            "reason_code": reason_code,
            "message": reason,
            "failed_reasons": [],
        }

    token = (config or {}).get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        return {
            "sent": 0,
            "failed": len(targets),
            "target_count": len(targets),
            "no_guardians": False,
            "reason_code": "missing_token",
            "message": "系統暫時無法推播 LINE，請稍後再試",
            "failed_reasons": ["missing_token"],
        }

    sender = (config or {}).get("LINE_PUSH_SENDER") or line_push_message
    sent = 0
    failed = 0
    failed_reasons = []
    for target in targets:
        try:
            result = sender(token, target, message)
            append_notification_log(
                state, "safety_guard", target, "sent", message, json.dumps(result, ensure_ascii=False)
            )
            sent += 1
        except Exception as exc:
            hint = classify_line_push_error(exc)
            append_notification_log(state, "safety_guard", target, "failed", message, str(exc))
            failed += 1
            if hint not in failed_reasons:
                failed_reasons.append(hint)

    if sent and not failed:
        summary = f"已通知 {sent} 位守護人"
        reason_code = "ok"
    elif sent and failed:
        summary = f"已通知 {sent} 位，{failed} 位失敗"
        reason_code = "partial"
        if failed_reasons:
            summary = f"{summary}。{failed_reasons[0]}"
    else:
        reason_code = "push_failed"
        summary = "守護人通知失敗（已開啟安全守護，但對方沒收到）"
        if failed_reasons:
            summary = f"{summary}。{failed_reasons[0]}"
        else:
            summary = f"{summary}。請確認守護人已加入「每日平安」官方帳號好友且未封鎖"

    return {
        "sent": sent,
        "failed": failed,
        "target_count": len(targets),
        "no_guardians": False,
        "reason_code": reason_code,
        "message": summary,
        "failed_reasons": failed_reasons,
        "selected_target_count": len(targets),
        "selected_target_ids": list(targets),
    }


def update_location(data_file, payload, config=None):
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
    was_active = _location_session_active(existing, now)

    if refresh_only:
        # Update last known coords; keep an active session as-is, do not invent a new share window.
        if was_active:
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

    # 開始／重開安全守護：必須已有 ≥1 位 LINE 已綁守護人（前端也會先擋；此處為後端保底）
    if not profile_has_bound_line_guardian(profile):
        return {
            "ok": False,
            "error": "還沒完成綁定守護人，無法使用此功能",
            "error_code": "guardian_required",
            "message": "還沒完成綁定守護人，無法使用此功能",
        }, 403

    is_trial = str(profile.get("plan") or "") == "trial"
    usage_date = now.strftime("%Y-%m-%d")
    daily_limit = int(plan_rules(profile).get("safety_guard_daily_limit") or 0)
    stored_usage_date = (
        profile.get("safety_guard_usage_date")
        or profile.get("safety_guard_trial_usage_date")
    )
    stored_usage_count = int(
        profile.get("safety_guard_usage_count")
        if profile.get("safety_guard_usage_count") is not None
        else profile.get("safety_guard_trial_usage_count") or 0
    )
    usage_count = stored_usage_count if stored_usage_date == usage_date else 0
    if (
        not was_active
        and daily_limit > 0
        and usage_count >= daily_limit
    ):
        return {
            "ok": False,
            "error": "safety guard daily limit reached",
            "error_code": (
                "trial_daily_limit_reached"
                if is_trial
                else "safety_guard_daily_limit_reached"
            ),
            "message": (
                "今天的安全守護體驗已使用，明天可以再使用 1 次"
                if is_trial
                else f"今天已使用安全守護 {daily_limit} 次，明天可再使用"
            ),
            "daily_limit": daily_limit,
        }, 429

    allowed_hours = allowed_safety_guard_hours(profile)
    if not allowed_hours:
        return {
            "ok": False,
            "error": "safety guard requires an active trial or paid plan",
            "error_code": "safety_guard_upgrade_required",
            "message": "安全守護定位需在 14 天體驗期間或升級方案後使用",
            "allowed_hours": [],
            "safety_guard_hours": [],
        }, 403
    try:
        duration_hours, until_stop = _parse_safety_guard_duration(payload, allowed_hours)
    except ValueError as exc:
        return {
            "error": str(exc),
            "allowed_hours": allowed_hours,
            "safety_guard_hours": allowed_hours,
        }, 403
    if duration_hours not in set(allowed_hours):
        return {
            "error": "duration not allowed for this plan",
            "allowed_hours": allowed_hours,
            "safety_guard_hours": allowed_hours,
        }, 403
    selected_guardian_ids = payload.get("guardian_line_user_ids")
    if selected_guardian_ids is not None and not isinstance(selected_guardian_ids, list):
        return {"error": "guardian_line_user_ids must be a list"}, 400
    started_at = (
        existing.get("started_at")
        if was_active
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
        "guardian_line_user_ids": [],
        "sharing": True,
        "active": True,
        "mode": "safety_guard",
    }
    # Notify guardians when starting (or restarting) a timed session — not on silent refresh.
    guardian_notify = notify_safety_guard_started(
        state,
        profile,
        line_user_id,
        duration_hours,
        config=config,
        selected_guardian_ids=selected_guardian_ids,
    )
    profile["location"]["guardian_line_user_ids"] = list(
        guardian_notify.get("selected_target_ids") or []
    )
    if not was_active:
        profile["safety_guard_usage_date"] = usage_date
        profile["safety_guard_usage_count"] = usage_count + 1
        if is_trial:
            profile["safety_guard_trial_usage_date"] = usage_date
            profile["safety_guard_trial_usage_count"] = usage_count + 1
    save_state(data_file, state)
    snap = safety_guard_snapshot(profile, now)
    snap["notified_count"] = int(guardian_notify.get("sent") or 0)
    snap["notify_message"] = str(guardian_notify.get("message") or "")
    snap["notify_reason_code"] = str(guardian_notify.get("reason_code") or "")
    return {
        "ok": True,
        "location": profile["location"],
        "safety_guard": snap,
        "guardian_notify": guardian_notify,
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


def classify_line_push_error(exc) -> str:
    """Map LINE push failures to a short, user-facing hint (zh-Hant)."""
    text = str(exc or "").lower()
    if any(k in text for k in ("not a friend", "friendship", "you have been blocked", "blocked")):
        return "對方或你尚未把「每日平安」加為好友（或封鎖了官方帳號），LINE 無法推播。"
    if "429" in text or "rate" in text:
        return "LINE 推播暫時過於頻繁，請稍後再試。"
    if "401" in text or "invalid" in text and "token" in text:
        return "系統推播憑證異常，請稍後再試或聯絡客服。"
    if "400" in text:
        return "LINE 推播被拒（常見原因：未加入官方帳號好友）。綁定本身已成功。"
    return "LINE 推播失敗，請確認已加入官方帳號好友後再試。"


def collect_phone_only_contacts(contacts):
    """Emergency contacts that have a dialable phone but no LINE id (cannot receive push)."""
    out = []
    for contact in contacts or []:
        if not isinstance(contact, dict):
            continue
        target = contact.get("line_id") or contact.get("line_user_id")
        phone = str(contact.get("phone") or contact.get("mobile") or "").strip()
        digits = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
        if target:
            continue
        if not digits:
            continue
        out.append({
            "name": contact.get("name") or contact.get("relationship") or "緊急聯絡人",
            "phone": digits,
            "priority": int(contact.get("priority") or 9999),
        })
    out.sort(key=lambda item: item.get("priority") or 9999)
    return out


def ranked_sos_guardians(profile, owner_id, *, selected_ids=None, limit=None):
    """Eligible SOS guardians in priority order, without applying initial fan-out size."""
    selected_set = set(selected_ids) if selected_ids is not None else None
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
        if not target or target == owner_id or target in seen:
            continue
        if selected_set is not None and target not in selected_set:
            continue
        methods = contact.get("notify_methods")
        if methods is not None and len(methods) == 0:
            methods = ["line"]
        if "line" not in (methods or ["line"]):
            continue
        row = dict(contact)
        row["line_id"] = target
        rows.append(row)
        seen.add(target)
        if limit and len(rows) >= int(limit):
            break
    return rows


def _sos_false_alarm_times(profile, now):
    times = []
    for raw in profile.get("sos_false_alarm_at") or []:
        try:
            parsed = datetime.fromisoformat(str(raw))
        except (TypeError, ValueError):
            continue
        if parsed <= now and parsed >= now - timedelta(days=7):
            times.append(parsed)
    return sorted(times)


def sos_abuse_state(profile: dict, now: datetime) -> dict:
    """Return the graded SOS safety policy without removing emergency access."""
    false_alarms = _sos_false_alarm_times(profile or {}, now)
    in_24h = [item for item in false_alarms if item >= now - timedelta(hours=24)]
    if len(false_alarms) >= 3:
        expires_at = false_alarms[-1] + timedelta(days=7)
        if expires_at > now:
            return {
                "mode": "restricted",
                "expires_at": expires_at.isoformat(timespec="seconds"),
                "reason": "repeated_false_alarm",
                "false_alarm_count_7d": len(false_alarms),
                "false_alarm_count_24h": len(in_24h),
            }
    if len(in_24h) >= 2:
        expires_at = in_24h[-1] + timedelta(days=3)
        if expires_at > now:
            return {
                "mode": "observation",
                "expires_at": expires_at.isoformat(timespec="seconds"),
                "reason": "two_false_alarms_24h",
                "false_alarm_count_7d": len(false_alarms),
                "false_alarm_count_24h": len(in_24h),
            }
    return {
        "mode": "normal",
        "expires_at": None,
        "reason": None,
        "false_alarm_count_7d": len(false_alarms),
        "false_alarm_count_24h": len(in_24h),
    }


def eligible_sos_retry_recipients(event: dict) -> list[dict]:
    """Retry only failed recipients; successful deliveries are idempotently excluded."""
    return [
        dict(item)
        for item in (event or {}).get("deliveries") or []
        if item.get("status") in {"failed", "pending"}
    ]


SOS_RESPONSE_ACTIONS = {"take_over", "assist", "contacted", "unable"}
SOS_CLOSED_STATUSES = {"safe_closed", "cancelled", "resolved", "closed"}


def build_sos_guardian_flex(message, event_id):
    return {
        "type": "flex",
        "altText": "SOS 緊急求助，請確認是否能協助",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#D6322C",
                "paddingAll": "lg",
                "contents": [{
                    "type": "text", "text": "🆘 SOS 緊急求助",
                    "color": "#FFFFFF", "weight": "bold", "size": "xl",
                }],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    {"type": "text", "text": str(message), "wrap": True, "size": "md"},
                    {
                        "type": "text",
                        "text": "「已送達」不代表已讀，請按下方回報實際處理狀態",
                        "wrap": True, "size": "sm", "color": "#666666",
                    },
                ],
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "button", "style": "primary", "color": "#D6322C",
                        "action": {
                            "type": "postback", "label": "我來聯繫",
                            "data": f"sos:take_over:{event_id}",
                            "displayText": "我來聯繫",
                        },
                    },
                    {
                        "type": "button", "style": "secondary",
                        "action": {
                            "type": "postback", "label": "已聯繫本人",
                            "data": f"sos:contacted:{event_id}",
                            "displayText": "已聯繫本人",
                        },
                    },
                    {
                        "type": "button", "style": "link",
                        "action": {
                            "type": "postback", "label": "無法處理",
                            "data": f"sos:unable:{event_id}",
                            "displayText": "目前無法處理",
                        },
                    },
                ],
            },
        },
    }


def _sos_recipient(event, line_user_id):
    return next(
        (
            row for row in (event.get("deliveries") or [])
            if row.get("kind") == "guardian"
            and row.get("status") == "sent"
            and str(row.get("target") or "") == line_user_id
        ),
        None,
    )


def _sos_public_snapshot(event):
    primary_id = str(event.get("primary_responder_id") or "")
    assistants = set(event.get("assistant_responder_ids") or [])
    responses = event.get("guardian_responses") or {}
    recipients = []
    for row in event.get("deliveries") or []:
        if row.get("kind") not in {"guardian", "group"}:
            continue
        target = str(row.get("target") or "")
        response = responses.get(target) or {}
        recipients.append({
            "name": str(row.get("display_name") or (
                "核心守護人" if row.get("kind") == "guardian" else "守護群"
            )),
            "kind": row.get("kind"),
            "delivery_status": row.get("status"),
            "response_status": response.get("action") or "waiting",
            "role": (
                "primary" if target and target == primary_id
                else "assistant" if target in assistants
                else None
            ),
            "responded_at": response.get("responded_at"),
        })
    return {
        "ok": True,
        "event_id": event.get("event_id"),
        "status": event.get("status") or "pending",
        "created_at": event.get("created_at"),
        "sent_at": event.get("sent_at"),
        "closed_at": event.get("closed_at") or event.get("resolved_at"),
        "escalation_round": int(event.get("escalation_round") or 0),
        "escalation_stopped": bool(event.get("escalation_stopped")),
        "primary_responder": next(
            (row["name"] for row in recipients if row.get("role") == "primary"),
            None,
        ),
        "assistants": [
            row["name"] for row in recipients if row.get("role") == "assistant"
        ],
        "recipients": recipients,
        "timeline": [
            {
                "action": item.get("action"),
                "actor_name": item.get("actor_name"),
                "at": item.get("at"),
            }
            for item in (event.get("timeline") or [])
        ],
    }


def respond_to_sos_event(data_file, payload, config=None):
    """Record a guardian response without treating delivery as acknowledgement."""
    event_id = str((payload or {}).get("event_id") or "").strip()
    actor_id = str((payload or {}).get("line_user_id") or "").strip()
    action = str((payload or {}).get("action") or "").strip().casefold()
    if not event_id or not actor_id or action not in SOS_RESPONSE_ACTIONS:
        return {"ok": False, "error": "invalid_sos_response"}, 400
    now = current_app_time(config or {})

    def transition(state):
        event = (state.get("sos_events") or {}).get(event_id)
        if not event:
            return {"ok": False, "error": "sos_event_not_found", "code": 404}
        if str(event.get("status") or "").casefold() in SOS_CLOSED_STATUSES:
            return {"ok": False, "error": "sos_event_closed", "code": 409}
        delivery = _sos_recipient(event, actor_id)
        if not delivery:
            return {"ok": False, "error": "not_sos_recipient", "code": 403}
        actor_name = str(
            delivery.get("display_name")
            or ((state.get("users") or {}).get(actor_id) or {}).get("display_name")
            or "核心守護人"
        )
        responses = event.setdefault("guardian_responses", {})
        previous = responses.get(actor_id) or {}
        role = previous.get("role")
        effective_action = action
        if action in {"take_over", "assist", "contacted"}:
            if not event.get("primary_responder_id"):
                event["primary_responder_id"] = actor_id
                role = "primary"
            elif event.get("primary_responder_id") == actor_id:
                role = "primary"
            else:
                role = "assistant"
                assistants = list(event.get("assistant_responder_ids") or [])
                if actor_id not in assistants:
                    assistants.append(actor_id)
                event["assistant_responder_ids"] = assistants
            event["escalation_stopped"] = True
            event["status"] = "contacted" if action == "contacted" else "responding"
        else:
            role = role or "unable"
        responded_at = now.isoformat(timespec="seconds")
        responses[actor_id] = {
            "action": effective_action,
            "role": role,
            "display_name": actor_name,
            "responded_at": responded_at,
        }
        event.setdefault("timeline", []).append({
            "action": effective_action,
            "actor_id": actor_id,
            "actor_name": actor_name,
            "at": responded_at,
        })
        return {
            "ok": True,
            "code": 200,
            "event_id": event_id,
            "action": effective_action,
            "role": role,
            "actor_name": actor_name,
            "status": event.get("status"),
            "snapshot": _sos_public_snapshot(event),
        }

    result = mutate_state_atomically(data_file, transition)
    code = int(result.pop("code", 200))
    if code == 200:
        cfg = config or {}
        token = cfg.get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get(
            "LINE_CHANNEL_ACCESS_TOKEN", ""
        )
        if token:
            latest = load_state(data_file)
            event = (latest.get("sos_events") or {}).get(event_id) or {}
            actor = result.get("actor_name") or "守護人"
            action_text = {
                "take_over": "已接手，正在聯繫本人",
                "assist": "已加入協助處理",
                "contacted": "已確認聯繫到本人",
                "unable": "目前無法處理",
            }[action]
            notice = f"🆘 SOS 狀態更新：{actor}{action_text}\n事件尚未自動結案"
            targets = [event.get("owner_line_user_id")] + [
                row.get("target") for row in (event.get("deliveries") or [])
                if row.get("kind") == "guardian" and row.get("status") == "sent"
                and row.get("target") != actor_id
            ]
            sender = cfg.get("LINE_PUSH_SENDER") or line_push_message
            delivered = 0
            for target in dict.fromkeys(target for target in targets if target):
                try:
                    _send_line_with_retry_key(
                        sender, token, target, notice,
                        _line_retry_key(f"{event_id}:response:{action}:{actor_id}:{target}"),
                    )
                    delivered += 1
                except Exception:
                    continue
            if delivered:
                mutate_state_atomically(
                    data_file,
                    lambda state: record_line_message_usage(
                        state,
                        category="sos",
                        owner_line_user_id=event.get("owner_line_user_id"),
                        recipient_count=delivered,
                        event_id=f"{event_id}:response:{action}:{actor_id}",
                        sent_at=now,
                    ),
                )
    return result, code


def get_sos_event_status(data_file, requester_id, event_id):
    state = load_state(data_file)
    event = (state.get("sos_events") or {}).get(str(event_id or ""))
    if not event:
        return {"ok": False, "error": "sos_event_not_found"}, 404
    requester_id = str(requester_id or "")
    allowed = requester_id == str(event.get("owner_line_user_id") or "")
    allowed = allowed or _sos_recipient(event, requester_id) is not None
    if not allowed:
        return {"ok": False, "error": "not_sos_participant"}, 403
    return _sos_public_snapshot(event), 200


def close_sos_as_safe(data_file, payload, config=None):
    event_id = str((payload or {}).get("event_id") or "").strip()
    owner_id = str((payload or {}).get("line_user_id") or "").strip()
    now = current_app_time(config or {})

    def close(state):
        event = (state.get("sos_events") or {}).get(event_id)
        if not event:
            return {"ok": False, "error": "sos_event_not_found", "code": 404}
        if owner_id != str(event.get("owner_line_user_id") or ""):
            return {"ok": False, "error": "not_sos_owner", "code": 403}
        if str(event.get("status") or "").casefold() in SOS_CLOSED_STATUSES:
            return {"ok": True, "code": 200, **_sos_public_snapshot(event)}
        closed_at = now.isoformat(timespec="seconds")
        event["status"] = "safe_closed"
        event["closed_at"] = closed_at
        event["escalation_stopped"] = True
        event.setdefault("timeline", []).append({
            "action": "safe_closed",
            "actor_id": owner_id,
            "actor_name": event.get("owner_display_name") or "本人",
            "at": closed_at,
        })
        return {"ok": True, "code": 200, **_sos_public_snapshot(event)}

    result = mutate_state_atomically(data_file, close)
    code = int(result.pop("code", 200))
    if code == 200 and result.get("status") == "safe_closed":
        cfg = config or {}
        token = cfg.get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get(
            "LINE_CHANNEL_ACCESS_TOKEN", ""
        )
        if token:
            state = load_state(data_file)
            event = (state.get("sos_events") or {}).get(event_id) or {}
            sender = cfg.get("LINE_PUSH_SENDER") or line_push_message
            notice = (
                f"✅【SOS 已結束】{event.get('owner_display_name') or '本人'} "
                "已確認目前安全\n本次處理紀錄已保留"
            )
            for row in event.get("deliveries") or []:
                if row.get("kind") not in {"guardian", "group"}:
                    continue
                if row.get("status") != "sent" or not row.get("target"):
                    continue
                try:
                    _send_line_with_retry_key(
                        sender, token, row["target"], notice,
                        _line_retry_key(f"{event_id}:safe:{row['target']}"),
                    )
                except Exception:
                    continue
    return result, code


def process_sos_escalations(data_file, config=None, now=None):
    """Send at most one due 3/5/10 minute SOS escalation round per cron tick."""
    cfg = config or {}
    current = now or current_app_time(cfg)
    token = cfg.get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get(
        "LINE_CHANNEL_ACCESS_TOKEN", ""
    )
    sender = cfg.get("LINE_PUSH_SENDER") or line_push_message
    state = load_state(data_file)
    sent = failed = 0
    events_updated = 0
    thresholds = ((1, 3), (2, 5), (3, 10))
    for event in (state.get("sos_events") or {}).values():
        if event.get("escalation_stopped"):
            continue
        if str(event.get("status") or "").casefold() in SOS_CLOSED_STATUSES:
            continue
        sent_at = parse_datetime(event.get("sent_at"))
        if not sent_at:
            continue
        if current.tzinfo is None and sent_at.tzinfo is not None:
            sent_at = sent_at.replace(tzinfo=None)
        elif current.tzinfo is not None and sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=current.tzinfo)
        elapsed_minutes = (current - sent_at).total_seconds() / 60
        current_round = int(event.get("escalation_round") or 0)
        due = next(
            (
                (round_no, minute)
                for round_no, minute in thresholds
                if round_no > current_round and elapsed_minutes >= minute
            ),
            None,
        )
        if not due:
            continue
        round_no, minute = due
        label = (
            "第三順位通知：前兩位尚未接手"
            if round_no == 1 else
            "第 4、5 位通知：SOS 仍無人接手"
            if round_no == 2 else
            "其餘守護人通知：請立即確認本人安全"
        )
        message = (
            f"⚠️【{label}】{event.get('owner_display_name') or '你的親友'} "
            f"在 {minute} 分鐘前發出 SOS\n"
            "你是本次新增通知的備援守護人。若能處理請按「我來聯繫」；"
            "若有立即危險請撥打 119／110"
        )
        round_units = 0
        already_attempted = {
            str(delivery.get("target") or "")
            for delivery in (event.get("deliveries") or [])
            if delivery.get("kind") == "guardian"
        }
        candidates = [
            row
            for row in (event.get("escalation_guardians") or [])
            if str(row.get("target") or "") not in already_attempted
        ]
        if round_no == 1:
            batch = candidates[:1]
        elif round_no == 2:
            batch = candidates[:2]
        else:
            batch = candidates
        for guardian in batch:
            target = str(guardian.get("target") or "")
            if not target:
                continue
            try:
                outgoing = (
                    build_sos_guardian_flex(message, event.get("event_id"))
                    if sender is line_push_message else message
                )
                _send_line_with_retry_key(
                    sender,
                    token,
                    target,
                    outgoing,
                    _line_retry_key(
                        f"{event.get('event_id')}:escalation:{round_no}:{target}"
                    ),
                )
                sent += 1
                round_units += 1
                event.setdefault("deliveries", []).append({
                    "kind": "guardian",
                    "target": target,
                    "display_name": str(guardian.get("display_name") or "備援守護人"),
                    "recipient_count": 1,
                    "status": "sent",
                    "escalation_round": round_no,
                })
                append_notification_log(
                    state, "sos_escalation", target, "sent",
                    message, json.dumps({"round": round_no}, ensure_ascii=False),
                )
            except Exception as exc:
                failed += 1
                event.setdefault("deliveries", []).append({
                    "kind": "guardian",
                    "target": target,
                    "display_name": str(guardian.get("display_name") or "備援守護人"),
                    "recipient_count": 1,
                    "status": "failed",
                    "escalation_round": round_no,
                })
                append_notification_log(
                    state, "sos_escalation", target, "failed",
                    message, str(exc),
                )
        event["escalation_round"] = round_no
        event["last_escalated_at"] = current.isoformat(timespec="seconds")
        event.setdefault("timeline", []).append({
            "action": f"escalation_{round_no}",
            "actor_name": "系統",
            "at": event["last_escalated_at"],
        })
        record_line_message_usage(
            state,
            category="sos_escalation",
            owner_line_user_id=event.get("owner_line_user_id"),
            recipient_count=round_units,
            event_id=f"{event.get('event_id')}:escalation:{round_no}",
            sent_at=current,
        )
        events_updated += 1
    if events_updated:
        save_state(data_file, state)
    return {
        "sent": sent,
        "failed": failed,
        "events_updated": events_updated,
    }


def _claim_sos_event_action(state, event_id, owner_id, action, now):
    """Lease cancel/retry so concurrent workers cannot duplicate LINE pushes."""
    event = (state.get("sos_events") or {}).get(event_id)
    if not event:
        return {"claimed": False, "reason": "not_found"}
    if event.get("owner_line_user_id") != owner_id:
        return {"claimed": False, "reason": "forbidden"}
    claim_key = "action_claim"
    existing = event.get(claim_key) or {}
    claimed_at = parse_datetime(existing.get("claimed_at"))
    if claimed_at and now - claimed_at < timedelta(minutes=2):
        return {"claimed": False, "reason": "busy"}
    claim_token = uuid.uuid4().hex
    event[claim_key] = {
        "token": claim_token,
        "action": action,
        "claimed_at": now.isoformat(timespec="seconds"),
    }
    return {
        "claimed": True,
        "claim_token": claim_token,
        "event": copy.deepcopy(event),
    }


def _release_sos_event_action(data_file, event_id, claim_token):
    """Release only the lease owned by this request."""
    def release(latest):
        latest_event = (latest.get("sos_events") or {}).get(event_id) or {}
        active = latest_event.get("action_claim") or {}
        if active.get("token") == claim_token:
            latest_event.pop("action_claim", None)

    mutate_state_atomically(data_file, release)


def cancel_sos_event(data_file, payload, config=None):
    """Cancel a delivered SOS and notify only its successful original recipients."""
    line_user_id = str(payload.get("line_user_id") or "").strip()
    event_id = str(payload.get("event_id") or "").strip()
    if not line_user_id or not event_id:
        return {"error": "missing line_user_id or event_id"}, 400
    now = current_app_time(config or {})
    claim = mutate_state_atomically(
        data_file,
        lambda current: _claim_sos_event_action(
            current, event_id, line_user_id, "cancel", now
        ),
    )
    if not claim.get("claimed"):
        reason = claim.get("reason")
        if reason == "not_found":
            return {"error": "SOS event not found"}, 404
        if reason == "forbidden":
            return {"error": "not SOS event owner"}, 403
        return {"error": "SOS cancellation already in progress"}, 409
    claim_token = claim["claim_token"]
    state = load_state(data_file)
    event = (state.get("sos_events") or {}).get(event_id) or claim["event"]
    if event.get("status") == "cancelled" and not int(event.get("cancel_failed") or 0):
        _release_sos_event_action(data_file, event_id, claim_token)
        return {
            "ok": True,
            "event_id": event_id,
            "status": "cancelled",
            "cancel_sent": int(event.get("cancel_sent") or 0),
            "idempotent": True,
        }, 200

    sent_at = parse_datetime(event.get("sent_at"))
    if not sent_at or now - sent_at > timedelta(minutes=10):
        _release_sos_event_action(data_file, event_id, claim_token)
        return {"error": "SOS cancellation window expired"}, 409

    profile = (state.get("users") or {}).get(line_user_id) or {}
    reason = str(payload.get("reason") or "誤觸").strip()[:80]
    message = (
        f"✅【SOS 已取消】{profile.get('display_name') or '你的親友'} 已回報目前安全\n"
        f"原因：{reason}\n原 SOS 紀錄仍會保留供安全查核"
    )
    token = (config or {}).get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    sender = (config or {}).get("LINE_PUSH_SENDER") or line_push_message
    notification_log_start = len(state.get("notification_logs") or [])
    usage_start = len(state.get("line_message_usage") or [])
    cancel_results = []
    cancel_sent = 0
    cancel_failed = 0
    previous_cancel = event.get("cancel_deliveries") or []
    source_deliveries = previous_cancel if previous_cancel else (event.get("deliveries") or [])
    for delivery in source_deliveries:
        wanted_statuses = {"failed"} if previous_cancel else {"sent"}
        if delivery.get("status") not in wanted_statuses or delivery.get("kind") == "self":
            continue
        target = delivery.get("target")
        if not target:
            continue
        try:
            result = _send_line_with_retry_key(
                sender,
                token,
                target,
                message,
                _line_retry_key(f"{event_id}:cancel:{target}"),
            )
            cancel_results.append({
                "kind": delivery.get("kind"),
                "target": target,
                "status": "sent",
                "recipient_count": max(1, int(delivery.get("recipient_count") or 1)),
            })
            append_notification_log(
                state, "sos_cancel", target, "sent", message,
                json.dumps(result, ensure_ascii=False),
            )
            cancel_sent += 1
        except Exception as exc:
            cancel_results.append({
                "kind": delivery.get("kind"),
                "target": target,
                "status": "failed",
                "recipient_count": max(1, int(delivery.get("recipient_count") or 1)),
            })
            append_notification_log(state, "sos_cancel", target, "failed", message, str(exc))
            cancel_failed += 1

    combined_cancel_results = [
        copy.deepcopy(item)
        for item in previous_cancel
        if item.get("status") == "sent"
    ] + cancel_results
    cancel_sent_total = sum(
        1 for item in combined_cancel_results if item.get("status") == "sent"
    )
    cancel_failed_total = sum(
        1 for item in combined_cancel_results if item.get("status") == "failed"
    )
    event["status"] = "cancelled" if cancel_failed_total == 0 else "cancel_partial"
    event["cancelled_at"] = now.isoformat(timespec="seconds")
    event["cancel_reason"] = reason
    event["cancel_deliveries"] = combined_cancel_results
    event["cancel_sent"] = cancel_sent_total
    event["cancel_failed"] = cancel_failed_total
    if not previous_cancel:
        profile.setdefault("sos_false_alarm_at", []).append(now.isoformat(timespec="seconds"))
    policy = sos_abuse_state(profile, now)
    profile["sos_abuse_mode"] = policy["mode"]
    profile["sos_abuse_expires_at"] = policy["expires_at"]
    pending = (state.get("sos_pending") or {}).get(line_user_id)
    if pending and pending.get("event_id") == event_id:
        pending["stage"] = event["status"]
        pending["cancelled_at"] = event["cancelled_at"]
    cancel_units = 0
    for item in cancel_results:
        if item.get("status") != "sent":
            continue
        if item.get("kind") == "group":
            cancel_units += max(1, int(item.get("recipient_count") or 1))
        else:
            cancel_units += 1
    record_line_message_usage(
        state,
        category="sos_cancel",
        owner_line_user_id=line_user_id,
        recipient_count=cancel_units,
        event_id=f"{event_id}:cancel:{claim_token}",
        sent_at=now,
    )
    event_snapshot = copy.deepcopy(event)
    false_alarm_at = now.isoformat(timespec="seconds") if not previous_cancel else None
    pending_snapshot = copy.deepcopy(pending) if pending else None
    new_logs = copy.deepcopy((state.get("notification_logs") or [])[notification_log_start:])
    new_usage = copy.deepcopy((state.get("line_message_usage") or [])[usage_start:])

    def finish_cancel(latest):
        latest_event = (latest.get("sos_events") or {}).get(event_id)
        if not latest_event:
            return
        active_claim = latest_event.get("action_claim") or {}
        if active_claim.get("token") != claim_token:
            return
        latest.setdefault("sos_events", {})[event_id] = copy.deepcopy(event_snapshot)
        latest["sos_events"][event_id].pop("action_claim", None)
        latest_profile = (latest.get("users") or {}).get(line_user_id) or {}
        if false_alarm_at:
            false_alarms = list(latest_profile.get("sos_false_alarm_at") or [])
            if false_alarm_at not in false_alarms:
                false_alarms.append(false_alarm_at)
            latest_profile["sos_false_alarm_at"] = false_alarms
        latest_policy = sos_abuse_state(latest_profile, now)
        latest_profile["sos_abuse_mode"] = latest_policy["mode"]
        latest_profile["sos_abuse_expires_at"] = latest_policy["expires_at"]
        if pending_snapshot:
            latest.setdefault("sos_pending", {})[line_user_id] = copy.deepcopy(pending_snapshot)
        logs = list(latest.get("notification_logs") or [])
        logs.extend(new_logs)
        latest["notification_logs"] = logs[-100:]
        ledger = list(latest.get("line_message_usage") or [])
        known = {str(row.get("key") or "") for row in ledger if isinstance(row, dict)}
        for row in new_usage:
            key = str(row.get("key") or "")
            if key and key not in known:
                ledger.append(row)
                known.add(key)
        latest["line_message_usage"] = ledger[-10000:]

    mutate_state_atomically(data_file, finish_cancel)
    return {
        "ok": cancel_failed_total == 0,
        "event_id": event_id,
        "status": event["status"],
        "cancel_sent": cancel_sent_total,
        "cancel_failed": cancel_failed_total,
        "abuse": policy,
    }, 200 if cancel_failed_total == 0 else 502


def retry_sos_event(data_file, payload, config=None):
    """Retry only failed original recipients and never duplicate successful delivery."""
    line_user_id = str(payload.get("line_user_id") or "").strip()
    event_id = str(payload.get("event_id") or "").strip()
    if not line_user_id or not event_id:
        return {"error": "missing line_user_id or event_id"}, 400
    now = current_app_time(config or {})
    claim = mutate_state_atomically(
        data_file,
        lambda current: _claim_sos_event_action(
            current, event_id, line_user_id, "retry", now
        ),
    )
    if not claim.get("claimed"):
        reason = claim.get("reason")
        if reason == "not_found":
            return {"error": "SOS event not found"}, 404
        if reason == "forbidden":
            return {"error": "not SOS event owner"}, 403
        return {"error": "SOS retry already in progress"}, 409
    claim_token = claim["claim_token"]
    state = load_state(data_file)
    event = (state.get("sos_events") or {}).get(event_id) or claim["event"]
    if (
        event.get("status") in {"cancelled", "cancel_partial"}
        or event.get("cancel_deliveries")
        or event.get("cancelled_at")
    ):
        def release_retry_claim(latest):
            latest_event = (latest.get("sos_events") or {}).get(event_id) or {}
            active = latest_event.get("action_claim") or {}
            if active.get("token") == claim_token:
                latest_event.pop("action_claim", None)

        mutate_state_atomically(data_file, release_retry_claim)
        return {"error": "cancelled SOS cannot be retried"}, 409

    token = (config or {}).get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    sender = (config or {}).get("LINE_PUSH_SENDER") or line_push_message
    notification_log_start = len(state.get("notification_logs") or [])
    usage_start = len(state.get("line_message_usage") or [])
    message = str(event.get("message") or "🚨【SOS 緊急求助】請立即聯絡本人並確認安全")
    retried_sent = 0
    retried_failed = 0
    retried_units = 0
    retried_guardian_or_group_sent = 0
    retried_guardian_or_group_failed = 0
    for delivery in event.get("deliveries") or []:
        if delivery.get("status") not in {"failed", "pending"}:
            continue
        target = delivery.get("target")
        try:
            if delivery.get("kind") == "group":
                group = (state.get("guardian_groups") or {}).get(target) or {}
                push_sos_to_guardian_group(
                    token,
                    target,
                    message,
                    sender=sender,
                    member_ids=list(group.get("member_ids_at_bind") or []),
                    retry_key=delivery.get("retry_key")
                    or f"{event_id}:group:{target}",
                )
                retried_units += max(1, int(delivery.get("recipient_count") or 1))
            else:
                _send_line_with_retry_key(
                    sender,
                    token,
                    target,
                    str(delivery.get("message") or message),
                    delivery.get("retry_key")
                    or _line_retry_key(f"{event_id}:guardian:{target}"),
                )
                retried_units += 1
            delivery["status"] = "sent"
            delivery["retried_at"] = current_app_time(config or {}).isoformat(timespec="seconds")
            append_notification_log(state, "sos_retry", target, "sent", message, event_id)
            retried_sent += 1
            if delivery.get("kind") != "self":
                retried_guardian_or_group_sent += 1
        except Exception as exc:
            delivery["retry_error"] = classify_line_push_error(exc)
            append_notification_log(state, "sos_retry", target, "failed", message, str(exc))
            retried_failed += 1
            if delivery.get("kind") != "self":
                retried_guardian_or_group_failed += 1
    event["retry_count"] = int(event.get("retry_count") or 0) + 1
    remaining = [
        row for row in (event.get("deliveries") or [])
        if row.get("status") in {"failed", "pending"}
    ]
    if retried_guardian_or_group_sent and not event.get("sent_at"):
        event["sent_at"] = now.isoformat(timespec="seconds")
    event["status"] = (
        "sent"
        if not remaining and event.get("sent_at")
        else "partial" if event.get("sent_at") else "delivery_failed"
    )
    record_line_message_usage(
        state,
        category="sos",
        owner_line_user_id=line_user_id,
        recipient_count=retried_units,
        event_id=f"{event_id}:retry:{event['retry_count']}",
        sent_at=current_app_time(config or {}),
    )
    event_snapshot = copy.deepcopy(event)
    new_logs = copy.deepcopy((state.get("notification_logs") or [])[notification_log_start:])
    new_usage = copy.deepcopy((state.get("line_message_usage") or [])[usage_start:])

    def finish_retry(latest):
        latest_event = (latest.get("sos_events") or {}).get(event_id)
        if not latest_event:
            return
        active_claim = latest_event.get("action_claim") or {}
        if active_claim.get("token") != claim_token:
            return
        latest.setdefault("sos_events", {})[event_id] = copy.deepcopy(event_snapshot)
        latest["sos_events"][event_id].pop("action_claim", None)
        if event_snapshot.get("sent_at"):
            latest.setdefault("sos_pending", {})[line_user_id] = {
                "stage": event_snapshot.get("status") or "sent",
                "tap_count": 3,
                "first_tap_at": event_snapshot.get("created_at") or event_snapshot["sent_at"],
                "last_tap_at": event_snapshot.get("sent_at"),
                "sent_at": event_snapshot.get("sent_at"),
                "event_id": event_id,
            }
        logs = list(latest.get("notification_logs") or [])
        logs.extend(new_logs)
        latest["notification_logs"] = logs[-100:]
        ledger = list(latest.get("line_message_usage") or [])
        known = {str(row.get("key") or "") for row in ledger if isinstance(row, dict)}
        for row in new_usage:
            key = str(row.get("key") or "")
            if key and key not in known:
                ledger.append(row)
                known.add(key)
        latest["line_message_usage"] = ledger[-10000:]

    mutate_state_atomically(data_file, finish_retry)
    return {
        "ok": retried_failed == 0,
        "event_id": event_id,
        "retried_sent": retried_sent,
        "retried_failed": retried_failed,
        "recipient_retried_sent": retried_guardian_or_group_sent,
        "recipient_retried_failed": retried_guardian_or_group_failed,
        "deliveries": [
            {
                "kind": row.get("kind"),
                "name": row.get("display_name") or (
                    "本人" if row.get("kind") == "self"
                    else "守護群" if row.get("kind") == "group"
                    else "核心守護人"
                ),
                "status": row.get("status"),
                "error_hint": row.get("retry_error") or row.get("error_hint"),
            }
            for row in (event.get("deliveries") or [])
        ],
    }, (
        200
        if retried_guardian_or_group_sent or (
            not retried_guardian_or_group_failed and bool(event.get("sent_at"))
        )
        else 502
    )


def _claim_sos_delivery(
    state,
    line_user_id,
    now_dt,
    daily_limit=3,
    cooldown_sec=300,
    long_confirm=False,
    reason="",
):
    """Atomically reserve one SOS attempt before any external notification is sent."""
    profile = (state.get("users") or {}).get(line_user_id)
    if not profile:
        return {"claimed": False, "reason": "member_not_found"}
    previous_event_id = str(profile.get("last_sos_event_id") or "").strip()
    previous_event = (state.get("sos_events") or {}).get(previous_event_id) or {}
    if previous_event.get("status") == "sending" and any(
        row.get("status") == "pending"
        for row in (previous_event.get("deliveries") or [])
    ):
        return {
            "claimed": False,
            "reason": "recover_pending",
            "event_id": previous_event_id,
        }
    latest_abuse = sos_abuse_state(profile, now_dt)
    if latest_abuse["mode"] == "observation" and (
        not long_confirm or not str(reason or "").strip()
    ):
        return {
            "claimed": False,
            "reason": "long_confirmation_required",
            "abuse": latest_abuse,
        }
    today_str = now_dt.strftime("%Y-%m-%d")
    sos_log = profile.get("sos_daily_log") or {}
    if sos_log.get("date") != today_str:
        sos_log = {"date": today_str, "count": 0}
    if int(sos_log.get("count") or 0) >= int(daily_limit):
        return {
            "claimed": False,
            "reason": "daily_limit",
            "count": int(sos_log.get("count") or 0),
        }
    last_sos = parse_datetime(profile.get("last_sos_at"))
    if last_sos:
        elapsed = (now_dt - last_sos).total_seconds()
        if elapsed < int(cooldown_sec):
            return {
                "claimed": False,
                "reason": "cooldown",
                "wait_sec": max(1, int(int(cooldown_sec) - elapsed)),
            }
    profile["last_sos_at"] = now_dt.isoformat(timespec="seconds")
    profile["sos_daily_log"] = {
        "date": today_str,
        "count": int(sos_log.get("count") or 0) + 1,
    }
    return {"claimed": True}


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
    abuse = sos_abuse_state(profile, now_dt)
    profile["sos_abuse_mode"] = abuse["mode"]
    profile["sos_abuse_expires_at"] = abuse["expires_at"]
    if abuse["mode"] == "observation" and (
        not payload.get("long_confirm") or not str(payload.get("reason") or "").strip()
    ):
        return {
            "error": "long confirmation required",
            "abuse_mode": "observation",
            "expires_at": abuse["expires_at"],
            "requires_reason": True,
            "emergency_numbers_available": True,
            "emergency_numbers": ["119", "110"],
        }, 428

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
        def append_limit_audit(latest):
            latest_profile = (latest.get("users") or {}).get(line_user_id)
            if latest_profile is None:
                return
            latest_profile.setdefault("sos_abuse_log", []).append({
                "at": now_dt.isoformat(timespec="seconds"),
                "reason": "daily_limit_exceeded",
                "count_today": sos_log.get("count", 0),
            })

        mutate_state_atomically(data_file, append_limit_audit)
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
            pending_event = (
                (state.get("sos_events") or {}).get(
                    str(profile.get("last_sos_event_id") or "")
                )
                or {}
            )
            recovery_pending = (
                pending_event.get("status") == "sending"
                and any(
                    row.get("status") == "pending"
                    for row in (pending_event.get("deliveries") or [])
                )
            )
            if elapsed < SOS_COOLDOWN_SEC and not recovery_pending:
                wait_sec = int(SOS_COOLDOWN_SEC - elapsed)
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
    if abuse["mode"] == "restricted":
        limit = 1
    selected_guardian_ids = payload.get("guardian_line_user_ids")
    if selected_guardian_ids is not None and not isinstance(selected_guardian_ids, list):
        return {"error": "guardian_line_user_ids must be a list"}, 400
    has_explicit_guardian_selection = bool(
        isinstance(selected_guardian_ids, list)
        and any(str(target or "").strip() for target in selected_guardian_ids)
    )
    selected_guardian_set = (
        {
            str(target).strip()
            for target in selected_guardian_ids
            if str(target).strip()
        }
        if has_explicit_guardian_selection
        else None
    )
    guardian_delivery_limit = limit if has_explicit_guardian_selection else min(limit, 2)
    # SOS directly consumes the accepted core-guardian relationship. A second,
    # reciprocal invitation is not required for the guardian to receive help.
    contacts = sorted(
        profile.get("contacts") or [],
        key=lambda item: (0 if item.get("is_primary") else 1, int(item.get("priority") or 9999)),
    )
    phone_contacts = collect_phone_only_contacts(contacts)
    eligible_line_contacts = ranked_sos_guardians(
        profile,
        line_user_id,
        selected_ids=selected_guardian_set,
        limit=limit,
    )
    line_contacts = eligible_line_contacts[:guardian_delivery_limit]
    escalation_contacts = (
        [] if selected_guardian_set is not None
        else eligible_line_contacts[guardian_delivery_limit:]
    )

    active_group_ids = []
    if (
        selected_guardian_set is None
        and rules.get("guardian_group_limit")
        and abuse["mode"] != "restricted"
    ):
        groups = state.get("guardian_groups", {})
        active_group_ids = [
            group_id for group_id in (profile.get("guardian_group_ids") or [])
            if groups.get(group_id, {}).get("owner_line_user_id") == line_user_id
            and groups.get(group_id, {}).get("status") == "active"
        ][: int(rules.get("guardian_group_limit") or 0)]

    # 個人守護人或守護群任一可送；兩者都沒有才拒絕（方案本身不會自動綁定對象）
    if not line_contacts and not active_group_ids:
        return {
            "error": "no bound LINE guardians",
            "sent": 0,
            "phone_only_count": len(phone_contacts),
            "phone_contacts": phone_contacts[:5],
            "has_bound_guardian": profile_has_bound_line_guardian(profile),
        }, 400

    claim = mutate_state_atomically(
        data_file,
        lambda current_state: _claim_sos_delivery(
            current_state,
            line_user_id,
            now_dt,
            daily_limit=SOS_DAILY_LIMIT,
            cooldown_sec=SOS_COOLDOWN_SEC,
            long_confirm=bool(payload.get("long_confirm")),
            reason=str(payload.get("reason") or ""),
        ),
    )
    if not claim.get("claimed"):
        if claim.get("reason") == "member_not_found":
            return {"error": "member not found"}, 404
        if claim.get("reason") == "daily_limit":
            return {
                "error": f"daily SOS limit reached ({SOS_DAILY_LIMIT})",
                "limit": SOS_DAILY_LIMIT,
                "resets_at": f"{today_str}T23:59:59+08:00",
            }, 429
        if claim.get("reason") == "recover_pending":
            recovered, recovered_code = retry_sos_event(
                data_file,
                {
                    "line_user_id": line_user_id,
                    "event_id": claim.get("event_id"),
                },
                config,
            )
            if recovered_code == 200:
                recovered_deliveries = recovered.get("deliveries") or []
                guardian_rows = [
                    {
                        "name": row.get("name") or "核心守護人",
                        "status": row.get("status"),
                        "error_hint": row.get("error_hint"),
                    }
                    for row in recovered_deliveries
                    if row.get("kind") == "guardian"
                ]
                group_rows = [
                    {
                        "name": row.get("name") or "守護群",
                        "status": row.get("status"),
                        "error_hint": row.get("error_hint"),
                    }
                    for row in recovered_deliveries
                    if row.get("kind") == "group"
                ]
                self_rows = [
                    row for row in recovered_deliveries
                    if row.get("kind") == "self"
                ]
                recovered_sent = sum(
                    1 for row in guardian_rows + group_rows
                    if row.get("status") == "sent"
                )
                recovered_failed = sum(
                    1 for row in guardian_rows + group_rows
                    if row.get("status") == "failed"
                )
                return {
                    "sent": recovered_sent,
                    "failed": recovered_failed,
                    "group_sent": sum(1 for row in group_rows if row.get("status") == "sent"),
                    "group_failed": sum(1 for row in group_rows if row.get("status") == "failed"),
                    "guardian_limit": len(guardian_rows),
                    "self": {
                        "status": self_rows[0].get("status")
                        if self_rows else "not_sent"
                    },
                    "guardians": guardian_rows,
                    "groups": group_rows,
                    "results": guardian_rows + group_rows,
                    "location_attached": False,
                    "phone_only_count": 0,
                    "phone_contacts": [],
                    "event_id": claim.get("event_id"),
                    "sent_at": current_app_time(config or {}).isoformat(timespec="seconds"),
                    "location_updated_at": None,
                    "cancel_available": recovered_sent > 0,
                    "abuse_mode": abuse["mode"],
                    "abuse_expires_at": abuse["expires_at"],
                    "emergency_numbers_available": True,
                    "emergency_numbers": ["119", "110"],
                    "recovered": True,
                }, 200
            return recovered, recovered_code
        if claim.get("reason") == "long_confirmation_required":
            latest_abuse = claim.get("abuse") or {}
            return {
                "error": "long confirmation required",
                "abuse_mode": "observation",
                "expires_at": latest_abuse.get("expires_at"),
                "requires_reason": True,
                "emergency_numbers_available": True,
                "emergency_numbers": ["119", "110"],
            }, 428
        return {
            "error": f"SOS cooldown active, wait {int(claim.get('wait_sec') or 1)}s",
            "cooldown_remaining_sec": int(claim.get("wait_sec") or 1),
        }, 429

    # Continue from the claimed revision so the final audit write cannot overwrite
    # the reservation or conflict merely because this request made the claim.
    state = load_state(data_file)
    profile = (state.get("users") or {}).get(line_user_id) or profile
    notification_log_start = len(state.get("notification_logs") or [])
    usage_start = len(state.get("line_message_usage") or [])
    # Rebuild the emergency fan-out from the post-claim authoritative snapshot.
    # A guardian may have been unbound, or a group disabled, between the first
    # request read and the atomic claim.
    rules = plan_rules(profile)
    limit = 1 if abuse["mode"] == "restricted" else int(
        rules.get("core_guardian_alert_limit") or 1
    )
    contacts = sorted(
        profile.get("contacts") or [],
        key=lambda item: (0 if item.get("is_primary") else 1, int(item.get("priority") or 9999)),
    )
    phone_contacts = collect_phone_only_contacts(contacts)
    eligible_line_contacts = ranked_sos_guardians(
        profile,
        line_user_id,
        selected_ids=selected_guardian_set,
        limit=limit,
    )
    line_contacts = eligible_line_contacts[:guardian_delivery_limit]
    escalation_contacts = (
        [] if selected_guardian_set is not None
        else eligible_line_contacts[guardian_delivery_limit:]
    )
    active_group_ids = []
    if (
        selected_guardian_set is None
        and rules.get("guardian_group_limit")
        and abuse["mode"] != "restricted"
    ):
        groups = state.get("guardian_groups") or {}
        active_group_ids = [
            group_id
            for group_id in (profile.get("guardian_group_ids") or [])
            if groups.get(group_id, {}).get("owner_line_user_id") == line_user_id
            and groups.get(group_id, {}).get("status") == "active"
        ][: int(rules.get("guardian_group_limit") or 0)]
    if not line_contacts and not active_group_ids:
        return {
            "error": "no bound LINE guardians",
            "sent": 0,
            "phone_only_count": len(phone_contacts),
            "phone_contacts": phone_contacts[:5],
            "has_bound_guardian": profile_has_bound_line_guardian(profile),
        }, 400

    # SOS only attaches coordinates obtained for this exact request.  A denied or
    # timed-out lookup must never silently disclose a stale stored location.
    location = {}
    try:
        req_lat = payload.get("latitude")
        req_lng = payload.get("longitude")
        if req_lat is not None and req_lng is not None:
            location["latitude"] = float(req_lat)
            location["longitude"] = float(req_lng)
            city = str(payload.get("city") or "").strip()
            if city:
                location["city"] = city
            location["updated_at"] = now_dt.isoformat(timespec="seconds")
            stored_location = dict(profile.get("location") or {})
            stored_location.update(location)
            profile["location"] = stored_location
    except (TypeError, ValueError):
        location = {}

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
    group_delivery_members = {}
    group_member_getter = (config or {}).get("GROUP_MEMBER_IDS_GETTER")
    for group_id in active_group_ids:
        group_info = (state.get("guardian_groups") or {}).get(group_id) or {}
        try:
            if callable(group_member_getter):
                current_ids = group_member_getter(token, group_id)
            elif ((config or {}).get("LINE_PUSH_SENDER") or line_push_message) is line_push_message:
                current_ids = get_group_member_ids(token, group_id)
            else:
                current_ids = list(group_info.get("member_ids_at_bind") or [])
        except Exception:
            current_ids = list(group_info.get("member_ids_at_bind") or [])
        group_delivery_members[group_id] = list(dict.fromkeys(current_ids or []))

    requested_units = len(line_contacts) + sum(
        max(1, len(group_delivery_members.get(group_id) or []))
        for group_id in active_group_ids
    )
    budget = line_push_budget_decision(
        state,
        owner_line_user_id=line_user_id,
        requested_units=requested_units,
        now=now_dt,
        monthly_hard_cap=int(
            (config or {}).get("LINE_MONTHLY_MESSAGE_HARD_CAP")
            or os.environ.get("LINE_MONTHLY_MESSAGE_HARD_CAP")
            or (config or {}).get("LINE_MONTHLY_MESSAGE_QUOTA")
            or os.environ.get("LINE_MONTHLY_MESSAGE_QUOTA")
            or 200
        ),
        member_daily_hard_cap=int(
            (config or {}).get("LINE_MEMBER_DAILY_MESSAGE_HARD_CAP")
            or os.environ.get("LINE_MEMBER_DAILY_MESSAGE_HARD_CAP")
            or 20
        ),
        emergency=True,
    )
    remaining_budget = int(budget.get("allowed_units") or 0)
    line_contacts = line_contacts[:remaining_budget]
    remaining_budget -= len(line_contacts)
    budgeted_groups = []
    for group_id in active_group_ids:
        group_units = max(1, len(group_delivery_members.get(group_id) or []))
        if group_units > remaining_budget:
            continue
        budgeted_groups.append(group_id)
        remaining_budget -= group_units
    active_group_ids = budgeted_groups
    if budget.get("reason"):
        append_notification_log(
            state,
            "sos",
            line_user_id,
            "budget_limited",
            "SOS 額外推播已依成本上限縮減",
            json.dumps(budget, ensure_ascii=False),
        )

    self_confirmation = (
        "✅ SOS 通知流程已完成\n"
        "請留意下方通知明細；若是誤觸或目前已安全，"
        "請在 10 分鐘內回到 SOS 畫面取消通知"
    )
    prepared_escalation_guardians = [
        {
            "target": contact["line_id"],
            "display_name": str(
                contact.get("name") or contact.get("relationship") or "備援守護人"
            ),
            "priority": int(contact.get("priority") or 9999),
        }
        for contact in escalation_contacts
    ]
    prepared_deliveries = [
        {
            "kind": "guardian",
            "target": contact["line_id"],
            "display_name": str(
                contact.get("name") or contact.get("relationship") or "核心守護人"
            ),
            "status": "pending",
            "retry_key": _line_retry_key(
                f"{sos_event_id}:guardian:{contact['line_id']}"
            ),
        }
        for contact in line_contacts
    ] + [
        {
            "kind": "group",
            "target": group_id,
            "display_name": str(
                ((state.get("guardian_groups") or {}).get(group_id) or {}).get("group_name")
                or ((state.get("guardian_groups") or {}).get(group_id) or {}).get("name")
                or "守護群"
            ),
            "recipient_count": max(1, len(group_delivery_members.get(group_id) or [])),
            "status": "pending",
            "retry_key": f"{sos_event_id}:group:{group_id}",
        }
        for group_id in active_group_ids
    ] + [{
        "kind": "self",
        "target": line_user_id,
        "display_name": "本人",
        "recipient_count": 1,
        "status": "pending",
        "message": self_confirmation,
        "retry_key": _line_retry_key(f"{sos_event_id}:self:{line_user_id}"),
    }]

    def persist_sos_outbox(latest):
        latest_profile = (latest.get("users") or {}).get(line_user_id)
        if latest_profile is None:
            return
        latest_profile["last_sos_event_id"] = sos_event_id
        if location:
            stored_location = dict(latest_profile.get("location") or {})
            stored_location.update(copy.deepcopy(location))
            latest_profile["location"] = stored_location
        latest.setdefault("sos_events", {})[sos_event_id] = {
            "event_id": sos_event_id,
            "owner_line_user_id": line_user_id,
            "owner_display_name": profile.get("display_name") or "會員",
            "status": "sending",
            "created_at": now_dt.isoformat(timespec="seconds"),
            "sent_at": None,
            "deliveries": copy.deepcopy(prepared_deliveries),
            "escalation_guardians": copy.deepcopy(prepared_escalation_guardians),
            "message": message,
            "location_attached": bool(location_text),
            "abuse_mode": abuse["mode"],
        }

    mutate_state_atomically(data_file, persist_sos_outbox)
    state = load_state(data_file)
    profile = (state.get("users") or {}).get(line_user_id) or profile
    notification_log_start = len(state.get("notification_logs") or [])
    usage_start = len(state.get("line_message_usage") or [])

    sender = (config or {}).get("LINE_PUSH_SENDER") or line_push_message
    sent = 0
    sent_at = None
    failed = 0
    group_sent = 0
    group_failed = 0
    results = []
    deliveries = []
    guardian_results = []
    group_results = []
    print(
        f"[sos] trigger user={line_user_id[:8]} line_targets={len(line_contacts)} "
        f"groups={len(active_group_ids)} loc={bool(location_text)} phone_only={len(phone_contacts)}",
        flush=True,
    )
    for contact in line_contacts:
        target = contact["line_id"]
        delivery_retry_key = _line_retry_key(
            f"{sos_event_id}:guardian:{target}"
        )
        try:
            guardian_message = (
                build_sos_guardian_flex(message, sos_event_id)
                if sender is line_push_message
                else message
            )
            result = _send_line_with_retry_key(
                sender,
                token,
                target,
                guardian_message,
                delivery_retry_key,
            )
            append_notification_log(state, "sos", target, "sent", message, json.dumps(result, ensure_ascii=False))
            sent += 1
            if sent_at is None:
                sent_at = current_app_time(config or {}).isoformat(timespec="seconds")
            results.append({"line_user_id": target, "status": "sent"})
            deliveries.append({
                "kind": "guardian",
                "target": target,
                "display_name": str(contact.get("name") or contact.get("relationship") or "核心守護人"),
                "recipient_count": 1,
                "status": "sent",
                "retry_key": delivery_retry_key,
            })
            guardian_results.append({
                "name": str(contact.get("name") or contact.get("relationship") or "核心守護人"),
                "status": "sent",
            })
            print(f"[sos] push ok target={str(target)[:8]}", flush=True)
        except Exception as exc:
            append_notification_log(state, "sos", target, "failed", message, str(exc))
            failed += 1
            results.append({
                "line_user_id": target,
                "status": "failed",
                "error_hint": classify_line_push_error(exc),
            })
            deliveries.append({
                "kind": "guardian",
                "target": target,
                "display_name": str(contact.get("name") or contact.get("relationship") or "核心守護人"),
                "recipient_count": 1,
                "status": "failed",
                "retry_key": delivery_retry_key,
            })
            guardian_results.append({
                "name": str(contact.get("name") or contact.get("relationship") or "核心守護人"),
                "status": "failed",
                "error_hint": classify_line_push_error(exc),
            })
            print(f"[sos] push FAIL target={str(target)[:8]} err={str(exc)[:180]}", flush=True)

    for group_id in active_group_ids:
        delivery_retry_key = f"{sos_event_id}:group:{group_id}"
        try:
            group_info = (state.get("guardian_groups") or {}).get(group_id) or {}
            member_ids = list(group_delivery_members.get(group_id) or [])
            result, mention_mode, _payload = push_sos_to_guardian_group(
                token,
                group_id,
                message,
                sender=sender,
                member_ids=member_ids,
                retry_key=delivery_retry_key,
            )
            append_notification_log(
                state,
                "sos_guardian_group",
                group_id,
                "sent",
                message,
                json.dumps({"result": result, "mention": mention_mode}, ensure_ascii=False),
            )
            sent += 1
            if sent_at is None:
                sent_at = current_app_time(config or {}).isoformat(timespec="seconds")
            group_sent += 1
            results.append({
                "group_id": group_id,
                "status": "sent",
                "mention": mention_mode,
            })
            deliveries.append({
                "kind": "group",
                "target": group_id,
                "display_name": str(group_info.get("group_name") or group_info.get("name") or "守護群"),
                "recipient_count": max(1, len(member_ids)),
                "status": "sent",
                "retry_key": delivery_retry_key,
            })
            group_results.append({
                "name": str(group_info.get("group_name") or group_info.get("name") or "守護群"),
                "status": "sent",
                "mention": mention_mode,
            })
            print(f"[sos] group push ok group={str(group_id)[:8]} mention={mention_mode}", flush=True)
        except Exception as exc:
            append_notification_log(state, "sos_guardian_group", group_id, "failed", message, str(exc))
            failed += 1
            group_failed += 1
            results.append({"group_id": group_id, "status": "failed"})
            deliveries.append({
                "kind": "group",
                "target": group_id,
                "display_name": str(group_info.get("group_name") or group_info.get("name") or "守護群"),
                "recipient_count": max(1, len(group_delivery_members.get(group_id) or [])),
                "status": "failed",
                "retry_key": delivery_retry_key,
            })
            group_info = (state.get("guardian_groups") or {}).get(group_id) or {}
            group_results.append({
                "name": str(group_info.get("group_name") or group_info.get("name") or "守護群"),
                "status": "failed",
                "error_hint": classify_line_push_error(exc),
            })
            print(f"[sos] group push FAIL group={str(group_id)[:8]} err={str(exc)[:180]}", flush=True)

    self_result = {"status": "not_sent"}
    self_delivery = copy.deepcopy(prepared_deliveries[-1])
    if sent:
        confirmation = (
            f"✅ SOS 已送出\n"
            f"已通知 {sent} 個守護對象，失敗 {failed} 個\n"
            f"{'已附上這次取得的位置' if location_text else '這次未附即時位置'}\n"
            "若是誤觸或目前已安全，請在 10 分鐘內回到 SOS 畫面取消通知"
        )
        try:
            result = _send_line_with_retry_key(
                sender,
                token,
                line_user_id,
                confirmation,
                _line_retry_key(f"{sos_event_id}:self:{line_user_id}"),
            )
            append_notification_log(
                state, "sos_self_confirmation", line_user_id, "sent",
                confirmation, json.dumps(result, ensure_ascii=False),
            )
            self_result = {"status": "sent"}
            self_delivery["status"] = "sent"
        except Exception as exc:
            append_notification_log(
                state, "sos_self_confirmation", line_user_id, "failed",
                confirmation, str(exc),
            )
            self_result = {
                "status": "failed",
                "error_hint": classify_line_push_error(exc),
            }
            self_delivery["status"] = "failed"
            self_delivery["error_hint"] = self_result["error_hint"]
    deliveries.append(self_delivery)

    profile["last_sos_event_id"] = sos_event_id
    state.setdefault("sos_events", {})[sos_event_id] = {
        "event_id": sos_event_id,
        "owner_line_user_id": line_user_id,
        "owner_display_name": profile.get("display_name") or "會員",
        "status": "sent" if sent else "delivery_failed",
        "created_at": now_dt.isoformat(timespec="seconds"),
        "sent_at": sent_at,
        "deliveries": deliveries,
        "escalation_guardians": copy.deepcopy(prepared_escalation_guardians),
        "message": message,
        "location_attached": bool(location_text),
        "abuse_mode": abuse["mode"],
        "push_budget": budget,
    }
    sos_units = 0
    for delivery in deliveries:
        if delivery.get("status") != "sent":
            continue
        if delivery.get("kind") == "group":
            sos_units += max(1, int(delivery.get("recipient_count") or 1))
        elif delivery.get("kind") == "self":
            continue
        else:
            sos_units += 1
    if self_result.get("status") == "sent":
        sos_units += 1
    record_line_message_usage(
        state,
        category="sos",
        owner_line_user_id=line_user_id,
        recipient_count=sos_units,
        event_id=sos_event_id,
        sent_at=now_dt,
    )
    code = 200 if sent else 502
    cancel_available = sent > 0
    pending_event = None
    if cancel_available:
        pending_event = {
            "stage": "sent",
            "tap_count": 3,
            "first_tap_at": now_dt.isoformat(timespec="seconds"),
            "last_tap_at": now_dt.isoformat(timespec="seconds"),
            "sent_at": sent_at,
            "event_id": sos_event_id,
        }
    event_record = copy.deepcopy(state["sos_events"][sos_event_id])
    delivery_logs = copy.deepcopy(
        (state.get("notification_logs") or [])[notification_log_start:]
    )
    delivery_usage = copy.deepcopy(
        (state.get("line_message_usage") or [])[usage_start:]
    )
    profile_patch = {
        "last_sos_event_id": sos_event_id,
    }
    if location:
        profile_patch["location"] = copy.deepcopy(profile.get("location") or location)

    def merge_sos_delivery(latest):
        latest_profile = (latest.get("users") or {}).get(line_user_id)
        if latest_profile is not None:
            latest_profile.update(copy.deepcopy(profile_patch))
            latest_policy = sos_abuse_state(latest_profile, now_dt)
            latest_profile["sos_abuse_mode"] = latest_policy["mode"]
            latest_profile["sos_abuse_expires_at"] = latest_policy["expires_at"]
        latest.setdefault("sos_events", {})[sos_event_id] = copy.deepcopy(event_record)
        if pending_event:
            latest.setdefault("sos_pending", {})[line_user_id] = copy.deepcopy(pending_event)
        if delivery_logs:
            logs = list(latest.get("notification_logs") or [])
            logs.extend(copy.deepcopy(delivery_logs))
            latest["notification_logs"] = logs[-100:]
        if delivery_usage:
            ledger = list(latest.get("line_message_usage") or [])
            known_keys = {
                str(row.get("key") or "")
                for row in ledger
                if isinstance(row, dict)
            }
            for row in delivery_usage:
                key = str(row.get("key") or "")
                if key and key not in known_keys:
                    ledger.append(copy.deepcopy(row))
                    known_keys.add(key)
            latest["line_message_usage"] = ledger[-10000:]

    mutate_state_atomically(data_file, merge_sos_delivery)
    return {
        "sent": sent,
        "failed": failed,
        "group_sent": group_sent,
        "group_failed": group_failed,
        "guardian_limit": limit,
        "self": self_result,
        "guardians": guardian_results,
        "groups": group_results,
        "results": [*guardian_results, *group_results],
        "location_attached": bool(location_text),
        "phone_only_count": len(phone_contacts),
        "phone_contacts": phone_contacts[:5],
        "event_id": sos_event_id,
        "sent_at": sent_at,
        "location_updated_at": location.get("updated_at") if location_text else None,
        "cancel_available": cancel_available,
        "abuse_mode": abuse["mode"],
        "abuse_expires_at": abuse["expires_at"],
        "emergency_numbers_available": True,
        "emergency_numbers": ["119", "110"],
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
    requested_plan = str(payload.get("plan") or "trial")
    beta_cohort = (
        requested_plan.removeprefix("beta_").upper()
        if requested_plan.startswith("beta_")
        else ""
    )
    if requested_plan not in PLAN_LIMITS and beta_cohort not in BETA_COHORT_PLAN:
        return {"error": "unknown plan"}, 400
    plan = BETA_COHORT_PLAN.get(beta_cohort, requested_plan)
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
    if beta_cohort:
        now = current_app_time({})
        profile["membership_source"] = "beta"
        profile["free_eligibility_source"] = f"beta_{beta_cohort}"
        profile["free_eligibility_used_at"] = now.isoformat(timespec="seconds")
        profile["payment_status"] = "beta"
        profile["beta_cohort"] = beta_cohort
        profile["beta_started_at"] = now.isoformat(timespec="seconds")
        profile["beta_ends_at"] = (
            now + timedelta(days=BETA_TRIAL_DAYS)
        ).isoformat(timespec="seconds")
        profile["beta_revoked_at"] = None
        profile["beta_recruitment_source"] = str(
            payload.get("source") or profile.get("beta_recruitment_source") or ""
        ).strip()[:80]
    elif plan.startswith("paid_"):
        profile["membership_source"] = "paid"
        profile["trial_policy_version"] = TRIAL_POLICY_VERSION
        profile["trial_bonus_days"] = 0
        profile["beta_cohort"] = ""
        profile["beta_started_at"] = ""
        profile["beta_ends_at"] = ""
        profile["beta_revoked_at"] = None
    elif plan == "free":
        profile["membership_source"] = "expired"
    elif plan == "trial" and not str(profile.get("membership_source") or ""):
        profile["membership_source"] = "public_trial"
    if not beta_cohort:
        profile["payment_status"] = str(
            payload.get("payment_status") or ("trial" if plan == "trial" else "active")
        )

    paid_until = str(payload.get("paid_until") or "").strip()
    if not paid_until:
        paid_until = str(profile.get("paid_until") or "").strip()
        existing_expiry = parse_datetime(paid_until) if paid_until else None
        if plan.startswith("paid_") and existing_expiry:
            comparable_expiry, comparable_now = _comparable_datetimes(
                existing_expiry, current_app_time({})
            )
            if comparable_expiry < comparable_now:
                paid_until = ""
    # 後台改成付費方案但未填到期日時，自動補合理到期日，避免被過期降級排程立刻打回 free
    if plan.startswith("paid_") and not beta_cohort and not paid_until:
        product = PAYMENT_PRODUCTS.get(plan) or {}
        days = int(product.get("duration_days") or (365 if "year" in plan else 30))
        paid_until = (datetime.now() + timedelta(days=days)).isoformat(timespec="seconds")
        profile["billing_cycle"] = product.get("billing_cycle") or (
            "yearly" if "year" in plan else "monthly"
        )
    if paid_until and not beta_cohort:
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

    # 付費／重新開通試用：取消 30 天軟保留倒數（資料續留）
    if plan.startswith("paid_") or (plan == "trial" and trial_days_left(profile) > 0):
        clear_contacts_retain_window(profile)

    # 後台升級到含守護群方案：自動授予守護群管理員
    admin_granted = ensure_guardian_group_admin_for_user(state, profile)

    save_state(data_file, state)
    status = build_status(profile, state)
    status["preserved_contacts"] = len(preserved_contacts)
    status["preserved_friends"] = len(preserved_friends)
    status["preserved_guardian_groups"] = len(preserved_groups)
    status["guardian_group_admin_granted"] = admin_granted
    return status, 200


def admin_set_core_guardian(data_file, payload):
    """後台指定／取消核心守護人（is_primary）。可同時指定多位，上限依方案 core_guardian_alert_limit。"""
    line_user_id = str(payload.get("line_user_id") or "").strip()
    if not line_user_id:
        return {"error": "missing line_user_id"}, 400
    contact_id = str(payload.get("contact_id") or "").strip()
    contact_line_id = str(
        payload.get("contact_line_user_id") or payload.get("guardian_line_user_id") or ""
    ).strip()
    if not contact_id and not contact_line_id:
        return {"error": "missing contact_id or contact_line_user_id"}, 400
    make_core = payload.get("is_primary")
    if make_core is None:
        make_core = True
    make_core = bool(make_core)

    state = load_state(data_file)
    profile = state.get("users", {}).get(line_user_id)
    if not profile:
        return {"error": "member not found"}, 404
    contacts = list(profile.get("contacts") or [])
    if not contacts:
        return {"error": "no contacts"}, 400

    target_idx = None
    for i, c in enumerate(contacts):
        cid = str(c.get("id") or "")
        lid = str(c.get("line_id") or c.get("line_user_id") or "")
        if contact_id and cid == contact_id:
            target_idx = i
            break
        if contact_line_id and lid == contact_line_id:
            target_idx = i
            break
    if target_idx is None:
        return {"error": "contact_not_found"}, 404

    limit = int(plan_rules(profile).get("core_guardian_alert_limit") or 1)
    now = iso_now()
    if make_core:
        contacts[target_idx]["is_primary"] = True
        contacts[target_idx]["updated_at"] = now
        # 超過方案核心人數時，依 priority 保留較前面的核心
        core_idxs = [
            i for i, c in enumerate(contacts)
            if bool(c.get("is_primary"))
        ]
        if len(core_idxs) > limit:
            core_idxs_sorted = sorted(
                core_idxs,
                key=lambda i: int(contacts[i].get("priority") or 9999),
            )
            keep = set(core_idxs_sorted[:limit])
            # 確保剛指定的目標一定留下
            if target_idx not in keep:
                keep = set(core_idxs_sorted[: max(0, limit - 1)] + [target_idx])
                keep = set(list(keep)[:limit])
            for i, c in enumerate(contacts):
                if bool(c.get("is_primary")) and i not in keep:
                    c["is_primary"] = False
                    c["updated_at"] = now
    else:
        contacts[target_idx]["is_primary"] = False
        contacts[target_idx]["updated_at"] = now
        # 不可全部沒有核心：若無人是核心，把順位最高者補回
        if contacts and not any(bool(c.get("is_primary")) for c in contacts):
            ranked = sorted(range(len(contacts)), key=lambda i: int(contacts[i].get("priority") or 9999))
            contacts[ranked[0]]["is_primary"] = True
            contacts[ranked[0]]["updated_at"] = now

    profile["contacts"] = contacts
    save_state(data_file, state)
    status = build_status(profile, state)
    status["ok"] = True
    status["updated_contact"] = contacts[target_idx]
    return status, 200


def create_support_ticket(data_file, payload):
    line_user_id = str(payload.get("line_user_id") or "").strip()
    message = str(payload.get("message") or "").strip()
    if not line_user_id or not message:
        return {"error": "missing line_user_id or message"}, 400
    state = load_state(data_file)
    profile = get_profile(state, line_user_id)
    email = str(payload.get("email") or profile.get("contact_email") or "").strip()
    reply_channel = str(payload.get("reply_channel") or "").strip().lower()
    if not reply_channel:
        reply_channel = "email" if email else "line"
    if reply_channel not in {"email", "line"}:
        return {"error": "invalid reply_channel"}, 400
    if reply_channel == "email" and not re.match(
        r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email
    ):
        return {"error": "valid email required"}, 400
    ticket = {
        "id": secrets.token_urlsafe(8),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "line_user_id": line_user_id,
        "display_name": str(payload.get("display_name") or profile.get("display_name") or "LINE 使用者"),
        "email": email,
        "reply_channel": reply_channel,
        "category": str(payload.get("category") or "其他").strip()[:40],
        "subject": str(payload.get("subject") or "").strip()[:120],
        "message": message[:1000],
        "status": "submitted",
        "plan": profile.get("plan", "trial"),
        "last_check_in": profile.get("last_check_in"),
        "reply": "",
        "replied_at": "",
        "delivery_log": [],
    }
    tickets = state.setdefault("support_tickets", [])
    tickets.append(ticket)
    state["support_tickets"] = tickets[-200:]
    save_state(data_file, state)
    return {"ticket": ticket}, 201


def member_support_tickets(data_file, line_user_id):
    owner_id = str(line_user_id or "").strip()
    if not owner_id:
        return {"error": "missing line_user_id"}, 400
    state = load_state(data_file)
    tickets = [
        ticket
        for ticket in reversed(state.get("support_tickets", [])[-200:])
        if str(ticket.get("line_user_id") or "") == owner_id
    ]
    return {"tickets": tickets}, 200


def send_support_email(to_email, subject, message, config=None):
    config = config or {}
    host = str(config.get("SMTP_HOST") or os.environ.get("SMTP_HOST") or "").strip()
    username = str(
        config.get("SMTP_USERNAME") or os.environ.get("SMTP_USERNAME") or ""
    ).strip()
    password = str(
        config.get("SMTP_PASSWORD") or os.environ.get("SMTP_PASSWORD") or ""
    )
    from_email = str(
        config.get("SUPPORT_FROM_EMAIL")
        or os.environ.get("SUPPORT_FROM_EMAIL")
        or username
    ).strip()
    if not host or not username or not password or not from_email:
        raise RuntimeError("support_email_not_configured")
    port = int(config.get("SMTP_PORT") or os.environ.get("SMTP_PORT") or 587)
    use_tls = str(
        config.get("SMTP_USE_TLS")
        if config.get("SMTP_USE_TLS") is not None
        else os.environ.get("SMTP_USE_TLS", "true")
    ).strip().lower() in {"1", "true", "yes", "on"}
    email = EmailMessage()
    email["From"] = from_email
    email["To"] = to_email
    email["Subject"] = subject
    email.set_content(message)
    factory = config.get("SMTP_FACTORY") or smtplib.SMTP
    with factory(host, port, timeout=10) as smtp:
        if use_tls:
            smtp.starttls()
        smtp.login(username, password)
        smtp.send_message(email)
    return {"sent": True, "provider": "smtp"}


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
    reply_channel = str(
        payload.get("reply_channel") or ticket.get("reply_channel") or "line"
    ).lower()
    now = datetime.now().isoformat(timespec="seconds")
    delivery = {"channel": reply_channel, "status": "failed", "created_at": now}
    try:
        if reply_channel == "email":
            email = str(ticket.get("email") or "").strip()
            sender = (config or {}).get("SUPPORT_EMAIL_SENDER") or send_support_email
            if not email:
                return {"error": "ticket email is missing"}, 400
            result = sender(
                email,
                str(ticket.get("subject") or "每日平安客服回覆"),
                message,
                config or {},
            )
            target = email
        elif reply_channel == "line":
            target = str(ticket.get("line_user_id") or "")
            if target.startswith(("C", "R")):
                return {"error": "line_private_reply_required"}, 400
            token = (config or {}).get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
            sender = (config or {}).get("LINE_PUSH_SENDER") or line_push_message
            if not token:
                return {"error": "LINE_CHANNEL_ACCESS_TOKEN is not set"}, 400
            result = sender(token, target, message)
        else:
            return {"error": "invalid reply_channel"}, 400
    except Exception:
        delivery["target"] = str(ticket.get("email") or ticket.get("line_user_id") or "")
        ticket.setdefault("delivery_log", []).append(delivery)
        save_state(data_file, state)
        return {"error": "support_delivery_failed", "ticket": ticket}, 502
    delivery.update({"status": "sent", "target": target})
    ticket.setdefault("delivery_log", []).append(delivery)
    ticket["status"] = (
        "resolved"
        if str(payload.get("status") or "") == "resolved"
        else "waiting_user"
    )
    ticket["reply_channel"] = reply_channel
    ticket["reply"] = message[:1000]
    ticket["replied_at"] = now
    append_notification_log(state, "support_reply", target, "sent", message, json.dumps(result, ensure_ascii=False))
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
    """Legacy compatibility hook; secure admin never permits open mode."""
    return False


def admin_allowed(config, password):
    return admin_password_matches(config, password)


def admin_auth_error_payload(config, password):
    """Return (payload, http_status) when auth fails; None when allowed."""
    if not admin_security_ready(config):
        return {"error": "admin_not_configured"}, 503
    if not admin_allowed(config, password):
        return {"error": "unauthorized"}, 401
    return None


def admin_security_ready(config):
    password = any(
        _normalize_admin_password(config.get(name, ""))
        for name in (
            "ADMIN_PASSWORD",
            "ADMIN_OPERATIONS_PASSWORD",
            "ADMIN_FINANCE_PASSWORD",
            "ADMIN_VIEWER_PASSWORD",
        )
    )
    session_secret = str(config.get("ADMIN_SESSION_SECRET") or "").strip()
    return bool(password and len(session_secret) >= 32)


def account_migration_ready(config):
    legacy_channel = str(
        config.get("LEGACY_LINE_LOGIN_CHANNEL_ID") or ""
    ).strip()
    current_channel = str(config.get("LINE_LOGIN_CHANNEL_ID") or "").strip()
    secret = str(config.get("ACCOUNT_MIGRATION_SECRET") or "").strip()
    return bool(
        legacy_channel
        and current_channel
        and len(secret.encode("utf-8")) >= 32
    )


ACCOUNT_MIGRATION_TICKET_RETENTION_DAYS = 30
ACCOUNT_MIGRATION_TICKET_MAX_PER_SOURCE = 20
ACCOUNT_MIGRATION_TICKET_GLOBAL_MAX = 2000
ACCOUNT_MIGRATION_AUDIT_RETENTION_DAYS = 90
ACCOUNT_MIGRATION_AUDIT_GLOBAL_MAX = 1000
ACCOUNT_MIGRATION_START_WINDOW_SECONDS = 600
ACCOUNT_MIGRATION_START_MAX_PER_WINDOW = 5
ACCOUNT_MIGRATION_INVALID_REDEEM_WINDOW_SECONDS = 600
ACCOUNT_MIGRATION_INVALID_REDEEM_MAX_PER_WINDOW = 30


def _account_migration_now(now=None):
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _account_migration_datetime(value):
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return _account_migration_now(parsed)


def purge_account_migration_history(state, now=None):
    current = _account_migration_now(now)
    ticket_cutoff = current - timedelta(
        days=ACCOUNT_MIGRATION_TICKET_RETENTION_DAYS
    )
    audit_cutoff = current - timedelta(
        days=ACCOUNT_MIGRATION_AUDIT_RETENTION_DAYS
    )
    tickets = state.get("account_migration_tickets") or {}
    active_tickets = []
    history_tickets = []
    for key, ticket in tickets.items():
        if not isinstance(ticket, dict):
            continue
        created = _account_migration_datetime(ticket.get("created_at"))
        expires = _account_migration_datetime(ticket.get("expires_at"))
        status = str(ticket.get("status") or "")
        if status == "pending" and expires and expires > current:
            active_tickets.append((key, ticket))
        elif created and created >= ticket_cutoff:
            history_tickets.append((key, ticket))
    history_tickets.sort(
        key=lambda item: str(item[1].get("created_at") or ""),
        reverse=True,
    )
    history_capacity = max(
        0,
        ACCOUNT_MIGRATION_TICKET_GLOBAL_MAX - len(active_tickets),
    )
    # Capacity is a write/history bound, never a reason to invalidate an
    # inherited, unused ticket that has not expired.
    retained_tickets = active_tickets + history_tickets[:history_capacity]
    state["account_migration_tickets"] = dict(retained_tickets)

    audit = [
        event
        for event in (state.get("account_migration_audit") or [])
        if isinstance(event, dict)
        and (
            _account_migration_datetime(event.get("created_at"))
            and _account_migration_datetime(event.get("created_at"))
            >= audit_cutoff
        )
    ][-ACCOUNT_MIGRATION_AUDIT_GLOBAL_MAX:]
    removed = {
        "tickets": len(tickets) - len(state["account_migration_tickets"]),
        "audit": len(state.get("account_migration_audit") or []) - len(audit),
    }
    state["account_migration_audit"] = audit
    return removed


def account_migration_code_digest(code, secret):
    return hmac.new(
        str(secret or "").encode("utf-8"),
        str(code or "").encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def validate_account_migration_ticket(state, code, secret, now=None):
    """Return a pending ticket or a fixed safe error category.

    This helper only validates ticket state. Task 4 performs consumption and
    profile mutation together inside the atomic persistence boundary.
    """
    raw_code = str(code or "").strip()
    signing_secret = str(secret or "").strip()
    if not raw_code or not signing_secret:
        return None, "invalid_code"

    expected_digest = account_migration_code_digest(raw_code, signing_secret)
    matched = None
    for ticket in (state.get("account_migration_tickets") or {}).values():
        candidate = str((ticket or {}).get("code_digest") or "")
        if secrets.compare_digest(candidate, expected_digest):
            matched = ticket

    if not isinstance(matched, dict):
        return None, "invalid_code"
    status = str(matched.get("status") or "")
    if status == "used":
        return None, "used_code"
    expires_at = _account_migration_datetime(matched.get("expires_at"))
    if status == "expired" or not expires_at:
        return None, "expired_code"
    if _account_migration_now(now) >= expires_at:
        return None, "expired_code"
    if status != "pending":
        return None, "invalid_code"

    old_line_user_id = str(matched.get("old_line_user_id") or "")
    users = state.get("users") or {}
    aliases = state.get("account_migration_aliases") or {}
    if old_line_user_id not in users or old_line_user_id in aliases:
        return None, "source_missing"
    return matched, None


def create_account_migration_ticket(
    data_file,
    old_line_user_id,
    config,
    now=None,
):
    if not account_migration_ready(config):
        return {"ok": False, "error": "migration_unavailable"}, 503

    verified_old_id = str(old_line_user_id or "").strip()
    current = _account_migration_now(now)
    current_iso = current.isoformat(timespec="seconds")
    ttl_seconds = int(config.get("ACCOUNT_MIGRATION_TTL_SECONDS") or 600)
    raw_code = secrets.token_urlsafe(32)
    ticket_id = f"amt_{secrets.token_urlsafe(12)}"

    def mutate(state):
        purge_account_migration_history(state, current)
        users = state.get("users") or {}
        aliases = state.get("account_migration_aliases") or {}
        if (
            not verified_old_id
            or verified_old_id not in users
            or verified_old_id in aliases
        ):
            return {"ok": False, "error": "account_not_found"}, 404
        tickets = state.setdefault("account_migration_tickets", {})
        recent_cutoff = current - timedelta(
            seconds=ACCOUNT_MIGRATION_START_WINDOW_SECONDS
        )
        recent = [
            ticket for ticket in tickets.values()
            if isinstance(ticket, dict)
            and ticket.get("old_line_user_id") == verified_old_id
            and (
                _account_migration_datetime(ticket.get("created_at"))
                and _account_migration_datetime(ticket.get("created_at"))
                >= recent_cutoff
            )
        ]
        source_tickets = [
            ticket for ticket in tickets.values()
            if isinstance(ticket, dict)
            and ticket.get("old_line_user_id") == verified_old_id
        ]
        if (
            len(recent) >= ACCOUNT_MIGRATION_START_MAX_PER_WINDOW
            or len(source_tickets) >= ACCOUNT_MIGRATION_TICKET_MAX_PER_SOURCE
            or len(tickets) >= ACCOUNT_MIGRATION_TICKET_GLOBAL_MAX
        ):
            return {"ok": False, "error": "rate_limited"}, 429
        for ticket in tickets.values():
            if (
                isinstance(ticket, dict)
                and ticket.get("old_line_user_id") == verified_old_id
                and ticket.get("status") == "pending"
            ):
                ticket["status"] = "expired"
                ticket["expires_at"] = current_iso
        tickets[ticket_id] = {
            "ticket_id": ticket_id,
            "code_digest": account_migration_code_digest(
                raw_code,
                config.get("ACCOUNT_MIGRATION_SECRET"),
            ),
            "old_line_user_id": verified_old_id,
            "created_at": current_iso,
            "expires_at": (
                current + timedelta(seconds=ttl_seconds)
            ).isoformat(timespec="seconds"),
            "used_at": "",
            "status": "pending",
        }
        return {
            "ok": True,
            "migration_code": raw_code,
            "expires_in": ttl_seconds,
        }, 200

    return mutate_state_atomically(data_file, mutate)


def account_migration_ticket_status(
    data_file,
    old_line_user_id,
    config,
    now=None,
):
    safe_status = {
        "ok": True,
        "configured": account_migration_ready(config),
        "pending": False,
        "expires_in": 0,
    }
    if not safe_status["configured"]:
        return safe_status

    verified_old_id = str(old_line_user_id or "").strip()
    state = load_state(data_file)
    current = _account_migration_now(now)
    remaining = 0
    users = state.get("users") or {}
    aliases = state.get("account_migration_aliases") or {}
    source_exists = verified_old_id in users and verified_old_id not in aliases
    for ticket in (state.get("account_migration_tickets") or {}).values():
        if (
            not isinstance(ticket, dict)
            or ticket.get("old_line_user_id") != verified_old_id
            or ticket.get("status") != "pending"
        ):
            continue
        expires_at = _account_migration_datetime(ticket.get("expires_at"))
        if not source_exists or not expires_at or current >= expires_at:
            continue
        remaining = max(remaining, int((expires_at - current).total_seconds()))

    safe_status["pending"] = remaining > 0
    safe_status["expires_in"] = remaining
    return safe_status


_MIGRATION_PROFILE_LIST_KEYS = {
    "contacts": ("id", "accepted_invite_id", "invite_id"),
    "contacts_archived": ("id", "accepted_invite_id", "invite_id"),
    "smart_reminders": ("id",),
    "guarding_details": ("id", "line_user_id"),
}

_MIGRATION_PREFERENCE_KEYS = {
    "preferences",
    "interaction_state",
    "smart_reminder_defaults",
    "grace_hours",
    "reminder_time",
    "reminder_times",
    "checkin_mode",
    "auto_checkin_on_open",
    "warning_cancel_minutes",
    "alert_channels",
    "attach_location_on_alert",
    "contact_capacity_reminder_enabled",
    "daily_checkin_reminder_enabled",
    "guardian_details_reminder_enabled",
    "expiry_remind_opt_out",
}

_MIGRATION_ENTITLEMENT_KEYS = {
    "plan",
    "membership_source",
    "trial_started_at",
    "trial_end",
    "trial_policy_version",
    "trial_notice_days_sent",
    "trial_bonus_days",
    "payment_status",
    "paid_until",
    "billing_cycle",
    "payment_provider",
    "payment_method_last4",
    "next_billing_date",
    "auto_renew_requested",
    "auto_renew_enabled",
    "auto_renew_status",
    "plan_expired_at",
    "contacts_retain_until",
}


def _migration_value_blank(value):
    return value is None or value == "" or value == [] or value == {}


def _migration_timestamp(value):
    if not value:
        return None
    return _account_migration_datetime(value)


def _migration_record_timestamp(record):
    if not isinstance(record, dict):
        return None
    for key in ("updated_at", "accepted_at", "created_at"):
        parsed = _migration_timestamp(record.get(key))
        if parsed:
            return parsed
    return None


def _migration_preference_timestamp(profile, key, value):
    if isinstance(value, dict):
        nested = _migration_timestamp(value.get("updated_at"))
        if nested:
            return nested
    return (
        _migration_timestamp((profile or {}).get(f"{key}_updated_at"))
        or _migration_timestamp((profile or {}).get("preferences_updated_at"))
    )


def _migration_choose_record(legacy, current):
    legacy_time = _migration_record_timestamp(legacy)
    current_time = _migration_record_timestamp(current)
    if current_time and (not legacy_time or current_time > legacy_time):
        return copy.deepcopy(current)
    return copy.deepcopy(legacy)


def _migration_stable_value(record, keys):
    if not isinstance(record, dict):
        return ""
    for key in keys:
        value = str(record.get(key) or "").strip()
        if value:
            return f"{key}:{value}"
    return ""


def _merge_migration_records(legacy_rows, current_rows, keys, prefix):
    merged = []
    positions = {}
    used_ids = {
        str(row.get("id") or "").strip()
        for row in [*(legacy_rows or []), *(current_rows or [])]
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    }
    generated_index = 0

    for source_name, rows in (("legacy", legacy_rows or []), ("current", current_rows or [])):
        for row in rows:
            if not isinstance(row, dict):
                row = {"value": copy.deepcopy(row)}
            else:
                row = copy.deepcopy(row)
            stable = _migration_stable_value(row, keys)
            if stable and stable in positions:
                position = positions[stable]
                if source_name == "current":
                    merged[position] = _migration_choose_record(
                        merged[position],
                        row,
                    )
                continue
            if not stable:
                generated_index += 1
                generated = f"migration-{prefix}-{generated_index:04d}"
                while generated in used_ids:
                    generated_index += 1
                    generated = f"migration-{prefix}-{generated_index:04d}"
                row["id"] = generated
                used_ids.add(generated)
                stable = f"id:{generated}"
            positions[stable] = len(merged)
            merged.append(row)
    return merged


def _migration_history_date(value):
    if isinstance(value, dict):
        raw = (
            value.get("date")
            or value.get("checkin_date")
            or value.get("checked_at")
            or value.get("created_at")
        )
    else:
        raw = value
    text = str(raw or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    return date_string_in_taipei(text)


def _merge_migration_history(legacy_rows, current_rows):
    by_date = {}
    undated = []
    for row in [*(legacy_rows or []), *(current_rows or [])]:
        normalized = _migration_history_date(row)
        if normalized:
            by_date[normalized] = normalized
        else:
            undated.append(copy.deepcopy(row))
    return [*sorted(by_date), *undated]


def _merge_migration_calendar_notes(legacy_notes, current_notes):
    if isinstance(legacy_notes, dict) or isinstance(current_notes, dict):
        merged = copy.deepcopy(legacy_notes) if isinstance(legacy_notes, dict) else {}
        used_ids = set()
        for notes in (legacy_notes, current_notes):
            for value in (notes or {}).values() if isinstance(notes, dict) else []:
                values = value if isinstance(value, list) else [value]
                for item in values:
                    if isinstance(item, dict) and item.get("id"):
                        used_ids.add(str(item["id"]))
        generated_index = 0

        def normalized_note_records(value):
            nonlocal generated_index
            values = value if isinstance(value, list) else [value]
            records = []
            for item in values:
                if isinstance(item, dict):
                    record = copy.deepcopy(item)
                else:
                    record = {"content": str(item or "")}
                if not str(record.get("id") or "").strip():
                    generated_index += 1
                    generated = f"migration-calendar-note-{generated_index:04d}"
                    while generated in used_ids:
                        generated_index += 1
                        generated = f"migration-calendar-note-{generated_index:04d}"
                    record["id"] = generated
                    used_ids.add(generated)
                records.append(record)
            return records

        for key, current_value in (
            current_notes.items() if isinstance(current_notes, dict) else []
        ):
            if key not in merged:
                merged[key] = copy.deepcopy(current_value)
                continue
            combined = []
            positions = {}
            for record in [
                *normalized_note_records(merged[key]),
                *normalized_note_records(current_value),
            ]:
                stable = str(record["id"])
                if stable in positions:
                    position = positions[stable]
                    combined[position] = _migration_choose_record(
                        combined[position],
                        record,
                    )
                    continue
                positions[stable] = len(combined)
                combined.append(record)
            merged[key] = combined[0] if len(combined) == 1 else combined
        return merged
    return _merge_migration_records(
        legacy_notes or [],
        current_notes or [],
        ("id",),
        "calendar-note",
    )


def _migration_entitlement_active(profile, now):
    plan = str((profile or {}).get("plan") or "")
    if plan not in PLAN_RANK:
        return False
    if plan == "trial":
        expires_at = _migration_timestamp((profile or {}).get("trial_end"))
        return bool(expires_at and expires_at > now)
    if str((profile or {}).get("payment_status") or "") != "active":
        return False
    expires_at = _migration_timestamp((profile or {}).get("paid_until"))
    return expires_at is None or expires_at > now


def _migration_entitlement_expiry(profile):
    plan = str((profile or {}).get("plan") or "")
    key = "trial_end" if plan == "trial" else "paid_until"
    return _migration_timestamp((profile or {}).get(key))


def _migration_choose_entitlement(legacy_profile, current_profile, now):
    candidates = [
        profile
        for profile in (legacy_profile or {}, current_profile or {})
        if _migration_entitlement_active(profile, now)
    ]
    if not candidates:
        return legacy_profile or current_profile or {}

    def entitlement_key(profile):
        expiry = _migration_entitlement_expiry(profile)
        expiry_score = expiry.timestamp() if expiry else float("inf")
        return (PLAN_RANK.get(str(profile.get("plan") or ""), -1), expiry_score)

    return max(candidates, key=entitlement_key)


def _migration_location_active(location, now):
    if not isinstance(location, dict):
        return False
    if not location.get("active") and not location.get("sharing"):
        return False
    if location.get("until_stop"):
        return True
    expires_at = _migration_timestamp(location.get("expires_at"))
    return bool(expires_at and expires_at > now)


def _merge_migration_location(legacy_location, current_location, now):
    legacy_active = _migration_location_active(legacy_location, now)
    current_active = _migration_location_active(current_location, now)
    if legacy_active and current_active:
        return _migration_choose_record(legacy_location, current_location)
    if current_active:
        return copy.deepcopy(current_location)
    if legacy_active:
        return copy.deepcopy(legacy_location)
    return {}


def merge_migration_profiles(old_profile, new_profile, now=None):
    """Deterministically merge two verified Provider profiles.

    Stable business identifiers drive collection deduplication. Display names
    and other human-readable attributes are never identity keys.
    """
    legacy = copy.deepcopy(old_profile or {})
    current = copy.deepcopy(new_profile or {})
    current_now = _account_migration_now(now)
    merged = copy.deepcopy(legacy)

    for key, value in current.items():
        if key in {
            "line_user_id",
            "history",
            "calendar_notes",
            "location",
            "friends",
            "guardian_group_ids",
            "guarding_for",
            "smart_reminder_sent_keys",
            *_MIGRATION_PROFILE_LIST_KEYS,
            *_MIGRATION_ENTITLEMENT_KEYS,
            *_MIGRATION_PREFERENCE_KEYS,
        }:
            continue
        if key == "display_name" and is_placeholder_display_name(value):
            continue
        if _migration_value_blank(value):
            continue
        if key in DEFAULT_PROFILE and value == DEFAULT_PROFILE.get(key):
            continue
        merged[key] = copy.deepcopy(value)

    merged["history"] = _merge_migration_history(
        legacy.get("history"),
        current.get("history"),
    )
    for key, stable_keys in _MIGRATION_PROFILE_LIST_KEYS.items():
        merged[key] = _merge_migration_records(
            legacy.get(key),
            current.get(key),
            stable_keys,
            key.replace("_", "-"),
        )
    merged["calendar_notes"] = _merge_migration_calendar_notes(
        legacy.get("calendar_notes"),
        current.get("calendar_notes"),
    )
    for key in (
        "friends",
        "guardian_group_ids",
        "guarding_for",
        "smart_reminder_sent_keys",
    ):
        merged[key] = list(
            dict.fromkeys([*(legacy.get(key) or []), *(current.get(key) or [])])
        )

    for key in _MIGRATION_PREFERENCE_KEYS:
        legacy_value = legacy.get(key)
        current_value = current.get(key)
        legacy_time = _migration_preference_timestamp(legacy, key, legacy_value)
        current_time = _migration_preference_timestamp(current, key, current_value)
        if current_time and (not legacy_time or current_time > legacy_time):
            merged[key] = copy.deepcopy(current_value)
        elif key in legacy:
            merged[key] = copy.deepcopy(legacy_value)
        elif key in current:
            merged[key] = copy.deepcopy(current_value)

    entitlement = _migration_choose_entitlement(legacy, current, current_now)
    for key in _MIGRATION_ENTITLEMENT_KEYS:
        if key in entitlement:
            merged[key] = copy.deepcopy(entitlement[key])

    merged["location"] = _merge_migration_location(
        legacy.get("location"),
        current.get("location"),
        current_now,
    )
    merged["line_user_id"] = str(current.get("line_user_id") or "").strip()
    return merged


_MIGRATION_REFERENCE_SCALAR_FIELDS = {
    "line_user_id",
    "line_id",
    "owner_line_user_id",
    "member_line_user_id",
    "requester_line_user_id",
    "payer_line_user_id",
    "recipient_line_user_id",
    "inviter_line_user_id",
    "contact_line_user_id",
    "guardian_line_user_id",
    "acceptor_line_user_id",
    "grantee_line_user_id",
    "accepted_by",
    "invited_by",
    "target",
}

_MIGRATION_REFERENCE_LIST_FIELDS = {
    "admin_line_user_ids",
    "member_ids_at_bind",
    "member_line_user_ids",
    "member_user_ids",
    "members",
    "friends",
    "guarding_for",
}

_MIGRATION_TOP_LEVEL_COLLECTION_KEYS = {
    "orders": ("order_id", "merchant_order_id", "merchant_trade_no"),
    "payment_records": ("transaction_id", "order_id", "merchant_order_id"),
    "payments": ("transaction_id", "order_id", "merchant_order_id"),
    "support_tickets": ("id", "ticket_id"),
    "privacy_requests": ("id", "request_id"),
    "notification_logs": ("id", "log_id", "event_id"),
    "checkin_warnings": ("id", "event_id", "log_id"),
    "checkin_warning_logs": ("id", "event_id", "log_id"),
    "sos_logs": ("id", "event_id", "log_id"),
    "contact_rewards": ("id", "reward_id"),
}

_MIGRATION_INDEX_KEYS = {
    "sos_pending",
    "location_grants",
    "checkin_warning_index",
    "location_grant_index",
}


def _reindex_migration_record(record, old_id, new_id, migration_event_id):
    if not isinstance(record, dict):
        return False
    changed = False
    for key, value in list(record.items()):
        if key in _MIGRATION_REFERENCE_SCALAR_FIELDS:
            if str(value or "") == old_id:
                record[key] = new_id
                changed = True
            continue
        if key in _MIGRATION_REFERENCE_LIST_FIELDS and isinstance(value, list):
            replaced = []
            list_changed = False
            for item in value:
                if isinstance(item, dict):
                    nested_changed = _reindex_migration_record(
                        item,
                        old_id,
                        new_id,
                        migration_event_id,
                    )
                    list_changed = list_changed or nested_changed
                    replaced.append(item)
                elif str(item or "") == old_id:
                    replaced.append(new_id)
                    list_changed = True
                else:
                    replaced.append(item)
            if list_changed:
                deduped = []
                seen_scalars = set()
                for item in replaced:
                    if isinstance(item, dict):
                        deduped.append(item)
                        continue
                    marker = str(item)
                    if marker in seen_scalars:
                        continue
                    seen_scalars.add(marker)
                    deduped.append(item)
                record[key] = deduped
                changed = True
            continue
        if isinstance(value, dict):
            changed = (
                _reindex_migration_record(
                    value,
                    old_id,
                    new_id,
                    migration_event_id,
                )
                or changed
            )
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    changed = (
                        _reindex_migration_record(
                            item,
                            old_id,
                            new_id,
                            migration_event_id,
                        )
                        or changed
                    )
    if changed:
        record["migration_event_id"] = migration_event_id
    return changed


def _dedupe_migration_collection(rows, stable_keys, prefix, migration_event_id):
    deduped = []
    positions = {}
    used_ids = {
        str(row.get("id") or "").strip()
        for row in rows
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    }
    generated_index = 0
    for row in rows:
        if not isinstance(row, dict):
            deduped.append(row)
            continue
        stable = _migration_stable_value(row, stable_keys)
        if not stable:
            generated_index += 1
            generated = f"migration-{prefix}-{generated_index:04d}"
            while generated in used_ids:
                generated_index += 1
                generated = f"migration-{prefix}-{generated_index:04d}"
            row["id"] = generated
            used_ids.add(generated)
            deduped.append(row)
            continue
        if stable not in positions:
            positions[stable] = len(deduped)
            deduped.append(row)
            continue

        position = positions[stable]
        previous = deduped[position]
        winner = _migration_choose_record(previous, row)
        loser = row if winner == previous else previous
        combined = copy.deepcopy(loser)
        combined.update(winner)
        combined["migration_event_id"] = migration_event_id
        deduped[position] = combined
    return deduped


def reindex_account_references(
    state,
    old_id,
    new_id,
    migration_event_id,
    now=None,
):
    """Replace exact account references without rewriting historical prose."""
    source_id = str(old_id or "").strip()
    target_id = str(new_id or "").strip()
    if not source_id or not target_id:
        raise ValueError("missing_identity")
    if source_id == target_id:
        raise ValueError("same_identity")

    event_id = str(migration_event_id or "").strip()
    if not event_id:
        raise ValueError("missing_migration_event")
    reindexed_records = 0

    for user_id, profile in (state.get("users") or {}).items():
        if user_id in {source_id, target_id} or not isinstance(profile, dict):
            continue
        if _reindex_migration_record(profile, source_id, target_id, event_id):
            reindexed_records += 1

    for group in (state.get("guardian_groups") or {}).values():
        if isinstance(group, dict) and _reindex_migration_record(
            group,
            source_id,
            target_id,
            event_id,
        ):
            reindexed_records += 1

    for invite in (state.get("friend_invites") or {}).values():
        if isinstance(invite, dict) and _reindex_migration_record(
            invite,
            source_id,
            target_id,
            event_id,
        ):
            reindexed_records += 1

    for collection_key, stable_keys in _MIGRATION_TOP_LEVEL_COLLECTION_KEYS.items():
        rows = state.get(collection_key) or []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            if _reindex_migration_record(
                row,
                source_id,
                target_id,
                event_id,
            ):
                reindexed_records += 1
        state[collection_key] = _dedupe_migration_collection(
            rows,
            stable_keys,
            collection_key.replace("_", "-"),
            event_id,
        )

    for index_key in _MIGRATION_INDEX_KEYS:
        index = state.get(index_key) or {}
        if not isinstance(index, dict):
            continue
        was_rekeyed = source_id in index
        if source_id in index:
            source_record = index.pop(source_id)
            if target_id in index:
                index[target_id] = _migration_choose_record(
                    source_record,
                    index[target_id],
                )
            else:
                index[target_id] = source_record
        record = index.get(target_id)
        if isinstance(record, dict):
            changed = _reindex_migration_record(
                record,
                source_id,
                target_id,
                event_id,
            )
            if changed or was_rekeyed:
                record["migration_event_id"] = event_id
                reindexed_records += 1
        state[index_key] = index

    return {"ok": True, "reindexed_records": reindexed_records}


def create_account_migration_alias(state, old_id, new_id, now=None):
    source_id = str(old_id or "").strip()
    target_id = str(new_id or "").strip()
    if not source_id or not target_id:
        raise ValueError("missing_identity")
    if source_id == target_id:
        raise ValueError("same_identity")
    current_iso = _account_migration_now(now).isoformat(timespec="seconds")
    state.setdefault("account_migration_aliases", {})[source_id] = {
        "target_line_user_id": target_id,
        "created_at": current_iso,
        "status": "disabled",
    }
    return state["account_migration_aliases"][source_id]


def _account_migration_record_references(record, line_user_id):
    if not isinstance(record, dict):
        return False
    return any(
        str(record.get(key) or "") == line_user_id
        for key in _MIGRATION_REFERENCE_SCALAR_FIELDS
    )


def _account_migration_safe_counts(state, profile, line_user_id):
    def owned_count(collection_key):
        return sum(
            1
            for record in (state.get(collection_key) or [])
            if _account_migration_record_references(record, line_user_id)
        )

    return {
        "checkins": len(profile.get("history") or []),
        "contacts": len(profile.get("contacts") or []),
        "groups": len(profile.get("guardian_group_ids") or []),
        "reminders": len(profile.get("smart_reminders") or []),
        "orders": owned_count("orders"),
        "requests": (
            owned_count("support_tickets")
            + owned_count("privacy_requests")
        ),
    }


def _append_account_migration_failure_audit(state, category, now):
    purge_account_migration_history(state, now)
    state.setdefault("account_migration_audit", []).append({
        "event_id": f"ame_{secrets.token_urlsafe(12)}",
        "status": "failed",
        "created_at": now.isoformat(timespec="seconds"),
        "failure_category": str(category),
        "counts": {
            "checkins": 0,
            "contacts": 0,
            "groups": 0,
            "reminders": 0,
            "orders": 0,
            "requests": 0,
        },
    })
    state["account_migration_audit"] = state["account_migration_audit"][
        -ACCOUNT_MIGRATION_AUDIT_GLOBAL_MAX:
    ]


def _account_migration_snapshot(
    state,
    ticket,
    old_line_user_id,
    new_line_user_id,
    event_id,
    now,
):
    users = state.get("users") or {}
    affected_users = {}
    for user_id, profile in users.items():
        if (
            user_id in {old_line_user_id, new_line_user_id}
            or not isinstance(profile, dict)
        ):
            continue
        reindexed_probe = copy.deepcopy(profile)
        if _reindex_migration_record(
            reindexed_probe,
            old_line_user_id,
            new_line_user_id,
            event_id,
        ):
            affected_users[user_id] = copy.deepcopy(profile)
    affected_keys = {
        "guardian_groups",
        "friend_invites",
        "account_migration_aliases",
        *_MIGRATION_TOP_LEVEL_COLLECTION_KEYS,
        *_MIGRATION_INDEX_KEYS,
    }
    snapshot_id = f"ams_{secrets.token_urlsafe(12)}"
    return snapshot_id, {
        "snapshot_id": snapshot_id,
        "event_id": event_id,
        "created_at": now.isoformat(timespec="seconds"),
        "purge_after": (now + timedelta(days=30)).isoformat(timespec="seconds"),
        "old_profile": copy.deepcopy(users.get(old_line_user_id)),
        "new_profile": (
            copy.deepcopy(users.get(new_line_user_id))
            if new_line_user_id in users
            else None
        ),
        "migration_ticket": copy.deepcopy(ticket),
        "affected_users": affected_users,
        "affected_top_level_records": {
            key: copy.deepcopy(state.get(key))
            for key in sorted(affected_keys)
            if key in state
        },
    }


def redeem_account_migration_ticket(
    data_file,
    code,
    new_line_user_id,
    config,
    now=None,
):
    if not account_migration_ready(config):
        return {"ok": False, "error": "migration_unavailable"}, 503

    current = _account_migration_now(now)
    verified_new_id = str(new_line_user_id or "").strip()
    raw_code = str(code or "").strip()

    def mutate(state):
        purge_account_migration_history(state, current)
        invalid_cutoff = current - timedelta(
            seconds=ACCOUNT_MIGRATION_INVALID_REDEEM_WINDOW_SECONDS
        )
        invalid_recent = sum(
            1
            for event in (state.get("account_migration_audit") or [])
            if isinstance(event, dict)
            and event.get("failure_category") == "invalid_code"
            and (
                _account_migration_datetime(event.get("created_at"))
                and _account_migration_datetime(event.get("created_at"))
                >= invalid_cutoff
            )
        )
        if invalid_recent >= ACCOUNT_MIGRATION_INVALID_REDEEM_MAX_PER_WINDOW:
            return {"ok": False, "error": "rate_limited"}, 429
        ticket, ticket_error = validate_account_migration_ticket(
            state,
            raw_code,
            config.get("ACCOUNT_MIGRATION_SECRET"),
            now=current,
        )
        error_statuses = {
            "invalid_code": 404,
            "expired_code": 410,
            "used_code": 409,
            "source_missing": 404,
        }
        if ticket_error:
            _append_account_migration_failure_audit(
                state,
                ticket_error,
                current,
            )
            return (
                {"ok": False, "error": ticket_error},
                error_statuses.get(ticket_error, 409),
            )

        old_line_user_id = str(ticket.get("old_line_user_id") or "").strip()
        aliases = state.get("account_migration_aliases") or {}
        if (
            not verified_new_id
            or old_line_user_id == verified_new_id
            or verified_new_id in aliases
        ):
            _append_account_migration_failure_audit(
                state,
                "unsafe_conflict",
                current,
            )
            return {"ok": False, "error": "unsafe_conflict"}, 409

        users = state.setdefault("users", {})
        old_profile = users.get(old_line_user_id)
        if not isinstance(old_profile, dict):
            _append_account_migration_failure_audit(
                state,
                "source_missing",
                current,
            )
            return {"ok": False, "error": "source_missing"}, 404
        new_profile = users.get(verified_new_id)
        if new_profile is not None and not isinstance(new_profile, dict):
            _append_account_migration_failure_audit(
                state,
                "unsafe_conflict",
                current,
            )
            return {"ok": False, "error": "unsafe_conflict"}, 409

        event_id = f"ame_{secrets.token_urlsafe(12)}"
        snapshot_id, snapshot = _account_migration_snapshot(
            state,
            ticket,
            old_line_user_id,
            verified_new_id,
            event_id,
            current,
        )
        state.setdefault("account_migration_snapshots", {})[snapshot_id] = snapshot

        merged_profile = merge_migration_profiles(
            old_profile,
            new_profile or {
                **DEFAULT_PROFILE,
                "line_user_id": verified_new_id,
            },
            now=current,
        )
        reindex_account_references(
            state,
            old_line_user_id,
            verified_new_id,
            event_id,
            now=current,
        )
        _reindex_migration_record(
            merged_profile,
            old_line_user_id,
            verified_new_id,
            event_id,
        )
        users[verified_new_id] = merged_profile
        users.pop(old_line_user_id, None)
        create_account_migration_alias(
            state,
            old_line_user_id,
            verified_new_id,
            now=current,
        )

        ticket["status"] = "used"
        ticket["used_at"] = current.isoformat(timespec="seconds")
        ticket["migration_event_id"] = event_id
        counts = _account_migration_safe_counts(
            state,
            merged_profile,
            verified_new_id,
        )
        state.setdefault("account_migration_audit", []).append({
            "event_id": event_id,
            "status": "success",
            "created_at": current.isoformat(timespec="seconds"),
            "failure_category": "",
            "counts": counts,
        })
        return {
            "ok": True,
            "status": "migrated",
            "counts": counts,
        }, 200

    try:
        return mutate_state_atomically(data_file, mutate)
    except Exception:
        try:
            mutate_state_atomically(
                data_file,
                lambda state: _append_account_migration_failure_audit(
                    state,
                    "migration_failed",
                    current,
                ),
            )
        except Exception:
            pass
        return {"ok": False, "error": "migration_failed"}, 500


def purge_account_migration_snapshots(state, now=None):
    current = _account_migration_now(now)
    snapshots = state.get("account_migration_snapshots") or {}
    retained = {}
    removed = 0
    for snapshot_id, snapshot in snapshots.items():
        purge_after = _account_migration_datetime(
            (snapshot or {}).get("purge_after")
            if isinstance(snapshot, dict)
            else None
        )
        if purge_after and purge_after <= current:
            removed += 1
            continue
        retained[snapshot_id] = snapshot
    state["account_migration_snapshots"] = retained
    return removed


def admin_password_matches(config, candidate):
    return admin_role_for_password(config, candidate) is not None


ADMIN_ROLE_PERMISSIONS = {
    "super_admin": {
        "backup.manage",
        "beta.manage",
        "incident.manage",
        "member.manage",
        "notification.manage",
        "order.manage",
        "privacy.manage",
        "support.manage",
        "system.manage",
    },
    "operations": {
        "beta.manage",
        "incident.manage",
        "member.manage",
        "notification.manage",
        "privacy.manage",
        "support.manage",
    },
    "finance": {"order.manage"},
    "viewer": set(),
}


def admin_role_for_password(config, candidate):
    if not admin_security_ready(config):
        return None
    got = _normalize_admin_password(candidate)
    if not got:
        return None
    role_passwords = (
        ("super_admin", "ADMIN_PASSWORD"),
        ("operations", "ADMIN_OPERATIONS_PASSWORD"),
        ("finance", "ADMIN_FINANCE_PASSWORD"),
        ("viewer", "ADMIN_VIEWER_PASSWORD"),
    )
    for role, config_name in role_passwords:
        expected = _normalize_admin_password(config.get(config_name, ""))
        if expected and secrets.compare_digest(expected, got):
            return role
    return None


def admin_permissions_for_role(role):
    return sorted(ADMIN_ROLE_PERMISSIONS.get(str(role or ""), set()))


ADMIN_LOGIN_ATTEMPTS = {}


def _admin_login_attempts(client_key, now=None):
    now = now or datetime.now()
    cutoff = now - timedelta(minutes=10)
    recent = [
        value for value in ADMIN_LOGIN_ATTEMPTS.get(client_key, [])
        if value >= cutoff
    ]
    ADMIN_LOGIN_ATTEMPTS[client_key] = recent
    return recent


def admin_login_rate_limited(client_key, now=None):
    return len(_admin_login_attempts(client_key, now)) >= 5


def record_admin_login_failure(client_key, now=None):
    now = now or datetime.now()
    recent = _admin_login_attempts(client_key, now)
    recent.append(now)
    ADMIN_LOGIN_ATTEMPTS[client_key] = recent[-5:]


_ADMIN_AUDIT_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "token",
    "secret",
    "csrf",
    "authorization",
    "cookie",
    "email",
    "phone",
    "mobile",
    "address",
    "lineuserid",
    "userid",
    "displayname",
    "fullname",
    "latitude",
    "longitude",
    "location",
    "ipaddress",
    "remoteaddr",
)


def _sanitize_admin_audit_metadata(value):
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            compact_key = re.sub(r"[^a-z0-9]", "", str(key).casefold())
            if (
                compact_key in {"name", "username"}
                or any(
                    part in compact_key
                    for part in _ADMIN_AUDIT_SENSITIVE_KEY_PARTS
                )
            ):
                continue
            cleaned[str(key)] = _sanitize_admin_audit_metadata(item)
        return cleaned
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_admin_audit_metadata(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def append_admin_audit(data_file, action, status, metadata=None):
    state = load_state(data_file)
    logs = list(state.get("admin_audit_logs") or [])
    logs.append({
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "action": str(action),
        "status": str(status),
        "metadata": _sanitize_admin_audit_metadata(dict(metadata or {})),
    })
    state["admin_audit_logs"] = logs[-200:]
    save_state(data_file, state)


ADMIN_TEST_CENTER_TESTS = {
    "daily_greeting": ("每日問候推播", "line"),
    "trial_14_notice": ("14 天體驗提醒", "line"),
    "beta_21_notice": ("21 天封測提醒", "line"),
    "paid_expiry_notice": ("付費方案到期提醒", "line"),
    "payment_restore": ("付款後恢復原設定", "simulation"),
    "sos_location": ("SOS、取消與定位通知", "line"),
    "guardian_invite": ("核心守護人邀請綁定", "line"),
    "beta_feedback_1900": ("19:00 封測詢問", "line"),
    "stop_renewal_notice": ("不再提醒我", "simulation"),
    "r2_backup": ("R2 加密備份", "r2"),
}


def _test_line_user_ids(config):
    raw = config.get("TEST_LINE_USER_IDS") or ""
    if isinstance(raw, (list, tuple, set)):
        values = raw
    else:
        values = str(raw).split(",")
    return [str(value).strip() for value in values if str(value).strip()]


def _masked_test_account(line_user_id):
    digest = hashlib.sha256(str(line_user_id).encode("utf-8")).hexdigest()[:8]
    return {"id": digest, "label": f"測試帳號 …{digest[-4:]}"}


def _test_center_integrations(config):
    configured = lambda key: bool(str(config.get(key) or "").strip())
    return {
        "line": {
            "configured": configured("LINE_CHANNEL_ACCESS_TOKEN"),
            "label": "LINE 推播",
        },
        "r2": {
            "configured": all(configured(key) for key in (
                "R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
                "R2_BUCKET", "R2_BACKUP_ENCRYPTION_KEY",
            )),
            "label": "R2 加密備份",
        },
        "ga4": {
            "configured": configured("GA4_MEASUREMENT_ID")
            and configured("GA4_PROPERTY_ID")
            and configured("GA4_SERVICE_ACCOUNT_JSON"),
            "label": "GA4 報表",
        },
        "payment": {
            "configured": (
                all(configured(key) for key in (
                    "ECPAY_MERCHANT_ID", "ECPAY_HASH_KEY", "ECPAY_HASH_IV",
                ))
                or all(configured(key) for key in (
                    "NEWEBPAY_MERCHANT_ID", "NEWEBPAY_HASH_KEY", "NEWEBPAY_HASH_IV",
                ))
            ),
            "live": (
                str(config.get("ECPAY_STAGE") or "sandbox").lower() == "production"
                or str(config.get("NEWEBPAY_STAGE") or "sandbox").lower() == "production"
            ),
            "label": "金流",
        },
    }


def admin_test_center_status(data_file, config):
    state = load_state(data_file)
    accounts = _test_line_user_ids(config)
    return {
        "test_mode": True,
        "test_accounts": [_masked_test_account(item) for item in accounts],
        "integrations": _test_center_integrations(config),
        "tests": [
            {"id": test_id, "label": label, "kind": kind}
            for test_id, (label, kind) in ADMIN_TEST_CENTER_TESTS.items()
        ],
        "recent_runs": list(reversed(state.get("test_center_runs") or []))[:20],
    }


def _test_center_message(test_id):
    label = ADMIN_TEST_CENTER_TESTS[test_id][0]
    details = {
        "daily_greeting": "這是每日問候推播測試，請確認文字與按鈕顯示正常。",
        "trial_14_notice": "這是 14 天體驗第 7／12／14 天提醒預覽。",
        "beta_21_notice": "這是 21 天封測第 18／20／21 天提醒預覽。",
        "paid_expiry_notice": "這是付費方案到期前 7／3／1 天與到期日提醒預覽。",
        "sos_location": "這是 SOS、取消 SOS 與定位通知的安全預覽，不會建立真實事件。",
        "guardian_invite": "這是核心守護人邀請與綁定說明預覽。",
        "beta_feedback_1900": "這是每天 19:00 封測使用詢問預覽。",
    }
    return f"【測試模式】{label}\n{details.get(test_id, '安全測試預覽')}\n不會扣款、不會變更方案。"


def run_admin_test(data_file, config, payload):
    payload = payload if isinstance(payload, dict) else {}
    test_id = str(payload.get("test_id") or "").strip()
    line_user_id = str(payload.get("line_user_id") or "").strip()
    if test_id not in ADMIN_TEST_CENTER_TESTS:
        return {"ok": False, "error": "unknown_test"}, 400
    allowed = _test_line_user_ids(config)
    account_id = str(payload.get("account_id") or "").strip()
    if not line_user_id and account_id:
        line_user_id = next(
            (
                item for item in allowed
                if _masked_test_account(item)["id"] == account_id
            ),
            "",
        )
    if line_user_id not in allowed:
        return {"ok": False, "error": "test_recipient_not_allowed"}, 403
    label, kind = ADMIN_TEST_CENTER_TESTS[test_id]
    status = "success"
    error = ""
    result = {"ok": True, "test_id": test_id, "label": label, "test_mode": True}
    try:
        if kind == "line":
            token = str(config.get("LINE_CHANNEL_ACCESS_TOKEN") or "").strip()
            if not token:
                raise ValueError("line_not_configured")
            sender = config.get("LINE_PUSH_SENDER") or line_push_message
            sender(token, line_user_id, _test_center_message(test_id))
            result["sent"] = True
        elif kind == "r2":
            backup, code = create_r2_encrypted_backup(config)
            if code >= 400:
                raise ValueError(str(backup.get("error") or "r2_backup_failed"))
            result["backup"] = {
                "key": str(backup.get("key") or ""),
                "created_at": str(backup.get("created_at") or ""),
            }
        else:
            result["simulated"] = True
            result["message"] = (
                "付款後恢復原設定模擬成功；未呼叫金流、未改方案。"
                if test_id == "payment_restore"
                else "不再提醒偏好模擬成功；未修改正式會員資料。"
            )
    except Exception as exc:
        status = "failed"
        error = classify_line_push_error(exc)
        result = {
            "ok": False,
            "error": error,
            "test_id": test_id,
            "test_mode": True,
        }

    state = load_state(data_file)
    runs = list(state.get("test_center_runs") or [])
    runs.append({
        "id": uuid.uuid4().hex[:12],
        "test_id": test_id,
        "label": label,
        "target": _masked_test_account(line_user_id)["label"],
        "status": status,
        "error": error,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    })
    state["test_center_runs"] = runs[-100:]
    save_state(data_file, state)
    return result, (200 if status == "success" else 502)


def resolve_admin_incident(data_file, payload, actor_role):
    kind = str((payload or {}).get("kind") or "").strip().casefold()
    incident_id = str((payload or {}).get("incident_id") or "").strip()
    note = str((payload or {}).get("resolution_note") or "").strip()[:500]
    if kind not in {"sos", "delivery"} or not incident_id:
        return {"ok": False, "error": "invalid_incident"}, 400
    state = load_state(data_file)
    resolved_at = datetime.now().isoformat(timespec="seconds")
    if kind == "sos":
        target = (state.get("sos_events") or {}).get(incident_id)
        if target is None:
            target = next(
                (
                    item
                    for item in (state.get("sos_pending") or {}).values()
                    if str(item.get("event_id") or "") == incident_id
                ),
                None,
            )
    else:
        target = next(
            (
                item
                for index, item in enumerate(state.get("notification_logs") or [])
                if str(item.get("incident_id") or f"delivery-{index}") == incident_id
                and item.get("status") in {"failed", "error"}
            ),
            None,
        )
    if target is None:
        return {"ok": False, "error": "incident_not_found"}, 404
    target["status"] = "resolved"
    target["resolved_at"] = resolved_at
    target["resolved_by_role"] = str(actor_role or "unknown")
    if note:
        target["resolution_note"] = note
    save_state(data_file, state)
    return {"ok": True, "kind": kind, "incident_id": incident_id, "resolved_at": resolved_at}, 200


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
    invite_text = None
    invite_type = None
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
            invite_text = action.get("text")
            invite_type = action.get("type")

    # 圖文選單必須進入永久 LIFF 入口。LIFF 會辨識登入會員、建立專屬邀請，
    # 隨即開啟 shareTargetPicker；不可把網站路徑附加在 LIFF ID 後方。
    invite_uri_ok = False
    if invite_uri:
        try:
            parsed_invite_uri = urllib.parse.urlparse(str(invite_uri).strip())
            invite_query = urllib.parse.parse_qs(parsed_invite_uri.query)
            invite_uri_ok = (
                parsed_invite_uri.scheme == "https"
                and parsed_invite_uri.netloc == "liff.line.me"
                and parsed_invite_uri.path.rstrip("/") == f"/{DEFAULT_LIFF_ID}"
                and invite_query.get("open") == ["share-invite"]
            )
        except (TypeError, ValueError):
            invite_uri_ok = False

    # 仍相容舊版 message「一鍵邀請」→ Bot Flex。
    invite_ok = invite_uri_ok or (
        invite_type == "message"
        and str(invite_text or "").strip() in {"一鍵邀請", "一鍵邀請守護人"}
    )

    return {
        "ok": True,
        "richMenuId": rich_menu_id,
        "name": detail.get("name"),
        "chatBarText": detail.get("chatBarText"),
        "areas": areas,
        "invite_uri": invite_uri,
        "invite_text": invite_text,
        "invite_type": invite_type,
        "invite_uri_ok": invite_ok,
    }, 200


def cron_allowed(config, secret):
    expected = (config.get("CRON_SECRET") or os.environ.get("CRON_SECRET", "") or "").strip()
    provided = str(secret or "").strip()
    # Empty CRON_SECRET must never authorize — fail closed.
    if not expected:
        return False
    return secrets.compare_digest(expected, provided)


def _positive_percentage(config, name, default):
    raw = config.get(name) if hasattr(config, "get") else None
    if raw in (None, ""):
        raw = os.environ.get(name, "")
    try:
        value = int(str(raw or default))
    except (TypeError, ValueError):
        return default
    return value if 1 <= value <= 100 else default


def line_message_budget_status(state, config=None, now=None):
    """Return system-recorded LINE usage without exposing configuration values."""
    cfg = config if config is not None and hasattr(config, "get") else {}
    generated_at = now or current_app_time(cfg)
    try:
        message_limit = max(
            1,
            int(str(cfg.get("LINE_MONTHLY_MESSAGE_LIMIT")
                    or os.environ.get("LINE_MONTHLY_MESSAGE_LIMIT", "")
                    or 200)),
        )
    except (TypeError, ValueError):
        message_limit = 200
    warning_percent = _positive_percentage(
        cfg, "LINE_MESSAGE_WARNING_PERCENT", 80
    )
    hard_stop_percent = _positive_percentage(
        cfg, "LINE_MESSAGE_HARD_STOP_PERCENT", 100
    )
    month_key = generated_at.strftime("%Y-%m")
    monthly_logs = [
        item
        for item in (state.get("notification_logs") or [])
        if not str(item.get("created_at") or "")
        or str(item.get("created_at") or "").startswith(month_key)
    ]
    used = len(monthly_logs)
    usage_percent = round(used / message_limit * 100, 1)
    hard_stop_active = usage_percent >= hard_stop_percent
    if used >= message_limit:
        status = "exceeded"
    elif usage_percent >= warning_percent:
        status = "warning"
    else:
        status = "healthy"
    return {
        "month": month_key,
        "used": used,
        "limit": message_limit,
        "remaining": max(0, message_limit - used),
        "usage_percent": usage_percent,
        "warning_percent": warning_percent,
        "hard_stop_percent": hard_stop_percent,
        "hard_stop_active": hard_stop_active,
        "status": status,
    }


def line_non_emergency_push_allowed(state, config=None, now=None):
    return not line_message_budget_status(state, config, now)["hard_stop_active"]


def line_push_allowed_for_kind(state, config, kind, now=None):
    emergency_kinds = {"sos", "safety_guard", "guardian_sos", "emergency"}
    if str(kind or "").strip().casefold() in emergency_kinds:
        return True
    return line_non_emergency_push_allowed(state, config, now)


def line_budget_blocked_response(state, config, now=None):
    budget = line_message_budget_status(state, config, now)
    return {
        "sent": 0,
        "skipped": 0,
        "error": "line_non_emergency_budget_hard_stop",
        "line_budget": budget,
    }, 429


BETA_COHORTS = {
    "known_10": {"label": "認識會員 10 人", "capacity": 10},
    "standard_20": {"label": "一般會員 20 人", "capacity": 20},
    "family_group_10": {"label": "家庭群組 10 人", "capacity": 10},
}
BETA_ACTIVE_STATUSES = {"active", "waitlisted"}
BETA_STATUSES = BETA_ACTIVE_STATUSES | {"completed", "withdrawn"}


def admin_beta_summary(data_file, now=None):
    state = load_state(data_file)
    members = list(state.get("beta_program_members") or [])
    current = now or current_app_time({})
    legacy_cohort_map = {
        "known_10": "A",
        "standard_20": "B399",
        "family_group_10": "B799",
    }
    backfilled = False
    for member in members:
        if member.get("status") not in BETA_ACTIVE_STATUSES:
            continue
        line_user_id = str(member.get("line_user_id") or "").strip()
        profile = (state.get("users") or {}).get(line_user_id)
        if not isinstance(profile, dict) or profile.get("membership_source") == "beta":
            continue
        entitlement_cohort = legacy_cohort_map.get(str(member.get("cohort") or ""))
        if not entitlement_cohort:
            continue
        started = parse_datetime(member.get("starts_at")) or current
        try:
            assign_beta_cohort(
                state,
                line_user_id,
                entitlement_cohort,
                now=started,
                recruitment_source=f"admin-{member.get('cohort')}",
            )
        except ValueError:
            continue
        if member.get("ends_at"):
            profile["beta_ends_at"] = str(member["ends_at"])
        backfilled = True
    if backfilled:
        save_state(data_file, state)
    cohorts = {}
    for key, definition in BETA_COHORTS.items():
        cohort_members = [row for row in members if row.get("cohort") == key]
        active = sum(
            1 for row in cohort_members if row.get("status") in BETA_ACTIVE_STATUSES
        )
        cohorts[key] = {
            **definition,
            "active": active,
            "completed": sum(
                1 for row in cohort_members if row.get("status") == "completed"
            ),
            "remaining": max(0, definition["capacity"] - active),
        }
    return {
        "duration_days": 21,
        "generated_at": current.isoformat(timespec="seconds"),
        "cohorts": cohorts,
        "members": list(reversed(members[-100:])),
    }


def assign_beta_member(data_file, payload, now=None):
    line_user_id = str((payload or {}).get("line_user_id") or "").strip()
    cohort = str((payload or {}).get("cohort") or "").strip()
    if not line_user_id or cohort not in BETA_COHORTS:
        return {"ok": False, "error": "invalid_beta_assignment"}, 400
    state = load_state(data_file)
    profile = (state.get("users") or {}).get(line_user_id)
    if profile is None:
        return {"ok": False, "error": "member_not_found"}, 404
    members = state.setdefault("beta_program_members", [])
    existing = next(
        (
            row for row in members
            if row.get("line_user_id") == line_user_id
            and row.get("status") in BETA_ACTIVE_STATUSES
        ),
        None,
    )
    if existing:
        return {"ok": False, "error": "beta_member_already_assigned"}, 409
    active_count = sum(
        1 for row in members
        if row.get("cohort") == cohort
        and row.get("status") in BETA_ACTIVE_STATUSES
    )
    if active_count >= BETA_COHORTS[cohort]["capacity"]:
        return {"ok": False, "error": "beta_cohort_full"}, 409
    started = now or current_app_time({})
    entitlement_cohort = {
        "known_10": "A",
        "standard_20": "B399",
        "family_group_10": "B799",
    }[cohort]
    try:
        assign_beta_cohort(
            state,
            line_user_id,
            entitlement_cohort,
            now=started,
            recruitment_source=f"admin-{cohort}",
        )
    except ValueError as exc:
        error = str(exc)
        return {"ok": False, "error": error}, (
            404 if error == "member_not_found"
            else 409 if error in {"cohort_full", "free_eligibility_already_used"}
            else 400
        )
    profile = state["users"][line_user_id]
    if not profile.get("reminder_times"):
        apply_reminder_times_to_profile(profile)
    member = {
        "line_user_id": line_user_id,
        "display_name": str(profile.get("display_name") or "未取得暱稱"),
        "cohort": cohort,
        "status": "active",
        "starts_at": started.isoformat(timespec="seconds"),
        "ends_at": (started + timedelta(days=21)).isoformat(timespec="seconds"),
        "outcome_note": "",
    }
    members.append(member)
    state["beta_program_members"] = members[-200:]
    save_state(data_file, state)
    return {"ok": True, "member": member}, 200


def update_beta_member(data_file, payload, now=None):
    line_user_id = str((payload or {}).get("line_user_id") or "").strip()
    status = str((payload or {}).get("status") or "").strip().casefold()
    if not line_user_id or status not in BETA_STATUSES:
        return {"ok": False, "error": "invalid_beta_update"}, 400
    state = load_state(data_file)
    member = next(
        (
            row for row in reversed(state.get("beta_program_members") or [])
            if row.get("line_user_id") == line_user_id
            and row.get("status") in BETA_ACTIVE_STATUSES
        ),
        None,
    )
    if member is None:
        return {"ok": False, "error": "beta_member_not_found"}, 404
    member["status"] = status
    member["updated_at"] = (now or current_app_time({})).isoformat(
        timespec="seconds"
    )
    note = str((payload or {}).get("outcome_note") or "").strip()[:500]
    if note:
        member["outcome_note"] = note
    save_state(data_file, state)
    return {"ok": True, "member": member}, 200


def admin_privacy_requests(data_file):
    state = load_state(data_file)
    requests = list(reversed((state.get("privacy_requests") or [])[-100:]))
    statuses = ("pending", "in_progress", "completed", "rejected")
    return {
        "requests": requests,
        "counts": {
            status: sum(1 for row in requests if row.get("status") == status)
            for status in statuses
        },
    }


def create_privacy_request(data_file, payload, now=None):
    line_user_id = str((payload or {}).get("line_user_id") or "").strip()
    request_type = str((payload or {}).get("request_type") or "").strip().casefold()
    if not line_user_id or request_type not in {
        "export", "deletion", "correction", "inquiry"
    }:
        return {"ok": False, "error": "invalid_privacy_request"}, 400
    state = load_state(data_file)
    if line_user_id not in (state.get("users") or {}):
        return {"ok": False, "error": "member_not_found"}, 404
    requests = state.setdefault("privacy_requests", [])
    if any(
        row.get("line_user_id") == line_user_id
        and row.get("request_type") == request_type
        and row.get("status") in {"pending", "in_progress"}
        for row in requests
    ):
        return {"ok": False, "error": "privacy_request_already_open"}, 409
    created = now or current_app_time({})
    privacy_request = {
        "id": f"privacy-{secrets.token_hex(8)}",
        "line_user_id": line_user_id,
        "request_type": request_type,
        "summary": str((payload or {}).get("summary") or "").strip()[:500],
        "status": "pending",
        "created_at": created.isoformat(timespec="seconds"),
    }
    requests.append(privacy_request)
    state["privacy_requests"] = requests[-200:]
    save_state(data_file, state)
    return {"ok": True, "request": privacy_request}, 201


def update_privacy_request(data_file, payload, actor_role):
    request_id = str((payload or {}).get("request_id") or "").strip()
    status = str((payload or {}).get("status") or "").strip().casefold()
    note = str((payload or {}).get("resolution_note") or "").strip()[:1000]
    if not request_id or status not in {
        "pending", "in_progress", "completed", "rejected"
    }:
        return {"ok": False, "error": "invalid_privacy_update"}, 400
    if status in {"completed", "rejected"} and not note:
        return {"ok": False, "error": "resolution_note_required"}, 400
    state = load_state(data_file)
    privacy_request = next(
        (
            row for row in (state.get("privacy_requests") or [])
            if str(row.get("id") or "") == request_id
        ),
        None,
    )
    if privacy_request is None:
        return {"ok": False, "error": "privacy_request_not_found"}, 404
    privacy_request["status"] = status
    privacy_request["updated_at"] = datetime.now().isoformat(timespec="seconds")
    privacy_request["resolved_by_role"] = str(actor_role or "unknown")
    if note:
        privacy_request["resolution_note"] = note
    save_state(data_file, state)
    return {"ok": True, "request": privacy_request}, 200


def admin_business_dashboard(data_file, config=None, now=None):
    """Aggregate non-sensitive commercial metrics for the protected admin UI."""
    state = load_state(data_file)
    cfg = config if config is not None and hasattr(config, "get") else {}
    generated_at = now or current_app_time(cfg)
    users = list((state.get("users") or {}).values())
    notification_logs = list(state.get("notification_logs") or [])
    sent = sum(1 for item in notification_logs if item.get("status") == "sent")
    failed = sum(1 for item in notification_logs if item.get("status") in {"failed", "error"})
    delivery_total = sent + failed

    def configured(name):
        return bool(str(cfg.get(name) or os.environ.get(name, "") or "").strip())

    ga4_measurement_id = str(
        cfg.get("GA4_MEASUREMENT_ID")
        or os.environ.get("GA4_MEASUREMENT_ID", "")
        or "G-7LT14XLHFM"
    ).strip()
    ga4_property = configured("GA4_PROPERTY_ID")
    ga4_credentials = configured("GA4_SERVICE_ACCOUNT_JSON")
    line_token = configured("LINE_CHANNEL_ACCESS_TOKEN")
    line_secret = configured("LINE_CHANNEL_SECRET")
    liff_id = configured("LIFF_ID")
    public_url = str(
        cfg.get("APP_PUBLIC_URL")
        or os.environ.get("APP_PUBLIC_URL", "")
        or "https://alive-checkin.onrender.com"
    ).strip().rstrip("/")
    wordpress_site = configured("WORDPRESS_SITE_URL")
    wordpress_user = configured("WORDPRESS_USERNAME")
    wordpress_password = configured("WORDPRESS_APPLICATION_PASSWORD")

    line_budget = line_message_budget_status(state, cfg, generated_at)

    pending_sos = [
        item
        for item in (state.get("sos_events") or {}).values()
        if str(item.get("status") or "pending").casefold()
        not in SOS_CLOSED_STATUSES
    ]
    known_sos_ids = {str(item.get("event_id") or "") for item in pending_sos}
    pending_sos.extend(
        item
        for item in (state.get("sos_pending") or {}).values()
        if str(item.get("event_id") or "") not in known_sos_ids
        and str(item.get("status") or "pending").casefold()
        not in SOS_CLOSED_STATUSES
    )
    delivery_failures = [
        dict(item, incident_id=str(item.get("incident_id") or f"delivery-{index}"))
        for index, item in enumerate(notification_logs)
        if item.get("status") in {"failed", "error"}
    ]
    public_pages = ("index.html", "pricing.html", "help.html", "privacy.html", "terms.html")
    project_root = Path(__file__).resolve().parent
    seo_pages = []
    for filename in public_pages:
        path = project_root / filename
        source = path.read_text(encoding="utf-8") if path.exists() else ""
        lowered = source.lower()
        checks = {
            "title": "<title" in lowered,
            "description": 'name="description"' in lowered or "name='description'" in lowered,
            "canonical": 'rel="canonical"' in lowered or "rel='canonical'" in lowered,
            "robots": 'name="robots"' in lowered or "name='robots'" in lowered,
            "structured_data": "application/ld+json" in lowered,
        }
        seo_pages.append(
            {
                "page": filename,
                "checks": checks,
                "passed": sum(1 for value in checks.values() if value),
                "total": len(checks),
            }
        )

    return {
        "generated_at": generated_at.isoformat(),
        "funnel": {
            "registered_members": len(users),
            "members_with_guardian": sum(
                1
                for user in users
                if any(get_contact_line_id(contact) for contact in (user.get("contacts") or []))
            ),
            "active_paid_members": sum(
                1
                for user in users
                if str(user.get("plan") or "").startswith("paid_")
                and user.get("payment_status") == "active"
            ),
        },
        "delivery": {
            "sent": sent,
            "failed": failed,
            "total": delivery_total,
            "success_rate": round((sent / delivery_total * 100), 1) if delivery_total else None,
        },
        "incidents": {
            "open_sos": len(pending_sos),
            "delivery_failures": len(delivery_failures),
            "total_open": len(pending_sos) + len(delivery_failures),
            "items": [
                {
                    "kind": "sos",
                    "incident_id": str(item.get("event_id") or ""),
                    "created_at": item.get("created_at"),
                    "owner_display_name": item.get("owner_display_name") or "會員",
                    "status": item.get("status") or "pending",
                    "primary_responder": _sos_public_snapshot(item).get("primary_responder"),
                    "assistants": _sos_public_snapshot(item).get("assistants"),
                    "escalation_round": int(item.get("escalation_round") or 0),
                    "sent_count": sum(
                        1 for row in (item.get("deliveries") or [])
                        if row.get("status") == "sent"
                    ),
                    "failed_count": sum(
                        1 for row in (item.get("deliveries") or [])
                        if row.get("status") == "failed"
                    ),
                    "timeline": _sos_public_snapshot(item).get("timeline"),
                }
                for item in pending_sos
                if item.get("event_id")
            ] + [
                {
                    "kind": "delivery",
                    "incident_id": item["incident_id"],
                    "created_at": item.get("created_at"),
                    "notification_kind": item.get("kind"),
                }
                for item in delivery_failures
            ],
        },
        "line_budget": line_budget,
        "integrations": {
            "line": {
                "configured": line_token,
                "messaging_ready": line_token and line_secret,
                "token_configured": line_token,
                "secret_configured": line_secret,
                "liff_configured": liff_id,
                "webhook_configured": bool(public_url and line_secret),
                "webhook_url": f"{public_url}/api/line/webhook" if public_url else "",
            },
            "ga4": {
                # Keep the legacy key as report-access status for existing clients.
                "configured": ga4_property and ga4_credentials,
                "tracking_configured": bool(re.fullmatch(r"G-[A-Z0-9]+", ga4_measurement_id)),
                "reporting_configured": ga4_property and ga4_credentials,
                "measurement_id": ga4_measurement_id,
                "property_configured": ga4_property,
                "credentials_configured": ga4_credentials,
            },
            "wordpress": {
                "configured": wordpress_site and wordpress_user and wordpress_password,
                "site_configured": wordpress_site,
                "username_configured": wordpress_user,
                "application_password_configured": wordpress_password,
            },
        },
        "seo": {
            "pages": seo_pages,
            "passed": sum(row["passed"] for row in seo_pages),
            "total": sum(row["total"] for row in seo_pages),
        },
    }


def admin_summary(data_file, config=None, now=None):
    state = load_state(data_file)
    status_now = now or current_app_time(config or {})
    token = ""
    if config is not None and hasattr(config, "get"):
        token = str(config.get("LINE_CHANNEL_ACCESS_TOKEN") or "").strip()
    if not token:
        token = str(os.environ.get("LINE_CHANNEL_ACCESS_TOKEN") or "").strip()

    # 後台載入時補齊「LINE 使用者」佔位名稱（最多打 40 次 LINE profile，避免逾時）
    hydrated = 0
    dirty = False
    for user in (state.get("users") or {}).values():
        if hydrated >= 40:
            break
        if not is_placeholder_display_name(user.get("display_name")):
            continue
        before = str(user.get("display_name") or "")
        ensure_user_display_name(user, token=token)
        if str(user.get("display_name") or "") != before:
            hydrated += 1
            dirty = True
    if dirty:
        save_state(data_file, state)

    users = []
    invite_edges = []
    for user in state.get("users", {}).values():
        status = build_status(user, state, now=status_now)
        latest_checkin = (status.get("checkin_records") or [])[-1:] or [{}]
        status["last_checkin_area"] = str(
            latest_checkin[0].get("area")
            or (user.get("location") or {}).get("city")
            or "未提供"
        ).strip()
        # 後台顯示名稱：絕不空白；仍是佔位時至少附短 ID 方便辨識
        name = str(status.get("display_name") or "").strip()
        if is_placeholder_display_name(name):
            short = str(status.get("line_user_id") or "")[-6:] or "?"
            status["display_name"] = f"未取得暱稱（…{short}）"
            status["display_name_missing"] = True
        else:
            status["display_name_missing"] = False
        users.append(status)
        inviter_id = status.get("line_user_id") or ""
        inviter_name = status.get("display_name") or ""
        for contact in status.get("contacts") or []:
            guardian_id = get_contact_line_id(contact)
            if not guardian_id:
                continue
            if guardian_id == inviter_id:
                continue
            invite_edges.append(
                {
                    "inviter_line_user_id": inviter_id,
                    "inviter_display_name": inviter_name,
                    "guardian_line_user_id": guardian_id,
                    "guardian_display_name": contact.get("name") or "",
                    "binding_status": contact.get("binding_status") or "",
                    "accepted_at": contact.get("accepted_at") or contact.get("updated_at") or "",
                }
            )
    users.sort(key=lambda item: (not item["is_overdue"], item.get("display_name") or ""))
    users_by_id = {
        str(user.get("line_user_id") or ""): user
        for user in users
        if user.get("line_user_id")
    }
    daily_push_rows = {}
    persisted_daily_pushes = state.get("daily_push_member_stats") or {}
    if isinstance(persisted_daily_pushes, dict):
        for key, item in persisted_daily_pushes.items():
            if isinstance(item, dict):
                daily_push_rows[str(key)] = dict(item)
    # Backfill recent legacy logs that predate the persistent daily counters.
    for log in state.get("notification_logs") or []:
        line_user_id = str(log.get("line_user_id") or "").strip()
        created_at = str(log.get("created_at") or "")
        date = created_at[:10]
        if not line_user_id or len(date) != 10:
            continue
        key = f"{date}|{line_user_id}"
        if key in daily_push_rows:
            continue
        matching = [
            row
            for row in (state.get("notification_logs") or [])
            if str(row.get("line_user_id") or "").strip() == line_user_id
            and str(row.get("created_at") or "")[:10] == date
        ]
        daily_push_rows[key] = {
            "date": date,
            "line_user_id": line_user_id,
            "sent_count": sum(1 for row in matching if row.get("status") == "sent"),
            "failed_count": sum(
                1 for row in matching if row.get("status") in {"failed", "error", "blocked"}
            ),
            "total_count": len(matching),
            "kinds": sorted({
                str(row.get("kind") or "other") for row in matching
            }),
            "last_push_at": max(
                (str(row.get("created_at") or "") for row in matching),
                default="",
            ),
            "latest_failure_detail": next(
                (
                    str(row.get("detail") or "")[:500]
                    for row in sorted(
                        matching,
                        key=lambda row: str(row.get("created_at") or ""),
                        reverse=True,
                    )
                    if row.get("status") in {"failed", "error", "blocked"}
                    and str(row.get("detail") or "").strip()
                ),
                "",
            ),
            "latest_failure_at": next(
                (
                    str(row.get("created_at") or "")
                    for row in sorted(
                        matching,
                        key=lambda row: str(row.get("created_at") or ""),
                        reverse=True,
                    )
                    if row.get("status") in {"failed", "error", "blocked"}
                ),
                "",
            ),
        }
    daily_push_member_stats = []
    for item in daily_push_rows.values():
        member = users_by_id.get(str(item.get("line_user_id") or ""), {})
        if not str(item.get("latest_failure_detail") or "").strip():
            matching_failures = [
                row
                for row in (state.get("notification_logs") or [])
                if str(row.get("line_user_id") or "").strip()
                == str(item.get("line_user_id") or "").strip()
                and str(row.get("created_at") or "")[:10]
                == str(item.get("date") or "")
                and row.get("status") in {"failed", "error", "blocked"}
            ]
            if matching_failures:
                latest_failure = max(
                    matching_failures,
                    key=lambda row: str(row.get("created_at") or ""),
                )
                item["latest_failure_detail"] = str(
                    latest_failure.get("detail") or ""
                )[:500]
                item["latest_failure_at"] = str(
                    latest_failure.get("created_at") or ""
                )
        daily_push_member_stats.append({
            **item,
            "display_name": member.get("display_name") or "未取得暱稱",
            "plan": member.get("plan") or "free",
            "expires_at": member.get("plan_expires_at") or "",
        })
    daily_push_member_stats.sort(
        key=lambda item: (item.get("date") or "", item.get("last_push_at") or ""),
        reverse=True,
    )
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
        latest = [
            row for row in (profile.get("checkin_records") or [])
            if isinstance(row, dict)
        ]
        county = str(
            (latest[-1].get("area") if latest else "")
            or (profile.get("location") or {}).get("city")
            or "未提供"
        ).strip()
        county_row(county)["members"] += 1

    for order in orders:
        profile = state.get("users", {}).get(order.get("line_user_id"), {})
        latest = [
            row for row in (profile.get("checkin_records") or [])
            if isinstance(row, dict)
        ]
        county = str(
            (latest[-1].get("area") if latest else "")
            or (profile.get("location") or {}).get("city")
            or "未提供"
        ).strip()
        row = county_row(county)
        row["orders"] += 1
        if order.get("status") == "paid":
            row["paid_orders"] += 1
            row["revenue"] += int(order.get("amount") or 0)

    county_stats = sorted(
        county_rows.values(),
        key=lambda item: (-item["revenue"], -item["members"], item["county"]),
    )
    persist = persistence_info(data_file)
    guardian_invites = []
    for row in reversed((state.get("guardian_invites") or [])[-100:]):
        if not isinstance(row, dict):
            continue
        guardian_invites.append({
            "id": row.get("id") or "",
            "inviter_line_user_id": row.get("inviter_line_user_id") or "",
            "display_name": row.get("display_name") or "",
            "relationship": row.get("relationship") or "",
            "status": row.get("status") or "",
            "created_at": row.get("created_at") or "",
            "expires_at": row.get("expires_at") or "",
            "accepted_at": row.get("accepted_at") or "",
            "invitee_line_user_id": row.get("invitee_line_user_id") or "",
        })
    quota = int((config or {}).get("LINE_MONTHLY_MESSAGE_QUOTA") or os.environ.get("LINE_MONTHLY_MESSAGE_QUOTA") or 200)
    line_usage = monthly_line_message_usage(
        state, status_now.strftime("%Y-%m"), quota, status_now
    )
    return {
        "total_users": len(users),
        "overdue_users": sum(1 for user in users if user["is_overdue"]),
        "warning_users": sum(1 for user in users if user["status_class"] == "warning"),
        "checked_today": sum(1 for user in users if user["is_today_checked"]),
        "guardian_group_count": len(guardian_groups),
        "guardian_groups": guardian_groups,
        "bound_guardian_total": sum(int(user.get("bound_guardian_count") or 0) for user in users),
        "invite_edges": list(reversed(invite_edges[-100:])),
        "guardian_invites": guardian_invites,
        "guardian_invite_counts": {
            status: sum(1 for row in guardian_invites if row.get("status") == status)
            for status in ("pending", "accepted", "expired")
        },
        "orders": orders,
        "paid_order_count": len(paid_orders),
        "paid_revenue": sum(int(order.get("amount") or 0) for order in paid_orders),
        "pending_order_count": sum(1 for order in orders if order.get("status") == "pending"),
        "county_stats": county_stats,
        "users": users,
        "contact_rewards": list(reversed(state.get("contact_rewards", [])[-20:])),
        "notification_logs": list(reversed(state.get("notification_logs", [])[-20:])),
        "daily_push_member_stats": daily_push_member_stats[:500],
        "line_message_usage": line_usage,
        "display_names_hydrated": hydrated,
        "persistence": persist,
    }


_MIGRATION_ADMIN_COUNT_KEYS = (
    "checkins",
    "contacts",
    "groups",
    "reminders",
    "orders",
    "requests",
)
_MIGRATION_ADMIN_FAILURE_CATEGORIES = {
    "",
    "invalid_code",
    "expired_code",
    "used_code",
    "source_missing",
    "unsafe_conflict",
    "migration_failed",
}


def admin_account_migrations(data_file, config, now=None):
    """Return a read-only, allowlisted operational migration summary."""
    state = load_state(data_file)
    current = _account_migration_now(now)
    audit = state.get("account_migration_audit") or []
    successes = sum(
        1
        for event in audit
        if isinstance(event, dict) and event.get("status") == "success"
    )
    failures = sum(
        1
        for event in audit
        if isinstance(event, dict) and event.get("status") == "failed"
    )
    pending = sum(
        1
        for ticket in (state.get("account_migration_tickets") or {}).values()
        if (
            isinstance(ticket, dict)
            and ticket.get("status") == "pending"
            and (
                _account_migration_datetime(ticket.get("expires_at"))
                and current
                < _account_migration_datetime(ticket.get("expires_at"))
            )
        )
    )
    latest_events = []
    for event in reversed(audit[-10:]):
        if not isinstance(event, dict):
            continue
        status = (
            event.get("status")
            if event.get("status") in {"success", "failed"}
            else "failed"
        )
        failure_category = str(event.get("failure_category") or "")
        if failure_category not in _MIGRATION_ADMIN_FAILURE_CATEGORIES:
            failure_category = "other"
        created_at = _account_migration_datetime(event.get("created_at"))
        raw_counts = (
            event.get("counts")
            if isinstance(event.get("counts"), dict)
            else {}
        )
        counts = {}
        for key in _MIGRATION_ADMIN_COUNT_KEYS:
            try:
                counts[key] = max(0, int(raw_counts.get(key) or 0))
            except (TypeError, ValueError):
                counts[key] = 0
        latest_events.append({
            "status": status,
            "created_at": (
                created_at.isoformat(timespec="seconds")
                if created_at
                else ""
            ),
            "failure_category": failure_category,
            "counts": counts,
        })
    return {
        "configured": account_migration_ready(config),
        "totals": {
            "total": successes + failures + pending,
            "success": successes,
            "failed": failures,
            "pending": pending,
        },
        "latest_events": latest_events,
    }


def backup_root(data_file):
    return Path(data_file).parent / "backups"


def _r2_backup_key(raw):
    try:
        key = base64.urlsafe_b64decode(str(raw).encode())
    except Exception:
        key = b""
    return key if len(key) == 32 else None


def _default_r2_uploader(bucket, object_key, body, content_type, metadata, config):
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=config.get("R2_ENDPOINT"),
        aws_access_key_id=config.get("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=config.get("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
    )
    return client.put_object(
        Bucket=bucket,
        Key=object_key,
        Body=body,
        ContentType=content_type,
        Metadata=metadata,
    )


def create_r2_encrypted_backup(config):
    bucket = str(config.get("R2_BUCKET") or "").strip()
    key = _r2_backup_key(config.get("R2_BACKUP_ENCRYPTION_KEY") or "")
    uploader = config.get("R2_UPLOADER") or _default_r2_uploader
    if not bucket or key is None or AES is None:
        return {"error": "r2_backup_not_configured"}, 503
    if uploader is _default_r2_uploader and not all(
        str(config.get(name) or "").strip()
        for name in ("R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")
    ):
        return {"error": "r2_backup_not_configured"}, 503
    state = load_state(config["DATA_FILE"])
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    backup_id = (
        f"r2-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-"
        f"{secrets.token_hex(3)}"
    )
    snapshot = {
        key_name: value
        for key_name, value in state.items()
        if key_name not in {"backup_exports", "r2_backup_exports"}
    }
    plaintext = json.dumps(
        {"backup_id": backup_id, "created_at": created_at, "snapshot": snapshot},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    cipher = AES.new(key, AES.MODE_GCM)
    ciphertext, tag = cipher.encrypt_and_digest(plaintext)
    envelope = json.dumps(
        {
            "version": 1,
            "algorithm": "AES-256-GCM",
            "nonce": base64.b64encode(cipher.nonce).decode(),
            "tag": base64.b64encode(tag).decode(),
            "ciphertext": base64.b64encode(ciphertext).decode(),
        },
        separators=(",", ":"),
    ).encode()
    object_key = f"alive-checkin/{created_at[:10]}/{backup_id}.json.aesgcm"
    metadata = {
        "encryption": "AES-256-GCM",
        "backup-id": backup_id,
        "sha256": hashlib.sha256(envelope).hexdigest(),
    }
    try:
        result = uploader(
            bucket,
            object_key,
            envelope,
            "application/octet-stream",
            metadata,
            config,
        )
    except Exception:
        return {"error": "r2_backup_upload_failed"}, 502
    etag = str((result or {}).get("etag") or (result or {}).get("ETag") or "")
    etag = etag.strip('"')
    backup = {
        "id": backup_id,
        "created_at": created_at,
        "bucket": bucket,
        "object_key": object_key,
        "etag": etag,
        "sha256": metadata["sha256"],
        "encryption": metadata["encryption"],
        "user_count": len(snapshot.get("users", {})),
    }
    state.setdefault("r2_backup_exports", []).append(backup)
    state["r2_backup_exports"] = state["r2_backup_exports"][-100:]
    save_state(config["DATA_FILE"], state)
    return {"backup": backup}, 201


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


def build_sos_group_mention_message(alert_text: str):
    """群組 SOS：用 textV2 + mentionee type=all（@全體），盡可能讓每位成員收到通知。"""
    body = str(alert_text or "").strip()
    return {
        "type": "textV2",
        "text": "{everyone}\n🚨【@全體 緊急SOS】\n" + body,
        "substitution": {
            "everyone": {
                "type": "mention",
                "mentionee": {"type": "all"},
            }
        },
    }


def build_sos_group_member_mentions_message(alert_text: str, member_user_ids=None):
    """@all 失敗時備援：mention 已知成員 userId（單則最多 20 人）。"""
    body = str(alert_text or "").strip()
    ids = []
    seen = set()
    for uid in member_user_ids or []:
        u = str(uid or "").strip()
        if not u or u in seen or not u.startswith("U"):
            continue
        seen.add(u)
        ids.append(u)
        if len(ids) >= 20:
            break
    if not ids:
        return "🚨【@全體 緊急SOS】\n" + body
    substitution = {}
    parts = []
    for i, uid in enumerate(ids):
        key = f"m{i}"
        parts.append("{" + key + "}")
        substitution[key] = {
            "type": "mention",
            "mentionee": {"type": "user", "userId": uid},
        }
    return {
        "type": "textV2",
        "text": " ".join(parts) + "\n🚨【@全體 緊急SOS】\n" + body,
        "substitution": substitution,
    }


def _send_line_with_retry_key(sender, token, target, message, retry_key):
    """Use LINE retry keys in production while keeping simple injected test senders."""
    if sender is line_push_message:
        return sender(token, target, message, retry_key=retry_key)
    return sender(token, target, message)


def push_sos_to_guardian_group(
    token, group_id, alert_text, *, sender=None, member_ids=None, retry_key=None
):
    """推送群組 SOS，優先 @all；失敗再 mention 已知成員；最後純文字加 @全體 前綴。"""
    push = sender or line_push_message
    gid = str(group_id or "").strip()
    if not gid:
        raise ValueError("missing group_id for SOS group push")
    primary = build_sos_group_mention_message(alert_text)
    try:
        result = _send_line_with_retry_key(
            push, token, gid, primary,
            _line_retry_key(f"{retry_key}:all") if retry_key else None,
        )
        return result, "all", primary
    except Exception as exc:
        if classify_push_exception(exc).kind != "message":
            raise
        fallback_ids = list(member_ids or [])
        if not fallback_ids:
            fallback_ids = get_group_member_ids(token, gid) or []
        secondary = build_sos_group_member_mentions_message(alert_text, fallback_ids)
        try:
            result = _send_line_with_retry_key(
                push, token, gid, secondary,
                _line_retry_key(f"{retry_key}:members") if retry_key else None,
            )
            mode = "members" if isinstance(secondary, dict) else "text"
            return result, mode, secondary
        except Exception as exc:
            if classify_push_exception(exc).kind != "message":
                raise
            plain = "🚨【@全體 緊急SOS】\n" + str(alert_text or "").strip()
            result = _send_line_with_retry_key(
                push, token, gid, plain,
                _line_retry_key(f"{retry_key}:text") if retry_key else None,
            )
            return result, "text", plain


def line_push_message(token, line_user_id, message, *, retry_key=None):
    """推訊息給單一 LINE 用戶。

    message 可以是:
    - str: 純文字訊息
    - dict 且帶 "type" key: 直接作為 LINE message object (例如 flex)
    """
    to_id = str(line_user_id or "").strip()
    if not to_id:
        raise ValueError("missing line_user_id for push")
    if isinstance(message, dict) and message.get("type"):
        msg_obj = message
    else:
        msg_obj = {"type": "text", "text": str(message)}
    body = json.dumps(
        {"to": to_id, "messages": [msg_obj]},
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "Authorization": f"Bearer {token}",
    }
    if retry_key:
        headers["X-Line-Retry-Key"] = str(retry_key)
    req = urllib.request.Request(
        "https://api.line.me/v2/bot/message/push",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return {"ok": 200 <= res.status < 300, "status": res.status}
    except urllib.error.HTTPError as exc:
        if exc.code == 409 and exc.headers.get("X-Line-Accepted-Request-Id"):
            return {
                "ok": True,
                "status": 409,
                "idempotent_replay": True,
                "accepted_request_id": exc.headers.get(
                    "X-Line-Accepted-Request-Id"
                ),
            }
        err_body = ""
        try:
            err_body = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            err_body = ""
        # Re-raise with LINE body so cron/backfill can surface the real cause.
        raise urllib.error.HTTPError(
            exc.url,
            exc.code,
            f"{exc.reason}: {err_body}" if err_body else exc.reason,
            exc.headers,
            None,
        ) from exc


def append_notification_log(state, kind, line_user_id, status, message, detail=None):
    logs = state.setdefault("notification_logs", [])
    if isinstance(message, dict):
        message_text = str(message.get("altText") or message.get("type") or message)[:120]
    else:
        message_text = str(message or "")[:120]
    created_at = datetime.now().isoformat(timespec="seconds")
    logs.append(
        {
            "created_at": created_at,
            "kind": kind,
            "line_user_id": line_user_id,
            "status": status,
            "message": message_text,
            "detail": detail or "",
        }
    )
    state["notification_logs"] = logs[-100:]
    member_id = str(line_user_id or "").strip()
    date = created_at[:10]
    if member_id:
        stats = state.setdefault("daily_push_member_stats", {})
        key = f"{date}|{member_id}"
        row = stats.setdefault(
            key,
            {
                "date": date,
                "line_user_id": member_id,
                "sent_count": 0,
                "failed_count": 0,
                "total_count": 0,
                "kinds": [],
                "last_push_at": created_at,
            },
        )
        row["total_count"] = int(row.get("total_count") or 0) + 1
        if status == "sent":
            row["sent_count"] = int(row.get("sent_count") or 0) + 1
        elif status in {"failed", "error", "blocked"}:
            row["failed_count"] = int(row.get("failed_count") or 0) + 1
            row["latest_failure_detail"] = str(detail or "")[:500]
            row["latest_failure_at"] = created_at
        row["kinds"] = sorted(set(row.get("kinds") or []) | {str(kind or "other")})
        row["last_push_at"] = created_at
        # Keep roughly one year of daily/member aggregates without growing forever.
        if len(stats) > 20000:
            for old_key in sorted(stats)[: len(stats) - 20000]:
                stats.pop(old_key, None)


LINE_MESSAGE_USAGE_CATEGORIES = {
    "binding",
    "checkin",
    "overdue",
    "sos",
    "sos_cancel",
    "sos_escalation",
    "smart_reminder",
    "guardian_summary",
}


def record_line_message_usage(
    state: dict,
    *,
    category: str,
    owner_line_user_id: str,
    recipient_count: int,
    event_id: str,
    sent_at: datetime,
) -> dict:
    """Idempotently record delivered LINE recipient units."""
    category = str(category or "").strip()
    if category not in LINE_MESSAGE_USAGE_CATEGORIES:
        raise ValueError("invalid LINE message usage category")
    units = max(0, int(recipient_count or 0))
    if units <= 0:
        return {"recorded": False, "units": 0}
    owner = str(owner_line_user_id or "").strip()
    event_id = str(event_id or "").strip()
    if not owner or not event_id:
        raise ValueError("owner_line_user_id and event_id are required")
    ledger = state.setdefault("line_message_usage", [])
    key = f"{category}:{event_id}"
    existing = next((row for row in ledger if row.get("key") == key), None)
    if existing:
        return {**existing, "recorded": False, "idempotent": True}
    row = {
        "key": key,
        "category": category,
        "owner_line_user_id": owner,
        "recipient_count": units,
        "units": units,
        "event_id": event_id,
        "sent_at": sent_at.isoformat(timespec="seconds"),
    }
    ledger.append(row)
    state["line_message_usage"] = ledger[-10000:]
    return {**row, "recorded": True, "idempotent": False}


def line_push_budget_decision(
    state: dict,
    *,
    owner_line_user_id: str,
    requested_units: int,
    now: datetime,
    monthly_hard_cap: int,
    member_daily_hard_cap: int,
    emergency: bool = False,
) -> dict:
    """Apply pre-send hard caps while retaining one primary SOS delivery."""
    owner = str(owner_line_user_id or "").strip()
    requested = max(0, int(requested_units or 0))
    monthly_cap = max(0, int(monthly_hard_cap or 0))
    daily_cap = max(0, int(member_daily_hard_cap or 0))
    month_prefix = now.strftime("%Y-%m-")
    day_prefix = now.strftime("%Y-%m-%d")
    rows = state.get("line_message_usage") or []
    monthly_used = sum(
        max(0, int(row.get("units") or row.get("recipient_count") or 0))
        for row in rows
        if str(row.get("sent_at") or "").startswith(month_prefix)
    )
    member_daily_used = sum(
        max(0, int(row.get("units") or row.get("recipient_count") or 0))
        for row in rows
        if str(row.get("owner_line_user_id") or "") == owner
        and str(row.get("sent_at") or "").startswith(day_prefix)
    )
    monthly_remaining = max(0, monthly_cap - monthly_used)
    daily_remaining = max(0, daily_cap - member_daily_used)
    allowed_units = min(requested, monthly_remaining, daily_remaining)
    reason = None
    if allowed_units < requested:
        reason = (
            "monthly_hard_cap"
            if monthly_remaining <= daily_remaining
            else "member_daily_hard_cap"
        )
    if emergency and requested > 0 and allowed_units < 1:
        allowed_units = 1
        reason = "emergency_primary_only"
    return {
        "allowed": allowed_units > 0 or requested == 0,
        "reason": reason,
        "requested_units": requested,
        "allowed_units": allowed_units,
        "monthly_used": monthly_used,
        "monthly_hard_cap": monthly_cap,
        "member_daily_used": member_daily_used,
        "member_daily_hard_cap": daily_cap,
    }


def monthly_line_message_usage(state: dict, year_month: str, quota: int, now: datetime) -> dict:
    """Aggregate delivered recipient units for the requested calendar month."""
    category_totals = {key: 0 for key in sorted(LINE_MESSAGE_USAGE_CATEGORIES)}
    member_map = {}
    rows = []
    for row in state.get("line_message_usage") or []:
        if not str(row.get("sent_at") or "").startswith(f"{year_month}-"):
            continue
        units = max(0, int(row.get("units") or row.get("recipient_count") or 0))
        if units <= 0:
            continue
        rows.append(row)
        category = str(row.get("category") or "")
        if category in category_totals:
            category_totals[category] += units
        owner = str(row.get("owner_line_user_id") or "")
        member_map[owner] = member_map.get(owner, 0) + units
    used = sum(category_totals.values())
    try:
        month_days = calendar.monthrange(now.year, now.month)[1]
    except Exception:
        month_days = 30
    elapsed_days = max(1, now.day)
    projected = int(math.ceil(used * month_days / elapsed_days))
    quota = max(0, int(quota or 0))
    ratio = (used / quota) if quota else 0
    alert = "critical_90" if quota and ratio >= 0.9 else (
        "warning_70" if quota and ratio >= 0.7 else "normal"
    )
    members = [
        {"line_user_id": uid[:6] + "..." + uid[-4:] if len(uid) > 10 else uid, "units": units}
        for uid, units in sorted(member_map.items(), key=lambda item: (-item[1], item[0]))
    ]
    return {
        "year_month": year_month,
        "quota": quota,
        "used_units": used,
        "remaining_units": max(0, quota - used) if quota else None,
        "usage_percent": round(ratio * 100, 1) if quota else None,
        "projected_units": projected,
        "alert_level": alert,
        "category_totals": category_totals,
        "member_totals": members,
        "false_alarm_units": category_totals["sos_cancel"],
        "records": len(rows),
    }


def _clear_push_delivery_failure(recipient, delivery_key):
    attempts = dict(recipient.get("push_delivery_attempts") or {})
    attempts.pop(delivery_key, None)
    if attempts:
        recipient["push_delivery_attempts"] = attempts
    else:
        recipient.pop("push_delivery_attempts", None)


def _record_launch_delivery(state, delivery_key, kind, target, status):
    ledger = state.setdefault("launch_delivery_events", {})
    ledger_key = f"{kind}:{target}:{delivery_key}"
    event = ledger.setdefault(ledger_key, {
        "kind": str(kind),
        "target": str(target),
        "expected": True,
        "sent_count": 0,
        "failed": False,
    })
    if status == "sent":
        event["sent_count"] = int(event.get("sent_count") or 0) + 1
    elif status == "failed":
        event["failed"] = True
    event["updated_at"] = datetime.now().isoformat(timespec="seconds")
    return event


def _record_scheduled_push_failure(
    state,
    recipient,
    delivery_key,
    kind,
    line_user_id,
    message,
    exc,
    now,
):
    failure = record_push_failure(recipient, delivery_key, exc, now)
    _record_launch_delivery(
        state, delivery_key, kind, line_user_id, "failed"
    )
    append_notification_log(
        state,
        kind,
        line_user_id,
        failure["status"],
        message,
        str(exc),
    )
    return failure


def log_notification(data_file, kind, line_user_id, status, message, detail=None):
    state = load_state(data_file)
    append_notification_log(state, kind, line_user_id, status, message, detail)
    save_state(data_file, state)


def send_due_reminders(config):
    token = config.get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        return {"sent": 0, "skipped": 0, "error": "LINE_CHANNEL_ACCESS_TOKEN is not set"}, 400

    now = current_app_time(config)
    sender = config.get("LINE_PUSH_SENDER") or line_push_message
    state = load_state(config["DATA_FILE"])
    sent = 0
    skipped = 0
    results = []
    system_error = False
    for profile in (state.get("users") or {}).values():
        owner_id = str(profile.get("line_user_id") or "").strip()
        event = profile.get("active_overdue_event")
        if not owner_id or not isinstance(event, dict) or event.get("resolved_at"):
            skipped += 1
            continue
        if profile.get("membership_paused") or not membership_access_active(profile, now):
            skipped += 1
            continue
        if profile_is_today_checked(profile, config=config, now=now):
            event["resolved_at"] = now.isoformat(timespec="seconds")
            event["status"] = "checked_in"
            profile["last_overdue_event"] = copy.deepcopy(event)
            profile["active_overdue_event"] = None
            skipped += 1
            continue
        started_at = parse_datetime(event.get("started_at"))
        if not started_at:
            skipped += 1
            continue
        if now.tzinfo is None and started_at.tzinfo is not None:
            started_at = started_at.replace(tzinfo=None)
        elif now.tzinfo is not None and started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=now.tzinfo)
        elapsed_minutes = max(0, (now - started_at).total_seconds() / 60)
        grace_minutes = normalize_grace_hours(
            profile.get("grace_hours")
        ) * 60
        elapsed_after_grace = max(0, elapsed_minutes - grace_minutes)
        wait_minutes = normalize_overdue_wait_minutes(
            profile.get("overdue_wait_minutes")
        )
        location = profile.get("location") or {}
        location_link = ""
        if profile.get("attach_location_on_alert") and location.get("latitude") and location.get("longitude"):
            location_link = f"\n最後位置：https://www.google.com/maps?q={location['latitude']},{location['longitude']}"

        # 本人於提醒後最多再收到一次短提醒；不因多個每日時段建立重複事件。
        if elapsed_minutes >= grace_minutes and not event.get("self_followup_sent_at"):
            self_message = (
                f"❤️ 還沒收到你的平安回報\n"
                f"請點一下「我平安」；若提醒後 {wait_minutes} 分鐘仍未回應，"
                "系統會通知第一順位守護人。"
            )
            self_key = f"{event.get('event_id')}:self-followup"
            try:
                result = sender(token, owner_id, self_message)
                event["self_followup_sent_at"] = now.isoformat(timespec="seconds")
                append_notification_log(
                    state, "overdue_self_followup", owner_id, "sent",
                    self_message, json.dumps(result, ensure_ascii=False),
                )
                record_line_message_usage(
                    state,
                    category="overdue",
                    owner_line_user_id=owner_id,
                    recipient_count=1,
                    event_id=self_key,
                    sent_at=now,
                )
                sent += 1
                results.append({"line_user_id": owner_id, "stage": "self_followup", "result": result})
            except Exception as exc:
                append_notification_log(
                    state, "overdue_self_followup", owner_id, "failed",
                    self_message, str(exc),
                )
                skipped += 1
                results.append({"line_user_id": owner_id, "stage": "self_followup", "error": str(exc)})

        # 799 守護群仍是選用通道；在第一順位到期時通知一次，不取代私人順位通知。
        if elapsed_after_grace >= wait_minutes:
            rules = plan_rules(profile, now)
            group_limit = int(rules.get("guardian_group_limit") or 0)
            groups = state.get("guardian_groups") or {}
            notified_group_ids = event.setdefault("notified_group_ids", [])
            active_group_ids = [
                group_id
                for group_id in (profile.get("guardian_group_ids") or [])
                if group_id not in notified_group_ids
                and groups.get(group_id, {}).get("owner_line_user_id") == owner_id
                and groups.get(group_id, {}).get("status") == "active"
                and guardian_group_preference(
                    groups.get(group_id), "notify_group_on_overdue"
                )
            ][:group_limit]
            group_message = (
                f"⚠️【失聯預警】{profile.get('display_name') or '成員'} 在提醒後 "
                f"{wait_minutes} 分鐘仍未回報平安，請群內協助確認。{location_link}"
            )
            for group_id in active_group_ids:
                delivery_key = f"{event.get('event_id')}:group:{group_id}"
                try:
                    result = sender(token, group_id, group_message)
                    notified_group_ids.append(group_id)
                    append_notification_log(
                        state, "overdue_guardian_group", group_id, "sent",
                        group_message, json.dumps(result, ensure_ascii=False),
                    )
                    record_line_message_usage(
                        state,
                        category="overdue",
                        owner_line_user_id=owner_id,
                        recipient_count=1,
                        event_id=delivery_key,
                        sent_at=now,
                    )
                    sent += 1
                    results.append({
                        "group_id": group_id,
                        "stage": "guardian_group",
                        "result": result,
                    })
                except Exception as exc:
                    append_notification_log(
                        state, "overdue_guardian_group", group_id, "failed",
                        group_message, str(exc),
                    )
                    skipped += 1
                    results.append({
                        "group_id": group_id,
                        "stage": "guardian_group",
                        "error": str(exc),
                    })

        current_stage = int(event.get("guardian_stage") or 0)
        due_stage = next(
            (
                stage
                for stage in (1, 2, 3)
                if stage > current_stage
                and elapsed_after_grace >= wait_minutes * stage
            ),
            None,
        )
        if due_stage is None:
            continue
        if not should_notify_private_guardians(state, profile):
            event["guardian_stage"] = due_stage
            skipped += 1
            continue
        guardians = ranked_overdue_guardians(profile)
        if due_stage > len(guardians):
            event["guardian_stage"] = due_stage
            skipped += 1
            continue
        contact = guardians[due_stage - 1]
        target = get_contact_line_id(contact)
        contact_name = str(contact.get("name") or contact.get("relationship") or f"第 {due_stage} 順位守護人")
        contact_message = (
            f"⚠️【第 {due_stage} 順位未報平安通知】"
            f"{profile.get('display_name') or '你的親友'} 在提醒後 "
            f"{wait_minutes * due_stage} 分鐘仍未回報平安，請協助確認。"
            f"{location_link}"
        )
        delivery_key = f"{event.get('event_id')}:guardian:{due_stage}:{target}"
        try:
            result = sender(token, target, contact_message)
            event["guardian_stage"] = due_stage
            event.setdefault("notified_guardian_ids", []).append(target)
            append_notification_log(
                state, "contact_alert", target, "sent",
                contact_message, json.dumps(result, ensure_ascii=False),
            )
            record_line_message_usage(
                state,
                category="overdue",
                owner_line_user_id=owner_id,
                recipient_count=1,
                event_id=delivery_key,
                sent_at=now,
            )
            sent += 1
            results.append({
                "line_user_id": target,
                "display_name": contact_name,
                "stage": due_stage,
                "result": result,
            })
        except Exception as exc:
            append_notification_log(
                state, "contact_alert", target, "failed",
                contact_message, str(exc),
            )
            skipped += 1
            results.append({
                "line_user_id": target,
                "display_name": contact_name,
                "stage": due_stage,
                "error": str(exc),
            })

    save_state(config["DATA_FILE"], state)
    return {
        "sent": sent,
        "skipped": skipped,
        "results": results,
        "system_error": system_error,
    }, 200


def send_guardian_group_daily_summaries(config):
    """選用：守護群勾選「群組每日摘要」時，於晚間推播今日已報／未報（預設關閉）。"""
    token = config.get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        return {"sent": 0, "skipped": 0, "error": "LINE_CHANNEL_ACCESS_TOKEN is not set"}, 400

    state = load_state(config["DATA_FILE"])
    sender = config.get("LINE_PUSH_SENDER") or line_push_message
    now = current_app_time(config)
    today = now.strftime("%Y-%m-%d")
    users = state.get("users") or {}
    groups = state.get("guardian_groups") or {}
    sent = 0
    skipped = 0
    results = []
    system_error = False
    deferred = 0
    member_fetcher = config.get("GROUP_MEMBER_IDS_FETCHER") or get_group_member_ids
    for group_id, group in list(groups.items()):
        if not isinstance(group, dict) or group.get("status") != "active":
            skipped += 1
            continue
        owner = users.get(str(group.get("owner_line_user_id") or "").strip()) or {}
        if (
            not guardian_group_entitlement_active(owner, now)
        ):
            skipped += 1
            results.append({"group_id": group_id, "status": "owner_not_eligible"})
            continue
        prefs = normalize_guardian_group_preferences(group.get("preferences"))
        if not prefs.get("daily_admin_summary"):
            skipped += 1
            continue
        summary_time = str(prefs.get("daily_summary_time") or "21:00")
        current_hm = now.strftime("%H:%M")
        if current_hm < summary_time:
            deferred += 1
            continue
        if group.get("last_daily_summary_date") == today:
            skipped += 1
            continue
        delivery_key = f"guardian_group_daily_summary:{today}:{group_id}"
        if not push_attempt_allowed(group, delivery_key):
            skipped += 1
            continue
        claim_result = mutate_state_atomically(
            config["DATA_FILE"],
            lambda current_state: _claim_guardian_group_summary(
                current_state, group_id, today, now
            ),
        )
        if not claim_result.get("claimed"):
            skipped += 1
            results.append({"group_id": group_id, "status": "already_claimed"})
            continue
        claim_token = claim_result["claim_token"]
        try:
            current_ids = None
            member_error = None
            for _attempt in range(3):
                try:
                    current_ids = member_fetcher(token, group_id)
                    if current_ids is not None:
                        member_error = None
                        break
                    member_error = RuntimeError("LINE member list unavailable")
                except Exception as exc:
                    member_error = exc
            if current_ids is None:
                mutate_state_atomically(
                    config["DATA_FILE"],
                    lambda current_state: _finish_guardian_group_summary(
                        current_state,
                        group_id,
                        today,
                        now,
                        claim_token=claim_token,
                        release_only=True,
                        audit_kind="guardian_group_member_refresh",
                        audit_status="failed",
                        audit_detail=str(member_error or "member refresh failed")[:400],
                    ),
                )
                skipped += 1
                results.append({
                    "group_id": group_id,
                    "status": "member_refresh_failed",
                    "error": str(member_error or "")[:400],
                })
                continue
        except Exception:
            mutate_state_atomically(
                config["DATA_FILE"],
                lambda current_state: _finish_guardian_group_summary(
                    current_state,
                    group_id,
                    today,
                    now,
                    claim_token=claim_token,
                    release_only=True,
                ),
            )
            raise
        member_ids = list(dict.fromkeys(
            str(uid or "").strip() for uid in current_ids if str(uid or "").strip()
        ))
        prepared = mutate_state_atomically(
            config["DATA_FILE"],
            lambda current_state: _prepare_guardian_group_summary(
                current_state,
                group_id,
                today,
                now,
                claim_token,
                member_ids,
            ),
        )
        eligible_members = prepared.get("eligible_members") or []
        if not prepared.get("ready"):
            skipped += 1
            results.append({
                "group_id": group_id,
                "status": prepared.get("reason") or "no_longer_eligible",
            })
            continue
        if not eligible_members:
            mutate_state_atomically(
                config["DATA_FILE"],
                lambda current_state: _finish_guardian_group_summary(
                    current_state,
                    group_id,
                    today,
                    now,
                    claim_token=claim_token,
                    release_only=True,
                    member_ids=member_ids,
                ),
            )
            skipped += 1
            results.append({"group_id": group_id, "status": "no_eligible_members"})
            continue
        checked = []
        unchecked = []
        for member in eligible_members:
            profile = member["profile"]
            name = member["name"]
            (checked if _member_checked_today(profile, today) else unchecked).append(name)
        message = (
            f"📊 今日平安摘要（{today}）\n"
            f"已報平安：{', '.join(checked) if checked else '尚無'}\n"
            f"尚未報平安：{', '.join(unchecked) if unchecked else '目前都已完成'}\n\n"
            "（此為選用群組摘要；關閉後只會私訊核心守護人。）"
        )
        try:
            if sender is line_push_message:
                result = sender(
                    token,
                    group_id,
                    message,
                    retry_key=_line_retry_key(delivery_key),
                )
            else:
                result = sender(token, group_id, message)
            mutate_state_atomically(
                config["DATA_FILE"],
                lambda current_state: _finish_guardian_group_summary(
                    current_state,
                    group_id,
                    today,
                    now,
                    claim_token=claim_token,
                    sent=True,
                    message=message,
                    result=result,
                    member_ids=member_ids,
                ),
            )
            sent += 1
            results.append({"group_id": group_id, "result": result})
        except Exception as exc:
            failure = mutate_state_atomically(
                config["DATA_FILE"],
                lambda current_state: _finish_guardian_group_summary(
                    current_state,
                    group_id,
                    today,
                    now,
                    claim_token=claim_token,
                    message=message,
                    error=exc,
                    member_ids=member_ids,
                ),
            )
            skipped += 1
            results.append({"group_id": group_id, "error": str(exc)})
            if failure["kind"] == "system":
                system_error = True
                break

    return {
        "sent": sent,
        "skipped": skipped,
        "deferred": deferred,
        "results": results,
        "date": today,
        "system_error": system_error,
    }, 200


def _line_retry_key(delivery_key):
    """Stable UUID accepted by LINE for idempotent retries of one logical push."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"daily-peace:{delivery_key}"))


def _claim_guardian_group_summary(state, group_id, today, now):
    group = (state.get("guardian_groups") or {}).get(group_id)
    if not isinstance(group, dict):
        return {"claimed": False, "reason": "group_not_found"}
    owner = (state.get("users") or {}).get(
        str(group.get("owner_line_user_id") or "").strip()
    ) or {}
    prefs = normalize_guardian_group_preferences(group.get("preferences"))
    if (
        group.get("status") != "active"
        or not prefs.get("daily_admin_summary")
        or not guardian_group_entitlement_active(owner, now)
    ):
        return {"claimed": False, "reason": "no_longer_eligible"}
    if group.get("last_daily_summary_date") == today:
        return {"claimed": False}
    claims = dict(group.get("daily_summary_claims") or {})
    existing = claims.get(today) or {}
    if existing:
        claimed_at = None
        try:
            claimed_at = datetime.fromisoformat(str(existing.get("claimed_at") or ""))
        except (TypeError, ValueError):
            claimed_at = None
        if claimed_at is not None and (now - claimed_at).total_seconds() < 900:
            return {"claimed": False, "reason": "active_claim"}
    claim_token = secrets.token_hex(16)
    claims[today] = {
        "claimed_at": now.isoformat(timespec="seconds"),
        "claim_token": claim_token,
    }
    group["daily_summary_claims"] = claims
    return {
        "claimed": True,
        "recovered": bool(existing),
        "claim_token": claim_token,
    }


def _prepare_guardian_group_summary(
    state, group_id, today, now, claim_token, member_ids
):
    group = (state.get("guardian_groups") or {}).get(group_id)
    claim = ((group or {}).get("daily_summary_claims") or {}).get(today) or {}
    if not isinstance(group, dict) or claim.get("claim_token") != claim_token:
        return {"ready": False, "reason": "claim_lost"}
    owner = (state.get("users") or {}).get(
        str(group.get("owner_line_user_id") or "").strip()
    ) or {}
    prefs = normalize_guardian_group_preferences(group.get("preferences"))
    if (
        group.get("status") != "active"
        or not prefs.get("daily_admin_summary")
        or not guardian_group_entitlement_active(owner, now)
    ):
        _finish_guardian_group_summary(
            state,
            group_id,
            today,
            now,
            claim_token=claim_token,
            release_only=True,
        )
        return {"ready": False, "reason": "no_longer_eligible"}
    group["member_ids_last_summary"] = list(member_ids)
    group["member_ids_last_summary_at"] = now.isoformat(timespec="seconds")
    return {
        "ready": True,
        "eligible_members": eligible_guardian_group_summary_members(
            state, group, member_ids
        ),
    }


def _finish_guardian_group_summary(
    state,
    group_id,
    today,
    now,
    *,
    claim_token,
    sent=False,
    release_only=False,
    message="",
    result=None,
    error=None,
    member_ids=None,
    audit_kind=None,
    audit_status=None,
    audit_detail=None,
):
    group = (state.get("guardian_groups") or {}).get(group_id)
    if not isinstance(group, dict):
        return {"kind": "permanent", "retry": False}
    claims = dict(group.get("daily_summary_claims") or {})
    claim = claims.get(today) or {}
    if claim.get("claim_token") != claim_token:
        return {"kind": "claim_lost", "retry": False}
    claims.pop(today, None)
    if claims:
        group["daily_summary_claims"] = claims
    else:
        group.pop("daily_summary_claims", None)
    if member_ids is not None:
        group["member_ids_last_summary"] = list(member_ids)
        group["member_ids_last_summary_at"] = now.isoformat(timespec="seconds")
    if audit_kind:
        append_notification_log(
            state,
            audit_kind,
            group_id,
            audit_status or "failed",
            "",
            audit_detail,
        )
    if release_only:
        return {"released": True}
    delivery_key = f"guardian_group_daily_summary:{today}:{group_id}"
    if sent:
        _clear_push_delivery_failure(group, delivery_key)
        append_notification_log(
            state,
            "guardian_group_daily_summary",
            group_id,
            "sent",
            message,
            json.dumps(result, ensure_ascii=False),
        )
        record_line_message_usage(
            state,
            category="guardian_summary",
            owner_line_user_id=group.get("owner_line_user_id") or group_id,
            recipient_count=max(1, len(member_ids or [])),
            event_id=delivery_key,
            sent_at=now,
        )
        group["last_daily_summary_date"] = today
        return {"sent": True}
    return _record_scheduled_push_failure(
        state,
        group,
        delivery_key,
        "guardian_group_daily_summary",
        group_id,
        message,
        error,
        now,
    )


def send_missing_contact_reminders(config):
    token = config.get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        return {"sent": 0, "skipped": 0, "error": "LINE_CHANNEL_ACCESS_TOKEN is not set"}, 400

    state = load_state(config["DATA_FILE"])
    sender = config.get("LINE_PUSH_SENDER") or line_push_message
    public_url = (config.get("APP_PUBLIC_URL") or os.environ.get("APP_PUBLIC_URL", "")).rstrip("/")
    now = current_app_time(config)
    if not line_non_emergency_push_allowed(state, config, now):
        return line_budget_blocked_response(state, config, now)
    today = now.strftime("%Y-%m-%d")
    sent = 0
    skipped = 0
    results = []
    system_error = False
    for user in state.get("users", {}).values():
        line_user_id = user.get("line_user_id")
        if not line_user_id:
            skipped += 1
            continue
        if user.get("membership_paused") or not membership_access_active(user, now):
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
            delivery_key = f"guardian_details:{today}"
            if not push_attempt_allowed(user, delivery_key):
                skipped += 1
                continue
            link_text = (
                f"\n前往我的守護資料：{liff_entry_url(open_action='member') if liff_entry_url else 'https://liff.line.me/2010848330-UAiqPPYD?open=member'}"
            )
            message = (
                "你的 799 守護方案還少一份必要資料。請在『我的守護資料』完成至少 1 位守護人的姓名、關係與電話，"
                f"緊急時系統才能正確聯絡對方。這則提醒只會傳送一次。{link_text}"
            )
            try:
                result = sender(token, line_user_id, message)
                _clear_push_delivery_failure(user, delivery_key)
                user["guardian_details_reminder_sent_at"] = now.isoformat(timespec="seconds")
                append_notification_log(state, "guardian_details", line_user_id, "sent", message, json.dumps(result, ensure_ascii=False))
                sent += 1
                results.append({"line_user_id": line_user_id, "result": result})
            except Exception as exc:
                failure = _record_scheduled_push_failure(
                    state,
                    user,
                    delivery_key,
                    "guardian_details",
                    line_user_id,
                    message,
                    exc,
                    now,
                )
                skipped += 1
                results.append({"line_user_id": line_user_id, "error": str(exc)})
                if failure["kind"] == "system":
                    system_error = True
                    break
            continue
        if contact_count >= contact_limit or (contact_count > 0 and not reminder_enabled):
            continue
        sent_dates = set(user.get("contact_reminder_sent_dates") or [])
        if today in sent_dates:
            continue
        link_text = (
            f"\n一鍵邀請守護人：{share_invite_liff_url() if share_invite_liff_url else 'https://liff.line.me/2010848330-UAiqPPYD/liff/share-invite.html'}"
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
        delivery_key = f"missing_contact:{today}"
        if not push_attempt_allowed(user, delivery_key):
            skipped += 1
            continue
        try:
            result = sender(token, line_user_id, message)
            _clear_push_delivery_failure(user, delivery_key)
            sent_dates.add(today)
            user["contact_reminder_sent_dates"] = sorted(sent_dates)[-30:]
            append_notification_log(state, "missing_contact", line_user_id, "sent", message, json.dumps(result, ensure_ascii=False))
            sent += 1
            results.append({"line_user_id": line_user_id, "result": result})
        except Exception as exc:
            failure = _record_scheduled_push_failure(
                state,
                user,
                delivery_key,
                "missing_contact",
                line_user_id,
                message,
                exc,
                now,
            )
            skipped += 1
            results.append({"line_user_id": line_user_id, "error": str(exc)})
            if failure["kind"] == "system":
                system_error = True
                break
    save_state(config["DATA_FILE"], state)
    return {
        "sent": sent,
        "skipped": skipped,
        "results": results,
        "system_error": system_error,
    }, 200


def cleanup_expired_data(config):
    data_file = config["DATA_FILE"]
    now = current_app_time(config)
    invite_cutoff = now - timedelta(days=7)
    notification_cutoff = now - timedelta(days=90)
    migration_cleanup_now = now
    if migration_cleanup_now.tzinfo is None:
        timezone_name = (
            config.get("APP_TIMEZONE")
            or os.environ.get("APP_TIMEZONE")
            or "Asia/Taipei"
        )
        try:
            app_timezone = ZoneInfo(str(timezone_name))
        except Exception:
            app_timezone = timezone.utc
        migration_cleanup_now = migration_cleanup_now.replace(
            tzinfo=app_timezone
        ).astimezone(timezone.utc)

    def at_or_after(value, cutoff):
        parsed = parse_datetime(value)
        if parsed is None:
            return True
        comparable_parsed, comparable_cutoff = _comparable_datetimes(
            parsed, cutoff
        )
        return comparable_parsed >= comparable_cutoff

    def mutate(state):
        downgraded = _apply_expired_plan_downgrades_to_state(state, now)
        migration_history_removed = purge_account_migration_history(
            state,
            now=migration_cleanup_now,
        )
        expired_locations_removed = 0
        contacts_archived = 0
        contacts_restored = 0
        migration_snapshots_removed = purge_account_migration_snapshots(
            state,
            now=migration_cleanup_now,
        )

        for profile in state.get("users", {}).values():
            if restore_legacy_auto_archived_contacts(profile):
                contacts_restored += 1
            if soft_archive_contacts_past_retain(profile, now):
                contacts_archived += 1
            location = profile.get("location") or {}
            if not location:
                continue
            if location.get("until_stop") and (
                location.get("sharing") or location.get("active")
            ):
                continue
            expires_at = parse_datetime(location.get("expires_at"))
            location_expired = False
            if expires_at:
                comparable_expires, comparable_now = _comparable_datetimes(
                    expires_at, now
                )
                location_expired = comparable_expires < comparable_now
            if location_expired:
                profile["location"] = {
                    **location,
                    "sharing": False,
                    "active": False,
                    "ended_at": (
                        location.get("ended_at")
                        or now.isoformat(timespec="seconds")
                    ),
                }
                expired_locations_removed += 1

        invites_before = len(state.get("friend_invites", {}))
        state["friend_invites"] = {
            code: invite
            for code, invite in state.get("friend_invites", {}).items()
            if at_or_after(invite.get("created_at"), invite_cutoff)
        }

        logs_before = len(state.get("notification_logs", []))
        state["notification_logs"] = [
            log
            for log in state.get("notification_logs", [])
            if at_or_after(log.get("created_at"), notification_cutoff)
        ][-100:]
        return {
            "cleaned_at": now.isoformat(timespec="seconds"),
            "expired_locations_removed": expired_locations_removed,
            "expired_invites_removed": (
                invites_before - len(state["friend_invites"])
            ),
            "old_notification_logs_removed": (
                logs_before - len(state["notification_logs"])
            ),
            "contacts_archived_users": contacts_archived,
            "contacts_restored_users": contacts_restored,
            "migration_snapshots_removed": migration_snapshots_removed,
            "migration_tickets_removed": migration_history_removed["tickets"],
            "migration_audit_removed": migration_history_removed["audit"],
            "orders_removed": 0,
            "plans_downgraded": len(downgraded),
        }, 200

    return mutate_state_atomically(data_file, mutate)


def reminder_time_in_window(reminder_time, now, late_minutes=4):
    try:
        hour, minute = [int(part) for part in str(reminder_time or "12:00").split(":", 1)]
    except (TypeError, ValueError):
        hour, minute = 12, 0
    scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    delta = now - scheduled
    return timedelta(0) <= delta <= timedelta(minutes=int(late_minutes), seconds=59)


def build_daily_checkin_flex(now, target_time=""):
    """Daily check-in Flex: greeting + optional holiday blessing + quote + postback.

    Keeps classic green (#00B900) header; 「我平安」 uses postback action=checkin.
    """
    today = now.strftime("%Y-%m-%d")
    weekday_zh = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"][now.weekday()]
    time_bit = f" {target_time}" if target_time else ""
    copy = (
        holidays_tw.daily_push_copy(now)
        if holidays_tw is not None
        else {
            "greeting": "❤️ 今天一切都好嗎？",
            "holiday_name": "",
            "holiday_blessing": "",
            "positive_quote": "每一天的平安，都是給家人最好的禮物。",
            "instruction": "點「我平安」立刻完成報到（不用再開網頁）",
        }
    )
    guard_uri = (
        liff_entry_url(open_action="guard")
        if liff_entry_url
        else "https://liff.line.me/2010848330-UAiqPPYD?open=guard"
    )
    sos_uri = (
        liff_entry_url(open_action="sos")
        if liff_entry_url
        else "https://liff.line.me/2010848330-UAiqPPYD?open=sos"
    )
    body_contents = [
        {
            "type": "text",
            "text": copy["greeting"],
            "size": "xl",
            "weight": "bold",
            "color": "#1a1a1a",
            "wrap": True,
        },
    ]
    holiday_name = str(copy.get("holiday_name") or "").strip()
    holiday_blessing = str(copy.get("holiday_blessing") or "").strip()
    if holiday_name and holiday_blessing:
        body_contents.append(
            {
                "type": "text",
                "text": f"🎉 {holiday_name}",
                "size": "md",
                "weight": "bold",
                "color": "#B45309",
                "wrap": True,
            }
        )
        body_contents.append(
            {
                "type": "text",
                "text": holiday_blessing,
                "size": "md",
                "color": "#92400E",
                "wrap": True,
            }
        )
    body_contents.append(
        {
            "type": "text",
            "text": f"✨ {copy['positive_quote']}",
            "size": "md",
            "color": "#166534",
            "wrap": True,
        }
    )
    body_contents.append(
        {
            "type": "text",
            "text": copy["instruction"],
            "size": "lg",
            "color": "#555555",
            "wrap": True,
        }
    )
    alt_parts = [copy["greeting"], today]
    if holiday_name:
        alt_parts.append(holiday_name)
    if target_time:
        alt_parts.append(target_time)
    return {
        "type": "flex",
        "altText": " ".join(alt_parts)[:400],
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
                    {
                        "type": "text",
                        "text": "每日平安",
                        "color": "#FFFFFF",
                        "size": "lg",
                        "weight": "bold",
                        "wrap": True,
                    },
                    {
                        "type": "text",
                        "text": f"📅 {today} {weekday_zh}{time_bit}".strip(),
                        "color": "#FFFFFF",
                        "size": "xl",
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
                "contents": body_contents,
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "paddingAll": "lg",
                "backgroundColor": "#FAFAFA",
                "contents": [
                    {
                        "type": "button",
                        "action": {
                            "type": "postback",
                            "label": "✅ 我平安",
                            "data": "action=checkin",
                            "displayText": "我平安",
                        },
                        "style": "primary",
                        "color": "#16A34A",
                        "height": "md",
                    },
                    {
                        "type": "button",
                        "action": {"type": "uri", "label": "🛡️ 安全守護", "uri": guard_uri},
                        "style": "primary",
                        "color": "#2563EB",
                        "height": "md",
                    },
                    {
                        "type": "button",
                        "action": {"type": "uri", "label": "需要幫忙", "uri": sos_uri},
                        "style": "primary",
                        "color": "#DC2626",
                        "height": "md",
                    },
                ],
            },
        },
    }


def _mark_line_push_blocked(user, exc):
    """Mark blocked / gone users so future broadcasts skip them."""
    code = None
    if isinstance(exc, urllib.error.HTTPError):
        code = exc.code
    text = str(exc or "").lower()
    if code in {401, 403, 404} or "not a friend" in text or "blocked" in text:
        user["line_push_blocked"] = True
        user["line_push_blocked_at"] = datetime.now().isoformat(timespec="seconds")
        return True
    return False


def _mark_checkin_reminder_slots(user, today, times, due_times):
    sent_slots = dict(user.get("checkin_reminder_sent_slots") or {})
    sent_today = set(sent_slots.get(today) or [])
    sent_today.update(due_times or times or [])
    sent_slots[today] = sorted(sent_today)
    keep_dates = sorted(sent_slots.keys())[-30:]
    user["checkin_reminder_sent_slots"] = {d: sent_slots[d] for d in keep_dates}
    legacy_dates = set(user.get("checkin_reminder_sent_dates") or [])
    if set(times or []).issubset(sent_today):
        legacy_dates.add(today)
        user["checkin_reminder_sent_dates"] = sorted(legacy_dates)[-30:]


def send_checkin_reminders(config):
    """Morning/slot cron: skip users already checked in (Taipei). Prefer pre-check-in remind."""
    token = config.get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        return {"sent": 0, "skipped": 0, "error": "LINE_CHANNEL_ACCESS_TOKEN is not set"}, 400

    data_file = config["DATA_FILE"]
    state = load_state(data_file)
    sender = config.get("LINE_PUSH_SENDER") or line_push_message
    now = current_app_time(config)
    if not line_non_emergency_push_allowed(state, config, now):
        return line_budget_blocked_response(state, config, now)
    today = now.strftime("%Y-%m-%d")
    sent = 0
    skipped = 0
    results = []
    system_error = False

    for user in state.get("users", {}).values():
        line_user_id = user.get("line_user_id")
        if not line_user_id:
            skipped += 1
            continue
        if user.get("line_push_blocked"):
            skipped += 1
            continue
        if user.get("membership_paused") or not membership_access_active(user, now):
            skipped += 1
            continue
        if not bool(user.get("daily_checkin_reminder_enabled", True)):
            skipped += 1
            continue
        if profile_is_today_checked(user, config=config, now=now):
            # Heal missing Taipei history so later cron/status stay consistent
            hist = set(user.get("history") or [])
            if today not in hist:
                hist.add(today)
                user["history"] = sorted(hist)
            # 今日已報平安 → 略過同日剩餘排程提醒（標記 slots，避免後續誤推）
            times = reminder_times_for_profile(user) or ["12:00"]
            _mark_checkin_reminder_slots(user, today, times, times)
            skipped += 1
            continue

        times = reminder_times_for_profile(user)
        sent_slots = dict(user.get("checkin_reminder_sent_slots") or {})
        sent_today = set(sent_slots.get(today) or [])

        # 相容舊版:當天已用單一日期標記送過 → 視為本輪已提醒
        legacy_dates = set(user.get("checkin_reminder_sent_dates") or [])
        if today in legacy_dates and not sent_today:
            continue

        due_unsent = [
            t
            for t in times
            if reminder_time_in_window(t, now, late_minutes=4) and t not in sent_today
        ]
        if not due_unsent:
            continue

        # 同一五分鐘時間窗只推一次；較早漏掉的時段不補送也不標記。
        target_time = due_unsent[-1]
        delivery_key = f"checkin:{today}:{target_time}"
        _record_launch_delivery(
            state, delivery_key, "checkin", line_user_id, "expected"
        )
        if not push_attempt_allowed(user, delivery_key):
            skipped += 1
            continue
        message = build_daily_checkin_flex(now, target_time=target_time)
        try:
            result = sender(token, line_user_id, message)
            _clear_push_delivery_failure(user, delivery_key)
            _record_launch_delivery(
                state, delivery_key, "checkin", line_user_id, "sent"
            )
            _mark_checkin_reminder_slots(user, today, times, due_unsent)
            ensure_active_overdue_event(user, target_time, now)
            append_notification_log(state, "checkin", line_user_id, "sent", message, json.dumps(result, ensure_ascii=False))
            record_line_message_usage(
                state,
                category="checkin",
                owner_line_user_id=line_user_id,
                recipient_count=1,
                event_id=delivery_key,
                sent_at=now,
            )
            sent += 1
            results.append({"line_user_id": line_user_id, "reminder_time": target_time, "result": result})
            # 方案即將／已到期：同日最多附帶一次提醒（不洗版）
            if should_offer_expiry_remind(user, now):
                expiry_msg = build_expiry_remind_flex(user, now)
                expiry_key = f"expiry_remind:{today}"
                if not push_attempt_allowed(user, expiry_key):
                    continue
                try:
                    expiry_result = sender(token, line_user_id, expiry_msg)
                    _clear_push_delivery_failure(user, expiry_key)
                    mark_expiry_remind_sent(user, now)
                    append_notification_log(
                        state,
                        "expiry_remind",
                        line_user_id,
                        "sent",
                        expiry_msg,
                        json.dumps(expiry_result, ensure_ascii=False),
                    )
                except Exception as expiry_exc:
                    failure = _record_scheduled_push_failure(
                        state,
                        user,
                        expiry_key,
                        "expiry_remind",
                        line_user_id,
                        expiry_msg,
                        expiry_exc,
                        now,
                    )
                    if failure["kind"] == "system":
                        system_error = True
                        break
        except Exception as exc:
            failure = _record_scheduled_push_failure(
                state,
                user,
                delivery_key,
                "checkin",
                line_user_id,
                message,
                exc,
                now,
            )
            skipped += 1
            results.append({"line_user_id": line_user_id, "error": str(exc)})
            if failure["kind"] == "system":
                system_error = True
                break

    save_state(data_file, state)
    return {
        "sent": sent,
        "skipped": skipped,
        "results": results,
        "system_error": system_error,
    }, 200


def broadcast_checkin_reminders(config, *, pause_every=20, pause_seconds=1.0):
    """重新推播：送新模板給所有已註冊會員（有 line_user_id），含今日已簽到者。

    - 跳過 line_push_blocked
    - 分批暫停以降低 LINE rate-limit 風險
    - 標記今日 reminder slots，避免 cron 稍後再洗版
    """
    import time as _time

    token = config.get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        return {"sent": 0, "skipped": 0, "error": "LINE_CHANNEL_ACCESS_TOKEN is not set"}, 400

    data_file = config["DATA_FILE"]
    state = load_state(data_file)
    sender = config.get("LINE_PUSH_SENDER") or line_push_message
    now = current_app_time(config)
    if not line_non_emergency_push_allowed(state, config, now):
        return line_budget_blocked_response(state, config, now)
    today = now.strftime("%Y-%m-%d")
    message = build_daily_checkin_flex(now, target_time="")
    sent = 0
    skipped = 0
    blocked = 0
    results = []
    push_count = 0

    for user in state.get("users", {}).values():
        line_user_id = str(user.get("line_user_id") or "").strip()
        if not line_user_id:
            skipped += 1
            continue
        if user.get("line_push_blocked"):
            blocked += 1
            skipped += 1
            continue
        times = reminder_times_for_profile(user)
        try:
            result = sender(token, line_user_id, message)
            _mark_checkin_reminder_slots(user, today, times, times)
            user["checkin_broadcast_sent_dates"] = sorted(
                set(user.get("checkin_broadcast_sent_dates") or []) | {today}
            )[-30:]
            append_notification_log(
                state, "checkin_broadcast", line_user_id, "sent", message, json.dumps(result, ensure_ascii=False)
            )
            sent += 1
            push_count += 1
            results.append({"line_user_id": line_user_id, "result": result})
            if pause_every and push_count % int(pause_every) == 0:
                _time.sleep(float(pause_seconds))
        except Exception as exc:
            if _mark_line_push_blocked(user, exc):
                blocked += 1
                append_notification_log(state, "checkin_broadcast", line_user_id, "blocked", message, str(exc))
            else:
                append_notification_log(state, "checkin_broadcast", line_user_id, "failed", message, str(exc))
            skipped += 1
            results.append({"line_user_id": line_user_id, "error": str(exc)})

    save_state(data_file, state)
    holiday = holidays_tw.holiday_for(now) if holidays_tw is not None else None
    return {
        "sent": sent,
        "skipped": skipped,
        "blocked": blocked,
        "mode": "broadcast",
        "holiday": (holiday or {}).get("name") if holiday else None,
        "positive_quote": holidays_tw.positive_quote_for(now) if holidays_tw is not None else None,
        "results": results,
    }, 200


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

    blocked = 0
    system_error = False
    for user in state.get("users", {}).values():
        line_user_id = user.get("line_user_id")
        if not line_user_id:
            skipped += 1
            continue
        if not plan_has_smart_reminders(user, now=now):
            skipped += 1
            continue
        if user.get("membership_paused") or not membership_access_active(user, now):
            skipped += 1
            continue
        if user.get("line_push_blocked"):
            blocked += 1
            skipped += 1
            continue
        notes = user.get("calendar_notes") or {}
        if not isinstance(notes, dict):
            continue
        sent_keys = set(user.get("birthday_reminder_sent_keys") or [])
        for note_date, note in notes.items():
            for birthday_index, birthday in enumerate(calendar_note_birthdays(note)):
                try:
                    remind_days = int(birthday.get("birthday_remind_days") or 1)
                except (TypeError, ValueError):
                    remind_days = 1
                target_date = today_date + timedelta(days=remind_days)
                if not birthday_occurs_on(birthday, target_date):
                    continue
                birthday_suffix = f":{birthday_index}" if birthday_index else ""
                sent_key = (
                    f"{today_key}:{note_date}:{remind_days}{birthday_suffix}"
                )
                if sent_key in sent_keys:
                    continue
                delivery_key = f"birthday:{sent_key}"
                if not push_attempt_allowed(user, delivery_key):
                    skipped += 1
                    continue
                who = birthday.get("birthday_relationship") or birthday.get("birthday_name") or "家人"
                when_text = "今天" if remind_days == 0 else ("明天" if remind_days == 1 else f"{remind_days} 天後")
                message = f"{when_text}是{who}生日，記得跟他說聲生日快樂。也可以順手確認他今天平安。"
                try:
                    result = sender(token, line_user_id, message)
                    _clear_push_delivery_failure(user, delivery_key)
                    sent_keys.add(sent_key)
                    user["birthday_reminder_sent_keys"] = sorted(sent_keys)[-80:]
                    append_notification_log(state, "birthday", line_user_id, "sent", message, json.dumps(result, ensure_ascii=False))
                    sent += 1
                    results.append({"line_user_id": line_user_id, "birthday": who, "remind_days": remind_days})
                except Exception as exc:
                    failure = _record_scheduled_push_failure(
                        state,
                        user,
                        delivery_key,
                        "birthday",
                        line_user_id,
                        message,
                        exc,
                        now,
                    )
                    if failure["status"] == "blocked":
                        blocked += 1
                    skipped += 1
                    results.append({"line_user_id": line_user_id, "birthday": who, "error": str(exc)})
                    if failure["kind"] == "system":
                        system_error = True
                        break
            if system_error:
                break
        if system_error:
            break

    save_state(data_file, state)
    return {
        "sent": sent,
        "skipped": skipped,
        "blocked": blocked,
        "results": results,
        "system_error": system_error,
    }, 200


# === 799 智能提醒（生活提醒：只走 LINE 私訊，預設不進守護群）===
SMART_REMINDER_CATEGORIES = {
    "birthday": {"emoji": "🎂", "label": "生日"},
    "wedding": {"emoji": "💍", "label": "結婚紀念日"},
    "dating": {"emoji": "💕", "label": "交往紀念日"},
    "child_birthday": {"emoji": "👶", "label": "小孩生日"},
    "elder_birthday": {"emoji": "👴", "label": "長輩生日"},
    "graduation": {"emoji": "🎓", "label": "畢業"},
    "moving": {"emoji": "🏠", "label": "搬家"},
    "special": {"emoji": "🎉", "label": "特殊紀念日"},
    "checkup": {"emoji": "💊", "label": "回診"},
    "medicine": {"emoji": "💊", "label": "吃藥"},
    "schedule": {"emoji": "📅", "label": "行程"},
    "greeting": {"emoji": "❤️", "label": "問候"},
    "custom": {"emoji": "🗓️", "label": "自訂"},
}


def plan_has_smart_reminders(profile, now=None):
    profile = profile or {}
    plan = effective_entitlement_plan(profile, now=now)
    return plan in {"paid_799", "paid_799_year"} and membership_access_active(
        profile, now=now
    )


def normalize_smart_reminder(raw, index=0):
    raw = raw if isinstance(raw, dict) else {}
    category = str(raw.get("category") or "custom").strip().lower()
    if category not in SMART_REMINDER_CATEGORIES:
        category = "custom"
    meta = SMART_REMINDER_CATEGORIES[category]
    emoji = str(raw.get("emoji") or meta["emoji"]).strip() or meta["emoji"]
    try:
        month = int(raw.get("month") or 0)
        day = int(raw.get("day") or 0)
    except (TypeError, ValueError):
        month, day = 0, 0
    year_raw = raw.get("year")
    try:
        year = int(year_raw) if year_raw not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        year = None
    # date_iso（YYYY-MM-DD）優先於拆開的年月日
    date_iso = str(raw.get("date") or raw.get("date_iso") or "").strip()
    if date_iso and re.match(r"^\d{4}-\d{2}-\d{2}$", date_iso):
        try:
            y, m, d = date_iso.split("-")
            year = int(y)
            month = int(m)
            day = int(d)
        except (TypeError, ValueError):
            pass
    if bool(raw.get("yearly", False)) or bool(raw.get("repeat_yearly", False)):
        year = None
    remind_time = str(raw.get("remind_time") or raw.get("time") or "09:00").strip()
    if not REMINDER_TIME_PATTERN.match(remind_time):
        remind_time = "09:00"
    custom_title = str(raw.get("custom_title") or "").strip()[:80]
    category_label = meta["label"]
    if category == "custom" and custom_title:
        category_label = custom_title
    rid = str(raw.get("id") or "").strip() or f"sr_{secrets.token_hex(6)}"
    notify_private = True  # product: 智能提醒只走私訊
    notify_group = False
    delivery_target = str(raw.get("delivery_target") or "private").strip()
    if not (delivery_target == "private" or delivery_target.startswith("guardian:")):
        delivery_target = str(raw.get("delivery_target") or "private").strip()
    return {
        "id": rid,
        "target_name": str(raw.get("target_name") or "").strip() or f"對象{index + 1}",
        "category": category,
        "category_label": category_label,
        "custom_title": custom_title,
        "emoji": emoji,
        "month": month if 1 <= month <= 12 else 1,
        "day": day if 1 <= day <= 31 else 1,
        "year": year,
        "remind_time": remind_time,
        "note": str(raw.get("note") or "").strip()[:200],
        "notify_private": notify_private,
        "notify_group": notify_group,
        "delivery_target": delivery_target,
        "eve_remind": bool(raw.get("eve_remind", True)),
        "enabled": bool(raw.get("enabled", True)),
        "created_at": str(raw.get("created_at") or datetime.now().isoformat(timespec="seconds")),
        "updated_at": str(raw.get("updated_at") or ""),
    }


def list_smart_reminders(profile):
    rows = profile.get("smart_reminders") if isinstance(profile.get("smart_reminders"), list) else []
    return [normalize_smart_reminder(row, i) for i, row in enumerate(rows)]


def smart_reminder_occurs_on(reminder, target_date):
    try:
        month = int(reminder.get("month") or 0)
        day = int(reminder.get("day") or 0)
    except (TypeError, ValueError):
        return False
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return False
    year = reminder.get("year")
    if year:
        try:
            return target_date.year == int(year) and target_date.month == month and target_date.day == day
        except (TypeError, ValueError):
            return False
    # yearly recurrence; skip invalid dates like 2/30
    try:
        datetime(target_date.year, month, day)
    except ValueError:
        return False
    return target_date.month == month and target_date.day == day


def smart_reminder_canned_wish(reminder):
    name = reminder.get("target_name") or "對方"
    cat = reminder.get("category") or "custom"
    label = reminder.get("category_label") or SMART_REMINDER_CATEGORIES.get(cat, {}).get("label", "日子")
    templates = {
        "birthday": f"🎂 {name}，生日快樂！願你今天被溫柔包圍，平安健康每一天 ❤️",
        "wedding": f"💍 親愛的{name}，結婚紀念日快樂！感謝一路上的陪伴與包容 ❤️",
        "dating": f"💕 {name}，交往紀念日快樂！謝謝你讓平凡日子變得特別。",
        "child_birthday": f"👶 親愛的小孩生日快樂！長大的每一步，我們都為你開心。",
        "elder_birthday": f"👴 {name}生日快樂！願您身體硬朗、每天笑口常開。",
        "graduation": f"🎓 恭喜{name}畢業！新的旅程開始了，我們為你驕傲。",
        "moving": f"🏠 新家落成／喬遷愉快！願{name}在新環境一切順利。",
        "special": f"🎉 今天是特別的日子，祝{name}開心、平安。",
        "checkup": f"💊 提醒：記得陪／關心{name}回診，帶健保卡與就醫資料。",
        "medicine": f"💊 提醒：該吃藥／拿藥了，幫{name}確認一次。",
        "schedule": f"📅 行程提醒：今天與{name}有關的安排，別忘了預留時間。",
        "greeting": f"❤️ 傳一句問候給{name}：「今天還好嗎？我想你了。」",
        "custom": f"🗓️ 提醒：今天是你為{name}設定的「{label}」，記得處理一下。",
    }
    return templates.get(cat, templates["custom"])


def smart_reminder_canned_gift(reminder):
    name = reminder.get("target_name") or "對方"
    cat = reminder.get("category") or "custom"
    if cat in {"birthday", "child_birthday", "elder_birthday"}:
        return f"🎁 禮物建議：1) 手寫小卡＋喜歡的甜點 2) 實用日常好物 3) 一起吃頓飯。對象：{name}"
    if cat in {"wedding", "dating"}:
        return f"🎁 禮物建議：一起回憶照片書、共同喜歡的小旅行，或一頓安靜晚餐。對象：{name}"
    if cat in {"checkup", "medicine"}:
        return f"🎁 實用協助：陪診、整理藥單、準備水杯與交通安排。對象：{name}"
    return f"🎁 建議：一句真心話＋小驚喜（花／甜點／陪伴時間）。對象：{name}"


def build_smart_reminder_flex(reminder, *, mode="day"):
    """mode=day|eve Flex for private LINE push."""
    name = reminder.get("target_name") or "對方"
    emoji = reminder.get("emoji") or "🗓️"
    label = reminder.get("category_label") or "提醒"
    month = int(reminder.get("month") or 1)
    day = int(reminder.get("day") or 1)
    date_text = f"{month}/{day}"
    rid = reminder.get("id") or ""
    if mode == "eve":
        title = f"❤️ 明天是{name}{label}"
        body = "需要幫你準備一句祝福嗎？"
        buttons = [
            {"type": "button", "action": {"type": "postback", "label": "✨每日產生祝福", "data": f"smart:wish:{rid}", "displayText": "幫我產生祝福"}, "style": "primary", "color": "#7C3AED", "height": "sm"},
            {"type": "button", "action": {"type": "postback", "label": "🎁禮物建議", "data": f"smart:gift:{rid}", "displayText": "禮物建議"}, "style": "secondary", "height": "sm"},
            {"type": "button", "action": {"type": "postback", "label": "📞明天提醒", "data": f"smart:snooze:{rid}", "displayText": "明天再提醒我"}, "style": "secondary", "height": "sm"},
        ]
        alt = f"明天是{name}的{label}"
    else:
        if (reminder.get("category") or "") == "birthday":
            title = f"🎂 今天是{name}的生日"
            body = f"別忘了送上一句祝福 ❤️\n姓名：{name}\n今天：{date_text}"
            buttons = [
                {"type": "button", "action": {"type": "postback", "label": "🎁傳送祝福", "data": f"smart:wish:{rid}", "displayText": "傳送祝福"}, "style": "primary", "color": "#E11D48", "height": "sm"},
                {"type": "button", "action": {"type": "postback", "label": "🎂已祝福", "data": f"smart:blessed:{rid}", "displayText": "已祝福"}, "style": "secondary", "height": "sm"},
                {"type": "button", "action": {"type": "postback", "label": "⏰晚點提醒我", "data": f"smart:snooze:{rid}", "displayText": "晚點提醒我"}, "style": "secondary", "height": "sm"},
            ]
        elif "父" in name or label in {"特殊紀念日"} and "父" in (reminder.get("note") or ""):
            title = f"🎉 今天是父親節"
            body = f"你設定的提醒對象：👨{name}\n記得向他說聲：父親節快樂 ❤️"
            buttons = [
                {"type": "button", "action": {"type": "postback", "label": "💌LINE祝福", "data": f"smart:wish:{rid}", "displayText": "LINE祝福"}, "style": "primary", "color": "#2563EB", "height": "sm"},
                {"type": "button", "action": {"type": "postback", "label": "📞打電話", "data": f"smart:call:{rid}", "displayText": "提醒我打電話"}, "style": "secondary", "height": "sm"},
                {"type": "button", "action": {"type": "postback", "label": "⏰晚點提醒", "data": f"smart:snooze:{rid}", "displayText": "晚點提醒"}, "style": "secondary", "height": "sm"},
            ]
        else:
            title = f"{emoji} 今天是{name}的{label}"
            body = f"別忘了關心一下 ❤️\n對象：{name}\n今天：{date_text}"
            if reminder.get("note"):
                body += f"\n備註：{reminder.get('note')}"
            buttons = [
                {"type": "button", "action": {"type": "postback", "label": "💌傳送祝福", "data": f"smart:wish:{rid}", "displayText": "傳送祝福"}, "style": "primary", "color": "#E11D48", "height": "sm"},
                {"type": "button", "action": {"type": "postback", "label": "✅已完成", "data": f"smart:blessed:{rid}", "displayText": "已完成"}, "style": "secondary", "height": "sm"},
                {"type": "button", "action": {"type": "postback", "label": "⏰晚點提醒我", "data": f"smart:snooze:{rid}", "displayText": "晚點提醒我"}, "style": "secondary", "height": "sm"},
            ]
        alt = f"今天是{name}的{label}"
    return {
        "type": "flex",
        "altText": alt,
        "contents": {
            "type": "bubble",
            "size": "mega",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    {"type": "text", "text": title, "weight": "bold", "size": "xl", "wrap": True},
                    {"type": "text", "text": body, "size": "md", "color": "#444444", "wrap": True},
                    {"type": "text", "text": "💬 此提醒只傳到你的 LINE 私訊（不會進守護群）", "size": "xs", "color": "#888888", "wrap": True},
                ],
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": buttons,
            },
        },
    }


def build_smart_reminder_digest(reminders, *, mode="day"):
    reminders = list(reminders or [])
    if len(reminders) == 1:
        return build_smart_reminder_flex(reminders[0], mode=mode)
    when = "明天" if mode == "eve" else "今天"
    lines = [
        f"{item.get('emoji') or '🗓️'} {item.get('target_name') or '對象'}："
        f"{item.get('category_label') or '提醒'}"
        for item in reminders
    ]
    return {
        "type": "flex",
        "altText": f"{when}有 {len(reminders)} 個提醒",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    {"type": "text", "text": f"🗓️ {when}有 {len(reminders)} 個提醒", "weight": "bold", "size": "xl", "wrap": True},
                    {"type": "text", "text": "\n".join(lines), "size": "md", "wrap": True},
                    {"type": "text", "text": "同一時段已合併成一則，避免重複打擾", "size": "xs", "color": "#888888", "wrap": True},
                ],
            },
        },
    }


def is_checkin_postback(data):
    """Daily push / Flex 「我平安」 postback."""
    text = str(data or "").strip()
    if not text:
        return False
    if text in {"action=checkin", "checkin", "checkin:ok", "checkin=1"}:
        return True
    if text.startswith("action=checkin"):
        return True
    if text.startswith("checkin:"):
        return True
    try:
        from alerts.postback import parse_postback_data
        return parse_postback_data(text).get("action") == "checkin"
    except Exception:
        return "action=checkin" in text


def handle_checkin_postback(data_file, line_user_id, config=None):
    """Persist check-in from LINE postback — same path as LIFF /api/checkin.

    Returns text, or a list of [text, optional expiry Flex] when membership is near expiry.
    """
    if not line_user_id:
        return "請先加入每日平安好友後再報平安。"
    status = record_checkin(data_file, {"line_user_id": line_user_id}, config=config)
    now = current_app_time(config)
    text = build_checkin_success_text(status, now=now, config=config)
    state = load_state(data_file)
    profile = get_profile(state, line_user_id)
    messages = maybe_attach_expiry_remind(
        [text], profile, now=now, state=state, data_file=data_file
    )
    if len(messages) == 1:
        return messages[0]
    return messages


def is_expiry_opt_out_postback(data):
    text = str(data or "").strip()
    return text == "action=expiry_opt_out" or "action=expiry_opt_out" in text


def handle_smart_reminder_postback(data_file, line_user_id, data, config=None):
    """Handle smart:* postbacks; returns reply text."""
    parts = str(data or "").split(":")
    if len(parts) < 3 or parts[0] != "smart":
        return None
    action, rid = parts[1], parts[2]
    state = load_state(data_file)
    profile = get_profile(state, line_user_id)
    reminder = next((r for r in list_smart_reminders(profile) if r.get("id") == rid), None)
    if not reminder:
        return "找不到這筆智能提醒，可能已被刪除。"
    if action == "wish":
        return smart_reminder_canned_wish(reminder)
    if action == "gift":
        return smart_reminder_canned_gift(reminder)
    if action == "call":
        return f"📞 現在就可以撥電話給「{reminder.get('target_name')}」。打完後可回「已完成」。"
    if action == "blessed":
        return f"太好了，已幫你記下「已祝福／已完成」：{reminder.get('target_name')}。"
    if action == "snooze":
        # Mark a soft snooze key so day cron can re-nudge later same day once
        keys = set(profile.get("smart_reminder_sent_keys") or [])
        today = today_string(config)
        # Remove day key to allow one re-send after 2h via separate snooze marker
        profile["smart_reminder_snooze"] = {
            "id": rid,
            "until": (current_app_time(config) + timedelta(hours=2)).isoformat(timespec="seconds"),
        }
        # Keep day key so we don't double-fire immediately; snooze path uses until
        keys = {k for k in keys if not k.endswith(f":{rid}:day")}
        profile["smart_reminder_sent_keys"] = sorted(keys)[-120:]
        save_state(data_file, state)
        return "好，約 2 小時後再私訊提醒你一次。"
    return "已收到。"


def get_smart_reminders_payload(data_file, line_user_id):
    state = load_state(data_file)
    profile = get_profile(state, line_user_id)
    entitled = plan_has_smart_reminders(profile)
    recovering = str(profile.get("account_migration_status") or "").lower() in {
        "pending", "recovering", "in_progress"
    }
    today = datetime.now().strftime("%Y-%m-%d")
    usage = (profile.get("smart_reminder_daily_usage") or {}).get(today) or {}
    bound_guardians = []
    for contact in profile.get("contacts") or []:
        if not contact_is_bound_guardian(contact, line_user_id):
            continue
        guardian_id = get_contact_line_id(contact)
        if not guardian_id:
            continue
        bound_guardians.append({
            "line_user_id": guardian_id,
            "name": contact.get("name") or contact.get("display_name") or "核心守護人",
            "is_primary": bool(contact.get("is_primary")),
        })
    return {
        "ok": True,
        "entitled": entitled,
        "state": "entitled" if entitled else ("recovering" if recovering else "upgrade_required"),
        "plan": profile.get("plan") or "trial",
        "upgrade_hint": None if entitled else (
            "帳號資料正在恢復，完成後會自動取回既有智慧提醒"
            if recovering else
            "智能提醒為 799 守護版功能，升級後可設定生日／紀念日／回診等生活提醒（不進守護群）。"
        ),
        "reminders": list_smart_reminders(profile) if entitled else [],
        "defaults": profile.get("smart_reminder_defaults") or {"notify_private": True, "notify_group": False},
        "bound_guardians": bound_guardians if entitled else [],
        "daily_usage": {
            "private": int(usage.get("private") or 0),
            "guardian": int(usage.get("guardian") or 0),
        },
        "daily_limits": {"private": 2, "guardian": 1},
        "categories": [
            {"id": key, "emoji": meta["emoji"], "label": meta["label"]}
            for key, meta in SMART_REMINDER_CATEGORIES.items()
        ],
    }


def save_smart_reminder(data_file, payload):
    line_user_id = str(payload.get("line_user_id") or "").strip()
    if not line_user_id:
        return {"ok": False, "error": "missing line_user_id"}, 400
    state = load_state(data_file)
    profile = get_profile(state, line_user_id)
    if not plan_has_smart_reminders(profile):
        return {"ok": False, "error": "smart_reminders_require_799", "upgrade_hint": "請升級 799 守護版"}, 403
    delivery_target = str(payload.get("delivery_target") or "private").strip()
    if delivery_target.startswith("group:"):
        return {"ok": False, "error": "guardian_group_target_not_allowed"}, 400
    if delivery_target != "private":
        if not delivery_target.startswith("guardian:"):
            return {"ok": False, "error": "invalid_delivery_target"}, 400
        target_id = delivery_target.split(":", 1)[1]
        allowed = {
            get_contact_line_id(contact)
            for contact in profile.get("contacts") or []
            if contact_is_bound_guardian(contact, line_user_id)
        }
        if target_id not in allowed:
            return {"ok": False, "error": "guardian_target_not_bound"}, 400
    reminder = normalize_smart_reminder(payload, 0)
    reminder["updated_at"] = current_app_time({}).isoformat(timespec="seconds")
    rows = list_smart_reminders(profile)
    replaced = False
    for i, row in enumerate(rows):
        if row.get("id") == reminder["id"]:
            reminder["created_at"] = row.get("created_at") or reminder["created_at"]
            rows[i] = reminder
            replaced = True
            break
    if not replaced:
        if len(rows) >= 40:
            return {"ok": False, "error": "smart_reminder_limit"}, 400
        rows.append(reminder)
    profile["smart_reminders"] = rows
    # 產品決策：智能提醒永遠只私訊，群組旗標固定關閉
    profile["smart_reminder_defaults"] = {"notify_private": True, "notify_group": False}
    save_state(data_file, state)
    return {"ok": True, "reminder": reminder, "reminders": rows}, 200


def delete_smart_reminder(data_file, line_user_id, reminder_id):
    line_user_id = str(line_user_id or "").strip()
    reminder_id = str(reminder_id or "").strip()
    if not line_user_id or not reminder_id:
        return {"ok": False, "error": "missing id"}, 400
    state = load_state(data_file)
    profile = get_profile(state, line_user_id)
    if not plan_has_smart_reminders(profile):
        return {"ok": False, "error": "smart_reminders_require_799"}, 403
    rows = [r for r in list_smart_reminders(profile) if r.get("id") != reminder_id]
    profile["smart_reminders"] = rows
    save_state(data_file, state)
    return {"ok": True, "reminders": rows}, 200


def send_smart_reminders(config):
    """Push merged, capped smart reminders to self or one bound core guardian."""
    token = config.get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        return {"sent": 0, "skipped": 0, "error": "LINE_CHANNEL_ACCESS_TOKEN is not set"}, 400

    data_file = config["DATA_FILE"]
    state = load_state(data_file)
    sender = config.get("LINE_PUSH_SENDER") or line_push_message
    now = current_app_time(config)
    today_date = now.date()
    tomorrow = today_date + timedelta(days=1)
    today_key = today_date.strftime("%Y-%m-%d")
    sent = 0
    skipped = 0
    results = []
    now_hm = now.strftime("%H:%M")
    eve_window = now.hour >= 20
    system_error = False

    for user in state.get("users", {}).values():
        line_user_id = user.get("line_user_id")
        if (
            not line_user_id
            or user.get("membership_paused")
            or not membership_access_active(user, now)
            or not plan_has_smart_reminders(user)
        ):
            skipped += 1
            continue
        sent_keys = set(user.get("smart_reminder_sent_keys") or [])
        snooze = user.get("smart_reminder_snooze") or {}
        daily_all = user.setdefault("smart_reminder_daily_usage", {})
        usage = daily_all.setdefault(today_key, {"private": 0, "guardian": 0})
        # Keep only a compact rolling window.
        user["smart_reminder_daily_usage"] = {
            key: value for key, value in daily_all.items() if key >= (today_date - timedelta(days=7)).isoformat()
        }
        bound_guardians = {
            get_contact_line_id(contact)
            for contact in user.get("contacts") or []
            if contact_is_bound_guardian(contact, line_user_id)
        }
        due_groups = {}
        for reminder in list_smart_reminders(user):
            if not reminder.get("enabled", True):
                skipped += 1
                continue
            rid = reminder.get("id")
            remind_hm = str(reminder.get("remind_time") or "09:00").strip()
            if not REMINDER_TIME_PATTERN.match(remind_hm):
                remind_hm = "09:00"
            target_spec = str(reminder.get("delivery_target") or "private")
            if target_spec == "private":
                target_kind, target_id = "private", line_user_id
            elif target_spec.startswith("guardian:"):
                target_kind, target_id = "guardian", target_spec.split(":", 1)[1]
                if target_id not in bound_guardians:
                    skipped += 1
                    continue
            else:
                skipped += 1
                continue
            if now_hm >= remind_hm and smart_reminder_occurs_on(reminder, today_date):
                key = f"{today_key}:{rid}:day"
                snooze_until = parse_datetime(snooze.get("until")) if snooze.get("id") == rid else None
                if key in sent_keys and not (snooze_until and now >= snooze_until):
                    continue
                if snooze_until and now < snooze_until:
                    continue
                due_groups.setdefault(("day", remind_hm, target_kind, target_id), []).append((key, reminder))
            if eve_window and reminder.get("eve_remind", True) and smart_reminder_occurs_on(reminder, tomorrow):
                key = f"{today_key}:{rid}:eve"
                if key in sent_keys:
                    continue
                due_groups.setdefault(("eve", "20:00", target_kind, target_id), []).append((key, reminder))

        for (mode, slot, target_kind, target_id), entries in sorted(due_groups.items()):
            limit = 2 if target_kind == "private" else 1
            if int(usage.get(target_kind) or 0) >= limit:
                skipped += len(entries)
                continue
            keys = [key for key, _reminder in entries]
            reminders = [reminder for _key, reminder in entries]
            delivery_key = f"smart_reminder:{today_key}:{mode}:{slot}:{target_kind}:{target_id}"
            if not push_attempt_allowed(user, delivery_key):
                skipped += len(entries)
                continue
            message = build_smart_reminder_digest(reminders, mode=mode)
            try:
                result = sender(token, target_id, message)
                _clear_push_delivery_failure(user, delivery_key)
                sent_keys.update(keys)
                usage[target_kind] = int(usage.get(target_kind) or 0) + 1
                if snooze.get("id") in {r.get("id") for r in reminders}:
                    user["smart_reminder_snooze"] = {}
                append_notification_log(
                    state, "smart_reminder", target_id, "sent",
                    message.get("altText"), json.dumps(result, ensure_ascii=False),
                )
                record_line_message_usage(
                    state,
                    category="smart_reminder",
                    owner_line_user_id=line_user_id,
                    recipient_count=1,
                    event_id=delivery_key,
                    sent_at=now,
                )
                sent += 1
                results.append({
                    "line_user_id": line_user_id,
                    "target": target_kind,
                    "recipient": target_id,
                    "ids": [r.get("id") for r in reminders],
                    "mode": mode,
                    "merged_count": len(reminders),
                })
            except Exception as exc:
                failure = _record_scheduled_push_failure(
                    state, user, delivery_key, "smart_reminder", target_id,
                    message.get("altText"), exc, now,
                )
                skipped += len(entries)
                results.append({"line_user_id": line_user_id, "ids": [r.get("id") for r in reminders], "error": str(exc)})
                if failure["kind"] == "system":
                    system_error = True
                    break
        user["smart_reminder_sent_keys"] = sorted(sent_keys)[-120:]
        if system_error:
            break

    save_state(data_file, state)
    return {
        "sent": sent,
        "skipped": skipped,
        "results": results,
        "system_error": system_error,
    }, 200


def cleanup_expired_sos(config):
    state = load_state(config["DATA_FILE"])
    removed = sos_flow.sos_purge_old(state, keep_minutes=60) if sos_flow else []
    save_state(config["DATA_FILE"], state)
    return {"removed": len(removed)}, 200


def send_profile_completion_reminders(config):
    """Private, retryable reminders at bind, +24h, day 3, and day 7 only."""
    token = config.get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        return {"sent": 0, "skipped": 0, "error": "LINE_CHANNEL_ACCESS_TOKEN is not set"}, 400
    state = load_state(config["DATA_FILE"])
    sender = config.get("LINE_PUSH_SENDER") or line_push_message
    now = current_app_time(config)
    sent = skipped = 0
    results = []
    for profile in (state.get("users") or {}).values():
        if not isinstance(profile, dict) or not profile.get("profile_completion_required"):
            continue
        if profile.get("membership_paused") or not membership_access_active(profile, now):
            skipped += 1
            continue
        completion_peer = str(
            profile.get("profile_completion_peer_line_user_id") or ""
        ).strip()
        completion_contacts = [
            contact
            for contact in (profile.get("contacts") or [])
            if isinstance(contact, dict)
            and resolve_contact_role(contact) == "guardian"
            and (
                not completion_peer
                or get_contact_line_id(contact) == completion_peer
            )
        ]
        if any(complete_guardian_contact(contact) for contact in completion_contacts):
            profile["profile_completion_required"] = False
            profile["profile_completion_completed_at"] = now.isoformat(timespec="seconds")
            skipped += 1
            continue
        try:
            bound_at = datetime.fromisoformat(str(profile.get("profile_completion_bound_at") or ""))
        except ValueError:
            skipped += 1
            continue
        elapsed_days = max(0, (now.date() - bound_at.date()).days)
        already = {int(day) for day in (profile.get("profile_completion_reminder_days") or [])}
        due = [day for day in PROFILE_COMPLETION_REMINDER_DAYS if day <= elapsed_days and day not in already]
        for day in due:
            message = "已完成核心守護綁定。請私訊「每日平安」完成自己的聯絡資料；LINE 通知已可使用，電話聯絡會在資料完成後啟用。"
            try:
                result = sender(token, profile.get("line_user_id"), message)
                append_notification_log(state, "profile_completion", profile.get("line_user_id"), "sent", message, json.dumps(result, ensure_ascii=False))
                already.add(day)
                sent += 1
                results.append({"line_user_id": profile.get("line_user_id"), "day": day, "status": "sent"})
            except Exception as exc:
                append_notification_log(state, "profile_completion", profile.get("line_user_id"), "failed", message, str(exc)[:400])
                results.append({"line_user_id": profile.get("line_user_id"), "day": day, "status": "failed"})
        profile["profile_completion_reminder_days"] = sorted(already)
    save_state(config["DATA_FILE"], state)
    return {"sent": sent, "skipped": skipped, "results": results}, 200


def run_cron_tick(config):
    now = current_app_time(config)
    results = {}
    slot = now.strftime("%H:%M")

    migration_data, migration_code = migrate_existing_free_members(config)
    results["membership_transition_migration"] = {
        "status": migration_code,
        "result": migration_data,
    }
    # 每次 Cron 都先補送到期里程碑，再執行到期降級；claim/outbox 會防重。
    milestone_data, milestone_code = send_trial_milestone_notices(config)
    results["trial_milestone_notices"] = {
        "status": milestone_code,
        "result": milestone_data,
    }
    expiry_data, expiry_code = apply_expired_plan_downgrades(config)
    results["membership_expiry"] = {
        "status": expiry_code,
        "result": expiry_data,
    }

    always = {
        "checkin_reminders": send_checkin_reminders,
        "binding_notification_retries": retry_pending_bind_notifications,
        "profile_completion_reminders": send_profile_completion_reminders,
        "overdue_alerts": send_due_reminders,
        "guardian_group_daily_summaries": send_guardian_group_daily_summaries,
        "smart_reminders": send_smart_reminders,
        "sos_escalations": lambda cfg: (
            process_sos_escalations(cfg["DATA_FILE"], cfg, now=now),
            200,
        ),
        "sos_cleanup": cleanup_expired_sos,
    }
    for name, task in always.items():
        data, code = task(config)
        results[name] = {"status": code, "result": data}
        if isinstance(data, dict) and data.get("system_error"):
            return {
                "ok": False,
                "system_error": True,
                "ran_at": now.isoformat(timespec="seconds"),
                "timezone": "Asia/Taipei",
                "tasks": results,
            }, 200

    token = config.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    results["guardian_group_refresh"] = refresh_all_guardian_groups_count(
        config["DATA_FILE"],
        token=token,
    )

    daily = {
        "09:00": ("birthday_reminders", send_birthday_reminders),
        "09:05": ("contact_reminders", send_missing_contact_reminders),
        "10:00": ("renewal_reminders", send_renewal_reminders),
        "19:00": ("beta_daily_feedback", send_beta_daily_feedback),
        "02:30": ("data_cleanup", cleanup_expired_data),
    }
    if slot in daily:
        name, task = daily[slot]
        data, code = task(config)
        results[name] = {"status": code, "result": data}
        if isinstance(data, dict) and data.get("system_error"):
            return {
                "ok": False,
                "system_error": True,
                "ran_at": now.isoformat(timespec="seconds"),
                "timezone": "Asia/Taipei",
                "tasks": results,
            }, 200

    return {
        "ok": all(
            item.get("status", 200) < 500
            for item in results.values()
            if isinstance(item, dict)
        ),
        "system_error": False,
        "ran_at": now.isoformat(timespec="seconds"),
        "timezone": "Asia/Taipei",
        "tasks": results,
    }, 200


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
        "liff_id": config.get("LIFF_ID") or os.environ.get("LIFF_ID") or DEFAULT_LIFF_ID,
        "legacy_liff_id": (
            config.get("LEGACY_LIFF_ID")
            or os.environ.get("LEGACY_LIFF_ID")
            or DEFAULT_LEGACY_LIFF_ID
        ),
        "public_url": config.get("APP_PUBLIC_URL") or os.environ.get("APP_PUBLIC_URL", ""),
        # Visible deploy stamp for verifying Render actually rolled the welcome Flex.
        "deploy_version": os.environ.get("DEPLOY_VERSION") or "W250725gh",
        # Both token and secret are required for LINE webhook / messaging.
        "line_enabled": bool(token and secret),
        "require_liff_auth": str(
            config.get("REQUIRE_LIFF_AUTH")
            if config.get("REQUIRE_LIFF_AUTH") is not None
            else os.environ.get("REQUIRE_LIFF_AUTH", "0")
        ).strip().lower()
        in {"1", "true", "yes", "on"},
        "ecpay_ready": bool(ecpay and ecpay.ecpay_configured(config)),
        "newebpay_ready": bool(newebpay and newebpay.newebpay_configured(config)),
        "sms_live": bool(
            (config.get("SMSKING_USERNAME") or os.environ.get("SMSKING_USERNAME") or "").strip()
            and (config.get("SMSKING_PASSWORD") or os.environ.get("SMSKING_PASSWORD") or "").strip()
        ),
    }


def authenticated_line_user(payload=None, *, args=None, headers=None, config=None):
    """Resolve one caller identity; never trust a route's requested member ID."""
    payload = payload or {}
    args = args or {}
    headers = headers or {}
    if resolve_line_user_id is None:
        claimed = str(payload.get("line_user_id") or args.get("line_user_id") or "").strip()
        if not claimed:
            return None, ({"ok": False, "error": "missing line_user_id"}, 400)
        return claimed, None
    return resolve_line_user_id(
        headers=headers,
        payload=payload,
        args=args,
        config=config or {},
    )


def update_onboarding_reminder(data_file, line_user_id, payload):
    state = load_state(data_file)
    profile = get_profile(state, line_user_id)
    max_count = int(plan_rules(profile).get("daily_reminders") or 1)
    if "reminder_times" in payload:
        raw = payload.get("reminder_times")
        if not isinstance(raw, list) or not raw:
            return {"ok": False, "error": "reminder_times must be a non-empty list"}, 400
        normalized = normalize_reminder_times(raw, max_count)
        if not normalized:
            return {"ok": False, "error": "invalid reminder_times format, use HH:MM"}, 400
        times = apply_reminder_times_to_profile(profile, times=normalized)
    else:
        reminder_time = (payload.get("reminder_time") or "").strip()
        if not REMINDER_TIME_PATTERN.match(reminder_time):
            return {"ok": False, "error": "invalid reminder_time format, use HH:MM"}, 400
        times = apply_reminder_times_to_profile(profile, single=reminder_time)
    if "daily_checkin_reminder_enabled" in payload:
        profile["daily_checkin_reminder_enabled"] = bool(
            payload.get("daily_checkin_reminder_enabled")
        )
    if "grace_hours" in payload:
        profile["grace_hours"] = normalize_grace_hours(payload.get("grace_hours"))
    else:
        profile["grace_hours"] = normalize_grace_hours(profile.get("grace_hours"))
    if "overdue_wait_minutes" in payload:
        profile["overdue_wait_minutes"] = normalize_overdue_wait_minutes(
            payload.get("overdue_wait_minutes")
        )
    else:
        profile["overdue_wait_minutes"] = normalize_overdue_wait_minutes(
            profile.get("overdue_wait_minutes")
        )
    profile["onboarding_reminder_configured"] = True
    save_state(data_file, state)
    return {
        "ok": True,
        "reminder_time": times[0],
        "reminder_times": times,
        "daily_reminders": max_count,
        "onboarding_reminder_configured": True,
        "daily_checkin_reminder_enabled": bool(
            profile.get("daily_checkin_reminder_enabled", True)
        ),
        "grace_hours": normalize_grace_hours(profile.get("grace_hours")),
        "overdue_wait_minutes": normalize_overdue_wait_minutes(
            profile.get("overdue_wait_minutes")
        ),
        "allowed_overdue_wait_minutes": list(ALLOWED_OVERDUE_WAIT_MINUTES),
        "warning_cancel_minutes": int(
            profile.get("warning_cancel_minutes") or DEFAULT_WARNING_CANCEL_MINUTES
        ),
        "allowed_grace_hours": list(ALLOWED_GRACE_HOURS),
    }, 200


def complete_onboarding_for_user(data_file, line_user_id, payload):
    state = load_state(data_file)
    profile = state.get("users", {}).get(line_user_id)
    if not profile:
        return {"ok": False, "error": "user not registered"}, 404
    access = member_access_state(profile)
    if access["guardian_required"]:
        return {
            "ok": False,
            "error": "guardian_required",
            "message": "必須先完成至少 1 位可接收 LINE 通知的核心守護人綁定",
            **access,
        }, 400
    profile["is_onboarding_completed"] = True
    if "reminder_times" in payload or payload.get("reminder_time"):
        apply_reminder_times_to_profile(
            profile,
            times=payload.get("reminder_times"),
            single=payload.get("reminder_time"),
        )
    else:
        apply_reminder_times_to_profile(profile)
    istate = get_or_create_interaction_state(profile)
    istate["onboarding_completed"] = True
    if "add_first_guardian" not in istate["completed_steps"]:
        istate["completed_steps"].append("add_first_guardian")
    if "set_reminder_time" not in istate["completed_steps"]:
        istate["completed_steps"].append("set_reminder_time")
    if not istate.get("pending_steps"):
        istate["pending_steps"] = [
            "explore_app",
            "read_help",
            "add_more_guardians_if_paid",
        ]
    istate["last_interaction_at"] = datetime.now().isoformat(timespec="seconds")
    save_state(data_file, state)
    times = reminder_times_for_profile(profile)
    return {
        "ok": True,
        **member_access_state(profile),
        "is_onboarding_completed": True,
        "setup_completed": True,
        "reminder_time": times[0],
        "reminder_times": times,
        "interaction_state": istate,
    }, 200


def checkin_for_user(data_file, line_user_id, payload, config=None):
    payload = dict(payload or {})
    payload["line_user_id"] = line_user_id
    now = current_app_time(config or {})
    event_id = f"checkin:{line_user_id}:{uuid.uuid4().hex}"
    mutate_state_atomically(
        data_file,
        lambda current_state: current_state.setdefault(
            "launch_events", []
        ).append({
            "id": event_id,
            "kind": "checkin",
            "success": False,
            "at": now.isoformat(timespec="seconds"),
        }),
    )
    state = load_state(data_file)
    if line_user_id not in state.get("users", {}):
        register_line_user(
            data_file,
            {
                "line_user_id": line_user_id,
                "display_name": str(payload.get("display_name") or "LINE 使用者"),
            },
        )
        state = load_state(data_file)
    access = member_access_state(state.get("users", {}).get(line_user_id))
    if access["guardian_required"]:
        return {
            "ok": False,
            "error": "guardian_required",
            "message": "必須先完成至少 1 位可接收 LINE 通知的核心守護人綁定",
            **access,
        }, 400
    status = record_checkin(data_file, payload, config=config)
    mutate_state_atomically(
        data_file,
        lambda current_state: next(
            (
                row.update({"success": True})
                for row in current_state.get("launch_events") or []
                if row.get("id") == event_id
            ),
            None,
        ),
    )
    status["ok"] = True
    return status, 200


def status_for_user(data_file, line_user_id, display_name=""):
    state = load_state(data_file)
    profile = state.get("users", {}).get(line_user_id)
    if not profile:
        data, code = register_line_user(
            data_file,
            {
                "line_user_id": line_user_id,
                "display_name": str(display_name or "").strip() or "LINE 使用者",
            },
        )
        if code != 200:
            return data, code
        if isinstance(data, dict):
            data["auto_registered"] = True
        return data, 200
    dirty = scrub_self_line_ids_on_contacts(profile)
    dirty = deduplicate_contact_line_bindings(profile) or dirty
    dirty = ensure_onboarding_completed_flag(profile) or dirty
    today = today_string()
    if profile_is_today_checked(profile) and today not in set(profile.get("history") or []):
        hist = set(profile.get("history") or [])
        hist.add(today)
        profile["history"] = sorted(hist)
        dirty = True
    before_groups = list(profile.get("guardian_group_ids") or [])
    sync_owned_guardian_group_ids(state, profile)
    if list(profile.get("guardian_group_ids") or []) != before_groups:
        dirty = True
    if dirty:
        save_state(data_file, state)
    return build_status(profile, state), 200


def create_app(config=None):
    if Flask is None:
        return MiniApp(config)

    supplied_config = config or {}
    liff_id = (
        supplied_config.get("LIFF_ID")
        or os.environ.get("LIFF_ID")
        or DEFAULT_LIFF_ID
    ).strip() or DEFAULT_LIFF_ID
    explicit_channel_id = (
        supplied_config.get("LINE_LOGIN_CHANNEL_ID")
        or os.environ.get("LINE_LOGIN_CHANNEL_ID")
        or os.environ.get("LINE_Login_Channel_ID")
        or ""
    ).strip()
    line_login_channel_id = (
        explicit_channel_id
        or liff_id.split("-", 1)[0]
        or DEFAULT_LINE_LOGIN_CHANNEL_ID
    )

    app = Flask(__name__, static_folder=".", static_url_path="")
    app._start_time = datetime.now()  # 2026-07-21 patch 17: 供 /api/bot/status 計算 uptime

    @app.errorhandler(AccountMigratedError)
    def _account_migrated_error(_error):
        return jsonify(account_migrated_response()), 409

    app.config.update(
        DATA_FILE=resolve_data_file(os.environ.get("DATA_FILE")),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", ""),
        ADMIN_OPERATIONS_PASSWORD=os.environ.get("ADMIN_OPERATIONS_PASSWORD", ""),
        ADMIN_FINANCE_PASSWORD=os.environ.get("ADMIN_FINANCE_PASSWORD", ""),
        ADMIN_VIEWER_PASSWORD=os.environ.get("ADMIN_VIEWER_PASSWORD", ""),
        ADMIN_SESSION_SECRET=os.environ.get("ADMIN_SESSION_SECRET", ""),
        TRUST_PROXY_HEADERS=os.environ.get("TRUST_PROXY_HEADERS", ""),
        ALLOW_OPEN_ADMIN=os.environ.get("ALLOW_OPEN_ADMIN", ""),
        ADMIN_OPEN=os.environ.get("ADMIN_OPEN", ""),
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_SAMESITE="Strict",
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
        LINE_LOGIN_CHANNEL_ID=line_login_channel_id,
        LINE_LOGIN_CHANNEL_SECRET=(
            os.environ.get("LINE_LOGIN_CHANNEL_SECRET")
            or os.environ.get("LINE_Login_CHANNEL_SECRET")
            or ""
        ),
        LEGACY_LINE_LOGIN_CHANNEL_ID=os.environ.get(
            "LEGACY_LINE_LOGIN_CHANNEL_ID", "2010674803"
        ),
        LEGACY_LIFF_ID=os.environ.get(
            "LEGACY_LIFF_ID", DEFAULT_LEGACY_LIFF_ID
        ),
        ACCOUNT_MIGRATION_SECRET=os.environ.get("ACCOUNT_MIGRATION_SECRET", ""),
        ACCOUNT_MIGRATION_TTL_SECONDS=600,
        LIFF_ID=liff_id,
        APP_PUBLIC_URL=os.environ.get("APP_PUBLIC_URL", ""),
        APP_TIMEZONE=os.environ.get("APP_TIMEZONE", "Asia/Taipei"),
        GA4_PROPERTY_ID=os.environ.get("GA4_PROPERTY_ID", ""),
        GA4_SERVICE_ACCOUNT_JSON=os.environ.get("GA4_SERVICE_ACCOUNT_JSON", ""),
        GA4_MEASUREMENT_ID=os.environ.get("GA4_MEASUREMENT_ID", "G-7LT14XLHFM"),
        WORDPRESS_SITE_URL=os.environ.get("WORDPRESS_SITE_URL", ""),
        WORDPRESS_USERNAME=os.environ.get("WORDPRESS_USERNAME", ""),
        WORDPRESS_APPLICATION_PASSWORD=os.environ.get("WORDPRESS_APPLICATION_PASSWORD", ""),
        LINE_MONTHLY_MESSAGE_LIMIT=os.environ.get("LINE_MONTHLY_MESSAGE_LIMIT", "200"),
        LINE_MESSAGE_WARNING_PERCENT=os.environ.get("LINE_MESSAGE_WARNING_PERCENT", "80"),
        LINE_MESSAGE_HARD_STOP_PERCENT=os.environ.get("LINE_MESSAGE_HARD_STOP_PERCENT", "100"),
        CRON_SECRET=os.environ.get("CRON_SECRET", ""),
        REQUIRE_LIFF_AUTH=os.environ.get("REQUIRE_LIFF_AUTH", "0"),
        NEWEBPAY_MERCHANT_ID=os.environ.get("NEWEBPAY_MERCHANT_ID", ""),
        NEWEBPAY_HASH_KEY=os.environ.get("NEWEBPAY_HASH_KEY", ""),
        NEWEBPAY_HASH_IV=os.environ.get("NEWEBPAY_HASH_IV", ""),
        NEWEBPAY_STAGE=os.environ.get("NEWEBPAY_STAGE", "sandbox"),
        NEWEBPAY_MPG_URL=os.environ.get("NEWEBPAY_MPG_URL", ""),
        ECPAY_MERCHANT_ID=os.environ.get("ECPAY_MERCHANT_ID", ""),
        ECPAY_HASH_KEY=os.environ.get("ECPAY_HASH_KEY", ""),
        ECPAY_HASH_IV=os.environ.get("ECPAY_HASH_IV", ""),
        ECPAY_STAGE=os.environ.get("ECPAY_STAGE", "sandbox"),
        ECPAY_PERIOD_TIMES=os.environ.get("ECPAY_PERIOD_TIMES", "99"),
        SMSKING_USERNAME=os.environ.get("SMSKING_USERNAME", ""),
        SMSKING_PASSWORD=os.environ.get("SMSKING_PASSWORD", ""),
        SMTP_HOST=os.environ.get("SMTP_HOST", ""),
        SMTP_PORT=os.environ.get("SMTP_PORT", "587"),
        SMTP_USERNAME=os.environ.get("SMTP_USERNAME", ""),
        SMTP_PASSWORD=os.environ.get("SMTP_PASSWORD", ""),
        SMTP_USE_TLS=os.environ.get("SMTP_USE_TLS", "true"),
        SUPPORT_FROM_EMAIL=os.environ.get("SUPPORT_FROM_EMAIL", ""),
        R2_ENDPOINT=os.environ.get("R2_ENDPOINT", ""),
        R2_ACCESS_KEY_ID=os.environ.get("R2_ACCESS_KEY_ID", ""),
        R2_SECRET_ACCESS_KEY=os.environ.get("R2_SECRET_ACCESS_KEY", ""),
        R2_BUCKET=os.environ.get("R2_BUCKET", ""),
        R2_BACKUP_ENCRYPTION_KEY=os.environ.get(
            "R2_BACKUP_ENCRYPTION_KEY", ""
        ),
        TEST_LINE_USER_IDS=os.environ.get("TEST_LINE_USER_IDS", ""),
    )
    if config:
        app.config.update(config)
    app.secret_key = (
        app.config.get("ADMIN_SESSION_SECRET")
        or secrets.token_hex(32)
    )

    def _admin_guard(*, write=False, permission=None):
        if not admin_security_ready(app.config):
            return jsonify({"error": "admin_not_configured"}), 503
        if session.get("admin_authenticated") is not True:
            return jsonify({"error": "unauthorized"}), 401
        if write:
            expected = str(session.get("admin_csrf") or "")
            provided = str(request.headers.get("X-CSRF-Token") or "")
            if not expected or not secrets.compare_digest(expected, provided):
                return jsonify({"error": "csrf_required"}), 403
        if permission:
            role = str(session.get("admin_role") or "viewer")
            if permission not in ADMIN_ROLE_PERMISSIONS.get(role, set()):
                append_admin_audit(
                    app.config["DATA_FILE"],
                    "permission.denied",
                    "failed",
                    {"role": role, "required_permission": permission},
                )
                return jsonify({"error": "forbidden", "required_permission": permission}), 403
        return None

    def _admin_mutation_response(action, data, code=200):
        append_admin_audit(
            app.config["DATA_FILE"],
            action,
            "success" if code < 400 else "failed",
            {"http_status": code},
        )
        return jsonify(data), code

    def _admin_login_transport_secure():
        if app.config.get("TESTING") is True:
            return True
        if request.is_secure:
            return True
        if str(request.remote_addr or "") in {"127.0.0.1", "::1"}:
            return True
        trusted_proxy = (
            _env_flag_on("RENDER", app.config)
            or _env_flag_on("TRUST_PROXY_HEADERS", app.config)
        )
        forwarded_proto = str(
            request.headers.get("X-Forwarded-Proto") or ""
        ).split(",", 1)[0].strip().lower()
        return trusted_proxy and forwarded_proto == "https"

    @app.post("/api/admin/login")
    def admin_login_api():
        if not _admin_login_transport_secure():
            return jsonify({"error": "https_required"}), 400
        if not admin_security_ready(app.config):
            return jsonify({"error": "admin_not_configured"}), 503
        payload = request.get_json(silent=True) or {}
        client_key = str(request.remote_addr or "unknown")
        if admin_login_rate_limited(client_key):
            return jsonify({"error": "too_many_attempts"}), 429
        role = admin_role_for_password(app.config, payload.get("password"))
        if role is None:
            record_admin_login_failure(client_key)
            append_admin_audit(app.config["DATA_FILE"], "session.login", "failed")
            return jsonify({"error": "invalid_credentials"}), 401
        ADMIN_LOGIN_ATTEMPTS.pop(client_key, None)
        session.clear()
        session.permanent = True
        session["admin_authenticated"] = True
        session["admin_role"] = role
        session["admin_csrf"] = secrets.token_urlsafe(32)
        append_admin_audit(app.config["DATA_FILE"], "session.login", "success")
        return jsonify({
            "ok": True,
            "csrf_token": session["admin_csrf"],
            "role": role,
            "permissions": admin_permissions_for_role(role),
            "expires_in": 8 * 60 * 60,
        })

    @app.get("/api/admin/session")
    def admin_session_api():
        if not admin_security_ready(app.config):
            return jsonify({"authenticated": False, "error": "admin_not_configured"}), 503
        authenticated = session.get("admin_authenticated") is True
        return jsonify({
            "authenticated": authenticated,
            "csrf_token": session.get("admin_csrf") if authenticated else None,
            "role": session.get("admin_role") if authenticated else None,
            "permissions": admin_permissions_for_role(session.get("admin_role")) if authenticated else [],
        }), (200 if authenticated else 401)

    @app.post("/api/admin/logout")
    def admin_logout_api():
        denied = _admin_guard(write=True)
        if denied:
            return denied
        session.clear()
        append_admin_audit(app.config["DATA_FILE"], "session.logout", "success")
        return jsonify({"ok": True})

    def _authenticated_line_user(payload=None, *, use_args=False):
        """Resolve LINE user from verified id_token when required."""
        payload = payload if payload is not None else (request.get_json(silent=True) or {})
        args = request.args if use_args else {}
        return authenticated_line_user(
            payload,
            args=args,
            headers={key: value for key, value in request.headers.items()},
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

    @app.get("/beta/399")
    @app.get("/beta/799")
    def beta_registration_landing():
        """Public 21-day beta introduction; the CTA continues in verified LIFF."""
        return send_from_directory(app.static_folder, "beta-register.html")

    @app.get("/trial/14")
    def public_trial_landing():
        """Public 14-day trial introduction and guided registration."""
        return send_from_directory(app.static_folder, "trial-14.html")

    @app.get("/guardian-guide")
    def guardian_guide():
        """Detailed guardian notice linked from the concise invite landing."""
        return send_from_directory(app.static_folder, "guardian-guide.html")

    @app.get("/health")
    def health():
        persist = persistence_info(app.config["DATA_FILE"])
        return jsonify({"ok": True, "persistence": persist})

    @app.get("/robots.txt")
    def robots_txt():
        return send_from_directory(app.static_folder, "robots.txt", mimetype="text/plain")

    @app.get("/sitemap.xml")
    def sitemap_xml():
        return send_from_directory(app.static_folder, "sitemap.xml", mimetype="application/xml")

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
                or DEFAULT_LIFF_ID
            ).strip()
            target = f"https://liff.line.me/{lid}"
            if open_action:
                target += f"?open={open_action}"
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

    @app.get("/liff/migrate.html")
    def liff_migration_handoff_page():
        """Legacy LIFF handoff that asks users to explicitly reauthorize."""
        return send_from_directory(app.static_folder, "liff/migrate.html")

    # 2026-07-21 patch 24: Onboarding 流程 API
    @app.get("/liff/onboarding")
    def liff_onboarding():
        return _liff_embed_redirect(open_action="onboarding")

    @app.get("/api/onboarding/state")
    def onboarding_state_api():
        """取得使用者 onboarding 狀態(守護人是否綁定 + 提醒時間)。"""
        line_user_id, err = _authenticated_line_user({}, use_args=True)
        if err:
            return jsonify(err[0]), err[1]
        data, code = onboarding_status_payload(
            app.config["DATA_FILE"],
            line_user_id,
            allow_missing_profile=True,
        )
        return jsonify(data), code

    @app.post("/api/onboarding/reminder")
    def onboarding_reminder_api():
        """設定使用者每日提醒時間(支援單一或多時段)。"""
        data = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(data)
        if err:
            return jsonify(err[0]), err[1]
        result, code = update_onboarding_reminder(
            app.config["DATA_FILE"], line_user_id, data
        )
        return jsonify(result), code

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
            "deploy_version": os.environ.get("DEPLOY_VERSION") or "W250725gh",
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
        data, code = status_for_user(
            app.config["DATA_FILE"],
            line_user_id,
            request.args.get("display_name"),
        )
        return jsonify(data), code

    @app.post("/api/line/register")
    def line_register():
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        payload["line_user_id"] = line_user_id
        data, code = register_line_user(app.config["DATA_FILE"], payload)
        return jsonify(data), code

    @app.post("/api/beta/claim")
    def beta_claim_api():
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        cohort = str(payload.get("beta_cohort") or "").strip().upper()
        if cohort not in {"B399", "B799"}:
            return jsonify({"ok": False, "error": "invalid_beta_link"}), 400
        try:
            result = mutate_state_atomically(
                app.config["DATA_FILE"],
                lambda state: claim_beta_link(state, line_user_id, cohort),
            )
        except ValueError as exc:
            reason = str(exc)
            messages = {
                "cohort_full": "這一組封測名額已滿",
                "already_in_other_cohort": "你已加入另一個封測組別",
                "member_not_found": "請先完成 LINE 會員註冊",
                "free_eligibility_already_used": "你已使用過免費體驗或封測資格",
            }
            return jsonify({
                "ok": False,
                "error": reason,
                "message": messages.get(reason, "無法加入封測"),
            }), 409 if reason != "member_not_found" else 404
        return jsonify({"ok": True, **result}), 200

    @app.post("/api/checkin")
    def checkin():
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        result, code = checkin_for_user(
            app.config["DATA_FILE"], line_user_id, payload, app.config
        )
        return jsonify(result), code

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
            """需要幫忙：聊天室連續確認 3 次後送入共用 SOS 事件。

            command:
              - '需要幫忙' / 'SOS' / 'sos' / '緊急求助' : 累計一次確認
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
            # 已送到聊天室的舊 Flex 按鈕無法回收；保留其文字命令，
            # 但一律只回新版 LIFF 入口，不再啟動舊的聊天狀態機。
            legacy_entry_commands = (
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

            # 聊天室保留連續 3 次確認；圖文選單則開 LIFF 的同一套 3 次流程。
            if command in entry_commands or command in legacy_entry_commands:
                tap = sos_flow.sos_tap(state, line_user_id)
                count = int((tap.get("entry") or {}).get("tap_count") or 1)
                save_state(app.config["DATA_FILE"], state)
                if count < 3:
                    reply(
                        sos_flow.sos_warning_flex(count),
                        f"🆘 需要幫忙確認 {count}/3",
                    )
                    return
                result, status_code = trigger_sos(
                    app.config["DATA_FILE"],
                    {"line_user_id": line_user_id},
                    app.config,
                )
                if status_code == 200:
                    latest = load_state(app.config["DATA_FILE"])
                    sos_flow.sos_mark_sent(
                        latest, line_user_id, result.get("event_id")
                    )
                    save_state(app.config["DATA_FILE"], latest)
                    reply(
                        sos_flow.sos_sent_flex(),
                        f"🚨 SOS 已送出，已通知 {int(result.get('sent') or 0)} 個對象",
                    )
                elif str(result.get("error") or "") == "no bound LINE guardians":
                    reply(
                        sos_flow.sos_no_guardians_flex(),
                        sos_user_facing_error(result.get("error")),
                    )
                else:
                    reply(None, sos_user_facing_error(result.get("error")))
                return

            if command not in entry_commands and command not in legacy_entry_commands:
                reply(None, "請傳送「需要幫忙」開啟求助選項")
                return

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
                else "https://liff.line.me/2010848330-UAiqPPYD?open=onboarding"
            )
            invite_uri = (
                share_invite_liff_url()
                if share_invite_liff_url
                else "https://liff.line.me/2010848330-UAiqPPYD/liff/share-invite.html"
            )
            help_uri = (
                liff_entry_url(open_action="help")
                if liff_entry_url
                else "https://liff.line.me/2010848330-UAiqPPYD?open=help"
            )
            welcome_fallback = (
                f"{greeting}\n\n"
                "每天 10 秒，報個平安\n"
                "平常不打擾，有事才通知守護人\n\n"
                "開始使用前兩個步驟：\n"
                "① 新增 1 位守護人\n"
                "② 設定每日提醒時間\n\n"
                "🎁 首次註冊可享一次 14 天安心體驗\n"
                "緊急狀況請直接撥打 119 或 110\n\n"
                f"免費體驗 14 天：{setup_uri}\n"
                f"一鍵守護邀請：{invite_uri}\n"
                f"了解每日平安：{help_uri}\n"
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

        def _guardian_intro_messages(owner_info, hint_text=None):
            """進群歡迎：短文字 + Flex（雙保險，避免 Flex 被拒時整段消失）。"""
            tip = hint_text or (
                "🛡️ 歡迎加入「每日平安」守護群\n"
                "平時不打擾，只在需要時通知大家。"
            )
            messages = [TextSendMessage(text=tip)]
            if FlexSendMessage is not None and guardian_group_intro_flex is not None:
                messages.append(
                    FlexSendMessage(
                        alt_text="🛡️ 歡迎加入「每日平安」守護群",
                        contents=guardian_group_intro_flex(owner_info),
                    )
                )
            return messages

        def _reply_migrated_account(reply_token, registration_result):
            guidance = migrated_account_webhook_guidance(
                registration_result,
                app.config.get("LIFF_ID") or DEFAULT_LIFF_ID,
            )
            if not guidance:
                return False
            try:
                line_bot_api.reply_message(
                    reply_token,
                    TextSendMessage(text=guidance),
                )
            except Exception as exc:
                app.logger.exception(
                    "migrated account guidance reply failed: %s", exc
                )
            return True

        def _enrich_bind_result_for_flex(result, line_user_id):
            """補上資訊卡：管理人／核心守護人／緊急聯絡人／群組成員／提醒時間。"""
            enriched = dict(result or {})
            try:
                state = load_state(app.config["DATA_FILE"])
                profile = get_profile(state, line_user_id) or {}
                rules = plan_rules(profile)
                times = reminder_times_for_profile(profile) or ["09:00"]
                contacts = profile.get("contacts") or []
                # 已綁定核心守護人 ≠ 群組成員 ≠ 緊急聯絡人；只用 core 名額
                guardian_count = sum(
                    1
                    for c in contacts
                    if resolve_contact_role(c) != "emergency"
                    and contact_is_bound_guardian(c, line_user_id)
                )
                emergency_count = sum(
                    1 for c in contacts if resolve_contact_role(c) == "emergency"
                )
                enriched.setdefault(
                    "display_name",
                    (profile.get("display_name") or "").strip() or "管理員",
                )
                enriched.setdefault("guardian_count", guardian_count)
                enriched.setdefault(
                    "guardian_limit",
                    int(rules.get("core_guardian_alert_limit") or 5),
                )
                enriched.setdefault("core_guardian_alert_limit", int(rules.get("core_guardian_alert_limit") or 5))
                enriched.setdefault("emergency_count", emergency_count)
                enriched.setdefault(
                    "emergency_limit",
                    int(rules.get("emergency_contact_limit") or 2),
                )
                enriched.setdefault(
                    "emergency_contact_limit",
                    int(rules.get("emergency_contact_limit") or 2),
                )
                enriched.setdefault("reminder_time", str(times[0] if times else "09:00"))
                enriched.setdefault("reminder_times", list(times))
                group_id = enriched.get("group_id")
                if group_id:
                    refreshed = refresh_guardian_group_member_snapshot(
                        app.config["DATA_FILE"], group_id
                    )
                    if refreshed and refreshed.get("member_count_at_bind") is not None:
                        enriched["member_count"] = refreshed.get("member_count_at_bind")
                    else:
                        g = (state.get("guardian_groups") or {}).get(group_id) or {}
                        if g.get("member_count_at_bind") is not None:
                            enriched.setdefault(
                                "member_count", g.get("member_count_at_bind")
                            )
            except Exception as exc:
                app.logger.exception("enrich bind result failed: %s", exc)
                enriched.setdefault("display_name", "管理員")
                enriched.setdefault("guardian_count", 0)
                enriched.setdefault("guardian_limit", 5)
                enriched.setdefault("emergency_count", 0)
                enriched.setdefault("emergency_limit", 2)
                enriched.setdefault("reminder_time", "09:00")
            return enriched

        def _owner_display_name(owner_info):
            owner_id = (owner_info or {}).get("owner_id")
            if not owner_id:
                return "家人"
            try:
                state = load_state(app.config["DATA_FILE"])
                profile = state.get("users", {}).get(owner_id, {}) or {}
                name = (profile.get("display_name") or "").strip()
                return name or "家人"
            except Exception:
                return "家人"

        def _load_group_owner_info(group_id, line_user_id=None):
            owner_info = {
                "bound": False,
                "is_owner": False,
                "owner_id": None,
                "is_active": False,
                "owner_plan": None,
            }
            if not group_id:
                return owner_info
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
                app.logger.exception("group owner_info load failed: %s", exc)
            return owner_info

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

            owner_info = _load_group_owner_info(group_id, line_user_id)
            intro_msgs = _guardian_intro_messages(owner_info, outcome.get("reply_text") if owner_info.get("bound") else None)

            sent = False
            try:
                line_bot_api.reply_message(event.reply_token, intro_msgs)
                sent = True
                app.logger.info("JoinEvent reply intro ok group=%s", (group_id or "")[:12])
            except Exception as exc:
                app.logger.exception("JoinEvent reply intro failed: %s", exc)

            if not sent and target_id:
                try:
                    line_bot_api.push_message(target_id, intro_msgs)
                    app.logger.info("JoinEvent push intro ok group=%s", (group_id or "")[:12])
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
                    registration_result = register_line_user(
                        app.config["DATA_FILE"],
                        {
                            "line_user_id": line_user_id,
                            "display_name": display_name or "",
                        },
                    )
                    if _reply_migrated_account(
                        event.reply_token, registration_result
                    ):
                        return
                    reactivate_line_push_for_follow(app.config["DATA_FILE"], line_user_id)
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
            # 2026-07-24: 成員進群也補歡迎／綁定提醒（JoinEvent 漏送時的備援）
            # 2026-07-25: 進群刷新群成員數；文案區分「群組成員」vs「已綁定守護人」
            if getattr(event.source, "type", None) != "group":
                return
            group_id = getattr(event.source, "group_id", None)
            if not group_id:
                return
            try:
                new_ids = [m.user_id for m in (event.joined.members or []) if getattr(m, "user_id", None)]
                owner_info = _load_group_owner_info(group_id)
                # 已綁定守護群：刷新群組成員數快照（不影響已綁定守護人計數）
                if owner_info.get("bound"):
                    try:
                        refresh_guardian_group_member_snapshot(
                            app.config["DATA_FILE"], group_id
                        )
                    except Exception as exc:
                        app.logger.exception("MemberJoined member snapshot refresh failed: %s", exc)
                # 未綁定：推歡迎卡，請管理員點「綁定守護群」
                # 已綁定：簡短歡迎新成員（進群 ≠ 一鍵邀請綁定）
                if not owner_info.get("bound"):
                    try:
                        line_bot_api.push_message(
                            group_id,
                            _guardian_intro_messages(owner_info),
                        )
                        app.logger.info(
                            "MemberJoined unbound intro push group=%s new=%s",
                            group_id[:12],
                            len(new_ids),
                        )
                    except Exception as exc:
                        app.logger.exception("MemberJoined intro push failed: %s", exc)
                elif new_ids:
                    try:
                        inviter_name = _owner_display_name(owner_info)
                        member_msgs = []
                        if FlexSendMessage is not None and guardian_group_member_joined_flex is not None:
                            member_msgs.append(
                                FlexSendMessage(
                                    alt_text=f"❤️ 歡迎加入 {inviter_name} 的守護群",
                                    contents=guardian_group_member_joined_flex(inviter_name),
                                )
                            )
                        else:
                            member_msgs.append(
                                TextSendMessage(
                                    text=(
                                        f"❤️ 歡迎加入 {inviter_name} 的守護群\n"
                                        "您已加入「每日平安」LINE 守護群。\n"
                                        "群內可收提醒；若要成為個人已綁定守護人，"
                                        "請請對方用「一鍵邀請」再綁一次。"
                                    )
                                )
                            )
                        line_bot_api.push_message(group_id, member_msgs)
                    except Exception as exc:
                        app.logger.exception("MemberJoined welcome flex failed: %s", exc)

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
                        f"⚠️ 「每日平安」目前無法請出超額成員（另有 {result['bot_not_admin_count']} 位）。"
                        "請管理員手動退出超額成員，或必要時把「每日平安」設為群組管理員後再試。"
                    )
                if result.get("failed") and not result.get("bot_not_admin_count"):
                    msg_lines.append(f"請出失敗:{len(result['failed'])} 位。")
                # 僅在 Bot 無管理員權限、真的踢人失敗時才提示；升級／綁定後使用者已自動是守護群管理員
                if result.get("bot_not_admin_count"):
                    msg_lines.append("💡 若需請出超額成員，可在群裡打「管理員設定」看教學（非必要開通步驟）")
                line_bot_api.push_message(group_id, TextSendMessage(text="\n".join(msg_lines)))
            except Exception:
                pass

        if PostbackEvent is not None:
            @handler.add(PostbackEvent)
            def handle_postback(event):
                line_user_id = getattr(event.source, "user_id", None)
                data = ""
                try:
                    data = str(getattr(event.postback, "data", "") or "")
                except Exception:
                    data = ""
                if not line_user_id or not data:
                    return
                reply = None
                # 每日推播「我平安」：在 LINE 內點選即寫入簽到（與 LIFF 同一套 record_checkin）
                if is_checkin_postback(data):
                    reply = handle_checkin_postback(app.config["DATA_FILE"], line_user_id, app.config)
                elif is_expiry_opt_out_postback(data):
                    reply = handle_expiry_opt_out_postback(app.config["DATA_FILE"], line_user_id)
                elif data.startswith("beta_feedback:"):
                    reply = handle_beta_feedback_postback(
                        app.config["DATA_FILE"], line_user_id, data
                    )
                elif data.startswith("sos:"):
                    parts = data.split(":", 2)
                    if len(parts) == 3:
                        result, status_code = respond_to_sos_event(
                            app.config["DATA_FILE"],
                            {
                                "line_user_id": line_user_id,
                                "action": parts[1],
                                "event_id": parts[2],
                            },
                            app.config,
                        )
                        if status_code == 200:
                            role_text = (
                                "你是主要接手人"
                                if result.get("role") == "primary"
                                else "已有守護人先接手，你已加入協助"
                                if result.get("role") == "assistant"
                                else "已記錄你的回應"
                            )
                            reply = f"✅ {role_text}\n系統已停止重複催促；請繼續聯絡本人"
                        else:
                            reply = "這筆 SOS 無法更新，可能已結案或你不是本次收件人"
                elif data.startswith("smart:"):
                    reply = handle_smart_reminder_postback(
                        app.config["DATA_FILE"], line_user_id, data, app.config
                    )
                else:
                    # 相容舊版取消警報 postback：也視為今日報平安
                    try:
                        from alerts.postback import is_alert_cancel_postback
                        if is_alert_cancel_postback(data):
                            reply = handle_checkin_postback(
                                app.config["DATA_FILE"], line_user_id, app.config
                            )
                    except Exception:
                        reply = None
                if reply:
                    items = normalize_line_reply_items(reply)
                    messages = []
                    for item in items:
                        if isinstance(item, dict) and item.get("type") == "flex":
                            if FlexSendMessage is None:
                                messages.append(
                                    TextSendMessage(
                                        text=str(item.get("altText") or "每日平安")
                                    )
                                )
                            else:
                                messages.append(
                                    FlexSendMessage(
                                        alt_text=str(item.get("altText") or "每日平安")[:400],
                                        contents=item.get("contents") or {},
                                    )
                                )
                        else:
                            messages.append(TextSendMessage(text=str(item)))
                    if messages:
                        line_bot_api.reply_message(event.reply_token, messages)

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
                        registration_result = register_line_user(
                            app.config["DATA_FILE"],
                            {
                                "line_user_id": line_user_id,
                                "display_name": display_name or "LINE 使用者",
                            },
                        )
                        if _reply_migrated_account(
                            event.reply_token, registration_result
                        ):
                            return
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

            # 一鍵邀請：略過 LIFF 大按鈕頁 → 回 Flex URI（line.me/R/share）直接開好友選擇
            if stripped in ("一鍵邀請", "一鍵邀請守護人", "邀請守護人"):
                if not line_user_id:
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text="請先加「每日平安」為好友，再點一鍵邀請。"),
                    )
                    return
                try:
                    registration_result = register_line_user(
                        app.config["DATA_FILE"],
                        {"line_user_id": line_user_id, "display_name": "LINE 使用者"},
                    )
                    if _reply_migrated_account(
                        event.reply_token, registration_result
                    ):
                        return
                except Exception as exc:
                    app.logger.exception("invite keyword register failed: %s", exc)
                if FlexSendMessage is not None and share_invite_flex is not None:
                    flex = share_invite_flex(line_user_id)
                    line_bot_api.reply_message(
                        event.reply_token,
                        FlexSendMessage(alt_text="邀請家人當守護人｜點擊傳給家人", contents=flex),
                    )
                    return
                # fallback：純文字附上原生分享網址
                if guardian_invite_share_text is not None and line_native_share_url is not None:
                    share_text = guardian_invite_share_text(line_user_id)
                    share_uri = line_native_share_url(share_text)
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(
                            text=(
                                "請點開下面連結，選一位家人傳送邀請：\n"
                                f"{share_uri}"
                            )
                        ),
                    )
                    return
                share_page = (
                    share_invite_liff_url()
                    if share_invite_liff_url
                    else "https://liff.line.me/2010848330-UAiqPPYD/liff/share-invite.html"
                )
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=f"請開啟邀請頁分享給家人：\n{share_page}"),
                )
                return

            # 需要幫忙／緊急求助：聊天室只回統一 LIFF 入口
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
                    f"👥 群組指令:守護群狀態 / 綁定守護群 / 使用說明"
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
                            enriched = _enrich_bind_result_for_flex(result, line_user_id)
                            success_msgs = [
                                FlexSendMessage(
                                    alt_text="📋 守護群資訊",
                                    contents=guardian_group_bind_confirm_flex(enriched),
                                )
                            ]
                            # 綁定成功後不要停在資訊卡：再 nudge 完成守護人／提醒設定
                            if not result.get("already_bound"):
                                nudge = (
                                    guardian_group_setup_nudge_text(
                                        enriched.get("guardian_count", 0),
                                        enriched.get("guardian_limit", 5),
                                        enriched.get("emergency_count", 0),
                                        enriched.get("emergency_limit", 2),
                                    )
                                    if guardian_group_setup_nudge_text is not None
                                    else (
                                        "🎉 守護群已建立成功！\n"
                                        "建議再完成：新增核心守護人、緊急聯絡人、設定每日提醒時間。"
                                    )
                                )
                                success_msgs.append(TextSendMessage(text=nudge))
                            line_bot_api.reply_message(event.reply_token, success_msgs)
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
                            if not result.get("already_bound") and guardian_group_setup_nudge_text is not None:
                                enriched = _enrich_bind_result_for_flex(result, line_user_id)
                                reply_text = (
                                    reply_text
                                    + "\n\n"
                                    + guardian_group_setup_nudge_text(
                                        enriched.get("guardian_count", 0),
                                        enriched.get("guardian_limit", 5),
                                        enriched.get("emergency_count", 0),
                                        enriched.get("emergency_limit", 2),
                                    )
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

                # 2) 守護群狀態（含「查看守護群／查看守護群狀態」按鈕別名）
                if stripped in ("守護群狀態", "群狀態", "狀態", "查看守護群", "查看守護群狀態"):
                    # 查詢前先刷新本群成員數，避免仍顯示綁定當下的舊快照
                    try:
                        refresh_guardian_group_member_snapshot(
                            app.config["DATA_FILE"], group_id
                        )
                    except Exception as exc:
                        app.logger.exception("status member snapshot refresh failed: %s", exc)
                    state = load_state(app.config["DATA_FILE"])
                    profile = get_profile(state, line_user_id) or {}
                    if FlexSendMessage is not None and guardian_group_status_flex is not None:
                        line_bot_api.reply_message(
                            event.reply_token,
                            FlexSendMessage(
                                alt_text="守護群狀態（群組成員數）",
                                contents=guardian_group_status_flex(profile, state),
                            ),
                        )
                    else:
                        reply_text = f"守護群數量：{len(profile.get('guardian_group_ids') or [])}"
                        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
                    return

                # 2-1) 今日平安名單：只有群組建立者/管理員可看詳細資料
                if stripped in DAILY_ROSTER_KEYWORDS:
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
                            TextSendMessage(text="使用說明:1.升級 799 → 2.建群 → 3.邀「每日平安」進群 → 4.點「綁定守護群」（升級／綁定後自動成為守護群管理員）"),
                        )
                    return

                # 4) 管理員設定 / 怎麼設管理員 / 群組設定
                if stripped in ("管理員設定", "設管理員", "怎麼設管理員", "6步驟", "群組設定"):
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

                # 未符合上述明確指令：群聊保持安靜，避免打擾家人對話。
                # LINE OA 後台的自動回應也應關閉，否則仍可能由後台另外回文字。
                if group_id:
                    return

            # 私訊：管理員可查「今天誰還沒報平安」（不需開群組提醒）
            if not group_id and stripped in DAILY_ROSTER_KEYWORDS:
                reply_text, _status = owner_today_safety_roster_text(
                    app.config["DATA_FILE"], line_user_id, config=app.config
                )
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
                return

            status = None
            if any(keyword in text for keyword in CHECKIN_KEYWORDS):
                status = record_checkin(
                    app.config["DATA_FILE"],
                    {"line_user_id": line_user_id},
                    config=app.config,
                )
                reply_items = normalize_line_reply_items(
                    build_checkin_success_text(status, config=app.config)
                )
                state = load_state(app.config["DATA_FILE"])
                profile = get_profile(state, line_user_id)
                reply_items = maybe_attach_expiry_remind(
                    reply_items,
                    profile,
                    now=current_app_time(app.config),
                    state=state,
                    data_file=app.config["DATA_FILE"],
                )
                messages = []
                for item in reply_items:
                    if isinstance(item, dict) and item.get("type") == "flex":
                        if FlexSendMessage is not None:
                            messages.append(
                                FlexSendMessage(
                                    alt_text=str(item.get("altText") or "方案提醒")[:400],
                                    contents=item.get("contents") or {},
                                )
                            )
                        else:
                            messages.append(
                                TextSendMessage(text=str(item.get("altText") or "方案提醒"))
                            )
                    else:
                        messages.append(TextSendMessage(text=str(item)))
                if should_create_support_ticket(text):
                    create_support_ticket(
                        app.config["DATA_FILE"],
                        {
                            "line_user_id": line_user_id,
                            "message": text,
                        },
                    )
                if messages:
                    line_bot_api.reply_message(event.reply_token, messages)
                return
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
                reply_text = (
                    "你的問題已經記錄下來。\n\n"
                    "📩 客服會在 1–3 個工作天內透過 LINE 官方帳號回覆。\n\n"
                    f"也可以先看常見問題：{line_liff_url('faq')}\n\n"
                    "若是立即危險，請先撥打 119。"
                )
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

    @app.post("/api/billing/cancel")
    def billing_cancel_api():
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        payload["line_user_id"] = line_user_id
        data, code = cancel_recurring_subscription(
            app.config["DATA_FILE"], payload, app.config
        )
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
                "amount": parsed.get("amount"),
                "provider": "newebpay",
            },
            app.config,
        )
        if code >= 400:
            return jsonify(data), code
        return Response("SUCCESS", mimetype="text/plain"), 200

    @app.post("/api/payment/ecpay/notify")
    def ecpay_webhook():
        form = request.form.to_dict() if request.form else (request.get_json(silent=True) or {})
        if ecpay is None:
            return Response("0|payment module missing", mimetype="text/plain"), 503
        parsed, error = ecpay.parse_notify_payload(form, app.config)
        if error:
            return Response(f"0|{error}", mimetype="text/plain"), 400
        if not ecpay.notify_success(parsed, app.config):
            return Response("1|OK", mimetype="text/plain"), 200
        data, code = confirm_payment_order(
            app.config["DATA_FILE"],
            {
                "order_id": parsed.get("order_id"),
                "transaction_id": parsed.get("transaction_id"),
                "amount": parsed.get("amount"),
                "provider": "ecpay",
            },
            app.config,
        )
        if code >= 400:
            return Response(f"0|{data.get('error', 'order update failed')}", mimetype="text/plain"), code
        return Response("1|OK", mimetype="text/plain"), 200

    @app.post("/api/payment/ecpay/period-notify")
    def ecpay_period_webhook():
        form = request.form.to_dict() if request.form else (request.get_json(silent=True) or {})
        if ecpay is None:
            return Response("0|payment module missing", mimetype="text/plain"), 503
        parsed, error = ecpay.parse_notify_payload(form, app.config)
        if error:
            return Response(f"0|{error}", mimetype="text/plain"), 400
        if not ecpay.notify_success(parsed, app.config):
            return Response("1|OK", mimetype="text/plain"), 200
        parsed.update({"status": "SUCCESS", "provider": "ecpay"})
        data, code = process_period_notification(
            app.config["DATA_FILE"], parsed, app.config
        )
        if code >= 400:
            return Response(f"0|{data.get('error', 'order update failed')}", mimetype="text/plain"), code
        return Response("1|OK", mimetype="text/plain"), 200

    @app.post("/api/payment/newebpay/period-notify")
    def newebpay_period_webhook():
        form = request.form.to_dict() if request.form else (request.get_json(silent=True) or {})
        if newebpay is None:
            return jsonify({"error": "newebpay module missing"}), 503
        parsed, error = newebpay.parse_period_payload(form, app.config)
        if error:
            return jsonify({"error": error}), 400
        data, code = process_period_notification(
            app.config["DATA_FILE"], parsed, app.config
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
        line_user_id, err = _authenticated_line_user({}, use_args=True)
        if err:
            return jsonify(err[0]), err[1]
        data = get_calendar_notes(
            app.config["DATA_FILE"], line_user_id
        )
        return jsonify(data), 200 if data.get("ok") else 403

    @app.post("/api/calendar-notes")
    def calendar_notes_post():
        payload = request.get_json(silent=True) or {}
        line_user_id, err = _authenticated_line_user(payload)
        if err:
            return jsonify(err[0]), err[1]
        payload["line_user_id"] = line_user_id
        data, code = save_calendar_note(app.config["DATA_FILE"], payload)
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
        line_user_id, err = _authenticated_line_user({}, use_args=True)
        if err:
            return jsonify(err[0]), err[1]
        data, code = onboarding_status_payload(
            app.config["DATA_FILE"], line_user_id
        )
        return jsonify(data), code

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
