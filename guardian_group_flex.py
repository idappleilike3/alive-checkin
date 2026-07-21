"""守護群 Flex Message 構建器(2026-07-21 patch 11)。

5 個 Flex 用途:
1. guardian_group_intro_flex()       — Bot 加入群組時的自我介紹
2. guardian_group_status_flex()      — 守護群狀態查詢
3. guardian_group_bind_confirm_flex  — 綁定完成確認(大綠色按鈕 + 結果)
4. guardian_group_user_guide_flex()  — 使用說明(給群成員)
5. guardian_group_admin_setup_flex() — 管理員設定 6 步驟

設計原則:
- 老人/長者閱讀:字級只用 xxl(20-24px) / lg(16-18px) / md(14px),禁 sm/xs
- 顏色:綠(#06C755 LINE 綠 / #00B900 深綠 / #4A9D4A 淺綠)
- 句末無「。」,訊息用「,」分隔(2026-07-20 17:44 蝦董新規則)
- footer 按鈕 postback 文字訊息,點下去觸發對應 handler
"""

from __future__ import annotations


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
    """Bot 加入群組時的「守護群 6 步驟教學」Flex。

    2026-07-21 patch 12: 從「自我介紹」改成「6 步驟教學」。
    給新進群的人一進來就看懂:我會做什麼 + 該按哪個按鈕。
    2026-07-21 patch 13: 加 「📍 今天還在嗎」 品牌主標 + body 開頭 brand 區塊
    (不然進群人不知道這是哪個服務的 bot)
    2026-07-21 patch 16: 加 owner 狀態區塊
      - 未綁定 → 不加
      - 已綁定 + 使用者是 owner → 「🛡️ 你是這個守護群的管理員」
      - 已綁定 + 使用者不是 owner → 「👥 這群已由管理員綁定」

    owner_info 結構: {
        "bound": bool,
        "is_owner": bool,      # 使用者是不是 owner
        "owner_id": str | None,
        "bound_at": str | None,
    }
    """
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
                    "text": "🛡️ 平安守護助手 · 守護群 6 步驟教學",
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
                # Brand 區塊:告訴進群人這是哪個服務的 bot
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
                            "text": "🤖 我是誰",
                            "size": "lg",
                            "weight": "bold",
                            "color": GREEN_DARK,
                        },
                        {
                            "type": "text",
                            "text": "「今天還在嗎」這個服務的平安守護助手,專門守護長輩平安,在這群提醒簽到、發 SOS 通知",
                            "size": "md",
                            "color": GRAY,
                            "wrap": True,
                        },
                    ],
                },
                # 2026-07-21 patch 16: owner 狀態區塊
                _owner_status_block(owner_info),
                _intro_step("1", "升級 799 守護版", "在 LINE 主選單點「方案」,挑月費或年費,完成付款才能開守護群"),
                _intro_step("2", "建一個 LINE 群", "把你最關心的家人/長輩拉進來,群名可標「守護:OOO」"),
                _intro_step("3", "把平安守護助手邀進群", "從「平安守護助手」聊天室右上「≡」→「邀請」,選這個新群"),
                _intro_step("4", "把平安守護助手設為管理員", "必做!點下方「管理員設定」看 6 步驟教學"),
                _intro_step("5", "在群裡打「綁定平安守護助手」", "會回「✅ 已完成綁定平安守護助手」,此群就會收到逾期未簽到/SOS 通知"),
                _intro_step("6", "每天在群裡打「簽到」", "沒簽到時會在群裡提醒所有守護人"),
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "paddingAll": "md",
            "backgroundColor": "#FAFAFA",
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "message",
                        "label": "綁定平安守護助手",
                        "text": "綁定平安守護助手",
                    },
                    "style": "primary",
                    "color": GREEN_DARK,
                    "height": "md",
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "spacing": "sm",
                    "contents": _footer_buttons(("status", "guide", "admin")),
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
            "text": "尚未綁定任何守護群,請先升級 799 方案,然後邀請「平安守護助手」進群,再點「綁定平安守護助手」",
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
    """「綁定平安守護助手」指令完成後的 Flex(綠大按鈕視覺 + 結果)。"""
    already = result.get("already_bound")
    count = result.get("guardian_group_count", 1)
    limit = result.get("guardian_group_limit", 1)

    if already:
        head_text = "✅ 此群已是你的守護群"
        body_text = f"目前已綁定 {count}/{limit} 個守護群,無需重複操作"
        color = GREEN_DARK
    else:
        head_text = "✅ 已完成綁定平安守護助手"
        body_text = f"目前已綁定 {count}/{limit} 個守護群,逾期未簽到與 SOS 提醒會在此群發送"
        color = GREEN_DARK

    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": color,
            "paddingTop": "lg",
            "paddingBottom": "lg",
            "paddingStart": "lg",
            "paddingEnd": "lg",
            "contents": [
                {
                    "type": "text",
                    "text": head_text,
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
                    "text": "接下來可以做:",
                    "size": "md",
                    "color": GRAY_LIGHT,
                    "margin": "md",
                },
                {
                    "type": "text",
                    "text": "• 把「平安守護助手」設為此群管理員(必做)\n• 邀請長輩/家人加入此群\n• 設定每日簽到時間",
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
                    "contents": _footer_buttons(("guide", "admin")),
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
                _guide_step("3", "把平安守護助手邀進群", "從「平安守護助手」聊天室右上「≡」→「邀請」,選這個新群"),
                _guide_step("4", "把平安守護助手設為管理員", "這步必做,點下方「管理員設定」看 6 步驟教學"),
                _guide_step("5", "在群裡打「綁定平安守護助手」", "會回「✅ 已完成綁定平安守護助手」,這樣這個群就會收到逾期未簽到/SOS 通知"),
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
                    "text": "⚙️ 設定「平安守護助手」為管理員",
                    "color": "#FFFFFF",
                    "size": "xxl",
                    "weight": "bold",
                    "align": "center",
                },
                {
                    "type": "text",
                    "text": "LINE 規定「平安守護助手」無法自動設自己為管理員,需用戶手動操作",
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
                _admin_step("2", "進入成員列表", "選「成員」,找到「平安守護助手」"),
                _admin_step("3", "長按「平安守護助手」名稱", "在「平安守護助手」名稱上長按,跳出選單"),
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
                        "text": "只有你能解綁、設定與重新邀請「平安守護助手」,其他成員只能簽到與查看狀態",
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


def welcome_flex():
    """2026-07-21 patch 17: 使用者加 Bot 為好友時的歡迎詞(私訊 context)。

    3 大功能區塊 + CTA 按鈕。
    """
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
                    "text": "🎉 歡迎加入",
                    "color": "#FFFFFF",
                    "size": "lg",
                    "align": "center",
                },
                {
                    "type": "text",
                    "text": "📍 今天還在嗎",
                    "color": "#FFFFFF",
                    "size": "xxl",
                    "weight": "bold",
                    "align": "center",
                    "margin": "sm",
                },
                {
                    "type": "text",
                    "text": "🛡️ 平安守護助手",
                    "color": "#FFFFFF",
                    "size": "md",
                    "align": "center",
                    "margin": "sm",
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
                # 品牌一句話
                {
                    "type": "text",
                    "text": "專門守護平安的 LINE 助手,逾期未簽到/SOS自動通知緊急聯絡人",
                    "size": "md",
                    "color": GRAY,
                    "wrap": True,
                    "align": "center",
                    "margin": "md",
                },
                # 功能 1: 每日簽到
                {
                    "type": "box",
                    "layout": "horizontal",
                    "spacing": "md",
                    "backgroundColor": "#E8F8EE",
                    "cornerRadius": "md",
                    "paddingAll": "md",
                    "contents": [
                        {
                            "type": "text",
                            "text": "📅",
                            "size": "xxl",
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
                                    "text": "每日簽到",
                                    "size": "lg",
                                    "weight": "bold",
                                    "color": GREEN_DARK,
                                },
                                {
                                    "type": "text",
                                    "text": "在私訊群推播報平安，3秒完成，讓守護人放心",
                                    "size": "md",
                                    "color": GRAY,
                                    "wrap": True,
                                },
                            ],
                        },
                    ],
                },
                # 功能 2: 守護人
                {
                    "type": "box",
                    "layout": "horizontal",
                    "spacing": "md",
                    "backgroundColor": "#E8F8EE",
                    "cornerRadius": "md",
                    "paddingAll": "md",
                    "contents": [
                        {
                            "type": "text",
                            "text": "👨‍👩‍👧",
                            "size": "xxl",
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
                                    "text": "守護人",
                                    "size": "lg",
                                    "weight": "bold",
                                    "color": GREEN_DARK,
                                },
                                {
                                    "type": "text",
                                    "text": "把家人/朋友加為緊急聯絡人,出事時 LINE+SMS簡訊通知",
                                    "size": "lg",
                                    "color": GRAY,
                                    "wrap": True,
                                },
                            ],
                        },
                    ],
                },
                # 功能 3: 守護群
                {
                    "type": "box",
                    "layout": "horizontal",
                    "spacing": "md",
                    "backgroundColor": "#E8F8EE",
                    "cornerRadius": "md",
                    "paddingAll": "md",
                    "contents": [
                        {
                            "type": "text",
                            "text": "🛡️",
                            "size": "xxl",
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
                                    "text": "守護群(799 訂戶限定)",
                                    "size": "lg",
                                    "weight": "bold",
                                    "color": GREEN_DARK,
                                },
                                {
                                    "type": "text",
                                    "text": "開一個 LINE 群,把 Bot 邀進去當管理員,逾期未簽到 / SOS 在群裡通知所有守護人",
                                    "size": "md",
                                    "color": GRAY,
                                    "wrap": True,
                                },
                            ],
                        },
                    ],
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
                {
                    "type": "button",
                    "action": {
                        "type": "message",
                        "label": "查看方案",
                        "text": "查看方案",
                    },
                    "style": "primary",
                    "color": GREEN_DARK,
                    "height": "md",
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "spacing": "sm",
                    "contents": [
                        _postback_button("報平安", "報平安", style="link", color=GREEN_DARK),
                        _postback_button("綁定守護人", "綁定守護人", style="link", color=GRAY),
                    ],
                },
            ],
        },
    }
