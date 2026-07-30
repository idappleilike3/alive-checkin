from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "liff" / "onboarding.html").read_text(encoding="utf-8")


class OnboardingReadableLayoutTests(unittest.TestCase):
    def test_heading_is_before_story_image_and_left_aligned(self):
        self.assertLess(HTML.index('class="beginner-story-copy"'), HTML.index("<img "))
        self.assertIn(".beginner-story-copy {", HTML)
        self.assertIn("text-align: left;", HTML)

    def test_first_two_steps_use_large_plain_language_labels(self):
        self.assertIn("第一步：加入「每日平安」官方 LINE", HTML)
        self.assertIn("加入完成後，請返回這個頁面", HTML)
        self.assertIn("第二步：開始 14 天安心體驗", HTML)
        self.assertIn(".peace-step strong {", HTML)
        self.assertIn("font-size: 20px;", HTML)

    def test_action_text_is_balanced_without_single_character_orphans(self):
        self.assertIn("text-wrap: balance;", HTML)
        self.assertIn("word-break: keep-all;", HTML)
        self.assertIn(".btn-label", HTML)
        self.assertIn("開始 14 天<br>安心體驗", HTML)


if __name__ == "__main__":
    unittest.main()
