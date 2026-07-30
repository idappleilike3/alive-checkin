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

    assert 'id="startShare"' in html
    assert "立即選擇 LINE 好友分享" in html
    assert "不會先跳到每日平安首頁" in html
    assert "liff.getFriendship" not in html
    assert "window.location.href = buildDirectLiffShareUrl()" in html
    assert "await openShare();" in html
    assert 'const inviteUrl = new URL("/invite", appPublicOrigin())' in html
    assert 'inviteUrl.searchParams.set("invite_from", safeId)' in html
    assert 'inviteUrl.searchParams.set("invite_token", inviteToken)' in html
    assert 'inviteUrl.searchParams.set("inviter_name", inviterName)' in html
    assert "liff.shareTargetPicker" in html
    assert "bindUrl = inviteUrl.toString()" in html
    assert "填寫姓名、關係與手機" in html
    assert "確認同意後才完成綁定" in html
    assert "`https://line.me/R/app/${LIFF_ID}?invite_from=" not in html


def test_share_page_auto_opens_picker_in_line_without_showing_member_home():
    html = (ROOT / "liff" / "share-invite.html").read_text(encoding="utf-8")

    initialized = html.split("async function initializeLiff()", 1)[1]
    initialized = initialized.split('window.addEventListener("pageshow"', 1)[0]
    assert "if (isInsideLine() && !shareAttempted)" in initialized
    assert "await openShare();" in initialized
    assert "buildDirectLiffShareUrl" in html


def test_share_page_prepares_the_invite_before_waiting_for_profile():
    html = (ROOT / "liff" / "share-invite.html").read_text(encoding="utf-8")

    initialized = html.split("async function initializeLiff()", 1)[1]
    initialized = initialized.split('window.addEventListener("pageshow"', 1)[0]
    assert "liff.getDecodedIDToken()" in initialized
    assert "primeGuardianInvite();" in initialized
    assert initialized.index("primeGuardianInvite();") < initialized.index("liff.getProfile()")


def test_invitee_page_shows_the_optional_14_day_199_trial():
    html = (ROOT / "invite.html").read_text(encoding="utf-8")

    assert "14 天免費體驗｜199 活著版" in html
    assert "2 位核心守護人" in html
    assert "4 位緊急聯絡人" in html
    assert "每日 1 次 LINE 預警" in html
    assert "15 分鐘安全守護" in html
    assert "不用刷卡、不會自動扣款" in html


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
