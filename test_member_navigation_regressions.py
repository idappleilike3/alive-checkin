import pathlib
import unittest
from datetime import datetime

import app


ROOT = pathlib.Path(__file__).resolve().parent


class MemberNavigationRegressionTests(unittest.TestCase):
    def test_daily_card_buttons_stay_inside_authenticated_liff(self):
        flex = app.build_daily_checkin_flex(
            datetime(2026, 8, 3, 12, 0),
            target_time="12:00",
            profile={"line_user_id": "U" + "a" * 32, "history": []},
        )
        footer = flex["contents"]["footer"]["contents"]
        actions = [row.get("action", {}) for row in footer]
        self.assertEqual(actions[0]["type"], "uri")
        self.assertIn("open=checkin", actions[0]["uri"])
        self.assertTrue(any("open=daily-care" in row.get("uri", "") for row in actions))

    def test_achievement_button_stays_inside_authenticated_liff(self):
        flex = app.build_daily_checkin_flex(
            datetime(2026, 8, 3, 12, 0),
            profile={
                "line_user_id": "U" + "b" * 32,
                "history": ["2026-08-03"],
                "streak_days": 1,
            },
        )
        actions = [row.get("action", {}) for row in flex["contents"]["footer"]["contents"]]
        achievement = next(row for row in actions if "achievement" in row.get("uri", ""))
        self.assertIn("open=achievement", achievement["uri"])
        self.assertIn("milestone=1", achievement["uri"])

    def test_member_routes_include_daily_care_and_achievement_without_onboarding(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('openAction === "daily-care"', html)
        self.assertIn('openAction === "achievement"', html)
        self.assertIn("openDailyCarePanel", html)

    def test_admin_dates_are_explicitly_rendered_in_taipei_timezone(self):
        html = (ROOT / "admin.html").read_text(encoding="utf-8")
        format_date = html[html.index("function formatDate(value)"):]
        format_date = format_date[: format_date.index("\n    }")]
        self.assertIn('timeZone: "Asia/Taipei"', format_date)

    def test_guardian_binding_reminder_runs_with_regular_cron_tasks(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        always = source[source.index('always = {', source.index('def run_cron_tick')):]
        always = always[: always.index('\n    }')]
        self.assertIn('"contact_reminders": send_missing_contact_reminders', always)


if __name__ == "__main__":
    unittest.main()
