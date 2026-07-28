from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PAGES = ("beta-register.html", "trial-14.html", "invite.html")


class CheckinDemoCardTests(unittest.TestCase):
    def test_all_four_landing_routes_use_the_new_checkin_success_card(self):
        for file_name in PAGES:
            with self.subTest(file_name=file_name):
                html = (ROOT / file_name).read_text(encoding="utf-8")
                for copy in (
                    "報平安成功",
                    "女兒已收到「今天平安」通知",
                    "一鍵完成",
                    "不用每天打字",
                    "適時提醒",
                    "忘記才通知",
                    "需要時求救",
                    "SOS 快速聯絡",
                ):
                    self.assertIn(copy, html)

    def test_checkin_result_stays_hidden_until_the_user_taps(self):
        for file_name in PAGES:
            with self.subTest(file_name=file_name):
                html = (ROOT / file_name).read_text(encoding="utf-8")
                self.assertTrue(
                    "demo-live-result" in html or 'id="demoResult"' in html
                )
                self.assertIn("hidden", html)
                self.assertNotIn("今天是 7/28（二）", html)
                self.assertNotIn("報到時間 15:59", html)
                self.assertNotIn("願你出門順利、回家平安", html)
                self.assertNotIn("下次提醒 7/28（二） 12:00", html)

    def test_checkin_button_has_an_animated_finger_and_share_action(self):
        for file_name in PAGES:
            with self.subTest(file_name=file_name):
                html = (ROOT / file_name).read_text(encoding="utf-8")
                self.assertIn("tap-hand", html)
                self.assertIn("@keyframes tapHint", html)
                self.assertIn("一鍵分享", html)


if __name__ == "__main__":
    unittest.main()
