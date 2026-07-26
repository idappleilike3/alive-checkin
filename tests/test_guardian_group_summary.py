from datetime import datetime
from pathlib import Path
import tempfile
import unittest

import app


class GuardianGroupSummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_file = Path(self.tmp.name) / "state.json"

    def tearDown(self):
        self.tmp.cleanup()

    def save_group(self, preferences, member_ids_at_bind=None):
        app.save_state(self.data_file, {
            "users": {
                "U-owner": {
                    "line_user_id": "U-owner",
                    "display_name": "本人",
                    "history": ["2026-07-27"],
                },
                "U-active": {
                    "line_user_id": "U-active",
                    "display_name": "有效成員",
                    "history": [],
                },
                "U-removed": {
                    "line_user_id": "U-removed",
                    "display_name": "已退出成員",
                    "history": [],
                },
            },
            "guardian_groups": {
                "C-group": {
                    "group_id": "C-group",
                    "owner_line_user_id": "U-owner",
                    "status": "active",
                    "member_ids_at_bind": member_ids_at_bind or ["U-active", "U-removed"],
                    "preferences": preferences,
                },
            },
        })

    def config(self, sender, now, fetcher):
        return {
            "DATA_FILE": self.data_file,
            "LINE_CHANNEL_ACCESS_TOKEN": "token",
            "LINE_PUSH_SENDER": sender,
            "GROUP_MEMBER_IDS_FETCHER": fetcher,
            "CRON_NOW": now,
        }

    def test_summary_is_off_by_default(self):
        self.save_group({})
        sent = []
        result, code = app.send_guardian_group_daily_summaries(
            self.config(lambda *_args: sent.append(True), datetime(2026, 7, 27, 21, 0), lambda *_args: ["U-active"])
        )
        self.assertEqual(code, 200)
        self.assertEqual(result["sent"], 0)
        self.assertEqual(sent, [])

    def test_custom_summary_time_defers_until_configured_minute(self):
        self.save_group({"daily_admin_summary": True, "daily_summary_time": "22:30"})
        result, code = app.send_guardian_group_daily_summaries(
            self.config(lambda *_args: {"ok": True}, datetime(2026, 7, 27, 22, 29), lambda *_args: ["U-active"])
        )
        self.assertEqual(code, 200)
        self.assertEqual(result["sent"], 0)
        self.assertEqual(result["deferred"], 1)

    def test_summary_recomputes_members_and_excludes_removed_snapshot_member(self):
        self.save_group({"daily_admin_summary": True, "daily_summary_time": "21:00"})
        messages = []
        result, code = app.send_guardian_group_daily_summaries(
            self.config(
                lambda _token, _group, message: messages.append(message) or {"ok": True},
                datetime(2026, 7, 27, 21, 0),
                lambda _token, _group: ["U-owner", "U-active"],
            )
        )
        self.assertEqual(code, 200)
        self.assertEqual(result["sent"], 1)
        self.assertIn("有效成員", messages[0])
        self.assertNotIn("已退出成員", messages[0])
        stored = app.load_state(self.data_file)["guardian_groups"]["C-group"]
        self.assertEqual(stored["member_ids_last_summary"], ["U-owner", "U-active"])


if __name__ == "__main__":
    unittest.main()
