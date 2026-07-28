from pathlib import Path
import re
import unittest
from urllib.parse import urljoin, urlparse


ROOT = Path(__file__).resolve().parents[1]


class BrandLogoPagesTests(unittest.TestCase):
    def test_web_home_displays_logo_immediately_before_daily_peace_brand(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn(
            '<div class="mvp-brand"><img class="mvp-brand-logo" '
            'src="assets/daily-peace-logo.png" alt="">每日平安</div>',
            page,
        )

    def test_public_share_page_uses_daily_peace_name_and_logo(self):
        page = (ROOT / "share.html").read_text(encoding="utf-8")
        self.assertIn('src="assets/daily-peace-logo.png"', page)
        self.assertIn("每日平安", page)
        self.assertNotIn('<div class="brand">今天還在嗎</div>', page)

    def test_399_and_799_beta_page_displays_logo_before_daily_peace_brand(self):
        page = (ROOT / "beta-register.html").read_text(encoding="utf-8")
        self.assertIn(
            '<img class="brand-logo" src="/assets/daily-peace-logo.png" alt="">'
            "每日平安限定招募",
            page,
        )
        self.assertIn("每日平安限定招募", page)
        self.assertIn('"B399"', page)
        self.assertIn('"B799"', page)
        self.assertIn("399 年費安心版｜21 天封測", page)
        self.assertIn("799 年費守護版｜21 天封測", page)

    def test_beta_logo_resolves_to_public_asset_from_both_beta_routes(self):
        page = (ROOT / "beta-register.html").read_text(encoding="utf-8")
        match = re.search(r'<img class="brand-logo" src="([^"]+)"', page)
        self.assertIsNotNone(match)

        for route in ("/beta/399", "/beta/799"):
            resolved = urlparse(urljoin(f"https://alive-checkin.onrender.com{route}", match.group(1)))
            self.assertEqual("/assets/daily-peace-logo.png", resolved.path)


if __name__ == "__main__":
    unittest.main()
