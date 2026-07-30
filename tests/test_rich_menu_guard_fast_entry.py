import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RichMenuGuardFastEntryTests(unittest.TestCase):
    def test_safety_guard_skips_liff_redirect_and_opens_guard_route(self):
        config = json.loads(
            (ROOT / "line-rich-menu-config.json").read_text(encoding="utf-8")
        )
        action = next(
            area["action"]
            for area in config["areas"]
            if area["action"].get("label") == "安全守護"
        )

        self.assertEqual(
            action["uri"],
            "https://alive-checkin.onrender.com/?open=guard",
        )
        self.assertNotIn("liff.line.me", action["uri"])


if __name__ == "__main__":
    unittest.main()
