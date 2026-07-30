from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "trial-14.html").read_text(encoding="utf-8")

class TrialPublicHeaderActionsTests(unittest.TestCase):
    def test_logo_brand_and_title_share_one_header_row(self):
        self.assertIn('class="trial-header"', HTML)
        header = HTML.split('class="trial-header"', 1)[1].split("</header>", 1)[0]
        self.assertIn('class="brand"', header)
        self.assertIn("<h1>14 天安心體驗</h1>", header)
        self.assertIn(".trial-header{display:flex", HTML)

    def test_confirmed_intro_is_left_aligned_and_before_line_step(self):
        intro = HTML.index('class="trial-intro"')
        line_step = HTML.index('class="line-join-step"')
        story = HTML.index('class="story-title"')
        self.assertLess(intro, line_step)
        self.assertLess(line_step, story)
        self.assertIn("每天 10 秒，讓家人知道你平安。先加入官方 LINE", HTML)
        self.assertIn("先設定每日提醒，再分享守護邀請。對方接受後，你們的連結就建立了。", HTML)
        self.assertIn(".trial-intro{text-align:left", HTML)

    def test_line_join_step_precedes_large_trial_action(self):
        join = HTML.index("第一步：點我加入官方 LINE")
        tip = HTML.index("加入後，才能收到報平安通知與守護人綁定邀請")
        trial = HTML.index("開始 14 天安心體驗")
        self.assertLess(join, tip)
        self.assertLess(tip, trial)
        self.assertIn("加入完請返回這個頁面", HTML)
        self.assertIn(".line-join-step", HTML)
        self.assertIn(".primary-actions", HTML)

if __name__ == "__main__":
    unittest.main()
