import unittest
from datetime import datetime

import app


class LineMessageUsageTests(unittest.TestCase):
    def test_usage_is_idempotent_and_counts_actual_recipients(self):
        state = {}
        first = app.record_line_message_usage(
            state,
            category="sos",
            owner_line_user_id="U-owner",
            recipient_count=3,
            event_id="sos-1",
            sent_at=datetime(2026, 7, 10, 9, 0),
        )
        duplicate = app.record_line_message_usage(
            state,
            category="sos",
            owner_line_user_id="U-owner",
            recipient_count=3,
            event_id="sos-1",
            sent_at=datetime(2026, 7, 10, 9, 0),
        )
        self.assertEqual(first["units"], 3)
        self.assertTrue(duplicate["idempotent"])
        self.assertEqual(len(state["line_message_usage"]), 1)

    def test_monthly_usage_has_category_member_projection_and_alerts(self):
        state = {}
        for index, (category, owner, units, day) in enumerate([
            ("checkin", "U-a", 20, 1),
            ("sos", "U-a", 30, 10),
            ("sos_cancel", "U-a", 5, 10),
            ("guardian_summary", "U-b", 15, 15),
        ]):
            app.record_line_message_usage(
                state,
                category=category,
                owner_line_user_id=owner,
                recipient_count=units,
                event_id=f"event-{index}",
                sent_at=datetime(2026, 7, day, 9, 0),
            )
        usage = app.monthly_line_message_usage(
            state, "2026-07", quota=100, now=datetime(2026, 7, 20, 12, 0)
        )
        self.assertEqual(usage["used_units"], 70)
        self.assertEqual(usage["category_totals"]["sos"], 30)
        self.assertEqual(usage["member_totals"][0]["units"], 55)
        self.assertEqual(usage["false_alarm_units"], 5)
        self.assertGreaterEqual(usage["projected_units"], 108)
        self.assertEqual(usage["alert_level"], "warning_70")

        critical = app.monthly_line_message_usage(
            state, "2026-07", quota=75, now=datetime(2026, 7, 20, 12, 0)
        )
        self.assertEqual(critical["alert_level"], "critical_90")

    def test_failed_or_zero_recipient_delivery_is_not_recorded(self):
        state = {}
        result = app.record_line_message_usage(
            state,
            category="smart_reminder",
            owner_line_user_id="U-owner",
            recipient_count=0,
            event_id="failed-1",
            sent_at=datetime(2026, 7, 20, 9, 0),
        )
        self.assertFalse(result["recorded"])
        self.assertEqual(state.get("line_message_usage") or [], [])


if __name__ == "__main__":
    unittest.main()
