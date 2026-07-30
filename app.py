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
        birthday_remind_da