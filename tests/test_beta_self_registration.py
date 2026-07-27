import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import app


ROOT = Path(__file__).resolve().parents[1]


class BetaSelfRegistrationTests(unittest.TestCase):
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

    def test_public_trial_user_cannot_claim_beta_after_free_eligibility_was_used(self):
        state = {
            "users": {
                "U-trial": {
                    "line_user_id": "U-trial",
                    "plan": "trial",
                    "membership_source": "public_trial",
                    "free_eligibility_source": "public_trial",
                    "free_eligibility_used_at": "2026-07-01T12:00:00",
                }
            }
        }

        with self.assertRaisesRegex(ValueError, "free_eligibility_already_used"):
            app.claim_beta_link(
                state,
                "U-trial",
                "B399",
                now=datetime(2026, 7, 27, 12, 0, 0),
            )

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

    def test_public_links_and_liff_claim_hook_are_present(self):
        backend = (ROOT / "app.py").read_text(encoding="utf-8")
        page = (ROOT / "beta-register.html").read_text(encoding="utf-8")
        member = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn('@app.get("/beta/399")', backend)
        self.assertIn('@app.get("/beta/799")', backend)
        self.assertIn("399 安心版｜21 天封測", page)
        self.assertIn("799 守護版｜21 天封測", page)
        self.assertIn("年費版完整功能", page)
        self.assertIn("這 21 天請協助測試", page)
        self.assertIn("beta_cohort", member)
        self.assertIn('beta_cohort: betaCohort', member)
        self.assertNotIn('fetch("/api/beta/claim"', member)

    def test_guardian_trial_and_mutual_binding_are_explicit_opt_in(self):
        member = (ROOT / "index.html").read_text(encoding="utf-8")
        backend = (ROOT / "app.py").read_text(encoding="utf-8")

        self.assertIn("我也要免費體驗 14 天", member)
        self.assertIn("activate_trial", member)
        self.assertIn('activate_trial = bool(payload.get("activate_trial"))', backend)
        self.assertIn(
            "reciprocal = bool(pending_invite and (activate_trial or legacy_reciprocal))",
            backend,
        )


if __name__ == "__main__":
    unittest.main()
