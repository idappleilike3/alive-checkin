import unittest
from pathlib import Path

import app as alive_app


ROOT = Path(__file__).resolve().parents[1]
MEASUREMENT_ID = "G-7LT14XLHFM"


class PublicAnalyticsSeoTests(unittest.TestCase):
    def test_public_pages_include_ga4_and_complete_seo_contract(self):
        for filename in (
            "index.html",
            "pricing.html",
            "liff/pricing.html",
            "help.html",
            "faq.html",
            "privacy.html",
            "terms.html",
        ):
            source = (ROOT / filename).read_text(encoding="utf-8")
            with self.subTest(filename=filename):
                self.assertIn(MEASUREMENT_ID, source)
                self.assertIn("googletagmanager.com/gtag/js", source)
                self.assertIn('name="description"', source)
                self.assertIn('rel="canonical"', source)
                self.assertIn('property="og:title"', source)
                self.assertIn('property="og:description"', source)
                self.assertIn('property="og:url"', source)
                self.assertIn('name="robots"', source)
                self.assertIn('type="application/ld+json"', source)

    def test_search_engine_files_are_public_and_reference_production_site(self):
        flask_app = alive_app.create_app({"TESTING": True})
        client = flask_app.test_client()

        robots = client.get("/robots.txt")
        self.assertEqual(robots.status_code, 200)
        self.assertIn("Sitemap: https://alive-checkin.onrender.com/sitemap.xml", robots.get_data(as_text=True))

        sitemap = client.get("/sitemap.xml")
        self.assertEqual(sitemap.status_code, 200)
        body = sitemap.get_data(as_text=True)
        self.assertIn("https://alive-checkin.onrender.com/", body)
        self.assertIn("https://alive-checkin.onrender.com/pricing", body)
        self.assertIn("https://alive-checkin.onrender.com/help", body)
        self.assertNotIn("/admin", body)


if __name__ == "__main__":
    unittest.main()
