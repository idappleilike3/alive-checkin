import unittest
from pathlib import Path


class AdminPersonalizedCardApiContractTests(unittest.TestCase):
    def test_routes_cover_template_preview_and_holiday_workflow(self):
        source = Path("app.py").read_text(encoding="utf-8")
        for route in (
            '/api/admin/card-templates',
            '/api/admin/personalized-checkin-push/card-preview',
            '/api/admin/holiday-card/catalog',
            '/api/admin/holiday-card/prompt',
            '/api/admin/holiday-card/generate',
        ):
            self.assertIn(route, source)


if __name__ == "__main__":
    unittest.main()
