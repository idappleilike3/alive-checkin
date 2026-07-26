"""One-time membership trial policy."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import app as app_module


class MembershipTrialPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_file = str(Path(self.tmp.name) / "state.json")
        self.now = datetime(2026, 7, 26, 10, 0, 0)

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_member_receives_exactly_fourteen_days_once(self):
        profile = {"plan": "trial", "trial_bonus_days": 21}

        granted = app_module.ensure_membership_trial(profile, now=self.now)

        self.assertTrue(granted)
        self.assertEqual(profile["plan"], "trial")
        self.assertEqual(profile["membership_source"], "public_trial")
        self.assertEqual(profile["trial_started_at"], "2026-07-26T10:00:00")
        self.assertEqual(profile["trial_end"], "2026-08-09T10:00:00")
        self.assertEqual(app_module.trial_bonus_days(profile), 0)
        self.assertTrue(app_module.membership_access_active(profile, now=self.now))
        self.assertFalse(
            app_module.membership_access_active(
                profile, now=self.now + timedelta(days=14, seconds=1)
            )
        )

        first_end = profile["trial_end"]
        self.assertFalse(
            app_module.ensure_membership_trial(
                profile, now=self.now + timedelta(days=5)
            )
        )
        self.assertEqual(profile["trial_end"], first_end)

    def test_reregister_does_not_restart_public_trial(self):
        first, code = app_module.register_line_user(
            self.data_file, {"line_user_id": "U-once", "display_name": "小美"}
        )
        self.assertEqual(code, 200)
        first_started = first["trial_started_at"]
        first_end = first["trial_end"]

        second, code = app_module.register_line_user(
            self.data_file, {"line_user_id": "U-once", "display_name": "小美"}
        )

        self.assertEqual(code, 200)
        self.assertTrue(second["existing_user"])
        self.assertEqual(second["trial_started_at"], first_started)
        self.assertEqual(second["trial_end"], first_end)
        self.assertEqual(second["trial_total_days"], 14)

    def test_existing_free_member_receives_one_transition_trial(self):
        state = app_module.load_state(self.data_file)
        profile = app_module.get_profile(state, "U-free")
        profile["plan"] = "free"
        profile["payment_status"] = "expired"
        profile.pop("trial_policy_version", None)
        profile.pop("trial_end", None)
        app_module.save_state(self.data_file, state)

        first, code = app_module.register_line_user(
            self.data_file, {"line_user_id": "U-free", "display_name": "舊會員"}
        )

        self.assertEqual(code, 200)
        self.assertEqual(first["plan"], "trial")
        self.assertEqual(first["membership_source"], "transition_trial")
        self.assertTrue(first["trial_end"])
        first_end = first["trial_end"]

        second, code = app_module.register_line_user(
            self.data_file, {"line_user_id": "U-free", "display_name": "舊會員"}
        )
        self.assertEqual(code, 200)
        self.assertEqual(second["trial_end"], first_end)
        self.assertEqual(second["membership_source"], "transition_trial")

    def test_transition_trial_clears_expired_retention_before_cleanup(self):
        state = app_module.load_state(self.data_file)
        profile = app_module.get_profile(state, "U-retained")
        profile.update(
            {
                "plan": "free",
                "payment_status": "expired",
                "membership_source": "expired",
                "contacts": [
                    {
                        "id": "core-1",
                        "line_user_id": "U-core",
                        "line_id": "U-core",
                        "name": "核心守護人",
                        "binding_status": "accepted",
                        "consent_status": "accepted",
                        "is_primary": True,
                    }
                ],
                "plan_expired_at": "2026-06-01T00:00:00",
                "contacts_retain_until": "2026-07-01T00:00:00",
            }
        )
        profile.pop("trial_policy_version", None)

        granted = app_module.ensure_membership_trial(
            profile, now=self.now, source="transition_trial"
        )

        self.assertTrue(granted)
        self.assertEqual(profile["plan_expired_at"], "")
        self.assertEqual(profile["contacts_retain_until"], "")
        app_module.save_state(self.data_file, state)

        result, code = app_module.cleanup_expired_data(
            {
                "DATA_FILE": self.data_file,
                "CRON_NOW": self.now + timedelta(days=1),
            }
        )
        self.assertEqual(code, 200)
        self.assertEqual(result["contacts_archived_users"], 0)
        saved = app_module.load_state(self.data_file)["users"]["U-retained"]
        self.assertEqual(len(saved["contacts"]), 1)
        self.assertEqual(saved["contacts"][0]["line_user_id"], "U-core")

    def test_free_member_migration_is_batch_idempotent_and_uses_one_clock(self):
        state = app_module.load_state(self.data_file)
        for user_id in ("U-free-1", "U-free-2"):
            profile = app_module.get_profile(state, user_id)
            profile["plan"] = "free"
            profile["payment_status"] = "expired"
            profile["membership_source"] = "expired"
            profile.pop("trial_policy_version", None)
            profile.pop("trial_end", None)
        paid = app_module.get_profile(state, "U-paid")
        paid["plan"] = "paid_399"
        paid["payment_status"] = "active"
        paid["paid_until"] = (self.now + timedelta(days=30)).isoformat(
            timespec="seconds"
        )
        paid["membership_source"] = ""
        paid.pop("trial_policy_version", None)
        app_module.save_state(self.data_file, state)

        first, code = app_module.migrate_existing_free_members(
            {"DATA_FILE": self.data_file, "CRON_NOW": self.now}
        )

        self.assertEqual(code, 200)
        self.assertEqual(first["migrated"], 2)
        saved = app_module.load_state(self.data_file)["users"]
        starts = {saved[user_id]["trial_started_at"] for user_id in ("U-free-1", "U-free-2")}
        ends = {saved[user_id]["trial_end"] for user_id in ("U-free-1", "U-free-2")}
        self.assertEqual(starts, {"2026-07-26T10:00:00"})
        self.assertEqual(ends, {"2026-08-09T10:00:00"})
        for user_id in ("U-free-1", "U-free-2"):
            self.assertEqual(saved[user_id]["membership_source"], "transition_trial")
            self.assertEqual(saved[user_id]["trial_notice_days_sent"], [])
        self.assertEqual(saved["U-paid"]["membership_source"], "paid")
        self.assertEqual(
            saved["U-paid"]["trial_policy_version"],
            app_module.TRIAL_POLICY_VERSION,
        )

        second, code = app_module.migrate_existing_free_members(
            {
                "DATA_FILE": self.data_file,
                "CRON_NOW": self.now + timedelta(days=3),
            }
        )
        self.assertEqual(code, 200)
        self.assertEqual(second["migrated"], 0)
        saved_again = app_module.load_state(self.data_file)["users"]
        self.assertEqual(saved_again["U-free-1"]["trial_started_at"], "2026-07-26T10:00:00")
        self.assertEqual(saved_again["U-free-1"]["trial_end"], "2026-08-09T10:00:00")

        saved_again["U-paid"]["paid_until"] = (
            self.now - timedelta(seconds=1)
        ).isoformat(timespec="seconds")
        app_module.save_state(self.data_file, {"users": saved_again})
        app_module.apply_expired_plan_downgrades(
            {"DATA_FILE": self.data_file, "CRON_NOW": self.now}
        )
        third, code = app_module.migrate_existing_free_members(
            {
                "DATA_FILE": self.data_file,
                "CRON_NOW": self.now + timedelta(days=4),
            }
        )
        self.assertEqual(code, 200)
        self.assertEqual(third["migrated"], 0)
        expired_paid = app_module.load_state(self.data_file)["users"]["U-paid"]
        self.assertEqual(expired_paid["plan"], "free")
        self.assertEqual(expired_paid["membership_source"], "expired")

    def test_membership_source_tracks_paid_and_expired_lifecycle(self):
        self.assertEqual(app_module.DEFAULT_PROFILE["membership_source"], "")
        app_module.register_line_user(
            self.data_file, {"line_user_id": "U-pay", "display_name": "付款會員"}
        )
        created, code = app_module.create_payment_order(
            self.data_file, {"line_user_id": "U-pay", "plan": "paid_199"}
        )
        self.assertEqual(code, 201)
        confirmed, code = app_module.confirm_payment_order(
            self.data_file,
            {
                "order_id": created["order"]["order_id"],
                "transaction_id": "TX-001",
            },
            config={"CRON_NOW": self.now},
        )
        self.assertEqual(code, 200)
        self.assertEqual(confirmed["member"]["membership_source"], "paid")

        state = app_module.load_state(self.data_file)
        profile = state["users"]["U-pay"]
        profile["paid_until"] = (self.now - timedelta(seconds=1)).isoformat(
            timespec="seconds"
        )
        app_module.save_state(self.data_file, state)
        result, code = app_module.apply_expired_plan_downgrades(
            {"DATA_FILE": self.data_file, "CRON_NOW": self.now}
        )
        self.assertEqual(code, 200)
        self.assertEqual(result["downgraded"], 1)
        expired = app_module.load_state(self.data_file)["users"]["U-pay"]
        self.assertEqual(expired["membership_source"], "expired")

    def test_guardian_invitations_never_add_trial_days(self):
        app_module.register_line_user(
            self.data_file, {"line_user_id": "U-owner", "display_name": "本人"}
        )
        state = app_module.load_state(self.data_file)
        state["users"]["U-owner"]["plan"] = "paid_399"
        state["users"]["U-owner"]["payment_status"] = "active"
        state["users"]["U-owner"]["paid_until"] = (
            self.now + timedelta(days=30)
        ).isoformat(timespec="seconds")
        app_module.save_state(self.data_file, state)

        for guardian_id in ("U-g1", "U-g2"):
            result, code = app_module.bind_emergency_contact(
                self.data_file,
                {
                    "inviter_line_user_id": "U-owner",
                    "contact_line_user_id": guardian_id,
                    "contact_display_name": guardian_id,
                },
                config={},
            )
            self.assertEqual(code, 200)
            self.assertFalse(result["invite_reward_applied"])
            self.assertEqual(result["trial_bonus_days"], 0)

        state = app_module.load_state(self.data_file)
        self.assertEqual(app_module.trial_bonus_days(state["users"]["U-owner"]), 0)


if __name__ == "__main__":
    unittest.main()
