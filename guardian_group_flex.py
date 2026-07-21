"""守護群 / 歡迎 Flex Message 構建器。

主要 Flex:
1. guardian_group_intro_flex()       — 進群自我介紹(一鍵綁定守護群)
2. guardian_group_status_flex()      — 守護群狀態查詢
3. guardian_group_bind_confirm_flex  — 綁定完成(主標：我已綁定守護群)
4. guardian_group_user_guide_flex()  — 使用說明(給群成員)
5. guardian_group_admin_setup_flex() — 管理員設定 6 步驟
6. welcome_flex()                   — 加好友歡迎(7 天免費體驗 + 綁定守護人)

設計原則:
- 老人/長者閱讀:字級只用 xxl(20-24px) / lg(16-18px) / md(14px),禁 sm/xs 字級
- 顏色:綠(#06C755 LINE 綠 / #00B900 深綠)
- 對使用者文案不使用 BOT 字眼
- footer 小按鈕用 height=sm；主 CTA 用 primary md
"""

from __future__ import annotations

import os


# ───────────────────────────────────────────────────────────
# 共用元件
# ───────────────────────────────────────────────────────────

GREEN = "#06C755"          # LINE 主綠
GREEN_DARK = "#00B900"     # 深綠(已綁定 / 大按鈕)
GREEN_SOFT = "#E8F8EE"     # 淺綠背景
GRAY = "#555555"
GRAY_LIGHT = "#888888"
RED_WARN = "#D6322C"
ORANGE = "#E08E00"

# 與 render.yaml / 正式 /api/config 一致。禁止把帶 code=&state= 的 OAuth callback 當永久連結。
DEFAULT_LIFF_ID = "2010674803-rK98c0lo"
PUBLIC_BASE = "https://alive-checkin.onrender.com"


def get_liff_id() -> str:
    return (os.environ.get("LIFF_ID") or DEFAULT_LIFF_ID).strip() or DEFAULT_LIFF_ID


def liff_entry_url(*, open_action: str | None = None, fragment: str = "") -> str:
    """永久內嵌 LIFF 入口（https://liff.line.me/<LIFF_ID>）。

    不要使用含 code= / state= 的一次性 OAuth callback URL。
    open_action 會傳到 Endpoint（例如 open=onboarding → 先一鍵分享邀請，再填守護人表單→提醒設定）。
    """
    url = f"https://liff.line.me/{get_liff_id()}"
    if open_action:
        url += f"?open={open_action}"
    if fragment:
        url += f"#{fragment.lstrip('#')}"
    return url


def _postback_button(label: str, text: str, style: str = "link", color: str | None = None, height: str = "md"):
    """建立一個點下去會送出指定文字訊息的按鈕(message action,不是 postback event)。
    這樣比 postback 簡單,handler 端用文字判斷即可。"""
    btn = {
        "type": "button",
        "action": {
            "type": "message",
            "label": label[:20],  # LINE 限制 20 字
            "text": text,
        },
        "style": style,
        "height": height,
    }
    if color:
        btn["color"] = color
    return btn


def _uri_button(label: str, uri: str, style: str = "link", color: str | None = None, height: str = "md"):
    btn = {
        "type": "button",
        "action": {
            "type": "uri",
            "label": label[:20],
            "uri": uri,
        },
        "style": style,
        "height": height,
    }
    if color:
        btn["color"] = color
    return btn


def _footer_buttons(include: tuple[str, ...] = ("status", "guide", "admin")):
    """常駐 footer 小按鈕:守護群狀態 / 使用說明 / 管理員設定。"""
    btns = []
    if "status" in include:
        btns.append(_postback_button("守護群狀態", "守護群狀態", style="link", color=GREEN_DARK))
    if "guide" in include:
        btns.append(_postback_button("使用說明", "使用說明", style="link", color=GRAY))
    if "admin" in include:
        btns.append(_postback_button("管理員設定", "管理員設定", style="link", color=GRAY))
    return btns


# ───────────────────────────────────────────────────────────
# 1. 自我介紹(Intro)
# ───────────────────────────────────────────────────────────

def guardian_group_intro_flex(owner_info: dict | None = None):
    """進群自我介紹 Flex：管理員已就緒，一鍵綁定守護群。

    設計重點:
    - 短文案：邀進群 = 管理員準備綁定
    - 主 CTA：「綁定守護群」(message → 觸發既有 keyword handler)
    - 功能簡介 + footer 小按鈕(報平安 / 守護人 / 會員 / 方案 / 引導)
    - 不使用 BOT 字眼

    owner_info 結構: {
        "bound": bool,
        "is_owner": bool,
        "owner_id": str | None,
        "bound_at": str | None,
    }
    """
    already_bound = bool(owner_info and owner_info.get("bound"))
    primary_bind = {
        "type": "button",
        "action": {
            "type": "message",
            "label": "綁定守護群",
            "text": "綁定守護群",
        },
        "style": "primary",
        "color": GREEN_DARK,
        "height": "md",
    }
    # 已綁定則主按鈕改成「我已綁定守護群」視覺提示(仍可再點,handler 會回 already_bound)
    if already_bound:
        primary_bind = {
            "type": "button",
            "action": {
                "type": "message",
                "label": "我已綁定守護群",
                "text": "綁定守護群",
            },
            "style": "primary",
            "color": GREEN_DARK,
            "height": "md",
        }

    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": GREEN_DARK,
            "paddingTop": "lg",
            "paddingBottom": "lg",
            "paddingStart": "lg",
            "paddingEnd": "lg",
            "contents": [
                {
                    "type": "text",
                    "text": "📍 今天還在嗎",
                    "color": "#FFFFFF",
                    "size": "xxl",
                    "weight": "bold",
                    "align": "center",
                },
                {
                    "type": "text",
                    "text": "🛡️ 守護群已就緒",
                    "color": "#FFFFFF",
                    "size": "md",
                    "align": "center",
                    "margin": "sm",
                    "wrap": True,
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "paddingTop": "lg",
            "paddingBottom": "md",
            "contents": [
                {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "xs",
                    "backgroundColor": "#E8F8EE",
                    "cornerRadius": "md",
                    "paddingAll": "md",
                    "borderColor": GREEN_DARK,
                    "borderWidth": "1px",
                    "contents": [
                        {
                            "type": "text",
                            "text": "管理員可以一鍵綁定",
                            "size": "lg",
                            "weight": "bold",
                            "color": GREEN_DARK,
                        },
                        {
                            "type": "text",
                            "text": "把平安守護助理邀進群,代表管理員已準備好啟用守護。點下方「綁定守護群」即可完成",
                            "size": "md",
                            "color": GRAY,
                            "wrap": True,
                        },
                    ],
                },
                _owner_status_block(owner_info),
                {
                    "type": "text",
                    "text": "這個群可以做什麼",
                    "size": "md",
                    "weight": "bold",
                    "color": GRAY,
                    "margin": "sm",
                },
                {
                    "type": "text",
                    "text": "• 報平安：群裡也能快速簽到\n• 逾期提醒：沒簽到時通知守護人\n• SOS：緊急狀況在群裡同步\n• 建議：綁定後把助理設為群管理員",
                    "size": "md",
                    "color": GRAY_LIGHT,
                    "wrap": True,
                },
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "paddingAll": "md",
            "backgroundColor": "#FAFAFA",
            "contents": [
                primary_bind,
                {
                    "type": "box",
                    "layout": "horizontal",
                    "spacing": "sm",
                    "contents": [
                        _uri_button(
                            "報平安",
                            liff_entry_url(fragment="home"),
                            style="secondary",
                            color=GREEN_DARK,
                            height="sm",
                        ),
                        _uri_button(
                            "守護人",
                            liff_entry_url(open_action="onboarding"),
                            style="secondary",
                            color=GREEN_DARK,
                            height="sm",
                        ),
                        _uri_button(
                            "我的會員",
                            liff_entry_url(open_action="member"),
                            style="secondary",
                            color=GREEN_DARK,
                            height="sm",
                        ),
                    ],
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "spacing": "sm",
                    "contents": [
                        _uri_button(
                            "守護群設定",
                            liff_entry_url(open_action="guardians"),
                            style="link",
                            color=GREEN_DARK,
                            height="sm",
                        ),
                        _uri_button(
                            "查看方案",
                            f"{PUBLIC_BASE}/pricing.html",
                            style="link",
                            color=GRAY,
                            height="sm",
                        ),
                        _uri_button(
                            "首次引導",
                            liff_entry_url(open_action="onboarding"),
                            style="link",
                            color=GRAY,
                            height="sm",
                        ),
                    ],
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "spacing": "sm",
                    "contents": [
                        _postback_button("守護群狀態", "守護群狀態", style="link", color=GREEN_DARK, height="sm"),
                        _postback_button("管理員設定", "管理員設定", style="link", color=GRAY, height="sm"),
                    ],
                },
            ],
        },
    }


def _intro_step(num: str, title: str, desc: str):
    return {
        "type": "box",
        "layout": "horizontal",
        "spacing": "md",
        "paddingTop": "sm",
        "paddingBottom": "sm",
        "contents": [
            {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": GREEN_DARK,
                "cornerRadius": "xxl",
                "paddingAll": "sm",
                "width": "36px",
                "height": "36px",
                "justifyContent": "center",
                "alignItems": "center",
                "flex": 0,
                "contents": [
                    {
                        "type": "text",
                        "text": num,
                        "color": "#FFFFFF",
                        "size": "lg",
                        "weight": "bold",
                        "align": "center",
                    },
                ],
            },
            {
                "type": "box",
                "layout": "vertical",
                "spacing": "xs",
                "flex": 1,
                "contents": [
                    {
                        "type": "text",
                        "text": title,
                        "size": "lg",
                        "weight": "bold",
                        "color": GRAY,
                        "wrap": True,
                    },
                    {
                        "type": "text",
                        "text": desc,
                        "size": "md",
                        "color": GRAY_LIGHT,
                        "wrap": True,
                    },
                ],
            },
        ],
    }


# ───────────────────────────────────────────────────────────
# 2. 守護群狀態
# ───────────────────────────────────────────────────────────

_PLAN_LABEL = {
    "paid_799": "799 月費",
    "paid_799_year": "799 年費",
}


def _plan_label(plan: str) -> str:
    return _PLAN_LABEL.get(plan, plan or "未訂閱")


def guardian_group_status_flex(profile: dict, state: dict):
    """守護群狀態:顯示用戶所有守護群 + 額度 + 每群人數。"""
    user_id = profile.get("line_user_id", "")
    group_ids = profile.get("guardian_group_ids") or []
    group_limit = profile.get("plan", "") and 3 if profile.get("plan") == "paid_799_year" else (1 if profile.get("plan") == "paid_799" else 0)
    all_groups = state.get("guardian_groups", {}) or {}

    contents = []
    if not group_ids or not all_groups.get(group_ids[0] if group_ids else "", {}).get("owner_line_user_id") == user_id:
        owned = [gid for gid in group_ids if all_groups.get(gid, {}).get("owner_line_user_id") == user_id]
    else:
        owned = list(group_ids)

    # 總覽區塊
    contents.append({
        "type": "box",
        "layout": "vertical",
        "spacing": "xs",
        "backgroundColor": GREEN_SOFT,
        "cornerRadius": "md",
        "paddingAll": "md",
        "contents": [
            {
                "type": "text",
                "text": f"📊 你的守護群 ({len(owned)} 群)",
                "size": "xl",
                "weight": "bold",
                "color": GREEN_DARK,
            },
            {
                "type": "text",
                "text": f"目前方案:{_plan_label(profile.get('plan', ''))},額度 {len(owned)}/{group_limit} 群",
                "size": "md",
                "color": GRAY,
                "wrap": True,
            },
        ],
    })

    if not owned:
        contents.append({
            "type": "text",
            "text": "尚未綁定任何守護群,請先升級 799 方案,然後邀請「平安守護助理」進群,再點「綁定平安守護助理」",
            "size": "md",
            "color": GRAY,
            "wrap": True,
            "margin": "md",
        })
    else:
        body_contents = []
        for idx, gid in enumerate(owned, start=1):
            g = all_groups.get(gid, {})
            mc = g.get("member_count_at_bind") or len(g.get("member_ids_at_bind") or [])
            plan = _plan_label(profile.get("plan", ""))
            body_contents.append({
                "type": "box",
                "layout": "horizontal",
                "spacing": "md",
                "paddingTop": "sm",
                "paddingBottom": "sm",
                "contents": [
                    {
                        "type": "text",
                        "text": f"{idx}.",
                        "size": "lg",
                        "weight": "bold",
                        "color": GREEN_DARK,
                    },
                    {
                        "type": "text",
                        "text": f"{plan} · {mc} 人",
                        "size": "lg",
                        "color": GRAY,
                        "flex": 1,
                        "wrap": True,
                    },
                ],
            })
            if idx < len(owned):
                body_contents.append({
                    "type": "separator",
                    "margin": "sm",
                })
        contents.append({
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "backgroundColor": "#FFFFFF",
            "cornerRadius": "md",
            "paddingAll": "md",
            "contents": body_contents,
        })

    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": GREEN_DARK,
            "paddingTop": "lg",
            "paddingBottom": "lg",
            "paddingStart": "lg",
            "paddingEnd": "lg",
            "contents": [
                {
                    "type": "text",
                    "text": "📊 守護群狀態",
                    "color": "#FFFFFF",
                    "size": "xxl",
                    "weight": "bold",
                    "align": "center",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "lg",
            "paddingAll": "lg",
            "contents": contents,
        },
        "footer": {
            "type": "box",
            "layout": "horizontal",
            "spacing": "sm",
            "paddingAll": "md",
            "backgroundColor": "#FAFAFA",
            "contents": _footer_buttons(("status", "guide", "admin")),
        },
    }


# ───────────────────────────────────────────────────────────
# 3. 綁定守護群確認(大綠色按鈕 + 結果)
# ───────────────────────────────────────────────────────────

def guardian_group_bind_confirm_flex(result: dict):
    """「綁定守護群」完成後的 Flex。成功主標固定為「我已綁定守護群」。"""
    already = result.get("already_bound")
    count = result.get("guardian_group_count", 1)
    limit = result.get("guardian_group_limit", 1)

    head_text = "我已綁定守護群"
    if already:
        body_text = f"此群已是你的守護群,目前已綁定 {count}/{limit} 個,無需重複操作"
    else:
        body_text = f"綁定成功,目前已綁定 {count}/{limit} 個守護群。逾期未簽到與 SOS 提醒會在此群發送"

    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": GREEN_DARK,
            "paddingTop": "lg",
            "paddingBottom": "lg",
            "paddingStart": "lg",
            "paddingEnd": "lg",
            "contents": [
                {
                    "type": "text",
                    "text": f"✅ {head_text}",
                    "color": "#FFFFFF",
                    "size": "xxl",
                    "weight": "bold",
                    "align": "center",
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
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "xs",
                    "backgroundColor": GREEN_SOFT,
                    "cornerRadius": "md",
                    "paddingAll": "md",
                    "contents": [
                        {
                            "type": "text",
                            "text": body_text,
                            "size": "lg",
                            "color": GRAY,
                            "wrap": True,
                        },
                    ],
                },
                {
                    "type": "text",
                    "text": "接下來建議:",
                    "size": "md",
                    "color": GRAY_LIGHT,
                    "margin": "md",
                },
                {
                    "type": "text",
                    "text": "• 把「平安守護助理」設為此群管理員(必做)\n• 邀請長輩/家人加入此群\n• 設定每日簽到時間",
                    "size": "md",
                    "color": GRAY,
                    "wrap": True,
                },
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "paddingAll": "md",
            "backgroundColor": "#FAFAFA",
            "contents": [
                _postback_button("守護群狀態", "守護群狀態", style="primary", color=GREEN_DARK, height="md"),
                {
                    "type": "box",
                    "layout": "horizontal",
                    "spacing": "sm",
                    "contents": [
                        _postback_button("使用說明", "使用說明", style="link", color=GRAY, height="sm"),
                        _postback_button("管理員設定", "管理員設定", style="link", color=GRAY, height="sm"),
                    ],
                },
            ],
        },
    }


def guardian_group_bind_fail_flex(reason: str):
    """綁定失敗 Flex(其他會員已綁 / 非 799 / 超限)。"""
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": RED_WARN,
            "paddingTop": "lg",
            "paddingBottom": "lg",
            "paddingStart": "lg",
            "paddingEnd": "lg",
            "contents": [
                {
                    "type": "text",
                    "text": "❌ 無法綁定此群",
                    "color": "#FFFFFF",
                    "size": "xxl",
                    "weight": "bold",
                    "align": "center",
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
                    "text": reason,
                    "size": "lg",
                    "color": GRAY,
                    "wrap": True,
                },
            ],
        },
        "footer": {
            "type": "box",
            "layout": "horizontal",
            "spacing": "sm",
            "paddingAll": "md",
            "backgroundColor": "#FAFAFA",
            "contents": _footer_buttons(("guide", "admin")),
        },
    }


# ───────────────────────────────────────────────────────────
# 4. 使用說明(給群成員)
# ───────────────────────────────────────────────────────────

def guardian_group_user_guide_flex():
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": GREEN_DARK,
            "paddingTop": "lg",
            "paddingBottom": "lg",
            "paddingStart": "lg",
            "paddingEnd": "lg",
            "contents": [
                {
                    "type": "text",
                    "text": "📖 使用說明",
                    "color": "#FFFFFF",
                    "size": "xxl",
                    "weight": "bold",
                    "align": "center",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "paddingAll": "lg",
            "contents": [
                _guide_step("1", "升級 799 守護版", "在 LINE 主選單「方案」挑月費或年費,完成付款才能開守護群"),
                _guide_step("2", "建一個新的 LINE 群", "把你最關心的家人/長輩全部拉進來,群名可標「守護:OOO」"),
                _guide_step("3", "把平安守護助理邀進群", "從「平安守護助理」聊天室右上「≡」→「邀請」,選這個新群"),
                _guide_step("4", "把平安守護助理設為管理員", "這步必做,點下方「管理員設定」看 6 步驟教學"),
                _guide_step("5", "在群裡打「綁定平安守護助理」", "會回「✅ 已完成綁定平安守護助理」,這樣這個群就會收到逾期未簽到/SOS 通知"),
                _guide_step("6", "每天在群裡打「簽到」", "成員簽到會在群裡顯示 ✓,沒簽到時會在群裡提醒"),
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "paddingAll": "md",
            "backgroundColor": "#FAFAFA",
            "contents": [
                _postback_button("管理員設定 6 步驟", "管理員設定", style="primary", color=GREEN_DARK, height="md"),
                {
                    "type": "box",
                    "layout": "horizontal",
                    "spacing": "sm",
                    "contents": _footer_buttons(("status", "guide", "admin")),
                },
            ],
        },
    }


def _guide_step(num: str, title: str, desc: str):
    return {
        "type": "box",
        "layout": "horizontal",
        "spacing": "md",
        "paddingTop": "sm",
        "paddingBottom": "sm",
        "contents": [
            {
                "type": "text",
                "text": num,
                "size": "xxl",
                "weight": "bold",
                "color": GREEN_DARK,
                "flex": 0,
            },
            {
                "type": "box",
                "layout": "vertical",
                "spacing": "xs",
                "flex": 1,
                "contents": [
                    {
                        "type": "text",
                        "text": title,
                        "size": "lg",
                        "weight": "bold",
                        "color": GRAY,
                        "wrap": True,
                    },
                    {
                        "type": "text",
                        "text": desc,
                        "size": "md",
                        "color": GRAY_LIGHT,
                        "wrap": True,
                    },
                ],
            },
        ],
    }


# ───────────────────────────────────────────────────────────
# 5. 管理員設定(6 步驟怎麼把 Bot 設為管理員)
# ───────────────────────────────────────────────────────────

def guardian_group_admin_setup_flex():
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": ORANGE,
            "paddingTop": "lg",
            "paddingBottom": "lg",
            "paddingStart": "lg",
            "paddingEnd": "lg",
            "contents": [
                {
                    "type": "text",
                    "text": "⚙️ 設定「平安守護助理」為管理員",
                    "color": "#FFFFFF",
                    "size": "xxl",
                    "weight": "bold",
                    "align": "center",
                },
                {
                    "type": "text",
                    "text": "LINE 規定「平安守護助理」無法自動設自己為管理員,需用戶手動操作",
                    "color": "#FFFFFF",
                    "size": "md",
                    "align": "center",
                    "margin": "sm",
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
                _admin_step("1", "打開群設定", "在群聊畫面右上角點「≡」(三條線)圖示"),
                _admin_step("2", "進入成員列表", "選「成員」,找到「平安守護助理」"),
                _admin_step("3", "長按「平安守護助理」名稱", "在「平安守護助理」名稱上長按,跳出選單"),
                _admin_step("4", "選「設為管理員」", "從選單中選「設為管理員」"),
                _admin_step("5", "確認權限", "LINE 會列出可授與的權限,直接按「確定」即可"),
                _admin_step("6", "完成", "回群裡,打「守護群狀態」可確認是否已生效,看到「✅ 已設為管理員」就成功"),
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "paddingAll": "md",
            "backgroundColor": "#FAFAFA",
            "contents": [
                _postback_button("📖 使用說明", "使用說明", style="primary", color=GREEN_DARK, height="md"),
                {
                    "type": "box",
                    "layout": "horizontal",
                    "spacing": "sm",
                    "contents": _footer_buttons(("status", "guide", "admin")),
                },
            ],
        },
    }


def _admin_step(num: str, title: str, desc: str):
    return {
        "type": "box",
        "layout": "horizontal",
        "spacing": "md",
        "paddingTop": "sm",
        "paddingBottom": "sm",
        "contents": [
            {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": ORANGE,
                "cornerRadius": "xxl",
                "paddingAll": "md",
                "width": "48px",
                "height": "48px",
                "justifyContent": "center",
                "alignItems": "center",
                "flex": 0,
                "contents": [
                    {
                        "type": "text",
                        "text": num,
                        "color": "#FFFFFF",
                        "size": "xl",
                        "weight": "bold",
                        "align": "center",
                    },
                ],
            },
            {
                "type": "box",
                "layout": "vertical",
                "spacing": "xs",
                "flex": 1,
                "contents": [
                    {
                        "type": "text",
                        "text": title,
                        "size": "lg",
                        "weight": "bold",
                        "color": GRAY,
                        "wrap": True,
                    },
                    {
                        "type": "text",
                        "text": desc,
                        "size": "md",
                        "color": GRAY_LIGHT,
                        "wrap": True,
                    },
                ],
            },
        ],
    }



def _owner_status_block(owner_info):
    """2026-07-21 patch 17: 根據 owner 狀態回傳對應的顯示區塊(4 種狀態)。

    - 未綁定 → 回空 box(不顯示)
    - 已綁定 + 使用者是 owner + 方案有效 → 🛡️ 你是這個守護群的管理員(綠色框)
    - 已綁定 + 使用者是 owner + 方案過期 → ⚠️ 管理員資格已過期,請續約(橘色框)
    - 已綁定 + 使用者不是 owner → 👥 這群已由管理員綁定(灰色框)

    注意:patch 17 軟降級 — 方案過期時不自動解綁,只降級顯示。
    蝦董續約後會自動恢復 🛡️ 狀態。
    """
    if not owner_info or not owner_info.get("bound"):
        return {"type": "box", "layout": "vertical", "contents": []}

    if owner_info.get("is_owner"):
        if owner_info.get("is_active"):
            return {
                "type": "box",
                "layout": "vertical",
                "spacing": "xs",
                "backgroundColor": "#E8F8EE",
                "cornerRadius": "md",
                "paddingAll": "md",
                "borderColor": GREEN_DARK,
                "borderWidth": "2px",
                "contents": [
                    {
                        "type": "text",
                        "text": "🛡️ 你是這個守護群的管理員",
                        "size": "lg",
                        "weight": "bold",
                        "color": GREEN_DARK,
                        "wrap": True,
                    },
                    {
                        "type": "text",
                        "text": "只有你能解綁、設定與重新邀請「平安守護助理」,其他成員只能簽到與查看狀態",
                        "size": "md",
                        "color": GRAY,
                        "wrap": True,
                    },
                ],
            }

        # 方案過期 → 軟降級橘框
        plan_label = owner_info.get("owner_plan") or "原方案"
        return {
            "type": "box",
            "layout": "vertical",
            "spacing": "xs",
            "backgroundColor": "#FFF4E5",
            "cornerRadius": "md",
            "paddingAll": "md",
            "borderColor": ORANGE,
            "borderWidth": "2px",
            "contents": [
                {
                    "type": "text",
                    "text": "⚠️ 管理員資格已過期",
                    "size": "lg",
                    "weight": "bold",
                    "color": ORANGE,
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": f"你的「{plan_label}」已過期,目前無法執行管理動作(解綁/設定/重新邀請)。守護群綁定仍在,續約後自動恢復 🛡️ 狀態",
                    "size": "md",
                    "color": GRAY,
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": "💡 在主選單點「方案」續約,綁定關係不會重來",
                    "size": "md",
                    "color": GRAY_LIGHT,
                    "wrap": True,
                },
            ],
        }

    return {
        "type": "box",
        "layout": "vertical",
        "spacing": "xs",
        "backgroundColor": "#F5F5F5",
        "cornerRadius": "md",
        "paddingAll": "md",
        "contents": [
            {
                "type": "text",
                "text": "👥 這群已由管理員綁定",
                "size": "lg",
                "weight": "bold",
                "color": GRAY,
                "wrap": True,
            },
            {
                "type": "text",
                "text": "你是成員之一,簽到、查看狀態都可以,解綁/設定需找管理員",
                "size": "md",
                "color": GRAY_LIGHT,
                "wrap": True,
            },
        ],
    }


def welcome_flex(display_name: str | None = None):
    """加好友歡迎 Flex：Exact 歡迎文案 + 單一主 CTA「立即綁定守護人」。

    display_name：LINE 顯示名稱；缺省時用「您」。
    主 CTA：永久 liff.line.me 入口（內嵌）→ 先一鍵分享邀請 → 再填守護人表單 → 私訊預警提醒設定。
    僅保留一個大按鈕；標題／內文放大方便閱讀。不使用 BOT 字眼。
    """
    name = (display_name or "").strip() or "您"
    greeting = f"👋 {name} 您好，歡迎加入今天還在嗎"
    # 永久連結：開 LIFF 內嵌 → onboarding（分享邀請 → 守護人表單 → 提醒）。勿硬編碼 OAuth code/state。
    bind_uri = liff_entry_url(open_action="onboarding")
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": GREEN_DARK,
            "paddingTop": "xl",
            "paddingBottom": "xl",
            "paddingStart": "lg",
            "paddingEnd": "lg",
            "contents": [
                {
                    "type": "text",
                    "text": greeting,
                    "color": "#FFFFFF",
                    "size": "xxl",
                    "weight": "bold",
                    "align": "center",
                    "wrap": True,
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "lg",
            "paddingTop": "lg",
            "paddingBottom": "md",
            "contents": [
                {
                    "type": "text",
                    "text": (
                        "我是您的每日平安小助手，會在您設定的時間提醒您報平安，"
                        "只有超過時間仍未報平安，才會通知您指定的守護人"
                    ),
                    "size": "lg",
                    "color": GRAY,
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": "開始使用前，請先完成 1 位守護人綁定，並設定每日提醒時間",
                    "size": "lg",
                    "color": GRAY,
                    "wrap": True,
                    "weight": "bold",
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "xs",
                    "backgroundColor": "#FFF8E6",
                    "cornerRadius": "md",
                    "paddingAll": "md",
                    "borderColor": ORANGE,
                    "borderWidth": "1px",
                    "contents": [
                        {
                            "type": "text",
                            "text": "🎁 完成設定即享 7 天免費安心體驗",
                            "size": "lg",
                            "weight": "bold",
                            "color": ORANGE,
                            "wrap": True,
                        },
                    ],
                },
                {
                    "type": "text",
                    "text": "🚨 緊急狀況請直接撥打 119，聊天訊息可能因網路延遲",
                    "size": "lg",
                    "color": GRAY_LIGHT,
                    "wrap": True,
                },
            ],
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
                        "type": "uri",
                        "label": "立即綁定守護人",
                        "uri": bind_uri,
                    },
                    "style": "primary",
                    "color": GREEN_DARK,
                    "height": "md",
                },
            ],
        },
    }
