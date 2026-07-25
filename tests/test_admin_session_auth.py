import tempfile
import unittest
from pathlib import Path

import app as alive_app


class AdminSessionAuthTests(unittest.TestCase):
    def make_client(self, **overrides):
        alive_app.ADMIN_LOGIN_ATTEMPTS.clear()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        config = {
            "TESTING": True,
            "DATA_FILE": str(Path(temp.name) / "state.json"),
            "ADMIN_PASSWORD": "very-strong-admin-password",
            "ADMIN_SESSION_SECRET": "test-session-secret-at-least-32-characters",
            "ALLOW_OPEN_ADMIN": "false",
        }
        config.update(overrides)
        return alive_app.create_app(config).test_client(), config["DATA_FILE"]

    def login(self, client, password="very-strong-admin-password"):
        return client.post("/api/admin/login", json={"password": password})

    def test_empty_password_fails_closed(self):
        client, _ = self.make_client(ADMIN_PASSWORD="", ALLOW_OPEN_ADMIN="true")
        response = client.get("/api/admin/summary")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"], "admin_not_configured")

    def test_summary_requires_session_and_rejects_query_password(self):
        client, _ = self.make_client()
        self.assertEqual(client.get("/api/admin/summary").status_code, 401)
        self.assertEqual(
            client.get("/api/admin/summary?password=very-strong-admin-password").status_code,
            401,
        )

    def test_login_creates_session_and_logout_invalidates_it(self):
        client, _ = self.make_client()
        login = self.login(client)
        self.assertEqual(login.status_code, 200)
        self.assertTrue(login.get_json()["csrf_token"])
        self.assertEqual(client.get("/api/admin/summary").status_code, 200)
        self.assertEqual(client.post("/api/admin/logout").status_code, 200)
        self.assertEqual(client.get("/api/admin/summary").status_code, 401)

    def test_write_route_requires_csrf(self):
        client, _ = self.make_client()
        login = self.login(client).get_json()
        self.assertEqual(client.post("/api/admin/backups").status_code, 403)
        allowed = client.post(
            "/api/admin/backups",
            headers={"X-CSRF-Token": login["csrf_token"]},
        )
        self.assertEqual(allowed.status_code, 200)

    def test_wrong_password_is_rejected_without_secret_leak(self):
        client, _ = self.make_client()
        response = self.login(client, "wrong")
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("wrong", response.get_data(as_text=True))
        self.assertNotIn("very-strong", response.get_data(as_text=True))

    def test_sixth_failed_login_is_rate_limited(self):
        client, _ = self.make_client()
        for _ in range(5):
            self.assertEqual(self.login(client, "wrong").status_code, 401)
        self.assertEqual(self.login(client, "wrong").status_code, 429)

    def test_admin_mutation_is_audited_without_credentials(self):
        client, data_file = self.make_client()
        token = self.login(client).get_json()["csrf_token"]
        client.post("/api/admin/backups", headers={"X-CSRF-Token": token})
        state = alive_app.load_state(data_file)
        logs = state.get("admin_audit_logs") or []
        self.assertEqual(logs[-1]["action"], "backup.create")
        self.assertNotIn("password", str(logs[-1]).lower())
        self.assertNotIn("csrf", str(logs[-1]).lower())
