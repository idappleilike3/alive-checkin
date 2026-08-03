import tempfile
import unittest
from pathlib import Path

import app as alive_app


class AdminPersonalizedCardPushTests(unittest.TestCase):
    def setUp(self):
        alive_app.ADMIN_LOGIN_ATTEMPTS.clear()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_file = str(Path(self.temp_dir.name) / "state.json")
        self.sent = []
        self.config = {
            "DATA_FILE": self.data_file,
            "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
            "LINE_PUSH_SENDER": lambda token, uid, message: self.sent.append((uid, message)) or {"ok": True},
        }
        state = alive_app.load_state(self.data_file)
        state["users"] = {
            "U" + "a" * 32: {
                **alive_app.DEFAULT_PROFILE,
                "line_user_id": "U" + "a" * 32,
                "display_name": "寶寶",
                "plan": "paid_799",
                "payment_status": "active",
                "membership_source": "paid",
                "history": ["2026-08-02"],
            },
            "U" + "b" * 32: {
                **alive_app.DEFAULT_PROFILE,
                "line_user_id": "U" + "b" * 32,
                "display_name": "失敗舊帳號",
                "plan": "paid_799",
                "payment_status": "active",
                "membership_source": "paid",
                "line_push_blocked": True,
            },
        }
        alive_app.save_state(self.data_file, state)
    def test_preview_lists_only_eligible_members_without_sending(self):
        data = alive_app.personalized_checkin_push_preview(self.data_file)
        self.assertEqual(data["eligible_count"], 1)
        self.assertEqual(data["members"][0]["display_name"], "寶寶")
        self.assertTrue(data["members"][0]["masked_line_user_id"].endswith("aaaa"))
        self.assertEqual(self.sent, [])

    def test_send_all_requires_explicit_confirmation(self):
        data, status = alive_app.admin_send_personalized_checkin_cards(
            self.config, mode="all", confirmed=False
        )
        self.assertEqual(status, 409)
        self.assertEqual(data["error"], "confirmation_required")
        self.assertEqual(self.sent, [])

    def test_single_send_targets_only_selected_active_member(self):
        uid = "U" + "a" * 32
        data, status = alive_app.admin_send_personalized_checkin_cards(
            self.config, mode="single", line_user_id=uid, confirmed=True
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["sent"], 1)
        self.assertEqual([row[0] for row in self.sent], [uid])
        self.assertEqual(self.sent[0][1]["type"], "flex")

    def test_admin_page_exposes_preview_and_confirmed_send_controls(self):
        html = Path("admin.html").read_text(encoding="utf-8")
        source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn("全部會員新版圖片卡測試", html)
        self.assertIn("指定單一會員立即發", html)
        self.assertIn("personalized-checkin-push/preview", html)
        self.assertIn("personalized-checkin-push/send", html)
        self.assertIn('@app.get("/api/admin/personalized-checkin-push/preview")', source)
        self.assertIn('@app.post("/api/admin/personalized-checkin-push/send")', source)


if __name__ == "__main__":
    unittest.main()
