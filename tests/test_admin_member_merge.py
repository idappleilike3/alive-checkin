import tempfile
import unittest
from pathlib import Path

import app


class AdminMemberMergeTests(unittest.TestCase):
    def test_merge_moves_old_account_into_existing_new_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_file = str(Path(tmp) / "state.json")
            app.save_state(data_file, {
                "users": {
                    "U-old": {
                        **app.DEFAULT_PROFILE,
                        "line_user_id": "U-old",
                        "display_name": "舊會員",
                        "plan": "paid_399_year",
                        "membership_source": "beta",
                        "payment_status": "active",
                        "paid_until": "2026-08-22T23:59:59+08:00",
                        "history": ["2026-07-24"],
                    },
                    "U-new": {
                        **app.DEFAULT_PROFILE,
                        "line_user_id": "U-new",
                        "display_name": "新會員",
                        "history": ["2026-08-04"],
                    },
                    "U-guardian": {
                        **app.DEFAULT_PROFILE,
                        "line_user_id": "U-guardian",
                        "contacts": [{"id": "c1", "line_user_id": "U-old"}],
                    },
                }
            })

            result, status = app.admin_merge_member_accounts(
                data_file, "U-old", "U-new"
            )

            self.assertEqual(status, 200)
            self.assertTrue(result["ok"])
            state = app.load_state(data_file)
            self.assertNotIn("U-old", state["users"])
            self.assertEqual(state["account_migration_aliases"]["U-old"]["target_line_user_id"], "U-new")
            merged = state["users"]["U-new"]
            self.assertEqual(merged["plan"], "paid_399_year")
            self.assertEqual(merged["history"], ["2026-07-24", "2026-08-04"])
            self.assertEqual(state["users"]["U-guardian"]["contacts"][0]["line_user_id"], "U-new")

    def test_merge_rejects_missing_or_same_accounts(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_file = str(Path(tmp) / "state.json")
            app.save_state(data_file, {"users": {"U-one": {**app.DEFAULT_PROFILE, "line_user_id": "U-one"}}})
            self.assertEqual(app.admin_merge_member_accounts(data_file, "U-one", "U-one")[1], 400)
            self.assertEqual(app.admin_merge_member_accounts(data_file, "U-missing", "U-one")[1], 404)


if __name__ == "__main__":
    unittest.main()
