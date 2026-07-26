from pathlib import Path
import tempfile
import unittest

import app


class GuardianGroupSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_file = Path(self.tmp.name) / "state.json"
        app.save_state(
            self.data_file,
            {
                "users": {
                    "U-owner": {
                        "line_user_id": "U-owner",
                        "plan": "paid_799_year",
                        "guardian_group_ids": ["C-family"],
                    },
                    "U-other": {
                        "line_user_id": "U-other",
                        "plan": "paid_799",
                        "guardian_group_ids": ["C-other"],
                    },
                },
                "guardian_groups": {
                    "C-family": {
                        "group_id": "C-family",
                        "group_name": "家人守護群",
                        "owner_line_user_id": "U-owner",
                        "status": "active",
                        "member_count_at_bind": 4,
                        "preferences": {
                            "daily_admin_summary": True,
                            "daily_summary_time": "22:30",
                        },
                    },
                    "C-other": {
                        "group_id": "C-other",
                        "group_name": "別人的群",
                        "owner_line_user_id": "U-other",
                        "status": "active",
                        "preferences": {"daily_admin_summary": True},
                    },
                },
            },
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_settings_only_return_groups_owned_by_member(self):
        result, code = app.guardian_group_settings_for_user(
            self.data_file, "U-owner"
        )

        self.assertEqual(code, 200)
        self.assertEqual(result["guardian_group_limit"], 3)
        self.assertEqual(result["guardian_group_count"], 1)
        self.assertEqual([g["group_id"] for g in result["groups"]], ["C-family"])
        self.assertEqual(result["groups"][0]["group_name"], "家人守護群")
        self.assertEqual(result["groups"][0]["member_count"], 4)
        self.assertTrue(result["groups"][0]["preferences"]["daily_admin_summary"])
        self.assertEqual(
            result["groups"][0]["preferences"]["daily_summary_time"], "22:30"
        )

    def test_member_without_groups_receives_empty_settings(self):
        state = app.load_state(self.data_file)
        state["users"]["U-empty"] = {
            "line_user_id": "U-empty",
            "plan": "paid_799",
            "guardian_group_ids": [],
        }
        app.save_state(self.data_file, state)

        result, code = app.guardian_group_settings_for_user(
            self.data_file, "U-empty"
        )

        self.assertEqual(code, 200)
        self.assertEqual(result["guardian_group_limit"], 1)
        self.assertEqual(result["guardian_group_count"], 0)
        self.assertEqual(result["groups"], [])

    def test_unknown_member_is_rejected(self):
        result, code = app.guardian_group_settings_for_user(
            self.data_file, "U-missing"
        )

        self.assertEqual(code, 404)
        self.assertEqual(result["error"], "user not registered")

    def test_settings_and_save_are_available_through_http_client(self):
        client = app.create_app({
            "TESTING": True,
            "DATA_FILE": self.data_file,
            "ALLOW_LEGACY_LINE_USER_ID": True,
        }).test_client()

        fetched = client.get(
            "/api/guardian-groups/settings?line_user_id=U-owner"
        )
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.get_json()["groups"][0]["group_id"], "C-family")

        saved = client.post(
            "/api/guardian-groups/preferences",
            data='{"line_user_id":"U-owner","group_id":"C-family",'
            '"daily_admin_summary":false,"daily_summary_time":"20:15"}',
            content_type="application/json",
        )
        self.assertEqual(saved.status_code, 200)
        self.assertFalse(saved.get_json()["preferences"]["daily_admin_summary"])
        self.assertEqual(
            saved.get_json()["preferences"]["daily_summary_time"], "20:15"
        )


if __name__ == "__main__":
    unittest.main()
