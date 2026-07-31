import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app import (
    build_smart_reminder_flex,
    build_status,
    calendar_note_content,
    get_calendar_notes,
    load_state,
    save_calendar_note,
    save_state,
    send_birthday_reminders,
)


ROOT = Path(__file__).resolve().parents[1]


class CalendarNotesTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_file = Path(self.temp_dir.name) / "state.json"
        save_state(
            self.data_file,
            {
                "users": {
                    "U-calendar": {
                        "line_user_id": "U-calendar",
                        "plan": "paid_799",
                        "payment_status": "active",
                        "paid_until": "2099-01-01T00:00:00",
                    }
                }
            },
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_calendar_notes_allow_active_399_and_799_memberships(self):
        state = load_state(self.data_file)
        state["users"] = {
            "U-trial": {
                "line_user_id": "U-trial",
                "plan": "trial",
                "trial_started_at": "2026-07-27T09:00:00",
                "trial_end": "2099-01-01T00:00:00",
            },
            "U-399": {
                "line_user_id": "U-399",
                "plan": "paid_399",
                "payment_status": "active",
                "paid_until": "2099-01-01T00:00:00",
            },
            "U-399-year": {
                "line_user_id": "U-399-year",
                "plan": "paid_399_year",
                "payment_status": "active",
                "paid_until": "2099-01-01T00:00:00",
            },
            "U-beta-799": {
                "line_user_id": "U-beta-799",
                "plan": "paid_799",
                "payment_status": "beta",
                "membership_source": "beta",
                "beta_cohort": "A",
                "beta_started_at": "2026-07-27T09:00:00",
                "beta_ends_at": "2099-01-01T00:00:00",
            },
            "U-799": {
                "line_user_id": "U-799",
                "plan": "paid_799",
                "payment_status": "active",
                "paid_until": "2099-01-01T00:00:00",
            },
        }
        save_state(self.data_file, state)

        for line_user_id in ("U-trial",):
            read_result = get_calendar_notes(self.data_file, line_user_id)
            write_result, write_code = save_calendar_note(
                self.data_file,
                {
                    "line_user_id": line_user_id,
                    "date": "2026-07-27",
                    "content": "不應儲存",
                },
            )
            self.assertFalse(read_result["ok"])
            self.assertEqual(read_result["error"], "calendar_notes_require_799")
            self.assertEqual(write_code, 403)
            self.assertEqual(write_result["error"], "calendar_notes_require_799")

        allowed_399, allowed_399_code = save_calendar_note(
            self.data_file,
            {
                "line_user_id": "U-399",
                "date": "2026-07-27",
                "content": "399 網頁備忘",
            },
        )
        self.assertEqual(allowed_399_code, 200)
        self.assertTrue(allowed_399["ok"])
        allowed_399_year, allowed_399_year_code = save_calendar_note(
            self.data_file,
            {
                "line_user_id": "U-399-year",
                "date": "2026-07-27",
                "content": "399 年費網頁備忘",
            },
        )
        self.assertEqual(allowed_399_year_code, 200)
        self.assertTrue(allowed_399_year["ok"])

        beta_allowed, beta_allowed_code = save_calendar_note(
            self.data_file,
            {
                "line_user_id": "U-beta-799",
                "date": "2026-07-27",
                "content": "21 天 799 封測備忘錄",
            },
        )
        self.assertEqual(beta_allowed_code, 200)
        self.assertTrue(beta_allowed["ok"])

        allowed, allowed_code = save_calendar_note(
            self.data_file,
            {
                "line_user_id": "U-799",
                "date": "2026-07-27",
                "content": "799 樂年方案備忘錄",
            },
        )
        self.assertEqual(allowed_code, 200)
        self.assertTrue(allowed["ok"])

    def test_status_separates_calendar_notes_from_799_line_reminders(self):
        base = {"line_user_id": "U", "paid_until": "2099-01-01T00:00:00"}
        status_399 = build_status({
                **base,
                "plan": "paid_399",
                "payment_status": "active",
            })
        self.assertTrue(status_399["calendar_notes_enabled"])
        self.assertFalse(status_399["smart_reminders_enabled"])
        beta_799_status = build_status({
            **base,
            "plan": "paid_799_year",
            "payment_status": "beta",
            "membership_source": "beta",
            "beta_cohort": "B799",
            "beta_started_at": "2026-07-27T09:00:00",
            "beta_ends_at": "2099-01-01T00:00:00",
        })
        self.assertTrue(beta_799_status["calendar_notes_enabled"])
        formal_799 = build_status({
            **base,
            "plan": "paid_799",
            "payment_status": "active",
        })
        self.assertTrue(formal_799["calendar_notes_enabled"])
        self.assertTrue(formal_799["smart_reminders_enabled"])

        formal_799_year = build_status({
            **base,
            "plan": "paid_799_year",
            "payment_status": "active",
        })
        self.assertTrue(formal_799_year["calendar_notes_enabled"])
        self.assertTrue(formal_799_year["smart_reminders_enabled"])

    def test_member_center_restores_799_year_memo_entry_without_typo(self):
        member = (ROOT / "liff" / "member.html").read_text(encoding="utf-8")
        index = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn("我的平安紀錄", member)
        self.assertIn("＋ 新增備忘錄", member)
        self.assertIn('/?open=history#history', member)
        self.assertIn("799 年費", member)
        self.assertNotIn("樂年", member)
        self.assertNotIn("樂年", index)
        self.assertIn("399／799 月費與年費方案皆可使用網頁日期備忘", index)
        self.assertIn(
            'lineButton.hidden = status.smart_reminders_enabled !== true;',
            index,
        )

    def test_liff_pricing_shows_web_memo_for_399_and_799(self):
        page = (ROOT / "liff" / "pricing.html").read_text(encoding="utf-8")
        self.assertIn(
            '<tr><td>網頁日期備忘</td><td class="no">✗</td><td class="no">✗</td>'
            '<td class="no">✗</td><td class="yes">✓</td><td class="yes">✓</td>'
            '<td class="yes">✓</td><td class="yes">✓</td></tr>',
            page,
        )
        self.assertNotIn("<li>SOS、月曆備忘</li>", page)
        self.assertNotIn("<li>月曆備忘、簽到後停止當日提醒</li>", page.split("799 守護版(月)")[0])

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

    def test_migrated_same_date_notes_have_readable_public_output(self):
        state = load_state(self.data_file)
        state["users"]["U-calendar"] = {
            "line_user_id": "U-calendar",
            "plan": "paid_799",
            "payment_status": "active",
            "paid_until": "2099-01-01T00:00:00",
            "calendar_notes": {
                "2026-08-08": [
                    {
                        "id": "migration-calendar-note-0001",
                        "content": "陪媽媽回診",
                    },
                    {
                        "id": "migration-calendar-note-0002",
                        "content": "記得打電話",
                        "birthday_name": "爸爸",
                        "birthday_relationship": "爸爸",
                        "birthday_date": "2026-08-08",
                        "birthday_yearly": True,
                        "birthday_remind_days": 1,
                    },
                ]
            },
        }
        save_state(self.data_file, state)

        result = get_calendar_notes(self.data_file, "U-calendar")
        public_note = result["notes"]["2026-08-08"]

        self.assertEqual(public_note["content"], "陪媽媽回診\n記得打電話")
        self.assertEqual(public_note["birthday_name"], "爸爸")
        self.assertEqual(
            public_note["birthdays"],
            [
                {
                    "birthday_name": "爸爸",
                    "birthday_relationship": "爸爸",
                    "birthday_date": "2026-08-08",
                    "birthday_yearly": True,
                    "birthday_remind_days": 1,
                }
            ],
        )
        self.assertNotIn("id", public_note)
        self.assertNotIn("migration-calendar-note", str(result))
        self.assertNotIn("[{", calendar_note_content(state["users"]["U-calendar"]["calendar_notes"]["2026-08-08"]))

    def test_single_migrated_note_dict_hides_internal_fields(self):
        state = load_state(self.data_file)
        state["users"]["U-calendar"] = {
            "line_user_id": "U-calendar",
            "plan": "paid_799",
            "payment_status": "active",
            "paid_until": "2099-01-01T00:00:00",
            "calendar_notes": {
                "2026-08-08": {
                    "id": "migration-calendar-note-0001",
                    "migration_event_id": "migration-event-001",
                    "content": "記得打電話",
                    "birthday_name": "爸爸",
                    "birthday_relationship": "爸爸",
                    "birthday_date": "2026-08-08",
                    "birthday_yearly": True,
                    "birthday_remind_days": 1,
                }
            },
        }
        save_state(self.data_file, state)

        result = get_calendar_notes(self.data_file, "U-calendar")

        self.assertEqual(
            result["notes"]["2026-08-08"],
            {
                "content": "記得打電話",
                "birthday_name": "爸爸",
                "birthday_relationship": "爸爸",
                "birthday_date": "2026-08-08",
                "birthday_yearly": True,
                "birthday_remind_days": 1,
            },
        )
        response_text = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("migration-calendar-note", response_text)
        self.assertNotIn("migration_event_id", response_text)

    def test_save_response_sanitizes_existing_migrated_notes(self):
        state = load_state(self.data_file)
        state["users"]["U-calendar"] = {
            "line_user_id": "U-calendar",
            "plan": "paid_799",
            "payment_status": "active",
            "paid_until": "2099-01-01T00:00:00",
            "calendar_notes": {
                "2026-08-08": [
                    {
                        "id": "migration-calendar-note-0001",
                        "migration_event_id": "migration-event-001",
                        "content": "陪媽媽回診",
                    },
                    {
                        "id": "migration-calendar-note-0002",
                        "content": "記得打電話",
                        "birthday_name": "爸爸",
                        "birthday_relationship": "爸爸",
                        "birthday_date": "2026-08-08",
                        "birthday_yearly": True,
                        "birthday_remind_days": 1,
                    },
                ]
            },
        }
        save_state(self.data_file, state)

        result, code = save_calendar_note(
            self.data_file,
            {
                "line_user_id": "U-calendar",
                "date": "2026-08-09",
                "content": "領藥",
            },
        )

        self.assertEqual(code, 200)
        self.assertEqual(
            result["notes"]["2026-08-08"]["content"],
            "陪媽媽回診\n記得打電話",
        )
        self.assertEqual(result["notes"]["2026-08-09"], "領藥")
        response_text = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("migration-calendar-note", response_text)
        self.assertNotIn("migration_event_id", response_text)

    def test_migrated_birthday_inside_same_date_list_is_reminded(self):
        state = load_state(self.data_file)
        state["users"]["U-calendar"] = {
            "line_user_id": "U-calendar",
            "plan": "paid_799",
            "payment_status": "active",
            "paid_until": "2099-01-01T00:00:00",
            "calendar_notes": {
                "2026-08-08": [
                    {
                        "id": "migration-calendar-note-0001",
                        "content": "買藥",
                    },
                    {
                        "id": "migration-calendar-note-0002",
                        "content": "記得打電話",
                        "birthday_name": "爸爸",
                        "birthday_relationship": "爸爸",
                        "birthday_date": "2026-08-08",
                        "birthday_yearly": True,
                        "birthday_remind_days": 1,
                    },
                ]
            },
        }
        save_state(self.data_file, state)
        sent_messages = []

        def fake_sender(_token, line_user_id, message):
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
        self.assertEqual(len(sent_messages), 1)
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
        self.assertNotIn('id="birthdayNameInput"', page)
        self.assertIn("birthday-reminders", (ROOT / "app.py").read_text(encoding="utf-8"))
        self.assertIn(".day-cell.festival .day-number", page)
        self.assertNotIn("body.neon", page)

    def test_web_note_and_line_reminder_use_separate_entry_points(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn("純文字備忘只儲存，不會推播 LINE", page)
        self.assertIn('id="calendarNoteQuickAddBtn"', page)
        self.assertIn("＋ 新增日期備忘", page)
        self.assertIn('id="lineReminderQuickAddBtn"', page)
        self.assertIn("＋ 新增 LINE 推播提醒", page)
        note_modal = page.split('id="calendarNoteModal"')[1].split('id="smartReminderEditorModal"')[0]
        self.assertNotIn("LINE 推播", note_modal)
        self.assertNotIn("calendarNoteReminderBtn", note_modal)
        self.assertNotIn('<legend>家人生日提醒</legend>', page)
        self.assertIn('id="smartReminderCancelBtn" type="button">取消</button>', page)
        self.assertIn('overscroll-behavior:contain', page)

    def test_calendar_note_has_web_only_time_and_yearly_repeat(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="calendarNoteDate" type="date" required', page)
        self.assertIn('id="calendarNoteWebReminderTime" type="time"', page)
        self.assertIn('id="calendarNoteWebReminderYearly" type="checkbox"', page)
        self.assertIn("進入「每日平安」網頁時提醒一次", page)
        self.assertIn("checkDueWebCalendarNotes", page)

    def test_saved_web_reminders_have_an_explicit_edit_entry(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="calendarNoteReminderList"', page)
        self.assertIn("calendar-note-edit-btn", page)
        self.assertIn("修改記事與提醒", page)
        self.assertIn('openCalendarNote(button.dataset.date)', page)
        self.assertIn("每年重複", page)

    def test_line_reminder_has_its_own_full_date_and_24_hour_time_fields(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn('{ id: "memo", emoji: "📝", label: "一般備忘" }', page)
        self.assertIn('fillSmartReminderCategoryOptions(existing ? existing.category : "memo")', page)
        self.assertIn("日期（年／月／日）", page)
        self.assertIn('id="smartReminderDate" type="date" required', page)
        self.assertIn('id="smartReminderTime" type="time" value="09:00" required', page)
        self.assertIn("生日／紀念日可選每年重複；吃藥、回診等預設單次提醒", page)
        self.assertIn('class="action-btn smart-edit-btn"', page)
        self.assertIn(">修改<", page)
        self.assertIn("findSmartReminderForCalendarDate", page)
        self.assertIn('openSmartReminderEditor(null, getToday())', page)

    def test_saved_line_reminders_are_listed_with_edit_and_delete_actions(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="lineReminderList"', page)
        self.assertIn('const listEl = $("lineReminderList")', page)
        self.assertIn("修改 LINE 推播提醒", page)
        self.assertIn('class="action-btn smart-edit-btn"', page)
        self.assertIn('class="action-btn danger-action smart-delete-btn"', page)
        self.assertIn('openSmartReminderEditor(btn.dataset.id)', page)
        self.assertIn('deleteSmartReminder(btn.dataset.id)', page)

    def test_history_reminder_tools_are_compact_independent_accordions(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="calendarNoteCreateSection"', page)
        self.assertIn('id="calendarNoteManageSection"', page)
        self.assertIn('id="lineReminderManageSection"', page)
        self.assertIn('id="calendarNoteCount"', page)
        self.assertIn('id="lineReminderCount"', page)
        self.assertIn("筆", page)
        self.assertIn(".history-tool-accordion", page)
        self.assertIn(".history-tool-summary", page)
        self.assertIn("history-tool-body", page)

    def test_gratitude_and_daily_attention_are_not_repeated(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn("每日感恩", page)
        self.assertIn('id="todayReminderText"', page)
        self.assertIn('id="dailyAttentionTitle">今日提醒事項</h3>', page)
        self.assertNotIn('id="dailyBlessingText"', page)
        almanac_renderer = page.split("function renderDailyAlmanac")[1].split(
            "const WEB_NOTE_META_MARKER"
        )[0]
        self.assertNotIn("DAILY_BLESSINGS", almanac_renderer)
        self.assertNotIn("FESTIVAL_BLESSINGS", almanac_renderer)

    def test_calendar_note_web_reminder_metadata_uses_existing_note_storage(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn("WEB_NOTE_META_MARKER", page)
        self.assertIn("encodeCalendarNoteContent", page)
        self.assertIn("noteWebReminder", page)
        self.assertIn("content: storedContent", page)

    def test_general_memo_is_single_timed_line_reminder_without_eve_push(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")

        self.assertIn('"memo": {"emoji": "📝", "label": "一般備忘"}', source)
        self.assertIn('category = str(raw.get("category") or "memo")', source)
        self.assertIn("eve_remind = False", source)
        self.assertIn('"memo": f"📝 備忘提醒：{label}"', source)
        self.assertIn('title = "📝 備忘提醒"', source)
        self.assertIn('alt = f"備忘提醒：{name}"', source)

    def test_line_reminder_cards_have_two_actions_and_no_snooze(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")

        self.assertNotIn("smart:snooze:", source)
        self.assertNotIn("晚點提醒", source)
        birthday = build_smart_reminder_flex({
            "id": "birthday-1",
            "target_name": "媽媽",
            "category": "birthday",
            "category_label": "生日",
            "month": 7,
            "day": 30,
        })
        medicine = build_smart_reminder_flex({
            "id": "medicine-1",
            "target_name": "自己",
            "category": "medicine",
            "category_label": "吃藥",
            "month": 7,
            "day": 30,
        })
        birthday_labels = [
            item["action"]["label"]
            for item in birthday["contents"]["footer"]["contents"]
        ]
        medicine_labels = [
            item["action"]["label"]
            for item in medicine["contents"]["footer"]["contents"]
        ]
        self.assertEqual(birthday_labels, ["🎁傳送祝福", "✅已祝福"])
        self.assertEqual(medicine_labels, ["📋查看備忘", "✅我知道了"])


    def test_private_memo_push_explains_the_reminder_and_uses_warm_acknowledgement(self):
        message = build_smart_reminder_flex({
            "id": "memo-1",
            "target_name": "房租包",
            "category": "memo",
            "category_label": "一般備忘",
            "month": 7,
            "day": 31,
            "remind_time": "13:00",
            "note": "帶租約",
        })

        body_texts = [
            item["text"]
            for item in message["contents"]["body"]["contents"]
            if item.get("type") == "text"
        ]
        labels = [
            item["action"]["label"]
            for item in message["contents"]["footer"]["contents"]
        ]
        body_copy = "\n".join(body_texts)
        self.assertIn("提醒：7/31 13:00 房租包，請記得處理喔。", body_copy)
        self.assertIn("備註：帶租約", body_copy)
        self.assertEqual(labels, ["📋查看備忘", "好的，謝謝提醒 🙏"])



if __name__ == "__main__":
    unittest.main()
