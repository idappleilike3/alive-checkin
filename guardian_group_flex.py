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
from urllib.parse import quote, urlencode


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


def liff_path_url(path: str) -> str:
    """直連 LIFF 子路徑（不經 SPA index / home）。

    Endpoint 若為 https://alive-checkin.onrender.com/ ，則
    https://liff.line.me/<LIFF_ID>/liff/share-invite.html
    會直接開啟 /liff/share-invite.html，不會先載入首頁。
    """
    clean = "/" + str(path or "").lstrip("/")
    return f"https://liff.line.me/{get_liff_id()}{clean}"


def share_invite_liff_url() -> str:
    """一鍵邀請守護人：專用分享頁（init→login→導向 line.me/R/share；失敗才全螢幕重試）。"""
    return liff_path_url("/liff/share-invite.html")


def pricing_direct_url() -> str:
    """方案頁直連（勿走 LIFF 首頁再轉跳）。"""
    return f"{(os.environ.get('APP_PUBLIC_URL') or PUBLIC_BASE).rstrip('/')}/liff/pricing.html"


def liff_entry_url(*, open_action: str | None = None, fragment: str = "", **query) -> str:
    """永久內嵌 LIFF 入口（https://liff.line.me/<LIFF_ID>）。

    不要使用含 code= / state= 的一次性 OAuth callback URL。
    open_action 會傳到 Endpoint（例如 open=onboarding → 先一鍵分享邀請，再填守護人表單→提醒設定）。
    其餘 query（如 invite_from / friend_invite）會附加在同一條永久連結上。

    重要：query 用 ``?`` 不要用 ``/?``。``/?`` 會讓 LIFF 把 path 當成 ``/``
    接到 Endpoint（常是 .../），合成 ``...//?``，OAuth／LIFF 閘道容易回 400。
    """
    url = f"https://liff.line.me/{get_liff_id()}"
    params = {}
    if open_action:
        params["open"] = open_action
    for key, value in (query or {}).items():
        if value is None or value == "":
            continue
        key_s = str(key)
        if key_s in {"code", "state", "liffClientId", "liffRedirectUri"}:
            continue
        params[key_s] = str(value)
    if params:
        # allow path-like open actions such as onboarding/invite
        url += "?" + urlencode(params, safe="/")
    elif fragment:
        url += f"#{fragment.lstrip('#')}"
    return url


def guardian_invite_bind_url(invite_from: str) -> str:
    """受邀者綁定連結：強制進 LINE App，避免 liff.line.me/? 造成閘道 400。"""
    safe = "".join(ch for ch in str(invite_from or "").strip() if ch.isalnum() or ch in "_-")
    lid = get_liff_id()
    if not safe:
        return f"https://line.me/R/app/{lid}?open=onboarding"
    return f"https://line.me/R/app/{lid}?invite_from={quote(safe, safe='')}"


def guardian_invite_share_text(invite_from: str, *, nickname: str = "") -> str:
    """分享給好友的純文字（含綁定連結）。"""
    name = (nickname or "").strip()
    prefix = f"嗨 {name}，" if name else ""
    bind = guardian_invite_bind_url(invite_from)
    return (
        f"{prefix}我想邀請你成為「每日平安」的守護人。\n"
        "請用 LINE 點開下面連結\n\n"
        f"{bind}"
    )


def line_native_share_url(text: str) -> str:
    """LINE 原生分享（好友選擇）：由選單／按鈕點擊開啟，不經 LIFF shareTargetPicker。"""
    return "https://line.me/R/share?text=" + quote(str(text or ""), safe="")


def share_invite_flex(invite_from: str, *, nickname: str = ""):
    """一鍵邀請回覆：整張卡片 URI＝line.me/R/share（無教學文案大按鈕頁）。"""
    text = guardian_invite_share_text(invite_from, nickname=nickname)
    share_uri = line_native_share_url(text)
    return {
        "type": "bubble",
        "action": {"type": "uri", "label": "傳給家人", "uri": share_uri},
        "body": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "xl",
            "contents": [
                {
                    "type": "text",
                    "text": "傳給家人",
                    "weight": "bold",
                    "size": "xl",
                    "color": "#067647",
                    "align": "center",
                    "wrap": True,
                }
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "lg",
            "contents": [
                _uri_button(
                    "傳給家人",
                    share_uri,
                    style="primary",
                    color=GREEN_DARK,
                    height="md",
                )
            ],
        },
    }

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


def _group_quick_actions():
    """守護群固定 4 顆大按鈕，採 2x2 排版避免 LINE 手機版文字被切掉。"""
    rows = [
        [
            _uri_button("我平安", liff_entry_url(open_action="checkin"), style="secondary", color=GREEN_DARK, height="md"),
            _postback_button("聯絡家人", "聯絡家人", style="secondary", color=GREEN_DARK, height="md"),
        ],
        [
            # 用 message 觸發 Bot 緊急求助 Flex（非只開 LIFF）
            _postback_button("需要幫忙", "需要幫忙", style="secondary", color=RED_WARN, height="md"),
            _postback_button("守護群狀態", "守護群狀態", style="secondary", color=GREEN_DARK, height="md"),
        ],
    ]
    return [
        {
            "type": "box",
            "layout": "horizontal",
            "spacing": "sm",
            "contents": row,
        }
        for row in rows
    ]


# ───────────────────────────────────────────────────────────
# 1. 自我介紹(Intro)
# ───────────────────────────────────────────────────────────

def guardian_group_intro_flex(owner_info: dict | None = None):
    """進群自我介紹 Flex：管理員已就緒，一鍵綁定守護群。

    設計重點:
    - 短文案：邀進群 = 管理員準備綁定
    - 主 CTA：「點我綁定守護群」(message → 觸發既有 keyword handler)
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
            "label": "點我綁定守護群",
            "text": "點我綁定守護群",
        },
        "style": "primary",
        "color": GREEN_DARK,
        "height": "md",
    }
    if already_bound:
        primary_bind = {
            "type": "button",
            "action": {
                "type": "message",
                "label": "我已完成守護群設定",
                "text": "守護群狀態",
            },
            "style": "primary",
            "color": GREEN_DARK,
            "height": "md",
        }

    # LINE Flex 禁止空 contents box；未綁定時不可塞空區塊，否則整張卡被 API 拒收
    body_contents = [
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
                    "text": "這裡用來互相關心",
                    "size": "lg",
                    "weight": "bold",
                    "color": GREEN_DARK,
                },
                {
                    "type": "text",
                    "text": "收到家人的平安訊息。在這提醒報平安、發需要幫忙通知、逾期未報平安或主動求助時，才會在群裡提醒",
                    "size": "lg",
                    "color": GRAY,
                    "wrap": True,
                },
            ],
        },
    ]
    owner_block = _owner_status_block(owner_info)
    if owner_block:
        body_contents.append(owner_block)
    body_contents.extend(
        [
            {
                "type": "text",
                "text": "管理員第一次進群，請先完成守護群設定",
                "size": "lg",
                "weight": "bold",
                "color": GRAY,
                "margin": "sm",
            },
            {
                "type": "text",
                "text": "完成後會顯示「我已完成守護群設定」。群內狀態明細預設只有管理員可以查看，保護家人隱私",
                "size": "lg",
                "color": GRAY_LIGHT,
                "wrap": True,
            },
        ]
    )

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
                    "text": "❤️ 每日平安",
                    "color": "#FFFFFF",
                    "size": "xxl",
                    "weight": "bold",
                    "align": "center",
                },
                {
                    "type": "text",
                    "text": "歡迎加入守護群",
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
            "contents": body_contents,
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "paddingAll": "md",
            "backgroundColor": "#FAFAFA",
            "contents": [primary_bind, *_group_quick_actions()],
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
            "text": "尚未綁定任何守護群,請先升級 799 方案,然後邀請「每日平安」官方帳號進群,再點「點我綁定守護群」",
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
    """「綁定守護群」完成後的 Flex。成功主標固定為「我已完成守護群設定」。"""
    already = result.get("already_bound")
    count = result.get("guardian_group_count", 1)
    limit = result.get("guardian_group_limit", 1)

    head_text = "我已完成守護群設定"
    if already:
        body_text = f"此群已是你的守護群,目前已綁定 {count}/{limit} 個,無需重複操作"
    else:
        body_text = f"綁定成功,目前已綁定 {count}/{limit} 個守護群。逾期未簽到與需要幫忙提醒會在此群發送"

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
                    "text": "• 把「每日平安」設為此群管理員(必做)\n• 邀請長輩/家人加入此群\n• 設定每日簽到時間",
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
                _guide_step("3", "把每日平安邀進群", "從「每日平安」聊天室右上「≡」→「邀請」,選這個新群"),
                _guide_step("4", "把每日平安設為管理員", "這步必做,點下方「管理員設定」看 6 步驟教學"),
                _guide_step("5", "在群裡點「點我綁定守護群」", "會回「✅ 我已完成守護群設定」,這樣這個群就會收到逾期未簽到／需要幫忙通知"),
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
                    "text": "⚙️ 設定「每日平安」為管理員",
                    "color": "#FFFFFF",
                    "size": "xxl",
                    "weight": "bold",
                    "align": "center",
                },
                {
                    "type": "text",
                    "text": "LINE 規定「每日平安」無法自動設自己為管理員,需用戶手動操作",
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
                _admin_step("2", "進入成員列表", "選「成員」,找到「每日平安」"),
                _admin_step("3", "長按「每日平安」名稱", "在「每日平安」名稱上長按,跳出選單"),
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
        # 不可回傳空 contents（LINE Flex 會整卡拒收 → 進群歡迎詞消失）
        return None

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
                        "text": "只有你能解綁、設定與重新邀請「每日平安」,其他成員只能簽到與查看狀態",
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


_WELCOME_PLACEHOLDER_NAMES = frozenset(
    {"", "您", "LINE 使用者", "LINE 會員", "LINE 聯絡人", "使用者"}
)


def welcome_greeting_text(display_name: str | None = None) -> str:
    """歡迎標題：有真實暱稱就寫名；否則不寫「您」，避免看起來像沒寫誰。"""
    name = (display_name or "").strip()
    if name and name not in _WELCOME_PLACEHOLDER_NAMES:
        return f"👋 {name} 您好，歡迎加入「每日平安」"
    return "👋 您好，歡迎加入「每日平安」"


def welcome_flex(display_name: str | None = None):
    """加好友歡迎 Flex（粉白風格，對齊設計稿）：真實暱稱問候 + 兩顆 CTA。

    結構對齊 mockup：
    - Header：唯一 Logo + 👋 您好歡迎加入 / 每日平安
    - Hero：白卡視覺（心＋大字＋手機「我平安」），無第二個 Logo
    - Body：兩步驟並排、黃底 7 天免費、119/110 免責
    - Footer：立即開始設定 + 查看方案
    """
    greeting = welcome_greeting_text(display_name)
    setup_uri = liff_entry_url(open_action="onboarding")
    pricing_uri = pricing_direct_url()
    base = (os.environ.get("APP_PUBLIC_URL") or PUBLIC_BASE).rstrip("/")
    logo_uri = f"{base}/assets/daily-peace-logo.png"
    heart_uri = f"{base}/assets/welcome-heart-banner.png"
    pink_bg = "#FFF5F8"
    pink_soft = "#FFE4EC"
    pink_accent = "#DB2777"
    text_dark = "#831843"
    yellow_bg = "#FFF7D6"
    step_bg = "#FFFFFF"
    teal_btn = "#0EA5A4"

    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "paddingAll": "lg",
            "backgroundColor": pink_bg,
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "image",
                            "url": logo_uri,
                            "size": "sm",
                            "aspectMode": "fit",
                            "aspectRatio": "1:1",
                            "flex": 0,
                        }
                    ],
                    "justifyContent": "center",
                },
                {
                    "type": "text",
                    "text": greeting,
                    "weight": "bold",
                    "size": "lg",
                    "color": text_dark,
                    "wrap": True,
                    "align": "center",
                },
                {
                    "type": "text",
                    "text": "每日平安",
                    "weight": "bold",
                    "size": "xl",
                    "color": pink_accent,
                    "wrap": True,
                    "align": "center",
                },
            ],
        },
        "hero": {
            "type": "image",
            "url": heart_uri,
            "size": "full",
            "aspectMode": "fit",
            "aspectRatio": "20:9",
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "paddingAll": "lg",
            "backgroundColor": pink_bg,
            "contents": [
                {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "sm",
                    "paddingAll": "md",
                    "backgroundColor": "#FFFFFF",
                    "cornerRadius": "xl",
                    "contents": [
                        {
                            "type": "text",
                            "text": "每天 10 秒，報個平安",
                            "weight": "bold",
                            "size": "xl",
                            "color": pink_accent,
                            "wrap": True,
                            "align": "center",
                        },
                        {
                            "type": "text",
                            "text": "平常不打擾，有事才通知守護人",
                            "weight": "bold",
                            "size": "lg",
                            "color": text_dark,
                            "wrap": True,
                            "align": "center",
                        },
                    ],
                },
                {
                    "type": "text",
                    "text": "📋 開始使用前，只要完成兩個步驟：",
                    "weight": "bold",
                    "size": "lg",
                    "color": text_dark,
                    "wrap": True,
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "spacing": "md",
                    "contents": [
                        {
                            "type": "box",
                            "layout": "vertical",
                            "spacing": "sm",
                            "paddingAll": "md",
                            "backgroundColor": step_bg,
                            "cornerRadius": "xl",
                            "flex": 1,
                            "contents": [
                                {
                                    "type": "text",
                                    "text": "① 新增 1 位守護人",
                                    "weight": "bold",
                                    "size": "lg",
                                    "color": pink_accent,
                                    "wrap": True,
                                },
                                {
                                    "type": "text",
                                    "text": "讓重要的人在關鍵時刻收到通知",
                                    "weight": "bold",
                                    "size": "md",
                                    "color": GRAY,
                                    "wrap": True,
                                },
                            ],
                        },
                        {
                            "type": "box",
                            "layout": "vertical",
                            "spacing": "sm",
                            "paddingAll": "md",
                            "backgroundColor": step_bg,
                            "cornerRadius": "xl",
                            "flex": 1,
                            "contents": [
                                {
                                    "type": "text",
                                    "text": "② 設定每日提醒時間",
                                    "weight": "bold",
                                    "size": "lg",
                                    "color": pink_accent,
                                    "wrap": True,
                                },
                                {
                                    "type": "text",
                                    "text": "系統會在您設定的時間提醒您報平安",
                                    "weight": "bold",
                                    "size": "md",
                                    "color": GRAY,
                                    "wrap": True,
                                },
                            ],
                        },
                    ],
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "xs",
                    "paddingAll": "md",
                    "backgroundColor": yellow_bg,
                    "cornerRadius": "xl",
                    "contents": [
                        {
                            "type": "text",
                            "text": "🎁 完成設定即可享 7 天免費安心體驗",
                            "weight": "bold",
                            "size": "lg",
                            "color": pink_accent,
                            "wrap": True,
                            "align": "center",
                        },
                    ],
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "paddingAll": "md",
                    "backgroundColor": pink_soft,
                    "cornerRadius": "xl",
                    "contents": [
                        {
                            "type": "text",
                            "text": "🚨 緊急狀況請直接撥打 119 或 110，本服務無法取代緊急救援。",
                            "weight": "bold",
                            "size": "md",
                            "color": RED_WARN,
                            "wrap": True,
                        },
                    ],
                },
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "paddingAll": "lg",
            "backgroundColor": pink_bg,
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "uri",
                        "label": "立即開始設定",
                        "uri": setup_uri,
                    },
                    "style": "primary",
                    "color": GREEN_DARK,
                    "height": "md",
                },
                {
                    "type": "button",
                    "action": {
                        "type": "uri",
                        "label": "查看方案",
                        "uri": pricing_uri,
                    },
                    "style": "primary",
                    "color": teal_btn,
                    "height": "md",
                },
            ],
        },
    }
