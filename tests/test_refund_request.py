import copy
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import app as alive_app


class RefundRequestTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_file = Path(self.temp_dir.name) / "state.json"
        self.now = datetime(2026, 8, 1, 12, 0, 0)
        state = copy.deepcopy(alive_app.DEFAULT_STATE)
        state["users"]["U-member"] = {
            **alive_app.DEFAULT_PROFILE,
            "line_user_id": "U-member",
            "display_name": "測試會員",
            "contact_email": "member@example.com",
        }
        state["orders"] = [
            {
                "order_id": "AC-ELIGIBLE",
                "line_user_id": "U-member",
                "plan": "paid_399",
                "amount": 399,
                "status": "paid",
                "paid_at": (self.now - timedelta(days=3)).isoformat(),
                "activated_at": "",
            },
            {
                "order_id": "AC-OLD",
                "line_user_id": "U-member",
                "plan": "paid_199",
                "amount": 199,
                "status": "paid",
                "paid_at": (self.now - timedelta(days=8)).isoformat(),
            },
            {
                "order_id": "AC-OTHER",
                "line_user_id": "U-other",
                "plan": "paid_799",
                "amount": 799,
                "status": "paid",
                "paid_at": (self.now - timedelta(days=1)).isoformat(),
            },
        ]
        alive_app.save_state(self.data_file, state)

    def test_only_owned_paid_unactivated_orders_within_seven_days_are_eligible(self):
        result, code = alive_app.member_refundable_orders(
            self.data_file, "U-member", now=self.now
        )
        self.assertEqual(code, 200)
        self.assertEqual([row["order_id"] for row in result["orders"]], ["AC-ELIGIBLE"])

    def test_creates_one_manual_review_ticket_and_sends_member_and_admin_email(self):
        sender = mock.Mock(return_value={"sent": True, "provider": "test"})
        payload = {
            "line_user_id": "U-member",
            "order_id": "AC-ELIGIBLE",
            "email": "member@example.com",
            "reason": "尚未開始使用，想申請退款。",
            "unused_confirmed": True,
        }
        result, code = alive_app.create_member_refund_request(
            self.data_file,
            payload,
            now=self.now,
            config={"SUPPORT_EMAIL_SENDER": sender, "SUPPORT_ADMIN_EMAIL": "alivecheckin.tw@gmail.com"},
        )
        self.assertEqual(code, 201)
        self.assertEqual(result["ticket"]["request_type"], "refund")
        self.assertEqual(result["ticket"]["refund_order_id"], "AC-ELIGIBLE")
        self.assertEqual(result["ticket"]["status"], "submitted")
        self.assertEqual(sender.call_count, 2)

        duplicate, duplicate_code = alive_app.create_member_refund_request(
            self.data_file, payload, now=self.now, config={"SUPPORT_EMAIL_SENDER": sender}
        )
        self.assertEqual(duplicate_code, 409)
        self.assertEqual(duplicate["error"], "refund_request_already_open")

    def test_rejects_another_members_order(self):
        result, code = alive_app.create_member_refund_request(
            self.data_file,
            {
                "line_user_id": "U-member",
                "order_id": "AC-OTHER",
                "email": "member@example.com",
                "reason": "申請退款",
                "unused_confirmed": True,
            },
            now=self.now,
        )
        self.assertEqual(code, 404)
        self.assertEqual(result["error"], "refund_order_not_eligible")

    def test_authenticated_refund_api_ignores_spoofed_member_id(self):
        web_app = alive_app.create_app({"TESTING": True, "DATA_FILE": str(self.data_file), "CRON_NOW": self.now})
        client = web_app.test_client()
        sender = mock.Mock(return_value={"sent": True, "provider": "test"})
        web_app.config["SUPPORT_EMAIL_SENDER"] = sender
        with mock.patch.object(alive_app, "authenticated_line_user", return_value=("U-member", None)):
            listed = client.get("/api/refund/eligible-orders?line_user_id=U-other")
            created = client.post(
                "/api/refund/requests",
                json={
                    "line_user_id": "U-other",
                    "order_id": "AC-ELIGIBLE",
                    "email": "member@example.com",
                    "reason": "尚未使用，申請退款。",
                    "unused_confirmed": True,
                },
            )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([row["order_id"] for row in listed.get_json()["orders"]], ["AC-ELIGIBLE"])
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.get_json()["ticket"]["line_user_id"], "U-member")


if __name__ == "__main__":
    unittest.main()
