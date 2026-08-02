from pathlib import Path
import json
import unittest

import app as alive_app
import guardian_group_flex


ROOT = Path(__file__).resolve().parents[1]


class TrialGuardianCopyAndMemberGateTests(unittest.TestCase):
    def test_member_trial_share_waits_for_completed_guardian_binding(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="memberTrialShareSection"', html)
        self.assertIn('id="memberTrialShareTitle"', html)
        self.assertIn('id="memberTrialShareHelp"', html)
        self.assertIn("const canShareTrial = Boolean(status.is_onboarding_completed) && boundCount > 0;", html)
        self.assertIn('memberShareTrialBtn.hidden = !canShareTrial', html)
        self.assertIn('memberCompleteSetupBtn.hidden = canShareTrial', html)
        self.assertIn("繼續完成我的體驗設定", html)

    def test_member_status_includes_authoritative_setup_progress(self):
        profile = {
            "line_user_id": "U-owner",
            "display_name": "測試會員",
            "is_onboarding_completed": False,
            "onboarding_reminder_configured": True,
            "contacts": [],
        }

        status = alive_app.build_status(profile, {"users": {"U-owner": profile}})

        self.assertFalse(status["is_onboarding_completed"])
        self.assertTrue(status["onboarding_reminder_configured"])

    def test_binding_direction_copy_is_consistent_on_required_pages(self):
        required_copy = "綁定是單向的；若要互相守護，雙方需要各邀請一次。"
        for filename in ("trial-14.html", "beta-register.html", "invite.html", "faq.html"):
            with self.subTest(filename=filename):
                html = (ROOT / filename).read_text(encoding="utf-8")
                self.assertIn(required_copy, html)

    def test_trial_and_beta_pages_put_profile_before_guardian_invitation(self):
        for filename in ("trial-14.html", "beta-register.html"):
            with self.subTest(filename=filename):
                html = (ROOT / filename).read_text(encoding="utf-8")
                profile_position = html.index("填寫自己的姓名與基本資料")
                guardian_position = html.index("邀請我的核心守護人")
                self.assertLess(profile_position, guardian_position)

    def test_welcome_message_starts_the_current_trial_flow(self):
        welcome = json.loads(
            (ROOT / "assets" / "welcome_message.json").read_text(encoding="utf-8")
        )
        serialized = json.dumps(welcome, ensure_ascii=False)

        self.assertIn("① 填寫自己的姓名與基本資料", serialized)
        self.assertIn("② 邀請我的核心守護人", serialized)
        self.assertIn("開始免費體驗 14 天", serialized)
        self.assertIn("open=onboarding", serialized)

        production = json.dumps(
            guardian_group_flex.welcome_flex(), ensure_ascii=False
        )
        self.assertIn("welcome-approved-full-20260802-help-large.png", production)
        self.assertIn("開始 14 天安心體驗", production)
        self.assertNotIn('"footer"', production)

    def test_faq_separates_trial_sharing_from_guardian_invitation(self):
        html = (ROOT / "faq.html").read_text(encoding="utf-8")

        self.assertIn("分享 14 天免費體驗給朋友", html)
        self.assertIn("不會把朋友綁定成你的核心守護人", html)
        self.assertIn("完成自己的資料並成功綁定至少 1 位核心守護人後", html)


if __name__ == "__main__":
    unittest.main()
