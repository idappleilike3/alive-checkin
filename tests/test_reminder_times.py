import tempfile
import unittest
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as alive_app


class ReminderTimesTests(unittest.TestCase):
    def test_default_times_by_count(self):
        self.assertEqual(alive_app.default_reminder_times_for_count(1), ["12:00"])
        self.assertEqual(alive_app.default_reminder_times_for_count(2), ["12:00", "18:00"])
        self.assertEqual(alive_app.default_reminder_times_for_count(3), ["12:00", "18:00", "22:00"])

    def test_plan_limits_drive_reminder_count(self):
        self.assertEqual(alive_app.plan_rules({"plan": "trial"})["daily_reminders"], 1)
        self.assertEqual(alive_app.plan_rules({"plan": "paid_199"})["daily_reminders"], 1)
        self.assertEqual(alive_app.plan_rules({"plan": "paid_199_year"})["daily_reminders"], 2)
        self.assertEqual(alive_app.plan_rules({"plan": "paid_399"})["daily_reminders"], 2)
        self.assertEqual(alive_app.plan_rules({"plan": "paid_399_year"})["daily_reminders"], 3)
        self.assertEqual(alive_app.plan_rules({"plan": "paid_799"})["daily_reminders"], 3)
        self.assertEqual(alive_app.plan_rules({"plan": "paid_799_year"})["daily_reminders"], 3)

    def test_profile_falls_back_to_defaults(self):
        profile = {"plan": "paid_399"}
        self.assertEqual(alive_app.reminder_times_for_profile(profile), ["12:00", "18:00"])

    def test_profile_keeps_custom_times_within_limit(self):
        profile = {"plan": "paid_799", "reminder_times": ["10:30", "15:00", "21:15", "23:00"]}
        self.assertEqual(alive_app.reminder_times_for_profile(profile), ["10:30", "15:00", "21:15"])

    def test_send_checkin_reminders_respects_multiple_slots(self):
        sent_messages = []

        def fake_sender(token, user_id, message):
            sent_messages.append((user_id, message))
            return {"ok": True}

        with tempfile.TemporaryDirectory() as tmp:
            data_file = str(Path(tmp) / "state.json")
            state = {
                "users": {
                    "U1": {
                        "line_user_id": "U1",
                        "plan": "paid_399",
                        "history": [],
                        "reminder_times": ["12:00", "18:00"],
                        "reminder_time": "12:00",
                        "checkin_reminder_sent_dates": [],
                        "checkin_reminder_sent_slots": {},
                    }
                }
            }
            alive_app.save_state(data_file, state)

            # 12:30 → 應送出 12:00 時段
            config = {
                "DATA_FILE": data_file,
                "LINE_CHANNEL_ACCESS_TOKEN": "token",
                "LINE_PUSH_SENDER": fake_sender,
                "APP_TIMEZONE": "Asia/Taipei",
                "CRON_NOW": datetime(2026, 7, 22, 12, 30),
            }
            result, code = alive_app.send_checkin_reminders(config)
            self.assertEqual(code, 200)
            self.assertEqual(result["sent"], 1)
            self.assertEqual(len(sent_messages), 1)
            self.assertIn("12:00", sent_messages[0][1])

            reloaded = alive_app.load_state(data_file)
            slots = reloaded["users"]["U1"]["checkin_reminder_sent_slots"]["2026-07-22"]
            self.assertEqual(slots, ["12:00"])
            self.assertNotIn("2026-07-22", reloaded["users"]["U1"].get("checkin_reminder_sent_dates") or [])

            # 18:10 → 應再送 18:00
            config["CRON_NOW"] = datetime(2026, 7, 22, 18, 10)
            result2, code2 = alive_app.send_checkin_reminders(config)
            self.assertEqual(code2, 200)
            self.assertEqual(result2["sent"], 1)
            self.assertEqual(len(sent_messages), 2)
            self.assertIn("18:00", sent_messages[1][1])

            reloaded2 = alive_app.load_state(data_file)
            slots2 = reloaded2["users"]["U1"]["checkin_reminder_sent_slots"]["2026-07-22"]
            self.assertEqual(slots2, ["12:00", "18:00"])
            self.assertIn("2026-07-22", reloaded2["users"]["U1"]["checkin_reminder_sent_dates"])


if __name__ == "__main__":
    unittest.main()
