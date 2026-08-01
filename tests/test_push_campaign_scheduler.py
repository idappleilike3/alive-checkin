import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app import (
    load_state,
    mutate_state_atomically,
    push_audience_code,
    save_state,
    send_due_push_campaigns,
)
from push_management import (
    claim_due_campaign,
    create_campaign,
    prepare_campaign,
    schedule_campaign,
)


SCHEDULED_AT = datetime(2026, 8, 2, 9, 0, 0)


def paid_member(uid, plan="paid_799"):
    return {
        "line_user_id": uid,
        "display_name": f"會員 {uid}",
        "plan": plan,
        "membership_source": "paid",
        "payment_status": "active",
        "paid_until": "2026-09-01T09:00:00",
    }


def scheduled_state(users, audiences=None, explicit=None):
    state = {"users": dict(users), "orders": [], "guardian_groups": {}}
    campaign = create_campaign(
        state,
        {
            "name": "排程測試",
            "content_type": "text",
            "text": "排程訊息",
            "plan_audiences": list(audiences or []),
            "explicit_member_ids": list(explicit or []),
        },
        actor="super_admin",
        now=SCHEDULED_AT - timedelta(hours=1),
    )
    prepare_campaign(
        state,
        campaign["id"],
        actor="super_admin",
        now=SCHEDULED_AT - timedelta(minutes=30),
        audience_classifier=push_audience_code,
    )
    schedule_campaign(
        state,
        campaign["id"],
        scheduled_at=SCHEDULED_AT,
        actor="super_admin",
        now=SCHEDULED_AT - timedelta(minutes=20),
    )
    return state, campaign["id"]


class RecordingSender:
    def __init__(self, behavior=None):
        self.calls = []
        self.behavior = behavior or (lambda _uid, _attempt: {"ok": True, "status": 200})
        self.attempts = {}

    def __call__(self, token, line_user_id, message, retry_key):
        attempt = self.attempts.get(line_user_id, 0) + 1
        self.attempts[line_user_id] = attempt
        self.calls.append(
            {
                "token": token,
                "line_user_id": line_user_id,
                "message": message,
                "retry_key": retry_key,
                "attempt": attempt,
            }
        )
        return self.behavior(line_user_id, attempt)


class FakeHttpError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.headers = {}


class PushCampaignSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_file = str(Path(self.temp_dir.name) / "state.json")

    def seed(self, users=None, audiences=None, explicit=None):
        state, campaign_id = scheduled_state(
            users or {"U1": paid_member("U1")},
            audiences=audiences if audiences is not None else ["paid_799"],
            explicit=explicit,
        )
        save_state(self.data_file, state)
        return campaign_id

    def config(self, sender):
        return {
            "DATA_FILE": self.data_file,
            "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
            "PUSH_CAMPAIGN_SENDER": sender,
        }

    def campaign(self, campaign_id):
        state = load_state(self.data_file)
        return state, next(row for row in state["push_campaigns"] if row["id"] == campaign_id)

    def test_sends_at_exact_schedule_time_and_keeps_recipient_snapshot(self):
        campaign_id = self.seed()
        sender = RecordingSender()

        result, code = send_due_push_campaigns(self.config(sender), now=SCHEDULED_AT)

        self.assertEqual(code, 200)
        self.assertEqual(result["completed"], 1)
        self.assertEqual(len(sender.calls), 1)
        state, campaign = self.campaign(campaign_id)
        self.assertEqual(campaign["status"], "completed")
        delivery = state["push_delivery_records"][0]
        self.assertEqual(delivery["recipient_display_name"], "會員 U1")
        self.assertEqual(delivery["line_user_id"], "U1")
        self.assertEqual(delivery["plan"], "paid_799")
        self.assertEqual(delivery["scheduled_at"], SCHEDULED_AT.isoformat(timespec="seconds"))
        self.assertEqual(delivery["status"], "sent")
        self.assertEqual(delivery["attempts"], 1)

    def test_sends_when_just_under_24_hours_late(self):
        self.seed()
        sender = RecordingSender()

        result, _ = send_due_push_campaigns(
            self.config(sender),
            now=SCHEDULED_AT + timedelta(hours=23, minutes=59, seconds=59),
        )

        self.assertEqual(result["completed"], 1)
        self.assertEqual(len(sender.calls), 1)

    def test_more_than_24_hours_late_is_cancelled_without_send(self):
        campaign_id = self.seed()
        sender = RecordingSender()

        result, _ = send_due_push_campaigns(
            self.config(sender),
            now=SCHEDULED_AT + timedelta(hours=24, seconds=1),
        )

        self.assertEqual(result["cancelled"], 1)
        self.assertEqual(sender.calls, [])
        state, campaign = self.campaign(campaign_id)
        self.assertEqual(campaign["status"], "cancelled")
        self.assertEqual(
            state["push_campaign_events"][-1]["reason_zh"],
            "已超過預定發送時間 24 小時，系統自動取消。",
        )

    def test_transient_failure_retries_three_times_with_same_retry_key(self):
        campaign_id = self.seed()

        def behavior(_uid, attempt):
            if attempt < 3:
                raise TimeoutError("LINE timeout")
            return {"ok": True, "status": 200}

        sender = RecordingSender(behavior)

        send_due_push_campaigns(self.config(sender), now=SCHEDULED_AT)

        self.assertEqual(len(sender.calls), 3)
        self.assertEqual(len({call["retry_key"] for call in sender.calls}), 1)
        state, campaign = self.campaign(campaign_id)
        self.assertEqual(campaign["status"], "completed")
        self.assertEqual(state["push_delivery_records"][0]["attempts"], 3)

    def test_permanent_line_400_is_not_retried_and_has_chinese_reason(self):
        campaign_id = self.seed()

        def behavior(_uid, _attempt):
            raise FakeHttpError(400, "Bad Request")

        sender = RecordingSender(behavior)

        send_due_push_campaigns(self.config(sender), now=SCHEDULED_AT)

        self.assertEqual(len(sender.calls), 1)
        state, campaign = self.campaign(campaign_id)
        self.assertEqual(campaign["status"], "fully_failed")
        delivery = state["push_delivery_records"][0]
        self.assertEqual(delivery["status"], "failed")
        self.assertIn("LINE", delivery["failure_reason_zh"])
        self.assertTrue(delivery["failure_action_zh"])

    def test_mixed_results_finish_as_partially_failed(self):
        users = {"U1": paid_member("U1"), "U2": paid_member("U2")}
        campaign_id = self.seed(users=users)

        def behavior(uid, _attempt):
            if uid == "U2":
                raise FakeHttpError(400, "blocked")
            return {"ok": True, "status": 200}

        sender = RecordingSender(behavior)

        send_due_push_campaigns(self.config(sender), now=SCHEDULED_AT)

        state, campaign = self.campaign(campaign_id)
        self.assertEqual(campaign["status"], "partially_failed")
        self.assertEqual(campaign["sent_count"], 1)
        self.assertEqual(campaign["failed_count"], 1)
        self.assertEqual(len(state["push_delivery_records"]), 2)

    def test_empty_send_time_audience_fails_without_calling_line(self):
        campaign_id = self.seed()
        state = load_state(self.data_file)
        state["users"]["U1"]["paid_until"] = "2026-08-01T00:00:00"
        save_state(self.data_file, state)
        sender = RecordingSender()

        send_due_push_campaigns(self.config(sender), now=SCHEDULED_AT)

        self.assertEqual(sender.calls, [])
        state, campaign = self.campaign(campaign_id)
        self.assertEqual(campaign["status"], "fully_failed")
        self.assertEqual(
            state["push_campaign_events"][-1]["reason_zh"],
            "發送當下沒有符合資格的收件人。",
        )

    def test_monthly_hard_stop_leaves_campaign_scheduled_without_sending(self):
        campaign_id = self.seed()
        state = load_state(self.data_file)
        state["notification_logs"] = [
            {"kind": "checkin", "status": "sent", "created_at": "2026-08-02T08:00:00"}
        ]
        save_state(self.data_file, state)
        sender = RecordingSender()
        config = self.config(sender)
        config["LINE_MONTHLY_MESSAGE_LIMIT"] = 1

        result, code = send_due_push_campaigns(config, now=SCHEDULED_AT)

        self.assertEqual(code, 200)
        self.assertEqual(result["blocked"], 1)
        self.assertEqual(result["block_reason"], "line_non_emergency_budget_hard_stop")
        self.assertEqual(sender.calls, [])
        saved_state, campaign = self.campaign(campaign_id)
        self.assertEqual(campaign["status"], "scheduled")
        self.assertEqual(
            campaign["budget_block_reason"],
            "line_non_emergency_budget_hard_stop",
        )
        self.assertEqual(saved_state["push_campaign_events"][-1]["event_type"], "budget_blocked")

    def test_live_clock_renews_campaign_lease_between_recipients(self):
        users = {"U1": paid_member("U1"), "U2": paid_member("U2")}
        self.seed(users=users)
        clock = [SCHEDULED_AT]
        competing_claims = []
        sender = RecordingSender()

        def behavior(_uid, attempt):
            if len(sender.calls) == 1:
                clock[0] = SCHEDULED_AT + timedelta(minutes=4)
            elif len(sender.calls) == 2:
                competing_claims.append(
                    mutate_state_atomically(
                        self.data_file,
                        lambda state: claim_due_campaign(
                            state,
                            SCHEDULED_AT + timedelta(minutes=8),
                            worker_id="worker-2",
                            audience_classifier=push_audience_code,
                        ),
                    )
                )
            return {"ok": True, "status": 200}

        sender.behavior = behavior
        config = self.config(sender)
        config["PUSH_CAMPAIGN_CLOCK"] = lambda: clock[0]

        result, _ = send_due_push_campaigns(config)

        self.assertEqual(result["completed"], 1)
        self.assertEqual(competing_claims, [None])

    def test_campaign_stops_at_monthly_limit_and_resumes_remaining_recipient(self):
        users = {"U1": paid_member("U1"), "U2": paid_member("U2")}
        campaign_id = self.seed(users=users)
        state = load_state(self.data_file)
        state["notification_logs"] = [
            {"kind": "checkin", "status": "sent", "created_at": "2026-08-02T08:00:00"}
        ]
        save_state(self.data_file, state)
        sender = RecordingSender()
        config = self.config(sender)
        config["LINE_MONTHLY_MESSAGE_LIMIT"] = 2

        first, _ = send_due_push_campaigns(config, now=SCHEDULED_AT)

        self.assertEqual(len(sender.calls), 1)
        self.assertEqual(first["blocked"], 1)
        state, campaign = self.campaign(campaign_id)
        self.assertEqual(campaign["status"], "sending")
        self.assertEqual(
            sorted(row["status"] for row in state["push_delivery_records"]),
            ["pending", "sent"],
        )

        config["LINE_MONTHLY_MESSAGE_LIMIT"] = 3
        second, _ = send_due_push_campaigns(
            config, now=SCHEDULED_AT + timedelta(minutes=6)
        )

        self.assertEqual(len(sender.calls), 2)
        self.assertEqual(second["completed"], 1)
        _state, campaign = self.campaign(campaign_id)
        self.assertEqual(campaign["status"], "completed")


class CampaignLeaseTests(unittest.TestCase):
    def test_active_lease_blocks_second_worker_and_expired_lease_can_be_recovered(self):
        state, campaign_id = scheduled_state(
            {"U1": paid_member("U1")}, audiences=["paid_799"]
        )

        first = claim_due_campaign(
            state,
            SCHEDULED_AT,
            worker_id="worker-1",
            audience_classifier=push_audience_code,
        )
        blocked = claim_due_campaign(
            state,
            SCHEDULED_AT + timedelta(minutes=1),
            worker_id="worker-2",
            audience_classifier=push_audience_code,
        )
        recovered = claim_due_campaign(
            state,
            SCHEDULED_AT + timedelta(minutes=6),
            worker_id="worker-2",
            audience_classifier=push_audience_code,
        )

        self.assertEqual(first["campaign_id"], campaign_id)
        self.assertIsNone(blocked)
        self.assertEqual(recovered["campaign_id"], campaign_id)
        self.assertTrue(recovered["recovered"])
        self.assertEqual(len(state["push_delivery_records"]), 1)


class CronIntegrationTests(unittest.TestCase):
    def test_cron_tick_always_reports_push_campaign_job(self):
        from app import run_cron_tick

        with tempfile.TemporaryDirectory() as temp:
            data_file = str(Path(temp) / "state.json")
            save_state(data_file, {"users": {}})

            result, code = run_cron_tick(
                {
                    "DATA_FILE": data_file,
                    "LINE_CHANNEL_ACCESS_TOKEN": "",
                    "CRON_NOW": SCHEDULED_AT,
                }
            )

        self.assertEqual(code, 200)
        self.assertIn("push_campaigns", result["tasks"])
        self.assertEqual(result["tasks"]["push_campaigns"]["status"], 200)


if __name__ == "__main__":
    unittest.main()
