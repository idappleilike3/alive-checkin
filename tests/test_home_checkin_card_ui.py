import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class HomeCheckinCardUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / "index.html").read_text(encoding="utf-8")
        marker = '<section class="checkin-card"'
        cls.card = (
            cls.page.split(marker, 1)[1].split('<div class="countdown-block"', 1)[0]
            if marker in cls.page else ""
        )

    def test_card_has_one_frame_and_keeps_lower_actions_outside(self):
        self.assertEqual(self.page.count('<section class="checkin-card"'), 1)
        self.assertNotIn("checkin-card-inner", self.card)
        self.assertNotIn('class="mvp-grid"', self.card)

    def test_compact_button_copy_and_accessible_size(self):
        self.assertRegex(self.page, r"\.check-btn\s*\{[^}]*width:\s*104px")
        self.assertRegex(self.page, r"\.check-btn\s*\{[^}]*height:\s*104px")
        self.assertIn('<span class="label">我平安</span>', self.card)
        self.assertIn('<span class="sub">點我一下</span>', self.card)
        self.assertRegex(self.page, r"\.check-btn \.sub\s*\{[^}]*font-size:\s*16px")

    def test_original_header_decorations_and_lower_actions_remain(self):
        for text in ("每日平安", "每天 10 秒，報個平安", "check-wrap::before", "安全守護", "聯絡家人", "緊急求助"):
            self.assertIn(text, self.page)
        for element_id in ("mvpSafeBtn", "mvpGuardBtn", "mvpCallBtn", "mvpSosBtn"):
            self.assertEqual(self.page.count(f'id="{element_id}"'), 1)

    def test_classic_is_green_and_cute_is_pink(self):
        self.assertRegex(self.page, r"\.checkin-card\s*\{[^}]*border:[^;}]*#22c55e")
        self.assertRegex(self.page, r"body\.cute \.checkin-card\s*\{[^}]*border-color:\s*#f9a8d4")
        self.assertRegex(self.page, r"body\.cute \.check-btn:not\(\.danger\):not\(\.warning\)\s*\{[^}]*#fb7185")

    def test_three_time_greetings_and_location_weather_are_rendered(self):
        for greeting in ('return "早安"', 'return "午安"', 'return "晚安"'):
            self.assertIn(greeting, self.page)
        self.assertIn("function renderWeatherLocation", self.page)
        self.assertIn("data.user_location", self.page)
        self.assertNotIn("navigator.geolocation", self.card)

    def test_inline_javascript_parses(self):
        scripts = re.findall(r"<script(?![^>]*type=\"application/ld\+json\")[^>]*>(.*?)</script>", self.page, flags=re.S)
        scripts = [script for script in scripts if script.strip()]
        self.assertGreater(len(scripts), 0)
        for index, script in enumerate(scripts):
            result = subprocess.run(
                ["node", "--check", "-"], input=script, text=True,
                capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 0, f"script {index}: {result.stderr}")


if __name__ == "__main__":
    unittest.main()
