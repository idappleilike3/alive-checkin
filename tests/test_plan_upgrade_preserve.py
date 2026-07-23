"""Plan upgrade must never wipe guardians / friends."""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app import admin_update_user_plan, apply_expired_plan_downgrades, save_state, load_state


class PlanUpgradePreserveBindingsTests(unittest.TestCase):
    def make_data_file(self, profile):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        data_file = str(Path(temp_dir.name) / "state.json")
        save_state(data_file, {"users": {profile["line_user_id"]: profile}})
        return data_file

    def test_admin_upgrade_keeps_contacts_and_friends(self):
        profile = {
            "line_user_id": "U-owner",
            "display_name": "測試",
            "plan": "trial",
            "payment_status": "trial",
            "contacts": [
                {"id": "c1", "name": "媽媽", "relationship": "母親", "line_id": "U-mom", "priority": 1}
            ],
            "friends": ["U-friend-1"],
            "guardian_group_ids": ["g1"],
            "is_onboarding_completed": True,
            "reminder_times": ["09:30"],
            "reminder_time": "09:30",
        }
        data_file = self.make_data_file(profile)

        result, status = admin_update_user_plan(data_file, {
            "line_user_id": "U-owner",
            "plan": "paid_799_year",
            "payment_status": "active",
        })

        self.assertEqual(status, 200)
        self.assertEqual(result["plan"], "paid_799_year")
        self.assertEqual(result["preserved_contacts"], 1)
        self.assertEqual(result["preserved_friends"], 1)
        self.assertTrue(result.get("paid_until"))

        saved = load_state(data_file)["users"]["U-owner"]
        self.assertEqual(len(saved["contacts"]), 1)
        self.assertEqual(saved["contacts"][0]["name"], "媽媽")
        self.assertEqual(saved["friends"], ["U-friend-1"])
        self.assertEqual(saved["guardian_group_ids"], ["g1"])
        self.assertTrue(saved["is_onboarding_completed"])
        self.assertEqual(saved["reminder_times"], ["09:30"])

    def test_empty_paid_until_does_not_force_downgrade(self):
        profile = {
            "line_user_id": "U-owner",
            "display_name": "測試",
            "plan": "paid_799_year",
            "payment_status": "active",
            "paid_until": "",
            "contacts": [{"id": "c1", "name": "爸爸", "relationship": "父親", "line_id": "U-dad"}],
            "friends": ["U-f"],
        }
        data_file = self.make_data_file(profile)
        result, code = apply_expired_plan_downgrades({"DATA_FILE": data_file})
        self.assertEqual(code, 200)
        self.assertEqual(result["downgraded"], 0)
        saved = load_state(data_file)["users"]["U-owner"]
        self.assertEqual(saved["plan"], "paid_799_year")
        self.assertEqual(len(saved["contacts"]), 1)
        self.assertEqual(saved["friends"], ["U-f"])


if __name__ == "__main__":
    unittest.main()
