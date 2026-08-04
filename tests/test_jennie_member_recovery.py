import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import app as app_module


class JennieMemberRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_file = Path(self.temp_dir.name) / "state.json"
        self.line_user_id = "Ua723c8919f544d515422f143d1710b74"
        app_module.save_state(
            self.data_file,
            {
                "users": {
                    self.line_user_id: {
                        **app_module.DEFAULT_PROFILE,
                        "line_user_id": self.line_user_id,
                        "display_name": "Jennie",
                        # Simulate stale values left after reset + re-registration.
                        "plan": "trial",
                        "payment_status": "trial",
                        "membership_source": "beta",
                        "beta_cohort": "B799",
                        "beta_started_at": "2026-08-04T11:16:00",
                        "beta_ends_at": "2026-08-25T11:16:00",
                        "beta_reset_pending": False,
                        "onboarding_reminder_configured": True,
                        "is_onboarding_completed": False,
                        "interaction_state": {"completed_steps": []},
                        "contacts": [{
                            "id": "guardian-bound",
                            "name": "守護人",
                            "contact_role": "guardian",
                            "line_user_id": "U-guardian",
                            "binding_status": "accepted",
                            "recipient_consent": True,
                        }],
                    }
                }
            },
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_admin_member_list_repairs_b799_and_shows_five_of_five(self):
        summary = app_module.admin_summary(
            self.data_file,
            now=datetime.fromisoformat("2026-08-05T12:00:00"),
        )

        member = next(
            row for row in summary["users"]
            if row["line_user_id"] == self.line_user_id
        )
        self.assertEqual(member["plan"], "paid_799_year")
        self.assertEqual(member["payment_status"], "beta")
        self.assertEqual(member["membership_source"], "beta")
        self.assertEqual(member["beta_cohort"], "B799")
        self.assertEqual(member["onboarding_progress"]["current_step"], 5)
        self.assertTrue(
            all(member["onboarding_progress"]["completed_steps"].values())
        )
        self.assertTrue(member["is_onboarding_completed"])

        saved = app_module.load_state(self.data_file)["users"][self.line_user_id]
        self.assertEqual(saved["plan"], "paid_799_year")
        self.assertEqual(saved["payment_status"], "beta")
        self.assertTrue(saved["is_onboarding_completed"])
        self.assertTrue(saved["interaction_state"]["onboarding_completed"])

    def test_member_status_uses_bound_guardian_as_authoritative_completion(self):
        profile = app_module.load_state(self.data_file)["users"][self.line_user_id]

        status = app_module.build_status(profile)

        self.assertTrue(status["home_ready"])
        self.assertTrue(status["is_onboarding_completed"])


if __name__ == "__main__":
    unittest.main()
