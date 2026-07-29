import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import app


class InviteePlanFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_file = str(Path(self.tmp.name) / "state.json")
        self.now = datetime(2026, 7, 29, 18, 0)
        inviter = {
            **app.DEFAULT_PROFILE,
            "line_user_id": "U-beta-799",
            "display_name": "封測會員",
            "plan": "paid_799",
            "membership_source": "beta",
            "payment_status": "beta",
            "beta_cohort": "B799",
            "beta_started_at": self.now.isoformat(timespec="seconds"),
            "beta_ends_at": (self.now + timedelta(days=21)).isoformat(
                timespec="seconds"
            ),
            "free_eligibility_source": "beta_B799",
        }
        app.save_state(self.data_file, {"users": {"U-beta-799": inviter}})

    def test_pending_invite_does_not_complete_beta_onboarding(self):
        invite, code = app.create_guardian_invite(
            self.data_file,
            "U-beta-799",
            {"display_name": "女兒", "relationship": "女兒"},
            now=self.now,
        )
        self.assertEqual(code, 201)

        state = app.load_state(self.data_file)
        status = app.build_status(
            state["users"]["U-beta-799"], state, now=self.now
        )
        self.assertEqual(status["plan"], "paid_799")
        self.assertTrue(status["guardian_required"])
        self.assertEqual(status["pending_guardian_invite_count"], 1)

        incomplete, incomplete_code = app.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-beta-799",
                "contact_line_user_id": "U-daughter",
                "invite_token": invite["invite_token"],
                "recipient_consent": True,
                "activate_trial": False,
            },
        )
        self.assertEqual(incomplete_code, 400)
        self.assertEqual(incomplete["code"], "guardian_profile_required")

        complete, complete_code = app.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-beta-799",
                "contact_line_user_id": "U-daughter",
                "invite_token": invite["invite_token"],
                "recipient_consent": True,
                "activate_trial": False,
                "contact_display_name": "女兒",
                "contact_relationship": "女兒",
                "contact_phone": "0912345678",
            },
        )
        self.assertEqual(complete_code, 200)
        self.assertTrue(complete["binding_complete"])

        state = app.load_state(self.data_file)
        inviter = state["users"]["U-beta-799"]
        self.assertEqual(inviter["plan"], "paid_799")
        self.assertEqual(inviter["membership_source"], "beta")
        status = app.build_status(inviter, state, now=self.now)
        self.assertFalse(status["guardian_required"])
        self.assertEqual(status["pending_guardian_invite_count"], 0)

    def test_new_invitee_gets_own_trial_without_changing_inviter_plan(self):
        invite, _ = app.create_guardian_invite(
            self.data_file,
            "U-beta-799",
            {"display_name": "女兒", "relationship": "女兒"},
            now=self.now,
        )
        app.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-beta-799",
                "contact_line_user_id": "U-daughter",
                "invite_token": invite["invite_token"],
                "recipient_consent": True,
                "activate_trial": False,
                "contact_display_name": "女兒",
                "contact_relationship": "女兒",
                "contact_phone": "0912345678",
            },
        )

        invitee_status, code = app.register_line_user(
            self.data_file,
            {
                "line_user_id": "U-daughter",
                "display_name": "女兒",
                "activate_own_trial": True,
            },
        )
        self.assertEqual(code, 200)
        self.assertTrue(invitee_status["own_trial_activated"])
        self.assertEqual(invitee_status["plan"], "trial")
        self.assertEqual(invitee_status["membership_source"], "public_trial")
        inviter = app.load_state(self.data_file)["users"]["U-beta-799"]
        self.assertEqual(inviter["plan"], "paid_799")
        self.assertEqual(inviter["membership_source"], "beta")

    def test_paid_and_beta_invitees_never_get_downgraded_to_trial(self):
        state = app.load_state(self.data_file)
        state["users"]["U-paid"] = {
            **app.DEFAULT_PROFILE,
            "line_user_id": "U-paid",
            "plan": "paid_799",
            "membership_source": "paid",
            "payment_status": "active",
            "paid_until": (self.now + timedelta(days=365)).isoformat(
                timespec="seconds"
            ),
        }
        app.save_state(self.data_file, state)

        paid, paid_code = app.register_line_user(
            self.data_file,
            {"line_user_id": "U-paid", "activate_own_trial": True},
        )
        beta, beta_code = app.register_line_user(
            self.data_file,
            {"line_user_id": "U-beta-799", "activate_own_trial": True},
        )

        self.assertEqual(paid_code, 200)
        self.assertEqual(beta_code, 200)
        self.assertEqual(paid["plan"], "paid_799")
        self.assertEqual(paid["membership_source"], "paid")
        self.assertFalse(paid["own_trial_activated"])
        self.assertEqual(beta["plan"], "paid_799")
        self.assertEqual(beta["membership_source"], "beta")
        self.assertFalse(beta["own_trial_activated"])


if __name__ == "__main__":
    unittest.main()
