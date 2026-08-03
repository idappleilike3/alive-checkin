import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import app


class FiveStepOnboardingReminderTests(unittest.TestCase):
    def make_state(self, profile, *, events=None, invites=None):
        handle = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        handle.close()
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        state = app._hydrate_state({
            "users": {profile["line_user_id"]: profile},
            "onboarding_events": events or [],
            "guardian_invites": invites or [],
            "notification_logs": [],
        })
        app.save_state(handle.name, state)
        return handle.name

    def run_reminders(self, data_file, now, sent):
        return app.send_onboarding_progress_reminders({
            "DATA_FILE": data_file,
            "LINE_CHANNEL_ACCESS_TOKEN": "token",
            "APP_PUBLIC_URL": "https://alive-checkin.example",
            "CRON_NOW": now,
            "LINE_PUSH_SENDER": (
                lambda _token, target, message: sent.append((target, message))
                or {"ok": True}
            ),
        })

    def test_unfilled_profile_is_reminded_on_days_1_3_5_7_without_catchup_burst(self):
        profile = {"line_user_id": "U-owner", "display_name": "Eros", "contacts": []}
        data_file = self.make_state(profile, events=[{
            "line_user_id": "U-owner",
            "event": "line_verified",
            "source_page": "/beta/799",
            "occurred_at": "2026-08-01T09:00:00",
        }])
        sent = []

        result, code = self.run_reminders(
            data_file, datetime(2026, 8, 4, 9, 5), sent
        )

        self.assertEqual(code, 200)
        self.assertEqual(result["sent"], 1)
        self.assertEqual(len(sent), 1)
        self.assertIn("完成會員資料", str(sent[0][1]))
        stored = app.load_state(data_file)
        log = stored["notification_logs"][-1]
        self.assertEqual(log["kind"], "onboarding_profile")
        self.assertEqual(log["workflow_step"], 3)
        self.assertEqual(log["due_day"], 3)
        self.assertTrue(log["message_full"])

        again, _ = self.run_reminders(
            data_file, datetime(2026, 8, 4, 9, 6), sent
        )
        self.assertEqual(again["sent"], 0)
        self.assertEqual(len(sent), 1)

    def test_saved_profile_without_invite_gets_invite_reminder_then_stops_after_invite(self):
        profile = {
            "line_user_id": "U-owner",
            "display_name": "Eros",
            "onboarding_reminder_configured": True,
            "contacts": [],
        }
        events = [{
            "line_user_id": "U-owner",
            "event": "profile_saved",
            "source_page": "/liff/onboarding.html",
            "occurred_at": "2026-08-03T10:00:00",
        }]
        data_file = self.make_state(profile, events=events)
        sent = []

        first, _ = self.run_reminders(
            data_file, datetime(2026, 8, 4, 10, 5), sent
        )
        self.assertEqual(first["sent"], 1)
        self.assertIn("一鍵邀請", str(sent[-1][1]))

        state = app.load_state(data_file)
        state["guardian_invites"] = [{
            "id": "invite-1",
            "inviter_line_user_id": "U-owner",
            "status": "pending",
            "created_at": "2026-08-04T11:00:00",
            "expires_at": "2026-08-11T11:00:00",
        }]
        app.save_state(data_file, state)
        stopped, _ = self.run_reminders(
            data_file, datetime(2026, 8, 5, 10, 5), sent
        )
        self.assertEqual(stopped["sent"], 0)

    def test_pending_invite_gets_confirmation_reminder_and_bound_member_gets_none(self):
        profile = {
            "line_user_id": "U-owner",
            "display_name": "Eros",
            "onboarding_reminder_configured": True,
            "contacts": [],
        }
        invite = {
            "id": "invite-1",
            "inviter_line_user_id": "U-owner",
            "display_name": "朋友",
            "status": "pending",
            "created_at": "2026-08-02T10:00:00",
            "expires_at": "2026-08-11T10:00:00",
        }
        data_file = self.make_state(profile, invites=[invite])
        sent = []

        pending, _ = self.run_reminders(
            data_file, datetime(2026, 8, 4, 10, 5), sent
        )
        self.assertEqual(pending["sent"], 1)
        self.assertIn("朋友", str(sent[-1][1]))
        self.assertIn("確認", str(sent[-1][1]))

        state = app.load_state(data_file)
        state["users"]["U-owner"]["contacts"] = [{
            "line_user_id": "U-friend",
            "contact_role": "guardian",
            "binding_status": "accepted",
            "consent_status": "accepted",
        }]
        app.save_state(data_file, state)
        bound, _ = self.run_reminders(
            data_file, datetime(2026, 8, 7, 10, 5), sent
        )
        self.assertEqual(bound["sent"], 0)

    def test_checkin_reminder_excludes_member_until_guardian_is_bound(self):
        profile = {
            "line_user_id": "U-owner",
            "display_name": "Eros",
            "plan": "paid_799",
            "payment_status": "active",
            "paid_until": "2026-09-01T00:00:00",
            "onboarding_reminder_configured": True,
            "daily_checkin_reminder_enabled": True,
            "reminder_time": "09:00",
            "contacts": [],
        }
        data_file = self.make_state(profile)
        sent = []
        result, code = app.send_checkin_reminders({
            "DATA_FILE": data_file,
            "LINE_CHANNEL_ACCESS_TOKEN": "token",
            "CRON_NOW": datetime(2026, 8, 4, 9, 1),
            "LINE_PUSH_SENDER": lambda *_args: sent.append(True) or {"ok": True},
        })
        self.assertEqual(code, 200)
        self.assertEqual(result["sent"], 0)
        self.assertEqual(sent, [])


if __name__ == "__main__":
    unittest.main()
