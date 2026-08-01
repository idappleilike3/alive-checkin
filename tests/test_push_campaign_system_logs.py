import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app import append_notification_log, cleanup_expired_data, load_state, save_state


def state_fixture():
    return {
        "users": {
            "U1": {
                "line_user_id": "U1",
                "display_name": "小安",
                "plan": "paid_799_year",
                "membership_source": "gift",
                "gift_code": "G799",
                "payment_status": "active",
                "paid_until": "2027-08-01T00:00:00",
            }
        }
    }


class PermanentSystemDeliveryLogTests(unittest.TestCase):
    def test_successful_system_notification_is_mirrored_with_member_snapshot(self):
        state = state_fixture()

        append_notification_log(
            state,
            "sos",
            "U1",
            "sent",
            "緊急通知",
            metadata={
                "event_id": "sos-E1-U1",
                "scheduled_at": "2026-08-01T09:00:00",
                "sent_at": "2026-08-01T09:00:03",
            },
        )

        record = state["push_delivery_records"][0]
        self.assertEqual(record["source"], "system")
        self.assertEqual(record["kind"], "sos")
        self.assertEqual(record["event_id"], "sos-E1-U1")
        self.assertEqual(record["recipient_display_name"], "小安")
        self.assertEqual(record["line_user_id"], "U1")
        self.assertEqual(record["plan"], "paid_799_year")
        self.assertEqual(record["audience_code"], "G799")
        self.assertEqual(record["scheduled_at"], "2026-08-01T09:00:00")
        self.assertEqual(record["sent_at"], "2026-08-01T09:00:03")
        self.assertEqual(record["status"], "sent")

    def test_failed_system_notification_has_chinese_reason_and_action(self):
        state = state_fixture()

        append_notification_log(
            state,
            "binding",
            "U1",
            "failed",
            "綁定完成通知",
            detail="HTTP Error 400: blocked",
        )

        record = state["push_delivery_records"][0]
        self.assertEqual(record["status"], "failed")
        self.assertTrue(record["failure_reason_zh"])
        self.assertTrue(record["failure_action_zh"])
        self.assertEqual(record["technical_detail"], "HTTP Error 400: blocked")

    def test_all_system_kinds_share_the_permanent_ledger(self):
        state = state_fixture()
        kinds = (
            "sos",
            "binding",
            "checkin",
            "day7_pin_reminder",
            "beta_feedback_day2",
            "profile_completion",
        )
        for kind in kinds:
            append_notification_log(state, kind, "U1", "sent", f"{kind} 訊息")

        self.assertEqual(
            [record["kind"] for record in state["push_delivery_records"]],
            list(kinds),
        )

    def test_legacy_dashboard_stays_at_100_but_permanent_ledger_keeps_every_row(self):
        state = state_fixture()
        for index in range(150):
            append_notification_log(
                state,
                "checkin",
                "U1",
                "sent",
                f"第 {index} 筆",
                metadata={"event_id": f"checkin-{index}"},
            )

        self.assertEqual(len(state["notification_logs"]), 100)
        self.assertEqual(len(state["push_delivery_records"]), 150)

    def test_stable_system_event_id_is_idempotent(self):
        state = state_fixture()
        for _ in range(2):
            append_notification_log(
                state,
                "sos",
                "U1",
                "sent",
                "同一事件",
                metadata={"event_id": "stable-event"},
            )

        self.assertEqual(len(state["push_delivery_records"]), 1)

    def test_data_cleanup_never_removes_permanent_delivery_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            data_file = str(Path(temp) / "state.json")
            state = state_fixture()
            state["push_delivery_records"] = [
                {
                    "id": "old-permanent-record",
                    "source": "system",
                    "kind": "sos",
                    "status": "sent",
                    "created_at": "2020-01-01T00:00:00",
                    "line_user_id": "U1",
                }
            ]
            save_state(data_file, state)

            result, code = cleanup_expired_data(
                {"DATA_FILE": data_file, "CRON_NOW": datetime(2026, 8, 1, 2, 30)}
            )

            self.assertEqual(code, 200)
            self.assertIn("old_notification_logs_removed", result)
            saved = load_state(data_file)
            self.assertEqual(
                [row["id"] for row in saved["push_delivery_records"]],
                ["old-permanent-record"],
            )


if __name__ == "__main__":
    unittest.main()
