"""Missed-check-in wait: member-selectable 15/30/60 minutes."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import app as app_module


class GraceHoursTests(unittest.TestCase):
    def test_overdue_clock_waits_48_hours_then_15_minutes(self):
        now = datetime(2099, 1, 3, 12, 15)
        profile = {
            **app_module.DEFAULT_PROFILE,
            "line_user_id": "U-clock",
            "last_check_in": datetime(2099, 1, 1, 11, 0).isoformat(
                timespec="seconds"
            ),
            "grace_hours": 48,
            "overdue_wait_minutes": 15,
            "active_overdue_event": {
                "date": "2099-01-01",
                "started_at": datetime(2099, 1, 1, 12, 0).isoformat(
                    timespec="seconds"
                ),
                "guardian_stage": 0,
            },
        }

        before_grace = app_module.build_status(
            profile, now=datetime(2099, 1, 3, 11, 59)
        )
        after_48_hours = app_module.build_status(
            profile, now=datetime(2099, 1, 3, 12, 0)
        )
        after_48_hours_and_15_minutes = app_module.build_status(profile, now=now)

        self.assertFalse(before_grace["is_prealert"])
        self.assertFalse(before_grace["is_overdue"])
        self.assertTrue(after_48_hours["is_prealert"])
        self.assertFalse(after_48_hours["is_overdue"])
        self.assertFalse(after_48_hours_and_15_minutes["is_prealert"])
        self.assertTrue(after_48_hours_and_15_minutes["is_overdue"])

    def test_status_applies_48_hour_grace_before_15_minute_default_wait(self):
        now = datetime(2099, 1, 2, 12, 0)
        profile = {
            **app_module.DEFAULT_PROFILE,
            "line_user_id": "U-clock",
            "last_check_in": (now - timedelta(days=1)).isoformat(timespec="seconds"),
            "active_overdue_event": {
                "date": "2099-01-02",
                "started_at": (
                    now - timedelta(hours=48, minutes=14)
                ).isoformat(timespec="seconds"),
                "guardian_stage": 0,
            },
        }

        prealert = app_module.build_status(profile, now=now)
        self.assertTrue(prealert["is_prealert"])
        self.assertFalse(prealert["is_overdue"])
        self.assertEqual(prealert["status_text"], "已提醒本人，等待平安回報")

        profile["active_overdue_event"]["started_at"] = (
            now - timedelta(hours=48, minutes=15)
        ).isoformat(timespec="seconds")
        profile["last_check_in"] = None
        boundary = app_module.build_status(profile, now=now)
        self.assertFalse(boundary["is_prealert"])
        self.assertTrue(boundary["is_overdue"])
        self.assertEqual(boundary["status_text"], "已進入守護人順位通知")

    def test_normalize_allowed_and_legacy(self):
        self.assertEqual(app_module.normalize_grace_hours(24), 24)
        self.assertEqual(app_module.normalize_grace_hours(36), 36)
        self.assertEqual(app_module.normalize_grace_hours(48), 48)
        self.assertEqual(app_module.normalize_grace_hours(72), 72)
        self.assertEqual(app_module.normalize_grace_hours(None), 48)
        self.assertEqual(app_module.normalize_grace_hours("abc"), 48)
        self.assertEqual(app_module.DEFAULT_GRACE_HOURS, 48)
        self.assertEqual(app_module.DEFAULT_PROFILE["grace_hours"], 48)
        self.assertEqual(app_module.normalize_overdue_wait_minutes(15), 15)
        self.assertEqual(app_module.normalize_overdue_wait_minutes(30), 30)
        self.assertEqual(app_module.normalize_overdue_wait_minutes(60), 60)
        self.assertEqual(app_module.normalize_overdue_wait_minutes(None), 15)
        self.assertEqual(app_module.DEFAULT_PROFILE["overdue_wait_minutes"], 15)

    def test_settings_persist_allowed_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_file = str(Path(tmp) / "state.json")
            status = app_module.save_settings_for_profile(
                data_file,
                {
                    "line_user_id": "U-grace",
                    "grace_hours": 24,
                    "overdue_wait_minutes": 15,
                    "reminder_time": "12:00",
                },
            )
            self.assertEqual(status["grace_hours"], 24)
            self.assertEqual(status["allowed_grace_hours"], [24, 36, 48, 72])
            self.assertEqual(status["overdue_wait_minutes"], 15)
            self.assertEqual(status["allowed_overdue_wait_minutes"], [15, 30, 60])

            status = app_module.save_settings_for_profile(
                data_file,
                {
                    "line_user_id": "U-grace",
                    "grace_hours": 36,
                    "reminder_time": "12:00",
                },
            )
            self.assertEqual(status["grace_hours"], 36)

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
        self.assertIn("第一、第二、第三順位", guardian_notice)
        self.assertIn("SOS", guardian_notice)


if __name__ == "__main__":
    unittest.main()
