import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import app as alive_app


ROOT = Path(__file__).resolve().parents[1]


class SchedulerTickTests(unittest.TestCase):
    def test_cleanup_and_redemption_cannot_stale_overwrite_each_other(self):
        with tempfile.TemporaryDirectory() as temp:
            data_file = str(Path(temp) / "state.json")
            old_id = "U-old-cleanup-race"
            new_id = "U-new-cleanup-race"
            now = datetime(2026, 7, 26, 2, 0)
            config = {
                "DATA_FILE": data_file,
                "APP_TIMEZONE": "UTC",
                "CRON_NOW": now,
                "LEGACY_LINE_LOGIN_CHANNEL_ID": "legacy-channel",
                "LINE_LOGIN_CHANNEL_ID": "current-channel",
                "ACCOUNT_MIGRATION_SECRET": "test-only-secret",
                "ACCOUNT_MIGRATION_TTL_SECONDS": 600,
            }
            state = alive_app.load_state(data_file)
            state["users"][old_id] = {
                **alive_app.DEFAULT_PROFILE,
                "line_user_id": old_id,
                "display_name": "Legacy member",
            }
            alive_app.save_state(data_file, state)
            issued, issue_code = alive_app.create_account_migration_ticket(
                data_file,
                old_id,
                config,
                now=now,
            )
            self.assertEqual(issue_code, 200)

            cleanup_loaded = threading.Event()
            allow_cleanup = threading.Event()
            redemption_finished = threading.Event()
            real_purge = alive_app.purge_account_migration_snapshots

            def pause_after_cleanup_load(state, now=None):
                cleanup_loaded.set()
                allow_cleanup.wait(timeout=5)
                return real_purge(state, now=now)

            def redeem():
                try:
                    return alive_app.redeem_account_migration_ticket(
                        data_file,
                        issued["migration_code"],
                        new_id,
                        config,
                        now=now + timedelta(seconds=1),
                    )
                finally:
                    redemption_finished.set()

            with (
                mock.patch.object(
                    alive_app,
                    "purge_account_migration_snapshots",
                    side_effect=pause_after_cleanup_load,
                ),
                ThreadPoolExecutor(max_workers=2) as executor,
            ):
                cleanup_future = executor.submit(
                    alive_app.cleanup_expired_data,
                    config,
                )
                self.assertTrue(cleanup_loaded.wait(timeout=5))
                redeem_future = executor.submit(redeem)
                redemption_finished.wait(timeout=0.5)
                allow_cleanup.set()
                cleanup_result, cleanup_code = cleanup_future.result(timeout=5)
                redeem_result, redeem_code = redeem_future.result(timeout=5)

            self.assertEqual(cleanup_code, 200)
            self.assertEqual(cleanup_result["migration_snapshots_removed"], 0)
            self.assertEqual(redeem_code, 200)
            self.assertTrue(redeem_result["ok"])
            final = alive_app.load_state(data_file)
            self.assertNotIn(old_id, final["users"])
            self.assertIn(new_id, final["users"])
            self.assertEqual(
                final["account_migration_aliases"][old_id]["status"],
                "disabled",
            )
            self.assertEqual(
                next(iter(final["account_migration_tickets"].values()))["status"],
                "used",
            )
            self.assertEqual(len(final["account_migration_snapshots"]), 1)
            self.assertEqual(len(final["account_migration_audit"]), 1)

    def test_reminder_only_runs_in_zero_to_four_minute_window(self):
        self.assertTrue(
            alive_app.reminder_time_in_window(
                "12:00",
                datetime(2026, 7, 26, 12, 0),
            )
        )
        self.assertTrue(
            alive_app.reminder_time_in_window(
                "12:00",
                datetime(2026, 7, 26, 12, 4, 59),
            )
        )
        self.assertFalse(
            alive_app.reminder_time_in_window(
                "12:00",
                datetime(2026, 7, 26, 12, 5),
            )
        )
        self.assertFalse(
            alive_app.reminder_time_in_window(
                "08:00",
                datetime(2026, 7, 26, 15, 0),
            )
        )

    def test_tick_requires_secret_header_and_rejects_query_secret(self):
        app = alive_app.create_app(
            {
                "TESTING": True,
                "CRON_SECRET": "cron-secret",
                "ENABLE_INTERNAL_SCHEDULER": "0",
            }
        )
        client = app.test_client()
        self.assertEqual(client.post("/api/cron/tick").status_code, 401)
        self.assertEqual(
            client.post("/api/cron/tick?secret=cron-secret").status_code,
            401,
        )

    def test_tick_accepts_matching_secret_header(self):
        with tempfile.TemporaryDirectory() as temp:
            app = alive_app.create_app(
                {
                    "TESTING": True,
                    "CRON_SECRET": "cron-secret",
                    "DATA_FILE": str(Path(temp) / "state.json"),
                    "LINE_CHANNEL_ACCESS_TOKEN": "",
                    "CRON_NOW": datetime(2026, 7, 26, 15, 0),
                    "ENABLE_INTERNAL_SCHEDULER": "0",
                }
            )
            response = app.test_client().post(
                "/api/cron/tick",
                headers={"X-Cron-Secret": "cron-secret"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["timezone"], "Asia/Taipei")

    def test_legacy_cron_routes_reject_query_secret(self):
        config = {
            "TESTING": True,
            "CRON_SECRET": "cron-secret",
            "LINE_CHANNEL_ACCESS_TOKEN": "",
        }
        app = alive_app.create_app(config)
        response = app.test_client().post(
            "/api/cron/contact-reminders?secret=cron-secret"
        )
        self.assertEqual(response.status_code, 401)
        mini_response = alive_app.MiniApp(config).test_client().post(
            "/api/cron/contact-reminders?secret=cron-secret"
        )
        self.assertEqual(mini_response.status_code, 401)

    def test_mini_app_tick_uses_secret_header(self):
        with tempfile.TemporaryDirectory() as temp:
            app = alive_app.MiniApp(
                {
                    "CRON_SECRET": "cron-secret",
                    "DATA_FILE": str(Path(temp) / "state.json"),
                    "LINE_CHANNEL_ACCESS_TOKEN": "",
                    "CRON_NOW": datetime(2026, 7, 26, 15, 0),
                }
            )
            response = app.test_client().post(
                "/api/cron/tick",
                headers={"X-Cron-Secret": "cron-secret"},
            )
            self.assertEqual(response.status_code, 200)

    def test_daily_tick_slots_are_0900_birthday_and_0905_contacts(self):
        with tempfile.TemporaryDirectory() as temp:
            data_file = str(Path(temp) / "state.json")
            alive_app.save_state(data_file, {"users": {}})
            base_config = {
                "DATA_FILE": data_file,
                "LINE_CHANNEL_ACCESS_TOKEN": "",
            }

            birthday, _ = alive_app.run_cron_tick(
                {
                    **base_config,
                    "CRON_NOW": datetime(2026, 7, 26, 9, 0),
                }
            )
            contacts, _ = alive_app.run_cron_tick(
                {
                    **base_config,
                    "CRON_NOW": datetime(2026, 7, 26, 9, 5),
                }
            )
            afternoon, _ = alive_app.run_cron_tick(
                {
                    **base_config,
                    "CRON_NOW": datetime(2026, 7, 26, 15, 0),
                }
            )
            renewal, _ = alive_app.run_cron_tick(
                {
                    **base_config,
                    "CRON_NOW": datetime(2026, 7, 26, 10, 0),
                }
            )
            membership, _ = alive_app.run_cron_tick(
                {
                    **base_config,
                    "CRON_NOW": datetime(2026, 7, 26, 10, 15),
                }
            )
            cleanup, _ = alive_app.run_cron_tick(
                {
                    **base_config,
                    "CRON_NOW": datetime(2026, 7, 26, 2, 30),
                }
            )

            self.assertIn("birthday_reminders", birthday["tasks"])
            self.assertNotIn("contact_reminders", birthday["tasks"])
            self.assertIn("contact_reminders", contacts["tasks"])
            self.assertNotIn("birthday_reminders", contacts["tasks"])
            self.assertNotIn("birthday_reminders", afternoon["tasks"])
            self.assertNotIn("contact_reminders", afternoon["tasks"])
            self.assertIn("guardian_group_daily_summaries", afternoon["tasks"])
            self.assertIn("renewal_reminders", renewal["tasks"])
            self.assertIn("membership_expiry", membership["tasks"])
            self.assertIn("data_cleanup", cleanup["tasks"])

    def test_render_has_one_cron_and_internal_scheduler_disabled(self):
        render = (ROOT / "render.yaml").read_text(encoding="utf-8")
        self.assertEqual(render.count("- type: cron"), 1)
        self.assertIn("python cron_ping.py /api/cron/tick", render)
        self.assertIn('value: "0"', render)
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("_start_internal_scheduler(app)", app_source)

    def test_cron_secret_is_sent_in_header_not_url(self):
        source = (ROOT / "cron_ping.py").read_text(encoding="utf-8")
        self.assertIn('"X-Cron-Secret": cron_secret', source)
        self.assertNotIn('urlencode({"secret": cron_secret})', source)

    def test_tick_purges_expired_sos_records(self):
        with tempfile.TemporaryDirectory() as temp:
            data_file = str(Path(temp) / "state.json")
            old = datetime.now() - timedelta(minutes=61)
            alive_app.save_state(
                data_file,
                {
                    "users": {},
                    "sos_pending": {
                        "U-old": {
                            "stage": "warning_1",
                            "last_tap_at": old.isoformat(timespec="seconds"),
                        }
                    },
                },
            )
            result, code = alive_app.cleanup_expired_sos(
                {"DATA_FILE": data_file}
            )
            self.assertEqual(code, 200)
            self.assertEqual(result["removed"], 1)
            state = alive_app.load_state(data_file)
            self.assertNotIn("U-old", state.get("sos_pending", {}))

    def test_tick_migrates_existing_free_members_without_login(self):
        with tempfile.TemporaryDirectory() as temp:
            data_file = str(Path(temp) / "state.json")
            state = alive_app.load_state(data_file)
            profile = alive_app.get_profile(state, "U-legacy-free")
            profile["plan"] = "free"
            profile["payment_status"] = "expired"
            profile["membership_source"] = "expired"
            profile.pop("trial_policy_version", None)
            profile.pop("trial_end", None)
            alive_app.save_state(data_file, state)

            result, code = alive_app.run_cron_tick(
                {
                    "DATA_FILE": data_file,
                    "LINE_CHANNEL_ACCESS_TOKEN": "",
                    "CRON_NOW": datetime(2026, 7, 26, 15, 0),
                }
            )

            self.assertEqual(code, 200)
            self.assertEqual(
                result["tasks"]["membership_transition_migration"]["result"]["migrated"],
                1,
            )
            migrated = alive_app.load_state(data_file)["users"]["U-legacy-free"]
            self.assertEqual(migrated["plan"], "trial")
            self.assertEqual(migrated["membership_source"], "transition_trial")
            self.assertEqual(migrated["trial_started_at"], "2026-07-26T15:00:00")


if __name__ == "__main__":
    unittest.main()
