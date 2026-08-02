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

    def test_time_period_selects_matching_ui_ux_hero_pool(self):
        cases = ((8, "morning"), (13, "afternoon"), (20, "evening"))
        for hour, period in cases:
            with self.subTest(period=period):
                context = build_daily_care_context({}, datetime(2026, 8, 2, hour))
                self.assertEqual(context["hero_period"], period)
                asset_name = context["hero_url"].rsplit("/", 1)[-1]
                self.assertTrue(asset_name.startswith(f"{period}-"))
                self.assertTrue(Path(f"assets/daily-care/{asset_name}").is_file())

    def test_consecutive_dates_rotate_each_period_without_crossing_pools(self):
        for hour, period in ((8, "morning"), (13, "afternoon"), (20, "evening")):
            first = build_daily_care_context({}, datetime(2026, 8, 2, hour))
            second = build_daily_care_context({}, datetime(2026, 8, 3, hour))
            with self.subTest(period=period):
                self.assertNotEqual(first["hero_url"], second["hero_url"])
                self.assertIn(f"/{period}-", first["hero_url"])
                self.assertIn(f"/{period}-", second["hero_url"])

    def test_day_100_replaces_daily_information(self):
        context = build_daily_care_context({"streak_days": 100}, datetime(2026, 8, 2, 13))
        self.assertEqual(context["content_kind"], "milestone")
        self.assertIn("100", context["care_title"])

    def test_day_365_replaces_daily_information(self):
        context = build_daily_care_context({"streak_days": 365}, datetime(2026, 8, 2, 13))
        self.assertEqual(context["content_kind"], "milestone")
        self.assertIn("365", context["care_title"])

    def test_all_upgrade_days_link_to_web_celebration(self):
        for day in (1, 7, 30, 60, 100, 180, 365):
            with self.subTest(day=day):
                context = build_daily_care_context(
                    {"streak_days": day}, datetime(2026, 8, 2, 13)
                )
                self.assertEqual(context["content_kind"], "milestone")
                self.assertEqual(context["milestone_day"], day)
                self.assertIn(f"milestone={day}", context["achievement_url"])

    def test_milestone_flex_adds_real_achievement_button(self):
        history = ["2026-08-02"]
        flex = app.build_daily_checkin_flex(
            datetime(2026, 8, 2, 13), profile={"history": history}
        )
        buttons = flex["contents"]["footer"]["contents"]
        achievement = buttons[-1]
        self.assertEqual(achievement["action"]["type"], "uri")
        self.assertIn("查看我的平安成就", achievement["action"]["label"])
        self.assertIn("milestone=1", achievement["action"]["uri"])

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
        self.assertIn("/assets/daily-care/morning-", flex["contents"]["hero"]["url"])
        self.assertEqual(flex["contents"]["hero"]["aspectRatio"], "20:13")
        self.assertEqual(
            flex["contents"]["body"]["contents"][0]["text"],
            "早安，今天一切都還好嗎？",
        )

    def test_detail_page_uses_liff_identity_and_has_required_sections(self):
        html = Path("daily-care.html").read_text(encoding="utf-8")
        for marker in ("liff.getIDToken", "/api/daily-care", "所在地區天氣", "今日安心資訊", "返回每日平安卡"):
            self.assertIn(marker, html)


if __name__ == "__main__":
    unittest.main()
