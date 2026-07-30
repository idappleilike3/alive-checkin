from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_beta_pages_use_story_comic_and_keep_plan_specific_content():
    html = (ROOT / "beta-register.html").read_text(encoding="utf-8")
    assert "/assets/daily-peace-story-comic.png" in html
    assert 'class="story-comic"' in html
    assert "21天安心守護體驗" in html
    assert "399 年費安心版｜21 天封測" not in html
    assert "799 年費守護版｜21 天封測" not in html
    assert "beta_cohort=${cohort}" in html
    assert 'id="addOfficialLine"' in html
    assert 'href="https://line.me/R/ti/p/%40042kwqib"' in html
    assert 'id="continueRegistration"' in html
    assert "點我加入官方LINE" in html
    assert "我已加入官方LINE，繼續登入設定" in html


def test_trial_and_beta_pages_keep_only_join_and_login_actions():
    trial = (ROOT / "trial-14.html").read_text(encoding="utf-8")
    beta = (ROOT / "beta-register.html").read_text(encoding="utf-8")

    assert trial.count('class="cta') == 2
    assert "LINE 登入後，一鍵分享邀請核心守護人" not in trial
    assert "一鍵分享這個頁面給 LINE 好友" not in trial

    assert beta.count('class="cta') == 2  # two setup actions; pricing is a text link
    assert "LINE 登入後，一鍵分享邀請核心守護人" not in beta
    assert "一鍵分享這個頁面給 LINE 好友" not in beta


def test_beta_page_hides_prices_and_ends_with_faq_then_pricing_link():
    html = (ROOT / "beta-register.html").read_text(encoding="utf-8")

    assert "NT$199" not in html
    assert "NT$399" not in html
    assert "NT$799" not in html
    assert 'class="plan-card"' not in html
    assert 'class="faq"' in html
    assert "21 天體驗會收費嗎？" in html
    assert "體驗結束會自動扣款嗎？" in html
    assert 'class="pricing-link"' in html
    assert 'href="/liff/pricing.html"' in html
    assert html.index('class="faq"') < html.index('class="pricing-link"')


def test_beta_page_uses_four_step_line_first_flow():
    html = (ROOT / "beta-register.html").read_text(encoding="utf-8")

    expected = [
        "① 加入「每日平安」官方LINE",
        "② 回到此頁，用LINE登入",
        "③ 一鍵邀請守護人",
        "④ 設定提醒時間，開始安心練習",
    ]
    positions = [html.index(item) for item in expected]
    assert positions == sorted(positions)
    assert "加入後，才能收到報平安通知與守護人綁定邀請" in html
    assert "分享連結，對方接受後即完成綁定" in html


def test_general_14_day_onboarding_uses_same_story_comic():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert 'class="onboarding-story-comic"' in html
    assert 'src="assets/daily-peace-story-comic.png"' in html
    assert "女兒收到通知，知道媽媽平安，就能放心" in html
    assert "先加入「每日平安」官方帳號好友" in html
    assert "步驟 2／4　填寫資料與提醒設定" in html
    assert "步驟 3／4　一鍵分享邀請守護人" in html
    assert "緊急聯絡候補（選填）" in html


def test_trial_and_beta_follow_the_same_registration_order():
    beta = (ROOT / "beta-register.html").read_text(encoding="utf-8")
    member = (ROOT / "index.html").read_text(encoding="utf-8")

    for beta_step, member_step in [
        ("官方 LINE", "官方 LINE"),
        ("LINE登入", "LINE 登入"),
        ("守護人", "守護人"),
        ("提醒時間", "提醒時間"),
    ]:
        assert beta_step in beta
        assert member_step in member


def test_welcome_card_names_one_click_guardian_invitation_as_a_setup_step():
    flex = (ROOT / "guardian_group_flex.py").read_text(encoding="utf-8")
    assert "開始使用前，只要完成三個步驟" in flex
    assert "① 一鍵邀請 1 位核心守護人" in flex
    assert "② 填寫守護人資料" in flex
    assert "③ 設定每日提醒時間" in flex


def test_story_comic_asset_exists():
    image = ROOT / "assets" / "daily-peace-story-comic.png"
    assert image.exists()
    assert image.stat().st_size > 100_000


def test_guardian_invitation_uses_story_comic_before_acceptance():
    html = (ROOT / "invite.html").read_text(encoding="utf-8")
    assert 'class="invite-story-comic"' in html
    assert 'src="assets/daily-peace-story-comic.png"' in html
    assert "成為核心守護人後，重要時刻才會收到通知" in html
    assert 'src="assets/daily-peace-logo.png"' in html
    assert 'id="acceptGuardianCta"' in html
    assert "接受成為核心守護人" in html
    assert 'id="acceptAndTrialCta"' not in html
    assert "完成守護資料後，我也要申請 14 天體驗" not in html
    assert 'q.set("trial_after_guardian", "1")' not in html
    assert "接受邀請只會讓你免費接收對方通知" in html


def test_guardian_invitation_explains_the_complete_join_and_binding_flow():
    html = (ROOT / "invite.html").read_text(encoding="utf-8")
    assert 'id="joinOfficialLineCta"' in html
    assert 'href="https://line.me/R/ti/p/%40042kwqib"' in html
    assert "先加入每日平安官方 LINE" in html
    assert "使用 LINE 一鍵登入" in html
    assert "填寫姓名、關係、手機" in html
    assert "確認綁定核心守護人" in html
    assert 'id="guardianBindingPreview"' in html
    assert "您的姓名（必填）" in html
    assert "您與邀請人的關係（必填）" in html
    assert "您的手機號碼（必填）" in html
    assert "登入後會回到這個邀請流程" in html


def test_guardian_invitation_names_the_inviter_when_provided():
    html = (ROOT / "invite.html").read_text(encoding="utf-8")
    assert 'id="inviterName"' in html
    assert 'params.get("inviter_name")' in html
    assert 'inviterNameEl.textContent = inviterName' in html


def test_guardian_invitation_preserves_identity_in_line_login():
    html = (ROOT / "invite.html").read_text(encoding="utf-8")
    assert 'q.set("inviter_name", inviterName)' in html
    assert 'q.set("return_to", "guardian_binding")' in html


def test_member_shares_the_story_landing_not_a_bare_liff_bind_url():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "const landingUrl = buildInviteLandingUrl" in html
    assert "invite_from: safeId" in html
    assert "inviter_name: lineDisplayName" in html
    assert "const bindUrl = landingUrl;" in html


def test_guardian_acceptance_keeps_trial_optional_and_reverse_invite_separate():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "mutual_core: false" in html
    assert "activate_trial: false" in html
    assert 'const trialAfterGuardian = getAppParam("trial_after_guardian") === "1";' not in html
    assert "activate_trial: trialAfterGuardian" not in html
    assert "activate_own_trial: true" in html
    assert "activateOwnTrialAfterGuardianBind" in html
    assert "guardianBindStartTrialBtn" in html
    assert "若希望原邀請人也守護您，仍須另外發送一次邀請" in html
    bind_flow = html.split("async function completeGuardianBindOnce", 1)[1].split(
        "function resetInviteAcceptPromptUi", 1
    )[0]
    assert "activateOwnTrialAfterGuardianBind" not in bind_flow
    assert "方案沒有被改成 14 天體驗" in html
    assert "同時互相設為核心守護人" not in html
