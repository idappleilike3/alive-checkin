from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_trial_settings_and_guardian_share_actions_are_visually_separated():
    html = (ROOT / "liff" / "onboarding.html").read_text(encoding="utf-8")

    assert '.onboarding-action-group' in html
    assert 'gap: 14px' in html
    assert 'id="trialSettingsActions"' in html
    assert 'id="guardianShareActions"' in html
    assert 'id="guardianStatusActions"' in html


def test_trial_actions_explain_that_settings_and_sharing_are_different_steps():
    html = (ROOT / "liff" / "onboarding.html").read_text(encoding="utf-8")

    assert "儲存體驗設定，前往邀請守護人" in html
    assert "選擇 LINE 好友，分享守護邀請" in html
    assert "分享完成後，再回來檢查對方是否接受" in html
