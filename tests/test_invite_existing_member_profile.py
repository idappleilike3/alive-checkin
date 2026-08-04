import tempfile
import unittest
from pathlib import Path

import app


class InviteExistingMemberProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_file = str(Path(self.tmp.name) / "state.json")

    def _save_members(self, *, already_bound=False):
        state = app.load_state(self.data_file)
        inviter = app.get_profile(state, "U-inviter")
        inviter["display_name"] = "Jennie"
        invitee = app.get_profile(state, "U-invitee")
        invitee.update({
            "display_name": "珮淩",
            "onboarding_reminder_configured": True,
            "profile_completed_at": "2026-08-04T08:00:00",
        })
        previous_owner = app.get_profile(state, "U-previous-owner")
        previous_owner["contacts"] = [{
            "line_user_id": "U-invitee",
            "line_id": "U-invitee",
            "name": "珮淩",
            "phone": "0912345678",
            "relationship": "家人",
            "binding_status": "accepted",
            "recipient_consent": True,
        }]
        if already_bound:
            inviter["contacts"] = [{
                "line_user_id": "U-invitee",
                "line_id": "U-invitee",
                "name": "珮淩",
                "phone": "0912345678",
                "relationship": "姐姐",
                "binding_status": "accepted",
                "recipient_consent": True,
            }]
        app.save_state(self.data_file, state)

    def test_preview_returns_authoritative_saved_invitee_profile(self):
        self._save_members()
        preview, code = app.invite_bind_preview(self.data_file, {
            "invite_from": "U-inviter",
            "line_user_id": "U-invitee",
        })
        self.assertEqual(code, 200)
        self.assertEqual(preview["invitee_profile"]["display_name"], "珮淩")
        self.assertEqual(preview["invitee_profile"]["phone"], "0912345678")
        self.assertTrue(preview["invitee_profile"]["profile_completed"])
        self.assertFalse(preview["binding_completed"])

    def test_preview_reports_existing_completed_binding(self):
        self._save_members(already_bound=True)
        preview, code = app.invite_bind_preview(self.data_file, {
            "invite_from": "U-inviter",
            "line_user_id": "U-invitee",
        })
        self.assertEqual(code, 200)
        self.assertTrue(preview["binding_completed"])
        self.assertEqual(preview["existing_relationship"], "姐姐")


if __name__ == "__main__":
    unittest.main()
