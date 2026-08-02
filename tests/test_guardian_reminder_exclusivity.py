import os
import tempfile
import unittest
from datetime import datetime, timedelta

import app


class GuardianReminderExclusivityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_file = os.path.join(self.tmp.name, "state.json")
        self.sent = []

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, now):
        return {
            "DATA_FILE": self.data_file,
            "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
            "LINE_PUSH_SENDER": lambda token, target, message: self.sent.append(
                (target, message)
            ) or {"ok": True},
            "CRON_NOW": now,
            "APP_TIMEZONE": "Asia/Taipei",
        }

    @staticmethod
    def bound_guardian():
        return {
            "id": "guardian-1",
            "contact_role": "guardian",
            "line_user_id": "U-guardian",
            "binding_status": "accepted",
            "consent_status": "accepted",
            "notify_methods": ["line"],
        }

    def test_daily_checkin_card_requires_an_accepted_guardian(self):
        now = datetime(2026, 8, 3, 12, 0)
        app.save_state(
            self.data_file,
            {
                "users": {
                    "U-unbound": {
                        "line_user_id": "U-unbound",
                        "plan": "paid_799_year",
                        "payment_status": "active",
                        "paid_until": (now + timedelta(days=365)).isoformat(),
                        "reminder_times": ["12:00"],
                        "contacts": [],
                    },
                    "U-pending": {
                        "line_user_id": "U-pending",
                        "plan": "paid_799_year",
                        "payment_status": "active",
                        "paid_until": (now + timedelta(days=365)).isoformat(),
                        "reminder_times": ["12:00"],
                        "contacts": [{
                            "id": "pending",
                            "contact_role": "guardian",
                            "line_user_id": "U-peer",
                            "binding_status": "pending",
                        }],
                    },
                    "U-bound": {
                        "line_user_id": "U-bound",
                        "plan": "paid_799_year",
                        "payment_status": "active",
                        "paid_until": (now + timedelta(days=365)).isoformat(),
                        "reminder_times": ["12:00"],
                        "contacts": [self.bound_guardian()],
                    },
                }
            },
        )

        result, code = app.send_checkin_reminders(self.config(now))

        self.assertEqual(code, 200)
        self.assertEqual(result["sent"], 1)
        self.assertEqual([target for target, _ in self.sent], ["U-bound"])

    def test_beta_and_annual_binding_cadences_use_the_selected_days(self):
        start = datetime(2026, 8, 1, 9, 5)
        beta = {
            "membership_source": "beta",
            "beta_cohort": "B799",
            "guardian_unbound_since": start.isoformat(),
        }
        annual = {
            "plan": "paid_799_year",
            "guardian_unbound_since": start.isoformat(),
        }

        beta_due = [
            day for day in range(1, 22)
            if app.guardian_binding_reminder_due(beta, start + timedelta(days=day - 1))
        ]
        annual_due = [
            day for day in range(1, 23)
            if app.guardian_binding_reminder_due(annual, start + timedelta(days=day - 1))
        ]

        self.assertEqual(beta_due, [2, 4, 6, 8, 10, 13, 16, 19])
        self.assertEqual(annual_due, [3, 7, 14, 21])

    def test_bound_member_never_receives_binding_reminder(self):
        now = datetime(2026, 8, 3, 9, 5)
        app.save_state(
            self.data_file,
            {"users": {"U-bound": {
                "line_user_id": "U-bound",
                "plan": "paid_799_year",
                "payment_status": "active",
                "paid_until": (now + timedelta(days=365)).isoformat(),
                "membership_started_at": (now - timedelta(days=2)).isoformat(),
                "contacts": [self.bound_guardian()],
            }}},
        )

        result, code = app.send_missing_contact_reminders(self.config(now))

        self.assertEqual(code, 200)
        self.assertEqual(result["sent"], 0)
        self.assertEqual(self.sent, [])

    def test_phone_only_emergency_contact_does_not_count_as_bound_guardian(self):
        now = datetime(2026, 8, 3, 12, 0)
        app.save_state(
            self.data_file,
            {"users": {"U-owner": {
                "line_user_id": "U-owner",
                "plan": "paid_799_year",
                "payment_status": "active",
                "paid_until": (now + timedelta(days=365)).isoformat(),
                "reminder_times": ["12:00"],
                "contacts": [{
                    "id": "emergency-1",
                    "contact_role": "emergency",
                    "name": "家人",
                    "phone": "0912345678",
                }],
            }}},
        )

        result, code = app.send_checkin_reminders(self.config(now))

        self.assertEqual(code, 200)
        self.assertEqual(result["sent"], 0)
        self.assertEqual(self.sent, [])

    def test_daily_card_only_embeds_optional_emergency_contact_hint_when_missing(self):
        now = datetime(2026, 8, 3, 12, 0)
        profile = {
            "line_user_id": "U-owner",
            "contacts": [self.bound_guardian()],
        }

        missing_card = app.build_daily_checkin_flex(now, profile=profile)
        missing_body = missing_card["contents"]["body"]["contents"]
        missing_text = "\n".join(
            item.get("text", "") for item in missing_body if item.get("type") == "text"
        )
        self.assertIn("緊急聯絡人電話尚未設定", missing_text)
        self.assertIn("選填", missing_text)

        profile["contacts"].append({
            "id": "emergency-1",
            "contact_role": "emergency",
            "name": "媽媽",
            "phone": "0912345678",
        })
        completed_card = app.build_daily_checkin_flex(now, profile=profile)
        completed_body = completed_card["contents"]["body"]["contents"]
        completed_text = "\n".join(
            item.get("text", "") for item in completed_body if item.get("type") == "text"
        )
        self.assertNotIn("緊急聯絡人電話尚未設定", completed_text)

    def test_every_unbound_reminder_has_one_tap_guardian_share_button(self):
        now = datetime(2026, 8, 3, 9, 5)
        app.save_state(
            self.data_file,
            {"users": {"U-pending": {
                "line_user_id": "U-pending",
                "display_name": "Jennie",
                "plan": "paid_799_year",
                "payment_status": "active",
                "paid_until": (now + timedelta(days=365)).isoformat(),
                "membership_started_at": (now - timedelta(days=2)).isoformat(),
                "contacts": [{
                    "id": "pending-1",
                    "contact_role": "guardian",
                    "name": "媽媽",
                    "phone": "0912345678",
                    "binding_status": "pending",
                }],
            }}},
        )

        result, code = app.send_missing_contact_reminders(self.config(now))

        self.assertEqual(code, 200)
        self.assertEqual(result["sent"], 1)
        message = self.sent[0][1]
        self.assertIsInstance(message, dict)
        self.assertEqual(message["type"], "flex")
        button = message["contents"]["footer"]["contents"][0]
        self.assertEqual(button["action"]["label"], "💚 一鍵邀請守護人")
        self.assertEqual(button["action"]["type"], "uri")
        self.assertIn("share-invite", button["action"]["uri"])

    def test_deleting_last_guardian_restarts_unbound_schedule(self):
        now = datetime(2026, 8, 3, 9, 5)
        app.save_state(
            self.data_file,
            {"users": {"U-owner": {
                "line_user_id": "U-owner",
                "plan": "paid_799_year",
                "payment_status": "active",
                "paid_until": (now + timedelta(days=365)).isoformat(),
                "membership_started_at": (now - timedelta(days=100)).isoformat(),
                "contacts": [self.bound_guardian()],
            }}},
        )

        deleted, delete_code = app.delete_single_contact(
            self.data_file, "U-owner", "guardian-1"
        )
        self.assertEqual(delete_code, 200)
        self.assertTrue(deleted["deleted"])

        stored = app.load_state(self.data_file)["users"]["U-owner"]
        self.assertTrue(stored.get("guardian_unbound_since"))

        day_1, _ = app.send_missing_contact_reminders(self.config(now))
        self.assertEqual(day_1["sent"], 0)

        self.sent.clear()
        day_3, _ = app.send_missing_contact_reminders(
            self.config(now + timedelta(days=2))
        )
        self.assertEqual(day_3["sent"], 1)
        self.assertEqual([target for target, _ in self.sent], ["U-owner"])


if __name__ == "__main__":
    unittest.main()
