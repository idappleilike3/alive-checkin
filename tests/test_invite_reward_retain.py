"""No invite trial extension + 30-day contacts retain after entitlement lapse."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import app as app_module


class InviteRewardRetainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_file = str(Path(self.tmp.name) / "state.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_guardian_bind_does_not_extend_trial(self):
        app_module.register_line_user(
            self.data_file, {"line_user_id": "U-inv", "display_name": "邀請人"}
        )
        state = app_module.load_state(self.data_file)
        inv = state["users"]["U-inv"]
        inv["trial_started_at"] = (datetime.now() - timedelta(days=3)).isoformat(timespec="seconds")
        inv["trial_bonus_days"] = 0
        app_module.save_state(self.data_file, state)

        before = app_module.trial_days_left(inv)
        result, code = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-inv",
                "contact_line_user_id": "U-g1",
                "contact_display_name": "阿媽",
            },
            config={},
        )
        self.assertEqual(code, 200)
        self.assertFalse(result.get("invite_reward_applied"))
        self.assertEqual(result.get("trial_bonus_days"), 0)
        self.assertEqual(result.get("trial_days_left"), before)

        state = app_module.load_state(self.data_file)
        inv2 = state["users"]["U-inv"]
        self.assertEqual(app_module.trial_bonus_days(inv2), 0)
        reward = state["contact_rewards"][0]
        self.assertEqual(reward.get("status"), "not_applicable")
        self.assertEqual(reward.get("reward_days"), 0)

        # Same guardian rebinding must not double-count
        result2, code2 = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-inv",
                "contact_line_user_id": "U-g1",
                "contact_display_name": "阿媽",
            },
            config={},
        )
        self.assertEqual(code2, 200)
        self.assertFalse(result2.get("invite_reward_applied"))
        state = app_module.load_state(self.data_file)
        self.assertEqual(app_module.trial_bonus_days(state["users"]["U-inv"]), 0)

    def test_second_unique_guardian_also_does_not_extend_trial(self):
        app_module.register_line_user(
            self.data_file, {"line_user_id": "U-inv2", "display_name": "邀請人"}
        )
        state = app_module.load_state(self.data_file)
        state["users"]["U-inv2"]["plan"] = "paid_199"
        state["users"]["U-inv2"]["payment_status"] = "active"
        state["users"]["U-inv2"]["paid_until"] = (
            datetime.now() + timedelta(days=20)
        ).isoformat(timespec="seconds")
        app_module.save_state(self.data_file, state)

        app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-inv2",
                "contact_line_user_id": "U-a",
                "contact_display_name": "A",
            },
            config={},
        )
        app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-inv2",
                "contact_line_user_id": "U-b",
                "contact_display_name": "B",
            },
            config={},
        )
        state = app_module.load_state(self.data_file)
        self.assertEqual(app_module.trial_bonus_days(state["users"]["U-inv2"]), 0)

    def test_trial_expiry_keeps_contacts_until_verified_request(self):
        app_module.register_line_user(
            self.data_file, {"line_user_id": "U-old", "display_name": "過期用戶"}
        )
        app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-old",
                "contact_line_user_id": "U-keep",
                "contact_display_name": "要保留",
            },
            config={},
        )
        state = app_module.load_state(self.data_file)
        profile = state["users"]["U-old"]
        profile["plan"] = "trial"
        profile["trial_started_at"] = (datetime.now() - timedelta(days=40)).isoformat(
            timespec="seconds"
        )
        profile["trial_end"] = (datetime.now() - timedelta(days=26)).isoformat(
            timespec="seconds"
        )
        profile["trial_bonus_days"] = 0
        app_module.save_state(self.data_file, state)

        result, code = app_module.apply_expired_plan_downgrades({"DATA_FILE": self.data_file})
        self.assertEqual(code, 200)
        self.assertGreaterEqual(result["downgraded"], 1)

        state = app_module.load_state(self.data_file)
        profile = state["users"]["U-old"]
        self.assertEqual(profile.get("plan"), "free")
        self.assertEqual(profile.get("payment_status"), "expired")
        self.assertEqual(profile.get("contacts_retain_until"), "")
        self.assertTrue(profile.get("membership_paused"))
        self.assertEqual(len(profile.get("contacts") or []), 1)

        # Even a stale legacy retain date must not auto-delete relationships.
        profile["contacts_retain_until"] = (datetime.now() - timedelta(days=1)).isoformat(
            timespec="seconds"
        )
        app_module.save_state(self.data_file, state)
        cleaned, code2 = app_module.cleanup_expired_data({"DATA_FILE": self.data_file})
        self.assertEqual(code2, 200)
        self.assertEqual(cleaned.get("contacts_archived_users", 0), 0)
        state = app_module.load_state(self.data_file)
        profile = state["users"]["U-old"]
        self.assertEqual(len(profile.get("contacts") or []), 1)
        self.assertEqual(profile.get("contacts_archived") or [], [])

    def test_ui_copy_does_not_sell_cancelled_invite_bonus(self):
        page = Path(__file__).resolve().parents[1].joinpath("index.html").read_text(encoding="utf-8")
        self.assertNotIn("每成功邀請 1 位守護人", page)
        self.assertIn("memberInviteMoreGuardianBtn", page)
        self.assertIn("inviteMoreGuardiansFromMember", page)


if __name__ == "__main__":
    unittest.main()
