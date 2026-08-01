import unittest
from pathlib import Path


class ExpiryPricingAnimationTests(unittest.TestCase):
    def test_expiry_reminder_entry_has_reduced_motion_safe_welcome_animation(self):
        html = (Path(__file__).parents[1] / "liff" / "pricing.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("expiry-welcome", html)
        self.assertIn("get('from') === 'expiry_reminder'", html)
        self.assertIn("@media (prefers-reduced-motion: reduce)", html)
        self.assertIn("方案內容都為您保留好了", html)

    def test_liff_pricing_redirect_preserves_expiry_animation_source(self):
        html = (Path(__file__).parents[1] / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("expiry_reminder", html)
        self.assertIn('? "?from=expiry_reminder"', html)
        self.assertIn("location.replace(publicOpenPages[action] + expirySource + section)", html)


if __name__ == "__main__":
    unittest.main()
