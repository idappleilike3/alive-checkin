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

    def test_trial_and_both_beta_plans_share_the_same_waiting_step(self):
        plan_cases = (
            ("trial", "", "trial"),
            ("beta_399", "B399", "paid_399"),
            ("beta_799", "B799", "paid_799"),
        )
        for label, cohort, plan in plan_cases:
            with self.subTest(plan=label):
                state = app_module.load_state(self.data_file)
                profile = state["users"]["U-owner"]
                profile["onboarding_reminder_configured"] = True
                profile["beta_cohort"] = cohort
                profile["plan"] = plan
                profile["contacts"] = []
                state["guardian_invites"] = [{
                    "inviter_line_user_id": "U-owner",
                    "status": "pending",
                }]
                app_module.save_state(self.data_file, state)

                payload, status = app_module.onboarding_status_payload(
                    self.data_file, "U-owner"
                )

                self.assertEqual(status, 200)
                self.assertEqual(payload["current_step"], 5)
                self.assertTrue(payload["completed_steps"]["guardian_invite_sent"])
                self.assertFalse(payload["completed_steps"]["guardian_bound"])
                self.assertFalse(payload["home_ready"])

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

    def test_partially_saved_guardian_data_is_returned_for_form_recovery(self):
        state = app_module.load_state(self.data_file)
        profile = state["users"]["U-owner"]
        profile["contacts"] = [{
            "id": "guardian-1",
            "name": "柔柔",
            "relationship": "女兒",
            "phone": "0912345678",
            "email": "guardian@example.com",
            "contact_role": "guardian",
        }]
        profile["location"] = {"city": "台北市", "district": "中山區"}
        app_module.save_state(self.data_file, state)

        payload, status = app_module.onboarding_status_payload(
            self.data_file, "U-owner"
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["onboarding_draft"], {
            "guardian": {
                "name": "柔柔",
                "relationship": "女兒",
                "phone": "0912345678",
                "email": "guardian@example.com",
            },
            "location": {"city": "台北市", "district": "中山區"},
        })


if __name__ == "__main__":
    unittest.main()
