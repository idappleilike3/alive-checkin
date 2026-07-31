from pathlib import Path
import unittest


HTML = (
    Path(__file__).resolve().parents[1] / "liff" / "onboarding.html"
).read_text(encoding="utf-8")


class InlineFriendshipTests(unittest.TestCase):
    def test_non_friend_is_prompted_inside_full_size_liff_before_external_fallback(self):
        self.assertIn("liff.requestFriendship", HTML)
        self.assertIn("await liff.getFriendship()", HTML)
        self.assertIn('href="https://line.me/R/ti/p/%40042kwqib"', HTML)
        self.assertIn("requestFriendship", HTML.split("renderFriendshipEntry", 1)[1])

    def test_inline_friendship_continues_onboarding_without_second_click(self):
        self.assertIn("async function requestOfficialAccountFriendship()", HTML)
        self.assertIn("await liff.requestFriendship()", HTML)
        self.assertIn("await continueAfterFriendshipCheck()", HTML)

    def test_inline_friendship_has_clear_retry_and_external_fallback(self):
        self.assertIn('id="requestOfficialAccountFriendship"', HTML)
        self.assertIn("無法顯示 LINE 加好友視窗", HTML)
        self.assertIn("改用 LINE 官方加好友頁", HTML)


if __name__ == "__main__":
    unittest.main()
