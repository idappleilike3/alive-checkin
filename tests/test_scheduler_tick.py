import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import app as alive_app


ROOT = Path(__file__).resolve().parents[1]


class SchedulerTickTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
