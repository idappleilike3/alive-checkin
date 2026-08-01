import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import app as app_module


class SosMembershipDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.fromisoformat("2026-08-02T12:00:00+08:00")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_file = str(Path(self.temp_dir.name) / "state.json")

    def save_profile(self, plan="free", with_guardian=True, **updates):
        contacts = [{
            "id": "g1", "name": "女兒", "line_id": "U-guardian",
            "line_user_id": "U-guardian", "is_primary": True, "priority": 1,
            "binding_status": "accepted", "notify_methods": ["line"],
        }] if with_guardian else []
        profile = {
            "line_user_id": "U-owner", "display_name": "媽媽",
            "plan": plan, "contacts": contacts, **updates,
        }
        users = {"U-owner": profile}
        if contacts:
            users["U-guardian"] = {
                "line_user_id": "U-guardian", "display_name": "女兒",
                "guarding_for": ["U-owner"],
                "guarding_details": [{"line_user_id": "U-owner", "display_name": "媽媽"}],
            }
        app_module.save_state(self.data_file, {"users": users})

    def trigger(self):
        line_calls, sms_calls = [], []
        result, status = app_module.trigger_sos(
            self.data_file,
            {"line_user_id": "U-owner"},
            {
                "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
                "LINE_PUSH_SENDER": lambda *_args, **_kwargs: line_calls.append(_args) or {"ok": True},
                "SMS_SENDER": lambda *_args, **_kwargs: sms_calls.append(_args) or {"ok": True},
            },
        )
        return result, status, line_calls, sms_calls

    def test_free_with_guardian_creates_web_alert_without_push(self):
        self.save_profile()
        result, status, line_calls, sms_calls = self.trigger()
        self.assertEqual(status, 200)
        self.assertEqual(result["delivery_mode"], "web_only")
        self.assertTrue(result["has_bound_guardian"])
        self.assertIn("主動打開每日平安網頁", result["message"])
        self.assertEqual(line_calls, [])
        self.assertEqual(sms_calls, [])
        state = app_module.load_state(self.data_file)
        event = state["sos_events"][result["event_id"]]
        self.assertEqual(event["status"], "web_pending")
        self.assertEqual(state.get("notification_logs") or [], [])

    def test_free_without_guardian_explains_that_no_one_can_view(self):
        self.save_profile(with_guardian=False)
        result, status, line_calls, sms_calls = self.trigger()
        self.assertEqual(status, 200)
        self.assertFalse(result["has_bound_guardian"])
        self.assertIn("尚未綁定守護人", result["message"])
        self.assertIn("無人可以查看", result["message"])
        self.assertEqual(line_calls + sms_calls, [])

    def test_active_trial_and_paid_plans_keep_immediate_line_delivery(self):
        cases = [
            ("trial", {
                "membership_source": "public_trial",
                "trial_started_at": (self.now - timedelta(days=1)).isoformat(),
                "trial_end": (self.now + timedelta(days=13)).isoformat(),
            }),
            ("paid_199", {"paid_until": (self.now + timedelta(days=30)).isoformat()}),
            ("paid_399", {"paid_until": (self.now + timedelta(days=30)).isoformat()}),
            ("paid_799", {"paid_until": (self.now + timedelta(days=30)).isoformat()}),
        ]
        for plan, fields in cases:
            with self.subTest(plan=plan):
                self.save_profile(plan=plan, **fields)
                result, status, line_calls, _sms_calls = self.trigger()
                self.assertEqual(status, 200)
                self.assertNotEqual(result.get("delivery_mode"), "web_only")
                self.assertGreaterEqual(len(line_calls), 1)

    def test_expired_trial_and_paid_plan_use_web_only_delivery(self):
        cases = [
            ("trial", {
                "membership_source": "public_trial",
                "trial_started_at": (self.now - timedelta(days=15)).isoformat(),
                "trial_end": (self.now - timedelta(days=1)).isoformat(),
            }),
            ("paid_799", {"paid_until": (self.now - timedelta(days=1)).isoformat()}),
        ]
        for plan, fields in cases:
            with self.subTest(plan=plan):
                self.save_profile(plan=plan, **fields)
                result, status, line_calls, sms_calls = self.trigger()
                self.assertEqual(status, 200)
                self.assertEqual(result["delivery_mode"], "web_only")
                self.assertEqual(line_calls + sms_calls, [])

    def test_guardian_status_exposes_web_alert_text_and_time(self):
        self.save_profile()
        result, status, _line_calls, _sms_calls = self.trigger()
        self.assertEqual(status, 200)
        state = app_module.load_state(self.data_file)
        snapshot = app_module.build_status(
            state["users"]["U-guardian"], state=state, now=self.now
        )
        detail = snapshot["guarding_details"][0]
        self.assertEqual(detail["latest_sos_status"], "web_pending")
        self.assertEqual(detail["latest_sos_message"], "您的家人 媽媽 剛剛發出了求救訊號。")
        self.assertTrue(detail["latest_sos_created_at"])


if __name__ == "__main__":
    unittest.main()
