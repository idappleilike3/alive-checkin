"""
alerts/messages.py — Wave 訊息範本

對應 Code change map v0.4 §2.3.4 + §10.5。
所有訊息採「遞增語氣」(蝦董 19:29 欽定)。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# ============================================================================
# 顏色定義(對應 §2.9)
# ============================================================================

WAVE_COLORS = {
    1: "#F39C12",   # 橘(警告)
    2: "#E67E22",   # 深橘(緊急)
    3: "#E74C3C",   # 紅(最高)
}


# ============================================================================
# 個人 LINE 訊息(核心聯護人 / 所有聯護人)
# ============================================================================

def build_alert_text(wave_number: int, display_name: str) -> str:
    """
    純文字版本(給 SMS 用)
    """
    name = display_name or "您的親友"
    if wave_number == 1:
        return (
            f"[失聯預警] {name} 沒有按時簽到報平安。\n"
            f"請您撥個電話或傳 LINE 給對方確認安全。\n"
            f"如果您已經聯絡到本人,請按下方按鈕讓我們知道。"
        )
    if wave_number == 2:
        return (
            f"[緊急] {name} 仍未回應簽到,已超過 15 分鐘。\n"
            f"請您立即聯絡本人,或請鄰居/家人協助查看。\n"
            f"如有立即危險,請撥打 119。\n"
            f"如果您已經聯絡到本人,請按下方按鈕。"
        )
    if wave_number == 3:
        return (
            f"[最後通知] {name} 已失聯超過 30 分鐘。\n"
            f"請所有親友立即協助查看,或撥打 119。\n"
            f"如已聯絡到本人,請按下方按鈕。"
        )
    raise ValueError(f"invalid wave_number: {wave_number}")


def build_alert_flex(wave_number: int, display_name: str, alert_id: str,
                      source: str = "individual") -> Dict[str, Any]:
    """
    LINE Flex Message(含「我會去聯絡他」按鈕 + 撥打 119 按鈕)
    
    source: "individual" (個人) / "group" (群組)
    """
    name = display_name or "您的親友"
    header_titles = {1: "🛡️ 失聯預警", 2: "⚠️ 緊急通知", 3: "🚨 最後通知"}
    header_bg = WAVE_COLORS.get(wave_number, "#999999")

    if wave_number == 1:
        body_text = (
            f"🛡️ 【失聯預警】{name} 沒有按時簽到報平安。\n"
            f"請您撥個電話或傳 LINE 給對方確認安全。\n"
            f"如果您已經聯絡到本人,請按下方按鈕讓我們知道。"
        )
    elif wave_number == 2:
        body_text = (
            f"⚠️ 【緊急】{name} 仍未回應簽到,已超過 15 分鐘。\n"
            f"請您立即聯絡本人,或請鄰居/家人協助查看。\n"
            f"如有立即危險,請撥打 119。\n"
            f"如果您已經聯絡到本人,請按下方按鈕。"
        )
    else:
        body_text = (
            f"🚨 【最後通知】{name} 已失聯超過 30 分鐘。\n"
            f"請所有親友立即協助查看,或撥打 119。\n"
            f"如已聯絡到本人,請按下方按鈕。"
        )

    return {
        "type": "flex",
        "altText": header_titles.get(wave_number, "失聯預警"),
        "contents": {
            "type": "bubble",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": header_bg,
                "contents": [{
                    "type": "text",
                    "text": header_titles.get(wave_number, "失聯預警"),
                    "color": "#FFFFFF",
                    "weight": "bold",
                    "size": "lg",
                }],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": body_text, "wrap": True, "size": "sm"},
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
                        "color": "#2ECC71",
                        "action": {
                            "type": "postback",
                            "label": "✅ 我會去聯絡他",
                            "data": (
                                f"action=alert_confirm"
                                f"&alert_id={alert_id}"
                                f"&source={source}"
                            ),
                        },
                    },
                    {
                        "type": "button",
                        "style": "secondary",
                        "action": {
                            "type": "uri",
                            "label": "撥打 119",
                            "uri": "tel:119",
                        },
                    },
                ],
            },
        },
    }


# ============================================================================
# 守護群訊息
# ============================================================================

def build_alert_group_flex(wave_number: int, display_name: str, alert_id: str) -> Dict[str, Any]:
    """守護群訊息 Flex Message(跟個人版同 template,source=group)"""
    return build_alert_flex(wave_number, display_name, alert_id, source="group")


def build_alert_group_text(wave_number: int, display_name: str) -> str:
    """守護群純文字(無 LINE Flex 時 fallback)"""
    name = display_name or "家人/朋友"
    if wave_number == 1:
        return (
            f"🛡️ 【失聯預警】家人/朋友 {name} 沒有按時簽到報平安。\n"
            f"請大家協助撥個電話或傳 LINE 給對方確認安全。\n"
            f"如已聯絡到本人,請按下方按鈕。"
        )
    if wave_number == 2:
        return (
            f"⚠️ 【緊急】家人/朋友 {name} 仍未回應簽到,已超過 15 分鐘。\n"
            f"請大家立即聯絡本人,或請鄰居/家人協助查看。\n"
            f"如有立即危險,請撥打 119。\n"
            f"如已聯絡到本人,請按下方按鈕。"
        )
    if wave_number == 3:
        return (
            f"🚨 【最後通知】家人/朋友 {name} 已失聯超過 30 分鐘。\n"
            f"請所有群成員立即協助查看,或撥打 119。\n"
            f"如已聯絡到本人,請按下方按鈕。"
        )
    raise ValueError(f"invalid wave_number: {wave_number}")


# ============================================================================
# 已平安通知(使用者補簽到 → 通知守護人)
# ============================================================================

def build_user_ok_text(display_name: str) -> str:
    """給守護人的「已平安」通知(純文字,LINE 推播用)"""
    name = display_name or "您的親友"
    return (
        f"✅ 【已平安】{name} 已於剛才補簽到報平安。\n"
        f"先前的失聯預警已自動取消,請放心。"
    )


# ============================================================================
# 用戶主動取消警報(用戶本人按「我平安,取消警報」postback)
# ============================================================================

def build_user_cancel_flex(alert_id: str) -> Dict[str, Any]:
    """
    給失聯用戶本人在 LINE Bot 上的「取消警報」按鈕。
    按下後會觸發 alerts.core.cancel_alert_by_user()。
    """
    return {
        "type": "flex",
        "altText": "如果您平安,請按下方取消警報",
        "contents": {
            "type": "bubble",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#2ECC71",  # 安全綠
                "contents": [{
                    "type": "text",
                    "text": "✅ 我平安,請取消警報",
                    "color": "#FFFFFF",
                    "weight": "bold",
                    "size": "lg",
                }],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text",
                     "text": "如果您平安,只是無法按時簽到,請按下方按鈕取消失聯預警。\n\n"
                             "您的家人會收到「已平安」通知。",
                     "wrap": True, "size": "sm"},
                ],
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "button",
                        "style": "primary",
                        "color": "#2ECC71",
                        "action": {
                            "type": "postback",
                            "label": "✅ 我平安,取消警報",
                            "data": f"action=alert_cancel&alert_id={alert_id}&source=user",
                        },
                    },
                ],
            },
        },
    }


# ============================================================================
# Admin Alert(Email / LINE)
# ============================================================================

def build_admin_alert_text(alert: Dict[str, Any]) -> str:
    """Wave 3 給管理員的告警文字"""
    name = alert.get("display_name") or "(無名稱)"
    created = alert.get("created_at", "")
    confirmed = alert.get("confirmed_by")
    status = "已確認" if confirmed else "未確認(已升級到第 3 波)"
    return (
        f"🚨 [Admin Alert] 用戶 {name}({alert.get('line_user_id')}) 失聯預警\n"
        f"建立時間: {created}\n"
        f"狀態: {status}\n"
        f"Alert ID: {alert.get('alert_id')}\n"
        f"請立即聯繫本人或確認狀況。"
    )