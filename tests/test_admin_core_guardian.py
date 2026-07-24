import tempfile
import unittest
from pathlib import Path

from app import admin_set_core_guardian, save_state, trigger_sos


class AdminCoreGuardianTests(unittest.TestCase):
    def make_data_file(self, profile):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        data_file = str(Path(temp_dir.name) / "state.json")
        save_state(data_file, {"users": {profile["line_user_id"]: profile}})
        return data_file

    def test_admin_can_switch_core_guardian(self):
        profile = {
            "line_user_id": "U-owner",
            "display_name": "會員",
            "plan": "paid_799",
            "payment_status": "active",
            "contacts": [
                {
                    "id": "c1",
                    "name": "老大",
                    "line_id": "U-a",
                    "priority": 1,
                    "is_primary": True,
                    "binding_status": "accepted",
                    "notify_methods": ["line"],
                },
                {
                    "id": "c2",
                    "name": "老二",
                    "line_id": "U-b",
                    "priority": 2,
                    "is_primary": False,
                    "binding_status": "accepted",
                    "notify_methods": ["line"],
                },
            ],
        }
        data_file = self.make_data_file(profile)
        result, status = admin_set_core_guardian(data_file, {
            "line_user_id": "U-owner",
            "contact_id": "c2",
            "is_primary": True,
        })
        self.assertEqual(status, 200)
        self.assertTrue(result["ok"])
        contacts = {c["id"]: c for c in result["contacts"]}
        self.assertTrue(contacts["c2"]["is_primary"])

    def test_free_plan_sos_prefers_core_guardian(self):
        messages = []
        profile = {
            "line_user_id": "U-free",
            "display_name": "免費",
            "plan": "free",
            "contacts": [
                {
                    "id": "c1",
                    "name": "一般",
                    "line_id": "U-general",
                    "priority": 1,
                    "is_primary": False,
                    "notify_methods": ["line"],
                },
                {
                    "id": "c2",
                    "name": "核心",
                    "line_id": "U-core",
                    "priority": 2,
                    "is_primary": True,
                    "notify_methods": ["line"],
                },
            ],
        }
        data_file = self.make_data_file(profile)
        result, status = trigger_sos(data_file, {"line_user_id": "U-free"}, {
            "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
            "LINE_PUSH_SENDER": lambda _token, target, message: messages.append(target) or {"ok": True},
        })
        self.assertEqual(status, 200)
        self.assertEqual(result["sent"], 1)
        self.assertEqual(messages, ["U-core"])


if __name__ == "__main__":
    unittest.main()
