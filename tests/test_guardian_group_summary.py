from datetime import datetime
from pathlib import Path
import threading
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

import app


class GuardianGroupSummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_file = Path(self.tmp.name) / "state.json"

    def tearDown(self):
        self.tmp.cleanup()

    def save_group(self, preferences, member_ids_at_bind=None):
        app.save_state(self.data_file, {
            "users": {
                "U-owner": {
                    "line_user_id": "U-owner",
                    "display_name": "本人",
                    "plan": "paid_799",
                    "payment_status": "active",
                    "history": ["2026-07-27"],
                    "contacts": [{
                        "line_user_id": "U-active",
                        "name": "有效成員",
                        "role": "core",
                        "is_primary": True,
                        "binding_status": "accepted",
                        "consent_status": "accepted",
                        "notify_methods": ["line"],
                    }],
                },
                "U-active": {
                    "line_user_id": "U-active",
                    "display_name": "有效成員",
                    "history": [],
                    "contacts": [{
                        "line_user_id": "U-owner",
                        "name": "本人",
                        "role": "core",
                        "is_primary": True,
                        "binding_status": "accepted",
                        "consent_status": "accepted",
                        "notify_methods": ["line"],
                    }],
                },
                "U-removed": {
                    "line_user_id": "U-removed",
                    "display_name": "已退出成員",
                    "history": [],
                },
            },
            "guardian_groups": {
                "C-group": {
                    "group_id": "C-group",
                    "owner_line_user_id": "U-owner",
                    "status": "active",
                    "member_ids_at_bind": member_ids_at_bind or ["U-active", "U-removed"],
                    "preferences": preferences,
                },
            },
        })

    def config(self, sender, now, fetcher):
        return {
            "DATA_FILE": self.data_file,
            "LINE_CHANNEL_ACCESS_TOKEN": "token",
            "LINE_PUSH_SENDER": sender,
            "GROUP_MEMBER_IDS_FETCHER": fetcher,
            "CRON_NOW": now,
        }

    def test_summary_is_off_by_default(self):
        self.save_group({})
        sent = []
        result, code = app.send_guardian_group_daily_summaries(
            self.config(lambda *_args: sent.append(True), datetime(2026, 7, 27, 21, 0), lambda *_args: ["U-active"])
        )
        self.assertEqual(code, 200)
        self.assertEqual(result["sent"], 0)
        self.assertEqual(sent, [])

    def test_custom_summary_time_defers_until_configured_minute(self):
        self.save_group({"daily_admin_summary": True, "daily_summary_time": "22:30"})
        result, code = app.send_guardian_group_daily_summaries(
            self.config(lambda *_args: {"ok": True}, datetime(2026, 7, 27, 22, 29), lambda *_args: ["U-active"])
        )
        self.assertEqual(code, 200)
        self.assertEqual(result["sent"], 0)
        self.assertEqual(result["deferred"], 1)

    def test_summary_recomputes_members_and_excludes_removed_snapshot_member(self):
        self.save_group({"daily_admin_summary": True, "daily_summary_time": "21:00"})
        messages = []
        result, code = app.send_guardian_group_daily_summaries(
            self.config(
                lambda _token, _group, message: messages.append(message) or {"ok": True},
                datetime(2026, 7, 27, 21, 0),
                lambda _token, _group: ["U-owner", "U-active"],
            )
        )
        self.assertEqual(code, 200)
        self.assertEqual(result["sent"], 1)
        self.assertIn("有效成員", messages[0])
        self.assertNotIn("已退出成員", messages[0])
        stored = app.load_state(self.data_file)["guardian_groups"]["C-group"]
        self.assertEqual(stored["member_ids_last_summary"], ["U-owner", "U-active"])

    def test_summary_excludes_current_group_member_without_live_guardian_relationship(self):
        self.save_group({"daily_admin_summary": True, "daily_summary_time": "21:00"})
        messages = []

        result, code = app.send_guardian_group_daily_summaries(
            self.config(
                lambda _token, _group, message: messages.append(message) or {"ok": True},
                datetime(2026, 7, 27, 21, 0),
                lambda _token, _group: ["U-owner", "U-active", "U-removed"],
            )
        )

        self.assertEqual(code, 200)
        self.assertEqual(result["sent"], 1)
        self.assertIn("有效成員", messages[0])
        self.assertNotIn("已退出成員", messages[0])

    def test_summary_skips_group_when_no_current_member_has_live_relationship(self):
        self.save_group({"daily_admin_summary": True, "daily_summary_time": "21:00"})
        sent = []

        result, code = app.send_guardian_group_daily_summaries(
            self.config(
                lambda *_args: sent.append(True) or {"ok": True},
                datetime(2026, 7, 27, 21, 0),
                lambda _token, _group: ["U-removed"],
            )
        )

        self.assertEqual(code, 200)
        self.assertEqual(result["sent"], 0)
        self.assertEqual(sent, [])
        self.assertEqual(result["results"][0]["status"], "no_eligible_members")

    def test_summary_skips_when_owner_membership_is_not_active(self):
        self.save_group({"daily_admin_summary": True, "daily_summary_time": "21:00"})
        state = app.load_state(self.data_file)
        state["users"]["U-owner"]["payment_status"] = "expired"
        app.save_state(self.data_file, state)
        sent = []

        result, code = app.send_guardian_group_daily_summaries(
            self.config(
                lambda *_args: sent.append(True) or {"ok": True},
                datetime(2026, 7, 27, 21, 0),
                lambda _token, _group: ["U-owner", "U-active"],
            )
        )

        self.assertEqual(code, 200)
        self.assertEqual(result["sent"], 0)
        self.assertEqual(sent, [])
        self.assertEqual(result["results"][0]["status"], "owner_not_eligible")

    def test_summary_excludes_emergency_contact_even_when_both_rows_are_accepted(self):
        self.save_group({"daily_admin_summary": True, "daily_summary_time": "21:00"})
        state = app.load_state(self.data_file)
        state["users"]["U-owner"]["contacts"][0]["contact_role"] = "emergency"
        state["users"]["U-active"]["contacts"][0]["contact_role"] = "emergency"
        app.save_state(self.data_file, state)
        messages = []

        result, code = app.send_guardian_group_daily_summaries(
            self.config(
                lambda _token, _group, message: messages.append(message) or {"ok": True},
                datetime(2026, 7, 27, 21, 0),
                lambda _token, _group: ["U-owner", "U-active"],
            )
        )

        self.assertEqual(code, 200)
        self.assertEqual(result["sent"], 1)
        self.assertNotIn("有效成員", messages[0])

    def test_summary_excludes_bound_guardian_who_is_not_primary(self):
        self.save_group({"daily_admin_summary": True, "daily_summary_time": "21:00"})
        state = app.load_state(self.data_file)
        state["users"]["U-owner"]["contacts"][0]["is_primary"] = False
        state["users"]["U-active"]["contacts"][0]["is_primary"] = False
        app.save_state(self.data_file, state)
        messages = []

        result, code = app.send_guardian_group_daily_summaries(
            self.config(
                lambda _token, _group, message: messages.append(message) or {"ok": True},
                datetime(2026, 7, 27, 21, 0),
                lambda _token, _group: ["U-owner", "U-active"],
            )
        )

        self.assertEqual(code, 200)
        self.assertEqual(result["sent"], 1)
        self.assertNotIn("有效成員", messages[0])

    def test_summary_rechecks_current_preferences_after_member_refresh(self):
        self.save_group({"daily_admin_summary": True, "daily_summary_time": "21:00"})
        sent = []

        def fetch_then_disable(_token, _group):
            state = app.load_state(self.data_file)
            state["guardian_groups"]["C-group"]["preferences"]["daily_admin_summary"] = False
            app.save_state(self.data_file, state)
            return ["U-owner", "U-active"]

        result, code = app.send_guardian_group_daily_summaries(
            self.config(
                lambda *_args: sent.append(True) or {"ok": True},
                datetime(2026, 7, 27, 21, 0),
                fetch_then_disable,
            )
        )

        self.assertEqual(code, 200)
        self.assertEqual(result["sent"], 0)
        self.assertEqual(sent, [])
        self.assertEqual(result["results"][0]["status"], "no_longer_eligible")

    def test_overlapping_cron_runs_send_and_charge_only_once(self):
        self.save_group({"daily_admin_summary": True, "daily_summary_time": "21:00"})
        calls = []
        sender_entered = threading.Event()
        release_sender = threading.Event()

        def sender(_token, group_id, _message):
            calls.append(group_id)
            sender_entered.set()
            release_sender.wait(timeout=2)
            return {"ok": True}

        results = []
        config = self.config(
            sender,
            datetime(2026, 7, 27, 21, 0),
            lambda *_args: ["U-owner", "U-active"],
        )
        first = threading.Thread(
            target=lambda: results.append(
                app.send_guardian_group_daily_summaries(config)
            )
        )
        second = threading.Thread(
            target=lambda: results.append(
                app.send_guardian_group_daily_summaries(config)
            )
        )
        first.start()
        self.assertTrue(sender_entered.wait(timeout=2))
        second.start()
        second.join(timeout=2)
        release_sender.set()
        first.join(timeout=2)

        state = app.load_state(self.data_file)
        usage = [
            row for row in state.get("line_message_usage", [])
            if row.get("category") == "guardian_summary"
        ]
        self.assertEqual(calls, ["C-group"])
        self.assertEqual(len(usage), 1)
        self.assertTrue(any(
            row[0]["results"][0].get("status") == "already_claimed"
            for row in results
        ))

    def test_member_refresh_retries_three_times_then_writes_audit(self):
        self.save_group({"daily_admin_summary": True, "daily_summary_time": "21:00"})
        attempts = []

        def failing_fetcher(_token, group_id):
            attempts.append(group_id)
            raise TimeoutError("LINE members timeout")

        result, code = app.send_guardian_group_daily_summaries(
            self.config(
                lambda *_args: self.fail("summary must not be sent"),
                datetime(2026, 7, 27, 21, 0),
                failing_fetcher,
            )
        )

        state = app.load_state(self.data_file)
        logs = [
            row for row in state.get("notification_logs", [])
            if row.get("kind") == "guardian_group_member_refresh"
        ]
        group = state["guardian_groups"]["C-group"]
        self.assertEqual(code, 200)
        self.assertEqual(attempts, ["C-group", "C-group", "C-group"])
        self.assertEqual(result["results"][0]["status"], "member_refresh_failed")
        self.assertEqual(len(logs), 1)
        self.assertNotIn("daily_summary_claims", group)

    def test_active_claim_cannot_be_stolen_but_expired_claim_recovers(self):
        self.save_group({"daily_admin_summary": True, "daily_summary_time": "21:00"})
        now = datetime(2026, 7, 27, 21, 0)
        first = app.mutate_state_atomically(
            self.data_file,
            lambda state: app._claim_guardian_group_summary(
                state, "C-group", "2026-07-27", now
            ),
        )
        active = app.mutate_state_atomically(
            self.data_file,
            lambda state: app._claim_guardian_group_summary(
                state, "C-group", "2026-07-27", datetime(2026, 7, 27, 21, 5)
            ),
        )
        recovered = app.mutate_state_atomically(
            self.data_file,
            lambda state: app._claim_guardian_group_summary(
                state, "C-group", "2026-07-27", datetime(2026, 7, 27, 21, 16)
            ),
        )

        self.assertTrue(first["claimed"])
        self.assertFalse(active["claimed"])
        self.assertEqual(active["reason"], "active_claim")
        self.assertTrue(recovered["claimed"])
        self.assertTrue(recovered["recovered"])

    def test_line_push_uses_stable_retry_key_and_accepts_duplicate_response(self):
        delivery_key = "guardian_group_daily_summary:2026-07-27:C-group"
        retry_key = app._line_retry_key(delivery_key)
        self.assertEqual(retry_key, app._line_retry_key(delivery_key))
        self.assertNotEqual(
            retry_key,
            app._line_retry_key(
                "guardian_group_daily_summary:2026-07-28:C-group"
            ),
        )
        requests = []

        def duplicate_response(request, timeout):
            requests.append((request, timeout))
            raise urllib.error.HTTPError(
                request.full_url,
                409,
                "Conflict",
                {"X-Line-Accepted-Request-Id": "accepted-123"},
                None,
            )

        with patch.object(app.urllib.request, "urlopen", duplicate_response):
            result = app.line_push_message(
                "token",
                "C-group",
                "摘要",
                retry_key=retry_key,
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["idempotent_replay"])
        self.assertEqual(result["accepted_request_id"], "accepted-123")
        self.assertEqual(
            requests[0][0].get_header("X-line-retry-key"),
            retry_key,
        )


if __name__ == "__main__":
    unittest.main()
