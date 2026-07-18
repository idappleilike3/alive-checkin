"""
alerts/models.py — Alert / Wave 資料模型

對應 Code change map v0.4 §1 State 結構。
獨立模組,不依賴 app.py。
"""

from typing import TypedDict, Literal, Optional, List, Dict, Any


# ---------- 狀態字串常數 ----------

AlertStatus = Literal["pending", "confirmed", "expired", "auto_cancelled"]
AlertTrigger = Literal["missed_checkin"]  # Phase 1 only; Phase 2 可能加 "manual_sos"
ChannelName = Literal["line", "sms", "admin_alert"]
WaveNumber = Literal[1, 2, 3]
ConfirmSource = Literal["individual", "group"]
ContactMode = Literal["both", "group_only", "individual_only"]


# ---------- 聯護人資訊 ----------

class GuardianContact(TypedDict):
    line_id: str
    phone: str
    name: str
    priority: int


class GuardianGroupTarget(TypedDict):
    group_id: str
    name: str


class SendResult(TypedDict):
    contact: str           # LINE ID 或 phone
    channel: ChannelName
    status: str            # "sent" / "failed" / "skipped"
    error: Optional[str]
    at: str                # ISO8601


class Confirmation(TypedDict):
    confirmer_line_id: str
    at: str


# ---------- Wave ----------

class AlertWave(TypedDict, total=False):
    wave_number: int
    scheduled_at: str              # ISO8601
    sent_at: Optional[str]         # None until sent
    channels: List[ChannelName]

    # Wave 1 / 2:5 位核心
    # Wave 3:所有聯護人
    contacts: List[GuardianContact]

    # 守護群
    guardian_group_targets: List[GuardianGroupTarget]

    results: List[SendResult]
    guardian_group_results: List[SendResult]

    confirmations: List[Confirmation]


# ---------- Alert ----------

class Alert(TypedDict, total=False):
    alert_id: str
    line_user_id: str              # 失聯本人
    display_name: str
    trigger: AlertTrigger
    created_at: str
    expires_at: str                # created_at + 30 min

    status: AlertStatus
    confirmed_by: Optional[str]
    confirmed_at: Optional[str]
    cancelled_reason: Optional[str]

    waves: List[AlertWave]

    admin_alerted_at: Optional[str]


# ---------- Profile 相關 ----------

class PlanRules(TypedDict, total=False):
    contact_limit: int
    friend_location_limit: int
    daily_reminders: int
    channels: List[str]
    location_mode: str
    core_guardian_alert_limit: int
    realtime_tracking: bool
    trajectory_days: int
    offline_sync_days: int
    sos_enabled: bool
    guardian_group_limit: int
    dedicated_support: bool
    realtime_trial_days: int


class Profile(TypedDict, total=False):
    line_user_id: str
    display_name: str
    plan: str
    paid_until: Optional[str]
    payment_status: Optional[str]
    contacts: List[Dict[str, Any]]
    guardian_group_ids: List[str]
    guardian_group_notification_enabled: bool
    core_contact_in_group_mode: ContactMode
    location: Optional[Dict[str, Any]]
    last_check_in: Optional[str]


# ---------- 設定 / Config ----------

class AlertsConfig(TypedDict, total=False):
    """
    從 app.config 抽出 alerts 需要的部分。
    alerts 模組不直接讀 app.config,而是接收這個 dict。
    """
    DATA_FILE: str
    LINE_CHANNEL_ACCESS_TOKEN: str
    LINE_PUSH_SENDER: Any            # callable(token, target, message)
    SMS_SENDER: Any                 # callable(phone, message, user_id) -> SendResult dict
    ADMIN_LINE_USER_ID: str
    ADMIN_EMAIL: str
    ALERT_WAVE_2_DELAY_MINUTES: int  # 預設 15
    ALERT_WAVE_3_DELAY_MINUTES: int  # 預設 30
    ALERT_HISTORY_RETENTION_DAYS: int  # 預設 30