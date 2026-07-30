import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import app


class OverdueEscalationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_file = str(Path(self.tmp.name) / "state.json")
        self.started = datetime(2026, 7, 29, 9, 0)
        contacts = [
            {
                "id": f"g-{idx}",
                "name": name,
                "line_id": target,
                "binding_status": "accepted",
                "consent_status": "accepted",
                "contact_role": "guardian",
                "is_primary": idx == 1,
                "priority": idx,
                "notify_methods": ["line"],
            }
            for idx, (name, target) in enumerate(
                [("媽媽", "U-g1"), ("姊姊", "U-g2"), ("弟弟", "U-g3")],
                start=1,
            )
        ]
        profile = {
            **app.DEFAULT_PROFILE,
            "line_user_id": "U-owner",
            "display_name": "小美",
            "plan": "paid_399",
            "payment_status": "active",
            "paid_until": "2099-12-31T23:59:59",
            "overdue_wait_minutes": 30,
            "contacts": contacts,
            "active_overdue_event": {
                "event_id": "overdue-U-owner-2026-07-29",
                "date": "2026-07-29",
                "reminder_time": "09:00",
                "started_at": self.started.isoformat(timespec="seconds"),
                "self_followup_sent_at": "",
                "guardian_stage": 0,
                "notified_guardian_ids": [],
                "resolved_at": "",
            },
        }
        app.save_state(self.data_file, {"users": {"U-owner": profile}})
        self.pushes = []

    def run_due(self, now):
        return app.send_due_reminders({
            "DATA_FILE": self.data_file,
            "LINE_CHANNEL_ACCESS_TOKEN": "token",
            "CRON_NOW": now,
            "LINE_PUSH_SENDER": (
                lambda _token, target, message: self.pushes.append((target, message))
                or {"ok": True}
            ),
        })

    def test_self_then_first_second_third_guardian_without_duplicates(self):
        self.run_due(datetime(2026, 7, 31, 9, 0))
        self.run_due(datetime(2026, 7, 31, 9, 30))
        self.run_due(datetime(2026, 7, 31, 10, 0))
        self.run_due(datetime(2026, 7, 31, 10, 30))
        self.run_due(datetime(2026, 7, 31, 11, 0))

        self.assertEqual(
            [target for target, _message in self.pushes],
            ["U-owner", "U-g1", "U-g2", "U-g3"],
        )
        event = app.load_state(self.data_file)["users"]["U-owner"]["active_overdue_event"]
        self.assertEqual(event["guardian_stage"], 3)
        self.assertEqual(event["notified_guardian_ids"], ["U-g1", "U-g2", "U-g3"])

    def test_sends_nothing_at_15_minutes_and_alerts_after_48_hours_plus_15(self):
        state = app.load_state(self.data_file)
        state["users"]["U-owner"]["overdue_wait_minutes"] = 15
        app.save_state(self.data_file, state)

        self.run_due(datetime(2026, 7, 29, 9, 15))
        self.assertEqual(self.pushes, [])

        self.run_due(datetime(2026, 7, 31, 9, 0))
        self.assertEqual([target for target, _ in self.pushes], ["U-owner"])

        self.run_due(datetime(2026, 7, 31, 9, 15))
        self.assertEqual(
            [target for target, _ in self.pushes],
            ["U-owner", "U-g1"],
        )

    def test_second_daily_slot_does_not_restart_active_event(self):
        state = app.load_state(self.data_file)
        profile = state["users"]["U-owner"]
        original = app.ensure_active_overdue_event(
            profile, "09:00", datetime(2026, 7, 29, 9, 0)
        )
        again = app.ensure_active_overdue_event(
            profile, "18:00", datetime(2026, 7, 29, 18, 0)
        )
        self.assertIs(original, again)
        self.assertEqual(again["reminder_time"], "09:00")

    def test_next_day_reminder_does_not_restart_48_hour_clock(self):
        state = app.load_state(self.data_file)
        profile = state["users"]["U-owner"]
        original = app.ensure_active_overdue_event(
            profile, "09:00", datetime(2026, 7, 29, 9, 0)
        )
        next_day = app.ensure_active_overdue_event(
            profile, "12:00", datetime(2026, 7, 30, 12, 0)
        )

        self.assertIs(original, next_day)
        self.assertEqual(next_day["started_at"], "2026-07-29T09:00:00")
        self.assertEqual(next_day["reminder_time"], "09:00")

    def test_checkin_closes_active_overdue_flow(self):
        app.record_checkin(
            self.data_file,
            {"line_user_id": "U-owner"},
            config={"CRON_NOW": datetime(2026, 7, 29, 9, 20)},
        )
        profile = app.load_state(self.data_file)["users"]["U-owner"]
        self.assertIsNone(profile["active_overdue_event"])
        self.run_due(datetime(2026, 7, 29, 9, 30))
        self.assertEqual(self.pushes, [])

    def test_successful_checkin_notifies_all_bound_core_guardians(self):
        result = app.notify_guardians_of_checkin(
            self.data_file,
            "U-owner",
            config={
                "LINE_CHANNEL_ACCESS_TOKEN": "token",
                "LINE_PUSH_SENDER": (
                    lambda _token, target, message:
                    self.pushes.append((target, message)) or {"ok": True}
                ),
                "CRON_NOW": datetime(2026, 7, 29, 9, 20),
            },
        )
        self.assertEqual(result["sent"], 3)
        self.assertEqual(
            [target for target, _message in self.pushes],
            ["U-g1", "U-g2", "U-g3"],
        )


if __name__ == "__main__":
    unittest.main()
