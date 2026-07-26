import unittest
from pathlib import Path
from unittest.mock import patch

import app as alive_app


ROOT = Path(__file__).resolve().parents[1]


class LiffFastRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.client = alive_app.create_app({"TESTING": True}).test_client()

    def section(self, start, end):
        self.assertIn(start, self.page)
        self.assertIn(end, self.page)
        return self.page[self.page.index(start):self.page.index(end)]

    def test_deep_link_is_applied_before_liff_network_initialization(self):
        bootstrap = self.page[
            self.page.index("async function bootstrapApp()"):
            self.page.index("appBootstrapPromise = bootstrapApp()")
        ]
        self.assertIn("applyInitialDeepLinkRoute()", bootstrap)
        self.assertLess(
            bootstrap.index("applyInitialDeepLinkRoute()"),
            bootstrap.index("await initLine()"),
        )

    def test_open_and_page_share_one_action_parser(self):
        self.assertIn("function requestedAppAction()", self.page)
        self.assertIn('getAppParam("open") || getAppParam("page")', self.page)
        self.assertIn('"checkin"', self.page)
        self.assertIn('"guard"', self.page)
        self.assertIn('"sos"', self.page)
        self.assertIn('"member"', self.page)

    def test_public_pages_redirect_before_liff_initialization(self):
        router = self.section(
            "function applyInitialDeepLinkRoute()",
            "async function initializeLiff()",
        )
        for page in ("help", "faq", "pricing", "terms", "privacy"):
            self.assertIn(f"{page}:", router)
        self.assertIn("location.replace", router)

    def test_fixed_liff_id_initializes_before_background_config(self):
        initializer = self.page[
            self.page.index("async function initializeLiff()"):
            self.page.index("async function initLine()")
        ]
        self.assertIn('const FIXED_LIFF_ID = "2010848330-UAiqPPYD"', initializer)
        self.assertIn("await liff.init({ liffId: FIXED_LIFF_ID })", initializer)
        self.assertIn("appConfigPromise", initializer)
        self.assertLess(
            initializer.index("await liff.init({ liffId: FIXED_LIFF_ID })"),
            initializer.index('fetch("/api/config")'),
        )

    def test_line_registration_occurs_once_per_bootstrap(self):
        self.assertEqual(self.page.count('fetch("/api/line/register"'), 1)

    def test_initial_member_requests_run_in_parallel(self):
        loader = self.section(
            "async function loadInitialMemberData()",
            "async function initApp()",
        )
        self.assertIn("const statusPromise", loader)
        self.assertIn("const contactsPromise", loader)
        self.assertIn("const onboardingPromise", loader)
        self.assertIn("const status = await statusPromise", loader)

    def test_first_status_response_syncs_checkin_button_immediately(self):
        loader = self.section(
            "async function loadInitialMemberData()",
            "async function initApp()",
        )
        self.assertIn("renderStatus(status)", loader)
        self.assertIn("syncCheckBtn(status)", loader)

    def test_first_status_response_unlocks_safe_member_actions(self):
        loader = self.section(
            "async function loadInitialMemberData()",
            "async function initApp()",
        )
        self.assertIn('$("mvpSafeBtn").disabled = false', loader)
        self.assertIn('$("mvpGuardStartBtn").disabled = false', loader)
        self.assertIn("renderSosAccess()", loader)

    def test_background_poll_is_sixty_seconds_not_five(self):
        self.assertIn("}, 60000);", self.page)
        self.assertNotIn("}, 5000);", self.page)
        self.assertIn('document.visibilityState === "visible"', self.page)

    def test_migration_page_is_served(self):
        response = self.client.get("/liff/migrate.html")
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)

    def test_account_migration_redeems_after_liff_before_member_bootstrap(self):
        bootstrap = self.section(
            "async function bootstrapApp()",
            "appBootstrapPromise = bootstrapApp()",
        )
        self.assertIn("await redeemPendingAccountMigration()", bootstrap)
        self.assertLess(
            bootstrap.index("await initLine()"),
            bootstrap.index("await redeemPendingAccountMigration()"),
        )
        self.assertLess(
            bootstrap.index("await redeemPendingAccountMigration()"),
            bootstrap.index("await initApp("),
        )

    def test_migration_redemption_reuses_member_data_without_page_reload(self):
        redeem = self.section(
            "async function redeemPendingAccountMigration()",
            "function requestedAppAction()",
        )
        self.assertIn('fetch("/api/account-migration/redeem"', redeem)
        self.assertIn("removeMigrationCodeFromVisibleUrl()", redeem)
        self.assertIn("history.replaceState", self.page)
        self.assertIn("await loadInitialMemberData()", redeem)
        self.assertNotIn("location.reload", redeem)

    def test_degraded_liff_embed_redirect_uses_query_without_extra_slash(self):
        with patch.object(alive_app, "liff_entry_url", None):
            response = self.client.get("/liff/onboarding")
        self.addCleanup(response.close)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["Location"],
            "https://liff.line.me/2010848330-UAiqPPYD?open=onboarding",
        )


if __name__ == "__main__":
    unittest.main()
