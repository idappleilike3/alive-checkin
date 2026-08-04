"""Shared, deterministic answers for Xiao Pingan web chat and LINE OA."""

import re


QUESTIONS = {
    "what_is_it": "這是做什麼的？",
    "how_it_works": "如何為我帶來平安？",
    "invite_guardian": "怎麼邀請守護人？",
    "my_plan": "我的方案是什麼？",
    "missing_reminder": "為什麼收不到提醒？",
    "pin_line": "如何把 LINE 置頂？",
    "price_refund": "要花錢嗎？怎麼退？",
    "get_started": "現在就開始",
}

_PATTERNS = {
    "what_is_it": [r"這是(做)?什麼", r"每日平安.*(用途|幹嘛|做什麼)", r"什麼是每日平安"],
    "how_it_works": [r"如何.*(平安|守護)", r"怎麼.*帶來平安", r"運作.*方式", r"使用流程"],
    "invite_guardian": [r"(怎麼|如何|我要).*(邀請|新增|綁定).*(守護人|家人|媽媽|爸爸|朋友)", r"守護人.*(邀請|新增|綁定)"],
    "my_plan": [r"我的.*(方案|資格|會員)", r"(方案|會員).*(哪一種|是什麼|到期|權益)"],
    "missing_reminder": [r"(沒有|沒|收不到|未收到).*(提醒|通知|推播)", r"(提醒|通知|推播).*(沒有|沒來|收不到|失敗)"],
    "pin_line": [r"(LINE|賴).*(置頂|釘選)", r"(置頂|釘選).*(LINE|賴|每日平安)", r"怎麼置頂"],
    "price_refund": [r"(要|需要).*(錢|付費)", r"(價格|費用|多少錢)", r"(退款|退費|怎麼退)"],
    "get_started": [r"現在.*開始", r"(我要|如何|怎麼).*(註冊|加入|體驗)", r"開始.*(註冊|體驗)"],
}


def _normalize(text):
    return re.sub(r"[\s，。！？、,.!?：:；;]+", "", str(text or "").strip()).lower()


def _answer(topic, member):
    if topic == "what_is_it":
        return "每日平安讓你每天用幾秒回報平安；逾時或需要幫忙時，系統會依設定通知你信任的守護人。"
    if topic == "how_it_works":
        return "最簡單的流程是：收到每日提醒 → 點一下「我平安」→ 系統留下紀錄，守護人就能知道你今天平安。"
    if topic == "invite_guardian":
        return "請到會員中心的「核心守護人」，點「一鍵邀請守護人」，用 LINE 分享專屬連結；對方登入並同意後才完成綁定。"
    if topic == "missing_reminder":
        return "請依序檢查：①已加入且沒有封鎖每日平安官方 LINE；②LINE 通知已開啟；③會員中心的每日提醒開關與提醒時間正確；④方案仍有效；⑤LINE 身分已綁定。仍收不到時請聯絡客服協助查看推播紀錄。"
    if topic == "pin_line":
        return "iPhone：在 LINE 聊天列表把「每日平安」向右滑，點圖釘。Android：長按「每日平安」聊天室，選「釘選」或「置頂」。完成後也請確認通知已開啟。"
    if topic == "price_refund":
        return "14 天安心體驗不會自動扣款；付費方案與當期價格會在付款前清楚顯示。若需要退費，請到會員中心提交退款申請，我們會依網站退款政策人工審核，不會用金流處理費名義任意扣款。"
    if topic == "get_started":
        return "可以，請點「現在就開始」進入每日平安；未註冊會帶你完成加入，已登入則會接續真正尚未完成的步驟。"
    if topic == "my_plan":
        member = member or {}
        label = str(member.get("membership_label") or member.get("plan_label") or "").strip()
        expiry = str(member.get("plan_expires_text") or member.get("expires_text") or "").strip()
        if not label:
            return "我目前讀不到你的會員方案，所以不會猜。請先登入每日平安，或到會員中心查看；若仍沒有顯示，請聯絡客服。"
        suffix = f"，{expiry}" if expiry else ""
        return f"你目前的方案是「{label}」{suffix}。完整權益可在會員中心的「我的方案」查看。"
    return "小平安還不能確定你想問哪一項，不會隨便猜答案。請選下面最接近的問題，或聯絡人工客服。"


def answer_xiao_pingan_question(text, member=None):
    """Return one high-confidence answer or a safe fallback.

    Multiple unrelated topic hits are treated as ambiguous instead of choosing
    whichever keyword happens to appear first.
    """
    normalized = _normalize(text)
    matches = []
    for topic, patterns in _PATTERNS.items():
        if any(re.search(pattern, normalized, re.IGNORECASE) for pattern in patterns):
            matches.append(topic)
    if len(matches) != 1:
        suggestions = list(QUESTIONS.values())[:4]
        return {
            "topic": "fallback",
            "answer": _answer("fallback", member),
            "confidence": 0.2 if normalized else 0.0,
            "suggestions": suggestions,
            "needs_member": False,
            "action": "support",
        }
    topic = matches[0]
    return {
        "topic": topic,
        "answer": _answer(topic, member),
        "confidence": 0.95,
        "suggestions": [],
        "needs_member": topic == "my_plan" and not bool((member or {}).get("membership_label") or (member or {}).get("plan_label")),
        "action": "start" if topic == "get_started" else None,
    }
