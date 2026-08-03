import tempfile
import unittest
from pathlib import Path

import app as alive_app


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


if __name__ == "__main__":
    unittest.main()
