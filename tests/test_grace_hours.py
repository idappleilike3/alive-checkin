"""Grace hours: member-selectable 24/48/72 with default 48."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import app as app_module


class GraceHoursTests(unittest.TestCase):
    def test_status_uses_supplied_now_and_waits_through_cancel_window(self):
        now = datetime(2099, 1, 2, 12, 0)
        profile = {
            **app_module.DEFAULT_PROFILE,
            "line_user_id": "U-clock",
            "last_check_in": (now - timedelta(hours=48, minutes=14)).isoformat(
                timespec="seconds"
            ),
        }

        prealert = app_module.build_status(profile, now=now)
        self.assertTrue(prealert["is_prealert"])
        self.assertFalse(prealert["is_overdue"])

        profile["last_check_in"] = (
            now - timedelta(hours=48, minutes=16)
        ).isoformat(timespec="seconds")
        overdue = app_module.build_status(profile, now=now)
        self.assertFalse(overdue["is_prealert"])
        self.assertTrue(overdue["is_overdue"])

    def test_normalize_allowed_and_legacy(self):
        self.assertEqual(app_module.normalize_grace_hours(24), 24)
        self.assertEqual(app_module.normalize_grace_hours(48), 48)
        self.assertEqual(app_module.normalize_grace_hours(72), 72)
        self.assertEqual(app_module.normalize_grace_hours(36), 48)
        self.assertEqual(app_module.normalize_grace_hours(None), 48)
        self.assertEqual(app_module.normalize_grace_hours("abc"), 48)
        self.assertEqual(app_module.DEFAULT_GRACE_HOURS, 48)
        self.assertEqual(app_module.DEFAULT_PROFILE["grace_hours"], 48)

    def test_settings_persist_allowed_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_file = str(Path(tmp) / "state.json")
            status = app_module.save_settings_for_profile(
                data_file,
                {
                    "line_user_id": "U-grace",
                    "grace_hours": 24,
                    "reminder_time": "12:00",
                },
            )
            self.assertEqual(status["grace_hours"], 24)
            self.assertEqual(status["allowed_grace_hours"], [24, 48, 72])

            status = app_module.save_settings_for_profile(
                data_file,
                {
                    "line_user_id": "U-grace",
                    "grace_hours": 36,
                    "reminder_time": "12:00",
                },
            )
            self.assertEqual(status["grace_hours"], 48)

            status = app_module.save_settings_for_profile(
                data_file,
                {
                    "line_user_id": "U-grace",
                    "grace_hours": 72,
                    "reminder_time": "12:00",
                },
            )
            self.assertEqual(status["grace_hours"], 72)

    def test_bind_success_notices_both_parties(self):
        inviter = {"display_name": "阿明", "plan": "trial", "trial_started_at": None}
        contacts = [
            {
                "line_id": "U-g",
                "binding_status": "accepted",
                "is_primary": True,
            }
        ]
        inviter_notice, guardian_notice = app_module.build_bind_success_notices(
            inviter, contacts, "U-inviter", "小美", invite_reward_applied=False
        )
        self.assertIn("綁定成功", inviter_notice)
        self.assertIn("小美", inviter_notice)
        self.assertIn("逾時未報平安", inviter_notice)
        self.assertIn("SOS", inviter_notice)
        self.assertIn("綁定成功", guardian_notice)
        self.assertIn("阿明", guardian_notice)
        self.assertIn("24／48／72", guardian_notice)
        self.assertIn("SOS", guardian_notice)


if __name__ == "__main__":
    unittest.main()
