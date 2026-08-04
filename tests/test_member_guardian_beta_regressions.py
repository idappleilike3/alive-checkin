import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import app


ROOT = Path(__file__).resolve().parents[1]


class MemberGuardianBetaRegressionTests(unittest.TestCase):
    def test_unbound_member_can_still_edit_contacts_and_emergency_contacts(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        start = page.index("function requireMemberActionReady")
        body = page[start : start + 1100]
        self.assertIn('scope === "guardian_service"', body)
        self.assertNotIn('if (memberBootstrapState.guardianRequired)', body)
        self.assertIn("setOnboardingCloseVisible(Boolean(lineUserId))", page)
        self.assertIn("完成資料與提醒設定後才開始 21 天", page)

    def test_beta_link_reserves_cohort_without_starting_21_day_clock(self):
        state = {"users": {"U-beta": {"line_user_id": "U-beta", "plan": "trial"}}}
        now = datetime(2026, 8, 4, 10, 0, 0)

        result = app.claim_beta_link(state, "U-beta", "B799", now=now)

        profile = state["users"]["U-beta"]
        self.assertEqual(result["cohort"], "B799")
        self.assertTrue(profile["beta_activation_pending"])
        self.assertNotIn("beta_started_at", profile)
        self.assertNotIn("beta_ends_at", profile)

    def test_saving_profile_and_reminder_starts_reserved_beta_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_file = Path(tmp) / "state.json"
            state = {"users": {"U-beta": {"line_user_id": "U-beta", "plan": "trial"}}}
            app.claim_beta_link(state, "U-beta", "B399", now=datetime(2026, 8, 4, 9, 0, 0))
            app.save_state(str(data_file), state)

            result, code = app.update_onboarding_reminder(
                str(data_file), "U-beta", {"reminder_time": "12:00"}
            )

            saved = app.load_state(str(data_file))["users"]["U-beta"]
            self.assertEqual(code, 200)
            self.assertTrue(result["beta_activated"])
            self.assertFalse(saved["beta_activation_pending"])
            self.assertTrue(saved["beta_started_at"])
            self.assertTrue(saved["beta_ends_at"])

    def test_accepted_invite_repairs_both_admin_relationship_indexes(self):
        owner = {"line_user_id": "U-owner", "display_name": "Jennie", "contacts": []}
        guardian = {"line_user_id": "U-guardian", "display_name": "好友", "guarding_for": []}
        state = {
            "users": {"U-owner": owner, "U-guardian": guardian},
            "guardian_invites": [{
                "id": "invite-1",
                "inviter_line_user_id": "U-owner",
                "invitee_line_user_id": "U-guardian",
                "invitee_display_name": "好友",
                "status": "accepted",
                "accepted_at": "2026-08-04T09:30:00",
            }],
        }

        self.assertTrue(app.repair_accepted_guardian_invites(state, owner))

        self.assertEqual(owner["contacts"][0]["line_user_id"], "U-guardian")
        self.assertIn("U-owner", guardian["guarding_for"])
        self.assertEqual(guardian["guarding_details"][0]["line_user_id"], "U-owner")

    def test_unbound_beta_member_can_update_guardian_phone_and_add_emergency_contact(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_file = str(Path(tmp) / "state.json")
            profile = {
                "line_user_id": "U-owner",
                "plan": "paid_399_year",
                "membership_source": "beta",
                "beta_cohort": "B399",
                "contacts": [{
                    "id": "contact-1",
                    "name": "家人",
                    "relationship": "姊姊",
                    "phone": "0911000000",
                    "contact_role": "guardian",
                    "binding_status": "unbound",
                }],
            }
            app.save_state(data_file, {"users": {"U-owner": profile}})

            updated, update_code = app.update_single_contact(
                data_file,
                "U-owner",
                "contact-1",
                {
                    "name": "家人",
                    "relationship": "姊姊",
                    "phone": "0922000000",
                    "contact_role": "guardian",
                },
            )
            added, add_code = app.add_single_contact(
                data_file,
                "U-owner",
                {
                    "name": "爸爸",
                    "relationship": "爸爸",
                    "phone": "02-2345-6789",
                    "contact_role": "emergency",
                },
            )

            self.assertEqual(update_code, 200)
            self.assertEqual(updated["contact"]["phone"], "0922000000")
            self.assertEqual(add_code, 200)
            self.assertEqual(added["contact"]["contact_role"], "emergency")


if __name__ == "__main__":
    unittest.main()
