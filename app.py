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
import threading
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

from daily_care import build_daily_care_context, streak_level_context
from finance_admin import (
    FinanceValidationError,
    create_expense as create_finance_expense,
    finance_dashboard,
    update_finance_settings,
)
from security_controls import apply_security_headers, security_readiness

from push_delivery import (
    classify_push_exception,
    push_attempt_allowed,
    record_push_failure,
)
from push_management import (
    APPROVED_PUSH_TEMPLATES,
    AUDIENCE_CODES,
    CAMPAIGN_STATUS_LABELS_ZH,
    MAX_DELIVERY_ATTEMPTS,
    CampaignConflictError,
    CampaignNotFoundError,
    CampaignValidationError,
    append_system_delivery_record,
    cancel_campaign,
    claim_due_campaign,
    claim_next_delivery,
    create_campaign,
    finalize_claimed_campaign,
    get_campaign_detail,
    list_campaigns,
    list_delivery_records,
    mark_due_campaigns_budget_blocked,
    prepare_campaign,
    schedule_campaign,
    settle_delivery_attempt,
    update_campaign,
)


DEFAULT_LIFF_ID = "2010848330-UAiqPPYD"
DEFAULT_LEGACY_LIFF_ID = "2010674803-rK98c0lo"
DEFAULT_LINE_LOGIN_CHANNEL_ID = "2010848330"
DAILY_PEACE_LOGO_URL = "https://alive-checkin.onrender.com/assets/daily-peace-logo.png"

DEFAULT_CARD_TEMPLATE = {
    "id": "daily-peace-default",
    "name": "æ¯æ—¥å¹³å®‰é è¨­å¡",
    "system": True,
    "blessing": "æ¯ä¸€å¤©çš„å¹³å®‰ï¼Œéƒ½æ˜¯çµ¦å®¶äººæœ€å¥½çš„ç¦®ç‰©ã€‚",
    "hero_url": "https://alive-checkin.onrender.com/assets/daily-care/morning-warm.webp",
    "logo_url": DAILY_PEACE_LOGO_URL,
    "blessing_style": {
        "font_family": "rounded",
        "color": "#166534",
        "size": 34,
        "align": "center",
        "position": "top",
    },
    "buttons": [
        {"label": "âœ… æˆ‘å¹³å®‰", "action": "checkin"},
        {"label": "ğŸ›¡ï¸ å®‰å…¨å®ˆè­·", "uri": "https://alive-checkin.onrender.com/liff/checkin.html?open=guard"},
        {"label": "éœ€è¦å¹«å¿™", "uri": "https://alive-checkin.onrender.com/liff/sos.html"},
        {"label": "ğŸ”” ä»Šæ—¥å®‰å¿ƒæé†’", "uri": "https://alive-checkin.onrender.com/daily-care.html"},
    ],
}


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
    "reminder_times": ["12:00"],
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
    "push_campaigns": [],
    "push_campaign_versions": [],
    "push_delivery_records": [],
    "push_campaign_events": [],
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
        "daily_reminders": 1,
        "default_daily_reminders": 1,
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
        "default_daily_reminders": 1,
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
        "default_daily_reminders": 1,
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
        "default_daily_reminders": 2,
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
        "default_daily_reminders": 2,
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
            "Aï¼šæ ¸å¿ƒï¼å¯æ”¶ LINE é€šçŸ¥ï¼›ç·Šæ€¥è¯çµ¡äººï¼é›»è©±å‚™æ´ï¼Œä¸æœƒè‡ªå‹•æ”¶åˆ°ç³»çµ±é€šçŸ¥ã€‚\n\n"
            "Qï¼šå®ˆè­·äººä¸€å®šè¦è¨»å†Šå—ï¼Ÿ\n"
            "Aï¼šä¸ç”¨ï¼Œå°æ–¹åŠ å…¥å®˜æ–¹å¸³è™Ÿä¸¦é»é‚€è«‹åŒæ„å³å¯ã€‚\n\n"
            f"å®Œæ•´å•èˆ‡ç­”ï¼š{faq_url}\n"
            f"æŸ¥çœ‹æ–¹æ¡ˆï¼š{pricing_url}"
        )
    if any(keyword in text for keyword in SUPPORT_KEYWORDS):
        faq_url = line_liff_url("faq")
        return (
            "éœ€è¦å®¢æœå”åŠ©æ™‚ï¼Œè«‹åˆ°æœƒå“¡ä¸­å¿ƒå¡«å¯«å•é¡Œï¼Œæˆ–å¯„åˆ° alivecheckin.tw@gmail.comã€‚\n\n"
            "ğŸ“© æˆ‘å€‘æœƒåœ¨ 1â€“3 å€‹å·¥ä½œå¤©å…§å›è¦†ï¼Œä¸¦ä»¥ Email å¯„åˆ°ä½ çš„ä¿¡ç®±ã€‚\n\n"
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
    state["push_campaigns"] = state.get("push_campaigns") or []
    state["push_campaign_versions"] = state.get("push_campaign_versions") or []
    state["push_delivery_records"] = state.get("push_delivery_records") or []
    state["push_campaign_events"] = state.get("push_campaign_events") or []
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
    if str(profile.get("membership_source") or "") != "beta":
        catalog_label = (PAYMENT_PRODUCTS.get(str(profile.get("plan") or "")) or {}).get(
            "display_name"
        )
        if catalog_label:
            label = catalog_label
    days = info.get("days_left")
    is_upgrade = (
        str(profile.get("plan") or "") == "trial"
        or str(profile.get("membership_source") or "") == "beta"
    )
    action_word = "å‡ç´š" if is_upgrade else "çºŒè¨‚"
    nickname = str(profile.get("display_name") or profile.get("name") or "").strip()
    greeting_name = "" if not nickname or is_placeholder_display_name(nickname) else nickname[:20]
    greeting = (
        f"{greeting_name}ï¼Œè¬è¬æ‚¨é€™æ®µæ™‚é–“çš„æ”¯æŒ"
        if greeting_name
        else "æ‚¨å¥½ï¼Œè¬è¬æ‚¨é€™æ®µæ™‚é–“çš„æ”¯æŒ"
    )
    if isinstance(days, int) and days < 0:
        title = f"æ‚¨çš„ã€Œ{label}ã€å·²åˆ°æœŸ"
        countdown = "å·²åˆ°æœŸ"
        body = (
            f"{action_word}å¾Œï¼Œæ¯æ—¥å•å€™èˆ‡å®ˆè­·æœå‹™å¯ç¹¼çºŒä½¿ç”¨ï¼Œ"
            "åŸæœ‰å®ˆè­·è¨­å®šä»æœƒä¿ç•™ã€‚"
        )
    elif days == 0:
        title = f"æ‚¨çš„ã€Œ{label}ã€ä»Šå¤©åˆ°æœŸ"
        countdown = "ä»Šå¤©åˆ°æœŸ"
        body = (
            f"ä»Šå¤©æ˜¯æ–¹æ¡ˆæœ€å¾Œä¸€å¤©ã€‚{action_word}å¾Œï¼Œ"
            "æ¯æ—¥å•å€™èˆ‡å®ˆè­·æœå‹™å°‡æŒçºŒä¸ä¸­æ–·ã€‚"
        )
    elif days == 1:
        title = f"æ‚¨çš„ã€Œ{label}ã€å³å°‡åˆ°æœŸ"
        countdown = "æ˜å¤©æœ€å¾Œä¸€å¤©"
        body = (
            f"æ˜å¤©æ˜¯æœ€å¾Œä¸€å¤©ã€‚{action_word}å¾Œç¹¼çºŒäº«æœ‰æ¯æ—¥å•å€™èˆ‡å®‰å…¨å®ˆè­·ã€‚"
        )
    elif days == 3:
        title = f"æ‚¨çš„ã€Œ{label}ã€å³å°‡åˆ°æœŸ"
        countdown = "é‚„æœ‰ 4 å¤©"
        body = (
            f"å°‡åœ¨ 4 å¤©å¾Œåˆ°æœŸã€‚{action_word}å¾Œå¯ä¿ç•™æ‚¨çš„é€£çºŒå ±åˆ°å¤©æ•¸èˆ‡å®ˆè­·è¨­å®šã€‚"
        )
    elif days == 7:
        title = f"æ‚¨çš„ã€Œ{label}ã€å³å°‡åˆ°æœŸ"
        countdown = "é‚„æœ‰ 8 å¤©"
        body = (
            f"å°‡åœ¨ 8 å¤©å¾Œåˆ°æœŸã€‚{action_word}å¾Œï¼Œæ¯æ—¥å•å€™èˆ‡å®ˆè­·æœå‹™å°‡æŒçºŒä¸ä¸­æ–·ã€‚"
            "æå‰é€šçŸ¥ï¼Œæ–¹ä¾¿å®¶äººä¸€èµ·æ±ºå®šã€‚"
        )
    else:
        title = f"æ‚¨çš„ã€Œ{label}ã€å³å°‡åˆ°æœŸ"
        countdown = f"é‚„æœ‰ {max(1, int(days or 0) + 1)} å¤©"
        body = (
            f"å°‡åœ¨ {max(1, int(days or 0) + 1)} å¤©å¾Œåˆ°æœŸã€‚"
            f"{action_word}å¾Œï¼Œæ¯æ—¥å•å€™èˆ‡å®ˆè­·æœå‹™å°‡æŒçºŒä¸ä¸­æ–·ã€‚"
        )
    pricing_uri = f"{pricing_direct_url()}&from=expiry_reminder"
    return {
        "type": "flex",
        "altText": title,
        "contents": {
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#FFF7ED",
                "paddingAll": "xl",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "alignItems": "center",
                        "contents": [
                            {
                                "type": "image",
                                "url": public_page_url("assets/daily-peace-logo.png"),
                                "size": "xs",
                                "aspectMode": "fit",
                                "aspectRatio": "1:1",
                                "flex": 0,
                            },
                            {
                                "type": "text",
                                "text": "æ¯æ—¥å¹³å®‰",
                                "color": "#334155",
                                "size": "md",
                                "weight": "bold",
                                "margin": "sm",
                                "gravity": "center",
                            },
                        ],
                    },
                    {
                        "type": "text",
                        "text": greeting,
                        "color": "#334155",
                        "size": "lg",
                        "weight": "bold",
                        "wrap": True,
                    },
                    {
                        "type": "text",
                        "text": label,
                        "color": "#64748B",
                        "size": "sm",
                        "wrap": True,
                    },
                ],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "paddingAll": "xl",
                "contents": [
                    {
                        "type": "box",
                        "layout": "vertical",
                        "backgroundColor": "#ECFDF5",
                        "cornerRadius": "xl",
                        "paddingAll": "lg",
                        "contents": [
                            {
                                "type": "text",
                                "text": countdown,
                                "size": "xxl",
                                "weight": "bold",
                                "align": "center",
                                "color": "#047857",
                                "wrap": True,
                            },
                            {
                                "type": "text",
                                "text": title,
                                "size": "sm",
                                "align": "center",
                                "color": "#475569",
                                "wrap": True,
                                "margin": "sm",
                            },
                        ],
                    },
                    {
                        "type": "text",
                        "text": body,
                        "size": "md",
                        "color": "#334155",
                        "wrap": True,
                    },
                    {
                        "type": "separator",
                        "color": "#E2E8F0",
                        "margin": "sm",
                    },
                    {
                        "type": "text",
                        "text": "ğŸ’¬ æ‚¨çš„æ¯ä¸€å€‹æ„Ÿå—éƒ½å¾ˆé‡è¦ï¼Œä¹Ÿæ­¡è¿åˆ†äº«ä½¿ç”¨æ„Ÿå—èˆ‡å»ºè­°ï¼Œè®“æˆ‘å€‘åšå¾—æ›´è²¼å¿ƒã€‚",
                        "size": "sm",
                        "color": "#64748B",
                        "wrap": True,
                    },
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
                            "label": "ç¹¼çºŒå®‰å¿ƒå®ˆè­·",
                            "uri": pricing_uri,
                        },
                        "style": "primary",
                        "color": "#059669",
                        "height": "md",
                    },
                    {
                        "type": "button",
                        "action": {
                            "type": "postback",
                            "label": "ä¸å†æé†’",
                            "data": "action=expiry_opt_out",
                            "displayText": "è¬è¬æé†’ï¼Œå…ˆä¸ç”¨å†æé†’æˆ‘æ–¹æ¡ˆåˆ°æœŸ",
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
    return (
        "ğŸ’› è¬è¬æ‚¨å‘Šè¨´æˆ‘å€‘ï¼Œä¹‹å¾Œä¸æœƒå†æé†’æ–¹æ¡ˆåˆ°æœŸã€‚\n\n"
        "åŸæœ‰çš„å¹³å®‰ç´€éŒ„èˆ‡å®ˆè­·è¨­å®šæœƒä¾æœå‹™è¦å‰‡ä¿ç•™ï¼›å¦‚æœä¹‹å¾Œæƒ³ç¹¼çºŒä½¿ç”¨ï¼Œ"
        "éš¨æ™‚å›ä¾†æŸ¥çœ‹æ–¹æ¡ˆå°±å¯ä»¥ã€‚ä¹Ÿè¬è¬æ‚¨æ›¾è®“æ¯æ—¥å¹³å®‰é™ªä¼´æ‚¨èˆ‡å®¶äººã€‚"
    )


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
    "beta_reset_pending",
    "beta_reset_origin_cohort",
    "account_state_version",
    "location",
    "location_source",
    "location_updated_at",
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
    if not plan_has_calendar_notes(profile):
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
    if not plan_has_calendar_notes(profile):
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
        return normalize_reminder_times([single], max_count) or default_reminder_times_for_count(default_daily_reminder_count(profile))
    return default_reminder_times_for_count(default_daily_reminder_count(profile))


def default_daily_reminder_count(profile):
    rules = plan_rules(profile)
    max_count = max(1, min(3, int(rules.get("daily_reminders") or 1)))
    configured = rules.get("default_daily_reminders")
    if configured is None:
        configured = min(max_count, 2)
    return max(1, min(max_count, int(configured or 1)))


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
        normalized = default_reminder_times_for_count(default_daily_reminder_count(profile))
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


def guardian_binding_reminder_day(profile, now):
    """Return the 1-based day in the current unbound episode."""
    raw_start = (
        (profile or {}).get("guardian_unbound_since")
        or (profile or {}).get("beta_started_at")
        or (profile or {}).get("trial_started_at")
        or (profile or {}).get("membership_started_at")
        or (profile or {}).get("paid_at")
        or (profile or {}).get("created_at")
    )
    started = parse_datetime(raw_start)
    if not started:
        return 1
    comparable_now, comparable_started = _comparable_datetimes(now, started)
    return max(1, (comparable_now.date() - comparable_started.date()).days + 1)


def guardian_binding_reminder_due(profile, now):
    """Apply the selected per-plan cadence while the member has zero guardians."""
    day = guardian_binding_reminder_day(profile, now)
    source = str((profile or {}).get("membership_source") or "").lower()
    cohort = str((profile or {}).get("beta_cohort") or "").upper()
    if source == "beta" or cohort in {"B399", "B799"}:
        return day in {2, 4, 6, 8, 10, 13, 16, 19}
    if str((profile or {}).get("plan") or "") in {"paid_399_year", "paid_799_year"}:
        return day in {3, 7, 14, 21}
    return day <= 14


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
    pending_invites = pending_guardian_invite_count(state, line_user_id)
    completed_steps = {
        # æ­¤ API åªæœ‰å®Œæˆ LINE ç™»å…¥ä¸¦å»ºç«‹å¾Œç«¯æœƒå“¡å¾Œæ‰èƒ½å–å¾—ã€‚
        "line_login": bool(profile),
        "profile_and_reminder": bool(
            profile.get("onboarding_reminder_configured")
        ),
        # å¾Œç«¯ç¢ºå¯¦æœ‰å¾…æ¥å—é‚€è«‹ï¼Œæˆ–å·²å®Œæˆç¶å®šï¼Œæ‰ç®—åˆ†äº«æ­¥é©Ÿå®Œæˆã€‚
        "guardian_invite_sent": bool(pending_invites or access["home_ready"]),
        "guardian_bound": bool(access["home_ready"]),
    }
    if not completed_steps["profile_and_reminder"]:
        current_step = 3
    elif not completed_steps["guardian_invite_sent"]:
        current_step = 4
    else:
        current_step = 5
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
        "default_daily_reminders": default_daily_reminder_count(profile) if profile else 1,
        "daily_checkin_reminder_enabled": bool(
            profile.get("daily_checkin_reminder_enabled", True)
        ),
        # é¦–æ¬¡ç¶å®šä¾æ–¹æ¡ˆé è¨­ï¼š199ï¼399 ä¸€æ¬¡ï¼›799 å…©æ¬¡ã€‚æœƒå“¡ä¸­å¿ƒä»å¯èª¿åˆ°æ–¹æ¡ˆä¸Šé™ã€‚
        "default_reminder_times": default_reminder_times_for_count(default_daily_reminder_count(profile) if profile else 1),
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
        "user_location": {
            "city": str((profile.get("location") or {}).get("city") or "").strip(),
            "district": str((profile.get("location") or {}).get("district") or "").strip(),
        },
        "location_configured": bool(
            str((profile.get("location") or {}).get("city") or "").strip()
            and str((profile.get("location") or {}).get("district") or "").strip()
        ),
    }, 200


def update_member_location(data_file, line_user_id, payload, *, source="member"):
    """Save a coarse Taiwan location without collecting an address or GPS."""
    line_user_id = str(line_user_id or "").strip()
    city = str((payload or {}).get("city") or "").strip()
    district = str((payload or {}).get("district") or "").strip()
    if not line_user_id:
        return {"ok": False, "error": "missing line_user_id"}, 400
    if not city or not district:
        return {
            "ok": False,
            "error": "location_required",
            "message": "è«‹é¸æ“‡ç¸£å¸‚èˆ‡é„‰é®å¸‚å€",
        }, 400
    if len(city) > 12 or len(district) > 20:
        return {"ok": False, "error": "invalid_location"}, 400
    source = "admin" if source == "admin" else "member"
    state = load_state(data_file)
    profile = (state.get("users") or {}).get(line_user_id)
    if not isinstance(profile, dict):
        return {"ok": False, "error": "user not registered"}, 404
    profile["location"] = {"city": city, "district": district}
    profile["location_source"] = source
    profile["location_updated_at"] = datetime.now().isoformat(timespec="seconds")
    save_state(data_file, state)
    return {
        "ok": True,
        "user_location": dict(profile["location"]),
        "location_source": source,
        "location_updated_at": profile["location_updated_at"],
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
    if profile.get("beta_reset_pending"):
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
        if paid_until is None:
            return True
        comparable_now, comparable_paid_until = _comparable_datetimes(now, paid_until)
        return comparable_now < comparable_paid_until
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
    if str(profile.get("plan") or "") == "trial":
        return "paid_199" if membership_access_active(profile, now) else "free"
    if beta_access_active(profile, now):
        return BETA_COHORT_PLAN.get(str(profile.get("beta_cohort") or ""), "paid_399")
    if str(profile.get("membership_source") or "") == "beta":
        return "free"
    plan = str(profile.get("plan") or "free")
    if plan.startswith("paid_") and not membership_access_active(profile, now):
        return "free"
    return plan


def sos_delivery_mode(profile, now=None):
    """Return the server-authoritative SOS delivery mode for current rights."""
    return "web_only" if effective_entitlement_plan(profile, now) == "free" else "immediate"


def push_audience_code(profile, now=None):
    """å›å‚³æœƒå“¡åœ¨æŒ‡å®šæ™‚é–“å”¯ä¸€ä¸”å¯ç”¨çš„æ¨æ’­å—çœ¾ä»£ç¢¼ã€‚"""
    if not isinstance(profile, dict):
        return None
    now = now or current_app_time({})
    source = str(profile.get("membership_source") or "")
    if source == "beta":
        if not beta_access_active(profile, now):
            return None
        cohort = str(profile.get("beta_cohort") or "").upper()
        return cohort if cohort in {"A", "B399", "B799"} else None
    if source == "gift":
        if str(profile.get("gift_code") or "").upper() != "G799":
            return None
        started = parse_datetime(profile.get("gift_started_at"))
        ends = parse_datetime(profile.get("gift_ends_at"))
        if not started or not ends:
            return None
        comparable_now, comparable_start = _comparable_datetimes(now, started)
        comparable_now, comparable_end = _comparable_datetimes(comparable_now, ends)
        return "G799" if comparable_start <= comparable_now < comparable_end else None
    plan = str(profile.get("plan") or "free")
    if plan == "trial":
        return "trial" if membership_access_active(profile, now) else None
    if not plan.startswith("paid_"):
        return None
    if profile.get("expiry_review_required"):
        return None
    if str(profile.get("payment_status") or "") != "active":
        return None
    return plan if membership_access_active(profile, now) else None


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
        str(profile.get("plan") or "").startswith("paid_")
        and str(profile.get("payment_status") or "") == "active"
    ):
        raise ValueError("paid_member_not_beta_eligible")
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
    """Build one caring daily beta check-in with three clear reply paths."""
    day = max(1, min(BETA_TRIAL_DAYS, int(day or 1)))
    cohort = str((profile or {}).get("beta_cohort") or "B399").upper()
    buttons = [
        ("âœ… ä¸€åˆ‡é †åˆ©", "normal", "#168C65"),
        ("âš ï¸ æœ‰é‡åˆ°å•é¡Œ", "issue", "#C2413A"),
        ("ğŸ’¬ åˆ†äº«å¿ƒå¾—", "insight", "#3178C6"),
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
                    {"type": "text", "text": "ä»Šå¤©ç”¨èµ·ä¾†é‚„é †åˆ©å—ï¼Ÿ",
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
                    {"type": "text", "text": "å¦‚æœæœ‰ä»»ä½•å¡ä½çš„åœ°æ–¹ï¼Œæˆ–æ˜¯æœ‰æƒ³åˆ†äº«çš„å¿ƒå¾—ï¼Œéƒ½å¯ä»¥ç›´æ¥å›è¦†è·Ÿæˆ‘èªªå–”ã€‚",
                     "wrap": True, "margin": "lg", "size": "sm", "color": "#52625D"},
                    {"type": "text", "text": "é»é¸ä¸‹æ–¹æœ€ç¬¦åˆçš„ç‹€æ³ï¼š",
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
            or str(profile.get("payment_status") or "") == "active"
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
    "sos_recipient_reminder",
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
            profile["guarding_for"] = [
                value for value in (profile.get("guarding_for") or [])
                if str(value or "").strip() != peer_id
            ]
            profile["guarding_details"] = [
                row for row in (profile.get("guarding_details") or [])
                if str(
                    (row or {}).get("line_user_id")
                    or (row or {}).get("line_id")
                    or (row or {}).get("user_id")
                    or ""
                ).strip() != peer_id
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
    if str(profile.get("membership_source") or "") == "beta":
        cohort = str(profile.get("beta_cohort") or "").strip().upper()
        beta_plan = BETA_COHORT_PLAN.get(cohort, plan)
        beta_label = {
            "paid_399_year": "399 å¹´è²»ï½œ21 å¤©å°æ¸¬",
            "paid_799_year": "799 å¹´è²»ï½œ21 å¤©å°æ¸¬",
        }.get(beta_plan)
        if beta_label:
            return beta_label
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

    _reminder_times = [] if profile.get("beta_reset_pending") else reminder_times_for_profile(profile)
    if not _reminder_times and not profile.get("beta_reset_pending"):
        _reminder_times = ["12:00"]
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
    active_guarding_for = []
    raw_guarding_for = [
        str(value or "").strip()
        for value in (profile.get("guarding_for") or [])
        if str(value or "").strip()
    ]

    def is_active_guarding_peer(peer_id):
        if state is None:
            return True
        peer = (state.get("users") or {}).get(peer_id)
        if not isinstance(peer, dict):
            return False
        return any(
            get_contact_line_id(contact) == owner_id
            and resolve_contact_role(contact) == "guardian"
            and (
                contact_is_bound_guardian(contact, peer_id)
                or bool(contact.get("bound"))
            )
            for contact in (peer.get("contacts") or [])
            if isinstance(contact, dict)
        )

    for peer_id in raw_guarding_for:
        if peer_id not in active_guarding_for and is_active_guarding_peer(peer_id):
            active_guarding_for.append(peer_id)

    for raw_detail in profile.get("guarding_details") or []:
        if not isinstance(raw_detail, dict):
            continue
        detail = dict(raw_detail)
        peer_id = str(
            detail.get("line_user_id")
            or detail.get("line_id")
            or detail.get("user_id")
            or ""
        ).strip()
        if not peer_id or not is_active_guarding_peer(peer_id):
            continue
        if peer_id not in active_guarding_for:
            active_guarding_for.append(peer_id)
        peer = ((state or {}).get("users") or {}).get(peer_id) or {}
        peer_times = reminder_times_for_profile(peer) if peer else []
        detail["reminder_times"] = peer_times
        detail["today_status"] = (
            "å·²å ±å¹³å®‰" if peer and profile_is_today_checked(peer, now=now)
            else "å°šæœªå ±å¹³å®‰"
        )
        detail["latest_sos_status"] = ""
        detail["latest_sos_message"] = ""
        detail["latest_sos_created_at"] = ""
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
                if peer_events[0].get("delivery_mode") == "web_only":
                    detail["latest_sos_message"] = str(peer_events[0].get("message") or "")
                    detail["latest_sos_created_at"] = str(peer_events[0].get("created_at") or "")
        guarding_details.append(detail)

    streak_days = compute_streak_days(profile.get("history") or [], today)
    level_context = streak_level_context(
        streak_days, profile.get("highest_streak_days") or streak_days
    )
    return {
        "ok": True,
        **access,
        "line_user_id": profile.get("line_user_id"),
        "display_name": profile.get("display_name", ""),
        "picture_url": profile.get("picture_url", ""),
        "user_location": {
            "city": str((profile.get("location") or {}).get("city") or "").strip(),
            "district": str((profile.get("location") or {}).get("district") or "").strip(),
        },
        "weather": copy.deepcopy(profile.get("weather") or {}),
        "daily_blessing": checkin_blessing_text(now),
        "is_onboarding_completed": bool(profile.get("is_onboarding_completed")),
        "onboarding_reminder_configured": bool(
            profile.get("onboarding_reminder_configured")
        ),
        "streak_days": streak_days,
        "highest_streak_days": int(profile.get("highest_streak_days") or streak_days),
        "streak_restarted": bool(profile.get("streak_restarted")),
        "streak_level": level_context,
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
        "reminder_time": _reminder_times[0] if _reminder_times else "",
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
        "guarding_for": active_guarding_for,
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
        "beta_reset_pending": bool(profile.get("beta_reset_pending")),
        "account_state_version": str(profile.get("account_state_version") or "legacy"),
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
        "default_daily_reminders": default_daily_reminder_count(profile),
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
        "calendar_notes_enabled": plan_has_calendar_notes(profile),
        "smart_reminders_enabled": plan_has_smart_reminders(profile),
        "safety_guard_hours": allowed_safety_guard_hours(profile),
        "guardian_group_ids": profile.get("guardian_group_ids", []),
        "guardian_groups": guardian_groups,
        "guardian_group_default_preferences": normalize_guardian_group_preferences(
            profile.get("guardian_group_preferences")
        ),
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
    if str(profile.get("membership_source") or "") == "beta":
        return plan_type_label(profile)
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
    if str(profile.get("membership_source") or "") == "beta":
        return f"{_membership_label(profile)}ï½œå°æ¸¬ä½¿ç”¨ä¸­"
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
    beta_reset_pending = bool((existing or {}).get("beta_reset_pending"))
    if beta_reset_pending and requested_beta and str((existing or {}).get("beta_reset_origin_cohort") or "").upper() == "A":
        return {"ok": False, "error": "a_cohort_requires_admin_reassignment"}, 409
    user = get_profile(
        state,
        line_user_id,
        start_public_trial=not beta_reset_pending and not bool(requested_beta) and not guardian_only,
    )
    user.pop("test_reset_pending", None)
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
        if not user.get("onboarding_reminder_configured"):
            user["reminder_times"] = default_reminder_times_for_count(
                default_daily_reminder_count(user)
            )
            user["reminder_time"] = user["reminder_times"][0]
        if beta_reset_pending:
            user["beta_reset_pending"] = False
            user["reminder_time"] = ""
            user["reminder_times"] = []
            user["daily_checkin_reminder_enabled"] = False
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
    current_streak = compute_streak_days(profile.get("history") or [], today)
    previous_highest = int(profile.get("highest_streak_days") or 0)
    profile["streak_restarted"] = bool(
        not already_checked and current_streak == 1 and previous_highest > 1
    )
    profile["highest_streak_days"] = max(previous_highest, current_streak)
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
        for day in (7, 11, 13, 14):
            if elapsed_days != day or day in completed:
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
        beta_end = parse_datetime(profile.get("beta_ends_at"))
        if not beta_end:
            return []
        days_left = (beta_end.date() - now.date()).days
        return [day for day in (7, 3, 1, 0) if days_left == day]
    if plan == "trial":
        started = parse_datetime(profile.get("trial_started_at"))
        if not started:
            return []
        elapsed = max(0, (now.date() - started.date()).days)
        return [day for day in (7, 11, 13, 14) if elapsed == day]
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
            message["altText"] = "14 å¤©å®‰å¿ƒé«”é©—å°‡åœ¨ 8 å¤©å¾Œåˆ°æœŸ"
        elif day == 11:
            message["altText"] = "14 å¤©å®‰å¿ƒé«”é©—å°‡åœ¨ 4 å¤©å¾Œåˆ°æœŸ"
        elif day == 13:
            message["altText"] = "14 å¤©å®‰å¿ƒé«”é©—æ˜å¤©æ˜¯æœ€å¾Œä¸€å¤©"
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


def membership_activation_time(profile):
    """Return the start of the member's current trial, beta, or paid period."""
    source = str((profile or {}).get("membership_source") or "").strip()
    plan = str((profile or {}).get("plan") or "").strip()
    if source == "beta":
        return parse_datetime(profile.get("beta_started_at"))
    if plan == "trial":
        return parse_datetime(profile.get("trial_started_at"))
    if not plan.startswith("paid_"):
        return None
    explicit = parse_datetime(profile.get("membership_started_at"))
    if explicit:
        return explicit
    paid_until = parse_datetime(profile.get("paid_until"))
    product = PAYMENT_PRODUCTS.get(plan) or {}
    duration_days = int(
        product.get("duration_days") or (365 if "year" in plan else 30)
    )
    return paid_until - timedelta(days=duration_days) if paid_until else None


def _week_one_card_variant(profile):
    """Return the visual and copy variant for a member's current entitlement."""
    profile = profile or {}
    plan = str(profile.get("plan") or "trial")
    if str(profile.get("membership_source") or "") == "beta":
        return {
            "label": "21 å¤©å®‰å¿ƒå®ˆè­·å°æ¸¬", "color": "#8B6BCB", "soft": "#F4EFFB",
            "icon": "âœ¨", "title": "è¬è¬æ‚¨é™ªæˆ‘å€‘å®Œæˆç¬¬ä¸€é€±",
            "copy": "æ‚¨çš„æ¯ä¸€æ¬¡ä½¿ç”¨èˆ‡å»ºè­°ï¼Œéƒ½åœ¨å¹«åŠ©æ¯æ—¥å¹³å®‰è®Šå¾—æ›´è²¼è¿‘å®¶äººçš„éœ€è¦ã€‚",
            "primary": "ğŸ›¡ï¸ ç¹¼çºŒå®‰å¿ƒå®ˆè­·", "path": "/liff/member.html?from=week_one_beta",
        }
    family = "trial" if plan == "trial" else plan.split("_")[1] if plan.startswith("paid_") else "trial"
    variants = {
        "trial": {
            "label": "14 å¤©å®‰å¿ƒé«”é©—", "color": "#F7B84B", "soft": "#FFF7E5",
            "icon": "ğŸŒ·", "title": "æ‚¨å·²ç¶“ä½¿ç”¨ä¸€é€±äº†",
            "copy": "è¬è¬æ‚¨è®“æ¯æ—¥å¹³å®‰é™ªä¼´æ‚¨å’Œå®¶äººé€™ 7 å¤©ã€‚æ¯å¤©è¼•è¼•æŒ‰ä¸€ä¸‹ï¼Œå°±æ˜¯çµ¦å®¶äººæœ€å®‰å¿ƒçš„å•å€™ã€‚",
            "primary": "ğŸ’š ä»Šå¤©ä¹Ÿè¦å ±å¹³å®‰", "path": "/?from=week_one_trial",
        },
        "199": {
            "label": "199 å¹³å®‰ç‰ˆ", "color": "#4FAF83", "soft": "#EAF7F1",
            "icon": "ğŸŒ¿", "title": "å®‰å¿ƒå®ˆè­·æ»¿ä¸€é€±äº†",
            "copy": "è¬è¬æ‚¨æŒçºŒç”¨æ¯å¤© 10 ç§’ï¼Œè®“é‡è¦çš„äººçŸ¥é“æ‚¨å¹³å®‰ã€‚ä»Šå¤©ä¹Ÿè¨˜å¾—é€å‡ºä¸€ä»½å®‰å¿ƒå•å€™å–”ï¼",
            "primary": "ğŸ’š æˆ‘ä»Šå¤©å¹³å®‰", "path": "/?from=week_one_199",
        },
        "399": {
            "label": "399 å®‰å¿ƒç‰ˆ", "color": "#E59B45", "soft": "#FFF3E4",
            "icon": "ğŸ’›", "title": "é€™ä¸€é€±è¾›è‹¦äº†",
            "copy": "æ¯å¤©çš„ä¸€æ¬¡å›æ‡‰ï¼Œä¸åªæ˜¯ç´€éŒ„ï¼Œæ›´æ˜¯è®“å®ˆè­·äººæ”¾å¿ƒçš„æº«æš–è¨Šæ¯ã€‚è¬è¬æ‚¨æŒçºŒé™ªä¼´å®¶äººã€‚",
            "primary": "ğŸ’š å‚³é€ä»Šæ—¥å¹³å®‰", "path": "/?from=week_one_399",
        },
        "799": {
            "label": "799 å®ˆè­·ç‰ˆ", "color": "#4776C6", "soft": "#EDF3FC",
            "icon": "ğŸ¡", "title": "æ‚¨çš„å®‰å¿ƒå®ˆè­·å·²æŒçºŒä¸€é€±",
            "copy": "å®ˆè­·ç¾¤ã€æ—¥æœŸæé†’èˆ‡å®‰å…¨å®ˆè­·éƒ½ç‚ºæ‚¨æº–å‚™å¥½äº†ï¼Œè®“å®¶äººçš„é—œå¿ƒæ›´å®Œæ•´ï¼Œå¹³å¸¸ä¹Ÿä¸äº’ç›¸æ‰“æ“¾ã€‚",
            "primary": "âœ¨ ç¹¼çºŒå®ˆè­·å®¶äºº", "path": "/liff/member.html?from=week_one_799",
        },
    }
    return variants.get(family, variants["trial"])


def build_day7_pin_reminder_flex(profile=None):
    """Build the personalized, plan-aware week-one LINE Flex card."""
    profile = profile or {}
    variant = _week_one_card_variant(profile)
    nickname = str(
        profile.get("display_name") or profile.get("nickname") or profile.get("name") or ""
    ).strip() or "æ‚¨å¥½"
    public_url = (os.environ.get("APP_PUBLIC_URL") or "https://alive-checkin.onrender.com").rstrip("/")
    return {
        "type": "flex",
        "altText": f"{nickname}ï¼Œ{variant['label']}ä½¿ç”¨ä¸€é€±çš„å°æé†’",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": variant["color"],
                "paddingAll": "20px",
                "contents": [
                    {
                        "type": "text",
                        "text": f"{variant['icon']} ä½¿ç”¨ä¸€é€±çš„å°æé†’",
                        "color": "#FFFFFF",
                        "weight": "bold",
                        "size": "xl",
                    },
                    {
                        "type": "text", "text": variant["label"], "color": "#FFFFFF",
                        "size": "sm", "margin": "sm", "weight": "bold",
                    },
                ],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": variant["soft"],
                "paddingAll": "20px",
                "contents": [
                    {
                        "type": "text",
                        "text": f"{nickname}ï¼Œ{variant['title']}",
                        "wrap": True,
                        "weight": "bold", "size": "lg", "color": "#27352F",
                    },
                    {
                        "type": "text",
                        "text": variant["copy"],
                        "wrap": True,
                        "margin": "md", "size": "md", "color": "#46554F",
                    },
                    {
                        "type": "text",
                        "text": "ä¹Ÿæ­¡è¿å‘Šè¨´æˆ‘å€‘æ‚¨çš„ä½¿ç”¨æ„Ÿå—ï¼Œè®“æ¯æ—¥å¹³å®‰åšå¾—æ›´è²¼å¿ƒ ğŸ’›",
                        "wrap": True, "margin": "lg", "size": "sm", "color": "#68736F",
                    },
                ],
            },
            "footer": {
                "type": "box", "layout": "vertical", "spacing": "sm", "paddingAll": "16px",
                "contents": [
                    {
                        "type": "button", "style": "primary", "height": "sm",
                        "color": variant["color"],
                        "action": {"type": "uri", "label": variant["primary"], "uri": public_url + variant["path"]},
                    },
                    {
                        "type": "button", "style": "secondary", "height": "sm",
                        "action": {"type": "uri", "label": "ğŸ’¬ æä¾›å»ºè­°", "uri": public_url + "/help.html?from=week_one"},
                    },
                ],
            },
        },
    }


def _day7_pin_qualification_key(profile, activated_at):
    return "|".join(
        (
            str(profile.get("plan") or ""),
            str(profile.get("membership_source") or ""),
            activated_at.isoformat(timespec="seconds"),
        )
    )


def _day7_pin_membership_is_active(profile, clock):
    source = str((profile or {}).get("membership_source") or "").strip()
    plan = str((profile or {}).get("plan") or "").strip()
    if source == "beta":
        return beta_access_active(profile, clock)
    if plan == "trial":
        return trial_days_left(profile, now=clock) > 0
    if plan.startswith("paid_"):
        return paid_membership_is_active(profile, now=clock)
    return False


def send_day7_pin_reminders(config, now=None):
    """Send one personalized Flex card to memberships reaching week one."""
    if config.get("LEGACY_DAY7_PIN_REMINDER_ENABLED") is False:
        return {"sent": 0, "failed": 0, "skipped": 0, "reason": "legacy_scheduler_retired"}, 200
    clock = now or current_app_time(config)
    state = load_state(config["DATA_FILE"])
    enabled_at = parse_datetime(state.get("day7_flex_reminder_enabled_at"))
    if not enabled_at:
        state["day7_flex_reminder_enabled_at"] = clock.isoformat(timespec="seconds")
        save_state(config["DATA_FILE"], state)
        return {
            "sent": 0,
            "failed": 0,
            "skipped": 0,
            "reason": "feature_initialized",
        }, 200
    token = config.get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get(
        "LINE_CHANNEL_ACCESS_TOKEN", ""
    )
    if not token:
        return {
            "sent": 0,
            "failed": 0,
            "skipped": 0,
            "error": "LINE_CHANNEL_ACCESS_TOKEN is not set",
        }, 400
    sender = config.get("LINE_PUSH_SENDER") or line_push_message
    sent = 0
    failed = 0
    skipped = 0
    results = []
    for profile in (state.get("users") or {}).values():
        target = str(profile.get("line_user_id") or "").strip()
        activated_at = membership_activation_time(profile)
        if (
            not target
            or not activated_at
            or not _day7_pin_membership_is_active(profile, clock)
        ):
            skipped += 1
            continue
        due_at = activated_at + timedelta(days=7)
        comparable_due, comparable_clock = _comparable_datetimes(due_at, clock)
        comparable_enabled, _ = _comparable_datetimes(enabled_at, clock)
        if comparable_due < comparable_enabled or comparable_clock < comparable_due:
            skipped += 1
            continue
        qualification_key = _day7_pin_qualification_key(profile, activated_at)
        completed = set(profile.get("day7_pin_reminder_keys_sent") or [])
        if qualification_key in completed:
            skipped += 1
            continue
        message = build_day7_pin_reminder_flex(profile)
        retry_key = _line_retry_key(
            f"day7-pin-reminder:{target}:{qualification_key}"
        )
        status = "sent"
        detail = ""
        try:
            _send_line_with_retry_key(sender, token, target, message, retry_key)
            completed.add(qualification_key)
            profile["day7_pin_reminder_keys_sent"] = sorted(completed)
            sent += 1
        except Exception as exc:
            status = "failed"
            detail = str(exc)[:400]
            failed += 1
        append_notification_log(
            state,
            "day7_pin_reminder",
            target,
            status,
            message.get("altText") or "ç¬¬ 7 å¤© LINE ç½®é ‚æé†’",
            detail,
            metadata={
                "plan": str(profile.get("plan") or ""),
                "membership_source": str(profile.get("membership_source") or ""),
                "beta_cohort": str(profile.get("beta_cohort") or ""),
                "scheduled_at": due_at.isoformat(timespec="seconds"),
                "sent_at": clock.isoformat(timespec="seconds"),
            },
        )
        results.append({
            "line_user_id": target,
            "plan": str(profile.get("plan") or ""),
            "scheduled_at": due_at.isoformat(timespec="seconds"),
            "status": status,
        })
    save_state(config["DATA_FILE"], state)
    return {
        "sent": sent,
        "failed": failed,
        "skipped": skipped,
        "results": results,
    }, 200


def remove_retired_push_uids(data_file, config):
    """Remove explicitly retired deployment-test recipients from saved state."""
    raw = config.get("RETIRED_LINE_USER_IDS") or (
        "U_deploy_smoke_ax,Ua723c8919f544d515422f143d1710b74"
    )
    retired = {
        value.strip()
        for value in re.split(r"[,;ï¼›\s]+", str(raw))
        if value.strip()
    }

    def mutate(state):
        users = state.get("users") or {}
        removed = 0
        for key, profile in list(users.items()):
            target = str((profile or {}).get("line_user_id") or key).strip()
            if key in retired or target in retired:
                users.pop(key, None)
                removed += 1
        state["users"] = users
        return {"removed": removed}

    return mutate_state_atomically(data_file, mutate)


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
        requested_role = resolve_contact_role(contact)
        for c in existing:
            if str(c.get("id") or "") == contact_id:
                continue
            # åŒä¸€äººå¯ä»¥åŒæ™‚æ˜¯æ ¸å¿ƒå®ˆè­·äººèˆ‡é›»è©±å‚™æ´ç·Šæ€¥è¯çµ¡äººï¼›
            # åªæœ‰åŒä¸€åˆ†é¡å…§çš„é‡è¤‡è³‡æ–™æ‰æ‡‰æ“‹ä¸‹ã€‚
            if resolve_contact_role(c) != requested_role:
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
    role = resolve_contact_role(cleaned)
    same_role = [c for c in existing if resolve_contact_role(c) == role]
    cleaned["priority"] = len(same_role) + 1
    # ç¬¬ä¸€ä½å®ˆè­·äººè‡ªå‹•æˆç‚ºä¸»è¦å®ˆè­·äººï¼›ä¹‹å¾Œåªæœ‰æœƒå“¡æ˜ç¢ºæŒ‡å®šæ™‚æ‰æ›¿æ›ã€‚
    # ç·Šæ€¥è¯çµ¡äººæ˜¯ç¨ç«‹åˆ†é¡ï¼Œä¸å¾—å› èª¿æ•´ä¸»è¦å®ˆè­·äººè€Œè¢«å–æ¶ˆæ¨™è¨˜ã€‚
    if role == "guardian" and not same_role:
        cleaned["is_primary"] = True
    if role == "guardian" and cleaned["is_primary"]:
        for c in existing:
            if resolve_contact_role(c) != "guardian":
                continue
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
        had_bound_guardian = profile_has_bound_line_guardian(profile)
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
        peer = (state.get("users") or {}).get(peer_id) if peer_id else None
        legacy_reciprocal_evidence = bool(
            isinstance(peer, dict)
            and (
                line_user_id in {
                    str(value or "").strip()
                    for value in (peer.get("guarding_for") or [])
                }
                or any(
                    get_contact_line_id(contact) == line_user_id
                    and resolve_contact_role(contact) == "guardian"
                    and (
                        contact_is_bound_guardian(contact, peer_id)
                        or contact.get("bound") is True
                    )
                    for contact in (peer.get("contacts") or [])
                )
            )
        )
        is_reciprocal_guardian = bool(
            peer_id
            and resolve_contact_role(removed) == "guardian"
            and (
                contact_is_bound_guardian(removed, line_user_id)
                or removed.get("bound") is True
                or legacy_reciprocal_evidence
            )
        )
        profile["contacts"] = [
            contact
            for contact in existing
            if str(contact.get("id") or "") != contact_id
        ]
        if had_bound_guardian and not profile_has_bound_line_guardian(profile):
            profile["guardian_unbound_since"] = iso_now()
            profile["contact_reminder_sent_dates"] = []
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
            if isinstance(peer, dict):
                peer["contacts"] = [
                    contact
                    for contact in (peer.get("contacts") or [])
                    if get_contact_line_id(contact) != line_user_id
                ]
                if not profile_has_bound_line_guardian(peer):
                    peer["guardian_unbound_since"] = iso_now()
                    peer["contact_reminder_sent_dates"] = []
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
    ):
        return {
            "ok": False,
            "error": "è«‹å¡«å¯«æœ¬äººå§“ååŠèˆ‡é‚€è«‹äººçš„é—œä¿‚å¾Œå†å®Œæˆç¶å®šï¼›é›»è©±å¯ä¸å¡«",
            "code": "guardian_profile_required",
            "required_fields": ["name", "relationship"],
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

    bound_contact = next(
        (row for row in contacts if get_contact_line_id(row) == contact_line_user_id),
        None,
    )
    if bound_contact is not None and pending_invite:
        bound_contact["accepted_invite_id"] = pending_invite.get("id") or ""
        bound_contact["invited_at"] = pending_invite.get("created_at") or ""
        bound_contact["accepted_at"] = pending_invite.get("accepted_at") or bound_contact.get("accepted_at") or accepted_at

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
    inviter.pop("guardian_unbound_since", None)

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
            "invited_at": (pending_invite or {}).get("created_at") or "",
            "accepted_at": (pending_invite or {}).get("accepted_at") or accepted_at,
            "accepted_invite_id": (pending_invite or {}).get("id") or "",
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
        if pending_invite:
            reward["invited_at"] = reward.get("invited_at") or pending_invite.get("created_at") or ""
            reward["accepted_at"] = reward.get("accepted_at") or pending_invite.get("accepted_at") or accepted_at
            reward["accepted_invite_id"] = reward.get("accepted_invite_id") or pending_invite.get("id") or ""

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
    permanent_delivery_start = len(state.get("push_delivery_records") or [])
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
    permanent_deliveries = copy.deepcopy(
        (state.get("push_delivery_records") or [])[permanent_delivery_start:]
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
            _merge_permanent_delivery_rows(latest, permanent_deliveries)
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
    prefs.setdefault("daily_summary_time", "20:00")
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
        "default_preferences": normalize_guardian_group_preferences(
            profile.get("guardian_group_preferences")
        ),
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


def can_view_guardian_group_status(state, group, line_user_id) -> bool:
    """Allow an admin or an accepted guardian in this LINE group to view status.

    notify_admin_only controls names included in pushed summaries. It must not
    block an invited guardian who actively signs in and opens the status page.
    Mere LINE group membership is never sufficient.
    """
    uid = str(line_user_id or "").strip()
    if not uid or not isinstance(group, dict):
        return False
    if is_guardian_group_admin(group, uid):
        return True
    users = (state or {}).get("users") or {}
    if uid not in users:
        return False
    group_member_ids = {
        str(value or "").strip()
        for value in (group.get("member_ids_at_bind") or [])
        if str(value or "").strip()
    }
    if uid not in group_member_ids:
        return False
    owner_id = str(group.get("owner_line_user_id") or "").strip()
    owner = users.get(owner_id) or {}
    return any(
        get_contact_line_id(contact) == uid
        and resolve_contact_role(contact) == "guardian"
        and contact_is_bound_guardian(contact, owner_id)
        for contact in (owner.get("contacts") or [])
    )


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
        "preferences": normalize_guardian_group_preferences(
            profile.get("guardian_group_preferences")
        ),
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
    profile = (state.get("users") or {}).get(line_user_id)
    if not profile:
        return {"error": "user not registered"}, 404
    if group_id == "__default__":
        if not plan_includes_guardian_group(profile):
            return {"error": "guardian group plan required"}, 403
        preferences = normalize_guardian_group_preferences(
            profile.get("guardian_group_preferences")
        )
        for key in DEFAULT_GUARDIAN_GROUP_PREFERENCES:
            if key in payload:
                preferences[key] = bool(payload.get(key))
        if "daily_summary_time" in payload:
            summary_time = str(payload.get("daily_summary_time") or "").strip()
            if not REMINDER_TIME_PATTERN.match(summary_time):
                return {"error": "invalid daily_summary_time format, use HH:MM"}, 400
            preferences["daily_summary_time"] = summary_time
        profile["guardian_group_preferences"] = preferences
        save_state(data_file, state)
        return {
            "ok": True,
            "group_id": group_id,
            "preferences": preferences,
        }, 200

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


def guardian_group_daily_status(data_file, line_user_id, group_id, now=None):
    if not line_user_id or not group_id:
        return {"error": "missing line_user_id or group_id"}, 400

    state = load_state(data_file)
    group = state.get("guardian_groups", {}).get(group_id)
    if not group or group.get("status") != "active":
        return {"error": "guardian group not found"}, 404
    if not can_view_guardian_group_status(state, group, line_user_id):
        return {"error": "guardian group status forbidden"}, 403

    users = state.get("users", {}) or {}
    owner_id = str(group.get("owner_line_user_id") or "").strip()
    member_ids = [owner_id]
    for uid in group.get("member_ids_at_bind") or []:
        if uid and uid in users and uid not in member_ids:
            member_ids.append(uid)
    now = now or datetime.now()
    today = now.strftime("%Y-%m-%d")
    members = []
    for uid in member_ids:
        profile = users.get(uid)
        if not isinstance(profile, dict):
            continue
        name = profile.get("display_name") or profile.get("name") or "æ¯æ—¥å¹³å®‰æœƒå“¡"
        if uid == owner_id:
            name = f"{name}ï¼ˆç®¡ç†å“¡ï¼‰"
        checked = _member_checked_today(profile, today)
        reminder_times = reminder_times_for_profile(profile) or ["12:00"]
        latest_reminder = max(reminder_times)
        overdue = not checked and now.strftime("%H:%M") > latest_reminder
        members.append({
            "line_user_id": uid,
            "name": name,
            "status": "checked" if checked else ("overdue" if overdue else "pending"),
            "status_label": (
                "ä»Šæ—¥å·²å ±å¹³å®‰"
                if checked
                else ("å·²è¶…éè¨­å®šæ™‚é–“" if overdue else "å°šæœªå ±å¹³å®‰")
            ),
        })
    counts = {
        key: sum(1 for row in members if row["status"] == key)
        for key in ("checked", "pending", "overdue")
    }
    counts["total"] = len(members)
    return {
        "ok": True,
        "group_id": group_id,
        "group_name": group.get("group_name") or "å®ˆè­·ç¾¤",
        "date": today,
        "counts": counts,
        "members": members,
    }, 200


def guardian_group_daily_status_text(data_file, line_user_id, group_id):
    result, code = guardian_group_daily_status(data_file, line_user_id, group_id)
    if code != 200:
        messages = {
            400: "ç›®å‰ç„¡æ³•ç¢ºèªä½ çš„èº«åˆ†ï¼Œè«‹ç¨å¾Œå†è©¦ã€‚",
            403: "ä»Šæ—¥å¹³å®‰åå–®åªé–‹æ”¾å®ˆè­·ç¾¤ç®¡ç†å“¡åŠå·²æ¥å—é‚€è«‹çš„å®ˆè­·äººæŸ¥çœ‹ã€‚",
            404: "æ­¤ç¾¤å°šæœªå®Œæˆå®ˆè­·ç¾¤ç¶å®šã€‚è«‹ç”±æœ‰æ•ˆçš„ 799 æœƒå“¡åœ¨ç¾¤è£¡è¼¸å…¥ã€Œé»æˆ‘ç¶å®šå®ˆè­·ç¾¤ã€ã€‚",
        }
        return messages.get(code, "ç›®å‰ç„¡æ³•æŸ¥çœ‹å®ˆè­·ç¾¤ç‹€æ…‹ã€‚"), code
    checked = [row["name"] for row in result["members"] if row["status"] == "checked"]
    unchecked = [row["name"] for row in result["members"] if row["status"] in {"pending", "overdue"}]
    prefs = normalize_guardian_group_preferences(
        (load_state(data_file).get("guardian_groups", {}).get(group_id) or {}).get("preferences")
    )
    lines = [
        f"ğŸ“Š {result['group_name']}ä»Šæ—¥å¹³å®‰ç‹€æ…‹",
        f"å…± {result['counts']['total']} ä½æˆå“¡",
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
    daily_limit = int(plan_rules(profile).get("safety_guard_daily_limit") or 0)
    stored_usage_date = profile.get("safety_guard_usage_date") or profile.get("safety_guard_trial_usage_date")
    stored_usage_count = int(
        profile.get("safety_guard_usage_count")
        if profile.get("safety_guard_usage_count") is not None
        else profile.get("safety_guard_trial_usage_count") or 0
    )
    daily_used = stored_usage_count if stored_usage_date == today else 0
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
        "daily_limit": daily_limit,
        "daily_used": daily_used,
        "daily_remaining": max(0, daily_limit - daily_used),
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

    now = current_app_time(config or {})
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
            "daily_used": usage_count,
            "daily_remaining": 0,
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
    started_at = existing.get("started_at") if was_active else now.isoformat(timespec="seconds")
    if was_active:
        expires_at = existing.get("expires_at") or ""
        duration_hours = existing.get("duration_hours") or duration_hours
        until_stop = bool(existing.get("until_stop"))
    elif until_stop:
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
        "guardian_line_user_ids": list(existing.get("guardian_line_user_ids") or []) if was_active else [],
        "sharing": True,
        "active": True,
        "mode": "safety_guard",
    }
    # åŒä¸€å€‹é€²è¡Œä¸­çš„å·¥ä½œéšæ®µåªæ›´æ–°ä½ç½®ï¼Œä¸é‡è¤‡è¨ˆæ¬¡ï¼Œä¹Ÿä¸å†æ¬¡é€šçŸ¥å®ˆè­·äººã€‚
    if was_active:
        guardian_notify = {
            "sent": 0,
            "failed": 0,
            "target_count": len(profile["location"]["guardian_line_user_ids"]),
            "no_guardians": False,
            "reason_code": "active_session_updated",
            "message": "å·²æ›´æ–°ç›®å‰ä½ç½®ï¼Œæœ¬æ¬¡ä¸é‡è¤‡é€šçŸ¥å®ˆè­·äºº",
            "selected_target_ids": list(profile["location"]["guardian_line_user_ids"]),
        }
    else:
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
    selected_set = set(selected_ÛÎ{Ó†òµë(š+myÖVçEöF—7Æ•öæÖR%ÒÒ€¢ÖVÖ&W"ævWB‚&F—7Æ•öæÖR"’÷".iÊ®Xùn[é~i«z‹ ¢¢&÷u²'&V6—–VçE÷G—UöÆ&VÂ%ÒÒ$Ä”äRiÈ>Y: ¢VÆ–b—5÷FW7E÷F&vWC ¢&÷u²'&V6—–VçEöF—7Æ•öæÖR%ÒÒ.˜:{Û.kŠÎŠšnX~[‹>‰™ò ¢&÷u²'&V6—–VçE÷G—UöÆ&VÂ%ÒÒ.kŠÎŠšn‹8~iiûÈKˆŞiŠşyÉşZúniÈ>Y:ûÈ’ ¢VÆ–bÆ–æU÷W6W%ö–Bç7F'G7v—F‚‚$2"“ ¢&÷u²'&V6—–VçEöF—7Æ•öæÖR%ÒÒ$Ä”äRZèŠÛ~{êB ¢&÷u²'&V6—–VçE÷G—UöÆ&VÂ%ÒÒ$Ä”äR{êN{XB ¢VÇ6S ¢&÷u²'&V6—–VçEöF—7Æ•öæÖR%ÒÒ.iÊ®ˆ;Ş[ŞhxiÈ>Y:Zy>YÒ ¢&÷u²'&V6—–VçE÷G—UöÆ&VÂ%ÒÒ.iÊ®yú^iKnK»nˆR ¢–b&÷rævWB‚'7FGW2"’–â²&f–ÆVB"Â&W'&÷""Â&&Æö6¶VB'Ó ¢&÷rçWFFR…öFÖ–å÷W6…öf–ÇW&UöW‡ÆæF–öâ‡&÷rævWB‚&FWF–Â"’’¢VÇ6S ¢&÷u²&f–ÇW&U÷&V6öå÷¦‚%ÒÒ" ¢&÷u²&f–ÇW&Uö7F–öå÷¦‚%ÒÒ" ¢&÷w2æVæB‡&÷r¢&WGW&â&÷w0  ¦FVbFÖ–å÷7VÖÖ'’†FFöf–ÆRÂ6öæf–sÔæöæRÂæ÷sÔæöæR“ ¢7FFRÒÆöE÷7FFR†FFöf–ÆR¢7FGW5öæ÷rÒæ÷r÷"7W'&VçEö÷F–ÖR†6öæf–r÷"·Ò¢Fö¶VâÒ" ¢–b6öæf–r—2æ÷BæöæRæB†6GG"†6öæf–rÂ&vWB"“ ¢Fö¶VâÒ7G"†6öæf–rævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"’÷"""’ç7G&—‚¢–bæ÷BFö¶Vã ¢Fö¶VâÒ7G"†÷2æVçf—&öâævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"’÷"""’ç7G&—‚ ¢2[èÎXû‹ÈXZ^i˜.Š9Î›Ø®8ÄÄ”äRKÛşyJˆ^8ŞKÙNKØŞYŞz‹ûÈiÈZI®h™2CjÊÄ”äR&öf–Æ^ûÈÎ˜şXXŞ˜îi˜.ûÈ¢‡–G&FVBÒ ¢F—'G’ÒfÇ6P¢W‡—'•÷&Wf–WrÒ&6¶f–ÆÅöÖVÖ&W'6†—öW‡—'•÷&Wf–Ww2‡7FFRÂæ÷s×7FGW5öæ÷r¢–bW‡—'•÷&Wf–Wu²&&6¶f–ÆÆVB%Ò÷"W‡—'•÷&Wf–Wu²'&Wf–Wu÷&WV—&VB%Ó ¢F—'G’ÒG'VP¢f÷"W6W"–â‡7FFRævWB‚'W6W'2"’÷"·Ò’çfÇVW2‚“ ¢–b€¢7G"‡W6W"ævWB‚&ÖVÖ&W'6†—÷6÷W&6R"’÷"""’ÓÒ&&WF ¢æBæ÷B7G"‡W6W"ævWB‚&&WFöVæG5öB"’÷"""’ç7G&—‚¢“ ¢7F'FVBÒ'6UöFFWF–ÖR‡W6W"ævWB‚&&WF÷7F'FVEöB"’¢–bæ÷B7F'FVC ¢7F'FVBÒ7FGW5öæ÷p¢W6W%²&&WF÷7F'FVEöB%ÒÒ7F'FVBæ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"¢W6W%²&&WFöVæG5öB%ÒÒ€¢7F'FVB²F–ÖVFVÇF†F—3Ô$UDõE$”ÅôD•2¢’æ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"¢F—'G’ÒG'VP¢f÷"W6W"–â‡7FFRævWB‚'W6W'2"’÷"·Ò’çfÇVW2‚“ ¢–b‡–G&FVBãÒC ¢'&V°¢–bæ÷B—5÷Æ6V†öÆFW%öF—7Æ•öæÖR‡W6W"ævWB‚&F—7Æ•öæÖR"’“ ¢6öçF–çVP¢&Vf÷&RÒ7G"‡W6W"ævWB‚&F—7Æ•öæÖR"’÷"""¢Vç7W&U÷W6W%öF—7Æ•öæÖR‡W6W"ÂFö¶Vã×Fö¶Vâ¢–b7G"‡W6W"ævWB‚&F—7Æ•öæÖR"’÷"""’Ò&Vf÷&S ¢‡–G&FVB³Ò¢F—'G’ÒG'VP¢–bF—'G“ ¢6fU÷7FFR†FFöf–ÆRÂ7FFR ¢W6W'2ÒµĞ¢–çf—FUöVFvW2ÒµĞ¢66WFVEö–çf—FW2Ò°¢&÷rf÷"&÷r–â‡7FFRævWB‚&wV&F–åö–çf—FW2"’÷"µÒ¢–b—6–ç7Fæ6R‡&÷rÂF–7B’æB&÷rævWB‚'7FGW2"’ÓÒ&66WFVB ¢Ğ¢–çf—FW5ö'•ö–BÒ°¢7G"‡&÷rævWB‚&–B"’÷"""“¢&÷rf÷"&÷r–â66WFVEö–çf—FW2–b&÷rævWB‚&–B"¢Ğ ¢FVb66WFVEö–çf—FUöf÷"†–çf—FW%ö–BÂwV&F–åö–BÂ&V6÷&CÔæöæR“ ¢&V6÷&BÒ&V6÷&B÷"·Ğ¢–çf—FUö–BÒ7G"‡&V6÷&BævWB‚&66WFVEö–çf—FUö–B"’÷"&V6÷&BævWB‚&–çf—FUö–B"’÷"""¢–b–çf—FUö–BæB–çf—FUö–B–â–çf—FW5ö'•ö–C ¢&WGW&â–çf—FW5ö'•ö–E¶–çf—FUö–EĞ¢ÖF6†W2Ò°¢&÷rf÷"&÷r–â66WFVEö–çf—FW0¢–b7G"‡&÷rævWB‚&–çf—FW%öÆ–æU÷W6W%ö–B"’÷"""’ÓÒ7G"†–çf—FW%ö–B÷"""¢æB7G"‡&÷rævWB‚&–çf—FVUöÆ–æU÷W6W%ö–B"’÷"""’ÓÒ7G"†wV&F–åö–B÷"""¢Ğ¢&WGW&âÖF6†W5³Ò–bÆVâ†ÖF6†W2’ÓÒVÇ6RæöæP¢f÷"W6W"–â7FFRævWB‚'W6W'2"Â·Ò’çfÇVW2‚“ ¢7FGW2Ò'V–ÆE÷7FGW2‡W6W"Â7FFRÂæ÷s×7FGW5öæ÷r¢7FGW5²&W‡—'•÷&Wf–Wu÷&WV—&VB%ÒÒ&ööÂ‡W6W"ævWB‚&W‡—'•÷&Wf–Wu÷&WV—&VB"’¢7FGW5²&v–gEö6öFR%ÒÒ7G"‡W6W"ævWB‚&v–gEö6öFR"’÷"""¢7FGW5²&v–gE÷7F'FVEöB%ÒÒ7G"‡W6W"ævWB‚&v–gE÷7F'FVEöB"’÷"""¢7FGW5²&v–gEöVæG5öB%ÒÒ7G"‡W6W"ævWB‚&v–gEöVæG5öB"’÷"""¢7FGW5²&—5÷FW7Eö66÷VçB%ÒÒ7G"€¢7FGW2ævWB‚&Æ–æU÷W6W%ö–B"’÷"" ¢’–â6WB…÷FW7EöÆ–æU÷W6W%ö–G2†6öæf–r÷"·Ò’¢ÆFW7Eö6†V6¶–âÒ‡7FGW2ævWB‚&6†V6¶–å÷&V6÷&G2"’÷"µÒ•²Ó¥Ò÷"··ÕĞ¢7FGW5²&Æ7Eö6†V6¶–åö&V%ÒÒ7G"€¢ÆFW7Eö6†V6¶–å³ÒævWB‚&&V"¢÷"‡W6W"ævWB‚&Æö6F–öâ"’÷"·Ò’ævWB‚&6—G’"¢÷".iÊ®hùKé² ¢’ç7G&—‚¢2[èÎXûšşzK®YŞz‹ûÉ®{Y^KˆŞz›®y›ŞûÉ¾K¸ŞiŠşKÙNKØŞi˜.ˆ{>[	™˜NyúÒ”BikKëş‹êŠÙ€¢æÖRÒ7G"‡7FGW2ævWB‚&F—7Æ•öæÖR"’÷"""’ç7G&—‚¢–b—5÷Æ6V†öÆFW%öF—7Æ•öæÖR†æÖR“ ¢6†÷'BÒ7G"‡7FGW2ævWB‚&Æ–æU÷W6W%ö–B"’÷"""•²Óc¥Ò÷"#ò ¢7FGW5²&F—7Æ•öæÖR%ÒÒb.iÊ®Xùn[é~i«z‹ûÈ(
g·6†÷'GŞûÈ’ ¢7FGW5²&F—7Æ•öæÖUöÖ—76–ær%ÒÒG'VP¢VÇ6S ¢7FGW5²&F—7Æ•öæÖUöÖ—76–ær%ÒÒfÇ6P¢W6W'2æVæB‡7FGW2¢–çf—FW%ö–BÒ7FGW2ævWB‚&Æ–æU÷W6W%ö–B"’÷"" ¢–çf—FW%öæÖRÒ7FGW2ævWB‚&F—7Æ•öæÖR"’÷"" ¢f÷"6öçF7B–â7FGW2ævWB‚&6öçF7G2"’÷"µÓ ¢wV&F–åö–BÒvWEö6öçF7EöÆ–æUö–B†6öçF7B¢–bæ÷BwV&F–åö–C ¢6öçF–çVP¢–bwV&F–åö–BÓÒ–çf—FW%ö–C ¢6öçF–çVP¢ÖF6†VEö–çf—FRÒ66WFVEö–çf—FUöf÷"†–çf—FW%ö–BÂwV&F–åö–BÂ6öçF7B¢–çf—FVEöBÒ7G"†6öçF7BævWB‚&–çf—FVEöB"’÷"†ÖF6†VEö–çf—FR÷"·Ò’ævWB‚&7&VFVEöB"’÷"""’ç7G&—‚¢66WFVEöBÒ7G"†6öçF7BævWB‚&66WFVEöB"’÷"†ÖF6†VEö–çf—FR÷"·Ò’ævWB‚&66WFVEöB"’÷"""’ç7G&—‚¢–çf—FUöVFvW2æVæB€¢°¢&–çf—FW%öÆ–æU÷W6W%ö–B#¢–çf—FW%ö–BÀ¢&–çf—FW%öF—7Æ•öæÖR#¢–çf—FW%öæÖRÀ¢&wV&F–åöÆ–æU÷W6W%ö–B#¢wV&F–åö–BÀ¢&wV&F–åöF—7Æ•öæÖR#¢6öçF7BævWB‚&æÖR"’÷"""À¢&&–æF–æu÷7FGW2#¢6öçF7BævWB‚&&–æF–æu÷7FGW2"’÷"""À¢&–çf—FVEöB#¢–çf—FVEöB÷".ˆˆ®‹8~iiiÊ®Š‰˜ÈB"À¢&66WFVEöB#¢66WFVEöB÷".ˆˆ®‹8~iiiÊ®Š‰˜ÈB"À¢Ğ¢¢W6W'2ç6÷'B†¶W“ÖÆÖ&F—FVÓ¢†æ÷B—FVÕ²&—5ö÷fW&GVR%ÒÂ—FVÒævWB‚&F—7Æ•öæÖR"’÷"""’¢W6W'5ö'•ö–BÒ°¢7G"‡W6W"ævWB‚&Æ–æU÷W6W%ö–B"’÷"""“¢W6W ¢f÷"W6W"–âW6W'0¢–bW6W"ævWB‚&Æ–æU÷W6W%ö–B"¢Ğ¢F–Ç•÷W6…÷&÷w2Ò·Ğ¢W'6—7FVEöF–Ç•÷W6†W2Ò7FFRævWB‚&F–Ç•÷W6…öÖVÖ&W%÷7FG2"’÷"·Ğ¢–b—6–ç7Fæ6R‡W'6—7FVEöF–Ç•÷W6†W2ÂF–7B“ ¢f÷"¶W’Â—FVÒ–âW'6—7FVEöF–Ç•÷W6†W2æ—FV×2‚“ ¢–b—6–ç7Fæ6R†—FVÒÂF–7B“ ¢F–Ç•÷W6…÷&÷w5·7G"†¶W’•ÒÒF–7B†—FVÒ¢2&6¶f–ÆÂ&V6VçBÆVv7’Æöw2F†B&VFFRF†RW'6—7FVçBF–Ç’6÷VçFW'2à¢f÷"Æör–â7FFRævWB‚&æ÷F–f–6F–öåöÆöw2"’÷"µÓ ¢Æ–æU÷W6W%ö–BÒ7G"†ÆörævWB‚&Æ–æU÷W6W%ö–B"’÷"""’ç7G&—‚¢7&VFVEöBÒ7G"†ÆörævWB‚&7&VFVEöB"’÷"""¢FFRÒ7&VFVEöE³£Ğ¢–bæ÷BÆ–æU÷W6W%ö–B÷"ÆVâ†FFR’Ò ¢6öçF–çVP¢¶W’Òb'¶FFW×Ç¶Æ–æU÷W6W%ö–GÒ ¢–b¶W’–âF–Ç•÷W6…÷&÷w3 ¢6öçF–çVP¢ÖF6†–ærÒ°¢&÷p¢f÷"&÷r–â‡7FFRævWB‚&æ÷F–f–6F–öåöÆöw2"’÷"µÒ¢–b7G"‡&÷rævWB‚&Æ–æU÷W6W%ö–B"’÷"""’ç7G&—‚’ÓÒÆ–æU÷W6W%ö–@¢æB7G"‡&÷rævWB‚&7&VFVEöB"’÷"""•³£ÒÓÒFFP¢Ğ¢F–Ç•÷W6…÷&÷w5¶¶W•ÒÒ°¢&FFR#¢FFRÀ¢&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–BÀ¢'6VçEö6÷VçB#¢7VÒƒf÷"&÷r–âÖF6†–ær–b&÷rævWB‚'7FGW2"’ÓÒ'6VçB"’À¢&f–ÆVEö6÷VçB#¢7VÒ€¢f÷"&÷r–âÖF6†–ær–b&÷rævWB‚'7FGW2"’–â²&f–ÆVB"Â&W'&÷""Â&&Æö6¶VB'Ğ¢’À¢'F÷FÅö6÷VçB#¢ÆVâ†ÖF6†–ær’À¢&¶–æG2#¢6÷'FVB‡°¢7G"‡&÷rævWB‚&¶–æB"’÷"&÷F†W""’f÷"&÷r–âÖF6†–æp¢Ò’À¢&Æ7E÷W6…öB#¢Ö‚€¢‡7G"‡&÷rævWB‚&7&VFVEöB"’÷"""’f÷"&÷r–âÖF6†–ær’À¢FVfVÇCÒ""À¢’À¢&ÆFW7Eöf–ÇW&UöFWF–Â#¢æW‡B€¢€¢7G"‡&÷rævWB‚&FWF–Â"’÷"""•³£SĞ¢f÷"&÷r–â6÷'FVB€¢ÖF6†–ærÀ¢¶W“ÖÆÖ&F&÷s¢7G"‡&÷rævWB‚&7&VFVEöB"’÷"""’À¢&WfW'6SÕG'VRÀ¢¢–b&÷rævWB‚'7FGW2"’–â²&f–ÆVB"Â&W'&÷""Â&&Æö6¶VB'Ğ¢æB7G"‡&÷rævWB‚&FWF–Â"’÷"""’ç7G&—‚¢’À¢""À¢’À¢&ÆFW7Eöf–ÇW&UöB#¢æW‡B€¢€¢7G"‡&÷rævWB‚&7&VFVEöB"’÷"""¢f÷"&÷r–â6÷'FVB€¢ÖF6†–ærÀ¢¶W“ÖÆÖ&F&÷s¢7G"‡&÷rævWB‚&7&VFVEöB"’÷"""’À¢&WfW'6SÕG'VRÀ¢¢–b&÷rævWB‚'7FGW2"’–â²&f–ÆVB"Â&W'&÷""Â&&Æö6¶VB'Ğ¢’À¢""À¢’À¢Ğ¢F–Ç•÷W6…öÖVÖ&W%÷7FG2ÒµĞ¢f÷"—FVÒ–âF–Ç•÷W6…÷&÷w2çfÇVW2‚“ ¢ÖVÖ&W"ÒW6W'5ö'•ö–BævWB‡7G"†—FVÒævWB‚&Æ–æU÷W6W%ö–B"’÷"""’Â·Ò¢–bæ÷B7G"†—FVÒævWB‚&ÆFW7Eöf–ÇW&UöFWF–Â"’÷"""’ç7G&—‚“ ¢ÖF6†–æuöf–ÇW&W2Ò°¢&÷p¢f÷"&÷r–â‡7FFRævWB‚&æ÷F–f–6F–öåöÆöw2"’÷"µÒ¢–b7G"‡&÷rævWB‚&Æ–æU÷W6W%ö–B"’÷"""’ç7G&—‚¢ÓÒ7G"†—FVÒævWB‚&Æ–æU÷W6W%ö–B"’÷"""’ç7G&—‚¢æB7G"‡&÷rævWB‚&7&VFVEöB"’÷"""•³£Ğ¢ÓÒ7G"†—FVÒævWB‚&FFR"’÷"""¢æB&÷rævWB‚'7FGW2"’–â²&f–ÆVB"Â&W'&÷""Â&&Æö6¶VB'Ğ¢Ğ¢–bÖF6†–æuöf–ÇW&W3 ¢ÆFW7Eöf–ÇW&RÒÖ‚€¢ÖF6†–æuöf–ÇW&W2À¢¶W“ÖÆÖ&F&÷s¢7G"‡&÷rævWB‚&7&VFVEöB"’÷"""’À¢¢—FVÕ²&ÆFW7Eöf–ÇW&UöFWF–Â%ÒÒ7G"€¢ÆFW7Eöf–ÇW&RævWB‚&FWF–Â"’÷"" ¢•³£SĞ¢—FVÕ²&ÆFW7Eöf–ÇW&UöB%ÒÒ7G"€¢ÆFW7Eöf–ÇW&RævWB‚&7&VFVEöB"’÷"" ¢¢f–ÇW&UöW‡ÆæF–öâÒöFÖ–å÷W6…öf–ÇW&UöW‡ÆæF–öâ€¢—FVÒævWB‚&ÆFW7Eöf–ÇW&UöFWF–Â"¢’–b–çB†—FVÒævWB‚&f–ÆVEö6÷VçB"’÷"’VÇ6R°¢&f–ÇW&U÷&V6öå÷¦‚#¢""À¢&f–ÇW&Uö7F–öå÷¦‚#¢""À¢Ğ¢F–Ç•÷W6…öÖVÖ&W%÷7FG2æVæB‡°¢¢¦—FVÒÀ¢&F—7Æ•öæÖR#¢ÖVÖ&W"ævWB‚&F—7Æ•öæÖR"’÷".iÊ®Xùn[é~i«z‹"À¢'Æâ#¢ÖVÖ&W"ævWB‚'Æâ"’÷"&g&VR"À¢&W‡—&W5öB#¢ÖVÖ&W"ævWB‚'ÆåöW‡—&W5öB"’÷"""À¢&ÆFW7Eöf–ÇW&U÷&V6öå÷¦‚#¢f–ÇW&UöW‡ÆæF–öå²&f–ÇW&U÷&V6öå÷¦‚%ÒÀ¢&ÆFW7Eöf–ÇW&Uö7F–öå÷¦‚#¢f–ÇW&UöW‡ÆæF–öå²&f–ÇW&Uö7F–öå÷¦‚%ÒÀ¢Ò¢F–Ç•÷W6…öÖVÖ&W%÷7FG2ç6÷'B€¢¶W“ÖÆÖ&F—FVÓ¢†—FVÒævWB‚&FFR"’÷"""Â—FVÒævWB‚&Æ7E÷W6…öB"’÷"""’À¢&WfW'6SÕG'VRÀ¢¢wV&F–åöw&÷W2ÒÆ—7B‡7FFRævWB‚&wV&F–åöw&÷W2"Â·Ò’çfÇVW2‚’¢wV&F–åöw&÷W2ç6÷'B†¶W“ÖÆÖ&F—FVÓ¢—FVÒævWB‚&7&VFVEöB"Â""’Â&WfW'6SÕG'VR¢÷&FW'2ÒÆ—7B‡&WfW'6VB‡7FFRævWB‚&÷&FW'2"ÂµÒ•²Ó¥Ò’¢–Eö÷&FW'2Ò¶÷&FW"f÷"÷&FW"–â÷&FW'2–b÷&FW"ævWB‚'7FGW2"’ÓÒ'–B%Ğ¢6÷VçG•÷&÷w2Ò·Ğ ¢FVb6÷VçG•÷&÷r†6÷VçG’“ ¢&WGW&â6÷VçG•÷&÷w2ç6WFFVfVÇB€¢6÷VçG’÷".iÊ®hùKé²"À¢²&6÷VçG’#¢6÷VçG’÷".iÊ®hùKé²"Â&ÖVÖ&W'2#¢Â&÷&FW'2#¢Â'–Eö÷&FW'2#¢Â'&WfVçVR#¢ÒÀ¢ ¢f÷"&öf–ÆR–â7FFRævWB‚'W6W'2"Â·Ò’çfÇVW2‚“ ¢ÆFW7BÒ°¢&÷rf÷"&÷r–â‡&öf–ÆRævWB‚&6†V6¶–å÷&V6÷&G2"’÷"µÒ¢–b—6–ç7Fæ6R‡&÷rÂF–7B¢Ğ¢6÷VçG’Ò7G"€¢†ÆFW7E²ÓÒævWB‚&&V"’–bÆFW7BVÇ6R""¢÷"‡&öf–ÆRævWB‚&Æö6F–öâ"’÷"·Ò’ævWB‚&6—G’"¢÷".iÊ®hùKé² ¢’ç7G&—‚¢6÷VçG•÷&÷r†6÷VçG’•²&ÖVÖ&W'2%Ò³Ò ¢f÷"÷&FW"–â÷&FW'3 ¢&öf–ÆRÒ7FFRævWB‚'W6W'2"Â·Ò’ævWB†÷&FW"ævWB‚&Æ–æU÷W6W%ö–B"’Â·Ò¢ÆFW7BÒ°¢&÷rf÷"&÷r–â‡&öf–ÆRævWB‚&6†V6¶–å÷&V6÷&G2"’÷"µÒ¢–b—6–ç7Fæ6R‡&÷rÂF–7B¢Ğ¢6÷VçG’Ò7G"€¢†ÆFW7E²ÓÒævWB‚&&V"’–bÆFW7BVÇ6R""¢÷"‡&öf–ÆRævWB‚&Æö6F–öâ"’÷"·Ò’ævWB‚&6—G’"¢÷".iÊ®hùKé² ¢’ç7G&—‚¢&÷rÒ6÷VçG•÷&÷r†6÷VçG’¢&÷u²&÷&FW'2%Ò³Ò¢–b÷&FW"ævWB‚'7FGW2"’ÓÒ'–B# ¢&÷u²'–Eö÷&FW'2%Ò³Ò¢&÷u²'&WfVçVR%Ò³Ò–çB†÷&FW"ævWB‚&Ö÷VçB"’÷" ¢6÷VçG•÷7FG2Ò6÷'FVB€¢6÷VçG•÷&÷w2çfÇVW2‚’À¢¶W“ÖÆÖ&F—FVÓ¢‚Ö—FVÕ²'&WfVçVR%ÒÂÖ—FVÕ²&ÖVÖ&W'2%ÒÂ—FVÕ²&6÷VçG’%Ò’À¢¢W'6—7BÒW'6—7FVæ6Uö–æfò†FFöf–ÆR¢wV&F–åö–çf—FW2ÒµĞ¢f÷"&÷r–â&WfW'6VB‚‡7FFRævWB‚&wV&F–åö–çf—FW2"’÷"µÒ•²Ó¥Ò“ ¢–bæ÷B—6–ç7Fæ6R‡&÷rÂF–7B“ ¢6öçF–çVP¢wV&F–åö–çf—FW2æVæB‡°¢&–B#¢&÷rævWB‚&–B"’÷"""À¢&–çf—FW%öÆ–æU÷W6W%ö–B#¢&÷rævWB‚&–çf—FW%öÆ–æU÷W6W%ö–B"’÷"""À¢&F—7Æ•öæÖR#¢&÷rævWB‚&F—7Æ•öæÖR"’÷"""À¢'&VÆF–öç6†—#¢&÷rævWB‚'&VÆF–öç6†—"’÷"""À¢'7FGW2#¢&÷rævWB‚'7FGW2"’÷"""À¢&7&VFVEöB#¢&÷rævWB‚&7&VFVEöB"’÷"""À¢&W‡—&W5öB#¢&÷rævWB‚&W‡—&W5öB"’÷"""À¢&66WFVEöB#¢&÷rævWB‚&66WFVEöB"’÷"""À¢&–çf—FVUöÆ–æU÷W6W%ö–B#¢&÷rævWB‚&–çf—FVUöÆ–æU÷W6W%ö–B"’÷"""À¢Ò¢V÷FÒ–çB‚†6öæf–r÷"·Ò’ævWB‚$Ä”äUôÔôåD„Å•ôÔU54tUõTõD"’÷"÷2æVçf—&öâævWB‚$Ä”äUôÔôåD„Å•ôÔU54tUõTõD"’÷"#¢Æ–æU÷W6vRÒÖöçF†Ç•öÆ–æUöÖW76vU÷W6vR€¢7FFRÂ7FGW5öæ÷rç7G&gF–ÖR‚"U’ÒVÒ"’ÂV÷FÂ7FGW5öæ÷p¢¢6öçF7E÷&Wv&G2ÒµĞ¢f÷"&Wv&B–â&WfW'6VB‡7FFRævWB‚&6öçF7E÷&Wv&G2"ÂµÒ•²Ó#¥Ò“ ¢–bæ÷B—6–ç7Fæ6R‡&Wv&BÂF–7B“ ¢6öçF–çVP¢&÷rÒF–7B‡&Wv&B¢ÖF6†VEö–çf—FRÒ66WFVEö–çf—FUöf÷"€¢&÷rævWB‚&–çf—FW%öÆ–æU÷W6W%ö–B"’Â&÷rævWB‚&6öçF7EöÆ–æU÷W6W%ö–B"’Â&÷p¢¢&÷u²&–çf—FVEöB%ÒÒ7G"‡&÷rævWB‚&–çf—FVEöB"’÷"†ÖF6†VEö–çf—FR÷"·Ò’ævWB‚&7&VFVEöB"’÷"""’ç7G&—‚’÷".ˆˆ®‹8~iiiÊ®Š‰˜ÈB ¢&÷u²&66WFVEöB%ÒÒ7G"‡&÷rævWB‚&66WFVEöB"’÷"†ÖF6†VEö–çf—FR÷"·Ò’ævWB‚&66WFVEöB"’÷"""’ç7G&—‚’÷".ˆˆ®‹8~iiiÊ®Š‰˜ÈB ¢6öçF7E÷&Wv&G2æVæB‡&÷r ¢&WGW&â°¢'F÷FÅ÷W6W'2#¢ÆVâ‡W6W'2’À¢&÷fW&GVU÷W6W'2#¢7VÒƒf÷"W6W"–âW6W'2–bW6W%²&—5ö÷fW&GVR%Ò’À¢'v&æ–æu÷W6W'2#¢7VÒƒf÷"W6W"–âW6W'2–bW6W%²'7FGW5ö6Æ72%ÒÓÒ'v&æ–ær"’À¢&6†V6¶VE÷FöF’#¢7VÒƒf÷"W6W"–âW6W'2–bW6W%²&—5÷FöF•ö6†V6¶VB%Ò’À¢&wV&F–åöw&÷Wö6÷VçB#¢ÆVâ†wV&F–åöw&÷W2’À¢&wV&F–åöw&÷W2#¢wV&F–åöw&÷W2À¢&&÷VæEöwV&F–å÷F÷FÂ#¢7VÒ†–çB‡W6W"ævWB‚&&÷VæEöwV&F–åö6÷VçB"’÷"’f÷"W6W"–âW6W'2’À¢&–çf—FUöVFvW2#¢Æ—7B‡&WfW'6VB†–çf—FUöVFvW5²Ó¥Ò’’À¢&wV&F–åö–çf—FW2#¢wV&F–åö–çf—FW2À¢&wV&F–åö–çf—FUö6÷VçG2#¢°¢7FGW3¢7VÒƒf÷"&÷r–âwV&F–åö–çf—FW2–b&÷rævWB‚'7FGW2"’ÓÒ7FGW2¢f÷"7FGW2–â‚'VæF–ær"Â&66WFVB"Â&W‡—&VB"¢ÒÀ¢&÷&FW'2#¢÷&FW'2À¢'–Eö÷&FW%ö6÷VçB#¢ÆVâ‡–Eö÷&FW'2’À¢'–E÷&WfVçVR#¢7VÒ†–çB†÷&FW"ævWB‚&Ö÷VçB"’÷"’f÷"÷&FW"–â–Eö÷&FW'2’À¢'VæF–æuö÷&FW%ö6÷VçB#¢7VÒƒf÷"÷&FW"–â÷&FW'2–b÷&FW"ævWB‚'7FGW2"’ÓÒ'VæF–ær"’À¢&6÷VçG•÷7FG2#¢6÷VçG•÷7FG2À¢'W6W'2#¢W6W'2À¢&6öçF7E÷&Wv&G2#¢6öçF7E÷&Wv&G2À¢&æ÷F–f–6F–öåöÆöw2#¢öFÖ–åöæ÷F–f–6F–öåöÆöw2‡7FFRÂW6W'5ö'•ö–B’À¢&F–Ç•÷W6…öÖVÖ&W%÷7FG2#¢F–Ç•÷W6…öÖVÖ&W%÷7FG5³£SÒÀ¢&Æ–æUöÖW76vU÷W6vR#¢Æ–æU÷W6vRÀ¢&F—7Æ•öæÖW5ö‡–G&FVB#¢‡–G&FVBÀ¢'W'6—7FVæ6R#¢W'6—7BÀ¢Ğ  ¥ôÔ”u$D”ôåôDÔ”åô4õTåEô´U•2Ò€¢&6†V6¶–ç2"À¢&6öçF7G2"À¢&w&÷W2"À¢'&VÖ–æFW'2"À¢&÷&FW'2"À¢'&WVW7G2"À¢¥ôÔ”u$D”ôåôDÔ”åôd”ÅU$Uô4DTtõ$”U2Ò°¢""À¢&–çfÆ–Eö6öFR"À¢&W‡—&VEö6öFR"À¢'W6VEö6öFR"À¢'6÷W&6UöÖ—76–ær"À¢'Vç6fUö6öæfÆ–7B"À¢&Ö–w&F–öåöf–ÆVB"À§Ğ  ¦FVbFÖ–åö66÷VçEöÖ–w&F–öç2†FFöf–ÆRÂ6öæf–rÂæ÷sÔæöæR“ ¢""%&WGW&â&VBÖöæÇ’ÂÆÆ÷vÆ—7FVB÷W&F–öæÂÖ–w&F–öâ7VÖÖ'’â"" ¢7FFRÒÆöE÷7FFR†FFöf–ÆR¢7W'&VçBÒö66÷VçEöÖ–w&F–öåöæ÷r†æ÷r¢VF—BÒ7FFRævWB‚&66÷VçEöÖ–w&F–öåöVF—B"’÷"µĞ¢7V66W76W2Ò7VÒ€¢¢f÷"WfVçB–âVF—@¢–b—6–ç7Fæ6R†WfVçBÂF–7B’æBWfVçBævWB‚'7FGW2"’ÓÒ'7V66W72 ¢¢f–ÇW&W2Ò7VÒ€¢¢f÷"WfVçB–âVF—@¢–b—6–ç7Fæ6R†WfVçBÂF–7B’æBWfVçBævWB‚'7FGW2"’ÓÒ&f–ÆVB ¢¢VæF–ærÒ7VÒ€¢¢f÷"F–6¶WB–â‡7FFRævWB‚&66÷VçEöÖ–w&F–öå÷F–6¶WG2"’÷"·Ò’çfÇVW2‚¢–b€¢—6–ç7Fæ6R‡F–6¶WBÂF–7B¢æBF–6¶WBævWB‚'7FGW2"’ÓÒ'VæF–ær ¢æB€¢ö66÷VçEöÖ–w&F–öåöFFWF–ÖR‡F–6¶WBævWB‚&W‡—&W5öB"’¢æB7W'&Vç@¢Âö66÷VçEöÖ–w&F–öåöFFWF–ÖR‡F–6¶WBævWB‚&W‡—&W5öB"’¢¢¢¢ÆFW7EöWfVçG2ÒµĞ¢f÷"WfVçB–â&WfW'6VB†VF—E²Ó¥Ò“ ¢–bæ÷B—6–ç7Fæ6R†WfVçBÂF–7B“ ¢6öçF–çVP¢7FGW2Ò€¢WfVçBævWB‚'7FGW2"¢–bWfVçBævWB‚'7FGW2"’–â²'7V66W72"Â&f–ÆVB'Ğ¢VÇ6R&f–ÆVB ¢¢f–ÇW&Uö6FVv÷'’Ò7G"†WfVçBævWB‚&f–ÇW&Uö6FVv÷'’"’÷"""¢–bf–ÇW&Uö6FVv÷'’æ÷B–âôÔ”u$D”ôåôDÔ”åôd”ÅU$Uô4DTtõ$”U3 ¢f–ÇW&Uö6FVv÷'’Ò&÷F†W" ¢7&VFVEöBÒö66÷VçEöÖ–w&F–öåöFFWF–ÖR†WfVçBævWB‚&7&VFVEöB"’¢&uö6÷VçG2Ò€¢WfVçBævWB‚&6÷VçG2"¢–b—6–ç7Fæ6R†WfVçBævWB‚&6÷VçG2"’ÂF–7B¢VÇ6R·Ğ¢¢6÷VçG2Ò·Ğ¢f÷"¶W’–âôÔ”u$D”ôåôDÔ”åô4õTåEô´U•3 ¢G'“ ¢6÷VçG5¶¶W•ÒÒÖ‚ƒÂ–çB‡&uö6÷VçG2ævWB†¶W’’÷"’¢W†6WB…G—TW'&÷"ÂfÇVTW'&÷"“ ¢6÷VçG5¶¶W•ÒÒ ¢ÆFW7EöWfVçG2æVæB‡°¢'7FGW2#¢7FGW2À¢&7&VFVEöB#¢€¢7&VFVEöBæ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"¢–b7&VFVEö@¢VÇ6R" ¢’À¢&f–ÇW&Uö6FVv÷'’#¢f–ÇW&Uö6FVv÷'’À¢&6÷VçG2#¢6÷VçG2À¢Ò¢&WGW&â°¢&6öæf–wW&VB#¢66÷VçEöÖ–w&F–öå÷&VG’†6öæf–r’À¢'F÷FÇ2#¢°¢'F÷FÂ#¢7V66W76W2²f–ÇW&W2²VæF–ærÀ¢'7V66W72#¢7V66W76W2À¢&f–ÆVB#¢f–ÇW&W2À¢'VæF–ær#¢VæF–ærÀ¢ÒÀ¢&ÆFW7EöWfVçG2#¢ÆFW7EöWfVçG2À¢Ğ  ¦FVb&6·W÷&ö÷B†FFöf–ÆR“ ¢&WGW&âF‚†FFöf–ÆR’ç&VçBò&&6·W2   ¦FVb÷#%ö&6·Wö¶W’‡&r“ ¢G'“ ¢¶W’Ò&6ScBçW&Ç6fUö#cFFV6öFR‡7G"‡&r’æVæ6öFR‚’¢W†6WBW†6WF–öã ¢¶W’Ò"" ¢&WGW&â¶W’–bÆVâ†¶W’’ÓÒ3"VÇ6RæöæP  ¦FVböFVfVÇE÷#%÷WÆöFW"†'V6¶WBÂö&¦V7Eö¶W’Â&öG’Â6öçFVçE÷G—RÂÖWFFFÂ6öæf–r“ ¢–×÷'B&÷Fó0 ¢6Æ–VçBÒ&÷Fó2æ6Æ–VçB€¢'32"À¢VæGö–çE÷W&ÃÖ6öæf–rævWB‚%#%ôTäEô”åB"’À¢w5ö66W75ö¶W•ö–CÖ6öæf–rævWB‚%#%ô44U55ô´U•ô”B"’À¢w5÷6V7&WEö66W75ö¶W“Ö6öæf–rævWB‚%#%õ4T5$UEô44U55ô´U’"’À¢&Vv–öåöæÖSÒ&WFò"À¢¢&WGW&â6Æ–VçBçWEöö&¦V7B€¢'V6¶WCÖ'V6¶WBÀ¢¶W“Öö&¦V7Eö¶W’À¢&öG“Ö&öG’À¢6öçFVçEG—SÖ6öçFVçE÷G—RÀ¢ÖWFFFÖÖWFFFÀ¢  ¦FVb7&VFU÷#%öVæ7'—FVEö&6·W†6öæf–r“ ¢'V6¶WBÒ7G"†6öæf–rævWB‚%#%ô%T4´UB"’÷"""’ç7G&—‚¢¶W’Ò÷#%ö&6·Wö¶W’†6öæf–rævWB‚%#%ô$4µUôTä5%•D”ôåô´U’"’÷"""¢WÆöFW"Ò6öæf–rævWB‚%#%õUÄôDU""’÷"öFVfVÇE÷#%÷WÆöFW ¢–bæ÷B'V6¶WB÷"¶W’—2æöæR÷"U2—2æöæS ¢&WGW&â²&W'&÷"#¢'#%ö&6·Wöæ÷Eö6öæf–wW&VB'ÒÂS0¢–bWÆöFW"—2öFVfVÇE÷#%÷WÆöFW"æBæ÷BÆÂ€¢7G"†6öæf–rævWB†æÖR’÷"""’ç7G&—‚¢f÷"æÖR–â‚%#%ôTäEô”åB"Â%#%ô44U55ô´U•ô”B"Â%#%õ4T5$UEô44U55ô´U’"¢“ ¢&WGW&â²&W'&÷"#¢'#%ö&6·Wöæ÷Eö6öæf–wW&VB'ÒÂS0¢7FFRÒÆöE÷7FFR†6öæf–u²$DDôd”ÄR%Ò¢7&VFVEöBÒFFWF–ÖRææ÷r‡F–ÖW¦öæRçWF2’æ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"¢&6·Wö–BÒ€¢b'#"×¶FFWF–ÖRææ÷r‡F–ÖW¦öæRçWF2’ç7G&gF–ÖR‚rU’VÒVEBT‚TÒU5¢r—ÒÒ ¢b'·6V7&WG2çFö¶Våö†W‚ƒ2—Ò ¢¢6æ6†÷BÒ°¢¶W•öæÖS¢fÇVP¢f÷"¶W•öæÖRÂfÇVR–â7FFRæ—FV×2‚¢–b¶W•öæÖRæ÷B–â²&&6·WöW‡÷'G2"Â'#%ö&6·WöW‡÷'G2'Ğ¢Ğ¢Æ–çFW‡BÒ§6öâæGV×2€¢²&&6·Wö–B#¢&6·Wö–BÂ&7&VFVEöB#¢7&VFVEöBÂ'6æ6†÷B#¢6æ6†÷GÒÀ¢Vç7W&Uö66–“ÔfÇ6RÀ¢6W&F÷'3Ò‚"Â"Â#¢"’À¢’æVæ6öFR‚¢6—†W"ÒU2ææWr†¶W’ÂU2äÔôDUôt4Ò¢6—†W'FW‡BÂFrÒ6—†W"æVæ7'—EöæEöF–vW7B‡Æ–çFW‡B¢VçfVÆ÷RÒ§6öâæGV×2€¢°¢'fW'6–öâ#¢À¢&Æv÷&—F†Ò#¢$U2Ó#SbÔt4Ò"À¢&æöæ6R#¢&6ScBæ#cFVæ6öFR†6—†W"ææöæ6R’æFV6öFR‚’À¢'Fr#¢&6ScBæ#cFVæ6öFR‡Fr’æFV6öFR‚’À¢&6—†W'FW‡B#¢&6ScBæ#cFVæ6öFR†6—†W'FW‡B’æFV6öFR‚’À¢ÒÀ¢6W&F÷'3Ò‚"Â"Â#¢"’À¢’æVæ6öFR‚¢ö&¦V7Eö¶W’Òb&Æ—fRÖ6†V6¶–â÷¶7&VFVEöE³£×Ò÷¶&6·Wö–GÒæ§6öâæW6v6Ò ¢ÖWFFFÒ°¢&Væ7'—F–öâ#¢$U2Ó#SbÔt4Ò"À¢&&6·WÖ–B#¢&6·Wö–BÀ¢'6†#Sb#¢†6†Æ–"ç6†#Sb†VçfVÆ÷R’æ†W†F–vW7B‚’À¢Ğ¢G'“ ¢&W7VÇBÒWÆöFW"€¢'V6¶WBÀ¢ö&¦V7Eö¶W’À¢VçfVÆ÷RÀ¢&Æ–6F–öâöö7FWB×7G&VÒ"À¢ÖWFFFÀ¢6öæf–rÀ¢¢W†6WBW†6WF–öã ¢&WGW&â²&W'&÷"#¢'#%ö&6·W÷WÆöEöf–ÆVB'ÒÂS ¢WFrÒ7G"‚‡&W7VÇB÷"·Ò’ævWB‚&WFr"’÷"‡&W7VÇB÷"·Ò’ævWB‚$UFr"’÷"""¢WFrÒWFrç7G&—‚r"r¢&6·WÒ°¢&–B#¢&6·Wö–BÀ¢&7&VFVEöB#¢7&VFVEöBÀ¢&'V6¶WB#¢'V6¶WBÀ¢&ö&¦V7Eö¶W’#¢ö&¦V7Eö¶W’À¢&WFr#¢WFrÀ¢'6†#Sb#¢ÖWFFF²'6†#Sb%ÒÀ¢&Væ7'—F–öâ#¢ÖWFFF²&Væ7'—F–öâ%ÒÀ¢'W6W%ö6÷VçB#¢ÆVâ‡6æ6†÷BævWB‚'W6W'2"Â·Ò’’À¢Ğ¢7FFRç6WFFVfVÇB‚'#%ö&6·WöW‡÷'G2"ÂµÒ’æVæB†&6·W¢7FFU²'#%ö&6·WöW‡÷'G2%ÒÒ7FFU²'#%ö&6·WöW‡÷'G2%Õ²Ó¥Ğ¢6fU÷7FFR†6öæf–u²$DDôd”ÄR%ÒÂ7FFR¢&WGW&â²&&6·W#¢&6·WÒÂ#  ¦FVb7&VFUöFÖ–åö&6·W†FFöf–ÆR“ ¢7FFRÒÆöE÷7FFR†FFöf–ÆR¢7&VFVEöBÒFFWF–ÖRææ÷r‚’æ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"¢&6·Wö–BÒb&&6·W×¶FFWF–ÖRææ÷r‚’ç7G&gF–ÖR‚rU’VÒVBT‚TÒU2r—Ò×·6V7&WG2çFö¶Våö†W‚ƒ2—Ò ¢f–ÆVæÖRÒb'¶&6·Wö–GÒæ§6öâ ¢6æ6†÷BÒ¶¶W“¢fÇVRf÷"¶W’ÂfÇVR–â7FFRæ—FV×2‚’–b¶W’Ò&&6·WöW‡÷'G2'Ğ¢&6·WÒ°¢&–B#¢&6·Wö–BÀ¢&7&VFVEöB#¢7&VFVEöBÀ¢&f–ÆVæÖR#¢f–ÆVæÖRÀ¢'W6W%ö6÷VçB#¢ÆVâ‡6æ6†÷BævWB‚'W6W'2"Â·Ò’’À¢Ğ¢&ö÷BÒ&6·W÷&ö÷B†FFöf–ÆR¢&ö÷BæÖ¶F—"‡&VçG3ÕG'VRÂW†—7Eöö³ÕG'VR¢‡&ö÷Bòf–ÆVæÖR’çw&—FU÷FW‡B€¢§6öâæGV×2‡²&&6·W#¢&6·WÂ'6æ6†÷B#¢6æ6†÷GÒÂVç7W&Uö66–“ÔfÇ6RÂ–æFVçCÓ"’À¢Væ6öF–æsÒ'WFbÓ‚"À¢¢7FFRç6WFFVfVÇB‚&&6·WöW‡÷'G2"ÂµÒ’æVæB†&6·W¢7FFU²&&6·WöW‡÷'G2%ÒÒ7FFU²&&6·WöW‡÷'G2%Õ²ÓS¥Ğ¢6fU÷7FFR†FFöf–ÆRÂ7FFR¢&WGW&â²&&6·W#¢&6·WÒÂ#   ¦FVbÆ—7EöFÖ–åö&6·W2†FFöf–ÆR“ ¢7FFRÒÆöE÷7FFR†FFöf–ÆR¢&WGW&â²&&6·W2#¢Æ—7B‡&WfW'6VB‡7FFRævWB‚&&6·WöW‡÷'G2"ÂµÒ’’—Ğ  ¦FVb&VEöFÖ–åö&6·W†FFöf–ÆRÂ&6·Wö–B“ ¢7FFRÒÆöE÷7FFR†FFöf–ÆR¢&6·WÒæW‡B‚†—FVÒf÷"—FVÒ–â7FFRævWB‚&&6·WöW‡÷'G2"ÂµÒ’–b—FVÒævWB‚&–B"’ÓÒ&6·Wö–B’ÂæöæR¢–bæ÷B&6·W ¢&WGW&â²&W'&÷"#¢&&6·Wæ÷Bf÷VæB'ÒÂC@¢F‚Ò&6·W÷&ö÷B†FFöf–ÆR’ò&6·WævWB‚&f–ÆVæÖR"Â""¢–bæ÷BF‚æW†—7G2‚“ ¢&WGW&â²&W'&÷"#¢&&6·Wf–ÆRÖ—76–ær'ÒÂC@¢G'“ ¢&WGW&â§6öâæÆöG2‡F‚ç&VE÷FW‡B†Væ6öF–æsÒ'WFbÓ‚"’’Â# ¢W†6WB†§6öâä¥4ôäFV6öFTW'&÷"Âõ4W'&÷"“ ¢&WGW&â²&W'&÷"#¢&&6·Wf–ÆRVç&VF&ÆR'ÒÂS   ¦FVb'V–ÆE÷6÷5öw&÷WöÖVçF–öåöÖW76vR†ÆW'E÷FW‡C¢7G"“ ¢"".{êN{XB4õ>ûÉ®yJ‚FW‡Ec"²ÖVçF–öæVRG—SÖÆÎûÈ„XZš¹NûÈûÈÎyºXúşˆ;ŞŠé>jøşKØŞh‰Y:iKnX‹˜	®yú^8""" ¢&öG’Ò7G"†ÆW'E÷FW‡B÷"""’ç7G&—‚¢&WGW&â°¢'G—R#¢'FW‡Ec""À¢'FW‡B#¢'¶WfW'–öæWÕÆï	ùª8	XZš¹B{x®h
U4õ>8	Æâ"²&öG’À¢'7V'7F—GWF–öâ#¢°¢&WfW'–öæR#¢°¢'G—R#¢&ÖVçF–öâ"À¢&ÖVçF–öæVR#¢²'G—R#¢&ÆÂ'ÒÀ¢Ğ¢ÒÀ¢Ğ  ¦FVb'V–ÆE÷6÷5öw&÷WöÖVÖ&W%öÖVçF–öç5öÖW76vR†ÆW'E÷FW‡C¢7G"ÂÖVÖ&W%÷W6W%ö–G3ÔæöæR“ ¢""$ÆÂZKiY~i˜.X)hûNûÉ¦ÖVçF–öâ[{.yú^h‰Y:W6W$–NûÈYjîX˜~iÈZI¢#K«®ûÈ8""" ¢&öG’Ò7G"†ÆW'E÷FW‡B÷"""’ç7G&—‚¢–G2ÒµĞ¢6VVâÒ6WB‚¢f÷"V–B–âÖVÖ&W%÷W6W%ö–G2÷"µÓ ¢RÒ7G"‡V–B÷"""’ç7G&—‚¢–bæ÷BR÷"R–â6VVâ÷"æ÷BRç7F'G7v—F‚‚%R"“ ¢6öçF–çVP¢6VVâæFB‡R¢–G2æVæB‡R¢–bÆVâ†–G2’ãÒ# ¢'&V°¢–bæ÷B–G3 ¢&WGW&â/	ùª8	XZš¹B{x®h
U4õ>8	Æâ"²&öG¢7V'7F—GWF–öâÒ·Ğ¢'G2ÒµĞ¢f÷"’ÂV–B–âVçVÖW&FR†–G2“ ¢¶W’Òb&×¶—Ò ¢'G2æVæB‚'²"²¶W’²'Ò"¢7V'7F—GWF–öå¶¶W•ÒÒ°¢'G—R#¢&ÖVçF–öâ"À¢&ÖVçF–öæVR#¢²'G—R#¢'W6W""Â'W6W$–B#¢V–GÒÀ¢Ğ¢&WGW&â°¢'G—R#¢'FW‡Ec""À¢'FW‡B#¢""æ¦ö–â‡'G2’²%Æï	ùª8	XZš¹B{x®h
U4õ>8	Æâ"²&öG’À¢'7V'7F—GWF–öâ#¢7V'7F—GWF–öâÀ¢Ğ  ¦FVb÷6VæEöÆ–æU÷v—F…÷&WG'•ö¶W’‡6VæFW"ÂFö¶VâÂF&vWBÂÖW76vRÂ&WG'•ö¶W’“ ¢""%W6RÄ”äR&WG'’¶W—2–â&öGV7F–öâv†–ÆR¶VW–ær6–×ÆR–æ¦V7FVBFW7B6VæFW'2â"" ¢–b6VæFW"—2Æ–æU÷W6…öÖW76vS ¢&WGW&â6VæFW"‡Fö¶VâÂF&vWBÂÖW76vRÂ&WG'•ö¶W“×&WG'•ö¶W’¢&WGW&â6VæFW"‡Fö¶VâÂF&vWBÂÖW76vR  ¦FVbW6…÷6÷5÷FõöwV&F–åöw&÷W€¢Fö¶VâÂw&÷Wö–BÂÆW'E÷FW‡BÂ¢Â6VæFW#ÔæöæRÂÖVÖ&W%ö–G3ÔæöæRÂ&WG'•ö¶W“ÔæöæP¢“ ¢"".hê˜{êN{XB4õ>ûÈÎXJ®XX‚ÆÎûÉ¾ZKiY~XhÒÖVçF–öâ[{.yú^h‰Y:ûÉ¾iÈ[èÎ{INih~ZÙ~XªXZš¹BX˜Ş{kN8""" ¢W6‚Ò6VæFW"÷"Æ–æU÷W6…öÖW76vP¢v–BÒ7G"†w&÷Wö–B÷"""’ç7G&—‚¢–bæ÷Bv–C ¢&—6RfÇVTW'&÷"‚&Ö—76–ærw&÷Wö–Bf÷"4õ2w&÷WW6‚"¢&–Ö'’Ò'V–ÆE÷6÷5öw&÷WöÖVçF–öåöÖW76vR†ÆW'E÷FW‡B¢G'“ ¢&W7VÇBÒ÷6VæEöÆ–æU÷v—F…÷&WG'•ö¶W’€¢W6‚ÂFö¶VâÂv–BÂ&–Ö'’À¢öÆ–æU÷&WG'•ö¶W’†b'·&WG'•ö¶W—Ó¦ÆÂ"’–b&WG'•ö¶W’VÇ6RæöæRÀ¢¢&WGW&â&W7VÇBÂ&ÆÂ"Â&–Ö'¢W†6WBW†6WF–öâ2W†3 ¢–b6Æ76–g•÷W6…öW†6WF–öâ†W†2’æ¶–æBÒ&ÖW76vR# ¢&—6P¢fÆÆ&6µö–G2ÒÆ—7B†ÖVÖ&W%ö–G2÷"µÒ¢–bæ÷BfÆÆ&6µö–G3 ¢fÆÆ&6µö–G2ÒvWEöw&÷WöÖVÖ&W%ö–G2‡Fö¶VâÂv–B’÷"µĞ¢6V6öæF'’Ò'V–ÆE÷6÷5öw&÷WöÖVÖ&W%öÖVçF–öç5öÖW76vR†ÆW'E÷FW‡BÂfÆÆ&6µö–G2¢G'“ ¢&W7VÇBÒ÷6VæEöÆ–æU÷v—F…÷&WG'•ö¶W’€¢W6‚ÂFö¶VâÂv–BÂ6V6öæF'’À¢öÆ–æU÷&WG'•ö¶W’†b'·&WG'•ö¶W—Ó¦ÖVÖ&W'2"’–b&WG'•ö¶W’VÇ6RæöæRÀ¢¢ÖöFRÒ&ÖVÖ&W'2"–b—6–ç7Fæ6R‡6V6öæF'’ÂF–7B’VÇ6R'FW‡B ¢&WGW&â&W7VÇBÂÖöFRÂ6V6öæF'¢W†6WBW†6WF–öâ2W†3 ¢–b6Æ76–g•÷W6…öW†6WF–öâ†W†2’æ¶–æBÒ&ÖW76vR# ¢&—6P¢Æ–âÒ/	ùª8	XZš¹B{x®h
U4õ>8	Æâ"²7G"†ÆW'E÷FW‡B÷"""’ç7G&—‚¢&W7VÇBÒ÷6VæEöÆ–æU÷v—F…÷&WG'•ö¶W’€¢W6‚ÂFö¶VâÂv–BÂÆ–âÀ¢öÆ–æU÷&WG'•ö¶W’†b'·&WG'•ö¶W—Ó§FW‡B"’–b&WG'•ö¶W’VÇ6RæöæRÀ¢¢&WGW&â&W7VÇBÂ'FW‡B"ÂÆ–à  ¦FVbÆ–æU÷W6…öÖW76vR‡Fö¶VâÂÆ–æU÷W6W%ö–BÂÖW76vRÂ¢Â&WG'•ö¶W“ÔæöæR“ ¢"".hêŠˆ®hş{ZnYjîKˆÄ”äRyJh‹n8  ¢ÖW76vRXúşKº^iŠó ¢Ò7G#¢{INih~ZÙ~Šˆ®hğ¢ÒF–7BK‰N[‹b'G—R"¶W“¢y»Nhê^KÙÎx+¢Ä”äRÖW76vRö&¦V7BKè¾Zh"fÆW‚¢"" ¢Fõö–BÒ7G"†Æ–æU÷W6W%ö–B÷"""’ç7G&—‚¢–bæ÷BFõö–C ¢&—6RfÇVTW'&÷"‚&Ö—76–ærÆ–æU÷W6W%ö–Bf÷"W6‚"¢–b—6–ç7Fæ6R†ÖW76vRÂF–7B’æBÖW76vRævWB‚'G—R"“ ¢×6uöö&¢ÒÖW76vP¢VÇ6S ¢×6uöö&¢Ò²'G—R#¢'FW‡B"Â'FW‡B#¢7G"†ÖW76vR—Ğ¢&öG’Ò§6öâæGV×2€¢²'Fò#¢Fõö–BÂ&ÖW76vW2#¢¶×6uöö&¥×ÒÀ¢Vç7W&Uö66–“ÔfÇ6RÀ¢’æVæ6öFR‚'WFbÓ‚"¢†VFW'2Ò°¢$6öçFVçBÕG—R#¢&Æ–6F–öâö§6öã²6†'6WCÕUDbÓ‚"À¢$WF†÷&—¦F–öâ#¢b$&V&W"·Fö¶VçÒ"À¢Ğ¢–b&WG'•ö¶W“ ¢†VFW'5²%‚ÔÆ–æRÕ&WG'’Ô¶W’%ÒÒ7G"‡&WG'•ö¶W’¢&WÒW&ÆÆ–"ç&WVW7Bå&WVW7B€¢&‡GG3¢òö’æÆ–æRæÖR÷c"ö&÷BöÖW76vR÷W6‚"À¢FFÖ&öG’À¢†VFW'3Ö†VFW'2À¢ÖWF†öCÒ%õ5B"À¢¢G'“ ¢v—F‚W&ÆÆ–"ç&WVW7BçW&Æ÷Vâ‡&WÂF–ÖV÷WCÓ’2&W3 ¢&WGW&â²&ö²#¢#ÃÒ&W2ç7FGW2Â3Â'7FGW2#¢&W2ç7FGW7Ğ¢W†6WBW&ÆÆ–"æW'&÷"ä…EEW'&÷"2W†3 ¢–bW†2æ6öFRÓÒC’æBW†2æ†VFW'2ævWB‚%‚ÔÆ–æRÔ66WFVBÕ&WVW7BÔ–B"“ ¢&WGW&â°¢&ö²#¢G'VRÀ¢'7FGW2#¢C’À¢&–FV×÷FVçE÷&WÆ’#¢G'VRÀ¢&66WFVE÷&WVW7Eö–B#¢W†2æ†VFW'2ævWB€¢%‚ÔÆ–æRÔ66WFVBÕ&WVW7BÔ–B ¢’À¢Ğ¢W'%ö&öG’Ò" ¢G'“ ¢W'%ö&öG’ÒW†2ç&VB‚’æFV6öFR‚'WFbÓ‚"ÂW'&÷'3Ò'&WÆ6R"•³£SĞ¢W†6WBW†6WF–öã ¢W'%ö&öG’Ò" ¢2&R×&—6Rv—F‚Ä”äR&öG’6ò7&öâö&6¶f–ÆÂ6â7W&f6RF†R&VÂ6W6Rà¢&—6RW&ÆÆ–"æW'&÷"ä…EEW'&÷"€¢W†2çW&ÂÀ¢W†2æ6öFRÀ¢b'¶W†2ç&V6öçÓ¢¶W'%ö&öG—Ò"–bW'%ö&öG’VÇ6RW†2ç&V6öâÀ¢W†2æ†VFW'2À¢æöæRÀ¢’g&öÒW†0  ¦FVböÖW&vU÷W&ÖæVçEöFVÆ—fW'•÷&÷w2‡7FFRÂ&÷w2“ ¢""$ÖW&vRFVÆ—fW'’6æ6†÷G2&6²gFW"W‡FW&æÂ’ôòv—F†÷WBÆ÷6–ær6öæ7W'&VçBw&—FW2â"" ¢ÆVFvW"ÒÆ—7B‡7FFRævWB‚'W6…öFVÆ—fW'•÷&V6÷&G2"’÷"µÒ¢¶æ÷våö–G2Ò°¢7G"‡&÷rævWB‚&–B"’÷"""¢f÷"&÷r–âÆVFvW ¢–b—6–ç7Fæ6R‡&÷rÂF–7B’æB7G"‡&÷rævWB‚&–B"’÷"""¢Ğ¢f÷"&÷r–â&÷w2÷"µÓ ¢–bæ÷B—6–ç7Fæ6R‡&÷rÂF–7B“ ¢6öçF–çVP¢&V6÷&Eö–BÒ7G"‡&÷rævWB‚&–B"’÷"""¢–b&V6÷&Eö–BæB&V6÷&Eö–B–â¶æ÷våö–G3 ¢6öçF–çVP¢ÆVFvW"æVæB†6÷’æFVW6÷’‡&÷r’¢–b&V6÷&Eö–C ¢¶æ÷våö–G2æFB‡&V6÷&Eö–B¢7FFU²'W6…öFVÆ—fW'•÷&V6÷&G2%ÒÒÆVFvW   ¦FVbVæEöæ÷F–f–6F–öåöÆör€¢7FFRÂ¶–æBÂÆ–æU÷W6W%ö–BÂ7FGW2ÂÖW76vRÂFWF–ÃÔæöæRÂÖWFFFÔæöæP¢“ ¢Æöw2Ò7FFRç6WFFVfVÇB‚&æ÷F–f–6F–öåöÆöw2"ÂµÒ¢–b—6–ç7Fæ6R†ÖW76vRÂF–7B“ ¢ÖW76vU÷FW‡BÒ7G"†ÖW76vRævWB‚&ÇEFW‡B"’÷"ÖW76vRævWB‚'G—R"’÷"ÖW76vR•³£#Ğ¢VÇ6S ¢ÖW76vU÷FW‡BÒ7G"†ÖW76vR÷"""•³£#Ğ¢7&VFVEöBÒFFWF–ÖRææ÷r‚’æ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"¢&÷rÒ°¢&7&VFVEöB#¢7&VFVEöBÀ¢&¶–æB#¢¶–æBÀ¢&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–BÀ¢'7FGW2#¢7FGW2À¢&ÖW76vR#¢ÖW76vU÷FW‡BÀ¢&FWF–Â#¢FWF–Â÷"""À¢Ğ¢–b—6–ç7Fæ6R†ÖWFFFÂF–7B“ ¢&÷rçWFFR‡°¢¶W“¢ÖWFFFævWB†¶W’¢f÷"¶W’–â€¢'Æâ"À¢&ÖVÖ&W'6†—÷6÷W&6R"À¢&&WFö6ö†÷'B"À¢'66†VGVÆVEöB"À¢'6VçEöB"À¢¢–bÖWFFFævWB†¶W’’æ÷B–â„æöæRÂ""¢Ò¢Æöw2æVæB‡&÷r¢7FFU²&æ÷F–f–6F–öåöÆöw2%ÒÒÆöw5²Ó¥Ğ¢W&ÖæVçEöÖWFFFÒF–7B†ÖWFFF÷"·Ò’–b—6–ç7Fæ6R†ÖWFFFÂF–7B’VÇ6R·Ğ¢–b7FGW2–â²&f–ÆVB"Â&W'&÷""Â&&Æö6¶VB'Ó ¢W‡ÆæF–öâÒöFÖ–å÷W6…öf–ÇW&UöW‡ÆæF–öâ†FWF–Â¢W&ÖæVçEöÖWFFFç6WFFVfVÇB€¢&f–ÇW&U÷&V6öå÷¦‚"ÂW‡ÆæF–öâævWB‚&f–ÇW&U÷&V6öå÷¦‚"’÷"$Ä”äRhêi*ŞZKiY~8" ¢¢W&ÖæVçEöÖWFFFç6WFFVfVÇB€¢&f–ÇW&Uö7F–öå÷¦‚"ÂW‡ÆæF–öâævWB‚&f–ÇW&Uö7F–öå÷¦‚"’÷".Š¸¾yK{;¾{[zêynY:jª.iú^8" ¢¢VæE÷7—7FVÕöFVÆ—fW'•÷&V6÷&B€¢7FFRÀ¢¶–æCÖ¶–æBÀ¢Æ–æU÷W6W%ö–CÖÆ–æU÷W6W%ö–BÀ¢7FGW3×7FGW2À¢ÖW76vSÖÖW76vRÀ¢7&VFVEöCÖ7&VFVEöBÀ¢FWF–ÃÖFWF–Â÷"""À¢ÖWFFF×W&ÖæVçEöÖWFFFÀ¢¢ÖVÖ&W%ö–BÒ7G"†Æ–æU÷W6W%ö–B÷"""’ç7G&—‚¢FFRÒ7&VFVEöE³£Ğ¢–bÖVÖ&W%ö–C ¢7FG2Ò7FFRç6WFFVfVÇB‚&F–Ç•÷W6…öÖVÖ&W%÷7FG2"Â·Ò¢¶W’Òb'¶FFW×Ç¶ÖVÖ&W%ö–GÒ ¢&÷rÒ7FG2ç6WFFVfVÇB€¢¶W’À¢°¢&FFR#¢FFRÀ¢&Æ–æU÷W6W%ö–B#¢ÖVÖ&W%ö–BÀ¢'6VçEö6÷VçB#¢À¢&f–ÆVEö6÷VçB#¢À¢'F÷FÅö6÷VçB#¢À¢&¶–æG2#¢µÒÀ¢&Æ7E÷W6…öB#¢7&VFVEöBÀ¢ÒÀ¢¢&÷u²'F÷FÅö6÷VçB%ÒÒ–çB‡&÷rævWB‚'F÷FÅö6÷VçB"’÷"’²¢–b7FGW2ÓÒ'6VçB# ¢&÷u²'6VçEö6÷VçB%ÒÒ–çB‡&÷rævWB‚'6VçEö6÷VçB"’÷"’²¢VÆ–b7FGW2–â²&f–ÆVB"Â&W'&÷""Â&&Æö6¶VB'Ó ¢&÷u²&f–ÆVEö6÷VçB%ÒÒ–çB‡&÷rævWB‚&f–ÆVEö6÷VçB"’÷"’²¢&÷u²&ÆFW7Eöf–ÇW&UöFWF–Â%ÒÒ7G"†FWF–Â÷"""•³£SĞ¢&÷u²&ÆFW7Eöf–ÇW&UöB%ÒÒ7&VFVEö@¢&÷u²&¶–æG2%ÒÒ6÷'FVB‡6WB‡&÷rævWB‚&¶–æG2"’÷"µÒ’Â·7G"†¶–æB÷"&÷F†W""—Ò¢&÷u²&Æ7E÷W6…öB%ÒÒ7&VFVEö@¢2¶VW&÷Vv†Ç’öæR–V"öbF–Ç’öÖVÖ&W"vw&VvFW2v—F†÷WBw&÷v–ærf÷&WfW"à¢–bÆVâ‡7FG2’â# ¢f÷"öÆEö¶W’–â6÷'FVB‡7FG2•³¢ÆVâ‡7FG2’Ò#Ó ¢7FG2ç÷†öÆEö¶W’ÂæöæR  ¤Ä”äUôÔU54tUõU4tUô4DTtõ$”U2Ò°¢&&–æF–ær"À¢&6†V6¶–â"À¢&÷fW&GVR"À¢'6÷2"À¢'6÷5ö6æ6VÂ"À¢'6÷5÷&V6—–VçE÷&VÖ–æFW""À¢'6Ö'E÷&VÖ–æFW""À¢&wV&F–å÷7VÖÖ'’"À§Ğ  ¦FVb&V6÷&EöÆ–æUöÖW76vU÷W6vR€¢7FFS¢F–7BÀ¢¢À¢6FVv÷'“¢7G"À¢÷væW%öÆ–æU÷W6W%ö–C¢7G"À¢&V6—–VçEö6÷VçC¢–çBÀ¢WfVçEö–C¢7G"À¢6VçEöC¢FFWF–ÖRÀ¢’ÓâF–7C ¢""$–FV×÷FVçFÇ’&V6÷&BFVÆ—fW&VBÄ”äR&V6—–VçBVæ—G2â"" ¢6FVv÷'’Ò7G"†6FVv÷'’÷"""’ç7G&—‚¢–b6FVv÷'’æ÷B–âÄ”äUôÔU54tUõU4tUô4DTtõ$”U3 ¢&—6RfÇVTW'&÷"‚&–çfÆ–BÄ”äRÖW76vRW6vR6FVv÷'’"¢Væ—G2ÒÖ‚ƒÂ–çB‡&V6—–VçEö6÷VçB÷"’¢–bVæ—G2ÃÒ ¢&WGW&â²'&V6÷&FVB#¢fÇ6RÂ'Væ—G2#¢Ğ¢÷væW"Ò7G"†÷væW%öÆ–æU÷W6W%ö–B÷"""’ç7G&—‚¢WfVçEö–BÒ7G"†WfVçEö–B÷"""’ç7G&—‚¢–bæ÷B÷væW"÷"æ÷BWfVçEö–C ¢&—6RfÇVTW'&÷"‚&÷væW%öÆ–æU÷W6W%ö–BæBWfVçEö–B&R&WV—&VB"¢ÆVFvW"Ò7FFRç6WFFVfVÇB‚&Æ–æUöÖW76vU÷W6vR"ÂµÒ¢¶W’Òb'¶6FVv÷'—Ó§¶WfVçEö–GÒ ¢W†—7F–ærÒæW‡B‚‡&÷rf÷"&÷r–âÆVFvW"–b&÷rævWB‚&¶W’"’ÓÒ¶W’’ÂæöæR¢–bW†—7F–æs ¢&WGW&â²¢¦W†—7F–ærÂ'&V6÷&FVB#¢fÇ6RÂ&–FV×÷FVçB#¢G'VWĞ¢&÷rÒ°¢&¶W’#¢¶W’À¢&6FVv÷'’#¢6FVv÷'’À¢&÷væW%öÆ–æU÷W6W%ö–B#¢÷væW"À¢'&V6—–VçEö6÷VçB#¢Væ—G2À¢'Væ—G2#¢Væ—G2À¢&WfVçEö–B#¢WfVçEö–BÀ¢'6VçEöB#¢6VçEöBæ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"’À¢Ğ¢ÆVFvW"æVæB‡&÷r¢7FFU²&Æ–æUöÖW76vU÷W6vR%ÒÒÆVFvW%²Ó¥Ğ¢&WGW&â²¢§&÷rÂ'&V6÷&FVB#¢G'VRÂ&–FV×÷FVçB#¢fÇ6WĞ  ¦FVbÆ–æU÷W6…ö'VFvWEöFV6—6–öâ€¢7FFS¢F–7BÀ¢¢À¢÷væW%öÆ–æU÷W6W%ö–C¢7G"À¢&WVW7FVE÷Væ—G3¢–çBÀ¢æ÷s¢FFWF–ÖRÀ¢ÖöçF†Ç•ö†&Eö6¢–çBÀ¢ÖVÖ&W%öF–Ç•ö†&Eö6¢–çBÀ¢VÖW&vVæ7“¢&ööÂÒfÇ6RÀ¢’ÓâF–7C ¢""$Ç’&R×6VæB†&B62v†–ÆR&WF–æ–æröæR&–Ö'’4õ2FVÆ—fW'’â"" ¢÷væW"Ò7G"†÷væW%öÆ–æU÷W6W%ö–B÷"""’ç7G&—‚¢&WVW7FVBÒÖ‚ƒÂ–çB‡&WVW7FVE÷Væ—G2÷"’¢ÖöçF†Ç•ö6ÒÖ‚ƒÂ–çB†ÖöçF†Ç•ö†&Eö6÷"’¢F–Ç•ö6ÒÖ‚ƒÂ–çB†ÖVÖ&W%öF–Ç•ö†&Eö6÷"’¢ÖöçF…÷&Vf—‚Òæ÷rç7G&gF–ÖR‚"U’ÒVÒÒ"¢F•÷&Vf—‚Òæ÷rç7G&gF–ÖR‚"U’ÒVÒÒVB"¢&÷w2Ò7FFRævWB‚&Æ–æUöÖW76vU÷W6vR"’÷"µĞ¢ÖöçF†Ç•÷W6VBÒ7VÒ€¢Ö‚ƒÂ–çB‡&÷rævWB‚'Væ—G2"’÷"&÷rævWB‚'&V6—–VçEö6÷VçB"’÷"’¢f÷"&÷r–â&÷w0¢–b7G"‡&÷rævWB‚'6VçEöB"’÷"""’ç7F'G7v—F‚†ÖöçF…÷&Vf—‚¢¢ÖVÖ&W%öF–Ç•÷W6VBÒ7VÒ€¢Ö‚ƒÂ–çB‡&÷rævWB‚'Væ—G2"’÷"&÷rævWB‚'&V6—–VçEö6÷VçB"’÷"’¢f÷"&÷r–â&÷w0¢–b7G"‡&÷rævWB‚&÷væW%öÆ–æU÷W6W%ö–B"’÷"""’ÓÒ÷væW ¢æB7G"‡&÷rævWB‚'6VçEöB"’÷"""’ç7F'G7v—F‚†F•÷&Vf—‚¢¢ÖöçF†Ç•÷&VÖ–æ–ærÒÖ‚ƒÂÖöçF†Ç•ö6ÒÖöçF†Ç•÷W6VB¢F–Ç•÷&VÖ–æ–ærÒÖ‚ƒÂF–Ç•ö6ÒÖVÖ&W%öF–Ç•÷W6VB¢ÆÆ÷vVE÷Væ—G2ÒÖ–â‡&WVW7FVBÂÖöçF†Ç•÷&VÖ–æ–ærÂF–Ç•÷&VÖ–æ–ær¢&V6öâÒæöæP¢–bÆÆ÷vVE÷Væ—G2Â&WVW7FVC ¢&V6öâÒ€¢&ÖöçF†Ç•ö†&Eö6 ¢–bÖöçF†Ç•÷&VÖ–æ–ærÃÒF–Ç•÷&VÖ–æ–æp¢VÇ6R&ÖVÖ&W%öF–Ç•ö†&Eö6 ¢¢–bVÖW&vVæ7’æB&WVW7FVBâæBÆÆ÷vVE÷Væ—G2Â ¢ÆÆ÷vVE÷Væ—G2Ò¢&V6öâÒ&VÖW&vVæ7•÷&–Ö'•ööæÇ’ ¢&WGW&â°¢&ÆÆ÷vVB#¢ÆÆ÷vVE÷Væ—G2â÷"&WVW7FVBÓÒÀ¢'&V6öâ#¢&V6öâÀ¢'&WVW7FVE÷Væ—G2#¢&WVW7FVBÀ¢&ÆÆ÷vVE÷Væ—G2#¢ÆÆ÷vVE÷Væ—G2À¢&ÖöçF†Ç•÷W6VB#¢ÖöçF†Ç•÷W6VBÀ¢&ÖöçF†Ç•ö†&Eö6#¢ÖöçF†Ç•ö6À¢&ÖVÖ&W%öF–Ç•÷W6VB#¢ÖVÖ&W%öF–Ç•÷W6VBÀ¢&ÖVÖ&W%öF–Ç•ö†&Eö6#¢F–Ç•ö6À¢Ğ  ¦FVbÖöçF†Ç•öÆ–æUöÖW76vU÷W6vR‡7FFS¢F–7BÂ–V%öÖöçFƒ¢7G"ÂV÷F¢–çBÂæ÷s¢FFWF–ÖR’ÓâF–7C ¢""$vw&VvFRFVÆ—fW&VB&V6—–VçBVæ—G2f÷"F†R&WVW7FVB6ÆVæF"ÖöçF‚â"" ¢6FVv÷'•÷F÷FÇ2Ò¶¶W“¢f÷"¶W’–â6÷'FVB„Ä”äUôÔU54tUõU4tUô4DTtõ$”U2—Ğ¢ÖVÖ&W%öÖÒ·Ğ¢&÷w2ÒµĞ¢f÷"&÷r–â7FFRævWB‚&Æ–æUöÖW76vU÷W6vR"’÷"µÓ ¢–bæ÷B7G"‡&÷rævWB‚'6VçEöB"’÷"""’ç7F'G7v—F‚†b'·–V%öÖöçF‡ÒÒ"“ ¢6öçF–çVP¢Væ—G2ÒÖ‚ƒÂ–çB‡&÷rævWB‚'Væ—G2"’÷"&÷rævWB‚'&V6—–VçEö6÷VçB"’÷"’¢–bVæ—G2ÃÒ ¢6öçF–çVP¢&÷w2æVæB‡&÷r¢6FVv÷'’Ò7G"‡&÷rævWB‚&6FVv÷'’"’÷"""¢–b6FVv÷'’–â6FVv÷'•÷F÷FÇ3 ¢6FVv÷'•÷F÷FÇ5¶6FVv÷'•Ò³ÒVæ—G0¢÷væW"Ò7G"‡&÷rævWB‚&÷væW%öÆ–æU÷W6W%ö–B"’÷"""¢ÖVÖ&W%öÖ¶÷væW%ÒÒÖVÖ&W%öÖævWB†÷væW"Â’²Væ—G0¢W6VBÒ7VÒ†6FVv÷'•÷F÷FÇ2çfÇVW2‚’¢G'“ ¢ÖöçF…öF—2Ò6ÆVæF"æÖöçF‡&ævR†æ÷rç–V"Âæ÷ræÖöçF‚•³Ğ¢W†6WBW†6WF–öã ¢ÖöçF…öF—2Ò3 ¢VÆ6VEöF—2ÒÖ‚ƒÂæ÷ræF’¢&ö¦V7FVBÒ–çB†ÖF‚æ6V–Â‡W6VB¢ÖöçF…öF—2òVÆ6VEöF—2’¢V÷FÒÖ‚ƒÂ–çB‡V÷F÷"’¢&F–òÒ‡W6VBòV÷F’–bV÷FVÇ6R ¢ÆW'BÒ&7&—F–6Åó“"–bV÷FæB&F–òãÒã’VÇ6R€¢'v&æ–æuós"–bV÷FæB&F–òãÒãrVÇ6R&æ÷&ÖÂ ¢¢ÖVÖ&W'2Ò°¢²&Æ–æU÷W6W%ö–B#¢V–E³£eÒ²"âââ"²V–E²ÓC¥Ò–bÆVâ‡V–B’âVÇ6RV–BÂ'Væ—G2#¢Væ—G7Ğ¢f÷"V–BÂVæ—G2–â6÷'FVB†ÖVÖ&W%öÖæ—FV×2‚’Â¶W“ÖÆÖ&F—FVÓ¢‚Ö—FVÕ³ÒÂ—FVÕ³Ò’¢Ğ¢&WGW&â°¢'–V%öÖöçF‚#¢–V%öÖöçF‚À¢'V÷F#¢V÷FÀ¢'W6VE÷Væ—G2#¢W6VBÀ¢'&VÖ–æ–æu÷Væ—G2#¢Ö‚ƒÂV÷FÒW6VB’–bV÷FVÇ6RæöæRÀ¢'W6vU÷W&6VçB#¢&÷VæB‡&F–ò¢Â’–bV÷FVÇ6RæöæRÀ¢'&ö¦V7FVE÷Væ—G2#¢&ö¦V7FVBÀ¢&ÆW'EöÆWfVÂ#¢ÆW'BÀ¢&6FVv÷'•÷F÷FÇ2#¢6FVv÷'•÷F÷FÇ2À¢&ÖVÖ&W%÷F÷FÇ2#¢ÖVÖ&W'2À¢&fÇ6UöÆ&Õ÷Væ—G2#¢6FVv÷'•÷F÷FÇ5²'6÷5ö6æ6VÂ%ÒÀ¢'&V6÷&G2#¢ÆVâ‡&÷w2’À¢Ğ  ¦FVbö6ÆV%÷W6…öFVÆ—fW'•öf–ÇW&R‡&V6—–VçBÂFVÆ—fW'•ö¶W’“ ¢GFV×G2ÒF–7B‡&V6—–VçBævWB‚'W6…öFVÆ—fW'•öGFV×G2"’÷"·Ò¢GFV×G2ç÷†FVÆ—fW'•ö¶W’ÂæöæR¢–bGFV×G3 ¢&V6—–VçE²'W6…öFVÆ—fW'•öGFV×G2%ÒÒGFV×G0¢VÇ6S ¢&V6—–VçBç÷‚'W6…öFVÆ—fW'•öGFV×G2"ÂæöæR  ¦FVb÷&V6÷&EöÆVæ6…öFVÆ—fW'’‡7FFRÂFVÆ—fW'•ö¶W’Â¶–æBÂF&vWBÂ7FGW2“ ¢ÆVFvW"Ò7FFRç6WFFVfVÇB‚&ÆVæ6…öFVÆ—fW'•öWfVçG2"Â·Ò¢ÆVFvW%ö¶W’Òb'¶¶–æGÓ§·F&vWGÓ§¶FVÆ—fW'•ö¶W—Ò ¢WfVçBÒÆVFvW"ç6WFFVfVÇB†ÆVFvW%ö¶W’Â°¢&¶–æB#¢7G"†¶–æB’À¢'F&vWB#¢7G"‡F&vWB’À¢&W‡V7FVB#¢G'VRÀ¢'6VçEö6÷VçB#¢À¢&f–ÆVB#¢fÇ6RÀ¢Ò¢–b7FGW2ÓÒ'6VçB# ¢WfVçE²'6VçEö6÷VçB%ÒÒ–çB†WfVçBævWB‚'6VçEö6÷VçB"’÷"’²¢VÆ–b7FGW2ÓÒ&f–ÆVB# ¢WfVçE²&f–ÆVB%ÒÒG'VP¢WfVçE²'WFFVEöB%ÒÒFFWF–ÖRææ÷r‚’æ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"¢&WGW&âWfVç@  ¦FVb÷&V6÷&E÷66†VGVÆVE÷W6…öf–ÇW&R€¢7FFRÀ¢&V6—–VçBÀ¢FVÆ—fW'•ö¶W’À¢¶–æBÀ¢Æ–æU÷W6W%ö–BÀ¢ÖW76vRÀ¢W†2À¢æ÷rÀ¢“ ¢f–ÇW&RÒ&V6÷&E÷W6…öf–ÇW&R‡&V6—–VçBÂFVÆ—fW'•ö¶W’ÂW†2Âæ÷r¢÷&V6÷&EöÆVæ6…öFVÆ—fW'’€¢7FFRÂFVÆ—fW'•ö¶W’Â¶–æBÂÆ–æU÷W6W%ö–BÂ&f–ÆVB ¢¢VæEöæ÷F–f–6F–öåöÆör€¢7FFRÀ¢¶–æBÀ¢Æ–æU÷W6W%ö–BÀ¢f–ÇW&U²'7FGW2%ÒÀ¢ÖW76vRÀ¢7G"†W†2’À¢¢&WGW&âf–ÇW&P  ¦FVbÆöuöæ÷F–f–6F–öâ†FFöf–ÆRÂ¶–æBÂÆ–æU÷W6W%ö–BÂ7FGW2ÂÖW76vRÂFWF–ÃÔæöæR“ ¢7FFRÒÆöE÷7FFR†FFöf–ÆR¢VæEöæ÷F–f–6F–öåöÆör‡7FFRÂ¶–æBÂÆ–æU÷W6W%ö–BÂ7FGW2ÂÖW76vRÂFWF–Â¢6fU÷7FFR†FFöf–ÆRÂ7FFR  ¦FVb6VæEöGVU÷&VÖ–æFW'2†6öæf–r“ ¢Fö¶VâÒ6öæf–rævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"’÷"÷2æVçf—&öâævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"Â""¢–bæ÷BFö¶Vã ¢&WGW&â²'6VçB#¢Â'6¶—VB#¢Â&W'&÷"#¢$Ä”äUô4„ääTÅô44U55õDô´Tâ—2æ÷B6WB'ÒÂC  ¢æ÷rÒ7W'&VçEö÷F–ÖR†6öæf–r¢6VæFW"Ò6öæf–rævWB‚$Ä”äUõU4…õ4TäDU""’÷"Æ–æU÷W6…öÖW76vP¢7FFRÒÆöE÷7FFR†6öæf–u²$DDôd”ÄR%Ò¢6VçBÒ ¢6¶—VBÒ ¢&W7VÇG2ÒµĞ¢7—7FVÕöW'&÷"ÒfÇ6P¢f÷"&öf–ÆR–â‡7FFRævWB‚'W6W'2"’÷"·Ò’çfÇVW2‚“ ¢÷væW%ö–BÒ7G"‡&öf–ÆRævWB‚&Æ–æU÷W6W%ö–B"’÷"""’ç7G&—‚¢WfVçBÒ&öf–ÆRævWB‚&7F—fUö÷fW&GVUöWfVçB"¢–bæ÷B÷væW%ö–B÷"æ÷B—6–ç7Fæ6R†WfVçBÂF–7B’÷"WfVçBævWB‚'&W6öÇfVEöB"“ ¢6¶—VB³Ò¢6öçF–çVP¢–b&öf–ÆRævWB‚&ÖVÖ&W'6†—÷W6VB"’÷"æ÷BÖVÖ&W'6†—ö66W75ö7F—fR‡&öf–ÆRÂæ÷r“ ¢6¶—VB³Ò¢6öçF–çVP¢–b&öf–ÆUö—5÷FöF•ö6†V6¶VB‡&öf–ÆRÂ6öæf–sÖ6öæf–rÂæ÷sÖæ÷r“ ¢WfVçE²'&W6öÇfVEöB%ÒÒæ÷ræ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"¢WfVçE²'7FGW2%ÒÒ&6†V6¶VEö–â ¢&öf–ÆU²&Æ7Eö÷fW&GVUöWfVçB%ÒÒ6÷’æFVW6÷’†WfVçB¢&öf–ÆU²&7F—fUö÷fW&GVUöWfVçB%ÒÒæöæP¢6¶—VB³Ò¢6öçF–çVP¢7F'FVEöBÒ'6UöFFWF–ÖR†WfVçBævWB‚'7F'FVEöB"’¢–bæ÷B7F'FVEöC ¢6¶—VB³Ò¢6öçF–çVP¢–bæ÷rçG¦–æfò—2æöæRæB7F'FVEöBçG¦–æfò—2æ÷BæöæS ¢7F'FVEöBÒ7F'FVEöBç&WÆ6R‡G¦–æfóÔæöæR¢VÆ–bæ÷rçG¦–æfò—2æ÷BæöæRæB7F'FVEöBçG¦–æfò—2æöæS ¢7F'FVEöBÒ7F'FVEöBç&WÆ6R‡G¦–æfóÖæ÷rçG¦–æfò¢VÆ6VEöÖ–çWFW2ÒÖ‚ƒÂ†æ÷rÒ7F'FVEöB’çF÷FÅ÷6V6öæG2‚’òc¢w&6UöÖ–çWFW2Òæ÷&ÖÆ—¦Uöw&6Uö†÷W'2€¢&öf–ÆRævWB‚&w&6Uö†÷W'2"¢’¢c ¢VÆ6VEögFW%öw&6RÒÖ‚ƒÂVÆ6VEöÖ–çWFW2Òw&6UöÖ–çWFW2¢v—EöÖ–çWFW2Òæ÷&ÖÆ—¦Uö÷fW&GVU÷v—EöÖ–çWFW2€¢&öf–ÆRævWB‚&÷fW&GVU÷v—EöÖ–çWFW2"¢¢Æö6F–öâÒ&öf–ÆRævWB‚&Æö6F–öâ"’÷"·Ğ¢Æö6F–öåöÆ–æ²Ò" ¢–b&öf–ÆRævWB‚&GF6…öÆö6F–öåööåöÆW'B"’æBÆö6F–öâævWB‚&ÆF—GVFR"’æBÆö6F–öâævWB‚&Æöæv—GVFR"“ ¢Æö6F–öåöÆ–æ²Òb%ÆîiÈ[èÎKØŞ{ÚîûÉ¦‡GG3¢ò÷wwrævöövÆRæ6öÒöÖ3÷×¶Æö6F–öå²vÆF—GVFRu×ÒÇ¶Æö6F–öå²vÆöæv—GVFRu×Ò  ¢2iÊÎK«®ikÎhù˜i.[èÎiÈZI®XhŞiKnX‹KˆjÊyúŞhù˜i.ûÉ¾KˆŞYºZI®X¾jøşiz^i˜.jë^[»®z¸¾˜xŞŠH~K¨¾K»n8 ¢–bVÆ6VEöÖ–çWFW2ãÒw&6UöÖ–çWFW2æBæ÷BWfVçBævWB‚'6VÆeöföÆÆ÷wW÷6VçEöB"“ ¢6VÆeöÖW76vRÒ€¢b.)ÚNûˆò˜(Nk).iKnX‹KÚy¨N[›>ZèY¹îZÆâ ¢b.Š¸¾›¹îKˆKˆ¾8Îh‰[›>Zè8ŞûÉ¾ˆº^hù˜i.[èÂ·v—EöÖ–çWFW7ÒXˆn™	K¸ŞiÊ®Y¹îhxûÈÂ ¢.{;¾{[iÈ>˜	®yú^zÊÎKˆšnKØŞZèŠÛ~K«®8" ¢¢6VÆeö¶W’Òb'¶WfVçBævWB‚vWfVçEö–Br—Ó§6VÆbÖföÆÆ÷wW ¢G'“ ¢&W7VÇBÒ6VæFW"‡Fö¶VâÂ÷væW%ö–BÂ6VÆeöÖW76vR¢WfVçE²'6VÆeöföÆÆ÷wW÷6VçEöB%ÒÒæ÷ræ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"¢VæEöæ÷F–f–6F–öåöÆör€¢7FFRÂ&÷fW&GVU÷6VÆeöföÆÆ÷wW"Â÷væW%ö–BÂ'6VçB"À¢6VÆeöÖW76vRÂ§6öâæGV×2‡&W7VÇBÂVç7W&Uö66–“ÔfÇ6R’À¢¢&V6÷&EöÆ–æUöÖW76vU÷W6vR€¢7FFRÀ¢6FVv÷'“Ò&÷fW&GVR"À¢÷væW%öÆ–æU÷W6W%ö–CÖ÷væW%ö–BÀ¢&V6—–VçEö6÷VçCÓÀ¢WfVçEö–C×6VÆeö¶W’À¢6VçEöCÖæ÷rÀ¢¢6VçB³Ò¢&W7VÇG2æVæB‡²&Æ–æU÷W6W%ö–B#¢÷væW%ö–BÂ'7FvR#¢'6VÆeöföÆÆ÷wW"Â'&W7VÇB#¢&W7VÇGÒ¢W†6WBW†6WF–öâ2W†3 ¢VæEöæ÷F–f–6F–öåöÆör€¢7FFRÂ&÷fW&GVU÷6VÆeöföÆÆ÷wW"Â÷væW%ö–BÂ&f–ÆVB"À¢6VÆeöÖW76vRÂ7G"†W†2’À¢¢6¶—VB³Ò¢&W7VÇG2æVæB‡²&Æ–æU÷W6W%ö–B#¢÷væW%ö–BÂ'7FvR#¢'6VÆeöföÆÆ÷wW"Â&W'&÷"#¢7G"†W†2—Ò ¢2s“’ZèŠÛ~{êNK¸ŞiŠş˜yJ˜	®˜>ûÉ¾YÊzÊÎKˆšnKØŞX‹iÉşi˜.˜	®yú^KˆjÊûÈÎKˆŞXùnKº>zxK«®šnKØŞ˜	®yú^8 ¢–bVÆ6VEögFW%öw&6RãÒv—EöÖ–çWFW3 ¢'VÆW2ÒÆå÷'VÆW2‡&öf–ÆRÂæ÷r¢w&÷WöÆ–Ö—BÒ–çB‡'VÆW2ævWB‚&wV&F–åöw&÷WöÆ–Ö—B"’÷"¢w&÷W2Ò7FFRævWB‚&wV&F–åöw&÷W2"’÷"·Ğ¢æ÷F–f–VEöw&÷Wö–G2ÒWfVçBç6WFFVfVÇB‚&æ÷F–f–VEöw&÷Wö–G2"ÂµÒ¢7F—fUöw&÷Wö–G2Ò°¢w&÷Wö–@¢f÷"w&÷Wö–B–â‡&öf–ÆRævWB‚&wV&F–åöw&÷Wö–G2"’÷"µÒ¢–bw&÷Wö–Bæ÷B–âæ÷F–f–VEöw&÷Wö–G0¢æBw&÷W2ævWB†w&÷Wö–BÂ·Ò’ævWB‚&÷væW%öÆ–æU÷W6W%ö–B"’ÓÒ÷væW%ö–@¢æBw&÷W2ævWB†w&÷Wö–BÂ·Ò’ævWB‚'7FGW2"’ÓÒ&7F—fR ¢æBwV&F–åöw&÷W÷&VfW&Væ6R€¢w&÷W2ævWB†w&÷Wö–B’Â&æ÷F–g•öw&÷Wööåö÷fW&GVR ¢¢Õ³¦w&÷WöÆ–Ö—EĞ¢w&÷WöÖW76vRÒ€¢b.)ªûˆş8	ZKˆşš	ŠÚn8	·&öf–ÆRævWB‚vF—7Æ•öæÖRr’÷"~h‰Y:wÒYÊhù˜i.[èÂ ¢b'·v—EöÖ–çWFW7ÒXˆn™	K¸ŞiÊ®Y¹îZ[›>ZèûÈÎŠ¸¾{êNXZ~XÙNXªz+®Š¨Ş8'¶Æö6F–öåöÆ–æ·Ò ¢¢f÷"w&÷Wö–B–â7F—fUöw&÷Wö–G3 ¢FVÆ—fW'•ö¶W’Òb'¶WfVçBævWB‚vWfVçEö–Br—Ó¦w&÷W§¶w&÷Wö–GÒ ¢G'“ ¢&W7VÇBÒ6VæFW"‡Fö¶VâÂw&÷Wö–BÂw&÷WöÖW76vR¢æ÷F–f–VEöw&÷Wö–G2æVæB†w&÷Wö–B¢VæEöæ÷F–f–6F–öåöÆör€¢7FFRÂ&÷fW&GVUöwV&F–åöw&÷W"Âw&÷Wö–BÂ'6VçB"À¢w&÷WöÖW76vRÂ§6öâæGV×2‡&W7VÇBÂVç7W&Uö66–“ÔfÇ6R’À¢¢&V6÷&EöÆ–æUöÖW76vU÷W6vR€¢7FFRÀ¢6FVv÷'“Ò&÷fW&GVR"À¢÷væW%öÆ–æU÷W6W%ö–CÖ÷væW%ö–BÀ¢&V6—–VçEö6÷VçCÓÀ¢WfVçEö–CÖFVÆ—fW'•ö¶W’À¢6VçEöCÖæ÷rÀ¢¢6VçB³Ò¢&W7VÇG2æVæB‡°¢&w&÷Wö–B#¢w&÷Wö–BÀ¢'7FvR#¢&wV&F–åöw&÷W"À¢'&W7VÇB#¢&W7VÇBÀ¢Ò¢W†6WBW†6WF–öâ2W†3 ¢VæEöæ÷F–f–6F–öåöÆör€¢7FFRÂ&÷fW&GVUöwV&F–åöw&÷W"Âw&÷Wö–BÂ&f–ÆVB"À¢w&÷WöÖW76vRÂ7G"†W†2’À¢¢6¶—VB³Ò¢&W7VÇG2æVæB‡°¢&w&÷Wö–B#¢w&÷Wö–BÀ¢'7FvR#¢&wV&F–åöw&÷W"À¢&W'&÷"#¢7G"†W†2’À¢Ò ¢7W'&VçE÷7FvRÒ–çB†WfVçBævWB‚&wV&F–å÷7FvR"’÷"¢GVU÷7FvRÒæW‡B€¢€¢7FvP¢f÷"7FvR–âƒÂ"Â2¢–b7FvRâ7W'&VçE÷7FvP¢æBVÆ6VEögFW%öw&6RãÒv—EöÖ–çWFW2¢7FvP¢’À¢æöæRÀ¢¢–bGVU÷7FvR—2æöæS ¢6öçF–çVP¢–bæ÷B6†÷VÆEöæ÷F–g•÷&—fFUöwV&F–ç2‡7FFRÂ&öf–ÆR“ ¢WfVçE²&wV&F–å÷7FvR%ÒÒGVU÷7FvP¢6¶—VB³Ò¢6öçF–çVP¢wV&F–ç2Ò&æ¶VEö÷fW&GVUöwV&F–ç2‡&öf–ÆR¢–bGVU÷7FvRâÆVâ†wV&F–ç2“ ¢WfVçE²&wV&F–å÷7FvR%ÒÒGVU÷7FvP¢6¶—VB³Ò¢6öçF–çVP¢6öçF7BÒwV&F–ç5¶GVU÷7FvRÒĞ¢F&vWBÒvWEö6öçF7EöÆ–æUö–B†6öçF7B¢6öçF7EöæÖRÒ7G"†6öçF7BævWB‚&æÖR"’÷"6öçF7BævWB‚'&VÆF–öç6†—"’÷"b.zÊÂ¶GVU÷7FvWÒšnKØŞZèŠÛ~K«¢"¢6öçF7EöÖW76vRÒ€¢b.)ªûˆş8	zÊÂ¶GVU÷7FvWÒšnKØŞiÊ®Z[›>Zè˜	®yú^8	 ¢b'·&öf–ÆRævWB‚vF—7Æ•öæÖRr’÷"~KÚy¨NŠj®Xø²wÒYÊhù˜i.[èÂ ¢b'·v—EöÖ–çWFW2¢GVU÷7FvWÒXˆn™	K¸ŞiÊ®Y¹îZ[›>ZèûÈÎŠ¸¾XÙNXªz+®Š¨Ş8" ¢b'¶Æö6F–öåöÆ–æ·Ò ¢¢FVÆ—fW'•ö¶W’Òb'¶WfVçBævWB‚vWfVçEö–Br—Ó¦wV&F–ã§¶GVU÷7FvWÓ§·F&vWGÒ ¢G'“ ¢&W7VÇBÒ6VæFW"‡Fö¶VâÂF&vWBÂ6öçF7EöÖW76vR¢WfVçE²&wV&F–å÷7FvR%ÒÒGVU÷7FvP¢WfVçBç6WFFVfVÇB‚&æ÷F–f–VEöwV&F–åö–G2"ÂµÒ’æVæB‡F&vWB¢VæEöæ÷F–f–6F–öåöÆör€¢7FFRÂ&6öçF7EöÆW'B"ÂF&vWBÂ'6VçB"À¢6öçF7EöÖW76vRÂ§6öâæGV×2‡&W7VÇBÂVç7W&Uö66–“ÔfÇ6R’À¢¢&V6÷&EöÆ–æUöÖW76vU÷W6vR€¢7FFRÀ¢6FVv÷'“Ò&÷fW&GVR"À¢÷væW%öÆ–æU÷W6W%ö–CÖ÷væW%ö–BÀ¢&V6—–VçEö6÷VçCÓÀ¢WfVçEö–CÖFVÆ—fW'•ö¶W’À¢6VçEöCÖæ÷rÀ¢¢6VçB³Ò¢&W7VÇG2æVæB‡°¢&Æ–æU÷W6W%ö–B#¢F&vWBÀ¢&F—7Æ•öæÖR#¢6öçF7EöæÖRÀ¢'7FvR#¢GVU÷7FvRÀ¢'&W7VÇB#¢&W7VÇBÀ¢Ò¢W†6WBW†6WF–öâ2W†3 ¢VæEöæ÷F–f–6F–öåöÆör€¢7FFRÂ&6öçF7EöÆW'B"ÂF&vWBÂ&f–ÆVB"À¢6öçF7EöÖW76vRÂ7G"†W†2’À¢¢6¶—VB³Ò¢&W7VÇG2æVæB‡°¢&Æ–æU÷W6W%ö–B#¢F&vWBÀ¢&F—7Æ•öæÖR#¢6öçF7EöæÖRÀ¢'7FvR#¢GVU÷7FvRÀ¢&W'&÷"#¢7G"†W†2’À¢Ò ¢6fU÷7FFR†6öæf–u²$DDôd”ÄR%ÒÂ7FFR¢&WGW&â°¢'6VçB#¢6VçBÀ¢'6¶—VB#¢6¶—VBÀ¢'&W7VÇG2#¢&W7VÇG2À¢'7—7FVÕöW'&÷"#¢7—7FVÕöW'&÷"À¢ÒÂ#   ¦FVb6VæEöwV&F–åöw&÷WöF–Ç•÷7VÖÖ&–W2†6öæf–r“ ¢"".˜yJûÉ®ZèŠÛ~{êNX»î˜8Î{êN{XNjøşiz^iŠh8Şi˜.ûÈÎikÎi™®™i>hêi*ŞK¸®iz^[{.ZûÈşiÊ®ZûÈš	ŠŠŞ™yÎ™hûÈ8""" ¢Fö¶VâÒ6öæf–rævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"’÷"÷2æVçf—&öâævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"Â""¢–bæ÷BFö¶Vã ¢&WGW&â²'6VçB#¢Â'6¶—VB#¢Â&W'&÷"#¢$Ä”äUô4„ääTÅô44U55õDô´Tâ—2æ÷B6WB'ÒÂC  ¢7FFRÒÆöE÷7FFR†6öæf–u²$DDôd”ÄR%Ò¢6VæFW"Ò6öæf–rævWB‚$Ä”äUõU4…õ4TäDU""’÷"Æ–æU÷W6…öÖW76vP¢æ÷rÒ7W'&VçEö÷F–ÖR†6öæf–r¢FöF’Òæ÷rç7G&gF–ÖR‚"U’ÒVÒÒVB"¢W6W'2Ò7FFRævWB‚'W6W'2"’÷"·Ğ¢w&÷W2Ò7FFRævWB‚&wV&F–åöw&÷W2"’÷"·Ğ¢6VçBÒ ¢6¶—VBÒ ¢&W7VÇG2ÒµĞ¢7—7FVÕöW'&÷"ÒfÇ6P¢FVfW'&VBÒ ¢ÖVÖ&W%öfWF6†W"Ò6öæf–rævWB‚$u$õUôÔTÔ$U%ô”E5ôdUD4„U""’÷"vWEöw&÷WöÖVÖ&W%ö–G0¢f÷"w&÷Wö–BÂw&÷W–âÆ—7B†w&÷W2æ—FV×2‚’“ ¢–bæ÷B—6–ç7Fæ6R†w&÷WÂF–7B’÷"w&÷WævWB‚'7FGW2"’Ò&7F—fR# ¢6¶—VB³Ò¢6öçF–çVP¢÷væW"ÒW6W'2ævWB‡7G"†w&÷WævWB‚&÷væW%öÆ–æU÷W6W%ö–B"’÷"""’ç7G&—‚’’÷"·Ğ¢–b€¢æ÷BwV&F–åöw&÷WöVçF—FÆVÖVçEö7F—fR†÷væW"Âæ÷r¢“ ¢6¶—VB³Ò¢&W7VÇG2æVæB‡²&w&÷Wö–B#¢w&÷Wö–BÂ'7FGW2#¢&÷væW%öæ÷EöVÆ–v–&ÆR'Ò¢6öçF–çVP¢&Vg2Òæ÷&ÖÆ—¦UöwV&F–åöw&÷W÷&VfW&Væ6W2†w&÷WævWB‚'&VfW&Væ6W2"’¢–bæ÷B&Vg2ævWB‚&F–Ç•öFÖ–å÷7VÖÖ'’"“ ¢6¶—VB³Ò¢6öçF–çVP¢7VÖÖ'•÷F–ÖRÒ7G"‡&Vg2ævWB‚&F–Ç•÷7VÖÖ'•÷F–ÖR"’÷"##£"¢7W'&VçEö†ÒÒæ÷rç7G&gF–ÖR‚"Tƒ¢TÒ"¢–b7W'&VçEö†ÒÂ7VÖÖ'•÷F–ÖS ¢FVfW'&VB³Ò¢6öçF–çVP¢–bw&÷WævWB‚&Æ7EöF–Ç•÷7VÖÖ'•öFFR"’ÓÒFöF“ ¢6¶—VB³Ò¢6öçF–çVP¢FVÆ—fW'•ö¶W’Òb&wV&F–åöw&÷WöF–Ç•÷7VÖÖ'“§·FöF—Ó§¶w&÷Wö–GÒ ¢–bæ÷BW6…öGFV×EöÆÆ÷vVB†w&÷WÂFVÆ—fW'•ö¶W’“ ¢6¶—VB³Ò¢6öçF–çVP¢6Æ–Õ÷&W7VÇBÒ×WFFU÷7FFUöFöÖ–6ÆÇ’€¢6öæf–u²$DDôd”ÄR%ÒÀ¢ÆÖ&F7W'&VçE÷7FFS¢ö6Æ–ÕöwV&F–åöw&÷W÷7VÖÖ'’€¢7W'&VçE÷7FFRÂw&÷Wö–BÂFöF’Âæ÷p¢’À¢¢–bæ÷B6Æ–Õ÷&W7VÇBævWB‚&6Æ–ÖVB"“ ¢6¶—VB³Ò¢&W7VÇG2æVæB‡²&w&÷Wö–B#¢w&÷Wö–BÂ'7FGW2#¢&Ç&VG•ö6Æ–ÖVB'Ò¢6öçF–çVP¢6Æ–Õ÷Fö¶VâÒ6Æ–Õ÷&W7VÇE²&6Æ–Õ÷Fö¶Vâ%Ğ¢G'“ ¢7W'&VçEö–G2ÒæöæP¢ÖVÖ&W%öW'&÷"ÒæöæP¢f÷"öGFV×B–â&ævRƒ2“ ¢G'“ ¢7W'&VçEö–G2ÒÖVÖ&W%öfWF6†W"‡Fö¶VâÂw&÷Wö–B¢–b7W'&VçEö–G2—2æ÷BæöæS ¢ÖVÖ&W%öW'&÷"ÒæöæP¢'&V°¢ÖVÖ&W%öW'&÷"Ò'VçF–ÖTW'&÷"‚$Ä”äRÖVÖ&W"Æ—7BVæf–Æ&ÆR"¢W†6WBW†6WF–öâ2W†3 ¢ÖVÖ&W%öW'&÷"ÒW†0¢–b7W'&VçEö–G2—2æöæS ¢×WFFU÷7FFUöFöÖ–6ÆÇ’€¢6öæf–u²$DDôd”ÄR%ÒÀ¢ÆÖ&F7W'&VçE÷7FFS¢öf–æ—6…öwV&F–åöw&÷W÷7VÖÖ'’€¢7W'&VçE÷7FFRÀ¢w&÷Wö–BÀ¢FöF’À¢æ÷rÀ¢6Æ–Õ÷Fö¶VãÖ6Æ–Õ÷Fö¶VâÀ¢&VÆV6UööæÇ“ÕG'VRÀ¢VF—Eö¶–æCÒ&wV&F–åöw&÷WöÖVÖ&W%÷&Vg&W6‚"À¢VF—E÷7FGW3Ò&f–ÆVB"À¢VF—EöFWF–Ã×7G"†ÖVÖ&W%öW'&÷"÷"&ÖVÖ&W"&Vg&W6‚f–ÆVB"•³£CÒÀ¢’À¢¢6¶—VB³Ò¢&W7VÇG2æVæB‡°¢&w&÷Wö–B#¢w&÷Wö–BÀ¢'7FGW2#¢&ÖVÖ&W%÷&Vg&W6…öf–ÆVB"À¢&W'&÷"#¢7G"†ÖVÖ&W%öW'&÷"÷"""•³£CÒÀ¢Ò¢6öçF–çVP¢W†6WBW†6WF–öã ¢×WFFU÷7FFUöFöÖ–6ÆÇ’€¢6öæf–u²$DDôd”ÄR%ÒÀ¢ÆÖ&F7W'&VçE÷7FFS¢öf–æ—6…öwV&F–åöw&÷W÷7VÖÖ'’€¢7W'&VçE÷7FFRÀ¢w&÷Wö–BÀ¢FöF’À¢æ÷rÀ¢6Æ–Õ÷Fö¶VãÖ6Æ–Õ÷Fö¶VâÀ¢&VÆV6UööæÇ“ÕG'VRÀ¢’À¢¢&—6P¢ÖVÖ&W%ö–G2ÒÆ—7B†F–7Bæg&öÖ¶W—2€¢7G"‡V–B÷"""’ç7G&—‚’f÷"V–B–â7W'&VçEö–G2–b7G"‡V–B÷"""’ç7G&—‚¢’¢&W&VBÒ×WFFU÷7FFUöFöÖ–6ÆÇ’€¢6öæf–u²$DDôd”ÄR%ÒÀ¢ÆÖ&F7W'&VçE÷7FFS¢÷&W&UöwV&F–åöw&÷W÷7VÖÖ'’€¢7W'&VçE÷7FFRÀ¢w&÷Wö–BÀ¢FöF’À¢æ÷rÀ¢6Æ–Õ÷Fö¶VâÀ¢ÖVÖ&W%ö–G2À¢’À¢¢VÆ–v–&ÆUöÖVÖ&W'2Ò&W&VBævWB‚&VÆ–v–&ÆUöÖVÖ&W'2"’÷"µĞ¢–bæ÷B&W&VBævWB‚'&VG’"“ ¢6¶—VB³Ò¢&W7VÇG2æVæB‡°¢&w&÷Wö–B#¢w&÷Wö–BÀ¢'7FGW2#¢&W&VBævWB‚'&V6öâ"’÷"&æõöÆöævW%öVÆ–v–&ÆR"À¢Ò¢6öçF–çVP¢–bæ÷BVÆ–v–&ÆUöÖVÖ&W'3 ¢×WFFU÷7FFUöFöÖ–6ÆÇ’€¢6öæf–u²$DDôd”ÄR%ÒÀ¢ÆÖ&F7W'&VçE÷7FFS¢öf–æ—6…öwV&F–åöw&÷W÷7VÖÖ'’€¢7W'&VçE÷7FFRÀ¢w&÷Wö–BÀ¢FöF’À¢æ÷rÀ¢6Æ–Õ÷Fö¶VãÖ6Æ–Õ÷Fö¶VâÀ¢&VÆV6UööæÇ“ÕG'VRÀ¢ÖVÖ&W%ö–G3ÖÖVÖ&W%ö–G2À¢’À¢¢6¶—VB³Ò¢&W7VÇG2æVæB‡²&w&÷Wö–B#¢w&÷Wö–BÂ'7FGW2#¢&æõöVÆ–v–&ÆUöÖVÖ&W'2'Ò¢6öçF–çVP¢6†V6¶VBÒµĞ¢Væ6†V6¶VBÒµĞ¢f÷"ÖVÖ&W"–âVÆ–v–&ÆUöÖVÖ&W'3 ¢&öf–ÆRÒÖVÖ&W%²'&öf–ÆR%Ğ¢æÖRÒÖVÖ&W%²&æÖR%Ğ¢†6†V6¶VB–böÖVÖ&W%ö6†V6¶VE÷FöF’‡&öf–ÆRÂFöF’’VÇ6RVæ6†V6¶VB’æVæB†æÖR¢ÖW76vRÒ€¢b/	ù8¢K¸®iz^[›>ZèiŠhûÈ‡·FöF—ŞûÈ•Æâ ¢b.[{.Z[›>ZèûÉ§²rÂræ¦ö–â†6†V6¶VB’–b6†V6¶VBVÇ6R~[	®xJwÕÆâ ¢b.[	®iÊ®Z[›>ZèûÉ§²rÂræ¦ö–â‡Væ6†V6¶VB’–bVæ6†V6¶VBVÇ6R~yºîX˜Ş˜;Ş[{.ZèÎh‰wÕÆåÆâ ¢.ûÈjÚNx+®˜yJ{êN{XNiŠhûÉ¾™yÎ™h[èÎXú®iÈ>zxŠˆ®j[ø>ZèŠÛ~K«®8.ûÈ’ ¢¢G'“ ¢–b6VæFW"—2Æ–æU÷W6…öÖW76vS ¢&W7VÇBÒ6VæFW"€¢Fö¶VâÀ¢w&÷Wö–BÀ¢ÖW76vRÀ¢&WG'•ö¶W“ÕöÆ–æU÷&WG'•ö¶W’†FVÆ—fW'•ö¶W’’À¢¢VÇ6S ¢&W7VÇBÒ6VæFW"‡Fö¶VâÂw&÷Wö–BÂÖW76vR¢×WFFU÷7FFUöFöÖ–6ÆÇ’€¢6öæf–u²$DDôd”ÄR%ÒÀ¢ÆÖ&F7W'&VçE÷7FFS¢öf–æ—6…öwV&F–åöw&÷W÷7VÖÖ'’€¢7W'&VçE÷7FFRÀ¢w&÷Wö–BÀ¢FöF’À¢æ÷rÀ¢6Æ–Õ÷Fö¶VãÖ6Æ–Õ÷Fö¶VâÀ¢6VçCÕG'VRÀ¢ÖW76vSÖÖW76vRÀ¢&W7VÇC×&W7VÇBÀ¢ÖVÖ&W%ö–G3ÖÖVÖ&W%ö–G2À¢’À¢¢6VçB³Ò¢&W7VÇG2æVæB‡²&w&÷Wö–B#¢w&÷Wö–BÂ'&W7VÇB#¢&W7VÇGÒ¢W†6WBW†6WF–öâ2W†3 ¢f–ÇW&RÒ×WFFU÷7FFUöFöÖ–6ÆÇ’€¢6öæf–u²$DDôd”ÄR%ÒÀ¢ÆÖ&F7W'&VçE÷7FFS¢öf–æ—6…öwV&F–åöw&÷W÷7VÖÖ'’€¢7W'&VçE÷7FFRÀ¢w&÷Wö–BÀ¢FöF’À¢æ÷rÀ¢6Æ–Õ÷Fö¶VãÖ6Æ–Õ÷Fö¶VâÀ¢ÖW76vSÖÖW76vRÀ¢W'&÷#ÖW†2À¢ÖVÖ&W%ö–G3ÖÖVÖ&W%ö–G2À¢’À¢¢6¶—VB³Ò¢&W7VÇG2æVæB‡²&w&÷Wö–B#¢w&÷Wö–BÂ&W'&÷"#¢7G"†W†2—Ò¢–bf–ÇW&U²&¶–æB%ÒÓÒ'7—7FVÒ# ¢7—7FVÕöW'&÷"ÒG'VP¢'&V° ¢&WGW&â°¢'6VçB#¢6VçBÀ¢'6¶—VB#¢6¶—VBÀ¢&FVfW'&VB#¢FVfW'&VBÀ¢'&W7VÇG2#¢&W7VÇG2À¢&FFR#¢FöF’À¢'7—7FVÕöW'&÷"#¢7—7FVÕöW'&÷"À¢ÒÂ#   ¦FVböÆ–æU÷&WG'•ö¶W’†FVÆ—fW'•ö¶W’“ ¢""%7F&ÆRUT”B66WFVB'’Ä”äRf÷"–FV×÷FVçB&WG&–W2öböæRÆöv–6ÂW6‚â"" ¢&WGW&â7G"‡WV–BçWV–CR‡WV–BääÔU54UõU$ÂÂb&F–Ç’×V6S§¶FVÆ—fW'•ö¶W—Ò"’  ¦FVbö6Æ–ÕöwV&F–åöw&÷W÷7VÖÖ'’‡7FFRÂw&÷Wö–BÂFöF’Âæ÷r“ ¢w&÷WÒ‡7FFRævWB‚&wV&F–åöw&÷W2"’÷"·Ò’ævWB†w&÷Wö–B¢–bæ÷B—6–ç7Fæ6R†w&÷WÂF–7B“ ¢&WGW&â²&6Æ–ÖVB#¢fÇ6RÂ'&V6öâ#¢&w&÷Wöæ÷Eöf÷VæB'Ğ¢÷væW"Ò‡7FFRævWB‚'W6W'2"’÷"·Ò’ævWB€¢7G"†w&÷WævWB‚&÷væW%öÆ–æU÷W6W%ö–B"’÷"""’ç7G&—‚¢’÷"·Ğ¢&Vg2Òæ÷&ÖÆ—¦UöwV&F–åöw&÷W÷&VfW&Væ6W2†w&÷WævWB‚'&VfW&Væ6W2"’¢–b€¢w&÷WævWB‚'7FGW2"’Ò&7F—fR ¢÷"æ÷B&Vg2ævWB‚&F–Ç•öFÖ–å÷7VÖÖ'’"¢÷"æ÷BwV&F–åöw&÷WöVçF—FÆVÖVçEö7F—fR†÷væW"Âæ÷r¢“ ¢&WGW&â²&6Æ–ÖVB#¢fÇ6RÂ'&V6öâ#¢&æõöÆöævW%öVÆ–v–&ÆR'Ğ¢–bw&÷WævWB‚&Æ7EöF–Ç•÷7VÖÖ'•öFFR"’ÓÒFöF“ ¢&WGW&â²&6Æ–ÖVB#¢fÇ6WĞ¢6Æ–×2ÒF–7B†w&÷WævWB‚&F–Ç•÷7VÖÖ'•ö6Æ–×2"’÷"·Ò¢W†—7F–ærÒ6Æ–×2ævWB‡FöF’’÷"·Ğ¢–bW†—7F–æs ¢6Æ–ÖVEöBÒæöæP¢G'“ ¢6Æ–ÖVEöBÒFFWF–ÖRæg&öÖ—6öf÷&ÖB‡7G"†W†—7F–ærævWB‚&6Æ–ÖVEöB"’÷"""’¢W†6WB…G—TW'&÷"ÂfÇVTW'&÷"“ ¢6Æ–ÖVEöBÒæöæP¢–b6Æ–ÖVEöB—2æ÷BæöæRæB†æ÷rÒ6Æ–ÖVEöB’çF÷FÅ÷6V6öæG2‚’Â“ ¢&WGW&â²&6Æ–ÖVB#¢fÇ6RÂ'&V6öâ#¢&7F—fUö6Æ–Ò'Ğ¢6Æ–Õ÷Fö¶VâÒ6V7&WG2çFö¶Våö†W‚ƒb¢6Æ–×5·FöF•ÒÒ°¢&6Æ–ÖVEöB#¢æ÷ræ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"’À¢&6Æ–Õ÷Fö¶Vâ#¢6Æ–Õ÷Fö¶VâÀ¢Ğ¢w&÷W²&F–Ç•÷7VÖÖ'•ö6Æ–×2%ÒÒ6Æ–×0¢&WGW&â°¢&6Æ–ÖVB#¢G'VRÀ¢'&V6÷fW&VB#¢&ööÂ†W†—7F–ær’À¢&6Æ–Õ÷Fö¶Vâ#¢6Æ–Õ÷Fö¶VâÀ¢Ğ  ¦FVb÷&W&UöwV&F–åöw&÷W÷7VÖÖ'’€¢7FFRÂw&÷Wö–BÂFöF’Âæ÷rÂ6Æ–Õ÷Fö¶VâÂÖVÖ&W%ö–G0¢“ ¢w&÷WÒ‡7FFRævWB‚&wV&F–åöw&÷W2"’÷"·Ò’ævWB†w&÷Wö–B¢6Æ–ÒÒ‚†w&÷W÷"·Ò’ævWB‚&F–Ç•÷7VÖÖ'•ö6Æ–×2"’÷"·Ò’ævWB‡FöF’’÷"·Ğ¢–bæ÷B—6–ç7Fæ6R†w&÷WÂF–7B’÷"6Æ–ÒævWB‚&6Æ–Õ÷Fö¶Vâ"’Ò6Æ–Õ÷Fö¶Vã ¢&WGW&â²'&VG’#¢fÇ6RÂ'&V6öâ#¢&6Æ–ÕöÆ÷7B'Ğ¢÷væW"Ò‡7FFRævWB‚'W6W'2"’÷"·Ò’ævWB€¢7G"†w&÷WævWB‚&÷væW%öÆ–æU÷W6W%ö–B"’÷"""’ç7G&—‚¢’÷"·Ğ¢&Vg2Òæ÷&ÖÆ—¦UöwV&F–åöw&÷W÷&VfW&Væ6W2†w&÷WævWB‚'&VfW&Væ6W2"’¢–b€¢w&÷WævWB‚'7FGW2"’Ò&7F—fR ¢÷"æ÷B&Vg2ævWB‚&F–Ç•öFÖ–å÷7VÖÖ'’"¢÷"æ÷BwV&F–åöw&÷WöVçF—FÆVÖVçEö7F—fR†÷væW"Âæ÷r¢“ ¢öf–æ—6…öwV&F–åöw&÷W÷7VÖÖ'’€¢7FFRÀ¢w&÷Wö–BÀ¢FöF’À¢æ÷rÀ¢6Æ–Õ÷Fö¶VãÖ6Æ–Õ÷Fö¶VâÀ¢&VÆV6UööæÇ“ÕG'VRÀ¢¢&WGW&â²'&VG’#¢fÇ6RÂ'&V6öâ#¢&æõöÆöævW%öVÆ–v–&ÆR'Ğ¢w&÷W²&ÖVÖ&W%ö–G5öÆ7E÷7VÖÖ'’%ÒÒÆ—7B†ÖVÖ&W%ö–G2¢w&÷W²&ÖVÖ&W%ö–G5öÆ7E÷7VÖÖ'•öB%ÒÒæ÷ræ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"¢&WGW&â°¢'&VG’#¢G'VRÀ¢&VÆ–v–&ÆUöÖVÖ&W'2#¢VÆ–v–&ÆUöwV&F–åöw&÷W÷7VÖÖ'•öÖVÖ&W'2€¢7FFRÂw&÷WÂÖVÖ&W%ö–G0¢’À¢Ğ  ¦FVböf–æ—6…öwV&F–åöw&÷W÷7VÖÖ'’€¢7FFRÀ¢w&÷Wö–BÀ¢FöF’À¢æ÷rÀ¢¢À¢6Æ–Õ÷Fö¶VâÀ¢6VçCÔfÇ6RÀ¢&VÆV6UööæÇ“ÔfÇ6RÀ¢ÖW76vSÒ""À¢&W7VÇCÔæöæRÀ¢W'&÷#ÔæöæRÀ¢ÖVÖ&W%ö–G3ÔæöæRÀ¢VF—Eö¶–æCÔæöæRÀ¢VF—E÷7FGW3ÔæöæRÀ¢VF—EöFWF–ÃÔæöæRÀ¢“ ¢w&÷WÒ‡7FFRævWB‚&wV&F–åöw&÷W2"’÷"·Ò’ævWB†w&÷Wö–B¢–bæ÷B—6–ç7Fæ6R†w&÷WÂF–7B“ ¢&WGW&â²&¶–æB#¢'W&ÖæVçB"Â'&WG'’#¢fÇ6WĞ¢6Æ–×2ÒF–7B†w&÷WævWB‚&F–Ç•÷7VÖÖ'•ö6Æ–×2"’÷"·Ò¢6Æ–ÒÒ6Æ–×2ævWB‡FöF’’÷"·Ğ¢–b6Æ–ÒævWB‚&6Æ–Õ÷Fö¶Vâ"’Ò6Æ–Õ÷Fö¶Vã ¢&WGW&â²&¶–æB#¢&6Æ–ÕöÆ÷7B"Â'&WG'’#¢fÇ6WĞ¢6Æ–×2ç÷‡FöF’ÂæöæR¢–b6Æ–×3 ¢w&÷W²&F–Ç•÷7VÖÖ'•ö6Æ–×2%ÒÒ6Æ–×0¢VÇ6S ¢w&÷Wç÷‚&F–Ç•÷7VÖÖ'•ö6Æ–×2"ÂæöæR¢–bÖVÖ&W%ö–G2—2æ÷BæöæS ¢w&÷W²&ÖVÖ&W%ö–G5öÆ7E÷7VÖÖ'’%ÒÒÆ—7B†ÖVÖ&W%ö–G2¢w&÷W²&ÖVÖ&W%ö–G5öÆ7E÷7VÖÖ'•öB%ÒÒæ÷ræ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"¢–bVF—Eö¶–æC ¢VæEöæ÷F–f–6F–öåöÆör€¢7FFRÀ¢VF—Eö¶–æBÀ¢w&÷Wö–BÀ¢VF—E÷7FGW2÷"&f–ÆVB"À¢""À¢VF—EöFWF–ÂÀ¢¢–b&VÆV6UööæÇ“ ¢&WGW&â²'&VÆV6VB#¢G'VWĞ¢FVÆ—fW'•ö¶W’Òb&wV&F–åöw&÷WöF–Ç•÷7VÖÖ'“§·FöF—Ó§¶w&÷Wö–GÒ ¢–b6VçC ¢ö6ÆV%÷W6…öFVÆ—fW'•öf–ÇW&R†w&÷WÂFVÆ—fW'•ö¶W’¢VæEöæ÷F–f–6F–öåöÆör€¢7FFRÀ¢&wV&F–åöw&÷WöF–Ç•÷7VÖÖ'’"À¢w&÷Wö–BÀ¢'6VçB"À¢ÖW76vRÀ¢§6öâæGV×2‡&W7VÇBÂVç7W&Uö66–“ÔfÇ6R’À¢¢&V6÷&EöÆ–æUöÖW76vU÷W6vR€¢7FFRÀ¢6FVv÷'“Ò&wV&F–å÷7VÖÖ'’"À¢÷væW%öÆ–æU÷W6W%ö–CÖw&÷WævWB‚&÷væW%öÆ–æU÷W6W%ö–B"’÷"w&÷Wö–BÀ¢&V6—–VçEö6÷VçCÖÖ‚ƒÂÆVâ†ÖVÖ&W%ö–G2÷"µÒ’’À¢WfVçEö–CÖFVÆ—fW'•ö¶W’À¢6VçEöCÖæ÷rÀ¢¢w&÷W²&Æ7EöF–Ç•÷7VÖÖ'•öFFR%ÒÒFöF¢&WGW&â²'6VçB#¢G'VWĞ¢&WGW&â÷&V6÷&E÷66†VGVÆVE÷W6…öf–ÇW&R€¢7FFRÀ¢w&÷WÀ¢FVÆ—fW'•ö¶W’À¢&wV&F–åöw&÷WöF–Ç•÷7VÖÖ'’"À¢w&÷Wö–BÀ¢ÖW76vRÀ¢W'&÷"À¢æ÷rÀ¢  ¦FVb'V–ÆEöÖ—76–æuöwV&F–åöfÆW‚‡&öf–ÆSÔæöæR“ ¢""%v&ÒÄ”äRfÆW‚6&B–çf—F–ærÖVÖ&W"Fò&–æBF†V—"f—'7BwV&F–ââ"" ¢ÖVÖ&W%öæÖRÒ7G"‚‡&öf–ÆR÷"·Ò’ævWB‚&F—7Æ•öæÖR"’÷".KÚ"’ç7G&—‚’÷".KÚ ¢–çf—FU÷W&’Ò€¢6†&Uö–çf—FUöÆ–fe÷W&Â‚¢–b6†&Uö–çf—FUöÆ–fe÷W&À¢VÇ6R&‡GG3¢òöÆ–fbæÆ–æRæÖRó#ƒCƒ33ÕT—”BöÆ–fb÷6†&RÖ–çf—FRæ‡FÖÂ ¢¢&WGW&â°¢'G—R#¢&fÆW‚"À¢&ÇEFW‡B#¢.jøşiz^[›>ZèûÙÎ˜(Š¸¾KˆKØŞKúK»¾y¨NZèŠÛ~K«¢"À¢&6öçFVçG2#¢°¢'G—R#¢&'V&&ÆR"À¢'6—¦R#¢&ÖVv"À¢&†W&ò#¢°¢'G—R#¢&–ÖvR"À¢'W&Â#¢&‡GG3¢òöÆ—fRÖ6†V6¶–âæöç&VæFW"æ6öÒö76WG2öwV&F–â×7F÷'’ÖÖ÷F†W"ÖFVv‡FW"çvV'"À¢'6—¦R#¢&gVÆÂ"À¢&7V7E&F–ò#¢##£2"À¢&7V7DÖöFR#¢&6÷fW""À¢ÒÀ¢&†VFW"#¢°¢'G—R#¢&&÷‚"À¢&Æ–÷WB#¢'fW'F–6Â"À¢&&6¶w&÷VæD6öÆ÷"#¢"4TctTR"À¢'FF–ætÆÂ#¢'†Â"À¢&6öçFVçG2#¢°¢°¢'G—R#¢'FW‡B"À¢'FW‡B#¢.jøşiz^[›>Zè’"À¢'6—¦R#¢&ÖB"À¢'vV–v‡B#¢&&öÆB"À¢&6öÆ÷"#¢"3Sƒ4B"À¢ÒÀ¢°¢'G—R#¢'FW‡B"À¢'FW‡B#¢/	ù)¢Šé>x›Şhé¾ûÈÎiÈKˆX¾Zè[ø>y¨NXë¾‰™R"À¢'6—¦R#¢'†Â"À¢'vV–v‡B#¢&&öÆB"À¢&6öÆ÷"#¢"3CS3$B"À¢'w&#¢G'VRÀ¢&Ö&v–â#¢&ÖB"À¢ÒÀ¢ÒÀ¢ÒÀ¢&&öG’#¢°¢'G—R#¢&&÷‚"À¢&Æ–÷WB#¢'fW'F–6Â"À¢'76–ær#¢&Ær"À¢'FF–ætÆÂ#¢'†Â"À¢&&6¶w&÷VæD6öÆ÷"#¢"4ddd4cR"À¢&6öçFVçG2#¢°¢°¢'G—R#¢'FW‡B"À¢'FW‡B#¢b'¶ÖVÖ&W%öæÖWŞûÈÎyºîX˜Ş˜(Nk).iÈZèÎh‰ZèŠÛ~K«®{hZé®8""À¢'6—¦R#¢&Ær"À¢'vV–v‡B#¢&&öÆB"À¢&6öÆ÷"#¢"34c43""À¢'w&#¢G'VRÀ¢ÒÀ¢°¢'G—R#¢'FW‡B"À¢'FW‡B#¢.˜(Š¸¾ˆ{>[	KØŞKúK»¾y¨NŠj®Xø¾ûÈÎ{x®h
^h‰nˆş{ZKˆŞKˆ®KÚi˜.ûÈÎ{;¾{[h˜Şyú^˜>zÊÎKˆi˜.™i>Š›.˜	®yú^Š«8""À¢'6—¦R#¢&ÖB"À¢&6öÆ÷"#¢"3SsS3DR"À¢'w&#¢G'VRÀ¢ÒÀ¢°¢'G—R#¢&&÷‚"À¢&Æ–÷WB#¢'fW'F–6Â"À¢&&6¶w&÷VæD6öÆ÷"#¢"4ddc4Cb"À¢&6÷&æW%&F—W2#¢&Ær"À¢'FF–ætÆÂ#¢&Ær"À¢&6öçFVçG2#¢·°¢'G—R#¢'FW‡B"À¢'FW‡B#¢.ZèŠÛ~KˆŞiŠşh™>i;îûÈÎˆÎiŠşi»ş[ÛÎjÚNZI®yYKˆK»ŞZè[ø>8""À¢'6—¦R#¢&ÖB"À¢'vV–v‡B#¢&&öÆB"À¢&6öÆ÷"#¢"3“#CR"À¢'w&#¢G'VRÀ¢ÕÒÀ¢ÒÀ¢ÒÀ¢ÒÀ¢&fö÷FW"#¢°¢'G—R#¢&&÷‚"À¢&Æ–÷WB#¢'fW'F–6Â"À¢'FF–ætÆÂ#¢'†Â"À¢'76–ær#¢'6Ò"À¢&&6¶w&÷VæD6öÆ÷"#¢"4ddd4cR"À¢&6öçFVçG2#¢°¢°¢'G—R#¢&'WGFöâ"À¢&7F–öâ#¢°¢'G—R#¢'W&’"À¢&Æ&VÂ#¢/	ù)¢Kˆ˜Û^˜(Š¸¾ZèŠÛ~K«¢"À¢'W&’#¢–çf—FU÷W&’À¢ÒÀ¢'7G–ÆR#¢'&–Ö'’"À¢&6öÆ÷"#¢"3d3D"À¢&†V–v‡B#¢&ÖB"À¢ÒÀ¢°¢'G—R#¢'FW‡B"À¢'FW‡B#¢.[ŞikŠj®ˆz®YÎhHş[èÎh˜ŞiÈ>ZèÎh‰{hZé¢"À¢'6—¦R#¢'6Ò"À¢&6öÆ÷"#¢"3sƒsd2"À¢&Æ–vâ#¢&6VçFW""À¢'w&#¢G'VRÀ¢&Ö&v–â#¢&ÖB"À¢ÒÀ¢ÒÀ¢ÒÀ¢ÒÀ¢Ğ  ¦FVb6VæEöÖ—76–æuö6öçF7E÷&VÖ–æFW'2†6öæf–r“ ¢Fö¶VâÒ6öæf–rævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"’÷"÷2æVçf—&öâævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"Â""¢–bæ÷BFö¶Vã ¢&WGW&â²'6VçB#¢Â'6¶—VB#¢Â&W'&÷"#¢$Ä”äUô4„ääTÅô44U55õDô´Tâ—2æ÷B6WB'ÒÂC  ¢7FFRÒÆöE÷7FFR†6öæf–u²$DDôd”ÄR%Ò¢6VæFW"Ò6öæf–rævWB‚$Ä”äUõU4…õ4TäDU""’÷"Æ–æU÷W6…öÖW76vP¢V&Æ–5÷W&ÂÒ†6öæf–rævWB‚$õT$Ä”5õU$Â"’÷"÷2æVçf—&öâævWB‚$õT$Ä”5õU$Â"Â""’’ç'7G&—‚"ò"¢æ÷rÒ7W'&VçEö÷F–ÖR†6öæf–r¢–bæ÷BÆ–æUöæöåöVÖW&vVæ7•÷W6…öÆÆ÷vVB‡7FFRÂ6öæf–rÂæ÷r“ ¢&WGW&âÆ–æUö'VFvWEö&Æö6¶VE÷&W7öç6R‡7FFRÂ6öæf–rÂæ÷r¢FöF’Òæ÷rç7G&gF–ÖR‚"U’ÒVÒÒVB"¢6VçBÒ ¢6¶—VBÒ ¢&W7VÇG2ÒµĞ¢7—7FVÕöW'&÷"ÒfÇ6P¢f÷"W6W"–â7FFRævWB‚'W6W'2"Â·Ò’çfÇVW2‚“ ¢Æ–æU÷W6W%ö–BÒW6W"ævWB‚&Æ–æU÷W6W%ö–B"¢–bæ÷BÆ–æU÷W6W%ö–C ¢6¶—VB³Ò¢6öçF–çVP¢–bW6W"ævWB‚&ÖVÖ&W'6†—÷W6VB"’÷"æ÷BÖVÖ&W'6†—ö66W75ö7F—fR‡W6W"Âæ÷r“ ¢6¶—VB³Ò¢6öçF–çVP¢–b&öf–ÆUö†5ö&÷VæEöÆ–æUöwV&F–â‡W6W"“ ¢6¶—VB³Ò¢6öçF–çVP¢–bæ÷BW6W"ævWB‚&wV&F–å÷Væ&÷VæE÷6–æ6R"“ ¢W6W%²&wV&F–å÷Væ&÷VæE÷6–æ6R%ÒÒ€¢W6W"ævWB‚&&WF÷7F'FVEöB"¢÷"W6W"ævWB‚'G&–Å÷7F'FVEöB"¢÷"W6W"ævWB‚&ÖVÖ&W'6†—÷7F'FVEöB"¢÷"W6W"ævWB‚'–EöB"¢÷"W6W"ævWB‚&7&VFVEöB"¢÷"æ÷ræ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"¢¢–bæ÷BwV&F–åö&–æF–æu÷&VÖ–æFW%öGVR‡W6W"Âæ÷r“ ¢6¶—VB³Ò¢6öçF–çVP¢6VçEöFFW2Ò6WB‡W6W"ævWB‚&6öçF7E÷&VÖ–æFW%÷6VçEöFFW2"’÷"µÒ¢–bFöF’–â6VçEöFFW3 ¢6öçF–çVP¢2iÊ®ZèÎh‰Ä”äR{hZé®i˜.ûÈÎKˆŞŠ¹niŠşY
n[{.iÈh˜¾X¹^‹8~ii8[è^hê^Xù~˜(Š¸¾h‰n™»¾Š›¢2{x®h
^ˆş{ZK«®ûÈÎKˆ[è¾hùKé¾Xúşy»Nhê^™h¾YYòÄ”äRZ[ŞXø¾XˆnKª¾y¨NKˆ˜Û^˜(Š¸¾XÚ8 ¢ÖW76vRÒ'V–ÆEöÖ—76–æuöwV&F–åöfÆW‚‡W6W"¢FVÆ—fW'•ö¶W’Òb&Ö—76–æuö6öçF7C§·FöF—Ò ¢–bæ÷BW6…öGFV×EöÆÆ÷vVB‡W6W"ÂFVÆ—fW'•ö¶W’“ ¢6¶—VB³Ò¢6öçF–çVP¢G'“ ¢&W7VÇBÒ6VæFW"‡Fö¶VâÂÆ–æU÷W6W%ö–BÂÖW76vR¢ö6ÆV%÷W6…öFVÆ—fW'•öf–ÇW&R‡W6W"ÂFVÆ—fW'•ö¶W’¢6VçEöFFW2æFB‡FöF’¢W6W%²&6öçF7E÷&VÖ–æFW%÷6VçEöFFW2%ÒÒ6÷'FVB‡6VçEöFFW2•²Ó3¥Ğ¢VæEöæ÷F–f–6F–öåöÆör‡7FFRÂ&Ö—76–æuö6öçF7B"ÂÆ–æU÷W6W%ö–BÂ'6VçB"ÂÖW76vRÂ§6öâæGV×2‡&W7VÇBÂVç7W&Uö66–“ÔfÇ6R’¢6VçB³Ò¢&W7VÇG2æVæB‡²&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–BÂ'&W7VÇB#¢&W7VÇGÒ¢W†6WBW†6WF–öâ2W†3 ¢f–ÇW&RÒ÷&V6÷&E÷66†VGVÆVE÷W6…öf–ÇW&R€¢7FFRÀ¢W6W"À¢FVÆ—fW'•ö¶W’À¢&Ö—76–æuö6öçF7B"À¢Æ–æU÷W6W%ö–BÀ¢ÖW76vRÀ¢W†2À¢æ÷rÀ¢¢6¶—VB³Ò¢&W7VÇG2æVæB‡²&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–BÂ&W'&÷"#¢7G"†W†2—Ò¢–bf–ÇW&U²&¶–æB%ÒÓÒ'7—7FVÒ# ¢7—7FVÕöW'&÷"ÒG'VP¢'&V°¢6fU÷7FFR†6öæf–u²$DDôd”ÄR%ÒÂ7FFR¢&WGW&â°¢'6VçB#¢6VçBÀ¢'6¶—VB#¢6¶—VBÀ¢'&W7VÇG2#¢&W7VÇG2À¢'7—7FVÕöW'&÷"#¢7—7FVÕöW'&÷"À¢ÒÂ#   ¦FVb6ÆVçWöW‡—&VEöFF†6öæf–r“ ¢FFöf–ÆRÒ6öæf–u²$DDôd”ÄR%Ğ¢æ÷rÒ7W'&VçEö÷F–ÖR†6öæf–r¢–çf—FUö7WFöfbÒæ÷rÒF–ÖVFVÇF†F—3Ór¢æ÷F–f–6F–öåö7WFöfbÒæ÷rÒF–ÖVFVÇF†F—3Ó“¢Ö–w&F–öåö6ÆVçWöæ÷rÒæ÷p¢–bÖ–w&F–öåö6ÆVçWöæ÷rçG¦–æfò—2æöæS ¢F–ÖW¦öæUöæÖRÒ€¢6öæf–rævWB‚$õD”ÔU¤ôäR"¢÷"÷2æVçf—&öâævWB‚$õD”ÔU¤ôäR"¢÷"$6–õF—V’ ¢¢G'“ ¢÷F–ÖW¦öæRÒ¦öæT–æfò‡7G"‡F–ÖW¦öæUöæÖR’¢W†6WBW†6WF–öã ¢÷F–ÖW¦öæRÒF–ÖW¦öæRçWF0¢Ö–w&F–öåö6ÆVçWöæ÷rÒÖ–w&F–öåö6ÆVçWöæ÷rç&WÆ6R€¢G¦–æfóÖ÷F–ÖW¦öæP¢’æ7F–ÖW¦öæR‡F–ÖW¦öæRçWF2 ¢FVbEö÷%ögFW"‡fÇVRÂ7WFöfb“ ¢'6VBÒ'6UöFFWF–ÖR‡fÇVR¢–b'6VB—2æöæS ¢&WGW&âG'VP¢6ö×&&ÆU÷'6VBÂ6ö×&&ÆUö7WFöfbÒö6ö×&&ÆUöFFWF–ÖW2€¢'6VBÂ7WFöf`¢¢&WGW&â6ö×&&ÆU÷'6VBãÒ6ö×&&ÆUö7WFöf` ¢FVb×WFFR‡7FFR“ ¢F÷væw&FVBÒöÇ•öW‡—&VE÷ÆåöF÷væw&FW5÷Fõ÷7FFR‡7FFRÂæ÷r¢Ö–w&F–öåö†—7F÷'•÷&VÖ÷fVBÒW&vUö66÷VçEöÖ–w&F–öåö†—7F÷'’€¢7FFRÀ¢æ÷sÖÖ–w&F–öåö6ÆVçWöæ÷rÀ¢¢W‡—&VEöÆö6F–öç5÷&VÖ÷fVBÒ ¢6öçF7G5ö&6†—fVBÒ ¢6öçF7G5÷&W7F÷&VBÒ ¢Ö–w&F–öå÷6æ6†÷G5÷&VÖ÷fVBÒW&vUö66÷VçEöÖ–w&F–öå÷6æ6†÷G2€¢7FFRÀ¢æ÷sÖÖ–w&F–öåö6ÆVçWöæ÷rÀ¢ ¢f÷"&öf–ÆR–â7FFRævWB‚'W6W'2"Â·Ò’çfÇVW2‚“ ¢–b&W7F÷&UöÆVv7•öWFõö&6†—fVEö6öçF7G2‡&öf–ÆR“ ¢6öçF7G5÷&W7F÷&VB³Ò¢–b6ögEö&6†—fUö6öçF7G5÷7E÷&WF–â‡&öf–ÆRÂæ÷r“ ¢6öçF7G5ö&6†—fVB³Ò¢Æö6F–öâÒ&öf–ÆRævWB‚&Æö6F–öâ"’÷"·Ğ¢–bæ÷BÆö6F–öã ¢6öçF–çVP¢–bÆö6F–öâævWB‚'VçF–Å÷7F÷"’æB€¢Æö6F–öâævWB‚'6†&–ær"’÷"Æö6F–öâævWB‚&7F—fR"¢“ ¢6öçF–çVP¢W‡—&W5öBÒ'6UöFFWF–ÖR†Æö6F–öâævWB‚&W‡—&W5öB"’¢Æö6F–öåöW‡—&VBÒfÇ6P¢–bW‡—&W5öC ¢6ö×&&ÆUöW‡—&W2Â6ö×&&ÆUöæ÷rÒö6ö×&&ÆUöFFWF–ÖW2€¢W‡—&W5öBÂæ÷p¢¢Æö6F–öåöW‡—&VBÒ6ö×&&ÆUöW‡—&W2Â6ö×&&ÆUöæ÷p¢–bÆö6F–öåöW‡—&VC ¢&öf–ÆU²&Æö6F–öâ%ÒÒ°¢¢¦Æö6F–öâÀ¢'6†&–ær#¢fÇ6RÀ¢&7F—fR#¢fÇ6RÀ¢&VæFVEöB#¢€¢Æö6F–öâævWB‚&VæFVEöB"¢÷"æ÷ræ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"¢’À¢Ğ¢W‡—&VEöÆö6F–öç5÷&VÖ÷fVB³Ò ¢–çf—FW5ö&Vf÷&RÒÆVâ‡7FFRævWB‚&g&–VæEö–çf—FW2"Â·Ò’¢7FFU²&g&–VæEö–çf—FW2%ÒÒ°¢6öFS¢–çf—FP¢f÷"6öFRÂ–çf—FR–â7FFRævWB‚&g&–VæEö–çf—FW2"Â·Ò’æ—FV×2‚¢–bEö÷%ögFW"†–çf—FRævWB‚&7&VFVEöB"’Â–çf—FUö7WFöfb¢Ğ ¢Æöw5ö&Vf÷&RÒÆVâ‡7FFRævWB‚&æ÷F–f–6F–öåöÆöw2"ÂµÒ’¢7FFU²&æ÷F–f–6F–öåöÆöw2%ÒÒ°¢Æöp¢f÷"Æör–â7FFRævWB‚&æ÷F–f–6F–öåöÆöw2"ÂµÒ¢–bEö÷%ögFW"†ÆörævWB‚&7&VFVEöB"’Âæ÷F–f–6F–öåö7WFöfb¢Õ²Ó¥Ğ¢&WGW&â°¢&6ÆVæVEöB#¢æ÷ræ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"’À¢&W‡—&VEöÆö6F–öç5÷&VÖ÷fVB#¢W‡—&VEöÆö6F–öç5÷&VÖ÷fVBÀ¢&W‡—&VEö–çf—FW5÷&VÖ÷fVB#¢€¢–çf—FW5ö&Vf÷&RÒÆVâ‡7FFU²&g&–VæEö–çf—FW2%Ò¢’À¢&öÆEöæ÷F–f–6F–öåöÆöw5÷&VÖ÷fVB#¢€¢Æöw5ö&Vf÷&RÒÆVâ‡7FFU²&æ÷F–f–6F–öåöÆöw2%Ò¢’À¢&6öçF7G5ö&6†—fVE÷W6W'2#¢6öçF7G5ö&6†—fVBÀ¢&6öçF7G5÷&W7F÷&VE÷W6W'2#¢6öçF7G5÷&W7F÷&VBÀ¢&Ö–w&F–öå÷6æ6†÷G5÷&VÖ÷fVB#¢Ö–w&F–öå÷6æ6†÷G5÷&VÖ÷fVBÀ¢&Ö–w&F–öå÷F–6¶WG5÷&VÖ÷fVB#¢Ö–w&F–öåö†—7F÷'•÷&VÖ÷fVE²'F–6¶WG2%ÒÀ¢&Ö–w&F–öåöVF—E÷&VÖ÷fVB#¢Ö–w&F–öåö†—7F÷'•÷&VÖ÷fVE²&VF—B%ÒÀ¢&÷&FW'5÷&VÖ÷fVB#¢À¢'Æç5öF÷væw&FVB#¢ÆVâ†F÷væw&FVB’À¢ÒÂ#  ¢&WGW&â×WFFU÷7FFUöFöÖ–6ÆÇ’†FFöf–ÆRÂ×WFFR  ¦FVb&VÖ–æFW%÷F–ÖUö–å÷v–æF÷r‡&VÖ–æFW%÷F–ÖRÂæ÷rÂÆFUöÖ–çWFW3ÓB“ ¢G'“ ¢†÷W"ÂÖ–çWFRÒ¶–çB‡'B’f÷"'B–â7G"‡&VÖ–æFW%÷F–ÖR÷"##£"’ç7Æ—B‚#¢"Â•Ğ¢W†6WB…G—TW'&÷"ÂfÇVTW'&÷"“ ¢†÷W"ÂÖ–çWFRÒ"Â ¢66†VGVÆVBÒæ÷rç&WÆ6R††÷W#Ö†÷W"ÂÖ–çWFSÖÖ–çWFRÂ6V6öæCÓÂÖ–7&÷6V6öæCÓ¢FVÇFÒæ÷rÒ66†VGVÆV@¢&WGW&âF–ÖVFVÇFƒ’ÃÒFVÇFÃÒF–ÖVFVÇF†Ö–çWFW3Ö–çB†ÆFUöÖ–çWFW2’Â6V6öæG3ÓS’  ¦FVb'V–ÆEöF–Ç•ö6†V6¶–åöfÆW‚†æ÷rÂF&vWE÷F–ÖSÒ""Â&öf–ÆSÔæöæR“ ¢""$F–Ç’6†V6²Ö–âfÆWƒ¢w&VWF–ær²÷F–öæÂ†öÆ–F’&ÆW76–ær²V÷FR²÷7F&6²à ¢¶VW26Æ76–2w&VVâ‚3#“’†VFW#²8Îh‰[›>Zè8ÒW6W2÷7F&6²7F–öãÖ6†V6¶–âà¢"" ¢FöF’Òæ÷rç7G&gF–ÖR‚"U’ÒVÒÒVB"¢vVV¶F•÷¦‚Ò².˜Kˆ"Â.˜K¨Â"Â.˜Kˆ’"Â.˜Y¹²"Â.˜K©B"Â.˜XZÒ"Â.˜izR%Õ¶æ÷rçvVV¶F’‚•Ğ¢F–ÖUö&—BÒb"·F&vWE÷F–ÖWÒ"–bF&vWE÷F–ÖRVÇ6R" ¢6÷’Ò€¢†öÆ–F—5÷GræF–Ç•÷W6…ö6÷’†æ÷r¢–b†öÆ–F—5÷Gr—2æ÷BæöæP¢VÇ6R°¢&w&VWF–ær#¢.)ÚNûˆòK¸®ZJKˆXˆ~˜;ŞZ[ŞYxîûÉò"À¢&†öÆ–F•öæÖR#¢""À¢&†öÆ–F•ö&ÆW76–ær#¢""À¢'÷6—F—fU÷V÷FR#¢.jøşKˆZJy¨N[›>ZèûÈÎ˜;ŞiŠş{ZnZënK«®iÈZ[Şy¨Nzjîxš8""À¢&–ç7G'V7F–öâ#¢.›¹î8Îh‰[›>Zè8Şz¸¾X‹¾ZèÎh‰ZX‹ûÈKˆŞyJXhŞ™h¾{k.šûÈ’"À¢Ğ¢¢wV&E÷W&’Ò€¢Æ–feöVçG'•÷W&Â†÷Våö7F–öãÒ&wV&B"¢–bÆ–feöVçG'•÷W&À¢VÇ6R&‡GG3¢òöÆ–fbæÆ–æRæÖRó#ƒCƒ33ÕT—”Cö÷VãÖwV&B ¢¢6÷5÷W&’Ò€¢Æ–feöVçG'•÷W&Â†÷Våö7F–öãÒ'6÷2"¢–bÆ–feöVçG'•÷W&À¢VÇ6R&‡GG3¢òöÆ–fbæÆ–æRæÖRó#ƒCƒ33ÕT—”Cö÷Vã×6÷2 ¢¢6†V6¶–å÷W&’Ò€¢Æ–feöVçG'•÷W&Â†÷Våö7F–öãÒ&6†V6¶–â"¢–bÆ–feöVçG'•÷W&À¢VÇ6R&‡GG3¢òöÆ–fbæÆ–æRæÖRó#ƒCƒ33ÕT—”Cö÷VãÖ6†V6¶–â ¢¢F–Ç•ö6&U÷W&’Ò€¢Æ–feöVçG'•÷W&Â†÷Våö7F–öãÒ&F–Ç’Ö6&R"¢–bÆ–feöVçG'•÷W&À¢VÇ6R&‡GG3¢òöÆ–fbæÆ–æRæÖRó#ƒCƒ33ÕT—”Cö÷VãÖF–Ç’Ö6&R ¢¢†öÆ–F•öæÖRÒ7G"†6÷’ævWB‚&†öÆ–F•öæÖR"’÷"""’ç7G&—‚¢†öÆ–F•ö&ÆW76–ærÒ7G"†6÷’ævWB‚&†öÆ–F•ö&ÆW76–ær"’÷"""’ç7G&—‚¢6&U÷&öf–ÆRÒF–7B‡&öf–ÆR÷"·Ò¢6&U÷&öf–ÆU²'7G&VµöF—2%ÒÒ6ö×WFU÷7G&VµöF—2†6&U÷&öf–ÆRævWB‚&†—7F÷'’"’÷"µÒÂæ÷rç7G&gF–ÖR‚"U’ÒVÒÒVB"’¢6&RÒ'V–ÆEöF–Ç•ö6&Uö6öçFW‡B†6&U÷&öf–ÆRÂæ÷r¢–b6&U²&6öçFVçEö¶–æB%ÒÒ&Ö–ÆW7FöæR"æB†öÆ–F•öæÖRæB†öÆ–F•ö&ÆW76–æs ¢6&U²&6&U÷F—FÆR%ÒÒb/	øè’¶†öÆ–F•öæÖWÒ ¢6&U²&6&U÷7VÖÖ'’%ÒÒ†öÆ–F•ö&ÆW76–æp¢6&U²&6öçFVçEö¶–æB%ÒÒ&†öÆ–F’ ¢&öG•ö6öçFVçG2Ò°¢°¢'G—R#¢'FW‡B"À¢'FW‡B#¢b'¶6&U²vw&VWF–æru×ŞûÈÇ¶6&U²v6†V6¶–å÷&ö×Bu×Ò"À¢'6—¦R#¢'†Â"À¢'vV–v‡B#¢&&öÆB"À¢&6öÆ÷"#¢"3"À¢'w&#¢G'VRÀ¢ÒÀ¢°¢'G—R#¢'FW‡B"À¢'FW‡B#¢6&U²&ÆWfVÅ÷&öw&W75÷FW‡B%ÒÀ¢'6—¦R#¢&Ær"À¢'vV–v‡B#¢&&öÆB"À¢&6öÆ÷"#¢6&U²&ÆWfVÅö6öÆ÷"%ÒÀ¢'w&#¢G'VRÀ¢ÒÀ¢°¢'G—R#¢'FW‡B"À¢'FW‡B#¢b'¶6&U²w&Wv&Eö–6öâu×Ò˜®h‹.X»>zºûÉ§¶6&U²vvÖUö&FvUöæÖRu×Ò"À¢'6—¦R#¢&Ær"À¢'vV–v‡B#¢&&öÆB"À¢&6öÆ÷"#¢6&U²&ÆWfVÅö6öÆ÷"%ÒÀ¢'w&#¢G'VRÀ¢ÒÀ¢°¢'G—R#¢'FW‡B"À¢'FW‡B#¢b/	øÊNûˆò¶6&U²wvVF†W%öÆ–æRu×Ò"À¢'6—¦R#¢&Ær"À¢'vV–v‡B#¢&&öÆB"À¢&6öÆ÷"#¢"333CSR"À¢'w&#¢G'VRÀ¢ÒÀ¢°¢'G—R#¢'FW‡B"À¢'FW‡B#¢b/	ù;¶6&U²væWw5÷F—FÆRu×Ò"À¢'6—¦R#¢&Ær"À¢'vV–v‡B#¢&&öÆB"À¢&6öÆ÷"#¢"4#CS3’"À¢'w&#¢G'VRÀ¢ÒÀ¢°¢'G—R#¢'FW‡B"À¢'FW‡B#¢6&U²&æWw5÷7VÖÖ'’%ÒÀ¢'6—¦R#¢&Ær"À¢'vV–v‡B#¢&&öÆB"À¢&6öÆ÷"#¢"3CsSSc’"À¢'w&#¢G'VRÀ¢ÒÀ¢Ğ¢–b6&RævWB‚'FöF•÷&VÖ–æFW'2"“ ¢&öG•ö6öçFVçG2æW‡FVæB…°¢°¢'G—R#¢'FW‡B"Â'FW‡B#¢/	ù9Òh‰y¨NK¸®iz^hù˜i""Â'6—¦R#¢&Ær"À¢'vV–v‡B#¢&&öÆB"Â&6öÆ÷"#¢"3CDTC‚"Â'w&#¢G'VRÀ¢ÒÀ¢°¢'G—R#¢'FW‡B"À¢'FW‡B#¢%Æâ"æ¦ö–â†—FVÒævWB‚'FW‡B"Â""’f÷"—FVÒ–â6&U²'FöF•÷&VÖ–æFW'2%Ò–b—FVÒævWB‚'FW‡B"’’À¢'6—¦R#¢&Ær"Â'vV–v‡B#¢&&öÆB"Â&6öÆ÷"#¢"333CSR"Â'w&#¢G'VRÀ¢ÒÀ¢Ò¢–b6&RævWB‚&6öçFVçEö¶–æB"’–â²&Ö–ÆW7FöæR"Â&†öÆ–F’'Ó ¢&öG•ö6öçFVçG2æW‡FVæB…°¢°¢'G—R#¢'FW‡B"Â'FW‡B#¢6&U²&6&U÷F—FÆR%ÒÂ'6—¦R#¢&Ær"À¢'vV–v‡B#¢&&öÆB"Â&6öÆ÷"#¢6&U²&ÆWfVÅö6öÆ÷"%ÒÂ'w&#¢G'VRÀ¢ÒÀ¢°¢'G—R#¢'FW‡B"Â'FW‡B#¢6&U²&6&U÷7VÖÖ'’%ÒÂ'6—¦R#¢&Ær"À¢'vV–v‡B#¢&&öÆB"Â&6öÆ÷"#¢"3ccS3B"Â'w&#¢G'VRÀ¢ÒÀ¢Ò¢&öG•ö6öçFVçG2æVæB€¢°¢'G—R#¢'FW‡B"À¢'FW‡B#¢b.)Ê‚¶6&U²v&ÆW76–æu÷FW‡BuÒ÷"6÷•²w÷6—F—fU÷V÷FRu×Ò"À¢'6—¦R#¢&Ær"À¢'vV–v‡B#¢&&öÆB"À¢&6öÆ÷"#¢"3ccS3B"À¢'w&#¢G'VRÀ¢Ğ¢¢&öG•ö6öçFVçG2æVæB€¢°¢'G—R#¢'FW‡B"À¢'FW‡B#¢6÷•²&–ç7G'V7F–öâ%ÒÀ¢'6—¦R#¢&Ær"À¢'vV–v‡B#¢&&öÆB"À¢&6öÆ÷"#¢"3SSSSSR"À¢'w&#¢G'VRÀ¢Ğ¢¢VÖW&vVæ7•ö6öçF7E÷6WBÒç’€¢&W6öÇfUö6öçF7E÷&öÆR†6öçF7B’ÓÒ&VÖW&vVæ7’ ¢æB&ööÂ‡7G"†6öçF7BævWB‚'†öæR"’÷"""’ç7G&—‚’¢f÷"6öçF7B–â†6&U÷&öf–ÆRævWB‚&6öçF7G2"’÷"µÒ¢–b—6–ç7Fæ6R†6öçF7BÂF–7B¢¢–bæ÷BVÖW&vVæ7•ö6öçF7E÷6WC ¢&öG•ö6öçFVçG2æVæB€¢°¢'G—R#¢'FW‡B"À¢'FW‡B#¢.)ˆîûˆò{x®h
^ˆş{ZK«®™»¾Š›[	®iÊ®ŠŠŞZé®ûÈÎXúşYÊiÈ>Y:KŠŞ[ø>˜Z¾ûÈÎ{x®h
^i˜.ikKëşˆz®ŠÎˆş{Z8""À¢'6—¦R#¢&Ær"À¢'vV–v‡B#¢&&öÆB"À¢&6öÆ÷"#¢"3sƒsd2"À¢'w&#¢G'VRÀ¢Ğ¢¢ÇE÷'G2Ò¶6÷•²&w&VWF–ær%ÒÂFöF•Ğ¢–b†öÆ–F•öæÖS ¢ÇE÷'G2æVæB††öÆ–F•öæÖR¢–bF&vWE÷F–ÖS ¢ÇE÷'G2æVæB‡F&vWE÷F–ÖR¢fö÷FW%ö6öçFVçG2Ò°¢°¢'G—R#¢&&÷‚"À¢&Æ–÷WB#¢&†÷&—¦öçFÂ"À¢&&6¶w&÷VæD6öÆ÷"#¢"3d3D"À¢&6÷&æW%&F—W2#¢&ÖB"À¢'FF–ætÆÂ#¢&ÖB"À¢&7F–öâ#¢°¢'G—R#¢'W&’"À¢&Æ&VÂ#¢.)ÈRh‰[›>Zè’"À¢'W&’#¢6†V6¶–å÷W&’À¢ÒÀ¢&Ö&v–â#¢&ÖB"À¢&6öçFVçG2#¢·°¢'G—R#¢&–ÖvR"À¢'W&Â#¢&‡GG3¢òöÆ—fRÖ6†V6¶–âæöç&VæFW"æ6öÒö76WG2öF–Ç’×V6RÖÆövòçær"À¢'6—¦R#¢'‡‡2"À¢&7V7DÖöFR#¢&f—B"À¢&fÆW‚#¢À¢ÒÂ°¢'G—R#¢'FW‡B"À¢'FW‡B#¢.)ÈRh‰[›>Zè’"À¢'6—¦R#¢'†Â"À¢'vV–v‡B#¢&&öÆB"À¢&6öÆ÷"#¢"4dddddb"À¢&Æ–vâ#¢&6VçFW""À¢ÕÒÀ¢ÒÀ¢°¢'G—R#¢&'WGFöâ"À¢&7F–öâ#¢²'G—R#¢'W&’"Â&Æ&VÂ#¢/	ùºûˆòZèXZZèŠÛr"Â'W&’#¢wV&E÷W&—ÒÀ¢'7G–ÆR#¢'&–Ö'’"À¢&6öÆ÷"#¢"3#Sc4T""À¢&†V–v‡B#¢&ÖB"À¢ÒÀ¢°¢'G—R#¢&'WGFöâ"À¢&7F–öâ#¢²'G—R#¢'W&’"Â&Æ&VÂ#¢.™ÈŠh[š¾[ù’"Â'W&’#¢6÷5÷W&—ÒÀ¢'7G–ÆR#¢'&–Ö'’"À¢&6öÆ÷"#¢"4D3#c#b"À¢&†V–v‡B#¢&ÖB"À¢ÒÀ¢°¢'G—R#¢&'WGFöâ"À¢&7F–öâ#¢°¢'G—R#¢'W&’"À¢&Æ&VÂ#¢/	ùIBiú^yÈ¾K¸®iz^Zè[ø>hù˜i""À¢'W&’#¢F–Ç•ö6&U÷W&’À¢ÒÀ¢'7G–ÆR#¢'&–Ö'’"À¢&6öÆ÷"#¢"4CDr"À¢&†V–v‡B#¢&ÖB"À¢ÒÀ¢Ğ¢–b6&RævWB‚&Ö–ÆW7FöæUöF’"“ ¢6†–WfVÖVçE÷W&’Ò€¢Æ–feöVçG'•÷W&Â†÷Våö7F–öãÒ&6†–WfVÖVçB"ÂÖ–ÆW7FöæSÖ6&U²&Ö–ÆW7FöæUöF’%Ò¢–bÆ–feöVçG'•÷W&À¢VÇ6R€¢&‡GG3¢òöÆ–fbæÆ–æRæÖRó#ƒCƒ33ÕT—”B ¢b#ö÷VãÖ6†–WfVÖVçBfÖ–ÆW7FöæS×¶6&U²vÖ–ÆW7FöæUöF’u×Ò ¢¢¢fö÷FW%ö6öçFVçG2æVæB‡°¢'G—R#¢&'WGFöâ"À¢&7F–öâ#¢°¢'G—R#¢'W&’"À¢&Æ&VÂ#¢.)Ê‚iú^yÈ¾h‰y¨N[›>Zèh‰["À¢'W&’#¢6†–WfVÖVçE÷W&’À¢ÒÀ¢'7G–ÆR#¢'&–Ö'’"À¢&6öÆ÷"#¢"4C“ssb"À¢&†V–v‡B#¢&ÖB"À¢Ò¢&WGW&â°¢'G—R#¢&fÆW‚"À¢&ÇEFW‡B#¢""æ¦ö–â†ÇE÷'G2•³£CÒÀ¢&6öçFVçG2#¢°¢'G—R#¢&'V&&ÆR"À¢'6—¦R#¢&ÖVv"À¢&†W&ò#¢°¢'G—R#¢&–ÖvR"À¢'W&Â#¢6&U²&†W&õ÷W&Â%ÒÀ¢'6—¦R#¢&gVÆÂ"À¢&7V7E&F–ò#¢#C£R"À¢&7V7DÖöFR#¢&6÷fW""À¢&æ–ÖFVB#¢fÇ6RÀ¢ÒÀ¢&†VFW"#¢°¢'G—R#¢&&÷‚"À¢&Æ–÷WB#¢'fW'F–6Â"À¢'76–ær#¢'‡2"À¢&&6¶w&÷VæD6öÆ÷"#¢"3#“"À¢'FF–æuF÷#¢&Ær"À¢'FF–æt&÷GFöÒ#¢&Ær"À¢'FF–æu7F'B#¢&Ær"À¢'FF–ætVæB#¢&Ær"À¢&6öçFVçG2#¢°¢°¢'G—R#¢'FW‡B"À¢'FW‡B#¢.jøşiz^[›>Zè’"À¢&6öÆ÷"#¢"4dddddb"À¢'6—¦R#¢&Ær"À¢'vV–v‡B#¢&&öÆB"À¢'w&#¢G'VRÀ¢ÒÀ¢°¢'G—R#¢'FW‡B"À¢'FW‡B#¢b/	ù8R·FöF—Ò·vVV¶F•÷¦‡×·F–ÖUö&—GÒ"ç7G&—‚’À¢&6öÆ÷"#¢"4dddddb"À¢'6—¦R#¢'†Â"À¢'vV–v‡B#¢&&öÆB"À¢'w&#¢G'VRÀ¢ÒÀ¢ÒÀ¢ÒÀ¢&&öG’#¢°¢'G—R#¢&&÷‚"À¢&Æ–÷WB#¢'fW'F–6Â"À¢'76–ær#¢&ÖB"À¢'FF–ætÆÂ#¢&Ær"À¢&6öçFVçG2#¢&öG•ö6öçFVçG2À¢ÒÀ¢&fö÷FW"#¢°¢'G—R#¢&&÷‚"À¢&Æ–÷WB#¢'fW'F–6Â"À¢'76–ær#¢'6Ò"À¢'FF–ætÆÂ#¢&Ær"À¢&&6¶w&÷VæD6öÆ÷"#¢"4ddd"À¢&6öçFVçG2#¢fö÷FW%ö6öçFVçG2À¢ÒÀ¢ÒÀ¢Ğ  ¦FVb6VæEöGVU÷7G&VµöÖ–ÆW7FöæU÷f–FV÷2†6öæf–r“ ¢""%6VæBF’ó3cRÖVÖ&W"f–FV÷3²&V6÷&B6ö×ÆWF–öâöæÇ’gFW"7V66W72â"" ¢Fö¶VâÒ6öæf–rævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"’÷"÷2æVçf—&öâævWB€¢$Ä”äUô4„ääTÅô44U55õDô´Tâ"Â" ¢¢–bæ÷BFö¶Vã ¢&WGW&â²'6VçB#¢Â&f–ÆVB#¢Â&Ö—76–æuöÖVF–#¢À¢&W'&÷"#¢$Ä”äUô4„ääTÅô44U55õDô´Tâ—2æ÷B6WB'ÒÂC ¢7FFRÒÆöE÷7FFR†6öæf–u²$DDôd”ÄR%Ò¢6VæFW"Ò6öæf–rævWB‚$Ä”äUõU4…õ4TäDU""’÷"Æ–æU÷W6…öÖW76vP¢æ÷rÒ7W'&VçEö÷F–ÖR†6öæf–r¢FöF’Òæ÷rç7G&gF–ÖR‚"U’ÒVÒÒVB"¢6VçBÒf–ÆVBÒÖ—76–æuöÖVF–Ò6¶—VBÒ ¢&W7VÇG2ÒµĞ¢f÷"&öf–ÆR–â‡7FFRævWB‚'W6W'2"’÷"·Ò’çfÇVW2‚“ ¢V–BÒ7G"‡&öf–ÆRævWB‚&Æ–æU÷W6W%ö–B"’÷"""’ç7G&—‚¢–bæ÷BV–B÷"&öf–ÆRævWB‚&Æ–æU÷W6…ö&Æö6¶VB"“ ¢6¶—VB³Ò¢6öçF–çVP¢F’Ò6ö×WFU÷7G&VµöF—2‡&öf–ÆRævWB‚&†—7F÷'’"’÷"µÒÂFöF’¢VæF–ærÒ°¢–çB‡fÇVR’f÷"fÇVR–â‡&öf–ÆRævWB‚'7G&VµöÖ–ÆW7FöæU÷f–FV÷5÷VæF–ær"’÷"µÒ¢–b7G"‡fÇVR’æ—6F–v—B‚’æB–çB‡fÇVR’–âƒÂ3cR¢Ğ¢–bF’–âƒÂ3cR“ ¢VæF–æræFB†F’¢–bæ÷BVæF–æs ¢6öçF–çVP¢F’ÒÖ–â‡VæF–ær¢&öf–ÆU²'7G&VµöÖ–ÆW7FöæU÷f–FV÷5÷VæF–ær%ÒÒ6÷'FVB‡VæF–ær¢6ö×ÆWFVBÒ6WB‡&öf–ÆRævWB‚'7G&VµöÖ–ÆW7FöæU÷f–FV÷5÷6VçB"’÷"µÒ¢¶W’Òb'·V–GÓ§¶F—Ò ¢–b¶W’–â6ö×ÆWFVC ¢6¶—VB³Ò¢6öçF–çVP¢W&ÂÒ7G"€¢6öæf–rævWB†b$Ô”ÄU5DôäUõd”DTõ÷¶F—ÕõU$Â"¢÷"÷2æVçf—&öâævWB†b$Ô”ÄU5DôäUõd”DTõ÷¶F—ÕõU$Â"Â""¢’ç7G&—‚¢–bæ÷BW&Ã ¢Ö—76–æuöÖVF–³Ò¢&W7VÇG2æVæB‡²&Æ–æU÷W6W%ö–B#¢V–BÂ&Ö–ÆW7FöæUöF’#¢F’À¢'7FGW2#¢&Ö—76–æuöÖVF–'Ò¢6öçF–çVP¢&Wf–WrÒ7G"€¢6öæf–rævWB†b$Ô”ÄU5DôäUõd”DTõ÷¶F—Õõ$Ud”UuõU$Â"¢÷"÷2æVçf—&öâævWB†b$Ô”ÄU5DôäUõd”DTõ÷¶F—Õõ$Ud”UuõU$Â"Â""¢÷"&‡GG3¢òöÆ—fRÖ6†V6¶–âæöç&VæFW"æ6öÒö76WG2öF–Ç’Ö6&Rö¦Vææ–R×6×ÆRÓ##cƒ"çvV' ¢’ç7G&—‚¢ÖW76vRÒ°¢'G—R#¢'f–FVò"À¢&÷&–v–æÄ6öçFVçEW&Â#¢W&ÂÀ¢'&Wf–Wt–ÖvUW&Â#¢&Wf–WrÀ¢'G&6¶–æt–B#¢b'7G&V²×¶F—Ò"À¢Ğ¢G'“ ¢&W7VÇBÒ6VæFW"‡Fö¶VâÂV–BÂÖW76vR¢–b—6–ç7Fæ6R‡&W7VÇBÂF–7B’æB&W7VÇBævWB‚&ö²"’—2fÇ6S ¢&—6R'VçF–ÖTW'&÷"‡7G"‡&W7VÇB’¢6ö×ÆWFVBæFB†¶W’¢&öf–ÆU²'7G&VµöÖ–ÆW7FöæU÷f–FV÷5÷6VçB%ÒÒ6÷'FVB†6ö×ÆWFVB¢VæF–æræF—66&B†F’¢–bVæF–æs ¢&öf–ÆU²'7G&VµöÖ–ÆW7FöæU÷f–FV÷5÷VæF–ær%ÒÒ6÷'FVB‡VæF–ær¢VÇ6S ¢&öf–ÆRç÷‚'7G&VµöÖ–ÆW7FöæU÷f–FV÷5÷VæF–ær"ÂæöæR¢&öf–ÆU²'7G&VµöÖ–ÆW7FöæU÷f–FVõöÆ7E÷6VçEöB%ÒÒæ÷ræ—6öf÷&ÖB€¢F–ÖW7V3Ò'6V6öæG2 ¢¢ö6ÆV%÷W6…öFVÆ—fW'•öf–ÇW&R‡&öf–ÆRÂb'7G&V²×f–FVó§¶F—Ò"¢VæEöæ÷F–f–6F–öåöÆör€¢7FFRÂ'7G&VµöÖ–ÆW7FöæU÷f–FVò"ÂV–BÂ'6VçB"ÂÖW76vRÀ¢§6öâæGV×2‡&W7VÇBÂVç7W&Uö66–“ÔfÇ6R’À¢ÖWFFF×²&Ö–ÆW7FöæUöF’#¢F—ÒÀ¢¢&V6÷&EöÆ–æUöÖW76vU÷W6vR€¢7FFRÂ6FVv÷'“Ò&6†V6¶–â"Â÷væW%öÆ–æU÷W6W%ö–C×V–BÀ¢&V6—–VçEö6÷VçCÓÂWfVçEö–CÖb'7G&V²×f–FVó§·V–GÓ§¶F—Ò"À¢6VçEöCÖæ÷rÀ¢¢6VçB³Ò¢&W7VÇG2æVæB‡²&Æ–æU÷W6W%ö–B#¢V–BÂ&Ö–ÆW7FöæUöF’#¢F’À¢'7FGW2#¢'6VçB'Ò¢W†6WBW†6WF–öâ2W†3 ¢&V6÷&E÷W6…öf–ÇW&R‡&öf–ÆRÂb'7G&V²×f–FVó§¶F—Ò"ÂW†2Âæ÷r¢VæEöæ÷F–f–6F–öåöÆör€¢7FFRÂ'7G&VµöÖ–ÆW7FöæU÷f–FVò"ÂV–BÂ&f–ÆVB"ÂÖW76vRÀ¢7G"†W†2’ÂÖWFFF×²&Ö–ÆW7FöæUöF’#¢F—ÒÀ¢¢f–ÆVB³Ò¢&W7VÇG2æVæB‡²&Æ–æU÷W6W%ö–B#¢V–BÂ&Ö–ÆW7FöæUöF’#¢F’À¢'7FGW2#¢&f–ÆVB"Â&W'&÷"#¢7G"†W†2—Ò¢6fU÷7FFR†6öæf–u²$DDôd”ÄR%ÒÂ7FFR¢&WGW&â²'6VçB#¢6VçBÂ&f–ÆVB#¢f–ÆVBÂ&Ö—76–æuöÖVF–#¢Ö—76–æuöÖVF–À¢'6¶—VB#¢6¶—VBÂ'&W7VÇG2#¢&W7VÇG7ÒÂ#   ¦FVböÖ&µöÆ–æU÷W6…ö&Æö6¶VB‡W6W"ÂW†2“ ¢""$Ö&²&Æö6¶VBòvöæRW6W'26ògWGW&R'&öF67G26¶—F†VÒâ"" ¢6öFRÒæöæP¢–b—6–ç7Fæ6R†W†2ÂW&ÆÆ–"æW'&÷"ä…EEW'&÷"“ ¢6öFRÒW†2æ6öFP¢FW‡BÒ7G"†W†2÷"""’æÆ÷vW"‚¢–b6öFR–â³CÂC2ÂCGÒ÷"&æ÷Bg&–VæB"–âFW‡B÷"&&Æö6¶VB"–âFW‡C ¢W6W%²&Æ–æU÷W6…ö&Æö6¶VB%ÒÒG'VP¢W6W%²&Æ–æU÷W6…ö&Æö6¶VEöB%ÒÒFFWF–ÖRææ÷r‚’æ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"¢&WGW&âG'VP¢&WGW&âfÇ6P  ¦FVböÖ&µö6†V6¶–å÷&VÖ–æFW%÷6Æ÷G2‡W6W"ÂFöF’ÂF–ÖW2ÂGVU÷F–ÖW2“ ¢6VçE÷6Æ÷G2ÒF–7B‡W6W"ævWB‚&6†V6¶–å÷&VÖ–æFW%÷6VçE÷6Æ÷G2"’÷"·Ò¢6VçE÷FöF’Ò6WB‡6VçE÷6Æ÷G2ævWB‡FöF’’÷"µÒ¢6VçE÷FöF’çWFFR†GVU÷F–ÖW2÷"F–ÖW2÷"µÒ¢6VçE÷6Æ÷G5·FöF•ÒÒ6÷'FVB‡6VçE÷FöF’¢¶VWöFFW2Ò6÷'FVB‡6VçE÷6Æ÷G2æ¶W—2‚’•²Ó3¥Ğ¢W6W%²&6†V6¶–å÷&VÖ–æFW%÷6VçE÷6Æ÷G2%ÒÒ¶C¢6VçE÷6Æ÷G5¶EÒf÷"B–â¶VWöFFW7Ğ¢ÆVv7•öFFW2Ò6WB‡W6W"ævWB‚&6†V6¶–å÷&VÖ–æFW%÷6VçEöFFW2"’÷"µÒ¢–b6WB‡F–ÖW2÷"µÒ’æ—77V'6WB‡6VçE÷FöF’“ ¢ÆVv7•öFFW2æFB‡FöF’¢W6W%²&6†V6¶–å÷&VÖ–æFW%÷6VçEöFFW2%ÒÒ6÷'FVB†ÆVv7•öFFW2•²Ó3¥Ğ  ¦FVb6VæEö6†V6¶–å÷&VÖ–æFW'2†6öæf–r“ ¢""$Ö÷&æ–ær÷6Æ÷B7&öã¢6¶—W6W'2Ç&VG’6†V6¶VB–â…F—V’’â&VfW"&RÖ6†V6²Ö–â&VÖ–æBâ"" ¢Fö¶VâÒ6öæf–rævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"’÷"÷2æVçf—&öâævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"Â""¢–bæ÷BFö¶Vã ¢&WGW&â²'6VçB#¢Â'6¶—VB#¢Â&W'&÷"#¢$Ä”äUô4„ääTÅô44U55õDô´Tâ—2æ÷B6WB'ÒÂC  ¢FFöf–ÆRÒ6öæf–u²$DDôd”ÄR%Ğ¢7FFRÒÆöE÷7FFR†FFöf–ÆR¢6VæFW"Ò6öæf–rævWB‚$Ä”äUõU4…õ4TäDU""’÷"Æ–æU÷W6…öÖW76vP¢æ÷rÒ7W'&VçEö÷F–ÖR†6öæf–r¢–bæ÷BÆ–æUöæöåöVÖW&vVæ7•÷W6…öÆÆ÷vVB‡7FFRÂ6öæf–rÂæ÷r“ ¢&WGW&âÆ–æUö'VFvWEö&Æö6¶VE÷&W7öç6R‡7FFRÂ6öæf–rÂæ÷r¢FöF’Òæ÷rç7G&gF–ÖR‚"U’ÒVÒÒVB"¢6VçBÒ ¢6¶—VBÒ ¢&W7VÇG2ÒµĞ¢7—7FVÕöW'&÷"ÒfÇ6P ¢f÷"W6W"–â7FFRævWB‚'W6W'2"Â·Ò’çfÇVW2‚“ ¢Æ–æU÷W6W%ö–BÒW6W"ævWB‚&Æ–æU÷W6W%ö–B"¢–bæ÷BÆ–æU÷W6W%ö–C ¢6¶—VB³Ò¢6öçF–çVP¢–bW6W"ævWB‚&Æ–æU÷W6…ö&Æö6¶VB"“ ¢6¶—VB³Ò¢6öçF–çVP¢–bW6W"ævWB‚&ÖVÖ&W'6†—÷W6VB"’÷"æ÷BÖVÖ&W'6†—ö66W75ö7F—fR‡W6W"Âæ÷r“ ¢6¶—VB³Ò¢6öçF–çVP¢–bæ÷B&öf–ÆUö†5ö&÷VæEöÆ–æUöwV&F–â‡W6W"“ ¢6¶—VB³Ò¢6öçF–çVP¢–bæ÷B&ööÂ‡W6W"ævWB‚&F–Ç•ö6†V6¶–å÷&VÖ–æFW%öVæ&ÆVB"ÂG'VR’“ ¢6¶—VB³Ò¢6öçF–çVP¢–b&öf–ÆUö—5÷FöF•ö6†V6¶VB‡W6W"Â6öæf–sÖ6öæf–rÂæ÷sÖæ÷r“ ¢2†VÂÖ—76–ærF—V’†—7F÷'’6òÆFW"7&öâ÷7FGW27F’6öç6—7FVç@¢†—7BÒ6WB‡W6W"ævWB‚&†—7F÷'’"’÷"µÒ¢–bFöF’æ÷B–â†—7C ¢†—7BæFB‡FöF’¢W6W%²&†—7F÷'’%ÒÒ6÷'FVB††—7B¢2K¸®iz^[{.Z[›>Zè’(i"yZ^˜îYÎiz^XššIhé.zˆ¾hù˜i.ûÈj‰Š‰‚6Æ÷G>ûÈÎ˜şXXŞ[èÎ{¨ÎŠªNhêûÈ¢F–ÖW2Ò&VÖ–æFW%÷F–ÖW5öf÷%÷&öf–ÆR‡W6W"’÷"²##£%Ğ¢öÖ&µö6†V6¶–å÷&VÖ–æFW%÷6Æ÷G2‡W6W"ÂFöF’ÂF–ÖW2ÂF–ÖW2¢6¶—VB³Ò¢6öçF–çVP ¢F–ÖW2Ò&VÖ–æFW%÷F–ÖW5öf÷%÷&öf–ÆR‡W6W"¢6VçE÷6Æ÷G2ÒF–7B‡W6W"ævWB‚&6†V6¶–å÷&VÖ–æFW%÷6VçE÷6Æ÷G2"’÷"·Ò¢6VçE÷FöF’Ò6WB‡6VçE÷6Æ÷G2ævWB‡FöF’’÷"µÒ ¢2y»Zëˆˆ®x˜ƒ®y[nZJ[{.yJYjîKˆiz^iÉşj‰Š‰˜˜â(i"Šinx+®iÊÎ‹Ê®[{.hù˜i ¢ÆVv7•öFFW2Ò6WB‡W6W"ævWB‚&6†V6¶–å÷&VÖ–æFW%÷6VçEöFFW2"’÷"µÒ¢–bFöF’–âÆVv7•öFFW2æBæ÷B6VçE÷FöF“ ¢6öçF–çVP ¢GVU÷Vç6VçBÒ°¢@¢f÷"B–âF–ÖW0¢–b&VÖ–æFW%÷F–ÖUö–å÷v–æF÷r‡BÂæ÷rÂÆFUöÖ–çWFW3ÓB’æBBæ÷B–â6VçE÷FöF¢Ğ¢–bæ÷BGVU÷Vç6VçC ¢6öçF–çVP ¢2YÎKˆK©NXˆn™	i˜.™i>z©~Xú®hêKˆjÊûÉ¾‹È>izkÈşhèy¨Ni˜.jë^KˆŞŠ9Î˜K™şKˆŞj‰Š‰8 ¢F&vWE÷F–ÖRÒGVU÷Vç6VçE²ÓĞ¢FVÆ—fW'•ö¶W’Òb&6†V6¶–ã§·FöF—Ó§·F&vWE÷F–ÖWÒ ¢÷&V6÷&EöÆVæ6…öFVÆ—fW'’€¢7FFRÂFVÆ—fW'•ö¶W’Â&6†V6¶–â"ÂÆ–æU÷W6W%ö–BÂ&W‡V7FVB ¢¢–bæ÷BW6…öGFV×EöÆÆ÷vVB‡W6W"ÂFVÆ—fW'•ö¶W’“ ¢6¶—VB³Ò¢6öçF–çVP¢ÖW76vRÒ'V–ÆEöF–Ç•ö6†V6¶–åöfÆW‚†æ÷rÂF&vWE÷F–ÖS×F&vWE÷F–ÖRÂ&öf–ÆS×W6W"¢G'“ ¢&W7VÇBÒ6VæFW"‡Fö¶VâÂÆ–æU÷W6W%ö–BÂÖW76vR¢ö6ÆV%÷W6…öFVÆ—fW'•öf–ÇW&R‡W6W"ÂFVÆ—fW'•ö¶W’¢÷&V6÷&EöÆVæ6…öFVÆ—fW'’€¢7FFRÂFVÆ—fW'•ö¶W’Â&6†V6¶–â"ÂÆ–æU÷W6W%ö–BÂ'6VçB ¢¢öÖ&µö6†V6¶–å÷&VÖ–æFW%÷6Æ÷G2‡W6W"ÂFöF’ÂF–ÖW2ÂGVU÷Vç6VçB¢Vç7W&Uö7F—fUö÷fW&GVUöWfVçB‡W6W"ÂF&vWE÷F–ÖRÂæ÷r¢VæEöæ÷F–f–6F–öåöÆör‡7FFRÂ&6†V6¶–â"ÂÆ–æU÷W6W%ö–BÂ'6VçB"ÂÖW76vRÂ§6öâæGV×2‡&W7VÇBÂVç7W&Uö66–“ÔfÇ6R’¢&V6÷&EöÆ–æUöÖW76vU÷W6vR€¢7FFRÀ¢6FVv÷'“Ò&6†V6¶–â"À¢÷væW%öÆ–æU÷W6W%ö–CÖÆ–æU÷W6W%ö–BÀ¢&V6—–VçEö6÷VçCÓÀ¢WfVçEö–CÖFVÆ—fW'•ö¶W’À¢6VçEöCÖæ÷rÀ¢¢6VçB³Ò¢&W7VÇG2æVæB‡²&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–BÂ'&VÖ–æFW%÷F–ÖR#¢F&vWE÷F–ÖRÂ'&W7VÇB#¢&W7VÇGÒ¢2ikjXÛ>[~ûÈş[{.X‹iÉşûÉ®YÎiz^iÈZI®™˜N[‹nKˆjÊhù˜i.ûÈKˆŞkI~x˜ûÈ¢–b6†÷VÆEööffW%öW‡—'•÷&VÖ–æB‡W6W"Âæ÷r“ ¢W‡—'•ö×6rÒ'V–ÆEöW‡—'•÷&VÖ–æEöfÆW‚‡W6W"Âæ÷r¢W‡—'•ö¶W’Òb&W‡—'•÷&VÖ–æC§·FöF—Ò ¢–bæ÷BW6…öGFV×EöÆÆ÷vVB‡W6W"ÂW‡—'•ö¶W’“ ¢6öçF–çVP¢G'“ ¢W‡—'•÷&W7VÇBÒ6VæFW"‡Fö¶VâÂÆ–æU÷W6W%ö–BÂW‡—'•ö×6r¢ö6ÆV%÷W6…öFVÆ—fW'•öf–ÇW&R‡W6W"ÂW‡—'•ö¶W’¢Ö&µöW‡—'•÷&VÖ–æE÷6VçB‡W6W"Âæ÷r¢VæEöæ÷F–f–6F–öåöÆör€¢7FFRÀ¢&W‡—'•÷&VÖ–æB"À¢Æ–æU÷W6W%ö–BÀ¢'6VçB"À¢W‡—'•ö×6rÀ¢§6öâæGV×2†W‡—'•÷&W7VÇBÂVç7W&Uö66–“ÔfÇ6R’À¢¢W†6WBW†6WF–öâ2W‡—'•öW†3 ¢f–ÇW&RÒ÷&V6÷&E÷66†VGVÆVE÷W6…öf–ÇW&R€¢7FFRÀ¢W6W"À¢W‡—'•ö¶W’À¢&W‡—'•÷&VÖ–æB"À¢Æ–æU÷W6W%ö–BÀ¢W‡—'•ö×6rÀ¢W‡—'•öW†2À¢æ÷rÀ¢¢–bf–ÇW&U²&¶–æB%ÒÓÒ'7—7FVÒ# ¢7—7FVÕöW'&÷"ÒG'VP¢'&V°¢W†6WBW†6WF–öâ2W†3 ¢f–ÇW&RÒ÷&V6÷&E÷66†VGVÆVE÷W6…öf–ÇW&R€¢7FFRÀ¢W6W"À¢FVÆ—fW'•ö¶W’À¢&6†V6¶–â"À¢Æ–æU÷W6W%ö–BÀ¢ÖW76vRÀ¢W†2À¢æ÷rÀ¢¢6¶—VB³Ò¢&W7VÇG2æVæB‡²&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–BÂ&W'&÷"#¢7G"†W†2—Ò¢–bf–ÇW&U²&¶–æB%ÒÓÒ'7—7FVÒ# ¢7—7FVÕöW'&÷"ÒG'VP¢'&V° ¢6fU÷7FFR†FFöf–ÆRÂ7FFR¢&WGW&â°¢'6VçB#¢6VçBÀ¢'6¶—VB#¢6¶—VBÀ¢'&W7VÇG2#¢&W7VÇG2À¢'7—7FVÕöW'&÷"#¢7—7FVÕöW'&÷"À¢ÒÂ#   ¦FVb'&öF67Eö6†V6¶–å÷&VÖ–æFW'2†6öæf–rÂ¢ÂW6UöWfW'“Ó#ÂW6U÷6V6öæG3Óã“ ¢"".˜xŞikhêi*ŞûÉ®˜ikjŠiÛş{Znh˜iÈ[{.Š‹¾Xh®iÈ>Y:ûÈiÈ’Æ–æU÷W6W%ö–NûÈûÈÎY
¾K¸®iz^[{.{ŞX‹ˆ^8  ¢Ò‹{>˜âÆ–æU÷W6…ö&Æö6¶V@¢ÒXˆnh›iª¾XÎKº^™˜ŞKØâÄ”äR&FRÖÆ–Ö—Bš*™ª ¢Òj‰Š‰K¸®izR&VÖ–æFW"6Æ÷G>ûÈÎ˜şXXÒ7&öâzˆŞ[èÎXhŞkI~x˜€¢"" ¢–×÷'BF–ÖR2÷F–ÖP ¢Fö¶VâÒ6öæf–rævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"’÷"÷2æVçf—&öâævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"Â""¢–bæ÷BFö¶Vã ¢&WGW&â²'6VçB#¢Â'6¶—VB#¢Â&W'&÷"#¢$Ä”äUô4„ääTÅô44U55õDô´Tâ—2æ÷B6WB'ÒÂC  ¢FFöf–ÆRÒ6öæf–u²$DDôd”ÄR%Ğ¢7FFRÒÆöE÷7FFR†FFöf–ÆR¢6VæFW"Ò6öæf–rævWB‚$Ä”äUõU4…õ4TäDU""’÷"Æ–æU÷W6…öÖW76vP¢æ÷rÒ7W'&VçEö÷F–ÖR†6öæf–r¢–bæ÷BÆ–æUöæöåöVÖW&vVæ7•÷W6…öÆÆ÷vVB‡7FFRÂ6öæf–rÂæ÷r“ ¢&WGW&âÆ–æUö'VFvWEö&Æö6¶VE÷&W7öç6R‡7FFRÂ6öæf–rÂæ÷r¢FöF’Òæ÷rç7G&gF–ÖR‚"U’ÒVÒÒVB"¢6VçBÒ ¢6¶—VBÒ ¢&Æö6¶VBÒ ¢&W7VÇG2ÒµĞ¢W6…ö6÷VçBÒ  ¢f÷"W6W"–â7FFRævWB‚'W6W'2"Â·Ò’çfÇVW2‚“ ¢Æ–æU÷W6W%ö–BÒ7G"‡W6W"ævWB‚&Æ–æU÷W6W%ö–B"’÷"""’ç7G&—‚¢–bæ÷BÆ–æU÷W6W%ö–C ¢6¶—VB³Ò¢6öçF–çVP¢–bW6W"ævWB‚&Æ–æU÷W6…ö&Æö6¶VB"“ ¢&Æö6¶VB³Ò¢6¶—VB³Ò¢6öçF–çVP¢F–ÖW2Ò&VÖ–æFW%÷F–ÖW5öf÷%÷&öf–ÆR‡W6W"¢ÖW76vRÒ'V–ÆEöF–Ç•ö6†V6¶–åöfÆW‚†æ÷rÂF&vWE÷F–ÖSÒ""Â&öf–ÆS×W6W"¢G'“ ¢&W7VÇBÒ6VæFW"‡Fö¶VâÂÆ–æU÷W6W%ö–BÂÖW76vR¢öÖ&µö6†V6¶–å÷&VÖ–æFW%÷6Æ÷G2‡W6W"ÂFöF’ÂF–ÖW2ÂF–ÖW2¢W6W%²&6†V6¶–åö'&öF67E÷6VçEöFFW2%ÒÒ6÷'FVB€¢6WB‡W6W"ævWB‚&6†V6¶–åö'&öF67E÷6VçEöFFW2"’÷"µÒ’Â·FöF—Ğ¢•²Ó3¥Ğ¢VæEöæ÷F–f–6F–öåöÆör€¢7FFRÂ&6†V6¶–åö'&öF67B"ÂÆ–æU÷W6W%ö–BÂ'6VçB"ÂÖW76vRÂ§6öâæGV×2‡&W7VÇBÂVç7W&Uö66–“ÔfÇ6R¢¢6VçB³Ò¢W6…ö6÷VçB³Ò¢&W7VÇG2æVæB‡²&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–BÂ'&W7VÇB#¢&W7VÇGÒ¢–bW6UöWfW'’æBW6…ö6÷VçBR–çB‡W6UöWfW'’’ÓÒ ¢÷F–ÖRç6ÆVW†fÆöB‡W6U÷6V6öæG2’¢W†6WBW†6WF–öâ2W†3 ¢–böÖ&µöÆ–æU÷W6…ö&Æö6¶VB‡W6W"ÂW†2“ ¢&Æö6¶VB³Ò¢VæEöæ÷F–f–6F–öåöÆör‡7FFRÂ&6†V6¶–åö'&öF67B"ÂÆ–æU÷W6W%ö–BÂ&&Æö6¶VB"ÂÖW76vRÂ7G"†W†2’¢VÇ6S ¢VæEöæ÷F–f–6F–öåöÆör‡7FFRÂ&6†V6¶–åö'&öF67B"ÂÆ–æU÷W6W%ö–BÂ&f–ÆVB"ÂÖW76vRÂ7G"†W†2’¢6¶—VB³Ò¢&W7VÇG2æVæB‡²&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–BÂ&W'&÷"#¢7G"†W†2—Ò ¢6fU÷7FFR†FFöf–ÆRÂ7FFR¢†öÆ–F’Ò†öÆ–F—5÷Græ†öÆ–F•öf÷"†æ÷r’–b†öÆ–F—5÷Gr—2æ÷BæöæRVÇ6RæöæP¢&WGW&â°¢'6VçB#¢6VçBÀ¢'6¶—VB#¢6¶—VBÀ¢&&Æö6¶VB#¢&Æö6¶VBÀ¢&ÖöFR#¢&'&öF67B"À¢&†öÆ–F’#¢††öÆ–F’÷"·Ò’ævWB‚&æÖR"’–b†öÆ–F’VÇ6RæöæRÀ¢'÷6—F—fU÷V÷FR#¢†öÆ–F—5÷Grç÷6—F—fU÷V÷FUöf÷"†æ÷r’–b†öÆ–F—5÷Gr—2æ÷BæöæRVÇ6RæöæRÀ¢'&W7VÇG2#¢&W7VÇG2À¢ÒÂ#   ¦FVb6VæE÷F&vWFVEö6†V6¶–å÷&WW6‚†6öæf–rÂÆ–æU÷W6W%ö–G2“ ¢""%6fVÇ’&R×6VæBFöF’w2fÆW‚FòW‡Æ–6—FÇ’6VÆV7FVB7F—fRÖVÖ&W'2öæÇ’â"" ¢Fö¶VâÒ6öæf–rævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"’÷"÷2æVçf—&öâævWB€¢$Ä”äUô4„ääTÅô44U55õDô´Tâ"Â" ¢¢–bæ÷BFö¶Vã ¢&WGW&â²'6VçB#¢Â&f–ÆVB#¢Â&W'&÷"#¢$Ä”äUô4„ääTÅô44U55õDô´Tâ—2æ÷B6WB'ÒÂC ¢&WVW7FVBÒÆ—7B†F–7Bæg&öÖ¶W—2€¢7G"‡fÇVR÷"""’ç7G&—‚’f÷"fÇVR–â†Æ–æU÷W6W%ö–G2÷"µÒ¢–b7G"‡fÇVR÷"""’ç7G&—‚¢’•³£Ğ¢&WF—&VBÒ°¢fÇVRç7G&—‚¢f÷"fÇVR–â&Rç7Æ—B€¢"%²Ã¾ûÉµÇ5Ò²"Â7G"€¢6öæf–rævWB‚%$UD•$TEôÄ”äUõU4U%ô”E2"¢÷"%UöFWÆ÷•÷6Öö¶Uö‚ÅVs#63ƒ“–cSCFCSSC#&cC6Cs#sB ¢¢¢–bfÇVRç7G&—‚¢Ğ¢7FFRÒÆöE÷7FFR†6öæf–u²$DDôd”ÄR%Ò¢W6W'2Ò7FFRævWB‚'W6W'2"’÷"·Ğ¢6VæFW"Ò6öæf–rævWB‚$Ä”äUõU4…õ4TäDU""’÷"Æ–æU÷W6…öÖW76vP¢æ÷rÒ7W'&VçEö÷F–ÖR†6öæf–r¢FöF’Òæ÷rç7G&gF–ÖR‚"U’ÒVÒÒVB"¢6VçBÒf–ÆVBÒ ¢6¶—VE÷&WF—&VBÒµĞ¢6¶—VEö–æ7F—fRÒµĞ¢æ÷Eöf÷VæBÒµĞ¢&W7VÇG2ÒµĞ¢f÷"V–B–â&WVW7FVC ¢–bV–B–â&WF—&VC ¢6¶—VE÷&WF—&VBæVæB‡V–B¢6öçF–çVP¢&öf–ÆRÒW6W'2ævWB‡V–B¢–bæ÷B—6–ç7Fæ6R‡&öf–ÆRÂF–7B“ ¢&öf–ÆRÒæW‡B€¢‡&÷rf÷"&÷r–âW6W'2çfÇVW2‚’–b7G"‚‡&÷r÷"·Ò’ævWB‚&Æ–æU÷W6W%ö–B"’÷"""’ç7G&—‚’ÓÒV–B’À¢æöæRÀ¢¢–bæ÷B—6–ç7Fæ6R‡&öf–ÆRÂF–7B“ ¢æ÷Eöf÷VæBæVæB‡V–B¢6öçF–çVP¢–b&öf–ÆRævWB‚&ÖVÖ&W'6†—÷W6VB"’÷"æ÷BÖVÖ&W'6†—ö66W75ö7F—fR‡&öf–ÆRÂæ÷r“ ¢6¶—VEö–æ7F—fRæVæB‡V–B¢6öçF–çVP¢ÖW76vRÒ'V–ÆEöF–Ç•ö6†V6¶–åöfÆW‚†æ÷rÂF&vWE÷F–ÖSÒ""Â&öf–ÆS×&öf–ÆR¢G'“ ¢&W7VÇBÒ6VæFW"‡Fö¶VâÂV–BÂÖW76vR¢&öf–ÆU²&Æ–æU÷W6…ö&Æö6¶VB%ÒÒfÇ6P¢&öf–ÆRç÷‚&Æ–æU÷W6…ö&Æö6¶VEöB"ÂæöæR¢F–ÖW2Ò&VÖ–æFW%÷F–ÖW5öf÷%÷&öf–ÆR‡&öf–ÆR’÷"²##£%Ğ¢öÖ&µö6†V6¶–å÷&VÖ–æFW%÷6Æ÷G2‡&öf–ÆRÂFöF’ÂF–ÖW2ÂF–ÖW2¢VæEöæ÷F–f–6F–öåöÆör€¢7FFRÂ&6†V6¶–å÷F&vWFVE÷&WW6‚"ÂV–BÂ'6VçB"ÂÖW76vRÀ¢§6öâæGV×2‡&W7VÇBÂVç7W&Uö66–“ÔfÇ6R’À¢¢6VçB³Ò¢&W7VÇG2æVæB‡²&Æ–æU÷W6W%ö–B#¢V–BÂ'7FGW2#¢'6VçB'Ò¢W†6WBW†6WF–öâ2W†3 ¢f–ÇW&RÒ÷&V6÷&E÷66†VGVÆVE÷W6…öf–ÇW&R€¢7FFRÂ&öf–ÆRÂb&6†V6¶–â×&WW6ƒ§·FöF—Ó§·V–GÒ"À¢&6†V6¶–å÷F&vWFVE÷&WW6‚"ÂV–BÂÖW76vRÂW†2Âæ÷rÀ¢¢f–ÆVB³Ò¢&W7VÇG2æVæB‡°¢&Æ–æU÷W6W%ö–B#¢V–BÀ¢'7FGW2#¢&f–ÆVB"À¢&f–ÇW&Uö¶–æB#¢f–ÇW&RævWB‚&¶–æB"’À¢'FV6†æ–6ÅöFWF–Â#¢7G"†W†2•³£ÒÀ¢Ò¢6fU÷7FFR†6öæf–u²$DDôd”ÄR%ÒÂ7FFR¢&WGW&â°¢'6VçB#¢6VçBÀ¢&f–ÆVB#¢f–ÆVBÀ¢'6¶—VE÷&WF—&VB#¢6¶—VE÷&WF—&VBÀ¢'6¶—VEö–æ7F—fR#¢6¶—VEö–æ7F—fRÀ¢&æ÷Eöf÷VæB#¢æ÷Eöf÷VæBÀ¢'&W7VÇG2#¢&W7VÇG2À¢ÒÂ#   ¦FVböVÆ–v–&ÆU÷W'6öæÆ—¦VEö6†V6¶–åöÖVÖ&W'2‡7FFRÂæ÷sÔæöæR“ ¢""%&WGW&â7F—fRÂW6†&ÆRÖVÖ&W'2f÷"F†RFÖ–â6&B&Wf–Wr÷6VæBfÆ÷râ"" ¢7W'&VçBÒæ÷r÷"7W'&VçEö÷F–ÖR‡·Ò¢&÷w2ÒµĞ¢f÷"¶W’Â&öf–ÆR–â‡7FFRævWB‚'W6W'2"’÷"·Ò’æ—FV×2‚“ ¢–bæ÷B—6–ç7Fæ6R‡&öf–ÆRÂF–7B“ ¢6öçF–çVP¢V–BÒ7G"‡&öf–ÆRævWB‚&Æ–æU÷W6W%ö–B"’÷"¶W’÷"""’ç7G&—‚¢–bæ÷B&RægVÆÆÖF6‚‡"%U³Ó–ÖdÔe×³3'Ò"ÂV–B“ ¢6öçF–çVP¢–b&öf–ÆRævWB‚&Æ–æU÷W6…ö&Æö6¶VB"’÷"&öf–ÆRævWB‚&ÖVÖ&W'6†—÷W6VB"“ ¢6öçF–çVP¢–bæ÷BÖVÖ&W'6†—ö66W75ö7F—fR‡&öf–ÆRÂ7W'&VçB“ ¢6öçF–çVP¢&÷w2æVæB‚‡V–BÂ&öf–ÆR’¢&WGW&â6÷'FVB‡&÷w2Â¶W“ÖÆÖ&F&÷s¢‡7G"‡&÷u³ÒævWB‚&F—7Æ•öæÖR"’÷"""’Â&÷u³Ò’  ¦FVbW'6öæÆ—¦VEö6†V6¶–å÷W6…÷&Wf–Wr†FFöf–ÆRÂæ÷sÔæöæR“ ¢&÷w2ÒöVÆ–v–&ÆU÷W'6öæÆ—¦VEö6†V6¶–åöÖVÖ&W'2†ÆöE÷7FFR†FFöf–ÆR’Âæ÷sÖæ÷r¢&WGW&â°¢&VÆ–v–&ÆUö6÷VçB#¢ÆVâ‡&÷w2’À¢&ÖVÖ&W'2#¢°¢°¢&F—7Æ•öæÖR#¢7G"‡&öf–ÆRævWB‚&F—7Æ•öæÖR"’÷"$Ä”äRKÛşyJˆR"’À¢&Æ–æU÷W6W%ö–B#¢V–BÀ¢&Ö6¶VEöÆ–æU÷W6W%ö–B#¢öÖ6µöÆ–æU÷W6W%ö–B‡V–B’À¢'Æâ#¢7G"‡&öf–ÆRævWB‚'Æâ"’÷"""’À¢Ğ¢f÷"V–BÂ&öf–ÆR–â&÷w0¢ÒÀ¢Ğ  ¦FVb÷fÆ–FFVEö‡GG5÷W&Â‡fÇVRÂf–VÆEöæÖR“ ¢fÇVRÒ7G"‡fÇVR÷"""’ç7G&—‚¢'6VBÒW&ÆÆ–"ç'6RçW&Ç'6R‡fÇVR¢–b'6VBç66†VÖRÒ&‡GG2"÷"æ÷B'6VBææWFÆö3 ¢&—6RfÇVTW'&÷"†b'¶f–VÆEöæÖWŞXú®hê^Xùr…EE2{k.YØ"¢&WGW&âfÇVP  ¦FVböæ÷&ÖÆ—¦Uö6&E÷FV×ÆFR‡–ÆöBÂ¢ÂFV×ÆFUö–CÔæöæR“ ¢æÖRÒ7G"‡–ÆöBævWB‚&æÖR"’÷"""’ç7G&—‚•³£cĞ¢&ÆW76–ærÒ7G"‡–ÆöBævWB‚&&ÆW76–ær"’÷"""’ç7G&—‚•³£3Ğ¢–bæ÷BæÖS ¢&—6RfÇVTW'&÷"‚.Š¸¾‹ËXZ^zøNiÊÎYŞz‹"¢–bæ÷B&ÆW76–æs ¢&—6RfÇVTW'&÷"‚.Š¸¾‹ËXZ^zYŞzhşih~ZÙr"¢&u÷7G–ÆRÒ–ÆöBævWB‚&&ÆW76–æu÷7G–ÆR"’÷"·Ğ¢föçEöfÖ–Ç’Ò7G"‡&u÷7G–ÆRævWB‚&föçEöfÖ–Ç’"’÷"'&÷VæFVB"’ç7G&—‚¢–bföçEöfÖ–Ç’æ÷B–â²'&÷VæFVB"Â'7—7FVÒ"Â'6W&–b'Ó ¢föçEöfÖ–Ç’Ò'&÷VæFVB ¢6öÆ÷"Ò7G"‡&u÷7G–ÆRævWB‚&6öÆ÷""’÷""3ccS3B"’ç7G&—‚’çWW"‚¢–bæ÷B&RægVÆÆÖF6‚‡""5³Ó”Ôe×³gÒ"Â6öÆ÷"“ ¢&—6RfÇVTW'&÷"‚.zYŞzhşŠ©îšşˆ›.Š¸¾KÛşyJXZŞKØÒ„U‚ˆ›.z+Â"¢G'“ ¢föçE÷6—¦RÒ–çB‡&u÷7G–ÆRævWB‚'6—¦R"’÷"3B¢W†6WB…G—TW'&÷"ÂfÇVTW'&÷"“ ¢föçE÷6—¦RÒ3@¢föçE÷6—¦RÒÖ‚ƒ#BÂÖ–âƒS"ÂföçE÷6—¦R’¢Æ–vâÒ7G"‡&u÷7G–ÆRævWB‚&Æ–vâ"’÷"&6VçFW""’ç7G&—‚¢–bÆ–vâæ÷B–â²'7F'B"Â&6VçFW""Â&VæB'Ó ¢Æ–vâÒ&6VçFW" ¢÷6—F–öâÒ7G"‡&u÷7G–ÆRævWB‚'÷6—F–öâ"’÷"'F÷"’ç7G&—‚¢–b÷6—F–öâæ÷B–â²'F÷"Â&&÷GFöÒ'Ó ¢÷6—F–öâÒ'F÷ ¢'WGFöç2ÒµĞ¢f÷"&r–âÆ—7B‡–ÆöBævWB‚&'WGFöç2"’÷"µÒ•³£EÓ ¢Æ&VÂÒ7G"‚‡&r÷"·Ò’ævWB‚&Æ&VÂ"’÷"""’ç7G&—‚•³£#Ğ¢–bæ÷BÆ&VÃ ¢6öçF–çVP¢–b‡&r÷"·Ò’ævWB‚&7F–öâ"’ÓÒ&6†V6¶–â# ¢'WGFöç2æVæB‡²&Æ&VÂ#¢Æ&VÂÂ&7F–öâ#¢&6†V6¶–â'Ò¢VÇ6S ¢'WGFöç2æVæB‡²&Æ&VÂ#¢Æ&VÂÂ'W&’#¢÷fÆ–FFVEö‡GG5÷W&Â‚‡&r÷"·Ò’ævWB‚'W&’"’Â.hÈ˜‰^˜
>{Y"—Ò¢–bæ÷B'WGFöç3 ¢&—6RfÇVTW'&÷"‚.ˆ{>[	KùŞyYKˆX¾YÉnih~XÚhÈ˜‰R"¢&WGW&â°¢&–B#¢FV×ÆFUö–B÷"b&6&B×·WV–BçWV–CB‚’æ†W…³£%×Ò"À¢&æÖR#¢æÖRÀ¢'7—7FVÒ#¢fÇ6RÀ¢&&ÆW76–ær#¢&ÆW76–ærÀ¢&†W&õ÷W&Â#¢÷fÆ–FFVEö‡GG5÷W&Â‡–ÆöBævWB‚&†W&õ÷W&Â"’Â.K‹¾YÉb"’À¢&Æövõ÷W&Â#¢D”Å•õT4UôÄôtõõU$ÂÀ¢&&ÆW76–æu÷7G–ÆR#¢°¢&föçEöfÖ–Ç’#¢föçEöfÖ–Ç’À¢&6öÆ÷"#¢6öÆ÷"À¢'6—¦R#¢föçE÷6—¦RÀ¢&Æ–vâ#¢Æ–vâÀ¢'÷6—F–öâ#¢÷6—F–öâÀ¢ÒÀ¢&'WGFöç2#¢'WGFöç2À¢'WFFVEöB#¢FFWF–ÖRææ÷r…¦öæT–æfò‚$6–õF—V’"’’æ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"’À¢Ğ  ¦FVbÆ—7Eö6&E÷FV×ÆFW2‡7FFR“ ¢7W7FöÒÒ·&÷rf÷"&÷r–âÆ—7B‚‡7FFR÷"·Ò’ævWB‚'W'6öæÆ—¦VEö6&E÷FV×ÆFW2"’÷"µÒ’–b—6–ç7Fæ6R‡&÷rÂF–7B•Ğ¢&WGW&â¶6÷’æFVW6÷’„DTdTÅEô4$EõDTÕÄDR•Ò²7W7FöĞ  ¦FVb6fUö6&E÷FV×ÆFR†FFöf–ÆRÂ–ÆöB“ ¢7FFRÒÆöE÷7FFR†FFöf–ÆR¢&WVW7FVEö–BÒ7G"‡–ÆöBævWB‚&–B"’÷"""’ç7G&—‚¢–b&WVW7FVEö–BÓÒDTdTÅEô4$EõDTÕÄDU²&–B%Ó ¢&—6RfÇVTW'&÷"‚.{;¾{[š	ŠŠŞzøNiÊÎKˆŞXúşŠhnZú¾ûÈÎŠ¸¾XúnZÙikzøNiÊÂ"¢FV×ÆFRÒöæ÷&ÖÆ—¦Uö6&E÷FV×ÆFR‡–ÆöBÂFV×ÆFUö–C×&WVW7FVEö–B÷"æöæR¢&÷w2ÒÆ—7B‡7FFRævWB‚'W'6öæÆ—¦VEö6&E÷FV×ÆFW2"’÷"µÒ¢&÷w2Ò·&÷rf÷"&÷r–â&÷w2–b7G"‚‡&÷r÷"·Ò’ævWB‚&–B"’’ÒFV×ÆFU²&–B%ÕĞ¢&÷w2æVæB‡FV×ÆFR¢7FFU²'W'6öæÆ—¦VEö6&E÷FV×ÆFW2%ÒÒ&÷w5²Ó¥Ğ¢6fU÷7FFR†FFöf–ÆRÂ7FFR¢&WGW&âFV×ÆFP  ¦FVbö6&E÷FV×ÆFUö'•ö–B‡7FFRÂFV×ÆFUö–B“ ¢vçFVBÒ7G"‡FV×ÆFUö–B÷"DTdTÅEô4$EõDTÕÄDU²&–B%Ò¢&WGW&âæW‡B‚‡&÷rf÷"&÷r–âÆ—7Eö6&E÷FV×ÆFW2‡7FFR’–b&÷rævWB‚&–B"’ÓÒvçFVB’ÂæöæR  ¦FVböÇ•ö6&E÷FV×ÆFR†ÖW76vRÂFV×ÆFRÂ&öf–ÆR“ ¢&W7VÇBÒ6÷’æFVW6÷’†ÖW76vR¢6öçFVçG2Ò&W7VÇE²&6öçFVçG2%Ğ¢6öçFVçG5²&†W&ò%Õ²'W&Â%ÒÒFV×ÆFU²&†W&õ÷W&Â%Ğ¢6öçFVçG5²&†W&ò%Õ²&7V7E&F–ò%ÒÒ#C£R ¢&öG’Ò6öçFVçG5²&&öG’%Õ²&6öçFVçG2%Ğ¢F—7Æ•öæÖRÒ7G"‡&öf–ÆRævWB‚&F—7Æ•öæÖR"’÷".KÚ"¢&öG•³Õ²'FW‡B%ÒÒb'¶F—7Æ•öæÖWŞûÈÎK¸®ZJKˆXˆ~˜;ŞZ[ŞYxîûÉò ¢7G–ÆRÒ²¢¤DTdTÅEô4$EõDTÕÄDU²&&ÆW76–æu÷7G–ÆR%ÒÂ¢¢‡FV×ÆFRævWB‚&&ÆW76–æu÷7G–ÆR"’÷"·Ò—Ğ¢6—¦U÷fÇVRÒ–çB‡7G–ÆRævWB‚'6—¦R"’÷"3B¢fÆW…÷6—¦RÒ&Ær"–b6—¦U÷fÇVRÃÒ#‚VÇ6R'†Â"–b6—¦U÷fÇVRÃÒ3bVÇ6R'‡†Â"–b6—¦U÷fÇVRÃÒCBVÇ6R#7†Â ¢&ÆW76–æuöæöFRÒ°¢'G—R#¢'FW‡B"Â'FW‡B#¢FV×ÆFU²&&ÆW76–ær%ÒÂ'6—¦R#¢fÆW…÷6—¦RÀ¢'vV–v‡B#¢&&öÆB"Â&6öÆ÷"#¢7G–ÆU²&6öÆ÷"%ÒÂ&Æ–vâ#¢7G–ÆU²&Æ–vâ%ÒÂ'w&#¢G'VRÀ¢Ğ¢–b7G–ÆRævWB‚'÷6—F–öâ"’ÓÒ&&÷GFöÒ# ¢&öG’æVæB†&ÆW76–æuöæöFR¢VÇ6S ¢&öG’æ–ç6W'BƒÂ&ÆW76–æuöæöFR¢6öÆ÷'2Ò²"3d3D"Â"3#Sc4T""Â"4D3#c#b"Â"4CDr%Ğ¢&VæFW&VEö'WGFöç2ÒµĞ¢f÷"–æFW‚Â'WGFöâ–âVçVÖW&FR‡FV×ÆFRævWB‚&'WGFöç2"’÷"µÒ“ ¢–b'WGFöâævWB‚&7F–öâ"’ÓÒ&6†V6¶–â# ¢7F–öâÒ²'G—R#¢'÷7F&6²"Â&Æ&VÂ#¢'WGFöå²&Æ&VÂ%ÒÂ&FF#¢&7F–öãÖ6†V6¶–â"Â&F—7Æ•FW‡B#¢.h‰[›>Zè’'Ğ¢VÇ6S ¢7F–öâÒ²'G—R#¢'W&’"Â&Æ&VÂ#¢'WGFöå²&Æ&VÂ%ÒÂ'W&’#¢'WGFöå²'W&’%×Ğ¢&VæFW&VEö'WGFöç2æVæB‡²'G—R#¢&'WGFöâ"Â&7F–öâ#¢7F–öâÂ'7G–ÆR#¢'&–Ö'’"Â&6öÆ÷"#¢6öÆ÷'5¶–æFW‚RÆVâ†6öÆ÷'2•ÒÂ&†V–v‡B#¢&ÖB'Ò¢6öçFVçG5²&fö÷FW"%Õ²&6öçFVçG2%ÒÒ&VæFW&VEö'WGFöç0¢&WGW&â&W7VÇ@  ¦FVb&Wf–Wu÷W'6öæÆ—¦VEö6&B†FFöf–ÆRÂÆ–æU÷W6W%ö–BÂFV×ÆFUö–BÂæ÷sÔæöæR“ ¢7FFRÒÆöE÷7FFR†FFöf–ÆR¢VÆ–v–&ÆRÒF–7B…öVÆ–v–&ÆU÷W'6öæÆ—¦VEö6†V6¶–åöÖVÖ&W'2‡7FFRÂæ÷sÖæ÷r’¢&öf–ÆRÒVÆ–v–&ÆRævWB‡7G"†Æ–æU÷W6W%ö–B÷"""’ç7G&—‚’¢–bæ÷B&öf–ÆS ¢&—6RÆöö·WW'&÷"‚.jÚNiÈ>Y:yºîX˜Şk).iÈXúşhêi*Ş‹8~jÂ"¢FV×ÆFRÒö6&E÷FV×ÆFUö'•ö–B‡7FFRÂFV×ÆFUö–B¢–bæ÷BFV×ÆFS ¢&—6RÆöö·WW'&÷"‚.h›îKˆŞX‹hÈ~Zé®y¨NYÉnih~XÚzøNiÊÂ"¢7W'&VçBÒæ÷r÷"7W'&VçEö÷F–ÖR‡·Ò¢ÖW76vRÒöÇ•ö6&E÷FV×ÆFR†'V–ÆEöF–Ç•ö6†V6¶–åöfÆW‚†7W'&VçBÂ&öf–ÆS×&öf–ÆR’ÂFV×ÆFRÂ&öf–ÆR¢&WGW&â°¢&ÖVÖ&W"#¢²&F—7Æ•öæÖR#¢7G"‡&öf–ÆRævWB‚&F—7Æ•öæÖR"’÷"$Ä”äRKÛşyJˆR"’Â&Ö6¶VEöÆ–æU÷W6W%ö–B#¢öÖ6µöÆ–æU÷W6W%ö–B†Æ–æU÷W6W%ö–B—ÒÀ¢'FV×ÆFR#¢FV×ÆFRÀ¢&ÖW76vR#¢ÖW76vRÀ¢Ğ  ¦FVb†öÆ–F•÷FV×ÆFUö6FÆör‡–V#ÔæöæR“ ¢–V"Ò–çB‡–V"÷"FFWF–ÖRææ÷r…¦öæT–æfò‚$6–õF—V’"’’ç–V"¢&÷w2Ò°¢‚.XX>izb"Â#Ó"Â.kˆ^iš˜yˆ›.™›ŞXX8XZZën‹øîhê^ik[›B"Â.iˆîKªîZè[ø2"’À¢‚.Š[şkH¾h8^K«®zø"Â#"ÓB"Â.™¹K«®kª¾i©n™š®KËN8ˆ«iÙşˆˆ~iùNXX’"Â.kZ®kÊ¾kª¾iùB"’À¢‚.‹ë.i¸nik[›B"Â.KéŞ‹ë.i¸b"Â.[›NzøYÉYÉ>8{H^˜yxx{ˆˆ~z©~ˆ«"Â.YiÎk
>kª¾i©b"’À¢‚.XX>Zë^zø"Â.KéŞ‹ë.i¸b"Â.ZIÎz›®xx{8kšşYÉ>ˆˆ~YÉYÉ>jÂ"Â.kª¾i©nYÉYÉ2"’À¢‚.XY.zº^zø"Â#BÓB"Â.Zën[ªŞ™š®KËN8[Úˆ›.š*zèşˆˆ~ˆØYË"Â.kK¾kÙZè[ø2"’À¢‚.kˆ^iˆîzø"Â.KéŞ[›N[ªb"Â.kˆ^iÉ~iŠ^iz^8y›Şˆ«ˆˆ~Zè™ÙÎh	Ş[ûR"Â.k(™ÙÎiùNY(Â"’À¢‚.jøŞŠj®zø"Â.K©NiÈzÊÎK¨ÎX¾i‰şiÉşizR"Â.jøŞZ[>y»i88[«~K˜>šjˆˆ~išXX’"Â.kª¾iùNhIşŠÉÒ"’À¢‚.zºşXØzø"Â.KéŞ‹ë.i¸b"Â.{+Ş‰8šiXÈ^ˆˆ~k+>[+išXX’"Â.kˆ^ikZè[«r"’À¢‚.x‹nŠj®zø"Â#‚Ó‚"Â.x‹x‹ˆˆ~ZënK«®8zYŞzhş‰¸¾{9^y¨NXH[ÈşhIò"Â.kª¾i©nhIşŠÉÒ"’À¢‚.Kˆ>ZI^h8^K«®zø"Â.KéŞ‹ë.i¸b"Â.i‰şk+>8x›Şh˜¾™š®KËNˆˆ~iùNY(ÎxxXX’"Â.kZ®kÊ¾ZèŠÛr"’À¢‚.KŠŞXX>zø"Â.KéŞ‹ë.i¸b"Â.iùNY(Îxxx¾8[›>ZèzXzhşhHş‹"Â.ˆè®˜xŞZè[ø2"’À¢‚.iY[Š¾zø"Â#’Ó#‚"Â.i»iÊÎ8i©nXXˆˆ~hIşŠÉŞXÚ"Â.yú^h
~kª¾i©b"’À¢‚.KŠŞzx¾zø"Â.KéŞ‹ë.i¸b"Â.YÉ>iÈ8ZënK«®YÉYÉ>ˆˆ~iÈšH^ˆËn[ŠÒ"Â.YÉYÉ>Zè[ø2"’À¢‚.YÈ¾h[nizR"Â#Ó"Â.Xûx>Yøî[ˆ.išXX8zøh[niy~[™şˆ›.[Ú’"Â.iˆîKªîˆè®˜xÒ"’À¢‚.˜xŞ™›Şzø"Â.KéŞ‹ë.i¸b"Â.™[~‹Êˆˆ~i™®‹ÊiZ>jÚ^8zx¾iz^ˆø®ˆ«"Â.iZÎˆkª¾i©b"’À¢‚.‰
Îˆnzø"Â#Ó3"Â.XúşhI¾XÙ~y9Îxxˆˆ~Zën[ªŞkKî[Ò"Â.zº^‹j>KˆŞš™®h)¢"’À¢‚.hIşhzø"Â.XØKˆiÈzÊÎY¹¾X¾i‰şiÉşY¹²"Â.ZënK«®šIjÎ8xzŞXXˆˆ~hIşŠÉÒ"Â.kª¾i©nhIşh’"’À¢‚.ˆnŠ©^zø"Â#"Ó#R"Â.ˆnŠ©^j‹8zjîxšˆˆ~[^Zëni©nXX’"Â.kª¾šjzYŞzhò"’À¢‚.‹z[›B"Â#"Ó3"Â.Yøî[ˆ.xYx¾8ZënK«®y»KËN‹øîik[›B"Â.[ˆÎiÉ¾Zè[ø2"’À¢Ğ¢&WGW&â·²&–B#¢b&†öÆ–F’×¶–æFW‚³Ò"Â&æÖR#¢æÖRÂ&FFUöÆ&VÂ#¢FFUöÆ&VÂÂ&VÆVÖVçG2#¢VÆVÖVçG2Â&ÖööB#¢ÖööBÂ'–V"#¢–V'Òf÷"–æFW‚Â†æÖRÂFFUöÆ&VÂÂVÆVÖVçG2ÂÖööB’–âVçVÖW&FR‡&÷w2•Ğ  ¦FVb'V–ÆEö†öÆ–F•ö–ÖvU÷&ö×B‡–ÆöB“ ¢†öÆ–F’Ò7G"‡–ÆöBævWB‚&†öÆ–F’"’÷".ˆz®Šˆ.zøizR"’ç7G&—‚•³£CĞ¢ÖööBÒ7G"‡–ÆöBævWB‚&ÖööB"’÷".kª¾i©nZè[ø2"’ç7G&—‚•³£ƒĞ¢VÆVÖVçG2Ò7G"‡–ÆöBævWB‚&VÆVÖVçG2"’÷".ZënK«®K©.y»™š®KËB"’ç7G&—‚•³£#Ğ¢æ÷FW2Ò7G"‡–ÆöBævWB‚&æ÷FW2"’÷"""’ç7G&—‚•³£3Ğ¢&WGW&â€¢b.x+®Xûx2Ä”äRiÈŞX¹8îjøşiz^[›>Zè8şŠ;ŞKÙÂ¶†öÆ–F—ÒYÉnih~XÚy¨Ny»N[ÈşK‹¾ŠinŠk®ˆ8Îišş8" ¢b.k
>k	¾ûÉ§¶ÖööGŞ8.yZ¾™Ú.XX>{JûÉ§¶VÆVÖVçG7Ş8.Š9ÎXX^ûÉ§¶æ÷FW2÷"~ˆz®xKn8yÉşZún8kª¾šj‚wŞ8" ¢.jx¾YÉnš	yYKˆ®ikˆˆ~Kˆ¾ikK›îkzz›®™i>Ké¾{;¾{[yh®XªY8x˜Îˆˆ~i8ŞKÙÎXX>K»nûÈÎy»N[ÈòC£^ûÈÎ˜Yh˜¾j™şk»şx˜XÚ8" ¢.Xú®yIşh‰ˆ8ÎišşûÉ¾KˆŞŠhK»¾KÙ^ih~ZÙ~8KˆŞŠhÆövş8KˆŞŠhYXnj‰8KˆŞŠhhÈ˜‰^8KˆŞŠhK¸¾™Ú.hŠ®YÉn8KˆŞŠhkZîkNXÛ8" ¢  ¦FVbö÷Væ•ö†öÆ–F•ö–ÖvR†•ö¶W’Â&ö×B“ ¢&öG’Ò§6öâæGV×2‡²&ÖöFVÂ#¢&FÆÂÖRÓ2"Â'&ö×B#¢&ö×BÂ'6—¦R#¢##Gƒs“""Â'VÆ—G’#¢'7FæF&B"Â&â#¢Ò’æVæ6öFR‚'WFbÓ‚"¢&WÒW&ÆÆ–"ç&WVW7Bå&WVW7B‚&‡GG3¢òö’æ÷Væ’æ6öÒ÷cö–ÖvW2övVæW&F–öç2"ÂFFÖ&öG’Â†VFW'3×²$WF†÷&—¦F–öâ#¢b$&V&W"¶•ö¶W—Ò"Â$6öçFVçBÕG—R#¢&Æ–6F–öâö§6öâ'ÒÂÖWF†öCÒ%õ5B"¢v—F‚W&ÆÆ–"ç&WVW7BçW&Æ÷Vâ‡&WÂF–ÖV÷WCÓ“’2&W7öç6S ¢FFÒ§6öâæÆöG2‡&W7öç6Rç&VB‚’æFV6öFR‚'WFbÓ‚"’¢&WGW&â7G"‚‚†FFævWB‚&FF"’÷"··ÕÒ•³Ò’ævWB‚'W&Â"’÷"""  ¦FVbvVæW&FUö†öÆ–F•ö&6¶w&÷VæB†6öæf–rÂ–ÆöB“ ¢&ö×BÒ'V–ÆEö†öÆ–F•ö–ÖvU÷&ö×B‡–ÆöB¢vVæW&F÷"Ò6öæf–rævWB‚$„ôÄ”D•ô”ÔtUôtTäU$Dõ""¢•ö¶W’Ò7G"†6öæf–rævWB‚$õTä•ô•ô´U’"’÷"÷2æVçf—&öâævWB‚$õTä•ô•ô´U’"’÷"""’ç7G&—‚¢–bæ÷BvVæW&F÷"æBæ÷B•ö¶W“ ¢&WGW&â²&ö²#¢fÇ6RÂ&W'&÷"#¢&–ÖvUö•ö¶W•öÖ—76–ær"Â&ÖW76vR#¢.[	®iÊ®ŠŠŞZé®YÉnx˜~yIşh‰˜y™ûÈÎŠ¸¾XXYÊ‚&VæFW"y+Z(>Šè®i[XªXZRõTä•ô•ô´U8""Â'&ö×B#¢&ö×GÒÂS0¢G'“ ¢–ÖvU÷W&ÂÒ†vVæW&F÷"÷"†ÆÖ&FfÇVS¢ö÷Væ•ö†öÆ–F•ö–ÖvR†•ö¶W’ÂfÇVR’’’‡&ö×B¢–ÖvU÷W&ÂÒ÷fÆ–FFVEö‡GG5÷W&Â†–ÖvU÷W&ÂÂ.yIşh‰YÉnx˜r"¢W†6WBW†6WF–öâ2W†3 ¢&WGW&â²&ö²#¢fÇ6RÂ&W'&÷"#¢&–ÖvUövVæW&F–öåöf–ÆVB"Â&ÖW76vR#¢.YÉnx˜~yIşh‰ZKiY~ûÈÎŠ¸¾zˆŞ[èÎ˜xŞŠšnh‰nKúîiKhøş‹û8""Â&FWF–Â#¢7G"†W†2•³£SÒÂ'&ö×B#¢&ö×GÒÂS ¢&WGW&â²&ö²#¢G'VRÂ&–ÖvU÷W&Â#¢–ÖvU÷W&ÂÂ'&ö×B#¢&ö×BÂ&ÖW76vR#¢.ˆ8Îišş[{.yIşh‰ûÈÎŠ¸¾XXš	ŠkŞûÉ¾yºîX˜Ş[	®iÊ®XK.ZÙh‰nhêi*Ş8"'ÒÂ#   ¦FVbFÖ–å÷6VæE÷W'6öæÆ—¦VEö6†V6¶–åö6&G2€¢6öæf–rÂ¢ÂÖöFRÂ6öæf—&ÖVCÔfÇ6RÂÆ–æU÷W6W%ö–CÒ""ÂFV×ÆFUö–CÒ&F–Ç’×V6RÖFVfVÇB"Âæ÷sÔæöæP¢“ ¢""%6VæBF†R7W'&VçBW'6öæÆ—¦VB6†V6²Ö–â6&BgFW"W‡Æ–6—BFÖ–â6öæf—&ÖF–öââ"" ¢–b6öæf—&ÖVB—2æ÷BG'VS ¢&WGW&â²&ö²#¢fÇ6RÂ&W'&÷"#¢&6öæf—&ÖF–öå÷&WV—&VB'ÒÂC¢–bÖöFRæ÷B–â²&ÆÂ"Â'6–ævÆR'Ó ¢&WGW&â²&ö²#¢fÇ6RÂ&W'&÷"#¢&–çfÆ–EöÖöFR'ÒÂC ¢Fö¶VâÒ6öæf–rævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"’÷"÷2æVçf—&öâævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"Â""¢–bæ÷BFö¶Vã ¢&WGW&â²&ö²#¢fÇ6RÂ&W'&÷"#¢&Æ–æU÷Fö¶VåöÖ—76–ær'ÒÂS0¢FFöf–ÆRÒ6öæf–u²$DDôd”ÄR%Ğ¢7FFRÒÆöE÷7FFR†FFöf–ÆR¢FV×ÆFRÒö6&E÷FV×ÆFUö'•ö–B‡7FFRÂFV×ÆFUö–B¢–bæ÷BFV×ÆFS ¢&WGW&â²&ö²#¢fÇ6RÂ&W'&÷"#¢'FV×ÆFUöæ÷Eöf÷VæB'ÒÂC@¢7W'&VçBÒæ÷r÷"7W'&VçEö÷F–ÖR†6öæf–r¢VÆ–v–&ÆRÒöVÆ–v–&ÆU÷W'6öæÆ—¦VEö6†V6¶–åöÖVÖ&W'2‡7FFRÂæ÷sÖ7W'&VçB¢–bÖöFRÓÒ'6–ævÆR# ¢vçFVBÒ7G"†Æ–æU÷W6W%ö–B÷"""’ç7G&—‚¢VÆ–v–&ÆRÒ·&÷rf÷"&÷r–âVÆ–v–&ÆR–b&÷u³ÒÓÒvçFVEĞ¢–bæ÷BVÆ–v–&ÆS ¢&WGW&â²&ö²#¢fÇ6RÂ&W'&÷"#¢&ÖVÖ&W%öæ÷EöVÆ–v–&ÆR'ÒÂC@¢6VæFW"Ò6öæf–rævWB‚$Ä”äUõU4…õ4TäDU""’÷"Æ–æU÷W6…öÖW76vP¢6VçBÒf–ÆVBÒ ¢&W7VÇG2ÒµĞ¢f÷"V–BÂ&öf–ÆR–âVÆ–v–&ÆS ¢ÖW76vRÒöÇ•ö6&E÷FV×ÆFR†'V–ÆEöF–Ç•ö6†V6¶–åöfÆW‚†7W'&VçBÂ&öf–ÆS×&öf–ÆR’ÂFV×ÆFRÂ&öf–ÆR¢G'“ ¢6VæFW"‡Fö¶VâÂV–BÂÖW76vR¢VæEöæ÷F–f–6F–öåöÆör‡7FFRÂ&FÖ–å÷W'6öæÆ—¦VEö6†V6¶–â"ÂV–BÂ'6VçB"ÂÖW76vR¢6VçB³Ò¢&W7VÇG2æVæB‡²&Æ–æU÷W6W%ö–B#¢V–BÂ'7FGW2#¢'6VçB'Ò¢W†6WBW†6WF–öâ2W†3 ¢VæEöæ÷F–f–6F–öåöÆör‡7FFRÂ&FÖ–å÷W'6öæÆ—¦VEö6†V6¶–â"ÂV–BÂ&f–ÆVB"ÂÖW76vRÂ7G"†W†2’¢f–ÆVB³Ò¢&W7VÇG2æVæB‡²&Æ–æU÷W6W%ö–B#¢V–BÂ'7FGW2#¢&f–ÆVB'Ò¢6fU÷7FFR†FFöf–ÆRÂ7FFR¢&WGW&â²&ö²#¢f–ÆVBÓÒÂ&ÖöFR#¢ÖöFRÂ'6VçB#¢6VçBÂ&f–ÆVB#¢f–ÆVBÂ'&W7VÇG2#¢&W7VÇG7ÒÂ#   ¦FVb6VæEö&—'F†F•÷&VÖ–æFW'2†6öæf–r“ ¢Fö¶VâÒ6öæf–rævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"’÷"÷2æVçf—&öâævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"Â""¢–bæ÷BFö¶Vã ¢&WGW&â²'6VçB#¢Â'6¶—VB#¢Â&W'&÷"#¢$Ä”äUô4„ääTÅô44U55õDô´Tâ—2æ÷B6WB'ÒÂC  ¢FFöf–ÆRÒ6öæf–u²$DDôd”ÄR%Ğ¢7FFRÒÆöE÷7FFR†FFöf–ÆR¢6VæFW"Ò6öæf–rævWB‚$Ä”äUõU4…õ4TäDU""’÷"Æ–æU÷W6…öÖW76vP¢æ÷rÒ7W'&VçEö÷F–ÖR†6öæf–r¢FöF•öFFRÒæ÷ræFFR‚¢FöF•ö¶W’ÒFöF•öFFRç7G&gF–ÖR‚"U’ÒVÒÒVB"¢6VçBÒ ¢6¶—VBÒ ¢&W7VÇG2ÒµĞ ¢&Æö6¶VBÒ ¢7—7FVÕöW'&÷"ÒfÇ6P¢f÷"W6W"–â7FFRævWB‚'W6W'2"Â·Ò’çfÇVW2‚“ ¢Æ–æU÷W6W%ö–BÒW6W"ævWB‚&Æ–æU÷W6W%ö–B"¢–bæ÷BÆ–æU÷W6W%ö–C ¢6¶—VB³Ò¢6öçF–çVP¢–bæ÷BÆåö†5÷6Ö'E÷&VÖ–æFW'2‡W6W"Âæ÷sÖæ÷r“ ¢6¶—VB³Ò¢6öçF–çVP¢–bW6W"ævWB‚&ÖVÖ&W'6†—÷W6VB"’÷"æ÷BÖVÖ&W'6†—ö66W75ö7F—fR‡W6W"Âæ÷r“ ¢6¶—VB³Ò¢6öçF–çVP¢–bW6W"ævWB‚&Æ–æU÷W6…ö&Æö6¶VB"“ ¢&Æö6¶VB³Ò¢6¶—VB³Ò¢6öçF–çVP¢æ÷FW2ÒW6W"ævWB‚&6ÆVæF%öæ÷FW2"’÷"·Ğ¢–bæ÷B—6–ç7Fæ6R†æ÷FW2ÂF–7B“ ¢6öçF–çVP¢6VçEö¶W—2Ò6WB‡W6W"ævWB‚&&—'F†F•÷&VÖ–æFW%÷6VçEö¶W—2"’÷"µÒ¢f÷"æ÷FUöFFRÂæ÷FR–âæ÷FW2æ—FV×2‚“ ¢f÷"&—'F†F•ö–æFW‚Â&—'F†F’–âVçVÖW&FR†6ÆVæF%öæ÷FUö&—'F†F—2†æ÷FR’“ ¢G'“ ¢&VÖ–æEöF—2Ò–çB†&—'F†F’ævWB‚&&—'F†F•÷&VÖ–æEöF—2"’÷"¢W†6WB…G—TW'&÷"ÂfÇVTW'&÷"“ ¢&VÖ–æEöF—2Ò¢F&vWEöFFRÒFöF•öFFR²F–ÖVFVÇF†F—3×&VÖ–æEöF—2¢–bæ÷B&—'F†F•öö67W'5ööâ†&—'F†F’ÂF&vWEöFFR“ ¢6öçF–çVP¢&—'F†F•÷7Vff—‚Òb#§¶&—'F†F•ö–æFW‡Ò"–b&—'F†F•ö–æFW‚VÇ6R" ¢6VçEö¶W’Ò€¢b'·FöF•ö¶W—Ó§¶æ÷FUöFFWÓ§·&VÖ–æEöF—7×¶&—'F†F•÷7Vff—‡Ò ¢¢–b6VçEö¶W’–â6VçEö¶W—3 ¢6öçF–çVP¢FVÆ—fW'•ö¶W’Òb&&—'F†F“§·6VçEö¶W—Ò ¢–bæ÷BW6…öGFV×EöÆÆ÷vVB‡W6W"ÂFVÆ—fW'•ö¶W’“ ¢6¶—VB³Ò¢6öçF–çVP¢v†òÒ&—'F†F’ævWB‚&&—'F†F•÷&VÆF–öç6†—"’÷"&—'F†F’ævWB‚&&—'F†F•öæÖR"’÷".ZënK«¢ ¢v†Vå÷FW‡BÒ.K¸®ZJ’"–b&VÖ–æEöF—2ÓÒVÇ6R‚.iˆîZJ’"–b&VÖ–æEöF—2ÓÒVÇ6Rb'·&VÖ–æEöF—7ÒZJ[èÂ"¢ÖW76vRÒb'·v†Vå÷FW‡GŞiŠ÷·v†÷ŞyIşiz^ûÈÎŠ‰[é~‹yşK¹nŠª®ˆ.yIşiz^[ú¾jˆ.8.K™şXúşKº^šnh˜¾z+®Š¨ŞK¹nK¸®ZJ[›>Zè8" ¢G'“ ¢&W7VÇBÒ6VæFW"‡Fö¶VâÂÆ–æU÷W6W%ö–BÂÖW76vR¢ö6ÆV%÷W6…öFVÆ—fW'•öf–ÇW&R‡W6W"ÂFVÆ—fW'•ö¶W’¢6VçEö¶W—2æFB‡6VçEö¶W’¢W6W%²&&—'F†F•÷&VÖ–æFW%÷6VçEö¶W—2%ÒÒ6÷'FVB‡6VçEö¶W—2•²Óƒ¥Ğ¢VæEöæ÷F–f–6F–öåöÆör‡7FFRÂ&&—'F†F’"ÂÆ–æU÷W6W%ö–BÂ'6VçB"ÂÖW76vRÂ§6öâæGV×2‡&W7VÇBÂVç7W&Uö66–“ÔfÇ6R’¢6VçB³Ò¢&W7VÇG2æVæB‡²&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–BÂ&&—'F†F’#¢v†òÂ'&VÖ–æEöF—2#¢&VÖ–æEöF—7Ò¢W†6WBW†6WF–öâ2W†3 ¢f–ÇW&RÒ÷&V6÷&E÷66†VGVÆVE÷W6…öf–ÇW&R€¢7FFRÀ¢W6W"À¢FVÆ—fW'•ö¶W’À¢&&—'F†F’"À¢Æ–æU÷W6W%ö–BÀ¢ÖW76vRÀ¢W†2À¢æ÷rÀ¢¢–bf–ÇW&U²'7FGW2%ÒÓÒ&&Æö6¶VB# ¢&Æö6¶VB³Ò¢6¶—VB³Ò¢&W7VÇG2æVæB‡²&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–BÂ&&—'F†F’#¢v†òÂ&W'&÷"#¢7G"†W†2—Ò¢–bf–ÇW&U²&¶–æB%ÒÓÒ'7—7FVÒ# ¢7—7FVÕöW'&÷"ÒG'VP¢'&V°¢–b7—7FVÕöW'&÷# ¢'&V°¢–b7—7FVÕöW'&÷# ¢'&V° ¢6fU÷7FFR†FFöf–ÆRÂ7FFR¢&WGW&â°¢'6VçB#¢6VçBÀ¢'6¶—VB#¢6¶—VBÀ¢&&Æö6¶VB#¢&Æö6¶VBÀ¢'&W7VÇG2#¢&W7VÇG2À¢'7—7FVÕöW'&÷"#¢7—7FVÕöW'&÷"À¢ÒÂ#   ¢2ÓÓÒs“’i›®ˆ;Şhù˜i.ûÈyIşkK¾hù˜i.ûÉ®Xú®‹[Ä”äRzxŠˆ®ûÈÎš	ŠŠŞKˆŞ˜.ZèŠÛ~{êNûÈ“ÓÓĞ¥4Ô%Eõ$TÔ”äDU%ô4DTtõ$”U2Ò°¢&ÖVÖò#¢²&VÖö¦’#¢/	ù9Ò"Â&Æ&VÂ#¢.KˆˆŠÎX)[ù‚'ÒÀ¢&&—'F†F’#¢²&VÖö¦’#¢/	øè""Â&Æ&VÂ#¢.yIşizR'ÒÀ¢'vVFF–ær#¢²&VÖö¦’#¢/	ù(Ò"Â&Æ&VÂ#¢.{YZ™®{H[û^izR'ÒÀ¢&FF–ær#¢²&VÖö¦’#¢/	ù)R"Â&Æ&VÂ#¢.KªN[è{H[û^izR'ÒÀ¢&6†–ÆEö&—'F†F’#¢²&VÖö¦’#¢/	ùb"Â&Æ&VÂ#¢.[şZÚyIşizR'ÒÀ¢&VÆFW%ö&—'F†F’#¢²&VÖö¦’#¢/	ùB"Â&Æ&VÂ#¢.™[~‹ÊyIşizR'ÒÀ¢&w&GVF–öâ#¢²&VÖö¦’#¢/	øé2"Â&Æ&VÂ#¢.yZ.jZÒ'ÒÀ¢&Ö÷f–ær#¢²&VÖö¦’#¢/	øú"Â&Æ&VÂ#¢.i
ÎZëb'ÒÀ¢'7V6–Â#¢²&VÖö¦’#¢/	øè’"Â&Æ&VÂ#¢.x›jè®{H[û^izR'ÒÀ¢&6†V6·W#¢²&VÖö¦’#¢/	ù(¢"Â&Æ&VÂ#¢.Y¹îŠ‹¢'ÒÀ¢&ÖVF–6–æR#¢²&VÖö¦’#¢/	ù(¢"Â&Æ&VÂ#¢.Y>‰zR'ÒÀ¢'66†VGVÆR#¢²&VÖö¦’#¢/	ù8R"Â&Æ&VÂ#¢.ŠÎzˆ²'ÒÀ¢&w&VWF–ær#¢²&VÖö¦’#¢.)ÚNûˆò"Â&Æ&VÂ#¢.YXşX	’'ÒÀ¢&7W7FöÒ#¢²&VÖö¦’#¢/	ùy>ûˆò"Â&Æ&VÂ#¢.ˆz®Šˆ"'ÒÀ§Ğ  ¦FVbÆåö†5÷6Ö'E÷&VÖ–æFW'2‡&öf–ÆRÂæ÷sÔæöæR“ ¢&öf–ÆRÒ&öf–ÆR÷"·Ğ¢ÆâÒVffV7F—fUöVçF—FÆVÖVçE÷Æâ‡&öf–ÆRÂæ÷sÖæ÷r¢&WGW&âÆâ–â²'–Eós“’"Â'–Eós“•÷–V"'ÒæBÖVÖ&W'6†—ö66W75ö7F—fR€¢&öf–ÆRÂæ÷sÖæ÷p¢  ¦FVbÆåö†5ö6ÆVæF%öæ÷FW2‡&öf–ÆRÂæ÷sÔæöæR“ ¢&öf–ÆRÒ&öf–ÆR÷"·Ğ¢ÆâÒVffV7F—fUöVçF—FÆVÖVçE÷Æâ‡&öf–ÆRÂæ÷sÖæ÷r¢&WGW&âÆâ–â°¢'–Eó3“’"À¢'–Eó3“•÷–V""À¢'–Eós“’"À¢'–Eós“•÷–V""À¢ÒæBÖVÖ&W'6†—ö66W75ö7F—fR‡&öf–ÆRÂæ÷sÖæ÷r  ¦FVbæ÷&ÖÆ—¦U÷6Ö'E÷&VÖ–æFW"‡&rÂ–æFWƒÓ“ ¢&rÒ&r–b—6–ç7Fæ6R‡&rÂF–7B’VÇ6R·Ğ¢6FVv÷'’Ò7G"‡&rævWB‚&6FVv÷'’"’÷"&ÖVÖò"’ç7G&—‚’æÆ÷vW"‚¢–b6FVv÷'’æ÷B–â4Ô%Eõ$TÔ”äDU%ô4DTtõ$”U3 ¢6FVv÷'’Ò&7W7FöÒ ¢ÖWFÒ4Ô%Eõ$TÔ”äDU%ô4DTtõ$”U5¶6FVv÷'•Ğ¢VÖö¦’Ò7G"‡&rævWB‚&VÖö¦’"’÷"ÖWF²&VÖö¦’%Ò’ç7G&—‚’÷"ÖWF²&VÖö¦’%Ğ¢G'“ ¢ÖöçF‚Ò–çB‡&rævWB‚&ÖöçF‚"’÷"¢F’Ò–çB‡&rævWB‚&F’"’÷"¢W†6WB…G—TW'&÷"ÂfÇVTW'&÷"“ ¢ÖöçF‚ÂF’ÒÂ ¢–V%÷&rÒ&rævWB‚'–V""¢G'“ ¢–V"Ò–çB‡–V%÷&r’–b–V%÷&ræ÷B–â„æöæRÂ""ÂÂ#"’VÇ6RæöæP¢W†6WB…G—TW'&÷"ÂfÇVTW'&÷"“ ¢–V"ÒæöæP¢2FFUö—6şûÈ…•••’ÔÔÒÔDNûÈXJ®XXikÎh¸n™h¾y¨N[›NiÈizP¢FFUö—6òÒ7G"‡&rævWB‚&FFR"’÷"&rævWB‚&FFUö—6ò"’÷"""’ç7G&—‚¢–bFFUö—6òæB&RæÖF6‚‡"%åÆG³GÒÕÆG³'ÒÕÆG³'ÒB"ÂFFUö—6ò“ ¢G'“ ¢’ÂÒÂBÒFFUö—6òç7Æ—B‚"Ò"¢–V"Ò–çB‡’¢ÖöçF‚Ò–çB†Ò¢F’Ò–çB†B¢W†6WB…G—TW'&÷"ÂfÇVTW'&÷"“ ¢70¢–b&ööÂ‡&rævWB‚'–V&Ç’"ÂfÇ6R’’÷"&ööÂ‡&rævWB‚'&WVE÷–V&Ç’"ÂfÇ6R’“ ¢–V"ÒæöæP¢&VÖ–æE÷F–ÖRÒ7G"‡&rævWB‚'&VÖ–æE÷F–ÖR"’÷"&rævWB‚'F–ÖR"’÷"#“£"’ç7G&—‚¢–bæ÷B$TÔ”äDU%õD”ÔUõEDU$âæÖF6‚‡&VÖ–æE÷F–ÖR“ ¢&VÖ–æE÷F–ÖRÒ#“£ ¢7W7FöÕ÷F—FÆRÒ7G"‡&rævWB‚&7W7FöÕ÷F—FÆR"’÷"""’ç7G&—‚•³£ƒĞ¢6FVv÷'•öÆ&VÂÒÖWF²&Æ&VÂ%Ğ¢–b6FVv÷'’ÓÒ&7W7FöÒ"æB7W7FöÕ÷F—FÆS ¢6FVv÷'•öÆ&VÂÒ7W7FöÕ÷F—FÆP¢–b6FVv÷'’ÓÒ&ÖVÖò# ¢6FVv÷'•öÆ&VÂÒ7W7FöÕ÷F—FÆR÷"7G"‡&rævWB‚&æ÷FR"’÷"""’ç7G&—‚•³£ƒÒ÷".KˆˆŠÎX)[ù‚ ¢&–BÒ7G"‡&rævWB‚&–B"’÷"""’ç7G&—‚’÷"b'7%÷·6V7&WG2çFö¶Våö†W‚ƒb—Ò ¢æ÷F–g•÷&—fFRÒG'VR2&öGV7C¢i›®ˆ;Şhù˜i.Xú®‹[zxŠˆ ¢æ÷F–g•öw&÷WÒfÇ6P¢WfU÷&VÖ–æBÒfÇ6P¢FVÆ—fW'•÷F&vWBÒ7G"‡&rævWB‚&FVÆ—fW'•÷F&vWB"’÷"'&—fFR"’ç7G&—‚¢–bæ÷B†FVÆ—fW'•÷F&vWBÓÒ'&—fFR"÷"FVÆ—fW'•÷F&vWBç7F'G7v—F‚‚&wV&F–ã¢"’“ ¢FVÆ—fW'•÷F&vWBÒ7G"‡&rævWB‚&FVÆ—fW'•÷F&vWB"’÷"'&—fFR"’ç7G&—‚¢&WGW&â°¢&–B#¢&–BÀ¢'F&vWEöæÖR#¢7G"‡&rævWB‚'F&vWEöæÖR"’÷"""’ç7G&—‚’÷"b.[Ş‹¶–æFW‚²Ò"À¢&6FVv÷'’#¢6FVv÷'’À¢&6FVv÷'•öÆ&VÂ#¢6FVv÷'•öÆ&VÂÀ¢&7W7FöÕ÷F—FÆR#¢7W7FöÕ÷F—FÆRÀ¢&VÖö¦’#¢VÖö¦’À¢&ÖöçF‚#¢ÖöçF‚–bÃÒÖöçF‚ÃÒ"VÇ6RÀ¢&F’#¢F’–bÃÒF’ÃÒ3VÇ6RÀ¢'–V"#¢–V"À¢'&VÖ–æE÷F–ÖR#¢&VÖ–æE÷F–ÖRÀ¢&æ÷FR#¢7G"‡&rævWB‚&æ÷FR"’÷"""’ç7G&—‚•³£#ÒÀ¢&æ÷F–g•÷&—fFR#¢æ÷F–g•÷&—fFRÀ¢&æ÷F–g•öw&÷W#¢æ÷F–g•öw&÷WÀ¢&FVÆ—fW'•÷F&vWB#¢FVÆ—fW'•÷F&vWBÀ¢&WfU÷&VÖ–æB#¢WfU÷&VÖ–æBÀ¢&Væ&ÆVB#¢&ööÂ‡&rævWB‚&Væ&ÆVB"ÂG'VR’’À¢&7&VFVEöB#¢7G"‡&rævWB‚&7&VFVEöB"’÷"FFWF–ÖRææ÷r‚’æ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"’’À¢'WFFVEöB#¢7G"‡&rævWB‚'WFFVEöB"’÷"""’À¢Ğ  ¦FVb6Ö'E÷&VÖ–æFW%ö–FVçF—G’‡&VÖ–æFW"“ ¢""$f–VÆG2F†BÖ¶RGvò&VÖ–æFW"&÷w2F†R6ÖRW6W"–çFVçBâ"" ¢&VÖ–æFW"Ò&VÖ–æFW"÷"·Ğ¢&WGW&â€¢7G"‡&VÖ–æFW"ævWB‚'F&vWEöæÖR"’÷"""’ç7G&—‚’À¢7G"‡&VÖ–æFW"ævWB‚&6FVv÷'’"’÷"""’ç7G&—‚’À¢7G"‡&VÖ–æFW"ævWB‚&7W7FöÕ÷F—FÆR"’÷"""’ç7G&—‚’À¢–çB‡&VÖ–æFW"ævWB‚&ÖöçF‚"’÷"’À¢–çB‡&VÖ–æFW"ævWB‚&F’"’÷"’À¢–çB‡&VÖ–æFW"ævWB‚'–V""’÷"’À¢7G"‡&VÖ–æFW"ævWB‚'&VÖ–æE÷F–ÖR"’÷"""’ç7G&—‚’À¢7G"‡&VÖ–æFW"ævWB‚&æ÷FR"’÷"""’ç7G&—‚’À¢7G"‡&VÖ–æFW"ævWB‚&FVÆ—fW'•÷F&vWB"’÷"'&—fFR"’ç7G&—‚’À¢  ¦FVbÆ—7E÷6Ö'E÷&VÖ–æFW'2‡&öf–ÆR“ ¢&÷w2Ò&öf–ÆRævWB‚'6Ö'E÷&VÖ–æFW'2"’–b—6–ç7Fæ6R‡&öf–ÆRævWB‚'6Ö'E÷&VÖ–æFW'2"’ÂÆ—7B’VÇ6RµĞ¢Væ—VRÒµĞ¢6VVâÒ6WB‚¢f÷"’Â&÷r–âVçVÖW&FR‡&÷w2“ ¢&VÖ–æFW"Òæ÷&ÖÆ—¦U÷6Ö'E÷&VÖ–æFW"‡&÷rÂ’¢–FVçF—G’Ò6Ö'E÷&VÖ–æFW%ö–FVçF—G’‡&VÖ–æFW"¢–b–FVçF—G’–â6VVã ¢6öçF–çVP¢6VVâæFB†–FVçF—G’¢Væ—VRæVæB‡&VÖ–æFW"¢&WGW&âVæ—VP  ¦FVb6Ö'E÷&VÖ–æFW%öö67W'5ööâ‡&VÖ–æFW"ÂF&vWEöFFR“ ¢G'“ ¢ÖöçF‚Ò–çB‡&VÖ–æFW"ævWB‚&ÖöçF‚"’÷"¢F’Ò–çB‡&VÖ–æFW"ævWB‚&F’"’÷"¢W†6WB…G—TW'&÷"ÂfÇVTW'&÷"“ ¢&WGW&âfÇ6P¢–bæ÷BƒÃÒÖöçF‚ÃÒ"æBÃÒF’ÃÒ3“ ¢&WGW&âfÇ6P¢–V"Ò&VÖ–æFW"ævWB‚'–V""¢–b–V# ¢G'“ ¢&WGW&âF&vWEöFFRç–V"ÓÒ–çB‡–V"’æBF&vWEöFFRæÖöçF‚ÓÒÖöçF‚æBF&vWEöFFRæF’ÓÒF¢W†6WB…G—TW'&÷"ÂfÇVTW'&÷"“ ¢&WGW&âfÇ6P¢2–V&Ç’&V7W'&Væ6S²6¶—–çfÆ–BFFW2Æ–¶R"ó3 ¢G'“ ¢FFWF–ÖR‡F&vWEöFFRç–V"ÂÖöçF‚ÂF’¢W†6WBfÇVTW'&÷# ¢&WGW&âfÇ6P¢&WGW&âF&vWEöFFRæÖöçF‚ÓÒÖöçF‚æBF&vWEöFFRæF’ÓÒF  ¦FVb6Ö'E÷&VÖ–æFW%ö6ææVE÷v—6‚‡&VÖ–æFW"“ ¢æÖRÒ&VÖ–æFW"ævWB‚'F&vWEöæÖR"’÷".[Şik’ ¢6BÒ&VÖ–æFW"ævWB‚&6FVv÷'’"’÷"&7W7FöÒ ¢Æ&VÂÒ&VÖ–æFW"ævWB‚&6FVv÷'•öÆ&VÂ"’÷"4Ô%Eõ$TÔ”äDU%ô4DTtõ$”U2ævWB†6BÂ·Ò’ævWB‚&Æ&VÂ"Â.iz^ZÙ"¢FV×ÆFW2Ò°¢&ÖVÖò#¢b/	ù9ÒX)[ùhù˜i.ûÉ§¶Æ&VÇÒ"À¢&&—'F†F’#¢b/	øè"¶æÖWŞûÈÎyIşiz^[ú¾jˆ.ûÈšKÚK¸®ZJŠ*¾kª¾iùNXÈ^YÈŞûÈÎ[›>ZèX^[«~jøşKˆZJ’)ÚNûˆò"À¢'vVFF–ær#¢b/	ù(ÒŠj®hI¾y¨G¶æÖWŞûÈÎ{YZ™®{H[û^iz^[ú¾jˆ.ûÈhIşŠÉŞKˆ‹zşKˆ®y¨N™š®KËNˆˆ~XÈ^Zë’)ÚNûˆò"À¢&FF–ær#¢b/	ù)R¶æÖWŞûÈÎKªN[è{H[û^iz^[ú¾jˆ.ûÈŠÉŞŠÉŞKÚŠé>[›>Xziz^ZÙŠè®[é~x›XŠ^8""À¢&6†–ÆEö&—'F†F’#¢b/	ùbŠj®hI¾y¨N[şZÚyIşiz^[ú¾jˆ.ûÈ™[~ZJ~y¨NjøşKˆjÚ^ûÈÎh‰X	˜;Şx+®KÚ™h¾[ø>8""À¢&VÆFW%ö&—'F†F’#¢b/	ùB¶æÖWŞyIşiz^[ú¾jˆ.ûÈšh*‹ª¾š¹NzÎiÉ~8jøşZJzÉXú>[‹™h¾8""À¢&w&GVF–öâ#¢b/	øé2hŞYiÇ¶æÖWŞyZ.jZŞûÈiky¨Nix^zˆ¾™h¾Zx¾K¨nûÈÎh‰X	x+®KÚš™^X+.8""À¢&Ö÷f–ær#¢b/	øúikZën‰Şh‰ûÈşYjÎ˜~hH[ú¾ûÈš‡¶æÖWŞYÊiky+Z(>KˆXˆ~šnXŠ8""À¢'7V6–Â#¢b/	øè’K¸®ZJiŠşx›XŠ^y¨Niz^ZÙûÈÎzY×¶æÖWŞ™h¾[ø>8[›>Zè8""À¢&6†V6·W#¢b/	ù(¢hù˜i.ûÉ®Š‰[é~™š®ûÈş™yÎ[ø7¶æÖWŞY¹îŠ‹®ûÈÎ[‹nX^KùŞXÚˆˆ~[˜j¾‹8~ii8""À¢&ÖVF–6–æR#¢b/	ù(¢hù˜i.ûÉ®Š›.Y>‰z^ûÈşh»ş‰z^K¨nûÈÎ[š·¶æÖWŞz+®Š¨ŞKˆjÊ8""À¢'66†VGVÆR#¢b/	ù8RŠÎzˆ¾hù˜i.ûÉ®K¸®ZJˆˆw¶æÖWŞiÈ™yÎy¨NZèhé.ûÈÎXŠ^[ùK¨nš	yYi˜.™i>8""À¢&w&VWF–ær#¢b.)ÚNûˆòX+>KˆXú^YXşX	{Zg¶æÖWŞûÉ®8ÎK¸®ZJ˜(NZ[ŞYxîûÉşh‰h;>KÚK¨n8.8Ò"À¢&7W7FöÒ#¢b/	ùy>ûˆòhù˜i.ûÉ®K¸®ZJiŠşKÚx+§¶æÖWŞŠŠŞZé®y¨N8Ç¶Æ&VÇŞ8ŞûÈÎŠ‰[é~‰™^ynKˆKˆ¾8""À¢Ğ¢&WGW&âFV×ÆFW2ævWB†6BÂFV×ÆFW5²&7W7FöÒ%Ò  ¦FVb6Ö'E÷&VÖ–æFW%ö6ææVEöv–gB‡&VÖ–æFW"“ ¢æÖRÒ&VÖ–æFW"ævWB‚'F&vWEöæÖR"’÷".[Şik’ ¢6BÒ&VÖ–æFW"ævWB‚&6FVv÷'’"’÷"&7W7FöÒ ¢–b6B–â²&&—'F†F’"Â&6†–ÆEö&—'F†F’"Â&VÆFW%ö&—'F†F’'Ó ¢&WGW&âb/	øèzjîxš[»®ŠÛûÉ£’h˜¾Zú¾[şXÚûÈ¾YiÎjÚy¨NyIÎ›¹â"’ZúnyJiz^[‹Z[Şxš’2’Kˆ‹[~Y>š	>š:ş8.[Ş‹ûÉ§¶æÖWÒ ¢–b6B–â²'vVFF–ær"Â&FF–ær'Ó ¢&WGW&âb/	øèzjîxš[»®ŠÛûÉ®Kˆ‹[~Y¹îhknxZ~x˜~i»8X[YÎYiÎjÚy¨N[şix^ŠÎûÈÎh‰nKˆš	>Zè™ÙÎi™®šI8.[Ş‹ûÉ§¶æÖWÒ ¢–b6B–â²&6†V6·W"Â&ÖVF–6–æR'Ó ¢&WGW&âb/	øèZúnyJXÙNXªûÉ®™š®Š‹®8i[Nyn‰z^Yjî8k©nX)kNiÚşˆˆ~KªN˜	®Zèhé.8.[Ş‹ûÉ§¶æÖWÒ ¢&WGW&âb/	øè[»®ŠÛûÉ®KˆXú^yÉş[ø>Š›ûÈ¾[şš™®YiÎûÈˆ«ûÈşyIÎ›¹îûÈş™š®KËNi˜.™i>ûÈ8.[Ş‹ûÉ§¶æÖWÒ   ¦FVb'V–ÆE÷6Ö'E÷&VÖ–æFW%öfÆW‚‡&VÖ–æFW"Â¢ÂÖöFSÒ&F’"“ ¢""&ÖöFSÖF—ÆWfRfÆW‚f÷"&—fFRÄ”äRW6‚â"" ¢æÖRÒ&VÖ–æFW"ævWB‚'F&vWEöæÖR"’÷".[Şik’ ¢VÖö¦’Ò&VÖ–æFW"ævWB‚&VÖö¦’"’÷"/	ùy>ûˆò ¢Æ&VÂÒ&VÖ–æFW"ævWB‚&6FVv÷'•öÆ&VÂ"’÷".hù˜i" ¢ÖöçF‚Ò–çB‡&VÖ–æFW"ævWB‚&ÖöçF‚"’÷"¢F’Ò–çB‡&VÖ–æFW"ævWB‚&F’"’÷"¢FFU÷FW‡BÒb'¶ÖöçF‡Ò÷¶F—Ò ¢&–BÒ&VÖ–æFW"ævWB‚&–B"’÷"" ¢–bÖöFRÓÒ&WfR# ¢ÖöFRÒ&F’ ¢–bÖöFRÓÒ&F’# ¢–b‡&VÖ–æFW"ævWB‚&6FVv÷'’"’÷"""’ÓÒ&ÖVÖò# ¢F—FÆRÒ/	ù9ÒX)[ùhù˜i" ¢&öG’Ò€¢b.hù˜i.ûÉ§¶FFU÷FW‡GÒ·&VÖ–æFW"ævWB‚w&VÖ–æE÷F–ÖRr’÷"s“£wÒ ¢b'¶æÖWŞûÈÎŠ¸¾Š‰[é~‰™^ynYiN8" ¢¢–b&VÖ–æFW"ævWB‚&æ÷FR"“ ¢&öG’³Òb%ÆîX)Š‹¾ûÉ§·&VÖ–æFW"ævWB‚væ÷FRr—Ò ¢'WGFöç2Ò°¢²'G—R#¢&'WGFöâ"Â&7F–öâ#¢²'G—R#¢'÷7F&6²"Â&Æ&VÂ#¢/	ù8¾iú^yÈ¾X)[ù‚"Â&FF#¢b'6Ö'C§f–Ws§·&–GÒ"Â&F—7Æ•FW‡B#¢.iú^yÈ¾X)[ù‚'ÒÂ'7G–ÆR#¢'&–Ö'’"Â&6öÆ÷"#¢"3#Sc4T""Â&†V–v‡B#¢'6Ò'ÒÀ¢²'G—R#¢&'WGFöâ"Â&7F–öâ#¢²'G—R#¢'÷7F&6²"Â&Æ&VÂ#¢.Z[Şy¨NûÈÎŠÉŞŠÉŞhù˜i"	ù˜ò"Â&FF#¢b'6Ö'C¦&ÆW76VC§·&–GÒ"Â&F—7Æ•FW‡B#¢.Z[Şy¨NûÈÎŠÉŞŠÉŞhù˜i"	ù˜ò'ÒÂ'7G–ÆR#¢'6V6öæF'’"Â&†V–v‡B#¢'6Ò'ÒÀ¢Ğ¢VÆ–b‡&VÖ–æFW"ævWB‚&6FVv÷'’"’÷"""’ÓÒ&&—'F†F’# ¢F—FÆRÒb/	øè"K¸®ZJiŠ÷¶æÖWŞy¨NyIşizR ¢&öG’Òb.XŠ^[ùK¨n˜Kˆ®KˆXú^zYŞzhò)ÚNûˆõÆîZy>YŞûÉ§¶æÖWÕÆîK¸®ZJûÉ§¶FFU÷FW‡GÒ ¢'WGFöç2Ò°¢²'G—R#¢&'WGFöâ"Â&7F–öâ#¢²'G—R#¢'÷7F&6²"Â&Æ&VÂ#¢/	øèX+>˜zYŞzhò"Â&FF#¢b'6Ö'C§v—6ƒ§·&–GÒ"Â&F—7Æ•FW‡B#¢.X+>˜zYŞzhò'ÒÂ'7G–ÆR#¢'&–Ö'’"Â&6öÆ÷"#¢"4SCC‚"Â&†V–v‡B#¢'6Ò'ÒÀ¢²'G—R#¢&'WGFöâ"Â&7F–öâ#¢²'G—R#¢'÷7F&6²"Â&Æ&VÂ#¢.)È^[{.zYŞzhò"Â&FF#¢b'6Ö'C¦&ÆW76VC§·&–GÒ"Â&F—7Æ•FW‡B#¢.[{.zYŞzhò'ÒÂ'7G–ÆR#¢'6V6öæF'’"Â&†V–v‡B#¢'6Ò'ÒÀ¢Ğ¢VÆ–b‡&VÖ–æFW"ævWB‚&6FVv÷'’"’÷"""’–â²&6†V6·W"Â&ÖVF–6–æR'Ó ¢F—FÆRÒb'¶VÖö¦—Ò¶Æ&VÇÒ ¢&öG’Òb'¶æÖWÕÆîi˜.™i>ûÉ§¶FFU÷FW‡GÒ·&VÖ–æFW"ævWB‚w&VÖ–æE÷F–ÖRr’÷"s“£wÒ ¢–b&VÖ–æFW"ævWB‚&æ÷FR"“ ¢&öG’³Òb%ÆîX)Š‹¾ûÉ§·&VÖ–æFW"ævWB‚væ÷FRr—Ò ¢'WGFöç2Ò°¢²'G—R#¢&'WGFöâ"Â&7F–öâ#¢²'G—R#¢'÷7F&6²"Â&Æ&VÂ#¢/	ù8¾iú^yÈ¾X)[ù‚"Â&FF#¢b'6Ö'C§f–Ws§·&–GÒ"Â&F—7Æ•FW‡B#¢.iú^yÈ¾X)[ù‚'ÒÂ'7G–ÆR#¢'&–Ö'’"Â&6öÆ÷"#¢"3#Sc4T""Â&†V–v‡B#¢'6Ò'ÒÀ¢²'G—R#¢&'WGFöâ"Â&7F–öâ#¢²'G—R#¢'÷7F&6²"Â&Æ&VÂ#¢.)È^h‰yú^˜>K¨b"Â&FF#¢b'6Ö'C¦&ÆW76VC§·&–GÒ"Â&F—7Æ•FW‡B#¢.h‰yú^˜>K¨b'ÒÂ'7G–ÆR#¢'6V6öæF'’"Â&†V–v‡B#¢'6Ò'ÒÀ¢Ğ¢VÆ–b.x‹b"–âæÖR÷"Æ&VÂ–â².x›jè®{H[û^izR'ÒæB.x‹b"–â‡&VÖ–æFW"ævWB‚&æ÷FR"’÷"""“ ¢F—FÆRÒb/	øè’K¸®ZJiŠşx‹nŠj®zø ¢&öG’Òb.KÚŠŠŞZé®y¨Nhù˜i.[Ş‹ûÉ¯	ù‡¶æÖWÕÆîŠ‰[é~Y	K¹nŠª®ˆ.ûÉ®x‹nŠj®zø[ú¾jˆ")ÚNûˆò ¢'WGFöç2Ò°¢²'G—R#¢&'WGFöâ"Â&7F–öâ#¢²'G—R#¢'÷7F&6²"Â&Æ&VÂ#¢/	ù(ÄÄ”ä^zYŞzhò"Â&FF#¢b'6Ö'C§v—6ƒ§·&–GÒ"Â&F—7Æ•FW‡B#¢$Ä”ä^zYŞzhò'ÒÂ'7G–ÆR#¢'&–Ö'’"Â&6öÆ÷"#¢"3#Sc4T""Â&†V–v‡B#¢'6Ò'ÒÀ¢²'G—R#¢&'WGFöâ"Â&7F–öâ#¢²'G—R#¢'÷7F&6²"Â&Æ&VÂ#¢.)È^[{.ZèÎh‰"Â&FF#¢b'6Ö'C¦&ÆW76VC§·&–GÒ"Â&F—7Æ•FW‡B#¢.[{.ZèÎh‰'ÒÂ'7G–ÆR#¢'6V6öæF'’"Â&†V–v‡B#¢'6Ò'ÒÀ¢Ğ¢VÇ6S ¢F—FÆRÒb'¶VÖö¦—ÒK¸®ZJiŠ÷¶æÖWŞy¨G¶Æ&VÇÒ ¢&öG’Òb.XŠ^[ùK¨n™yÎ[ø>KˆKˆ²)ÚNûˆõÆî[Ş‹ûÉ§¶æÖWÕÆîK¸®ZJûÉ§¶FFU÷FW‡GÒ ¢–b&VÖ–æFW"ævWB‚&æ÷FR"“ ¢&öG’³Òb%ÆîX)Š‹¾ûÉ§·&VÖ–æFW"ævWB‚væ÷FRr—Ò ¢'WGFöç2Ò°¢²'G—R#¢&'WGFöâ"Â&7F–öâ#¢²'G—R#¢'÷7F&6²"Â&Æ&VÂ#¢/	ù(ÎX+>˜zYŞzhò"Â&FF#¢b'6Ö'C§v—6ƒ§·&–GÒ"Â&F—7Æ•FW‡B#¢.X+>˜zYŞzhò'ÒÂ'7G–ÆR#¢'&–Ö'’"Â&6öÆ÷"#¢"4SCC‚"Â&†V–v‡B#¢'6Ò'ÒÀ¢²'G—R#¢&'WGFöâ"Â&7F–öâ#¢²'G—R#¢'÷7F&6²"Â&Æ&VÂ#¢.)È^[{.ZèÎh‰"Â&FF#¢b'6Ö'C¦&ÆW76VC§·&–GÒ"Â&F—7Æ•FW‡B#¢.[{.ZèÎh‰'ÒÂ'7G–ÆR#¢'6V6öæF'’"Â&†V–v‡B#¢'6Ò'ÒÀ¢Ğ¢ÇBÒb.X)[ùhù˜i.ûÉ§¶æÖWÒ"–b‡&VÖ–æFW"ævWB‚&6FVv÷'’"’÷"""’ÓÒ&ÖVÖò"VÇ6Rb.K¸®ZJiŠ÷¶æÖWŞy¨G¶Æ&VÇÒ ¢&WGW&â°¢'G—R#¢&fÆW‚"À¢&ÇEFW‡B#¢ÇBÀ¢&6öçFVçG2#¢°¢'G—R#¢&'V&&ÆR"À¢'6—¦R#¢&ÖVv"À¢&&öG’#¢°¢'G—R#¢&&÷‚"À¢&Æ–÷WB#¢'fW'F–6Â"À¢'76–ær#¢&ÖB"À¢&6öçFVçG2#¢°¢²'G—R#¢'FW‡B"Â'FW‡B#¢F—FÆRÂ'vV–v‡B#¢&&öÆB"Â'6—¦R#¢'†Â"Â'w&#¢G'VWÒÀ¢²'G—R#¢'FW‡B"Â'FW‡B#¢&öG’Â'6—¦R#¢&ÖB"Â&6öÆ÷"#¢"3CCCCCB"Â'w&#¢G'VWÒÀ¢²'G—R#¢'FW‡B"Â'FW‡B#¢/	ù*ÂjÚNhù˜i.Xú®X+>X‹KÚy¨BÄ”äRzxŠˆ®ûÈKˆŞiÈ>˜.ZèŠÛ~{êNûÈ’"Â'6—¦R#¢'‡2"Â&6öÆ÷"#¢"3ƒƒƒƒƒ‚"Â'w&#¢G'VWÒÀ¢ÒÀ¢ÒÀ¢&fö÷FW"#¢°¢'G—R#¢&&÷‚"À¢&Æ–÷WB#¢'fW'F–6Â"À¢'76–ær#¢'6Ò"À¢&6öçFVçG2#¢'WGFöç2À¢ÒÀ¢ÒÀ¢Ğ  ¦FVb'V–ÆE÷6Ö'E÷&VÖ–æFW%öF–vW7B‡&VÖ–æFW'2Â¢ÂÖöFSÒ&F’"“ ¢&VÖ–æFW'2ÒÆ—7B‡&VÖ–æFW'2÷"µÒ¢–bÆVâ‡&VÖ–æFW'2’ÓÒ ¢&WGW&â'V–ÆE÷6Ö'E÷&VÖ–æFW%öfÆW‚‡&VÖ–æFW'5³ÒÂÖöFSÖÖöFR¢v†VâÒ.iˆîZJ’"–bÖöFRÓÒ&WfR"VÇ6R.K¸®ZJ’ ¢Æ–æW2Ò°¢b'¶—FVÒævWB‚vVÖö¦’r’÷"	ùy>ûˆòwÒ¶—FVÒævWB‚wF&vWEöæÖRr’÷"~[Ş‹wŞûÉ¢ ¢b'¶—FVÒævWB‚v6FVv÷'•öÆ&VÂr’÷"~hù˜i"wÒ ¢f÷"—FVÒ–â&VÖ–æFW'0¢Ğ¢&WGW&â°¢'G—R#¢&fÆW‚"À¢&ÇEFW‡B#¢b'·v†VçŞiÈ’¶ÆVâ‡&VÖ–æFW'2—ÒX¾hù˜i""À¢&6öçFVçG2#¢°¢'G—R#¢&'V&&ÆR"À¢'6—¦R#¢&ÖVv"À¢&&öG’#¢°¢'G—R#¢&&÷‚"À¢&Æ–÷WB#¢'fW'F–6Â"À¢'76–ær#¢&ÖB"À¢&6öçFVçG2#¢°¢²'G—R#¢'FW‡B"Â'FW‡B#¢b/	ùy>ûˆò·v†VçŞiÈ’¶ÆVâ‡&VÖ–æFW'2—ÒX¾hù˜i""Â'vV–v‡B#¢&&öÆB"Â'6—¦R#¢'†Â"Â'w&#¢G'VWÒÀ¢²'G—R#¢'FW‡B"Â'FW‡B#¢%Æâ"æ¦ö–â†Æ–æW2’Â'6—¦R#¢&ÖB"Â'w&#¢G'VWÒÀ¢²'G—R#¢'FW‡B"Â'FW‡B#¢.YÎKˆi˜.jë^[{.YKÛ^h‰KˆX˜~ûÈÎ˜şXXŞ˜xŞŠH~h™>i;â"Â'6—¦R#¢'‡2"Â&6öÆ÷"#¢"3ƒƒƒƒƒ‚"Â'w&#¢G'VWÒÀ¢ÒÀ¢ÒÀ¢ÒÀ¢Ğ  ¦FVb—5ö6†V6¶–å÷÷7F&6²†FF“ ¢""$F–Ç’W6‚òfÆW‚8Îh‰[›>Zè8Ò÷7F&6²â"" ¢FW‡BÒ7G"†FF÷"""’ç7G&—‚¢–bæ÷BFW‡C ¢&WGW&âfÇ6P¢–bFW‡B–â²&7F–öãÖ6†V6¶–â"Â&6†V6¶–â"Â&6†V6¶–ã¦ö²"Â&6†V6¶–ãÓ'Ó ¢&WGW&âG'VP¢–bFW‡Bç7F'G7v—F‚‚&7F–öãÖ6†V6¶–â"“ ¢&WGW&âG'VP¢–bFW‡Bç7F'G7v—F‚‚&6†V6¶–ã¢"“ ¢&WGW&âG'VP¢G'“ ¢g&öÒÆW'G2ç÷7F&6²–×÷'B'6U÷÷7F&6µöFF¢&WGW&â'6U÷÷7F&6µöFF‡FW‡B’ævWB‚&7F–öâ"’ÓÒ&6†V6¶–â ¢W†6WBW†6WF–öã ¢&WGW&â&7F–öãÖ6†V6¶–â"–âFW‡@  ¦FVb†æFÆUö6†V6¶–å÷÷7F&6²†FFöf–ÆRÂÆ–æU÷W6W%ö–BÂ6öæf–sÔæöæR“ ¢""%W'6—7B6†V6²Ö–âg&öÒÄ”äR÷7F&6²(	B6ÖRF‚2Ä”dbö’ö6†V6¶–âà ¢&WGW&ç2FW‡BÂ÷"Æ—7Böb·FW‡BÂ÷F–öæÂW‡—'’fÆW…Òv†VâÖVÖ&W'6†——2æV"W‡—'’à¢"" ¢–bæ÷BÆ–æU÷W6W%ö–C ¢&WGW&â.Š¸¾XXXªXZ^jøşiz^[›>ZèZ[ŞXø¾[èÎXhŞZ[›>Zè8" ¢7FGW2Ò&V6÷&Eö6†V6¶–â†FFöf–ÆRÂ²&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–GÒÂ6öæf–sÖ6öæf–r¢æ÷rÒ7W'&VçEö÷F–ÖR†6öæf–r¢FW‡BÒ'V–ÆEö6†V6¶–å÷7V66W75÷FW‡B‡7FGW2Âæ÷sÖæ÷rÂ6öæf–sÖ6öæf–r¢7FFRÒÆöE÷7FFR†FFöf–ÆR¢&öf–ÆRÒvWE÷&öf–ÆR‡7FFRÂÆ–æU÷W6W%ö–B¢ÖW76vW2ÒÖ–&UöGF6…öW‡—'•÷&VÖ–æB€¢·FW‡EÒÂ&öf–ÆRÂæ÷sÖæ÷rÂ7FFS×7FFRÂFFöf–ÆSÖFFöf–ÆP¢¢–bÆVâ†ÖW76vW2’ÓÒ ¢&WGW&âÖW76vW5³Ğ¢&WGW&âÖW76vW0  ¦FVb—5öW‡—'•ö÷Eö÷WE÷÷7F&6²†FF“ ¢FW‡BÒ7G"†FF÷"""’ç7G&—‚¢&WGW&âFW‡BÓÒ&7F–öãÖW‡—'•ö÷Eö÷WB"÷"&7F–öãÖW‡—'•ö÷Eö÷WB"–âFW‡@  ¦FVb†æFÆU÷6Ö'E÷&VÖ–æFW%÷÷7F&6²†FFöf–ÆRÂÆ–æU÷W6W%ö–BÂFFÂ6öæf–sÔæöæR“ ¢""$†æFÆR6Ö'C¢¢÷7F&6·3²&WGW&ç2&WÇ’FW‡Bâ"" ¢'G2Ò7G"†FF÷"""’ç7Æ—B‚#¢"¢–bÆVâ‡'G2’Â2÷"'G5³ÒÒ'6Ö'B# ¢&WGW&âæöæP¢7F–öâÂ&–BÒ'G5³ÒÂ'G5³%Ğ¢7FFRÒÆöE÷7FFR†FFöf–ÆR¢&öf–ÆRÒvWE÷&öf–ÆR‡7FFRÂÆ–æU÷W6W%ö–B¢&VÖ–æFW"ÒæW‡B‚‡"f÷""–âÆ—7E÷6Ö'E÷&VÖ–æFW'2‡&öf–ÆR’–b"ævWB‚&–B"’ÓÒ&–B’ÂæöæR¢–bæ÷B&VÖ–æFW# ¢&WGW&â.h›îKˆŞX‹˜	zØni›®ˆ;Şhù˜i.ûÈÎXúşˆ;Ş[{.Š*¾XŠ®™šN8" ¢–b7F–öâÓÒ'v—6‚# ¢&WGW&â6Ö'E÷&VÖ–æFW%ö6ææVE÷v—6‚‡&VÖ–æFW"¢–b7F–öâÓÒ&v–gB# ¢&WGW&â6Ö'E÷&VÖ–æFW%ö6ææVEöv–gB‡&VÖ–æFW"¢–b7F–öâÓÒ&6ÆÂ# ¢&WGW&âb/	ù9âxûîYÊ[XúşKº^i*^™»¾Š›{Zn8Ç·&VÖ–æFW"ævWB‚wF&vWEöæÖRr—Ş8Ş8.h™>ZèÎ[èÎXúşY¹î8Î[{.ZèÎh‰8Ş8" ¢–b7F–öâÓÒ&&ÆW76VB# ¢&WGW&âb.ZJ®Z[ŞK¨nûÈÎ[{.[š¾KÚŠ‰Kˆ¾8Î[{.zYŞzhşûÈş[{.ZèÎh‰8ŞûÉ§·&VÖ–æFW"ævWB‚wF&vWEöæÖRr—Ş8" ¢–b7F–öâÓÒ'f–Wr# ¢æ÷FRÒ7G"‡&VÖ–æFW"ævWB‚&æ÷FR"’÷"""’ç7G&—‚¢&WGW&âæ÷FR÷"b'·&VÖ–æFW"ævWB‚wF&vWEöæÖRr—ŞûÙÇ·&VÖ–æFW"ævWB‚v6FVv÷'•öÆ&VÂr’÷"~hù˜i"wÒ ¢&WGW&â.[{.iKnX‹8"   ¦FVbvWE÷6Ö'E÷&VÖ–æFW'5÷–ÆöB†FFöf–ÆRÂÆ–æU÷W6W%ö–B“ ¢7FFRÒÆöE÷7FFR†FFöf–ÆR¢&öf–ÆRÒvWE÷&öf–ÆR‡7FFRÂÆ–æU÷W6W%ö–B¢VçF—FÆVBÒÆåö†5÷6Ö'E÷&VÖ–æFW'2‡&öf–ÆR¢&V6÷fW&–ærÒ7G"‡&öf–ÆRævWB‚&66÷VçEöÖ–w&F–öå÷7FGW2"’÷"""’æÆ÷vW"‚’–â°¢'VæF–ær"Â'&V6÷fW&–ær"Â&–å÷&öw&W72 ¢Ğ¢FöF’ÒFFWF–ÖRææ÷r‚’ç7G&gF–ÖR‚"U’ÒVÒÒVB"¢W6vRÒ‡&öf–ÆRævWB‚'6Ö'E÷&VÖ–æFW%öF–Ç•÷W6vR"’÷"·Ò’ævWB‡FöF’’÷"·Ğ¢&÷VæEöwV&F–ç2ÒµĞ¢f÷"6öçF7B–â&öf–ÆRævWB‚&6öçF7G2"’÷"µÓ ¢–bæ÷B6öçF7Eö—5ö&÷VæEöwV&F–â†6öçF7BÂÆ–æU÷W6W%ö–B“ ¢6öçF–çVP¢wV&F–åö–BÒvWEö6öçF7EöÆ–æUö–B†6öçF7B¢–bæ÷BwV&F–åö–C ¢6öçF–çVP¢&÷VæEöwV&F–ç2æVæB‡°¢&Æ–æU÷W6W%ö–B#¢wV&F–åö–BÀ¢&æÖR#¢6öçF7BævWB‚&æÖR"’÷"6öçF7BævWB‚&F—7Æ•öæÖR"’÷".j[ø>ZèŠÛ~K«¢"À¢&—5÷&–Ö'’#¢&ööÂ†6öçF7BævWB‚&—5÷&–Ö'’"’’À¢Ò¢&WGW&â°¢&ö²#¢G'VRÀ¢&VçF—FÆVB#¢VçF—FÆVBÀ¢'7FFR#¢&VçF—FÆVB"–bVçF—FÆVBVÇ6R‚'&V6÷fW&–ær"–b&V6÷fW&–ærVÇ6R'Ww&FU÷&WV—&VB"’À¢'Æâ#¢&öf–ÆRævWB‚'Æâ"’÷"'G&–Â"À¢'Ww&FUö†–çB#¢æöæR–bVçF—FÆVBVÇ6R€¢.[‹>‰™ş‹8~iijÚ>YÊh.[êûÈÎZèÎh‰[èÎiÈ>ˆz®X¹^XùnY¹îiz.iÈi›®hZ~hù˜i" ¢–b&V6÷fW&–ærVÇ6P¢.i›®ˆ;Şhù˜i.x+¢s“’ZèŠÛ~x˜X©şˆ;ŞûÈÎXØ~{I®[èÎXúşŠŠŞZé®yIşiz^ûÈş{H[û^iz^ûÈşY¹îŠ‹®zØyIşkK¾hù˜i.ûÈKˆŞ˜.ZèŠÛ~{êNûÈ8" ¢’À¢'&VÖ–æFW'2#¢Æ—7E÷6Ö'E÷&VÖ–æFW'2‡&öf–ÆR’–bVçF—FÆVBVÇ6RµÒÀ¢&FVfVÇG2#¢&öf–ÆRævWB‚'6Ö'E÷&VÖ–æFW%öFVfVÇG2"’÷"²&æ÷F–g•÷&—fFR#¢G'VRÂ&æ÷F–g•öw&÷W#¢fÇ6WÒÀ¢&&÷VæEöwV&F–ç2#¢&÷VæEöwV&F–ç2–bVçF—FÆVBVÇ6RµÒÀ¢&F–Ç•÷W6vR#¢°¢'&—fFR#¢–çB‡W6vRævWB‚'&—fFR"’÷"’À¢&wV&F–â#¢–çB‡W6vRævWB‚&wV&F–â"’÷"’À¢ÒÀ¢&F–Ç•öÆ–Ö—G2#¢²'F÷FÂ#¢'ÒÀ¢&6FVv÷&–W2#¢°¢²&–B#¢¶W’Â&VÖö¦’#¢ÖWF²&VÖö¦’%ÒÂ&Æ&VÂ#¢ÖWF²&Æ&VÂ%×Ğ¢f÷"¶W’ÂÖWF–â4Ô%Eõ$TÔ”äDU%ô4DTtõ$”U2æ—FV×2‚¢ÒÀ¢Ğ  ¦FVb6fU÷6Ö'E÷&VÖ–æFW"†FFöf–ÆRÂ–ÆöB“ ¢Æ–æU÷W6W%ö–BÒ7G"‡–ÆöBævWB‚&Æ–æU÷W6W%ö–B"’÷"""’ç7G&—‚¢–bæ÷BÆ–æU÷W6W%ö–C ¢&WGW&â²&ö²#¢fÇ6RÂ&W'&÷"#¢&Ö—76–ærÆ–æU÷W6W%ö–B'ÒÂC ¢7FFRÒÆöE÷7FFR†FFöf–ÆR¢&öf–ÆRÒvWE÷&öf–ÆR‡7FFRÂÆ–æU÷W6W%ö–B¢–bæ÷BÆåö†5÷6Ö'E÷&VÖ–æFW'2‡&öf–ÆR“ ¢&WGW&â²&ö²#¢fÇ6RÂ&W'&÷"#¢'6Ö'E÷&VÖ–æFW'5÷&WV—&Uós“’"Â'Ww&FUö†–çB#¢.Š¸¾XØ~{I¢s“’ZèŠÛ~x˜‚'ÒÂC0¢FVÆ—fW'•÷F&vWBÒ7G"‡–ÆöBævWB‚&FVÆ—fW'•÷F&vWB"’÷"'&—fFR"’ç7G&—‚¢–bFVÆ—fW'•÷F&vWBç7F'G7v—F‚‚&w&÷W¢"“ ¢&WGW&â²&ö²#¢fÇ6RÂ&W'&÷"#¢&wV&F–åöw&÷W÷F&vWEöæ÷EöÆÆ÷vVB'ÒÂC ¢–bFVÆ—fW'•÷F&vWBÒ'&—fFR# ¢–bæ÷BFVÆ—fW'•÷F&vWBç7F'G7v—F‚‚&wV&F–ã¢"“ ¢&WGW&â²&ö²#¢fÇ6RÂ&W'&÷"#¢&–çfÆ–EöFVÆ—fW'•÷F&vWB'ÒÂC ¢F&vWEö–BÒFVÆ—fW'•÷F&vWBç7Æ—B‚#¢"Â•³Ğ¢ÆÆ÷vVBÒ°¢vWEö6öçF7EöÆ–æUö–B†6öçF7B¢f÷"6öçF7B–â&öf–ÆRævWB‚&6öçF7G2"’÷"µĞ¢–b6öçF7Eö—5ö&÷VæEöwV&F–â†6öçF7BÂÆ–æU÷W6W%ö–B¢Ğ¢–bF&vWEö–Bæ÷B–âÆÆ÷vVC ¢&WGW&â²&ö²#¢fÇ6RÂ&W'&÷"#¢&wV&F–å÷F&vWEöæ÷Eö&÷VæB'ÒÂC ¢&WVW7FVEö–BÒ7G"‡–ÆöBævWB‚&–B"’÷"""’ç7G&—‚¢&VÖ–æFW"Òæ÷&ÖÆ—¦U÷6Ö'E÷&VÖ–æFW"‡–ÆöBÂ¢&VÖ–æFW%²'WFFVEöB%ÒÒ7W'&VçEö÷F–ÖR‡·Ò’æ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"¢&÷w2ÒÆ—7E÷6Ö'E÷&VÖ–æFW'2‡&öf–ÆR¢&WÆ6VBÒfÇ6P¢f÷"’Â&÷r–âVçVÖW&FR‡&÷w2“ ¢–b&÷rævWB‚&–B"’ÓÒ&VÖ–æFW%²&–B%Ó ¢&VÖ–æFW%²&7&VFVEöB%ÒÒ&÷rævWB‚&7&VFVEöB"’÷"&VÖ–æFW%²&7&VFVEöB%Ğ¢&÷w5¶•ÒÒ&VÖ–æFW ¢&WÆ6VBÒG'VP¢'&V°¢–bæ÷B&WÆ6VBæBæ÷B&WVW7FVEö–C ¢–FVçF—G’Ò6Ö'E÷&VÖ–æFW%ö–FVçF—G’‡&VÖ–æFW"¢f÷"’Â&÷r–âVçVÖW&FR‡&÷w2“ ¢–b6Ö'E÷&VÖ–æFW%ö–FVçF—G’‡&÷r’Ò–FVçF—G“ ¢6öçF–çVP¢&VÖ–æFW%²&–B%ÒÒ&÷u²&–B%Ğ¢&VÖ–æFW%²&7&VFVEöB%ÒÒ&÷rævWB‚&7&VFVEöB"’÷"&VÖ–æFW%²&7&VFVEöB%Ğ¢&÷w5¶•ÒÒ&VÖ–æFW ¢&WÆ6VBÒG'VP¢'&V°¢–bæ÷B&WÆ6VC ¢–bÆVâ‡&÷w2’ãÒC ¢&WGW&â²&ö²#¢fÇ6RÂ&W'&÷"#¢'6Ö'E÷&VÖ–æFW%öÆ–Ö—B'ÒÂC ¢&÷w2æVæB‡&VÖ–æFW"¢&öf–ÆU²'6Ö'E÷&VÖ–æFW'2%ÒÒ&÷w0¢2yJ.Y8k®zÙnûÉ®i›®ˆ;Şhù˜i.k˜Xú®zxŠˆ®ûÈÎ{êN{XNiy~j‰Y»®Zé®™yÎ™h¢&öf–ÆU²'6Ö'E÷&VÖ–æFW%öFVfVÇG2%ÒÒ²&æ÷F–g•÷&—fFR#¢G'VRÂ&æ÷F–g•öw&÷W#¢fÇ6WĞ¢6fU÷7FFR†FFöf–ÆRÂ7FFR¢&WGW&â²&ö²#¢G'VRÂ'&VÖ–æFW"#¢&VÖ–æFW"Â'&VÖ–æFW'2#¢&÷w7ÒÂ#   ¦FVbFVÆWFU÷6Ö'E÷&VÖ–æFW"†FFöf–ÆRÂÆ–æU÷W6W%ö–BÂ&VÖ–æFW%ö–B“ ¢Æ–æU÷W6W%ö–BÒ7G"†Æ–æU÷W6W%ö–B÷"""’ç7G&—‚¢&VÖ–æFW%ö–BÒ7G"‡&VÖ–æFW%ö–B÷"""’ç7G&—‚¢–bæ÷BÆ–æU÷W6W%ö–B÷"æ÷B&VÖ–æFW%ö–C ¢&WGW&â²&ö²#¢fÇ6RÂ&W'&÷"#¢&Ö—76–ær–B'ÒÂC ¢7FFRÒÆöE÷7FFR†FFöf–ÆR¢&öf–ÆRÒvWE÷&öf–ÆR‡7FFRÂÆ–æU÷W6W%ö–B¢–bæ÷BÆåö†5÷6Ö'E÷&VÖ–æFW'2‡&öf–ÆR“ ¢&WGW&â²&ö²#¢fÇ6RÂ&W'&÷"#¢'6Ö'E÷&VÖ–æFW'5÷&WV—&Uós“’'ÒÂC0¢&÷w2Ò·"f÷""–âÆ—7E÷6Ö'E÷&VÖ–æFW'2‡&öf–ÆR’–b"ævWB‚&–B"’Ò&VÖ–æFW%ö–EĞ¢&öf–ÆU²'6Ö'E÷&VÖ–æFW'2%ÒÒ&÷w0¢6fU÷7FFR†FFöf–ÆRÂ7FFR¢&WGW&â²&ö²#¢G'VRÂ'&VÖ–æFW'2#¢&÷w7ÒÂ#   ¦FVb6VæE÷6Ö'E÷&VÖ–æFW'2†6öæf–r“ ¢""%W6‚ÖW&vVBÂ6VB6Ö'B&VÖ–æFW'2Fò6VÆb÷"öæR&÷VæB6÷&RwV&F–ââ"" ¢Fö¶VâÒ6öæf–rævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"’÷"÷2æVçf—&öâævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"Â""¢–bæ÷BFö¶Vã ¢&WGW&â²'6VçB#¢Â'6¶—VB#¢Â&W'&÷"#¢$Ä”äUô4„ääTÅô44U55õDô´Tâ—2æ÷B6WB'ÒÂC  ¢FFöf–ÆRÒ6öæf–u²$DDôd”ÄR%Ğ¢7FFRÒÆöE÷7FFR†FFöf–ÆR¢6VæFW"Ò6öæf–rævWB‚$Ä”äUõU4…õ4TäDU""’÷"Æ–æU÷W6…öÖW76vP¢æ÷rÒ7W'&VçEö÷F–ÖR†6öæf–r¢FöF•öFFRÒæ÷ræFFR‚¢FöÖ÷'&÷rÒFöF•öFFR²F–ÖVFVÇF†F—3Ó¢FöF•ö¶W’ÒFöF•öFFRç7G&gF–ÖR‚"U’ÒVÒÒVB"¢6VçBÒ ¢6¶—VBÒ ¢&W7VÇG2ÒµĞ¢æ÷uö†ÒÒæ÷rç7G&gF–ÖR‚"Tƒ¢TÒ"¢WfU÷v–æF÷rÒæ÷ræ†÷W"ãÒ# ¢7—7FVÕöW'&÷"ÒfÇ6P ¢f÷"W6W"–â7FFRævWB‚'W6W'2"Â·Ò’çfÇVW2‚“ ¢Æ–æU÷W6W%ö–BÒW6W"ævWB‚&Æ–æU÷W6W%ö–B"¢–b€¢æ÷BÆ–æU÷W6W%ö–@¢÷"W6W"ævWB‚&ÖVÖ&W'6†—÷W6VB"¢÷"æ÷BÖVÖ&W'6†—ö66W75ö7F—fR‡W6W"Âæ÷r¢÷"æ÷BÆåö†5÷6Ö'E÷&VÖ–æFW'2‡W6W"¢“ ¢6¶—VB³Ò¢6öçF–çVP¢6VçEö¶W—2Ò6WB‡W6W"ævWB‚'6Ö'E÷&VÖ–æFW%÷6VçEö¶W—2"’÷"µÒ¢F–Ç•öÆÂÒW6W"ç6WFFVfVÇB‚'6Ö'E÷&VÖ–æFW%öF–Ç•÷W6vR"Â·Ò¢W6vRÒF–Ç•öÆÂç6WFFVfVÇB‡FöF•ö¶W’Â²'&—fFR#¢Â&wV&F–â#¢Ò¢2¶VWöæÇ’6ö×7B&öÆÆ–ærv–æF÷rà¢W6W%²'6Ö'E÷&VÖ–æFW%öF–Ç•÷W6vR%ÒÒ°¢¶W“¢fÇVRf÷"¶W’ÂfÇVR–âF–Ç•öÆÂæ—FV×2‚’–b¶W’ãÒ‡FöF•öFFRÒF–ÖVFVÇF†F—3Ór’’æ—6öf÷&ÖB‚¢Ğ¢&÷VæEöwV&F–ç2Ò°¢vWEö6öçF7EöÆ–æUö–B†6öçF7B¢f÷"6öçF7B–âW6W"ævWB‚&6öçF7G2"’÷"µĞ¢–b6öçF7Eö—5ö&÷VæEöwV&F–â†6öçF7BÂÆ–æU÷W6W%ö–B¢Ğ¢GVUöw&÷W2Ò·Ğ¢f÷"&VÖ–æFW"–âÆ—7E÷6Ö'E÷&VÖ–æFW'2‡W6W"“ ¢–bæ÷B&VÖ–æFW"ævWB‚&Væ&ÆVB"ÂG'VR“ ¢6¶—VB³Ò¢6öçF–çVP¢&–BÒ&VÖ–æFW"ævWB‚&–B"¢&VÖ–æEö†ÒÒ7G"‡&VÖ–æFW"ævWB‚'&VÖ–æE÷F–ÖR"’÷"#“£"’ç7G&—‚¢–bæ÷B$TÔ”äDU%õD”ÔUõEDU$âæÖF6‚‡&VÖ–æEö†Ò“ ¢&VÖ–æEö†ÒÒ#“£ ¢F&vWE÷7V2Ò7G"‡&VÖ–æFW"ævWB‚&FVÆ—fW'•÷F&vWB"’÷"'&—fFR"¢–bF&vWE÷7V2ÓÒ'&—fFR# ¢F&vWEö¶–æBÂF&vWEö–BÒ'&—fFR"ÂÆ–æU÷W6W%ö–@¢VÆ–bF&vWE÷7V2ç7F'G7v—F‚‚&wV&F–ã¢"“ ¢F&vWEö¶–æBÂF&vWEö–BÒ&wV&F–â"ÂF&vWE÷7V2ç7Æ—B‚#¢"Â•³Ğ¢–bF&vWEö–Bæ÷B–â&÷VæEöwV&F–ç3 ¢6¶—VB³Ò¢6öçF–çVP¢VÇ6S ¢6¶—VB³Ò¢6öçF–çVP¢–bæ÷uö†ÒãÒ&VÖ–æEö†ÒæB6Ö'E÷&VÖ–æFW%öö67W'5ööâ‡&VÖ–æFW"ÂFöF•öFFR“ ¢¶W’Òb'·FöF•ö¶W—Ó§·&–GÓ¦F’ ¢–b¶W’–â6VçEö¶W—3 ¢6öçF–çVP¢GVUöw&÷W2ç6WFFVfVÇB‚‚&F’"Â&VÖ–æEö†ÒÂF&vWEö¶–æBÂF&vWEö–B’ÂµÒ’æVæB‚†¶W’Â&VÖ–æFW"’¢–bWfU÷v–æF÷ræB&VÖ–æFW"ævWB‚&WfU÷&VÖ–æB"ÂG'VR’æB6Ö'E÷&VÖ–æFW%öö67W'5ööâ‡&VÖ–æFW"ÂFöÖ÷'&÷r“ ¢¶W’Òb'·FöF•ö¶W—Ó§·&–GÓ¦WfR ¢–b¶W’–â6VçEö¶W—3 ¢6öçF–çVP¢GVUöw&÷W2ç6WFFVfVÇB‚‚&WfR"Â##£"ÂF&vWEö¶–æBÂF&vWEö–B’ÂµÒ’æVæB‚†¶W’Â&VÖ–æFW"’ ¢f÷"†ÖöFRÂ6Æ÷BÂF&vWEö¶–æBÂF&vWEö–B’ÂVçG&–W2–â6÷'FVB†GVUöw&÷W2æ—FV×2‚’“ ¢F÷FÅ÷W6VBÒ–çB‡W6vRævWB‚'&—fFR"’÷"’²–çB‡W6vRævWB‚&wV&F–â"’÷"¢–bF÷FÅ÷W6VBãÒ# ¢6¶—VB³ÒÆVâ†VçG&–W2¢6öçF–çVP¢¶W—2Ò¶¶W’f÷"¶W’Â÷&VÖ–æFW"–âVçG&–W5Ğ¢&VÖ–æFW'2Ò·&VÖ–æFW"f÷"ö¶W’Â&VÖ–æFW"–âVçG&–W5Ğ¢FVÆ—fW'•ö¶W’Òb'6Ö'E÷&VÖ–æFW#§·FöF•ö¶W—Ó§¶ÖöFWÓ§·6Æ÷GÓ§·F&vWEö¶–æGÓ§·F&vWEö–GÒ ¢–bæ÷BW6…öGFV×EöÆÆ÷vVB‡W6W"ÂFVÆ—fW'•ö¶W’“ ¢6¶—VB³ÒÆVâ†VçG&–W2¢6öçF–çVP¢ÖW76vRÒ'V–ÆE÷6Ö'E÷&VÖ–æFW%öF–vW7B‡&VÖ–æFW'2ÂÖöFSÖÖöFR¢G'“ ¢&W7VÇBÒ6VæFW"‡Fö¶VâÂF&vWEö–BÂÖW76vR¢ö6ÆV%÷W6…öFVÆ—fW'•öf–ÇW&R‡W6W"ÂFVÆ—fW'•ö¶W’¢6VçEö¶W—2çWFFR†¶W—2¢W6vU·F&vWEö¶–æEÒÒ–çB‡W6vRævWB‡F&vWEö¶–æB’÷"’²¢VæEöæ÷F–f–6F–öåöÆör€¢7FFRÂ'6Ö'E÷&VÖ–æFW""ÂF&vWEö–BÂ'6VçB"À¢ÖW76vRævWB‚&ÇEFW‡B"’Â§6öâæGV×2‡&W7VÇBÂVç7W&Uö66–“ÔfÇ6R’À¢¢&V6÷&EöÆ–æUöÖW76vU÷W6vR€¢7FFRÀ¢6FVv÷'“Ò'6Ö'E÷&VÖ–æFW""À¢÷væW%öÆ–æU÷W6W%ö–CÖÆ–æU÷W6W%ö–BÀ¢&V6—–VçEö6÷VçCÓÀ¢WfVçEö–CÖFVÆ—fW'•ö¶W’À¢6VçEöCÖæ÷rÀ¢¢6VçB³Ò¢&W7VÇG2æVæB‡°¢&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–BÀ¢'F&vWB#¢F&vWEö¶–æBÀ¢'&V6—–VçB#¢F&vWEö–BÀ¢&–G2#¢·"ævWB‚&–B"’f÷""–â&VÖ–æFW'5ÒÀ¢&ÖöFR#¢ÖöFRÀ¢&ÖW&vVEö6÷VçB#¢ÆVâ‡&VÖ–æFW'2’À¢Ò¢W†6WBW†6WF–öâ2W†3 ¢f–ÇW&RÒ÷&V6÷&E÷66†VGVÆVE÷W6…öf–ÇW&R€¢7FFRÂW6W"ÂFVÆ—fW'•ö¶W’Â'6Ö'E÷&VÖ–æFW""ÂF&vWEö–BÀ¢ÖW76vRævWB‚&ÇEFW‡B"’ÂW†2Âæ÷rÀ¢¢6¶—VB³ÒÆVâ†VçG&–W2¢&W7VÇG2æVæB‡²&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–BÂ&–G2#¢·"ævWB‚&–B"’f÷""–â&VÖ–æFW'5ÒÂ&W'&÷"#¢7G"†W†2—Ò¢–bf–ÇW&U²&¶–æB%ÒÓÒ'7—7FVÒ# ¢7—7FVÕöW'&÷"ÒG'VP¢'&V°¢W6W%²'6Ö'E÷&VÖ–æFW%÷6VçEö¶W—2%ÒÒ6÷'FVB‡6VçEö¶W—2•²Ó#¥Ğ¢–b7—7FVÕöW'&÷# ¢'&V° ¢6fU÷7FFR†FFöf–ÆRÂ7FFR¢&WGW&â°¢'6VçB#¢6VçBÀ¢'6¶—VB#¢6¶—VBÀ¢'&W7VÇG2#¢&W7VÇG2À¢'7—7FVÕöW'&÷"#¢7—7FVÕöW'&÷"À¢ÒÂ#   ¦FVb6ÆVçWöW‡—&VE÷6÷2†6öæf–r“ ¢7FFRÒÆöE÷7FFR†6öæf–u²$DDôd”ÄR%Ò¢&VÖ÷fVBÒ6÷5öfÆ÷rç6÷5÷W&vUööÆB‡7FFRÂ¶VWöÖ–çWFW3Óc’–b6÷5öfÆ÷rVÇ6RµĞ¢6fU÷7FFR†6öæf–u²$DDôd”ÄR%ÒÂ7FFR¢&WGW&â²'&VÖ÷fVB#¢ÆVâ‡&VÖ÷fVB—ÒÂ#   ¦FVb6VæE÷&öf–ÆUö6ö×ÆWF–öå÷&VÖ–æFW'2†6öæf–r“ ¢""%&—fFRÂ&WG'–&ÆR&VÖ–æFW'2B&–æBÂ³#F‚ÂF’2ÂæBF’röæÇ’â"" ¢Fö¶VâÒ6öæf–rævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"’÷"÷2æVçf—&öâævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"Â""¢–bæ÷BFö¶Vã ¢&WGW&â²'6VçB#¢Â'6¶—VB#¢Â&W'&÷"#¢$Ä”äUô4„ääTÅô44U55õDô´Tâ—2æ÷B6WB'ÒÂC ¢7FFRÒÆöE÷7FFR†6öæf–u²$DDôd”ÄR%Ò¢6VæFW"Ò6öæf–rævWB‚$Ä”äUõU4…õ4TäDU""’÷"Æ–æU÷W6…öÖW76vP¢æ÷rÒ7W'&VçEö÷F–ÖR†6öæf–r¢6VçBÒ6¶—VBÒ ¢&W7VÇG2ÒµĞ¢f÷"&öf–ÆR–â‡7FFRævWB‚'W6W'2"’÷"·Ò’çfÇVW2‚“ ¢–bæ÷B—6–ç7Fæ6R‡&öf–ÆRÂF–7B’÷"æ÷B&öf–ÆRævWB‚'&öf–ÆUö6ö×ÆWF–öå÷&WV—&VB"“ ¢6öçF–çVP¢–b&öf–ÆRævWB‚&ÖVÖ&W'6†—÷W6VB"’÷"æ÷BÖVÖ&W'6†—ö66W75ö7F—fR‡&öf–ÆRÂæ÷r“ ¢6¶—VB³Ò¢6öçF–çVP¢6ö×ÆWF–öå÷VW"Ò7G"€¢&öf–ÆRævWB‚'&öf–ÆUö6ö×ÆWF–öå÷VW%öÆ–æU÷W6W%ö–B"’÷"" ¢’ç7G&—‚¢6ö×ÆWF–öåö6öçF7G2Ò°¢6öçF7@¢f÷"6öçF7B–â‡&öf–ÆRævWB‚&6öçF7G2"’÷"µÒ¢–b—6–ç7Fæ6R†6öçF7BÂF–7B¢æB&W6öÇfUö6öçF7E÷&öÆR†6öçF7B’ÓÒ&wV&F–â ¢æB€¢æ÷B6ö×ÆWF–öå÷VW ¢÷"vWEö6öçF7EöÆ–æUö–B†6öçF7B’ÓÒ6ö×ÆWF–öå÷VW ¢¢Ğ¢–bç’†6ö×ÆWFUöwV&F–åö6öçF7B†6öçF7B’f÷"6öçF7B–â6ö×ÆWF–öåö6öçF7G2“ ¢&öf–ÆU²'&öf–ÆUö6ö×ÆWF–öå÷&WV—&VB%ÒÒfÇ6P¢&öf–ÆU²'&öf–ÆUö6ö×ÆWF–öåö6ö×ÆWFVEöB%ÒÒæ÷ræ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"¢6¶—VB³Ò¢6öçF–çVP¢G'“ ¢&÷VæEöBÒFFWF–ÖRæg&öÖ—6öf÷&ÖB‡7G"‡&öf–ÆRævWB‚'&öf–ÆUö6ö×ÆWF–öåö&÷VæEöB"’÷"""’¢W†6WBfÇVTW'&÷# ¢6¶—VB³Ò¢6öçF–çVP¢VÆ6VEöF—2ÒÖ‚ƒÂ†æ÷ræFFR‚’Ò&÷VæEöBæFFR‚’’æF—2¢Ç&VG’Ò¶–çB†F’’f÷"F’–â‡&öf–ÆRævWB‚'&öf–ÆUö6ö×ÆWF–öå÷&VÖ–æFW%öF—2"’÷"µÒ—Ğ¢GVRÒ¶F’f÷"F’–â$ôd”ÄUô4ôÕÄUD”ôåõ$TÔ”äDU%ôD•2–bF’ÃÒVÆ6VEöF—2æBF’æ÷B–âÇ&VG•Ğ¢f÷"F’–âGVS ¢ÖW76vRÒ.[{.ZèÎh‰j[ø>ZèŠÛ~{hZé®8.Š¸¾zxŠˆ®8Îjøşiz^[›>Zè8ŞZèÎh‰ˆz®[{y¨Nˆş{Z‹8~iiûÉ´Ä”äR˜	®yú^[{.XúşKÛşyJûÈÎ™»¾Š›ˆş{ZiÈ>YÊ‹8~iiZèÎh‰[èÎYYşyJ8" ¢G'“ ¢&W7VÇBÒ6VæFW"‡Fö¶VâÂ&öf–ÆRævWB‚&Æ–æU÷W6W%ö–B"’ÂÖW76vR¢VæEöæ÷F–f–6F–öåöÆör‡7FFRÂ'&öf–ÆUö6ö×ÆWF–öâ"Â&öf–ÆRævWB‚&Æ–æU÷W6W%ö–B"’Â'6VçB"ÂÖW76vRÂ§6öâæGV×2‡&W7VÇBÂVç7W&Uö66–“ÔfÇ6R’¢Ç&VG’æFB†F’¢6VçB³Ò¢&W7VÇG2æVæB‡²&Æ–æU÷W6W%ö–B#¢&öf–ÆRævWB‚&Æ–æU÷W6W%ö–B"’Â&F’#¢F’Â'7FGW2#¢'6VçB'Ò¢W†6WBW†6WF–öâ2W†3 ¢VæEöæ÷F–f–6F–öåöÆör‡7FFRÂ'&öf–ÆUö6ö×ÆWF–öâ"Â&öf–ÆRævWB‚&Æ–æU÷W6W%ö–B"’Â&f–ÆVB"ÂÖW76vRÂ7G"†W†2•³£CÒ¢&W7VÇG2æVæB‡²&Æ–æU÷W6W%ö–B#¢&öf–ÆRævWB‚&Æ–æU÷W6W%ö–B"’Â&F’#¢F’Â'7FGW2#¢&f–ÆVB'Ò¢&öf–ÆU²'&öf–ÆUö6ö×ÆWF–öå÷&VÖ–æFW%öF—2%ÒÒ6÷'FVB†Ç&VG’¢6fU÷7FFR†6öæf–u²$DDôd”ÄR%ÒÂ7FFR¢&WGW&â²'6VçB#¢6VçBÂ'6¶—VB#¢6¶—VBÂ'&W7VÇG2#¢&W7VÇG7ÒÂ#   ¦FVb÷W6…ö6×–våöf–ÇW&U÷¦‚†W†2“ ¢f–ÇW&RÒ6Æ76–g•÷W6…öW†6WF–öâ†W†2¢–bf–ÇW&Ræ¶–æBÓÒ'W&ÖæVçB# ¢&WGW&â°¢'G&ç6–VçB#¢fÇ6RÀ¢'&V6öå÷¦‚#¢$Ä”äRiKnK»nK«®[{.[˜énZéik[‹>‰™şh‰n[‹>‰™şxJk9^hê^iKnŠˆ®hş8""À¢&7F–öå÷¦‚#¢.Š¸¾z+®Š¨ŞiÈ>Y:K¸Şx+®Zéik[‹>‰™şZ[ŞXø¾ûÈÎKŠn˜xŞikj[ŞZèÎi[BÄ”äRT”N8""À¢Ğ¢–bf–ÇW&Ræ¶–æBÓÒ'7—7FVÒ# ¢&WGW&â°¢'G&ç6–VçB#¢fÇ6RÀ¢'&V6öå÷¦‚#¢$Ä”äRš¾˜>hèjÈ®ZKiXh‰njÈ®™™KˆŞ‹k>8""À¢&7F–öå÷¦‚#¢.Š¸¾yK{;¾{[zêynY:jª.iúR6†ææVÂ66W72Fö¶VâˆˆrÖW76v–ær’jÈ®™™8""À¢Ğ¢–bf–ÇW&Ræ¶–æBÓÒ&ÖW76vR# ¢&WGW&â°¢'G&ç6–VçB#¢fÇ6RÀ¢'&V6öå÷¦‚#¢$Ä”äRh¹.{Y^jÚNiKnK»nK«®h‰nŠˆ®hşXZ~Zë8""À¢&7F–öå÷¦‚#¢.Š¸¾jª.iú^ZèÎi[BÄ”äRT”N8Z[ŞXø¾x¸hX¾ˆˆ~hêi*ŞjŠiÛşXZ~Zë8""À¢Ğ¢–bf–ÇW&Ræ¶–æBÓÒ'&FUöÆ–Ö—FVB# ¢&WGW&â°¢'G&ç6–VçB#¢G'VRÀ¢'&V6öå÷¦‚#¢$Ä”äRy›Î˜š¾xè~iª¾i˜.‹h^˜î™™X‹n8""À¢&7F–öå÷¦‚#¢.{;¾{[iÈ>KÛşyJy»YÎ˜xŞŠšn˜Û^ˆz®X¹^˜xŞŠšnûÈÎŠ¸¾zˆŞ[èÎiú^yÈ¾{YiéÎ8""À¢Ğ¢&WGW&â°¢'G&ç6–VçB#¢G'VRÀ¢'&V6öå÷¦‚#¢$Ä”äRiÈŞX¹iª¾i˜.xJk9^˜
>{y®h‰nY¹îhx˜îi˜.8""À¢&7F–öå÷¦‚#¢.{;¾{[iÈ>KÛşyJy»YÎ˜xŞŠšn˜Û^ˆz®X¹^˜xŞŠšnûÈÎˆº^K¸ŞZKiY~Š¸¾jª.iú^{k.‹zşˆˆrÄ”äRx¸hX¾8""À¢Ğ  ¦FVb÷W6…ö6×–vå÷fW'6–öâ‡7FFRÂ6×–våö–BÂfW'6–öåöçVÖ&W"“ ¢&WGW&âæW‡B€¢€¢&÷p¢f÷"&÷r–â7FFRævWB‚'W6…ö6×–vå÷fW'6–öç2"’÷"µĞ¢–b&÷rævWB‚&6×–våö–B"’ÓÒ6×–våö–@¢æB–çB‡&÷rævWB‚'fW'6–öâ"’÷"’ÓÒ–çB‡fW'6–öåöçVÖ&W"÷"¢’À¢·ÒÀ¢  ¦FVb÷W6…ö6×–våöÖW76vR‡fW'6–öâÂ&öf–ÆR“ ¢–b7G"‡fW'6–öâævWB‚&6öçFVçE÷G—R"’÷"'FW‡B"’ÓÒ'FW‡B# ¢&WGW&â7G"‡fW'6–öâævWB‚'FW‡B"’÷"""¢FV×ÆFUö¶W’Ò7G"‡fW'6–öâævWB‚'FV×ÆFUö¶W’"’÷"""¢–bFV×ÆFUö¶W’ÓÒ&F“u÷–å÷&VÖ–æFW"# ¢&WGW&â'V–ÆEöF“u÷–å÷&VÖ–æFW%öfÆW‚‚¢–bFV×ÆFUö¶W’ÓÒ&&WFöF“%÷&—fFUöæ÷FR# ¢&WGW&â'V–ÆEö&WFöfVVF&6µöfÆW‚‡&öf–ÆR÷"·ÒÂ"¢&—6RfÇVTW'&÷"‚&&÷fVBW6‚FV×ÆFR—2Væf–Æ&ÆR"  ¦FVb÷6VæE÷W6…ö6×–våöÖW76vR†6öæf–rÂF&vWBÂÖW76vRÂ&WG'•ö¶W’“ ¢Fö¶VâÒ7G"†6öæf–rævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"’÷"""’ç7G&—‚¢–bæ÷BFö¶Vã ¢&—6RW&Ö—76–öäW'&÷"‚$Ä”äUô4„ääTÅô44U55õDô´Tâ—2æ÷B6WB"¢–æ¦V7FVBÒ6öæf–rævWB‚%U4…ô4Õ”tåõ4TäDU""¢–b–æ¦V7FVC ¢&WGW&â–æ¦V7FVB‡Fö¶VâÂF&vWBÂÖW76vRÂ&WG'•ö¶W’¢&WGW&âÆ–æU÷W6…öÖW76vR‡Fö¶VâÂF&vWBÂÖW76vRÂ&WG'•ö¶W“×&WG'•ö¶W’  ¦FVb6VæEöGVU÷W6…ö6×–vç2†6öæf–rÂæ÷sÔæöæR“ ¢""$6Æ–ÒæBFVÆ—fW"GVR6×–vç2v—F†÷WB†öÆF–ærFF&6RÆö6²GW&–ærÄ”äR’ôòâ"" ¢–æ¦V7FVEö6Æö6²Ò6öæf–rævWB‚%U4…ô4Õ”tåô4Äô4²" ¢FVb6Æö6µöæ÷r‚“ ¢–b6ÆÆ&ÆR†–æ¦V7FVEö6Æö6²“ ¢&WGW&â–æ¦V7FVEö6Æö6²‚¢–bæ÷r—2æ÷BæöæS ¢&WGW&âæ÷p¢&WGW&â7W'&VçEö÷F–ÖR†6öæf–r ¢v÷&¶W%ö–BÒb'W6‚×·WV–BçWV–CB‚—Ò ¢7VÖÖ'’Ò°¢&6Æ–ÖVB#¢À¢&6ö×ÆWFVB#¢À¢''F–ÆÇ•öf–ÆVB#¢À¢&gVÆÇ•öf–ÆVB#¢À¢&6æ6VÆÆVB#¢À¢'6VçB#¢À¢&f–ÆVB#¢À¢&&Æö6¶VB#¢À¢&&Æö6µ÷&V6öâ#¢""À¢Ğ¢v†–ÆRG'VS ¢÷W&F–öåö6Æö6²Ò6Æö6µöæ÷r‚¢'VFvWE÷7FFRÒÆöE÷7FFR†6öæf–u²$DDôd”ÄR%Ò¢–bæ÷BÆ–æUöæöåöVÖW&vVæ7•÷W6…öÆÆ÷vVB€¢'VFvWE÷7FFRÂ6öæf–rÂ÷W&F–öåö6Æö6°¢“ ¢7VÖÖ'•²&&Æö6¶VB%ÒÒ×WFFU÷7FFUöFöÖ–6ÆÇ’€¢6öæf–u²$DDôd”ÄR%ÒÀ¢ÆÖ&F7FFS¢Ö&µöGVUö6×–vç5ö'VFvWEö&Æö6¶VB€¢7FFRÂ÷W&F–öåö6Æö6°¢’À¢¢7VÖÖ'•²&&Æö6µ÷&V6öâ%ÒÒ&Æ–æUöæöåöVÖW&vVæ7•ö'VFvWEö†&E÷7F÷ ¢'&V°¢6Æ–ÒÒ×WFFU÷7FFUöFöÖ–6ÆÇ’€¢6öæf–u²$DDôd”ÄR%ÒÀ¢ÆÖ&F7FFS¢6Æ–ÕöGVUö6×–vâ€¢7FFRÀ¢÷W&F–öåö6Æö6²À¢v÷&¶W%ö–C×v÷&¶W%ö–BÀ¢VF–Væ6Uö6Æ76–f–W#×W6…öVF–Væ6Uö6öFRÀ¢’À¢¢–b6Æ–Ò—2æöæS ¢'&V°¢7F–öâÒ6Æ–ÒævWB‚&7F–öâ"¢–b7F–öâÓÒ&6æ6VÆÆVB# ¢7VÖÖ'•²&6æ6VÆÆVB%Ò³Ò¢6öçF–çVP¢–b7F–öâÓÒ&V×G•öVF–Væ6R# ¢7VÖÖ'•²&gVÆÇ•öf–ÆVB%Ò³Ò¢6öçF–çVP¢6×–våö–BÒ6Æ–Õ²&6×–våö–B%Ğ¢7VÖÖ'•²&6Æ–ÖVB%Ò³Ò¢6×–våö'VFvWEö&Æö6¶VBÒfÇ6P¢v†–ÆRG'VS ¢÷W&F–öåö6Æö6²Ò6Æö6µöæ÷r‚ ¢FVb6Æ–ÕöFVÆ—fW'•÷v—F…ö'VFvWB‡7FFR“ ¢†5÷VæF–æuöFVÆ—fW'’Òç’€¢&÷rævWB‚'6÷W&6R"’ÓÒ&6×–vâ ¢æB&÷rævWB‚&6×–våö–B"’ÓÒ6×–våö–@¢æB&÷rævWB‚'7FGW2"’–â²'VæF–ær"Â'&WG'’'Ğ¢æB–çB‡&÷rævWB‚&GFV×G2"’÷"’ÂÔ…ôDTÄ•dU%•ôEDTÕE0¢f÷"&÷r–â‡7FFRævWB‚'W6…öFVÆ—fW'•÷&V6÷&G2"’÷"µÒ¢¢–bæ÷B†5÷VæF–æuöFVÆ—fW'“ ¢&WGW&âæöæP¢–bæ÷BÆ–æUöæöåöVÖW&vVæ7•÷W6…öÆÆ÷vVB€¢7FFRÂ6öæf–rÂ÷W&F–öåö6Æö6°¢“ ¢&Æö6¶VEö6÷VçBÒÖ&µöGVUö6×–vç5ö'VFvWEö&Æö6¶VB€¢7FFRÂ÷W&F–öåö6Æö6°¢¢&WGW&â°¢&'VFvWEö&Æö6¶VB#¢G'VRÀ¢&&Æö6¶VEö6÷VçB#¢&Æö6¶VEö6÷VçBÀ¢Ğ¢&WGW&â6Æ–ÕöæW‡EöFVÆ—fW'’€¢7FFRÀ¢6×–våö–BÀ¢v÷&¶W%ö–C×v÷&¶W%ö–BÀ¢æ÷sÖ÷W&F–öåö6Æö6²À¢ ¢FVÆ—fW'’Ò×WFFU÷7FFUöFöÖ–6ÆÇ’€¢6öæf–u²$DDôd”ÄR%ÒÀ¢6Æ–ÕöFVÆ—fW'•÷v—F…ö'VFvWBÀ¢¢–b—6–ç7Fæ6R†FVÆ—fW'’ÂF–7B’æBFVÆ—fW'’ævWB‚&'VFvWEö&Æö6¶VB"“ ¢7VÖÖ'•²&&Æö6¶VB%ÒÒ–çB†FVÆ—fW'’ævWB‚&&Æö6¶VEö6÷VçB"’÷"¢7VÖÖ'•²&&Æö6µ÷&V6öâ%ÒÒ&Æ–æUöæöåöVÖW&vVæ7•ö'VFvWEö†&E÷7F÷ ¢6×–våö'VFvWEö&Æö6¶VBÒG'VP¢'&V°¢–bFVÆ—fW'’—2æöæS ¢'&V°¢7FFRÒÆöE÷7FFR†6öæf–u²$DDôd”ÄR%Ò¢fW'6–öâÒ÷W6…ö6×–vå÷fW'6–öâ€¢7FFRÀ¢6×–våö–BÀ¢FVÆ—fW'’ævWB‚&6×–vå÷fW'6–öâ"’À¢¢&öf–ÆRÒ‡7FFRævWB‚'W6W'2"’÷"·Ò’ævWB†FVÆ—fW'•²&Æ–æU÷W6W%ö–B%Ò’÷"·Ğ¢G'“ ¢ÖW76vRÒ÷W6…ö6×–våöÖW76vR‡fW'6–öâÂ&öf–ÆR¢&W7VÇBÒ÷6VæE÷W6…ö6×–våöÖW76vR€¢6öæf–rÀ¢FVÆ—fW'•²&Æ–æU÷W6W%ö–B%ÒÀ¢ÖW76vRÀ¢FVÆ—fW'•²'&WG'•ö¶W’%ÒÀ¢¢–b—6–ç7Fæ6R‡&W7VÇBÂF–7B’æB&W7VÇBævWB‚&ö²"’—2fÇ6S ¢&—6R'VçF–ÖTW'&÷"‡7G"‡&W7VÇB’¢×WFFU÷7FFUöFöÖ–6ÆÇ’€¢6öæf–u²$DDôd”ÄR%ÒÀ¢ÆÖ&F6fVE÷7FFS¢6WGFÆUöFVÆ—fW'•öGFV×B€¢6fVE÷7FFRÀ¢6×–våö–BÀ¢FVÆ—fW'•²&–B%ÒÀ¢v÷&¶W%ö–C×v÷&¶W%ö–BÀ¢æ÷sÖ6Æö6µöæ÷r‚’À¢7V66W73ÕG'VRÀ¢’À¢¢7VÖÖ'•²'6VçB%Ò³Ò¢W†6WBW†6WF–öâ2W†3 ¢–b—6–ç7Fæ6R†W†2ÂW&Ö—76–öäW'&÷"“ ¢f–ÇW&RÒ°¢'G&ç6–VçB#¢fÇ6RÀ¢'&V6öå÷¦‚#¢.[	®iÊ®ŠŠŞZé¢Ä”äR6†ææVÂ66W72Fö¶VîûÈÎxJk9^y›Î˜8""À¢&7F–öå÷¦‚#¢.Š¸¾yK{;¾{[zêynY:ZèÎh‰&VæFW"y¨BÄ”äUô4„ääTÅô44U55õDô´TâŠŠŞZé®8""À¢Ğ¢VÇ6S ¢f–ÇW&RÒ÷W6…ö6×–våöf–ÇW&U÷¦‚†W†2¢6WGFÆVBÒ×WFFU÷7FFUöFöÖ–6ÆÇ’€¢6öæf–u²$DDôd”ÄR%ÒÀ¢ÆÖ&F6fVE÷7FFS¢6WGFÆUöFVÆ—fW'•öGFV×B€¢6fVE÷7FFRÀ¢6×–våö–BÀ¢FVÆ—fW'•²&–B%ÒÀ¢v÷&¶W%ö–C×v÷&¶W%ö–BÀ¢æ÷sÖ6Æö6µöæ÷r‚’À¢7V66W73ÔfÇ6RÀ¢G&ç6–VçCÖf–ÇW&U²'G&ç6–VçB%ÒÀ¢f–ÇW&U÷&V6öå÷¦ƒÖf–ÇW&U²'&V6öå÷¦‚%ÒÀ¢f–ÇW&Uö7F–öå÷¦ƒÖf–ÇW&U²&7F–öå÷¦‚%ÒÀ¢FV6†æ–6ÅöFWF–Ã×7G"†W†2•³£ÒÀ¢’À¢¢–b6WGFÆVE²'7FGW2%ÒÓÒ&f–ÆVB# ¢7VÖÖ'•²&f–ÆVB%Ò³Ò¢–b6×–våö'VFvWEö&Æö6¶VC ¢'&V°¢f–æ—6†VBÒ×WFFU÷7FFUöFöÖ–6ÆÇ’€¢6öæf–u²$DDôd”ÄR%ÒÀ¢ÆÖ&F7FFS¢f–æÆ—¦Uö6Æ–ÖVEö6×–vâ€¢7FFRÀ¢6×–våö–BÀ¢v÷&¶W%ö–C×v÷&¶W%ö–BÀ¢æ÷sÖ6Æö6µöæ÷r‚’À¢’À¢¢7VÖÖ'•¶f–æ—6†VE²'7FGW2%ÕÒ³Ò¢&WGW&â7VÖÖ'’Â#   ¦FVb'Våö7&öå÷F–6²†6öæf–r“ ¢æ÷rÒ7W'&VçEö÷F–ÖR†6öæf–r¢&W7VÇG2Ò·Ğ¢6Æ÷BÒæ÷rç7G&gF–ÖR‚"Tƒ¢TÒ" ¢&W7VÇG5²'&WF—&VE÷W6…÷V–G2%ÒÒ°¢'7FGW2#¢#À¢'&W7VÇB#¢&VÖ÷fU÷&WF—&VE÷W6…÷V–G2†6öæf–u²$DDôd”ÄR%ÒÂ6öæf–r’À¢Ğ ¢Ö–w&F–öåöFFÂÖ–w&F–öåö6öFRÒÖ–w&FUöW†—7F–æuög&VUöÖVÖ&W'2†6öæf–r¢&W7VÇG5²&ÖVÖ&W'6†—÷G&ç6—F–öåöÖ–w&F–öâ%ÒÒ°¢'7FGW2#¢Ö–w&F–öåö6öFRÀ¢'&W7VÇB#¢Ö–w&F–öåöFFÀ¢Ğ¢2jøşjÊ7&öâ˜;ŞXXŠ9Î˜X‹iÉş˜xÎzˆ¾z)ûÈÎXhŞYû~ŠÎX‹iÉş™˜Ş{I®ûÉ¶6Æ–Òö÷WF&÷‚iÈ>™‹.˜xŞ8 ¢Ö–ÆW7FöæUöFFÂÖ–ÆW7FöæUö6öFRÒ6VæE÷G&–ÅöÖ–ÆW7FöæUöæ÷F–6W2†6öæf–r¢&W7VÇG5²'G&–ÅöÖ–ÆW7FöæUöæ÷F–6W2%ÒÒ°¢'7FGW2#¢Ö–ÆW7FöæUö6öFRÀ¢'&W7VÇB#¢Ö–ÆW7FöæUöFFÀ¢Ğ¢–åöFFÂ–åö6öFRÒ6VæEöF“u÷–å÷&VÖ–æFW'2†6öæf–rÂæ÷sÖæ÷r¢&W7VÇG5²&F“u÷–å÷&VÖ–æFW'2%ÒÒ°¢'7FGW2#¢–åö6öFRÀ¢'&W7VÇB#¢–åöFFÀ¢Ğ¢W‡—'•öFFÂW‡—'•ö6öFRÒÇ•öW‡—&VE÷ÆåöF÷væw&FW2†6öæf–r¢&W7VÇG5²&ÖVÖ&W'6†—öW‡—'’%ÒÒ°¢'7FGW2#¢W‡—'•ö6öFRÀ¢'&W7VÇB#¢W‡—'•öFFÀ¢Ğ ¢Çv—2Ò°¢'W6…ö6×–vç2#¢6VæEöGVU÷W6…ö6×–vç2À¢&6†V6¶–å÷&VÖ–æFW'2#¢6VæEö6†V6¶–å÷&VÖ–æFW'2À¢'7G&VµöÖ–ÆW7FöæU÷f–FV÷2#¢6VæEöGVU÷7G&VµöÖ–ÆW7FöæU÷f–FV÷2À¢&&–æF–æuöæ÷F–f–6F–öå÷&WG&–W2#¢&WG'•÷VæF–æuö&–æEöæ÷F–f–6F–öç2À¢'&öf–ÆUö6ö×ÆWF–öå÷&VÖ–æFW'2#¢6VæE÷&öf–ÆUö6ö×ÆWF–öå÷&VÖ–æFW'2À¢&6öçF7E÷&VÖ–æFW'2#¢6VæEöÖ—76–æuö6öçF7E÷&VÖ–æFW'2À¢&÷fW&GVUöÆW'G2#¢6VæEöGVU÷&VÖ–æFW'2À¢&wV&F–åöw&÷WöF–Ç•÷7VÖÖ&–W2#¢6VæEöwV&F–åöw&÷WöF–Ç•÷7VÖÖ&–W2À¢'6Ö'E÷&VÖ–æFW'2#¢6VæE÷6Ö'E÷&VÖ–æFW'2À¢'6÷5÷&V6—–VçE÷&VÖ–æFW'2#¢ÆÖ&F6fs¢€¢&ö6W75÷6÷5÷&V6—–VçE÷&VÖ–æFW'2†6fu²$DDôd”ÄR%ÒÂ6frÂæ÷sÖæ÷r’À¢#À¢’À¢'6÷5ö6ÆVçW#¢6ÆVçWöW‡—&VE÷6÷2À¢Ğ¢f÷"æÖRÂF6²–âÇv—2æ—FV×2‚“ ¢FFÂ6öFRÒF6²†6öæf–r¢&W7VÇG5¶æÖUÒÒ²'7FGW2#¢6öFRÂ'&W7VÇB#¢FFĞ¢–b—6–ç7Fæ6R†FFÂF–7B’æBFFævWB‚'7—7FVÕöW'&÷""“ ¢&WGW&â°¢&ö²#¢fÇ6RÀ¢'7—7FVÕöW'&÷"#¢G'VRÀ¢'&åöB#¢æ÷ræ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"’À¢'F–ÖW¦öæR#¢$6–õF—V’"À¢'F6·2#¢&W7VÇG2À¢ÒÂ#  ¢Fö¶VâÒ6öæf–rævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"Â""¢&W7VÇG5²&wV&F–åöw&÷W÷&Vg&W6‚%ÒÒ&Vg&W6…öÆÅöwV&F–åöw&÷W5ö6÷VçB€¢6öæf–u²$DDôd”ÄR%ÒÀ¢Fö¶Vã×Fö¶VâÀ¢ ¢F–Ç’Ò°¢#“£#¢‚&&—'F†F•÷&VÖ–æFW'2"Â6VæEö&—'F†F•÷&VÖ–æFW'2’À¢#£#¢‚'&VæWvÅ÷&VÖ–æFW'2"Â6VæE÷&VæWvÅ÷&VÖ–æFW'2’À¢#“£#¢‚&&WFöF–Ç•öfVVF&6²"Â6VæEö&WFöF–Ç•öfVVF&6²’À¢##£3#¢‚&FFö6ÆVçW"Â6ÆVçWöW‡—&VEöFF’À¢Ğ¢–b6Æ÷B–âF–Ç“ ¢æÖRÂF6²ÒF–Ç•·6Æ÷EĞ¢FFÂ6öFRÒF6²†6öæf–r¢&W7VÇG5¶æÖUÒÒ²'7FGW2#¢6öFRÂ'&W7VÇB#¢FFĞ¢–b—6–ç7Fæ6R†FFÂF–7B’æBFFævWB‚'7—7FVÕöW'&÷""“ ¢&WGW&â°¢&ö²#¢fÇ6RÀ¢'7—7FVÕöW'&÷"#¢G'VRÀ¢'&åöB#¢æ÷ræ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"’À¢'F–ÖW¦öæR#¢$6–õF—V’"À¢'F6·2#¢&W7VÇG2À¢ÒÂ#  ¢&WGW&â°¢&ö²#¢ÆÂ€¢—FVÒævWB‚'7FGW2"Â#’ÂS ¢f÷"—FVÒ–â&W7VÇG2çfÇVW2‚¢–b—6–ç7Fæ6R†—FVÒÂF–7B¢’À¢'7—7FVÕöW'&÷"#¢fÇ6RÀ¢'&åöB#¢æ÷ræ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"’À¢'F–ÖW¦öæR#¢$6–õF—V’"À¢'F6·2#¢&W7VÇG2À¢ÒÂ#   ¦FVbö6öæf–r†6öæf–r“ ¢Fö¶VâÒ€¢6öæf–rævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"¢÷"÷2æVçf—&öâævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"¢÷"÷2æVçf—&öâævWB‚$4„ääTÅô44U55õDô´Tâ"¢÷"" ¢’ç7G&—‚¢6V7&WBÒ€¢6öæf–rævWB‚$Ä”äUô4„ääTÅõ4T5$UB"¢÷"÷2æVçf—&öâævWB‚$Ä”äUô4„ääTÅõ4T5$UB"¢÷"÷2æVçf—&öâævWB‚$4„ääTÅõ4T5$UB"¢÷"" ¢’ç7G&—‚¢&WGW&â°¢&Æ–feö–B#¢6öæf–rævWB‚$Ä”deô”B"’÷"÷2æVçf—&öâævWB‚$Ä”deô”B"’÷"DTdTÅEôÄ”deô”BÀ¢&ÆVv7•öÆ–feö–B#¢€¢6öæf–rævWB‚$ÄTt5•ôÄ”deô”B"¢÷"÷2æVçf—&öâævWB‚$ÄTt5•ôÄ”deô”B"¢÷"DTdTÅEôÄTt5•ôÄ”deô”@¢’À¢'V&Æ–5÷W&Â#¢6öæf–rævWB‚$õT$Ä”5õU$Â"’÷"÷2æVçf—&öâævWB‚$õT$Ä”5õU$Â"Â""’À¢2f—6–&ÆRFWÆ÷’7F×f÷"fW&–g––ær&VæFW"7GVÆÇ’&öÆÆVBF†RvVÆ6öÖRfÆW‚à¢&FWÆ÷•÷fW'6–öâ#¢÷2æVçf—&öâævWB‚$DUÄõ•õdU%4”ôâ"’÷"%s#Ss#Vv‚"À¢2&÷F‚Fö¶VâæB6V7&WB&R&WV—&VBf÷"Ä”äRvV&†öö²òÖW76v–ærà¢&Æ–æUöVæ&ÆVB#¢&ööÂ‡Fö¶VâæB6V7&WB’À¢'&WV—&UöÆ–feöWF‚#¢7G"€¢6öæf–rævWB‚%$UT•$UôÄ”deôUD‚"¢–b6öæf–rævWB‚%$UT•$UôÄ”deôUD‚"’—2æ÷BæöæP¢VÇ6R÷2æVçf—&öâævWB‚%$UT•$UôÄ”deôUD‚"Â#"¢’ç7G&—‚’æÆ÷vW"‚¢–â²#"Â'G'VR"Â'–W2"Â&öâ'ÒÀ¢&V7•÷&VG’#¢&ööÂ†V7’æBV7’æV7•ö6öæf–wW&VB†6öæf–r’’À¢&æWvV'•÷&VG’#¢&ööÂ†æWvV'’æBæWvV'’ææWvV'•ö6öæf–wW&VB†6öæf–r’’À¢'6×5öÆ—fR#¢&ööÂ€¢†6öæf–rævWB‚%4Õ4´”äuõU4U$äÔR"’÷"÷2æVçf—&öâævWB‚%4Õ4´”äuõU4U$äÔR"’÷"""’ç7G&—‚¢æB†6öæf–rævWB‚%4Õ4´”äuõ55tõ$B"’÷"÷2æVçf—&öâævWB‚%4Õ4´”äuõ55tõ$B"’÷"""’ç7G&—‚¢’À¢Ğ  ¦FVbWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöCÔæöæRÂ¢Â&w3ÔæöæRÂ†VFW'3ÔæöæRÂ6öæf–sÔæöæR“ ¢""%&W6öÇfRöæR6ÆÆW"–FVçF—G“²æWfW"G'W7B&÷WFRw2&WVW7FVBÖVÖ&W"”Bâ"" ¢–ÆöBÒ–ÆöB÷"·Ğ¢&w2Ò&w2÷"·Ğ¢†VFW'2Ò†VFW'2÷"·Ğ¢–b&W6öÇfUöÆ–æU÷W6W%ö–B—2æöæS ¢6Æ–ÖVBÒ7G"‡–ÆöBævWB‚&Æ–æU÷W6W%ö–B"’÷"&w2ævWB‚&Æ–æU÷W6W%ö–B"’÷"""’ç7G&—‚¢–bæ÷B6Æ–ÖVC ¢&WGW&âæöæRÂ‡²&ö²#¢fÇ6RÂ&W'&÷"#¢&Ö—76–ærÆ–æU÷W6W%ö–B'ÒÂC¢&WGW&â6Æ–ÖVBÂæöæP¢&WGW&â&W6öÇfUöÆ–æU÷W6W%ö–B€¢†VFW'3Ö†VFW'2À¢–ÆöC×–ÆöBÀ¢&w3Ö&w2À¢6öæf–sÖ6öæf–r÷"·ÒÀ¢  ¦FVbWFFUööæ&ö&F–æu÷&VÖ–æFW"†FFöf–ÆRÂÆ–æU÷W6W%ö–BÂ–ÆöB“ ¢7FFRÒÆöE÷7FFR†FFöf–ÆR¢&öf–ÆRÒvWE÷&öf–ÆR‡7FFRÂÆ–æU÷W6W%ö–B¢Ö…ö6÷VçBÒ–çB‡Æå÷'VÆW2‡&öf–ÆR’ævWB‚&F–Ç•÷&VÖ–æFW'2"’÷"¢–b'&VÖ–æFW%÷F–ÖW2"–â–ÆöC ¢&rÒ–ÆöBævWB‚'&VÖ–æFW%÷F–ÖW2"¢–bæ÷B—6–ç7Fæ6R‡&rÂÆ—7B’÷"æ÷B&s ¢&WGW&â²&ö²#¢fÇ6RÂ&W'&÷"#¢'&VÖ–æFW%÷F–ÖW2×W7B&RæöâÖV×G’Æ—7B'ÒÂC ¢æ÷&ÖÆ—¦VBÒæ÷&ÖÆ—¦U÷&VÖ–æFW%÷F–ÖW2‡&rÂÖ…ö6÷VçB¢–bæ÷Bæ÷&ÖÆ—¦VC ¢&WGW&â²&ö²#¢fÇ6RÂ&W'&÷"#¢&–çfÆ–B&VÖ–æFW%÷F–ÖW2f÷&ÖBÂW6R„ƒ¤ÔÒ'ÒÂC ¢F–ÖW2ÒÇ•÷&VÖ–æFW%÷F–ÖW5÷Fõ÷&öf–ÆR‡&öf–ÆRÂF–ÖW3Öæ÷&ÖÆ—¦VB¢VÇ6S ¢&VÖ–æFW%÷F–ÖRÒ‡–ÆöBævWB‚'&VÖ–æFW%÷F–ÖR"’÷"""’ç7G&—‚¢–bæ÷B$TÔ”äDU%õD”ÔUõEDU$âæÖF6‚‡&VÖ–æFW%÷F–ÖR“ ¢&WGW&â²&ö²#¢fÇ6RÂ&W'&÷"#¢&–çfÆ–B&VÖ–æFW%÷F–ÖRf÷&ÖBÂW6R„ƒ¤ÔÒ'ÒÂC ¢F–ÖW2ÒÇ•÷&VÖ–æFW%÷F–ÖW5÷Fõ÷&öf–ÆR‡&öf–ÆRÂ6–ævÆS×&VÖ–æFW%÷F–ÖR¢–b&F–Ç•ö6†V6¶–å÷&VÖ–æFW%öVæ&ÆVB"–â–ÆöC ¢&öf–ÆU²&F–Ç•ö6†V6¶–å÷&VÖ–æFW%öVæ&ÆVB%ÒÒ&ööÂ€¢–ÆöBævWB‚&F–Ç•ö6†V6¶–å÷&VÖ–æFW%öVæ&ÆVB"¢¢–b&w&6Uö†÷W'2"–â–ÆöC ¢&öf–ÆU²&w&6Uö†÷W'2%ÒÒæ÷&ÖÆ—¦Uöw&6Uö†÷W'2‡–ÆöBævWB‚&w&6Uö†÷W'2"’¢VÇ6S ¢&öf–ÆU²&w&6Uö†÷W'2%ÒÒæ÷&ÖÆ—¦Uöw&6Uö†÷W'2‡&öf–ÆRævWB‚&w&6Uö†÷W'2"’¢–b&÷fW&GVU÷v—EöÖ–çWFW2"–â–ÆöC ¢&öf–ÆU²&÷fW&GVU÷v—EöÖ–çWFW2%ÒÒæ÷&ÖÆ—¦Uö÷fW&GVU÷v—EöÖ–çWFW2€¢–ÆöBævWB‚&÷fW&GVU÷v—EöÖ–çWFW2"¢¢VÇ6S ¢&öf–ÆU²&÷fW&GVU÷v—EöÖ–çWFW2%ÒÒæ÷&ÖÆ—¦Uö÷fW&GVU÷v—EöÖ–çWFW2€¢&öf–ÆRævWB‚&÷fW&GVU÷v—EöÖ–çWFW2"¢¢&öf–ÆU²&öæ&ö&F–æu÷&VÖ–æFW%ö6öæf–wW&VB%ÒÒG'VP¢6fU÷7FFR†FFöf–ÆRÂ7FFR¢&WGW&â°¢&ö²#¢G'VRÀ¢'&VÖ–æFW%÷F–ÖR#¢F–ÖW5³ÒÀ¢'&VÖ–æFW%÷F–ÖW2#¢F–ÖW2À¢&F–Ç•÷&VÖ–æFW'2#¢Ö…ö6÷VçBÀ¢&öæ&ö&F–æu÷&VÖ–æFW%ö6öæf–wW&VB#¢G'VRÀ¢&F–Ç•ö6†V6¶–å÷&VÖ–æFW%öVæ&ÆVB#¢&ööÂ€¢&öf–ÆRævWB‚&F–Ç•ö6†V6¶–å÷&VÖ–æFW%öVæ&ÆVB"ÂG'VR¢’À¢&w&6Uö†÷W'2#¢æ÷&ÖÆ—¦Uöw&6Uö†÷W'2‡&öf–ÆRævWB‚&w&6Uö†÷W'2"’’À¢&÷fW&GVU÷v—EöÖ–çWFW2#¢æ÷&ÖÆ—¦Uö÷fW&GVU÷v—EöÖ–çWFW2€¢&öf–ÆRævWB‚&÷fW&GVU÷v—EöÖ–çWFW2"¢’À¢&ÆÆ÷vVEö÷fW&GVU÷v—EöÖ–çWFW2#¢Æ—7B„ÄÄõtTEôõdU$ETUõt•EôÔ”åUDU2’À¢'v&æ–æuö6æ6VÅöÖ–çWFW2#¢–çB€¢&öf–ÆRævWB‚'v&æ–æuö6æ6VÅöÖ–çWFW2"’÷"DTdTÅEõt$ä”äuô4ä4TÅôÔ”åUDU0¢’À¢&ÆÆ÷vVEöw&6Uö†÷W'2#¢Æ—7B„ÄÄõtTEôu$4Uô„õU%2’À¢ÒÂ#   ¦FVb6ö×ÆWFUööæ&ö&F–æuöf÷%÷W6W"†FFöf–ÆRÂÆ–æU÷W6W%ö–BÂ–ÆöB“ ¢7FFRÒÆöE÷7FFR†FFöf–ÆR¢&öf–ÆRÒ7FFRævWB‚'W6W'2"Â·Ò’ævWB†Æ–æU÷W6W%ö–B¢–bæ÷B&öf–ÆS ¢&WGW&â²&ö²#¢fÇ6RÂ&W'&÷"#¢'W6W"æ÷B&Vv—7FW&VB'ÒÂC@¢66W72ÒÖVÖ&W%ö66W75÷7FFR‡&öf–ÆR¢–b66W75²&wV&F–å÷&WV—&VB%Ó ¢&WGW&â°¢&ö²#¢fÇ6RÀ¢&W'&÷"#¢&wV&F–å÷&WV—&VB"À¢&ÖW76vR#¢.[ø^šXXZèÎh‰ˆ{>[	KØŞXúşhê^iKbÄ”äR˜	®yú^y¨Nj[ø>ZèŠÛ~K«®{hZé¢"À¢¢¦66W72À¢ÒÂC ¢&öf–ÆU²&—5ööæ&ö&F–æuö6ö×ÆWFVB%ÒÒG'VP¢–b'&VÖ–æFW%÷F–ÖW2"–â–ÆöB÷"–ÆöBævWB‚'&VÖ–æFW%÷F–ÖR"“ ¢Ç•÷&VÖ–æFW%÷F–ÖW5÷Fõ÷&öf–ÆR€¢&öf–ÆRÀ¢F–ÖW3×–ÆöBævWB‚'&VÖ–æFW%÷F–ÖW2"’À¢6–ævÆS×–ÆöBævWB‚'&VÖ–æFW%÷F–ÖR"’À¢¢VÇ6S ¢Ç•÷&VÖ–æFW%÷F–ÖW5÷Fõ÷&öf–ÆR‡&öf–ÆR¢—7FFRÒvWEö÷%ö7&VFUö–çFW&7F–öå÷7FFR‡&öf–ÆR¢—7FFU²&öæ&ö&F–æuö6ö×ÆWFVB%ÒÒG'VP¢–b&FEöf—'7EöwV&F–â"æ÷B–â—7FFU²&6ö×ÆWFVE÷7FW2%Ó ¢—7FFU²&6ö×ÆWFVE÷7FW2%ÒæVæB‚&FEöf—'7EöwV&F–â"¢–b'6WE÷&VÖ–æFW%÷F–ÖR"æ÷B–â—7FFU²&6ö×ÆWFVE÷7FW2%Ó ¢—7FFU²&6ö×ÆWFVE÷7FW2%ÒæVæB‚'6WE÷&VÖ–æFW%÷F–ÖR"¢–bæ÷B—7FFRævWB‚'VæF–æu÷7FW2"“ ¢—7FFU²'VæF–æu÷7FW2%ÒÒ°¢&W‡Æ÷&Uö"À¢'&VEö†VÇ"À¢&FEöÖ÷&UöwV&F–ç5ö–e÷–B"À¢Ğ¢—7FFU²&Æ7Eö–çFW&7F–öåöB%ÒÒFFWF–ÖRææ÷r‚’æ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"¢6fU÷7FFR†FFöf–ÆRÂ7FFR¢F–ÖW2Ò&VÖ–æFW%÷F–ÖW5öf÷%÷&öf–ÆR‡&öf–ÆR¢&WGW&â°¢&ö²#¢G'VRÀ¢¢¦ÖVÖ&W%ö66W75÷7FFR‡&öf–ÆR’À¢&—5ööæ&ö&F–æuö6ö×ÆWFVB#¢G'VRÀ¢'6WGWö6ö×ÆWFVB#¢G'VRÀ¢'&VÖ–æFW%÷F–ÖR#¢F–ÖW5³ÒÀ¢'&VÖ–æFW%÷F–ÖW2#¢F–ÖW2À¢&–çFW&7F–öå÷7FFR#¢—7FFRÀ¢ÒÂ#   ¦FVb6†V6¶–åöf÷%÷W6W"†FFöf–ÆRÂÆ–æU÷W6W%ö–BÂ–ÆöBÂ6öæf–sÔæöæR“ ¢–ÆöBÒF–7B‡–ÆöB÷"·Ò¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢æ÷rÒ7W'&VçEö÷F–ÖR†6öæf–r÷"·Ò¢WfVçEö–BÒb&6†V6¶–ã§¶Æ–æU÷W6W%ö–GÓ§·WV–BçWV–CB‚’æ†W‡Ò ¢×WFFU÷7FFUöFöÖ–6ÆÇ’€¢FFöf–ÆRÀ¢ÆÖ&F7W'&VçE÷7FFS¢7W'&VçE÷7FFRç6WFFVfVÇB€¢&ÆVæ6…öWfVçG2"ÂµĞ¢’æVæB‡°¢&–B#¢WfVçEö–BÀ¢&¶–æB#¢&6†V6¶–â"À¢'7V66W72#¢fÇ6RÀ¢&B#¢æ÷ræ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"’À¢Ò’À¢¢7FFRÒÆöE÷7FFR†FFöf–ÆR¢–bÆ–æU÷W6W%ö–Bæ÷B–â7FFRævWB‚'W6W'2"Â·Ò“ ¢&Vv—7FW%öÆ–æU÷W6W"€¢FFöf–ÆRÀ¢°¢&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–BÀ¢&F—7Æ•öæÖR#¢7G"‡–ÆöBævWB‚&F—7Æ•öæÖR"’÷"$Ä”äRKÛşyJˆR"’À¢ÒÀ¢¢7FFRÒÆöE÷7FFR†FFöf–ÆR¢66W72ÒÖVÖ&W%ö66W75÷7FFR‡7FFRævWB‚'W6W'2"Â·Ò’ævWB†Æ–æU÷W6W%ö–B’¢–b66W75²&wV&F–å÷&WV—&VB%Ó ¢&WGW&â°¢&ö²#¢fÇ6RÀ¢&W'&÷"#¢&wV&F–å÷&WV—&VB"À¢&ÖW76vR#¢.[ø^šXXZèÎh‰ˆ{>[	KØŞXúşhê^iKbÄ”äR˜	®yú^y¨Nj[ø>ZèŠÛ~K«®{hZé¢"À¢¢¦66W72À¢ÒÂC ¢7FGW2Ò&V6÷&Eö6†V6¶–â†FFöf–ÆRÂ–ÆöBÂ6öæf–sÖ6öæf–r¢×WFFU÷7FFUöFöÖ–6ÆÇ’€¢FFöf–ÆRÀ¢ÆÖ&F7W'&VçE÷7FFS¢æW‡B€¢€¢&÷rçWFFR‡²'7V66W72#¢G'VWÒ¢f÷"&÷r–â7W'&VçE÷7FFRævWB‚&ÆVæ6…öWfVçG2"’÷"µĞ¢–b&÷rævWB‚&–B"’ÓÒWfVçEö–@¢’À¢æöæRÀ¢’À¢¢7FGW5²&ö²%ÒÒG'VP¢&WGW&â7FGW2Â#   ¦FVb7FGW5öf÷%÷W6W"†FFöf–ÆRÂÆ–æU÷W6W%ö–BÂF—7Æ•öæÖSÒ""“ ¢7FFRÒÆöE÷7FFR†FFöf–ÆR¢&öf–ÆRÒ7FFRævWB‚'W6W'2"Â·Ò’ævWB†Æ–æU÷W6W%ö–B¢–bæ÷B&öf–ÆS ¢FFÂ6öFRÒ&Vv—7FW%öÆ–æU÷W6W"€¢FFöf–ÆRÀ¢°¢&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–BÀ¢&F—7Æ•öæÖR#¢7G"†F—7Æ•öæÖR÷"""’ç7G&—‚’÷"$Ä”äRKÛşyJˆR"À¢ÒÀ¢¢–b6öFRÒ# ¢&WGW&âFFÂ6öFP¢–b—6–ç7Fæ6R†FFÂF–7B“ ¢FF²&WFõ÷&Vv—7FW&VB%ÒÒG'VP¢&WGW&âFFÂ# ¢F—'G’Ò67'V%÷6VÆeöÆ–æUö–G5ööåö6öçF7G2‡&öf–ÆR¢F—'G’ÒFVGWÆ–6FUö6öçF7EöÆ–æUö&–æF–æw2‡&öf–ÆR’÷"F—'G¢F—'G’ÒVç7W&Uööæ&ö&F–æuö6ö×ÆWFVEöfÆr‡&öf–ÆR’÷"F—'G¢FöF’ÒFöF•÷7G&–ær‚¢–b&öf–ÆUö—5÷FöF•ö6†V6¶VB‡&öf–ÆR’æBFöF’æ÷B–â6WB‡&öf–ÆRævWB‚&†—7F÷'’"’÷"µÒ“ ¢†—7BÒ6WB‡&öf–ÆRævWB‚&†—7F÷'’"’÷"µÒ¢†—7BæFB‡FöF’¢&öf–ÆU²&†—7F÷'’%ÒÒ6÷'FVB††—7B¢F—'G’ÒG'VP¢&Vf÷&Uöw&÷W2ÒÆ—7B‡&öf–ÆRævWB‚&wV&F–åöw&÷Wö–G2"’÷"µÒ¢7–æ5ö÷væVEöwV&F–åöw&÷Wö–G2‡7FFRÂ&öf–ÆR¢–bÆ—7B‡&öf–ÆRævWB‚&wV&F–åöw&÷Wö–G2"’÷"µÒ’Ò&Vf÷&Uöw&÷W3 ¢F—'G’ÒG'VP¢–bF—'G“ ¢6fU÷7FFR†FFöf–ÆRÂ7FFR¢&WGW&â'V–ÆE÷7FGW2‡&öf–ÆRÂ7FFR’Â#   ¦FVb7&VFUö†6öæf–sÔæöæR“ ¢–bfÆ6²—2æöæS ¢&WGW&âÖ–æ”†6öæf–r ¢7WÆ–VEö6öæf–rÒ6öæf–r÷"·Ğ¢Æ–feö–BÒ€¢7WÆ–VEö6öæf–rævWB‚$Ä”deô”B"¢÷"÷2æVçf—&öâævWB‚$Ä”deô”B"¢÷"DTdTÅEôÄ”deô”@¢’ç7G&—‚’÷"DTdTÅEôÄ”deô”@¢2Ä”db”BFö¶Vâ—2—77VVBf÷"F†RÄ”äRÆöv–â6†ææVÂVæ6öFVB–âF†P¢2Ä”db”B&Vf—‚â¶VWF†—22F†R6–ævÆR6÷W&6RöbG'WF‚6ò7FÆP¢2&VæFW"Vçf—&öæÖVçBf&–&ÆR6ææ÷BÖ—‚öÆBæBæWr&÷f–FW'2à¢2ÄTt5•ôÄ”äUôÄôt”åô4„ääTÅô”B&VÖ–ç2–æFWVæFVçBf÷"66÷VçBÖ–w&F–öâà¢Æ–æUöÆöv–åö6†ææVÅö–BÒ€¢Æ–feö–Bç7Æ—B‚"Ò"Â•³Ğ¢÷"DTdTÅEôÄ”äUôÄôt”åô4„ääTÅô”@¢ ¢ÒfÆ6²…õöæÖUõòÂ7FF–5öföÆFW#Ò"â"Â7FF–5÷W&Å÷FƒÒ""¢å÷7F'E÷F–ÖRÒFFWF–ÖRææ÷r‚’2##bÓrÓ#F6‚s¢Ké²ö’ö&÷B÷7FGW2ŠˆzérWF–ÖP ¢æW'&÷&†æFÆW"„66÷VçDÖ–w&FVDW'&÷"¢FVbö66÷VçEöÖ–w&FVEöW'&÷"…öW'&÷"“ ¢&WGW&â§6öæ–g’†66÷VçEöÖ–w&FVE÷&W7öç6R‚’’ÂC ¢æ6öæf–rçWFFR€¢DDôd”ÄS×&W6öÇfUöFFöf–ÆR†÷2æVçf—&öâævWB‚$DDôd”ÄR"’’À¢DÔ”åõ55tõ$CÖ÷2æVçf—&öâævWB‚$DÔ”åõ55tõ$B"Â""’À¢DÔ”åôõU$D”ôå5õ55tõ$CÖ÷2æVçf—&öâævWB‚$DÔ”åôõU$D”ôå5õ55tõ$B"Â""’À¢DÔ”åôd”ää4Uõ55tõ$CÖ÷2æVçf—&öâævWB‚$DÔ”åôd”ää4Uõ55tõ$B"Â""’À¢DÔ”åõd”UtU%õ55tõ$CÖ÷2æVçf—&öâævWB‚$DÔ”åõd”UtU%õ55tõ$B"Â""’À¢DÔ”åõ4U54”ôåõ4T5$UCÖ÷2æVçf—&öâævWB‚$DÔ”åõ4U54”ôåõ4T5$UB"Â""’À¢E%U5Eõ$õ…•ô„TDU%3Ö÷2æVçf—&öâævWB‚%E%U5Eõ$õ…•ô„TDU%2"Â""’À¢ÄÄõuôõTåôDÔ”ãÖ÷2æVçf—&öâævWB‚$ÄÄõuôõTåôDÔ”â"Â""’À¢DÔ”åôõTãÖ÷2æVçf—&öâævWB‚$DÔ”åôõTâ"Â""’À¢U$ÔäTåEõ4U54”ôåôÄ”dUD”ÔS×F–ÖVFVÇF††÷W'3Ó‚’À¢4U54”ôåô4ôô´”Uô…EEôäÅ“ÕG'VRÀ¢4U54”ôåô4ôô´”Uõ4T5U$SÕG'VRÀ¢4U54”ôåô4ôô´”Uõ4ÔU4•DSÒ%7G&–7B"À¢Ä”äUô4„ääTÅô44U55õDô´TãÒ€¢÷2æVçf—&öâævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"¢÷"÷2æVçf—&öâævWB‚$4„ääTÅô44U55õDô´Tâ"¢÷"" ¢’À¢Ä”äUô4„ääTÅõ4T5$UCÒ€¢÷2æVçf—&öâævWB‚$Ä”äUô4„ääTÅõ4T5$UB"¢÷"÷2æVçf—&öâævWB‚$4„ääTÅõ4T5$UB"¢÷"" ¢’À¢266WBöFB66–ærg&öÒ&VæFW"T’G—÷2„Ä”äUôÆöv–åô6†ææVÅô”BWF2â¢Ä”äUôÄôt”åô4„ääTÅô”CÖÆ–æUöÆöv–åö6†ææVÅö–BÀ¢Ä”äUôÄôt”åô4„ääTÅõ4T5$UCÒ€¢÷2æVçf—&öâævWB‚$Ä”äUôÄôt”åô4„ääTÅõ4T5$UB"¢÷"÷2æVçf—&öâævWB‚$Ä”äUôÆöv–åô4„ääTÅõ4T5$UB"¢÷"" ¢’À¢ÄTt5•ôÄ”äUôÄôt”åô4„ääTÅô”CÖ÷2æVçf—&öâævWB€¢$ÄTt5•ôÄ”äUôÄôt”åô4„ääTÅô”B"Â##csCƒ2 ¢’À¢ÄTt5•ôÄ”deô”CÖ÷2æVçf—&öâævWB€¢$ÄTt5•ôÄ”deô”B"ÂDTdTÅEôÄTt5•ôÄ”deô”@¢’À¢44õTåEôÔ”u$D”ôåõ4T5$UCÖ÷2æVçf—&öâævWB‚$44õTåEôÔ”u$D”ôåõ4T5$UB"Â""’À¢44õTåEôÔ”u$D”ôåõEDÅõ4T4ôäE3ÓcÀ¢Ä”deô”CÖÆ–feö–BÀ¢õT$Ä”5õU$ÃÖ÷2æVçf—&öâævWB‚$õT$Ä”5õU$Â"Â""’À¢õD”ÔU¤ôäSÖ÷2æVçf—&öâævWB‚$õD”ÔU¤ôäR"Â$6–õF—V’"’À¢tEõ$õU%E•ô”CÖ÷2æVçf—&öâævWB‚$tEõ$õU%E•ô”B"Â""’À¢tEõ4U%d”4Uô44õTåEô¥4ôãÖ÷2æVçf—&öâævWB‚$tEõ4U%d”4Uô44õTåEô¥4ôâ"Â""’À¢tEôÔT5U$TÔTåEô”CÖ÷2æVçf—&öâævWB‚$tEôÔT5U$TÔTåEô”B"Â$rÓtÅCE„Ä„dÒ"’À¢tõ$E$U55õ4•DUõU$ÃÖ÷2æVçf—&öâævWB‚%tõ$E$U55õ4•DUõU$Â"Â""’À¢tõ$E$U55õU4U$äÔSÖ÷2æVçf—&öâævWB‚%tõ$E$U55õU4U$äÔR"Â""’À¢tõ$E$U55ôÄ”4D”ôåõ55tõ$CÖ÷2æVçf—&öâævWB‚%tõ$E$U55ôÄ”4D”ôåõ55tõ$B"Â""’À¢Ä”äUôÔôåD„Å•ôÔU54tUôÄ”Ô•CÖ÷2æVçf—&öâævWB‚$Ä”äUôÔôåD„Å•ôÔU54tUôÄ”Ô•B"Â##"’À¢Ä”äUôÔU54tUõt$ä”äuõU$4TåCÖ÷2æVçf—&öâævWB‚$Ä”äUôÔU54tUõt$ä”äuõU$4TåB"Â#ƒ"’À¢Ä”äUôÔU54tUô„$Eõ5DõõU$4TåCÖ÷2æVçf—&öâævWB‚$Ä”äUôÔU54tUô„$Eõ5DõõU$4TåB"Â#"’À¢5$ôåõ4T5$UCÖ÷2æVçf—&öâævWB‚$5$ôåõ4T5$UB"Â""’À¢$UT•$UôÄ”deôUDƒÖ÷2æVçf—&öâævWB‚%$UT•$UôÄ”deôUD‚"Â#"’À¢äUtT%•ôÔU$4„åEô”CÖ÷2æVçf—&öâævWB‚$äUtT%•ôÔU$4„åEô”B"Â""’À¢äUtT%•ô„4…ô´U“Ö÷2æVçf—&öâævWB‚$äUtT%•ô„4…ô´U’"Â""’À¢äUtT%•ô„4…ô•cÖ÷2æVçf—&öâævWB‚$äUtT%•ô„4…ô•b"Â""’À¢äUtT%•õ5DtSÖ÷2æVçf—&öâævWB‚$äUtT%•õ5DtR"Â'6æF&÷‚"’À¢äUtT%•ôÕuõU$ÃÖ÷2æVçf—&öâævWB‚$äUtT%•ôÕuõU$Â"Â""’À¢T5•ôÔU$4„åEô”CÖ÷2æVçf—&öâævWB‚$T5•ôÔU$4„åEô”B"Â""’À¢T5•ô„4…ô´U“Ö÷2æVçf—&öâævWB‚$T5•ô„4…ô´U’"Â""’À¢T5•ô„4…ô•cÖ÷2æVçf—&öâævWB‚$T5•ô„4…ô•b"Â""’À¢T5•õ5DtSÖ÷2æVçf—&öâævWB‚$T5•õ5DtR"Â'6æF&÷‚"’À¢T5•õU$”ôEõD”ÔU3Ö÷2æVçf—&öâævWB‚$T5•õU$”ôEõD”ÔU2"Â#“’"’À¢4Õ4´”äuõU4U$äÔSÖ÷2æVçf—&öâævWB‚%4Õ4´”äuõU4U$äÔR"Â""’À¢4Õ4´”äuõ55tõ$CÖ÷2æVçf—&öâævWB‚%4Õ4´”äuõ55tõ$B"Â""’À¢4ÕEô„õ5CÖ÷2æVçf—&öâævWB‚%4ÕEô„õ5B"Â""’À¢4ÕEõõ%CÖ÷2æVçf—&öâævWB‚%4ÕEõõ%B"Â#Sƒr"’À¢4ÕEõU4U$äÔSÖ÷2æVçf—&öâævWB‚%4ÕEõU4U$äÔR"Â""’À¢4ÕEõ55tõ$CÖ÷2æVçf—&öâævWB‚%4ÕEõ55tõ$B"Â""’À¢4ÕEõU4UõDÅ3Ö÷2æVçf—&öâævWB‚%4ÕEõU4UõDÅ2"Â'G'VR"’À¢5Uõ%Eôe$ôÕôTÔ”ÃÖ÷2æVçf—&öâævWB‚%5Uõ%Eôe$ôÕôTÔ”Â"Â""’À¢#%ôTäEô”åCÖ÷2æVçf—&öâævWB‚%#%ôTäEô”åB"Â""’À¢#%ô44U55ô´U•ô”CÖ÷2æVçf—&öâævWB‚%#%ô44U55ô´U•ô”B"Â""’À¢#%õ4T5$UEô44U55ô´U“Ö÷2æVçf—&öâævWB‚%#%õ4T5$UEô44U55ô´U’"Â""’À¢#%ô%T4´UCÖ÷2æVçf—&öâævWB‚%#%ô%T4´UB"Â""’À¢#%ô$4µUôTä5%•D”ôåô´U“Ö÷2æVçf—&öâævWB€¢%#%ô$4µUôTä5%•D”ôåô´U’"Â" ¢’À¢DU5EôÄ”äUõU4U%ô”E3Ö÷2æVçf—&öâævWB‚%DU5EôÄ”äUõU4U%ô”E2"Â""’À¢$UD•$TEôÄ”äUõU4U%ô”E3Ö÷2æVçf—&öâævWB€¢%$UD•$TEôÄ”äUõU4U%ô”E2"À¢%UöFWÆ÷•÷6Öö¶Uö‚ÅVs#63ƒ“–cSCFCSSC#&cC6Cs#sB"À¢’À¢ÄTt5•ôD“uõ”åõ$TÔ”äDU%ôTä$ÄTCÕG'VRÀ¢4T5$UE5õ44åõ54TCÖ÷2æVçf—&öâævWB‚%4T5$UE5õ44åõ54TB"Â""’À¢DD$4UôÄT5Eõ$•d”ÄTtUô4ôäd•$ÔTCÖ÷2æVçf—&öâævWB‚$DD$4UôÄT5Eõ$•d”ÄTtUô4ôäd•$ÔTB"Â""’À¢DUTäDTä5•ôTD•Eõ54TCÖ÷2æVçf—&öâævWB‚$DUTäDTä5•ôTD•Eõ54TB"Â""’À¢$4µUõ$U5Dõ$UõDU5DTEôCÖ÷2æVçf—&öâævWB‚$$4µUõ$U5Dõ$UõDU5DTEôB"Â""’À¢4T5U$•E•ôÔôä•Dõ$”äuôTä$ÄTCÖ÷2æVçf—&öâævWB‚%4T5U$•E•ôÔôä•Dõ$”äuôTä$ÄTB"Â""’À¢”ä4”DTåEõ%Tä$ôôµô4ôäd•$ÔTCÖ÷2æVçf—&öâævWB‚$”ä4”DTåEõ%Tä$ôôµô4ôäd•$ÔTB"Â""’À¢¢f÷"6V7W&—G•ö6†V6µöçVÖ&W"–â&ævRƒÂ“ ¢6V7W&—G•÷&Vf—‚Òb%4T5U$•E•ô4„T4µ÷·6V7W&—G•ö6†V6µöçVÖ&W#£&GÒ ¢f÷"6V7W&—G•öf–VÆB–â‚%5DEU2"Â%4õU$4R"Â$4„T4´TEôB"Â$Ud”DTä4R"“ ¢6V7W&—G•ö¶W’Òb'·6V7W&—G•÷&Vf—‡Õ÷·6V7W&—G•öf–VÆGÒ ¢æ6öæf–u·6V7W&—G•ö¶W•ÒÒ÷2æVçf—&öâævWB‡6V7W&—G•ö¶W’Â""¢–b6öæf–s ¢æ6öæf–rçWFFR†6öæf–r¢ç6V7&WEö¶W’Ò€¢æ6öæf–rævWB‚$DÔ”åõ4U54”ôåõ4T5$UB"¢÷"6V7&WG2çFö¶Våö†W‚ƒ3"¢ ¢FVböFÖ–åöwV&B‚¢Âw&—FSÔfÇ6RÂW&Ö—76–öãÔæöæR“ ¢–bæ÷BFÖ–å÷6V7W&—G•÷&VG’†æ6öæf–r“ ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢&FÖ–åöæ÷Eö6öæf–wW&VB'Ò’ÂS0¢–b6W76–öâævWB‚&FÖ–åöWF†VçF–6FVB"’—2æ÷BG'VS ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢'VæWF†÷&—¦VB'Ò’ÂC¢–bw&—FS ¢W‡V7FVBÒ7G"‡6W76–öâævWB‚&FÖ–åö77&b"’÷"""¢&÷f–FVBÒ7G"‡&WVW7Bæ†VFW'2ævWB‚%‚Ô55$bÕFö¶Vâ"’÷"""¢–bæ÷BW‡V7FVB÷"æ÷B6V7&WG2æ6ö×&UöF–vW7B†W‡V7FVBÂ&÷f–FVB“ ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢&77&e÷&WV—&VB'Ò’ÂC0¢–bW&Ö—76–öã ¢&öÆRÒ7G"‡6W76–öâævWB‚&FÖ–å÷&öÆR"’÷"'f–WvW""¢–bW&Ö—76–öâæ÷B–âDÔ”åõ$ôÄUõU$Ô•54”ôå2ævWB‡&öÆRÂ6WB‚’“ ¢VæEöFÖ–åöVF—B€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢'W&Ö—76–öâæFVæ–VB"À¢&f–ÆVB"À¢²'&öÆR#¢&öÆRÂ'&WV—&VE÷W&Ö—76–öâ#¢W&Ö—76–öçÒÀ¢¢&WGW&â§6öæ–g’‡²&W'&÷"#¢&f÷&&–FFVâ"Â'&WV—&VE÷W&Ö—76–öâ#¢W&Ö—76–öçÒ’ÂC0¢&WGW&âæöæP ¢FVb÷7WW%öFÖ–åö×WFF–öåöwV&B‚“ ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VR¢–bFVæ–VC ¢&WGW&âFVæ–V@¢&öÆRÒ7G"‡6W76–öâævWB‚&FÖ–å÷&öÆR"’÷"'f–WvW""¢–b&öÆRÒ'7WW%öFÖ–â# ¢VæEöFÖ–åöVF—B€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢'W6…ö6×–vâçW&Ö—76–öåöFVæ–VB"À¢&f–ÆVB"À¢²'&öÆR#¢&öÆRÂ'&WV—&VE÷&öÆR#¢'7WW%öFÖ–â'ÒÀ¢¢&WGW&â§6öæ–g’‡²&W'&÷"#¢&f÷&&–FFVâ"Â'&WV—&VE÷&öÆR#¢'7WW%öFÖ–â'Ò’ÂC0¢&WGW&âæöæP ¢FVböFÖ–åö×WFF–öå÷&W7öç6R†7F–öâÂFFÂ6öFSÓ#“ ¢VæEöFÖ–åöVF—B€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢7F–öâÀ¢'7V66W72"–b6öFRÂCVÇ6R&f–ÆVB"À¢²&‡GG÷7FGW2#¢6öFWÒÀ¢¢&WGW&â§6öæ–g’†FF’Â6öFP ¢FVböFÖ–åöÆöv–å÷G&ç7÷'E÷6V7W&R‚“ ¢–bæ6öæf–rævWB‚%DU5D”är"’—2G'VS ¢&WGW&âG'VP¢–b&WVW7Bæ—5÷6V7W&S ¢&WGW&âG'VP¢–b7G"‡&WVW7Bç&VÖ÷FUöFG"÷"""’–â²##rããã"Â#££'Ó ¢&WGW&âG'VP¢G'W7FVE÷&÷‡’Ò€¢öVçeöfÆuööâ‚%$TäDU""Âæ6öæf–r¢÷"öVçeöfÆuööâ‚%E%U5Eõ$õ…•ô„TDU%2"Âæ6öæf–r¢¢f÷'v&FVE÷&÷FòÒ7G"€¢&WVW7Bæ†VFW'2ævWB‚%‚Ôf÷'v&FVBÕ&÷Fò"’÷"" ¢’ç7Æ—B‚"Â"Â•³Òç7G&—‚’æÆ÷vW"‚¢&WGW&âG'W7FVE÷&÷‡’æBf÷'v&FVE÷&÷FòÓÒ&‡GG2  ¢ægFW%÷&WVW7@¢FVböÇ•övÆö&Å÷6V7W&—G•ö†VFW'2‡&W7öç6R“ ¢&WGW&âÇ•÷6V7W&—G•ö†VFW'2€¢&W7öç6RÀ¢—5ö‡GG3ÕöFÖ–åöÆöv–å÷G&ç7÷'E÷6V7W&R‚’À¢Fƒ×&WVW7BçF‚À¢ ¢ç÷7B‚"ö’öFÖ–âöÆöv–â"¢FVbFÖ–åöÆöv–åö’‚“ ¢–bæ÷BöFÖ–åöÆöv–å÷G&ç7÷'E÷6V7W&R‚“ ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢&‡GG5÷&WV—&VB'Ò’ÂC ¢–bæ÷BFÖ–å÷6V7W&—G•÷&VG’†æ6öæf–r“ ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢&FÖ–åöæ÷Eö6öæf–wW&VB'Ò’ÂS0¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢6Æ–VçEö¶W’Ò7G"‡&WVW7Bç&VÖ÷FUöFG"÷"'Væ¶æ÷vâ"¢–bFÖ–åöÆöv–å÷&FUöÆ–Ö—FVB†6Æ–VçEö¶W’“ ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢'FöõöÖç•öGFV×G2'Ò’ÂC#¢&öÆRÒFÖ–å÷&öÆUöf÷%÷77v÷&B†æ6öæf–rÂ–ÆöBævWB‚'77v÷&B"’¢–b&öÆR—2æöæS ¢&V6÷&EöFÖ–åöÆöv–åöf–ÇW&R†6Æ–VçEö¶W’¢VæEöFÖ–åöVF—B†æ6öæf–u²$DDôd”ÄR%ÒÂ'6W76–öâæÆöv–â"Â&f–ÆVB"¢&WGW&â§6öæ–g’‡²&W'&÷"#¢&–çfÆ–Eö7&VFVçF–Ç2'Ò’ÂC¢DÔ”åôÄôt”åôEDTÕE2ç÷†6Æ–VçEö¶W’ÂæöæR¢6W76–öâæ6ÆV"‚¢6W76–öâçW&ÖæVçBÒG'VP¢6W76–öå²&FÖ–åöWF†VçF–6FVB%ÒÒG'VP¢6W76–öå²&FÖ–å÷&öÆR%ÒÒ&öÆP¢6W76–öå²&FÖ–åö77&b%ÒÒ6V7&WG2çFö¶Vå÷W&Ç6fRƒ3"¢VæEöFÖ–åöVF—B†æ6öæf–u²$DDôd”ÄR%ÒÂ'6W76–öâæÆöv–â"Â'7V66W72"¢&WGW&â§6öæ–g’‡°¢&ö²#¢G'VRÀ¢&77&e÷Fö¶Vâ#¢6W76–öå²&FÖ–åö77&b%ÒÀ¢'&öÆR#¢&öÆRÀ¢'W&Ö—76–öç2#¢FÖ–å÷W&Ö—76–öç5öf÷%÷&öÆR‡&öÆR’À¢&W‡—&W5ö–â#¢‚¢c¢cÀ¢Ò ¢ævWB‚"ö’öFÖ–â÷6W76–öâ"¢FVbFÖ–å÷6W76–öåö’‚“ ¢–bæ÷BFÖ–å÷6V7W&—G•÷&VG’†æ6öæf–r“ ¢&WGW&â§6öæ–g’‡²&WF†VçF–6FVB#¢fÇ6RÂ&W'&÷"#¢&FÖ–åöæ÷Eö6öæf–wW&VB'Ò’ÂS0¢WF†VçF–6FVBÒ6W76–öâævWB‚&FÖ–åöWF†VçF–6FVB"’—2G'VP¢&WGW&â§6öæ–g’‡°¢&WF†VçF–6FVB#¢WF†VçF–6FVBÀ¢&77&e÷Fö¶Vâ#¢6W76–öâævWB‚&FÖ–åö77&b"’–bWF†VçF–6FVBVÇ6RæöæRÀ¢'&öÆR#¢6W76–öâævWB‚&FÖ–å÷&öÆR"’–bWF†VçF–6FVBVÇ6RæöæRÀ¢'W&Ö—76–öç2#¢FÖ–å÷W&Ö—76–öç5öf÷%÷&öÆR‡6W76–öâævWB‚&FÖ–å÷&öÆR"’’–bWF†VçF–6FVBVÇ6RµÒÀ¢Ò’Âƒ#–bWF†VçF–6FVBVÇ6RC ¢ç÷7B‚"ö’öFÖ–âöÆöv÷WB"¢FVbFÖ–åöÆöv÷WEö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VR¢–bFVæ–VC ¢&WGW&âFVæ–V@¢6W76–öâæ6ÆV"‚¢VæEöFÖ–åöVF—B†æ6öæf–u²$DDôd”ÄR%ÒÂ'6W76–öâæÆöv÷WB"Â'7V66W72"¢&WGW&â§6öæ–g’‡²&ö²#¢G'VWÒ ¢FVböWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöCÔæöæRÂ¢ÂW6Uö&w3ÔfÇ6R“ ¢""%&W6öÇfRÄ”äRW6W"g&öÒfW&–f–VB–E÷Fö¶Vâv†Vâ&WV—&VBâ"" ¢–ÆöBÒ–ÆöB–b–ÆöB—2æ÷BæöæRVÇ6R‡&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ò¢&w2Ò&WVW7Bæ&w2–bW6Uö&w2VÇ6R·Ğ¢&WGW&âWF†VçF–6FVEöÆ–æU÷W6W"€¢–ÆöBÀ¢&w3Ö&w2À¢†VFW'3×¶¶W“¢fÇVRf÷"¶W’ÂfÇVR–â&WVW7Bæ†VFW'2æ—FV×2‚—ÒÀ¢6öæf–sÖæ6öæf–rÀ¢ ¢FVb÷6†÷VÆEö¶VWöÆ–feöVæGö–çE÷7‚“ ¢""$Ä”dbVæGö–çBÕU5BÇv—26W'fRF†R5F†B'Vç2Æ–fbæ–æ—B‚’à ¢æWfW"3"óö–çf—FUög&öÓÖ†÷"g&–VæEö–çf—FR’v’g&öÒö ¢ÒÄ”äR÷Vç2VæGö–çBv—F‚VW'’òÆ–fbç7FFP¢ÒÄ”äRÆöv–â&WGW&ç26öFVö7FFVöâF†R6ÖRVæGö–çBU$À¢&VF—&V7F–ærF†÷6RFòö–çf—FV7G&—2ôWF‚&×2(i"”õ2´æG&ö–BÆöv–âF–W2à¢W‡FW&æÂÖ'&÷w6W"–çf—FVW26†÷VÆBW6RW‡Æ–6—Bö–çf—FV6†÷'BÆ–æ·2–ç7FVBà¢"" ¢&WGW&âG'VP ¢ævWB‚"ò"¢FVb–æFW‚‚“ ¢2Çv—26W'fR5öâÄ”dbVæGö–çBö‡6VR÷6†÷VÆEö¶VWöÆ–feöVæGö–çE÷7’à¢òÒ÷6†÷VÆEö¶VWöÆ–feöVæGö–çE÷7‚¢&WGW&â6VæEög&öÕöF—&V7F÷'’†ç7FF–5öföÆFW"Â&–æFW‚æ‡FÖÂ" ¢ævWB‚"ö–çf—FR"¢FVb–çf—FU÷6†÷'EöÆ–æ²‚“ ¢""$–çf—FRÆæF–ærf÷"W‡FW&æÂ'&÷w6W'2öæÇ’†æ÷BF†RÄ”dbVæGö–çB’â"" ¢&WGW&â6VæEög&öÕöF—&V7F÷'’†ç7FF–5öföÆFW"Â&–çf—FRæ‡FÖÂ" ¢ævWB‚"ö&WFó3“’"¢ævWB‚"ö&WFós“’"¢FVb&WF÷&Vv—7G&F–öåöÆæF–ær‚“ ¢""%V&Æ–2#ÖF’&WF–çG&öGV7F–öã²F†R5D6öçF–çVW2–âfW&–f–VBÄ”dbâ"" ¢&WGW&â6VæEög&öÕöF—&V7F÷'’†ç7FF–5öföÆFW"Â&&WF×&Vv—7FW"æ‡FÖÂ" ¢ævWB‚"÷G&–ÂóB"¢FVbV&Æ–5÷G&–ÅöÆæF–ær‚“ ¢""%V&Æ–2BÖF’G&–Â–çG&öGV7F–öâæBwV–FVB&Vv—7G&F–öââ"" ¢&WGW&â6VæEög&öÕöF—&V7F÷'’†ç7FF–5öföÆFW"Â'G&–ÂÓBæ‡FÖÂ" ¢ævWB‚"öF–Ç’Ö6&Ræ‡FÖÂ"¢FVbF–Ç•ö6&U÷vR‚“ ¢&WGW&â6VæEög&öÕöF—&V7F÷'’†ç7FF–5öföÆFW"Â&F–Ç’Ö6&Ræ‡FÖÂ" ¢ævWB‚"öwV&F–âÖwV–FR"¢FVbwV&F–åöwV–FR‚“ ¢""$FWF–ÆVBwV&F–âæ÷F–6RÆ–æ¶VBg&öÒF†R6öæ6—6R–çf—FRÆæF–ærâ"" ¢&WGW&â6VæEög&öÕöF—&V7F÷'’†ç7FF–5öföÆFW"Â&wV&F–âÖwV–FRæ‡FÖÂ" ¢ævWB‚"ö†VÇF‚"¢FVb†VÇF‚‚“ ¢W'6—7BÒW'6—7FVæ6Uö–æfò†æ6öæf–u²$DDôd”ÄR%Ò¢&WGW&â§6öæ–g’‡²&ö²#¢G'VRÂ'W'6—7FVæ6R#¢W'6—7GÒ ¢ævWB‚"÷&ö&÷G2çG‡B"¢FVb&ö&÷G5÷G‡B‚“ ¢&WGW&â6VæEög&öÕöF—&V7F÷'’†ç7FF–5öföÆFW"Â'&ö&÷G2çG‡B"ÂÖ–ÖWG—SÒ'FW‡B÷Æ–â" ¢ævWB‚"÷6—FVÖç†ÖÂ"¢FVb6—FVÖ÷†ÖÂ‚“ ¢&WGW&â6VæEög&öÕöF—&V7F÷'’†ç7FF–5öföÆFW"Â'6—FVÖç†ÖÂ"ÂÖ–ÖWG—SÒ&Æ–6F–öâ÷†ÖÂ" ¢ævWB‚"öFÖ–â"¢FVbFÖ–â‚“ ¢&W7Ò6VæEög&öÕöF—&V7F÷'’†ç7FF–5öföÆFW"Â&FÖ–âæ‡FÖÂ"¢2fö–B7FÆR66†VBFÖ–âT’†Æöv–â&"ò77v÷&BU‚’gFW"FWÆ÷—0¢&W7æ†VFW'5²$66†RÔ6öçG&öÂ%ÒÒ&æò×7F÷&RÂæòÖ66†RÂ×W7B×&WfÆ–FFRÂÖ‚ÖvSÓ ¢&W7æ†VFW'5²%&vÖ%ÒÒ&æòÖ66†R ¢&WGW&â&W7  ¢ævWB‚"÷FW7Eö&–æB"¢FVbFW7Eö&–æB‚“ ¢&WGW&â6VæEög&öÕöF—&V7F÷'’†ç7FF–5öföÆFW"Â'FW7Eö&–æBæ‡FÖÂ" ¢ævWB‚"÷FW&×2"¢FVbFW&×2‚“ ¢&WGW&â6VæEög&öÕöF—&V7F÷'’†ç7FF–5öföÆFW"Â'FW&×2æ‡FÖÂ" ¢ævWB‚"÷&—f7’"¢FVb&—f7’‚“ ¢&WGW&â6VæEög&öÕöF—&V7F÷'’†ç7FF–5öföÆFW"Â'&—f7’æ‡FÖÂ" ¢ævWB‚"öf"¢FVbf‚“ ¢&WGW&â6VæEög&öÕöF—&V7F÷'’†ç7FF–5öföÆFW"Â&fæ‡FÖÂ" ¢ævWB‚"ö†VÇ"¢FVb†VÇ÷vR‚“ ¢&WGW&â6VæEög&öÕöF—&V7F÷'’†ç7FF–5öföÆFW"Â&†VÇæ‡FÖÂ" ¢ævWB‚"÷&–6–ær"¢FVb&–6–æu÷vR‚“ ¢2y»NX{®ikjšûÈÎ˜şXXÒ&–6–æræ‡FÖÂ(i"Æ–fb÷&–6–æræ‡FÖÂ™¹˜xŞ‹Ø‹{0¢&WGW&â6VæEög&öÕöF—&V7F÷'’†ç7FF–5öföÆFW"Â&Æ–fb÷&–6–æræ‡FÖÂ" ¢FVböÆ–feöVÖ&VE÷&VF—&V7B†÷Våö7F–öãÔæöæRÂg&vÖVçCÒ""“ ¢"".ˆˆ¢öÆ–fbò¢…EE2˜
>{YiK[îkK˜^XZ~[XÎXZ^Xú>ûÈÎ˜şXXŞZIn™h¾xşŠkŞYš8""" ¢–bÆ–feöVçG'•÷W&Â—2æ÷BæöæS ¢F&vWBÒÆ–feöVçG'•÷W&Â†÷Våö7F–öãÖ÷Våö7F–öâÂg&vÖVçCÖg&vÖVçB¢VÇ6S ¢Æ–BÒ€¢æ6öæf–rævWB‚$Ä”deô”B"¢÷"÷2æVçf—&öâævWB‚$Ä”deô”B"¢÷"DTdTÅEôÄ”deô”@¢’ç7G&—‚¢F&vWBÒb&‡GG3¢òöÆ–fbæÆ–æRæÖR÷¶Æ–GÒ ¢–b÷Våö7F–öã ¢F&vWB³Òb#ö÷Vã×¶÷Våö7F–öçÒ ¢VÆ–bg&vÖVçC ¢F&vWB³Òb"7¶g&vÖVçBæÇ7G&—‚r2r—Ò ¢–b&VF—&V7B—2æ÷BæöæS ¢&WGW&â&VF—&V7B‡F&vWBÂ6öFSÓ3"¢&WGW&â§6öæ–g’‡²'&VF—&V7B#¢F&vWGÒ’Â3  ¢2YÉnih~˜Yjâòˆˆ®˜
>{YûÉ®[îY	Æ–fbæÆ–æRæÖRXZ~[XÎûÈYjîKˆVæGö–çBÒ–æFW‚æ‡FÖÎûÈ¢ævWB‚"öÆ–fb÷6†&RÖ–çf—FR"¢ævWB‚"öÆ–fb÷6†&RÖ–çf—FRæ‡FÖÂ"¢FVbÆ–fe÷6†&Uö–çf—FU÷vR‚“ ¢"".[yJKˆ˜Û^XˆnKª¾šûÈ{ZbÄ”dbZÙ‹zş[éy»N˜
>ûÉ¾KˆŞ{i25†öÖ^ûÈ8""" ¢&WGW&â6VæEög&öÕöF—&V7F÷'’†ç7FF–5öföÆFW"Â&Æ–fb÷6†&RÖ–çf—FRæ‡FÖÂ" ¢ævWB‚"öÆ–fb÷6†&R×G&–Âæ‡FÖÂ"¢FVbÆ–fe÷6†&U÷G&–Å÷vR‚“ ¢"".iÈ>Y:XˆnKª²BZJš¹Nš™~ûÉ¾KˆŞ[»®z¸¾h‰nhê^Xù~K»¾KÙ^ZèŠÛ~K«®˜(Š¸¾8""" ¢&WGW&â6VæEög&öÕöF—&V7F÷'’†ç7FF–5öföÆFW"Â&Æ–fb÷6†&R×G&–Âæ‡FÖÂ" ¢ævWB‚"öÆ–fb÷6÷2æ‡FÖÂ"¢FVbÆ–fe÷6÷5÷vR‚“ ¢"".‹É^˜xò4õ2XZ^Xú>ûÉ®XXšşzK®k.XªyZ¾™Ú.ûÈÎXhŞikÎˆ8ÎišşZèÎh‰Ä”dbš™~ŠØ8""" ¢&WGW&â6VæEög&öÕöF—&V7F÷'’†ç7FF–5öföÆFW"Â&Æ–fb÷6÷2æ‡FÖÂ" ¢ævWB‚"öÆ–fböÖ–w&FRæ‡FÖÂ"¢FVbÆ–feöÖ–w&F–öåö†æFöfe÷vR‚“ ¢""$ÆVv7’Ä”db†æFöfbF†B6·2W6W'2FòW‡Æ–6—FÇ’&VWF†÷&—¦Râ"" ¢&WGW&â6VæEög&öÕöF—&V7F÷'’†ç7FF–5öföÆFW"Â&Æ–fböÖ–w&FRæ‡FÖÂ" ¢2##bÓrÓ#F6‚#C¢öæ&ö&F–ærkXzˆ²¢ævWB‚"öÆ–fbööæ&ö&F–ær"¢FVbÆ–feööæ&ö&F–ær‚“ ¢&WGW&âöÆ–feöVÖ&VE÷&VF—&V7B†÷Våö7F–öãÒ&öæ&ö&F–ær" ¢ævWB‚"ö’ööæ&ö&F–ær÷7FFR"¢FVböæ&ö&F–æu÷7FFUö’‚“ ¢"".Xùn[é~KÛşyJˆRöæ&ö&F–ærx¸hX²ZèŠÛ~K«®iŠşY
n{hZé¢²hù˜i.i˜.™i28""" ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡·ÒÂW6Uö&w3ÕG'VR¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢FFÂ6öFRÒöæ&ö&F–æu÷7FGW5÷–ÆöB€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢Æ–æU÷W6W%ö–BÀ¢ÆÆ÷uöÖ—76–æu÷&öf–ÆSÕG'VRÀ¢¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç÷7B‚"ö’ööæ&ö&F–ær÷&VÖ–æFW""¢FVböæ&ö&F–æu÷&VÖ–æFW%ö’‚“ ¢"".ŠŠŞZé®KÛşyJˆ^jøşiz^hù˜i.i˜.™i2iJşhûNYjîKˆh‰nZI®i˜.jëR8""" ¢FFÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"†FF¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢&W7VÇBÂ6öFRÒWFFUööæ&ö&F–æu÷&VÖ–æFW"€¢æ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–BÂFF¢¢&WGW&â§6öæ–g’‡&W7VÇB’Â6öFP ¢ævWB‚"öÆ–fböwV&F–â"¢FVbÆ–feöwV&F–â‚“ ¢2kK˜^XZ^Xú>hxiŠòÆ–fbæÆ–æRæÖ^ûÉ¾jÚN‹zş[éKùŞyYy»ZëûÈÎ[îY	XZ~[XÂöæ&ö&F–æ~ûÈZèŠÛ~K«®(i.hù˜i.ûÈ¢&WGW&âöÆ–feöVÖ&VE÷&VF—&V7B†÷Våö7F–öãÒ&öæ&ö&F–ær" ¢ævWB‚"öÆ–fböÖVÖ&W""¢FVbÆ–feöÖVÖ&W"‚“ ¢&WGW&âöÆ–feöVÖ&VE÷&VF—&V7B†÷Våö7F–öãÒ&ÖVÖ&W"" ¢ævWB‚"öÆ–fböwV&F–âÖw&÷W2"¢FVbÆ–feöwV&F–åöw&÷W2‚“ ¢&WGW&âöÆ–feöVÖ&VE÷&VF—&V7B†÷Våö7F–öãÒ&wV&F–ç2" ¢ævWB‚"ö’ö6öæf–r"¢FVb6öæf–uö’‚“ ¢&WGW&â§6öæ–g’†ö6öæf–r†æ6öæf–r’ ¢ævWB‚"ö’ö&÷B÷7FGW2"¢FVb&÷E÷7FGW5ö’‚“ ¢""###bÓrÓ#F6‚s¢&÷Bi[Nš¹NX^[«~x¸hX²{Zn‰›‰>yÈ²8  ¢&WGW&ç3 ¢Ò6W'f–6S¢Æ—fRÖ6†V6¶–à¢Ò&÷EöæÖS¢jøşiz^[›>Zè¢ÒWF–ÖU÷6V6öæG3¢˜.zˆ¾YYşX¹^[èÎzy.i[€¢ÒW6W'5÷F÷FÃ¢Š‹¾Xh®K«®i[€¢ÒwV&F–åöw&÷W5÷F÷FÃ¢ZèŠÛ~{êN{hZé®{‹Şi[€¢ÒwV&F–åöw&÷W5ö7F—fS¢iÈiXy¨NZèŠÛ~{êNi[€¢ÒF–ÖW7F×¢y[nKˆ¾i˜.™i0¢ÒÆ–æU÷Fö¶Våö†5÷fÇVRòÆ–æU÷6V7&WEö†5÷fÇVS¢VçbiŠşY
niÈXÎûÈKˆŞY¹îX+>XZ~ZëûÈ¢ÒÆ–æU÷Fö¶Våöö²òÆ–æU÷Fö¶Våö‡GG¢yJ‚÷c"ö&÷Bö–æfòhê.kŠÂFö¶VâiŠşY
nŠ*²Ä”äRhê^Xùp¢"" ¢7FFRÒÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò¢w&÷W2Ò7FFRævWB‚&wV&F–åöw&÷W2"Â·Ò¢7F—fUöw&÷W2Ò7VÒƒf÷"r–âw&÷W2çfÇVW2‚’–brævWB‚'7FGW2"’ÓÒ&7F—fR"¢æ÷rÒFFWF–ÖRææ÷r‚¢&ö5÷7F'BÒvWFGG"†Â%÷7F'E÷F–ÖR"ÂæöæR¢WF–ÖRÒ†æ÷rÒ&ö5÷7F'B’çF÷FÅ÷6V6öæG2‚’–b&ö5÷7F'BVÇ6RæöæP¢Fö¶VâÒ€¢æ6öæf–rævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"¢÷"÷2æVçf—&öâævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"¢÷"÷2æVçf—&öâævWB‚$4„ääTÅô44U55õDô´Tâ"¢÷"" ¢’ç7G&—‚¢6V7&WBÒ€¢æ6öæf–rævWB‚$Ä”äUô4„ääTÅõ4T5$UB"¢÷"÷2æVçf—&öâævWB‚$Ä”äUô4„ääTÅõ4T5$UB"¢÷"÷2æVçf—&öâævWB‚$4„ääTÅõ4T5$UB"¢÷"" ¢’ç7G&—‚¢Æ–æU÷Fö¶Våöö²ÒæöæP¢Æ–æU÷Fö¶Våö‡GGÒæöæP¢–bFö¶Vã ¢G'“ ¢–×÷'BW&ÆÆ–"ç&WVW7@ ¢&WÒW&ÆÆ–"ç&WVW7Bå&WVW7B€¢&‡GG3¢òö’æÆ–æRæÖR÷c"ö&÷Bö–æfò"À¢†VFW'3×²$WF†÷&—¦F–öâ#¢b$&V&W"·Fö¶VçÒ'ÒÀ¢ÖWF†öCÒ$tUB"À¢¢v—F‚W&ÆÆ–"ç&WVW7BçW&Æ÷Vâ‡&WÂF–ÖV÷WCÓ‚’2&W7 ¢Æ–æU÷Fö¶Våö‡GGÒ–çB†vWFGG"‡&W7Â'7FGW2"Â#’÷"#¢Æ–æU÷Fö¶Våöö²ÒÆ–æU÷Fö¶Våö‡GGÓÒ# ¢W†6WBW†6WF–öâ2W†3 ¢6öFRÒvWFGG"†vWFGG"†W†2Â&6öFR"ÂæöæR’Â'&VÂ"ÂæöæR’÷"vWFGG"†W†2Â&6öFR"ÂæöæR¢G'“ ¢Æ–æU÷Fö¶Våö‡GGÒ–çB†6öFR’–b6öFR—2æ÷BæöæRVÇ6RæöæP¢W†6WBW†6WF–öã ¢Æ–æU÷Fö¶Våö‡GGÒæöæP¢Æ–æU÷Fö¶Våöö²ÒfÇ6P¢æÆövvW"çv&æ–ær€¢&Æ–æRFö¶Vâ&ö&Rf–ÆVB‡GGÒW2W'#ÒW2"À¢Æ–æU÷Fö¶Våö‡GGÀ¢G—R†W†2’åõöæÖUõòÀ¢¢&WGW&â§6öæ–g’‡°¢'6W'f–6R#¢&Æ—fRÖ6†V6¶–â"À¢&&÷EöæÖR#¢.jøşiz^[›>Zè’"À¢&FWÆ÷•÷fW'6–öâ#¢÷2æVçf—&öâævWB‚$DUÄõ•õdU%4”ôâ"’÷"%s#Ss#Vv‚"À¢'WF–ÖU÷6V6öæG2#¢&÷VæB‡WF–ÖRÂ’–bWF–ÖRVÇ6RæöæRÀ¢'W6W'5÷F÷FÂ#¢ÆVâ‡7FFRævWB‚'W6W'2"Â·Ò’’À¢&wV&F–åöw&÷W5÷F÷FÂ#¢ÆVâ†w&÷W2’À¢&wV&F–åöw&÷W5ö7F—fR#¢7F—fUöw&÷W2À¢'F–ÖW7F×#¢æ÷ræ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"’À¢&Æ–æU÷Fö¶Våö†5÷fÇVR#¢&ööÂ‡Fö¶Vâ’À¢&Æ–æU÷6V7&WEö†5÷fÇVR#¢&ööÂ‡6V7&WB’À¢&Æ–æU÷Fö¶Våöö²#¢Æ–æU÷Fö¶Våöö²À¢&Æ–æU÷Fö¶Våö‡GG#¢Æ–æU÷Fö¶Våö‡GGÀ¢Ò ¢ævWB‚"ö’÷7FGW2"¢FVb7FGW2‚“ ¢""$Ä”dbšin‹ÈûÉ®iÈiÈiX‹ª¾Xˆn[W6W'NûÈÎ˜şXXÒD"Š*²W†VÖW&ÂF—6²kˆ^hè[èÎXÚCN8""" ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡·ÒÂW6Uö&w3ÕG'VR¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢FFÂ6öFRÒ7FGW5öf÷%÷W6W"€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢Æ–æU÷W6W%ö–BÀ¢&WVW7Bæ&w2ævWB‚&F—7Æ•öæÖR"’À¢¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ævWB‚"ö’öÖVÖ&W"öW†—7G2"¢FVbÖVÖ&W%öW†—7G5ö’‚“ ¢"".Xú®Šèjª.iú^iÈ>Y:iŠşY
n[{.ZÙYÊûÉ¾KˆŞ[é~YºXˆnKª¾XZ^Xú>ˆÎˆz®X¹^Š‹¾Xh®8""" ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡·ÒÂW6Uö&w3ÕG'VR¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢7FFRÒÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò¢&öf–ÆRÒ‡7FFRævWB‚'W6W'2"’÷"·Ò’ævWB†Æ–æU÷W6W%ö–B¢&WGW&â§6öæ–g’‡°¢&ö²#¢G'VRÀ¢'&Vv—7FW&VB#¢&ööÂ‡&öf–ÆR’À¢&†öÖU÷&VG’#¢&ööÂ‡&öf–ÆRæBÖVÖ&W%ö66W75÷7FFR‡&öf–ÆR•²&†öÖU÷&VG’%Ò’À¢Ò’Â#  ¢ævWB‚"ö’öF–Ç’Ö6&R"¢FVbF–Ç•ö6&Uö’‚“ ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡·ÒÂW6Uö&w3ÕG'VR¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢7FFRÒÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò¢&öf–ÆRÒ‡7FFRævWB‚'W6W'2"’÷"·Ò’ævWB†Æ–æU÷W6W%ö–B¢–bæ÷B—6–ç7Fæ6R‡&öf–ÆRÂF–7B“ ¢&WGW&â§6öæ–g’‡²&ö²#¢fÇ6RÂ&W'&÷"#¢&ÖVÖ&W%öæ÷Eöf÷VæB'Ò’ÂC@¢æ÷rÒ7W'&VçEö÷F–ÖR†æ6öæf–r¢6&U÷&öf–ÆRÒF–7B‡&öf–ÆR¢6&U÷&öf–ÆU²'7G&VµöF—2%ÒÒ6ö×WFU÷7G&VµöF—2€¢6&U÷&öf–ÆRævWB‚&†—7F÷'’"’÷"µÒÂæ÷rç7G&gF–ÖR‚"U’ÒVÒÒVB"¢¢6öçFW‡BÒ'V–ÆEöF–Ç•ö6&Uö6öçFW‡B†6&U÷&öf–ÆRÂæ÷r¢–b6öçFW‡E²&6öçFVçEö¶–æB%ÒÒ&Ö–ÆW7FöæR"æB†öÆ–F—5÷Gr—2æ÷BæöæS ¢†öÆ–F’Ò†öÆ–F—5÷Græ†öÆ–F•öf÷"†æ÷r¢–b†öÆ–F“ ¢6öçFW‡E²&6&U÷F—FÆR%ÒÒb/	øè’¶†öÆ–F’ævWB‚væÖRrÂ~zøiz^zYŞzhòr—Ò ¢6öçFW‡E²&6&U÷7VÖÖ'’%ÒÒ7G"††öÆ–F’ævWB‚&&ÆW76–ær"’÷"6öçFW‡E²&6&U÷7VÖÖ'’%Ò¢6öçFW‡E²&6öçFVçEö¶–æB%ÒÒ&†öÆ–F’ ¢&WGW&â§6öæ–g’‡²&ö²#¢G'VRÂ¢¦6öçFW‡GÒ’Â#  ¢ç÷7B‚"ö’öÆ–æR÷&Vv—7FW""¢FVbÆ–æU÷&Vv—7FW"‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢FFÂ6öFRÒ&Vv—7FW%öÆ–æU÷W6W"†æ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöB¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç÷7B‚"ö’÷&öf–ÆRöÆö6F–öâ"¢FVbÖVÖ&W%öÆö6F–öåö’‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢FFÂ6öFRÒWFFUöÖVÖ&W%öÆö6F–öâ€¢æ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–BÂ–ÆöBÂ6÷W&6SÒ&ÖVÖ&W" ¢¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç÷7B‚"ö’ö&WFö6Æ–Ò"¢FVb&WFö6Æ–Õö’‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢6ö†÷'BÒ7G"‡–ÆöBævWB‚&&WFö6ö†÷'B"’÷"""’ç7G&—‚’çWW"‚¢–b6ö†÷'Bæ÷B–â²$#3“’"Â$#s“’'Ó ¢&WGW&â§6öæ–g’‡²&ö²#¢fÇ6RÂ&W'&÷"#¢&–çfÆ–Eö&WFöÆ–æ²'Ò’ÂC ¢G'“ ¢&W7VÇBÒ×WFFU÷7FFUöFöÖ–6ÆÇ’€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢ÆÖ&F7FFS¢6Æ–Õö&WFöÆ–æ²‡7FFRÂÆ–æU÷W6W%ö–BÂ6ö†÷'B’À¢¢W†6WBfÇVTW'&÷"2W†3 ¢&V6öâÒ7G"†W†2¢ÖW76vW2Ò°¢&6ö†÷'EögVÆÂ#¢.˜	Kˆ{XN[kŠÎYŞšŞ[{.k»ò"À¢&Ç&VG•ö–åö÷F†W%ö6ö†÷'B#¢.KÚ[{.XªXZ^XúnKˆX¾[kŠÎ{XNXŠR"À¢&ÖVÖ&W%öæ÷Eöf÷VæB#¢.Š¸¾XXZèÎh‰Ä”äRiÈ>Y:Š‹¾Xh¢"À¢&g&VUöVÆ–v–&–Æ—G•öÇ&VG•÷W6VB#¢.KÚ[{.KÛşyJ˜îXXŞ‹+¾š¹Nš™~h‰n[kŠÎ‹8~jÂ"À¢Ğ¢&WGW&â§6öæ–g’‡°¢&ö²#¢fÇ6RÀ¢&W'&÷"#¢&V6öâÀ¢&ÖW76vR#¢ÖW76vW2ævWB‡&V6öâÂ.xJk9^XªXZ^[kŠÂ"’À¢Ò’ÂC’–b&V6öâÒ&ÖVÖ&W%öæ÷Eöf÷VæB"VÇ6RC@¢&WGW&â§6öæ–g’‡²&ö²#¢G'VRÂ¢§&W7VÇGÒ’Â#  ¢ç÷7B‚"ö’ö6†V6¶–â"¢FVb6†V6¶–â‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢&W7VÇBÂ6öFRÒ6†V6¶–åöf÷%÷W6W"€¢æ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–BÂ–ÆöBÂæ6öæf–p¢¢&WGW&â§6öæ–g’‡&W7VÇB’Â6öFP ¢ç÷7B‚"ö6ÆÆ&6²"¢FVbÆ–æUö6ÆÆ&6²‚“ ¢–bÆ–æT&÷D’—2æöæR÷"vV&†öö´†æFÆW"—2æöæS ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢&Æ–æRÖ&÷B×6F²—2æ÷B–ç7FÆÆVB'Ò’ÂS0¢Fö¶VâÒ€¢æ6öæf–rævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"¢÷"÷2æVçf—&öâævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"¢÷"÷2æVçf—&öâævWB‚$4„ääTÅô44U55õDô´Tâ"¢÷"" ¢’ç7G&—‚¢6V7&WBÒ€¢æ6öæf–rævWB‚$Ä”äUô4„ääTÅõ4T5$UB"¢÷"÷2æVçf—&öâævWB‚$Ä”äUô4„ääTÅõ4T5$UB"¢÷"÷2æVçf—&öâævWB‚$4„ääTÅõ4T5$UB"¢÷"" ¢’ç7G&—‚¢–bæ÷BFö¶Vâ÷"æ÷B6V7&WC ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢$Ä”äR7&VFVçF–Ç2&Ræ÷B6öæf–wW&VB'Ò’ÂS0 ¢Æ–æUö&÷Eö’ÒÆ–æT&÷D’‡Fö¶Vâ¢†æFÆW"ÒvV&†öö´†æFÆW"‡6V7&WB ¢FVb÷6÷5ö†æFÆR†Æ–æUö&÷Eö’ÂÆ–æU÷W6W%ö–BÂ6öÖÖæBÂ&WÇ•÷Fö¶VãÔæöæRÂw&÷Wö–CÔæöæR“ ¢"".™ÈŠh[š¾[ùûÉ®ˆ®ZJZêN˜
>{¨Îz+®Š¨Ò2jÊ[èÎ˜XZ^X[yJ‚4õ2K¨¾K»n8  ¢6öÖÖæC ¢Ò~™ÈŠh[š¾[ù’ròu4õ2ròw6÷2rò~{x®h
^k.Xª’r¢{JşŠˆKˆjÊz+®Š¨Ğ¢Ò~Xùnkh™ÈŠh[š¾[ù’ròu4õ2Xùnkh‚r¢Xùnkh‚VæF–æp¢"" ¢7FFRÒÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò¢&öf–ÆRÒvWE÷&öf–ÆR‡7FFRÂÆ–æU÷W6W%ö–B’–bÆ–æU÷W6W%ö–BVÇ6RæöæP¢æÆövvW"æ–æfò€¢'6÷5ö†æFÆR6öÖÖæCÒW2W6W#ÒW2w&÷WÒW2"À¢6öÖÖæBÀ¢†Æ–æU÷W6W%ö–B÷"""•³£…ÒÀ¢†w&÷Wö–B÷"""•³£…ÒÀ¢ ¢FVb&WÇ’†fÆW‚ÂÇE÷FW‡CÒ""“ ¢ÖW76vW2ÒµĞ¢–bfÆW…6VæDÖW76vR—2æ÷BæöæRæBfÆW‚—2æ÷BæöæS ¢ÖW76vW2æVæB„fÆW…6VæDÖW76vR†ÇE÷FW‡CÖÇE÷FW‡BÂ6öçFVçG3ÖfÆW‚’¢VÇ6S ¢ÖW76vW2æVæB…FW‡E6VæDÖW76vR‡FW‡CÖÇE÷FW‡B÷".™ÈŠh[š¾[ù’"’¢G'“ ¢–b&WÇ•÷Fö¶Vã ¢Æ–æUö&÷Eö’ç&WÇ•öÖW76vR‡&WÇ•÷Fö¶VâÂÖW76vW2¢&WGW&à¢W†6WBW†6WF–öâ2W†3 ¢æÆövvW"æW†6WF–öâ‚'6÷2&WÇ•öÖW76vRf–ÆVC¢W2"ÂW†2¢2&WÇ•÷Fö¶VâZKiY~h‰niÊ®hùKé²(i"W6‚X‹YÎKˆX¾[ŞŠ›¢W6…÷F&vWBÒw&÷Wö–B÷"Æ–æU÷W6W%ö–@¢–bæ÷BW6…÷F&vWC ¢æÆövvW"æW'&÷"‚'6÷26VæB&÷'FVC¢æòW6‚F&vWB"¢&WGW&à¢G'“ ¢Æ–æUö&÷Eö’çW6…öÖW76vR‡W6…÷F&vWBÂÖW76vW2¢W†6WBW†6WF–öâ2W†3 ¢æÆövvW"æW†6WF–öâ‚'6÷2W6…öÖW76vRf–ÆVC¢W2"ÂW†2 ¢VçG'•ö6öÖÖæG2Ò‚.™ÈŠh[š¾[ù’"Â%4õ2"Â'6÷2"Â.{x®h
^k.Xª’"¢2[{.˜X‹ˆ®ZJZêNy¨Nˆˆ¢fÆW‚hÈ˜‰^xJk9^Y¹îiKnûÉ¾KùŞyYX[nih~ZÙ~YŞKºNûÈÀ¢2KØnKˆ[è¾Xú®Y¹îikx˜‚Ä”dbXZ^Xú>ûÈÎKˆŞXhŞYYşX¹^ˆˆ®y¨Nˆ®ZJx¸hX¾j™ş8 ¢ÆVv7•öVçG'•ö6öÖÖæG2Ò€¢.˜	®yú^ZënK«¢"À¢.ˆş{ZZënK«®˜
>hÈ“>jÊ"À¢.™ÈŠh[š¾[ùz+®Š¨Ò"À¢%4õ2z+®Š¨Ò""À¢%4õ2z+®Š¨Ò2"À¢¢6æ6VÅö6öÖÖæG2Ò‚%4õ2Xùnkh‚"Â.Xùnkh™ÈŠh[š¾[ù’" ¢–b6öÖÖæB–â6æ6VÅö6öÖÖæG3 ¢–b6÷5öfÆ÷rç6÷5ö6æ6VÅ÷VæF–ær‡7FFRÂÆ–æU÷W6W%ö–B“ ¢6fU÷7FFR†æ6öæf–u²$DDôd”ÄR%ÒÂ7FFR¢&WÇ’‡6÷5öfÆ÷rç6÷5ö6æ6VÆÆVEöfÆW‚‚’Â.)ÈR[{.Xùnkh™ÈŠh[š¾[ù’"¢VÇ6S ¢&WÇ’„æöæRÂ.k).iÈ[è^Xùnkhy¨N™ÈŠh[š¾[ù˜	®yúR"¢&WGW&à ¢2ˆ®ZJZêNKùŞyY˜
>{¨Â2jÊz+®Š¨ŞûÉ¾YÉnih~˜YjîX˜~™h²Ä”dby¨NYÎKˆZYr2jÊkXzˆ¾8 ¢–b6öÖÖæB–âVçG'•ö6öÖÖæG2÷"6öÖÖæB–âÆVv7•öVçG'•ö6öÖÖæG3 ¢FÒ6÷5öfÆ÷rç6÷5÷F‡7FFRÂÆ–æU÷W6W%ö–B¢6÷VçBÒ–çB‚‡FævWB‚&VçG'’"’÷"·Ò’ævWB‚'Fö6÷VçB"’÷"¢6fU÷7FFR†æ6öæf–u²$DDôd”ÄR%ÒÂ7FFR¢–b6÷VçBÂ3 ¢&WÇ’€¢6÷5öfÆ÷rç6÷5÷v&æ–æuöfÆW‚†6÷VçB’À¢b/	øi‚™ÈŠh[š¾[ùz+®Š¨Ò¶6÷VçGÒó2"À¢¢&WGW&à¢&W7VÇBÂ7FGW5ö6öFRÒG&–vvW%÷6÷2€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢²&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–GÒÀ¢æ6öæf–rÀ¢¢–b7FGW5ö6öFRÓÒ# ¢ÆFW7BÒÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò¢6÷5öfÆ÷rç6÷5öÖ&µ÷6VçB€¢ÆFW7BÂÆ–æU÷W6W%ö–BÂ&W7VÇBævWB‚&WfVçEö–B"¢¢6fU÷7FFR†æ6öæf–u²$DDôd”ÄR%ÒÂÆFW7B¢&WÇ’€¢6÷5öfÆ÷rç6÷5÷6VçEöfÆW‚‚’À¢b/	ùª‚4õ2[{.˜X{®ûÈÎ[{.˜	®yúR¶–çB‡&W7VÇBævWB‚w6VçBr’÷"—ÒX¾[Ş‹"À¢¢VÆ–b7G"‡&W7VÇBævWB‚&W'&÷""’÷"""’ÓÒ&æò&÷VæBÄ”äRwV&F–ç2# ¢&WÇ’€¢6÷5öfÆ÷rç6÷5öæõöwV&F–ç5öfÆW‚‚’À¢6÷5÷W6W%öf6–æuöW'&÷"‡&W7VÇBævWB‚&W'&÷""’’À¢¢VÇ6S ¢&WÇ’„æöæRÂ6÷5÷W6W%öf6–æuöW'&÷"‡&W7VÇBævWB‚&W'&÷""’’¢&WGW&à ¢–b6öÖÖæBæ÷B–âVçG'•ö6öÖÖæG2æB6öÖÖæBæ÷B–âÆVv7•öVçG'•ö6öÖÖæG3 ¢&WÇ’„æöæRÂ.Š¸¾X+>˜8Î™ÈŠh[š¾[ù8Ş™h¾YYşk.Xª˜šR"¢&WGW&à ¢FVb÷6VæE÷vVÆ6öÖR†Æ–æUö&÷Eö’Â&WÇ•÷Fö¶VãÔæöæRÂÆ–æU÷W6W%ö–CÔæöæRÂF—7Æ•öæÖSÔæöæRÂG&–vvW#ÔæöæR“ ¢""$föÆÆ÷rò™yÎ˜Û^ZÙ~X[yJûÉ®˜vVÆ6öÖUöfÆWûÈÎZKiY~Zú²ÆörKŠbW6‚fÆÆ&6¾8""" ¢2jøşjÊy›Î˜X˜ŞXhŞXùnKˆjÊyÉşZúni«z‹ûÈ˜şXXÒföÆÆ÷ry[nKˆ²&öf–ÆRZKiY~Šè®h‰z›®y›ŞûÈş8Îh*8ŞûÈ¢&W6öÇfVBÒ&W6öÇfU÷vVÆ6öÖUöF—7Æ•öæÖR€¢Æ–æUö&÷Eö“ÖÆ–æUö&÷Eö’À¢FFöf–ÆSÖæ6öæf–u²$DDôd”ÄR%ÒÀ¢Æ–æU÷W6W%ö–CÖÆ–æU÷W6W%ö–BÀ¢†–çCÖF—7Æ•öæÖRÀ¢ÆövvW#ÖæÆövvW"À¢¢–bvVÆ6öÖUöw&VWF–æu÷FW‡B—2æ÷BæöæS ¢w&VWF–ærÒvVÆ6öÖUöw&VWF–æu÷FW‡B‡&W6öÇfVB¢VÆ–b&W6öÇfVC ¢w&VWF–ærÒb/	ù²·&W6öÇfVGÒh*Z[ŞûÈÎjÚ‹øîXªXZ^8Îjøşiz^[›>Zè8Ò ¢VÇ6S ¢w&VWF–ærÒ/	ù²h*Z[ŞûÈÎjÚ‹øîXªXZ^8Îjøşiz^[›>Zè8Ò ¢æÆövvW"æ–æfò€¢'vVÆ6öÖUöfÆW‚7F'BG&–vvW#ÒW2W6W#ÒW2æÖSÒW"†5÷&WÇ“ÒW2"À¢G&–vvW"÷"'Væ¶æ÷vâ"À¢†Æ–æU÷W6W%ö–B÷"""•³£…ÒÀ¢&W6öÇfVB÷"""À¢&ööÂ‡&WÇ•÷Fö¶Vâ’À¢¢6WGW÷W&’Ò€¢Æ–feöVçG'•÷W&Â†÷Våö7F–öãÒ&öæ&ö&F–ær"¢–bÆ–feöVçG'•÷W&À¢VÇ6R&‡GG3¢òöÆ–fbæÆ–æRæÖRó#ƒCƒ33ÕT—”Cö÷VãÖöæ&ö&F–ær ¢¢–çf—FU÷W&’Ò€¢6†&Uö–çf—FUöÆ–fe÷W&Â‚¢–b6†&Uö–çf—FUöÆ–fe÷W&À¢VÇ6R&‡GG3¢òöÆ–fbæÆ–æRæÖRó#ƒCƒ33ÕT—”BöÆ–fb÷6†&RÖ–çf—FRæ‡FÖÂ ¢¢†VÇ÷W&’Ò€¢Æ–feöVçG'•÷W&Â†÷Våö7F–öãÒ&†VÇ"¢–bÆ–feöVçG'•÷W&À¢VÇ6R&‡GG3¢òöÆ–fbæÆ–æRæÖRó#ƒCƒ33ÕT—”Cö÷VãÖ†VÇ ¢¢vVÆ6öÖUöfÆÆ&6²Ò€¢b'¶w&VWF–æwÕÆåÆâ ¢.jøşZJ’zy.ûÈÎZX¾[›>Zè•Æâ ¢.[›>[‹KˆŞh™>i;îûÈÎiÈK¨¾h˜Ş˜	®yú^ZèŠÛ~K«¥ÆåÆâ ¢.™h¾Zx¾KÛşyJX˜ŞXZX¾jÚ^š™şûÉ¥Æâ ¢.)ikZ)âKØŞZèŠÛ~K«¥Æâ ¢.)ŠŠŞZé®jøşiz^hù˜i.i˜.™i5ÆåÆâ ¢/	øèšinjÊŠ‹¾Xh®XúşKª¾KˆjÊBZJZè[ø>š¹Nš™uÆâ ¢.{x®h
^x¸k8Š¸¾y»Nhê^i*^h™2’h‰bÆåÆâ ¢b.XXŞ‹+¾š¹Nš™rBZJûÉ§·6WGW÷W&—ÕÆâ ¢b.Kˆ˜Û^ZèŠÛ~˜(Š¸¾ûÉ§¶–çf—FU÷W&—ÕÆâ ¢b.K¨nŠz>jøşiz^[›>ZèûÉ§¶†VÇ÷W&—ÕÆâ ¢.X+>8Î™h¾Zx¾8ŞXúş˜xŞh»şjÚ‹øîXÚ ¢¢ÇE÷FW‡BÒ€¢b.jøşiz^[›>ZèûÙÇ·&W6öÇfVGÒh*Z[ŞûÈÎjÚ‹øîXªXZR ¢–b&W6öÇfV@¢VÇ6R.jøşiz^[›>ZèûÙÎh*Z[ŞûÈÎjÚ‹øîXªXZR ¢¢fÆW…ö6öçFVçG2ÒvVÆ6öÖUöfÆW‚‡&W6öÇfVB’–bvVÆ6öÖUöfÆW‚—2æ÷BæöæRVÇ6RæöæP¢–bfÆW…ö6öçFVçG2—2æöæS ¢æÆövvW"æW'&÷"‚'vVÆ6öÖUöfÆW‚6öçFVçG2—2æöæR(	B6†V6²–×÷'B"¢G'“ ¢–bfÆW…6VæDÖW76vR—2æ÷BæöæRæBfÆW…ö6öçFVçG2—2æ÷BæöæRæB&WÇ•÷Fö¶Vã ¢Æ–æUö&÷Eö’ç&WÇ•öÖW76vR€¢&WÇ•÷Fö¶VâÀ¢fÆW…6VæDÖW76vR†ÇE÷FW‡CÖÇE÷FW‡BÂ6öçFVçG3ÖfÆW…ö6öçFVçG2’À¢¢æÆövvW"æ–æfò‚'vVÆ6öÖUöfÆW‚&WÇ’ö²æÖSÒW""Â&W6öÇfVB÷"""¢&WGW&à¢–b&WÇ•÷Fö¶Vã ¢Æ–æUö&÷Eö’ç&WÇ•öÖW76vR‡&WÇ•÷Fö¶VâÂFW‡E6VæDÖW76vR‡FW‡C×vVÆ6öÖUöfÆÆ&6²’¢æÆövvW"çv&æ–ær‚'vVÆ6öÖRFW‡B&WÇ’fÆÆ&6²"¢&WGW&à¢W†6WBW†6WF–öâ2W†3 ¢æÆövvW"æW†6WF–öâ‚'vVÆ6öÖR&WÇ’f–ÆVC¢W2"ÂW†2¢–bÆ–æU÷W6W%ö–BæBfÆW…6VæDÖW76vR—2æ÷BæöæRæBfÆW…ö6öçFVçG2—2æ÷BæöæS ¢G'“ ¢Æ–æUö&÷Eö’çW6…öÖW76vR€¢Æ–æU÷W6W%ö–BÀ¢fÆW…6VæDÖW76vR†ÇE÷FW‡CÖÇE÷FW‡BÂ6öçFVçG3ÖfÆW…ö6öçFVçG2’À¢¢æÆövvW"æ–æfò‚'vVÆ6öÖUöfÆW‚W6‚ö²æÖSÒW""Â&W6öÇfVB÷"""¢&WGW&à¢W†6WBW†6WF–öâ2W†3 ¢æÆövvW"æW†6WF–öâ‚'vVÆ6öÖRW6‚fÆW‚f–ÆVC¢W2"ÂW†2¢G'“ ¢26GW&RW†7BÄ”äRW'&÷"&öG’v†Vâf–Æ&ÆP¢W'%ö&öG’ÒvWFGG"†W†2Â&W'&÷""ÂæöæR’÷"vWFGG"†W†2Â'&W7öç6R"ÂæöæR¢æÆövvW"æW'&÷"‚'vVÆ6öÖRW6‚fÆW‚Ä”äRFWF–Ã¢W2"ÂW'%ö&öG’¢W†6WBW†6WF–öã ¢70¢–bÆ–æU÷W6W%ö–C ¢G'“ ¢Æ–æUö&÷Eö’çW6…öÖW76vR†Æ–æU÷W6W%ö–BÂFW‡E6VæDÖW76vR‡FW‡C×vVÆ6öÖUöfÆÆ&6²’¢æÆövvW"çv&æ–ær‚'vVÆ6öÖRFW‡BW6‚fÆÆ&6²"¢W†6WBW†6WF–öâ2W†3 ¢æÆövvW"æW†6WF–öâ‚'vVÆ6öÖRW6‚FW‡Bf–ÆVC¢W2"ÂW†2 ¢FVböwV&F–åö–çG&õöÖW76vW2†÷væW%ö–æfòÂ†–çE÷FW‡CÔæöæR“ ¢"".˜.{êNjÚ‹øîûÉ®yúŞih~ZÙr²fÆWûÈ™¹KùŞ™ª®ûÈÎ˜şXXÒfÆW‚Š*¾h¹.i˜.i[Një^khZKûÈ8""" ¢F—Ò†–çE÷FW‡B÷"€¢/	ùºûˆòjÚ‹øîXªXZ^8Îjøşiz^[›>Zè8ŞZèŠÛ~{êEÆâ ¢.[›>i˜.KˆŞh™>i;îûÈÎXú®YÊ™ÈŠhi˜.˜	®yú^ZJ~Zën8" ¢¢ÖW76vW2ÒµFW‡E6VæDÖW76vR‡FW‡C×F—•Ğ¢–bfÆW…6VæDÖW76vR—2æ÷BæöæRæBwV&F–åöw&÷Wö–çG&õöfÆW‚—2æ÷BæöæS ¢ÖW76vW2æVæB€¢fÆW…6VæDÖW76vR€¢ÇE÷FW‡CÒ/	ùºûˆòjÚ‹øîXªXZ^8Îjøşiz^[›>Zè8ŞZèŠÛ~{êB"À¢6öçFVçG3ÖwV&F–åöw&÷Wö–çG&õöfÆW‚†÷væW%ö–æfò’À¢¢¢&WGW&âÖW76vW0 ¢FVb÷&WÇ•öÖ–w&FVEö66÷VçB‡&WÇ•÷Fö¶VâÂ&Vv—7G&F–öå÷&W7VÇB“ ¢wV–Fæ6RÒÖ–w&FVEö66÷VçE÷vV&†ööµöwV–Fæ6R€¢&Vv—7G&F–öå÷&W7VÇBÀ¢æ6öæf–rævWB‚$Ä”deô”B"’÷"DTdTÅEôÄ”deô”BÀ¢¢–bæ÷BwV–Fæ6S ¢&WGW&âfÇ6P¢G'“ ¢Æ–æUö&÷Eö’ç&WÇ•öÖW76vR€¢&WÇ•÷Fö¶VâÀ¢FW‡E6VæDÖW76vR‡FW‡CÖwV–Fæ6R’À¢¢W†6WBW†6WF–öâ2W†3 ¢æÆövvW"æW†6WF–öâ€¢&Ö–w&FVB66÷VçBwV–Fæ6R&WÇ’f–ÆVC¢W2"ÂW†0¢¢&WGW&âG'VP ¢FVböVç&–6…ö&–æE÷&W7VÇEöf÷%öfÆW‚‡&W7VÇBÂÆ–æU÷W6W%ö–B“ ¢"".Š9ÎKˆ®‹8~Šˆ®XÚûÉ®zêynK«®ûÈşj[ø>ZèŠÛ~K«®ûÈş{x®h
^ˆş{ZK«®ûÈş{êN{XNh‰Y:ûÈşhù˜i.i˜.™i>8""" ¢Vç&–6†VBÒF–7B‡&W7VÇB÷"·Ò¢G'“ ¢7FFRÒÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò¢&öf–ÆRÒvWE÷&öf–ÆR‡7FFRÂÆ–æU÷W6W%ö–B’÷"·Ğ¢'VÆW2ÒÆå÷'VÆW2‡&öf–ÆR¢F–ÖW2Ò&VÖ–æFW%÷F–ÖW5öf÷%÷&öf–ÆR‡&öf–ÆR’÷"²#“£%Ğ¢6öçF7G2Ò&öf–ÆRævWB‚&6öçF7G2"’÷"µĞ¢2[{.{hZé®j[ø>ZèŠÛ~K«¢(š{êN{XNh‰Y:(š{x®h
^ˆş{ZK«®ûÉ¾Xú®yJ‚6÷&RYŞšĞ¢wV&F–åö6÷VçBÒ7VÒ€¢¢f÷"2–â6öçF7G0¢–b&W6öÇfUö6öçF7E÷&öÆR†2’Ò&VÖW&vVæ7’ ¢æB6öçF7Eö—5ö&÷VæEöwV&F–â†2ÂÆ–æU÷W6W%ö–B¢¢VÖW&vVæ7•ö6÷VçBÒ7VÒ€¢f÷"2–â6öçF7G2–b&W6öÇfUö6öçF7E÷&öÆR†2’ÓÒ&VÖW&vVæ7’ ¢¢Vç&–6†VBç6WFFVfVÇB€¢&F—7Æ•öæÖR"À¢‡&öf–ÆRævWB‚&F—7Æ•öæÖR"’÷"""’ç7G&—‚’÷".zêynY:"À¢¢Vç&–6†VBç6WFFVfVÇB‚&wV&F–åö6÷VçB"ÂwV&F–åö6÷VçB¢Vç&–6†VBç6WFFVfVÇB€¢&wV&F–åöÆ–Ö—B"À¢–çB‡'VÆW2ævWB‚&6÷&UöwV&F–åöÆW'EöÆ–Ö—B"’÷"R’À¢¢Vç&–6†VBç6WFFVfVÇB‚&6÷&UöwV&F–åöÆW'EöÆ–Ö—B"Â–çB‡'VÆW2ævWB‚&6÷&UöwV&F–åöÆW'EöÆ–Ö—B"’÷"R’¢Vç&–6†VBç6WFFVfVÇB‚&VÖW&vVæ7•ö6÷VçB"ÂVÖW&vVæ7•ö6÷VçB¢Vç&–6†VBç6WFFVfVÇB€¢&VÖW&vVæ7•öÆ–Ö—B"À¢–çB‡'VÆW2ævWB‚&VÖW&vVæ7•ö6öçF7EöÆ–Ö—B"’÷""’À¢¢Vç&–6†VBç6WFFVfVÇB€¢&VÖW&vVæ7•ö6öçF7EöÆ–Ö—B"À¢–çB‡'VÆW2ævWB‚&VÖW&vVæ7•ö6öçF7EöÆ–Ö—B"’÷""’À¢¢Vç&–6†VBç6WFFVfVÇB‚'&VÖ–æFW%÷F–ÖR"Â7G"‡F–ÖW5³Ò–bF–ÖW2VÇ6R#“£"’¢Vç&–6†VBç6WFFVfVÇB‚'&VÖ–æFW%÷F–ÖW2"ÂÆ—7B‡F–ÖW2’¢w&÷Wö–BÒVç&–6†VBævWB‚&w&÷Wö–B"¢–bw&÷Wö–C ¢&Vg&W6†VBÒ&Vg&W6…öwV&F–åöw&÷WöÖVÖ&W%÷6æ6†÷B€¢æ6öæf–u²$DDôd”ÄR%ÒÂw&÷Wö–@¢¢–b&Vg&W6†VBæB&Vg&W6†VBævWB‚&ÖVÖ&W%ö6÷VçEöEö&–æB"’—2æ÷BæöæS ¢Vç&–6†VE²&ÖVÖ&W%ö6÷VçB%ÒÒ&Vg&W6†VBævWB‚&ÖVÖ&W%ö6÷VçEöEö&–æB"¢VÇ6S ¢rÒ‡7FFRævWB‚&wV&F–åöw&÷W2"’÷"·Ò’ævWB†w&÷Wö–B’÷"·Ğ¢–brævWB‚&ÖVÖ&W%ö6÷VçEöEö&–æB"’—2æ÷BæöæS ¢Vç&–6†VBç6WFFVfVÇB€¢&ÖVÖ&W%ö6÷VçB"ÂrævWB‚&ÖVÖ&W%ö6÷VçEöEö&–æB"¢¢W†6WBW†6WF–öâ2W†3 ¢æÆövvW"æW†6WF–öâ‚&Vç&–6‚&–æB&W7VÇBf–ÆVC¢W2"ÂW†2¢Vç&–6†VBç6WFFVfVÇB‚&F—7Æ•öæÖR"Â.zêynY:"¢Vç&–6†VBç6WFFVfVÇB‚&wV&F–åö6÷VçB"Â¢Vç&–6†VBç6WFFVfVÇB‚&wV&F–åöÆ–Ö—B"ÂR¢Vç&–6†VBç6WFFVfVÇB‚&VÖW&vVæ7•ö6÷VçB"Â¢Vç&–6†VBç6WFFVfVÇB‚&VÖW&vVæ7•öÆ–Ö—B"Â"¢Vç&–6†VBç6WFFVfVÇB‚'&VÖ–æFW%÷F–ÖR"Â#“£"¢&WGW&âVç&–6†V@ ¢FVbö÷væW%öF—7Æ•öæÖR†÷væW%ö–æfò“ ¢÷væW%ö–BÒ†÷væW%ö–æfò÷"·Ò’ævWB‚&÷væW%ö–B"¢–bæ÷B÷væW%ö–C ¢&WGW&â.ZënK«¢ ¢G'“ ¢7FFRÒÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò¢&öf–ÆRÒ7FFRævWB‚'W6W'2"Â·Ò’ævWB†÷væW%ö–BÂ·Ò’÷"·Ğ¢æÖRÒ‡&öf–ÆRævWB‚&F—7Æ•öæÖR"’÷"""’ç7G&—‚¢&WGW&âæÖR÷".ZënK«¢ ¢W†6WBW†6WF–öã ¢&WGW&â.ZënK«¢  ¢FVböÆöEöw&÷Wö÷væW%ö–æfò†w&÷Wö–BÂÆ–æU÷W6W%ö–CÔæöæR“ ¢÷væW%ö–æfòÒ°¢&&÷VæB#¢fÇ6RÀ¢&—5ö÷væW"#¢fÇ6RÀ¢&÷væW%ö–B#¢æöæRÀ¢&—5ö7F—fR#¢fÇ6RÀ¢&÷væW%÷Æâ#¢æöæRÀ¢Ğ¢–bæ÷Bw&÷Wö–C ¢&WGW&â÷væW%ö–æfğ¢G'“ ¢7FFRÒÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò¢W†—7F–æuöw&÷WÒ7FFRævWB‚&wV&F–åöw&÷W2"Â·Ò’ævWB†w&÷Wö–B÷"""Â·Ò¢–bW†—7F–æuöw&÷WævWB‚'7FGW2"’ÓÒ&7F—fR# ¢÷væW%ö–BÒW†—7F–æuöw&÷WævWB‚&÷væW%öÆ–æU÷W6W%ö–B"¢÷væW%÷&öf–ÆRÒ7FFRævWB‚'W6W'2"Â·Ò’ævWB†÷væW%ö–BÂ·Ò¢÷væW%÷ÆâÒ÷væW%÷&öf–ÆRævWB‚'Æâ"¢—5ö7F—fRÒ&ööÂ†÷væW%÷&öf–ÆR’æB–EöÖVÖ&W'6†—ö—5ö7F—fR†÷væW%÷&öf–ÆR¢÷væW%ö–æfòÒ°¢&&÷VæB#¢G'VRÀ¢&—5ö÷væW"#¢†Æ–æU÷W6W%ö–BÓÒ÷væW%ö–B’–bÆ–æU÷W6W%ö–BVÇ6RfÇ6RÀ¢&÷væW%ö–B#¢÷væW%ö–BÀ¢&—5ö7F—fR#¢—5ö7F—fRÀ¢&÷væW%÷Æâ#¢÷væW%÷ÆâÀ¢Ğ¢W†6WBW†6WF–öâ2W†3 ¢æÆövvW"æW†6WF–öâ‚&w&÷W÷væW%ö–æfòÆöBf–ÆVC¢W2"ÂW†2¢&WGW&â÷væW%ö–æfğ ¢†æFÆW"æFB„¦ö–äWfVçB¢FVb†æFÆUöw&÷Wö¦ö–â†WfVçB“ ¢""$&÷BŠ*¾˜(˜.{êB(i"[ø^˜ZèŠÛ~{êNjÚ‹øîXÚûÈKˆŞKéŞ‹;Nˆz®X¹^{hZé®h‰X©şûÈ8""" ¢Æ–æU÷W6W%ö–BÒvWFGG"†WfVçBç6÷W&6RÂ'W6W%ö–B"ÂæöæR¢w&÷Wö–BÒvWFGG"†WfVçBç6÷W&6RÂ&w&÷Wö–B"ÂæöæR¢&ööÕö–BÒvWFGG"†WfVçBç6÷W&6RÂ'&ööÕö–B"ÂæöæR¢F&vWEö–BÒw&÷Wö–B÷"&ööÕö–@¢æÆövvW"æ–æfò€¢$¦ö–äWfVçBw&÷WÒW2&ööÓÒW2–çf—FW#ÒW2"À¢†w&÷Wö–B÷"""•³£%ÒÀ¢‡&ööÕö–B÷"""•³£%ÒÀ¢†Æ–æU÷W6W%ö–B÷"""•³£…ÒÀ¢ ¢2¦ö–äWfVçB˜	®[‹k).iÈ’W6W%ö–NûÉ¾KˆŞŠhYºxJk9^ˆz®X¹^{hZé®[h¹.˜jÚ‹øîXÚ¢÷WF6öÖRÂ÷7FGW2Ò²'&WÇ•÷FW‡B#¢.jÚ‹øîXªXZ^ZèŠÛ~{êB"Â'6†÷VÆEöÆVfR#¢fÇ6WÒÂ# ¢–bÆ–æU÷W6W%ö–BæBw&÷Wö–C ¢G'“ ¢÷WF6öÖRÂ÷7FGW2ÒwV&F–åöw&÷Wö¦ö–åö÷WF6öÖR€¢æ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–BÂw&÷Wö–@¢¢W†6WBW†6WF–öâ2W†3 ¢æÆövvW"æW†6WF–öâ‚&wV&F–åöw&÷Wö¦ö–åö÷WF6öÖRf–ÆVC¢W2"ÂW†2¢÷WF6öÖRÂ÷7FGW2Ò²'&WÇ•÷FW‡B#¢.jÚ‹øîXªXZ^ZèŠÛ~{êB"Â'6†÷VÆEöÆVfR#¢fÇ6WÒÂ#  ¢÷væW%ö–æfòÒöÆöEöw&÷Wö÷væW%ö–æfò†w&÷Wö–BÂÆ–æU÷W6W%ö–B¢–çG&õö×6w2ÒöwV&F–åö–çG&õöÖW76vW2†÷væW%ö–æfòÂ÷WF6öÖRævWB‚'&WÇ•÷FW‡B"’–b÷væW%ö–æfòævWB‚&&÷VæB"’VÇ6RæöæR ¢6VçBÒfÇ6P¢G'“ ¢Æ–æUö&÷Eö’ç&WÇ•öÖW76vR†WfVçBç&WÇ•÷Fö¶VâÂ–çG&õö×6w2¢6VçBÒG'VP¢æÆövvW"æ–æfò‚$¦ö–äWfVçB&WÇ’–çG&òö²w&÷WÒW2"Â†w&÷Wö–B÷"""•³£%Ò¢W†6WBW†6WF–öâ2W†3 ¢æÆövvW"æW†6WF–öâ‚$¦ö–äWfVçB&WÇ’–çG&òf–ÆVC¢W2"ÂW†2 ¢–bæ÷B6VçBæBF&vWEö–C ¢G'“ ¢Æ–æUö&÷Eö’çW6…öÖW76vR‡F&vWEö–BÂ–çG&õö×6w2¢æÆövvW"æ–æfò‚$¦ö–äWfVçBW6‚–çG&òö²w&÷WÒW2"Â†w&÷Wö–B÷"""•³£%Ò¢W†6WBW†6WF–öâ2W†3 ¢æÆövvW"æW†6WF–öâ‚$¦ö–äWfVçBW6‚–çG&òf–ÆVC¢W2"ÂW†2 ¢2X8^YÊ{êN[{.Š*¾X[nK¹niÈ>Y:KÙNyJi˜.™º.™h°¢–bw&÷Wö–BæB÷7FGW2ÓÒC“ ¢G'“ ¢Æ–æUö&÷Eö’æÆVfUöw&÷W†w&÷Wö–B¢W†6WBW†6WF–öâ2W†3 ¢æÆövvW"æW†6WF–öâ‚&ÆVfUöw&÷Wf–ÆVC¢W2"ÂW†2 ¢†æFÆW"æFB„föÆÆ÷tWfVçB¢FVb†æFÆUöföÆÆ÷r†WfVçB“ ¢"".XªZ[ŞXø¾jÚ‹øîûÉ®XJ®XXY¹âfÆW‚yÉşZúni«z‹YXşX	’²z¸¾XÛ>™h¾Zx¾ŠŠŞZé¢8""" ¢Æ–æU÷W6W%ö–BÒvWFGG"†WfVçBç6÷W&6RÂ'W6W%ö–B"ÂæöæR¢F—7Æ•öæÖRÒ&W6öÇfU÷vVÆ6öÖUöF—7Æ•öæÖR€¢Æ–æUö&÷Eö“ÖÆ–æUö&÷Eö’À¢FFöf–ÆSÖæ6öæf–u²$DDôd”ÄR%ÒÀ¢Æ–æU÷W6W%ö–CÖÆ–æU÷W6W%ö–BÀ¢ÆövvW#ÖæÆövvW"À¢¢–bÆ–æU÷W6W%ö–C ¢2föÆÆ÷ry[nKˆ¾[Zú¾XZRW6W'>ûÈÎK˜¾[èÎ™h²Ä”dbKˆŞiÈ>Yº{Ë¢&÷rˆÂC@¢G'“ ¢&Vv—7G&F–öå÷&W7VÇBÒ&Vv—7FW%öÆ–æU÷W6W"€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢°¢&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–BÀ¢&F—7Æ•öæÖR#¢F—7Æ•öæÖR÷"""À¢ÒÀ¢¢–b÷&WÇ•öÖ–w&FVEö66÷VçB€¢WfVçBç&WÇ•÷Fö¶VâÂ&Vv—7G&F–öå÷&W7VÇ@¢“ ¢&WGW&à¢&V7F—fFUöÆ–æU÷W6…öf÷%öföÆÆ÷r†æ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–B¢W†6WBW†6WF–öâ2W†3 ¢æÆövvW"æW†6WF–öâ‚$föÆÆ÷tWfVçB&Vv—7FW"f–ÆVC¢W2"ÂW†2¢æÆövvW"æ–æfò€¢$föÆÆ÷tWfVçBvVÆ6öÖRG&–vvW"W6W#ÒW2æÖSÒW""À¢†Æ–æU÷W6W%ö–B÷"""•³£…ÒÀ¢F—7Æ•öæÖR÷"""À¢¢÷6VæE÷vVÆ6öÖR€¢Æ–æUö&÷Eö’À¢&WÇ•÷Fö¶VãÖWfVçBç&WÇ•÷Fö¶VâÀ¢Æ–æU÷W6W%ö–CÖÆ–æU÷W6W%ö–BÀ¢F—7Æ•öæÖSÖF—7Æ•öæÖRÀ¢G&–vvW#Ò&föÆÆ÷r"À¢ ¢†æFÆW"æFB„ÖVÖ&W$¦ö–æVDWfVçB¢FVb†æFÆUöÖVÖ&W%ö¦ö–æVB†WfVçB“ ¢2##bÓrÓ#‰Ún‰2FFVC¢‹h^˜âSK«®Kˆ®™™i˜"ÎŠ¸¾X{®ikh‰Y:¢2##bÓrÓ#C¢h‰Y:˜.{êNK™şŠ9ÎjÚ‹øîûÈş{hZé®hù˜i.ûÈ„¦ö–äWfVçBkÈş˜i˜.y¨NX)hûNûÈ¢2##bÓrÓ#S¢˜.{êNX‹~ik{êNh‰Y:i[ûÉ¾ih~jXØXˆn8Î{êN{XNh‰Y:8×g>8Î[{.{hZé®ZèŠÛ~K«®8Ğ¢–bvWFGG"†WfVçBç6÷W&6RÂ'G—R"ÂæöæR’Ò&w&÷W# ¢&WGW&à¢w&÷Wö–BÒvWFGG"†WfVçBç6÷W&6RÂ&w&÷Wö–B"ÂæöæR¢–bæ÷Bw&÷Wö–C ¢&WGW&à¢G'“ ¢æWuö–G2Ò¶ÒçW6W%ö–Bf÷"Ò–â†WfVçBæ¦ö–æVBæÖVÖ&W'2÷"µÒ’–bvWFGG"†ÒÂ'W6W%ö–B"ÂæöæR•Ğ¢÷væW%ö–æfòÒöÆöEöw&÷Wö÷væW%ö–æfò†w&÷Wö–B¢2[{.{hZé®ZèŠÛ~{êNûÉ®X‹~ik{êN{XNh‰Y:i[[ú¾xZ~ûÈKˆŞ[Û™ûş[{.{hZé®ZèŠÛ~K«®Šˆi[ûÈ¢–b÷væW%ö–æfòævWB‚&&÷VæB"“ ¢G'“ ¢&Vg&W6…öwV&F–åöw&÷WöÖVÖ&W%÷6æ6†÷B€¢æ6öæf–u²$DDôd”ÄR%ÒÂw&÷Wö–@¢¢W†6WBW†6WF–öâ2W†3 ¢æÆövvW"æW†6WF–öâ‚$ÖVÖ&W$¦ö–æVBÖVÖ&W"6æ6†÷B&Vg&W6‚f–ÆVC¢W2"ÂW†2¢2iÊ®{hZé®ûÉ®hêjÚ‹øîXÚûÈÎŠ¸¾zêynY:›¹î8Î{hZé®ZèŠÛ~{êN8Ğ¢2[{.{hZé®ûÉ®{
yúŞjÚ‹øîikh‰Y:ûÈ˜.{êB(šKˆ˜Û^˜(Š¸¾{hZé®ûÈ¢–bæ÷B÷væW%ö–æfòævWB‚&&÷VæB"“ ¢G'“ ¢Æ–æUö&÷Eö’çW6…öÖW76vR€¢w&÷Wö–BÀ¢öwV&F–åö–çG&õöÖW76vW2†÷væW%ö–æfò’À¢¢æÆövvW"æ–æfò€¢$ÖVÖ&W$¦ö–æVBVæ&÷VæB–çG&òW6‚w&÷WÒW2æWsÒW2"À¢w&÷Wö–E³£%ÒÀ¢ÆVâ†æWuö–G2’À¢¢W†6WBW†6WF–öâ2W†3 ¢æÆövvW"æW†6WF–öâ‚$ÖVÖ&W$¦ö–æVB–çG&òW6‚f–ÆVC¢W2"ÂW†2¢VÆ–bæWuö–G3 ¢G'“ ¢–çf—FW%öæÖRÒö÷væW%öF—7Æ•öæÖR†÷væW%ö–æfò¢ÖVÖ&W%ö×6w2ÒµĞ¢–bfÆW…6VæDÖW76vR—2æ÷BæöæRæBwV&F–åöw&÷WöÖVÖ&W%ö¦ö–æVEöfÆW‚—2æ÷BæöæS ¢ÖVÖ&W%ö×6w2æVæB€¢fÆW…6VæDÖW76vR€¢ÇE÷FW‡CÖb.)ÚNûˆòjÚ‹øîXªXZR¶–çf—FW%öæÖWÒy¨NZèŠÛ~{êB"À¢6öçFVçG3ÖwV&F–åöw&÷WöÖVÖ&W%ö¦ö–æVEöfÆW‚†–çf—FW%öæÖR’À¢¢¢VÇ6S ¢ÖVÖ&W%ö×6w2æVæB€¢FW‡E6VæDÖW76vR€¢FW‡CÒ€¢b.)ÚNûˆòjÚ‹øîXªXZR¶–çf—FW%öæÖWÒy¨NZèŠÛ~{êEÆâ ¢.h*[{.XªXZ^8Îjøşiz^[›>Zè8ÔÄ”äRZèŠÛ~{êN8%Æâ ¢.{êNXZ~XúşiKnhù˜i.ûÉ¾ˆº^Šhh‰x+®X¾K«®[{.{hZé®ZèŠÛ~K«®ûÈÂ ¢.Š¸¾Š¸¾[ŞikyJ8ÎKˆ˜Û^˜(Š¸¾8ŞXhŞ{hKˆjÊ8" ¢¢¢¢Æ–æUö&÷Eö’çW6…öÖW76vR†w&÷Wö–BÂÖVÖ&W%ö×6w2¢W†6WBW†6WF–öâ2W†3 ¢æÆövvW"æW†6WF–öâ‚$ÖVÖ&W$¦ö–æVBvVÆ6öÖRfÆW‚f–ÆVC¢W2"ÂW†2 ¢&W7VÇBÂ6öFRÒVæf÷&6Uöw&÷WöÖVÖ&W%öÆ–Ö—B†w&÷Wö–BÂF–7B†æ6öæf–r’¢–b6öFRÒ#÷"æ÷B&W7VÇBævWB‚&Væf÷&6VB"“ ¢&WGW&à¢×6uöÆ–æW2Ò°¢b.)ªûˆòZèŠÛ~{êN‹h^˜â´u$õUôÔTÔ$U%ôÄ”Ô•GÒK«®Kˆ®™™8""À¢b.yºîX˜Şh‰Y:i[ƒ§·&W7VÇBævWB‚v7W'&VçEö6÷VçBr—Ò÷´u$õUôÔTÔ$U%ôÄ”Ô•GÒ"À¢Ğ¢–b&W7VÇBævWB‚&¶–6¶VB"“ ¢×6uöÆ–æW2æVæB†b.[{.Š¸¾X{¢¶ÆVâ‡&W7VÇE²v¶–6¶VBuÒ—ÒKØŞikh‰Y:8""¢–b&W7VÇBævWB‚&&÷Eöæ÷EöFÖ–åö6÷VçB"“ ¢×6uöÆ–æW2æVæB€¢b.)ªûˆò8Îjøşiz^[›>Zè8ŞyºîX˜ŞxJk9^Š¸¾X{®‹h^šŞh‰Y:ûÈXúniÈ’·&W7VÇE²v&÷Eöæ÷EöFÖ–åö6÷VçBu×ÒKØŞûÈ8" ¢.Š¸¾zêynY:h˜¾X¹^˜X{®‹h^šŞh‰Y:ûÈÎh‰n[ø^Šhi˜.h¨®8Îjøşiz^[›>Zè8ŞŠŠŞx+®{êN{XNzêynY:[èÎXhŞŠšn8" ¢¢–b&W7VÇBævWB‚&f–ÆVB"’æBæ÷B&W7VÇBævWB‚&&÷Eöæ÷EöFÖ–åö6÷VçB"“ ¢×6uöÆ–æW2æVæB†b.Š¸¾X{®ZKiYs§¶ÆVâ‡&W7VÇE²vf–ÆVBuÒ—ÒKØŞ8""¢2X8^YÊ‚&÷BxJzêynY:jÈ®™™8yÉşy¨N‹Š.K«®ZKiY~i˜.h˜ŞhùzK®ûÉ¾XØ~{I®ûÈş{hZé®[èÎKÛşyJˆ^[{.ˆz®X¹^iŠşZèŠÛ~{êNzêynY:¢–b&W7VÇBævWB‚&&÷Eöæ÷EöFÖ–åö6÷VçB"“ ¢×6uöÆ–æW2æVæB‚/	ù*ˆº^™ÈŠ¸¾X{®‹h^šŞh‰Y:ûÈÎXúşYÊ{êNŠ:h™>8ÎzêynY:ŠŠŞZé®8ŞyÈ¾iYZÛûÈ™Ùî[ø^Šh™h¾˜	®jÚ^š™şûÈ’"¢Æ–æUö&÷Eö’çW6…öÖW76vR†w&÷Wö–BÂFW‡E6VæDÖW76vR‡FW‡CÒ%Æâ"æ¦ö–â†×6uöÆ–æW2’’¢W†6WBW†6WF–öã ¢70 ¢–b÷7F&6´WfVçB—2æ÷BæöæS ¢†æFÆW"æFB…÷7F&6´WfVçB¢FVb†æFÆU÷÷7F&6²†WfVçB“ ¢Æ–æU÷W6W%ö–BÒvWFGG"†WfVçBç6÷W&6RÂ'W6W%ö–B"ÂæöæR¢FFÒ" ¢G'“ ¢FFÒ7G"†vWFGG"†WfVçBç÷7F&6²Â&FF"Â""’÷"""¢W†6WBW†6WF–öã ¢FFÒ" ¢–bæ÷BÆ–æU÷W6W%ö–B÷"æ÷BFF ¢&WGW&à¢&WÇ’ÒæöæP¢2jøşiz^hêi*Ş8Îh‰[›>Zè8ŞûÉ®YÊ‚Ä”äRXZ~›¹î˜XÛ>Zú¾XZ^{ŞX‹ûÈˆˆrÄ”dbYÎKˆZYr&V6÷&Eö6†V6¶–îûÈ¢–b—5ö6†V6¶–å÷÷7F&6²†FF“ ¢&WÇ’Ò†æFÆUö6†V6¶–å÷÷7F&6²†æ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–BÂæ6öæf–r¢VÆ–b—5öW‡—'•ö÷Eö÷WE÷÷7F&6²†FF“ ¢&WÇ’Ò†æFÆUöW‡—'•ö÷Eö÷WE÷÷7F&6²†æ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–B¢VÆ–bFFç7F'G7v—F‚‚&&WFöfVVF&6³¢"“ ¢&WÇ’Ò†æFÆUö&WFöfVVF&6µ÷÷7F&6²€¢æ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–BÂFF¢¢VÆ–bFFç7F'G7v—F‚‚'6÷3¢"“ ¢'G2ÒFFç7Æ—B‚#¢"Â"¢–bÆVâ‡'G2’ÓÒ3 ¢&W7VÇBÂ7FGW5ö6öFRÒ&W7öæE÷Fõ÷6÷5öWfVçB€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢°¢&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–BÀ¢&7F–öâ#¢'G5³ÒÀ¢&WfVçEö–B#¢'G5³%ÒÀ¢ÒÀ¢æ6öæf–rÀ¢¢–b7FGW5ö6öFRÓÒ# ¢&öÆU÷FW‡BÒ€¢.[{.h›îX‹iÊÎK«®ûÈÎiÊÎjÊ4õ2[{.{YiÙò ¢–b&W7VÇBævWB‚'7FGW2"’ÓÒ&f÷VæEö6Æ÷6VB ¢VÇ6R.yºîX˜Ş[	®xJZèŠÛ~K«®hê^h˜¾ûÈÎ[{.XhŞjÊhù˜i.h˜iÈK«¢ ¢–b&W7VÇBævWB‚&æõ÷&W7öæFW""¢VÇ6R.[{.Š‰˜ÈN8ÎŠ¸¾X[nK¹nK«®ˆş{š¾8ŞûÈÎKÚK¸ŞXúşiú^yÈ¾[èÎ{¨Îx¸hX² ¢–b'G5³ÒÓÒ&FVfW" ¢VÇ6R.[{.Š‰˜ÈNKÚyºîX˜ŞxJk9^‰™^ynûÈÎKˆŞXhŞhù˜i.KÚ ¢–b'G5³ÒÓÒ'Væ&ÆR ¢VÇ6P¢.KÚiŠşK‹¾Šhhê^h˜¾K«¢ ¢–b&W7VÇBævWB‚'&öÆR"’ÓÒ'&–Ö'’ ¢VÇ6R.[{.iÈZèŠÛ~K«®XXhê^h˜¾ûÈÎKÚ[{.XªXZ^XÙNXª’ ¢–b&W7VÇBævWB‚'&öÆR"’ÓÒ&76—7FçB ¢VÇ6R.[{.Š‰˜ÈNKÚy¨NY¹îhx’ ¢¢&WÇ’Òb.)ÈR·&öÆU÷FW‡GÒ ¢VÇ6S ¢&WÇ’Ò.˜	zØb4õ2xJk9^i»NikûÈÎXúşˆ;Ş[{.{Yjh‰nKÚKˆŞiŠşiÊÎjÊiKnK»nK«¢ ¢VÆ–bFFç7F'G7v—F‚‚'6Ö'C¢"“ ¢&WÇ’Ò†æFÆU÷6Ö'E÷&VÖ–æFW%÷÷7F&6²€¢æ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–BÂFFÂæ6öæf–p¢¢VÇ6S ¢2y»Zëˆˆ®x˜XùnkhŠÚnZ÷7F&6¾ûÉ®K™şŠinx+®K¸®iz^Z[›>Zè¢G'“ ¢g&öÒÆW'G2ç÷7F&6²–×÷'B—5öÆW'Eö6æ6VÅ÷÷7F&6°¢–b—5öÆW'Eö6æ6VÅ÷÷7F&6²†FF“ ¢&WÇ’Ò†æFÆUö6†V6¶–å÷÷7F&6²€¢æ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–BÂæ6öæf–p¢¢W†6WBW†6WF–öã ¢&WÇ’ÒæöæP¢–b&WÇ“ ¢—FV×2Òæ÷&ÖÆ—¦UöÆ–æU÷&WÇ•ö—FV×2‡&WÇ’¢ÖW76vW2ÒµĞ¢f÷"—FVÒ–â—FV×3 ¢–b—6–ç7Fæ6R†—FVÒÂF–7B’æB—FVÒævWB‚'G—R"’ÓÒ&fÆW‚# ¢–bfÆW…6VæDÖW76vR—2æöæS ¢ÖW76vW2æVæB€¢FW‡E6VæDÖW76vR€¢FW‡C×7G"†—FVÒævWB‚&ÇEFW‡B"’÷".jøşiz^[›>Zè’"¢¢¢VÇ6S ¢ÖW76vW2æVæB€¢fÆW…6VæDÖW76vR€¢ÇE÷FW‡C×7G"†—FVÒævWB‚&ÇEFW‡B"’÷".jøşiz^[›>Zè’"•³£CÒÀ¢6öçFVçG3Ö—FVÒævWB‚&6öçFVçG2"’÷"·ÒÀ¢¢¢VÇ6S ¢ÖW76vW2æVæB…FW‡E6VæDÖW76vR‡FW‡C×7G"†—FVÒ’’¢–bÖW76vW3 ¢Æ–æUö&÷Eö’ç&WÇ•öÖW76vR†WfVçBç&WÇ•÷Fö¶VâÂÖW76vW2 ¢†æFÆW"æFB„ÖW76vTWfVçBÂÖW76vSÕFW‡DÖW76vR¢FVb†æFÆU÷FW‡EöÖW76vR†WfVçB“ ¢FW‡BÒWfVçBæÖW76vRçFW‡@¢Æ–æU÷W6W%ö–BÒvWFGG"†WfVçBç6÷W&6RÂ'W6W%ö–B"ÂæöæR¢w&÷Wö–BÒvWFGG"†WfVçBç6÷W&6RÂ&w&÷Wö–B"ÂæöæR¢7G&—VBÒFW‡Bç7G&—‚ ¢2jÚ‹øîŠ™î™yÎ˜Û^ZÙ~ûÈ[{.iŠşZ[ŞXø¾K™şXúş˜xŞh»şjÚ‹øîXÚûÉ¾KˆŞ™ÈXùnkhZ[ŞXø¾ûÈ¢2{IN™yÎ˜Û^ZÙ~h‰n8Î™h¾Zx¾ûÈ8ŞzØj‰›¹îK™şXúşŠ{y›ÎûÈÎ˜şXXÒôh™>h¹¾YÎˆˆ®Šˆ®˜
h‰ŠªNiÈ0¢vVÆ6öÖUö¶W—2Ò‚.™h¾Zx²"Â.jÚ‹øâ"Â.Šª®iˆâ"Â.jÚ‹øîŠ™â"¢–b7G&—VB–âvVÆ6öÖUö¶W—2÷"7G&—VBç'7G&—‚.ûÈ8"çîûÙâ"’–âvVÆ6öÖUö¶W—3 ¢æÆövvW"æ–æfò€¢'vVÆ6öÖR¶W—v÷&B†—BFW‡CÒW"W6W#ÒW2"À¢7G&—VE³£#ÒÀ¢†Æ–æU÷W6W%ö–B÷"""•³£…ÒÀ¢¢F—7Æ•öæÖRÒ&W6öÇfU÷vVÆ6öÖUöF—7Æ•öæÖR€¢Æ–æUö&÷Eö“ÖÆ–æUö&÷Eö’À¢FFöf–ÆSÖæ6öæf–u²$DDôd”ÄR%ÒÀ¢Æ–æU÷W6W%ö–CÖÆ–æU÷W6W%ö–BÀ¢ÆövvW#ÖæÆövvW"À¢¢–bÆ–æU÷W6W%ö–C ¢G'“ ¢&Vv—7G&F–öå÷&W7VÇBÒ&Vv—7FW%öÆ–æU÷W6W"€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢°¢&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–BÀ¢&F—7Æ•öæÖR#¢F—7Æ•öæÖR÷"$Ä”äRKÛşyJˆR"À¢ÒÀ¢¢–b÷&WÇ•öÖ–w&FVEö66÷VçB€¢WfVçBç&WÇ•÷Fö¶VâÂ&Vv—7G&F–öå÷&W7VÇ@¢“ ¢&WGW&à¢W†6WBW†6WF–öâ2W†3 ¢æÆövvW"æW†6WF–öâ‚'vVÆ6öÖR¶W—v÷&B&Vv—7FW"f–ÆVC¢W2"ÂW†2¢÷6VæE÷vVÆ6öÖR€¢Æ–æUö&÷Eö’À¢&WÇ•÷Fö¶VãÖWfVçBç&WÇ•÷Fö¶VâÀ¢Æ–æU÷W6W%ö–CÖÆ–æU÷W6W%ö–BÀ¢F—7Æ•öæÖSÖF—7Æ•öæÖRÀ¢G&–vvW#Öb&¶W—v÷&C§·7G&—VE³£#×Ò"À¢¢&WGW&à ¢2Kˆ˜Û^˜(Š¸¾ûÉ®yZ^˜âÄ”dbZJ~hÈ˜‰^š(i"Y¹âfÆW‚U$ûÈ†Æ–æRæÖRõ"÷6†&^ûÈy»Nhê^™h¾Z[ŞXø¾˜i8p¢–b7G&—VB–â‚.Kˆ˜Û^˜(Š¸²"Â.Kˆ˜Û^˜(Š¸¾ZèŠÛ~K«¢"Â.˜(Š¸¾ZèŠÛ~K«¢"“ ¢–bæ÷BÆ–æU÷W6W%ö–C ¢Æ–æUö&÷Eö’ç&WÇ•öÖW76vR€¢WfVçBç&WÇ•÷Fö¶VâÀ¢FW‡E6VæDÖW76vR‡FW‡CÒ.Š¸¾XXXª8Îjøşiz^[›>Zè8Şx+®Z[ŞXø¾ûÈÎXhŞ›¹îKˆ˜Û^˜(Š¸¾8""’À¢¢&WGW&à¢G'“ ¢&Vv—7G&F–öå÷&W7VÇBÒ&Vv—7FW%öÆ–æU÷W6W"€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢²&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–BÂ&F—7Æ•öæÖR#¢$Ä”äRKÛşyJˆR'ÒÀ¢¢–b÷&WÇ•öÖ–w&FVEö66÷VçB€¢WfVçBç&WÇ•÷Fö¶VâÂ&Vv—7G&F–öå÷&W7VÇ@¢“ ¢&WGW&à¢W†6WBW†6WF–öâ2W†3 ¢æÆövvW"æW†6WF–öâ‚&–çf—FR¶W—v÷&B&Vv—7FW"f–ÆVC¢W2"ÂW†2¢–bfÆW…6VæDÖW76vR—2æ÷BæöæRæB6†&Uö–çf—FUöfÆW‚—2æ÷BæöæS ¢fÆW‚Ò6†&Uö–çf—FUöfÆW‚†Æ–æU÷W6W%ö–B¢Æ–æUö&÷Eö’ç&WÇ•öÖW76vR€¢WfVçBç&WÇ•÷Fö¶VâÀ¢fÆW…6VæDÖW76vR†ÇE÷FW‡CÒ.˜(Š¸¾ZënK«®y[nZèŠÛ~K«®ûÙÎ›¹îi8®X+>{ZnZënK«¢"Â6öçFVçG3ÖfÆW‚’À¢¢&WGW&à¢2fÆÆ&6¾ûÉ®{INih~ZÙ~™˜NKˆ®XéşyIşXˆnKª¾{k.YØ ¢–bwV&F–åö–çf—FU÷6†&U÷FW‡B—2æ÷BæöæRæBÆ–æUöæF—fU÷6†&U÷W&Â—2æ÷BæöæS ¢6†&U÷FW‡BÒwV&F–åö–çf—FU÷6†&U÷FW‡B†Æ–æU÷W6W%ö–B¢6†&U÷W&’ÒÆ–æUöæF—fU÷6†&U÷W&Â‡6†&U÷FW‡B¢Æ–æUö&÷Eö’ç&WÇ•öÖW76vR€¢WfVçBç&WÇ•÷Fö¶VâÀ¢FW‡E6VæDÖW76vR€¢FW‡CÒ€¢.Š¸¾›¹î™h¾Kˆ¾™Ú.˜
>{YûÈÎ˜KˆKØŞZënK«®X+>˜˜(Š¸¾ûÉ¥Æâ ¢b'·6†&U÷W&—Ò ¢¢’À¢¢&WGW&à¢6†&U÷vRÒ€¢6†&Uö–çf—FUöÆ–fe÷W&Â‚¢–b6†&Uö–çf—FUöÆ–fe÷W&À¢VÇ6R&‡GG3¢òöÆ–fbæÆ–æRæÖRó#ƒCƒ33ÕT—”BöÆ–fb÷6†&RÖ–çf—FRæ‡FÖÂ ¢¢Æ–æUö&÷Eö’ç&WÇ•öÖW76vR€¢WfVçBç&WÇ•÷Fö¶VâÀ¢FW‡E6VæDÖW76vR‡FW‡CÖb.Š¸¾™h¾YYş˜(Š¸¾šXˆnKª¾{ZnZënK«®ûÉ¥Æç·6†&U÷vWÒ"’À¢¢&WGW&à ¢2™ÈŠh[š¾[ùûÈş{x®h
^k.XªûÉ®ˆ®ZJZêNXú®Y¹î{[KˆÄ”dbXZ^Xú0¢–b6÷5öfÆ÷r—2æ÷BæöæRæB7G&—VB–â€¢.™ÈŠh[š¾[ù’"À¢%4õ2"À¢'6÷2"À¢.{x®h
^k.Xª’"À¢.˜	®yú^ZënK«¢"À¢.ˆş{ZZënK«®˜
>hÈ“>jÊ"À¢.™ÈŠh[š¾[ùz+®Š¨Ò"À¢%4õ2z+®Š¨Ò""À¢%4õ2z+®Š¨Ò2"À¢%4õ2Xùnkh‚"À¢.Xùnkh™ÈŠh[š¾[ù’"À¢“ ¢÷6÷5ö†æFÆR€¢Æ–æUö&÷Eö’À¢Æ–æU÷W6W%ö–BÀ¢7G&—VBÀ¢&WÇ•÷Fö¶VãÖWfVçBç&WÇ•÷Fö¶VâÀ¢w&÷Wö–CÖw&÷Wö–BÀ¢¢&WGW&à ¢2##bÓrÓ#F6‚s¢$õBx¸hX¾iú^Šš"„DÒ²{êN{XN˜;ŞXúşyJ‚¢–b7G&—VB–â‚$$õBx¸hX²"Â&&÷Bx¸hX²"Â.j™şYšK«®x¸hX²"Â.j™şYšK«®x¸k8"“ ¢7FFRÒÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò¢w&÷W2Ò7FFRævWB‚&wV&F–åöw&÷W2"Â·Ò¢7F—fUöw&÷W2Ò7VÒƒf÷"r–âw&÷W2çfÇVW2‚’–brævWB‚'7FGW2"’ÓÒ&7F—fR"¢WF–ÖU÷6V2Ò†FFWF–ÖRææ÷r‚’Òå÷7F'E÷F–ÖR’çF÷FÅ÷6V6öæG2‚¢†÷W'2Ò–çB‡WF–ÖU÷6V2òò3c¢Ö–çWFW2Ò–çB‚‡WF–ÖU÷6V2R3c’òòc¢7FGW5÷FW‡BÒ€¢b/	úIbh‰iŠş8Îjøşiz^[›>Zè8ÕÅÆâ ¢b.[ÎikÎ8Îjøşiz^[›>Zè8Ş˜	X¾iÈŞX¹•ÅÆåÅÆâ ¢b.)ÈRyºîX˜ŞYYşyJKŠÒ[{.˜
>{¨Â¶†÷W'7Ò[şi˜"¶Ö–çWFW7ÒXˆb•ÅÆâ ¢b/	ùR[{.Š‹¾Xh®K«®i[ƒ§¶ÆVâ‡7FFRævWB‚wW6W'2rÂ·Ò’—ÕÅÆâ ¢b/	ùºûˆòZèŠÛ~{êC§¶7F—fUöw&÷W7Ò{êNiÈiX{hZé¥ÅÆåÅÆâ ¢b/	ùJrXúşyJhÈ~KºBzxŠˆ¢“¥ÅÆâ ¢b.(
"{ŞX‹òZ[›>Zè•ÅÆâ ¢b.(
"{hZé®ZèŠÛ~K«¥ÅÆâ ¢b.(
"iú^yÈ¾ikj‚òh‰y¨Nx¸hXµÅÆåÅÆâ ¢b/	ùR{êN{XNhÈ~KºC®ZèŠÛ~{êNx¸hX²ò{hZé®ZèŠÛ~{êBòKÛşyJŠª®iˆâ ¢¢Æ–æUö&÷Eö’ç&WÇ•öÖW76vR†WfVçBç&WÇ•÷Fö¶VâÂFW‡E6VæDÖW76vR‡FW‡C×7FGW5÷FW‡B’¢&WGW&à ¢2##bÓrÓ#F6‚¢ZèŠÛ~{êNy»™yÂBX²fÆW‚hÈ~KºB{êN{XN™™Zé¢¢–bw&÷Wö–C ¢2’{hZé®ZèŠÛ~{êBKùŞyYˆˆ®hÈ~KºBÆ–2¢–b7G&—VB–â‚.›¹îh‰{hZé®ZèŠÛ~{êB"Â.{hZé®ZèŠÛ~{êB"Â.{hZé®[›>ZèZèŠÛ~Xªyb"“ ¢&W7VÇBÂ6öFRÒ&–æEöwV&F–åöw&÷W€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢²&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–BÂ&w&÷Wö–B#¢w&÷Wö–GÒÀ¢¢–bfÆW…6VæDÖW76vR—2æ÷BæöæRæBwV&F–åöw&÷Wö&–æEö6öæf—&ÕöfÆW‚—2æ÷BæöæS ¢–b6öFRÓÒ# ¢Vç&–6†VBÒöVç&–6…ö&–æE÷&W7VÇEöf÷%öfÆW‚‡&W7VÇBÂÆ–æU÷W6W%ö–B¢7V66W75ö×6w2Ò°¢fÆW…6VæDÖW76vR€¢ÇE÷FW‡CÒ/	ù8²ZèŠÛ~{êN‹8~Šˆ¢"À¢6öçFVçG3ÖwV&F–åöw&÷Wö&–æEö6öæf—&ÕöfÆW‚†Vç&–6†VB’À¢¢Ğ¢2{hZé®h‰X©ş[èÎKˆŞŠhXÎYÊ‹8~Šˆ®XÚûÉ®XhÒçVFvRZèÎh‰ZèŠÛ~K«®ûÈşhù˜i.ŠŠŞZé ¢–bæ÷B&W7VÇBævWB‚&Ç&VG•ö&÷VæB"“ ¢çVFvRÒ€¢wV&F–åöw&÷W÷6WGWöçVFvU÷FW‡B€¢Vç&–6†VBævWB‚&wV&F–åö6÷VçB"Â’À¢Vç&–6†VBævWB‚&wV&F–åöÆ–Ö—B"ÂR’À¢Vç&–6†VBævWB‚&VÖW&vVæ7•ö6÷VçB"Â’À¢Vç&–6†VBævWB‚&VÖW&vVæ7•öÆ–Ö—B"Â"’À¢¢–bwV&F–åöw&÷W÷6WGWöçVFvU÷FW‡B—2æ÷BæöæP¢VÇ6R€¢/	øè’ZèŠÛ~{êN[{.[»®z¸¾h‰X©şûÈÆâ ¢.[»®ŠÛXhŞZèÎh‰ûÉ®ikZ)îj[ø>ZèŠÛ~K«®8{x®h
^ˆş{ZK«®8ŠŠŞZé®jøşiz^hù˜i.i˜.™i>8" ¢¢¢7V66W75ö×6w2æVæB…FW‡E6VæDÖW76vR‡FW‡CÖçVFvR’¢Æ–æUö&÷Eö’ç&WÇ•öÖW76vR†WfVçBç&WÇ•÷Fö¶VâÂ7V66W75ö×6w2¢VÇ6S ¢&V6öâÒ&W7VÇBævWB€¢'&WÇ•÷FW‡B"À¢.˜	X¾{êN{XNyºîX˜ŞxJk9^YYşyJZèŠÛ~X©şˆ;ÒÎŠ¸¾jª.iúRs“’Šˆ.™kx¸hX¾h‰nyKXéş[»®z¸¾ˆ^i8ŞKÙÂ"À¢¢Æ–æUö&÷Eö’ç&WÇ•öÖW76vR€¢WfVçBç&WÇ•÷Fö¶VâÀ¢fÆW…6VæDÖW76vR€¢ÇE÷FW‡CÒ.)ØÂxJk9^{hZé®jÚN{êB"À¢6öçFVçG3ÖwV&F–åöw&÷Wö&–æEöf–ÅöfÆW‚‡&V6öâ’À¢’À¢¢VÇ6S ¢2fÆÆ&6²{INih~ZÙ~ûÉ®h‰X©şY¹îŠhnY»®Zé®8Îh‰[{.ZèÎh‰ZèŠÛ~{êNŠŠŞZé®8Ğ¢–b6öFRÓÒ# ¢&WÇ•÷FW‡BÒ€¢.h‰[{.ZèÎh‰ZèŠÛ~{êNŠŠŞZé¥Æâ ¢b.yºîX˜Ş[{.{hZé¢·&W7VÇBævWB‚vwV&F–åöw&÷Wö6÷VçBrÂ—Òò ¢b'·&W7VÇBævWB‚vwV&F–åöw&÷WöÆ–Ö—BrÂ2—ÒX¾{êN{XN8" ¢¢–bæ÷B&W7VÇBævWB‚&Ç&VG•ö&÷VæB"’æBwV&F–åöw&÷W÷6WGWöçVFvU÷FW‡B—2æ÷BæöæS ¢Vç&–6†VBÒöVç&–6…ö&–æE÷&W7VÇEöf÷%öfÆW‚‡&W7VÇBÂÆ–æU÷W6W%ö–B¢&WÇ•÷FW‡BÒ€¢&WÇ•÷FW‡@¢²%ÆåÆâ ¢²wV&F–åöw&÷W÷6WGWöçVFvU÷FW‡B€¢Vç&–6†VBævWB‚&wV&F–åö6÷VçB"Â’À¢Vç&–6†VBævWB‚&wV&F–åöÆ–Ö—B"ÂR’À¢Vç&–6†VBævWB‚&VÖW&vVæ7•ö6÷VçB"Â’À¢Vç&–6†VBævWB‚&VÖW&vVæ7•öÆ–Ö—B"Â"’À¢¢¢VÆ–b&W7VÇBævWB‚'6†÷VÆEöÆVfR"“ ¢&WÇ•÷FW‡BÒ€¢.˜	X¾{êN{XNyºîX˜ŞxJk9^YYşyJZèŠÛ~X©şˆ;Ş8.ZèŠÛ~{êN™™iÈiXy¨Bs“’iÈ‹+¾h‰n[›N‹+¾iÈ>Y:[»®z¸¾ûÉ¾iÈ‹+¾iÈZI¢{êNûÈÎ[›N‹+¾iÈZI¢2{êN8%Æâ ¢.Š¸¾XXZèÎh‰XØ~{I®ûÈÎXhŞ˜xŞik˜(Š¸¾8Îjøşiz^[›>Zè8ŞûÉ¾h‰xûîYÊiÈ>˜X{®{êN{XN8" ¢¢VÇ6S ¢&WÇ•÷FW‡BÒ.˜	X¾{êN{XN[{.{hZé®X[nK¹niÈ>Y:ûÈÎŠ¸¾yKXéş[»®z¸¾ˆ^zêynZèŠÛ~ŠŠŞZé®8" ¢Æ–æUö&÷Eö’ç&WÇ•öÖW76vR†WfVçBç&WÇ•÷Fö¶VâÂFW‡E6VæDÖW76vR‡FW‡C×&WÇ•÷FW‡B’¢–b&W7VÇBævWB‚'6†÷VÆEöÆVfR"“ ¢Æ–æUö&÷Eö’æÆVfUöw&÷W†w&÷Wö–B¢&WGW&à ¢2"’ZèŠÛ~{êNx¸hX¾ûÈY
¾8Îiú^yÈ¾ZèŠÛ~{êNûÈşiú^yÈ¾ZèŠÛ~{êNx¸hX¾8ŞhÈ˜‰^XŠ^YŞûÈ¢–b7G&—VB–â‚.ZèŠÛ~{êNx¸hX²"Â.{êNx¸hX²"Â.x¸hX²"Â.iú^yÈ¾ZèŠÛ~{êB"Â.iú^yÈ¾ZèŠÛ~{êNx¸hX²"“ ¢2iú^Šš.X˜ŞXXX‹~ikiÊÎ{êNh‰Y:i[ûÈÎ˜şXXŞK¸ŞšşzK®{hZé®y[nKˆ¾y¨Nˆˆ®[ú¾xZp¢G'“ ¢&Vg&W6…öwV&F–åöw&÷WöÖVÖ&W%÷6æ6†÷B€¢æ6öæf–u²$DDôd”ÄR%ÒÂw&÷Wö–@¢¢W†6WBW†6WF–öâ2W†3 ¢æÆövvW"æW†6WF–öâ‚'7FGW2ÖVÖ&W"6æ6†÷B&Vg&W6‚f–ÆVC¢W2"ÂW†2¢7FFRÒÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò¢&öf–ÆRÒvWE÷&öf–ÆR‡7FFRÂÆ–æU÷W6W%ö–B’÷"·Ğ¢–bfÆW…6VæDÖW76vR—2æ÷BæöæRæBwV&F–åöw&÷W÷7FGW5öfÆW‚—2æ÷BæöæS ¢Æ–æUö&÷Eö’ç&WÇ•öÖW76vR€¢WfVçBç&WÇ•÷Fö¶VâÀ¢fÆW…6VæDÖW76vR€¢ÇE÷FW‡CÒ.ZèŠÛ~{êNx¸hX¾ûÈ{êN{XNh‰Y:i[ûÈ’"À¢6öçFVçG3ÖwV&F–åöw&÷W÷7FGW5öfÆW‚‡&öf–ÆRÂ7FFR’À¢’À¢¢VÇ6S ¢&WÇ•÷FW‡BÒb.ZèŠÛ~{êNi[˜xşûÉ§¶ÆVâ‡&öf–ÆRævWB‚vwV&F–åöw&÷Wö–G2r’÷"µÒ—Ò ¢Æ–æUö&÷Eö’ç&WÇ•öÖW76vR†WfVçBç&WÇ•÷Fö¶VâÂFW‡E6VæDÖW76vR‡FW‡C×&WÇ•÷FW‡B’¢&WGW&à ¢2"Ó’K¸®iz^[›>ZèYŞYjîûÉ®Xú®iÈ{êN{XN[»®z¸¾ˆRşzêynY:XúşyÈ¾Š›>{K‹8~ii¢–b7G&—VB–âD”Å•õ$õ5DU%ô´U•tõ$E3 ¢&WÇ•÷FW‡BÂ÷7FGW2ÒwV&F–åöw&÷WöF–Ç•÷7FGW5÷FW‡B€¢æ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–BÂw&÷Wö–@¢¢Æ–æUö&÷Eö’ç&WÇ•öÖW76vR†WfVçBç&WÇ•÷Fö¶VâÂFW‡E6VæDÖW76vR‡FW‡C×&WÇ•÷FW‡B’¢&WGW&à ¢22’KÛşyJŠª®iˆâòKÛşyJˆ^Šª®iˆà¢–b7G&—VB–â‚.KÛşyJŠª®iˆâ"Â.KÛşyJˆ^Šª®iˆâ"Â.iYZÛ‚"Â.hî›«ÎyJ‚"“ ¢–bfÆW…6VæDÖW76vR—2æ÷BæöæRæBwV&F–åöw&÷W÷W6W%öwV–FUöfÆW‚—2æ÷BæöæS ¢Æ–æUö&÷Eö’ç&WÇ•öÖW76vR€¢WfVçBç&WÇ•÷Fö¶VâÀ¢fÆW…6VæDÖW76vR€¢ÇE÷FW‡CÒ/	ù9bZèŠÛ~{êNKÛşyJŠª®iˆâ"À¢6öçFVçG3ÖwV&F–åöw&÷W÷W6W%öwV–FUöfÆW‚‚’À¢’À¢¢VÇ6S ¢Æ–æUö&÷Eö’ç&WÇ•öÖW76vR€¢WfVçBç&WÇ•÷Fö¶VâÀ¢FW‡E6VæDÖW76vR‡FW‡CÒ.KÛşyJŠª®iˆã£îXØ~{I¢s“’(i""î[»®{êB(i"2î˜(8Îjøşiz^[›>Zè8Ş˜.{êB(i"Bî›¹î8Î{hZé®ZèŠÛ~{êN8ŞûÈXØ~{I®ûÈş{hZé®[èÎˆz®X¹^h‰x+®ZèŠÛ~{êNzêynY:ûÈ’"’À¢¢&WGW&à ¢2B’zêynY:ŠŠŞZé¢òhî›«ÎŠŠŞzêynY:ò{êN{XNŠŠŞZé ¢–b7G&—VB–â‚.zêynY:ŠŠŞZé¢"Â.ŠŠŞzêynY:"Â.hî›«ÎŠŠŞzêynY:"Â#njÚ^š™ò"Â.{êN{XNŠŠŞZé¢"“ ¢–bfÆW…6VæDÖW76vR—2æ÷BæöæRæBwV&F–åöw&÷WöFÖ–å÷6WGWöfÆW‚—2æ÷BæöæS ¢Æ–æUö&÷Eö’ç&WÇ•öÖW76vR€¢WfVçBç&WÇ•÷Fö¶VâÀ¢fÆW…6VæDÖW76vR€¢ÇE÷FW‡CÒ.)©ûˆòŠŠŞZé®8Îjøşiz^[›>Zè8Şx+®zêynY:bjÚ^š™ò"À¢6öçFVçG3ÖwV&F–åöw&÷WöFÖ–å÷6WGWöfÆW‚‚’À¢’À¢¢VÇ6S ¢Æ–æUö&÷Eö’ç&WÇ•öÖW76vR€¢WfVçBç&WÇ•÷Fö¶VâÀ¢FW‡E6VæDÖW76vR‡FW‡CÒ.zêynY:ŠŠŞZé¢bjÚ^š™ó£î{êNXû>Kˆ®8Î(š8Ş(i""î˜h‰Y:(i"2î™[~hÈ8Îjøşiz^[›>Zè8Ò(i"BîŠŠŞx+®zêynY:(i"Rîz+®Zé¢(i"bîZèÎh‰"’À¢¢&WGW&à ¢2iÊ®zÊnYKˆ®‹ûiˆîz+®hÈ~KºNûÉ®{êNˆ®KùŞhÈZè™ÙÎûÈÎ˜şXXŞh™>i;îZënK«®[ŞŠ›8 ¢2Ä”äRô[èÎXûy¨Nˆz®X¹^Y¹îhxK™şhx™yÎ™hûÈÎY
nX˜~K¸ŞXúşˆ;ŞyK[èÎXûXúnZInY¹îih~ZÙ~8 ¢–bw&÷Wö–C ¢&WGW&à ¢2zxŠˆ®ûÉ®zêynY:Xúşiú^8ÎK¸®ZJŠ«˜(Nk).Z[›>Zè8ŞûÈKˆŞ™È™h¾{êN{XNhù˜i.ûÈ¢–bæ÷Bw&÷Wö–BæB7G&—VB–âD”Å•õ$õ5DU%ô´U•tõ$E3 ¢&WÇ•÷FW‡BÂ÷7FGW2Ò÷væW%÷FöF•÷6fWG•÷&÷7FW%÷FW‡B€¢æ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–BÂ6öæf–sÖæ6öæf–p¢¢Æ–æUö&÷Eö’ç&WÇ•öÖW76vR†WfVçBç&WÇ•÷Fö¶VâÂFW‡E6VæDÖW76vR‡FW‡C×&WÇ•÷FW‡B’¢&WGW&à ¢7FGW2ÒæöæP¢–bç’†¶W—v÷&B–âFW‡Bf÷"¶W—v÷&B–â4„T4´”åô´U•tõ$E2“ ¢7FGW2Ò&V6÷&Eö6†V6¶–â€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢²&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–GÒÀ¢6öæf–sÖæ6öæf–rÀ¢¢&WÇ•ö—FV×2Òæ÷&ÖÆ—¦UöÆ–æU÷&WÇ•ö—FV×2€¢'V–ÆEö6†V6¶–å÷7V66W75÷FW‡B‡7FGW2Â6öæf–sÖæ6öæf–r¢¢7FFRÒÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò¢&öf–ÆRÒvWE÷&öf–ÆR‡7FFRÂÆ–æU÷W6W%ö–B¢&WÇ•ö—FV×2ÒÖ–&UöGF6…öW‡—'•÷&VÖ–æB€¢&WÇ•ö—FV×2À¢&öf–ÆRÀ¢æ÷sÖ7W'&VçEö÷F–ÖR†æ6öæf–r’À¢7FFS×7FFRÀ¢FFöf–ÆSÖæ6öæf–u²$DDôd”ÄR%ÒÀ¢¢ÖW76vW2ÒµĞ¢f÷"—FVÒ–â&WÇ•ö—FV×3 ¢–b—6–ç7Fæ6R†—FVÒÂF–7B’æB—FVÒævWB‚'G—R"’ÓÒ&fÆW‚# ¢–bfÆW…6VæDÖW76vR—2æ÷BæöæS ¢ÖW76vW2æVæB€¢fÆW…6VæDÖW76vR€¢ÇE÷FW‡C×7G"†—FVÒævWB‚&ÇEFW‡B"’÷".ikjhù˜i""•³£CÒÀ¢6öçFVçG3Ö—FVÒævWB‚&6öçFVçG2"’÷"·ÒÀ¢¢¢VÇ6S ¢ÖW76vW2æVæB€¢FW‡E6VæDÖW76vR‡FW‡C×7G"†—FVÒævWB‚&ÇEFW‡B"’÷".ikjhù˜i""’¢¢VÇ6S ¢ÖW76vW2æVæB…FW‡E6VæDÖW76vR‡FW‡C×7G"†—FVÒ’’¢–b6†÷VÆEö7&VFU÷7W÷'E÷F–6¶WB‡FW‡B“ ¢7&VFU÷7W÷'E÷F–6¶WB€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢°¢&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–BÀ¢&ÖW76vR#¢FW‡BÀ¢ÒÀ¢¢–bÖW76vW3 ¢Æ–æUö&÷Eö’ç&WÇ•öÖW76vR†WfVçBç&WÇ•÷Fö¶VâÂÖW76vW2¢&WGW&à¢VÆ–bç’†¶W—v÷&B–âFW‡Bf÷"¶W—v÷&B–â5DEU5ô´U•tõ$E2“ ¢7FFRÒÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò¢7FGW2Ò'V–ÆE÷7FGW2†vWE÷&öf–ÆR‡7FFRÂÆ–æU÷W6W%ö–B’¢–b6†÷VÆEö7&VFU÷7W÷'E÷F–6¶WB‡FW‡B“ ¢7&VFU÷7W÷'E÷F–6¶WB€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢°¢&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–BÀ¢&ÖW76vR#¢FW‡BÀ¢ÒÀ¢¢&WÇ•÷FW‡BÒ€¢.KÚy¨NYXşšÎ[{.{i>Š‰˜ÈNKˆ¾Kèn8%ÆåÆâ ¢/	ù:’Zê.iÈŞiÈ>YÊ‚ûÙã2X¾[z^KÙÎZJXZ~KºRVÖ–ÂY¹îŠhn8%ÆåÆâ ¢b.K™şXúşKº^XXyÈ¾[‹Šh¾YXşšÎûÉ§¶Æ–æUöÆ–fe÷W&Â‚vfr—ÕÆåÆâ ¢.ˆº^iŠşz¸¾XÛ>XÛ™ª®ûÈÎŠ¸¾XXi*^h™28" ¢¢VÇ6S ¢&WÇ•÷FW‡BÒÆ–æUöWFõ÷&WÇ•÷FW‡B‡FW‡BÂ7FGW2¢Æ–æUö&÷Eö’ç&WÇ•öÖW76vR†WfVçBç&WÇ•÷Fö¶VâÂFW‡E6VæDÖW76vR‡FW‡C×&WÇ•÷FW‡B’ ¢6–væGW&RÒ&WVW7Bæ†VFW'2ævWB‚%‚ÔÆ–æRÕ6–væGW&R"Â""¢2W6R&r'—FW2F†VâFV6öFR6ò„Ô2ÖF6†W2Ä”äRw26–væVB&öG’W†7FÇ¢&öG•ö'—FW2Ò&WVW7BævWEöFF†66†SÕG'VRÂ5÷FW‡CÔfÇ6R’÷""" ¢G'“ ¢&öG’Ò&öG•ö'—FW2æFV6öFR‚'WFbÓ‚"¢W†6WBVæ–6öFTFV6öFTW'&÷# ¢2Ä”äR6öç6öÆRfW&–g’×W7BæWfW"6VRæöâÓ# ¢æÆövvW"æW'&÷"‚&6ÆÆ&6²&öG’æ÷BWFbÓ‚ÆVãÒW2"ÂÆVâ†&öG•ö'—FW2’¢&WGW&â§6öæ–g’‡²&ö²#¢G'VRÂ'fW&–g’#¢G'VWÒ ¢26ögBÖ66WC¢V×G’òæòÖWfVçG2–ÆöG2Çv—2#„Ä”äRfW&–g’'WGFöâ¢7G&—VBÒ†&öG’÷"""’ç7G&—‚¢–bæ÷B7G&—VC ¢&WGW&â§6öæ–g’‡²&ö²#¢G'VRÂ'fW&–g’#¢G'VWÒ¢G'“ ¢&ö&RÒ§6öâæÆöG2‡7G&—VB¢–b—6–ç7Fæ6R‡&ö&RÂF–7B’æBæ÷B‡&ö&RævWB‚&WfVçG2"’÷"µÒ“ ¢27F–ÆÂ'Vâ†æFÆW"v†Vâ6–væGW&R—2fÆ–C²öâÖ—6ÖF6‚&WGW&â# ¢G'“ ¢†æFÆW"æ†æFÆR†&öG’Â6–væGW&R¢W†6WB–çfÆ–E6–væGW&TW'&÷# ¢æÆövvW"çv&æ–ær€¢$Ä”äRfW&–g’öV×G’WfVçG2&B6–væGW&R&öG•öÆVãÒW26V7&WEöÆVãÒW2"À¢ÆVâ†&öG•ö'—FW2’À¢ÆVâ‡6V7&WB÷"""’À¢¢W†6WBW†6WF–öâ2W†3¢2æ÷¢$ÄS¢æÆövvW"çv&æ–ær‚$Ä”äRfW&–g’öV×G’†æFÆR6¶—¢W2"ÂG—R†W†2’åõöæÖUõò¢&WGW&â§6öæ–g’‡²&ö²#¢G'VRÂ'fW&–g’#¢G'VWÒ¢W†6WBW†6WF–öã ¢70 ¢G'“ ¢†æFÆW"æ†æFÆR†&öG’Â6–væGW&R¢W†6WB–çfÆ–E6–væGW&TW'&÷# ¢2Ä”äRFö73¢Çv—2&WGW&â#FòF†RÆFf÷&Ó²Fòæ÷B&ö6W72&B×6–rWfVçG0¢æÆövvW"çv&æ–ær€¢&–çfÆ–BÄ”äR6–væGW&R–væ÷&VB&öG•öÆVãÒW26–uöÆVãÒW26V7&WEöÆVãÒW2"À¢ÆVâ†&öG•ö'—FW2’À¢ÆVâ‡6–væGW&R÷"""’À¢ÆVâ‡6V7&WB÷"""’À¢¢&WGW&â§6öæ–g’‡²&ö²#¢G'VRÂ'6–væGW&R#¢&–væ÷&VB'Ò¢W†6WBÆ–æT&÷D”W'&÷"2W†3 ¢æÆövvW"æW†6WF–öâ‚&6ÆÆ&6²Æ–æT&÷D”W'&÷#¢W2"ÂW†2¢27F–ÆÂ#6òÄ”äRFöW2æ÷BF—6&ÆRvV&†öö²òf–ÂfW&–g’ÖÆ–¶R&ö&W0¢&WGW&â§6öæ–g’‡²&ö²#¢G'VRÂ&Æ–æUö•öW'&÷"#¢G'VWÒ¢W†6WBW†6WF–öâ2W†3¢2æ÷¢$ÄS¢æÆövvW"æW†6WF–öâ‚&6ÆÆ&6²VæW‡V7FVC¢W2"ÂW†2¢&WGW&â§6öæ–g’‡²&ö²#¢G'VRÂ&W'&÷%ö–væ÷&VB#¢G'VWÒ¢&WGW&â§6öæ–g’‡²&ö²#¢G'VWÒ ¢ç÷7B‚"ö’÷v&æ–ærö6æ6VÂ"¢FVbv&æ–æuö6æ6VÅö’‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢&WGW&â§6öæ–g’†6æ6VÅ÷v&æ–ær†æ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöBÂæ6öæf–r’ ¢ç÷7B‚"ö’÷6WGF–æw2"¢FVb6WGF–æw2‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢&WGW&â§6öæ–g’‡6fU÷6WGF–æw5öf÷%÷&öf–ÆR†æ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöB’ ¢ç÷7B‚"ö’ö&–ÆÆ–ær÷&VfW&Væ6W2"¢FVb&–ÆÆ–æu÷&VfW&Væ6W5ö’‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢FFÂ6öFRÒ6fUö&–ÆÆ–æu÷&VfW&Væ6W2†æ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöB¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç÷7B‚"ö’ö&–ÆÆ–ærö6æ6VÂ"¢FVb&–ÆÆ–æuö6æ6VÅö’‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢FFÂ6öFRÒ6æ6VÅ÷&V7W'&–æu÷7V'67&—F–öâ€¢æ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöBÂæ6öæf–p¢¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç÷7B‚"ö’÷–ÖVçG2ö÷&FW'2"¢FVb–ÖVçEö÷&FW'5ö’‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢FFÂ6öFRÒ7&VFU÷–ÖVçEö÷&FW"†æ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöBÂæ6öæf–r¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç÷7B‚"÷vV&†öö²öæWvV'’"¢ç÷7B‚"ö’÷–ÖVçBöæWvV'’öæ÷F–g’"¢FVbæWvV'•÷vV&†öö²‚“ ¢"".‰xŞikæ÷F–g•U$Â(	Bš™~{Ş[èÎˆz®X¹^™h¾˜	®ikjûÈXj®zØ’6öæf—&ŞûÈ8  ¢XZX¾‹zş[ézØiXûÈÎi8~KˆZ¾XZ^YXn[©~[èÎXûXÛ>XúşûÉ ¢Òö’÷–ÖVçBöæWvV'’öæ÷F–gûÈ†6†V6¶÷WBš	ŠŠŞûÈ¢Ò÷vV&†öö²öæWvV'¢h‰X©şi˜.Y¹îX+>{INih~ZÙr5T44U5>ûÈ‰xŞikXşZ[ŞûÈ8 ¢"" ¢f÷&ÒÒ&WVW7Bæf÷&ÒçFõöF–7B‚’–b&WVW7Bæf÷&ÒVÇ6R‡&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ò¢–bæWvV'’—2æöæS ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢&æWvV'’ÖöGVÆRÖ—76–ær'Ò’ÂS0¢'6VBÂW'&÷"ÒæWvV'’ç'6Uöæ÷F–g•÷–ÆöB†f÷&ÒÂæ6öæf–r¢–bW'&÷# ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢W'&÷'Ò’ÂC ¢–bæ÷BæWvV'’ææ÷F–g•÷7V66W72‡'6VB“ ¢&WGW&â&W7öç6R‚%5T44U52"ÂÖ–ÖWG—SÒ'FW‡B÷Æ–â"’Â# ¢FFÂ6öFRÒ6öæf—&Õ÷–ÖVçEö÷&FW"€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢°¢&÷&FW%ö–B#¢'6VBævWB‚&÷&FW%ö–B"’À¢'G&ç67F–öåö–B#¢'6VBævWB‚'G&ç67F–öåö–B"’À¢&Ö÷VçB#¢'6VBævWB‚&Ö÷VçB"’À¢'&÷f–FW"#¢&æWvV'’"À¢ÒÀ¢æ6öæf–rÀ¢¢–b6öFRãÒC ¢&WGW&â§6öæ–g’†FF’Â6öFP¢&WGW&â&W7öç6R‚%5T44U52"ÂÖ–ÖWG—SÒ'FW‡B÷Æ–â"’Â#  ¢ç÷7B‚"ö’÷–ÖVçBöV7’öæ÷F–g’"¢FVbV7•÷vV&†öö²‚“ ¢f÷&ÒÒ&WVW7Bæf÷&ÒçFõöF–7B‚’–b&WVW7Bæf÷&ÒVÇ6R‡&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ò¢–bV7’—2æöæS ¢&WGW&â&W7öç6R‚#Ç–ÖVçBÖöGVÆRÖ—76–ær"ÂÖ–ÖWG—SÒ'FW‡B÷Æ–â"’ÂS0¢'6VBÂW'&÷"ÒV7’ç'6Uöæ÷F–g•÷–ÆöB†f÷&ÒÂæ6öæf–r¢–bW'&÷# ¢&WGW&â&W7öç6R†b#Ç¶W'&÷'Ò"ÂÖ–ÖWG—SÒ'FW‡B÷Æ–â"’ÂC ¢–bæ÷BV7’ææ÷F–g•÷7V66W72‡'6VBÂæ6öæf–r“ ¢&WGW&â&W7öç6R‚#Äô²"ÂÖ–ÖWG—SÒ'FW‡B÷Æ–â"’Â# ¢FFÂ6öFRÒ6öæf—&Õ÷–ÖVçEö÷&FW"€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢°¢&÷&FW%ö–B#¢'6VBævWB‚&÷&FW%ö–B"’À¢'G&ç67F–öåö–B#¢'6VBævWB‚'G&ç67F–öåö–B"’À¢&Ö÷VçB#¢'6VBævWB‚&Ö÷VçB"’À¢'&÷f–FW"#¢&V7’"À¢ÒÀ¢æ6öæf–rÀ¢¢–b6öFRãÒC ¢&WGW&â&W7öç6R†b#Ç¶FFævWB‚vW'&÷"rÂv÷&FW"WFFRf–ÆVBr—Ò"ÂÖ–ÖWG—SÒ'FW‡B÷Æ–â"’Â6öFP¢&WGW&â&W7öç6R‚#Äô²"ÂÖ–ÖWG—SÒ'FW‡B÷Æ–â"’Â#  ¢ç÷7B‚"ö’÷–ÖVçBöV7’÷W&–öBÖæ÷F–g’"¢FVbV7•÷W&–öE÷vV&†öö²‚“ ¢f÷&ÒÒ&WVW7Bæf÷&ÒçFõöF–7B‚’–b&WVW7Bæf÷&ÒVÇ6R‡&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ò¢–bV7’—2æöæS ¢&WGW&â&W7öç6R‚#Ç–ÖVçBÖöGVÆRÖ—76–ær"ÂÖ–ÖWG—SÒ'FW‡B÷Æ–â"’ÂS0¢'6VBÂW'&÷"ÒV7’ç'6Uöæ÷F–g•÷–ÆöB†f÷&ÒÂæ6öæf–r¢–bW'&÷# ¢&WGW&â&W7öç6R†b#Ç¶W'&÷'Ò"ÂÖ–ÖWG—SÒ'FW‡B÷Æ–â"’ÂC ¢–bæ÷BV7’ææ÷F–g•÷7V66W72‡'6VBÂæ6öæf–r“ ¢&WGW&â&W7öç6R‚#Äô²"ÂÖ–ÖWG—SÒ'FW‡B÷Æ–â"’Â# ¢'6VBçWFFR‡²'7FGW2#¢%5T44U52"Â'&÷f–FW"#¢&V7’'Ò¢FFÂ6öFRÒ&ö6W75÷W&–öEöæ÷F–f–6F–öâ€¢æ6öæf–u²$DDôd”ÄR%ÒÂ'6VBÂæ6öæf–p¢¢–b6öFRãÒC ¢&WGW&â&W7öç6R†b#Ç¶FFævWB‚vW'&÷"rÂv÷&FW"WFFRf–ÆVBr—Ò"ÂÖ–ÖWG—SÒ'FW‡B÷Æ–â"’Â6öFP¢&WGW&â&W7öç6R‚#Äô²"ÂÖ–ÖWG—SÒ'FW‡B÷Æ–â"’Â#  ¢ç÷7B‚"ö’÷–ÖVçBöæWvV'’÷W&–öBÖæ÷F–g’"¢FVbæWvV'•÷W&–öE÷vV&†öö²‚“ ¢f÷&ÒÒ&WVW7Bæf÷&ÒçFõöF–7B‚’–b&WVW7Bæf÷&ÒVÇ6R‡&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ò¢–bæWvV'’—2æöæS ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢&æWvV'’ÖöGVÆRÖ—76–ær'Ò’ÂS0¢'6VBÂW'&÷"ÒæWvV'’ç'6U÷W&–öE÷–ÆöB†f÷&ÒÂæ6öæf–r¢–bW'&÷# ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢W'&÷'Ò’ÂC ¢FFÂ6öFRÒ&ö6W75÷W&–öEöæ÷F–f–6F–öâ€¢æ6öæf–u²$DDôd”ÄR%ÒÂ'6VBÂæ6öæf–p¢¢–b6öFRãÒC ¢&WGW&â§6öæ–g’†FF’Â6öFP¢&WGW&â&W7öç6R‚%5T44U52"ÂÖ–ÖWG—SÒ'FW‡B÷Æ–â"’Â#  ¢ç&÷WFR‚"÷–ÖVçB×7V66W72"ÂÖWF†öG3Õ²$tUB"Â%õ5B%Ò¢FVb–ÖVçE÷7V66W75÷vR‚“ ¢2‰xŞik&WGW&åU$Â[‹KºRõ5B[‹nY¹îK¹jËî{YiéÎûÉ¾ˆˆrtUBYÎjŠ>Y¹îX+258 ¢&WGW&â6VæEög&öÕöF—&V7F÷'’†ç7FF–5öföÆFW"Â&–æFW‚æ‡FÖÂ" ¢ævWB‚"ö’ö6öçF7G2"¢FVb6öçF7G5övWB‚“ ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡·ÒÂW6Uö&w3ÕG'VR¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢&WGW&â§6öæ–g’†vWEö6öçF7G2†æ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–B’ ¢ç÷7B‚"ö’ö6öçF7G2"¢FVb6öçF7G5÷÷7B‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢FFÂ6öFRÒ6fUö6öçF7G2†æ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöB¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ævWB‚"ö’ö6ÆVæF"Öæ÷FW2"¢FVb6ÆVæF%öæ÷FW5övWB‚“ ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡·ÒÂW6Uö&w3ÕG'VR¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢FFÒvWEö6ÆVæF%öæ÷FW2€¢æ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–@¢¢&WGW&â§6öæ–g’†FF’Â#–bFFævWB‚&ö²"’VÇ6RC0 ¢ç÷7B‚"ö’ö6ÆVæF"Öæ÷FW2"¢FVb6ÆVæF%öæ÷FW5÷÷7B‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢FFÂ6öFRÒ6fUö6ÆVæF%öæ÷FR†æ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöB¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç÷7B‚"ö’ö6öçF7G2öFB"¢FVb6öçF7G5öFB‚“ ¢"".ikZ)îYjîKˆZèŠÛ~K«®ˆş{ZK«®8""" ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢FFÂ6öFRÒFE÷6–ævÆUö6öçF7B†æ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–BÂ–ÆöB¢–b6öFRÓÒ# ¢&W7öç6RÒ²&ö²#¢G'VRÂ&6öçF7B#¢FF²&6öçF7B%ÒÂ&6öçF7G2#¢FF²&6öçF7G2%ÒÂ&6öçF7EöÆ–Ö—B#¢FF²&6öçF7EöÆ–Ö—B%×Ğ¢VÇ6S ¢&W7öç6RÒ²&ö²#¢fÇ6RÂ&W'&÷"#¢FFævWB‚&W'&÷""’Â&f–VÆG2#¢FFævWB‚&f–VÆG2"’Â&6öçF7EöÆ–Ö—B#¢FFævWB‚&6öçF7EöÆ–Ö—B"’Â&7W'&VçEö6÷VçB#¢FFævWB‚&7W'&VçEö6÷VçB"’Â&ÖW76vR#¢FFævWB‚&ÖW76vR"—Ğ¢&WGW&â§6öæ–g’‡&W7öç6R’Â6öFP ¢çWB‚"ö’ö6öçF7G2óÆ6öçF7Eö–Câ"¢FVb6öçF7G5÷WFFR†6öçF7Eö–B“ ¢"".i»NikYjîKˆZèŠÛ~K«®ˆş{ZK«®8""" ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢FFÂ6öFRÒWFFU÷6–ævÆUö6öçF7B†æ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–BÂ6öçF7Eö–BÂ–ÆöB¢–b6öFRÓÒ# ¢&W7öç6RÒ²&ö²#¢G'VRÂ&6öçF7B#¢FF²&6öçF7B%ÒÂ&6öçF7G2#¢FF²&6öçF7G2%×Ğ¢VÇ6S ¢&W7öç6RÒ²&ö²#¢fÇ6RÂ&W'&÷"#¢FFævWB‚&W'&÷""’Â&f–VÆG2#¢FFævWB‚&f–VÆG2"—Ğ¢&WGW&â§6öæ–g’‡&W7öç6R’Â6öFP ¢æFVÆWFR‚"ö’ö6öçF7G2óÆ6öçF7Eö–Câ"¢FVb6öçF7G5öFVÆWFR†6öçF7Eö–B“ ¢"".XŠ®™šNYjîKˆZèŠÛ~K«®ˆş{ZK«®8""" ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡·ÒÂW6Uö&w3ÕG'VR¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢FFÂ6öFRÒFVÆWFU÷6–ævÆUö6öçF7B†æ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–BÂ6öçF7Eö–B¢–b6öFRÓÒ# ¢&W7öç6RÒ²&ö²#¢G'VRÂ&FVÆWFVB#¢G'VRÂ&6öçF7Eö–B#¢FF²&6öçF7Eö–B%ÒÂ&6öçF7G2#¢FF²&6öçF7G2%×Ğ¢VÇ6S ¢&W7öç6RÒ²&ö²#¢fÇ6RÂ&W'&÷"#¢FFævWB‚&W'&÷""’Â&6öçF7Eö–B#¢FFævWB‚&6öçF7Eö–B"—Ğ¢&WGW&â§6öæ–g’‡&W7öç6R’Â6öFP ¢ævWB‚"ö’ööæ&ö&F–ær"¢FVböæ&ö&F–æuövWB‚“ ¢"".Y¹îX+>KÛşyJˆRöæ&ö&F–ærx¸hX¾8""" ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡·ÒÂW6Uö&w3ÕG'VR¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢FFÂ6öFRÒöæ&ö&F–æu÷7FGW5÷–ÆöB€¢æ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–@¢¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ævWB‚"ö’ö–çFW&7F–öâ×7FFR"¢FVb–çFW&7F–öå÷7FFUövWB‚“ ¢"".ŠèXùnKÛşyJˆ^K©.X¹^x¸hX²™‹.jøşiz^˜xŞŠH~y»YÎXZ~ZëyJ‚8""" ¢Æ–æU÷W6W%ö–BÒ‡&WVW7Bæ&w2ævWB‚&Æ–æU÷W6W%ö–B"’÷"""’ç7G&—‚¢–bæ÷BÆ–æU÷W6W%ö–C ¢&WGW&â§6öæ–g’‡²&ö²#¢fÇ6RÂ&W'&÷"#¢&Ö—76–ærÆ–æU÷W6W%ö–B'Ò’ÂC ¢7FFRÒÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò¢&öf–ÆRÒ7FFRævWB‚'W6W'2"Â·Ò’ævWB†Æ–æU÷W6W%ö–B¢–bæ÷B&öf–ÆS ¢&WGW&â§6öæ–g’‡²&ö²#¢fÇ6RÂ&W'&÷"#¢'W6W"æ÷B&Vv—7FW&VB'Ò’ÂC@¢—7FFRÒvWEö÷%ö7&VFUö–çFW&7F–öå÷7FFR‡&öf–ÆR¢6fU÷7FFR†æ6öæf–u²$DDôd”ÄR%ÒÂ7FFR¢&WGW&â§6öæ–g’‡²&ö²#¢G'VRÂ&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–BÂ&–çFW&7F–öå÷7FFR#¢—7FFWÒ ¢ç÷7B‚"ö’ö–çFW&7F–öâ×7FFR"¢FVb–çFW&7F–öå÷7FFU÷÷7B‚“ ¢"".i»NikKÛşyJˆ^K©.X¹^x¸hX²†6ö×ÆWFVE÷7FW2òF—6Ö—76VE÷&ö×G2òÆ7Eö6Æ÷6–æuöÖW76vRzØ’8""" ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÒ‡–ÆöBævWB‚&Æ–æU÷W6W%ö–B"’÷"""’ç7G&—‚¢–bæ÷BÆ–æU÷W6W%ö–C ¢&WGW&â§6öæ–g’‡²&ö²#¢fÇ6RÂ&W'&÷"#¢&Ö—76–ærÆ–æU÷W6W%ö–B'Ò’ÂC ¢7FFRÒÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò¢&öf–ÆRÒ7FFRævWB‚'W6W'2"Â·Ò’ævWB†Æ–æU÷W6W%ö–B¢–bæ÷B&öf–ÆS ¢&WGW&â§6öæ–g’‡²&ö²#¢fÇ6RÂ&W'&÷"#¢'W6W"æ÷B&Vv—7FW&VB'Ò’ÂC@¢—7FFRÒvWEö÷%ö7&VFUö–çFW&7F–öå÷7FFR‡&öf–ÆR¢2YKÛ^XXŠ‹i»Niky¨NjÈNKØĞ¢f÷"f–VÆB–â‚&Æ7Eö–çFW&7F–öåöB"Â&Æ7Eö–çFW&7F–öå÷7VÖÖ'’"À¢&æW‡E÷&VÖ–æFW%öB"Â&Æ7Eö6Æ÷6–æuöÖW76vR"À¢&öæ&ö&F–æuö6ö×ÆWFVB"Â&wV&F–å÷&ö×E÷7FGW2"“ ¢–bf–VÆB–â–ÆöC ¢—7FFU¶f–VÆEÒÒ–ÆöE¶f–VÆEĞ¢–b&6ö×ÆWFVE÷7FW2"–â–ÆöBæB—6–ç7Fæ6R‡–ÆöE²&6ö×ÆWFVE÷7FW2%ÒÂÆ—7B“ ¢—7FFU²&6ö×ÆWFVE÷7FW2%ÒÒÆ—7B‡6WB†—7FFRævWB‚&6ö×ÆWFVE÷7FW2"ÂµÒ’²–ÆöE²&6ö×ÆWFVE÷7FW2%Ò’¢–b'VæF–æu÷7FW2"–â–ÆöBæB—6–ç7Fæ6R‡–ÆöE²'VæF–æu÷7FW2%ÒÂÆ—7B“ ¢—7FFU²'VæF–æu÷7FW2%ÒÒ–ÆöE²'VæF–æu÷7FW2%Ğ¢–b&F—6Ö—76VE÷&ö×G2"–â–ÆöBæB—6–ç7Fæ6R‡–ÆöE²&F—6Ö—76VE÷&ö×G2%ÒÂF–7B“ ¢ÖW&vVBÒ—7FFRævWB‚&F—6Ö—76VE÷&ö×G2"Â·Ò¢ÖW&vVBçWFFR‡–ÆöE²&F—6Ö—76VE÷&ö×G2%Ò¢—7FFU²&F—6Ö—76VE÷&ö×G2%ÒÒÖW&vV@¢—7FFU²&Æ7Eö–çFW&7F–öåöB%ÒÒFFWF–ÖRææ÷r‚’æ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"¢6fU÷7FFR†æ6öæf–u²$DDôd”ÄR%ÒÂ7FFR¢&WGW&â§6öæ–g’‡²&ö²#¢G'VRÂ&–çFW&7F–öå÷7FFR#¢—7FFWÒ ¢ç÷7B‚"ö’öwV&F–â×&VÖ–æFW"öF—6Ö—72"¢FVbwV&F–å÷&VÖ–æFW%öF—6Ö—72‚“ ¢"".KÛşyJˆ^[ŞZèŠÛ~K«®ZèÎh‰[ªnhùzK®y¨NY¹îhx8  ¢&öG’ç&VfW&Væ6S¢væ÷rrÂwFöÖ÷'&÷rrÂvF—6Ö—75óvBrÂvF—6Ö—76VBp¢"" ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÒ‡–ÆöBævWB‚&Æ–æU÷W6W%ö–B"’÷"""’ç7G&—‚¢&VbÒ‡–ÆöBævWB‚'&VfW&Væ6R"’÷"""’ç7G&—‚¢–bæ÷BÆ–æU÷W6W%ö–C ¢&WGW&â§6öæ–g’‡²&ö²#¢fÇ6RÂ&W'&÷"#¢&Ö—76–ærÆ–æU÷W6W%ö–B'Ò’ÂC ¢–b&Vbæ÷B–â‚&æ÷r"Â'FöÖ÷'&÷r"Â&F—6Ö—75óvB"Â&F—6Ö—76VB"“ ¢&WGW&â§6öæ–g’‡²&ö²#¢fÇ6RÂ&W'&÷"#¢&–çfÆ–B&VfW&Væ6R'Ò’ÂC ¢7FFRÒÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò¢&öf–ÆRÒ7FFRævWB‚'W6W'2"Â·Ò’ævWB†Æ–æU÷W6W%ö–B¢–bæ÷B&öf–ÆS ¢&WGW&â§6öæ–g’‡²&ö²#¢fÇ6RÂ&W'&÷"#¢'W6W"æ÷B&Vv—7FW&VB'Ò’ÂC@¢—7FFRÒvWEö÷%ö7&VFUö–çFW&7F–öå÷7FFR‡&öf–ÆR¢—7FFU²&wV&F–å÷&VÖ–æFW%÷&VfW&Væ6R%ÒÒ&V`¢—7FFU²&wV&F–åöÆ7E÷&ö×FVEöB%ÒÒFFWF–ÖRææ÷r‚’æ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"¢æ÷rÒFFWF–ÖRææ÷r‚¢–b&VbÓÒ'FöÖ÷'&÷r# ¢—7FFU²&wV&F–å÷&VÖ–æFW%÷6æö÷¦VE÷VçF–Â%ÒÒ†æ÷r²F–ÖVFVÇF†F—3Ó’’æ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"¢VÆ–b&VbÓÒ&F—6Ö—75óvB# ¢—7FFU²&wV&F–å÷&VÖ–æFW%÷6æö÷¦VE÷VçF–Â%ÒÒ†æ÷r²F–ÖVFVÇF†F—3Ór’’æ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"¢VÇ6S ¢—7FFU²&wV&F–å÷&VÖ–æFW%÷6æö÷¦VE÷VçF–Â%ÒÒ" ¢6fU÷7FFR†æ6öæf–u²$DDôd”ÄR%ÒÂ7FFR¢&WGW&â§6öæ–g’‡²&ö²#¢G'VRÂ&–çFW&7F–öå÷7FFR#¢—7FFWÒ   ¢2&öGV7F–öâZèÎXZKˆŞŠ‹¾Xh¢FWbVæGö–çB†wVæ–6÷&âKˆŞ‹yç'Vâ‚’ÆFV'VriŠòfÇ6R¢ö—5öFWbÒ€¢÷2æVçf—&öâævWB‚$DUeôÔôDR"Â""’æÆ÷vW"‚’–â‚#"Â'G'VR"Â'–W2"¢÷"÷2æVçf—&öâævWB‚$dÄ4µôTåb"Â""’æÆ÷vW"‚’–â‚&FWfVÆ÷ÖVçB"Â&FWb"¢÷"æFV'Vp¢ ¢–bö—5öFWc ¢ç÷7B‚"ö’öFWb÷Ww&FR×Æâ"¢FVbFWe÷Ww&FU÷Æâ‚“ ¢""$DUbôäÅ“¢XØ~{I¢ÆâkŠÎŠšnyJ‚8  ¢&öGV7F–öâKˆ[è¾Y¹âCN8.Xú®iÈKº^Kˆ¾h8^k8h˜ŞXXŠ‹YÎXú³ ¢â&WVW7Bç&VÖ÷FUöFG"iŠò#rãããò££iÊÎj™ò¢"âh‰bVçbDUeôÔôDS×G'VRiˆîz+®YYşyJ€¢2âh‰b†÷7B†VFW"iŠòÆö6Æ†÷7Bò#rããã¢"" ¢2âiÊÎj™ò•XXŠ‹¢&VÖ÷FRÒ‡&WVW7Bç&VÖ÷FUöFG"÷"""’ç7G&—‚¢†÷7BÒ‡&WVW7Bæ†÷7B÷"""’æÆ÷vW"‚¢—5öÆö6ÂÒ&VÖ÷FR–â‚##rããã"Â#££"Â&Æö6Æ†÷7B"’÷"†÷7Bç7F'G7v—F‚‚&Æö6Æ†÷7B"’÷"†÷7Bç7F'G7v—F‚‚##râ"¢2"âVçbiˆîz+®YYşyJ€¢FWeöÖöFUöVæ&ÆVBÒ÷2æVçf—&öâævWB‚$DUeôÔôDR"Â""’æÆ÷vW"‚’–â‚#"Â'G'VR"Â'–W2"¢–bæ÷B†—5öÆö6Â÷"FWeöÖöFUöVæ&ÆVB“ ¢2&öGV7F–öây+Z(2Îh¹.{Y^ZÙXùbKˆŞ˜ş™Ë"VæGö–çBZÙYÊ‚¢&WGW&â§6öæ–g’‡²&ö²#¢fÇ6RÂ&W'&÷"#¢&æ÷Eöf÷VæB'Ò’ÂC@¢2˜	®˜îjª.iúRÎYû~ŠÂFWb˜(ş‹Êğ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÒ‡–ÆöBævWB‚&Æ–æU÷W6W%ö–B"’÷"""’ç7G&—‚¢ÆâÒ‡–ÆöBævWB‚'Æâ"’÷"'–Eós“•÷–V""’ç7G&—‚¢–bæ÷BÆ–æU÷W6W%ö–C ¢&WGW&â§6öæ–g’‡²&ö²#¢fÇ6RÂ&W'&÷"#¢&Ö—76–ærÆ–æU÷W6W%ö–B'Ò’ÂC ¢7FFRÒÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò¢&öf–ÆRÒ7FFRævWB‚'W6W'2"Â·Ò’ævWB†Æ–æU÷W6W%ö–B¢–bæ÷B&öf–ÆS ¢&WGW&â§6öæ–g’‡²&ö²#¢fÇ6RÂ&W'&÷"#¢'W6W"æ÷B&Vv—7FW&VB'Ò’ÂC@¢&öf–ÆU²'Æâ%ÒÒÆà¢6fU÷7FFR†æ6öæf–u²$DDôd”ÄR%ÒÂ7FFR¢&WGW&â§6öæ–g’‡²&ö²#¢G'VRÂ'Æâ#¢ÆçÒ’Â#  ¢ç÷7B‚"ö’ööæ&ö&F–ærö6ö×ÆWFR"¢FVböæ&ö&F–æuö6ö×ÆWFR‚“ ¢"".j‰Š‰‚öæ&ö&F–ærZèÎh‰[ø^šˆ{>[	iÈ’KØŞZèŠÛ~K«¢8""" ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢&W7VÇBÂ6öFRÒ6ö×ÆWFUööæ&ö&F–æuöf÷%÷W6W"€¢æ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–BÂ–Æö@¢¢&WGW&â§6öæ–g’‡&W7VÇB’Â6öFP ¢ævWB‚"ö’öVÖW&vVæ7’Ö6öçF7Bö–çf—FR×&Wf–Wr"¢FVbVÖW&vVæ7•ö6öçF7Eö–çf—FU÷&Wf–Wuö’‚“ ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡·ÒÂW6Uö&w3ÕG'VR¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢–ÆöBÒ°¢&–çf—FUög&öÒ#¢&WVW7Bæ&w2ævWB‚&–çf—FUög&öÒ"’÷"&WVW7Bæ&w2ævWB‚&g&öÒ"’÷"""À¢&–çf—FU÷Fö¶Vâ#¢&WVW7Bæ&w2ævWB‚&–çf—FU÷Fö¶Vâ"’÷"""À¢&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–BÀ¢Ğ¢FFÂ6öFRÒ–çf—FUö&–æE÷&Wf–Wr†æ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöB¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç÷7B‚"ö’öVÖW&vVæ7’Ö6öçF7Bö–çf—FR"¢FVbVÖW&vVæ7•ö6öçF7Eö–çf—FUö7&VFUö’‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢FFÂ6öFRÒ7&VFUöwV&F–åö–çf—FR€¢æ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–BÂ–Æö@¢¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç÷7B‚"ö’öVÖW&vVæ7’Ö6öçF7Bö&–æB"¢FVbVÖW&vVæ7•ö6öçF7Eö&–æEö’‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢–ÆöE²&6öçF7EöÆ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢FFÂ6öFRÒ&–æEöVÖW&vVæ7•ö6öçF7B†æ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöBÂæ6öæf–r¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç÷7B‚"ö’öwV&F–âÖw&÷W2ö&–æB"¢FVbwV&F–åöw&÷W5ö&–æEö’‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢FFÂ6öFRÒ&–æEöwV&F–åöw&÷W†æ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöB¢–b6öFRÓÒ#æBFFævWB‚'G&–Å÷FW7EöÖW76vR"“ ¢Fö¶VâÒæ6öæf–rævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"’÷"÷2æVçf—&öâævWB€¢$Ä”äUô4„ääTÅô44U55õDô´Tâ"Â" ¢¢–bæ÷BFö¶Vã ¢&WGW&â§6öæ–g’‡°¢¢¦FFÀ¢'G&–Å÷FW7EöFVÆ—fW'’#¢&f–ÆVB"À¢&W'&÷"#¢$Ä”äUô4„ääTÅô44U55õDô´Tâ—2æ÷B6WB"À¢Ò’ÂS0¢6VæFW"Òæ6öæf–rævWB‚$Ä”äUõU4…õ4TäDU""’÷"Æ–æU÷W6…öÖW76vP¢&WG'•ö¶W’ÒFFævWB‚'G&–Å÷FW7E÷&WG'•ö¶W’"’÷"öÆ–æU÷&WG'•ö¶W’€¢b'G&–ÂÖw&÷W×FW7C§¶Æ–æU÷W6W%ö–GÓ§·–ÆöBævWB‚vw&÷Wö–Br—Ò ¢¢G'“ ¢÷6VæEöÆ–æU÷v—F…÷&WG'•ö¶W’€¢6VæFW"À¢Fö¶VâÀ¢–ÆöBævWB‚&w&÷Wö–B"’À¢FF²'G&–Å÷FW7EöÖW76vR%ÒÀ¢&WG'•ö¶W’À¢¢FF²'G&–Å÷FW7EöFVÆ—fW'’%ÒÒ'6VçB ¢×WFFU÷7FFUöFöÖ–6ÆÇ’€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢ÆÖ&F7FFS¢€¢‡7FFRævWB‚'W6W'2"’÷"·Ò’ævWB†Æ–æU÷W6W%ö–BÂ·Ò’ç6WFFVfVÇB€¢'G&–Åöw&÷W÷FW7EöFVÆ—fW'’"Â·Ğ¢’çWFFR‡°¢'7FGW2#¢'6VçB"À¢'6VçEöB#¢7W'&VçEö÷F–ÖR†æ6öæf–r’æ—6öf÷&ÖB€¢F–ÖW7V3Ò'6V6öæG2 ¢’À¢Ò’À¢&V6÷&EöÆ–æUöÖW76vU÷W6vR€¢7FFRÀ¢6FVv÷'“Ò'G&–Åöw&÷W÷FW7B"À¢÷væW%öÆ–æU÷W6W%ö–CÖÆ–æU÷W6W%ö–BÀ¢&V6—–VçEö6÷VçCÓÀ¢WfVçEö–C×&WG'•ö¶W’À¢’À¢•²ÓÒÀ¢¢W†6WBW†6WF–öâ2W†3 ¢FF²'G&–Å÷FW7EöFVÆ—fW'’%ÒÒ&f–ÆVB ¢FF²&W'&÷"%ÒÒ.kŠÎŠšn˜	®yú^iª¾i˜.xJk9^˜X{®ûÈÎŠ¸¾zˆŞ[èÎXhŞŠšn8" ¢×WFFU÷7FFUöFöÖ–6ÆÇ’€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢ÆÖ&F7FFS¢‡7FFRævWB‚'W6W'2"’÷"·Ò’ævWB€¢Æ–æU÷W6W%ö–BÂ·Ğ¢’ç6WFFVfVÇB‚'G&–Åöw&÷W÷FW7EöFVÆ—fW'’"Â·Ò’çWFFR‡°¢'7FGW2#¢&f–ÆVB"À¢&Æ7EöW'&÷"#¢7G"†W†2•³£#ÒÀ¢Ò’À¢¢æÆövvW"çv&æ–ær‚'G&–Âw&÷WFW7BFVÆ—fW'’f–ÆVC¢W2"ÂW†2¢&WGW&â§6öæ–g’†FF’ÂS ¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç÷7B‚"ö’öwV&F–âÖw&÷W2÷Væ&–æB"¢FVbwV&F–åöw&÷W5÷Væ&–æEö’‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢FFÂ6öFRÒVæ&–æEöwV&F–åöw&÷W†æ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöB¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç÷7B‚"ö’öwV&F–âÖw&÷W2÷&VfW&Væ6W2"¢FVbwV&F–åöw&÷W5÷&VfW&Væ6W5ö’‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢FFÂ6öFRÒWFFUöwV&F–åöw&÷W÷&VfW&Væ6W2€¢æ6öæf–u²$DDôd”ÄR%ÒÂ–Æö@¢¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ævWB‚"ö’öwV&F–âÖw&÷W2÷6WGF–æw2"¢FVbwV&F–åöw&÷W5÷6WGF–æw5ö’‚“ ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡·ÒÂW6Uö&w3ÕG'VR¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢FFÂ6öFRÒwV&F–åöw&÷W÷6WGF–æw5öf÷%÷W6W"€¢æ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–@¢¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ævWB‚"ö’öwV&F–âÖw&÷W2÷7FGW2"¢FVbwV&F–åöw&÷W5÷7FGW5ö’‚“ ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡·ÒÂW6Uö&w3ÕG'VR¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢FFÂ6öFRÒwV&F–åöw&÷WöF–Ç•÷7FGW2€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢Æ–æU÷W6W%ö–BÀ¢7G"‡&WVW7Bæ&w2ævWB‚&w&÷Wö–B"’÷"""’ç7G&—‚’À¢¢&WGW&â§6öæ–g’†FF’Â6öFP ¢2ÓÓÓÓÒ##bÓrÓ#‰Ún‰2FFVC¢kŠÎŠšnšVæGö–çG2ÓÓÓÓĞ¢DU5EõU4U%õ$Td•‚Ò%UõDU5Eò  ¢ævWB‚"ö’öwV&F–âÖw&÷W2÷FW7B×W6W'2"¢FVbwV&F–åöw&÷W5÷FW7E÷W6W'5ö’‚“ ¢7FFRÒÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò¢W6W'2ÒµĞ¢f÷"V–BÂ&öf–ÆR–â‡7FFRævWB‚'W6W'2"’÷"·Ò’æ—FV×2‚“ ¢–bæ÷BV–Bç7F'G7v—F‚…DU5EõU4U%õ$Td•‚“ ¢6öçF–çVP¢ÆâÒ&öf–ÆRævWB‚'Æâ"’÷"'G&–Â ¢—5÷–V"ÒÆâÓÒ'–Eós“•÷–V" ¢—5öÖöçF‚ÒÆâÓÒ'–Eós“’ ¢VÆ–v–&ÆRÒ†—5÷–V"÷"—5öÖöçF‚’æB–EöÖVÖ&W'6†—ö—5ö7F—fR‡&öf–ÆR¢W6W'2æVæB‡°¢&Æ–æU÷W6W%ö–B#¢V–BÀ¢&F—7Æ•öæÖR#¢&öf–ÆRævWB‚&F—7Æ•öæÖR"Â""’À¢'Æâ#¢ÆâÀ¢'–E÷VçF–Â#¢&öf–ÆRævWB‚'–E÷VçF–Â"Â""’À¢'–ÖVçE÷7FGW2#¢&öf–ÆRævWB‚'–ÖVçE÷7FGW2"Â""’À¢&&–æEö6÷VçB#¢ÆVâ‡&öf–ÆRævWB‚&wV&F–åöw&÷Wö–G2"’÷"µÒ’À¢&Ö…öw&÷W2#¢ƒ2–b—5÷–V"VÇ6R’–bVÆ–v–&ÆRVÇ6RÀ¢&VÆ–v–&ÆR#¢VÆ–v–&ÆRÀ¢'7FGW2#¢&VÆ–v–&ÆR"–bVÆ–v–&ÆRVÇ6R&–æVÆ–v–&ÆR"À¢&wV&F–åöw&÷Wö–G2#¢&öf–ÆRævWB‚&wV&F–åöw&÷Wö–G2"ÂµÒ’À¢Ò¢w&÷W2Ò°¢²&w&÷Wö–B#¢v–BÂ¢¦v–æf÷Ğ¢f÷"v–BÂv–æfò–â‡7FFRævWB‚&wV&F–åöw&÷W2"’÷"·Ò’æ—FV×2‚¢Ğ¢&WGW&â§6öæ–g’‡²'W6W'2#¢W6W'2Â&w&÷W2#¢w&÷W2Â'&Vf—‚#¢DU5EõU4U%õ$Td•‡Ò ¢ç÷7B‚"ö’öwV&F–âÖw&÷W2÷FW7B×&W6WB"¢FVbwV&F–åöw&÷W5÷FW7E÷&W6WEö’‚“ ¢7FFRÒÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò¢V–G2Ò·V–Bf÷"V–B–â7FFRævWB‚'W6W'2"Â·Ò’æ¶W—2‚’–bV–Bç7F'G7v—F‚…DU5EõU4U%õ$Td•‚•Ğ¢f÷"V–B–âV–G3 ¢7FFU²'W6W'2%Òç÷‡V–BÂæöæR¢f÷"&öf–ÆR–â7FFRævWB‚'W6W'2"Â·Ò’çfÇVW2‚“ ¢–b—6–ç7Fæ6R‡&öf–ÆRævWB‚&6öçF7G2"’ÂÆ—7B“ ¢&öf–ÆU²&6öçF7G2%ÒÒ¶2f÷"2–â&öf–ÆU²&6öçF7G2%Ò–b2ævWB‚&Æ–æUö–B"’æ÷B–âV–G5Ğ¢–b—6–ç7Fæ6R‡&öf–ÆRævWB‚&g&–VæG2"’ÂÆ—7B“ ¢&öf–ÆU²&g&–VæG2%ÒÒ¶bf÷"b–â&öf–ÆU²&g&–VæG2%Ò–bbæ÷B–âV–G5Ğ¢f÷"v–B–âÆ—7B‡7FFRævWB‚&wV&F–åöw&÷W2"Â·Ò’æ¶W—2‚’“ ¢÷væW"Ò7FFU²&wV&F–åöw&÷W2%Õ¶v–EÒævWB‚&÷væW%öÆ–æU÷W6W%ö–B"Â""¢–b÷væW"ç7F'G7v—F‚…DU5EõU4U%õ$Td•‚“ ¢7FFU²&wV&F–åöw&÷W2%Òç÷†v–BÂæöæR¢f÷"&öf–ÆR–â7FFRævWB‚'W6W'2"Â·Ò’çfÇVW2‚“ ¢–b—6–ç7Fæ6R‡&öf–ÆRævWB‚&wV&F–åöw&÷Wö–G2"’ÂÆ—7B“ ¢&öf–ÆU²&wV&F–åöw&÷Wö–G2%ÒÒµĞ¢6fU÷7FFR†æ6öæf–u²$DDôd”ÄR%ÒÂ7FFR¢FVfVÇG2Ò°¢‚%UõDU5E÷–V&Ç•ó"Â'–Eós“•÷–V""Â.kŠÎŠšbŞ[›N‹+³““’"Â##“’Ó"Ó3C££"Â&7F—fR"’À¢‚%UõDU5EöÖöçF†Ç•ó"Â'–Eós“’"Â.kŠÎŠšbŞiÈ‹+²"Â##“’Ó"Ó3C££"Â&7F—fR"’À¢‚%UõDU5Eó3“•ó"Â'–Eó3“’"Â.kŠÎŠšbÓ3“’KˆŞzÊn‹8~jÂ"Â##“’Ó"Ó3C££"Â&7F—fR"’À¢‚%UõDU5E÷G&–Åó"Â'G&–Â"Â.kŠÎŠšb×G&–Â"Â""Â'G&–Â"’À¢Ğ¢7&VFVBÒµĞ¢f÷"V–BÂÆâÂæÖRÂ–E÷VçF–ÂÂ–ÖVçE÷7FGW2–âFVfVÇG3 ¢–bV–B–â7FFU²'W6W'2%Ó ¢6öçF–çVP¢7FFU²'W6W'2%Õ·V–EÒÒ°¢&Æ–æU÷W6W%ö–B#¢V–BÂ&F—7Æ•öæÖR#¢æÖRÂ'Æâ#¢ÆâÀ¢'–E÷VçF–Â#¢–E÷VçF–ÂÂ'–ÖVçE÷7FGW2#¢–ÖVçE÷7FGW2À¢&wV&F–åöw&÷Wö–G2#¢µÒÂ&6öçF7G2#¢µÒÂ&g&–VæG2#¢µÒÀ¢Ğ¢7&VFVBæVæB‡V–B¢6fU÷7FFR†æ6öæf–u²$DDôd”ÄR%ÒÂ7FFR¢&WGW&â§6öæ–g’‡²'&W6WB#¢G'VRÂ&FVÆWFVE÷W6W'2#¢ÆVâ‡V–G2’Â&7&VFVB#¢7&VFVGÒ ¢ç÷7B‚"ö’öwV&F–âÖw&÷W2÷FW7BÖVæf÷&6R"¢FVbwV&F–åöw&÷W5÷FW7EöVæf÷&6Uö’‚“ ¢&öG’Ò&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢w&÷Wö–BÒ7G"†&öG’ævWB‚&w&÷Wö–B"’÷"""’ç7G&—‚¢6–×VÆFVEö6÷VçBÒ&öG’ævWB‚'6–×VÆFVEö6÷VçB"¢6–×VÆFVEöæWuö–G2Ò&öG’ævWB‚'6–×VÆFVEöæWuö–G2"’÷"µĞ¢–bæ÷Bw&÷Wö–C ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢&Ö—76–ærw&÷Wö–B'Ò’ÂC ¢7FFRÒÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò¢w&÷Wö–æfòÒ7FFRævWB‚&wV&F–åöw&÷W2"Â·Ò’ævWB†w&÷Wö–B¢–bæ÷Bw&÷Wö–æfó ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢&w&÷Wæ÷B&÷VæB'Ò’ÂC@¢–bw&÷Wö–æfòævWB‚'7FGW2"’Ò&7F—fR# ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢&w&÷W–æ7F—fR'Ò’ÂC¢–b6–×VÆFVEö6÷VçB—2æöæS ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢'6–×VÆFVEö6÷VçB&WV—&VB'Ò’ÂC ¢7W'&VçEö6÷VçBÒ–çB‡6–×VÆFVEö6÷VçB¢–b7W'&VçEö6÷VçBÃÒu$õUôÔTÔ$U%ôÄ”Ô•C ¢&WGW&â§6öæ–g’‡°¢&ö²#¢G'VRÂ&Væf÷&6VB#¢fÇ6RÀ¢&7W'&VçEö6÷VçB#¢7W'&VçEö6÷VçBÂ&Æ–Ö—B#¢u$õUôÔTÔ$U%ôÄ”Ô•BÀ¢&¶–6¶VB#¢µÒÂ&f–ÆVB#¢µÒÀ¢&w&÷Wö–B#¢w&÷Wö–BÀ¢&æ÷FR#¢.iÊ®‹h^˜îKˆ®™™ÎKˆŞ™ÈWf–7B"À¢Ò’Â# ¢&–æEö–G2Ò6WB†w&÷Wö–æfòævWB‚&ÖVÖ&W%ö–G5öEö&–æB"’÷"µÒ¢6æF–FFUö–G2ÒÆ—7B‡6–×VÆFVEöæWuö–G2¢÷fW&fÆ÷rÒ7W'&VçEö6÷VçBÒu$õUôÔTÔ$U%ôÄ”Ô•@¢Fõö¶–6²Ò6æF–FFUö–G5³¦÷fW&fÆ÷uÒ–b÷fW&fÆ÷râVÇ6R†6æF–FFUö–G5³£Ò–b6æF–FFUö–G2VÇ6RµÒ¢¶–6¶VBÒÆ—7B‡Fõö¶–6²¢&WGW&â§6öæ–g’‡°¢&ö²#¢G'VRÂ&Væf÷&6VB#¢G'VRÀ¢&7W'&VçEö6÷VçB#¢7W'&VçEö6÷VçBÂ&Æ–Ö—B#¢u$õUôÔTÔ$U%ôÄ”Ô•BÀ¢&÷fW&fÆ÷r#¢÷fW&fÆ÷rÀ¢&6æF–FFUö6÷VçB#¢ÆVâ†6æF–FFUö–G2’À¢&&–æE÷6æ6†÷Eö6÷VçB#¢ÆVâ†&–æEö–G2’À¢&¶–6¶VB#¢¶–6¶VBÂ&f–ÆVB#¢µÒÀ¢&w&÷Wö–B#¢w&÷Wö–BÀ¢&æ÷FR#¢.kŠÎŠšnjŠi:Â†æ÷NZún™©¾h™2Ä”äR’’"À¢Ò’Â#  ¢ç÷7B‚"ö’ög&–VæG2ö–çf—FR"¢FVbg&–VæG5ö–çf—FUö’‚“ ¢FFÂ6öFRÒ7&VFUög&–VæEö–çf—FR†æ6öæf–u²$DDôd”ÄR%ÒÂ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ò¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç÷7B‚"ö’ög&–VæG2ö66WB"¢FVbg&–VæG5ö66WEö’‚“ ¢FFÂ6öFRÒ66WEög&–VæEö–çf—FR†æ6öæf–u²$DDôd”ÄR%ÒÂ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ò¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ævWB‚"ö’ög&–VæG2öÆö6F–öç2"¢FVbg&–VæG5öÆö6F–öç5ö’‚“ ¢&WGW&â§6öæ–g’†g&–VæEöÆö6F–öç2†æ6öæf–u²$DDôd”ÄR%ÒÂ&WVW7Bæ&w2ævWB‚&Æ–æU÷W6W%ö–B"’’ ¢ævWB‚"ö’öÆö6F–öâ÷7FGW2"¢FVbÆö6F–öå÷7FGW5ö’‚“ ¢Æ–æU÷W6W%ö–BÒ7G"‡&WVW7Bæ&w2ævWB‚&Æ–æU÷W6W%ö–B"’÷"""’ç7G&—‚¢–bæ÷BÆ–æU÷W6W%ö–C ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢&Ö—76–ærÆ–æU÷W6W%ö–B'Ò’ÂC ¢7FFRÒÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò¢&öf–ÆRÒvWE÷&öf–ÆR‡7FFRÂÆ–æU÷W6W%ö–B¢&WGW&â§6öæ–g’‡²&ö²#¢G'VRÂ'6fWG•öwV&B#¢6fWG•öwV&E÷6æ6†÷B‡&öf–ÆR—Ò ¢ç÷7B‚"ö’öÆö6F–öâ÷WFFR"¢FVbÆö6F–öå÷WFFUö’‚“ ¢FFÂ6öFRÒWFFUöÆö6F–öâ€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·ÒÀ¢æ6öæf–rÀ¢¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç÷7B‚"ö’öÆö6F–öâ÷7F÷"¢FVbÆö6F–öå÷7F÷ö’‚“ ¢FFÂ6öFRÒ7F÷öÆö6F–öå÷6†&–ær†æ6öæf–u²$DDôd”ÄR%ÒÂ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ò¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç÷7B‚"ö’÷6÷2"¢FVb6÷5ö’‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢FFÂ6öFRÒG&–vvW%÷6÷2†æ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöBÂæ6öæf–r¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç÷7B‚"ö’÷G&–Â÷FW7BÖ7F–öâ"¢FVbG&–Å÷FW7Eö7F–öåö’‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢FFÂ6öFRÒWF†÷&—¦UöÆ&VÆVE÷FW7Eö7F–öâ€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢Æ–æU÷W6W%ö–BÀ¢–ÆöBævWB‚&7F–öâ"’À¢¢–b6öFRÓÒ#æBFFævWB‚&ÆÆ÷vVB"“ ¢Fö¶VâÒæ6öæf–rævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"’÷"÷2æVçf—&öâævWB€¢$Ä”äUô4„ääTÅô44U55õDô´Tâ"Â" ¢¢–bæ÷BFö¶Vã ¢&WGW&â§6öæ–g’‡°¢¢¦FFÀ¢&ÆÆ÷vVB#¢fÇ6RÀ¢'&V6öâ#¢'W6…÷Væf–Æ&ÆR"À¢Ò’ÂS0¢6VæFW"Òæ6öæf–rævWB‚$Ä”äUõU4…õ4TäDU""’÷"Æ–æU÷W6…öÖW76vP¢&WG'•ö¶W’ÒöÆ–æU÷&WG'•ö¶W’†FF²&WfVçEö–B%Ò¢G'“ ¢÷6VæEöÆ–æU÷v—F…÷&WG'•ö¶W’€¢6VæFW"ÂFö¶VâÂÆ–æU÷W6W%ö–BÂFF²&ÖW76vR%ÒÂ&WG'•ö¶W¢¢×WFFU÷7FFUöFöÖ–6ÆÇ’€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢ÆÖ&F7FFS¢&V6÷&EöÆ–æUöÖW76vU÷W6vR€¢7FFRÀ¢6FVv÷'“Öb'G&–Å÷·–ÆöBævWB‚v7F–öâr—Õ÷FW7B"À¢÷væW%öÆ–æU÷W6W%ö–CÖÆ–æU÷W6W%ö–BÀ¢&V6—–VçEö6÷VçCÓÀ¢WfVçEö–CÖFF²&WfVçEö–B%ÒÀ¢’À¢¢FF²&FVÆ—fW'’%ÒÒ'6VçB ¢W†6WBW†6WF–öâ2W†3 ¢æÆövvW"çv&æ–ær‚'G&–ÂFW7BFVÆ—fW'’f–ÆVC¢W2"ÂW†2¢FF²&FVÆ—fW'’%ÒÒ&f–ÆVB ¢FF²'&V6öâ%ÒÒ'W6…öf–ÆVB ¢&WGW&â§6öæ–g’†FF’ÂS ¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç÷7B‚"ö’÷6÷2ö6æ6VÂ"¢FVb6÷5ö6æ6VÅö’‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢FFÂ6öFRÒ6æ6VÅ÷6÷5öWfVçB†æ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöBÂæ6öæf–r¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç÷7B‚"ö’÷6÷2÷&WG'’"¢FVb6÷5÷&WG'•ö’‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢FFÂ6öFRÒ&WG'•÷6÷5öWfVçB†æ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöBÂæ6öæf–r¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ævWB‚"ö’÷6÷2÷7FGW2"¢FVb6÷5÷7FGW5ö’‚“ ¢–ÆöBÒ²&Æ–æU÷W6W%ö–B#¢&WVW7Bæ&w2ævWB‚&Æ–æU÷W6W%ö–B"Â""—Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢FFÂ6öFRÒvWE÷6÷5öWfVçE÷7FGW2€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢Æ–æU÷W6W%ö–BÀ¢&WVW7Bæ&w2ævWB‚&WfVçEö–B"Â""’À¢¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç÷7B‚"ö’÷6÷2÷&W7öæB"¢FVb6÷5÷&W7öæEö’‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢FFÂ6öFRÒ&W7öæE÷Fõ÷6÷5öWfVçB€¢æ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöBÂæ6öæf–p¢¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç÷7B‚"ö’÷6÷2÷6fR"¢FVb6÷5÷6fUö’‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢FFÂ6öFRÒ6Æ÷6U÷6÷5ö5÷6fR€¢æ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöBÂæ6öæf–p¢¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ævWB‚"ö’ö&÷BöwV&F–âÖw&÷W2"¢FVb&÷EöwV&F–åöw&÷W5ö’‚“ ¢""###bÓrÓ#F6‚##¢‹ùNY¹îh˜iÈZèŠÛ~{êNkˆ^YjâKé²&÷EöFÖ–âæ‡FÖÂ8""" ¢FVæ–VBÒöFÖ–åöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@ ¢7FFRÒÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò¢w&÷W2Ò7FFRævWB‚&wV&F–åöw&÷W2"Â·Ò¢W6W'2Ò7FFRævWB‚'W6W'2"Â·Ò¢÷WBÒµĞ¢f÷"v–BÂr–âw&÷W2æ—FV×2‚“ ¢÷væW%ö–BÒrævWB‚&÷væW%öÆ–æU÷W6W%ö–B"Â""¢÷væW%÷&öf–ÆRÒW6W'2ævWB†÷væW%ö–BÂ·Ò¢÷WBæVæB‡°¢&w&÷Wö–B#¢v–BÀ¢&÷væW%ö–B#¢÷væW%ö–E³£eÒ²"âââ"²÷væW%ö–E²ÓC¥Ò–b÷væW%ö–BVÇ6RæöæRÀ¢&÷væW%÷Æâ#¢÷væW%÷&öf–ÆRævWB‚'Æâ"’À¢&ÖVÖ&W%ö6÷VçEöEö&–æB#¢rævWB‚&ÖVÖ&W%ö6÷VçEöEö&–æB"’À¢&7&VFVEöB#¢rævWB‚&7&VFVEöB"’À¢'7FGW2#¢rævWB‚'7FGW2"’À¢Ò¢&WGW&â§6öæ–g’‡²&w&÷W2#¢÷WBÂ'F÷FÂ#¢ÆVâ†÷WB—Ò ¢ævWB‚"ö’ö&÷B÷6÷2×VæF–ær"¢FVb&÷E÷6÷5÷VæF–æuö’‚“ ¢""%&WGW&â4õ2&öw&W72ÂFVÆ—fW'’WfVçG2æBw&FVB6fWG’&W7G&–7F–öç2â"" ¢FVæ–VBÒöFÖ–åöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@ ¢7FFRÒÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò¢VæF–ærÒ7FFRævWB‚'6÷5÷VæF–ær"Â·Ò¢÷WBÒµĞ¢f÷"V–BÂ–âVæF–æræ—FV×2‚“ ¢÷WBæVæB‡°¢'W6W%ö–B#¢V–E³£eÒ²"âââ"²V–E²ÓC¥ÒÀ¢'7FvR#¢ævWB‚'7FvR"’À¢'Fö6÷VçB#¢ævWB‚'Fö6÷VçB"’À¢&f—'7E÷FöB#¢ævWB‚&f—'7E÷FöB"’À¢&Æ7E÷FöB#¢ævWB‚&Æ7E÷FöB"’À¢'6VçEöB#¢ævWB‚'6VçEöB"’À¢&WfVçEö–B#¢ævWB‚&WfVçEö–B"’À¢&6æ6VÆÆVEöB#¢ævWB‚&6æ6VÆÆVEöB"’À¢Ò¢27F—fRYÊX˜ÒŠÚnY¢÷v&æ–ær’Ç6VçBÆ6æ6VÆÆVBYÊ[èÀ¢÷WBç6÷'B†¶W“ÖÆÖ&Fƒ¢‡‚ævWB‚'7FvR"Â""’æ÷B–â‚'v&æ–æuó"Â'v&æ–æuó""Â'v&æ–æuó2"’Â‚ævWB‚&Æ7E÷FöB"’÷"""’¢WfVçG2ÒµĞ¢f÷"WfVçB–â‡7FFRævWB‚'6÷5öWfVçG2"’÷"·Ò’çfÇVW2‚“ ¢÷væW"Ò7G"†WfVçBævWB‚&÷væW%öÆ–æU÷W6W%ö–B"’÷"""¢FVÆ—fW&–W2ÒWfVçBævWB‚&FVÆ—fW&–W2"’÷"µĞ¢WfVçG2æVæB‡°¢&WfVçEö–B#¢WfVçBævWB‚&WfVçEö–B"’À¢&÷væW%ö–B#¢÷væW%³£eÒ²"âââ"²÷væW%²ÓC¥Ò–b÷væW"VÇ6RæöæRÀ¢&÷væW%öF—7Æ•öæÖR#¢WfVçBævWB‚&÷væW%öF—7Æ•öæÖR"’À¢'7FGW2#¢WfVçBævWB‚'7FGW2"’À¢'6VçEöB#¢WfVçBævWB‚'6VçEöB"’À¢&6æ6VÆÆVEöB#¢WfVçBævWB‚&6æ6VÆÆVEöB"’À¢'6VçB#¢7VÒƒf÷"—FVÒ–âFVÆ—fW&–W2–b—FVÒævWB‚'7FGW2"’ÓÒ'6VçB"’À¢&f–ÆVB#¢7VÒƒf÷"—FVÒ–âFVÆ—fW&–W2–b—FVÒævWB‚'7FGW2"’ÓÒ&f–ÆVB"’À¢&'W6UöÖöFR#¢WfVçBævWB‚&'W6UöÖöFR"’÷"&æ÷&ÖÂ"À¢Ò¢WfVçG2ç6÷'B†¶W“ÖÆÖ&F—FVÓ¢—FVÒævWB‚'6VçEöB"’÷"""Â&WfW'6SÕG'VR¢'W6RÒ²&ö'6W'fF–öâ#¢Â'&W7G&–7FVB#¢Ğ¢f÷"&öf–ÆR–â‡7FFRævWB‚'W6W'2"’÷"·Ò’çfÇVW2‚“ ¢ÖöFRÒ6÷5ö'W6U÷7FFR‡&öf–ÆRÂ7W'&VçEö÷F–ÖR†æ6öæf–r’’ævWB‚&ÖöFR"¢–bÖöFR–â'W6S ¢'W6U¶ÖöFUÒ³Ò¢&WGW&â§6öæ–g’‡°¢'VæF–ær#¢÷WBÀ¢'F÷FÂ#¢ÆVâ†÷WB’À¢&WfVçG2#¢WfVçG5³£SÒÀ¢&WfVçE÷F÷FÂ#¢ÆVâ†WfVçG2’À¢&'W6R#¢'W6RÀ¢Ò ¢ævWB‚"ö’ö&÷B÷&V6VçBÖWfVçG2"¢FVb&÷E÷&V6VçEöWfVçG5ö’‚“ ¢""###bÓrÓ#F6‚##¢‹ùNY¹îiÈ‹ùy¨BvV&†öö²K¨¾K»bKÛşyJ‚æ÷F–f–6F–öåöÆör8""" ¢FVæ–VBÒöFÖ–åöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@ ¢7FFRÒÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò¢ÆörÒ7FFRævWB‚&æ÷F–f–6F–öåöÆör"ÂµÒ¢&V6VçBÒÆöu²Ó#¥Ò2iÈ‹ù#j)Ğ¢&V6VçBç&WfW'6R‚¢&WGW&â§6öæ–g’‡²'&V6VçB#¢&V6VçBÂ'F÷FÂ#¢ÆVâ†Æör—Ò ¢ç÷7B‚"ö’÷6÷2ö6†V6²×66†VGVÆVB"¢FVb6÷5ö6†V6µ÷66†VGVÆVEö’‚“ ¢""###bÓrÓ#F6‚#¢7&öâzºş›¹â(	Bkˆ^yn˜îiÉò4õ2{H˜ÈN8  ¢2×FkXzˆ¾iÈ>z¸¾XÛ>y›Î˜Îh˜Kº^˜	X²7&öâXú®‹*‹*Ã ¢âkˆ^hè’[şi˜.Kº^X˜Şy¨B6VçBö6æ6VÆÆVB{H˜ÈB˜şXXÒ7FFRˆjˆKR¢iÊ®KènXúşXª®YÊ‚6VçEöB[èÂRXˆn™	hù˜i.8ÎXúşKº^XùnkhK¨n8ŞzØ¢"" ¢g&öÒ6÷5öfÆ÷r–×÷'B6÷5÷W&vUööÆ@¢g&öÒFFWF–ÖR–×÷'BFFWF–ÖP ¢7FFRÒÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò¢æ÷rÒFFWF–ÖRææ÷r‚¢&VÖ÷fVBÒ6÷5÷W&vUööÆB‡7FFRÂ¶VWöÖ–çWFW3Óc¢6fU÷7FFR†æ6öæf–u²$DDôd”ÄR%ÒÂ7FFR¢&WGW&â§6öæ–g’‡°¢&6†V6¶VEöB#¢æ÷ræ—6öf÷&ÖB‡F–ÖW7V3Ò'6V6öæG2"’À¢'W&vVB#¢ÆVâ‡&VÖ÷fVB’À¢Ò ¢ç÷7B‚"ö’ö66÷VçBöFVÆWFR"¢FVb66÷VçEöFVÆWFUö’‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢FFÂ6öFRÒFVÆWFUö66÷VçB†æ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöB¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç÷7B‚"ö’ö66÷VçBöW‡÷'B"¢FVb66÷VçEöW‡÷'Eö’‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢FFÂ6öFRÒW‡÷'Eö66÷VçEöFF†æ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöB¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç÷7B‚"ö’ö66÷VçBö†—7F÷'’öFVÆWFR"¢FVb66÷VçEö†—7F÷'•öFVÆWFUö’‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢FFÂ6öFRÒFVÆWFU÷W'6öæÅö†—7F÷'’†æ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöB¢&WGW&â§6öæ–g’†FF’Â6öFP ¢FVböÖ–w&F–öå÷fW&–f–VE÷7V&¦V7B‡–ÆöBÂ6†ææVÅö¶W’“ ¢–bæ÷B66÷VçEöÖ–w&F–öå÷&VG’†æ6öæf–r“ ¢&WGW&âæöæRÂ‡²&ö²#¢fÇ6RÂ&W'&÷"#¢&Ö–w&F–öå÷Væf–Æ&ÆR'ÒÂS2¢–bW‡G&7Eö–E÷Fö¶Vâ—2æöæR÷"fW&–g•öÆ–æUö–E÷Fö¶Våöf÷%ö6†ææVÂ—2æöæS ¢&WGW&âæöæRÂ‡²&ö²#¢fÇ6RÂ&W'&÷"#¢&Ö–w&F–öå÷Væf–Æ&ÆR'ÒÂS2¢Fö¶VâÒW‡G&7Eö–E÷Fö¶Vâ€¢¶¶W“¢fÇVRf÷"¶W’ÂfÇVR–â&WVW7Bæ†VFW'2æ—FV×2‚—ÒÀ¢–ÆöBÀ¢·ÒÀ¢¢7V&¦V7BÒfW&–g•öÆ–æUö–E÷Fö¶Våöf÷%ö6†ææVÂ€¢Fö¶VâÀ¢æ6öæf–rævWB†6†ææVÅö¶W’’À¢¢–bæ÷B7V&¦V7C ¢&WGW&âæöæRÂ‡²&ö²#¢fÇ6RÂ&W'&÷"#¢&–çfÆ–E÷Fö¶Vâ'ÒÂC¢&WGW&â7V&¦V7BÂæöæP ¢ægFW%÷&WVW7@¢FVböF—6&ÆUö66÷VçEöÖ–w&F–öå÷&W7öç6Uö66†–ær‡&W7öç6R“ ¢–b&WVW7BçF‚ç7F'G7v—F‚‚"ö’ö66÷VçBÖÖ–w&F–öâò"“ ¢&W7öç6Ræ†VFW'5²$66†RÔ6öçG&öÂ%ÒÒ&æò×7F÷&R ¢&WGW&â&W7öç6P ¢ç÷7B‚"ö’ö66÷VçBÖÖ–w&F–öâ÷7F'B"¢FVb66÷VçEöÖ–w&F–öå÷7F'Eö’‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR¢–bæ÷B—6–ç7Fæ6R‡–ÆöBÂF–7B“ ¢&WGW&â§6öæ–g’‡²&ö²#¢fÇ6RÂ&W'&÷"#¢&–çfÆ–E÷&WVW7B'Ò’ÂC ¢öÆEöÆ–æU÷W6W%ö–BÂW'"ÒöÖ–w&F–öå÷fW&–f–VE÷7V&¦V7B€¢–ÆöBÀ¢$ÄTt5•ôÄ”äUôÄôt”åô4„ääTÅô”B"À¢¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢FFÂ6öFRÒ7&VFUö66÷VçEöÖ–w&F–öå÷F–6¶WB€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢öÆEöÆ–æU÷W6W%ö–BÀ¢æ6öæf–rÀ¢¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ævWB‚"ö’ö66÷VçBÖÖ–w&F–öâ÷7FGW2"¢FVb66÷VçEöÖ–w&F–öå÷7FGW5ö’‚“ ¢öÆEöÆ–æU÷W6W%ö–BÂW'"ÒöÖ–w&F–öå÷fW&–f–VE÷7V&¦V7B€¢·ÒÀ¢$ÄTt5•ôÄ”äUôÄôt”åô4„ääTÅô”B"À¢¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢FFÒ66÷VçEöÖ–w&F–öå÷F–6¶WE÷7FGW2€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢öÆEöÆ–æU÷W6W%ö–BÀ¢æ6öæf–rÀ¢¢&WGW&â§6öæ–g’†FF ¢ç÷7B‚"ö’ö66÷VçBÖÖ–w&F–öâ÷&VFVVÒ"¢FVb66÷VçEöÖ–w&F–öå÷&VFVVÕö’‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR¢–bæ÷B—6–ç7Fæ6R‡–ÆöBÂF–7B“ ¢&WGW&â§6öæ–g’‡²&ö²#¢fÇ6RÂ&W'&÷"#¢&–çfÆ–E÷&WVW7B'Ò’ÂC ¢æWuöÆ–æU÷W6W%ö–BÂW'"ÒöÖ–w&F–öå÷fW&–f–VE÷7V&¦V7B€¢–ÆöBÀ¢$Ä”äUôÄôt”åô4„ääTÅô”B"À¢¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢FFÂ6öFRÒ&VFVVÕö66÷VçEöÖ–w&F–öå÷F–6¶WB€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢–ÆöBævWB‚&Ö–w&F–öåö6öFR"’À¢æWuöÆ–æU÷W6W%ö–BÀ¢æ6öæf–rÀ¢¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç÷7B‚"ö’ö66÷VçB÷&—f7’×&WVW7B"¢FVb66÷VçE÷&—f7•÷&WVW7Eö’‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢FFÂ6öFRÒ7&VFU÷&—f7•÷&WVW7B†æ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöB¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ævWB‚"ö’öFÖ–â÷7VÖÖ'’"¢FVbFÖ–å÷7VÖÖ'•ö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@¢&WGW&â§6öæ–g’†FÖ–å÷7VÖÖ'’†æ6öæf–u²$DDôd”ÄR%ÒÂæ6öæf–r’ ¢FVb÷W6…ö6×–våöW'&÷%÷&W7öç6R†W†2“ ¢–b—6–ç7Fæ6R†W†2Â6×–väæ÷Df÷VæDW'&÷"“ ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢&6×–våöæ÷Eöf÷VæB'Ò’ÂC@¢–b—6–ç7Fæ6R†W†2Â6×–vä6öæfÆ–7DW'&÷"“ ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢&6×–våö6öæfÆ–7B"Â&FWF–Â#¢7G"†W†2—Ò’ÂC¢&WGW&â§6öæ–g’‡²&W'&÷"#¢&–çfÆ–Eö6×–vâ"Â&FWF–Â#¢7G"†W†2—Ò’ÂC  ¢ævWB‚"ö’öFÖ–â÷W6‚Ö÷F–öç2"¢FVbFÖ–å÷W6…ö÷F–öç5ö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@¢&WGW&â§6öæ–g’€¢°¢&VF–Væ6Uö6öFW2#¢6÷'FVB„TD”Tä4Uô4ôDU2’À¢'FV×ÆFW2#¢6÷'FVB„$õdTEõU4…õDTÕÄDU2’À¢'7FGW5öÆ&VÇ2#¢4Õ”tåõ5DEU5ôÄ$TÅ5õ¤‚À¢&6åö×WFFR#¢7G"‡6W76–öâævWB‚&FÖ–å÷&öÆR"’÷"""’ÓÒ'7WW%öFÖ–â"À¢Ğ¢ ¢ævWB‚"ö’öFÖ–â÷W'6öæÆ—¦VBÖ6†V6¶–â×W6‚÷&Wf–Wr"¢FVbFÖ–å÷W'6öæÆ—¦VEö6†V6¶–å÷W6…÷&Wf–Wuö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@¢&WGW&â§6öæ–g’‡W'6öæÆ—¦VEö6†V6¶–å÷W6…÷&Wf–Wr†æ6öæf–u²$DDôd”ÄR%Ò’ ¢ævWB‚"ö’öFÖ–âö6&B×FV×ÆFW2"¢FVbFÖ–åö6&E÷FV×ÆFW5ö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@¢&WGW&â§6öæ–g’‡²'FV×ÆFW2#¢Æ—7Eö6&E÷FV×ÆFW2†ÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò’—Ò ¢ç÷7B‚"ö’öFÖ–âö6&B×FV×ÆFW2"¢FVbFÖ–åö6&E÷FV×ÆFU÷6fUö’‚“ ¢FVæ–VBÒ÷7WW%öFÖ–åö×WFF–öåöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@¢G'“ ¢FV×ÆFRÒ6fUö6&E÷FV×ÆFR†æ6öæf–u²$DDôd”ÄR%ÒÂ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ò¢W†6WBfÇVTW'&÷"2W†3 ¢&WGW&â§6öæ–g’‡²&ö²#¢fÇ6RÂ&W'&÷"#¢&–çfÆ–E÷FV×ÆFR"Â&ÖW76vR#¢7G"†W†2—Ò’ÂC ¢VæEöFÖ–åöVF—B†æ6öæf–u²$DDôd”ÄR%ÒÂ'W'6öæÆ—¦VEö6&E÷FV×ÆFRç6fR"Â'7V66W72"Â²'FV×ÆFUö–B#¢FV×ÆFU²&–B%×Ò¢&WGW&â§6öæ–g’‡²&ö²#¢G'VRÂ'FV×ÆFR#¢FV×ÆFWÒ’Â# ¢ç÷7B‚"ö’öFÖ–â÷W'6öæÆ—¦VBÖ6†V6¶–â×W6‚ö6&B×&Wf–Wr"¢FVbFÖ–å÷W'6öæÆ—¦VEö6&E÷&Wf–Wuö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢G'“ ¢&W7VÇBÒ&Wf–Wu÷W'6öæÆ—¦VEö6&B†æ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöBævWB‚&Æ–æU÷W6W%ö–B"’Â–ÆöBævWB‚'FV×ÆFUö–B"’¢W†6WBÆöö·WW'&÷"2W†3 ¢&WGW&â§6öæ–g’‡²&ö²#¢fÇ6RÂ&W'&÷"#¢'&Wf–Wu÷Væf–Æ&ÆR"Â&ÖW76vR#¢7G"†W†2—Ò’ÂC@¢&WGW&â§6öæ–g’‡²&ö²#¢G'VRÂ¢§&W7VÇGÒ ¢ævWB‚"ö’öFÖ–âö†öÆ–F’Ö6&Bö6FÆör"¢FVbFÖ–åö†öÆ–F•ö6&Eö6FÆöuö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@¢&WGW&â§6öæ–g’‡²&†öÆ–F—2#¢†öÆ–F•÷FV×ÆFUö6FÆör‡&WVW7Bæ&w2ævWB‚'–V""’÷"æöæR—Ò ¢ç÷7B‚"ö’öFÖ–âö†öÆ–F’Ö6&B÷&ö×B"¢FVbFÖ–åö†öÆ–F•ö6&E÷&ö×Eö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@¢&WGW&â§6öæ–g’‡²&ö²#¢G'VRÂ'&ö×B#¢'V–ÆEö†öÆ–F•ö–ÖvU÷&ö×B‡&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ò—Ò ¢ç÷7B‚"ö’öFÖ–âö†öÆ–F’Ö6&BövVæW&FR"¢FVbFÖ–åö†öÆ–F•ö6&EövVæW&FUö’‚“ ¢FVæ–VBÒ÷7WW%öFÖ–åö×WFF–öåöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@¢FFÂ6öFRÒvVæW&FUö†öÆ–F•ö&6¶w&÷VæB†æ6öæf–rÂ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ò¢VæEöFÖ–åöVF—B†æ6öæf–u²$DDôd”ÄR%ÒÂ&†öÆ–F•ö6&BævVæW&FR"Â'7V66W72"–b6öFRÂCVÇ6R&f–ÆVB"Â²&†öÆ–F’#¢7G"‚‡&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ò’ævWB‚&†öÆ–F’"’÷"""•³£CÒÂ&W'&÷"#¢FFævWB‚&W'&÷""Â""—Ò¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç÷7B‚"ö’öFÖ–â÷W'6öæÆ—¦VBÖ6†V6¶–â×W6‚÷6VæB"¢FVbFÖ–å÷W'6öæÆ—¦VEö6†V6¶–å÷W6…÷6VæEö’‚“ ¢FVæ–VBÒ÷7WW%öFÖ–åö×WFF–öåöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢FFÂ6öFRÒFÖ–å÷6VæE÷W'6öæÆ—¦VEö6†V6¶–åö6&G2€¢æ6öæf–rÀ¢ÖöFS×7G"‡–ÆöBævWB‚&ÖöFR"’÷"""’À¢6öæf—&ÖVC×–ÆöBævWB‚&6öæf—&ÖVB"’—2G'VRÀ¢Æ–æU÷W6W%ö–C×7G"‡–ÆöBævWB‚&Æ–æU÷W6W%ö–B"’÷"""’À¢FV×ÆFUö–C×7G"‡–ÆöBævWB‚'FV×ÆFUö–B"’÷"DTdTÅEô4$EõDTÕÄDU²&–B%Ò’À¢¢VæEöFÖ–åöVF—B€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢'W'6öæÆ—¦VEö6†V6¶–å÷W6‚ç6VæB"À¢'7V66W72"–b6öFRÂCVÇ6R&f–ÆVB"À¢²&ÖöFR#¢–ÆöBævWB‚&ÖöFR"’Â'6VçB#¢FFævWB‚'6VçB"Â’Â&f–ÆVB#¢FFævWB‚&f–ÆVB"Â—ÒÀ¢¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ævWB‚"ö’öFÖ–â÷W6‚Ö6×–vç2"¢FVbFÖ–å÷W6…ö6×–vç5ö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@¢7FFRÒÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò¢&WGW&â§6öæ–g’€¢°¢&6×–vç2#¢Æ—7Eö6×–vç2€¢7FFRÀ¢7FGW3×&WVW7Bæ&w2ævWB‚'7FGW2"Â""’À¢VW'“×&WVW7Bæ&w2ævWB‚'VW'’"Â""’À¢¢Ğ¢ ¢ç÷7B‚"ö’öFÖ–â÷W6‚Ö6×–vç2"¢FVbFÖ–å÷W6…ö6×–våö7&VFUö’‚“ ¢FVæ–VBÒ÷7WW%öFÖ–åö×WFF–öåöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢æ÷rÒ7W'&VçEö÷F–ÖR†æ6öæf–r¢G'“ ¢6×–vâÒ×WFFU÷7FFUöFöÖ–6ÆÇ’€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢ÆÖ&F7FFS¢7&VFUö6×–vâ€¢7FFRÂ–ÆöBÂ7F÷#Ò'7WW%öFÖ–â"Âæ÷sÖæ÷p¢’À¢¢W†6WB„6×–våfÆ–FF–öäW'&÷"Â6×–vä6öæfÆ–7DW'&÷"Â6×–väæ÷Df÷VæDW'&÷"’2W†3 ¢&WGW&â÷W6…ö6×–våöW'&÷%÷&W7öç6R†W†2¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R€¢'W6…ö6×–vâæ7&VFR"Â²&6×–vâ#¢6×–vçÒÂ#¢ ¢ævWB‚"ö’öFÖ–â÷W6‚Ö6×–vç2óÆ6×–våö–Câ"¢FVbFÖ–å÷W6…ö6×–våöFWF–Åö’†6×–våö–B“ ¢FVæ–VBÒöFÖ–åöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@¢G'“ ¢FWF–ÂÒvWEö6×–våöFWF–Â†ÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò’Â6×–våö–B¢W†6WB6×–väæ÷Df÷VæDW'&÷"2W†3 ¢&WGW&â÷W6…ö6×–våöW'&÷%÷&W7öç6R†W†2¢&WGW&â§6öæ–g’†FWF–Â ¢ç÷7B‚"ö’öFÖ–â÷W6‚Ö6×–vç2óÆ6×–våö–CâöVF—B"¢FVbFÖ–å÷W6…ö6×–våöVF—Eö’†6×–våö–B“ ¢FVæ–VBÒ÷7WW%öFÖ–åö×WFF–öåöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢æ÷rÒ7W'&VçEö÷F–ÖR†æ6öæf–r¢G'“ ¢6×–vâÒ×WFFU÷7FFUöFöÖ–6ÆÇ’€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢ÆÖ&F7FFS¢WFFUö6×–vâ€¢7FFRÂ6×–våö–BÂ–ÆöBÂ7F÷#Ò'7WW%öFÖ–â"Âæ÷sÖæ÷p¢’À¢¢W†6WB„6×–våfÆ–FF–öäW'&÷"Â6×–vä6öæfÆ–7DW'&÷"Â6×–väæ÷Df÷VæDW'&÷"’2W†3 ¢&WGW&â÷W6…ö6×–våöW'&÷%÷&W7öç6R†W†2¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R‚'W6…ö6×–vâæVF—B"Â²&6×–vâ#¢6×–vçÒ ¢ç÷7B‚"ö’öFÖ–â÷W6‚Ö6×–vç2óÆ6×–våö–Câ÷&W&R"¢FVbFÖ–å÷W6…ö6×–vå÷&W&Uö’†6×–våö–B“ ¢FVæ–VBÒ÷7WW%öFÖ–åö×WFF–öåöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@¢æ÷rÒ7W'&VçEö÷F–ÖR†æ6öæf–r¢G'“ ¢6×–vâÒ×WFFU÷7FFUöFöÖ–6ÆÇ’€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢ÆÖ&F7FFS¢&W&Uö6×–vâ€¢7FFRÀ¢6×–våö–BÀ¢7F÷#Ò'7WW%öFÖ–â"À¢æ÷sÖæ÷rÀ¢VF–Væ6Uö6Æ76–f–W#×W6…öVF–Væ6Uö6öFRÀ¢’À¢¢W†6WB„6×–våfÆ–FF–öäW'&÷"Â6×–vä6öæfÆ–7DW'&÷"Â6×–väæ÷Df÷VæDW'&÷"’2W†3 ¢&WGW&â÷W6…ö6×–våöW'&÷%÷&W7öç6R†W†2¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R‚'W6…ö6×–vâç&W&R"Â²&6×–vâ#¢6×–vçÒ ¢ç÷7B‚"ö’öFÖ–â÷W6‚Ö6×–vç2óÆ6×–våö–Câ÷66†VGVÆR"¢FVbFÖ–å÷W6…ö6×–vå÷66†VGVÆUö’†6×–våö–B“ ¢FVæ–VBÒ÷7WW%öFÖ–åö×WFF–öåöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢66†VGVÆVEöBÒ'6UöFFWF–ÖR‡–ÆöBævWB‚'66†VGVÆVEöB"’¢æ÷rÒ7W'&VçEö÷F–ÖR†æ6öæf–r¢G'“ ¢6×–vâÒ×WFFU÷7FFUöFöÖ–6ÆÇ’€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢ÆÖ&F7FFS¢66†VGVÆUö6×–vâ€¢7FFRÀ¢6×–våö–BÀ¢66†VGVÆVEöC×66†VGVÆVEöBÀ¢7F÷#Ò'7WW%öFÖ–â"À¢æ÷sÖæ÷rÀ¢’À¢¢W†6WB„6×–våfÆ–FF–öäW'&÷"Â6×–vä6öæfÆ–7DW'&÷"Â6×–väæ÷Df÷VæDW'&÷"’2W†3 ¢&WGW&â÷W6…ö6×–våöW'&÷%÷&W7öç6R†W†2¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R‚'W6…ö6×–vâç66†VGVÆR"Â²&6×–vâ#¢6×–vçÒ ¢ç÷7B‚"ö’öFÖ–â÷W6‚Ö6×–vç2óÆ6×–våö–Câö6æ6VÂ"¢FVbFÖ–å÷W6…ö6×–våö6æ6VÅö’†6×–våö–B“ ¢FVæ–VBÒ÷7WW%öFÖ–åö×WFF–öåöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢æ÷rÒ7W'&VçEö÷F–ÖR†æ6öæf–r¢G'“ ¢6×–vâÒ×WFFU÷7FFUöFöÖ–6ÆÇ’€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢ÆÖ&F7FFS¢6æ6VÅö6×–vâ€¢7FFRÀ¢6×–våö–BÀ¢&V6öå÷¦ƒ×–ÆöBævWB‚'&V6öå÷¦‚"’À¢7F÷#Ò'7WW%öFÖ–â"À¢æ÷sÖæ÷rÀ¢’À¢¢W†6WB„6×–våfÆ–FF–öäW'&÷"Â6×–vä6öæfÆ–7DW'&÷"Â6×–väæ÷Df÷VæDW'&÷"’2W†3 ¢&WGW&â÷W6…ö6×–våöW'&÷%÷&W7öç6R†W†2¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R‚'W6…ö6×–vâæ6æ6VÂ"Â²&6×–vâ#¢6×–vçÒ ¢ævWB‚"ö’öFÖ–â÷W6‚ÖFVÆ—fW&–W2"¢FVbFÖ–å÷W6…öFVÆ—fW&–W5ö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@¢G'“ ¢öfg6WBÒ–çB‡&WVW7Bæ&w2ævWB‚&öfg6WB"Â’¢Æ–Ö—BÒ–çB‡&WVW7Bæ&w2ævWB‚&Æ–Ö—B"ÂS’¢W†6WB…G—TW'&÷"ÂfÇVTW'&÷"“ ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢&–çfÆ–E÷v–æF–öâ'Ò’ÂC ¢7FFRÒÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò¢&WGW&â§6öæ–g’€¢Æ—7EöFVÆ—fW'•÷&V6÷&G2€¢7FFRÀ¢6×–våö–C×&WVW7Bæ&w2ævWB‚&6×–våö–B"Â""’À¢6÷W&6S×&WVW7Bæ&w2ævWB‚'6÷W&6R"Â""’À¢¶–æC×&WVW7Bæ&w2ævWB‚&¶–æB"Â""’À¢7FGW3×&WVW7Bæ&w2ævWB‚'7FGW2"Â""’À¢VF–Væ6Uö6öFS×&WVW7Bæ&w2ævWB‚&VF–Væ6Uö6öFR"Â""’À¢Æã×&WVW7Bæ&w2ævWB‚'Æâ"Â""’À¢ÖVÖ&W#×&WVW7Bæ&w2ævWB‚&ÖVÖ&W""Â""’À¢Æ–æU÷W6W%ö–C×&WVW7Bæ&w2ævWB‚&Æ–æU÷W6W%ö–B"Â""’À¢FFUög&öÓ×&WVW7Bæ&w2ævWB‚&FFUög&öÒ"Â""’À¢FFU÷Fó×&WVW7Bæ&w2ævWB‚&FFU÷Fò"Â""’À¢öfg6WCÖöfg6WBÀ¢Æ–Ö—CÖÆ–Ö—BÀ¢¢ ¢ævWB‚"ö’öFÖ–â÷FW7BÖ6VçFW""¢FVbFÖ–å÷FW7Eö6VçFW%ö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@¢&WGW&â§6öæ–g’†FÖ–å÷FW7Eö6VçFW%÷7FGW2†æ6öæf–u²$DDôd”ÄR%ÒÂæ6öæf–r’ ¢ç÷7B‚"ö’öFÖ–â÷FW7BÖ6VçFW"÷'Vâ"¢FVbFÖ–å÷FW7Eö6VçFW%÷'Våö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VR¢–bFVæ–VC ¢&WGW&âFVæ–V@¢FFÂ6öFRÒ'VåöFÖ–å÷FW7B€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢æ6öæf–rÀ¢&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·ÒÀ¢¢VæEöFÖ–åöVF—B€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢b'FW7Eö6VçFW"ç¶FFævWB‚wFW7Eö–Br’÷"wVæ¶æ÷vâwÒ"À¢'7V66W72"–b6öFRÂCVÇ6R&f–ÆVB"À¢²&‡GG÷7FGW2#¢6öFRÂ'FW7EöÖöFR#¢G'VWÒÀ¢¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ævWB‚"ö’öFÖ–âö66÷VçBÖÖ–w&F–öç2"¢FVbFÖ–åö66÷VçEöÖ–w&F–öç5ö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@¢&WGW&â§6öæ–g’€¢FÖ–åö66÷VçEöÖ–w&F–öç2€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢æ6öæf–rÀ¢¢ ¢ævWB‚"ö’öFÖ–âö&WFÖÖVÖ&W'2"¢FVbFÖ–åö&WFöÖVÖ&W'5ö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@¢&WGW&â§6öæ–g’†&WFöÖVÖ&W'5÷6æ6†÷B†ÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò’’ ¢ævWB‚"ö’öFÖ–âöÆ–æRÖ66WFæ6R"¢FVbFÖ–åöÆ–æUö66WFæ6Uö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@¢&WGW&â§6öæ–g’€¢Æ–æUö66WFæ6U÷6æ6†÷B†ÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò’¢ ¢ç÷7B‚"ö’öFÖ–âöÆ–æRÖ66WFæ6R"¢FVbFÖ–åöÆ–æUö66WFæ6Uö7&VFUö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VR¢–bFVæ–VC ¢&WGW&âFVæ–V@¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢G'“ ¢&W7VÇBÒ×WFFU÷7FFUöFöÖ–6ÆÇ’€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢ÆÖ&F7FFS¢7&VFUöÆ–æUö66WFæ6Uö66R‡7FFRÂ–ÆöB’À¢¢W†6WBfÇVTW'&÷"2W†3 ¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R€¢&Æ–æUö66WFæ6Ræ7&VFR"À¢²&ö²#¢fÇ6RÂ&W'&÷"#¢7G"†W†2—ÒÀ¢CÀ¢¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R€¢&Æ–æUö66WFæ6Ræ7&VFR"À¢²&ö²#¢G'VRÂ¢§&W7VÇGÒÀ¢ ¢çF6‚‚"ö’öFÖ–âöÆ–æRÖ66WFæ6RóÆ66Uö–Câ"¢FVbFÖ–åöÆ–æUö66WFæ6U÷&Wf–Wuö’†66Uö–B“ ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VR¢–bFVæ–VC ¢&WGW&âFVæ–V@¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢G'“ ¢&W7VÇBÒ×WFFU÷7FFUöFöÖ–6ÆÇ’€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢ÆÖ&F7FFS¢&Wf–WuöÆ–æUö66WFæ6Uö66R€¢7FFRÂ66Uö–BÂ–Æö@¢’À¢¢W†6WBfÇVTW'&÷"2W†3 ¢W'&÷"Ò7G"†W†2¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R€¢&Æ–æUö66WFæ6Rç&Wf–Wr"À¢²&ö²#¢fÇ6RÂ&W'&÷"#¢W'&÷'ÒÀ¢CB–bW'&÷"ÓÒ&66WFæ6Uö66Uöæ÷Eöf÷VæB"VÇ6RCÀ¢¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R€¢&Æ–æUö66WFæ6Rç&Wf–Wr"À¢²&ö²#¢G'VRÂ¢§&W7VÇGÒÀ¢ ¢ævWB‚"ö’öFÖ–âö'W6–æW72ÖF6†&ö&B"¢FVbFÖ–åö'W6–æW75öF6†&ö&Eö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@¢&WGW&â§6öæ–g’†FÖ–åö'W6–æW75öF6†&ö&B†æ6öæf–u²$DDôd”ÄR%ÒÂæ6öæf–r’ ¢ævWB‚"ö’öFÖ–â÷6V7W&—G’×&VF–æW72"¢FVbFÖ–å÷6V7W&—G•÷&VF–æW75ö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‡W&Ö—76–öãÒ'7—7FVÒæÖævR"¢–bFVæ–VC ¢&WGW&âFVæ–V@¢&WGW&â§6öæ–g’‡6V7W&—G•÷&VF–æW72†æ6öæf–r’ ¢ævWB‚"ö’öFÖ–âöf–ææ6RöF6†&ö&B"¢FVbFÖ–åöf–ææ6UöF6†&ö&Eö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‡W&Ö—76–öãÒ&f–ææ6RæÖævR"¢–bFVæ–VC ¢&WGW&âFVæ–V@¢ÖöçF‚Ò7G"‡&WVW7Bæ&w2ævWB‚&ÖöçF‚"’÷"7W'&VçEö÷F–ÖR†æ6öæf–r’ç7G&gF–ÖR‚"U’ÒVÒ"’¢G'“ ¢FFÒf–ææ6UöF6†&ö&B†ÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò’ÂÖöçF‚¢W†6WBf–ææ6UfÆ–FF–öäW'&÷"2W†3 ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢&–çfÆ–Eöf–ææ6U÷&WVW7B"Â&ÖW76vR#¢7G"†W†2—Ò’ÂC ¢&WGW&â§6öæ–g’†FF ¢ç÷7B‚"ö’öFÖ–âöf–ææ6RöW‡Vç6W2"¢FVbFÖ–åöf–ææ6UöW‡Vç6Uö7&VFUö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VRÂW&Ö—76–öãÒ&f–ææ6RæÖævR"¢–bFVæ–VC ¢&WGW&âFVæ–V@¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR¢–bæ÷B—6–ç7Fæ6R‡–ÆöBÂF–7B“ ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢&–çfÆ–Eöf–ææ6U÷&WVW7B"Â&ÖW76vR#¢.Š¸¾hùKé¾jÚ>z+®y¨NiJşX{®‹8~ii’'Ò’ÂC ¢G'“ ¢W‡Vç6RÒ×WFFU÷7FFUöFöÖ–6ÆÇ’€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢ÆÖ&F7FFS¢7&VFUöf–ææ6UöW‡Vç6R€¢7FFRÂ–ÆöBÂ7G"‡6W76–öâævWB‚&FÖ–å÷&öÆR"’÷"'Væ¶æ÷vâ"¢’À¢¢W†6WBf–ææ6UfÆ–FF–öäW'&÷"2W†3 ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢&–çfÆ–Eöf–ææ6U÷&WVW7B"Â&ÖW76vR#¢7G"†W†2—Ò’ÂC ¢&WGW&â§6öæ–g’‡²&ö²#¢G'VRÂ&W‡Vç6R#¢W‡Vç6WÒ’Â# ¢çWB‚"ö’öFÖ–âöf–ææ6R÷6WGF–æw2"¢FVbFÖ–åöf–ææ6U÷6WGF–æw5÷WFFUö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VRÂW&Ö—76–öãÒ&f–ææ6RæÖævR"¢–bFVæ–VC ¢&WGW&âFVæ–V@¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR¢–bæ÷B—6–ç7Fæ6R‡–ÆöBÂF–7B“ ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢&–çfÆ–Eöf–ææ6U÷&WVW7B"Â&ÖW76vR#¢.Š¸¾hùKé¾jÚ>z+®y¨NŠŠŞZé®‹8~ii’'Ò’ÂC ¢G'“ ¢6WGF–æw2Ò×WFFU÷7FFUöFöÖ–6ÆÇ’€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢ÆÖ&F7FFS¢WFFUöf–ææ6U÷6WGF–æw2€¢7FFRÂ–ÆöBÂ7G"‡6W76–öâævWB‚&FÖ–å÷&öÆR"’÷"'Væ¶æ÷vâ"¢’À¢¢W†6WBf–ææ6UfÆ–FF–öäW'&÷"2W†3 ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢&–çfÆ–Eöf–ææ6U÷&WVW7B"Â&ÖW76vR#¢7G"†W†2—Ò’ÂC ¢&WGW&â§6öæ–g’‡²&ö²#¢G'VRÂ'6WGF–æw2#¢6WGF–æw7Ò ¢ævWB‚"ö’öFÖ–âö&WF×&öw&Ò"¢FVbFÖ–åö&WF÷&öw&Õö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‡W&Ö—76–öãÒ&&WFæÖævR"¢–bFVæ–VC ¢&WGW&âFVæ–V@¢&WGW&â§6öæ–g’†FÖ–åö&WF÷7VÖÖ'’†æ6öæf–u²$DDôd”ÄR%Ò’ ¢ç÷7B‚"ö’öFÖ–âö&WF×&öw&Òö76–vâ"¢FVbFÖ–åö&WF÷&öw&Õö76–våö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VRÂW&Ö—76–öãÒ&&WFæÖævR"¢–bFVæ–VC ¢&WGW&âFVæ–V@¢FFÂ6öFRÒ76–våö&WFöÖVÖ&W"€¢æ6öæf–u²$DDôd”ÄR%ÒÂ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R‚&&WFæ76–vâ"ÂFFÂ6öFR ¢ç÷7B‚"ö’öFÖ–âö&WFÖÖVÖ&W'2"¢FVbFÖ–åö&WFöÖVÖ&W%ö76–våö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VR¢–bFVæ–VC ¢&WGW&âFVæ–V@¢FFÂ6öFRÒFÖ–åö76–våö&WFöÖVÖ&W"€¢æ6öæf–u²$DDôd”ÄR%ÒÂ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R‚&&WFæ76–vâ"ÂFFÂ6öFR ¢æFVÆWFR‚"ö’öFÖ–âö&WFÖÖVÖ&W'2óÆÆ–æU÷W6W%ö–Câ"¢FVbFÖ–åö&WFöÖVÖ&W%÷&Wfö¶Uö’†Æ–æU÷W6W%ö–B“ ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VR¢–bFVæ–VC ¢&WGW&âFVæ–V@¢FFÂ6öFRÒFÖ–å÷&Wfö¶Uö&WFöÖVÖ&W"€¢æ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–@¢¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R‚&&WFç&Wfö¶R"ÂFFÂ6öFR ¢ævWB‚"ö’öFÖ–âöÖVÖ&W'2óÆÆ–æU÷W6W%ö–CâöÆ–æR×&V&–æB"¢FVbFÖ–åöÖVÖ&W%öÆ–æU÷&V&–æE÷7FGW5ö’†Æ–æU÷W6W%ö–B“ ¢FVæ–VBÒöFÖ–åöwV&B‡W&Ö—76–öãÒ&ÖVÖ&W"æÖævR"¢–bFVæ–VC ¢&WGW&âFVæ–V@¢&WGW&â§6öæ–g’†66÷VçEöÖ–w&F–öå÷F–6¶WE÷7FGW2€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢Æ–æU÷W6W%ö–BÀ¢æ6öæf–rÀ¢’ ¢ç÷7B‚"ö’öFÖ–âöÖVÖ&W'2óÆÆ–æU÷W6W%ö–CâöÆ–æR×&V&–æB"¢FVbFÖ–åöÖVÖ&W%öÆ–æU÷&V&–æEö’†Æ–æU÷W6W%ö–B“ ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VRÂW&Ö—76–öãÒ&ÖVÖ&W"æÖævR"¢–bFVæ–VC ¢&WGW&âFVæ–V@¢FFÂ6öFRÒFÖ–åö7&VFUöÆ–æU÷&V&–æEöÆ–æ²€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢Æ–æU÷W6W%ö–BÀ¢æ6öæf–rÀ¢¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R‚&ÖVÖ&W"æÆ–æU÷&V&–æBæ—77VR"ÂFFÂ6öFR ¢ç÷7B‚"ö’öFÖ–â÷FW7BÖ66÷VçG2óÆÆ–æU÷W6W%ö–Câ÷&W6WB"¢FVbFÖ–å÷FW7Eö66÷VçE÷&W6WEö’†Æ–æU÷W6W%ö–B“ ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VRÂW&Ö—76–öãÒ&ÖVÖ&W"æÖævR"¢–bFVæ–VC ¢&WGW&âFVæ–V@¢–b7G"‡6W76–öâævWB‚&FÖ–å÷&öÆR"’÷"'f–WvW""’Ò'7WW%öFÖ–â# ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢&öæÇ•÷7WW%öFÖ–â"Â&ÖW76vR#¢.Xú®iÈiÈš¹zêynY:XúşKº^˜xŞ{Úî[kŠÎ[‹>‰™ò'Ò’ÂC0¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢–b–ÆöBævWB‚&6öæf—&Ò"’—2æ÷BG'VS ¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R€¢'FW7Eö66÷VçBç&W6WB"À¢²&ö²#¢fÇ6RÂ&W'&÷"#¢&6öæf—&ÖF–öå÷&WV—&VB'ÒÀ¢CÀ¢¢FFÂ6öFRÒFÖ–å÷&W6WE÷FW7Eö66÷VçB€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢Æ–æU÷W6W%ö–BÀ¢ÆÆ÷vVE÷FW7E÷W6W%ö–G3Õ÷FW7EöÆ–æU÷W6W%ö–G2†æ6öæf–r’À¢W‡V7FVE÷fW'6–öã×7G"‡–ÆöBævWB‚&66÷VçE÷7FFU÷fW'6–öâ"’÷"""’À¢7F÷#×7G"‡6W76–öâævWB‚&FÖ–å÷&öÆR"’÷"'7WW%öFÖ–â"’À¢¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R‚'FW7Eö66÷VçBç&W6WB"ÂFFÂ6öFR ¢ævWB‚"ö’öFÖ–âö&WF×&W6WBÖ6æF–FFW2"¢FVbFÖ–åö&WF÷&W6WEö6æF–FFW5ö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‡W&Ö—76–öãÒ&ÖVÖ&W"æÖævR"¢–bFVæ–VC ¢&WGW&âFVæ–V@¢—5÷7WW%öFÖ–âÒ7G"‡6W76–öâævWB‚&FÖ–å÷&öÆR"’÷"'f–WvW""’ÓÒ'7WW%öFÖ–â ¢ÆÆ÷vVE÷FW7E÷W6W%ö–G2Ò÷FW7EöÆ–æU÷W6W%ö–G2†æ6öæf–r¢6æF–FFW2ÒÆ—7Eö&WF÷&W6WEö6æF–FFW2€¢ÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò’À¢ÆÆ÷vVE÷FW7E÷W6W%ö–G2À¢’–b—5÷7WW%öFÖ–âVÇ6RµĞ¢&WGW&â§6öæ–g’‡°¢&ö²#¢G'VRÀ¢&6å÷&W6WB#¢—5÷7WW%öFÖ–âÀ¢&ÖW76vR#¢""–b—5÷7WW%öFÖ–âVÇ6R.Xú®iÈiÈš¹zêynY:XúşKº^˜xŞ{Úî[kŠÎ[‹>‰™ò"À¢'v†—FVÆ—7Eö6öæf–wW&VB#¢&ööÂ†ÆÆ÷vVE÷FW7E÷W6W%ö–G2’À¢&6æF–FFW2#¢6æF–FFW2À¢Ò ¢æFVÆWFR‚"ö’öFÖ–â÷FW7BÖ66÷VçG2óÆÆ–æU÷W6W%ö–Câ"¢FVbFÖ–å÷FW7Eö66÷VçEöFVÆWFUö’†Æ–æU÷W6W%ö–B“ ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VRÂW&Ö—76–öãÒ&ÖVÖ&W"æÖævR"¢–bFVæ–VC ¢&WGW&âFVæ–V@¢FFÂ6öFRÒFÖ–åöFVÆWFU÷FW7Eö66÷VçB€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢Æ–æU÷W6W%ö–BÀ¢ÆÆ÷vVE÷FW7E÷W6W%ö–G3Õ÷FW7EöÆ–æU÷W6W%ö–G2†æ6öæf–r’À¢¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R‚'FW7Eö66÷VçBæFVÆWFR"ÂFFÂ6öFR ¢ævWB‚"ö’öFÖ–âöÆVæ6‚×&VF–æW72"¢FVbFÖ–åöÆVæ6…÷&VF–æW75ö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@¢&WGW&â§6öæ–g’€¢ÆVæ6…÷&VF–æW75÷6æ6†÷B†ÆöE÷7FFR†æ6öæf–u²$DDôd”ÄR%Ò’¢ ¢ç÷7B‚"ö’öFÖ–âöÆVæ6‚×fÆ–FF–öâ"¢FVbFÖ–åöÆVæ6…÷fÆ–FF–öåö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VR¢–bFVæ–VC ¢&WGW&âFVæ–V@¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢G'“ ¢66Væ&–òÒ×WFFU÷7FFUöFöÖ–6ÆÇ’€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢ÆÖ&F7FFS¢&V6÷&EöÆVæ6…÷fÆ–FF–öå÷7FW€¢7FFRÀ¢–ÆöBævWB‚'66Væ&–õö–B"’À¢–ÆöBævWB‚&¶–æB"’À¢–ÆöBævWB‚'7FW"’À¢Æ–æU÷W6W%ö–C×–ÆöBævWB‚&Æ–æU÷W6W%ö–B"’÷"""À¢’À¢¢W†6WBfÇVTW'&÷"2W†3 ¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R€¢&ÆVæ6…÷fÆ–FF–öâç&V6÷&B"À¢²&ö²#¢fÇ6RÂ&W'&÷"#¢7G"†W†2—ÒÀ¢CÀ¢¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R€¢&ÆVæ6…÷fÆ–FF–öâç&V6÷&B"À¢²&ö²#¢G'VRÂ'66Væ&–ò#¢66Væ&–÷ÒÀ¢#À¢ ¢ç÷7B‚"ö’öFÖ–âö&WF×&öw&Ò÷WFFR"¢FVbFÖ–åö&WF÷&öw&Õ÷WFFUö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VRÂW&Ö—76–öãÒ&&WFæÖævR"¢–bFVæ–VC ¢&WGW&âFVæ–V@¢FFÂ6öFRÒWFFUö&WFöÖVÖ&W"€¢æ6öæf–u²$DDôd”ÄR%ÒÂ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R‚&&WFçWFFR"ÂFFÂ6öFR ¢ævWB‚"ö’öFÖ–â÷&—f7’×&WVW7G2"¢FVbFÖ–å÷&—f7•÷&WVW7G5ö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‡W&Ö—76–öãÒ'&—f7’æÖævR"¢–bFVæ–VC ¢&WGW&âFVæ–V@¢&WGW&â§6öæ–g’†FÖ–å÷&—f7•÷&WVW7G2†æ6öæf–u²$DDôd”ÄR%Ò’ ¢ç÷7B‚"ö’öFÖ–â÷&—f7’×&WVW7G2÷WFFR"¢FVbFÖ–å÷&—f7•÷&WVW7G5÷WFFUö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VRÂW&Ö—76–öãÒ'&—f7’æÖævR"¢–bFVæ–VC ¢&WGW&âFVæ–V@¢FFÂ6öFRÒWFFU÷&—f7•÷&WVW7B€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·ÒÀ¢7G"‡6W76–öâævWB‚&FÖ–å÷&öÆR"’÷"'f–WvW""’À¢¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R‚'&—f7’çWFFR"ÂFFÂ6öFR ¢ævWB‚"ö’öFÖ–â÷7W÷'B×F–6¶WG2"¢FVbFÖ–å÷7W÷'E÷F–6¶WG5ö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@¢&WGW&â§6öæ–g’†FÖ–å÷7W÷'E÷F–6¶WG2†æ6öæf–u²$DDôd”ÄR%Ò’ ¢ævWB‚"ö’÷7W÷'B÷F–6¶WG2"¢FVbÖVÖ&W%÷7W÷'E÷F–6¶WG5ö’‚“ ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡·ÒÂW6Uö&w3ÕG'VR¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢FFÂ6öFRÒÖVÖ&W%÷7W÷'E÷F–6¶WG2€¢æ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–@¢¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç÷7B‚"ö’÷7W÷'B÷F–6¶WG2"¢FVbÖVÖ&W%÷7W÷'E÷F–6¶WEö7&VFUö’‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢FFÂ6öFRÒ7&VFU÷7W÷'E÷F–6¶WB†æ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöBÂæ6öæf–r¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ævWB‚"ö’÷&VgVæBöVÆ–v–&ÆRÖ÷&FW'2"¢FVbÖVÖ&W%÷&VgVæF&ÆUö÷&FW'5ö’‚“ ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡·ÒÂW6Uö&w3ÕG'VR¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢FFÂ6öFRÒÖVÖ&W%÷&VgVæF&ÆUö÷&FW'2€¢æ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–BÂæ÷sÖ7W'&VçEö÷F–ÖR†æ6öæf–r¢¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç÷7B‚"ö’÷&VgVæB÷&WVW7G2"¢FVbÖVÖ&W%÷&VgVæE÷&WVW7Eö7&VFUö’‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢FFÂ6öFRÒ7&VFUöÖVÖ&W%÷&VgVæE÷&WVW7B€¢æ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöBÂæ÷sÖ7W'&VçEö÷F–ÖR†æ6öæf–r’Â6öæf–sÖæ6öæf–p¢¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ævWB‚"ö’öFÖ–âö&6·W2"¢FVbFÖ–åö&6·W5öÆ—7Eö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@¢&WGW&â§6öæ–g’†Æ—7EöFÖ–åö&6·W2†æ6öæf–u²$DDôd”ÄR%Ò’ ¢ç÷7B‚"ö’öFÖ–âö&6·W2"¢FVbFÖ–åö&6·W5ö7&VFUö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VRÂW&Ö—76–öãÒ&&6·WæÖævR"¢–bFVæ–VC ¢&WGW&âFVæ–V@¢FFÂ6öFRÒ7&VFUöFÖ–åö&6·W†æ6öæf–u²$DDôd”ÄR%Ò¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R‚&&6·Wæ7&VFR"ÂFFÂ6öFR ¢ç÷7B‚"ö’öFÖ–âö&6·W2÷#""¢FVbFÖ–å÷#%ö&6·Wö7&VFUö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VR¢–bFVæ–VC ¢&WGW&âFVæ–V@¢FFÂ6öFRÒ7&VFU÷#%öVæ7'—FVEö&6·W†æ6öæf–r¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R‚&&6·Wç#"æ7&VFR"ÂFFÂ6öFR ¢ævWB‚"ö’öFÖ–âö&6·W2óÆ&6·Wö–Câ"¢FVbFÖ–åö&6·W5öF÷væÆöEö’†&6·Wö–B“ ¢FVæ–VBÒöFÖ–åöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@¢FFÂ6öFRÒ&VEöFÖ–åö&6·W†æ6öæf–u²$DDôd”ÄR%ÒÂ&6·Wö–B¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç÷7B‚"ö’öFÖ–â÷7W÷'B×&WÇ’"¢FVbFÖ–å÷7W÷'E÷&WÇ•ö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VRÂW&Ö—76–öãÒ'7W÷'BæÖævR"¢–bFVæ–VC ¢&WGW&âFVæ–V@¢FFÂ6öFRÒFÖ–å÷&WÇ•÷7W÷'E÷F–6¶WB†æ6öæf–u²$DDôd”ÄR%ÒÂ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·ÒÂæ6öæf–r¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R‚'7W÷'Bç&WÇ’"ÂFFÂ6öFR ¢ç÷7B‚"ö’öFÖ–â÷6VæB×&VÖ–æFW'2"¢FVb6VæE÷&VÖ–æFW'5ö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VRÂW&Ö—76–öãÒ&æ÷F–f–6F–öâæÖævR"¢–bFVæ–VC ¢&WGW&âFVæ–V@¢FFÂ6öFRÒ6VæEöGVU÷&VÖ–æFW'2†æ6öæf–r¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R‚'&VÖ–æFW"ç6VæB"ÂFFÂ6öFR ¢ç÷7B‚"ö’öFÖ–â÷6VæBÖ6öçF7B×&VÖ–æFW'2"¢FVb6VæEö6öçF7E÷&VÖ–æFW'5ö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VRÂW&Ö—76–öãÒ&æ÷F–f–6F–öâæÖævR"¢–bFVæ–VC ¢&WGW&âFVæ–V@¢FFÂ6öFRÒ6VæEöÖ—76–æuö6öçF7E÷&VÖ–æFW'2†æ6öæf–r¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R‚&6öçF7E÷&VÖ–æFW"ç6VæB"ÂFFÂ6öFR ¢ç÷7B‚"ö’öFÖ–â÷6VæB×&VæWvÂ×&VÖ–æFW'2"¢FVb6VæE÷&VæWvÅ÷&VÖ–æFW'5ö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VRÂW&Ö—76–öãÒ&æ÷F–f–6F–öâæÖævR"¢–bFVæ–VC ¢&WGW&âFVæ–V@¢FFÂ6öFRÒ6VæE÷&VæWvÅ÷&VÖ–æFW'2†æ6öæf–r¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R‚'&VæWvÅ÷&VÖ–æFW"ç6VæB"ÂFFÂ6öFR ¢ç÷7B‚"ö’öFÖ–â÷6VæBÖ&—'F†F’×&VÖ–æFW'2"¢FVb6VæEö&—'F†F•÷&VÖ–æFW'5ö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VRÂW&Ö—76–öãÒ&æ÷F–f–6F–öâæÖævR"¢–bFVæ–VC ¢&WGW&âFVæ–V@¢FFÂ6öFRÒ6VæEö&—'F†F•÷&VÖ–æFW'2†æ6öæf–r¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R‚&&—'F†F•÷&VÖ–æFW"ç6VæB"ÂFFÂ6öFR ¢ç÷7B‚"ö’öFÖ–â÷–ÖVçG2ö6öæf—&Ò"¢FVbFÖ–å÷–ÖVçEö6öæf—&Õö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VRÂW&Ö—76–öãÒ&÷&FW"æÖævR"¢–bFVæ–VC ¢&WGW&âFVæ–V@¢FFÂ6öFRÒ6öæf—&Õ÷–ÖVçEö÷&FW"†æ6öæf–u²$DDôd”ÄR%ÒÂ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·ÒÂæ6öæf–r¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R‚'–ÖVçBæ6öæf—&Ò"ÂFFÂ6öFR ¢ç÷7B‚"ö’öFÖ–â÷–ÖVçG2÷&VgVæB"¢FVbFÖ–å÷–ÖVçE÷&VgVæEö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VR¢–bFVæ–VC ¢&WGW&âFVæ–V@¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢–ÆöE²'&WVW7FVEö'’%ÒÒ&FÖ–å÷6W76–öâ ¢FFÂ6öFRÒ&VgVæE÷–ÖVçEö÷&FW"€¢æ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöBÂæ6öæf–p¢¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R‚'–ÖVçBç&VgVæB"ÂFFÂ6öFR ¢ç÷7B‚"ö’ö7&öâ÷F–6²"¢FVb7&öå÷F–6µö’‚“ ¢6V7&WBÒ&WVW7Bæ†VFW'2ævWB‚%‚Ô7&öâÕ6V7&WB"Â""¢–bæ÷B7&öåöÆÆ÷vVB†æ6öæf–rÂ6V7&WB“ ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢'VæWF†÷&—¦VB'Ò’ÂC¢FFÂ6öFRÒ'Våö7&öå÷F–6²†æ6öæf–r¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç&÷WFR‚"ö’ö7&öâö6öçF7B×&VÖ–æFW'2"ÂÖWF†öG3Õ²$tUB"Â%õ5B%Ò¢FVb7&öåö6öçF7E÷&VÖ–æFW'5ö’‚“ ¢6V7&WBÒ&WVW7Bæ†VFW'2ævWB‚%‚Ô7&öâÕ6V7&WB"Â""¢–bæ÷B7&öåöÆÆ÷vVB†æ6öæf–rÂ6V7&WB“ ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢'VæWF†÷&—¦VB'Ò’ÂC¢FFÂ6öFRÒ6VæEöÖ—76–æuö6öçF7E÷&VÖ–æFW'2†æ6öæf–r¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç&÷WFR‚"ö’ö7&öâö6†V6¶–â×&VÖ–æFW'2"ÂÖWF†öG3Õ²$tUB"Â%õ5B%Ò¢FVb7&öåö6†V6¶–å÷&VÖ–æFW'5ö’‚“ ¢6V7&WBÒ&WVW7Bæ†VFW'2ævWB‚%‚Ô7&öâÕ6V7&WB"Â""¢–bæ÷B7&öåöÆÆ÷vVB†æ6öæf–rÂ6V7&WB“ ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢'VæWF†÷&—¦VB'Ò’ÂC¢2öÖöFSÖ'&öF67Bh‰bf÷&6SÓ(i"˜xŞikhêi*Ş{ZnXZ˜:[{.Š‹¾Xh®iÈ>Y:ûÈY
¾K¸®iz^[{.{ŞX‹ûÈ¢ÖöFRÒ7G"‡&WVW7Bæ&w2ævWB‚&ÖöFR"’÷"""’ç7G&—‚’æÆ÷vW"‚¢f÷&6RÒ7G"‡&WVW7Bæ&w2ævWB‚&f÷&6R"’÷"""’ç7G&—‚’æÆ÷vW"‚’–â²#"Â'G'VR"Â'–W2"Â&öâ'Ğ¢–bÖöFR–â²&'&öF67B"Â'&WW6‚"Â&ÆÂ'Ò÷"f÷&6S ¢FFÂ6öFRÒ'&öF67Eö6†V6¶–å÷&VÖ–æFW'2†æ6öæf–r¢VÇ6S ¢FFÂ6öFRÒ6VæEö6†V6¶–å÷&VÖ–æFW'2†æ6öæf–r¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç&÷WFR‚"ö’ö7&öâö6†V6¶–âÖ'&öF67B"ÂÖWF†öG3Õ²$tUB"Â%õ5B%Ò¢FVb7&öåö6†V6¶–åö'&öF67Eö’‚“ ¢"".˜xŞikhêi*Ş[yJûÉ®[ŞiÈ’Æ–æU÷W6W%ö–By¨NiÈ>Y:˜ikx˜jøşiz^[›>Zè’fÆW8""" ¢6V7&WBÒ&WVW7Bæ†VFW'2ævWB‚%‚Ô7&öâÕ6V7&WB"Â""¢–bæ÷B7&öåöÆÆ÷vVB†æ6öæf–rÂ6V7&WB“ ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢'VæWF†÷&—¦VB'Ò’ÂC¢FFÂ6öFRÒ'&öF67Eö6†V6¶–å÷&VÖ–æFW'2†æ6öæf–r¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç&÷WFR‚"ö’ö7&öâö6†V6¶–â×F&vWFVB×&WW6‚"ÂÖWF†öG3Õ²%õ5B%Ò¢FVb7&öåö6†V6¶–å÷F&vWFVE÷&WW6…ö’‚“ ¢""%&R×6VæBöæÇ’FòW‡Æ–6—FÇ’æÖVB7F—fRÖVÖ&W'3²æWfW"'&öF67Bâ"" ¢6V7&WBÒ&WVW7Bæ†VFW'2ævWB‚%‚Ô7&öâÕ6V7&WB"Â""¢–bæ÷B7&öåöÆÆ÷vVB†æ6öæf–rÂ6V7&WB“ ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢'VæWF†÷&—¦VB'Ò’ÂC¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢FFÂ6öFRÒ6VæE÷F&vWFVEö6†V6¶–å÷&WW6‚€¢æ6öæf–rÂ–ÆöBævWB‚&Æ–æU÷W6W%ö–G2"’÷"µĞ¢¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç&÷WFR‚"ö’ö7&öâö÷fW&GVRÖÆW'G2"ÂÖWF†öG3Õ²$tUB"Â%õ5B%Ò¢FVb7&öåö÷fW&GVUöÆW'G5ö’‚“ ¢6V7&WBÒ&WVW7Bæ†VFW'2ævWB‚%‚Ô7&öâÕ6V7&WB"Â""¢–bæ÷B7&öåöÆÆ÷vVB†æ6öæf–rÂ6V7&WB“ ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢'VæWF†÷&—¦VB'Ò’ÂC¢FFÂ6öFRÒ6VæEöGVU÷&VÖ–æFW'2†æ6öæf–r¢F–Ç’ÂöF–Ç•ö6öFRÒ6VæEöwV&F–åöw&÷WöF–Ç•÷7VÖÖ&–W2†æ6öæf–r¢–b—6–ç7Fæ6R†FFÂF–7B“ ¢FFÒF–7B†FF¢FF²&F–Ç•öw&÷W÷7VÖÖ'’%ÒÒF–Ç¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç&÷WFR‚"ö’ö7&öâ÷&VæWvÂ×&VÖ–æFW'2"ÂÖWF†öG3Õ²$tUB"Â%õ5B%Ò¢FVb7&öå÷&VæWvÅ÷&VÖ–æFW'5ö’‚“ ¢6V7&WBÒ&WVW7Bæ†VFW'2ævWB‚%‚Ô7&öâÕ6V7&WB"Â""¢–bæ÷B7&öåöÆÆ÷vVB†æ6öæf–rÂ6V7&WB“ ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢'VæWF†÷&—¦VB'Ò’ÂC¢FFÂ6öFRÒ6VæE÷&VæWvÅ÷&VÖ–æFW'2†æ6öæf–r¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç&÷WFR‚"ö’ö7&öâö&—'F†F’×&VÖ–æFW'2"ÂÖWF†öG3Õ²$tUB"Â%õ5B%Ò¢FVb7&öåö&—'F†F•÷&VÖ–æFW'5ö’‚“ ¢6V7&WBÒ&WVW7Bæ†VFW'2ævWB‚%‚Ô7&öâÕ6V7&WB"Â""¢–bæ÷B7&öåöÆÆ÷vVB†æ6öæf–rÂ6V7&WB“ ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢'VæWF†÷&—¦VB'Ò’ÂC¢FFÂ6öFRÒ6VæEö&—'F†F•÷&VÖ–æFW'2†æ6öæf–r¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç&÷WFR‚"ö’ö7&öâ÷6Ö'B×&VÖ–æFW'2"ÂÖWF†öG3Õ²$tUB"Â%õ5B%Ò¢FVb7&öå÷6Ö'E÷&VÖ–æFW'5ö’‚“ ¢6V7&WBÒ&WVW7Bæ†VFW'2ævWB‚%‚Ô7&öâÕ6V7&WB"Â""¢–bæ÷B7&öåöÆÆ÷vVB†æ6öæf–rÂ6V7&WB“ ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢'VæWF†÷&—¦VB'Ò’ÂC¢FFÂ6öFRÒ6VæE÷6Ö'E÷&VÖ–æFW'2†æ6öæf–r¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ævWB‚"ö’÷6Ö'B×&VÖ–æFW'2"¢FVb6Ö'E÷&VÖ–æFW'5övWB‚“ ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡·ÒÂW6Uö&w3ÕG'VR¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢&WGW&â§6öæ–g’†vWE÷6Ö'E÷&VÖ–æFW'5÷–ÆöB†æ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–B’ ¢ç÷7B‚"ö’÷6Ö'B×&VÖ–æFW'2"¢FVb6Ö'E÷&VÖ–æFW'5÷÷7B‚“ ¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢FFÂ6öFRÒ6fU÷6Ö'E÷&VÖ–æFW"†æ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöB¢&WGW&â§6öæ–g’†FF’Â6öFP ¢æFVÆWFR‚"ö’÷6Ö'B×&VÖ–æFW'2óÇ&VÖ–æFW%ö–Câ"¢FVb6Ö'E÷&VÖ–æFW'5öFVÆWFR‡&VÖ–æFW%ö–B“ ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡·ÒÂW6Uö&w3ÕG'VR¢–bW'# ¢2Ç6ò66WB¥4ôâ&öG’f÷"6Æ–VçG2F†B6VæBÆ–æU÷W6W%ö–BF†W&P¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÂW'"ÒöWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöB¢–bW'# ¢&WGW&â§6öæ–g’†W'%³Ò’ÂW'%³Ğ¢FFÂ6öFRÒFVÆWFU÷6Ö'E÷&VÖ–æFW"†æ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–BÂ&VÖ–æFW%ö–B¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç&÷WFR‚"ö’ö7&öâöÖVÖ&W'6†—ÖW‡—'’"ÂÖWF†öG3Õ²$tUB"Â%õ5B%Ò¢FVb7&öåöÖVÖ&W'6†—öW‡—'•ö’‚“ ¢6V7&WBÒ&WVW7Bæ†VFW'2ævWB‚%‚Ô7&öâÕ6V7&WB"Â""¢–bæ÷B7&öåöÆÆ÷vVB†æ6öæf–rÂ6V7&WB“ ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢'VæWF†÷&—¦VB'Ò’ÂC¢FFÂ6öFRÒÇ•öW‡—&VE÷ÆåöF÷væw&FW2†æ6öæf–r¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç&÷WFR‚"ö’ö7&öâöFFÖ6ÆVçW"ÂÖWF†öG3Õ²$tUB"Â%õ5B%Ò¢FVb7&öåöFFö6ÆVçWö’‚“ ¢6V7&WBÒ&WVW7Bæ†VFW'2ævWB‚%‚Ô7&öâÕ6V7&WB"Â""¢–bæ÷B7&öåöÆÆ÷vVB†æ6öæf–rÂ6V7&WB“ ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢'VæWF†÷&—¦VB'Ò’ÂC¢FFÂ6öFRÒ6ÆVçWöW‡—&VEöFF†æ6öæf–r¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç&÷WFR‚"ö’ö7&öâö&6¶f–ÆÂÖ&–æBÖæ÷F–g’"ÂÖWF†öG3Õ²$tUB"Â%õ5B%Ò¢FVb7&öåö&6¶f–ÆÅö&–æEöæ÷F–g•ö’‚“ ¢""$öæR×6†÷C¢Š9Îy›ÎjÛ~Xû.[{.{hZé®™¹iky¨N{hZé®h‰X©òÄ”ä^ûÈXj®zØ’&–æEöæ÷F–g•÷6VçEöNûÈ8""" ¢6V7&WBÒ&WVW7Bæ†VFW'2ævWB‚%‚Ô7&öâÕ6V7&WB"Â""¢–bæ÷B7&öåöÆÆ÷vVB†æ6öæf–rÂ6V7&WB“ ¢&WGW&â§6öæ–g’‡²&W'&÷"#¢'VæWF†÷&—¦VB'Ò’ÂC¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢G'•÷'VâÒ7G"€¢&WVW7Bæ&w2ævWB‚&G'•÷'Vâ"¢÷"–ÆöBævWB‚&G'•÷'Vâ"¢÷"" ¢’ç7G&—‚’æÆ÷vW"‚’–â²#"Â'G'VR"Â'–W2"Â&öâ'Ğ¢G'“ ¢Æ–Ö—BÒ–çB‡&WVW7Bæ&w2ævWB‚&Æ–Ö—B"’÷"–ÆöBævWB‚&Æ–Ö—B"’÷"¢W†6WB…G—TW'&÷"ÂfÇVTW'&÷"“ ¢Æ–Ö—BÒ ¢FFÂ6öFRÒ&6¶f–ÆÅö&–æEöæ÷F–g’†æ6öæf–rÂG'•÷'VãÖG'•÷'VâÂÆ–Ö—CÖÆ–Ö—B¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ævWB‚"ö’öFÖ–â÷&–6‚ÖÖVçR"¢FVbFÖ–å÷&–6…öÖVçUö–ç7V7Eö’‚“ ¢"".iú^Šš.yºîX˜Şš	ŠŠŞYÉnih~˜YjîûÈY
¾Kˆ˜Û^˜(Š¸²U$ûÈ8.KˆŞY¹îX+2Fö¶Vî8""" ¢FVæ–VBÒöFÖ–åöwV&B‚¢–bFVæ–VC ¢&WGW&âFVæ–V@¢FFÂ6öFRÒ–ç7V7EöFVfVÇE÷&–6…öÖVçR†æ6öæf–r¢&WGW&â§6öæ–g’†FF’Â6öFP ¢ç÷7B‚"ö’öFÖ–â÷&–6‚ÖÖVçRöFWÆ÷’"¢FVbFÖ–å÷&–6…öÖVçUöFWÆ÷•ö’‚“ ¢"".yJ‚&VæFW"Kˆ®y¨BÄ”äUô4„ääTÅô44U55õDô´TâKˆ®X+>KŠnŠŠŞx+®š	ŠŠŞYÉnih~˜Yjî8""" ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VRÂW&Ö—76–öãÒ'7—7FVÒæÖævR"¢–bFVæ–VC ¢&WGW&âFVæ–V@¢FFÂ6öFRÒFWÆ÷•öFVfVÇE÷&–6…öÖVçR†æ6öæf–r¢–bFFævWB‚&ö²"“ ¢æÆövvW"æ–æfò€¢'&–6‚ÖVçRFWÆ÷–VB&–6„ÖVçT–CÒW2æÖSÒW2"À¢FFævWB‚'&–6„ÖVçT–B"’À¢FFævWB‚&æÖR"’À¢¢VÇ6S ¢æÆövvW"çv&æ–ær€¢'&–6‚ÖVçRFWÆ÷’f–ÆVB7FWÒW2‡GGÒW2"À¢FFævWB‚'7FW"’À¢FFævWB‚&‡GG"’À¢¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R‚'&–6…öÖVçRæFWÆ÷’"ÂFFÂ6öFR ¢ç÷7B‚"ö’öFÖ–â÷W6‚×vVÆ6öÖR"¢FVbFÖ–å÷W6…÷vVÆ6öÖUö’‚“ ¢"".zêynY:Š9ÎhêjÚ‹øâfÆWûÈ™È[{.XªZ[ŞXø¾ûÈ8&&öG“¢¶Æ–æU÷W6W%ö–BÂF—7Æ•öæÖS÷Ò"" ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VRÂW&Ö—76–öãÒ&æ÷F–f–6F–öâæÖævR"¢–bFVæ–VC ¢&WGW&âFVæ–V@¢–bÆ–æT&÷D’—2æöæR÷"fÆW…6VæDÖW76vR—2æöæR÷"vVÆ6öÖUöfÆW‚—2æöæS ¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R€¢'vVÆ6öÖRçW6‚"À¢²&ö²#¢fÇ6RÂ&W'&÷"#¢&Æ–æR6F²÷"vVÆ6öÖUöfÆW‚Væf–Æ&ÆR'ÒÀ¢S2À¢¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢Æ–æU÷W6W%ö–BÒ7G"‡–ÆöBævWB‚&Æ–æU÷W6W%ö–B"’÷"""’ç7G&—‚¢–bæ÷BÆ–æU÷W6W%ö–C ¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R€¢'vVÆ6öÖRçW6‚"À¢²&ö²#¢fÇ6RÂ&W'&÷"#¢&Ö—76–ærÆ–æU÷W6W%ö–B'ÒÀ¢CÀ¢¢Fö¶VâÒ€¢æ6öæf–rævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"¢÷"÷2æVçf—&öâævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"¢÷"" ¢’ç7G&—‚¢–bæ÷BFö¶Vã ¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R€¢'vVÆ6öÖRçW6‚"À¢²&ö²#¢fÇ6RÂ&W'&÷"#¢$Ä”äUô4„ääTÅô44U55õDô´Tâæ÷B6WB'ÒÀ¢S2À¢¢Æ–æUö&÷Eö’ÒÆ–æT&÷D’‡Fö¶Vâ¢†–çBÒ7G"‡–ÆöBævWB‚&F—7Æ•öæÖR"’÷"""’ç7G&—‚’÷"æöæP¢&W6öÇfVBÒ&W6öÇfU÷vVÆ6öÖUöF—7Æ•öæÖR€¢Æ–æUö&÷Eö“ÖÆ–æUö&÷Eö’À¢FFöf–ÆSÖæ6öæf–u²$DDôd”ÄR%ÒÀ¢Æ–æU÷W6W%ö–CÖÆ–æU÷W6W%ö–BÀ¢†–çCÖ†–çBÀ¢ÆövvW#ÖæÆövvW"À¢¢G'“ ¢&Vv—7FW%öÆ–æU÷W6W"€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢²&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–BÂ&F—7Æ•öæÖR#¢&W6öÇfVB÷"$Ä”äRKÛşyJˆR'ÒÀ¢¢W†6WBW†6WF–öâ2W†3 ¢æÆövvW"çv&æ–ær‚&FÖ–âW6‚×vVÆ6öÖR&Vv—7FW"f–ÆVC¢W2"ÂW†2¢6öçFVçG2ÒvVÆ6öÖUöfÆW‚‡&W6öÇfVB¢w&VWF–ærÒ€¢vVÆ6öÖUöw&VWF–æu÷FW‡B‡&W6öÇfVB¢–bvVÆ6öÖUöw&VWF–æu÷FW‡B—2æ÷BæöæP¢VÇ6R†b/	ù²·&W6öÇfVGÒh*Z[ŞûÈÎjÚ‹øîXªXZ^8Îjøşiz^[›>Zè8Ò"–b&W6öÇfVBVÇ6R/	ù²h*Z[ŞûÈÎjÚ‹øîXªXZ^8Îjøşiz^[›>Zè8Ò"¢¢ÇE÷FW‡BÒ€¢b.jøşiz^[›>ZèûÙÇ·&W6öÇfVGÒh*Z[ŞûÈÎjÚ‹øîXªXZR ¢–b&W6öÇfV@¢VÇ6R.jøşiz^[›>ZèûÙÎh*Z[ŞûÈÎjÚ‹øîXªXZR ¢¢G'“ ¢Æ–æUö&÷Eö’çW6…öÖW76vR€¢Æ–æU÷W6W%ö–BÀ¢fÆW…6VæDÖW76vR†ÇE÷FW‡CÖÇE÷FW‡BÂ6öçFVçG3Ö6öçFVçG2’À¢¢æÆövvW"æ–æfò€¢&FÖ–âW6‚×vVÆ6öÖRö²W6W#ÒW2æÖSÒW""À¢Æ–æU÷W6W%ö–E³£…ÒÀ¢&W6öÇfVB÷"""À¢¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R€¢'vVÆ6öÖRçW6‚"À¢°¢&ö²#¢G'VRÀ¢&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–BÀ¢&F—7Æ•öæÖR#¢&W6öÇfVBÀ¢&w&VWF–ær#¢w&VWF–ærÀ¢ÒÀ¢¢W†6WBÆ–æT&÷D”W'&÷"2W†3 ¢FWF–ÂÒ7G"†W†2¢G'“ ¢FWF–ÂÒvWFGG"†W†2Â&W'&÷""ÂæöæR’÷"FWF–À¢W†6WBW†6WF–öã ¢70¢æÆövvW"æW†6WF–öâ‚&FÖ–âW6‚×vVÆ6öÖRÄ”äRW'&÷#¢W2"ÂFWF–Â¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R€¢'vVÆ6öÖRçW6‚"À¢²&ö²#¢fÇ6RÂ&W'&÷"#¢&Æ–æUö•öW'&÷""Â&FWF–Â#¢7G"†FWF–Â—ÒÀ¢S"À¢¢W†6WBW†6WF–öâ2W†3 ¢æÆövvW"æW†6WF–öâ‚&FÖ–âW6‚×vVÆ6öÖRf–ÆVC¢W2"ÂW†2¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R€¢'vVÆ6öÖRçW6‚"À¢²&ö²#¢fÇ6RÂ&W'&÷"#¢7G"†W†2—ÒÀ¢SÀ¢ ¢ç÷7B‚"ö’öFÖ–â÷W6W"×Æâ"¢FVbFÖ–å÷W6W%÷Æåö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VRÂW&Ö—76–öãÒ&ÖVÖ&W"æÖævR"¢–bFVæ–VC ¢&WGW&âFVæ–V@¢FFÂ6öFRÒFÖ–å÷WFFU÷W6W%÷Æâ†æ6öæf–u²$DDôd”ÄR%ÒÂ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ò¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R‚'W6W%÷ÆâçWFFR"ÂFFÂ6öFR ¢ç÷7B‚"ö’öFÖ–âöÖVÖ&W"ÖÆö6F–öâ"¢FVbFÖ–åöÖVÖ&W%öÆö6F–öåö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VRÂW&Ö—76–öãÒ&ÖVÖ&W"æÖævR"¢–bFVæ–VC ¢&WGW&âFVæ–V@¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢FFÂ6öFRÒWFFUöÖVÖ&W%öÆö6F–öâ€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢–ÆöBævWB‚&Æ–æU÷W6W%ö–B"’À¢–ÆöBÀ¢6÷W&6SÒ&FÖ–â"À¢¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R‚&ÖVÖ&W%öÆö6F–öâçWFFR"ÂFFÂ6öFR ¢ç÷7B‚"ö’öFÖ–â÷6WBÖ6÷&RÖwV&F–â"¢FVbFÖ–å÷6WEö6÷&UöwV&F–åö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VRÂW&Ö—76–öãÒ&ÖVÖ&W"æÖævR"¢–bFVæ–VC ¢&WGW&âFVæ–V@¢FFÂ6öFRÒFÖ–å÷6WEö6÷&UöwV&F–â†æ6öæf–u²$DDôd”ÄR%ÒÂ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ò¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R‚&6÷&UöwV&F–âç6WB"ÂFFÂ6öFR ¢ç÷7B‚"ö’öFÖ–âö–æ6–FVçG2÷&W6öÇfR"¢FVbFÖ–åö–æ6–FVçE÷&W6öÇfUö’‚“ ¢FVæ–VBÒöFÖ–åöwV&B‡w&—FSÕG'VRÂW&Ö—76–öãÒ&–æ6–FVçBæÖævR"¢–bFVæ–VC ¢&WGW&âFVæ–V@¢–ÆöBÒ&WVW7BævWEö§6öâ‡6–ÆVçCÕG'VR’÷"·Ğ¢FFÂ6öFRÒ&W6öÇfUöFÖ–åö–æ6–FVçB€¢æ6öæf–u²$DDôd”ÄR%ÒÀ¢–ÆöBÀ¢6W76–öâævWB‚&FÖ–å÷&öÆR"’À¢¢&WGW&âöFÖ–åö×WFF–öå÷&W7öç6R€¢&–æ6–FVçBç&W6öÇfR"À¢FFÀ¢6öFRÀ¢ ¢&WGW&â   ¦6Æ72Ö–æ•&W7öç6S ¢FVbõö–æ—Eõò‡6VÆbÂFFÂ7FGW5ö6öFSÓ#Â†VFW'3ÔæöæR“ ¢6VÆbåöFFÒFF¢6VÆbç7FGW5ö6öFRÒ7FGW5ö6öFP¢6VÆbæ†VFW'2Ò†VFW'2÷"·Ğ ¢FVbvWEö§6öâ‡6VÆb“ ¢&WGW&â6VÆbåöFF ¢FVb6Æ÷6R‡6VÆb“ ¢&WGW&âæöæP ¢FVbvWEöFF‡6VÆbÂ5÷FW‡CÔfÇ6R“ ¢–b—6–ç7Fæ6R‡6VÆbåöFFÂ'—FW2“ ¢&WGW&â6VÆbåöFFæFV6öFR‚'WFbÓ‚"’–b5÷FW‡BVÇ6R6VÆbåöFF¢–b—6–ç7Fæ6R‡6VÆbåöFFÂ7G"“ ¢&WGW&â6VÆbåöFF–b5÷FW‡BVÇ6R6VÆbåöFFæVæ6öFR‚'WFbÓ‚"¢&VæFW&VBÒ§6öâæGV×2‡6VÆbåöFFÂVç7W&Uö66–“ÔfÇ6R¢&WGW&â&VæFW&VB–b5÷FW‡BVÇ6R&VæFW&VBæVæ6öFR‚'WFbÓ‚"  ¦6Æ72Ö–æ”6Æ–VçC ¢FVbõö–æ—Eõò‡6VÆbÂ“ ¢6VÆbæÒ  ¢FVbvWB‡6VÆbÂF‚Â†VFW'3ÔæöæR“ ¢&÷WFRÂòÂVW'’ÒF‚ç'F—F–öâ‚#ò"¢–b&÷WFRÓÒ"ö’öFÖ–â"÷"&÷WFRç7F'G7v—F‚‚"ö’öFÖ–âò"“ ¢&WGW&âÖ–æ•&W7öç6R‡²&W'&÷"#¢&FÖ–åöæ÷Eö6öæf–wW&VB'ÒÂS2¢&×2ÒF–7B‡W&ÆÆ–"ç'6Rç'6U÷6Â‡VW'’’¢†VFW'2Ò†VFW'2÷"·Ğ¢–b&÷WFRÓÒ"ö’ö6öæf–r# ¢&WGW&âÖ–æ•&W7öç6R†ö6öæf–r‡6VÆbææ6öæf–r’¢–b&÷WFRÓÒ"ö†VÇF‚# ¢&WGW&âÖ–æ•&W7öç6R‡²&ö²#¢G'VWÒ¢–b&÷WFR–â‚"÷&ö&÷G2çG‡B"Â"÷6—FVÖç†ÖÂ"“ ¢f–ÆVæÖRÒ&÷WFRæÇ7G&—‚"ò"¢F…öö&¢ÒF‚…õöf–ÆUõò’ç&W6öÇfR‚’ç&VçBòf–ÆVæÖP¢–bF…öö&¢æW†—7G2‚“ ¢&WGW&âÖ–æ•&W7öç6R‡F…öö&¢ç&VE÷FW‡B†Væ6öF–æsÒ'WFbÓ‚"’¢&WGW&âÖ–æ•&W7öç6R‡²&W'&÷"#¢&æ÷Bf÷VæB'ÒÂCB¢–b&÷WFR–â‚"÷FW&×2"Â"÷&—f7’"“ ¢&WGW&âÖ–æ•&W7öç6R‡²&ö²#¢G'VWÒ¢–b&÷WFRÓÒ"öÆ–fböÖ–w&FRæ‡FÖÂ# ¢&WGW&âÖ–æ•&W7öç6R‡²&ö²#¢G'VWÒ¢–b&÷WFRÓÒ"öÆ–fb÷6÷2æ‡FÖÂ# ¢F…öö&¢ÒF‚…õöf–ÆUõò’ç&W6öÇfR‚’ç&VçBò&Æ–fb"ò'6÷2æ‡FÖÂ ¢–bF…öö&¢æW†—7G2‚“ ¢&WGW&âÖ–æ•&W7öç6R‡F…öö&¢ç&VE÷FW‡B†Væ6öF–æsÒ'WFbÓ‚"’¢&WGW&âÖ–æ•&W7öç6R‡²&W'&÷"#¢&æ÷Bf÷VæB'ÒÂCB¢–b&÷WFRÓÒ"öÆ–fbööæ&ö&F–ær# ¢Æ–feö–BÒ7G"‡6VÆbææ6öæf–rævWB‚$Ä”deô”B"’÷"DTdTÅEôÄ”deô”B’ç7G&—‚¢&WGW&âÖ–æ•&W7öç6R€¢²&ö²#¢G'VWÒÀ¢3"À¢²$Æö6F–öâ#¢b&‡GG3¢òöÆ–fbæÆ–æRæÖR÷¶Æ–feö–GÓö÷VãÖöæ&ö&F–ær'ÒÀ¢¢–b&÷WFRÓÒ"ö’÷7FGW2# ¢Æ–æU÷W6W%ö–BÂW'"ÒWF†VçF–6FVEöÆ–æU÷W6W"€¢·ÒÂ&w3×&×2Â†VFW'3Ö†VFW'2Â6öæf–s×6VÆbææ6öæf–p¢¢–bW'# ¢&WGW&âÖ–æ•&W7öç6R†W'%³ÒÂW'%³Ò¢&öG’Â6öFRÒ7FGW5öf÷%÷W6W"€¢6VÆbææ6öæf–u²$DDôd”ÄR%ÒÀ¢Æ–æU÷W6W%ö–BÀ¢&×2ævWB‚&F—7Æ•öæÖR"’À¢¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’ööæ&ö&F–ær# ¢Æ–æU÷W6W%ö–BÂW'"ÒWF†VçF–6FVEöÆ–æU÷W6W"€¢·ÒÂ&w3×&×2Â†VFW'3Ö†VFW'2Â6öæf–s×6VÆbææ6öæf–p¢¢–bW'# ¢&WGW&âÖ–æ•&W7öç6R†W'%³ÒÂW'%³Ò¢&öG’Â6öFRÒöæ&ö&F–æu÷7FGW5÷–ÆöB€¢6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–@¢¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’ööæ&ö&F–ær÷7FFR# ¢Æ–æU÷W6W%ö–BÂW'"ÒWF†VçF–6FVEöÆ–æU÷W6W"€¢·ÒÂ&w3×&×2Â†VFW'3Ö†VFW'2Â6öæf–s×6VÆbææ6öæf–p¢¢–bW'# ¢&WGW&âÖ–æ•&W7öç6R†W'%³ÒÂW'%³Ò¢&öG’Â6öFRÒöæ&ö&F–æu÷7FGW5÷–ÆöB€¢6VÆbææ6öæf–u²$DDôd”ÄR%ÒÀ¢Æ–æU÷W6W%ö–BÀ¢ÆÆ÷uöÖ—76–æu÷&öf–ÆSÕG'VRÀ¢¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’öwV&F–âÖw&÷W2÷6WGF–æw2# ¢Æ–æU÷W6W%ö–BÂW'"ÒWF†VçF–6FVEöÆ–æU÷W6W"€¢·ÒÂ&w3×&×2Â†VFW'3Ö†VFW'2Â6öæf–s×6VÆbææ6öæf–p¢¢–bW'# ¢&WGW&âÖ–æ•&W7öç6R†W'%³ÒÂW'%³Ò¢&öG’Â6öFRÒwV&F–åöw&÷W÷6WGF–æw5öf÷%÷W6W"€¢6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–@¢¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’öwV&F–âÖw&÷W2÷7FGW2# ¢Æ–æU÷W6W%ö–BÂW'"ÒWF†VçF–6FVEöÆ–æU÷W6W"€¢·ÒÂ&w3×&×2Â†VFW'3Ö†VFW'2Â6öæf–s×6VÆbææ6öæf–p¢¢–bW'# ¢&WGW&âÖ–æ•&W7öç6R†W'%³ÒÂW'%³Ò¢&öG’Â6öFRÒwV&F–åöw&÷WöF–Ç•÷7FGW2€¢6VÆbææ6öæf–u²$DDôd”ÄR%ÒÀ¢Æ–æU÷W6W%ö–BÀ¢&×2ævWB‚&w&÷Wö–B"’À¢¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’öFÖ–â÷7VÖÖ'’# ¢FVæ–VBÒFÖ–åöWF…öW'&÷%÷–ÆöB‡6VÆbææ6öæf–rÂ&×2ævWB‚'77v÷&B"Â""’¢–bFVæ–VC ¢–ÆöBÂ6öFRÒFVæ–V@¢&WGW&âÖ–æ•&W7öç6R‡–ÆöBÂ6öFR¢&WGW&âÖ–æ•&W7öç6R†FÖ–å÷7VÖÖ'’‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ6VÆbææ6öæf–r’¢–b&÷WFRÓÒ"ö’öFÖ–â÷7W÷'B×F–6¶WG2# ¢–bæ÷BFÖ–åöÆÆ÷vVB‡6VÆbææ6öæf–rÂ&×2ævWB‚'77v÷&B"Â""’“ ¢&WGW&âÖ–æ•&W7öç6R‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢&WGW&âÖ–æ•&W7öç6R†FÖ–å÷7W÷'E÷F–6¶WG2‡6VÆbææ6öæf–u²$DDôd”ÄR%Ò’¢–b&÷WFRÓÒ"ö’÷7W÷'B÷F–6¶WG2# ¢Æ–æU÷W6W%ö–BÂW'"ÒWF†VçF–6FVEöÆ–æU÷W6W"€¢·ÒÂ&w3×&×2Â†VFW'3Ö†VFW'2Â6öæf–s×6VÆbææ6öæf–p¢¢–bW'# ¢&WGW&âÖ–æ•&W7öç6R†W'%³ÒÂW'%³Ò¢&öG’Â6öFRÒÖVÖ&W%÷7W÷'E÷F–6¶WG2€¢6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–@¢¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’÷&VgVæBöVÆ–v–&ÆRÖ÷&FW'2# ¢Æ–æU÷W6W%ö–BÂW'"ÒWF†VçF–6FVEöÆ–æU÷W6W"€¢·ÒÂ&w3×&×2Â†VFW'3Ö†VFW'2Â6öæf–s×6VÆbææ6öæf–p¢¢–bW'# ¢&WGW&âÖ–æ•&W7öç6R†W'%³ÒÂW'%³Ò¢&öG’Â6öFRÒÖVÖ&W%÷&VgVæF&ÆUö÷&FW'2€¢6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–BÂæ÷sÖ7W'&VçEö÷F–ÖR‡6VÆbææ6öæf–r¢¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’öFÖ–âö&6·W2# ¢–bæ÷BFÖ–åöÆÆ÷vVB‡6VÆbææ6öæf–rÂ&×2ævWB‚'77v÷&B"Â""’“ ¢&WGW&âÖ–æ•&W7öç6R‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢&WGW&âÖ–æ•&W7öç6R†Æ—7EöFÖ–åö&6·W2‡6VÆbææ6öæf–u²$DDôd”ÄR%Ò’¢–b&÷WFRç7F'G7v—F‚‚"ö’öFÖ–âö&6·W2ò"“ ¢–bæ÷BFÖ–åöÆÆ÷vVB‡6VÆbææ6öæf–rÂ&×2ævWB‚'77v÷&B"Â""’“ ¢&WGW&âÖ–æ•&W7öç6R‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢&6·Wö–BÒ&÷WFRç'7Æ—B‚"ò"Â•²ÓĞ¢&öG’Â6öFRÒ&VEöFÖ–åö&6·W‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ&6·Wö–B¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’ö6öçF7G2# ¢&WGW&âÖ–æ•&W7öç6R†vWEö6öçF7G2‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ&×2ævWB‚&Æ–æU÷W6W%ö–B"’’¢–b&÷WFRÓÒ"ö’öVÖW&vVæ7’Ö6öçF7Bö–çf—FR×&Wf–Wr# ¢Æ–æU÷W6W%ö–BÂW'"ÒWF†VçF–6FVEöÆ–æU÷W6W"€¢·ÒÂ&w3×&×2Â†VFW'3Ö†VFW'2Â6öæf–s×6VÆbææ6öæf–p¢¢–bW'# ¢&WGW&âÖ–æ•&W7öç6R†W'%³ÒÂW'%³Ò¢&öG’Â6öFRÒ–çf—FUö&–æE÷&Wf–Wr€¢6VÆbææ6öæf–u²$DDôd”ÄR%ÒÀ¢°¢&–çf—FUög&öÒ#¢&×2ævWB‚&–çf—FUög&öÒ"’÷"&×2ævWB‚&g&öÒ"’÷"""À¢&–çf—FU÷Fö¶Vâ#¢&×2ævWB‚&–çf—FU÷Fö¶Vâ"’÷"""À¢&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–BÀ¢ÒÀ¢¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’ö6ÆVæF"Öæ÷FW2# ¢Æ–æU÷W6W%ö–BÂW'"ÒWF†VçF–6FVEöÆ–æU÷W6W"€¢·ÒÂ&w3×&×2Â†VFW'3Ö†VFW'2Â6öæf–s×6VÆbææ6öæf–p¢¢–bW'# ¢&WGW&âÖ–æ•&W7öç6R†W'%³ÒÂW'%³Ò¢&öG’ÒvWEö6ÆVæF%öæ÷FW2‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–B¢&WGW&âÖ–æ•&W7öç6R†&öG’Â#–b&öG’ævWB‚&ö²"’VÇ6RC2¢–b&÷WFRÓÒ"ö’÷6Ö'B×&VÖ–æFW'2# ¢Æ–æU÷W6W%ö–BÂW'"ÒWF†VçF–6FVEöÆ–æU÷W6W"€¢·ÒÂ&w3×&×2Â†VFW'3Ö†VFW'2Â6öæf–s×6VÆbææ6öæf–p¢¢–bW'# ¢&WGW&âÖ–æ•&W7öç6R†W'%³ÒÂW'%³Ò¢&WGW&âÖ–æ•&W7öç6R€¢vWE÷6Ö'E÷&VÖ–æFW'5÷–ÆöB€¢6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–@¢¢¢–b&÷WFRÓÒ"ö’ög&–VæG2öÆö6F–öç2# ¢&WGW&âÖ–æ•&W7öç6R†g&–VæEöÆö6F–öç2‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ&×2ævWB‚&Æ–æU÷W6W%ö–B"’’¢–b&÷WFRÓÒ"ö’öÆö6F–öâ÷7FGW2# ¢Æ–æU÷W6W%ö–BÒ&×2ævWB‚&Æ–æU÷W6W%ö–B"¢–bæ÷BÆ–æU÷W6W%ö–C ¢&WGW&âÖ–æ•&W7öç6R‡²&W'&÷"#¢&Ö—76–ærÆ–æU÷W6W%ö–B'ÒÂC¢&öf–ÆRÒvWE÷&öf–ÆR†ÆöE÷7FFR‡6VÆbææ6öæf–u²$DDôd”ÄR%Ò’ÂÆ–æU÷W6W%ö–B¢&WGW&âÖ–æ•&W7öç6R‡²&ö²#¢G'VRÂ'6fWG•öwV&B#¢6fWG•öwV&E÷6æ6†÷B‡&öf–ÆR—Ò¢&WGW&âÖ–æ•&W7öç6R‡²&W'&÷"#¢&æ÷Bf÷VæB'ÒÂCB ¢FVb÷7B‡6VÆbÂF‚ÂFFÔæöæRÂ6öçFVçE÷G—SÔæöæRÂ†VFW'3ÔæöæRÂ¢¦·v&w2“ ¢&÷WFRÂòÂVW'’ÒF‚ç'F—F–öâ‚#ò"¢–b&÷WFRÓÒ"ö’öFÖ–â"÷"&÷WFRç7F'G7v—F‚‚"ö’öFÖ–âò"“ ¢&WGW&âÖ–æ•&W7öç6R‡²&W'&÷"#¢&FÖ–åöæ÷Eö6öæf–wW&VB'ÒÂS2¢&×2ÒF–7B‡W&ÆÆ–"ç'6Rç'6U÷6Â‡VW'’’¢†VFW'2Ò†VFW'2÷"·Ğ¢7&öå÷6V7&WBÒ€¢†VFW'2ævWB‚%‚Ô7&öâÕ6V7&WB"¢÷"†VFW'2ævWB‚'‚Ö7&öâ×6V7&WB"¢÷"" ¢¢–ÆöBÒ·Ğ¢§6öå÷–ÆöBÒ·v&w2ævWB‚&§6öâ"¢–b—6–ç7Fæ6R†§6öå÷–ÆöBÂF–7B“ ¢–ÆöBÒF–7B†§6öå÷–ÆöB¢VÆ–bFFæB6öçFVçE÷G—RÓÒ&Æ–6F–öâö§6öâ# ¢–ÆöBÒ§6öâæÆöG2†FF¢–b&÷WFRÓÒ"ö’öÆ–æR÷&Vv—7FW"# ¢&öG’Â6öFRÒ&Vv—7FW%öÆ–æU÷W6W"‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöB¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’ö6†V6¶–â# ¢Æ–æU÷W6W%ö–BÂW'"ÒWF†VçF–6FVEöÆ–æU÷W6W"€¢–ÆöBÂ&w3×&×2Â†VFW'3Ö†VFW'2Â6öæf–s×6VÆbææ6öæf–p¢¢–bW'# ¢&WGW&âÖ–æ•&W7öç6R†W'%³ÒÂW'%³Ò¢&W7VÇBÂ6öFRÒ6†V6¶–åöf÷%÷W6W"€¢6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–BÂ–ÆöBÂ6VÆbææ6öæf–p¢¢&WGW&âÖ–æ•&W7öç6R‡&W7VÇBÂ6öFR¢–b&÷WFRÓÒ"ö’ööæ&ö&F–ær÷&VÖ–æFW"# ¢Æ–æU÷W6W%ö–BÂW'"ÒWF†VçF–6FVEöÆ–æU÷W6W"€¢–ÆöBÂ&w3×&×2Â†VFW'3Ö†VFW'2Â6öæf–s×6VÆbææ6öæf–p¢¢–bW'# ¢&WGW&âÖ–æ•&W7öç6R†W'%³ÒÂW'%³Ò¢&W7VÇBÂ6öFRÒWFFUööæ&ö&F–æu÷&VÖ–æFW"€¢6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–BÂ–Æö@¢¢&WGW&âÖ–æ•&W7öç6R‡&W7VÇBÂ6öFR¢–b&÷WFRÓÒ"ö’ööæ&ö&F–ærö6ö×ÆWFR# ¢Æ–æU÷W6W%ö–BÂW'"ÒWF†VçF–6FVEöÆ–æU÷W6W"€¢–ÆöBÂ&w3×&×2Â†VFW'3Ö†VFW'2Â6öæf–s×6VÆbææ6öæf–p¢¢–bW'# ¢&WGW&âÖ–æ•&W7öç6R†W'%³ÒÂW'%³Ò¢&W7VÇBÂ6öFRÒ6ö×ÆWFUööæ&ö&F–æuöf÷%÷W6W"€¢6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–BÂ–Æö@¢¢&WGW&âÖ–æ•&W7öç6R‡&W7VÇBÂ6öFR¢–b&÷WFRÓÒ"ö’÷v&æ–ærö6æ6VÂ# ¢&WGW&âÖ–æ•&W7öç6R†6æ6VÅ÷v&æ–ær‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöBÂ6VÆbææ6öæf–r’¢–b&÷WFRÓÒ"ö’÷6WGF–æw2# ¢&WGW&âÖ–æ•&W7öç6R‡6fU÷6WGF–æw5öf÷%÷&öf–ÆR‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöB’¢–b&÷WFRÓÒ"ö’ö&–ÆÆ–ær÷&VfW&Væ6W2# ¢&öG’Â6öFRÒ6fUö&–ÆÆ–æu÷&VfW&Væ6W2‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöB¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’÷–ÖVçG2ö÷&FW'2# ¢&öG’Â6öFRÒ7&VFU÷–ÖVçEö÷&FW"‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöBÂ6VÆbææ6öæf–r¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFR–â²"ö’÷–ÖVçBöV7’öæ÷F–g’"Â"ö’÷–ÖVçBöV7’÷W&–öBÖæ÷F–g’'Ó ¢f÷&ÒÒF–7B†FF’–b—6–ç7Fæ6R†FFÂF–7B’VÇ6R–Æö@¢–bV7’—2æöæS ¢&WGW&âÖ–æ•&W7öç6R‚#Ç–ÖVçBÖöGVÆRÖ—76–ær"ÂS2¢'6VBÂW'&÷"ÒV7’ç'6Uöæ÷F–g•÷–ÆöB†f÷&ÒÂ6VÆbææ6öæf–r¢–bW'&÷# ¢&WGW&âÖ–æ•&W7öç6R†b#Ç¶W'&÷'Ò"ÂC¢–bæ÷BV7’ææ÷F–g•÷7V66W72‡'6VBÂ6VÆbææ6öæf–r“ ¢&WGW&âÖ–æ•&W7öç6R‚#Äô²"Â#¢–b&÷WFRæVæG7v—F‚‚"÷W&–öBÖæ÷F–g’"“ ¢'6VBçWFFR‡²'7FGW2#¢%5T44U52"Â'&÷f–FW"#¢&V7’'Ò¢&öG’Â6öFRÒ&ö6W75÷W&–öEöæ÷F–f–6F–öâ€¢6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ'6VBÂ6VÆbææ6öæf–p¢¢VÇ6S ¢&öG’Â6öFRÒ6öæf—&Õ÷–ÖVçEö÷&FW"€¢6VÆbææ6öæf–u²$DDôd”ÄR%ÒÀ¢°¢&÷&FW%ö–B#¢'6VBævWB‚&÷&FW%ö–B"’À¢'G&ç67F–öåö–B#¢'6VBævWB‚'G&ç67F–öåö–B"’À¢&Ö÷VçB#¢'6VBævWB‚&Ö÷VçB"’À¢'&÷f–FW"#¢&V7’"À¢ÒÀ¢6VÆbææ6öæf–rÀ¢¢–b6öFRãÒC ¢&WGW&âÖ–æ•&W7öç6R€¢b#Ç¶&öG’ævWB‚vW'&÷"rÂv÷&FW"WFFRf–ÆVBr—Ò"Â6öFP¢¢&WGW&âÖ–æ•&W7öç6R‚#Äô²"Â#¢–b&÷WFRÓÒ"ö’ö6öçF7G2# ¢&öG’Â6öFRÒ6fUö6öçF7G2‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöB¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’ö6ÆVæF"Öæ÷FW2# ¢Æ–æU÷W6W%ö–BÂW'"ÒWF†VçF–6FVEöÆ–æU÷W6W"€¢–ÆöBÂ&w3×&×2Â†VFW'3Ö†VFW'2Â6öæf–s×6VÆbææ6öæf–p¢¢–bW'# ¢&WGW&âÖ–æ•&W7öç6R†W'%³ÒÂW'%³Ò¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢&öG’Â6öFRÒ6fUö6ÆVæF%öæ÷FR‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöB¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’÷6Ö'B×&VÖ–æFW'2# ¢Æ–æU÷W6W%ö–BÂW'"ÒWF†VçF–6FVEöÆ–æU÷W6W"€¢–ÆöBÂ&w3×&×2Â†VFW'3Ö†VFW'2Â6öæf–s×6VÆbææ6öæf–p¢¢–bW'# ¢&WGW&âÖ–æ•&W7öç6R†W'%³ÒÂW'%³Ò¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢&öG’Â6öFRÒ6fU÷6Ö'E÷&VÖ–æFW"‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöB¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFR–â²"ö’ö7&öâ÷6Ö'B×&VÖ–æFW'2"Â"ö’ö7&öâö&—'F†F’×&VÖ–æFW'2'Ó ¢–bæ÷B7&öåöÆÆ÷vVB‡6VÆbææ6öæf–rÂ7&öå÷6V7&WB“ ¢&WGW&âÖ–æ•&W7öç6R‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢F6²Ò€¢6VæE÷6Ö'E÷&VÖ–æFW'0¢–b&÷WFRæVæG7v—F‚‚'6Ö'B×&VÖ–æFW'2"¢VÇ6R6VæEö&—'F†F•÷&VÖ–æFW'0¢¢&öG’Â6öFRÒF6²‡6VÆbææ6öæf–r¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’öVÖW&vVæ7’Ö6öçF7Bö&–æB# ¢Æ–æU÷W6W%ö–BÂW'"ÒWF†VçF–6FVEöÆ–æU÷W6W"‡–ÆöBÂ&w3×&×2Â†VFW'3Ö†VFW'2Â6öæf–s×6VÆbææ6öæf–r¢–bW'# ¢&WGW&âÖ–æ•&W7öç6R†W'%³ÒÂW'%³Ò¢–ÆöE²&6öçF7EöÆ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢&öG’Â6öFRÒ&–æEöVÖW&vVæ7•ö6öçF7B‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöBÂ6VÆbææ6öæf–r¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’öVÖW&vVæ7’Ö6öçF7Bö–çf—FR# ¢Æ–æU÷W6W%ö–BÂW'"ÒWF†VçF–6FVEöÆ–æU÷W6W"€¢–ÆöBÂ&w3×&×2Â†VFW'3Ö†VFW'2Â6öæf–s×6VÆbææ6öæf–p¢¢–bW'# ¢&WGW&âÖ–æ•&W7öç6R†W'%³ÒÂW'%³Ò¢&öG’Â6öFRÒ7&VFUöwV&F–åö–çf—FR€¢6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–BÂ–Æö@¢¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’öwV&F–âÖw&÷W2ö&–æB# ¢Æ–æU÷W6W%ö–BÂW'"ÒWF†VçF–6FVEöÆ–æU÷W6W"€¢–ÆöBÂ&w3×&×2Â†VFW'3Ö†VFW'2Â6öæf–s×6VÆbææ6öæf–p¢¢–bW'# ¢&WGW&âÖ–æ•&W7öç6R†W'%³ÒÂW'%³Ò¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢&öG’Â6öFRÒ&–æEöwV&F–åöw&÷W‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöB¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’öwV&F–âÖw&÷W2÷&VfW&Væ6W2# ¢Æ–æU÷W6W%ö–BÂW'"ÒWF†VçF–6FVEöÆ–æU÷W6W"€¢–ÆöBÂ&w3×&×2Â†VFW'3Ö†VFW'2Â6öæf–s×6VÆbææ6öæf–p¢¢–bW'# ¢&WGW&âÖ–æ•&W7öç6R†W'%³ÒÂW'%³Ò¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢&öG’Â6öFRÒWFFUöwV&F–åöw&÷W÷&VfW&Væ6W2€¢6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ–Æö@¢¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’öwV&F–âÖw&÷W2÷Væ&–æB# ¢Æ–æU÷W6W%ö–BÂW'"ÒWF†VçF–6FVEöÆ–æU÷W6W"€¢–ÆöBÂ&w3×&×2Â†VFW'3Ö†VFW'2Â6öæf–s×6VÆbææ6öæf–p¢¢–bW'# ¢&WGW&âÖ–æ•&W7öç6R†W'%³ÒÂW'%³Ò¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢&öG’Â6öFRÒVæ&–æEöwV&F–åöw&÷W‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöB¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’ög&–VæG2ö–çf—FR# ¢&öG’Â6öFRÒ7&VFUög&–VæEö–çf—FR‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöB¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’ög&–VæG2ö66WB# ¢&öG’Â6öFRÒ66WEög&–VæEö–çf—FR‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöB¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’öÆö6F–öâ÷WFFR# ¢&öG’Â6öFRÒWFFUöÆö6F–öâ‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöBÂ6VÆbææ6öæf–r¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’öÆö6F–öâ÷7F÷# ¢&öG’Â6öFRÒ7F÷öÆö6F–öå÷6†&–ær‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöB¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’÷6÷2# ¢&öG’Â6öFRÒG&–vvW%÷6÷2‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöBÂ6VÆbææ6öæf–r¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’÷6÷2ö6æ6VÂ# ¢&öG’Â6öFRÒ6æ6VÅ÷6÷5öWfVçB‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöBÂ6VÆbææ6öæf–r¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’÷6÷2÷&WG'’# ¢&öG’Â6öFRÒ&WG'•÷6÷5öWfVçB‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöBÂ6VÆbææ6öæf–r¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’ö66÷VçBöFVÆWFR# ¢&öG’Â6öFRÒFVÆWFUö66÷VçB‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöB¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’ö66÷VçBöW‡÷'B# ¢&öG’Â6öFRÒW‡÷'Eö66÷VçEöFF‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöB¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’ö66÷VçBö†—7F÷'’öFVÆWFR# ¢&öG’Â6öFRÒFVÆWFU÷W'6öæÅö†—7F÷'’‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöB¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’öFÖ–â÷6VæB×&VÖ–æFW'2# ¢–bæ÷BFÖ–åöÆÆ÷vVB‡6VÆbææ6öæf–rÂ&×2ævWB‚'77v÷&B"Â""’“ ¢&WGW&âÖ–æ•&W7öç6R‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢&öG’Â6öFRÒ6VæEöGVU÷&VÖ–æFW'2‡6VÆbææ6öæf–r¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’öFÖ–â÷6VæBÖ6öçF7B×&VÖ–æFW'2# ¢–bæ÷BFÖ–åöÆÆ÷vVB‡6VÆbææ6öæf–rÂ&×2ævWB‚'77v÷&B"Â""’“ ¢&WGW&âÖ–æ•&W7öç6R‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢&öG’Â6öFRÒ6VæEöÖ—76–æuö6öçF7E÷&VÖ–æFW'2‡6VÆbææ6öæf–r¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’öFÖ–â÷6VæB×&VæWvÂ×&VÖ–æFW'2# ¢–bæ÷BFÖ–åöÆÆ÷vVB‡6VÆbææ6öæf–rÂ&×2ævWB‚'77v÷&B"Â""’“ ¢&WGW&âÖ–æ•&W7öç6R‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢&öG’Â6öFRÒ6VæE÷&VæWvÅ÷&VÖ–æFW'2‡6VÆbææ6öæf–r¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’öFÖ–â÷–ÖVçG2ö6öæf—&Ò# ¢–bæ÷BFÖ–åöÆÆ÷vVB‡6VÆbææ6öæf–rÂ&×2ævWB‚'77v÷&B"Â""’“ ¢&WGW&âÖ–æ•&W7öç6R‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢&öG’Â6öFRÒ6öæf—&Õ÷–ÖVçEö÷&FW"‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöBÂ6VÆbææ6öæf–r¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’öFÖ–âö&6·W2# ¢–bæ÷BFÖ–åöÆÆ÷vVB‡6VÆbææ6öæf–rÂ&×2ævWB‚'77v÷&B"Â""’“ ¢&WGW&âÖ–æ•&W7öç6R‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢&öG’Â6öFRÒ7&VFUöFÖ–åö&6·W‡6VÆbææ6öæf–u²$DDôd”ÄR%Ò¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’ö7&öâ÷F–6²# ¢–bæ÷B7&öåöÆÆ÷vVB‡6VÆbææ6öæf–rÂ7&öå÷6V7&WB“ ¢&WGW&âÖ–æ•&W7öç6R‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢&öG’Â6öFRÒ'Våö7&öå÷F–6²‡6VÆbææ6öæf–r¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’ö7&öâö6öçF7B×&VÖ–æFW'2# ¢–bæ÷B7&öåöÆÆ÷vVB‡6VÆbææ6öæf–rÂ7&öå÷6V7&WB“ ¢&WGW&âÖ–æ•&W7öç6R‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢&öG’Â6öFRÒ6VæEöÖ—76–æuö6öçF7E÷&VÖ–æFW'2‡6VÆbææ6öæf–r¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’ö7&öâö6†V6¶–â×&VÖ–æFW'2# ¢–bæ÷B7&öåöÆÆ÷vVB‡6VÆbææ6öæf–rÂ7&öå÷6V7&WB“ ¢&WGW&âÖ–æ•&W7öç6R‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢ÖöFRÒ7G"‡&×2ævWB‚&ÖöFR"Â""’÷"""’ç7G&—‚’æÆ÷vW"‚¢f÷&6RÒ7G"‡&×2ævWB‚&f÷&6R"Â""’÷"""’ç7G&—‚’æÆ÷vW"‚’–â²#"Â'G'VR"Â'–W2"Â&öâ'Ğ¢–bÖöFR–â²&'&öF67B"Â'&WW6‚"Â&ÆÂ'Ò÷"f÷&6S ¢&öG’Â6öFRÒ'&öF67Eö6†V6¶–å÷&VÖ–æFW'2‡6VÆbææ6öæf–r¢VÇ6S ¢&öG’Â6öFRÒ6VæEö6†V6¶–å÷&VÖ–æFW'2‡6VÆbææ6öæf–r¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’ö7&öâö6†V6¶–âÖ'&öF67B# ¢–bæ÷B7&öåöÆÆ÷vVB‡6VÆbææ6öæf–rÂ7&öå÷6V7&WB“ ¢&WGW&âÖ–æ•&W7öç6R‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢&öG’Â6öFRÒ'&öF67Eö6†V6¶–å÷&VÖ–æFW'2‡6VÆbææ6öæf–r¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’ö7&öâ÷&VæWvÂ×&VÖ–æFW'2# ¢–bæ÷B7&öåöÆÆ÷vVB‡6VÆbææ6öæf–rÂ7&öå÷6V7&WB“ ¢&WGW&âÖ–æ•&W7öç6R‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢&öG’Â6öFRÒ6VæE÷&VæWvÅ÷&VÖ–æFW'2‡6VÆbææ6öæf–r¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’ö7&öâöFFÖ6ÆVçW# ¢–bæ÷B7&öåöÆÆ÷vVB‡6VÆbææ6öæf–rÂ7&öå÷6V7&WB“ ¢&WGW&âÖ–æ•&W7öç6R‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢&öG’Â6öFRÒ6ÆVçWöW‡—&VEöFF‡6VÆbææ6öæf–r¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’ö7&öâö&6¶f–ÆÂÖ&–æBÖæ÷F–g’# ¢–bæ÷B7&öåöÆÆ÷vVB‡6VÆbææ6öæf–rÂ7&öå÷6V7&WB“ ¢&WGW&âÖ–æ•&W7öç6R‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢G'•÷'VâÒ7G"‡&×2ævWB‚&G'•÷'Vâ"’÷"–ÆöBævWB‚&G'•÷'Vâ"’÷"""’ç7G&—‚’æÆ÷vW"‚’–â°¢#"À¢'G'VR"À¢'–W2"À¢&öâ"À¢Ğ¢G'“ ¢Æ–Ö—BÒ–çB‡&×2ævWB‚&Æ–Ö—B"’÷"–ÆöBævWB‚&Æ–Ö—B"’÷"¢W†6WB…G—TW'&÷"ÂfÇVTW'&÷"“ ¢Æ–Ö—BÒ ¢&öG’Â6öFRÒ&6¶f–ÆÅö&–æEöæ÷F–g’‡6VÆbææ6öæf–rÂG'•÷'VãÖG'•÷'VâÂÆ–Ö—CÖÆ–Ö—B¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’öFÖ–â÷W6W"×Æâ# ¢–bæ÷BFÖ–åöÆÆ÷vVB‡6VÆbææ6öæf–rÂ&×2ævWB‚'77v÷&B"Â""’“ ¢&WGW&âÖ–æ•&W7öç6R‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢&öG’Â6öFRÒFÖ–å÷WFFU÷W6W%÷Æâ‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöB¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’öFÖ–â÷6WBÖ6÷&RÖwV&F–â# ¢–bæ÷BFÖ–åöÆÆ÷vVB‡6VÆbææ6öæf–rÂ&×2ævWB‚'77v÷&B"Â""’“ ¢&WGW&âÖ–æ•&W7öç6R‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢&öG’Â6öFRÒFÖ–å÷6WEö6÷&UöwV&F–â‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöB¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’öFÖ–â÷7W÷'B×&WÇ’# ¢–bæ÷BFÖ–åöÆÆ÷vVB‡6VÆbææ6öæf–rÂ&×2ævWB‚'77v÷&B"Â""’“ ¢&WGW&âÖ–æ•&W7öç6R‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢&öG’Â6öFRÒFÖ–å÷&WÇ•÷7W÷'E÷F–6¶WB‡6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöBÂ6VÆbææ6öæf–r¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’÷7W÷'B÷F–6¶WG2# ¢Æ–æU÷W6W%ö–BÂW'"ÒWF†VçF–6FVEöÆ–æU÷W6W"€¢–ÆöBÂ&w3×&×2Â†VFW'3Ö†VFW'2Â6öæf–s×6VÆbææ6öæf–p¢¢–bW'# ¢&WGW&âÖ–æ•&W7öç6R†W'%³ÒÂW'%³Ò¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢&öG’Â6öFRÒ7&VFU÷7W÷'E÷F–6¶WB€¢6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöBÂ6VÆbææ6öæf–p¢¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢–b&÷WFRÓÒ"ö’÷&VgVæB÷&WVW7G2# ¢Æ–æU÷W6W%ö–BÂW'"ÒWF†VçF–6FVEöÆ–æU÷W6W"€¢–ÆöBÂ&w3×&×2Â†VFW'3Ö†VFW'2Â6öæf–s×6VÆbææ6öæf–p¢¢–bW'# ¢&WGW&âÖ–æ•&W7öç6R†W'%³ÒÂW'%³Ò¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢&öG’Â6öFRÒ7&VFUöÖVÖ&W%÷&VgVæE÷&WVW7B€¢6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂ–ÆöBÂæ÷sÖ7W'&VçEö÷F–ÖR‡6VÆbææ6öæf–r’Â6öæf–s×6VÆbææ6öæf–p¢¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢&WGW&âÖ–æ•&W7öç6R‡²&W'&÷"#¢&æ÷Bf÷VæB'ÒÂCB ¢FVbFVÆWFR‡6VÆbÂF‚Â†VFW'3ÔæöæR“ ¢&÷WFRÂòÂVW'’ÒF‚ç'F—F–öâ‚#ò"¢&×2ÒF–7B‡W&ÆÆ–"ç'6Rç'6U÷6Â‡VW'’’¢†VFW'2Ò†VFW'2÷"·Ğ¢–b&÷WFRç7F'G7v—F‚‚"ö’÷6Ö'B×&VÖ–æFW'2ò"“ ¢Æ–æU÷W6W%ö–BÂW'"ÒWF†VçF–6FVEöÆ–æU÷W6W"€¢·ÒÂ&w3×&×2Â†VFW'3Ö†VFW'2Â6öæf–s×6VÆbææ6öæf–p¢¢–bW'# ¢&WGW&âÖ–æ•&W7öç6R†W'%³ÒÂW'%³Ò¢&VÖ–æFW%ö–BÒ&÷WFRç'7Æ—B‚"ò"Â•²ÓĞ¢&öG’Â6öFRÒFVÆWFU÷6Ö'E÷&VÖ–æFW"€¢6VÆbææ6öæf–u²$DDôd”ÄR%ÒÂÆ–æU÷W6W%ö–BÂ&VÖ–æFW%ö–@¢¢&WGW&âÖ–æ•&W7öç6R†&öG’Â6öFR¢&WGW&âÖ–æ•&W7öç6R‡²&W'&÷"#¢&æ÷Bf÷VæB'ÒÂCB  ¦6Æ72Ö–æ” ¢FVbõö–æ—Eõò‡6VÆbÂ6öæf–sÔæöæR“ ¢6VÆbæ6öæf–rÒ°¢$DDôd”ÄR#¢&W6öÇfUöFFöf–ÆR†÷2æVçf—&öâævWB‚$DDôd”ÄR"’’À¢$DÔ”åõ55tõ$B#¢÷2æVçf—&öâævWB‚$DÔ”åõ55tõ$B"Â""’À¢$DÔ”åõ4U54”ôåõ4T5$UB#¢÷2æVçf—&öâævWB‚$DÔ”åõ4U54”ôåõ4T5$UB"Â""’À¢$ÄÄõuôõTåôDÔ”â#¢÷2æVçf—&öâævWB‚$ÄÄõuôõTåôDÔ”â"Â""’À¢$DÔ”åôõTâ#¢÷2æVçf—&öâævWB‚$DÔ”åôõTâ"Â""’À¢$Ä”äUô4„ääTÅô44U55õDô´Tâ#¢÷2æVçf—&öâævWB‚$Ä”äUô4„ääTÅô44U55õDô´Tâ"Â""’À¢$Ä”äUô4„ääTÅõ4T5$UB#¢÷2æVçf—&öâævWB‚$Ä”äUô4„ääTÅõ4T5$UB"Â""’À¢$Ä”deô”B#¢÷2æVçf—&öâævWB‚$Ä”deô”B"’÷"DTdTÅEôÄ”deô”BÀ¢$Ä”äUôÄôt”åô4„ääTÅô”B#¢€¢÷2æVçf—&öâævWB‚$Ä”äUôÄôt”åô4„ääTÅô”B"¢÷"†÷2æVçf—&öâævWB‚$Ä”deô”B"’÷"DTdTÅEôÄ”deô”B’ç7Æ—B‚"Ò"Â•³Ğ¢÷"DTdTÅEôÄ”äUôÄôt”åô4„ääTÅô”@¢’À¢$ÄTt5•ôÄ”äUôÄôt”åô4„ääTÅô”B#¢÷2æVçf—&öâævWB€¢$ÄTt5•ôÄ”äUôÄôt”åô4„ääTÅô”B"Â##csCƒ2 ¢’À¢$ÄTt5•ôÄ”deô”B#¢÷2æVçf—&öâævWB‚$ÄTt5•ôÄ”deô”B"ÂDTdTÅEôÄTt5•ôÄ”deô”B’À¢$44õTåEôÔ”u$D”ôåõ4T5$UB#¢÷2æVçf—&öâævWB‚$44õTåEôÔ”u$D”ôåõ4T5$UB"Â""’À¢$õT$Ä”5õU$Â#¢÷2æVçf—&öâævWB‚$õT$Ä”5õU$Â"Â""’À¢$õD”ÔU¤ôäR#¢÷2æVçf—&öâævWB‚$õD”ÔU¤ôäR"Â$6–õF—V’"’À¢$5$ôåõ4T5$UB#¢÷2æVçf—&öâævWB‚$5$ôåõ4T5$UB"Â""’À¢Ğ¢–b6öæf–s ¢6VÆbæ6öæf–rçWFFR†6öæf–r¢7W'&VçEöÆ–feö–BÒ7G"‡6VÆbæ6öæf–rævWB‚$Ä”deô”B"’÷"DTdTÅEôÄ”deô”B’ç7G&—‚¢6VÆbæ6öæf–u²$Ä”deô”B%ÒÒ7W'&VçEöÆ–feö–@¢6VÆbæ6öæf–u²$Ä”äUôÄôt”åô4„ääTÅô”B%ÒÒ€¢7W'&VçEöÆ–feö–Bç7Æ—B‚"Ò"Â•³Ò÷"DTdTÅEôÄ”äUôÄôt”åô4„ääTÅô”@¢ ¢FVbFW7Eö6Æ–VçB‡6VÆb“ ¢&WGW&âÖ–æ”6Æ–VçB‡6VÆb ¢FVb7FGW2‡6VÆbÂÆ–æU÷W6W%ö–CÔæöæR“ ¢7FFRÒÆöE÷7FFR‡6VÆbæ6öæf–u²$DDôd”ÄR%Ò¢&WGW&â'V–ÆE÷7FGW2†vWE÷&öf–ÆR‡7FFRÂÆ–æU÷W6W%ö–B’ ¢FVb'Vâ‡6VÆbÂ†÷7CÒ##rããã"Â÷'CÓSÂFV'VsÔfÇ6R“ ¢FFöf–ÆRÒ6VÆbæ6öæf–u²$DDôd”ÄR%Ğ¢6öæf–rÒ6VÆbæ6öæf–p¢7FF–5÷&ö÷BÒF‚…õöf–ÆUõò’ç&W6öÇfR‚’ç&Vç@ ¢6Æ72†æFÆW"„&6T…EE&WVW7D†æFÆW"“ ¢FVb6VæEö§6öâ††æFÆW"Â–ÆöBÂ7FGW3Ó#“ ¢&öG’Ò§6öâæGV×2‡–ÆöBÂVç7W&Uö66–“ÔfÇ6R’æVæ6öFR‚'WFbÓ‚"¢†æFÆW"ç6VæE÷&W7öç6R‡7FGW2¢†æFÆW"ç6VæEö†VFW"‚$6öçFVçBÕG—R"Â&Æ–6F–öâö§6öã²6†'6WC×WFbÓ‚"¢†æFÆW"ç6VæEö†VFW"‚$6öçFVçBÔÆVæwF‚"Â7G"†ÆVâ†&öG’’’¢†æFÆW"æVæEö†VFW'2‚¢†æFÆW"çvf–ÆRçw&—FR†&öG’ ¢FVb&VE÷–ÆöB††æFÆW"“ ¢ÆVæwF‚Ò–çB††æFÆW"æ†VFW'2ævWB‚$6öçFVçBÔÆVæwF‚"’÷"¢–bæ÷BÆVæwFƒ ¢&WGW&â·Ğ¢G'“ ¢&WGW&â§6öâæÆöG2††æFÆW"ç&f–ÆRç&VB†ÆVæwF‚’æFV6öFR‚'WFbÓ‚"’¢W†6WB§6öâä¥4ôäFV6öFTW'&÷# ¢&WGW&â·Ğ ¢FVbVW'’††æFÆW"“ ¢&WGW&âF–7B‡W&ÆÆ–"ç'6Rç'6U÷6Â‡W&ÆÆ–"ç'6RçW&Ç7Æ—B††æFÆW"çF‚’çVW'’’ ¢FVb7&öå÷6V7&WB††æFÆW"“ ¢&WGW&â†æFÆW"æ†VFW'2ævWB‚%‚Ô7&öâÕ6V7&WB"Â"" ¢FVb&÷WFR††æFÆW"“ ¢&WGW&âW&ÆÆ–"ç'6RçW&Ç7Æ—B††æFÆW"çF‚’çF€ ¢FVbWF†VçF–6FVE÷W6W"††æFÆW"Â–ÆöCÔæöæRÂ&×3ÔæöæR“ ¢&WGW&âWF†VçF–6FVEöÆ–æU÷W6W"€¢–ÆöB÷"·ÒÀ¢&w3×&×2÷"·ÒÀ¢†VFW'3ÖF–7B††æFÆW"æ†VFW'2æ—FV×2‚’’À¢6öæf–sÖ6öæf–rÀ¢ ¢FVbFõôtUB††æFÆW"“ ¢&÷WFRÒ†æFÆW"ç&÷WFR‚¢–b&÷WFRÓÒ"ö’öFÖ–â"÷"&÷WFRç7F'G7v—F‚‚"ö’öFÖ–âò"“ ¢&WGW&â†æFÆW"ç6VæEö§6öâ‡²&W'&÷"#¢&FÖ–åöæ÷Eö6öæf–wW&VB'ÒÂS2¢&×2Ò†æFÆW"çVW'’‚¢–b&÷WFRÓÒ"ö’ö6öæf–r# ¢&WGW&â†æFÆW"ç6VæEö§6öâ†ö6öæf–r†6öæf–r’¢–b&÷WFRÓÒ"ö†VÇF‚# ¢&WGW&â†æFÆW"ç6VæEö§6öâ‡²&ö²#¢G'VWÒ¢–b&÷WFRÓÒ"ö’÷7FGW2# ¢Æ–æU÷W6W%ö–BÂW'"Ò†æFÆW"æWF†VçF–6FVE÷W6W"‡&×3×&×2¢–bW'# ¢&WGW&â†æFÆW"ç6VæEö§6öâ†W'%³ÒÂW'%³Ò¢FFÂ6öFRÒ7FGW5öf÷%÷W6W"€¢FFöf–ÆRÀ¢Æ–æU÷W6W%ö–BÀ¢&×2ævWB‚&F—7Æ•öæÖR"’À¢¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’ööæ&ö&F–ær# ¢Æ–æU÷W6W%ö–BÂW'"Ò†æFÆW"æWF†VçF–6FVE÷W6W"‡&×3×&×2¢–bW'# ¢&WGW&â†æFÆW"ç6VæEö§6öâ†W'%³ÒÂW'%³Ò¢FFÂ6öFRÒöæ&ö&F–æu÷7FGW5÷–ÆöB†FFöf–ÆRÂÆ–æU÷W6W%ö–B¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’ööæ&ö&F–ær÷7FFR# ¢Æ–æU÷W6W%ö–BÂW'"Ò†æFÆW"æWF†VçF–6FVE÷W6W"‡&×3×&×2¢–bW'# ¢&WGW&â†æFÆW"ç6VæEö§6öâ†W'%³ÒÂW'%³Ò¢FFÂ6öFRÒöæ&ö&F–æu÷7FGW5÷–ÆöB€¢FFöf–ÆRÀ¢Æ–æU÷W6W%ö–BÀ¢ÆÆ÷uöÖ—76–æu÷&öf–ÆSÕG'VRÀ¢¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’öFÖ–â÷7VÖÖ'’# ¢FVæ–VBÒFÖ–åöWF…öW'&÷%÷–ÆöB†6öæf–rÂ&×2ævWB‚'77v÷&B"Â""’¢–bFVæ–VC ¢–ÆöBÂ6öFRÒFVæ–V@¢&WGW&â†æFÆW"ç6VæEö§6öâ‡–ÆöBÂ6öFR¢&WGW&â†æFÆW"ç6VæEö§6öâ†FÖ–å÷7VÖÖ'’†FFöf–ÆRÂ6öæf–r’¢–b&÷WFRÓÒ"ö’ö6öçF7G2# ¢&WGW&â†æFÆW"ç6VæEö§6öâ†vWEö6öçF7G2†FFöf–ÆRÂ&×2ævWB‚&Æ–æU÷W6W%ö–B"’’¢–b&÷WFRÓÒ"ö’öVÖW&vVæ7’Ö6öçF7Bö–çf—FR×&Wf–Wr# ¢Æ–æU÷W6W%ö–BÂW'"Ò†æFÆW"æWF†VçF–6FVE÷W6W"‡·ÒÂ&×2¢–bW'# ¢&WGW&â†æFÆW"ç6VæEö§6öâ†W'%³ÒÂW'%³Ò¢FFÂ6öFRÒ–çf—FUö&–æE÷&Wf–Wr€¢FFöf–ÆRÀ¢°¢&–çf—FUög&öÒ#¢&×2ævWB‚&–çf—FUög&öÒ"’÷"&×2ævWB‚&g&öÒ"’÷"""À¢&–çf—FU÷Fö¶Vâ#¢&×2ævWB‚&–çf—FU÷Fö¶Vâ"’÷"""À¢&Æ–æU÷W6W%ö–B#¢Æ–æU÷W6W%ö–BÀ¢ÒÀ¢¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’ö6ÆVæF"Öæ÷FW2# ¢Æ–æU÷W6W%ö–BÂW'"Ò†æFÆW"æWF†VçF–6FVE÷W6W"‡&×3×&×2¢–bW'# ¢&WGW&â†æFÆW"ç6VæEö§6öâ†W'%³ÒÂW'%³Ò¢&öG’ÒvWEö6ÆVæF%öæ÷FW2†FFöf–ÆRÂÆ–æU÷W6W%ö–B¢&WGW&â†æFÆW"ç6VæEö§6öâ€¢&öG’Â7FGW3Ó#–b&öG’ævWB‚&ö²"’VÇ6RC0¢¢–b&÷WFRÓÒ"ö’÷6Ö'B×&VÖ–æFW'2# ¢Æ–æU÷W6W%ö–BÂW'"Ò†æFÆW"æWF†VçF–6FVE÷W6W"‡&×3×&×2¢–bW'# ¢&WGW&â†æFÆW"ç6VæEö§6öâ†W'%³ÒÂW'%³Ò¢&WGW&â†æFÆW"ç6VæEö§6öâ€¢vWE÷6Ö'E÷&VÖ–æFW'5÷–ÆöB†FFöf–ÆRÂÆ–æU÷W6W%ö–B¢¢–b&÷WFRÓÒ"ö’ög&–VæG2öÆö6F–öç2# ¢&WGW&â†æFÆW"ç6VæEö§6öâ†g&–VæEöÆö6F–öç2†FFöf–ÆRÂ&×2ævWB‚&Æ–æU÷W6W%ö–B"’’¢–b&÷WFRÓÒ"ö’öÆö6F–öâ÷7FGW2# ¢Æ–æU÷W6W%ö–BÒ&×2ævWB‚&Æ–æU÷W6W%ö–B"¢–bæ÷BÆ–æU÷W6W%ö–C ¢&WGW&â†æFÆW"ç6VæEö§6öâ‡²&W'&÷"#¢&Ö—76–ærÆ–æU÷W6W%ö–B'ÒÂC¢&WGW&â†æFÆW"ç6VæEö§6öâ‡°¢&ö²#¢G'VRÀ¢'6fWG•öwV&B#¢6fWG•öwV&E÷6æ6†÷B†vWE÷&öf–ÆR†ÆöE÷7FFR†FFöf–ÆR’ÂÆ–æU÷W6W%ö–B’’À¢Ò¢–b&÷WFRÓÒ"ö’ö7&öâö6öçF7B×&VÖ–æFW'2# ¢–bæ÷B7&öåöÆÆ÷vVB†6öæf–rÂ†æFÆW"æ7&öå÷6V7&WB‚’“ ¢&WGW&â†æFÆW"ç6VæEö§6öâ‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢FFÂ6öFRÒ6VæEöÖ—76–æuö6öçF7E÷&VÖ–æFW'2†6öæf–r¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’ö7&öâö6†V6¶–â×&VÖ–æFW'2# ¢–bæ÷B7&öåöÆÆ÷vVB†6öæf–rÂ†æFÆW"æ7&öå÷6V7&WB‚’“ ¢&WGW&â†æFÆW"ç6VæEö§6öâ‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢ÖöFRÒ7G"‡&×2ævWB‚&ÖöFR"Â""’÷"""’ç7G&—‚’æÆ÷vW"‚¢f÷&6RÒ7G"‡&×2ævWB‚&f÷&6R"Â""’÷"""’ç7G&—‚’æÆ÷vW"‚’–â²#"Â'G'VR"Â'–W2"Â&öâ'Ğ¢–bÖöFR–â²&'&öF67B"Â'&WW6‚"Â&ÆÂ'Ò÷"f÷&6S ¢FFÂ6öFRÒ'&öF67Eö6†V6¶–å÷&VÖ–æFW'2†6öæf–r¢VÇ6S ¢FFÂ6öFRÒ6VæEö6†V6¶–å÷&VÖ–æFW'2†6öæf–r¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’ö7&öâö6†V6¶–âÖ'&öF67B# ¢–bæ÷B7&öåöÆÆ÷vVB†6öæf–rÂ†æFÆW"æ7&öå÷6V7&WB‚’“ ¢&WGW&â†æFÆW"ç6VæEö§6öâ‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢FFÂ6öFRÒ'&öF67Eö6†V6¶–å÷&VÖ–æFW'2†6öæf–r¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’ö7&öâöFFÖ6ÆVçW# ¢–bæ÷B7&öåöÆÆ÷vVB†6öæf–rÂ†æFÆW"æ7&öå÷6V7&WB‚’“ ¢&WGW&â†æFÆW"ç6VæEö§6öâ‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢FFÂ6öFRÒ6ÆVçWöW‡—&VEöFF†6öæf–r¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’ö7&öâö&6¶f–ÆÂÖ&–æBÖæ÷F–g’# ¢–bæ÷B7&öåöÆÆ÷vVB†6öæf–rÂ†æFÆW"æ7&öå÷6V7&WB‚’“ ¢&WGW&â†æFÆW"ç6VæEö§6öâ‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢G'•÷'VâÒ7G"‡&×2ævWB‚&G'•÷'Vâ"’÷"""’ç7G&—‚’æÆ÷vW"‚’–â°¢#"À¢'G'VR"À¢'–W2"À¢&öâ"À¢Ğ¢G'“ ¢Æ–Ö—BÒ–çB‡&×2ævWB‚&Æ–Ö—B"’÷"¢W†6WB…G—TW'&÷"ÂfÇVTW'&÷"“ ¢Æ–Ö—BÒ ¢FFÂ6öFRÒ&6¶f–ÆÅö&–æEöæ÷F–g’†6öæf–rÂG'•÷'VãÖG'•÷'VâÂÆ–Ö—CÖÆ–Ö—B¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR ¢f–ÆUöæÖRÒ&–æFW‚æ‡FÖÂ"–b&÷WFRÓÒ"ò"VÇ6R&÷WFRæÇ7G&—‚"ò"¢–b&÷WFRÓÒ"öFÖ–â# ¢f–ÆUöæÖRÒ&FÖ–âæ‡FÖÂ ¢–b&÷WFRÓÒ"÷FW&×2# ¢f–ÆUöæÖRÒ'FW&×2æ‡FÖÂ ¢–b&÷WFRÓÒ"÷&—f7’# ¢f–ÆUöæÖRÒ'&—f7’æ‡FÖÂ ¢–b&÷WFRÓÒ"öf# ¢f–ÆUöæÖRÒ&fæ‡FÖÂ ¢f–ÆU÷F‚Ò7FF–5÷&ö÷Bòf–ÆUöæÖP¢–bæ÷Bf–ÆU÷F‚æW†—7G2‚’÷"æ÷Bf–ÆU÷F‚æ—5öf–ÆR‚“ ¢†æFÆW"ç6VæE÷&W7öç6RƒCB¢†æFÆW"æVæEö†VFW'2‚¢&WGW&à¢&öG’Òf–ÆU÷F‚ç&VEö'—FW2‚¢6öçFVçE÷G—RÒ'FW‡Bö‡FÖÃ²6†'6WC×WFbÓ‚"–bf–ÆU÷F‚ç7Vff—‚ÓÒ"æ‡FÖÂ"VÇ6R'FW‡B÷Æ–ã²6†'6WC×WFbÓ‚ ¢†æFÆW"ç6VæE÷&W7öç6Rƒ#¢†æFÆW"ç6VæEö†VFW"‚$6öçFVçBÕG—R"Â6öçFVçE÷G—R¢†æFÆW"ç6VæEö†VFW"‚$6öçFVçBÔÆVæwF‚"Â7G"†ÆVâ†&öG’’’¢–b&÷WFRÓÒ"öFÖ–â# ¢†æFÆW"ç6VæEö†VFW"‚$66†RÔ6öçG&öÂ"Â&æò×7F÷&RÂæòÖ66†RÂ×W7B×&WfÆ–FFRÂÖ‚ÖvSÓ"¢†æFÆW"ç6VæEö†VFW"‚%&vÖ"Â&æòÖ66†R"¢†æFÆW"æVæEö†VFW'2‚¢†æFÆW"çvf–ÆRçw&—FR†&öG’ ¢FVbFõõõ5B††æFÆW"“ ¢&÷WFRÒ†æFÆW"ç&÷WFR‚¢–b&÷WFRÓÒ"ö’öFÖ–â"÷"&÷WFRç7F'G7v—F‚‚"ö’öFÖ–âò"“ ¢&WGW&â†æFÆW"ç6VæEö§6öâ‡²&W'&÷"#¢&FÖ–åöæ÷Eö6öæf–wW&VB'ÒÂS2¢&×2Ò†æFÆW"çVW'’‚¢–ÆöBÒ†æFÆW"ç&VE÷–ÆöB‚¢–b&÷WFRÓÒ"ö’öÆ–æR÷&Vv—7FW"# ¢FFÂ6öFRÒ&Vv—7FW%öÆ–æU÷W6W"†FFöf–ÆRÂ–ÆöB¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’ö6†V6¶–â# ¢Æ–æU÷W6W%ö–BÂW'"Ò†æFÆW"æWF†VçF–6FVE÷W6W"‡–ÆöBÂ&×2¢–bW'# ¢&WGW&â†æFÆW"ç6VæEö§6öâ†W'%³ÒÂW'%³Ò¢FFÂ6öFRÒ6†V6¶–åöf÷%÷W6W"€¢FFöf–ÆRÂÆ–æU÷W6W%ö–BÂ–ÆöBÂ6öæf–p¢¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’ööæ&ö&F–ær÷&VÖ–æFW"# ¢Æ–æU÷W6W%ö–BÂW'"Ò†æFÆW"æWF†VçF–6FVE÷W6W"‡–ÆöBÂ&×2¢–bW'# ¢&WGW&â†æFÆW"ç6VæEö§6öâ†W'%³ÒÂW'%³Ò¢FFÂ6öFRÒWFFUööæ&ö&F–æu÷&VÖ–æFW"€¢FFöf–ÆRÂÆ–æU÷W6W%ö–BÂ–Æö@¢¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’ööæ&ö&F–ærö6ö×ÆWFR# ¢Æ–æU÷W6W%ö–BÂW'"Ò†æFÆW"æWF†VçF–6FVE÷W6W"‡–ÆöBÂ&×2¢–bW'# ¢&WGW&â†æFÆW"ç6VæEö§6öâ†W'%³ÒÂW'%³Ò¢FFÂ6öFRÒ6ö×ÆWFUööæ&ö&F–æuöf÷%÷W6W"€¢FFöf–ÆRÂÆ–æU÷W6W%ö–BÂ–Æö@¢¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’÷v&æ–ærö6æ6VÂ# ¢&WGW&â†æFÆW"ç6VæEö§6öâ†6æ6VÅ÷v&æ–ær†FFöf–ÆRÂ–ÆöBÂ6öæf–r’¢–b&÷WFRÓÒ"ö’÷6WGF–æw2# ¢&WGW&â†æFÆW"ç6VæEö§6öâ‡6fU÷6WGF–æw5öf÷%÷&öf–ÆR†FFöf–ÆRÂ–ÆöB’¢–b&÷WFRÓÒ"ö’ö&–ÆÆ–ær÷&VfW&Væ6W2# ¢FFÂ6öFRÒ6fUö&–ÆÆ–æu÷&VfW&Væ6W2†FFöf–ÆRÂ–ÆöB¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’÷–ÖVçG2ö÷&FW'2# ¢FFÂ6öFRÒ7&VFU÷–ÖVçEö÷&FW"†FFöf–ÆRÂ–ÆöBÂ6öæf–r¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’ö6öçF7G2# ¢FFÂ6öFRÒ6fUö6öçF7G2†FFöf–ÆRÂ–ÆöB¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’ö6ÆVæF"Öæ÷FW2# ¢Æ–æU÷W6W%ö–BÂW'"Ò†æFÆW"æWF†VçF–6FVE÷W6W"‡–ÆöBÂ&×2¢–bW'# ¢&WGW&â†æFÆW"ç6VæEö§6öâ†W'%³ÒÂW'%³Ò¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢FFÂ6öFRÒ6fUö6ÆVæF%öæ÷FR†FFöf–ÆRÂ–ÆöB¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’÷6Ö'B×&VÖ–æFW'2# ¢Æ–æU÷W6W%ö–BÂW'"Ò†æFÆW"æWF†VçF–6FVE÷W6W"‡–ÆöBÂ&×2¢–bW'# ¢&WGW&â†æFÆW"ç6VæEö§6öâ†W'%³ÒÂW'%³Ò¢–ÆöE²&Æ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢FFÂ6öFRÒ6fU÷6Ö'E÷&VÖ–æFW"†FFöf–ÆRÂ–ÆöB¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFR–â°¢"ö’ö7&öâ÷6Ö'B×&VÖ–æFW'2"À¢"ö’ö7&öâö&—'F†F’×&VÖ–æFW'2"À¢Ó ¢–bæ÷B7&öåöÆÆ÷vVB†6öæf–rÂ†æFÆW"æ7&öå÷6V7&WB‚’“ ¢&WGW&â†æFÆW"ç6VæEö§6öâ‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢F6²Ò€¢6VæE÷6Ö'E÷&VÖ–æFW'0¢–b&÷WFRæVæG7v—F‚‚'6Ö'B×&VÖ–æFW'2"¢VÇ6R6VæEö&—'F†F•÷&VÖ–æFW'0¢¢FFÂ6öFRÒF6²†6öæf–r¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’öVÖW&vVæ7’Ö6öçF7Bö&–æB# ¢Æ–æU÷W6W%ö–BÂW'"Ò†æFÆW"æWF†VçF–6FVE÷W6W"‡–ÆöBÂ&×2¢–bW'# ¢&WGW&â†æFÆW"ç6VæEö§6öâ†W'%³ÒÂW'%³Ò¢–ÆöE²&6öçF7EöÆ–æU÷W6W%ö–B%ÒÒÆ–æU÷W6W%ö–@¢FFÂ6öFRÒ&–æEöVÖW&vVæ7•ö6öçF7B†FFöf–ÆRÂ–ÆöBÂ6öæf–r¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’öVÖW&vVæ7’Ö6öçF7Bö–çf—FR# ¢Æ–æU÷W6W%ö–BÂW'"Ò†æFÆW"æWF†VçF–6FVE÷W6W"‡–ÆöBÂ&×2¢–bW'# ¢&WGW&â†æFÆW"ç6VæEö§6öâ†W'%³ÒÂW'%³Ò¢FFÂ6öFRÒ7&VFUöwV&F–åö–çf—FR€¢FFöf–ÆRÂÆ–æU÷W6W%ö–BÂ–Æö@¢¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’öwV&F–âÖw&÷W2ö&–æB# ¢FFÂ6öFRÒ&–æEöwV&F–åöw&÷W†FFöf–ÆRÂ–ÆöB¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’öwV&F–âÖw&÷W2÷Væ&–æB# ¢FFÂ6öFRÒVæ&–æEöwV&F–åöw&÷W†FFöf–ÆRÂ–ÆöB¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’ög&–VæG2ö–çf—FR# ¢FFÂ6öFRÒ7&VFUög&–VæEö–çf—FR†FFöf–ÆRÂ–ÆöB¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’ög&–VæG2ö66WB# ¢FFÂ6öFRÒ66WEög&–VæEö–çf—FR†FFöf–ÆRÂ–ÆöB¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’öÆö6F–öâ÷WFFR# ¢FFÂ6öFRÒWFFUöÆö6F–öâ†FFöf–ÆRÂ–ÆöBÂ6öæf–r¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’öÆö6F–öâ÷7F÷# ¢FFÂ6öFRÒ7F÷öÆö6F–öå÷6†&–ær†FFöf–ÆRÂ–ÆöB¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’÷6÷2# ¢FFÂ6öFRÒG&–vvW%÷6÷2†FFöf–ÆRÂ–ÆöBÂ6öæf–r¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’÷6÷2ö6æ6VÂ# ¢FFÂ6öFRÒ6æ6VÅ÷6÷5öWfVçB†FFöf–ÆRÂ–ÆöBÂ6öæf–r¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’÷6÷2÷&WG'’# ¢FFÂ6öFRÒ&WG'•÷6÷5öWfVçB†FFöf–ÆRÂ–ÆöBÂ6öæf–r¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’ö66÷VçBöFVÆWFR# ¢FFÂ6öFRÒFVÆWFUö66÷VçB†FFöf–ÆRÂ–ÆöB¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’ö66÷VçBöW‡÷'B# ¢FFÂ6öFRÒW‡÷'Eö66÷VçEöFF†FFöf–ÆRÂ–ÆöB¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’ö66÷VçBö†—7F÷'’öFVÆWFR# ¢FFÂ6öFRÒFVÆWFU÷W'6öæÅö†—7F÷'’†FFöf–ÆRÂ–ÆöB¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’öFÖ–â÷6VæB×&VÖ–æFW'2# ¢–bæ÷BFÖ–åöÆÆ÷vVB†6öæf–rÂ&×2ævWB‚'77v÷&B"Â""’“ ¢&WGW&â†æFÆW"ç6VæEö§6öâ‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢FFÂ6öFRÒ6VæEöGVU÷&VÖ–æFW'2†6öæf–r¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’öFÖ–â÷6VæBÖ6öçF7B×&VÖ–æFW'2# ¢–bæ÷BFÖ–åöÆÆ÷vVB†6öæf–rÂ&×2ævWB‚'77v÷&B"Â""’“ ¢&WGW&â†æFÆW"ç6VæEö§6öâ‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢FFÂ6öFRÒ6VæEöÖ—76–æuö6öçF7E÷&VÖ–æFW'2†6öæf–r¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’öFÖ–â÷6VæB×&VæWvÂ×&VÖ–æFW'2# ¢–bæ÷BFÖ–åöÆÆ÷vVB†6öæf–rÂ&×2ævWB‚'77v÷&B"Â""’“ ¢&WGW&â†æFÆW"ç6VæEö§6öâ‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢FFÂ6öFRÒ6VæE÷&VæWvÅ÷&VÖ–æFW'2†6öæf–r¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’öFÖ–â÷–ÖVçG2ö6öæf—&Ò# ¢–bæ÷BFÖ–åöÆÆ÷vVB†6öæf–rÂ&×2ævWB‚'77v÷&B"Â""’“ ¢&WGW&â†æFÆW"ç6VæEö§6öâ‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢FFÂ6öFRÒ6öæf—&Õ÷–ÖVçEö÷&FW"†FFöf–ÆRÂ–ÆöBÂ6öæf–r¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’ö7&öâ÷F–6²# ¢–bæ÷B7&öåöÆÆ÷vVB†6öæf–rÂ†æFÆW"æ7&öå÷6V7&WB‚’“ ¢&WGW&â†æFÆW"ç6VæEö§6öâ‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢FFÂ6öFRÒ'Våö7&öå÷F–6²†6öæf–r¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’ö7&öâö6öçF7B×&VÖ–æFW'2# ¢–bæ÷B7&öåöÆÆ÷vVB†6öæf–rÂ†æFÆW"æ7&öå÷6V7&WB‚’“ ¢&WGW&â†æFÆW"ç6VæEö§6öâ‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢FFÂ6öFRÒ6VæEöÖ—76–æuö6öçF7E÷&VÖ–æFW'2†6öæf–r¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’ö7&öâö6†V6¶–â×&VÖ–æFW'2# ¢–bæ÷B7&öåöÆÆ÷vVB†6öæf–rÂ†æFÆW"æ7&öå÷6V7&WB‚’“ ¢&WGW&â†æFÆW"ç6VæEö§6öâ‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢ÖöFRÒ7G"‡&×2ævWB‚&ÖöFR"Â""’÷"""’ç7G&—‚’æÆ÷vW"‚¢f÷&6RÒ7G"‡&×2ævWB‚&f÷&6R"Â""’÷"""’ç7G&—‚’æÆ÷vW"‚’–â²#"Â'G'VR"Â'–W2"Â&öâ'Ğ¢–bÖöFR–â²&'&öF67B"Â'&WW6‚"Â&ÆÂ'Ò÷"f÷&6S ¢FFÂ6öFRÒ'&öF67Eö6†V6¶–å÷&VÖ–æFW'2†6öæf–r¢VÇ6S ¢FFÂ6öFRÒ6VæEö6†V6¶–å÷&VÖ–æFW'2†6öæf–r¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’ö7&öâö6†V6¶–âÖ'&öF67B# ¢–bæ÷B7&öåöÆÆ÷vVB†6öæf–rÂ†æFÆW"æ7&öå÷6V7&WB‚’“ ¢&WGW&â†æFÆW"ç6VæEö§6öâ‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢FFÂ6öFRÒ'&öF67Eö6†V6¶–å÷&VÖ–æFW'2†6öæf–r¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’ö7&öâ÷&VæWvÂ×&VÖ–æFW'2# ¢–bæ÷B7&öåöÆÆ÷vVB†6öæf–rÂ†æFÆW"æ7&öå÷6V7&WB‚’“ ¢&WGW&â†æFÆW"ç6VæEö§6öâ‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢FFÂ6öFRÒ6VæE÷&VæWvÅ÷&VÖ–æFW'2†6öæf–r¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’ö7&öâöFFÖ6ÆVçW# ¢–bæ÷B7&öåöÆÆ÷vVB†6öæf–rÂ†æFÆW"æ7&öå÷6V7&WB‚’“ ¢&WGW&â†æFÆW"ç6VæEö§6öâ‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢FFÂ6öFRÒ6ÆVçWöW‡—&VEöFF†6öæf–r¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’ö7&öâö&6¶f–ÆÂÖ&–æBÖæ÷F–g’# ¢–bæ÷B7&öåöÆÆ÷vVB†6öæf–rÂ†æFÆW"æ7&öå÷6V7&WB‚’“ ¢&WGW&â†æFÆW"ç6VæEö§6öâ‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢G'•÷'VâÒ7G"€¢&×2ævWB‚&G'•÷'Vâ"’÷"–ÆöBævWB‚&G'•÷'Vâ"’÷"" ¢’ç7G&—‚’æÆ÷vW"‚’–â²#"Â'G'VR"Â'–W2"Â&öâ'Ğ¢G'“ ¢Æ–Ö—BÒ–çB‡&×2ævWB‚&Æ–Ö—B"’÷"–ÆöBævWB‚&Æ–Ö—B"’÷"¢W†6WB…G—TW'&÷"ÂfÇVTW'&÷"“ ¢Æ–Ö—BÒ ¢FFÂ6öFRÒ&6¶f–ÆÅö&–æEöæ÷F–g’†6öæf–rÂG'•÷'VãÖG'•÷'VâÂÆ–Ö—CÖÆ–Ö—B¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’öFÖ–â÷W6W"×Æâ# ¢–bæ÷BFÖ–åöÆÆ÷vVB†6öæf–rÂ&×2ævWB‚'77v÷&B"Â""’“ ¢&WGW&â†æFÆW"ç6VæEö§6öâ‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢FFÂ6öFRÒFÖ–å÷WFFU÷W6W%÷Æâ†FFöf–ÆRÂ–ÆöB¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢–b&÷WFRÓÒ"ö’öFÖ–â÷6WBÖ6÷&RÖwV&F–â# ¢–bæ÷BFÖ–åöÆÆ÷vVB†6öæf–rÂ&×2ævWB‚'77v÷&B"Â""’“ ¢&WGW&â†æFÆW"ç6VæEö§6öâ‡²&W'&÷"#¢'VæWF†÷&—¦VB'ÒÂC¢FFÂ6öFRÒFÖ–å÷6WEö6÷&UöwV&F–â†FFöf–ÆRÂ–ÆöB¢&WGW&â†æFÆW"ç6VæEö§6öâ†FFÂ6öFR¢†æFÆW"ç6VæEö§6öâ‡²&W'&÷"#¢&æ÷Bf÷VæB'ÒÂCB ¢&–çB‚$fÆ6²—2æ÷B–ç7FÆÆVBâW6–ærF†R'V–ÇBÖ–âfÆÆ&6²6W'fW"â"¢&–çB†b$÷Vâ‡GG¢ò÷¶†÷7GÓ§·÷'GÒ"¢F‡&VF–æt…EE6W'fW"‚††÷7BÂ÷'B’Â†æFÆW"’ç6W'fUöf÷&WfW"‚  ¦Ò7&VFUö‚¦–bfÆ6²—2æ÷BæöæS ¢7F'E÷&–6…öÖVçUöWFõ÷7–æ2†  ¦–bõöæÖUõòÓÒ%õöÖ–åõò# ¢ç'Vâ††÷7CÒ##rããã"Â÷'CÖ–çB†÷2æVçf—&öâævWB‚%õ%B"Â#S"’’ÂFV'VsÕG'VR 