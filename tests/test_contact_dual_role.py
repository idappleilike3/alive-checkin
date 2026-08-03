import tempfile
import unittest
from pathlib import Path

import app


ROOT = Path(__file__).resolve().parents[1]


class ContactDualRoleTests(unittest.TestCase):
    def test_first_setup_saves_reminder_before_guardian_acceptance(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        save_start = page.index("async function saveOnboardingGuardian()")
        save_end = page.index("async function saveOnboardingReminder()", save_start)
        first_setup_save = page[save_start:save_end]

        self.assertIn("apiSaveOnboardingReminder(lineUserId, times)", first_setup_save)
        self.assertNotIn("apiCompleteOnboarding(lineUserId, times)", first_setup_save)

    def test_same_person_can_be_guardian_and_emergency_contact(self):
        with tempfile.TemporaryDirectory() as directory:
            data_file = str(Path(directory) / "state.json")
            state = {
                "users": {
                    "U-owner": {
                        "line_user_id": "U-owner",
                        "plan": "paid_799_year",
                        "contacts": [],
                    }
                }
            }
            app.save_state(data_file, state)

            guardian = {
                "name": "王小明",
                "relationship": "家人",
                "phone": "0912345678",
                "contact_role": "guardian",
            }
            emergency = {**guardian, "contact_role": "emergency"}

            guardian_result, guardian_status = app.add_single_contact(data_file, "U-owner", guardian)
            emergency_result, emergency_status = app.add_single_contact(data_file, "U-owner", emergency)

            self.assertEqual(guardian_status, 200, guardian_result)
            self.assertEqual(emergency_status, 200, emergency_result)
            self.assertEqual(
                [contact["contact_role"] for contact in emergency_result["contacts"]],
                ["guardian", "emergency"],
            )

    def test_first_guardian_is_primary_and_later_guardians_have_explicit_rank(self):
        with tempfile.TemporaryDirectory() as directory:
            data_file = str(Path(directory) / "state.json")
            app.save_state(data_file, {"users": {"U-owner": {
                "line_user_id": "U-owner", "plan": "paid_799", "contacts": [],
            }}})

            first, first_status = app.add_single_contact(data_file, "U-owner", {
                "name": "媽媽", "relationship": "母親", "phone": "0912345678",
                "contact_role": "guardian", "is_primary": False,
            })
            second, second_status = app.add_single_contact(data_file, "U-owner", {
                "name": "姐姐", "relationship": "姊妹", "phone": "0987654321",
                "contact_role": "guardian", "is_primary": False,
            })

            self.assertEqual((first_status, second_status), (200, 200))
            self.assertTrue(second["contacts"][0]["is_primary"])
            self.assertFalse(second["contacts"][1]["is_primary"])
            self.assertEqual([row["priority"] for row in second["contacts"]], [1, 2])

    def test_selecting_primary_guardian_does_not_demote_emergency_contact(self):
        with tempfile.TemporaryDirectory() as directory:
            data_file = str(Path(directory) / "state.json")
            app.save_state(data_file, {"users": {"U-owner": {
                "line_user_id": "U-owner", "plan": "paid_799", "contacts": [{
                    "id": "e1", "name": "阿姨", "relationship": "親屬",
                    "phone": "0911111111", "contact_role": "emergency", "is_primary": True,
                }],
            }}})

            result, status = app.add_single_contact(data_file, "U-owner", {
                "name": "媽媽", "relationship": "母親", "phone": "0922222222",
                "contact_role": "guardian", "is_primary": True,
            })

            self.assertEqual(status, 200)
            self.assertTrue(result["contacts"][0]["is_primary"])
            self.assertTrue(result["contacts"][1]["is_primary"])


if __name__ == "__main__":
    unittest.main()
