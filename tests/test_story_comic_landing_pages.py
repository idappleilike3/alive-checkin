from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_beta_pages_use_story_comic_and_keep_plan_specific_content():
    html = (ROOT / "beta-register.html").read_text(encoding="utf-8")
    assert "/assets/daily-peace-story-comic.png" in html
    assert 'class="story-comic"' in html
    assert "399 安心版｜21 天封測" in html
    assert "799 守護版｜21 天封測" in html
    assert "beta_cohort=${cohort}" in html
    assert 'id="addOfficialLine"' in html
    assert 'href="https://line.me/R/ti/p/%40042kwqib"' in html
    assert 'id="continueRegistration"' in html
    assert "第一步：先加入「每日平安」官方 LINE" in html
    assert "第二步：回到這裡，用 LINE 登入並開始設定" in html


def test_general_14_day_onboarding_uses_same_story_comic():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert 'class="onboarding-story-comic"' in html
    assert 'src="assets/daily-peace-story-comic.png"' in html
    assert "女兒收到通知，知道媽媽平安，就能放心" in html
    assert "先加入「每日平安」官方帳號好友" in html
    assert "步驟 2／4　一鍵分享邀請守護人" in html
    assert "步驟 3／4　填寫守護人資料" in html
    assert "步驟 4／4　私訊預警通知提醒設定" in html


def test_trial_and_beta_follow_the_same_registration_order():
    beta = (ROOT / "beta-register.html").read_text(encoding="utf-8")
    member = (ROOT / "index.html").read_text(encoding="utf-8")

    expected_steps = [
        "加入「每日平安」官方",
        "LINE 登入",
        "核心守護人",
        "填寫",
    ]
    for step in expected_steps:
        assert step in beta
        assert step in member


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


def test_guardian_acceptance_cannot_activate_a_trial():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "mutual_core: false" in html
    assert "activate_trial: false" in html
    assert 'const trialAfterGuardian = getAppParam("trial_after_guardian") === "1";' not in html
    assert "activate_trial: trialAfterGuardian" not in html
    assert "activate_own_trial: true" in html
    assert "同時互相設為核心守護人" not in html
