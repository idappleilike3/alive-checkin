import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import app as alive_app


class AdminPersonalizedCardEditorTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_file = str(Path(self.temp_dir.name) / "state.json")
        state = alive_app.load_state(self.data_file)
        self.uid = "U" + "a" * 32
        state["users"] = {self.uid: {
            **alive_app.DEFAULT_PROFILE,
            "line_user_id": self.uid,
            "display_name": "寶寶",
            "plan": "paid_799",
            "payment_status": "active",
            "membership_source": "paid",
            "history": ["2026-08-02"],
        }}
        alive_app.save_state(self.data_file, state)

    def test_default_template_is_available_and_logo_is_fixed(self):
        templates = alive_app.list_card_templates(alive_app.load_state(self.data_file))
        self.assertEqual(templates[0]["id"], "daily-peace-default")
        self.assertTrue(templates[0]["system"])
        self.assertEqual(templates[0]["logo_url"], alive_app.DAILY_PEACE_LOGO_URL)
        self.assertEqual(len(templates[0]["buttons"]), 5)
        self.assertEqual(templates[0]["buttons"][4]["label"], "邀請親友成為守護人")
        self.assertTrue(templates[0]["buttons"][4]["uri"].endswith("/liff/share-invite.html"))

    def test_template_rejects_non_https_image_and_button_urls(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            alive_app.save_card_template(self.data_file, {
                "name": "不安全卡片", "blessing": "平安",
                "hero_url": "javascript:alert(1)",
                "buttons": [{"label": "開啟", "uri": "http://example.com"}],
            })

    def test_custom_template_persists_without_member_data(self):
        saved = alive_app.save_card_template(self.data_file, {
            "name": "父親節", "blessing": "父親節快樂",
            "hero_url": "https://example.com/father.webp",
            "blessing_style": {
                "font_family": "rounded",
                "color": "#FFF4C2",
                "size": 34,
                "align": "center",
                "position": "top",
            },
            "buttons": [{"label": "我平安", "action": "checkin"}],
        })
        self.assertEqual(saved["name"], "父親節")
        self.assertNotIn("display_name", saved)
        self.assertEqual(saved["blessing_style"]["font_family"], "rounded")
        self.assertEqual(saved["blessing_style"]["color"], "#FFF4C2")
        self.assertEqual(saved["blessing_style"]["size"], 34)
        self.assertEqual(saved["blessing_style"]["align"], "center")
        self.assertEqual(saved["blessing_style"]["position"], "top")
        self.assertEqual(len(alive_app.list_card_templates(alive_app.load_state(self.data_file))), 2)

    def test_template_rejects_unsafe_blessing_style(self):
        with self.assertRaisesRegex(ValueError, "祝福語顏色"):
            alive_app.save_card_template(self.data_file, {
                "name": "不安全樣式", "blessing": "平安",
                "hero_url": "https://example.com/card.webp",
                "blessing_style": {"color": "url(javascript:alert(1))"},
                "buttons": [{"label": "我平安", "action": "checkin"}],
            })

    def test_preview_uses_real_member_and_does_not_send(self):
        now = datetime(2026, 8, 3, 12, 0)
        result = alive_app.preview_personalized_card(
            self.data_file, self.uid, "daily-peace-default",
            now=now,
        )
        self.assertEqual(result["member"]["display_name"], "寶寶")
        self.assertEqual(result["message"]["type"], "flex")
        self.assertEqual(
            result["message"],
            alive_app.build_daily_checkin_flex(now, profile=alive_app.load_state(self.data_file)["users"][self.uid]),
        )
        self.assertEqual(result["message"]["contents"]["hero"]["aspectRatio"], "16:9")
        self.assertEqual(result["message"]["contents"]["hero"]["aspectMode"], "fit")

    def test_confirmed_send_uses_selected_custom_template(self):
        template = alive_app.save_card_template(self.data_file, {
            "name": "中秋卡", "blessing": "月圓人團圓",
            "hero_url": "https://example.com/moon.webp",
            "buttons": [{"label": "我平安", "action": "checkin"}],
        })
        sent = []
        data, status = alive_app.admin_send_personalized_checkin_cards(
            {"DATA_FILE": self.data_file, "LINE_CHANNEL_ACCESS_TOKEN": "test", "LINE_PUSH_SENDER": lambda token, uid, message: sent.append(message)},
            mode="single", line_user_id=self.uid, confirmed=True, template_id=template["id"], now=datetime(2026, 8, 3, 12, 0),
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["sent"], 1)
        self.assertEqual(sent[0]["contents"]["hero"]["url"], "https://example.com/moon.webp")


if __name__ == "__main__":
    unittest.main()
