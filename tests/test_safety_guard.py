import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import app as alive_app


def _add_bound_guardian(profile, lid="U_guard", name="家人"):
    profile["contacts"] = [
        {
            "name": name,
            "relationship": "家人",
            "line_user_id": lid,
            "binding_status": "accepted",
            "notify_methods": ["line"],
            "is_primary": True,
        }
    ]


class SafetyGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_file = str(Path(self.tmp.name) / "state.json")
        alive_app.save_state(self.data_file, {"users": {}})

    def tearDown(self):
        self.tmp.cleanup()

    def test_start_rejects_without_bound_guardian(self):
        state = alive_app.load_state(self.data_file)
        profile = alive_app.get_profile(state, "U0")
        profile["plan"] = "free"
        # 僅表單資料、尚未 LINE 綁定 → 不可開安全守護
        profile["contacts"] = [
            {"name": "媽媽", "relationship": "媽媽", "phone": "0911111111"}
        ]
        alive_app.save_state(self.data_file, state)
        body, code = alive_app.update_location(
            self.data_file,
            {
                "line_user_id": "U0",
                "latitude": 25.033,
                "longitude": 121.5654,
                "city": "台北市",
                "duration": 1,
            },
        )
        self.assertEqual(code, 403)
        self.assertEqual(body.get("error_code"), "guardian_required")
        self.assertIn("還沒完成綁定守護人", body.get("error") or "")

    def test_start_timed_session_and_stop(self):
        state = alive_app.load_state(self.data_file)
        profile = alive_app.get_profile(state, "U1")
        profile["plan"] = "paid_399"
        _add_bound_guardian(profile, "U_mom", "媽媽")
        alive_app.save_state(self.data_file, state)
        body, code = alive_app.update_location(
            self.data_file,
            {
                "line_user_id": "U1",
                "latitude": 25.033,
                "longitude": 121.5654,
                "city": "台北市",
                "duration": 3,
            },
        )
        self.assertEqual(code, 200)
        self.assertTrue(body["safety_guard"]["active"])
        self.assertEqual(body["safety_guard"]["duration_hours"], 3)
        self.assertFalse(body["safety_guard"]["until_stop"])
        self.assertEqual(body["location"]["mode"], "safety_guard")
        self.assertIn("guardian_notify", body)
        # 有綁定但無 push token 時仍算可開通；通知結果可能 failed
        self.assertFalse(body["guardian_notify"].get("no_guardians"))

        stop, stop_code = alive_app.stop_location_sharing(
            self.data_file, {"line_user_id": "U1"}
        )
        self.assertEqual(stop_code, 200)
        self.assertFalse(stop["safety_guard"]["active"])
        self.assertTrue(stop["safety_guard"]["ended_at"])

    def test_until_stop_rejected_and_refresh_only(self):
        # until_stop is no longer offered; timed session + refresh_only still works.
        state = alive_app.load_state(self.data_file)
        profile = alive_app.get_profile(state, "U2")
        profile["plan"] = "paid_399"
        _add_bound_guardian(profile)
        alive_app.save_state(self.data_file, state)
        alive_app.update_location(
            self.data_file,
            {
                "line_user_id": "U2",
                "latitude": 24.15,
                "longitude": 120.67,
                "city": "台中市",
                "duration": 1,
            },
        )
        rejected, rejected_code = alive_app.update_location(
            self.data_file,
            {
                "line_user_id": "U2",
                "latitude": 24.15,
                "longitude": 120.67,
                "city": "台中市",
                "duration": "until_stop",
            },
        )
        self.assertEqual(rejected_code, 403)
        self.assertIn("allowed_hours", rejected)

        refreshed, code = alive_app.update_location(
            self.data_file,
            {
                "line_user_id": "U2",
                "latitude": 24.16,
                "longitude": 120.68,
                "city": "台中市",
                "refresh_only": True,
            },
        )
        self.assertEqual(code, 200)
        self.assertTrue(refreshed["safety_guard"]["active"])
        self.assertFalse(refreshed["safety_guard"]["until_stop"])
        self.assertEqual(refreshed["location"]["latitude"], 24.16)

    def test_plan_gated_safety_guard_hours(self):
        state = alive_app.load_state(self.data_file)
        free_user = alive_app.get_profile(state, "free_user")
        free_user["plan"] = "free"
        _add_bound_guardian(free_user, "U_g_free")
        p399 = alive_app.get_profile(state, "u399")
        p399["plan"] = "paid_399"
        _add_bound_guardian(p399, "U_g_399")
        p799 = alive_app.get_profile(state, "u799")
        p799["plan"] = "paid_799"
        _add_bound_guardian(p799, "U_g_799")
        alive_app.save_state(self.data_file, state)

        self.assertEqual(alive_app.allowed_safety_guard_hours(free_user), [])
        self.assertEqual(alive_app.allowed_safety_guard_hours(p399), [1, 3])
        self.assertEqual(alive_app.allowed_safety_guard_hours(p799), [1, 3, 6, 8])

        denied_free, denied_free_code = alive_app.update_location(
            self.data_file,
            {
                "line_user_id": "free_user",
                "latitude": 25.0,
                "longitude": 121.5,
                "city": "台北市",
                "duration": 1,
            },
        )
        self.assertEqual(denied_free_code, 403)
        self.assertEqual(denied_free.get("error_code"), "safety_guard_upgrade_required")

        denied, code = alive_app.update_location(
            self.data_file,
            {
                "line_user_id": "free_user",
                "latitude": 25.0,
                "longitude": 121.5,
                "city": "台北市",
                "duration": 3,
            },
        )
        self.assertEqual(code, 403)
        self.assertEqual(denied["allowed_hours"], [])

        ok8, code8 = alive_app.update_location(
            self.data_file,
            {
                "line_user_id": "u799",
                "latitude": 25.0,
                "longitude": 121.5,
                "city": "台北市",
                "duration": 8,
            },
        )
        self.assertEqual(code8, 200)
        self.assertEqual(ok8["safety_guard"]["duration_hours"], 8)

        denied399, code399 = alive_app.update_location(
            self.data_file,
            {
                "line_user_id": "u399",
                "latitude": 25.0,
                "longitude": 121.5,
                "city": "台北市",
                "duration": 8,
            },
        )
        self.assertEqual(code399, 403)
        self.assertEqual(denied399["allowed_hours"], [1, 3])

    def test_paid_199_is_limited_to_fifteen_minutes(self):
        state = alive_app.load_state(self.data_file)
        owner = alive_app.get_profile(state, "u199")
        owner["plan"] = "paid_199"
        _add_bound_guardian(owner, "U_guard_199")
        alive_app.save_state(self.data_file, state)

        self.assertEqual(alive_app.allowed_safety_guard_hours(owner), [0.25])
        body, code = alive_app.update_location(
            self.data_file,
            {
                "line_user_id": "u199",
                "latitude": 25.0,
                "longitude": 121.5,
                "city": "台北市",
                "duration": 0.25,
            },
        )

        self.assertEqual(code, 200)
        self.assertEqual(body["safety_guard"]["duration_hours"], 0.25)
        started = datetime.fromisoformat(body["safety_guard"]["started_at"])
        expires = datetime.fromisoformat(body["safety_guard"]["expires_at"])
        self.assertEqual(expires - started, timedelta(minutes=15))

    def test_active_trial_gets_two_fifteen_minute_sessions_per_day(self):
        state = alive_app.load_state(self.data_file)
        owner = alive_app.get_profile(state, "u_trial_guard")
        owner["plan"] = "trial"
        owner["trial_started_at"] = (datetime.now() - timedelta(days=1)).isoformat(
            timespec="seconds"
        )
        owner["trial_end"] = (datetime.now() + timedelta(days=13)).isoformat(
            timespec="seconds"
        )
        _add_bound_guardian(owner, "U_guard_trial")
        alive_app.save_state(self.data_file, state)

        self.assertEqual(alive_app.allowed_safety_guard_hours(owner), [0.25])
        first, first_code = alive_app.update_location(
            self.data_file,
            {
                "line_user_id": "u_trial_guard",
                "latitude": 25.0,
                "longitude": 121.5,
                "city": "台北市",
                "duration": 0.25,
            },
        )
        self.assertEqual(first_code, 200)
        self.assertEqual(first["safety_guard"]["duration_hours"], 0.25)

        alive_app.stop_location_sharing(
            self.data_file, {"line_user_id": "u_trial_guard"}
        )
        second, second_code = alive_app.update_location(
            self.data_file,
            {
                "line_user_id": "u_trial_guard",
                "latitude": 25.001,
                "longitude": 121.501,
                "city": "台北市",
                "duration": 0.25,
            },
        )
        self.assertEqual(second_code, 200)
        self.assertEqual(second["safety_guard"]["duration_hours"], 0.25)

        alive_app.stop_location_sharing(
            self.data_file, {"line_user_id": "u_trial_guard"}
        )
        third, third_code = alive_app.update_location(
            self.data_file,
            {
                "line_user_id": "u_trial_guard",
                "latitude": 25.002,
                "longitude": 121.502,
                "city": "台北市",
                "duration": 0.25,
            },
        )
        self.assertEqual(third_code, 429)
        self.assertEqual(third.get("error_code"), "trial_daily_limit_reached")
        self.assertIn("明天", third.get("message") or "")

    def test_paid_plans_enforce_daily_session_limits(self):
        cases = [
            ("paid_199", 0.25, 2),
            ("paid_199_year", 0.25, 2),
            ("paid_399", 1, 3),
            ("paid_399_year", 1, 3),
            ("paid_799", 1, 5),
            ("paid_799_year", 1, 5),
        ]
        for plan, duration, daily_limit in cases:
            with self.subTest(plan=plan):
                user_id = f"user_{plan}"
                state = alive_app.load_state(self.data_file)
                owner = alive_app.get_profile(state, user_id)
                owner["plan"] = plan
                _add_bound_guardian(owner, f"guardian_{plan}")
                alive_app.save_state(self.data_file, state)

                for _ in range(daily_limit):
                    body, code = alive_app.update_location(
                        self.data_file,
                        {
                            "line_user_id": user_id,
                            "latitude": 25.0,
                            "longitude": 121.5,
                            "duration": duration,
                        },
                    )
                    self.assertEqual(code, 200, body)
                    alive_app.stop_location_sharing(
                        self.data_file, {"line_user_id": user_id}
                    )

                denied, denied_code = alive_app.update_location(
                    self.data_file,
                    {
                        "line_user_id": user_id,
                        "latitude": 25.0,
                        "longitude": 121.5,
                        "duration": duration,
                    },
                )
                self.assertEqual(denied_code, 429)
                self.assertEqual(
                    denied.get("error_code"), "safety_guard_daily_limit_reached"
                )
                self.assertEqual(denied.get("daily_limit"), daily_limit)

    def test_active_session_update_does_not_count_or_notify_again(self):
        sent = []

        def fake_sender(_token, target, _message):
            sent.append(target)
            return {"ok": True}

        fixed_now = datetime(2026, 8, 1, 23, 55)
        state = alive_app.load_state(self.data_file)
        owner = alive_app.get_profile(state, "U-active")
        owner["plan"] = "paid_399"
        _add_bound_guardian(owner, "U-family")
        alive_app.save_state(self.data_file, state)
        config = {"CRON_NOW": fixed_now, "LINE_CHANNEL_ACCESS_TOKEN": "token", "LINE_PUSH_SENDER": fake_sender}

        first, first_code = alive_app.update_location(
            self.data_file,
            {"line_user_id": "U-active", "latitude": 25.0, "longitude": 121.5, "duration": 1},
            config,
        )
        second, second_code = alive_app.update_location(
            self.data_file,
            {"line_user_id": "U-active", "latitude": 25.01, "longitude": 121.51, "duration": 1},
            config,
        )
        self.assertEqual((first_code, second_code), (200, 200))
        self.assertEqual(sent, ["U-family"])
        self.assertEqual(first["safety_guard"]["daily_used"], 1)
        self.assertEqual(second["safety_guard"]["daily_used"], 1)
        self.assertEqual(second["safety_guard"]["daily_remaining"], 2)
        self.assertEqual(second["guardian_notify"]["reason_code"], "active_session_updated")

    def test_snapshot_resets_daily_quota_by_taipei_calendar_day(self):
        profile = {
            **alive_app.DEFAULT_PROFILE,
            "plan": "paid_799",
            "safety_guard_usage_date": "2026-07-31",
            "safety_guard_usage_count": 5,
        }
        snap = alive_app.safety_guard_snapshot(profile, datetime(2026, 8, 1, 0, 5))
        self.assertEqual(snap["daily_limit"], 5)
        self.assertEqual(snap["daily_used"], 0)
        self.assertEqual(snap["daily_remaining"], 5)

    def test_expired_trial_cannot_start_safety_guard(self):
        state = alive_app.load_state(self.data_file)
        owner = alive_app.get_profile(state, "u_expired_trial")
        owner["plan"] = "trial"
        owner["trial_started_at"] = (datetime.now() - timedelta(days=15)).isoformat(
            timespec="seconds"
        )
        owner["trial_end"] = (datetime.now() - timedelta(days=1)).isoformat(
            timespec="seconds"
        )
        _add_bound_guardian(owner, "U_guard_expired")
        alive_app.save_state(self.data_file, state)

        body, code = alive_app.update_location(
            self.data_file,
            {
                "line_user_id": "u_expired_trial",
                "latitude": 25.0,
                "longitude": 121.5,
                "city": "台北市",
                "duration": 0.25,
            },
        )
        self.assertEqual(code, 403)
        self.assertEqual(body.get("error_code"), "safety_guard_upgrade_required")

    def test_selected_guardians_only_notifies_eligible_selected_targets(self):
        sent = []

        def fake_sender(token, target, message):
            sent.append(target)
            return {"ok": True}

        state = alive_app.load_state(self.data_file)
        owner = alive_app.get_profile(state, "owner_selected")
        owner["plan"] = "paid_799"
        owner["contacts"] = [
            {
                "name": "媽媽",
                "contact_role": "guardian",
                "line_user_id": "U_mom",
                "binding_status": "accepted",
                "notify_methods": ["line"],
                "is_primary": True,
            },
            {
                "name": "姊姊",
                "contact_role": "guardian",
                "line_user_id": "U_sister",
                "binding_status": "accepted",
                "notify_methods": ["line"],
                "is_primary": True,
            },
            {
                "name": "朋友",
                "contact_role": "guardian",
                "line_user_id": "U_friend",
                "binding_status": "accepted",
                "notify_methods": ["line"],
                "is_primary": False,
            },
        ]
        alive_app.save_state(self.data_file, state)

        body, code = alive_app.update_location(
            self.data_file,
            {
                "line_user_id": "owner_selected",
                "latitude": 25.0,
                "longitude": 121.5,
                "duration": 1,
                "guardian_line_user_ids": ["U_sister", "U_unknown"],
            },
            {"LINE_CHANNEL_ACCESS_TOKEN": "token", "LINE_PUSH_SENDER": fake_sender},
        )

        self.assertEqual(code, 200)
        self.assertEqual(sent, ["U_sister"])
        self.assertEqual(body["guardian_notify"]["selected_target_count"], 1)
        self.assertEqual(body["safety_guard"]["guardian_line_user_ids"], ["U_sister"])

    def test_safety_guard_notifies_bound_guardians(self):
        sent = []

        def fake_sender(token, target, message):
            sent.append({"target": target, "message": message})
            return {"ok": True, "status": 200}

        state = alive_app.load_state(self.data_file)
        owner = alive_app.get_profile(state, "owner_sg")
        owner["plan"] = "paid_399"
        owner["display_name"] = "小明"
        owner["contacts"] = [
            {
                "name": "媽媽",
                "relationship": "媽媽",
                "line_user_id": "U_mom",
                "binding_status": "accepted",
                "notify_methods": ["line"],
                "is_primary": True,
            }
        ]
        alive_app.save_state(self.data_file, state)

        body, code = alive_app.update_location(
            self.data_file,
            {
                "line_user_id": "owner_sg",
                "latitude": 25.04,
                "longitude": 121.56,
                "city": "台北市",
                "duration": 1,
            },
            {"LINE_CHANNEL_ACCESS_TOKEN": "test-token", "LINE_PUSH_SENDER": fake_sender},
        )
        self.assertEqual(code, 200)
        self.assertTrue(body["safety_guard"]["active"])
        self.assertEqual(body["guardian_notify"]["sent"], 1)
        self.assertEqual(body["guardian_notify"]["failed"], 0)
        self.assertFalse(body["guardian_notify"]["no_guardians"])
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["target"], "U_mom")
        self.assertIn("安全守護", sent[0]["message"])
        self.assertIn("1 小時", sent[0]["message"])
        self.assertIn("台北市", sent[0]["message"])

    def test_safety_guard_skips_emergency_only_and_reports_reason(self):
        """緊急聯絡人有 LINE 不算可通知守護人；須回傳 notified 0 與原因。"""
        state = alive_app.load_state(self.data_file)
        owner = alive_app.get_profile(state, "owner_em")
        owner["plan"] = "free"
        owner["contacts"] = [
            {
                "name": "爸爸",
                "relationship": "爸爸",
                "line_user_id": "U_dad_phone",
                "binding_status": "accepted",
                "notify_methods": ["line"],
                "contact_role": "emergency",
            }
        ]
        alive_app.save_state(self.data_file, state)
        self.assertFalse(alive_app.profile_has_bound_line_guardian(owner))
        body, code = alive_app.update_location(
            self.data_file,
            {
                "line_user_id": "owner_em",
                "latitude": 25.0,
                "longitude": 121.5,
                "city": "台北市",
                "duration": 1,
            },
            {"LINE_CHANNEL_ACCESS_TOKEN": "test-token"},
        )
        self.assertEqual(code, 403)
        self.assertEqual(body.get("error_code"), "guardian_required")

    def test_safety_guard_push_failure_includes_reason(self):
        def boom_sender(token, target, message):
            raise RuntimeError("You have been blocked by the user")

        state = alive_app.load_state(self.data_file)
        owner = alive_app.get_profile(state, "owner_blk")
        owner["plan"] = "paid_399"
        owner["display_name"] = "小華"
        _add_bound_guardian(owner, "U_blocked", "家人")
        alive_app.save_state(self.data_file, state)
        body, code = alive_app.update_location(
            self.data_file,
            {
                "line_user_id": "owner_blk",
                "latitude": 25.04,
                "longitude": 121.56,
                "city": "台北市",
                "duration": 1,
            },
            {"LINE_CHANNEL_ACCESS_TOKEN": "test-token", "LINE_PUSH_SENDER": boom_sender},
        )
        self.assertEqual(code, 200)
        self.assertTrue(body["safety_guard"]["active"])
        self.assertEqual(body["guardian_notify"]["sent"], 0)
        self.assertEqual(body["guardian_notify"]["failed"], 1)
        self.assertEqual(body["safety_guard"].get("notified_count"), 0)
        self.assertIn("好友", body["guardian_notify"]["message"])
        self.assertTrue(body["guardian_notify"].get("failed_reasons"))

    def test_friend_can_see_active_safety_status(self):
        state = alive_app.load_state(self.data_file)
        owner = alive_app.get_profile(state, "owner")
        friend = alive_app.get_profile(state, "friend")
        friend["plan"] = "paid_399"
        owner["friends"] = ["friend"]
        friend["friends"] = ["owner"]
        friend["history"] = [datetime.now().date().isoformat()]
        friend["last_check_in"] = datetime.now().isoformat(timespec="seconds")
        _add_bound_guardian(friend, "U_friend_guard")
        alive_app.save_state(self.data_file, state)

        alive_app.update_location(
            self.data_file,
            {
                "line_user_id": "friend",
                "latitude": 22.63,
                "longitude": 120.3,
                "city": "高雄市",
                "duration": 1,
            },
        )
        visible = alive_app.friend_locations(self.data_file, "owner")
        self.assertEqual(len(visible["friends"]), 1)
        self.assertIn("今日已簽到", visible["friends"][0]["safety_status"])

    def test_expired_session_hidden_and_cleanup(self):
        state = alive_app.load_state(self.data_file)
        profile = alive_app.get_profile(state, "U3")
        past = (datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds")
        profile["location"] = {
            "latitude": 25.0,
            "longitude": 121.5,
            "city": "台北市",
            "sharing": True,
            "active": True,
            "started_at": past,
            "expires_at": past,
            "until_stop": False,
            "mode": "safety_guard",
        }
        alive_app.save_state(self.data_file, state)

        visible = alive_app.friend_locations(self.data_file, "U3")
        self.assertEqual(visible["friends"], [])

        result, code = alive_app.cleanup_expired_data(
            {"DATA_FILE": self.data_file, "APP_TIMEZONE": "Asia/Taipei"}
        )
        self.assertEqual(code, 200)
        self.assertGreaterEqual(result["expired_locations_removed"], 1)
        state2 = alive_app.load_state(self.data_file)
        self.assertFalse(state2["users"]["U3"]["location"].get("sharing"))


if __name__ == "__main__":
    unittest.main()
