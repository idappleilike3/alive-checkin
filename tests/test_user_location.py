import unittest
from datetime import datetime

from app import build_status


class UserLocationStatusTests(unittest.TestCase):
    def test_status_exposes_saved_member_location_and_weather(self):
        profile = {
            "line_user_id": "U-location",
            "display_name": "寶寶",
            "location": {"city": "台北市", "district": "中山區"},
            "weather": {
                "condition": "多雲",
                "temperature_range": "25～31°C",
                "resolved_location": {"city": "新北市", "district": "板橋區"},
            },
        }

        status = build_status(profile, now=datetime(2026, 8, 2, 8, 0, 0))

        self.assertEqual(status["user_location"], {"city": "台北市", "district": "中山區"})
        self.assertEqual(status["weather"]["condition"], "多雲")

    def test_missing_weather_is_safe_and_serializable(self):
        status = build_status(
            {"line_user_id": "U-no-weather", "display_name": "長輩"},
            now=datetime(2026, 8, 2, 18, 0, 0),
        )

        self.assertEqual(status["user_location"], {"city": "", "district": ""})
        self.assertEqual(status["weather"], {})
        self.assertTrue(status["daily_blessing"])


if __name__ == "__main__":
    unittest.main()
