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

    def test_active_trial_gets_199_entitlement(self):
        self.assertEqual(
            app_module.effective_entitlement_plan(self.profile, self.now),
            "paid_199",
        )
        self.assertEqual(
            app_module.plan_rules_for_effective_entitlement(self.profile, self.now)[
                "guardian_group_limit"
            ],
            0,
        )

    def test_trial_does_not_include_a_guardian_group_test(self):
        first = app_module.claim_trial_group_test(
            self.profile, "C-family", now=self.now
        )
        self.assertFalse(first["claimed"])
        self.assertEqual(first["reason"], "not_eligible")

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
                app_module.PLAN_LIMITS["paid_199"]["daily_reminders"],
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
            self.assertEqual(code, 403)
            self.assertEqual(result["required_plan"], "paid_799")

    def test_parallel_trial_group_binds_are_both_rejected(self):
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
            self.assertEqual(sorted(codes), [403, 403])
            state = app_module.load_state(data_file)
            self.assertEqual(len(state.get("guardian_groups") or {}), 0)

    def test_trial_group_request_does_not_create_delivery_state(self):
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
            self.assertEqual(first_code, 403)
            self.assertEqual(first["required_plan"], "paid_799")
            state = app_module.load_state(data_file)
            self.assertNotIn(
                "trial_group_test_delivery",
                state["users"]["U-owner"],
            )


if __name__ == "__main__":
    unittest.main()
