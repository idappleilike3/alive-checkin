import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ThemeOptionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_only_classic_and_cute_are_offered(self):
        themes = re.findall(r'data-theme="([^"]+)"', self.page)

        self.assertEqual(themes, ["classic", "cute"])
        self.assertNotIn("霓虹", self.page)

    def test_removed_or_unknown_preference_falls_back_to_classic(self):
        self.assertIn('const supportedThemes = new Set(["classic", "cute"]);', self.page)
        self.assertIn(
            'const safeTheme = supportedThemes.has(theme) ? theme : "classic";',
            self.page,
        )
        self.assertIn('localStorage.setItem("preferred_theme", safeTheme);', self.page)

    def test_neon_styles_are_removed(self):
        self.assertNotIn("body.neon", self.page)

    def test_cute_primary_surfaces_use_the_pink_palette(self):
        expected_rules = [
            "body.cute .mvp-home .countdown-block",
            "body.cute .mvp-btn.safe",
            "body.cute .mvp-btn.done",
            "body.cute .mvp-action.primary",
            "body.cute .subtitle-safe",
        ]

        for rule in expected_rules:
            with self.subTest(rule=rule):
                self.assertIn(rule, self.page)
        self.assertIn("background: #fff1f7;", self.page)
        self.assertIn("background: linear-gradient(180deg, #fb7185 0%, #db2777 100%);", self.page)


    def test_cute_guardian_relationship_and_group_surfaces_use_pink(self):
        expected_rules = [
            "body.cute .mvp-reward-card",
            "body.cute .mvp-bound-summary",
            "body.cute .member-contact-group.guardian-group",
            "body.cute .guardian-status-card",
            "body.cute .guardian-group-guide-intro",
            'body.cute .guardian-group-bind-status[data-bound="false"]',
            "body.cute .guardian-group-card",
            "body.cute .guardian-group-preferences",
        ]

        for rule in expected_rules:
            with self.subTest(rule=rule):
                self.assertIn(rule, self.page)

        cute_guardian_palette = re.search(
            r"/\* 可愛主題：守護關係與守護群統一粉色 \*/(?P<rules>.*?)"
            r"/\* 可愛主題守護區塊結束 \*/",
            self.page,
            re.S,
        )
        self.assertIsNotNone(cute_guardian_palette)
        rules = cute_guardian_palette.group("rules")
        self.assertIn("#fff1f7", rules)
        self.assertIn("#f9a8d4", rules)
        self.assertNotIn("#fff7ed", rules)
        self.assertNotIn("#fffbeb", rules)
        self.assertNotIn("#fef3c7", rules)


if __name__ == "__main__":
    unittest.main()
