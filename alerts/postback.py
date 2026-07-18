"""
alerts/postback.py — Postback data 解析

LINE Postback data 格式:`action=alert_confirm&alert_id=alert_xxx&source=group`
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import parse_qs


def parse_postback_data(data: str) -> Dict[str, Any]:
    """
    解析 LINE Postback data。
    
    範例:
        "action=alert_confirm&alert_id=alert_abc&source=group"
        → {"action": "alert_confirm", "alert_id": "alert_abc", "source": "group"}
    
    容錯:
        - 空字串 → {}
        - 格式錯誤 → 回解析到的部分
    """
    if not data or not isinstance(data, str):
        return {}
    try:
        parsed = parse_qs(data, keep_blank_values=False)
        return {k: v[0] if v else "" for k, v in parsed.items()}
    except Exception:
        return {}


def is_alert_confirm_postback(data: str) -> bool:
    """判斷是否為 alert_confirm 的 postback(守護人按「我會去聯絡他」)"""
    parsed = parse_postback_data(data)
    return parsed.get("action") == "alert_confirm"


def is_alert_cancel_postback(data: str) -> bool:
    """判斷是否為 alert_cancel 的 postback(用戶按「我平安,取消警報」)"""
    parsed = parse_postback_data(data)
    return parsed.get("action") == "alert_cancel"


def extract_alert_id(data: str) -> Optional[str]:
    """從 postback data 取 alert_id"""
    parsed = parse_postback_data(data)
    return parsed.get("alert_id") or None