import unittest

import app as alive_app


class AdminHolidayBackgroundGeneratorTests(unittest.TestCase):
    def test_catalog_includes_requested_major_and_minor_festivals(self):
        names = {row["name"] for row in alive_app.holiday_template_catalog(2026)}
        for name in {"元宵節", "七夕情人節", "國慶日", "中秋節", "聖誕節", "父親節"}:
            self.assertIn(name, names)

    def test_prompt_generates_background_only_and_preserves_brand_rules(self):
        prompt = alive_app.build_holiday_image_prompt({
            "holiday": "父親節", "mood": "溫暖", "elements": "蛋糕儀式感",
            "notes": "家人一起慶祝",
        })
        self.assertIn("蛋糕儀式感", prompt)
        self.assertIn("不要任何文字", prompt)
        self.assertIn("不要 Logo", prompt)
        self.assertIn("不要按鈕", prompt)
        self.assertIn("直式 4:5", prompt)

    def test_missing_image_api_key_returns_chinese_setup_message(self):
        result, status = alive_app.generate_holiday_background({}, {"holiday": "中秋節"})
        self.assertEqual(status, 503)
        self.assertEqual(result["error"], "image_api_key_missing")
        self.assertIn("圖片生成金鑰", result["message"])

    def test_injected_generator_returns_preview_without_line_delivery(self):
        calls = []
        result, status = alive_app.generate_holiday_background(
            {"HOLIDAY_IMAGE_GENERATOR": lambda prompt: calls.append(prompt) or "https://example.com/moon.webp"},
            {"holiday": "中秋節", "mood": "溫馨"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["image_url"], "https://example.com/moon.webp")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
