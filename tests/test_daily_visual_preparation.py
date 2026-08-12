import tempfile
import unittest
import inspect
from datetime import datetime
from pathlib import Path

import app


class DailyVisualPreparationTests(unittest.TestCase):
    def test_cron_prepares_tomorrows_visual(self):
        self.assertTrue(
            hasattr(app, "prepare_tomorrow_daily_card"),
            "cron must expose tomorrow's daily visual preparation",
        )

    def test_style_schedule_is_seventy_percent_illustration(self):
        self.assertTrue(hasattr(app, "daily_visual_style_for_date"))
        styles = [
            app.daily_visual_style_for_date(datetime(2026, 8, day).date())
            for day in range(1, 11)
        ]
        self.assertEqual(styles.count("illustration"), 7)
        self.assertEqual(styles.count("photorealistic"), 3)

    def test_generated_visual_is_saved_to_persistent_disk_and_state(self):
        self.assertTrue(hasattr(app, "prepare_tomorrow_daily_card"))
        with tempfile.TemporaryDirectory() as folder:
            data_file = str(Path(folder) / "state.json")
            generated = b"generated-image-bytes"
            result, code = app.prepare_tomorrow_daily_card(
                {
                    "DATA_FILE": data_file,
                    "DAILY_CARD_ASSET_DIR": folder,
                    "DAILY_IMAGE_GENERATOR": lambda _prompt: "https://example.test/new.png",
                    "DAILY_IMAGE_DOWNLOADER": lambda _url: generated,
                },
                now=datetime(2026, 8, 12, 9, 0),
            )

            self.assertEqual(code, 200)
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["source"], "generated")
            self.assertEqual(result["style"], "illustration")
            self.assertTrue(Path(result["local_path"]).is_file())
            self.assertEqual(Path(result["local_path"]).read_bytes(), generated)
            self.assertTrue(result["image_url"].startswith(
                "https://alive-checkin.onrender.com/generated-daily-card/"
            ))

    def test_cron_calls_daily_visual_preparation(self):
        source = inspect.getsource(app.run_cron_tick)
        self.assertIn("prepare_tomorrow_daily_card", source)
        self.assertIn('results["daily_card_preparation"]', source)

    def test_prepared_daily_visual_is_used_as_portrait_hero(self):
        image_url = (
            "https://alive-checkin.onrender.com/generated-daily-card/2026-08-13.img"
        )
        flex = app.build_daily_checkin_flex(
            datetime(2026, 8, 13, 12, 0),
            profile={"display_name": "Jennie"},
            holiday_asset_url=image_url,
        )
        self.assertEqual(flex["contents"]["hero"]["url"], image_url)
        self.assertEqual(flex["contents"]["hero"]["aspectRatio"], "4:5")


if __name__ == "__main__":
    unittest.main()
