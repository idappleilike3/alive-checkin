import tempfile
import unittest
from pathlib import Path

import app as alive_app


class AdminLineRebindTests(unittest.TestCase):
    def setUp(self):
        alive_app.ADMIN_LOGIN_ATTEMPTS.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data_file = str(Path(self.temp.name) / "state.json")
        self.config = {
            "TESTING": True,
            "DATA_FILE": self.data_file,
            "ADMIN_PASSWORD": "very-strong-admin-password",
            "ADMIN_SESSION_SECRET": "test-session-secret-at-least-32-characters",
            "ACCOUNT_MIGRATION_SECRET": "test-only-migration-secret-32bytes",
            "LEGACY_LINE_LOGIN_CHANNEL_ID": "legacy-channel",
            "LINE_LOGIN_CHANNEL_ID": "current-channel",
            "LIFF_ID": "2010848330-UAiqPPYD",
        }
        state = alive_app.load_state(self.data_file)
        state["users"]["U-old-rourou"] = {
            **alive_app.DEFAULT_PROFILE,
            "line_user_id": "U-old-rourou",
            "display_name": "柔柔",
            "plan": "trial",
            "membership_source": "public_trial",
            "trial_end": "2026-08-12T12:00:00+08:00",
            "contacts": [{"id": "guardian-1", "name": "家人"}],
            "checkins": ["2026-08-02T12:00:00+08:00"],
        }
        alive_app.save_state(self.data_file, state)

    def test_issue_rebind_link_is_one_time_and_hides_old_uid(self):
        body, code = alive_app.admin_create_line_rebind_link(
            self.data_file,
            "U-old-rourou",
            self.config,
        )
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["status"], "pending")
        self.assertGreater(body["expires_in"], 0)
        self.assertIn("https://liff.line.me/2010848330-UAiqPPYD", body["rebind_url"])
        self.assertIn("migration_code=", body["rebind_url"])
        self.assertNotIn("U-old-rourou", body["rebind_url"])
        migration_code = body["rebind_url"].split("migration_code=", 1)[1].split("&", 1)[0]
        ticket, error = alive_app.validate_account_migration_ticket(
            alive_app.load_state(self.data_file),
            migration_code,
            self.config["ACCOUNT_MIGRATION_SECRET"],
        )
        self.assertIsNone(error)
        self.assertEqual(ticket["old_line_user_id"], "U-old-rourou")

    def test_admin_route_is_permission_and_csrf_guarded(self):
        source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn('@app.get("/api/admin/members/<line_user_id>/line-rebind")', source)
        route = source.split('@app.post("/api/admin/members/<line_user_id>/line-rebind")', 1)[1]
        route = route.split("@app.", 1)[0]
        self.assertIn('_admin_guard(write=True, permission="member.manage")', route)
        self.assertIn("admin_create_line_rebind_link", route)

    def test_rebind_replaces_uid_but_keeps_membership_and_history(self):
        body, code = alive_app.admin_create_line_rebind_link(
            self.data_file,
            "U-old-rourou",
            self.config,
        )
        self.assertEqual(code, 200)
        migration_code = body["rebind_url"].split("migration_code=", 1)[1].split("&", 1)[0]
        result, redeem_code = alive_app.redeem_account_migration_ticket(
            self.data_file,
            migration_code,
            "U-new-rourou",
            self.config,
        )
        self.assertEqual(redeem_code, 200)
        self.assertEqual(result["status"], "migrated")
        state = alive_app.load_state(self.data_file)
        self.assertNotIn("U-old-rourou", state["users"])
        rebound = state["users"]["U-new-rourou"]
        self.assertEqual(rebound["plan"], "trial")
        self.assertEqual(rebound["trial_end"], "2026-08-12T12:00:00+08:00")
        self.assertEqual(rebound["contacts"][0]["name"], "家人")
        self.assertEqual(rebound["checkins"], ["2026-08-02T12:00:00+08:00"])
        self.assertEqual(
            state["account_migration_aliases"]["U-old-rourou"]["status"],
            "disabled",
        )

    def test_rebind_moves_only_future_push_targets_to_new_uid(self):
        state = alive_app.load_state(self.data_file)
        state["push_campaign_versions"] = [{
            "id": "version-1",
            "explicit_member_ids": ["U-old-rourou", "U-other"],
        }]
        state["push_delivery_records"] = [
            {"id": "pending", "status": "pending", "line_user_id": "U-old-rourou"},
            {"id": "retry", "status": "retry", "line_user_id": "U-old-rourou"},
            {"id": "sent", "status": "sent", "line_user_id": "U-old-rourou"},
            {"id": "failed", "status": "failed", "line_user_id": "U-old-rourou"},
        ]
        alive_app.save_state(self.data_file, state)
        body, code = alive_app.admin_create_line_rebind_link(
            self.data_file,
            "U-old-rourou",
            self.config,
        )
        self.assertEqual(code, 200)
        migration_code = body["rebind_url"].split("migration_code=", 1)[1].split("&", 1)[0]

        result, redeem_code = alive_app.redeem_account_migration_ticket(
            self.data_file,
            migration_code,
            "U-new-rourou",
            self.config,
        )

        self.assertEqual(redeem_code, 200)
        self.assertEqual(result["status"], "migrated")
        rebound = alive_app.load_state(self.data_file)
        self.assertEqual(
            rebound["push_campaign_versions"][0]["explicit_member_ids"],
            ["U-new-rourou", "U-other"],
        )
        deliveries = {
            row["id"]: row for row in rebound["push_delivery_records"]
        }
        self.assertEqual(deliveries["pending"]["line_user_id"], "U-new-rourou")
        self.assertEqual(deliveries["retry"]["line_user_id"], "U-new-rourou")
        self.assertEqual(deliveries["sent"]["line_user_id"], "U-old-rourou")
        self.assertEqual(deliveries["failed"]["line_user_id"], "U-old-rourou")

    def test_admin_page_has_member_rebind_action(self):
        page = Path("admin.html").read_text(encoding="utf-8")
        self.assertIn("更新／重新綁定 LINE 身分", page)
        self.assertIn('data-action="line-rebind"', page)
        self.assertIn("issueLineRebind", page)


if __name__ == "__main__":
    unittest.main()
