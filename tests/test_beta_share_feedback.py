import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import app


ROOT = Path(__file__).resolve().parents[1]


class BetaShareFeedbackTests(unittest.TestCase):
    def test_paid_member_with_stale_beta_fields_does_not_receive_feedback(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_file = str(Path(tmp) / "state.json")
            app.save_state(data_file, {
                "users": {
                    "U-jennie": {
                        "line_user_id": "U-jennie",
                        "display_name": "JENNIE",
                        "plan": "paid_799_year",
                        "membership_source": "beta",
                        "payment_status": "active",
                        "paid_until": "2027-07-24T15:54:00",
                        "beta_cohort": "B799",
                        "beta_started_at": "2026-07-27T10:00:00",
                        "beta_ends_at": "2026-08-17T10:00:00",
                    }
                }
            })
            sent = []

            result, code = app.send_beta_daily_feedback(
                {
                    "DATA_FILE": data_file,
                    "LINE_CHANNEL_ACCESS_TOKEN": "token",
                    "LINE_PUSH_SENDER": lambda token, target, message: sent.append(target),
                },
                now=datetime(2026, 7, 30, 19, 0, 0),
            )

            self.assertEqual(code, 200)
            self.assertEqual(result["sent"], 0)
            self.assertEqual(sent, [])

    def test_beta_pages_explain_story_tasks_rules_and_require_consent(self):
        page = (ROOT / "beta-register.html").read_text(encoding="utf-8")
        self.assertIn("daily-peace-story-comic.png", page)
        self.assertIn("每天 19:00", page)
        self.assertIn("截圖、發生時間、操作步驟、手機型號與 LINE 版本", page)
        self.assertIn("家庭 LINE 群組", page)
        self.assertIn("我已加入官方LINE，繼續登入設定", page)
        self.assertIn("beta799Task.hidden = !is799", page)
        self.assertIn("join.disabled = !consent.checked", page)

    def test_trial_and_guardian_entries_include_beginner_story(self):
        onboarding = (ROOT / "liff" / "onboarding.html").read_text(encoding="utf-8")
        invite = (ROOT / "invite.html").read_text(encoding="utf-8")
        guide = (ROOT / "guardian-guide.html").read_text(encoding="utf-8")
        self.assertIn("14 天免費體驗｜199 活著版", onboarding)
        self.assertIn("guardian-story-mother-daughter", onboarding)
        self.assertIn("guardian-story-mother-daughter", invite)
        self.assertIn("不會全天偷追蹤", guide)

    def test_feedback_flex_has_all_five_responses_and_cohort_task(self):
        profile = {"beta_cohort": "B799", "beta_started_at": "2026-07-27T10:00:00"}
        message = app.build_beta_feedback_flex(profile, 3)
        payload = str(message)
        for label in ("使用正常", "發現問題", "使用心得", "不會操作", "稍後提醒"):
            self.assertIn(label, payload)
        self.assertIn("家庭群組", payload)
        self.assertIn("beta_feedback:issue:3", payload)

    def test_daily_feedback_sends_once_at_1900_and_persists_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_file = str(Path(tmp) / "state.json")
            app.save_state(data_file, {
                "users": {
                    "U-beta": {
                        "line_user_id": "U-beta",
                        "display_name": "小安",
                        "plan": "paid_399",
                        "membership_source": "beta",
                        "beta_cohort": "B399",
                        "beta_started_at": "2026-07-27T10:00:00",
                        "beta_ends_at": "2026-08-17T10:00:00",
                    }
                }
            })
            sent = []

            def sender(token, target, message):
                sent.append((target, message))
                return {"ok": True}

            config = {
                "DATA_FILE": data_file,
                "LINE_CHANNEL_ACCESS_TOKEN": "token",
                "LINE_PUSH_SENDER": sender,
            }
            now = datetime(2026, 7, 28, 19, 0, 0)
            first, first_code = app.send_beta_daily_feedback(config, now=now)
            second, second_code = app.send_beta_daily_feedback(config, now=now)

            self.assertEqual((first_code, second_code), (200, 200))
            self.assertEqual(first["sent"], 1)
            self.assertEqual(second["sent"], 0)
            self.assertEqual(len(sent), 1)
            state = app.load_state(data_file)
            self.assertEqual(
                state["users"]["U-beta"]["beta_feedback_last_push_date"],
                "2026-07-28",
            )
            self.assertEqual(
                state["notification_logs"][-1]["kind"], "beta_daily_feedback"
            )

    def test_feedback_postback_updates_member_and_returns_issue_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_file = str(Path(tmp) / "state.json")
            app.save_state(data_file, {
                "users": {
                    "U-beta": {
                        "line_user_id": "U-beta",
                        "membership_source": "beta",
                        "beta_cohort": "B399",
                        "beta_started_at": "2026-07-27T10:00:00",
                        "beta_ends_at": "2026-08-17T10:00:00",
                    }
                }
            })
            reply = app.handle_beta_feedback_postback(
                data_file, "U-beta", "beta_feedback:issue:2",
                now=datetime(2026, 7, 28, 19, 5, 0),
            )
            state = app.load_state(data_file)
            self.assertEqual(state["users"]["U-beta"]["beta_feedback_status"], "issue")
            self.assertIn("手機型號", reply)
            self.assertIn("LINE 版本", reply)
            self.assertEqual(state["beta_feedback_reports"][-1]["day"], 2)

    def test_beta_snapshot_contains_latest_feedback_details(self):
        state = {"users": {"U-beta": {
            "line_user_id": "U-beta",
            "display_name": "測試者",
            "plan": "paid_399",
            "membership_source": "beta",
            "beta_cohort": "B399",
            "beta_started_at": "2026-07-27T10:00:00",
            "beta_ends_at": "2026-08-17T10:00:00",
            "beta_feedback_status": "normal",
            "beta_feedback_last_at": "2026-07-28T19:03:00",
            "beta_feedback_last_day": 2,
        }}}
        row = app.beta_members_snapshot(
            state, now=datetime(2026, 7, 28, 19, 5, 0)
        )["members"][0]
        self.assertEqual(row["feedback_last_day"], 2)
        self.assertEqual(row["feedback_last_at"], "2026-07-28T19:03:00")


if __name__ == "__main__":
    unittest.main()
