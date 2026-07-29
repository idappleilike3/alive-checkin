from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OnboardingFlowTest(unittest.TestCase):
    def test_trial_uses_four_steps_and_reminder_before_share(self):
        text = (ROOT / "liff/onboarding.html").read_text(encoding="utf-8")
        self.assertIn("1 加入官方 LINE", text)
        self.assertIn("2 設定提醒", text)
        self.assertIn("3 分享邀請", text)
        self.assertIn("4 完成綁定", text)
        self.assertLess(text.index("設定提醒"), text.index("分享邀請"))
        self.assertIn("等待對方登入並接受", text)

    def test_beta_pages_name_yearly_plans(self):
        text = (ROOT / "beta-register.html").read_text(encoding="utf-8")
        self.assertIn("399 安心版年費", text)
        self.assertIn("799 守護版年費", text)
        self.assertIn("paid_399_year", text)
        self.assertIn("paid_799_year", text)

    def test_share_page_explains_acceptance_is_required(self):
        text = (ROOT / "liff/share-invite.html").read_text(encoding="utf-8")
        self.assertIn("等待對方接受", text)
        self.assertIn("對方完成 LINE 登入並同意後", text)
        self.assertIn("綁定完成後立即生效", text)


if __name__ == "__main__":
    unittest.main()
