"""
alerts/ — 失聯預警 + 守護群 模組

對應 Code change map v0.4 spec。

公開 API:
    - create_missing_person_alert() : 建立失聯預警
    - confirm_alert()              : 守護人按「我會去聯絡他」postback
    - cancel_pending_alerts()      : 用戶補簽到 → 取消未發送的 wave
    - process_alert_waves()        : cron job 主流程,發送 T+X 的 wave
    - send_user_ok_notifications() : 補簽到後通知所有守護人

內部模組:
    - models.py     TypedDicts
    - utils.py      時間 / state IO / plan rules
    - messages.py   Wave 1/2/3 Flex + 純文字
    - postback.py   postback 解析
    - kotsms_client.py  簡訊王 SMS client
    - sender.py     LINE + SMS + Admin + 守護群 統一發送
    - core.py       主要邏輯(create / confirm / cancel / process)

設計原則:
1. 不 import app.py(完全解耦)
2. 依賴注入(外部傳入 line_headers / kotsms client / data_file 路徑)
3. state 用 JSON 檔(同 process 內),跨 process 需要時換 DB
4. 所有發送結果寫進 state 的 audit log
"""

from .core import (
    create_missing_person_alert,
    confirm_alert,
    cancel_pending_alerts,
    cancel_alert_by_user,
    process_alert_waves,
    is_alert_active,
)
from .sender import (
    send_line_push_individual,
    send_line_push_group,
    send_admin_alert_line,
    send_admin_alert_email,
    send_sms_to_contact,
    send_wave_to_contacts,
    send_user_ok_notifications,
    DeliveryResult,
)
from .kotsms_client import KotsmsClient, SendResult, make_client_from_env
from .models import (
    Alert,
    AlertWave,
    GuardianContact,
    GuardianGroupTarget,
    Profile,
    AlertsConfig,
    AlertStatus,
    AlertTrigger,
    ChannelName,
    WaveNumber,
    ConfirmSource,
    ContactMode,
)
from .postback import (
    parse_postback_data,
    is_alert_confirm_postback,
    extract_alert_id,
    is_alert_cancel_postback,
)
from .utils import (
    check_in_idempotency,
    record_check_in,
)

__all__ = [
    # 主邏輯
    "create_missing_person_alert",
    "confirm_alert",
    "cancel_pending_alerts",
    "cancel_alert_by_user",
    "process_alert_waves",
    "is_alert_active",
    # 重複簽到防護
    "check_in_idempotency",
    "record_check_in",
    # 發送層
    "send_line_push_individual",
    "send_line_push_group",
    "send_admin_alert_line",
    "send_admin_alert_email",
    "send_sms_to_contact",
    "send_wave_to_contacts",
    "send_user_ok_notifications",
    "DeliveryResult",
    # SMS
    "KotsmsClient",
    "SendResult",
    "make_client_from_env",
    # Models
    "Alert",
    "AlertWave",
    "GuardianContact",
    "GuardianGroupTarget",
    "Profile",
    "AlertsConfig",
    "AlertStatus",
    "AlertTrigger",
    "ChannelName",
    "WaveNumber",
    "ConfirmSource",
    "ContactMode",
    # Postback
    "parse_postback_data",
    "is_alert_confirm_postback",
    "extract_alert_id",
]