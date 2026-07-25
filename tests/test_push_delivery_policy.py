import unittest
import urllib.error
from datetime import datetime
from pathlib import Path
import tempfile

import app as alive_app
from push_delivery import (
    classify_push_exception,
    push_attempt_allowed,
    record_push_failure,
)


class PushDeliveryPolicyTests(unittest.TestCase):
    def test_invalid_target_is_permanent(self):
        exc = urllib.error.HTTPError("https://api.line.me", 400, "bad", {}, None)
        self.addCleanup(exc.close)
        failure = classify_push_exception(exc)
        self.assertEqual(failure.kind, "permanent")

    def test_auth_failure_is_system_configuration(self):
        exc = urllib.error.HTTPError("https://api.line.me", 401, "bad", {}, None)
        self.addCleanup(exc.close)
        self.assertEqual(classify_push_exception(exc).kind, "system")

    def test_rate_limit_and_server_error_are_transient(self):
        e429 = urllib.error.HTTPError(
            "https://api.line.me", 429, "busy", {"Retry-After": "60"}, None
        )
        e503 = urllib.error.HTTPError("https://api.line.me", 503, "down", {}, None)
        self.addCleanup(e503.close)
        self.addCleanup(e429.close)
        self.assertEqual(classify_push_exception(e429).kind, "rate_limited")
        self.assertEqual(classify_push_exception(e429).retry_after_seconds, 60)
        self.assertEqual(classify_push_exception(e503).kind, "transient")

    def test_transient_failure_stops_after_three_attempts_for_same_key(self):
        user = {}
        exc = TimeoutError("LINE timeout")
        for _ in range(3):
            record_push_failure(
                user,
                "checkin:2026-07-26:12:00",
                exc,
                datetime(2026, 7, 26, 12, 1),
            )
        self.assertFalse(
            push_attempt_allowed(user, "checkin:2026-07-26:12:00")
        )
        self.assertTrue(
            push_attempt_allowed(user, "checkin:2026-07-27:12:00")
        )

    def test_permanent_failure_marks_user_blocked(self):
        user = {}
        exc = urllib.error.HTTPError("https://api.line.me", 400, "bad", {}, None)
        self.addCleanup(exc.close)
        result = record_push_failure(user, "birthday:2026-07-26", exc)
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(user["line_push_blocked"])

    def test_checkin_stops_retrying_same_delivery_after_three_failures(self):
        calls = []

        def timeout_sender(token, line_user_id, message):
            calls.append(line_user_id)
            raise TimeoutError("LINE timeout")

        with tempfile.TemporaryDirectory() as tmp:
            data_file = Path(tmp) / "state.json"
            alive_app.save_state(
                data_file,
                {
                    "users": {
                        "U1": {
                            "line_user_id": "U1",
                            "plan": "paid_199",
                            "history": [],
                            "reminder_times": ["12:00"],
                        }
                    }
                },
            )
            config = {
                "DATA_FILE": data_file,
                "LINE_CHANNEL_ACCESS_TOKEN": "token",
                "LINE_PUSH_SENDER": timeout_sender,
                "APP_TIMEZONE": "Asia/Taipei",
                "CRON_NOW": datetime(2026, 7, 26, 12, 1),
            }

            for _ in range(4):
                alive_app.send_checkin_reminders(config)

            profile = alive_app.load_state(data_file)["users"]["U1"]
            self.assertEqual(calls, ["U1", "U1", "U1"])
            self.assertEqual(
                profile["push_delivery_attempts"][
                    "checkin:2026-07-26:12:00"
                ]["count"],
                3,
            )

    def test_checkin_auth_failure_stops_current_task_after_one_user(self):
        calls = []

        def auth_failure_sender(token, line_user_id, message):
            calls.append(line_user_id)
            exc = RuntimeError("bad token")
            exc.status_code = 401
            raise exc

        with tempfile.TemporaryDirectory() as tmp:
            data_file = Path(tmp) / "state.json"
            users = {
                user_id: {
                    "line_user_id": user_id,
                    "plan": "paid_199",
                    "history": [],
                    "reminder_times": ["12:00"],
                }
                for user_id in ("U1", "U2")
            }
            alive_app.save_state(data_file, {"users": users})
            alive_app.send_checkin_reminders(
                {
                    "DATA_FILE": data_file,
                    "LINE_CHANNEL_ACCESS_TOKEN": "bad-token",
                    "LINE_PUSH_SENDER": auth_failure_sender,
                    "APP_TIMEZONE": "Asia/Taipei",
                    "CRON_NOW": datetime(2026, 7, 26, 12, 1),
                }
            )

            state = alive_app.load_state(data_file)
            system_errors = [
                row
                for row in state.get("notification_logs", [])
                if row.get("status") == "system_error"
            ]
            self.assertEqual(calls, ["U1"])
            self.assertEqual(len(system_errors), 1)

    def test_successful_checkin_clears_previous_failure_for_delivery_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_file = Path(tmp) / "state.json"
            delivery_key = "checkin:2026-07-26:12:00"
            alive_app.save_state(
                data_file,
                {
                    "users": {
                        "U1": {
                            "line_user_id": "U1",
                            "plan": "paid_199",
                            "history": [],
                            "reminder_times": ["12:00"],
                            "push_delivery_attempts": {
                                delivery_key: {
                                    "count": 2,
                                    "kind": "transient",
                                }
                            },
                        }
                    }
                },
            )

            alive_app.send_checkin_reminders(
                {
                    "DATA_FILE": data_file,
                    "LINE_CHANNEL_ACCESS_TOKEN": "token",
                    "LINE_PUSH_SENDER": lambda token, user_id, message: {
                        "ok": True
                    },
                    "APP_TIMEZONE": "Asia/Taipei",
                    "CRON_NOW": datetime(2026, 7, 26, 12, 1),
                }
            )

            profile = alive_app.load_state(data_file)["users"]["U1"]
            self.assertNotIn(
                delivery_key, profile.get("push_delivery_attempts", {})
            )


if __name__ == "__main__":
    unittest.main()
