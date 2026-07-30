import re
import unittest
from pathlib import Path


HTML = (Path(__file__).parents[1] / "liff" / "onboarding.html").read_text(
    encoding="utf-8"
)


class OnboardingFooterActionsTest(unittest.TestCase):
    def test_navigation_is_persistent_below_dynamic_onboarding_content(self):
        content_end = HTML.index("</div>", HTML.index('id="content"'))
        footer_start = HTML.index('id="onboardingFooterActions"')
        script_start = HTML.index("<script>")

        self.assertLess(content_end, footer_start)
        self.assertLess(footer_start, script_start)

    def test_footer_has_the_three_requested_destinations(self):
        footer = re.search(
            r'<nav id="onboardingFooterActions".*?</nav>', HTML, re.DOTALL
        )
        self.assertIsNotNone(footer)
        markup = footer.group(0)
        self.assertIn('href="/"', markup)
        self.assertIn(">返回首頁</a>", markup)
        self.assertIn('href="/trial-14.html"', markup)
        self.assertIn(">查看體驗與方案</a>", markup)
        self.assertIn('href="/faq.html"', markup)
        self.assertIn(">常見問題</a>", markup)

    def test_footer_buttons_stay_in_one_row_on_mobile(self):
        self.assertIn(
            ".onboarding-footer-links {", HTML
        )
        self.assertRegex(
            HTML,
            r"\.onboarding-footer-links\s*\{[^}]*"
            r"grid-template-columns:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\)",
        )


if __name__ == "__main__":
    unittest.main()
