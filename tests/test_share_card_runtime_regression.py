from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRIAL_SHARE = (ROOT / "liff" / "share-trial.html").read_text(encoding="utf-8")
INVITE_SHARE = (ROOT / "liff" / "share-invite.html").read_text(encoding="utf-8")


def test_trial_share_does_not_reference_removed_preview_element():
    assert 'getElementById("cardTitle")' not in TRIAL_SHARE
    assert "cardTitle.textContent" not in TRIAL_SHARE


def test_both_share_flows_keep_flex_cards_and_target_picker():
    for html in (TRIAL_SHARE, INVITE_SHARE):
        assert '\"type\": \"flex\"' in html
        assert "liff.shareTargetPicker" in html


def test_share_card_targets_stay_separate():
    assert 'const trialUrl = `${location.origin}/trial-14.html`' in TRIAL_SHARE
    assert 'new URL("/invite", appPublicOrigin())' in INVITE_SHARE
    assert 'inviteUrl.searchParams.set("invite_token", inviteToken)' in INVITE_SHARE
