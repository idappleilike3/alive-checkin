import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import app


class CheckinSmartSuccessMessageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_file = str(Path(self.tmp.name) / "state.json")
        self.now = datetime(2026, 8, 5, 20, 36)

    def profile(self, *, with_news=True):
        profile = {
            **app.DEFAULT_PROFILE,
            "line_user_id": "U-owner",
            "display_name": "Jennie",
            "history": [],
            "highest_streak_days": 0,
            "daily_blessing": "平凡的一天，也值得慶祝。",
            "reminder_times": ["12:00"],
            "contacts": [
                {
                    "id": "g-1",
                    "name": "家人",
                    "line_id": "U-guardian",
                    "binding_status": "accepted",
                    "consent_status": "accepted",
                    "contact_role": "guardian",
                    "is_primary": True,
                    "priority": 1,
                    "notify_methods": ["line"],
                }
            ],
        }
        if with_news:
            profile["daily_news"] = {
                "title": "颱風接近",
                "summary": "今天有颱風接近，外出請留意風雨。",
                "source_name": "交通部中央氣象署",
            }
        return profile

    def checkin(self, profile):
        app.save_state(self.data_file, {"users": {"U-owner": profile}})
        return app.record_checkin(
            self.data_file,
            {"line_user_id": "U-owner"},
            config={"CRON_NOW": self.now},
        )

    def test_member_reply_includes_real_time_blessing_level_news_and_next_reminder(self):
        status = self.checkin(self.profile())
        text = app.build_checkin_success_text(status, now=self.now)

        self.assertIn("✅ 已報平安時間：2026/08/05 20:36", text)
        self.assertIn("📅 今天是 8/5（三）", text)
        self.assertIn("💌 平凡的一天，也值得慶祝。", text)
        self.assertIn("🌱 當前等級：安心啟程｜連續 1 天", text)
        self.assertIn("📰 安心提醒：今天有颱風接近，外出請留意風雨。", text)
        self.assertIn("⏰ 下次提醒 8/6（四） 12:00", text)
        self.assertTrue(text.endswith("今日已報平安，請放心"))

    def test_member_reply_hides_news_line_when_no_important_news(self):
        status = self.checkin(self.profile(with_news=False))
        text = app.build_checkin_success_text(status, now=self.now)

        self.assertNotIn("📰", text)
        self.assertIn("🌱 當前等級：安心啟程｜連續 1 天", text)

    def test_guardian_receives_blessing_level_and_news_without_next_reminder(self):
        pushes = []
        profile = self.profile()
        profile["history"] = ["2026-08-05"]
        app.save_state(self.data_file, {"users": {"U-owner": profile}})
        result = app.notify_guardians_of_checkin(
            self.data_file,
            "U-owner",
            config={
                "CRON_NOW": self.now,
                "LINE_CHANNEL_ACCESS_TOKEN": "token",
                "LINE_PUSH_SENDER": lambda _token, target, message: pushes.append(
                    (target, message)
                ) or {"ok": True},
            },
            now=self.now,
        )

        self.assertEqual(result["sent"], 1)
        self.assertEqual(pushes[0][0], "U-guardian")
        text = pushes[0][1]
        self.assertIn("✅ Jennie 今日已報平安", text)
        self.assertIn("🕒 完成時間：2026/08/05 20:36", text)
        self.assertIn("💌 平凡的一天，也值得慶祝。", text)
        self.assertIn("🌱 當前等級：安心啟程｜連續 1 天", text)
        self.assertIn("📰 安心提醒：今天有颱風接近，外出請留意風雨。", text)
        self.assertNotIn("下次提醒", text)
        self.assertTrue(text.endswith("今日已收到 Jennie 的平安，請放心"))


if __name__ == "__main__":
    unittest.main()
