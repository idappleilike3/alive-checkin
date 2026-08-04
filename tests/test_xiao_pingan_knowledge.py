from assistant_knowledge import answer_xiao_pingan_question


def test_invite_question_does_not_return_reminder_answer():
    result = answer_xiao_pingan_question("我要怎麼邀請媽媽當守護人？")
    assert result["topic"] == "invite_guardian"
    assert "一鍵邀請" in result["answer"]
    assert result["confidence"] >= 0.7


def test_reminder_question_returns_ordered_troubleshooting():
    result = answer_xiao_pingan_question("為什麼今天沒有收到 LINE 提醒？")
    assert result["topic"] == "missing_reminder"
    assert "封鎖" in result["answer"]
    assert "提醒時間" in result["answer"]


def test_plan_question_uses_real_member_data():
    member = {
        "membership_label": "799 家庭守護年費",
        "plan_expires_text": "2027-08-04 到期",
    }
    result = answer_xiao_pingan_question("我的方案是哪一種？", member)
    assert result["topic"] == "my_plan"
    assert "799 家庭守護年費" in result["answer"]
    assert "2027-08-04 到期" in result["answer"]


def test_plan_question_never_guesses_when_member_data_missing():
    result = answer_xiao_pingan_question("我的方案是什麼？")
    assert result["topic"] == "my_plan"
    assert result["needs_member"] is True
    assert "不會猜" in result["answer"]


def test_unknown_question_returns_fallback_and_suggestions():
    result = answer_xiao_pingan_question("明天晚餐要吃什麼？")
    assert result["topic"] == "fallback"
    assert result["confidence"] < 0.7
    assert "不能確定" in result["answer"]
    assert "會員中心" in result["answer"]
    assert "聯絡客服" in result["answer"]
    assert len(result["suggestions"]) >= 2


def test_short_ambiguous_input_does_not_match_by_one_character():
    result = answer_xiao_pingan_question("方案朋友提醒")
    assert result["topic"] == "fallback"
