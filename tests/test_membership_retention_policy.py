import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import app as app_module


class MembershipRetentionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.fromisoformat("2026-07-27T12:00:00")

    def test_expiry_pauses_service_but_keeps_contacts_without_auto_delete_deadline(self):
        state = {
            "users": {
                "U-owner": {
                    "line_user_id": "U-owner",
                    "plan": "paid_399",
                    "payment_status": "active",
                    "paid_until": (self.now - timedelta(seconds=1)).isoformat(),
                    "contacts": [{"name": "媽媽", "binding_status": "accepted"}],
                    "guardian_group_ids": ["C-family"],
                    "daily_checkin_reminder_enabled": True,
                    "location": {"active": True, "sharing": True},
                }
            }
        }
        changed = app_module._apply_expired_plan_downgrades_to_state(
            state, self.now
        )
        profile = state["users"]["U-owner"]
        self.assertEqual(changed, ["U-owner"])
        self.assertEqual(profile["contacts"][0]["name"], "媽媽")
        self.assertEqual(profile["guardian_group_ids"], ["C-family"])
        self.assertTrue(profile["membership_paused"])
        self.assertFalse(profile["daily_checkin_reminder_enabled"])
        self.assertFalse(profile["location"]["active"])
        self.assertEqual(profile.get("contacts_retain_until"), "")
        self.assertFalse(
            app_module.soft_archive_contacts_past_retain(
                profile, self.now + timedelta(days=500)
            )
        )
        self.assertEqual(len(profile["contacts"]), 1)

    def test_beta_expiry_lapses_exactly_at_end_and_is_idempotent(self):
        state = {
            "users": {
                "U-beta": {
                    "line_user_id": "U-beta",
                    "membership_source": "beta",
                    "plan": "paid_799",
                    "payment_status": "beta",
                    "beta_started_at": (
                        self.now - timedelta(days=21)
                    ).isoformat(timespec="seconds"),
                    "beta_ends_at": self.now.isoformat(timespec="seconds"),
                    "contacts": [{"name": "媽媽", "binding_status": "accepted"}],
                    "guardian_group_ids": ["C-family"],
                    "daily_checkin_reminder_enabled": True,
                }
            }
        }

        first = app_module._apply_expired_plan_downgrades_to_state(
            state, self.now
        )
        second = app_module._apply_expired_plan_downgrades_to_state(
            state, self.now + timedelta(seconds=1)
        )
        profile = state["users"]["U-beta"]

        self.assertEqual(first, ["U-beta"])
        self.assertEqual(second, [])
        self.assertEqual(profile["plan"], "free")
        self.assertEqual(profile["membership_source"], "expired")
        self.assertTrue(profile["membership_paused"])
        self.assertEqual(profile["contacts"][0]["name"], "媽媽")
        self.assertEqual(profile["guardian_group_ids"], ["C-family"])
        self.assertFalse(
            app_module.membership_access_active(profile, self.now)
        )

    def test_paused_membership_sends_no_due_or_checkin_notifications(self):
        with TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "data.json"
            profile = {
                "line_user_id": "U-owner",
                "display_name": "王媽媽",
                "plan": "free",
                "membership_source": "expired",
                "membership_paused": True,
                "daily_checkin_reminder_enabled": True,
                "last_check_in": (
                    self.now - timedelta(days=3)
                ).isoformat(timespec="seconds"),
                "reminder_times": [self.now.strftime("%H:%M")],
                "contacts": [{
                    "line_user_id": "U-guardian",
                    "line_id": "U-guardian",
                    "binding_status": "accepted",
                    "notify_methods": ["line"],
                }],
            }
            app_module.save_state(data_file, {"users": {"U-owner": profile}})
            sent = []
            config = {
                "DATA_FILE": data_file,
                "CRON_NOW": self.now,
                "LINE_CHANNEL_ACCESS_TOKEN": "token",
                "LINE_PUSH_SENDER": lambda *args: sent.append(args),
            }

            due, due_code = app_module.send_due_reminders(config)
            checkin, checkin_code = app_module.send_checkin_reminders(config)

            self.assertEqual((due_code, checkin_code), (200, 200))
            self.assertEqual(due["sent"], 0)
            self.assertEqual(checkin["sent"], 0)
            self.assertEqual(sent, [])

    def test_paid_renewal_restores_paused_service_without_reinviting(self):
        profile = {
            "line_user_id": "U-owner",
            "plan": "free",
            "membership_source": "expired",
            "membership_paused": True,
            "contacts": [{"name": "媽媽", "binding_status": "accepted"}],
            "guardian_group_ids": ["C-family"],
        }
        app_module.restore_membership_after_renewal(
            profile,
            "paid_399",
            self.now + timedelta(days=30),
            now=self.now,
        )
        self.assertFalse(profile["membership_paused"])
        self.assertTrue(profile["daily_checkin_reminder_enabled"])
        self.assertEqual(profile["contacts"][0]["name"], "媽媽")
        self.assertEqual(profile["guardian_group_ids"], ["C-family"])

    def test_verified_privacy_unlink_is_idempotent_and_audited(self):
        state = {
            "users": {
                "U-owner": {
                    "line_user_id": "U-owner",
                    "contacts": [{
                        "line_user_id": "U-guardian",
                        "binding_status": "accepted",
                    }],
                },
                "U-guardian": {
                    "line_user_id": "U-guardian",
                    "contacts": [{
                        "line_user_id": "U-owner",
                        "binding_status": "accepted",
                    }],
                },
            }
        }
        first = app_module.process_verified_privacy_request(
            state, "U-owner", "unlink_guardian", peer_line_user_id="U-guardian",
            now=self.now,
        )
        second = app_module.process_verified_privacy_request(
            state, "U-owner", "unlink_guardian", peer_line_user_id="U-guardian",
            now=self.now,
        )
        self.assertTrue(first["processed"])
        self.assertTrue(second["idempotent"])
        self.assertEqual(state["users"]["U-owner"]["contacts"], [])
        self.assertEqual(state["users"]["U-guardian"]["contacts"], [])
        self.assertEqual(len(state["privacy_requests"]), 1)

    def test_privacy_unlink_preserves_separate_emergency_contact(self):
        state = {
            "users": {
                "U-owner": {
                    "contacts": [
                        {
                            "line_user_id": "U-peer",
                            "contact_role": "guardian",
                            "binding_status": "accepted",
                        },
                        {
                            "line_user_id": "U-peer",
                            "contact_role": "emergency",
                            "phone": "0912345678",
                        },
                    ]
                },
                "U-peer": {
                    "contacts": [{
                        "line_user_id": "U-owner",
                        "contact_role": "guardian",
                    }]
                },
            }
        }
        app_module.process_verified_privacy_request(
            state,
            "U-owner",
            "unlink_guardian",
            peer_line_user_id="U-peer",
            now=self.now,
        )
        self.assertEqual(len(state["users"]["U-owner"]["contacts"]), 1)
        self.assertEqual(
            state["users"]["U-owner"]["contacts"][0]["contact_role"],
            "emergency",
        )

    def test_privacy_delete_clears_graph_but_retains_anonymized_order(self):
        state = {
            "users": {
                "U-owner": {"line_user_id": "U-owner", "location": {"active": True}},
                "U-peer": {
                    "line_user_id": "U-peer",
                    "friends": ["U-owner"],
                    "guarding_for": ["U-owner"],
                    "contacts": [{"line_user_id": "U-owner"}],
                },
            },
            "guardian_groups": {
                "C-owned": {"owner_line_user_id": "U-owner"},
                "C-other": {
                    "owner_line_user_id": "U-peer",
                    "member_line_user_ids": ["U-owner", "U-peer"],
                },
            },
            "guardian_invites": [{"inviter_line_user_id": "U-owner"}],
            "location_grants": {"U-owner": {"line_user_id": "U-owner"}},
            "sos_events": {
                "S-1": {
                    "owner_line_user_id": "U-owner",
                    "deliveries": [{"target": "U-owner"}],
                }
            },
            "line_message_usage": [{
                "owner_line_user_id": "U-owner",
                "recipient_line_user_id": "U-owner",
            }],
            "beta_audit": [{"line_user_id": "U-owner"}],
            "account_migration_aliases": {
                "U-owner": {"target_line_user_id": "U-peer"}
            },
            "orders": [{
                "order_id": "O-1",
                "line_user_id": "U-owner",
                "display_name": "王小明",
            }],
        }
        first = app_module.process_verified_privacy_request(
            state, "U-owner", "delete_account", now=self.now
        )
        second = app_module.process_verified_privacy_request(
            state, "U-owner", "delete_account", now=self.now
        )

        self.assertTrue(first["processed"])
        self.assertTrue(second["idempotent"])
        self.assertNotIn("U-owner", state["users"])
        self.assertNotIn("C-owned", state["guardian_groups"])
        self.assertEqual(
            state["guardian_groups"]["C-other"]["member_line_user_ids"],
            ["U-peer"],
        )
        self.assertEqual(state["guardian_invites"], [])
        self.assertEqual(state["location_grants"], {})
        self.assertEqual(state["sos_events"], {})
        self.assertEqual(state["line_message_usage"], [])
        self.assertEqual(state["beta_audit"], [])
        self.assertEqual(state["account_migration_aliases"], {})
        self.assertEqual(state["orders"][0]["line_user_id"], "deleted-user")
        self.assertEqual(state["orders"][0]["display_name"], "已刪除會員")

    def test_trial_milestones_send_once_on_days_7_12_and_14(self):
        with TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "data.json"
            started = self.now - timedelta(days=14)
            app_module.save_state(data_file, {
                "users": {
                    "U-owner": {
                        "line_user_id": "U-owner",
                        "plan": "trial",
                        "trial_started_at": started.isoformat(timespec="seconds"),
                        "trial_end": self.now.isoformat(timespec="seconds"),
                    }
                }
            })
            sent = []
            config = {
                "DATA_FILE": data_file,
                "LINE_CHANNEL_ACCESS_TOKEN": "token",
                "LINE_PUSH_SENDER": lambda token, target, message: sent.append(
                    (target, message)
                ),
            }

            first, first_code = app_module.send_trial_milestone_notices(
                config, now=self.now
            )
            second, second_code = app_module.send_trial_milestone_notices(
                config, now=self.now
            )

            self.assertEqual((first_code, second_code), (200, 200))
            self.assertEqual(first["sent"], 3)
            self.assertEqual(second["sent"], 0)
            self.assertEqual(len(sent), 3)
            saved = app_module.load_state(data_file)["users"]["U-owner"]
            self.assertEqual(saved["trial_notice_days_sent"], [7, 12, 14])
            self.assertNotIn("trial_milestone_notices_sent", saved)

    def test_trial_milestones_skip_non_trial_and_not_yet_due(self):
        with TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "data.json"
            app_module.save_state(data_file, {
                "users": {
                    "U-trial": {
                        "line_user_id": "U-trial",
                        "plan": "trial",
                        "trial_started_at": (
                            self.now - timedelta(days=6)
                        ).isoformat(timespec="seconds"),
                    },
                    "U-paid": {
                        "line_user_id": "U-paid",
                        "plan": "paid_399",
                        "trial_started_at": (
                            self.now - timedelta(days=14)
                        ).isoformat(timespec="seconds"),
                    },
                }
            })
            sent = []
            result, code = app_module.send_trial_milestone_notices({
                "DATA_FILE": data_file,
                "LINE_CHANNEL_ACCESS_TOKEN": "token",
                "LINE_PUSH_SENDER": lambda *args: sent.append(args),
            }, now=self.now)

            self.assertEqual(code, 200)
            self.assertEqual(result["sent"], 0)
            self.assertEqual(sent, [])

    def test_parallel_trial_milestone_ticks_claim_each_node_once(self):
        with TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "data.json"
            app_module.save_state(data_file, {
                "users": {
                    "U-owner": {
                        "line_user_id": "U-owner",
                        "plan": "trial",
                        "trial_started_at": (
                            self.now - timedelta(days=7)
                        ).isoformat(timespec="seconds"),
                        "display_name": "並發後仍保留",
                    }
                }
            })
            sent = []
            config = {
                "DATA_FILE": data_file,
                "LINE_CHANNEL_ACCESS_TOKEN": "token",
                "LINE_PUSH_SENDER": lambda *args: sent.append(args),
            }
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(
                    lambda _index: app_module.send_trial_milestone_notices(
                        config, now=self.now
                    )[0]["sent"],
                    range(2),
                ))

            self.assertEqual(sum(results), 1)
            self.assertEqual(len(sent), 1)
            saved = app_module.load_state(data_file)["users"]["U-owner"]
            self.assertEqual(saved["trial_notice_days_sent"], [7])
            self.assertEqual(saved["display_name"], "並發後仍保留")

    def test_cron_sends_day_14_once_before_lapsing_expired_trial(self):
        with TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "data.json"
            clock = datetime.fromisoformat("2026-07-27T09:45:00")
            app_module.save_state(data_file, {
                "users": {
                    "U-owner": {
                        "line_user_id": "U-owner",
                        "plan": "trial",
                        "trial_started_at": "2026-07-13T08:00:00",
                        "trial_end": "2026-07-27T08:00:00",
                        "daily_checkin_reminder_enabled": False,
                    }
                }
            })
            sent = []
            config = {
                "DATA_FILE": data_file,
                "CRON_NOW": clock,
                "LINE_CHANNEL_ACCESS_TOKEN": "token",
                "LINE_PUSH_SENDER": lambda *args: sent.append(args),
            }

            with mock.patch.object(
                app_module,
                "refresh_all_guardian_groups_count",
                return_value={"updated": 0, "failed": 0},
            ):
                first, first_code = app_module.run_cron_tick(config)
                second, second_code = app_module.run_cron_tick(config)

            self.assertEqual((first_code, second_code), (200, 200))
            self.assertEqual(
                first["tasks"]["trial_milestone_notices"]["result"]["sent"],
                3,
            )
            self.assertEqual(
                second["tasks"]["trial_milestone_notices"]["result"]["sent"],
                0,
            )
            self.assertEqual(len(sent), 3)
            saved = app_module.load_state(data_file)["users"]["U-owner"]
            self.assertEqual(saved["plan"], "free")
            self.assertTrue(saved["membership_paused"])
            self.assertEqual(saved["trial_notice_days_sent"], [7, 12, 14])


if __name__ == "__main__":
    unittest.main()
