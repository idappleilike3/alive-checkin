import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app as alive_app


class SupportApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_file = Path(self.temp_dir.name) / "state.json"
        state = copy.deepcopy(alive_app.DEFAULT_STATE)
        state["users"]["U-member"] = {
            **alive_app.DEFAULT_PROFILE,
            "line_user_id": "U-member",
            "display_name": "測試會員",
            "contact_email": "member@example.com",
        }
        alive_app.save_state(self.data_file, state)
        self.app = alive_app.create_app(
            {"TESTING": True, "DATA_FILE": str(self.data_file)}
        )
        self.client = self.app.test_client()

    def _identity(self, *_args, **_kwargs):
        return "U-member", None

    def test_member_can_create_and_list_only_own_support_tickets(self):
        with mock.patch.object(
            alive_app, "authenticated_line_user", side_effect=self._identity
        ):
            created = self.client.post(
                "/api/support/tickets",
                json={
                    "line_user_id": "U-someone-else",
                    "category": "付款退款",
                    "subject": "退款進度",
                    "message": "請協助查詢",
                    "email": "member@example.com",
                    "reply_channel": "email",
                },
            )
            listed = self.client.get(
                "/api/support/tickets?line_user_id=U-someone-else"
            )

        self.assertEqual(created.status_code, 201)
        self.assertEqual(
            created.get_json()["ticket"]["line_user_id"], "U-member"
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.get_json()["tickets"]), 1)
        self.assertEqual(
            listed.get_json()["tickets"][0]["line_user_id"], "U-member"
        )


if __name__ == "__main__":
    unittest.main()
