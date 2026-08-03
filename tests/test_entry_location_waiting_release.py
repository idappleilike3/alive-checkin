from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class EntryLocationWaitingReleaseTests(unittest.TestCase):
    def read(self, relative_path):
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_trial_entry_shows_immediate_waiting_feedback_before_liff_navigation(self):
        page = self.read("trial-14.html")
        self.assertIn('id="entryLoading"', page)
        self.assertIn("正在準備 14 天安心體驗", page)
        self.assertIn("請稍候 5–10 秒，請不要重複點擊或關閉頁面", page)
        self.assertIn("showEntryLoading", page)
        handler = page[page.index("function showEntryLoading"):page.index("document.getElementById('startTrialOnboarding')")]
        self.assertLess(handler.index("event.preventDefault()"), handler.index('hidden=false'))
        self.assertIn("requestAnimationFrame", handler)
        self.assertIn("location.assign", handler)

    def test_beta_entry_shows_immediate_waiting_feedback_before_liff_navigation(self):
        page = self.read("beta-register.html")
        self.assertIn('id="entryLoading"', page)
        self.assertIn("正在準備 21 天封測註冊", page)
        self.assertIn("請稍候 5–10 秒，請不要重複點擊或關閉頁面", page)
        self.assertIn("showEntryLoading", page)
        handler = page[page.index("function showEntryLoading"):page.index('continueRegistration.addEventListener')]
        self.assertLess(handler.index("event.preventDefault()"), handler.index("hidden = false"))
        self.assertIn("requestAnimationFrame", handler)
        self.assertIn("location.assign", handler)

    def test_share_invite_has_generation_waiting_state_and_duplicate_click_guard(self):
        page = self.read("liff/share-invite.html")
        self.assertIn("正在產生你的專屬邀請連結，請稍候", page)
        self.assertIn("beginInternalWait", page)
        self.assertIn("shareActionInProgress", page)

    def test_all_self_membership_entries_route_to_location_required_onboarding(self):
        trial = self.read("trial-14.html")
        beta = self.read("beta-register.html")
        invite = self.read("invite.html")
        onboarding = self.read("liff/onboarding.html")
        self.assertIn("open=onboarding", trial)
        self.assertIn("open=onboarding", beta)
        self.assertIn("開始你的 14 天免費體驗", invite)
        self.assertIn("open=onboarding", invite)
        self.assertIn('id="onboardingCity"', onboarding)
        self.assertIn('id="onboardingDistrict"', onboarding)
        self.assertIn("saveOnboardingLocation", onboarding)

    def test_accepting_guardian_invite_does_not_require_location_or_auto_start_trial(self):
        invite = self.read("invite.html")
        self.assertIn('q.set("return_to", "guardian_binding")', invite)
        self.assertIn("if (!inviteFrom && !friendInvite && !openAction)", invite)
        self.assertIn('class="guide trial-link"', invite)
        self.assertNotIn('q.set("activate_trial", "true")', invite)

if __name__ == "__main__":
    unittest.main()
