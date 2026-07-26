import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app as alive_app
import line_auth


class ProviderVerificationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.config = {
            "TESTING": True,
            "DATA_FILE": str(Path(self.tempdir.name) / "state.json"),
            "LEGACY_LINE_LOGIN_CHANNEL_ID": "2010674803",
            "LEGACY_LIFF_ID": "2010674803-rK98c0lo",
            "LINE_LOGIN_CHANNEL_ID": "2010848330",
            "ACCOUNT_MIGRATION_SECRET": "test-only-secret",
        }

    def test_start_rejects_token_verified_for_current_channel(self):
        client_ids = []

        def verify_current_only(_id_token, client_id):
            client_ids.append(client_id)
            if client_id == "2010848330":
                return "U-current-provider"
            return None

        app = alive_app.create_app(self.config)
        with mock.patch.object(
            alive_app,
            "verify_line_id_token_for_channel",
            side_effect=verify_current_only,
            create=True,
        ):
            response = app.test_client().post(
                "/api/account-migration/start",
                headers={"Authorization": "Bearer test-current-token"},
                json={"line_user_id": "client-claimed-id"},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json(), {"ok": False, "error": "invalid_token"})
        self.assertEqual(client_ids, ["2010674803"])
        self.assertNotIn("test-current-token", response.get_data(as_text=True))
        self.assertNotIn("client-claimed-id", response.get_data(as_text=True))

    def test_redeem_rejects_token_verified_for_legacy_channel(self):
        client_ids = []

        def verify_legacy_only(_id_token, client_id):
            client_ids.append(client_id)
            if client_id == "2010674803":
                return "U-legacy-provider"
            return None

        app = alive_app.create_app(self.config)
        with mock.patch.object(
            alive_app,
            "verify_line_id_token_for_channel",
            side_effect=verify_legacy_only,
            create=True,
        ):
            response = app.test_client().post(
                "/api/account-migration/redeem",
                headers={"Authorization": "Bearer test-legacy-token"},
                json={
                    "line_user_id": "client-claimed-id",
                    "migration_code": "test-raw-code",
                },
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json(), {"ok": False, "error": "invalid_token"})
        self.assertEqual(client_ids, ["2010848330"])
        response_text = response.get_data(as_text=True)
        self.assertNotIn("test-legacy-token", response_text)
        self.assertNotIn("client-claimed-id", response_text)
        self.assertNotIn("test-raw-code", response_text)

    def test_migration_endpoints_fail_closed_when_secret_or_channel_missing(self):
        for missing_key in (
            "LEGACY_LINE_LOGIN_CHANNEL_ID",
            "LINE_LOGIN_CHANNEL_ID",
            "ACCOUNT_MIGRATION_SECRET",
        ):
            config = {**self.config, missing_key: ""}
            app = alive_app.create_app(config)
            with self.subTest(missing_key=missing_key):
                with mock.patch.object(
                    alive_app,
                    "verify_line_id_token_for_channel",
                    side_effect=AssertionError("verifier must not run"),
                    create=True,
                ):
                    client = app.test_client()
                    for endpoint in (
                        "/api/account-migration/start",
                        "/api/account-migration/redeem",
                    ):
                        response = client.post(
                            endpoint,
                            headers={"Authorization": "Bearer test-token"},
                            json={"migration_code": "test-code"},
                        )
                        self.assertEqual(response.status_code, 503)
                        self.assertEqual(
                            response.get_json(),
                            {"ok": False, "error": "migration_unavailable"},
                        )

    def test_channel_explicit_verifier_returns_only_verified_subject(self):
        calls = []

        def verifier(id_token, client_id):
            calls.append((id_token, client_id))
            return {"sub": " U-server-verified "}

        result = line_auth.verify_line_id_token_for_channel(
            " token ",
            " 2010674803 ",
            verify_fn=verifier,
        )

        self.assertEqual(result, "U-server-verified")
        self.assertEqual(calls, [("token", "2010674803")])


if __name__ == "__main__":
    unittest.main()
