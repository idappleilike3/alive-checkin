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
        self.assertIn("onboarding_reminder_configured", text)
        self.assertIn("state.currentStep = 2", text)
        self.assertIn("state.currentStep = 3", text)
        self.assertIn("等待接受中", text)

    def test_beta_pages_name_yearly_plans(self):
        text = (ROOT / "beta-register.html").read_text(encoding="utf-8")
        self.assertIn("399 安心版年費", text)
        self.assertIn("799 守護版年費", text)
        self.assertIn("paid_399_year", text)
        self.assertIn("paid_799_year", text)

    def test_share_page_explains_acceptance_is_required(self):
        text = (ROOT / "liff/share-invite.html").read_text(encoding="utf-8")
        self.assertIn("Step 1 加入每日平安官方 LINE", text)
        self.assertIn("Step 2 設定我的資料與提醒時間", text)
        self.assertIn("Step 3 一鍵分享核心守護人", text)
        self.assertIn("Step 4 完成綁定", text)
        self.assertLess(
            text.index("Step 2 設定我的資料與提醒時間"),
            text.index("Step 3 一鍵分享核心守護人"),
        )
        self.assertIn("等待對方登入", text)
        self.assertIn("等待對方接受", text)
        self.assertIn("對方完成 LINE 登入並同意後", text)
        self.assertIn("對方接受後才顯示", text)

    def test_public_trial_page_uses_the_same_four_step_order(self):
        text = (ROOT / "trial-14.html").read_text(encoding="utf-8")
        labels = [
            "Step 1 加入每日平安官方 LINE",
            "Step 2 設定我的資料",
            "Step 3 一鍵分享核心守護人",
            "Step 4 完成綁定",
        ]
        positions = [text.index(label) for label in labels]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("等待對方登入", text)
        self.assertIn("等待對方接受", text)


if __name__ == "__main__":
    unittest.main()
