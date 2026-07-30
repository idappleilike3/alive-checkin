import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app import admin_update_user_plan, load_state, save_state


class AdminMembershipModeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_file = Path(self.temp_dir.name) / "state.json"
        save_state(
            self.data_file,
            {
                "users": {
                    "U-member": {
                        "line_user_id": "U-member",
                        "display_name": "Jennie",
                        "plan": "trial",
                        "payment_status": "trial",
                        "membership_source": "public_trial",
                        "trial_started_at": "2026-07-20T00:00:00",
                        "trial_end": "2026-08-03T00:00:00",
                        "contacts": [{"name": "媽媽"}],
                        "calendar_notes": {},
                    }
                }
            },
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_admin_can_change_14_day_trial_to_21_day_b799(self):
        result, code = admin_update_user_plan(
            self.data_file,
            {
                "line_user_id": "U-member",
                "plan": "beta_B799",
            },
        )

        self.assertEqual(code, 200)
        self.assertEqual(result["membership_source"], "beta")
        self.assertEqual(result["beta_cohort"], "B799")
        self.assertEqual(result["plan"], "paid_799_year")
        self.assertTrue(result["calendar_notes_enabled"])

        profile = load_state(self.data_file)["users"]["U-member"]
        self.assertEqual(profile["contacts"], [{"name": "媽媽"}])
        self.assertEqual(profile["payment_status"], "beta")
        started = datetime.fromisoformat(profile["beta_started_at"])
        ends = datetime.fromisoformat(profile["beta_ends_at"])
        self.assertEqual((ends - started).days, 21)

    def test_changing_beta_to_formal_plan_clears_beta_membership_state(self):
        admin_update_user_plan(
            self.data_file,
            {"line_user_id": "U-member", "plan": "beta_B799"},
        )

        result, code = admin_update_user_plan(
            self.data_file,
            {"line_user_id": "U-member", "plan": "paid_799_year"},
        )

        self.assertEqual(code, 200)
        self.assertEqual(result["membership_source"], "paid")
        profile = load_state(self.data_file)["users"]["U-member"]
        self.assertEqual(profile.get("beta_cohort"), "")
        self.assertEqual(profile.get("beta_started_at"), "")
        self.assertEqual(profile.get("beta_ends_at"), "")

    def test_formal_plan_is_still_saved_after_reloading_state(self):
        result, code = admin_update_user_plan(
            self.data_file,
            {"line_user_id": "U-member", "plan": "paid_399_year"},
        )

        self.assertEqual(code, 200)
        self.assertEqual(result["plan"], "paid_399_year")
        reloaded = load_state(self.data_file)["users"]["U-member"]
        self.assertEqual(reloaded["plan"], "paid_399_year")
        self.assertEqual(reloaded["payment_status"], "active")
        self.assertEqual(reloaded["membership_source"], "paid")
        self.assertTrue(reloaded["paid_until"])


if __name__ == "__main__":
    unittest.main()
