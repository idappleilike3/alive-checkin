"""Product rules: one check-in; private default; optional group alerts."""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import app as alive_app


class NotifyChannelPrefsTests(unittest.TestCase):
    def test_default_group_preferences_private_on_group_off(self):
        prefs = alive_app.normalize_guardian_group_preferences(None)
        self.assertTrue(prefs["notify_private_guardians"])
        self.assertFalse(prefs["notify_group_on_overdue"])
        self.assertFalse(prefs["daily_admin_summary"])
        self.assertTrue(prefs["notify_admin_only"])

    def test_bind_guardian_group_persists_new_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_file = str(Path(tmp) / "state.json")
            state = alive_app.load_state(data_file)
            state["users"]["U1"] = {
                **alive_app.DEFAULT_PROFILE,
                "line_user_id": "U1",
                "plan": "paid_799",
                "payment_status": "active",
                "paid_until": (datetime.now() + timedelta(days=30)).isoformat(timespec="seconds"),
            }
            alive_app.save_state(data_file, state)
            result, code = alive_app.bind_guardian_group(
                data_file, {"line_user_id": "U1", "group_id": "G1"}
            )
            self.assertEqual(code, 200)
            self.assertTrue(result.get("bound"))
            group = alive_app.load_state(data_file)["guardian_groups"]["G1"]
            prefs = group["preferences"]
            self.assertTrue(prefs["notify_private_guardians"])
            self.assertFalse(prefs["notify_group_on_overdue"])
            self.assertFalse(prefs["daily_admin_summary"])

    def test_private_off_skips_core_guardian_push(self):
        pushes = []

        def fake_sender(token, target, message):
            pushes.append((target, message))
            return {"ok": True}

        with tempfile.TemporaryDirectory() as tmp:
            data_file = str(Path(tmp) / "state.json")
            now = datetime.now()
            state = alive_app.load_state(data_file)
            state["users"]["U-owner"] = {
                **alive_app.DEFAULT_PROFILE,
                "line_user_id": "U-owner",
                "display_name": "阿明",
                "plan": "paid_799",
                "payment_status": "active",
                "paid_until": (now + timedelta(days=10)).isoformat(timespec="seconds"),
                "last_check_in": (now - timedelta(days=3)).isoformat(timespec="seconds"),
                "history": [],
                "reminder_time": "08:00",
                "contacts": [
                    {
                        "id": "c1",
                        "name": "家人",
                        "line_id": "U-g1",
                        "priority": 1,
                        "notify_methods": ["line"],
                        "binding_status": "accepted",
                    }
                ],
                "guardian_group_ids": ["Cgroup1"],
            }
            state["guardian_groups"] = {
                "Cgroup1": {
                    "owner_line_user_id": "U-owner",
                    "status": "active",
                    "preferences": {
                        "notify_private_guardians": False,
                        "notify_group_on_overdue": True,
                    },
                }
            }
            alive_app.save_state(data_file, state)
            alive_app.send_due_reminders(
                {
                    "DATA_FILE": data_file,
                    "LINE_CHANNEL_ACCESS_TOKEN": "token",
                    "LINE_PUSH_SENDER": fake_sender,
                    "CRON_NOW": now,
                }
            )
            targets = [t for t, _ in pushes]
            self.assertIn("U-owner", targets)  # self nudge still sent
            self.assertNotIn("U-g1", targets)
            self.assertIn("Cgroup1", targets)

    def test_daily_group_summary_respects_flag_and_hour(self):
        pushes = []

        def fake_sender(token, target, message):
            pushes.append((target, message))
            return {"ok": True}

        with tempfile.TemporaryDirectory() as tmp:
            data_file = str(Path(tmp) / "state.json")
            morning = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
            evening = morning.replace(hour=21, minute=5)
            state = alive_app.load_state(data_file)
            state["users"]["U-owner"] = {
                **alive_app.DEFAULT_PROFILE,
                "line_user_id": "U-owner",
                "display_name": "阿明",
                "history": [evening.strftime("%Y-%m-%d")],
            }
            state["guardian_groups"] = {
                "G1": {
                    "owner_line_user_id": "U-owner",
                    "status": "active",
                    "member_ids_at_bind": [],
                    "preferences": {"daily_admin_summary": True},
                }
            }
            alive_app.save_state(data_file, state)
            deferred, code = alive_app.send_guardian_group_daily_summaries(
                {
                    "DATA_FILE": data_file,
                    "LINE_CHANNEL_ACCESS_TOKEN": "token",
                    "LINE_PUSH_SENDER": fake_sender,
                    "CRON_NOW": morning,
                }
            )
            self.assertEqual(code, 200)
            self.assertEqual(deferred.get("sent"), 0)
            self.assertEqual(pushes, [])

            sent, code = alive_app.send_guardian_group_daily_summaries(
                {
                    "DATA_FILE": data_file,
                    "LINE_CHANNEL_ACCESS_TOKEN": "token",
                    "LINE_PUSH_SENDER": fake_sender,
                    "CRON_NOW": evening,
                }
            )
            self.assertEqual(code, 200)
            self.assertEqual(sent.get("sent"), 1)
            self.assertEqual(pushes[0][0], "G1")
            self.assertIn("今日平安摘要", pushes[0][1])

    def test_owner_roster_text_and_one_checkin_rule_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_file = str(Path(tmp) / "state.json")
            today = datetime.now().strftime("%Y-%m-%d")
            state = alive_app.load_state(data_file)
            state["users"]["U-owner"] = {
                **alive_app.DEFAULT_PROFILE,
                "line_user_id": "U-owner",
                "display_name": "阿明",
                "plan": "paid_799",
                "history": [today],
                "guardian_group_ids": ["G1"],
            }
            state["guardian_groups"] = {
                "G1": {
                    "owner_line_user_id": "U-owner",
                    "status": "active",
                    "preferences": {},
                }
            }
            alive_app.save_state(data_file, state)
            text, code = alive_app.owner_today_safety_roster_text(data_file, "U-owner")
            self.assertEqual(code, 200)
            self.assertIn("今天誰還沒報平安", text)
            self.assertIn("不必再另外做群組簽到", text)
            self.assertIn("生日／生活提醒只會私訊", text)
            self.assertIn("群組提醒：關", text)

    def test_member_ui_has_channel_checkboxes(self):
        page = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
        self.assertIn("私訊提醒（預設，建議）", page)
        self.assertIn("群組提醒（選用）", page)
        self.assertIn("notify_group_on_overdue === true", page)
        self.assertIn("今天誰還沒報平安", page)
        self.assertIn("生日／生活提醒只會私訊", page)


if __name__ == "__main__":
    unittest.main()
