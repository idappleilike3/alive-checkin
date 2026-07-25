"""One-time membership trial policy."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import app as app_module


class MembershipTrialPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_file = str(Path(self.tmp.name) / "state.json")
        self.now = datetime(2026, 7, 26, 10, 0, 0)

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_member_receives_exactly_fourteen_days_once(self):
        profile = {"plan": "trial", "trial_bonus_days": 21}

        granted = app_module.ensure_membership_trial(profile, now=self.now)

        self.assertTrue(granted)
        self.assertEqual(profile["plan"], "trial")
        self.assertEqual(profile["membership_source"], "public_trial")
        self.assertEqual(profile["trial_started_at"], "2026-07-26T10:00:00")
        self.assertEqual(profile["trial_end"], "2026-08-09T10:00:00")
        self.assertEqual(app_module.trial_bonus_days(profile), 0)
        self.assertTrue(app_module.membership_access_active(profile, now=self.now))
        self.assertFalse(
            app_module.membership_access_active(
                profile, now=self.now + timedelta(days=14, seconds=1)
            )
        )

        first_end = profile["trial_end"]
        self.assertFalse(
            app_module.ensure_membership_trial(
                profile, now=self.now + timedelta(days=5)
            )
        )
        self.assertEqual(profile["trial_end"], first_end)

    def test_reregister_does_not_restart_public_trial(self):
        first, code = app_module.register_line_user(
            self.data_file, {"line_user_id": "U-once", "display_name": "小美"}
        )
        self.assertEqual(code, 200)
        first_started = first["trial_started_at"]
        first_end = first["trial_end"]

        second, code = app_module.register_line_user(
            self.data_file, {"line_user_id": "U-once", "display_name": "小美"}
        )

        self.assertEqual(code, 200)
        self.assertTrue(second["existing_user"])
        self.assertEqual(second["trial_started_at"], first_started)
        self.assertEqual(second["trial_end"], first_end)
        self.assertEqual(second["trial_total_days"], 14)

    def test_existing_free_member_receives_one_transition_trial(self):
        state = app_module.load_state(self.data_file)
        profile = app_module.get_profile(state, "U-free")
        profile["plan"] = "free"
        profile["payment_status"] = "expired"
        profile.pop("trial_policy_version", None)
        profile.pop("trial_end", None)
        app_module.save_state(self.data_file, state)

        first, code = app_module.register_line_user(
            self.data_file, {"line_user_id": "U-free", "display_name": "舊會員"}
        )

        self.assertEqual(code, 200)
        self.assertEqual(first["plan"], "trial")
        self.assertEqual(first["membership_source"], "transition_trial")
        self.assertTrue(first["trial_end"])
        first_end = first["trial_end"]

        second, code = app_module.register_line_user(
            self.data_file, {"line_user_id": "U-free", "display_name": "舊會員"}
        )
        self.assertEqual(code, 200)
        self.assertEqual(second["trial_end"], first_end)
        self.assertEqual(second["membership_source"], "transition_trial")

    def test_guardian_invitations_never_add_trial_days(self):
        app_module.register_line_user(
            self.data_file, {"line_user_id": "U-owner", "display_name": "本人"}
        )
        state = app_module.load_state(self.data_file)
        state["users"]["U-owner"]["plan"] = "paid_399"
        state["users"]["U-owner"]["payment_status"] = "active"
        state["users"]["U-owner"]["paid_until"] = (
            self.now + timedelta(days=30)
        ).isoformat(timespec="seconds")
        app_module.save_state(self.data_file, state)

        for guardian_id in ("U-g1", "U-g2"):
            result, code = app_module.bind_emergency_contact(
                self.data_file,
                {
                    "inviter_line_user_id": "U-owner",
                    "contact_line_user_id": guardian_id,
                    "contact_display_name": guardian_id,
                },
                config={},
            )
            self.assertEqual(code, 200)
            self.assertFalse(result["invite_reward_applied"])
            self.assertEqual(result["trial_bonus_days"], 0)

        state = app_module.load_state(self.data_file)
        self.assertEqual(app_module.trial_bonus_days(state["users"]["U-owner"]), 0)


if __name__ == "__main__":
    unittest.main()
