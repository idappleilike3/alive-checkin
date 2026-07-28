from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_onboarding_registers_the_logged_in_member_and_starts_trial():
    html = (ROOT / "liff" / "onboarding.html").read_text(encoding="utf-8")

    assert 'fetch(`${API_BASE}/api/line/register`' in html
    assert "display_name: state.displayName" in html
    assert "picture_url: state.pictureUrl" in html
    assert "state.trialDaysLeft = Number(registration.trial_days_left)" in html


def test_onboarding_shows_trial_activation_immediately_after_login():
    html = (ROOT / "liff" / "onboarding.html").read_text(encoding="utf-8")

    assert 'id="trialActivationNotice"' in html
    assert "14 天免費體驗已啟用" in html
    assert "體驗剩 ${state.trialDaysLeft} 天" in html


def test_onboarding_share_keeps_the_member_identity():
    html = (ROOT / "liff" / "onboarding.html").read_text(encoding="utf-8")

    assert 'inviter_id: state.lineUserId' in html
    assert 'inviter_name: state.displayName' in html


def test_share_picker_sends_the_story_and_binding_page_to_the_friend():
    html = (ROOT / "liff" / "share-invite.html").read_text(encoding="utf-8")

    assert 'const inviteUrl = new URL("/invite", appPublicOrigin())' in html
    assert 'inviteUrl.searchParams.set("invite_from", safeId)' in html
    assert 'inviteUrl.searchParams.set("invite_token", inviteToken)' in html
    assert 'inviteUrl.searchParams.set("inviter_name", inviterName)' in html
    assert "liff.shareTargetPicker" in html
    assert "bindUrl = inviteUrl.toString()" in html
    assert "`https://line.me/R/app/${LIFF_ID}?invite_from=" not in html


def test_every_member_share_entry_uses_the_same_picker_page():
    onboarding = (ROOT / "liff" / "onboarding.html").read_text(encoding="utf-8")
    member = (ROOT / "liff" / "member.html").read_text(encoding="utf-8")
    home = (ROOT / "index.html").read_text(encoding="utf-8")

    assert "/liff/share-invite.html?" in onboarding
    assert "/liff/share-invite.html?" in member
    assert "/liff/share-invite.html?" in home


def test_trial_and_beta_pages_offer_a_direct_member_guardian_share_action():
    trial = (ROOT / "trial-14.html").read_text(encoding="utf-8")
    beta = (ROOT / "beta-register.html").read_text(encoding="utf-8")
    direct_liff_share = (
        "https://liff.line.me/2010848330-UAiqPPYD?open=share-invite"
    )

    for html in (trial, beta):
        assert direct_liff_share in html
        assert "LINE 登入後，一鍵分享邀請核心守護人" in html
def test_guardian_share_page_has_a_desktop_fallback_after_line_login():
    html = (ROOT / "liff" / "share-invite.html").read_text(encoding="utf-8")

    assert 'id="desktopShare"' in html
    assert 'id="desktopLineShare"' in html
    assert 'id="copyInviteLink"' in html
    assert 'id="inviteQrCode"' in html
    assert "電腦版分享" in html
    assert "buildInvitePayload" in html
    assert "renderDesktopFallback" in html
    assert "https://line.me/R/msg/text/?" in html
    assert "navigator.clipboard.writeText" in html


def test_beta_page_explains_that_the_full_21_day_flow_works_on_computers():
    html = (ROOT / "beta-register.html").read_text(encoding="utf-8")

    assert "電腦版也能完成 21 天封測" in html
    assert "開啟 LINE 分享、複製專屬連結或掃描 QR Code" in html


def test_home_and_member_show_explicit_completed_guardian_binding_status():
    home = (ROOT / "index.html").read_text(encoding="utf-8")
    member = (ROOT / "liff" / "member.html").read_text(encoding="utf-8")

    assert "✓ 已完成綁定守護人" in home
    assert "✓ 已完成綁定守護人" in member
