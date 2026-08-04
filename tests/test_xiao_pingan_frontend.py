import unittest
from pathlib import Path


HTML = Path(__file__).resolve().parents[1] / "index.html"


class XiaoPinganFrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = HTML.read_text(encoding="utf-8")

    def test_chat_has_free_text_form_and_log(self):
        self.assertIn('id="xiaoPinganChatLog"', self.html)
        self.assertIn('id="xiaoPinganQuestionInput"', self.html)
        self.assertIn('id="xiaoPinganChatForm"', self.html)
        self.assertIn('aria-live="polite"', self.html)

    def test_character_remains_separate_from_panel(self):
        self.assertIn('id="xiaoPinganCharacter"', self.html)
        self.assertIn('id="peaceHelperPanel"', self.html)
        self.assertIn('class="xiao-pingan-svg"', self.html)

    def test_all_fifteen_animations_are_registered(self):
        expected = [
            "smile", "blink", "wave", "heartbeat", "float",
            "clap", "hearts", "stars", "worried", "alert-red",
            "point-location", "phone", "confetti", "hug", "jump",
        ]
        for name in expected:
            self.assertIn(f'"{name}"', self.html)

    def test_reduced_motion_and_accessible_controls_exist(self):
        self.assertIn("prefers-reduced-motion: reduce", self.html)
        self.assertIn('aria-label="輸入想問小平安的問題"', self.html)
        self.assertIn('aria-label="傳送問題"', self.html)


if __name__ == "__main__":
    unittest.main()
