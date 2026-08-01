"""Day-7 LINE pin reminder scheduling, delivery and audit records."""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import app as app_module


class Day7PinReminderTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.fromisoformat("2026-08-10T10:00:00")

    def config(self, data_file, sent):
        return {
            "DATA_FILE": data_file,
            "LINE_CHANNEL_ACCESS_TOKEN": "token",
            "LEGACY_DAY7_PIN_REMINDER_ENABLED": True,
            "LINE_PUSH_SENDER": lambda token, target, message: sent.append(
                (target, message)
            ) or {"ok": True},
        }

    def test_first_run_sets_cutoff_without_backfilling_existing_members(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "state.json"
            app_module.save_state(
                data_file,
                {
                    "users": {
                        "U-old": {
                            "line_user_id": "U-old",
                            "plan": "paid_799_year",
                            "membership_source": "beta",
                            "beta_cohort": "B799",
                            "beta_started_at": (
                                self.now - timedelta(days=10)
                            ).isoformat(timespec="seconds"),
                        }
                    }
                },
            )
            sent = []

            result, code = app_module.send_day7_pin_reminders(
                self.config(data_file, sent), now=self.now
            )

            state = app_module.load_state(data_file)
            self.assertEqual(code, 200)
            self.assertEqual(result["reason"], "feature_initialized")
            self.assertEqual(sent, [])
            self.assertEqual(
                state["day7_pin_reminder_enabled_at"],
                self.now.isoformat(timespec="seconds"),
            )

    def test_trial_beta_and_paid_memberships_send_once_after_cutoff(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "state.json"
            started = self.now - timedelta(days=7, minutes=1)
            app_module.save_state(
                data_file,
                {
                    "day7_pin_reminder_enabled_at": (
                        started + timedelta(days=7) - timedelta(minutes=1)
                    ).isoformat(timespec="seconds"),
                    "users": {
                        "U-trial": {
                            "line_user_id": "U-trial",
                            "plan": "trial",
                            "membership_source": "public_trial",
                            "trial_started_at": started.isoformat(timespec="seconds"),
                        },
                        "U-beta": {
                            "line_user_id": "U-beta",
                            "plan": "paid_799_year",
                            "membership_source": "beta",
                            "beta_cohort": "B799",
                            "beta_started_at": started.isoformat(timespec="seconds"),
                            "beta_ends_at": (
                                started + timedelta(days=21)
                            ).isoformat(timespec="seconds"),
                        },
                        "U-paid": {
                            "line_user_id": "U-paid",
                            "plan": "paid_399",
                            "membership_source": "paid",
                            "payment_status": "active",
                            "paid_until": (
                                started + timedelta(days=30)
                            ).isoformat(timespec="seconds"),
                        },
                    },
                },
            )
            sent = []
            config = self.config(data_file, sent)

            first, first_code = app_module.send_day7_pin_reminders(
                config, now=self.now
            )
            second, second_code = app_module.send_day7_pin_reminders(
                config, now=self.now + timedelta(minutes=1)
            )

            self.assertEqual((first_code, second_code), (200, 200))
            self.assertEqual(first["sent"], 3)
            self.assertEqual(second["sent"], 0)
            self.assertEqual({target for target, _ in sent}, {
                "U-trial", "U-beta", "U-paid",
            })
            self.assertTrue(all(message["type"] == "flex" for _, message in sent))
            self.assertIn("置頂", str(sent))

    def test_log_preserves_beta_plan_schedule_and_actual_send_time(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "state.json"
            started = self.now - timedelta(days=7)
            due_at = started + timedelta(days=7)
            app_module.save_state(
                data_file,
                {
                    "day7_pin_reminder_enabled_at": (
                        due_at - timedelta(seconds=1)
                    ).isoformat(timespec="seconds"),
                    "users": {
                        "U-b799": {
                            "line_user_id": "U-b799",
                            "display_name": "小美",
                            "plan": "paid_799_year",
                            "membership_source": "beta",
                            "beta_cohort": "B799",
                            "beta_started_at": started.isoformat(timespec="seconds"),
                            "beta_ends_at": (
                                started + timedelta(days=21)
                            ).isoformat(timespec="seconds"),
                        }
                    },
                },
            )

            app_module.send_day7_pin_reminders(
                self.config(data_file, []), now=self.now
            )

            log = app_module.load_state(data_file)["notification_logs"][-1]
            self.assertEqual(log["kind"], "day7_pin_reminder")
            self.assertEqual(log["status"], "sent")
            self.assertEqual(log["plan"], "paid_799_year")
            self.assertEqual(log["membership_source"], "beta")
            self.assertEqual(log["beta_cohort"], "B799")
            self.assertEqual(log["scheduled_at"], due_at.isoformat(timespec="seconds"))
            self.assertEqual(log["sent_at"], self.now.isoformat(timespec="seconds"))

    def test_legacy_day7_scheduler_is_retired_and_does_not_send(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "state.json"
            started = self.now - timedelta(days=7)
            app_module.save_state(
                data_file,
                {
                    "day7_pin_reminder_enabled_at": (
                        self.now - timedelta(seconds=1)
                    ).isoformat(timespec="seconds"),
                    "users": {
                        "U-fail": {
                            "line_user_id": "U-fail",
                            "plan": "trial",
                            "membership_source": "public_trial",
                            "trial_started_at": started.isoformat(timespec="seconds"),
                        }
                    },
                },
            )
            attempts = []

            def fail_sender(token, target, message):
                attempts.append(target)
                raise RuntimeError("LINE blocked")

            config = {
                "DATA_FILE": data_file,
                "LINE_CHANNEL_ACCESS_TOKEN": "token",
                "LEGACY_DAY7_PIN_REMINDER_ENABLED": False,
                "LINE_PUSH_SENDER": fail_sender,
            }
            first, _ = app_module.send_day7_pin_reminders(config, now=self.now)
            second, _ = app_module.send_day7_pin_reminders(
                config, now=self.now + timedelta(minutes=1)
            )

            state = app_module.load_state(data_file)
            profile = state["users"]["U-fail"]
            logs = [
                row for row in state["notification_logs"]
                if row["kind"] == "day7_pin_reminder"
            ]
            self.assertEqual(first["failed"], 0)
            self.assertEqual(second["failed"], 0)
            self.assertEqual(first["reason"], "legacy_scheduler_retired")
            self.assertEqual(second["reason"], "legacy_scheduler_retired")
            self.assertEqual(attempts, [])
            self.assertEqual(logs, [])
            self.assertEqual(profile.get("day7_pin_reminder_keys_sent", []), [])

    def test_deploy_smoke_uid_is_removed_before_any_push(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "state.json"
            app_module.save_state(data_file, {
                "users": {
                    "U_deploy_smoke_ax": {
                        "line_user_id": "U_deploy_smoke_ax",
                        "plan": "trial",
                    },
                    "U-real": {"line_user_id": "U-real", "plan": "trial"},
                }
            })

            result = app_module.remove_retired_push_uids(
                data_file, {"RETIRED_LINE_USER_IDS": "U_deploy_smoke_ax"}
            )

            state = app_module.load_state(data_file)
            self.assertEqual(result["removed"], 1)
            self.assertNotIn("U_deploy_smoke_ax", state["users"])
            self.assertIn("U-real", state["users"])

    def test_admin_page_displays_plan_and_scheduled_time_for_push_logs(self):
        source = Path("admin.html").read_text(encoding="utf-8")
        self.assertIn("當時方案", source)
        self.assertIn("預定發送", source)


if __name__ == "__main__":
    unittest.main()
