import unittest
from pathlib import Path

import sos_flow
from guardian_group_flex import pricing_direct_url, share_invite_liff_url, welcome_flex


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

    def test_welcome_flex_new_card_two_ctas(self):
        flex = welcome_flex("小明")
        blob = str(flex)
        self.assertIn("👋 小明 您好，歡迎加入「每日平安」", blob)
        self.assertIn("每天 10 秒，報個平安", blob)
        self.assertIn("平常不打擾，有事才通知守護人", blob)
        self.assertIn("① 新增 1 位守護人", blob)
        self.assertIn("② 設定每日提醒時間", blob)
        self.assertIn("7 天免費安心體驗", blob)
        self.assertIn("daily-peace-logo.png", blob)
        self.assertIn("welcome-heart-banner.png", blob)
        self.assertIn("open=onboarding", blob)
        self.assertIn("/liff/pricing.html", blob)
        self.assertNotIn("版本 W", blob)
        self.assertNotIn("W250723", blob)
        self.assertNotIn("BOT", blob)
        self.assertNotIn("一鍵邀請守護人", blob)
        self.assertNotIn("需要幫忙", blob)
        labels = [
            item["action"]["label"]
            for item in (flex.get("footer") or {}).get("contents") or []
            if item.get("type") == "button"
        ]
        self.assertEqual(labels, ["立即開始設定", "查看方案"])
        self.assertEqual(
            pricing_direct_url(),
            "https://alive-checkin.onrender.com/liff/pricing.html",
        )
        self.assertEqual(
            share_invite_liff_url(),
            "https://liff.line.me/2010674803-rK98c0lo/liff/share-invite.html",
        )


if __name__ == "__main__":
    unittest.main()
