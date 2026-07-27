import tempfile
import unittest
from pathlib import Path

import app as alive_app


class AdminTestCenterTests(unittest.TestCase):
    def make_client(self, **overrides):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        sent = []
        config = {
            "TESTING": True,
            "DATA_FILE": str(Path(temp.name) / "state.json"),
            "ADMIN_PASSWORD": "very-strong-admin-password",
            "ADMIN_SESSION_SECRET": "test-session-secret-at-least-32-characters",
            "ALLOW_OPEN_ADMIN": "false",
            "TEST_LINE_USER_IDS": "U-test-1,U-test-2",
            "LINE_CHANNEL_ACCESS_TOKEN": "line-token",
            "LINE_PUSH_SENDER": lambda token, target, message, **kwargs: sent.append(
                (token, target, message)
            ),
        }
        config.update(overrides)
        return alive_app.create_app(config).test_client(), config["DATA_FILE"], sent

    def login(self, client):
        return client.post(
            "/api/admin/login",
            json={"password": "very-strong-admin-password"},
        ).get_json()

    def test_status_requires_admin_and_exposes_only_masked_whitelist(self):
        client, _, _ = self.make_client()
        self.assertEqual(client.get("/api/admin/test-center").status_code, 401)
        self.login(client)

        response = client.get("/api/admin/test-center")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data["test_accounts"]), 2)
        self.assertNotIn("U-test-1", str(data))
        self.assertTrue(data["integrations"]["line"]["configured"])
        self.assertEqual(len(data["tests"]), 10)

    def test_run_requires_csrf_and_rejects_non_whitelisted_recipient(self):
        client, _, _ = self.make_client()
        login = self.login(client)

        self.assertEqual(
            client.post(
                "/api/admin/test-center/run",
                json={"test_id": "daily_greeting", "line_user_id": "U-test-1"},
            ).status_code,
            403,
        )
        response = client.post(
            "/api/admin/test-center/run",
            json={"test_id": "daily_greeting", "line_user_id": "U-real-member"},
            headers={"X-CSRF-Token": login["csrf_token"]},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "test_recipient_not_allowed")

    def test_line_test_is_labeled_and_does_not_change_member_or_quota(self):
        client, data_file, sent = self.make_client()
        state = alive_app.load_state(data_file)
        state["users"]["U-test-1"] = {
            "line_user_id": "U-test-1",
            "plan": "399",
            "daily_push_count": 2,
        }
        alive_app.save_state(data_file, state)
        before = alive_app.load_state(data_file)["users"]["U-test-1"].copy()
        login = self.login(client)

        response = client.post(
            "/api/admin/test-center/run",
            json={"test_id": "beta_21_notice", "line_user_id": "U-test-1"},
            headers={"X-CSRF-Token": login["csrf_token"]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        self.assertEqual(len(sent), 1)
        self.assertIn("【測試模式】", str(sent[0][2]))
        after_state = alive_app.load_state(data_file)
        self.assertEqual(after_state["users"]["U-test-1"], before)
        self.assertEqual(after_state.get("test_center_runs")[-1]["status"], "success")
        self.assertNotIn("U-test-1", str(after_state["test_center_runs"][-1]))

    def test_payment_restore_is_simulation_only_and_never_calls_line(self):
        client, data_file, sent = self.make_client()
        alive_app.save_state(data_file, {
            "users": {"U-test-1": {"line_user_id": "U-test-1", "plan": "free"}},
            "orders": [],
        })
        login = self.login(client)

        response = client.post(
            "/api/admin/test-center/run",
            json={"test_id": "payment_restore", "line_user_id": "U-test-1"},
            headers={"X-CSRF-Token": login["csrf_token"]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["simulated"])
        self.assertEqual(sent, [])
        state = alive_app.load_state(data_file)
        self.assertEqual(state["users"]["U-test-1"]["plan"], "free")
        self.assertEqual(state["orders"], [])

    def test_unknown_test_is_rejected(self):
        client, _, _ = self.make_client()
        login = self.login(client)
        response = client.post(
            "/api/admin/test-center/run",
            json={"test_id": "charge_card", "line_user_id": "U-test-1"},
            headers={"X-CSRF-Token": login["csrf_token"]},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "unknown_test")


if __name__ == "__main__":
    unittest.main()
