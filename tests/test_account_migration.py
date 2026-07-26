import copy
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
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


class ProfileMergeTests(unittest.TestCase):
    def setUp(self):
        self.old_id = "U-legacy-provider"
        self.new_id = "U-current-provider"
        self.event_id = "migration-event-001"
        self.now = datetime(2026, 7, 26, 2, 0, tzinfo=timezone.utc)

    def test_blank_new_profile_is_replaced_by_complete_old_profile(self):
        old_profile = {
            **alive_app.DEFAULT_PROFILE,
            "line_user_id": self.old_id,
            "display_name": "Legacy member",
            "history": ["2026-07-24", "2026-07-25"],
            "contacts": [{"id": "contact-1", "name": "Alice"}],
            "smart_reminders": [{"id": "reminder-1", "title": "Medication"}],
            "calendar_notes": {
                "2026-07-25": {"id": "note-1", "content": "Doctor"}
            },
            "friends": ["U-friend-1"],
            "guardian_group_ids": ["group-1"],
            "contact_email": "legacy@example.invalid",
        }
        new_profile = {
            **alive_app.DEFAULT_PROFILE,
            "line_user_id": self.new_id,
            "display_name": "LINE 使用者",
        }

        merged = alive_app.merge_migration_profiles(
            old_profile,
            new_profile,
            now=self.now,
        )

        self.assertEqual(merged["line_user_id"], self.new_id)
        self.assertEqual(merged["display_name"], "Legacy member")
        self.assertEqual(merged["history"], ["2026-07-24", "2026-07-25"])
        self.assertEqual([row["id"] for row in merged["contacts"]], ["contact-1"])
        self.assertEqual(
            [row["id"] for row in merged["smart_reminders"]],
            ["reminder-1"],
        )
        self.assertEqual(
            merged["calendar_notes"]["2026-07-25"]["content"],
            "Doctor",
        )
        self.assertEqual(merged["friends"], ["U-friend-1"])
        self.assertEqual(merged["guardian_group_ids"], ["group-1"])
        self.assertEqual(merged["contact_email"], "legacy@example.invalid")

    def test_nonblank_profiles_merge_without_duplicate_business_ids(self):
        old_profile = {
            **alive_app.DEFAULT_PROFILE,
            "line_user_id": self.old_id,
            "display_name": "Legacy member",
            "history": ["2026-07-24T23:30:00+00:00", "2026-07-26"],
            "contacts": [
                {
                    "id": "contact-shared",
                    "name": "Legacy name",
                    "updated_at": "2026-07-20T00:00:00+00:00",
                },
                {"name": "Same visible name", "phone": "0900-old"},
            ],
            "smart_reminders": [
                {
                    "id": "reminder-shared",
                    "title": "Legacy title",
                    "updated_at": "2026-07-20T00:00:00+00:00",
                }
            ],
            "calendar_notes": {
                "note-shared": {
                    "id": "note-shared",
                    "content": "Legacy note",
                    "updated_at": "2026-07-20T00:00:00+00:00",
                }
            },
            "friends": ["U-friend-1"],
            "guardian_group_ids": ["group-1"],
        }
        new_profile = {
            **alive_app.DEFAULT_PROFILE,
            "line_user_id": self.new_id,
            "display_name": "Current member",
            "history": ["2026-07-25", "2026-07-26"],
            "contacts": [
                {
                    "id": "contact-shared",
                    "name": "Current name",
                    "updated_at": "2026-07-25T00:00:00+00:00",
                },
                {"name": "Same visible name", "phone": "0900-new"},
            ],
            "smart_reminders": [
                {
                    "id": "reminder-shared",
                    "title": "Current title",
                    "updated_at": "2026-07-25T00:00:00+00:00",
                }
            ],
            "calendar_notes": {
                "note-shared": {
                    "id": "note-shared",
                    "content": "Current note",
                    "updated_at": "2026-07-25T00:00:00+00:00",
                }
            },
            "friends": ["U-friend-1", "U-friend-2"],
            "guardian_group_ids": ["group-1", "group-2"],
        }

        merged = alive_app.merge_migration_profiles(
            old_profile,
            new_profile,
            now=self.now,
        )

        self.assertEqual(merged["history"], ["2026-07-25", "2026-07-26"])
        shared_contacts = [
            row for row in merged["contacts"] if row["id"] == "contact-shared"
        ]
        self.assertEqual(len(shared_contacts), 1)
        self.assertEqual(shared_contacts[0]["name"], "Current name")
        unnamed_contacts = [
            row for row in merged["contacts"] if row["name"] == "Same visible name"
        ]
        self.assertEqual(len(unnamed_contacts), 2)
        self.assertEqual(len({row["id"] for row in unnamed_contacts}), 2)
        self.assertEqual(
            merged["smart_reminders"][0]["title"],
            "Current title",
        )
        self.assertEqual(
            merged["calendar_notes"]["note-shared"]["content"],
            "Current note",
        )
        self.assertEqual(merged["friends"], ["U-friend-1", "U-friend-2"])
        self.assertEqual(merged["guardian_group_ids"], ["group-1", "group-2"])

    def test_same_date_calendar_notes_without_ids_are_both_preserved(self):
        old_profile = {
            **alive_app.DEFAULT_PROFILE,
            "line_user_id": self.old_id,
            "calendar_notes": {
                "2026-08-01": "Legacy appointment",
            },
        }
        new_profile = {
            **alive_app.DEFAULT_PROFILE,
            "line_user_id": self.new_id,
            "calendar_notes": {
                "2026-08-01": {
                    "content": "Current birthday",
                    "birthday_name": "Alice",
                    "birthday_date": "1950-08-01",
                    "birthday_yearly": True,
                },
            },
        }

        merged = alive_app.merge_migration_profiles(
            old_profile,
            new_profile,
            now=self.now,
        )

        notes = merged["calendar_notes"]["2026-08-01"]
        self.assertIsInstance(notes, list)
        self.assertEqual(len(notes), 2)
        self.assertEqual(
            {note["content"] for note in notes},
            {"Legacy appointment", "Current birthday"},
        )
        self.assertEqual(len({note["id"] for note in notes}), 2)
        birthday = next(note for note in notes if note.get("birthday_name"))
        self.assertEqual(birthday["birthday_date"], "1950-08-01")

    def test_newer_preferences_win_but_higher_active_entitlement_is_preserved(self):
        old_profile = {
            **alive_app.DEFAULT_PROFILE,
            "line_user_id": self.old_id,
            "plan": "paid_799",
            "payment_status": "active",
            "paid_until": "2026-08-26T00:00:00+00:00",
            "preferences": {
                "updated_at": "2026-07-20T00:00:00+00:00",
                "reminder_time": "09:00",
            },
        }
        new_profile = {
            **alive_app.DEFAULT_PROFILE,
            "line_user_id": self.new_id,
            "plan": "paid_199_year",
            "payment_status": "active",
            "paid_until": "2027-07-26T00:00:00+00:00",
            "preferences": {
                "updated_at": "2026-07-25T00:00:00+00:00",
                "reminder_time": "18:00",
            },
        }

        merged = alive_app.merge_migration_profiles(
            old_profile,
            new_profile,
            now=self.now,
        )
        self.assertEqual(merged["plan"], "paid_799")
        self.assertEqual(
            merged["paid_until"],
            "2026-08-26T00:00:00+00:00",
        )
        self.assertEqual(merged["preferences"]["reminder_time"], "18:00")

        same_rank = alive_app.merge_migration_profiles(
            {
                **old_profile,
                "plan": "paid_399",
                "paid_until": "2026-08-26T00:00:00+00:00",
            },
            {
                **new_profile,
                "plan": "paid_399_year",
                "paid_until": "2026-09-26T00:00:00+00:00",
            },
            now=self.now,
        )
        self.assertEqual(same_rank["plan"], "paid_399_year")
        self.assertEqual(
            same_rank["paid_until"],
            "2026-09-26T00:00:00+00:00",
        )

    def test_expired_location_is_not_moved(self):
        old_profile = {
            **alive_app.DEFAULT_PROFILE,
            "line_user_id": self.old_id,
            "location": {
                "active": True,
                "sharing": True,
                "expires_at": "2026-07-26T01:59:59+00:00",
                "latitude": 25.0,
                "longitude": 121.5,
            },
        }
        new_profile = {
            **alive_app.DEFAULT_PROFILE,
            "line_user_id": self.new_id,
            "location": {},
        }

        merged = alive_app.merge_migration_profiles(
            old_profile,
            new_profile,
            now=self.now,
        )

        self.assertEqual(merged["location"], {})

    def test_all_top_level_owner_references_are_reindexed(self):
        state = {
            "users": {
                self.old_id: {
                    **alive_app.DEFAULT_PROFILE,
                    "line_user_id": self.old_id,
                },
                self.new_id: {
                    **alive_app.DEFAULT_PROFILE,
                    "line_user_id": self.new_id,
                },
                "U-peer": {
                    **alive_app.DEFAULT_PROFILE,
                    "line_user_id": "U-peer",
                    "friends": [self.old_id],
                    "contacts": [
                        {
                            "id": "peer-contact",
                            "line_id": self.old_id,
                            "line_user_id": self.old_id,
                        }
                    ],
                    "guarding_for": [self.old_id],
                    "invited_by": self.old_id,
                },
            },
            "guardian_groups": {
                "group-1": {
                    "group_id": "group-1",
                    "owner_line_user_id": self.old_id,
                    "admin_line_user_ids": [self.old_id, "U-peer"],
                    "member_ids_at_bind": [self.old_id, "U-peer"],
                }
            },
            "friend_invites": {
                "INVITE1": {
                    "line_user_id": self.old_id,
                    "accepted_by": self.old_id,
                }
            },
            "orders": [
                {"order_id": "order-1", "line_user_id": self.old_id}
            ],
            "payment_records": [
                {"transaction_id": "payment-1", "payer_line_user_id": self.old_id}
            ],
            "support_tickets": [
                {"id": "support-1", "line_user_id": self.old_id}
            ],
            "privacy_requests": [
                {"request_id": "privacy-1", "requester_line_user_id": self.old_id},
                {"requester_line_user_id": self.old_id, "status": "open"},
            ],
            "notification_logs": [
                {
                    "log_id": "notification-1",
                    "line_user_id": self.old_id,
                    "target": self.old_id,
                    "message": "Historical message remains unchanged",
                }
            ],
            "checkin_warnings": [
                {"event_id": "warning-1", "owner_line_user_id": self.old_id}
            ],
            "sos_logs": [
                {"event_id": "sos-1", "line_user_id": self.old_id}
            ],
            "sos_pending": {
                self.old_id: {
                    "event_id": "sos-pending-1",
                }
            },
            "location_grants": {
                self.old_id: {
                    "grant_id": "grant-1",
                    "owner_line_user_id": self.old_id,
                    "grantee_line_user_id": "U-peer",
                }
            },
            "account_migration_aliases": {},
        }

        result = alive_app.reindex_account_references(
            state,
            self.old_id,
            self.new_id,
            self.event_id,
            now=self.now,
        )

        self.assertEqual(
            result,
            {"ok": True, "reindexed_records": 13},
        )
        peer = state["users"]["U-peer"]
        self.assertEqual(peer["friends"], [self.new_id])
        self.assertEqual(peer["contacts"][0]["line_id"], self.new_id)
        self.assertEqual(peer["contacts"][0]["line_user_id"], self.new_id)
        self.assertEqual(peer["guarding_for"], [self.new_id])
        self.assertEqual(peer["invited_by"], self.new_id)
        group = state["guardian_groups"]["group-1"]
        self.assertEqual(group["owner_line_user_id"], self.new_id)
        self.assertEqual(
            group["admin_line_user_ids"],
            [self.new_id, "U-peer"],
        )
        self.assertEqual(
            group["member_ids_at_bind"],
            [self.new_id, "U-peer"],
        )
        self.assertEqual(
            state["friend_invites"]["INVITE1"]["line_user_id"],
            self.new_id,
        )
        self.assertEqual(
            state["friend_invites"]["INVITE1"]["accepted_by"],
            self.new_id,
        )
        self.assertEqual(state["orders"][0]["line_user_id"], self.new_id)
        self.assertEqual(
            state["payment_records"][0]["payer_line_user_id"],
            self.new_id,
        )
        self.assertEqual(
            state["support_tickets"][0]["line_user_id"],
            self.new_id,
        )
        self.assertTrue(
            all(
                row["requester_line_user_id"] == self.new_id
                for row in state["privacy_requests"]
            )
        )
        self.assertIn("id", state["privacy_requests"][1])
        notification = state["notification_logs"][0]
        self.assertEqual(notification["line_user_id"], self.new_id)
        self.assertEqual(notification["target"], self.new_id)
        self.assertEqual(
            notification["message"],
            "Historical message remains unchanged",
        )
        self.assertEqual(
            state["checkin_warnings"][0]["owner_line_user_id"],
            self.new_id,
        )
        self.assertEqual(state["sos_logs"][0]["line_user_id"], self.new_id)
        self.assertIn(self.new_id, state["sos_pending"])
        self.assertNotIn(self.old_id, state["sos_pending"])
        self.assertIn(self.new_id, state["location_grants"])
        self.assertNotIn(self.old_id, state["location_grants"])
        self.assertTrue(
            all(
                row.get("migration_event_id") == self.event_id
                for row in (
                    group,
                    state["friend_invites"]["INVITE1"],
                    state["orders"][0],
                    state["payment_records"][0],
                    state["support_tickets"][0],
                    *state["privacy_requests"],
                    notification,
                    state["checkin_warnings"][0],
                    state["sos_logs"][0],
                    state["sos_pending"][self.new_id],
                    state["location_grants"][self.new_id],
                )
            )
        )
        self.assertNotIn(self.old_id, state["account_migration_aliases"])

    def test_guardian_group_dict_members_are_reindexed_without_hashing(self):
        state = {
            "users": {},
            "guardian_groups": {
                "group-1": {
                    "group_id": "group-1",
                    "members": [
                        {"line_user_id": self.old_id, "role": "member"},
                        {"line_user_id": "U-peer", "role": "member"},
                    ],
                }
            },
            "account_migration_aliases": {},
        }

        result = alive_app.reindex_account_references(
            state,
            self.old_id,
            self.new_id,
            self.event_id,
            now=self.now,
        )

        self.assertEqual(result["reindexed_records"], 1)
        group = state["guardian_groups"]["group-1"]
        self.assertEqual(group["members"][0]["line_user_id"], self.new_id)
        self.assertEqual(group["members"][1]["line_user_id"], "U-peer")
        self.assertEqual(group["migration_event_id"], self.event_id)

    def test_top_level_records_dedupe_by_stable_id_but_not_visible_fields(self):
        state = {
            "users": {},
            "orders": [
                {
                    "order_id": "order-shared",
                    "line_user_id": self.old_id,
                    "status": "pending",
                    "updated_at": "2026-07-20T00:00:00+00:00",
                },
                {
                    "order_id": "order-shared",
                    "line_user_id": self.new_id,
                    "status": "paid",
                    "updated_at": "2026-07-25T00:00:00+00:00",
                },
                {
                    "line_user_id": self.old_id,
                    "display_name": "Same visible name",
                },
                {
                    "line_user_id": self.new_id,
                    "display_name": "Same visible name",
                },
            ],
            "account_migration_aliases": {},
        }

        alive_app.reindex_account_references(
            state,
            self.old_id,
            self.new_id,
            self.event_id,
            now=self.now,
        )

        shared = [
            row for row in state["orders"] if row.get("order_id") == "order-shared"
        ]
        self.assertEqual(len(shared), 1)
        self.assertEqual(shared[0]["status"], "paid")
        stableless = [
            row
            for row in state["orders"]
            if row.get("display_name") == "Same visible name"
        ]
        self.assertEqual(len(stableless), 2)
        self.assertEqual(len({row["id"] for row in stableless}), 2)

    def test_same_old_and_new_identity_is_rejected(self):
        state = {
            "users": {
                self.old_id: {
                    **alive_app.DEFAULT_PROFILE,
                    "line_user_id": self.old_id,
                }
            },
            "account_migration_aliases": {},
        }
        before = copy.deepcopy(state)

        with self.assertRaisesRegex(ValueError, "^same_identity$"):
            alive_app.reindex_account_references(
                state,
                self.old_id,
                self.old_id,
                self.event_id,
                now=self.now,
            )

        self.assertEqual(state, before)

    def test_disabled_alias_blocks_profile_recreation_and_registration(self):
        with tempfile.TemporaryDirectory() as tempdir:
            data_file = str(Path(tempdir) / "state.json")
            state = alive_app.load_state(data_file)
            state["users"].pop(self.old_id, None)
            state["account_migration_aliases"][self.old_id] = {
                "target_line_user_id": self.new_id,
                "created_at": self.now.isoformat(),
                "status": "disabled",
            }
            alive_app.save_state(data_file, state)

            loaded = alive_app.load_state(data_file)
            with self.assertRaises(alive_app.AccountMigratedError):
                alive_app.get_profile(loaded, self.old_id)
            response, code = alive_app.register_line_user(
                data_file,
                {
                    "line_user_id": self.old_id,
                    "display_name": "Must not recreate",
                },
            )
            after = alive_app.load_state(data_file)

        self.assertEqual(
            response,
            {
                "ok": False,
                "error": "account_migrated",
                "action": "open_current_liff",
            },
        )
        self.assertEqual(code, 409)
        self.assertNotIn(self.old_id, after["users"])
        response_text = json.dumps(response, ensure_ascii=False)
        self.assertNotIn(self.old_id, response_text)
        self.assertNotIn(self.new_id, response_text)

    def test_disabled_alias_get_lookup_apis_return_safe_guidance(self):
        with tempfile.TemporaryDirectory() as tempdir:
            data_file = str(Path(tempdir) / "state.json")
            state = alive_app.load_state(data_file)
            state["users"].pop(self.old_id, None)
            state["account_migration_aliases"][self.old_id] = {
                "target_line_user_id": self.new_id,
                "created_at": self.now.isoformat(),
                "status": "disabled",
            }
            alive_app.save_state(data_file, state)
            app = alive_app.create_app(
                {
                    "TESTING": True,
                    "DATA_FILE": data_file,
                }
            )
            client = app.test_client()

            calendar_response = client.get(
                "/api/calendar-notes",
                query_string={"line_user_id": self.old_id},
            )
            location_response = client.get(
                "/api/location/status",
                query_string={"line_user_id": self.old_id},
            )
            after = alive_app.load_state(data_file)

        expected = {
            "ok": False,
            "error": "account_migrated",
            "action": "open_current_liff",
        }
        for response in (calendar_response, location_response):
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.get_json(), expected)
            response_text = response.get_data(as_text=True)
            self.assertNotIn(self.old_id, response_text)
            self.assertNotIn(self.new_id, response_text)
        self.assertNotIn(self.old_id, after["users"])


class AtomicRedemptionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.data_file = str(Path(self.tempdir.name) / "state.json")
        self.old_id = "U0123456789abcdef0123456789abcdef"
        self.new_id = "Ufedcba9876543210fedcba9876543210"
        self.now = datetime(2026, 7, 26, 2, 0, tzinfo=timezone.utc)
        self.config = {
            "TESTING": True,
            "DATA_FILE": self.data_file,
            "LEGACY_LINE_LOGIN_CHANNEL_ID": "2010674803",
            "LINE_LOGIN_CHANNEL_ID": "2010848330",
            "ACCOUNT_MIGRATION_SECRET": "test-only-secret",
            "ACCOUNT_MIGRATION_TTL_SECONDS": 600,
            "LINE_CHANNEL_ACCESS_TOKEN": "",
        }
        state = alive_app.load_state(self.data_file)
        state["users"][self.old_id] = {
            **alive_app.DEFAULT_PROFILE,
            "line_user_id": self.old_id,
            "display_name": "Legacy member",
            "history": ["2026-07-25", "2026-07-26"],
            "contacts": [{"id": "contact-1", "name": "Guardian"}],
            "smart_reminders": [{"id": "reminder-1", "title": "Medicine"}],
            "guardian_group_ids": ["group-1"],
        }
        state["users"][self.new_id] = {
            **alive_app.DEFAULT_PROFILE,
            "line_user_id": self.new_id,
            "display_name": "Current member",
            "history": ["2026-07-26"],
        }
        state["guardian_groups"]["group-1"] = {
            "group_id": "group-1",
            "owner_line_user_id": self.old_id,
        }
        state["orders"] = [
            {"order_id": "order-1", "line_user_id": self.old_id}
        ]
        state["support_tickets"] = [
            {"id": "support-1", "line_user_id": self.old_id}
        ]
        alive_app.save_state(self.data_file, state)
        created, code = alive_app.create_account_migration_ticket(
            self.data_file,
            self.old_id,
            self.config,
            now=self.now,
        )
        self.assertEqual(code, 200)
        self.migration_code = created["migration_code"]

    def _redeem(self, **overrides):
        return alive_app.redeem_account_migration_ticket(
            self.data_file,
            overrides.get("migration_code", self.migration_code),
            overrides.get("new_line_user_id", self.new_id),
            self.config,
            now=overrides.get("now", self.now + timedelta(seconds=1)),
        )

    def test_redeem_is_atomic_and_marks_ticket_used_in_same_write(self):
        result, code = self._redeem()

        self.assertEqual(code, 200)
        self.assertEqual(
            result,
            {
                "ok": True,
                "status": "migrated",
                "counts": {
                    "checkins": 2,
                    "contacts": 1,
                    "groups": 1,
                    "reminders": 1,
                    "orders": 1,
                    "requests": 1,
                },
            },
        )
        state = alive_app.load_state(self.data_file)
        self.assertNotIn(self.old_id, state["users"])
        self.assertIn(self.new_id, state["users"])
        self.assertEqual(
            state["account_migration_aliases"][self.old_id]["status"],
            "disabled",
        )
        ticket = next(iter(state["account_migration_tickets"].values()))
        self.assertEqual(ticket["status"], "used")
        self.assertTrue(ticket["used_at"])
        self.assertEqual(len(state["account_migration_snapshots"]), 1)
        self.assertEqual(len(state["account_migration_audit"]), 1)
        self.assertNotIn(
            self.migration_code,
            json.dumps(state, ensure_ascii=False),
        )

    def test_redeem_creates_alias_only_after_reindex_and_user_key_replacement(self):
        state = alive_app.load_state(self.data_file)
        operations = []

        class TrackingUsers(dict):
            def __setitem__(tracking_self, key, value):
                if key == self.new_id:
                    operations.append("replace_new_user")
                super().__setitem__(key, value)

            def pop(tracking_self, key, default=None):
                if key == self.old_id:
                    operations.append("remove_old_user")
                return super().pop(key, default)

        class TrackingAliases(dict):
            def __setitem__(tracking_self, key, value):
                if key == self.old_id:
                    operations.append("create_alias")
                super().__setitem__(key, value)

        state["users"] = TrackingUsers(state["users"])
        state["account_migration_aliases"] = TrackingAliases(
            state["account_migration_aliases"]
        )
        real_reindex = alive_app.reindex_account_references

        def record_reindex(*args, **kwargs):
            operations.append("reindex")
            return real_reindex(*args, **kwargs)

        with (
            mock.patch.object(
                alive_app,
                "mutate_state_atomically",
                side_effect=lambda _data_file, mutator: mutator(state),
            ),
            mock.patch.object(
                alive_app,
                "reindex_account_references",
                side_effect=record_reindex,
            ),
        ):
            result, code = self._redeem()

        self.assertEqual(code, 200)
        self.assertTrue(result["ok"])
        self.assertEqual(
            operations,
            [
                "reindex",
                "replace_new_user",
                "remove_old_user",
                "create_alias",
            ],
        )

    def test_save_failure_restores_old_and_new_accounts(self):
        before = alive_app.load_state(self.data_file)
        with mock.patch.object(
            alive_app,
            "_account_migration_serialize_state",
            side_effect=RuntimeError("simulated write failure"),
            create=True,
        ):
            result, code = self._redeem()
        after = alive_app.load_state(self.data_file)

        self.assertEqual(code, 500)
        self.assertEqual(result, {"ok": False, "error": "migration_failed"})
        self.assertEqual(after, before)
        self.assertNotIn(self.old_id, after["account_migration_aliases"])
        ticket = next(iter(after["account_migration_tickets"].values()))
        self.assertEqual(ticket["status"], "pending")
        self.assertEqual(after.get("account_migration_snapshots") or {}, {})
        self.assertEqual(after["account_migration_audit"], [])

    def test_two_parallel_redemptions_produce_exactly_one_success(self):
        barrier = threading.Barrier(2)

        def redeem_once():
            barrier.wait(timeout=5)
            return self._redeem()

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _: redeem_once(), range(2)))

        self.assertEqual(sorted(code for _, code in outcomes), [200, 409])
        self.assertEqual(
            sorted(result.get("status") or result.get("error") for result, _ in outcomes),
            ["migrated", "used_code"],
        )
        state = alive_app.load_state(self.data_file)
        self.assertEqual(len(state["account_migration_snapshots"]), 1)
        self.assertEqual(len(state["account_migration_audit"]), 1)
        self.assertEqual(
            next(iter(state["account_migration_tickets"].values()))["status"],
            "used",
        )

    def test_success_snapshot_is_retained_for_thirty_days(self):
        result, code = self._redeem()
        self.assertEqual(code, 200)
        self.assertTrue(result["ok"])

        day_29, _ = alive_app.cleanup_expired_data(
            {
                **self.config,
                "CRON_NOW": self.now + timedelta(days=29),
            }
        )
        state_at_29 = alive_app.load_state(self.data_file)
        day_31, _ = alive_app.cleanup_expired_data(
            {
                **self.config,
                "CRON_NOW": self.now + timedelta(days=31),
            }
        )
        state_at_31 = alive_app.load_state(self.data_file)

        self.assertEqual(day_29["migration_snapshots_removed"], 0)
        self.assertEqual(len(state_at_29["account_migration_snapshots"]), 1)
        self.assertEqual(day_31["migration_snapshots_removed"], 1)
        self.assertEqual(state_at_31["account_migration_snapshots"], {})

    def test_snapshot_cleanup_converts_naive_app_time_before_retention_check(self):
        result, code = self._redeem()
        self.assertEqual(code, 200)
        self.assertTrue(result["ok"])

        cleanup, _ = alive_app.cleanup_expired_data(
            {
                **self.config,
                "APP_TIMEZONE": "Asia/Taipei",
                # Snapshot purge_after is 2026-08-25 02:00 UTC (10:00 Taipei).
                "CRON_NOW": datetime(2026, 8, 25, 9, 59),
            }
        )
        state = alive_app.load_state(self.data_file)

        self.assertEqual(cleanup["migration_snapshots_removed"], 0)
        self.assertEqual(len(state["account_migration_snapshots"]), 1)

    def test_admin_audit_contains_counts_but_no_identity_or_code(self):
        created, create_code = alive_app.create_account_migration_ticket(
            self.data_file,
            self.old_id,
            self.config,
        )
        self.assertEqual(create_code, 200)
        migration_code = created["migration_code"]
        app = alive_app.create_app(self.config)
        with mock.patch.object(
            alive_app,
            "verify_line_id_token_for_channel",
            return_value=self.new_id,
        ):
            response = app.test_client().post(
                "/api/account-migration/redeem",
                headers={"Authorization": "Bearer current-id-token"},
                json={
                    "migration_code": migration_code,
                    "line_user_id": self.old_id,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(set(response.get_json()), {"ok", "status", "counts"})
        public_text = response.get_data(as_text=True)
        for secret_value in (
            self.old_id,
            self.new_id,
            migration_code,
            "current-id-token",
        ):
            self.assertNotIn(secret_value, public_text)

        audit = alive_app.load_state(self.data_file)["account_migration_audit"]
        self.assertEqual(len(audit), 1)
        self.assertEqual(
            set(audit[0]),
            {"event_id", "status", "created_at", "failure_category", "counts"},
        )
        self.assertEqual(audit[0]["status"], "success")
        audit_text = json.dumps(audit, ensure_ascii=False)
        for secret_value in (self.old_id, self.new_id, migration_code):
            self.assertNotIn(secret_value, audit_text)
        self.assertNotIn("code_digest", audit_text)

    def test_postgres_atomic_boundary_uses_row_lock_transaction(self):
        initial = alive_app._hydrate_state({"users": {"U-one": {"value": 1}}})

        class FakeResult:
            def __init__(self, row=None):
                self.row = row

            def fetchone(self):
                return self.row

        class FakeConnection:
            def __init__(self):
                self.statements = []
                self.commits = 0
                self.rollbacks = 0
                self.closed = False

            def execute(self, sql, params=None):
                self.statements.append((sql, params))
                if "SELECT value" in sql:
                    return FakeResult((json.dumps(initial),))
                return FakeResult()

            def commit(self):
                self.commits += 1

            def rollback(self):
                self.rollbacks += 1

            def close(self):
                self.closed = True

        connection = FakeConnection()
        with (
            mock.patch.object(alive_app, "database_url", return_value="postgresql://db"),
            mock.patch.object(alive_app, "_ensure_pg_kv"),
            mock.patch.object(alive_app, "_pg_connect", return_value=connection),
            mock.patch.object(alive_app, "_save_state_sqlite"),
        ):
            result = alive_app.mutate_state_atomically(
                self.data_file,
                lambda state: state["users"]["U-one"].update({"value": 2}) or "ok",
            )

        sql = "\n".join(statement for statement, _ in connection.statements)
        self.assertEqual(result, "ok")
        self.assertIn("BEGIN", sql)
        self.assertIn("FOR UPDATE", sql)
        self.assertIn("UPDATE kv_store", sql)
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)
        self.assertTrue(connection.closed)


if __name__ == "__main__":
    unittest.main()
