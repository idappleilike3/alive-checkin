import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BetaPageCopyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / "beta-register.html").read_text(encoding="utf-8")

    def test_shared_intro_and_feature_heading_use_approved_copy(self):
        self.assertIn(
            "每天10秒，讓家人知道你平安。先加入官方LINE，再依照四個步驟完成設定",
            self.page,
        )
        self.assertIn("本次體驗，你可以使用：", self.page)

    def test_short_feedback_invitation_follows_feature_list(self):
        features_at = self.page.index('aria-label="封測功能介紹"')
        feedback_at = self.page.index("體驗過程中，若遇到任何不清楚或操作不順的地方")
        steps_at = self.page.index('aria-label="加入封測流程"')
        self.assertLess(features_at, feedback_at)
        self.assertLess(feedback_at, steps_at)
        self.assertIn("你的回饋，會讓這個服務變得更好", self.page)

    def test_line_join_tip_and_new_faq_entries_are_present(self):
        self.assertIn("加入後，才能收到報平安通知與守護人綁定邀請", self.page)
        self.assertIn("為什麼要先加入官方LINE？", self.page)
        self.assertIn(
            "因為報平安通知與守護人綁定，都是透過LINE發送，加入後才能完整體驗。",
            self.page,
        )
        self.assertIn("封測期間需要做什麼？", self.page)
        self.assertIn("請實際體驗報平安、逾時提醒、SOS求救、守護人通知等功能", self.page)

    def test_799_only_task_is_hidden_on_399_page(self):
        self.assertIn('id="beta799Task"', self.page)
        self.assertIn("beta799Task.hidden = !is799", self.page)
        self.assertNotIn(
            '<div class="flow-step">799 組另請實測家庭 LINE 群組',
            self.page,
        )

    def test_each_beta_page_has_its_own_practice_title(self):
        self.assertIn(
            'is799 ? "家庭守護練習｜21天體驗" : "個人安心練習｜21天體驗"',
            self.page,
        )
        self.assertNotIn(
            'document.getElementById("title").textContent = "21天安心守護體驗"',
            self.page,
        )

    def test_faq_compares_all_three_formal_plans(self):
        self.assertIn("<summary>三個方案有什麼不同？</summary>", self.page)
        self.assertIn("199、399、799", self.page)
        self.assertNotIn("兩個體驗頁有什麼不同？", self.page)


if __name__ == "__main__":
    unittest.main()
