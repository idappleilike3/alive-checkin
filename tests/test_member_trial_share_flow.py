from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MemberTrialShareFlowTests(unittest.TestCase):
    def test_member_center_separates_trial_share_from_guardian_binding(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="memberShareTrialBtn"', html)
        self.assertIn("分享 14 天免費體驗給朋友", html)
        self.assertNotIn('id="memberReinviteGuardianBtn"', html)
        self.assertIn('id="memberAddGuardianBtn"', html)
        self.assertIn('memberShareTrialBtn.addEventListener("click", shareTrialWithFriend)', html)

    def test_trial_share_opens_line_picker_directly_for_members(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        flow = html.split("async function shareTrialWithFriend", 1)[1].split(
            "async function shareFriendInvite", 1
        )[0]

        self.assertIn("requireLineMembership", flow)
        self.assertIn("tryLineShareTargetPicker", flow)
        self.assertIn("14 天免費體驗", flow)
        self.assertIn("trial-14.html", flow)
        self.assertNotIn("openShareInvitePage", flow)
        self.assertNotIn("invite_from", flow)

    def test_non_member_trial_share_is_sent_to_trial_introduction(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        flow = html.split("async function shareTrialWithFriend", 1)[1].split(
            "async function shareFriendInvite", 1
        )[0]

        self.assertIn('window.location.assign("/trial-14.html")', flow)

    def test_guardian_invitation_stays_on_dedicated_binding_flow(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        guardian_flow = html.split("async function shareContactInvite", 1)[1].split(
            "function currentShareReturnHash", 1
        )[0]

        self.assertIn("openShareInvitePage", guardian_flow)
        self.assertNotIn("shareTrialWithFriend", guardian_flow)


if __name__ == "__main__":
    unittest.main()
