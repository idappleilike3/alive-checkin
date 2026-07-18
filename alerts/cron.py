"""
alerts/cron.py — 與 app.py 整合的排程入口

設計:這是個「瘦」cron 入口,把工作交給 core.process_alert_waves() 處理。
實際部署建議:Render Cron Job / GitHub Actions / system cron,每分鐘觸發一次。

⚠️ 注意:這個檔案不直接被 app.py import,而是獨立的可執行入口。
Render 的 cron job 設定:
    command: python -m alerts.cron
    schedule: "* * * * *" (every minute)
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# 確保從專案根目錄 import
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from alerts.kotsms_client import KotsmsClient  # noqa: E402
from alerts.core import process_alert_waves  # noqa: E402
from alerts.utils import load_state, save_state  # noqa: E402


# ============================================================================
# 設定(從環境變數讀)
# ============================================================================

def load_config() -> Dict[str, Any]:
    """從環境變數讀設定。"""
    smtp_config = {}
    if os.environ.get("SMTP_HOST"):
        smtp_config = {
            "host": os.environ["SMTP_HOST"],
            "port": int(os.environ.get("SMTP_PORT", "587")),
            "username": os.environ.get("SMTP_USERNAME", ""),
            "password": os.environ.get("SMTP_PASSWORD", ""),
            "use_tls": os.environ.get("SMTP_USE_TLS", "true").lower() == "true",
        }

    return {
        "wave_2_delay_minutes": int(os.environ.get("ALERT_WAVE_2_DELAY_MINUTES", "15")),
        "wave_3_delay_minutes": int(os.environ.get("ALERT_WAVE_3_DELAY_MINUTES", "30")),
        "admin_line_user_id": os.environ.get("ADMIN_LINE_USER_ID", ""),
        "admin_email": os.environ.get("ADMIN_EMAIL", ""),
        "smtp_config": smtp_config,
    }


def build_line_headers() -> Dict[str, str]:
    """從環境變數建立 LINE API headers。"""
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def build_kotsms() -> Optional[KotsmsClient]:
    """從環境變數建立 kotsms client(沒設帳號密碼就回傳 None)。"""
    username = os.environ.get("SMSKING_USERNAME")
    password = os.environ.get("SMSKING_PASSWORD")
    if not username or not password:
        return None
    return KotsmsClient(
        username=username,
        password=password,
        timeout_sec=int(os.environ.get("SMSKING_TIMEOUT_SEC", "10")),
    )


# ============================================================================
# Cron 主流程
# ============================================================================

def run_once(data_file: Optional[str] = None) -> Dict[str, Any]:
    """
    跑一次 wave 處理。
    
    Args:
        data_file: state.json 路徑(預設從 STATE_FILE env 讀)
    
    Returns:
        {"sent_count": N, "sent_waves": [...]}
    """
    if data_file is None:
        data_file = os.environ.get("STATE_FILE", "state.json")

    state = load_state(data_file)
    config = load_config()
    line_headers = build_line_headers()
    kotsms = build_kotsms()

    sent_waves = process_alert_waves(
        state=state,
        config=config,
        line_headers=line_headers,
        kotsms=kotsms,
    )

    # 寫回 state
    save_state(data_file, state)

    return {
        "sent_count": len(sent_waves),
        "sent_waves": sent_waves,
    }


# ============================================================================
# CLI 入口
# ============================================================================

def main() -> int:
    """CLI entry point: python -m alerts.cron"""
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    log = logging.getLogger("alerts.cron")

    result = run_once()
    log.info(f"cron run done: sent_count={result['sent_count']}")
    if result["sent_waves"]:
        for sw in result["sent_waves"]:
            log.info(f"  - alert={sw['alert_id']} wave={sw['wave']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())