import unittest
from pathlib import Path

import sos_flow
from guardian_group_flex import welcome_flex


ROOT = Path(__file__).resolve().parents[1]


class BotKeywordHandlerTests(unittest.TestCase):
    def test_app_registers_welcome_and_sos_keywords(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('"開始", "歡迎", "說明", "歡迎詞"', source)
        self.assertIn('"需要幫忙"', source)
        self.assertIn('"緊急求助"', source)
        self.assertIn('"通知家人"', source)
        self.assertIn("sos_emergency_flex", source)
        self.assertIn("_send_welcome", source)

    def test_sos_emergency_flex_has_dials_and_notify(self):
        flex = sos_flow.sos_emergency_flex(family_tel="0912345678", family_label="媽媽")
        blob = str(flex)
        self.assertIn("tel:119", blob)
        self.assertIn("tel:110", blob)
        self.assertIn("tel:0912345678", blob)
        self.assertIn("通知家人", blob)
        self.assertIn("需要幫忙", blob)

    def test_welcome_flex_version_stamp(self):
        flex = welcome_flex("小明")
        blob = str(flex)
        self.assertIn("W250723g", blob)
        self.assertIn("歡迎加入每日平安", blob)
        self.assertIn("每天10秒報平安", blob)
        self.assertNotIn("BOT", blob)


if __name__ == "__main__":
    unittest.main()
