import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import app as alive_app


class FinancePersistenceHelperTests(unittest.TestCase):
    def make_data_file(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return str(Path(temp.name) / "state.json")

    def test_persisted_dashboard_atomically_creates_one_audited_timestamped_seed(self):
        data_file = self.make_data_file()
        clock = datetime(2026, 8, 20, 12, 0, 0)
        config = {"DATA_FILE": data_file, "CRON_NOW": clock, "APP_TIMEZONE": "Asia/Taipei"}

        first = alive_app.persisted_finance_dashboard(data_file, "2026-08", config)
        first_revision = alive_app.load_state(data_file)["_state_revision"]
        second = alive_app.persisted_finance_dashboard(data_file, "2026-08", config)
        second_revision = alive_app.load_state(data_file)["_state_revision"]

        self.assertEqual(first["essential_services"], second["essential_services"])
        self.assertEqual(second_revision, first_revision)
        state = alive_app.load_state(data_file)
        seeds = [
            row for row in state["finance"]["essential_services"]
            if row["id"] == "render-postgresql-alive-checkin-state"
        ]
        self.assertEqual(len(seeds), 1)
        self.assertEqual(seeds[0]["created_at"], "2026-08-20T12:00:00")
        create_events = [
            row for row in state["finance"]["audit"]
            if row["action"] == "essential_service.create"
            and row["target_id"] == seeds[0]["id"]
        ]
        self.assertEqual(len(create_events), 1)
        self.assertEqual(create_events[0]["created_at"], "2026-08-20T12:00:00")

    def test_persisted_dashboard_uses_taiwan_calendar_across_local_midnight(self):
        before_file = self.make_data_file()
        after_file = self.make_data_file()

        before = alive_app.persisted_finance_dashboard(
            before_file,
            "2026-08",
            {"CRON_NOW": datetime(2026, 8, 22, 23, 59), "APP_TIMEZONE": "Asia/Taipei"},
        )
        after = alive_app.persisted_finance_dashboard(
            after_file,
            "2026-08",
            {"CRON_NOW": datetime(2026, 8, 23, 0, 1), "APP_TIMEZONE": "Asia/Taipei"},
        )

        before_seed = before["essential_services"]["items"][0]
        after_seed = after["essential_services"]["items"][0]
        self.assertEqual(before_seed["days_remaining"], 1)
        self.assertEqual(after_seed["days_remaining"], 0)
        self.assertEqual(before_seed["reminder_history"][-1]["status"], "due")
        self.assertEqual(after_seed["reminder_history"][-1]["status"], "missed")


@unittest.skipIf(alive_app.Flask is None, "Flask dependency is not installed in the offline test runtime")
class FinanceApiTests(unittest.TestCase):
    def make_client(self, role="super_admin"):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        passwords = {
            "super_admin": ("ADMIN_PASSWORD", "super-admin-password-long"),
            "finance": ("ADMIN_FINANCE_PASSWORD", "finance-password-long-enough"),
            "operations": ("ADMIN_OPERATIONS_PASSWORD", "operations-password-long"),
        }
        key, password = passwords[role]
        config = {
            "TESTING": True,
            "DATA_FILE": str(Path(temp.name) / "state.json"),
            "CRON_NOW": datetime(2026, 8, 20, 12, 0, 0),
            "APP_TIMEZONE": "Asia/Taipei",
            "ADMIN_PASSWORD": "super-admin-password-long",
            "ADMIN_SESSION_SECRET": "finance-test-session-secret-at-least-32",
            "ALLOW_OPEN_ADMIN": "false",
            key: password,
        }
        client = alive_app.create_app(config).test_client()
        return client, config["DATA_FILE"], password

    @staticmethod
    def login(client, password):
        response = client.post("/api/admin/login", json={"password": password})
        return response.get_json()

    def test_dashboard_requires_finance_permission(self):
        client, _, _ = self.make_client()
        self.assertEqual(client.get("/api/admin/finance/dashboard?month=2026-08").status_code, 401)

        operations, _, password = self.make_client("operations")
        self.login(operations, password)
        self.assertEqual(operations.get("/api/admin/finance/dashboard?month=2026-08").status_code, 403)

    def test_finance_role_can_read_and_create_with_csrf(self):
        client, data_file, password = self.make_client("finance")
        login = self.login(client, password)
        response = client.get("/api/admin/finance/dashboard?month=2026-08")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["month"], "2026-08")
        self.assertEqual(client.get("/api/admin/finance/dashboard?month=2026-08").status_code, 200)
        seeded = alive_app.load_state(data_file)
        self.assertEqual(len(seeded["finance"]["essential_services"]), 1)
        self.assertEqual(
            len([
                row for row in seeded["finance"]["audit"]
                if row["action"] == "essential_service.create"
                and row["target_id"] == "render-postgresql-alive-checkin-state"
            ]),
            1,
        )

        self.assertEqual(client.post("/api/admin/finance/expenses", json={}).status_code, 403)
        created = client.post(
            "/api/admin/finance/expenses",
            json={"name": "Render", "amount": 1050, "category": "hosting", "expense_type": "fixed", "incurred_on": "2026-08-01"},
            headers={"X-CSRF-Token": login["csrf_token"]},
        )
        self.assertEqual(created.status_code, 201)
        state = alive_app.load_state(data_file)
        self.assertEqual(state["finance"]["expenses"][0]["name"], "Render")
        self.assertEqual(state["finance"]["audit"][-1]["action"], "expense.create")

    def test_invalid_finance_input_returns_chinese_error_without_stack(self):
        client, _, password = self.make_client()
        login = self.login(client, password)
        response = client.post(
            "/api/admin/finance/expenses",
            json={"name": "<script>x</script>", "amount": -1},
            headers={"X-CSRF-Token": login["csrf_token"]},
        )
        self.assertEqual(response.status_code, 400)
        body = response.get_json()
        self.assertIn("message", body)
        self.assertNotIn("traceback", str(body).lower())

    def test_essential_service_routes_require_finance_permission_and_valid_csrf(self):
        client, _, _ = self.make_client()
        self.assertEqual(client.post("/api/admin/finance/services", json={}).status_code, 401)
        self.assertEqual(client.put("/api/admin/finance/services/missing", json={}).status_code, 401)

        operations, _, operations_password = self.make_client("operations")
        operations_login = self.login(operations, operations_password)
        self.assertEqual(
            operations.post(
                "/api/admin/finance/services",
                json={},
                headers={"X-CSRF-Token": operations_login["csrf_token"]},
            ).status_code,
            403,
        )
        self.assertEqual(
            operations.put(
                "/api/admin/finance/services/missing",
                json={},
                headers={"X-CSRF-Token": operations_login["csrf_token"]},
            ).status_code,
            403,
        )

        finance, _, finance_password = self.make_client("finance")
        self.login(finance, finance_password)
        self.assertEqual(finance.post("/api/admin/finance/services", json={}).status_code, 403)
        self.assertEqual(finance.put("/api/admin/finance/services/missing", json={}).status_code, 403)
        self.assertEqual(
            finance.post(
                "/api/admin/finance/services",
                json={},
                headers={"X-CSRF-Token": "not-the-session-token"},
            ).status_code,
            403,
        )
        self.assertEqual(
            finance.put(
                "/api/admin/finance/services/missing",
                json={},
                headers={"X-CSRF-Token": "not-the-session-token"},
            ).status_code,
            403,
        )

    def test_finance_manager_can_create_and_update_essential_service_persistently(self):
        client, data_file, password = self.make_client("finance")
        login = self.login(client, password)
        headers = {"X-CSRF-Token": login["csrf_token"]}
        created = client.post(
            "/api/admin/finance/services",
            json={
                "vendor": "Example Cloud",
                "name": "primary database",
                "category": "database",
                "billing_cycle": "monthly",
                "currency": "USD",
                "original_amount": 6.3,
                "payment_url": "https://billing.example.test/plan",
                "status": "pending",
                "priority": "critical",
                "monthly_usd": 6.3,
                "monthly_twd": 210,
                "annual_twd": 2520,
                "deadline": "2026-08-23",
                "next_renewal_on": "2026-09-23",
                "reminder_days": [30, 14, 7, 3, 1],
                "risk": "期限前需確認方案",
                "note": "尚未扣款",
            },
            headers=headers,
        )
        self.assertEqual(created.status_code, 201)
        service = created.get_json()["service"]
        self.assertEqual(service["vendor"], "Example Cloud")
        self.assertEqual(service["annual_twd"], 2520)
        self.assertEqual(service["created_at"], "2026-08-20T12:00:00")

        updated = client.put(
            f"/api/admin/finance/services/{service['id']}",
            json={"status": "paid", "reminder_days": [7, 1]},
            headers=headers,
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["service"]["status"], "paid")
        self.assertTrue(Path(data_file).exists())
        state = alive_app.load_state(data_file)
        saved = next(row for row in state["finance"]["essential_services"] if row["id"] == service["id"])
        self.assertEqual(saved["status"], "paid")
        self.assertEqual(
            [row["action"] for row in state["finance"]["audit"][-2:]],
            ["essential_service.create", "essential_service.update"],
        )

    def test_essential_service_rejects_invalid_url_with_chinese_message_without_traceback(self):
        client, _, password = self.make_client("finance")
        login = self.login(client, password)
        response = client.post(
            "/api/admin/finance/services",
            json={
                "vendor": "Bad URL",
                "name": "bad-url-service",
                "payment_url": "https://billing-user:billing-secret@billing.example.test/plan",
                "status": "pending",
                "priority": "critical",
                "monthly_twd": 10,
                "deadline": "2026-09-01",
            },
            headers={"X-CSRF-Token": login["csrf_token"]},
        )
        self.assertEqual(response.status_code, 400)
        body = response.get_json()
        self.assertEqual(body["error"], "invalid_finance_request")
        self.assertRegex(body["message"], r"[\u4e00-\u9fff]")
        self.assertNotIn("traceback", str(body).lower())

    def test_essential_service_rejects_malformed_url_with_chinese_message_without_traceback(self):
        client, _, password = self.make_client("finance")
        login = self.login(client, password)
        response = client.post(
            "/api/admin/finance/services",
            json={
                "vendor": "Malformed URL",
                "name": "malformed-url-service",
                "payment_url": "https://[bad",
                "status": "pending",
                "priority": "critical",
                "monthly_twd": 10,
                "deadline": "2026-09-01",
            },
            headers={"X-CSRF-Token": login["csrf_token"]},
        )
        self.assertEqual(response.status_code, 400)
        body = response.get_json()
        self.assertEqual(body["error"], "invalid_finance_request")
        self.assertRegex(body["message"], r"[\u4e00-\u9fff]")
        self.assertNotIn("traceback", str(body).lower())

    def test_essential_service_requires_a_json_object(self):
        client, _, password = self.make_client("finance")
        login = self.login(client, password)
        response = client.post(
            "/api/admin/finance/services",
            json=[],
            headers={"X-CSRF-Token": login["csrf_token"]},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "invalid_finance_request")


if __name__ == "__main__":
    unittest.main()
