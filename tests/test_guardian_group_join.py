import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app import guardian_group_join_outcome, save_state


class GuardianGroupJoinTests(unittest.TestCase):
    def make_data_file(self, profile=None):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        data_file = str(Path(temp_dir.name) / "state.json")
        users = {profile["line_user_id"]: profile} if profile else {}
        save_state(data_file, {"users": users})
        return data_file

    def test_active_799_member_is_bound_when_bot_joins_group(self):
        profile = {
            "line_user_id": "U-owner",
            "display_name": "測試會員",
            "plan": "paid_799",
            "payment_status": "active",
            "paid_until": (datetime.now() + timedelta(days=30)).isoformat(timespec="seconds"),
        }
        data_file = self.make_data_file(profile)

        outcome, status = guardian_group_join_outcome(data_file, "U-owner", "G-family")

        self.assertEqual(status, 200)
        self.assertFalse(outcome["should_leave"])
        self.assertIn("守護群", outcome["reply_text"])

    def test_unknown_inviter_is_rejected_and_bot_leaves_group(self):
        data_file = self.make_data_file()

        outcome, status = guardian_group_join_outcome(data_file, None, "G-unknown")

        self.assertEqual(status, 400)
        self.assertTrue(outcome["should_leave"])
        self.assertIn("無法確認邀請人的會員身分", outcome["reply_text"])

    def test_callback_registers_join_event_handler(self):
        source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")

        self.assertIn("JoinEvent", source)
        self.assertIn("@handler.add(JoinEvent)", source)
        self.assertIn("guardian_group_join_outcome", source)


if __name__ == "__main__":
    unittest.main()
