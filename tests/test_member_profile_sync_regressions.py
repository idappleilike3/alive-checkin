import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import app


ROOT = Path(__file__).resolve().parents[1]


class MemberProfileSyncRegressionTests(unittest.TestCase):
    def test_location_patch_preserves_omitted_birthday_and_name(self):
        with tempfile.TemporaryDirectory() as root:
            data_file = Path(root) / "state.json"
            app.save_state(str(data_file), {"users": {"U-member": {
                "line_user_id": "U-member",
                "display_name": "珮淩",
                "birthday": "1988-06-09",
                "location": {"city": "新北市", "district": "三重區"},
            }}})

            result, code = app.update_member_location(
                str(data_file),
                "U-member",
                {"city": "台北市", "district": "中山區"},
            )

            saved = app.load_state(str(data_file))["users"]["U-member"]
            self.assertEqual(code, 200)
            self.assertEqual(result["birthday"], "1988-06-09")
            self.assertEqual(result["display_name"], "珮淩")
            self.assertEqual(saved["birthday"], "1988-06-09")
            self.assertEqual(saved["display_name"], "珮淩")

    def test_member_center_sends_authenticated_complete_profile_and_defaults_birthday(self):
        html = (ROOT / "liff" / "member.html").read_text(encoding="utf-8")

        for marker in (
            'id="memberDisplayName"',
            'id="memberBirthday"',
            'id="saveMemberProfileBtn"',
            'lineAuthHeaders({"Content-Type":"application/json"})',
            'display_name: displayName',
            'birthday: birthday',
            'birthday.value = state.birthday || todayLocalIsoDate();',
            '{ headers: lineAuthHeaders() }',
        ):
            self.assertIn(marker, html)

    def test_member_center_uses_authoritative_membership_label_and_dates(self):
        html = (ROOT / "liff" / "member.html").read_text(encoding="utf-8")

        self.assertIn('d.membership_label || d.plan', html)
        self.assertIn('d.membership_status_text', html)

    def test_onboarding_state_exposes_b799_label_and_period(self):
        with tempfile.TemporaryDirectory() as root:
            data_file = Path(root) / "state.json"
            app.save_state(str(data_file), {"users": {"U-member": {
                "line_user_id": "U-member",
                "plan": "paid_799_year",
                "membership_source": "beta",
                "payment_status": "beta",
                "beta_cohort": "B799",
                "beta_started_at": "2026-08-04T12:00:00",
                "beta_ends_at": "2026-08-25T12:00:00",
            }}})

            status, code = app.onboarding_status_payload(str(data_file), "U-member")

            self.assertEqual(code, 200)
            self.assertEqual(status["membership_label"], "799 年費｜21 天封測")
            self.assertEqual(status["beta_cohort"], "B799")
            self.assertEqual(status["membership_period"]["started_date"], "2026-08-04")
            self.assertEqual(status["membership_period"]["ends_date"], "2026-08-25")

    def test_onboarding_state_repairs_legacy_beta_plan_fields(self):
        with tempfile.TemporaryDirectory() as root:
            data_file = Path(root) / "state.json"
            app.save_state(str(data_file), {"users": {"U-member": {
                "line_user_id": "U-member",
                "plan": "trial",
                "membership_source": "beta",
                "payment_status": "trial",
                "beta_cohort": "B799",
                "beta_activation_pending": True,
            }}})

            status, code = app.onboarding_status_payload(str(data_file), "U-member")

            saved = app.load_state(str(data_file))["users"]["U-member"]
            self.assertEqual(code, 200)
            self.assertEqual(status["plan"], "paid_799_year")
            self.assertEqual(status["membership_label"], "799 年費｜21 天封測")
            self.assertEqual(saved["plan"], "paid_799_year")
            self.assertEqual(saved["payment_status"], "beta")

    def test_pending_beta_starts_only_after_reminder_and_accepted_guardian(self):
        now = datetime(2026, 8, 4, 12, 0, 0)
        profile = {
            "line_user_id": "U-member",
            "plan": "paid_799_year",
            "membership_source": "beta",
            "payment_status": "beta",
            "beta_cohort": "B799",
            "beta_activation_pending": True,
            "onboarding_reminder_configured": True,
            "contacts": [{
                "line_user_id": "U-guardian",
                "contact_role": "guardian",
                "binding_status": "accepted",
                "consent_status": "accepted",
            }],
        }
        state = {"users": {"U-member": profile}}

        result = app.activate_pending_membership_after_setup(state, "U-member", now=now)

        self.assertTrue(result["activated"])
        self.assertFalse(profile["beta_activation_pending"])
        self.assertEqual(profile["beta_started_at"], "2026-08-04T12:00:00")
        self.assertEqual(profile["beta_ends_at"], "2026-08-25T12:00:00")

    def test_login_only_records_member_without_starting_trial(self):
        with tempfile.TemporaryDirectory() as root:
            data_file = Path(root) / "state.json"
            data_file.write_text(json.dumps({"users": {}}), encoding="utf-8")

            result, code = app.register_line_user(
                str(data_file),
                {"line_user_id": "U-new", "display_name": "新會員"},
            )

            saved = app.load_state(str(data_file))["users"]["U-new"]
            self.assertEqual(code, 200)
            self.assertFalse(saved.get("trial_started_at"))
            self.assertFalse(saved.get("trial_end"))
            self.assertTrue(result["membership_activation_pending"])

    def test_home_always_renders_both_guardian_relationship_directions(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="mvpGuardedByCount"', html)
        self.assertIn('id="mvpGuardingCount"', html)
        self.assertIn('守護我的人', html)
        self.assertIn('我正在守護的人', html)
        self.assertIn('status.guarding_details', html)
        self.assertNotIn('box.hidden = true;\n        listEl.innerHTML = "";', html)


if __name__ == "__main__":
    unittest.main()
