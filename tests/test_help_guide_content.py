import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELP = ROOT / "help.html"


class HelpGuideContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = HELP.read_text(encoding="utf-8")

    def test_guide_has_eleven_numbered_steps(self):
        numbers = re.findall(r'<span class="num">(\d+)</span>', self.source)
        self.assertEqual(numbers, [str(number) for number in range(1, 12)])

    def test_official_line_link_is_current_and_old_link_is_removed(self):
        self.assertGreaterEqual(self.source.count("https://lin.ee/nRc3yxi"), 2)
        self.assertNotIn("%40042kwqib", self.source)

    def test_guardian_binding_flow_is_explicit(self):
        for copy in (
            "一鍵登入 LINE",
            "填寫本人設定",
            "一鍵分享守護卡",
            "守護人接受邀請",
            "雙方都會收到綁定成功訊息",
            "隔天開始收到每日報平安提醒",
        ):
            with self.subTest(copy=copy):
                self.assertIn(copy, self.source)

    def test_overdue_policy_matches_product_rules(self):
        for copy in ("24 小時", "36 小時", "48 小時", "72 小時", "15 分鐘後"):
            with self.subTest(copy=copy):
                self.assertIn(copy, self.source)
        self.assertIn("預設 48 小時", self.source)
        self.assertIn("依照優先順位通知守護人", self.source)

    def test_calendar_and_group_plan_copy_is_precise(self):
        for copy in (
            "199 月費／年費",
            "日期與節日",
            "不能新增備忘錄",
            "399 月費／年費",
            "不發 LINE 備忘錄推播",
            "799 月費／年費",
            "每天最多 2 則",
            "月費最多 1 群",
            "年費最多 3 群",
            "每群最多 50 人",
        ):
            with self.subTest(copy=copy):
                self.assertIn(copy, self.source)

    def test_action_links_use_real_product_entries(self):
        for url in (
            "https://liff.line.me/2010848330-UAiqPPYD?open=home",
            "https://liff.line.me/2010848330-UAiqPPYD?open=share-invite",
            "https://liff.line.me/2010848330-UAiqPPYD?open=checkin",
            "https://liff.line.me/2010848330-UAiqPPYD?open=history",
            "https://alive-checkin.onrender.com/liff/guardian-groups.html",
            "https://alive-checkin.onrender.com/pricing",
            "https://alive-checkin.onrender.com/faq",
        ):
            with self.subTest(url=url):
                self.assertIn(f'href="{url}"', self.source)


if __name__ == "__main__":
    unittest.main()
