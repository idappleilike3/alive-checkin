import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app as alive_app


@unittest.skipIf(alive_app.Flask is None, "Flask is not installed in this local runtime")
class XiaoPinganApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_file = Path(self.temp_dir.name) / "state.json"
        state = copy.deepcopy(alive_app.DEFAULT_STATE)
        state["users"]["U-member"] = {
            **alive_app.DEFAULT_PROFILE,
            "line_user_id": "U-member",
            "plan": "paid_799_year",
            "membership_source": "paid",
            "payment_status": "active",
            "paid_until": "2027-08-04T23:59:59+08:00",
        }
        alive_app.save_state(self.data_file, state)
        self.app = alive_app.create_app({"TESTING": True, "DATA_FILE": str(self.data_file)})
        self.client = self.app.test_client()

    def test_member_plan_answer_requires_authenticated_line_identity(self):
        response = self.client.post("/api/xiao-pingan/answer", json={"question": "我的方案是什麼"})
        self.assertIn(response.status_code, (401, 403))

    def test_answer_returns_real_member_plan(self):
        with mock.patch.object(alive_app, "authenticated_line_user", return_value=("U-member", None)):
            response = self.client.post("/api/xiao-pingan/answer", json={"question": "我的方案是什麼"})
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["topic"], "my_plan")
        self.assertIn("799", payload["answer"])

    def test_unknown_question_returns_safe_suggestions(self):
        with mock.patch.object(alive_app, "authenticated_line_user", return_value=("U-member", None)):
            response = self.client.post("/api/xiao-pingan/answer", json={"question": "今天晚餐吃什麼"})
        payload = response.get_json()
        self.assertEqual(payload["topic"], "fallback")
        self.assertGreaterEqual(len(payload["suggestions"]), 2)


if __name__ == "__main__":
    unittest.main()
