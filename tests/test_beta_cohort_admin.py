import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import app as app_module


class BetaCohortPolicyTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.fromisoformat("2026-07-27T12:00:00")
        self.state = {
            "users": {
                f"U-{index}": {
                    "line_user_id": f"U-{index}",
                    "display_name": f"測試者 {index}",
                    "plan": "trial",
                }
                for index in range(1, 45)
            },
            "orders": [],
        }

    def test_assigns_fixed_21_day_cohort_without_order(self):
        result = app_module.assign_beta_cohort(
            self.state, "U-1", "A", now=self.now, recruitment_source="friend"
        )
        profile = self.state["users"]["U-1"]
        self.assertTrue(result["assigned"])
        self.assertEqual(profile["membership_source"], "beta")
        self.assertEqual(profile["beta_cohort"], "A")
        self.assertEqual(profile["plan"], "paid_799")
        self.assertEqual(
            datetime.fromisoformat(profile["beta_ends_at"]) - self.now,
            timedelta(days=21),
        )
        self.assertEqual(profile["beta_recruitment_source"], "friend")
        self.assertEqual(self.state["orders"], [])

    def test_duplicate_assignment_is_idempotent(self):
        first = app_module.assign_beta_cohort(
            self.state, "U-1", "B399", now=self.now
        )
        second = app_module.assign_beta_cohort(
            self.state, "U-1", "B399", now=self.now + timedelta(days=1)
        )
        self.assertTrue(first["assigned"])
        self.assertFalse(second["assigned"])
        self.assertTrue(second["idempotent"])
        self.assertEqual(
            self.state["users"]["U-1"]["beta_started_at"],
            self.now.isoformat(timespec="seconds"),
        )

    def test_enforces_10_20_10_caps(self):
        for cohort, limit in app_module.BETA_COHORT_LIMITS.items():
            state = {
                "users": {
                    f"U-{index}": {"line_user_id": f"U-{index}", "plan": "trial"}
                    for index in range(limit + 1)
                }
            }
            for index in range(limit):
                app_module.assign_beta_cohort(
                    state, f"U-{index}", cohort, now=self.now
                )
            with self.assertRaisesRegex(ValueError, "cohort_full"):
                app_module.assign_beta_cohort(
                    state, f"U-{limit}", cohort, now=self.now
                )

    def test_revoke_restores_unsubscribed_state_without_deleting_data(self):
        app_module.assign_beta_cohort(self.state, "U-1", "B799", now=self.now)
        self.state["users"]["U-1"]["contacts"] = [{"name": "媽媽"}]
        result = app_module.revoke_beta_cohort(
            self.state, "U-1", now=self.now + timedelta(days=2)
        )
        profile = self.state["users"]["U-1"]
        self.assertTrue(result["revoked"])
        self.assertEqual(profile["membership_source"], "expired")
        self.assertEqual(profile["plan"], "free")
        self.assertEqual(profile["contacts"], [{"name": "媽媽"}])
        self.assertTrue(profile["beta_revoked_at"])

    def test_beta_access_requires_active_window_and_not_revoked(self):
        app_module.assign_beta_cohort(self.state, "U-1", "A", now=self.now)
        profile = self.state["users"]["U-1"]
        self.assertTrue(app_module.beta_access_active(profile, self.now))
        self.assertFalse(
            app_module.beta_access_active(profile, self.now + timedelta(days=22))
        )
        app_module.revoke_beta_cohort(
            self.state, "U-1", now=self.now + timedelta(days=1)
        )
        self.assertFalse(app_module.beta_access_active(profile, self.now))

    def test_expired_beta_never_falls_back_to_persistent_paid_plan(self):
        app_module.assign_beta_cohort(self.state, "U-1", "A", now=self.now)
        profile = self.state["users"]["U-1"]
        expired_at = self.now + timedelta(days=22)

        self.assertFalse(app_module.membership_access_active(profile, expired_at))
        self.assertEqual(
            app_module.effective_entitlement_plan(profile, expired_at),
            "free",
        )

    def test_active_a_beta_can_bind_799_group_without_order_until_expiry(self):
        with TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "data.json"
            app_module.assign_beta_cohort(
                self.state, "U-1", "A", now=self.now - timedelta(days=1)
            )
            app_module.save_state(data_file, self.state)

            result, code = app_module.bind_guardian_group(
                data_file, {"line_user_id": "U-1", "group_id": "C-family"}
            )

            self.assertEqual(code, 200)
            self.assertTrue(result["bound"])
            saved = app_module.load_state(data_file)["users"]["U-1"]
            self.assertIn("C-family", saved["guardian_group_ids"])
            self.assertFalse(
                app_module.guardian_group_entitlement_active(
                    saved, self.now + timedelta(days=20)
                )
            )

    def test_admin_concurrency_cannot_exceed_cohort_cap(self):
        with TemporaryDirectory() as temp_dir:
            data_file = Path(temp_dir) / "data.json"
            state = {
                "users": {
                    f"U-{index}": {
                        "line_user_id": f"U-{index}",
                        "plan": "trial",
                    }
                    for index in range(11)
                }
            }
            for index in range(9):
                app_module.assign_beta_cohort(
                    state, f"U-{index}", "A", now=self.now
                )
            app_module.save_state(data_file, state)

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(
                    lambda user_id: app_module.admin_assign_beta_member(
                        data_file,
                        {"line_user_id": user_id, "cohort": "A"},
                        now=self.now,
                    )[1],
                    ("U-9", "U-10"),
                ))

            self.assertEqual(sorted(results), [200, 409])
            saved = app_module.load_state(data_file)
            active = [
                profile for profile in saved["users"].values()
                if profile.get("beta_cohort") == "A"
                and not profile.get("beta_revoked_at")
            ]
            self.assertEqual(len(active), 10)


if __name__ == "__main__":
    unittest.main()
