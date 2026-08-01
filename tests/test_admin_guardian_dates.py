import tempfile
import unittest
from pathlib import Path

import app as alive_app

ROOT = Path(__file__).resolve().parents[1]


class AdminGuardianDatesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_file = str(Path(self.tmp.name) / "state.json")
        alive_app.save_state(self.data_file, {"users": {}})

    def test_verified_binding_persists_invited_and_reviewed_dates(self):
        state = alive_app.load_state(self.data_file)
        alive_app.get_profile(state, "U-owner")["display_name"] = "寶寶"
        alive_app.save_state(self.data_file, state)
        invite, code = alive_app.create_guardian_invite(
            self.data_file, "U-owner", {"display_name": "Jennie", "relationship": "家人"}
        )
        self.assertEqual(code, 201)
        result, bind_code = alive_app.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-owner",
                "contact_line_user_id": "U-jennie",
                "contact_display_name": "Jennie",
                "contact_relationship": "家人",
                "invite_token": invite["invite_token"],
                "recipient_consent": True,
            },
            config={},
        )
        self.assertEqual(bind_code, 200, result)
        state = alive_app.load_state(self.data_file)
        contact = state["users"]["U-owner"]["contacts"][0]
        reward = state["contact_rewards"][0]
        accepted_invite = state["guardian_invites"][0]
        self.assertEqual(contact["accepted_invite_id"], accepted_invite["id"])
        self.assertEqual(reward["invited_at"], accepted_invite["created_at"])
        self.assertEqual(reward["accepted_at"], accepted_invite["accepted_at"])

        summary = alive_app.admin_summary(self.data_file)
        edge = summary["invite_edges"][0]
        self.assertEqual(edge["invited_at"], accepted_invite["created_at"])
        self.assertEqual(edge["accepted_at"], accepted_invite["accepted_at"])
        self.assertEqual(summary["contact_rewards"][0]["invited_at"], accepted_invite["created_at"])

    def test_legacy_edge_without_unambiguous_invite_is_labelled(self):
        state = alive_app.load_state(self.data_file)
        owner = alive_app.get_profile(state, "U-old")
        owner["display_name"] = "舊會員"
        owner["contacts"] = [{
            "name": "舊守護人", "line_user_id": "U-old-guardian", "line_id": "U-old-guardian",
            "binding_status": "accepted", "consent_status": "accepted", "contact_role": "guardian",
            "is_primary": True,
        }]
        alive_app.save_state(self.data_file, state)
        summary = alive_app.admin_summary(self.data_file)
        edge = next(row for row in summary["invite_edges"] if row["inviter_line_user_id"] == "U-old")
        self.assertEqual(edge["invited_at"], "舊資料未記錄")
        self.assertEqual(edge["accepted_at"], "舊資料未記錄")

    def test_admin_guardian_operations_renders_both_dates(self):
        page = (ROOT / "admin.html").read_text(encoding="utf-8")
        self.assertIn("邀請日期：${edge.invited_at", page)
        self.assertIn("審核日期：${edge.accepted_at", page)
        self.assertIn("邀請日期：${reward.invited_at", page)
        self.assertIn("審核日期：${reward.accepted_at", page)


if __name__ == "__main__":
    unittest.main()
