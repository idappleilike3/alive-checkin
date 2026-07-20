import tempfile
import unittest
from pathlib import Path

from app import get_calendar_notes, save_calendar_note


ROOT = Path(__file__).resolve().parents[1]


class CalendarNotesTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_file = Path(self.temp_dir.name) / "state.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_note_can_be_created_and_updated(self):
        created, code = save_calendar_note(
            self.data_file,
            {"line_user_id": "U-calendar", "date": "2026-07-20", "content": "陪媽媽回診"},
        )

        self.assertEqual(code, 200)
        self.assertEqual(created["notes"]["2026-07-20"], "陪媽媽回診")

        updated, code = save_calendar_note(
            self.data_file,
            {"line_user_id": "U-calendar", "date": "2026-07-20", "content": "下午陪媽媽回診"},
        )

        self.assertEqual(code, 200)
        self.assertEqual(updated["notes"]["2026-07-20"], "下午陪媽媽回診")
        self.assertEqual(get_calendar_notes(self.data_file, "U-calendar")["notes"], updated["notes"])

    def test_empty_content_removes_existing_note(self):
        save_calendar_note(
            self.data_file,
            {"line_user_id": "U-calendar", "date": "2026-07-20", "content": "買藥"},
        )

        result, code = save_calendar_note(
            self.data_file,
            {"line_user_id": "U-calendar", "date": "2026-07-20", "content": "   "},
        )

        self.assertEqual(code, 200)
        self.assertNotIn("2026-07-20", result["notes"])

    def test_invalid_date_and_oversized_note_are_rejected(self):
        invalid_date, date_code = save_calendar_note(
            self.data_file,
            {"line_user_id": "U-calendar", "date": "2026-02-31", "content": "錯誤日期"},
        )
        oversized, size_code = save_calendar_note(
            self.data_file,
            {"line_user_id": "U-calendar", "date": "2026-07-20", "content": "字" * 501},
        )

        self.assertEqual(date_code, 400)
        self.assertEqual(invalid_date["error"], "invalid date")
        self.assertEqual(size_code, 400)
        self.assertEqual(oversized["error"], "note too long")

    def test_calendar_ui_contains_lunar_festivals_notes_and_google_entry(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="calendarNoteModal"', page)
        self.assertIn('id="calendarNoteInput"', page)
        self.assertIn('id="googleCalendarLink"', page)
        self.assertIn("lunar-mini", page)
        self.assertIn("TAIWAN_FESTIVALS", page)
        self.assertIn("LUNAR_FESTIVALS", page)


if __name__ == "__main__":
    unittest.main()
