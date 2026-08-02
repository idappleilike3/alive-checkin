import os
import tempfile
import unittest
from datetime import datetime, timedelta

import app


class MilestoneMediaDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_file = os.path.join(self.tmp.name, "state.json")

    def _config(self, sender, now):
        return {
            "DATA_FILE": self.data_file,
            "LINE_CHANNEL_ACCESS_TOKEN": "token",
            "LINE_PUSH_SENDER": sender,
            "CRON_NOW": now,
            "APP_TIMEZONE": "Asia/Taipei",
            "MILESTONE_VIDEO_100_URL": "https://cdn.example/day-100.mp4",
            "MILESTONE_VIDEO_365_URL": "https://cdn.example/day-365.mp4",
        }

    def _member_with_streak(self, uid, now, days):
        state = app.load_state(self.data_file)
        profile = app.get_profile(state, uid)
        profile["history"] = [
            (now.date() - timedelta(days=offset)).isoformat()
            for offset in range(days)
        ]
        app.save_state(self.data_file, state)

    def test_success_is_permanently_deduplicated(self):
        now = datetime(2026, 8, 2, 12)
        self._member_with_streak("U_member", now, 100)
        sent = []
        sender = lambda token, uid, message: sent.append((uid, message)) or {"ok": True}

        first, code = app.send_due_streak_milestone_videos(self._config(sender, now))
        second, code2 = app.send_due_streak_milestone_videos(self._config(sender, now))

        self.assertEqual((code, code2), (200, 200))
        self.assertEqual((first["sent"], second["sent"]), (1, 0))
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][1]["type"], "video")
        self.assertEqual(sent[0][1]["originalContentUrl"], "https://cdn.example/day-100.mp4")

    def test_failure_is_not_completed_and_next_tick_retries(self):
        now = datetime(2026, 8, 2, 12)
        self._member_with_streak("U_retry", now, 100)
        attempts = []

        def sender(token, uid, message):
            attempts.append(uid)
            if len(attempts) == 1:
                raise TimeoutError("temporary")
            return {"ok": True}

        first, _ = app.send_due_streak_milestone_videos(self._config(sender, now))
        next_day = now + timedelta(days=1)
        state = app.load_state(self.data_file)
        state["users"]["U_retry"]["history"].append(next_day.date().isoformat())
        app.save_state(self.data_file, state)
        second, _ = app.send_due_streak_milestone_videos(
            self._config(sender, next_day)
        )
        self.assertEqual(first["failed"], 1)
        self.assertEqual(second["sent"], 1)
        self.assertEqual(attempts, ["U_retry", "U_retry"])

    def test_missing_video_url_skips_without_marking_complete(self):
        now = datetime(2026, 8, 2, 12)
        self._member_with_streak("U_missing", now, 365)
        calls = []
        config = self._config(lambda *args: calls.append(args), now)
        config["MILESTONE_VIDEO_365_URL"] = ""
        result, code = app.send_due_streak_milestone_videos(config)
        self.assertEqual(code, 200)
        self.assertEqual(result["missing_media"], 1)
        self.assertEqual(calls, [])

    def test_guardian_contacts_never_receive_member_video(self):
        now = datetime(2026, 8, 2, 12)
        self._member_with_streak("U_owner", now, 100)
        state = app.load_state(self.data_file)
        state["users"]["U_owner"]["contacts"] = [
            {"line_user_id": "U_guardian", "contact_role": "core_guardian"}
        ]
        app.save_state(self.data_file, state)
        targets = []
        sender = lambda token, uid, message: targets.append(uid) or {"ok": True}
        app.send_due_streak_milestone_videos(self._config(sender, now))
        self.assertEqual(targets, ["U_owner"])


if __name__ == "__main__":
    unittest.main()
