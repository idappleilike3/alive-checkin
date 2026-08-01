"""Membership expiry notices and renewal restoration."""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import app as app_module


class MembershipLifecycleNoticeTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.fromisoformat("2026-07-27T10:00:00")

    def test_expiry_flex_has_one_upgrade_button_and_no_duplicate_plan_button(self):
        flex = app_module.build_expiry_remind_flex(
            {
                "plan": "trial",
                "trial_started_at": (
                    self.now - timedelta(days=12)
                ).isoformat(timespec="seconds"),
            },
            now=self.now,
        )
        buttons = flex["contents"]["footer"]["contents"]
        labels = [button["action"]["label"] for button in buttons]

        self.assertEqual(labels, ["繼續安心守護", "不再提醒"])
        self.assertNotIn("查看方案", str(flex))

    def test_expiry_flex_personalizes_warm_card_and_keeps_two_clear_actions(self):
        flex = app_module.build_expiry_remind_flex(
            {
                "display_name": "Jennie",
                "plan": "paid_399_year",
                "membership_source": "paid",
                "paid_until": (
                    self.now + timedelta(days=7)
                ).isoformat(timespec="seconds"),
            },
            now=self.now,
        )

        serialized = str(flex)
        self.assertIn("Jennie，謝謝您這段時間的支持", serialized)
        self.assertIn("399 安心版(年)", serialized)
        self.assertIn("歡迎分享使用感受與建議", serialized)
        self.assertIn("8 天", serialized)
        footer = flex["contents"]["footer"]["contents"]
        self.assertEqual(footer[0]["action"]["label"], "繼續安心守護")
        self.assertIn("from=expiry_reminder", footer[0]["action"]["uri"])
        self.assertEqual(footer[1]["action"]["label"], "不再提醒")

    def test_expiry_flex_header_uses_official_logo_beside_daily_peace_name(self):
        flex = app_module.build_expiry_remind_flex(
            {
                "display_name": "Jennie",
                "plan": "trial",
                "trial_started_at": "2026-07-20T10:00:00",
            },
            now=self.now,
        )

        brand = flex["contents"]["header"]["contents"][0]
        self.assertEqual(brand["type"], "box")
        self.assertEqual(brand["layout"], "horizontal")
        self.assertEqual(brand["contents"][0]["type"], "image")
        self.assertEqual(
            brand["contents"][0]["url"],
            app_module.public_page_url("assets/daily-peace-logo.png"),
        )
        self.assertEqual(brand["contents"][1]["text"], "每日平安")

    def test_expiry_flex_uses_safe_greeting_when_nickname_is_placeholder(self):
        flex = app_module.build_expiry_remind_flex(
            {
                "display_name": "LINE 使用者",
                "plan": "trial",
                "trial_started_at": "2026-07-20T10:00:00",
            },
            now=self.now,
        )

        serialized = str(flex)
        self.assertIn("您好，謝謝您這段時間的支持", serialized)
        self.assertNotIn("LINE 使用者，", serialized)

    def test_expiry_opt_out_reply_is_warm_and_reversible(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "state.json"
            app_module.save_state(
                data_file,
                {"users": {"U-owner": {"line_user_id": "U-owner"}}},
            )

            reply = app_module.handle_expiry_opt_out_postback(data_file, "U-owner")

            self.assertIn("謝謝您告訴我們", reply)
            self.assertIn("不會再提醒方案到期", reply)
            self.assertIn("隨時回來", reply)

    def test_trial_beta_and_paid_notice_schedules(self):
        self.assertEqual(
            app_module.membership_notice_milestones(
                {
                    "plan": "trial",
                    "trial_started_at": (
                        self.now - timedelta(days=11)
                    ).isoformat(timespec="seconds"),
                },
                now=self.now,
            ),
            [11],
        )
        self.assertEqual(
            app_module.membership_notice_milestones(
                {
                    "plan": "paid_399",
                    "membership_source": "beta",
                    "beta_started_at": (
                        self.now - timedelta(days=20)
                    ).isoformat(timespec="seconds"),
                    "beta_ends_at": (
                        self.now + timedelta(days=1)
                    ).isoformat(timespec="seconds"),
                },
                now=self.now,
            ),
            [1],
        )
        self.assertEqual(
            app_module.membership_notice_milestones(
                {
                    "plan": "paid_799",
                    "membership_source": "paid",
                    "payment_status": "active",
                    "paid_until": (
                        self.now + timedelta(days=3)
                    ).isoformat(timespec="seconds"),
                },
                now=self.now,
            ),
            [3],
        )

    def test_all_expiring_memberships_use_four_countdown_milestones(self):
        cases = [
            ({"plan": "trial", "trial_started_at": "2026-07-20T10:00:00"}, [7]),
            ({
                "plan": "paid_799",
                "membership_source": "beta",
                "beta_started_at": "2026-07-19T10:00:00",
                "beta_ends_at": "2026-08-03T10:00:00",
            }, [7]),
            ({
                "plan": "paid_399",
                "membership_source": "paid",
                "paid_until": "2026-08-03T10:00:00",
            }, [7]),
            ({
                "plan": "paid_799_year",
                "membership_source": "gift",
                "paid_until": "2026-08-03T10:00:00",
            }, [7]),
        ]

        for profile, expected in cases:
            with self.subTest(profile=profile):
                self.assertEqual(
                    app_module.membership_notice_milestones(profile, now=self.now),
                    expected,
                )

    def test_countdown_copy_counts_today_and_uses_plan_specific_action(self):
        trial = {
            "plan": "trial",
            "trial_started_at": "2026-07-20T10:00:00",
        }
        paid = {
            "plan": "paid_399",
            "membership_source": "paid",
            "paid_until": "2026-08-03T10:00:00",
        }

        trial_flex = app_module.build_expiry_remind_flex(trial, now=self.now)
        paid_flex = app_module.build_expiry_remind_flex(paid, now=self.now)

        self.assertIn("將在 8 天後到期", str(trial_flex))
        self.assertIn("提前通知，方便家人一起決定", str(trial_flex))
        self.assertNotIn("7 天考慮期", str(trial_flex))
        self.assertEqual(
            trial_flex["contents"]["footer"]["contents"][0]["action"]["label"],
            "繼續安心守護",
        )
        self.assertIn("將在 8 天後到期", str(paid_flex))
        self.assertEqual(
            paid_flex["contents"]["footer"]["contents"][0]["action"]["label"],
            "繼續安心守護",
        )

    def test_countdown_copy_for_three_one_and_zero_days_left(self):
        expected = {
            3: "將在 4 天後到期",
            1: "明天是最後一天",
            0: "今天到期",
        }
        for days_left, copy in expected.items():
            profile = {
                "plan": "paid_799",
                "membership_source": "paid",
                "paid_until": (
                    self.now + timedelta(days=days_left)
                ).isoformat(timespec="seconds"),
            }
            with self.subTest(days_left=days_left):
                self.assertIn(
                    copy,
                    str(app_module.build_expiry_remind_flex(profile, now=self.now)),
                )

    def test_renewal_restores_original_daily_greeting_choice_and_settings(self):
        profile = {
            "line_user_id": "U-owner",
            "plan": "paid_399",
            "daily_checkin_reminder_enabled": False,
            "reminder_times": ["08:30", "19:30"],
            "contacts": [{"line_id": "U-mom", "is_primary": True}],
        }
        app_module.mark_entitlement_lapsed(profile, self.now)
        app_module.restore_membership_after_renewal(
            profile,
            "paid_799",
            self.now + timedelta(days=30),
            now=self.now,
        )

        self.assertFalse(profile["daily_checkin_reminder_enabled"])
        self.assertEqual(profile["reminder_times"], ["08:30", "19:30"])
        self.assertEqual(profile["contacts"][0]["line_id"], "U-mom")
        self.assertFalse(profile["membership_paused"])

    def test_lifecycle_push_sends_flex_once_for_due_paid_notice(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "state.json"
            app_module.save_state(
                data_file,
                {
                    "users": {
                        "U-owner": {
                            "line_user_id": "U-owner",
                            "plan": "paid_399",
                            "membership_source": "paid",
                            "payment_status": "active",
                            "paid_until": (
                                self.now + timedelta(days=3)
                            ).isoformat(timespec="seconds"),
                        }
                    }
                },
            )
            sent = []
            config = {
                "DATA_FILE": data_file,
                "LINE_CHANNEL_ACCESS_TOKEN": "token",
                "LINE_PUSH_SENDER": lambda token, target, message: sent.append(
                    (target, message)
                ),
            }

            first, first_code = app_module.send_membership_lifecycle_notices(
                config, now=self.now
            )
            second, second_code = app_module.send_membership_lifecycle_notices(
                config, now=self.now
            )

            self.assertEqual((first_code, second_code), (200, 200))
            self.assertEqual(first["sent"], 1)
            self.assertEqual(second["sent"], 0)
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0][1]["type"], "flex")
            self.assertIn("繼續安心守護", str(sent[0][1]))


if __name__ == "__main__":
    unittest.main()
