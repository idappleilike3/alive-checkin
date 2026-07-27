import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import app as alive_app


class PaymentIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_file = str(Path(self.tmp.name) / "state.json")
        self.now = datetime(2026, 7, 27, 19, 30, 0)

    def create_order(self, user_id, plan="paid_399"):
        created, code = alive_app.create_payment_order(
            self.data_file,
            {"line_user_id": user_id, "plan": plan},
            {"CRON_NOW": self.now},
        )
        self.assertEqual(code, 201)
        return created["order"]

    def test_callback_amount_mismatch_is_flagged_and_does_not_activate_member(self):
        order = self.create_order("U-amount")

        result, code = alive_app.confirm_payment_order(
            self.data_file,
            {
                "order_id": order["order_id"],
                "transaction_id": "TX-AMOUNT-1",
                "amount": 199,
                "provider": "ecpay",
            },
            {"CRON_NOW": self.now},
        )

        self.assertEqual(code, 409)
        self.assertEqual(result["error"], "payment_amount_mismatch")
        state = alive_app.load_state(self.data_file)
        saved_order = state["orders"][0]
        self.assertEqual(saved_order["status"], "anomaly")
        self.assertEqual(saved_order["anomaly_code"], "amount_mismatch")
        self.assertEqual(saved_order["expected_amount"], 399)
        self.assertEqual(saved_order["received_amount"], 199)
        self.assertNotEqual(
            state["users"]["U-amount"].get("payment_status"),
            "active",
        )

    def test_transaction_id_cannot_be_reused_by_another_order(self):
        first = self.create_order("U-first", "paid_199")
        second = self.create_order("U-second", "paid_199")

        first_result, first_code = alive_app.confirm_payment_order(
            self.data_file,
            {
                "order_id": first["order_id"],
                "transaction_id": "TX-DUPLICATE-1",
                "amount": 199,
                "provider": "ecpay",
            },
            {"CRON_NOW": self.now},
        )
        duplicate_result, duplicate_code = alive_app.confirm_payment_order(
            self.data_file,
            {
                "order_id": second["order_id"],
                "transaction_id": "TX-DUPLICATE-1",
                "amount": 199,
                "provider": "ecpay",
            },
            {"CRON_NOW": self.now},
        )

        self.assertEqual(first_code, 200)
        self.assertFalse(first_result["already_confirmed"])
        self.assertEqual(duplicate_code, 409)
        self.assertEqual(duplicate_result["error"], "duplicate_transaction_id")
        state = alive_app.load_state(self.data_file)
        saved_second = next(
            item for item in state["orders"] if item["order_id"] == second["order_id"]
        )
        self.assertEqual(saved_second["status"], "anomaly")
        self.assertEqual(saved_second["anomaly_code"], "duplicate_transaction_id")
        self.assertEqual(saved_second["duplicate_of_order_id"], first["order_id"])
        self.assertNotEqual(
            state["users"]["U-second"].get("payment_status"),
            "active",
        )

    def test_period_callback_amount_mismatch_is_flagged_before_renewal(self):
        order = self.create_order("U-period")

        result, code = alive_app.process_period_notification(
            self.data_file,
            {
                "order_id": order["order_id"],
                "transaction_id": "TX-PERIOD-1",
                "amount": 799,
                "status": "SUCCESS",
                "provider": "ecpay",
            },
            {"CRON_NOW": self.now},
        )

        self.assertEqual(code, 409)
        self.assertEqual(result["error"], "payment_amount_mismatch")
        state = alive_app.load_state(self.data_file)
        self.assertEqual(state["orders"][0]["status"], "anomaly")
        self.assertNotEqual(
            state["users"]["U-period"].get("payment_status"),
            "active",
        )


if __name__ == "__main__":
    unittest.main()
