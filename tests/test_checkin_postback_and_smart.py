"""報平安 postback、鬼打牆時區、799 智能提醒、邀請按鈕位置。"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))

import app  # noqa: E402


class CheckinPostbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_file = os.path.join(self.tmp.name, "state.json")
        self.addCleanup(self.tmp.cleanup)

    def test_today_string_uses_taipei(self):
        # Simulate UTC evening that is already next calendar day in Taipei
        fixed = datetime(2026, 7, 24, 22, 30, 0)  # Taipei local naive via CRON_NOW
        with mock.patch.object(app, "current_app_time", return_value=fixed):
            self.assertEqual(app.today_string({"CRON_NOW": fixed}), "2026-07-24")

    def test_profile_checked_accepts_utc_last_check_in_as_taipei_today(self):
        # UTC 2026-07-24 16:00 == Taipei 2026-07-25 00:00
        now_taipei = datetime(2026, 7, 25, 1, 0, 0)
        profile = {
            "history": [],
            "last_check_in": "2026-07-24T16:05:00",  # UTC-naive from old Render
        }
        self.assertTrue(app.profile_is_today_checked(profile, now=now_taipei))

    def test_record_checkin_persists_history_and_next_reminder(self):
        status = app.record_checkin(self.data_file, {"line_user_id": "U_test_checkin"})
        self.assertTrue(status.get("is_today_checked"))
        self.assertIn(app.today_string(), status.get("history") or [])
        self.assertTrue(status.get("last_check_in"))
        self.assertTrue(status.get("next_reminder_text") or status.get("next_reminder_at"))

        again = app.record_checkin(self.data_file, {"line_user_id": "U_test_checkin"})
        self.assertTrue(again.get("already_checked_today") or again.get("is_duplicate"))
        self.assertTrue(again.get("is_today_checked"))

    def test_checkin_postback_writes_member_history(self):
        reply = app.handle_checkin_postback(self.data_file, "U_pb_1")
        self.assertIn("報平安成功", reply)
        state = app.load_state(self.data_file)
        profile = state["users"]["U_pb_1"]
        self.assertIn(app.today_string(), profile.get("history") or [])
        self.assertTrue(profile.get("last_check_in"))

        reply2 = app.handle_checkin_postback(self.data_file, "U_pb_1")
        self.assertIn("已經報過", reply2)

    def test_is_checkin_postback_variants(self):
        self.assertTrue(app.is_checkin_postback("action=checkin"))
        self.assertTrue(app.is_checkin_postback("checkin:ok"))
        self.assertFalse(app.is_checkin_postback("smart:wish:abc"))
        self.assertFalse(app.is_checkin_postback("action=alert_confirm"))

    def test_daily_push_flex_uses_checkin_postback(self):
        sent = []

        def fake_sender(token, to, message):
            sent.append(message)
            return {"ok": True}

        state = app.load_state(self.data_file)
        profile = app.get_profile(state, "U_push_1")
        profile["reminder_times"] = ["00:00"]
        profile["history"] = []
        app.save_state(self.data_file, state)

        now = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        config = {
            "DATA_FILE": self.data_file,
            "LINE_CHANNEL_ACCESS_TOKEN": "x",
            "LINE_PUSH_SENDER": fake_sender,
            "CRON_NOW": now,
            "APP_TIMEZONE": "Asia/Taipei",
        }
        data, code = app.send_checkin_reminders(config)
        self.assertEqual(code, 200)
        self.assertGreaterEqual(data.get("sent", 0), 1)
        self.assertTrue(sent)
        footer = sent[0]["contents"]["footer"]["contents"]
        checkin_btn = footer[0]
        self.assertEqual(checkin_btn["action"]["type"], "postback")
        self.assertEqual(checkin_btn["action"]["data"], "action=checkin")
        self.assertIn("我平安", checkin_btn["action"]["label"])


class SmartReminderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_file = os.path.join(self.tmp.name, "state.json")
        self.addCleanup(self.tmp.cleanup)

    def test_399_blocked_799_allowed(self):
        state = app.load_state(self.data_file)
        p399 = app.get_profile(state, "U399")
        p399["plan"] = "paid_399"
        p399["payment_status"] = "active"
        p399["paid_until"] = "2099-01-01"
        p799 = app.get_profile(state, "U799")
        p799["plan"] = "paid_799"
        p799["payment_status"] = "active"
        p799["paid_until"] = "2099-01-01"
        app.save_state(self.data_file, state)

        denied, code = app.save_smart_reminder(
            self.data_file,
            {"line_user_id": "U399", "target_name": "媽媽", "category": "birthday", "month": 7, "day": 24},
        )
        self.assertEqual(code, 403)

        ok, code = app.save_smart_reminder(
            self.data_file,
            {"line_user_id": "U799", "target_name": "媽媽", "category": "birthday", "month": 7, "day": 24},
        )
        self.assertEqual(code, 200)
        self.assertEqual(ok["reminder"]["target_name"], "媽媽")
        self.assertTrue(ok["reminder"]["notify_private"])
        self.assertFalse(ok["reminder"]["notify_group"])

    def test_smart_push_private_only(self):
        sent = []

        def fake_sender(token, to, message):
            sent.append((to, message))
            return {"ok": True}

        state = app.load_state(self.data_file)
        profile = app.get_profile(state, "U799s")
        profile["plan"] = "paid_799"
        profile["payment_status"] = "active"
        profile["paid_until"] = "2099-01-01"
        today = datetime.now()
        profile["smart_reminders"] = [
            {
                "id": "sr1",
                "target_name": "媽媽",
                "category": "birthday",
                "month": today.month,
                "day": today.day,
                "notify_private": True,
                "notify_group": False,
                "eve_remind": True,
            }
        ]
        app.save_state(self.data_file, state)
        now = today.replace(hour=10, minute=0, second=0, microsecond=0)
        data, code = app.send_smart_reminders(
            {
                "DATA_FILE": self.data_file,
                "LINE_CHANNEL_ACCESS_TOKEN": "x",
                "LINE_PUSH_SENDER": fake_sender,
                "CRON_NOW": now,
            }
        )
        self.assertEqual(code, 200)
        self.assertGreaterEqual(data.get("sent", 0), 1)
        self.assertEqual(sent[0][0], "U799s")
        self.assertEqual(sent[0][1]["type"], "flex")


class InviteButtonCleanupTests(unittest.TestCase):
    def test_member_center_keeps_wait_row_invite_only(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        # Wait-row invite remains
        self.assertIn("等待 LINE 綁定", page)
        self.assertIn('class="one-tap-invite-btn member-invite-guardian"', page)
        # Duplicate action-row invite removed (no second invite in manage-actions)
        self.assertNotIn(
            'member-guardian-manage-actions${bound ? "" : " has-invite"}',
            page,
        )
        # Top share button in member guardian section removed
        member_section = page.split('id="memberGuardianSection"')[1].split('id="memberSmartRemindersSection"')[0]
        self.assertNotIn("一鍵邀請守護人", member_section)
        # Edit / delete kept
        self.assertIn("member-edit-guardian", page)
        self.assertIn("member-delete-guardian", page)

    def test_member_html_keeps_wait_invite_removes_top_share(self):
        page = (ROOT / "liff" / "member.html").read_text(encoding="utf-8")
        self.assertIn("等待 LINE 綁定", page)
        self.assertIn("one-tap-invite-btn", page)
        self.assertNotIn("shareInviteBtn", page)
        self.assertIn("智能提醒", page)


if __name__ == "__main__":
    unittest.main()
