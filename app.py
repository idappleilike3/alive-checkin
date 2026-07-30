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

# å®ˆè­·ç¾¤ Flex æ§‹å»ºå™¨(2026-07-21 patch 11)
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

# è¨»:patch 15 çš„å…¨åŸŸç™½åå–®æ©Ÿåˆ¶(GROUP_ADMINS / is_group_admin / deny_if_not_admin)
# å·²æ–¼ 2026-07-21 ç§»é™¤ã€‚ã€Œç®¡ç†å“¡ã€= æ¯å€‹å®ˆè­·ç¾¤çš„ owner_line_user_id(åœ¨ guardian_groups è£¡)ã€‚
# patch 16 åŠ å¼· self-intro é¡¯ç¤º owner ç‹€æ…‹ã€‚

# SOS æ±‚æ•‘æµç¨‹(2026-07-21 patch 20):3 æ¬¡ç¢ºèª + 10 åˆ†é˜å–æ¶ˆæœŸ
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


# é€¾æ™‚æœªå ±å¹³å®‰ï¼šæœƒå“¡å¯é¸ 24ï¼36ï¼48ï¼72 å°æ™‚ï¼Œé è¨­ 48 å°æ™‚ã€‚
ALLOWED_GRACE_HOURS = (24, 36, 48, 72)
DEFAULT_GRACE_HOURS = 48
# æ»¿ N å°æ™‚å¾Œå¦æœ‰çŸ­æš«å¯å–æ¶ˆé è­¦ç·©è¡ï¼ˆåˆ†é˜ï¼‰ï¼›é€šçŸ¥å¯¦éš›åœ¨ deadline + æ­¤å€¼ä¹‹å¾Œ
DEFAULT_WARNING_CANCEL_MINUTES = 15
# é€£çºŒæœªå ±å¹³å®‰æ»¿ grace_hours å¾Œï¼Œç­‰å¾…æœ¬äººå›æ‡‰çš„æ™‚é–“ï¼›ä¹‹å¾Œæ‰é€šçŸ¥ç¬¬ä¸€é †ä½ï¼Œ
# ç¬¬äºŒã€ç¬¬ä¸‰é †ä½åˆ†åˆ¥å†ä¾æ­¤åˆ†é˜æ•¸éé€²ã€‚
ALLOWED_OVERDUE_WAIT_MINUTES = (15, 30, 60)
DEFAULT_OVERDUE_WAIT_MINUTES = 15


def normalize_grace_hours(value, default=DEFAULT_GRACE_HOURS):
    """Clampï¼å°é½Šåˆ°å…è¨±çš„ 24ï¼36ï¼48ï¼72 å°æ™‚ã€‚"""
    try:
        hours = int(value)
    except (TypeError, ValueError):
        return int(default)
    if hours in ALLOWED_GRACE_HOURS:
        return hours
    # å°±è¿‘ï¼›ä¸¦åˆ—æ™‚åå‘ç”¢å“é è¨­ 48
    return min(ALLOWED_GRACE_HOURS, key=lambda h: (abs(h - hours), abs(h - int(default))))


def normalize_overdue_wait_minutes(value, default=DEFAULT_OVERDUE_WAIT_MINUTES):
    """å°é½Šåˆ° 15ï¼30ï¼60 åˆ†é˜ï¼›ç„¡æ•ˆå€¼ä½¿ç”¨ 15 åˆ†é˜é è¨­ã€‚"""
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
    # èˆŠç‰ˆç›¸å®¹æ¬„ä½ï¼›æ–°æ”¿ç­–å›ºå®šç‚º 0ï¼Œé‚€è«‹ä¸å†å»¶é•·é«”é©—ã€‚
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
    # èˆŠç‰ˆç›¸å®¹æ¬„ä½ï¼›ç¾è¡Œæ”¿ç­–ä¸è¨­è‡ªå‹•åˆªé™¤æœŸé™ï¼Œæ’ç¨‹æœƒæ¸…é™¤èˆŠå€’æ•¸ä¸¦é‚„åŸèˆŠå°å­˜ã€‚
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
    # è©¦ç”¨ï¼æ–¹æ¡ˆåˆ°æœŸæé†’ï¼ˆâ‰¤3 å¤©æˆ–å·²åˆ°æœŸï¼‰ï¼›opt-out å¾Œä¸å†å‚¬
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

# è©¦ç”¨ï¼ä»˜è²»æ–¹æ¡ˆå‰©é¤˜ â‰¤ æ­¤å¤©æ•¸ï¼ˆå«å·²åˆ°æœŸï¼‰æ‰æ¨åˆ°æœŸæé†’ï¼›æ¯æ—¥æœ€å¤šä¸€æ¬¡
EXPIRY_REMIND_WITHIN_DAYS = 3
WEEKDAY_SHORT_ZH = ("ä¸€", "äºŒ", "ä¸‰", "å››", "äº”", "å…­", "æ—¥")

# æ­£å¼æ–°æœƒå“¡èˆ‡æ—¢æœ‰ free éæ¸¡æœƒå“¡çš†ç‚ºä¸€æ¬¡æ€§ 14 å¤©é«”é©—ã€‚
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
# ä¾æ¯æ—¥æé†’æ¬¡æ•¸çš„é è¨­æ™‚æ®µ(ä½¿ç”¨è€…æœªè‡ªè¨‚æ™‚ä½¿ç”¨)
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
    # æœ€çµ‚æ–¹æ¡ˆç¸½è¦½ï¼ˆ2026-07ï¼‰ï¼š
    # core_guardian_alert_limitï¼æ ¸å¿ƒå®ˆè­·äººï¼›emergency_contact_limitï¼ç·Šæ€¥è¯çµ¡äººï¼›
    # contact_limitï¼å…©è€…åˆè¨ˆï¼ˆç›¸å®¹èˆŠæ¬„ä½ï¼‰ï¼›daily_remindersï¼LINE ç§èŠé è­¦ï¼æ—¥ï¼›
    # ä¸è³£ç°¡è¨Šï¼å…æï¼å¥½å‹åœ°åœ–ï¼è»Œè·¡ï¼›199ï¼15 åˆ†é˜ï¼›399ï¼1/3 å°æ™‚ï¼›799ï¼1/3/6/8 å°æ™‚
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
        # 14 å¤©å…è²»é«”é©—å›ºå®šæ¯”ç…§ 199 æ´»è‘—ç‰ˆï¼ˆæœˆæ–¹æ¡ˆï¼‰ã€‚
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
    # ç”¢å“æ”¿ç­–ï¼šSOS å…¨æ–¹æ¡ˆé–‹æ”¾ï¼›799 è³£ã€Œæ›´å®Œæ•´å®ˆè­·ã€ï¼ˆæ›´å¤šæ ¸å¿ƒï¼ç·Šæ€¥ã€æ—©ä¸­æ™šã€å®ˆè­·ç¾¤ç­‰ï¼‰
    "paid_199": {"amount": 199, "billing_cycle": "monthly", "duration_days": 30, "display_name": "199 å¹³å®‰ç‰ˆ(æœˆ)", "tagline": "2 ä½æ ¸å¿ƒå®ˆè­·äººï¼‹15 åˆ†é˜å®‰å…¨å®ˆè­·ï¼ˆæ¯æ—¥ 2 æ¬¡ï¼‰"},
    "paid_199_year": {"amount": 1990, "billing_cycle": "yearly", "duration_days": 365, "display_name": "199 å¹³å®‰ç‰ˆ(å¹´)", "tagline": "ä»˜ 10 å€‹æœˆé€ 2 å€‹æœˆï¼š3 ä½æ ¸å¿ƒå®ˆè­·äººï¼‹æ¯æ—¥ 2 æ¬¡ LINE é è­¦"},
    "paid_399": {"amount": 399, "billing_cycle": "monthly", "duration_days": 30, "display_name": "399 å®‰å¿ƒç‰ˆ(æœˆ)", "tagline": "5 ä½æ ¸å¿ƒå®ˆè­·äººï¼‹å®‰å…¨å®ˆè­· 1ï¼3 å°æ™‚"},
    "paid_399_year": {"amount": 3990, "billing_cycle": "yearly", "duration_days": 365, "display_name": "399 å®‰å¿ƒç‰ˆ(å¹´)", "tagline": "ä»˜ 10 å€‹æœˆé€ 2 å€‹æœˆï¼š7 ä½æ ¸å¿ƒå®ˆè­·äººï¼‹å®‰å…¨å®ˆè­· 1ï¼3 å°æ™‚"},
    "paid_799": {"amount": 799, "billing_cycle": "monthly", "duration_days": 30, "display_name": "799 å®ˆè­·ç‰ˆ(æœˆ)", "tagline": "æ›´å®Œæ•´å®ˆè­·ï¼š10 ä½æ ¸å¿ƒï¼‹æ—©ä¸­æ™šï¼‹å®ˆè­·ç¾¤"},
    "paid_799_year": {"amount": 7990, "billing_cycle": "yearly", "duration_days": 365, "display_name": "799 å®ˆè­·ç‰ˆ(å¹´)", "tagline": "ä»˜ 10 å€‹æœˆé€ 2 å€‹æœˆï¼š15 ä½æ ¸å¿ƒï¼‹æœ€å¤š 3 å€‹å®ˆè­·ç¾¤"},
}

RICH_MENU_COMMANDS = [
    "ä»Šæ—¥ç°½åˆ°",
    "ç¶å®šå®ˆè­·äºº",
    "æˆ‘çš„ç‹€æ…‹",
    "æŸ¥çœ‹æ–¹æ¡ˆ",
    "å•èˆ‡ç­”",
    "è¯çµ¡å®¢æœ",
]

CHECKIN_KEYWORDS = {"ç°½åˆ°", "æ‰“å¡", "å ±å¹³å®‰", "ä»Šæ—¥ç°½åˆ°", "æˆ‘å¹³å®‰", "âœ… æˆ‘å¹³å®‰", "ä»Šæ—¥å·²å¹³å®‰"}
CONTACT_KEYWORDS = {"ç¶å®šå®ˆè­·äºº", "è¯çµ¡äºº", "ç·Šæ€¥è¯çµ¡äºº", "å¡«è¯çµ¡äºº", "ä¿®æ”¹é›»è©±", "å®ˆè­·äºº"}
STATUS_KEYWORDS = {"ç‹€æ…‹", "æˆ‘çš„ç‹€æ…‹", "æŸ¥è©¢ç´€éŒ„"}
# ç®¡ç†å“¡æŸ¥è©¢ä»Šæ—¥èª°é‚„æ²’å ±å¹³å®‰ï¼ˆç§è¨Šæˆ–å®ˆè­·ç¾¤çš†å¯ï¼‰
DAILY_ROSTER_KEYWORDS = {
    "ä»Šæ—¥ç‹€æ…‹",
    "ä»Šæ—¥å¹³å®‰ç‹€æ…‹",
    "èª°æ²’å ±å¹³å®‰",
    "æœªå ±å¹³å®‰",
    "èª°é‚„æ²’ç°½åˆ°",
    "ä»Šå¤©èª°é‚„æ²’å ±å¹³å®‰",
    "èª°é‚„æ²’å ±å¹³å®‰",
}
# å®ˆè­·ç¾¤é€šçŸ¥åå¥½ï¼šé€¾æœŸï¼å¹³å®‰ç‹€æ…‹é è¨­åªç§è¨Šæ ¸å¿ƒå®ˆè­·äººï¼›ç¾¤çµ„ç‚ºé¸ç”¨ï¼ˆé è¨­é—œï¼‰
DEFAULT_GUARDIAN_GROUP_PREFERENCES = {
    "notify_private_guardians": True,
    "notify_group_on_overdue": False,
    "notify_admin_only": True,
    "daily_admin_summary": False,
}
PLAN_KEYWORDS = {"æ–¹æ¡ˆ", "åƒ¹æ ¼", "æ”¶è²»", "å‡ç´š", "æŸ¥çœ‹æ–¹æ¡ˆ", "å¤šå°‘éŒ¢"}
FAQ_KEYWORDS = {"å•èˆ‡ç­”", "FAQ", "å¸¸è¦‹å•é¡Œ"}
SUPPORT_KEYWORDS = {"å®¢æœ", "äººå·¥", "å¹«åŠ©", "æ‰¾ä¸åˆ°", "å•é¡Œ", "è¯çµ¡å®¢æœ"}
INVOICE_KEYWORDS = {"ç™¼ç¥¨", "æ”¶æ“š", "ä»˜æ¬¾è­‰æ˜"}
GROUP_KEYWORDS = {"å®ˆè­·ç¾¤", "ç¾¤çµ„", "æ‹‰äºº"}
ALERT_CHANNEL_KEYWORDS = {"é›»è©±", "ç°¡è¨Š", "å…¨æ¸ é“", "å…¨é€šé“", "è‡ªå‹•æ’¥è™Ÿ"}
LARGE_TEXT_KEYWORDS = {"å¤§å­—", "è€äººæ¨¡å¼", "å­—é«”å¤ªå°", "é•·è¼©æ¨¡å¼"}


def line_status_summary(status):
    if not status:
        return "ç›®å‰é‚„æ²’æœ‰æŸ¥åˆ°ä½ çš„ç°½åˆ°ç´€éŒ„ã€‚è«‹å…ˆé»ã€Œä»Šæ—¥ç°½åˆ°ã€ï¼Œå»ºç«‹ç¬¬ä¸€ç­†å¹³å®‰ç´€éŒ„ã€‚"
    last_checkin = status.get("last_check_in") or "å°šæœªç°½åˆ°"
    contacts = len(status.get("contacts") or [])
    contact_limit = status.get("contact_limit", 1)
    plan = status.get("plan") or "trial"
    reminder_times = status.get("reminder_times") or [status.get("reminder_time") or "12:00"]
    if not isinstance(reminder_times, list):
        reminder_times = [str(reminder_times)]
    times_text = "ã€".join(str(t) for t in reminder_times if t)
    return (
        "ä½ çš„è¿‘æœŸç‹€æ…‹å¦‚ä¸‹ï¼š\n"
        f"æœ€å¾Œç°½åˆ°ï¼š{last_checkin}\n"
        f"ç›®å‰æ–¹æ¡ˆï¼š{plan}\n"
        f"å®ˆè­·äººï¼š{contacts}/{contact_limit} ä½\n"
        f"æ¯æ—¥æé†’æ™‚é–“ï¼š{times_text or '12:00'}\n\n"
        "è‹¥å®ˆè­·äººé‚„æ²’ç¶å®šï¼Œè«‹é»ã€Œç¶å®šå®ˆè­·äººã€ï¼ŒæŠŠ LINE é‚€è«‹é€£çµå‚³çµ¦èº«é‚Šé‡è¦çš„äººã€‚"
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
    """æ–¹æ¡ˆé  LIFF ç›´é€£ï¼ˆé¿å…è·³å‡º LINE é–‹ç€è¦½å™¨ï¼Œè·Ÿå…¶ä»–æŒ‰éˆ•ä¸€è‡´ï¼‰ã€‚"""
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
    """Force-open-in-LINE URL (https://line.me/R/app/...) â€” more reliable on Android Chrome.

    Use ``?`` not ``/?`` â€” the slash-before-query form can make LIFF/OAuth return 400.
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
    """Public /invite landing â€” showsã€Œç”¨ LINE é–‹å•Ÿã€when opened outside LINE."""
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
        "å¯ä»¥ï¼Œå‡ç´šæ–¹æ¡ˆè«‹é»é€™è£¡ï¼š\n"
        f"{pricing_url}\n\n"
        "è£¡é¢æœƒçœ‹åˆ° 199ï¼399ï¼799 çš„æœˆè²»ã€å¹´è²»èˆ‡å®ˆè­·æ¬Šç›Šã€‚"
    )


def line_auto_reply_text(text, status=None):
    text = (text or "").strip()
    if any(keyword in text for keyword in CHECKIN_KEYWORDS):
        if status and status.get("is_today_checked"):
            return build_checkin_success_text(status)
        return "ä»Šå¤©å¹³å®‰ç°½åˆ°æˆåŠŸã€‚ç³»çµ±å·²å¹«ä½ ç•™ä¸‹ç´€éŒ„ï¼Œå®ˆè­·äººä¸ç”¨æ“”å¿ƒã€‚"
    if any(keyword in text for keyword in CONTACT_KEYWORDS):
        return (
            "ç¶å®šå®ˆè­·äººè¨­å®šèªªæ˜\n\n"
            "è«‹å…ˆç¶å®šè‡³å°‘ 1 ä½å®ˆè­·äººï¼Œç·Šæ€¥æ™‚ç³»çµ±æ‰èƒ½é€é LINE é€šçŸ¥å°æ–¹ã€‚\n\n"
            "æ“ä½œæ–¹å¼ï¼š\n"
            "1. é»ã€Œä¸€éµé‚€è«‹å®ˆè­·äººã€\n"
            "2. è¼¸å…¥å°æ–¹æš±ç¨±\n"
            "3. ç”¨ LINE åˆ†äº«é‚€è«‹é€£çµ\n"
            "4. å°æ–¹é»åŒæ„å¾Œï¼Œå°±èƒ½æ”¶åˆ°æ¸¬è©¦æé†’\n\n"
            "å®ˆè­·äººç„¡é ˆè¨»å†Šï¼Œä¹Ÿèƒ½æ¥æ”¶è­¦å ±ã€‚"
        )
    if any(keyword in text for keyword in STATUS_KEYWORDS):
        return line_status_summary(status)
    if any(keyword in text for keyword in PLAN_KEYWORDS):
        return line_plan_message()
    if any(keyword in text for keyword in INVOICE_KEYWORDS):
        return (
            "ç›®å‰å°šæœªæä¾›ç·šä¸Šé›»å­ç™¼ç¥¨ï¼æ”¶æ“šæŸ¥è©¢ã€‚\n"
            "è‹¥éœ€è¦ä»˜æ¬¾è­‰æ˜ï¼Œè«‹é€éå®¢æœç•™è¨€ï¼Œæˆ‘å€‘æœƒäººå·¥å”åŠ©æ ¸å°è¨‚å–®ã€‚"
        )
    if any(keyword in text for keyword in GROUP_KEYWORDS):
        return (
            "å®ˆè­·ç¾¤åŠŸèƒ½èªªæ˜ï¼š\n"
            "å®ˆè­·ç¾¤é©åˆå®¶äººã€è¦ªå‹æˆ–ç¤¾å€é—œæ‡·å°çµ„ä¸€èµ·æ¥æ”¶å¹³å®‰ç‹€æ…‹ã€‚\n"
            "æœ‰æ•ˆçš„ 799 æœˆè²»æœƒå“¡å¯å»ºç«‹ 1 ç¾¤ï¼Œå¹´è²»æœƒå“¡æœ€å¤šå¯å»ºç«‹ 3 ç¾¤ã€‚\n"
            "è«‹æŠŠã€Œæ¯æ—¥å¹³å®‰ã€å®˜æ–¹å¸³è™ŸåŠ å…¥ç¾¤çµ„å¾Œï¼Œç”±æ–¹æ¡ˆæœ¬äººè¼¸å…¥ã€Œé»æˆ‘ç¶å®šå®ˆè­·ç¾¤ã€ã€‚è‹¥è³‡æ ¼ä¸ç¬¦ï¼Œã€Œæ¯æ—¥å¹³å®‰ã€æœƒèªªæ˜åŸå› ä¸¦é€€å‡ºç¾¤çµ„ã€‚\n"
            "ã€Œæ¯æ—¥å¹³å®‰ã€åªè™•ç†ç°½åˆ°ã€é è­¦èˆ‡å®ˆè­·æŒ‡ä»¤ï¼Œä¸æœƒæŠŠä¸€èˆ¬èŠå¤©å…§å®¹å­˜é€²æœƒå“¡è³‡æ–™ã€‚"
        )
    if any(keyword in text for keyword in ALERT_CHANNEL_KEYWORDS):
        return (
            "ç·Šæ€¥é€šçŸ¥æ–¹å¼èªªæ˜ï¼š\n"
            "ç›®å‰ä»¥ LINE é€šçŸ¥å·²ç¶å®šã€Œå®ˆè­·äººã€ç‚ºä¸»ï¼ˆé€¾æœŸæœªå ±å¹³å®‰ã€SOSã€å®‰å…¨å®ˆè­·ï¼‰ã€‚\n"
            "å®ˆè­·ç¾¤åƒ…ç”¨æ–¼å®‰å…¨äº‹ä»¶é€šçŸ¥ã€‚\n"
            "ã€Œç·Šæ€¥è¯çµ¡äººã€æ˜¯é›»è©±å‚™æ´ï¼ˆæ‰‹å‹•æ’¥æ‰“ï¼‰ï¼Œä¸æœƒè‡ªå‹•ç¾¤ç™¼ã€‚"
        )
    if any(keyword in text for keyword in LARGE_TEXT_KEYWORDS):
        return (
            "å¤§å­—æ¨¡å¼è¦åŠƒä¸­ï¼š\n"
            "é€™å€‹åŠŸèƒ½æœƒè®“é•·è¼©çœ‹åˆ°æ›´å¤§çš„æ–‡å­—ã€æ›´å°‘çš„é¸é …ï¼Œä»¥åŠæ›´æ˜é¡¯çš„ç°½åˆ°æŒ‰éˆ•ã€‚\n"
            "ç›®å‰å¯å…ˆä½¿ç”¨æ‰‹æ©Ÿç€è¦½å™¨æˆ– LINE å…§å»ºçš„æ–‡å­—ç¸®æ”¾åŠŸèƒ½ã€‚"
        )
    if any(keyword in text for keyword in FAQ_KEYWORDS):
        faq_url = line_liff_url("faq")
        pricing_url = line_liff_url("pricing")
        return (
            "å¸¸è¦‹å•é¡Œï¼š\n"
            "ã€Œæ¯æ—¥å¹³å®‰ã€å¹«ä½ æ¯æ—¥å ±å¹³å®‰ï¼›é€¾æ™‚æœªå ±æˆ– SOS æ™‚ï¼Œç”¨ LINE ç§è¨Šé€šçŸ¥å·²ç¶å®šçš„æ ¸å¿ƒå®ˆè­·äººã€‚\n\n"
            "Qï¼šæœªå ±å¹³å®‰å¤šä¹…æœƒé€šçŸ¥ï¼Ÿ\n"
            "Aï¼šå¯åœ¨æœƒå“¡ä¸­å¿ƒé¸ 24ï¼36ï¼48ï¼72 å°æ™‚ï¼ˆé è¨­ 48 å°æ™‚ï¼‰ã€‚æ»¿è¨­å®šæ™‚æ•¸æ‰å†æé†’æœ¬äººï¼›15 åˆ†é˜ä»æœªå›å ±ï¼Œä¹‹å¾Œä¾ç¬¬ä¸€ã€ç¬¬äºŒã€ç¬¬ä¸‰é †ä½é€æ­¥é€šçŸ¥å®ˆè­·äººã€‚\n\n"
            "Qï¼šæ ¸å¿ƒå®ˆè­·äººè·Ÿç·Šæ€¥è¯çµ¡äººå·®åœ¨å“ªï¼Ÿ\n"
            "Aï¼šæ ¸å¿ƒï¼å¯æ”¶ LINE é€šçŸ¥ï¼›ç·Šæ€¥è¯çµ¡äººï¼é›»è©±å‚™æ´ï¼Œä¸æœƒè‡ªå‹•æ¨æ’­ï¼ç°¡è¨Šã€‚\n\n"
            "Qï¼šå®ˆè­·äººä¸€å®šè¦è¨»å†Šå—ï¼Ÿ\n"
            "Aï¼šä¸ç”¨ï¼Œå°æ–¹åŠ å…¥å®˜æ–¹å¸³è™Ÿä¸¦é»é‚€è«‹åŒæ„å³å¯ã€‚\n\n"
            f"å®Œæ•´å•èˆ‡ç­”ï¼š{faq_url}\n"
            f"æŸ¥çœ‹æ–¹æ¡ˆï¼š{pricing_url}"
        )
    if any(keyword in text for keyword in SUPPORT_KEYWORDS):
        faq_url = line_liff_url("faq")
        return (
            "å®¢æœåœ¨é€™è£¡ã€‚è«‹ç›´æ¥åœ¨æ­¤ LINE ç•™è¨€ä½ çš„å•é¡Œï¼Œæˆ‘å€‘æœƒå”åŠ©ä½ è¨­å®šç°½åˆ°ã€å®ˆè­·äººèˆ‡æ–¹æ¡ˆã€‚\n\n"
            "ğŸ“© å·²æ”¶åˆ°çš„å•é¡Œæœƒåœ¨ 1â€“3 å€‹å·¥ä½œå¤©å…§å›è¦†ã€‚\n\n"
            f"ä¹Ÿå¯ä»¥å…ˆçœ‹å•èˆ‡ç­”ï¼š{faq_url}\n\n"
            "æé†’ï¼šè‹¥æ˜¯ç«‹å³å±éšªæˆ–é†«ç™‚ç·Šæ€¥ç‹€æ³ï¼Œè«‹å…ˆæ’¥æ‰“ 119ã€‚"
        )
    return (
        "æˆ‘çœ‹åˆ°äº†ã€‚ä½ å¯ä»¥é»ä¸‹æ–¹é¸å–®ï¼šä»Šæ—¥ç°½åˆ°ã€ç¶å®šå®ˆè­·äººã€æˆ‘çš„ç‹€æ…‹ã€æŸ¥çœ‹æ–¹æ¡ˆã€å•èˆ‡ç­”ã€è¯çµ¡å®¢æœã€‚\n\n"
        "è‹¥æ˜¯ç«‹å³å±éšªï¼Œè«‹å„ªå…ˆæ’¥æ‰“ 119ã€‚"
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
            "è³‡æ–™å¯èƒ½å› é‡å•Ÿéºå¤±è«‹æ›ç£ç¢Ÿã€‚"
            "Render Free æœ¬æ©Ÿç£ç¢Ÿæœƒåœ¨ redeployï¼é‡å•Ÿæ¸…ç©ºï¼›"
            "è«‹å‡ç´š Starter å¾Œæ› Persistent Diskï¼ˆ/var/dataï¼‰ä¸¦è¨­ DATA_FILE=/var/data/state.jsonï¼Œ"
            "æˆ–è¨­å®š DATABASE_URL ä½¿ç”¨å¤–éƒ¨ Postgresã€‚"
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
    """è¯çµ¡äººåŸºæœ¬è³‡æ–™ï¼šå§“å +ï¼ˆæ‰‹æ©Ÿæˆ–ä¿¡ç®±ï¼‰."""
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
                # Empty durable row â€” still authoritative once seeded intentionally.
                return pg_state
            return _hydrate_state({})
        except Exception:
            # PG down â†’ last-resort local cache (may be stale after redeploy)
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
    already-Taipei local â€” either matching today counts as checked-in.
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
    """True when user already å ±å¹³å®‰ for the Taipei calendar day.

    Prefer history[]; also accept last_check_in landing on today in Taipei
    (covers UTC/Taipei mismatch that caused é¬¼æ‰“ç‰† re-prompts).
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
    """Asia/Taipei é¡¯ç¤ºï¼š7/25ï¼ˆå…­ï¼‰"""
    try:
        return f"{int(dt.month)}/{int(dt.day)}ï¼ˆ{WEEKDAY_SHORT_ZH[dt.weekday()]}ï¼‰"
    except Exception:
        return ""


def format_hm(dt):
    try:
        return dt.strftime("%H:%M")
    except Exception:
        return ""


def checkin_blessing_text(now):
    """ç¯€æ—¥ç¥ç¦å„ªå…ˆï¼Œå¦å‰‡è¼ªæ’­æ­£å‘çŸ­å¥ï¼ˆholidays_twï¼‰ã€‚"""
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
    return "æ¯ä¸€å¤©çš„å¹³å®‰ï¼Œéƒ½æ˜¯çµ¦å®¶äººæœ€å¥½çš„ç¦®ç‰©ã€‚"


def next_checkin_reminder_info(profile, config=None, now=None):
    """Next daily å ±å¹³å®‰ reminder slot after now (or tomorrow first slot if already checked).

    Product rule: once å ±å¹³å®‰æˆåŠŸ for Taipei today, remaining same-day slots are skipped
    â€” next_reminder jumps to tomorrow's first slot.
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
                    "next_reminder_text": f"ä¸‹æ¬¡æé†’ {format_md_weekday(candidate)} {slot}",
                    "next_reminder_label": f"ä»Šå¤© {slot}",
                }
    # Already checked today, or all of today's slots passed â†’ tomorrow first
    hour, minute = _parse_hm(times[0])
    tomorrow = (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return {
        "next_reminder_at": tomorrow.isoformat(timespec="seconds"),
        "next_reminder_time": times[0],
        "next_reminder_text": f"ä¸‹æ¬¡æé†’ {format_md_weekday(tomorrow)} {times[0]}",
        "next_reminder_label": f"æ˜å¤© {times[0]}",
    }


def build_checkin_success_text(status, *, now=None, config=None):
    """å ±å¹³å®‰æˆåŠŸå›è¦†ï¼šæ˜ŸæœŸã€å ±åˆ°æ™‚é–“ã€ç¥ç¦èªã€ä¸‹æ¬¡æé†’ã€‚"""
    now = now or current_app_time(config)
    duplicate = bool(status.get("already_checked_today") or status.get("is_duplicate"))
    header = "âœ… ä»Šå¤©å·²ç¶“å ±éå¹³å®‰äº†ï¼Œä¸ç”¨å†é»ä¸€æ¬¡ã€‚" if duplicate else "âœ… å ±å¹³å®‰æˆåŠŸï¼"
    check_dt = parse_last_checkin(status.get("last_check_in")) or now
    if getattr(check_dt, "tzinfo", None) is not None:
        try:
            check_dt = check_dt.astimezone(ZoneInfo("Asia/Taipei")).replace(tzinfo=None)
        except Exception:
            check_dt = check_dt.replace(tzinfo=None)
    blessing = checkin_blessing_text(now)
    lines = [
        header,
        f"ğŸ“… ä»Šå¤©æ˜¯ {format_md_weekday(now)}ï½œå ±åˆ°æ™‚é–“ {format_hm(check_dt)}",
        f"ğŸ’Œ {blessing}",
    ]
    next_text = str(status.get("next_reminder_text") or "").strip()
    if next_text:
        lines.append(f"â° {next_text}" if next_text.startswith("ä¸‹æ¬¡æé†’") else f"â° ä¸‹æ¬¡æé†’ {next_text}")
    return "\n".join(lines)


def membership_expiry_info(profile, now=None):
    """è©¦ç”¨ï¼ä»˜è²»åˆ°æœŸè³‡è¨Šï¼›ç„¡éœ€æé†’æ™‚å› Noneã€‚"""
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
            "label": "21 å¤©å°æ¸¬",
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
            "label": "14 å¤©å®‰å¿ƒé«”é©—",
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
        # åƒ…å°ã€Œæ›¾åˆ°æœŸé™ç´šã€æˆ–æ›¾é–‹éè©¦ç”¨çš„æœƒå“¡å‚¬ä¿ƒï¼Œé¿å…å…¨æ–° free è¢«æ´—ç‰ˆ
        if not (
            str(profile.get("plan_expired_at") or "").strip()
            or str(profile.get("trial_started_at") or "").strip()
        ):
            return None
        return {
            "plan": plan,
            "label": "æœªè¨‚é–±",
            "days_left": 0,
            "expired": True,
            "near": True,
        }
    return None


def should_offer_expiry_remind(profile, now=None):
    """æ˜¯å¦æ‡‰æ¨æ–¹æ¡ˆåˆ°æœŸæé†’ï¼ˆopt-outï¼ç•¶æ—¥å·²æ¨éå‰‡å¦ï¼‰ã€‚"""
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
    """åˆ°æœŸï¼å³å°‡åˆ°æœŸ Flexï¼šç¹¼çºŒæ¯æ—¥å•å€™ â†’ æ–¹æ¡ˆé ï¼›ä¸å†æé†’æˆ‘ â†’ opt-out postbackã€‚"""
    now = now or current_app_time({})
    info = membership_expiry_info(profile, now) or {}
    label = info.get("label") or "æ–¹æ¡ˆ"
    days = info.get("days_left")
    if info.get("expired") or (isinstance(days, int) and days <= 0):
        title = f"ä½ çš„{label}å·²åˆ°æœŸ"
        body = (
            "çºŒç”¨å¾Œå¯ç¹¼çºŒæ¯æ—¥å•å€™èˆ‡å®ˆè­·æé†’ï¼Œå®¶äººä¹Ÿèƒ½å®‰å¿ƒã€‚"
            "å‡ç´šæ™‚è£œå·®é¡å³å¯ï¼Œä¸å¿…é‡è¨­è¯çµ¡äººï¼›å°æ–¹ä¹Ÿæœ‰ 7 å¤©è€ƒæ…®æœŸå¯æ…¢æ…¢æ±ºå®šã€‚"
        )
    else:
        title = f"ä½ çš„{label}å³å°‡åˆ°æœŸ"
        body = (
            f"é‚„å‰©ç´„ {days} å¤©ã€‚çºŒç”¨å¾Œå¯ç¹¼çºŒæ¯æ—¥å•å€™ï¼Œå®ˆè­·ä¸ä¸­æ–·ã€‚"
            "å‡ç´šè£œå·®é¡å³å¯ï¼›å¦æœ‰ 7 å¤©è€ƒæ…®æœŸï¼Œæ–¹ä¾¿å®¶äººä¸€èµ·æ±ºå®šã€‚"
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
                        "text": "æ–¹æ¡ˆæé†’",
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
                            "label": "å‡ç´šå¾Œç¹¼çºŒæ¯æ—¥å•å€™",
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
                            "label": "ä¸å†æé†’æˆ‘",
                            "data": "action=expiry_opt_out",
                            "displayText": "ä¸å†æé†’æˆ‘æ–¹æ¡ˆåˆ°æœŸ",
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
        return "è«‹å…ˆåŠ å…¥æ¯æ—¥å¹³å®‰å¥½å‹ã€‚"
    state = load_state(data_file)
    profile = get_profile(state, line_user_id)
    profile["expiry_remind_opt_out"] = True
    save_state(data_file, state)
    return "å¥½çš„ï¼Œä¹‹å¾Œä¸æœƒå†æé†’æ–¹æ¡ˆåˆ°æœŸã€‚è‹¥è¦çºŒç”¨ï¼Œéš¨æ™‚é»ã€ŒæŸ¥çœ‹æ–¹æ¡ˆã€å³å¯ã€‚"


def maybe_attach_expiry_remind(messages, profile, *, now=None, state=None, data_file=None):
    """è‹¥ç¬¦åˆæ¢ä»¶ï¼Œé™„åŠ åˆ°æœŸ Flex ä¸¦æ¨™è¨˜ä»Šæ—¥å·²æ¨ï¼ˆå¯«å…¥ profileï¼›å‘¼å«ç«¯è² è²¬ saveï¼‰ã€‚"""
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
    """æŠŠ postbackï¼é—œéµå­—å›è¦†æ­£è¦æˆ listï¼ˆtext str æˆ– flex dictï¼‰ã€‚"""
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
            "æ­¤å¸³è™Ÿå·²ç§»è½‰åˆ°æ–°ç‰ˆ LINE ç™»å…¥ï¼ŒèˆŠå…¥å£å·²åœç”¨ã€‚\n"
            "è«‹ç”±æ–°ç‰ˆå…¥å£ç¹¼çºŒä½¿ç”¨ï¼š\n"
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
            {**DEFAULT_PROFILE, "line_user_id": line_user_id, "display_name": "LINE ä½¿ç”¨è€…"},
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
    """ä¾æ–¹æ¡ˆå›å‚³å¯é¸å®‰å…¨å®ˆè­·æ™‚æ•¸ï¼ˆå°æ™‚ï¼‰ï¼›0.25 ä»£è¡¨ 15 åˆ†é˜ã€‚"""
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
    """ä¾æé†’æ¬¡æ•¸å›å‚³é è¨­æ™‚æ®µ:1â†’12:00ã€2â†’12/18ã€3â†’12/18/22ã€‚"""
    try:
        count = int(count or 1)
    except (TypeError, ValueError):
        count = 1
    count = max(1, min(3, count))
    return list(DEFAULT_REMINDER_TIMES_BY_COUNT.get(count, DEFAULT_REMINDER_TIMES_BY_COUNT[1]))


def normalize_reminder_times(raw_times, max_count=1):
    """é©—è­‰ä¸¦æ­£è¦åŒ– HH:MM æ¸…å–®,å»é‡å¾Œä¾æ™‚é–“æ’åº,æˆªæ–·è‡³æ–¹æ¡ˆä¸Šé™ã€‚"""
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
    """å–å¾—ä½¿ç”¨è€…æé†’æ™‚æ®µ:è‡ªè¨‚ reminder_times > å–®ä¸€ reminder_time > æ–¹æ¡ˆé è¨­ã€‚"""
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
    """å¯«å…¥ reminder_times,ä¸¦åŒæ­¥ç¬¬ä¸€å€‹æ™‚æ®µåˆ° reminder_time(ç›¸å®¹èˆŠæ¬„ä½)ã€‚"""
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


# === D01: äº’å‹•ç‹€æ…‹(é˜²æ¯æ—¥é‡è¤‡ç›¸åŒå…§å®¹) ===
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
    """è®€å–æˆ–åˆå§‹åŒ– profile.interaction_stateã€‚"""
    if "interaction_state" not in profile or not isinstance(profile.get("interaction_state"), dict):
        profile["interaction_state"] = default_interaction_state()
    # è£œé½Šç¼ºæ¼æ¬„ä½(å¾€å¾ŒåŠ æ–°æ¬„ä½æ™‚ä¸æœƒå£èˆŠè³‡æ–™)
    defaults = default_interaction_state()
    for k, v in defaults.items():
        if k not in profile["interaction_state"]:
            profile["interaction_state"][k] = v
    return profile["interaction_state"]


def contact_is_bound_guardian(contact, owner_line_user_id=None):
    """å°æ–¹æ˜¯å¦å·²é€é LINE é‚€è«‹ï¼ˆinvite_fromï¼‰ç¶å®šï¼åŒæ„æˆç‚ºå®ˆè­·äººã€‚

    è¡¨å–®æ–°å¢è¯çµ¡äººæ™‚ payload å¸¸å¸¶æœ¬äºº line_user_idï¼ˆåƒ…ä¾› API èªè­‰ï¼‰ï¼Œ
    ä¸å¯æŠŠã€Œæœ¬äºº ID èª¤å¯«é€²è¯çµ¡äººã€ç•¶æˆå·²ç¶å®šå®ˆè­·äººã€‚
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
    """å¯æ”¶å®‰å…¨å®ˆè­·ï¼SOS ç­‰ LINE æ¨æ’­çš„ã€Œå®ˆè­·äººã€ã€‚

    æ’é™¤ï¼šç·Šæ€¥è¯çµ¡äººï¼ˆåƒ…é›»è©±å‚™æ´ï¼‰ã€æœ¬äºº IDã€æœªç¶å®šã€æœªå‹¾é¸ line é€šçŸ¥ã€‚
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
    """æ˜¯å¦å·²å¡«å¯«å®ˆè­·äººåŸºæœ¬è³‡æ–™ï¼ˆå§“åï¼‹é—œä¿‚ï¼‰ã€‚"""
    if not isinstance(contact, dict):
        return False
    return bool((contact.get("name") or "").strip() and (contact.get("relationship") or "").strip())


def scrub_self_line_ids_on_contacts(profile):
    """æ¸…é™¤èª¤æŠŠæœ¬äºº line_user_id å¯«é€²è¯çµ¡äººçš„å‡ç¶å®šï¼ˆè¡¨å–® add æ±¡æŸ“ï¼‰ã€‚å›å‚³æ˜¯å¦æœ‰è®Šæ›´ã€‚"""
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
        # æœ¬äºº ID ä¸æ‡‰å‡ºç¾åœ¨å®ˆè­·äºº LINE æ¬„ï¼›çœŸæ­£ç¶å®šåªèµ° bind_emergency_contact
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
    """åŒä¸€å€‹ LINE å¸³è™Ÿåœ¨å–®ä¸€æœƒå“¡åä¸‹åªèƒ½ä¿ç•™ä¸€ç­†è¯çµ¡é—œä¿‚ã€‚"""
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
    """ä½¿ç”¨è€…æ˜¯å¦å·²æœ‰è‡³å°‘ 1 ä½å®ˆè­·äººï¼ˆè³‡æ–™æˆ– LINE ç¶å®šï¼‰ã€‚"""
    contacts = (profile or {}).get("contacts") or []
    owner = str((profile or {}).get("line_user_id") or "").strip()
    return any(
        contact_has_guardian_profile(c) or contact_is_bound_guardian(c, owner)
        for c in contacts
    )


def profile_has_bound_line_guardian(profile):
    """æ˜¯å¦å·²æœ‰ â‰¥1 ä½å¯ LINE é€šçŸ¥çš„å®ˆè­·äººï¼ˆå®‰å…¨å®ˆè­·ï¼SOS é–˜é–€ï¼›ä¸å«ç·Šæ€¥è¯çµ¡äººï¼‰ã€‚"""
    contacts = (profile or {}).get("contacts") or []
    owner = str((profile or {}).get("line_user_id") or "").strip()
    return any(contact_is_notifiable_line_guardian(c, owner) for c in contacts)


def pending_guardian_invite_count(state, inviter_line_user_id, now=None):
    """åˆ†äº«é‚€è«‹åªç®—ç­‰å¾…ä¸­ï¼›å—é‚€äººå¡«è³‡æ–™ä¸¦åŒæ„å¾Œæ‰ç®—å®Œæˆç¶å®šã€‚"""
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
        # é¦–æ¬¡ç¶å®šä¸å¼·è¿« 799 å¡«æ»¿ 3 æ¬¡ï¼›399ï¼799 æœªé¸æ™‚çš†é è¨­ 12:00ã€18:00ã€‚
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
    """è‹¥å·²æœ‰å®ˆè­·äººä½†æ——æ¨™æœªå¯«å…¥ï¼Œè£œä¸Š durable flagï¼ˆå›å‚³æ˜¯å¦æœ‰è®Šæ›´ï¼‰ã€‚"""
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
    """åˆ¤æ–·æ˜¯å¦è©²å½ˆå®ˆè­·äººå®Œæˆåº¦æç¤ºå¡ã€‚

    è¦å‰‡:
    - å·²æ˜¯ 399/799 æœƒå“¡æ‰é¡¯ç¤º(å…è²»/é«”é©—åªå¼·åˆ¶ 1 ä½,ä¸å†å‚¬)
    - contact_count >= limit â†’ ä¸é¡¯ç¤º
    - contact_count < limit:
      - æ²’å•é OR last_prompted_at è¶…é 1 å¤©å‰ â†’ é¡¯ç¤º
      - guardian_reminder_preference == 'tomorrow' ä¸” snoozed_until > now â†’ ä¸é¡¯ç¤º
      - guardian_reminder_preference == 'dismiss_7d' ä¸” snoozed_until > now â†’ ä¸é¡¯ç¤º
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
    if last and last > now_iso:  # safety:æœªä¾†æ™‚é–“å°±ä¸é¡¯ç¤º
        return False
    return True



def trial_bonus_days(profile):
    """èˆŠç‰ˆç›¸å®¹æ¬„ä½ï¼›é‚€è«‹æ ¸å¿ƒå®ˆè­·äººä¸å†å¢åŠ é«”é©—å¤©æ•¸ã€‚"""
    return 0


def trial_total_days(profile):
    """å…¬é–‹æˆ–éæ¸¡é«”é©—å›ºå®š 14 å¤©ï¼Œä¸å› é‚€è«‹å»¶é•·ã€‚"""
    return PUBLIC_TRIAL_DAYS


def ensure_membership_trial(profile, now=None, source="public_trial"):
    """çµ¦äºˆç›®å‰æ”¿ç­–çš„ä¸€æ¬¡æ€§ 14 å¤©é«”é©—ï¼›åŒä¸€ç‰ˆæœ¬æ°¸ä¸é‡å•Ÿã€‚"""
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
    """Cron å¯é‡è·‘é·ç§»ï¼šåŒä¸€æ™‚é–“æ‰¹æ¬¡çµ¦ legacy free ä¸€æ¬¡éæ¸¡é«”é©—ã€‚"""
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
                    # æ—¢æœ‰ä»˜è²»æœƒå“¡ä¸å¯åœ¨æœªä¾†åˆ°æœŸå¾Œè¢«èª¤åˆ¤ç‚º legacy free å†é ˜ä¸€æ¬¡ã€‚
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
            # åˆ°æœŸæœƒå“¡ä¸æ˜¯ legacy freeï¼›Cron é‡è·‘ä¸å¾—å†æ¬¡ç™¼æ”¾é«”é©—ã€‚
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
    """æœƒå“¡æ¬Šç›Šæ˜¯å¦æœ‰æ•ˆï¼›free åƒ…ä»£è¡¨æœªè¨‚é–±ï¼ŒSOS å®‰å…¨æ”¿ç­–å¦è¡Œåˆ¤æ–·ã€‚"""
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
                "message": "é€™æ˜¯æ¸¬è©¦é€šçŸ¥ï¼šå®ˆè­·ç¾¤ç¶å®šèˆ‡æ¨æ’­æµç¨‹å·²å®Œæˆ",
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
        "message": "é€™æ˜¯æ¸¬è©¦é€šçŸ¥ï¼šå®ˆè­·ç¾¤ç¶å®šèˆ‡æ¨æ’­æµç¨‹å·²å®Œæˆ",
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
        "message": f"é€™æ˜¯æ¸¬è©¦é€šçŸ¥ï¼ˆ{action.upper()}ï¼‰ï¼šæœªè§¸ç™¼çœŸæ­£ç·Šæ€¥æ±‚åŠ©æˆ–æŒçºŒå®šä½ã€‚",
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
            "display_name": str(profile.get("display_name") or "æœªå‘½åæœƒå“¡"),
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
        "notice": "å°é–‰æ¸¬è©¦ä¸æœƒå»ºç«‹è¨‚å–®ï¼Œä¹Ÿä¸æœƒè‡ªå‹•æ‰£æ¬¾",
    }


def _beta_feedback_task(cohort, day):
    common = {
        1: "å®Œæˆä¸€æ¬¡ã€Œæˆ‘å¹³å®‰ã€ï¼Œç¢ºèªæœ¬äººèˆ‡å®ˆè­·äººéƒ½çœ‹åˆ°æ­£ç¢ºçµæœ",
        7: "æª¢æŸ¥æé†’æ™‚é–“ã€é€¾æ™‚é€šçŸ¥èˆ‡å®ˆè­·äººæ”¶è¨Šæ˜¯å¦æ¸…æ¥š",
        14: "æ¸¬è©¦ SOS çš„é€å‡ºã€å–æ¶ˆåŠæ”¶ä»¶äººæç¤º",
        21: "æäº¤æ•´é«”å¿ƒå¾—ï¼Œå‘Šè¨´æˆ‘å€‘æœ€æƒ³ä¿ç•™èˆ‡æ”¹å–„çš„åŠŸèƒ½",
    }
    if int(day or 0) in common:
        return common[int(day)]
    if str(cohort or "").upper() == "B799":
        return "æ¸¬è©¦å®¶åº­ç¾¤çµ„ã€å¤šäººå®ˆè­·ã€å®‰å…¨å®ˆè­·æˆ– SOSï¼Œä¸¦ç¢ºèªé€šçŸ¥å°è±¡æ­£ç¢º"
    return "ä½¿ç”¨ä¸€æ¬¡å ±å¹³å®‰ã€æé†’ã€å®ˆè­·äººæˆ– SOSï¼Œç•™æ„æ“ä½œæ˜¯å¦å®¹æ˜“ç†è§£"


def build_beta_feedback_flex(profile, day):
    """Build one daily beta question with five explicit reply paths."""
    day = max(1, min(BETA_TRIAL_DAYS, int(day or 1)))
    cohort = str((profile or {}).get("beta_cohort") or "B399").upper()
    buttons = [
        ("ä½¿ç”¨æ­£å¸¸", "normal", "#168C65"),
        ("ç™¼ç¾å•é¡Œ", "issue", "#C2413A"),
        ("ä½¿ç”¨å¿ƒå¾—", "insight", "#3178C6"),
        ("ä¸æœƒæ“ä½œ", "help", "#8A5A16"),
        ("ç¨å¾Œæé†’", "later", "#6B7280"),
    ]
    return {
        "type": "flex",
        "altText": f"æ¯æ—¥å¹³å®‰å°æ¸¬ Day {day} ä½¿ç”¨ç‹€æ³è©¢å•",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#168C65",
                "contents": [
                    {"type": "text", "text": f"21 å¤©å°æ¸¬ Day {day}", "color": "#FFFFFF",
                     "weight": "bold", "size": "xl"},
                    {"type": "text", "text": "ä»Šå¤©ä½¿ç”¨ä¸Šæœ‰é‡åˆ°å•é¡Œå—ï¼Ÿ",
                     "color": "#EAF8F1", "margin": "sm"},
                ],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "ä»Šæ—¥å»ºè­°ä»»å‹™", "weight": "bold",
                     "color": "#168C65"},
                    {"type": "text", "text": _beta_feedback_task(cohort, day),
                     "wrap": True, "margin": "sm", "color": "#33443F"},
                    {"type": "text", "text": "é»é¸ä¸‹æ–¹æœ€ç¬¦åˆçš„ç‹€æ³å³å¯å›å ±",
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
        return "æ­¤å›å ±åªæä¾›çµ¦ç›®å‰çš„å°æ¸¬æœƒå“¡"
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
            "å·²è¨˜éŒ„ã€Œç™¼ç¾å•é¡Œã€ã€‚è«‹ç›´æ¥åœ¨é€™å€‹èŠå¤©å®¤å‚³é€ï¼š\n"
            "1. å•é¡Œæˆªåœ–\n2. ç™¼ç”Ÿæ™‚é–“\n3. æ“ä½œæ­¥é©Ÿ\n"
            "4. æ‰‹æ©Ÿå‹è™Ÿ\n5. LINE ç‰ˆæœ¬"
        )
    if kind == "insight":
        return "å·²è¨˜éŒ„ã€Œä½¿ç”¨å¿ƒå¾—ã€ã€‚è«‹ç›´æ¥å‘Šè¨´æˆ‘å€‘å“ªè£¡å¥½ç”¨ã€å“ªè£¡æƒ³æ”¹å–„"
    if kind == "help":
        return "å·²è¨˜éŒ„ã€Œä¸æœƒæ“ä½œã€ã€‚è«‹å‘Šè¨´æˆ‘å€‘å¡åœ¨å“ªå€‹ç•«é¢ï¼Œå®¢æœæœƒå”åŠ©ä½ "
    if kind == "later":
        return "å¥½çš„ï¼Œä»Šå¤©ä¸å†é‡è¤‡æ¨æ’­ï¼›ä½ æ–¹ä¾¿æ™‚å†å›åˆ°é€™å€‹èŠå¤©å®¤å‘Šè¨´æˆ‘å€‘"
    return "è¬è¬å›å ±ï¼Œå·²è¨˜éŒ„ä»Šå¤©ä½¿ç”¨æ­£å¸¸"


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
    return f"{raw[:3]}â€¦{raw[-3:]}"


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
        "notice": "æœ¬å·¥å…·åªè¨˜éŒ„æ—¢æœ‰ LINE æ¸¬è©¦è­‰æ“šï¼Œä¸æœƒä¸»å‹•ç™¼é€è¨Šæ¯",
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
        "display_name": str(profile.get("display_name") or "å°æ¸¬æœƒå“¡")[:80],
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
                order["display_name"] = "å·²åˆªé™¤æœƒå“¡"
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
    """è¨˜éŒ„å®ˆè­·äººç¶å®šï¼Œä½†ä¸æä¾›ä»»ä½•é«”é©—å¤©æ•¸çå‹µã€‚"""
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
        "trial": "14 å¤©å®‰å¿ƒé«”é©—",
        "free": "æœªè¨‚é–±",
        "paid_199": "199 æœˆè²»",
        "paid_199_year": "199 å¹´è²»",
        "paid_399": "399 æœˆè²»",
        "paid_399_year": "399 å¹´è²»",
        "paid_799": "799 æœˆè²»",
        "paid_799_year": "799 å¹´è²»",
    }.get(plan, plan)


def compute_plan_expires_at(profile):
    """å›å‚³æ–¹æ¡ˆåˆ°æœŸ ISO å­—ä¸²ï¼ˆè©¦ç”¨çµæŸæ—¥æˆ–ä»˜è²» paid_untilï¼‰ï¼›æœªè¨‚é–±å›ç©ºå­—ä¸²ã€‚"""
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
    # èˆŠè³‡æ–™ç›¸å®¹ï¼šæ²’æœ‰ trial_end æ™‚ï¼Œä»¥ trial_started_at + 14 å¤©è¨ˆç®—ã€‚
    started = parse_datetime(profile.get("trial_started_at"))
    if not started:
        started = datetime.now()
    return (started + timedelta(days=trial_total_days(profile))).isoformat(timespec="seconds")


def plan_expires_text(profile):
    plan = str(profile.get("plan") or "trial")
    label = plan_type_label(profile)
    expires = compute_plan_expires_at(profile)
    if plan == "free":
        return f"{label}ï½œç„¡åˆ°æœŸæ—¥"
    if not expires:
        return f"{label}ï½œå°šæœªè¨­å®šåˆ°æœŸæ—¥"
    try:
        dt = parse_datetime(expires) or datetime.fromisoformat(str(expires)[:19])
        date_part = dt.strftime("%Y/%m/%d")
    except Exception:
        date_part = str(expires)[:10].replace("-", "/")
    if plan == "trial":
        days = trial_days_left(profile)
        return f"{label}ï½œåˆ°æœŸ {date_part}ï¼ˆå‰© {days} å¤©ï¼‰"
    return f"{label}ï½œåˆ°æœŸ {date_part}"


def compute_streak_days(history, today):
    """è¨ˆç®—é€£çºŒç°½åˆ°å¤©æ•¸(ä»¥ Asia/Taipei ç‚ºä¸»)ã€‚

    è¦å‰‡:
    - ä»Šå¤©æœ‰ç°½åˆ° â†’ å¾ä»Šå¤©å¾€å‰é€£çºŒç®—
    - ä»Šå¤©æ²’ç°½åˆ°ä½†æ˜¨å¤©æœ‰ç°½åˆ° â†’ å¾æ˜¨å¤©å¾€å‰ç®—(ä»£è¡¨æ˜¨å¤©é‚„å¹³å®‰)
    - ä¸­é–“ç¼ºä¸€å¤©å°±ä¸­æ–·
    - history é‡è¤‡æ—¥æœŸä¸å½±éŸ¿(set åŒ–)
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
    # æ­£è¦åŒ– contactsï¼šè£œ contact_roleï¼Œä¸¦å»æ‰æœƒèˆ‡ã€Œæ ¸å¿ƒï¼ä¸€èˆ¬ã€æ··æ·†çš„ role æ¬„
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
        status_text = "å·²æé†’æœ¬äººï¼Œç­‰å¾…å¹³å®‰å›å ±"
        status_class = "warning"
    elif overdue:
        status_text = "å·²é€²å…¥å®ˆè­·äººé †ä½é€šçŸ¥"
        status_class = "danger"
    elif not last:
        status_text = "é‚„æ²’æœ‰ç°½åˆ°ç´€éŒ„"
        status_class = "gray"
    elif deadline and remaining_ms <= 6 * 60 * 60 * 1000:
        status_text = "å¿«åˆ°æé†’æ™‚é–“äº†"
        status_class = "warning"
    else:
        status_text = "ç‹€æ…‹æ­£å¸¸"
        status_class = "highlight"

    _reminder_times = reminder_times_for_profile(profile) or ["12:00"]
    _next_reminder = next_checkin_reminder_info(profile, now=now)
    guardian_groups = []
    today_safety_roster = None
    if state is not None:
        # é›™å‘å°é½Šï¼šé¿å…ç¾¤å·²ç¶å®šä½† profile.guardian_group_ids éºå¤± â†’ LIFF é¡¯ç¤ºã€Œå°šæœªç¶å®šã€
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
            "å·²å ±å¹³å®‰" if peer and profile_is_today_checked(peer, now=now)
            else "å°šæœªå ±å¹³å®‰"
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
                    "area": str(row.get("area") or "æœªæä¾›ä½ç½®")[:40],
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
        # Legacy field retained for old clients; user-facing "ä¸€èˆ¬" guardians no
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
                "role": "æ ¸å¿ƒå®ˆè­·äºº",
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
        "trial": "14 å¤©å®‰å¿ƒé«”é©—",
        "free": "æœªè¨‚é–±",
        "paid_199": "å·²å‡ç´š 199 æœˆè²»",
        "paid_199_year": "å·²å‡ç´š 199 å¹´è²»",
        "paid_399": "å·²å‡ç´š 399 æœˆè²»",
        "paid_399_year": "å·²å‡ç´š 399 å¹´è²»",
        "paid_799": "å·²å‡ç´š 799 æœˆè²»",
        "paid_799_year": "å·²å‡ç´š 799 å¹´è²»",
    }
    return labels.get(plan, plan)


def _trial_days_text(profile):
    if str(profile.get("membership_source") or "") == "beta":
        beta_end = parse_datetime(profile.get("beta_ends_at"))
        if not beta_end:
            return "21 å¤©å°æ¸¬ï¼ˆå°šæœªè¨­å®šåˆ°æœŸæ—¥ï¼‰"
        now = current_app_time({})
        comparable_now, comparable_end = _comparable_datetimes(now, beta_end)
        seconds = (comparable_end - comparable_now).total_seconds()
        days = max(0, int((seconds + 86399) // 86400))
        return f"21 å¤©å°æ¸¬å‰© {days} å¤©" if days > 0 else "21 å¤©å°æ¸¬å·²çµæŸ"
    plan = str(profile.get("plan") or "trial")
    if plan == "trial":
        days = trial_days_left(profile)
        return f"é«”é©—å‰© {days} å¤©" if days > 0 else "é«”é©—å·²çµæŸ"
    if plan == "free":
        return "æœªè¨‚é–±ï¼ˆç„¡é«”é©—å€’æ•¸ï¼‰"
    return "å·²å‡ç´šï¼ˆéè©¦ç”¨ï¼‰"


def _upgrade_status(profile):
    plan = str(profile.get("plan") or "trial")
    payment = str(profile.get("payment_status") or "")
    if plan.startswith("paid"):
        active = payment == "active" or paid_membership_is_active(profile)
        return f"{_membership_label(profile)}ï½œ{'ä½¿ç”¨ä¸­' if active else paymentLabel_zh(payment)}"
    if plan == "trial":
        days = trial_days_left(profile)
        return f"é«”é©—ä¸­ï½œå‰© {days} å¤©" if days > 0 else "é«”é©—å·²çµæŸï½œå°šæœªå‡ç´š"
    if plan == "free":
        return "æœªè¨‚é–±ï½œå°šæœªå‡ç´š"
    return _membership_label(profile)


def paymentLabel_zh(status):
    return {
        "trial": "è©¦ç”¨ä¸­",
        "free": "æœªè¨‚é–±",
        "active": "å·²ä»˜æ¬¾",
        "pending": "å¾…ä»˜æ¬¾",
        "expired": "å·²åˆ°æœŸ",
        "failed": "ä»˜æ¬¾å¤±æ•—",
        "cancelled": "å·²å–æ¶ˆ",
    }.get(status, status or "æœªä»˜è²»")


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
        "æ‚¨",
        "LINE ä½¿ç”¨è€…",
        "LINEä½¿ç”¨è€…",
        "LINE æœƒå“¡",
        "LINEæœƒå“¡",
        "LINE è¯çµ¡äºº",
        "LINEè¯çµ¡äºº",
        "ä½¿ç”¨è€…",
    }
)


def is_placeholder_display_name(name) -> bool:
    s = str(name or "").strip()
    if s in _WELCOME_NAME_PLACEHOLDERS:
        return True
    # ç›¸å®¹ã€ŒLINEä½¿ç”¨è€…ã€ç­‰ç„¡ç©ºç™½å¯«æ³•
    return s.replace(" ", "").replace("\u3000", "") in {
        "LINEä½¿ç”¨è€…",
        "LINEæœƒå“¡",
        "LINEè¯çµ¡äºº",
    }


def fetch_line_profile_dict(token: str, line_user_id: str) -> dict | None:
    """ç”¨ Messaging API å– profileï¼›å¤±æ•—å› Noneã€‚"""
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
    """ç¢ºä¿ profile æœ‰çœŸå¯¦ displayNameï¼›å¿…è¦æ™‚æ‰“ LINE profile API ä¸¦å¯«å›ã€‚"""
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
    profile["display_name"] = "LINE ä½¿ç”¨è€…"
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
                "message": "ä½ å·²ä½¿ç”¨éå…è²»é«”é©—ï¼›è«‹é¸æ“‡æ­£å¼æ–¹æ¡ˆç¹¼çºŒä½¿ç”¨å ±å¹³å®‰ã€‚",
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
                "cohort_full": "é€™ä¸€çµ„å°æ¸¬åé¡å·²æ»¿",
                "already_in_other_cohort": "ä½ å·²åŠ å…¥å¦ä¸€å€‹å°æ¸¬çµ„åˆ¥",
                "free_eligibility_already_used": "ä½ å·²ä½¿ç”¨éå…è²»é«”é©—æˆ–å°æ¸¬è³‡æ ¼",
            }
            return {
                "ok": False,
                "error": reason,
                "message": messages.get(reason, "ç„¡æ³•åŠ å…¥å°æ¸¬"),
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
    """å¾ line-bot-sdk Profile / dict å–å‡ºå¯ç”¨çš„ displayNameã€‚"""
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
    """Follow /ã€Œé–‹å§‹ã€å…±ç”¨ï¼šå„ªå…ˆ LINE profileï¼Œå…¶æ¬¡ hint / æœ¬åœ° usersï¼Œå¤±æ•—å› Noneã€‚"""
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
    """å ±å¹³å®‰æˆåŠŸå¾Œï¼Œç§è¨Šå·²å®Œæˆ LINE ç¶å®šçš„æ ¸å¿ƒå®ˆè­·äººã€‚"""
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
    owner_name = str(profile.get("display_name") or "æ‚¨çš„è¦ªå‹").strip()
    message = (
        f"âœ… {owner_name} å·²å ±å¹³å®‰\n"
        f"æ™‚é–“ï¼š{checked_at.strftime('%Y/%m/%d %H:%M')}\n"
        "ä»Šæ—¥å¹³å®‰å›å ±å·²å®Œæˆï¼Œè«‹æ”¾å¿ƒã€‚"
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
    area = area[:40] or "æœªæä¾›ä½ç½®"
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
    # Product rule: ä»Šæ—¥å·²å ±å¹³å®‰ â†’ ç•¥éåŒæ—¥å‰©é¤˜æ’ç¨‹æé†’ï¼ˆæ¨™è¨˜æ‰€æœ‰ slotsï¼‰
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
            message = f"{profile.get('display_name') or 'ä½¿ç”¨è€…'} å·²å–æ¶ˆæœ¬æ¬¡å¹³å®‰é è­¦ï¼Œæœ¬æ¬¡ç‚ºèª¤è§¸ï¼Œè«‹ä¸ç”¨æ“”å¿ƒã€‚"
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
        "display_name": profile.get("display_name") or "LINE æœƒå“¡",
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
            "message": "å®‰å…¨ä»˜æ¬¾æ¨¡çµ„æœªè¼‰å…¥ï¼›è¨‚å–®å·²å»ºç«‹ï¼Œè«‹ç¨å¾Œå†è©¦ã€‚",
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
    # å‡ç´šå«å®ˆè­·ç¾¤æ–¹æ¡ˆï¼šè‡ªå‹•æŠŠå»ºç«‹è€…è¨­ç‚ºå®ˆè­·ç¾¤ç®¡ç†å“¡ï¼ˆä¸å¿…å†èµ°ç®¡ç†å“¡è¨­å®šï¼‰
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

        # è©¦ç”¨åˆ°æœŸ â†’ æœªè¨‚é–±ï¼›è³‡æ–™èˆ‡å®ˆè­·é—œä¿‚ä¸è‡ªå‹•åˆªé™¤
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
            # ç„¡åˆ°æœŸæ—¥ï¼šä¿ç•™ç¾æ³ï¼Œé¿å…èª¤é™ç´šä¸¦è®“ä½¿ç”¨è€…ä»¥ç‚ºå¥½å‹è¢«æ¸…æ‰
            continue
        comparable_until, comparable_now = _comparable_datetimes(paid_until, now)
        if comparable_until >= comparable_now:
            continue
        # å·²éæœŸï¼šæš«åœä»˜è²»æœå‹™ï¼Œä½†ä¿ç•™æ‰€æœ‰ç¶å®šç›´åˆ°é©—è­‰å¾Œç”³è«‹è§£é™¤
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
    """è©¦ç”¨ï¼ä»˜è²»åˆ°æœŸï¼šé™ç‚º freeï¼Œä¸¦åœ¨åŒä¸€è³‡æ–™åº«äº¤æ˜“ä¿ç•™å¸³æˆ¶è³‡æ–™ã€‚"""
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
                "æ¯æ—¥å•å€™æ–¹æ¡ˆå³å°‡åˆ°æœŸ"
                if milestone not in (0, 14, 21)
                else "æ¯æ—¥å•å€™æ–¹æ¡ˆä»Šå¤©åˆ°æœŸ"
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
                message.get("altText") or "æ–¹æ¡ˆåˆ°æœŸæé†’",
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
            message["altText"] = "14 å¤©å®‰å¿ƒé«”é©—å·²é€²è¡Œ 7 å¤©"
        elif day == 12:
            message["altText"] = "14 å¤©å®‰å¿ƒé«”é©—é‚„å‰© 2 å¤©"
        else:
            message["altText"] = "14 å¤©å®‰å¿ƒé«”é©—ä»Šå¤©åˆ°æœŸ"
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
                    message.get("altText") or "14 å¤©é«”é©—æé†’",
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
    """å®ˆè­·äºº vs ç·Šæ€¥è¯çµ¡äººã€‚

    åªç”¨ ``contact_role``ï¼ˆæˆ–æ˜ç¢ºçš„ type / kindï¼‰ã€‚
    **ä¸å¯**è®€ ``role``ï¼šè©²æ¬„åœ¨ bound_guardians è¡¨ç¤ºã€Œæ ¸å¿ƒï¼ä¸€èˆ¬ã€å±¤ç´šï¼Œ
    è‹¥èª¤ç•¶æˆ contact_role æœƒæŠŠå®ˆè­·äººåˆ—æ¿¾ç©ºï¼Œå‡ºç¾ countâ‰¥1 ä½†åˆ—è¡¨ç©ºç™½ã€‚
    """
    if not isinstance(contact, dict):
        return "guardian"
    raw = str(
        contact.get("contact_role")
        or contact.get("type")
        or contact.get("kind")
        or ""
    ).strip().lower()
    if raw in ("emergency", "emergency_contact", "è¯çµ¡äºº", "ç·Šæ€¥è¯çµ¡äºº"):
        return "emergency"
    return "guardian"


def normalize_contact(contact, index):
    """æ­£è¦åŒ–å®ˆè­·äººè¯çµ¡äººè³‡æ–™,åŒ…å«ç©©å®š id èˆ‡æ™‚é–“æˆ³ã€‚

    è¦å‰‡:
    - id ä¸€æ—¦å»ºç«‹å°±ä¸è®Š(æ²’çµ¦å°±ç”¨ f"contact-{index+1}")
    - is_primary å¾ contact.get("is_primary") è®€,æ²’çµ¦å°±çœ‹ priority æ˜¯å¦ = 1
    - binding_status: unbound / pending / accepted / declined
    - line_user_id è·Ÿ line_id åŒç¾©(æ–°æ¬„ä½å„ªå…ˆ)
    - created_at èˆ‡ updated_at ç‚º ISO 8601 å­—ä¸²
    - contact_role: guardianï¼ˆæ ¸å¿ƒå®ˆè­·äººï¼‰| emergencyï¼ˆè¯çµ¡äººï¼‰
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
        # LINE æš±ç¨±ï¼ˆç¶å®šæ™‚è‡ª profile å¯«å…¥ï¼›åˆ—è¡¨ä¸»æ¨™ç±¤ç”¨ï¼Œå‹¿é¡¯ç¤º raw userIdï¼‰
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
        # LINE é ­åƒï¼ˆç¶å®šï¼register å¯«å…¥ï¼›åˆ—è¡¨ UI é¡¯ç¤ºç”¨ï¼Œä¸æ˜¯å¾Œå°å…§éƒ¨ UIDï¼‰
        "picture_url": str(contact.get("picture_url") or contact.get("pictureUrl") or "").strip(),
    }


def validate_contact_payload(contact, existing=None, contact_limit=10):
    """é©—è­‰å–®ç­† contact payloadã€‚å›å‚³ (ok, errors_list, cleaned_contact_or_None)ã€‚

    è¦å‰‡:
    - name å¿…å¡«
    - relationship å¿…å¡«
    - phone OR email è‡³å°‘ä¸€å€‹
    - phone æ ¼å¼åŸºæœ¬é©—è­‰(å°ç£æ‰‹æ©Ÿ 09 é–‹é ­æˆ–åœ‹éš›æ ¼å¼)
    - email æ ¼å¼åŸºæœ¬é©—è­‰
    - ä¸å…è¨±å®Œå…¨é‡è¤‡(åŒ user æ—¢æœ‰ contacts æ¯”å° name+phone+email)
    - è¶…éæ–¹æ¡ˆä¸Šé™ â†’ contact_limit_exceeded
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

    # phone format: æ¥å— 09xxxxxxxx(å°ç£)ã€9xxxxxxxx(å» 0)ã€+8869xxxxxxxxã€8869xxxxxxxx
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

    # duplicate check (æ’é™¤è‡ªå·± by id)
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

    # æ³¨æ„ï¼špayload çš„ line_user_id å¤šåŠæ˜¯ã€Œæœƒå“¡æœ¬äººã€èªè­‰æ¬„ï¼Œä¸æ˜¯å®ˆè­·äºº LINEã€‚
    # è¡¨å–®æ–°å¢ï¼ç·¨è¼¯ä¸å¯ç”±æ­¤å¯«å…¥ LINE ç¶å®šï¼›çœŸæ­£ç¶å®šåªèµ° bind_emergency_contact(invite_from)ã€‚
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
    """å›å‚³ç•¶ä¸‹æ™‚é–“çš„ ISO 8601 å­—ä¸²(Asia/Taipei)ã€‚"""
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
    """ç”¨å°æ–¹ LINE æœƒå“¡ profile è£œé½Šè¯çµ¡äºº picture_urlï¼ˆç¼ºåœ–æ™‚ï¼‰ã€‚å›å‚³æ˜¯å¦è®Šæ›´ã€‚"""
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
    """ç”¨å°æ–¹ LINE æœƒå“¡ profile è£œé½Šè¯çµ¡äºº display_nameï¼line_display_nameã€‚å›å‚³æ˜¯å¦è®Šæ›´ã€‚"""
    if not isinstance(contact, dict):
        return False
    lid = get_contact_line_id(contact)
    if not lid:
        return False
    current = str(
        contact.get("line_display_name") or contact.get("display_name") or ""
    ).strip()
    if current and not is_placeholder_display_name(current):
        # æ­£è¦åŒ–é›™æ¬„ä½
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
                continue  # æ ¸å¿ƒï¼ä¸€èˆ¬ï¼Œä¸å¯å¯«å›æ··æ·† contact_role
            if key not in normalized and value not in (None, ""):
                normalized[key] = value
        normalized["contact_role"] = resolve_contact_role(
            {"contact_role": contact.get("contact_role") or normalized.get("contact_role")}
        )
        if contact.get("contact_role") != normalized["contact_role"] or "contact_role" not in contact:
            changed = True
        if enrich_contact_peer_picture(state, normalized):
            # å›å¯«åˆ°åŸå§‹åˆ—ï¼Œä¹‹å¾Œåˆ—è¡¨ï¼æœƒå“¡ä¸­å¿ƒå°±èƒ½çœ‹åˆ°é ­åƒ
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
    """æ–°å¢å–®ä¸€è¯çµ¡äºº,å›å‚³ (status_code, response_dict)ã€‚"""
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
                    f"ç·Šæ€¥è¯çµ¡äººå·²é”æ–¹æ¡ˆä¸Šé™ {emergency_limit} ä½ã€‚"
                    f"å‡ç´šå¯æ–°å¢æ›´å¤šç·Šæ€¥è¯çµ¡äººã€‚"
                ),
            }, 400
    elif len(guardians) >= core_limit:
        return {
            "error": "contact_limit_exceeded",
            "code": "contact_limit",
            "contact_limit": core_limit,
            "current_count": len(guardians),
            "message": (
                f"ä½ å·²ç¶“æœ‰ {len(guardians)} ä½æ ¸å¿ƒå®ˆè­·äººå›‰ï¼ˆç›®å‰æ–¹æ¡ˆä¸Šé™ {core_limit} ä½ï¼‰ã€‚"
                f"å‡ç´šå¯æ–°å¢æ›´å¤šå®ˆè­·äººã€‚"
            ),
        }, 400
    if len(existing) >= limit:
        return {
            "error": "contact_limit_exceeded",
            "code": "contact_limit",
            "contact_limit": limit,
            "current_count": len(existing),
            "message": (
                f"è¯çµ¡äººåé¡å·²æ»¿ï¼ˆç›®å‰æ–¹æ¡ˆä¸Šé™ {limit} ä½ï¼‰ã€‚"
                f"å‡ç´šå¯æ–°å¢æ›´å¤šè¯çµ¡äººã€‚"
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
    # è¡¨å–®è·¯å¾‘ï¼šç»ä¸å†™å…¥ LINE ç»‘å®šæ ï¼ˆé¿å…æŠŠæœ¬äºº line_user_id å½“æˆå®ˆæŠ¤äººï¼‰
    cleaned["line_user_id"] = ""
    cleaned["line_id"] = ""
    cleaned["binding_status"] = "unbound"
    cleaned["consent_status"] = "pending"
    # primary é‚è¼¯:è¨­ç‚ºä¸»è¦æ™‚è‡ªå‹•å–æ¶ˆå…¶ä»–
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
    """æ›´æ–°å–®ä¸€è¯çµ¡äºº,å›å‚³ (status_code, response_dict)ã€‚"""
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
    # åˆä½µ:ä¿ç•™ id è·Ÿ created_at,å…¶ä»–å¾ payload
    merged_payload = dict(contact_payload)
    merged_payload["id"] = contact_id
    merged_payload["created_at"] = existing[idx].get("created_at") or iso_now()
    # é©—è­‰(æ’é™¤è‡ªå·±)
    other = [c for i, c in enumerate(existing) if i != idx]
    ok, errors, cleaned = validate_contact_payload(merged_payload, existing=other)
    if not ok:
        return {"error": "validation_failed", "fields": errors}, 400
    now = iso_now()
    cleaned["id"] = contact_id
    cleaned["created_at"] = merged_payload["created_at"]
    cleaned["updated_at"] = now
    # ä¿ç•™æ—¢æœ‰ LINE é‚€è«‹ç¶å®šæ¬„ï¼›è¡¨å–®ç·¨è¼¯ä¸å¯è¦†å¯«ï¼ä¸å¯æŠŠæœ¬äºº ID å¯«å…¥
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
    # primary é‚è¼¯
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
            # Don't downgrade accepted â†’ unbound when client omits bind state.
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
    """Replace contact list but merge bind fields per id â€” never wipe LINE binds."""
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
                f"ä½ å·²ç¶“æœ‰ {limit} ä½å®ˆè­·äººå›‰ï¼ˆç›®å‰æ–¹æ¡ˆä¸Šé™ï¼‰ã€‚"
                f"å‡ç´šå¯æ–°å¢æ›´å¤šå®ˆè­·äººã€‚"
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


ALREADY_BOUND_MESSAGE = "é€™ä½å¥½å‹å·²ç¶“ç¶å®šï¼Œä¸èƒ½é‡è¤‡ç¶å®šï¼›è«‹è¿”å›ä¸¦æ”¹é¸å…¶ä»–å¥½å‹"
CONTACT_LIMIT_MESSAGE = "å°æ–¹çš„å®ˆè­·äººåé¡å·²æ»¿ï¼Œè«‹è«‹å°æ–¹å‡ç´šæ–¹æ¡ˆå¾Œå†é‚€è«‹ä½ "


def detect_reverse_invite(state, inviter_id, invitee_id):
    """å°æ–¹æ˜¯å¦å·²å–®å‘å®ˆè­·é‚€è«‹äººï¼ˆåå‘äº’ç¶æƒ…å¢ƒï¼‰ã€‚

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
    display_name = str(payload.get("display_name") or payload.get("contact_display_name") or "è¦ªå‹").strip()
    relationship = str(payload.get("relationship") or "å®ˆè­·äºº").strip()
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
        return {"ok": False, "error": "ç¼ºå°‘é‚€è«‹äººæˆ–æœ¬äººè³‡æ–™", "code": "missing_ids"}, 400
    if inviter_id == invitee_id:
        return {"ok": False, "error": "ä¸èƒ½ç¶å®šè‡ªå·±æˆç‚ºå®ˆè­·äºº", "code": "self_bind"}, 400

    state = load_state(data_file)
    users = state.get("users") or {}
    inviter = users.get(inviter_id) if isinstance(users.get(inviter_id), dict) else {}
    invitee = users.get(invitee_id) if isinstance(users.get(invitee_id), dict) else {}
    is_reverse = detect_reverse_invite(state, inviter_id, invitee_id)
    inviter_name = str(inviter.get("display_name") or "").strip() or "è¦ªå‹"
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
            return {"ok": False, "error": "é‚€è«‹å·²ä½¿ç”¨", "code": "invite_used"}, 410
        if invite_status == "expired":
            save_state(data_file, state)
            return {"ok": False, "error": "é‚€è«‹å·²è¶…éä¸ƒå¤©ï¼Œè«‹å°æ–¹é‡æ–°åˆ†äº«", "code": "invite_expired"}, 410
        if invite_status != "pending":
            return {"ok": False, "error": "é‚€è«‹é€£çµç„¡æ•ˆ", "code": "invalid_invite_token"}, 403
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
        "guardian_purpose": "ä½ æœƒæ”¶åˆ°å°æ–¹çš„å ±å¹³å®‰ã€é€¾æ™‚æœªå ±å¹³å®‰ã€SOS èˆ‡å®‰å…¨å®ˆè­·é€šçŸ¥ã€‚",
        "privacy_explanation": "å®šä½åªåœ¨å°æ–¹ä¸»å‹•æ±‚åŠ©æˆ–å•Ÿç”¨å®‰å…¨å®ˆè­·æ™‚é€šçŸ¥ï¼›ä½ å¯éš¨æ™‚è§£é™¤ç¶å®šï¼Œè³‡æ–™åªç”¨æ–¼å®ˆè­·é€šçŸ¥ã€‚",
        "requires_reciprocal_consent": False,
        "message": (
            f"{inviter_name} å·²æ˜¯ä½ çš„å®ˆè­·äººï¼›æœ¬æ¬¡é‚€è«‹ä»éœ€ä½ å¦å¤–åŒæ„ï¼Œæ‰æœƒæ–°å¢å¦ä¸€æ–¹å‘çš„å®ˆè­·é—œä¿‚ã€‚"
            if is_reverse
            else "æ‚¨æ”¶åˆ°ä¸€ä½è¦ªå‹çš„å®ˆè­·é‚€è«‹"
        ),
    }, 200


def build_bind_success_notices(inviter, contacts, inviter_id, guardian_name, *, invite_reward_applied=False):
    """Same bind-success LINE copy used by live bind + historical backfill."""
    inviter_name = (inviter or {}).get("display_name") or "ä½¿ç”¨è€…"
    guardian_name = guardian_name or "å®ˆè­·äºº"
    bound_rows = [c for c in (contacts or []) if contact_is_bound_guardian(c, inviter_id)]
    core_n = sum(1 for c in bound_rows if c.get("is_primary"))
    if bound_rows and core_n == 0:
        core_n = 1
    inviter_notice = (
        "âœ… ç¶å®šæˆåŠŸ\n\n"
        f"å°æ–¹ï¼š{guardian_name}ï¼ˆå·²æˆç‚ºä½ çš„å®ˆè­·äººï¼‰\n"
        f"ç›®å‰ï¼šæ ¸å¿ƒå®ˆè­·äºº {len(bound_rows)} ä½ã€‚\n\n"
        "ä¹‹å¾Œè‹¥ä½ é€¾æ™‚æœªå ±å¹³å®‰æˆ–ç™¼å‡º SOSï¼Œç³»çµ±æœƒé€é LINE ç§è¨Šé€šçŸ¥å°æ–¹ã€‚\n"
        "è«‹é»ã€Œå®Œæˆè³‡æ–™ã€è£œé½Šè‡ªå·±çš„è¯çµ¡è³‡æ–™ï¼›LINE é€šçŸ¥å·²ç«‹å³å•Ÿç”¨ã€‚"
    )
    guardian_notice = (
        f"âœ… ç¶å®šæˆåŠŸ\n\n"
        f"å°æ–¹ï¼š{inviter_name}\n"
        f"ä½ å·²æˆç‚ºå°æ–¹çš„å®ˆè­·äººã€‚\n\n"
        f"ä¹‹å¾Œæœƒåœ¨ä»¥ä¸‹æƒ…æ³é€é LINE ç§è¨Šé€šçŸ¥ä½ ï¼š\n"
        f"âš ï¸ å°æ–¹åœ¨æé†’å¾Œä»æœªå ±å¹³å®‰ï¼ˆä¾ç¬¬ä¸€ã€ç¬¬äºŒã€ç¬¬ä¸‰é †ä½é€æ­¥é€šçŸ¥ï¼‰\n"
        f"ğŸš¨ å°æ–¹ç™¼å‡º SOS ç·Šæ€¥æ±‚åŠ©\n\n"
        f"è¬è¬ä½ é¡˜æ„æˆç‚ºå°æ–¹æœ€å®‰å¿ƒçš„ä¾é ã€‚"
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
            "å®ˆè­·äººç¶å®šå®Œæˆ" in msg
            or "æ„Ÿè¬é‚€è«‹æˆåŠŸ" in msg
            or ("ç¶å®šæˆåŠŸ" in msg and "å·²æˆç‚ºä½ çš„å®ˆè­·äºº" in msg)
        ):
            inviter_ok = True
        if uid == guardian_id and (
            "ä½ å·²æ¥å—é‚€è«‹" in msg
            or "ä½ å·²æˆç‚ºå°æ–¹çš„å®ˆè­·äºº" in msg
            or ("ç¶å®šæˆåŠŸ" in msg and "å®ˆè­·äºº" in msg)
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
            or "å®ˆè­·äºº"
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
            or "å®ˆè­·äºº"
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
                "ç¶å®šå®Œæˆé€šçŸ¥è£œé€",
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
    contact_display_name = str(payload.get("contact_display_name") or "LINE è¯çµ¡äºº").strip()
    contact_relationship = str(payload.get("contact_relationship") or "").strip()
    contact_phone = str(payload.get("contact_phone") or "").strip()
    contact_picture_url = str(
        payload.get("contact_picture_url") or payload.get("picture_url") or ""
    ).strip()
    activate_trial = bool(payload.get("activate_trial"))
    legacy_reciprocal = "activate_trial" not in payload
    # æ¯ä¸€å€‹å®ˆè­·æ–¹å‘éƒ½å¿…é ˆæœ‰è‡ªå·±çš„é‚€è«‹èˆ‡åŒæ„ç´€éŒ„ï¼›èˆŠå®¢æˆ¶ç«¯å³ä½¿å‚³å…¥
    # mutual_core=trueï¼Œä¹Ÿä¸èƒ½è·³éç¬¬äºŒæ¬¡åŒæ„ç›´æ¥æ”¹æˆé›™å‘æ ¸å¿ƒå®ˆè­·ã€‚
    mutual_core = False
    if not inviter_id or not contact_line_user_id:
        return {"ok": False, "error": "ç¼ºå°‘é‚€è«‹äººæˆ–å®ˆè­·äººè³‡æ–™", "code": "missing_ids"}, 400
    if inviter_id == contact_line_user_id:
        return {"ok": False, "error": "ä¸èƒ½ç¶å®šè‡ªå·±æˆç‚ºå®ˆè­·äºº", "code": "self_bind"}, 400

    # æ ¸å¿ƒå®ˆè­·äººå¿…é ˆå…ˆåŠ å…¥ã€Œæ¯æ—¥å¹³å®‰ã€å®˜æ–¹ LINEï¼›å¦å‰‡ä¸èƒ½æ¨™è¨˜ç‚ºç¶å®šå®Œæˆã€‚
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
            "error": "è«‹å…ˆåŠ å…¥ã€Œæ¯æ—¥å¹³å®‰ã€å®˜æ–¹ LINEï¼Œå†å›ä¾†æ¥å—æ ¸å¿ƒå®ˆè­·äººé‚€è«‹",
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
            return {"ok": False, "error": "é‚€è«‹å·²ä½¿ç”¨", "code": "invite_used"}, 410
        if invite_status == "expired":
            save_state(data_file, state)
            return {"ok": False, "error": "é‚€è«‹å·²è¶…éä¸ƒå¤©ï¼Œè«‹å°æ–¹é‡æ–°åˆ†äº«", "code": "invite_expired"}, 410
        if invite_status != "pending":
            return {"ok": False, "error": "é‚€è«‹é€£çµç„¡æ•ˆ", "code": "invalid_invite_token"}, 403
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
        return {"ok": False, "error": "é‚€è«‹å·²è¶…éä¸ƒå¤©ï¼Œè«‹å°æ–¹é‡æ–°åˆ†äº«", "code": "invite_expired"}, 410
    if pending_invite and not bool(payload.get("recipient_consent")):
        save_state(data_file, state)
        return {"ok": False, "error": "è«‹å…ˆé–±è®€èªªæ˜ä¸¦åŒæ„æˆç‚ºæ ¸å¿ƒå®ˆè­·äºº", "code": "consent_required"}, 409
    if pending_invite and "activate_trial" in payload and (
        not contact_display_name
        or contact_display_name == "LINE è¯çµ¡äºº"
        or not contact_relationship
        or not contact_phone
    ):
        return {
            "ok": False,
            "error": "è«‹å¡«å¯«å§“åã€èˆ‡é‚€è«‹äººçš„é—œä¿‚åŠé›»è©±å¾Œå†å®Œæˆç¶å®š",
            "code": "guardian_profile_required",
            "required_fields": ["name", "relationship", "phone"],
        }, 400
    # ç¶å®šå‰åµæ¸¬åå‘ï¼šç¶å®šå¾Œ guarding_for ä¸€å®šæœƒå¯«å…¥ï¼Œä¸å¯äº‹å¾Œåˆ¤æ–·
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
    contact_user["display_name"] = contact_display_name or contact_user.get("display_name") or "LINE è¯çµ¡äºº"
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
    # åé¡å·²æ»¿æ™‚ï¼šå„ªå…ˆæŠŠ LINE ç¶åˆ°å°šæœªç¶å®šçš„è¯çµ¡äººè³‡æ–™åˆ—ï¼ˆé¿å… Android çœ‹åˆ° contact_limit exceededï¼‰
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
    # åå‘ç´¢å¼•å·²å­˜åœ¨ï¼å…ˆå‰ç¶éï¼Œè¦–ç‚ºå·²å®Œæˆï¼ˆå‹¿å†ç•¶æ–°ç¶å®šç‹‚æ¨ï¼‰
    if already_guarding and not existing and not unbound_slot:
        already_accepted = True
    # å‡çµã€Œé€™æ¬¡æ˜¯å¦ç‚ºé‡è¤‡ç¶å®šã€â€”â€”unbound_slot åˆä½µå¾Œ existing æœƒè®Š truthyï¼Œä¸å¯å†æ‹¿ä¾†ç•¶ already_bound
    was_duplicate = bool(already_accepted)

    accepted_at = datetime.now().isoformat(timespec="seconds")

    def _apply_line_bind_fields(row, *, is_new_accept):
        row["name"] = row.get("name") or contact_display_name or "LINE è¯çµ¡äºº"
        # ç¶å®šæ™‚æŒä¹…åŒ–å°æ–¹ LINE æš±ç¨±ï¼ˆåˆ—è¡¨ä¸»æ¨™ç±¤ç”¨ï¼Œå‹¿éœ²å‡º raw userIdï¼‰
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

    # LIFF é»æ“Šæˆæ¬Šå³è¦–ç‚ºå®ˆè­·äººæœ¬äººåŒæ„ç¶å®šï¼ˆä¸éœ€å†å›ã€ŒåŒæ„ã€ï¼‰
    if existing:
        _apply_line_bind_fields(existing, is_new_accept=not was_duplicate)
    elif unbound_slot is not None:
        # åˆä½µåˆ°æ—¢æœ‰æœªç¶ LINE çš„è¯çµ¡äººåˆ—ï¼ˆå¸¸è¦‹ï¼šé‚€è«‹äººå…ˆå¡«è³‡æ–™å†åˆ†äº«é‚€è«‹ï¼‰
        _apply_line_bind_fields(unbound_slot, is_new_accept=True)
        unbound_slot["accepted_at"] = accepted_at
        existing = unbound_slot
    else:
        core_limit = int(plan_rules(inviter).get("core_guardian_alert_limit") or 1)
        guardian_count = sum(
            1 for c in contacts if resolve_contact_role(c) == "guardian"
        )
        if guardian_count >= core_limit:
            # å·²æ˜¯é€™ä½é‚€è«‹äººçš„å®ˆè­·äººï¼šç•¶æˆåŠŸï¼å·²ç¶å®šï¼Œä¸è¦ 400 è‹±æ–‡éŒ¯èª¤
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
                "name": contact_display_name or "LINE è¯çµ¡äºº",
                "display_name": contact_display_name or "",
                "line_display_name": contact_display_name or "",
                "relationship": contact_relationship or "å®ˆè­·äºº",
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
                "note": "LINE ä¸€éµæˆæ¬Šç¶å®š",
            }
        )
    # Always write back so shallow-list mutations + new rows both persist
    # é¦–ä½å®ˆè­·äººè‡ªå‹•è¨­ç‚ºæ ¸å¿ƒï¼ˆis_primaryï¼‰
    if existing is not None:
        existing["contact_role"] = "guardian"
        existing["is_primary"] = True
    elif contacts:
        contacts[-1]["is_primary"] = True
    inviter["contacts"] = contacts

    # Reverse index on invitee: who they guard (admin + home can show é‚€è«‹äºº)
    if inviter_id not in guarding:
        guarding.append(inviter_id)
    contact_user["guarding_for"] = guarding
    contact_user["invited_by"] = inviter_id
    # Mirror inviter details onto invitee so admin can seeã€Œå®ˆè­·èª°ã€without only counting users
    details = list(contact_user.get("guarding_details") or [])
    detail_row = next((d for d in details if str(d.get("line_user_id") or "") == inviter_id), None)
    inviter_name = inviter.get("display_name") or "é‚€è«‹äºº"
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
    # æ¥å—é‚€è«‹åªå»ºç«‹ã€Œå—é‚€è€…å®ˆè­·é‚€è«‹äººã€ï¼›ç”³è«‹ 14 å¤©é«”é©—ä¹Ÿä¸è‡ªå‹•äº’ç¶ã€‚
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
                    "error": "ä½ å·²ä½¿ç”¨éå…è²»é«”é©—æˆ–å°æ¸¬è³‡æ ¼",
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
                "line_display_name": inviter_name, "relationship": "å®ˆè­·äºº", "phone": "", "line_id": inviter_id,
                "line_user_id": inviter_id, "picture_url": inviter_picture, "email": "", "available_time": "",
                "notify_methods": ["line"], "priority": len(invitee_contacts) + 1,
                "consent_status": "accepted", "binding_status": "accepted", "accepted_at": accepted_at,
                "invited_by": contact_line_user_id, "contact_role": "guardian", "note": "é›™æ–¹åŒæ„æ ¸å¿ƒå®ˆè­·ç¶å®š",
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

    # åå‘é‚€è«‹å®Œæˆæ™‚ï¼Œæœ¬æ¬¡åªå»ºç«‹æ–°çš„å–®å‘é—œä¿‚ï¼›ä¸ä¿®æ”¹å¦ä¸€æ–¹å‘çš„æ ¸å¿ƒé †ä½ã€‚
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
                "error": "ç¶å®šç‹€æ…‹å‰›å‰›æœ‰æ›´æ–°ï¼Œè«‹é‡æ–°é–‹å•Ÿé‚€è«‹é€£çµ",
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
    # é¦–æ¬¡ç¶å®šæˆåŠŸï¼šä¸€å®šæ¨æ’­é›™æ–¹ï¼ˆé‡è¤‡ç¶å®šä¸ç‹‚æ¨ï¼‰
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
                "ç¶å®šå®Œæˆé€šçŸ¥æœªé€å‡º",
                "LINE_CHANNEL_ACCESS_TOKEN missing",
            )
            notify_hint = "ç³»çµ±æ¨æ’­æ†‘è­‰æœªè¨­å®šï¼Œç¶å®šå®Œæˆé€šçŸ¥æœªé€å‡ºã€‚"
        else:
            guardian_name = contact_display_name or "å®ˆè­·äºº"
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
                notify_hint = "é›™æ–¹ LINE é€šçŸ¥çš†æœªé€å‡ºï¼›è«‹ç¢ºèªå·²åŠ å…¥ã€Œæ¯æ—¥å¹³å®‰ã€å®˜æ–¹å¸³è™Ÿå¥½å‹ã€‚"

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
    bind_message = ALREADY_BOUND_MESSAGE if was_duplicate else "ç¶å®šå®Œæˆï¼ä½ å·²æˆç‚ºå°æ–¹çš„å®ˆè­·äººã€‚"
    if is_reverse_invite and not was_duplicate:
        bind_message = f"ç¶å®šå®Œæˆï¼ä½ ç¾åœ¨ä¹Ÿæœƒå®ˆè­·ã€Œ{inviter_name}ã€ã€‚é›™æ–¹çš„å…©å€‹å®ˆè­·æ–¹å‘å‡å·²å„è‡ªåŒæ„ã€‚"
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
        "test_messages_sent": sent,  # å‘ä¸‹ç›¸å®¹
        "inviter_notified": inviter_notified,
        "guardian_notified": guardian_notified,
        "notify_errors": notify_errors,
        "notify_hint": notify_hint,
        "persistence": persistence_info(data_file),
    }, 200



# ============================================================
# 2026-07-20 è¦è‘£ added: å®ˆè­·ç¾¤ 50 äººä¸Šé™ + evict é‚è¼¯
# ============================================================
GROUP_MEMBER_LIMIT = 50


def get_group_member_count(token, group_id):
    """å‘¼å« LINE API æŸ¥ group æˆå“¡æ•¸ã€‚å¤±æ•—å› None(ä¸æ“‹,åª log warn)ã€‚"""
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
    """å‘¼å« LINE API æ‹¿ group æˆå“¡ userIdsã€‚å¤±æ•—å› Noneã€‚"""
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
    """é€²ç¾¤ï¼æŸ¥ç‹€æ…‹æ™‚åˆ·æ–°ç¾¤çµ„æˆå“¡æ•¸å¿«ç…§ï¼ˆèˆ‡ã€Œå·²ç¶å®šå®ˆè­·äººã€ç„¡é—œï¼‰ã€‚

    Returns:
        dict | None: æ›´æ–°å¾Œçš„ group è³‡æ–™ï¼›ç¾¤ä¸å­˜åœ¨æˆ– API å¤±æ•—æ™‚å›å‚³ç¾æœ‰å€¼ï¼Noneã€‚
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
    """æ’ç¨‹å™¨ç”¨ï¼šåˆ·æ–°æ‰€æœ‰ active å®ˆè­·ç¾¤çš„æˆå“¡æ•¸å¿«ç…§ï¼ˆæ¯ 5 åˆ†é˜è·‘ä¸€æ¬¡ï¼‰ã€‚

    - è·³éé active çš„ç¾¤
    - å€‹åˆ¥ç¾¤ API å¤±æ•—ä¸æœƒä¸­æ–·å…¶ä»–ç¾¤
    - å¯«å…¥ member_count_at_bind / member_ids_at_bind / member_count_updated_at
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
    """è¸¢ userId å‡º group(bot å¿…é ˆæ˜¯ admin)ã€‚å¤±æ•—:å› None / HTTPError codeã€‚"""
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
    """è¶… 50 äººæ™‚ evict æ–°æˆå“¡(ç”¨ bind æ™‚çš„ member snapshot å°æ¯”)ã€‚"""
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
    """æ–¹æ¡ˆæ˜¯å¦å«å®ˆè­·ç¾¤ï¼ˆç›®å‰ç‚º 799 æœˆï¼å¹´ï¼‰ã€‚"""
    return int(plan_rules(profile or {}).get("guardian_group_limit") or 0) > 0


def guardian_group_entitlement_active(profile, now=None):
    if not plan_includes_guardian_group(profile):
        return False
    if str((profile or {}).get("membership_source") or "") == "beta":
        return membership_access_active(profile, now)
    return paid_membership_is_active(profile)


def normalize_guardian_group_preferences(raw=None):
    """Product defaults: ç§è¨Šæé†’ ONã€ç¾¤çµ„æé†’ OFFã€æ¯æ—¥ç¾¤çµ„æ‘˜è¦ OFFã€‚"""
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
    """æŠŠ guardian_groups è£¡ã€Œæ­¤æœƒå“¡ç‚º owner ä¸” activeã€çš„ç¾¤åŒæ­¥å› profile.guardian_group_idsã€‚

    ä¿®å¸¸è¦‹ä¸ä¸€è‡´ï¼šç¾¤å·²ç¶å®šæˆåŠŸï¼ˆguardian_groups æœ‰è³‡æ–™ï¼‰ï¼Œä½† LIFF è®€ profile ä»é¡¯ç¤ºæœªç¶å®šã€‚
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
    # ä¿ç•™æ—¢æœ‰é †åºï¼Œå†è£œä¸Šéºæ¼çš„ owned ç¾¤
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
    """å›å‚³æ­¤æœƒå“¡æ“æœ‰ä¸”å•Ÿç”¨çš„å®ˆè­·ç¾¤åˆ—è¡¨ï¼ˆå« ids èˆ‡ groups é›™å‘å°é½Šï¼‰ã€‚"""
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
            "group_name": str(group.get("group_name") or "LINE å®ˆè­·ç¾¤"),
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
    """ç„¡å®ˆè­·ç¾¤ â†’ æ°¸é ç§è¨Šï¼›æœ‰ç¾¤ â†’ ä»»ä¸€ç¾¤å‹¾é¸ç§è¨Šå³ç™¼é€ï¼ˆé è¨­å‹¾é¸ï¼‰ã€‚"""
    owned = owned_active_guardian_groups(state, profile)
    if not owned:
        return True
    return any(guardian_group_preference(g, "notify_private_guardians") for g in owned)


def is_guardian_group_admin(group, line_user_id) -> bool:
    """å®ˆè­·ç¾¤ç®¡ç†å“¡ï¼å»ºç«‹è€…ï¼ˆownerï¼‰æˆ– admin_line_user_ids åå–®ã€‚"""
    uid = str(line_user_id or "").strip()
    if not uid or not isinstance(group, dict):
        return False
    if str(group.get("owner_line_user_id") or "").strip() == uid:
        return True
    admins = group.get("admin_line_user_ids") or []
    return uid in {str(x).strip() for x in admins if str(x).strip()}


def grant_guardian_group_admin(group, line_user_id) -> bool:
    """æŠŠç”¨æˆ¶å¯«å…¥å®ˆè­·ç¾¤ç®¡ç†å“¡åå–®ï¼›å¿…è¦æ™‚è£œ ownerã€‚å›å‚³æ˜¯å¦æœ‰è®Šæ›´ã€‚"""
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
    """å‡ç´šå«å®ˆè­·ç¾¤æ–¹æ¡ˆå¾Œï¼šå°å…¶å·²ç¶å®šï¼æ“æœ‰çš„ç¾¤è‡ªå‹•æˆäºˆç®¡ç†å“¡ï¼ˆä¸å¿…å†èµ°ã€Œç®¡ç†å“¡è¨­å®šã€ï¼‰ã€‚"""
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
            # å»ºç«‹è€…é‡æ–°ç¶å®šï¼å·²ç¶å®šï¼šè‡ªå‹•ç¢ºä¿ç®¡ç†å“¡èº«åˆ†ï¼Œä¸¦è£œå› profile.guardian_group_ids
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
                    "trial_test_message": "é€™æ˜¯æ¸¬è©¦é€šçŸ¥ï¼šå®ˆè­·ç¾¤ç¶å®šèˆ‡æ¨æ’­æµç¨‹å·²å®Œæˆ",
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

    # 50 äºº/ç¾¤ é©—è­‰(è‹¥ token æä¾›)
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
                        f"æ­¤ç¾¤ç›®å‰æœ‰ {mc} ä½æˆå“¡(ä¸å«ã€Œæ¯æ—¥å¹³å®‰ã€)ã€‚\n"
                        f"å®ˆè­·ç¾¤ä¸Šé™ {GROUP_MEMBER_LIMIT} äºº,è«‹æŠŠç¾¤ç¸®åˆ° {GROUP_MEMBER_LIMIT} äººå…§å†é‡æ–°é‚€è«‹ã€Œæ¯æ—¥å¹³å®‰ã€ã€‚"
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
            "name": profile.get("display_name") or profile.get("name") or "LINE æˆå“¡",
            "profile": profile,
        })
    return rows


def build_owner_today_safety_roster(state, profile, config=None, now=None):
    """ç®¡ç†å“¡ç”¨ï¼šä»Šå¤©èª°å·²å ±ï¼å°šæœªå ±å¹³å®‰ï¼ˆç§è¨Šï¼LIFFï¼›ä¸ä¾è³´ç¾¤çµ„æé†’é–‹é—œï¼‰ã€‚"""
    now = now or current_app_time(config or {})
    today = now.strftime("%Y-%m-%d")
    users = (state or {}).get("users") or {}
    owner_id = str((profile or {}).get("line_user_id") or "").strip()
    checked = []
    unchecked = []
    seen = set()

    def add_uid(uid, fallback_name="LINE æˆå“¡"):
        uid = str(uid or "").strip()
        if not uid or uid in seen:
            return
        seen.add(uid)
        row = users.get(uid) or {}
        name = row.get("display_name") or row.get("name") or fallback_name
        if uid == owner_id:
            name = f"{name}ï¼ˆæˆ‘ï¼‰"
        target = checked if _member_checked_today(row if row else profile, today) else unchecked
        if uid == owner_id and not row:
            target = checked if _member_checked_today(profile, today) else unchecked
        target.append({"line_user_id": uid, "name": name})

    # æœ¬äºº
    if owner_id:
        add_uid(owner_id, (profile or {}).get("display_name") or "æˆ‘")

    # å·²ç¶å®šæ ¸å¿ƒï¼ä¸€èˆ¬å®ˆè­·äººï¼ˆå ±å¹³å®‰å°è±¡æ˜¯æœƒå“¡æœ¬äººï¼›æ­¤è™•åˆ—å‡ºã€Œå®¶äººåœˆã€ç‹€æ…‹ç”¨ç¾¤å…§ï¼ç¶å®šæˆå“¡ï¼‰
    for contact in (profile or {}).get("contacts") or []:
        if not contact_is_bound_guardian(contact, owner_id):
            continue
        gid = get_contact_line_id(contact)
        if gid:
            add_uid(gid, contact.get("name") or contact.get("display_name") or "å®ˆè­·äºº")

    # å®ˆè­·ç¾¤ç¶å®šç•¶ä¸‹æˆå“¡å¿«ç…§ï¼ˆ799ï¼‰
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
        return "ç›®å‰ç„¡æ³•ç¢ºèªä½ çš„èº«åˆ†ï¼Œè«‹ç¨å¾Œå†è©¦ã€‚", 400
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
                f"ãƒ»ç§è¨Šæé†’ï¼š{'é–‹' if prefs.get('notify_private_guardians') else 'é—œ'}ï¼"
                f"ç¾¤çµ„æé†’ï¼š{'é–‹' if prefs.get('notify_group_on_overdue') else 'é—œ'}ï¼"
                f"ç¾¤çµ„æ¯æ—¥æ‘˜è¦ï¼š{'é–‹' if prefs.get('daily_admin_summary') else 'é—œ'}"
            )
        group_hint = "\n\nå®ˆè­·ç¾¤é€šçŸ¥è¨­å®šï¼š\n" + "\n".join(flags)
    else:
        group_hint = "\n\nï¼ˆå°šæœªç¶å®šå®ˆè­·ç¾¤æ™‚ï¼Œé€¾æœŸé è­¦é è¨­åªç§è¨Šæ ¸å¿ƒå®ˆè­·äººã€‚ï¼‰"
    lines = [
        "ğŸ“Š ä»Šå¤©èª°é‚„æ²’å ±å¹³å®‰",
        f"æ—¥æœŸï¼š{roster['date']}",
        f"å·²å ±å¹³å®‰ï¼š{', '.join(checked_names) if checked_names else 'å°šç„¡'}",
        f"å°šæœªå ±å¹³å®‰ï¼š{', '.join(unchecked_names) if unchecked_names else 'ç›®å‰éƒ½å·²å®Œæˆ'}",
        group_hint,
        "",
        "èªªæ˜ï¼šç§è¨Šå ±å¹³å®‰æˆåŠŸï¼ä»Šæ—¥å®Œæˆï¼Œä¸å¿…å†å¦å¤–åšç¾¤çµ„ç°½åˆ°ã€‚",
        "ç”Ÿæ—¥ï¼ç”Ÿæ´»æé†’åªæœƒç§è¨Šæœ¬äººï¼Œä¸æœƒç™¼åˆ°å®ˆè­·ç¾¤ã€‚",
    ]
    return "\n".join(lines), 200


def guardian_group_daily_status_text(data_file, line_user_id, group_id):
    if not line_user_id or not group_id:
        return "ç›®å‰ç„¡æ³•ç¢ºèªä½ çš„èº«åˆ†ï¼Œè«‹ç¨å¾Œå†è©¦ã€‚", 400

    state = load_state(data_file)
    group = state.get("guardian_groups", {}).get(group_id)
    if not group or group.get("status") != "active":
        return "æ­¤ç¾¤å°šæœªå®Œæˆå®ˆè­·ç¾¤ç¶å®šã€‚è«‹ç”±æœ‰æ•ˆçš„ 799 æœƒå“¡åœ¨ç¾¤è£¡è¼¸å…¥ã€Œé»æˆ‘ç¶å®šå®ˆè­·ç¾¤ã€ã€‚", 404
    prefs = normalize_guardian_group_preferences(group.get("preferences"))
    if prefs.get("notify_admin_only", True) and not is_guardian_group_admin(group, line_user_id):
        return "ç‚ºäº†ä¿è­·æˆå“¡éš±ç§ï¼Œä»Šæ—¥å¹³å®‰åå–®åªæœ‰å®ˆè­·ç¾¤ç®¡ç†å“¡å¯ä»¥æŸ¥çœ‹ã€‚", 403

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
        name = profile.get("display_name") or profile.get("name") or "LINE æˆå“¡"
        is_checked = _member_checked_today(profile, today)
        (checked if is_checked else unchecked).append(name)

    total_count = len(checked) + len(unchecked)
    lines = [
        f"ğŸ“Š {group.get('group_name') or 'å®ˆè­·ç¾¤'}ä»Šæ—¥å¹³å®‰ç‹€æ…‹",
        f"å…± {total_count} ä½æˆå“¡",
        f"âœ… {len(checked)} ä½å·²å ±å¹³å®‰",
        f"âš ï¸ {len(unchecked)} ä½æœªå ±å¹³å®‰",
        f"æœªå ±å¹³å®‰ï¼š{'ã€'.join(unchecked) if unchecked else 'ç›®å‰éƒ½å·²å®Œæˆ'}",
        "",
        "ç¾¤çµ„éš±ç§è¨­å®šï¼š",
        f"ç§è¨Šæé†’ï¼ˆæ ¸å¿ƒå®ˆè­·äººï¼‰ï¼š{'é–‹å•Ÿ' if prefs.get('notify_private_guardians') else 'é—œé–‰'}ï¼ˆé è¨­å»ºè­°é–‹å•Ÿï¼‰",
        f"ç¾¤çµ„æé†’ï¼š{'é–‹å•Ÿ' if prefs.get('notify_group_on_overdue') else 'é—œé–‰'}ï¼ˆé¸ç”¨ï¼Œé è¨­é—œé–‰ï¼‰",
        f"ç¾¤çµ„æ¯æ—¥æ‘˜è¦ï¼š{'é–‹å•Ÿ' if prefs.get('daily_admin_summary') else 'é—œé–‰'}ï¼ˆé¸ç”¨ï¼Œé è¨­é—œé–‰ï¼‰",
        f"è©³ç´°åå–®ï¼š{'åƒ…ç®¡ç†å“¡å¯çœ‹' if prefs.get('notify_admin_only') else 'ç¾¤å…§å¯çœ‹'}",
        "",
        "ç§è¨Šå ±å¹³å®‰æˆåŠŸï¼ä»Šæ—¥å®Œæˆï¼Œä¸å¿…å†å¦å¤–åšç¾¤çµ„ç°½åˆ°ã€‚",
    ]
    return "\n".join(lines), 200


def guardian_group_join_outcome(data_file, line_user_id, group_id):
    if not line_user_id or not group_id:
        return {
            "reply_text": (
                "ç›®å‰ç„¡æ³•ç¢ºèªé‚€è«‹äººçš„æœƒå“¡èº«åˆ†ï¼Œå› æ­¤ä¸èƒ½å•Ÿç”¨å®ˆè­·ç¾¤ã€‚\n"
                "è«‹ç”±æœ‰æ•ˆçš„ 799 å®ˆè­·ç‰ˆæœƒå“¡é‡æ–°é‚€è«‹æˆ‘åŠ å…¥ï¼›æˆ‘æœƒå…ˆé€€å‡ºé€™å€‹ç¾¤çµ„ã€‚"
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
            "æˆ‘å·²å®Œæˆå®ˆè­·ç¾¤è¨­å®š\n"
            f"ç›®å‰å·²ç¶å®š {result.get('guardian_group_count', 1)}/"
            f"{result.get('guardian_group_limit', 1)} å€‹å®ˆè­·ç¾¤ã€‚"
        )
    elif result.get("should_leave"):
        outcome["reply_text"] = (
            "é€™å€‹ç¾¤çµ„ç›®å‰ç„¡æ³•å•Ÿç”¨å®ˆè­·åŠŸèƒ½ã€‚å®ˆè­·ç¾¤åªé–‹æ”¾çµ¦æœ‰æ•ˆçš„ 799 å®ˆè­·ç‰ˆæœƒå“¡ï¼›"
            "æœˆè²»æœ€å¤š 1 ç¾¤ï¼Œå¹´è²»æœ€å¤š 3 ç¾¤ã€‚\n"
            "æˆ‘æœƒå…ˆé€€å‡ºç¾¤çµ„ï¼Œå®Œæˆå‡ç´šå¾Œå†é‡æ–°é‚€è«‹å³å¯ã€‚"
        )
    else:
        outcome["reply_text"] = "é€™å€‹ç¾¤çµ„å·²ç¶å®šå…¶ä»–æœƒå“¡ï¼Œè«‹ç”±åŸå»ºç«‹è€…ç®¡ç†å®ˆè­·è¨­å®šã€‚"
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
    """ç”¢ç”Ÿå¥½å‹é‚€è«‹ç¢¼ã€‚å›å‚³åŒ…å« invite_code / invite_url / status / expires_at / inviter / invited_guardianã€‚"""
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
    # é‚€ç´„å°è±¡å¿…é ˆèµ°æ°¸ä¹… LIFF å…¥å£ï¼›å‹¿å›å‚³ onrender è£¸ç¶²å€æˆ–å« OAuth code/state çš„é€£çµ
    invite_url = permanent_liff_invite_url(friend_invite=code)
    return {
        "invite_code": code,
        "invite_url": invite_url,
        "status": "pending",
        "expires_at": expires_at,
        "inviter": {
            "line_user_id": line_user_id,
            "display_name": profile.get("display_name", "LINE ä½¿ç”¨è€…"),
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
            "display_name": inviter.get("display_name", "LINE ä½¿ç”¨è€…"),
        },
    }, 200


def _parse_safety_guard_duration(payload, allowed_hours=None):
    """Parse duration for å®‰å…¨å®ˆè­· by plan.

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
        hours = float(text.replace("h", "").replace("hr", "").replace("å°æ™‚", "") or 0)
    except (TypeError, ValueError):
        hours = 0
    if hours in allowed_set:
        return hours, False
    # Explicit known option outside this plan â†’ entitlement error (do not silently upgrade/downgrade).
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
    """True when å®‰å…¨å®ˆè­· session is active (sharing + not expired)."""
    location = location or {}
    if not location.get("sharing") and not location.get("active"):
        return False
    now = now or datetime.now()
    if location.get("until_stop"):
        return True
    expires_at = parse_datetime(location.get("expires_at"))
    return bool(expires_at and expires_at >= now)


def safety_guard_snapshot(profile, now=None):
    """Public snapshot of the user's å®‰å…¨å®ˆè­· session (single-shot location, not a trail)."""
    now = now or current_app_time({})
    location = profile.get("location") or {}
    active = _location_session_active(location, now)
    today = now.strftime("%Y-%m-%d")
    last_check_in = profile.get("last_check_in")
    is_today_checked = profile_is_today_checked(profile, now=now)
    if is_today_checked:
        safety_status = "ä»Šæ—¥å·²ç°½åˆ°ãƒ»ç‹€æ…‹æ­£å¸¸"
    elif last_check_in:
        safety_status = "ä»Šæ—¥å°šæœªç°½åˆ°"
    else:
        safety_status = "å°šç„¡ç°½åˆ°ç´€éŒ„"
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
    """Notify bound LINE guardians that å®‰å…¨å®ˆè­· started. Mutates notification_logs on state.

    Returns a small status dict for the LIFF UI (sent / failed / no_guardians / reason).
    Never raises â€” caller already started the guard session.
    """
    location = profile.get("location") or {}
    name = (profile.get("display_name") or "").strip() or "ä½ çš„è¦ªå‹"
    city = str(location.get("city") or "").strip()
    hours = float(duration_hours or 1)
    duration_label = "15 åˆ†é˜" if hours == 0.25 else f"{int(hours)} å°æ™‚"
    place = f"ï¼ˆ{city}ï¼‰" if city else ""
    map_url = ""
    try:
        lat = location.get("latitude")
        lng = location.get("longitude")
        if lat is not None and lng is not None:
            map_url = f"https://www.google.com/maps?q={lat},{lng}"
    except (TypeError, ValueError):
        map_url = ""
    message = (
        f"ğŸ›¡ï¸ã€å®‰å…¨å®ˆè­·ã€‘{name} å·²é–‹å•Ÿå®‰å…¨å®ˆè­·ï¼ˆ{duration_label}ï¼‰\n"
        f"ç›®å‰å¤§è‡´ä½ç½®{place}"
        + (f"ï¼š\n{map_url}" if map_url else "ï¼šå·²åˆ†äº«å®šä½")
        + "\næ™‚é–“åˆ°æœƒè‡ªå‹•çµæŸï¼›è‹¥å°æ–¹æå‰çµæŸï¼Œä½ å°±ä¸æœƒå†çœ‹åˆ°é€™æ¬¡åˆ†äº«ã€‚"
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
        # é€²ä¸€æ­¥è¨ºæ–·ï¼šåˆ†è¾¨ã€Œå®Œå…¨æ²’è¯çµ¡äººã€ã€ã€Œåªæœ‰ç·Šæ€¥è¯çµ¡äººã€ã€ã€Œæœ‰è¯çµ¡äººä½†æœªèµ° LINE ç¶å®šã€
        all_contacts = list(profile.get("contacts") or [])
        has_any_contact = bool(all_contacts)
        only_emergency = has_any_contact and all(
            resolve_contact_role(c) == "emergency" for c in all_contacts
        )
        # æœ‰ã€Œæ ¸å¿ƒå®ˆè­·äººã€(is_primary) ä½†é‚„æ²’æ‹¿åˆ°å°æ–¹çš„ LINE userId
        core_missing_line = has_any_contact and not any(
            (get_contact_line_id(c) or "").strip() for c in all_contacts
        )

        if not has_any_contact:
            reason = "å°šæœªæ–°å¢ä»»ä½•å®ˆè­·äººã€‚è«‹åˆ°ã€Œå®ˆè­·äººã€é ç±¤æ–°å¢ 1 ä½å®¶äºº"
            reason_code = "no_contacts"
        elif only_emergency:
            reason = "ç›®å‰åªæœ‰ç·Šæ€¥è¯çµ¡äººï¼ˆé›»è©±å‚™æ´ï¼‰ï¼Œå®‰å…¨å®ˆè­·éœ€å…ˆã€Œä¸€éµé‚€è«‹ã€LINE å®ˆè­·äºº"
            reason_code = "emergency_only"
        elif core_missing_line:
            reason = (
                "å·²æ–°å¢å®ˆè­·äººï¼Œä½†å°æ–¹å°šæœªå®Œæˆ LINE ç¶å®šã€‚"
                "è«‹æŠŠ LINE é‚€è«‹é€£çµå‚³çµ¦å®ˆè­·äººï¼Œè®“ä»–åŠ å…¥ã€Œæ¯æ—¥å¹³å®‰ã€å®˜æ–¹å¸³è™Ÿä¸¦é»é€£çµåŒæ„ï¼Œ"
                "å®Œæˆå¾Œä¸‹æ¬¡é–‹å•Ÿå®‰å…¨å®ˆè­·å°±æœƒé€šçŸ¥åˆ°ä»–"
            )
            reason_code = "guardian_not_bound_line"
        else:
            reason = "å°šæœªç¶å®šå¯é€šçŸ¥çš„å®ˆè­·äººã€‚è«‹å…ˆä¸€éµé‚€è«‹å®¶äººå®Œæˆ LINE ç¶å®šï¼Œä¸”å°æ–¹éœ€åŠ å…¥å®˜æ–¹å¸³è™Ÿå¥½å‹"
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
            "message": "ç³»çµ±æš«æ™‚ç„¡æ³•æ¨æ’­ LINEï¼Œè«‹ç¨å¾Œå†è©¦",
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
        summary = f"å·²é€šçŸ¥ {sent} ä½å®ˆè­·äºº"
        reason_code = "ok"
    elif sent and failed:
        summary = f"å·²é€šçŸ¥ {sent} ä½ï¼Œ{failed} ä½å¤±æ•—"
        reason_code = "partial"
        if failed_reasons:
            summary = f"{summary}ã€‚{failed_reasons[0]}"
    else:
        reason_code = "push_failed"
        summary = "å®ˆè­·äººé€šçŸ¥å¤±æ•—ï¼ˆå·²é–‹å•Ÿå®‰å…¨å®ˆè­·ï¼Œä½†å°æ–¹æ²’æ”¶åˆ°ï¼‰"
        if failed_reasons:
            summary = f"{summary}ã€‚{failed_reasons[0]}"
        else:
            summary = f"{summary}ã€‚è«‹ç¢ºèªå®ˆè­·äººå·²åŠ å…¥ã€Œæ¯æ—¥å¹³å®‰ã€å®˜æ–¹å¸³è™Ÿå¥½å‹ä¸”æœªå°é–"

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
    """Start or refresh å®‰å…¨å®ˆè­·: one location snapshot within a timed session (not continuous track)."""
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

    # é–‹å§‹ï¼é‡é–‹å®‰å…¨å®ˆè­·ï¼šå¿…é ˆå·²æœ‰ â‰¥1 ä½ LINE å·²ç¶å®ˆè­·äººï¼ˆå‰ç«¯ä¹Ÿæœƒå…ˆæ“‹ï¼›æ­¤è™•ç‚ºå¾Œç«¯ä¿åº•ï¼‰
    if not profile_has_bound_line_guardian(profile):
        return {
            "ok": False,
            "error": "é‚„æ²’å®Œæˆç¶å®šå®ˆè­·äººï¼Œç„¡æ³•ä½¿ç”¨æ­¤åŠŸèƒ½",
            "error_code": "guardian_required",
            "message": "é‚„æ²’å®Œæˆç¶å®šå®ˆè­·äººï¼Œç„¡æ³•ä½¿ç”¨æ­¤åŠŸèƒ½",
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
                "ä»Šå¤©çš„å®‰å…¨å®ˆè­·é«”é©—å·²ä½¿ç”¨ï¼Œæ˜å¤©å¯ä»¥å†ä½¿ç”¨ 1 æ¬¡"
                if is_trial
                else f"ä»Šå¤©å·²ä½¿ç”¨å®‰å…¨å®ˆè­· {daily_limit} æ¬¡ï¼Œæ˜å¤©å¯å†ä½¿ç”¨"
            ),
            "daily_limit": daily_limit,
        }, 429

    allowed_hours = allowed_safety_guard_hours(profile)
    if not allowed_hours:
        return {
            "ok": False,
            "error": "safety guard requires an active trial or paid plan",
            "error_code": "safety_guard_upgrade_required",
            "message": "å®‰å…¨å®ˆè­·å®šä½éœ€åœ¨ 14 å¤©é«”é©—æœŸé–“æˆ–å‡ç´šæ–¹æ¡ˆå¾Œä½¿ç”¨",
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
    # Notify guardians when starting (or restarting) a timed session â€” not on silent refresh.
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
    """Stop å®‰å…¨å®ˆè­· immediately."""
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
    """æŠŠ SOS API å…§éƒ¨è‹±æ–‡éŒ¯èª¤è½‰æˆèŠå¤©å®¤å¯è®€ä¸­æ–‡ï¼ˆä¸éœ²å‡ºæŠ€è¡“å­—ä¸²ã€ä¸ç”¨å¥è™Ÿï¼‰ã€‚"""
    text = str(err or "").strip()
    lower = text.lower()
    if "no bound line guardians" in lower:
        return "é‚„æ²’ç¶å®šå®ˆè­·äººå–” å…ˆå»é‚€è«‹å®¶äººåŠ å…¥å†è©¦ï¼›æœ‰å±éšªè«‹å…ˆæ‰“ 119 æˆ– 110"
    if "cooldown" in lower:
        return "å‰›å‰›å·²é€ééœ€è¦å¹«å¿™ï¼Œè«‹ç¨å€™å†è©¦ï¼›æœ‰å±éšªè«‹å…ˆæ‰“ 119 æˆ– 110"
    if "daily sos limit" in lower or "daily limit" in lower:
        return "ä»Šå¤©éœ€è¦å¹«å¿™é€šçŸ¥å·²é”ä¸Šé™ï¼Œè«‹æ˜å¤©å†è©¦ï¼›æœ‰å±éšªè«‹å…ˆæ‰“ 119 æˆ– 110"
    if "not available" in lower or "not active" in lower:
        return "ç›®å‰æš«æ™‚ç„¡æ³•ç”¨ç³»çµ±é€šçŸ¥å®¶äººï¼›æœ‰å±éšªè«‹å…ˆæ‰“ 119 æˆ– 110ï¼Œä¸¦ç›´æ¥è¯çµ¡è¦ªå‹"
    if "member not found" in lower:
        return "é‚„èªä¸åˆ°ä½ çš„æœƒå“¡è³‡æ–™ï¼Œè«‹å…ˆå®Œæˆè¨­å®šï¼›æœ‰å±éšªè«‹å…ˆæ‰“ 119 æˆ– 110"
    if "line_channel_access_token" in lower or "missing line_user_id" in lower:
        return "ç³»çµ±æš«æ™‚ç„¡æ³•é€å‡ºé€šçŸ¥ï¼Œè«‹ç¨å¾Œå†è©¦ï¼›æœ‰å±éšªè«‹å…ˆæ‰“ 119 æˆ– 110"
    return "æš«æ™‚é€šçŸ¥ä¸åˆ°å®¶äººï¼Œæœ‰å±éšªè«‹å…ˆæ‰“ 119 æˆ– 110ï¼Œä¸¦ç›´æ¥è¯çµ¡è¦ªå‹"


def classify_line_push_error(exc) -> str:
    """Map LINE push failures to a short, user-facing hint (zh-Hant)."""
    text = str(exc or "").lower()
    if any(k in text for k in ("not a friend", "friendship", "you have been blocked", "blocked")):
        return "å°æ–¹æˆ–ä½ å°šæœªæŠŠã€Œæ¯æ—¥å¹³å®‰ã€åŠ ç‚ºå¥½å‹ï¼ˆæˆ–å°é–äº†å®˜æ–¹å¸³è™Ÿï¼‰ï¼ŒLINE ç„¡æ³•æ¨æ’­ã€‚"
    if "429" in text or "rate" in text:
        return "LINE æ¨æ’­æš«æ™‚éæ–¼é »ç¹ï¼Œè«‹ç¨å¾Œå†è©¦ã€‚"
    if "401" in text or "invalid" in text and "token" in text:
        return "ç³»çµ±æ¨æ’­æ†‘è­‰ç•°å¸¸ï¼Œè«‹ç¨å¾Œå†è©¦æˆ–è¯çµ¡å®¢æœã€‚"
    if "400" in text:
        return "LINE æ¨æ’­è¢«æ‹’ï¼ˆå¸¸è¦‹åŸå› ï¼šæœªåŠ å…¥å®˜æ–¹å¸³è™Ÿå¥½å‹ï¼‰ã€‚ç¶å®šæœ¬èº«å·²æˆåŠŸã€‚"
    return "LINE æ¨æ’­å¤±æ•—ï¼Œè«‹ç¢ºèªå·²åŠ å…¥å®˜æ–¹å¸³è™Ÿå¥½å‹å¾Œå†è©¦ã€‚"


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
            "name": contact.get("name") or contact.get("relationship") or "ç·Šæ€¥è¯çµ¡äºº",
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
        "altText": "SOS ç·Šæ€¥æ±‚åŠ©ï¼Œè«‹ç¢ºèªæ˜¯å¦èƒ½å”åŠ©",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#D6322C",
                "paddingAll": "lg",
                "contents": [{
                    "type": "text", "text": "ğŸ†˜ SOS ç·Šæ€¥æ±‚åŠ©",
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
                        "text": "ã€Œå·²é€é”ã€ä¸ä»£è¡¨å·²è®€ï¼Œè«‹æŒ‰ä¸‹æ–¹å›å ±å¯¦éš›è™•ç†ç‹€æ…‹",
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
                            "type": "postback", "label": "æˆ‘ä¾†è¯ç¹«",
                            "data": f"sos:take_over:{event_id}",
                            "displayText": "æˆ‘ä¾†è¯ç¹«",
                        },
                    },
                    {
                        "type": "button", "style": "secondary",
                        "action": {
                            "type": "postback", "label": "å·²è¯ç¹«æœ¬äºº",
                            "data": f"sos:contacted:{event_id}",
                            "displayText": "å·²è¯ç¹«æœ¬äºº",
                        },
                    },
                    {
                        "type": "button", "style": "link",
                        "action": {
                            "type": "postback", "label": "ç„¡æ³•è™•ç†",
                            "data": f"sos:unable:{event_id}",
                            "displayText": "ç›®å‰ç„¡æ³•è™•ç†",
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
                "æ ¸å¿ƒå®ˆè­·äºº" if row.get("kind") == "guardian" else "å®ˆè­·ç¾¤"
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
            or "æ ¸å¿ƒå®ˆè­·äºº"
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
            actor = result.get("actor_name") or "å®ˆè­·äºº"
            action_text = {
                "take_over": "å·²æ¥æ‰‹ï¼Œæ­£åœ¨è¯ç¹«æœ¬äºº",
                "assist": "å·²åŠ å…¥å”åŠ©è™•ç†",
                "contacted": "å·²ç¢ºèªè¯ç¹«åˆ°æœ¬äºº",
                "unable": "ç›®å‰ç„¡æ³•è™•ç†",
            }[action]
            notice = f"ğŸ†˜ SOS ç‹€æ…‹æ›´æ–°ï¼š{actor}{action_text}\näº‹ä»¶å°šæœªè‡ªå‹•çµæ¡ˆ"
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
            "actor_name": event.get("owner_display_name") or "æœ¬äºº",
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
                f"âœ…ã€SOS å·²çµæŸã€‘{event.get('owner_display_name') or 'æœ¬äºº'} "
                "å·²ç¢ºèªç›®å‰å®‰å…¨\næœ¬æ¬¡è™•ç†ç´€éŒ„å·²ä¿ç•™"
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
            "ç¬¬ä¸‰é †ä½é€šçŸ¥ï¼šå‰å…©ä½å°šæœªæ¥æ‰‹"
            if round_no == 1 else
            "ç¬¬ 4ã€5 ä½é€šçŸ¥ï¼šSOS ä»ç„¡äººæ¥æ‰‹"
            if round_no == 2 else
            "å…¶é¤˜å®ˆè­·äººé€šçŸ¥ï¼šè«‹ç«‹å³ç¢ºèªæœ¬äººå®‰å…¨"
        )
        message = (
            f"âš ï¸ã€{label}ã€‘{event.get('owner_display_name') or 'ä½ çš„è¦ªå‹'} "
            f"åœ¨ {minute} åˆ†é˜å‰ç™¼å‡º SOS\n"
            "ä½ æ˜¯æœ¬æ¬¡æ–°å¢é€šçŸ¥çš„å‚™æ´å®ˆè­·äººã€‚è‹¥èƒ½è™•ç†è«‹æŒ‰ã€Œæˆ‘ä¾†è¯ç¹«ã€ï¼›"
            "è‹¥æœ‰ç«‹å³å±éšªè«‹æ’¥æ‰“ 119ï¼110"
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
                    "display_name": str(guardian.get("display_name") or "å‚™æ´å®ˆè­·äºº"),
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
                    "display_name": str(guardian.get("display_name") or "å‚™æ´å®ˆè­·äºº"),
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
            "actor_name": "ç³»çµ±",
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
    reason = str(payload.get("reason") or "èª¤è§¸").strip()[:80]
    message = (
        f"âœ…ã€SOS å·²å–æ¶ˆã€‘{profile.get('display_name') or 'ä½ çš„è¦ªå‹'} å·²å›å ±ç›®å‰å®‰å…¨\n"
        f"åŸå› ï¼š{reason}\nåŸ SOS ç´€éŒ„ä»æœƒä¿ç•™ä¾›å®‰å…¨æŸ¥æ ¸"
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
    message = str(event.get("message") or "ğŸš¨ã€SOS ç·Šæ€¥æ±‚åŠ©ã€‘è«‹ç«‹å³è¯çµ¡æœ¬äººä¸¦ç¢ºèªå®‰å…¨")
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
                    "æœ¬äºº" if row.get("kind") == "self"
                    else "å®ˆè­·ç¾¤" if row.get("kind") == "group"
                    else "æ ¸å¿ƒå®ˆè­·äºº"
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
    ğŸ”´ P0 FIX v0.5:åŠ  3 å±¤é˜²è­·
    1. æ¯æ—¥ä¸Šé™ 3 æ¬¡(profile.sos_daily_count ç´¯åŠ ,>3 æ‹’çµ•)
    2. 5 åˆ†é˜å†·å»(profile.lastóOwé¼­zÊ&ŠÛ^t€€€€€€€€€€€€¥Í¥¹ÍÑ…¹”¡Ñ¥­•Ğ°‘¥Ğ¤(€€€€€€€€€€€€€€€…¹Ñ¥­•Ğ¹•Ğ ‰½±‘}±¥¹•}ÕÍ•É}¥ˆ¤€ôôÙ•É¥™¥•‘}½±‘}¥(€€€€€€€€€€€€€€€…¹Ñ¥­•Ğ¹•Ğ ‰ÍÑ…ÑÕÌˆ¤€ôô€‰Á•¹‘¥¹œˆ(€€€€€€€€€€€€¤è(€€€€€€€€€€€€€€€Ñ¥­•Ñl‰ÍÑ…ÑÕÌ‰t€ô€‰•áÁ¥É•ˆ(€€€€€€€€€€€€€€€Ñ¥­•Ñl‰•áÁ¥É•Í}…Ğ‰t€ôÕÉÉ•¹Ñ}¥Í¼(€€€€€€€Ñ¥­•ÑÍmÑ¥­•Ñ}¥‘t€ôì(€€€€€€€€€€€€‰Ñ¥­•Ñ}¥ˆèÑ¥­•Ñ}¥°(€€€€€€€€€€€€‰½‘•}‘¥•ÍĞˆè…½Õ¹Ñ}µ¥É…Ñ¥½¹}½‘•}‘¥•ÍĞ (€€€€€€€€€€€€€€€É…İ}½‘”°(€€€€€€€€€€€€€€€½¹™¥œ¹•Ğ ‰=U9Q}5%IQ%=9}MIPˆ¤°(€€€€€€€€€€€€¤°(€€€€€€€€€€€€‰½±‘}±¥¹•}ÕÍ•É}¥ˆèÙ•É¥™¥•‘}½±‘}¥°(€€€€€€€€€€€€‰É•…Ñ•‘}…ĞˆèÕÉÉ•¹Ñ}¥Í¼°(€€€€€€€€€€€€‰•áÁ¥É•Í}…Ğˆè€ (€€€€€€€€€€€€€€€ÕÉÉ•¹Ğ€¬Ñ¥µ•‘•±Ñ„¡Í•½¹‘ÌõÑÑ±}Í•½¹‘Ì¤(€€€€€€€€€€€€¤¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤°(€€€€€€€€€€€€‰ÕÍ•‘}…Ğˆè€ˆˆ°(€€€€€€€€€€€€‰ÍÑ…ÑÕÌˆè€‰Á•¹‘¥¹œˆ°(€€€€€€€ô(€€€€€€€É•ÑÕÉ¸ì(€€€€€€€€€€€€‰½¬ˆèQÉÕ”°(€€€€€€€€€€€€‰µ¥É…Ñ¥½¹}½‘”ˆèÉ…İ}½‘”°(€€€€€€€€€€€€‰•áÁ¥É•Í}¥¸ˆèÑÑ±}Í•½¹‘Ì°(€€€€€€€ô°€ÈÀÀ((€€€É•ÑÕÉ¸µÕÑ…Ñ•}ÍÑ…Ñ•}…Ñ½µ¥…±±ä¡‘…Ñ…}™¥±”°µÕÑ…Ñ”¤(()‘•˜…½Õ¹Ñ}µ¥É…Ñ¥½¹}Ñ¥­•Ñ}ÍÑ…ÑÕÌ (€€€‘…Ñ…}™¥±”°(€€€½±‘}±¥¹•}ÕÍ•É}¥°(€€€½¹™¥œ°(€€€¹½Üõ9½¹”°(¤è(€€€Í…™•}ÍÑ…ÑÕÌ€ôì(€€€€€€€€‰½¬ˆèQÉÕ”°(€€€€€€€€‰½¹™¥ÕÉ•ˆè…½Õ¹Ñ}µ¥É…Ñ¥½¹}É•…‘ä¡½¹™¥œ¤°(€€€€€€€€‰Á•¹‘¥¹œˆè…±Í”°(€€€€€€€€‰•áÁ¥É•Í}¥¸ˆè€À°(€€€ô(€€€¥˜¹½ĞÍ…™•}ÍÑ…ÑÕÍl‰½¹™¥ÕÉ•‰tè(€€€€€€€É•ÑÕÉ¸Í…™•}ÍÑ…ÑÕÌ((€€€Ù•É¥™¥•‘}½±‘}¥€ôÍÑÈ¡½±‘}±¥¹•}ÕÍ•É}¥½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€ÕÉÉ•¹Ğ€ô}…½Õ¹Ñ}µ¥É…Ñ¥½¹}¹½Ü¡¹½Ü¤(€€€É•µ…¥¹¥¹œ€ô€À(€€€ÕÍ•ÉÌ€ôÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ¤½Èíô(€€€…±¥…Í•Ì€ôÍÑ…Ñ”¹•Ğ ‰…½Õ¹Ñ}µ¥É…Ñ¥½¹}…±¥…Í•Ìˆ¤½Èíô(€€€Í½ÕÉ•}•á¥ÍÑÌ€ôÙ•É¥™¥•‘}½±‘}¥¥¸ÕÍ•ÉÌ…¹Ù•É¥™¥•‘}½±‘}¥¹½Ğ¥¸…±¥…Í•Ì(€€€™½ÈÑ¥­•Ğ¥¸€¡ÍÑ…Ñ”¹•Ğ ‰…½Õ¹Ñ}µ¥É…Ñ¥½¹}Ñ¥­•ÑÌˆ¤½Èíô¤¹Ù…±Õ•Ì ¤è(€€€€€€€¥˜€ (€€€€€€€€€€€¹½Ğ¥Í¥¹ÍÑ…¹”¡Ñ¥­•Ğ°‘¥Ğ¤(€€€€€€€€€€€½ÈÑ¥­•Ğ¹•Ğ ‰½±‘}±¥¹•}ÕÍ•É}¥ˆ¤€„ôÙ•É¥™¥•‘}½±‘}¥(€€€€€€€€€€€½ÈÑ¥­•Ğ¹•Ğ ‰ÍÑ…ÑÕÌˆ¤€„ô€‰Á•¹‘¥¹œˆ(€€€€€€€€¤è(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€•áÁ¥É•Í}…Ğ€ô}…½Õ¹Ñ}µ¥É…Ñ¥½¹}‘…Ñ•Ñ¥µ”¡Ñ¥­•Ğ¹•Ğ ‰•áÁ¥É•Í}…Ğˆ¤¤(€€€€€€€¥˜¹½ĞÍ½ÕÉ•}•á¥ÍÑÌ½È¹½Ğ•áÁ¥É•Í}…Ğ½ÈÕÉÉ•¹Ğ€øô•áÁ¥É•Í}…Ğè(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€É•µ…¥¹¥¹œ€ôµ…à¡É•µ…¥¹¥¹œ°¥¹Ğ ¡•áÁ¥É•Í}…Ğ€´ÕÉÉ•¹Ğ¤¹Ñ½Ñ…±}Í•½¹‘Ì ¤¤¤((€€€Í…™•}ÍÑ…ÑÕÍl‰Á•¹‘¥¹œ‰t€ôÉ•µ…¥¹¥¹œ€ø€À(€€€Í…™•}ÍÑ…ÑÕÍl‰•áÁ¥É•Í}¥¸‰t€ôÉ•µ…¥¹¥¹œ(€€€É•ÑÕÉ¸Í…™•}ÍÑ…ÑÕÌ(()}5%IQ%=9}AI=%1}1%MQ}-eL€ôì(€€€€‰½¹Ñ…ÑÌˆè€ ‰¥ˆ°€‰…•ÁÑ•‘}¥¹Ù¥Ñ•}¥ˆ°€‰¥¹Ù¥Ñ•}¥ˆ¤°(€€€€‰½¹Ñ…ÑÍ}…É¡¥Ù•ˆè€ ‰¥ˆ°€‰…•ÁÑ•‘}¥¹Ù¥Ñ•}¥ˆ°€‰¥¹Ù¥Ñ•}¥ˆ¤°(€€€€‰Íµ…ÉÑ}É•µ¥¹‘•ÉÌˆè€ ‰¥ˆ°¤°(€€€€‰Õ…É‘¥¹}‘•Ñ…¥±Ìˆè€ ‰¥ˆ°€‰±¥¹•}ÕÍ•É}¥ˆ¤°)ô()}5%IQ%=9}AII9}-eL€ôì(€€€€‰ÁÉ•™•É•¹•Ìˆ°(€€€€‰¥¹Ñ•É…Ñ¥½¹}ÍÑ…Ñ”ˆ°(€€€€‰Íµ…ÉÑ}É•µ¥¹‘•É}‘•™…Õ±ÑÌˆ°(€€€€‰É…•}¡½ÕÉÌˆ°(€€€€‰É•µ¥¹‘•É}Ñ¥µ”ˆ°(€€€€‰É•µ¥¹‘•É}Ñ¥µ•Ìˆ°(€€€€‰¡•­¥¹}µ½‘”ˆ°(€€€€‰…ÕÑ½}¡•­¥¹}½¹}½Á•¸ˆ°(€€€€‰İ…É¹¥¹}…¹•±}µ¥¹ÕÑ•Ìˆ°(€€€€‰…±•ÉÑ}¡…¹¹•±Ìˆ°(€€€€‰…ÑÑ…¡}±½…Ñ¥½¹}½¹}…±•ÉĞˆ°(€€€€‰½¹Ñ…Ñ}…Á…¥Ñå}É•µ¥¹‘•É}•¹…‰±•ˆ°(€€€€‰‘…¥±å}¡•­¥¹}É•µ¥¹‘•É}•¹…‰±•ˆ°(€€€€‰Õ…É‘¥…¹}‘•Ñ…¥±Í}É•µ¥¹‘•É}•¹…‰±•ˆ°(€€€€‰•áÁ¥Éå}É•µ¥¹‘}½ÁÑ}½ÕĞˆ°)ô()}5%IQ%=9}9Q%Q159Q}-eL€ôì(€€€€‰Á±…¸ˆ°(€€€€‰µ•µ‰•ÉÍ¡¥Á}Í½ÕÉ”ˆ°(€€€€‰ÑÉ¥…±}ÍÑ…ÉÑ•‘}…Ğˆ°(€€€€‰ÑÉ¥…±}•¹ˆ°(€€€€‰ÑÉ¥…±}Á½±¥å}Ù•ÉÍ¥½¸ˆ°(€€€€‰ÑÉ¥…±}¹½Ñ¥•}‘…åÍ}Í•¹Ğˆ°(€€€€‰ÑÉ¥…±}‰½¹ÕÍ}‘…åÌˆ°(€€€€‰Á…åµ•¹Ñ}ÍÑ…ÑÕÌˆ°(€€€€‰Á…¥‘}Õ¹Ñ¥°ˆ°(€€€€‰‰¥±±¥¹}å±”ˆ°(€€€€‰Á…åµ•¹Ñ}ÁÉ½Ù¥‘•Èˆ°(€€€€‰Á…åµ•¹Ñ}µ•Ñ¡½‘}±…ÍĞĞˆ°(€€€€‰¹•áÑ}‰¥±±¥¹}‘…Ñ”ˆ°(€€€€‰…ÕÑ½}É•¹•İ}É•ÅÕ•ÍÑ•ˆ°(€€€€‰…ÕÑ½}É•¹•İ}•¹…‰±•ˆ°(€€€€‰…ÕÑ½}É•¹•İ}ÍÑ…ÑÕÌˆ°(€€€€‰Á±…¹}•áÁ¥É•‘}…Ğˆ°(€€€€‰½¹Ñ…ÑÍ}É•Ñ…¥¹}Õ¹Ñ¥°ˆ°)ô(()‘•˜}µ¥É…Ñ¥½¹}Ù…±Õ•}‰±…¹¬¡Ù…±Õ”¤è(€€€É•ÑÕÉ¸Ù…±Õ”¥Ì9½¹”½ÈÙ…±Õ”€ôô€ˆˆ½ÈÙ…±Õ”€ôômt½ÈÙ…±Õ”€ôôíô(()‘•˜}µ¥É…Ñ¥½¹}Ñ¥µ•ÍÑ…µÀ¡Ù…±Õ”¤è(€€€¥˜¹½ĞÙ…±Õ”è(€€€€€€€É•ÑÕÉ¸9½¹”(€€€É•ÑÕÉ¸}…½Õ¹Ñ}µ¥É…Ñ¥½¹}‘…Ñ•Ñ¥µ”¡Ù…±Õ”¤(()‘•˜}µ¥É…Ñ¥½¹}É•½É‘}Ñ¥µ•ÍÑ…µÀ¡É•½É¤è(€€€¥˜¹½Ğ¥Í¥¹ÍÑ…¹”¡É•½É°‘¥Ğ¤è(€€€€€€€É•ÑÕÉ¸9½¹”(€€€™½È­•ä¥¸€ ‰ÕÁ‘…Ñ•‘}…Ğˆ°€‰…•ÁÑ•‘}…Ğˆ°€‰É•…Ñ•‘}…Ğˆ¤è(€€€€€€€Á…ÉÍ•€ô}µ¥É…Ñ¥½¹}Ñ¥µ•ÍÑ…µÀ¡É•½É¹•Ğ¡­•ä¤¤(€€€€€€€¥˜Á…ÉÍ•è(€€€€€€€€€€€É•ÑÕÉ¸Á…ÉÍ•(€€€É•ÑÕÉ¸9½¹”(()‘•˜}µ¥É…Ñ¥½¹}ÁÉ•™•É•¹•}Ñ¥µ•ÍÑ…µÀ¡ÁÉ½™¥±”°­•ä°Ù…±Õ”¤è(€€€¥˜¥Í¥¹ÍÑ…¹”¡Ù…±Õ”°‘¥Ğ¤è(€€€€€€€¹•ÍÑ•€ô}µ¥É…Ñ¥½¹}Ñ¥µ•ÍÑ…µÀ¡Ù…±Õ”¹•Ğ ‰ÕÁ‘…Ñ•‘}…Ğˆ¤¤(€€€€€€€¥˜¹•ÍÑ•è(€€€€€€€€€€€É•ÑÕÉ¸¹•ÍÑ•(€€€É•ÑÕÉ¸€ (€€€€€€€}µ¥É…Ñ¥½¹}Ñ¥µ•ÍÑ…µÀ ¡ÁÉ½™¥±”½Èíô¤¹•Ğ¡˜‰í­•åõ}ÕÁ‘…Ñ•‘}…Ğˆ¤¤(€€€€€€€½È}µ¥É…Ñ¥½¹}Ñ¥µ•ÍÑ…µÀ ¡ÁÉ½™¥±”½Èíô¤¹•Ğ ‰ÁÉ•™•É•¹•Í}ÕÁ‘…Ñ•‘}…Ğˆ¤¤(€€€€¤(()‘•˜}µ¥É…Ñ¥½¹}¡½½Í•}É•½É¡±•…ä°ÕÉÉ•¹Ğ¤è(€€€±•…å}Ñ¥µ”€ô}µ¥É…Ñ¥½¹}É•½É‘}Ñ¥µ•ÍÑ…µÀ¡±•…ä¤(€€€ÕÉÉ•¹Ñ}Ñ¥µ”€ô}µ¥É…Ñ¥½¹}É•½É‘}Ñ¥µ•ÍÑ…µÀ¡ÕÉÉ•¹Ğ¤(€€€¥˜ÕÉÉ•¹Ñ}Ñ¥µ”…¹€¡¹½Ğ±•…å}Ñ¥µ”½ÈÕÉÉ•¹Ñ}Ñ¥µ”€ø±•…å}Ñ¥µ”¤è(€€€€€€€É•ÑÕÉ¸½Áä¹‘••Á½Áä¡ÕÉÉ•¹Ğ¤(€€€É•ÑÕÉ¸½Áä¹‘••Á½Áä¡±•…ä¤(()‘•˜}µ¥É…Ñ¥½¹}ÍÑ…‰±•}Ù…±Õ”¡É•½É°­•åÌ¤è(€€€¥˜¹½Ğ¥Í¥¹ÍÑ…¹”¡É•½É°‘¥Ğ¤è(€€€€€€€É•ÑÕÉ¸€ˆˆ(€€€™½È­•ä¥¸­•åÌè(€€€€€€€Ù…±Õ”€ôÍÑÈ¡É•½É¹•Ğ¡­•ä¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€¥˜Ù…±Õ”è(€€€€€€€€€€€É•ÑÕÉ¸˜‰í­•åôéíÙ…±Õ•ôˆ(€€€É•ÑÕÉ¸€ˆˆ(()‘•˜}µ•É•}µ¥É…Ñ¥½¹}É•½É‘Ì¡±•…å}É½İÌ°ÕÉÉ•¹Ñ}É½İÌ°­•åÌ°ÁÉ•™¥à¤è(€€€µ•É•€ômt(€€€Á½Í¥Ñ¥½¹Ì€ôíô(€€€ÕÍ•‘}¥‘Ì€ôì(€€€€€€€ÍÑÈ¡É½Ü¹•Ğ ‰¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€™½ÈÉ½Ü¥¸l¨¡±•…å}É½İÌ½Èmt¤°€¨¡ÕÉÉ•¹Ñ}É½İÌ½Èmt¥t(€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡É½Ü°‘¥Ğ¤…¹ÍÑÈ¡É½Ü¹•Ğ ‰¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€ô(€€€•¹•É…Ñ•‘}¥¹‘•à€ô€À((€€€™½ÈÍ½ÕÉ•}¹…µ”°É½İÌ¥¸€  ‰±•…äˆ°±•…å}É½İÌ½Èmt¤°€ ‰ÕÉÉ•¹Ğˆ°ÕÉÉ•¹Ñ}É½İÌ½Èmt¤¤è(€€€€€€€™½ÈÉ½Ü¥¸É½İÌè(€€€€€€€€€€€¥˜¹½Ğ¥Í¥¹ÍÑ…¹”¡É½Ü°‘¥Ğ¤è(€€€€€€€€€€€€€€€É½Ü€ôì‰Ù…±Õ”ˆè½Áä¹‘••Á½Áä¡É½Ü¥ô(€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€É½Ü€ô½Áä¹‘••Á½Áä¡É½Ü¤(€€€€€€€€€€€ÍÑ…‰±”€ô}µ¥É…Ñ¥½¹}ÍÑ…‰±•}Ù…±Õ”¡É½Ü°­•åÌ¤(€€€€€€€€€€€¥˜ÍÑ…‰±”…¹ÍÑ…‰±”¥¸Á½Í¥Ñ¥½¹Ìè(€€€€€€€€€€€€€€€Á½Í¥Ñ¥½¸€ôÁ½Í¥Ñ¥½¹ÍmÍÑ…‰±•t(€€€€€€€€€€€€€€€¥˜Í½ÕÉ•}¹…µ”€ôô€‰ÕÉÉ•¹Ğˆè(€€€€€€€€€€€€€€€€€€€µ•É•‘mÁ½Í¥Ñ¥½¹t€ô}µ¥É…Ñ¥½¹}¡½½Í•}É•½É (€€€€€€€€€€€€€€€€€€€€€€€µ•É•‘mÁ½Í¥Ñ¥½¹t°(€€€€€€€€€€€€€€€€€€€€€€€É½Ü°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€¥˜¹½ĞÍÑ…‰±”è(€€€€€€€€€€€€€€€•¹•É…Ñ•‘}¥¹‘•à€¬ô€Ä(€€€€€€€€€€€€€€€•¹•É…Ñ•€ô˜‰µ¥É…Ñ¥½¸µíÁÉ•™¥áôµí•¹•É…Ñ•‘}¥¹‘•àèÀÑ‘ôˆ(€€€€€€€€€€€€€€€İ¡¥±”•¹•É…Ñ•¥¸ÕÍ•‘}¥‘Ìè(€€€€€€€€€€€€€€€€€€€•¹•É…Ñ•‘}¥¹‘•à€¬ô€Ä(€€€€€€€€€€€€€€€€€€€•¹•É…Ñ•€ô˜‰µ¥É…Ñ¥½¸µíÁÉ•™¥áôµí•¹•É…Ñ•‘}¥¹‘•àèÀÑ‘ôˆ(€€€€€€€€€€€€€€€É½İl‰¥‰t€ô•¹•É…Ñ•(€€€€€€€€€€€€€€€ÕÍ•‘}¥‘Ì¹…‘¡•¹•É…Ñ•¤(€€€€€€€€€€€€€€€ÍÑ…‰±”€ô˜‰¥éí•¹•É…Ñ•‘ôˆ(€€€€€€€€€€€Á½Í¥Ñ¥½¹ÍmÍÑ…‰±•t€ô±•¸¡µ•É•¤(€€€€€€€€€€€µ•É•¹…ÁÁ•¹¡É½Ü¤(€€€É•ÑÕÉ¸µ•É•(()‘•˜}µ¥É…Ñ¥½¹}¡¥ÍÑ½Éå}‘…Ñ”¡Ù…±Õ”¤è(€€€¥˜¥Í¥¹ÍÑ…¹”¡Ù…±Õ”°‘¥Ğ¤è(€€€€€€€É…Ü€ô€ (€€€€€€€€€€€Ù…±Õ”¹•Ğ ‰‘…Ñ”ˆ¤(€€€€€€€€€€€½ÈÙ…±Õ”¹•Ğ ‰¡•­¥¹}‘…Ñ”ˆ¤(€€€€€€€€€€€½ÈÙ…±Õ”¹•Ğ ‰¡•­•‘}…Ğˆ¤(€€€€€€€€€€€½ÈÙ…±Õ”¹•Ğ ‰É•…Ñ•‘}…Ğˆ¤(€€€€€€€€¤(€€€•±Í”è(€€€€€€€É…Ü€ôÙ…±Õ”(€€€Ñ•áĞ€ôÍÑÈ¡É…Ü½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€¥˜É”¹™Õ±±µ…Ñ ¡È‰q‘ìÑôµq‘ìÉôµq‘ìÉôˆ°Ñ•áĞ¤è(€€€€€€€É•ÑÕÉ¸Ñ•áĞ(€€€É•ÑÕÉ¸‘…Ñ•}ÍÑÉ¥¹}¥¹}Ñ…¥Á•¤¡Ñ•áĞ¤(()‘•˜}µ•É•}µ¥É…Ñ¥½¹}¡¥ÍÑ½Éä¡±•…å}É½İÌ°ÕÉÉ•¹Ñ}É½İÌ¤è(€€€‰å}‘…Ñ”€ôíô(€€€Õ¹‘…Ñ•€ômt(€€€™½ÈÉ½Ü¥¸l¨¡±•…å}É½İÌ½Èmt¤°€¨¡ÕÉÉ•¹Ñ}É½İÌ½Èmt¥tè(€€€€€€€¹½Éµ…±¥é•€ô}µ¥É…Ñ¥½¹}¡¥ÍÑ½Éå}‘…Ñ”¡É½Ü¤(€€€€€€€¥˜¹½Éµ…±¥é•è(€€€€€€€€€€€‰å}‘…Ñ•m¹½Éµ…±¥é•‘t€ô¹½Éµ…±¥é•(€€€€€€€•±Í”è(€€€€€€€€€€€Õ¹‘…Ñ•¹…ÁÁ•¹¡½Áä¹‘••Á½Áä¡É½Ü¤¤(€€€É•ÑÕÉ¸l©Í½ÉÑ•¡‰å}‘…Ñ”¤°€©Õ¹‘…Ñ•‘t(()‘•˜}µ•É•}µ¥É…Ñ¥½¹}…±•¹‘…É}¹½Ñ•Ì¡±•…å}¹½Ñ•Ì°ÕÉÉ•¹Ñ}¹½Ñ•Ì¤è(€€€¥˜¥Í¥¹ÍÑ…¹”¡±•…å}¹½Ñ•Ì°‘¥Ğ¤½È¥Í¥¹ÍÑ…¹”¡ÕÉÉ•¹Ñ}¹½Ñ•Ì°‘¥Ğ¤è(€€€€€€€µ•É•€ô½Áä¹‘••Á½Áä¡±•…å}¹½Ñ•Ì¤¥˜¥Í¥¹ÍÑ…¹”¡±•…å}¹½Ñ•Ì°‘¥Ğ¤•±Í”íô(€€€€€€€ÕÍ•‘}¥‘Ì€ôÍ•Ğ ¤(€€€€€€€™½È¹½Ñ•Ì¥¸€¡±•…å}¹½Ñ•Ì°ÕÉÉ•¹Ñ}¹½Ñ•Ì¤è(€€€€€€€€€€€™½ÈÙ…±Õ”¥¸€¡¹½Ñ•Ì½Èíô¤¹Ù…±Õ•Ì ¤¥˜¥Í¥¹ÍÑ…¹”¡¹½Ñ•Ì°‘¥Ğ¤•±Í”mtè(€€€€€€€€€€€€€€€Ù…±Õ•Ì€ôÙ…±Õ”¥˜¥Í¥¹ÍÑ…¹”¡Ù…±Õ”°±¥ÍĞ¤•±Í”mÙ…±Õ•t(€€€€€€€€€€€€€€€™½È¥Ñ•´¥¸Ù…±Õ•Ìè(€€€€€€€€€€€€€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡¥Ñ•´°‘¥Ğ¤…¹¥Ñ•´¹•Ğ ‰¥ˆ¤è(€€€€€€€€€€€€€€€€€€€€€€€ÕÍ•‘}¥‘Ì¹…‘¡ÍÑÈ¡¥Ñ•µl‰¥‰t¤¤(€€€€€€€•¹•É…Ñ•‘}¥¹‘•à€ô€À((€€€€€€€‘•˜¹½Éµ…±¥é•‘}¹½Ñ•}É•½É‘Ì¡Ù…±Õ”¤è(€€€€€€€€€€€¹½¹±½…°•¹•É…Ñ•‘}¥¹‘•à(€€€€€€€€€€€Ù…±Õ•Ì€ôÙ…±Õ”¥˜¥Í¥¹ÍÑ…¹”¡Ù…±Õ”°±¥ÍĞ¤•±Í”mÙ…±Õ•t(€€€€€€€€€€€É•½É‘Ì€ômt(€€€€€€€€€€€™½È¥Ñ•´¥¸Ù…±Õ•Ìè(€€€€€€€€€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡¥Ñ•´°‘¥Ğ¤è(€€€€€€€€€€€€€€€€€€€É•½É€ô½Áä¹‘••Á½Áä¡¥Ñ•´¤(€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€É•½É€ôì‰½¹Ñ•¹ĞˆèÍÑÈ¡¥Ñ•´½È€ˆˆ¥ô(€€€€€€€€€€€€€€€¥˜¹½ĞÍÑÈ¡É•½É¹•Ğ ‰¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤è(€€€€€€€€€€€€€€€€€€€•¹•É…Ñ•‘}¥¹‘•à€¬ô€Ä(€€€€€€€€€€€€€€€€€€€•¹•É…Ñ•€ô˜‰µ¥É…Ñ¥½¸µ…±•¹‘…Èµ¹½Ñ”µí•¹•É…Ñ•‘}¥¹‘•àèÀÑ‘ôˆ(€€€€€€€€€€€€€€€€€€€İ¡¥±”•¹•É…Ñ•¥¸ÕÍ•‘}¥‘Ìè(€€€€€€€€€€€€€€€€€€€€€€€•¹•É…Ñ•‘}¥¹‘•à€¬ô€Ä(€€€€€€€€€€€€€€€€€€€€€€€•¹•É…Ñ•€ô˜‰µ¥É…Ñ¥½¸µ…±•¹‘…Èµ¹½Ñ”µí•¹•É…Ñ•‘}¥¹‘•àèÀÑ‘ôˆ(€€€€€€€€€€€€€€€€€€€É•½É‘l‰¥‰t€ô•¹•É…Ñ•(€€€€€€€€€€€€€€€€€€€ÕÍ•‘}¥‘Ì¹…‘¡•¹•É…Ñ•¤(€€€€€€€€€€€€€€€É•½É‘Ì¹…ÁÁ•¹¡É•½É¤(€€€€€€€€€€€É•ÑÕÉ¸É•½É‘Ì((€€€€€€€™½È­•ä°ÕÉÉ•¹Ñ}Ù…±Õ”¥¸€ (€€€€€€€€€€€ÕÉÉ•¹Ñ}¹½Ñ•Ì¹¥Ñ•µÌ ¤¥˜¥Í¥¹ÍÑ…¹”¡ÕÉÉ•¹Ñ}¹½Ñ•Ì°‘¥Ğ¤•±Í”mt(€€€€€€€€¤è(€€€€€€€€€€€¥˜­•ä¹½Ğ¥¸µ•É•è(€€€€€€€€€€€€€€€µ•É•‘m­•åt€ô½Áä¹‘••Á½Áä¡ÕÉÉ•¹Ñ}Ù…±Õ”¤(€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€½µ‰¥¹•€ômt(€€€€€€€€€€€Á½Í¥Ñ¥½¹Ì€ôíô(€€€€€€€€€€€™½ÈÉ•½É¥¸l(€€€€€€€€€€€€€€€€©¹½Éµ…±¥é•‘}¹½Ñ•}É•½É‘Ì¡µ•É•‘m­•åt¤°(€€€€€€€€€€€€€€€€©¹½Éµ…±¥é•‘}¹½Ñ•}É•½É‘Ì¡ÕÉÉ•¹Ñ}Ù…±Õ”¤°(€€€€€€€€€€€tè(€€€€€€€€€€€€€€€ÍÑ…‰±”€ôÍÑÈ¡É•½É‘l‰¥‰t¤(€€€€€€€€€€€€€€€¥˜ÍÑ…‰±”¥¸Á½Í¥Ñ¥½¹Ìè(€€€€€€€€€€€€€€€€€€€Á½Í¥Ñ¥½¸€ôÁ½Í¥Ñ¥½¹ÍmÍÑ…‰±•t(€€€€€€€€€€€€€€€€€€€½µ‰¥¹•‘mÁ½Í¥Ñ¥½¹t€ô}µ¥É…Ñ¥½¹}¡½½Í•}É•½É (€€€€€€€€€€€€€€€€€€€€€€€½µ‰¥¹•‘mÁ½Í¥Ñ¥½¹t°(€€€€€€€€€€€€€€€€€€€€€€€É•½É°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€€€€€Á½Í¥Ñ¥½¹ÍmÍÑ…‰±•t€ô±•¸¡½µ‰¥¹•¤(€€€€€€€€€€€€€€€½µ‰¥¹•¹…ÁÁ•¹¡É•½É¤(€€€€€€€€€€€µ•É•‘m­•åt€ô½µ‰¥¹•‘lÁt¥˜±•¸¡½µ‰¥¹•¤€ôô€Ä•±Í”½µ‰¥¹•(€€€€€€€É•ÑÕÉ¸µ•É•(€€€É•ÑÕÉ¸}µ•É•}µ¥É…Ñ¥½¹}É•½É‘Ì (€€€€€€€±•…å}¹½Ñ•Ì½Èmt°(€€€€€€€ÕÉÉ•¹Ñ}¹½Ñ•Ì½Èmt°(€€€€€€€€ ‰¥ˆ°¤°(€€€€€€€€‰…±•¹‘…Èµ¹½Ñ”ˆ°(€€€€¤(()‘•˜}µ¥É…Ñ¥½¹}•¹Ñ¥Ñ±•µ•¹Ñ}…Ñ¥Ù”¡ÁÉ½™¥±”°¹½Ü¤è(€€€Á±…¸€ôÍÑÈ ¡ÁÉ½™¥±”½Èíô¤¹•Ğ ‰Á±…¸ˆ¤½È€ˆˆ¤(€€€¥˜Á±…¸¹½Ğ¥¸A19}I9,è(€€€€€€€É•ÑÕÉ¸…±Í”(€€€¥˜Á±…¸€ôô€‰ÑÉ¥…°ˆè(€€€€€€€•áÁ¥É•Í}…Ğ€ô}µ¥É…Ñ¥½¹}Ñ¥µ•ÍÑ…µÀ ¡ÁÉ½™¥±”½Èíô¤¹•Ğ ‰ÑÉ¥…±}•¹ˆ¤¤(€€€€€€€É•ÑÕÉ¸‰½½°¡•áÁ¥É•Í}…Ğ…¹•áÁ¥É•Í}…Ğ€ø¹½Ü¤(€€€¥˜ÍÑÈ ¡ÁÉ½™¥±”½Èíô¤¹•Ğ ‰Á…åµ•¹Ñ}ÍÑ…ÑÕÌˆ¤½È€ˆˆ¤€„ô€‰…Ñ¥Ù”ˆè(€€€€€€€É•ÑÕÉ¸…±Í”(€€€•áÁ¥É•Í}…Ğ€ô}µ¥É…Ñ¥½¹}Ñ¥µ•ÍÑ…µÀ ¡ÁÉ½™¥±”½Èíô¤¹•Ğ ‰Á…¥‘}Õ¹Ñ¥°ˆ¤¤(€€€É•ÑÕÉ¸•áÁ¥É•Í}…Ğ¥Ì9½¹”½È•áÁ¥É•Í}…Ğ€ø¹½Ü(()‘•˜}µ¥É…Ñ¥½¹}•¹Ñ¥Ñ±•µ•¹Ñ}•áÁ¥Éä¡ÁÉ½™¥±”¤è(€€€Á±…¸€ôÍÑÈ ¡ÁÉ½™¥±”½Èíô¤¹•Ğ ‰Á±…¸ˆ¤½È€ˆˆ¤(€€€­•ä€ô€‰ÑÉ¥…±}•¹ˆ¥˜Á±…¸€ôô€‰ÑÉ¥…°ˆ•±Í”€‰Á…¥‘}Õ¹Ñ¥°ˆ(€€€É•ÑÕÉ¸}µ¥É…Ñ¥½¹}Ñ¥µ•ÍÑ…µÀ ¡ÁÉ½™¥±”½Èíô¤¹•Ğ¡­•ä¤¤(()‘•˜}µ¥É…Ñ¥½¹}¡½½Í•}•¹Ñ¥Ñ±•µ•¹Ğ¡±•…å}ÁÉ½™¥±”°ÕÉÉ•¹Ñ}ÁÉ½™¥±”°¹½Ü¤è(€€€…¹‘¥‘…Ñ•Ì€ôl(€€€€€€€ÁÉ½™¥±”(€€€€€€€™½ÈÁÉ½™¥±”¥¸€¡±•…å}ÁÉ½™¥±”½Èíô°ÕÉÉ•¹Ñ}ÁÉ½™¥±”½Èíô¤(€€€€€€€¥˜}µ¥É…Ñ¥½¹}•¹Ñ¥Ñ±•µ•¹Ñ}…Ñ¥Ù”¡ÁÉ½™¥±”°¹½Ü¤(€€€t(€€€¥˜¹½Ğ…¹‘¥‘…Ñ•Ìè(€€€€€€€É•ÑÕÉ¸±•…å}ÁÉ½™¥±”½ÈÕÉÉ•¹Ñ}ÁÉ½™¥±”½Èíô((€€€‘•˜•¹Ñ¥Ñ±•µ•¹Ñ}­•ä¡ÁÉ½™¥±”¤è(€€€€€€€•áÁ¥Éä€ô}µ¥É…Ñ¥½¹}•¹Ñ¥Ñ±•µ•¹Ñ}•áÁ¥Éä¡ÁÉ½™¥±”¤(€€€€€€€•áÁ¥Éå}Í½É”€ô•áÁ¥Éä¹Ñ¥µ•ÍÑ…µÀ ¤¥˜•áÁ¥Éä•±Í”™±½…Ğ ‰¥¹˜ˆ¤(€€€€€€€É•ÑÕÉ¸€¡A19}I9,¹•Ğ¡ÍÑÈ¡ÁÉ½™¥±”¹•Ğ ‰Á±…¸ˆ¤½È€ˆˆ¤°€´Ä¤°•áÁ¥Éå}Í½É”¤((€€€É•ÑÕÉ¸µ…à¡…¹‘¥‘…Ñ•Ì°­•äõ•¹Ñ¥Ñ±•µ•¹Ñ}­•ä¤(()‘•˜}µ¥É…Ñ¥½¹}±½…Ñ¥½¹}…Ñ¥Ù”¡±½…Ñ¥½¸°¹½Ü¤è(€€€¥˜¹½Ğ¥Í¥¹ÍÑ…¹”¡±½…Ñ¥½¸°‘¥Ğ¤è(€€€€€€€É•ÑÕÉ¸…±Í”(€€€¥˜¹½Ğ±½…Ñ¥½¸¹•Ğ ‰…Ñ¥Ù”ˆ¤…¹¹½Ğ±½…Ñ¥½¸¹•Ğ ‰Í¡…É¥¹œˆ¤è(€€€€€€€É•ÑÕÉ¸…±Í”(€€€¥˜±½…Ñ¥½¸¹•Ğ ‰Õ¹Ñ¥±}ÍÑ½Àˆ¤è(€€€€€€€É•ÑÕÉ¸QÉÕ”(€€€•áÁ¥É•Í}…Ğ€ô}µ¥É…Ñ¥½¹}Ñ¥µ•ÍÑ…µÀ¡±½…Ñ¥½¸¹•Ğ ‰•áÁ¥É•Í}…Ğˆ¤¤(€€€É•ÑÕÉ¸‰½½°¡•áÁ¥É•Í}…Ğ…¹•áÁ¥É•Í}…Ğ€ø¹½Ü¤(()‘•˜}µ•É•}µ¥É…Ñ¥½¹}±½…Ñ¥½¸¡±•…å}±½…Ñ¥½¸°ÕÉÉ•¹Ñ}±½…Ñ¥½¸°¹½Ü¤è(€€€±•…å}…Ñ¥Ù”€ô}µ¥É…Ñ¥½¹}±½…Ñ¥½¹}…Ñ¥Ù”¡±•…å}±½…Ñ¥½¸°¹½Ü¤(€€€ÕÉÉ•¹Ñ}…Ñ¥Ù”€ô}µ¥É…Ñ¥½¹}±½…Ñ¥½¹}…Ñ¥Ù”¡ÕÉÉ•¹Ñ}±½…Ñ¥½¸°¹½Ü¤(€€€¥˜±•…å}…Ñ¥Ù”…¹ÕÉÉ•¹Ñ}…Ñ¥Ù”è(€€€€€€€É•ÑÕÉ¸}µ¥É…Ñ¥½¹}¡½½Í•}É•½É¡±•…å}±½…Ñ¥½¸°ÕÉÉ•¹Ñ}±½…Ñ¥½¸¤(€€€¥˜ÕÉÉ•¹Ñ}…Ñ¥Ù”è(€€€€€€€É•ÑÕÉ¸½Áä¹‘••Á½Áä¡ÕÉÉ•¹Ñ}±½…Ñ¥½¸¤(€€€¥˜±•…å}…Ñ¥Ù”è(€€€€€€€É•ÑÕÉ¸½Áä¹‘••Á½Áä¡±•…å}±½…Ñ¥½¸¤(€€€É•ÑÕÉ¸íô(()‘•˜µ•É•}µ¥É…Ñ¥½¹}ÁÉ½™¥±•Ì¡½±‘}ÁÉ½™¥±”°¹•İ}ÁÉ½™¥±”°¹½Üõ9½¹”¤è(€€€€ˆˆ‰•Ñ•Éµ¥¹¥ÍÑ¥…±±äµ•É”Ñİ¼Ù•É¥™¥•AÉ½Ù¥‘•ÈÁÉ½™¥±•Ì¸((€€€MÑ…‰±”‰ÕÍ¥¹•ÍÌ¥‘•¹Ñ¥™¥•ÉÌ‘É¥Ù”½±±•Ñ¥½¸‘•‘ÕÁ±¥…Ñ¥½¸¸¥ÍÁ±…ä¹…µ•Ì(€€€…¹½Ñ¡•È¡Õµ…¸µÉ•…‘…‰±”…ÑÑÉ¥‰ÕÑ•Ì…É”¹•Ù•È¥‘•¹Ñ¥Ñä­•åÌ¸(€€€€ˆˆˆ(€€€±•…ä€ô½Áä¹‘••Á½Áä¡½±‘}ÁÉ½™¥±”½Èíô¤(€€€ÕÉÉ•¹Ğ€ô½Áä¹‘••Á½Áä¡¹•İ}ÁÉ½™¥±”½Èíô¤(€€€ÕÉÉ•¹Ñ}¹½Ü€ô}…½Õ¹Ñ}µ¥É…Ñ¥½¹}¹½Ü¡¹½Ü¤(€€€µ•É•€ô½Áä¹‘••Á½Áä¡±•…ä¤((€€€™½È­•ä°Ù…±Õ”¥¸ÕÉÉ•¹Ğ¹¥Ñ•µÌ ¤è(€€€€€€€¥˜­•ä¥¸ì(€€€€€€€€€€€€‰±¥¹•}ÕÍ•É}¥ˆ°(€€€€€€€€€€€€‰¡¥ÍÑ½Éäˆ°(€€€€€€€€€€€€‰…±•¹‘…É}¹½Ñ•Ìˆ°(€€€€€€€€€€€€‰±½…Ñ¥½¸ˆ°(€€€€€€€€€€€€‰™É¥•¹‘Ìˆ°(€€€€€€€€€€€€‰Õ…É‘¥…¹}É½ÕÁ}¥‘Ìˆ°(€€€€€€€€€€€€‰Õ…É‘¥¹}™½Èˆ°(€€€€€€€€€€€€‰Íµ…ÉÑ}É•µ¥¹‘•É}Í•¹Ñ}­•åÌˆ°(€€€€€€€€€€€€©}5%IQ%=9}AI=%1}1%MQ}-eL°(€€€€€€€€€€€€©}5%IQ%=9}9Q%Q159Q}-eL°(€€€€€€€€€€€€©}5%IQ%=9}AII9}-eL°(€€€€€€€ôè(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¥˜­•ä€ôô€‰‘¥ÍÁ±…å}¹…µ”ˆ…¹¥Í}Á±…•¡½±‘•É}‘¥ÍÁ±…å}¹…µ”¡Ù…±Õ”¤è(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¥˜}µ¥É…Ñ¥½¹}Ù…±Õ•}‰±…¹¬¡Ù…±Õ”¤è(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¥˜­•ä¥¸U1Q}AI=%1…¹Ù…±Õ”€ôôU1Q}AI=%1¹•Ğ¡­•ä¤è(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€µ•É•‘m­•åt€ô½Áä¹‘••Á½Áä¡Ù…±Õ”¤((€€€µ•É•‘l‰¡¥ÍÑ½Éä‰t€ô}µ•É•}µ¥É…Ñ¥½¹}¡¥ÍÑ½Éä (€€€€€€€±•…ä¹•Ğ ‰¡¥ÍÑ½Éäˆ¤°(€€€€€€€ÕÉÉ•¹Ğ¹•Ğ ‰¡¥ÍÑ½Éäˆ¤°(€€€€¤(€€€™½È­•ä°ÍÑ…‰±•}­•åÌ¥¸}5%IQ%=9}AI=%1}1%MQ}-eL¹¥Ñ•µÌ ¤è(€€€€€€€µ•É•‘m­•åt€ô}µ•É•}µ¥É…Ñ¥½¹}É•½É‘Ì (€€€€€€€€€€€±•…ä¹•Ğ¡­•ä¤°(€€€€€€€€€€€ÕÉÉ•¹Ğ¹•Ğ¡­•ä¤°(€€€€€€€€€€€ÍÑ…‰±•}­•åÌ°(€€€€€€€€€€€­•ä¹É•Á±…” ‰|ˆ°€ˆ´ˆ¤°(€€€€€€€€¤(€€€µ•É•‘l‰…±•¹‘…É}¹½Ñ•Ì‰t€ô}µ•É•}µ¥É…Ñ¥½¹}…±•¹‘…É}¹½Ñ•Ì (€€€€€€€±•…ä¹•Ğ ‰…±•¹‘…É}¹½Ñ•Ìˆ¤°(€€€€€€€ÕÉÉ•¹Ğ¹•Ğ ‰…±•¹‘…É}¹½Ñ•Ìˆ¤°(€€€€¤(€€€™½È­•ä¥¸€ (€€€€€€€€‰™É¥•¹‘Ìˆ°(€€€€€€€€‰Õ…É‘¥…¹}É½ÕÁ}¥‘Ìˆ°(€€€€€€€€‰Õ…É‘¥¹}™½Èˆ°(€€€€€€€€‰Íµ…ÉÑ}É•µ¥¹‘•É}Í•¹Ñ}­•åÌˆ°(€€€€¤è(€€€€€€€µ•É•‘m­•åt€ô±¥ÍĞ (€€€€€€€€€€€‘¥Ğ¹™É½µ­•åÌ¡l¨¡±•…ä¹•Ğ¡­•ä¤½Èmt¤°€¨¡ÕÉÉ•¹Ğ¹•Ğ¡­•ä¤½Èmt¥t¤(€€€€€€€€¤((€€€™½È­•ä¥¸}5%IQ%=9}AII9}-eLè(€€€€€€€±•…å}Ù…±Õ”€ô±•…ä¹•Ğ¡­•ä¤(€€€€€€€ÕÉÉ•¹Ñ}Ù…±Õ”€ôÕÉÉ•¹Ğ¹•Ğ¡­•ä¤(€€€€€€€±•…å}Ñ¥µ”€ô}µ¥É…Ñ¥½¹}ÁÉ•™•É•¹•}Ñ¥µ•ÍÑ…µÀ¡±•…ä°­•ä°±•…å}Ù…±Õ”¤(€€€€€€€ÕÉÉ•¹Ñ}Ñ¥µ”€ô}µ¥É…Ñ¥½¹}ÁÉ•™•É•¹•}Ñ¥µ•ÍÑ…µÀ¡ÕÉÉ•¹Ğ°­•ä°ÕÉÉ•¹Ñ}Ù…±Õ”¤(€€€€€€€¥˜ÕÉÉ•¹Ñ}Ñ¥µ”…¹€¡¹½Ğ±•…å}Ñ¥µ”½ÈÕÉÉ•¹Ñ}Ñ¥µ”€ø±•…å}Ñ¥µ”¤è(€€€€€€€€€€€µ•É•‘m­•åt€ô½Áä¹‘••Á½Áä¡ÕÉÉ•¹Ñ}Ù…±Õ”¤(€€€€€€€•±¥˜­•ä¥¸±•…äè(€€€€€€€€€€€µ•É•‘m­•åt€ô½Áä¹‘••Á½Áä¡±•…å}Ù…±Õ”¤(€€€€€€€•±¥˜­•ä¥¸ÕÉÉ•¹Ğè(€€€€€€€€€€€µ•É•‘m­•åt€ô½Áä¹‘••Á½Áä¡ÕÉÉ•¹Ñ}Ù…±Õ”¤((€€€•¹Ñ¥Ñ±•µ•¹Ğ€ô}µ¥É…Ñ¥½¹}¡½½Í•}•¹Ñ¥Ñ±•µ•¹Ğ¡±•…ä°ÕÉÉ•¹Ğ°ÕÉÉ•¹Ñ}¹½Ü¤(€€€™½È­•ä¥¸}5%IQ%=9}9Q%Q159Q}-eLè(€€€€€€€¥˜­•ä¥¸•¹Ñ¥Ñ±•µ•¹Ğè(€€€€€€€€€€€µ•É•‘m­•åt€ô½Áä¹‘••Á½Áä¡•¹Ñ¥Ñ±•µ•¹Ñm­•åt¤((€€€µ•É•‘l‰±½…Ñ¥½¸‰t€ô}µ•É•}µ¥É…Ñ¥½¹}±½…Ñ¥½¸ (€€€€€€€±•…ä¹•Ğ ‰±½…Ñ¥½¸ˆ¤°(€€€€€€€ÕÉÉ•¹Ğ¹•Ğ ‰±½…Ñ¥½¸ˆ¤°(€€€€€€€ÕÉÉ•¹Ñ}¹½Ü°(€€€€¤(€€€µ•É•‘l‰±¥¹•}ÕÍ•É}¥‰t€ôÍÑÈ¡ÕÉÉ•¹Ğ¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€É•ÑÕÉ¸µ•É•(()}5%IQ%=9}II9}M1I}%1L€ôì(€€€€‰±¥¹•}ÕÍ•É}¥ˆ°(€€€€‰±¥¹•}¥ˆ°(€€€€‰½İ¹•É}±¥¹•}ÕÍ•É}¥ˆ°(€€€€‰µ•µ‰•É}±¥¹•}ÕÍ•É}¥ˆ°(€€€€‰É•ÅÕ•ÍÑ•É}±¥¹•}ÕÍ•É}¥ˆ°(€€€€‰Á…å•É}±¥¹•}ÕÍ•É}¥ˆ°(€€€€‰É•¥Á¥•¹Ñ}±¥¹•}ÕÍ•É}¥ˆ°(€€€€‰¥¹Ù¥Ñ•É}±¥¹•}ÕÍ•É}¥ˆ°(€€€€‰½¹Ñ…Ñ}±¥¹•}ÕÍ•É}¥ˆ°(€€€€‰Õ…É‘¥…¹}±¥¹•}ÕÍ•É}¥ˆ°(€€€€‰…•ÁÑ½É}±¥¹•}ÕÍ•É}¥ˆ°(€€€€‰É…¹Ñ••}±¥¹•}ÕÍ•É}¥ˆ°(€€€€‰…•ÁÑ•‘}‰äˆ°(€€€€‰¥¹Ù¥Ñ•‘}‰äˆ°(€€€€‰Ñ…É•Ğˆ°)ô()}5%IQ%=9}II9}1%MQ}%1L€ôì(€€€€‰…‘µ¥¹}±¥¹•}ÕÍ•É}¥‘Ìˆ°(€€€€‰µ•µ‰•É}¥‘Í}…Ñ}‰¥¹ˆ°(€€€€‰µ•µ‰•É}±¥¹•}ÕÍ•É}¥‘Ìˆ°(€€€€‰µ•µ‰•É}ÕÍ•É}¥‘Ìˆ°(€€€€‰µ•µ‰•ÉÌˆ°(€€€€‰™É¥•¹‘Ìˆ°(€€€€‰Õ…É‘¥¹}™½Èˆ°)ô()}5%IQ%=9}Q=A}1Y1}=11Q%=9}-eL€ôì(€€€€‰½É‘•ÉÌˆè€ ‰½É‘•É}¥ˆ°€‰µ•É¡…¹Ñ}½É‘•É}¥ˆ°€‰µ•É¡…¹Ñ}ÑÉ…‘•}¹¼ˆ¤°(€€€€‰Á…åµ•¹Ñ}É•½É‘Ìˆè€ ‰ÑÉ…¹Í…Ñ¥½¹}¥ˆ°€‰½É‘•É}¥ˆ°€‰µ•É¡…¹Ñ}½É‘•É}¥ˆ¤°(€€€€‰Á…åµ•¹ÑÌˆè€ ‰ÑÉ…¹Í…Ñ¥½¹}¥ˆ°€‰½É‘•É}¥ˆ°€‰µ•É¡…¹Ñ}½É‘•É}¥ˆ¤°(€€€€‰ÍÕÁÁ½ÉÑ}Ñ¥­•ÑÌˆè€ ‰¥ˆ°€‰Ñ¥­•Ñ}¥ˆ¤°(€€€€‰ÁÉ¥Ù…å}É•ÅÕ•ÍÑÌˆè€ ‰¥ˆ°€‰É•ÅÕ•ÍÑ}¥ˆ¤°(€€€€‰¹½Ñ¥™¥…Ñ¥½¹}±½Ìˆè€ ‰¥ˆ°€‰±½}¥ˆ°€‰•Ù•¹Ñ}¥ˆ¤°(€€€€‰¡•­¥¹}İ…É¹¥¹Ìˆè€ ‰¥ˆ°€‰•Ù•¹Ñ}¥ˆ°€‰±½}¥ˆ¤°(€€€€‰¡•­¥¹}İ…É¹¥¹}±½Ìˆè€ ‰¥ˆ°€‰•Ù•¹Ñ}¥ˆ°€‰±½}¥ˆ¤°(€€€€‰Í½Í}±½Ìˆè€ ‰¥ˆ°€‰•Ù•¹Ñ}¥ˆ°€‰±½}¥ˆ¤°(€€€€‰½¹Ñ…Ñ}É•İ…É‘Ìˆè€ ‰¥ˆ°€‰É•İ…É‘}¥ˆ¤°)ô()}5%IQ%=9}%9a}-eL€ôì(€€€€‰Í½Í}Á•¹‘¥¹œˆ°(€€€€‰±½…Ñ¥½¹}É…¹ÑÌˆ°(€€€€‰¡•­¥¹}İ…É¹¥¹}¥¹‘•àˆ°(€€€€‰±½…Ñ¥½¹}É…¹Ñ}¥¹‘•àˆ°)ô(()‘•˜}É•¥¹‘•á}µ¥É…Ñ¥½¹}É•½É¡É•½É°½±‘}¥°¹•İ}¥°µ¥É…Ñ¥½¹}•Ù•¹Ñ}¥¤è(€€€¥˜¹½Ğ¥Í¥¹ÍÑ…¹”¡É•½É°‘¥Ğ¤è(€€€€€€€É•ÑÕÉ¸…±Í”(€€€¡…¹•€ô…±Í”(€€€™½È­•ä°Ù…±Õ”¥¸±¥ÍĞ¡É•½É¹¥Ñ•µÌ ¤¤è(€€€€€€€¥˜­•ä¥¸}5%IQ%=9}II9}M1I}%1Lè(€€€€€€€€€€€¥˜ÍÑÈ¡Ù…±Õ”½È€ˆˆ¤€ôô½±‘}¥è(€€€€€€€€€€€€€€€É•½É‘m­•åt€ô¹•İ}¥(€€€€€€€€€€€€€€€¡…¹•€ôQÉÕ”(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¥˜­•ä¥¸}5%IQ%=9}II9}1%MQ}%1L…¹¥Í¥¹ÍÑ…¹”¡Ù…±Õ”°±¥ÍĞ¤è(€€€€€€€€€€€É•Á±…•€ômt(€€€€€€€€€€€±¥ÍÑ}¡…¹•€ô…±Í”(€€€€€€€€€€€™½È¥Ñ•´¥¸Ù…±Õ”è(€€€€€€€€€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡¥Ñ•´°‘¥Ğ¤è(€€€€€€€€€€€€€€€€€€€¹•ÍÑ•‘}¡…¹•€ô}É•¥¹‘•á}µ¥É…Ñ¥½¹}É•½É (€€€€€€€€€€€€€€€€€€€€€€€¥Ñ•´°(€€€€€€€€€€€€€€€€€€€€€€€½±‘}¥°(€€€€€€€€€€€€€€€€€€€€€€€¹•İ}¥°(€€€€€€€€€€€€€€€€€€€€€€€µ¥É…Ñ¥½¹}•Ù•¹Ñ}¥°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€±¥ÍÑ}¡…¹•€ô±¥ÍÑ}¡…¹•½È¹•ÍÑ•‘}¡…¹•(€€€€€€€€€€€€€€€€€€€É•Á±…•¹…ÁÁ•¹¡¥Ñ•´¤(€€€€€€€€€€€€€€€•±¥˜ÍÑÈ¡¥Ñ•´½È€ˆˆ¤€ôô½±‘}¥è(€€€€€€€€€€€€€€€€€€€É•Á±…•¹…ÁÁ•¹¡¹•İ}¥¤(€€€€€€€€€€€€€€€€€€€±¥ÍÑ}¡…¹•€ôQÉÕ”(€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€É•Á±…•¹…ÁÁ•¹¡¥Ñ•´¤(€€€€€€€€€€€¥˜±¥ÍÑ}¡…¹•è(€€€€€€€€€€€€€€€‘•‘ÕÁ•€ômt(€€€€€€€€€€€€€€€Í••¹}Í…±…ÉÌ€ôÍ•Ğ ¤(€€€€€€€€€€€€€€€™½È¥Ñ•´¥¸É•Á±…•è(€€€€€€€€€€€€€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡¥Ñ•´°‘¥Ğ¤è(€€€€€€€€€€€€€€€€€€€€€€€‘•‘ÕÁ•¹…ÁÁ•¹¡¥Ñ•´¤(€€€€€€€€€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€€€€€€€€€µ…É­•È€ôÍÑÈ¡¥Ñ•´¤(€€€€€€€€€€€€€€€€€€€¥˜µ…É­•È¥¸Í••¹}Í…±…ÉÌè(€€€€€€€€€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€€€€€€€€€Í••¹}Í…±…ÉÌ¹…‘¡µ…É­•È¤(€€€€€€€€€€€€€€€€€€€‘•‘ÕÁ•¹…ÁÁ•¹¡¥Ñ•´¤(€€€€€€€€€€€€€€€É•½É‘m­•åt€ô‘•‘ÕÁ•(€€€€€€€€€€€€€€€¡…¹•€ôQÉÕ”(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡Ù…±Õ”°‘¥Ğ¤è(€€€€€€€€€€€¡…¹•€ô€ (€€€€€€€€€€€€€€€}É•¥¹‘•á}µ¥É…Ñ¥½¹}É•½É (€€€€€€€€€€€€€€€€€€€Ù…±Õ”°(€€€€€€€€€€€€€€€€€€€½±‘}¥°(€€€€€€€€€€€€€€€€€€€¹•İ}¥°(€€€€€€€€€€€€€€€€€€€µ¥É…Ñ¥½¹}•Ù•¹Ñ}¥°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€½È¡…¹•(€€€€€€€€€€€€¤(€€€€€€€•±¥˜¥Í¥¹ÍÑ…¹”¡Ù…±Õ”°±¥ÍĞ¤è(€€€€€€€€€€€™½È¥Ñ•´¥¸Ù…±Õ”è(€€€€€€€€€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡¥Ñ•´°‘¥Ğ¤è(€€€€€€€€€€€€€€€€€€€¡…¹•€ô€ (€€€€€€€€€€€€€€€€€€€€€€€}É•¥¹‘•á}µ¥É…Ñ¥½¹}É•½É (€€€€€€€€€€€€€€€€€€€€€€€€€€€¥Ñ•´°(€€€€€€€€€€€€€€€€€€€€€€€€€€€½±‘}¥°(€€€€€€€€€€€€€€€€€€€€€€€€€€€¹•İ}¥°(€€€€€€€€€€€€€€€€€€€€€€€€€€€µ¥É…Ñ¥½¹}•Ù•¹Ñ}¥°(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€½È¡…¹•(€€€€€€€€€€€€€€€€€€€€¤(€€€¥˜¡…¹•è(€€€€€€€É•½É‘l‰µ¥É…Ñ¥½¹}•Ù•¹Ñ}¥‰t€ôµ¥É…Ñ¥½¹}•Ù•¹Ñ}¥(€€€É•ÑÕÉ¸¡…¹•(()‘•˜}‘•‘ÕÁ•}µ¥É…Ñ¥½¹}½±±•Ñ¥½¸¡É½İÌ°ÍÑ…‰±•}­•åÌ°ÁÉ•™¥à°µ¥É…Ñ¥½¹}•Ù•¹Ñ}¥¤è(€€€‘•‘ÕÁ•€ômt(€€€Á½Í¥Ñ¥½¹Ì€ôíô(€€€ÕÍ•‘}¥‘Ì€ôì(€€€€€€€ÍÑÈ¡É½Ü¹•Ğ ‰¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€™½ÈÉ½Ü¥¸É½İÌ(€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡É½Ü°‘¥Ğ¤…¹ÍÑÈ¡É½Ü¹•Ğ ‰¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€ô(€€€•¹•É…Ñ•‘}¥¹‘•à€ô€À(€€€™½ÈÉ½Ü¥¸É½İÌè(€€€€€€€¥˜¹½Ğ¥Í¥¹ÍÑ…¹”¡É½Ü°‘¥Ğ¤è(€€€€€€€€€€€‘•‘ÕÁ•¹…ÁÁ•¹¡É½Ü¤(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€ÍÑ…‰±”€ô}µ¥É…Ñ¥½¹}ÍÑ…‰±•}Ù…±Õ”¡É½Ü°ÍÑ…‰±•}­•åÌ¤(€€€€€€€¥˜¹½ĞÍÑ…‰±”è(€€€€€€€€€€€•¹•É…Ñ•‘}¥¹‘•à€¬ô€Ä(€€€€€€€€€€€•¹•É…Ñ•€ô˜‰µ¥É…Ñ¥½¸µíÁÉ•™¥áôµí•¹•É…Ñ•‘}¥¹‘•àèÀÑ‘ôˆ(€€€€€€€€€€€İ¡¥±”•¹•É…Ñ•¥¸ÕÍ•‘}¥‘Ìè(€€€€€€€€€€€€€€€•¹•É…Ñ•‘}¥¹‘•à€¬ô€Ä(€€€€€€€€€€€€€€€•¹•É…Ñ•€ô˜‰µ¥É…Ñ¥½¸µíÁÉ•™¥áôµí•¹•É…Ñ•‘}¥¹‘•àèÀÑ‘ôˆ(€€€€€€€€€€€É½İl‰¥‰t€ô•¹•É…Ñ•(€€€€€€€€€€€ÕÍ•‘}¥‘Ì¹…‘¡•¹•É…Ñ•¤(€€€€€€€€€€€‘•‘ÕÁ•¹…ÁÁ•¹¡É½Ü¤(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¥˜ÍÑ…‰±”¹½Ğ¥¸Á½Í¥Ñ¥½¹Ìè(€€€€€€€€€€€Á½Í¥Ñ¥½¹ÍmÍÑ…‰±•t€ô±•¸¡‘•‘ÕÁ•¤(€€€€€€€€€€€‘•‘ÕÁ•¹…ÁÁ•¹¡É½Ü¤(€€€€€€€€€€€½¹Ñ¥¹Õ”((€€€€€€€Á½Í¥Ñ¥½¸€ôÁ½Í¥Ñ¥½¹ÍmÍÑ…‰±•t(€€€€€€€ÁÉ•Ù¥½ÕÌ€ô‘•‘ÕÁ•‘mÁ½Í¥Ñ¥½¹t(€€€€€€€İ¥¹¹•È€ô}µ¥É…Ñ¥½¹}¡½½Í•}É•½É¡ÁÉ•Ù¥½ÕÌ°É½Ü¤(€€€€€€€±½Í•È€ôÉ½Ü¥˜İ¥¹¹•È€ôôÁÉ•Ù¥½ÕÌ•±Í”ÁÉ•Ù¥½ÕÌ(€€€€€€€½µ‰¥¹•€ô½Áä¹‘••Á½Áä¡±½Í•È¤(€€€€€€€½µ‰¥¹•¹ÕÁ‘…Ñ”¡İ¥¹¹•È¤(€€€€€€€½µ‰¥¹•‘l‰µ¥É…Ñ¥½¹}•Ù•¹Ñ}¥‰t€ôµ¥É…Ñ¥½¹}•Ù•¹Ñ}¥(€€€€€€€‘•‘ÕÁ•‘mÁ½Í¥Ñ¥½¹t€ô½µ‰¥¹•(€€€É•ÑÕÉ¸‘•‘ÕÁ•(()‘•˜É•¥¹‘•á}…½Õ¹Ñ}É•™•É•¹•Ì (€€€ÍÑ…Ñ”°(€€€½±‘}¥°(€€€¹•İ}¥°(€€€µ¥É…Ñ¥½¹}•Ù•¹Ñ}¥°(€€€¹½Üõ9½¹”°(¤è(€€€€ˆˆ‰I•Á±…”•á…Ğ…½Õ¹ĞÉ•™•É•¹•Ìİ¥Ñ¡½ÕĞÉ•İÉ¥Ñ¥¹œ¡¥ÍÑ½É¥…°ÁÉ½Í”¸ˆˆˆ(€€€Í½ÕÉ•}¥€ôÍÑÈ¡½±‘}¥½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€Ñ…É•Ñ}¥€ôÍÑÈ¡¹•İ}¥½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€¥˜¹½ĞÍ½ÕÉ•}¥½È¹½ĞÑ…É•Ñ}¥è(€€€€€€€É…¥Í”Y…±Õ•ÉÉ½È ‰µ¥ÍÍ¥¹}¥‘•¹Ñ¥Ñäˆ¤(€€€¥˜Í½ÕÉ•}¥€ôôÑ…É•Ñ}¥è(€€€€€€€É…¥Í”Y…±Õ•ÉÉ½È ‰Í…µ•}¥‘•¹Ñ¥Ñäˆ¤((€€€•Ù•¹Ñ}¥€ôÍÑÈ¡µ¥É…Ñ¥½¹}•Ù•¹Ñ}¥½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€¥˜¹½Ğ•Ù•¹Ñ}¥è(€€€€€€€É…¥Í”Y…±Õ•ÉÉ½È ‰µ¥ÍÍ¥¹}µ¥É…Ñ¥½¹}•Ù•¹Ğˆ¤(€€€É•¥¹‘•á•‘}É•½É‘Ì€ô€À((€€€™½ÈÕÍ•É}¥°ÁÉ½™¥±”¥¸€¡ÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ¤½Èíô¤¹¥Ñ•µÌ ¤è(€€€€€€€¥˜ÕÍ•É}¥¥¸íÍ½ÕÉ•}¥°Ñ…É•Ñ}¥‘ô½È¹½Ğ¥Í¥¹ÍÑ…¹”¡ÁÉ½™¥±”°‘¥Ğ¤è(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¥˜}É•¥¹‘•á}µ¥É…Ñ¥½¹}É•½É¡ÁÉ½™¥±”°Í½ÕÉ•}¥°Ñ…É•Ñ}¥°•Ù•¹Ñ}¥¤è(€€€€€€€€€€€É•¥¹‘•á•‘}É•½É‘Ì€¬ô€Ä((€€€™½ÈÉ½ÕÀ¥¸€¡ÍÑ…Ñ”¹•Ğ ‰Õ…É‘¥…¹}É½ÕÁÌˆ¤½Èíô¤¹Ù…±Õ•Ì ¤è(€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡É½ÕÀ°‘¥Ğ¤…¹}É•¥¹‘•á}µ¥É…Ñ¥½¹}É•½É (€€€€€€€€€€€É½ÕÀ°(€€€€€€€€€€€Í½ÕÉ•}¥°(€€€€€€€€€€€Ñ…É•Ñ}¥°(€€€€€€€€€€€•Ù•¹Ñ}¥°(€€€€€€€€¤è(€€€€€€€€€€€É•¥¹‘•á•‘}É•½É‘Ì€¬ô€Ä((€€€™½È¥¹Ù¥Ñ”¥¸€¡ÍÑ…Ñ”¹•Ğ ‰™É¥•¹‘}¥¹Ù¥Ñ•Ìˆ¤½Èíô¤¹Ù…±Õ•Ì ¤è(€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡¥¹Ù¥Ñ”°‘¥Ğ¤…¹}É•¥¹‘•á}µ¥É…Ñ¥½¹}É•½É (€€€€€€€€€€€¥¹Ù¥Ñ”°(€€€€€€€€€€€Í½ÕÉ•}¥°(€€€€€€€€€€€Ñ…É•Ñ}¥°(€€€€€€€€€€€•Ù•¹Ñ}¥°(€€€€€€€€¤è(€€€€€€€€€€€É•¥¹‘•á•‘}É•½É‘Ì€¬ô€Ä((€€€™½È½±±•Ñ¥½¹}­•ä°ÍÑ…‰±•}­•åÌ¥¸}5%IQ%=9}Q=A}1Y1}=11Q%=9}-eL¹¥Ñ•µÌ ¤è(€€€€€€€É½İÌ€ôÍÑ…Ñ”¹•Ğ¡½±±•Ñ¥½¹}­•ä¤½Èmt(€€€€€€€¥˜¹½Ğ¥Í¥¹ÍÑ…¹”¡É½İÌ°±¥ÍĞ¤è(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€™½ÈÉ½Ü¥¸É½İÌè(€€€€€€€€€€€¥˜¹½Ğ¥Í¥¹ÍÑ…¹”¡É½Ü°‘¥Ğ¤è(€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€¥˜}É•¥¹‘•á}µ¥É…Ñ¥½¹}É•½É (€€€€€€€€€€€€€€€É½Ü°(€€€€€€€€€€€€€€€Í½ÕÉ•}¥°(€€€€€€€€€€€€€€€Ñ…É•Ñ}¥°(€€€€€€€€€€€€€€€•Ù•¹Ñ}¥°(€€€€€€€€€€€€¤è(€€€€€€€€€€€€€€€É•¥¹‘•á•‘}É•½É‘Ì€¬ô€Ä(€€€€€€€ÍÑ…Ñ•m½±±•Ñ¥½¹}­•åt€ô}‘•‘ÕÁ•}µ¥É…Ñ¥½¹}½±±•Ñ¥½¸ (€€€€€€€€€€€É½İÌ°(€€€€€€€€€€€ÍÑ…‰±•}­•åÌ°(€€€€€€€€€€€½±±•Ñ¥½¹}­•ä¹É•Á±…” ‰|ˆ°€ˆ´ˆ¤°(€€€€€€€€€€€•Ù•¹Ñ}¥°(€€€€€€€€¤((€€€™½È¥¹‘•á}­•ä¥¸}5%IQ%=9}%9a}-eLè(€€€€€€€¥¹‘•à€ôÍÑ…Ñ”¹•Ğ¡¥¹‘•á}­•ä¤½Èíô(€€€€€€€¥˜¹½Ğ¥Í¥¹ÍÑ…¹”¡¥¹‘•à°‘¥Ğ¤è(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€İ…Í}É•­•å•€ôÍ½ÕÉ•}¥¥¸¥¹‘•à(€€€€€€€¥˜Í½ÕÉ•}¥¥¸¥¹‘•àè(€€€€€€€€€€€Í½ÕÉ•}É•½É€ô¥¹‘•à¹Á½À¡Í½ÕÉ•}¥¤(€€€€€€€€€€€¥˜Ñ…É•Ñ}¥¥¸¥¹‘•àè(€€€€€€€€€€€€€€€¥¹‘•ámÑ…É•Ñ}¥‘t€ô}µ¥É…Ñ¥½¹}¡½½Í•}É•½É (€€€€€€€€€€€€€€€€€€€Í½ÕÉ•}É•½É°(€€€€€€€€€€€€€€€€€€€¥¹‘•ámÑ…É•Ñ}¥‘t°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€¥¹‘•ámÑ…É•Ñ}¥‘t€ôÍ½ÕÉ•}É•½É(€€€€€€€É•½É€ô¥¹‘•à¹•Ğ¡Ñ…É•Ñ}¥¤(€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡É•½É°‘¥Ğ¤è(€€€€€€€€€€€¡…¹•€ô}É•¥¹‘•á}µ¥É…Ñ¥½¹}É•½É (€€€€€€€€€€€€€€€É•½É°(€€€€€€€€€€€€€€€Í½ÕÉ•}¥°(€€€€€€€€€€€€€€€Ñ…É•Ñ}¥°(€€€€€€€€€€€€€€€•Ù•¹Ñ}¥°(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜¡…¹•½Èİ…Í}É•­•å•è(€€€€€€€€€€€€€€€É•½É‘l‰µ¥É…Ñ¥½¹}•Ù•¹Ñ}¥‰t€ô•Ù•¹Ñ}¥(€€€€€€€€€€€€€€€É•¥¹‘•á•‘}É•½É‘Ì€¬ô€Ä(€€€€€€€ÍÑ…Ñ•m¥¹‘•á}­•åt€ô¥¹‘•à((€€€É•ÑÕÉ¸ì‰½¬ˆèQÉÕ”°€‰É•¥¹‘•á•‘}É•½É‘ÌˆèÉ•¥¹‘•á•‘}É•½É‘Íô(()‘•˜É•…Ñ•}…½Õ¹Ñ}µ¥É…Ñ¥½¹}…±¥…Ì¡ÍÑ…Ñ”°½±‘}¥°¹•İ}¥°¹½Üõ9½¹”¤è(€€€Í½ÕÉ•}¥€ôÍÑÈ¡½±‘}¥½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€Ñ…É•Ñ}¥€ôÍÑÈ¡¹•İ}¥½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€¥˜¹½ĞÍ½ÕÉ•}¥½È¹½ĞÑ…É•Ñ}¥è(€€€€€€€É…¥Í”Y…±Õ•ÉÉ½È ‰µ¥ÍÍ¥¹}¥‘•¹Ñ¥Ñäˆ¤(€€€¥˜Í½ÕÉ•}¥€ôôÑ…É•Ñ}¥è(€€€€€€€É…¥Í”Y…±Õ•ÉÉ½È ‰Í…µ•}¥‘•¹Ñ¥Ñäˆ¤(€€€ÕÉÉ•¹Ñ}¥Í¼€ô}…½Õ¹Ñ}µ¥É…Ñ¥½¹}¹½Ü¡¹½Ü¤¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤(€€€ÍÑ…Ñ”¹Í•Ñ‘•™…Õ±Ğ ‰…½Õ¹Ñ}µ¥É…Ñ¥½¹}…±¥…Í•Ìˆ°íô¥mÍ½ÕÉ•}¥‘t€ôì(€€€€€€€€‰Ñ…É•Ñ}±¥¹•}ÕÍ•É}¥ˆèÑ…É•Ñ}¥°(€€€€€€€€‰É•…Ñ•‘}…ĞˆèÕÉÉ•¹Ñ}¥Í¼°(€€€€€€€€‰ÍÑ…ÑÕÌˆè€‰‘¥Í…‰±•ˆ°(€€€ô(€€€É•ÑÕÉ¸ÍÑ…Ñ•l‰…½Õ¹Ñ}µ¥É…Ñ¥½¹}…±¥…Í•Ì‰umÍ½ÕÉ•}¥‘t(()‘•˜}…½Õ¹Ñ}µ¥É…Ñ¥½¹}É•½É‘}É•™•É•¹•Ì¡É•½É°±¥¹•}ÕÍ•É}¥¤è(€€€¥˜¹½Ğ¥Í¥¹ÍÑ…¹”¡É•½É°‘¥Ğ¤è(€€€€€€€É•ÑÕÉ¸…±Í”(€€€É•ÑÕÉ¸…¹ä (€€€€€€€ÍÑÈ¡É•½É¹•Ğ¡­•ä¤½È€ˆˆ¤€ôô±¥¹•}ÕÍ•É}¥(€€€€€€€™½È­•ä¥¸}5%IQ%=9}II9}M1I}%1L(€€€€¤(()‘•˜}…½Õ¹Ñ}µ¥É…Ñ¥½¹}Í…™•}½Õ¹ÑÌ¡ÍÑ…Ñ”°ÁÉ½™¥±”°±¥¹•}ÕÍ•É}¥¤è(€€€‘•˜½İ¹•‘}½Õ¹Ğ¡½±±•Ñ¥½¹}­•ä¤è(€€€€€€€É•ÑÕÉ¸ÍÕ´ (€€€€€€€€€€€€Ä(€€€€€€€€€€€™½ÈÉ•½É¥¸€¡ÍÑ…Ñ”¹•Ğ¡½±±•Ñ¥½¹}­•ä¤½Èmt¤(€€€€€€€€€€€¥˜}…½Õ¹Ñ}µ¥É…Ñ¥½¹}É•½É‘}É•™•É•¹•Ì¡É•½É°±¥¹•}ÕÍ•É}¥¤(€€€€€€€€¤((€€€É•ÑÕÉ¸ì(€€€€€€€€‰¡•­¥¹Ìˆè±•¸¡ÁÉ½™¥±”¹•Ğ ‰¡¥ÍÑ½Éäˆ¤½Èmt¤°(€€€€€€€€‰½¹Ñ…ÑÌˆè±•¸¡ÁÉ½™¥±”¹•Ğ ‰½¹Ñ…ÑÌˆ¤½Èmt¤°(€€€€€€€€‰É½ÕÁÌˆè±•¸¡ÁÉ½™¥±”¹•Ğ ‰Õ…É‘¥…¹}É½ÕÁ}¥‘Ìˆ¤½Èmt¤°(€€€€€€€€‰É•µ¥¹‘•ÉÌˆè±•¸¡ÁÉ½™¥±”¹•Ğ ‰Íµ…ÉÑ}É•µ¥¹‘•ÉÌˆ¤½Èmt¤°(€€€€€€€€‰½É‘•ÉÌˆè½İ¹•‘}½Õ¹Ğ ‰½É‘•ÉÌˆ¤°(€€€€€€€€‰É•ÅÕ•ÍÑÌˆè€ (€€€€€€€€€€€½İ¹•‘}½Õ¹Ğ ‰ÍÕÁÁ½ÉÑ}Ñ¥­•ÑÌˆ¤(€€€€€€€€€€€€¬½İ¹•‘}½Õ¹Ğ ‰ÁÉ¥Ù…å}É•ÅÕ•ÍÑÌˆ¤(€€€€€€€€¤°(€€€ô(()‘•˜}…ÁÁ•¹‘}…½Õ¹Ñ}µ¥É…Ñ¥½¹}™…¥±ÕÉ•}…Õ‘¥Ğ¡ÍÑ…Ñ”°…Ñ•½Éä°¹½Ü¤è(€€€ÁÕÉ•}…½Õ¹Ñ}µ¥É…Ñ¥½¹}¡¥ÍÑ½Éä¡ÍÑ…Ñ”°¹½Ü¤(€€€ÍÑ…Ñ”¹Í•Ñ‘•™…Õ±Ğ ‰…½Õ¹Ñ}µ¥É…Ñ¥½¹}…Õ‘¥Ğˆ°mt¤¹…ÁÁ•¹¡ì(€€€€€€€€‰•Ù•¹Ñ}¥ˆè˜‰…µ•}íÍ•É•ÑÌ¹Ñ½­•¹}ÕÉ±Í…™” ÄÈ¥ôˆ°(€€€€€€€€‰ÍÑ…ÑÕÌˆè€‰™…¥±•ˆ°(€€€€€€€€‰É•…Ñ•‘}…Ğˆè¹½Ü¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤°(€€€€€€€€‰™…¥±ÕÉ•}…Ñ•½ÉäˆèÍÑÈ¡…Ñ•½Éä¤°(€€€€€€€€‰½Õ¹ÑÌˆèì(€€€€€€€€€€€€‰¡•­¥¹Ìˆè€À°(€€€€€€€€€€€€‰½¹Ñ…ÑÌˆè€À°(€€€€€€€€€€€€‰É½ÕÁÌˆè€À°(€€€€€€€€€€€€‰É•µ¥¹‘•ÉÌˆè€À°(€€€€€€€€€€€€‰½É‘•ÉÌˆè€À°(€€€€€€€€€€€€‰É•ÅÕ•ÍÑÌˆè€À°(€€€€€€€ô°(€€€ô¤(€€€ÍÑ…Ñ•l‰…½Õ¹Ñ}µ¥É…Ñ¥½¹}…Õ‘¥Ğ‰t€ôÍÑ…Ñ•l‰…½Õ¹Ñ}µ¥É…Ñ¥½¹}…Õ‘¥Ğ‰ul(€€€€€€€€µ=U9Q}5%IQ%=9}U%Q}1=	1}5`è(€€€t(()‘•˜}…½Õ¹Ñ}µ¥É…Ñ¥½¹}Í¹…ÁÍ¡½Ğ (€€€ÍÑ…Ñ”°(€€€Ñ¥­•Ğ°(€€€½±‘}±¥¹•}ÕÍ•É}¥°(€€€¹•İ}±¥¹•}ÕÍ•É}¥°(€€€•Ù•¹Ñ}¥°(€€€¹½Ü°(¤è(€€€ÕÍ•ÉÌ€ôÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ¤½Èíô(€€€…™™•Ñ•‘}ÕÍ•ÉÌ€ôíô(€€€™½ÈÕÍ•É}¥°ÁÉ½™¥±”¥¸ÕÍ•ÉÌ¹¥Ñ•µÌ ¤è(€€€€€€€¥˜€ (€€€€€€€€€€€ÕÍ•É}¥¥¸í½±‘}±¥¹•}ÕÍ•É}¥°¹•İ}±¥¹•}ÕÍ•É}¥‘ô(€€€€€€€€€€€½È¹½Ğ¥Í¥¹ÍÑ…¹”¡ÁÉ½™¥±”°‘¥Ğ¤(€€€€€€€€¤è(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€É•¥¹‘•á•‘}ÁÉ½‰”€ô½Áä¹‘••Á½Áä¡ÁÉ½™¥±”¤(€€€€€€€¥˜}É•¥¹‘•á}µ¥É…Ñ¥½¹}É•½É (€€€€€€€€€€€É•¥¹‘•á•‘}ÁÉ½‰”°(€€€€€€€€€€€½±‘}±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€¹•İ}±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€•Ù•¹Ñ}¥°(€€€€€€€€¤è(€€€€€€€€€€€…™™•Ñ•‘}ÕÍ•ÉÍmÕÍ•É}¥‘t€ô½Áä¹‘••Á½Áä¡ÁÉ½™¥±”¤(€€€…™™•Ñ•‘}­•åÌ€ôì(€€€€€€€€‰Õ…É‘¥…¹}É½ÕÁÌˆ°(€€€€€€€€‰™É¥•¹‘}¥¹Ù¥Ñ•Ìˆ°(€€€€€€€€‰…½Õ¹Ñ}µ¥É…Ñ¥½¹}…±¥…Í•Ìˆ°(€€€€€€€€©}5%IQ%=9}Q=A}1Y1}=11Q%=9}-eL°(€€€€€€€€©}5%IQ%=9}%9a}-eL°(€€€ô(€€€Í¹…ÁÍ¡½Ñ}¥€ô˜‰…µÍ}íÍ•É•ÑÌ¹Ñ½­•¹}ÕÉ±Í…™” ÄÈ¥ôˆ(€€€É•ÑÕÉ¸Í¹…ÁÍ¡½Ñ}¥°ì(€€€€€€€€‰Í¹…ÁÍ¡½Ñ}¥ˆèÍ¹…ÁÍ¡½Ñ}¥°(€€€€€€€€‰•Ù•¹Ñ}¥ˆè•Ù•¹Ñ}¥°(€€€€€€€€‰É•…Ñ•‘}…Ğˆè¹½Ü¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤°(€€€€€€€€‰ÁÕÉ•}…™Ñ•Èˆè€¡¹½Ü€¬Ñ¥µ•‘•±Ñ„¡‘…åÌôÌÀ¤¤¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤°(€€€€€€€€‰½±‘}ÁÉ½™¥±”ˆè½Áä¹‘••Á½Áä¡ÕÍ•ÉÌ¹•Ğ¡½±‘}±¥¹•}ÕÍ•É}¥¤¤°(€€€€€€€€‰¹•İ}ÁÉ½™¥±”ˆè€ (€€€€€€€€€€€½Áä¹‘••Á½Áä¡ÕÍ•ÉÌ¹•Ğ¡¹•İ}±¥¹•}ÕÍ•É}¥¤¤(€€€€€€€€€€€¥˜¹•İ}±¥¹•}ÕÍ•É}¥¥¸ÕÍ•ÉÌ(€€€€€€€€€€€•±Í”9½¹”(€€€€€€€€¤°(€€€€€€€€‰µ¥É…Ñ¥½¹}Ñ¥­•Ğˆè½Áä¹‘••Á½Áä¡Ñ¥­•Ğ¤°(€€€€€€€€‰…™™•Ñ•‘}ÕÍ•ÉÌˆè…™™•Ñ•‘}ÕÍ•ÉÌ°(€€€€€€€€‰…™™•Ñ•‘}Ñ½Á}±•Ù•±}É•½É‘Ìˆèì(€€€€€€€€€€€­•äè½Áä¹‘••Á½Áä¡ÍÑ…Ñ”¹•Ğ¡­•ä¤¤(€€€€€€€€€€€™½È­•ä¥¸Í½ÉÑ•¡…™™•Ñ•‘}­•åÌ¤(€€€€€€€€€€€¥˜­•ä¥¸ÍÑ…Ñ”(€€€€€€€ô°(€€€ô(()‘•˜É•‘••µ}…½Õ¹Ñ}µ¥É…Ñ¥½¹}Ñ¥­•Ğ (€€€‘…Ñ…}™¥±”°(€€€½‘”°(€€€¹•İ}±¥¹•}ÕÍ•É}¥°(€€€½¹™¥œ°(€€€¹½Üõ9½¹”°(¤è(€€€¥˜¹½Ğ…½Õ¹Ñ}µ¥É…Ñ¥½¹}É•…‘ä¡½¹™¥œ¤è(€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰µ¥É…Ñ¥½¹}Õ¹…Ù…¥±…‰±”‰ô°€ÔÀÌ((€€€ÕÉÉ•¹Ğ€ô}…½Õ¹Ñ}µ¥É…Ñ¥½¹}¹½Ü¡¹½Ü¤(€€€Ù•É¥™¥•‘}¹•İ}¥€ôÍÑÈ¡¹•İ}±¥¹•}ÕÍ•É}¥½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€É…İ}½‘”€ôÍÑÈ¡½‘”½È€ˆˆ¤¹ÍÑÉ¥À ¤((€€€‘•˜µÕÑ…Ñ”¡ÍÑ…Ñ”¤è(€€€€€€€ÁÕÉ•}…½Õ¹Ñ}µ¥É…Ñ¥½¹}¡¥ÍÑ½Éä¡ÍÑ…Ñ”°ÕÉÉ•¹Ğ¤(€€€€€€€¥¹Ù…±¥‘}ÕÑ½™˜€ôÕÉÉ•¹Ğ€´Ñ¥µ•‘•±Ñ„ (€€€€€€€€€€€Í•½¹‘Ìõ=U9Q}5%IQ%=9}%9Y1%}I5}]%9=]}M=9L(€€€€€€€€¤(€€€€€€€¥¹Ù…±¥‘}É••¹Ğ€ôÍÕ´ (€€€€€€€€€€€€Ä(€€€€€€€€€€€™½È•Ù•¹Ğ¥¸€¡ÍÑ…Ñ”¹•Ğ ‰…½Õ¹Ñ}µ¥É…Ñ¥½¹}…Õ‘¥Ğˆ¤½Èmt¤(€€€€€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡•Ù•¹Ğ°‘¥Ğ¤(€€€€€€€€€€€…¹•Ù•¹Ğ¹•Ğ ‰™…¥±ÕÉ•}…Ñ•½Éäˆ¤€ôô€‰¥¹Ù…±¥‘}½‘”ˆ(€€€€€€€€€€€…¹€ (€€€€€€€€€€€€€€€}…½Õ¹Ñ}µ¥É…Ñ¥½¹}‘…Ñ•Ñ¥µ”¡•Ù•¹Ğ¹•Ğ ‰É•…Ñ•‘}…Ğˆ¤¤(€€€€€€€€€€€€€€€…¹}…½Õ¹Ñ}µ¥É…Ñ¥½¹}‘…Ñ•Ñ¥µ”¡•Ù•¹Ğ¹•Ğ ‰É•…Ñ•‘}…Ğˆ¤¤(€€€€€€€€€€€€€€€€øô¥¹Ù…±¥‘}ÕÑ½™˜(€€€€€€€€€€€€¤(€€€€€€€€¤(€€€€€€€¥˜¥¹Ù…±¥‘}É••¹Ğ€øô=U9Q}5%IQ%=9}%9Y1%}I5}5a}AI}]%9=\è(€€€€€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰É…Ñ•}±¥µ¥Ñ•‰ô°€ĞÈä(€€€€€€€Ñ¥­•Ğ°Ñ¥­•Ñ}•ÉÉ½È€ôÙ…±¥‘…Ñ•}…½Õ¹Ñ}µ¥É…Ñ¥½¹}Ñ¥­•Ğ (€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€É…İ}½‘”°(€€€€€€€€€€€½¹™¥œ¹•Ğ ‰=U9Q}5%IQ%=9}MIPˆ¤°(€€€€€€€€€€€¹½ÜõÕÉÉ•¹Ğ°(€€€€€€€€¤(€€€€€€€•ÉÉ½É}ÍÑ…ÑÕÍ•Ì€ôì(€€€€€€€€€€€€‰¥¹Ù…±¥‘}½‘”ˆè€ĞÀĞ°(€€€€€€€€€€€€‰•áÁ¥É•‘}½‘”ˆè€ĞÄÀ°(€€€€€€€€€€€€‰ÕÍ•‘}½‘”ˆè€ĞÀä°(€€€€€€€€€€€€‰Í½ÕÉ•}µ¥ÍÍ¥¹œˆè€ĞÀĞ°(€€€€€€€ô(€€€€€€€¥˜Ñ¥­•Ñ}•ÉÉ½Èè(€€€€€€€€€€€}…ÁÁ•¹‘}…½Õ¹Ñ}µ¥É…Ñ¥½¹}™…¥±ÕÉ•}…Õ‘¥Ğ (€€€€€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€€€€€Ñ¥­•Ñ}•ÉÉ½È°(€€€€€€€€€€€€€€€ÕÉÉ•¹Ğ°(€€€€€€€€€€€€¤(€€€€€€€€€€€É•ÑÕÉ¸€ (€€€€€€€€€€€€€€€ì‰½¬ˆè…±Í”°€‰•ÉÉ½ÈˆèÑ¥­•Ñ}•ÉÉ½Éô°(€€€€€€€€€€€€€€€•ÉÉ½É}ÍÑ…ÑÕÍ•Ì¹•Ğ¡Ñ¥­•Ñ}•ÉÉ½È°€ĞÀä¤°(€€€€€€€€€€€€¤((€€€€€€€½±‘}±¥¹•}ÕÍ•É}¥€ôÍÑÈ¡Ñ¥­•Ğ¹•Ğ ‰½±‘}±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€…±¥…Í•Ì€ôÍÑ…Ñ”¹•Ğ ‰…½Õ¹Ñ}µ¥É…Ñ¥½¹}…±¥…Í•Ìˆ¤½Èíô(€€€€€€€¥˜€ (€€€€€€€€€€€¹½ĞÙ•É¥™¥•‘}¹•İ}¥(€€€€€€€€€€€½È½±‘}±¥¹•}ÕÍ•É}¥€ôôÙ•É¥™¥•‘}¹•İ}¥(€€€€€€€€€€€½ÈÙ•É¥™¥•‘}¹•İ}¥¥¸…±¥…Í•Ì(€€€€€€€€¤è(€€€€€€€€€€€}…ÁÁ•¹‘}…½Õ¹Ñ}µ¥É…Ñ¥½¹}™…¥±ÕÉ•}…Õ‘¥Ğ (€€€€€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€€€€€€‰Õ¹Í…™•}½¹™±¥Ğˆ°(€€€€€€€€€€€€€€€ÕÉÉ•¹Ğ°(€€€€€€€€€€€€¤(€€€€€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰Õ¹Í…™•}½¹™±¥Ğ‰ô°€ĞÀä((€€€€€€€ÕÍ•ÉÌ€ôÍÑ…Ñ”¹Í•Ñ‘•™…Õ±Ğ ‰ÕÍ•ÉÌˆ°íô¤(€€€€€€€½±‘}ÁÉ½™¥±”€ôÕÍ•ÉÌ¹•Ğ¡½±‘}±¥¹•}ÕÍ•É}¥¤(€€€€€€€¥˜¹½Ğ¥Í¥¹ÍÑ…¹”¡½±‘}ÁÉ½™¥±”°‘¥Ğ¤è(€€€€€€€€€€€}…ÁÁ•¹‘}…½Õ¹Ñ}µ¥É…Ñ¥½¹}™…¥±ÕÉ•}…Õ‘¥Ğ (€€€€€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€€€€€€‰Í½ÕÉ•}µ¥ÍÍ¥¹œˆ°(€€€€€€€€€€€€€€€ÕÉÉ•¹Ğ°(€€€€€€€€€€€€¤(€€€€€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰Í½ÕÉ•}µ¥ÍÍ¥¹œ‰ô°€ĞÀĞ(€€€€€€€¹•İ}ÁÉ½™¥±”€ôÕÍ•ÉÌ¹•Ğ¡Ù•É¥™¥•‘}¹•İ}¥¤(€€€€€€€¥˜¹•İ}ÁÉ½™¥±”¥Ì¹½Ğ9½¹”…¹¹½Ğ¥Í¥¹ÍÑ…¹”¡¹•İ}ÁÉ½™¥±”°‘¥Ğ¤è(€€€€€€€€€€€}…ÁÁ•¹‘}…½Õ¹Ñ}µ¥É…Ñ¥½¹}™…¥±ÕÉ•}…Õ‘¥Ğ (€€€€€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€€€€€€‰Õ¹Í…™•}½¹™±¥Ğˆ°(€€€€€€€€€€€€€€€ÕÉÉ•¹Ğ°(€€€€€€€€€€€€¤(€€€€€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰Õ¹Í…™•}½¹™±¥Ğ‰ô°€ĞÀä((€€€€€€€•Ù•¹Ñ}¥€ô˜‰…µ•}íÍ•É•ÑÌ¹Ñ½­•¹}ÕÉ±Í…™” ÄÈ¥ôˆ(€€€€€€€Í¹…ÁÍ¡½Ñ}¥°Í¹…ÁÍ¡½Ğ€ô}…½Õ¹Ñ}µ¥É…Ñ¥½¹}Í¹…ÁÍ¡½Ğ (€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€Ñ¥­•Ğ°(€€€€€€€€€€€½±‘}±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€Ù•É¥™¥•‘}¹•İ}¥°(€€€€€€€€€€€•Ù•¹Ñ}¥°(€€€€€€€€€€€ÕÉÉ•¹Ğ°(€€€€€€€€¤(€€€€€€€ÍÑ…Ñ”¹Í•Ñ‘•™…Õ±Ğ ‰…½Õ¹Ñ}µ¥É…Ñ¥½¹}Í¹…ÁÍ¡½ÑÌˆ°íô¥mÍ¹…ÁÍ¡½Ñ}¥‘t€ôÍ¹…ÁÍ¡½Ğ((€€€€€€€µ•É•‘}ÁÉ½™¥±”€ôµ•É•}µ¥É…Ñ¥½¹}ÁÉ½™¥±•Ì (€€€€€€€€€€€½±‘}ÁÉ½™¥±”°(€€€€€€€€€€€¹•İ}ÁÉ½™¥±”½Èì(€€€€€€€€€€€€€€€€¨©U1Q}AI=%1°(€€€€€€€€€€€€€€€€‰±¥¹•}ÕÍ•É}¥ˆèÙ•É¥™¥•‘}¹•İ}¥°(€€€€€€€€€€€ô°(€€€€€€€€€€€¹½ÜõÕÉÉ•¹Ğ°(€€€€€€€€¤(€€€€€€€É•¥¹‘•á}…½Õ¹Ñ}É•™•É•¹•Ì (€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€½±‘}±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€Ù•É¥™¥•‘}¹•İ}¥°(€€€€€€€€€€€•Ù•¹Ñ}¥°(€€€€€€€€€€€¹½ÜõÕÉÉ•¹Ğ°(€€€€€€€€¤(€€€€€€€}É•¥¹‘•á}µ¥É…Ñ¥½¹}É•½É (€€€€€€€€€€€µ•É•‘}ÁÉ½™¥±”°(€€€€€€€€€€€½±‘}±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€Ù•É¥™¥•‘}¹•İ}¥°(€€€€€€€€€€€•Ù•¹Ñ}¥°(€€€€€€€€¤(€€€€€€€ÕÍ•ÉÍmÙ•É¥™¥•‘}¹•İ}¥‘t€ôµ•É•‘}ÁÉ½™¥±”(€€€€€€€ÕÍ•ÉÌ¹Á½À¡½±‘}±¥¹•}ÕÍ•É}¥°9½¹”¤(€€€€€€€É•…Ñ•}…½Õ¹Ñ}µ¥É…Ñ¥½¹}…±¥…Ì (€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€½±‘}±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€Ù•É¥™¥•‘}¹•İ}¥°(€€€€€€€€€€€¹½ÜõÕÉÉ•¹Ğ°(€€€€€€€€¤((€€€€€€€Ñ¥­•Ñl‰ÍÑ…ÑÕÌ‰t€ô€‰ÕÍ•ˆ(€€€€€€€Ñ¥­•Ñl‰ÕÍ•‘}…Ğ‰t€ôÕÉÉ•¹Ğ¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤(€€€€€€€Ñ¥­•Ñl‰µ¥É…Ñ¥½¹}•Ù•¹Ñ}¥‰t€ô•Ù•¹Ñ}¥(€€€€€€€½Õ¹ÑÌ€ô}…½Õ¹Ñ}µ¥É…Ñ¥½¹}Í…™•}½Õ¹ÑÌ (€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€µ•É•‘}ÁÉ½™¥±”°(€€€€€€€€€€€Ù•É¥™¥•‘}¹•İ}¥°(€€€€€€€€¤(€€€€€€€ÍÑ…Ñ”¹Í•Ñ‘•™…Õ±Ğ ‰…½Õ¹Ñ}µ¥É…Ñ¥½¹}…Õ‘¥Ğˆ°mt¤¹…ÁÁ•¹¡ì(€€€€€€€€€€€€‰•Ù•¹Ñ}¥ˆè•Ù•¹Ñ}¥°(€€€€€€€€€€€€‰ÍÑ…ÑÕÌˆè€‰ÍÕ•ÍÌˆ°(€€€€€€€€€€€€‰É•…Ñ•‘}…ĞˆèÕÉÉ•¹Ğ¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤°(€€€€€€€€€€€€‰™…¥±ÕÉ•}…Ñ•½Éäˆè€ˆˆ°(€€€€€€€€€€€€‰½Õ¹ÑÌˆè½Õ¹ÑÌ°(€€€€€€€ô¤(€€€€€€€É•ÑÕÉ¸ì(€€€€€€€€€€€€‰½¬ˆèQÉÕ”°(€€€€€€€€€€€€‰ÍÑ…ÑÕÌˆè€‰µ¥É…Ñ•ˆ°(€€€€€€€€€€€€‰½Õ¹ÑÌˆè½Õ¹ÑÌ°(€€€€€€€ô°€ÈÀÀ((€€€ÑÉäè(€€€€€€€É•ÑÕÉ¸µÕÑ…Ñ•}ÍÑ…Ñ•}…Ñ½µ¥…±±ä¡‘…Ñ…}™¥±”°µÕÑ…Ñ”¤(€€€•á•ÁĞá•ÁÑ¥½¸è(€€€€€€€ÑÉäè(€€€€€€€€€€€µÕÑ…Ñ•}ÍÑ…Ñ•}…Ñ½µ¥…±±ä (€€€€€€€€€€€€€€€‘…Ñ…}™¥±”°(€€€€€€€€€€€€€€€±…µ‰‘„ÍÑ…Ñ”è}…ÁÁ•¹‘}…½Õ¹Ñ}µ¥É…Ñ¥½¹}™…¥±ÕÉ•}…Õ‘¥Ğ (€€€€€€€€€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€€€€€€€€€€‰µ¥É…Ñ¥½¹}™…¥±•ˆ°(€€€€€€€€€€€€€€€€€€€ÕÉÉ•¹Ğ°(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€¤(€€€€€€€•á•ÁĞá•ÁÑ¥½¸è(€€€€€€€€€€€Á…ÍÌ(€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰µ¥É…Ñ¥½¹}™…¥±•‰ô°€ÔÀÀ(()‘•˜ÁÕÉ•}…½Õ¹Ñ}µ¥É…Ñ¥½¹}Í¹…ÁÍ¡½ÑÌ¡ÍÑ…Ñ”°¹½Üõ9½¹”¤è(€€€ÕÉÉ•¹Ğ€ô}…½Õ¹Ñ}µ¥É…Ñ¥½¹}¹½Ü¡¹½Ü¤(€€€Í¹…ÁÍ¡½ÑÌ€ôÍÑ…Ñ”¹•Ğ ‰…½Õ¹Ñ}µ¥É…Ñ¥½¹}Í¹…ÁÍ¡½ÑÌˆ¤½Èíô(€€€É•Ñ…¥¹•€ôíô(€€€É•µ½Ù•€ô€À(€€€™½ÈÍ¹…ÁÍ¡½Ñ}¥°Í¹…ÁÍ¡½Ğ¥¸Í¹…ÁÍ¡½ÑÌ¹¥Ñ•µÌ ¤è(€€€€€€€ÁÕÉ•}…™Ñ•È€ô}…½Õ¹Ñ}µ¥É…Ñ¥½¹}‘…Ñ•Ñ¥µ” (€€€€€€€€€€€€¡Í¹…ÁÍ¡½Ğ½Èíô¤¹•Ğ ‰ÁÕÉ•}…™Ñ•Èˆ¤(€€€€€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡Í¹…ÁÍ¡½Ğ°‘¥Ğ¤(€€€€€€€€€€€•±Í”9½¹”(€€€€€€€€¤(€€€€€€€¥˜ÁÕÉ•}…™Ñ•È…¹ÁÕÉ•}…™Ñ•È€ğôÕÉÉ•¹Ğè(€€€€€€€€€€€É•µ½Ù•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€É•Ñ…¥¹•‘mÍ¹…ÁÍ¡½Ñ}¥‘t€ôÍ¹…ÁÍ¡½Ğ(€€€ÍÑ…Ñ•l‰…½Õ¹Ñ}µ¥É…Ñ¥½¹}Í¹…ÁÍ¡½ÑÌ‰t€ôÉ•Ñ…¥¹•(€€€É•ÑÕÉ¸É•µ½Ù•(()‘•˜…‘µ¥¹}Á…ÍÍİ½É‘}µ…Ñ¡•Ì¡½¹™¥œ°…¹‘¥‘…Ñ”¤è(€€€É•ÑÕÉ¸…‘µ¥¹}É½±•}™½É}Á…ÍÍİ½É¡½¹™¥œ°…¹‘¥‘…Ñ”¤¥Ì¹½Ğ9½¹”(()5%9}I=1}AI5%MM%=9L€ôì(€€€€‰ÍÕÁ•É}…‘µ¥¸ˆèì(€€€€€€€€‰‰…­ÕÀ¹µ…¹…”ˆ°(€€€€€€€€‰‰•Ñ„¹µ…¹…”ˆ°(€€€€€€€€‰¥¹¥‘•¹Ğ¹µ…¹…”ˆ°(€€€€€€€€‰µ•µ‰•È¹µ…¹…”ˆ°(€€€€€€€€‰¹½Ñ¥™¥…Ñ¥½¸¹µ…¹…”ˆ°(€€€€€€€€‰½É‘•È¹µ…¹…”ˆ°(€€€€€€€€‰ÁÉ¥Ù…ä¹µ…¹…”ˆ°(€€€€€€€€‰ÍÕÁÁ½ÉĞ¹µ…¹…”ˆ°(€€€€€€€€‰ÍåÍÑ•´¹µ…¹…”ˆ°(€€€ô°(€€€€‰½Á•É…Ñ¥½¹Ìˆèì(€€€€€€€€‰‰•Ñ„¹µ…¹…”ˆ°(€€€€€€€€‰¥¹¥‘•¹Ğ¹µ…¹…”ˆ°(€€€€€€€€‰µ•µ‰•È¹µ…¹…”ˆ°(€€€€€€€€‰¹½Ñ¥™¥…Ñ¥½¸¹µ…¹…”ˆ°(€€€€€€€€‰ÁÉ¥Ù…ä¹µ…¹…”ˆ°(€€€€€€€€‰ÍÕÁÁ½ÉĞ¹µ…¹…”ˆ°(€€€ô°(€€€€‰™¥¹…¹”ˆèì‰½É‘•È¹µ…¹…”‰ô°(€€€€‰Ù¥•İ•ÈˆèÍ•Ğ ¤°)ô(()‘•˜…‘µ¥¹}É½±•}™½É}Á…ÍÍİ½É¡½¹™¥œ°…¹‘¥‘…Ñ”¤è(€€€¥˜¹½Ğ…‘µ¥¹}Í•ÕÉ¥Ñå}É•…‘ä¡½¹™¥œ¤è(€€€€€€€É•ÑÕÉ¸9½¹”(€€€½Ğ€ô}¹½Éµ…±¥é•}…‘µ¥¹}Á…ÍÍİ½É¡…¹‘¥‘…Ñ”¤(€€€¥˜¹½Ğ½Ğè(€€€€€€€É•ÑÕÉ¸9½¹”(€€€É½±•}Á…ÍÍİ½É‘Ì€ô€ (€€€€€€€€ ‰ÍÕÁ•É}…‘µ¥¸ˆ°€‰5%9}AMM]=Iˆ¤°(€€€€€€€€ ‰½Á•É…Ñ¥½¹Ìˆ°€‰5%9}=AIQ%=9M}AMM]=Iˆ¤°(€€€€€€€€ ‰™¥¹…¹”ˆ°€‰5%9}%99}AMM]=Iˆ¤°(€€€€€€€€ ‰Ù¥•İ•Èˆ°€‰5%9}Y%]I}AMM]=Iˆ¤°(€€€€¤(€€€™½ÈÉ½±”°½¹™¥}¹…µ”¥¸É½±•}Á…ÍÍİ½É‘Ìè(€€€€€€€•áÁ•Ñ•€ô}¹½Éµ…±¥é•}…‘µ¥¹}Á…ÍÍİ½É¡½¹™¥œ¹•Ğ¡½¹™¥}¹…µ”°€ˆˆ¤¤(€€€€€€€¥˜•áÁ•Ñ•…¹Í•É•ÑÌ¹½µÁ…É•}‘¥•ÍĞ¡•áÁ•Ñ•°½Ğ¤è(€€€€€€€€€€€É•ÑÕÉ¸É½±”(€€€É•ÑÕÉ¸9½¹”(()‘•˜…‘µ¥¹}Á•Éµ¥ÍÍ¥½¹Í}™½É}É½±”¡É½±”¤è(€€€É•ÑÕÉ¸Í½ÉÑ•¡5%9}I=1}AI5%MM%=9L¹•Ğ¡ÍÑÈ¡É½±”½È€ˆˆ¤°Í•Ğ ¤¤¤(()5%9}1=%9}QQ5AQL€ôíô(()‘•˜}…‘µ¥¹}±½¥¹}…ÑÑ•µÁÑÌ¡±¥•¹Ñ}­•ä°¹½Üõ9½¹”¤è(€€€¹½Ü€ô¹½Ü½È‘…Ñ•Ñ¥µ”¹¹½Ü ¤(€€€ÕÑ½™˜€ô¹½Ü€´Ñ¥µ•‘•±Ñ„¡µ¥¹ÕÑ•ÌôÄÀ¤(€€€É••¹Ğ€ôl(€€€€€€€Ù…±Õ”™½ÈÙ…±Õ”¥¸5%9}1=%9}QQ5AQL¹•Ğ¡±¥•¹Ñ}­•ä°mt¤(€€€€€€€¥˜Ù…±Õ”€øôÕÑ½™˜(€€€t(€€€5%9}1=%9}QQ5AQMm±¥•¹Ñ}­•åt€ôÉ••¹Ğ(€€€É•ÑÕÉ¸É••¹Ğ(()‘•˜…‘µ¥¹}±½¥¹}É…Ñ•}±¥µ¥Ñ•¡±¥•¹Ñ}­•ä°¹½Üõ9½¹”¤è(€€€É•ÑÕÉ¸±•¸¡}…‘µ¥¹}±½¥¹}…ÑÑ•µÁÑÌ¡±¥•¹Ñ}­•ä°¹½Ü¤¤€øô€Ô(()‘•˜É•½É‘}…‘µ¥¹}±½¥¹}™…¥±ÕÉ”¡±¥•¹Ñ}­•ä°¹½Üõ9½¹”¤è(€€€¹½Ü€ô¹½Ü½È‘…Ñ•Ñ¥µ”¹¹½Ü ¤(€€€É••¹Ğ€ô}…‘µ¥¹}±½¥¹}…ÑÑ•µÁÑÌ¡±¥•¹Ñ}­•ä°¹½Ü¤(€€€É••¹Ğ¹…ÁÁ•¹¡¹½Ü¤(€€€5%9}1=%9}QQ5AQMm±¥•¹Ñ}­•åt€ôÉ••¹Ñl´Ôét(()}5%9}U%Q}M9M%Q%Y}-e}AIQL€ô€ (€€€€‰Á…ÍÍİ½Éˆ°(€€€€‰Á…ÍÍİˆ°(€€€€‰Ñ½­•¸ˆ°(€€€€‰Í•É•Ğˆ°(€€€€‰ÍÉ˜ˆ°(€€€€‰…ÕÑ¡½É¥é…Ñ¥½¸ˆ°(€€€€‰½½­¥”ˆ°(€€€€‰•µ…¥°ˆ°(€€€€‰Á¡½¹”ˆ°(€€€€‰µ½‰¥±”ˆ°(€€€€‰…‘‘É•ÍÌˆ°(€€€€‰±¥¹•ÕÍ•É¥ˆ°(€€€€‰ÕÍ•É¥ˆ°(€€€€‰‘¥ÍÁ±…å¹…µ”ˆ°(€€€€‰™Õ±±¹…µ”ˆ°(€€€€‰±…Ñ¥ÑÕ‘”ˆ°(€€€€‰±½¹¥ÑÕ‘”ˆ°(€€€€‰±½…Ñ¥½¸ˆ°(€€€€‰¥Á…‘‘É•ÍÌˆ°(€€€€‰É•µ½Ñ•…‘‘Èˆ°(¤(()‘•˜}Í…¹¥Ñ¥é•}…‘µ¥¹}…Õ‘¥Ñ}µ•Ñ…‘…Ñ„¡Ù…±Õ”¤è(€€€¥˜¥Í¥¹ÍÑ…¹”¡Ù…±Õ”°‘¥Ğ¤è(€€€€€€€±•…¹•€ôíô(€€€€€€€™½È­•ä°¥Ñ•´¥¸Ù…±Õ”¹¥Ñ•µÌ ¤è(€€€€€€€€€€€½µÁ…Ñ}­•ä€ôÉ”¹ÍÕˆ¡È‰my„µèÀ´åtˆ°€ˆˆ°ÍÑÈ¡­•ä¤¹…Í•™½± ¤¤(€€€€€€€€€€€¥˜€ (€€€€€€€€€€€€€€€½µÁ…Ñ}­•ä¥¸ì‰¹…µ”ˆ°€‰ÕÍ•É¹…µ”‰ô(€€€€€€€€€€€€€€€½È…¹ä (€€€€€€€€€€€€€€€€€€€Á…ÉĞ¥¸½µÁ…Ñ}­•ä(€€€€€€€€€€€€€€€€€€€™½ÈÁ…ÉĞ¥¸}5%9}U%Q}M9M%Q%Y}-e}AIQL(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€¤è(€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€±•…¹•‘mÍÑÈ¡­•ä¥t€ô}Í…¹¥Ñ¥é•}…‘µ¥¹}…Õ‘¥Ñ}µ•Ñ…‘…Ñ„¡¥Ñ•´¤(€€€€€€€É•ÑÕÉ¸±•…¹•(€€€¥˜¥Í¥¹ÍÑ…¹”¡Ù…±Õ”°€¡±¥ÍĞ°ÑÕÁ±”°Í•Ğ¤¤è(€€€€€€€É•ÑÕÉ¸m}Í…¹¥Ñ¥é•}…‘µ¥¹}…Õ‘¥Ñ}µ•Ñ…‘…Ñ„¡¥Ñ•´¤™½È¥Ñ•´¥¸Ù…±Õ•t(€€€¥˜Ù…±Õ”¥Ì9½¹”½È¥Í¥¹ÍÑ…¹”¡Ù…±Õ”°€¡ÍÑÈ°¥¹Ğ°™±½…Ğ°‰½½°¤¤è(€€€€€€€É•ÑÕÉ¸Ù…±Õ”(€€€É•ÑÕÉ¸ÍÑÈ¡Ù…±Õ”¤(()‘•˜…ÁÁ•¹‘}…‘µ¥¹}…Õ‘¥Ğ¡‘…Ñ…}™¥±”°…Ñ¥½¸°ÍÑ…ÑÕÌ°µ•Ñ…‘…Ñ„õ9½¹”¤è(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€±½Ì€ô±¥ÍĞ¡ÍÑ…Ñ”¹•Ğ ‰…‘µ¥¹}…Õ‘¥Ñ}±½Ìˆ¤½Èmt¤(€€€±½Ì¹…ÁÁ•¹¡ì(€€€€€€€€‰É•…Ñ•‘}…Ğˆè‘…Ñ•Ñ¥µ”¹¹½Ü ¤¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤°(€€€€€€€€‰…Ñ¥½¸ˆèÍÑÈ¡…Ñ¥½¸¤°(€€€€€€€€‰ÍÑ…ÑÕÌˆèÍÑÈ¡ÍÑ…ÑÕÌ¤°(€€€€€€€€‰µ•Ñ…‘…Ñ„ˆè}Í…¹¥Ñ¥é•}…‘µ¥¹}…Õ‘¥Ñ}µ•Ñ…‘…Ñ„¡‘¥Ğ¡µ•Ñ…‘…Ñ„½Èíô¤¤°(€€€ô¤(€€€ÍÑ…Ñ•l‰…‘µ¥¹}…Õ‘¥Ñ}±½Ì‰t€ô±½Íl´ÈÀÀét(€€€Í…Ù•}ÍÑ…Ñ”¡‘…Ñ…}™¥±”°ÍÑ…Ñ”¤(()5%9}QMQ}9QI}QMQL€ôì(€€€€‰‘…¥±å}É••Ñ¥¹œˆè€ ‹š¾?š^—–V?–gš:£šJ´ˆ°€‰±¥¹”ˆ¤°(€€€€‰ÑÉ¥…±|ÄÑ}¹½Ñ¥”ˆè€ ˆÄĞƒ–’§¦®S¦¦_š>C¦Hˆ°€‰±¥¹”ˆ¤°(€€€€‰‰•Ñ…|ÈÅ}¹½Ñ¥”ˆè€ ˆÈÄƒ–’§–Âšâ³š>C¦Hˆ°€‰±¥¹”ˆ¤°(€€€€‰Á…¥‘}•áÁ¥Éå}¹½Ñ¥”ˆè€ ‹’îc¢ÊïšZçš†#–"Ãšrš>C¦Hˆ°€‰±¥¹”ˆ¤°(€€€€‰Á…åµ•¹Ñ}É•ÍÑ½É”ˆè€ ‹’îcš²û–ú3š‹–ú§–:¢¢·–ºhˆ°€‰Í¥µÕ±…Ñ¥½¸ˆ¤°(€€€€‰Í½Í}±½…Ñ¥½¸ˆè€ ‰M=O–>[šÚ#¢"–ºk’ö7¦k~”ˆ°€‰±¥¹”ˆ¤°(€€€€‰Õ…É‘¥…¹}¥¹Ù¥Ñ”ˆè€ ‹š‚ã–ş–º#¢¶ß’êë¦
¢®/Ú–ºhˆ°€‰±¥¹”ˆ¤°(€€€€‰‰•Ñ…}™••‘‰…­|ÄäÀÀˆè€ ˆÄäèÀÀƒ–Âšâ³¢¦‹–V<ˆ°€‰±¥¹”ˆ¤°(€€€€‰ÍÑ½Á}É•¹•İ…±}¹½Ñ¥”ˆè€ ‹’â7–7š>C¦Kš"Dˆ°€‰Í¥µÕ±…Ñ¥½¸ˆ¤°(€€€€‰ÈÉ}‰…­ÕÀˆè€ ‰HÈƒ–*ƒ–¾–
g’îôˆ°€‰ÈÈˆ¤°)ô(()‘•˜}Ñ•ÍÑ}±¥¹•}ÕÍ•É}¥‘Ì¡½¹™¥œ¤è(€€€É…Ü€ô½¹™¥œ¹•Ğ ‰QMQ}1%9}UMI}%Lˆ¤½È€ˆˆ(€€€¥˜¥Í¥¹ÍÑ…¹”¡É…Ü°€¡±¥ÍĞ°ÑÕÁ±”°Í•Ğ¤¤è(€€€€€€€Ù…±Õ•Ì€ôÉ…Ü(€€€•±Í”è(€€€€€€€Ù…±Õ•Ì€ôÍÑÈ¡É…Ü¤¹ÍÁ±¥Ğ ˆ°ˆ¤(€€€É•ÑÕÉ¸mÍÑÈ¡Ù…±Õ”¤¹ÍÑÉ¥À ¤™½ÈÙ…±Õ”¥¸Ù…±Õ•Ì¥˜ÍÑÈ¡Ù…±Õ”¤¹ÍÑÉ¥À ¥t(()‘•˜}µ…Í­•‘}Ñ•ÍÑ}…½Õ¹Ğ¡±¥¹•}ÕÍ•É}¥¤è(€€€‘¥•ÍĞ€ô¡…Í¡±¥ˆ¹Í¡„ÈÔØ¡ÍÑÈ¡±¥¹•}ÕÍ•É}¥¤¹•¹½‘” ‰ÕÑ˜´àˆ¤¤¹¡•á‘¥•ÍĞ ¥lèát(€€€É•ÑÕÉ¸ì‰¥ˆè‘¥•ÍĞ°€‰±…‰•°ˆè˜‹šâ³¢¦›–âÏ¢f|ƒŠ™í‘¥•ÍÑl´Ğéuô‰ô(()‘•˜}Ñ•ÍÑ}•¹Ñ•É}¥¹Ñ•É…Ñ¥½¹Ì¡½¹™¥œ¤è(€€€½¹™¥ÕÉ•€ô±…µ‰‘„­•äè‰½½°¡ÍÑÈ¡½¹™¥œ¹•Ğ¡­•ä¤½È€ˆˆ¤¹ÍÑÉ¥À ¤¤(€€€É•ÑÕÉ¸ì(€€€€€€€€‰±¥¹”ˆèì(€€€€€€€€€€€€‰½¹™¥ÕÉ•ˆè½¹™¥ÕÉ• ‰1%9}!991}MM}Q=-8ˆ¤°(€€€€€€€€€€€€‰±…‰•°ˆè€‰1%9ƒš:£šJ´ˆ°(€€€€€€€ô°(€€€€€€€€‰ÈÈˆèì(€€€€€€€€€€€€‰½¹™¥ÕÉ•ˆè…±°¡½¹™¥ÕÉ•¡­•ä¤™½È­•ä¥¸€ (€€€€€€€€€€€€€€€€‰HÉ}9A=%9Pˆ°€‰HÉ}MM}-e}%ˆ°€‰HÉ}MIQ}MM}-dˆ°(€€€€€€€€€€€€€€€€‰HÉ}	U-Pˆ°€‰HÉ}	-UA}9IeAQ%=9}-dˆ°(€€€€€€€€€€€€¤¤°(€€€€€€€€€€€€‰±…‰•°ˆè€‰HÈƒ–*ƒ–¾–
g’îôˆ°(€€€€€€€ô°(€€€€€€€€‰„Ğˆèì(€€€€€€€€€€€€‰½¹™¥ÕÉ•ˆè½¹™¥ÕÉ• ‰Ñ}5MUI59Q}%ˆ¤(€€€€€€€€€€€…¹½¹™¥ÕÉ• ‰Ñ}AI=AIQe}%ˆ¤(€€€€€€€€€€€…¹½¹™¥ÕÉ• ‰Ñ}MIY%}=U9Q})M=8ˆ¤°(€€€€€€€€€€€€‰±…‰•°ˆè€‰Ğƒ–‚Ç¢† ˆ°(€€€€€€€ô°(€€€€€€€€‰Á…åµ•¹Ğˆèì(€€€€€€€€€€€€‰½¹™¥ÕÉ•ˆè€ (€€€€€€€€€€€€€€€…±°¡½¹™¥ÕÉ•¡­•ä¤™½È­•ä¥¸€ (€€€€€€€€€€€€€€€€€€€€‰Ae}5I!9Q}%ˆ°€‰Ae}!M!}-dˆ°€‰Ae}!M!}%Xˆ°(€€€€€€€€€€€€€€€€¤¤(€€€€€€€€€€€€€€€½È…±°¡½¹™¥ÕÉ•¡­•ä¤™½È­•ä¥¸€ (€€€€€€€€€€€€€€€€€€€€‰9]	Ae}5I!9Q}%ˆ°€‰9]	Ae}!M!}-dˆ°€‰9]	Ae}!M!}%Xˆ°(€€€€€€€€€€€€€€€€¤¤(€€€€€€€€€€€€¤°(€€€€€€€€€€€€‰±¥Ù”ˆè€ (€€€€€€€€€€€€€€€ÍÑÈ¡½¹™¥œ¹•Ğ ‰Ae}MQˆ¤½È€‰Í…¹‘‰½àˆ¤¹±½İ•È ¤€ôô€‰ÁÉ½‘ÕÑ¥½¸ˆ(€€€€€€€€€€€€€€€½ÈÍÑÈ¡½¹™¥œ¹•Ğ ‰9]	Ae}MQˆ¤½È€‰Í…¹‘‰½àˆ¤¹±½İ•È ¤€ôô€‰ÁÉ½‘ÕÑ¥½¸ˆ(€€€€€€€€€€€€¤°(€€€€€€€€€€€€‰±…‰•°ˆè€‹¦GšÖˆ°(€€€€€€€ô°(€€€ô(()‘•˜…‘µ¥¹}Ñ•ÍÑ}•¹Ñ•É}ÍÑ…ÑÕÌ¡‘…Ñ…}™¥±”°½¹™¥œ¤è(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€…½Õ¹ÑÌ€ô}Ñ•ÍÑ}±¥¹•}ÕÍ•É}¥‘Ì¡½¹™¥œ¤(€€€É•ÑÕÉ¸ì(€€€€€€€€‰Ñ•ÍÑ}µ½‘”ˆèQÉÕ”°(€€€€€€€€‰Ñ•ÍÑ}…½Õ¹ÑÌˆèm}µ…Í­•‘}Ñ•ÍÑ}…½Õ¹Ğ¡¥Ñ•´¤™½È¥Ñ•´¥¸…½Õ¹ÑÍt°(€€€€€€€€‰¥¹Ñ•É…Ñ¥½¹Ìˆè}Ñ•ÍÑ}•¹Ñ•É}¥¹Ñ•É…Ñ¥½¹Ì¡½¹™¥œ¤°(€€€€€€€€‰Ñ•ÍÑÌˆèl(€€€€€€€€€€€ì‰¥ˆèÑ•ÍÑ}¥°€‰±…‰•°ˆè±…‰•°°€‰­¥¹ˆè­¥¹‘ô(€€€€€€€€€€€™½ÈÑ•ÍÑ}¥°€¡±…‰•°°­¥¹¤¥¸5%9}QMQ}9QI}QMQL¹¥Ñ•µÌ ¤(€€€€€€€t°(€€€€€€€€‰É••¹Ñ}ÉÕ¹Ìˆè±¥ÍĞ¡É•Ù•ÉÍ•¡ÍÑ…Ñ”¹•Ğ ‰Ñ•ÍÑ}•¹Ñ•É}ÉÕ¹Ìˆ¤½Èmt¤¥lèÈÁt°(€€€ô(()‘•˜}Ñ•ÍÑ}•¹Ñ•É}µ•ÍÍ…”¡Ñ•ÍÑ}¥¤è(€€€±…‰•°€ô5%9}QMQ}9QI}QMQMmÑ•ÍÑ}¥‘ulÁt(€€€‘•Ñ…¥±Ì€ôì(€€€€€€€€‰‘…¥±å}É••Ñ¥¹œˆè€‹¦gšb¿š¾?š^—–V?–gš:£šJ·šâ³¢¦›¾ò3¢®/Šë¢ª7šZ–¶_¢"š2'¦"W¦†¿’ëš¶–âãˆ°(€€€€€€€€‰ÑÉ¥…±|ÄÑ}¹½Ñ¥”ˆè€‹¦gšb¼€ÄĞƒ–’§¦®S¦¦_²°€ß¾ò<ÄË¾ò<ÄĞƒ–’§š>C¦K¦‚C¢š÷ˆ°(€€€€€€€€‰‰•Ñ…|ÈÅ}¹½Ñ¥”ˆè€‹¦gšb¼€ÈÄƒ–’§–Âšâ³²°€Äã¾ò<ÈÃ¾ò<ÈÄƒ–’§š>C¦K¦‚C¢š÷ˆ°(€€€€€€€€‰Á…¥‘}•áÁ¥Éå}¹½Ñ¥”ˆè€‹¦gšb¿’îc¢ÊïšZçš†#–"Ãšr–&4€ß¾ò<Ï¾ò<Äƒ–’§¢"–"Ãšrš^—š>C¦K¦‚C¢š÷ˆ°(€€€€€€€€‰Í½Í}±½…Ñ¥½¸ˆè€‹¦gšb¼M=O–>[šÚ M=Lƒ¢"–ºk’ö7¦k~—j–º'–£¦‚C¢š÷¾ò3’â7šr–îë®/r–¾›’ê/’îÛˆ°(€€€€€€€€‰Õ…É‘¥…¹}¥¹Ù¥Ñ”ˆè€‹¦gšb¿š‚ã–ş–º#¢¶ß’êë¦
¢®/¢"Ú–ºk¢ª«šb;¦‚C¢š÷ˆ°(€€€€€€€€‰‰•Ñ…}™••‘‰…­|ÄäÀÀˆè€‹¦gšb¿š¾?–’¤€ÄäèÀÀƒ–Âšâ³’öÿR£¢¦‹–V?¦‚C¢š÷ˆ°(€€€ô(€€€É•ÑÕÉ¸˜‹Cšâ³¢¦›š¢‡–ò?Eí±…‰•±õq¹í‘•Ñ…¥±Ì¹•Ğ¡Ñ•ÍÑ}¥°€Ÿ–º'–£šâ³¢¦›¦‚C¢šôœ¥õq»’â7šrš&š²û’â7šr¢º+šnÓšZçš†#ˆ(()‘•˜ÉÕ¹}…‘µ¥¹}Ñ•ÍĞ¡‘…Ñ…}™¥±”°½¹™¥œ°Á…å±½…¤è(€€€Á…å±½…€ôÁ…å±½…¥˜¥Í¥¹ÍÑ…¹”¡Á…å±½…°‘¥Ğ¤•±Í”íô(€€€Ñ•ÍÑ}¥€ôÍÑÈ¡Á…å±½…¹•Ğ ‰Ñ•ÍÑ}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€±¥¹•}ÕÍ•É}¥€ôÍÑÈ¡Á…å±½…¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€¥˜Ñ•ÍÑ}¥¹½Ğ¥¸5%9}QMQ}9QI}QMQLè(€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰Õ¹­¹½İ¹}Ñ•ÍĞ‰ô°€ĞÀÀ(€€€…±±½İ•€ô}Ñ•ÍÑ}±¥¹•}ÕÍ•É}¥‘Ì¡½¹™¥œ¤(€€€…½Õ¹Ñ}¥€ôÍÑÈ¡Á…å±½…¹•Ğ ‰…½Õ¹Ñ}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€¥˜¹½Ğ±¥¹•}ÕÍ•É}¥…¹…½Õ¹Ñ}¥è(€€€€€€€±¥¹•}ÕÍ•É}¥€ô¹•áĞ (€€€€€€€€€€€€ (€€€€€€€€€€€€€€€¥Ñ•´™½È¥Ñ•´¥¸…±±½İ•(€€€€€€€€€€€€€€€¥˜}µ…Í­•‘}Ñ•ÍÑ}…½Õ¹Ğ¡¥Ñ•´¥l‰¥‰t€ôô…½Õ¹Ñ}¥(€€€€€€€€€€€€¤°(€€€€€€€€€€€€ˆˆ°(€€€€€€€€¤(€€€¥˜±¥¹•}ÕÍ•É}¥¹½Ğ¥¸…±±½İ•è(€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰Ñ•ÍÑ}É•¥Á¥•¹Ñ}¹½Ñ}…±±½İ•‰ô°€ĞÀÌ(€€€±…‰•°°­¥¹€ô5%9}QMQ}9QI}QMQMmÑ•ÍÑ}¥‘t(€€€ÍÑ…ÑÕÌ€ô€‰ÍÕ•ÍÌˆ(€€€•ÉÉ½È€ô€ˆˆ(€€€É•ÍÕ±Ğ€ôì‰½¬ˆèQÉÕ”°€‰Ñ•ÍÑ}¥ˆèÑ•ÍÑ}¥°€‰±…‰•°ˆè±…‰•°°€‰Ñ•ÍÑ}µ½‘”ˆèQÉÕ•ô(€€€ÑÉäè(€€€€€€€¥˜­¥¹€ôô€‰±¥¹”ˆè(€€€€€€€€€€€Ñ½­•¸€ôÍÑÈ¡½¹™¥œ¹•Ğ ‰1%9}!991}MM}Q=-8ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€€€€€¥˜¹½ĞÑ½­•¸è(€€€€€€€€€€€€€€€É…¥Í”Y…±Õ•ÉÉ½È ‰±¥¹•}¹½Ñ}½¹™¥ÕÉ•ˆ¤(€€€€€€€€€€€Í•¹‘•È€ô½¹™¥œ¹•Ğ ‰1%9}AUM!}M9Hˆ¤½È±¥¹•}ÁÕÍ¡}µ•ÍÍ…”(€€€€€€€€€€€Í•¹‘•È¡Ñ½­•¸°±¥¹•}ÕÍ•É}¥°}Ñ•ÍÑ}•¹Ñ•É}µ•ÍÍ…”¡Ñ•ÍÑ}¥¤¤(€€€€€€€€€€€É•ÍÕ±Ñl‰Í•¹Ğ‰t€ôQÉÕ”(€€€€€€€•±¥˜­¥¹€ôô€‰ÈÈˆè(€€€€€€€€€€€‰…­ÕÀ°½‘”€ôÉ•…Ñ•}ÈÉ}•¹ÉåÁÑ•‘}‰…­ÕÀ¡½¹™¥œ¤(€€€€€€€€€€€¥˜½‘”€øô€ĞÀÀè(€€€€€€€€€€€€€€€É…¥Í”Y…±Õ•ÉÉ½È¡ÍÑÈ¡‰…­ÕÀ¹•Ğ ‰•ÉÉ½Èˆ¤½È€‰ÈÉ}‰…­ÕÁ}™…¥±•ˆ¤¤(€€€€€€€€€€€É•ÍÕ±Ñl‰‰…­ÕÀ‰t€ôì(€€€€€€€€€€€€€€€€‰­•äˆèÍÑÈ¡‰…­ÕÀ¹•Ğ ‰­•äˆ¤½È€ˆˆ¤°(€€€€€€€€€€€€€€€€‰É•…Ñ•‘}…ĞˆèÍÑÈ¡‰…­ÕÀ¹•Ğ ‰É•…Ñ•‘}…Ğˆ¤½È€ˆˆ¤°(€€€€€€€€€€€ô(€€€€€€€•±Í”è(€€€€€€€€€€€É•ÍÕ±Ñl‰Í¥µÕ±…Ñ•‰t€ôQÉÕ”(€€€€€€€€€€€É•ÍÕ±Ñl‰µ•ÍÍ…”‰t€ô€ (€€€€€€€€€€€€€€€€‹’îcš²û–ú3š‹–ú§–:¢¢·–ºkš¢‡šN³š"C–*¾òošr«–Fó–>¯¦GšÖšr«šRçšZçš†#ˆ(€€€€€€€€€€€€€€€¥˜Ñ•ÍÑ}¥€ôô€‰Á…åµ•¹Ñ}É•ÍÑ½É”ˆ(€€€€€€€€€€€€€€€•±Í”€‹’â7–7š>C¦K–?––÷š¢‡šN³š"C–*¾òošr«’ş»šRçš¶–ò?šr–N‡¢ÎšZgˆ(€€€€€€€€€€€€¤(€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€ÍÑ…ÑÕÌ€ô€‰™…¥±•ˆ(€€€€€€€•ÉÉ½È€ô±…ÍÍ¥™å}±¥¹•}ÁÕÍ¡}•ÉÉ½È¡•áŒ¤(€€€€€€€É•ÍÕ±Ğ€ôì(€€€€€€€€€€€€‰½¬ˆè…±Í”°(€€€€€€€€€€€€‰•ÉÉ½Èˆè•ÉÉ½È°(€€€€€€€€€€€€‰Ñ•ÍÑ}¥ˆèÑ•ÍÑ}¥°(€€€€€€€€€€€€‰Ñ•ÍÑ}µ½‘”ˆèQÉÕ”°(€€€€€€€ô((€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€ÉÕ¹Ì€ô±¥ÍĞ¡ÍÑ…Ñ”¹•Ğ ‰Ñ•ÍÑ}•¹Ñ•É}ÉÕ¹Ìˆ¤½Èmt¤(€€€ÉÕ¹Ì¹…ÁÁ•¹¡ì(€€€€€€€€‰¥ˆèÕÕ¥¹ÕÕ¥Ğ ¤¹¡•álèÄÉt°(€€€€€€€€‰Ñ•ÍÑ}¥ˆèÑ•ÍÑ}¥°(€€€€€€€€‰±…‰•°ˆè±…‰•°°(€€€€€€€€‰Ñ…É•Ğˆè}µ…Í­•‘}Ñ•ÍÑ}…½Õ¹Ğ¡±¥¹•}ÕÍ•É}¥¥l‰±…‰•°‰t°(€€€€€€€€‰ÍÑ…ÑÕÌˆèÍÑ…ÑÕÌ°(€€€€€€€€‰•ÉÉ½Èˆè•ÉÉ½È°(€€€€€€€€‰É•…Ñ•‘}…Ğˆè‘…Ñ•Ñ¥µ”¹¹½Ü ¤¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤°(€€€ô¤(€€€ÍÑ…Ñ•l‰Ñ•ÍÑ}•¹Ñ•É}ÉÕ¹Ì‰t€ôÉÕ¹Íl´ÄÀÀét(€€€Í…Ù•}ÍÑ…Ñ”¡‘…Ñ…}™¥±”°ÍÑ…Ñ”¤(€€€É•ÑÕÉ¸É•ÍÕ±Ğ°€ ÈÀÀ¥˜ÍÑ…ÑÕÌ€ôô€‰ÍÕ•ÍÌˆ•±Í”€ÔÀÈ¤(()‘•˜É•Í½±Ù•}…‘µ¥¹}¥¹¥‘•¹Ğ¡‘…Ñ…}™¥±”°Á…å±½…°…Ñ½É}É½±”¤è(€€€­¥¹€ôÍÑÈ ¡Á…å±½…½Èíô¤¹•Ğ ‰­¥¹ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤¹…Í•™½± ¤(€€€¥¹¥‘•¹Ñ}¥€ôÍÑÈ ¡Á…å±½…½Èíô¤¹•Ğ ‰¥¹¥‘•¹Ñ}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€¹½Ñ”€ôÍÑÈ ¡Á…å±½…½Èíô¤¹•Ğ ‰É•Í½±ÕÑ¥½¹}¹½Ñ”ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¥lèÔÀÁt(€€€¥˜­¥¹¹½Ğ¥¸ì‰Í½Ìˆ°€‰‘•±¥Ù•Éä‰ô½È¹½Ğ¥¹¥‘•¹Ñ}¥è(€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰¥¹Ù…±¥‘}¥¹¥‘•¹Ğ‰ô°€ĞÀÀ(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€É•Í½±Ù•‘}…Ğ€ô‘…Ñ•Ñ¥µ”¹¹½Ü ¤¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤(€€€¥˜­¥¹€ôô€‰Í½Ìˆè(€€€€€€€Ñ…É•Ğ€ô€¡ÍÑ…Ñ”¹•Ğ ‰Í½Í}•Ù•¹ÑÌˆ¤½Èíô¤¹•Ğ¡¥¹¥‘•¹Ñ}¥¤(€€€€€€€¥˜Ñ…É•Ğ¥Ì9½¹”è(€€€€€€€€€€€Ñ…É•Ğ€ô¹•áĞ (€€€€€€€€€€€€€€€€ (€€€€€€€€€€€€€€€€€€€¥Ñ•´(€€€€€€€€€€€€€€€€€€€™½È¥Ñ•´¥¸€¡ÍÑ…Ñ”¹•Ğ ‰Í½Í}Á•¹‘¥¹œˆ¤½Èíô¤¹Ù…±Õ•Ì ¤(€€€€€€€€€€€€€€€€€€€¥˜ÍÑÈ¡¥Ñ•´¹•Ğ ‰•Ù•¹Ñ}¥ˆ¤½È€ˆˆ¤€ôô¥¹¥‘•¹Ñ}¥(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€9½¹”°(€€€€€€€€€€€€¤(€€€•±Í”è(€€€€€€€Ñ…É•Ğ€ô¹•áĞ (€€€€€€€€€€€€ (€€€€€€€€€€€€€€€¥Ñ•´(€€€€€€€€€€€€€€€™½È¥¹‘•à°¥Ñ•´¥¸•¹Õµ•É…Ñ”¡ÍÑ…Ñ”¹•Ğ ‰¹½Ñ¥™¥…Ñ¥½¹}±½Ìˆ¤½Èmt¤(€€€€€€€€€€€€€€€¥˜ÍÑÈ¡¥Ñ•´¹•Ğ ‰¥¹¥‘•¹Ñ}¥ˆ¤½È˜‰‘•±¥Ù•Éäµí¥¹‘•áôˆ¤€ôô¥¹¥‘•¹Ñ}¥(€€€€€€€€€€€€€€€…¹¥Ñ•´¹•Ğ ‰ÍÑ…ÑÕÌˆ¤¥¸ì‰™…¥±•ˆ°€‰•ÉÉ½È‰ô(€€€€€€€€€€€€¤°(€€€€€€€€€€€9½¹”°(€€€€€€€€¤(€€€¥˜Ñ…É•Ğ¥Ì9½¹”è(€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰¥¹¥‘•¹Ñ}¹½Ñ}™½Õ¹‰ô°€ĞÀĞ(€€€Ñ…É•Ñl‰ÍÑ…ÑÕÌ‰t€ô€‰É•Í½±Ù•ˆ(€€€Ñ…É•Ñl‰É•Í½±Ù•‘}…Ğ‰t€ôÉ•Í½±Ù•‘}…Ğ(€€€Ñ…É•Ñl‰É•Í½±Ù•‘}‰å}É½±”‰t€ôÍÑÈ¡…Ñ½É}É½±”½È€‰Õ¹­¹½İ¸ˆ¤(€€€¥˜¹½Ñ”è(€€€€€€€Ñ…É•Ñl‰É•Í½±ÕÑ¥½¹}¹½Ñ”‰t€ô¹½Ñ”(€€€Í…Ù•}ÍÑ…Ñ”¡‘…Ñ…}™¥±”°ÍÑ…Ñ”¤(€€€É•ÑÕÉ¸ì‰½¬ˆèQÉÕ”°€‰­¥¹ˆè­¥¹°€‰¥¹¥‘•¹Ñ}¥ˆè¥¹¥‘•¹Ñ}¥°€‰É•Í½±Ù•‘}…ĞˆèÉ•Í½±Ù•‘}…Ñô°€ÈÀÀ(()‘•˜}±¥¹•}¡…¹¹•±}…•ÍÍ}Ñ½­•¸¡½¹™¥œõ9½¹”¤è(€€€™œ€ô½¹™¥œ½Èíô(€€€É•ÑÕÉ¸€ (€€€€€€€™œ¹•Ğ ‰1%9}!991}MM}Q=-8ˆ¤(€€€€€€€½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}!991}MM}Q=-8ˆ¤(€€€€€€€½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰!991}MM}Q=-8ˆ¤(€€€€€€€½È€ˆˆ(€€€€¤¹ÍÑÉ¥À ¤(()‘•˜‘•Á±½å}‘•™…Õ±Ñ}É¥¡}µ•¹Ô¡½¹™¥œõ9½¹”°É½½Ñ}‘¥Èõ9½¹”¤è(€€€€ˆˆ‹R£’òëšr7–f£’â+j1%9}!991}MM}Q=-8ƒ–îë®/’â›¢¢·
ë¦‚C¢¢·–r[šZ¦ã–Z»((€€€ƒ’â7–n{–
Ï¾ò?’â4±½œÑ½­•»š"C–*–nx€¡Á…å±½…°€ÈÀÀ§¾òo–’ÇšV_–nx€¡•ÉÉ½È°¡ÑÑÁ}½‘”§(€€€€ˆˆˆ(€€€Ñ½­•¸€ô}±¥¹•}¡…¹¹•±}…•ÍÍ}Ñ½­•¸¡½¹™¥œ¤(€€€¥˜¹½ĞÑ½­•¸è(€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰1%9}!991}MM}Q=-8¹½Ğ½¹™¥ÕÉ•‰ô°€ÔÀÌ((€€€É½½Ğ€ôA…Ñ ¡É½½Ñ}‘¥È¤¥˜É½½Ñ}‘¥È•±Í”A…Ñ ¡}}™¥±•}|¤¹É•Í½±Ù” ¤¹Á…É•¹Ğ(€€€½¹™¥}Á…Ñ €ôÉ½½Ğ€¼€‰±¥¹”µÉ¥ µµ•¹Ôµ½¹™¥œ¹©Í½¸ˆ(€€€¥µ…•}Á…Ñ €ôÉ½½Ğ€¼€‰±¥¹”µÉ¥ µµ•¹Ô¹Á¹œˆ(€€€¥˜¹½Ğ½¹™¥}Á…Ñ ¹•á¥ÍÑÌ ¤è(€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè˜‰µ¥ÍÍ¥¹œí½¹™¥}Á…Ñ ¹¹…µ•ô‰ô°€ÔÀÀ(€€€¥˜¹½Ğ¥µ…•}Á…Ñ ¹•á¥ÍÑÌ ¤è(€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè˜‰µ¥ÍÍ¥¹œí¥µ…•}Á…Ñ ¹¹…µ•ô‰ô°€ÔÀÀ((€€€µ•¹Õ}½¹™¥œ€ô©Í½¸¹±½…‘Ì¡½¹™¥}Á…Ñ ¹É•…‘}Ñ•áĞ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤¤((€€€‘•˜}É•ÅÕ•ÍĞ¡µ•Ñ¡½°ÕÉ°°‰½‘äõ9½¹”°½¹Ñ•¹Ñ}ÑåÁ”ô‰…ÁÁ±¥…Ñ¥½¸½©Í½¸ˆ¤è(€€€€€€€‘…Ñ„€ô9½¹”(€€€€€€€¡•…‘•ÉÌ€ôì‰ÕÑ¡½É¥é…Ñ¥½¸ˆè˜‰	•…É•ÈíÑ½­•¹ô‰ô(€€€€€€€¥˜‰½‘ä¥Ì¹½Ğ9½¹”è(€€€€€€€€€€€¥˜½¹Ñ•¹Ñ}ÑåÁ”€ôô€‰…ÁÁ±¥…Ñ¥½¸½©Í½¸ˆè(€€€€€€€€€€€€€€€‘…Ñ„€ô©Í½¸¹‘ÕµÁÌ¡‰½‘ä°•¹ÍÕÉ•}…Í¥¤õ…±Í”¤¹•¹½‘” ‰ÕÑ˜´àˆ¤(€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€‘…Ñ„€ô‰½‘ä(€€€€€€€€€€€¡•…‘•ÉÍl‰½¹Ñ•¹ĞµQåÁ”‰t€ô½¹Ñ•¹Ñ}ÑåÁ”(€€€€€€€É•Ä€ôÕÉ±±¥ˆ¹É•ÅÕ•ÍĞ¹I•ÅÕ•ÍĞ¡ÕÉ°°‘…Ñ„õ‘…Ñ„°µ•Ñ¡½õµ•Ñ¡½°¡•…‘•ÉÌõ¡•…‘•ÉÌ¤(€€€€€€€ÑÉäè(€€€€€€€€€€€İ¥Ñ ÕÉ±±¥ˆ¹É•ÅÕ•ÍĞ¹ÕÉ±½Á•¸¡É•Ä°Ñ¥µ•½ÕĞôØÀ¤…ÌÉ•ÍÀè(€€€€€€€€€€€€€€€É…Ü€ôÉ•ÍÀ¹É•… ¤¹‘•½‘” ‰ÕÑ˜´àˆ°•ÉÉ½ÉÌô‰É•Á±…”ˆ¤(€€€€€€€€€€€€€€€½‘”€ô¥¹Ğ¡•Ñ…ÑÑÈ¡É•ÍÀ°€‰ÍÑ…ÑÕÌˆ°€ÈÀÀ¤½È€ÈÀÀ¤(€€€€€€€€€€€€€€€Á…ÉÍ•€ô©Í½¸¹±½…‘Ì¡É…Ü¤¥˜É…Ü¹ÍÑÉ¥À ¤•±Í”íô(€€€€€€€€€€€€€€€É•ÑÕÉ¸½‘”°Á…ÉÍ•(€€€€€€€•á•ÁĞÕÉ±±¥ˆ¹•ÉÉ½È¹!QQAÉÉ½È…Ì•áŒè(€€€€€€€€€€€•ÉÉ}‰½‘ä€ô•áŒ¹É•… ¤¹‘•½‘” ‰ÕÑ˜´àˆ°•ÉÉ½ÉÌô‰É•Á±…”ˆ¤(€€€€€€€€€€€É•ÑÕÉ¸¥¹Ğ¡•áŒ¹½‘”¤°ì‰•ÉÉ½Èˆè•ÉÉ}‰½‘åô((€€€½‘”°É•…Ñ•€ô}É•ÅÕ•ÍĞ ‰A=MPˆ°€‰¡ÑÑÁÌè¼½…Á¤¹±¥¹”¹µ”½ØÈ½‰½Ğ½É¥¡µ•¹Ôˆ°µ•¹Õ}½¹™¥œ¤(€€€¥˜½‘”€„ô€ÈÀÀ½È¹½ĞÉ•…Ñ•¹•Ğ ‰É¥¡5•¹Õ%ˆ¤è(€€€€€€€É•ÑÕÉ¸ì(€€€€€€€€€€€€‰½¬ˆè…±Í”°(€€€€€€€€€€€€‰ÍÑ•Àˆè€‰É•…Ñ”ˆ°(€€€€€€€€€€€€‰¡ÑÑÀˆè½‘”°(€€€€€€€€€€€€‰•ÉÉ½ÈˆèÉ•…Ñ•¹•Ğ ‰•ÉÉ½Èˆ¤½ÈÉ•…Ñ•°(€€€€€€€ô°€ÔÀÈ((€€€É¥¡}µ•¹Õ}¥€ôÉ•…Ñ•‘l‰É¥¡5•¹Õ%‰t(€€€½‘”°ÕÁ±½…‘•€ô}É•ÅÕ•ÍĞ (€€€€€€€€‰A=MPˆ°(€€€€€€€˜‰¡ÑÑÁÌè¼½…Á¤µ‘…Ñ„¹±¥¹”¹µ”½ØÈ½‰½Ğ½É¥¡µ•¹Ô½íÉ¥¡}µ•¹Õ}¥‘ô½½¹Ñ•¹Ğˆ°(€€€€€€€¥µ…•}Á…Ñ ¹É•…‘}‰åÑ•Ì ¤°(€€€€€€€½¹Ñ•¹Ñ}ÑåÁ”ô‰¥µ…”½Á¹œˆ°(€€€€¤(€€€¥˜½‘”¹½Ğ¥¸€ ÈÀÀ°€ÈÀĞ¤è(€€€€€€€É•ÑÕÉ¸ì(€€€€€€€€€€€€‰½¬ˆè…±Í”°(€€€€€€€€€€€€‰ÍÑ•Àˆè€‰ÕÁ±½…‘}¥µ…”ˆ°(€€€€€€€€€€€€‰É¥¡5•¹Õ%ˆèÉ¥¡}µ•¹Õ}¥°(€€€€€€€€€€€€‰¡ÑÑÀˆè½‘”°(€€€€€€€€€€€€‰•ÉÉ½ÈˆèÕÁ±½…‘•¹•Ğ ‰•ÉÉ½Èˆ¤½ÈÕÁ±½…‘•°(€€€€€€€ô°€ÔÀÈ((€€€½‘”°‘•™…Õ±Ñ•€ô}É•ÅÕ•ÍĞ (€€€€€€€€‰A=MPˆ°(€€€€€€€˜‰¡ÑÑÁÌè¼½…Á¤¹±¥¹”¹µ”½ØÈ½‰½Ğ½ÕÍ•È½…±°½É¥¡µ•¹Ô½íÉ¥¡}µ•¹Õ}¥‘ôˆ°(€€€€¤(€€€¥˜½‘”¹½Ğ¥¸€ ÈÀÀ°€ÈÀĞ¤è(€€€€€€€É•ÑÕÉ¸ì(€€€€€€€€€€€€‰½¬ˆè…±Í”°(€€€€€€€€€€€€‰ÍÑ•Àˆè€‰Í•Ñ}‘•™…Õ±Ğˆ°(€€€€€€€€€€€€‰É¥¡5•¹Õ%ˆèÉ¥¡}µ•¹Õ}¥°(€€€€€€€€€€€€‰¡ÑÑÀˆè½‘”°(€€€€€€€€€€€€‰•ÉÉ½Èˆè‘•™…Õ±Ñ•¹•Ğ ‰•ÉÉ½Èˆ¤½È‘•™…Õ±Ñ•°(€€€€€€€ô°€ÔÀÈ((€€€É•ÑÕÉ¸ì(€€€€€€€€‰½¬ˆèQÉÕ”°(€€€€€€€€‰É¥¡5•¹Õ%ˆèÉ¥¡}µ•¹Õ}¥°(€€€€€€€€‰¹…µ”ˆèµ•¹Õ}½¹™¥œ¹•Ğ ‰¹…µ”ˆ¤°(€€€€€€€€‰¡…Ñ	…ÉQ•áĞˆèµ•¹Õ}½¹™¥œ¹•Ğ ‰¡…Ñ	…ÉQ•áĞˆ¤°(€€€€€€€€‰¥µ…•}‰åÑ•Ìˆè¥µ…•}Á…Ñ ¹ÍÑ…Ğ ¤¹ÍÑ}Í¥é”°(€€€€€€€€‰…É•…Ìˆèl(€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€‰±…‰•°ˆè€¡…É•„¹•Ğ ‰…Ñ¥½¸ˆ¤½Èíô¤¹•Ğ ‰±…‰•°ˆ¤°(€€€€€€€€€€€€€€€€‰ÑåÁ”ˆè€¡…É•„¹•Ğ ‰…Ñ¥½¸ˆ¤½Èíô¤¹•Ğ ‰ÑåÁ”ˆ¤°(€€€€€€€€€€€€€€€€‰ÕÉ¤ˆè€¡…É•„¹•Ğ ‰…Ñ¥½¸ˆ¤½Èíô¤¹•Ğ ‰ÕÉ¤ˆ¤°(€€€€€€€€€€€€€€€€‰Ñ•áĞˆè€¡…É•„¹•Ğ ‰…Ñ¥½¸ˆ¤½Èíô¤¹•Ğ ‰Ñ•áĞˆ¤°(€€€€€€€€€€€ô(€€€€€€€€€€€™½È…É•„¥¸€¡µ•¹Õ}½¹™¥œ¹•Ğ ‰…É•…Ìˆ¤½Èmt¤(€€€€€€€t°(€€€ô°€ÈÀÀ(()‘•˜¥¹ÍÁ•Ñ}‘•™…Õ±Ñ}É¥¡}µ•¹Ô¡½¹™¥œõ9½¹”¤è(€€€€ˆˆ‹š~—¢¦‹n»–&7¦‚C¢¢·–r[šZ¦ã–Z»¾ò#–B¯–B–6–†(UI'¾ò'’â7–n{–
ÌÑ½­•»ˆˆˆ(€€€Ñ½­•¸€ô}±¥¹•}¡…¹¹•±}…•ÍÍ}Ñ½­•¸¡½¹™¥œ¤(€€€¥˜¹½ĞÑ½­•¸è(€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰1%9}!991}MM}Q=-8¹½Ğ½¹™¥ÕÉ•‰ô°€ÔÀÌ((€€€‘•˜}É•ÅÕ•ÍĞ¡µ•Ñ¡½°ÕÉ°¤è(€€€€€€€É•Ä€ôÕÉ±±¥ˆ¹É•ÅÕ•ÍĞ¹I•ÅÕ•ÍĞ (€€€€€€€€€€€ÕÉ°°µ•Ñ¡½õµ•Ñ¡½°¡•…‘•ÉÌõì‰ÕÑ¡½É¥é…Ñ¥½¸ˆè˜‰	•…É•ÈíÑ½­•¹ô‰ô(€€€€€€€€¤(€€€€€€€ÑÉäè(€€€€€€€€€€€İ¥Ñ ÕÉ±±¥ˆ¹É•ÅÕ•ÍĞ¹ÕÉ±½Á•¸¡É•Ä°Ñ¥µ•½ÕĞôØÀ¤…ÌÉ•ÍÀè(€€€€€€€€€€€€€€€É…Ü€ôÉ•ÍÀ¹É•… ¤¹‘•½‘” ‰ÕÑ˜´àˆ°•ÉÉ½ÉÌô‰É•Á±…”ˆ¤(€€€€€€€€€€€€€€€½‘”€ô¥¹Ğ¡•Ñ…ÑÑÈ¡É•ÍÀ°€‰ÍÑ…ÑÕÌˆ°€ÈÀÀ¤½È€ÈÀÀ¤(€€€€€€€€€€€€€€€Á…ÉÍ•€ô©Í½¸¹±½…‘Ì¡É…Ü¤¥˜É…Ü¹ÍÑÉ¥À ¤•±Í”íô(€€€€€€€€€€€€€€€É•ÑÕÉ¸½‘”°Á…ÉÍ•(€€€€€€€•á•ÁĞÕÉ±±¥ˆ¹•ÉÉ½È¹!QQAÉÉ½È…Ì•áŒè(€€€€€€€€€€€•ÉÉ}‰½‘ä€ô•áŒ¹É•… ¤¹‘•½‘” ‰ÕÑ˜´àˆ°•ÉÉ½ÉÌô‰É•Á±…”ˆ¤(€€€€€€€€€€€É•ÑÕÉ¸¥¹Ğ¡•áŒ¹½‘”¤°ì‰•ÉÉ½Èˆè•ÉÉ}‰½‘åô((€€€½‘”°‘•™…Õ±Ğ€ô}É•ÅÕ•ÍĞ ‰Pˆ°€‰¡ÑÑÁÌè¼½…Á¤¹±¥¹”¹µ”½ØÈ½‰½Ğ½ÕÍ•È½…±°½É¥¡µ•¹Ôˆ¤(€€€¥˜½‘”€„ô€ÈÀÀ½È¹½Ğ¥Í¥¹ÍÑ…¹”¡‘•™…Õ±Ğ°‘¥Ğ¤½È¹½Ğ‘•™…Õ±Ğ¹•Ğ ‰É¥¡5•¹Õ%ˆ¤è(€€€€€€€É•ÑÕÉ¸ì(€€€€€€€€€€€€‰½¬ˆè…±Í”°(€€€€€€€€€€€€‰ÍÑ•Àˆè€‰•Ñ}‘•™…Õ±Ğˆ°(€€€€€€€€€€€€‰¡ÑÑÀˆè½‘”°(€€€€€€€€€€€€‰•ÉÉ½Èˆè‘•™…Õ±Ğ¹•Ğ ‰•ÉÉ½Èˆ¤¥˜¥Í¥¹ÍÑ…¹”¡‘•™…Õ±Ğ°‘¥Ğ¤•±Í”‘•™…Õ±Ğ°(€€€€€€€ô°€ÔÀÈ((€€€É¥¡}µ•¹Õ}¥€ô‘•™…Õ±Ñl‰É¥¡5•¹Õ%‰t(€€€½‘”°‘•Ñ…¥°€ô}É•ÅÕ•ÍĞ ‰Pˆ°˜‰¡ÑÑÁÌè¼½…Á¤¹±¥¹”¹µ”½ØÈ½‰½Ğ½É¥¡µ•¹Ô½íÉ¥¡}µ•¹Õ}¥‘ôˆ¤(€€€¥˜½‘”€„ô€ÈÀÀ½È¹½Ğ¥Í¥¹ÍÑ…¹”¡‘•Ñ…¥°°‘¥Ğ¤è(€€€€€€€É•ÑÕÉ¸ì(€€€€€€€€€€€€‰½¬ˆè…±Í”°(€€€€€€€€€€€€‰ÍÑ•Àˆè€‰•Ñ}‘•Ñ…¥°ˆ°(€€€€€€€€€€€€‰É¥¡5•¹Õ%ˆèÉ¥¡}µ•¹Õ}¥°(€€€€€€€€€€€€‰¡ÑÑÀˆè½‘”°(€€€€€€€€€€€€‰•ÉÉ½Èˆè‘•Ñ…¥°¹•Ğ ‰•ÉÉ½Èˆ¤¥˜¥Í¥¹ÍÑ…¹”¡‘•Ñ…¥°°‘¥Ğ¤•±Í”‘•Ñ…¥°°(€€€€€€€ô°€ÔÀÈ((€€€…É•…Ì€ômt(€€€¥¹Ù¥Ñ•}ÕÉ¤€ô9½¹”(€€€¥¹Ù¥Ñ•}Ñ•áĞ€ô9½¹”(€€€¥¹Ù¥Ñ•}ÑåÁ”€ô9½¹”(€€€™½È…É•„¥¸‘•Ñ…¥°¹•Ğ ‰…É•…Ìˆ¤½Èmtè(€€€€€€€…Ñ¥½¸€ô…É•„¹•Ğ ‰…Ñ¥½¸ˆ¤½Èíô(€€€€€€€¥Ñ•´€ôì(€€€€€€€€€€€€‰±…‰•°ˆè…Ñ¥½¸¹•Ğ ‰±…‰•°ˆ¤°(€€€€€€€€€€€€‰ÑåÁ”ˆè…Ñ¥½¸¹•Ğ ‰ÑåÁ”ˆ¤°(€€€€€€€€€€€€‰ÕÉ¤ˆè…Ñ¥½¸¹•Ğ ‰ÕÉ¤ˆ¤°(€€€€€€€€€€€€‰Ñ•áĞˆè…Ñ¥½¸¹•Ğ ‰Ñ•áĞˆ¤°(€€€€€€€ô(€€€€€€€…É•…Ì¹…ÁÁ•¹¡¥Ñ•´¤(€€€€€€€¥˜…Ñ¥½¸¹•Ğ ‰±…‰•°ˆ¤€ôô€‹’â¦6×¦
¢®,ˆè(€€€€€€€€€€€¥¹Ù¥Ñ•}ÕÉ¤€ô…Ñ¥½¸¹•Ğ ‰ÕÉ¤ˆ¤(€€€€€€€€€€€¥¹Ù¥Ñ•}Ñ•áĞ€ô…Ñ¥½¸¹•Ğ ‰Ñ•áĞˆ¤(€€€€€€€€€€€¥¹Ù¥Ñ•}ÑåÁ”€ô…Ñ¥½¸¹•Ğ ‰ÑåÁ”ˆ¤((€€€€Œƒ–r[šZ¦ã–Z»–ş¦‚#¦Ë–—šÂã’æ1%ƒ–—–>	1%ƒšr¢ú£¢¶cfï–—šr–N‡–îë®/–Â#–Æ³¦
¢®/¾ò0(€€€€Œƒ¦j£–6Ï¦Z/–V|Í¡…É•Q…É•ÑA¥­•Ë¾òo’â7–>¿š*+ÚË®g¢Ş¿–úG¦f–*ƒ–r 1%%ƒ–ú3šZç(€€€¥¹Ù¥Ñ•}ÕÉ¥}½¬€ô…±Í”(€€€¥˜¥¹Ù¥Ñ•}ÕÉ¤è(€€€€€€€ÑÉäè(€€€€€€€€€€€Á…ÉÍ•‘}¥¹Ù¥Ñ•}ÕÉ¤€ôÕÉ±±¥ˆ¹Á…ÉÍ”¹ÕÉ±Á…ÉÍ”¡ÍÑÈ¡¥¹Ù¥Ñ•}ÕÉ¤¤¹ÍÑÉ¥À ¤¤(€€€€€€€€€€€¥¹Ù¥Ñ•}ÅÕ•Éä€ôÕÉ±±¥ˆ¹Á…ÉÍ”¹Á…ÉÍ•}ÅÌ¡Á…ÉÍ•‘}¥¹Ù¥Ñ•}ÕÉ¤¹ÅÕ•Éä¤(€€€€€€€€€€€¥¹Ù¥Ñ•}ÕÉ¥}½¬€ô€ (€€€€€€€€€€€€€€€Á…ÉÍ•‘}¥¹Ù¥Ñ•}ÕÉ¤¹Í¡•µ”€ôô€‰¡ÑÑÁÌˆ(€€€€€€€€€€€€€€€…¹Á…ÉÍ•‘}¥¹Ù¥Ñ•}ÕÉ¤¹¹•Ñ±½Œ€ôô€‰±¥™˜¹±¥¹”¹µ”ˆ(€€€€€€€€€€€€€€€…¹Á…ÉÍ•‘}¥¹Ù¥Ñ•}ÕÉ¤¹Á…Ñ ¹ÉÍÑÉ¥À ˆ¼ˆ¤€ôô˜ˆ½íU1Q}1%}%ôˆ(€€€€€€€€€€€€€€€…¹¥¹Ù¥Ñ•}ÅÕ•Éä¹•Ğ ‰½Á•¸ˆ¤€ôôl‰Í¡…É”µ¥¹Ù¥Ñ”‰t(€€€€€€€€€€€€¤(€€€€€€€•á•ÁĞ€¡QåÁ•ÉÉ½È°Y…±Õ•ÉÉ½È¤è(€€€€€€€€€€€¥¹Ù¥Ñ•}ÕÉ¥}½¬€ô…±Í”((€€€€Œƒ’î7nã–ºç¢"+& µ•ÍÍ…—3’â¦6×¦
¢®/7ŠH	½Ğ±•ã(€€€¥¹Ù¥Ñ•}½¬€ô¥¹Ù¥Ñ•}ÕÉ¥}½¬½È€ (€€€€€€€¥¹Ù¥Ñ•}ÑåÁ”€ôô€‰µ•ÍÍ…”ˆ(€€€€€€€…¹ÍÑÈ¡¥¹Ù¥Ñ•}Ñ•áĞ½È€ˆˆ¤¹ÍÑÉ¥À ¤¥¸ì‹’â¦6×¦
¢®,ˆ°€‹’â¦6×¦
¢®/–º#¢¶ß’êè‰ô(€€€€¤((€€€É•ÑÕÉ¸ì(€€€€€€€€‰½¬ˆèQÉÕ”°(€€€€€€€€‰É¥¡5•¹Õ%ˆèÉ¥¡}µ•¹Õ}¥°(€€€€€€€€‰¹…µ”ˆè‘•Ñ…¥°¹•Ğ ‰¹…µ”ˆ¤°(€€€€€€€€‰¡…Ñ	…ÉQ•áĞˆè‘•Ñ…¥°¹•Ğ ‰¡…Ñ	…ÉQ•áĞˆ¤°(€€€€€€€€‰…É•…Ìˆè…É•…Ì°(€€€€€€€€‰¥¹Ù¥Ñ•}ÕÉ¤ˆè¥¹Ù¥Ñ•}ÕÉ¤°(€€€€€€€€‰¥¹Ù¥Ñ•}Ñ•áĞˆè¥¹Ù¥Ñ•}Ñ•áĞ°(€€€€€€€€‰¥¹Ù¥Ñ•}ÑåÁ”ˆè¥¹Ù¥Ñ•}ÑåÁ”°(€€€€€€€€‰¥¹Ù¥Ñ•}ÕÉ¥}½¬ˆè¥¹Ù¥Ñ•}½¬°(€€€ô°€ÈÀÀ(()‘•˜É½¹}…±±½İ•¡½¹™¥œ°Í•É•Ğ¤è(€€€•áÁ•Ñ•€ô€¡½¹™¥œ¹•Ğ ‰I=9}MIPˆ¤½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰I=9}MIPˆ°€ˆˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€ÁÉ½Ù¥‘•€ôÍÑÈ¡Í•É•Ğ½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€ŒµÁÑäI=9}MIPµÕÍĞ¹•Ù•È…ÕÑ¡½É¥é”ƒŠP™…¥°±½Í•¸(€€€¥˜¹½Ğ•áÁ•Ñ•è(€€€€€€€É•ÑÕÉ¸…±Í”(€€€É•ÑÕÉ¸Í•É•ÑÌ¹½µÁ…É•}‘¥•ÍĞ¡•áÁ•Ñ•°ÁÉ½Ù¥‘•¤(()‘•˜}Á½Í¥Ñ¥Ù•}Á•É•¹Ñ…”¡½¹™¥œ°¹…µ”°‘•™…Õ±Ğ¤è(€€€É…Ü€ô½¹™¥œ¹•Ğ¡¹…µ”¤¥˜¡…Í…ÑÑÈ¡½¹™¥œ°€‰•Ğˆ¤•±Í”9½¹”(€€€¥˜É…Ü¥¸€¡9½¹”°€ˆˆ¤è(€€€€€€€É…Ü€ô½Ì¹•¹Ù¥É½¸¹•Ğ¡¹…µ”°€ˆˆ¤(€€€ÑÉäè(€€€€€€€Ù…±Õ”€ô¥¹Ğ¡ÍÑÈ¡É…Ü½È‘•™…Õ±Ğ¤¤(€€€•á•ÁĞ€¡QåÁ•ÉÉ½È°Y…±Õ•ÉÉ½È¤è(€€€€€€€É•ÑÕÉ¸‘•™…Õ±Ğ(€€€É•ÑÕÉ¸Ù…±Õ”¥˜€Ä€ğôÙ…±Õ”€ğô€ÄÀÀ•±Í”‘•™…Õ±Ğ(()‘•˜±¥¹•}µ•ÍÍ…•}‰Õ‘•Ñ}ÍÑ…ÑÕÌ¡ÍÑ…Ñ”°½¹™¥œõ9½¹”°¹½Üõ9½¹”¤è(€€€€ˆˆ‰I•ÑÕÉ¸ÍåÍÑ•´µÉ•½É‘•1%9ÕÍ…”İ¥Ñ¡½ÕĞ•áÁ½Í¥¹œ½¹™¥ÕÉ…Ñ¥½¸Ù…±Õ•Ì¸ˆˆˆ(€€€™œ€ô½¹™¥œ¥˜½¹™¥œ¥Ì¹½Ğ9½¹”…¹¡…Í…ÑÑÈ¡½¹™¥œ°€‰•Ğˆ¤•±Í”íô(€€€•¹•É…Ñ•‘}…Ğ€ô¹½Ü½ÈÕÉÉ•¹Ñ}…ÁÁ}Ñ¥µ”¡™œ¤(€€€ÑÉäè(€€€€€€€µ•ÍÍ…•}±¥µ¥Ğ€ôµ…à (€€€€€€€€€€€€Ä°(€€€€€€€€€€€¥¹Ğ¡ÍÑÈ¡™œ¹•Ğ ‰1%9}5=9Q!1e}5MM}1%5%Pˆ¤(€€€€€€€€€€€€€€€€€€€½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}5=9Q!1e}5MM}1%5%Pˆ°€ˆˆ¤(€€€€€€€€€€€€€€€€€€€½È€ÈÀÀ¤¤°(€€€€€€€€¤(€€€•á•ÁĞ€¡QåÁ•ÉÉ½È°Y…±Õ•ÉÉ½È¤è(€€€€€€€µ•ÍÍ…•}±¥µ¥Ğ€ô€ÈÀÀ(€€€İ…É¹¥¹}Á•É•¹Ğ€ô}Á½Í¥Ñ¥Ù•}Á•É•¹Ñ…” (€€€€€€€™œ°€‰1%9}5MM}]I9%9}AI9Pˆ°€àÀ(€€€€¤(€€€¡…É‘}ÍÑ½Á}Á•É•¹Ğ€ô}Á½Í¥Ñ¥Ù•}Á•É•¹Ñ…” (€€€€€€€™œ°€‰1%9}5MM}!I}MQ=A}AI9Pˆ°€ÄÀÀ(€€€€¤(€€€µ½¹Ñ¡}­•ä€ô•¹•É…Ñ•‘}…Ğ¹ÍÑÉ™Ñ¥µ” ˆ•d´•´ˆ¤(€€€µ½¹Ñ¡±å}±½Ì€ôl(€€€€€€€¥Ñ•´(€€€€€€€™½È¥Ñ•´¥¸€¡ÍÑ…Ñ”¹•Ğ ‰¹½Ñ¥™¥…Ñ¥½¹}±½Ìˆ¤½Èmt¤(€€€€€€€¥˜¹½ĞÍÑÈ¡¥Ñ•´¹•Ğ ‰É•…Ñ•‘}…Ğˆ¤½È€ˆˆ¤(€€€€€€€½ÈÍÑÈ¡¥Ñ•´¹•Ğ ‰É•…Ñ•‘}…Ğˆ¤½È€ˆˆ¤¹ÍÑ…ÉÑÍİ¥Ñ ¡µ½¹Ñ¡}­•ä¤(€€€t(€€€ÕÍ•€ô±•¸¡µ½¹Ñ¡±å}±½Ì¤(€€€ÕÍ…•}Á•É•¹Ğ€ôÉ½Õ¹¡ÕÍ•€¼µ•ÍÍ…•}±¥µ¥Ğ€¨€ÄÀÀ°€Ä¤(€€€¡…É‘}ÍÑ½Á}…Ñ¥Ù”€ôÕÍ…•}Á•É•¹Ğ€øô¡…É‘}ÍÑ½Á}Á•É•¹Ğ(€€€¥˜ÕÍ•€øôµ•ÍÍ…•}±¥µ¥Ğè(€€€€€€€ÍÑ…ÑÕÌ€ô€‰•á••‘•ˆ(€€€•±¥˜ÕÍ…•}Á•É•¹Ğ€øôİ…É¹¥¹}Á•É•¹Ğè(€€€€€€€ÍÑ…ÑÕÌ€ô€‰İ…É¹¥¹œˆ(€€€•±Í”è(€€€€€€€ÍÑ…ÑÕÌ€ô€‰¡•…±Ñ¡äˆ(€€€É•ÑÕÉ¸ì(€€€€€€€€‰µ½¹Ñ ˆèµ½¹Ñ¡}­•ä°(€€€€€€€€‰ÕÍ•ˆèÕÍ•°(€€€€€€€€‰±¥µ¥Ğˆèµ•ÍÍ…•}±¥µ¥Ğ°(€€€€€€€€‰É•µ…¥¹¥¹œˆèµ…à À°µ•ÍÍ…•}±¥µ¥Ğ€´ÕÍ•¤°(€€€€€€€€‰ÕÍ…•}Á•É•¹ĞˆèÕÍ…•}Á•É•¹Ğ°(€€€€€€€€‰İ…É¹¥¹}Á•É•¹Ğˆèİ…É¹¥¹}Á•É•¹Ğ°(€€€€€€€€‰¡…É‘}ÍÑ½Á}Á•É•¹Ğˆè¡…É‘}ÍÑ½Á}Á•É•¹Ğ°(€€€€€€€€‰¡…É‘}ÍÑ½Á}…Ñ¥Ù”ˆè¡…É‘}ÍÑ½Á}…Ñ¥Ù”°(€€€€€€€€‰ÍÑ…ÑÕÌˆèÍÑ…ÑÕÌ°(€€€ô(()‘•˜±¥¹•}¹½¹}•µ•É•¹å}ÁÕÍ¡}…±±½İ•¡ÍÑ…Ñ”°½¹™¥œõ9½¹”°¹½Üõ9½¹”¤è(€€€É•ÑÕÉ¸¹½Ğ±¥¹•}µ•ÍÍ…•}‰Õ‘•Ñ}ÍÑ…ÑÕÌ¡ÍÑ…Ñ”°½¹™¥œ°¹½Ü¥l‰¡…É‘}ÍÑ½Á}…Ñ¥Ù”‰t(()‘•˜±¥¹•}ÁÕÍ¡}…±±½İ•‘}™½É}­¥¹¡ÍÑ…Ñ”°½¹™¥œ°­¥¹°¹½Üõ9½¹”¤è(€€€•µ•É•¹å}­¥¹‘Ì€ôì‰Í½Ìˆ°€‰Í…™•Ñå}Õ…Éˆ°€‰Õ…É‘¥…¹}Í½Ìˆ°€‰•µ•É•¹ä‰ô(€€€¥˜ÍÑÈ¡­¥¹½È€ˆˆ¤¹ÍÑÉ¥À ¤¹…Í•™½± ¤¥¸•µ•É•¹å}­¥¹‘Ìè(€€€€€€€É•ÑÕÉ¸QÉÕ”(€€€É•ÑÕÉ¸±¥¹•}¹½¹}•µ•É•¹å}ÁÕÍ¡}…±±½İ•¡ÍÑ…Ñ”°½¹™¥œ°¹½Ü¤(()‘•˜±¥¹•}‰Õ‘•Ñ}‰±½­•‘}É•ÍÁ½¹Í”¡ÍÑ…Ñ”°½¹™¥œ°¹½Üõ9½¹”¤è(€€€‰Õ‘•Ğ€ô±¥¹•}µ•ÍÍ…•}‰Õ‘•Ñ}ÍÑ…ÑÕÌ¡ÍÑ…Ñ”°½¹™¥œ°¹½Ü¤(€€€É•ÑÕÉ¸ì(€€€€€€€€‰Í•¹Ğˆè€À°(€€€€€€€€‰Í­¥ÁÁ•ˆè€À°(€€€€€€€€‰•ÉÉ½Èˆè€‰±¥¹•}¹½¹}•µ•É•¹å}‰Õ‘•Ñ}¡…É‘}ÍÑ½Àˆ°(€€€€€€€€‰±¥¹•}‰Õ‘•Ğˆè‰Õ‘•Ğ°(€€€ô°€ĞÈä(()	Q}=!=IQL€ôì(€€€€‰­¹½İ¹|ÄÀˆèì‰±…‰•°ˆè€‹¢ª7¢¶cšr–N„€ÄÀƒ’êèˆ°€‰…Á…¥Ñäˆè€ÄÁô°(€€€€‰ÍÑ…¹‘…É‘|ÈÀˆèì‰±…‰•°ˆè€‹’â¢"³šr–N„€ÈÀƒ’êèˆ°€‰…Á…¥Ñäˆè€ÈÁô°(€€€€‰™…µ¥±å}É½ÕÁ|ÄÀˆèì‰±…‰•°ˆè€‹–ºÛ–ê·ú“Ö€ÄÀƒ’êèˆ°€‰…Á…¥Ñäˆè€ÄÁô°)ô)	Q}Q%Y}MQQUML€ôì‰…Ñ¥Ù”ˆ°€‰İ…¥Ñ±¥ÍÑ•‰ô)	Q}MQQUML€ô	Q}Q%Y}MQQUMLğì‰½µÁ±•Ñ•ˆ°€‰İ¥Ñ¡‘É…İ¸‰ô(()‘•˜…‘µ¥¹}‰•Ñ…}ÍÕµµ…Éä¡‘…Ñ…}™¥±”°¹½Üõ9½¹”¤è(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€µ•µ‰•ÉÌ€ô±¥ÍĞ¡ÍÑ…Ñ”¹•Ğ ‰‰•Ñ…}ÁÉ½É…µ}µ•µ‰•ÉÌˆ¤½Èmt¤(€€€ÕÉÉ•¹Ğ€ô¹½Ü½ÈÕÉÉ•¹Ñ}…ÁÁ}Ñ¥µ”¡íô¤(€€€±•…å}½¡½ÉÑ}µ…À€ôì(€€€€€€€€‰­¹½İ¹|ÄÀˆè€‰ˆ°(€€€€€€€€‰ÍÑ…¹‘…É‘|ÈÀˆè€‰Ìääˆ°(€€€€€€€€‰™…µ¥±å}É½ÕÁ|ÄÀˆè€‰Üääˆ°(€€€ô(€€€‰…­™¥±±•€ô…±Í”(€€€™½Èµ•µ‰•È¥¸µ•µ‰•ÉÌè(€€€€€€€¥˜µ•µ‰•È¹•Ğ ‰ÍÑ…ÑÕÌˆ¤¹½Ğ¥¸	Q}Q%Y}MQQUMLè(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€±¥¹•}ÕÍ•É}¥€ôÍÑÈ¡µ•µ‰•È¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€ÁÉ½™¥±”€ô€¡ÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ¤½Èíô¤¹•Ğ¡±¥¹•}ÕÍ•É}¥¤(€€€€€€€¥˜¹½Ğ¥Í¥¹ÍÑ…¹”¡ÁÉ½™¥±”°‘¥Ğ¤½ÈÁÉ½™¥±”¹•Ğ ‰µ•µ‰•ÉÍ¡¥Á}Í½ÕÉ”ˆ¤€ôô€‰‰•Ñ„ˆè(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€•¹Ñ¥Ñ±•µ•¹Ñ}½¡½ÉĞ€ô±•…å}½¡½ÉÑ}µ…À¹•Ğ¡ÍÑÈ¡µ•µ‰•È¹•Ğ ‰½¡½ÉĞˆ¤½È€ˆˆ¤¤(€€€€€€€¥˜¹½Ğ•¹Ñ¥Ñ±•µ•¹Ñ}½¡½ÉĞè(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€ÍÑ…ÉÑ•€ôÁ…ÉÍ•}‘…Ñ•Ñ¥µ”¡µ•µ‰•È¹•Ğ ‰ÍÑ…ÉÑÍ}…Ğˆ¤¤½ÈÕÉÉ•¹Ğ(€€€€€€€ÑÉäè(€€€€€€€€€€€…ÍÍ¥¹}‰•Ñ…}½¡½ÉĞ (€€€€€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€•¹Ñ¥Ñ±•µ•¹Ñ}½¡½ÉĞ°(€€€€€€€€€€€€€€€¹½ÜõÍÑ…ÉÑ•°(€€€€€€€€€€€€€€€É•ÉÕ¥Ñµ•¹Ñ}Í½ÕÉ”õ˜‰…‘µ¥¸µíµ•µ‰•È¹•Ğ ½¡½ÉĞœ¥ôˆ°(€€€€€€€€€€€€¤(€€€€€€€•á•ÁĞY…±Õ•ÉÉ½Èè(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¥˜µ•µ‰•È¹•Ğ ‰•¹‘Í}…Ğˆ¤è(€€€€€€€€€€€ÁÉ½™¥±•l‰‰•Ñ…}•¹‘Í}…Ğ‰t€ôÍÑÈ¡µ•µ‰•Él‰•¹‘Í}…Ğ‰t¤(€€€€€€€‰…­™¥±±•€ôQÉÕ”(€€€¥˜‰…­™¥±±•è(€€€€€€€Í…Ù•}ÍÑ…Ñ”¡‘…Ñ…}™¥±”°ÍÑ…Ñ”¤(€€€½¡½ÉÑÌ€ôíô(€€€™½È­•ä°‘•™¥¹¥Ñ¥½¸¥¸	Q}=!=IQL¹¥Ñ•µÌ ¤è(€€€€€€€½¡½ÉÑ}µ•µ‰•ÉÌ€ômÉ½Ü™½ÈÉ½Ü¥¸µ•µ‰•ÉÌ¥˜É½Ü¹•Ğ ‰½¡½ÉĞˆ¤€ôô­•åt(€€€€€€€…Ñ¥Ù”€ôÍÕ´ (€€€€€€€€€€€€Ä™½ÈÉ½Ü¥¸½¡½ÉÑ}µ•µ‰•ÉÌ¥˜É½Ü¹•Ğ ‰ÍÑ…ÑÕÌˆ¤¥¸	Q}Q%Y}MQQUML(€€€€€€€€¤(€€€€€€€½¡½ÉÑÍm­•åt€ôì(€€€€€€€€€€€€¨©‘•™¥¹¥Ñ¥½¸°(€€€€€€€€€€€€‰…Ñ¥Ù”ˆè…Ñ¥Ù”°(€€€€€€€€€€€€‰½µÁ±•Ñ•ˆèÍÕ´ (€€€€€€€€€€€€€€€€Ä™½ÈÉ½Ü¥¸½¡½ÉÑ}µ•µ‰•ÉÌ¥˜É½Ü¹•Ğ ‰ÍÑ…ÑÕÌˆ¤€ôô€‰½µÁ±•Ñ•ˆ(€€€€€€€€€€€€¤°(€€€€€€€€€€€€‰É•µ…¥¹¥¹œˆèµ…à À°‘•™¥¹¥Ñ¥½¹l‰…Á…¥Ñä‰t€´…Ñ¥Ù”¤°(€€€€€€€ô(€€€É•ÑÕÉ¸ì(€€€€€€€€‰‘ÕÉ…Ñ¥½¹}‘…åÌˆè€ÈÄ°(€€€€€€€€‰•¹•É…Ñ•‘}…ĞˆèÕÉÉ•¹Ğ¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤°(€€€€€€€€‰½¡½ÉÑÌˆè½¡½ÉÑÌ°(€€€€€€€€‰µ•µ‰•ÉÌˆè±¥ÍĞ¡É•Ù•ÉÍ•¡µ•µ‰•ÉÍl´ÄÀÀét¤¤°(€€€ô(()‘•˜…ÍÍ¥¹}‰•Ñ…}µ•µ‰•È¡‘…Ñ…}™¥±”°Á…å±½…°¹½Üõ9½¹”¤è(€€€±¥¹•}ÕÍ•É}¥€ôÍÑÈ ¡Á…å±½…½Èíô¤¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€½¡½ÉĞ€ôÍÑÈ ¡Á…å±½…½Èíô¤¹•Ğ ‰½¡½ÉĞˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€¥˜¹½Ğ±¥¹•}ÕÍ•É}¥½È½¡½ÉĞ¹½Ğ¥¸	Q}=!=IQLè(€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰¥¹Ù…±¥‘}‰•Ñ…}…ÍÍ¥¹µ•¹Ğ‰ô°€ĞÀÀ(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€ÁÉ½™¥±”€ô€¡ÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ¤½Èíô¤¹•Ğ¡±¥¹•}ÕÍ•É}¥¤(€€€¥˜ÁÉ½™¥±”¥Ì9½¹”è(€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰µ•µ‰•É}¹½Ñ}™½Õ¹‰ô°€ĞÀĞ(€€€µ•µ‰•ÉÌ€ôÍÑ…Ñ”¹Í•Ñ‘•™…Õ±Ğ ‰‰•Ñ…}ÁÉ½É…µ}µ•µ‰•ÉÌˆ°mt¤(€€€•á¥ÍÑ¥¹œ€ô¹•áĞ (€€€€€€€€ (€€€€€€€€€€€É½Ü™½ÈÉ½Ü¥¸µ•µ‰•ÉÌ(€€€€€€€€€€€¥˜É½Ü¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤€ôô±¥¹•}ÕÍ•É}¥(€€€€€€€€€€€…¹É½Ü¹•Ğ ‰ÍÑ…ÑÕÌˆ¤¥¸	Q}Q%Y}MQQUML(€€€€€€€€¤°(€€€€€€€9½¹”°(€€€€¤(€€€¥˜•á¥ÍÑ¥¹œè(€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰‰•Ñ…}µ•µ‰•É}…±É•…‘å}…ÍÍ¥¹•‰ô°€ĞÀä(€€€…Ñ¥Ù•}½Õ¹Ğ€ôÍÕ´ (€€€€€€€€Ä™½ÈÉ½Ü¥¸µ•µ‰•ÉÌ(€€€€€€€¥˜É½Ü¹•Ğ ‰½¡½ÉĞˆ¤€ôô½¡½ÉĞ(€€€€€€€…¹É½Ü¹•Ğ ‰ÍÑ…ÑÕÌˆ¤¥¸	Q}Q%Y}MQQUML(€€€€¤(€€€¥˜…Ñ¥Ù•}½Õ¹Ğ€øô	Q}=!=IQMm½¡½ÉÑul‰…Á…¥Ñä‰tè(€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰‰•Ñ…}½¡½ÉÑ}™Õ±°‰ô°€ĞÀä(€€€ÍÑ…ÉÑ•€ô¹½Ü½ÈÕÉÉ•¹Ñ}…ÁÁ}Ñ¥µ”¡íô¤(€€€•¹Ñ¥Ñ±•µ•¹Ñ}½¡½ÉĞ€ôì(€€€€€€€€‰­¹½İ¹|ÄÀˆè€‰ˆ°(€€€€€€€€‰ÍÑ…¹‘…É‘|ÈÀˆè€‰Ìääˆ°(€€€€€€€€‰™…µ¥±å}É½ÕÁ|ÄÀˆè€‰Üääˆ°(€€€õm½¡½ÉÑt(€€€ÑÉäè(€€€€€€€…ÍÍ¥¹}‰•Ñ…}½¡½ÉĞ (€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€•¹Ñ¥Ñ±•µ•¹Ñ}½¡½ÉĞ°(€€€€€€€€€€€¹½ÜõÍÑ…ÉÑ•°(€€€€€€€€€€€É•ÉÕ¥Ñµ•¹Ñ}Í½ÕÉ”õ˜‰…‘µ¥¸µí½¡½ÉÑôˆ°(€€€€€€€€¤(€€€•á•ÁĞY…±Õ•ÉÉ½È…Ì•áŒè(€€€€€€€•ÉÉ½È€ôÍÑÈ¡•áŒ¤(€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè•ÉÉ½Éô°€ (€€€€€€€€€€€€ĞÀĞ¥˜•ÉÉ½È€ôô€‰µ•µ‰•É}¹½Ñ}™½Õ¹ˆ(€€€€€€€€€€€•±Í”€ĞÀä¥˜•ÉÉ½È¥¸ì‰½¡½ÉÑ}™Õ±°ˆ°€‰™É••}•±¥¥‰¥±¥Ñå}…±É•…‘å}ÕÍ•‰ô(€€€€€€€€€€€•±Í”€ĞÀÀ(€€€€€€€€¤(€€€ÁÉ½™¥±”€ôÍÑ…Ñ•l‰ÕÍ•ÉÌ‰um±¥¹•}ÕÍ•É}¥‘t(€€€¥˜¹½ĞÁÉ½™¥±”¹•Ğ ‰É•µ¥¹‘•É}Ñ¥µ•Ìˆ¤è(€€€€€€€…ÁÁ±å}É•µ¥¹‘•É}Ñ¥µ•Í}Ñ½}ÁÉ½™¥±”¡ÁÉ½™¥±”¤(€€€µ•µ‰•È€ôì(€€€€€€€€‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°(€€€€€€€€‰‘¥ÍÁ±…å}¹…µ”ˆèÍÑÈ¡ÁÉ½™¥±”¹•Ğ ‰‘¥ÍÁ±…å}¹…µ”ˆ¤½È€‹šr«–>[–ú_šjÇ¢Äˆ¤°(€€€€€€€€‰½¡½ÉĞˆè½¡½ÉĞ°(€€€€€€€€‰ÍÑ…ÑÕÌˆè€‰…Ñ¥Ù”ˆ°(€€€€€€€€‰ÍÑ…ÉÑÍ}…ĞˆèÍÑ…ÉÑ•¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤°(€€€€€€€€‰•¹‘Í}…Ğˆè€¡ÍÑ…ÉÑ•€¬Ñ¥µ•‘•±Ñ„¡‘…åÌôÈÄ¤¤¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤°(€€€€€€€€‰½ÕÑ½µ•}¹½Ñ”ˆè€ˆˆ°(€€€ô(€€€µ•µ‰•ÉÌ¹…ÁÁ•¹¡µ•µ‰•È¤(€€€ÍÑ…Ñ•l‰‰•Ñ…}ÁÉ½É…µ}µ•µ‰•ÉÌ‰t€ôµ•µ‰•ÉÍl´ÈÀÀét(€€€Í…Ù•}ÍÑ…Ñ”¡‘…Ñ…}™¥±”°ÍÑ…Ñ”¤(€€€É•ÑÕÉ¸ì‰½¬ˆèQÉÕ”°€‰µ•µ‰•Èˆèµ•µ‰•Éô°€ÈÀÀ(()‘•˜ÕÁ‘…Ñ•}‰•Ñ…}µ•µ‰•È¡‘…Ñ…}™¥±”°Á…å±½…°¹½Üõ9½¹”¤è(€€€±¥¹•}ÕÍ•É}¥€ôÍÑÈ ¡Á…å±½…½Èíô¤¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€ÍÑ…ÑÕÌ€ôÍÑÈ ¡Á…å±½…½Èíô¤¹•Ğ ‰ÍÑ…ÑÕÌˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤¹…Í•™½± ¤(€€€¥˜¹½Ğ±¥¹•}ÕÍ•É}¥½ÈÍÑ…ÑÕÌ¹½Ğ¥¸	Q}MQQUMLè(€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰¥¹Ù…±¥‘}‰•Ñ…}ÕÁ‘…Ñ”‰ô°€ĞÀÀ(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€µ•µ‰•È€ô¹•áĞ (€€€€€€€€ (€€€€€€€€€€€É½Ü™½ÈÉ½Ü¥¸É•Ù•ÉÍ•¡ÍÑ…Ñ”¹•Ğ ‰‰•Ñ…}ÁÉ½É…µ}µ•µ‰•ÉÌˆ¤½Èmt¤(€€€€€€€€€€€¥˜É½Ü¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤€ôô±¥¹•}ÕÍ•É}¥(€€€€€€€€€€€…¹É½Ü¹•Ğ ‰ÍÑ…ÑÕÌˆ¤¥¸	Q}Q%Y}MQQUML(€€€€€€€€¤°(€€€€€€€9½¹”°(€€€€¤(€€€¥˜µ•µ‰•È¥Ì9½¹”è(€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰‰•Ñ…}µ•µ‰•É}¹½Ñ}™½Õ¹‰ô°€ĞÀĞ(€€€µ•µ‰•Él‰ÍÑ…ÑÕÌ‰t€ôÍÑ…ÑÕÌ(€€€µ•µ‰•Él‰ÕÁ‘…Ñ•‘}…Ğ‰t€ô€¡¹½Ü½ÈÕÉÉ•¹Ñ}…ÁÁ}Ñ¥µ”¡íô¤¤¹¥Í½™½Éµ…Ğ (€€€€€€€Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ(€€€€¤(€€€¹½Ñ”€ôÍÑÈ ¡Á…å±½…½Èíô¤¹•Ğ ‰½ÕÑ½µ•}¹½Ñ”ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¥lèÔÀÁt(€€€¥˜¹½Ñ”è(€€€€€€€µ•µ‰•Él‰½ÕÑ½µ•}¹½Ñ”‰t€ô¹½Ñ”(€€€Í…Ù•}ÍÑ…Ñ”¡‘…Ñ…}™¥±”°ÍÑ…Ñ”¤(€€€É•ÑÕÉ¸ì‰½¬ˆèQÉÕ”°€‰µ•µ‰•Èˆèµ•µ‰•Éô°€ÈÀÀ(()‘•˜…‘µ¥¹}ÁÉ¥Ù…å}É•ÅÕ•ÍÑÌ¡‘…Ñ…}™¥±”¤è(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€É•ÅÕ•ÍÑÌ€ô±¥ÍĞ¡É•Ù•ÉÍ• ¡ÍÑ…Ñ”¹•Ğ ‰ÁÉ¥Ù…å}É•ÅÕ•ÍÑÌˆ¤½Èmt¥l´ÄÀÀét¤¤(€€€ÍÑ…ÑÕÍ•Ì€ô€ ‰Á•¹‘¥¹œˆ°€‰¥¹}ÁÉ½É•ÍÌˆ°€‰½µÁ±•Ñ•ˆ°€‰É•©•Ñ•ˆ¤(€€€É•ÑÕÉ¸ì(€€€€€€€€‰É•ÅÕ•ÍÑÌˆèÉ•ÅÕ•ÍÑÌ°(€€€€€€€€‰½Õ¹ÑÌˆèì(€€€€€€€€€€€ÍÑ…ÑÕÌèÍÕ´ Ä™½ÈÉ½Ü¥¸É•ÅÕ•ÍÑÌ¥˜É½Ü¹•Ğ ‰ÍÑ…ÑÕÌˆ¤€ôôÍÑ…ÑÕÌ¤(€€€€€€€€€€€™½ÈÍÑ…ÑÕÌ¥¸ÍÑ…ÑÕÍ•Ì(€€€€€€€ô°(€€€ô(()‘•˜É•…Ñ•}ÁÉ¥Ù…å}É•ÅÕ•ÍĞ¡‘…Ñ…}™¥±”°Á…å±½…°¹½Üõ9½¹”¤è(€€€±¥¹•}ÕÍ•É}¥€ôÍÑÈ ¡Á…å±½…½Èíô¤¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€É•ÅÕ•ÍÑ}ÑåÁ”€ôÍÑÈ ¡Á…å±½…½Èíô¤¹•Ğ ‰É•ÅÕ•ÍÑ}ÑåÁ”ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤¹…Í•™½± ¤(€€€¥˜¹½Ğ±¥¹•}ÕÍ•É}¥½ÈÉ•ÅÕ•ÍÑ}ÑåÁ”¹½Ğ¥¸ì(€€€€€€€€‰•áÁ½ÉĞˆ°€‰‘•±•Ñ¥½¸ˆ°€‰½ÉÉ•Ñ¥½¸ˆ°€‰¥¹ÅÕ¥Éäˆ(€€€ôè(€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰¥¹Ù…±¥‘}ÁÉ¥Ù…å}É•ÅÕ•ÍĞ‰ô°€ĞÀÀ(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€¥˜±¥¹•}ÕÍ•É}¥¹½Ğ¥¸€¡ÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ¤½Èíô¤è(€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰µ•µ‰•É}¹½Ñ}™½Õ¹‰ô°€ĞÀĞ(€€€É•ÅÕ•ÍÑÌ€ôÍÑ…Ñ”¹Í•Ñ‘•™…Õ±Ğ ‰ÁÉ¥Ù…å}É•ÅÕ•ÍÑÌˆ°mt¤(€€€¥˜…¹ä (€€€€€€€É½Ü¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤€ôô±¥¹•}ÕÍ•É}¥(€€€€€€€…¹É½Ü¹•Ğ ‰É•ÅÕ•ÍÑ}ÑåÁ”ˆ¤€ôôÉ•ÅÕ•ÍÑ}ÑåÁ”(€€€€€€€…¹É½Ü¹•Ğ ‰ÍÑ…ÑÕÌˆ¤¥¸ì‰Á•¹‘¥¹œˆ°€‰¥¹}ÁÉ½É•ÍÌ‰ô(€€€€€€€™½ÈÉ½Ü¥¸É•ÅÕ•ÍÑÌ(€€€€¤è(€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰ÁÉ¥Ù…å}É•ÅÕ•ÍÑ}…±É•…‘å}½Á•¸‰ô°€ĞÀä(€€€É•…Ñ•€ô¹½Ü½ÈÕÉÉ•¹Ñ}…ÁÁ}Ñ¥µ”¡íô¤(€€€ÁÉ¥Ù…å}É•ÅÕ•ÍĞ€ôì(€€€€€€€€‰¥ˆè˜‰ÁÉ¥Ù…äµíÍ•É•ÑÌ¹Ñ½­•¹}¡•à à¥ôˆ°(€€€€€€€€‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°(€€€€€€€€‰É•ÅÕ•ÍÑ}ÑåÁ”ˆèÉ•ÅÕ•ÍÑ}ÑåÁ”°(€€€€€€€€‰ÍÕµµ…ÉäˆèÍÑÈ ¡Á…å±½…½Èíô¤¹•Ğ ‰ÍÕµµ…Éäˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¥lèÔÀÁt°(€€€€€€€€‰ÍÑ…ÑÕÌˆè€‰Á•¹‘¥¹œˆ°(€€€€€€€€‰É•…Ñ•‘}…ĞˆèÉ•…Ñ•¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤°(€€€ô(€€€É•ÅÕ•ÍÑÌ¹…ÁÁ•¹¡ÁÉ¥Ù…å}É•ÅÕ•ÍĞ¤(€€€ÍÑ…Ñ•l‰ÁÉ¥Ù…å}É•ÅÕ•ÍÑÌ‰t€ôÉ•ÅÕ•ÍÑÍl´ÈÀÀét(€€€Í…Ù•}ÍÑ…Ñ”¡‘…Ñ…}™¥±”°ÍÑ…Ñ”¤(€€€É•ÑÕÉ¸ì‰½¬ˆèQÉÕ”°€‰É•ÅÕ•ÍĞˆèÁÉ¥Ù…å}É•ÅÕ•ÍÑô°€ÈÀÄ(()‘•˜ÕÁ‘…Ñ•}ÁÉ¥Ù…å}É•ÅÕ•ÍĞ¡‘…Ñ…}™¥±”°Á…å±½…°…Ñ½É}É½±”¤è(€€€É•ÅÕ•ÍÑ}¥€ôÍÑÈ ¡Á…å±½…½Èíô¤¹•Ğ ‰É•ÅÕ•ÍÑ}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€ÍÑ…ÑÕÌ€ôÍÑÈ ¡Á…å±½…½Èíô¤¹•Ğ ‰ÍÑ…ÑÕÌˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤¹…Í•™½± ¤(€€€¹½Ñ”€ôÍÑÈ ¡Á…å±½…½Èíô¤¹•Ğ ‰É•Í½±ÕÑ¥½¹}¹½Ñ”ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¥lèÄÀÀÁt(€€€¥˜¹½ĞÉ•ÅÕ•ÍÑ}¥½ÈÍÑ…ÑÕÌ¹½Ğ¥¸ì(€€€€€€€€‰Á•¹‘¥¹œˆ°€‰¥¹}ÁÉ½É•ÍÌˆ°€‰½µÁ±•Ñ•ˆ°€‰É•©•Ñ•ˆ(€€€ôè(€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰¥¹Ù…±¥‘}ÁÉ¥Ù…å}ÕÁ‘…Ñ”‰ô°€ĞÀÀ(€€€¥˜ÍÑ…ÑÕÌ¥¸ì‰½µÁ±•Ñ•ˆ°€‰É•©•Ñ•‰ô…¹¹½Ğ¹½Ñ”è(€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰É•Í½±ÕÑ¥½¹}¹½Ñ•}É•ÅÕ¥É•‰ô°€ĞÀÀ(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€ÁÉ¥Ù…å}É•ÅÕ•ÍĞ€ô¹•áĞ (€€€€€€€€ (€€€€€€€€€€€É½Ü™½ÈÉ½Ü¥¸€¡ÍÑ…Ñ”¹•Ğ ‰ÁÉ¥Ù…å}É•ÅÕ•ÍÑÌˆ¤½Èmt¤(€€€€€€€€€€€¥˜ÍÑÈ¡É½Ü¹•Ğ ‰¥ˆ¤½È€ˆˆ¤€ôôÉ•ÅÕ•ÍÑ}¥(€€€€€€€€¤°(€€€€€€€9½¹”°(€€€€¤(€€€¥˜ÁÉ¥Ù…å}É•ÅÕ•ÍĞ¥Ì9½¹”è(€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰ÁÉ¥Ù…å}É•ÅÕ•ÍÑ}¹½Ñ}™½Õ¹‰ô°€ĞÀĞ(€€€ÁÉ¥Ù…å}É•ÅÕ•ÍÑl‰ÍÑ…ÑÕÌ‰t€ôÍÑ…ÑÕÌ(€€€ÁÉ¥Ù…å}É•ÅÕ•ÍÑl‰ÕÁ‘…Ñ•‘}…Ğ‰t€ô‘…Ñ•Ñ¥µ”¹¹½Ü ¤¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤(€€€ÁÉ¥Ù…å}É•ÅÕ•ÍÑl‰É•Í½±Ù•‘}‰å}É½±”‰t€ôÍÑÈ¡…Ñ½É}É½±”½È€‰Õ¹­¹½İ¸ˆ¤(€€€¥˜¹½Ñ”è(€€€€€€€ÁÉ¥Ù…å}É•ÅÕ•ÍÑl‰É•Í½±ÕÑ¥½¹}¹½Ñ”‰t€ô¹½Ñ”(€€€Í…Ù•}ÍÑ…Ñ”¡‘…Ñ…}™¥±”°ÍÑ…Ñ”¤(€€€É•ÑÕÉ¸ì‰½¬ˆèQÉÕ”°€‰É•ÅÕ•ÍĞˆèÁÉ¥Ù…å}É•ÅÕ•ÍÑô°€ÈÀÀ(()‘•˜…‘µ¥¹}‰ÕÍ¥¹•ÍÍ}‘…Í¡‰½…É¡‘…Ñ…}™¥±”°½¹™¥œõ9½¹”°¹½Üõ9½¹”¤è(€€€€ˆˆ‰É•…Ñ”¹½¸µÍ•¹Í¥Ñ¥Ù”½µµ•É¥…°µ•ÑÉ¥Ì™½ÈÑ¡”ÁÉ½Ñ•Ñ•…‘µ¥¸U$¸ˆˆˆ(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€™œ€ô½¹™¥œ¥˜½¹™¥œ¥Ì¹½Ğ9½¹”…¹¡…Í…ÑÑÈ¡½¹™¥œ°€‰•Ğˆ¤•±Í”íô(€€€•¹•É…Ñ•‘}…Ğ€ô¹½Ü½ÈÕÉÉ•¹Ñ}…ÁÁ}Ñ¥µ”¡™œ¤(€€€ÕÍ•ÉÌ€ô±¥ÍĞ ¡ÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ¤½Èíô¤¹Ù…±Õ•Ì ¤¤(€€€¹½Ñ¥™¥…Ñ¥½¹}±½Ì€ô±¥ÍĞ¡ÍÑ…Ñ”¹•Ğ ‰¹½Ñ¥™¥…Ñ¥½¹}±½Ìˆ¤½Èmt¤(€€€Í•¹Ğ€ôÍÕ´ Ä™½È¥Ñ•´¥¸¹½Ñ¥™¥…Ñ¥½¹}±½Ì¥˜¥Ñ•´¹•Ğ ‰ÍÑ…ÑÕÌˆ¤€ôô€‰Í•¹Ğˆ¤(€€€™…¥±•€ôÍÕ´ Ä™½È¥Ñ•´¥¸¹½Ñ¥™¥…Ñ¥½¹}±½Ì¥˜¥Ñ•´¹•Ğ ‰ÍÑ…ÑÕÌˆ¤¥¸ì‰™…¥±•ˆ°€‰•ÉÉ½È‰ô¤(€€€‘•±¥Ù•Éå}Ñ½Ñ…°€ôÍ•¹Ğ€¬™…¥±•((€€€‘•˜½¹™¥ÕÉ•¡¹…µ”¤è(€€€€€€€É•ÑÕÉ¸‰½½°¡ÍÑÈ¡™œ¹•Ğ¡¹…µ”¤½È½Ì¹•¹Ù¥É½¸¹•Ğ¡¹…µ”°€ˆˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤¤((€€€„Ñ}µ•…ÍÕÉ•µ•¹Ñ}¥€ôÍÑÈ (€€€€€€€™œ¹•Ğ ‰Ñ}5MUI59Q}%ˆ¤(€€€€€€€½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰Ñ}5MUI59Q}%ˆ°€ˆˆ¤(€€€€€€€½È€‰´İ1PÄÑa1!4ˆ(€€€€¤¹ÍÑÉ¥À ¤(€€€„Ñ}ÁÉ½Á•ÉÑä€ô½¹™¥ÕÉ• ‰Ñ}AI=AIQe}%ˆ¤(€€€„Ñ}É•‘•¹Ñ¥…±Ì€ô½¹™¥ÕÉ• ‰Ñ}MIY%}=U9Q})M=8ˆ¤(€€€±¥¹•}Ñ½­•¸€ô½¹™¥ÕÉ• ‰1%9}!991}MM}Q=-8ˆ¤(€€€±¥¹•}Í•É•Ğ€ô½¹™¥ÕÉ• ‰1%9}!991}MIPˆ¤(€€€±¥™™}¥€ô½¹™¥ÕÉ• ‰1%}%ˆ¤(€€€ÁÕ‰±¥}ÕÉ°€ôÍÑÈ (€€€€€€€™œ¹•Ğ ‰AA}AU	1%}UI0ˆ¤(€€€€€€€½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰AA}AU	1%}UI0ˆ°€ˆˆ¤(€€€€€€€½È€‰¡ÑÑÁÌè¼½…±¥Ù”µ¡•­¥¸¹½¹É•¹‘•È¹½´ˆ(€€€€¤¹ÍÑÉ¥À ¤¹ÉÍÑÉ¥À ˆ¼ˆ¤(€€€İ½É‘ÁÉ•ÍÍ}Í¥Ñ”€ô½¹™¥ÕÉ• ‰]=IAIMM}M%Q}UI0ˆ¤(€€€İ½É‘ÁÉ•ÍÍ}ÕÍ•È€ô½¹™¥ÕÉ• ‰]=IAIMM}UMI95ˆ¤(€€€İ½É‘ÁÉ•ÍÍ}Á…ÍÍİ½É€ô½¹™¥ÕÉ• ‰]=IAIMM}AA1%Q%=9}AMM]=Iˆ¤((€€€±¥¹•}‰Õ‘•Ğ€ô±¥¹•}µ•ÍÍ…•}‰Õ‘•Ñ}ÍÑ…ÑÕÌ¡ÍÑ…Ñ”°™œ°•¹•É…Ñ•‘}…Ğ¤((€€€Á•¹‘¥¹}Í½Ì€ôl(€€€€€€€¥Ñ•´(€€€€€€€™½È¥Ñ•´¥¸€¡ÍÑ…Ñ”¹•Ğ ‰Í½Í}•Ù•¹ÑÌˆ¤½Èíô¤¹Ù…±Õ•Ì ¤(€€€€€€€¥˜ÍÑÈ¡¥Ñ•´¹•Ğ ‰ÍÑ…ÑÕÌˆ¤½È€‰Á•¹‘¥¹œˆ¤¹…Í•™½± ¤(€€€€€€€¹½Ğ¥¸M=M}1=M}MQQUML(€€€t(€€€­¹½İ¹}Í½Í}¥‘Ì€ôíÍÑÈ¡¥Ñ•´¹•Ğ ‰•Ù•¹Ñ}¥ˆ¤½È€ˆˆ¤™½È¥Ñ•´¥¸Á•¹‘¥¹}Í½Íô(€€€Á•¹‘¥¹}Í½Ì¹•áÑ•¹ (€€€€€€€¥Ñ•´(€€€€€€€™½È¥Ñ•´¥¸€¡ÍÑ…Ñ”¹•Ğ ‰Í½Í}Á•¹‘¥¹œˆ¤½Èíô¤¹Ù…±Õ•Ì ¤(€€€€€€€¥˜ÍÑÈ¡¥Ñ•´¹•Ğ ‰•Ù•¹Ñ}¥ˆ¤½È€ˆˆ¤¹½Ğ¥¸­¹½İ¹}Í½Í}¥‘Ì(€€€€€€€…¹ÍÑÈ¡¥Ñ•´¹•Ğ ‰ÍÑ…ÑÕÌˆ¤½È€‰Á•¹‘¥¹œˆ¤¹…Í•™½± ¤(€€€€€€€¹½Ğ¥¸M=M}1=M}MQQUML(€€€€¤(€€€‘•±¥Ù•Éå}™…¥±ÕÉ•Ì€ôl(€€€€€€€‘¥Ğ¡¥Ñ•´°¥¹¥‘•¹Ñ}¥õÍÑÈ¡¥Ñ•´¹•Ğ ‰¥¹¥‘•¹Ñ}¥ˆ¤½È˜‰‘•±¥Ù•Éäµí¥¹‘•áôˆ¤¤(€€€€€€€™½È¥¹‘•à°¥Ñ•´¥¸•¹Õµ•É…Ñ”¡¹½Ñ¥™¥…Ñ¥½¹}±½Ì¤(€€€€€€€¥˜¥Ñ•´¹•Ğ ‰ÍÑ…ÑÕÌˆ¤¥¸ì‰™…¥±•ˆ°€‰•ÉÉ½È‰ô(€€€t(€€€ÁÕ‰±¥}Á…•Ì€ô€ ‰¥¹‘•à¹¡Ñµ°ˆ°€‰ÁÉ¥¥¹œ¹¡Ñµ°ˆ°€‰¡•±À¹¡Ñµ°ˆ°€‰ÁÉ¥Ù…ä¹¡Ñµ°ˆ°€‰Ñ•ÉµÌ¹¡Ñµ°ˆ¤(€€€ÁÉ½©•Ñ}É½½Ğ€ôA…Ñ ¡}}™¥±•}|¤¹É•Í½±Ù” ¤¹Á…É•¹Ğ(€€€Í•½}Á…•Ì€ômt(€€€™½È™¥±•¹…µ”¥¸ÁÕ‰±¥}Á…•Ìè(€€€€€€€Á…Ñ €ôÁÉ½©•Ñ}É½½Ğ€¼™¥±•¹…µ”(€€€€€€€Í½ÕÉ”€ôÁ…Ñ ¹É•…‘}Ñ•áĞ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤¥˜Á…Ñ ¹•á¥ÍÑÌ ¤•±Í”€ˆˆ(€€€€€€€±½İ•É•€ôÍ½ÕÉ”¹±½İ•È ¤(€€€€€€€¡•­Ì€ôì(€€€€€€€€€€€€‰Ñ¥Ñ±”ˆè€ˆñÑ¥Ñ±”ˆ¥¸±½İ•É•°(€€€€€€€€€€€€‰‘•ÍÉ¥ÁÑ¥½¸ˆè€¹…µ”ô‰‘•ÍÉ¥ÁÑ¥½¸ˆœ¥¸±½İ•É•½È€‰¹…µ”ô‘•ÍÉ¥ÁÑ¥½¸œˆ¥¸±½İ•É•°(€€€€€€€€€€€€‰…¹½¹¥…°ˆè€É•°ô‰…¹½¹¥…°ˆœ¥¸±½İ•É•½È€‰É•°ô…¹½¹¥…°œˆ¥¸±½İ•É•°(€€€€€€€€€€€€‰É½‰½ÑÌˆè€¹…µ”ô‰É½‰½ÑÌˆœ¥¸±½İ•É•½È€‰¹…µ”ôÉ½‰½ÑÌœˆ¥¸±½İ•É•°(€€€€€€€€€€€€‰ÍÑÉÕÑÕÉ•‘}‘…Ñ„ˆè€‰…ÁÁ±¥…Ñ¥½¸½±­©Í½¸ˆ¥¸±½İ•É•°(€€€€€€€ô(€€€€€€€Í•½}Á…•Ì¹…ÁÁ•¹ (€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€‰Á…”ˆè™¥±•¹…µ”°(€€€€€€€€€€€€€€€€‰¡•­Ìˆè¡•­Ì°(€€€€€€€€€€€€€€€€‰Á…ÍÍ•ˆèÍÕ´ Ä™½ÈÙ…±Õ”¥¸¡•­Ì¹Ù…±Õ•Ì ¤¥˜Ù…±Õ”¤°(€€€€€€€€€€€€€€€€‰Ñ½Ñ…°ˆè±•¸¡¡•­Ì¤°(€€€€€€€€€€€ô(€€€€€€€€¤((€€€É•ÑÕÉ¸ì(€€€€€€€€‰•¹•É…Ñ•‘}…Ğˆè•¹•É…Ñ•‘}…Ğ¹¥Í½™½Éµ…Ğ ¤°(€€€€€€€€‰™Õ¹¹•°ˆèì(€€€€€€€€€€€€‰É•¥ÍÑ•É•‘}µ•µ‰•ÉÌˆè±•¸¡ÕÍ•ÉÌ¤°(€€€€€€€€€€€€‰µ•µ‰•ÉÍ}İ¥Ñ¡}Õ…É‘¥…¸ˆèÍÕ´ (€€€€€€€€€€€€€€€€Ä(€€€€€€€€€€€€€€€™½ÈÕÍ•È¥¸ÕÍ•ÉÌ(€€€€€€€€€€€€€€€¥˜…¹ä¡•Ñ}½¹Ñ…Ñ}±¥¹•}¥¡½¹Ñ…Ğ¤™½È½¹Ñ…Ğ¥¸€¡ÕÍ•È¹•Ğ ‰½¹Ñ…ÑÌˆ¤½Èmt¤¤(€€€€€€€€€€€€¤°(€€€€€€€€€€€€‰…Ñ¥Ù•}Á…¥‘}µ•µ‰•ÉÌˆèÍÕ´ (€€€€€€€€€€€€€€€€Ä(€€€€€€€€€€€€€€€™½ÈÕÍ•È¥¸ÕÍ•ÉÌ(€€€€€€€€€€€€€€€¥˜ÍÑÈ¡ÕÍ•È¹•Ğ ‰Á±…¸ˆ¤½È€ˆˆ¤¹ÍÑ…ÉÑÍİ¥Ñ  ‰Á…¥‘|ˆ¤(€€€€€€€€€€€€€€€…¹ÕÍ•È¹•Ğ ‰Á…åµ•¹Ñ}ÍÑ…ÑÕÌˆ¤€ôô€‰…Ñ¥Ù”ˆ(€€€€€€€€€€€€¤°(€€€€€€€ô°(€€€€€€€€‰‘•±¥Ù•Éäˆèì(€€€€€€€€€€€€‰Í•¹ĞˆèÍ•¹Ğ°(€€€€€€€€€€€€‰™…¥±•ˆè™…¥±•°(€€€€€€€€€€€€‰Ñ½Ñ…°ˆè‘•±¥Ù•Éå}Ñ½Ñ…°°(€€€€€€€€€€€€‰ÍÕ•ÍÍ}É…Ñ”ˆèÉ½Õ¹ ¡Í•¹Ğ€¼‘•±¥Ù•Éå}Ñ½Ñ…°€¨€ÄÀÀ¤°€Ä¤¥˜‘•±¥Ù•Éå}Ñ½Ñ…°•±Í”9½¹”°(€€€€€€€ô°(€€€€€€€€‰¥¹¥‘•¹ÑÌˆèì(€€€€€€€€€€€€‰½Á•¹}Í½Ìˆè±•¸¡Á•¹‘¥¹}Í½Ì¤°(€€€€€€€€€€€€‰‘•±¥Ù•Éå}™…¥±ÕÉ•Ìˆè±•¸¡‘•±¥Ù•Éå}™…¥±ÕÉ•Ì¤°(€€€€€€€€€€€€‰Ñ½Ñ…±}½Á•¸ˆè±•¸¡Á•¹‘¥¹}Í½Ì¤€¬±•¸¡‘•±¥Ù•Éå}™…¥±ÕÉ•Ì¤°(€€€€€€€€€€€€‰¥Ñ•µÌˆèl(€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€‰­¥¹ˆè€‰Í½Ìˆ°(€€€€€€€€€€€€€€€€€€€€‰¥¹¥‘•¹Ñ}¥ˆèÍÑÈ¡¥Ñ•´¹•Ğ ‰•Ù•¹Ñ}¥ˆ¤½È€ˆˆ¤°(€€€€€€€€€€€€€€€€€€€€‰É•…Ñ•‘}…Ğˆè¥Ñ•´¹•Ğ ‰É•…Ñ•‘}…Ğˆ¤°(€€€€€€€€€€€€€€€€€€€€‰½İ¹•É}‘¥ÍÁ±…å}¹…µ”ˆè¥Ñ•´¹•Ğ ‰½İ¹•É}‘¥ÍÁ±…å}¹…µ”ˆ¤½È€‹šr–N„ˆ°(€€€€€€€€€€€€€€€€€€€€‰ÍÑ…ÑÕÌˆè¥Ñ•´¹•Ğ ‰ÍÑ…ÑÕÌˆ¤½È€‰Á•¹‘¥¹œˆ°(€€€€€€€€€€€€€€€€€€€€‰ÁÉ¥µ…Éå}É•ÍÁ½¹‘•Èˆè}Í½Í}ÁÕ‰±¥}Í¹…ÁÍ¡½Ğ¡¥Ñ•´¤¹•Ğ ‰ÁÉ¥µ…Éå}É•ÍÁ½¹‘•Èˆ¤°(€€€€€€€€€€€€€€€€€€€€‰…ÍÍ¥ÍÑ…¹ÑÌˆè}Í½Í}ÁÕ‰±¥}Í¹…ÁÍ¡½Ğ¡¥Ñ•´¤¹•Ğ ‰…ÍÍ¥ÍÑ…¹ÑÌˆ¤°(€€€€€€€€€€€€€€€€€€€€‰•Í…±…Ñ¥½¹}É½Õ¹ˆè¥¹Ğ¡¥Ñ•´¹•Ğ ‰•Í…±…Ñ¥½¹}É½Õ¹ˆ¤½È€À¤°(€€€€€€€€€€€€€€€€€€€€‰Í•¹Ñ}½Õ¹ĞˆèÍÕ´ (€€€€€€€€€€€€€€€€€€€€€€€€Ä™½ÈÉ½Ü¥¸€¡¥Ñ•´¹•Ğ ‰‘•±¥Ù•É¥•Ìˆ¤½Èmt¤(€€€€€€€€€€€€€€€€€€€€€€€¥˜É½Ü¹•Ğ ‰ÍÑ…ÑÕÌˆ¤€ôô€‰Í•¹Ğˆ(€€€€€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€€€€€‰™…¥±•‘}½Õ¹ĞˆèÍÕ´ (€€€€€€€€€€€€€€€€€€€€€€€€Ä™½ÈÉ½Ü¥¸€¡¥Ñ•´¹•Ğ ‰‘•±¥Ù•É¥•Ìˆ¤½Èmt¤(€€€€€€€€€€€€€€€€€€€€€€€¥˜É½Ü¹•Ğ ‰ÍÑ…ÑÕÌˆ¤€ôô€‰™…¥±•ˆ(€€€€€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€€€€€‰Ñ¥µ•±¥¹”ˆè}Í½Í}ÁÕ‰±¥}Í¹…ÁÍ¡½Ğ¡¥Ñ•´¤¹•Ğ ‰Ñ¥µ•±¥¹”ˆ¤°(€€€€€€€€€€€€€€€ô(€€€€€€€€€€€€€€€™½È¥Ñ•´¥¸Á•¹‘¥¹}Í½Ì(€€€€€€€€€€€€€€€¥˜¥Ñ•´¹•Ğ ‰•Ù•¹Ñ}¥ˆ¤(€€€€€€€€€€€t€¬l(€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€‰­¥¹ˆè€‰‘•±¥Ù•Éäˆ°(€€€€€€€€€€€€€€€€€€€€‰¥¹¥‘•¹Ñ}¥ˆè¥Ñ•µl‰¥¹¥‘•¹Ñ}¥‰t°(€€€€€€€€€€€€€€€€€€€€‰É•…Ñ•‘}…Ğˆè¥Ñ•´¹•Ğ ‰É•…Ñ•‘}…Ğˆ¤°(€€€€€€€€€€€€€€€€€€€€‰¹½Ñ¥™¥…Ñ¥½¹}­¥¹ˆè¥Ñ•´¹•Ğ ‰­¥¹ˆ¤°(€€€€€€€€€€€€€€€ô(€€€€€€€€€€€€€€€™½È¥Ñ•´¥¸‘•±¥Ù•Éå}™…¥±ÕÉ•Ì(€€€€€€€€€€€t°(€€€€€€€ô°(€€€€€€€€‰±¥¹•}‰Õ‘•Ğˆè±¥¹•}‰Õ‘•Ğ°(€€€€€€€€‰¥¹Ñ•É…Ñ¥½¹Ìˆèì(€€€€€€€€€€€€‰±¥¹”ˆèì(€€€€€€€€€€€€€€€€‰½¹™¥ÕÉ•ˆè±¥¹•}Ñ½­•¸°(€€€€€€€€€€€€€€€€‰µ•ÍÍ…¥¹}É•…‘äˆè±¥¹•}Ñ½­•¸…¹±¥¹•}Í•É•Ğ°(€€€€€€€€€€€€€€€€‰Ñ½­•¹}½¹™¥ÕÉ•ˆè±¥¹•}Ñ½­•¸°(€€€€€€€€€€€€€€€€‰Í•É•Ñ}½¹™¥ÕÉ•ˆè±¥¹•}Í•É•Ğ°(€€€€€€€€€€€€€€€€‰±¥™™}½¹™¥ÕÉ•ˆè±¥™™}¥°(€€€€€€€€€€€€€€€€‰İ•‰¡½½­}½¹™¥ÕÉ•ˆè‰½½°¡ÁÕ‰±¥}ÕÉ°…¹±¥¹•}Í•É•Ğ¤°(€€€€€€€€€€€€€€€€‰İ•‰¡½½­}ÕÉ°ˆè˜‰íÁÕ‰±¥}ÕÉ±ô½…Á¤½±¥¹”½İ•‰¡½½¬ˆ¥˜ÁÕ‰±¥}ÕÉ°•±Í”€ˆˆ°(€€€€€€€€€€€ô°(€€€€€€€€€€€€‰„Ğˆèì(€€€€€€€€€€€€€€€€Œ-••ÀÑ¡”±•…ä­•ä…ÌÉ•Á½ÉĞµ…•ÍÌÍÑ…ÑÕÌ™½È•á¥ÍÑ¥¹œ±¥•¹ÑÌ¸(€€€€€€€€€€€€€€€€‰½¹™¥ÕÉ•ˆè„Ñ}ÁÉ½Á•ÉÑä…¹„Ñ}É•‘•¹Ñ¥…±Ì°(€€€€€€€€€€€€€€€€‰ÑÉ…­¥¹}½¹™¥ÕÉ•ˆè‰½½°¡É”¹™Õ±±µ…Ñ ¡È‰µmµhÀ´åt¬ˆ°„Ñ}µ•…ÍÕÉ•µ•¹Ñ}¥¤¤°(€€€€€€€€€€€€€€€€‰É•Á½ÉÑ¥¹}½¹™¥ÕÉ•ˆè„Ñ}ÁÉ½Á•ÉÑä…¹„Ñ}É•‘•¹Ñ¥…±Ì°(€€€€€€€€€€€€€€€€‰µ•…ÍÕÉ•µ•¹Ñ}¥ˆè„Ñ}µ•…ÍÕÉ•µ•¹Ñ}¥°(€€€€€€€€€€€€€€€€‰ÁÉ½Á•ÉÑå}½¹™¥ÕÉ•ˆè„Ñ}ÁÉ½Á•ÉÑä°(€€€€€€€€€€€€€€€€‰É•‘•¹Ñ¥…±Í}½¹™¥ÕÉ•ˆè„Ñ}É•‘•¹Ñ¥…±Ì°(€€€€€€€€€€€ô°(€€€€€€€€€€€€‰İ½É‘ÁÉ•ÍÌˆèì(€€€€€€€€€€€€€€€€‰½¹™¥ÕÉ•ˆèİ½É‘ÁÉ•ÍÍ}Í¥Ñ”…¹İ½É‘ÁÉ•ÍÍ}ÕÍ•È…¹İ½É‘ÁÉ•ÍÍ}Á…ÍÍİ½É°(€€€€€€€€€€€€€€€€‰Í¥Ñ•}½¹™¥ÕÉ•ˆèİ½É‘ÁÉ•ÍÍ}Í¥Ñ”°(€€€€€€€€€€€€€€€€‰ÕÍ•É¹…µ•}½¹™¥ÕÉ•ˆèİ½É‘ÁÉ•ÍÍ}ÕÍ•È°(€€€€€€€€€€€€€€€€‰…ÁÁ±¥…Ñ¥½¹}Á…ÍÍİ½É‘}½¹™¥ÕÉ•ˆèİ½É‘ÁÉ•ÍÍ}Á…ÍÍİ½É°(€€€€€€€€€€€ô°(€€€€€€€ô°(€€€€€€€€‰Í•¼ˆèì(€€€€€€€€€€€€‰Á…•ÌˆèÍ•½}Á…•Ì°(€€€€€€€€€€€€‰Á…ÍÍ•ˆèÍÕ´¡É½İl‰Á…ÍÍ•‰t™½ÈÉ½Ü¥¸Í•½}Á…•Ì¤°(€€€€€€€€€€€€‰Ñ½Ñ…°ˆèÍÕ´¡É½İl‰Ñ½Ñ…°‰t™½ÈÉ½Ü¥¸Í•½}Á…•Ì¤°(€€€€€€€ô°(€€€ô(()‘•˜…‘µ¥¹}ÍÕµµ…Éä¡‘…Ñ…}™¥±”°½¹™¥œõ9½¹”°¹½Üõ9½¹”¤è(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€ÍÑ…ÑÕÍ}¹½Ü€ô¹½Ü½ÈÕÉÉ•¹Ñ}…ÁÁ}Ñ¥µ”¡½¹™¥œ½Èíô¤(€€€Ñ½­•¸€ô€ˆˆ(€€€¥˜½¹™¥œ¥Ì¹½Ğ9½¹”…¹¡…Í…ÑÑÈ¡½¹™¥œ°€‰•Ğˆ¤è(€€€€€€€Ñ½­•¸€ôÍÑÈ¡½¹™¥œ¹•Ğ ‰1%9}!991}MM}Q=-8ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€¥˜¹½ĞÑ½­•¸è(€€€€€€€Ñ½­•¸€ôÍÑÈ¡½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}!991}MM}Q=-8ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤((€€€€Œƒ–ú3–>Ã¢ò'–—šf¢s¦ö+11%9ƒ’öÿR£¢7’öS’ö7–B7¢Ç¾ò#šr–’kš&L€ĞÀƒš²„1%9ÁÉ½™¥±—¾ò3¦ÿ–7¦ûšf¾ò$(€€€¡å‘É…Ñ•€ô€À(€€€‘¥ÉÑä€ô…±Í”(€€€™½ÈÕÍ•È¥¸€¡ÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ¤½Èíô¤¹Ù…±Õ•Ì ¤è(€€€€€€€¥˜¡å‘É…Ñ•€øô€ĞÀè(€€€€€€€€€€€‰É•…¬(€€€€€€€¥˜¹½Ğ¥Í}Á±…•¡½±‘•É}‘¥ÍÁ±…å}¹…µ”¡ÕÍ•È¹•Ğ ‰‘¥ÍÁ±…å}¹…µ”ˆ¤¤è(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€‰•™½É”€ôÍÑÈ¡ÕÍ•È¹•Ğ ‰‘¥ÍÁ±…å}¹…µ”ˆ¤½È€ˆˆ¤(€€€€€€€•¹ÍÕÉ•}ÕÍ•É}‘¥ÍÁ±…å}¹…µ”¡ÕÍ•È°Ñ½­•¸õÑ½­•¸¤(€€€€€€€¥˜ÍÑÈ¡ÕÍ•È¹•Ğ ‰‘¥ÍÁ±…å}¹…µ”ˆ¤½È€ˆˆ¤€„ô‰•™½É”è(€€€€€€€€€€€¡å‘É…Ñ•€¬ô€Ä(€€€€€€€€€€€‘¥ÉÑä€ôQÉÕ”(€€€¥˜‘¥ÉÑäè(€€€€€€€Í…Ù•}ÍÑ…Ñ”¡‘…Ñ…}™¥±”°ÍÑ…Ñ”¤((€€€ÕÍ•ÉÌ€ômt(€€€¥¹Ù¥Ñ•}•‘•Ì€ômt(€€€™½ÈÕÍ•È¥¸ÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ°íô¤¹Ù…±Õ•Ì ¤è(€€€€€€€ÍÑ…ÑÕÌ€ô‰Õ¥±‘}ÍÑ…ÑÕÌ¡ÕÍ•È°ÍÑ…Ñ”°¹½ÜõÍÑ…ÑÕÍ}¹½Ü¤(€€€€€€€±…Ñ•ÍÑ}¡•­¥¸€ô€¡ÍÑ…ÑÕÌ¹•Ğ ‰¡•­¥¹}É•½É‘Ìˆ¤½Èmt¥l´Äét½Èmíõt(€€€€€€€ÍÑ…ÑÕÍl‰±…ÍÑ}¡•­¥¹}…É•„‰t€ôÍÑÈ (€€€€€€€€€€€±…Ñ•ÍÑ}¡•­¥¹lÁt¹•Ğ ‰…É•„ˆ¤(€€€€€€€€€€€½È€¡ÕÍ•È¹•Ğ ‰±½…Ñ¥½¸ˆ¤½Èíô¤¹•Ğ ‰¥Ñäˆ¤(€€€€€€€€€€€½È€‹šr«š>C’úlˆ(€€€€€€€€¤¹ÍÑÉ¥À ¤(€€€€€€€€Œƒ–ú3–>Ã¦†¿’ë–B7¢Ç¾òkÖW’â7¦ëf÷¾òo’î7šb¿’öS’ö7šf¢Ï–ÂG¦f~´%ƒšZç’úÿ¢ú£¢¶`(€€€€€€€¹…µ”€ôÍÑÈ¡ÍÑ…ÑÕÌ¹•Ğ ‰‘¥ÍÁ±…å}¹…µ”ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€¥˜¥Í}Á±…•¡½±‘•É}‘¥ÍÁ±…å}¹…µ”¡¹…µ”¤è(€€€€€€€€€€€Í¡½ÉĞ€ôÍÑÈ¡ÍÑ…ÑÕÌ¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¥l´Øét½È€ˆüˆ(€€€€€€€€€€€ÍÑ…ÑÕÍl‰‘¥ÍÁ±…å}¹…µ”‰t€ô˜‹šr«–>[–ú_šjÇ¢Ç¾ò#Š™íÍ¡½ÉÑ÷¾ò$ˆ(€€€€€€€€€€€ÍÑ…ÑÕÍl‰‘¥ÍÁ±…å}¹…µ•}µ¥ÍÍ¥¹œ‰t€ôQÉÕ”(€€€€€€€•±Í”è(€€€€€€€€€€€ÍÑ…ÑÕÍl‰‘¥ÍÁ±…å}¹…µ•}µ¥ÍÍ¥¹œ‰t€ô…±Í”(€€€€€€€ÕÍ•ÉÌ¹…ÁÁ•¹¡ÍÑ…ÑÕÌ¤(€€€€€€€¥¹Ù¥Ñ•É}¥€ôÍÑ…ÑÕÌ¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ(€€€€€€€¥¹Ù¥Ñ•É}¹…µ”€ôÍÑ…ÑÕÌ¹•Ğ ‰‘¥ÍÁ±…å}¹…µ”ˆ¤½È€ˆˆ(€€€€€€€™½È½¹Ñ…Ğ¥¸ÍÑ…ÑÕÌ¹•Ğ ‰½¹Ñ…ÑÌˆ¤½Èmtè(€€€€€€€€€€€Õ…É‘¥…¹}¥€ô•Ñ}½¹Ñ…Ñ}±¥¹•}¥¡½¹Ñ…Ğ¤(€€€€€€€€€€€¥˜¹½ĞÕ…É‘¥…¹}¥è(€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€¥˜Õ…É‘¥…¹}¥€ôô¥¹Ù¥Ñ•É}¥è(€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€¥¹Ù¥Ñ•}•‘•Ì¹…ÁÁ•¹ (€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€‰¥¹Ù¥Ñ•É}±¥¹•}ÕÍ•É}¥ˆè¥¹Ù¥Ñ•É}¥°(€€€€€€€€€€€€€€€€€€€€‰¥¹Ù¥Ñ•É}‘¥ÍÁ±…å}¹…µ”ˆè¥¹Ù¥Ñ•É}¹…µ”°(€€€€€€€€€€€€€€€€€€€€‰Õ…É‘¥…¹}±¥¹•}ÕÍ•É}¥ˆèÕ…É‘¥…¹}¥°(€€€€€€€€€€€€€€€€€€€€‰Õ…É‘¥…¹}‘¥ÍÁ±…å}¹…µ”ˆè½¹Ñ…Ğ¹•Ğ ‰¹…µ”ˆ¤½È€ˆˆ°(€€€€€€€€€€€€€€€€€€€€‰‰¥¹‘¥¹}ÍÑ…ÑÕÌˆè½¹Ñ…Ğ¹•Ğ ‰‰¥¹‘¥¹}ÍÑ…ÑÕÌˆ¤½È€ˆˆ°(€€€€€€€€€€€€€€€€€€€€‰…•ÁÑ•‘}…Ğˆè½¹Ñ…Ğ¹•Ğ ‰…•ÁÑ•‘}…Ğˆ¤½È½¹Ñ…Ğ¹•Ğ ‰ÕÁ‘…Ñ•‘}…Ğˆ¤½È€ˆˆ°(€€€€€€€€€€€€€€€ô(€€€€€€€€€€€€¤(€€€ÕÍ•ÉÌ¹Í½ÉĞ¡­•äõ±…µ‰‘„¥Ñ•´è€¡¹½Ğ¥Ñ•µl‰¥Í}½Ù•É‘Õ”‰t°¥Ñ•´¹•Ğ ‰‘¥ÍÁ±…å}¹…µ”ˆ¤½È€ˆˆ¤¤(€€€ÕÍ•ÉÍ}‰å}¥€ôì(€€€€€€€ÍÑÈ¡ÕÍ•È¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¤èÕÍ•È(€€€€€€€™½ÈÕÍ•È¥¸ÕÍ•ÉÌ(€€€€€€€¥˜ÕÍ•È¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤(€€€ô(€€€‘…¥±å}ÁÕÍ¡}É½İÌ€ôíô(€€€Á•ÉÍ¥ÍÑ•‘}‘…¥±å}ÁÕÍ¡•Ì€ôÍÑ…Ñ”¹•Ğ ‰‘…¥±å}ÁÕÍ¡}µ•µ‰•É}ÍÑ…ÑÌˆ¤½Èíô(€€€¥˜¥Í¥¹ÍÑ…¹”¡Á•ÉÍ¥ÍÑ•‘}‘…¥±å}ÁÕÍ¡•Ì°‘¥Ğ¤è(€€€€€€€™½È­•ä°¥Ñ•´¥¸Á•ÉÍ¥ÍÑ•‘}‘…¥±å}ÁÕÍ¡•Ì¹¥Ñ•µÌ ¤è(€€€€€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡¥Ñ•´°‘¥Ğ¤è(€€€€€€€€€€€€€€€‘…¥±å}ÁÕÍ¡}É½İÍmÍÑÈ¡­•ä¥t€ô‘¥Ğ¡¥Ñ•´¤(€€€€Œ	…­™¥±°É••¹Ğ±•…ä±½ÌÑ¡…ĞÁÉ•‘…Ñ”Ñ¡”Á•ÉÍ¥ÍÑ•¹Ğ‘…¥±ä½Õ¹Ñ•ÉÌ¸(€€€™½È±½œ¥¸ÍÑ…Ñ”¹•Ğ ‰¹½Ñ¥™¥…Ñ¥½¹}±½Ìˆ¤½Èmtè(€€€€€€€±¥¹•}ÕÍ•É}¥€ôÍÑÈ¡±½œ¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€É•…Ñ•‘}…Ğ€ôÍÑÈ¡±½œ¹•Ğ ‰É•…Ñ•‘}…Ğˆ¤½È€ˆˆ¤(€€€€€€€‘…Ñ”€ôÉ•…Ñ•‘}…ÑlèÄÁt(€€€€€€€¥˜¹½Ğ±¥¹•}ÕÍ•É}¥½È±•¸¡‘…Ñ”¤€„ô€ÄÀè(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€­•ä€ô˜‰í‘…Ñ•õñí±¥¹•}ÕÍ•É}¥‘ôˆ(€€€€€€€¥˜­•ä¥¸‘…¥±å}ÁÕÍ¡}É½İÌè(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€µ…Ñ¡¥¹œ€ôl(€€€€€€€€€€€É½Ü(€€€€€€€€€€€™½ÈÉ½Ü¥¸€¡ÍÑ…Ñ”¹•Ğ ‰¹½Ñ¥™¥…Ñ¥½¹}±½Ìˆ¤½Èmt¤(€€€€€€€€€€€¥˜ÍÑÈ¡É½Ü¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤€ôô±¥¹•}ÕÍ•É}¥(€€€€€€€€€€€…¹ÍÑÈ¡É½Ü¹•Ğ ‰É•…Ñ•‘}…Ğˆ¤½È€ˆˆ¥lèÄÁt€ôô‘…Ñ”(€€€€€€€t(€€€€€€€‘…¥±å}ÁÕÍ¡}É½İÍm­•åt€ôì(€€€€€€€€€€€€‰‘…Ñ”ˆè‘…Ñ”°(€€€€€€€€€€€€‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€‰Í•¹Ñ}½Õ¹ĞˆèÍÕ´ Ä™½ÈÉ½Ü¥¸µ…Ñ¡¥¹œ¥˜É½Ü¹•Ğ ‰ÍÑ…ÑÕÌˆ¤€ôô€‰Í•¹Ğˆ¤°(€€€€€€€€€€€€‰™…¥±•‘}½Õ¹ĞˆèÍÕ´ (€€€€€€€€€€€€€€€€Ä™½ÈÉ½Ü¥¸µ…Ñ¡¥¹œ¥˜É½Ü¹•Ğ ‰ÍÑ…ÑÕÌˆ¤¥¸ì‰™…¥±•ˆ°€‰•ÉÉ½Èˆ°€‰‰±½­•‰ô(€€€€€€€€€€€€¤°(€€€€€€€€€€€€‰Ñ½Ñ…±}½Õ¹Ğˆè±•¸¡µ…Ñ¡¥¹œ¤°(€€€€€€€€€€€€‰­¥¹‘ÌˆèÍ½ÉÑ•¡ì(€€€€€€€€€€€€€€€ÍÑÈ¡É½Ü¹•Ğ ‰­¥¹ˆ¤½È€‰½Ñ¡•Èˆ¤™½ÈÉ½Ü¥¸µ…Ñ¡¥¹œ(€€€€€€€€€€€ô¤°(€€€€€€€€€€€€‰±…ÍÑ}ÁÕÍ¡}…Ğˆèµ…à (€€€€€€€€€€€€€€€€¡ÍÑÈ¡É½Ü¹•Ğ ‰É•…Ñ•‘}…Ğˆ¤½È€ˆˆ¤™½ÈÉ½Ü¥¸µ…Ñ¡¥¹œ¤°(€€€€€€€€€€€€€€€‘•™…Õ±Ğôˆˆ°(€€€€€€€€€€€€¤°(€€€€€€€€€€€€‰±…Ñ•ÍÑ}™…¥±ÕÉ•}‘•Ñ…¥°ˆè¹•áĞ (€€€€€€€€€€€€€€€€ (€€€€€€€€€€€€€€€€€€€ÍÑÈ¡É½Ü¹•Ğ ‰‘•Ñ…¥°ˆ¤½È€ˆˆ¥lèÔÀÁt(€€€€€€€€€€€€€€€€€€€™½ÈÉ½Ü¥¸Í½ÉÑ• (€€€€€€€€€€€€€€€€€€€€€€€µ…Ñ¡¥¹œ°(€€€€€€€€€€€€€€€€€€€€€€€­•äõ±…µ‰‘„É½ÜèÍÑÈ¡É½Ü¹•Ğ ‰É•…Ñ•‘}…Ğˆ¤½È€ˆˆ¤°(€€€€€€€€€€€€€€€€€€€€€€€É•Ù•ÉÍ”õQÉÕ”°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€¥˜É½Ü¹•Ğ ‰ÍÑ…ÑÕÌˆ¤¥¸ì‰™…¥±•ˆ°€‰•ÉÉ½Èˆ°€‰‰±½­•‰ô(€€€€€€€€€€€€€€€€€€€…¹ÍÑÈ¡É½Ü¹•Ğ ‰‘•Ñ…¥°ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€ˆˆ°(€€€€€€€€€€€€¤°(€€€€€€€€€€€€‰±…Ñ•ÍÑ}™…¥±ÕÉ•}…Ğˆè¹•áĞ (€€€€€€€€€€€€€€€€ (€€€€€€€€€€€€€€€€€€€ÍÑÈ¡É½Ü¹•Ğ ‰É•…Ñ•‘}…Ğˆ¤½È€ˆˆ¤(€€€€€€€€€€€€€€€€€€€™½ÈÉ½Ü¥¸Í½ÉÑ• (€€€€€€€€€€€€€€€€€€€€€€€µ…Ñ¡¥¹œ°(€€€€€€€€€€€€€€€€€€€€€€€­•äõ±…µ‰‘„É½ÜèÍÑÈ¡É½Ü¹•Ğ ‰É•…Ñ•‘}…Ğˆ¤½È€ˆˆ¤°(€€€€€€€€€€€€€€€€€€€€€€€É•Ù•ÉÍ”õQÉÕ”°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€¥˜É½Ü¹•Ğ ‰ÍÑ…ÑÕÌˆ¤¥¸ì‰™…¥±•ˆ°€‰•ÉÉ½Èˆ°€‰‰±½­•‰ô(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€ˆˆ°(€€€€€€€€€€€€¤°(€€€€€€€ô(€€€‘…¥±å}ÁÕÍ¡}µ•µ‰•É}ÍÑ…ÑÌ€ômt(€€€™½È¥Ñ•´¥¸‘…¥±å}ÁÕÍ¡}É½İÌ¹Ù…±Õ•Ì ¤è(€€€€€€€µ•µ‰•È€ôÕÍ•ÉÍ}‰å}¥¹•Ğ¡ÍÑÈ¡¥Ñ•´¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¤°íô¤(€€€€€€€¥˜¹½ĞÍÑÈ¡¥Ñ•´¹•Ğ ‰±…Ñ•ÍÑ}™…¥±ÕÉ•}‘•Ñ…¥°ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤è(€€€€€€€€€€€µ…Ñ¡¥¹}™…¥±ÕÉ•Ì€ôl(€€€€€€€€€€€€€€€É½Ü(€€€€€€€€€€€€€€€™½ÈÉ½Ü¥¸€¡ÍÑ…Ñ”¹•Ğ ‰¹½Ñ¥™¥…Ñ¥½¹}±½Ìˆ¤½Èmt¤(€€€€€€€€€€€€€€€¥˜ÍÑÈ¡É½Ü¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€€€€€€€€€€ôôÍÑÈ¡¥Ñ•´¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€€€€€€€€€…¹ÍÑÈ¡É½Ü¹•Ğ ‰É•…Ñ•‘}…Ğˆ¤½È€ˆˆ¥lèÄÁt(€€€€€€€€€€€€€€€€ôôÍÑÈ¡¥Ñ•´¹•Ğ ‰‘…Ñ”ˆ¤½È€ˆˆ¤(€€€€€€€€€€€€€€€…¹É½Ü¹•Ğ ‰ÍÑ…ÑÕÌˆ¤¥¸ì‰™…¥±•ˆ°€‰•ÉÉ½Èˆ°€‰‰±½­•‰ô(€€€€€€€€€€€t(€€€€€€€€€€€¥˜µ…Ñ¡¥¹}™…¥±ÕÉ•Ìè(€€€€€€€€€€€€€€€±…Ñ•ÍÑ}™…¥±ÕÉ”€ôµ…à (€€€€€€€€€€€€€€€€€€€µ…Ñ¡¥¹}™…¥±ÕÉ•Ì°(€€€€€€€€€€€€€€€€€€€­•äõ±…µ‰‘„É½ÜèÍÑÈ¡É½Ü¹•Ğ ‰É•…Ñ•‘}…Ğˆ¤½È€ˆˆ¤°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€¥Ñ•µl‰±…Ñ•ÍÑ}™…¥±ÕÉ•}‘•Ñ…¥°‰t€ôÍÑÈ (€€€€€€€€€€€€€€€€€€€±…Ñ•ÍÑ}™…¥±ÕÉ”¹•Ğ ‰‘•Ñ…¥°ˆ¤½È€ˆˆ(€€€€€€€€€€€€€€€€¥lèÔÀÁt(€€€€€€€€€€€€€€€¥Ñ•µl‰±…Ñ•ÍÑ}™…¥±ÕÉ•}…Ğ‰t€ôÍÑÈ (€€€€€€€€€€€€€€€€€€€±…Ñ•ÍÑ}™…¥±ÕÉ”¹•Ğ ‰É•…Ñ•‘}…Ğˆ¤½È€ˆˆ(€€€€€€€€€€€€€€€€¤(€€€€€€€‘…¥±å}ÁÕÍ¡}µ•µ‰•É}ÍÑ…ÑÌ¹…ÁÁ•¹¡ì(€€€€€€€€€€€€¨©¥Ñ•´°(€€€€€€€€€€€€‰‘¥ÍÁ±…å}¹…µ”ˆèµ•µ‰•È¹•Ğ ‰‘¥ÍÁ±…å}¹…µ”ˆ¤½È€‹šr«–>[–ú_šjÇ¢Äˆ°(€€€€€€€€€€€€‰Á±…¸ˆèµ•µ‰•È¹•Ğ ‰Á±…¸ˆ¤½È€‰™É•”ˆ°(€€€€€€€€€€€€‰•áÁ¥É•Í}…Ğˆèµ•µ‰•È¹•Ğ ‰Á±…¹}•áÁ¥É•Í}…Ğˆ¤½È€ˆˆ°(€€€€€€€ô¤(€€€‘…¥±å}ÁÕÍ¡}µ•µ‰•É}ÍÑ…ÑÌ¹Í½ÉĞ (€€€€€€€­•äõ±…µ‰‘„¥Ñ•´è€¡¥Ñ•´¹•Ğ ‰‘…Ñ”ˆ¤½È€ˆˆ°¥Ñ•´¹•Ğ ‰±…ÍÑ}ÁÕÍ¡}…Ğˆ¤½È€ˆˆ¤°(€€€€€€€É•Ù•ÉÍ”õQÉÕ”°(€€€€¤(€€€Õ…É‘¥…¹}É½ÕÁÌ€ô±¥ÍĞ¡ÍÑ…Ñ”¹•Ğ ‰Õ…É‘¥…¹}É½ÕÁÌˆ°íô¤¹Ù…±Õ•Ì ¤¤(€€€Õ…É‘¥…¹}É½ÕÁÌ¹Í½ÉĞ¡­•äõ±…µ‰‘„¥Ñ•´è¥Ñ•´¹•Ğ ‰É•…Ñ•‘}…Ğˆ°€ˆˆ¤°É•Ù•ÉÍ”õQÉÕ”¤(€€€½É‘•ÉÌ€ô±¥ÍĞ¡É•Ù•ÉÍ•¡ÍÑ…Ñ”¹•Ğ ‰½É‘•ÉÌˆ°mt¥l´ÄÀÀét¤¤(€€€Á…¥‘}½É‘•ÉÌ€ôm½É‘•È™½È½É‘•È¥¸½É‘•ÉÌ¥˜½É‘•È¹•Ğ ‰ÍÑ…ÑÕÌˆ¤€ôô€‰Á…¥‰t(€€€½Õ¹Ñå}É½İÌ€ôíô((€€€‘•˜½Õ¹Ñå}É½Ü¡½Õ¹Ñä¤è(€€€€€€€É•ÑÕÉ¸½Õ¹Ñå}É½İÌ¹Í•Ñ‘•™…Õ±Ğ (€€€€€€€€€€€½Õ¹Ñä½È€‹šr«š>C’úlˆ°(€€€€€€€€€€€ì‰½Õ¹Ñäˆè½Õ¹Ñä½È€‹šr«š>C’úlˆ°€‰µ•µ‰•ÉÌˆè€À°€‰½É‘•ÉÌˆè€À°€‰Á…¥‘}½É‘•ÉÌˆè€À°€‰É•Ù•¹Õ”ˆè€Áô°(€€€€€€€€¤((€€€™½ÈÁÉ½™¥±”¥¸ÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ°íô¤¹Ù…±Õ•Ì ¤è(€€€€€€€±…Ñ•ÍĞ€ôl(€€€€€€€€€€€É½Ü™½ÈÉ½Ü¥¸€¡ÁÉ½™¥±”¹•Ğ ‰¡•­¥¹}É•½É‘Ìˆ¤½Èmt¤(€€€€€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡É½Ü°‘¥Ğ¤(€€€€€€€t(€€€€€€€½Õ¹Ñä€ôÍÑÈ (€€€€€€€€€€€€¡±…Ñ•ÍÑl´Åt¹•Ğ ‰…É•„ˆ¤¥˜±…Ñ•ÍĞ•±Í”€ˆˆ¤(€€€€€€€€€€€½È€¡ÁÉ½™¥±”¹•Ğ ‰±½…Ñ¥½¸ˆ¤½Èíô¤¹•Ğ ‰¥Ñäˆ¤(€€€€€€€€€€€½È€‹šr«š>C’úlˆ(€€€€€€€€¤¹ÍÑÉ¥À ¤(€€€€€€€½Õ¹Ñå}É½Ü¡½Õ¹Ñä¥l‰µ•µ‰•ÉÌ‰t€¬ô€Ä((€€€™½È½É‘•È¥¸½É‘•ÉÌè(€€€€€€€ÁÉ½™¥±”€ôÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ°íô¤¹•Ğ¡½É‘•È¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤°íô¤(€€€€€€€±…Ñ•ÍĞ€ôl(€€€€€€€€€€€É½Ü™½ÈÉ½Ü¥¸€¡ÁÉ½™¥±”¹•Ğ ‰¡•­¥¹}É•½É‘Ìˆ¤½Èmt¤(€€€€€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡É½Ü°‘¥Ğ¤(€€€€€€€t(€€€€€€€½Õ¹Ñä€ôÍÑÈ (€€€€€€€€€€€€¡±…Ñ•ÍÑl´Åt¹•Ğ ‰…É•„ˆ¤¥˜±…Ñ•ÍĞ•±Í”€ˆˆ¤(€€€€€€€€€€€½È€¡ÁÉ½™¥±”¹•Ğ ‰±½…Ñ¥½¸ˆ¤½Èíô¤¹•Ğ ‰¥Ñäˆ¤(€€€€€€€€€€€½È€‹šr«š>C’úlˆ(€€€€€€€€¤¹ÍÑÉ¥À ¤(€€€€€€€É½Ü€ô½Õ¹Ñå}É½Ü¡½Õ¹Ñä¤(€€€€€€€É½İl‰½É‘•ÉÌ‰t€¬ô€Ä(€€€€€€€¥˜½É‘•È¹•Ğ ‰ÍÑ…ÑÕÌˆ¤€ôô€‰Á…¥ˆè(€€€€€€€€€€€É½İl‰Á…¥‘}½É‘•ÉÌ‰t€¬ô€Ä(€€€€€€€€€€€É½İl‰É•Ù•¹Õ”‰t€¬ô¥¹Ğ¡½É‘•È¹•Ğ ‰…µ½Õ¹Ğˆ¤½È€À¤((€€€½Õ¹Ñå}ÍÑ…ÑÌ€ôÍ½ÉÑ• (€€€€€€€½Õ¹Ñå}É½İÌ¹Ù…±Õ•Ì ¤°(€€€€€€€­•äõ±…µ‰‘„¥Ñ•´è€ µ¥Ñ•µl‰É•Ù•¹Õ”‰t°€µ¥Ñ•µl‰µ•µ‰•ÉÌ‰t°¥Ñ•µl‰½Õ¹Ñä‰t¤°(€€€€¤(€€€Á•ÉÍ¥ÍĞ€ôÁ•ÉÍ¥ÍÑ•¹•}¥¹™¼¡‘…Ñ…}™¥±”¤(€€€Õ…É‘¥…¹}¥¹Ù¥Ñ•Ì€ômt(€€€™½ÈÉ½Ü¥¸É•Ù•ÉÍ• ¡ÍÑ…Ñ”¹•Ğ ‰Õ…É‘¥…¹}¥¹Ù¥Ñ•Ìˆ¤½Èmt¥l´ÄÀÀét¤è(€€€€€€€¥˜¹½Ğ¥Í¥¹ÍÑ…¹”¡É½Ü°‘¥Ğ¤è(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€Õ…É‘¥…¹}¥¹Ù¥Ñ•Ì¹…ÁÁ•¹¡ì(€€€€€€€€€€€€‰¥ˆèÉ½Ü¹•Ğ ‰¥ˆ¤½È€ˆˆ°(€€€€€€€€€€€€‰¥¹Ù¥Ñ•É}±¥¹•}ÕÍ•É}¥ˆèÉ½Ü¹•Ğ ‰¥¹Ù¥Ñ•É}±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ°(€€€€€€€€€€€€‰‘¥ÍÁ±…å}¹…µ”ˆèÉ½Ü¹•Ğ ‰‘¥ÍÁ±…å}¹…µ”ˆ¤½È€ˆˆ°(€€€€€€€€€€€€‰É•±…Ñ¥½¹Í¡¥ÀˆèÉ½Ü¹•Ğ ‰É•±…Ñ¥½¹Í¡¥Àˆ¤½È€ˆˆ°(€€€€€€€€€€€€‰ÍÑ…ÑÕÌˆèÉ½Ü¹•Ğ ‰ÍÑ…ÑÕÌˆ¤½È€ˆˆ°(€€€€€€€€€€€€‰É•…Ñ•‘}…ĞˆèÉ½Ü¹•Ğ ‰É•…Ñ•‘}…Ğˆ¤½È€ˆˆ°(€€€€€€€€€€€€‰•áÁ¥É•Í}…ĞˆèÉ½Ü¹•Ğ ‰•áÁ¥É•Í}…Ğˆ¤½È€ˆˆ°(€€€€€€€€€€€€‰…•ÁÑ•‘}…ĞˆèÉ½Ü¹•Ğ ‰…•ÁÑ•‘}…Ğˆ¤½È€ˆˆ°(€€€€€€€€€€€€‰¥¹Ù¥Ñ••}±¥¹•}ÕÍ•É}¥ˆèÉ½Ü¹•Ğ ‰¥¹Ù¥Ñ••}±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ°(€€€€€€€ô¤(€€€ÅÕ½Ñ„€ô¥¹Ğ ¡½¹™¥œ½Èíô¤¹•Ğ ‰1%9}5=9Q!1e}5MM}EU=Qˆ¤½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}5=9Q!1e}5MM}EU=Qˆ¤½È€ÈÀÀ¤(€€€±¥¹•}ÕÍ…”€ôµ½¹Ñ¡±å}±¥¹•}µ•ÍÍ…•}ÕÍ…” (€€€€€€€ÍÑ…Ñ”°ÍÑ…ÑÕÍ}¹½Ü¹ÍÑÉ™Ñ¥µ” ˆ•d´•´ˆ¤°ÅÕ½Ñ„°ÍÑ…ÑÕÍ}¹½Ü(€€€€¤(€€€É•ÑÕÉ¸ì(€€€€€€€€‰Ñ½Ñ…±}ÕÍ•ÉÌˆè±•¸¡ÕÍ•ÉÌ¤°(€€€€€€€€‰½Ù•É‘Õ•}ÕÍ•ÉÌˆèÍÕ´ Ä™½ÈÕÍ•È¥¸ÕÍ•ÉÌ¥˜ÕÍ•Él‰¥Í}½Ù•É‘Õ”‰t¤°(€€€€€€€€‰İ…É¹¥¹}ÕÍ•ÉÌˆèÍÕ´ Ä™½ÈÕÍ•È¥¸ÕÍ•ÉÌ¥˜ÕÍ•Él‰ÍÑ…ÑÕÍ}±…ÍÌ‰t€ôô€‰İ…É¹¥¹œˆ¤°(€€€€€€€€‰¡•­•‘}Ñ½‘…äˆèÍÕ´ Ä™½ÈÕÍ•È¥¸ÕÍ•ÉÌ¥˜ÕÍ•Él‰¥Í}Ñ½‘…å}¡•­•‰t¤°(€€€€€€€€‰Õ…É‘¥…¹}É½ÕÁ}½Õ¹Ğˆè±•¸¡Õ…É‘¥…¹}É½ÕÁÌ¤°(€€€€€€€€‰Õ…É‘¥…¹}É½ÕÁÌˆèÕ…É‘¥…¹}É½ÕÁÌ°(€€€€€€€€‰‰½Õ¹‘}Õ…É‘¥…¹}Ñ½Ñ…°ˆèÍÕ´¡¥¹Ğ¡ÕÍ•È¹•Ğ ‰‰½Õ¹‘}Õ…É‘¥…¹}½Õ¹Ğˆ¤½È€À¤™½ÈÕÍ•È¥¸ÕÍ•ÉÌ¤°(€€€€€€€€‰¥¹Ù¥Ñ•}•‘•Ìˆè±¥ÍĞ¡É•Ù•ÉÍ•¡¥¹Ù¥Ñ•}•‘•Íl´ÄÀÀét¤¤°(€€€€€€€€‰Õ…É‘¥…¹}¥¹Ù¥Ñ•ÌˆèÕ…É‘¥…¹}¥¹Ù¥Ñ•Ì°(€€€€€€€€‰Õ…É‘¥…¹}¥¹Ù¥Ñ•}½Õ¹ÑÌˆèì(€€€€€€€€€€€ÍÑ…ÑÕÌèÍÕ´ Ä™½ÈÉ½Ü¥¸Õ…É‘¥…¹}¥¹Ù¥Ñ•Ì¥˜É½Ü¹•Ğ ‰ÍÑ…ÑÕÌˆ¤€ôôÍÑ…ÑÕÌ¤(€€€€€€€€€€€™½ÈÍÑ…ÑÕÌ¥¸€ ‰Á•¹‘¥¹œˆ°€‰…•ÁÑ•ˆ°€‰•áÁ¥É•ˆ¤(€€€€€€€ô°(€€€€€€€€‰½É‘•ÉÌˆè½É‘•ÉÌ°(€€€€€€€€‰Á…¥‘}½É‘•É}½Õ¹Ğˆè±•¸¡Á…¥‘}½É‘•ÉÌ¤°(€€€€€€€€‰Á…¥‘}É•Ù•¹Õ”ˆèÍÕ´¡¥¹Ğ¡½É‘•È¹•Ğ ‰…µ½Õ¹Ğˆ¤½È€À¤™½È½É‘•È¥¸Á…¥‘}½É‘•ÉÌ¤°(€€€€€€€€‰Á•¹‘¥¹}½É‘•É}½Õ¹ĞˆèÍÕ´ Ä™½È½É‘•È¥¸½É‘•ÉÌ¥˜½É‘•È¹•Ğ ‰ÍÑ…ÑÕÌˆ¤€ôô€‰Á•¹‘¥¹œˆ¤°(€€€€€€€€‰½Õ¹Ñå}ÍÑ…ÑÌˆè½Õ¹Ñå}ÍÑ…ÑÌ°(€€€€€€€€‰ÕÍ•ÉÌˆèÕÍ•ÉÌ°(€€€€€€€€‰½¹Ñ…Ñ}É•İ…É‘Ìˆè±¥ÍĞ¡É•Ù•ÉÍ•¡ÍÑ…Ñ”¹•Ğ ‰½¹Ñ…Ñ}É•İ…É‘Ìˆ°mt¥l´ÈÀét¤¤°(€€€€€€€€‰¹½Ñ¥™¥…Ñ¥½¹}±½Ìˆè±¥ÍĞ¡É•Ù•ÉÍ•¡ÍÑ…Ñ”¹•Ğ ‰¹½Ñ¥™¥…Ñ¥½¹}±½Ìˆ°mt¥l´ÈÀét¤¤°(€€€€€€€€‰‘…¥±å}ÁÕÍ¡}µ•µ‰•É}ÍÑ…ÑÌˆè‘…¥±å}ÁÕÍ¡}µ•µ‰•É}ÍÑ…ÑÍlèÔÀÁt°(€€€€€€€€‰±¥¹•}µ•ÍÍ…•}ÕÍ…”ˆè±¥¹•}ÕÍ…”°(€€€€€€€€‰‘¥ÍÁ±…å}¹…µ•Í}¡å‘É…Ñ•ˆè¡å‘É…Ñ•°(€€€€€€€€‰Á•ÉÍ¥ÍÑ•¹”ˆèÁ•ÉÍ¥ÍĞ°(€€€ô(()}5%IQ%=9}5%9}=U9Q}-eL€ô€ (€€€€‰¡•­¥¹Ìˆ°(€€€€‰½¹Ñ…ÑÌˆ°(€€€€‰É½ÕÁÌˆ°(€€€€‰É•µ¥¹‘•ÉÌˆ°(€€€€‰½É‘•ÉÌˆ°(€€€€‰É•ÅÕ•ÍÑÌˆ°(¤)}5%IQ%=9}5%9}%1UI}Q=I%L€ôì(€€€€ˆˆ°(€€€€‰¥¹Ù…±¥‘}½‘”ˆ°(€€€€‰•áÁ¥É•‘}½‘”ˆ°(€€€€‰ÕÍ•‘}½‘”ˆ°(€€€€‰Í½ÕÉ•}µ¥ÍÍ¥¹œˆ°(€€€€‰Õ¹Í…™•}½¹™±¥Ğˆ°(€€€€‰µ¥É…Ñ¥½¹}™…¥±•ˆ°)ô(()‘•˜…‘µ¥¹}…½Õ¹Ñ}µ¥É…Ñ¥½¹Ì¡‘…Ñ…}™¥±”°½¹™¥œ°¹½Üõ9½¹”¤è(€€€€ˆˆ‰I•ÑÕÉ¸„É•…µ½¹±ä°…±±½İ±¥ÍÑ•½Á•É…Ñ¥½¹…°µ¥É…Ñ¥½¸ÍÕµµ…Éä¸ˆˆˆ(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€ÕÉÉ•¹Ğ€ô}…½Õ¹Ñ}µ¥É…Ñ¥½¹}¹½Ü¡¹½Ü¤(€€€…Õ‘¥Ğ€ôÍÑ…Ñ”¹•Ğ ‰…½Õ¹Ñ}µ¥É…Ñ¥½¹}…Õ‘¥Ğˆ¤½Èmt(€€€ÍÕ•ÍÍ•Ì€ôÍÕ´ (€€€€€€€€Ä(€€€€€€€™½È•Ù•¹Ğ¥¸…Õ‘¥Ğ(€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡•Ù•¹Ğ°‘¥Ğ¤…¹•Ù•¹Ğ¹•Ğ ‰ÍÑ…ÑÕÌˆ¤€ôô€‰ÍÕ•ÍÌˆ(€€€€¤(€€€™…¥±ÕÉ•Ì€ôÍÕ´ (€€€€€€€€Ä(€€€€€€€™½È•Ù•¹Ğ¥¸…Õ‘¥Ğ(€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡•Ù•¹Ğ°‘¥Ğ¤…¹•Ù•¹Ğ¹•Ğ ‰ÍÑ…ÑÕÌˆ¤€ôô€‰™…¥±•ˆ(€€€€¤(€€€Á•¹‘¥¹œ€ôÍÕ´ (€€€€€€€€Ä(€€€€€€€™½ÈÑ¥­•Ğ¥¸€¡ÍÑ…Ñ”¹•Ğ ‰…½Õ¹Ñ}µ¥É…Ñ¥½¹}Ñ¥­•ÑÌˆ¤½Èíô¤¹Ù…±Õ•Ì ¤(€€€€€€€¥˜€ (€€€€€€€€€€€¥Í¥¹ÍÑ…¹”¡Ñ¥­•Ğ°‘¥Ğ¤(€€€€€€€€€€€…¹Ñ¥­•Ğ¹•Ğ ‰ÍÑ…ÑÕÌˆ¤€ôô€‰Á•¹‘¥¹œˆ(€€€€€€€€€€€…¹€ (€€€€€€€€€€€€€€€}…½Õ¹Ñ}µ¥É…Ñ¥½¹}‘…Ñ•Ñ¥µ”¡Ñ¥­•Ğ¹•Ğ ‰•áÁ¥É•Í}…Ğˆ¤¤(€€€€€€€€€€€€€€€…¹ÕÉÉ•¹Ğ(€€€€€€€€€€€€€€€€ğ}…½Õ¹Ñ}µ¥É…Ñ¥½¹}‘…Ñ•Ñ¥µ”¡Ñ¥­•Ğ¹•Ğ ‰•áÁ¥É•Í}…Ğˆ¤¤(€€€€€€€€€€€€¤(€€€€€€€€¤(€€€€¤(€€€±…Ñ•ÍÑ}•Ù•¹ÑÌ€ômt(€€€™½È•Ù•¹Ğ¥¸É•Ù•ÉÍ•¡…Õ‘¥Ñl´ÄÀét¤è(€€€€€€€¥˜¹½Ğ¥Í¥¹ÍÑ…¹”¡•Ù•¹Ğ°‘¥Ğ¤è(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€ÍÑ…ÑÕÌ€ô€ (€€€€€€€€€€€•Ù•¹Ğ¹•Ğ ‰ÍÑ…ÑÕÌˆ¤(€€€€€€€€€€€¥˜•Ù•¹Ğ¹•Ğ ‰ÍÑ…ÑÕÌˆ¤¥¸ì‰ÍÕ•ÍÌˆ°€‰™…¥±•‰ô(€€€€€€€€€€€•±Í”€‰™…¥±•ˆ(€€€€€€€€¤(€€€€€€€™…¥±ÕÉ•}…Ñ•½Éä€ôÍÑÈ¡•Ù•¹Ğ¹•Ğ ‰™…¥±ÕÉ•}…Ñ•½Éäˆ¤½È€ˆˆ¤(€€€€€€€¥˜™…¥±ÕÉ•}…Ñ•½Éä¹½Ğ¥¸}5%IQ%=9}5%9}%1UI}Q=I%Lè(€€€€€€€€€€€™…¥±ÕÉ•}…Ñ•½Éä€ô€‰½Ñ¡•Èˆ(€€€€€€€É•…Ñ•‘}…Ğ€ô}…½Õ¹Ñ}µ¥É…Ñ¥½¹}‘…Ñ•Ñ¥µ”¡•Ù•¹Ğ¹•Ğ ‰É•…Ñ•‘}…Ğˆ¤¤(€€€€€€€É…İ}½Õ¹ÑÌ€ô€ (€€€€€€€€€€€•Ù•¹Ğ¹•Ğ ‰½Õ¹ÑÌˆ¤(€€€€€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡•Ù•¹Ğ¹•Ğ ‰½Õ¹ÑÌˆ¤°‘¥Ğ¤(€€€€€€€€€€€•±Í”íô(€€€€€€€€¤(€€€€€€€½Õ¹ÑÌ€ôíô(€€€€€€€™½È­•ä¥¸}5%IQ%=9}5%9}=U9Q}-eLè(€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€½Õ¹ÑÍm­•åt€ôµ…à À°¥¹Ğ¡É…İ}½Õ¹ÑÌ¹•Ğ¡­•ä¤½È€À¤¤(€€€€€€€€€€€•á•ÁĞ€¡QåÁ•ÉÉ½È°Y…±Õ•ÉÉ½È¤è(€€€€€€€€€€€€€€€½Õ¹ÑÍm­•åt€ô€À(€€€€€€€±…Ñ•ÍÑ}•Ù•¹ÑÌ¹…ÁÁ•¹¡ì(€€€€€€€€€€€€‰ÍÑ…ÑÕÌˆèÍÑ…ÑÕÌ°(€€€€€€€€€€€€‰É•…Ñ•‘}…Ğˆè€ (€€€€€€€€€€€€€€€É•…Ñ•‘}…Ğ¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤(€€€€€€€€€€€€€€€¥˜É•…Ñ•‘}…Ğ(€€€€€€€€€€€€€€€•±Í”€ˆˆ(€€€€€€€€€€€€¤°(€€€€€€€€€€€€‰™…¥±ÕÉ•}…Ñ•½Éäˆè™…¥±ÕÉ•}…Ñ•½Éä°(€€€€€€€€€€€€‰½Õ¹ÑÌˆè½Õ¹ÑÌ°(€€€€€€€ô¤(€€€É•ÑÕÉ¸ì(€€€€€€€€‰½¹™¥ÕÉ•ˆè…½Õ¹Ñ}µ¥É…Ñ¥½¹}É•…‘ä¡½¹™¥œ¤°(€€€€€€€€‰Ñ½Ñ…±Ìˆèì(€€€€€€€€€€€€‰Ñ½Ñ…°ˆèÍÕ•ÍÍ•Ì€¬™…¥±ÕÉ•Ì€¬Á•¹‘¥¹œ°(€€€€€€€€€€€€‰ÍÕ•ÍÌˆèÍÕ•ÍÍ•Ì°(€€€€€€€€€€€€‰™…¥±•ˆè™…¥±ÕÉ•Ì°(€€€€€€€€€€€€‰Á•¹‘¥¹œˆèÁ•¹‘¥¹œ°(€€€€€€€ô°(€€€€€€€€‰±…Ñ•ÍÑ}•Ù•¹ÑÌˆè±…Ñ•ÍÑ}•Ù•¹ÑÌ°(€€€ô(()‘•˜‰…­ÕÁ}É½½Ğ¡‘…Ñ…}™¥±”¤è(€€€É•ÑÕÉ¸A…Ñ ¡‘…Ñ…}™¥±”¤¹Á…É•¹Ğ€¼€‰‰…­ÕÁÌˆ(()‘•˜}ÈÉ}‰…­ÕÁ}­•ä¡É…Ü¤è(€€€ÑÉäè(€€€€€€€­•ä€ô‰…Í”ØĞ¹ÕÉ±Í…™•}ˆØÑ‘•½‘”¡ÍÑÈ¡É…Ü¤¹•¹½‘” ¤¤(€€€•á•ÁĞá•ÁÑ¥½¸è(€€€€€€€­•ä€ôˆˆˆ(€€€É•ÑÕÉ¸­•ä¥˜±•¸¡­•ä¤€ôô€ÌÈ•±Í”9½¹”(()‘•˜}‘•™…Õ±Ñ}ÈÉ}ÕÁ±½…‘•È¡‰Õ­•Ğ°½‰©•Ñ}­•ä°‰½‘ä°½¹Ñ•¹Ñ}ÑåÁ”°µ•Ñ…‘…Ñ„°½¹™¥œ¤è(€€€¥µÁ½ÉĞ‰½Ñ¼Ì((€€€±¥•¹Ğ€ô‰½Ñ¼Ì¹±¥•¹Ğ (€€€€€€€€‰ÌÌˆ°(€€€€€€€•¹‘Á½¥¹Ñ}ÕÉ°õ½¹™¥œ¹•Ğ ‰HÉ}9A=%9Pˆ¤°(€€€€€€€…İÍ}…•ÍÍ}­•å}¥õ½¹™¥œ¹•Ğ ‰HÉ}MM}-e}%ˆ¤°(€€€€€€€…İÍ}Í•É•Ñ}…•ÍÍ}­•äõ½¹™¥œ¹•Ğ ‰HÉ}MIQ}MM}-dˆ¤°(€€€€€€€É•¥½¹}¹…µ”ô‰…ÕÑ¼ˆ°(€€€€¤(€€€É•ÑÕÉ¸±¥•¹Ğ¹ÁÕÑ}½‰©•Ğ (€€€€€€€	Õ­•Ğõ‰Õ­•Ğ°(€€€€€€€-•äõ½‰©•Ñ}­•ä°(€€€€€€€	½‘äõ‰½‘ä°(€€€€€€€½¹Ñ•¹ÑQåÁ”õ½¹Ñ•¹Ñ}ÑåÁ”°(€€€€€€€5•Ñ…‘…Ñ„õµ•Ñ…‘…Ñ„°(€€€€¤(()‘•˜É•…Ñ•}ÈÉ}•¹ÉåÁÑ•‘}‰…­ÕÀ¡½¹™¥œ¤è(€€€‰Õ­•Ğ€ôÍÑÈ¡½¹™¥œ¹•Ğ ‰HÉ}	U-Pˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€­•ä€ô}ÈÉ}‰…­ÕÁ}­•ä¡½¹™¥œ¹•Ğ ‰HÉ}	-UA}9IeAQ%=9}-dˆ¤½È€ˆˆ¤(€€€ÕÁ±½…‘•È€ô½¹™¥œ¹•Ğ ‰HÉ}UA1=Hˆ¤½È}‘•™…Õ±Ñ}ÈÉ}ÕÁ±½…‘•È(€€€¥˜¹½Ğ‰Õ­•Ğ½È­•ä¥Ì9½¹”½ÈL¥Ì9½¹”è(€€€€€€€É•ÑÕÉ¸ì‰•ÉÉ½Èˆè€‰ÈÉ}‰…­ÕÁ}¹½Ñ}½¹™¥ÕÉ•‰ô°€ÔÀÌ(€€€¥˜ÕÁ±½…‘•È¥Ì}‘•™…Õ±Ñ}ÈÉ}ÕÁ±½…‘•È…¹¹½Ğ…±° (€€€€€€€ÍÑÈ¡½¹™¥œ¹•Ğ¡¹…µ”¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€™½È¹…µ”¥¸€ ‰HÉ}9A=%9Pˆ°€‰HÉ}MM}-e}%ˆ°€‰HÉ}MIQ}MM}-dˆ¤(€€€€¤è(€€€€€€€É•ÑÕÉ¸ì‰•ÉÉ½Èˆè€‰ÈÉ}‰…­ÕÁ}¹½Ñ}½¹™¥ÕÉ•‰ô°€ÔÀÌ(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡½¹™¥l‰Q}%1‰t¤(€€€É•…Ñ•‘}…Ğ€ô‘…Ñ•Ñ¥µ”¹¹½Ü¡Ñ¥µ•é½¹”¹ÕÑŒ¤¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤(€€€‰…­ÕÁ}¥€ô€ (€€€€€€€˜‰ÈÈµí‘…Ñ•Ñ¥µ”¹¹½Ü¡Ñ¥µ•é½¹”¹ÕÑŒ¤¹ÍÑÉ™Ñ¥µ” œ•d•´•‘P• •4•Mhœ¥ô´ˆ(€€€€€€€˜‰íÍ•É•ÑÌ¹Ñ½­•¹}¡•à Ì¥ôˆ(€€€€¤(€€€Í¹…ÁÍ¡½Ğ€ôì(€€€€€€€­•å}¹…µ”èÙ…±Õ”(€€€€€€€™½È­•å}¹…µ”°Ù…±Õ”¥¸ÍÑ…Ñ”¹¥Ñ•µÌ ¤(€€€€€€€¥˜­•å}¹…µ”¹½Ğ¥¸ì‰‰…­ÕÁ}•áÁ½ÉÑÌˆ°€‰ÈÉ}‰…­ÕÁ}•áÁ½ÉÑÌ‰ô(€€€ô(€€€Á±…¥¹Ñ•áĞ€ô©Í½¸¹‘ÕµÁÌ (€€€€€€€ì‰‰…­ÕÁ}¥ˆè‰…­ÕÁ}¥°€‰É•…Ñ•‘}…ĞˆèÉ•…Ñ•‘}…Ğ°€‰Í¹…ÁÍ¡½ĞˆèÍ¹…ÁÍ¡½Ñô°(€€€€€€€•¹ÍÕÉ•}…Í¥¤õ…±Í”°(€€€€€€€Í•Á…É…Ñ½ÉÌô ˆ°ˆ°€ˆèˆ¤°(€€€€¤¹•¹½‘” ¤(€€€¥Á¡•È€ôL¹¹•Ü¡­•ä°L¹5=}4¤(€€€¥Á¡•ÉÑ•áĞ°Ñ…œ€ô¥Á¡•È¹•¹ÉåÁÑ}…¹‘}‘¥•ÍĞ¡Á±…¥¹Ñ•áĞ¤(€€€•¹Ù•±½Á”€ô©Í½¸¹‘ÕµÁÌ (€€€€€€€ì(€€€€€€€€€€€€‰Ù•ÉÍ¥½¸ˆè€Ä°(€€€€€€€€€€€€‰…±½É¥Ñ¡´ˆè€‰L´ÈÔØµ4ˆ°(€€€€€€€€€€€€‰¹½¹”ˆè‰…Í”ØĞ¹ˆØÑ•¹½‘”¡¥Á¡•È¹¹½¹”¤¹‘•½‘” ¤°(€€€€€€€€€€€€‰Ñ…œˆè‰…Í”ØĞ¹ˆØÑ•¹½‘”¡Ñ…œ¤¹‘•½‘” ¤°(€€€€€€€€€€€€‰¥Á¡•ÉÑ•áĞˆè‰…Í”ØĞ¹ˆØÑ•¹½‘”¡¥Á¡•ÉÑ•áĞ¤¹‘•½‘” ¤°(€€€€€€€ô°(€€€€€€€Í•Á…É…Ñ½ÉÌô ˆ°ˆ°€ˆèˆ¤°(€€€€¤¹•¹½‘” ¤(€€€½‰©•Ñ}­•ä€ô˜‰…±¥Ù”µ¡•­¥¸½íÉ•…Ñ•‘}…ÑlèÄÁuô½í‰…­ÕÁ}¥‘ô¹©Í½¸¹…•Í´ˆ(€€€µ•Ñ…‘…Ñ„€ôì(€€€€€€€€‰•¹ÉåÁÑ¥½¸ˆè€‰L´ÈÔØµ4ˆ°(€€€€€€€€‰‰…­ÕÀµ¥ˆè‰…­ÕÁ}¥°(€€€€€€€€‰Í¡„ÈÔØˆè¡…Í¡±¥ˆ¹Í¡„ÈÔØ¡•¹Ù•±½Á”¤¹¡•á‘¥•ÍĞ ¤°(€€€ô(€€€ÑÉäè(€€€€€€€É•ÍÕ±Ğ€ôÕÁ±½…‘•È (€€€€€€€€€€€‰Õ­•Ğ°(€€€€€€€€€€€½‰©•Ñ}­•ä°(€€€€€€€€€€€•¹Ù•±½Á”°(€€€€€€€€€€€€‰…ÁÁ±¥…Ñ¥½¸½½Ñ•ĞµÍÑÉ•…´ˆ°(€€€€€€€€€€€µ•Ñ…‘…Ñ„°(€€€€€€€€€€€½¹™¥œ°(€€€€€€€€¤(€€€•á•ÁĞá•ÁÑ¥½¸è(€€€€€€€É•ÑÕÉ¸ì‰•ÉÉ½Èˆè€‰ÈÉ}‰…­ÕÁ}ÕÁ±½…‘}™…¥±•‰ô°€ÔÀÈ(€€€•Ñ…œ€ôÍÑÈ ¡É•ÍÕ±Ğ½Èíô¤¹•Ğ ‰•Ñ…œˆ¤½È€¡É•ÍÕ±Ğ½Èíô¤¹•Ğ ‰Q…œˆ¤½È€ˆˆ¤(€€€•Ñ…œ€ô•Ñ…œ¹ÍÑÉ¥À œˆœ¤(€€€‰…­ÕÀ€ôì(€€€€€€€€‰¥ˆè‰…­ÕÁ}¥°(€€€€€€€€‰É•…Ñ•‘}…ĞˆèÉ•…Ñ•‘}…Ğ°(€€€€€€€€‰‰Õ­•Ğˆè‰Õ­•Ğ°(€€€€€€€€‰½‰©•Ñ}­•äˆè½‰©•Ñ}­•ä°(€€€€€€€€‰•Ñ…œˆè•Ñ…œ°(€€€€€€€€‰Í¡„ÈÔØˆèµ•Ñ…‘…Ñ…l‰Í¡„ÈÔØ‰t°(€€€€€€€€‰•¹ÉåÁÑ¥½¸ˆèµ•Ñ…‘…Ñ…l‰•¹ÉåÁÑ¥½¸‰t°(€€€€€€€€‰ÕÍ•É}½Õ¹Ğˆè±•¸¡Í¹…ÁÍ¡½Ğ¹•Ğ ‰ÕÍ•ÉÌˆ°íô¤¤°(€€€ô(€€€ÍÑ…Ñ”¹Í•Ñ‘•™…Õ±Ğ ‰ÈÉ}‰…­ÕÁ}•áÁ½ÉÑÌˆ°mt¤¹…ÁÁ•¹¡‰…­ÕÀ¤(€€€ÍÑ…Ñ•l‰ÈÉ}‰…­ÕÁ}•áÁ½ÉÑÌ‰t€ôÍÑ…Ñ•l‰ÈÉ}‰…­ÕÁ}•áÁ½ÉÑÌ‰ul´ÄÀÀét(€€€Í…Ù•}ÍÑ…Ñ”¡½¹™¥l‰Q}%1‰t°ÍÑ…Ñ”¤(€€€É•ÑÕÉ¸ì‰‰…­ÕÀˆè‰…­ÕÁô°€ÈÀÄ(()‘•˜É•…Ñ•}…‘µ¥¹}‰…­ÕÀ¡‘…Ñ…}™¥±”¤è(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€É•…Ñ•‘}…Ğ€ô‘…Ñ•Ñ¥µ”¹¹½Ü ¤¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤(€€€‰…­ÕÁ}¥€ô˜‰‰…­ÕÀµí‘…Ñ•Ñ¥µ”¹¹½Ü ¤¹ÍÑÉ™Ñ¥µ” œ•d•´•• •4•Lœ¥ôµíÍ•É•ÑÌ¹Ñ½­•¹}¡•à Ì¥ôˆ(€€€™¥±•¹…µ”€ô˜‰í‰…­ÕÁ}¥‘ô¹©Í½¸ˆ(€€€Í¹…ÁÍ¡½Ğ€ôí­•äèÙ…±Õ”™½È­•ä°Ù…±Õ”¥¸ÍÑ…Ñ”¹¥Ñ•µÌ ¤¥˜­•ä€„ô€‰‰…­ÕÁ}•áÁ½ÉÑÌ‰ô(€€€‰…­ÕÀ€ôì(€€€€€€€€‰¥ˆè‰…­ÕÁ}¥°(€€€€€€€€‰É•…Ñ•‘}…ĞˆèÉ•…Ñ•‘}…Ğ°(€€€€€€€€‰™¥±•¹…µ”ˆè™¥±•¹…µ”°(€€€€€€€€‰ÕÍ•É}½Õ¹Ğˆè±•¸¡Í¹…ÁÍ¡½Ğ¹•Ğ ‰ÕÍ•ÉÌˆ°íô¤¤°(€€€ô(€€€É½½Ğ€ô‰…­ÕÁ}É½½Ğ¡‘…Ñ…}™¥±”¤(€€€É½½Ğ¹µ­‘¥È¡Á…É•¹ÑÌõQÉÕ”°•á¥ÍÑ}½¬õQÉÕ”¤(€€€€¡É½½Ğ€¼™¥±•¹…µ”¤¹İÉ¥Ñ•}Ñ•áĞ (€€€€€€€©Í½¸¹‘ÕµÁÌ¡ì‰‰…­ÕÀˆè‰…­ÕÀ°€‰Í¹…ÁÍ¡½ĞˆèÍ¹…ÁÍ¡½Ñô°•¹ÍÕÉ•}…Í¥¤õ…±Í”°¥¹‘•¹ĞôÈ¤°(€€€€€€€•¹½‘¥¹œô‰ÕÑ˜´àˆ°(€€€€¤(€€€ÍÑ…Ñ”¹Í•Ñ‘•™…Õ±Ğ ‰‰…­ÕÁ}•áÁ½ÉÑÌˆ°mt¤¹…ÁÁ•¹¡‰…­ÕÀ¤(€€€ÍÑ…Ñ•l‰‰…­ÕÁ}•áÁ½ÉÑÌ‰t€ôÍÑ…Ñ•l‰‰…­ÕÁ}•áÁ½ÉÑÌ‰ul´ÔÀét(€€€Í…Ù•}ÍÑ…Ñ”¡‘…Ñ…}™¥±”°ÍÑ…Ñ”¤(€€€É•ÑÕÉ¸ì‰‰…­ÕÀˆè‰…­ÕÁô°€ÈÀÀ(()‘•˜±¥ÍÑ}…‘µ¥¹}‰…­ÕÁÌ¡‘…Ñ…}™¥±”¤è(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€É•ÑÕÉ¸ì‰‰…­ÕÁÌˆè±¥ÍĞ¡É•Ù•ÉÍ•¡ÍÑ…Ñ”¹•Ğ ‰‰…­ÕÁ}•áÁ½ÉÑÌˆ°mt¤¤¥ô(()‘•˜É•…‘}…‘µ¥¹}‰…­ÕÀ¡‘…Ñ…}™¥±”°‰…­ÕÁ}¥¤è(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€‰…­ÕÀ€ô¹•áĞ ¡¥Ñ•´™½È¥Ñ•´¥¸ÍÑ…Ñ”¹•Ğ ‰‰…­ÕÁ}•áÁ½ÉÑÌˆ°mt¤¥˜¥Ñ•´¹•Ğ ‰¥ˆ¤€ôô‰…­ÕÁ}¥¤°9½¹”¤(€€€¥˜¹½Ğ‰…­ÕÀè(€€€€€€€É•ÑÕÉ¸ì‰•ÉÉ½Èˆè€‰‰…­ÕÀ¹½Ğ™½Õ¹‰ô°€ĞÀĞ(€€€Á…Ñ €ô‰…­ÕÁ}É½½Ğ¡‘…Ñ…}™¥±”¤€¼‰…­ÕÀ¹•Ğ ‰™¥±•¹…µ”ˆ°€ˆˆ¤(€€€¥˜¹½ĞÁ…Ñ ¹•á¥ÍÑÌ ¤è(€€€€€€€É•ÑÕÉ¸ì‰•ÉÉ½Èˆè€‰‰…­ÕÀ™¥±”µ¥ÍÍ¥¹œ‰ô°€ĞÀĞ(€€€ÑÉäè(€€€€€€€É•ÑÕÉ¸©Í½¸¹±½…‘Ì¡Á…Ñ ¹É•…‘}Ñ•áĞ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤¤°€ÈÀÀ(€€€•á•ÁĞ€¡©Í½¸¹)M=9•½‘•ÉÉ½È°=MÉÉ½È¤è(€€€€€€€É•ÑÕÉ¸ì‰•ÉÉ½Èˆè€‰‰…­ÕÀ™¥±”Õ¹É•…‘…‰±”‰ô°€ÔÀÀ(()‘•˜‰Õ¥±‘}Í½Í}É½ÕÁ}µ•¹Ñ¥½¹}µ•ÍÍ…”¡…±•ÉÑ}Ñ•áĞèÍÑÈ¤è(€€€€ˆˆ‹ú“ÖM=O¾òkR Ñ•áÑXÈ€¬µ•¹Ñ¥½¹•”ÑåÁ”õ…±³¾ò!–£¦®S¾ò'¾ò3n‡–>¿¢÷¢ºOš¾?’ö7š"C–N‡šRÛ–"Ã¦k~—ˆˆˆ(€€€‰½‘ä€ôÍÑÈ¡…±•ÉÑ}Ñ•áĞ½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€É•ÑÕÉ¸ì(€€€€€€€€‰ÑåÁ”ˆè€‰Ñ•áÑXÈˆ°(€€€€€€€€‰Ñ•áĞˆè€‰í•Ù•Éå½¹•õq»Â~j£A–£¦®PƒŞ+š•M=OEq¸ˆ€¬‰½‘ä°(€€€€€€€€‰ÍÕ‰ÍÑ¥ÑÕÑ¥½¸ˆèì(€€€€€€€€€€€€‰•Ù•Éå½¹”ˆèì(€€€€€€€€€€€€€€€€‰ÑåÁ”ˆè€‰µ•¹Ñ¥½¸ˆ°(€€€€€€€€€€€€€€€€‰µ•¹Ñ¥½¹•”ˆèì‰ÑåÁ”ˆè€‰…±°‰ô°(€€€€€€€€€€€ô(€€€€€€€ô°(€€€ô(()‘•˜‰Õ¥±‘}Í½Í}É½ÕÁ}µ•µ‰•É}µ•¹Ñ¥½¹Í}µ•ÍÍ…”¡…±•ÉÑ}Ñ•áĞèÍÑÈ°µ•µ‰•É}ÕÍ•É}¥‘Ìõ9½¹”¤è(€€€€ˆˆ‰…±°ƒ–’ÇšV_šf–
gš>Ó¾òiµ•¹Ñ¥½¸ƒ–ŞË~—š"C–N„ÕÍ•É%“¾ò#–Z»–&šr–’h€ÈÀƒ’êë¾ò'ˆˆˆ(€€€‰½‘ä€ôÍÑÈ¡…±•ÉÑ}Ñ•áĞ½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€¥‘Ì€ômt(€€€Í••¸€ôÍ•Ğ ¤(€€€™½ÈÕ¥¥¸µ•µ‰•É}ÕÍ•É}¥‘Ì½Èmtè(€€€€€€€Ô€ôÍÑÈ¡Õ¥½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€¥˜¹½ĞÔ½ÈÔ¥¸Í••¸½È¹½ĞÔ¹ÍÑ…ÉÑÍİ¥Ñ  ‰Tˆ¤è(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€Í••¸¹…‘¡Ô¤(€€€€€€€¥‘Ì¹…ÁÁ•¹¡Ô¤(€€€€€€€¥˜±•¸¡¥‘Ì¤€øô€ÈÀè(€€€€€€€€€€€‰É•…¬(€€€¥˜¹½Ğ¥‘Ìè(€€€€€€€É•ÑÕÉ¸€‹Â~j£A–£¦®PƒŞ+š•M=OEq¸ˆ€¬‰½‘ä(€€€ÍÕ‰ÍÑ¥ÑÕÑ¥½¸€ôíô(€€€Á…ÉÑÌ€ômt(€€€™½È¤°Õ¥¥¸•¹Õµ•É…Ñ”¡¥‘Ì¤è(€€€€€€€­•ä€ô˜‰µí¥ôˆ(€€€€€€€Á…ÉÑÌ¹…ÁÁ•¹ ‰ìˆ€¬­•ä€¬€‰ôˆ¤(€€€€€€€ÍÕ‰ÍÑ¥ÑÕÑ¥½¹m­•åt€ôì(€€€€€€€€€€€€‰ÑåÁ”ˆè€‰µ•¹Ñ¥½¸ˆ°(€€€€€€€€€€€€‰µ•¹Ñ¥½¹•”ˆèì‰ÑåÁ”ˆè€‰ÕÍ•Èˆ°€‰ÕÍ•É%ˆèÕ¥‘ô°(€€€€€€€ô(€€€É•ÑÕÉ¸ì(€€€€€€€€‰ÑåÁ”ˆè€‰Ñ•áÑXÈˆ°(€€€€€€€€‰Ñ•áĞˆè€ˆ€ˆ¹©½¥¸¡Á…ÉÑÌ¤€¬€‰q»Â~j£A–£¦®PƒŞ+š•M=OEq¸ˆ€¬‰½‘ä°(€€€€€€€€‰ÍÕ‰ÍÑ¥ÑÕÑ¥½¸ˆèÍÕ‰ÍÑ¥ÑÕÑ¥½¸°(€€€ô(()‘•˜}Í•¹‘}±¥¹•}İ¥Ñ¡}É•ÑÉå}­•ä¡Í•¹‘•È°Ñ½­•¸°Ñ…É•Ğ°µ•ÍÍ…”°É•ÑÉå}­•ä¤è(€€€€ˆˆ‰UÍ”1%9É•ÑÉä­•åÌ¥¸ÁÉ½‘ÕÑ¥½¸İ¡¥±”­••Á¥¹œÍ¥µÁ±”¥¹©•Ñ•Ñ•ÍĞÍ•¹‘•ÉÌ¸ˆˆˆ(€€€¥˜Í•¹‘•È¥Ì±¥¹•}ÁÕÍ¡}µ•ÍÍ…”è(€€€€€€€É•ÑÕÉ¸Í•¹‘•È¡Ñ½­•¸°Ñ…É•Ğ°µ•ÍÍ…”°É•ÑÉå}­•äõÉ•ÑÉå}­•ä¤(€€€É•ÑÕÉ¸Í•¹‘•È¡Ñ½­•¸°Ñ…É•Ğ°µ•ÍÍ…”¤(()‘•˜ÁÕÍ¡}Í½Í}Ñ½}Õ…É‘¥…¹}É½ÕÀ (€€€Ñ½­•¸°É½ÕÁ}¥°…±•ÉÑ}Ñ•áĞ°€¨°Í•¹‘•Èõ9½¹”°µ•µ‰•É}¥‘Ìõ9½¹”°É•ÑÉå}­•äõ9½¹”(¤è(€€€€ˆˆ‹š:£¦ú“ÖM=O¾ò3–«– …±³¾òo–’ÇšV_–4µ•¹Ñ¥½¸ƒ–ŞË~—š"C–N‡¾òošr–ú3ÒSšZ–¶_–*€–£¦®Pƒ–&7ÚÓˆˆˆ(€€€ÁÕÍ €ôÍ•¹‘•È½È±¥¹•}ÁÕÍ¡}µ•ÍÍ…”(€€€¥€ôÍÑÈ¡É½ÕÁ}¥½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€¥˜¹½Ğ¥è(€€€€€€€É…¥Í”Y…±Õ•ÉÉ½È ‰µ¥ÍÍ¥¹œÉ½ÕÁ}¥™½ÈM=LÉ½ÕÀÁÕÍ ˆ¤(€€€ÁÉ¥µ…Éä€ô‰Õ¥±‘}Í½Í}É½ÕÁ}µ•¹Ñ¥½¹}µ•ÍÍ…”¡…±•ÉÑ}Ñ•áĞ¤(€€€ÑÉäè(€€€€€€€É•ÍÕ±Ğ€ô}Í•¹‘}±¥¹•}İ¥Ñ¡}É•ÑÉå}­•ä (€€€€€€€€€€€ÁÕÍ °Ñ½­•¸°¥°ÁÉ¥µ…Éä°(€€€€€€€€€€€}±¥¹•}É•ÑÉå}­•ä¡˜‰íÉ•ÑÉå}­•åôé…±°ˆ¤¥˜É•ÑÉå}­•ä•±Í”9½¹”°(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸É•ÍÕ±Ğ°€‰…±°ˆ°ÁÉ¥µ…Éä(€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€¥˜±…ÍÍ¥™å}ÁÕÍ¡}•á•ÁÑ¥½¸¡•áŒ¤¹­¥¹€„ô€‰µ•ÍÍ…”ˆè(€€€€€€€€€€€É…¥Í”(€€€€€€€™…±±‰…­}¥‘Ì€ô±¥ÍĞ¡µ•µ‰•É}¥‘Ì½Èmt¤(€€€€€€€¥˜¹½Ğ™…±±‰…­}¥‘Ìè(€€€€€€€€€€€™…±±‰…­}¥‘Ì€ô•Ñ}É½ÕÁ}µ•µ‰•É}¥‘Ì¡Ñ½­•¸°¥¤½Èmt(€€€€€€€Í•½¹‘…Éä€ô‰Õ¥±‘}Í½Í}É½ÕÁ}µ•µ‰•É}µ•¹Ñ¥½¹Í}µ•ÍÍ…”¡…±•ÉÑ}Ñ•áĞ°™…±±‰…­}¥‘Ì¤(€€€€€€€ÑÉäè(€€€€€€€€€€€É•ÍÕ±Ğ€ô}Í•¹‘}±¥¹•}İ¥Ñ¡}É•ÑÉå}­•ä (€€€€€€€€€€€€€€€ÁÕÍ °Ñ½­•¸°¥°Í•½¹‘…Éä°(€€€€€€€€€€€€€€€}±¥¹•}É•ÑÉå}­•ä¡˜‰íÉ•ÑÉå}­•åôéµ•µ‰•ÉÌˆ¤¥˜É•ÑÉå}­•ä•±Í”9½¹”°(€€€€€€€€€€€€¤(€€€€€€€€€€€µ½‘”€ô€‰µ•µ‰•ÉÌˆ¥˜¥Í¥¹ÍÑ…¹”¡Í•½¹‘…Éä°‘¥Ğ¤•±Í”€‰Ñ•áĞˆ(€€€€€€€€€€€É•ÑÕÉ¸É•ÍÕ±Ğ°µ½‘”°Í•½¹‘…Éä(€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€¥˜±…ÍÍ¥™å}ÁÕÍ¡}•á•ÁÑ¥½¸¡•áŒ¤¹­¥¹€„ô€‰µ•ÍÍ…”ˆè(€€€€€€€€€€€€€€€É…¥Í”(€€€€€€€€€€€Á±…¥¸€ô€‹Â~j£A–£¦®PƒŞ+š•M=OEq¸ˆ€¬ÍÑÈ¡…±•ÉÑ}Ñ•áĞ½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€€€€€É•ÍÕ±Ğ€ô}Í•¹‘}±¥¹•}İ¥Ñ¡}É•ÑÉå}­•ä (€€€€€€€€€€€€€€€ÁÕÍ °Ñ½­•¸°¥°Á±…¥¸°(€€€€€€€€€€€€€€€}±¥¹•}É•ÑÉå}­•ä¡˜‰íÉ•ÑÉå}­•åôéÑ•áĞˆ¤¥˜É•ÑÉå}­•ä•±Í”9½¹”°(€€€€€€€€€€€€¤(€€€€€€€€€€€É•ÑÕÉ¸É•ÍÕ±Ğ°€‰Ñ•áĞˆ°Á±…¥¸(()‘•˜±¥¹•}ÁÕÍ¡}µ•ÍÍ…”¡Ñ½­•¸°±¥¹•}ÕÍ•É}¥°µ•ÍÍ…”°€¨°É•ÑÉå}­•äõ9½¹”¤è(€€€€ˆˆ‹š:£¢¢+š¿Ö›–Z»’â 1%9ƒR£š"Û((€€€µ•ÍÍ…”ƒ–>¿’î—šb¼è(€€€€´ÍÑÈèƒÒSšZ–¶_¢¢+š¼(€€€€´‘¥Ğƒ’âS–âØ€‰ÑåÁ”ˆ­•äèƒnÓš:—’ös
è1%9µ•ÍÍ…”½‰©•Ğ€£’ú/–š™±•à¤(€€€€ˆˆˆ(€€€Ñ½}¥€ôÍÑÈ¡±¥¹•}ÕÍ•É}¥½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€¥˜¹½ĞÑ½}¥è(€€€€€€€É…¥Í”Y…±Õ•ÉÉ½È ‰µ¥ÍÍ¥¹œ±¥¹•}ÕÍ•É}¥™½ÈÁÕÍ ˆ¤(€€€¥˜¥Í¥¹ÍÑ…¹”¡µ•ÍÍ…”°‘¥Ğ¤…¹µ•ÍÍ…”¹•Ğ ‰ÑåÁ”ˆ¤è(€€€€€€€µÍ}½‰¨€ôµ•ÍÍ…”(€€€•±Í”è(€€€€€€€µÍ}½‰¨€ôì‰ÑåÁ”ˆè€‰Ñ•áĞˆ°€‰Ñ•áĞˆèÍÑÈ¡µ•ÍÍ…”¥ô(€€€‰½‘ä€ô©Í½¸¹‘ÕµÁÌ (€€€€€€€ì‰Ñ¼ˆèÑ½}¥°€‰µ•ÍÍ…•ÌˆèmµÍ}½‰©uô°(€€€€€€€•¹ÍÕÉ•}…Í¥¤õ…±Í”°(€€€€¤¹•¹½‘” ‰ÕÑ˜´àˆ¤(€€€¡•…‘•ÉÌ€ôì(€€€€€€€€‰½¹Ñ•¹ĞµQåÁ”ˆè€‰…ÁÁ±¥…Ñ¥½¸½©Í½¸ì¡…ÉÍ•ĞõUQ´àˆ°(€€€€€€€€‰ÕÑ¡½É¥é…Ñ¥½¸ˆè˜‰	•…É•ÈíÑ½­•¹ôˆ°(€€€ô(€€€¥˜É•ÑÉå}­•äè(€€€€€€€¡•…‘•ÉÍl‰`µ1¥¹”µI•ÑÉäµ-•ä‰t€ôÍÑÈ¡É•ÑÉå}­•ä¤(€€€É•Ä€ôÕÉ±±¥ˆ¹É•ÅÕ•ÍĞ¹I•ÅÕ•ÍĞ (€€€€€€€€‰¡ÑÑÁÌè¼½…Á¤¹±¥¹”¹µ”½ØÈ½‰½Ğ½µ•ÍÍ…”½ÁÕÍ ˆ°(€€€€€€€‘…Ñ„õ‰½‘ä°(€€€€€€€¡•…‘•ÉÌõ¡•…‘•ÉÌ°(€€€€€€€µ•Ñ¡½ô‰A=MPˆ°(€€€€¤(€€€ÑÉäè(€€€€€€€İ¥Ñ ÕÉ±±¥ˆ¹É•ÅÕ•ÍĞ¹ÕÉ±½Á•¸¡É•Ä°Ñ¥µ•½ÕĞôÄÀ¤…ÌÉ•Ìè(€€€€€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè€ÈÀÀ€ğôÉ•Ì¹ÍÑ…ÑÕÌ€ğ€ÌÀÀ°€‰ÍÑ…ÑÕÌˆèÉ•Ì¹ÍÑ…ÑÕÍô(€€€•á•ÁĞÕÉ±±¥ˆ¹•ÉÉ½È¹!QQAÉÉ½È…Ì•áŒè(€€€€€€€¥˜•áŒ¹½‘”€ôô€ĞÀä…¹•áŒ¹¡•…‘•ÉÌ¹•Ğ ‰`µ1¥¹”µ•ÁÑ•µI•ÅÕ•ÍĞµ%ˆ¤è(€€€€€€€€€€€É•ÑÕÉ¸ì(€€€€€€€€€€€€€€€€‰½¬ˆèQÉÕ”°(€€€€€€€€€€€€€€€€‰ÍÑ…ÑÕÌˆè€ĞÀä°(€€€€€€€€€€€€€€€€‰¥‘•µÁ½Ñ•¹Ñ}É•Á±…äˆèQÉÕ”°(€€€€€€€€€€€€€€€€‰…•ÁÑ•‘}É•ÅÕ•ÍÑ}¥ˆè•áŒ¹¡•…‘•ÉÌ¹•Ğ (€€€€€€€€€€€€€€€€€€€€‰`µ1¥¹”µ•ÁÑ•µI•ÅÕ•ÍĞµ%ˆ(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€ô(€€€€€€€•ÉÉ}‰½‘ä€ô€ˆˆ(€€€€€€€ÑÉäè(€€€€€€€€€€€•ÉÉ}‰½‘ä€ô•áŒ¹É•… ¤¹‘•½‘” ‰ÕÑ˜´àˆ°•ÉÉ½ÉÌô‰É•Á±…”ˆ¥lèÔÀÁt(€€€€€€€•á•ÁĞá•ÁÑ¥½¸è(€€€€€€€€€€€•ÉÉ}‰½‘ä€ô€ˆˆ(€€€€€€€€ŒI”µÉ…¥Í”İ¥Ñ 1%9‰½‘äÍ¼É½¸½‰…­™¥±°…¸ÍÕÉ™…”Ñ¡”É•…°…ÕÍ”¸(€€€€€€€É…¥Í”ÕÉ±±¥ˆ¹•ÉÉ½È¹!QQAÉÉ½È (€€€€€€€€€€€•áŒ¹ÕÉ°°(€€€€€€€€€€€•áŒ¹½‘”°(€€€€€€€€€€€˜‰í•áŒ¹É•…Í½¹ôèí•ÉÉ}‰½‘åôˆ¥˜•ÉÉ}‰½‘ä•±Í”•áŒ¹É•…Í½¸°(€€€€€€€€€€€•áŒ¹¡•…‘•ÉÌ°(€€€€€€€€€€€9½¹”°(€€€€€€€€¤™É½´•áŒ(()‘•˜…ÁÁ•¹‘}¹½Ñ¥™¥…Ñ¥½¹}±½œ¡ÍÑ…Ñ”°­¥¹°±¥¹•}ÕÍ•É}¥°ÍÑ…ÑÕÌ°µ•ÍÍ…”°‘•Ñ…¥°õ9½¹”¤è(€€€±½Ì€ôÍÑ…Ñ”¹Í•Ñ‘•™…Õ±Ğ ‰¹½Ñ¥™¥…Ñ¥½¹}±½Ìˆ°mt¤(€€€¥˜¥Í¥¹ÍÑ…¹”¡µ•ÍÍ…”°‘¥Ğ¤è(€€€€€€€µ•ÍÍ…•}Ñ•áĞ€ôÍÑÈ¡µ•ÍÍ…”¹•Ğ ‰…±ÑQ•áĞˆ¤½Èµ•ÍÍ…”¹•Ğ ‰ÑåÁ”ˆ¤½Èµ•ÍÍ…”¥lèÄÈÁt(€€€•±Í”è(€€€€€€€µ•ÍÍ…•}Ñ•áĞ€ôÍÑÈ¡µ•ÍÍ…”½È€ˆˆ¥lèÄÈÁt(€€€É•…Ñ•‘}…Ğ€ô‘…Ñ•Ñ¥µ”¹¹½Ü ¤¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤(€€€±½Ì¹…ÁÁ•¹ (€€€€€€€ì(€€€€€€€€€€€€‰É•…Ñ•‘}…ĞˆèÉ•…Ñ•‘}…Ğ°(€€€€€€€€€€€€‰­¥¹ˆè­¥¹°(€€€€€€€€€€€€‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€‰ÍÑ…ÑÕÌˆèÍÑ…ÑÕÌ°(€€€€€€€€€€€€‰µ•ÍÍ…”ˆèµ•ÍÍ…•}Ñ•áĞ°(€€€€€€€€€€€€‰‘•Ñ…¥°ˆè‘•Ñ…¥°½È€ˆˆ°(€€€€€€€ô(€€€€¤(€€€ÍÑ…Ñ•l‰¹½Ñ¥™¥…Ñ¥½¹}±½Ì‰t€ô±½Íl´ÄÀÀét(€€€µ•µ‰•É}¥€ôÍÑÈ¡±¥¹•}ÕÍ•É}¥½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€‘…Ñ”€ôÉ•…Ñ•‘}…ÑlèÄÁt(€€€¥˜µ•µ‰•É}¥è(€€€€€€€ÍÑ…ÑÌ€ôÍÑ…Ñ”¹Í•Ñ‘•™…Õ±Ğ ‰‘…¥±å}ÁÕÍ¡}µ•µ‰•É}ÍÑ…ÑÌˆ°íô¤(€€€€€€€­•ä€ô˜‰í‘…Ñ•õñíµ•µ‰•É}¥‘ôˆ(€€€€€€€É½Ü€ôÍÑ…ÑÌ¹Í•Ñ‘•™…Õ±Ğ (€€€€€€€€€€€­•ä°(€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€‰‘…Ñ”ˆè‘…Ñ”°(€€€€€€€€€€€€€€€€‰±¥¹•}ÕÍ•É}¥ˆèµ•µ‰•É}¥°(€€€€€€€€€€€€€€€€‰Í•¹Ñ}½Õ¹Ğˆè€À°(€€€€€€€€€€€€€€€€‰™…¥±•‘}½Õ¹Ğˆè€À°(€€€€€€€€€€€€€€€€‰Ñ½Ñ…±}½Õ¹Ğˆè€À°(€€€€€€€€€€€€€€€€‰­¥¹‘Ìˆèmt°(€€€€€€€€€€€€€€€€‰±…ÍÑ}ÁÕÍ¡}…ĞˆèÉ•…Ñ•‘}…Ğ°(€€€€€€€€€€€ô°(€€€€€€€€¤(€€€€€€€É½İl‰Ñ½Ñ…±}½Õ¹Ğ‰t€ô¥¹Ğ¡É½Ü¹•Ğ ‰Ñ½Ñ…±}½Õ¹Ğˆ¤½È€À¤€¬€Ä(€€€€€€€¥˜ÍÑ…ÑÕÌ€ôô€‰Í•¹Ğˆè(€€€€€€€€€€€É½İl‰Í•¹Ñ}½Õ¹Ğ‰t€ô¥¹Ğ¡É½Ü¹•Ğ ‰Í•¹Ñ}½Õ¹Ğˆ¤½È€À¤€¬€Ä(€€€€€€€•±¥˜ÍÑ…ÑÕÌ¥¸ì‰™…¥±•ˆ°€‰•ÉÉ½Èˆ°€‰‰±½­•‰ôè(€€€€€€€€€€€É½İl‰™…¥±•‘}½Õ¹Ğ‰t€ô¥¹Ğ¡É½Ü¹•Ğ ‰™…¥±•‘}½Õ¹Ğˆ¤½È€À¤€¬€Ä(€€€€€€€€€€€É½İl‰±…Ñ•ÍÑ}™…¥±ÕÉ•}‘•Ñ…¥°‰t€ôÍÑÈ¡‘•Ñ…¥°½È€ˆˆ¥lèÔÀÁt(€€€€€€€€€€€É½İl‰±…Ñ•ÍÑ}™…¥±ÕÉ•}…Ğ‰t€ôÉ•…Ñ•‘}…Ğ(€€€€€€€É½İl‰­¥¹‘Ì‰t€ôÍ½ÉÑ•¡Í•Ğ¡É½Ü¹•Ğ ‰­¥¹‘Ìˆ¤½Èmt¤ğíÍÑÈ¡­¥¹½È€‰½Ñ¡•Èˆ¥ô¤(€€€€€€€É½İl‰±…ÍÑ}ÁÕÍ¡}…Ğ‰t€ôÉ•…Ñ•‘}…Ğ(€€€€€€€€Œ-••ÀÉ½Õ¡±ä½¹”å•…È½˜‘…¥±ä½µ•µ‰•È…É•…Ñ•Ìİ¥Ñ¡½ÕĞÉ½İ¥¹œ™½É•Ù•È¸(€€€€€€€¥˜±•¸¡ÍÑ…ÑÌ¤€ø€ÈÀÀÀÀè(€€€€€€€€€€€™½È½±‘}­•ä¥¸Í½ÉÑ•¡ÍÑ…ÑÌ¥lè±•¸¡ÍÑ…ÑÌ¤€´€ÈÀÀÀÁtè(€€€€€€€€€€€€€€€ÍÑ…ÑÌ¹Á½À¡½±‘}­•ä°9½¹”¤(()1%9}5MM}UM}Q=I%L€ôì(€€€€‰‰¥¹‘¥¹œˆ°(€€€€‰¡•­¥¸ˆ°(€€€€‰½Ù•É‘Õ”ˆ°(€€€€‰Í½Ìˆ°(€€€€‰Í½Í}…¹•°ˆ°(€€€€‰Í½Í}•Í…±…Ñ¥½¸ˆ°(€€€€‰Íµ…ÉÑ}É•µ¥¹‘•Èˆ°(€€€€‰Õ…É‘¥…¹}ÍÕµµ…Éäˆ°)ô(()‘•˜É•½É‘}±¥¹•}µ•ÍÍ…•}ÕÍ…” (€€€ÍÑ…Ñ”è‘¥Ğ°(€€€€¨°(€€€…Ñ•½ÉäèÍÑÈ°(€€€½İ¹•É}±¥¹•}ÕÍ•É}¥èÍÑÈ°(€€€É•¥Á¥•¹Ñ}½Õ¹Ğè¥¹Ğ°(€€€•Ù•¹Ñ}¥èÍÑÈ°(€€€Í•¹Ñ}…Ğè‘…Ñ•Ñ¥µ”°(¤€´ø‘¥Ğè(€€€€ˆˆ‰%‘•µÁ½Ñ•¹Ñ±äÉ•½É‘•±¥Ù•É•1%9É•¥Á¥•¹ĞÕ¹¥ÑÌ¸ˆˆˆ(€€€…Ñ•½Éä€ôÍÑÈ¡…Ñ•½Éä½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€¥˜…Ñ•½Éä¹½Ğ¥¸1%9}5MM}UM}Q=I%Lè(€€€€€€€É…¥Í”Y…±Õ•ÉÉ½È ‰¥¹Ù…±¥1%9µ•ÍÍ…”ÕÍ…”…Ñ•½Éäˆ¤(€€€Õ¹¥ÑÌ€ôµ…à À°¥¹Ğ¡É•¥Á¥•¹Ñ}½Õ¹Ğ½È€À¤¤(€€€¥˜Õ¹¥ÑÌ€ğô€Àè(€€€€€€€É•ÑÕÉ¸ì‰É•½É‘•ˆè…±Í”°€‰Õ¹¥ÑÌˆè€Áô(€€€½İ¹•È€ôÍÑÈ¡½İ¹•É}±¥¹•}ÕÍ•É}¥½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€•Ù•¹Ñ}¥€ôÍÑÈ¡•Ù•¹Ñ}¥½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€¥˜¹½Ğ½İ¹•È½È¹½Ğ•Ù•¹Ñ}¥è(€€€€€€€É…¥Í”Y…±Õ•ÉÉ½È ‰½İ¹•É}±¥¹•}ÕÍ•É}¥…¹•Ù•¹Ñ}¥…É”É•ÅÕ¥É•ˆ¤(€€€±•‘•È€ôÍÑ…Ñ”¹Í•Ñ‘•™…Õ±Ğ ‰±¥¹•}µ•ÍÍ…•}ÕÍ…”ˆ°mt¤(€€€­•ä€ô˜‰í…Ñ•½Éåôéí•Ù•¹Ñ}¥‘ôˆ(€€€•á¥ÍÑ¥¹œ€ô¹•áĞ ¡É½Ü™½ÈÉ½Ü¥¸±•‘•È¥˜É½Ü¹•Ğ ‰­•äˆ¤€ôô­•ä¤°9½¹”¤(€€€¥˜•á¥ÍÑ¥¹œè(€€€€€€€É•ÑÕÉ¸ì¨©•á¥ÍÑ¥¹œ°€‰É•½É‘•ˆè…±Í”°€‰¥‘•µÁ½Ñ•¹ĞˆèQÉÕ•ô(€€€É½Ü€ôì(€€€€€€€€‰­•äˆè­•ä°(€€€€€€€€‰…Ñ•½Éäˆè…Ñ•½Éä°(€€€€€€€€‰½İ¹•É}±¥¹•}ÕÍ•É}¥ˆè½İ¹•È°(€€€€€€€€‰É•¥Á¥•¹Ñ}½Õ¹ĞˆèÕ¹¥ÑÌ°(€€€€€€€€‰Õ¹¥ÑÌˆèÕ¹¥ÑÌ°(€€€€€€€€‰•Ù•¹Ñ}¥ˆè•Ù•¹Ñ}¥°(€€€€€€€€‰Í•¹Ñ}…ĞˆèÍ•¹Ñ}…Ğ¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤°(€€€ô(€€€±•‘•È¹…ÁÁ•¹¡É½Ü¤(€€€ÍÑ…Ñ•l‰±¥¹•}µ•ÍÍ…•}ÕÍ…”‰t€ô±•‘•Él´ÄÀÀÀÀét(€€€É•ÑÕÉ¸ì¨©É½Ü°€‰É•½É‘•ˆèQÉÕ”°€‰¥‘•µÁ½Ñ•¹Ğˆè…±Í•ô(()‘•˜±¥¹•}ÁÕÍ¡}‰Õ‘•Ñ}‘•¥Í¥½¸ (€€€ÍÑ…Ñ”è‘¥Ğ°(€€€€¨°(€€€½İ¹•É}±¥¹•}ÕÍ•É}¥èÍÑÈ°(€€€É•ÅÕ•ÍÑ•‘}Õ¹¥ÑÌè¥¹Ğ°(€€€¹½Üè‘…Ñ•Ñ¥µ”°(€€€µ½¹Ñ¡±å}¡…É‘}…Àè¥¹Ğ°(€€€µ•µ‰•É}‘…¥±å}¡…É‘}…Àè¥¹Ğ°(€€€•µ•É•¹äè‰½½°€ô…±Í”°(¤€´ø‘¥Ğè(€€€€ˆˆ‰ÁÁ±äÁÉ”µÍ•¹¡…É…ÁÌİ¡¥±”É•Ñ…¥¹¥¹œ½¹”ÁÉ¥µ…ÉäM=L‘•±¥Ù•Éä¸ˆˆˆ(€€€½İ¹•È€ôÍÑÈ¡½İ¹•É}±¥¹•}ÕÍ•É}¥½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€É•ÅÕ•ÍÑ•€ôµ…à À°¥¹Ğ¡É•ÅÕ•ÍÑ•‘}Õ¹¥ÑÌ½È€À¤¤(€€€µ½¹Ñ¡±å}…À€ôµ…à À°¥¹Ğ¡µ½¹Ñ¡±å}¡…É‘}…À½È€À¤¤(€€€‘…¥±å}…À€ôµ…à À°¥¹Ğ¡µ•µ‰•É}‘…¥±å}¡…É‘}…À½È€À¤¤(€€€µ½¹Ñ¡}ÁÉ•™¥à€ô¹½Ü¹ÍÑÉ™Ñ¥µ” ˆ•d´•´´ˆ¤(€€€‘…å}ÁÉ•™¥à€ô¹½Ü¹ÍÑÉ™Ñ¥µ” ˆ•d´•´´•ˆ¤(€€€É½İÌ€ôÍÑ…Ñ”¹•Ğ ‰±¥¹•}µ•ÍÍ…•}ÕÍ…”ˆ¤½Èmt(€€€µ½¹Ñ¡±å}ÕÍ•€ôÍÕ´ (€€€€€€€µ…à À°¥¹Ğ¡É½Ü¹•Ğ ‰Õ¹¥ÑÌˆ¤½ÈÉ½Ü¹•Ğ ‰É•¥Á¥•¹Ñ}½Õ¹Ğˆ¤½È€À¤¤(€€€€€€€™½ÈÉ½Ü¥¸É½İÌ(€€€€€€€¥˜ÍÑÈ¡É½Ü¹•Ğ ‰Í•¹Ñ}…Ğˆ¤½È€ˆˆ¤¹ÍÑ…ÉÑÍİ¥Ñ ¡µ½¹Ñ¡}ÁÉ•™¥à¤(€€€€¤(€€€µ•µ‰•É}‘…¥±å}ÕÍ•€ôÍÕ´ (€€€€€€€µ…à À°¥¹Ğ¡É½Ü¹•Ğ ‰Õ¹¥ÑÌˆ¤½ÈÉ½Ü¹•Ğ ‰É•¥Á¥•¹Ñ}½Õ¹Ğˆ¤½È€À¤¤(€€€€€€€™½ÈÉ½Ü¥¸É½İÌ(€€€€€€€¥˜ÍÑÈ¡É½Ü¹•Ğ ‰½İ¹•É}±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¤€ôô½İ¹•È(€€€€€€€…¹ÍÑÈ¡É½Ü¹•Ğ ‰Í•¹Ñ}…Ğˆ¤½È€ˆˆ¤¹ÍÑ…ÉÑÍİ¥Ñ ¡‘…å}ÁÉ•™¥à¤(€€€€¤(€€€µ½¹Ñ¡±å}É•µ…¥¹¥¹œ€ôµ…à À°µ½¹Ñ¡±å}…À€´µ½¹Ñ¡±å}ÕÍ•¤(€€€‘…¥±å}É•µ…¥¹¥¹œ€ôµ…à À°‘…¥±å}…À€´µ•µ‰•É}‘…¥±å}ÕÍ•¤(€€€…±±½İ•‘}Õ¹¥ÑÌ€ôµ¥¸¡É•ÅÕ•ÍÑ•°µ½¹Ñ¡±å}É•µ…¥¹¥¹œ°‘…¥±å}É•µ…¥¹¥¹œ¤(€€€É•…Í½¸€ô9½¹”(€€€¥˜…±±½İ•‘}Õ¹¥ÑÌ€ğÉ•ÅÕ•ÍÑ•è(€€€€€€€É•…Í½¸€ô€ (€€€€€€€€€€€€‰µ½¹Ñ¡±å}¡…É‘}…Àˆ(€€€€€€€€€€€¥˜µ½¹Ñ¡±å}É•µ…¥¹¥¹œ€ğô‘…¥±å}É•µ…¥¹¥¹œ(€€€€€€€€€€€•±Í”€‰µ•µ‰•É}‘…¥±å}¡…É‘}…Àˆ(€€€€€€€€¤(€€€¥˜•µ•É•¹ä…¹É•ÅÕ•ÍÑ•€ø€À…¹…±±½İ•‘}Õ¹¥ÑÌ€ğ€Äè(€€€€€€€…±±½İ•‘}Õ¹¥ÑÌ€ô€Ä(€€€€€€€É•…Í½¸€ô€‰•µ•É•¹å}ÁÉ¥µ…Éå}½¹±äˆ(€€€É•ÑÕÉ¸ì(€€€€€€€€‰…±±½İ•ˆè…±±½İ•‘}Õ¹¥ÑÌ€ø€À½ÈÉ•ÅÕ•ÍÑ•€ôô€À°(€€€€€€€€‰É•…Í½¸ˆèÉ•…Í½¸°(€€€€€€€€‰É•ÅÕ•ÍÑ•‘}Õ¹¥ÑÌˆèÉ•ÅÕ•ÍÑ•°(€€€€€€€€‰…±±½İ•‘}Õ¹¥ÑÌˆè…±±½İ•‘}Õ¹¥ÑÌ°(€€€€€€€€‰µ½¹Ñ¡±å}ÕÍ•ˆèµ½¹Ñ¡±å}ÕÍ•°(€€€€€€€€‰µ½¹Ñ¡±å}¡…É‘}…Àˆèµ½¹Ñ¡±å}…À°(€€€€€€€€‰µ•µ‰•É}‘…¥±å}ÕÍ•ˆèµ•µ‰•É}‘…¥±å}ÕÍ•°(€€€€€€€€‰µ•µ‰•É}‘…¥±å}¡…É‘}…Àˆè‘…¥±å}…À°(€€€ô(()‘•˜µ½¹Ñ¡±å}±¥¹•}µ•ÍÍ…•}ÕÍ…”¡ÍÑ…Ñ”è‘¥Ğ°å•…É}µ½¹Ñ èÍÑÈ°ÅÕ½Ñ„è¥¹Ğ°¹½Üè‘…Ñ•Ñ¥µ”¤€´ø‘¥Ğè(€€€€ˆˆ‰É•…Ñ”‘•±¥Ù•É•É•¥Á¥•¹ĞÕ¹¥ÑÌ™½ÈÑ¡”É•ÅÕ•ÍÑ•…±•¹‘…Èµ½¹Ñ ¸ˆˆˆ(€€€…Ñ•½Éå}Ñ½Ñ…±Ì€ôí­•äè€À™½È­•ä¥¸Í½ÉÑ•¡1%9}5MM}UM}Q=I%L¥ô(€€€µ•µ‰•É}µ…À€ôíô(€€€É½İÌ€ômt(€€€™½ÈÉ½Ü¥¸ÍÑ…Ñ”¹•Ğ ‰±¥¹•}µ•ÍÍ…•}ÕÍ…”ˆ¤½Èmtè(€€€€€€€¥˜¹½ĞÍÑÈ¡É½Ü¹•Ğ ‰Í•¹Ñ}…Ğˆ¤½È€ˆˆ¤¹ÍÑ…ÉÑÍİ¥Ñ ¡˜‰íå•…É}µ½¹Ñ¡ô´ˆ¤è(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€Õ¹¥ÑÌ€ôµ…à À°¥¹Ğ¡É½Ü¹•Ğ ‰Õ¹¥ÑÌˆ¤½ÈÉ½Ü¹•Ğ ‰É•¥Á¥•¹Ñ}½Õ¹Ğˆ¤½È€À¤¤(€€€€€€€¥˜Õ¹¥ÑÌ€ğô€Àè(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€É½İÌ¹…ÁÁ•¹¡É½Ü¤(€€€€€€€…Ñ•½Éä€ôÍÑÈ¡É½Ü¹•Ğ ‰…Ñ•½Éäˆ¤½È€ˆˆ¤(€€€€€€€¥˜…Ñ•½Éä¥¸…Ñ•½Éå}Ñ½Ñ…±Ìè(€€€€€€€€€€€…Ñ•½Éå}Ñ½Ñ…±Ím…Ñ•½Éåt€¬ôÕ¹¥ÑÌ(€€€€€€€½İ¹•È€ôÍÑÈ¡É½Ü¹•Ğ ‰½İ¹•É}±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¤(€€€€€€€µ•µ‰•É}µ…Ám½İ¹•Ét€ôµ•µ‰•É}µ…À¹•Ğ¡½İ¹•È°€À¤€¬Õ¹¥ÑÌ(€€€ÕÍ•€ôÍÕ´¡…Ñ•½Éå}Ñ½Ñ…±Ì¹Ù…±Õ•Ì ¤¤(€€€ÑÉäè(€€€€€€€µ½¹Ñ¡}‘…åÌ€ô…±•¹‘…È¹µ½¹Ñ¡É…¹”¡¹½Ü¹å•…È°¹½Ü¹µ½¹Ñ ¥lÅt(€€€•á•ÁĞá•ÁÑ¥½¸è(€€€€€€€µ½¹Ñ¡}‘…åÌ€ô€ÌÀ(€€€•±…ÁÍ•‘}‘…åÌ€ôµ…à Ä°¹½Ü¹‘…ä¤(€€€ÁÉ½©•Ñ•€ô¥¹Ğ¡µ…Ñ ¹•¥°¡ÕÍ•€¨µ½¹Ñ¡}‘…åÌ€¼•±…ÁÍ•‘}‘…åÌ¤¤(€€€ÅÕ½Ñ„€ôµ…à À°¥¹Ğ¡ÅÕ½Ñ„½È€À¤¤(€€€É…Ñ¥¼€ô€¡ÕÍ•€¼ÅÕ½Ñ„¤¥˜ÅÕ½Ñ„•±Í”€À(€€€…±•ÉĞ€ô€‰É¥Ñ¥…±|äÀˆ¥˜ÅÕ½Ñ„…¹É…Ñ¥¼€øô€À¸ä•±Í”€ (€€€€€€€€‰İ…É¹¥¹|ÜÀˆ¥˜ÅÕ½Ñ„…¹É…Ñ¥¼€øô€À¸Ü•±Í”€‰¹½Éµ…°ˆ(€€€€¤(€€€µ•µ‰•ÉÌ€ôl(€€€€€€€ì‰±¥¹•}ÕÍ•É}¥ˆèÕ¥‘lèÙt€¬€ˆ¸¸¸ˆ€¬Õ¥‘l´Ğét¥˜±•¸¡Õ¥¤€ø€ÄÀ•±Í”Õ¥°€‰Õ¹¥ÑÌˆèÕ¹¥ÑÍô(€€€€€€€™½ÈÕ¥°Õ¹¥ÑÌ¥¸Í½ÉÑ•¡µ•µ‰•É}µ…À¹¥Ñ•µÌ ¤°­•äõ±…µ‰‘„¥Ñ•´è€ µ¥Ñ•µlÅt°¥Ñ•µlÁt¤¤(€€€t(€€€É•ÑÕÉ¸ì(€€€€€€€€‰å•…É}µ½¹Ñ ˆèå•…É}µ½¹Ñ °(€€€€€€€€‰ÅÕ½Ñ„ˆèÅÕ½Ñ„°(€€€€€€€€‰ÕÍ•‘}Õ¹¥ÑÌˆèÕÍ•°(€€€€€€€€‰É•µ…¥¹¥¹}Õ¹¥ÑÌˆèµ…à À°ÅÕ½Ñ„€´ÕÍ•¤¥˜ÅÕ½Ñ„•±Í”9½¹”°(€€€€€€€€‰ÕÍ…•}Á•É•¹ĞˆèÉ½Õ¹¡É…Ñ¥¼€¨€ÄÀÀ°€Ä¤¥˜ÅÕ½Ñ„•±Í”9½¹”°(€€€€€€€€‰ÁÉ½©•Ñ•‘}Õ¹¥ÑÌˆèÁÉ½©•Ñ•°(€€€€€€€€‰…±•ÉÑ}±•Ù•°ˆè…±•ÉĞ°(€€€€€€€€‰…Ñ•½Éå}Ñ½Ñ…±Ìˆè…Ñ•½Éå}Ñ½Ñ…±Ì°(€€€€€€€€‰µ•µ‰•É}Ñ½Ñ…±Ìˆèµ•µ‰•ÉÌ°(€€€€€€€€‰™…±Í•}…±…Éµ}Õ¹¥ÑÌˆè…Ñ•½Éå}Ñ½Ñ…±Íl‰Í½Í}…¹•°‰t°(€€€€€€€€‰É•½É‘Ìˆè±•¸¡É½İÌ¤°(€€€ô(()‘•˜}±•…É}ÁÕÍ¡}‘•±¥Ù•Éå}™…¥±ÕÉ”¡É•¥Á¥•¹Ğ°‘•±¥Ù•Éå}­•ä¤è(€€€…ÑÑ•µÁÑÌ€ô‘¥Ğ¡É•¥Á¥•¹Ğ¹•Ğ ‰ÁÕÍ¡}‘•±¥Ù•Éå}…ÑÑ•µÁÑÌˆ¤½Èíô¤(€€€…ÑÑ•µÁÑÌ¹Á½À¡‘•±¥Ù•Éå}­•ä°9½¹”¤(€€€¥˜…ÑÑ•µÁÑÌè(€€€€€€€É•¥Á¥•¹Ñl‰ÁÕÍ¡}‘•±¥Ù•Éå}…ÑÑ•µÁÑÌ‰t€ô…ÑÑ•µÁÑÌ(€€€•±Í”è(€€€€€€€É•¥Á¥•¹Ğ¹Á½À ‰ÁÕÍ¡}‘•±¥Ù•Éå}…ÑÑ•µÁÑÌˆ°9½¹”¤(()‘•˜}É•½É‘}±…Õ¹¡}‘•±¥Ù•Éä¡ÍÑ…Ñ”°‘•±¥Ù•Éå}­•ä°­¥¹°Ñ…É•Ğ°ÍÑ…ÑÕÌ¤è(€€€±•‘•È€ôÍÑ…Ñ”¹Í•Ñ‘•™…Õ±Ğ ‰±…Õ¹¡}‘•±¥Ù•Éå}•Ù•¹ÑÌˆ°íô¤(€€€±•‘•É}­•ä€ô˜‰í­¥¹‘ôéíÑ…É•Ñôéí‘•±¥Ù•Éå}­•åôˆ(€€€•Ù•¹Ğ€ô±•‘•È¹Í•Ñ‘•™…Õ±Ğ¡±•‘•É}­•ä°ì(€€€€€€€€‰­¥¹ˆèÍÑÈ¡­¥¹¤°(€€€€€€€€‰Ñ…É•ĞˆèÍÑÈ¡Ñ…É•Ğ¤°(€€€€€€€€‰•áÁ•Ñ•ˆèQÉÕ”°(€€€€€€€€‰Í•¹Ñ}½Õ¹Ğˆè€À°(€€€€€€€€‰™…¥±•ˆè…±Í”°(€€€ô¤(€€€¥˜ÍÑ…ÑÕÌ€ôô€‰Í•¹Ğˆè(€€€€€€€•Ù•¹Ñl‰Í•¹Ñ}½Õ¹Ğ‰t€ô¥¹Ğ¡•Ù•¹Ğ¹•Ğ ‰Í•¹Ñ}½Õ¹Ğˆ¤½È€À¤€¬€Ä(€€€•±¥˜ÍÑ…ÑÕÌ€ôô€‰™…¥±•ˆè(€€€€€€€•Ù•¹Ñl‰™…¥±•‰t€ôQÉÕ”(€€€•Ù•¹Ñl‰ÕÁ‘…Ñ•‘}…Ğ‰t€ô‘…Ñ•Ñ¥µ”¹¹½Ü ¤¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤(€€€É•ÑÕÉ¸•Ù•¹Ğ(()‘•˜}É•½É‘}Í¡•‘Õ±•‘}ÁÕÍ¡}™…¥±ÕÉ” (€€€ÍÑ…Ñ”°(€€€É•¥Á¥•¹Ğ°(€€€‘•±¥Ù•Éå}­•ä°(€€€­¥¹°(€€€±¥¹•}ÕÍ•É}¥°(€€€µ•ÍÍ…”°(€€€•áŒ°(€€€¹½Ü°(¤è(€€€™…¥±ÕÉ”€ôÉ•½É‘}ÁÕÍ¡}™…¥±ÕÉ”¡É•¥Á¥•¹Ğ°‘•±¥Ù•Éå}­•ä°•áŒ°¹½Ü¤(€€€}É•½É‘}±…Õ¹¡}‘•±¥Ù•Éä (€€€€€€€ÍÑ…Ñ”°‘•±¥Ù•Éå}­•ä°­¥¹°±¥¹•}ÕÍ•É}¥°€‰™…¥±•ˆ(€€€€¤(€€€…ÁÁ•¹‘}¹½Ñ¥™¥…Ñ¥½¹}±½œ (€€€€€€€ÍÑ…Ñ”°(€€€€€€€­¥¹°(€€€€€€€±¥¹•}ÕÍ•É}¥°(€€€€€€€™…¥±ÕÉ•l‰ÍÑ…ÑÕÌ‰t°(€€€€€€€µ•ÍÍ…”°(€€€€€€€ÍÑÈ¡•áŒ¤°(€€€€¤(€€€É•ÑÕÉ¸™…¥±ÕÉ”(()‘•˜±½}¹½Ñ¥™¥…Ñ¥½¸¡‘…Ñ…}™¥±”°­¥¹°±¥¹•}ÕÍ•É}¥°ÍÑ…ÑÕÌ°µ•ÍÍ…”°‘•Ñ…¥°õ9½¹”¤è(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€…ÁÁ•¹‘}¹½Ñ¥™¥…Ñ¥½¹}±½œ¡ÍÑ…Ñ”°­¥¹°±¥¹•}ÕÍ•É}¥°ÍÑ…ÑÕÌ°µ•ÍÍ…”°‘•Ñ…¥°¤(€€€Í…Ù•}ÍÑ…Ñ”¡‘…Ñ…}™¥±”°ÍÑ…Ñ”¤(()‘•˜Í•¹‘}‘Õ•}É•µ¥¹‘•ÉÌ¡½¹™¥œ¤è(€€€Ñ½­•¸€ô½¹™¥œ¹•Ğ ‰1%9}!991}MM}Q=-8ˆ¤½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}!991}MM}Q=-8ˆ°€ˆˆ¤(€€€¥˜¹½ĞÑ½­•¸è(€€€€€€€É•ÑÕÉ¸ì‰Í•¹Ğˆè€À°€‰Í­¥ÁÁ•ˆè€À°€‰•ÉÉ½Èˆè€‰1%9}!991}MM}Q=-8¥Ì¹½ĞÍ•Ğ‰ô°€ĞÀÀ((€€€¹½Ü€ôÕÉÉ•¹Ñ}…ÁÁ}Ñ¥µ”¡½¹™¥œ¤(€€€Í•¹‘•È€ô½¹™¥œ¹•Ğ ‰1%9}AUM!}M9Hˆ¤½È±¥¹•}ÁÕÍ¡}µ•ÍÍ…”(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡½¹™¥l‰Q}%1‰t¤(€€€Í•¹Ğ€ô€À(€€€Í­¥ÁÁ•€ô€À(€€€É•ÍÕ±ÑÌ€ômt(€€€ÍåÍÑ•µ}•ÉÉ½È€ô…±Í”(€€€™½ÈÁÉ½™¥±”¥¸€¡ÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ¤½Èíô¤¹Ù…±Õ•Ì ¤è(€€€€€€€½İ¹•É}¥€ôÍÑÈ¡ÁÉ½™¥±”¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€•Ù•¹Ğ€ôÁÉ½™¥±”¹•Ğ ‰…Ñ¥Ù•}½Ù•É‘Õ•}•Ù•¹Ğˆ¤(€€€€€€€¥˜¹½Ğ½İ¹•É}¥½È¹½Ğ¥Í¥¹ÍÑ…¹”¡•Ù•¹Ğ°‘¥Ğ¤½È•Ù•¹Ğ¹•Ğ ‰É•Í½±Ù•‘}…Ğˆ¤è(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¥˜ÁÉ½™¥±”¹•Ğ ‰µ•µ‰•ÉÍ¡¥Á}Á…ÕÍ•ˆ¤½È¹½Ğµ•µ‰•ÉÍ¡¥Á}…•ÍÍ}…Ñ¥Ù”¡ÁÉ½™¥±”°¹½Ü¤è(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¥˜ÁÉ½™¥±•}¥Í}Ñ½‘…å}¡•­•¡ÁÉ½™¥±”°½¹™¥œõ½¹™¥œ°¹½Üõ¹½Ü¤è(€€€€€€€€€€€•Ù•¹Ñl‰É•Í½±Ù•‘}…Ğ‰t€ô¹½Ü¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤(€€€€€€€€€€€•Ù•¹Ñl‰ÍÑ…ÑÕÌ‰t€ô€‰¡•­•‘}¥¸ˆ(€€€€€€€€€€€ÁÉ½™¥±•l‰±…ÍÑ}½Ù•É‘Õ•}•Ù•¹Ğ‰t€ô½Áä¹‘••Á½Áä¡•Ù•¹Ğ¤(€€€€€€€€€€€ÁÉ½™¥±•l‰…Ñ¥Ù•}½Ù•É‘Õ•}•Ù•¹Ğ‰t€ô9½¹”(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€ÍÑ…ÉÑ•‘}…Ğ€ôÁ…ÉÍ•}‘…Ñ•Ñ¥µ”¡•Ù•¹Ğ¹•Ğ ‰ÍÑ…ÉÑ•‘}…Ğˆ¤¤(€€€€€€€¥˜¹½ĞÍÑ…ÉÑ•‘}…Ğè(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¥˜¹½Ü¹Ñé¥¹™¼¥Ì9½¹”…¹ÍÑ…ÉÑ•‘}…Ğ¹Ñé¥¹™¼¥Ì¹½Ğ9½¹”è(€€€€€€€€€€€ÍÑ…ÉÑ•‘}…Ğ€ôÍÑ…ÉÑ•‘}…Ğ¹É•Á±…”¡Ñé¥¹™¼õ9½¹”¤(€€€€€€€•±¥˜¹½Ü¹Ñé¥¹™¼¥Ì¹½Ğ9½¹”…¹ÍÑ…ÉÑ•‘}…Ğ¹Ñé¥¹™¼¥Ì9½¹”è(€€€€€€€€€€€ÍÑ…ÉÑ•‘}…Ğ€ôÍÑ…ÉÑ•‘}…Ğ¹É•Á±…”¡Ñé¥¹™¼õ¹½Ü¹Ñé¥¹™¼¤(€€€€€€€•±…ÁÍ•‘}µ¥¹ÕÑ•Ì€ôµ…à À°€¡¹½Ü€´ÍÑ…ÉÑ•‘}…Ğ¤¹Ñ½Ñ…±}Í•½¹‘Ì ¤€¼€ØÀ¤(€€€€€€€É…•}µ¥¹ÕÑ•Ì€ô¹½Éµ…±¥é•}É…•}¡½ÕÉÌ (€€€€€€€€€€€ÁÉ½™¥±”¹•Ğ ‰É…•}¡½ÕÉÌˆ¤(€€€€€€€€¤€¨€ØÀ(€€€€€€€•±…ÁÍ•‘}…™Ñ•É}É…”€ôµ…à À°•±…ÁÍ•‘}µ¥¹ÕÑ•Ì€´É…•}µ¥¹ÕÑ•Ì¤(€€€€€€€İ…¥Ñ}µ¥¹ÕÑ•Ì€ô¹½Éµ…±¥é•}½Ù•É‘Õ•}İ…¥Ñ}µ¥¹ÕÑ•Ì (€€€€€€€€€€€ÁÉ½™¥±”¹•Ğ ‰½Ù•É‘Õ•}İ…¥Ñ}µ¥¹ÕÑ•Ìˆ¤(€€€€€€€€¤(€€€€€€€±½…Ñ¥½¸€ôÁÉ½™¥±”¹•Ğ ‰±½…Ñ¥½¸ˆ¤½Èíô(€€€€€€€±½…Ñ¥½¹}±¥¹¬€ô€ˆˆ(€€€€€€€¥˜ÁÉ½™¥±”¹•Ğ ‰…ÑÑ…¡}±½…Ñ¥½¹}½¹}…±•ÉĞˆ¤…¹±½…Ñ¥½¸¹•Ğ ‰±…Ñ¥ÑÕ‘”ˆ¤…¹±½…Ñ¥½¸¹•Ğ ‰±½¹¥ÑÕ‘”ˆ¤è(€€€€€€€€€€€±½…Ñ¥½¹}±¥¹¬€ô˜‰q»šr–ú3’ö7ö»¾òi¡ÑÑÁÌè¼½İİÜ¹½½±”¹½´½µ…ÁÌıÄõí±½…Ñ¥½¹l±…Ñ¥ÑÕ‘”uô±í±½…Ñ¥½¹l±½¹¥ÑÕ‘”uôˆ((€€€€€€€€Œƒšr³’êëšZóš>C¦K–ú3šr–’k–7šRÛ–"Ã’âš²‡~·š>C¦K¾òo’â7–nƒ–’k–/š¾?š^—šfšº×–îë®/¦7¢’’ê/’îÛ(€€€€€€€¥˜•±…ÁÍ•‘}µ¥¹ÕÑ•Ì€øôÉ…•}µ¥¹ÕÑ•Ì…¹¹½Ğ•Ù•¹Ğ¹•Ğ ‰Í•±™}™½±±½İÕÁ}Í•¹Ñ}…Ğˆ¤è(€€€€€€€€€€€Í•±™}µ•ÍÍ…”€ô€ (€€€€€€€€€€€€€€€˜‹Šv“¾â<ƒ¦
šÊKšRÛ–"Ã’öƒj–æÏ–º'–n{–‚Åq¸ˆ(€€€€€€€€€€€€€€€˜‹¢®/¦î{’â’â/3š"G–æÏ–º'7¾òo¢.—š>C¦K–ú0íİ…¥Ñ}µ¥¹ÕÑ•Íôƒ–"¦Bc’î7šr«–n{š'¾ò0ˆ(€€€€€€€€€€€€€€€€‹ÎïÖÇšr¦k~—²³’â¦‚’ö7–º#¢¶ß’êëˆ(€€€€€€€€€€€€¤(€€€€€€€€€€€Í•±™}­•ä€ô˜‰í•Ù•¹Ğ¹•Ğ •Ù•¹Ñ}¥œ¥ôéÍ•±˜µ™½±±½İÕÀˆ(€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€É•ÍÕ±Ğ€ôÍ•¹‘•È¡Ñ½­•¸°½İ¹•É}¥°Í•±™}µ•ÍÍ…”¤(€€€€€€€€€€€€€€€•Ù•¹Ñl‰Í•±™}™½±±½İÕÁ}Í•¹Ñ}…Ğ‰t€ô¹½Ü¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤(€€€€€€€€€€€€€€€…ÁÁ•¹‘}¹½Ñ¥™¥…Ñ¥½¹}±½œ (€€€€€€€€€€€€€€€€€€€ÍÑ…Ñ”°€‰½Ù•É‘Õ•}Í•±™}™½±±½İÕÀˆ°½İ¹•É}¥°€‰Í•¹Ğˆ°(€€€€€€€€€€€€€€€€€€€Í•±™}µ•ÍÍ…”°©Í½¸¹‘ÕµÁÌ¡É•ÍÕ±Ğ°•¹ÍÕÉ•}…Í¥¤õ…±Í”¤°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€É•½É‘}±¥¹•}µ•ÍÍ…•}ÕÍ…” (€€€€€€€€€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€€€€€€€€€…Ñ•½Éäô‰½Ù•É‘Õ”ˆ°(€€€€€€€€€€€€€€€€€€€½İ¹•É}±¥¹•}ÕÍ•É}¥õ½İ¹•É}¥°(€€€€€€€€€€€€€€€€€€€É•¥Á¥•¹Ñ}½Õ¹ĞôÄ°(€€€€€€€€€€€€€€€€€€€•Ù•¹Ñ}¥õÍ•±™}­•ä°(€€€€€€€€€€€€€€€€€€€Í•¹Ñ}…Ğõ¹½Ü°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€Í•¹Ğ€¬ô€Ä(€€€€€€€€€€€€€€€É•ÍÕ±ÑÌ¹…ÁÁ•¹¡ì‰±¥¹•}ÕÍ•É}¥ˆè½İ¹•É}¥°€‰ÍÑ…”ˆè€‰Í•±™}™½±±½İÕÀˆ°€‰É•ÍÕ±ĞˆèÉ•ÍÕ±Ñô¤(€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€€€€€…ÁÁ•¹‘}¹½Ñ¥™¥…Ñ¥½¹}±½œ (€€€€€€€€€€€€€€€€€€€ÍÑ…Ñ”°€‰½Ù•É‘Õ•}Í•±™}™½±±½İÕÀˆ°½İ¹•É}¥°€‰™…¥±•ˆ°(€€€€€€€€€€€€€€€€€€€Í•±™}µ•ÍÍ…”°ÍÑÈ¡•áŒ¤°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€€€€€É•ÍÕ±ÑÌ¹…ÁÁ•¹¡ì‰±¥¹•}ÕÍ•É}¥ˆè½İ¹•É}¥°€‰ÍÑ…”ˆè€‰Í•±™}™½±±½İÕÀˆ°€‰•ÉÉ½ÈˆèÍÑÈ¡•áŒ¥ô¤((€€€€€€€€Œ€Üääƒ–º#¢¶ßú“’î7šb¿¦ãR£¦k¦O¾òo–r£²³’â¦‚’ö7–"Ãšršf¦k~—’âš²‡¾ò3’â7–>[’î’êë¦‚’ö7¦k~—(€€€€€€€¥˜•±…ÁÍ•‘}…™Ñ•É}É…”€øôİ…¥Ñ}µ¥¹ÕÑ•Ìè(€€€€€€€€€€€ÉÕ±•Ì€ôÁ±…¹}ÉÕ±•Ì¡ÁÉ½™¥±”°¹½Ü¤(€€€€€€€€€€€É½ÕÁ}±¥µ¥Ğ€ô¥¹Ğ¡ÉÕ±•Ì¹•Ğ ‰Õ…É‘¥…¹}É½ÕÁ}±¥µ¥Ğˆ¤½È€À¤(€€€€€€€€€€€É½ÕÁÌ€ôÍÑ…Ñ”¹•Ğ ‰Õ…É‘¥…¹}É½ÕÁÌˆ¤½Èíô(€€€€€€€€€€€¹½Ñ¥™¥•‘}É½ÕÁ}¥‘Ì€ô•Ù•¹Ğ¹Í•Ñ‘•™…Õ±Ğ ‰¹½Ñ¥™¥•‘}É½ÕÁ}¥‘Ìˆ°mt¤(€€€€€€€€€€€…Ñ¥Ù•}É½ÕÁ}¥‘Ì€ôl(€€€€€€€€€€€€€€€É½ÕÁ}¥(€€€€€€€€€€€€€€€™½ÈÉ½ÕÁ}¥¥¸€¡ÁÉ½™¥±”¹•Ğ ‰Õ…É‘¥…¹}É½ÕÁ}¥‘Ìˆ¤½Èmt¤(€€€€€€€€€€€€€€€¥˜É½ÕÁ}¥¹½Ğ¥¸¹½Ñ¥™¥•‘}É½ÕÁ}¥‘Ì(€€€€€€€€€€€€€€€…¹É½ÕÁÌ¹•Ğ¡É½ÕÁ}¥°íô¤¹•Ğ ‰½İ¹•É}±¥¹•}ÕÍ•É}¥ˆ¤€ôô½İ¹•É}¥(€€€€€€€€€€€€€€€…¹É½ÕÁÌ¹•Ğ¡É½ÕÁ}¥°íô¤¹•Ğ ‰ÍÑ…ÑÕÌˆ¤€ôô€‰…Ñ¥Ù”ˆ(€€€€€€€€€€€€€€€…¹Õ…É‘¥…¹}É½ÕÁ}ÁÉ•™•É•¹” (€€€€€€€€€€€€€€€€€€€É½ÕÁÌ¹•Ğ¡É½ÕÁ}¥¤°€‰¹½Ñ¥™å}É½ÕÁ}½¹}½Ù•É‘Õ”ˆ(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€uléÉ½ÕÁ}±¥µ¥Ñt(€€€€€€€€€€€É½ÕÁ}µ•ÍÍ…”€ô€ (€€€€€€€€€€€€€€€˜‹Šjƒ¾â?C–’Ç¢¿¦‚C¢¶›EíÁÉ½™¥±”¹•Ğ ‘¥ÍÁ±…å}¹…µ”œ¤½È€Ÿš"C–N„ôƒ–r£š>C¦K–ú0€ˆ(€€€€€€€€€€€€€€€˜‰íİ…¥Ñ}µ¥¹ÕÑ•Íôƒ–"¦Bc’î7šr«–n{–‚Ç–æÏ–º'¾ò3¢®/ú“–Ÿ–6S–*§Šë¢ª7	í±½…Ñ¥½¹}±¥¹­ôˆ(€€€€€€€€€€€€¤(€€€€€€€€€€€™½ÈÉ½ÕÁ}¥¥¸…Ñ¥Ù•}É½ÕÁ}¥‘Ìè(€€€€€€€€€€€€€€€‘•±¥Ù•Éå}­•ä€ô˜‰í•Ù•¹Ğ¹•Ğ •Ù•¹Ñ}¥œ¥ôéÉ½ÕÀéíÉ½ÕÁ}¥‘ôˆ(€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€É•ÍÕ±Ğ€ôÍ•¹‘•È¡Ñ½­•¸°É½ÕÁ}¥°É½ÕÁ}µ•ÍÍ…”¤(€€€€€€€€€€€€€€€€€€€¹½Ñ¥™¥•‘}É½ÕÁ}¥‘Ì¹…ÁÁ•¹¡É½ÕÁ}¥¤(€€€€€€€€€€€€€€€€€€€…ÁÁ•¹‘}¹½Ñ¥™¥…Ñ¥½¹}±½œ (€€€€€€€€€€€€€€€€€€€€€€€ÍÑ…Ñ”°€‰½Ù•É‘Õ•}Õ…É‘¥…¹}É½ÕÀˆ°É½ÕÁ}¥°€‰Í•¹Ğˆ°(€€€€€€€€€€€€€€€€€€€€€€€É½ÕÁ}µ•ÍÍ…”°©Í½¸¹‘ÕµÁÌ¡É•ÍÕ±Ğ°•¹ÍÕÉ•}…Í¥¤õ…±Í”¤°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€É•½É‘}±¥¹•}µ•ÍÍ…•}ÕÍ…” (€€€€€€€€€€€€€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€€€€€€€€€€€€€…Ñ•½Éäô‰½Ù•É‘Õ”ˆ°(€€€€€€€€€€€€€€€€€€€€€€€½İ¹•É}±¥¹•}ÕÍ•É}¥õ½İ¹•É}¥°(€€€€€€€€€€€€€€€€€€€€€€€É•¥Á¥•¹Ñ}½Õ¹ĞôÄ°(€€€€€€€€€€€€€€€€€€€€€€€•Ù•¹Ñ}¥õ‘•±¥Ù•Éå}­•ä°(€€€€€€€€€€€€€€€€€€€€€€€Í•¹Ñ}…Ğõ¹½Ü°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€Í•¹Ğ€¬ô€Ä(€€€€€€€€€€€€€€€€€€€É•ÍÕ±ÑÌ¹…ÁÁ•¹¡ì(€€€€€€€€€€€€€€€€€€€€€€€€‰É½ÕÁ}¥ˆèÉ½ÕÁ}¥°(€€€€€€€€€€€€€€€€€€€€€€€€‰ÍÑ…”ˆè€‰Õ…É‘¥…¹}É½ÕÀˆ°(€€€€€€€€€€€€€€€€€€€€€€€€‰É•ÍÕ±ĞˆèÉ•ÍÕ±Ğ°(€€€€€€€€€€€€€€€€€€€ô¤(€€€€€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€€€€€€€€€…ÁÁ•¹‘}¹½Ñ¥™¥…Ñ¥½¹}±½œ (€€€€€€€€€€€€€€€€€€€€€€€ÍÑ…Ñ”°€‰½Ù•É‘Õ•}Õ…É‘¥…¹}É½ÕÀˆ°É½ÕÁ}¥°€‰™…¥±•ˆ°(€€€€€€€€€€€€€€€€€€€€€€€É½ÕÁ}µ•ÍÍ…”°ÍÑÈ¡•áŒ¤°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€€€€€€€€€É•ÍÕ±ÑÌ¹…ÁÁ•¹¡ì(€€€€€€€€€€€€€€€€€€€€€€€€‰É½ÕÁ}¥ˆèÉ½ÕÁ}¥°(€€€€€€€€€€€€€€€€€€€€€€€€‰ÍÑ…”ˆè€‰Õ…É‘¥…¹}É½ÕÀˆ°(€€€€€€€€€€€€€€€€€€€€€€€€‰•ÉÉ½ÈˆèÍÑÈ¡•áŒ¤°(€€€€€€€€€€€€€€€€€€€ô¤((€€€€€€€ÕÉÉ•¹Ñ}ÍÑ…”€ô¥¹Ğ¡•Ù•¹Ğ¹•Ğ ‰Õ…É‘¥…¹}ÍÑ…”ˆ¤½È€À¤(€€€€€€€‘Õ•}ÍÑ…”€ô¹•áĞ (€€€€€€€€€€€€ (€€€€€€€€€€€€€€€ÍÑ…”(€€€€€€€€€€€€€€€™½ÈÍÑ…”¥¸€ Ä°€È°€Ì¤(€€€€€€€€€€€€€€€¥˜ÍÑ…”€øÕÉÉ•¹Ñ}ÍÑ…”(€€€€€€€€€€€€€€€…¹•±…ÁÍ•‘}…™Ñ•É}É…”€øôİ…¥Ñ}µ¥¹ÕÑ•Ì€¨ÍÑ…”(€€€€€€€€€€€€¤°(€€€€€€€€€€€9½¹”°(€€€€€€€€¤(€€€€€€€¥˜‘Õ•}ÍÑ…”¥Ì9½¹”è(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¥˜¹½ĞÍ¡½Õ±‘}¹½Ñ¥™å}ÁÉ¥Ù…Ñ•}Õ…É‘¥…¹Ì¡ÍÑ…Ñ”°ÁÉ½™¥±”¤è(€€€€€€€€€€€•Ù•¹Ñl‰Õ…É‘¥…¹}ÍÑ…”‰t€ô‘Õ•}ÍÑ…”(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€Õ…É‘¥…¹Ì€ôÉ…¹­•‘}½Ù•É‘Õ•}Õ…É‘¥…¹Ì¡ÁÉ½™¥±”¤(€€€€€€€¥˜‘Õ•}ÍÑ…”€ø±•¸¡Õ…É‘¥…¹Ì¤è(€€€€€€€€€€€•Ù•¹Ñl‰Õ…É‘¥…¹}ÍÑ…”‰t€ô‘Õ•}ÍÑ…”(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€½¹Ñ…Ğ€ôÕ…É‘¥…¹Ím‘Õ•}ÍÑ…”€´€Åt(€€€€€€€Ñ…É•Ğ€ô•Ñ}½¹Ñ…Ñ}±¥¹•}¥¡½¹Ñ…Ğ¤(€€€€€€€½¹Ñ…Ñ}¹…µ”€ôÍÑÈ¡½¹Ñ…Ğ¹•Ğ ‰¹…µ”ˆ¤½È½¹Ñ…Ğ¹•Ğ ‰É•±…Ñ¥½¹Í¡¥Àˆ¤½È˜‹²°í‘Õ•}ÍÑ…•ôƒ¦‚’ö7–º#¢¶ß’êèˆ¤(€€€€€€€½¹Ñ…Ñ}µ•ÍÍ…”€ô€ (€€€€€€€€€€€˜‹Šjƒ¾â?C²°í‘Õ•}ÍÑ…•ôƒ¦‚’ö7šr«–‚Ç–æÏ–º'¦k~—Dˆ(€€€€€€€€€€€˜‰íÁÉ½™¥±”¹•Ğ ‘¥ÍÁ±…å}¹…µ”œ¤½È€Ÿ’öƒj¢š«–>,ôƒ–r£š>C¦K–ú0€ˆ(€€€€€€€€€€€˜‰íİ…¥Ñ}µ¥¹ÕÑ•Ì€¨‘Õ•}ÍÑ…•ôƒ–"¦Bc’î7šr«–n{–‚Ç–æÏ–º'¾ò3¢®/–6S–*§Šë¢ª7ˆ(€€€€€€€€€€€˜‰í±½…Ñ¥½¹}±¥¹­ôˆ(€€€€€€€€¤(€€€€€€€‘•±¥Ù•Éå}­•ä€ô˜‰í•Ù•¹Ğ¹•Ğ •Ù•¹Ñ}¥œ¥ôéÕ…É‘¥…¸éí‘Õ•}ÍÑ…•ôéíÑ…É•Ñôˆ(€€€€€€€ÑÉäè(€€€€€€€€€€€É•ÍÕ±Ğ€ôÍ•¹‘•È¡Ñ½­•¸°Ñ…É•Ğ°½¹Ñ…Ñ}µ•ÍÍ…”¤(€€€€€€€€€€€•Ù•¹Ñl‰Õ…É‘¥…¹}ÍÑ…”‰t€ô‘Õ•}ÍÑ…”(€€€€€€€€€€€•Ù•¹Ğ¹Í•Ñ‘•™…Õ±Ğ ‰¹½Ñ¥™¥•‘}Õ…É‘¥…¹}¥‘Ìˆ°mt¤¹…ÁÁ•¹¡Ñ…É•Ğ¤(€€€€€€€€€€€…ÁÁ•¹‘}¹½Ñ¥™¥…Ñ¥½¹}±½œ (€€€€€€€€€€€€€€€ÍÑ…Ñ”°€‰½¹Ñ…Ñ}…±•ÉĞˆ°Ñ…É•Ğ°€‰Í•¹Ğˆ°(€€€€€€€€€€€€€€€½¹Ñ…Ñ}µ•ÍÍ…”°©Í½¸¹‘ÕµÁÌ¡É•ÍÕ±Ğ°•¹ÍÕÉ•}…Í¥¤õ…±Í”¤°(€€€€€€€€€€€€¤(€€€€€€€€€€€É•½É‘}±¥¹•}µ•ÍÍ…•}ÕÍ…” (€€€€€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€€€€€…Ñ•½Éäô‰½Ù•É‘Õ”ˆ°(€€€€€€€€€€€€€€€½İ¹•É}±¥¹•}ÕÍ•É}¥õ½İ¹•É}¥°(€€€€€€€€€€€€€€€É•¥Á¥•¹Ñ}½Õ¹ĞôÄ°(€€€€€€€€€€€€€€€•Ù•¹Ñ}¥õ‘•±¥Ù•Éå}­•ä°(€€€€€€€€€€€€€€€Í•¹Ñ}…Ğõ¹½Ü°(€€€€€€€€€€€€¤(€€€€€€€€€€€Í•¹Ğ€¬ô€Ä(€€€€€€€€€€€É•ÍÕ±ÑÌ¹…ÁÁ•¹¡ì(€€€€€€€€€€€€€€€€‰±¥¹•}ÕÍ•É}¥ˆèÑ…É•Ğ°(€€€€€€€€€€€€€€€€‰‘¥ÍÁ±…å}¹…µ”ˆè½¹Ñ…Ñ}¹…µ”°(€€€€€€€€€€€€€€€€‰ÍÑ…”ˆè‘Õ•}ÍÑ…”°(€€€€€€€€€€€€€€€€‰É•ÍÕ±ĞˆèÉ•ÍÕ±Ğ°(€€€€€€€€€€€ô¤(€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€…ÁÁ•¹‘}¹½Ñ¥™¥…Ñ¥½¹}±½œ (€€€€€€€€€€€€€€€ÍÑ…Ñ”°€‰½¹Ñ…Ñ}…±•ÉĞˆ°Ñ…É•Ğ°€‰™…¥±•ˆ°(€€€€€€€€€€€€€€€½¹Ñ…Ñ}µ•ÍÍ…”°ÍÑÈ¡•áŒ¤°(€€€€€€€€€€€€¤(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€É•ÍÕ±ÑÌ¹…ÁÁ•¹¡ì(€€€€€€€€€€€€€€€€‰±¥¹•}ÕÍ•É}¥ˆèÑ…É•Ğ°(€€€€€€€€€€€€€€€€‰‘¥ÍÁ±…å}¹…µ”ˆè½¹Ñ…Ñ}¹…µ”°(€€€€€€€€€€€€€€€€‰ÍÑ…”ˆè‘Õ•}ÍÑ…”°(€€€€€€€€€€€€€€€€‰•ÉÉ½ÈˆèÍÑÈ¡•áŒ¤°(€€€€€€€€€€€ô¤((€€€Í…Ù•}ÍÑ…Ñ”¡½¹™¥l‰Q}%1‰t°ÍÑ…Ñ”¤(€€€É•ÑÕÉ¸ì(€€€€€€€€‰Í•¹ĞˆèÍ•¹Ğ°(€€€€€€€€‰Í­¥ÁÁ•ˆèÍ­¥ÁÁ•°(€€€€€€€€‰É•ÍÕ±ÑÌˆèÉ•ÍÕ±ÑÌ°(€€€€€€€€‰ÍåÍÑ•µ}•ÉÉ½ÈˆèÍåÍÑ•µ}•ÉÉ½È°(€€€ô°€ÈÀÀ(()‘•˜Í•¹‘}Õ…É‘¥…¹}É½ÕÁ}‘…¥±å}ÍÕµµ…É¥•Ì¡½¹™¥œ¤è(€€€€ˆˆ‹¦ãR£¾òk–º#¢¶ßú“–.û¦ã3ú“Öš¾?š^—šFc¢š7šf¾ò3šZóšfk¦ZOš:£šJ·’î+š^—–ŞË–‚Ç¾ò?šr«–‚Ç¾ò#¦‚C¢¢·¦^s¦Z'¾ò'ˆˆˆ(€€€Ñ½­•¸€ô½¹™¥œ¹•Ğ ‰1%9}!991}MM}Q=-8ˆ¤½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}!991}MM}Q=-8ˆ°€ˆˆ¤(€€€¥˜¹½ĞÑ½­•¸è(€€€€€€€É•ÑÕÉ¸ì‰Í•¹Ğˆè€À°€‰Í­¥ÁÁ•ˆè€À°€‰•ÉÉ½Èˆè€‰1%9}!991}MM}Q=-8¥Ì¹½ĞÍ•Ğ‰ô°€ĞÀÀ((€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡½¹™¥l‰Q}%1‰t¤(€€€Í•¹‘•È€ô½¹™¥œ¹•Ğ ‰1%9}AUM!}M9Hˆ¤½È±¥¹•}ÁÕÍ¡}µ•ÍÍ…”(€€€¹½Ü€ôÕÉÉ•¹Ñ}…ÁÁ}Ñ¥µ”¡½¹™¥œ¤(€€€Ñ½‘…ä€ô¹½Ü¹ÍÑÉ™Ñ¥µ” ˆ•d´•´´•ˆ¤(€€€ÕÍ•ÉÌ€ôÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ¤½Èíô(€€€É½ÕÁÌ€ôÍÑ…Ñ”¹•Ğ ‰Õ…É‘¥…¹}É½ÕÁÌˆ¤½Èíô(€€€Í•¹Ğ€ô€À(€€€Í­¥ÁÁ•€ô€À(€€€É•ÍÕ±ÑÌ€ômt(€€€ÍåÍÑ•µ}•ÉÉ½È€ô…±Í”(€€€‘•™•ÉÉ•€ô€À(€€€µ•µ‰•É}™•Ñ¡•È€ô½¹™¥œ¹•Ğ ‰I=UA}55	I}%M}Q!Hˆ¤½È•Ñ}É½ÕÁ}µ•µ‰•É}¥‘Ì(€€€™½ÈÉ½ÕÁ}¥°É½ÕÀ¥¸±¥ÍĞ¡É½ÕÁÌ¹¥Ñ•µÌ ¤¤è(€€€€€€€¥˜¹½Ğ¥Í¥¹ÍÑ…¹”¡É½ÕÀ°‘¥Ğ¤½ÈÉ½ÕÀ¹•Ğ ‰ÍÑ…ÑÕÌˆ¤€„ô€‰…Ñ¥Ù”ˆè(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€½İ¹•È€ôÕÍ•ÉÌ¹•Ğ¡ÍÑÈ¡É½ÕÀ¹•Ğ ‰½İ¹•É}±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤¤½Èíô(€€€€€€€¥˜€ (€€€€€€€€€€€¹½ĞÕ…É‘¥…¹}É½ÕÁ}•¹Ñ¥Ñ±•µ•¹Ñ}…Ñ¥Ù”¡½İ¹•È°¹½Ü¤(€€€€€€€€¤è(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€É•ÍÕ±ÑÌ¹…ÁÁ•¹¡ì‰É½ÕÁ}¥ˆèÉ½ÕÁ}¥°€‰ÍÑ…ÑÕÌˆè€‰½İ¹•É}¹½Ñ}•±¥¥‰±”‰ô¤(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€ÁÉ•™Ì€ô¹½Éµ…±¥é•}Õ…É‘¥…¹}É½ÕÁ}ÁÉ•™•É•¹•Ì¡É½ÕÀ¹•Ğ ‰ÁÉ•™•É•¹•Ìˆ¤¤(€€€€€€€¥˜¹½ĞÁÉ•™Ì¹•Ğ ‰‘…¥±å}…‘µ¥¹}ÍÕµµ…Éäˆ¤è(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€ÍÕµµ…Éå}Ñ¥µ”€ôÍÑÈ¡ÁÉ•™Ì¹•Ğ ‰‘…¥±å}ÍÕµµ…Éå}Ñ¥µ”ˆ¤½È€ˆÈÄèÀÀˆ¤(€€€€€€€ÕÉÉ•¹Ñ}¡´€ô¹½Ü¹ÍÑÉ™Ñ¥µ” ˆ• è•4ˆ¤(€€€€€€€¥˜ÕÉÉ•¹Ñ}¡´€ğÍÕµµ…Éå}Ñ¥µ”è(€€€€€€€€€€€‘•™•ÉÉ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¥˜É½ÕÀ¹•Ğ ‰±…ÍÑ}‘…¥±å}ÍÕµµ…Éå}‘…Ñ”ˆ¤€ôôÑ½‘…äè(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€‘•±¥Ù•Éå}­•ä€ô˜‰Õ…É‘¥…¹}É½ÕÁ}‘…¥±å}ÍÕµµ…ÉäéíÑ½‘…åôéíÉ½ÕÁ}¥‘ôˆ(€€€€€€€¥˜¹½ĞÁÕÍ¡}…ÑÑ•µÁÑ}…±±½İ•¡É½ÕÀ°‘•±¥Ù•Éå}­•ä¤è(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€±…¥µ}É•ÍÕ±Ğ€ôµÕÑ…Ñ•}ÍÑ…Ñ•}…Ñ½µ¥…±±ä (€€€€€€€€€€€½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€±…µ‰‘„ÕÉÉ•¹Ñ}ÍÑ…Ñ”è}±…¥µ}Õ…É‘¥…¹}É½ÕÁ}ÍÕµµ…Éä (€€€€€€€€€€€€€€€ÕÉÉ•¹Ñ}ÍÑ…Ñ”°É½ÕÁ}¥°Ñ½‘…ä°¹½Ü(€€€€€€€€€€€€¤°(€€€€€€€€¤(€€€€€€€¥˜¹½Ğ±…¥µ}É•ÍÕ±Ğ¹•Ğ ‰±…¥µ•ˆ¤è(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€É•ÍÕ±ÑÌ¹…ÁÁ•¹¡ì‰É½ÕÁ}¥ˆèÉ½ÕÁ}¥°€‰ÍÑ…ÑÕÌˆè€‰…±É•…‘å}±…¥µ•‰ô¤(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€±…¥µ}Ñ½­•¸€ô±…¥µ}É•ÍÕ±Ñl‰±…¥µ}Ñ½­•¸‰t(€€€€€€€ÑÉäè(€€€€€€€€€€€ÕÉÉ•¹Ñ}¥‘Ì€ô9½¹”(€€€€€€€€€€€µ•µ‰•É}•ÉÉ½È€ô9½¹”(€€€€€€€€€€€™½È}…ÑÑ•µÁĞ¥¸É…¹” Ì¤è(€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€ÕÉÉ•¹Ñ}¥‘Ì€ôµ•µ‰•É}™•Ñ¡•È¡Ñ½­•¸°É½ÕÁ}¥¤(€€€€€€€€€€€€€€€€€€€¥˜ÕÉÉ•¹Ñ}¥‘Ì¥Ì¹½Ğ9½¹”è(€€€€€€€€€€€€€€€€€€€€€€€µ•µ‰•É}•ÉÉ½È€ô9½¹”(€€€€€€€€€€€€€€€€€€€€€€€‰É•…¬(€€€€€€€€€€€€€€€€€€€µ•µ‰•É}•ÉÉ½È€ôIÕ¹Ñ¥µ•ÉÉ½È ‰1%9µ•µ‰•È±¥ÍĞÕ¹…Ù…¥±…‰±”ˆ¤(€€€€€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€€€€€€€€€µ•µ‰•É}•ÉÉ½È€ô•áŒ(€€€€€€€€€€€¥˜ÕÉÉ•¹Ñ}¥‘Ì¥Ì9½¹”è(€€€€€€€€€€€€€€€µÕÑ…Ñ•}ÍÑ…Ñ•}…Ñ½µ¥…±±ä (€€€€€€€€€€€€€€€€€€€½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€€€€€±…µ‰‘„ÕÉÉ•¹Ñ}ÍÑ…Ñ”è}™¥¹¥Í¡}Õ…É‘¥…¹}É½ÕÁ}ÍÕµµ…Éä (€€€€€€€€€€€€€€€€€€€€€€€ÕÉÉ•¹Ñ}ÍÑ…Ñ”°(€€€€€€€€€€€€€€€€€€€€€€€É½ÕÁ}¥°(€€€€€€€€€€€€€€€€€€€€€€€Ñ½‘…ä°(€€€€€€€€€€€€€€€€€€€€€€€¹½Ü°(€€€€€€€€€€€€€€€€€€€€€€€±…¥µ}Ñ½­•¸õ±…¥µ}Ñ½­•¸°(€€€€€€€€€€€€€€€€€€€€€€€É•±•…Í•}½¹±äõQÉÕ”°(€€€€€€€€€€€€€€€€€€€€€€€…Õ‘¥Ñ}­¥¹ô‰Õ…É‘¥…¹}É½ÕÁ}µ•µ‰•É}É•™É•Í ˆ°(€€€€€€€€€€€€€€€€€€€€€€€…Õ‘¥Ñ}ÍÑ…ÑÕÌô‰™…¥±•ˆ°(€€€€€€€€€€€€€€€€€€€€€€€…Õ‘¥Ñ}‘•Ñ…¥°õÍÑÈ¡µ•µ‰•É}•ÉÉ½È½È€‰µ•µ‰•ÈÉ•™É•Í ™…¥±•ˆ¥lèĞÀÁt°(€€€€€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€€€€€É•ÍÕ±ÑÌ¹…ÁÁ•¹¡ì(€€€€€€€€€€€€€€€€€€€€‰É½ÕÁ}¥ˆèÉ½ÕÁ}¥°(€€€€€€€€€€€€€€€€€€€€‰ÍÑ…ÑÕÌˆè€‰µ•µ‰•É}É•™É•Í¡}™…¥±•ˆ°(€€€€€€€€€€€€€€€€€€€€‰•ÉÉ½ÈˆèÍÑÈ¡µ•µ‰•É}•ÉÉ½È½È€ˆˆ¥lèĞÀÁt°(€€€€€€€€€€€€€€€ô¤(€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€•á•ÁĞá•ÁÑ¥½¸è(€€€€€€€€€€€µÕÑ…Ñ•}ÍÑ…Ñ•}…Ñ½µ¥…±±ä (€€€€€€€€€€€€€€€½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€±…µ‰‘„ÕÉÉ•¹Ñ}ÍÑ…Ñ”è}™¥¹¥Í¡}Õ…É‘¥…¹}É½ÕÁ}ÍÕµµ…Éä (€€€€€€€€€€€€€€€€€€€ÕÉÉ•¹Ñ}ÍÑ…Ñ”°(€€€€€€€€€€€€€€€€€€€É½ÕÁ}¥°(€€€€€€€€€€€€€€€€€€€Ñ½‘…ä°(€€€€€€€€€€€€€€€€€€€¹½Ü°(€€€€€€€€€€€€€€€€€€€±…¥µ}Ñ½­•¸õ±…¥µ}Ñ½­•¸°(€€€€€€€€€€€€€€€€€€€É•±•…Í•}½¹±äõQÉÕ”°(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€¤(€€€€€€€€€€€É…¥Í”(€€€€€€€µ•µ‰•É}¥‘Ì€ô±¥ÍĞ¡‘¥Ğ¹™É½µ­•åÌ (€€€€€€€€€€€ÍÑÈ¡Õ¥½È€ˆˆ¤¹ÍÑÉ¥À ¤™½ÈÕ¥¥¸ÕÉÉ•¹Ñ}¥‘Ì¥˜ÍÑÈ¡Õ¥½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€€¤¤(€€€€€€€ÁÉ•Á…É•€ôµÕÑ…Ñ•}ÍÑ…Ñ•}…Ñ½µ¥…±±ä (€€€€€€€€€€€½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€±…µ‰‘„ÕÉÉ•¹Ñ}ÍÑ…Ñ”è}ÁÉ•Á…É•}Õ…É‘¥…¹}É½ÕÁ}ÍÕµµ…Éä (€€€€€€€€€€€€€€€ÕÉÉ•¹Ñ}ÍÑ…Ñ”°(€€€€€€€€€€€€€€€É½ÕÁ}¥°(€€€€€€€€€€€€€€€Ñ½‘…ä°(€€€€€€€€€€€€€€€¹½Ü°(€€€€€€€€€€€€€€€±…¥µ}Ñ½­•¸°(€€€€€€€€€€€€€€€µ•µ‰•É}¥‘Ì°(€€€€€€€€€€€€¤°(€€€€€€€€¤(€€€€€€€•±¥¥‰±•}µ•µ‰•ÉÌ€ôÁÉ•Á…É•¹•Ğ ‰•±¥¥‰±•}µ•µ‰•ÉÌˆ¤½Èmt(€€€€€€€¥˜¹½ĞÁÉ•Á…É•¹•Ğ ‰É•…‘äˆ¤è(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€É•ÍÕ±ÑÌ¹…ÁÁ•¹¡ì(€€€€€€€€€€€€€€€€‰É½ÕÁ}¥ˆèÉ½ÕÁ}¥°(€€€€€€€€€€€€€€€€‰ÍÑ…ÑÕÌˆèÁÉ•Á…É•¹•Ğ ‰É•…Í½¸ˆ¤½È€‰¹½}±½¹•É}•±¥¥‰±”ˆ°(€€€€€€€€€€€ô¤(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¥˜¹½Ğ•±¥¥‰±•}µ•µ‰•ÉÌè(€€€€€€€€€€€µÕÑ…Ñ•}ÍÑ…Ñ•}…Ñ½µ¥…±±ä (€€€€€€€€€€€€€€€½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€±…µ‰‘„ÕÉÉ•¹Ñ}ÍÑ…Ñ”è}™¥¹¥Í¡}Õ…É‘¥…¹}É½ÕÁ}ÍÕµµ…Éä (€€€€€€€€€€€€€€€€€€€ÕÉÉ•¹Ñ}ÍÑ…Ñ”°(€€€€€€€€€€€€€€€€€€€É½ÕÁ}¥°(€€€€€€€€€€€€€€€€€€€Ñ½‘…ä°(€€€€€€€€€€€€€€€€€€€¹½Ü°(€€€€€€€€€€€€€€€€€€€±…¥µ}Ñ½­•¸õ±…¥µ}Ñ½­•¸°(€€€€€€€€€€€€€€€€€€€É•±•…Í•}½¹±äõQÉÕ”°(€€€€€€€€€€€€€€€€€€€µ•µ‰•É}¥‘Ìõµ•µ‰•É}¥‘Ì°(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€¤(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€É•ÍÕ±ÑÌ¹…ÁÁ•¹¡ì‰É½ÕÁ}¥ˆèÉ½ÕÁ}¥°€‰ÍÑ…ÑÕÌˆè€‰¹½}•±¥¥‰±•}µ•µ‰•ÉÌ‰ô¤(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¡•­•€ômt(€€€€€€€Õ¹¡•­•€ômt(€€€€€€€™½Èµ•µ‰•È¥¸•±¥¥‰±•}µ•µ‰•ÉÌè(€€€€€€€€€€€ÁÉ½™¥±”€ôµ•µ‰•Él‰ÁÉ½™¥±”‰t(€€€€€€€€€€€¹…µ”€ôµ•µ‰•Él‰¹…µ”‰t(€€€€€€€€€€€€¡¡•­•¥˜}µ•µ‰•É}¡•­•‘}Ñ½‘…ä¡ÁÉ½™¥±”°Ñ½‘…ä¤•±Í”Õ¹¡•­•¤¹…ÁÁ•¹¡¹…µ”¤(€€€€€€€µ•ÍÍ…”€ô€ (€€€€€€€€€€€˜‹Â~N(ƒ’î+š^—–æÏ–º'šFc¢š¾ò!íÑ½‘…å÷¾ò%q¸ˆ(€€€€€€€€€€€˜‹–ŞË–‚Ç–æÏ–º'¾òiìœ°€œ¹©½¥¸¡¡•­•¤¥˜¡•­••±Í”€Ÿ–Âk„õq¸ˆ(€€€€€€€€€€€˜‹–Âkšr«–‚Ç–æÏ–º'¾òiìœ°€œ¹©½¥¸¡Õ¹¡•­•¤¥˜Õ¹¡•­••±Í”€Ÿn»–&7¦÷–ŞË–º3š"@õq¹q¸ˆ(€€€€€€€€€€€€‹¾ò#š¶“
ë¦ãR£ú“ÖšFc¢š¾òo¦^s¦Z'–ú3–>«šr¢¢+š‚ã–ş–º#¢¶ß’êë¾ò$ˆ(€€€€€€€€¤(€€€€€€€ÑÉäè(€€€€€€€€€€€¥˜Í•¹‘•È¥Ì±¥¹•}ÁÕÍ¡}µ•ÍÍ…”è(€€€€€€€€€€€€€€€É•ÍÕ±Ğ€ôÍ•¹‘•È (€€€€€€€€€€€€€€€€€€€Ñ½­•¸°(€€€€€€€€€€€€€€€€€€€É½ÕÁ}¥°(€€€€€€€€€€€€€€€€€€€µ•ÍÍ…”°(€€€€€€€€€€€€€€€€€€€É•ÑÉå}­•äõ}±¥¹•}É•ÑÉå}­•ä¡‘•±¥Ù•Éå}­•ä¤°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€É•ÍÕ±Ğ€ôÍ•¹‘•È¡Ñ½­•¸°É½ÕÁ}¥°µ•ÍÍ…”¤(€€€€€€€€€€€µÕÑ…Ñ•}ÍÑ…Ñ•}…Ñ½µ¥…±±ä (€€€€€€€€€€€€€€€½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€±…µ‰‘„ÕÉÉ•¹Ñ}ÍÑ…Ñ”è}™¥¹¥Í¡}Õ…É‘¥…¹}É½ÕÁ}ÍÕµµ…Éä (€€€€€€€€€€€€€€€€€€€ÕÉÉ•¹Ñ}ÍÑ…Ñ”°(€€€€€€€€€€€€€€€€€€€É½ÕÁ}¥°(€€€€€€€€€€€€€€€€€€€Ñ½‘…ä°(€€€€€€€€€€€€€€€€€€€¹½Ü°(€€€€€€€€€€€€€€€€€€€±…¥µ}Ñ½­•¸õ±…¥µ}Ñ½­•¸°(€€€€€€€€€€€€€€€€€€€Í•¹ĞõQÉÕ”°(€€€€€€€€€€€€€€€€€€€µ•ÍÍ…”õµ•ÍÍ…”°(€€€€€€€€€€€€€€€€€€€É•ÍÕ±ĞõÉ•ÍÕ±Ğ°(€€€€€€€€€€€€€€€€€€€µ•µ‰•É}¥‘Ìõµ•µ‰•É}¥‘Ì°(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€¤(€€€€€€€€€€€Í•¹Ğ€¬ô€Ä(€€€€€€€€€€€É•ÍÕ±ÑÌ¹…ÁÁ•¹¡ì‰É½ÕÁ}¥ˆèÉ½ÕÁ}¥°€‰É•ÍÕ±ĞˆèÉ•ÍÕ±Ñô¤(€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€™…¥±ÕÉ”€ôµÕÑ…Ñ•}ÍÑ…Ñ•}…Ñ½µ¥…±±ä (€€€€€€€€€€€€€€€½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€±…µ‰‘„ÕÉÉ•¹Ñ}ÍÑ…Ñ”è}™¥¹¥Í¡}Õ…É‘¥…¹}É½ÕÁ}ÍÕµµ…Éä (€€€€€€€€€€€€€€€€€€€ÕÉÉ•¹Ñ}ÍÑ…Ñ”°(€€€€€€€€€€€€€€€€€€€É½ÕÁ}¥°(€€€€€€€€€€€€€€€€€€€Ñ½‘…ä°(€€€€€€€€€€€€€€€€€€€¹½Ü°(€€€€€€€€€€€€€€€€€€€±…¥µ}Ñ½­•¸õ±…¥µ}Ñ½­•¸°(€€€€€€€€€€€€€€€€€€€µ•ÍÍ…”õµ•ÍÍ…”°(€€€€€€€€€€€€€€€€€€€•ÉÉ½Èõ•áŒ°(€€€€€€€€€€€€€€€€€€€µ•µ‰•É}¥‘Ìõµ•µ‰•É}¥‘Ì°(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€¤(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€É•ÍÕ±ÑÌ¹…ÁÁ•¹¡ì‰É½ÕÁ}¥ˆèÉ½ÕÁ}¥°€‰•ÉÉ½ÈˆèÍÑÈ¡•áŒ¥ô¤(€€€€€€€€€€€¥˜™…¥±ÕÉ•l‰­¥¹‰t€ôô€‰ÍåÍÑ•´ˆè(€€€€€€€€€€€€€€€ÍåÍÑ•µ}•ÉÉ½È€ôQÉÕ”(€€€€€€€€€€€€€€€‰É•…¬((€€€É•ÑÕÉ¸ì(€€€€€€€€‰Í•¹ĞˆèÍ•¹Ğ°(€€€€€€€€‰Í­¥ÁÁ•ˆèÍ­¥ÁÁ•°(€€€€€€€€‰‘•™•ÉÉ•ˆè‘•™•ÉÉ•°(€€€€€€€€‰É•ÍÕ±ÑÌˆèÉ•ÍÕ±ÑÌ°(€€€€€€€€‰‘…Ñ”ˆèÑ½‘…ä°(€€€€€€€€‰ÍåÍÑ•µ}•ÉÉ½ÈˆèÍåÍÑ•µ}•ÉÉ½È°(€€€ô°€ÈÀÀ(()‘•˜}±¥¹•}É•ÑÉå}­•ä¡‘•±¥Ù•Éå}­•ä¤è(€€€€ˆˆ‰MÑ…‰±”UU%…•ÁÑ•‰ä1%9™½È¥‘•µÁ½Ñ•¹ĞÉ•ÑÉ¥•Ì½˜½¹”±½¥…°ÁÕÍ ¸ˆˆˆ(€€€É•ÑÕÉ¸ÍÑÈ¡ÕÕ¥¹ÕÕ¥Ô¡ÕÕ¥¹95MA}UI0°˜‰‘…¥±äµÁ•…”éí‘•±¥Ù•Éå}­•åôˆ¤¤(()‘•˜}±…¥µ}Õ…É‘¥…¹}É½ÕÁ}ÍÕµµ…Éä¡ÍÑ…Ñ”°É½ÕÁ}¥°Ñ½‘…ä°¹½Ü¤è(€€€É½ÕÀ€ô€¡ÍÑ…Ñ”¹•Ğ ‰Õ…É‘¥…¹}É½ÕÁÌˆ¤½Èíô¤¹•Ğ¡É½ÕÁ}¥¤(€€€¥˜¹½Ğ¥Í¥¹ÍÑ…¹”¡É½ÕÀ°‘¥Ğ¤è(€€€€€€€É•ÑÕÉ¸ì‰±…¥µ•ˆè…±Í”°€‰É•…Í½¸ˆè€‰É½ÕÁ}¹½Ñ}™½Õ¹‰ô(€€€½İ¹•È€ô€¡ÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ¤½Èíô¤¹•Ğ (€€€€€€€ÍÑÈ¡É½ÕÀ¹•Ğ ‰½İ¹•É}±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€¤½Èíô(€€€ÁÉ•™Ì€ô¹½Éµ…±¥é•}Õ…É‘¥…¹}É½ÕÁ}ÁÉ•™•É•¹•Ì¡É½ÕÀ¹•Ğ ‰ÁÉ•™•É•¹•Ìˆ¤¤(€€€¥˜€ (€€€€€€€É½ÕÀ¹•Ğ ‰ÍÑ…ÑÕÌˆ¤€„ô€‰…Ñ¥Ù”ˆ(€€€€€€€½È¹½ĞÁÉ•™Ì¹•Ğ ‰‘…¥±å}…‘µ¥¹}ÍÕµµ…Éäˆ¤(€€€€€€€½È¹½ĞÕ…É‘¥…¹}É½ÕÁ}•¹Ñ¥Ñ±•µ•¹Ñ}…Ñ¥Ù”¡½İ¹•È°¹½Ü¤(€€€€¤è(€€€€€€€É•ÑÕÉ¸ì‰±…¥µ•ˆè…±Í”°€‰É•…Í½¸ˆè€‰¹½}±½¹•É}•±¥¥‰±”‰ô(€€€¥˜É½ÕÀ¹•Ğ ‰±…ÍÑ}‘…¥±å}ÍÕµµ…Éå}‘…Ñ”ˆ¤€ôôÑ½‘…äè(€€€€€€€É•ÑÕÉ¸ì‰±…¥µ•ˆè…±Í•ô(€€€±…¥µÌ€ô‘¥Ğ¡É½ÕÀ¹•Ğ ‰‘…¥±å}ÍÕµµ…Éå}±…¥µÌˆ¤½Èíô¤(€€€•á¥ÍÑ¥¹œ€ô±…¥µÌ¹•Ğ¡Ñ½‘…ä¤½Èíô(€€€¥˜•á¥ÍÑ¥¹œè(€€€€€€€±…¥µ•‘}…Ğ€ô9½¹”(€€€€€€€ÑÉäè(€€€€€€€€€€€±…¥µ•‘}…Ğ€ô‘…Ñ•Ñ¥µ”¹™É½µ¥Í½™½Éµ…Ğ¡ÍÑÈ¡•á¥ÍÑ¥¹œ¹•Ğ ‰±…¥µ•‘}…Ğˆ¤½È€ˆˆ¤¤(€€€€€€€•á•ÁĞ€¡QåÁ•ÉÉ½È°Y…±Õ•ÉÉ½È¤è(€€€€€€€€€€€±…¥µ•‘}…Ğ€ô9½¹”(€€€€€€€¥˜±…¥µ•‘}…Ğ¥Ì¹½Ğ9½¹”…¹€¡¹½Ü€´±…¥µ•‘}…Ğ¤¹Ñ½Ñ…±}Í•½¹‘Ì ¤€ğ€äÀÀè(€€€€€€€€€€€É•ÑÕÉ¸ì‰±…¥µ•ˆè…±Í”°€‰É•…Í½¸ˆè€‰…Ñ¥Ù•}±…¥´‰ô(€€€±…¥µ}Ñ½­•¸€ôÍ•É•ÑÌ¹Ñ½­•¹}¡•à ÄØ¤(€€€±…¥µÍmÑ½‘…åt€ôì(€€€€€€€€‰±…¥µ•‘}…Ğˆè¹½Ü¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤°(€€€€€€€€‰±…¥µ}Ñ½­•¸ˆè±…¥µ}Ñ½­•¸°(€€€ô(€€€É½ÕÁl‰‘…¥±å}ÍÕµµ…Éå}±…¥µÌ‰t€ô±…¥µÌ(€€€É•ÑÕÉ¸ì(€€€€€€€€‰±…¥µ•ˆèQÉÕ”°(€€€€€€€€‰É•½Ù•É•ˆè‰½½°¡•á¥ÍÑ¥¹œ¤°(€€€€€€€€‰±…¥µ}Ñ½­•¸ˆè±…¥µ}Ñ½­•¸°(€€€ô(()‘•˜}ÁÉ•Á…É•}Õ…É‘¥…¹}É½ÕÁ}ÍÕµµ…Éä (€€€ÍÑ…Ñ”°É½ÕÁ}¥°Ñ½‘…ä°¹½Ü°±…¥µ}Ñ½­•¸°µ•µ‰•É}¥‘Ì(¤è(€€€É½ÕÀ€ô€¡ÍÑ…Ñ”¹•Ğ ‰Õ…É‘¥…¹}É½ÕÁÌˆ¤½Èíô¤¹•Ğ¡É½ÕÁ}¥¤(€€€±…¥´€ô€ ¡É½ÕÀ½Èíô¤¹•Ğ ‰‘…¥±å}ÍÕµµ…Éå}±…¥µÌˆ¤½Èíô¤¹•Ğ¡Ñ½‘…ä¤½Èíô(€€€¥˜¹½Ğ¥Í¥¹ÍÑ…¹”¡É½ÕÀ°‘¥Ğ¤½È±…¥´¹•Ğ ‰±…¥µ}Ñ½­•¸ˆ¤€„ô±…¥µ}Ñ½­•¸è(€€€€€€€É•ÑÕÉ¸ì‰É•…‘äˆè…±Í”°€‰É•…Í½¸ˆè€‰±…¥µ}±½ÍĞ‰ô(€€€½İ¹•È€ô€¡ÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ¤½Èíô¤¹•Ğ (€€€€€€€ÍÑÈ¡É½ÕÀ¹•Ğ ‰½İ¹•É}±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€¤½Èíô(€€€ÁÉ•™Ì€ô¹½Éµ…±¥é•}Õ…É‘¥…¹}É½ÕÁ}ÁÉ•™•É•¹•Ì¡É½ÕÀ¹•Ğ ‰ÁÉ•™•É•¹•Ìˆ¤¤(€€€¥˜€ (€€€€€€€É½ÕÀ¹•Ğ ‰ÍÑ…ÑÕÌˆ¤€„ô€‰…Ñ¥Ù”ˆ(€€€€€€€½È¹½ĞÁÉ•™Ì¹•Ğ ‰‘…¥±å}…‘µ¥¹}ÍÕµµ…Éäˆ¤(€€€€€€€½È¹½ĞÕ…É‘¥…¹}É½ÕÁ}•¹Ñ¥Ñ±•µ•¹Ñ}…Ñ¥Ù”¡½İ¹•È°¹½Ü¤(€€€€¤è(€€€€€€€}™¥¹¥Í¡}Õ…É‘¥…¹}É½ÕÁ}ÍÕµµ…Éä (€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€É½ÕÁ}¥°(€€€€€€€€€€€Ñ½‘…ä°(€€€€€€€€€€€¹½Ü°(€€€€€€€€€€€±…¥µ}Ñ½­•¸õ±…¥µ}Ñ½­•¸°(€€€€€€€€€€€É•±•…Í•}½¹±äõQÉÕ”°(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸ì‰É•…‘äˆè…±Í”°€‰É•…Í½¸ˆè€‰¹½}±½¹•É}•±¥¥‰±”‰ô(€€€É½ÕÁl‰µ•µ‰•É}¥‘Í}±…ÍÑ}ÍÕµµ…Éä‰t€ô±¥ÍĞ¡µ•µ‰•É}¥‘Ì¤(€€€É½ÕÁl‰µ•µ‰•É}¥‘Í}±…ÍÑ}ÍÕµµ…Éå}…Ğ‰t€ô¹½Ü¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤(€€€É•ÑÕÉ¸ì(€€€€€€€€‰É•…‘äˆèQÉÕ”°(€€€€€€€€‰•±¥¥‰±•}µ•µ‰•ÉÌˆè•±¥¥‰±•}Õ…É‘¥…¹}É½ÕÁ}ÍÕµµ…Éå}µ•µ‰•ÉÌ (€€€€€€€€€€€ÍÑ…Ñ”°É½ÕÀ°µ•µ‰•É}¥‘Ì(€€€€€€€€¤°(€€€ô(()‘•˜}™¥¹¥Í¡}Õ…É‘¥…¹}É½ÕÁ}ÍÕµµ…Éä (€€€ÍÑ…Ñ”°(€€€É½ÕÁ}¥°(€€€Ñ½‘…ä°(€€€¹½Ü°(€€€€¨°(€€€±…¥µ}Ñ½­•¸°(€€€Í•¹Ğõ…±Í”°(€€€É•±•…Í•}½¹±äõ…±Í”°(€€€µ•ÍÍ…”ôˆˆ°(€€€É•ÍÕ±Ğõ9½¹”°(€€€•ÉÉ½Èõ9½¹”°(€€€µ•µ‰•É}¥‘Ìõ9½¹”°(€€€…Õ‘¥Ñ}­¥¹õ9½¹”°(€€€…Õ‘¥Ñ}ÍÑ…ÑÕÌõ9½¹”°(€€€…Õ‘¥Ñ}‘•Ñ…¥°õ9½¹”°(¤è(€€€É½ÕÀ€ô€¡ÍÑ…Ñ”¹•Ğ ‰Õ…É‘¥…¹}É½ÕÁÌˆ¤½Èíô¤¹•Ğ¡É½ÕÁ}¥¤(€€€¥˜¹½Ğ¥Í¥¹ÍÑ…¹”¡É½ÕÀ°‘¥Ğ¤è(€€€€€€€É•ÑÕÉ¸ì‰­¥¹ˆè€‰Á•Éµ…¹•¹Ğˆ°€‰É•ÑÉäˆè…±Í•ô(€€€±…¥µÌ€ô‘¥Ğ¡É½ÕÀ¹•Ğ ‰‘…¥±å}ÍÕµµ…Éå}±…¥µÌˆ¤½Èíô¤(€€€±…¥´€ô±…¥µÌ¹•Ğ¡Ñ½‘…ä¤½Èíô(€€€¥˜±…¥´¹•Ğ ‰±…¥µ}Ñ½­•¸ˆ¤€„ô±…¥µ}Ñ½­•¸è(€€€€€€€É•ÑÕÉ¸ì‰­¥¹ˆè€‰±…¥µ}±½ÍĞˆ°€‰É•ÑÉäˆè…±Í•ô(€€€±…¥µÌ¹Á½À¡Ñ½‘…ä°9½¹”¤(€€€¥˜±…¥µÌè(€€€€€€€É½ÕÁl‰‘…¥±å}ÍÕµµ…Éå}±…¥µÌ‰t€ô±…¥µÌ(€€€•±Í”è(€€€€€€€É½ÕÀ¹Á½À ‰‘…¥±å}ÍÕµµ…Éå}±…¥µÌˆ°9½¹”¤(€€€¥˜µ•µ‰•É}¥‘Ì¥Ì¹½Ğ9½¹”è(€€€€€€€É½ÕÁl‰µ•µ‰•É}¥‘Í}±…ÍÑ}ÍÕµµ…Éä‰t€ô±¥ÍĞ¡µ•µ‰•É}¥‘Ì¤(€€€€€€€É½ÕÁl‰µ•µ‰•É}¥‘Í}±…ÍÑ}ÍÕµµ…Éå}…Ğ‰t€ô¹½Ü¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤(€€€¥˜…Õ‘¥Ñ}­¥¹è(€€€€€€€…ÁÁ•¹‘}¹½Ñ¥™¥…Ñ¥½¹}±½œ (€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€…Õ‘¥Ñ}­¥¹°(€€€€€€€€€€€É½ÕÁ}¥°(€€€€€€€€€€€…Õ‘¥Ñ}ÍÑ…ÑÕÌ½È€‰™…¥±•ˆ°(€€€€€€€€€€€€ˆˆ°(€€€€€€€€€€€…Õ‘¥Ñ}‘•Ñ…¥°°(€€€€€€€€¤(€€€¥˜É•±•…Í•}½¹±äè(€€€€€€€É•ÑÕÉ¸ì‰É•±•…Í•ˆèQÉÕ•ô(€€€‘•±¥Ù•Éå}­•ä€ô˜‰Õ…É‘¥…¹}É½ÕÁ}‘…¥±å}ÍÕµµ…ÉäéíÑ½‘…åôéíÉ½ÕÁ}¥‘ôˆ(€€€¥˜Í•¹Ğè(€€€€€€€}±•…É}ÁÕÍ¡}‘•±¥Ù•Éå}™…¥±ÕÉ”¡É½ÕÀ°‘•±¥Ù•Éå}­•ä¤(€€€€€€€…ÁÁ•¹‘}¹½Ñ¥™¥…Ñ¥½¹}±½œ (€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€€‰Õ…É‘¥…¹}É½ÕÁ}‘…¥±å}ÍÕµµ…Éäˆ°(€€€€€€€€€€€É½ÕÁ}¥°(€€€€€€€€€€€€‰Í•¹Ğˆ°(€€€€€€€€€€€µ•ÍÍ…”°(€€€€€€€€€€€©Í½¸¹‘ÕµÁÌ¡É•ÍÕ±Ğ°•¹ÍÕÉ•}…Í¥¤õ…±Í”¤°(€€€€€€€€¤(€€€€€€€É•½É‘}±¥¹•}µ•ÍÍ…•}ÕÍ…” (€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€…Ñ•½Éäô‰Õ…É‘¥…¹}ÍÕµµ…Éäˆ°(€€€€€€€€€€€½İ¹•É}±¥¹•}ÕÍ•É}¥õÉ½ÕÀ¹•Ğ ‰½İ¹•É}±¥¹•}ÕÍ•É}¥ˆ¤½ÈÉ½ÕÁ}¥°(€€€€€€€€€€€É•¥Á¥•¹Ñ}½Õ¹Ğõµ…à Ä°±•¸¡µ•µ‰•É}¥‘Ì½Èmt¤¤°(€€€€€€€€€€€•Ù•¹Ñ}¥õ‘•±¥Ù•Éå}­•ä°(€€€€€€€€€€€Í•¹Ñ}…Ğõ¹½Ü°(€€€€€€€€¤(€€€€€€€É½ÕÁl‰±…ÍÑ}‘…¥±å}ÍÕµµ…Éå}‘…Ñ”‰t€ôÑ½‘…ä(€€€€€€€É•ÑÕÉ¸ì‰Í•¹ĞˆèQÉÕ•ô(€€€É•ÑÕÉ¸}É•½É‘}Í¡•‘Õ±•‘}ÁÕÍ¡}™…¥±ÕÉ” (€€€€€€€ÍÑ…Ñ”°(€€€€€€€É½ÕÀ°(€€€€€€€‘•±¥Ù•Éå}­•ä°(€€€€€€€€‰Õ…É‘¥…¹}É½ÕÁ}‘…¥±å}ÍÕµµ…Éäˆ°(€€€€€€€É½ÕÁ}¥°(€€€€€€€µ•ÍÍ…”°(€€€€€€€•ÉÉ½È°(€€€€€€€¹½Ü°(€€€€¤(()‘•˜Í•¹‘}µ¥ÍÍ¥¹}½¹Ñ…Ñ}É•µ¥¹‘•ÉÌ¡½¹™¥œ¤è(€€€Ñ½­•¸€ô½¹™¥œ¹•Ğ ‰1%9}!991}MM}Q=-8ˆ¤½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}!991}MM}Q=-8ˆ°€ˆˆ¤(€€€¥˜¹½ĞÑ½­•¸è(€€€€€€€É•ÑÕÉ¸ì‰Í•¹Ğˆè€À°€‰Í­¥ÁÁ•ˆè€À°€‰•ÉÉ½Èˆè€‰1%9}!991}MM}Q=-8¥Ì¹½ĞÍ•Ğ‰ô°€ĞÀÀ((€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡½¹™¥l‰Q}%1‰t¤(€€€Í•¹‘•È€ô½¹™¥œ¹•Ğ ‰1%9}AUM!}M9Hˆ¤½È±¥¹•}ÁÕÍ¡}µ•ÍÍ…”(€€€ÁÕ‰±¥}ÕÉ°€ô€¡½¹™¥œ¹•Ğ ‰AA}AU	1%}UI0ˆ¤½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰AA}AU	1%}UI0ˆ°€ˆˆ¤¤¹ÉÍÑÉ¥À ˆ¼ˆ¤(€€€¹½Ü€ôÕÉÉ•¹Ñ}…ÁÁ}Ñ¥µ”¡½¹™¥œ¤(€€€¥˜¹½Ğ±¥¹•}¹½¹}•µ•É•¹å}ÁÕÍ¡}…±±½İ•¡ÍÑ…Ñ”°½¹™¥œ°¹½Ü¤è(€€€€€€€É•ÑÕÉ¸±¥¹•}‰Õ‘•Ñ}‰±½­•‘}É•ÍÁ½¹Í”¡ÍÑ…Ñ”°½¹™¥œ°¹½Ü¤(€€€Ñ½‘…ä€ô¹½Ü¹ÍÑÉ™Ñ¥µ” ˆ•d´•´´•ˆ¤(€€€Í•¹Ğ€ô€À(€€€Í­¥ÁÁ•€ô€À(€€€É•ÍÕ±ÑÌ€ômt(€€€ÍåÍÑ•µ}•ÉÉ½È€ô…±Í”(€€€™½ÈÕÍ•È¥¸ÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ°íô¤¹Ù…±Õ•Ì ¤è(€€€€€€€±¥¹•}ÕÍ•É}¥€ôÕÍ•È¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤(€€€€€€€¥˜¹½Ğ±¥¹•}ÕÍ•É}¥è(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¥˜ÕÍ•È¹•Ğ ‰µ•µ‰•ÉÍ¡¥Á}Á…ÕÍ•ˆ¤½È¹½Ğµ•µ‰•ÉÍ¡¥Á}…•ÍÍ}…Ñ¥Ù”¡ÕÍ•È°¹½Ü¤è(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€½¹Ñ…Ñ}½Õ¹Ğ€ô±•¸¡ÕÍ•È¹•Ğ ‰½¹Ñ…ÑÌˆ¤½Èmt¤(€€€€€€€½¹Ñ…Ñ}±¥µ¥Ğ€ôÁ±…¹}ÉÕ±•Ì¡ÕÍ•È¥l‰½¹Ñ…Ñ}±¥µ¥Ğ‰t(€€€€€€€É•µ¥¹‘•É}•¹…‰±•€ô‰½½°¡ÕÍ•È¹•Ğ ‰½¹Ñ…Ñ}…Á…¥Ñå}É•µ¥¹‘•É}•¹…‰±•ˆ°…±Í”¤¤(€€€€€€€¥Í|Üää€ôÕÍ•È¹•Ğ ‰Á±…¸ˆ¤¥¸ì‰Á…¥‘|Üääˆ°€‰Á…¥‘|Üäå}å•…È‰ô(€€€€€€€Õ…É‘¥…¹}‘•Ñ…¥±Í}½µÁ±•Ñ”€ô…¹ä¡½µÁ±•Ñ•}Õ…É‘¥…¹}½¹Ñ…Ğ¡½¹Ñ…Ğ¤™½È½¹Ñ…Ğ¥¸€¡ÕÍ•È¹•Ğ ‰½¹Ñ…ÑÌˆ¤½Èmt¤¤(€€€€€€€¥˜¥Í|Üää…¹¹½ĞÕ…É‘¥…¹}‘•Ñ…¥±Í}½µÁ±•Ñ”è(€€€€€€€€€€€¥˜¹½ĞÕÍ•È¹•Ğ ‰Õ…É‘¥…¹}‘•Ñ…¥±Í}É•µ¥¹‘•É}•¹…‰±•ˆ°QÉÕ”¤½ÈÕÍ•È¹•Ğ ‰Õ…É‘¥…¹}‘•Ñ…¥±Í}É•µ¥¹‘•É}Í•¹Ñ}…Ğˆ¤è(€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€‘•±¥Ù•Éå}­•ä€ô˜‰Õ…É‘¥…¹}‘•Ñ…¥±ÌéíÑ½‘…åôˆ(€€€€€€€€€€€¥˜¹½ĞÁÕÍ¡}…ÑÑ•µÁÑ}…±±½İ•¡ÕÍ•È°‘•±¥Ù•Éå}­•ä¤è(€€€€€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€±¥¹­}Ñ•áĞ€ô€ (€€€€€€€€€€€€€€€˜‰q»–&7–úš"Gj–º#¢¶ß¢ÎšZg¾òií±¥™™}•¹ÑÉå}ÕÉ°¡½Á•¹}…Ñ¥½¸ôµ•µ‰•Èœ¤¥˜±¥™™}•¹ÑÉå}ÕÉ°•±Í”€¡ÑÑÁÌè¼½±¥™˜¹±¥¹”¹µ”¼ÈÀÄÀàĞàÌÌÀµU¥ÅAAeı½Á•¸õµ•µ‰•Èôˆ(€€€€€€€€€€€€¤(€€€€€€€€€€€µ•ÍÍ…”€ô€ (€€€€€€€€€€€€€€€€‹’öƒj€Üääƒ–º#¢¶ßšZçš†#¦
–ÂG’â’î÷–ş¢š¢ÎšZg¢®/–r£;š"Gj–º#¢¶ß¢ÎšZg?–º3š"C¢Ï–ÂD€Äƒ’ö7–º#¢¶ß’êëj–O–B7¦^s’ş¢"¦nï¢¦Ç¾ò0ˆ(€€€€€€€€€€€€€€€˜‹Ş+š—šfÎïÖÇš&7¢÷š¶Šë¢¿Ö‡–Â7šZç¦g–&š>C¦K–>«šr–
Ï¦’âš²‡	í±¥¹­}Ñ•áÑôˆ(€€€€€€€€€€€€¤(€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€É•ÍÕ±Ğ€ôÍ•¹‘•È¡Ñ½­•¸°±¥¹•}ÕÍ•É}¥°µ•ÍÍ…”¤(€€€€€€€€€€€€€€€}±•…É}ÁÕÍ¡}‘•±¥Ù•Éå}™…¥±ÕÉ”¡ÕÍ•È°‘•±¥Ù•Éå}­•ä¤(€€€€€€€€€€€€€€€ÕÍ•Él‰Õ…É‘¥…¹}‘•Ñ…¥±Í}É•µ¥¹‘•É}Í•¹Ñ}…Ğ‰t€ô¹½Ü¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤(€€€€€€€€€€€€€€€…ÁÁ•¹‘}¹½Ñ¥™¥…Ñ¥½¹}±½œ¡ÍÑ…Ñ”°€‰Õ…É‘¥…¹}‘•Ñ…¥±Ìˆ°±¥¹•}ÕÍ•É}¥°€‰Í•¹Ğˆ°µ•ÍÍ…”°©Í½¸¹‘ÕµÁÌ¡É•ÍÕ±Ğ°•¹ÍÕÉ•}…Í¥¤õ…±Í”¤¤(€€€€€€€€€€€€€€€Í•¹Ğ€¬ô€Ä(€€€€€€€€€€€€€€€É•ÍÕ±ÑÌ¹…ÁÁ•¹¡ì‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°€‰É•ÍÕ±ĞˆèÉ•ÍÕ±Ñô¤(€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€€€€€™…¥±ÕÉ”€ô}É•½É‘}Í¡•‘Õ±•‘}ÁÕÍ¡}™…¥±ÕÉ” (€€€€€€€€€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€€€€€€€€€ÕÍ•È°(€€€€€€€€€€€€€€€€€€€‘•±¥Ù•Éå}­•ä°(€€€€€€€€€€€€€€€€€€€€‰Õ…É‘¥…¹}‘•Ñ…¥±Ìˆ°(€€€€€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€€€€€µ•ÍÍ…”°(€€€€€€€€€€€€€€€€€€€•áŒ°(€€€€€€€€€€€€€€€€€€€¹½Ü°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€€€€€É•ÍÕ±ÑÌ¹…ÁÁ•¹¡ì‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°€‰•ÉÉ½ÈˆèÍÑÈ¡•áŒ¥ô¤(€€€€€€€€€€€€€€€¥˜™…¥±ÕÉ•l‰­¥¹‰t€ôô€‰ÍåÍÑ•´ˆè(€€€€€€€€€€€€€€€€€€€ÍåÍÑ•µ}•ÉÉ½È€ôQÉÕ”(€€€€€€€€€€€€€€€€€€€‰É•…¬(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¥˜½¹Ñ…Ñ}½Õ¹Ğ€øô½¹Ñ…Ñ}±¥µ¥Ğ½È€¡½¹Ñ…Ñ}½Õ¹Ğ€ø€À…¹¹½ĞÉ•µ¥¹‘•É}•¹…‰±•¤è(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€Í•¹Ñ}‘…Ñ•Ì€ôÍ•Ğ¡ÕÍ•È¹•Ğ ‰½¹Ñ…Ñ}É•µ¥¹‘•É}Í•¹Ñ}‘…Ñ•Ìˆ¤½Èmt¤(€€€€€€€¥˜Ñ½‘…ä¥¸Í•¹Ñ}‘…Ñ•Ìè(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€±¥¹­}Ñ•áĞ€ô€ (€€€€€€€€€€€˜‰q»’â¦6×¦
¢®/–º#¢¶ß’êë¾òiíÍ¡…É•}¥¹Ù¥Ñ•}±¥™™}ÕÉ° ¤¥˜Í¡…É•}¥¹Ù¥Ñ•}±¥™™}ÕÉ°•±Í”€¡ÑÑÁÌè¼½±¥™˜¹±¥¹”¹µ”¼ÈÀÄÀàĞàÌÌÀµU¥ÅAAe½±¥™˜½Í¡…É”µ¥¹Ù¥Ñ”¹¡Ñµ°ôˆ(€€€€€€€€¤(€€€€€€€¥˜½¹Ñ…Ñ}½Õ¹Ğ€ôô€Àè(€€€€€€€€€€€µ•ÍÍ…”€ô€ (€€€€€€€€€€€€€€€€‹’öƒn»–&7¦
šÊKšr'Ú–ºk–º#¢¶ß’êë¾ò#Ş+š—¢¿Ö‡’êë¾ò'¢®/¢Ï–ÂG¦
¢®,€Äƒ’ö7’ş‡’îïj¢š«–>/–º3š"@1%9ƒÚ–ºk¾ò0ˆ(€€€€€€€€€€€€€€€˜‹Ş+š—šfÎïÖÇš&7~—¦O¢š¢¿Ö‡¢ªÃ	í±¥¹­}Ñ•áÑôˆ(€€€€€€€€€€€€¤(€€€€€€€•±Í”è(€€€€€€€€€€€µ•ÍÍ…”€ô€ (€€€€€€€€€€€€€€€˜‹’öƒjšZçš†#–>¿Ú–ºhí½¹Ñ…Ñ}±¥µ¥Ñôƒ’ö7–º#¢¶ß’êë¾ò3n»–&7–ŞË–º3š"@í½¹Ñ…Ñ}½Õ¹Ñô½í½¹Ñ…Ñ}±¥µ¥Ñôƒ’ö7ˆ(€€€€€€€€€€€€€€€˜‹¢.—šÏ¢s¦ö+–º#¢¶ß–B7¦†7¾ò3–>¿¦î{’â/šZçæóê3¦
¢®/¾òo’æ¢÷–r£š>C¦K¢¢·–ºk’â·¦^s¦Z'¦g–&š¾?š^—š>C¦K	í±¥¹­}Ñ•áÑôˆ(€€€€€€€€€€€€¤(€€€€€€€‘•±¥Ù•Éå}­•ä€ô˜‰µ¥ÍÍ¥¹}½¹Ñ…ĞéíÑ½‘…åôˆ(€€€€€€€¥˜¹½ĞÁÕÍ¡}…ÑÑ•µÁÑ}…±±½İ•¡ÕÍ•È°‘•±¥Ù•Éå}­•ä¤è(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€ÑÉäè(€€€€€€€€€€€É•ÍÕ±Ğ€ôÍ•¹‘•È¡Ñ½­•¸°±¥¹•}ÕÍ•É}¥°µ•ÍÍ…”¤(€€€€€€€€€€€}±•…É}ÁÕÍ¡}‘•±¥Ù•Éå}™…¥±ÕÉ”¡ÕÍ•È°‘•±¥Ù•Éå}­•ä¤(€€€€€€€€€€€Í•¹Ñ}‘…Ñ•Ì¹…‘¡Ñ½‘…ä¤(€€€€€€€€€€€ÕÍ•Él‰½¹Ñ…Ñ}É•µ¥¹‘•É}Í•¹Ñ}‘…Ñ•Ì‰t€ôÍ½ÉÑ•¡Í•¹Ñ}‘…Ñ•Ì¥l´ÌÀét(€€€€€€€€€€€…ÁÁ•¹‘}¹½Ñ¥™¥…Ñ¥½¹}±½œ¡ÍÑ…Ñ”°€‰µ¥ÍÍ¥¹}½¹Ñ…Ğˆ°±¥¹•}ÕÍ•É}¥°€‰Í•¹Ğˆ°µ•ÍÍ…”°©Í½¸¹‘ÕµÁÌ¡É•ÍÕ±Ğ°•¹ÍÕÉ•}…Í¥¤õ…±Í”¤¤(€€€€€€€€€€€Í•¹Ğ€¬ô€Ä(€€€€€€€€€€€É•ÍÕ±ÑÌ¹…ÁÁ•¹¡ì‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°€‰É•ÍÕ±ĞˆèÉ•ÍÕ±Ñô¤(€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€™…¥±ÕÉ”€ô}É•½É‘}Í¡•‘Õ±•‘}ÁÕÍ¡}™…¥±ÕÉ” (€€€€€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€€€€€ÕÍ•È°(€€€€€€€€€€€€€€€‘•±¥Ù•Éå}­•ä°(€€€€€€€€€€€€€€€€‰µ¥ÍÍ¥¹}½¹Ñ…Ğˆ°(€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€µ•ÍÍ…”°(€€€€€€€€€€€€€€€•áŒ°(€€€€€€€€€€€€€€€¹½Ü°(€€€€€€€€€€€€¤(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€É•ÍÕ±ÑÌ¹…ÁÁ•¹¡ì‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°€‰•ÉÉ½ÈˆèÍÑÈ¡•áŒ¥ô¤(€€€€€€€€€€€¥˜™…¥±ÕÉ•l‰­¥¹‰t€ôô€‰ÍåÍÑ•´ˆè(€€€€€€€€€€€€€€€ÍåÍÑ•µ}•ÉÉ½È€ôQÉÕ”(€€€€€€€€€€€€€€€‰É•…¬(€€€Í…Ù•}ÍÑ…Ñ”¡½¹™¥l‰Q}%1‰t°ÍÑ…Ñ”¤(€€€É•ÑÕÉ¸ì(€€€€€€€€‰Í•¹ĞˆèÍ•¹Ğ°(€€€€€€€€‰Í­¥ÁÁ•ˆèÍ­¥ÁÁ•°(€€€€€€€€‰É•ÍÕ±ÑÌˆèÉ•ÍÕ±ÑÌ°(€€€€€€€€‰ÍåÍÑ•µ}•ÉÉ½ÈˆèÍåÍÑ•µ}•ÉÉ½È°(€€€ô°€ÈÀÀ(()‘•˜±•…¹ÕÁ}•áÁ¥É•‘}‘…Ñ„¡½¹™¥œ¤è(€€€‘…Ñ…}™¥±”€ô½¹™¥l‰Q}%1‰t(€€€¹½Ü€ôÕÉÉ•¹Ñ}…ÁÁ}Ñ¥µ”¡½¹™¥œ¤(€€€¥¹Ù¥Ñ•}ÕÑ½™˜€ô¹½Ü€´Ñ¥µ•‘•±Ñ„¡‘…åÌôÜ¤(€€€¹½Ñ¥™¥…Ñ¥½¹}ÕÑ½™˜€ô¹½Ü€´Ñ¥µ•‘•±Ñ„¡‘…åÌôäÀ¤(€€€µ¥É…Ñ¥½¹}±•…¹ÕÁ}¹½Ü€ô¹½Ü(€€€¥˜µ¥É…Ñ¥½¹}±•…¹ÕÁ}¹½Ü¹Ñé¥¹™¼¥Ì9½¹”è(€€€€€€€Ñ¥µ•é½¹•}¹…µ”€ô€ (€€€€€€€€€€€½¹™¥œ¹•Ğ ‰AA}Q%5i=9ˆ¤(€€€€€€€€€€€½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰AA}Q%5i=9ˆ¤(€€€€€€€€€€€½È€‰Í¥„½Q…¥Á•¤ˆ(€€€€€€€€¤(€€€€€€€ÑÉäè(€€€€€€€€€€€…ÁÁ}Ñ¥µ•é½¹”€ôi½¹•%¹™¼¡ÍÑÈ¡Ñ¥µ•é½¹•}¹…µ”¤¤(€€€€€€€•á•ÁĞá•ÁÑ¥½¸è(€€€€€€€€€€€…ÁÁ}Ñ¥µ•é½¹”€ôÑ¥µ•é½¹”¹ÕÑŒ(€€€€€€€µ¥É…Ñ¥½¹}±•…¹ÕÁ}¹½Ü€ôµ¥É…Ñ¥½¹}±•…¹ÕÁ}¹½Ü¹É•Á±…” (€€€€€€€€€€€Ñé¥¹™¼õ…ÁÁ}Ñ¥µ•é½¹”(€€€€€€€€¤¹…ÍÑ¥µ•é½¹”¡Ñ¥µ•é½¹”¹ÕÑŒ¤((€€€‘•˜…Ñ}½É}…™Ñ•È¡Ù…±Õ”°ÕÑ½™˜¤è(€€€€€€€Á…ÉÍ•€ôÁ…ÉÍ•}‘…Ñ•Ñ¥µ”¡Ù…±Õ”¤(€€€€€€€¥˜Á…ÉÍ•¥Ì9½¹”è(€€€€€€€€€€€É•ÑÕÉ¸QÉÕ”(€€€€€€€½µÁ…É…‰±•}Á…ÉÍ•°½µÁ…É…‰±•}ÕÑ½™˜€ô}½µÁ…É…‰±•}‘…Ñ•Ñ¥µ•Ì (€€€€€€€€€€€Á…ÉÍ•°ÕÑ½™˜(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸½µÁ…É…‰±•}Á…ÉÍ•€øô½µÁ…É…‰±•}ÕÑ½™˜((€€€‘•˜µÕÑ…Ñ”¡ÍÑ…Ñ”¤è(€€€€€€€‘½İ¹É…‘•€ô}…ÁÁ±å}•áÁ¥É•‘}Á±…¹}‘½İ¹É…‘•Í}Ñ½}ÍÑ…Ñ”¡ÍÑ…Ñ”°¹½Ü¤(€€€€€€€µ¥É…Ñ¥½¹}¡¥ÍÑ½Éå}É•µ½Ù•€ôÁÕÉ•}…½Õ¹Ñ}µ¥É…Ñ¥½¹}¡¥ÍÑ½Éä (€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€¹½Üõµ¥É…Ñ¥½¹}±•…¹ÕÁ}¹½Ü°(€€€€€€€€¤(€€€€€€€•áÁ¥É•‘}±½…Ñ¥½¹Í}É•µ½Ù•€ô€À(€€€€€€€½¹Ñ…ÑÍ}…É¡¥Ù•€ô€À(€€€€€€€½¹Ñ…ÑÍ}É•ÍÑ½É•€ô€À(€€€€€€€µ¥É…Ñ¥½¹}Í¹…ÁÍ¡½ÑÍ}É•µ½Ù•€ôÁÕÉ•}…½Õ¹Ñ}µ¥É…Ñ¥½¹}Í¹…ÁÍ¡½ÑÌ (€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€¹½Üõµ¥É…Ñ¥½¹}±•…¹ÕÁ}¹½Ü°(€€€€€€€€¤((€€€€€€€™½ÈÁÉ½™¥±”¥¸ÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ°íô¤¹Ù…±Õ•Ì ¤è(€€€€€€€€€€€¥˜É•ÍÑ½É•}±•…å}…ÕÑ½}…É¡¥Ù•‘}½¹Ñ…ÑÌ¡ÁÉ½™¥±”¤è(€€€€€€€€€€€€€€€½¹Ñ…ÑÍ}É•ÍÑ½É•€¬ô€Ä(€€€€€€€€€€€¥˜Í½™Ñ}…É¡¥Ù•}½¹Ñ…ÑÍ}Á…ÍÑ}É•Ñ…¥¸¡ÁÉ½™¥±”°¹½Ü¤è(€€€€€€€€€€€€€€€½¹Ñ…ÑÍ}…É¡¥Ù•€¬ô€Ä(€€€€€€€€€€€±½…Ñ¥½¸€ôÁÉ½™¥±”¹•Ğ ‰±½…Ñ¥½¸ˆ¤½Èíô(€€€€€€€€€€€¥˜¹½Ğ±½…Ñ¥½¸è(€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€¥˜±½…Ñ¥½¸¹•Ğ ‰Õ¹Ñ¥±}ÍÑ½Àˆ¤…¹€ (€€€€€€€€€€€€€€€±½…Ñ¥½¸¹•Ğ ‰Í¡…É¥¹œˆ¤½È±½…Ñ¥½¸¹•Ğ ‰…Ñ¥Ù”ˆ¤(€€€€€€€€€€€€¤è(€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€•áÁ¥É•Í}…Ğ€ôÁ…ÉÍ•}‘…Ñ•Ñ¥µ”¡±½…Ñ¥½¸¹•Ğ ‰•áÁ¥É•Í}…Ğˆ¤¤(€€€€€€€€€€€±½…Ñ¥½¹}•áÁ¥É•€ô…±Í”(€€€€€€€€€€€¥˜•áÁ¥É•Í}…Ğè(€€€€€€€€€€€€€€€½µÁ…É…‰±•}•áÁ¥É•Ì°½µÁ…É…‰±•}¹½Ü€ô}½µÁ…É…‰±•}‘…Ñ•Ñ¥µ•Ì (€€€€€€€€€€€€€€€€€€€•áÁ¥É•Í}…Ğ°¹½Ü(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€±½…Ñ¥½¹}•áÁ¥É•€ô½µÁ…É…‰±•}•áÁ¥É•Ì€ğ½µÁ…É…‰±•}¹½Ü(€€€€€€€€€€€¥˜±½…Ñ¥½¹}•áÁ¥É•è(€€€€€€€€€€€€€€€ÁÉ½™¥±•l‰±½…Ñ¥½¸‰t€ôì(€€€€€€€€€€€€€€€€€€€€¨©±½…Ñ¥½¸°(€€€€€€€€€€€€€€€€€€€€‰Í¡…É¥¹œˆè…±Í”°(€€€€€€€€€€€€€€€€€€€€‰…Ñ¥Ù”ˆè…±Í”°(€€€€€€€€€€€€€€€€€€€€‰•¹‘•‘}…Ğˆè€ (€€€€€€€€€€€€€€€€€€€€€€€±½…Ñ¥½¸¹•Ğ ‰•¹‘•‘}…Ğˆ¤(€€€€€€€€€€€€€€€€€€€€€€€½È¹½Ü¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤(€€€€€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€ô(€€€€€€€€€€€€€€€•áÁ¥É•‘}±½…Ñ¥½¹Í}É•µ½Ù•€¬ô€Ä((€€€€€€€¥¹Ù¥Ñ•Í}‰•™½É”€ô±•¸¡ÍÑ…Ñ”¹•Ğ ‰™É¥•¹‘}¥¹Ù¥Ñ•Ìˆ°íô¤¤(€€€€€€€ÍÑ…Ñ•l‰™É¥•¹‘}¥¹Ù¥Ñ•Ì‰t€ôì(€€€€€€€€€€€½‘”è¥¹Ù¥Ñ”(€€€€€€€€€€€™½È½‘”°¥¹Ù¥Ñ”¥¸ÍÑ…Ñ”¹•Ğ ‰™É¥•¹‘}¥¹Ù¥Ñ•Ìˆ°íô¤¹¥Ñ•µÌ ¤(€€€€€€€€€€€¥˜…Ñ}½É}…™Ñ•È¡¥¹Ù¥Ñ”¹•Ğ ‰É•…Ñ•‘}…Ğˆ¤°¥¹Ù¥Ñ•}ÕÑ½™˜¤(€€€€€€€ô((€€€€€€€±½Í}‰•™½É”€ô±•¸¡ÍÑ…Ñ”¹•Ğ ‰¹½Ñ¥™¥…Ñ¥½¹}±½Ìˆ°mt¤¤(€€€€€€€ÍÑ…Ñ•l‰¹½Ñ¥™¥…Ñ¥½¹}±½Ì‰t€ôl(€€€€€€€€€€€±½œ(€€€€€€€€€€€™½È±½œ¥¸ÍÑ…Ñ”¹•Ğ ‰¹½Ñ¥™¥…Ñ¥½¹}±½Ìˆ°mt¤(€€€€€€€€€€€¥˜…Ñ}½É}…™Ñ•È¡±½œ¹•Ğ ‰É•…Ñ•‘}…Ğˆ¤°¹½Ñ¥™¥…Ñ¥½¹}ÕÑ½™˜¤(€€€€€€€ul´ÄÀÀét(€€€€€€€É•ÑÕÉ¸ì(€€€€€€€€€€€€‰±•…¹•‘}…Ğˆè¹½Ü¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤°(€€€€€€€€€€€€‰•áÁ¥É•‘}±½…Ñ¥½¹Í}É•µ½Ù•ˆè•áÁ¥É•‘}±½…Ñ¥½¹Í}É•µ½Ù•°(€€€€€€€€€€€€‰•áÁ¥É•‘}¥¹Ù¥Ñ•Í}É•µ½Ù•ˆè€ (€€€€€€€€€€€€€€€¥¹Ù¥Ñ•Í}‰•™½É”€´±•¸¡ÍÑ…Ñ•l‰™É¥•¹‘}¥¹Ù¥Ñ•Ì‰t¤(€€€€€€€€€€€€¤°(€€€€€€€€€€€€‰½±‘}¹½Ñ¥™¥…Ñ¥½¹}±½Í}É•µ½Ù•ˆè€ (€€€€€€€€€€€€€€€±½Í}‰•™½É”€´±•¸¡ÍÑ…Ñ•l‰¹½Ñ¥™¥…Ñ¥½¹}±½Ì‰t¤(€€€€€€€€€€€€¤°(€€€€€€€€€€€€‰½¹Ñ…ÑÍ}…É¡¥Ù•‘}ÕÍ•ÉÌˆè½¹Ñ…ÑÍ}…É¡¥Ù•°(€€€€€€€€€€€€‰½¹Ñ…ÑÍ}É•ÍÑ½É•‘}ÕÍ•ÉÌˆè½¹Ñ…ÑÍ}É•ÍÑ½É•°(€€€€€€€€€€€€‰µ¥É…Ñ¥½¹}Í¹…ÁÍ¡½ÑÍ}É•µ½Ù•ˆèµ¥É…Ñ¥½¹}Í¹…ÁÍ¡½ÑÍ}É•µ½Ù•°(€€€€€€€€€€€€‰µ¥É…Ñ¥½¹}Ñ¥­•ÑÍ}É•µ½Ù•ˆèµ¥É…Ñ¥½¹}¡¥ÍÑ½Éå}É•µ½Ù•‘l‰Ñ¥­•ÑÌ‰t°(€€€€€€€€€€€€‰µ¥É…Ñ¥½¹}…Õ‘¥Ñ}É•µ½Ù•ˆèµ¥É…Ñ¥½¹}¡¥ÍÑ½Éå}É•µ½Ù•‘l‰…Õ‘¥Ğ‰t°(€€€€€€€€€€€€‰½É‘•ÉÍ}É•µ½Ù•ˆè€À°(€€€€€€€€€€€€‰Á±…¹Í}‘½İ¹É…‘•ˆè±•¸¡‘½İ¹É…‘•¤°(€€€€€€€ô°€ÈÀÀ((€€€É•ÑÕÉ¸µÕÑ…Ñ•}ÍÑ…Ñ•}…Ñ½µ¥…±±ä¡‘…Ñ…}™¥±”°µÕÑ…Ñ”¤(()‘•˜É•µ¥¹‘•É}Ñ¥µ•}¥¹}İ¥¹‘½Ü¡É•µ¥¹‘•É}Ñ¥µ”°¹½Ü°±…Ñ•}µ¥¹ÕÑ•ÌôĞ¤è(€€€ÑÉäè(€€€€€€€¡½ÕÈ°µ¥¹ÕÑ”€ôm¥¹Ğ¡Á…ÉĞ¤™½ÈÁ…ÉĞ¥¸ÍÑÈ¡É•µ¥¹‘•É}Ñ¥µ”½È€ˆÄÈèÀÀˆ¤¹ÍÁ±¥Ğ ˆèˆ°€Ä¥t(€€€•á•ÁĞ€¡QåÁ•ÉÉ½È°Y…±Õ•ÉÉ½È¤è(€€€€€€€¡½ÕÈ°µ¥¹ÕÑ”€ô€ÄÈ°€À(€€€Í¡•‘Õ±•€ô¹½Ü¹É•Á±…”¡¡½ÕÈõ¡½ÕÈ°µ¥¹ÕÑ”õµ¥¹ÕÑ”°Í•½¹ôÀ°µ¥É½Í•½¹ôÀ¤(€€€‘•±Ñ„€ô¹½Ü€´Í¡•‘Õ±•(€€€É•ÑÕÉ¸Ñ¥µ•‘•±Ñ„ À¤€ğô‘•±Ñ„€ğôÑ¥µ•‘•±Ñ„¡µ¥¹ÕÑ•Ìõ¥¹Ğ¡±…Ñ•}µ¥¹ÕÑ•Ì¤°Í•½¹‘ÌôÔä¤(()‘•˜‰Õ¥±‘}‘…¥±å}¡•­¥¹}™±•à¡¹½Ü°Ñ…É•Ñ}Ñ¥µ”ôˆˆ¤è(€€€€ˆˆ‰…¥±ä¡•¬µ¥¸±•àèÉ••Ñ¥¹œ€¬½ÁÑ¥½¹…°¡½±¥‘…ä‰±•ÍÍ¥¹œ€¬ÅÕ½Ñ”€¬Á½ÍÑ‰…¬¸((€€€-••ÁÌ±…ÍÍ¥ŒÉ••¸€ ŒÀÁäÀÀ¤¡•…‘•Èìƒ3š"G–æÏ–º'4ÕÍ•ÌÁ½ÍÑ‰…¬…Ñ¥½¸õ¡•­¥¸¸(€€€€ˆˆˆ(€€€Ñ½‘…ä€ô¹½Ü¹ÍÑÉ™Ñ¥µ” ˆ•d´•´´•ˆ¤(€€€İ••­‘…å}é €ôl‹¦Ç’â ˆ°€‹¦Ç’ê0ˆ°€‹¦Ç’â$ˆ°€‹¦Ç–nlˆ°€‹¦Ç’êPˆ°€‹¦Ç–´ˆ°€‹¦Çš^”‰um¹½Ü¹İ••­‘…ä ¥t(€€€Ñ¥µ•}‰¥Ğ€ô˜ˆíÑ…É•Ñ}Ñ¥µ•ôˆ¥˜Ñ…É•Ñ}Ñ¥µ”•±Í”€ˆˆ(€€€½Áä€ô€ (€€€€€€€¡½±¥‘…åÍ}ÑÜ¹‘…¥±å}ÁÕÍ¡}½Áä¡¹½Ü¤(€€€€€€€¥˜¡½±¥‘…åÍ}ÑÜ¥Ì¹½Ğ9½¹”(€€€€€€€•±Í”ì(€€€€€€€€€€€€‰É••Ñ¥¹œˆè€‹Šv“¾â<ƒ’î+–’§’â–"¦÷––÷–^;¾ò|ˆ°(€€€€€€€€€€€€‰¡½±¥‘…å}¹…µ”ˆè€ˆˆ°(€€€€€€€€€€€€‰¡½±¥‘…å}‰±•ÍÍ¥¹œˆè€ˆˆ°(€€€€€€€€€€€€‰Á½Í¥Ñ¥Ù•}ÅÕ½Ñ”ˆè€‹š¾?’â–’§j–æÏ–º'¾ò3¦÷šb¿Ö›–ºÛ’êëšr––÷jš»&§ˆ°(€€€€€€€€€€€€‰¥¹ÍÑÉÕÑ¥½¸ˆè€‹¦î{3š"G–æÏ–º'7®/–"ï–º3š"C–‚Ç–"Ã¾ò#’â7R£–7¦Z/ÚË¦‚¾ò$ˆ°(€€€€€€€ô(€€€€¤(€€€Õ…É‘}ÕÉ¤€ô€ (€€€€€€€±¥™™}•¹ÑÉå}ÕÉ°¡½Á•¹}…Ñ¥½¸ô‰Õ…Éˆ¤(€€€€€€€¥˜±¥™™}•¹ÑÉå}ÕÉ°(€€€€€€€•±Í”€‰¡ÑÑÁÌè¼½±¥™˜¹±¥¹”¹µ”¼ÈÀÄÀàĞàÌÌÀµU¥ÅAAeı½Á•¸õÕ…Éˆ(€€€€¤(€€€Í½Í}ÕÉ¤€ô€ (€€€€€€€±¥™™}•¹ÑÉå}ÕÉ°¡½Á•¹}…Ñ¥½¸ô‰Í½Ìˆ¤(€€€€€€€¥˜±¥™™}•¹ÑÉå}ÕÉ°(€€€€€€€•±Í”€‰¡ÑÑÁÌè¼½±¥™˜¹±¥¹”¹µ”¼ÈÀÄÀàĞàÌÌÀµU¥ÅAAeı½Á•¸õÍ½Ìˆ(€€€€¤(€€€‰½‘å}½¹Ñ•¹ÑÌ€ôl(€€€€€€€ì(€€€€€€€€€€€€‰ÑåÁ”ˆè€‰Ñ•áĞˆ°(€€€€€€€€€€€€‰Ñ•áĞˆè½Áål‰É••Ñ¥¹œ‰t°(€€€€€€€€€€€€‰Í¥é”ˆè€‰á°ˆ°(€€€€€€€€€€€€‰İ•¥¡Ğˆè€‰‰½±ˆ°(€€€€€€€€€€€€‰½±½Èˆè€ˆŒÅ„Å„Å„ˆ°(€€€€€€€€€€€€‰İÉ…ÀˆèQÉÕ”°(€€€€€€€ô°(€€€t(€€€¡½±¥‘…å}¹…µ”€ôÍÑÈ¡½Áä¹•Ğ ‰¡½±¥‘…å}¹…µ”ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€¡½±¥‘…å}‰±•ÍÍ¥¹œ€ôÍÑÈ¡½Áä¹•Ğ ‰¡½±¥‘…å}‰±•ÍÍ¥¹œˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€¥˜¡½±¥‘…å}¹…µ”…¹¡½±¥‘…å}‰±•ÍÍ¥¹œè(€€€€€€€‰½‘å}½¹Ñ•¹ÑÌ¹…ÁÁ•¹ (€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€‰ÑåÁ”ˆè€‰Ñ•áĞˆ°(€€€€€€€€€€€€€€€€‰Ñ•áĞˆè˜‹Â~:$í¡½±¥‘…å}¹…µ•ôˆ°(€€€€€€€€€€€€€€€€‰Í¥é”ˆè€‰µˆ°(€€€€€€€€€€€€€€€€‰İ•¥¡Ğˆè€‰‰½±ˆ°(€€€€€€€€€€€€€€€€‰½±½Èˆè€ˆĞÔÌÀäˆ°(€€€€€€€€€€€€€€€€‰İÉ…ÀˆèQÉÕ”°(€€€€€€€€€€€ô(€€€€€€€€¤(€€€€€€€‰½‘å}½¹Ñ•¹ÑÌ¹…ÁÁ•¹ (€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€‰ÑåÁ”ˆè€‰Ñ•áĞˆ°(€€€€€€€€€€€€€€€€‰Ñ•áĞˆè¡½±¥‘…å}‰±•ÍÍ¥¹œ°(€€€€€€€€€€€€€€€€‰Í¥é”ˆè€‰µˆ°(€€€€€€€€€€€€€€€€‰½±½Èˆè€ˆŒäÈĞÀÁˆ°(€€€€€€€€€€€€€€€€‰İÉ…ÀˆèQÉÕ”°(€€€€€€€€€€€ô(€€€€€€€€¤(€€€‰½‘å}½¹Ñ•¹ÑÌ¹…ÁÁ•¹ (€€€€€€€ì(€€€€€€€€€€€€‰ÑåÁ”ˆè€‰Ñ•áĞˆ°(€€€€€€€€€€€€‰Ñ•áĞˆè˜‹Šr í½ÁålÁ½Í¥Ñ¥Ù•}ÅÕ½Ñ”uôˆ°(€€€€€€€€€€€€‰Í¥é”ˆè€‰µˆ°(€€€€€€€€€€€€‰½±½Èˆè€ˆŒÄØØÔÌĞˆ°(€€€€€€€€€€€€‰İÉ…ÀˆèQÉÕ”°(€€€€€€€ô(€€€€¤(€€€‰½‘å}½¹Ñ•¹ÑÌ¹…ÁÁ•¹ (€€€€€€€ì(€€€€€€€€€€€€‰ÑåÁ”ˆè€‰Ñ•áĞˆ°(€€€€€€€€€€€€‰Ñ•áĞˆè½Áål‰¥¹ÍÑÉÕÑ¥½¸‰t°(€€€€€€€€€€€€‰Í¥é”ˆè€‰±œˆ°(€€€€€€€€€€€€‰½±½Èˆè€ˆŒÔÔÔÔÔÔˆ°(€€€€€€€€€€€€‰İÉ…ÀˆèQÉÕ”°(€€€€€€€ô(€€€€¤(€€€…±Ñ}Á…ÉÑÌ€ôm½Áål‰É••Ñ¥¹œ‰t°Ñ½‘…åt(€€€¥˜¡½±¥‘…å}¹…µ”è(€€€€€€€…±Ñ}Á…ÉÑÌ¹…ÁÁ•¹¡¡½±¥‘…å}¹…µ”¤(€€€¥˜Ñ…É•Ñ}Ñ¥µ”è(€€€€€€€…±Ñ}Á…ÉÑÌ¹…ÁÁ•¹¡Ñ…É•Ñ}Ñ¥µ”¤(€€€É•ÑÕÉ¸ì(€€€€€€€€‰ÑåÁ”ˆè€‰™±•àˆ°(€€€€€€€€‰…±ÑQ•áĞˆè€ˆ€ˆ¹©½¥¸¡…±Ñ}Á…ÉÑÌ¥lèĞÀÁt°(€€€€€€€€‰½¹Ñ•¹ÑÌˆèì(€€€€€€€€€€€€‰ÑåÁ”ˆè€‰‰Õ‰‰±”ˆ°(€€€€€€€€€€€€‰Í¥é”ˆè€‰µ•„ˆ°(€€€€€€€€€€€€‰¡•…‘•Èˆèì(€€€€€€€€€€€€€€€€‰ÑåÁ”ˆè€‰‰½àˆ°(€€€€€€€€€€€€€€€€‰±…å½ÕĞˆè€‰Ù•ÉÑ¥…°ˆ°(€€€€€€€€€€€€€€€€‰ÍÁ…¥¹œˆè€‰áÌˆ°(€€€€€€€€€€€€€€€€‰‰…­É½Õ¹‘½±½Èˆè€ˆŒÀÁäÀÀˆ°(€€€€€€€€€€€€€€€€‰Á…‘‘¥¹Q½Àˆè€‰±œˆ°(€€€€€€€€€€€€€€€€‰Á…‘‘¥¹	½ÑÑ½´ˆè€‰±œˆ°(€€€€€€€€€€€€€€€€‰Á…‘‘¥¹MÑ…ÉĞˆè€‰±œˆ°(€€€€€€€€€€€€€€€€‰Á…‘‘¥¹¹ˆè€‰±œˆ°(€€€€€€€€€€€€€€€€‰½¹Ñ•¹ÑÌˆèl(€€€€€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€€€€€‰ÑåÁ”ˆè€‰Ñ•áĞˆ°(€€€€€€€€€€€€€€€€€€€€€€€€‰Ñ•áĞˆè€‹š¾?š^—–æÏ–º$ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€‰½±½Èˆè€ˆˆ°(€€€€€€€€€€€€€€€€€€€€€€€€‰Í¥é”ˆè€‰±œˆ°(€€€€€€€€€€€€€€€€€€€€€€€€‰İ•¥¡Ğˆè€‰‰½±ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€‰İÉ…ÀˆèQÉÕ”°(€€€€€€€€€€€€€€€€€€€ô°(€€€€€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€€€€€‰ÑåÁ”ˆè€‰Ñ•áĞˆ°(€€€€€€€€€€€€€€€€€€€€€€€€‰Ñ•áĞˆè˜‹Â~NíÑ½‘…åôíİ••­‘…å}é¡õíÑ¥µ•}‰¥Ñôˆ¹ÍÑÉ¥À ¤°(€€€€€€€€€€€€€€€€€€€€€€€€‰½±½Èˆè€ˆˆ°(€€€€€€€€€€€€€€€€€€€€€€€€‰Í¥é”ˆè€‰á°ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€‰İ•¥¡Ğˆè€‰‰½±ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€‰İÉ…ÀˆèQÉÕ”°(€€€€€€€€€€€€€€€€€€€ô°(€€€€€€€€€€€€€€€t°(€€€€€€€€€€€ô°(€€€€€€€€€€€€‰‰½‘äˆèì(€€€€€€€€€€€€€€€€‰ÑåÁ”ˆè€‰‰½àˆ°(€€€€€€€€€€€€€€€€‰±…å½ÕĞˆè€‰Ù•ÉÑ¥…°ˆ°(€€€€€€€€€€€€€€€€‰ÍÁ…¥¹œˆè€‰µˆ°(€€€€€€€€€€€€€€€€‰Á…‘‘¥¹±°ˆè€‰±œˆ°(€€€€€€€€€€€€€€€€‰½¹Ñ•¹ÑÌˆè‰½‘å}½¹Ñ•¹ÑÌ°(€€€€€€€€€€€ô°(€€€€€€€€€€€€‰™½½Ñ•Èˆèì(€€€€€€€€€€€€€€€€‰ÑåÁ”ˆè€‰‰½àˆ°(€€€€€€€€€€€€€€€€‰±…å½ÕĞˆè€‰Ù•ÉÑ¥…°ˆ°(€€€€€€€€€€€€€€€€‰ÍÁ…¥¹œˆè€‰Í´ˆ°(€€€€€€€€€€€€€€€€‰Á…‘‘¥¹±°ˆè€‰±œˆ°(€€€€€€€€€€€€€€€€‰‰…­É½Õ¹‘½±½Èˆè€ˆˆ°(€€€€€€€€€€€€€€€€‰½¹Ñ•¹ÑÌˆèl(€€€€€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€€€€€‰ÑåÁ”ˆè€‰‰ÕÑÑ½¸ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€‰…Ñ¥½¸ˆèì(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰ÑåÁ”ˆè€‰Á½ÍÑ‰…¬ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰±…‰•°ˆè€‹Šrƒš"G–æÏ–º$ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰‘…Ñ„ˆè€‰…Ñ¥½¸õ¡•­¥¸ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰‘¥ÍÁ±…åQ•áĞˆè€‹š"G–æÏ–º$ˆ°(€€€€€€€€€€€€€€€€€€€€€€€ô°(€€€€€€€€€€€€€€€€€€€€€€€€‰ÍÑå±”ˆè€‰ÁÉ¥µ…Éäˆ°(€€€€€€€€€€€€€€€€€€€€€€€€‰½±½Èˆè€ˆŒÄÙÌÑˆ°(€€€€€€€€€€€€€€€€€€€€€€€€‰¡•¥¡Ğˆè€‰µˆ°(€€€€€€€€€€€€€€€€€€€ô°(€€€€€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€€€€€‰ÑåÁ”ˆè€‰‰ÕÑÑ½¸ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€‰…Ñ¥½¸ˆèì‰ÑåÁ”ˆè€‰ÕÉ¤ˆ°€‰±…‰•°ˆè€‹Â~n‡¾â<ƒ–º'–£–º#¢¶Üˆ°€‰ÕÉ¤ˆèÕ…É‘}ÕÉ¥ô°(€€€€€€€€€€€€€€€€€€€€€€€€‰ÍÑå±”ˆè€‰ÁÉ¥µ…Éäˆ°(€€€€€€€€€€€€€€€€€€€€€€€€‰½±½Èˆè€ˆŒÈÔØÍˆ°(€€€€€€€€€€€€€€€€€€€€€€€€‰¡•¥¡Ğˆè€‰µˆ°(€€€€€€€€€€€€€€€€€€€ô°(€€€€€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€€€€€‰ÑåÁ”ˆè€‰‰ÕÑÑ½¸ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€‰…Ñ¥½¸ˆèì‰ÑåÁ”ˆè€‰ÕÉ¤ˆ°€‰±…‰•°ˆè€‹¦r¢š–æ¯–şdˆ°€‰ÕÉ¤ˆèÍ½Í}ÕÉ¥ô°(€€€€€€€€€€€€€€€€€€€€€€€€‰ÍÑå±”ˆè€‰ÁÉ¥µ…Éäˆ°(€€€€€€€€€€€€€€€€€€€€€€€€‰½±½Èˆè€ˆÈØÈØˆ°(€€€€€€€€€€€€€€€€€€€€€€€€‰¡•¥¡Ğˆè€‰µˆ°(€€€€€€€€€€€€€€€€€€€ô°(€€€€€€€€€€€€€€€t°(€€€€€€€€€€€ô°(€€€€€€€ô°(€€€ô(()‘•˜}µ…É­}±¥¹•}ÁÕÍ¡}‰±½­•¡ÕÍ•È°•áŒ¤è(€€€€ˆˆ‰5…É¬‰±½­•€¼½¹”ÕÍ•ÉÌÍ¼™ÕÑÕÉ”‰É½…‘…ÍÑÌÍ­¥ÀÑ¡•´¸ˆˆˆ(€€€½‘”€ô9½¹”(€€€¥˜¥Í¥¹ÍÑ…¹”¡•áŒ°ÕÉ±±¥ˆ¹•ÉÉ½È¹!QQAÉÉ½È¤è(€€€€€€€½‘”€ô•áŒ¹½‘”(€€€Ñ•áĞ€ôÍÑÈ¡•áŒ½È€ˆˆ¤¹±½İ•È ¤(€€€¥˜½‘”¥¸ìĞÀÄ°€ĞÀÌ°€ĞÀÑô½È€‰¹½Ğ„™É¥•¹ˆ¥¸Ñ•áĞ½È€‰‰±½­•ˆ¥¸Ñ•áĞè(€€€€€€€ÕÍ•Él‰±¥¹•}ÁÕÍ¡}‰±½­•‰t€ôQÉÕ”(€€€€€€€ÕÍ•Él‰±¥¹•}ÁÕÍ¡}‰±½­•‘}…Ğ‰t€ô‘…Ñ•Ñ¥µ”¹¹½Ü ¤¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤(€€€€€€€É•ÑÕÉ¸QÉÕ”(€€€É•ÑÕÉ¸…±Í”(()‘•˜}µ…É­}¡•­¥¹}É•µ¥¹‘•É}Í±½ÑÌ¡ÕÍ•È°Ñ½‘…ä°Ñ¥µ•Ì°‘Õ•}Ñ¥µ•Ì¤è(€€€Í•¹Ñ}Í±½ÑÌ€ô‘¥Ğ¡ÕÍ•È¹•Ğ ‰¡•­¥¹}É•µ¥¹‘•É}Í•¹Ñ}Í±½ÑÌˆ¤½Èíô¤(€€€Í•¹Ñ}Ñ½‘…ä€ôÍ•Ğ¡Í•¹Ñ}Í±½ÑÌ¹•Ğ¡Ñ½‘…ä¤½Èmt¤(€€€Í•¹Ñ}Ñ½‘…ä¹ÕÁ‘…Ñ”¡‘Õ•}Ñ¥µ•Ì½ÈÑ¥µ•Ì½Èmt¤(€€€Í•¹Ñ}Í±½ÑÍmÑ½‘…åt€ôÍ½ÉÑ•¡Í•¹Ñ}Ñ½‘…ä¤(€€€­••Á}‘…Ñ•Ì€ôÍ½ÉÑ•¡Í•¹Ñ}Í±½ÑÌ¹­•åÌ ¤¥l´ÌÀét(€€€ÕÍ•Él‰¡•­¥¹}É•µ¥¹‘•É}Í•¹Ñ}Í±½ÑÌ‰t€ôíèÍ•¹Ñ}Í±½ÑÍm‘t™½È¥¸­••Á}‘…Ñ•Íô(€€€±•…å}‘…Ñ•Ì€ôÍ•Ğ¡ÕÍ•È¹•Ğ ‰¡•­¥¹}É•µ¥¹‘•É}Í•¹Ñ}‘…Ñ•Ìˆ¤½Èmt¤(€€€¥˜Í•Ğ¡Ñ¥µ•Ì½Èmt¤¹¥ÍÍÕ‰Í•Ğ¡Í•¹Ñ}Ñ½‘…ä¤è(€€€€€€€±•…å}‘…Ñ•Ì¹…‘¡Ñ½‘…ä¤(€€€€€€€ÕÍ•Él‰¡•­¥¹}É•µ¥¹‘•É}Í•¹Ñ}‘…Ñ•Ì‰t€ôÍ½ÉÑ•¡±•…å}‘…Ñ•Ì¥l´ÌÀét(()‘•˜Í•¹‘}¡•­¥¹}É•µ¥¹‘•ÉÌ¡½¹™¥œ¤è(€€€€ˆˆ‰5½É¹¥¹œ½Í±½ĞÉ½¸èÍ­¥ÀÕÍ•ÉÌ…±É•…‘ä¡•­•¥¸€¡Q…¥Á•¤¤¸AÉ•™•ÈÁÉ”µ¡•¬µ¥¸É•µ¥¹¸ˆˆˆ(€€€Ñ½­•¸€ô½¹™¥œ¹•Ğ ‰1%9}!991}MM}Q=-8ˆ¤½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}!991}MM}Q=-8ˆ°€ˆˆ¤(€€€¥˜¹½ĞÑ½­•¸è(€€€€€€€É•ÑÕÉ¸ì‰Í•¹Ğˆè€À°€‰Í­¥ÁÁ•ˆè€À°€‰•ÉÉ½Èˆè€‰1%9}!991}MM}Q=-8¥Ì¹½ĞÍ•Ğ‰ô°€ĞÀÀ((€€€‘…Ñ…}™¥±”€ô½¹™¥l‰Q}%1‰t(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€Í•¹‘•È€ô½¹™¥œ¹•Ğ ‰1%9}AUM!}M9Hˆ¤½È±¥¹•}ÁÕÍ¡}µ•ÍÍ…”(€€€¹½Ü€ôÕÉÉ•¹Ñ}…ÁÁ}Ñ¥µ”¡½¹™¥œ¤(€€€¥˜¹½Ğ±¥¹•}¹½¹}•µ•É•¹å}ÁÕÍ¡}…±±½İ•¡ÍÑ…Ñ”°½¹™¥œ°¹½Ü¤è(€€€€€€€É•ÑÕÉ¸±¥¹•}‰Õ‘•Ñ}‰±½­•‘}É•ÍÁ½¹Í”¡ÍÑ…Ñ”°½¹™¥œ°¹½Ü¤(€€€Ñ½‘…ä€ô¹½Ü¹ÍÑÉ™Ñ¥µ” ˆ•d´•´´•ˆ¤(€€€Í•¹Ğ€ô€À(€€€Í­¥ÁÁ•€ô€À(€€€É•ÍÕ±ÑÌ€ômt(€€€ÍåÍÑ•µ}•ÉÉ½È€ô…±Í”((€€€™½ÈÕÍ•È¥¸ÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ°íô¤¹Ù…±Õ•Ì ¤è(€€€€€€€±¥¹•}ÕÍ•É}¥€ôÕÍ•È¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤(€€€€€€€¥˜¹½Ğ±¥¹•}ÕÍ•É}¥è(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¥˜ÕÍ•È¹•Ğ ‰±¥¹•}ÁÕÍ¡}‰±½­•ˆ¤è(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¥˜ÕÍ•È¹•Ğ ‰µ•µ‰•ÉÍ¡¥Á}Á…ÕÍ•ˆ¤½È¹½Ğµ•µ‰•ÉÍ¡¥Á}…•ÍÍ}…Ñ¥Ù”¡ÕÍ•È°¹½Ü¤è(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¥˜¹½Ğ‰½½°¡ÕÍ•È¹•Ğ ‰‘…¥±å}¡•­¥¹}É•µ¥¹‘•É}•¹…‰±•ˆ°QÉÕ”¤¤è(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¥˜ÁÉ½™¥±•}¥Í}Ñ½‘…å}¡•­•¡ÕÍ•È°½¹™¥œõ½¹™¥œ°¹½Üõ¹½Ü¤è(€€€€€€€€€€€€Œ!•…°µ¥ÍÍ¥¹œQ…¥Á•¤¡¥ÍÑ½ÉäÍ¼±…Ñ•ÈÉ½¸½ÍÑ…ÑÕÌÍÑ…ä½¹Í¥ÍÑ•¹Ğ(€€€€€€€€€€€¡¥ÍĞ€ôÍ•Ğ¡ÕÍ•È¹•Ğ ‰¡¥ÍÑ½Éäˆ¤½Èmt¤(€€€€€€€€€€€¥˜Ñ½‘…ä¹½Ğ¥¸¡¥ÍĞè(€€€€€€€€€€€€€€€¡¥ÍĞ¹…‘¡Ñ½‘…ä¤(€€€€€€€€€€€€€€€ÕÍ•Él‰¡¥ÍÑ½Éä‰t€ôÍ½ÉÑ•¡¡¥ÍĞ¤(€€€€€€€€€€€€Œƒ’î+š^—–ŞË–‚Ç–æÏ–º$ƒŠHƒV—¦;–B3š^—–&§¦’cš:K¢/š>C¦K¾ò#š¢g¢¢`Í±½ÑÏ¾ò3¦ÿ–7–ú3ê3¢ª“š:£¾ò$(€€€€€€€€€€€Ñ¥µ•Ì€ôÉ•µ¥¹‘•É}Ñ¥µ•Í}™½É}ÁÉ½™¥±”¡ÕÍ•È¤½ÈlˆÄÈèÀÀ‰t(€€€€€€€€€€€}µ…É­}¡•­¥¹}É•µ¥¹‘•É}Í±½ÑÌ¡ÕÍ•È°Ñ½‘…ä°Ñ¥µ•Ì°Ñ¥µ•Ì¤(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”((€€€€€€€Ñ¥µ•Ì€ôÉ•µ¥¹‘•É}Ñ¥µ•Í}™½É}ÁÉ½™¥±”¡ÕÍ•È¤(€€€€€€€Í•¹Ñ}Í±½ÑÌ€ô‘¥Ğ¡ÕÍ•È¹•Ğ ‰¡•­¥¹}É•µ¥¹‘•É}Í•¹Ñ}Í±½ÑÌˆ¤½Èíô¤(€€€€€€€Í•¹Ñ}Ñ½‘…ä€ôÍ•Ğ¡Í•¹Ñ}Í±½ÑÌ¹•Ğ¡Ñ½‘…ä¤½Èmt¤((€€€€€€€€Œƒnã–ºç¢"+& ëVÛ–’§–ŞËR£–Z»’âš^—šrš¢g¢¢c¦¦8ƒŠHƒ¢š[
ëšr³¢ò«–ŞËš>C¦H(€€€€€€€±•…å}‘…Ñ•Ì€ôÍ•Ğ¡ÕÍ•È¹•Ğ ‰¡•­¥¹}É•µ¥¹‘•É}Í•¹Ñ}‘…Ñ•Ìˆ¤½Èmt¤(€€€€€€€¥˜Ñ½‘…ä¥¸±•…å}‘…Ñ•Ì…¹¹½ĞÍ•¹Ñ}Ñ½‘…äè(€€€€€€€€€€€½¹Ñ¥¹Õ”((€€€€€€€‘Õ•}Õ¹Í•¹Ğ€ôl(€€€€€€€€€€€Ğ(€€€€€€€€€€€™½ÈĞ¥¸Ñ¥µ•Ì(€€€€€€€€€€€¥˜É•µ¥¹‘•É}Ñ¥µ•}¥¹}İ¥¹‘½Ü¡Ğ°¹½Ü°±…Ñ•}µ¥¹ÕÑ•ÌôĞ¤…¹Ğ¹½Ğ¥¸Í•¹Ñ}Ñ½‘…ä(€€€€€€€t(€€€€€€€¥˜¹½Ğ‘Õ•}Õ¹Í•¹Ğè(€€€€€€€€€€€½¹Ñ¥¹Õ”((€€€€€€€€Œƒ–B3’â’êS–"¦Bcšf¦ZOª_–>«š:£’âš²‡¾òo¢òš^§šò?š:'jšfšº×’â7¢s¦’æ’â7š¢g¢¢c(€€€€€€€Ñ…É•Ñ}Ñ¥µ”€ô‘Õ•}Õ¹Í•¹Ñl´Åt(€€€€€€€‘•±¥Ù•Éå}­•ä€ô˜‰¡•­¥¸éíÑ½‘…åôéíÑ…É•Ñ}Ñ¥µ•ôˆ(€€€€€€€}É•½É‘}±…Õ¹¡}‘•±¥Ù•Éä (€€€€€€€€€€€ÍÑ…Ñ”°‘•±¥Ù•Éå}­•ä°€‰¡•­¥¸ˆ°±¥¹•}ÕÍ•É}¥°€‰•áÁ•Ñ•ˆ(€€€€€€€€¤(€€€€€€€¥˜¹½ĞÁÕÍ¡}…ÑÑ•µÁÑ}…±±½İ•¡ÕÍ•È°‘•±¥Ù•Éå}­•ä¤è(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€µ•ÍÍ…”€ô‰Õ¥±‘}‘…¥±å}¡•­¥¹}™±•à¡¹½Ü°Ñ…É•Ñ}Ñ¥µ”õÑ…É•Ñ}Ñ¥µ”¤(€€€€€€€ÑÉäè(€€€€€€€€€€€É•ÍÕ±Ğ€ôÍ•¹‘•È¡Ñ½­•¸°±¥¹•}ÕÍ•É}¥°µ•ÍÍ…”¤(€€€€€€€€€€€}±•…É}ÁÕÍ¡}‘•±¥Ù•Éå}™…¥±ÕÉ”¡ÕÍ•È°‘•±¥Ù•Éå}­•ä¤(€€€€€€€€€€€}É•½É‘}±…Õ¹¡}‘•±¥Ù•Éä (€€€€€€€€€€€€€€€ÍÑ…Ñ”°‘•±¥Ù•Éå}­•ä°€‰¡•­¥¸ˆ°±¥¹•}ÕÍ•É}¥°€‰Í•¹Ğˆ(€€€€€€€€€€€€¤(€€€€€€€€€€€}µ…É­}¡•­¥¹}É•µ¥¹‘•É}Í±½ÑÌ¡ÕÍ•È°Ñ½‘…ä°Ñ¥µ•Ì°‘Õ•}Õ¹Í•¹Ğ¤(€€€€€€€€€€€•¹ÍÕÉ•}…Ñ¥Ù•}½Ù•É‘Õ•}•Ù•¹Ğ¡ÕÍ•È°Ñ…É•Ñ}Ñ¥µ”°¹½Ü¤(€€€€€€€€€€€…ÁÁ•¹‘}¹½Ñ¥™¥…Ñ¥½¹}±½œ¡ÍÑ…Ñ”°€‰¡•­¥¸ˆ°±¥¹•}ÕÍ•É}¥°€‰Í•¹Ğˆ°µ•ÍÍ…”°©Í½¸¹‘ÕµÁÌ¡É•ÍÕ±Ğ°•¹ÍÕÉ•}…Í¥¤õ…±Í”¤¤(€€€€€€€€€€€É•½É‘}±¥¹•}µ•ÍÍ…•}ÕÍ…” (€€€€€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€€€€€…Ñ•½Éäô‰¡•­¥¸ˆ°(€€€€€€€€€€€€€€€½İ¹•É}±¥¹•}ÕÍ•É}¥õ±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€É•¥Á¥•¹Ñ}½Õ¹ĞôÄ°(€€€€€€€€€€€€€€€•Ù•¹Ñ}¥õ‘•±¥Ù•Éå}­•ä°(€€€€€€€€€€€€€€€Í•¹Ñ}…Ğõ¹½Ü°(€€€€€€€€€€€€¤(€€€€€€€€€€€Í•¹Ğ€¬ô€Ä(€€€€€€€€€€€É•ÍÕ±ÑÌ¹…ÁÁ•¹¡ì‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°€‰É•µ¥¹‘•É}Ñ¥µ”ˆèÑ…É•Ñ}Ñ¥µ”°€‰É•ÍÕ±ĞˆèÉ•ÍÕ±Ñô¤(€€€€€€€€€€€€ŒƒšZçš†#–6Ï–Â¾ò?–ŞË–"Ãšr¾òk–B3š^—šr–’k¦f–âÛ’âš²‡š>C¦K¾ò#’â7šÒ_&#¾ò$(€€€€€€€€€€€¥˜Í¡½Õ±‘}½™™•É}•áÁ¥Éå}É•µ¥¹¡ÕÍ•È°¹½Ü¤è(€€€€€€€€€€€€€€€•áÁ¥Éå}µÍœ€ô‰Õ¥±‘}•áÁ¥Éå}É•µ¥¹‘}™±•à¡ÕÍ•È°¹½Ü¤(€€€€€€€€€€€€€€€•áÁ¥Éå}­•ä€ô˜‰•áÁ¥Éå}É•µ¥¹éíÑ½‘…åôˆ(€€€€€€€€€€€€€€€¥˜¹½ĞÁÕÍ¡}…ÑÑ•µÁÑ}…±±½İ•¡ÕÍ•È°•áÁ¥Éå}­•ä¤è(€€€€€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€•áÁ¥Éå}É•ÍÕ±Ğ€ôÍ•¹‘•È¡Ñ½­•¸°±¥¹•}ÕÍ•É}¥°•áÁ¥Éå}µÍœ¤(€€€€€€€€€€€€€€€€€€€}±•…É}ÁÕÍ¡}‘•±¥Ù•Éå}™…¥±ÕÉ”¡ÕÍ•È°•áÁ¥Éå}­•ä¤(€€€€€€€€€€€€€€€€€€€µ…É­}•áÁ¥Éå}É•µ¥¹‘}Í•¹Ğ¡ÕÍ•È°¹½Ü¤(€€€€€€€€€€€€€€€€€€€…ÁÁ•¹‘}¹½Ñ¥™¥…Ñ¥½¹}±½œ (€€€€€€€€€€€€€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€€€€€€€€€€€€€€‰•áÁ¥Éå}É•µ¥¹ˆ°(€€€€€€€€€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€€€€€€€€€€‰Í•¹Ğˆ°(€€€€€€€€€€€€€€€€€€€€€€€•áÁ¥Éå}µÍœ°(€€€€€€€€€€€€€€€€€€€€€€€©Í½¸¹‘ÕµÁÌ¡•áÁ¥Éå}É•ÍÕ±Ğ°•¹ÍÕÉ•}…Í¥¤õ…±Í”¤°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áÁ¥Éå}•áŒè(€€€€€€€€€€€€€€€€€€€™…¥±ÕÉ”€ô}É•½É‘}Í¡•‘Õ±•‘}ÁÕÍ¡}™…¥±ÕÉ” (€€€€€€€€€€€€€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€€€€€€€€€€€€€ÕÍ•È°(€€€€€€€€€€€€€€€€€€€€€€€•áÁ¥Éå}­•ä°(€€€€€€€€€€€€€€€€€€€€€€€€‰•áÁ¥Éå}É•µ¥¹ˆ°(€€€€€€€€€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€€€€€€€€€•áÁ¥Éå}µÍœ°(€€€€€€€€€€€€€€€€€€€€€€€•áÁ¥Éå}•áŒ°(€€€€€€€€€€€€€€€€€€€€€€€¹½Ü°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€¥˜™…¥±ÕÉ•l‰­¥¹‰t€ôô€‰ÍåÍÑ•´ˆè(€€€€€€€€€€€€€€€€€€€€€€€ÍåÍÑ•µ}•ÉÉ½È€ôQÉÕ”(€€€€€€€€€€€€€€€€€€€€€€€‰É•…¬(€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€™…¥±ÕÉ”€ô}É•½É‘}Í¡•‘Õ±•‘}ÁÕÍ¡}™…¥±ÕÉ” (€€€€€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€€€€€ÕÍ•È°(€€€€€€€€€€€€€€€‘•±¥Ù•Éå}­•ä°(€€€€€€€€€€€€€€€€‰¡•­¥¸ˆ°(€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€µ•ÍÍ…”°(€€€€€€€€€€€€€€€•áŒ°(€€€€€€€€€€€€€€€¹½Ü°(€€€€€€€€€€€€¤(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€É•ÍÕ±ÑÌ¹…ÁÁ•¹¡ì‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°€‰•ÉÉ½ÈˆèÍÑÈ¡•áŒ¥ô¤(€€€€€€€€€€€¥˜™…¥±ÕÉ•l‰­¥¹‰t€ôô€‰ÍåÍÑ•´ˆè(€€€€€€€€€€€€€€€ÍåÍÑ•µ}•ÉÉ½È€ôQÉÕ”(€€€€€€€€€€€€€€€‰É•…¬((€€€Í…Ù•}ÍÑ…Ñ”¡‘…Ñ…}™¥±”°ÍÑ…Ñ”¤(€€€É•ÑÕÉ¸ì(€€€€€€€€‰Í•¹ĞˆèÍ•¹Ğ°(€€€€€€€€‰Í­¥ÁÁ•ˆèÍ­¥ÁÁ•°(€€€€€€€€‰É•ÍÕ±ÑÌˆèÉ•ÍÕ±ÑÌ°(€€€€€€€€‰ÍåÍÑ•µ}•ÉÉ½ÈˆèÍåÍÑ•µ}•ÉÉ½È°(€€€ô°€ÈÀÀ(()‘•˜‰É½…‘…ÍÑ}¡•­¥¹}É•µ¥¹‘•ÉÌ¡½¹™¥œ°€¨°Á…ÕÍ•}•Ù•ÉäôÈÀ°Á…ÕÍ•}Í•½¹‘ÌôÄ¸À¤è(€€€€ˆˆ‹¦7šZÃš:£šJ·¾òk¦šZÃš¢‡švÿÖ›š&šr'–ŞË¢¢ï–+šr–N‡¾ò#šr$±¥¹•}ÕÍ•É}¥“¾ò'¾ò3–B¯’î+š^—–ŞËÂ÷–"Ã¢((€€€€´ƒ¢ŞÏ¦8±¥¹•}ÁÕÍ¡}‰±½­•(€€€€´ƒ–"š&çšj¯–s’î—¦f7’ö81%9É…Ñ”µ±¥µ¥Ğƒ¦Š£¦j¨(€€€€´ƒš¢g¢¢c’î+š^”É•µ¥¹‘•ÈÍ±½ÑÏ¾ò3¦ÿ–4É½¸ƒ¢7–ú3–7šÒ_& (€€€€ˆˆˆ(€€€¥µÁ½ÉĞÑ¥µ”…Ì}Ñ¥µ”((€€€Ñ½­•¸€ô½¹™¥œ¹•Ğ ‰1%9}!991}MM}Q=-8ˆ¤½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}!991}MM}Q=-8ˆ°€ˆˆ¤(€€€¥˜¹½ĞÑ½­•¸è(€€€€€€€É•ÑÕÉ¸ì‰Í•¹Ğˆè€À°€‰Í­¥ÁÁ•ˆè€À°€‰•ÉÉ½Èˆè€‰1%9}!991}MM}Q=-8¥Ì¹½ĞÍ•Ğ‰ô°€ĞÀÀ((€€€‘…Ñ…}™¥±”€ô½¹™¥l‰Q}%1‰t(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€Í•¹‘•È€ô½¹™¥œ¹•Ğ ‰1%9}AUM!}M9Hˆ¤½È±¥¹•}ÁÕÍ¡}µ•ÍÍ…”(€€€¹½Ü€ôÕÉÉ•¹Ñ}…ÁÁ}Ñ¥µ”¡½¹™¥œ¤(€€€¥˜¹½Ğ±¥¹•}¹½¹}•µ•É•¹å}ÁÕÍ¡}…±±½İ•¡ÍÑ…Ñ”°½¹™¥œ°¹½Ü¤è(€€€€€€€É•ÑÕÉ¸±¥¹•}‰Õ‘•Ñ}‰±½­•‘}É•ÍÁ½¹Í”¡ÍÑ…Ñ”°½¹™¥œ°¹½Ü¤(€€€Ñ½‘…ä€ô¹½Ü¹ÍÑÉ™Ñ¥µ” ˆ•d´•´´•ˆ¤(€€€µ•ÍÍ…”€ô‰Õ¥±‘}‘…¥±å}¡•­¥¹}™±•à¡¹½Ü°Ñ…É•Ñ}Ñ¥µ”ôˆˆ¤(€€€Í•¹Ğ€ô€À(€€€Í­¥ÁÁ•€ô€À(€€€‰±½­•€ô€À(€€€É•ÍÕ±ÑÌ€ômt(€€€ÁÕÍ¡}½Õ¹Ğ€ô€À((€€€™½ÈÕÍ•È¥¸ÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ°íô¤¹Ù…±Õ•Ì ¤è(€€€€€€€±¥¹•}ÕÍ•É}¥€ôÍÑÈ¡ÕÍ•È¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€¥˜¹½Ğ±¥¹•}ÕÍ•É}¥è(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¥˜ÕÍ•È¹•Ğ ‰±¥¹•}ÁÕÍ¡}‰±½­•ˆ¤è(€€€€€€€€€€€‰±½­•€¬ô€Ä(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€Ñ¥µ•Ì€ôÉ•µ¥¹‘•É}Ñ¥µ•Í}™½É}ÁÉ½™¥±”¡ÕÍ•È¤(€€€€€€€ÑÉäè(€€€€€€€€€€€É•ÍÕ±Ğ€ôÍ•¹‘•È¡Ñ½­•¸°±¥¹•}ÕÍ•É}¥°µ•ÍÍ…”¤(€€€€€€€€€€€}µ…É­}¡•­¥¹}É•µ¥¹‘•É}Í±½ÑÌ¡ÕÍ•È°Ñ½‘…ä°Ñ¥µ•Ì°Ñ¥µ•Ì¤(€€€€€€€€€€€ÕÍ•Él‰¡•­¥¹}‰É½…‘…ÍÑ}Í•¹Ñ}‘…Ñ•Ì‰t€ôÍ½ÉÑ• (€€€€€€€€€€€€€€€Í•Ğ¡ÕÍ•È¹•Ğ ‰¡•­¥¹}‰É½…‘…ÍÑ}Í•¹Ñ}‘…Ñ•Ìˆ¤½Èmt¤ğíÑ½‘…åô(€€€€€€€€€€€€¥l´ÌÀét(€€€€€€€€€€€…ÁÁ•¹‘}¹½Ñ¥™¥…Ñ¥½¹}±½œ (€€€€€€€€€€€€€€€ÍÑ…Ñ”°€‰¡•­¥¹}‰É½…‘…ÍĞˆ°±¥¹•}ÕÍ•É}¥°€‰Í•¹Ğˆ°µ•ÍÍ…”°©Í½¸¹‘ÕµÁÌ¡É•ÍÕ±Ğ°•¹ÍÕÉ•}…Í¥¤õ…±Í”¤(€€€€€€€€€€€€¤(€€€€€€€€€€€Í•¹Ğ€¬ô€Ä(€€€€€€€€€€€ÁÕÍ¡}½Õ¹Ğ€¬ô€Ä(€€€€€€€€€€€É•ÍÕ±ÑÌ¹…ÁÁ•¹¡ì‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°€‰É•ÍÕ±ĞˆèÉ•ÍÕ±Ñô¤(€€€€€€€€€€€¥˜Á…ÕÍ•}•Ù•Éä…¹ÁÕÍ¡}½Õ¹Ğ€”¥¹Ğ¡Á…ÕÍ•}•Ù•Éä¤€ôô€Àè(€€€€€€€€€€€€€€€}Ñ¥µ”¹Í±••À¡™±½…Ğ¡Á…ÕÍ•}Í•½¹‘Ì¤¤(€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€¥˜}µ…É­}±¥¹•}ÁÕÍ¡}‰±½­•¡ÕÍ•È°•áŒ¤è(€€€€€€€€€€€€€€€‰±½­•€¬ô€Ä(€€€€€€€€€€€€€€€…ÁÁ•¹‘}¹½Ñ¥™¥…Ñ¥½¹}±½œ¡ÍÑ…Ñ”°€‰¡•­¥¹}‰É½…‘…ÍĞˆ°±¥¹•}ÕÍ•É}¥°€‰‰±½­•ˆ°µ•ÍÍ…”°ÍÑÈ¡•áŒ¤¤(€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€…ÁÁ•¹‘}¹½Ñ¥™¥…Ñ¥½¹}±½œ¡ÍÑ…Ñ”°€‰¡•­¥¹}‰É½…‘…ÍĞˆ°±¥¹•}ÕÍ•É}¥°€‰™…¥±•ˆ°µ•ÍÍ…”°ÍÑÈ¡•áŒ¤¤(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€É•ÍÕ±ÑÌ¹…ÁÁ•¹¡ì‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°€‰•ÉÉ½ÈˆèÍÑÈ¡•áŒ¥ô¤((€€€Í…Ù•}ÍÑ…Ñ”¡‘…Ñ…}™¥±”°ÍÑ…Ñ”¤(€€€¡½±¥‘…ä€ô¡½±¥‘…åÍ}ÑÜ¹¡½±¥‘…å}™½È¡¹½Ü¤¥˜¡½±¥‘…åÍ}ÑÜ¥Ì¹½Ğ9½¹”•±Í”9½¹”(€€€É•ÑÕÉ¸ì(€€€€€€€€‰Í•¹ĞˆèÍ•¹Ğ°(€€€€€€€€‰Í­¥ÁÁ•ˆèÍ­¥ÁÁ•°(€€€€€€€€‰‰±½­•ˆè‰±½­•°(€€€€€€€€‰µ½‘”ˆè€‰‰É½…‘…ÍĞˆ°(€€€€€€€€‰¡½±¥‘…äˆè€¡¡½±¥‘…ä½Èíô¤¹•Ğ ‰¹…µ”ˆ¤¥˜¡½±¥‘…ä•±Í”9½¹”°(€€€€€€€€‰Á½Í¥Ñ¥Ù•}ÅÕ½Ñ”ˆè¡½±¥‘…åÍ}ÑÜ¹Á½Í¥Ñ¥Ù•}ÅÕ½Ñ•}™½È¡¹½Ü¤¥˜¡½±¥‘…åÍ}ÑÜ¥Ì¹½Ğ9½¹”•±Í”9½¹”°(€€€€€€€€‰É•ÍÕ±ÑÌˆèÉ•ÍÕ±ÑÌ°(€€€ô°€ÈÀÀ(()‘•˜Í•¹‘}‰¥ÉÑ¡‘…å}É•µ¥¹‘•ÉÌ¡½¹™¥œ¤è(€€€Ñ½­•¸€ô½¹™¥œ¹•Ğ ‰1%9}!991}MM}Q=-8ˆ¤½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}!991}MM}Q=-8ˆ°€ˆˆ¤(€€€¥˜¹½ĞÑ½­•¸è(€€€€€€€É•ÑÕÉ¸ì‰Í•¹Ğˆè€À°€‰Í­¥ÁÁ•ˆè€À°€‰•ÉÉ½Èˆè€‰1%9}!991}MM}Q=-8¥Ì¹½ĞÍ•Ğ‰ô°€ĞÀÀ((€€€‘…Ñ…}™¥±”€ô½¹™¥l‰Q}%1‰t(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€Í•¹‘•È€ô½¹™¥œ¹•Ğ ‰1%9}AUM!}M9Hˆ¤½È±¥¹•}ÁÕÍ¡}µ•ÍÍ…”(€€€¹½Ü€ôÕÉÉ•¹Ñ}…ÁÁ}Ñ¥µ”¡½¹™¥œ¤(€€€Ñ½‘…å}‘…Ñ”€ô¹½Ü¹‘…Ñ” ¤(€€€Ñ½‘…å}­•ä€ôÑ½‘…å}‘…Ñ”¹ÍÑÉ™Ñ¥µ” ˆ•d´•´´•ˆ¤(€€€Í•¹Ğ€ô€À(€€€Í­¥ÁÁ•€ô€À(€€€É•ÍÕ±ÑÌ€ômt((€€€‰±½­•€ô€À(€€€ÍåÍÑ•µ}•ÉÉ½È€ô…±Í”(€€€™½ÈÕÍ•È¥¸ÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ°íô¤¹Ù…±Õ•Ì ¤è(€€€€€€€±¥¹•}ÕÍ•É}¥€ôÕÍ•È¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤(€€€€€€€¥˜¹½Ğ±¥¹•}ÕÍ•É}¥è(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¥˜¹½ĞÁ±…¹}¡…Í}Íµ…ÉÑ}É•µ¥¹‘•ÉÌ¡ÕÍ•È°¹½Üõ¹½Ü¤è(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¥˜ÕÍ•È¹•Ğ ‰µ•µ‰•ÉÍ¡¥Á}Á…ÕÍ•ˆ¤½È¹½Ğµ•µ‰•ÉÍ¡¥Á}…•ÍÍ}…Ñ¥Ù”¡ÕÍ•È°¹½Ü¤è(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¥˜ÕÍ•È¹•Ğ ‰±¥¹•}ÁÕÍ¡}‰±½­•ˆ¤è(€€€€€€€€€€€‰±½­•€¬ô€Ä(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¹½Ñ•Ì€ôÕÍ•È¹•Ğ ‰…±•¹‘…É}¹½Ñ•Ìˆ¤½Èíô(€€€€€€€¥˜¹½Ğ¥Í¥¹ÍÑ…¹”¡¹½Ñ•Ì°‘¥Ğ¤è(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€Í•¹Ñ}­•åÌ€ôÍ•Ğ¡ÕÍ•È¹•Ğ ‰‰¥ÉÑ¡‘…å}É•µ¥¹‘•É}Í•¹Ñ}­•åÌˆ¤½Èmt¤(€€€€€€€™½È¹½Ñ•}‘…Ñ”°¹½Ñ”¥¸¹½Ñ•Ì¹¥Ñ•µÌ ¤è(€€€€€€€€€€€™½È‰¥ÉÑ¡‘…å}¥¹‘•à°‰¥ÉÑ¡‘…ä¥¸•¹Õµ•É…Ñ”¡…±•¹‘…É}¹½Ñ•}‰¥ÉÑ¡‘…åÌ¡¹½Ñ”¤¤è(€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€É•µ¥¹‘}‘…åÌ€ô¥¹Ğ¡‰¥ÉÑ¡‘…ä¹•Ğ ‰‰¥ÉÑ¡‘…å}É•µ¥¹‘}‘…åÌˆ¤½È€Ä¤(€€€€€€€€€€€€€€€•á•ÁĞ€¡QåÁ•ÉÉ½È°Y…±Õ•ÉÉ½È¤è(€€€€€€€€€€€€€€€€€€€É•µ¥¹‘}‘…åÌ€ô€Ä(€€€€€€€€€€€€€€€Ñ…É•Ñ}‘…Ñ”€ôÑ½‘…å}‘…Ñ”€¬Ñ¥µ•‘•±Ñ„¡‘…åÌõÉ•µ¥¹‘}‘…åÌ¤(€€€€€€€€€€€€€€€¥˜¹½Ğ‰¥ÉÑ¡‘…å}½ÕÉÍ}½¸¡‰¥ÉÑ¡‘…ä°Ñ…É•Ñ}‘…Ñ”¤è(€€€€€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€€€€€‰¥ÉÑ¡‘…å}ÍÕ™™¥à€ô˜ˆéí‰¥ÉÑ¡‘…å}¥¹‘•áôˆ¥˜‰¥ÉÑ¡‘…å}¥¹‘•à•±Í”€ˆˆ(€€€€€€€€€€€€€€€Í•¹Ñ}­•ä€ô€ (€€€€€€€€€€€€€€€€€€€˜‰íÑ½‘…å}­•åôéí¹½Ñ•}‘…Ñ•ôéíÉ•µ¥¹‘}‘…åÍõí‰¥ÉÑ¡‘…å}ÍÕ™™¥áôˆ(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€¥˜Í•¹Ñ}­•ä¥¸Í•¹Ñ}­•åÌè(€€€€€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€€€€€‘•±¥Ù•Éå}­•ä€ô˜‰‰¥ÉÑ¡‘…äéíÍ•¹Ñ}­•åôˆ(€€€€€€€€€€€€€€€¥˜¹½ĞÁÕÍ¡}…ÑÑ•µÁÑ}…±±½İ•¡ÕÍ•È°‘•±¥Ù•Éå}­•ä¤è(€€€€€€€€€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€€€€€İ¡¼€ô‰¥ÉÑ¡‘…ä¹•Ğ ‰‰¥ÉÑ¡‘…å}É•±…Ñ¥½¹Í¡¥Àˆ¤½È‰¥ÉÑ¡‘…ä¹•Ğ ‰‰¥ÉÑ¡‘…å}¹…µ”ˆ¤½È€‹–ºÛ’êèˆ(€€€€€€€€€€€€€€€İ¡•¹}Ñ•áĞ€ô€‹’î+–’¤ˆ¥˜É•µ¥¹‘}‘…åÌ€ôô€À•±Í”€ ‹šb;–’¤ˆ¥˜É•µ¥¹‘}‘…åÌ€ôô€Ä•±Í”˜‰íÉ•µ¥¹‘}‘…åÍôƒ–’§–ú0ˆ¤(€€€€€€€€€€€€€€€µ•ÍÍ…”€ô˜‰íİ¡•¹}Ñ•áÑ÷šb½íİ¡½÷Rš^—¾ò3¢¢c–ú_¢Ş’î[¢ª«¢ËRš^—–ş¯š¢’æ–>¿’î—¦‚š&/Šë¢ª7’î[’î+–’§–æÏ–º'ˆ(€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€É•ÍÕ±Ğ€ôÍ•¹‘•È¡Ñ½­•¸°±¥¹•}ÕÍ•É}¥°µ•ÍÍ…”¤(€€€€€€€€€€€€€€€€€€€}±•…É}ÁÕÍ¡}‘•±¥Ù•Éå}™…¥±ÕÉ”¡ÕÍ•È°‘•±¥Ù•Éå}­•ä¤(€€€€€€€€€€€€€€€€€€€Í•¹Ñ}­•åÌ¹…‘¡Í•¹Ñ}­•ä¤(€€€€€€€€€€€€€€€€€€€ÕÍ•Él‰‰¥ÉÑ¡‘…å}É•µ¥¹‘•É}Í•¹Ñ}­•åÌ‰t€ôÍ½ÉÑ•¡Í•¹Ñ}­•åÌ¥l´àÀét(€€€€€€€€€€€€€€€€€€€…ÁÁ•¹‘}¹½Ñ¥™¥…Ñ¥½¹}±½œ¡ÍÑ…Ñ”°€‰‰¥ÉÑ¡‘…äˆ°±¥¹•}ÕÍ•É}¥°€‰Í•¹Ğˆ°µ•ÍÍ…”°©Í½¸¹‘ÕµÁÌ¡É•ÍÕ±Ğ°•¹ÍÕÉ•}…Í¥¤õ…±Í”¤¤(€€€€€€€€€€€€€€€€€€€Í•¹Ğ€¬ô€Ä(€€€€€€€€€€€€€€€€€€€É•ÍÕ±ÑÌ¹…ÁÁ•¹¡ì‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°€‰‰¥ÉÑ¡‘…äˆèİ¡¼°€‰É•µ¥¹‘}‘…åÌˆèÉ•µ¥¹‘}‘…åÍô¤(€€€€€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€€€€€€€€€™…¥±ÕÉ”€ô}É•½É‘}Í¡•‘Õ±•‘}ÁÕÍ¡}™…¥±ÕÉ” (€€€€€€€€€€€€€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€€€€€€€€€€€€€ÕÍ•È°(€€€€€€€€€€€€€€€€€€€€€€€‘•±¥Ù•Éå}­•ä°(€€€€€€€€€€€€€€€€€€€€€€€€‰‰¥ÉÑ¡‘…äˆ°(€€€€€€€€€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€€€€€€€€€µ•ÍÍ…”°(€€€€€€€€€€€€€€€€€€€€€€€•áŒ°(€€€€€€€€€€€€€€€€€€€€€€€¹½Ü°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€¥˜™…¥±ÕÉ•l‰ÍÑ…ÑÕÌ‰t€ôô€‰‰±½­•ˆè(€€€€€€€€€€€€€€€€€€€€€€€‰±½­•€¬ô€Ä(€€€€€€€€€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€€€€€€€€€É•ÍÕ±ÑÌ¹…ÁÁ•¹¡ì‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°€‰‰¥ÉÑ¡‘…äˆèİ¡¼°€‰•ÉÉ½ÈˆèÍÑÈ¡•áŒ¥ô¤(€€€€€€€€€€€€€€€€€€€¥˜™…¥±ÕÉ•l‰­¥¹‰t€ôô€‰ÍåÍÑ•´ˆè(€€€€€€€€€€€€€€€€€€€€€€€ÍåÍÑ•µ}•ÉÉ½È€ôQÉÕ”(€€€€€€€€€€€€€€€€€€€€€€€‰É•…¬(€€€€€€€€€€€¥˜ÍåÍÑ•µ}•ÉÉ½Èè(€€€€€€€€€€€€€€€‰É•…¬(€€€€€€€¥˜ÍåÍÑ•µ}•ÉÉ½Èè(€€€€€€€€€€€‰É•…¬((€€€Í…Ù•}ÍÑ…Ñ”¡‘…Ñ…}™¥±”°ÍÑ…Ñ”¤(€€€É•ÑÕÉ¸ì(€€€€€€€€‰Í•¹ĞˆèÍ•¹Ğ°(€€€€€€€€‰Í­¥ÁÁ•ˆèÍ­¥ÁÁ•°(€€€€€€€€‰‰±½­•ˆè‰±½­•°(€€€€€€€€‰É•ÍÕ±ÑÌˆèÉ•ÍÕ±ÑÌ°(€€€€€€€€‰ÍåÍÑ•µ}•ÉÉ½ÈˆèÍåÍÑ•µ}•ÉÉ½È°(€€€ô°€ÈÀÀ(((Œ€ôôô€Üääƒšfë¢÷š>C¦K¾ò#RšÒïš>C¦K¾òk–>«¢ÖÀ1%9ƒ¢¢+¾ò3¦‚C¢¢·’â7¦Ë–º#¢¶ßú“¾ò$ôôô)M5IQ}I5%9I}Q=I%L€ôì(€€€€‰‰¥ÉÑ¡‘…äˆèì‰•µ½©¤ˆè€‹Â~:ˆ°€‰±…‰•°ˆè€‹Rš^”‰ô°(€€€€‰İ•‘‘¥¹œˆèì‰•µ½©¤ˆè€‹Â~J4ˆ°€‰±…‰•°ˆè€‹ÖC–¦kÒ–ş×š^”‰ô°(€€€€‰‘…Ñ¥¹œˆèì‰•µ½©¤ˆè€‹Â~JTˆ°€‰±…‰•°ˆè€‹’ê“–úÒ–ş×š^”‰ô°(€€€€‰¡¥±‘}‰¥ÉÑ¡‘…äˆèì‰•µ½©¤ˆè€‹Â~FØˆ°€‰±…‰•°ˆè€‹–Â?–¶§Rš^”‰ô°(€€€€‰•±‘•É}‰¥ÉÑ¡‘…äˆèì‰•µ½©¤ˆè€‹Â~FĞˆ°€‰±…‰•°ˆè€‹¦Vß¢ò§Rš^”‰ô°(€€€€‰É…‘Õ…Ñ¥½¸ˆèì‰•µ½©¤ˆè€‹Â~:Lˆ°€‰±…‰•°ˆè€‹V‹š–´‰ô°(€€€€‰µ½Ù¥¹œˆèì‰•µ½©¤ˆè€‹Â~>€ˆ°€‰±…‰•°ˆè€‹šB³–ºØ‰ô°(€€€€‰ÍÁ•¥…°ˆèì‰•µ½©¤ˆè€‹Â~:$ˆ°€‰±…‰•°ˆè€‹&çšº+Ò–ş×š^”‰ô°(€€€€‰¡•­ÕÀˆèì‰•µ½©¤ˆè€‹Â~J(ˆ°€‰±…‰•°ˆè€‹–n{¢¢è‰ô°(€€€€‰µ•‘¥¥¹”ˆèì‰•µ½©¤ˆè€‹Â~J(ˆ°€‰±…‰•°ˆè€‹–B¢^”‰ô°(€€€€‰Í¡•‘Õ±”ˆèì‰•µ½©¤ˆè€‹Â~Nˆ°€‰±…‰•°ˆè€‹¢†3¢,‰ô°(€€€€‰É••Ñ¥¹œˆèì‰•µ½©¤ˆè€‹Šv“¾â<ˆ°€‰±…‰•°ˆè€‹–V?–d‰ô°(€€€€‰ÕÍÑ½´ˆèì‰•µ½©¤ˆè€‹Â~^O¾â<ˆ°€‰±…‰•°ˆè€‹¢«¢¢‰ô°)ô(()‘•˜Á±…¹}¡…Í}Íµ…ÉÑ}É•µ¥¹‘•ÉÌ¡ÁÉ½™¥±”°¹½Üõ9½¹”¤è(€€€Á±…¸€ôÍÑÈ ¡ÁÉ½™¥±”½Èíô¤¹•Ğ ‰Á±…¸ˆ¤½È€‰ÑÉ¥…°ˆ¤(€€€É•ÑÕÉ¸Á±…¸¥¸ì‰Á…¥‘|Üääˆ°€‰Á…¥‘|Üäå}å•…È‰ô…¹Á…¥‘}µ•µ‰•ÉÍ¡¥Á}¥Í}…Ñ¥Ù” (€€€€€€€ÁÉ½™¥±”½Èíô°¹½Üõ¹½Ü(€€€€¤(()‘•˜¹½Éµ…±¥é•}Íµ…ÉÑ}É•µ¥¹‘•È¡É…Ü°¥¹‘•àôÀ¤è(€€€É…Ü€ôÉ…Ü¥˜¥Í¥¹ÍÑ…¹”¡É…Ü°‘¥Ğ¤•±Í”íô(€€€…Ñ•½Éä€ôÍÑÈ¡É…Ü¹•Ğ ‰…Ñ•½Éäˆ¤½È€‰ÕÍÑ½´ˆ¤¹ÍÑÉ¥À ¤¹±½İ•È ¤(€€€¥˜…Ñ•½Éä¹½Ğ¥¸M5IQ}I5%9I}Q=I%Lè(€€€€€€€…Ñ•½Éä€ô€‰ÕÍÑ½´ˆ(€€€µ•Ñ„€ôM5IQ}I5%9I}Q=I%Mm…Ñ•½Éåt(€€€•µ½©¤€ôÍÑÈ¡É…Ü¹•Ğ ‰•µ½©¤ˆ¤½Èµ•Ñ…l‰•µ½©¤‰t¤¹ÍÑÉ¥À ¤½Èµ•Ñ…l‰•µ½©¤‰t(€€€ÑÉäè(€€€€€€€µ½¹Ñ €ô¥¹Ğ¡É…Ü¹•Ğ ‰µ½¹Ñ ˆ¤½È€À¤(€€€€€€€‘…ä€ô¥¹Ğ¡É…Ü¹•Ğ ‰‘…äˆ¤½È€À¤(€€€•á•ÁĞ€¡QåÁ•ÉÉ½È°Y…±Õ•ÉÉ½È¤è(€€€€€€€µ½¹Ñ °‘…ä€ô€À°€À(€€€å•…É}É…Ü€ôÉ…Ü¹•Ğ ‰å•…Èˆ¤(€€€ÑÉäè(€€€€€€€å•…È€ô¥¹Ğ¡å•…É}É…Ü¤¥˜å•…É}É…Ü¹½Ğ¥¸€¡9½¹”°€ˆˆ°€À°€ˆÀˆ¤•±Í”9½¹”(€€€•á•ÁĞ€¡QåÁ•ÉÉ½È°Y…±Õ•ÉÉ½È¤è(€€€€€€€å•…È€ô9½¹”(€€€€Œ‘…Ñ•}¥Í¿¾ò!eeedµ54µ¾ò'–«–#šZóš.¦Z/j–æÓšr#š^”(€€€‘…Ñ•}¥Í¼€ôÍÑÈ¡É…Ü¹•Ğ ‰‘…Ñ”ˆ¤½ÈÉ…Ü¹•Ğ ‰‘…Ñ•}¥Í¼ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€¥˜‘…Ñ•}¥Í¼…¹É”¹µ…Ñ ¡È‰yq‘ìÑôµq‘ìÉôµq‘ìÉôˆ°‘…Ñ•}¥Í¼¤è(€€€€€€€ÑÉäè(€€€€€€€€€€€ä°´°€ô‘…Ñ•}¥Í¼¹ÍÁ±¥Ğ ˆ´ˆ¤(€€€€€€€€€€€å•…È€ô¥¹Ğ¡ä¤(€€€€€€€€€€€µ½¹Ñ €ô¥¹Ğ¡´¤(€€€€€€€€€€€‘…ä€ô¥¹Ğ¡¤(€€€€€€€•á•ÁĞ€¡QåÁ•ÉÉ½È°Y…±Õ•ÉÉ½È¤è(€€€€€€€€€€€Á…ÍÌ(€€€¥˜‰½½°¡É…Ü¹•Ğ ‰å•…É±äˆ°…±Í”¤¤½È‰½½°¡É…Ü¹•Ğ ‰É•Á•…Ñ}å•…É±äˆ°…±Í”¤¤è(€€€€€€€å•…È€ô9½¹”(€€€É•µ¥¹‘}Ñ¥µ”€ôÍÑÈ¡É…Ü¹•Ğ ‰É•µ¥¹‘}Ñ¥µ”ˆ¤½ÈÉ…Ü¹•Ğ ‰Ñ¥µ”ˆ¤½È€ˆÀäèÀÀˆ¤¹ÍÑÉ¥À ¤(€€€¥˜¹½ĞI5%9I}Q%5}AQQI8¹µ…Ñ ¡É•µ¥¹‘}Ñ¥µ”¤è(€€€€€€€É•µ¥¹‘}Ñ¥µ”€ô€ˆÀäèÀÀˆ(€€€ÕÍÑ½µ}Ñ¥Ñ±”€ôÍÑÈ¡É…Ü¹•Ğ ‰ÕÍÑ½µ}Ñ¥Ñ±”ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¥lèàÁt(€€€…Ñ•½Éå}±…‰•°€ôµ•Ñ…l‰±…‰•°‰t(€€€¥˜…Ñ•½Éä€ôô€‰ÕÍÑ½´ˆ…¹ÕÍÑ½µ}Ñ¥Ñ±”è(€€€€€€€…Ñ•½Éå}±…‰•°€ôÕÍÑ½µ}Ñ¥Ñ±”(€€€É¥€ôÍÑÈ¡É…Ü¹•Ğ ‰¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤½È˜‰ÍÉ}íÍ•É•ÑÌ¹Ñ½­•¹}¡•à Ø¥ôˆ(€€€¹½Ñ¥™å}ÁÉ¥Ù…Ñ”€ôQÉÕ”€€ŒÁÉ½‘ÕĞèƒšfë¢÷š>C¦K–>«¢ÖÃ¢¢((€€€¹½Ñ¥™å}É½ÕÀ€ô…±Í”(€€€‘•±¥Ù•Éå}Ñ…É•Ğ€ôÍÑÈ¡É…Ü¹•Ğ ‰‘•±¥Ù•Éå}Ñ…É•Ğˆ¤½È€‰ÁÉ¥Ù…Ñ”ˆ¤¹ÍÑÉ¥À ¤(€€€¥˜¹½Ğ€¡‘•±¥Ù•Éå}Ñ…É•Ğ€ôô€‰ÁÉ¥Ù…Ñ”ˆ½È‘•±¥Ù•Éå}Ñ…É•Ğ¹ÍÑ…ÉÑÍİ¥Ñ  ‰Õ…É‘¥…¸èˆ¤¤è(€€€€€€€‘•±¥Ù•Éå}Ñ…É•Ğ€ôÍÑÈ¡É…Ü¹•Ğ ‰‘•±¥Ù•Éå}Ñ…É•Ğˆ¤½È€‰ÁÉ¥Ù…Ñ”ˆ¤¹ÍÑÉ¥À ¤(€€€É•ÑÕÉ¸ì(€€€€€€€€‰¥ˆèÉ¥°(€€€€€€€€‰Ñ…É•Ñ}¹…µ”ˆèÍÑÈ¡É…Ü¹•Ğ ‰Ñ…É•Ñ}¹…µ”ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤½È˜‹–Â7¢Æ…í¥¹‘•à€¬€Åôˆ°(€€€€€€€€‰…Ñ•½Éäˆè…Ñ•½Éä°(€€€€€€€€‰…Ñ•½Éå}±…‰•°ˆè…Ñ•½Éå}±…‰•°°(€€€€€€€€‰ÕÍÑ½µ}Ñ¥Ñ±”ˆèÕÍÑ½µ}Ñ¥Ñ±”°(€€€€€€€€‰•µ½©¤ˆè•µ½©¤°(€€€€€€€€‰µ½¹Ñ ˆèµ½¹Ñ ¥˜€Ä€ğôµ½¹Ñ €ğô€ÄÈ•±Í”€Ä°(€€€€€€€€‰‘…äˆè‘…ä¥˜€Ä€ğô‘…ä€ğô€ÌÄ•±Í”€Ä°(€€€€€€€€‰å•…Èˆèå•…È°(€€€€€€€€‰É•µ¥¹‘}Ñ¥µ”ˆèÉ•µ¥¹‘}Ñ¥µ”°(€€€€€€€€‰¹½Ñ”ˆèÍÑÈ¡É…Ü¹•Ğ ‰¹½Ñ”ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¥lèÈÀÁt°(€€€€€€€€‰¹½Ñ¥™å}ÁÉ¥Ù…Ñ”ˆè¹½Ñ¥™å}ÁÉ¥Ù…Ñ”°(€€€€€€€€‰¹½Ñ¥™å}É½ÕÀˆè¹½Ñ¥™å}É½ÕÀ°(€€€€€€€€‰‘•±¥Ù•Éå}Ñ…É•Ğˆè‘•±¥Ù•Éå}Ñ…É•Ğ°(€€€€€€€€‰•Ù•}É•µ¥¹ˆè‰½½°¡É…Ü¹•Ğ ‰•Ù•}É•µ¥¹ˆ°QÉÕ”¤¤°(€€€€€€€€‰•¹…‰±•ˆè‰½½°¡É…Ü¹•Ğ ‰•¹…‰±•ˆ°QÉÕ”¤¤°(€€€€€€€€‰É•…Ñ•‘}…ĞˆèÍÑÈ¡É…Ü¹•Ğ ‰É•…Ñ•‘}…Ğˆ¤½È‘…Ñ•Ñ¥µ”¹¹½Ü ¤¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤¤°(€€€€€€€€‰ÕÁ‘…Ñ•‘}…ĞˆèÍÑÈ¡É…Ü¹•Ğ ‰ÕÁ‘…Ñ•‘}…Ğˆ¤½È€ˆˆ¤°(€€€ô(()‘•˜±¥ÍÑ}Íµ…ÉÑ}É•µ¥¹‘•ÉÌ¡ÁÉ½™¥±”¤è(€€€É½İÌ€ôÁÉ½™¥±”¹•Ğ ‰Íµ…ÉÑ}É•µ¥¹‘•ÉÌˆ¤¥˜¥Í¥¹ÍÑ…¹”¡ÁÉ½™¥±”¹•Ğ ‰Íµ…ÉÑ}É•µ¥¹‘•ÉÌˆ¤°±¥ÍĞ¤•±Í”mt(€€€É•ÑÕÉ¸m¹½Éµ…±¥é•}Íµ…ÉÑ}É•µ¥¹‘•È¡É½Ü°¤¤™½È¤°É½Ü¥¸•¹Õµ•É…Ñ”¡É½İÌ¥t(()‘•˜Íµ…ÉÑ}É•µ¥¹‘•É}½ÕÉÍ}½¸¡É•µ¥¹‘•È°Ñ…É•Ñ}‘…Ñ”¤è(€€€ÑÉäè(€€€€€€€µ½¹Ñ €ô¥¹Ğ¡É•µ¥¹‘•È¹•Ğ ‰µ½¹Ñ ˆ¤½È€À¤(€€€€€€€‘…ä€ô¥¹Ğ¡É•µ¥¹‘•È¹•Ğ ‰‘…äˆ¤½È€À¤(€€€•á•ÁĞ€¡QåÁ•ÉÉ½È°Y…±Õ•ÉÉ½È¤è(€€€€€€€É•ÑÕÉ¸…±Í”(€€€¥˜¹½Ğ€ Ä€ğôµ½¹Ñ €ğô€ÄÈ…¹€Ä€ğô‘…ä€ğô€ÌÄ¤è(€€€€€€€É•ÑÕÉ¸…±Í”(€€€å•…È€ôÉ•µ¥¹‘•È¹•Ğ ‰å•…Èˆ¤(€€€¥˜å•…Èè(€€€€€€€ÑÉäè(€€€€€€€€€€€É•ÑÕÉ¸Ñ…É•Ñ}‘…Ñ”¹å•…È€ôô¥¹Ğ¡å•…È¤…¹Ñ…É•Ñ}‘…Ñ”¹µ½¹Ñ €ôôµ½¹Ñ …¹Ñ…É•Ñ}‘…Ñ”¹‘…ä€ôô‘…ä(€€€€€€€•á•ÁĞ€¡QåÁ•ÉÉ½È°Y…±Õ•ÉÉ½È¤è(€€€€€€€€€€€É•ÑÕÉ¸…±Í”(€€€€Œå•…É±äÉ•ÕÉÉ•¹”ìÍ­¥À¥¹Ù…±¥‘…Ñ•Ì±¥­”€È¼ÌÀ(€€€ÑÉäè(€€€€€€€‘…Ñ•Ñ¥µ”¡Ñ…É•Ñ}‘…Ñ”¹å•…È°µ½¹Ñ °‘…ä¤(€€€•á•ÁĞY…±Õ•ÉÉ½Èè(€€€€€€€É•ÑÕÉ¸…±Í”(€€€É•ÑÕÉ¸Ñ…É•Ñ}‘…Ñ”¹µ½¹Ñ €ôôµ½¹Ñ …¹Ñ…É•Ñ}‘…Ñ”¹‘…ä€ôô‘…ä(()‘•˜Íµ…ÉÑ}É•µ¥¹‘•É}…¹¹•‘}İ¥Í ¡É•µ¥¹‘•È¤è(€€€¹…µ”€ôÉ•µ¥¹‘•È¹•Ğ ‰Ñ…É•Ñ}¹…µ”ˆ¤½È€‹–Â7šZäˆ(€€€…Ğ€ôÉ•µ¥¹‘•È¹•Ğ ‰…Ñ•½Éäˆ¤½È€‰ÕÍÑ½´ˆ(€€€±…‰•°€ôÉ•µ¥¹‘•È¹•Ğ ‰…Ñ•½Éå}±…‰•°ˆ¤½ÈM5IQ}I5%9I}Q=I%L¹•Ğ¡…Ğ°íô¤¹•Ğ ‰±…‰•°ˆ°€‹š^—–¶@ˆ¤(€€€Ñ•µÁ±…Ñ•Ì€ôì(€€€€€€€€‰‰¥ÉÑ¡‘…äˆè˜‹Â~:í¹…µ•÷¾ò3Rš^—–ş¯š¢¾ò¦†c’öƒ’î+–’§¢Š¯šê¯š~S–2–r7¾ò3–æÏ–º'–—–êßš¾?’â–’¤ƒŠv“¾â<ˆ°(€€€€€€€€‰İ•‘‘¥¹œˆè˜‹Â~J4ƒ¢š«šojí¹…µ•÷¾ò3ÖC–¦kÒ–ş×š^—–ş¯š¢¾òš¢²w’â¢Ş¿’â+j¦f«’òÓ¢"–2–ºäƒŠv“¾â<ˆ°(€€€€€€€€‰‘…Ñ¥¹œˆè˜‹Â~JTí¹…µ•÷¾ò3’ê“–úÒ–ş×š^—–ş¯š¢¾ò¢²w¢²w’öƒ¢ºO–æÏ–‡š^—–¶C¢º+–ú_&ç–"—ˆ°(€€€€€€€€‰¡¥±‘}‰¥ÉÑ¡‘…äˆè˜‹Â~FØƒ¢š«šoj–Â?–¶§Rš^—–ş¯š¢¾ò¦Vß–’Ÿjš¾?’âš¶—¾ò3š"G–G¦÷
ë’öƒ¦Z/–şˆ°(€€€€€€€€‰•±‘•É}‰¥ÉÑ¡‘…äˆè˜‹Â~FĞí¹…µ•÷Rš^—–ş¯š¢¾ò¦†cš
£¢ê¯¦®S†³šr_š¾?–’§²G–>–âã¦Z/ˆ°(€€€€€€€€‰É…‘Õ…Ñ¥½¸ˆè˜‹Â~:Lƒš·–Zqí¹…µ•÷V‹š–·¾òšZÃjš^¢/¦Z/–/’ê¾ò3š"G–G
ë’öƒ¦¦W–
Ëˆ°(€€€€€€€€‰µ½Ù¥¹œˆè˜‹Â~>€ƒšZÃ–ºÛ¢B÷š"C¾ò?–Z³¦ßš'–ş¯¾ò¦†aí¹…µ•÷–r£šZÃJÃ–Š’â–"¦‚–"§ˆ°(€€€€€€€€‰ÍÁ•¥…°ˆè˜‹Â~:$ƒ’î+–’§šb¿&ç–"—jš^—–¶C¾ò3–uí¹…µ•÷¦Z/–ş–æÏ–º'ˆ°(€€€€€€€€‰¡•­ÕÀˆè˜‹Â~J(ƒš>C¦K¾òk¢¢c–ú_¦f«¾ò?¦^s–şí¹…µ•÷–n{¢¢ë¾ò3–âÛ–—’şw–6‡¢"–ÂÇ¦¯¢ÎšZgˆ°(€€€€€€€€‰µ•‘¥¥¹”ˆè˜‹Â~J(ƒš>C¦K¾òk¢¦Ë–B¢^—¾ò?š.ÿ¢^—’ê¾ò3–æ­í¹…µ•÷Šë¢ª7’âš²‡ˆ°(€€€€€€€€‰Í¡•‘Õ±”ˆè˜‹Â~Nƒ¢†3¢/š>C¦K¾òk’î+–’§¢"í¹…µ•÷šr'¦^sj–º'š:K¾ò3–"—–şc’ê¦‚CVgšf¦ZOˆ°(€€€€€€€€‰É••Ñ¥¹œˆè˜‹Šv“¾â<ƒ–
Ï’â–>—–V?–gÖ™í¹…µ•÷¾òk3’î+–’§¦
––÷–^;¾òš"GšÏ’öƒ’ê4ˆ°(€€€€€€€€‰ÕÍÑ½´ˆè˜‹Â~^O¾â<ƒš>C¦K¾òk’î+–’§šb¿’öƒ
éí¹…µ•÷¢¢·–ºkj1í±…‰•±÷7¾ò3¢¢c–ú_¢fWB’â’â/ˆ°(€€€ô(€€€É•ÑÕÉ¸Ñ•µÁ±…Ñ•Ì¹•Ğ¡…Ğ°Ñ•µÁ±…Ñ•Íl‰ÕÍÑ½´‰t¤(()‘•˜Íµ…ÉÑ}É•µ¥¹‘•É}…¹¹•‘}¥™Ğ¡É•µ¥¹‘•È¤è(€€€¹…µ”€ôÉ•µ¥¹‘•È¹•Ğ ‰Ñ…É•Ñ}¹…µ”ˆ¤½È€‹–Â7šZäˆ(€€€…Ğ€ôÉ•µ¥¹‘•È¹•Ğ ‰…Ñ•½Éäˆ¤½È€‰ÕÍÑ½´ˆ(€€€¥˜…Ğ¥¸ì‰‰¥ÉÑ¡‘…äˆ°€‰¡¥±‘}‰¥ÉÑ¡‘…äˆ°€‰•±‘•É}‰¥ÉÑ¡‘…ä‰ôè(€€€€€€€É•ÑÕÉ¸˜‹Â~:ƒš»&§–îë¢¶Ã¾òhÄ¤ƒš&/–¾¯–Â?–6‡¾ò/–Zsš¶‡jRs¦îx€È¤ƒ–¾›R£š^—–âã––÷&¤€Ì¤ƒ’â¢Öß–B¦‚O¦¿–Â7¢Æ‡¾òií¹…µ•ôˆ(€€€¥˜…Ğ¥¸ì‰İ•‘‘¥¹œˆ°€‰‘…Ñ¥¹œ‰ôè(€€€€€€€É•ÑÕÉ¸˜‹Â~:ƒš»&§–îë¢¶Ã¾òk’â¢Öß–n{šÛŸ&šnã–Ç–B3–Zsš¶‡j–Â?š^¢†3¾ò3š"[’â¦‚O–º'¦vsšfk¦’C–Â7¢Æ‡¾òií¹…µ•ôˆ(€€€¥˜…Ğ¥¸ì‰¡•­ÕÀˆ°€‰µ•‘¥¥¹”‰ôè(€€€€€€€É•ÑÕÉ¸˜‹Â~:ƒ–¾›R£–6S–*§¾òk¦f«¢¢ëšVÓB¢^—–Z»šê[–
gšÂÓšv¿¢"’ê“¦k–º'š:K–Â7¢Æ‡¾òií¹…µ•ôˆ(€€€É•ÑÕÉ¸˜‹Â~:ƒ–îë¢¶Ã¾òk’â–>—r–ş¢¦Ç¾ò/–Â?¦¦k–Zs¾ò#¢*Ç¾ò?Rs¦î{¾ò?¦f«’òÓšf¦ZO¾ò'–Â7¢Æ‡¾òií¹…µ•ôˆ(()‘•˜‰Õ¥±‘}Íµ…ÉÑ}É•µ¥¹‘•É}™±•à¡É•µ¥¹‘•È°€¨°µ½‘”ô‰‘…äˆ¤è(€€€€ˆˆ‰µ½‘”õ‘…åñ•Ù”±•à™½ÈÁÉ¥Ù…Ñ”1%9ÁÕÍ ¸ˆˆˆ(€€€¹…µ”€ôÉ•µ¥¹‘•È¹•Ğ ‰Ñ…É•Ñ}¹…µ”ˆ¤½È€‹–Â7šZäˆ(€€€•µ½©¤€ôÉ•µ¥¹‘•È¹•Ğ ‰•µ½©¤ˆ¤½È€‹Â~^O¾â<ˆ(€€€±…‰•°€ôÉ•µ¥¹‘•È¹•Ğ ‰…Ñ•½Éå}±…‰•°ˆ¤½È€‹š>C¦Hˆ(€€€µ½¹Ñ €ô¥¹Ğ¡É•µ¥¹‘•È¹•Ğ ‰µ½¹Ñ ˆ¤½È€Ä¤(€€€‘…ä€ô¥¹Ğ¡É•µ¥¹‘•È¹•Ğ ‰‘…äˆ¤½È€Ä¤(€€€‘…Ñ•}Ñ•áĞ€ô˜‰íµ½¹Ñ¡ô½í‘…åôˆ(€€€É¥€ôÉ•µ¥¹‘•È¹•Ğ ‰¥ˆ¤½È€ˆˆ(€€€¥˜µ½‘”€ôô€‰•Ù”ˆè(€€€€€€€Ñ¥Ñ±”€ô˜‹Šv“¾â<ƒšb;–’§šb½í¹…µ•õí±…‰•±ôˆ(€€€€€€€‰½‘ä€ô€‹¦r¢š–æ¯’öƒšê[–
g’â–>—–wš?–^;¾ò|ˆ(€€€€€€€‰ÕÑÑ½¹Ì€ôl(€€€€€€€€€€€ì‰ÑåÁ”ˆè€‰‰ÕÑÑ½¸ˆ°€‰…Ñ¥½¸ˆèì‰ÑåÁ”ˆè€‰Á½ÍÑ‰…¬ˆ°€‰±…‰•°ˆè€‹Šr£š¾?š^—R‹R–wš<ˆ°€‰‘…Ñ„ˆè˜‰Íµ…ÉĞéİ¥Í éíÉ¥‘ôˆ°€‰‘¥ÍÁ±…åQ•áĞˆè€‹–æ¯š"GR‹R–wš<‰ô°€‰ÍÑå±”ˆè€‰ÁÉ¥µ…Éäˆ°€‰½±½Èˆè€ˆŒİÍˆ°€‰¡•¥¡Ğˆè€‰Í´‰ô°(€€€€€€€€€€€ì‰ÑåÁ”ˆè€‰‰ÕÑÑ½¸ˆ°€‰…Ñ¥½¸ˆèì‰ÑåÁ”ˆè€‰Á½ÍÑ‰…¬ˆ°€‰±…‰•°ˆè€‹Â~:š»&§–îë¢¶Àˆ°€‰‘…Ñ„ˆè˜‰Íµ…ÉĞé¥™ĞéíÉ¥‘ôˆ°€‰‘¥ÍÁ±…åQ•áĞˆè€‹š»&§–îë¢¶À‰ô°€‰ÍÑå±”ˆè€‰Í•½¹‘…Éäˆ°€‰¡•¥¡Ğˆè€‰Í´‰ô°(€€€€€€€€€€€ì‰ÑåÁ”ˆè€‰‰ÕÑÑ½¸ˆ°€‰…Ñ¥½¸ˆèì‰ÑåÁ”ˆè€‰Á½ÍÑ‰…¬ˆ°€‰±…‰•°ˆè€‹Â~N{šb;–’§š>C¦Hˆ°€‰‘…Ñ„ˆè˜‰Íµ…ÉĞéÍ¹½½é”éíÉ¥‘ôˆ°€‰‘¥ÍÁ±…åQ•áĞˆè€‹šb;–’§–7š>C¦Kš"D‰ô°€‰ÍÑå±”ˆè€‰Í•½¹‘…Éäˆ°€‰¡•¥¡Ğˆè€‰Í´‰ô°(€€€€€€€t(€€€€€€€…±Ğ€ô˜‹šb;–’§šb½í¹…µ•÷jí±…‰•±ôˆ(€€€•±Í”è(€€€€€€€¥˜€¡É•µ¥¹‘•È¹•Ğ ‰…Ñ•½Éäˆ¤½È€ˆˆ¤€ôô€‰‰¥ÉÑ¡‘…äˆè(€€€€€€€€€€€Ñ¥Ñ±”€ô˜‹Â~:ƒ’î+–’§šb½í¹…µ•÷jRš^”ˆ(€€€€€€€€€€€‰½‘ä€ô˜‹–"—–şc’ê¦’â+’â–>—–wš<ƒŠv“¾â=q»–O–B7¾òií¹…µ•õq»’î+–’§¾òií‘…Ñ•}Ñ•áÑôˆ(€€€€€€€€€€€‰ÕÑÑ½¹Ì€ôl(€€€€€€€€€€€€€€€ì‰ÑåÁ”ˆè€‰‰ÕÑÑ½¸ˆ°€‰…Ñ¥½¸ˆèì‰ÑåÁ”ˆè€‰Á½ÍÑ‰…¬ˆ°€‰±…‰•°ˆè€‹Â~:–
Ï¦–wš<ˆ°€‰‘…Ñ„ˆè˜‰Íµ…ÉĞéİ¥Í éíÉ¥‘ôˆ°€‰‘¥ÍÁ±…åQ•áĞˆè€‹–
Ï¦–wš<‰ô°€‰ÍÑå±”ˆè€‰ÁÉ¥µ…Éäˆ°€‰½±½Èˆè€ˆÄÅĞàˆ°€‰¡•¥¡Ğˆè€‰Í´‰ô°(€€€€€€€€€€€€€€€ì‰ÑåÁ”ˆè€‰‰ÕÑÑ½¸ˆ°€‰…Ñ¥½¸ˆèì‰ÑåÁ”ˆè€‰Á½ÍÑ‰…¬ˆ°€‰±…‰•°ˆè€‹Â~:–ŞË–wš<ˆ°€‰‘…Ñ„ˆè˜‰Íµ…ÉĞé‰±•ÍÍ•éíÉ¥‘ôˆ°€‰‘¥ÍÁ±…åQ•áĞˆè€‹–ŞË–wš<‰ô°€‰ÍÑå±”ˆè€‰Í•½¹‘…Éäˆ°€‰¡•¥¡Ğˆè€‰Í´‰ô°(€€€€€€€€€€€€€€€ì‰ÑåÁ”ˆè€‰‰ÕÑÑ½¸ˆ°€‰…Ñ¥½¸ˆèì‰ÑåÁ”ˆè€‰Á½ÍÑ‰…¬ˆ°€‰±…‰•°ˆè€‹Š>Ãšfk¦î{š>C¦Kš"Dˆ°€‰‘…Ñ„ˆè˜‰Íµ…ÉĞéÍ¹½½é”éíÉ¥‘ôˆ°€‰‘¥ÍÁ±…åQ•áĞˆè€‹šfk¦î{š>C¦Kš"D‰ô°€‰ÍÑå±”ˆè€‰Í•½¹‘…Éäˆ°€‰¡•¥¡Ğˆè€‰Í´‰ô°(€€€€€€€€€€€t(€€€€€€€•±¥˜€‹"Øˆ¥¸¹…µ”½È±…‰•°¥¸ì‹&çšº+Ò–ş×š^”‰ô…¹€‹"Øˆ¥¸€¡É•µ¥¹‘•È¹•Ğ ‰¹½Ñ”ˆ¤½È€ˆˆ¤è(€€€€€€€€€€€Ñ¥Ñ±”€ô˜‹Â~:$ƒ’î+–’§šb¿"Û¢š«¾ ˆ(€€€€€€€€€€€‰½‘ä€ô˜‹’öƒ¢¢·–ºkjš>C¦K–Â7¢Æ‡¾òkÂ~F¡í¹…µ•õq»¢¢c–ú_–BG’î[¢ª«¢Ë¾òk"Û¢š«¾–ş¯š¢ƒŠv“¾â<ˆ(€€€€€€€€€€€‰ÕÑÑ½¹Ì€ôl(€€€€€€€€€€€€€€€ì‰ÑåÁ”ˆè€‰‰ÕÑÑ½¸ˆ°€‰…Ñ¥½¸ˆèì‰ÑåÁ”ˆè€‰Á½ÍÑ‰…¬ˆ°€‰±…‰•°ˆè€‹Â~J11%9–wš<ˆ°€‰‘…Ñ„ˆè˜‰Íµ…ÉĞéİ¥Í éíÉ¥‘ôˆ°€‰‘¥ÍÁ±…åQ•áĞˆè€‰1%9–wš<‰ô°€‰ÍÑå±”ˆè€‰ÁÉ¥µ…Éäˆ°€‰½±½Èˆè€ˆŒÈÔØÍˆ°€‰¡•¥¡Ğˆè€‰Í´‰ô°(€€€€€€€€€€€€€€€ì‰ÑåÁ”ˆè€‰‰ÕÑÑ½¸ˆ°€‰…Ñ¥½¸ˆèì‰ÑåÁ”ˆè€‰Á½ÍÑ‰…¬ˆ°€‰±…‰•°ˆè€‹Â~N{š&O¦nï¢¦Äˆ°€‰‘…Ñ„ˆè˜‰Íµ…ÉĞé…±°éíÉ¥‘ôˆ°€‰‘¥ÍÁ±…åQ•áĞˆè€‹š>C¦Kš"Gš&O¦nï¢¦Ä‰ô°€‰ÍÑå±”ˆè€‰Í•½¹‘…Éäˆ°€‰¡•¥¡Ğˆè€‰Í´‰ô°(€€€€€€€€€€€€€€€ì‰ÑåÁ”ˆè€‰‰ÕÑÑ½¸ˆ°€‰…Ñ¥½¸ˆèì‰ÑåÁ”ˆè€‰Á½ÍÑ‰…¬ˆ°€‰±…‰•°ˆè€‹Š>Ãšfk¦î{š>C¦Hˆ°€‰‘…Ñ„ˆè˜‰Íµ…ÉĞéÍ¹½½é”éíÉ¥‘ôˆ°€‰‘¥ÍÁ±…åQ•áĞˆè€‹šfk¦î{š>C¦H‰ô°€‰ÍÑå±”ˆè€‰Í•½¹‘…Éäˆ°€‰¡•¥¡Ğˆè€‰Í´‰ô°(€€€€€€€€€€€t(€€€€€€€•±Í”è(€€€€€€€€€€€Ñ¥Ñ±”€ô˜‰í•µ½©¥ôƒ’î+–’§šb½í¹…µ•÷jí±…‰•±ôˆ(€€€€€€€€€€€‰½‘ä€ô˜‹–"—–şc’ê¦^s–ş’â’â,ƒŠv“¾â=q»–Â7¢Æ‡¾òií¹…µ•õq»’î+–’§¾òií‘…Ñ•}Ñ•áÑôˆ(€€€€€€€€€€€¥˜É•µ¥¹‘•È¹•Ğ ‰¹½Ñ”ˆ¤è(€€€€€€€€€€€€€€€‰½‘ä€¬ô˜‰q»–
g¢¢ï¾òiíÉ•µ¥¹‘•È¹•Ğ ¹½Ñ”œ¥ôˆ(€€€€€€€€€€€‰ÕÑÑ½¹Ì€ôl(€€€€€€€€€€€€€€€ì‰ÑåÁ”ˆè€‰‰ÕÑÑ½¸ˆ°€‰…Ñ¥½¸ˆèì‰ÑåÁ”ˆè€‰Á½ÍÑ‰…¬ˆ°€‰±…‰•°ˆè€‹Â~J3–
Ï¦–wš<ˆ°€‰‘…Ñ„ˆè˜‰Íµ…ÉĞéİ¥Í éíÉ¥‘ôˆ°€‰‘¥ÍÁ±…åQ•áĞˆè€‹–
Ï¦–wš<‰ô°€‰ÍÑå±”ˆè€‰ÁÉ¥µ…Éäˆ°€‰½±½Èˆè€ˆÄÅĞàˆ°€‰¡•¥¡Ğˆè€‰Í´‰ô°(€€€€€€€€€€€€€€€ì‰ÑåÁ”ˆè€‰‰ÕÑÑ½¸ˆ°€‰…Ñ¥½¸ˆèì‰ÑåÁ”ˆè€‰Á½ÍÑ‰…¬ˆ°€‰±…‰•°ˆè€‹Šr–ŞË–º3š"@ˆ°€‰‘…Ñ„ˆè˜‰Íµ…ÉĞé‰±•ÍÍ•éíÉ¥‘ôˆ°€‰‘¥ÍÁ±…åQ•áĞˆè€‹–ŞË–º3š"@‰ô°€‰ÍÑå±”ˆè€‰Í•½¹‘…Éäˆ°€‰¡•¥¡Ğˆè€‰Í´‰ô°(€€€€€€€€€€€€€€€ì‰ÑåÁ”ˆè€‰‰ÕÑÑ½¸ˆ°€‰…Ñ¥½¸ˆèì‰ÑåÁ”ˆè€‰Á½ÍÑ‰…¬ˆ°€‰±…‰•°ˆè€‹Š>Ãšfk¦î{š>C¦Kš"Dˆ°€‰‘…Ñ„ˆè˜‰Íµ…ÉĞéÍ¹½½é”éíÉ¥‘ôˆ°€‰‘¥ÍÁ±…åQ•áĞˆè€‹šfk¦î{š>C¦Kš"D‰ô°€‰ÍÑå±”ˆè€‰Í•½¹‘…Éäˆ°€‰¡•¥¡Ğˆè€‰Í´‰ô°(€€€€€€€€€€€t(€€€€€€€…±Ğ€ô˜‹’î+–’§šb½í¹…µ•÷jí±…‰•±ôˆ(€€€É•ÑÕÉ¸ì(€€€€€€€€‰ÑåÁ”ˆè€‰™±•àˆ°(€€€€€€€€‰…±ÑQ•áĞˆè…±Ğ°(€€€€€€€€‰½¹Ñ•¹ÑÌˆèì(€€€€€€€€€€€€‰ÑåÁ”ˆè€‰‰Õ‰‰±”ˆ°(€€€€€€€€€€€€‰Í¥é”ˆè€‰µ•„ˆ°(€€€€€€€€€€€€‰‰½‘äˆèì(€€€€€€€€€€€€€€€€‰ÑåÁ”ˆè€‰‰½àˆ°(€€€€€€€€€€€€€€€€‰±…å½ÕĞˆè€‰Ù•ÉÑ¥…°ˆ°(€€€€€€€€€€€€€€€€‰ÍÁ…¥¹œˆè€‰µˆ°(€€€€€€€€€€€€€€€€‰½¹Ñ•¹ÑÌˆèl(€€€€€€€€€€€€€€€€€€€ì‰ÑåÁ”ˆè€‰Ñ•áĞˆ°€‰Ñ•áĞˆèÑ¥Ñ±”°€‰İ•¥¡Ğˆè€‰‰½±ˆ°€‰Í¥é”ˆè€‰á°ˆ°€‰İÉ…ÀˆèQÉÕ•ô°(€€€€€€€€€€€€€€€€€€€ì‰ÑåÁ”ˆè€‰Ñ•áĞˆ°€‰Ñ•áĞˆè‰½‘ä°€‰Í¥é”ˆè€‰µˆ°€‰½±½Èˆè€ˆŒĞĞĞĞĞĞˆ°€‰İÉ…ÀˆèQÉÕ•ô°(€€€€€€€€€€€€€€€€€€€ì‰ÑåÁ”ˆè€‰Ñ•áĞˆ°€‰Ñ•áĞˆè€‹Â~J°ƒš¶“š>C¦K–>«–
Ï–"Ã’öƒj1%9ƒ¢¢+¾ò#’â7šr¦Ë–º#¢¶ßú“¾ò$ˆ°€‰Í¥é”ˆè€‰áÌˆ°€‰½±½Èˆè€ˆŒààààààˆ°€‰İÉ…ÀˆèQÉÕ•ô°(€€€€€€€€€€€€€€€t°(€€€€€€€€€€€ô°(€€€€€€€€€€€€‰™½½Ñ•Èˆèì(€€€€€€€€€€€€€€€€‰ÑåÁ”ˆè€‰‰½àˆ°(€€€€€€€€€€€€€€€€‰±…å½ÕĞˆè€‰Ù•ÉÑ¥…°ˆ°(€€€€€€€€€€€€€€€€‰ÍÁ…¥¹œˆè€‰Í´ˆ°(€€€€€€€€€€€€€€€€‰½¹Ñ•¹ÑÌˆè‰ÕÑÑ½¹Ì°(€€€€€€€€€€€ô°(€€€€€€€ô°(€€€ô(()‘•˜‰Õ¥±‘}Íµ…ÉÑ}É•µ¥¹‘•É}‘¥•ÍĞ¡É•µ¥¹‘•ÉÌ°€¨°µ½‘”ô‰‘…äˆ¤è(€€€É•µ¥¹‘•ÉÌ€ô±¥ÍĞ¡É•µ¥¹‘•ÉÌ½Èmt¤(€€€¥˜±•¸¡É•µ¥¹‘•ÉÌ¤€ôô€Äè(€€€€€€€É•ÑÕÉ¸‰Õ¥±‘}Íµ…ÉÑ}É•µ¥¹‘•É}™±•à¡É•µ¥¹‘•ÉÍlÁt°µ½‘”õµ½‘”¤(€€€İ¡•¸€ô€‹šb;–’¤ˆ¥˜µ½‘”€ôô€‰•Ù”ˆ•±Í”€‹’î+–’¤ˆ(€€€±¥¹•Ì€ôl(€€€€€€€˜‰í¥Ñ•´¹•Ğ •µ½©¤œ¤½È€ŸÂ~^O¾â<ôí¥Ñ•´¹•Ğ Ñ…É•Ñ}¹…µ”œ¤½È€Ÿ–Â7¢Æ„÷¾òhˆ(€€€€€€€˜‰í¥Ñ•´¹•Ğ …Ñ•½Éå}±…‰•°œ¤½È€Ÿš>C¦Hôˆ(€€€€€€€™½È¥Ñ•´¥¸É•µ¥¹‘•ÉÌ(€€€t(€€€É•ÑÕÉ¸ì(€€€€€€€€‰ÑåÁ”ˆè€‰™±•àˆ°(€€€€€€€€‰…±ÑQ•áĞˆè˜‰íİ¡•¹÷šr$í±•¸¡É•µ¥¹‘•ÉÌ¥ôƒ–/š>C¦Hˆ°(€€€€€€€€‰½¹Ñ•¹ÑÌˆèì(€€€€€€€€€€€€‰ÑåÁ”ˆè€‰‰Õ‰‰±”ˆ°(€€€€€€€€€€€€‰Í¥é”ˆè€‰µ•„ˆ°(€€€€€€€€€€€€‰‰½‘äˆèì(€€€€€€€€€€€€€€€€‰ÑåÁ”ˆè€‰‰½àˆ°(€€€€€€€€€€€€€€€€‰±…å½ÕĞˆè€‰Ù•ÉÑ¥…°ˆ°(€€€€€€€€€€€€€€€€‰ÍÁ…¥¹œˆè€‰µˆ°(€€€€€€€€€€€€€€€€‰½¹Ñ•¹ÑÌˆèl(€€€€€€€€€€€€€€€€€€€ì‰ÑåÁ”ˆè€‰Ñ•áĞˆ°€‰Ñ•áĞˆè˜‹Â~^O¾â<íİ¡•¹÷šr$í±•¸¡É•µ¥¹‘•ÉÌ¥ôƒ–/š>C¦Hˆ°€‰İ•¥¡Ğˆè€‰‰½±ˆ°€‰Í¥é”ˆè€‰á°ˆ°€‰İÉ…ÀˆèQÉÕ•ô°(€€€€€€€€€€€€€€€€€€€ì‰ÑåÁ”ˆè€‰Ñ•áĞˆ°€‰Ñ•áĞˆè€‰q¸ˆ¹©½¥¸¡±¥¹•Ì¤°€‰Í¥é”ˆè€‰µˆ°€‰İÉ…ÀˆèQÉÕ•ô°(€€€€€€€€€€€€€€€€€€€ì‰ÑåÁ”ˆè€‰Ñ•áĞˆ°€‰Ñ•áĞˆè€‹–B3’âšfšº×–ŞË–B#’ö×š"C’â–&¾ò3¦ÿ–7¦7¢’š&OšNøˆ°€‰Í¥é”ˆè€‰áÌˆ°€‰½±½Èˆè€ˆŒààààààˆ°€‰İÉ…ÀˆèQÉÕ•ô°(€€€€€€€€€€€€€€€t°(€€€€€€€€€€€ô°(€€€€€€€ô°(€€€ô(()‘•˜¥Í}¡•­¥¹}Á½ÍÑ‰…¬¡‘…Ñ„¤è(€€€€ˆˆ‰…¥±äÁÕÍ €¼±•àƒ3š"G–æÏ–º'4Á½ÍÑ‰…¬¸ˆˆˆ(€€€Ñ•áĞ€ôÍÑÈ¡‘…Ñ„½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€¥˜¹½ĞÑ•áĞè(€€€€€€€É•ÑÕÉ¸…±Í”(€€€¥˜Ñ•áĞ¥¸ì‰…Ñ¥½¸õ¡•­¥¸ˆ°€‰¡•­¥¸ˆ°€‰¡•­¥¸é½¬ˆ°€‰¡•­¥¸ôÄ‰ôè(€€€€€€€É•ÑÕÉ¸QÉÕ”(€€€¥˜Ñ•áĞ¹ÍÑ…ÉÑÍİ¥Ñ  ‰…Ñ¥½¸õ¡•­¥¸ˆ¤è(€€€€€€€É•ÑÕÉ¸QÉÕ”(€€€¥˜Ñ•áĞ¹ÍÑ…ÉÑÍİ¥Ñ  ‰¡•­¥¸èˆ¤è(€€€€€€€É•ÑÕÉ¸QÉÕ”(€€€ÑÉäè(€€€€€€€™É½´…±•ÉÑÌ¹Á½ÍÑ‰…¬¥µÁ½ÉĞÁ…ÉÍ•}Á½ÍÑ‰…­}‘…Ñ„(€€€€€€€É•ÑÕÉ¸Á…ÉÍ•}Á½ÍÑ‰…­}‘…Ñ„¡Ñ•áĞ¤¹•Ğ ‰…Ñ¥½¸ˆ¤€ôô€‰¡•­¥¸ˆ(€€€•á•ÁĞá•ÁÑ¥½¸è(€€€€€€€É•ÑÕÉ¸€‰…Ñ¥½¸õ¡•­¥¸ˆ¥¸Ñ•áĞ(()‘•˜¡…¹‘±•}¡•­¥¹}Á½ÍÑ‰…¬¡‘…Ñ…}™¥±”°±¥¹•}ÕÍ•É}¥°½¹™¥œõ9½¹”¤è(€€€€ˆˆ‰A•ÉÍ¥ÍĞ¡•¬µ¥¸™É½´1%9Á½ÍÑ‰…¬ƒŠPÍ…µ”Á…Ñ …Ì1%€½…Á¤½¡•­¥¸¸((€€€I•ÑÕÉ¹ÌÑ•áĞ°½È„±¥ÍĞ½˜mÑ•áĞ°½ÁÑ¥½¹…°•áÁ¥Éä±•átİ¡•¸µ•µ‰•ÉÍ¡¥À¥Ì¹•…È•áÁ¥Éä¸(€€€€ˆˆˆ(€€€¥˜¹½Ğ±¥¹•}ÕÍ•É}¥è(€€€€€€€É•ÑÕÉ¸€‹¢®/–#–*ƒ–—š¾?š^—–æÏ–º'––÷–>/–ú3–7–‚Ç–æÏ–º'ˆ(€€€ÍÑ…ÑÕÌ€ôÉ•½É‘}¡•­¥¸¡‘…Ñ…}™¥±”°ì‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥‘ô°½¹™¥œõ½¹™¥œ¤(€€€¹½Ü€ôÕÉÉ•¹Ñ}…ÁÁ}Ñ¥µ”¡½¹™¥œ¤(€€€Ñ•áĞ€ô‰Õ¥±‘}¡•­¥¹}ÍÕ•ÍÍ}Ñ•áĞ¡ÍÑ…ÑÕÌ°¹½Üõ¹½Ü°½¹™¥œõ½¹™¥œ¤(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€ÁÉ½™¥±”€ô•Ñ}ÁÉ½™¥±”¡ÍÑ…Ñ”°±¥¹•}ÕÍ•É}¥¤(€€€µ•ÍÍ…•Ì€ôµ…å‰•}…ÑÑ…¡}•áÁ¥Éå}É•µ¥¹ (€€€€€€€mÑ•áÑt°ÁÉ½™¥±”°¹½Üõ¹½Ü°ÍÑ…Ñ”õÍÑ…Ñ”°‘…Ñ…}™¥±”õ‘…Ñ…}™¥±”(€€€€¤(€€€¥˜±•¸¡µ•ÍÍ…•Ì¤€ôô€Äè(€€€€€€€É•ÑÕÉ¸µ•ÍÍ…•ÍlÁt(€€€É•ÑÕÉ¸µ•ÍÍ…•Ì(()‘•˜¥Í}•áÁ¥Éå}½ÁÑ}½ÕÑ}Á½ÍÑ‰…¬¡‘…Ñ„¤è(€€€Ñ•áĞ€ôÍÑÈ¡‘…Ñ„½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€É•ÑÕÉ¸Ñ•áĞ€ôô€‰…Ñ¥½¸õ•áÁ¥Éå}½ÁÑ}½ÕĞˆ½È€‰…Ñ¥½¸õ•áÁ¥Éå}½ÁÑ}½ÕĞˆ¥¸Ñ•áĞ(()‘•˜¡…¹‘±•}Íµ…ÉÑ}É•µ¥¹‘•É}Á½ÍÑ‰…¬¡‘…Ñ…}™¥±”°±¥¹•}ÕÍ•É}¥°‘…Ñ„°½¹™¥œõ9½¹”¤è(€€€€ˆˆ‰!…¹‘±”Íµ…ÉĞè¨Á½ÍÑ‰…­ÌìÉ•ÑÕÉ¹ÌÉ•Á±äÑ•áĞ¸ˆˆˆ(€€€Á…ÉÑÌ€ôÍÑÈ¡‘…Ñ„½È€ˆˆ¤¹ÍÁ±¥Ğ ˆèˆ¤(€€€¥˜±•¸¡Á…ÉÑÌ¤€ğ€Ì½ÈÁ…ÉÑÍlÁt€„ô€‰Íµ…ÉĞˆè(€€€€€€€É•ÑÕÉ¸9½¹”(€€€…Ñ¥½¸°É¥€ôÁ…ÉÑÍlÅt°Á…ÉÑÍlÉt(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€ÁÉ½™¥±”€ô•Ñ}ÁÉ½™¥±”¡ÍÑ…Ñ”°±¥¹•}ÕÍ•É}¥¤(€€€É•µ¥¹‘•È€ô¹•áĞ ¡È™½ÈÈ¥¸±¥ÍÑ}Íµ…ÉÑ}É•µ¥¹‘•ÉÌ¡ÁÉ½™¥±”¤¥˜È¹•Ğ ‰¥ˆ¤€ôôÉ¥¤°9½¹”¤(€€€¥˜¹½ĞÉ•µ¥¹‘•Èè(€€€€€€€É•ÑÕÉ¸€‹š&û’â7–"Ã¦g¶šfë¢÷š>C¦K¾ò3–>¿¢÷–ŞË¢Š¯–"«¦f“ˆ(€€€¥˜…Ñ¥½¸€ôô€‰İ¥Í ˆè(€€€€€€€É•ÑÕÉ¸Íµ…ÉÑ}É•µ¥¹‘•É}…¹¹•‘}İ¥Í ¡É•µ¥¹‘•È¤(€€€¥˜…Ñ¥½¸€ôô€‰¥™Ğˆè(€€€€€€€É•ÑÕÉ¸Íµ…ÉÑ}É•µ¥¹‘•É}…¹¹•‘}¥™Ğ¡É•µ¥¹‘•È¤(€€€¥˜…Ñ¥½¸€ôô€‰…±°ˆè(€€€€€€€É•ÑÕÉ¸˜‹Â~Nxƒ>û–r£–ÂÇ–>¿’î—šJ—¦nï¢¦ÇÖ›1íÉ•µ¥¹‘•È¹•Ğ Ñ…É•Ñ}¹…µ”œ¥÷7š&O–º3–ú3–>¿–n{3–ŞË–º3š"C7ˆ(€€€¥˜…Ñ¥½¸€ôô€‰‰±•ÍÍ•ˆè(€€€€€€€É•ÑÕÉ¸˜‹–’«––÷’ê¾ò3–ŞË–æ¯’öƒ¢¢c’â/3–ŞË–wš?¾ò?–ŞË–º3š"C7¾òiíÉ•µ¥¹‘•È¹•Ğ Ñ…É•Ñ}¹…µ”œ¥÷ˆ(€€€¥˜…Ñ¥½¸€ôô€‰Í¹½½é”ˆè(€€€€€€€€Œ5…É¬„Í½™ĞÍ¹½½é”­•äÍ¼‘…äÉ½¸…¸É”µ¹Õ‘”±…Ñ•ÈÍ…µ”‘…ä½¹”(€€€€€€€­•åÌ€ôÍ•Ğ¡ÁÉ½™¥±”¹•Ğ ‰Íµ…ÉÑ}É•µ¥¹‘•É}Í•¹Ñ}­•åÌˆ¤½Èmt¤(€€€€€€€Ñ½‘…ä€ôÑ½‘…å}ÍÑÉ¥¹œ¡½¹™¥œ¤(€€€€€€€€ŒI•µ½Ù”‘…ä­•äÑ¼…±±½Ü½¹”É”µÍ•¹…™Ñ•È€É Ù¥„Í•Á…É…Ñ”Í¹½½é”µ…É­•È(€€€€€€€ÁÉ½™¥±•l‰Íµ…ÉÑ}É•µ¥¹‘•É}Í¹½½é”‰t€ôì(€€€€€€€€€€€€‰¥ˆèÉ¥°(€€€€€€€€€€€€‰Õ¹Ñ¥°ˆè€¡ÕÉÉ•¹Ñ}…ÁÁ}Ñ¥µ”¡½¹™¥œ¤€¬Ñ¥µ•‘•±Ñ„¡¡½ÕÉÌôÈ¤¤¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤°(€€€€€€€ô(€€€€€€€€Œ-••À‘…ä­•äÍ¼İ”‘½¸Ğ‘½Õ‰±”µ™¥É”¥µµ•‘¥…Ñ•±äìÍ¹½½é”Á…Ñ ÕÍ•ÌÕ¹Ñ¥°(€€€€€€€­•åÌ€ôí¬™½È¬¥¸­•åÌ¥˜¹½Ğ¬¹•¹‘Íİ¥Ñ ¡˜ˆéíÉ¥‘ôé‘…äˆ¥ô(€€€€€€€ÁÉ½™¥±•l‰Íµ…ÉÑ}É•µ¥¹‘•É}Í•¹Ñ}­•åÌ‰t€ôÍ½ÉÑ•¡­•åÌ¥l´ÄÈÀét(€€€€€€€Í…Ù•}ÍÑ…Ñ”¡‘…Ñ…}™¥±”°ÍÑ…Ñ”¤(€€€€€€€É•ÑÕÉ¸€‹––÷¾ò3Ò€Èƒ–Â?šf–ú3–7¢¢+š>C¦K’öƒ’âš²‡ˆ(€€€É•ÑÕÉ¸€‹–ŞËšRÛ–"Ãˆ(()‘•˜•Ñ}Íµ…ÉÑ}É•µ¥¹‘•ÉÍ}Á…å±½…¡‘…Ñ…}™¥±”°±¥¹•}ÕÍ•É}¥¤è(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€ÁÉ½™¥±”€ô•Ñ}ÁÉ½™¥±”¡ÍÑ…Ñ”°±¥¹•}ÕÍ•É}¥¤(€€€•¹Ñ¥Ñ±•€ôÁ±…¹}¡…Í}Íµ…ÉÑ}É•µ¥¹‘•ÉÌ¡ÁÉ½™¥±”¤(€€€É•½Ù•É¥¹œ€ôÍÑÈ¡ÁÉ½™¥±”¹•Ğ ‰…½Õ¹Ñ}µ¥É…Ñ¥½¹}ÍÑ…ÑÕÌˆ¤½È€ˆˆ¤¹±½İ•È ¤¥¸ì(€€€€€€€€‰Á•¹‘¥¹œˆ°€‰É•½Ù•É¥¹œˆ°€‰¥¹}ÁÉ½É•ÍÌˆ(€€€ô(€€€Ñ½‘…ä€ô‘…Ñ•Ñ¥µ”¹¹½Ü ¤¹ÍÑÉ™Ñ¥µ” ˆ•d´•´´•ˆ¤(€€€ÕÍ…”€ô€¡ÁÉ½™¥±”¹•Ğ ‰Íµ…ÉÑ}É•µ¥¹‘•É}‘…¥±å}ÕÍ…”ˆ¤½Èíô¤¹•Ğ¡Ñ½‘…ä¤½Èíô(€€€‰½Õ¹‘}Õ…É‘¥…¹Ì€ômt(€€€™½È½¹Ñ…Ğ¥¸ÁÉ½™¥±”¹•Ğ ‰½¹Ñ…ÑÌˆ¤½Èmtè(€€€€€€€¥˜¹½Ğ½¹Ñ…Ñ}¥Í}‰½Õ¹‘}Õ…É‘¥…¸¡½¹Ñ…Ğ°±¥¹•}ÕÍ•É}¥¤è(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€Õ…É‘¥…¹}¥€ô•Ñ}½¹Ñ…Ñ}±¥¹•}¥¡½¹Ñ…Ğ¤(€€€€€€€¥˜¹½ĞÕ…É‘¥…¹}¥è(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€‰½Õ¹‘}Õ…É‘¥…¹Ì¹…ÁÁ•¹¡ì(€€€€€€€€€€€€‰±¥¹•}ÕÍ•É}¥ˆèÕ…É‘¥…¹}¥°(€€€€€€€€€€€€‰¹…µ”ˆè½¹Ñ…Ğ¹•Ğ ‰¹…µ”ˆ¤½È½¹Ñ…Ğ¹•Ğ ‰‘¥ÍÁ±…å}¹…µ”ˆ¤½È€‹š‚ã–ş–º#¢¶ß’êèˆ°(€€€€€€€€€€€€‰¥Í}ÁÉ¥µ…Éäˆè‰½½°¡½¹Ñ…Ğ¹•Ğ ‰¥Í}ÁÉ¥µ…Éäˆ¤¤°(€€€€€€€ô¤(€€€É•ÑÕÉ¸ì(€€€€€€€€‰½¬ˆèQÉÕ”°(€€€€€€€€‰•¹Ñ¥Ñ±•ˆè•¹Ñ¥Ñ±•°(€€€€€€€€‰ÍÑ…Ñ”ˆè€‰•¹Ñ¥Ñ±•ˆ¥˜•¹Ñ¥Ñ±••±Í”€ ‰É•½Ù•É¥¹œˆ¥˜É•½Ù•É¥¹œ•±Í”€‰ÕÁÉ…‘•}É•ÅÕ¥É•ˆ¤°(€€€€€€€€‰Á±…¸ˆèÁÉ½™¥±”¹•Ğ ‰Á±…¸ˆ¤½È€‰ÑÉ¥…°ˆ°(€€€€€€€€‰ÕÁÉ…‘•}¡¥¹Ğˆè9½¹”¥˜•¹Ñ¥Ñ±••±Í”€ (€€€€€€€€€€€€‹–âÏ¢f¢ÎšZgš¶–r£š‹–ú§¾ò3–º3š"C–ú3šr¢«–.W–>[–n{š^‹šr'šfëšŸš>C¦Hˆ(€€€€€€€€€€€¥˜É•½Ù•É¥¹œ•±Í”(€€€€€€€€€€€€‹šfë¢÷š>C¦K
è€Üääƒ–º#¢¶ß&#–*¢÷¾ò3–6Òk–ú3–>¿¢¢·–ºkRš^—¾ò?Ò–ş×š^—¾ò?–n{¢¢ë¶'RšÒïš>C¦K¾ò#’â7¦Ë–º#¢¶ßú“¾ò'ˆ(€€€€€€€€¤°(€€€€€€€€‰É•µ¥¹‘•ÉÌˆè±¥ÍÑ}Íµ…ÉÑ}É•µ¥¹‘•ÉÌ¡ÁÉ½™¥±”¤¥˜•¹Ñ¥Ñ±••±Í”mt°(€€€€€€€€‰‘•™…Õ±ÑÌˆèÁÉ½™¥±”¹•Ğ ‰Íµ…ÉÑ}É•µ¥¹‘•É}‘•™…Õ±ÑÌˆ¤½Èì‰¹½Ñ¥™å}ÁÉ¥Ù…Ñ”ˆèQÉÕ”°€‰¹½Ñ¥™å}É½ÕÀˆè…±Í•ô°(€€€€€€€€‰‰½Õ¹‘}Õ…É‘¥…¹Ìˆè‰½Õ¹‘}Õ…É‘¥…¹Ì¥˜•¹Ñ¥Ñ±••±Í”mt°(€€€€€€€€‰‘…¥±å}ÕÍ…”ˆèì(€€€€€€€€€€€€‰ÁÉ¥Ù…Ñ”ˆè¥¹Ğ¡ÕÍ…”¹•Ğ ‰ÁÉ¥Ù…Ñ”ˆ¤½È€À¤°(€€€€€€€€€€€€‰Õ…É‘¥…¸ˆè¥¹Ğ¡ÕÍ…”¹•Ğ ‰Õ…É‘¥…¸ˆ¤½È€À¤°(€€€€€€€ô°(€€€€€€€€‰‘…¥±å}±¥µ¥ÑÌˆèì‰ÁÉ¥Ù…Ñ”ˆè€È°€‰Õ…É‘¥…¸ˆè€Åô°(€€€€€€€€‰…Ñ•½É¥•Ìˆèl(€€€€€€€€€€€ì‰¥ˆè­•ä°€‰•µ½©¤ˆèµ•Ñ…l‰•µ½©¤‰t°€‰±…‰•°ˆèµ•Ñ…l‰±…‰•°‰uô(€€€€€€€€€€€™½È­•ä°µ•Ñ„¥¸M5IQ}I5%9I}Q=I%L¹¥Ñ•µÌ ¤(€€€€€€€t°(€€€ô(()‘•˜Í…Ù•}Íµ…ÉÑ}É•µ¥¹‘•È¡‘…Ñ…}™¥±”°Á…å±½…¤è(€€€±¥¹•}ÕÍ•É}¥€ôÍÑÈ¡Á…å±½…¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€¥˜¹½Ğ±¥¹•}ÕÍ•É}¥è(€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰µ¥ÍÍ¥¹œ±¥¹•}ÕÍ•É}¥‰ô°€ĞÀÀ(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€ÁÉ½™¥±”€ô•Ñ}ÁÉ½™¥±”¡ÍÑ…Ñ”°±¥¹•}ÕÍ•É}¥¤(€€€¥˜¹½ĞÁ±…¹}¡…Í}Íµ…ÉÑ}É•µ¥¹‘•ÉÌ¡ÁÉ½™¥±”¤è(€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰Íµ…ÉÑ}É•µ¥¹‘•ÉÍ}É•ÅÕ¥É•|Üääˆ°€‰ÕÁÉ…‘•}¡¥¹Ğˆè€‹¢®/–6Òh€Üääƒ–º#¢¶ß& ‰ô°€ĞÀÌ(€€€‘•±¥Ù•Éå}Ñ…É•Ğ€ôÍÑÈ¡Á…å±½…¹•Ğ ‰‘•±¥Ù•Éå}Ñ…É•Ğˆ¤½È€‰ÁÉ¥Ù…Ñ”ˆ¤¹ÍÑÉ¥À ¤(€€€¥˜‘•±¥Ù•Éå}Ñ…É•Ğ¹ÍÑ…ÉÑÍİ¥Ñ  ‰É½ÕÀèˆ¤è(€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰Õ…É‘¥…¹}É½ÕÁ}Ñ…É•Ñ}¹½Ñ}…±±½İ•‰ô°€ĞÀÀ(€€€¥˜‘•±¥Ù•Éå}Ñ…É•Ğ€„ô€‰ÁÉ¥Ù…Ñ”ˆè(€€€€€€€¥˜¹½Ğ‘•±¥Ù•Éå}Ñ…É•Ğ¹ÍÑ…ÉÑÍİ¥Ñ  ‰Õ…É‘¥…¸èˆ¤è(€€€€€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰¥¹Ù…±¥‘}‘•±¥Ù•Éå}Ñ…É•Ğ‰ô°€ĞÀÀ(€€€€€€€Ñ…É•Ñ}¥€ô‘•±¥Ù•Éå}Ñ…É•Ğ¹ÍÁ±¥Ğ ˆèˆ°€Ä¥lÅt(€€€€€€€…±±½İ•€ôì(€€€€€€€€€€€•Ñ}½¹Ñ…Ñ}±¥¹•}¥¡½¹Ñ…Ğ¤(€€€€€€€€€€€™½È½¹Ñ…Ğ¥¸ÁÉ½™¥±”¹•Ğ ‰½¹Ñ…ÑÌˆ¤½Èmt(€€€€€€€€€€€¥˜½¹Ñ…Ñ}¥Í}‰½Õ¹‘}Õ…É‘¥…¸¡½¹Ñ…Ğ°±¥¹•}ÕÍ•É}¥¤(€€€€€€€ô(€€€€€€€¥˜Ñ…É•Ñ}¥¹½Ğ¥¸…±±½İ•è(€€€€€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰Õ…É‘¥…¹}Ñ…É•Ñ}¹½Ñ}‰½Õ¹‰ô°€ĞÀÀ(€€€É•µ¥¹‘•È€ô¹½Éµ…±¥é•}Íµ…ÉÑ}É•µ¥¹‘•È¡Á…å±½…°€À¤(€€€É•µ¥¹‘•Él‰ÕÁ‘…Ñ•‘}…Ğ‰t€ôÕÉÉ•¹Ñ}…ÁÁ}Ñ¥µ”¡íô¤¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤(€€€É½İÌ€ô±¥ÍÑ}Íµ…ÉÑ}É•µ¥¹‘•ÉÌ¡ÁÉ½™¥±”¤(€€€É•Á±…•€ô…±Í”(€€€™½È¤°É½Ü¥¸•¹Õµ•É…Ñ”¡É½İÌ¤è(€€€€€€€¥˜É½Ü¹•Ğ ‰¥ˆ¤€ôôÉ•µ¥¹‘•Él‰¥‰tè(€€€€€€€€€€€É•µ¥¹‘•Él‰É•…Ñ•‘}…Ğ‰t€ôÉ½Ü¹•Ğ ‰É•…Ñ•‘}…Ğˆ¤½ÈÉ•µ¥¹‘•Él‰É•…Ñ•‘}…Ğ‰t(€€€€€€€€€€€É½İÍm¥t€ôÉ•µ¥¹‘•È(€€€€€€€€€€€É•Á±…•€ôQÉÕ”(€€€€€€€€€€€‰É•…¬(€€€¥˜¹½ĞÉ•Á±…•è(€€€€€€€¥˜±•¸¡É½İÌ¤€øô€ĞÀè(€€€€€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰Íµ…ÉÑ}É•µ¥¹‘•É}±¥µ¥Ğ‰ô°€ĞÀÀ(€€€€€€€É½İÌ¹…ÁÁ•¹¡É•µ¥¹‘•È¤(€€€ÁÉ½™¥±•l‰Íµ…ÉÑ}É•µ¥¹‘•ÉÌ‰t€ôÉ½İÌ(€€€€ŒƒR‹–NšÆë¶[¾òkšfë¢÷š>C¦KšÂã¦ƒ–>«¢¢+¾ò3ú“Öš^_š¢g–në–ºk¦^s¦Z$(€€€ÁÉ½™¥±•l‰Íµ…ÉÑ}É•µ¥¹‘•É}‘•™…Õ±ÑÌ‰t€ôì‰¹½Ñ¥™å}ÁÉ¥Ù…Ñ”ˆèQÉÕ”°€‰¹½Ñ¥™å}É½ÕÀˆè…±Í•ô(€€€Í…Ù•}ÍÑ…Ñ”¡‘…Ñ…}™¥±”°ÍÑ…Ñ”¤(€€€É•ÑÕÉ¸ì‰½¬ˆèQÉÕ”°€‰É•µ¥¹‘•ÈˆèÉ•µ¥¹‘•È°€‰É•µ¥¹‘•ÉÌˆèÉ½İÍô°€ÈÀÀ(()‘•˜‘•±•Ñ•}Íµ…ÉÑ}É•µ¥¹‘•È¡‘…Ñ…}™¥±”°±¥¹•}ÕÍ•É}¥°É•µ¥¹‘•É}¥¤è(€€€±¥¹•}ÕÍ•É}¥€ôÍÑÈ¡±¥¹•}ÕÍ•É}¥½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€É•µ¥¹‘•É}¥€ôÍÑÈ¡É•µ¥¹‘•É}¥½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€¥˜¹½Ğ±¥¹•}ÕÍ•É}¥½È¹½ĞÉ•µ¥¹‘•É}¥è(€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰µ¥ÍÍ¥¹œ¥‰ô°€ĞÀÀ(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€ÁÉ½™¥±”€ô•Ñ}ÁÉ½™¥±”¡ÍÑ…Ñ”°±¥¹•}ÕÍ•É}¥¤(€€€¥˜¹½ĞÁ±…¹}¡…Í}Íµ…ÉÑ}É•µ¥¹‘•ÉÌ¡ÁÉ½™¥±”¤è(€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰Íµ…ÉÑ}É•µ¥¹‘•ÉÍ}É•ÅÕ¥É•|Üää‰ô°€ĞÀÌ(€€€É½İÌ€ômÈ™½ÈÈ¥¸±¥ÍÑ}Íµ…ÉÑ}É•µ¥¹‘•ÉÌ¡ÁÉ½™¥±”¤¥˜È¹•Ğ ‰¥ˆ¤€„ôÉ•µ¥¹‘•É}¥‘t(€€€ÁÉ½™¥±•l‰Íµ…ÉÑ}É•µ¥¹‘•ÉÌ‰t€ôÉ½İÌ(€€€Í…Ù•}ÍÑ…Ñ”¡‘…Ñ…}™¥±”°ÍÑ…Ñ”¤(€€€É•ÑÕÉ¸ì‰½¬ˆèQÉÕ”°€‰É•µ¥¹‘•ÉÌˆèÉ½İÍô°€ÈÀÀ(()‘•˜Í•¹‘}Íµ…ÉÑ}É•µ¥¹‘•ÉÌ¡½¹™¥œ¤è(€€€€ˆˆ‰AÕÍ µ•É•°…ÁÁ•Íµ…ÉĞÉ•µ¥¹‘•ÉÌÑ¼Í•±˜½È½¹”‰½Õ¹½É”Õ…É‘¥…¸¸ˆˆˆ(€€€Ñ½­•¸€ô½¹™¥œ¹•Ğ ‰1%9}!991}MM}Q=-8ˆ¤½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}!991}MM}Q=-8ˆ°€ˆˆ¤(€€€¥˜¹½ĞÑ½­•¸è(€€€€€€€É•ÑÕÉ¸ì‰Í•¹Ğˆè€À°€‰Í­¥ÁÁ•ˆè€À°€‰•ÉÉ½Èˆè€‰1%9}!991}MM}Q=-8¥Ì¹½ĞÍ•Ğ‰ô°€ĞÀÀ((€€€‘…Ñ…}™¥±”€ô½¹™¥l‰Q}%1‰t(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€Í•¹‘•È€ô½¹™¥œ¹•Ğ ‰1%9}AUM!}M9Hˆ¤½È±¥¹•}ÁÕÍ¡}µ•ÍÍ…”(€€€¹½Ü€ôÕÉÉ•¹Ñ}…ÁÁ}Ñ¥µ”¡½¹™¥œ¤(€€€Ñ½‘…å}‘…Ñ”€ô¹½Ü¹‘…Ñ” ¤(€€€Ñ½µ½ÉÉ½Ü€ôÑ½‘…å}‘…Ñ”€¬Ñ¥µ•‘•±Ñ„¡‘…åÌôÄ¤(€€€Ñ½‘…å}­•ä€ôÑ½‘…å}‘…Ñ”¹ÍÑÉ™Ñ¥µ” ˆ•d´•´´•ˆ¤(€€€Í•¹Ğ€ô€À(€€€Í­¥ÁÁ•€ô€À(€€€É•ÍÕ±ÑÌ€ômt(€€€¹½İ}¡´€ô¹½Ü¹ÍÑÉ™Ñ¥µ” ˆ• è•4ˆ¤(€€€•Ù•}İ¥¹‘½Ü€ô¹½Ü¹¡½ÕÈ€øô€ÈÀ(€€€ÍåÍÑ•µ}•ÉÉ½È€ô…±Í”((€€€™½ÈÕÍ•È¥¸ÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ°íô¤¹Ù…±Õ•Ì ¤è(€€€€€€€±¥¹•}ÕÍ•É}¥€ôÕÍ•È¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤(€€€€€€€¥˜€ (€€€€€€€€€€€¹½Ğ±¥¹•}ÕÍ•É}¥(€€€€€€€€€€€½ÈÕÍ•È¹•Ğ ‰µ•µ‰•ÉÍ¡¥Á}Á…ÕÍ•ˆ¤(€€€€€€€€€€€½È¹½Ğµ•µ‰•ÉÍ¡¥Á}…•ÍÍ}…Ñ¥Ù”¡ÕÍ•È°¹½Ü¤(€€€€€€€€€€€½È¹½ĞÁ±…¹}¡…Í}Íµ…ÉÑ}É•µ¥¹‘•ÉÌ¡ÕÍ•È¤(€€€€€€€€¤è(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€Í•¹Ñ}­•åÌ€ôÍ•Ğ¡ÕÍ•È¹•Ğ ‰Íµ…ÉÑ}É•µ¥¹‘•É}Í•¹Ñ}­•åÌˆ¤½Èmt¤(€€€€€€€Í¹½½é”€ôÕÍ•È¹•Ğ ‰Íµ…ÉÑ}É•µ¥¹‘•É}Í¹½½é”ˆ¤½Èíô(€€€€€€€‘…¥±å}…±°€ôÕÍ•È¹Í•Ñ‘•™…Õ±Ğ ‰Íµ…ÉÑ}É•µ¥¹‘•É}‘…¥±å}ÕÍ…”ˆ°íô¤(€€€€€€€ÕÍ…”€ô‘…¥±å}…±°¹Í•Ñ‘•™…Õ±Ğ¡Ñ½‘…å}­•ä°ì‰ÁÉ¥Ù…Ñ”ˆè€À°€‰Õ…É‘¥…¸ˆè€Áô¤(€€€€€€€€Œ-••À½¹±ä„½µÁ…ĞÉ½±±¥¹œİ¥¹‘½Ü¸(€€€€€€€ÕÍ•Él‰Íµ…ÉÑ}É•µ¥¹‘•É}‘…¥±å}ÕÍ…”‰t€ôì(€€€€€€€€€€€­•äèÙ…±Õ”™½È­•ä°Ù…±Õ”¥¸‘…¥±å}…±°¹¥Ñ•µÌ ¤¥˜­•ä€øô€¡Ñ½‘…å}‘…Ñ”€´Ñ¥µ•‘•±Ñ„¡‘…åÌôÜ¤¤¹¥Í½™½Éµ…Ğ ¤(€€€€€€€ô(€€€€€€€‰½Õ¹‘}Õ…É‘¥…¹Ì€ôì(€€€€€€€€€€€•Ñ}½¹Ñ…Ñ}±¥¹•}¥¡½¹Ñ…Ğ¤(€€€€€€€€€€€™½È½¹Ñ…Ğ¥¸ÕÍ•È¹•Ğ ‰½¹Ñ…ÑÌˆ¤½Èmt(€€€€€€€€€€€¥˜½¹Ñ…Ñ}¥Í}‰½Õ¹‘}Õ…É‘¥…¸¡½¹Ñ…Ğ°±¥¹•}ÕÍ•É}¥¤(€€€€€€€ô(€€€€€€€‘Õ•}É½ÕÁÌ€ôíô(€€€€€€€™½ÈÉ•µ¥¹‘•È¥¸±¥ÍÑ}Íµ…ÉÑ}É•µ¥¹‘•ÉÌ¡ÕÍ•È¤è(€€€€€€€€€€€¥˜¹½ĞÉ•µ¥¹‘•È¹•Ğ ‰•¹…‰±•ˆ°QÉÕ”¤è(€€€€€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€É¥€ôÉ•µ¥¹‘•È¹•Ğ ‰¥ˆ¤(€€€€€€€€€€€É•µ¥¹‘}¡´€ôÍÑÈ¡É•µ¥¹‘•È¹•Ğ ‰É•µ¥¹‘}Ñ¥µ”ˆ¤½È€ˆÀäèÀÀˆ¤¹ÍÑÉ¥À ¤(€€€€€€€€€€€¥˜¹½ĞI5%9I}Q%5}AQQI8¹µ…Ñ ¡É•µ¥¹‘}¡´¤è(€€€€€€€€€€€€€€€É•µ¥¹‘}¡´€ô€ˆÀäèÀÀˆ(€€€€€€€€€€€Ñ…É•Ñ}ÍÁ•Œ€ôÍÑÈ¡É•µ¥¹‘•È¹•Ğ ‰‘•±¥Ù•Éå}Ñ…É•Ğˆ¤½È€‰ÁÉ¥Ù…Ñ”ˆ¤(€€€€€€€€€€€¥˜Ñ…É•Ñ}ÍÁ•Œ€ôô€‰ÁÉ¥Ù…Ñ”ˆè(€€€€€€€€€€€€€€€Ñ…É•Ñ}­¥¹°Ñ…É•Ñ}¥€ô€‰ÁÉ¥Ù…Ñ”ˆ°±¥¹•}ÕÍ•É}¥(€€€€€€€€€€€•±¥˜Ñ…É•Ñ}ÍÁ•Œ¹ÍÑ…ÉÑÍİ¥Ñ  ‰Õ…É‘¥…¸èˆ¤è(€€€€€€€€€€€€€€€Ñ…É•Ñ}­¥¹°Ñ…É•Ñ}¥€ô€‰Õ…É‘¥…¸ˆ°Ñ…É•Ñ}ÍÁ•Œ¹ÍÁ±¥Ğ ˆèˆ°€Ä¥lÅt(€€€€€€€€€€€€€€€¥˜Ñ…É•Ñ}¥¹½Ğ¥¸‰½Õ¹‘}Õ…É‘¥…¹Ìè(€€€€€€€€€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€¥˜¹½İ}¡´€øôÉ•µ¥¹‘}¡´…¹Íµ…ÉÑ}É•µ¥¹‘•É}½ÕÉÍ}½¸¡É•µ¥¹‘•È°Ñ½‘…å}‘…Ñ”¤è(€€€€€€€€€€€€€€€­•ä€ô˜‰íÑ½‘…å}­•åôéíÉ¥‘ôé‘…äˆ(€€€€€€€€€€€€€€€Í¹½½é•}Õ¹Ñ¥°€ôÁ…ÉÍ•}‘…Ñ•Ñ¥µ”¡Í¹½½é”¹•Ğ ‰Õ¹Ñ¥°ˆ¤¤¥˜Í¹½½é”¹•Ğ ‰¥ˆ¤€ôôÉ¥•±Í”9½¹”(€€€€€€€€€€€€€€€¥˜­•ä¥¸Í•¹Ñ}­•åÌ…¹¹½Ğ€¡Í¹½½é•}Õ¹Ñ¥°…¹¹½Ü€øôÍ¹½½é•}Õ¹Ñ¥°¤è(€€€€€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€€€€€¥˜Í¹½½é•}Õ¹Ñ¥°…¹¹½Ü€ğÍ¹½½é•}Õ¹Ñ¥°è(€€€€€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€€€€€‘Õ•}É½ÕÁÌ¹Í•Ñ‘•™…Õ±Ğ  ‰‘…äˆ°É•µ¥¹‘}¡´°Ñ…É•Ñ}­¥¹°Ñ…É•Ñ}¥¤°mt¤¹…ÁÁ•¹ ¡­•ä°É•µ¥¹‘•È¤¤(€€€€€€€€€€€¥˜•Ù•}İ¥¹‘½Ü…¹É•µ¥¹‘•È¹•Ğ ‰•Ù•}É•µ¥¹ˆ°QÉÕ”¤…¹Íµ…ÉÑ}É•µ¥¹‘•É}½ÕÉÍ}½¸¡É•µ¥¹‘•È°Ñ½µ½ÉÉ½Ü¤è(€€€€€€€€€€€€€€€­•ä€ô˜‰íÑ½‘…å}­•åôéíÉ¥‘ôé•Ù”ˆ(€€€€€€€€€€€€€€€¥˜­•ä¥¸Í•¹Ñ}­•åÌè(€€€€€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€€€€€‘Õ•}É½ÕÁÌ¹Í•Ñ‘•™…Õ±Ğ  ‰•Ù”ˆ°€ˆÈÀèÀÀˆ°Ñ…É•Ñ}­¥¹°Ñ…É•Ñ}¥¤°mt¤¹…ÁÁ•¹ ¡­•ä°É•µ¥¹‘•È¤¤((€€€€€€€™½È€¡µ½‘”°Í±½Ğ°Ñ…É•Ñ}­¥¹°Ñ…É•Ñ}¥¤°•¹ÑÉ¥•Ì¥¸Í½ÉÑ•¡‘Õ•}É½ÕÁÌ¹¥Ñ•µÌ ¤¤è(€€€€€€€€€€€±¥µ¥Ğ€ô€È¥˜Ñ…É•Ñ}­¥¹€ôô€‰ÁÉ¥Ù…Ñ”ˆ•±Í”€Ä(€€€€€€€€€€€¥˜¥¹Ğ¡ÕÍ…”¹•Ğ¡Ñ…É•Ñ}­¥¹¤½È€À¤€øô±¥µ¥Ğè(€€€€€€€€€€€€€€€Í­¥ÁÁ•€¬ô±•¸¡•¹ÑÉ¥•Ì¤(€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€­•åÌ€ôm­•ä™½È­•ä°}É•µ¥¹‘•È¥¸•¹ÑÉ¥•Ít(€€€€€€€€€€€É•µ¥¹‘•ÉÌ€ômÉ•µ¥¹‘•È™½È}­•ä°É•µ¥¹‘•È¥¸•¹ÑÉ¥•Ít(€€€€€€€€€€€‘•±¥Ù•Éå}­•ä€ô˜‰Íµ…ÉÑ}É•µ¥¹‘•ÈéíÑ½‘…å}­•åôéíµ½‘•ôéíÍ±½ÑôéíÑ…É•Ñ}­¥¹‘ôéíÑ…É•Ñ}¥‘ôˆ(€€€€€€€€€€€¥˜¹½ĞÁÕÍ¡}…ÑÑ•µÁÑ}…±±½İ•¡ÕÍ•È°‘•±¥Ù•Éå}­•ä¤è(€€€€€€€€€€€€€€€Í­¥ÁÁ•€¬ô±•¸¡•¹ÑÉ¥•Ì¤(€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€µ•ÍÍ…”€ô‰Õ¥±‘}Íµ…ÉÑ}É•µ¥¹‘•É}‘¥•ÍĞ¡É•µ¥¹‘•ÉÌ°µ½‘”õµ½‘”¤(€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€É•ÍÕ±Ğ€ôÍ•¹‘•È¡Ñ½­•¸°Ñ…É•Ñ}¥°µ•ÍÍ…”¤(€€€€€€€€€€€€€€€}±•…É}ÁÕÍ¡}‘•±¥Ù•Éå}™…¥±ÕÉ”¡ÕÍ•È°‘•±¥Ù•Éå}­•ä¤(€€€€€€€€€€€€€€€Í•¹Ñ}­•åÌ¹ÕÁ‘…Ñ”¡­•åÌ¤(€€€€€€€€€€€€€€€ÕÍ…•mÑ…É•Ñ}­¥¹‘t€ô¥¹Ğ¡ÕÍ…”¹•Ğ¡Ñ…É•Ñ}­¥¹¤½È€À¤€¬€Ä(€€€€€€€€€€€€€€€¥˜Í¹½½é”¹•Ğ ‰¥ˆ¤¥¸íÈ¹•Ğ ‰¥ˆ¤™½ÈÈ¥¸É•µ¥¹‘•ÉÍôè(€€€€€€€€€€€€€€€€€€€ÕÍ•Él‰Íµ…ÉÑ}É•µ¥¹‘•É}Í¹½½é”‰t€ôíô(€€€€€€€€€€€€€€€…ÁÁ•¹‘}¹½Ñ¥™¥…Ñ¥½¹}±½œ (€€€€€€€€€€€€€€€€€€€ÍÑ…Ñ”°€‰Íµ…ÉÑ}É•µ¥¹‘•Èˆ°Ñ…É•Ñ}¥°€‰Í•¹Ğˆ°(€€€€€€€€€€€€€€€€€€€µ•ÍÍ…”¹•Ğ ‰…±ÑQ•áĞˆ¤°©Í½¸¹‘ÕµÁÌ¡É•ÍÕ±Ğ°•¹ÍÕÉ•}…Í¥¤õ…±Í”¤°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€É•½É‘}±¥¹•}µ•ÍÍ…•}ÕÍ…” (€€€€€€€€€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€€€€€€€€€…Ñ•½Éäô‰Íµ…ÉÑ}É•µ¥¹‘•Èˆ°(€€€€€€€€€€€€€€€€€€€½İ¹•É}±¥¹•}ÕÍ•É}¥õ±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€€€€€É•¥Á¥•¹Ñ}½Õ¹ĞôÄ°(€€€€€€€€€€€€€€€€€€€•Ù•¹Ñ}¥õ‘•±¥Ù•Éå}­•ä°(€€€€€€€€€€€€€€€€€€€Í•¹Ñ}…Ğõ¹½Ü°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€Í•¹Ğ€¬ô€Ä(€€€€€€€€€€€€€€€É•ÍÕ±ÑÌ¹…ÁÁ•¹¡ì(€€€€€€€€€€€€€€€€€€€€‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€€€€€€‰Ñ…É•ĞˆèÑ…É•Ñ}­¥¹°(€€€€€€€€€€€€€€€€€€€€‰É•¥Á¥•¹ĞˆèÑ…É•Ñ}¥°(€€€€€€€€€€€€€€€€€€€€‰¥‘ÌˆèmÈ¹•Ğ ‰¥ˆ¤™½ÈÈ¥¸É•µ¥¹‘•ÉÍt°(€€€€€€€€€€€€€€€€€€€€‰µ½‘”ˆèµ½‘”°(€€€€€€€€€€€€€€€€€€€€‰µ•É•‘}½Õ¹Ğˆè±•¸¡É•µ¥¹‘•ÉÌ¤°(€€€€€€€€€€€€€€€ô¤(€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€€€€€™…¥±ÕÉ”€ô}É•½É‘}Í¡•‘Õ±•‘}ÁÕÍ¡}™…¥±ÕÉ” (€€€€€€€€€€€€€€€€€€€ÍÑ…Ñ”°ÕÍ•È°‘•±¥Ù•Éå}­•ä°€‰Íµ…ÉÑ}É•µ¥¹‘•Èˆ°Ñ…É•Ñ}¥°(€€€€€€€€€€€€€€€€€€€µ•ÍÍ…”¹•Ğ ‰…±ÑQ•áĞˆ¤°•áŒ°¹½Ü°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€Í­¥ÁÁ•€¬ô±•¸¡•¹ÑÉ¥•Ì¤(€€€€€€€€€€€€€€€É•ÍÕ±ÑÌ¹…ÁÁ•¹¡ì‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°€‰¥‘ÌˆèmÈ¹•Ğ ‰¥ˆ¤™½ÈÈ¥¸É•µ¥¹‘•ÉÍt°€‰•ÉÉ½ÈˆèÍÑÈ¡•áŒ¥ô¤(€€€€€€€€€€€€€€€¥˜™…¥±ÕÉ•l‰­¥¹‰t€ôô€‰ÍåÍÑ•´ˆè(€€€€€€€€€€€€€€€€€€€ÍåÍÑ•µ}•ÉÉ½È€ôQÉÕ”(€€€€€€€€€€€€€€€€€€€‰É•…¬(€€€€€€€ÕÍ•Él‰Íµ…ÉÑ}É•µ¥¹‘•É}Í•¹Ñ}­•åÌ‰t€ôÍ½ÉÑ•¡Í•¹Ñ}­•åÌ¥l´ÄÈÀét(€€€€€€€¥˜ÍåÍÑ•µ}•ÉÉ½Èè(€€€€€€€€€€€‰É•…¬((€€€Í…Ù•}ÍÑ…Ñ”¡‘…Ñ…}™¥±”°ÍÑ…Ñ”¤(€€€É•ÑÕÉ¸ì(€€€€€€€€‰Í•¹ĞˆèÍ•¹Ğ°(€€€€€€€€‰Í­¥ÁÁ•ˆèÍ­¥ÁÁ•°(€€€€€€€€‰É•ÍÕ±ÑÌˆèÉ•ÍÕ±ÑÌ°(€€€€€€€€‰ÍåÍÑ•µ}•ÉÉ½ÈˆèÍåÍÑ•µ}•ÉÉ½È°(€€€ô°€ÈÀÀ(()‘•˜±•…¹ÕÁ}•áÁ¥É•‘}Í½Ì¡½¹™¥œ¤è(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡½¹™¥l‰Q}%1‰t¤(€€€É•µ½Ù•€ôÍ½Í}™±½Ü¹Í½Í}ÁÕÉ•}½±¡ÍÑ…Ñ”°­••Á}µ¥¹ÕÑ•ÌôØÀ¤¥˜Í½Í}™±½Ü•±Í”mt(€€€Í…Ù•}ÍÑ…Ñ”¡½¹™¥l‰Q}%1‰t°ÍÑ…Ñ”¤(€€€É•ÑÕÉ¸ì‰É•µ½Ù•ˆè±•¸¡É•µ½Ù•¥ô°€ÈÀÀ(()‘•˜Í•¹‘}ÁÉ½™¥±•}½µÁ±•Ñ¥½¹}É•µ¥¹‘•ÉÌ¡½¹™¥œ¤è(€€€€ˆˆ‰AÉ¥Ù…Ñ”°É•ÑÉå…‰±”É•µ¥¹‘•ÉÌ…Ğ‰¥¹°€¬ÈÑ °‘…ä€Ì°…¹‘…ä€Ü½¹±ä¸ˆˆˆ(€€€Ñ½­•¸€ô½¹™¥œ¹•Ğ ‰1%9}!991}MM}Q=-8ˆ¤½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}!991}MM}Q=-8ˆ°€ˆˆ¤(€€€¥˜¹½ĞÑ½­•¸è(€€€€€€€É•ÑÕÉ¸ì‰Í•¹Ğˆè€À°€‰Í­¥ÁÁ•ˆè€À°€‰•ÉÉ½Èˆè€‰1%9}!991}MM}Q=-8¥Ì¹½ĞÍ•Ğ‰ô°€ĞÀÀ(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡½¹™¥l‰Q}%1‰t¤(€€€Í•¹‘•È€ô½¹™¥œ¹•Ğ ‰1%9}AUM!}M9Hˆ¤½È±¥¹•}ÁÕÍ¡}µ•ÍÍ…”(€€€¹½Ü€ôÕÉÉ•¹Ñ}…ÁÁ}Ñ¥µ”¡½¹™¥œ¤(€€€Í•¹Ğ€ôÍ­¥ÁÁ•€ô€À(€€€É•ÍÕ±ÑÌ€ômt(€€€™½ÈÁÉ½™¥±”¥¸€¡ÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ¤½Èíô¤¹Ù…±Õ•Ì ¤è(€€€€€€€¥˜¹½Ğ¥Í¥¹ÍÑ…¹”¡ÁÉ½™¥±”°‘¥Ğ¤½È¹½ĞÁÉ½™¥±”¹•Ğ ‰ÁÉ½™¥±•}½µÁ±•Ñ¥½¹}É•ÅÕ¥É•ˆ¤è(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¥˜ÁÉ½™¥±”¹•Ğ ‰µ•µ‰•ÉÍ¡¥Á}Á…ÕÍ•ˆ¤½È¹½Ğµ•µ‰•ÉÍ¡¥Á}…•ÍÍ}…Ñ¥Ù”¡ÁÉ½™¥±”°¹½Ü¤è(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€½µÁ±•Ñ¥½¹}Á••È€ôÍÑÈ (€€€€€€€€€€€ÁÉ½™¥±”¹•Ğ ‰ÁÉ½™¥±•}½µÁ±•Ñ¥½¹}Á••É}±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ(€€€€€€€€¤¹ÍÑÉ¥À ¤(€€€€€€€½µÁ±•Ñ¥½¹}½¹Ñ…ÑÌ€ôl(€€€€€€€€€€€½¹Ñ…Ğ(€€€€€€€€€€€™½È½¹Ñ…Ğ¥¸€¡ÁÉ½™¥±”¹•Ğ ‰½¹Ñ…ÑÌˆ¤½Èmt¤(€€€€€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡½¹Ñ…Ğ°‘¥Ğ¤(€€€€€€€€€€€…¹É•Í½±Ù•}½¹Ñ…Ñ}É½±”¡½¹Ñ…Ğ¤€ôô€‰Õ…É‘¥…¸ˆ(€€€€€€€€€€€…¹€ (€€€€€€€€€€€€€€€¹½Ğ½µÁ±•Ñ¥½¹}Á••È(€€€€€€€€€€€€€€€½È•Ñ}½¹Ñ…Ñ}±¥¹•}¥¡½¹Ñ…Ğ¤€ôô½µÁ±•Ñ¥½¹}Á••È(€€€€€€€€€€€€¤(€€€€€€€t(€€€€€€€¥˜…¹ä¡½µÁ±•Ñ•}Õ…É‘¥…¹}½¹Ñ…Ğ¡½¹Ñ…Ğ¤™½È½¹Ñ…Ğ¥¸½µÁ±•Ñ¥½¹}½¹Ñ…ÑÌ¤è(€€€€€€€€€€€ÁÉ½™¥±•l‰ÁÉ½™¥±•}½µÁ±•Ñ¥½¹}É•ÅÕ¥É•‰t€ô…±Í”(€€€€€€€€€€€ÁÉ½™¥±•l‰ÁÉ½™¥±•}½µÁ±•Ñ¥½¹}½µÁ±•Ñ•‘}…Ğ‰t€ô¹½Ü¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€ÑÉäè(€€€€€€€€€€€‰½Õ¹‘}…Ğ€ô‘…Ñ•Ñ¥µ”¹™É½µ¥Í½™½Éµ…Ğ¡ÍÑÈ¡ÁÉ½™¥±”¹•Ğ ‰ÁÉ½™¥±•}½µÁ±•Ñ¥½¹}‰½Õ¹‘}…Ğˆ¤½È€ˆˆ¤¤(€€€€€€€•á•ÁĞY…±Õ•ÉÉ½Èè(€€€€€€€€€€€Í­¥ÁÁ•€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€•±…ÁÍ•‘}‘…åÌ€ôµ…à À°€¡¹½Ü¹‘…Ñ” ¤€´‰½Õ¹‘}…Ğ¹‘…Ñ” ¤¤¹‘…åÌ¤(€€€€€€€…±É•…‘ä€ôí¥¹Ğ¡‘…ä¤™½È‘…ä¥¸€¡ÁÉ½™¥±”¹•Ğ ‰ÁÉ½™¥±•}½µÁ±•Ñ¥½¹}É•µ¥¹‘•É}‘…åÌˆ¤½Èmt¥ô(€€€€€€€‘Õ”€ôm‘…ä™½È‘…ä¥¸AI=%1}=5A1Q%=9}I5%9I}eL¥˜‘…ä€ğô•±…ÁÍ•‘}‘…åÌ…¹‘…ä¹½Ğ¥¸…±É•…‘åt(€€€€€€€™½È‘…ä¥¸‘Õ”è(€€€€€€€€€€€µ•ÍÍ…”€ô€‹–ŞË–º3š"Cš‚ã–ş–º#¢¶ßÚ–ºk¢®/¢¢+3š¾?š^—–æÏ–º'7–º3š"C¢«–ŞÇj¢¿Ö‡¢ÎšZg¾òm1%9ƒ¦k~—–ŞË–>¿’öÿR£¾ò3¦nï¢¦Ç¢¿Ö‡šr–r£¢ÎšZg–º3š"C–ú3–VR£ˆ(€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€É•ÍÕ±Ğ€ôÍ•¹‘•È¡Ñ½­•¸°ÁÉ½™¥±”¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤°µ•ÍÍ…”¤(€€€€€€€€€€€€€€€…ÁÁ•¹‘}¹½Ñ¥™¥…Ñ¥½¹}±½œ¡ÍÑ…Ñ”°€‰ÁÉ½™¥±•}½µÁ±•Ñ¥½¸ˆ°ÁÉ½™¥±”¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤°€‰Í•¹Ğˆ°µ•ÍÍ…”°©Í½¸¹‘ÕµÁÌ¡É•ÍÕ±Ğ°•¹ÍÕÉ•}…Í¥¤õ…±Í”¤¤(€€€€€€€€€€€€€€€…±É•…‘ä¹…‘¡‘…ä¤(€€€€€€€€€€€€€€€Í•¹Ğ€¬ô€Ä(€€€€€€€€€€€€€€€É•ÍÕ±ÑÌ¹…ÁÁ•¹¡ì‰±¥¹•}ÕÍ•É}¥ˆèÁÉ½™¥±”¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤°€‰‘…äˆè‘…ä°€‰ÍÑ…ÑÕÌˆè€‰Í•¹Ğ‰ô¤(€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€€€€€…ÁÁ•¹‘}¹½Ñ¥™¥…Ñ¥½¹}±½œ¡ÍÑ…Ñ”°€‰ÁÉ½™¥±•}½µÁ±•Ñ¥½¸ˆ°ÁÉ½™¥±”¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤°€‰™…¥±•ˆ°µ•ÍÍ…”°ÍÑÈ¡•áŒ¥lèĞÀÁt¤(€€€€€€€€€€€€€€€É•ÍÕ±ÑÌ¹…ÁÁ•¹¡ì‰±¥¹•}ÕÍ•É}¥ˆèÁÉ½™¥±”¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤°€‰‘…äˆè‘…ä°€‰ÍÑ…ÑÕÌˆè€‰™…¥±•‰ô¤(€€€€€€€ÁÉ½™¥±•l‰ÁÉ½™¥±•}½µÁ±•Ñ¥½¹}É•µ¥¹‘•É}‘…åÌ‰t€ôÍ½ÉÑ•¡…±É•…‘ä¤(€€€Í…Ù•}ÍÑ…Ñ”¡½¹™¥l‰Q}%1‰t°ÍÑ…Ñ”¤(€€€É•ÑÕÉ¸ì‰Í•¹ĞˆèÍ•¹Ğ°€‰Í­¥ÁÁ•ˆèÍ­¥ÁÁ•°€‰É•ÍÕ±ÑÌˆèÉ•ÍÕ±ÑÍô°€ÈÀÀ(()‘•˜ÉÕ¹}É½¹}Ñ¥¬¡½¹™¥œ¤è(€€€¹½Ü€ôÕÉÉ•¹Ñ}…ÁÁ}Ñ¥µ”¡½¹™¥œ¤(€€€É•ÍÕ±ÑÌ€ôíô(€€€Í±½Ğ€ô¹½Ü¹ÍÑÉ™Ñ¥µ” ˆ• è•4ˆ¤((€€€µ¥É…Ñ¥½¹}‘…Ñ„°µ¥É…Ñ¥½¹}½‘”€ôµ¥É…Ñ•}•á¥ÍÑ¥¹}™É••}µ•µ‰•ÉÌ¡½¹™¥œ¤(€€€É•ÍÕ±ÑÍl‰µ•µ‰•ÉÍ¡¥Á}ÑÉ…¹Í¥Ñ¥½¹}µ¥É…Ñ¥½¸‰t€ôì(€€€€€€€€‰ÍÑ…ÑÕÌˆèµ¥É…Ñ¥½¹}½‘”°(€€€€€€€€‰É•ÍÕ±Ğˆèµ¥É…Ñ¥½¹}‘…Ñ„°(€€€ô(€€€€Œƒš¾?š²„É½¸ƒ¦÷–#¢s¦–"Ãšr¦3¢/ŠG¾ò3–7–~ß¢†3–"Ãšr¦f7Òk¾òm±…¥´½½ÕÑ‰½àƒšr¦bË¦7(€€€µ¥±•ÍÑ½¹•}‘…Ñ„°µ¥±•ÍÑ½¹•}½‘”€ôÍ•¹‘}ÑÉ¥…±}µ¥±•ÍÑ½¹•}¹½Ñ¥•Ì¡½¹™¥œ¤(€€€É•ÍÕ±ÑÍl‰ÑÉ¥…±}µ¥±•ÍÑ½¹•}¹½Ñ¥•Ì‰t€ôì(€€€€€€€€‰ÍÑ…ÑÕÌˆèµ¥±•ÍÑ½¹•}½‘”°(€€€€€€€€‰É•ÍÕ±Ğˆèµ¥±•ÍÑ½¹•}‘…Ñ„°(€€€ô(€€€•áÁ¥Éå}‘…Ñ„°•áÁ¥Éå}½‘”€ô…ÁÁ±å}•áÁ¥É•‘}Á±…¹}‘½İ¹É…‘•Ì¡½¹™¥œ¤(€€€É•ÍÕ±ÑÍl‰µ•µ‰•ÉÍ¡¥Á}•áÁ¥Éä‰t€ôì(€€€€€€€€‰ÍÑ…ÑÕÌˆè•áÁ¥Éå}½‘”°(€€€€€€€€‰É•ÍÕ±Ğˆè•áÁ¥Éå}‘…Ñ„°(€€€ô((€€€…±İ…åÌ€ôì(€€€€€€€€‰¡•­¥¹}É•µ¥¹‘•ÉÌˆèÍ•¹‘}¡•­¥¹}É•µ¥¹‘•ÉÌ°(€€€€€€€€‰‰¥¹‘¥¹}¹½Ñ¥™¥…Ñ¥½¹}É•ÑÉ¥•ÌˆèÉ•ÑÉå}Á•¹‘¥¹}‰¥¹‘}¹½Ñ¥™¥…Ñ¥½¹Ì°(€€€€€€€€‰ÁÉ½™¥±•}½µÁ±•Ñ¥½¹}É•µ¥¹‘•ÉÌˆèÍ•¹‘}ÁÉ½™¥±•}½µÁ±•Ñ¥½¹}É•µ¥¹‘•ÉÌ°(€€€€€€€€‰½Ù•É‘Õ•}…±•ÉÑÌˆèÍ•¹‘}‘Õ•}É•µ¥¹‘•ÉÌ°(€€€€€€€€‰Õ…É‘¥…¹}É½ÕÁ}‘…¥±å}ÍÕµµ…É¥•ÌˆèÍ•¹‘}Õ…É‘¥…¹}É½ÕÁ}‘…¥±å}ÍÕµµ…É¥•Ì°(€€€€€€€€‰Íµ…ÉÑ}É•µ¥¹‘•ÉÌˆèÍ•¹‘}Íµ…ÉÑ}É•µ¥¹‘•ÉÌ°(€€€€€€€€‰Í½Í}•Í…±…Ñ¥½¹Ìˆè±…µ‰‘„™œè€ (€€€€€€€€€€€ÁÉ½•ÍÍ}Í½Í}•Í…±…Ñ¥½¹Ì¡™l‰Q}%1‰t°™œ°¹½Üõ¹½Ü¤°(€€€€€€€€€€€€ÈÀÀ°(€€€€€€€€¤°(€€€€€€€€‰Í½Í}±•…¹ÕÀˆè±•…¹ÕÁ}•áÁ¥É•‘}Í½Ì°(€€€ô(€€€™½È¹…µ”°Ñ…Í¬¥¸…±İ…åÌ¹¥Ñ•µÌ ¤è(€€€€€€€‘…Ñ„°½‘”€ôÑ…Í¬¡½¹™¥œ¤(€€€€€€€É•ÍÕ±ÑÍm¹…µ•t€ôì‰ÍÑ…ÑÕÌˆè½‘”°€‰É•ÍÕ±Ğˆè‘…Ñ…ô(€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡‘…Ñ„°‘¥Ğ¤…¹‘…Ñ„¹•Ğ ‰ÍåÍÑ•µ}•ÉÉ½Èˆ¤è(€€€€€€€€€€€É•ÑÕÉ¸ì(€€€€€€€€€€€€€€€€‰½¬ˆè…±Í”°(€€€€€€€€€€€€€€€€‰ÍåÍÑ•µ}•ÉÉ½ÈˆèQÉÕ”°(€€€€€€€€€€€€€€€€‰É…¹}…Ğˆè¹½Ü¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤°(€€€€€€€€€€€€€€€€‰Ñ¥µ•é½¹”ˆè€‰Í¥„½Q…¥Á•¤ˆ°(€€€€€€€€€€€€€€€€‰Ñ…Í­ÌˆèÉ•ÍÕ±ÑÌ°(€€€€€€€€€€€ô°€ÈÀÀ((€€€Ñ½­•¸€ô½¹™¥œ¹•Ğ ‰1%9}!991}MM}Q=-8ˆ°€ˆˆ¤(€€€É•ÍÕ±ÑÍl‰Õ…É‘¥…¹}É½ÕÁ}É•™É•Í ‰t€ôÉ•™É•Í¡}…±±}Õ…É‘¥…¹}É½ÕÁÍ}½Õ¹Ğ (€€€€€€€½¹™¥l‰Q}%1‰t°(€€€€€€€Ñ½­•¸õÑ½­•¸°(€€€€¤((€€€‘…¥±ä€ôì(€€€€€€€€ˆÀäèÀÀˆè€ ‰‰¥ÉÑ¡‘…å}É•µ¥¹‘•ÉÌˆ°Í•¹‘}‰¥ÉÑ¡‘…å}É•µ¥¹‘•ÉÌ¤°(€€€€€€€€ˆÀäèÀÔˆè€ ‰½¹Ñ…Ñ}É•µ¥¹‘•ÉÌˆ°Í•¹‘}µ¥ÍÍ¥¹}½¹Ñ…Ñ}É•µ¥¹‘•ÉÌ¤°(€€€€€€€€ˆÄÀèÀÀˆè€ ‰É•¹•İ…±}É•µ¥¹‘•ÉÌˆ°Í•¹‘}É•¹•İ…±}É•µ¥¹‘•ÉÌ¤°(€€€€€€€€ˆÄäèÀÀˆè€ ‰‰•Ñ…}‘…¥±å}™••‘‰…¬ˆ°Í•¹‘}‰•Ñ…}‘…¥±å}™••‘‰…¬¤°(€€€€€€€€ˆÀÈèÌÀˆè€ ‰‘…Ñ…}±•…¹ÕÀˆ°±•…¹ÕÁ}•áÁ¥É•‘}‘…Ñ„¤°(€€€ô(€€€¥˜Í±½Ğ¥¸‘…¥±äè(€€€€€€€¹…µ”°Ñ…Í¬€ô‘…¥±åmÍ±½Ñt(€€€€€€€‘…Ñ„°½‘”€ôÑ…Í¬¡½¹™¥œ¤(€€€€€€€É•ÍÕ±ÑÍm¹…µ•t€ôì‰ÍÑ…ÑÕÌˆè½‘”°€‰É•ÍÕ±Ğˆè‘…Ñ…ô(€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡‘…Ñ„°‘¥Ğ¤…¹‘…Ñ„¹•Ğ ‰ÍåÍÑ•µ}•ÉÉ½Èˆ¤è(€€€€€€€€€€€É•ÑÕÉ¸ì(€€€€€€€€€€€€€€€€‰½¬ˆè…±Í”°(€€€€€€€€€€€€€€€€‰ÍåÍÑ•µ}•ÉÉ½ÈˆèQÉÕ”°(€€€€€€€€€€€€€€€€‰É…¹}…Ğˆè¹½Ü¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤°(€€€€€€€€€€€€€€€€‰Ñ¥µ•é½¹”ˆè€‰Í¥„½Q…¥Á•¤ˆ°(€€€€€€€€€€€€€€€€‰Ñ…Í­ÌˆèÉ•ÍÕ±ÑÌ°(€€€€€€€€€€€ô°€ÈÀÀ((€€€É•ÑÕÉ¸ì(€€€€€€€€‰½¬ˆè…±° (€€€€€€€€€€€¥Ñ•´¹•Ğ ‰ÍÑ…ÑÕÌˆ°€ÈÀÀ¤€ğ€ÔÀÀ(€€€€€€€€€€€™½È¥Ñ•´¥¸É•ÍÕ±ÑÌ¹Ù…±Õ•Ì ¤(€€€€€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡¥Ñ•´°‘¥Ğ¤(€€€€€€€€¤°(€€€€€€€€‰ÍåÍÑ•µ}•ÉÉ½Èˆè…±Í”°(€€€€€€€€‰É…¹}…Ğˆè¹½Ü¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤°(€€€€€€€€‰Ñ¥µ•é½¹”ˆè€‰Í¥„½Q…¥Á•¤ˆ°(€€€€€€€€‰Ñ…Í­ÌˆèÉ•ÍÕ±ÑÌ°(€€€ô°€ÈÀÀ(()‘•˜…ÁÁ}½¹™¥œ¡½¹™¥œ¤è(€€€Ñ½­•¸€ô€ (€€€€€€€½¹™¥œ¹•Ğ ‰1%9}!991}MM}Q=-8ˆ¤(€€€€€€€½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}!991}MM}Q=-8ˆ¤(€€€€€€€½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰!991}MM}Q=-8ˆ¤(€€€€€€€½È€ˆˆ(€€€€¤¹ÍÑÉ¥À ¤(€€€Í•É•Ğ€ô€ (€€€€€€€½¹™¥œ¹•Ğ ‰1%9}!991}MIPˆ¤(€€€€€€€½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}!991}MIPˆ¤(€€€€€€€½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰!991}MIPˆ¤(€€€€€€€½È€ˆˆ(€€€€¤¹ÍÑÉ¥À ¤(€€€É•ÑÕÉ¸ì(€€€€€€€€‰±¥™™}¥ˆè½¹™¥œ¹•Ğ ‰1%}%ˆ¤½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%}%ˆ¤½ÈU1Q}1%}%°(€€€€€€€€‰±•…å}±¥™™}¥ˆè€ (€€€€€€€€€€€½¹™¥œ¹•Ğ ‰1e}1%}%ˆ¤(€€€€€€€€€€€½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰1e}1%}%ˆ¤(€€€€€€€€€€€½ÈU1Q}1e}1%}%(€€€€€€€€¤°(€€€€€€€€‰ÁÕ‰±¥}ÕÉ°ˆè½¹™¥œ¹•Ğ ‰AA}AU	1%}UI0ˆ¤½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰AA}AU	1%}UI0ˆ°€ˆˆ¤°(€€€€€€€€ŒY¥Í¥‰±”‘•Á±½äÍÑ…µÀ™½ÈÙ•É¥™å¥¹œI•¹‘•È…ÑÕ…±±äÉ½±±•Ñ¡”İ•±½µ”±•à¸(€€€€€€€€‰‘•Á±½å}Ù•ÉÍ¥½¸ˆè½Ì¹•¹Ù¥É½¸¹•Ğ ‰A1=e}YIM%=8ˆ¤½È€‰\ÈÔÀÜÈÕ ˆ°(€€€€€€€€Œ	½Ñ Ñ½­•¸…¹Í•É•Ğ…É”É•ÅÕ¥É•™½È1%9İ•‰¡½½¬€¼µ•ÍÍ…¥¹œ¸(€€€€€€€€‰±¥¹•}•¹…‰±•ˆè‰½½°¡Ñ½­•¸…¹Í•É•Ğ¤°(€€€€€€€€‰É•ÅÕ¥É•}±¥™™}…ÕÑ ˆèÍÑÈ (€€€€€€€€€€€½¹™¥œ¹•Ğ ‰IEU%I}1%}UQ ˆ¤(€€€€€€€€€€€¥˜½¹™¥œ¹•Ğ ‰IEU%I}1%}UQ ˆ¤¥Ì¹½Ğ9½¹”(€€€€€€€€€€€•±Í”½Ì¹•¹Ù¥É½¸¹•Ğ ‰IEU%I}1%}UQ ˆ°€ˆÀˆ¤(€€€€€€€€¤¹ÍÑÉ¥À ¤¹±½İ•È ¤(€€€€€€€¥¸ìˆÄˆ°€‰ÑÉÕ”ˆ°€‰å•Ìˆ°€‰½¸‰ô°(€€€€€€€€‰•Á…å}É•…‘äˆè‰½½°¡•Á…ä…¹•Á…ä¹•Á…å}½¹™¥ÕÉ•¡½¹™¥œ¤¤°(€€€€€€€€‰¹•İ•‰Á…å}É•…‘äˆè‰½½°¡¹•İ•‰Á…ä…¹¹•İ•‰Á…ä¹¹•İ•‰Á…å}½¹™¥ÕÉ•¡½¹™¥œ¤¤°(€€€€€€€€‰ÍµÍ}±¥Ù”ˆè‰½½° (€€€€€€€€€€€€¡½¹™¥œ¹•Ğ ‰M5M-%9}UMI95ˆ¤½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰M5M-%9}UMI95ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€€€€€…¹€¡½¹™¥œ¹•Ğ ‰M5M-%9}AMM]=Iˆ¤½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰M5M-%9}AMM]=Iˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€€¤°(€€€ô(()‘•˜…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…õ9½¹”°€¨°…ÉÌõ9½¹”°¡•…‘•ÉÌõ9½¹”°½¹™¥œõ9½¹”¤è(€€€€ˆˆ‰I•Í½±Ù”½¹”…±±•È¥‘•¹Ñ¥Ñäì¹•Ù•ÈÑÉÕÍĞ„É½ÕÑ”ÌÉ•ÅÕ•ÍÑ•µ•µ‰•È%¸ˆˆˆ(€€€Á…å±½…€ôÁ…å±½…½Èíô(€€€…ÉÌ€ô…ÉÌ½Èíô(€€€¡•…‘•ÉÌ€ô¡•…‘•ÉÌ½Èíô(€€€¥˜É•Í½±Ù•}±¥¹•}ÕÍ•É}¥¥Ì9½¹”è(€€€€€€€±…¥µ•€ôÍÑÈ¡Á…å±½…¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤½È…ÉÌ¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€¥˜¹½Ğ±…¥µ•è(€€€€€€€€€€€É•ÑÕÉ¸9½¹”°€¡ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰µ¥ÍÍ¥¹œ±¥¹•}ÕÍ•É}¥‰ô°€ĞÀÀ¤(€€€€€€€É•ÑÕÉ¸±…¥µ•°9½¹”(€€€É•ÑÕÉ¸É•Í½±Ù•}±¥¹•}ÕÍ•É}¥ (€€€€€€€¡•…‘•ÉÌõ¡•…‘•ÉÌ°(€€€€€€€Á…å±½…õÁ…å±½…°(€€€€€€€…ÉÌõ…ÉÌ°(€€€€€€€½¹™¥œõ½¹™¥œ½Èíô°(€€€€¤(()‘•˜ÕÁ‘…Ñ•}½¹‰½…É‘¥¹}É•µ¥¹‘•È¡‘…Ñ…}™¥±”°±¥¹•}ÕÍ•É}¥°Á…å±½…¤è(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€ÁÉ½™¥±”€ô•Ñ}ÁÉ½™¥±”¡ÍÑ…Ñ”°±¥¹•}ÕÍ•É}¥¤(€€€µ…á}½Õ¹Ğ€ô¥¹Ğ¡Á±…¹}ÉÕ±•Ì¡ÁÉ½™¥±”¤¹•Ğ ‰‘…¥±å}É•µ¥¹‘•ÉÌˆ¤½È€Ä¤(€€€¥˜€‰É•µ¥¹‘•É}Ñ¥µ•Ìˆ¥¸Á…å±½…è(€€€€€€€É…Ü€ôÁ…å±½…¹•Ğ ‰É•µ¥¹‘•É}Ñ¥µ•Ìˆ¤(€€€€€€€¥˜¹½Ğ¥Í¥¹ÍÑ…¹”¡É…Ü°±¥ÍĞ¤½È¹½ĞÉ…Üè(€€€€€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰É•µ¥¹‘•É}Ñ¥µ•ÌµÕÍĞ‰”„¹½¸µ•µÁÑä±¥ÍĞ‰ô°€ĞÀÀ(€€€€€€€¹½Éµ…±¥é•€ô¹½Éµ…±¥é•}É•µ¥¹‘•É}Ñ¥µ•Ì¡É…Ü°µ…á}½Õ¹Ğ¤(€€€€€€€¥˜¹½Ğ¹½Éµ…±¥é•è(€€€€€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰¥¹Ù…±¥É•µ¥¹‘•É}Ñ¥µ•Ì™½Éµ…Ğ°ÕÍ”! é54‰ô°€ĞÀÀ(€€€€€€€Ñ¥µ•Ì€ô…ÁÁ±å}É•µ¥¹‘•É}Ñ¥µ•Í}Ñ½}ÁÉ½™¥±”¡ÁÉ½™¥±”°Ñ¥µ•Ìõ¹½Éµ…±¥é•¤(€€€•±Í”è(€€€€€€€É•µ¥¹‘•É}Ñ¥µ”€ô€¡Á…å±½…¹•Ğ ‰É•µ¥¹‘•É}Ñ¥µ”ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€¥˜¹½ĞI5%9I}Q%5}AQQI8¹µ…Ñ ¡É•µ¥¹‘•É}Ñ¥µ”¤è(€€€€€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰¥¹Ù…±¥É•µ¥¹‘•É}Ñ¥µ”™½Éµ…Ğ°ÕÍ”! é54‰ô°€ĞÀÀ(€€€€€€€Ñ¥µ•Ì€ô…ÁÁ±å}É•µ¥¹‘•É}Ñ¥µ•Í}Ñ½}ÁÉ½™¥±”¡ÁÉ½™¥±”°Í¥¹±”õÉ•µ¥¹‘•É}Ñ¥µ”¤(€€€¥˜€‰‘…¥±å}¡•­¥¹}É•µ¥¹‘•É}•¹…‰±•ˆ¥¸Á…å±½…è(€€€€€€€ÁÉ½™¥±•l‰‘…¥±å}¡•­¥¹}É•µ¥¹‘•É}•¹…‰±•‰t€ô‰½½° (€€€€€€€€€€€Á…å±½…¹•Ğ ‰‘…¥±å}¡•­¥¹}É•µ¥¹‘•É}•¹…‰±•ˆ¤(€€€€€€€€¤(€€€¥˜€‰É…•}¡½ÕÉÌˆ¥¸Á…å±½…è(€€€€€€€ÁÉ½™¥±•l‰É…•}¡½ÕÉÌ‰t€ô¹½Éµ…±¥é•}É…•}¡½ÕÉÌ¡Á…å±½…¹•Ğ ‰É…•}¡½ÕÉÌˆ¤¤(€€€•±Í”è(€€€€€€€ÁÉ½™¥±•l‰É…•}¡½ÕÉÌ‰t€ô¹½Éµ…±¥é•}É…•}¡½ÕÉÌ¡ÁÉ½™¥±”¹•Ğ ‰É…•}¡½ÕÉÌˆ¤¤(€€€¥˜€‰½Ù•É‘Õ•}İ…¥Ñ}µ¥¹ÕÑ•Ìˆ¥¸Á…å±½…è(€€€€€€€ÁÉ½™¥±•l‰½Ù•É‘Õ•}İ…¥Ñ}µ¥¹ÕÑ•Ì‰t€ô¹½Éµ…±¥é•}½Ù•É‘Õ•}İ…¥Ñ}µ¥¹ÕÑ•Ì (€€€€€€€€€€€Á…å±½…¹•Ğ ‰½Ù•É‘Õ•}İ…¥Ñ}µ¥¹ÕÑ•Ìˆ¤(€€€€€€€€¤(€€€•±Í”è(€€€€€€€ÁÉ½™¥±•l‰½Ù•É‘Õ•}İ…¥Ñ}µ¥¹ÕÑ•Ì‰t€ô¹½Éµ…±¥é•}½Ù•É‘Õ•}İ…¥Ñ}µ¥¹ÕÑ•Ì (€€€€€€€€€€€ÁÉ½™¥±”¹•Ğ ‰½Ù•É‘Õ•}İ…¥Ñ}µ¥¹ÕÑ•Ìˆ¤(€€€€€€€€¤(€€€ÁÉ½™¥±•l‰½¹‰½…É‘¥¹}É•µ¥¹‘•É}½¹™¥ÕÉ•‰t€ôQÉÕ”(€€€Í…Ù•}ÍÑ…Ñ”¡‘…Ñ…}™¥±”°ÍÑ…Ñ”¤(€€€É•ÑÕÉ¸ì(€€€€€€€€‰½¬ˆèQÉÕ”°(€€€€€€€€‰É•µ¥¹‘•É}Ñ¥µ”ˆèÑ¥µ•ÍlÁt°(€€€€€€€€‰É•µ¥¹‘•É}Ñ¥µ•ÌˆèÑ¥µ•Ì°(€€€€€€€€‰‘…¥±å}É•µ¥¹‘•ÉÌˆèµ…á}½Õ¹Ğ°(€€€€€€€€‰½¹‰½…É‘¥¹}É•µ¥¹‘•É}½¹™¥ÕÉ•ˆèQÉÕ”°(€€€€€€€€‰‘…¥±å}¡•­¥¹}É•µ¥¹‘•É}•¹…‰±•ˆè‰½½° (€€€€€€€€€€€ÁÉ½™¥±”¹•Ğ ‰‘…¥±å}¡•­¥¹}É•µ¥¹‘•É}•¹…‰±•ˆ°QÉÕ”¤(€€€€€€€€¤°(€€€€€€€€‰É…•}¡½ÕÉÌˆè¹½Éµ…±¥é•}É…•}¡½ÕÉÌ¡ÁÉ½™¥±”¹•Ğ ‰É…•}¡½ÕÉÌˆ¤¤°(€€€€€€€€‰½Ù•É‘Õ•}İ…¥Ñ}µ¥¹ÕÑ•Ìˆè¹½Éµ…±¥é•}½Ù•É‘Õ•}İ…¥Ñ}µ¥¹ÕÑ•Ì (€€€€€€€€€€€ÁÉ½™¥±”¹•Ğ ‰½Ù•É‘Õ•}İ…¥Ñ}µ¥¹ÕÑ•Ìˆ¤(€€€€€€€€¤°(€€€€€€€€‰…±±½İ•‘}½Ù•É‘Õ•}İ…¥Ñ}µ¥¹ÕÑ•Ìˆè±¥ÍĞ¡11=]}=YIU}]%Q}5%9UQL¤°(€€€€€€€€‰İ…É¹¥¹}…¹•±}µ¥¹ÕÑ•Ìˆè¥¹Ğ (€€€€€€€€€€€ÁÉ½™¥±”¹•Ğ ‰İ…É¹¥¹}…¹•±}µ¥¹ÕÑ•Ìˆ¤½ÈU1Q}]I9%9}91}5%9UQL(€€€€€€€€¤°(€€€€€€€€‰…±±½İ•‘}É…•}¡½ÕÉÌˆè±¥ÍĞ¡11=]}I}!=UIL¤°(€€€ô°€ÈÀÀ(()‘•˜½µÁ±•Ñ•}½¹‰½…É‘¥¹}™½É}ÕÍ•È¡‘…Ñ…}™¥±”°±¥¹•}ÕÍ•É}¥°Á…å±½…¤è(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€ÁÉ½™¥±”€ôÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ°íô¤¹•Ğ¡±¥¹•}ÕÍ•É}¥¤(€€€¥˜¹½ĞÁÉ½™¥±”è(€€€€€€€É•ÑÕÉ¸ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰ÕÍ•È¹½ĞÉ•¥ÍÑ•É•‰ô°€ĞÀĞ(€€€…•ÍÌ€ôµ•µ‰•É}…•ÍÍ}ÍÑ…Ñ”¡ÁÉ½™¥±”¤(€€€¥˜…•ÍÍl‰Õ…É‘¥…¹}É•ÅÕ¥É•‰tè(€€€€€€€É•ÑÕÉ¸ì(€€€€€€€€€€€€‰½¬ˆè…±Í”°(€€€€€€€€€€€€‰•ÉÉ½Èˆè€‰Õ…É‘¥…¹}É•ÅÕ¥É•ˆ°(€€€€€€€€€€€€‰µ•ÍÍ…”ˆè€‹–ş¦‚#–#–º3š"C¢Ï–ÂD€Äƒ’ö7–>¿š:—šRØ1%9ƒ¦k~—jš‚ã–ş–º#¢¶ß’êëÚ–ºhˆ°(€€€€€€€€€€€€¨©…•ÍÌ°(€€€€€€€ô°€ĞÀÀ(€€€ÁÉ½™¥±•l‰¥Í}½¹‰½…É‘¥¹}½µÁ±•Ñ•‰t€ôQÉÕ”(€€€¥˜€‰É•µ¥¹‘•É}Ñ¥µ•Ìˆ¥¸Á…å±½…½ÈÁ…å±½…¹•Ğ ‰É•µ¥¹‘•É}Ñ¥µ”ˆ¤è(€€€€€€€…ÁÁ±å}É•µ¥¹‘•É}Ñ¥µ•Í}Ñ½}ÁÉ½™¥±” (€€€€€€€€€€€ÁÉ½™¥±”°(€€€€€€€€€€€Ñ¥µ•ÌõÁ…å±½…¹•Ğ ‰É•µ¥¹‘•É}Ñ¥µ•Ìˆ¤°(€€€€€€€€€€€Í¥¹±”õÁ…å±½…¹•Ğ ‰É•µ¥¹‘•É}Ñ¥µ”ˆ¤°(€€€€€€€€¤(€€€•±Í”è(€€€€€€€…ÁÁ±å}É•µ¥¹‘•É}Ñ¥µ•Í}Ñ½}ÁÉ½™¥±”¡ÁÉ½™¥±”¤(€€€¥ÍÑ…Ñ”€ô•Ñ}½É}É•…Ñ•}¥¹Ñ•É…Ñ¥½¹}ÍÑ…Ñ”¡ÁÉ½™¥±”¤(€€€¥ÍÑ…Ñ•l‰½¹‰½…É‘¥¹}½µÁ±•Ñ•‰t€ôQÉÕ”(€€€¥˜€‰…‘‘}™¥ÉÍÑ}Õ…É‘¥…¸ˆ¹½Ğ¥¸¥ÍÑ…Ñ•l‰½µÁ±•Ñ•‘}ÍÑ•ÁÌ‰tè(€€€€€€€¥ÍÑ…Ñ•l‰½µÁ±•Ñ•‘}ÍÑ•ÁÌ‰t¹…ÁÁ•¹ ‰…‘‘}™¥ÉÍÑ}Õ…É‘¥…¸ˆ¤(€€€¥˜€‰Í•Ñ}É•µ¥¹‘•É}Ñ¥µ”ˆ¹½Ğ¥¸¥ÍÑ…Ñ•l‰½µÁ±•Ñ•‘}ÍÑ•ÁÌ‰tè(€€€€€€€¥ÍÑ…Ñ•l‰½µÁ±•Ñ•‘}ÍÑ•ÁÌ‰t¹…ÁÁ•¹ ‰Í•Ñ}É•µ¥¹‘•É}Ñ¥µ”ˆ¤(€€€¥˜¹½Ğ¥ÍÑ…Ñ”¹•Ğ ‰Á•¹‘¥¹}ÍÑ•ÁÌˆ¤è(€€€€€€€¥ÍÑ…Ñ•l‰Á•¹‘¥¹}ÍÑ•ÁÌ‰t€ôl(€€€€€€€€€€€€‰•áÁ±½É•}…ÁÀˆ°(€€€€€€€€€€€€‰É•…‘}¡•±Àˆ°(€€€€€€€€€€€€‰…‘‘}µ½É•}Õ…É‘¥…¹Í}¥™}Á…¥ˆ°(€€€€€€€t(€€€¥ÍÑ…Ñ•l‰±…ÍÑ}¥¹Ñ•É…Ñ¥½¹}…Ğ‰t€ô‘…Ñ•Ñ¥µ”¹¹½Ü ¤¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤(€€€Í…Ù•}ÍÑ…Ñ”¡‘…Ñ…}™¥±”°ÍÑ…Ñ”¤(€€€Ñ¥µ•Ì€ôÉ•µ¥¹‘•É}Ñ¥µ•Í}™½É}ÁÉ½™¥±”¡ÁÉ½™¥±”¤(€€€É•ÑÕÉ¸ì(€€€€€€€€‰½¬ˆèQÉÕ”°(€€€€€€€€¨©µ•µ‰•É}…•ÍÍ}ÍÑ…Ñ”¡ÁÉ½™¥±”¤°(€€€€€€€€‰¥Í}½¹‰½…É‘¥¹}½µÁ±•Ñ•ˆèQÉÕ”°(€€€€€€€€‰Í•ÑÕÁ}½µÁ±•Ñ•ˆèQÉÕ”°(€€€€€€€€‰É•µ¥¹‘•É}Ñ¥µ”ˆèÑ¥µ•ÍlÁt°(€€€€€€€€‰É•µ¥¹‘•É}Ñ¥µ•ÌˆèÑ¥µ•Ì°(€€€€€€€€‰¥¹Ñ•É…Ñ¥½¹}ÍÑ…Ñ”ˆè¥ÍÑ…Ñ”°(€€€ô°€ÈÀÀ(()‘•˜¡•­¥¹}™½É}ÕÍ•È¡‘…Ñ…}™¥±”°±¥¹•}ÕÍ•É}¥°Á…å±½…°½¹™¥œõ9½¹”¤è(€€€Á…å±½…€ô‘¥Ğ¡Á…å±½…½Èíô¤(€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€¹½Ü€ôÕÉÉ•¹Ñ}…ÁÁ}Ñ¥µ”¡½¹™¥œ½Èíô¤(€€€•Ù•¹Ñ}¥€ô˜‰¡•­¥¸éí±¥¹•}ÕÍ•É}¥‘ôéíÕÕ¥¹ÕÕ¥Ğ ¤¹¡•áôˆ(€€€µÕÑ…Ñ•}ÍÑ…Ñ•}…Ñ½µ¥…±±ä (€€€€€€€‘…Ñ…}™¥±”°(€€€€€€€±…µ‰‘„ÕÉÉ•¹Ñ}ÍÑ…Ñ”èÕÉÉ•¹Ñ}ÍÑ…Ñ”¹Í•Ñ‘•™…Õ±Ğ (€€€€€€€€€€€€‰±…Õ¹¡}•Ù•¹ÑÌˆ°mt(€€€€€€€€¤¹…ÁÁ•¹¡ì(€€€€€€€€€€€€‰¥ˆè•Ù•¹Ñ}¥°(€€€€€€€€€€€€‰­¥¹ˆè€‰¡•­¥¸ˆ°(€€€€€€€€€€€€‰ÍÕ•ÍÌˆè…±Í”°(€€€€€€€€€€€€‰…Ğˆè¹½Ü¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤°(€€€€€€€ô¤°(€€€€¤(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€¥˜±¥¹•}ÕÍ•É}¥¹½Ğ¥¸ÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ°íô¤è(€€€€€€€É•¥ÍÑ•É}±¥¹•}ÕÍ•È (€€€€€€€€€€€‘…Ñ…}™¥±”°(€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€€‰‘¥ÍÁ±…å}¹…µ”ˆèÍÑÈ¡Á…å±½…¹•Ğ ‰‘¥ÍÁ±…å}¹…µ”ˆ¤½È€‰1%9ƒ’öÿR£¢ˆ¤°(€€€€€€€€€€€ô°(€€€€€€€€¤(€€€€€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€…•ÍÌ€ôµ•µ‰•É}…•ÍÍ}ÍÑ…Ñ”¡ÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ°íô¤¹•Ğ¡±¥¹•}ÕÍ•É}¥¤¤(€€€¥˜…•ÍÍl‰Õ…É‘¥…¹}É•ÅÕ¥É•‰tè(€€€€€€€É•ÑÕÉ¸ì(€€€€€€€€€€€€‰½¬ˆè…±Í”°(€€€€€€€€€€€€‰•ÉÉ½Èˆè€‰Õ…É‘¥…¹}É•ÅÕ¥É•ˆ°(€€€€€€€€€€€€‰µ•ÍÍ…”ˆè€‹–ş¦‚#–#–º3š"C¢Ï–ÂD€Äƒ’ö7–>¿š:—šRØ1%9ƒ¦k~—jš‚ã–ş–º#¢¶ß’êëÚ–ºhˆ°(€€€€€€€€€€€€¨©…•ÍÌ°(€€€€€€€ô°€ĞÀÀ(€€€ÍÑ…ÑÕÌ€ôÉ•½É‘}¡•­¥¸¡‘…Ñ…}™¥±”°Á…å±½…°½¹™¥œõ½¹™¥œ¤(€€€µÕÑ…Ñ•}ÍÑ…Ñ•}…Ñ½µ¥…±±ä (€€€€€€€‘…Ñ…}™¥±”°(€€€€€€€±…µ‰‘„ÕÉÉ•¹Ñ}ÍÑ…Ñ”è¹•áĞ (€€€€€€€€€€€€ (€€€€€€€€€€€€€€€É½Ü¹ÕÁ‘…Ñ”¡ì‰ÍÕ•ÍÌˆèQÉÕ•ô¤(€€€€€€€€€€€€€€€™½ÈÉ½Ü¥¸ÕÉÉ•¹Ñ}ÍÑ…Ñ”¹•Ğ ‰±…Õ¹¡}•Ù•¹ÑÌˆ¤½Èmt(€€€€€€€€€€€€€€€¥˜É½Ü¹•Ğ ‰¥ˆ¤€ôô•Ù•¹Ñ}¥(€€€€€€€€€€€€¤°(€€€€€€€€€€€9½¹”°(€€€€€€€€¤°(€€€€¤(€€€ÍÑ…ÑÕÍl‰½¬‰t€ôQÉÕ”(€€€É•ÑÕÉ¸ÍÑ…ÑÕÌ°€ÈÀÀ(()‘•˜ÍÑ…ÑÕÍ}™½É}ÕÍ•È¡‘…Ñ…}™¥±”°±¥¹•}ÕÍ•É}¥°‘¥ÍÁ±…å}¹…µ”ôˆˆ¤è(€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤(€€€ÁÉ½™¥±”€ôÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ°íô¤¹•Ğ¡±¥¹•}ÕÍ•É}¥¤(€€€¥˜¹½ĞÁÉ½™¥±”è(€€€€€€€‘…Ñ„°½‘”€ôÉ•¥ÍÑ•É}±¥¹•}ÕÍ•È (€€€€€€€€€€€‘…Ñ…}™¥±”°(€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€€‰‘¥ÍÁ±…å}¹…µ”ˆèÍÑÈ¡‘¥ÍÁ±…å}¹…µ”½È€ˆˆ¤¹ÍÑÉ¥À ¤½È€‰1%9ƒ’öÿR£¢ˆ°(€€€€€€€€€€€ô°(€€€€€€€€¤(€€€€€€€¥˜½‘”€„ô€ÈÀÀè(€€€€€€€€€€€É•ÑÕÉ¸‘…Ñ„°½‘”(€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡‘…Ñ„°‘¥Ğ¤è(€€€€€€€€€€€‘…Ñ…l‰…ÕÑ½}É•¥ÍÑ•É•‰t€ôQÉÕ”(€€€€€€€É•ÑÕÉ¸‘…Ñ„°€ÈÀÀ(€€€‘¥ÉÑä€ôÍÉÕ‰}Í•±™}±¥¹•}¥‘Í}½¹}½¹Ñ…ÑÌ¡ÁÉ½™¥±”¤(€€€‘¥ÉÑä€ô‘•‘ÕÁ±¥…Ñ•}½¹Ñ…Ñ}±¥¹•}‰¥¹‘¥¹Ì¡ÁÉ½™¥±”¤½È‘¥ÉÑä(€€€‘¥ÉÑä€ô•¹ÍÕÉ•}½¹‰½…É‘¥¹}½µÁ±•Ñ•‘}™±…œ¡ÁÉ½™¥±”¤½È‘¥ÉÑä(€€€Ñ½‘…ä€ôÑ½‘…å}ÍÑÉ¥¹œ ¤(€€€¥˜ÁÉ½™¥±•}¥Í}Ñ½‘…å}¡•­•¡ÁÉ½™¥±”¤…¹Ñ½‘…ä¹½Ğ¥¸Í•Ğ¡ÁÉ½™¥±”¹•Ğ ‰¡¥ÍÑ½Éäˆ¤½Èmt¤è(€€€€€€€¡¥ÍĞ€ôÍ•Ğ¡ÁÉ½™¥±”¹•Ğ ‰¡¥ÍÑ½Éäˆ¤½Èmt¤(€€€€€€€¡¥ÍĞ¹…‘¡Ñ½‘…ä¤(€€€€€€€ÁÉ½™¥±•l‰¡¥ÍÑ½Éä‰t€ôÍ½ÉÑ•¡¡¥ÍĞ¤(€€€€€€€‘¥ÉÑä€ôQÉÕ”(€€€‰•™½É•}É½ÕÁÌ€ô±¥ÍĞ¡ÁÉ½™¥±”¹•Ğ ‰Õ…É‘¥…¹}É½ÕÁ}¥‘Ìˆ¤½Èmt¤(€€€Íå¹}½İ¹•‘}Õ…É‘¥…¹}É½ÕÁ}¥‘Ì¡ÍÑ…Ñ”°ÁÉ½™¥±”¤(€€€¥˜±¥ÍĞ¡ÁÉ½™¥±”¹•Ğ ‰Õ…É‘¥…¹}É½ÕÁ}¥‘Ìˆ¤½Èmt¤€„ô‰•™½É•}É½ÕÁÌè(€€€€€€€‘¥ÉÑä€ôQÉÕ”(€€€¥˜‘¥ÉÑäè(€€€€€€€Í…Ù•}ÍÑ…Ñ”¡‘…Ñ…}™¥±”°ÍÑ…Ñ”¤(€€€É•ÑÕÉ¸‰Õ¥±‘}ÍÑ…ÑÕÌ¡ÁÉ½™¥±”°ÍÑ…Ñ”¤°€ÈÀÀ(()‘•˜É•…Ñ•}…ÁÀ¡½¹™¥œõ9½¹”¤è(€€€¥˜±…Í¬¥Ì9½¹”è(€€€€€€€É•ÑÕÉ¸5¥¹¥ÁÀ¡½¹™¥œ¤((€€€ÍÕÁÁ±¥•‘}½¹™¥œ€ô½¹™¥œ½Èíô(€€€±¥™™}¥€ô€ (€€€€€€€ÍÕÁÁ±¥•‘}½¹™¥œ¹•Ğ ‰1%}%ˆ¤(€€€€€€€½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%}%ˆ¤(€€€€€€€½ÈU1Q}1%}%(€€€€¤¹ÍÑÉ¥À ¤½ÈU1Q}1%}%(€€€•áÁ±¥¥Ñ}¡…¹¹•±}¥€ô€ (€€€€€€€ÍÕÁÁ±¥•‘}½¹™¥œ¹•Ğ ‰1%9}1=%9}!991}%ˆ¤(€€€€€€€½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}1=%9}!991}%ˆ¤(€€€€€€€½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}1½¥¹}¡…¹¹•±}%ˆ¤(€€€€€€€½È€ˆˆ(€€€€¤¹ÍÑÉ¥À ¤(€€€±¥¹•}±½¥¹}¡…¹¹•±}¥€ô€ (€€€€€€€•áÁ±¥¥Ñ}¡…¹¹•±}¥(€€€€€€€½È±¥™™}¥¹ÍÁ±¥Ğ ˆ´ˆ°€Ä¥lÁt(€€€€€€€½ÈU1Q}1%9}1=%9}!991}%(€€€€¤((€€€…ÁÀ€ô±…Í¬¡}}¹…µ•}|°ÍÑ…Ñ¥}™½±‘•Èôˆ¸ˆ°ÍÑ…Ñ¥}ÕÉ±}Á…Ñ ôˆˆ¤(€€€…ÁÀ¹}ÍÑ…ÉÑ}Ñ¥µ”€ô‘…Ñ•Ñ¥µ”¹¹½Ü ¤€€Œ€ÈÀÈØ´ÀÜ´ÈÄÁ…Ñ €ÄÜèƒ’úl€½…Á¤½‰½Ğ½ÍÑ…ÑÕÌƒ¢¢#º\ÕÁÑ¥µ”((€€€…ÁÀ¹•ÉÉ½É¡…¹‘±•È¡½Õ¹Ñ5¥É…Ñ•‘ÉÉ½È¤(€€€‘•˜}…½Õ¹Ñ}µ¥É…Ñ•‘}•ÉÉ½È¡}•ÉÉ½È¤è(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡…½Õ¹Ñ}µ¥É…Ñ•‘}É•ÍÁ½¹Í” ¤¤°€ĞÀä((€€€…ÁÀ¹½¹™¥œ¹ÕÁ‘…Ñ” (€€€€€€€Q}%1õÉ•Í½±Ù•}‘…Ñ…}™¥±”¡½Ì¹•¹Ù¥É½¸¹•Ğ ‰Q}%1ˆ¤¤°(€€€€€€€5%9}AMM]=Iõ½Ì¹•¹Ù¥É½¸¹•Ğ ‰5%9}AMM]=Iˆ°€ˆˆ¤°(€€€€€€€5%9}=AIQ%=9M}AMM]=Iõ½Ì¹•¹Ù¥É½¸¹•Ğ ‰5%9}=AIQ%=9M}AMM]=Iˆ°€ˆˆ¤°(€€€€€€€5%9}%99}AMM]=Iõ½Ì¹•¹Ù¥É½¸¹•Ğ ‰5%9}%99}AMM]=Iˆ°€ˆˆ¤°(€€€€€€€5%9}Y%]I}AMM]=Iõ½Ì¹•¹Ù¥É½¸¹•Ğ ‰5%9}Y%]I}AMM]=Iˆ°€ˆˆ¤°(€€€€€€€5%9}MMM%=9}MIPõ½Ì¹•¹Ù¥É½¸¹•Ğ ‰5%9}MMM%=9}MIPˆ°€ˆˆ¤°(€€€€€€€QIUMQ}AI=ae}!ILõ½Ì¹•¹Ù¥É½¸¹•Ğ ‰QIUMQ}AI=ae}!ILˆ°€ˆˆ¤°(€€€€€€€11=]}=A9}5%8õ½Ì¹•¹Ù¥É½¸¹•Ğ ‰11=]}=A9}5%8ˆ°€ˆˆ¤°(€€€€€€€5%9}=A8õ½Ì¹•¹Ù¥É½¸¹•Ğ ‰5%9}=A8ˆ°€ˆˆ¤°(€€€€€€€AI599Q}MMM%=9}1%Q%5õÑ¥µ•‘•±Ñ„¡¡½ÕÉÌôà¤°(€€€€€€€MMM%=9}==-%}!QQA=91dõQÉÕ”°(€€€€€€€MMM%=9}==-%}MUIõQÉÕ”°(€€€€€€€MMM%=9}==-%}M5M%Qô‰MÑÉ¥Ğˆ°(€€€€€€€1%9}!991}MM}Q=-8ô (€€€€€€€€€€€½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}!991}MM}Q=-8ˆ¤(€€€€€€€€€€€½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰!991}MM}Q=-8ˆ¤(€€€€€€€€€€€½È€ˆˆ(€€€€€€€€¤°(€€€€€€€1%9}!991}MIPô (€€€€€€€€€€€½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}!991}MIPˆ¤(€€€€€€€€€€€½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰!991}MIPˆ¤(€€€€€€€€€€€½È€ˆˆ(€€€€€€€€¤°(€€€€€€€€Œ•ÁĞ½‘…Í¥¹œ™É½´I•¹‘•ÈU$ÑåÁ½Ì€¡1%9}1½¥¹}¡…¹¹•±}%•ÑŒ¸¤(€€€€€€€1%9}1=%9}!991}%õ±¥¹•}±½¥¹}¡…¹¹•±}¥°(€€€€€€€1%9}1=%9}!991}MIPô (€€€€€€€€€€€½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}1=%9}!991}MIPˆ¤(€€€€€€€€€€€½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}1½¥¹}!991}MIPˆ¤(€€€€€€€€€€€½È€ˆˆ(€€€€€€€€¤°(€€€€€€€1e}1%9}1=%9}!991}%õ½Ì¹•¹Ù¥É½¸¹•Ğ (€€€€€€€€€€€€‰1e}1%9}1=%9}!991}%ˆ°€ˆÈÀÄÀØÜĞàÀÌˆ(€€€€€€€€¤°(€€€€€€€1e}1%}%õ½Ì¹•¹Ù¥É½¸¹•Ğ (€€€€€€€€€€€€‰1e}1%}%ˆ°U1Q}1e}1%}%(€€€€€€€€¤°(€€€€€€€=U9Q}5%IQ%=9}MIPõ½Ì¹•¹Ù¥É½¸¹•Ğ ‰=U9Q}5%IQ%=9}MIPˆ°€ˆˆ¤°(€€€€€€€=U9Q}5%IQ%=9}QQ1}M=9LôØÀÀ°(€€€€€€€1%}%õ±¥™™}¥°(€€€€€€€AA}AU	1%}UI0õ½Ì¹•¹Ù¥É½¸¹•Ğ ‰AA}AU	1%}UI0ˆ°€ˆˆ¤°(€€€€€€€AA}Q%5i=9õ½Ì¹•¹Ù¥É½¸¹•Ğ ‰AA}Q%5i=9ˆ°€‰Í¥„½Q…¥Á•¤ˆ¤°(€€€€€€€Ñ}AI=AIQe}%õ½Ì¹•¹Ù¥É½¸¹•Ğ ‰Ñ}AI=AIQe}%ˆ°€ˆˆ¤°(€€€€€€€Ñ}MIY%}=U9Q})M=8õ½Ì¹•¹Ù¥É½¸¹•Ğ ‰Ñ}MIY%}=U9Q})M=8ˆ°€ˆˆ¤°(€€€€€€€Ñ}5MUI59Q}%õ½Ì¹•¹Ù¥É½¸¹•Ğ ‰Ñ}5MUI59Q}%ˆ°€‰´İ1PÄÑa1!4ˆ¤°(€€€€€€€]=IAIMM}M%Q}UI0õ½Ì¹•¹Ù¥É½¸¹•Ğ ‰]=IAIMM}M%Q}UI0ˆ°€ˆˆ¤°(€€€€€€€]=IAIMM}UMI95õ½Ì¹•¹Ù¥É½¸¹•Ğ ‰]=IAIMM}UMI95ˆ°€ˆˆ¤°(€€€€€€€]=IAIMM}AA1%Q%=9}AMM]=Iõ½Ì¹•¹Ù¥É½¸¹•Ğ ‰]=IAIMM}AA1%Q%=9}AMM]=Iˆ°€ˆˆ¤°(€€€€€€€1%9}5=9Q!1e}5MM}1%5%Põ½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}5=9Q!1e}5MM}1%5%Pˆ°€ˆÈÀÀˆ¤°(€€€€€€€1%9}5MM}]I9%9}AI9Põ½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}5MM}]I9%9}AI9Pˆ°€ˆàÀˆ¤°(€€€€€€€1%9}5MM}!I}MQ=A}AI9Põ½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}5MM}!I}MQ=A}AI9Pˆ°€ˆÄÀÀˆ¤°(€€€€€€€I=9}MIPõ½Ì¹•¹Ù¥É½¸¹•Ğ ‰I=9}MIPˆ°€ˆˆ¤°(€€€€€€€IEU%I}1%}UQ õ½Ì¹•¹Ù¥É½¸¹•Ğ ‰IEU%I}1%}UQ ˆ°€ˆÀˆ¤°(€€€€€€€9]	Ae}5I!9Q}%õ½Ì¹•¹Ù¥É½¸¹•Ğ ‰9]	Ae}5I!9Q}%ˆ°€ˆˆ¤°(€€€€€€€9]	Ae}!M!}-dõ½Ì¹•¹Ù¥É½¸¹•Ğ ‰9]	Ae}!M!}-dˆ°€ˆˆ¤°(€€€€€€€9]	Ae}!M!}%Xõ½Ì¹•¹Ù¥É½¸¹•Ğ ‰9]	Ae}!M!}%Xˆ°€ˆˆ¤°(€€€€€€€9]	Ae}MQõ½Ì¹•¹Ù¥É½¸¹•Ğ ‰9]	Ae}MQˆ°€‰Í…¹‘‰½àˆ¤°(€€€€€€€9]	Ae}5A}UI0õ½Ì¹•¹Ù¥É½¸¹•Ğ ‰9]	Ae}5A}UI0ˆ°€ˆˆ¤°(€€€€€€€Ae}5I!9Q}%õ½Ì¹•¹Ù¥É½¸¹•Ğ ‰Ae}5I!9Q}%ˆ°€ˆˆ¤°(€€€€€€€Ae}!M!}-dõ½Ì¹•¹Ù¥É½¸¹•Ğ ‰Ae}!M!}-dˆ°€ˆˆ¤°(€€€€€€€Ae}!M!}%Xõ½Ì¹•¹Ù¥É½¸¹•Ğ ‰Ae}!M!}%Xˆ°€ˆˆ¤°(€€€€€€€Ae}MQõ½Ì¹•¹Ù¥É½¸¹•Ğ ‰Ae}MQˆ°€‰Í…¹‘‰½àˆ¤°(€€€€€€€Ae}AI%=}Q%5Lõ½Ì¹•¹Ù¥É½¸¹•Ğ ‰Ae}AI%=}Q%5Lˆ°€ˆääˆ¤°(€€€€€€€M5M-%9}UMI95õ½Ì¹•¹Ù¥É½¸¹•Ğ ‰M5M-%9}UMI95ˆ°€ˆˆ¤°(€€€€€€€M5M-%9}AMM]=Iõ½Ì¹•¹Ù¥É½¸¹•Ğ ‰M5M-%9}AMM]=Iˆ°€ˆˆ¤°(€€€€€€€M5QA}!=MPõ½Ì¹•¹Ù¥É½¸¹•Ğ ‰M5QA}!=MPˆ°€ˆˆ¤°(€€€€€€€M5QA}A=IPõ½Ì¹•¹Ù¥É½¸¹•Ğ ‰M5QA}A=IPˆ°€ˆÔàÜˆ¤°(€€€€€€€M5QA}UMI95õ½Ì¹•¹Ù¥É½¸¹•Ğ ‰M5QA}UMI95ˆ°€ˆˆ¤°(€€€€€€€M5QA}AMM]=Iõ½Ì¹•¹Ù¥É½¸¹•Ğ ‰M5QA}AMM]=Iˆ°€ˆˆ¤°(€€€€€€€M5QA}UM}Q1Lõ½Ì¹•¹Ù¥É½¸¹•Ğ ‰M5QA}UM}Q1Lˆ°€‰ÑÉÕ”ˆ¤°(€€€€€€€MUAA=IQ}I=5}5%0õ½Ì¹•¹Ù¥É½¸¹•Ğ ‰MUAA=IQ}I=5}5%0ˆ°€ˆˆ¤°(€€€€€€€HÉ}9A=%9Põ½Ì¹•¹Ù¥É½¸¹•Ğ ‰HÉ}9A=%9Pˆ°€ˆˆ¤°(€€€€€€€HÉ}MM}-e}%õ½Ì¹•¹Ù¥É½¸¹•Ğ ‰HÉ}MM}-e}%ˆ°€ˆˆ¤°(€€€€€€€HÉ}MIQ}MM}-dõ½Ì¹•¹Ù¥É½¸¹•Ğ ‰HÉ}MIQ}MM}-dˆ°€ˆˆ¤°(€€€€€€€HÉ}	U-Põ½Ì¹•¹Ù¥É½¸¹•Ğ ‰HÉ}	U-Pˆ°€ˆˆ¤°(€€€€€€€HÉ}	-UA}9IeAQ%=9}-dõ½Ì¹•¹Ù¥É½¸¹•Ğ (€€€€€€€€€€€€‰HÉ}	-UA}9IeAQ%=9}-dˆ°€ˆˆ(€€€€€€€€¤°(€€€€€€€QMQ}1%9}UMI}%Lõ½Ì¹•¹Ù¥É½¸¹•Ğ ‰QMQ}1%9}UMI}%Lˆ°€ˆˆ¤°(€€€€¤(€€€¥˜½¹™¥œè(€€€€€€€…ÁÀ¹½¹™¥œ¹ÕÁ‘…Ñ”¡½¹™¥œ¤(€€€…ÁÀ¹Í•É•Ñ}­•ä€ô€ (€€€€€€€…ÁÀ¹½¹™¥œ¹•Ğ ‰5%9}MMM%=9}MIPˆ¤(€€€€€€€½ÈÍ•É•ÑÌ¹Ñ½­•¹}¡•à ÌÈ¤(€€€€¤((€€€‘•˜}…‘µ¥¹}Õ…É ¨°İÉ¥Ñ”õ…±Í”°Á•Éµ¥ÍÍ¥½¸õ9½¹”¤è(€€€€€€€¥˜¹½Ğ…‘µ¥¹}Í•ÕÉ¥Ñå}É•…‘ä¡…ÁÀ¹½¹™¥œ¤è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰…‘µ¥¹}¹½Ñ}½¹™¥ÕÉ•‰ô¤°€ÔÀÌ(€€€€€€€¥˜Í•ÍÍ¥½¸¹•Ğ ‰…‘µ¥¹}…ÕÑ¡•¹Ñ¥…Ñ•ˆ¤¥Ì¹½ĞQÉÕ”è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô¤°€ĞÀÄ(€€€€€€€¥˜İÉ¥Ñ”è(€€€€€€€€€€€•áÁ•Ñ•€ôÍÑÈ¡Í•ÍÍ¥½¸¹•Ğ ‰…‘µ¥¹}ÍÉ˜ˆ¤½È€ˆˆ¤(€€€€€€€€€€€ÁÉ½Ù¥‘•€ôÍÑÈ¡É•ÅÕ•ÍĞ¹¡•…‘•ÉÌ¹•Ğ ‰`µMIµQ½­•¸ˆ¤½È€ˆˆ¤(€€€€€€€€€€€¥˜¹½Ğ•áÁ•Ñ•½È¹½ĞÍ•É•ÑÌ¹½µÁ…É•}‘¥•ÍĞ¡•áÁ•Ñ•°ÁÉ½Ù¥‘•¤è(€€€€€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰ÍÉ™}É•ÅÕ¥É•‰ô¤°€ĞÀÌ(€€€€€€€¥˜Á•Éµ¥ÍÍ¥½¸è(€€€€€€€€€€€É½±”€ôÍÑÈ¡Í•ÍÍ¥½¸¹•Ğ ‰…‘µ¥¹}É½±”ˆ¤½È€‰Ù¥•İ•Èˆ¤(€€€€€€€€€€€¥˜Á•Éµ¥ÍÍ¥½¸¹½Ğ¥¸5%9}I=1}AI5%MM%=9L¹•Ğ¡É½±”°Í•Ğ ¤¤è(€€€€€€€€€€€€€€€…ÁÁ•¹‘}…‘µ¥¹}…Õ‘¥Ğ (€€€€€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€€€€€€‰Á•Éµ¥ÍÍ¥½¸¹‘•¹¥•ˆ°(€€€€€€€€€€€€€€€€€€€€‰™…¥±•ˆ°(€€€€€€€€€€€€€€€€€€€ì‰É½±”ˆèÉ½±”°€‰É•ÅÕ¥É•‘}Á•Éµ¥ÍÍ¥½¸ˆèÁ•Éµ¥ÍÍ¥½¹ô°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰™½É‰¥‘‘•¸ˆ°€‰É•ÅÕ¥É•‘}Á•Éµ¥ÍÍ¥½¸ˆèÁ•Éµ¥ÍÍ¥½¹ô¤°€ĞÀÌ(€€€€€€€É•ÑÕÉ¸9½¹”((€€€‘•˜}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í”¡…Ñ¥½¸°‘…Ñ„°½‘”ôÈÀÀ¤è(€€€€€€€…ÁÁ•¹‘}…‘µ¥¹}…Õ‘¥Ğ (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€…Ñ¥½¸°(€€€€€€€€€€€€‰ÍÕ•ÍÌˆ¥˜½‘”€ğ€ĞÀÀ•±Í”€‰™…¥±•ˆ°(€€€€€€€€€€€ì‰¡ÑÑÁ}ÍÑ…ÑÕÌˆè½‘•ô°(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€‘•˜}…‘µ¥¹}±½¥¹}ÑÉ…¹ÍÁ½ÉÑ}Í•ÕÉ” ¤è(€€€€€€€¥˜…ÁÀ¹½¹™¥œ¹•Ğ ‰QMQ%9ˆ¤¥ÌQÉÕ”è(€€€€€€€€€€€É•ÑÕÉ¸QÉÕ”(€€€€€€€¥˜É•ÅÕ•ÍĞ¹¥Í}Í•ÕÉ”è(€€€€€€€€€€€É•ÑÕÉ¸QÉÕ”(€€€€€€€¥˜ÍÑÈ¡É•ÅÕ•ÍĞ¹É•µ½Ñ•}…‘‘È½È€ˆˆ¤¥¸ìˆÄÈÜ¸À¸À¸Äˆ°€ˆèèÄ‰ôè(€€€€€€€€€€€É•ÑÕÉ¸QÉÕ”(€€€€€€€ÑÉÕÍÑ•‘}ÁÉ½áä€ô€ (€€€€€€€€€€€}•¹Ù}™±…}½¸ ‰I9Hˆ°…ÁÀ¹½¹™¥œ¤(€€€€€€€€€€€½È}•¹Ù}™±…}½¸ ‰QIUMQ}AI=ae}!ILˆ°…ÁÀ¹½¹™¥œ¤(€€€€€€€€¤(€€€€€€€™½Éİ…É‘•‘}ÁÉ½Ñ¼€ôÍÑÈ (€€€€€€€€€€€É•ÅÕ•ÍĞ¹¡•…‘•ÉÌ¹•Ğ ‰`µ½Éİ…É‘•µAÉ½Ñ¼ˆ¤½È€ˆˆ(€€€€€€€€¤¹ÍÁ±¥Ğ ˆ°ˆ°€Ä¥lÁt¹ÍÑÉ¥À ¤¹±½İ•È ¤(€€€€€€€É•ÑÕÉ¸ÑÉÕÍÑ•‘}ÁÉ½áä…¹™½Éİ…É‘•‘}ÁÉ½Ñ¼€ôô€‰¡ÑÑÁÌˆ((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…‘µ¥¸½±½¥¸ˆ¤(€€€‘•˜…‘µ¥¹}±½¥¹}…Á¤ ¤è(€€€€€€€¥˜¹½Ğ}…‘µ¥¹}±½¥¹}ÑÉ…¹ÍÁ½ÉÑ}Í•ÕÉ” ¤è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰¡ÑÑÁÍ}É•ÅÕ¥É•‰ô¤°€ĞÀÀ(€€€€€€€¥˜¹½Ğ…‘µ¥¹}Í•ÕÉ¥Ñå}É•…‘ä¡…ÁÀ¹½¹™¥œ¤è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰…‘µ¥¹}¹½Ñ}½¹™¥ÕÉ•‰ô¤°€ÔÀÌ(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥•¹Ñ}­•ä€ôÍÑÈ¡É•ÅÕ•ÍĞ¹É•µ½Ñ•}…‘‘È½È€‰Õ¹­¹½İ¸ˆ¤(€€€€€€€¥˜…‘µ¥¹}±½¥¹}É…Ñ•}±¥µ¥Ñ•¡±¥•¹Ñ}­•ä¤è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰Ñ½½}µ…¹å}…ÑÑ•µÁÑÌ‰ô¤°€ĞÈä(€€€€€€€É½±”€ô…‘µ¥¹}É½±•}™½É}Á…ÍÍİ½É¡…ÁÀ¹½¹™¥œ°Á…å±½…¹•Ğ ‰Á…ÍÍİ½Éˆ¤¤(€€€€€€€¥˜É½±”¥Ì9½¹”è(€€€€€€€€€€€É•½É‘}…‘µ¥¹}±½¥¹}™…¥±ÕÉ”¡±¥•¹Ñ}­•ä¤(€€€€€€€€€€€…ÁÁ•¹‘}…‘µ¥¹}…Õ‘¥Ğ¡…ÁÀ¹½¹™¥l‰Q}%1‰t°€‰Í•ÍÍ¥½¸¹±½¥¸ˆ°€‰™…¥±•ˆ¤(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰¥¹Ù…±¥‘}É•‘•¹Ñ¥…±Ì‰ô¤°€ĞÀÄ(€€€€€€€5%9}1=%9}QQ5AQL¹Á½À¡±¥•¹Ñ}­•ä°9½¹”¤(€€€€€€€Í•ÍÍ¥½¸¹±•…È ¤(€€€€€€€Í•ÍÍ¥½¸¹Á•Éµ…¹•¹Ğ€ôQÉÕ”(€€€€€€€Í•ÍÍ¥½¹l‰…‘µ¥¹}…ÕÑ¡•¹Ñ¥…Ñ•‰t€ôQÉÕ”(€€€€€€€Í•ÍÍ¥½¹l‰…‘µ¥¹}É½±”‰t€ôÉ½±”(€€€€€€€Í•ÍÍ¥½¹l‰…‘µ¥¹}ÍÉ˜‰t€ôÍ•É•ÑÌ¹Ñ½­•¹}ÕÉ±Í…™” ÌÈ¤(€€€€€€€…ÁÁ•¹‘}…‘µ¥¹}…Õ‘¥Ğ¡…ÁÀ¹½¹™¥l‰Q}%1‰t°€‰Í•ÍÍ¥½¸¹±½¥¸ˆ°€‰ÍÕ•ÍÌˆ¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì(€€€€€€€€€€€€‰½¬ˆèQÉÕ”°(€€€€€€€€€€€€‰ÍÉ™}Ñ½­•¸ˆèÍ•ÍÍ¥½¹l‰…‘µ¥¹}ÍÉ˜‰t°(€€€€€€€€€€€€‰É½±”ˆèÉ½±”°(€€€€€€€€€€€€‰Á•Éµ¥ÍÍ¥½¹Ìˆè…‘µ¥¹}Á•Éµ¥ÍÍ¥½¹Í}™½É}É½±”¡É½±”¤°(€€€€€€€€€€€€‰•áÁ¥É•Í}¥¸ˆè€à€¨€ØÀ€¨€ØÀ°(€€€€€€€ô¤((€€€…ÁÀ¹•Ğ ˆ½…Á¤½…‘µ¥¸½Í•ÍÍ¥½¸ˆ¤(€€€‘•˜…‘µ¥¹}Í•ÍÍ¥½¹}…Á¤ ¤è(€€€€€€€¥˜¹½Ğ…‘µ¥¹}Í•ÕÉ¥Ñå}É•…‘ä¡…ÁÀ¹½¹™¥œ¤è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰…ÕÑ¡•¹Ñ¥…Ñ•ˆè…±Í”°€‰•ÉÉ½Èˆè€‰…‘µ¥¹}¹½Ñ}½¹™¥ÕÉ•‰ô¤°€ÔÀÌ(€€€€€€€…ÕÑ¡•¹Ñ¥…Ñ•€ôÍ•ÍÍ¥½¸¹•Ğ ‰…‘µ¥¹}…ÕÑ¡•¹Ñ¥…Ñ•ˆ¤¥ÌQÉÕ”(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì(€€€€€€€€€€€€‰…ÕÑ¡•¹Ñ¥…Ñ•ˆè…ÕÑ¡•¹Ñ¥…Ñ•°(€€€€€€€€€€€€‰ÍÉ™}Ñ½­•¸ˆèÍ•ÍÍ¥½¸¹•Ğ ‰…‘µ¥¹}ÍÉ˜ˆ¤¥˜…ÕÑ¡•¹Ñ¥…Ñ••±Í”9½¹”°(€€€€€€€€€€€€‰É½±”ˆèÍ•ÍÍ¥½¸¹•Ğ ‰…‘µ¥¹}É½±”ˆ¤¥˜…ÕÑ¡•¹Ñ¥…Ñ••±Í”9½¹”°(€€€€€€€€€€€€‰Á•Éµ¥ÍÍ¥½¹Ìˆè…‘µ¥¹}Á•Éµ¥ÍÍ¥½¹Í}™½É}É½±”¡Í•ÍÍ¥½¸¹•Ğ ‰…‘µ¥¹}É½±”ˆ¤¤¥˜…ÕÑ¡•¹Ñ¥…Ñ••±Í”mt°(€€€€€€€ô¤°€ ÈÀÀ¥˜…ÕÑ¡•¹Ñ¥…Ñ••±Í”€ĞÀÄ¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…‘µ¥¸½±½½ÕĞˆ¤(€€€‘•˜…‘µ¥¹}±½½ÕÑ}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É¡İÉ¥Ñ”õQÉÕ”¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€Í•ÍÍ¥½¸¹±•…È ¤(€€€€€€€…ÁÁ•¹‘}…‘µ¥¹}…Õ‘¥Ğ¡…ÁÀ¹½¹™¥l‰Q}%1‰t°€‰Í•ÍÍ¥½¸¹±½½ÕĞˆ°€‰ÍÕ•ÍÌˆ¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¬ˆèQÉÕ•ô¤((€€€‘•˜}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…õ9½¹”°€¨°ÕÍ•}…ÉÌõ…±Í”¤è(€€€€€€€€ˆˆ‰I•Í½±Ù”1%9ÕÍ•È™É½´Ù•É¥™¥•¥‘}Ñ½­•¸İ¡•¸É•ÅÕ¥É•¸ˆˆˆ(€€€€€€€Á…å±½…€ôÁ…å±½…¥˜Á…å±½…¥Ì¹½Ğ9½¹”•±Í”€¡É•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô¤(€€€€€€€…ÉÌ€ôÉ•ÅÕ•ÍĞ¹…ÉÌ¥˜ÕÍ•}…ÉÌ•±Í”íô(€€€€€€€É•ÑÕÉ¸…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È (€€€€€€€€€€€Á…å±½…°(€€€€€€€€€€€…ÉÌõ…ÉÌ°(€€€€€€€€€€€¡•…‘•ÉÌõí­•äèÙ…±Õ”™½È­•ä°Ù…±Õ”¥¸É•ÅÕ•ÍĞ¹¡•…‘•ÉÌ¹¥Ñ•µÌ ¥ô°(€€€€€€€€€€€½¹™¥œõ…ÁÀ¹½¹™¥œ°(€€€€€€€€¤((€€€‘•˜}Í¡½Õ±‘}­••Á}±¥™™}•¹‘Á½¥¹Ñ}ÍÁ„ ¤è(€€€€€€€€ˆˆ‰1%¹‘Á½¥¹Ğ5UMP…±İ…åÌÍ•ÉÙ”Ñ¡”MAÑ¡…ĞÉÕ¹Ì±¥™˜¹¥¹¥Ğ ¤¸((€€€€€€€9•Ù•È€ÌÀÈ€¼ı¥¹Ù¥Ñ•}™É½´õ€€¡½È™É¥•¹‘}¥¹Ù¥Ñ”¤…İ…ä™É½´€½€è(€€€€€€€€´1%9½Á•¹Ì¹‘Á½¥¹Ğİ¥Ñ ÅÕ•Éä€¼±¥™˜¹ÍÑ…Ñ”(€€€€€€€€´1%91½¥¸É•ÑÕÉ¹Ì½‘•€½ÍÑ…Ñ•€½¸Ñ¡”Í…µ”¹‘Á½¥¹ĞUI0(€€€€€€€I•‘¥É•Ñ¥¹œÑ¡½Í”Ñ¼€½¥¹Ù¥Ñ•€ÍÑÉ¥ÁÌ=ÕÑ Á…É…µÌƒŠH¥=L­¹‘É½¥±½¥¸‘¥•Ì¸(€€€€€€€áÑ•É¹…°µ‰É½İÍ•È¥¹Ù¥Ñ••ÌÍ¡½Õ±ÕÍ”•áÁ±¥¥Ğ€½¥¹Ù¥Ñ•€Í¡½ÉĞ±¥¹­Ì¥¹ÍÑ•…¸(€€€€€€€€ˆˆˆ(€€€€€€€É•ÑÕÉ¸QÉÕ”((€€€…ÁÀ¹•Ğ ˆ¼ˆ¤(€€€‘•˜¥¹‘•à ¤è(€€€€€€€€Œ±İ…åÌÍ•ÉÙ”MA½¸1%¹‘Á½¥¹Ğ€½€€¡Í•”}Í¡½Õ±‘}­••Á}±¥™™}•¹‘Á½¥¹Ñ}ÍÁ„¤¸(€€€€€€€|€ô}Í¡½Õ±‘}­••Á}±¥™™}•¹‘Á½¥¹Ñ}ÍÁ„ ¤(€€€€€€€É•ÑÕÉ¸Í•¹‘}™É½µ}‘¥É•Ñ½Éä¡…ÁÀ¹ÍÑ…Ñ¥}™½±‘•È°€‰¥¹‘•à¹¡Ñµ°ˆ¤((€€€…ÁÀ¹•Ğ ˆ½¥¹Ù¥Ñ”ˆ¤(€€€‘•˜¥¹Ù¥Ñ•}Í¡½ÉÑ}±¥¹¬ ¤è(€€€€€€€€ˆˆ‰%¹Ù¥Ñ”±…¹‘¥¹œ™½È•áÑ•É¹…°‰É½İÍ•ÉÌ½¹±ä€¡¹½ĞÑ¡”1%¹‘Á½¥¹Ğ¤¸ˆˆˆ(€€€€€€€É•ÑÕÉ¸Í•¹‘}™É½µ}‘¥É•Ñ½Éä¡…ÁÀ¹ÍÑ…Ñ¥}™½±‘•È°€‰¥¹Ù¥Ñ”¹¡Ñµ°ˆ¤((€€€…ÁÀ¹•Ğ ˆ½‰•Ñ„¼Ìääˆ¤(€€€…ÁÀ¹•Ğ ˆ½‰•Ñ„¼Üääˆ¤(€€€‘•˜‰•Ñ…}É•¥ÍÑÉ…Ñ¥½¹}±…¹‘¥¹œ ¤è(€€€€€€€€ˆˆ‰AÕ‰±¥Œ€ÈÄµ‘…ä‰•Ñ„¥¹ÑÉ½‘ÕÑ¥½¸ìÑ¡”Q½¹Ñ¥¹Õ•Ì¥¸Ù•É¥™¥•1%¸ˆˆˆ(€€€€€€€É•ÑÕÉ¸Í•¹‘}™É½µ}‘¥É•Ñ½Éä¡…ÁÀ¹ÍÑ…Ñ¥}™½±‘•È°€‰‰•Ñ„µÉ•¥ÍÑ•È¹¡Ñµ°ˆ¤((€€€…ÁÀ¹•Ğ ˆ½ÑÉ¥…°¼ÄĞˆ¤(€€€‘•˜ÁÕ‰±¥}ÑÉ¥…±}±…¹‘¥¹œ ¤è(€€€€€€€€ˆˆ‰AÕ‰±¥Œ€ÄĞµ‘…äÑÉ¥…°¥¹ÑÉ½‘ÕÑ¥½¸…¹Õ¥‘•É•¥ÍÑÉ…Ñ¥½¸¸ˆˆˆ(€€€€€€€É•ÑÕÉ¸Í•¹‘}™É½µ}‘¥É•Ñ½Éä¡…ÁÀ¹ÍÑ…Ñ¥}™½±‘•È°€‰ÑÉ¥…°´ÄĞ¹¡Ñµ°ˆ¤((€€€…ÁÀ¹•Ğ ˆ½Õ…É‘¥…¸µÕ¥‘”ˆ¤(€€€‘•˜Õ…É‘¥…¹}Õ¥‘” ¤è(€€€€€€€€ˆˆ‰•Ñ…¥±•Õ…É‘¥…¸¹½Ñ¥”±¥¹­•™É½´Ñ¡”½¹¥Í”¥¹Ù¥Ñ”±…¹‘¥¹œ¸ˆˆˆ(€€€€€€€É•ÑÕÉ¸Í•¹‘}™É½µ}‘¥É•Ñ½Éä¡…ÁÀ¹ÍÑ…Ñ¥}™½±‘•È°€‰Õ…É‘¥…¸µÕ¥‘”¹¡Ñµ°ˆ¤((€€€…ÁÀ¹•Ğ ˆ½¡•…±Ñ ˆ¤(€€€‘•˜¡•…±Ñ  ¤è(€€€€€€€Á•ÉÍ¥ÍĞ€ôÁ•ÉÍ¥ÍÑ•¹•}¥¹™¼¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¬ˆèQÉÕ”°€‰Á•ÉÍ¥ÍÑ•¹”ˆèÁ•ÉÍ¥ÍÑô¤((€€€…ÁÀ¹•Ğ ˆ½É½‰½ÑÌ¹ÑáĞˆ¤(€€€‘•˜É½‰½ÑÍ}ÑáĞ ¤è(€€€€€€€É•ÑÕÉ¸Í•¹‘}™É½µ}‘¥É•Ñ½Éä¡…ÁÀ¹ÍÑ…Ñ¥}™½±‘•È°€‰É½‰½ÑÌ¹ÑáĞˆ°µ¥µ•ÑåÁ”ô‰Ñ•áĞ½Á±…¥¸ˆ¤((€€€…ÁÀ¹•Ğ ˆ½Í¥Ñ•µ…À¹áµ°ˆ¤(€€€‘•˜Í¥Ñ•µ…Á}áµ° ¤è(€€€€€€€É•ÑÕÉ¸Í•¹‘}™É½µ}‘¥É•Ñ½Éä¡…ÁÀ¹ÍÑ…Ñ¥}™½±‘•È°€‰Í¥Ñ•µ…À¹áµ°ˆ°µ¥µ•ÑåÁ”ô‰…ÁÁ±¥…Ñ¥½¸½áµ°ˆ¤((€€€…ÁÀ¹•Ğ ˆ½…‘µ¥¸ˆ¤(€€€‘•˜…‘µ¥¸ ¤è(€€€€€€€É•ÍÀ€ôÍ•¹‘}™É½µ}‘¥É•Ñ½Éä¡…ÁÀ¹ÍÑ…Ñ¥}™½±‘•È°€‰…‘µ¥¸¹¡Ñµ°ˆ¤(€€€€€€€€ŒÙ½¥ÍÑ…±”…¡•…‘µ¥¸U$€¡±½¥¸‰…È€¼Á…ÍÍİ½ÉU`¤…™Ñ•È‘•Á±½åÌ(€€€€€€€É•ÍÀ¹¡•…‘•ÉÍl‰…¡”µ½¹ÑÉ½°‰t€ô€‰¹¼µÍÑ½É”°¹¼µ…¡”°µÕÍĞµÉ•Ù…±¥‘…Ñ”°µ…àµ…”ôÀˆ(€€€€€€€É•ÍÀ¹¡•…‘•ÉÍl‰AÉ…µ„‰t€ô€‰¹¼µ…¡”ˆ(€€€€€€€É•ÑÕÉ¸É•ÍÀ((€€€…ÁÀ¹•Ğ ˆ½Ñ•ÍÑ}‰¥¹ˆ¤(€€€‘•˜Ñ•ÍÑ}‰¥¹ ¤è(€€€€€€€É•ÑÕÉ¸Í•¹‘}™É½µ}‘¥É•Ñ½Éä¡…ÁÀ¹ÍÑ…Ñ¥}™½±‘•È°€‰Ñ•ÍÑ}‰¥¹¹¡Ñµ°ˆ¤((€€€…ÁÀ¹•Ğ ˆ½Ñ•ÉµÌˆ¤(€€€‘•˜Ñ•ÉµÌ ¤è(€€€€€€€É•ÑÕÉ¸Í•¹‘}™É½µ}‘¥É•Ñ½Éä¡…ÁÀ¹ÍÑ…Ñ¥}™½±‘•È°€‰Ñ•ÉµÌ¹¡Ñµ°ˆ¤((€€€…ÁÀ¹•Ğ ˆ½ÁÉ¥Ù…äˆ¤(€€€‘•˜ÁÉ¥Ù…ä ¤è(€€€€€€€É•ÑÕÉ¸Í•¹‘}™É½µ}‘¥É•Ñ½Éä¡…ÁÀ¹ÍÑ…Ñ¥}™½±‘•È°€‰ÁÉ¥Ù…ä¹¡Ñµ°ˆ¤((€€€…ÁÀ¹•Ğ ˆ½™…Äˆ¤(€€€‘•˜™…Ä ¤è(€€€€€€€É•ÑÕÉ¸Í•¹‘}™É½µ}‘¥É•Ñ½Éä¡…ÁÀ¹ÍÑ…Ñ¥}™½±‘•È°€‰™…Ä¹¡Ñµ°ˆ¤((€€€…ÁÀ¹•Ğ ˆ½¡•±Àˆ¤(€€€‘•˜¡•±Á}Á…” ¤è(€€€€€€€É•ÑÕÉ¸Í•¹‘}™É½µ}‘¥É•Ñ½Éä¡…ÁÀ¹ÍÑ…Ñ¥}™½±‘•È°€‰¡•±À¹¡Ñµ°ˆ¤((€€€…ÁÀ¹•Ğ ˆ½ÁÉ¥¥¹œˆ¤(€€€‘•˜ÁÉ¥¥¹}Á…” ¤è(€€€€€€€€ŒƒnÓ–ëšZçš†#¦‚¾ò3¦ÿ–4ÁÉ¥¥¹œ¹¡Ñµ°ƒŠH±¥™˜½ÁÉ¥¥¹œ¹¡Ñµ°ƒ¦ng¦7¢ö'¢ŞÌ(€€€€€€€É•ÑÕÉ¸Í•¹‘}™É½µ}‘¥É•Ñ½Éä¡…ÁÀ¹ÍÑ…Ñ¥}™½±‘•È°€‰±¥™˜½ÁÉ¥¥¹œ¹¡Ñµ°ˆ¤((€€€‘•˜}±¥™™}•µ‰•‘}É•‘¥É•Ğ¡½Á•¹}…Ñ¥½¸õ9½¹”°™É…µ•¹Ğôˆˆ¤è(€€€€€€€€ˆˆ‹¢"(€½±¥™˜¼¨!QQALƒ¦ÖCšRç–Â;šÂã’æ–Ÿ–Ö3–—–>¾ò3¦ÿ–7–’[¦Z/?¢š÷–f£ˆˆˆ(€€€€€€€¥˜±¥™™}•¹ÑÉå}ÕÉ°¥Ì¹½Ğ9½¹”è(€€€€€€€€€€€Ñ…É•Ğ€ô±¥™™}•¹ÑÉå}ÕÉ°¡½Á•¹}…Ñ¥½¸õ½Á•¹}…Ñ¥½¸°™É…µ•¹Ğõ™É…µ•¹Ğ¤(€€€€€€€•±Í”è(€€€€€€€€€€€±¥€ô€ (€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥œ¹•Ğ ‰1%}%ˆ¤(€€€€€€€€€€€€€€€½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%}%ˆ¤(€€€€€€€€€€€€€€€½ÈU1Q}1%}%(€€€€€€€€€€€€¤¹ÍÑÉ¥À ¤(€€€€€€€€€€€Ñ…É•Ğ€ô˜‰¡ÑÑÁÌè¼½±¥™˜¹±¥¹”¹µ”½í±¥‘ôˆ(€€€€€€€€€€€¥˜½Á•¹}…Ñ¥½¸è(€€€€€€€€€€€€€€€Ñ…É•Ğ€¬ô˜ˆı½Á•¸õí½Á•¹}…Ñ¥½¹ôˆ(€€€€€€€€€€€•±¥˜™É…µ•¹Ğè(€€€€€€€€€€€€€€€Ñ…É•Ğ€¬ô˜ˆí™É…µ•¹Ğ¹±ÍÑÉ¥À œŒœ¥ôˆ(€€€€€€€¥˜É•‘¥É•Ğ¥Ì¹½Ğ9½¹”è(€€€€€€€€€€€É•ÑÕÉ¸É•‘¥É•Ğ¡Ñ…É•Ğ°½‘”ôÌÀÈ¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰É•‘¥É•ĞˆèÑ…É•Ñô¤°€ÌÀÈ((€€€€Œƒ–r[šZ¦ã–Z¸€¼ƒ¢"+¦ÖC¾òk–Â;–BD±¥™˜¹±¥¹”¹µ”ƒ–Ÿ–Ö3¾ò#–Z»’â ¹‘Á½¥¹Ğ€ô¥¹‘•à¹¡Ñµ³¾ò$(€€€…ÁÀ¹•Ğ ˆ½±¥™˜½Í¡…É”µ¥¹Ù¥Ñ”ˆ¤(€€€…ÁÀ¹•Ğ ˆ½±¥™˜½Í¡…É”µ¥¹Ù¥Ñ”¹¡Ñµ°ˆ¤(€€€‘•˜±¥™™}Í¡…É•}¥¹Ù¥Ñ•}Á…” ¤è(€€€€€€€€ˆˆ‹–Â#R£’â¦6×–"’ê¯¦‚¾ò#Ö˜1%ƒ–¶C¢Ş¿–úGnÓ¦¾òo’â7ÚLMA¡½µ—¾ò'ˆˆˆ(€€€€€€€É•ÑÕÉ¸Í•¹‘}™É½µ}‘¥É•Ñ½Éä¡…ÁÀ¹ÍÑ…Ñ¥}™½±‘•È°€‰±¥™˜½Í¡…É”µ¥¹Ù¥Ñ”¹¡Ñµ°ˆ¤((€€€…ÁÀ¹•Ğ ˆ½±¥™˜½µ¥É…Ñ”¹¡Ñµ°ˆ¤(€€€‘•˜±¥™™}µ¥É…Ñ¥½¹}¡…¹‘½™™}Á…” ¤è(€€€€€€€€ˆˆ‰1•…ä1%¡…¹‘½™˜Ñ¡…Ğ…Í­ÌÕÍ•ÉÌÑ¼•áÁ±¥¥Ñ±äÉ•…ÕÑ¡½É¥é”¸ˆˆˆ(€€€€€€€É•ÑÕÉ¸Í•¹‘}™É½µ}‘¥É•Ñ½Éä¡…ÁÀ¹ÍÑ…Ñ¥}™½±‘•È°€‰±¥™˜½µ¥É…Ñ”¹¡Ñµ°ˆ¤((€€€€Œ€ÈÀÈØ´ÀÜ´ÈÄÁ…Ñ €ÈĞè=¹‰½…É‘¥¹œƒšÖ¢,A$(€€€…ÁÀ¹•Ğ ˆ½±¥™˜½½¹‰½…É‘¥¹œˆ¤(€€€‘•˜±¥™™}½¹‰½…É‘¥¹œ ¤è(€€€€€€€É•ÑÕÉ¸}±¥™™}•µ‰•‘}É•‘¥É•Ğ¡½Á•¹}…Ñ¥½¸ô‰½¹‰½…É‘¥¹œˆ¤((€€€…ÁÀ¹•Ğ ˆ½…Á¤½½¹‰½…É‘¥¹œ½ÍÑ…Ñ”ˆ¤(€€€‘•˜½¹‰½…É‘¥¹}ÍÑ…Ñ•}…Á¤ ¤è(€€€€€€€€ˆˆ‹–>[–ú_’öÿR£¢½¹‰½…É‘¥¹œƒ.š,£–º#¢¶ß’êëšb¿–B›Ú–ºh€¬ƒš>C¦Kšf¦ZL§ˆˆˆ(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡íô°ÕÍ•}…ÉÌõQÉÕ”¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€‘…Ñ„°½‘”€ô½¹‰½…É‘¥¹}ÍÑ…ÑÕÍ}Á…å±½… (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€…±±½İ}µ¥ÍÍ¥¹}ÁÉ½™¥±”õQÉÕ”°(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½½¹‰½…É‘¥¹œ½É•µ¥¹‘•Èˆ¤(€€€‘•˜½¹‰½…É‘¥¹}É•µ¥¹‘•É}…Á¤ ¤è(€€€€€€€€ˆˆ‹¢¢·–ºk’öÿR£¢š¾?š^—š>C¦Kšf¦ZL£šR¿š>Ó–Z»’âš"[–’kšfšºÔ§ˆˆˆ(€€€€€€€‘…Ñ„€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡‘…Ñ„¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€É•ÍÕ±Ğ°½‘”€ôÕÁ‘…Ñ•}½¹‰½…É‘¥¹}É•µ¥¹‘•È (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥°‘…Ñ„(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡É•ÍÕ±Ğ¤°½‘”((€€€…ÁÀ¹•Ğ ˆ½±¥™˜½Õ…É‘¥…¸ˆ¤(€€€‘•˜±¥™™}Õ…É‘¥…¸ ¤è(€€€€€€€€ŒƒšÂã’æ–—–>š'šb¼±¥™˜¹±¥¹”¹µ—¾òoš¶“¢Ş¿–úG’şwVgnã–ºç¾ò3–Â;–BG–Ÿ–Ö0½¹‰½…É‘¥¹Ÿ¾ò#–º#¢¶ß’êëŠKš>C¦K¾ò$(€€€€€€€É•ÑÕÉ¸}±¥™™}•µ‰•‘}É•‘¥É•Ğ¡½Á•¹}…Ñ¥½¸ô‰½¹‰½…É‘¥¹œˆ¤((€€€…ÁÀ¹•Ğ ˆ½±¥™˜½µ•µ‰•Èˆ¤(€€€‘•˜±¥™™}µ•µ‰•È ¤è(€€€€€€€É•ÑÕÉ¸}±¥™™}•µ‰•‘}É•‘¥É•Ğ¡½Á•¹}…Ñ¥½¸ô‰µ•µ‰•Èˆ¤((€€€…ÁÀ¹•Ğ ˆ½±¥™˜½Õ…É‘¥…¸µÉ½ÕÁÌˆ¤(€€€‘•˜±¥™™}Õ…É‘¥…¹}É½ÕÁÌ ¤è(€€€€€€€É•ÑÕÉ¸}±¥™™}•µ‰•‘}É•‘¥É•Ğ¡½Á•¹}…Ñ¥½¸ô‰Õ…É‘¥…¹Ìˆ¤((€€€…ÁÀ¹•Ğ ˆ½…Á¤½½¹™¥œˆ¤(€€€‘•˜½¹™¥}…Á¤ ¤è(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡…ÁÁ}½¹™¥œ¡…ÁÀ¹½¹™¥œ¤¤((€€€…ÁÀ¹•Ğ ˆ½…Á¤½‰½Ğ½ÍÑ…ÑÕÌˆ¤(€€€‘•˜‰½Ñ}ÍÑ…ÑÕÍ}…Á¤ ¤è(€€€€€€€€ˆˆˆÈÀÈØ´ÀÜ´ÈÄÁ…Ñ €ÄÜè	½ĞƒšVÓ¦®S–—–êß.š,£Ö›¢fÇ¢Fr,§((€€€€€€€I•ÑÕÉ¹Ìè(€€€€€€€€€€€€´Í•ÉÙ¥”è…±¥Ù”µ¡•­¥¸(€€€€€€€€€€€€´‰½Ñ}¹…µ”èƒš¾?š^—–æÏ–º$(€€€€€€€€€€€€´ÕÁÑ¥µ•}Í•½¹‘Ìèƒ¦Ë¢/–V–.W–ú3KšVà(€€€€€€€€€€€€´ÕÍ•ÉÍ}Ñ½Ñ…°èƒ¢¢ï–+’êëšVà(€€€€€€€€€€€€´Õ…É‘¥…¹}É½ÕÁÍ}Ñ½Ñ…°èƒ–º#¢¶ßú“Ú–ºkâ÷šVà(€€€€€€€€€€€€´Õ…É‘¥…¹}É½ÕÁÍ}…Ñ¥Ù”èƒšr'šV#j–º#¢¶ßú“šVà(€€€€€€€€€€€€´Ñ¥µ•ÍÑ…µÀèƒVÛ’â/šf¦ZL(€€€€€€€€€€€€´±¥¹•}Ñ½­•¹}¡…Í}Ù…±Õ”€¼±¥¹•}Í•É•Ñ}¡…Í}Ù…±Õ”è•¹Øƒšb¿–B›šr'–ó¾ò#’â7–n{–
Ï–Ÿ–ºç¾ò$(€€€€€€€€€€€€´±¥¹•}Ñ½­•¹}½¬€¼±¥¹•}Ñ½­•¹}¡ÑÑÀèƒR €½ØÈ½‰½Ğ½¥¹™¼ƒš:‹šâ°Ñ½­•¸ƒšb¿–B›¢Š¬1%9ƒš:—–>\(€€€€€€€€ˆˆˆ(€€€€€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤(€€€€€€€É½ÕÁÌ€ôÍÑ…Ñ”¹•Ğ ‰Õ…É‘¥…¹}É½ÕÁÌˆ°íô¤(€€€€€€€…Ñ¥Ù•}É½ÕÁÌ€ôÍÕ´ Ä™½Èœ¥¸É½ÕÁÌ¹Ù…±Õ•Ì ¤¥˜œ¹•Ğ ‰ÍÑ…ÑÕÌˆ¤€ôô€‰…Ñ¥Ù”ˆ¤(€€€€€€€¹½Ü€ô‘…Ñ•Ñ¥µ”¹¹½Ü ¤(€€€€€€€ÁÉ½}ÍÑ…ÉĞ€ô•Ñ…ÑÑÈ¡…ÁÀ°€‰}ÍÑ…ÉÑ}Ñ¥µ”ˆ°9½¹”¤(€€€€€€€ÕÁÑ¥µ”€ô€¡¹½Ü€´ÁÉ½}ÍÑ…ÉĞ¤¹Ñ½Ñ…±}Í•½¹‘Ì ¤¥˜ÁÉ½}ÍÑ…ÉĞ•±Í”9½¹”(€€€€€€€Ñ½­•¸€ô€ (€€€€€€€€€€€…ÁÀ¹½¹™¥œ¹•Ğ ‰1%9}!991}MM}Q=-8ˆ¤(€€€€€€€€€€€½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}!991}MM}Q=-8ˆ¤(€€€€€€€€€€€½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰!991}MM}Q=-8ˆ¤(€€€€€€€€€€€½È€ˆˆ(€€€€€€€€¤¹ÍÑÉ¥À ¤(€€€€€€€Í•É•Ğ€ô€ (€€€€€€€€€€€…ÁÀ¹½¹™¥œ¹•Ğ ‰1%9}!991}MIPˆ¤(€€€€€€€€€€€½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}!991}MIPˆ¤(€€€€€€€€€€€½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰!991}MIPˆ¤(€€€€€€€€€€€½È€ˆˆ(€€€€€€€€¤¹ÍÑÉ¥À ¤(€€€€€€€±¥¹•}Ñ½­•¹}½¬€ô9½¹”(€€€€€€€±¥¹•}Ñ½­•¹}¡ÑÑÀ€ô9½¹”(€€€€€€€¥˜Ñ½­•¸è(€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€¥µÁ½ÉĞÕÉ±±¥ˆ¹É•ÅÕ•ÍĞ((€€€€€€€€€€€€€€€É•Ä€ôÕÉ±±¥ˆ¹É•ÅÕ•ÍĞ¹I•ÅÕ•ÍĞ (€€€€€€€€€€€€€€€€€€€€‰¡ÑÑÁÌè¼½…Á¤¹±¥¹”¹µ”½ØÈ½‰½Ğ½¥¹™¼ˆ°(€€€€€€€€€€€€€€€€€€€¡•…‘•ÉÌõì‰ÕÑ¡½É¥é…Ñ¥½¸ˆè˜‰	•…É•ÈíÑ½­•¹ô‰ô°(€€€€€€€€€€€€€€€€€€€µ•Ñ¡½ô‰Pˆ°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€İ¥Ñ ÕÉ±±¥ˆ¹É•ÅÕ•ÍĞ¹ÕÉ±½Á•¸¡É•Ä°Ñ¥µ•½ÕĞôà¤…ÌÉ•ÍÀè(€€€€€€€€€€€€€€€€€€€±¥¹•}Ñ½­•¹}¡ÑÑÀ€ô¥¹Ğ¡•Ñ…ÑÑÈ¡É•ÍÀ°€‰ÍÑ…ÑÕÌˆ°€ÈÀÀ¤½È€ÈÀÀ¤(€€€€€€€€€€€€€€€€€€€±¥¹•}Ñ½­•¹}½¬€ô±¥¹•}Ñ½­•¹}¡ÑÑÀ€ôô€ÈÀÀ(€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€€€€€½‘”€ô•Ñ…ÑÑÈ¡•Ñ…ÑÑÈ¡•áŒ°€‰½‘”ˆ°9½¹”¤°€‰É•…°ˆ°9½¹”¤½È•Ñ…ÑÑÈ¡•áŒ°€‰½‘”ˆ°9½¹”¤(€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€±¥¹•}Ñ½­•¹}¡ÑÑÀ€ô¥¹Ğ¡½‘”¤¥˜½‘”¥Ì¹½Ğ9½¹”•±Í”9½¹”(€€€€€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸è(€€€€€€€€€€€€€€€€€€€±¥¹•}Ñ½­•¹}¡ÑÑÀ€ô9½¹”(€€€€€€€€€€€€€€€±¥¹•}Ñ½­•¹}½¬€ô…±Í”(€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹İ…É¹¥¹œ (€€€€€€€€€€€€€€€€€€€€‰±¥¹”Ñ½­•¸ÁÉ½‰”™…¥±•¡ÑÑÀô•Ì•ÉÈô•Ìˆ°(€€€€€€€€€€€€€€€€€€€±¥¹•}Ñ½­•¹}¡ÑÑÀ°(€€€€€€€€€€€€€€€€€€€ÑåÁ”¡•áŒ¤¹}}¹…µ•}|°(€€€€€€€€€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì(€€€€€€€€€€€€‰Í•ÉÙ¥”ˆè€‰…±¥Ù”µ¡•­¥¸ˆ°(€€€€€€€€€€€€‰‰½Ñ}¹…µ”ˆè€‹š¾?š^—–æÏ–º$ˆ°(€€€€€€€€€€€€‰‘•Á±½å}Ù•ÉÍ¥½¸ˆè½Ì¹•¹Ù¥É½¸¹•Ğ ‰A1=e}YIM%=8ˆ¤½È€‰\ÈÔÀÜÈÕ ˆ°(€€€€€€€€€€€€‰ÕÁÑ¥µ•}Í•½¹‘ÌˆèÉ½Õ¹¡ÕÁÑ¥µ”°€Ä¤¥˜ÕÁÑ¥µ”•±Í”9½¹”°(€€€€€€€€€€€€‰ÕÍ•ÉÍ}Ñ½Ñ…°ˆè±•¸¡ÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ°íô¤¤°(€€€€€€€€€€€€‰Õ…É‘¥…¹}É½ÕÁÍ}Ñ½Ñ…°ˆè±•¸¡É½ÕÁÌ¤°(€€€€€€€€€€€€‰Õ…É‘¥…¹}É½ÕÁÍ}…Ñ¥Ù”ˆè…Ñ¥Ù•}É½ÕÁÌ°(€€€€€€€€€€€€‰Ñ¥µ•ÍÑ…µÀˆè¹½Ü¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤°(€€€€€€€€€€€€‰±¥¹•}Ñ½­•¹}¡…Í}Ù…±Õ”ˆè‰½½°¡Ñ½­•¸¤°(€€€€€€€€€€€€‰±¥¹•}Í•É•Ñ}¡…Í}Ù…±Õ”ˆè‰½½°¡Í•É•Ğ¤°(€€€€€€€€€€€€‰±¥¹•}Ñ½­•¹}½¬ˆè±¥¹•}Ñ½­•¹}½¬°(€€€€€€€€€€€€‰±¥¹•}Ñ½­•¹}¡ÑÑÀˆè±¥¹•}Ñ½­•¹}¡ÑÑÀ°(€€€€€€€ô¤((€€€…ÁÀ¹•Ğ ˆ½…Á¤½ÍÑ…ÑÕÌˆ¤(€€€‘•˜ÍÑ…ÑÕÌ ¤è(€€€€€€€€ˆˆ‰1%ƒ¦š[¢ò'¾òkšr'šr'šV#¢ê¯–"–ÂÄÕÁÍ•ÉÓ¾ò3¦ÿ–4ƒ¢Š¬•Á¡•µ•É…°‘¥Í¬ƒšâš:'–ú3–6„€ĞÀÓˆˆˆ(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡íô°ÕÍ•}…ÉÌõQÉÕ”¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€‘…Ñ„°½‘”€ôÍÑ…ÑÕÍ}™½É}ÕÍ•È (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€É•ÅÕ•ÍĞ¹…ÉÌ¹•Ğ ‰‘¥ÍÁ±…å}¹…µ”ˆ¤°(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½±¥¹”½É•¥ÍÑ•Èˆ¤(€€€‘•˜±¥¹•}É•¥ÍÑ•È ¤è(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€‘…Ñ„°½‘”€ôÉ•¥ÍÑ•É}±¥¹•}ÕÍ•È¡…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½‰•Ñ„½±…¥´ˆ¤(€€€‘•˜‰•Ñ…}±…¥µ}…Á¤ ¤è(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€½¡½ÉĞ€ôÍÑÈ¡Á…å±½…¹•Ğ ‰‰•Ñ…}½¡½ÉĞˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤¹ÕÁÁ•È ¤(€€€€€€€¥˜½¡½ÉĞ¹½Ğ¥¸ì‰Ìääˆ°€‰Üää‰ôè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰¥¹Ù…±¥‘}‰•Ñ…}±¥¹¬‰ô¤°€ĞÀÀ(€€€€€€€ÑÉäè(€€€€€€€€€€€É•ÍÕ±Ğ€ôµÕÑ…Ñ•}ÍÑ…Ñ•}…Ñ½µ¥…±±ä (€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€±…µ‰‘„ÍÑ…Ñ”è±…¥µ}‰•Ñ…}±¥¹¬¡ÍÑ…Ñ”°±¥¹•}ÕÍ•É}¥°½¡½ÉĞ¤°(€€€€€€€€€€€€¤(€€€€€€€•á•ÁĞY…±Õ•ÉÉ½È…Ì•áŒè(€€€€€€€€€€€É•…Í½¸€ôÍÑÈ¡•áŒ¤(€€€€€€€€€€€µ•ÍÍ…•Ì€ôì(€€€€€€€€€€€€€€€€‰½¡½ÉÑ}™Õ±°ˆè€‹¦g’âÖ–Âšâ³–B7¦†7–ŞËšîüˆ°(€€€€€€€€€€€€€€€€‰…±É•…‘å}¥¹}½Ñ¡•É}½¡½ÉĞˆè€‹’öƒ–ŞË–*ƒ–—–>›’â–/–Âšâ³Ö–"”ˆ°(€€€€€€€€€€€€€€€€‰µ•µ‰•É}¹½Ñ}™½Õ¹ˆè€‹¢®/–#–º3š"@1%9ƒšr–N‡¢¢ï–(ˆ°(€€€€€€€€€€€€€€€€‰™É••}•±¥¥‰¥±¥Ñå}…±É•…‘å}ÕÍ•ˆè€‹’öƒ–ŞË’öÿR£¦;–7¢Êï¦®S¦¦_š"[–Âšâ³¢Îš‚ğˆ°(€€€€€€€€€€€ô(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì(€€€€€€€€€€€€€€€€‰½¬ˆè…±Í”°(€€€€€€€€€€€€€€€€‰•ÉÉ½ÈˆèÉ•…Í½¸°(€€€€€€€€€€€€€€€€‰µ•ÍÍ…”ˆèµ•ÍÍ…•Ì¹•Ğ¡É•…Í½¸°€‹‡šÎW–*ƒ–—–Âšâ°ˆ¤°(€€€€€€€€€€€ô¤°€ĞÀä¥˜É•…Í½¸€„ô€‰µ•µ‰•É}¹½Ñ}™½Õ¹ˆ•±Í”€ĞÀĞ(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¬ˆèQÉÕ”°€¨©É•ÍÕ±Ñô¤°€ÈÀÀ((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½¡•­¥¸ˆ¤(€€€‘•˜¡•­¥¸ ¤è(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€É•ÍÕ±Ğ°½‘”€ô¡•­¥¹}™½É}ÕÍ•È (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥°Á…å±½…°…ÁÀ¹½¹™¥œ(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡É•ÍÕ±Ğ¤°½‘”((€€€…ÁÀ¹Á½ÍĞ ˆ½…±±‰…¬ˆ¤(€€€‘•˜±¥¹•}…±±‰…¬ ¤è(€€€€€€€¥˜1¥¹•	½ÑÁ¤¥Ì9½¹”½È]•‰¡½½­!…¹‘±•È¥Ì9½¹”è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰±¥¹”µ‰½ĞµÍ‘¬¥Ì¹½Ğ¥¹ÍÑ…±±•‰ô¤°€ÔÀÌ(€€€€€€€Ñ½­•¸€ô€ (€€€€€€€€€€€…ÁÀ¹½¹™¥œ¹•Ğ ‰1%9}!991}MM}Q=-8ˆ¤(€€€€€€€€€€€½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}!991}MM}Q=-8ˆ¤(€€€€€€€€€€€½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰!991}MM}Q=-8ˆ¤(€€€€€€€€€€€½È€ˆˆ(€€€€€€€€¤¹ÍÑÉ¥À ¤(€€€€€€€Í•É•Ğ€ô€ (€€€€€€€€€€€…ÁÀ¹½¹™¥œ¹•Ğ ‰1%9}!991}MIPˆ¤(€€€€€€€€€€€½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}!991}MIPˆ¤(€€€€€€€€€€€½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰!991}MIPˆ¤(€€€€€€€€€€€½È€ˆˆ(€€€€€€€€¤¹ÍÑÉ¥À ¤(€€€€€€€¥˜¹½ĞÑ½­•¸½È¹½ĞÍ•É•Ğè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰1%9É•‘•¹Ñ¥…±Ì…É”¹½Ğ½¹™¥ÕÉ•‰ô¤°€ÔÀÌ((€€€€€€€±¥¹•}‰½Ñ}…Á¤€ô1¥¹•	½ÑÁ¤¡Ñ½­•¸¤(€€€€€€€¡…¹‘±•È€ô]•‰¡½½­!…¹‘±•È¡Í•É•Ğ¤((€€€€€€€‘•˜}Í½Í}¡…¹‘±”¡±¥¹•}‰½Ñ}…Á¤°±¥¹•}ÕÍ•É}¥°½µµ…¹°É•Á±å}Ñ½­•¸õ9½¹”°É½ÕÁ}¥õ9½¹”¤è(€€€€€€€€€€€€ˆˆ‹¦r¢š–æ¯–şg¾òk¢+–’§–º“¦ê3Šë¢ª4€Ìƒš²‡–ú3¦–—–ÇR M=Lƒ’ê/’îÛ((€€€€€€€€€€€½µµ…¹è(€€€€€€€€€€€€€€´€Ÿ¦r¢š–æ¯–şdœ€¼€M=Lœ€¼€Í½Ìœ€¼€ŸŞ+š—šÆ–*¤œ€èƒÒ¿¢¢#’âš²‡Šë¢ª4(€€€€€€€€€€€€€€´€Ÿ–>[šÚ#¦r¢š–æ¯–şdœ€¼€M=Lƒ–>[šÚ œ€èƒ–>[šÚ Á•¹‘¥¹œ(€€€€€€€€€€€€ˆˆˆ(€€€€€€€€€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤(€€€€€€€€€€€ÁÉ½™¥±”€ô•Ñ}ÁÉ½™¥±”¡ÍÑ…Ñ”°±¥¹•}ÕÍ•É}¥¤¥˜±¥¹•}ÕÍ•É}¥•±Í”9½¹”(€€€€€€€€€€€…ÁÀ¹±½•È¹¥¹™¼ (€€€€€€€€€€€€€€€€‰Í½Í}¡…¹‘±”½µµ…¹ô•ÌÕÍ•Èô•ÌÉ½ÕÀô•Ìˆ°(€€€€€€€€€€€€€€€½µµ…¹°(€€€€€€€€€€€€€€€€¡±¥¹•}ÕÍ•É}¥½È€ˆˆ¥lèát°(€€€€€€€€€€€€€€€€¡É½ÕÁ}¥½È€ˆˆ¥lèát°(€€€€€€€€€€€€¤((€€€€€€€€€€€‘•˜É•Á±ä¡™±•à°…±Ñ}Ñ•áĞôˆˆ¤è(€€€€€€€€€€€€€€€µ•ÍÍ…•Ì€ômt(€€€€€€€€€€€€€€€¥˜±•áM•¹‘5•ÍÍ…”¥Ì¹½Ğ9½¹”…¹™±•à¥Ì¹½Ğ9½¹”è(€€€€€€€€€€€€€€€€€€€µ•ÍÍ…•Ì¹…ÁÁ•¹¡±•áM•¹‘5•ÍÍ…”¡…±Ñ}Ñ•áĞõ…±Ñ}Ñ•áĞ°½¹Ñ•¹ÑÌõ™±•à¤¤(€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€µ•ÍÍ…•Ì¹…ÁÁ•¹¡Q•áÑM•¹‘5•ÍÍ…”¡Ñ•áĞõ…±Ñ}Ñ•áĞ½È€‹¦r¢š–æ¯–şdˆ¤¤(€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€¥˜É•Á±å}Ñ½­•¸è(€€€€€€€€€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹É•Á±å}µ•ÍÍ…”¡É•Á±å}Ñ½­•¸°µ•ÍÍ…•Ì¤(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸(€€€€€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹•á•ÁÑ¥½¸ ‰Í½ÌÉ•Á±å}µ•ÍÍ…”™…¥±•è€•Ìˆ°•áŒ¤(€€€€€€€€€€€€€€€€ŒÉ•Á±å}Ñ½­•¸ƒ–’ÇšV_š"[šr«š>C’úlƒŠHÁÕÍ ƒ–"Ã–B3’â–/–Â7¢¦Ä(€€€€€€€€€€€€€€€ÁÕÍ¡}Ñ…É•Ğ€ôÉ½ÕÁ}¥½È±¥¹•}ÕÍ•É}¥(€€€€€€€€€€€€€€€¥˜¹½ĞÁÕÍ¡}Ñ…É•Ğè(€€€€€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹•ÉÉ½È ‰Í½ÌÍ•¹…‰½ÉÑ•è¹¼ÁÕÍ Ñ…É•Ğˆ¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸(€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹ÁÕÍ¡}µ•ÍÍ…”¡ÁÕÍ¡}Ñ…É•Ğ°µ•ÍÍ…•Ì¤(€€€€€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹•á•ÁÑ¥½¸ ‰Í½ÌÁÕÍ¡}µ•ÍÍ…”™…¥±•è€•Ìˆ°•áŒ¤((€€€€€€€€€€€•¹ÑÉå}½µµ…¹‘Ì€ô€ ‹¦r¢š–æ¯–şdˆ°€‰M=Lˆ°€‰Í½Ìˆ°€‹Ş+š—šÆ–*¤ˆ¤(€€€€€€€€€€€€Œƒ–ŞË¦–"Ã¢+–’§–º“j¢"(±•àƒš2'¦"W‡šÎW–n{šRÛ¾òo’şwVg–ÛšZ–¶_–F÷’î“¾ò0(€€€€€€€€€€€€Œƒ’ö’â–ú/–>«–n{šZÃ& 1%ƒ–—–>¾ò3’â7–7–V–.W¢"+j¢+–’§.š/š¦(€€€€€€€€€€€±•…å}•¹ÑÉå}½µµ…¹‘Ì€ô€ (€€€€€€€€€€€€€€€€‹¦k~—–ºÛ’êèˆ°(€€€€€€€€€€€€€€€€‹¢¿Ö‡–ºÛ’êë¦š2$Ïš²„ˆ°(€€€€€€€€€€€€€€€€‹¦r¢š–æ¯–şgŠë¢ª4ˆ°(€€€€€€€€€€€€€€€€‰M=LƒŠë¢ª4€Èˆ°(€€€€€€€€€€€€€€€€‰M=LƒŠë¢ª4€Ìˆ°(€€€€€€€€€€€€¤(€€€€€€€€€€€…¹•±}½µµ…¹‘Ì€ô€ ‰M=Lƒ–>[šÚ ˆ°€‹–>[šÚ#¦r¢š–æ¯–şdˆ¤((€€€€€€€€€€€¥˜½µµ…¹¥¸…¹•±}½µµ…¹‘Ìè(€€€€€€€€€€€€€€€¥˜Í½Í}™±½Ü¹Í½Í}…¹•±}Á•¹‘¥¹œ¡ÍÑ…Ñ”°±¥¹•}ÕÍ•É}¥¤è(€€€€€€€€€€€€€€€€€€€Í…Ù•}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t°ÍÑ…Ñ”¤(€€€€€€€€€€€€€€€€€€€É•Á±ä¡Í½Í}™±½Ü¹Í½Í}…¹•±±•‘}™±•à ¤°€‹Šrƒ–ŞË–>[šÚ#¦r¢š–æ¯–şdˆ¤(€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€É•Á±ä¡9½¹”°€‹šÊKšr'–ú–>[šÚ#j¦r¢š–æ¯–şg¦k~”ˆ¤(€€€€€€€€€€€€€€€É•ÑÕÉ¸((€€€€€€€€€€€€Œƒ¢+–’§–º“’şwVg¦ê0€Ìƒš²‡Šë¢ª7¾òo–r[šZ¦ã–Z»–&¦Z,1%ƒj–B3’â––\€Ìƒš²‡šÖ¢/(€€€€€€€€€€€¥˜½µµ…¹¥¸•¹ÑÉå}½µµ…¹‘Ì½È½µµ…¹¥¸±•…å}•¹ÑÉå}½µµ…¹‘Ìè(€€€€€€€€€€€€€€€Ñ…À€ôÍ½Í}™±½Ü¹Í½Í}Ñ…À¡ÍÑ…Ñ”°±¥¹•}ÕÍ•É}¥¤(€€€€€€€€€€€€€€€½Õ¹Ğ€ô¥¹Ğ ¡Ñ…À¹•Ğ ‰•¹ÑÉäˆ¤½Èíô¤¹•Ğ ‰Ñ…Á}½Õ¹Ğˆ¤½È€Ä¤(€€€€€€€€€€€€€€€Í…Ù•}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t°ÍÑ…Ñ”¤(€€€€€€€€€€€€€€€¥˜½Õ¹Ğ€ğ€Ìè(€€€€€€€€€€€€€€€€€€€É•Á±ä (€€€€€€€€€€€€€€€€€€€€€€€Í½Í}™±½Ü¹Í½Í}İ…É¹¥¹}™±•à¡½Õ¹Ğ¤°(€€€€€€€€€€€€€€€€€€€€€€€˜‹Â~`ƒ¦r¢š–æ¯–şgŠë¢ª4í½Õ¹Ñô¼Ìˆ°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸(€€€€€€€€€€€€€€€É•ÍÕ±Ğ°ÍÑ…ÑÕÍ}½‘”€ôÑÉ¥•É}Í½Ì (€€€€€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€€€€€ì‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥‘ô°(€€€€€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥œ°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€¥˜ÍÑ…ÑÕÍ}½‘”€ôô€ÈÀÀè(€€€€€€€€€€€€€€€€€€€±…Ñ•ÍĞ€ô±½…‘}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤(€€€€€€€€€€€€€€€€€€€Í½Í}™±½Ü¹Í½Í}µ…É­}Í•¹Ğ (€€€€€€€€€€€€€€€€€€€€€€€±…Ñ•ÍĞ°±¥¹•}ÕÍ•É}¥°É•ÍÕ±Ğ¹•Ğ ‰•Ù•¹Ñ}¥ˆ¤(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€Í…Ù•}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t°±…Ñ•ÍĞ¤(€€€€€€€€€€€€€€€€€€€É•Á±ä (€€€€€€€€€€€€€€€€€€€€€€€Í½Í}™±½Ü¹Í½Í}Í•¹Ñ}™±•à ¤°(€€€€€€€€€€€€€€€€€€€€€€€˜‹Â~j M=Lƒ–ŞË¦–ë¾ò3–ŞË¦k~”í¥¹Ğ¡É•ÍÕ±Ğ¹•Ğ Í•¹Ğœ¤½È€À¥ôƒ–/–Â7¢Æ„ˆ°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€•±¥˜ÍÑÈ¡É•ÍÕ±Ğ¹•Ğ ‰•ÉÉ½Èˆ¤½È€ˆˆ¤€ôô€‰¹¼‰½Õ¹1%9Õ…É‘¥…¹Ìˆè(€€€€€€€€€€€€€€€€€€€É•Á±ä (€€€€€€€€€€€€€€€€€€€€€€€Í½Í}™±½Ü¹Í½Í}¹½}Õ…É‘¥…¹Í}™±•à ¤°(€€€€€€€€€€€€€€€€€€€€€€€Í½Í}ÕÍ•É}™…¥¹}•ÉÉ½È¡É•ÍÕ±Ğ¹•Ğ ‰•ÉÉ½Èˆ¤¤°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€É•Á±ä¡9½¹”°Í½Í}ÕÍ•É}™…¥¹}•ÉÉ½È¡É•ÍÕ±Ğ¹•Ğ ‰•ÉÉ½Èˆ¤¤¤(€€€€€€€€€€€€€€€É•ÑÕÉ¸((€€€€€€€€€€€¥˜½µµ…¹¹½Ğ¥¸•¹ÑÉå}½µµ…¹‘Ì…¹½µµ…¹¹½Ğ¥¸±•…å}•¹ÑÉå}½µµ…¹‘Ìè(€€€€€€€€€€€€€€€É•Á±ä¡9½¹”°€‹¢®/–
Ï¦3¦r¢š–æ¯–şg7¦Z/–VšÆ–*§¦ã¦‚ˆ¤(€€€€€€€€€€€€€€€É•ÑÕÉ¸((€€€€€€€‘•˜}Í•¹‘}İ•±½µ”¡±¥¹•}‰½Ñ}…Á¤°É•Á±å}Ñ½­•¸õ9½¹”°±¥¹•}ÕÍ•É}¥õ9½¹”°‘¥ÍÁ±…å}¹…µ”õ9½¹”°ÑÉ¥•Èõ9½¹”¤è(€€€€€€€€€€€€ˆˆ‰½±±½Ü€¼ƒ¦^s¦6×–¶_–ÇR£¾òk¦İ•±½µ•}™±•ã¾ò3–’ÇšV_–¾¬±½œƒ’â˜ÁÕÍ ™…±±‰…¯ˆˆˆ(€€€€€€€€€€€€Œƒš¾?š²‡fó¦–&7–7–>[’âš²‡r–¾›šjÇ¢Ç¾ò#¦ÿ–4½±±½ÜƒVÛ’â,ÁÉ½™¥±”ƒ–’ÇšV_¢º+š"C¦ëf÷¾ò?3š
£7¾ò$(€€€€€€€€€€€É•Í½±Ù•€ôÉ•Í½±Ù•}İ•±½µ•}‘¥ÍÁ±…å}¹…µ” (€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤õ±¥¹•}‰½Ñ}…Á¤°(€€€€€€€€€€€€€€€‘…Ñ…}™¥±”õ…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥õ±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€¡¥¹Ğõ‘¥ÍÁ±…å}¹…µ”°(€€€€€€€€€€€€€€€±½•Èõ…ÁÀ¹±½•È°(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜İ•±½µ•}É••Ñ¥¹}Ñ•áĞ¥Ì¹½Ğ9½¹”è(€€€€€€€€€€€€€€€É••Ñ¥¹œ€ôİ•±½µ•}É••Ñ¥¹}Ñ•áĞ¡É•Í½±Ù•¤(€€€€€€€€€€€•±¥˜É•Í½±Ù•è(€€€€€€€€€€€€€€€É••Ñ¥¹œ€ô˜‹Â~F,íÉ•Í½±Ù•‘ôƒš
£––÷¾ò3š¶‡¢ş;–*ƒ–—3š¾?š^—–æÏ–º'4ˆ(€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€É••Ñ¥¹œ€ô€‹Â~F,ƒš
£––÷¾ò3š¶‡¢ş;–*ƒ–—3š¾?š^—–æÏ–º'4ˆ(€€€€€€€€€€€…ÁÀ¹±½•È¹¥¹™¼ (€€€€€€€€€€€€€€€€‰İ•±½µ•}™±•àÍÑ…ÉĞÑÉ¥•Èô•ÌÕÍ•Èô•Ì¹…µ”ô•È¡…Í}É•Á±äô•Ìˆ°(€€€€€€€€€€€€€€€ÑÉ¥•È½È€‰Õ¹­¹½İ¸ˆ°(€€€€€€€€€€€€€€€€¡±¥¹•}ÕÍ•É}¥½È€ˆˆ¥lèát°(€€€€€€€€€€€€€€€É•Í½±Ù•½È€ˆˆ°(€€€€€€€€€€€€€€€‰½½°¡É•Á±å}Ñ½­•¸¤°(€€€€€€€€€€€€¤(€€€€€€€€€€€Í•ÑÕÁ}ÕÉ¤€ô€ (€€€€€€€€€€€€€€€±¥™™}•¹ÑÉå}ÕÉ°¡½Á•¹}…Ñ¥½¸ô‰½¹‰½…É‘¥¹œˆ¤(€€€€€€€€€€€€€€€¥˜±¥™™}•¹ÑÉå}ÕÉ°(€€€€€€€€€€€€€€€•±Í”€‰¡ÑÑÁÌè¼½±¥™˜¹±¥¹”¹µ”¼ÈÀÄÀàĞàÌÌÀµU¥ÅAAeı½Á•¸õ½¹‰½…É‘¥¹œˆ(€€€€€€€€€€€€¤(€€€€€€€€€€€¥¹Ù¥Ñ•}ÕÉ¤€ô€ (€€€€€€€€€€€€€€€Í¡…É•}¥¹Ù¥Ñ•}±¥™™}ÕÉ° ¤(€€€€€€€€€€€€€€€¥˜Í¡…É•}¥¹Ù¥Ñ•}±¥™™}ÕÉ°(€€€€€€€€€€€€€€€•±Í”€‰¡ÑÑÁÌè¼½±¥™˜¹±¥¹”¹µ”¼ÈÀÄÀàĞàÌÌÀµU¥ÅAAe½±¥™˜½Í¡…É”µ¥¹Ù¥Ñ”¹¡Ñµ°ˆ(€€€€€€€€€€€€¤(€€€€€€€€€€€¡•±Á}ÕÉ¤€ô€ (€€€€€€€€€€€€€€€±¥™™}•¹ÑÉå}ÕÉ°¡½Á•¹}…Ñ¥½¸ô‰¡•±Àˆ¤(€€€€€€€€€€€€€€€¥˜±¥™™}•¹ÑÉå}ÕÉ°(€€€€€€€€€€€€€€€•±Í”€‰¡ÑÑÁÌè¼½±¥™˜¹±¥¹”¹µ”¼ÈÀÄÀàĞàÌÌÀµU¥ÅAAeı½Á•¸õ¡•±Àˆ(€€€€€€€€€€€€¤(€€€€€€€€€€€İ•±½µ•}™…±±‰…¬€ô€ (€€€€€€€€€€€€€€€˜‰íÉ••Ñ¥¹õq¹q¸ˆ(€€€€€€€€€€€€€€€€‹š¾?–’¤€ÄÀƒK¾ò3–‚Ç–/–æÏ–º%q¸ˆ(€€€€€€€€€€€€€€€€‹–æÏ–âã’â7š&OšNû¾ò3šr'’ê/š&7¦k~—–º#¢¶ß’êéq¹q¸ˆ(€€€€€€€€€€€€€€€€‹¦Z/–/’öÿR£–&7–§–/š¶—¦¦¾òiq¸ˆ(€€€€€€€€€€€€€€€€‹ŠF€ƒšZÃ–Šx€Äƒ’ö7–º#¢¶ß’êéq¸ˆ(€€€€€€€€€€€€€€€€‹ŠF„ƒ¢¢·–ºkš¾?š^—š>C¦Kšf¦ZMq¹q¸ˆ(€€€€€€€€€€€€€€€€‹Â~:ƒ¦š[š²‡¢¢ï–+–>¿’ê¯’âš²„€ÄĞƒ–’§–º'–ş¦®S¦¦]q¸ˆ(€€€€€€€€€€€€€€€€‹Ş+š—.šÎ¢®/nÓš:—šJ—š&L€ÄÄäƒš"X€ÄÄÁq¹q¸ˆ(€€€€€€€€€€€€€€€˜‹–7¢Êï¦®S¦¦\€ÄĞƒ–’§¾òiíÍ•ÑÕÁ}ÕÉ¥õq¸ˆ(€€€€€€€€€€€€€€€˜‹’â¦6×–º#¢¶ß¦
¢®/¾òií¥¹Ù¥Ñ•}ÕÉ¥õq¸ˆ(€€€€€€€€€€€€€€€˜‹’ê¢š¾?š^—–æÏ–º'¾òií¡•±Á}ÕÉ¥õq¸ˆ(€€€€€€€€€€€€€€€€‹–
Ï3¦Z/–/7–>¿¦7š.ÿš¶‡¢ş;–6„ˆ(€€€€€€€€€€€€¤(€€€€€€€€€€€…±Ñ}Ñ•áĞ€ô€ (€€€€€€€€€€€€€€€˜‹š¾?š^—–æÏ–º'¾öqíÉ•Í½±Ù•‘ôƒš
£––÷¾ò3š¶‡¢ş;–*ƒ–”ˆ(€€€€€€€€€€€€€€€¥˜É•Í½±Ù•(€€€€€€€€€€€€€€€•±Í”€‹š¾?š^—–æÏ–º'¾ösš
£––÷¾ò3š¶‡¢ş;–*ƒ–”ˆ(€€€€€€€€€€€€¤(€€€€€€€€€€€™±•á}½¹Ñ•¹ÑÌ€ôİ•±½µ•}™±•à¡É•Í½±Ù•¤¥˜İ•±½µ•}™±•à¥Ì¹½Ğ9½¹”•±Í”9½¹”(€€€€€€€€€€€¥˜™±•á}½¹Ñ•¹ÑÌ¥Ì9½¹”è(€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹•ÉÉ½È ‰İ•±½µ•}™±•à½¹Ñ•¹ÑÌ¥Ì9½¹”ƒŠP¡•¬¥µÁ½ÉĞˆ¤(€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€¥˜±•áM•¹‘5•ÍÍ…”¥Ì¹½Ğ9½¹”…¹™±•á}½¹Ñ•¹ÑÌ¥Ì¹½Ğ9½¹”…¹É•Á±å}Ñ½­•¸è(€€€€€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹É•Á±å}µ•ÍÍ…” (€€€€€€€€€€€€€€€€€€€€€€€É•Á±å}Ñ½­•¸°(€€€€€€€€€€€€€€€€€€€€€€€±•áM•¹‘5•ÍÍ…”¡…±Ñ}Ñ•áĞõ…±Ñ}Ñ•áĞ°½¹Ñ•¹ÑÌõ™±•á}½¹Ñ•¹ÑÌ¤°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹¥¹™¼ ‰İ•±½µ•}™±•àÉ•Á±ä½¬¹…µ”ô•Èˆ°É•Í½±Ù•½È€ˆˆ¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸(€€€€€€€€€€€€€€€¥˜É•Á±å}Ñ½­•¸è(€€€€€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹É•Á±å}µ•ÍÍ…”¡É•Á±å}Ñ½­•¸°Q•áÑM•¹‘5•ÍÍ…”¡Ñ•áĞõİ•±½µ•}™…±±‰…¬¤¤(€€€€€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹İ…É¹¥¹œ ‰İ•±½µ”Ñ•áĞÉ•Á±ä™…±±‰…¬ˆ¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸(€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹•á•ÁÑ¥½¸ ‰İ•±½µ”É•Á±ä™…¥±•è€•Ìˆ°•áŒ¤(€€€€€€€€€€€¥˜±¥¹•}ÕÍ•É}¥…¹±•áM•¹‘5•ÍÍ…”¥Ì¹½Ğ9½¹”…¹™±•á}½¹Ñ•¹ÑÌ¥Ì¹½Ğ9½¹”è(€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹ÁÕÍ¡}µ•ÍÍ…” (€€€€€€€€€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€€€€€€€€€±•áM•¹‘5•ÍÍ…”¡…±Ñ}Ñ•áĞõ…±Ñ}Ñ•áĞ°½¹Ñ•¹ÑÌõ™±•á}½¹Ñ•¹ÑÌ¤°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹¥¹™¼ ‰İ•±½µ•}™±•àÁÕÍ ½¬¹…µ”ô•Èˆ°É•Í½±Ù•½È€ˆˆ¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸(€€€€€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹•á•ÁÑ¥½¸ ‰İ•±½µ”ÁÕÍ ™±•à™…¥±•è€•Ìˆ°•áŒ¤(€€€€€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€€€€€€Œ…ÁÑÕÉ”•á…Ğ1%9•ÉÉ½È‰½‘äİ¡•¸…Ù…¥±…‰±”(€€€€€€€€€€€€€€€€€€€€€€€•ÉÉ}‰½‘ä€ô•Ñ…ÑÑÈ¡•áŒ°€‰•ÉÉ½Èˆ°9½¹”¤½È•Ñ…ÑÑÈ¡•áŒ°€‰É•ÍÁ½¹Í”ˆ°9½¹”¤(€€€€€€€€€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹•ÉÉ½È ‰İ•±½µ”ÁÕÍ ™±•à1%9‘•Ñ…¥°è€•Ìˆ°•ÉÉ}‰½‘ä¤(€€€€€€€€€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸è(€€€€€€€€€€€€€€€€€€€€€€€Á…ÍÌ(€€€€€€€€€€€¥˜±¥¹•}ÕÍ•É}¥è(€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹ÁÕÍ¡}µ•ÍÍ…”¡±¥¹•}ÕÍ•É}¥°Q•áÑM•¹‘5•ÍÍ…”¡Ñ•áĞõİ•±½µ•}™…±±‰…¬¤¤(€€€€€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹İ…É¹¥¹œ ‰İ•±½µ”Ñ•áĞÁÕÍ ™…±±‰…¬ˆ¤(€€€€€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹•á•ÁÑ¥½¸ ‰İ•±½µ”ÁÕÍ Ñ•áĞ™…¥±•è€•Ìˆ°•áŒ¤((€€€€€€€‘•˜}Õ…É‘¥…¹}¥¹ÑÉ½}µ•ÍÍ…•Ì¡½İ¹•É}¥¹™¼°¡¥¹Ñ}Ñ•áĞõ9½¹”¤è(€€€€€€€€€€€€ˆˆ‹¦Ëú“š¶‡¢ş;¾òk~·šZ–¶\€¬±•ã¾ò#¦ng’şw¦j«¾ò3¦ÿ–4±•àƒ¢Š¯š.KšfšVÓšº×šÚ#–’Ç¾ò'ˆˆˆ(€€€€€€€€€€€Ñ¥À€ô¡¥¹Ñ}Ñ•áĞ½È€ (€€€€€€€€€€€€€€€€‹Â~n‡¾â<ƒš¶‡¢ş;–*ƒ–—3š¾?š^—–æÏ–º'7–º#¢¶ßú‘q¸ˆ(€€€€€€€€€€€€€€€€‹–æÏšf’â7š&OšNû¾ò3–>«–r£¦r¢ššf¦k~—–’Ÿ–ºÛˆ(€€€€€€€€€€€€¤(€€€€€€€€€€€µ•ÍÍ…•Ì€ômQ•áÑM•¹‘5•ÍÍ…”¡Ñ•áĞõÑ¥À¥t(€€€€€€€€€€€¥˜±•áM•¹‘5•ÍÍ…”¥Ì¹½Ğ9½¹”…¹Õ…É‘¥…¹}É½ÕÁ}¥¹ÑÉ½}™±•à¥Ì¹½Ğ9½¹”è(€€€€€€€€€€€€€€€µ•ÍÍ…•Ì¹…ÁÁ•¹ (€€€€€€€€€€€€€€€€€€€±•áM•¹‘5•ÍÍ…” (€€€€€€€€€€€€€€€€€€€€€€€…±Ñ}Ñ•áĞô‹Â~n‡¾â<ƒš¶‡¢ş;–*ƒ–—3š¾?š^—–æÏ–º'7–º#¢¶ßúˆ°(€€€€€€€€€€€€€€€€€€€€€€€½¹Ñ•¹ÑÌõÕ…É‘¥…¹}É½ÕÁ}¥¹ÑÉ½}™±•à¡½İ¹•É}¥¹™¼¤°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€É•ÑÕÉ¸µ•ÍÍ…•Ì((€€€€€€€‘•˜}É•Á±å}µ¥É…Ñ•‘}…½Õ¹Ğ¡É•Á±å}Ñ½­•¸°É•¥ÍÑÉ…Ñ¥½¹}É•ÍÕ±Ğ¤è(€€€€€€€€€€€Õ¥‘…¹”€ôµ¥É…Ñ•‘}…½Õ¹Ñ}İ•‰¡½½­}Õ¥‘…¹” (€€€€€€€€€€€€€€€É•¥ÍÑÉ…Ñ¥½¹}É•ÍÕ±Ğ°(€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥œ¹•Ğ ‰1%}%ˆ¤½ÈU1Q}1%}%°(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜¹½ĞÕ¥‘…¹”è(€€€€€€€€€€€€€€€É•ÑÕÉ¸…±Í”(€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹É•Á±å}µ•ÍÍ…” (€€€€€€€€€€€€€€€€€€€É•Á±å}Ñ½­•¸°(€€€€€€€€€€€€€€€€€€€Q•áÑM•¹‘5•ÍÍ…”¡Ñ•áĞõÕ¥‘…¹”¤°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹•á•ÁÑ¥½¸ (€€€€€€€€€€€€€€€€€€€€‰µ¥É…Ñ•…½Õ¹ĞÕ¥‘…¹”É•Á±ä™…¥±•è€•Ìˆ°•áŒ(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€É•ÑÕÉ¸QÉÕ”((€€€€€€€‘•˜}•¹É¥¡}‰¥¹‘}É•ÍÕ±Ñ}™½É}™±•à¡É•ÍÕ±Ğ°±¥¹•}ÕÍ•É}¥¤è(€€€€€€€€€€€€ˆˆ‹¢s’â+¢Î¢¢+–6‡¾òkº‡B’êë¾ò?š‚ã–ş–º#¢¶ß’êë¾ò?Ş+š—¢¿Ö‡’êë¾ò?ú“Öš"C–N‡¾ò?š>C¦Kšf¦ZOˆˆˆ(€€€€€€€€€€€•¹É¥¡•€ô‘¥Ğ¡É•ÍÕ±Ğ½Èíô¤(€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤(€€€€€€€€€€€€€€€ÁÉ½™¥±”€ô•Ñ}ÁÉ½™¥±”¡ÍÑ…Ñ”°±¥¹•}ÕÍ•É}¥¤½Èíô(€€€€€€€€€€€€€€€ÉÕ±•Ì€ôÁ±…¹}ÉÕ±•Ì¡ÁÉ½™¥±”¤(€€€€€€€€€€€€€€€Ñ¥µ•Ì€ôÉ•µ¥¹‘•É}Ñ¥µ•Í}™½É}ÁÉ½™¥±”¡ÁÉ½™¥±”¤½ÈlˆÀäèÀÀ‰t(€€€€€€€€€€€€€€€½¹Ñ…ÑÌ€ôÁÉ½™¥±”¹•Ğ ‰½¹Ñ…ÑÌˆ¤½Èmt(€€€€€€€€€€€€€€€€Œƒ–ŞËÚ–ºkš‚ã–ş–º#¢¶ß’êèƒŠ&€ƒú“Öš"C–N„ƒŠ&€ƒŞ+š—¢¿Ö‡’êë¾òo–>«R ½É”ƒ–B7¦†4(€€€€€€€€€€€€€€€Õ…É‘¥…¹}½Õ¹Ğ€ôÍÕ´ (€€€€€€€€€€€€€€€€€€€€Ä(€€€€€€€€€€€€€€€€€€€™½ÈŒ¥¸½¹Ñ…ÑÌ(€€€€€€€€€€€€€€€€€€€¥˜É•Í½±Ù•}½¹Ñ…Ñ}É½±”¡Œ¤€„ô€‰•µ•É•¹äˆ(€€€€€€€€€€€€€€€€€€€…¹½¹Ñ…Ñ}¥Í}‰½Õ¹‘}Õ…É‘¥…¸¡Œ°±¥¹•}ÕÍ•É}¥¤(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€•µ•É•¹å}½Õ¹Ğ€ôÍÕ´ (€€€€€€€€€€€€€€€€€€€€Ä™½ÈŒ¥¸½¹Ñ…ÑÌ¥˜É•Í½±Ù•}½¹Ñ…Ñ}É½±”¡Œ¤€ôô€‰•µ•É•¹äˆ(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€•¹É¥¡•¹Í•Ñ‘•™…Õ±Ğ (€€€€€€€€€€€€€€€€€€€€‰‘¥ÍÁ±…å}¹…µ”ˆ°(€€€€€€€€€€€€€€€€€€€€¡ÁÉ½™¥±”¹•Ğ ‰‘¥ÍÁ±…å}¹…µ”ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤½È€‹º‡B–N„ˆ°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€•¹É¥¡•¹Í•Ñ‘•™…Õ±Ğ ‰Õ…É‘¥…¹}½Õ¹Ğˆ°Õ…É‘¥…¹}½Õ¹Ğ¤(€€€€€€€€€€€€€€€•¹É¥¡•¹Í•Ñ‘•™…Õ±Ğ (€€€€€€€€€€€€€€€€€€€€‰Õ…É‘¥…¹}±¥µ¥Ğˆ°(€€€€€€€€€€€€€€€€€€€¥¹Ğ¡ÉÕ±•Ì¹•Ğ ‰½É•}Õ…É‘¥…¹}…±•ÉÑ}±¥µ¥Ğˆ¤½È€Ô¤°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€•¹É¥¡•¹Í•Ñ‘•™…Õ±Ğ ‰½É•}Õ…É‘¥…¹}…±•ÉÑ}±¥µ¥Ğˆ°¥¹Ğ¡ÉÕ±•Ì¹•Ğ ‰½É•}Õ…É‘¥…¹}…±•ÉÑ}±¥µ¥Ğˆ¤½È€Ô¤¤(€€€€€€€€€€€€€€€•¹É¥¡•¹Í•Ñ‘•™…Õ±Ğ ‰•µ•É•¹å}½Õ¹Ğˆ°•µ•É•¹å}½Õ¹Ğ¤(€€€€€€€€€€€€€€€•¹É¥¡•¹Í•Ñ‘•™…Õ±Ğ (€€€€€€€€€€€€€€€€€€€€‰•µ•É•¹å}±¥µ¥Ğˆ°(€€€€€€€€€€€€€€€€€€€¥¹Ğ¡ÉÕ±•Ì¹•Ğ ‰•µ•É•¹å}½¹Ñ…Ñ}±¥µ¥Ğˆ¤½È€È¤°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€•¹É¥¡•¹Í•Ñ‘•™…Õ±Ğ (€€€€€€€€€€€€€€€€€€€€‰•µ•É•¹å}½¹Ñ…Ñ}±¥µ¥Ğˆ°(€€€€€€€€€€€€€€€€€€€¥¹Ğ¡ÉÕ±•Ì¹•Ğ ‰•µ•É•¹å}½¹Ñ…Ñ}±¥µ¥Ğˆ¤½È€È¤°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€•¹É¥¡•¹Í•Ñ‘•™…Õ±Ğ ‰É•µ¥¹‘•É}Ñ¥µ”ˆ°ÍÑÈ¡Ñ¥µ•ÍlÁt¥˜Ñ¥µ•Ì•±Í”€ˆÀäèÀÀˆ¤¤(€€€€€€€€€€€€€€€•¹É¥¡•¹Í•Ñ‘•™…Õ±Ğ ‰É•µ¥¹‘•É}Ñ¥µ•Ìˆ°±¥ÍĞ¡Ñ¥µ•Ì¤¤(€€€€€€€€€€€€€€€É½ÕÁ}¥€ô•¹É¥¡•¹•Ğ ‰É½ÕÁ}¥ˆ¤(€€€€€€€€€€€€€€€¥˜É½ÕÁ}¥è(€€€€€€€€€€€€€€€€€€€É•™É•Í¡•€ôÉ•™É•Í¡}Õ…É‘¥…¹}É½ÕÁ}µ•µ‰•É}Í¹…ÁÍ¡½Ğ (€€€€€€€€€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°É½ÕÁ}¥(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€¥˜É•™É•Í¡•…¹É•™É•Í¡•¹•Ğ ‰µ•µ‰•É}½Õ¹Ñ}…Ñ}‰¥¹ˆ¤¥Ì¹½Ğ9½¹”è(€€€€€€€€€€€€€€€€€€€€€€€•¹É¥¡•‘l‰µ•µ‰•É}½Õ¹Ğ‰t€ôÉ•™É•Í¡•¹•Ğ ‰µ•µ‰•É}½Õ¹Ñ}…Ñ}‰¥¹ˆ¤(€€€€€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€€€€€œ€ô€¡ÍÑ…Ñ”¹•Ğ ‰Õ…É‘¥…¹}É½ÕÁÌˆ¤½Èíô¤¹•Ğ¡É½ÕÁ}¥¤½Èíô(€€€€€€€€€€€€€€€€€€€€€€€¥˜œ¹•Ğ ‰µ•µ‰•É}½Õ¹Ñ}…Ñ}‰¥¹ˆ¤¥Ì¹½Ğ9½¹”è(€€€€€€€€€€€€€€€€€€€€€€€€€€€•¹É¥¡•¹Í•Ñ‘•™…Õ±Ğ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰µ•µ‰•É}½Õ¹Ğˆ°œ¹•Ğ ‰µ•µ‰•É}½Õ¹Ñ}…Ñ}‰¥¹ˆ¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹•á•ÁÑ¥½¸ ‰•¹É¥ ‰¥¹É•ÍÕ±Ğ™…¥±•è€•Ìˆ°•áŒ¤(€€€€€€€€€€€€€€€•¹É¥¡•¹Í•Ñ‘•™…Õ±Ğ ‰‘¥ÍÁ±…å}¹…µ”ˆ°€‹º‡B–N„ˆ¤(€€€€€€€€€€€€€€€•¹É¥¡•¹Í•Ñ‘•™…Õ±Ğ ‰Õ…É‘¥…¹}½Õ¹Ğˆ°€À¤(€€€€€€€€€€€€€€€•¹É¥¡•¹Í•Ñ‘•™…Õ±Ğ ‰Õ…É‘¥…¹}±¥µ¥Ğˆ°€Ô¤(€€€€€€€€€€€€€€€•¹É¥¡•¹Í•Ñ‘•™…Õ±Ğ ‰•µ•É•¹å}½Õ¹Ğˆ°€À¤(€€€€€€€€€€€€€€€•¹É¥¡•¹Í•Ñ‘•™…Õ±Ğ ‰•µ•É•¹å}±¥µ¥Ğˆ°€È¤(€€€€€€€€€€€€€€€•¹É¥¡•¹Í•Ñ‘•™…Õ±Ğ ‰É•µ¥¹‘•É}Ñ¥µ”ˆ°€ˆÀäèÀÀˆ¤(€€€€€€€€€€€É•ÑÕÉ¸•¹É¥¡•((€€€€€€€‘•˜}½İ¹•É}‘¥ÍÁ±…å}¹…µ”¡½İ¹•É}¥¹™¼¤è(€€€€€€€€€€€½İ¹•É}¥€ô€¡½İ¹•É}¥¹™¼½Èíô¤¹•Ğ ‰½İ¹•É}¥ˆ¤(€€€€€€€€€€€¥˜¹½Ğ½İ¹•É}¥è(€€€€€€€€€€€€€€€É•ÑÕÉ¸€‹–ºÛ’êèˆ(€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤(€€€€€€€€€€€€€€€ÁÉ½™¥±”€ôÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ°íô¤¹•Ğ¡½İ¹•É}¥°íô¤½Èíô(€€€€€€€€€€€€€€€¹…µ”€ô€¡ÁÉ½™¥±”¹•Ğ ‰‘¥ÍÁ±…å}¹…µ”ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€€€€€€€€€É•ÑÕÉ¸¹…µ”½È€‹–ºÛ’êèˆ(€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸è(€€€€€€€€€€€€€€€É•ÑÕÉ¸€‹–ºÛ’êèˆ((€€€€€€€‘•˜}±½…‘}É½ÕÁ}½İ¹•É}¥¹™¼¡É½ÕÁ}¥°±¥¹•}ÕÍ•É}¥õ9½¹”¤è(€€€€€€€€€€€½İ¹•É}¥¹™¼€ôì(€€€€€€€€€€€€€€€€‰‰½Õ¹ˆè…±Í”°(€€€€€€€€€€€€€€€€‰¥Í}½İ¹•Èˆè…±Í”°(€€€€€€€€€€€€€€€€‰½İ¹•É}¥ˆè9½¹”°(€€€€€€€€€€€€€€€€‰¥Í}…Ñ¥Ù”ˆè…±Í”°(€€€€€€€€€€€€€€€€‰½İ¹•É}Á±…¸ˆè9½¹”°(€€€€€€€€€€€ô(€€€€€€€€€€€¥˜¹½ĞÉ½ÕÁ}¥è(€€€€€€€€€€€€€€€É•ÑÕÉ¸½İ¹•É}¥¹™¼(€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤(€€€€€€€€€€€€€€€•á¥ÍÑ¥¹}É½ÕÀ€ôÍÑ…Ñ”¹•Ğ ‰Õ…É‘¥…¹}É½ÕÁÌˆ°íô¤¹•Ğ¡É½ÕÁ}¥½È€ˆˆ°íô¤(€€€€€€€€€€€€€€€¥˜•á¥ÍÑ¥¹}É½ÕÀ¹•Ğ ‰ÍÑ…ÑÕÌˆ¤€ôô€‰…Ñ¥Ù”ˆè(€€€€€€€€€€€€€€€€€€€½İ¹•É}¥€ô•á¥ÍÑ¥¹}É½ÕÀ¹•Ğ ‰½İ¹•É}±¥¹•}ÕÍ•É}¥ˆ¤(€€€€€€€€€€€€€€€€€€€½İ¹•É}ÁÉ½™¥±”€ôÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ°íô¤¹•Ğ¡½İ¹•É}¥°íô¤(€€€€€€€€€€€€€€€€€€€½İ¹•É}Á±…¸€ô½İ¹•É}ÁÉ½™¥±”¹•Ğ ‰Á±…¸ˆ¤(€€€€€€€€€€€€€€€€€€€¥Í}…Ñ¥Ù”€ô‰½½°¡½İ¹•É}ÁÉ½™¥±”¤…¹Á…¥‘}µ•µ‰•ÉÍ¡¥Á}¥Í}…Ñ¥Ù”¡½İ¹•É}ÁÉ½™¥±”¤(€€€€€€€€€€€€€€€€€€€½İ¹•É}¥¹™¼€ôì(€€€€€€€€€€€€€€€€€€€€€€€€‰‰½Õ¹ˆèQÉÕ”°(€€€€€€€€€€€€€€€€€€€€€€€€‰¥Í}½İ¹•Èˆè€¡±¥¹•}ÕÍ•É}¥€ôô½İ¹•É}¥¤¥˜±¥¹•}ÕÍ•É}¥•±Í”…±Í”°(€€€€€€€€€€€€€€€€€€€€€€€€‰½İ¹•É}¥ˆè½İ¹•É}¥°(€€€€€€€€€€€€€€€€€€€€€€€€‰¥Í}…Ñ¥Ù”ˆè¥Í}…Ñ¥Ù”°(€€€€€€€€€€€€€€€€€€€€€€€€‰½İ¹•É}Á±…¸ˆè½İ¹•É}Á±…¸°(€€€€€€€€€€€€€€€€€€€ô(€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹•á•ÁÑ¥½¸ ‰É½ÕÀ½İ¹•É}¥¹™¼±½…™…¥±•è€•Ìˆ°•áŒ¤(€€€€€€€€€€€É•ÑÕÉ¸½İ¹•É}¥¹™¼((€€€€€€€¡…¹‘±•È¹…‘¡)½¥¹Ù•¹Ğ¤(€€€€€€€‘•˜¡…¹‘±•}É½ÕÁ}©½¥¸¡•Ù•¹Ğ¤è(€€€€€€€€€€€€ˆˆ‰	½Ğƒ¢Š¯¦
¦ËúƒŠHƒ–ş¦–º#¢¶ßú“š¶‡¢ş;–6‡¾ò#’â7’úw¢ÎÓ¢«–.WÚ–ºkš"C–*¾ò'ˆˆˆ(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥€ô•Ñ…ÑÑÈ¡•Ù•¹Ğ¹Í½ÕÉ”°€‰ÕÍ•É}¥ˆ°9½¹”¤(€€€€€€€€€€€É½ÕÁ}¥€ô•Ñ…ÑÑÈ¡•Ù•¹Ğ¹Í½ÕÉ”°€‰É½ÕÁ}¥ˆ°9½¹”¤(€€€€€€€€€€€É½½µ}¥€ô•Ñ…ÑÑÈ¡•Ù•¹Ğ¹Í½ÕÉ”°€‰É½½µ}¥ˆ°9½¹”¤(€€€€€€€€€€€Ñ…É•Ñ}¥€ôÉ½ÕÁ}¥½ÈÉ½½µ}¥(€€€€€€€€€€€…ÁÀ¹±½•È¹¥¹™¼ (€€€€€€€€€€€€€€€€‰)½¥¹Ù•¹ĞÉ½ÕÀô•ÌÉ½½´ô•Ì¥¹Ù¥Ñ•Èô•Ìˆ°(€€€€€€€€€€€€€€€€¡É½ÕÁ}¥½È€ˆˆ¥lèÄÉt°(€€€€€€€€€€€€€€€€¡É½½µ}¥½È€ˆˆ¥lèÄÉt°(€€€€€€€€€€€€€€€€¡±¥¹•}ÕÍ•É}¥½È€ˆˆ¥lèát°(€€€€€€€€€€€€¤((€€€€€€€€€€€€Œ)½¥¹Ù•¹Ğƒ¦k–âãšÊKšr$ÕÍ•É}¥“¾òo’â7¢š–nƒ‡šÎW¢«–.WÚ–ºk–ÂÇš.K¦š¶‡¢ş;–6„(€€€€€€€€€€€½ÕÑ½µ”°}ÍÑ…ÑÕÌ€ôì‰É•Á±å}Ñ•áĞˆè€‹š¶‡¢ş;–*ƒ–—–º#¢¶ßúˆ°€‰Í¡½Õ±‘}±•…Ù”ˆè…±Í•ô°€ÈÀÀ(€€€€€€€€€€€¥˜±¥¹•}ÕÍ•É}¥…¹É½ÕÁ}¥è(€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€½ÕÑ½µ”°}ÍÑ…ÑÕÌ€ôÕ…É‘¥…¹}É½ÕÁ}©½¥¹}½ÕÑ½µ” (€€€€€€€€€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥°É½ÕÁ}¥(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹•á•ÁÑ¥½¸ ‰Õ…É‘¥…¹}É½ÕÁ}©½¥¹}½ÕÑ½µ”™…¥±•è€•Ìˆ°•áŒ¤(€€€€€€€€€€€€€€€€€€€½ÕÑ½µ”°}ÍÑ…ÑÕÌ€ôì‰É•Á±å}Ñ•áĞˆè€‹š¶‡¢ş;–*ƒ–—–º#¢¶ßúˆ°€‰Í¡½Õ±‘}±•…Ù”ˆè…±Í•ô°€ÈÀÀ((€€€€€€€€€€€½İ¹•É}¥¹™¼€ô}±½…‘}É½ÕÁ}½İ¹•É}¥¹™¼¡É½ÕÁ}¥°±¥¹•}ÕÍ•É}¥¤(€€€€€€€€€€€¥¹ÑÉ½}µÍÌ€ô}Õ…É‘¥…¹}¥¹ÑÉ½}µ•ÍÍ…•Ì¡½İ¹•É}¥¹™¼°½ÕÑ½µ”¹•Ğ ‰É•Á±å}Ñ•áĞˆ¤¥˜½İ¹•É}¥¹™¼¹•Ğ ‰‰½Õ¹ˆ¤•±Í”9½¹”¤((€€€€€€€€€€€Í•¹Ğ€ô…±Í”(€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹É•Á±å}µ•ÍÍ…”¡•Ù•¹Ğ¹É•Á±å}Ñ½­•¸°¥¹ÑÉ½}µÍÌ¤(€€€€€€€€€€€€€€€Í•¹Ğ€ôQÉÕ”(€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹¥¹™¼ ‰)½¥¹Ù•¹ĞÉ•Á±ä¥¹ÑÉ¼½¬É½ÕÀô•Ìˆ°€¡É½ÕÁ}¥½È€ˆˆ¥lèÄÉt¤(€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹•á•ÁÑ¥½¸ ‰)½¥¹Ù•¹ĞÉ•Á±ä¥¹ÑÉ¼™…¥±•è€•Ìˆ°•áŒ¤((€€€€€€€€€€€¥˜¹½ĞÍ•¹Ğ…¹Ñ…É•Ñ}¥è(€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹ÁÕÍ¡}µ•ÍÍ…”¡Ñ…É•Ñ}¥°¥¹ÑÉ½}µÍÌ¤(€€€€€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹¥¹™¼ ‰)½¥¹Ù•¹ĞÁÕÍ ¥¹ÑÉ¼½¬É½ÕÀô•Ìˆ°€¡É½ÕÁ}¥½È€ˆˆ¥lèÄÉt¤(€€€€€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹•á•ÁÑ¥½¸ ‰)½¥¹Ù•¹ĞÁÕÍ ¥¹ÑÉ¼™…¥±•è€•Ìˆ°•áŒ¤((€€€€€€€€€€€€Œƒ––r£ú“–ŞË¢Š¯–Û’î[šr–N‡’öSR£šf¦n‹¦Z,(€€€€€€€€€€€¥˜É½ÕÁ}¥…¹}ÍÑ…ÑÕÌ€ôô€ĞÀäè(€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹±•…Ù•}É½ÕÀ¡É½ÕÁ}¥¤(€€€€€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹•á•ÁÑ¥½¸ ‰±•…Ù•}É½ÕÀ™…¥±•è€•Ìˆ°•áŒ¤((€€€€€€€¡…¹‘±•È¹…‘¡½±±½İÙ•¹Ğ¤(€€€€€€€‘•˜¡…¹‘±•}™½±±½Ü¡•Ù•¹Ğ¤è(€€€€€€€€€€€€ˆˆ‹–*ƒ––÷–>/š¶‡¢ş;¾òk–«–#–nx±•à£r–¾›šjÇ¢Ç–V?–d€¬ƒ®/–6Ï¦Z/–/¢¢·–ºh§ˆˆˆ(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥€ô•Ñ…ÑÑÈ¡•Ù•¹Ğ¹Í½ÕÉ”°€‰ÕÍ•É}¥ˆ°9½¹”¤(€€€€€€€€€€€‘¥ÍÁ±…å}¹…µ”€ôÉ•Í½±Ù•}İ•±½µ•}‘¥ÍÁ±…å}¹…µ” (€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤õ±¥¹•}‰½Ñ}…Á¤°(€€€€€€€€€€€€€€€‘…Ñ…}™¥±”õ…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥õ±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€±½•Èõ…ÁÀ¹±½•È°(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜±¥¹•}ÕÍ•É}¥è(€€€€€€€€€€€€€€€€Œ½±±½ÜƒVÛ’â/–ÂÇ–¾¯–”ÕÍ•ÉÏ¾ò3’æ/–ú3¦Z,1%ƒ’â7šr–nƒòèÉ½Üƒ¢0€ĞÀĞ(€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€É•¥ÍÑÉ…Ñ¥½¹}É•ÍÕ±Ğ€ôÉ•¥ÍÑ•É}±¥¹•}ÕÍ•È (€€€€€€€€€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰‘¥ÍÁ±…å}¹…µ”ˆè‘¥ÍÁ±…å}¹…µ”½È€ˆˆ°(€€€€€€€€€€€€€€€€€€€€€€€ô°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€¥˜}É•Á±å}µ¥É…Ñ•‘}…½Õ¹Ğ (€€€€€€€€€€€€€€€€€€€€€€€•Ù•¹Ğ¹É•Á±å}Ñ½­•¸°É•¥ÍÑÉ…Ñ¥½¹}É•ÍÕ±Ğ(€€€€€€€€€€€€€€€€€€€€¤è(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸(€€€€€€€€€€€€€€€€€€€É•…Ñ¥Ù…Ñ•}±¥¹•}ÁÕÍ¡}™½É}™½±±½Ü¡…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥¤(€€€€€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹•á•ÁÑ¥½¸ ‰½±±½İÙ•¹ĞÉ•¥ÍÑ•È™…¥±•è€•Ìˆ°•áŒ¤(€€€€€€€€€€€…ÁÀ¹±½•È¹¥¹™¼ (€€€€€€€€€€€€€€€€‰½±±½İÙ•¹Ğİ•±½µ”ÑÉ¥•ÈÕÍ•Èô•Ì¹…µ”ô•Èˆ°(€€€€€€€€€€€€€€€€¡±¥¹•}ÕÍ•É}¥½È€ˆˆ¥lèát°(€€€€€€€€€€€€€€€‘¥ÍÁ±…å}¹…µ”½È€ˆˆ°(€€€€€€€€€€€€¤(€€€€€€€€€€€}Í•¹‘}İ•±½µ” (€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤°(€€€€€€€€€€€€€€€É•Á±å}Ñ½­•¸õ•Ù•¹Ğ¹É•Á±å}Ñ½­•¸°(€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥õ±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€‘¥ÍÁ±…å}¹…µ”õ‘¥ÍÁ±…å}¹…µ”°(€€€€€€€€€€€€€€€ÑÉ¥•Èô‰™½±±½Üˆ°(€€€€€€€€€€€€¤((€€€€€€€¡…¹‘±•È¹…‘¡5•µ‰•É)½¥¹•‘Ù•¹Ğ¤(€€€€€€€‘•˜¡…¹‘±•}µ•µ‰•É}©½¥¹•¡•Ù•¹Ğ¤è(€€€€€€€€€€€€Œ€ÈÀÈØ´ÀÜ´ÈÀƒ¢v›¢FŒ…‘‘•èƒ¢Ú¦8€ÔÀƒ’êë’â+¦fCšf³¢®/–ëšZÃš"C–N„(€€€€€€€€€€€€Œ€ÈÀÈØ´ÀÜ´ÈĞèƒš"C–N‡¦Ëú“’æ¢sš¶‡¢ş;¾ò?Ú–ºkš>C¦K¾ò!)½¥¹Ù•¹Ğƒšò?¦šfj–
gš>Ó¾ò$(€€€€€€€€€€€€Œ€ÈÀÈØ´ÀÜ´ÈÔèƒ¦Ëú“–"ßšZÃú“š"C–N‡šVã¾òošZš†#–6–"3ú“Öš"C–N‡5ÙÏ3–ŞËÚ–ºk–º#¢¶ß’êë4(€€€€€€€€€€€¥˜•Ñ…ÑÑÈ¡•Ù•¹Ğ¹Í½ÕÉ”°€‰ÑåÁ”ˆ°9½¹”¤€„ô€‰É½ÕÀˆè(€€€€€€€€€€€€€€€É•ÑÕÉ¸(€€€€€€€€€€€É½ÕÁ}¥€ô•Ñ…ÑÑÈ¡•Ù•¹Ğ¹Í½ÕÉ”°€‰É½ÕÁ}¥ˆ°9½¹”¤(€€€€€€€€€€€¥˜¹½ĞÉ½ÕÁ}¥è(€€€€€€€€€€€€€€€É•ÑÕÉ¸(€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€¹•İ}¥‘Ì€ôm´¹ÕÍ•É}¥™½È´¥¸€¡•Ù•¹Ğ¹©½¥¹•¹µ•µ‰•ÉÌ½Èmt¤¥˜•Ñ…ÑÑÈ¡´°€‰ÕÍ•É}¥ˆ°9½¹”¥t(€€€€€€€€€€€€€€€½İ¹•É}¥¹™¼€ô}±½…‘}É½ÕÁ}½İ¹•É}¥¹™¼¡É½ÕÁ}¥¤(€€€€€€€€€€€€€€€€Œƒ–ŞËÚ–ºk–º#¢¶ßú“¾òk–"ßšZÃú“Öš"C–N‡šVã–ş¯Ÿ¾ò#’â7–öÇ¦~ÿ–ŞËÚ–ºk–º#¢¶ß’êë¢¢#šVã¾ò$(€€€€€€€€€€€€€€€¥˜½İ¹•É}¥¹™¼¹•Ğ ‰‰½Õ¹ˆ¤è(€€€€€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€€€€€É•™É•Í¡}Õ…É‘¥…¹}É½ÕÁ}µ•µ‰•É}Í¹…ÁÍ¡½Ğ (€€€€€€€€€€€€€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°É½ÕÁ}¥(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹•á•ÁÑ¥½¸ ‰5•µ‰•É)½¥¹•µ•µ‰•ÈÍ¹…ÁÍ¡½ĞÉ•™É•Í ™…¥±•è€•Ìˆ°•áŒ¤(€€€€€€€€€€€€€€€€Œƒšr«Ú–ºk¾òkš:£š¶‡¢ş;–6‡¾ò3¢®/º‡B–N‡¦î{3Ú–ºk–º#¢¶ßú“4(€€€€€€€€€€€€€€€€Œƒ–ŞËÚ–ºk¾òkÂ‡~·š¶‡¢ş;šZÃš"C–N‡¾ò#¦ËúƒŠ&€ƒ’â¦6×¦
¢®/Ú–ºk¾ò$(€€€€€€€€€€€€€€€¥˜¹½Ğ½İ¹•É}¥¹™¼¹•Ğ ‰‰½Õ¹ˆ¤è(€€€€€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹ÁÕÍ¡}µ•ÍÍ…” (€€€€€€€€€€€€€€€€€€€€€€€€€€€É½ÕÁ}¥°(€€€€€€€€€€€€€€€€€€€€€€€€€€€}Õ…É‘¥…¹}¥¹ÑÉ½}µ•ÍÍ…•Ì¡½İ¹•É}¥¹™¼¤°(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹¥¹™¼ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰5•µ‰•É)½¥¹•Õ¹‰½Õ¹¥¹ÑÉ¼ÁÕÍ É½ÕÀô•Ì¹•Üô•Ìˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€É½ÕÁ}¥‘lèÄÉt°(€€€€€€€€€€€€€€€€€€€€€€€€€€€±•¸¡¹•İ}¥‘Ì¤°(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹•á•ÁÑ¥½¸ ‰5•µ‰•É)½¥¹•¥¹ÑÉ¼ÁÕÍ ™…¥±•è€•Ìˆ°•áŒ¤(€€€€€€€€€€€€€€€•±¥˜¹•İ}¥‘Ìè(€€€€€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€€€€€¥¹Ù¥Ñ•É}¹…µ”€ô}½İ¹•É}‘¥ÍÁ±…å}¹…µ”¡½İ¹•É}¥¹™¼¤(€€€€€€€€€€€€€€€€€€€€€€€µ•µ‰•É}µÍÌ€ômt(€€€€€€€€€€€€€€€€€€€€€€€¥˜±•áM•¹‘5•ÍÍ…”¥Ì¹½Ğ9½¹”…¹Õ…É‘¥…¹}É½ÕÁ}µ•µ‰•É}©½¥¹•‘}™±•à¥Ì¹½Ğ9½¹”è(€€€€€€€€€€€€€€€€€€€€€€€€€€€µ•µ‰•É}µÍÌ¹…ÁÁ•¹ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€±•áM•¹‘5•ÍÍ…” (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€…±Ñ}Ñ•áĞõ˜‹Šv“¾â<ƒš¶‡¢ş;–*ƒ–”í¥¹Ù¥Ñ•É}¹…µ•ôƒj–º#¢¶ßúˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€½¹Ñ•¹ÑÌõÕ…É‘¥…¹}É½ÕÁ}µ•µ‰•É}©½¥¹•‘}™±•à¡¥¹Ù¥Ñ•É}¹…µ”¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€€€€€€€€€µ•µ‰•É}µÍÌ¹…ÁÁ•¹ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€Q•áÑM•¹‘5•ÍÍ…” (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€Ñ•áĞô (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€˜‹Šv“¾â<ƒš¶‡¢ş;–*ƒ–”í¥¹Ù¥Ñ•É}¹…µ•ôƒj–º#¢¶ßú‘q¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‹š
£–ŞË–*ƒ–—3š¾?š^—–æÏ–º'51%9ƒ–º#¢¶ßú“	q¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‹ú“–Ÿ–>¿šRÛš>C¦K¾òo¢.—¢šš"C
ë–/’êë–ŞËÚ–ºk–º#¢¶ß’êë¾ò0ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‹¢®/¢®/–Â7šZçR£3’â¦6×¦
¢®/7–7Ú’âš²‡ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹ÁÕÍ¡}µ•ÍÍ…”¡É½ÕÁ}¥°µ•µ‰•É}µÍÌ¤(€€€€€€€€€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹•á•ÁÑ¥½¸ ‰5•µ‰•É)½¥¹•İ•±½µ”™±•à™…¥±•è€•Ìˆ°•áŒ¤((€€€€€€€€€€€€€€€É•ÍÕ±Ğ°½‘”€ô•¹™½É•}É½ÕÁ}µ•µ‰•É}±¥µ¥Ğ¡É½ÕÁ}¥°‘¥Ğ¡…ÁÀ¹½¹™¥œ¤¤(€€€€€€€€€€€€€€€¥˜½‘”€„ô€ÈÀÀ½È¹½ĞÉ•ÍÕ±Ğ¹•Ğ ‰•¹™½É•ˆ¤è(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸(€€€€€€€€€€€€€€€µÍ}±¥¹•Ì€ôl(€€€€€€€€€€€€€€€€€€€˜‹Šjƒ¾â<ƒ–º#¢¶ßú“¢Ú¦8íI=UA}55	I}1%5%Qôƒ’êë’â+¦fCˆ°(€€€€€€€€€€€€€€€€€€€˜‹n»–&7š"C–N‡šVàéíÉ•ÍÕ±Ğ¹•Ğ ÕÉÉ•¹Ñ}½Õ¹Ğœ¥ô½íI=UA}55	I}1%5%Qôˆ°(€€€€€€€€€€€€€€€t(€€€€€€€€€€€€€€€¥˜É•ÍÕ±Ğ¹•Ğ ‰­¥­•ˆ¤è(€€€€€€€€€€€€€€€€€€€µÍ}±¥¹•Ì¹…ÁÁ•¹¡˜‹–ŞË¢®/–èí±•¸¡É•ÍÕ±Ñl­¥­•t¥ôƒ’ö7šZÃš"C–N‡ˆ¤(€€€€€€€€€€€€€€€¥˜É•ÍÕ±Ğ¹•Ğ ‰‰½Ñ}¹½Ñ}…‘µ¥¹}½Õ¹Ğˆ¤è(€€€€€€€€€€€€€€€€€€€µÍ}±¥¹•Ì¹…ÁÁ•¹ (€€€€€€€€€€€€€€€€€€€€€€€˜‹Šjƒ¾â<ƒ3š¾?š^—–æÏ–º'7n»–&7‡šÎW¢®/–ë¢Ú¦†7š"C–N‡¾ò#–>›šr$íÉ•ÍÕ±Ñl‰½Ñ}¹½Ñ}…‘µ¥¹}½Õ¹Ğuôƒ’ö7¾ò'ˆ(€€€€€€€€€€€€€€€€€€€€€€€€‹¢®/º‡B–N‡š&/–.W¦–ë¢Ú¦†7š"C–N‡¾ò3š"[–ş¢ššfš*+3š¾?š^—–æÏ–º'7¢¢·
ëú“Öº‡B–N‡–ú3–7¢¦›ˆ(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€¥˜É•ÍÕ±Ğ¹•Ğ ‰™…¥±•ˆ¤…¹¹½ĞÉ•ÍÕ±Ğ¹•Ğ ‰‰½Ñ}¹½Ñ}…‘µ¥¹}½Õ¹Ğˆ¤è(€€€€€€€€€€€€€€€€€€€µÍ}±¥¹•Ì¹…ÁÁ•¹¡˜‹¢®/–ë–’ÇšV\éí±•¸¡É•ÍÕ±Ñl™…¥±•t¥ôƒ’ö7ˆ¤(€€€€€€€€€€€€€€€€Œƒ––r 	½Ğƒ‡º‡B–N‡š²+¦fCrj¢â‹’êë–’ÇšV_šfš&7š>C’ë¾òo–6Òk¾ò?Ú–ºk–ú3’öÿR£¢–ŞË¢«–.Wšb¿–º#¢¶ßú“º‡B–N„(€€€€€€€€€€€€€€€¥˜É•ÍÕ±Ğ¹•Ğ ‰‰½Ñ}¹½Ñ}…‘µ¥¹}½Õ¹Ğˆ¤è(€€€€€€€€€€€€€€€€€€€µÍ}±¥¹•Ì¹…ÁÁ•¹ ‹Â~J„ƒ¢.—¦r¢®/–ë¢Ú¦†7š"C–N‡¾ò3–>¿–r£ú“¢‡š&O3º‡B–N‡¢¢·–ºk7r/šVg–¶ã¾ò#¦v{–ş¢š¦Z/¦kš¶—¦¦¾ò$ˆ¤(€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹ÁÕÍ¡}µ•ÍÍ…”¡É½ÕÁ}¥°Q•áÑM•¹‘5•ÍÍ…”¡Ñ•áĞô‰q¸ˆ¹©½¥¸¡µÍ}±¥¹•Ì¤¤¤(€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸è(€€€€€€€€€€€€€€€Á…ÍÌ((€€€€€€€¥˜A½ÍÑ‰…­Ù•¹Ğ¥Ì¹½Ğ9½¹”è(€€€€€€€€€€€¡…¹‘±•È¹…‘¡A½ÍÑ‰…­Ù•¹Ğ¤(€€€€€€€€€€€‘•˜¡…¹‘±•}Á½ÍÑ‰…¬¡•Ù•¹Ğ¤è(€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥€ô•Ñ…ÑÑÈ¡•Ù•¹Ğ¹Í½ÕÉ”°€‰ÕÍ•É}¥ˆ°9½¹”¤(€€€€€€€€€€€€€€€‘…Ñ„€ô€ˆˆ(€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€‘…Ñ„€ôÍÑÈ¡•Ñ…ÑÑÈ¡•Ù•¹Ğ¹Á½ÍÑ‰…¬°€‰‘…Ñ„ˆ°€ˆˆ¤½È€ˆˆ¤(€€€€€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸è(€€€€€€€€€€€€€€€€€€€‘…Ñ„€ô€ˆˆ(€€€€€€€€€€€€€€€¥˜¹½Ğ±¥¹•}ÕÍ•É}¥½È¹½Ğ‘…Ñ„è(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸(€€€€€€€€€€€€€€€É•Á±ä€ô9½¹”(€€€€€€€€€€€€€€€€Œƒš¾?š^—š:£šJ·3š"G–æÏ–º'7¾òk–r 1%9ƒ–Ÿ¦î{¦ã–6Ï–¾¯–—Â÷–"Ã¾ò#¢"1%ƒ–B3’â––\É•½É‘}¡•­¥»¾ò$(€€€€€€€€€€€€€€€¥˜¥Í}¡•­¥¹}Á½ÍÑ‰…¬¡‘…Ñ„¤è(€€€€€€€€€€€€€€€€€€€É•Á±ä€ô¡…¹‘±•}¡•­¥¹}Á½ÍÑ‰…¬¡…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥°…ÁÀ¹½¹™¥œ¤(€€€€€€€€€€€€€€€•±¥˜¥Í}•áÁ¥Éå}½ÁÑ}½ÕÑ}Á½ÍÑ‰…¬¡‘…Ñ„¤è(€€€€€€€€€€€€€€€€€€€É•Á±ä€ô¡…¹‘±•}•áÁ¥Éå}½ÁÑ}½ÕÑ}Á½ÍÑ‰…¬¡…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥¤(€€€€€€€€€€€€€€€•±¥˜‘…Ñ„¹ÍÑ…ÉÑÍİ¥Ñ  ‰‰•Ñ…}™••‘‰…¬èˆ¤è(€€€€€€€€€€€€€€€€€€€É•Á±ä€ô¡…¹‘±•}‰•Ñ…}™••‘‰…­}Á½ÍÑ‰…¬ (€€€€€€€€€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥°‘…Ñ„(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€•±¥˜‘…Ñ„¹ÍÑ…ÉÑÍİ¥Ñ  ‰Í½Ìèˆ¤è(€€€€€€€€€€€€€€€€€€€Á…ÉÑÌ€ô‘…Ñ„¹ÍÁ±¥Ğ ˆèˆ°€È¤(€€€€€€€€€€€€€€€€€€€¥˜±•¸¡Á…ÉÑÌ¤€ôô€Ìè(€€€€€€€€€€€€€€€€€€€€€€€É•ÍÕ±Ğ°ÍÑ…ÑÕÍ}½‘”€ôÉ•ÍÁ½¹‘}Ñ½}Í½Í}•Ù•¹Ğ (€€€€€€€€€€€€€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰…Ñ¥½¸ˆèÁ…ÉÑÍlÅt°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰•Ù•¹Ñ}¥ˆèÁ…ÉÑÍlÉt°(€€€€€€€€€€€€€€€€€€€€€€€€€€€ô°(€€€€€€€€€€€€€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥œ°(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€¥˜ÍÑ…ÑÕÍ}½‘”€ôô€ÈÀÀè(€€€€€€€€€€€€€€€€€€€€€€€€€€€É½±•}Ñ•áĞ€ô€ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‹’öƒšb¿’âï¢šš:—š&/’êèˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¥˜É•ÍÕ±Ğ¹•Ğ ‰É½±”ˆ¤€ôô€‰ÁÉ¥µ…Éäˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€•±Í”€‹–ŞËšr'–º#¢¶ß’êë–#š:—š&/¾ò3’öƒ–ŞË–*ƒ–—–6S–*¤ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¥˜É•ÍÕ±Ğ¹•Ğ ‰É½±”ˆ¤€ôô€‰…ÍÍ¥ÍÑ…¹Ğˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€•±Í”€‹–ŞË¢¢c¦2’öƒj–n{š$ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€É•Á±ä€ô˜‹ŠríÉ½±•}Ñ•áÑõq»ÎïÖÇ–ŞË–sš¶‹¦7¢’–
³’ş¾òo¢®/æóê3¢¿Ö‡šr³’êèˆ(€€€€€€€€€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€€€€€€€€€É•Á±ä€ô€‹¦g¶M=Lƒ‡šÎWšnÓšZÃ¾ò3–>¿¢÷–ŞËÖCš†#š"[’öƒ’â7šb¿šr³š²‡šRÛ’îÛ’êèˆ(€€€€€€€€€€€€€€€•±¥˜‘…Ñ„¹ÍÑ…ÉÑÍİ¥Ñ  ‰Íµ…ÉĞèˆ¤è(€€€€€€€€€€€€€€€€€€€É•Á±ä€ô¡…¹‘±•}Íµ…ÉÑ}É•µ¥¹‘•É}Á½ÍÑ‰…¬ (€€€€€€€€€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥°‘…Ñ„°…ÁÀ¹½¹™¥œ(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€€Œƒnã–ºç¢"+&#–>[šÚ#¢¶›–‚ÄÁ½ÍÑ‰…¯¾òk’æ¢š[
ë’î+š^—–‚Ç–æÏ–º$(€€€€€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€€€€€™É½´…±•ÉÑÌ¹Á½ÍÑ‰…¬¥µÁ½ÉĞ¥Í}…±•ÉÑ}…¹•±}Á½ÍÑ‰…¬(€€€€€€€€€€€€€€€€€€€€€€€¥˜¥Í}…±•ÉÑ}…¹•±}Á½ÍÑ‰…¬¡‘…Ñ„¤è(€€€€€€€€€€€€€€€€€€€€€€€€€€€É•Á±ä€ô¡…¹‘±•}¡•­¥¹}Á½ÍÑ‰…¬ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥°…ÁÀ¹½¹™¥œ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸è(€€€€€€€€€€€€€€€€€€€€€€€É•Á±ä€ô9½¹”(€€€€€€€€€€€€€€€¥˜É•Á±äè(€€€€€€€€€€€€€€€€€€€¥Ñ•µÌ€ô¹½Éµ…±¥é•}±¥¹•}É•Á±å}¥Ñ•µÌ¡É•Á±ä¤(€€€€€€€€€€€€€€€€€€€µ•ÍÍ…•Ì€ômt(€€€€€€€€€€€€€€€€€€€™½È¥Ñ•´¥¸¥Ñ•µÌè(€€€€€€€€€€€€€€€€€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡¥Ñ•´°‘¥Ğ¤…¹¥Ñ•´¹•Ğ ‰ÑåÁ”ˆ¤€ôô€‰™±•àˆè(€€€€€€€€€€€€€€€€€€€€€€€€€€€¥˜±•áM•¹‘5•ÍÍ…”¥Ì9½¹”è(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€µ•ÍÍ…•Ì¹…ÁÁ•¹ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€Q•áÑM•¹‘5•ÍÍ…” (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€Ñ•áĞõÍÑÈ¡¥Ñ•´¹•Ğ ‰…±ÑQ•áĞˆ¤½È€‹š¾?š^—–æÏ–º$ˆ¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€µ•ÍÍ…•Ì¹…ÁÁ•¹ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€±•áM•¹‘5•ÍÍ…” (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€…±Ñ}Ñ•áĞõÍÑÈ¡¥Ñ•´¹•Ğ ‰…±ÑQ•áĞˆ¤½È€‹š¾?š^—–æÏ–º$ˆ¥lèĞÀÁt°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€½¹Ñ•¹ÑÌõ¥Ñ•´¹•Ğ ‰½¹Ñ•¹ÑÌˆ¤½Èíô°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€€€€€€€€€µ•ÍÍ…•Ì¹…ÁÁ•¹¡Q•áÑM•¹‘5•ÍÍ…”¡Ñ•áĞõÍÑÈ¡¥Ñ•´¤¤¤(€€€€€€€€€€€€€€€€€€€¥˜µ•ÍÍ…•Ìè(€€€€€€€€€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹É•Á±å}µ•ÍÍ…”¡•Ù•¹Ğ¹É•Á±å}Ñ½­•¸°µ•ÍÍ…•Ì¤((€€€€€€€¡…¹‘±•È¹…‘¡5•ÍÍ…•Ù•¹Ğ°µ•ÍÍ…”õQ•áÑ5•ÍÍ…”¤(€€€€€€€‘•˜¡…¹‘±•}Ñ•áÑ}µ•ÍÍ…”¡•Ù•¹Ğ¤è(€€€€€€€€€€€Ñ•áĞ€ô•Ù•¹Ğ¹µ•ÍÍ…”¹Ñ•áĞ(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥€ô•Ñ…ÑÑÈ¡•Ù•¹Ğ¹Í½ÕÉ”°€‰ÕÍ•É}¥ˆ°9½¹”¤(€€€€€€€€€€€É½ÕÁ}¥€ô•Ñ…ÑÑÈ¡•Ù•¹Ğ¹Í½ÕÉ”°€‰É½ÕÁ}¥ˆ°9½¹”¤(€€€€€€€€€€€ÍÑÉ¥ÁÁ•€ôÑ•áĞ¹ÍÑÉ¥À ¤((€€€€€€€€€€€€Œƒš¶‡¢ş;¢¦{¦^s¦6×–¶_¾ò#–ŞËšb¿––÷–>/’æ–>¿¦7š.ÿš¶‡¢ş;–6‡¾òo’â7¦r–>[šÚ#––÷–>/¾ò$(€€€€€€€€€€€€ŒƒÒS¦^s¦6×–¶_š"[3¦Z/–/¾ò7¶'š¢g¦î{’æ–>¿¢ãfó¾ò3¦ÿ–4=ƒš&Oš.o–Fó¢"+¢¢+¦ƒš"C¢ª“šr(€€€€€€€€€€€İ•±½µ•}­•åÌ€ô€ ‹¦Z/–,ˆ°€‹š¶‡¢ş8ˆ°€‹¢ª«šb8ˆ°€‹š¶‡¢ş;¢¦xˆ¤(€€€€€€€€€€€¥˜ÍÑÉ¥ÁÁ•¥¸İ•±½µ•}­•åÌ½ÈÍÑÉ¥ÁÁ•¹ÉÍÑÉ¥À ‹¾ò‡¹û¾öx€ˆ¤¥¸İ•±½µ•}­•åÌè(€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹¥¹™¼ (€€€€€€€€€€€€€€€€€€€€‰İ•±½µ”­•åİ½É¡¥ĞÑ•áĞô•ÈÕÍ•Èô•Ìˆ°(€€€€€€€€€€€€€€€€€€€ÍÑÉ¥ÁÁ•‘lèÈÁt°(€€€€€€€€€€€€€€€€€€€€¡±¥¹•}ÕÍ•É}¥½È€ˆˆ¥lèát°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€‘¥ÍÁ±…å}¹…µ”€ôÉ•Í½±Ù•}İ•±½µ•}‘¥ÍÁ±…å}¹…µ” (€€€€€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤õ±¥¹•}‰½Ñ}…Á¤°(€€€€€€€€€€€€€€€€€€€‘…Ñ…}™¥±”õ…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥õ±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€€€€€±½•Èõ…ÁÀ¹±½•È°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€¥˜±¥¹•}ÕÍ•É}¥è(€€€€€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€€€€€É•¥ÍÑÉ…Ñ¥½¹}É•ÍÕ±Ğ€ôÉ•¥ÍÑ•É}±¥¹•}ÕÍ•È (€€€€€€€€€€€€€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰‘¥ÍÁ±…å}¹…µ”ˆè‘¥ÍÁ±…å}¹…µ”½È€‰1%9ƒ’öÿR£¢ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€ô°(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€¥˜}É•Á±å}µ¥É…Ñ•‘}…½Õ¹Ğ (€€€€€€€€€€€€€€€€€€€€€€€€€€€•Ù•¹Ğ¹É•Á±å}Ñ½­•¸°É•¥ÍÑÉ…Ñ¥½¹}É•ÍÕ±Ğ(€€€€€€€€€€€€€€€€€€€€€€€€¤è(€€€€€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸(€€€€€€€€€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹•á•ÁÑ¥½¸ ‰İ•±½µ”­•åİ½ÉÉ•¥ÍÑ•È™…¥±•è€•Ìˆ°•áŒ¤(€€€€€€€€€€€€€€€}Í•¹‘}İ•±½µ” (€€€€€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤°(€€€€€€€€€€€€€€€€€€€É•Á±å}Ñ½­•¸õ•Ù•¹Ğ¹É•Á±å}Ñ½­•¸°(€€€€€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥õ±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€€€€€‘¥ÍÁ±…å}¹…µ”õ‘¥ÍÁ±…å}¹…µ”°(€€€€€€€€€€€€€€€€€€€ÑÉ¥•Èõ˜‰­•åİ½ÉéíÍÑÉ¥ÁÁ•‘lèÈÁuôˆ°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€É•ÑÕÉ¸((€€€€€€€€€€€€Œƒ’â¦6×¦
¢®/¾òkV—¦81%ƒ–’Ÿš2'¦"W¦‚ƒŠHƒ–nx±•àUI'¾ò!±¥¹”¹µ”½H½Í¡…É—¾ò'nÓš:—¦Z/––÷–>/¦ãšN(€€€€€€€€€€€¥˜ÍÑÉ¥ÁÁ•¥¸€ ‹’â¦6×¦
¢®,ˆ°€‹’â¦6×¦
¢®/–º#¢¶ß’êèˆ°€‹¦
¢®/–º#¢¶ß’êèˆ¤è(€€€€€€€€€€€€€€€¥˜¹½Ğ±¥¹•}ÕÍ•É}¥è(€€€€€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹É•Á±å}µ•ÍÍ…” (€€€€€€€€€€€€€€€€€€€€€€€•Ù•¹Ğ¹É•Á±å}Ñ½­•¸°(€€€€€€€€€€€€€€€€€€€€€€€Q•áÑM•¹‘5•ÍÍ…”¡Ñ•áĞô‹¢®/–#–*ƒ3š¾?š^—–æÏ–º'7
ë––÷–>/¾ò3–7¦î{’â¦6×¦
¢®/ˆ¤°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸(€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€É•¥ÍÑÉ…Ñ¥½¹}É•ÍÕ±Ğ€ôÉ•¥ÍÑ•É}±¥¹•}ÕÍ•È (€€€€€€€€€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€€€€€€€€€ì‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°€‰‘¥ÍÁ±…å}¹…µ”ˆè€‰1%9ƒ’öÿR£¢‰ô°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€¥˜}É•Á±å}µ¥É…Ñ•‘}…½Õ¹Ğ (€€€€€€€€€€€€€€€€€€€€€€€•Ù•¹Ğ¹É•Á±å}Ñ½­•¸°É•¥ÍÑÉ…Ñ¥½¹}É•ÍÕ±Ğ(€€€€€€€€€€€€€€€€€€€€¤è(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸(€€€€€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹•á•ÁÑ¥½¸ ‰¥¹Ù¥Ñ”­•åİ½ÉÉ•¥ÍÑ•È™…¥±•è€•Ìˆ°•áŒ¤(€€€€€€€€€€€€€€€¥˜±•áM•¹‘5•ÍÍ…”¥Ì¹½Ğ9½¹”…¹Í¡…É•}¥¹Ù¥Ñ•}™±•à¥Ì¹½Ğ9½¹”è(€€€€€€€€€€€€€€€€€€€™±•à€ôÍ¡…É•}¥¹Ù¥Ñ•}™±•à¡±¥¹•}ÕÍ•É}¥¤(€€€€€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹É•Á±å}µ•ÍÍ…” (€€€€€€€€€€€€€€€€€€€€€€€•Ù•¹Ğ¹É•Á±å}Ñ½­•¸°(€€€€€€€€€€€€€€€€€€€€€€€±•áM•¹‘5•ÍÍ…”¡…±Ñ}Ñ•áĞô‹¦
¢®/–ºÛ’êëVÛ–º#¢¶ß’êë¾ös¦î{šN+–
ÏÖ›–ºÛ’êèˆ°½¹Ñ•¹ÑÌõ™±•à¤°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸(€€€€€€€€€€€€€€€€Œ™…±±‰…¯¾òkÒSšZ–¶_¦f’â+–:R–"’ê¯ÚË–v (€€€€€€€€€€€€€€€¥˜Õ…É‘¥…¹}¥¹Ù¥Ñ•}Í¡…É•}Ñ•áĞ¥Ì¹½Ğ9½¹”…¹±¥¹•}¹…Ñ¥Ù•}Í¡…É•}ÕÉ°¥Ì¹½Ğ9½¹”è(€€€€€€€€€€€€€€€€€€€Í¡…É•}Ñ•áĞ€ôÕ…É‘¥…¹}¥¹Ù¥Ñ•}Í¡…É•}Ñ•áĞ¡±¥¹•}ÕÍ•É}¥¤(€€€€€€€€€€€€€€€€€€€Í¡…É•}ÕÉ¤€ô±¥¹•}¹…Ñ¥Ù•}Í¡…É•}ÕÉ°¡Í¡…É•}Ñ•áĞ¤(€€€€€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹É•Á±å}µ•ÍÍ…” (€€€€€€€€€€€€€€€€€€€€€€€•Ù•¹Ğ¹É•Á±å}Ñ½­•¸°(€€€€€€€€€€€€€€€€€€€€€€€Q•áÑM•¹‘5•ÍÍ…” (€€€€€€€€€€€€€€€€€€€€€€€€€€€Ñ•áĞô (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‹¢®/¦î{¦Z/’â/¦v‹¦ÖC¾ò3¦ã’â’ö7–ºÛ’êë–
Ï¦¦
¢®/¾òiq¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€˜‰íÍ¡…É•}ÕÉ¥ôˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸(€€€€€€€€€€€€€€€Í¡…É•}Á…”€ô€ (€€€€€€€€€€€€€€€€€€€Í¡…É•}¥¹Ù¥Ñ•}±¥™™}ÕÉ° ¤(€€€€€€€€€€€€€€€€€€€¥˜Í¡…É•}¥¹Ù¥Ñ•}±¥™™}ÕÉ°(€€€€€€€€€€€€€€€€€€€•±Í”€‰¡ÑÑÁÌè¼½±¥™˜¹±¥¹”¹µ”¼ÈÀÄÀàĞàÌÌÀµU¥ÅAAe½±¥™˜½Í¡…É”µ¥¹Ù¥Ñ”¹¡Ñµ°ˆ(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹É•Á±å}µ•ÍÍ…” (€€€€€€€€€€€€€€€€€€€•Ù•¹Ğ¹É•Á±å}Ñ½­•¸°(€€€€€€€€€€€€€€€€€€€Q•áÑM•¹‘5•ÍÍ…”¡Ñ•áĞõ˜‹¢®/¦Z/–V¦
¢®/¦‚–"’ê¯Ö›–ºÛ’êë¾òiq¹íÍ¡…É•}Á…•ôˆ¤°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€É•ÑÕÉ¸((€€€€€€€€€€€€Œƒ¦r¢š–æ¯–şg¾ò?Ş+š—šÆ–*§¾òk¢+–’§–º“–>«–n{ÖÇ’â 1%ƒ–—–>Œ(€€€€€€€€€€€¥˜Í½Í}™±½Ü¥Ì¹½Ğ9½¹”…¹ÍÑÉ¥ÁÁ•¥¸€ (€€€€€€€€€€€€€€€€‹¦r¢š–æ¯–şdˆ°(€€€€€€€€€€€€€€€€‰M=Lˆ°(€€€€€€€€€€€€€€€€‰Í½Ìˆ°(€€€€€€€€€€€€€€€€‹Ş+š—šÆ–*¤ˆ°(€€€€€€€€€€€€€€€€‹¦k~—–ºÛ’êèˆ°(€€€€€€€€€€€€€€€€‹¢¿Ö‡–ºÛ’êë¦š2$Ïš²„ˆ°(€€€€€€€€€€€€€€€€‹¦r¢š–æ¯–şgŠë¢ª4ˆ°(€€€€€€€€€€€€€€€€‰M=LƒŠë¢ª4€Èˆ°(€€€€€€€€€€€€€€€€‰M=LƒŠë¢ª4€Ìˆ°(€€€€€€€€€€€€€€€€‰M=Lƒ–>[šÚ ˆ°(€€€€€€€€€€€€€€€€‹–>[šÚ#¦r¢š–æ¯–şdˆ°(€€€€€€€€€€€€¤è(€€€€€€€€€€€€€€€}Í½Í}¡…¹‘±” (€€€€€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤°(€€€€€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€€€€€ÍÑÉ¥ÁÁ•°(€€€€€€€€€€€€€€€€€€€É•Á±å}Ñ½­•¸õ•Ù•¹Ğ¹É•Á±å}Ñ½­•¸°(€€€€€€€€€€€€€€€€€€€É½ÕÁ}¥õÉ½ÕÁ}¥°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€É•ÑÕÉ¸((€€€€€€€€€€€€Œ€ÈÀÈØ´ÀÜ´ÈÄÁ…Ñ €ÄÜè	=Pƒ.š/š~—¢¦ˆ¡4€¬ƒú“Ö¦÷–>¿R ¤(€€€€€€€€€€€¥˜ÍÑÉ¥ÁÁ•¥¸€ ‰	=Pƒ.š,ˆ°€‰‰½Ğƒ.š,ˆ°€‹š¦–f£’êë.š,ˆ°€‹š¦–f£’êë.šÎˆ¤è(€€€€€€€€€€€€€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤(€€€€€€€€€€€€€€€É½ÕÁÌ€ôÍÑ…Ñ”¹•Ğ ‰Õ…É‘¥…¹}É½ÕÁÌˆ°íô¤(€€€€€€€€€€€€€€€…Ñ¥Ù•}É½ÕÁÌ€ôÍÕ´ Ä™½Èœ¥¸É½ÕÁÌ¹Ù…±Õ•Ì ¤¥˜œ¹•Ğ ‰ÍÑ…ÑÕÌˆ¤€ôô€‰…Ñ¥Ù”ˆ¤(€€€€€€€€€€€€€€€ÕÁÑ¥µ•}Í•Œ€ô€¡‘…Ñ•Ñ¥µ”¹¹½Ü ¤€´…ÁÀ¹}ÍÑ…ÉÑ}Ñ¥µ”¤¹Ñ½Ñ…±}Í•½¹‘Ì ¤(€€€€€€€€€€€€€€€¡½ÕÉÌ€ô¥¹Ğ¡ÕÁÑ¥µ•}Í•Œ€¼¼€ÌØÀÀ¤(€€€€€€€€€€€€€€€µ¥¹ÕÑ•Ì€ô¥¹Ğ ¡ÕÁÑ¥µ•}Í•Œ€”€ÌØÀÀ¤€¼¼€ØÀ¤(€€€€€€€€€€€€€€€ÍÑ…ÑÕÍ}Ñ•áĞ€ô€ (€€€€€€€€€€€€€€€€€€€˜‹Â~’Xƒš"Gšb¿3š¾?š^—–æÏ–º'5qq¸ˆ(€€€€€€€€€€€€€€€€€€€˜‹–Æ³šZó3š¾?š^—–æÏ–º'7¦g–/šr7–.eqq¹qq¸ˆ(€€€€€€€€€€€€€€€€€€€˜‹Šrƒn»–&7–VR£’â´£–ŞË¦ê0í¡½ÕÉÍôƒ–Â?šfíµ¥¹ÕÑ•Íôƒ–"¥qq¸ˆ(€€€€€€€€€€€€€€€€€€€˜‹Â~F”ƒ–ŞË¢¢ï–+’êëšVàéí±•¸¡ÍÑ…Ñ”¹•Ğ ÕÍ•ÉÌœ°íô¤¥õqq¸ˆ(€€€€€€€€€€€€€€€€€€€˜‹Â~n‡¾â<ƒ–º#¢¶ßúéí…Ñ¥Ù•}É½ÕÁÍôƒú“šr'šV#Ú–ºiqq¹qq¸ˆ(€€€€€€€€€€€€€€€€€€€˜‹Â~Rœƒ–>¿R£š2’î£¢¢(¤éqq¸ˆ(€€€€€€€€€€€€€€€€€€€˜‹ŠˆƒÂ÷–"À€¼ƒ–‚Ç–æÏ–º%qq¸ˆ(€€€€€€€€€€€€€€€€€€€˜‹ŠˆƒÚ–ºk–º#¢¶ß’êéqq¸ˆ(€€€€€€€€€€€€€€€€€€€˜‹Šˆƒš~—r/šZçš† €¼ƒš"Gj.š-qq¹qq¸ˆ(€€€€€€€€€€€€€€€€€€€˜‹Â~F”ƒú“Öš2’îë–º#¢¶ßú“.š,€¼ƒÚ–ºk–º#¢¶ßú€¼ƒ’öÿR£¢ª«šb8ˆ(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹É•Á±å}µ•ÍÍ…”¡•Ù•¹Ğ¹É•Á±å}Ñ½­•¸°Q•áÑM•¹‘5•ÍÍ…”¡Ñ•áĞõÍÑ…ÑÕÍ}Ñ•áĞ¤¤(€€€€€€€€€€€€€€€É•ÑÕÉ¸((€€€€€€€€€€€€Œ€ÈÀÈØ´ÀÜ´ÈÄÁ…Ñ €ÄÄèƒ–º#¢¶ßú“nã¦^p€Ğƒ–,±•àƒš2’î£ú“Ö¦fC–ºh¤(€€€€€€€€€€€¥˜É½ÕÁ}¥è(€€€€€€€€€€€€€€€€Œ€Ä¤ƒÚ–ºk–º#¢¶ßú£’şwVg¢"+š2’î…±¥…Ì¤(€€€€€€€€€€€€€€€¥˜ÍÑÉ¥ÁÁ•¥¸€ ‹¦î{š"GÚ–ºk–º#¢¶ßúˆ°€‹Ú–ºk–º#¢¶ßúˆ°€‹Ú–ºk–æÏ–º'–º#¢¶ß–*§Bˆ¤è(€€€€€€€€€€€€€€€€€€€É•ÍÕ±Ğ°½‘”€ô‰¥¹‘}Õ…É‘¥…¹}É½ÕÀ (€€€€€€€€€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€€€€€€€€€ì‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°€‰É½ÕÁ}¥ˆèÉ½ÕÁ}¥‘ô°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€¥˜±•áM•¹‘5•ÍÍ…”¥Ì¹½Ğ9½¹”…¹Õ…É‘¥…¹}É½ÕÁ}‰¥¹‘}½¹™¥Éµ}™±•à¥Ì¹½Ğ9½¹”è(€€€€€€€€€€€€€€€€€€€€€€€¥˜½‘”€ôô€ÈÀÀè(€€€€€€€€€€€€€€€€€€€€€€€€€€€•¹É¥¡•€ô}•¹É¥¡}‰¥¹‘}É•ÍÕ±Ñ}™½É}™±•à¡É•ÍÕ±Ğ°±¥¹•}ÕÍ•É}¥¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÕ•ÍÍ}µÍÌ€ôl(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€±•áM•¹‘5•ÍÍ…” (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€…±Ñ}Ñ•áĞô‹Â~N,ƒ–º#¢¶ßú“¢Î¢¢(ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€½¹Ñ•¹ÑÌõÕ…É‘¥…¹}É½ÕÁ}‰¥¹‘}½¹™¥Éµ}™±•à¡•¹É¥¡•¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€t(€€€€€€€€€€€€€€€€€€€€€€€€€€€€ŒƒÚ–ºkš"C–*–ú3’â7¢š–s–r£¢Î¢¢+–6‡¾òk–4¹Õ‘”ƒ–º3š"C–º#¢¶ß’êë¾ò?š>C¦K¢¢·–ºh(€€€€€€€€€€€€€€€€€€€€€€€€€€€¥˜¹½ĞÉ•ÍÕ±Ğ¹•Ğ ‰…±É•…‘å}‰½Õ¹ˆ¤è(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¹Õ‘”€ô€ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€Õ…É‘¥…¹}É½ÕÁ}Í•ÑÕÁ}¹Õ‘•}Ñ•áĞ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€•¹É¥¡•¹•Ğ ‰Õ…É‘¥…¹}½Õ¹Ğˆ°€À¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€•¹É¥¡•¹•Ğ ‰Õ…É‘¥…¹}±¥µ¥Ğˆ°€Ô¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€•¹É¥¡•¹•Ğ ‰•µ•É•¹å}½Õ¹Ğˆ°€À¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€•¹É¥¡•¹•Ğ ‰•µ•É•¹å}±¥µ¥Ğˆ°€È¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¥˜Õ…É‘¥…¹}É½ÕÁ}Í•ÑÕÁ}¹Õ‘•}Ñ•áĞ¥Ì¹½Ğ9½¹”(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€•±Í”€ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‹Â~:$ƒ–º#¢¶ßú“–ŞË–îë®/š"C–*¾òq¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‹–îë¢¶Ã–7–º3š"C¾òkšZÃ–Š{š‚ã–ş–º#¢¶ß’êëŞ+š—¢¿Ö‡’êë¢¢·–ºkš¾?š^—š>C¦Kšf¦ZOˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÕ•ÍÍ}µÍÌ¹…ÁÁ•¹¡Q•áÑM•¹‘5•ÍÍ…”¡Ñ•áĞõ¹Õ‘”¤¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹É•Á±å}µ•ÍÍ…”¡•Ù•¹Ğ¹É•Á±å}Ñ½­•¸°ÍÕ•ÍÍ}µÍÌ¤(€€€€€€€€€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€€€€€€€€€É•…Í½¸€ôÉ•ÍÕ±Ğ¹•Ğ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰É•Á±å}Ñ•áĞˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‹¦g–/ú“Ön»–&7‡šÎW–VR£–º#¢¶ß–*¢ô³¢®/šª‹š~”€Üääƒ¢¢¦ZÇ.š/š"[RÇ–:–îë®/¢šN7’öpˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹É•Á±å}µ•ÍÍ…” (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€•Ù•¹Ğ¹É•Á±å}Ñ½­•¸°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€±•áM•¹‘5•ÍÍ…” (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€…±Ñ}Ñ•áĞô‹Šv0ƒ‡šÎWÚ–ºkš¶“úˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€½¹Ñ•¹ÑÌõÕ…É‘¥…¹}É½ÕÁ}‰¥¹‘}™…¥±}™±•à¡É•…Í½¸¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€€€€€€Œ™…±±‰…¬ƒÒSšZ–¶_¾òkš"C–*–n{¢š–në–ºk3š"G–ŞË–º3š"C–º#¢¶ßú“¢¢·–ºk4(€€€€€€€€€€€€€€€€€€€€€€€¥˜½‘”€ôô€ÈÀÀè(€€€€€€€€€€€€€€€€€€€€€€€€€€€É•Á±å}Ñ•áĞ€ô€ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‹š"G–ŞË–º3š"C–º#¢¶ßú“¢¢·–ºiq¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€˜‹n»–&7–ŞËÚ–ºhíÉ•ÍÕ±Ğ¹•Ğ Õ…É‘¥…¹}É½ÕÁ}½Õ¹Ğœ°€Ä¥ô¼ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€˜‰íÉ•ÍÕ±Ğ¹•Ğ Õ…É‘¥…¹}É½ÕÁ}±¥µ¥Ğœ°€Ì¥ôƒ–/ú“Öˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€¥˜¹½ĞÉ•ÍÕ±Ğ¹•Ğ ‰…±É•…‘å}‰½Õ¹ˆ¤…¹Õ…É‘¥…¹}É½ÕÁ}Í•ÑÕÁ}¹Õ‘•}Ñ•áĞ¥Ì¹½Ğ9½¹”è(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€•¹É¥¡•€ô}•¹É¥¡}‰¥¹‘}É•ÍÕ±Ñ}™½É}™±•à¡É•ÍÕ±Ğ°±¥¹•}ÕÍ•É}¥¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€É•Á±å}Ñ•áĞ€ô€ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€É•Á±å}Ñ•áĞ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¬€‰q¹q¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¬Õ…É‘¥…¹}É½ÕÁ}Í•ÑÕÁ}¹Õ‘•}Ñ•áĞ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€•¹É¥¡•¹•Ğ ‰Õ…É‘¥…¹}½Õ¹Ğˆ°€À¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€•¹É¥¡•¹•Ğ ‰Õ…É‘¥…¹}±¥µ¥Ğˆ°€Ô¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€•¹É¥¡•¹•Ğ ‰•µ•É•¹å}½Õ¹Ğˆ°€À¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€•¹É¥¡•¹•Ğ ‰•µ•É•¹å}±¥µ¥Ğˆ°€È¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€•±¥˜É•ÍÕ±Ğ¹•Ğ ‰Í¡½Õ±‘}±•…Ù”ˆ¤è(€€€€€€€€€€€€€€€€€€€€€€€€€€€É•Á±å}Ñ•áĞ€ô€ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‹¦g–/ú“Ön»–&7‡šÎW–VR£–º#¢¶ß–*¢÷–º#¢¶ßú“¦fCšr'šV#j€Üääƒšr#¢Êïš"[–æÓ¢Êïšr–N‡–îë®/¾òošr#¢Êïšr–’h€Äƒú“¾ò3–æÓ¢Êïšr–’h€Ìƒú“	q¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‹¢®/–#–º3š"C–6Òk¾ò3–7¦7šZÃ¦
¢®/3š¾?š^—–æÏ–º'7¾òoš"G>û–r£šr¦–ëú“Öˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€€€€€€€€€É•Á±å}Ñ•áĞ€ô€‹¦g–/ú“Ö–ŞËÚ–ºk–Û’î[šr–N‡¾ò3¢®/RÇ–:–îë®/¢º‡B–º#¢¶ß¢¢·–ºkˆ(€€€€€€€€€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹É•Á±å}µ•ÍÍ…”¡•Ù•¹Ğ¹É•Á±å}Ñ½­•¸°Q•áÑM•¹‘5•ÍÍ…”¡Ñ•áĞõÉ•Á±å}Ñ•áĞ¤¤(€€€€€€€€€€€€€€€€€€€¥˜É•ÍÕ±Ğ¹•Ğ ‰Í¡½Õ±‘}±•…Ù”ˆ¤è(€€€€€€€€€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹±•…Ù•}É½ÕÀ¡É½ÕÁ}¥¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸((€€€€€€€€€€€€€€€€Œ€È¤ƒ–º#¢¶ßú“.š/¾ò#–B¯3š~—r/–º#¢¶ßú“¾ò?š~—r/–º#¢¶ßú“.š/7š2'¦"W–"—–B7¾ò$(€€€€€€€€€€€€€€€¥˜ÍÑÉ¥ÁÁ•¥¸€ ‹–º#¢¶ßú“.š,ˆ°€‹ú“.š,ˆ°€‹.š,ˆ°€‹š~—r/–º#¢¶ßúˆ°€‹š~—r/–º#¢¶ßú“.š,ˆ¤è(€€€€€€€€€€€€€€€€€€€€Œƒš~—¢¦‹–&7–#–"ßšZÃšr³ú“š"C–N‡šVã¾ò3¦ÿ–7’î7¦†¿’ëÚ–ºkVÛ’â/j¢"+–ş¯œ(€€€€€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€€€€€É•™É•Í¡}Õ…É‘¥…¹}É½ÕÁ}µ•µ‰•É}Í¹…ÁÍ¡½Ğ (€€€€€€€€€€€€€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°É½ÕÁ}¥(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹•á•ÁÑ¥½¸ ‰ÍÑ…ÑÕÌµ•µ‰•ÈÍ¹…ÁÍ¡½ĞÉ•™É•Í ™…¥±•è€•Ìˆ°•áŒ¤(€€€€€€€€€€€€€€€€€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤(€€€€€€€€€€€€€€€€€€€ÁÉ½™¥±”€ô•Ñ}ÁÉ½™¥±”¡ÍÑ…Ñ”°±¥¹•}ÕÍ•É}¥¤½Èíô(€€€€€€€€€€€€€€€€€€€¥˜±•áM•¹‘5•ÍÍ…”¥Ì¹½Ğ9½¹”…¹Õ…É‘¥…¹}É½ÕÁ}ÍÑ…ÑÕÍ}™±•à¥Ì¹½Ğ9½¹”è(€€€€€€€€€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹É•Á±å}µ•ÍÍ…” (€€€€€€€€€€€€€€€€€€€€€€€€€€€•Ù•¹Ğ¹É•Á±å}Ñ½­•¸°(€€€€€€€€€€€€€€€€€€€€€€€€€€€±•áM•¹‘5•ÍÍ…” (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€…±Ñ}Ñ•áĞô‹–º#¢¶ßú“.š/¾ò#ú“Öš"C–N‡šVã¾ò$ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€½¹Ñ•¹ÑÌõÕ…É‘¥…¹}É½ÕÁ}ÍÑ…ÑÕÍ}™±•à¡ÁÉ½™¥±”°ÍÑ…Ñ”¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€€€€€É•Á±å}Ñ•áĞ€ô˜‹–º#¢¶ßú“šVã¦?¾òií±•¸¡ÁÉ½™¥±”¹•Ğ Õ…É‘¥…¹}É½ÕÁ}¥‘Ìœ¤½Èmt¥ôˆ(€€€€€€€€€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹É•Á±å}µ•ÍÍ…”¡•Ù•¹Ğ¹É•Á±å}Ñ½­•¸°Q•áÑM•¹‘5•ÍÍ…”¡Ñ•áĞõÉ•Á±å}Ñ•áĞ¤¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸((€€€€€€€€€€€€€€€€Œ€È´Ä¤ƒ’î+š^—–æÏ–º'–B7–Z»¾òk–>«šr'ú“Ö–îë®/¢¿º‡B–N‡–>¿r/¢¦ÏÒÃ¢ÎšZd(€€€€€€€€€€€€€€€¥˜ÍÑÉ¥ÁÁ•¥¸%1e}I=MQI}-e]=ILè(€€€€€€€€€€€€€€€€€€€É•Á±å}Ñ•áĞ°}ÍÑ…ÑÕÌ€ôÕ…É‘¥…¹}É½ÕÁ}‘…¥±å}ÍÑ…ÑÕÍ}Ñ•áĞ (€€€€€€€€€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥°É½ÕÁ}¥(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹É•Á±å}µ•ÍÍ…”¡•Ù•¹Ğ¹É•Á±å}Ñ½­•¸°Q•áÑM•¹‘5•ÍÍ…”¡Ñ•áĞõÉ•Á±å}Ñ•áĞ¤¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸((€€€€€€€€€€€€€€€€Œ€Ì¤ƒ’öÿR£¢ª«šb8€¼ƒ’öÿR£¢¢ª«šb8(€€€€€€€€€€€€€€€¥˜ÍÑÉ¥ÁÁ•¥¸€ ‹’öÿR£¢ª«šb8ˆ°€‹’öÿR£¢¢ª«šb8ˆ°€‹šVg–¶àˆ°€‹š;¦êóR ˆ¤è(€€€€€€€€€€€€€€€€€€€¥˜±•áM•¹‘5•ÍÍ…”¥Ì¹½Ğ9½¹”…¹Õ…É‘¥…¹}É½ÕÁ}ÕÍ•É}Õ¥‘•}™±•à¥Ì¹½Ğ9½¹”è(€€€€€€€€€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹É•Á±å}µ•ÍÍ…” (€€€€€€€€€€€€€€€€€€€€€€€€€€€•Ù•¹Ğ¹É•Á±å}Ñ½­•¸°(€€€€€€€€€€€€€€€€€€€€€€€€€€€±•áM•¹‘5•ÍÍ…” (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€…±Ñ}Ñ•áĞô‹Â~NXƒ–º#¢¶ßú“’öÿR£¢ª«šb8ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€½¹Ñ•¹ÑÌõÕ…É‘¥…¹}É½ÕÁ}ÕÍ•É}Õ¥‘•}™±•à ¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹É•Á±å}µ•ÍÍ…” (€€€€€€€€€€€€€€€€€€€€€€€€€€€•Ù•¹Ğ¹É•Á±å}Ñ½­•¸°(€€€€€€€€€€€€€€€€€€€€€€€€€€€Q•áÑM•¹‘5•ÍÍ…”¡Ñ•áĞô‹’öÿR£¢ª«šb8èÄ»–6Òh€ÜääƒŠH€È»–îëúƒŠH€Ì»¦
3š¾?š^—–æÏ–º'7¦ËúƒŠH€Ğ»¦î{3Ú–ºk–º#¢¶ßú“7¾ò#–6Òk¾ò?Ú–ºk–ú3¢«–.Wš"C
ë–º#¢¶ßú“º‡B–N‡¾ò$ˆ¤°(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸((€€€€€€€€€€€€€€€€Œ€Ğ¤ƒº‡B–N‡¢¢·–ºh€¼ƒš;¦êó¢¢·º‡B–N„€¼ƒú“Ö¢¢·–ºh(€€€€€€€€€€€€€€€¥˜ÍÑÉ¥ÁÁ•¥¸€ ‹º‡B–N‡¢¢·–ºhˆ°€‹¢¢·º‡B–N„ˆ°€‹š;¦êó¢¢·º‡B–N„ˆ°€ˆÛš¶—¦¦|ˆ°€‹ú“Ö¢¢·–ºhˆ¤è(€€€€€€€€€€€€€€€€€€€¥˜±•áM•¹‘5•ÍÍ…”¥Ì¹½Ğ9½¹”…¹Õ…É‘¥…¹}É½ÕÁ}…‘µ¥¹}Í•ÑÕÁ}™±•à¥Ì¹½Ğ9½¹”è(€€€€€€€€€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹É•Á±å}µ•ÍÍ…” (€€€€€€€€€€€€€€€€€€€€€€€€€€€•Ù•¹Ğ¹É•Á±å}Ñ½­•¸°(€€€€€€€€€€€€€€€€€€€€€€€€€€€±•áM•¹‘5•ÍÍ…” (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€…±Ñ}Ñ•áĞô‹Šjg¾â<ƒ¢¢·–ºk3š¾?š^—–æÏ–º'7
ëº‡B–N„€Øƒš¶—¦¦|ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€½¹Ñ•¹ÑÌõÕ…É‘¥…¹}É½ÕÁ}…‘µ¥¹}Í•ÑÕÁ}™±•à ¤°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹É•Á±å}µ•ÍÍ…” (€€€€€€€€€€€€€€€€€€€€€€€€€€€•Ù•¹Ğ¹É•Á±å}Ñ½­•¸°(€€€€€€€€€€€€€€€€€€€€€€€€€€€Q•áÑM•¹‘5•ÍÍ…”¡Ñ•áĞô‹º‡B–N‡¢¢·–ºh€Øƒš¶—¦¦|èÄ»ú“–>Ï’â+3Š&‡7ŠH€È»¦ãš"C–N„ƒŠH€Ì»¦Vßš2'3š¾?š^—–æÏ–º'4ƒŠH€Ğ»¢¢·
ëº‡B–N„ƒŠH€Ô»Šë–ºhƒŠH€Ø»–º3š"@ˆ¤°(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸((€€€€€€€€€€€€€€€€Œƒšr«²›–B#’â+¢şÃšb;Šëš2’î“¾òkú“¢+’şwš2–º'¦vs¾ò3¦ÿ–7š&OšNû–ºÛ’êë–Â7¢¦Ç(€€€€€€€€€€€€€€€€Œ1%9=ƒ–ú3–>Ãj¢«–.W–n{š'’æš'¦^s¦Z'¾ò3–B›–&’î7–>¿¢÷RÇ–ú3–>Ã–>›–’[–n{šZ–¶_(€€€€€€€€€€€€€€€¥˜É½ÕÁ}¥è(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸((€€€€€€€€€€€€Œƒ¢¢+¾òkº‡B–N‡–>¿š~—3’î+–’§¢ªÃ¦
šÊK–‚Ç–æÏ–º'7¾ò#’â7¦r¦Z/ú“Öš>C¦K¾ò$(€€€€€€€€€€€¥˜¹½ĞÉ½ÕÁ}¥…¹ÍÑÉ¥ÁÁ•¥¸%1e}I=MQI}-e]=ILè(€€€€€€€€€€€€€€€É•Á±å}Ñ•áĞ°}ÍÑ…ÑÕÌ€ô½İ¹•É}Ñ½‘…å}Í…™•Ñå}É½ÍÑ•É}Ñ•áĞ (€€€€€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥°½¹™¥œõ…ÁÀ¹½¹™¥œ(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹É•Á±å}µ•ÍÍ…”¡•Ù•¹Ğ¹É•Á±å}Ñ½­•¸°Q•áÑM•¹‘5•ÍÍ…”¡Ñ•áĞõÉ•Á±å}Ñ•áĞ¤¤(€€€€€€€€€€€€€€€É•ÑÕÉ¸((€€€€€€€€€€€ÍÑ…ÑÕÌ€ô9½¹”(€€€€€€€€€€€¥˜…¹ä¡­•åİ½É¥¸Ñ•áĞ™½È­•åİ½É¥¸!-%9}-e]=IL¤è(€€€€€€€€€€€€€€€ÍÑ…ÑÕÌ€ôÉ•½É‘}¡•­¥¸ (€€€€€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€€€€€ì‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥‘ô°(€€€€€€€€€€€€€€€€€€€½¹™¥œõ…ÁÀ¹½¹™¥œ°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€É•Á±å}¥Ñ•µÌ€ô¹½Éµ…±¥é•}±¥¹•}É•Á±å}¥Ñ•µÌ (€€€€€€€€€€€€€€€€€€€‰Õ¥±‘}¡•­¥¹}ÍÕ•ÍÍ}Ñ•áĞ¡ÍÑ…ÑÕÌ°½¹™¥œõ…ÁÀ¹½¹™¥œ¤(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤(€€€€€€€€€€€€€€€ÁÉ½™¥±”€ô•Ñ}ÁÉ½™¥±”¡ÍÑ…Ñ”°±¥¹•}ÕÍ•É}¥¤(€€€€€€€€€€€€€€€É•Á±å}¥Ñ•µÌ€ôµ…å‰•}…ÑÑ…¡}•áÁ¥Éå}É•µ¥¹ (€€€€€€€€€€€€€€€€€€€É•Á±å}¥Ñ•µÌ°(€€€€€€€€€€€€€€€€€€€ÁÉ½™¥±”°(€€€€€€€€€€€€€€€€€€€¹½ÜõÕÉÉ•¹Ñ}…ÁÁ}Ñ¥µ”¡…ÁÀ¹½¹™¥œ¤°(€€€€€€€€€€€€€€€€€€€ÍÑ…Ñ”õÍÑ…Ñ”°(€€€€€€€€€€€€€€€€€€€‘…Ñ…}™¥±”õ…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€µ•ÍÍ…•Ì€ômt(€€€€€€€€€€€€€€€™½È¥Ñ•´¥¸É•Á±å}¥Ñ•µÌè(€€€€€€€€€€€€€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡¥Ñ•´°‘¥Ğ¤…¹¥Ñ•´¹•Ğ ‰ÑåÁ”ˆ¤€ôô€‰™±•àˆè(€€€€€€€€€€€€€€€€€€€€€€€¥˜±•áM•¹‘5•ÍÍ…”¥Ì¹½Ğ9½¹”è(€€€€€€€€€€€€€€€€€€€€€€€€€€€µ•ÍÍ…•Ì¹…ÁÁ•¹ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€±•áM•¹‘5•ÍÍ…” (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€…±Ñ}Ñ•áĞõÍÑÈ¡¥Ñ•´¹•Ğ ‰…±ÑQ•áĞˆ¤½È€‹šZçš†#š>C¦Hˆ¥lèĞÀÁt°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€½¹Ñ•¹ÑÌõ¥Ñ•´¹•Ğ ‰½¹Ñ•¹ÑÌˆ¤½Èíô°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€€€€€€€€€µ•ÍÍ…•Ì¹…ÁÁ•¹ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€Q•áÑM•¹‘5•ÍÍ…”¡Ñ•áĞõÍÑÈ¡¥Ñ•´¹•Ğ ‰…±ÑQ•áĞˆ¤½È€‹šZçš†#š>C¦Hˆ¤¤(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€€€€€µ•ÍÍ…•Ì¹…ÁÁ•¹¡Q•áÑM•¹‘5•ÍÍ…”¡Ñ•áĞõÍÑÈ¡¥Ñ•´¤¤¤(€€€€€€€€€€€€€€€¥˜Í¡½Õ±‘}É•…Ñ•}ÍÕÁÁ½ÉÑ}Ñ¥­•Ğ¡Ñ•áĞ¤è(€€€€€€€€€€€€€€€€€€€É•…Ñ•}ÍÕÁÁ½ÉÑ}Ñ¥­•Ğ (€€€€€€€€€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰µ•ÍÍ…”ˆèÑ•áĞ°(€€€€€€€€€€€€€€€€€€€€€€€ô°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€¥˜µ•ÍÍ…•Ìè(€€€€€€€€€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹É•Á±å}µ•ÍÍ…”¡•Ù•¹Ğ¹É•Á±å}Ñ½­•¸°µ•ÍÍ…•Ì¤(€€€€€€€€€€€€€€€É•ÑÕÉ¸(€€€€€€€€€€€•±¥˜…¹ä¡­•åİ½É¥¸Ñ•áĞ™½È­•åİ½É¥¸MQQUM}-e]=IL¤è(€€€€€€€€€€€€€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤(€€€€€€€€€€€€€€€ÍÑ…ÑÕÌ€ô‰Õ¥±‘}ÍÑ…ÑÕÌ¡•Ñ}ÁÉ½™¥±”¡ÍÑ…Ñ”°±¥¹•}ÕÍ•É}¥¤¤(€€€€€€€€€€€¥˜Í¡½Õ±‘}É•…Ñ•}ÍÕÁÁ½ÉÑ}Ñ¥­•Ğ¡Ñ•áĞ¤è(€€€€€€€€€€€€€€€É•…Ñ•}ÍÕÁÁ½ÉÑ}Ñ¥­•Ğ (€€€€€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€€€€€‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€€€€€€€€€€‰µ•ÍÍ…”ˆèÑ•áĞ°(€€€€€€€€€€€€€€€€€€€ô°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€É•Á±å}Ñ•áĞ€ô€ (€€€€€€€€€€€€€€€€€€€€‹’öƒj–V?¦†3–ŞËÚO¢¢c¦2’â/’ú	q¹q¸ˆ(€€€€€€€€€€€€€€€€€€€€‹Â~N¤ƒ–º‹šr7šr–r €ÇŠLÌƒ–/–Ş—’ös–’§–Ÿ¦?¦81%9ƒ–ºcšZç–âÏ¢f–n{¢š	q¹q¸ˆ(€€€€€€€€€€€€€€€€€€€˜‹’æ–>¿’î—–#r/–âã¢š/–V?¦†3¾òií±¥¹•}±¥™™}ÕÉ° ™…Äœ¥õq¹q¸ˆ(€€€€€€€€€€€€€€€€€€€€‹¢.—šb¿®/–6Ï–6Ç¦j«¾ò3¢®/–#šJ—š&L€ÄÄçˆ(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€É•Á±å}Ñ•áĞ€ô±¥¹•}…ÕÑ½}É•Á±å}Ñ•áĞ¡Ñ•áĞ°ÍÑ…ÑÕÌ¤(€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹É•Á±å}µ•ÍÍ…”¡•Ù•¹Ğ¹É•Á±å}Ñ½­•¸°Q•áÑM•¹‘5•ÍÍ…”¡Ñ•áĞõÉ•Á±å}Ñ•áĞ¤¤((€€€€€€€Í¥¹…ÑÕÉ”€ôÉ•ÅÕ•ÍĞ¹¡•…‘•ÉÌ¹•Ğ ‰`µ1¥¹”µM¥¹…ÑÕÉ”ˆ°€ˆˆ¤(€€€€€€€€ŒUÍ”É…Ü‰åÑ•ÌÑ¡•¸‘•½‘”Í¼!5µ…Ñ¡•Ì1%9ÌÍ¥¹•‰½‘ä•á…Ñ±ä(€€€€€€€‰½‘å}‰åÑ•Ì€ôÉ•ÅÕ•ÍĞ¹•Ñ}‘…Ñ„¡…¡”õQÉÕ”°…Í}Ñ•áĞõ…±Í”¤½Èˆˆˆ(€€€€€€€ÑÉäè(€€€€€€€€€€€‰½‘ä€ô‰½‘å}‰åÑ•Ì¹‘•½‘” ‰ÕÑ˜´àˆ¤(€€€€€€€•á•ÁĞU¹¥½‘••½‘•ÉÉ½Èè(€€€€€€€€€€€€Œ1%9½¹Í½±”Y•É¥™äµÕÍĞ¹•Ù•ÈÍ•”¹½¸´ÈÀÀ(€€€€€€€€€€€…ÁÀ¹±½•È¹•ÉÉ½È ‰…±±‰…¬‰½‘ä¹½ĞÕÑ˜´à±•¸ô•Ìˆ°±•¸¡‰½‘å}‰åÑ•Ì¤¤(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¬ˆèQÉÕ”°€‰Ù•É¥™äˆèQÉÕ•ô¤((€€€€€€€€ŒM½™Ğµ…•ÁĞè•µÁÑä€¼¹¼µ•Ù•¹ÑÌÁ…å±½…‘Ì…±İ…åÌ€ÈÀÀ€¡1%9Y•É¥™ä‰ÕÑÑ½¸¤(€€€€€€€ÍÑÉ¥ÁÁ•€ô€¡‰½‘ä½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€¥˜¹½ĞÍÑÉ¥ÁÁ•è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¬ˆèQÉÕ”°€‰Ù•É¥™äˆèQÉÕ•ô¤(€€€€€€€ÑÉäè(€€€€€€€€€€€ÁÉ½‰”€ô©Í½¸¹±½…‘Ì¡ÍÑÉ¥ÁÁ•¤(€€€€€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡ÁÉ½‰”°‘¥Ğ¤…¹¹½Ğ€¡ÁÉ½‰”¹•Ğ ‰•Ù•¹ÑÌˆ¤½Èmt¤è(€€€€€€€€€€€€€€€€ŒMÑ¥±°ÉÕ¸¡…¹‘±•Èİ¡•¸Í¥¹…ÑÕÉ”¥ÌÙ…±¥ì½¸µ¥Íµ…Ñ É•ÑÕÉ¸€ÈÀÀ(€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€¡…¹‘±•È¹¡…¹‘±”¡‰½‘ä°Í¥¹…ÑÕÉ”¤(€€€€€€€€€€€€€€€•á•ÁĞ%¹Ù…±¥‘M¥¹…ÑÕÉ•ÉÉ½Èè(€€€€€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹İ…É¹¥¹œ (€€€€€€€€€€€€€€€€€€€€€€€€‰1%9Ù•É¥™ä½•µÁÑä•Ù•¹ÑÌ‰…Í¥¹…ÑÕÉ”‰½‘å}±•¸ô•ÌÍ•É•Ñ}±•¸ô•Ìˆ°(€€€€€€€€€€€€€€€€€€€€€€€±•¸¡‰½‘å}‰åÑ•Ì¤°(€€€€€€€€€€€€€€€€€€€€€€€±•¸¡Í•É•Ğ½È€ˆˆ¤°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè€€Œ¹½Å„è	1ÀÀÄ(€€€€€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹İ…É¹¥¹œ ‰1%9Ù•É¥™ä½•µÁÑä¡…¹‘±”Í­¥Àè€•Ìˆ°ÑåÁ”¡•áŒ¤¹}}¹…µ•}|¤(€€€€€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¬ˆèQÉÕ”°€‰Ù•É¥™äˆèQÉÕ•ô¤(€€€€€€€•á•ÁĞá•ÁÑ¥½¸è(€€€€€€€€€€€Á…ÍÌ((€€€€€€€ÑÉäè(€€€€€€€€€€€¡…¹‘±•È¹¡…¹‘±”¡‰½‘ä°Í¥¹…ÑÕÉ”¤(€€€€€€€•á•ÁĞ%¹Ù…±¥‘M¥¹…ÑÕÉ•ÉÉ½Èè(€€€€€€€€€€€€Œ1%9‘½Ìè…±İ…åÌÉ•ÑÕÉ¸€ÈÀÀÑ¼Ñ¡”Á±…Ñ™½É´ì‘¼¹½ĞÁÉ½•ÍÌ‰…µÍ¥œ•Ù•¹ÑÌ(€€€€€€€€€€€…ÁÀ¹±½•È¹İ…É¹¥¹œ (€€€€€€€€€€€€€€€€‰¥¹Ù…±¥1%9Í¥¹…ÑÕÉ”¥¹½É•‰½‘å}±•¸ô•ÌÍ¥}±•¸ô•ÌÍ•É•Ñ}±•¸ô•Ìˆ°(€€€€€€€€€€€€€€€±•¸¡‰½‘å}‰åÑ•Ì¤°(€€€€€€€€€€€€€€€±•¸¡Í¥¹…ÑÕÉ”½È€ˆˆ¤°(€€€€€€€€€€€€€€€±•¸¡Í•É•Ğ½È€ˆˆ¤°(€€€€€€€€€€€€¤(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¬ˆèQÉÕ”°€‰Í¥¹…ÑÕÉ”ˆè€‰¥¹½É•‰ô¤(€€€€€€€•á•ÁĞ1¥¹•	½ÑÁ¥ÉÉ½È…Ì•áŒè(€€€€€€€€€€€…ÁÀ¹±½•È¹•á•ÁÑ¥½¸ ‰…±±‰…¬1¥¹•	½ÑÁ¥ÉÉ½Èè€•Ìˆ°•áŒ¤(€€€€€€€€€€€€ŒMÑ¥±°€ÈÀÀÍ¼1%9‘½•Ì¹½Ğ‘¥Í…‰±”İ•‰¡½½¬€¼™…¥°Y•É¥™äµ±¥­”ÁÉ½‰•Ì(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¬ˆèQÉÕ”°€‰±¥¹•}…Á¥}•ÉÉ½ÈˆèQÉÕ•ô¤(€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè€€Œ¹½Å„è	1ÀÀÄ(€€€€€€€€€€€…ÁÀ¹±½•È¹•á•ÁÑ¥½¸ ‰…±±‰…¬Õ¹•áÁ•Ñ•è€•Ìˆ°•áŒ¤(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¬ˆèQÉÕ”°€‰•ÉÉ½É}¥¹½É•ˆèQÉÕ•ô¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¬ˆèQÉÕ•ô¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½İ…É¹¥¹œ½…¹•°ˆ¤(€€€‘•˜İ…É¹¥¹}…¹•±}…Á¤ ¤è(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡…¹•±}İ…É¹¥¹œ¡…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…°…ÁÀ¹½¹™¥œ¤¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½Í•ÑÑ¥¹Ìˆ¤(€€€‘•˜Í•ÑÑ¥¹Ì ¤è(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡Í…Ù•}Í•ÑÑ¥¹Í}™½É}ÁÉ½™¥±”¡…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½‰¥±±¥¹œ½ÁÉ•™•É•¹•Ìˆ¤(€€€‘•˜‰¥±±¥¹}ÁÉ•™•É•¹•Í}…Á¤ ¤è(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€‘…Ñ„°½‘”€ôÍ…Ù•}‰¥±±¥¹}ÁÉ•™•É•¹•Ì¡…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½‰¥±±¥¹œ½…¹•°ˆ¤(€€€‘•˜‰¥±±¥¹}…¹•±}…Á¤ ¤è(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€‘…Ñ„°½‘”€ô…¹•±}É•ÕÉÉ¥¹}ÍÕ‰ÍÉ¥ÁÑ¥½¸ (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…°…ÁÀ¹½¹™¥œ(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½Á…åµ•¹ÑÌ½½É‘•ÉÌˆ¤(€€€‘•˜Á…åµ•¹Ñ}½É‘•ÉÍ}…Á¤ ¤è(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€‘…Ñ„°½‘”€ôÉ•…Ñ•}Á…åµ•¹Ñ}½É‘•È¡…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…°…ÁÀ¹½¹™¥œ¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹Á½ÍĞ ˆ½İ•‰¡½½¬½¹•İ•‰Á…äˆ¤(€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½Á…åµ•¹Ğ½¹•İ•‰Á…ä½¹½Ñ¥™äˆ¤(€€€‘•˜¹•İ•‰Á…å}İ•‰¡½½¬ ¤è(€€€€€€€€ˆˆ‹¢^7šZÀ9½Ñ¥™åUI0ƒŠPƒ¦¦_Â÷–ú3¢«–.W¦Z/¦kšZçš†#¾ò#–«¶$½¹™¥É·¾ò'((€€€€€€€ƒ–§–/¢Ş¿–úG¶'šV#¾ò3šN’â–†¯–—–V–ê_–ú3–>Ã–6Ï–>¿¾òh(€€€€€€€€´€½…Á¤½Á…åµ•¹Ğ½¹•İ•‰Á…ä½¹½Ñ¥™ç¾ò!¡•­½ÕĞƒ¦‚C¢¢·¾ò$(€€€€€€€€´€½İ•‰¡½½¬½¹•İ•‰Á…ä(€€€€€€€ƒš"C–*šf–n{–
ÏÒSšZ–¶\MUMO¾ò#¢^7šZÃ–?––÷¾ò'(€€€€€€€€ˆˆˆ(€€€€€€€™½É´€ôÉ•ÅÕ•ÍĞ¹™½É´¹Ñ½}‘¥Ğ ¤¥˜É•ÅÕ•ÍĞ¹™½É´•±Í”€¡É•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô¤(€€€€€€€¥˜¹•İ•‰Á…ä¥Ì9½¹”è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰¹•İ•‰Á…äµ½‘Õ±”µ¥ÍÍ¥¹œ‰ô¤°€ÔÀÌ(€€€€€€€Á…ÉÍ•°•ÉÉ½È€ô¹•İ•‰Á…ä¹Á…ÉÍ•}¹½Ñ¥™å}Á…å±½…¡™½É´°…ÁÀ¹½¹™¥œ¤(€€€€€€€¥˜•ÉÉ½Èè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè•ÉÉ½Éô¤°€ĞÀÀ(€€€€€€€¥˜¹½Ğ¹•İ•‰Á…ä¹¹½Ñ¥™å}ÍÕ•ÍÌ¡Á…ÉÍ•¤è(€€€€€€€€€€€É•ÑÕÉ¸I•ÍÁ½¹Í” ‰MUMLˆ°µ¥µ•ÑåÁ”ô‰Ñ•áĞ½Á±…¥¸ˆ¤°€ÈÀÀ(€€€€€€€‘…Ñ„°½‘”€ô½¹™¥Éµ}Á…åµ•¹Ñ}½É‘•È (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€‰½É‘•É}¥ˆèÁ…ÉÍ•¹•Ğ ‰½É‘•É}¥ˆ¤°(€€€€€€€€€€€€€€€€‰ÑÉ…¹Í…Ñ¥½¹}¥ˆèÁ…ÉÍ•¹•Ğ ‰ÑÉ…¹Í…Ñ¥½¹}¥ˆ¤°(€€€€€€€€€€€€€€€€‰…µ½Õ¹ĞˆèÁ…ÉÍ•¹•Ğ ‰…µ½Õ¹Ğˆ¤°(€€€€€€€€€€€€€€€€‰ÁÉ½Ù¥‘•Èˆè€‰¹•İ•‰Á…äˆ°(€€€€€€€€€€€ô°(€€€€€€€€€€€…ÁÀ¹½¹™¥œ°(€€€€€€€€¤(€€€€€€€¥˜½‘”€øô€ĞÀÀè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”(€€€€€€€É•ÑÕÉ¸I•ÍÁ½¹Í” ‰MUMLˆ°µ¥µ•ÑåÁ”ô‰Ñ•áĞ½Á±…¥¸ˆ¤°€ÈÀÀ((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½Á…åµ•¹Ğ½•Á…ä½¹½Ñ¥™äˆ¤(€€€‘•˜•Á…å}İ•‰¡½½¬ ¤è(€€€€€€€™½É´€ôÉ•ÅÕ•ÍĞ¹™½É´¹Ñ½}‘¥Ğ ¤¥˜É•ÅÕ•ÍĞ¹™½É´•±Í”€¡É•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô¤(€€€€€€€¥˜•Á…ä¥Ì9½¹”è(€€€€€€€€€€€É•ÑÕÉ¸I•ÍÁ½¹Í” ˆÁñÁ…åµ•¹Ğµ½‘Õ±”µ¥ÍÍ¥¹œˆ°µ¥µ•ÑåÁ”ô‰Ñ•áĞ½Á±…¥¸ˆ¤°€ÔÀÌ(€€€€€€€Á…ÉÍ•°•ÉÉ½È€ô•Á…ä¹Á…ÉÍ•}¹½Ñ¥™å}Á…å±½…¡™½É´°…ÁÀ¹½¹™¥œ¤(€€€€€€€¥˜•ÉÉ½Èè(€€€€€€€€€€€É•ÑÕÉ¸I•ÍÁ½¹Í”¡˜ˆÁñí•ÉÉ½Éôˆ°µ¥µ•ÑåÁ”ô‰Ñ•áĞ½Á±…¥¸ˆ¤°€ĞÀÀ(€€€€€€€¥˜¹½Ğ•Á…ä¹¹½Ñ¥™å}ÍÕ•ÍÌ¡Á…ÉÍ•°…ÁÀ¹½¹™¥œ¤è(€€€€€€€€€€€É•ÑÕÉ¸I•ÍÁ½¹Í” ˆÅñ=,ˆ°µ¥µ•ÑåÁ”ô‰Ñ•áĞ½Á±…¥¸ˆ¤°€ÈÀÀ(€€€€€€€‘…Ñ„°½‘”€ô½¹™¥Éµ}Á…åµ•¹Ñ}½É‘•È (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€‰½É‘•É}¥ˆèÁ…ÉÍ•¹•Ğ ‰½É‘•É}¥ˆ¤°(€€€€€€€€€€€€€€€€‰ÑÉ…¹Í…Ñ¥½¹}¥ˆèÁ…ÉÍ•¹•Ğ ‰ÑÉ…¹Í…Ñ¥½¹}¥ˆ¤°(€€€€€€€€€€€€€€€€‰…µ½Õ¹ĞˆèÁ…ÉÍ•¹•Ğ ‰…µ½Õ¹Ğˆ¤°(€€€€€€€€€€€€€€€€‰ÁÉ½Ù¥‘•Èˆè€‰•Á…äˆ°(€€€€€€€€€€€ô°(€€€€€€€€€€€…ÁÀ¹½¹™¥œ°(€€€€€€€€¤(€€€€€€€¥˜½‘”€øô€ĞÀÀè(€€€€€€€€€€€É•ÑÕÉ¸I•ÍÁ½¹Í”¡˜ˆÁñí‘…Ñ„¹•Ğ •ÉÉ½Èœ°€½É‘•ÈÕÁ‘…Ñ”™…¥±•œ¥ôˆ°µ¥µ•ÑåÁ”ô‰Ñ•áĞ½Á±…¥¸ˆ¤°½‘”(€€€€€€€É•ÑÕÉ¸I•ÍÁ½¹Í” ˆÅñ=,ˆ°µ¥µ•ÑåÁ”ô‰Ñ•áĞ½Á±…¥¸ˆ¤°€ÈÀÀ((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½Á…åµ•¹Ğ½•Á…ä½Á•É¥½µ¹½Ñ¥™äˆ¤(€€€‘•˜•Á…å}Á•É¥½‘}İ•‰¡½½¬ ¤è(€€€€€€€™½É´€ôÉ•ÅÕ•ÍĞ¹™½É´¹Ñ½}‘¥Ğ ¤¥˜É•ÅÕ•ÍĞ¹™½É´•±Í”€¡É•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô¤(€€€€€€€¥˜•Á…ä¥Ì9½¹”è(€€€€€€€€€€€É•ÑÕÉ¸I•ÍÁ½¹Í” ˆÁñÁ…åµ•¹Ğµ½‘Õ±”µ¥ÍÍ¥¹œˆ°µ¥µ•ÑåÁ”ô‰Ñ•áĞ½Á±…¥¸ˆ¤°€ÔÀÌ(€€€€€€€Á…ÉÍ•°•ÉÉ½È€ô•Á…ä¹Á…ÉÍ•}¹½Ñ¥™å}Á…å±½…¡™½É´°…ÁÀ¹½¹™¥œ¤(€€€€€€€¥˜•ÉÉ½Èè(€€€€€€€€€€€É•ÑÕÉ¸I•ÍÁ½¹Í”¡˜ˆÁñí•ÉÉ½Éôˆ°µ¥µ•ÑåÁ”ô‰Ñ•áĞ½Á±…¥¸ˆ¤°€ĞÀÀ(€€€€€€€¥˜¹½Ğ•Á…ä¹¹½Ñ¥™å}ÍÕ•ÍÌ¡Á…ÉÍ•°…ÁÀ¹½¹™¥œ¤è(€€€€€€€€€€€É•ÑÕÉ¸I•ÍÁ½¹Í” ˆÅñ=,ˆ°µ¥µ•ÑåÁ”ô‰Ñ•áĞ½Á±…¥¸ˆ¤°€ÈÀÀ(€€€€€€€Á…ÉÍ•¹ÕÁ‘…Ñ”¡ì‰ÍÑ…ÑÕÌˆè€‰MUMLˆ°€‰ÁÉ½Ù¥‘•Èˆè€‰•Á…ä‰ô¤(€€€€€€€‘…Ñ„°½‘”€ôÁÉ½•ÍÍ}Á•É¥½‘}¹½Ñ¥™¥…Ñ¥½¸ (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…ÉÍ•°…ÁÀ¹½¹™¥œ(€€€€€€€€¤(€€€€€€€¥˜½‘”€øô€ĞÀÀè(€€€€€€€€€€€É•ÑÕÉ¸I•ÍÁ½¹Í”¡˜ˆÁñí‘…Ñ„¹•Ğ •ÉÉ½Èœ°€½É‘•ÈÕÁ‘…Ñ”™…¥±•œ¥ôˆ°µ¥µ•ÑåÁ”ô‰Ñ•áĞ½Á±…¥¸ˆ¤°½‘”(€€€€€€€É•ÑÕÉ¸I•ÍÁ½¹Í” ˆÅñ=,ˆ°µ¥µ•ÑåÁ”ô‰Ñ•áĞ½Á±…¥¸ˆ¤°€ÈÀÀ((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½Á…åµ•¹Ğ½¹•İ•‰Á…ä½Á•É¥½µ¹½Ñ¥™äˆ¤(€€€‘•˜¹•İ•‰Á…å}Á•É¥½‘}İ•‰¡½½¬ ¤è(€€€€€€€™½É´€ôÉ•ÅÕ•ÍĞ¹™½É´¹Ñ½}‘¥Ğ ¤¥˜É•ÅÕ•ÍĞ¹™½É´•±Í”€¡É•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô¤(€€€€€€€¥˜¹•İ•‰Á…ä¥Ì9½¹”è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰¹•İ•‰Á…äµ½‘Õ±”µ¥ÍÍ¥¹œ‰ô¤°€ÔÀÌ(€€€€€€€Á…ÉÍ•°•ÉÉ½È€ô¹•İ•‰Á…ä¹Á…ÉÍ•}Á•É¥½‘}Á…å±½…¡™½É´°…ÁÀ¹½¹™¥œ¤(€€€€€€€¥˜•ÉÉ½Èè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè•ÉÉ½Éô¤°€ĞÀÀ(€€€€€€€‘…Ñ„°½‘”€ôÁÉ½•ÍÍ}Á•É¥½‘}¹½Ñ¥™¥…Ñ¥½¸ (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…ÉÍ•°…ÁÀ¹½¹™¥œ(€€€€€€€€¤(€€€€€€€¥˜½‘”€øô€ĞÀÀè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”(€€€€€€€É•ÑÕÉ¸I•ÍÁ½¹Í” ‰MUMLˆ°µ¥µ•ÑåÁ”ô‰Ñ•áĞ½Á±…¥¸ˆ¤°€ÈÀÀ((€€€…ÁÀ¹É½ÕÑ” ˆ½Á…åµ•¹ĞµÍÕ•ÍÌˆ°µ•Ñ¡½‘Ìõl‰Pˆ°€‰A=MP‰t¤(€€€‘•˜Á…åµ•¹Ñ}ÍÕ•ÍÍ}Á…” ¤è(€€€€€€€€Œƒ¢^7šZÀI•ÑÕÉ¹UI0ƒ–âã’î”A=MPƒ–âÛ–n{’îcš²ûÖCšzs¾òo¢"Pƒ–B3š¢–n{–
ÌMA(€€€€€€€É•ÑÕÉ¸Í•¹‘}™É½µ}‘¥É•Ñ½Éä¡…ÁÀ¹ÍÑ…Ñ¥}™½±‘•È°€‰¥¹‘•à¹¡Ñµ°ˆ¤((€€€…ÁÀ¹•Ğ ˆ½…Á¤½½¹Ñ…ÑÌˆ¤(€€€‘•˜½¹Ñ…ÑÍ}•Ğ ¤è(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡íô°ÕÍ•}…ÉÌõQÉÕ”¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•Ñ}½¹Ñ…ÑÌ¡…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥¤¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½½¹Ñ…ÑÌˆ¤(€€€‘•˜½¹Ñ…ÑÍ}Á½ÍĞ ¤è(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€‘…Ñ„°½‘”€ôÍ…Ù•}½¹Ñ…ÑÌ¡…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹•Ğ ˆ½…Á¤½…±•¹‘…Èµ¹½Ñ•Ìˆ¤(€€€‘•˜…±•¹‘…É}¹½Ñ•Í}•Ğ ¤è(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡íô°ÕÍ•}…ÉÌõQÉÕ”¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€‘…Ñ„€ô•Ñ}…±•¹‘…É}¹½Ñ•Ì (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°€ÈÀÀ¥˜‘…Ñ„¹•Ğ ‰½¬ˆ¤•±Í”€ĞÀÌ((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…±•¹‘…Èµ¹½Ñ•Ìˆ¤(€€€‘•˜…±•¹‘…É}¹½Ñ•Í}Á½ÍĞ ¤è(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€‘…Ñ„°½‘”€ôÍ…Ù•}…±•¹‘…É}¹½Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½½¹Ñ…ÑÌ½…‘ˆ¤(€€€‘•˜½¹Ñ…ÑÍ}…‘ ¤è(€€€€€€€€ˆˆ‹šZÃ–Š{–Z»’â–º#¢¶ß’êë¢¿Ö‡’êëˆˆˆ(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€‘…Ñ„°½‘”€ô…‘‘}Í¥¹±•}½¹Ñ…Ğ¡…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥°Á…å±½…¤(€€€€€€€¥˜½‘”€ôô€ÈÀÀè(€€€€€€€€€€€É•ÍÁ½¹Í”€ôì‰½¬ˆèQÉÕ”°€‰½¹Ñ…Ğˆè‘…Ñ…l‰½¹Ñ…Ğ‰t°€‰½¹Ñ…ÑÌˆè‘…Ñ…l‰½¹Ñ…ÑÌ‰t°€‰½¹Ñ…Ñ}±¥µ¥Ğˆè‘…Ñ…l‰½¹Ñ…Ñ}±¥µ¥Ğ‰uô(€€€€€€€•±Í”è(€€€€€€€€€€€É•ÍÁ½¹Í”€ôì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè‘…Ñ„¹•Ğ ‰•ÉÉ½Èˆ¤°€‰™¥•±‘Ìˆè‘…Ñ„¹•Ğ ‰™¥•±‘Ìˆ¤°€‰½¹Ñ…Ñ}±¥µ¥Ğˆè‘…Ñ„¹•Ğ ‰½¹Ñ…Ñ}±¥µ¥Ğˆ¤°€‰ÕÉÉ•¹Ñ}½Õ¹Ğˆè‘…Ñ„¹•Ğ ‰ÕÉÉ•¹Ñ}½Õ¹Ğˆ¤°€‰µ•ÍÍ…”ˆè‘…Ñ„¹•Ğ ‰µ•ÍÍ…”ˆ¥ô(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡É•ÍÁ½¹Í”¤°½‘”((€€€…ÁÀ¹ÁÕĞ ˆ½…Á¤½½¹Ñ…ÑÌ¼ñ½¹Ñ…Ñ}¥øˆ¤(€€€‘•˜½¹Ñ…ÑÍ}ÕÁ‘…Ñ”¡½¹Ñ…Ñ}¥¤è(€€€€€€€€ˆˆ‹šnÓšZÃ–Z»’â–º#¢¶ß’êë¢¿Ö‡’êëˆˆˆ(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€‘…Ñ„°½‘”€ôÕÁ‘…Ñ•}Í¥¹±•}½¹Ñ…Ğ¡…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥°½¹Ñ…Ñ}¥°Á…å±½…¤(€€€€€€€¥˜½‘”€ôô€ÈÀÀè(€€€€€€€€€€€É•ÍÁ½¹Í”€ôì‰½¬ˆèQÉÕ”°€‰½¹Ñ…Ğˆè‘…Ñ…l‰½¹Ñ…Ğ‰t°€‰½¹Ñ…ÑÌˆè‘…Ñ…l‰½¹Ñ…ÑÌ‰uô(€€€€€€€•±Í”è(€€€€€€€€€€€É•ÍÁ½¹Í”€ôì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè‘…Ñ„¹•Ğ ‰•ÉÉ½Èˆ¤°€‰™¥•±‘Ìˆè‘…Ñ„¹•Ğ ‰™¥•±‘Ìˆ¥ô(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡É•ÍÁ½¹Í”¤°½‘”((€€€…ÁÀ¹‘•±•Ñ” ˆ½…Á¤½½¹Ñ…ÑÌ¼ñ½¹Ñ…Ñ}¥øˆ¤(€€€‘•˜½¹Ñ…ÑÍ}‘•±•Ñ”¡½¹Ñ…Ñ}¥¤è(€€€€€€€€ˆˆ‹–"«¦f“–Z»’â–º#¢¶ß’êë¢¿Ö‡’êëˆˆˆ(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡íô°ÕÍ•}…ÉÌõQÉÕ”¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€‘…Ñ„°½‘”€ô‘•±•Ñ•}Í¥¹±•}½¹Ñ…Ğ¡…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥°½¹Ñ…Ñ}¥¤(€€€€€€€¥˜½‘”€ôô€ÈÀÀè(€€€€€€€€€€€É•ÍÁ½¹Í”€ôì‰½¬ˆèQÉÕ”°€‰‘•±•Ñ•ˆèQÉÕ”°€‰½¹Ñ…Ñ}¥ˆè‘…Ñ…l‰½¹Ñ…Ñ}¥‰t°€‰½¹Ñ…ÑÌˆè‘…Ñ…l‰½¹Ñ…ÑÌ‰uô(€€€€€€€•±Í”è(€€€€€€€€€€€É•ÍÁ½¹Í”€ôì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè‘…Ñ„¹•Ğ ‰•ÉÉ½Èˆ¤°€‰½¹Ñ…Ñ}¥ˆè‘…Ñ„¹•Ğ ‰½¹Ñ…Ñ}¥ˆ¥ô(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡É•ÍÁ½¹Í”¤°½‘”((€€€…ÁÀ¹•Ğ ˆ½…Á¤½½¹‰½…É‘¥¹œˆ¤(€€€‘•˜½¹‰½…É‘¥¹}•Ğ ¤è(€€€€€€€€ˆˆ‹–n{–
Ï’öÿR£¢½¹‰½…É‘¥¹œƒ.š/ˆˆˆ(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡íô°ÕÍ•}…ÉÌõQÉÕ”¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€‘…Ñ„°½‘”€ô½¹‰½…É‘¥¹}ÍÑ…ÑÕÍ}Á…å±½… (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹•Ğ ˆ½…Á¤½¥¹Ñ•É…Ñ¥½¸µÍÑ…Ñ”ˆ¤(€€€‘•˜¥¹Ñ•É…Ñ¥½¹}ÍÑ…Ñ•}•Ğ ¤è(€€€€€€€€ˆˆ‹¢º–>[’öÿR£¢’êK–.W.š,£¦bËš¾?š^—¦7¢’nã–B3–Ÿ–ºçR §ˆˆˆ(€€€€€€€±¥¹•}ÕÍ•É}¥€ô€¡É•ÅÕ•ÍĞ¹…ÉÌ¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€¥˜¹½Ğ±¥¹•}ÕÍ•É}¥è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰µ¥ÍÍ¥¹œ±¥¹•}ÕÍ•É}¥‰ô¤°€ĞÀÀ(€€€€€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤(€€€€€€€ÁÉ½™¥±”€ôÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ°íô¤¹•Ğ¡±¥¹•}ÕÍ•É}¥¤(€€€€€€€¥˜¹½ĞÁÉ½™¥±”è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰ÕÍ•È¹½ĞÉ•¥ÍÑ•É•‰ô¤°€ĞÀĞ(€€€€€€€¥ÍÑ…Ñ”€ô•Ñ}½É}É•…Ñ•}¥¹Ñ•É…Ñ¥½¹}ÍÑ…Ñ”¡ÁÉ½™¥±”¤(€€€€€€€Í…Ù•}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t°ÍÑ…Ñ”¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¬ˆèQÉÕ”°€‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°€‰¥¹Ñ•É…Ñ¥½¹}ÍÑ…Ñ”ˆè¥ÍÑ…Ñ•ô¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½¥¹Ñ•É…Ñ¥½¸µÍÑ…Ñ”ˆ¤(€€€‘•˜¥¹Ñ•É…Ñ¥½¹}ÍÑ…Ñ•}Á½ÍĞ ¤è(€€€€€€€€ˆˆ‹šnÓšZÃ’öÿR£¢’êK–.W.š,¡½µÁ±•Ñ•‘}ÍÑ•ÁÌ€¼‘¥Íµ¥ÍÍ•‘}ÁÉ½µÁÑÌ€¼±…ÍÑ}±½Í¥¹}µ•ÍÍ…”ƒ¶$§ˆˆˆ(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥€ô€¡Á…å±½…¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€¥˜¹½Ğ±¥¹•}ÕÍ•É}¥è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰µ¥ÍÍ¥¹œ±¥¹•}ÕÍ•É}¥‰ô¤°€ĞÀÀ(€€€€€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤(€€€€€€€ÁÉ½™¥±”€ôÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ°íô¤¹•Ğ¡±¥¹•}ÕÍ•É}¥¤(€€€€€€€¥˜¹½ĞÁÉ½™¥±”è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰ÕÍ•È¹½ĞÉ•¥ÍÑ•É•‰ô¤°€ĞÀĞ(€€€€€€€¥ÍÑ…Ñ”€ô•Ñ}½É}É•…Ñ•}¥¹Ñ•É…Ñ¥½¹}ÍÑ…Ñ”¡ÁÉ½™¥±”¤(€€€€€€€€Œƒ–B#’ö×–¢¢ÇšnÓšZÃjš²’ö4(€€€€€€€™½È™¥•±¥¸€ ‰±…ÍÑ}¥¹Ñ•É…Ñ¥½¹}…Ğˆ°€‰±…ÍÑ}¥¹Ñ•É…Ñ¥½¹}ÍÕµµ…Éäˆ°(€€€€€€€€€€€€€€€€€€€€€€‰¹•áÑ}É•µ¥¹‘•É}…Ğˆ°€‰±…ÍÑ}±½Í¥¹}µ•ÍÍ…”ˆ°(€€€€€€€€€€€€€€€€€€€€€€‰½¹‰½…É‘¥¹}½µÁ±•Ñ•ˆ°€‰Õ…É‘¥…¹}ÁÉ½µÁÑ}ÍÑ…ÑÕÌˆ¤è(€€€€€€€€€€€¥˜™¥•±¥¸Á…å±½…è(€€€€€€€€€€€€€€€¥ÍÑ…Ñ•m™¥•±‘t€ôÁ…å±½…‘m™¥•±‘t(€€€€€€€¥˜€‰½µÁ±•Ñ•‘}ÍÑ•ÁÌˆ¥¸Á…å±½……¹¥Í¥¹ÍÑ…¹”¡Á…å±½…‘l‰½µÁ±•Ñ•‘}ÍÑ•ÁÌ‰t°±¥ÍĞ¤è(€€€€€€€€€€€¥ÍÑ…Ñ•l‰½µÁ±•Ñ•‘}ÍÑ•ÁÌ‰t€ô±¥ÍĞ¡Í•Ğ¡¥ÍÑ…Ñ”¹•Ğ ‰½µÁ±•Ñ•‘}ÍÑ•ÁÌˆ°mt¤€¬Á…å±½…‘l‰½µÁ±•Ñ•‘}ÍÑ•ÁÌ‰t¤¤(€€€€€€€¥˜€‰Á•¹‘¥¹}ÍÑ•ÁÌˆ¥¸Á…å±½……¹¥Í¥¹ÍÑ…¹”¡Á…å±½…‘l‰Á•¹‘¥¹}ÍÑ•ÁÌ‰t°±¥ÍĞ¤è(€€€€€€€€€€€¥ÍÑ…Ñ•l‰Á•¹‘¥¹}ÍÑ•ÁÌ‰t€ôÁ…å±½…‘l‰Á•¹‘¥¹}ÍÑ•ÁÌ‰t(€€€€€€€¥˜€‰‘¥Íµ¥ÍÍ•‘}ÁÉ½µÁÑÌˆ¥¸Á…å±½……¹¥Í¥¹ÍÑ…¹”¡Á…å±½…‘l‰‘¥Íµ¥ÍÍ•‘}ÁÉ½µÁÑÌ‰t°‘¥Ğ¤è(€€€€€€€€€€€µ•É•€ô¥ÍÑ…Ñ”¹•Ğ ‰‘¥Íµ¥ÍÍ•‘}ÁÉ½µÁÑÌˆ°íô¤(€€€€€€€€€€€µ•É•¹ÕÁ‘…Ñ”¡Á…å±½…‘l‰‘¥Íµ¥ÍÍ•‘}ÁÉ½µÁÑÌ‰t¤(€€€€€€€€€€€¥ÍÑ…Ñ•l‰‘¥Íµ¥ÍÍ•‘}ÁÉ½µÁÑÌ‰t€ôµ•É•(€€€€€€€¥ÍÑ…Ñ•l‰±…ÍÑ}¥¹Ñ•É…Ñ¥½¹}…Ğ‰t€ô‘…Ñ•Ñ¥µ”¹¹½Ü ¤¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤(€€€€€€€Í…Ù•}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t°ÍÑ…Ñ”¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¬ˆèQÉÕ”°€‰¥¹Ñ•É…Ñ¥½¹}ÍÑ…Ñ”ˆè¥ÍÑ…Ñ•ô¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½Õ…É‘¥…¸µÉ•µ¥¹‘•È½‘¥Íµ¥ÍÌˆ¤(€€€‘•˜Õ…É‘¥…¹}É•µ¥¹‘•É}‘¥Íµ¥ÍÌ ¤è(€€€€€€€€ˆˆ‹’öÿR£¢–Â7–º#¢¶ß’êë–º3š"C–ê›š>C’ëj–n{š'((€€€€€€€‰½‘ä¹ÁÉ•™•É•¹”è€¹½Üœğ€Ñ½µ½ÉÉ½Üœğ€‘¥Íµ¥ÍÍ|İœğ€‘¥Íµ¥ÍÍ•œ(€€€€€€€€ˆˆˆ(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥€ô€¡Á…å±½…¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€ÁÉ•˜€ô€¡Á…å±½…¹•Ğ ‰ÁÉ•™•É•¹”ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€¥˜¹½Ğ±¥¹•}ÕÍ•É}¥è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰µ¥ÍÍ¥¹œ±¥¹•}ÕÍ•É}¥‰ô¤°€ĞÀÀ(€€€€€€€¥˜ÁÉ•˜¹½Ğ¥¸€ ‰¹½Üˆ°€‰Ñ½µ½ÉÉ½Üˆ°€‰‘¥Íµ¥ÍÍ|İˆ°€‰‘¥Íµ¥ÍÍ•ˆ¤è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰¥¹Ù…±¥ÁÉ•™•É•¹”‰ô¤°€ĞÀÀ(€€€€€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤(€€€€€€€ÁÉ½™¥±”€ôÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ°íô¤¹•Ğ¡±¥¹•}ÕÍ•É}¥¤(€€€€€€€¥˜¹½ĞÁÉ½™¥±”è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰ÕÍ•È¹½ĞÉ•¥ÍÑ•É•‰ô¤°€ĞÀĞ(€€€€€€€¥ÍÑ…Ñ”€ô•Ñ}½É}É•…Ñ•}¥¹Ñ•É…Ñ¥½¹}ÍÑ…Ñ”¡ÁÉ½™¥±”¤(€€€€€€€¥ÍÑ…Ñ•l‰Õ…É‘¥…¹}É•µ¥¹‘•É}ÁÉ•™•É•¹”‰t€ôÁÉ•˜(€€€€€€€¥ÍÑ…Ñ•l‰Õ…É‘¥…¹}±…ÍÑ}ÁÉ½µÁÑ•‘}…Ğ‰t€ô‘…Ñ•Ñ¥µ”¹¹½Ü ¤¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤(€€€€€€€¹½Ü€ô‘…Ñ•Ñ¥µ”¹¹½Ü ¤(€€€€€€€¥˜ÁÉ•˜€ôô€‰Ñ½µ½ÉÉ½Üˆè(€€€€€€€€€€€¥ÍÑ…Ñ•l‰Õ…É‘¥…¹}É•µ¥¹‘•É}Í¹½½é•‘}Õ¹Ñ¥°‰t€ô€¡¹½Ü€¬Ñ¥µ•‘•±Ñ„¡‘…åÌôÄ¤¤¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤(€€€€€€€•±¥˜ÁÉ•˜€ôô€‰‘¥Íµ¥ÍÍ|İˆè(€€€€€€€€€€€¥ÍÑ…Ñ•l‰Õ…É‘¥…¹}É•µ¥¹‘•É}Í¹½½é•‘}Õ¹Ñ¥°‰t€ô€¡¹½Ü€¬Ñ¥µ•‘•±Ñ„¡‘…åÌôÜ¤¤¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤(€€€€€€€•±Í”è(€€€€€€€€€€€¥ÍÑ…Ñ•l‰Õ…É‘¥…¹}É•µ¥¹‘•É}Í¹½½é•‘}Õ¹Ñ¥°‰t€ô€ˆˆ(€€€€€€€Í…Ù•}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t°ÍÑ…Ñ”¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¬ˆèQÉÕ”°€‰¥¹Ñ•É…Ñ¥½¹}ÍÑ…Ñ”ˆè¥ÍÑ…Ñ•ô¤((((€€€€ŒAÉ½‘ÕÑ¥½¸ƒ–º3–£’â7¢¢ï–(‘•Ø•¹‘Á½¥¹Ğ¡Õ¹¥½É¸ƒ’â7¢ŞD…ÁÀ¹ÉÕ¸ ¤±‘•‰Õœƒšb¼…±Í”¤(€€€}¥Í}‘•Ø€ô€ (€€€€€€€½Ì¹•¹Ù¥É½¸¹•Ğ ‰Y}5=ˆ°€ˆˆ¤¹±½İ•È ¤¥¸€ ˆÄˆ°€‰ÑÉÕ”ˆ°€‰å•Ìˆ¤(€€€€€€€½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰1M-}9Xˆ°€ˆˆ¤¹±½İ•È ¤¥¸€ ‰‘•Ù•±½Áµ•¹Ğˆ°€‰‘•Øˆ¤(€€€€€€€½È…ÁÀ¹‘•‰Õœ(€€€€¤((€€€¥˜}¥Í}‘•Øè(€€€€€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½‘•Ø½ÕÁÉ…‘”µÁ±…¸ˆ¤(€€€€€€€‘•˜‘•Ù}ÕÁÉ…‘•}Á±…¸ ¤è(€€€€€€€€€€€€ˆˆ‰X=91dèƒ–6ÒhÁ±…¸€£šâ³¢¦›R §((€€€€€€€AÉ½‘ÕÑ¥½¸ƒ’â–ú/–nx€ĞÀÓ–>«šr'’î—’â/ššÎš&7–¢¢Ç–Fó–>¬è(€€€€€€€€Ä¸É•ÅÕ•ÍĞ¹É•µ½Ñ•}…‘‘Èƒšb¼€ÄÈÜ¸À¸À¸Ä€¼€èèÄ€£šr³š¦|¤(€€€€€€€€È¸ƒš"X•¹ØY}5=õÑÉÕ”ƒšb;Šë–VR (€€€€€€€€Ì¸ƒš"X¡½ÍĞ¡•…‘•Èƒšb¼±½…±¡½ÍĞ€¼€ÄÈÜ¸À¸À¸Ä(€€€€€€€€ˆˆˆ(€€€€€€€€Œ€Ä¸ƒšr³š¦|%@ƒ–¢¢Ä(€€€€€€€É•µ½Ñ”€ô€¡É•ÅÕ•ÍĞ¹É•µ½Ñ•}…‘‘È½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€¡½ÍĞ€ô€¡É•ÅÕ•ÍĞ¹¡½ÍĞ½È€ˆˆ¤¹±½İ•È ¤(€€€€€€€¥Í}±½…°€ôÉ•µ½Ñ”¥¸€ ˆÄÈÜ¸À¸À¸Äˆ°€ˆèèÄˆ°€‰±½…±¡½ÍĞˆ¤½È¡½ÍĞ¹ÍÑ…ÉÑÍİ¥Ñ  ‰±½…±¡½ÍĞˆ¤½È¡½ÍĞ¹ÍÑ…ÉÑÍİ¥Ñ  ˆÄÈÜ¸ˆ¤(€€€€€€€€Œ€È¸•¹Øƒšb;Šë–VR (€€€€€€€‘•Ù}µ½‘•}•¹…‰±•€ô½Ì¹•¹Ù¥É½¸¹•Ğ ‰Y}5=ˆ°€ˆˆ¤¹±½İ•È ¤¥¸€ ˆÄˆ°€‰ÑÉÕ”ˆ°€‰å•Ìˆ¤(€€€€€€€¥˜¹½Ğ€¡¥Í}±½…°½È‘•Ù}µ½‘•}•¹…‰±•¤è(€€€€€€€€€€€€ŒAÉ½‘ÕÑ¥½¸ƒJÃ–Š³š.KÖW–¶c–>X£’â7¦?¦rÈ•¹‘Á½¥¹Ğƒ–¶c–r ¤(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰¹½Ñ}™½Õ¹‰ô¤°€ĞÀĞ(€€€€€€€€Œƒ¦k¦;šª‹š~”³–~ß¢†0‘•Øƒ¦
?¢ò¼(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥€ô€¡Á…å±½…¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€Á±…¸€ô€¡Á…å±½…¹•Ğ ‰Á±…¸ˆ¤½È€‰Á…¥‘|Üäå}å•…Èˆ¤¹ÍÑÉ¥À ¤(€€€€€€€¥˜¹½Ğ±¥¹•}ÕÍ•É}¥è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰µ¥ÍÍ¥¹œ±¥¹•}ÕÍ•É}¥‰ô¤°€ĞÀÀ(€€€€€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤(€€€€€€€ÁÉ½™¥±”€ôÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ°íô¤¹•Ğ¡±¥¹•}ÕÍ•É}¥¤(€€€€€€€¥˜¹½ĞÁÉ½™¥±”è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰ÕÍ•È¹½ĞÉ•¥ÍÑ•É•‰ô¤°€ĞÀĞ(€€€€€€€ÁÉ½™¥±•l‰Á±…¸‰t€ôÁ±…¸(€€€€€€€Í…Ù•}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t°ÍÑ…Ñ”¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¬ˆèQÉÕ”°€‰Á±…¸ˆèÁ±…¹ô¤°€ÈÀÀ((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½½¹‰½…É‘¥¹œ½½µÁ±•Ñ”ˆ¤(€€€‘•˜½¹‰½…É‘¥¹}½µÁ±•Ñ” ¤è(€€€€€€€€ˆˆ‹š¢g¢¢`½¹‰½…É‘¥¹œƒ–º3š"@£–ş¦‚#¢Ï–ÂGšr$€Äƒ’ö7–º#¢¶ß’êè§ˆˆˆ(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€É•ÍÕ±Ğ°½‘”€ô½µÁ±•Ñ•}½¹‰½…É‘¥¹}™½É}ÕÍ•È (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥°Á…å±½…(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡É•ÍÕ±Ğ¤°½‘”((€€€…ÁÀ¹•Ğ ˆ½…Á¤½•µ•É•¹äµ½¹Ñ…Ğ½¥¹Ù¥Ñ”µÁÉ•Ù¥•Üˆ¤(€€€‘•˜•µ•É•¹å}½¹Ñ…Ñ}¥¹Ù¥Ñ•}ÁÉ•Ù¥•İ}…Á¤ ¤è(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡íô°ÕÍ•}…ÉÌõQÉÕ”¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€Á…å±½…€ôì(€€€€€€€€€€€€‰¥¹Ù¥Ñ•}™É½´ˆèÉ•ÅÕ•ÍĞ¹…ÉÌ¹•Ğ ‰¥¹Ù¥Ñ•}™É½´ˆ¤½ÈÉ•ÅÕ•ÍĞ¹…ÉÌ¹•Ğ ‰™É½´ˆ¤½È€ˆˆ°(€€€€€€€€€€€€‰¥¹Ù¥Ñ•}Ñ½­•¸ˆèÉ•ÅÕ•ÍĞ¹…ÉÌ¹•Ğ ‰¥¹Ù¥Ñ•}Ñ½­•¸ˆ¤½È€ˆˆ°(€€€€€€€€€€€€‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°(€€€€€€€ô(€€€€€€€‘…Ñ„°½‘”€ô¥¹Ù¥Ñ•}‰¥¹‘}ÁÉ•Ù¥•Ü¡…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½•µ•É•¹äµ½¹Ñ…Ğ½¥¹Ù¥Ñ”ˆ¤(€€€‘•˜•µ•É•¹å}½¹Ñ…Ñ}¥¹Ù¥Ñ•}É•…Ñ•}…Á¤ ¤è(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€‘…Ñ„°½‘”€ôÉ•…Ñ•}Õ…É‘¥…¹}¥¹Ù¥Ñ” (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥°Á…å±½…(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½•µ•É•¹äµ½¹Ñ…Ğ½‰¥¹ˆ¤(€€€‘•˜•µ•É•¹å}½¹Ñ…Ñ}‰¥¹‘}…Á¤ ¤è(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€Á…å±½…‘l‰½¹Ñ…Ñ}±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€‘…Ñ„°½‘”€ô‰¥¹‘}•µ•É•¹å}½¹Ñ…Ğ¡…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…°…ÁÀ¹½¹™¥œ¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½Õ…É‘¥…¸µÉ½ÕÁÌ½‰¥¹ˆ¤(€€€‘•˜Õ…É‘¥…¹}É½ÕÁÍ}‰¥¹‘}…Á¤ ¤è(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€‘…Ñ„°½‘”€ô‰¥¹‘}Õ…É‘¥…¹}É½ÕÀ¡…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤(€€€€€€€¥˜½‘”€ôô€ÈÀÀ…¹‘…Ñ„¹•Ğ ‰ÑÉ¥…±}Ñ•ÍÑ}µ•ÍÍ…”ˆ¤è(€€€€€€€€€€€Ñ½­•¸€ô…ÁÀ¹½¹™¥œ¹•Ğ ‰1%9}!991}MM}Q=-8ˆ¤½È½Ì¹•¹Ù¥É½¸¹•Ğ (€€€€€€€€€€€€€€€€‰1%9}!991}MM}Q=-8ˆ°€ˆˆ(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜¹½ĞÑ½­•¸è(€€€€€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì(€€€€€€€€€€€€€€€€€€€€¨©‘…Ñ„°(€€€€€€€€€€€€€€€€€€€€‰ÑÉ¥…±}Ñ•ÍÑ}‘•±¥Ù•Éäˆè€‰™…¥±•ˆ°(€€€€€€€€€€€€€€€€€€€€‰•ÉÉ½Èˆè€‰1%9}!991}MM}Q=-8¥Ì¹½ĞÍ•Ğˆ°(€€€€€€€€€€€€€€€ô¤°€ÔÀÌ(€€€€€€€€€€€Í•¹‘•È€ô…ÁÀ¹½¹™¥œ¹•Ğ ‰1%9}AUM!}M9Hˆ¤½È±¥¹•}ÁÕÍ¡}µ•ÍÍ…”(€€€€€€€€€€€É•ÑÉå}­•ä€ô‘…Ñ„¹•Ğ ‰ÑÉ¥…±}Ñ•ÍÑ}É•ÑÉå}­•äˆ¤½È}±¥¹•}É•ÑÉå}­•ä (€€€€€€€€€€€€€€€˜‰ÑÉ¥…°µÉ½ÕÀµÑ•ÍĞéí±¥¹•}ÕÍ•É}¥‘ôéíÁ…å±½…¹•Ğ É½ÕÁ}¥œ¥ôˆ(€€€€€€€€€€€€¤(€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€}Í•¹‘}±¥¹•}İ¥Ñ¡}É•ÑÉå}­•ä (€€€€€€€€€€€€€€€€€€€Í•¹‘•È°(€€€€€€€€€€€€€€€€€€€Ñ½­•¸°(€€€€€€€€€€€€€€€€€€€Á…å±½…¹•Ğ ‰É½ÕÁ}¥ˆ¤°(€€€€€€€€€€€€€€€€€€€‘…Ñ…l‰ÑÉ¥…±}Ñ•ÍÑ}µ•ÍÍ…”‰t°(€€€€€€€€€€€€€€€€€€€É•ÑÉå}­•ä°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€‘…Ñ…l‰ÑÉ¥…±}Ñ•ÍÑ}‘•±¥Ù•Éä‰t€ô€‰Í•¹Ğˆ(€€€€€€€€€€€€€€€µÕÑ…Ñ•}ÍÑ…Ñ•}…Ñ½µ¥…±±ä (€€€€€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€€€€€±…µ‰‘„ÍÑ…Ñ”è€ (€€€€€€€€€€€€€€€€€€€€€€€€¡ÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ¤½Èíô¤¹•Ğ¡±¥¹•}ÕÍ•É}¥°íô¤¹Í•Ñ‘•™…Õ±Ğ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰ÑÉ¥…±}É½ÕÁ}Ñ•ÍÑ}‘•±¥Ù•Éäˆ°íô(€€€€€€€€€€€€€€€€€€€€€€€€¤¹ÕÁ‘…Ñ”¡ì(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰ÍÑ…ÑÕÌˆè€‰Í•¹Ğˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰Í•¹Ñ}…ĞˆèÕÉÉ•¹Ñ}…ÁÁ}Ñ¥µ”¡…ÁÀ¹½¹™¥œ¤¹¥Í½™½Éµ…Ğ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€€€€€€€€ô¤°(€€€€€€€€€€€€€€€€€€€€€€€É•½É‘}±¥¹•}µ•ÍÍ…•}ÕÍ…” (€€€€€€€€€€€€€€€€€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€€€€€€€€€€€€€€€€€…Ñ•½Éäô‰ÑÉ¥…±}É½ÕÁ}Ñ•ÍĞˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€½İ¹•É}±¥¹•}ÕÍ•É}¥õ±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€€€€€€€€€€€€€É•¥Á¥•¹Ñ}½Õ¹ĞôÄ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€•Ù•¹Ñ}¥õÉ•ÑÉå}­•ä°(€€€€€€€€€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€€€€€¥l´Åt°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€€€€€‘…Ñ…l‰ÑÉ¥…±}Ñ•ÍÑ}‘•±¥Ù•Éä‰t€ô€‰™…¥±•ˆ(€€€€€€€€€€€€€€€‘…Ñ…l‰•ÉÉ½È‰t€ô€‹šâ³¢¦›¦k~—šj¯šf‡šÎW¦–ë¾ò3¢®/¢7–ú3–7¢¦›ˆ(€€€€€€€€€€€€€€€µÕÑ…Ñ•}ÍÑ…Ñ•}…Ñ½µ¥…±±ä (€€€€€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€€€€€±…µ‰‘„ÍÑ…Ñ”è€¡ÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ¤½Èíô¤¹•Ğ (€€€€€€€€€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°íô(€€€€€€€€€€€€€€€€€€€€¤¹Í•Ñ‘•™…Õ±Ğ ‰ÑÉ¥…±}É½ÕÁ}Ñ•ÍÑ}‘•±¥Ù•Éäˆ°íô¤¹ÕÁ‘…Ñ”¡ì(€€€€€€€€€€€€€€€€€€€€€€€€‰ÍÑ…ÑÕÌˆè€‰™…¥±•ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€‰±…ÍÑ}•ÉÉ½ÈˆèÍÑÈ¡•áŒ¥lèÈÀÁt°(€€€€€€€€€€€€€€€€€€€ô¤°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹İ…É¹¥¹œ ‰ÑÉ¥…°É½ÕÀÑ•ÍĞ‘•±¥Ù•Éä™…¥±•è€•Ìˆ°•áŒ¤(€€€€€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°€ÔÀÈ(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½Õ…É‘¥…¸µÉ½ÕÁÌ½Õ¹‰¥¹ˆ¤(€€€‘•˜Õ…É‘¥…¹}É½ÕÁÍ}Õ¹‰¥¹‘}…Á¤ ¤è(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€‘…Ñ„°½‘”€ôÕ¹‰¥¹‘}Õ…É‘¥…¹}É½ÕÀ¡…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½Õ…É‘¥…¸µÉ½ÕÁÌ½ÁÉ•™•É•¹•Ìˆ¤(€€€‘•˜Õ…É‘¥…¹}É½ÕÁÍ}ÁÉ•™•É•¹•Í}…Á¤ ¤è(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€‘…Ñ„°½‘”€ôÕÁ‘…Ñ•}Õ…É‘¥…¹}É½ÕÁ}ÁÉ•™•É•¹•Ì (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹•Ğ ˆ½…Á¤½Õ…É‘¥…¸µÉ½ÕÁÌ½Í•ÑÑ¥¹Ìˆ¤(€€€‘•˜Õ…É‘¥…¹}É½ÕÁÍ}Í•ÑÑ¥¹Í}…Á¤ ¤è(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡íô°ÕÍ•}…ÉÌõQÉÕ”¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€‘…Ñ„°½‘”€ôÕ…É‘¥…¹}É½ÕÁ}Í•ÑÑ¥¹Í}™½É}ÕÍ•È (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€€Œ€ôôôôô€ÈÀÈØ´ÀÜ´ÈÀƒ¢v›¢FŒ…‘‘•èƒšâ³¢¦›¦‚•¹‘Á½¥¹ÑÌ€ôôôôô(€€€QMQ}UMI}AI%`€ô€‰U}QMQ|ˆ((€€€…ÁÀ¹•Ğ ˆ½…Á¤½Õ…É‘¥…¸µÉ½ÕÁÌ½Ñ•ÍĞµÕÍ•ÉÌˆ¤(€€€‘•˜Õ…É‘¥…¹}É½ÕÁÍ}Ñ•ÍÑ}ÕÍ•ÉÍ}…Á¤ ¤è(€€€€€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤(€€€€€€€ÕÍ•ÉÌ€ômt(€€€€€€€™½ÈÕ¥°ÁÉ½™¥±”¥¸€¡ÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ¤½Èíô¤¹¥Ñ•µÌ ¤è(€€€€€€€€€€€¥˜¹½ĞÕ¥¹ÍÑ…ÉÑÍİ¥Ñ ¡QMQ}UMI}AI%`¤è(€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€Á±…¸€ôÁÉ½™¥±”¹•Ğ ‰Á±…¸ˆ¤½È€‰ÑÉ¥…°ˆ(€€€€€€€€€€€¥Í}å•…È€ôÁ±…¸€ôô€‰Á…¥‘|Üäå}å•…Èˆ(€€€€€€€€€€€¥Í}µ½¹Ñ €ôÁ±…¸€ôô€‰Á…¥‘|Üääˆ(€€€€€€€€€€€•±¥¥‰±”€ô€¡¥Í}å•…È½È¥Í}µ½¹Ñ ¤…¹Á…¥‘}µ•µ‰•ÉÍ¡¥Á}¥Í}…Ñ¥Ù”¡ÁÉ½™¥±”¤(€€€€€€€€€€€ÕÍ•ÉÌ¹…ÁÁ•¹¡ì(€€€€€€€€€€€€€€€€‰±¥¹•}ÕÍ•É}¥ˆèÕ¥°(€€€€€€€€€€€€€€€€‰‘¥ÍÁ±…å}¹…µ”ˆèÁÉ½™¥±”¹•Ğ ‰‘¥ÍÁ±…å}¹…µ”ˆ°€ˆˆ¤°(€€€€€€€€€€€€€€€€‰Á±…¸ˆèÁ±…¸°(€€€€€€€€€€€€€€€€‰Á…¥‘}Õ¹Ñ¥°ˆèÁÉ½™¥±”¹•Ğ ‰Á…¥‘}Õ¹Ñ¥°ˆ°€ˆˆ¤°(€€€€€€€€€€€€€€€€‰Á…åµ•¹Ñ}ÍÑ…ÑÕÌˆèÁÉ½™¥±”¹•Ğ ‰Á…åµ•¹Ñ}ÍÑ…ÑÕÌˆ°€ˆˆ¤°(€€€€€€€€€€€€€€€€‰‰¥¹‘}½Õ¹Ğˆè±•¸¡ÁÉ½™¥±”¹•Ğ ‰Õ…É‘¥…¹}É½ÕÁ}¥‘Ìˆ¤½Èmt¤°(€€€€€€€€€€€€€€€€‰µ…á}É½ÕÁÌˆè€ Ì¥˜¥Í}å•…È•±Í”€Ä¤¥˜•±¥¥‰±”•±Í”€À°(€€€€€€€€€€€€€€€€‰•±¥¥‰±”ˆè•±¥¥‰±”°(€€€€€€€€€€€€€€€€‰ÍÑ…ÑÕÌˆè€‰•±¥¥‰±”ˆ¥˜•±¥¥‰±”•±Í”€‰¥¹•±¥¥‰±”ˆ°(€€€€€€€€€€€€€€€€‰Õ…É‘¥…¹}É½ÕÁ}¥‘ÌˆèÁÉ½™¥±”¹•Ğ ‰Õ…É‘¥…¹}É½ÕÁ}¥‘Ìˆ°mt¤°(€€€€€€€€€€€ô¤(€€€€€€€É½ÕÁÌ€ôl(€€€€€€€€€€€ì‰É½ÕÁ}¥ˆè¥°€¨©¥¹™½ô(€€€€€€€€€€€™½È¥°¥¹™¼¥¸€¡ÍÑ…Ñ”¹•Ğ ‰Õ…É‘¥…¹}É½ÕÁÌˆ¤½Èíô¤¹¥Ñ•µÌ ¤(€€€€€€€t(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰ÕÍ•ÉÌˆèÕÍ•ÉÌ°€‰É½ÕÁÌˆèÉ½ÕÁÌ°€‰ÁÉ•™¥àˆèQMQ}UMI}AI%aô¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½Õ…É‘¥…¸µÉ½ÕÁÌ½Ñ•ÍĞµÉ•Í•Ğˆ¤(€€€‘•˜Õ…É‘¥…¹}É½ÕÁÍ}Ñ•ÍÑ}É•Í•Ñ}…Á¤ ¤è(€€€€€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤(€€€€€€€Õ¥‘Ì€ômÕ¥™½ÈÕ¥¥¸ÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ°íô¤¹­•åÌ ¤¥˜Õ¥¹ÍÑ…ÉÑÍİ¥Ñ ¡QMQ}UMI}AI%`¥t(€€€€€€€™½ÈÕ¥¥¸Õ¥‘Ìè(€€€€€€€€€€€ÍÑ…Ñ•l‰ÕÍ•ÉÌ‰t¹Á½À¡Õ¥°9½¹”¤(€€€€€€€™½ÈÁÉ½™¥±”¥¸ÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ°íô¤¹Ù…±Õ•Ì ¤è(€€€€€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡ÁÉ½™¥±”¹•Ğ ‰½¹Ñ…ÑÌˆ¤°±¥ÍĞ¤è(€€€€€€€€€€€€€€€ÁÉ½™¥±•l‰½¹Ñ…ÑÌ‰t€ômŒ™½ÈŒ¥¸ÁÉ½™¥±•l‰½¹Ñ…ÑÌ‰t¥˜Œ¹•Ğ ‰±¥¹•}¥ˆ¤¹½Ğ¥¸Õ¥‘Ít(€€€€€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡ÁÉ½™¥±”¹•Ğ ‰™É¥•¹‘Ìˆ¤°±¥ÍĞ¤è(€€€€€€€€€€€€€€€ÁÉ½™¥±•l‰™É¥•¹‘Ì‰t€ôm˜™½È˜¥¸ÁÉ½™¥±•l‰™É¥•¹‘Ì‰t¥˜˜¹½Ğ¥¸Õ¥‘Ít(€€€€€€€™½È¥¥¸±¥ÍĞ¡ÍÑ…Ñ”¹•Ğ ‰Õ…É‘¥…¹}É½ÕÁÌˆ°íô¤¹­•åÌ ¤¤è(€€€€€€€€€€€½İ¹•È€ôÍÑ…Ñ•l‰Õ…É‘¥…¹}É½ÕÁÌ‰um¥‘t¹•Ğ ‰½İ¹•É}±¥¹•}ÕÍ•É}¥ˆ°€ˆˆ¤(€€€€€€€€€€€¥˜½İ¹•È¹ÍÑ…ÉÑÍİ¥Ñ ¡QMQ}UMI}AI%`¤è(€€€€€€€€€€€€€€€ÍÑ…Ñ•l‰Õ…É‘¥…¹}É½ÕÁÌ‰t¹Á½À¡¥°9½¹”¤(€€€€€€€™½ÈÁÉ½™¥±”¥¸ÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ°íô¤¹Ù…±Õ•Ì ¤è(€€€€€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡ÁÉ½™¥±”¹•Ğ ‰Õ…É‘¥…¹}É½ÕÁ}¥‘Ìˆ¤°±¥ÍĞ¤è(€€€€€€€€€€€€€€€ÁÉ½™¥±•l‰Õ…É‘¥…¹}É½ÕÁ}¥‘Ì‰t€ômt(€€€€€€€Í…Ù•}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t°ÍÑ…Ñ”¤(€€€€€€€‘•™…Õ±ÑÌ€ôl(€€€€€€€€€€€€ ‰U}QMQ}å•…É±å|ÀÀÄˆ°€‰Á…¥‘|Üäå}å•…Èˆ°€‹šâ³¢¦˜·–æÓ¢Êìäääˆ°€ˆÈÀää´ÄÈ´ÌÅPÀÀèÀÀèÀÀˆ°€‰…Ñ¥Ù”ˆ¤°(€€€€€€€€€€€€ ‰U}QMQ}µ½¹Ñ¡±å|ÀÀÄˆ°€‰Á…¥‘|Üääˆ°€‹šâ³¢¦˜·šr#¢Êìˆ°€ˆÈÀää´ÄÈ´ÌÅPÀÀèÀÀèÀÀˆ°€‰…Ñ¥Ù”ˆ¤°(€€€€€€€€€€€€ ‰U}QMQ|Ìäå|ÀÀÄˆ°€‰Á…¥‘|Ìääˆ°€‹šâ³¢¦˜´Ìääƒ’â7²›¢Îš‚ğˆ°€ˆÈÀää´ÄÈ´ÌÅPÀÀèÀÀèÀÀˆ°€‰…Ñ¥Ù”ˆ¤°(€€€€€€€€€€€€ ‰U}QMQ}ÑÉ¥…±|ÀÀÄˆ°€‰ÑÉ¥…°ˆ°€‹šâ³¢¦˜µÑÉ¥…°ˆ°€ˆˆ°€‰ÑÉ¥…°ˆ¤°(€€€€€€€t(€€€€€€€É•…Ñ•€ômt(€€€€€€€™½ÈÕ¥°Á±…¸°¹…µ”°Á…¥‘}Õ¹Ñ¥°°Á…åµ•¹Ñ}ÍÑ…ÑÕÌ¥¸‘•™…Õ±ÑÌè(€€€€€€€€€€€¥˜Õ¥¥¸ÍÑ…Ñ•l‰ÕÍ•ÉÌ‰tè(€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€ÍÑ…Ñ•l‰ÕÍ•ÉÌ‰umÕ¥‘t€ôì(€€€€€€€€€€€€€€€€‰±¥¹•}ÕÍ•É}¥ˆèÕ¥°€‰‘¥ÍÁ±…å}¹…µ”ˆè¹…µ”°€‰Á±…¸ˆèÁ±…¸°(€€€€€€€€€€€€€€€€‰Á…¥‘}Õ¹Ñ¥°ˆèÁ…¥‘}Õ¹Ñ¥°°€‰Á…åµ•¹Ñ}ÍÑ…ÑÕÌˆèÁ…åµ•¹Ñ}ÍÑ…ÑÕÌ°(€€€€€€€€€€€€€€€€‰Õ…É‘¥…¹}É½ÕÁ}¥‘Ìˆèmt°€‰½¹Ñ…ÑÌˆèmt°€‰™É¥•¹‘Ìˆèmt°(€€€€€€€€€€€ô(€€€€€€€€€€€É•…Ñ•¹…ÁÁ•¹¡Õ¥¤(€€€€€€€Í…Ù•}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t°ÍÑ…Ñ”¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰É•Í•ĞˆèQÉÕ”°€‰‘•±•Ñ•‘}ÕÍ•ÉÌˆè±•¸¡Õ¥‘Ì¤°€‰É•…Ñ•ˆèÉ•…Ñ•‘ô¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½Õ…É‘¥…¸µÉ½ÕÁÌ½Ñ•ÍĞµ•¹™½É”ˆ¤(€€€‘•˜Õ…É‘¥…¹}É½ÕÁÍ}Ñ•ÍÑ}•¹™½É•}…Á¤ ¤è(€€€€€€€‰½‘ä€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€É½ÕÁ}¥€ôÍÑÈ¡‰½‘ä¹•Ğ ‰É½ÕÁ}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€Í¥µÕ±…Ñ•‘}½Õ¹Ğ€ô‰½‘ä¹•Ğ ‰Í¥µÕ±…Ñ•‘}½Õ¹Ğˆ¤(€€€€€€€Í¥µÕ±…Ñ•‘}¹•İ}¥‘Ì€ô‰½‘ä¹•Ğ ‰Í¥µÕ±…Ñ•‘}¹•İ}¥‘Ìˆ¤½Èmt(€€€€€€€¥˜¹½ĞÉ½ÕÁ}¥è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰µ¥ÍÍ¥¹œÉ½ÕÁ}¥‰ô¤°€ĞÀÀ(€€€€€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤(€€€€€€€É½ÕÁ}¥¹™¼€ôÍÑ…Ñ”¹•Ğ ‰Õ…É‘¥…¹}É½ÕÁÌˆ°íô¤¹•Ğ¡É½ÕÁ}¥¤(€€€€€€€¥˜¹½ĞÉ½ÕÁ}¥¹™¼è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰É½ÕÀ¹½Ğ‰½Õ¹‰ô¤°€ĞÀĞ(€€€€€€€¥˜É½ÕÁ}¥¹™¼¹•Ğ ‰ÍÑ…ÑÕÌˆ¤€„ô€‰…Ñ¥Ù”ˆè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰É½ÕÀ¥¹…Ñ¥Ù”‰ô¤°€ĞÀä(€€€€€€€¥˜Í¥µÕ±…Ñ•‘}½Õ¹Ğ¥Ì9½¹”è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰Í¥µÕ±…Ñ•‘}½Õ¹ĞÉ•ÅÕ¥É•‰ô¤°€ĞÀÀ(€€€€€€€ÕÉÉ•¹Ñ}½Õ¹Ğ€ô¥¹Ğ¡Í¥µÕ±…Ñ•‘}½Õ¹Ğ¤(€€€€€€€¥˜ÕÉÉ•¹Ñ}½Õ¹Ğ€ğôI=UA}55	I}1%5%Pè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì(€€€€€€€€€€€€€€€€‰½¬ˆèQÉÕ”°€‰•¹™½É•ˆè…±Í”°(€€€€€€€€€€€€€€€€‰ÕÉÉ•¹Ñ}½Õ¹ĞˆèÕÉÉ•¹Ñ}½Õ¹Ğ°€‰±¥µ¥ĞˆèI=UA}55	I}1%5%P°(€€€€€€€€€€€€€€€€‰­¥­•ˆèmt°€‰™…¥±•ˆèmt°(€€€€€€€€€€€€€€€€‰É½ÕÁ}¥ˆèÉ½ÕÁ}¥°(€€€€€€€€€€€€€€€€‰¹½Ñ”ˆè€‹šr«¢Ú¦;’â+¦f@³’â7¦r •Ù¥Ğˆ°(€€€€€€€€€€€ô¤°€ÈÀÀ(€€€€€€€‰¥¹‘}¥‘Ì€ôÍ•Ğ¡É½ÕÁ}¥¹™¼¹•Ğ ‰µ•µ‰•É}¥‘Í}…Ñ}‰¥¹ˆ¤½Èmt¤(€€€€€€€…¹‘¥‘…Ñ•}¥‘Ì€ô±¥ÍĞ¡Í¥µÕ±…Ñ•‘}¹•İ}¥‘Ì¤(€€€€€€€½Ù•É™±½Ü€ôÕÉÉ•¹Ñ}½Õ¹Ğ€´I=UA}55	I}1%5%P(€€€€€€€Ñ½}­¥¬€ô…¹‘¥‘…Ñ•}¥‘Ílé½Ù•É™±½İt¥˜½Ù•É™±½Ü€ø€À•±Í”€¡…¹‘¥‘…Ñ•}¥‘ÍlèÅt¥˜…¹‘¥‘…Ñ•}¥‘Ì•±Í”mt¤(€€€€€€€­¥­•€ô±¥ÍĞ¡Ñ½}­¥¬¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì(€€€€€€€€€€€€‰½¬ˆèQÉÕ”°€‰•¹™½É•ˆèQÉÕ”°(€€€€€€€€€€€€‰ÕÉÉ•¹Ñ}½Õ¹ĞˆèÕÉÉ•¹Ñ}½Õ¹Ğ°€‰±¥µ¥ĞˆèI=UA}55	I}1%5%P°(€€€€€€€€€€€€‰½Ù•É™±½Üˆè½Ù•É™±½Ü°(€€€€€€€€€€€€‰…¹‘¥‘…Ñ•}½Õ¹Ğˆè±•¸¡…¹‘¥‘…Ñ•}¥‘Ì¤°(€€€€€€€€€€€€‰‰¥¹‘}Í¹…ÁÍ¡½Ñ}½Õ¹Ğˆè±•¸¡‰¥¹‘}¥‘Ì¤°(€€€€€€€€€€€€‰­¥­•ˆè­¥­•°€‰™…¥±•ˆèmt°(€€€€€€€€€€€€‰É½ÕÁ}¥ˆèÉ½ÕÁ}¥°(€€€€€€€€€€€€‰¹½Ñ”ˆè€‹šâ³¢¦›š¢‡šN°¡¹½Ó–¾›¦još&L1%9A$¤ˆ°(€€€€€€€ô¤°€ÈÀÀ((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½™É¥•¹‘Ì½¥¹Ù¥Ñ”ˆ¤(€€€‘•˜™É¥•¹‘Í}¥¹Ù¥Ñ•}…Á¤ ¤è(€€€€€€€‘…Ñ„°½‘”€ôÉ•…Ñ•}™É¥•¹‘}¥¹Ù¥Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t°É•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½™É¥•¹‘Ì½…•ÁĞˆ¤(€€€‘•˜™É¥•¹‘Í}…•ÁÑ}…Á¤ ¤è(€€€€€€€‘…Ñ„°½‘”€ô…•ÁÑ}™É¥•¹‘}¥¹Ù¥Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t°É•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹•Ğ ˆ½…Á¤½™É¥•¹‘Ì½±½…Ñ¥½¹Ìˆ¤(€€€‘•˜™É¥•¹‘Í}±½…Ñ¥½¹Í}…Á¤ ¤è(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡™É¥•¹‘}±½…Ñ¥½¹Ì¡…ÁÀ¹½¹™¥l‰Q}%1‰t°É•ÅÕ•ÍĞ¹…ÉÌ¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤¤¤((€€€…ÁÀ¹•Ğ ˆ½…Á¤½±½…Ñ¥½¸½ÍÑ…ÑÕÌˆ¤(€€€‘•˜±½…Ñ¥½¹}ÍÑ…ÑÕÍ}…Á¤ ¤è(€€€€€€€±¥¹•}ÕÍ•É}¥€ôÍÑÈ¡É•ÅÕ•ÍĞ¹…ÉÌ¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€¥˜¹½Ğ±¥¹•}ÕÍ•É}¥è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰µ¥ÍÍ¥¹œ±¥¹•}ÕÍ•É}¥‰ô¤°€ĞÀÀ(€€€€€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤(€€€€€€€ÁÉ½™¥±”€ô•Ñ}ÁÉ½™¥±”¡ÍÑ…Ñ”°±¥¹•}ÕÍ•É}¥¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¬ˆèQÉÕ”°€‰Í…™•Ñå}Õ…ÉˆèÍ…™•Ñå}Õ…É‘}Í¹…ÁÍ¡½Ğ¡ÁÉ½™¥±”¥ô¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½±½…Ñ¥½¸½ÕÁ‘…Ñ”ˆ¤(€€€‘•˜±½…Ñ¥½¹}ÕÁ‘…Ñ•}…Á¤ ¤è(€€€€€€€‘…Ñ„°½‘”€ôÕÁ‘…Ñ•}±½…Ñ¥½¸ (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€É•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô°(€€€€€€€€€€€…ÁÀ¹½¹™¥œ°(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½±½…Ñ¥½¸½ÍÑ½Àˆ¤(€€€‘•˜±½…Ñ¥½¹}ÍÑ½Á}…Á¤ ¤è(€€€€€€€‘…Ñ„°½‘”€ôÍÑ½Á}±½…Ñ¥½¹}Í¡…É¥¹œ¡…ÁÀ¹½¹™¥l‰Q}%1‰t°É•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½Í½Ìˆ¤(€€€‘•˜Í½Í}…Á¤ ¤è(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€‘…Ñ„°½‘”€ôÑÉ¥•É}Í½Ì¡…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…°…ÁÀ¹½¹™¥œ¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½ÑÉ¥…°½Ñ•ÍĞµ…Ñ¥½¸ˆ¤(€€€‘•˜ÑÉ¥…±}Ñ•ÍÑ}…Ñ¥½¹}…Á¤ ¤è(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€‘…Ñ„°½‘”€ô…ÕÑ¡½É¥é•}±…‰•±•‘}Ñ•ÍÑ}…Ñ¥½¸ (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€Á…å±½…¹•Ğ ‰…Ñ¥½¸ˆ¤°(€€€€€€€€¤(€€€€€€€¥˜½‘”€ôô€ÈÀÀ…¹‘…Ñ„¹•Ğ ‰…±±½İ•ˆ¤è(€€€€€€€€€€€Ñ½­•¸€ô…ÁÀ¹½¹™¥œ¹•Ğ ‰1%9}!991}MM}Q=-8ˆ¤½È½Ì¹•¹Ù¥É½¸¹•Ğ (€€€€€€€€€€€€€€€€‰1%9}!991}MM}Q=-8ˆ°€ˆˆ(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜¹½ĞÑ½­•¸è(€€€€€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì(€€€€€€€€€€€€€€€€€€€€¨©‘…Ñ„°(€€€€€€€€€€€€€€€€€€€€‰…±±½İ•ˆè…±Í”°(€€€€€€€€€€€€€€€€€€€€‰É•…Í½¸ˆè€‰ÁÕÍ¡}Õ¹…Ù…¥±…‰±”ˆ°(€€€€€€€€€€€€€€€ô¤°€ÔÀÌ(€€€€€€€€€€€Í•¹‘•È€ô…ÁÀ¹½¹™¥œ¹•Ğ ‰1%9}AUM!}M9Hˆ¤½È±¥¹•}ÁÕÍ¡}µ•ÍÍ…”(€€€€€€€€€€€É•ÑÉå}­•ä€ô}±¥¹•}É•ÑÉå}­•ä¡‘…Ñ…l‰•Ù•¹Ñ}¥‰t¤(€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€}Í•¹‘}±¥¹•}İ¥Ñ¡}É•ÑÉå}­•ä (€€€€€€€€€€€€€€€€€€€Í•¹‘•È°Ñ½­•¸°±¥¹•}ÕÍ•É}¥°‘…Ñ…l‰µ•ÍÍ…”‰t°É•ÑÉå}­•ä(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€µÕÑ…Ñ•}ÍÑ…Ñ•}…Ñ½µ¥…±±ä (€€€€€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€€€€€±…µ‰‘„ÍÑ…Ñ”èÉ•½É‘}±¥¹•}µ•ÍÍ…•}ÕÍ…” (€€€€€€€€€€€€€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€€€€€€€€€€€€€…Ñ•½Éäõ˜‰ÑÉ¥…±}íÁ…å±½…¹•Ğ …Ñ¥½¸œ¥õ}Ñ•ÍĞˆ°(€€€€€€€€€€€€€€€€€€€€€€€½İ¹•É}±¥¹•}ÕÍ•É}¥õ±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€€€€€€€€€É•¥Á¥•¹Ñ}½Õ¹ĞôÄ°(€€€€€€€€€€€€€€€€€€€€€€€•Ù•¹Ñ}¥õ‘…Ñ…l‰•Ù•¹Ñ}¥‰t°(€€€€€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€‘…Ñ…l‰‘•±¥Ù•Éä‰t€ô€‰Í•¹Ğˆ(€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€€€€€…ÁÀ¹±½•È¹İ…É¹¥¹œ ‰ÑÉ¥…°Ñ•ÍĞ‘•±¥Ù•Éä™…¥±•è€•Ìˆ°•áŒ¤(€€€€€€€€€€€€€€€‘…Ñ…l‰‘•±¥Ù•Éä‰t€ô€‰™…¥±•ˆ(€€€€€€€€€€€€€€€‘…Ñ…l‰É•…Í½¸‰t€ô€‰ÁÕÍ¡}™…¥±•ˆ(€€€€€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°€ÔÀÈ(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½Í½Ì½…¹•°ˆ¤(€€€‘•˜Í½Í}…¹•±}…Á¤ ¤è(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€‘…Ñ„°½‘”€ô…¹•±}Í½Í}•Ù•¹Ğ¡…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…°…ÁÀ¹½¹™¥œ¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½Í½Ì½É•ÑÉäˆ¤(€€€‘•˜Í½Í}É•ÑÉå}…Á¤ ¤è(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€‘…Ñ„°½‘”€ôÉ•ÑÉå}Í½Í}•Ù•¹Ğ¡…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…°…ÁÀ¹½¹™¥œ¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹•Ğ ˆ½…Á¤½Í½Ì½ÍÑ…ÑÕÌˆ¤(€€€‘•˜Í½Í}ÍÑ…ÑÕÍ}…Á¤ ¤è(€€€€€€€Á…å±½…€ôì‰±¥¹•}ÕÍ•É}¥ˆèÉ•ÅÕ•ÍĞ¹…ÉÌ¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ°€ˆˆ¥ô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€‘…Ñ„°½‘”€ô•Ñ}Í½Í}•Ù•¹Ñ}ÍÑ…ÑÕÌ (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€É•ÅÕ•ÍĞ¹…ÉÌ¹•Ğ ‰•Ù•¹Ñ}¥ˆ°€ˆˆ¤°(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½Í½Ì½É•ÍÁ½¹ˆ¤(€€€‘•˜Í½Í}É•ÍÁ½¹‘}…Á¤ ¤è(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€‘…Ñ„°½‘”€ôÉ•ÍÁ½¹‘}Ñ½}Í½Í}•Ù•¹Ğ (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…°…ÁÀ¹½¹™¥œ(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½Í½Ì½Í…™”ˆ¤(€€€‘•˜Í½Í}Í…™•}…Á¤ ¤è(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€‘…Ñ„°½‘”€ô±½Í•}Í½Í}…Í}Í…™” (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…°…ÁÀ¹½¹™¥œ(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹•Ğ ˆ½…Á¤½‰½Ğ½Õ…É‘¥…¸µÉ½ÕÁÌˆ¤(€€€‘•˜‰½Ñ}Õ…É‘¥…¹}É½ÕÁÍ}…Á¤ ¤è(€€€€€€€€ˆˆˆÈÀÈØ´ÀÜ´ÈÄÁ…Ñ €ÈÈèƒ¢şS–n{š&šr'–º#¢¶ßú“šâ–Z¸£’úl‰½Ñ}…‘µ¥¸¹¡Ñµ°§ˆˆˆ(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•((€€€€€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤(€€€€€€€É½ÕÁÌ€ôÍÑ…Ñ”¹•Ğ ‰Õ…É‘¥…¹}É½ÕÁÌˆ°íô¤(€€€€€€€ÕÍ•ÉÌ€ôÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ°íô¤(€€€€€€€½ÕĞ€ômt(€€€€€€€™½È¥°œ¥¸É½ÕÁÌ¹¥Ñ•µÌ ¤è(€€€€€€€€€€€½İ¹•É}¥€ôœ¹•Ğ ‰½İ¹•É}±¥¹•}ÕÍ•É}¥ˆ°€ˆˆ¤(€€€€€€€€€€€½İ¹•É}ÁÉ½™¥±”€ôÕÍ•ÉÌ¹•Ğ¡½İ¹•É}¥°íô¤(€€€€€€€€€€€½ÕĞ¹…ÁÁ•¹¡ì(€€€€€€€€€€€€€€€€‰É½ÕÁ}¥ˆè¥°(€€€€€€€€€€€€€€€€‰½İ¹•É}¥ˆè½İ¹•É}¥‘lèÙt€¬€ˆ¸¸¸ˆ€¬½İ¹•É}¥‘l´Ğét¥˜½İ¹•É}¥•±Í”9½¹”°(€€€€€€€€€€€€€€€€‰½İ¹•É}Á±…¸ˆè½İ¹•É}ÁÉ½™¥±”¹•Ğ ‰Á±…¸ˆ¤°(€€€€€€€€€€€€€€€€‰µ•µ‰•É}½Õ¹Ñ}…Ñ}‰¥¹ˆèœ¹•Ğ ‰µ•µ‰•É}½Õ¹Ñ}…Ñ}‰¥¹ˆ¤°(€€€€€€€€€€€€€€€€‰É•…Ñ•‘}…Ğˆèœ¹•Ğ ‰É•…Ñ•‘}…Ğˆ¤°(€€€€€€€€€€€€€€€€‰ÍÑ…ÑÕÌˆèœ¹•Ğ ‰ÍÑ…ÑÕÌˆ¤°(€€€€€€€€€€€ô¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰É½ÕÁÌˆè½ÕĞ°€‰Ñ½Ñ…°ˆè±•¸¡½ÕĞ¥ô¤((€€€…ÁÀ¹•Ğ ˆ½…Á¤½‰½Ğ½Í½ÌµÁ•¹‘¥¹œˆ¤(€€€‘•˜‰½Ñ}Í½Í}Á•¹‘¥¹}…Á¤ ¤è(€€€€€€€€ˆˆ‰I•ÑÕÉ¸M=LÁÉ½É•ÍÌ°‘•±¥Ù•Éä•Ù•¹ÑÌ…¹É…‘•Í…™•ÑäÉ•ÍÑÉ¥Ñ¥½¹Ì¸ˆˆˆ(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•((€€€€€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤(€€€€€€€Á•¹‘¥¹œ€ôÍÑ…Ñ”¹•Ğ ‰Í½Í}Á•¹‘¥¹œˆ°íô¤(€€€€€€€½ÕĞ€ômt(€€€€€€€™½ÈÕ¥°À¥¸Á•¹‘¥¹œ¹¥Ñ•µÌ ¤è(€€€€€€€€€€€½ÕĞ¹…ÁÁ•¹¡ì(€€€€€€€€€€€€€€€€‰ÕÍ•É}¥ˆèÕ¥‘lèÙt€¬€ˆ¸¸¸ˆ€¬Õ¥‘l´Ğét°(€€€€€€€€€€€€€€€€‰ÍÑ…”ˆèÀ¹•Ğ ‰ÍÑ…”ˆ¤°(€€€€€€€€€€€€€€€€‰Ñ…Á}½Õ¹ĞˆèÀ¹•Ğ ‰Ñ…Á}½Õ¹Ğˆ¤°(€€€€€€€€€€€€€€€€‰™¥ÉÍÑ}Ñ…Á}…ĞˆèÀ¹•Ğ ‰™¥ÉÍÑ}Ñ…Á}…Ğˆ¤°(€€€€€€€€€€€€€€€€‰±…ÍÑ}Ñ…Á}…ĞˆèÀ¹•Ğ ‰±…ÍÑ}Ñ…Á}…Ğˆ¤°(€€€€€€€€€€€€€€€€‰Í•¹Ñ}…ĞˆèÀ¹•Ğ ‰Í•¹Ñ}…Ğˆ¤°(€€€€€€€€€€€€€€€€‰•Ù•¹Ñ}¥ˆèÀ¹•Ğ ‰•Ù•¹Ñ}¥ˆ¤°(€€€€€€€€€€€€€€€€‰…¹•±±•‘}…ĞˆèÀ¹•Ğ ‰…¹•±±•‘}…Ğˆ¤°(€€€€€€€€€€€ô¤(€€€€€€€€Œ…Ñ¥Ù”ƒ–r£–&4£¢¶›–F(½İ…É¹¥¹œ¤±Í•¹Ğ±…¹•±±•ƒ–r£–ú0(€€€€€€€½ÕĞ¹Í½ÉĞ¡­•äõ±…µ‰‘„àè€¡à¹•Ğ ‰ÍÑ…”ˆ°€ˆˆ¤¹½Ğ¥¸€ ‰İ…É¹¥¹|Äˆ°€‰İ…É¹¥¹|Èˆ°€‰İ…É¹¥¹|Ìˆ¤°à¹•Ğ ‰±…ÍÑ}Ñ…Á}…Ğˆ¤½È€ˆˆ¤¤(€€€€€€€•Ù•¹ÑÌ€ômt(€€€€€€€™½È•Ù•¹Ğ¥¸€¡ÍÑ…Ñ”¹•Ğ ‰Í½Í}•Ù•¹ÑÌˆ¤½Èíô¤¹Ù…±Õ•Ì ¤è(€€€€€€€€€€€½İ¹•È€ôÍÑÈ¡•Ù•¹Ğ¹•Ğ ‰½İ¹•É}±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¤(€€€€€€€€€€€‘•±¥Ù•É¥•Ì€ô•Ù•¹Ğ¹•Ğ ‰‘•±¥Ù•É¥•Ìˆ¤½Èmt(€€€€€€€€€€€•Ù•¹ÑÌ¹…ÁÁ•¹¡ì(€€€€€€€€€€€€€€€€‰•Ù•¹Ñ}¥ˆè•Ù•¹Ğ¹•Ğ ‰•Ù•¹Ñ}¥ˆ¤°(€€€€€€€€€€€€€€€€‰½İ¹•É}¥ˆè½İ¹•ÉlèÙt€¬€ˆ¸¸¸ˆ€¬½İ¹•Él´Ğét¥˜½İ¹•È•±Í”9½¹”°(€€€€€€€€€€€€€€€€‰½İ¹•É}‘¥ÍÁ±…å}¹…µ”ˆè•Ù•¹Ğ¹•Ğ ‰½İ¹•É}‘¥ÍÁ±…å}¹…µ”ˆ¤°(€€€€€€€€€€€€€€€€‰ÍÑ…ÑÕÌˆè•Ù•¹Ğ¹•Ğ ‰ÍÑ…ÑÕÌˆ¤°(€€€€€€€€€€€€€€€€‰Í•¹Ñ}…Ğˆè•Ù•¹Ğ¹•Ğ ‰Í•¹Ñ}…Ğˆ¤°(€€€€€€€€€€€€€€€€‰…¹•±±•‘}…Ğˆè•Ù•¹Ğ¹•Ğ ‰…¹•±±•‘}…Ğˆ¤°(€€€€€€€€€€€€€€€€‰Í•¹ĞˆèÍÕ´ Ä™½È¥Ñ•´¥¸‘•±¥Ù•É¥•Ì¥˜¥Ñ•´¹•Ğ ‰ÍÑ…ÑÕÌˆ¤€ôô€‰Í•¹Ğˆ¤°(€€€€€€€€€€€€€€€€‰™…¥±•ˆèÍÕ´ Ä™½È¥Ñ•´¥¸‘•±¥Ù•É¥•Ì¥˜¥Ñ•´¹•Ğ ‰ÍÑ…ÑÕÌˆ¤€ôô€‰™…¥±•ˆ¤°(€€€€€€€€€€€€€€€€‰…‰ÕÍ•}µ½‘”ˆè•Ù•¹Ğ¹•Ğ ‰…‰ÕÍ•}µ½‘”ˆ¤½È€‰¹½Éµ…°ˆ°(€€€€€€€€€€€ô¤(€€€€€€€•Ù•¹ÑÌ¹Í½ÉĞ¡­•äõ±…µ‰‘„¥Ñ•´è¥Ñ•´¹•Ğ ‰Í•¹Ñ}…Ğˆ¤½È€ˆˆ°É•Ù•ÉÍ”õQÉÕ”¤(€€€€€€€…‰ÕÍ”€ôì‰½‰Í•ÉÙ…Ñ¥½¸ˆè€À°€‰É•ÍÑÉ¥Ñ•ˆè€Áô(€€€€€€€™½ÈÁÉ½™¥±”¥¸€¡ÍÑ…Ñ”¹•Ğ ‰ÕÍ•ÉÌˆ¤½Èíô¤¹Ù…±Õ•Ì ¤è(€€€€€€€€€€€µ½‘”€ôÍ½Í}…‰ÕÍ•}ÍÑ…Ñ”¡ÁÉ½™¥±”°ÕÉÉ•¹Ñ}…ÁÁ}Ñ¥µ”¡…ÁÀ¹½¹™¥œ¤¤¹•Ğ ‰µ½‘”ˆ¤(€€€€€€€€€€€¥˜µ½‘”¥¸…‰ÕÍ”è(€€€€€€€€€€€€€€€…‰ÕÍ•mµ½‘•t€¬ô€Ä(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì(€€€€€€€€€€€€‰Á•¹‘¥¹œˆè½ÕĞ°(€€€€€€€€€€€€‰Ñ½Ñ…°ˆè±•¸¡½ÕĞ¤°(€€€€€€€€€€€€‰•Ù•¹ÑÌˆè•Ù•¹ÑÍlèÔÁt°(€€€€€€€€€€€€‰•Ù•¹Ñ}Ñ½Ñ…°ˆè±•¸¡•Ù•¹ÑÌ¤°(€€€€€€€€€€€€‰…‰ÕÍ”ˆè…‰ÕÍ”°(€€€€€€€ô¤((€€€…ÁÀ¹•Ğ ˆ½…Á¤½‰½Ğ½É••¹Ğµ•Ù•¹ÑÌˆ¤(€€€‘•˜‰½Ñ}É••¹Ñ}•Ù•¹ÑÍ}…Á¤ ¤è(€€€€€€€€ˆˆˆÈÀÈØ´ÀÜ´ÈÄÁ…Ñ €ÈÈèƒ¢şS–n{šr¢şGjİ•‰¡½½¬ƒ’ê/’îØ£’öÿR ¹½Ñ¥™¥…Ñ¥½¹}±½œ§ˆˆˆ(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•((€€€€€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤(€€€€€€€±½œ€ôÍÑ…Ñ”¹•Ğ ‰¹½Ñ¥™¥…Ñ¥½¹}±½œˆ°mt¤(€€€€€€€É••¹Ğ€ô±½l´ÈÀét€€Œƒšr¢şD€ÈÀƒšŠt(€€€€€€€É••¹Ğ¹É•Ù•ÉÍ” ¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰É••¹ĞˆèÉ••¹Ğ°€‰Ñ½Ñ…°ˆè±•¸¡±½œ¥ô¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½Í½Ì½¡•¬µÍ¡•‘Õ±•ˆ¤(€€€‘•˜Í½Í}¡•­}Í¡•‘Õ±•‘}…Á¤ ¤è(€€€€€€€€ˆˆˆÈÀÈØ´ÀÜ´ÈÄÁ…Ñ €ÈÄèÉ½¸ƒ®¿¦îxƒŠPƒšâB¦;šr|M=LƒÒ¦2((€€€€€€€€ÌµÑ…ÀƒšÖ¢/šr®/–6Ïfó¦³š&’î—¦g–,É½¸ƒ–>«¢Êƒ¢Ê°è(€€€€€€€€Ä¸ƒšâš:$€Äƒ–Â?šf’î—–&7jÍ•¹Ğ½…¹•±±•ƒÒ¦2£¦ÿ–4ÍÑ…Ñ”ƒ¢£¢Ô¤(€€€€€€€ƒšr«’ú–>¿–*€ë–r Í•¹Ñ}…Ğƒ–ú0€Ôƒ–"¦Bcš>C¦K3–>¿’î—–>[šÚ#’ê7¶$(€€€€€€€€ˆˆˆ(€€€€€€€™É½´Í½Í}™±½Ü¥µÁ½ÉĞÍ½Í}ÁÕÉ•}½±(€€€€€€€™É½´‘…Ñ•Ñ¥µ”¥µÁ½ÉĞ‘…Ñ•Ñ¥µ”((€€€€€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤(€€€€€€€¹½Ü€ô‘…Ñ•Ñ¥µ”¹¹½Ü ¤(€€€€€€€É•µ½Ù•€ôÍ½Í}ÁÕÉ•}½±¡ÍÑ…Ñ”°­••Á}µ¥¹ÕÑ•ÌôØÀ¤(€€€€€€€Í…Ù•}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t°ÍÑ…Ñ”¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì(€€€€€€€€€€€€‰¡•­•‘}…Ğˆè¹½Ü¹¥Í½™½Éµ…Ğ¡Ñ¥µ•ÍÁ•Œô‰Í•½¹‘Ìˆ¤°(€€€€€€€€€€€€‰ÁÕÉ•ˆè±•¸¡É•µ½Ù•¤°(€€€€€€€ô¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…½Õ¹Ğ½‘•±•Ñ”ˆ¤(€€€‘•˜…½Õ¹Ñ}‘•±•Ñ•}…Á¤ ¤è(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€‘…Ñ„°½‘”€ô‘•±•Ñ•}…½Õ¹Ğ¡…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…½Õ¹Ğ½•áÁ½ÉĞˆ¤(€€€‘•˜…½Õ¹Ñ}•áÁ½ÉÑ}…Á¤ ¤è(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€‘…Ñ„°½‘”€ô•áÁ½ÉÑ}…½Õ¹Ñ}‘…Ñ„¡…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…½Õ¹Ğ½¡¥ÍÑ½Éä½‘•±•Ñ”ˆ¤(€€€‘•˜…½Õ¹Ñ}¡¥ÍÑ½Éå}‘•±•Ñ•}…Á¤ ¤è(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€‘…Ñ„°½‘”€ô‘•±•Ñ•}Á•ÉÍ½¹…±}¡¥ÍÑ½Éä¡…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€‘•˜}µ¥É…Ñ¥½¹}Ù•É¥™¥•‘}ÍÕ‰©•Ğ¡Á…å±½…°¡…¹¹•±}­•ä¤è(€€€€€€€¥˜¹½Ğ…½Õ¹Ñ}µ¥É…Ñ¥½¹}É•…‘ä¡…ÁÀ¹½¹™¥œ¤è(€€€€€€€€€€€É•ÑÕÉ¸9½¹”°€¡ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰µ¥É…Ñ¥½¹}Õ¹…Ù…¥±…‰±”‰ô°€ÔÀÌ¤(€€€€€€€¥˜•áÑÉ…Ñ}¥‘}Ñ½­•¸¥Ì9½¹”½ÈÙ•É¥™å}±¥¹•}¥‘}Ñ½­•¹}™½É}¡…¹¹•°¥Ì9½¹”è(€€€€€€€€€€€É•ÑÕÉ¸9½¹”°€¡ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰µ¥É…Ñ¥½¹}Õ¹…Ù…¥±…‰±”‰ô°€ÔÀÌ¤(€€€€€€€Ñ½­•¸€ô•áÑÉ…Ñ}¥‘}Ñ½­•¸ (€€€€€€€€€€€í­•äèÙ…±Õ”™½È­•ä°Ù…±Õ”¥¸É•ÅÕ•ÍĞ¹¡•…‘•ÉÌ¹¥Ñ•µÌ ¥ô°(€€€€€€€€€€€Á…å±½…°(€€€€€€€€€€€íô°(€€€€€€€€¤(€€€€€€€ÍÕ‰©•Ğ€ôÙ•É¥™å}±¥¹•}¥‘}Ñ½­•¹}™½É}¡…¹¹•° (€€€€€€€€€€€Ñ½­•¸°(€€€€€€€€€€€…ÁÀ¹½¹™¥œ¹•Ğ¡¡…¹¹•±}­•ä¤°(€€€€€€€€¤(€€€€€€€¥˜¹½ĞÍÕ‰©•Ğè(€€€€€€€€€€€É•ÑÕÉ¸9½¹”°€¡ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰¥¹Ù…±¥‘}Ñ½­•¸‰ô°€ĞÀÄ¤(€€€€€€€É•ÑÕÉ¸ÍÕ‰©•Ğ°9½¹”((€€€…ÁÀ¹…™Ñ•É}É•ÅÕ•ÍĞ(€€€‘•˜}‘¥Í…‰±•}…½Õ¹Ñ}µ¥É…Ñ¥½¹}É•ÍÁ½¹Í•}…¡¥¹œ¡É•ÍÁ½¹Í”¤è(€€€€€€€¥˜É•ÅÕ•ÍĞ¹Á…Ñ ¹ÍÑ…ÉÑÍİ¥Ñ  ˆ½…Á¤½…½Õ¹Ğµµ¥É…Ñ¥½¸¼ˆ¤è(€€€€€€€€€€€É•ÍÁ½¹Í”¹¡•…‘•ÉÍl‰…¡”µ½¹ÑÉ½°‰t€ô€‰¹¼µÍÑ½É”ˆ(€€€€€€€É•ÑÕÉ¸É•ÍÁ½¹Í”((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…½Õ¹Ğµµ¥É…Ñ¥½¸½ÍÑ…ÉĞˆ¤(€€€‘•˜…½Õ¹Ñ}µ¥É…Ñ¥½¹}ÍÑ…ÉÑ}…Á¤ ¤è(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤(€€€€€€€¥˜¹½Ğ¥Í¥¹ÍÑ…¹”¡Á…å±½…°‘¥Ğ¤è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰¥¹Ù…±¥‘}É•ÅÕ•ÍĞ‰ô¤°€ĞÀÀ(€€€€€€€½±‘}±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}µ¥É…Ñ¥½¹}Ù•É¥™¥•‘}ÍÕ‰©•Ğ (€€€€€€€€€€€Á…å±½…°(€€€€€€€€€€€€‰1e}1%9}1=%9}!991}%ˆ°(€€€€€€€€¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€‘…Ñ„°½‘”€ôÉ•…Ñ•}…½Õ¹Ñ}µ¥É…Ñ¥½¹}Ñ¥­•Ğ (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€½±‘}±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€…ÁÀ¹½¹™¥œ°(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹•Ğ ˆ½…Á¤½…½Õ¹Ğµµ¥É…Ñ¥½¸½ÍÑ…ÑÕÌˆ¤(€€€‘•˜…½Õ¹Ñ}µ¥É…Ñ¥½¹}ÍÑ…ÑÕÍ}…Á¤ ¤è(€€€€€€€½±‘}±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}µ¥É…Ñ¥½¹}Ù•É¥™¥•‘}ÍÕ‰©•Ğ (€€€€€€€€€€€íô°(€€€€€€€€€€€€‰1e}1%9}1=%9}!991}%ˆ°(€€€€€€€€¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€‘…Ñ„€ô…½Õ¹Ñ}µ¥É…Ñ¥½¹}Ñ¥­•Ñ}ÍÑ…ÑÕÌ (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€½±‘}±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€…ÁÀ¹½¹™¥œ°(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…½Õ¹Ğµµ¥É…Ñ¥½¸½É•‘••´ˆ¤(€€€‘•˜…½Õ¹Ñ}µ¥É…Ñ¥½¹}É•‘••µ}…Á¤ ¤è(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤(€€€€€€€¥˜¹½Ğ¥Í¥¹ÍÑ…¹”¡Á…å±½…°‘¥Ğ¤è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰¥¹Ù…±¥‘}É•ÅÕ•ÍĞ‰ô¤°€ĞÀÀ(€€€€€€€¹•İ}±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}µ¥É…Ñ¥½¹}Ù•É¥™¥•‘}ÍÕ‰©•Ğ (€€€€€€€€€€€Á…å±½…°(€€€€€€€€€€€€‰1%9}1=%9}!991}%ˆ°(€€€€€€€€¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€‘…Ñ„°½‘”€ôÉ•‘••µ}…½Õ¹Ñ}µ¥É…Ñ¥½¹}Ñ¥­•Ğ (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€Á…å±½…¹•Ğ ‰µ¥É…Ñ¥½¹}½‘”ˆ¤°(€€€€€€€€€€€¹•İ}±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€…ÁÀ¹½¹™¥œ°(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…½Õ¹Ğ½ÁÉ¥Ù…äµÉ•ÅÕ•ÍĞˆ¤(€€€‘•˜…½Õ¹Ñ}ÁÉ¥Ù…å}É•ÅÕ•ÍÑ}…Á¤ ¤è(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€‘…Ñ„°½‘”€ôÉ•…Ñ•}ÁÉ¥Ù…å}É•ÅÕ•ÍĞ¡…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹•Ğ ˆ½…Á¤½…‘µ¥¸½ÍÕµµ…Éäˆ¤(€€€‘•˜…‘µ¥¹}ÍÕµµ…Éå}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡…‘µ¥¹}ÍÕµµ…Éä¡…ÁÀ¹½¹™¥l‰Q}%1‰t°…ÁÀ¹½¹™¥œ¤¤((€€€…ÁÀ¹•Ğ ˆ½…Á¤½…‘µ¥¸½Ñ•ÍĞµ•¹Ñ•Èˆ¤(€€€‘•˜…‘µ¥¹}Ñ•ÍÑ}•¹Ñ•É}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡…‘µ¥¹}Ñ•ÍÑ}•¹Ñ•É}ÍÑ…ÑÕÌ¡…ÁÀ¹½¹™¥l‰Q}%1‰t°…ÁÀ¹½¹™¥œ¤¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…‘µ¥¸½Ñ•ÍĞµ•¹Ñ•È½ÉÕ¸ˆ¤(€€€‘•˜…‘µ¥¹}Ñ•ÍÑ}•¹Ñ•É}ÉÕ¹}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É¡İÉ¥Ñ”õQÉÕ”¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€‘…Ñ„°½‘”€ôÉÕ¹}…‘µ¥¹}Ñ•ÍĞ (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€…ÁÀ¹½¹™¥œ°(€€€€€€€€€€€É•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô°(€€€€€€€€¤(€€€€€€€…ÁÁ•¹‘}…‘µ¥¹}…Õ‘¥Ğ (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€˜‰Ñ•ÍÑ}•¹Ñ•È¹í‘…Ñ„¹•Ğ Ñ•ÍÑ}¥œ¤½È€Õ¹­¹½İ¸ôˆ°(€€€€€€€€€€€€‰ÍÕ•ÍÌˆ¥˜½‘”€ğ€ĞÀÀ•±Í”€‰™…¥±•ˆ°(€€€€€€€€€€€ì‰¡ÑÑÁ}ÍÑ…ÑÕÌˆè½‘”°€‰Ñ•ÍÑ}µ½‘”ˆèQÉÕ•ô°(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹•Ğ ˆ½…Á¤½…‘µ¥¸½…½Õ¹Ğµµ¥É…Ñ¥½¹Ìˆ¤(€€€‘•˜…‘µ¥¹}…½Õ¹Ñ}µ¥É…Ñ¥½¹Í}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä (€€€€€€€€€€€…‘µ¥¹}…½Õ¹Ñ}µ¥É…Ñ¥½¹Ì (€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥œ°(€€€€€€€€€€€€¤(€€€€€€€€¤((€€€…ÁÀ¹•Ğ ˆ½…Á¤½…‘µ¥¸½‰•Ñ„µµ•µ‰•ÉÌˆ¤(€€€‘•˜…‘µ¥¹}‰•Ñ…}µ•µ‰•ÉÍ}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‰•Ñ…}µ•µ‰•ÉÍ}Í¹…ÁÍ¡½Ğ¡±½…‘}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤¤¤((€€€…ÁÀ¹•Ğ ˆ½…Á¤½…‘µ¥¸½±¥¹”µ…•ÁÑ…¹”ˆ¤(€€€‘•˜…‘µ¥¹}±¥¹•}…•ÁÑ…¹•}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä (€€€€€€€€€€€±¥¹•}…•ÁÑ…¹•}Í¹…ÁÍ¡½Ğ¡±½…‘}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤¤(€€€€€€€€¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…‘µ¥¸½±¥¹”µ…•ÁÑ…¹”ˆ¤(€€€‘•˜…‘µ¥¹}±¥¹•}…•ÁÑ…¹•}É•…Ñ•}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É¡İÉ¥Ñ”õQÉÕ”¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€ÑÉäè(€€€€€€€€€€€É•ÍÕ±Ğ€ôµÕÑ…Ñ•}ÍÑ…Ñ•}…Ñ½µ¥…±±ä (€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€±…µ‰‘„ÍÑ…Ñ”èÉ•…Ñ•}±¥¹•}…•ÁÑ…¹•}…Í”¡ÍÑ…Ñ”°Á…å±½…¤°(€€€€€€€€€€€€¤(€€€€€€€•á•ÁĞY…±Õ•ÉÉ½È…Ì•áŒè(€€€€€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” (€€€€€€€€€€€€€€€€‰±¥¹•}…•ÁÑ…¹”¹É•…Ñ”ˆ°(€€€€€€€€€€€€€€€ì‰½¬ˆè…±Í”°€‰•ÉÉ½ÈˆèÍÑÈ¡•áŒ¥ô°(€€€€€€€€€€€€€€€€ĞÀÀ°(€€€€€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” (€€€€€€€€€€€€‰±¥¹•}…•ÁÑ…¹”¹É•…Ñ”ˆ°(€€€€€€€€€€€ì‰½¬ˆèQÉÕ”°€¨©É•ÍÕ±Ñô°(€€€€€€€€¤((€€€…ÁÀ¹Á…Ñ  ˆ½…Á¤½…‘µ¥¸½±¥¹”µ…•ÁÑ…¹”¼ñ…Í•}¥øˆ¤(€€€‘•˜…‘µ¥¹}±¥¹•}…•ÁÑ…¹•}É•Ù¥•İ}…Á¤¡…Í•}¥¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É¡İÉ¥Ñ”õQÉÕ”¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€ÑÉäè(€€€€€€€€€€€É•ÍÕ±Ğ€ôµÕÑ…Ñ•}ÍÑ…Ñ•}…Ñ½µ¥…±±ä (€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€±…µ‰‘„ÍÑ…Ñ”èÉ•Ù¥•İ}±¥¹•}…•ÁÑ…¹•}…Í” (€€€€€€€€€€€€€€€€€€€ÍÑ…Ñ”°…Í•}¥°Á…å±½…(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€¤(€€€€€€€•á•ÁĞY…±Õ•ÉÉ½È…Ì•áŒè(€€€€€€€€€€€•ÉÉ½È€ôÍÑÈ¡•áŒ¤(€€€€€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” (€€€€€€€€€€€€€€€€‰±¥¹•}…•ÁÑ…¹”¹É•Ù¥•Üˆ°(€€€€€€€€€€€€€€€ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè•ÉÉ½Éô°(€€€€€€€€€€€€€€€€ĞÀĞ¥˜•ÉÉ½È€ôô€‰…•ÁÑ…¹•}…Í•}¹½Ñ}™½Õ¹ˆ•±Í”€ĞÀÀ°(€€€€€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” (€€€€€€€€€€€€‰±¥¹•}…•ÁÑ…¹”¹É•Ù¥•Üˆ°(€€€€€€€€€€€ì‰½¬ˆèQÉÕ”°€¨©É•ÍÕ±Ñô°(€€€€€€€€¤((€€€…ÁÀ¹•Ğ ˆ½…Á¤½…‘µ¥¸½‰ÕÍ¥¹•ÍÌµ‘…Í¡‰½…Éˆ¤(€€€‘•˜…‘µ¥¹}‰ÕÍ¥¹•ÍÍ}‘…Í¡‰½…É‘}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡…‘µ¥¹}‰ÕÍ¥¹•ÍÍ}‘…Í¡‰½…É¡…ÁÀ¹½¹™¥l‰Q}%1‰t°…ÁÀ¹½¹™¥œ¤¤((€€€…ÁÀ¹•Ğ ˆ½…Á¤½…‘µ¥¸½‰•Ñ„µÁÉ½É…´ˆ¤(€€€‘•˜…‘µ¥¹}‰•Ñ…}ÁÉ½É…µ}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É¡Á•Éµ¥ÍÍ¥½¸ô‰‰•Ñ„¹µ…¹…”ˆ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡…‘µ¥¹}‰•Ñ…}ÍÕµµ…Éä¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…‘µ¥¸½‰•Ñ„µÁÉ½É…´½…ÍÍ¥¸ˆ¤(€€€‘•˜…‘µ¥¹}‰•Ñ…}ÁÉ½É…µ}…ÍÍ¥¹}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É¡İÉ¥Ñ”õQÉÕ”°Á•Éµ¥ÍÍ¥½¸ô‰‰•Ñ„¹µ…¹…”ˆ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€‘…Ñ„°½‘”€ô…ÍÍ¥¹}‰•Ñ…}µ•µ‰•È (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°É•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” ‰‰•Ñ„¹…ÍÍ¥¸ˆ°‘…Ñ„°½‘”¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…‘µ¥¸½‰•Ñ„µµ•µ‰•ÉÌˆ¤(€€€‘•˜…‘µ¥¹}‰•Ñ…}µ•µ‰•É}…ÍÍ¥¹}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É¡İÉ¥Ñ”õQÉÕ”¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€‘…Ñ„°½‘”€ô…‘µ¥¹}…ÍÍ¥¹}‰•Ñ…}µ•µ‰•È (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°É•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” ‰‰•Ñ„¹…ÍÍ¥¸ˆ°‘…Ñ„°½‘”¤((€€€…ÁÀ¹‘•±•Ñ” ˆ½…Á¤½…‘µ¥¸½‰•Ñ„µµ•µ‰•ÉÌ¼ñ±¥¹•}ÕÍ•É}¥øˆ¤(€€€‘•˜…‘µ¥¹}‰•Ñ…}µ•µ‰•É}É•Ù½­•}…Á¤¡±¥¹•}ÕÍ•É}¥¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É¡İÉ¥Ñ”õQÉÕ”¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€‘…Ñ„°½‘”€ô…‘µ¥¹}É•Ù½­•}‰•Ñ…}µ•µ‰•È (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” ‰‰•Ñ„¹É•Ù½­”ˆ°‘…Ñ„°½‘”¤((€€€…ÁÀ¹•Ğ ˆ½…Á¤½…‘µ¥¸½±…Õ¹ µÉ•…‘¥¹•ÍÌˆ¤(€€€‘•˜…‘µ¥¹}±…Õ¹¡}É•…‘¥¹•ÍÍ}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä (€€€€€€€€€€€±…Õ¹¡}É•…‘¥¹•ÍÍ}Í¹…ÁÍ¡½Ğ¡±½…‘}ÍÑ…Ñ”¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤¤(€€€€€€€€¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…‘µ¥¸½±…Õ¹ µÙ…±¥‘…Ñ¥½¸ˆ¤(€€€‘•˜…‘µ¥¹}±…Õ¹¡}Ù…±¥‘…Ñ¥½¹}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É¡İÉ¥Ñ”õQÉÕ”¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€ÑÉäè(€€€€€€€€€€€Í•¹…É¥¼€ôµÕÑ…Ñ•}ÍÑ…Ñ•}…Ñ½µ¥…±±ä (€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€±…µ‰‘„ÍÑ…Ñ”èÉ•½É‘}±…Õ¹¡}Ù…±¥‘…Ñ¥½¹}ÍÑ•À (€€€€€€€€€€€€€€€€€€€ÍÑ…Ñ”°(€€€€€€€€€€€€€€€€€€€Á…å±½…¹•Ğ ‰Í•¹…É¥½}¥ˆ¤°(€€€€€€€€€€€€€€€€€€€Á…å±½…¹•Ğ ‰­¥¹ˆ¤°(€€€€€€€€€€€€€€€€€€€Á…å±½…¹•Ğ ‰ÍÑ•Àˆ¤°(€€€€€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥õÁ…å±½…¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ°(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€¤(€€€€€€€•á•ÁĞY…±Õ•ÉÉ½È…Ì•áŒè(€€€€€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” (€€€€€€€€€€€€€€€€‰±…Õ¹¡}Ù…±¥‘…Ñ¥½¸¹É•½Éˆ°(€€€€€€€€€€€€€€€ì‰½¬ˆè…±Í”°€‰•ÉÉ½ÈˆèÍÑÈ¡•áŒ¥ô°(€€€€€€€€€€€€€€€€ĞÀÀ°(€€€€€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” (€€€€€€€€€€€€‰±…Õ¹¡}Ù…±¥‘…Ñ¥½¸¹É•½Éˆ°(€€€€€€€€€€€ì‰½¬ˆèQÉÕ”°€‰Í•¹…É¥¼ˆèÍ•¹…É¥½ô°(€€€€€€€€€€€€ÈÀÀ°(€€€€€€€€¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…‘µ¥¸½‰•Ñ„µÁÉ½É…´½ÕÁ‘…Ñ”ˆ¤(€€€‘•˜…‘µ¥¹}‰•Ñ…}ÁÉ½É…µ}ÕÁ‘…Ñ•}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É¡İÉ¥Ñ”õQÉÕ”°Á•Éµ¥ÍÍ¥½¸ô‰‰•Ñ„¹µ…¹…”ˆ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€‘…Ñ„°½‘”€ôÕÁ‘…Ñ•}‰•Ñ…}µ•µ‰•È (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°É•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” ‰‰•Ñ„¹ÕÁ‘…Ñ”ˆ°‘…Ñ„°½‘”¤((€€€…ÁÀ¹•Ğ ˆ½…Á¤½…‘µ¥¸½ÁÉ¥Ù…äµÉ•ÅÕ•ÍÑÌˆ¤(€€€‘•˜…‘µ¥¹}ÁÉ¥Ù…å}É•ÅÕ•ÍÑÍ}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É¡Á•Éµ¥ÍÍ¥½¸ô‰ÁÉ¥Ù…ä¹µ…¹…”ˆ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡…‘µ¥¹}ÁÉ¥Ù…å}É•ÅÕ•ÍÑÌ¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…‘µ¥¸½ÁÉ¥Ù…äµÉ•ÅÕ•ÍÑÌ½ÕÁ‘…Ñ”ˆ¤(€€€‘•˜…‘µ¥¹}ÁÉ¥Ù…å}É•ÅÕ•ÍÑÍ}ÕÁ‘…Ñ•}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É¡İÉ¥Ñ”õQÉÕ”°Á•Éµ¥ÍÍ¥½¸ô‰ÁÉ¥Ù…ä¹µ…¹…”ˆ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€‘…Ñ„°½‘”€ôÕÁ‘…Ñ•}ÁÉ¥Ù…å}É•ÅÕ•ÍĞ (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€É•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô°(€€€€€€€€€€€ÍÑÈ¡Í•ÍÍ¥½¸¹•Ğ ‰…‘µ¥¹}É½±”ˆ¤½È€‰Ù¥•İ•Èˆ¤°(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” ‰ÁÉ¥Ù…ä¹ÕÁ‘…Ñ”ˆ°‘…Ñ„°½‘”¤((€€€…ÁÀ¹•Ğ ˆ½…Á¤½…‘µ¥¸½ÍÕÁÁ½ÉĞµÑ¥­•ÑÌˆ¤(€€€‘•˜…‘µ¥¹}ÍÕÁÁ½ÉÑ}Ñ¥­•ÑÍ}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡…‘µ¥¹}ÍÕÁÁ½ÉÑ}Ñ¥­•ÑÌ¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤¤((€€€…ÁÀ¹•Ğ ˆ½…Á¤½ÍÕÁÁ½ÉĞ½Ñ¥­•ÑÌˆ¤(€€€‘•˜µ•µ‰•É}ÍÕÁÁ½ÉÑ}Ñ¥­•ÑÍ}…Á¤ ¤è(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡íô°ÕÍ•}…ÉÌõQÉÕ”¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€‘…Ñ„°½‘”€ôµ•µ‰•É}ÍÕÁÁ½ÉÑ}Ñ¥­•ÑÌ (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½ÍÕÁÁ½ÉĞ½Ñ¥­•ÑÌˆ¤(€€€‘•˜µ•µ‰•É}ÍÕÁÁ½ÉÑ}Ñ¥­•Ñ}É•…Ñ•}…Á¤ ¤è(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€‘…Ñ„°½‘”€ôÉ•…Ñ•}ÍÕÁÁ½ÉÑ}Ñ¥­•Ğ¡…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹•Ğ ˆ½…Á¤½…‘µ¥¸½‰…­ÕÁÌˆ¤(€€€‘•˜…‘µ¥¹}‰…­ÕÁÍ}±¥ÍÑ}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡±¥ÍÑ}…‘µ¥¹}‰…­ÕÁÌ¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…‘µ¥¸½‰…­ÕÁÌˆ¤(€€€‘•˜…‘µ¥¹}‰…­ÕÁÍ}É•…Ñ•}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É¡İÉ¥Ñ”õQÉÕ”°Á•Éµ¥ÍÍ¥½¸ô‰‰…­ÕÀ¹µ…¹…”ˆ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€‘…Ñ„°½‘”€ôÉ•…Ñ•}…‘µ¥¹}‰…­ÕÀ¡…ÁÀ¹½¹™¥l‰Q}%1‰t¤(€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” ‰‰…­ÕÀ¹É•…Ñ”ˆ°‘…Ñ„°½‘”¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…‘µ¥¸½‰…­ÕÁÌ½ÈÈˆ¤(€€€‘•˜…‘µ¥¹}ÈÉ}‰…­ÕÁ}É•…Ñ•}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É¡İÉ¥Ñ”õQÉÕ”¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€‘…Ñ„°½‘”€ôÉ•…Ñ•}ÈÉ}•¹ÉåÁÑ•‘}‰…­ÕÀ¡…ÁÀ¹½¹™¥œ¤(€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” ‰‰…­ÕÀ¹ÈÈ¹É•…Ñ”ˆ°‘…Ñ„°½‘”¤((€€€…ÁÀ¹•Ğ ˆ½…Á¤½…‘µ¥¸½‰…­ÕÁÌ¼ñ‰…­ÕÁ}¥øˆ¤(€€€‘•˜…‘µ¥¹}‰…­ÕÁÍ}‘½İ¹±½…‘}…Á¤¡‰…­ÕÁ}¥¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€‘…Ñ„°½‘”€ôÉ•…‘}…‘µ¥¹}‰…­ÕÀ¡…ÁÀ¹½¹™¥l‰Q}%1‰t°‰…­ÕÁ}¥¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…‘µ¥¸½ÍÕÁÁ½ÉĞµÉ•Á±äˆ¤(€€€‘•˜…‘µ¥¹}ÍÕÁÁ½ÉÑ}É•Á±å}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É¡İÉ¥Ñ”õQÉÕ”°Á•Éµ¥ÍÍ¥½¸ô‰ÍÕÁÁ½ÉĞ¹µ…¹…”ˆ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€‘…Ñ„°½‘”€ô…‘µ¥¹}É•Á±å}ÍÕÁÁ½ÉÑ}Ñ¥­•Ğ¡…ÁÀ¹½¹™¥l‰Q}%1‰t°É•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô°…ÁÀ¹½¹™¥œ¤(€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” ‰ÍÕÁÁ½ÉĞ¹É•Á±äˆ°‘…Ñ„°½‘”¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…‘µ¥¸½Í•¹µÉ•µ¥¹‘•ÉÌˆ¤(€€€‘•˜Í•¹‘}É•µ¥¹‘•ÉÍ}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É¡İÉ¥Ñ”õQÉÕ”°Á•Éµ¥ÍÍ¥½¸ô‰¹½Ñ¥™¥…Ñ¥½¸¹µ…¹…”ˆ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€‘…Ñ„°½‘”€ôÍ•¹‘}‘Õ•}É•µ¥¹‘•ÉÌ¡…ÁÀ¹½¹™¥œ¤(€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” ‰É•µ¥¹‘•È¹Í•¹ˆ°‘…Ñ„°½‘”¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…‘µ¥¸½Í•¹µ½¹Ñ…ĞµÉ•µ¥¹‘•ÉÌˆ¤(€€€‘•˜Í•¹‘}½¹Ñ…Ñ}É•µ¥¹‘•ÉÍ}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É¡İÉ¥Ñ”õQÉÕ”°Á•Éµ¥ÍÍ¥½¸ô‰¹½Ñ¥™¥…Ñ¥½¸¹µ…¹…”ˆ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€‘…Ñ„°½‘”€ôÍ•¹‘}µ¥ÍÍ¥¹}½¹Ñ…Ñ}É•µ¥¹‘•ÉÌ¡…ÁÀ¹½¹™¥œ¤(€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” ‰½¹Ñ…Ñ}É•µ¥¹‘•È¹Í•¹ˆ°‘…Ñ„°½‘”¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…‘µ¥¸½Í•¹µÉ•¹•İ…°µÉ•µ¥¹‘•ÉÌˆ¤(€€€‘•˜Í•¹‘}É•¹•İ…±}É•µ¥¹‘•ÉÍ}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É¡İÉ¥Ñ”õQÉÕ”°Á•Éµ¥ÍÍ¥½¸ô‰¹½Ñ¥™¥…Ñ¥½¸¹µ…¹…”ˆ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€‘…Ñ„°½‘”€ôÍ•¹‘}É•¹•İ…±}É•µ¥¹‘•ÉÌ¡…ÁÀ¹½¹™¥œ¤(€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” ‰É•¹•İ…±}É•µ¥¹‘•È¹Í•¹ˆ°‘…Ñ„°½‘”¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…‘µ¥¸½Í•¹µ‰¥ÉÑ¡‘…äµÉ•µ¥¹‘•ÉÌˆ¤(€€€‘•˜Í•¹‘}‰¥ÉÑ¡‘…å}É•µ¥¹‘•ÉÍ}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É¡İÉ¥Ñ”õQÉÕ”°Á•Éµ¥ÍÍ¥½¸ô‰¹½Ñ¥™¥…Ñ¥½¸¹µ…¹…”ˆ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€‘…Ñ„°½‘”€ôÍ•¹‘}‰¥ÉÑ¡‘…å}É•µ¥¹‘•ÉÌ¡…ÁÀ¹½¹™¥œ¤(€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” ‰‰¥ÉÑ¡‘…å}É•µ¥¹‘•È¹Í•¹ˆ°‘…Ñ„°½‘”¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…‘µ¥¸½Á…åµ•¹ÑÌ½½¹™¥É´ˆ¤(€€€‘•˜…‘µ¥¹}Á…åµ•¹Ñ}½¹™¥Éµ}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É¡İÉ¥Ñ”õQÉÕ”°Á•Éµ¥ÍÍ¥½¸ô‰½É‘•È¹µ…¹…”ˆ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€‘…Ñ„°½‘”€ô½¹™¥Éµ}Á…åµ•¹Ñ}½É‘•È¡…ÁÀ¹½¹™¥l‰Q}%1‰t°É•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô°…ÁÀ¹½¹™¥œ¤(€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” ‰Á…åµ•¹Ğ¹½¹™¥É´ˆ°‘…Ñ„°½‘”¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…‘µ¥¸½Á…åµ•¹ÑÌ½É•™Õ¹ˆ¤(€€€‘•˜…‘µ¥¹}Á…åµ•¹Ñ}É•™Õ¹‘}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É¡İÉ¥Ñ”õQÉÕ”¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€Á…å±½…‘l‰É•ÅÕ•ÍÑ•‘}‰ä‰t€ô€‰…‘µ¥¹}Í•ÍÍ¥½¸ˆ(€€€€€€€‘…Ñ„°½‘”€ôÉ•™Õ¹‘}Á…åµ•¹Ñ}½É‘•È (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…°…ÁÀ¹½¹™¥œ(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” ‰Á…åµ•¹Ğ¹É•™Õ¹ˆ°‘…Ñ„°½‘”¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½É½¸½Ñ¥¬ˆ¤(€€€‘•˜É½¹}Ñ¥­}…Á¤ ¤è(€€€€€€€Í•É•Ğ€ôÉ•ÅÕ•ÍĞ¹¡•…‘•ÉÌ¹•Ğ ‰`µÉ½¸µM•É•Ğˆ°€ˆˆ¤(€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡…ÁÀ¹½¹™¥œ°Í•É•Ğ¤è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô¤°€ĞÀÄ(€€€€€€€‘…Ñ„°½‘”€ôÉÕ¹}É½¹}Ñ¥¬¡…ÁÀ¹½¹™¥œ¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹É½ÕÑ” ˆ½…Á¤½É½¸½½¹Ñ…ĞµÉ•µ¥¹‘•ÉÌˆ°µ•Ñ¡½‘Ìõl‰Pˆ°€‰A=MP‰t¤(€€€‘•˜É½¹}½¹Ñ…Ñ}É•µ¥¹‘•ÉÍ}…Á¤ ¤è(€€€€€€€Í•É•Ğ€ôÉ•ÅÕ•ÍĞ¹¡•…‘•ÉÌ¹•Ğ ‰`µÉ½¸µM•É•Ğˆ°€ˆˆ¤(€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡…ÁÀ¹½¹™¥œ°Í•É•Ğ¤è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô¤°€ĞÀÄ(€€€€€€€‘…Ñ„°½‘”€ôÍ•¹‘}µ¥ÍÍ¥¹}½¹Ñ…Ñ}É•µ¥¹‘•ÉÌ¡…ÁÀ¹½¹™¥œ¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹É½ÕÑ” ˆ½…Á¤½É½¸½¡•­¥¸µÉ•µ¥¹‘•ÉÌˆ°µ•Ñ¡½‘Ìõl‰Pˆ°€‰A=MP‰t¤(€€€‘•˜É½¹}¡•­¥¹}É•µ¥¹‘•ÉÍ}…Á¤ ¤è(€€€€€€€Í•É•Ğ€ôÉ•ÅÕ•ÍĞ¹¡•…‘•ÉÌ¹•Ğ ‰`µÉ½¸µM•É•Ğˆ°€ˆˆ¤(€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡…ÁÀ¹½¹™¥œ°Í•É•Ğ¤è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô¤°€ĞÀÄ(€€€€€€€€Œ€ıµ½‘”õ‰É½…‘…ÍĞƒš"X™½É”ôÄƒŠHƒ¦7šZÃš:£šJ·Ö›–£¦£–ŞË¢¢ï–+šr–N‡¾ò#–B¯’î+š^—–ŞËÂ÷–"Ã¾ò$(€€€€€€€µ½‘”€ôÍÑÈ¡É•ÅÕ•ÍĞ¹…ÉÌ¹•Ğ ‰µ½‘”ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤¹±½İ•È ¤(€€€€€€€™½É”€ôÍÑÈ¡É•ÅÕ•ÍĞ¹…ÉÌ¹•Ğ ‰™½É”ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤¹±½İ•È ¤¥¸ìˆÄˆ°€‰ÑÉÕ”ˆ°€‰å•Ìˆ°€‰½¸‰ô(€€€€€€€¥˜µ½‘”¥¸ì‰‰É½…‘…ÍĞˆ°€‰É•ÁÕÍ ˆ°€‰…±°‰ô½È™½É”è(€€€€€€€€€€€‘…Ñ„°½‘”€ô‰É½…‘…ÍÑ}¡•­¥¹}É•µ¥¹‘•ÉÌ¡…ÁÀ¹½¹™¥œ¤(€€€€€€€•±Í”è(€€€€€€€€€€€‘…Ñ„°½‘”€ôÍ•¹‘}¡•­¥¹}É•µ¥¹‘•ÉÌ¡…ÁÀ¹½¹™¥œ¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹É½ÕÑ” ˆ½…Á¤½É½¸½¡•­¥¸µ‰É½…‘…ÍĞˆ°µ•Ñ¡½‘Ìõl‰Pˆ°€‰A=MP‰t¤(€€€‘•˜É½¹}¡•­¥¹}‰É½…‘…ÍÑ}…Á¤ ¤è(€€€€€€€€ˆˆ‹¦7šZÃš:£šJ·–Â#R£¾òk–Â7šr$±¥¹•}ÕÍ•É}¥ƒjšr–N‡¦šZÃ&#š¾?š^—–æÏ–º$±•ãˆˆˆ(€€€€€€€Í•É•Ğ€ôÉ•ÅÕ•ÍĞ¹¡•…‘•ÉÌ¹•Ğ ‰`µÉ½¸µM•É•Ğˆ°€ˆˆ¤(€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡…ÁÀ¹½¹™¥œ°Í•É•Ğ¤è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô¤°€ĞÀÄ(€€€€€€€‘…Ñ„°½‘”€ô‰É½…‘…ÍÑ}¡•­¥¹}É•µ¥¹‘•ÉÌ¡…ÁÀ¹½¹™¥œ¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹É½ÕÑ” ˆ½…Á¤½É½¸½½Ù•É‘Õ”µ…±•ÉÑÌˆ°µ•Ñ¡½‘Ìõl‰Pˆ°€‰A=MP‰t¤(€€€‘•˜É½¹}½Ù•É‘Õ•}…±•ÉÑÍ}…Á¤ ¤è(€€€€€€€Í•É•Ğ€ôÉ•ÅÕ•ÍĞ¹¡•…‘•ÉÌ¹•Ğ ‰`µÉ½¸µM•É•Ğˆ°€ˆˆ¤(€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡…ÁÀ¹½¹™¥œ°Í•É•Ğ¤è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô¤°€ĞÀÄ(€€€€€€€‘…Ñ„°½‘”€ôÍ•¹‘}‘Õ•}É•µ¥¹‘•ÉÌ¡…ÁÀ¹½¹™¥œ¤(€€€€€€€‘…¥±ä°}‘…¥±å}½‘”€ôÍ•¹‘}Õ…É‘¥…¹}É½ÕÁ}‘…¥±å}ÍÕµµ…É¥•Ì¡…ÁÀ¹½¹™¥œ¤(€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡‘…Ñ„°‘¥Ğ¤è(€€€€€€€€€€€‘…Ñ„€ô‘¥Ğ¡‘…Ñ„¤(€€€€€€€€€€€‘…Ñ…l‰‘…¥±å}É½ÕÁ}ÍÕµµ…Éä‰t€ô‘…¥±ä(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹É½ÕÑ” ˆ½…Á¤½É½¸½É•¹•İ…°µÉ•µ¥¹‘•ÉÌˆ°µ•Ñ¡½‘Ìõl‰Pˆ°€‰A=MP‰t¤(€€€‘•˜É½¹}É•¹•İ…±}É•µ¥¹‘•ÉÍ}…Á¤ ¤è(€€€€€€€Í•É•Ğ€ôÉ•ÅÕ•ÍĞ¹¡•…‘•ÉÌ¹•Ğ ‰`µÉ½¸µM•É•Ğˆ°€ˆˆ¤(€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡…ÁÀ¹½¹™¥œ°Í•É•Ğ¤è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô¤°€ĞÀÄ(€€€€€€€‘…Ñ„°½‘”€ôÍ•¹‘}É•¹•İ…±}É•µ¥¹‘•ÉÌ¡…ÁÀ¹½¹™¥œ¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹É½ÕÑ” ˆ½…Á¤½É½¸½‰¥ÉÑ¡‘…äµÉ•µ¥¹‘•ÉÌˆ°µ•Ñ¡½‘Ìõl‰Pˆ°€‰A=MP‰t¤(€€€‘•˜É½¹}‰¥ÉÑ¡‘…å}É•µ¥¹‘•ÉÍ}…Á¤ ¤è(€€€€€€€Í•É•Ğ€ôÉ•ÅÕ•ÍĞ¹¡•…‘•ÉÌ¹•Ğ ‰`µÉ½¸µM•É•Ğˆ°€ˆˆ¤(€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡…ÁÀ¹½¹™¥œ°Í•É•Ğ¤è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô¤°€ĞÀÄ(€€€€€€€‘…Ñ„°½‘”€ôÍ•¹‘}‰¥ÉÑ¡‘…å}É•µ¥¹‘•ÉÌ¡…ÁÀ¹½¹™¥œ¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹É½ÕÑ” ˆ½…Á¤½É½¸½Íµ…ÉĞµÉ•µ¥¹‘•ÉÌˆ°µ•Ñ¡½‘Ìõl‰Pˆ°€‰A=MP‰t¤(€€€‘•˜É½¹}Íµ…ÉÑ}É•µ¥¹‘•ÉÍ}…Á¤ ¤è(€€€€€€€Í•É•Ğ€ôÉ•ÅÕ•ÍĞ¹¡•…‘•ÉÌ¹•Ğ ‰`µÉ½¸µM•É•Ğˆ°€ˆˆ¤(€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡…ÁÀ¹½¹™¥œ°Í•É•Ğ¤è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô¤°€ĞÀÄ(€€€€€€€‘…Ñ„°½‘”€ôÍ•¹‘}Íµ…ÉÑ}É•µ¥¹‘•ÉÌ¡…ÁÀ¹½¹™¥œ¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹•Ğ ˆ½…Á¤½Íµ…ÉĞµÉ•µ¥¹‘•ÉÌˆ¤(€€€‘•˜Íµ…ÉÑ}É•µ¥¹‘•ÉÍ}•Ğ ¤è(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡íô°ÕÍ•}…ÉÌõQÉÕ”¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•Ñ}Íµ…ÉÑ}É•µ¥¹‘•ÉÍ}Á…å±½…¡…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥¤¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½Íµ…ÉĞµÉ•µ¥¹‘•ÉÌˆ¤(€€€‘•˜Íµ…ÉÑ}É•µ¥¹‘•ÉÍ}Á½ÍĞ ¤è(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€‘…Ñ„°½‘”€ôÍ…Ù•}Íµ…ÉÑ}É•µ¥¹‘•È¡…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹‘•±•Ñ” ˆ½…Á¤½Íµ…ÉĞµÉ•µ¥¹‘•ÉÌ¼ñÉ•µ¥¹‘•É}¥øˆ¤(€€€‘•˜Íµ…ÉÑ}É•µ¥¹‘•ÉÍ}‘•±•Ñ”¡É•µ¥¹‘•É}¥¤è(€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡íô°ÕÍ•}…ÉÌõQÉÕ”¤(€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€Œ±Í¼…•ÁĞ)M=8‰½‘ä™½È±¥•¹ÑÌÑ¡…ĞÍ•¹±¥¹•}ÕÍ•É}¥Ñ¡•É”(€€€€€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô}…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…¤(€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡•ÉÉlÁt¤°•ÉÉlÅt(€€€€€€€‘…Ñ„°½‘”€ô‘•±•Ñ•}Íµ…ÉÑ}É•µ¥¹‘•È¡…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥°É•µ¥¹‘•É}¥¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹É½ÕÑ” ˆ½…Á¤½É½¸½µ•µ‰•ÉÍ¡¥Àµ•áÁ¥Éäˆ°µ•Ñ¡½‘Ìõl‰Pˆ°€‰A=MP‰t¤(€€€‘•˜É½¹}µ•µ‰•ÉÍ¡¥Á}•áÁ¥Éå}…Á¤ ¤è(€€€€€€€Í•É•Ğ€ôÉ•ÅÕ•ÍĞ¹¡•…‘•ÉÌ¹•Ğ ‰`µÉ½¸µM•É•Ğˆ°€ˆˆ¤(€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡…ÁÀ¹½¹™¥œ°Í•É•Ğ¤è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô¤°€ĞÀÄ(€€€€€€€‘…Ñ„°½‘”€ô…ÁÁ±å}•áÁ¥É•‘}Á±…¹}‘½İ¹É…‘•Ì¡…ÁÀ¹½¹™¥œ¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹É½ÕÑ” ˆ½…Á¤½É½¸½‘…Ñ„µ±•…¹ÕÀˆ°µ•Ñ¡½‘Ìõl‰Pˆ°€‰A=MP‰t¤(€€€‘•˜É½¹}‘…Ñ…}±•…¹ÕÁ}…Á¤ ¤è(€€€€€€€Í•É•Ğ€ôÉ•ÅÕ•ÍĞ¹¡•…‘•ÉÌ¹•Ğ ‰`µÉ½¸µM•É•Ğˆ°€ˆˆ¤(€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡…ÁÀ¹½¹™¥œ°Í•É•Ğ¤è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô¤°€ĞÀÄ(€€€€€€€‘…Ñ„°½‘”€ô±•…¹ÕÁ}•áÁ¥É•‘}‘…Ñ„¡…ÁÀ¹½¹™¥œ¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹É½ÕÑ” ˆ½…Á¤½É½¸½‰…­™¥±°µ‰¥¹µ¹½Ñ¥™äˆ°µ•Ñ¡½‘Ìõl‰Pˆ°€‰A=MP‰t¤(€€€‘•˜É½¹}‰…­™¥±±}‰¥¹‘}¹½Ñ¥™å}…Á¤ ¤è(€€€€€€€€ˆˆ‰=¹”µÍ¡½Ğèƒ¢sfóš¶ß–>Ë–ŞËÚ–ºk¦ngšZçjÚ–ºkš"C–*|1%9¾ò#–«¶$‰¥¹‘}¹½Ñ¥™å}Í•¹Ñ}…Ó¾ò'ˆˆˆ(€€€€€€€Í•É•Ğ€ôÉ•ÅÕ•ÍĞ¹¡•…‘•ÉÌ¹•Ğ ‰`µÉ½¸µM•É•Ğˆ°€ˆˆ¤(€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡…ÁÀ¹½¹™¥œ°Í•É•Ğ¤è(€€€€€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô¤°€ĞÀÄ(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€‘Éå}ÉÕ¸€ôÍÑÈ (€€€€€€€€€€€É•ÅÕ•ÍĞ¹…ÉÌ¹•Ğ ‰‘Éå}ÉÕ¸ˆ¤(€€€€€€€€€€€½ÈÁ…å±½…¹•Ğ ‰‘Éå}ÉÕ¸ˆ¤(€€€€€€€€€€€½È€ˆˆ(€€€€€€€€¤¹ÍÑÉ¥À ¤¹±½İ•È ¤¥¸ìˆÄˆ°€‰ÑÉÕ”ˆ°€‰å•Ìˆ°€‰½¸‰ô(€€€€€€€ÑÉäè(€€€€€€€€€€€±¥µ¥Ğ€ô¥¹Ğ¡É•ÅÕ•ÍĞ¹…ÉÌ¹•Ğ ‰±¥µ¥Ğˆ¤½ÈÁ…å±½…¹•Ğ ‰±¥µ¥Ğˆ¤½È€À¤(€€€€€€€•á•ÁĞ€¡QåÁ•ÉÉ½È°Y…±Õ•ÉÉ½È¤è(€€€€€€€€€€€±¥µ¥Ğ€ô€À(€€€€€€€‘…Ñ„°½‘”€ô‰…­™¥±±}‰¥¹‘}¹½Ñ¥™ä¡…ÁÀ¹½¹™¥œ°‘Éå}ÉÕ¸õ‘Éå}ÉÕ¸°±¥µ¥Ğõ±¥µ¥Ğ¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹•Ğ ˆ½…Á¤½…‘µ¥¸½É¥ µµ•¹Ôˆ¤(€€€‘•˜…‘µ¥¹}É¥¡}µ•¹Õ}¥¹ÍÁ•Ñ}…Á¤ ¤è(€€€€€€€€ˆˆ‹š~—¢¦‹n»–&7¦‚C¢¢·–r[šZ¦ã–Z»¾ò#–B¯’â¦6×¦
¢®,UI'¾ò'’â7–n{–
ÌÑ½­•»ˆˆˆ(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€‘…Ñ„°½‘”€ô¥¹ÍÁ•Ñ}‘•™…Õ±Ñ}É¥¡}µ•¹Ô¡…ÁÀ¹½¹™¥œ¤(€€€€€€€É•ÑÕÉ¸©Í½¹¥™ä¡‘…Ñ„¤°½‘”((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…‘µ¥¸½É¥ µµ•¹Ô½‘•Á±½äˆ¤(€€€‘•˜…‘µ¥¹}É¥¡}µ•¹Õ}‘•Á±½å}…Á¤ ¤è(€€€€€€€€ˆˆ‹R I•¹‘•Èƒ’â+j1%9}!991}MM}Q=-8ƒ’â+–
Ï’â›¢¢·
ë¦‚C¢¢·–r[šZ¦ã–Z»ˆˆˆ(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É¡İÉ¥Ñ”õQÉÕ”°Á•Éµ¥ÍÍ¥½¸ô‰ÍåÍÑ•´¹µ…¹…”ˆ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€‘…Ñ„°½‘”€ô‘•Á±½å}‘•™…Õ±Ñ}É¥¡}µ•¹Ô¡…ÁÀ¹½¹™¥œ¤(€€€€€€€¥˜‘…Ñ„¹•Ğ ‰½¬ˆ¤è(€€€€€€€€€€€…ÁÀ¹±½•È¹¥¹™¼ (€€€€€€€€€€€€€€€€‰É¥ µ•¹Ô‘•Á±½å•É¥¡5•¹Õ%ô•Ì¹…µ”ô•Ìˆ°(€€€€€€€€€€€€€€€‘…Ñ„¹•Ğ ‰É¥¡5•¹Õ%ˆ¤°(€€€€€€€€€€€€€€€‘…Ñ„¹•Ğ ‰¹…µ”ˆ¤°(€€€€€€€€€€€€¤(€€€€€€€•±Í”è(€€€€€€€€€€€…ÁÀ¹±½•È¹İ…É¹¥¹œ (€€€€€€€€€€€€€€€€‰É¥ µ•¹Ô‘•Á±½ä™…¥±•ÍÑ•Àô•Ì¡ÑÑÀô•Ìˆ°(€€€€€€€€€€€€€€€‘…Ñ„¹•Ğ ‰ÍÑ•Àˆ¤°(€€€€€€€€€€€€€€€‘…Ñ„¹•Ğ ‰¡ÑÑÀˆ¤°(€€€€€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” ‰É¥¡}µ•¹Ô¹‘•Á±½äˆ°‘…Ñ„°½‘”¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…‘µ¥¸½ÁÕÍ µİ•±½µ”ˆ¤(€€€‘•˜…‘µ¥¹}ÁÕÍ¡}İ•±½µ•}…Á¤ ¤è(€€€€€€€€ˆˆ‹º‡B–N‡¢sš:£š¶‡¢ş8±•ã¾ò#¦r–ŞË–*ƒ––÷–>/¾ò'	‰½‘äèí±¥¹•}ÕÍ•É}¥°‘¥ÍÁ±…å}¹…µ”ıôˆˆˆ(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É¡İÉ¥Ñ”õQÉÕ”°Á•Éµ¥ÍÍ¥½¸ô‰¹½Ñ¥™¥…Ñ¥½¸¹µ…¹…”ˆ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€¥˜1¥¹•	½ÑÁ¤¥Ì9½¹”½È±•áM•¹‘5•ÍÍ…”¥Ì9½¹”½Èİ•±½µ•}™±•à¥Ì9½¹”è(€€€€€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” (€€€€€€€€€€€€€€€€‰İ•±½µ”¹ÁÕÍ ˆ°(€€€€€€€€€€€€€€€ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰±¥¹”Í‘¬½Èİ•±½µ•}™±•àÕ¹…Ù…¥±…‰±”‰ô°(€€€€€€€€€€€€€€€€ÔÀÌ°(€€€€€€€€€€€€¤(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€±¥¹•}ÕÍ•É}¥€ôÍÑÈ¡Á…å±½…¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤(€€€€€€€¥˜¹½Ğ±¥¹•}ÕÍ•É}¥è(€€€€€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” (€€€€€€€€€€€€€€€€‰İ•±½µ”¹ÁÕÍ ˆ°(€€€€€€€€€€€€€€€ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰µ¥ÍÍ¥¹œ±¥¹•}ÕÍ•É}¥‰ô°(€€€€€€€€€€€€€€€€ĞÀÀ°(€€€€€€€€€€€€¤(€€€€€€€Ñ½­•¸€ô€ (€€€€€€€€€€€…ÁÀ¹½¹™¥œ¹•Ğ ‰1%9}!991}MM}Q=-8ˆ¤(€€€€€€€€€€€½È½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}!991}MM}Q=-8ˆ¤(€€€€€€€€€€€½È€ˆˆ(€€€€€€€€¤¹ÍÑÉ¥À ¤(€€€€€€€¥˜¹½ĞÑ½­•¸è(€€€€€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” (€€€€€€€€€€€€€€€€‰İ•±½µ”¹ÁÕÍ ˆ°(€€€€€€€€€€€€€€€ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰1%9}!991}MM}Q=-8¹½ĞÍ•Ğ‰ô°(€€€€€€€€€€€€€€€€ÔÀÌ°(€€€€€€€€€€€€¤(€€€€€€€±¥¹•}‰½Ñ}…Á¤€ô1¥¹•	½ÑÁ¤¡Ñ½­•¸¤(€€€€€€€¡¥¹Ğ€ôÍÑÈ¡Á…å±½…¹•Ğ ‰‘¥ÍÁ±…å}¹…µ”ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤½È9½¹”(€€€€€€€É•Í½±Ù•€ôÉ•Í½±Ù•}İ•±½µ•}‘¥ÍÁ±…å}¹…µ” (€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤õ±¥¹•}‰½Ñ}…Á¤°(€€€€€€€€€€€‘…Ñ…}™¥±”õ…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥õ±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€¡¥¹Ğõ¡¥¹Ğ°(€€€€€€€€€€€±½•Èõ…ÁÀ¹±½•È°(€€€€€€€€¤(€€€€€€€ÑÉäè(€€€€€€€€€€€É•¥ÍÑ•É}±¥¹•}ÕÍ•È (€€€€€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€ì‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°€‰‘¥ÍÁ±…å}¹…µ”ˆèÉ•Í½±Ù•½È€‰1%9ƒ’öÿR£¢‰ô°(€€€€€€€€€€€€¤(€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€…ÁÀ¹±½•È¹İ…É¹¥¹œ ‰…‘µ¥¸ÁÕÍ µİ•±½µ”É•¥ÍÑ•È™…¥±•è€•Ìˆ°•áŒ¤(€€€€€€€½¹Ñ•¹ÑÌ€ôİ•±½µ•}™±•à¡É•Í½±Ù•¤(€€€€€€€É••Ñ¥¹œ€ô€ (€€€€€€€€€€€İ•±½µ•}É••Ñ¥¹}Ñ•áĞ¡É•Í½±Ù•¤(€€€€€€€€€€€¥˜İ•±½µ•}É••Ñ¥¹}Ñ•áĞ¥Ì¹½Ğ9½¹”(€€€€€€€€€€€•±Í”€¡˜‹Â~F,íÉ•Í½±Ù•‘ôƒš
£––÷¾ò3š¶‡¢ş;–*ƒ–—3š¾?š^—–æÏ–º'4ˆ¥˜É•Í½±Ù••±Í”€‹Â~F,ƒš
£––÷¾ò3š¶‡¢ş;–*ƒ–—3š¾?š^—–æÏ–º'4ˆ¤(€€€€€€€€¤(€€€€€€€…±Ñ}Ñ•áĞ€ô€ (€€€€€€€€€€€˜‹š¾?š^—–æÏ–º'¾öqíÉ•Í½±Ù•‘ôƒš
£––÷¾ò3š¶‡¢ş;–*ƒ–”ˆ(€€€€€€€€€€€¥˜É•Í½±Ù•(€€€€€€€€€€€•±Í”€‹š¾?š^—–æÏ–º'¾ösš
£––÷¾ò3š¶‡¢ş;–*ƒ–”ˆ(€€€€€€€€¤(€€€€€€€ÑÉäè(€€€€€€€€€€€±¥¹•}‰½Ñ}…Á¤¹ÁÕÍ¡}µ•ÍÍ…” (€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€±•áM•¹‘5•ÍÍ…”¡…±Ñ}Ñ•áĞõ…±Ñ}Ñ•áĞ°½¹Ñ•¹ÑÌõ½¹Ñ•¹ÑÌ¤°(€€€€€€€€€€€€¤(€€€€€€€€€€€…ÁÀ¹±½•È¹¥¹™¼ (€€€€€€€€€€€€€€€€‰…‘µ¥¸ÁÕÍ µİ•±½µ”½¬ÕÍ•Èô•Ì¹…µ”ô•Èˆ°(€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥‘lèát°(€€€€€€€€€€€€€€€É•Í½±Ù•½È€ˆˆ°(€€€€€€€€€€€€¤(€€€€€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” (€€€€€€€€€€€€€€€€‰İ•±½µ”¹ÁÕÍ ˆ°(€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€‰½¬ˆèQÉÕ”°(€€€€€€€€€€€€€€€€€€€€‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€€€€€€‰‘¥ÍÁ±…å}¹…µ”ˆèÉ•Í½±Ù•°(€€€€€€€€€€€€€€€€€€€€‰É••Ñ¥¹œˆèÉ••Ñ¥¹œ°(€€€€€€€€€€€€€€€ô°(€€€€€€€€€€€€¤(€€€€€€€•á•ÁĞ1¥¹•	½ÑÁ¥ÉÉ½È…Ì•áŒè(€€€€€€€€€€€‘•Ñ…¥°€ôÍÑÈ¡•áŒ¤(€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€‘•Ñ…¥°€ô•Ñ…ÑÑÈ¡•áŒ°€‰•ÉÉ½Èˆ°9½¹”¤½È‘•Ñ…¥°(€€€€€€€€€€€•á•ÁĞá•ÁÑ¥½¸è(€€€€€€€€€€€€€€€Á…ÍÌ(€€€€€€€€€€€…ÁÀ¹±½•È¹•á•ÁÑ¥½¸ ‰…‘µ¥¸ÁÕÍ µİ•±½µ”1%9•ÉÉ½Èè€•Ìˆ°‘•Ñ…¥°¤(€€€€€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” (€€€€€€€€€€€€€€€€‰İ•±½µ”¹ÁÕÍ ˆ°(€€€€€€€€€€€€€€€ì‰½¬ˆè…±Í”°€‰•ÉÉ½Èˆè€‰±¥¹•}…Á¥}•ÉÉ½Èˆ°€‰‘•Ñ…¥°ˆèÍÑÈ¡‘•Ñ…¥°¥ô°(€€€€€€€€€€€€€€€€ÔÀÈ°(€€€€€€€€€€€€¤(€€€€€€€•á•ÁĞá•ÁÑ¥½¸…Ì•áŒè(€€€€€€€€€€€…ÁÀ¹±½•È¹•á•ÁÑ¥½¸ ‰…‘µ¥¸ÁÕÍ µİ•±½µ”™…¥±•è€•Ìˆ°•áŒ¤(€€€€€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” (€€€€€€€€€€€€€€€€‰İ•±½µ”¹ÁÕÍ ˆ°(€€€€€€€€€€€€€€€ì‰½¬ˆè…±Í”°€‰•ÉÉ½ÈˆèÍÑÈ¡•áŒ¥ô°(€€€€€€€€€€€€€€€€ÔÀÀ°(€€€€€€€€€€€€¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…‘µ¥¸½ÕÍ•ÈµÁ±…¸ˆ¤(€€€‘•˜…‘µ¥¹}ÕÍ•É}Á±…¹}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É¡İÉ¥Ñ”õQÉÕ”°Á•Éµ¥ÍÍ¥½¸ô‰µ•µ‰•È¹µ…¹…”ˆ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€‘…Ñ„°½‘”€ô…‘µ¥¹}ÕÁ‘…Ñ•}ÕÍ•É}Á±…¸¡…ÁÀ¹½¹™¥l‰Q}%1‰t°É•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô¤(€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” ‰ÕÍ•É}Á±…¸¹ÕÁ‘…Ñ”ˆ°‘…Ñ„°½‘”¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…‘µ¥¸½Í•Ğµ½É”µÕ…É‘¥…¸ˆ¤(€€€‘•˜…‘µ¥¹}Í•Ñ}½É•}Õ…É‘¥…¹}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É¡İÉ¥Ñ”õQÉÕ”°Á•Éµ¥ÍÍ¥½¸ô‰µ•µ‰•È¹µ…¹…”ˆ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€‘…Ñ„°½‘”€ô…‘µ¥¹}Í•Ñ}½É•}Õ…É‘¥…¸¡…ÁÀ¹½¹™¥l‰Q}%1‰t°É•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô¤(€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” ‰½É•}Õ…É‘¥…¸¹Í•Ğˆ°‘…Ñ„°½‘”¤((€€€…ÁÀ¹Á½ÍĞ ˆ½…Á¤½…‘µ¥¸½¥¹¥‘•¹ÑÌ½É•Í½±Ù”ˆ¤(€€€‘•˜…‘µ¥¹}¥¹¥‘•¹Ñ}É•Í½±Ù•}…Á¤ ¤è(€€€€€€€‘•¹¥•€ô}…‘µ¥¹}Õ…É¡İÉ¥Ñ”õQÉÕ”°Á•Éµ¥ÍÍ¥½¸ô‰¥¹¥‘•¹Ğ¹µ…¹…”ˆ¤(€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€É•ÑÕÉ¸‘•¹¥•(€€€€€€€Á…å±½…€ôÉ•ÅÕ•ÍĞ¹•Ñ}©Í½¸¡Í¥±•¹ĞõQÉÕ”¤½Èíô(€€€€€€€‘…Ñ„°½‘”€ôÉ•Í½±Ù•}…‘µ¥¹}¥¹¥‘•¹Ğ (€€€€€€€€€€€…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€Á…å±½…°(€€€€€€€€€€€Í•ÍÍ¥½¸¹•Ğ ‰…‘µ¥¹}É½±”ˆ¤°(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸}…‘µ¥¹}µÕÑ…Ñ¥½¹}É•ÍÁ½¹Í” (€€€€€€€€€€€€‰¥¹¥‘•¹Ğ¹É•Í½±Ù”ˆ°(€€€€€€€€€€€‘…Ñ„°(€€€€€€€€€€€½‘”°(€€€€€€€€¤((€€€É•ÑÕÉ¸…ÁÀ(()±…ÍÌ5¥¹¥I•ÍÁ½¹Í”è(€€€‘•˜}}¥¹¥Ñ}|¡Í•±˜°‘…Ñ„°ÍÑ…ÑÕÍ}½‘”ôÈÀÀ°¡•…‘•ÉÌõ9½¹”¤è(€€€€€€€Í•±˜¹}‘…Ñ„€ô‘…Ñ„(€€€€€€€Í•±˜¹ÍÑ…ÑÕÍ}½‘”€ôÍÑ…ÑÕÍ}½‘”(€€€€€€€Í•±˜¹¡•…‘•ÉÌ€ô¡•…‘•ÉÌ½Èíô((€€€‘•˜•Ñ}©Í½¸¡Í•±˜¤è(€€€€€€€É•ÑÕÉ¸Í•±˜¹}‘…Ñ„((€€€‘•˜±½Í”¡Í•±˜¤è(€€€€€€€É•ÑÕÉ¸9½¹”((€€€‘•˜•Ñ}‘…Ñ„¡Í•±˜°…Í}Ñ•áĞõ…±Í”¤è(€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡Í•±˜¹}‘…Ñ„°‰åÑ•Ì¤è(€€€€€€€€€€€É•ÑÕÉ¸Í•±˜¹}‘…Ñ„¹‘•½‘” ‰ÕÑ˜´àˆ¤¥˜…Í}Ñ•áĞ•±Í”Í•±˜¹}‘…Ñ„(€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡Í•±˜¹}‘…Ñ„°ÍÑÈ¤è(€€€€€€€€€€€É•ÑÕÉ¸Í•±˜¹}‘…Ñ„¥˜…Í}Ñ•áĞ•±Í”Í•±˜¹}‘…Ñ„¹•¹½‘” ‰ÕÑ˜´àˆ¤(€€€€€€€É•¹‘•É•€ô©Í½¸¹‘ÕµÁÌ¡Í•±˜¹}‘…Ñ„°•¹ÍÕÉ•}…Í¥¤õ…±Í”¤(€€€€€€€É•ÑÕÉ¸É•¹‘•É•¥˜…Í}Ñ•áĞ•±Í”É•¹‘•É•¹•¹½‘” ‰ÕÑ˜´àˆ¤(()±…ÍÌ5¥¹¥±¥•¹Ğè(€€€‘•˜}}¥¹¥Ñ}|¡Í•±˜°…ÁÀ¤è(€€€€€€€Í•±˜¹…ÁÀ€ô…ÁÀ((€€€‘•˜•Ğ¡Í•±˜°Á…Ñ °¡•…‘•ÉÌõ9½¹”¤è(€€€€€€€É½ÕÑ”°|°ÅÕ•Éä€ôÁ…Ñ ¹Á…ÉÑ¥Ñ¥½¸ ˆüˆ¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…‘µ¥¸ˆ½ÈÉ½ÕÑ”¹ÍÑ…ÉÑÍİ¥Ñ  ˆ½…Á¤½…‘µ¥¸¼ˆ¤è(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰•ÉÉ½Èˆè€‰…‘µ¥¹}¹½Ñ}½¹™¥ÕÉ•‰ô°€ÔÀÌ¤(€€€€€€€Á…É…µÌ€ô‘¥Ğ¡ÕÉ±±¥ˆ¹Á…ÉÍ”¹Á…ÉÍ•}ÅÍ°¡ÅÕ•Éä¤¤(€€€€€€€¡•…‘•ÉÌ€ô¡•…‘•ÉÌ½Èíô(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½½¹™¥œˆè(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡…ÁÁ}½¹™¥œ¡Í•±˜¹…ÁÀ¹½¹™¥œ¤¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½¡•…±Ñ ˆè(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰½¬ˆèQÉÕ•ô¤(€€€€€€€¥˜É½ÕÑ”¥¸€ ˆ½É½‰½ÑÌ¹ÑáĞˆ°€ˆ½Í¥Ñ•µ…À¹áµ°ˆ¤è(€€€€€€€€€€€™¥±•¹…µ”€ôÉ½ÕÑ”¹±ÍÑÉ¥À ˆ¼ˆ¤(€€€€€€€€€€€Á…Ñ¡}½‰¨€ôA…Ñ ¡}}™¥±•}|¤¹É•Í½±Ù” ¤¹Á…É•¹Ğ€¼™¥±•¹…µ”(€€€€€€€€€€€¥˜Á…Ñ¡}½‰¨¹•á¥ÍÑÌ ¤è(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡Á…Ñ¡}½‰¨¹É•…‘}Ñ•áĞ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰•ÉÉ½Èˆè€‰¹½Ğ™½Õ¹‰ô°€ĞÀĞ¤(€€€€€€€¥˜É½ÕÑ”¥¸€ ˆ½Ñ•ÉµÌˆ°€ˆ½ÁÉ¥Ù…äˆ¤è(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰½¬ˆèQÉÕ•ô¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½±¥™˜½µ¥É…Ñ”¹¡Ñµ°ˆè(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰½¬ˆèQÉÕ•ô¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½±¥™˜½½¹‰½…É‘¥¹œˆè(€€€€€€€€€€€±¥™™}¥€ôÍÑÈ¡Í•±˜¹…ÁÀ¹½¹™¥œ¹•Ğ ‰1%}%ˆ¤½ÈU1Q}1%}%¤¹ÍÑÉ¥À ¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í” (€€€€€€€€€€€€€€€ì‰½¬ˆèQÉÕ•ô°(€€€€€€€€€€€€€€€€ÌÀÈ°(€€€€€€€€€€€€€€€ì‰1½…Ñ¥½¸ˆè˜‰¡ÑÑÁÌè¼½±¥™˜¹±¥¹”¹µ”½í±¥™™}¥‘ôı½Á•¸õ½¹‰½…É‘¥¹œ‰ô°(€€€€€€€€€€€€¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½ÍÑ…ÑÕÌˆè(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È (€€€€€€€€€€€€€€€íô°…ÉÌõÁ…É…µÌ°¡•…‘•ÉÌõ¡•…‘•ÉÌ°½¹™¥œõÍ•±˜¹…ÁÀ¹½¹™¥œ(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€‰½‘ä°½‘”€ôÍÑ…ÑÕÍ}™½É}ÕÍ•È (€€€€€€€€€€€€€€€Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€Á…É…µÌ¹•Ğ ‰‘¥ÍÁ±…å}¹…µ”ˆ¤°(€€€€€€€€€€€€¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½½¹‰½…É‘¥¹œˆè(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È (€€€€€€€€€€€€€€€íô°…ÉÌõÁ…É…µÌ°¡•…‘•ÉÌõ¡•…‘•ÉÌ°½¹™¥œõÍ•±˜¹…ÁÀ¹½¹™¥œ(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€‰½‘ä°½‘”€ô½¹‰½…É‘¥¹}ÍÑ…ÑÕÍ}Á…å±½… (€€€€€€€€€€€€€€€Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥(€€€€€€€€€€€€¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½½¹‰½…É‘¥¹œ½ÍÑ…Ñ”ˆè(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È (€€€€€€€€€€€€€€€íô°…ÉÌõÁ…É…µÌ°¡•…‘•ÉÌõ¡•…‘•ÉÌ°½¹™¥œõÍ•±˜¹…ÁÀ¹½¹™¥œ(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€‰½‘ä°½‘”€ô½¹‰½…É‘¥¹}ÍÑ…ÑÕÍ}Á…å±½… (€€€€€€€€€€€€€€€Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€…±±½İ}µ¥ÍÍ¥¹}ÁÉ½™¥±”õQÉÕ”°(€€€€€€€€€€€€¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½Õ…É‘¥…¸µÉ½ÕÁÌ½Í•ÑÑ¥¹Ìˆè(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È (€€€€€€€€€€€€€€€íô°…ÉÌõÁ…É…µÌ°¡•…‘•ÉÌõ¡•…‘•ÉÌ°½¹™¥œõÍ•±˜¹…ÁÀ¹½¹™¥œ(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€‰½‘ä°½‘”€ôÕ…É‘¥…¹}É½ÕÁ}Í•ÑÑ¥¹Í}™½É}ÕÍ•È (€€€€€€€€€€€€€€€Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥(€€€€€€€€€€€€¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…‘µ¥¸½ÍÕµµ…Éäˆè(€€€€€€€€€€€‘•¹¥•€ô…‘µ¥¹}…ÕÑ¡}•ÉÉ½É}Á…å±½…¡Í•±˜¹…ÁÀ¹½¹™¥œ°Á…É…µÌ¹•Ğ ‰Á…ÍÍİ½Éˆ°€ˆˆ¤¤(€€€€€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€€€€€Á…å±½…°½‘”€ô‘•¹¥•(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡Á…å±½…°½‘”¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡…‘µ¥¹}ÍÕµµ…Éä¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Í•±˜¹…ÁÀ¹½¹™¥œ¤¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…‘µ¥¸½ÍÕÁÁ½ÉĞµÑ¥­•ÑÌˆè(€€€€€€€€€€€¥˜¹½Ğ…‘µ¥¹}…±±½İ•¡Í•±˜¹…ÁÀ¹½¹™¥œ°Á…É…µÌ¹•Ğ ‰Á…ÍÍİ½Éˆ°€ˆˆ¤¤è(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡…‘µ¥¹}ÍÕÁÁ½ÉÑ}Ñ¥­•ÑÌ¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t¤¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½ÍÕÁÁ½ÉĞ½Ñ¥­•ÑÌˆè(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È (€€€€€€€€€€€€€€€íô°…ÉÌõÁ…É…µÌ°¡•…‘•ÉÌõ¡•…‘•ÉÌ°½¹™¥œõÍ•±˜¹…ÁÀ¹½¹™¥œ(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€‰½‘ä°½‘”€ôµ•µ‰•É}ÍÕÁÁ½ÉÑ}Ñ¥­•ÑÌ (€€€€€€€€€€€€€€€Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥(€€€€€€€€€€€€¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…‘µ¥¸½‰…­ÕÁÌˆè(€€€€€€€€€€€¥˜¹½Ğ…‘µ¥¹}…±±½İ•¡Í•±˜¹…ÁÀ¹½¹™¥œ°Á…É…µÌ¹•Ğ ‰Á…ÍÍİ½Éˆ°€ˆˆ¤¤è(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡±¥ÍÑ}…‘µ¥¹}‰…­ÕÁÌ¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t¤¤(€€€€€€€¥˜É½ÕÑ”¹ÍÑ…ÉÑÍİ¥Ñ  ˆ½…Á¤½…‘µ¥¸½‰…­ÕÁÌ¼ˆ¤è(€€€€€€€€€€€¥˜¹½Ğ…‘µ¥¹}…±±½İ•¡Í•±˜¹…ÁÀ¹½¹™¥œ°Á…É…µÌ¹•Ğ ‰Á…ÍÍİ½Éˆ°€ˆˆ¤¤è(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€‰…­ÕÁ}¥€ôÉ½ÕÑ”¹ÉÍÁ±¥Ğ ˆ¼ˆ°€Ä¥l´Åt(€€€€€€€€€€€‰½‘ä°½‘”€ôÉ•…‘}…‘µ¥¹}‰…­ÕÀ¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°‰…­ÕÁ}¥¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½½¹Ñ…ÑÌˆè(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡•Ñ}½¹Ñ…ÑÌ¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…É…µÌ¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤¤¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½•µ•É•¹äµ½¹Ñ…Ğ½¥¹Ù¥Ñ”µÁÉ•Ù¥•Üˆè(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È (€€€€€€€€€€€€€€€íô°…ÉÌõÁ…É…µÌ°¡•…‘•ÉÌõ¡•…‘•ÉÌ°½¹™¥œõÍ•±˜¹…ÁÀ¹½¹™¥œ(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€‰½‘ä°½‘”€ô¥¹Ù¥Ñ•}‰¥¹‘}ÁÉ•Ù¥•Ü (€€€€€€€€€€€€€€€Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€‰¥¹Ù¥Ñ•}™É½´ˆèÁ…É…µÌ¹•Ğ ‰¥¹Ù¥Ñ•}™É½´ˆ¤½ÈÁ…É…µÌ¹•Ğ ‰™É½´ˆ¤½È€ˆˆ°(€€€€€€€€€€€€€€€€€€€€‰¥¹Ù¥Ñ•}Ñ½­•¸ˆèÁ…É…µÌ¹•Ğ ‰¥¹Ù¥Ñ•}Ñ½­•¸ˆ¤½È€ˆˆ°(€€€€€€€€€€€€€€€€€€€€‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€ô°(€€€€€€€€€€€€¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…±•¹‘…Èµ¹½Ñ•Ìˆè(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È (€€€€€€€€€€€€€€€íô°…ÉÌõÁ…É…µÌ°¡•…‘•ÉÌõ¡•…‘•ÉÌ°½¹™¥œõÍ•±˜¹…ÁÀ¹½¹™¥œ(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€‰½‘ä€ô•Ñ}…±•¹‘…É}¹½Ñ•Ì¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°€ÈÀÀ¥˜‰½‘ä¹•Ğ ‰½¬ˆ¤•±Í”€ĞÀÌ¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½Íµ…ÉĞµÉ•µ¥¹‘•ÉÌˆè(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È (€€€€€€€€€€€€€€€íô°…ÉÌõÁ…É…µÌ°¡•…‘•ÉÌõ¡•…‘•ÉÌ°½¹™¥œõÍ•±˜¹…ÁÀ¹½¹™¥œ(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í” (€€€€€€€€€€€€€€€•Ñ}Íµ…ÉÑ}É•µ¥¹‘•ÉÍ}Á…å±½… (€€€€€€€€€€€€€€€€€€€Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½™É¥•¹‘Ì½±½…Ñ¥½¹Ìˆè(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡™É¥•¹‘}±½…Ñ¥½¹Ì¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…É…µÌ¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤¤¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½±½…Ñ¥½¸½ÍÑ…ÑÕÌˆè(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥€ôÁ…É…µÌ¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤(€€€€€€€€€€€¥˜¹½Ğ±¥¹•}ÕÍ•É}¥è(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰•ÉÉ½Èˆè€‰µ¥ÍÍ¥¹œ±¥¹•}ÕÍ•É}¥‰ô°€ĞÀÀ¤(€€€€€€€€€€€ÁÉ½™¥±”€ô•Ñ}ÁÉ½™¥±”¡±½…‘}ÍÑ…Ñ”¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t¤°±¥¹•}ÕÍ•É}¥¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰½¬ˆèQÉÕ”°€‰Í…™•Ñå}Õ…ÉˆèÍ…™•Ñå}Õ…É‘}Í¹…ÁÍ¡½Ğ¡ÁÉ½™¥±”¥ô¤(€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰•ÉÉ½Èˆè€‰¹½Ğ™½Õ¹‰ô°€ĞÀĞ¤((€€€‘•˜Á½ÍĞ¡Í•±˜°Á…Ñ °‘…Ñ„õ9½¹”°½¹Ñ•¹Ñ}ÑåÁ”õ9½¹”°¡•…‘•ÉÌõ9½¹”°€¨©­İ…ÉÌ¤è(€€€€€€€É½ÕÑ”°|°ÅÕ•Éä€ôÁ…Ñ ¹Á…ÉÑ¥Ñ¥½¸ ˆüˆ¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…‘µ¥¸ˆ½ÈÉ½ÕÑ”¹ÍÑ…ÉÑÍİ¥Ñ  ˆ½…Á¤½…‘µ¥¸¼ˆ¤è(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰•ÉÉ½Èˆè€‰…‘µ¥¹}¹½Ñ}½¹™¥ÕÉ•‰ô°€ÔÀÌ¤(€€€€€€€Á…É…µÌ€ô‘¥Ğ¡ÕÉ±±¥ˆ¹Á…ÉÍ”¹Á…ÉÍ•}ÅÍ°¡ÅÕ•Éä¤¤(€€€€€€€¡•…‘•ÉÌ€ô¡•…‘•ÉÌ½Èíô(€€€€€€€É½¹}Í•É•Ğ€ô€ (€€€€€€€€€€€¡•…‘•ÉÌ¹•Ğ ‰`µÉ½¸µM•É•Ğˆ¤(€€€€€€€€€€€½È¡•…‘•ÉÌ¹•Ğ ‰àµÉ½¸µÍ•É•Ğˆ¤(€€€€€€€€€€€½È€ˆˆ(€€€€€€€€¤(€€€€€€€Á…å±½…€ôíô(€€€€€€€©Í½¹}Á…å±½…€ô­İ…ÉÌ¹•Ğ ‰©Í½¸ˆ¤(€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡©Í½¹}Á…å±½…°‘¥Ğ¤è(€€€€€€€€€€€Á…å±½…€ô‘¥Ğ¡©Í½¹}Á…å±½…¤(€€€€€€€•±¥˜‘…Ñ„…¹½¹Ñ•¹Ñ}ÑåÁ”€ôô€‰…ÁÁ±¥…Ñ¥½¸½©Í½¸ˆè(€€€€€€€€€€€Á…å±½…€ô©Í½¸¹±½…‘Ì¡‘…Ñ„¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½±¥¹”½É•¥ÍÑ•Èˆè(€€€€€€€€€€€‰½‘ä°½‘”€ôÉ•¥ÍÑ•É}±¥¹•}ÕÍ•È¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½¡•­¥¸ˆè(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È (€€€€€€€€€€€€€€€Á…å±½…°…ÉÌõÁ…É…µÌ°¡•…‘•ÉÌõ¡•…‘•ÉÌ°½¹™¥œõÍ•±˜¹…ÁÀ¹½¹™¥œ(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€É•ÍÕ±Ğ°½‘”€ô¡•­¥¹}™½É}ÕÍ•È (€€€€€€€€€€€€€€€Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥°Á…å±½…°Í•±˜¹…ÁÀ¹½¹™¥œ(€€€€€€€€€€€€¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡É•ÍÕ±Ğ°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½½¹‰½…É‘¥¹œ½É•µ¥¹‘•Èˆè(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È (€€€€€€€€€€€€€€€Á…å±½…°…ÉÌõÁ…É…µÌ°¡•…‘•ÉÌõ¡•…‘•ÉÌ°½¹™¥œõÍ•±˜¹…ÁÀ¹½¹™¥œ(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€É•ÍÕ±Ğ°½‘”€ôÕÁ‘…Ñ•}½¹‰½…É‘¥¹}É•µ¥¹‘•È (€€€€€€€€€€€€€€€Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥°Á…å±½…(€€€€€€€€€€€€¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡É•ÍÕ±Ğ°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½½¹‰½…É‘¥¹œ½½µÁ±•Ñ”ˆè(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È (€€€€€€€€€€€€€€€Á…å±½…°…ÉÌõÁ…É…µÌ°¡•…‘•ÉÌõ¡•…‘•ÉÌ°½¹™¥œõÍ•±˜¹…ÁÀ¹½¹™¥œ(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€É•ÍÕ±Ğ°½‘”€ô½µÁ±•Ñ•}½¹‰½…É‘¥¹}™½É}ÕÍ•È (€€€€€€€€€€€€€€€Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥°Á…å±½…(€€€€€€€€€€€€¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡É•ÍÕ±Ğ°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½İ…É¹¥¹œ½…¹•°ˆè(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡…¹•±}İ…É¹¥¹œ¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…°Í•±˜¹…ÁÀ¹½¹™¥œ¤¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½Í•ÑÑ¥¹Ìˆè(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡Í…Ù•}Í•ÑÑ¥¹Í}™½É}ÁÉ½™¥±”¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½‰¥±±¥¹œ½ÁÉ•™•É•¹•Ìˆè(€€€€€€€€€€€‰½‘ä°½‘”€ôÍ…Ù•}‰¥±±¥¹}ÁÉ•™•É•¹•Ì¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½Á…åµ•¹ÑÌ½½É‘•ÉÌˆè(€€€€€€€€€€€‰½‘ä°½‘”€ôÉ•…Ñ•}Á…åµ•¹Ñ}½É‘•È¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…°Í•±˜¹…ÁÀ¹½¹™¥œ¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”¥¸ìˆ½…Á¤½Á…åµ•¹Ğ½•Á…ä½¹½Ñ¥™äˆ°€ˆ½…Á¤½Á…åµ•¹Ğ½•Á…ä½Á•É¥½µ¹½Ñ¥™ä‰ôè(€€€€€€€€€€€™½É´€ô‘¥Ğ¡‘…Ñ„¤¥˜¥Í¥¹ÍÑ…¹”¡‘…Ñ„°‘¥Ğ¤•±Í”Á…å±½…(€€€€€€€€€€€¥˜•Á…ä¥Ì9½¹”è(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í” ˆÁñÁ…åµ•¹Ğµ½‘Õ±”µ¥ÍÍ¥¹œˆ°€ÔÀÌ¤(€€€€€€€€€€€Á…ÉÍ•°•ÉÉ½È€ô•Á…ä¹Á…ÉÍ•}¹½Ñ¥™å}Á…å±½…¡™½É´°Í•±˜¹…ÁÀ¹½¹™¥œ¤(€€€€€€€€€€€¥˜•ÉÉ½Èè(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡˜ˆÁñí•ÉÉ½Éôˆ°€ĞÀÀ¤(€€€€€€€€€€€¥˜¹½Ğ•Á…ä¹¹½Ñ¥™å}ÍÕ•ÍÌ¡Á…ÉÍ•°Í•±˜¹…ÁÀ¹½¹™¥œ¤è(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í” ˆÅñ=,ˆ°€ÈÀÀ¤(€€€€€€€€€€€¥˜É½ÕÑ”¹•¹‘Íİ¥Ñ  ˆ½Á•É¥½µ¹½Ñ¥™äˆ¤è(€€€€€€€€€€€€€€€Á…ÉÍ•¹ÕÁ‘…Ñ”¡ì‰ÍÑ…ÑÕÌˆè€‰MUMLˆ°€‰ÁÉ½Ù¥‘•Èˆè€‰•Á…ä‰ô¤(€€€€€€€€€€€€€€€‰½‘ä°½‘”€ôÁÉ½•ÍÍ}Á•É¥½‘}¹½Ñ¥™¥…Ñ¥½¸ (€€€€€€€€€€€€€€€€€€€Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…ÉÍ•°Í•±˜¹…ÁÀ¹½¹™¥œ(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€‰½‘ä°½‘”€ô½¹™¥Éµ}Á…åµ•¹Ñ}½É‘•È (€€€€€€€€€€€€€€€€€€€Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°(€€€€€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€€€€€‰½É‘•É}¥ˆèÁ…ÉÍ•¹•Ğ ‰½É‘•É}¥ˆ¤°(€€€€€€€€€€€€€€€€€€€€€€€€‰ÑÉ…¹Í…Ñ¥½¹}¥ˆèÁ…ÉÍ•¹•Ğ ‰ÑÉ…¹Í…Ñ¥½¹}¥ˆ¤°(€€€€€€€€€€€€€€€€€€€€€€€€‰…µ½Õ¹ĞˆèÁ…ÉÍ•¹•Ğ ‰…µ½Õ¹Ğˆ¤°(€€€€€€€€€€€€€€€€€€€€€€€€‰ÁÉ½Ù¥‘•Èˆè€‰•Á…äˆ°(€€€€€€€€€€€€€€€€€€€ô°(€€€€€€€€€€€€€€€€€€€Í•±˜¹…ÁÀ¹½¹™¥œ°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜½‘”€øô€ĞÀÀè(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í” (€€€€€€€€€€€€€€€€€€€˜ˆÁñí‰½‘ä¹•Ğ •ÉÉ½Èœ°€½É‘•ÈÕÁ‘…Ñ”™…¥±•œ¥ôˆ°½‘”(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í” ˆÅñ=,ˆ°€ÈÀÀ¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½½¹Ñ…ÑÌˆè(€€€€€€€€€€€‰½‘ä°½‘”€ôÍ…Ù•}½¹Ñ…ÑÌ¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…±•¹‘…Èµ¹½Ñ•Ìˆè(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È (€€€€€€€€€€€€€€€Á…å±½…°…ÉÌõÁ…É…µÌ°¡•…‘•ÉÌõ¡•…‘•ÉÌ°½¹™¥œõÍ•±˜¹…ÁÀ¹½¹™¥œ(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€€€€€‰½‘ä°½‘”€ôÍ…Ù•}…±•¹‘…É}¹½Ñ”¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½Íµ…ÉĞµÉ•µ¥¹‘•ÉÌˆè(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È (€€€€€€€€€€€€€€€Á…å±½…°…ÉÌõÁ…É…µÌ°¡•…‘•ÉÌõ¡•…‘•ÉÌ°½¹™¥œõÍ•±˜¹…ÁÀ¹½¹™¥œ(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€€€€€‰½‘ä°½‘”€ôÍ…Ù•}Íµ…ÉÑ}É•µ¥¹‘•È¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”¥¸ìˆ½…Á¤½É½¸½Íµ…ÉĞµÉ•µ¥¹‘•ÉÌˆ°€ˆ½…Á¤½É½¸½‰¥ÉÑ¡‘…äµÉ•µ¥¹‘•ÉÌ‰ôè(€€€€€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡Í•±˜¹…ÁÀ¹½¹™¥œ°É½¹}Í•É•Ğ¤è(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€Ñ…Í¬€ô€ (€€€€€€€€€€€€€€€Í•¹‘}Íµ…ÉÑ}É•µ¥¹‘•ÉÌ(€€€€€€€€€€€€€€€¥˜É½ÕÑ”¹•¹‘Íİ¥Ñ  ‰Íµ…ÉĞµÉ•µ¥¹‘•ÉÌˆ¤(€€€€€€€€€€€€€€€•±Í”Í•¹‘}‰¥ÉÑ¡‘…å}É•µ¥¹‘•ÉÌ(€€€€€€€€€€€€¤(€€€€€€€€€€€‰½‘ä°½‘”€ôÑ…Í¬¡Í•±˜¹…ÁÀ¹½¹™¥œ¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½•µ•É•¹äµ½¹Ñ…Ğ½‰¥¹ˆè(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È¡Á…å±½…°…ÉÌõÁ…É…µÌ°¡•…‘•ÉÌõ¡•…‘•ÉÌ°½¹™¥œõÍ•±˜¹…ÁÀ¹½¹™¥œ¤(€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€Á…å±½…‘l‰½¹Ñ…Ñ}±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€€€€€‰½‘ä°½‘”€ô‰¥¹‘}•µ•É•¹å}½¹Ñ…Ğ¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…°Í•±˜¹…ÁÀ¹½¹™¥œ¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½•µ•É•¹äµ½¹Ñ…Ğ½¥¹Ù¥Ñ”ˆè(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È (€€€€€€€€€€€€€€€Á…å±½…°…ÉÌõÁ…É…µÌ°¡•…‘•ÉÌõ¡•…‘•ÉÌ°½¹™¥œõÍ•±˜¹…ÁÀ¹½¹™¥œ(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€‰½‘ä°½‘”€ôÉ•…Ñ•}Õ…É‘¥…¹}¥¹Ù¥Ñ” (€€€€€€€€€€€€€€€Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥°Á…å±½…(€€€€€€€€€€€€¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½Õ…É‘¥…¸µÉ½ÕÁÌ½‰¥¹ˆè(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È (€€€€€€€€€€€€€€€Á…å±½…°…ÉÌõÁ…É…µÌ°¡•…‘•ÉÌõ¡•…‘•ÉÌ°½¹™¥œõÍ•±˜¹…ÁÀ¹½¹™¥œ(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€€€€€‰½‘ä°½‘”€ô‰¥¹‘}Õ…É‘¥…¹}É½ÕÀ¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½Õ…É‘¥…¸µÉ½ÕÁÌ½ÁÉ•™•É•¹•Ìˆè(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È (€€€€€€€€€€€€€€€Á…å±½…°…ÉÌõÁ…É…µÌ°¡•…‘•ÉÌõ¡•…‘•ÉÌ°½¹™¥œõÍ•±˜¹…ÁÀ¹½¹™¥œ(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€€€€€‰½‘ä°½‘”€ôÕÁ‘…Ñ•}Õ…É‘¥…¹}É½ÕÁ}ÁÉ•™•É•¹•Ì (€€€€€€€€€€€€€€€Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…(€€€€€€€€€€€€¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½Õ…É‘¥…¸µÉ½ÕÁÌ½Õ¹‰¥¹ˆè(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È (€€€€€€€€€€€€€€€Á…å±½…°…ÉÌõÁ…É…µÌ°¡•…‘•ÉÌõ¡•…‘•ÉÌ°½¹™¥œõÍ•±˜¹…ÁÀ¹½¹™¥œ(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€€€€€‰½‘ä°½‘”€ôÕ¹‰¥¹‘}Õ…É‘¥…¹}É½ÕÀ¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½™É¥•¹‘Ì½¥¹Ù¥Ñ”ˆè(€€€€€€€€€€€‰½‘ä°½‘”€ôÉ•…Ñ•}™É¥•¹‘}¥¹Ù¥Ñ”¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½™É¥•¹‘Ì½…•ÁĞˆè(€€€€€€€€€€€‰½‘ä°½‘”€ô…•ÁÑ}™É¥•¹‘}¥¹Ù¥Ñ”¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½±½…Ñ¥½¸½ÕÁ‘…Ñ”ˆè(€€€€€€€€€€€‰½‘ä°½‘”€ôÕÁ‘…Ñ•}±½…Ñ¥½¸¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…°Í•±˜¹…ÁÀ¹½¹™¥œ¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½±½…Ñ¥½¸½ÍÑ½Àˆè(€€€€€€€€€€€‰½‘ä°½‘”€ôÍÑ½Á}±½…Ñ¥½¹}Í¡…É¥¹œ¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½Í½Ìˆè(€€€€€€€€€€€‰½‘ä°½‘”€ôÑÉ¥•É}Í½Ì¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…°Í•±˜¹…ÁÀ¹½¹™¥œ¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½Í½Ì½…¹•°ˆè(€€€€€€€€€€€‰½‘ä°½‘”€ô…¹•±}Í½Í}•Ù•¹Ğ¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…°Í•±˜¹…ÁÀ¹½¹™¥œ¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½Í½Ì½É•ÑÉäˆè(€€€€€€€€€€€‰½‘ä°½‘”€ôÉ•ÑÉå}Í½Í}•Ù•¹Ğ¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…°Í•±˜¹…ÁÀ¹½¹™¥œ¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…½Õ¹Ğ½‘•±•Ñ”ˆè(€€€€€€€€€€€‰½‘ä°½‘”€ô‘•±•Ñ•}…½Õ¹Ğ¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…½Õ¹Ğ½•áÁ½ÉĞˆè(€€€€€€€€€€€‰½‘ä°½‘”€ô•áÁ½ÉÑ}…½Õ¹Ñ}‘…Ñ„¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…½Õ¹Ğ½¡¥ÍÑ½Éä½‘•±•Ñ”ˆè(€€€€€€€€€€€‰½‘ä°½‘”€ô‘•±•Ñ•}Á•ÉÍ½¹…±}¡¥ÍÑ½Éä¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…‘µ¥¸½Í•¹µÉ•µ¥¹‘•ÉÌˆè(€€€€€€€€€€€¥˜¹½Ğ…‘µ¥¹}…±±½İ•¡Í•±˜¹…ÁÀ¹½¹™¥œ°Á…É…µÌ¹•Ğ ‰Á…ÍÍİ½Éˆ°€ˆˆ¤¤è(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€‰½‘ä°½‘”€ôÍ•¹‘}‘Õ•}É•µ¥¹‘•ÉÌ¡Í•±˜¹…ÁÀ¹½¹™¥œ¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…‘µ¥¸½Í•¹µ½¹Ñ…ĞµÉ•µ¥¹‘•ÉÌˆè(€€€€€€€€€€€¥˜¹½Ğ…‘µ¥¹}…±±½İ•¡Í•±˜¹…ÁÀ¹½¹™¥œ°Á…É…µÌ¹•Ğ ‰Á…ÍÍİ½Éˆ°€ˆˆ¤¤è(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€‰½‘ä°½‘”€ôÍ•¹‘}µ¥ÍÍ¥¹}½¹Ñ…Ñ}É•µ¥¹‘•ÉÌ¡Í•±˜¹…ÁÀ¹½¹™¥œ¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…‘µ¥¸½Í•¹µÉ•¹•İ…°µÉ•µ¥¹‘•ÉÌˆè(€€€€€€€€€€€¥˜¹½Ğ…‘µ¥¹}…±±½İ•¡Í•±˜¹…ÁÀ¹½¹™¥œ°Á…É…µÌ¹•Ğ ‰Á…ÍÍİ½Éˆ°€ˆˆ¤¤è(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€‰½‘ä°½‘”€ôÍ•¹‘}É•¹•İ…±}É•µ¥¹‘•ÉÌ¡Í•±˜¹…ÁÀ¹½¹™¥œ¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…‘µ¥¸½Á…åµ•¹ÑÌ½½¹™¥É´ˆè(€€€€€€€€€€€¥˜¹½Ğ…‘µ¥¹}…±±½İ•¡Í•±˜¹…ÁÀ¹½¹™¥œ°Á…É…µÌ¹•Ğ ‰Á…ÍÍİ½Éˆ°€ˆˆ¤¤è(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€‰½‘ä°½‘”€ô½¹™¥Éµ}Á…åµ•¹Ñ}½É‘•È¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…°Í•±˜¹…ÁÀ¹½¹™¥œ¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…‘µ¥¸½‰…­ÕÁÌˆè(€€€€€€€€€€€¥˜¹½Ğ…‘µ¥¹}…±±½İ•¡Í•±˜¹…ÁÀ¹½¹™¥œ°Á…É…µÌ¹•Ğ ‰Á…ÍÍİ½Éˆ°€ˆˆ¤¤è(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€‰½‘ä°½‘”€ôÉ•…Ñ•}…‘µ¥¹}‰…­ÕÀ¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½É½¸½Ñ¥¬ˆè(€€€€€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡Í•±˜¹…ÁÀ¹½¹™¥œ°É½¹}Í•É•Ğ¤è(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€‰½‘ä°½‘”€ôÉÕ¹}É½¹}Ñ¥¬¡Í•±˜¹…ÁÀ¹½¹™¥œ¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½É½¸½½¹Ñ…ĞµÉ•µ¥¹‘•ÉÌˆè(€€€€€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡Í•±˜¹…ÁÀ¹½¹™¥œ°É½¹}Í•É•Ğ¤è(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€‰½‘ä°½‘”€ôÍ•¹‘}µ¥ÍÍ¥¹}½¹Ñ…Ñ}É•µ¥¹‘•ÉÌ¡Í•±˜¹…ÁÀ¹½¹™¥œ¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½É½¸½¡•­¥¸µÉ•µ¥¹‘•ÉÌˆè(€€€€€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡Í•±˜¹…ÁÀ¹½¹™¥œ°É½¹}Í•É•Ğ¤è(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€µ½‘”€ôÍÑÈ¡Á…É…µÌ¹•Ğ ‰µ½‘”ˆ°€ˆˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤¹±½İ•È ¤(€€€€€€€€€€€™½É”€ôÍÑÈ¡Á…É…µÌ¹•Ğ ‰™½É”ˆ°€ˆˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤¹±½İ•È ¤¥¸ìˆÄˆ°€‰ÑÉÕ”ˆ°€‰å•Ìˆ°€‰½¸‰ô(€€€€€€€€€€€¥˜µ½‘”¥¸ì‰‰É½…‘…ÍĞˆ°€‰É•ÁÕÍ ˆ°€‰…±°‰ô½È™½É”è(€€€€€€€€€€€€€€€‰½‘ä°½‘”€ô‰É½…‘…ÍÑ}¡•­¥¹}É•µ¥¹‘•ÉÌ¡Í•±˜¹…ÁÀ¹½¹™¥œ¤(€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€‰½‘ä°½‘”€ôÍ•¹‘}¡•­¥¹}É•µ¥¹‘•ÉÌ¡Í•±˜¹…ÁÀ¹½¹™¥œ¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½É½¸½¡•­¥¸µ‰É½…‘…ÍĞˆè(€€€€€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡Í•±˜¹…ÁÀ¹½¹™¥œ°É½¹}Í•É•Ğ¤è(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€‰½‘ä°½‘”€ô‰É½…‘…ÍÑ}¡•­¥¹}É•µ¥¹‘•ÉÌ¡Í•±˜¹…ÁÀ¹½¹™¥œ¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½É½¸½É•¹•İ…°µÉ•µ¥¹‘•ÉÌˆè(€€€€€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡Í•±˜¹…ÁÀ¹½¹™¥œ°É½¹}Í•É•Ğ¤è(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€‰½‘ä°½‘”€ôÍ•¹‘}É•¹•İ…±}É•µ¥¹‘•ÉÌ¡Í•±˜¹…ÁÀ¹½¹™¥œ¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½É½¸½‘…Ñ„µ±•…¹ÕÀˆè(€€€€€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡Í•±˜¹…ÁÀ¹½¹™¥œ°É½¹}Í•É•Ğ¤è(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€‰½‘ä°½‘”€ô±•…¹ÕÁ}•áÁ¥É•‘}‘…Ñ„¡Í•±˜¹…ÁÀ¹½¹™¥œ¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½É½¸½‰…­™¥±°µ‰¥¹µ¹½Ñ¥™äˆè(€€€€€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡Í•±˜¹…ÁÀ¹½¹™¥œ°É½¹}Í•É•Ğ¤è(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€‘Éå}ÉÕ¸€ôÍÑÈ¡Á…É…µÌ¹•Ğ ‰‘Éå}ÉÕ¸ˆ¤½ÈÁ…å±½…¹•Ğ ‰‘Éå}ÉÕ¸ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤¹±½İ•È ¤¥¸ì(€€€€€€€€€€€€€€€€ˆÄˆ°(€€€€€€€€€€€€€€€€‰ÑÉÕ”ˆ°(€€€€€€€€€€€€€€€€‰å•Ìˆ°(€€€€€€€€€€€€€€€€‰½¸ˆ°(€€€€€€€€€€€ô(€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€±¥µ¥Ğ€ô¥¹Ğ¡Á…É…µÌ¹•Ğ ‰±¥µ¥Ğˆ¤½ÈÁ…å±½…¹•Ğ ‰±¥µ¥Ğˆ¤½È€À¤(€€€€€€€€€€€•á•ÁĞ€¡QåÁ•ÉÉ½È°Y…±Õ•ÉÉ½È¤è(€€€€€€€€€€€€€€€±¥µ¥Ğ€ô€À(€€€€€€€€€€€‰½‘ä°½‘”€ô‰…­™¥±±}‰¥¹‘}¹½Ñ¥™ä¡Í•±˜¹…ÁÀ¹½¹™¥œ°‘Éå}ÉÕ¸õ‘Éå}ÉÕ¸°±¥µ¥Ğõ±¥µ¥Ğ¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…‘µ¥¸½ÕÍ•ÈµÁ±…¸ˆè(€€€€€€€€€€€¥˜¹½Ğ…‘µ¥¹}…±±½İ•¡Í•±˜¹…ÁÀ¹½¹™¥œ°Á…É…µÌ¹•Ğ ‰Á…ÍÍİ½Éˆ°€ˆˆ¤¤è(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€‰½‘ä°½‘”€ô…‘µ¥¹}ÕÁ‘…Ñ•}ÕÍ•É}Á±…¸¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…‘µ¥¸½Í•Ğµ½É”µÕ…É‘¥…¸ˆè(€€€€€€€€€€€¥˜¹½Ğ…‘µ¥¹}…±±½İ•¡Í•±˜¹…ÁÀ¹½¹™¥œ°Á…É…µÌ¹•Ğ ‰Á…ÍÍİ½Éˆ°€ˆˆ¤¤è(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€‰½‘ä°½‘”€ô…‘µ¥¹}Í•Ñ}½É•}Õ…É‘¥…¸¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…‘µ¥¸½ÍÕÁÁ½ÉĞµÉ•Á±äˆè(€€€€€€€€€€€¥˜¹½Ğ…‘µ¥¹}…±±½İ•¡Í•±˜¹…ÁÀ¹½¹™¥œ°Á…É…µÌ¹•Ğ ‰Á…ÍÍİ½Éˆ°€ˆˆ¤¤è(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€‰½‘ä°½‘”€ô…‘µ¥¹}É•Á±å}ÍÕÁÁ½ÉÑ}Ñ¥­•Ğ¡Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…°Í•±˜¹…ÁÀ¹½¹™¥œ¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½ÍÕÁÁ½ÉĞ½Ñ¥­•ÑÌˆè(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È (€€€€€€€€€€€€€€€Á…å±½…°…ÉÌõÁ…É…µÌ°¡•…‘•ÉÌõ¡•…‘•ÉÌ°½¹™¥œõÍ•±˜¹…ÁÀ¹½¹™¥œ(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€€€€€‰½‘ä°½‘”€ôÉ•…Ñ•}ÍÕÁÁ½ÉÑ}Ñ¥­•Ğ (€€€€€€€€€€€€€€€Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°Á…å±½…(€€€€€€€€€€€€¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰•ÉÉ½Èˆè€‰¹½Ğ™½Õ¹‰ô°€ĞÀĞ¤((€€€‘•˜‘•±•Ñ”¡Í•±˜°Á…Ñ °¡•…‘•ÉÌõ9½¹”¤è(€€€€€€€É½ÕÑ”°|°ÅÕ•Éä€ôÁ…Ñ ¹Á…ÉÑ¥Ñ¥½¸ ˆüˆ¤(€€€€€€€Á…É…µÌ€ô‘¥Ğ¡ÕÉ±±¥ˆ¹Á…ÉÍ”¹Á…ÉÍ•}ÅÍ°¡ÅÕ•Éä¤¤(€€€€€€€¡•…‘•ÉÌ€ô¡•…‘•ÉÌ½Èíô(€€€€€€€¥˜É½ÕÑ”¹ÍÑ…ÉÑÍİ¥Ñ  ˆ½…Á¤½Íµ…ÉĞµÉ•µ¥¹‘•ÉÌ¼ˆ¤è(€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È (€€€€€€€€€€€€€€€íô°…ÉÌõÁ…É…µÌ°¡•…‘•ÉÌõ¡•…‘•ÉÌ°½¹™¥œõÍ•±˜¹…ÁÀ¹½¹™¥œ(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€É•µ¥¹‘•É}¥€ôÉ½ÕÑ”¹ÉÍÁ±¥Ğ ˆ¼ˆ°€Ä¥l´Åt(€€€€€€€€€€€‰½‘ä°½‘”€ô‘•±•Ñ•}Íµ…ÉÑ}É•µ¥¹‘•È (€€€€€€€€€€€€€€€Í•±˜¹…ÁÀ¹½¹™¥l‰Q}%1‰t°±¥¹•}ÕÍ•É}¥°É•µ¥¹‘•É}¥(€€€€€€€€€€€€¤(€€€€€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡‰½‘ä°½‘”¤(€€€€€€€É•ÑÕÉ¸5¥¹¥I•ÍÁ½¹Í”¡ì‰•ÉÉ½Èˆè€‰¹½Ğ™½Õ¹‰ô°€ĞÀĞ¤(()±…ÍÌ5¥¹¥ÁÀè(€€€‘•˜}}¥¹¥Ñ}|¡Í•±˜°½¹™¥œõ9½¹”¤è(€€€€€€€Í•±˜¹½¹™¥œ€ôì(€€€€€€€€€€€€‰Q}%1ˆèÉ•Í½±Ù•}‘…Ñ…}™¥±”¡½Ì¹•¹Ù¥É½¸¹•Ğ ‰Q}%1ˆ¤¤°(€€€€€€€€€€€€‰5%9}AMM]=Iˆè½Ì¹•¹Ù¥É½¸¹•Ğ ‰5%9}AMM]=Iˆ°€ˆˆ¤°(€€€€€€€€€€€€‰5%9}MMM%=9}MIPˆè½Ì¹•¹Ù¥É½¸¹•Ğ ‰5%9}MMM%=9}MIPˆ°€ˆˆ¤°(€€€€€€€€€€€€‰11=]}=A9}5%8ˆè½Ì¹•¹Ù¥É½¸¹•Ğ ‰11=]}=A9}5%8ˆ°€ˆˆ¤°(€€€€€€€€€€€€‰5%9}=A8ˆè½Ì¹•¹Ù¥É½¸¹•Ğ ‰5%9}=A8ˆ°€ˆˆ¤°(€€€€€€€€€€€€‰1%9}!991}MM}Q=-8ˆè½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}!991}MM}Q=-8ˆ°€ˆˆ¤°(€€€€€€€€€€€€‰1%9}!991}MIPˆè½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}!991}MIPˆ°€ˆˆ¤°(€€€€€€€€€€€€‰1%}%ˆè½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%}%ˆ¤½ÈU1Q}1%}%°(€€€€€€€€€€€€‰1%9}1=%9}!991}%ˆè€ (€€€€€€€€€€€€€€€½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%9}1=%9}!991}%ˆ¤(€€€€€€€€€€€€€€€½È€¡½Ì¹•¹Ù¥É½¸¹•Ğ ‰1%}%ˆ¤½ÈU1Q}1%}%¤¹ÍÁ±¥Ğ ˆ´ˆ°€Ä¥lÁt(€€€€€€€€€€€€€€€½ÈU1Q}1%9}1=%9}!991}%(€€€€€€€€€€€€¤°(€€€€€€€€€€€€‰1e}1%9}1=%9}!991}%ˆè½Ì¹•¹Ù¥É½¸¹•Ğ (€€€€€€€€€€€€€€€€‰1e}1%9}1=%9}!991}%ˆ°€ˆÈÀÄÀØÜĞàÀÌˆ(€€€€€€€€€€€€¤°(€€€€€€€€€€€€‰1e}1%}%ˆè½Ì¹•¹Ù¥É½¸¹•Ğ ‰1e}1%}%ˆ°U1Q}1e}1%}%¤°(€€€€€€€€€€€€‰=U9Q}5%IQ%=9}MIPˆè½Ì¹•¹Ù¥É½¸¹•Ğ ‰=U9Q}5%IQ%=9}MIPˆ°€ˆˆ¤°(€€€€€€€€€€€€‰AA}AU	1%}UI0ˆè½Ì¹•¹Ù¥É½¸¹•Ğ ‰AA}AU	1%}UI0ˆ°€ˆˆ¤°(€€€€€€€€€€€€‰AA}Q%5i=9ˆè½Ì¹•¹Ù¥É½¸¹•Ğ ‰AA}Q%5i=9ˆ°€‰Í¥„½Q…¥Á•¤ˆ¤°(€€€€€€€€€€€€‰I=9}MIPˆè½Ì¹•¹Ù¥É½¸¹•Ğ ‰I=9}MIPˆ°€ˆˆ¤°(€€€€€€€ô(€€€€€€€¥˜½¹™¥œè(€€€€€€€€€€€Í•±˜¹½¹™¥œ¹ÕÁ‘…Ñ”¡½¹™¥œ¤((€€€‘•˜Ñ•ÍÑ}±¥•¹Ğ¡Í•±˜¤è(€€€€€€€É•ÑÕÉ¸5¥¹¥±¥•¹Ğ¡Í•±˜¤((€€€‘•˜ÍÑ…ÑÕÌ¡Í•±˜°±¥¹•}ÕÍ•É}¥õ9½¹”¤è(€€€€€€€ÍÑ…Ñ”€ô±½…‘}ÍÑ…Ñ”¡Í•±˜¹½¹™¥l‰Q}%1‰t¤(€€€€€€€É•ÑÕÉ¸‰Õ¥±‘}ÍÑ…ÑÕÌ¡•Ñ}ÁÉ½™¥±”¡ÍÑ…Ñ”°±¥¹•}ÕÍ•É}¥¤¤((€€€‘•˜ÉÕ¸¡Í•±˜°¡½ÍĞôˆÄÈÜ¸À¸À¸Äˆ°Á½ÉĞôÔÀÀÀ°‘•‰Õœõ…±Í”¤è(€€€€€€€‘…Ñ…}™¥±”€ôÍ•±˜¹½¹™¥l‰Q}%1‰t(€€€€€€€½¹™¥œ€ôÍ•±˜¹½¹™¥œ(€€€€€€€ÍÑ…Ñ¥}É½½Ğ€ôA…Ñ ¡}}™¥±•}|¤¹É•Í½±Ù” ¤¹Á…É•¹Ğ((€€€€€€€±…ÍÌ!…¹‘±•È¡	…Í•!QQAI•ÅÕ•ÍÑ!…¹‘±•È¤è(€€€€€€€€€€€‘•˜Í•¹‘}©Í½¸¡¡…¹‘±•È°Á…å±½…°ÍÑ…ÑÕÌôÈÀÀ¤è(€€€€€€€€€€€€€€€‰½‘ä€ô©Í½¸¹‘ÕµÁÌ¡Á…å±½…°•¹ÍÕÉ•}…Í¥¤õ…±Í”¤¹•¹½‘” ‰ÕÑ˜´àˆ¤(€€€€€€€€€€€€€€€¡…¹‘±•È¹Í•¹‘}É•ÍÁ½¹Í”¡ÍÑ…ÑÕÌ¤(€€€€€€€€€€€€€€€¡…¹‘±•È¹Í•¹‘}¡•…‘•È ‰½¹Ñ•¹ĞµQåÁ”ˆ°€‰…ÁÁ±¥…Ñ¥½¸½©Í½¸ì¡…ÉÍ•ĞõÕÑ˜´àˆ¤(€€€€€€€€€€€€€€€¡…¹‘±•È¹Í•¹‘}¡•…‘•È ‰½¹Ñ•¹Ğµ1•¹Ñ ˆ°ÍÑÈ¡±•¸¡‰½‘ä¤¤¤(€€€€€€€€€€€€€€€¡…¹‘±•È¹•¹‘}¡•…‘•ÉÌ ¤(€€€€€€€€€€€€€€€¡…¹‘±•È¹İ™¥±”¹İÉ¥Ñ”¡‰½‘ä¤((€€€€€€€€€€€‘•˜É•…‘}Á…å±½…¡¡…¹‘±•È¤è(€€€€€€€€€€€€€€€±•¹Ñ €ô¥¹Ğ¡¡…¹‘±•È¹¡•…‘•ÉÌ¹•Ğ ‰½¹Ñ•¹Ğµ1•¹Ñ ˆ¤½È€À¤(€€€€€€€€€€€€€€€¥˜¹½Ğ±•¹Ñ è(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸íô(€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸©Í½¸¹±½…‘Ì¡¡…¹‘±•È¹É™¥±”¹É•…¡±•¹Ñ ¤¹‘•½‘” ‰ÕÑ˜´àˆ¤¤(€€€€€€€€€€€€€€€•á•ÁĞ©Í½¸¹)M=9•½‘•ÉÉ½Èè(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸íô((€€€€€€€€€€€‘•˜ÅÕ•Éä¡¡…¹‘±•È¤è(€€€€€€€€€€€€€€€É•ÑÕÉ¸‘¥Ğ¡ÕÉ±±¥ˆ¹Á…ÉÍ”¹Á…ÉÍ•}ÅÍ°¡ÕÉ±±¥ˆ¹Á…ÉÍ”¹ÕÉ±ÍÁ±¥Ğ¡¡…¹‘±•È¹Á…Ñ ¤¹ÅÕ•Éä¤¤((€€€€€€€€€€€‘•˜É½¹}Í•É•Ğ¡¡…¹‘±•È¤è(€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹¡•…‘•ÉÌ¹•Ğ ‰`µÉ½¸µM•É•Ğˆ°€ˆˆ¤((€€€€€€€€€€€‘•˜É½ÕÑ”¡¡…¹‘±•È¤è(€€€€€€€€€€€€€€€É•ÑÕÉ¸ÕÉ±±¥ˆ¹Á…ÉÍ”¹ÕÉ±ÍÁ±¥Ğ¡¡…¹‘±•È¹Á…Ñ ¤¹Á…Ñ ((€€€€€€€€€€€‘•˜…ÕÑ¡•¹Ñ¥…Ñ•‘}ÕÍ•È¡¡…¹‘±•È°Á…å±½…õ9½¹”°Á…É…µÌõ9½¹”¤è(€€€€€€€€€€€€€€€É•ÑÕÉ¸…ÕÑ¡•¹Ñ¥…Ñ•‘}±¥¹•}ÕÍ•È (€€€€€€€€€€€€€€€€€€€Á…å±½…½Èíô°(€€€€€€€€€€€€€€€€€€€…ÉÌõÁ…É…µÌ½Èíô°(€€€€€€€€€€€€€€€€€€€¡•…‘•ÉÌõ‘¥Ğ¡¡…¹‘±•È¹¡•…‘•ÉÌ¹¥Ñ•µÌ ¤¤°(€€€€€€€€€€€€€€€€€€€½¹™¥œõ½¹™¥œ°(€€€€€€€€€€€€€€€€¤((€€€€€€€€€€€‘•˜‘½}P¡¡…¹‘±•È¤è(€€€€€€€€€€€€€€€É½ÕÑ”€ô¡…¹‘±•È¹É½ÕÑ” ¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…‘µ¥¸ˆ½ÈÉ½ÕÑ”¹ÍÑ…ÉÑÍİ¥Ñ  ˆ½…Á¤½…‘µ¥¸¼ˆ¤è(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡ì‰•ÉÉ½Èˆè€‰…‘µ¥¹}¹½Ñ}½¹™¥ÕÉ•‰ô°€ÔÀÌ¤(€€€€€€€€€€€€€€€Á…É…µÌ€ô¡…¹‘±•È¹ÅÕ•Éä ¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½½¹™¥œˆè(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡…ÁÁ}½¹™¥œ¡½¹™¥œ¤¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½¡•…±Ñ ˆè(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡ì‰½¬ˆèQÉÕ•ô¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½ÍÑ…ÑÕÌˆè(€€€€€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô¡…¹‘±•È¹…ÕÑ¡•¹Ñ¥…Ñ•‘}ÕÍ•È¡Á…É…µÌõÁ…É…µÌ¤(€€€€€€€€€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ôÍÑ…ÑÕÍ}™½É}ÕÍ•È (€€€€€€€€€€€€€€€€€€€€€€€‘…Ñ…}™¥±”°(€€€€€€€€€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€€€€€€€€€Á…É…µÌ¹•Ğ ‰‘¥ÍÁ±…å}¹…µ”ˆ¤°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½½¹‰½…É‘¥¹œˆè(€€€€€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô¡…¹‘±•È¹…ÕÑ¡•¹Ñ¥…Ñ•‘}ÕÍ•È¡Á…É…µÌõÁ…É…µÌ¤(€€€€€€€€€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ô½¹‰½…É‘¥¹}ÍÑ…ÑÕÍ}Á…å±½…¡‘…Ñ…}™¥±”°±¥¹•}ÕÍ•É}¥¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½½¹‰½…É‘¥¹œ½ÍÑ…Ñ”ˆè(€€€€€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô¡…¹‘±•È¹…ÕÑ¡•¹Ñ¥…Ñ•‘}ÕÍ•È¡Á…É…µÌõÁ…É…µÌ¤(€€€€€€€€€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ô½¹‰½…É‘¥¹}ÍÑ…ÑÕÍ}Á…å±½… (€€€€€€€€€€€€€€€€€€€€€€€‘…Ñ…}™¥±”°(€€€€€€€€€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€€€€€€€€€…±±½İ}µ¥ÍÍ¥¹}ÁÉ½™¥±”õQÉÕ”°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…‘µ¥¸½ÍÕµµ…Éäˆè(€€€€€€€€€€€€€€€€€€€‘•¹¥•€ô…‘µ¥¹}…ÕÑ¡}•ÉÉ½É}Á…å±½…¡½¹™¥œ°Á…É…µÌ¹•Ğ ‰Á…ÍÍİ½Éˆ°€ˆˆ¤¤(€€€€€€€€€€€€€€€€€€€¥˜‘•¹¥•è(€€€€€€€€€€€€€€€€€€€€€€€Á…å±½…°½‘”€ô‘•¹¥•(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡Á…å±½…°½‘”¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡…‘µ¥¹}ÍÕµµ…Éä¡‘…Ñ…}™¥±”°½¹™¥œ¤¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½½¹Ñ…ÑÌˆè(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡•Ñ}½¹Ñ…ÑÌ¡‘…Ñ…}™¥±”°Á…É…µÌ¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤¤¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½•µ•É•¹äµ½¹Ñ…Ğ½¥¹Ù¥Ñ”µÁÉ•Ù¥•Üˆè(€€€€€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô¡…¹‘±•È¹…ÕÑ¡•¹Ñ¥…Ñ•‘}ÕÍ•È¡íô°Á…É…µÌ¤(€€€€€€€€€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ô¥¹Ù¥Ñ•}‰¥¹‘}ÁÉ•Ù¥•Ü (€€€€€€€€€€€€€€€€€€€€€€€‘…Ñ…}™¥±”°(€€€€€€€€€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰¥¹Ù¥Ñ•}™É½´ˆèÁ…É…µÌ¹•Ğ ‰¥¹Ù¥Ñ•}™É½´ˆ¤½ÈÁ…É…µÌ¹•Ğ ‰™É½´ˆ¤½È€ˆˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰¥¹Ù¥Ñ•}Ñ½­•¸ˆèÁ…É…µÌ¹•Ğ ‰¥¹Ù¥Ñ•}Ñ½­•¸ˆ¤½È€ˆˆ°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰±¥¹•}ÕÍ•É}¥ˆè±¥¹•}ÕÍ•É}¥°(€€€€€€€€€€€€€€€€€€€€€€€ô°(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…±•¹‘…Èµ¹½Ñ•Ìˆè(€€€€€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô¡…¹‘±•È¹…ÕÑ¡•¹Ñ¥…Ñ•‘}ÕÍ•È¡Á…É…µÌõÁ…É…µÌ¤(€€€€€€€€€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€€€€€€€€€‰½‘ä€ô•Ñ}…±•¹‘…É}¹½Ñ•Ì¡‘…Ñ…}™¥±”°±¥¹•}ÕÍ•É}¥¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸ (€€€€€€€€€€€€€€€€€€€€€€€‰½‘ä°ÍÑ…ÑÕÌôÈÀÀ¥˜‰½‘ä¹•Ğ ‰½¬ˆ¤•±Í”€ĞÀÌ(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½Íµ…ÉĞµÉ•µ¥¹‘•ÉÌˆè(€€€€€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô¡…¹‘±•È¹…ÕÑ¡•¹Ñ¥…Ñ•‘}ÕÍ•È¡Á…É…µÌõÁ…É…µÌ¤(€€€€€€€€€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸ (€€€€€€€€€€€€€€€€€€€€€€€•Ñ}Íµ…ÉÑ}É•µ¥¹‘•ÉÍ}Á…å±½…¡‘…Ñ…}™¥±”°±¥¹•}ÕÍ•É}¥¤(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½™É¥•¹‘Ì½±½…Ñ¥½¹Ìˆè(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡™É¥•¹‘}±½…Ñ¥½¹Ì¡‘…Ñ…}™¥±”°Á…É…µÌ¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤¤¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½±½…Ñ¥½¸½ÍÑ…ÑÕÌˆè(€€€€€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥€ôÁ…É…µÌ¹•Ğ ‰±¥¹•}ÕÍ•É}¥ˆ¤(€€€€€€€€€€€€€€€€€€€¥˜¹½Ğ±¥¹•}ÕÍ•É}¥è(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡ì‰•ÉÉ½Èˆè€‰µ¥ÍÍ¥¹œ±¥¹•}ÕÍ•É}¥‰ô°€ĞÀÀ¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡ì(€€€€€€€€€€€€€€€€€€€€€€€€‰½¬ˆèQÉÕ”°(€€€€€€€€€€€€€€€€€€€€€€€€‰Í…™•Ñå}Õ…ÉˆèÍ…™•Ñå}Õ…É‘}Í¹…ÁÍ¡½Ğ¡•Ñ}ÁÉ½™¥±”¡±½…‘}ÍÑ…Ñ”¡‘…Ñ…}™¥±”¤°±¥¹•}ÕÍ•É}¥¤¤°(€€€€€€€€€€€€€€€€€€€ô¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½É½¸½½¹Ñ…ĞµÉ•µ¥¹‘•ÉÌˆè(€€€€€€€€€€€€€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡½¹™¥œ°¡…¹‘±•È¹É½¹}Í•É•Ğ ¤¤è(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ôÍ•¹‘}µ¥ÍÍ¥¹}½¹Ñ…Ñ}É•µ¥¹‘•ÉÌ¡½¹™¥œ¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½É½¸½¡•­¥¸µÉ•µ¥¹‘•ÉÌˆè(€€€€€€€€€€€€€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡½¹™¥œ°¡…¹‘±•È¹É½¹}Í•É•Ğ ¤¤è(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€€€€€€€€€µ½‘”€ôÍÑÈ¡Á…É…µÌ¹•Ğ ‰µ½‘”ˆ°€ˆˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤¹±½İ•È ¤(€€€€€€€€€€€€€€€€€€€™½É”€ôÍÑÈ¡Á…É…µÌ¹•Ğ ‰™½É”ˆ°€ˆˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤¹±½İ•È ¤¥¸ìˆÄˆ°€‰ÑÉÕ”ˆ°€‰å•Ìˆ°€‰½¸‰ô(€€€€€€€€€€€€€€€€€€€¥˜µ½‘”¥¸ì‰‰É½…‘…ÍĞˆ°€‰É•ÁÕÍ ˆ°€‰…±°‰ô½È™½É”è(€€€€€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ô‰É½…‘…ÍÑ}¡•­¥¹}É•µ¥¹‘•ÉÌ¡½¹™¥œ¤(€€€€€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ôÍ•¹‘}¡•­¥¹}É•µ¥¹‘•ÉÌ¡½¹™¥œ¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½É½¸½¡•­¥¸µ‰É½…‘…ÍĞˆè(€€€€€€€€€€€€€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡½¹™¥œ°¡…¹‘±•È¹É½¹}Í•É•Ğ ¤¤è(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ô‰É½…‘…ÍÑ}¡•­¥¹}É•µ¥¹‘•ÉÌ¡½¹™¥œ¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½É½¸½‘…Ñ„µ±•…¹ÕÀˆè(€€€€€€€€€€€€€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡½¹™¥œ°¡…¹‘±•È¹É½¹}Í•É•Ğ ¤¤è(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ô±•…¹ÕÁ}•áÁ¥É•‘}‘…Ñ„¡½¹™¥œ¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½É½¸½‰…­™¥±°µ‰¥¹µ¹½Ñ¥™äˆè(€€€€€€€€€€€€€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡½¹™¥œ°¡…¹‘±•È¹É½¹}Í•É•Ğ ¤¤è(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€€€€€€€€€‘Éå}ÉÕ¸€ôÍÑÈ¡Á…É…µÌ¹•Ğ ‰‘Éå}ÉÕ¸ˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤¹±½İ•È ¤¥¸ì(€€€€€€€€€€€€€€€€€€€€€€€€ˆÄˆ°(€€€€€€€€€€€€€€€€€€€€€€€€‰ÑÉÕ”ˆ°(€€€€€€€€€€€€€€€€€€€€€€€€‰å•Ìˆ°(€€€€€€€€€€€€€€€€€€€€€€€€‰½¸ˆ°(€€€€€€€€€€€€€€€€€€€ô(€€€€€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€€€€€±¥µ¥Ğ€ô¥¹Ğ¡Á…É…µÌ¹•Ğ ‰±¥µ¥Ğˆ¤½È€À¤(€€€€€€€€€€€€€€€€€€€•á•ÁĞ€¡QåÁ•ÉÉ½È°Y…±Õ•ÉÉ½È¤è(€€€€€€€€€€€€€€€€€€€€€€€±¥µ¥Ğ€ô€À(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ô‰…­™¥±±}‰¥¹‘}¹½Ñ¥™ä¡½¹™¥œ°‘Éå}ÉÕ¸õ‘Éå}ÉÕ¸°±¥µ¥Ğõ±¥µ¥Ğ¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤((€€€€€€€€€€€€€€€™¥±•}¹…µ”€ô€‰¥¹‘•à¹¡Ñµ°ˆ¥˜É½ÕÑ”€ôô€ˆ¼ˆ•±Í”É½ÕÑ”¹±ÍÑÉ¥À ˆ¼ˆ¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…‘µ¥¸ˆè(€€€€€€€€€€€€€€€€€€€™¥±•}¹…µ”€ô€‰…‘µ¥¸¹¡Ñµ°ˆ(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½Ñ•ÉµÌˆè(€€€€€€€€€€€€€€€€€€€™¥±•}¹…µ”€ô€‰Ñ•ÉµÌ¹¡Ñµ°ˆ(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½ÁÉ¥Ù…äˆè(€€€€€€€€€€€€€€€€€€€™¥±•}¹…µ”€ô€‰ÁÉ¥Ù…ä¹¡Ñµ°ˆ(€€€€€€€€€€€€€€€™¥±•}Á…Ñ €ôÍÑ…Ñ¥}É½½Ğ€¼™¥±•}¹…µ”(€€€€€€€€€€€€€€€¥˜¹½Ğ™¥±•}Á…Ñ ¹•á¥ÍÑÌ ¤½È¹½Ğ™¥±•}Á…Ñ ¹¥Í}™¥±” ¤è(€€€€€€€€€€€€€€€€€€€¡…¹‘±•È¹Í•¹‘}É•ÍÁ½¹Í” ĞÀĞ¤(€€€€€€€€€€€€€€€€€€€¡…¹‘±•È¹•¹‘}¡•…‘•ÉÌ ¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸(€€€€€€€€€€€€€€€‰½‘ä€ô™¥±•}Á…Ñ ¹É•…‘}‰åÑ•Ì ¤(€€€€€€€€€€€€€€€½¹Ñ•¹Ñ}ÑåÁ”€ô€‰Ñ•áĞ½¡Ñµ°ì¡…ÉÍ•ĞõÕÑ˜´àˆ¥˜™¥±•}Á…Ñ ¹ÍÕ™™¥à€ôô€ˆ¹¡Ñµ°ˆ•±Í”€‰Ñ•áĞ½Á±…¥¸ì¡…ÉÍ•ĞõÕÑ˜´àˆ(€€€€€€€€€€€€€€€¡…¹‘±•È¹Í•¹‘}É•ÍÁ½¹Í” ÈÀÀ¤(€€€€€€€€€€€€€€€¡…¹‘±•È¹Í•¹‘}¡•…‘•È ‰½¹Ñ•¹ĞµQåÁ”ˆ°½¹Ñ•¹Ñ}ÑåÁ”¤(€€€€€€€€€€€€€€€¡…¹‘±•È¹Í•¹‘}¡•…‘•È ‰½¹Ñ•¹Ğµ1•¹Ñ ˆ°ÍÑÈ¡±•¸¡‰½‘ä¤¤¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…‘µ¥¸ˆè(€€€€€€€€€€€€€€€€€€€¡…¹‘±•È¹Í•¹‘}¡•…‘•È ‰…¡”µ½¹ÑÉ½°ˆ°€‰¹¼µÍÑ½É”°¹¼µ…¡”°µÕÍĞµÉ•Ù…±¥‘…Ñ”°µ…àµ…”ôÀˆ¤(€€€€€€€€€€€€€€€€€€€¡…¹‘±•È¹Í•¹‘}¡•…‘•È ‰AÉ…µ„ˆ°€‰¹¼µ…¡”ˆ¤(€€€€€€€€€€€€€€€¡…¹‘±•È¹•¹‘}¡•…‘•ÉÌ ¤(€€€€€€€€€€€€€€€¡…¹‘±•È¹İ™¥±”¹İÉ¥Ñ”¡‰½‘ä¤((€€€€€€€€€€€‘•˜‘½}A=MP¡¡…¹‘±•È¤è(€€€€€€€€€€€€€€€É½ÕÑ”€ô¡…¹‘±•È¹É½ÕÑ” ¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…‘µ¥¸ˆ½ÈÉ½ÕÑ”¹ÍÑ…ÉÑÍİ¥Ñ  ˆ½…Á¤½…‘µ¥¸¼ˆ¤è(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡ì‰•ÉÉ½Èˆè€‰…‘µ¥¹}¹½Ñ}½¹™¥ÕÉ•‰ô°€ÔÀÌ¤(€€€€€€€€€€€€€€€Á…É…µÌ€ô¡…¹‘±•È¹ÅÕ•Éä ¤(€€€€€€€€€€€€€€€Á…å±½…€ô¡…¹‘±•È¹É•…‘}Á…å±½… ¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½±¥¹”½É•¥ÍÑ•Èˆè(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ôÉ•¥ÍÑ•É}±¥¹•}ÕÍ•È¡‘…Ñ…}™¥±”°Á…å±½…¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½¡•­¥¸ˆè(€€€€€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô¡…¹‘±•È¹…ÕÑ¡•¹Ñ¥…Ñ•‘}ÕÍ•È¡Á…å±½…°Á…É…µÌ¤(€€€€€€€€€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ô¡•­¥¹}™½É}ÕÍ•È (€€€€€€€€€€€€€€€€€€€€€€€‘…Ñ…}™¥±”°±¥¹•}ÕÍ•É}¥°Á…å±½…°½¹™¥œ(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½½¹‰½…É‘¥¹œ½É•µ¥¹‘•Èˆè(€€€€€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô¡…¹‘±•È¹…ÕÑ¡•¹Ñ¥…Ñ•‘}ÕÍ•È¡Á…å±½…°Á…É…µÌ¤(€€€€€€€€€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ôÕÁ‘…Ñ•}½¹‰½…É‘¥¹}É•µ¥¹‘•È (€€€€€€€€€€€€€€€€€€€€€€€‘…Ñ…}™¥±”°±¥¹•}ÕÍ•É}¥°Á…å±½…(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½½¹‰½…É‘¥¹œ½½µÁ±•Ñ”ˆè(€€€€€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô¡…¹‘±•È¹…ÕÑ¡•¹Ñ¥…Ñ•‘}ÕÍ•È¡Á…å±½…°Á…É…µÌ¤(€€€€€€€€€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ô½µÁ±•Ñ•}½¹‰½…É‘¥¹}™½É}ÕÍ•È (€€€€€€€€€€€€€€€€€€€€€€€‘…Ñ…}™¥±”°±¥¹•}ÕÍ•É}¥°Á…å±½…(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½İ…É¹¥¹œ½…¹•°ˆè(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡…¹•±}İ…É¹¥¹œ¡‘…Ñ…}™¥±”°Á…å±½…°½¹™¥œ¤¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½Í•ÑÑ¥¹Ìˆè(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡Í…Ù•}Í•ÑÑ¥¹Í}™½É}ÁÉ½™¥±”¡‘…Ñ…}™¥±”°Á…å±½…¤¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½‰¥±±¥¹œ½ÁÉ•™•É•¹•Ìˆè(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ôÍ…Ù•}‰¥±±¥¹}ÁÉ•™•É•¹•Ì¡‘…Ñ…}™¥±”°Á…å±½…¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½Á…åµ•¹ÑÌ½½É‘•ÉÌˆè(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ôÉ•…Ñ•}Á…åµ•¹Ñ}½É‘•È¡‘…Ñ…}™¥±”°Á…å±½…°½¹™¥œ¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½½¹Ñ…ÑÌˆè(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ôÍ…Ù•}½¹Ñ…ÑÌ¡‘…Ñ…}™¥±”°Á…å±½…¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…±•¹‘…Èµ¹½Ñ•Ìˆè(€€€€€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô¡…¹‘±•È¹…ÕÑ¡•¹Ñ¥…Ñ•‘}ÕÍ•È¡Á…å±½…°Á…É…µÌ¤(€€€€€€€€€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€€€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ôÍ…Ù•}…±•¹‘…É}¹½Ñ”¡‘…Ñ…}™¥±”°Á…å±½…¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½Íµ…ÉĞµÉ•µ¥¹‘•ÉÌˆè(€€€€€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô¡…¹‘±•È¹…ÕÑ¡•¹Ñ¥…Ñ•‘}ÕÍ•È¡Á…å±½…°Á…É…µÌ¤(€€€€€€€€€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€€€€€€€€€Á…å±½…‘l‰±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ôÍ…Ù•}Íµ…ÉÑ}É•µ¥¹‘•È¡‘…Ñ…}™¥±”°Á…å±½…¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”¥¸ì(€€€€€€€€€€€€€€€€€€€€ˆ½…Á¤½É½¸½Íµ…ÉĞµÉ•µ¥¹‘•ÉÌˆ°(€€€€€€€€€€€€€€€€€€€€ˆ½…Á¤½É½¸½‰¥ÉÑ¡‘…äµÉ•µ¥¹‘•ÉÌˆ°(€€€€€€€€€€€€€€€ôè(€€€€€€€€€€€€€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡½¹™¥œ°¡…¹‘±•È¹É½¹}Í•É•Ğ ¤¤è(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€€€€€€€€€Ñ…Í¬€ô€ (€€€€€€€€€€€€€€€€€€€€€€€Í•¹‘}Íµ…ÉÑ}É•µ¥¹‘•ÉÌ(€€€€€€€€€€€€€€€€€€€€€€€¥˜É½ÕÑ”¹•¹‘Íİ¥Ñ  ‰Íµ…ÉĞµÉ•µ¥¹‘•ÉÌˆ¤(€€€€€€€€€€€€€€€€€€€€€€€•±Í”Í•¹‘}‰¥ÉÑ¡‘…å}É•µ¥¹‘•ÉÌ(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ôÑ…Í¬¡½¹™¥œ¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½•µ•É•¹äµ½¹Ñ…Ğ½‰¥¹ˆè(€€€€€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô¡…¹‘±•È¹…ÕÑ¡•¹Ñ¥…Ñ•‘}ÕÍ•È¡Á…å±½…°Á…É…µÌ¤(€€€€€€€€€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€€€€€€€€€Á…å±½…‘l‰½¹Ñ…Ñ}±¥¹•}ÕÍ•É}¥‰t€ô±¥¹•}ÕÍ•É}¥(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ô‰¥¹‘}•µ•É•¹å}½¹Ñ…Ğ¡‘…Ñ…}™¥±”°Á…å±½…°½¹™¥œ¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½•µ•É•¹äµ½¹Ñ…Ğ½¥¹Ù¥Ñ”ˆè(€€€€€€€€€€€€€€€€€€€±¥¹•}ÕÍ•É}¥°•ÉÈ€ô¡…¹‘±•È¹…ÕÑ¡•¹Ñ¥…Ñ•‘}ÕÍ•È¡Á…å±½…°Á…É…µÌ¤(€€€€€€€€€€€€€€€€€€€¥˜•ÉÈè(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡•ÉÉlÁt°•ÉÉlÅt¤(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ôÉ•…Ñ•}Õ…É‘¥…¹}¥¹Ù¥Ñ” (€€€€€€€€€€€€€€€€€€€€€€€‘…Ñ…}™¥±”°±¥¹•}ÕÍ•É}¥°Á…å±½…(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½Õ…É‘¥…¸µÉ½ÕÁÌ½‰¥¹ˆè(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ô‰¥¹‘}Õ…É‘¥…¹}É½ÕÀ¡‘…Ñ…}™¥±”°Á…å±½…¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½Õ…É‘¥…¸µÉ½ÕÁÌ½Õ¹‰¥¹ˆè(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ôÕ¹‰¥¹‘}Õ…É‘¥…¹}É½ÕÀ¡‘…Ñ…}™¥±”°Á…å±½…¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½™É¥•¹‘Ì½¥¹Ù¥Ñ”ˆè(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ôÉ•…Ñ•}™É¥•¹‘}¥¹Ù¥Ñ”¡‘…Ñ…}™¥±”°Á…å±½…¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½™É¥•¹‘Ì½…•ÁĞˆè(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ô…•ÁÑ}™É¥•¹‘}¥¹Ù¥Ñ”¡‘…Ñ…}™¥±”°Á…å±½…¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½±½…Ñ¥½¸½ÕÁ‘…Ñ”ˆè(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ôÕÁ‘…Ñ•}±½…Ñ¥½¸¡‘…Ñ…}™¥±”°Á…å±½…°½¹™¥œ¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½±½…Ñ¥½¸½ÍÑ½Àˆè(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ôÍÑ½Á}±½…Ñ¥½¹}Í¡…É¥¹œ¡‘…Ñ…}™¥±”°Á…å±½…¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½Í½Ìˆè(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ôÑÉ¥•É}Í½Ì¡‘…Ñ…}™¥±”°Á…å±½…°½¹™¥œ¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½Í½Ì½…¹•°ˆè(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ô…¹•±}Í½Í}•Ù•¹Ğ¡‘…Ñ…}™¥±”°Á…å±½…°½¹™¥œ¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½Í½Ì½É•ÑÉäˆè(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ôÉ•ÑÉå}Í½Í}•Ù•¹Ğ¡‘…Ñ…}™¥±”°Á…å±½…°½¹™¥œ¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…½Õ¹Ğ½‘•±•Ñ”ˆè(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ô‘•±•Ñ•}…½Õ¹Ğ¡‘…Ñ…}™¥±”°Á…å±½…¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…½Õ¹Ğ½•áÁ½ÉĞˆè(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ô•áÁ½ÉÑ}…½Õ¹Ñ}‘…Ñ„¡‘…Ñ…}™¥±”°Á…å±½…¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…½Õ¹Ğ½¡¥ÍÑ½Éä½‘•±•Ñ”ˆè(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ô‘•±•Ñ•}Á•ÉÍ½¹…±}¡¥ÍÑ½Éä¡‘…Ñ…}™¥±”°Á…å±½…¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…‘µ¥¸½Í•¹µÉ•µ¥¹‘•ÉÌˆè(€€€€€€€€€€€€€€€€€€€¥˜¹½Ğ…‘µ¥¹}…±±½İ•¡½¹™¥œ°Á…É…µÌ¹•Ğ ‰Á…ÍÍİ½Éˆ°€ˆˆ¤¤è(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ôÍ•¹‘}‘Õ•}É•µ¥¹‘•ÉÌ¡½¹™¥œ¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…‘µ¥¸½Í•¹µ½¹Ñ…ĞµÉ•µ¥¹‘•ÉÌˆè(€€€€€€€€€€€€€€€€€€€¥˜¹½Ğ…‘µ¥¹}…±±½İ•¡½¹™¥œ°Á…É…µÌ¹•Ğ ‰Á…ÍÍİ½Éˆ°€ˆˆ¤¤è(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ôÍ•¹‘}µ¥ÍÍ¥¹}½¹Ñ…Ñ}É•µ¥¹‘•ÉÌ¡½¹™¥œ¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…‘µ¥¸½Í•¹µÉ•¹•İ…°µÉ•µ¥¹‘•ÉÌˆè(€€€€€€€€€€€€€€€€€€€¥˜¹½Ğ…‘µ¥¹}…±±½İ•¡½¹™¥œ°Á…É…µÌ¹•Ğ ‰Á…ÍÍİ½Éˆ°€ˆˆ¤¤è(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ôÍ•¹‘}É•¹•İ…±}É•µ¥¹‘•ÉÌ¡½¹™¥œ¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…‘µ¥¸½Á…åµ•¹ÑÌ½½¹™¥É´ˆè(€€€€€€€€€€€€€€€€€€€¥˜¹½Ğ…‘µ¥¹}…±±½İ•¡½¹™¥œ°Á…É…µÌ¹•Ğ ‰Á…ÍÍİ½Éˆ°€ˆˆ¤¤è(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ô½¹™¥Éµ}Á…åµ•¹Ñ}½É‘•È¡‘…Ñ…}™¥±”°Á…å±½…°½¹™¥œ¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½É½¸½Ñ¥¬ˆè(€€€€€€€€€€€€€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡½¹™¥œ°¡…¹‘±•È¹É½¹}Í•É•Ğ ¤¤è(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ôÉÕ¹}É½¹}Ñ¥¬¡½¹™¥œ¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½É½¸½½¹Ñ…ĞµÉ•µ¥¹‘•ÉÌˆè(€€€€€€€€€€€€€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡½¹™¥œ°¡…¹‘±•È¹É½¹}Í•É•Ğ ¤¤è(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ôÍ•¹‘}µ¥ÍÍ¥¹}½¹Ñ…Ñ}É•µ¥¹‘•ÉÌ¡½¹™¥œ¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½É½¸½¡•­¥¸µÉ•µ¥¹‘•ÉÌˆè(€€€€€€€€€€€€€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡½¹™¥œ°¡…¹‘±•È¹É½¹}Í•É•Ğ ¤¤è(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€€€€€€€€€µ½‘”€ôÍÑÈ¡Á…É…µÌ¹•Ğ ‰µ½‘”ˆ°€ˆˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤¹±½İ•È ¤(€€€€€€€€€€€€€€€€€€€™½É”€ôÍÑÈ¡Á…É…µÌ¹•Ğ ‰™½É”ˆ°€ˆˆ¤½È€ˆˆ¤¹ÍÑÉ¥À ¤¹±½İ•È ¤¥¸ìˆÄˆ°€‰ÑÉÕ”ˆ°€‰å•Ìˆ°€‰½¸‰ô(€€€€€€€€€€€€€€€€€€€¥˜µ½‘”¥¸ì‰‰É½…‘…ÍĞˆ°€‰É•ÁÕÍ ˆ°€‰…±°‰ô½È™½É”è(€€€€€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ô‰É½…‘…ÍÑ}¡•­¥¹}É•µ¥¹‘•ÉÌ¡½¹™¥œ¤(€€€€€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ôÍ•¹‘}¡•­¥¹}É•µ¥¹‘•ÉÌ¡½¹™¥œ¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½É½¸½¡•­¥¸µ‰É½…‘…ÍĞˆè(€€€€€€€€€€€€€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡½¹™¥œ°¡…¹‘±•È¹É½¹}Í•É•Ğ ¤¤è(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ô‰É½…‘…ÍÑ}¡•­¥¹}É•µ¥¹‘•ÉÌ¡½¹™¥œ¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½É½¸½É•¹•İ…°µÉ•µ¥¹‘•ÉÌˆè(€€€€€€€€€€€€€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡½¹™¥œ°¡…¹‘±•È¹É½¹}Í•É•Ğ ¤¤è(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ôÍ•¹‘}É•¹•İ…±}É•µ¥¹‘•ÉÌ¡½¹™¥œ¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½É½¸½‘…Ñ„µ±•…¹ÕÀˆè(€€€€€€€€€€€€€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡½¹™¥œ°¡…¹‘±•È¹É½¹}Í•É•Ğ ¤¤è(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ô±•…¹ÕÁ}•áÁ¥É•‘}‘…Ñ„¡½¹™¥œ¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½É½¸½‰…­™¥±°µ‰¥¹µ¹½Ñ¥™äˆè(€€€€€€€€€€€€€€€€€€€¥˜¹½ĞÉ½¹}…±±½İ•¡½¹™¥œ°¡…¹‘±•È¹É½¹}Í•É•Ğ ¤¤è(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€€€€€€€€€‘Éå}ÉÕ¸€ôÍÑÈ (€€€€€€€€€€€€€€€€€€€€€€€Á…É…µÌ¹•Ğ ‰‘Éå}ÉÕ¸ˆ¤½ÈÁ…å±½…¹•Ğ ‰‘Éå}ÉÕ¸ˆ¤½È€ˆˆ(€€€€€€€€€€€€€€€€€€€€¤¹ÍÑÉ¥À ¤¹±½İ•È ¤¥¸ìˆÄˆ°€‰ÑÉÕ”ˆ°€‰å•Ìˆ°€‰½¸‰ô(€€€€€€€€€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€€€€€€€€€±¥µ¥Ğ€ô¥¹Ğ¡Á…É…µÌ¹•Ğ ‰±¥µ¥Ğˆ¤½ÈÁ…å±½…¹•Ğ ‰±¥µ¥Ğˆ¤½È€À¤(€€€€€€€€€€€€€€€€€€€•á•ÁĞ€¡QåÁ•ÉÉ½È°Y…±Õ•ÉÉ½È¤è(€€€€€€€€€€€€€€€€€€€€€€€±¥µ¥Ğ€ô€À(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ô‰…­™¥±±}‰¥¹‘}¹½Ñ¥™ä¡½¹™¥œ°‘Éå}ÉÕ¸õ‘Éå}ÉÕ¸°±¥µ¥Ğõ±¥µ¥Ğ¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…‘µ¥¸½ÕÍ•ÈµÁ±…¸ˆè(€€€€€€€€€€€€€€€€€€€¥˜¹½Ğ…‘µ¥¹}…±±½İ•¡½¹™¥œ°Á…É…µÌ¹•Ğ ‰Á…ÍÍİ½Éˆ°€ˆˆ¤¤è(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ô…‘µ¥¹}ÕÁ‘…Ñ•}ÕÍ•É}Á±…¸¡‘…Ñ…}™¥±”°Á…å±½…¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¥˜É½ÕÑ”€ôô€ˆ½…Á¤½…‘µ¥¸½Í•Ğµ½É”µÕ…É‘¥…¸ˆè(€€€€€€€€€€€€€€€€€€€¥˜¹½Ğ…‘µ¥¹}…±±½İ•¡½¹™¥œ°Á…É…µÌ¹•Ğ ‰Á…ÍÍİ½Éˆ°€ˆˆ¤¤è(€€€€€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡ì‰•ÉÉ½Èˆè€‰Õ¹…ÕÑ¡½É¥é•‰ô°€ĞÀÄ¤(€€€€€€€€€€€€€€€€€€€‘…Ñ„°½‘”€ô…‘µ¥¹}Í•Ñ}½É•}Õ…É‘¥…¸¡‘…Ñ…}™¥±”°Á…å±½…¤(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸¡…¹‘±•È¹Í•¹‘}©Í½¸¡‘…Ñ„°½‘”¤(€€€€€€€€€€€€€€€¡…¹‘±•È¹Í•¹‘}©Í½¸¡ì‰•ÉÉ½Èˆè€‰¹½Ğ™½Õ¹‰ô°€ĞÀĞ¤((€€€€€€€ÁÉ¥¹Ğ ‰±…Í¬¥Ì¹½Ğ¥¹ÍÑ…±±•¸UÍ¥¹œÑ¡”‰Õ¥±Ğµ¥¸™…±±‰…¬Í•ÉÙ•È¸ˆ¤(€€€€€€€ÁÉ¥¹Ğ¡˜‰=Á•¸¡ÑÑÀè¼½í¡½ÍÑôéíÁ½ÉÑôˆ¤(€€€€€€€Q¡É•…‘¥¹!QQAM•ÉÙ•È ¡¡½ÍĞ°Á½ÉĞ¤°!…¹‘±•È¤¹Í•ÉÙ•}™½É•Ù•È ¤(()…ÁÀ€ôÉ•…Ñ•}…ÁÀ ¤(()¥˜}}¹…µ•}|€ôô€‰}}µ…¥¹}|ˆè(€€€…ÁÀ¹ÉÕ¸¡¡½ÍĞôˆÄÈÜ¸À¸À¸Äˆ°Á½ÉĞõ¥¹Ğ¡½Ì¹•¹Ù¥É½¸¹•Ğ ‰A=IPˆ°€ˆÔÀÀÀˆ¤¤°‘•‰ÕœõQÉÕ”¤