import re
import unittest
from pathlib import Path


HTML = (Path(__file__).parents[1] / "liff" / "onboarding.html").read_text(
    encoding="utf-8"
)


class OnboardingBrandHeaderTest(unittest.TestCase):
    def test_logo_brand_and_trial_title_share_one_header(self):
        header = re.search(
            r'<header class="onboarding-brand-header".*?</header>',
            HTML,
            re.DOTALL,
        )
        self.assertIsNotNone(header)
        markup = header.group(0)
        self.assertIn('src="/assets/daily-peace-logo.png"', markup)
        self.assertIn("每日平安", markup)
        self.assertIn("14 天安心體驗", markup)

    def test_header_uses_a_single_flex_row(self):
        self.assertRegex(
            HTML,
            r"\.onboarding-brand-header\s*\{[^}]*display:\s*flex;"
            r"[^}]*align-items:\s*center;",
        )
        self.assertRegex(
            HTML,
            r"\.onboarding-brand-header\s*\{[^}]*flex-wrap:\s*nowrap;",
        )

    def test_footer_keeps_three_requested_buttons(self):
        footer = re.search(
            r'<nav id="onboardingFooterActions".*?</nav>',
            HTML,
            re.DOTALL,
        )
        self.assertIsNotNone(footer)
        markup = footer.group(0)
        self.assertIn(">返回首頁</a>", markup)
        self.assertIn(">查看體驗與方案</a>", markup)
        self.assertIn(">常見問題</a>", markup)


if __name__ == "__main__":
    unittest.main()
