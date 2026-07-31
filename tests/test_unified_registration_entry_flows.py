import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


ROOT = Path(__file__).resolve().parents[1]


class UnifiedRegistrationEntryFlowTests(unittest.TestCase):
    def test_guardian_can_accept_invitation_without_optional_phone(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_file = str(Path(tmp) / "state.json")
            state = app.load_state(data_file)
            app.get_profile(state, "U-owner", start_public_trial=True)
            app.get_profile(state, "U-guardian", start_public_trial=False)
            state["guardian_invites"] = [{
                "id": "invite-1",
                "invite_token": "token-1",
                "inviter_line_user_id": "U-owner",
                "status": "pending",
                "expires_at": "2099-12-31T23:59:59",
            }]
            app.save_state(data_file, state)

            with patch.object(app, "fetch_line_profile_dict", return_value={"displayName": "守護人"}):
                result, status = app.bind_emergency_contact(
                    data_file,
                    {
                        "inviter_line_user_id": "U-owner",
                        "contact_line_user_id": "U-guardian",
                        "contact_display_name": "王小明",
                        "contact_relationship": "女兒",
                        "contact_phone": "",
                        "invite_token": "token-1",
                        "recipient_consent": True,
                        "activate_trial": False,
                    },
                    {
                        "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
                        "LINE_PUSH_SENDER": lambda *_args, **_kwargs: {"ok": True},
                    },
                )

            self.assertEqual(status, 200)
            self.assertTrue(result["bound"])
            saved = app.load_state(data_file)["users"]["U-owner"]["contacts"]
            guardian = next(row for row in saved if row.get("line_user_id") == "U-guardian")
            self.assertEqual(guardian["phone"], "")

    def test_all_entry_pages_keep_their_registration_context(self):
        onboarding = (ROOT / "liff" / "onboarding.html").read_text(encoding="utf-8")
        trial = (ROOT / "trial-14.html").read_text(encoding="utf-8")
        beta = (ROOT / "beta-register.html").read_text(encoding="utf-8")
        invite = (ROOT / "invite.html").read_text(encoding="utf-8")

        self.assertIn('"beta_cohort"', onboarding)
        self.assertIn("open=onboarding", trial)
        self.assertIn("beta_cohort=${cohort}", beta)
        self.assertIn('q.set("invite_from", inviteFrom)', invite)

    def test_registration_copy_identifies_whose_data_and_phone_visibility(self):
        member = (ROOT / "index.html").read_text(encoding="utf-8")
        invite = (ROOT / "invite.html").read_text(encoding="utf-8")

        self.assertIn("你的姓名（本人）", member)
        self.assertIn("你是邀請人的誰？", member)
        self.assertIn("你的聯絡電話（選填）", member)
        self.assertIn("填寫後邀請人可以看到", member)
        self.assertNotIn('id="inviteGuardianPhone" type="tel" inputmode="tel" maxlength="20" autocomplete="tel" placeholder="例如：0912345678" required', member)
        self.assertIn("聯絡電話可不填", invite)

    def test_onboarding_shows_the_entry_plan_without_changing_it(self):
        member = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="onboardingEntryPlan"', member)
        self.assertIn("399 安心版｜21 天封測", member)
        self.assertIn("799 守護版｜21 天封測", member)
        self.assertIn("14 天安心體驗", member)

    def test_admin_has_separate_399_and_799_beta_share_actions(self):
        admin = (ROOT / "admin.html").read_text(encoding="utf-8")

        self.assertIn('data-beta-share="B399"', admin)
        self.assertIn('data-beta-share="B799"', admin)
        self.assertIn("/beta/399", admin)
        self.assertIn("/beta/799", admin)


if __name__ == "__main__":
    unittest.main()
