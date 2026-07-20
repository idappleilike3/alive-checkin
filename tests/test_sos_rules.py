import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app import save_state, trigger_sos


class SosRulesTests(unittest.TestCase):
    def make_data_file(self, profile):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        data_file = str(Path(temp_dir.name) / "state.json")
        save_state(data_file, {"users": {profile["line_user_id"]: profile}})
        return data_file

    def test_expired_799_membership_cannot_send_sos(self):
        profile = {
            "line_user_id": "U-owner",
            "display_name": "測試會員",
            "plan": "paid_799",
            "payment_status": "active",
            "paid_until": (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds"),
            "contacts": [{"line_id": "U-guardian", "priority": 1, "notify_methods": ["line"]}],
        }
        data_file = self.make_data_file(profile)

        result, status = trigger_sos(data_file, {"line_user_id": "U-owner"}, {
            "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
            "LINE_PUSH_SENDER": lambda *_: {"ok": True},
        })

        self.assertEqual(status, 403)
        self.assertEqual(result["error"], "sos membership is not active")

    def test_active_799_sends_clear_message_without_fake_cancel_code(self):
        messages = []
        profile = {
            "line_user_id": "U-owner",
            "display_name": "小美",
            "plan": "paid_799",
            "payment_status": "active",
            "paid_until": (datetime.now() + timedelta(days=30)).isoformat(timespec="seconds"),
            "contacts": [{"line_id": "U-guardian", "priority": 1, "notify_methods": ["line"]}],
            "location": {"latitude": 25.033, "longitude": 121.5654, "city": "台北市"},
        }
        data_file = self.make_data_file(profile)

        result, status = trigger_sos(data_file, {"line_user_id": "U-owner"}, {
            "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
            "LINE_PUSH_SENDER": lambda _token, _target, message: messages.append(message) or {"ok": True},
        })

        self.assertEqual(status, 200)
        self.assertEqual(result["sent"], 1)
        self.assertTrue(result["location_attached"])
        self.assertNotIn("取消碼", messages[0])
        self.assertIn("本通知不會自動聯絡警消", messages[0])


if __name__ == "__main__":
    unittest.main()
