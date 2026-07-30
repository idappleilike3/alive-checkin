import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import app


ROOT = Path(__file__).resolve().parents[1]


class BetaSelfRegistrationTests(unittest.TestCase):
    def test_active_paid_member_cannot_be_changed_to_beta(self):
        state = {
            "users": {
                "U-jennie": {
                    "line_user_id": "U-jennie",
                    "plan": "paid_799_year",
                    "membership_source": "paid",
                    "payment_status": "active",
                    "paid_until": "2027-07-24T15:54:00",
                }
            }
        }

        with self.assertRaisesRegex(ValueError, "paid_member_not_beta_eligible"):
            app.assign_beta_cohort(
                state,
                "U-jennie",
                "B799",
                now=datetime(2026, 7, 30, 19, 0, 0),
            )

    def test_claim_beta_link_assigns_399_yearly_entitlements_for_21_days(self):
        state = {"users": {"U-member": {"line_user_id": "U-member", "plan": "trial"}}}
        result = app.claim_beta_link(
            state,
            "U-member",
            "B399",
            now=datetime(2026, 7, 27, 12, 0, 0),
        )

        profile = state["users"]["U-member"]
        self.assertTrue(result["assigned"])
        self.assertEqual(profile["beta_cohort"], "B399")
        self.assertEqual(profile["plan"], "paid_399_year")
        self.assertEqual(profile["beta_ends_at"], "2026-08-17T12:00:00")

    def test_claim_beta_link_assigns_799_yearly_entitlements_for_21_days(self):
        state = {"users": {"U-member": {"line_user_id": "U-member", "plan": "trial"}}}
        result = app.claim_beta_link(
            state,
            "U-member",
            "B799",
            now=datetime(2026, 7, 27, 12, 0, 0),
        )

        profile = state["users"]["U-member"]
        self.assertTrue(result["assigned"])
        self.assertEqual(profile["plan"], "paid_799_year")
        self.assertEqual(profile["beta_ends_at"], "2026-08-17T12:00:00")

    def test_claim_beta_link_rejects_when_399_is_full(self):
        users = {}
        for index in range(20):
            profile = {"line_user_id": f"U-{index}", "plan": "trial"}
            profile.update(
                {
                    "membership_source": "beta",
                    "beta_cohort": "B399",
                    "beta_started_at": "2026-07-27T12:00:00",
                    "beta_ends_at": "2026-08-17T12:00:00",
                    "beta_revoked_at": None,
                }
            )
            users[f"U-{index}"] = profile
        users["U-new"] = {"line_user_id": "U-new", "plan": "trial"}

        with self.assertRaisesRegex(ValueError, "cohort_full"):
            app.claim_beta_link(
                {"users": users},
                "U-new",
                "B399",
                now=datetime(2026, 7, 27, 12, 0, 0),
            )

    def test_claim_is_idempotent_and_cannot_switch_groups(self):
        state = {"users": {"U-member": {"line_user_id": "U-member", "plan": "trial"}}}
        first = app.claim_beta_link(state, "U-member", "B799")
        second = app.claim_beta_link(state, "U-member", "B799")
        self.assertTrue(first["assigned"])
        self.assertTrue(second["idempotent"])
        with self.assertRaisesRegex(ValueError, "already_in_other_cohort"):
            app.claim_beta_link(state, "U-member", "B399")

    def test_public_trial_user_can_upgrade_to_beta_without_reentering_profile_data(self):
        state = {
            "users": {
                "U-trial": {
                    "line_user_id": "U-trial",
                    "plan": "trial",
                    "membership_source": "public_trial",
                    "free_eligibility_source": "public_trial",
                    "free_eligibility_used_at": "2026-07-01T12:00:00",
                    "contacts": [{"id": "guardian-1", "name": "女兒"}],
                    "daily_reminder_times": ["09:00"],
                }
            }
        }

        result = app.claim_beta_link(
            state,
            "U-trial",
            "B799",
            now=datetime(2026, 7, 27, 12, 0, 0),
        )

        profile = state["users"]["U-trial"]
        self.assertTrue(result["assigned"])
        self.assertEqual(profile["plan"], "paid_799_year")
        self.assertEqual(profile["membership_source"], "beta")
        self.assertEqual(profile["beta_cohort"], "B799")
        self.assertEqual(profile["contacts"], [{"id": "guardian-1", "name": "女兒"}])
        self.assertEqual(profile["daily_reminder_times"], ["09:00"])

    def test_beta_registration_claims_first_free_eligibility_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_file = str(Path(tmp) / "state.json")
            result, code = app.register_line_user(
                data_file,
                {
                    "line_user_id": "U-beta-new",
                    "display_name": "封測者",
                    "beta_cohort": "B799",
                },
            )

            self.assertEqual(code, 200)
            saved = app.load_state(data_file)["users"]["U-beta-new"]
            self.assertEqual(result["beta_cohort"], "B799")
            self.assertEqual(saved["membership_source"], "beta")
            self.assertEqual(saved["free_eligibility_source"], "beta_B799")
            self.assertTrue(saved["free_eligibility_used_at"])
            self.assertFalse(
                app.ensure_membership_trial(
                    saved,
                    now=datetime(2026, 8, 18, 12, 0, 0),
                    source="public_trial",
                )
            )

    def test_existing_trial_member_clicking_799_beta_keeps_guardian_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_file = str(Path(tmp) / "state.json")
            app.register_line_user(
                data_file,
                {"line_user_id": "U-trial-upgrade", "display_name": "體驗者"},
            )
            state = app.load_state(data_file)
            state["users"]["U-trial-upgrade"]["contacts"] = [
                {"id": "guardian-1", "name": "女兒", "line_user_id": "U-daughter"}
            ]
            state["users"]["U-trial-upgrade"]["daily_reminder_times"] = ["08:30"]
            app.save_state(data_file, state)

            result, code = app.register_line_user(
                data_file,
                {
                    "line_user_id": "U-trial-upgrade",
                    "display_name": "體驗者",
                    "beta_cohort": "B799",
                },
            )

            saved = app.load_state(data_file)["users"]["U-trial-upgrade"]
            self.assertEqual(code, 200)
            self.assertEqual(result["plan"], "paid_799_year")
            self.assertEqual(result["membership_source"], "beta")
            self.assertEqual(saved["beta_cohort"], "B799")
            self.assertEqual(saved["contacts"][0]["line_user_id"], "U-daughter")
            self.assertEqual(saved["daily_reminder_times"], ["08:30"])

    def test_public_links_and_liff_claim_hook_are_present(self):
        backend = (ROOT / "app.py").read_text(encoding="utf-8")
        page = (ROOT / "beta-register.html").read_text(encoding="utf-8")
        member = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn('@app.get("/beta/399")', backend)
        self.assertIn('@app.get("/beta/799")', backend)
        self.assertIn("21天安心守護體驗", page)
        self.assertNotIn("399 年費安心版｜21 天封測", page)
        self.assertNotIn("799 年費守護版｜21 天封測", page)
        self.assertIn("本次體驗，你可以使用：", page)
        self.assertIn("封測期間需要做什麼？", page)
        self.assertIn("beta_cohort", member)
        self.assertIn('beta_cohort: betaCohort', member)
        self.assertNotIn('fetch("/api/beta/claim"', member)

    def test_guardian_trial_is_optional_and_mutual_binding_still_requires_consent(self):
        member = (ROOT / "index.html").read_text(encoding="utf-8")
        backend = (ROOT / "app.py").read_text(encoding="utf-8")

        self.assertIn("activateOwnTrialAfterGuardianBind", member)
        self.assertIn("要不要使用 14 天免費體驗", member)
        self.assertNotIn("您的 14 天免費體驗已自動開通", member)
        self.assertIn("activate_trial", member)
        self.assertIn('activate_trial = bool(payload.get("activate_trial"))', backend)
        self.assertIn("reciprocal = False", backend)
        self.assertIn("申請 14 天體驗也不自動互綁", backend)


if __name__ == "__main__":
    unittest.main()
