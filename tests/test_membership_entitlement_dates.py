import copy
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app import (
    admin_summary,
    admin_update_user_plan,
    apply_admin_entitlement_change,
    backfill_membership_expiry_reviews,
    load_state,
    save_state,
)


NOW = datetime(2026, 8, 1, 15, 30, 0)


def profile_fixture(**overrides):
    profile = {
        "line_user_id": "U-member",
        "display_name": "寶寶",
        "plan": "trial",
        "membership_source": "public_trial",
        "payment_status": "trial",
        "paid_until": "",
        "history": ["2026-07-26", "2026-08-01"],
        "checkin_records": [
            {"date": "2026-07-26", "status": "safe"},
            {"date": "2026-08-01", "status": "safe"},
        ],
        "streak": 7,
        "level": 3,
        "experience": 880,
        "contacts": [{"name": "媽媽"}],
        "friends": ["U-friend"],
        "guardian_group_ids": ["G-family"],
    }
    profile.update(overrides)
    return profile


class PaidEntitlementDateTests(unittest.TestCase):
    def assert_progress_unchanged(self, before, after):
        for key in ("history", "checkin_records", "streak", "level", "experience"):
            self.assertEqual(after[key], before[key], key)

    def test_paid_399_to_paid_799_restarts_full_month(self):
        profile = profile_fixture(
            plan="paid_399",
            membership_source="paid",
            payment_status="active",
            paid_until="2026-08-20T10:00:00",
        )
        before = copy.deepcopy(profile)

        changed = apply_admin_entitlement_change(
            profile,
            {"plan": "paid_799"},
            effective_at=NOW,
            actor="super_admin",
        )

        self.assertEqual(changed["paid_until"], "2026-08-31T15:30:00")
        self.assertEqual(changed["membership_started_at"], "2026-08-01T15:30:00")
        self.assertEqual(changed["previous_plan"], "paid_399")
        self.assert_progress_unchanged(before, changed)

    def test_trial_to_yearly_paid_restarts_365_days(self):
        profile = profile_fixture(trial_started_at="2026-07-20T09:00:00")

        changed = apply_admin_entitlement_change(
            profile,
            {"plan": "paid_799_year"},
            effective_at=datetime(2026, 8, 1, 12, 0, 0),
            actor="super_admin",
        )

        self.assertEqual(changed["paid_until"], "2027-08-01T12:00:00")
        self.assertEqual(changed["billing_cycle"], "yearly")

    def test_saving_same_active_paid_plan_does_not_extend_it(self):
        profile = profile_fixture(
            plan="paid_799",
            membership_source="paid",
            payment_status="active",
            paid_until="2026-08-20T10:00:00",
        )

        changed = apply_admin_entitlement_change(
            profile,
            {"plan": "paid_799"},
            effective_at=NOW,
            actor="super_admin",
        )

        self.assertEqual(changed["paid_until"], "2026-08-20T10:00:00")


class BetaAndGiftEntitlementTests(unittest.TestCase):
    def test_existing_beta_switch_retains_original_beta_dates(self):
        profile = profile_fixture(
            plan="paid_399_year",
            membership_source="beta",
            payment_status="beta",
            beta_cohort="B399",
            beta_started_at="2026-07-25T09:00:00",
            beta_ends_at="2026-08-15T09:00:00",
        )

        changed = apply_admin_entitlement_change(
            profile,
            {"plan": "beta_B799"},
            effective_at=NOW,
            actor="super_admin",
        )

        self.assertEqual(changed["plan"], "paid_799_year")
        self.assertEqual(changed["beta_cohort"], "B799")
        self.assertEqual(changed["beta_started_at"], "2026-07-25T09:00:00")
        self.assertEqual(changed["beta_ends_at"], "2026-08-15T09:00:00")

    def test_g799_requires_explicit_valid_start_and_end(self):
        for payload in (
            {"plan": "G799"},
            {
                "plan": "G799",
                "gift_started_at": "2026-08-10T00:00:00",
                "gift_ends_at": "2026-08-01T00:00:00",
            },
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    apply_admin_entitlement_change(
                        profile_fixture(), payload, effective_at=NOW, actor="super_admin"
                    )

    def test_g799_uses_explicit_dates_without_creating_billing_cycle(self):
        changed = apply_admin_entitlement_change(
            profile_fixture(),
            {
                "plan": "G799",
                "gift_started_at": "2026-08-03T09:00:00",
                "gift_ends_at": "2027-01-15T18:00:00",
            },
            effective_at=NOW,
            actor="super_admin",
        )

        self.assertEqual(changed["plan"], "paid_799_year")
        self.assertEqual(changed["membership_source"], "gift")
        self.assertEqual(changed["gift_code"], "G799")
        self.assertEqual(changed["gift_started_at"], "2026-08-03T09:00:00")
        self.assertEqual(changed["gift_ends_at"], "2027-01-15T18:00:00")
        self.assertEqual(changed["paid_until"], "2027-01-15T18:00:00")
        self.assertEqual(changed["billing_cycle"], "gift")
        self.assertFalse(changed["auto_renew_enabled"])


class LegacyExpiryReviewTests(unittest.TestCase):
    def test_backfill_uses_latest_trustworthy_paid_order(self):
        state = {
            "users": {
                "U1": profile_fixture(
                    line_user_id="U1",
                    plan="paid_399",
                    membership_source="paid",
                    payment_status="active",
                    paid_until="",
                )
            },
            "orders": [
                {
                    "line_user_id": "U1",
                    "plan": "paid_399",
                    "status": "paid",
                    "paid_at": "2026-07-20T08:00:00",
                }
            ],
        }

        result = backfill_membership_expiry_reviews(state, now=NOW)

        self.assertEqual(result["backfilled"], 1)
        self.assertEqual(state["users"]["U1"]["paid_until"], "2026-08-19T08:00:00")
        self.assertFalse(state["users"]["U1"]["expiry_review_required"])

    def test_backfill_flags_missing_evidence_instead_of_guessing(self):
        state = {
            "users": {
                "U1": profile_fixture(
                    line_user_id="U1",
                    plan="paid_799_year",
                    membership_source="paid",
                    payment_status="active",
                    paid_until="",
                )
            },
            "orders": [],
        }

        result = backfill_membership_expiry_reviews(state, now=NOW)

        self.assertEqual(result["review_required"], 1)
        self.assertEqual(state["users"]["U1"]["paid_until"], "")
        self.assertTrue(state["users"]["U1"]["expiry_review_required"])


class AdminPlanUpdateIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_file = str(Path(self.temp_dir.name) / "state.json")

    def seed(self, profile, orders=None):
        save_state(
            self.data_file,
            {
                "users": {profile["line_user_id"]: profile},
                "orders": list(orders or []),
                "guardian_groups": {},
            },
        )

    def test_admin_update_restarts_paid_expiry_and_preserves_progress(self):
        original = profile_fixture(
            plan="paid_399",
            membership_source="paid",
            payment_status="active",
            paid_until="2026-08-20T10:00:00",
        )
        self.seed(original)

        result, code = admin_update_user_plan(
            self.data_file,
            {"line_user_id": "U-member", "plan": "paid_799"},
            effective_at=NOW,
            actor="super_admin",
        )

        self.assertEqual(code, 200)
        self.assertEqual(result["paid_until"], "2026-08-31T15:30:00")
        saved = load_state(self.data_file)["users"]["U-member"]
        self.assertEqual(saved["history"], original["history"])
        self.assertEqual(saved["checkin_records"], original["checkin_records"])
        self.assertEqual(saved["streak"], original["streak"])
        self.assertEqual(saved["level"], original["level"])

    def test_admin_g799_does_not_create_order(self):
        self.seed(profile_fixture())

        result, code = admin_update_user_plan(
            self.data_file,
            {
                "line_user_id": "U-member",
                "plan": "G799",
                "gift_started_at": "2026-08-03T09:00:00",
                "gift_ends_at": "2027-01-15T18:00:00",
            },
            effective_at=NOW,
            actor="super_admin",
        )

        self.assertEqual(code, 200)
        self.assertEqual(result["membership_source"], "gift")
        state = load_state(self.data_file)
        self.assertEqual(state["orders"], [])
        self.assertEqual(state["users"]["U-member"]["gift_code"], "G799")

    def test_admin_returns_400_for_invalid_gift_dates(self):
        self.seed(profile_fixture())

        result, code = admin_update_user_plan(
            self.data_file,
            {"line_user_id": "U-member", "plan": "G799"},
            effective_at=NOW,
            actor="super_admin",
        )

        self.assertEqual(code, 400)
        self.assertEqual(result["error"], "invalid membership change")

    def test_admin_summary_exposes_expiry_review_and_gift_fields(self):
        profile = profile_fixture(
            plan="paid_799_year",
            membership_source="paid",
            payment_status="active",
            paid_until="",
        )
        self.seed(profile)

        summary = admin_summary(self.data_file, now=NOW)

        member = next(row for row in summary["users"] if row["line_user_id"] == "U-member")
        self.assertTrue(member["expiry_review_required"])
        self.assertEqual(member["gift_code"], "")
        self.assertEqual(member["gift_started_at"], "")
        self.assertEqual(member["gift_ends_at"], "")


if __name__ == "__main__":
    unittest.main()
