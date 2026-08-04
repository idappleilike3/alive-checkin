import unittest
from pathlib import Path
from datetime import datetime

import app
from daily_care import build_daily_care_context, streak_level_context


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

    def test_today_detail_combines_calendar_note_and_smart_reminder(self):
        profile = {
            "calendar_notes": {"2026-08-03": "下午三點陪媽媽回診"},
            "smart_reminders": [{
                "target_name": "自己", "category": "medicine", "category_label": "吃藥",
                "month": 8, "day": 3, "year": 2026, "remind_time": "20:00",
                "note": "晚餐後服用", "enabled": True,
            }],
        }
        context = build_daily_care_context(profile, datetime(2026, 8, 3, 9))
        self.assertEqual(len(context["today_reminders"]), 2)
        self.assertIn("陪媽媽回診", context["today_reminders"][0]["text"])
        self.assertIn("20:00", context["today_reminders"][1]["text"])
        self.assertIn("晚餐後服用", context["today_reminders"][1]["text"])

    def test_government_life_news_is_separate_from_blessing_and_level(self):
        profile = {
            "streak_days": 7,
            "daily_news": {
                "title": "政府重要生活消息",
                "summary": "今日部分地區有豪雨，外出前請留意官方警特報。",
                "source_name": "交通部中央氣象署",
                "source_url": "https://www.cwa.gov.tw/",
            },
            "daily_blessing": "今天也要平安順心。",
        }
        context = build_daily_care_context(profile, datetime(2026, 8, 3, 9))
        self.assertEqual(context["news_title"], "政府重要生活消息")
        self.assertIn("豪雨", context["news_summary"])
        self.assertEqual(context["blessing_text"], "今天也要平安順心。")
        self.assertIn("Lv.3", context["level_progress_text"])

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

    def test_evening_rotation_includes_the_new_family_video_call_template(self):
        urls = {
            build_daily_care_context({}, datetime(2026, 8, day, 20))["hero_url"]
            for day in range(2, 8)
        }
        self.assertIn(
            "https://alive-checkin.onrender.com/assets/daily-care/evening-03.webp",
            urls,
        )

    def test_day_100_replaces_daily_information(self):
        context = build_daily_care_context({"streak_days": 100}, datetime(2026, 8, 2, 13))
        self.assertEqual(context["content_kind"], "milestone")
        self.assertIn("100", context["care_title"])

    def test_day_365_replaces_daily_information(self):
        context = build_daily_care_context({"streak_days": 365}, datetime(2026, 8, 2, 13))
        self.assertEqual(context["content_kind"], "milestone")
        self.assertIn("365", context["care_title"])

    def test_all_upgrade_days_link_to_web_celebration(self):
        for day in (1, 3, 7, 14, 21, 30, 60, 90, 100, 180, 270, 365):
            with self.subTest(day=day):
                context = build_daily_care_context(
                    {"streak_days": day}, datetime(2026, 8, 2, 13)
                )
                self.assertEqual(context["content_kind"], "milestone")
                self.assertEqual(context["milestone_day"], day)
                self.assertIn(f"milestone={day}", context["achievement_url"])

    def test_every_streak_has_level_and_next_upgrade_progress(self):
        context = streak_level_context(18)
        self.assertEqual(context["level"], 4)
        self.assertEqual(context["level_name"], "安心同行")
        self.assertEqual(context["next_level_day"], 21)
        self.assertEqual(context["days_to_next_level"], 3)
        self.assertFalse(context["is_upgrade_day"])

    def test_restart_keeps_highest_earned_level_without_calling_it_downgrade(self):
        context = build_daily_care_context(
            {"streak_days": 1, "highest_streak_days": 100, "streak_restarted": True},
            datetime(2026, 8, 2, 9),
        )
        self.assertEqual(context["level"], 9)
        self.assertEqual(context["level_name"], "百日之星")
        self.assertEqual(context["streak_status_text"], "重新開始連續守護")
        self.assertNotIn("降級", context["streak_status_text"])

    def test_all_twelve_levels_use_the_approved_upgrade_rewards(self):
        cases = (
            (1, "愛心動畫"), (3, "小星光"), (7, "彩帶驚喜"), (14, "新徽章"),
            (21, "鼓勵卡"), (30, "金色獎章"), (60, "進階徽章"), (90, "星光卡"),
            (100, "煙火＋第一支 MP4"), (180, "高級金色徽章"), (270, "年度倒數卡"),
            (365, "年度動畫＋第二支 MP4"),
        )
        for day, reward in cases:
            with self.subTest(day=day):
                context = streak_level_context(day)
                self.assertEqual(context["reward_name"], reward)

    def test_all_twelve_levels_use_the_approved_game_badge_names(self):
        cases = (
            (1, "初心愛心章"), (3, "星芽徽章"), (7, "七日守護章"),
            (14, "雙週同行章"), (21, "習慣守護章"), (30, "金色夥伴章"),
            (60, "穩定之星章"), (90, "長久陪伴章"), (100, "百日榮耀章"),
            (180, "黃金守護章"), (270, "典範之星章"), (365, "年度傳說勳章"),
        )
        for day, badge_name in cases:
            with self.subTest(day=day):
                context = streak_level_context(day)
                self.assertEqual(context["game_badge_name"], badge_name)

    def test_flex_and_detail_context_share_the_same_game_badge(self):
        context = build_daily_care_context(
            {"streak_days": 100, "highest_streak_days": 100},
            datetime(2026, 8, 3, 9),
        )
        self.assertEqual(context["game_badge_name"], "百日榮耀章")
        flex = app.build_daily_checkin_flex(
            datetime(2026, 8, 3, 9),
            profile={"history": ["2026-04-26", "2026-08-03"], "highest_streak_days": 100},
        )
        body_text = "\n".join(
            item.get("text", "") for item in flex["contents"]["body"]["contents"]
        )
        self.assertIn("遊戲勳章：百日榮耀章", body_text)

    def test_daily_card_has_question_before_checkin_and_level_progress(self):
        context = build_daily_care_context({"streak_days": 18}, datetime(2026, 8, 2, 9))
        self.assertEqual(context["checkin_prompt"], "今天一切都還好嗎？點一下「我平安」")
        self.assertIn("Lv.4 安心同行", context["level_progress_text"])
        self.assertIn("還差 3 天", context["level_progress_text"])

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
        self.assertIn("daily-peace-logo.png", footer[0]["contents"][0]["url"])
        self.assertEqual(footer[0]["contents"][1]["size"], "xl")
        self.assertEqual(footer[1]["height"], "md")
        self.assertIn("查看今日安心提醒", footer[3]["action"]["label"])
        self.assertIn("/assets/daily-care/morning-", flex["contents"]["hero"]["url"])
        self.assertEqual(flex["contents"]["hero"]["aspectRatio"], "16:9")
        self.assertEqual(flex["contents"]["hero"]["aspectMode"], "fit")
        self.assertEqual(footer[1]["color"], "#2563EB")
        self.assertEqual(footer[2]["color"], "#DC2626")
        self.assertEqual(footer[3]["color"], "#D4A017")
        self.assertEqual(
            flex["contents"]["body"]["contents"][0]["text"],
            "早安，今天一切都還好嗎？點一下「我平安」",
        )
        self.assertIn("Lv.1 安心啟程", flex["contents"]["body"]["contents"][1]["text"])

    def test_daily_card_personalizes_name_and_keeps_the_habit_value_visible(self):
        flex = app.build_daily_checkin_flex(
            datetime(2026, 8, 5, 20),
            profile={"display_name": "Jennie", "history": ["2026-08-05"]},
        )
        body_text = "\n".join(
            item.get("text", "")
            for item in flex["contents"]["body"]["contents"]
            if item.get("type") == "text"
        )
        self.assertIn("晚安，Jennie，今天一切都還好嗎？", body_text)
        self.assertIn("每天只花 10 秒", body_text)
        self.assertIn("也讓在乎我的人放心", body_text)

    def test_default_daily_card_does_not_fill_the_card_with_non_urgent_news(self):
        flex = app.build_daily_checkin_flex(
            datetime(2026, 8, 5, 20), profile={"display_name": "Jennie"}
        )
        body_text = "\n".join(
            item.get("text", "")
            for item in flex["contents"]["body"]["contents"]
            if item.get("type") == "text"
        )
        self.assertNotIn("今日政府與生活重要消息", body_text)
        self.assertIn("今天沒有特別提醒", body_text)

    def test_flex_uses_same_news_reminders_and_large_bold_copy_as_detail_page(self):
        profile = {
            "history": ["2026-08-03"],
            "calendar_notes": {"2026-08-03": "下午領藥"},
            "daily_news": {"title": "政府生活消息", "summary": "外出請留意豪雨。"},
            "daily_blessing": "今天平安順心。",
        }
        flex = app.build_daily_checkin_flex(datetime(2026, 8, 3, 9), profile=profile)
        body = flex["contents"]["body"]["contents"]
        text = "\n".join(item.get("text", "") for item in body)
        self.assertIn("政府生活消息", text)
        self.assertIn("下午領藥", text)
        self.assertIn("今天平安順心", text)
        for item in body:
            if item.get("type") == "text":
                self.assertEqual(item.get("weight"), "bold")
                self.assertIn(item.get("size"), {"lg", "xl"})

    def test_detail_page_uses_liff_identity_and_has_required_sections(self):
        html = Path("daily-care.html").read_text(encoding="utf-8")
        for marker in ("liff.getIDToken", "/api/daily-care", "所在地區天氣", "政府與生活重要消息", "我的今日提醒", "我的平安等級", "今日祝福語", "返回每日平安卡"):
            self.assertIn(marker, html)
        self.assertIn("font-weight:900", html)


if __name__ == "__main__":
    unittest.main()
