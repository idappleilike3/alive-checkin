import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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


class TicketLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.data_file = str(Path(self.tempdir.name) / "state.json")
        self.old_line_user_id = "U0123456789abcdef0123456789abcdef"
        self.claimed_line_user_id = "Ufedcba9876543210fedcba9876543210"
        self.config = {
            "TESTING": True,
            "DATA_FILE": self.data_file,
            "LEGACY_LINE_LOGIN_CHANNEL_ID": "2010674803",
            "LEGACY_LIFF_ID": "2010674803-rK98c0lo",
            "LINE_LOGIN_CHANNEL_ID": "2010848330",
            "ACCOUNT_MIGRATION_SECRET": "test-only-secret",
            "ACCOUNT_MIGRATION_TTL_SECONDS": 600,
        }
        state = alive_app.load_state(self.data_file)
        state["users"][self.old_line_user_id] = {
            **alive_app.DEFAULT_PROFILE,
            "line_user_id": self.old_line_user_id,
            "display_name": "Legacy member",
        }
        alive_app.save_state(self.data_file, state)

    def _start(self):
        app = alive_app.create_app(self.config)
        with mock.patch.object(
            alive_app,
            "verify_line_id_token_for_channel",
            return_value=self.old_line_user_id,
        ):
            return app.test_client().post(
                "/api/account-migration/start",
                headers={"Authorization": "Bearer legacy-id-token"},
                json={"line_user_id": self.claimed_line_user_id},
            )

    def test_start_returns_random_code_but_stores_only_digest(self):
        first = self._start()
        second = self._start()

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.headers.get("Cache-Control"), "no-store")
        first_body = first.get_json()
        second_body = second.get_json()
        self.assertEqual(set(first_body), {"ok", "migration_code", "expires_in"})
        self.assertTrue(first_body["ok"])
        self.assertEqual(first_body["expires_in"], 600)
        self.assertNotEqual(
            first_body["migration_code"],
            second_body["migration_code"],
        )

        state = alive_app.load_state(self.data_file)
        tickets = list(state["account_migration_tickets"].values())
        self.assertEqual(len(tickets), 2)
        self.assertEqual(
            [ticket["status"] for ticket in tickets],
            ["expired", "pending"],
        )
        self.assertNotEqual(tickets[0]["code_digest"], tickets[1]["code_digest"])
        serialized = json.dumps(state, ensure_ascii=False)
        self.assertNotIn(first_body["migration_code"], serialized)
        self.assertNotIn(second_body["migration_code"], serialized)
        for ticket in tickets:
            self.assertNotIn("migration_code", ticket)
            self.assertEqual(ticket["old_line_user_id"], self.old_line_user_id)

    def test_ticket_expires_after_ten_minutes(self):
        created_at = datetime(2026, 7, 26, 1, 0, tzinfo=timezone.utc)
        data, code = alive_app.create_account_migration_ticket(
            self.data_file,
            self.old_line_user_id,
            self.config,
            now=created_at,
        )
        self.assertEqual(code, 200)

        before_expiry = alive_app.account_migration_ticket_status(
            self.data_file,
            self.old_line_user_id,
            self.config,
            now=created_at + timedelta(seconds=599),
        )
        state_before_expired_status = alive_app.load_state(self.data_file)
        at_expiry = alive_app.account_migration_ticket_status(
            self.data_file,
            self.old_line_user_id,
            self.config,
            now=created_at + timedelta(seconds=600),
        )
        state_after_expired_status = alive_app.load_state(self.data_file)

        self.assertEqual(
            before_expiry,
            {"ok": True, "configured": True, "pending": True, "expires_in": 1},
        )
        self.assertEqual(
            at_expiry,
            {"ok": True, "configured": True, "pending": False, "expires_in": 0},
        )
        self.assertEqual(
            state_after_expired_status,
            state_before_expired_status,
        )
        ticket = next(
            iter(state_after_expired_status["account_migration_tickets"].values())
        )
        self.assertEqual(ticket["status"], "pending")
        self.assertNotIn(
            data["migration_code"],
            json.dumps(state_after_expired_status),
        )

    def test_ticket_cannot_be_redeemed_twice(self):
        created_at = datetime(2026, 7, 26, 1, 0, tzinfo=timezone.utc)
        data, _ = alive_app.create_account_migration_ticket(
            self.data_file,
            self.old_line_user_id,
            self.config,
            now=created_at,
        )
        state = alive_app.load_state(self.data_file)

        ticket, error = alive_app.validate_account_migration_ticket(
            state,
            data["migration_code"],
            self.config["ACCOUNT_MIGRATION_SECRET"],
            now=created_at + timedelta(seconds=1),
        )
        self.assertIsNone(error)
        ticket["status"] = "used"
        ticket["used_at"] = (created_at + timedelta(seconds=1)).isoformat()
        state_before_repeated_validation = copy.deepcopy(state)

        repeated_ticket, repeated_error = (
            alive_app.validate_account_migration_ticket(
                state,
                data["migration_code"],
                self.config["ACCOUNT_MIGRATION_SECRET"],
                now=created_at + timedelta(seconds=2),
            )
        )
        self.assertIsNone(repeated_ticket)
        self.assertEqual(repeated_error, "used_code")
        self.assertEqual(state, state_before_repeated_validation)

    def test_ticket_source_must_still_exist(self):
        created_at = datetime(2026, 7, 26, 1, 0, tzinfo=timezone.utc)
        data, _ = alive_app.create_account_migration_ticket(
            self.data_file,
            self.old_line_user_id,
            self.config,
            now=created_at,
        )
        state = alive_app.load_state(self.data_file)
        del state["users"][self.old_line_user_id]
        state_before_validation = copy.deepcopy(state)

        ticket, error = alive_app.validate_account_migration_ticket(
            state,
            data["migration_code"],
            self.config["ACCOUNT_MIGRATION_SECRET"],
            now=created_at + timedelta(seconds=1),
        )

        self.assertIsNone(ticket)
        self.assertEqual(error, "source_missing")
        self.assertEqual(state, state_before_validation)

    def test_ticket_alias_validation_leaves_state_unchanged(self):
        created_at = datetime(2026, 7, 26, 1, 0, tzinfo=timezone.utc)
        data, _ = alive_app.create_account_migration_ticket(
            self.data_file,
            self.old_line_user_id,
            self.config,
            now=created_at,
        )
        state = alive_app.load_state(self.data_file)
        state["account_migration_aliases"][self.old_line_user_id] = {
            "status": "disabled",
            "target_line_user_id": self.claimed_line_user_id,
        }
        state_before_validation = copy.deepcopy(state)

        ticket, error = alive_app.validate_account_migration_ticket(
            state,
            data["migration_code"],
            self.config["ACCOUNT_MIGRATION_SECRET"],
            now=created_at + timedelta(seconds=1),
        )

        self.assertIsNone(ticket)
        self.assertEqual(error, "source_missing")
        self.assertEqual(state, state_before_validation)

    def test_status_is_read_only_for_missing_and_aliased_sources(self):
        created_at = datetime(2026, 7, 26, 1, 0, tzinfo=timezone.utc)
        for source_state in ("missing", "aliased"):
            with self.subTest(source_state=source_state):
                data_file = str(
                    Path(self.tempdir.name) / f"{source_state}-state.json"
                )
                state = alive_app.load_state(data_file)
                state["users"][self.old_line_user_id] = {
                    **alive_app.DEFAULT_PROFILE,
                    "line_user_id": self.old_line_user_id,
                }
                alive_app.save_state(data_file, state)
                alive_app.create_account_migration_ticket(
                    data_file,
                    self.old_line_user_id,
                    self.config,
                    now=created_at,
                )
                state = alive_app.load_state(data_file)
                if source_state == "missing":
                    del state["users"][self.old_line_user_id]
                else:
                    state["account_migration_aliases"][self.old_line_user_id] = {
                        "status": "disabled",
                        "target_line_user_id": self.claimed_line_user_id,
                    }
                alive_app.save_state(data_file, state)
                state_before_status = alive_app.load_state(data_file)

                status = alive_app.account_migration_ticket_status(
                    data_file,
                    self.old_line_user_id,
                    self.config,
                    now=created_at + timedelta(seconds=1),
                )
                state_after_status = alive_app.load_state(data_file)

                self.assertEqual(
                    status,
                    {
                        "ok": True,
                        "configured": True,
                        "pending": False,
                        "expires_in": 0,
                    },
                )
                self.assertEqual(state_after_status, state_before_status)

    def test_raw_code_and_line_ids_are_absent_from_public_status_and_audit(self):
        start = self._start()
        raw_code = start.get_json()["migration_code"]
        app = alive_app.create_app(self.config)
        with mock.patch.object(
            alive_app,
            "verify_line_id_token_for_channel",
            return_value=self.old_line_user_id,
        ):
            response = app.test_client().get(
                "/api/account-migration/status",
                headers={"Authorization": "Bearer legacy-id-token"},
                query_string={
                    "line_user_id": self.claimed_line_user_id,
                    "migration_code": raw_code,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        body = response.get_json()
        self.assertEqual(set(body), {"ok", "configured", "pending", "expires_in"})
        self.assertTrue(body["pending"])
        public_text = response.get_data(as_text=True)
        self.assertNotIn(raw_code, public_text)
        self.assertNotIn(self.old_line_user_id, public_text)
        self.assertNotIn(self.claimed_line_user_id, public_text)

        state = alive_app.load_state(self.data_file)
        audit_text = json.dumps(
            state.get("account_migration_audit", []),
            ensure_ascii=False,
        )
        self.assertNotIn(raw_code, audit_text)
        self.assertNotIn(self.old_line_user_id, audit_text)
        self.assertNotIn(self.claimed_line_user_id, audit_text)

    def test_start_rejects_missing_or_aliased_source_without_leaking_identity(self):
        state = alive_app.load_state(self.data_file)
        del state["users"][self.old_line_user_id]
        state["account_migration_aliases"][self.old_line_user_id] = {
            "status": "disabled",
            "target_line_user_id": self.claimed_line_user_id,
        }
        alive_app.save_state(self.data_file, state)

        response = self._start()

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        self.assertEqual(response.get_json(), {"ok": False, "error": "account_not_found"})
        response_text = response.get_data(as_text=True)
        self.assertNotIn(self.old_line_user_id, response_text)
        self.assertNotIn(self.claimed_line_user_id, response_text)


if __name__ == "__main__":
    unittest.main()
