import tempfile
import unittest
from pathlib import Path

import app as alive_app


class AdminResetTestAccountTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_file = Path(self.temp_dir.name) / "state.json"
        alive_app.save_state(
            self.data_file,
            {
                "users": {
                    "U-test": {
                        "line_user_id": "U-test",
                        "display_name": "測試會員",
                        "picture_url": "https://example.com/avatar.jpg",
                        "plan": "paid_799_year",
                        "payment_status": "active",
                        "trial_started_at": "2026-07-01T00:00:00",
                        "beta_cohort": "A",
                        "contacts": [
                            {
                                "name": "守護人",
                                "line_user_id": "U-guardian",
                                "bound": True,
                            }
                        ],
                        "reminder_time": "09:00",
                        "reminder_times": ["09:00"],
                        "onboarding_reminder_configured": True,
                        "is_onboarding_completed": True,
                        "history": ["2026-07-30"],
                        "checkin_records": [{"checked_at": "2026-07-30T09:00:00"}],
                    },
                    "U-guardian": {
                        "line_user_id": "U-guardian",
                        "contacts": [
                            {
                                "name": "測試會員",
                                "line_user_id": "U-test",
                                "bound": True,
                            },
                            {
                                "name": "舊版測試會員",
                                "line_id": "U-test",
                                "bound": True,
                            },
                        ],
                        "guarding_for": ["U-test"],
                    },
                },
                "orders": [
                    {
                        "order_id": "ORDER-1",
                        "line_user_id": "U-test",
                        "status": "paid",
                        "amount": 799,
                    }
                ],
                "admin_audit_logs": [{"action": "existing.audit"}],
                "account_migration_audit": [{"event_id": "migration-1"}],
                "guardian_invites": [
                    {
                        "id": "invite-1",
                        "inviter_line_user_id": "U-test",
                        "invitee_line_user_id": "U-guardian",
                    }
                ],
                "beta_program_members": [{"line_user_id": "U-test"}],
                "beta_feedback_reports": [{"line_user_id": "U-test"}],
                "notification_logs": [{"line_user_id": "U-test", "kind": "checkin"}],
                "contact_rewards": [{"contact_line_user_id": "U-test"}],
                "sos_pending": {"U-test": {"event_id": "sos-1"}},
                "sos_events": {
                    "sos-1": {"event_id": "sos-1", "line_user_id": "U-test"}
                },
                "guardian_groups": {
                    "G-owned": {"owner_line_user_id": "U-test", "members": ["U-test"]},
                    "G-other": {
                        "owner_line_user_id": "U-guardian",
                        "members": ["U-guardian", "U-test"],
                    },
                },
            },
        )

    def test_reset_clears_test_state_but_preserves_uid_orders_and_audits(self):
        result, code = alive_app.admin_reset_test_account(
            self.data_file,
            "U-test",
            allowed_test_user_ids={"U-test"},
        )

        self.assertEqual(code, 200)
        self.assertTrue(result["ok"])
        state = alive_app.load_state(self.data_file)
        profile = state["users"]["U-test"]
        self.assertEqual(profile["line_user_id"], "U-test")
        self.assertEqual(profile["display_name"], "測試會員")
        self.assertEqual(profile["picture_url"], "https://example.com/avatar.jpg")
        self.assertFalse(profile.get("is_onboarding_completed", False))
        self.assertEqual(profile["contacts"], [])
        self.assertEqual(profile["history"], [])
        self.assertEqual(profile["checkin_records"], [])
        self.assertIsNone(profile["trial_started_at"])
        self.assertEqual(profile["membership_source"], "")

        self.assertEqual(state["orders"][0]["order_id"], "ORDER-1")
        self.assertEqual(state["admin_audit_logs"], [{"action": "existing.audit"}])
        self.assertEqual(
            state["account_migration_audit"], [{"event_id": "migration-1"}]
        )
        self.assertEqual(state["guardian_invites"], [])
        self.assertEqual(state["beta_program_members"], [])
        self.assertEqual(state["beta_feedback_reports"], [])
        self.assertEqual(state["notification_logs"], [])
        self.assertEqual(state["contact_rewards"], [])
        self.assertNotIn("U-test", state["sos_pending"])
        self.assertNotIn("sos-1", state["sos_events"])
        self.assertNotIn("G-owned", state["guardian_groups"])
        self.assertEqual(
            state["guardian_groups"]["G-other"]["members"], ["U-guardian"]
        )
        self.assertEqual(state["users"]["U-guardian"]["contacts"], [])
        self.assertEqual(state["users"]["U-guardian"]["guarding_for"], [])

        registration, registration_code = alive_app.register_line_user(
            self.data_file,
            {
                "line_user_id": "U-test",
                "display_name": "測試會員",
                "picture_url": "https://example.com/avatar.jpg",
            },
        )
        self.assertEqual(registration_code, 200)
        self.assertEqual(registration["plan"], "trial")
        registered = alive_app.load_state(self.data_file)["users"]["U-test"]
        self.assertTrue(registered["trial_started_at"])
        self.assertTrue(registered["trial_end"])
        self.assertNotIn("test_reset_pending", registered)

    def test_reset_rejects_non_whitelisted_member(self):
        result, code = alive_app.admin_reset_test_account(
            self.data_file,
            "U-test",
            allowed_test_user_ids={"U-someone-else"},
        )

        self.assertEqual(code, 403)
        self.assertEqual(result["error"], "not_a_test_account")
        self.assertEqual(
            alive_app.load_state(self.data_file)["users"]["U-test"]["plan"],
            "paid_799_year",
        )

    def test_delete_test_account_removes_profile_checkins_and_peer_visibility(self):
        result, code = alive_app.admin_delete_test_account(
            self.data_file,
            "U-test",
            allowed_test_user_ids={"U-test"},
        )

        self.assertEqual(code, 200)
        self.assertTrue(result["ok"])
        state = alive_app.load_state(self.data_file)
        self.assertNotIn("U-test", state["users"])
        self.assertEqual(state["users"]["U-guardian"]["contacts"], [])
        self.assertEqual(state["users"]["U-guardian"].get("guarding_for") or [], [])
        self.assertEqual(state["guardian_invites"], [])
        self.assertNotIn("U-test", state["sos_pending"])
        self.assertNotIn("sos-1", state["sos_events"])
        self.assertNotIn("G-owned", state["guardian_groups"])
        self.assertEqual(state["guardian_groups"]["G-other"]["members"], ["U-guardian"])
        self.assertEqual(state["orders"][0]["line_user_id"], "deleted-test-user")
        self.assertEqual(state["admin_audit_logs"], [{"action": "existing.audit"}])
        self.assertEqual(
            state["account_migration_audit"], [{"event_id": "migration-1"}]
        )

    def test_delete_test_account_rejects_non_whitelisted_member(self):
        result, code = alive_app.admin_delete_test_account(
            self.data_file,
            "U-test",
            allowed_test_user_ids={"U-someone-else"},
        )

        self.assertEqual(code, 403)
        self.assertEqual(result["error"], "not_a_test_account")
        self.assertIn("U-test", alive_app.load_state(self.data_file)["users"])

    def test_admin_exposes_protected_delete_test_account_route(self):
        source = Path(alive_app.__file__).read_text(encoding="utf-8")

        self.assertIn(
            '@app.delete("/api/admin/test-accounts/<line_user_id>")', source
        )
        self.assertIn(
            '_admin_guard(write=True, permission="member.manage")', source
        )
        self.assertIn("admin_delete_test_account(", source)

    def test_admin_ui_has_explicit_delete_test_account_action(self):
        page = Path("admin.html").read_text(encoding="utf-8")

        self.assertIn('data-action="delete-test-account"', page)
        self.assertIn("async function deleteTestAccount", page)
        self.assertIn('method: "DELETE"', page)

    def test_admin_route_requires_member_permission_csrf_and_test_whitelist(self):
        application = alive_app.create_app(
            {
                "TESTING": True,
                "DATA_FILE": str(self.data_file),
                "ADMIN_PASSWORD": "very-strong-admin-password",
                "ADMIN_SESSION_SECRET": "test-session-secret-at-least-32-characters",
                "TEST_LINE_USER_IDS": "U-test",
            }
        )
        client = application.test_client()
        if application.__class__.__name__ == "MiniApp":
            source = Path(alive_app.__file__).read_text(encoding="utf-8")
            self.assertIn(
                '@app.post("/api/admin/test-accounts/<line_user_id>/reset")',
                source,
            )
            self.assertIn(
                '_admin_guard(write=True, permission="member.manage")',
                source,
            )
            return

        self.assertEqual(
            client.post(
                "/api/admin/test-accounts/U-test/reset",
                json={"confirm": True},
            ).status_code,
            401,
        )
        login = client.post(
            "/api/admin/login",
            json={"password": "very-strong-admin-password"},
        ).get_json()
        self.assertEqual(
            client.post(
                "/api/admin/test-accounts/U-test/reset",
                json={"confirm": True},
            ).status_code,
            403,
        )
        response = client.post(
            "/api/admin/test-accounts/U-test/reset",
            json={"confirm": True},
            headers={"X-CSRF-Token": login["csrf_token"]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["billing_preserved"])


if __name__ == "__main__":
    unittest.main()
