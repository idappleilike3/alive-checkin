import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import app as alive_app
import ecpay


CONFIG = {
    "ECPAY_MERCHANT_ID": "2000132",
    "ECPAY_HASH_KEY": "5294y06JbISpM5x9",
    "ECPAY_HASH_IV": "v77hoKGq4kWxNNIS",
    "ECPAY_STAGE": "sandbox",
    "APP_PUBLIC_URL": "https://alive.example",
}


class ECPayPaymentTests(unittest.TestCase):
    def test_one_time_checkout_uses_aio_v5_and_valid_check_mac(self):
        with patch("ecpay.time.time", return_value=1_722_000_000):
            checkout = ecpay.build_checkout(
                {
                    "order_id": "AC202607270001",
                    "amount": 399,
                    "plan": "paid_399",
                },
                config=CONFIG,
            )

        self.assertEqual(checkout["mode"], "ecpay")
        self.assertEqual(
            checkout["checkout_url"],
            "https://payment-stage.ecpay.com.tw/Cashier/AioCheckOut/V5",
        )
        form = checkout["form"]
        self.assertEqual(form["ChoosePayment"], "Credit")
        self.assertEqual(form["TotalAmount"], 399)
        self.assertEqual(
            form["ReturnURL"],
            "https://alive.example/api/payment/ecpay/notify",
        )
        self.assertTrue(ecpay.verify_check_mac(form, CONFIG))

    def test_recurring_checkout_uses_period_fields(self):
        checkout = ecpay.build_period_checkout(
            {
                "order_id": "AC202607270002",
                "amount": 399,
                "plan": "paid_399",
                "billing_cycle": "monthly",
            },
            config=CONFIG,
        )

        form = checkout["form"]
        self.assertEqual(checkout["mode"], "ecpay_period")
        self.assertEqual(form["PeriodAmount"], 399)
        self.assertEqual(form["PeriodType"], "M")
        self.assertEqual(form["Frequency"], 1)
        self.assertEqual(form["ExecTimes"], 99)
        self.assertEqual(
            form["PeriodReturnURL"],
            "https://alive.example/api/payment/ecpay/period-notify",
        )
        self.assertTrue(ecpay.verify_check_mac(form, CONFIG))

    def test_notify_rejects_bad_mac_and_simulated_payment(self):
        valid = {
            "MerchantID": "2000132",
            "MerchantTradeNo": "AC202607270001",
            "TradeNo": "240727000001",
            "RtnCode": "1",
            "RtnMsg": "Succeeded",
            "TradeAmt": "399",
            "SimulatePaid": "1",
        }
        valid["CheckMacValue"] = ecpay.generate_check_mac(valid, CONFIG)

        parsed, error = ecpay.parse_notify_payload(valid, CONFIG)
        self.assertIsNone(error)
        self.assertTrue(parsed["simulated"])
        self.assertFalse(ecpay.notify_success(parsed))

        invalid = dict(valid)
        invalid["CheckMacValue"] = "BAD"
        parsed, error = ecpay.parse_notify_payload(invalid, CONFIG)
        self.assertIsNone(parsed)
        self.assertEqual(error, "invalid_check_mac")

    def test_refund_request_uses_credit_do_action(self):
        request = ecpay.build_credit_action(
            merchant_trade_no="AC202607270001",
            trade_no="240727000001",
            amount=199,
            action="R",
            config=CONFIG,
        )

        self.assertEqual(
            request["url"],
            "https://payment.ecpay.com.tw/CreditDetail/DoAction",
        )
        self.assertEqual(request["form"]["Action"], "R")
        self.assertEqual(request["form"]["TotalAmount"], 199)
        self.assertTrue(ecpay.verify_check_mac(request["form"], CONFIG))

    def test_cancel_recurring_uses_period_action_and_signed_timestamp(self):
        with patch("ecpay.time.time", return_value=1_722_000_000):
            request = ecpay.build_period_action(
                merchant_trade_no="AC202607270002",
                action="Cancel",
                config=CONFIG,
            )

        self.assertEqual(
            request["url"],
            "https://payment-stage.ecpay.com.tw/Cashier/CreditCardPeriodAction",
        )
        self.assertEqual(request["form"]["Action"], "Cancel")
        self.assertEqual(request["form"]["TimeStamp"], 1_722_000_000)
        self.assertTrue(ecpay.verify_check_mac(request["form"], CONFIG))

    def test_action_response_requires_a_valid_check_mac(self):
        response = {
            "MerchantID": CONFIG["ECPAY_MERCHANT_ID"],
            "MerchantTradeNo": "AC202607270002",
            "TradeNo": "240727000001",
            "RtnCode": "1",
            "RtnMsg": "Success",
        }
        response["CheckMacValue"] = ecpay.generate_check_mac(response, CONFIG)

        parsed, error = ecpay.parse_action_response(response, CONFIG)
        self.assertIsNone(error)
        self.assertEqual(parsed["status"], "1")

        forged = dict(response)
        forged["CheckMacValue"] = "FORGED"
        parsed, error = ecpay.parse_action_response(forged, CONFIG)
        self.assertIsNone(parsed)
        self.assertEqual(error, "invalid_check_mac")


class ECPayAppIntegrationTests(unittest.TestCase):
    def test_new_orders_use_ecpay_without_exposing_provider_in_customer_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, status = alive_app.create_payment_order(
                str(Path(tmp) / "state.json"),
                {"line_user_id": "U-member", "plan": "paid_399"},
                CONFIG,
            )

        self.assertEqual(status, 201)
        self.assertEqual(result["order"]["provider"], "ecpay")
        self.assertEqual(result["checkout"]["mode"], "ecpay")
        self.assertNotIn("綠界", result["checkout"]["message"])

    def test_verified_ecpay_notify_activates_order_and_returns_ack(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_file = str(Path(tmp) / "state.json")
            created, _ = alive_app.create_payment_order(
                data_file,
                {"line_user_id": "U-member", "plan": "paid_399"},
                CONFIG,
            )
            form = {
                "MerchantID": CONFIG["ECPAY_MERCHANT_ID"],
                "MerchantTradeNo": created["order"]["order_id"],
                "TradeNo": "240727000001",
                "RtnCode": "1",
                "RtnMsg": "Succeeded",
                "TradeAmt": "399",
                "SimulatePaid": "0",
            }
            form["CheckMacValue"] = ecpay.generate_check_mac(form, CONFIG)
            client = alive_app.create_app(
                {**CONFIG, "DATA_FILE": data_file, "REQUIRE_LIFF_AUTH": "0"}
            ).test_client()

            response = client.post("/api/payment/ecpay/notify", data=form)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_data(as_text=True), "1|OK")
            profile = alive_app.load_state(data_file)["users"]["U-member"]
            self.assertEqual(profile["payment_status"], "active")
            self.assertEqual(profile["payment_provider"], "ecpay")


if __name__ == "__main__":
    unittest.main()
