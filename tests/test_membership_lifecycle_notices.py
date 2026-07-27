"""Membership expiry notices and renewal restoration."""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import app as app_module


class MembershipLifecycleNoticeTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.fromisoformat("2026-07-27T10:00:00")

    def test_expiry_flex_has_one_upgrade_button_and_no_duplicate_plan_button(self):
        flex = app_module.build_expiry_remind_flex(
            {
                "plan": "trial",
                "trial_started_at": (
                    self.now - timedelta(days=12)
                ).isoformat(timespec="seconds"),
            },
            now=self.now,
        )
        buttons = flex["contents"]["footer"]["contents"]
        labels = [button["action"]["label"] for button in buttons]

        self.assertEqual(
            labels,
            ["升級後繼續每日問候", "不再提醒我"],
        )
        self.assertNotIn("查看方案", str(flex))

    def test_trial_beta_and_paid_notice_schedules(self):
        self.assertEqual(
            app_module.membership_notice_milestones(
                {
                    "plan": "trial",
                    "trial_started_at": (
                        self.now - timedelta(days=12)
                    ).isoformat(timespec="seconds"),
                },
                now=self.now,
            ),
            [12],
        )
        self.assertEqual(
            app_module.membership_notice_milestones(
                {
                    "plan": "paid_399",
                    "membership_source": "beta",
                    "beta_started_at": (
                        self.now - timedelta(days=20)
                    ).isoformat(timespec="seconds"),
                    "beta_ends_at": (
                        self.now + timedelta(days=1)
                    ).isoformat(timespec="seconds"),
                },
                now=self.now,
            ),
            [20],
        )
        self.assertEqual(
            app_module.membership_notice_milestones(
                {
                    "plan": "paid_799",
                    "membership_source": "paid",
                    "payment_status": "active",
                    "paid_until": (
                        self.now + timedelta(days=3)
                    ).isoformat(timespec="seconds"),
                },
                now=self.now,
            ),
            [3],
        )

    def test_renewal_restores_original_daily_greeting_choice_and_settings(self):
        profile = {
            "line_user_id": "U-owner",
            "plan": "paid_399",
            "daily_checkin_reminder_enabled": False,
            "reminder_times": ["08:30", "19:30"],
            "contacts": [{"line_id": "U-mom", "is_primary": True}],
        }
        app_module.mark_entitlement_lapsed(profile, self.now)
        app_module.restore_membership_after_renewal(
            profile,
            "paid_799",
            self.now + timedelta(days=30),
            now=self.now,
        )

        self.assertFalse(profile["daily_checkin_reminder_enabled"])
        self.assertEqual(profile["reminder_times"], ["08:30", "19:30"])
        self.assertEqual(profile["contacts"][0]["line_id"], "U-mom")
        self.assertFalse(profile["membership_paused"])

    def test_lifecycle_push_sends_flex_once_for_due_paid_notice(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "state.json"
            app_module.save_state(
                data_file,
                {
                    "users": {
                        "U-owner": {
                            "line_user_id": "U-owner",
                            "plan": "paid_399",
                            "membership_source": "paid",
                            "payment_status": "active",
                            "paid_until": (
                                self.now + timedelta(days=3)
                            ).isoformat(timespec="seconds"),
                        }
                    }
                },
            )
            sent = []
            config = {
                "DATA_FILE": data_file,
                "LINE_CHANNEL_ACCESS_TOKEN": "token",
                "LINE_PUSH_SENDER": lambda token, target, message: sent.append(
                    (target, message)
                ),
            }

            first, first_code = app_module.send_membership_lifecycle_notices(
                config, now=self.now
            )
            second, second_code = app_module.send_membership_lifecycle_notices(
                config, now=self.now
            )

            self.assertEqual((first_code, second_code), (200, 200))
            self.assertEqual(first["sent"], 1)
            self.assertEqual(second["sent"], 0)
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0][1]["type"], "flex")
            self.assertIn("升級後繼續每日問候", str(sent[0][1]))


if __name__ == "__main__":
    unittest.main()
