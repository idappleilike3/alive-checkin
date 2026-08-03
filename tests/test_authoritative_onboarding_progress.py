import tempfile
import unittest
from pathlib import Path

import app as app_module


ROOT = Path(__file__).resolve().parents[1]
WAITING_COPY = (
    "請等待對方加入每日平安、完成 LINE 登入、填寫姓名與雙方關係，"
    "並確認接受邀請；完成後才算綁定成功。"
)


class AuthoritativeOnboardingProgressTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_file = Path(self.tmp.name) / "data.json"
        state = app_module.load_state(self.data_file)
        state["users"]["U-owner"] = app_module.get_profile(state, "U-owner")
        state["users"]["U-owner"]["display_name"] = "本人"
        app_module.save_state(self.data_file, state)

    def tearDown(self):
        self.tmp.cleanup()

    def test_payload_exposes_four_server_authoritative_steps(self):
        payload, status = app_module.onboarding_status_payload(
            self.data_file, "U-owner"
        )

        self.assertEqual(status, 200)
        self.assertEqual(
            payload["completed_steps"],
            {
                "line_login": True,
                "profile_and_reminder": False,
                "guardian_invite_sent": False,
                "guardian_bound": False,
            },
        )
        self.assertEqual(payload["current_step"], 3)
        self.assertEqual(payload["binding_status"], "waiting_for_invite")

    def test_pending_invite_is_waiting_not_completed(self):
        state = app_module.load_state(self.data_file)
        state["users"]["U-owner"]["onboarding_reminder_configured"] = True
        state["guardian_invites"] = [{
            "inviter_line_user_id": "U-owner",
            "status": "pending",
        }]
        app_module.save_state(self.data_file, state)

        payload, _ = app_module.onboarding_status_payload(
            self.data_file, "U-owner"
        )

        self.assertEqual(payload["completed_steps"]["guardian_invite_sent"], True)
        self.assertEqual(payload["completed_steps"]["guardian_bound"], False)
        self.assertEqual(payload["current_step"], 5)
        self.assertEqual(payload["binding_status"], "waiting_for_guardian")

    def test_four_entry_pages_keep_step_four_waiting_copy(self):
        pages = (
            "liff/onboarding.html",
            "liff/share-invite.html",
            "trial-14.html",
            "beta-register.html",
        )
        for page in pages:
            with self.subTest(page=page):
                text = (ROOT / page).read_text(encoding="utf-8")
                self.assertIn(WAITING_COPY, text)

    def test_onboarding_checks_are_rendered_from_api_completed_steps(self):
        text = (ROOT / "liff/onboarding.html").read_text(encoding="utf-8")
        self.assertIn("data.completed_steps", text)
        self.assertIn("renderProgressSteps", text)
        self.assertIn("showStepReminderOnce", text)
        self.assertNotIn(
            '<div class="gift-check">✅ 3 分享邀請</div>', text
        )


if __name__ == "__main__":
    unittest.main()
