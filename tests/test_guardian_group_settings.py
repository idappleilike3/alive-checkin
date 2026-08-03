from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timedelta

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
        self.assertEqual(
            result["default_preferences"],
            {
                "notify_private_guardians": True,
                "notify_group_on_overdue": False,
                "notify_admin_only": True,
                "daily_admin_summary": False,
                "daily_summary_time": "20:00",
            },
        )

    def test_non_799_member_is_told_to_upgrade_before_viewing_settings(self):
        state = app.load_state(self.data_file)
        state["users"]["U-399"] = {
            "line_user_id": "U-399",
            "plan": "paid_399",
            "payment_status": "active",
        }
        app.save_state(self.data_file, state)

        result, code = app.guardian_group_settings_for_user(
            self.data_file, "U-399"
        )

        self.assertEqual(code, 403)
        self.assertEqual(result["error"], "guardian group plan required")
        self.assertTrue(result["upgrade_required"])
        self.assertEqual(result["required_plan"], "799")
        self.assertIn("799", result["message"])

    def test_guardian_group_defaults_are_available_to_monthly_yearly_and_beta_799(self):
        state = app.load_state(self.data_file)
        now = datetime.now()
        state["users"]["U-month"] = {
            "line_user_id": "U-month",
            "plan": "paid_799",
            "payment_status": "active",
            "paid_until": (now + timedelta(days=30)).isoformat(timespec="seconds"),
        }
        state["users"]["U-year"] = {
            "line_user_id": "U-year",
            "plan": "paid_799_year",
            "payment_status": "active",
            "paid_until": (now + timedelta(days=365)).isoformat(timespec="seconds"),
        }
        state["users"]["U-beta"] = {
            "line_user_id": "U-beta",
            "plan": "paid_799_year",
            "membership_source": "beta",
            "payment_status": "beta",
            "beta_cohort": "B799",
            "beta_started_at": (now - timedelta(days=1)).isoformat(timespec="seconds"),
            "beta_ends_at": (now + timedelta(days=20)).isoformat(timespec="seconds"),
        }
        app.save_state(self.data_file, state)

        monthly, monthly_code = app.guardian_group_settings_for_user(
            self.data_file, "U-month"
        )
        yearly, yearly_code = app.guardian_group_settings_for_user(
            self.data_file, "U-year"
        )
        beta, beta_code = app.guardian_group_settings_for_user(
            self.data_file, "U-beta"
        )

        self.assertEqual((monthly_code, yearly_code, beta_code), (200, 200, 200))
        self.assertEqual(monthly["guardian_group_limit"], 1)
        self.assertEqual(yearly["guardian_group_limit"], 3)
        self.assertEqual(beta["guardian_group_limit"], 3)
        for result in (monthly, yearly, beta):
            self.assertTrue(result["default_preferences"]["notify_private_guardians"])
            self.assertFalse(result["default_preferences"]["notify_group_on_overdue"])
            self.assertFalse(result["default_preferences"]["daily_admin_summary"])
            self.assertTrue(result["default_preferences"]["notify_admin_only"])

    def test_unbound_member_can_save_defaults_for_the_first_guardian_group(self):
        state = app.load_state(self.data_file)
        state["users"]["U-empty"] = {
            "line_user_id": "U-empty",
            "plan": "paid_799",
            "guardian_group_ids": [],
        }
        app.save_state(self.data_file, state)

        result, code = app.update_guardian_group_preferences(
            self.data_file,
            {
                "line_user_id": "U-empty",
                "group_id": "__default__",
                "notify_private_guardians": True,
                "notify_group_on_overdue": True,
                "daily_admin_summary": False,
                "notify_admin_only": True,
                "daily_summary_time": "20:30",
            },
        )

        self.assertEqual(code, 200)
        self.assertTrue(result["preferences"]["notify_group_on_overdue"])
        profile = app.load_state(self.data_file)["users"]["U-empty"]
        self.assertEqual(
            profile["guardian_group_preferences"]["daily_summary_time"], "20:30"
        )

    def test_new_group_preferences_default_to_twenty_hundred(self):
        self.assertEqual(
            app.normalize_guardian_group_preferences({})["daily_summary_time"],
            "20:00",
        )

    def test_group_status_shows_counts_and_only_that_groups_missing_names(self):
        state = app.load_state(self.data_file)
        today = datetime.now().strftime("%Y-%m-%d")
        state["users"].update({
            "U-owner": {
                **state["users"]["U-owner"],
                "display_name": "媽媽",
                "history": [today],
            },
            "U-a": {"line_user_id": "U-a", "display_name": "小美", "history": [today]},
            "U-b": {"line_user_id": "U-b", "display_name": "爸爸"},
            "U-c": {"line_user_id": "U-c", "display_name": "阿嬤"},
            "U-d": {"line_user_id": "U-d", "display_name": "哥哥", "history": [today]},
            "U-other-member": {"line_user_id": "U-other-member", "display_name": "別群成員"},
        })
        state["guardian_groups"]["C-family"]["member_ids_at_bind"] = [
            "U-a", "U-b", "U-c", "U-d"
        ]
        state["guardian_groups"]["C-family"]["preferences"] = {
            "notify_admin_only": True,
            "daily_admin_summary": False,
            "notify_group_on_overdue": False,
        }
        state["guardian_groups"]["C-other"]["member_ids_at_bind"] = ["U-other-member"]
        app.save_state(self.data_file, state)

        text, code = app.guardian_group_daily_status_text(
            self.data_file, "U-owner", "C-family"
        )

        self.assertEqual(code, 200)
        self.assertIn("共 5 位成員", text)
        self.assertIn("3 位已報平安", text)
        self.assertIn("2 位未報平安", text)
        self.assertIn("未報平安：爸爸、阿嬤", text)
        self.assertNotIn("別群成員", text)

    def test_group_status_includes_owner_but_hides_unregistered_line_members(self):
        state = app.load_state(self.data_file)
        today = datetime.now().strftime("%Y-%m-%d")
        state["users"]["U-owner"]["display_name"] = "媽媽"
        state["users"]["U-owner"]["history"] = [today]
        state["users"]["U-a"] = {
            "line_user_id": "U-a",
            "display_name": "小美",
        }
        state["guardian_groups"]["C-family"]["member_ids_at_bind"] = [
            "U-owner",
            "U-a",
            "U-not-registered",
        ]
        app.save_state(self.data_file, state)

        result, code = app.guardian_group_daily_status(
            self.data_file,
            "U-owner",
            "C-family",
            now=datetime.now().replace(hour=10, minute=0, second=0, microsecond=0),
        )

        self.assertEqual(code, 200)
        self.assertEqual(result["counts"]["checked"], 1)
        self.assertEqual(result["counts"].get("unbound", 0), 0)
        self.assertEqual(result["counts"]["total"], 2)
        self.assertEqual(
            [row["status"] for row in result["members"]],
            ["checked", "pending"],
        )
        self.assertEqual(result["members"][0]["name"], "媽媽（管理員）")
        self.assertNotIn(
            "U-not-registered",
            [row["line_user_id"] for row in result["members"]],
        )

    def test_group_status_is_available_through_authenticated_http_api(self):
        client = app.create_app({
            "TESTING": True,
            "DATA_FILE": self.data_file,
            "ALLOW_LEGACY_LINE_USER_ID": True,
        }).test_client()

        response = client.get(
            "/api/guardian-groups/status"
            "?line_user_id=U-owner&group_id=C-family"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["group_id"], "C-family")

    def test_group_status_allows_accepted_guardian_but_rejects_other_member(self):
        state = app.load_state(self.data_file)
        state["users"]["U-owner"]["contacts"] = [{
            "line_user_id": "U-guardian",
            "contact_role": "guardian",
            "binding_status": "accepted",
        }]
        state["users"]["U-guardian"] = {
            "line_user_id": "U-guardian",
            "display_name": "女兒",
        }
        state["users"]["U-other-member"] = {
            "line_user_id": "U-other-member",
            "display_name": "一般群成員",
        }
        state["guardian_groups"]["C-family"]["member_ids_at_bind"] = [
            "U-guardian",
            "U-other-member",
        ]
        app.save_state(self.data_file, state)

        guardian_result, guardian_code = app.guardian_group_daily_status(
            self.data_file, "U-guardian", "C-family"
        )
        other_result, other_code = app.guardian_group_daily_status(
            self.data_file, "U-other-member", "C-family"
        )

        self.assertEqual(guardian_code, 200)
        self.assertTrue(guardian_result["ok"])
        self.assertEqual(other_code, 403)
        self.assertEqual(other_result["error"], "guardian group status forbidden")

    def test_unchecked_registered_member_is_overdue_after_reminder_time(self):
        state = app.load_state(self.data_file)
        state["users"]["U-a"] = {
            "line_user_id": "U-a",
            "display_name": "爸爸",
            "reminder_time": "12:00",
        }
        state["guardian_groups"]["C-family"]["member_ids_at_bind"] = ["U-a"]
        app.save_state(self.data_file, state)

        result, code = app.guardian_group_daily_status(
            self.data_file,
            "U-owner",
            "C-family",
            now=datetime(2026, 7, 30, 20, 0),
        )

        self.assertEqual(code, 200)
        member = next(row for row in result["members"] if row["line_user_id"] == "U-a")
        self.assertEqual(member["status"], "overdue")
        self.assertEqual(member["status_label"], "已超過設定時間")

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

    def test_save_requires_authenticated_line_identity(self):
        client = app.create_app({
            "TESTING": True,
            "DATA_FILE": self.data_file,
            "ALLOW_LEGACY_LINE_USER_ID": False,
            "REQUIRE_LIFF_AUTH": True,
        }).test_client()

        saved = client.post(
            "/api/guardian-groups/preferences",
            json={
                "line_user_id": "U-owner",
                "group_id": "C-family",
                "daily_admin_summary": False,
                "daily_summary_time": "20:15",
            },
        )

        self.assertEqual(saved.status_code, 401)
        stored = app.load_state(self.data_file)["guardian_groups"]["C-family"]
        self.assertTrue(stored["preferences"]["daily_admin_summary"])
        self.assertEqual(stored["preferences"]["daily_summary_time"], "22:30")

    def test_bind_and_unbind_require_authenticated_line_identity(self):
        client = app.create_app({
            "TESTING": True,
            "DATA_FILE": self.data_file,
            "ALLOW_LEGACY_LINE_USER_ID": False,
            "REQUIRE_LIFF_AUTH": True,
        }).test_client()

        bound = client.post(
            "/api/guardian-groups/bind",
            json={"line_user_id": "U-owner", "group_id": "C-new"},
        )
        unbound = client.post(
            "/api/guardian-groups/unbind",
            json={"line_user_id": "U-owner", "group_id": "C-family"},
        )

        self.assertEqual(bound.status_code, 401)
        self.assertEqual(unbound.status_code, 401)
        state = app.load_state(self.data_file)
        self.assertNotIn("C-new", state["guardian_groups"])
        self.assertIn("C-family", state["guardian_groups"])


if __name__ == "__main__":
    unittest.main()
