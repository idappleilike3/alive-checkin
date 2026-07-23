import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app import save_state, sos_user_facing_error, trigger_sos


class SosRulesTests(unittest.TestCase):
    def make_data_file(self, profile, extra_state=None):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        data_file = str(Path(temp_dir.name) / "state.json")
        state = {"users": {profile["line_user_id"]: profile}}
        if extra_state:
            state.update(extra_state)
        save_state(data_file, state)
        return data_file

    def test_expired_membership_can_still_send_sos(self):
        """SOS 不依方案／價格：過期付費會員仍可送出（仍受每日上限／冷卻限制）。"""
        messages = []
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
            "LINE_PUSH_SENDER": lambda _token, _target, message: messages.append(message) or {"ok": True},
        })

        self.assertEqual(status, 200)
        self.assertEqual(result["sent"], 1)
        self.assertEqual(len(messages), 1)

    def test_free_plan_can_send_sos(self):
        messages = []
        profile = {
            "line_user_id": "U-free",
            "display_name": "免費會員",
            "plan": "free",
            "contacts": [{"line_id": "U-guardian", "priority": 1, "notify_methods": ["line"]}],
        }
        data_file = self.make_data_file(profile)

        result, status = trigger_sos(data_file, {"line_user_id": "U-free"}, {
            "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
            "LINE_PUSH_SENDER": lambda _token, _target, message: messages.append(message) or {"ok": True},
        })

        self.assertEqual(status, 200)
        self.assertEqual(result["sent"], 1)

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

    def test_no_guardians_returns_api_error_code(self):
        profile = {
            "line_user_id": "U-alone",
            "display_name": "單身會員",
            "plan": "paid_799",
            "payment_status": "active",
            "contacts": [],
        }
        data_file = self.make_data_file(profile)
        result, status = trigger_sos(data_file, {"line_user_id": "U-alone"}, {
            "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
            "LINE_PUSH_SENDER": lambda *_args: {"ok": True},
        })
        self.assertEqual(status, 400)
        self.assertEqual(result["error"], "no bound LINE guardians")

    def test_guardian_group_only_can_send_sos(self):
        messages = []
        profile = {
            "line_user_id": "U-owner",
            "display_name": "有群沒人",
            "plan": "paid_799",
            "payment_status": "active",
            "paid_until": (datetime.now() + timedelta(days=30)).isoformat(timespec="seconds"),
            "contacts": [],
            "guardian_group_ids": ["C-group"],
        }
        data_file = self.make_data_file(profile, {
            "guardian_groups": {
                "C-group": {
                    "owner_line_user_id": "U-owner",
                    "status": "active",
                    "preferences": {"notify_group_on_overdue": True},
                }
            }
        })
        result, status = trigger_sos(data_file, {"line_user_id": "U-owner"}, {
            "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
            "LINE_PUSH_SENDER": lambda _token, target, message: messages.append((target, message)) or {"ok": True},
        })
        self.assertEqual(status, 200)
        self.assertEqual(result["sent"], 1)
        self.assertEqual(result["group_sent"], 1)
        self.assertEqual(messages[0][0], "C-group")

    def test_user_facing_error_hides_english(self):
        msg = sos_user_facing_error("no bound LINE guardians")
        self.assertIn("還沒綁定守護人喔", msg)
        self.assertNotIn("no bound", msg.lower())
        self.assertNotIn("LINE guardians", msg)
        self.assertFalse(msg.endswith("。"))


if __name__ == "__main__":
    unittest.main()
