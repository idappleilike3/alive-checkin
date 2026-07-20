import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DeployConfigTests(unittest.TestCase):
    def test_render_uses_supported_python_version(self):
        python_version = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
        render_config = (ROOT / "render.yaml").read_text(encoding="utf-8")

        self.assertEqual(python_version, "3.11.9")
        self.assertIn("key: PYTHON_VERSION", render_config)
        self.assertIn("value: 3.11.9", render_config)

    def test_render_declares_all_line_webhook_credentials(self):
        render_config = (ROOT / "render.yaml").read_text(encoding="utf-8")

        self.assertIn("key: LINE_CHANNEL_ACCESS_TOKEN", render_config)
        self.assertIn("key: LINE_CHANNEL_SECRET", render_config)


if __name__ == "__main__":
    unittest.main()
