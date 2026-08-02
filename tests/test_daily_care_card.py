import unittest
from pathlib import Path
from datetime import datetime

import app
from daily_care import build_daily_care_context


class DailyCareContextTests(unittest.TestCase):
    def test_missing_location_never_invents_weather(self):
        context = build_daily_care_context({}, datetime(2026, 8, 2, 9))
        self.assertEqual(context["weather_status"], "missing_location")
        self.assertEqual(context["weather_line"], "請設定所在地區")
        self.assertNotIn("臺北", context["weather_line"])

    def test_member_weather_and_one_care_item_are_rendered(self):
        profile = {
            "city": "臺中市",
            "district": "西屯區",
            "weather": {"description": "晴時多雲", "min_c": 26, "max_c": 32, "rain_probability": 30},
        }
        context = build_daily_care_context(profile, datetime(2026, 8, 2, 13))
        self.assertEqual(context["greeting"], "午安")
        self.assertEqual(context["weather_line"], "臺中市｜晴時多雲｜26～32°C｜降雨機率 30%")
        self.assertTrue(30 <= len(context["care_summary"]) <= 50)

    def test_time_period_selects_matching_ui_ux_hero(self):
        cases = ((8, "morning"), (13, "afternoon"), (20, "evening"))
        for hour, period in cases:
            with self.subTest(period=period):
                context = build_daily_care_context({}, datetime(2026, 8, 2, hour))
                self.assertEqual(context["hero_period"], period)
                self.assertTrue(context["hero_url"].endswith(f"/{period}.webp"))
                self.assertTrue(Path(f"assets/daily-care/{period}.webp").is_file())

    def test_day_100_replaces_daily_information(self):
        context = build_daily_care_context({"streak_days": 100}, datetime(2026, 8, 2, 13))
        self.assertEqual(context["content_kind"], "milestone")
        self.assertIn("100", context["care_title"])

    def test_flex_has_four_large_buttons_and_larger_checkin(self):
        profile = {"city": "臺中市", "district": "西屯區"}
        flex = app.build_daily_checkin_flex(datetime(2026, 8, 2, 9), profile=profile)
        footer = flex["contents"]["footer"]["contents"]
        self.assertEqual(len(footer), 4)
        self.assertEqual(footer[0]["action"]["label"], "✅ 我平安")
        self.assertEqual(footer[0]["type"], "box")
        self.assertEqual(footer[0]["contents"][0]["size"], "xl")
        self.assertEqual(footer[1]["height"], "md")
        self.assertIn("查看今日安心提醒", footer[3]["action"]["label"])
        self.assertEqual(flex["contents"]["hero"]["url"], "https://alive-checkin.onrender.com/assets/daily-care/morning.webp")
        self.assertEqual(flex["contents"]["hero"]["aspectRatio"], "16:9")

    def test_detail_page_uses_liff_identity_and_has_required_sections(self):
        html = Path("daily-care.html").read_text(encoding="utf-8")
        for marker in ("liff.getIDToken", "/api/daily-care", "所在地區天氣", "今日安心資訊", "返回每日平安卡"):
            self.assertIn(marker, html)


if __name__ == "__main__":
    unittest.main()
