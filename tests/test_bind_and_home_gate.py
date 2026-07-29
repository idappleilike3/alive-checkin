"""Bind persistence fields + home gate helpers."""
from __future__ import annotations

import os
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import app as app_module


ROOT = Path(__file__).resolve().parents[1]


class BindAndHomeGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_file = str(Path(self.tmp.name) / "state.json")

    def tearDown(self):
        self.tmp.cleanup()

    def fallback_http_request(self, method, path, *, payload=None, authenticated_user="U-owner"):
        """Exercise the real MiniApp.run BaseHTTPRequestHandler over a socket."""
        real_server_class = app_module.ThreadingHTTPServer
        ready = threading.Event()
        holder = {}

        class RecordingServer(real_server_class):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                holder["server"] = self
                ready.set()

        app = app_module.MiniApp({
            "DATA_FILE": self.data_file,
            "REQUIRE_LIFF_AUTH": "1",
        })
        with (
            patch.object(app_module, "ThreadingHTTPServer", RecordingServer),
            patch.object(
                app_module,
                "resolve_line_user_id",
                return_value=(authenticated_user, None),
            ),
        ):
            thread = threading.Thread(
                target=app.run,
                kwargs={"host": "127.0.0.1", "port": 0},
                daemon=True,
            )
            thread.start()
            self.assertTrue(ready.wait(2), "fallback HTTP server did not start")
            server = holder["server"]
            connection = http.client.HTTPConnection(
                server.server_address[0], server.server_address[1], timeout=2
            )
            body = json.dumps(payload or {}, ensure_ascii=False) if payload is not None else None
            headers = {"Authorization": "Bearer verified-test-token"}
            if body is not None:
                headers["Content-Type"] = "application/json"
            try:
                connection.request(method, path, body=body, headers=headers)
                response = connection.getresponse()
                raw = response.read().decode("utf-8")
                result = (response.status, json.loads(raw) if raw else {})
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
        return result

    def test_bind_writes_line_user_id_and_invite_edge(self):
        result, code = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-inviter",
                "contact_line_user_id": "U-guardian",
                "contact_display_name": "阿媽",
            },
            config={},
        )
        self.assertEqual(code, 200)
        self.assertTrue(result["bound"])
        contact = result["contact"]
        self.assertEqual(contact["line_id"], "U-guardian")
        self.assertEqual(contact["line_user_id"], "U-guardian")
        self.assertEqual(contact["binding_status"], "accepted")
        self.assertEqual(contact["invited_by"], "U-inviter")
        self.assertEqual(contact.get("display_name") or contact.get("line_display_name"), "阿媽")
        self.assertEqual(contact.get("line_display_name") or contact.get("display_name"), "阿媽")

        state = app_module.load_state(self.data_file)
        inviter = state["users"]["U-inviter"]
        guardian = state["users"]["U-guardian"]
        self.assertEqual(len(inviter["contacts"]), 1)
        self.assertIn("U-inviter", guardian.get("guarding_for") or [])
        self.assertEqual(guardian.get("invited_by"), "U-inviter")
        self.assertEqual(len(state.get("contact_rewards") or []), 1)

        summary = app_module.admin_summary(self.data_file)
        self.assertEqual(summary["bound_guardian_total"], 1)
        self.assertEqual(len(summary["invite_edges"]), 1)
        self.assertEqual(summary["invite_edges"][0]["inviter_line_user_id"], "U-inviter")
        self.assertEqual(summary["invite_edges"][0]["guardian_line_user_id"], "U-guardian")
        self.assertIn("persistence", summary)

    def test_verified_pending_invite_needs_consent_then_creates_two_core_records(self):
        """Dropping consent, or either reciprocal record, must keep the member gated."""
        state = app_module.load_state(self.data_file)
        app_module.get_profile(state, "U-owner")["display_name"] = "小美"
        app_module.save_state(self.data_file, state)
        invite, invite_code = app_module.create_guardian_invite(
            self.data_file, "U-owner", {"display_name": "阿媽", "relationship": "阿嬤"}
        )
        self.assertEqual(invite_code, 201)

        rejected, rejected_code = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-owner",
                "contact_line_user_id": "U-guardian",
                "invite_token": invite["invite_token"],
            },
            config={},
        )
        self.assertEqual(rejected_code, 409)
        self.assertEqual(rejected["code"], "consent_required")
        self.assertTrue(app_module.member_access_state(app_module.load_state(self.data_file)["users"]["U-owner"])["guardian_required"])

        missing, missing_code = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-owner",
                "contact_line_user_id": "U-guardian",
                "recipient_consent": True,
                "activate_trial": False,
                "invite_token": invite["invite_token"],
            },
            config={},
        )
        self.assertEqual(missing_code, 400)
        self.assertEqual(missing["code"], "guardian_profile_required")
        self.assertEqual(missing["required_fields"], ["name", "relationship", "phone"])

        result, code = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-owner",
                "contact_line_user_id": "U-guardian",
                "contact_display_name": "小芳",
                "contact_relationship": "女兒",
                "contact_phone": "0912345678",
                "recipient_consent": True,
                "invite_token": invite["invite_token"],
            },
            config={},
        )
        self.assertEqual(code, 200)
        self.assertTrue(result["reciprocal"])
        self.assertEqual(result["owner_guardian"]["line_user_id"], "U-guardian")
        self.assertEqual(result["invitee_guardian"]["line_user_id"], "U-owner")
        state = app_module.load_state(self.data_file)
        owner_row = state["users"]["U-owner"]["contacts"][0]
        invitee_row = state["users"]["U-guardian"]["contacts"][0]
        self.assertTrue(owner_row["is_primary"])
        self.assertTrue(invitee_row["is_primary"])
        self.assertEqual(invite["status"], "pending")
        self.assertEqual(state["guardian_invites"][0]["status"], "accepted")

    def test_verified_bind_keeps_both_records_when_one_notice_fails(self):
        invite, _ = app_module.create_guardian_invite(
            self.data_file, "U-owner", {"display_name": "阿媽", "relationship": "阿嬤"}
        )

        def sender(_token, target, _message):
            if target == "U-guardian":
                raise RuntimeError("not a friend")
            return {"ok": True}

        result, code = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-owner",
                "contact_line_user_id": "U-guardian",
                "recipient_consent": True,
                "invite_token": invite["invite_token"],
            },
            config={"LINE_CHANNEL_ACCESS_TOKEN": "token", "LINE_PUSH_SENDER": sender},
        )
        self.assertEqual(code, 200)
        self.assertTrue(result["reciprocal"])
        self.assertEqual(result["owner_notice"]["status"], "sent")
        self.assertEqual(result["invitee_notice"]["status"], "failed")
        state = app_module.load_state(self.data_file)
        self.assertEqual(len(state["users"]["U-owner"]["contacts"]), 1)
        self.assertEqual(len(state["users"]["U-guardian"]["contacts"]), 1)
        self.assertEqual(len([row for row in state["notification_logs"] if row["kind"] == "binding_complete"]), 2)

    def test_binding_retry_sends_only_the_previously_failed_recipient(self):
        invite, _ = app_module.create_guardian_invite(
            self.data_file, "U-owner", {"display_name": "阿媽"}
        )
        first_targets = []

        def first_sender(_token, target, _message):
            first_targets.append(target)
            if target == "U-guardian":
                raise RuntimeError("temporary network failure")
            return {"ok": True}

        result, code = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-owner",
                "contact_line_user_id": "U-guardian",
                "recipient_consent": True,
                "invite_token": invite["invite_token"],
            },
            config={"LINE_CHANNEL_ACCESS_TOKEN": "token", "LINE_PUSH_SENDER": first_sender},
        )
        self.assertEqual(code, 200)
        self.assertEqual(result["owner_notice"]["status"], "sent")
        self.assertEqual(result["invitee_notice"]["status"], "failed")

        retry_targets = []
        retried, retry_code = app_module.retry_pending_bind_notifications({
            "DATA_FILE": self.data_file,
            "LINE_CHANNEL_ACCESS_TOKEN": "token",
            "LINE_PUSH_SENDER": lambda _token, target, _message: retry_targets.append(target) or {"ok": True},
        })

        self.assertEqual(retry_code, 200)
        self.assertEqual(retried["sent"], 1)
        self.assertEqual(retry_targets, ["U-guardian"])
        state = app_module.load_state(self.data_file)
        contact = state["users"]["U-owner"]["contacts"][0]
        self.assertTrue(contact["bind_notify_sent_at"])

    def test_pending_invite_expires_after_seven_days(self):
        past = app_module.current_app_time({}) - app_module.timedelta(days=8)
        invite, _ = app_module.create_guardian_invite(
            self.data_file,
            "U-owner",
            {"display_name": "阿媽", "relationship": "阿嬤"},
            now=past,
        )
        result, code = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-owner",
                "contact_line_user_id": "U-guardian",
                "recipient_consent": True,
                "invite_token": invite["invite_token"],
            },
            config={},
        )
        self.assertEqual(code, 410)
        self.assertEqual(result["code"], "invite_expired")

    def test_guardian_invite_token_is_required_and_bound_to_one_invite(self):
        invite, code = app_module.create_guardian_invite(
            self.data_file,
            "U-owner",
            {"display_name": "阿媽", "relationship": "阿嬤"},
        )
        self.assertEqual(code, 201)
        token = invite.get("invite_token")
        self.assertTrue(token)

        missing, missing_code = app_module.invite_bind_preview(
            self.data_file,
            {"invite_from": "U-owner", "line_user_id": "U-stranger"},
        )
        self.assertEqual(missing_code, 403)
        self.assertEqual(missing["code"], "invalid_invite_token")

        wrong, wrong_code = app_module.invite_bind_preview(
            self.data_file,
            {
                "invite_from": "U-owner",
                "line_user_id": "U-stranger",
                "invite_token": "wrong-token",
            },
        )
        self.assertEqual(wrong_code, 403)
        self.assertEqual(wrong["code"], "invalid_invite_token")

        preview, preview_code = app_module.invite_bind_preview(
            self.data_file,
            {
                "invite_from": "U-owner",
                "line_user_id": "U-guardian",
                "invite_token": token,
            },
        )
        self.assertEqual(preview_code, 200)
        self.assertEqual(preview["invite_status"], "pending")
        self.assertNotIn("invite_token", preview)

    def test_guardian_bind_rejects_wrong_token_and_consumed_token(self):
        invite, _ = app_module.create_guardian_invite(
            self.data_file, "U-owner", {"display_name": "阿媽"}
        )
        token = invite["invite_token"]

        wrong, wrong_code = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-owner",
                "contact_line_user_id": "U-attacker",
                "recipient_consent": True,
                "invite_token": "wrong-token",
            },
            config={},
        )
        self.assertEqual(wrong_code, 403)
        self.assertEqual(wrong["code"], "invalid_invite_token")

        accepted, accepted_code = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-owner",
                "contact_line_user_id": "U-guardian",
                "recipient_consent": True,
                "invite_token": token,
            },
            config={},
        )
        self.assertEqual(accepted_code, 200)
        self.assertTrue(accepted["reciprocal"])

        reused, reused_code = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-owner",
                "contact_line_user_id": "U-other",
                "recipient_consent": True,
                "invite_token": token,
            },
            config={},
        )
        self.assertEqual(reused_code, 410)
        self.assertEqual(reused["code"], "invite_used")

    def test_delete_bound_guardian_unbinds_both_sides_and_allows_reinvite(self):
        invite, _ = app_module.create_guardian_invite(
            self.data_file, "U-owner", {"display_name": "阿媽"}
        )
        accepted, accepted_code = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-owner",
                "contact_line_user_id": "U-guardian",
                "recipient_consent": True,
                "invite_token": invite["invite_token"],
            },
            config={},
        )
        self.assertEqual(accepted_code, 200)
        contact_id = accepted["owner_guardian"]["id"]

        deleted, deleted_code = app_module.delete_single_contact(
            self.data_file, "U-owner", contact_id
        )
        self.assertEqual(deleted_code, 200)
        self.assertTrue(deleted["deleted"])
        state = app_module.load_state(self.data_file)
        self.assertEqual(state["users"]["U-owner"]["contacts"], [])
        self.assertEqual(state["users"]["U-guardian"]["contacts"], [])
        self.assertNotIn(
            "U-owner", state["users"]["U-guardian"].get("guarding_for") or []
        )
        self.assertNotIn(
            "U-guardian", state["users"]["U-owner"].get("guarding_for") or []
        )

        reinvite, reinvite_code = app_module.create_guardian_invite(
            self.data_file, "U-owner", {"display_name": "阿媽"}
        )
        self.assertEqual(reinvite_code, 201)
        rebound, rebound_code = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-owner",
                "contact_line_user_id": "U-guardian",
                "recipient_consent": True,
                "invite_token": reinvite["invite_token"],
            },
            config={},
        )
        self.assertEqual(rebound_code, 200)
        self.assertTrue(rebound["binding_complete"])

    def test_delete_bound_guardian_clears_profile_completion_reminders(self):
        invite, _ = app_module.create_guardian_invite(
            self.data_file, "U-owner", {"display_name": "阿媽"}
        )
        accepted, _ = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-owner",
                "contact_line_user_id": "U-guardian",
                "recipient_consent": True,
                "invite_token": invite["invite_token"],
            },
            config={},
        )

        deleted, code = app_module.delete_single_contact(
            self.data_file, "U-owner", accepted["owner_guardian"]["id"]
        )

        self.assertEqual(code, 200)
        self.assertTrue(deleted["deleted"])
        state = app_module.load_state(self.data_file)
        for line_user_id in ("U-owner", "U-guardian"):
            profile = state["users"][line_user_id]
            self.assertFalse(profile.get("profile_completion_required"))
            self.assertNotIn("profile_completion_peer_line_user_id", profile)
            self.assertNotIn("profile_completion_bound_at", profile)

    def test_delete_emergency_contact_does_not_remove_guardian_for_same_peer(self):
        state = app_module.load_state(self.data_file)
        owner = app_module.get_profile(state, "U-owner")
        peer = app_module.get_profile(state, "U-peer")
        owner["contacts"] = [
            {
                "id": "guardian-peer",
                "line_user_id": "U-peer",
                "binding_status": "accepted",
                "consent_status": "accepted",
                "contact_role": "guardian",
                "is_primary": True,
            },
            {
                "id": "emergency-peer",
                "line_user_id": "U-peer",
                "binding_status": "accepted",
                "contact_role": "emergency",
            },
        ]
        peer["contacts"] = [
            {
                "id": "guardian-owner",
                "line_user_id": "U-owner",
                "binding_status": "accepted",
                "consent_status": "accepted",
                "contact_role": "guardian",
                "is_primary": True,
            }
        ]
        owner["guarding_for"] = ["U-peer"]
        peer["guarding_for"] = ["U-owner"]
        app_module.save_state(self.data_file, state)

        deleted, code = app_module.delete_single_contact(
            self.data_file, "U-owner", "emergency-peer"
        )

        self.assertEqual(code, 200)
        self.assertTrue(deleted["deleted"])
        stored = app_module.load_state(self.data_file)
        self.assertEqual(
            [row["id"] for row in stored["users"]["U-owner"]["contacts"]],
            ["guardian-peer"],
        )
        self.assertEqual(
            [row["id"] for row in stored["users"]["U-peer"]["contacts"]],
            ["guardian-owner"],
        )
        self.assertIn("U-peer", stored["users"]["U-owner"]["guarding_for"])
        self.assertIn("U-owner", stored["users"]["U-peer"]["guarding_for"])

    def test_binding_is_persisted_before_success_notifications_are_sent(self):
        invite, _ = app_module.create_guardian_invite(
            self.data_file, "U-owner", {"display_name": "阿媽"}
        )

        def sender(_token, _target, _message):
            persisted = app_module.load_state(self.data_file)
            owner = persisted["users"]["U-owner"]
            guardian = persisted["users"]["U-guardian"]
            self.assertEqual(owner["contacts"][0]["line_user_id"], "U-guardian")
            self.assertEqual(guardian["contacts"][0]["line_user_id"], "U-owner")
            self.assertEqual(persisted["guardian_invites"][0]["status"], "accepted")
            return {"ok": True}

        result, code = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-owner",
                "contact_line_user_id": "U-guardian",
                "recipient_consent": True,
                "invite_token": invite["invite_token"],
            },
            config={"LINE_CHANNEL_ACCESS_TOKEN": "token", "LINE_PUSH_SENDER": sender},
        )
        self.assertEqual(code, 200)
        self.assertEqual(result["owner_notice"]["status"], "sent")
        self.assertEqual(result["invitee_notice"]["status"], "sent")

    def test_bind_retries_one_state_conflict_and_consumes_invite_once(self):
        """A concurrent state update must not turn invite acceptance into a 500."""
        invite, _ = app_module.create_guardian_invite(
            self.data_file, "U-owner", {"display_name": "阿媽"}
        )
        real_save_state = app_module.save_state
        saves = 0

        def conflict_once(data_file, state):
            nonlocal saves
            saves += 1
            if saves == 1:
                raise app_module.StateConflictError("state_conflict")
            return real_save_state(data_file, state)

        with patch.object(app_module, "save_state", side_effect=conflict_once):
            result, code = app_module.bind_emergency_contact(
                self.data_file,
                {
                    "inviter_line_user_id": "U-owner",
                    "contact_line_user_id": "U-guardian",
                    "recipient_consent": True,
                    "invite_token": invite["invite_token"],
                },
                config={},
            )

        self.assertEqual(code, 200)
        self.assertTrue(result["binding_complete"])
        state = app_module.load_state(self.data_file)
        self.assertEqual(state["guardian_invites"][0]["status"], "accepted")
        self.assertEqual(len(state["users"]["U-owner"]["contacts"]), 1)
        self.assertEqual(len(state["users"]["U-guardian"]["contacts"]), 1)

    def test_same_invite_concurrent_acceptance_has_one_winner(self):
        invite, _ = app_module.create_guardian_invite(
            self.data_file, "U-owner", {"display_name": "阿媽"}
        )
        barrier = threading.Barrier(2)
        results = []

        def accept_as(line_user_id):
            barrier.wait(timeout=2)
            results.append(
                app_module.bind_emergency_contact(
                    self.data_file,
                    {
                        "inviter_line_user_id": "U-owner",
                        "contact_line_user_id": line_user_id,
                        "recipient_consent": True,
                        "invite_token": invite["invite_token"],
                    },
                    config={},
                )
            )

        threads = [
            threading.Thread(target=accept_as, args=("U-guardian-a",)),
            threading.Thread(target=accept_as, args=("U-guardian-b",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)

        self.assertEqual(sorted(code for _body, code in results), [200, 410])
        state = app_module.load_state(self.data_file)
        self.assertEqual(state["guardian_invites"][0]["status"], "accepted")
        owner_contacts = state["users"]["U-owner"]["contacts"]
        self.assertEqual(len(owner_contacts), 1)

    def test_persistent_state_conflict_leaves_no_one_sided_relationship(self):
        invite, _ = app_module.create_guardian_invite(
            self.data_file, "U-owner", {"display_name": "阿媽"}
        )
        with patch.object(
            app_module,
            "save_state",
            side_effect=app_module.StateConflictError("state_conflict"),
        ):
            result, code = app_module.bind_emergency_contact(
                self.data_file,
                {
                    "inviter_line_user_id": "U-owner",
                    "contact_line_user_id": "U-guardian",
                    "recipient_consent": True,
                    "invite_token": invite["invite_token"],
                },
                config={},
            )

        self.assertEqual(code, 409)
        self.assertEqual(result["code"], "state_conflict")
        state = app_module.load_state(self.data_file)
        self.assertEqual(state["guardian_invites"][0]["status"], "pending")
        self.assertEqual(state["users"]["U-owner"].get("contacts") or [], [])
        self.assertNotIn("U-guardian", state["users"])

    def test_bind_notification_logging_preserves_concurrent_state_update(self):
        """A write during LINE delivery must not lose data or fail the accepted bind."""
        invite, _ = app_module.create_guardian_invite(
            self.data_file, "U-owner", {"display_name": "阿媽"}
        )
        sender_calls = 0

        def sender(_token, _target, _message):
            nonlocal sender_calls
            sender_calls += 1
            if sender_calls == 1:
                concurrent = app_module.load_state(self.data_file)
                concurrent["concurrent_marker"] = "keep-me"
                app_module.save_state(self.data_file, concurrent)
            return {"ok": True}

        result, code = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-owner",
                "contact_line_user_id": "U-guardian",
                "recipient_consent": True,
                "invite_token": invite["invite_token"],
            },
            config={"LINE_CHANNEL_ACCESS_TOKEN": "token", "LINE_PUSH_SENDER": sender},
        )

        self.assertEqual(code, 200)
        self.assertTrue(result["binding_complete"])
        state = app_module.load_state(self.data_file)
        self.assertEqual(state["concurrent_marker"], "keep-me")
        logs = [
            row
            for row in state["notification_logs"]
            if row.get("kind") == "binding_complete"
        ]
        self.assertEqual(len(logs), 2)

    def test_fallback_http_create_invite_uses_authenticated_owner_and_returns_token(self):
        status, body = self.fallback_http_request(
            "POST",
            "/api/emergency-contact/invite",
            payload={"line_user_id": "U-forged"},
            authenticated_user="U-owner",
        )
        self.assertEqual(status, 201)
        self.assertTrue(body["invite_token"])
        self.assertEqual(body["inviter_line_user_id"], "U-owner")
        state = app_module.load_state(self.data_file)
        self.assertEqual(state["guardian_invites"][0]["inviter_line_user_id"], "U-owner")
        self.assertEqual(state["guardian_invites"][0]["invite_token"], body["invite_token"])
        summary = app_module.admin_summary(self.data_file)
        self.assertEqual(summary["guardian_invite_counts"]["pending"], 1)
        self.assertEqual(summary["guardian_invites"][0]["status"], "pending")
        self.assertNotIn("invite_token", summary["guardian_invites"][0])
        admin_page = (ROOT / "admin.html").read_text(encoding="utf-8")
        self.assertIn('id="pendingGuardianInvites"', admin_page)
        self.assertIn('id="acceptedGuardianInvites"', admin_page)
        self.assertIn('id="expiredGuardianInvites"', admin_page)

    def test_bind_matches_legacy_line_user_id_field(self):
        state = app_module.load_state(self.data_file)
        inviter = app_module.get_profile(state, "U-inviter")
        inviter["contacts"] = [
            {
                "id": "contact-1",
                "name": "舊格式",
                "relationship": "家人",
                "phone": "0912345678",
                "line_user_id": "U-guardian",
                "binding_status": "unbound",
            }
        ]
        app_module.save_state(self.data_file, state)

        result, code = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-inviter",
                "contact_line_user_id": "U-guardian",
                "contact_display_name": "阿媽",
            },
            config={},
        )
        self.assertEqual(code, 200)
        self.assertTrue(result["bound"])
        self.assertFalse(result["already_bound"])  # unbound → 首次同意，應推播／顯示成功
        self.assertTrue(result["binding_complete"])
        state2 = app_module.load_state(self.data_file)
        contacts = state2["users"]["U-inviter"]["contacts"]
        self.assertEqual(len(contacts), 1)
        self.assertEqual(contacts[0]["binding_status"], "accepted")
        self.assertEqual(contacts[0]["line_id"], "U-guardian")

    def test_home_gate_helpers_exist_in_spa(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("function hasHomeSetupComplete(", page)
        self.assertIn("function hasLineBoundGuardian(", page)
        self.assertIn("function hasAnyGuardianOrContact(", page)
        self.assertIn("function syncInviteUiForBoundState(", page)
        self.assertIn("hasHomeSetupComplete(currentGuardianContacts())", page)
        self.assertIn("const guardianRequired = (", page)
        self.assertIn("status.guardian_required === true", page)
        self.assertIn("status.home_ready === true", page)
        self.assertIn("mvpRewardInviteCard", page)
        self.assertIn("mvpGuardInviteCard", page)
        self.assertIn("isCheckinOpen", page)
        self.assertIn("isGuardOpen", page)
        self.assertIn('openAction === "checkin" && homeReady', page)
        self.assertNotIn("if (isCheckinOpen || isGuardOpen || forceOnboarding)", page)
        # LINE 綁定即可進首頁（不再要求聯絡人電話）
        gate = page[page.index("function hasHomeSetupComplete(") : page.index("function closeGuardianPrompt(")]
        self.assertIn("return hasLineBoundGuardian(contacts);", gate)
        self.assertNotIn("hasContactProfile", gate)
        # 一般登入不再於 LIFF init 立刻彈守護提示（等 contacts）
        init_line = page[
            page.index("async function initializeLiff()") : page.index("const LUNAR_DAY_NAMES")
        ]
        self.assertNotIn("maybeShowGuardianPrompt();", init_line)
        self.assertIn("maybeShowInviteAcceptPrompt();", init_line)
        init_app = page[page.rindex("async function initApp()") : page.index("// ===== D01")]
        self.assertIn("else if (guardianRequired)", init_app)
        self.assertIn("syncInviteUiForBoundState(homeReady)", init_app)
        self.assertIn("await showOnboarding();\n          return true;", init_app)
        # 報平安／安全守護不得被 wantsInviteShare 帶走；一鍵邀請才進分享頁
        self.assertTrue(
            'location.replace("/liff/share-invite.html")' in init_app
            or "buildShareInvitePageUrl(" in init_app
        )
        self.assertIn("onboarding/invite", init_app)
        self.assertIn("isOnboardingInvite", init_app)

    def test_form_add_does_not_copy_owner_line_id(self):
        state = app_module.load_state(self.data_file)
        app_module.get_profile(state, "U-owner")
        app_module.save_state(self.data_file, state)
        result, code = app_module.add_single_contact(
            self.data_file,
            "U-owner",
            {
                "line_user_id": "U-owner",  # auth field — must NOT become guardian LINE id
                "name": "寶寶",
                "relationship": "家人",
                "phone": "0912345678",
            },
        )
        self.assertEqual(code, 200)
        contact = result["contact"]
        self.assertEqual(contact.get("line_user_id") or "", "")
        self.assertEqual(contact.get("line_id") or "", "")
        self.assertEqual(contact.get("binding_status"), "unbound")
        self.assertFalse(app_module.contact_is_bound_guardian(contact, "U-owner"))
        status = app_module.build_status(app_module.load_state(self.data_file)["users"]["U-owner"])
        self.assertEqual(status["bound_guardian_count"], 0)
        self.assertEqual(status["contact_count"], 1)

    def test_member_access_state_rejects_every_legacy_or_unbound_false_positive(self):
        """A legacy completion signal must not make a member home-ready."""
        false_positive_profiles = {
            "legacy completion flag": {"is_onboarding_completed": True},
            "legacy interaction completion": {
                "interaction_state": {"onboarding_completed": True},
            },
            "emergency contact": {
                "contacts": [{
                    "name": "阿姨",
                    "relationship": "緊急聯絡人",
                    "phone": "0912345678",
                    "contact_role": "emergency",
                }],
            },
            "unbound guardian profile": {
                "contacts": [{
                    "name": "阿媽",
                    "relationship": "家人",
                    "phone": "0912345678",
                    "contact_role": "guardian",
                    "line_user_id": "U-unbound-guardian",
                    "line_id": "U-unbound-guardian",
                    "binding_status": "unbound",
                    "notify_methods": ["line"],
                }],
            },
            "name and phone only": {
                "contacts": [{
                    "name": "阿公",
                    "relationship": "家人",
                    "phone": "0912345678",
                }],
            },
        }
        for label, fields in false_positive_profiles.items():
            with self.subTest(label=label):
                profile = {"line_user_id": "U-member", **fields}
                access = app_module.member_access_state(profile)
                self.assertEqual(access["home_ready"], False)
                self.assertEqual(access["guardian_required"], True)
                self.assertNotIn("friend_required", access)
                self.assertNotIn("login_required", access)
                self.assertNotIn("migration_pending", access)

    def test_member_access_state_unlocks_only_a_notifiable_bound_line_guardian(self):
        profile = {
            "line_user_id": "U-member",
            "contacts": [{
                "name": "阿媽",
                "relationship": "家人",
                "contact_role": "guardian",
                "line_user_id": "U-guardian",
                "binding_status": "accepted",
                "consent_status": "accepted",
                "notify_methods": ["line"],
            }],
        }

        self.assertEqual(
            app_module.member_access_state(profile),
            {"guardian_required": False, "home_ready": True},
        )

    def test_status_and_onboarding_apis_expose_authoritative_member_access_state(self):
        app = app_module.create_app({"DATA_FILE": self.data_file, "REQUIRE_LIFF_AUTH": "0"})
        state = app_module.load_state(self.data_file)
        profile = app_module.get_profile(state, "U-member")
        profile["is_onboarding_completed"] = True
        profile["interaction_state"] = {"onboarding_completed": True}
        profile["contacts"] = [{
            "name": "阿媽",
            "relationship": "家人",
            "phone": "0912345678",
            "contact_role": "guardian",
            "binding_status": "unbound",
        }]
        app_module.save_state(self.data_file, state)

        client = app.test_client()
        status = client.get("/api/status?line_user_id=U-member").get_json()
        onboarding = client.get("/api/onboarding?line_user_id=U-member").get_json()
        for payload in (status, onboarding):
            self.assertEqual(payload["home_ready"], False)
            self.assertEqual(payload["guardian_required"], True)

    def test_onboarding_routes_use_verified_identity_not_requested_member_id(self):
        app = app_module.create_app({"DATA_FILE": self.data_file, "REQUIRE_LIFF_AUTH": "1"})
        state = app_module.load_state(self.data_file)
        owner = app_module.get_profile(state, "U-owner")
        owner["display_name"] = "本人"
        owner["contacts"] = [{
            "name": "阿媽",
            "relationship": "家人",
            "contact_role": "guardian",
            "line_user_id": "U-guardian",
            "binding_status": "accepted",
            "consent_status": "accepted",
            "notify_methods": ["line"],
        }]
        target = app_module.get_profile(state, "U-target")
        target["display_name"] = "別人"
        target["reminder_times"] = ["12:00"]
        app_module.save_state(self.data_file, state)

        # A verified U-owner token must win over an attacker-controlled U-target ID.
        with patch.object(app_module, "resolve_line_user_id", return_value=("U-owner", None)):
            client = app.test_client()
            read = client.get("/api/onboarding?line_user_id=U-target")
            self.assertEqual(read.status_code, 200)
            self.assertEqual(read.get_json()["line_user_id"], "U-owner")

            complete = client.post(
                "/api/onboarding/complete",
                data='{"line_user_id":"U-target","reminder_times":["13:00"]}',
                content_type="application/json",
            )
            reminder = client.post(
                "/api/onboarding/reminder",
                data='{"line_user_id":"U-target","reminder_times":["14:00"],"grace_hours":72}',
                content_type="application/json",
            )
        self.assertEqual(complete.status_code, 200)
        self.assertEqual(reminder.status_code, 200)
        state_after = app_module.load_state(self.data_file)
        self.assertEqual(state_after["users"]["U-owner"]["reminder_times"], ["14:00"])
        self.assertEqual(state_after["users"]["U-owner"]["grace_hours"], 72)
        self.assertEqual(state_after["users"]["U-target"]["reminder_times"], ["12:00"])

    def test_fallback_http_onboarding_read_uses_verified_identity(self):
        state = app_module.load_state(self.data_file)
        app_module.get_profile(state, "U-owner")["display_name"] = "本人"
        app_module.get_profile(state, "U-target")["display_name"] = "別人"
        app_module.save_state(self.data_file, state)

        status, payload = self.fallback_http_request(
            "GET", "/api/onboarding?line_user_id=U-target"
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["line_user_id"], "U-owner")
        self.assertEqual(payload["display_name"], "本人")

    def test_miniclient_status_uses_verified_identity_not_requested_member_id(self):
        state = app_module.load_state(self.data_file)
        app_module.get_profile(state, "U-owner")["display_name"] = "本人"
        app_module.get_profile(state, "U-target")["display_name"] = "別人"
        app_module.save_state(self.data_file, state)
        app = app_module.MiniApp({
            "DATA_FILE": self.data_file,
            "REQUIRE_LIFF_AUTH": "1",
        })

        with patch.object(
            app_module, "resolve_line_user_id", return_value=("U-owner", None)
        ):
            response = app.test_client().get(
                "/api/status?line_user_id=U-target",
                headers={"Authorization": "Bearer verified-test-token"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["line_user_id"], "U-owner")
        self.assertEqual(response.get_json()["display_name"], "本人")

    def test_miniclient_status_registers_verified_user_not_supplied_blank_id(self):
        app = app_module.MiniApp({
            "DATA_FILE": self.data_file,
            "REQUIRE_LIFF_AUTH": "1",
        })

        with patch.object(
            app_module, "resolve_line_user_id", return_value=("U-owner", None)
        ):
            response = app.test_client().get(
                "/api/status?line_user_id=U-foreign&display_name=Owner",
                headers={"Authorization": "Bearer verified-test-token"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["line_user_id"], "U-owner")
        self.assertTrue(response.get_json()["auto_registered"])
        state_after = app_module.load_state(self.data_file)
        self.assertIn("U-owner", state_after["users"])
        self.assertNotIn("U-foreign", state_after["users"])

    def test_fallback_http_status_uses_verified_identity_not_requested_member_id(self):
        state = app_module.load_state(self.data_file)
        app_module.get_profile(state, "U-owner")["display_name"] = "本人"
        app_module.get_profile(state, "U-target")["display_name"] = "別人"
        app_module.save_state(self.data_file, state)

        status, payload = self.fallback_http_request(
            "GET", "/api/status?line_user_id=U-target"
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["line_user_id"], "U-owner")
        self.assertEqual(payload["display_name"], "本人")

    def test_fallback_http_status_registers_verified_user_not_supplied_blank_id(self):
        status, payload = self.fallback_http_request(
            "GET", "/api/status?line_user_id=U-foreign&display_name=Owner"
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["line_user_id"], "U-owner")
        self.assertTrue(payload["auto_registered"])
        state_after = app_module.load_state(self.data_file)
        self.assertIn("U-owner", state_after["users"])
        self.assertNotIn("U-foreign", state_after["users"])

    def test_fallback_http_reminder_mutates_only_verified_identity(self):
        state = app_module.load_state(self.data_file)
        app_module.get_profile(state, "U-owner")["reminder_times"] = ["12:00"]
        app_module.get_profile(state, "U-target")["reminder_times"] = ["12:00"]
        app_module.save_state(self.data_file, state)

        status, payload = self.fallback_http_request(
            "POST",
            "/api/onboarding/reminder",
            payload={
                "line_user_id": "U-target",
                "reminder_times": ["14:00"],
                "grace_hours": 72,
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["reminder_times"], ["14:00"])
        state_after = app_module.load_state(self.data_file)
        self.assertEqual(state_after["users"]["U-owner"]["reminder_times"], ["14:00"])
        self.assertEqual(state_after["users"]["U-owner"]["grace_hours"], 72)
        self.assertEqual(state_after["users"]["U-target"]["reminder_times"], ["12:00"])

    def test_fallback_http_onboarding_completion_mutates_only_verified_identity(self):
        state = app_module.load_state(self.data_file)
        owner = app_module.get_profile(state, "U-owner")
        owner["contacts"] = [{
            "contact_role": "guardian",
            "line_user_id": "U-guardian",
            "binding_status": "accepted",
            "notify_methods": ["line"],
        }]
        owner["reminder_times"] = ["12:00"]
        target = app_module.get_profile(state, "U-target")
        target["reminder_times"] = ["12:00"]
        app_module.save_state(self.data_file, state)

        status, payload = self.fallback_http_request(
            "POST",
            "/api/onboarding/complete",
            payload={"line_user_id": "U-target", "reminder_times": ["13:00"]},
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["home_ready"])
        state_after = app_module.load_state(self.data_file)
        self.assertEqual(state_after["users"]["U-owner"]["reminder_times"], ["13:00"])
        self.assertFalse(state_after["users"]["U-target"].get("is_onboarding_completed", False))

    def test_fallback_http_checkin_rejects_verified_unbound_member(self):
        state = app_module.load_state(self.data_file)
        owner = app_module.get_profile(state, "U-owner")
        owner["contacts"] = [{
            "contact_role": "guardian",
            "line_user_id": "U-unbound-guardian",
            "binding_status": "unbound",
            "notify_methods": ["line"],
        }]
        target = app_module.get_profile(state, "U-target")
        target["contacts"] = [{
            "contact_role": "guardian",
            "line_user_id": "U-target-guardian",
            "binding_status": "accepted",
            "notify_methods": ["line"],
        }]
        app_module.save_state(self.data_file, state)

        status, payload = self.fallback_http_request(
            "POST", "/api/checkin", payload={"line_user_id": "U-target"}
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "guardian_required")
        state_after = app_module.load_state(self.data_file)
        self.assertEqual(state_after["users"]["U-owner"]["history"], [])
        self.assertEqual(state_after["users"]["U-target"]["history"], [])

    def test_checkin_rejects_unbound_contact_even_when_it_has_a_foreign_line_id(self):
        app = app_module.create_app({"DATA_FILE": self.data_file, "REQUIRE_LIFF_AUTH": "0"})
        state = app_module.load_state(self.data_file)
        profile = app_module.get_profile(state, "U-member")
        profile["contacts"] = [{
            "name": "阿媽",
            "relationship": "家人",
            "contact_role": "guardian",
            "line_user_id": "U-unbound-guardian",
            "binding_status": "unbound",
            "notify_methods": ["line"],
        }]
        app_module.save_state(self.data_file, state)

        response = app.test_client().post(
            "/api/checkin",
            data='{"line_user_id":"U-member"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "guardian_required")
        self.assertEqual(app_module.load_state(self.data_file)["users"]["U-member"]["history"], [])

    def test_scrub_self_line_id_fake_bind(self):
        state = app_module.load_state(self.data_file)
        user = app_module.get_profile(state, "U-jennie")
        user["contacts"] = [
            {
                "id": "contact-1",
                "name": "假綁定",
                "relationship": "家人",
                "phone": "0926568873",
                "line_user_id": "U-jennie",
                "binding_status": "unbound",
            }
        ]
        app_module.save_state(self.data_file, state)
        contacts = app_module.get_contacts(self.data_file, "U-jennie")
        self.assertEqual(contacts["contacts"][0].get("line_user_id") or "", "")
        status = app_module.build_status(app_module.load_state(self.data_file)["users"]["U-jennie"])
        self.assertEqual(status["bound_guardian_count"], 0)
        self.assertEqual(status["contact_count"], 1)

    def test_admin_summary_exposes_bound_guardians(self):
        app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-inviter",
                "contact_line_user_id": "U-guardian",
                "contact_display_name": "阿媽",
            },
            config={},
        )
        summary = app_module.admin_summary(self.data_file)
        inviter = next(u for u in summary["users"] if u["line_user_id"] == "U-inviter")
        self.assertEqual(inviter["bound_guardian_count"], 1)
        self.assertEqual(inviter["bound_guardians"][0]["line_user_id"], "U-guardian")
        self.assertEqual(summary["bound_guardian_total"], 1)
        self.assertEqual(len(summary["invite_edges"]), 1)

    def test_admin_html_renders_bind_panels(self):
        page = (ROOT / "admin.html").read_text(encoding="utf-8")
        self.assertIn("boundGuardians", page)
        self.assertIn("inviteEdgeList", page)
        self.assertIn("formatBoundGuardiansCell", page)
        self.assertIn("membershipCell", page)
        self.assertIn("守護關係（守護你的人／你守護的人）", page)
        self.assertIn("autoRefreshAdmin", page)

    def test_per_user_invite_link_format(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        share = (ROOT / "liff" / "share-invite.html").read_text(encoding="utf-8")
        self.assertIn("invite_from: safeId", page)
        self.assertIn("?invite_from=${encodeURIComponent(safeId)}", share)
        self.assertIn("buildContactInvite", page)

    def test_invite_flex_targets_dedicated_share_page(self):
        """Changing the Flex action to an R/share URL would bypass the LIFF picker flow."""
        flex = (ROOT / "guardian_group_flex.py").read_text(encoding="utf-8")

        self.assertIn('return liff_path_url("/liff/share-invite.html")', flex)
        self.assertIn("share_uri = share_invite_liff_url()", flex)

    def test_resolve_data_file_honors_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = str(Path(tmp) / "state.json")
            resolved = app_module.resolve_data_file(target)
            self.assertEqual(resolved, target)

    def test_persistence_info_marks_postgres_durable(self):
        old = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = "postgresql://user:pass@localhost/db"
        try:
            info = app_module.persistence_info("/opt/render/project/src/data/state.json")
            self.assertTrue(info["durable"])
            self.assertEqual(info["backend"], "postgres")
            self.assertEqual(info["ephemeral_warning"], "")
        finally:
            if old is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = old

    def test_bind_writes_guarding_details_on_invitee(self):
        result, code = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-inviter",
                "contact_line_user_id": "U-guardian",
                "contact_display_name": "阿媽",
            },
            config={},
        )
        self.assertEqual(code, 200)
        state = app_module.load_state(self.data_file)
        guardian = state["users"]["U-guardian"]
        self.assertEqual(guardian.get("invited_by"), "U-inviter")
        details = guardian.get("guarding_details") or []
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]["line_user_id"], "U-inviter")
        status = app_module.build_status(guardian)
        self.assertEqual(status["guarding_details"][0]["line_user_id"], "U-inviter")
        contact = result["contact"]
        self.assertEqual(contact.get("contact_role"), "guardian")
        self.assertEqual(contact.get("relationship"), "守護人")


    def test_duplicate_bind_returns_already_bound_not_limit_error(self):
        pushed = []

        def fake_sender(token, line_user_id, message):
            pushed.append((line_user_id, message))
            return {"ok": True, "status": 200}

        first, code1 = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-inviter",
                "contact_line_user_id": "U-guardian",
                "contact_display_name": "寶寶",
                "contact_picture_url": "https://example.com/avatar.jpg",
            },
            config={"LINE_CHANNEL_ACCESS_TOKEN": "tok", "LINE_PUSH_SENDER": fake_sender},
        )
        self.assertEqual(code1, 200)
        self.assertTrue(first["bound"])
        self.assertFalse(first["already_bound"])
        self.assertEqual(first["contact"]["picture_url"], "https://example.com/avatar.jpg")
        self.assertEqual(len(pushed), 2)
        self.assertTrue(
            "感謝邀請成功" in pushed[0][1]
            or "守護人綁定完成" in pushed[0][1]
            or ("綁定成功" in pushed[0][1] and "已成為你的守護人" in pushed[0][1]),
            pushed[0][1],
        )
        self.assertTrue(
            "你已接受邀請" in pushed[1][1]
            or "你已成為對方的守護人" in pushed[1][1]
            or ("綁定成功" in pushed[1][1] and "守護人" in pushed[1][1]),
            pushed[1][1],
        )
        self.assertTrue(first.get("inviter_notified"))
        self.assertTrue(first.get("guardian_notified"))
        self.assertTrue(first.get("binding_complete"))
        self.assertFalse(first.get("invite_reward_applied"))
        self.assertEqual(first.get("trial_bonus_days"), 0)
        self.assertTrue(str(first["contact"].get("bind_notify_sent_at") or "").strip())
        self.assertEqual(first.get("notify_hint") or "", "")
        self.assertEqual(first.get("notify_errors") or [], [])

        second, code2 = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-inviter",
                "contact_line_user_id": "U-guardian",
                "contact_display_name": "寶寶",
            },
            config={"LINE_CHANNEL_ACCESS_TOKEN": "tok", "LINE_PUSH_SENDER": fake_sender},
        )
        self.assertEqual(code2, 200)
        self.assertTrue(second["already_bound"])
        self.assertIn("已經是守護人", second["message"])
        self.assertEqual(len(pushed), 2)  # no second notify storm

    def test_bind_notify_failure_returns_hint_without_blocking_bind(self):
        def failing_sender(token, line_user_id, message):
            raise RuntimeError("400 Bad Request: Failed to send messages; not a friend")

        result, code = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-inviter",
                "contact_line_user_id": "U-guardian",
                "contact_display_name": "寶寶",
            },
            config={"LINE_CHANNEL_ACCESS_TOKEN": "tok", "LINE_PUSH_SENDER": failing_sender},
        )
        self.assertEqual(code, 200)
        self.assertTrue(result["bound"])
        self.assertTrue(result["binding_complete"])
        self.assertFalse(result["inviter_notified"])
        self.assertFalse(result["guardian_notified"])
        self.assertTrue(result.get("notify_hint"))
        self.assertIn("好友", result["notify_hint"])
        self.assertEqual(len(result.get("notify_errors") or []), 2)

    def test_limit_full_without_match_returns_chinese(self):
        state = app_module.load_state(self.data_file)
        inviter = app_module.get_profile(state, "U-inviter")
        inviter["plan"] = "free"
        inviter["membership_source"] = "expired"
        inviter["contacts"] = [
            {
                "id": "c1",
                "name": "別人",
                "relationship": "家人",
                "phone": "0911111111",
                "line_id": "U-other",
                "line_user_id": "U-other",
                "binding_status": "accepted",
                "consent_status": "accepted",
                "is_primary": True,
            }
        ]
        app_module.save_state(self.data_file, state)
        result, code = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-inviter",
                "contact_line_user_id": "U-new",
                "contact_display_name": "新人",
            },
            config={},
        )
        self.assertEqual(code, 400)
        self.assertEqual(result.get("code"), "contact_limit")
        self.assertNotIn("exceeded", str(result.get("error") or "").lower())
        self.assertIn("名額", result.get("message") or result.get("error") or "")

    def test_merge_unbound_slot_when_limit_full(self):
        state = app_module.load_state(self.data_file)
        inviter = app_module.get_profile(state, "U-inviter")
        inviter["contacts"] = [
            {
                "id": "c1",
                "name": "寶寶",
                "relationship": "家人",
                "phone": "0912345678",
                "line_id": "",
                "binding_status": "unbound",
                "is_primary": True,
            }
        ]
        app_module.save_state(self.data_file, state)
        result, code = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-inviter",
                "contact_line_user_id": "U-guardian",
                "contact_display_name": "寶寶LINE",
            },
            config={},
        )
        self.assertEqual(code, 200)
        self.assertTrue(result["bound"])
        state2 = app_module.load_state(self.data_file)
        contacts = state2["users"]["U-inviter"]["contacts"]
        self.assertEqual(len(contacts), 1)
        self.assertEqual(contacts[0]["line_user_id"], "U-guardian")
        self.assertEqual(contacts[0]["binding_status"], "accepted")

    def test_admin_summary_membership_and_core_counts(self):
        app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-inviter",
                "contact_line_user_id": "U-guardian",
                "contact_display_name": "寶寶",
            },
            config={},
        )
        # 模擬真實暱稱寫入
        state = app_module.load_state(self.data_file)
        state["users"]["U-inviter"]["display_name"] = "小美"
        app_module.save_state(self.data_file, state)
        summary = app_module.admin_summary(self.data_file)
        inviter = next(u for u in summary["users"] if u["line_user_id"] == "U-inviter")
        self.assertEqual(inviter["bound_guardian_count"], 1)
        self.assertGreaterEqual(inviter["core_guardian_count"], 1)
        self.assertIn("trial_days_text", inviter)
        self.assertIn("upgrade_status", inviter)
        self.assertIn("membership_label", inviter)
        self.assertEqual(inviter["display_name"], "小美")
        self.assertIn("plan_expires_text", inviter)
        self.assertIn("到期", inviter["plan_expires_text"])
        self.assertFalse(inviter.get("display_name_missing"))

    def test_admin_placeholder_name_marked(self):
        state = app_module.load_state(self.data_file)
        user = app_module.get_profile(state, "U-anon")
        user["display_name"] = "LINE 使用者"
        app_module.save_state(self.data_file, state)
        summary = app_module.admin_summary(self.data_file)
        anon = next(u for u in summary["users"] if u["line_user_id"] == "U-anon")
        self.assertTrue(anon.get("display_name_missing"))
        self.assertNotEqual(anon.get("display_name"), "LINE 使用者")
        self.assertIn("未取得暱稱", anon.get("display_name"))
        page = (ROOT / "admin.html").read_text(encoding="utf-8")
        self.assertIn("memberNameCell", page)
        self.assertIn("plan_expires_text", page)
        self.assertIn("方案到期（試用／訂閱）", page)

    def test_reregister_preserves_trial_and_bindings(self):
        """Re-login must NOT restart trial clock or wipe contacts."""
        first, code1 = app_module.register_line_user(
            self.data_file,
            {"line_user_id": "U-persist", "display_name": "小孟"},
        )
        self.assertEqual(code1, 200)
        started = first.get("trial_started_at")
        self.assertTrue(started)

        # Bind a guardian then re-register as if LIFF reopened.
        app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-persist",
                "contact_line_user_id": "U-guard-1",
                "contact_display_name": "阿爸",
            },
            config={},
        )
        # Simulate clock advancing: mutate stored trial to a fixed past value.
        state = app_module.load_state(self.data_file)
        state["users"]["U-persist"]["trial_started_at"] = "2026-07-20T10:00:00"
        state["users"]["U-persist"]["trial_end"] = "2026-08-03T10:00:00"
        state["users"]["U-persist"]["history"] = ["2026-07-21", "2026-07-22"]
        app_module.save_state(self.data_file, state)

        second, code2 = app_module.register_line_user(
            self.data_file,
            {"line_user_id": "U-persist", "display_name": "小孟"},
        )
        self.assertEqual(code2, 200)
        self.assertTrue(second.get("existing_user"))
        self.assertEqual(second.get("trial_started_at"), "2026-07-20T10:00:00")
        # Re-registration preserves the one-time trial and no invite bonus is added.
        self.assertEqual(
            second.get("trial_days_left"),
            app_module.trial_days_left(
                {
                    "trial_started_at": "2026-07-20T10:00:00",
                    "trial_end": "2026-08-03T10:00:00",
                    "plan": "trial",
                    "trial_bonus_days": second.get("trial_bonus_days") or 0,
                }
            ),
        )
        self.assertEqual(int(second.get("trial_bonus_days") or 0), 0)
        contacts = second.get("contacts") or []
        self.assertEqual(len(contacts), 1)
        self.assertEqual(app_module.get_contact_line_id(contacts[0]), "U-guard-1")
        self.assertIn("2026-07-21", second.get("history") or [])

    def test_save_contacts_merges_binding_fields(self):
        app_module.register_line_user(
            self.data_file, {"line_user_id": "U-owner", "display_name": "主人"}
        )
        app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-owner",
                "contact_line_user_id": "U-g1",
                "contact_display_name": "阿媽",
            },
            config={},
        )
        state = app_module.load_state(self.data_file)
        contact = state["users"]["U-owner"]["contacts"][0]
        contact_id = contact["id"]

        # Client payload omits LINE bind fields (common after form edit).
        result, code = app_module.save_contacts(
            self.data_file,
            {
                "line_user_id": "U-owner",
                "contacts": [
                    {
                        "id": contact_id,
                        "name": "阿媽改名",
                        "relationship": "媽媽",
                        "phone": "0911111111",
                        "contact_role": "guardian",
                    }
                ],
            },
        )
        self.assertEqual(code, 200)
        saved = result["contacts"][0]
        self.assertEqual(saved["name"], "阿媽改名")
        self.assertEqual(app_module.get_contact_line_id(saved), "U-g1")
        self.assertEqual(saved.get("binding_status"), "accepted")


    def test_member_center_list_before_add_markers(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertTrue(
            "守護人（Guardian）" in page or "核心守護人" in page,
            "guardian section title missing",
        )
        self.assertIn("memberGuardianQuotaLine", page)
        self.assertIn("memberGuardianLimitBanner", page)
        self.assertIn("memberEmergencySection", page)
        self.assertIn("你已經有", page)
        self.assertIn("ensureSyncedContactData", page)
        self.assertIn("contact_role", page)
        # 不可再用 role（核心／一般）當成 contact_role
        self.assertIn("不可讀 role", page)
        self.assertIn("memberAddGuardianBtn", page)
        self.assertTrue(
            "➕ 新增核心守護人" in page or "➕ 新增守護人" in page,
            "member add guardian button missing",
        )
        self.assertTrue(
            "➕ 新增聯絡人" in page or "➕ 新增緊急聯絡人" in page,
            "member add contact button missing",
        )
        self.assertIn("名額已滿", page)
        share = (ROOT / "liff" / "share-invite.html").read_text(encoding="utf-8")
        self.assertIn("goNextStep", share)
        self.assertTrue(
            "完成，返回原位置" in share or "完成，回首頁" in share,
            "share done CTA missing",
        )
        admin = (ROOT / "admin.html").read_text(encoding="utf-8")
        self.assertIn("membershipCell", admin)
        self.assertIn("體驗剩幾天", admin)
        self.assertIn("緊急聯絡人／名額", admin)
        self.assertNotIn("核心／一般／名額", admin)
        self.assertIn("資料可能因重啟遺失請掛磁碟", admin)

    def test_contact_role_ignores_core_general_role_field(self):
        """根因：role=核心／一般 被誤當 contact_role → 列表被濾空。"""
        self.assertEqual(
            app_module.resolve_contact_role({"role": "一般", "name": "阿媽"}),
            "guardian",
        )
        self.assertEqual(
            app_module.resolve_contact_role({"role": "核心", "name": "阿爸"}),
            "guardian",
        )
        self.assertEqual(
            app_module.resolve_contact_role({"contact_role": "emergency", "role": "核心"}),
            "emergency",
        )
        normalized = app_module.normalize_contact(
            {"name": "阿媽", "relationship": "媽媽", "phone": "0912345678", "role": "一般"},
            0,
        )
        self.assertEqual(normalized["contact_role"], "guardian")
        self.assertNotIn("role", normalized)

    def test_backfill_bind_notify_is_idempotent(self):
        pushed = []

        def fake_sender(token, line_user_id, message):
            pushed.append((line_user_id, message))
            return {"ok": True, "status": 200}

        # Seed a historical accepted bind WITHOUT notify flag (pre dual-notify era)
        state = app_module.load_state(self.data_file)
        inviter = app_module.get_profile(state, "U-old-inviter")
        inviter["display_name"] = "小孟"
        inviter["contacts"] = [
            {
                "id": "line-U-old-g",
                "name": "阿公",
                "relationship": "爺爺",
                "line_id": "U-old-g",
                "line_user_id": "U-old-g",
                "binding_status": "accepted",
                "consent_status": "accepted",
                "accepted_at": "2026-07-20T10:00:00",
                "contact_role": "guardian",
                "is_primary": True,
            }
        ]
        guardian = app_module.get_profile(state, "U-old-g")
        guardian["display_name"] = "阿公"
        guardian["guarding_for"] = ["U-old-inviter"]
        app_module.save_state(self.data_file, state)

        cfg = {
            "DATA_FILE": self.data_file,
            "LINE_CHANNEL_ACCESS_TOKEN": "tok",
            "LINE_PUSH_SENDER": fake_sender,
            "APP_TIMEZONE": "Asia/Taipei",
        }
        first, code = app_module.backfill_bind_notify(cfg)
        self.assertEqual(code, 200)
        self.assertEqual(first["pairs_notified"], 1)
        self.assertEqual(len(pushed), 2)
        self.assertTrue(
            "守護人綁定完成" in pushed[0][1]
            or ("綁定成功" in pushed[0][1] and "已成為你的守護人" in pushed[0][1]),
            pushed[0][1],
        )
        self.assertTrue(
            "你已接受邀請" in pushed[1][1]
            or "你已成為對方的守護人" in pushed[1][1],
            pushed[1][1],
        )

        state2 = app_module.load_state(self.data_file)
        contact = state2["users"]["U-old-inviter"]["contacts"][0]
        self.assertTrue(str(contact.get("bind_notify_sent_at") or "").strip())

        second, code2 = app_module.backfill_bind_notify(cfg)
        self.assertEqual(code2, 200)
        self.assertEqual(second["pairs_notified"], 0)
        self.assertEqual(second["pairs_skipped"], 1)
        self.assertEqual(len(pushed), 2)  # no re-spam

        dry, code3 = app_module.backfill_bind_notify(cfg, dry_run=True)
        self.assertEqual(code3, 200)
        self.assertTrue(dry["dry_run"])
        self.assertEqual(dry["pairs_notified"], 0)

    def test_reverse_invite_requires_a_second_independent_consent(self):
        """媽媽、女兒要互相守護，必須完成兩次獨立邀請與同意。"""
        first, code1 = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-mom",
                "contact_line_user_id": "U-daughter",
                "contact_display_name": "女兒",
            },
            config={},
        )
        self.assertEqual(code1, 200)
        self.assertFalse(first.get("is_reverse_invite"))

        state = app_module.load_state(self.data_file)
        state["users"]["U-mom"]["display_name"] = "媽媽"
        state["users"]["U-daughter"]["display_name"] = "女兒"
        app_module.save_state(self.data_file, state)

        preview, pcode = app_module.invite_bind_preview(
            self.data_file,
            {"invite_from": "U-daughter", "line_user_id": "U-mom"},
        )
        self.assertEqual(pcode, 200)
        self.assertTrue(preview["is_reverse_invite"])
        self.assertEqual(preview["inviter_display_name"], "女兒")
        self.assertIn("本次邀請仍需你另外同意", preview["message"])

        preview2, pcode2 = app_module.invite_bind_preview(
            self.data_file,
            {"invite_from": "U-stranger", "line_user_id": "U-mom"},
        )
        self.assertEqual(pcode2, 200)
        self.assertFalse(preview2["is_reverse_invite"])

        second, code2 = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-daughter",
                "contact_line_user_id": "U-mom",
                "contact_display_name": "媽媽",
                "mutual_core": True,
            },
            config={},
        )
        self.assertEqual(code2, 200)
        self.assertTrue(second["is_reverse_invite"])
        self.assertFalse(second["mutual_core_requested"])
        self.assertFalse(second["mutual_core_applied"])
        self.assertNotIn("互綁完成", second["message"])
        self.assertIn("兩個守護方向均已各自同意", second["message"])

        state2 = app_module.load_state(self.data_file)
        mom = state2["users"]["U-mom"]
        daughter = state2["users"]["U-daughter"]
        mom_on_daughter = next(
            c for c in daughter["contacts"] if app_module.get_contact_line_id(c) == "U-mom"
        )
        self.assertTrue(mom_on_daughter.get("is_primary"))
        daughter_on_mom = next(
            c for c in mom["contacts"] if app_module.get_contact_line_id(c) == "U-daughter"
        )
        self.assertTrue(daughter_on_mom.get("is_primary"))
        self.assertIn("U-daughter", mom.get("guarding_for") or [])
        self.assertIn("U-mom", daughter.get("guarding_for") or [])

    def test_spa_has_one_way_guardian_and_separate_trial_ui(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("apiInviteBindPreview", page)
        self.assertIn("is_reverse_invite", page)
        self.assertIn("我也要報平安｜免費體驗 14 天", page)
        self.assertIn("startMyOwnTrialFromGuardianSuccess", page)
        self.assertIn("guardian_only: Boolean(inviteFrom", page)
        self.assertNotIn("mutualCoreCheckbox", page)
        self.assertNotIn("同時互相設為核心守護人", page)


if __name__ == "__main__":
    unittest.main()
