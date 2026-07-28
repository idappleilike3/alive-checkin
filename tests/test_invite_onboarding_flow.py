from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import app as app_module

ROOT = Path(__file__).resolve().parents[1]


class InviteOnboardingFlowTests(unittest.TestCase):
    def test_guardian_only_registration_does_not_start_own_trial(self):
        with TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "state.json"
            result, code = app_module.register_line_user(
                data_file,
                {
                    "line_user_id": "U-B",
                    "display_name": "B",
                    "guardian_only": True,
                },
            )
            self.assertEqual(code, 200)
            state = app_module.load_state(data_file)
            guardian = state["users"]["U-B"]
            self.assertEqual(guardian["free_eligibility_source"], "")
            self.assertIsNone(guardian["trial_started_at"])
            self.assertFalse(app_module.membership_access_active(guardian))
            self.assertTrue(result["guardian_only"])

    def test_guardian_can_explicitly_claim_own_one_time_trial(self):
        with TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "state.json"
            app_module.register_line_user(
                data_file,
                {
                    "line_user_id": "U-B",
                    "display_name": "B",
                    "guardian_only": True,
                },
            )
            result, code = app_module.register_line_user(
                data_file,
                {
                    "line_user_id": "U-B",
                    "display_name": "B",
                    "activate_own_trial": True,
                },
            )
            self.assertEqual(code, 200)
            state = app_module.load_state(data_file)
            guardian = state["users"]["U-B"]
            self.assertEqual(guardian["free_eligibility_source"], "public_trial")
            self.assertTrue(guardian["trial_started_at"])
            self.assertTrue(app_module.membership_access_active(guardian))
            self.assertTrue(result["own_trial_activated"])

    def test_share_page_explains_official_line_and_three_steps(self):
        html = (ROOT / "liff/share-invite.html").read_text(encoding="utf-8")
        self.assertIn("加入「每日平安」官方 LINE", html)
        self.assertIn("https://line.me/R/ti/p/%40042kwqib", html)
        for copy in (
            "1. 選擇 LINE 好友",
            "2. 對方登入並同意",
            "3. 綁定完成後立即生效",
        ):
            self.assertIn(copy, html)

    def test_invitation_survives_line_login_and_reopens_the_profile_form(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('const PENDING_GUARDIAN_INVITE_KEY = "alive_pending_guardian_invite_v1"', html)
        self.assertIn("rememberPendingGuardianInvite", html)
        self.assertIn("restorePendingGuardianInvite", html)
        self.assertIn("clearPendingGuardianInvite", html)
        self.assertIn("showInviteGuardianProfileForm", html)
        self.assertIn("請填寫您的資料，確認後才會完成核心守護綁定", html)

    def test_acceptance_is_one_way_and_reverse_guarding_requires_a_new_invite(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("這次只會由您守護邀請人，不會自動互相綁定", html)
        self.assertIn("我也要報平安｜免費體驗 14 天", html)
        self.assertIn("startMyOwnTrialFromGuardianSuccess", html)
        self.assertIn("activate_own_trial: true", html)
        self.assertIn("guardian_only: Boolean(inviteFrom", html)
        self.assertNotIn("同時互相設為核心守護人", html)
        self.assertNotIn("同意互相成為核心守護人", html)

    def test_public_invite_cannot_bundle_guardian_acceptance_with_a_trial(self):
        invite_html = (ROOT / "invite.html").read_text(encoding="utf-8")
        home_html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("acceptAndTrialCta", invite_html)
        self.assertNotIn("trial_after_guardian", invite_html)
        self.assertIn("接受邀請只會讓你免費接收對方通知", invite_html)
        self.assertNotIn("activate_trial: trialAfterGuardian", home_html)
        self.assertIn("activate_trial: false", home_html)

    def test_trial_home_has_share_and_guardian_status_entry_points(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("一鍵分享邀請核心守護人", html)
        self.assertIn("查看核心守護人綁定狀態", html)
        self.assertIn("等待加入官方 LINE", html)
        self.assertIn("已加入官方 LINE 並完成綁定", html)

    def test_member_center_separates_who_guards_me_from_who_i_guard(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="memberGuardingForList"', html)
        self.assertIn("我正在守護的人", html)
        self.assertIn("守護我的人", html)
        self.assertIn("renderGuardingForRows", html)
        self.assertIn("免費接收對方的報平安、逾時與 SOS 通知", html)

    def test_mutual_core_flag_cannot_skip_the_second_consent(self):
        with TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "state.json"
            first, first_code = app_module.bind_emergency_contact(
                data_file,
                {
                    "inviter_line_user_id": "U-A",
                    "contact_line_user_id": "U-B",
                    "contact_display_name": "B",
                },
                config={},
            )
            self.assertEqual(first_code, 200)
            self.assertFalse(first["reciprocal"])

            second, second_code = app_module.bind_emergency_contact(
                data_file,
                {
                    "inviter_line_user_id": "U-B",
                    "contact_line_user_id": "U-A",
                    "contact_display_name": "A",
                    "mutual_core": True,
                },
                config={},
            )
            self.assertEqual(second_code, 200)
            self.assertFalse(second["mutual_core_applied"])
            self.assertNotIn("互綁完成", second["message"])


if __name__ == "__main__":
    unittest.main()
