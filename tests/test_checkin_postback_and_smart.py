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
        fixed = datetime(2026, 7, 25, 1, 26, 0)
        with mock.patch.object(app, "current_app_time", return_value=fixed):
            reply = app.handle_checkin_postback(self.data_file, "U_pb_1")
        if isinstance(reply, list):
            reply = "\n".join(str(x) if not isinstance(x, dict) else x.get("altText", "") for x in reply)
        self.assertIn("報平安成功", reply)
        self.assertIn("7/25（六）", reply)
        self.assertIn("01:26", reply)
        self.assertIn("💌", reply)
        self.assertIn("下次提醒", reply)
        state = app.load_state(self.data_file)
        profile = state["users"]["U_pb_1"]
        self.assertIn("2026-07-25", profile.get("history") or [])
        self.assertTrue(profile.get("last_check_in"))
        # 同日剩餘提醒 slot 應標記為已處理
        slots = (profile.get("checkin_reminder_sent_slots") or {}).get("2026-07-25") or []
        self.assertTrue(slots)

        with mock.patch.object(app, "current_app_time", return_value=fixed):
            reply2 = app.handle_checkin_postback(self.data_file, "U_pb_1")
        if isinstance(reply2, list):
            reply2 = "\n".join(str(x) if not isinstance(x, dict) else x.get("altText", "") for x in reply2)
        self.assertIn("已經報過", reply2)

    def test_after_checkin_cron_skips_remaining_same_day_slots(self):
        """今日已報平安後，同日後續排程提醒不再推「請報平安」視窗。"""
        sent = []

        def fake_sender(token, to, message):
            sent.append((to, message))
            return {"ok": True}

        fixed_morning = datetime(2026, 7, 25, 8, 0, 0)
        with mock.patch.object(app, "current_app_time", return_value=fixed_morning):
            app.record_checkin(
                self.data_file,
                {"line_user_id": "U_skip_slots"},
                config={"CRON_NOW": fixed_morning, "APP_TIMEZONE": "Asia/Taipei"},
            )
        state = app.load_state(self.data_file)
        profile = state["users"]["U_skip_slots"]
        profile["reminder_times"] = ["08:00", "12:00", "18:00"]
        profile["plan"] = "paid_799"
        profile["payment_status"] = "active"
        profile["paid_until"] = "2099-01-01"
        app.save_state(self.data_file, state)

        afternoon = datetime(2026, 7, 25, 18, 5, 0)
        data, code = app.send_checkin_reminders(
            {
                "DATA_FILE": self.data_file,
                "LINE_CHANNEL_ACCESS_TOKEN": "x",
                "LINE_PUSH_SENDER": fake_sender,
                "CRON_NOW": afternoon,
                "APP_TIMEZONE": "Asia/Taipei",
            }
        )
        self.assertEqual(code, 200)
        self.assertEqual(data.get("sent", 0), 0)
        self.assertEqual(sent, [])

        # 隔日進入下一個時段的五分鐘時間窗仍會推
        next_day = datetime(2026, 7, 26, 12, 4, 0)
        data2, code2 = app.send_checkin_reminders(
            {
                "DATA_FILE": self.data_file,
                "LINE_CHANNEL_ACCESS_TOKEN": "x",
                "LINE_PUSH_SENDER": fake_sender,
                "CRON_NOW": next_day,
                "APP_TIMEZONE": "Asia/Taipei",
            }
        )
        self.assertEqual(code2, 200)
        self.assertGreaterEqual(data2.get("sent", 0), 1)
        self.assertTrue(sent)

    def test_expiry_remind_on_checkin_and_opt_out(self):
        fixed = datetime(2026, 7, 25, 10, 0, 0)
        state = app.load_state(self.data_file)
        profile = app.get_profile(state, "U_exp")
        profile["plan"] = "trial"
        profile["trial_started_at"] = (fixed - timedelta(days=13)).isoformat(timespec="seconds")
        profile["trial_end"] = (fixed + timedelta(days=1)).isoformat(timespec="seconds")
        profile["trial_bonus_days"] = 0
        app.save_state(self.data_file, state)

        with mock.patch.object(app, "current_app_time", return_value=fixed):
            reply = app.handle_checkin_postback(self.data_file, "U_exp")
        self.assertIsInstance(reply, list)
        self.assertEqual(len(reply), 2)
        self.assertIn("報平安成功", reply[0])
        self.assertEqual(reply[1]["type"], "flex")
        footer = reply[1]["contents"]["footer"]["contents"]
        self.assertEqual(footer[0]["action"]["type"], "uri")
        self.assertIn("pricing", footer[0]["action"]["uri"])
        self.assertEqual(footer[1]["action"]["data"], "action=expiry_opt_out")

        state2 = app.load_state(self.data_file)
        self.assertEqual(state2["users"]["U_exp"].get("expiry_remind_sent_date"), "2026-07-25")

        # 同日不再附帶
        with mock.patch.object(app, "current_app_time", return_value=fixed.replace(hour=15)):
            reply2 = app.handle_checkin_postback(self.data_file, "U_exp")
        self.assertIsInstance(reply2, str)

        opt = app.handle_expiry_opt_out_postback(self.data_file, "U_exp")
        self.assertIn("不會再提醒", opt)
        self.assertTrue(app.load_state(self.data_file)["users"]["U_exp"].get("expiry_remind_opt_out"))


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
        profile["reminder_times"] = ["12:00"]
        profile["history"] = []
        app.save_state(self.data_file, state)

        now = datetime(2026, 7, 25, 12, 0, 0)
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
        body_texts = "\n".join(
            c.get("text", "") for c in sent[0]["contents"]["body"]["contents"]
        )
        self.assertIn("✨", body_texts)
        self.assertEqual(sent[0]["contents"]["header"]["backgroundColor"], "#00B900")


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
        # Top share / re-invite button kept in member guardian section
        member_section = page.split('id="memberGuardianSection"')[1].split('id="memberSmartRemindersSection"')[0]
        self.assertIn("再邀請一位守護人", member_section)
        self.assertIn("memberInviteMoreGuardianBtn", member_section)
        self.assertIn("memberReinviteGuardianBtn", member_section)
        self.assertIn("inviteMoreGuardiansFromMember", page)
        # Edit / delete kept
        self.assertIn("member-edit-guardian", page)
        self.assertIn("member-delete-guardian", page)

    def test_member_html_keeps_wait_invite_and_reinvite(self):
        page = (ROOT / "liff" / "member.html").read_text(encoding="utf-8")
        self.assertIn("等待 LINE 綁定", page)
        self.assertIn("one-tap-invite-btn", page)
        self.assertIn("reinviteGuardianBtn", page)
        self.assertIn("再邀請一位守護人", page)
        self.assertIn("免費延長 7 天", page)
        self.assertNotIn("shareInviteBtn", page)
        self.assertIn("智能提醒", page)
        self.assertIn("smartRemindersPanel", page)
        self.assertIn("dailyCheckinReminderEnabled", page)
        self.assertNotIn("smartNotifyGroup", page)
        self.assertNotIn("群組提醒", page)

    def test_index_smart_remind_second_layer_and_home_padding(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="smartRemindersPanel"', page)
        self.assertIn('id="smartRemindersToggleBtn"', page)
        self.assertIn("dailyCheckinReminderEnabled", page)
        self.assertNotIn("smartReminderNotifyGroup", page)
        # 智能提醒不再提供群組推播勾選；守護群偏好仍可有「群組提醒（選用）」
        self.assertNotIn("選擇守護人", page)
        self.assertIn("核心守護人", page)
        self.assertIn("148px + env(safe-area-inset-bottom", page)
        self.assertIn("72px + env(safe-area-inset-bottom", page)
        self.assertIn("88px + env(safe-area-inset-bottom", page)
        self.assertIn('id="smartReminderEditorModal"', page)
        self.assertIn('id="smartReminderCategory"', page)
        self.assertIn('type="date"', page)
        self.assertIn('id="memberDailyReminderCountRow"', page)
        self.assertIn("一次", page)
        self.assertIn("guardianGroupBindStatusCard", page)
        self.assertNotIn("類型代碼", page)
        self.assertIn("flex-direction: column", page)
        self.assertIn("核心守護一鍵分享", page)
        self.assertIn('id="coreGuardianShareBtn"', page)
        self.assertIn('openShareInvitePage("guardians")', page)


if __name__ == "__main__":
    unittest.main()
