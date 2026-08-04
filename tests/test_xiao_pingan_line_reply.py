from app import line_auto_reply_text, should_create_support_ticket


def test_line_invite_question_gets_invite_answer():
    reply = line_auto_reply_text("我想邀請媽媽當守護人")
    assert "一鍵邀請守護人" in reply
    assert "提醒時間" not in reply


def test_line_unknown_question_does_not_guess():
    reply = line_auto_reply_text("我家的電視為什麼沒有畫面")
    assert "不能確定" in reply
    assert "不會隨便猜" in reply


def test_line_plan_answer_uses_status_data():
    reply = line_auto_reply_text(
        "我的方案是什麼",
        {"membership_label": "399 安心年費", "plan_expires_text": "2027-08-04 到期"},
    )
    assert "399 安心年費" in reply
    assert "2027-08-04 到期" in reply


def test_unknown_question_does_not_silently_create_ticket():
    assert should_create_support_ticket("我家的電視為什麼沒有畫面") is False
    assert should_create_support_ticket("請幫我轉人工客服處理付款問題") is True
