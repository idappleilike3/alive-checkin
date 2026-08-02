"""Taiwan holiday helper + daily push Flex / broadcast."""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))

import app  # noqa: E402
import holidays_tw  # noqa: E402


class HolidaysTwTests(unittest.TestCase):
    def test_solar_national_day(self):
        h = holidays_tw.holiday_for(date(2026, 10, 10))
        self.assertIsNotNone(h)
        self.assertIn("雙十", h["name"])
        self.assertTrue(h["blessing"])

    def test_lunar_mid_autumn_2026(self):
        h = holidays_tw.holiday_for(date(2026, 9, 25))
        self.assertEqual(h["name"], "中秋節")

    def test_mothers_day_dynamic(self):
        # 2028 Mother's Day (2nd Sunday May) = May 14
        h = holidays_tw.holiday_for(date(2028, 5, 14))
        self.assertEqual(h["name"], "母親節")

    def test_positive_quote_rotates(self):
        a = holidays_tw.positive_quote_for(date(2026, 1, 1))
        b = holidays_tw.positive_quote_for(date(2026, 1, 2))
        self.assertTrue(a)
        self.assertNotEqual(a, b)

    def test_ordinary_day_no_holiday(self):
        self.assertIsNone(holidays_tw.holiday_for(date(2026, 7, 24)))


class DailyPushFlexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_file = os.path.join(self.tmp.name, "state.json")
        self.addCleanup(self.tmp.cleanup)

    def test_flex_includes_quote_and_checkin_postback(self):
        now = datetime(2026, 7, 24, 9, 0, 0)
        flex = app.build_daily_checkin_flex(now, target_time="09:00")
        self.assertEqual(flex["type"], "flex")
        body_texts = [c.get("text", "") for c in flex["contents"]["body"]["contents"]]
        joined = "\n".join(body_texts)
        self.assertIn("今天一切都還好嗎", joined)
        self.assertIn("✨", joined)
        self.assertNotIn("中秋", joined)  # ordinary day
        footer = flex["contents"]["footer"]["contents"]
        self.assertEqual(footer[0]["action"]["type"], "postback")
        self.assertEqual(footer[0]["action"]["data"], "action=checkin")
        self.assertEqual(flex["contents"]["header"]["backgroundColor"], "#00B900")

    def test_flex_includes_holiday_blessing(self):
        now = datetime(2026, 9, 25, 9, 0, 0)
        flex = app.build_daily_checkin_flex(now)
        joined = "\n".join(c.get("text", "") for c in flex["contents"]["body"]["contents"])
        self.assertIn("中秋", joined)
        self.assertIn("月圓", joined)

    def test_broadcast_sends_even_if_checked_in(self):
        sent = []

        def fake_sender(token, to, message):
            sent.append((to, message))
            return {"ok": True}

        state = app.load_state(self.data_file)
        p = app.get_profile(state, "U_bc_1")
        p["history"] = ["2026-07-24"]
        p["last_check_in"] = "2026-07-24T08:00:00"
        p["reminder_times"] = ["12:00"]
        blocked = app.get_profile(state, "U_bc_blocked")
        blocked["line_push_blocked"] = True
        no_id = app.get_profile(state, "U_no_line")
        no_id["line_user_id"] = ""
        app.save_state(self.data_file, state)

        data, code = app.broadcast_checkin_reminders(
            {
                "DATA_FILE": self.data_file,
                "LINE_CHANNEL_ACCESS_TOKEN": "x",
                "LINE_PUSH_SENDER": fake_sender,
                "CRON_NOW": datetime(2026, 7, 24, 10, 0, 0),
                "APP_TIMEZONE": "Asia/Taipei",
            },
            pause_every=0,
        )
        self.assertEqual(code, 200)
        self.assertEqual(data["mode"], "broadcast")
        self.assertGreaterEqual(data["sent"], 1)
        targets = [t for t, _ in sent]
        self.assertIn("U_bc_1", targets)
        self.assertNotIn("U_bc_blocked", targets)
        footer = sent[0][1]["contents"]["footer"]["contents"]
        self.assertEqual(footer[0]["action"]["data"], "action=checkin")

    def test_cron_skips_checked_in_but_broadcast_does_not(self):
        sent = []

        def fake_sender(token, to, message):
            sent.append(to)
            return {"ok": True}

        state = app.load_state(self.data_file)
        p = app.get_profile(state, "U_skip")
        p["history"] = ["2026-07-24"]
        p["last_check_in"] = "2026-07-24T08:00:00"
        p["reminder_times"] = ["00:00"]
        app.save_state(self.data_file, state)
        config = {
            "DATA_FILE": self.data_file,
            "LINE_CHANNEL_ACCESS_TOKEN": "x",
            "LINE_PUSH_SENDER": fake_sender,
            "CRON_NOW": datetime(2026, 7, 24, 12, 0, 0),
            "APP_TIMEZONE": "Asia/Taipei",
        }
        cron, code = app.send_checkin_reminders(config)
        self.assertEqual(code, 200)
        self.assertEqual(cron.get("sent", 0), 0)
        self.assertEqual(sent, [])

        bc, code2 = app.broadcast_checkin_reminders(config, pause_every=0)
        self.assertEqual(code2, 200)
        self.assertGreaterEqual(bc.get("sent", 0), 1)
        self.assertIn("U_skip", sent)

    def test_targeted_repush_only_sends_active_requested_members(self):
        sent = []

        def fake_sender(token, to, message):
            sent.append(to)
            return {"ok": True}

        state = app.load_state(self.data_file)
        baby = app.get_profile(state, "U_baby")
        baby.update({
            "plan": "paid_399_year",
            "membership_source": "beta",
            "beta_started_at": "2026-08-01T00:00:00",
            "beta_ends_at": "2026-08-22T00:00:00",
        })
        soft = app.get_profile(state, "U_soft")
        soft.update({"plan": "trial", "trial_started_at": "2026-08-01T00:00:00"})
        retired = app.get_profile(state, "U_jennie")
        retired.update({"plan": "trial", "membership_started_at": "2026-08-01T00:00:00"})
        app.save_state(self.data_file, state)

        data, code = app.send_targeted_checkin_repush(
            {
                "DATA_FILE": self.data_file,
                "LINE_CHANNEL_ACCESS_TOKEN": "x",
                "LINE_PUSH_SENDER": fake_sender,
                "CRON_NOW": datetime(2026, 8, 2, 12, 30, 0),
                "APP_TIMEZONE": "Asia/Taipei",
                "RETIRED_LINE_USER_IDS": "U_jennie",
            },
            ["U_baby", "U_soft", "U_jennie"],
        )

        self.assertEqual(code, 200)
        self.assertEqual(sent, ["U_baby", "U_soft"])
        self.assertEqual(data["sent"], 2)
        self.assertEqual(data["skipped_retired"], ["U_jennie"])


class CheckinPostbackStillLive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_file = os.path.join(self.tmp.name, "state.json")
        self.addCleanup(self.tmp.cleanup)

    def test_postback_still_writes_history(self):
        fixed = datetime(2026, 7, 25, 1, 26, 0)
        with mock.patch.object(app, "current_app_time", return_value=fixed):
            reply = app.handle_checkin_postback(self.data_file, "U_live_pb")
        if isinstance(reply, list):
            reply = "\n".join(str(x) if not isinstance(x, dict) else x.get("altText", "") for x in reply)
        self.assertIn("報平安成功", reply)
        self.assertIn("7/25（六）", reply)
        state = app.load_state(self.data_file)
        self.assertIn("2026-07-25", state["users"]["U_live_pb"].get("history") or [])


if __name__ == "__main__":
    unittest.main()
