import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class BetaAccountFullResetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_file = Path(self.tmp.name) / "state.json"
        self.uid = "U-beta"
        self.state = {
            **app.DEFAULT_STATE,
            "users": {
                self.uid: {
                    **app.DEFAULT_PROFILE,
                    "line_user_id": self.uid,
                    "display_name": "Jenni",
                    "picture_url": "https://example.test/avatar.jpg",
                    "beta_cohort": "B799",
                    "account_state_version": "old-version",
                    "history": [{"date": "2026-08-01"}],
                    "contacts": [{"line_user_id": "U-guardian"}],
                    "guardian_group_ids": ["C-family"],
                    "location": {"lat": 25.0},
                },
                "U-guardian": {
                    **app.DEFAULT_PROFILE,
                    "line_user_id": "U-guardian",
                    "contacts": [{"line_user_id": self.uid}],
                    "friends": [self.uid],
                    "guarding_for": [self.uid],
                },
            },
            "orders": [{"id": "order-1", "line_user_id": self.uid, "status": "paid"}],
            "admin_audit_logs": [{"action": "existing", "line_user_id": self.uid}],
            "guardian_groups": {"C-family": {"owner_line_user_id": self.uid, "members": [self.uid, "U-guardian"]}},
            "notification_logs": [{"line_user_id": self.uid, "kind": "reminder"}],
            "sos_events": {"s1": {"line_user_id": self.uid}},
            "location_grants": {self.uid: {"line_user_id": self.uid}},
        }
        app.save_state(self.data_file, self.state)

    def tearDown(self):
        self.tmp.cleanup()

    def test_candidate_summary_identifies_person_with_full_uid_plan_and_version(self):
        candidates = app.list_beta_reset_candidates(self.state, {self.uid})
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["cohort"], "B799")
        self.assertEqual(candidates[0]["candidate_id"], self.uid)
        self.assertEqual(candidates[0]["plan"], "799")
        self.assertEqual(candidates[0]["account_state_version"], "old-version")
        self.assertNotIn("masked_line_user_id", candidates[0])

    def test_enrolled_beta_member_is_listed_without_manual_test_whitelist(self):
        candidates = app.list_beta_reset_candidates(self.state, set())

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["candidate_id"], self.uid)
        self.assertEqual(candidates[0]["cohort"], "B799")

    def test_enrolled_beta_member_can_reset_without_manual_test_whitelist(self):
        result, status = app.admin_reset_test_account(
            self.data_file,
            self.uid,
            set(),
            expected_version="old-version",
            actor="admin-1",
        )

        self.assertEqual(status, 200, result)
        self.assertTrue(result["ok"])

    def test_test_account_whitelist_accepts_common_render_formats(self):
        config = {
            "TEST_LINE_USER_IDS": "U-one\nU-two； U-three;U-four, U-five"
        }
        self.assertEqual(
            app._test_line_user_ids(config),
            ["U-one", "U-two", "U-three", "U-four", "U-five"],
        )

    def test_reset_is_atomic_and_preserves_orders_and_existing_audit(self):
        result, status = app.admin_reset_test_account(
            self.data_file,
            self.uid,
            {self.uid},
            expected_version="old-version",
            actor="admin-1",
        )
        self.assertEqual(status, 200, result)
        state = app.load_state(self.data_file)
        profile = state["users"][self.uid]
        self.assertTrue(profile["beta_reset_pending"])
        self.assertEqual(profile["beta_reset_origin_cohort"], "B799")
        self.assertEqual(profile["reminder_times"], [])
        self.assertFalse(profile["daily_checkin_reminder_enabled"])
        self.assertEqual(profile["history"], [])
        self.assertEqual(profile["contacts"], [])
        self.assertEqual(profile["guardian_group_ids"], [])
        self.assertNotEqual(profile["account_state_version"], "old-version")
        self.assertEqual(state["orders"], self.state["orders"])
        self.assertEqual(state["admin_audit_logs"][0], self.state["admin_audit_logs"][0])
        self.assertEqual(state["admin_audit_logs"][-1]["action"], "beta_account_full_reset")
        guardian = state["users"]["U-guardian"]
        self.assertEqual(guardian["contacts"], [])
        self.assertEqual(guardian["friends"], [])
        self.assertNotIn("C-family", state["guardian_groups"])
        self.assertEqual(state["notification_logs"], [])
        self.assertEqual(state["sos_events"], {})
        self.assertEqual(state["location_grants"], {})

    def test_reset_member_registration_does_not_restart_public_trial(self):
        result, status = app.admin_reset_test_account(self.data_file, self.uid, set())
        self.assertEqual(status, 200)
        registered, register_status = app.register_line_user(self.data_file, {
            "line_user_id": self.uid,
            "display_name": "Jennie",
        })
        self.assertEqual(register_status, 200)
        profile = app.load_state(self.data_file)["users"][self.uid]
        self.assertTrue(profile["beta_reset_pending"])
        self.assertFalse(app.membership_access_active(profile))
        self.assertFalse(profile.get("trial_started_at"))
        self.assertFalse(profile.get("trial_end"))

    def test_pending_reset_never_has_active_access_even_with_legacy_trial_dates(self):
        profile = {
            "plan": "trial",
            "payment_status": "trial",
            "trial_started_at": "2026-08-03T00:00:00",
            "trial_end": "2099-08-17T00:00:00",
            "beta_reset_pending": True,
        }
        self.assertFalse(app.membership_access_active(profile))

    def test_version_conflict_changes_nothing(self):
        before = app.load_state(self.data_file)
        result, status = app.admin_reset_test_account(
            self.data_file, self.uid, {self.uid}, expected_version="stale", actor="admin-1"
        )
        self.assertEqual(status, 409)
        self.assertEqual(result["error"], "account_state_version_conflict")
        self.assertEqual(app.load_state(self.data_file), before)

    def test_already_reset_account_is_not_a_candidate(self):
        self.state["users"][self.uid]["beta_reset_pending"] = True
        self.state["users"][self.uid]["beta_cohort"] = ""
        self.assertEqual(app.list_beta_reset_candidates(self.state, {self.uid}), [])

    def test_general_registration_keeps_pending_and_does_not_start_public_trial(self):
        profile = self.state["users"][self.uid]
        profile.update({
            "beta_cohort": "",
            "beta_reset_pending": True,
            "beta_reset_origin_cohort": "B799",
            "trial_started_at": None,
            "trial_end": None,
            "reminder_time": "",
            "reminder_times": [],
            "daily_checkin_reminder_enabled": False,
            "history": [],
        })
        app.save_state(self.data_file, self.state)
        result, status = app.register_line_user(self.data_file, {"line_user_id": self.uid, "display_name": "Jenni"})
        self.assertEqual(status, 200, result)
        saved = app.load_state(self.data_file)["users"][self.uid]
        self.assertTrue(saved["beta_reset_pending"])
        self.assertIsNone(saved["trial_started_at"])
        self.assertEqual(saved["reminder_times"], [])
        self.assertEqual(result["reminder_time"], "")


if __name__ == "__main__":
    unittest.main()
