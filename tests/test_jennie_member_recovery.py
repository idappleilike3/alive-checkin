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

    def test_app_startup_persists_b799_completion_without_opening_admin(self):
        app_module.create_app({
            "TESTING": True,
            "DATA_FILE": self.data_file,
            "ADMIN_SESSION_SECRET": "test-secret",
        })

        saved = app_module.load_state(self.data_file)["users"][self.line_user_id]
        self.assertEqual(saved["plan"], "paid_799_year")
        self.assertEqual(saved["payment_status"], "beta")
        self.assertFalse(saved["beta_reset_pending"])
        self.assertTrue(saved["is_onboarding_completed"])
        self.assertTrue(saved["interaction_state"]["onboarding_completed"])
        self.assertEqual(saved["interaction_state"]["guardian_prompt_status"], "accepted")

    def test_restore_missing_beta_member_from_tombstone(self):
        guardian_id = "Ufd7bebdfa2382aeaaf490dd204c2c77a"
        app_module.save_state(
            self.data_file,
            {
                "users": {
                    guardian_id: {
                        **app_module.DEFAULT_PROFILE,
                        "line_user_id": guardian_id,
                        "display_name": "❤寶寶❤",
                        "contacts": [{
                            "id": "jennie-guards-baby",
                            "name": "jennie",
                            "contact_role": "guardian",
                            "line_user_id": self.line_user_id,
                            "binding_status": "accepted",
                            "recipient_consent": True,
                        }],
                    }
                },
                "test_account_tombstones": {
                    self.line_user_id: {
                        "line_user_id": self.line_user_id,
                        "display_name": "jennie",
                        "last_beta_cohort": "B799",
                        "reset_at": "2026-08-04T11:16:00",
                        "status": "beta_reset_pending",
                    }
                },
            },
        )

        result, code = app_module.admin_restore_beta_member_from_tombstone(
            self.data_file,
            self.line_user_id,
            guardian_id,
            now=datetime.fromisoformat("2026-08-05T12:00:00"),
        )

        self.assertEqual(code, 200)
        self.assertTrue(result["ok"])
        saved = app_module.load_state(self.data_file)
        member = saved["users"][self.line_user_id]
        self.assertEqual(member["plan"], "paid_799_year")
        self.assertEqual(member["membership_source"], "beta")
        self.assertEqual(member["beta_cohort"], "B799")
        self.assertEqual(member["beta_started_at"], "2026-08-04T11:16:00")
        self.assertEqual(member["beta_ends_at"], "2026-08-25T11:16:00")
        self.assertTrue(member["is_onboarding_completed"])
        self.assertTrue(app_module.profile_has_bound_line_guardian(member))
        self.assertEqual(member["contacts"][0]["line_user_id"], guardian_id)
        self.assertNotIn(self.line_user_id, saved["test_account_tombstones"])

    def test_stale_retired_uid_setting_does_not_delete_restored_beta_member(self):
        state = app_module.load_state(self.data_file)
        member = state["users"][self.line_user_id]
        member["plan"] = "paid_799_year"
        member["payment_status"] = "beta"
        member["membership_source"] = "beta"
        member["beta_cohort"] = "B799"
        app_module.save_state(self.data_file, state)

        result = app_module.remove_retired_push_uids(
            self.data_file,
            {"RETIRED_LINE_USER_IDS": self.line_user_id},
        )

        self.assertEqual(result["removed"], 0)
        self.assertIn(
            self.line_user_id,
            app_module.load_state(self.data_file)["users"],
        )


if __name__ == "__main__":
    unittest.main()
