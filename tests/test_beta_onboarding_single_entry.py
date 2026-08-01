from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BetaOnboardingSingleEntryTests(unittest.TestCase):
    def test_beta_cta_uses_the_same_dedicated_onboarding_entry_for_both_plans(self):
        html = (ROOT / "beta-register.html").read_text(encoding="utf-8")

        self.assertIn("2010848330-UAiqPPYD/liff/onboarding.html?", html)
        self.assertIn("beta_cohort=${cohort}", html)
        self.assertNotIn("2010848330-UAiqPPYD?beta_cohort=${cohort}", html)


    def test_onboarding_does_not_enable_external_browser_auto_login(self):
        html = (ROOT / "liff" / "onboarding.html").read_text(encoding="utf-8")

        self.assertNotIn("withLoginOnExternalBrowser", html)


    def test_onboarding_claims_the_selected_beta_and_uses_authenticated_requests(self):
        html = (ROOT / "liff" / "onboarding.html").read_text(encoding="utf-8")

        self.assertIn("function selectedBetaCohort()", html)
        self.assertIn("beta_cohort: selectedBetaCohort()", html)
        self.assertIn("async function authHeaders()", html)
        self.assertIn('headers: await authHeaders()', html)


    def test_onboarding_reports_existing_members_even_if_local_page_state_was_reset(self):
        html = (ROOT / "liff" / "onboarding.html").read_text(encoding="utf-8")

        self.assertIn("registration.existing_user === true", html)
        self.assertIn("你已經註冊過每日平安", html)


    def test_beta_onboarding_explains_minimum_and_plan_specific_guardian_limit(self):
        html = (ROOT / "liff" / "onboarding.html").read_text(encoding="utf-8")

        self.assertIn("最少邀請 1 位核心守護人", html)
        self.assertIn("399 安心版 21 天封測最多 7 位", html)
        self.assertIn("799 守護版 21 天封測最多 15 位", html)


if __name__ == "__main__":
    unittest.main()
