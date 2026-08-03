import unittest
from datetime import datetime

import app


class FiveStepOnboardingAuditTests(unittest.TestCase):
    def test_snapshot_reports_each_of_five_steps_from_authoritative_facts(self):
        profile = {
            "line_user_id": "U-owner",
            "display_name": "Eros",
            "onboarding_reminder_configured": True,
            "contacts": [],
        }
        state = {
            "users": {"U-owner": profile},
            "guardian_invites": [{
                "id": "invite-1",
                "inviter_line_user_id": "U-owner",
                "invitee_line_user_id": "U-friend",
                "display_name": "朋友",
                "status": "pending",
                "created_at": "2026-08-04T10:00:00",
                "expires_at": "2026-08-11T10:00:00",
            }],
            "onboarding_events": [],
            "notification_logs": [],
        }

        progress = app.onboarding_progress_snapshot(
            state, profile, now=datetime(2026, 8, 4, 12, 0, 0)
        )

        self.assertEqual(progress["total_steps"], 5)
        self.assertEqual(progress["current_step"], 5)
        self.assertEqual(
            progress["completed_steps"],
            {"line_joined": True, "line_verified": True,
             "profile_saved": True, "invite_sent": True,
             "guardian_bound": False},
        )
        self.assertEqual(progress["binding_status"], "waiting_for_guardian")
        self.assertEqual(progress["latest_invitee_display_name"], "朋友")

    def test_event_ledger_is_idempotent_and_keeps_full_source_page(self):
        state = {"onboarding_events": []}
        when = datetime(2026, 8, 4, 10, 30, 15)

        first = app.append_onboarding_event(
            state, "U-owner", "profile_saved",
            source_page="/liff/onboarding.html", occurred_at=when,
            metadata={"plan": "beta_799"},
        )
        second = app.append_onboarding_event(
            state, "U-owner", "profile_saved",
            source_page="/liff/onboarding.html", occurred_at=when,
            metadata={"plan": "beta_799"},
        )

        self.assertEqual(first, second)
        self.assertEqual(len(state["onboarding_events"]), 1)
        self.assertEqual(first["source_page"], "/liff/onboarding.html")
        self.assertEqual(first["occurred_at"], "2026-08-04T10:30:15")
        self.assertEqual(first["plan"], "beta_799")


if __name__ == "__main__":
    unittest.main()
