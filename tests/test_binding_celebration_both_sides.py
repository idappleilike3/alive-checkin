import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import app


class BindingCelebrationBothSidesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_file = str(Path(self.tmp.name) / "state.json")
        now = datetime(2026, 8, 4, 10, 0)
        inviter = {
            **app.DEFAULT_PROFILE,
            "line_user_id": "U-owner",
            "display_name": "媽媽",
            "plan": "paid_399",
            "membership_source": "beta",
            "payment_status": "beta",
            "beta_cohort": "B399",
            "beta_started_at": now.isoformat(timespec="seconds"),
            "beta_ends_at": (now + timedelta(days=21)).isoformat(timespec="seconds"),
            "onboarding_reminder_configured": True,
        }
        app.save_state(self.data_file, {"users": {"U-owner": inviter}})

    def _bind(self):
        invite, code = app.create_guardian_invite(
            self.data_file,
            "U-owner",
            {"display_name": "女兒", "relationship": "女兒"},
        )
        self.assertEqual(code, 201)
        result, code = app.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-owner",
                "contact_line_user_id": "U-guardian",
                "invite_token": invite["invite_token"],
                "recipient_consent": True,
                "activate_trial": False,
                "contact_display_name": "女兒",
                "contact_relationship": "女兒",
                "contact_phone": "0912345678",
            },
        )
        self.assertEqual(code, 200)
        self.assertTrue(result["binding_complete"])

    def test_new_binding_queues_one_celebration_for_both_people(self):
        self._bind()

        owner, owner_code = app.onboarding_status_payload(self.data_file, "U-owner")
        guardian, guardian_code = app.onboarding_status_payload(self.data_file, "U-guardian")

        self.assertEqual(owner_code, 200)
        self.assertEqual(guardian_code, 200)
        self.assertTrue(owner["show_binding_celebration"])
        self.assertTrue(guardian["show_binding_celebration"])
        self.assertEqual(owner["binding_celebration"]["peer_display_name"], "女兒")
        self.assertEqual(guardian["binding_celebration"]["peer_display_name"], "媽媽")

    def test_ack_can_save_optional_birthday_and_never_shows_event_again(self):
        self._bind()
        status, _ = app.onboarding_status_payload(self.data_file, "U-guardian")
        event_id = status["binding_celebration"]["event_id"]

        ack, code = app.acknowledge_binding_celebration(
            self.data_file,
            "U-guardian",
            {"event_id": event_id, "birthday": "1988-06-09"},
        )
        after, _ = app.onboarding_status_payload(self.data_file, "U-guardian")

        self.assertEqual(code, 200)
        self.assertEqual(ack["birthday"], "1988-06-09")
        self.assertFalse(after["show_binding_celebration"])
        self.assertEqual(after["birthday"], "1988-06-09")


if __name__ == "__main__":
    unittest.main()
