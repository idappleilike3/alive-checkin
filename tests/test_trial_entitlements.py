import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import app as app_module


class TrialEntitlementTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.fromisoformat("2026-07-27T12:00:00")
        self.profile = {
            "line_user_id": "U-trial",
            "plan": "trial",
            "membership_source": "public_trial",
            "trial_started_at": self.now.isoformat(timespec="seconds"),
            "trial_end": (self.now + timedelta(days=14)).isoformat(timespec="seconds"),
        }

    def test_active_trial_gets_399_core_entitlement_not_799(self):
        self.assertEqual(
            app_module.effective_entitlement_plan(self.profile, self.now),
            "paid_399",
        )
        self.assertEqual(
            app_module.plan_rules_for_effective_entitlement(self.profile, self.now)[
                "guardian_group_limit"
            ],
            0,
        )

    def test_trial_may_claim_exactly_one_labeled_group_test(self):
        first = app_module.claim_trial_group_test(
            self.profile, "C-family", now=self.now
        )
        second = app_module.claim_trial_group_test(
            self.profile, "C-other", now=self.now + timedelta(minutes=1)
        )
        self.assertTrue(first["claimed"])
        self.assertTrue(first["message"].startswith("這是測試通知"))
        self.assertFalse(second["claimed"])
        self.assertEqual(second["reason"], "already_used")

    def test_labeled_test_actions_are_two_per_day_and_ten_minutes_apart(self):
        first = app_module.consume_labeled_test_action(
            self.profile, "sos", now=self.now
        )
        too_soon = app_module.consume_labeled_test_action(
            self.profile, "sos", now=self.now + timedelta(minutes=5)
        )
        second = app_module.consume_labeled_test_action(
            self.profile, "sos", now=self.now + timedelta(minutes=10)
        )
        third = app_module.consume_labeled_test_action(
            self.profile, "sos", now=self.now + timedelta(minutes=20)
        )
        self.assertTrue(first["allowed"])
        self.assertEqual(too_soon["reason"], "cooldown")
        self.assertTrue(second["allowed"])
        self.assertEqual(third["reason"], "daily_limit")

    def test_production_plan_rules_and_group_bind_use_bounded_trial_overlay(self):
        with TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "data.json"
            profile = {
                **self.profile,
                "line_user_id": "U-owner",
                "guardian_group_ids": [],
            }
            app_module.save_state(data_file, {"users": {"U-owner": profile}})

            self.assertEqual(
                app_module.plan_rules(profile)["daily_reminders"],
                app_module.PLAN_LIMITS["paid_399"]["daily_reminders"],
            )
            self.assertEqual(
                app_module.plan_rules(profile)["guardian_group_limit"], 0
            )
            result, code = app_module.bind_guardian_group(
                data_file,
                {
                    "line_user_id": "U-owner",
                    "group_id": "C-test",
                    "trial_test": True,
                },
            )
            self.assertEqual(code, 200)
            self.assertTrue(result["trial_test"])
            self.assertIn("這是測試通知", result["trial_test_message"])
            second, second_code = app_module.bind_guardian_group(
                data_file,
                {
                    "line_user_id": "U-owner",
                    "group_id": "C-test-2",
                    "trial_test": True,
                },
            )
            self.assertEqual(second_code, 409)
            self.assertEqual(second["error"], "trial_group_test_already_used")

    def test_parallel_trial_group_binds_claim_only_one_test(self):
        with TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "data.json"
            app_module.save_state(data_file, {
                "users": {
                    "U-owner": {
                        **self.profile,
                        "line_user_id": "U-owner",
                        "guardian_group_ids": [],
                    }
                }
            })
            with ThreadPoolExecutor(max_workers=2) as pool:
                codes = list(pool.map(
                    lambda group_id: app_module.bind_guardian_group(
                        data_file,
                        {
                            "line_user_id": "U-owner",
                            "group_id": group_id,
                            "trial_test": True,
                        },
                    )[1],
                    ("C-one", "C-two"),
                ))
            self.assertEqual(sorted(codes), [200, 409])
            state = app_module.load_state(data_file)
            self.assertEqual(len(state.get("guardian_groups") or {}), 1)

    def test_failed_trial_group_delivery_is_retryable_with_same_key(self):
        with TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "data.json"
            app_module.save_state(data_file, {
                "users": {
                    "U-owner": {
                        **self.profile,
                        "line_user_id": "U-owner",
                        "guardian_group_ids": [],
                    }
                }
            })
            first, first_code = app_module.bind_guardian_group(
                data_file,
                {
                    "line_user_id": "U-owner",
                    "group_id": "C-test",
                    "trial_test": True,
                },
            )
            state = app_module.load_state(data_file)
            delivery = state["users"]["U-owner"]["trial_group_test_delivery"]
            original_key = delivery["retry_key"]
            delivery["status"] = "failed"
            app_module.save_state(data_file, state)

            retry, retry_code = app_module.bind_guardian_group(
                data_file,
                {
                    "line_user_id": "U-owner",
                    "group_id": "C-test",
                    "trial_test": True,
                },
            )

            self.assertEqual((first_code, retry_code), (200, 200))
            self.assertTrue(retry["trial_test_recovered"])
            self.assertEqual(retry["trial_test_retry_key"], original_key)
            self.assertEqual(
                first["trial_test_retry_key"], retry["trial_test_retry_key"]
            )


if __name__ == "__main__":
    unittest.main()
