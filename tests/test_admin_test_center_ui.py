import unittest
from pathlib import Path


class AdminTestCenterUiTests(unittest.TestCase):
    def test_admin_page_contains_safe_test_center(self):
        source = Path("admin.html").read_text(encoding="utf-8")

        self.assertIn('id="test-center"', source)
        self.assertIn('id="testAccountSelect"', source)
        self.assertIn('id="testIntegrationStatus"', source)
        self.assertIn('id="testCenterRuns"', source)
        self.assertIn("loadTestCenter", source)
        self.assertIn("runTestCenterAction", source)
        self.assertIn("/api/admin/test-center/run", source)
        self.assertIn("測試模式", source)
        for test_id in (
            "daily_greeting",
            "trial_14_notice",
            "beta_21_notice",
            "paid_expiry_notice",
            "payment_restore",
            "sos_location",
            "guardian_invite",
            "beta_feedback_1900",
            "stop_renewal_notice",
            "r2_backup",
        ):
            self.assertIn(f'data-test-id="{test_id}"', source)


if __name__ == "__main__":
    unittest.main()
