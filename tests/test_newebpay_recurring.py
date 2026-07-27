import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs
from unittest.mock import patch

import app as alive_app
import newebpay


CONFIG = {
    "NEWEBPAY_MERCHANT_ID": "MS123456789",
    "NEWEBPAY_HASH_KEY": "12345678901234567890123456789012",
    "NEWEBPAY_HASH_IV": "1234567890123456",
    "NEWEBPAY_STAGE": "sandbox",
    "APP_PUBLIC_URL": "https://alive.example",
}


class NewebPayRecurringTests(unittest.TestCase):
    def test_build_period_checkout_uses_official_v15_monthly_fields(self):
        order = {
            "order_id": "AC202607270001",
            "amount": 399,
            "plan": "paid_399",
            "billing_cycle": "monthly",
        }
        with patch("newebpay.time.time", return_value=1_722_000_000):
            checkout = newebpay.build_period_checkout(
                order,
                payer_email="member@example.com",
                config=CONFIG,
            )

        self.assertEqual(checkout["mode"], "newebpay_period")
        self.assertEqual(checkout["period_url"], "https://ccore.newebpay.com/MPG/period")
        self.assertEqual(checkout["form"]["MerchantID_"], CONFIG["NEWEBPAY_MERCHANT_ID"])
        plain = newebpay.aes_decrypt(
            checkout["form"]["PostData_"],
            CONFIG["NEWEBPAY_HASH_KEY"],
            CONFIG["NEWEBPAY_HASH_IV"],
        )
        fields = {key: values[0] for key, values in parse_qs(plain).items()}
        self.assertEqual(fields["Version"], "1.5")
        self.assertEqual(fields["MerOrderNo"], order["order_id"])
        self.assertEqual(fields["PeriodAmt"], "399")
        self.assertEqual(fields["PeriodType"], "M")
        self.assertEqual(fields["PeriodTimes"], "12")
        self.assertEqual(fields["PeriodStartType"], "2")
        self.assertEqual(fields["PayerEmail"], "member@example.com")
        self.assertEqual(
            fields["NotifyURL"],
            "https://alive.example/api/payment/newebpay/period-notify",
        )

    def test_yearly_period_checkout_uses_yearly_cycle(self):
        checkout = newebpay.build_period_checkout(
            {
                "order_id": "AC202607270002",
                "amount": 3990,
                "plan": "paid_399_year",
                "billing_cycle": "yearly",
            },
            payer_email="member@example.com",
            config=CONFIG,
        )
        plain = newebpay.aes_decrypt(
            checkout["form"]["PostData_"],
            CONFIG["NEWEBPAY_HASH_KEY"],
            CONFIG["NEWEBPAY_HASH_IV"],
        )
        fields = {key: values[0] for key, values in parse_qs(plain).items()}
        self.assertEqual(fields["PeriodType"], "Y")
        self.assertEqual(len(fields["PeriodPoint"]), 4)

    def test_open_ended_period_requires_explicit_cau_permission(self):
        checkout = newebpay.build_period_checkout(
            {
                "order_id": "AC202607270003",
                "amount": 399,
                "plan": "paid_399",
                "billing_cycle": "monthly",
            },
            payer_email="member@example.com",
            config={**CONFIG, "NEWEBPAY_CAU_ENABLED": "1"},
        )
        plain = newebpay.aes_decrypt(
            checkout["form"]["PostData_"],
            CONFIG["NEWEBPAY_HASH_KEY"],
            CONFIG["NEWEBPAY_HASH_IV"],
        )
        fields = {key: values[0] for key, values in parse_qs(plain).items()}
        self.assertEqual(fields["PeriodTimes"], "NE")

    def test_period_notify_decrypts_period_field(self):
        raw = {
            "Status": "SUCCESS",
            "Message": "委託單成立",
            "Result": {
                "MerchantOrderNo": "AC202607270001",
                "PeriodNo": "P260727ABC",
                "TradeNo": "260727000001",
                "PeriodAmt": "399",
                "CardNo": "400022******1111",
            },
        }
        encrypted = newebpay.aes_encrypt(
            json.dumps(raw, ensure_ascii=False),
            CONFIG["NEWEBPAY_HASH_KEY"],
            CONFIG["NEWEBPAY_HASH_IV"],
        )

        parsed, error = newebpay.parse_period_payload(
            {"Period": encrypted},
            CONFIG,
        )

        self.assertIsNone(error)
        self.assertEqual(parsed["status"], "SUCCESS")
        self.assertEqual(parsed["order_id"], "AC202607270001")
        self.assertEqual(parsed["period_no"], "P260727ABC")
        self.assertEqual(parsed["payment_method_last4"], "1111")

    def test_build_period_status_change_uses_terminate_for_cancellation(self):
        with patch("newebpay.time.time", return_value=1_722_000_000):
            request = newebpay.build_period_status_change(
                merchant_order_no="AC202607270001",
                period_no="P260727ABC",
                action="terminate",
                config=CONFIG,
            )

        self.assertEqual(
            request["url"],
            "https://ccore.newebpay.com/MPG/period/AlterStatus",
        )
        plain = newebpay.aes_decrypt(
            request["form"]["PostData_"],
            CONFIG["NEWEBPAY_HASH_KEY"],
            CONFIG["NEWEBPAY_HASH_IV"],
        )
        fields = {key: values[0] for key, values in parse_qs(plain).items()}
        self.assertEqual(fields["Version"], "1.0")
        self.assertEqual(fields["MerOrderNo"], "AC202607270001")
        self.assertEqual(fields["PeriodNo"], "P260727ABC")
        self.assertEqual(fields["AlterType"], "terminate")

    def test_period_status_change_rejects_unknown_action(self):
        with self.assertRaises(ValueError):
            newebpay.build_period_status_change(
                merchant_order_no="AC1",
                period_no="P1",
                action="delete",
                config=CONFIG,
            )

    def test_build_credit_card_refund_uses_official_close_api(self):
        with patch("newebpay.time.time", return_value=1_722_000_000):
            request = newebpay.build_credit_card_refund(
                merchant_order_no="AC202607270001",
                trade_no="260727000001",
                amount=199,
                config=CONFIG,
            )

        self.assertEqual(
            request["url"],
            "https://ccore.newebpay.com/API/CreditCard/Close",
        )
        plain = newebpay.aes_decrypt(
            request["form"]["PostData_"],
            CONFIG["NEWEBPAY_HASH_KEY"],
            CONFIG["NEWEBPAY_HASH_IV"],
        )
        fields = {key: values[0] for key, values in parse_qs(plain).items()}
        self.assertEqual(fields["Version"], "1.1")
        self.assertEqual(fields["Amt"], "199")
        self.assertEqual(fields["MerchantOrderNo"], "AC202607270001")
        self.assertEqual(fields["TradeNo"], "260727000001")
        self.assertEqual(fields["IndexType"], "2")
        self.assertEqual(fields["CloseType"], "2")
        self.assertNotIn("Cancel", fields)

    def test_parse_credit_card_refund_response(self):
        parsed, error = newebpay.parse_credit_card_close_response(
            "Status=SUCCESS&Message=refund+accepted&Amt=199"
            "&MerchantOrderNo=AC202607270001&TradeNo=260727000001"
        )
        self.assertIsNone(error)
        self.assertEqual(parsed["status"], "SUCCESS")
        self.assertEqual(parsed["amount"], 199)
        self.assertEqual(parsed["order_id"], "AC202607270001")


class RecurringBillingLifecycleTests(unittest.TestCase):
    def test_auto_renew_without_email_rejects_without_orphan_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_file = str(Path(tmp) / "state.json")
            state = alive_app.load_state(data_file)
            profile = alive_app.get_profile(state, "U-member")
            profile["auto_renew_requested"] = True
            profile["contact_email"] = ""
            alive_app.save_state(data_file, state)

            result, status = alive_app.create_payment_order(
                data_file,
                {"line_user_id": "U-member", "plan": "paid_399"},
                CONFIG,
            )

            self.assertEqual(status, 400)
            self.assertEqual(result["error"], "payer_email_required_for_auto_renew")
            self.assertEqual(alive_app.load_state(data_file)["orders"], [])

    def test_auto_renew_order_uses_period_checkout_and_records_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_file = str(Path(tmp) / "state.json")
            state = alive_app.load_state(data_file)
            profile = alive_app.get_profile(state, "U-member")
            profile["contact_email"] = "member@example.com"
            profile["auto_renew_requested"] = True
            alive_app.save_state(data_file, state)

            result, status = alive_app.create_payment_order(
                data_file,
                {"line_user_id": "U-member", "plan": "paid_399"},
                CONFIG,
            )

            self.assertEqual(status, 201)
            self.assertEqual(result["checkout"]["mode"], "newebpay_period")
            self.assertTrue(result["order"]["recurring_requested"])
            self.assertEqual(result["order"]["subscription_status"], "pending")

    def test_successful_period_notification_enables_subscription_idempotently(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_file = str(Path(tmp) / "state.json")
            created, _ = alive_app.create_payment_order(
                data_file,
                {"line_user_id": "U-member", "plan": "paid_399"},
                {},
            )
            order_id = created["order"]["order_id"]
            payload = {
                "status": "SUCCESS",
                "order_id": order_id,
                "period_no": "P260727ABC",
                "transaction_id": "260727000001",
                "payment_method_last4": "1111",
            }

            first, first_status = alive_app.process_period_notification(
                data_file, payload, CONFIG
            )
            second, second_status = alive_app.process_period_notification(
                data_file, payload, CONFIG
            )

            self.assertEqual(first_status, 200)
            self.assertEqual(second_status, 200)
            self.assertFalse(first["already_processed"])
            self.assertTrue(second["already_processed"])
            state = alive_app.load_state(data_file)
            profile = state["users"]["U-member"]
            self.assertTrue(profile["auto_renew_enabled"])
            self.assertEqual(profile["auto_renew_status"], "active")
            self.assertEqual(profile["newebpay_period_no"], "P260727ABC")
            order = next(item for item in state["orders"] if item["order_id"] == order_id)
            self.assertEqual(order["subscription_status"], "active")

    def test_cancel_subscription_only_turns_off_after_gateway_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_file = str(Path(tmp) / "state.json")
            state = alive_app.load_state(data_file)
            profile = alive_app.get_profile(state, "U-member")
            profile.update(
                {
                    "auto_renew_enabled": True,
                    "auto_renew_requested": True,
                    "auto_renew_status": "active",
                    "newebpay_period_no": "P260727ABC",
                    "newebpay_period_order_no": "AC202607270001",
                }
            )
            alive_app.save_state(data_file, state)
            response_body = {
                "Status": "SUCCESS",
                "Result": {
                    "MerOrderNo": "AC202607270001",
                    "PeriodNo": "P260727ABC",
                    "AlterType": "terminate",
                },
            }
            encrypted = newebpay.aes_encrypt(
                json.dumps(response_body),
                CONFIG["NEWEBPAY_HASH_KEY"],
                CONFIG["NEWEBPAY_HASH_IV"],
            )

            result, status = alive_app.cancel_recurring_subscription(
                data_file,
                {"line_user_id": "U-member"},
                {
                    **CONFIG,
                    "NEWEBPAY_HTTP_POSTER": (
                        lambda _url, _form: {"period": encrypted}
                    ),
                },
            )

            self.assertEqual(status, 200)
            self.assertTrue(result["cancelled"])
            profile = alive_app.load_state(data_file)["users"]["U-member"]
            self.assertFalse(profile["auto_renew_enabled"])
            self.assertFalse(profile["auto_renew_requested"])
            self.assertEqual(profile["auto_renew_status"], "terminated")

    def test_period_notify_route_activates_verified_subscription(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_file = str(Path(tmp) / "state.json")
            created, _ = alive_app.create_payment_order(
                data_file,
                {"line_user_id": "U-member", "plan": "paid_399"},
                {},
            )
            raw = {
                "Status": "SUCCESS",
                "Result": {
                    "MerchantOrderNo": created["order"]["order_id"],
                    "PeriodNo": "P260727ABC",
                    "TradeNo": "260727000001",
                    "PeriodAmt": "399",
                },
            }
            encrypted = newebpay.aes_encrypt(
                json.dumps(raw),
                CONFIG["NEWEBPAY_HASH_KEY"],
                CONFIG["NEWEBPAY_HASH_IV"],
            )
            client = alive_app.create_app(
                {**CONFIG, "DATA_FILE": data_file, "REQUIRE_LIFF_AUTH": "0"}
            ).test_client()

            response = client.post(
                "/api/payment/newebpay/period-notify",
                data={"Period": encrypted},
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_data(as_text=True), "SUCCESS")
            profile = alive_app.load_state(data_file)["users"]["U-member"]
            self.assertTrue(profile["auto_renew_enabled"])

    def test_member_cancel_route_terminates_private_subscription(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_file = str(Path(tmp) / "state.json")
            state = alive_app.load_state(data_file)
            profile = alive_app.get_profile(state, "U-member")
            profile.update(
                {
                    "auto_renew_enabled": True,
                    "auto_renew_requested": True,
                    "auto_renew_status": "active",
                    "newebpay_period_no": "P260727ABC",
                    "newebpay_period_order_no": "AC202607270001",
                }
            )
            alive_app.save_state(data_file, state)
            encrypted = newebpay.aes_encrypt(
                json.dumps(
                    {
                        "Status": "SUCCESS",
                        "Result": {
                            "MerOrderNo": "AC202607270001",
                            "PeriodNo": "P260727ABC",
                            "AlterType": "terminate",
                        },
                    }
                ),
                CONFIG["NEWEBPAY_HASH_KEY"],
                CONFIG["NEWEBPAY_HASH_IV"],
            )
            client = alive_app.create_app(
                {
                    **CONFIG,
                    "DATA_FILE": data_file,
                    "REQUIRE_LIFF_AUTH": "0",
                    "NEWEBPAY_HTTP_POSTER": (
                        lambda _url, _form: {"period": encrypted}
                    ),
                }
            ).test_client()

            response = client.post(
                "/api/billing/cancel",
                json={"line_user_id": "U-member"},
            )

            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.get_json()["cancelled"])

    def test_refund_rejects_amount_over_remaining_paid_total(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_file = str(Path(tmp) / "state.json")
            state = alive_app.load_state(data_file)
            state["orders"] = [
                {
                    "order_id": "AC1",
                    "line_user_id": "U-member",
                    "status": "paid",
                    "amount": 399,
                    "transaction_id": "T1",
                    "refunded_amount": 300,
                }
            ]
            alive_app.save_state(data_file, state)

            result, status = alive_app.refund_payment_order(
                data_file,
                {"order_id": "AC1", "amount": 100, "reason": "member request"},
                CONFIG,
            )

            self.assertEqual(status, 400)
            self.assertEqual(result["error"], "refund amount exceeds remaining amount")

    def test_successful_refund_records_gateway_result_and_audit_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_file = str(Path(tmp) / "state.json")
            state = alive_app.load_state(data_file)
            state["orders"] = [
                {
                    "order_id": "AC1",
                    "line_user_id": "U-member",
                    "status": "paid",
                    "amount": 399,
                    "transaction_id": "T1",
                    "refunded_amount": 0,
                }
            ]
            alive_app.save_state(data_file, state)

            result, status = alive_app.refund_payment_order(
                data_file,
                {
                    "order_id": "AC1",
                    "amount": 199,
                    "reason": "member request",
                    "requested_by": "admin",
                },
                {
                    **CONFIG,
                    "NEWEBPAY_HTTP_POSTER": lambda _url, _form: (
                        "Status=SUCCESS&Message=refund+accepted&Amt=199"
                        "&MerchantOrderNo=AC1&TradeNo=T1"
                    ),
                },
            )

            self.assertEqual(status, 200)
            self.assertEqual(result["refund"]["status"], "accepted")
            order = alive_app.load_state(data_file)["orders"][0]
            self.assertEqual(order["refunded_amount"], 199)
            self.assertEqual(order["refunds"][0]["reason"], "member request")
            self.assertEqual(order["refunds"][0]["requested_by"], "admin")


if __name__ == "__main__":
    unittest.main()
