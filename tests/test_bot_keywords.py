import unittest
from pathlib import Path

import sos_flow
from guardian_group_flex import share_invite_liff_url, welcome_flex


ROOT = Path(__file__).resolve().parents[1]


class BotKeywordHandlerTests(unittest.TestCase):
    def test_app_registers_welcome_and_sos_keywords(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('"開始", "歡迎", "說明", "歡迎詞"', source)
        self.assertIn('"需要幫忙"', source)
        self.assertIn('"緊急求助"', source)
        self.assertIn('"通知家人"', source)
        self.assertIn('"聯絡家人連按3次"', source)
        self.assertIn("sos_emergency_flex", source)
        self.assertIn("_send_welcome", source)

    def test_sos_emergency_flex_has_dials_and_notify(self):
        flex = sos_flow.sos_emergency_flex(family_tel="0912345678", family_label="媽媽")
        blob = str(flex)
        self.assertIn("tel:119", blob)
        self.assertIn("tel:110", blob)
        self.assertIn("聯絡家人連按3次", blob)
        self.assertIn("需要幫忙", blob)
        self.assertNotIn("開啟完整求助頁", blob)
        self.assertNotIn("通知家人連按3次", blob)
        # 119／110 不可再做成跟主按鈕同等級的 primary 大按鈕堆
        footer = flex.get("footer", {}).get("contents", [])
        primary_buttons = [
            item for item in footer
            if item.get("type") == "button" and item.get("style") == "primary"
        ]
        self.assertEqual(len(primary_buttons), 1)
        self.assertEqual(primary_buttons[0]["action"]["label"], "聯絡家人連按3次")

    def test_sos_no_guardians_flex_has_invite(self):
        flex = sos_flow.sos_no_guardians_flex("https://liff.line.me/2010674803-rK98c0lo/liff/share-invite.html")
        blob = str(flex)
        self.assertIn("還沒綁定守護人喔", blob)
        self.assertIn("邀請家人加入", blob)
        self.assertIn("share-invite.html", blob)
        self.assertNotIn("no bound", blob.lower())

    def test_welcome_flex_no_version_stamp_and_direct_share_uri(self):
        flex = welcome_flex("小明")
        blob = str(flex)
        self.assertIn("❤️ 今天還在嗎", blob)
        self.assertIn("歡迎加入「今天還在嗎」", blob)
        self.assertIn("完成設定即享 7 天免費安心體驗", blob)
        self.assertIn("/liff/share-invite.html", blob)
        self.assertNotIn("版本 W", blob)
        self.assertNotIn("W250723", blob)
        self.assertNotIn("BOT", blob)
        self.assertEqual(
            share_invite_liff_url(),
            "https://liff.line.me/2010674803-rK98c0lo/liff/share-invite.html",
        )


if __name__ == "__main__":
    unittest.main()
