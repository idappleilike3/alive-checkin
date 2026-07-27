import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import app as app_module


class LineAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.fromisoformat("2026-07-27T16:00:00")
        self.state = {
            "users": {
                "U-beta": {
                    "line_user_id": "U-beta",
                    "display_name": "測試會員",
                    "membership_source": "beta",
                    "beta_cohort": "B799",
                    "beta_started_at": "2026-07-26T16:00:00",
                    "beta_ends_at": "2026-08-16T16:00:00",
                },
                "U-normal": {
                    "line_user_id": "U-normal",
                    "display_name": "正式會員",
                },
            }
        }

    def test_rejects_non_beta_member(self):
        with self.assertRaisesRegex(ValueError, "beta_member_required"):
            app_module.create_line_acceptance_case(
                self.state,
                {"line_user_id": "U-normal", "kind": "direct_message"},
                now=self.now,
            )

    def test_rejects_unknown_kind(self):
        with self.assertRaisesRegex(ValueError, "invalid_acceptance_kind"):
            app_module.create_line_acceptance_case(
                self.state,
                {"line_user_id": "U-beta", "kind": "arbitrary_push"},
                now=self.now,
            )

    def test_creates_pending_case_without_send_action(self):
        result = app_module.create_line_acceptance_case(
            self.state,
            {"line_user_id": "U-beta", "kind": "sos"},
            now=self.now,
        )

        self.assertTrue(result["created"])
        case = result["case"]
        self.assertEqual(case["manual_status"], "pending")
        self.assertEqual(case["system_status"], "awaiting_evidence")
        self.assertNotIn("send", case)
        self.assertNotEqual(case["member_ref"], "U-beta")

    def test_review_only_accepts_passed_or_failed(self):
        case = app_module.create_line_acceptance_case(
            self.state,
            {"line_user_id": "U-beta", "kind": "direct_message"},
            now=self.now,
        )["case"]

        with self.assertRaisesRegex(ValueError, "invalid_manual_status"):
            app_module.review_line_acceptance_case(
                self.state,
                case["case_id"],
                {"manual_status": "success"},
                now=self.now,
            )

        reviewed = app_module.review_line_acceptance_case(
            self.state,
            case["case_id"],
            {"manual_status": "passed", "note": "<img onerror=alert(1)>"},
            now=self.now,
        )["case"]
        self.assertEqual(reviewed["manual_status"], "passed")
        self.assertEqual(reviewed["note"], "<img onerror=alert(1)>")
        self.assertEqual(reviewed["reviewed_at"], self.now.isoformat(timespec="seconds"))

    def test_snapshot_reports_required_kinds_and_counts(self):
        created = app_module.create_line_acceptance_case(
            self.state,
            {"line_user_id": "U-beta", "kind": "family_group"},
            now=self.now,
        )["case"]
        app_module.review_line_acceptance_case(
            self.state,
            created["case_id"],
            {"manual_status": "passed"},
            now=self.now,
        )

        snapshot = app_module.line_acceptance_snapshot(self.state, self.now)

        self.assertEqual(snapshot["counts"]["passed"], 1)
        self.assertEqual(snapshot["counts"]["pending"], 0)
        self.assertIn("family_group", snapshot["requirements"]["B799"])
        self.assertNotIn("family_group", snapshot["requirements"]["B399"])

    def test_admin_api_requires_session_and_csrf_for_writes(self):
        with TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "state.json"
            app_module.save_state(data_file, self.state)
            client = app_module.create_app({
                "TESTING": True,
                "DATA_FILE": str(data_file),
                "ADMIN_PASSWORD": "very-strong-admin-password",
                "ADMIN_SESSION_SECRET": "test-session-secret-at-least-32-characters",
            }).test_client()
            payload = {"line_user_id": "U-beta", "kind": "direct_message"}

            self.assertEqual(client.get("/api/admin/line-acceptance").status_code, 401)
            self.assertEqual(
                client.post("/api/admin/line-acceptance", json=payload).status_code,
                401,
            )
            login = client.post(
                "/api/admin/login",
                json={"password": "very-strong-admin-password"},
            ).get_json()
            self.assertEqual(
                client.post("/api/admin/line-acceptance", json=payload).status_code,
                403,
            )
            response = client.post(
                "/api/admin/line-acceptance",
                json=payload,
                headers={"X-CSRF-Token": login["csrf_token"]},
            )
            self.assertEqual(response.status_code, 200)
            case_id = response.get_json()["case"]["case_id"]
            reviewed = client.patch(
                f"/api/admin/line-acceptance/{case_id}",
                json={"manual_status": "passed", "note": "手機已收到"},
                headers={"X-CSRF-Token": login["csrf_token"]},
            )
            self.assertEqual(reviewed.status_code, 200)
            snapshot = client.get("/api/admin/line-acceptance").get_json()
            self.assertEqual(snapshot["counts"]["passed"], 1)


if __name__ == "__main__":
    unittest.main()
