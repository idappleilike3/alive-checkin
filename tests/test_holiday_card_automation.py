import os
import tempfile
import unittest
from datetime import datetime

import app
import holidays_tw


class HolidayCardAutomationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_file = os.path.join(self.tmp.name, "state.json")

    def test_august_seventh_resolves_tomorrows_fathers_day(self):
        holiday = holidays_tw.holiday_on_next_day(datetime(2026, 8, 7, 9, 0))
        self.assertEqual(holiday["name"], "父親節")
        self.assertEqual(holiday["date"], "2026-08-08")

    def test_august_ninth_2026_is_a_one_day_fathers_day_makeup(self):
        holiday = holidays_tw.holiday_for(datetime(2026, 8, 9, 9, 0))

        self.assertEqual(holiday["name"], "父親節延續祝福")
        self.assertIn("祝福不遲到", holiday["blessing"])

    def test_august_ninth_makeup_reuses_fathers_day_portrait(self):
        url = app.holiday_asset_url_for_date({}, datetime(2026, 8, 9, 9, 0))

        self.assertTrue(url.endswith("holiday-fathers-day.webp"))

    def test_preparation_uses_durable_bundled_fathers_day_asset_once(self):
        config = {"DATA_FILE": self.data_file}
        first, first_code = app.prepare_tomorrow_holiday_card(
            config, now=datetime(2026, 8, 7, 9, 0)
        )
        second, second_code = app.prepare_tomorrow_holiday_card(
            config, now=datetime(2026, 8, 7, 9, 5)
        )

        self.assertEqual(first_code, 200)
        self.assertEqual(first["status"], "ready")
        self.assertEqual(first["source"], "bundled")
        self.assertTrue(first["image_url"].endswith("holiday-fathers-day.webp"))
        self.assertEqual(second_code, 200)
        self.assertEqual(second["status"], "already_ready")
        state = app.load_state(self.data_file)
        self.assertEqual(list(state["holiday_card_assets"]), ["2026-08-08"])

    def test_ordinary_tomorrow_needs_no_preparation(self):
        result, code = app.prepare_tomorrow_holiday_card(
            {"DATA_FILE": self.data_file}, now=datetime(2026, 8, 9, 9, 0)
        )
        self.assertEqual(code, 200)
        self.assertEqual(result["status"], "no_holiday_tomorrow")

    def test_fathers_day_uses_portrait_special_hero_and_four_real_actions(self):
        flex = app.build_daily_checkin_flex(
            datetime(2026, 8, 8, 12, 0),
            profile={"display_name": "Jennie", "history": ["2026-08-08"]},
            holiday_asset_url=(
                "https://alive-checkin.onrender.com/assets/daily-care/"
                "holiday-fathers-day.webp"
            ),
        )
        hero = flex["contents"]["hero"]
        self.assertEqual(hero["aspectRatio"], "4:5")
        self.assertEqual(hero["aspectMode"], "fit")
        self.assertTrue(hero["url"].endswith("holiday-fathers-day.webp"))
        footer = flex["contents"]["footer"]["contents"]
        self.assertGreaterEqual(len(footer), 4)
        self.assertEqual(footer[0]["action"]["type"], "postback")
        self.assertEqual(
            [button["action"]["label"] for button in footer[:4]],
            ["✅ 我平安", "🛡️ 安全守護", "需要幫忙", "🔔 查看今日安心提醒"],
        )

    def test_fathers_day_card_keeps_member_weather_visible(self):
        flex = app.build_daily_checkin_flex(
            datetime(2026, 8, 8, 12, 0),
            profile={
                "location": {"city": "臺中市", "district": "西屯區"},
                "weather": {
                    "condition": "多雲",
                    "temperature_range": "26～32°C",
                    "rain_probability": 30,
                },
            },
            holiday_asset_url=(
                "https://alive-checkin.onrender.com/assets/daily-care/"
                "holiday-fathers-day.webp"
            ),
        )
        body_text = "\n".join(
            item.get("text", "") for item in flex["contents"]["body"]["contents"]
        )

        self.assertIn("🌤️ 臺中市｜多雲｜26～32°C｜降雨機率 30%", body_text)

    def test_cron_tick_reports_holiday_preparation(self):
        result, code = app.run_cron_tick({
            "DATA_FILE": self.data_file,
            "LINE_CHANNEL_ACCESS_TOKEN": "",
            "CRON_NOW": datetime(2026, 8, 7, 9, 0),
        })
        self.assertEqual(code, 200)
        prepared = result["tasks"]["holiday_card_preparation"]
        self.assertEqual(prepared["status"], 200)
        self.assertEqual(prepared["result"]["status"], "ready")


if __name__ == "__main__":
    unittest.main()
