import unittest
from datetime import datetime

from finance_admin import FinanceValidationError, create_expense, finance_dashboard, update_finance_settings


NOW = datetime(2026, 8, 20, 12, 0, 0)


class FinanceDashboardTests(unittest.TestCase):
    def state(self):
        return {
            "orders": [
                {
                    "order_id": "MONTH-399",
                    "plan": "paid_399_month",
                    "provider": "ecpay",
                    "amount": 399,
                    "status": "paid",
                    "paid_at": "2026-08-03T10:00:00",
                    "refunded_amount": 0,
                },
                {
                    "order_id": "YEAR-799",
                    "plan": "paid_799_year",
                    "provider": "newebpay",
                    "amount": 7990,
                    "status": "partially_refunded",
                    "paid_at": "2026-08-12T10:00:00",
                    "refunded_amount": 790,
                },
                {
                    "order_id": "OLD-YEAR-199",
                    "plan": "paid_199_year",
                    "provider": "ecpay",
                    "amount": 1990,
                    "status": "paid",
                    "paid_at": "2026-07-15T10:00:00",
                    "refunded_amount": 0,
                },
            ],
            "finance": {
                "settings": {
                    "tax_enabled": True,
                    "tax_rate_percent": "5",
                    "gateway_fees": {
                        "ecpay": {"percent": "2.75", "fixed": "0"},
                        "newebpay": {"percent": "2.8", "fixed": "1"},
                    },
                    "break_even_prices": {"199": 199, "399": 399, "799": 799},
                },
                "expenses": [
                    {
                        "id": "EXP-1",
                        "name": "Render",
                        "category": "hosting",
                        "expense_type": "fixed",
                        "amount": 1050,
                        "incurred_on": "2026-08-01",
                        "has_tax_invoice": True,
                        "input_tax_deductible": True,
                        "status": "active",
                    },
                    {
                        "id": "EXP-2",
                        "name": "網域",
                        "category": "domain",
                        "expense_type": "one_time",
                        "amount": 600,
                        "incurred_on": "2026-07-01",
                        "has_tax_invoice": False,
                        "input_tax_deductible": False,
                        "status": "active",
                    },
                ],
            },
        }

    def test_dashboard_separates_cash_and_accrual_without_double_counting(self):
        result = finance_dashboard(self.state(), "2026-08", now=NOW)
        self.assertEqual(result["cash"]["gross_collected"], 8389)
        self.assertEqual(result["cash"]["refunds"], 790)
        self.assertEqual(result["cash"]["net_collected"], 7599)
        self.assertEqual(result["accrual"]["recognized_gross"], 1164.83)
        self.assertNotEqual(result["cash"]["net_collected"], result["accrual"]["recognized_gross"])

    def test_dashboard_calculates_gateway_tax_expenses_and_break_even(self):
        result = finance_dashboard(self.state(), "2026-08", now=NOW)
        self.assertEqual(result["expenses"]["gross"], 1050)
        self.assertEqual(result["tax"]["input_tax_credit"], 50)
        self.assertGreater(result["cash"]["gateway_fees"], 200)
        self.assertIn("199", result["break_even_members"])
        self.assertGreaterEqual(result["break_even_members"]["199"], 1)

    def test_expense_validation_rejects_html_and_invalid_amount(self):
        state = self.state()
        with self.assertRaises(FinanceValidationError):
            create_expense(state, {"name": "<script>alert(1)</script>", "amount": 10}, "finance", NOW)
        with self.assertRaises(FinanceValidationError):
            create_expense(state, {"name": "主機", "amount": -1}, "finance", NOW)

    def test_expense_and_settings_changes_append_sanitized_audit(self):
        state = self.state()
        expense = create_expense(
            state,
            {
                "name": "Render 正式主機",
                "category": "hosting",
                "expense_type": "fixed",
                "amount": 1050,
                "incurred_on": "2026-08-20",
                "has_tax_invoice": True,
                "input_tax_deductible": False,
            },
            "finance",
            NOW,
        )
        self.assertEqual(expense["amount"], 1050)
        update_finance_settings(
            state,
            {"gateway_fees": {"ecpay": {"percent": 2.5, "fixed": 1}}},
            "super_admin",
            NOW,
        )
        events = state["finance"]["audit"]
        self.assertEqual([row["action"] for row in events[-2:]], ["expense.create", "settings.update"])
        self.assertNotIn("payload", events[-1])


if __name__ == "__main__":
    unittest.main()
