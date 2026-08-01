import copy
import unittest
from datetime import datetime, timedelta

from push_management import (
    CampaignConflictError,
    cancel_campaign,
    create_campaign,
    ensure_push_state,
    finalize_campaign,
    mark_campaign_sending,
    prepare_campaign,
    schedule_campaign,
    update_campaign,
)


NOW = datetime(2026, 8, 1, 10, 0, 0)


class PushCampaignStateTests(unittest.TestCase):
    def test_ensure_push_state_adds_collections_without_changing_existing_data(self):
        state = {"users": {"U1": {"display_name": "小安"}}, "orders": [{"id": "O1"}]}
        original_users = copy.deepcopy(state["users"])
        original_orders = copy.deepcopy(state["orders"])

        hydrated = ensure_push_state(state)

        self.assertIs(hydrated, state)
        self.assertEqual(hydrated["users"], original_users)
        self.assertEqual(hydrated["orders"], original_orders)
        self.assertEqual(hydrated["push_campaigns"], [])
        self.assertEqual(hydrated["push_campaign_versions"], [])
        self.assertEqual(hydrated["push_delivery_records"], [])
        self.assertEqual(hydrated["push_campaign_events"], [])

    def test_app_hydration_adds_push_collections_idempotently(self):
        from app import _hydrate_state

        legacy = {
            "users": {"U1": {"display_name": "小安", "checkins": ["2026-08-01"]}},
            "orders": [{"id": "O1", "status": "paid"}],
            "notification_logs": [{"kind": "sos", "status": "sent"}],
        }

        first = _hydrate_state(copy.deepcopy(legacy), revision=7)
        second = _hydrate_state(copy.deepcopy(first), revision=7)

        for key in (
            "push_campaigns",
            "push_campaign_versions",
            "push_delivery_records",
            "push_campaign_events",
        ):
            self.assertIn(key, first)
            self.assertEqual(first[key], [])
        self.assertEqual(second, first)
        self.assertEqual(first["users"], legacy["users"])
        self.assertEqual(first["orders"], legacy["orders"])
        self.assertEqual(first["notification_logs"], legacy["notification_logs"])
        self.assertEqual(first["_state_revision"], 7)


class PushCampaignLifecycleTests(unittest.TestCase):
    def create_campaign(self, **overrides):
        state = {"users": {}}
        payload = {
            "name": "七日提醒",
            "content_type": "text",
            "text": "記得置頂每日平安",
        }
        payload.update(overrides)
        campaign = create_campaign(
            state,
            payload,
            actor="super_admin",
            now=NOW,
        )
        return state, campaign

    def test_create_campaign_starts_as_draft_and_creates_version_one(self):
        state, campaign = self.create_campaign()

        self.assertEqual(campaign["status"], "draft")
        self.assertEqual(campaign["current_version"], 1)
        self.assertEqual(len(state["push_campaign_versions"]), 1)
        version = state["push_campaign_versions"][0]
        self.assertEqual(version["campaign_id"], campaign["id"])
        self.assertEqual(version["name"], "七日提醒")
        self.assertEqual(version["created_by"], "super_admin")

    def test_update_appends_version_without_replacing_old_version(self):
        state, campaign = self.create_campaign()
        original = copy.deepcopy(state["push_campaign_versions"][0])

        updated = update_campaign(
            state,
            campaign["id"],
            {"text": "新版提醒"},
            actor="super_admin",
            now=NOW + timedelta(minutes=5),
        )

        self.assertEqual(state["push_campaign_versions"][0], original)
        self.assertEqual(len(state["push_campaign_versions"]), 2)
        self.assertEqual(updated["current_version"], 2)
        self.assertEqual(state["push_campaign_versions"][1]["text"], "新版提醒")

    def test_editing_scheduled_campaign_invalidates_schedule(self):
        state, campaign = self.create_campaign(plan_audiences=["paid_799"])
        prepare_campaign(state, campaign["id"], actor="super_admin", now=NOW)
        schedule_campaign(
            state,
            campaign["id"],
            scheduled_at=NOW + timedelta(hours=2),
            actor="super_admin",
            now=NOW,
        )

        updated = update_campaign(
            state,
            campaign["id"],
            {"text": "排程後修改"},
            actor="super_admin",
            now=NOW + timedelta(minutes=10),
        )

        self.assertEqual(updated["status"], "pending_schedule")
        self.assertIsNone(updated["scheduled_at"])
        self.assertEqual(updated["current_version"], 2)

    def test_campaign_cannot_be_edited_after_sending_starts(self):
        state, campaign = self.create_campaign(plan_audiences=["paid_799"])
        prepare_campaign(state, campaign["id"], actor="super_admin", now=NOW)
        schedule_campaign(
            state,
            campaign["id"],
            scheduled_at=NOW + timedelta(hours=1),
            actor="super_admin",
            now=NOW,
        )
        mark_campaign_sending(state, campaign["id"], now=NOW + timedelta(hours=1))

        with self.assertRaises(CampaignConflictError):
            update_campaign(
                state,
                campaign["id"],
                {"text": "不應寫入"},
                actor="super_admin",
                now=NOW + timedelta(hours=1, minutes=1),
            )

    def test_lifecycle_supports_success_partial_and_full_failure(self):
        expected = {
            (2, 0): "completed",
            (1, 1): "partially_failed",
            (0, 2): "fully_failed",
        }
        for (sent, failed), final_status in expected.items():
            with self.subTest(final_status=final_status):
                state, campaign = self.create_campaign(plan_audiences=["paid_799"])
                prepare_campaign(state, campaign["id"], actor="super_admin", now=NOW)
                schedule_campaign(
                    state,
                    campaign["id"],
                    scheduled_at=NOW + timedelta(hours=1),
                    actor="super_admin",
                    now=NOW,
                )
                mark_campaign_sending(state, campaign["id"], now=NOW + timedelta(hours=1))

                finished = finalize_campaign(
                    state,
                    campaign["id"],
                    sent_count=sent,
                    failed_count=failed,
                    now=NOW + timedelta(hours=1, minutes=1),
                )

                self.assertEqual(finished["status"], final_status)

    def test_cancel_is_allowed_before_sending_but_not_after(self):
        for starting_status in ("draft", "pending_schedule", "scheduled"):
            with self.subTest(starting_status=starting_status):
                state, campaign = self.create_campaign(plan_audiences=["paid_799"])
                if starting_status in {"pending_schedule", "scheduled"}:
                    prepare_campaign(state, campaign["id"], actor="super_admin", now=NOW)
                if starting_status == "scheduled":
                    schedule_campaign(
                        state,
                        campaign["id"],
                        scheduled_at=NOW + timedelta(hours=1),
                        actor="super_admin",
                        now=NOW,
                    )
                cancelled = cancel_campaign(
                    state,
                    campaign["id"],
                    reason_zh="最高管理員取消排程。",
                    actor="super_admin",
                    now=NOW,
                )
                self.assertEqual(cancelled["status"], "cancelled")

        state, campaign = self.create_campaign(plan_audiences=["paid_799"])
        prepare_campaign(state, campaign["id"], actor="super_admin", now=NOW)
        schedule_campaign(
            state,
            campaign["id"],
            scheduled_at=NOW + timedelta(hours=1),
            actor="super_admin",
            now=NOW,
        )
        mark_campaign_sending(state, campaign["id"], now=NOW + timedelta(hours=1))
        with self.assertRaises(CampaignConflictError):
            cancel_campaign(
                state,
                campaign["id"],
                reason_zh="太晚取消",
                actor="super_admin",
                now=NOW + timedelta(hours=1),
            )


if __name__ == "__main__":
    unittest.main()
