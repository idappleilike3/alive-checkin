import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app import get_calendar_notes, save_calendar_note, send_birthday_reminders


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

    def test_birthday_note_can_be_saved_and_reminded(self):
        created, code = save_calendar_note(
            self.data_file,
            {
                "line_user_id": "U-calendar",
                "date": "2026-08-08",
                "content": "記得打電話",
                "birthday_name": "爸爸",
                "birthday_relationship": "爸爸",
                "birthday_date": "2026-08-08",
                "birthday_yearly": True,
                "birthday_remind_days": 1,
            },
        )

        self.assertEqual(code, 200)
        self.assertEqual(created["notes"]["2026-08-08"]["birthday_name"], "爸爸")

        sent_messages = []

        def fake_sender(token, line_user_id, message):
            sent_messages.append((line_user_id, message))
            return {"ok": True}

        result, code = send_birthday_reminders(
            {
                "DATA_FILE": self.data_file,
                "LINE_CHANNEL_ACCESS_TOKEN": "token",
                "LINE_PUSH_SENDER": fake_sender,
                "CRON_NOW": datetime(2026, 8, 7, 9, 0),
            }
        )

        self.assertEqual(code, 200)
        self.assertEqual(result["sent"], 1)
        self.assertIn("明天是爸爸生日", sent_messages[0][1])

    def test_calendar_ui_contains_lunar_festivals_notes_and_google_entry(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="calendarNoteModal"', page)
        self.assertIn('id="calendarNoteInput"', page)
        self.assertIn('id="googleCalendarLink"', page)
        self.assertIn("lunar-mini", page)
        self.assertIn("TAIWAN_FESTIVALS", page)
        self.assertIn("LUNAR_FESTIVALS", page)
        self.assertIn('id="todayReminderCard"', page)
        self.assertIn('id="birthdayNameInput"', page)
        self.assertIn("birthday-reminders", (ROOT / "app.py").read_text(encoding="utf-8"))
        self.assertIn("body.neon .day-cell.festival .day-number", page)


if __name__ == "__main__":
    unittest.main()
