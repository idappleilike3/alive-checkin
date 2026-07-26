import unittest
from datetime import datetime, timedelta

import app as app_module


class LaunchReadinessTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.fromisoformat("2026-07-27T12:00:00")
        self.state = {
            "launch_metrics": {
                "checkin_attempts": 100,
                "checkin_successes": 99,
                "required_reminders": 40,
                "sent_required_reminders": 40,
                "duplicate_alerts": 0,
                "sos_tests": 10,
                "sos_test_successes": 10,
                "guardian_bind_attempts": 20,
                "guardian_bind_successes": 19,
                "payment_flow_passed": True,
                "expiry_flow_passed": True,
            },
            "push_failures": [],
            "launch_validation_scenarios": {
                "PAY-ready": {
                    "kind": "payment",
                    "steps": sorted(
                        app_module.LAUNCH_SCENARIO_STEPS["payment"]
                    ),
                },
                "EXP-ready": {
                    "kind": "expiry",
                    "line_user_id": "U-ready",
                    "steps": sorted(
                        app_module.LAUNCH_SCENARIO_STEPS["expiry"]
                    ),
                },
            },
            "beta_release_history": [{
                "batch": "B",
                "count": 10,
                "released_at": (self.now - timedelta(days=1)).isoformat(),
            }],
        }

    def test_exact_thresholds_are_ready(self):
        result = app_module.launch_readiness_snapshot(self.state, self.now)
        self.assertEqual(result["checkin_success_rate"], 0.99)
        self.assertEqual(result["guardian_bind_success_rate"], 0.95)
        self.assertEqual(result["missed_required_reminders"], 0)
        self.assertEqual(result["duplicate_alerts"], 0)
        self.assertTrue(result["ready"])

    def test_critical_notification_miss_stops_release(self):
        self.state["launch_metrics"]["sent_required_reminders"] = 39
        self.state["push_failures"] = [{
            "category": "overdue",
            "critical": True,
            "reason": "LINE timeout",
        }]
        snapshot = app_module.launch_readiness_snapshot(self.state, self.now)
        allowed, reason = app_module.beta_release_allowed(
            self.state, 20, now=self.now
        )
        self.assertFalse(snapshot["ready"])
        self.assertTrue(snapshot["critical_notification_miss"])
        self.assertFalse(allowed)
        self.assertEqual(reason, "readiness_blocked")

    def test_second_batch_first_day_is_capped_at_ten(self):
        state = {
            "launch_metrics": self.state["launch_metrics"],
            "launch_validation_scenarios": self.state[
                "launch_validation_scenarios"
            ],
            "push_failures": [],
            "beta_release_history": [],
        }
        allowed, reason = app_module.beta_release_allowed(
            state, 20, now=self.now
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "first_release_max_10")
        self.assertTrue(app_module.beta_release_allowed(state, 10, now=self.now)[0])

    def test_remaining_twenty_require_later_day_and_green_gates(self):
        self.assertTrue(
            app_module.beta_release_allowed(self.state, 20, now=self.now)[0]
        )
        same_day = {
            **self.state,
            "beta_release_history": [{
                "batch": "B",
                "count": 10,
                "released_at": self.now.isoformat(),
            }],
        }
        self.assertEqual(
            app_module.beta_release_allowed(same_day, 20, now=self.now),
            (False, "wait_until_next_day"),
        )

    def test_admin_assignment_enforces_mature_a_and_first_day_ten_cap(self):
        state = {
            "users": {
                "U-a": {
                    "line_user_id": "U-a",
                    "membership_source": "beta",
                    "beta_cohort": "A",
                    "beta_started_at": (
                        self.now - timedelta(days=7)
                    ).isoformat(timespec="seconds"),
                },
                **{
                    f"U-b-{index}": {
                        "line_user_id": f"U-b-{index}",
                        "plan": "trial",
                    }
                    for index in range(11)
                },
            },
            "launch_metrics": dict(self.state["launch_metrics"]),
            "launch_validation_scenarios": dict(
                self.state["launch_validation_scenarios"]
            ),
            "push_failures": [],
        }
        for index in range(10):
            result = app_module.assign_beta_member_with_release_gate(
                state, f"U-b-{index}", "B399", now=self.now
            )
            self.assertTrue(result["assigned"])
        with self.assertRaisesRegex(ValueError, "wait_until_next_day"):
            app_module.assign_beta_member_with_release_gate(
                state, "U-b-10", "B799", now=self.now
            )

    def test_admin_assignment_blocks_unready_or_immature_second_batch(self):
        base = {
            "users": {
                "U-a": {
                    "line_user_id": "U-a",
                    "membership_source": "beta",
                    "beta_cohort": "A",
                    "beta_started_at": self.now.isoformat(timespec="seconds"),
                },
                "U-b": {"line_user_id": "U-b", "plan": "trial"},
            },
            "launch_metrics": dict(self.state["launch_metrics"]),
            "launch_validation_scenarios": dict(
                self.state["launch_validation_scenarios"]
            ),
            "push_failures": [],
        }
        with self.assertRaisesRegex(ValueError, "a_cohort_not_mature"):
            app_module.assign_beta_member_with_release_gate(
                base, "U-b", "B399", now=self.now
            )
        base["users"]["U-a"]["beta_started_at"] = (
            self.now - timedelta(days=7)
        ).isoformat(timespec="seconds")
        base["launch_metrics"]["checkin_successes"] = 98
        with self.assertRaisesRegex(ValueError, "readiness_blocked"):
            app_module.assign_beta_member_with_release_gate(
                base, "U-b", "B399", now=self.now
            )

    def test_authoritative_delivery_ledger_blocks_missing_and_duplicate(self):
        missing = {
            **self.state,
            "launch_delivery_events": {
                "checkin:U-1:slot": {
                    "kind": "checkin",
                    "expected": True,
                    "sent_count": 0,
                }
            },
        }
        missing_result = app_module.launch_readiness_snapshot(
            missing, self.now
        )
        self.assertEqual(missing_result["missed_required_reminders"], 1)
        self.assertTrue(missing_result["critical_notification_miss"])
        self.assertFalse(missing_result["ready"])

        duplicate = {
            **self.state,
            "launch_delivery_events": {
                "checkin:U-1:slot": {
                    "kind": "checkin",
                    "expected": True,
                    "sent_count": 2,
                }
            },
        }
        duplicate_result = app_module.launch_readiness_snapshot(
            duplicate, self.now
        )
        self.assertEqual(duplicate_result["duplicate_alerts"], 1)
        self.assertFalse(duplicate_result["ready"])

    def test_payment_and_expiry_gates_require_correlated_scenarios(self):
        state = {
            **self.state,
            "launch_validation_scenarios": {},
        }
        for step in ("success", "failure", "cancel", "callback_idempotent"):
            app_module.record_launch_validation_step(
                state, "PAY-1", "payment", step, now=self.now
            )
        app_module.record_launch_validation_step(
            state,
            "EXP-1",
            "expiry",
            "expired",
            line_user_id="U-1",
            now=self.now,
        )
        app_module.record_launch_validation_step(
            state,
            "EXP-2",
            "expiry",
            "paused",
            line_user_id="U-1",
            now=self.now,
        )
        incomplete = app_module.launch_readiness_snapshot(state, self.now)
        self.assertFalse(incomplete["payment_flow_passed"])
        self.assertFalse(incomplete["expiry_flow_passed"])

        app_module.record_launch_validation_step(
            state, "PAY-1", "payment", "order_synced", now=self.now
        )
        for step in ("paused", "renewed"):
            app_module.record_launch_validation_step(
                state,
                "EXP-1",
                "expiry",
                step,
                line_user_id="U-1",
                now=self.now,
            )
        complete = app_module.launch_readiness_snapshot(state, self.now)
        self.assertTrue(complete["payment_flow_passed"])
        self.assertTrue(complete["expiry_flow_passed"])

    def test_legacy_metrics_cannot_bypass_missing_scenarios(self):
        state = {
            **self.state,
            "launch_validation_scenarios": {},
        }
        result = app_module.launch_readiness_snapshot(state, self.now)
        self.assertFalse(result["payment_flow_passed"])
        self.assertFalse(result["expiry_flow_passed"])
        self.assertFalse(result["ready"])


if __name__ == "__main__":
    unittest.main()
