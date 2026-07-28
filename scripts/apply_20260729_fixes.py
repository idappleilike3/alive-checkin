from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_TAG = '<script src="/assets/ux-fixes-20260729.js"></script>'


def inject_script(path: str) -> None:
    file = ROOT / path
    text = file.read_text(encoding="utf-8")
    if SCRIPT_TAG not in text:
        text = text.replace("</body>", f"  {SCRIPT_TAG}\n</body>")
        file.write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    file = ROOT / path
    text = file.read_text(encoding="utf-8")
    if old in text:
        text = text.replace(old, new, 1)
        file.write_text(text, encoding="utf-8")


def patch_trial_limits() -> None:
    file = ROOT / "app.py"
    text = file.read_text(encoding="utf-8")
    pattern = re.compile(r'    "trial": \{\n.*?\n    \},\n    "paid_199": \{', re.S)
    replacement = '''    "trial": {
        # 14 天新會員體驗固定比照 199 活著版（月方案）
        "contact_limit": 6,
        "emergency_contact_limit": 4,
        "friend_location_limit": 0,
        "daily_reminders": 1,
        "channels": ["line"],
        "location_mode": "snapshot_24h",
        "core_guardian_alert_limit": 2,
        "realtime_tracking": False,
        "trajectory_days": 0,
        "offline_sync_days": 0,
        "sos_enabled": True,
        "guardian_group_limit": 0,
        "safety_guard_hours": [0.25],
        "safety_guard_daily_limit": 2,
    },
    "paid_199": {'''
    updated, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise SystemExit("Unable to patch trial plan limits")
    file.write_text(updated, encoding="utf-8")


def patch_onboarding() -> None:
    path = ROOT / "liff/onboarding.html"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "<h2>14 天新會員安心體驗</h2>",
        "<h2>14 天免費體驗｜199 活著版</h2>",
    )
    text = text.replace(
        "每天按一次「我平安」，平常不打擾；真的逾時或需要幫忙時，才通知你指定的核心守護人。體驗不用刷卡，也不會自動扣款。",
        "每天按一次「我平安」。先設定提醒時間，再邀請核心守護人；體驗不用刷卡，也不會自動扣款。",
    )
    text = text.replace(
        "<strong>🎁 14 天免費體驗已啟用</strong>",
        "<strong>🎁 14 天免費體驗已啟用｜199 活著版</strong>",
    )
    path.write_text(text, encoding="utf-8")


def patch_beta_copy() -> None:
    path = ROOT / "beta-register.html"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "不用刷卡、不會自動扣款。完成 LINE 註冊後，系統會自動分入正確組別，並引導你邀請至少一位核心守護人。",
        "不用刷卡、不會自動扣款。先加入 LINE、完成登入，再依頁面完成提醒與核心守護人設定。",
    )
    path.write_text(text, encoding="utf-8")


def bump_deploy_version() -> None:
    path = ROOT / "render.yaml"
    text = path.read_text(encoding="utf-8")
    text = re.sub(r'(DEPLOY_VERSION\n\s+value:)\s*\S+', r'\1 W260729ux1', text, count=1)
    path.write_text(text, encoding="utf-8")


def verify() -> None:
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    onboarding = (ROOT / "liff/onboarding.html").read_text(encoding="utf-8")
    assert '"trial": {' in app
    assert '"core_guardian_alert_limit": 2' in app
    assert '"emergency_contact_limit": 4' in app
    assert "199 活著版" in onboarding
    for path in ["index.html", "liff/onboarding.html", "beta-register.html", "liff/share-invite.html"]:
        assert SCRIPT_TAG in (ROOT / path).read_text(encoding="utf-8"), path


if __name__ == "__main__":
    patch_trial_limits()
    patch_onboarding()
    patch_beta_copy()
    for html in ["index.html", "liff/onboarding.html", "beta-register.html", "liff/share-invite.html"]:
        inject_script(html)
    bump_deploy_version()
    verify()
    print("Applied 2026-07-29 UX and 199 trial fixes")
