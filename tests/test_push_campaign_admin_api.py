import tempfile
import unittest
from pathlib import Path

import app as alive_app


class PushCampaignAdminApiTests(unittest.TestCase):
    def setUp(self):
        alive_app.ADMIN_LOGIN_ATTEMPTS.clear()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_file = str(Path(self.temp_dir.name) / "state.json")
        self.app = alive_app.create_app(
            {
                "TESTING": True,
                "DATA_FILE": self.data_file,
                "ADMIN_PASSWORD": "super-admin-password-very-strong",
                "ADMIN_OPERATIONS_PASSWORD": "operations-password-very-strong",
                "ADMIN_FINANCE_PASSWORD": "finance-password-very-strong",
                "ADMIN_VIEWER_PASSWORD": "viewer-password-very-strong",
                "ADMIN_SESSION_SECRET": "test-session-secret-at-least-32-characters",
                "ALLOW_OPEN_ADMIN": "false",
                "ENABLE_INTERNAL_SCHEDULER": "0",
            }
        )

    def client_for(self, role):
        password = {
            "super_admin": "super-admin-password-very-strong",
            "operations": "operations-password-very-strong",
            "finance": "finance-password-very-strong",
            "viewer": "viewer-password-very-strong",
        }[role]
        client = self.app.test_client()
        response = client.post("/api/admin/login", json={"password": password})
        self.assertEqual(response.status_code, 200)
        return client, response.get_json()["csrf_token"]

    def create_payload(self):
        return {
            "name": "七日提醒",
            "content_type": "text",
            "text": "記得把每日平安置頂",
            "plan_audiences": ["paid_799"],
            "explicit_member_ids": [],
        }

    def create_campaign(self, client, csrf):
        response = client.post(
            "/api/admin/push-campaigns",
            json=self.create_payload(),
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status_code, 201)
        return response.get_json()["campaign"]

    def test_read_routes_require_login(self):
        client = self.app.test_client()
        for route in (
            "/api/admin/push-campaigns",
            "/api/admin/push-deliveries",
            "/api/admin/push-options",
        ):
            with self.subTest(route=route):
                self.assertEqual(client.get(route).status_code, 401)

    def test_every_authenticated_role_can_read(self):
        for role in ("super_admin", "operations", "finance", "viewer"):
            with self.subTest(role=role):
                client, _ = self.client_for(role)
                response = client.get("/api/admin/push-campaigns")
                self.assertEqual(response.status_code, 200)
                self.assertIn("campaigns", response.get_json())

    def test_only_super_admin_can_create(self):
        for role in ("operations", "finance", "viewer"):
            with self.subTest(role=role):
                client, csrf = self.client_for(role)
                response = client.post(
                    "/api/admin/push-campaigns",
                    json=self.create_payload(),
                    headers={"X-CSRF-Token": csrf},
                )
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.get_json()["required_role"], "super_admin")

        client, csrf = self.client_for("super_admin")
        response = client.post(
            "/api/admin/push-campaigns",
            json=self.create_payload(),
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["campaign"]["status"], "draft")

    def test_super_admin_mutation_requires_csrf(self):
        client, _ = self.client_for("super_admin")
        response = client.post("/api/admin/push-campaigns", json=self.create_payload())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "csrf_required")

    def test_lifecycle_routes_create_versions_and_invalidate_schedule_on_edit(self):
        client, csrf = self.client_for("super_admin")
        campaign = self.create_campaign(client, csrf)
        campaign_id = campaign["id"]

        prepared = client.post(
            f"/api/admin/push-campaigns/{campaign_id}/prepare",
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(prepared.status_code, 200)
        scheduled = client.post(
            f"/api/admin/push-campaigns/{campaign_id}/schedule",
            json={"scheduled_at": "2099-08-02T09:00:00"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(scheduled.status_code, 200)
        edited = client.post(
            f"/api/admin/push-campaigns/{campaign_id}/edit",
            json={"text": "修改後內容"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(edited.get_json()["campaign"]["status"], "pending_schedule")
        self.assertEqual(edited.get_json()["campaign"]["current_version"], 2)

        detail = client.get(f"/api/admin/push-campaigns/{campaign_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(len(detail.get_json()["versions"]), 2)
        self.assertEqual(detail.get_json()["versions"][0]["text"], "記得把每日平安置頂")
        self.assertEqual(detail.get_json()["versions"][1]["text"], "修改後內容")

    def test_cancel_route_requires_super_admin(self):
        super_client, super_csrf = self.client_for("super_admin")
        campaign = self.create_campaign(super_client, super_csrf)
        operations_client, operations_csrf = self.client_for("operations")

        denied = operations_client.post(
            f"/api/admin/push-campaigns/{campaign['id']}/cancel",
            json={"reason_zh": "取消測試"},
            headers={"X-CSRF-Token": operations_csrf},
        )
        self.assertEqual(denied.status_code, 403)
        allowed = super_client.post(
            f"/api/admin/push-campaigns/{campaign['id']}/cancel",
            json={"reason_zh": "最高管理員取消測試排程。"},
            headers={"X-CSRF-Token": super_csrf},
        )
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.get_json()["campaign"]["status"], "cancelled")

    def test_arbitrary_flex_json_is_rejected(self):
        client, csrf = self.client_for("super_admin")
        payload = self.create_payload()
        payload.update(content_type="template", template_key="unknown", flex_json={"type": "flex"})
        response = client.post(
            "/api/admin/push-campaigns",
            json=payload,
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status_code, 400)

    def test_no_immediate_send_or_immutable_row_mutation_routes_exist(self):
        client, csrf = self.client_for("super_admin")
        campaign = self.create_campaign(client, csrf)
        routes = (
            f"/api/admin/push-campaigns/{campaign['id']}/send",
            "/api/admin/push-deliveries/delivery-id",
            f"/api/admin/push-campaigns/{campaign['id']}/versions/version-id",
        )
        for route in routes:
            with self.subTest(route=route, method="post"):
                self.assertIn(
                    client.post(route, headers={"X-CSRF-Token": csrf}).status_code,
                    {404, 405},
                )
            with self.subTest(route=route, method="delete"):
                self.assertIn(
                    client.delete(route, headers={"X-CSRF-Token": csrf}).status_code,
                    {404, 405},
                )

    def test_delivery_filters_and_limit_do_not_trim_storage(self):
        state = alive_app.load_state(self.data_file)
        state["push_delivery_records"] = [
            {
                "id": f"D{index}",
                "source": "campaign" if index % 2 == 0 else "system",
                "kind": "campaign" if index % 2 == 0 else "sos",
                "campaign_id": "C1" if index % 2 == 0 else "",
                "recipient_display_name": "小安" if index == 0 else "其他會員",
                "line_user_id": f"U{index}",
                "audience_code": "paid_799",
                "plan": "paid_799",
                "status": "sent" if index != 2 else "failed",
                "scheduled_at": f"2026-08-0{index + 1}T09:00:00",
                "sent_at": f"2026-08-0{index + 1}T09:00:01",
            }
            for index in range(4)
        ]
        alive_app.save_state(self.data_file, state)
        client, _ = self.client_for("viewer")

        response = client.get(
            "/api/admin/push-deliveries",
            query_string={"source": "campaign", "status": "sent", "member": "小安", "limit": 1},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.get_json()["deliveries"]], ["D0"])
        self.assertEqual(len(alive_app.load_state(self.data_file)["push_delivery_records"]), 4)


if __name__ == "__main__":
    unittest.main()
