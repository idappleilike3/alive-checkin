import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import app as alive_app


class SafetyGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_file = str(Path(self.tmp.name) / "state.json")
        alive_app.save_state(self.data_file, {"users": {}})

    def tearDown(self):
        self.tmp.cleanup()

    def test_start_timed_session_and_stop(self):
        state = alive_app.load_state(self.data_file)
        profile = alive_app.get_profile(state, "U1")
        profile["plan"] = "paid_399"
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

        stop, stop_code = alive_app.stop_location_sharing(
            self.data_file, {"line_user_id": "U1"}
        )
        self.assertEqual(stop_code, 200)
        self.assertFalse(stop["safety_guard"]["active"])
        self.assertTrue(stop["safety_guard"]["ended_at"])

    def test_until_stop_rejected_and_refresh_only(self):
        # until_stop is no longer offered; timed session + refresh_only still works.
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
        p399 = alive_app.get_profile(state, "u399")
        p399["plan"] = "paid_399"
        p799 = alive_app.get_profile(state, "u799")
        p799["plan"] = "paid_799"
        alive_app.save_state(self.data_file, state)

        self.assertEqual(alive_app.allowed_safety_guard_hours(free_user), [1])
        self.assertEqual(alive_app.allowed_safety_guard_hours(p399), [1, 3])
        self.assertEqual(alive_app.allowed_safety_guard_hours(p799), [1, 3, 6, 8])

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
        self.assertEqual(denied["allowed_hours"], [1])

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

    def test_friend_can_see_active_safety_status(self):
        state = alive_app.load_state(self.data_file)
        owner = alive_app.get_profile(state, "owner")
        friend = alive_app.get_profile(state, "friend")
        owner["friends"] = ["friend"]
        friend["friends"] = ["owner"]
        friend["history"] = [datetime.now().date().isoformat()]
        friend["last_check_in"] = datetime.now().isoformat(timespec="seconds")
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
