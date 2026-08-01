from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class TrialPeaceExperienceTest(unittest.TestCase):
    def test_public_trial_page_is_a_price_free_peace_experience(self):
        html = _read("trial-14.html")

        self.assertIn("14 天安心體驗", html)
        self.assertNotIn("199 平安版", html)
        self.assertNotIn("NT$", html)
        self.assertNotIn("月費", html)
        self.assertNotIn("年費", html)
        self.assertNotIn("體驗後可續用的正式方案", html)

    def test_both_trial_pages_show_three_visual_benefits(self):
        for relative_path in ("trial-14.html", "liff/onboarding.html"):
            html = _read(relative_path)
            self.assertIn("每日提醒", html)
            self.assertIn("多位守護人", html)
            self.assertIn("SOS 緊急求助", html)

    def test_both_trial_pages_use_the_confirmed_conversational_steps(self):
        for relative_path in ("trial-14.html", "liff/onboarding.html"):
            html = _read(relative_path)
            labels = [
                "填寫邀請人資料",
                "設定提醒時間",
                "邀請守護人",
                "安心連結建立",
            ]
            positions = [html.index(label) for label in labels]
            self.assertEqual(positions, sorted(positions))
            self.assertIn("讓守護人知道你是誰", html)
            self.assertIn("可事後填寫，SOS 時可用來緊急聯絡", html)
            self.assertIn("對方接受後，安心連結就建立了", html)

    def test_trial_actions_have_share_icon_and_large_final_cta(self):
        public_html = _read("trial-14.html")
        onboarding_html = _read("liff/onboarding.html")

        for html in (public_html, onboarding_html):
            self.assertIn('aria-hidden="true">↗</span>', html)
            self.assertIn("開始 14 天安心體驗", html)
            self.assertIn("peace-trial-cta", html)

    def test_onboarding_experience_copy_does_not_name_the_199_plan(self):
        html = _read("liff/onboarding.html")

        self.assertNotIn("14 天免費體驗｜199 平安版", html)
        self.assertIn("14 天安心體驗", html)


if __name__ == "__main__":
    unittest.main()
