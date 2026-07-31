from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class UidContinuousEntryFlowTests(unittest.TestCase):
    def test_trial_onboarding_starts_line_login_and_returns_to_same_flow(self):
        html = (ROOT / "liff" / "onboarding.html").read_text(encoding="utf-8")

        self.assertIn("function buildOnboardingLoginRedirect()", html)
        self.assertIn("liff.login({ redirectUri: buildOnboardingLoginRedirect() })", html)
        self.assertIn("resumeTrialAfterFriendship", html)
        self.assertIn('document.addEventListener("visibilitychange"', html)
        self.assertNotIn("加入官方 LINE 後，請回到這個頁面", html)
        self.assertNotIn("請先使用上方按鈕加入官方 LINE，再點", html)

    def test_trial_public_page_has_one_continuous_primary_action(self):
        html = (ROOT / "trial-14.html").read_text(encoding="utf-8")

        self.assertIn("加入官方 LINE 並開始填寫資料", html)
        self.assertIn("取得 LINE UID 後會直接繼續", html)
        self.assertNotIn("先加入官方 LINE，再回到本頁", html)

    def test_logged_in_uid_skips_the_second_login_button(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn("resumeLineEntryWhenVisible", html)
        self.assertIn('document.addEventListener("visibilitychange"', html)


if __name__ == "__main__":
    unittest.main()
