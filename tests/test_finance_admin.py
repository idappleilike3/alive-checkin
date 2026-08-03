import unittest
from datetime import datetime

import finance_admin

from finance_admin import (
    FinanceValidationError,
    create_expense,
    finance_dashboard,
    update_finance_settings,
)


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


class EssentialServiceTests(unittest.TestCase):
    def test_essential_service_summary_interface_is_available(self):
        self.assertTrue(hasattr(finance_admin, "essential_service_summary"))

    def test_summary_seeds_exactly_one_render_service_with_budget_and_deadline(self):
        state = {"orders": []}

        first = finance_admin.essential_service_summary(state, NOW)
        second = finance_admin.essential_service_summary(state, NOW)

        self.assertEqual(len(state["finance"]["essential_services"]), 1)
        self.assertEqual(first["items"], second["items"])
        service = first["items"][0]
        self.assertEqual(service["id"], "render-postgresql-alive-checkin-state")
        self.assertEqual(service["vendor"], "Render")
        self.assertEqual(service["name"], "alive-checkin-state")
        self.assertEqual(service["payment_url"], "https://dashboard.render.com/d/dpg-d9hn1guq1p3s73a7atr0-a/plan")
        self.assertEqual(service["status"], "pending")
        self.assertEqual(service["priority"], "critical")
        self.assertEqual(service["category"], "database")
        self.assertEqual(service["billing_cycle"], "monthly")
        self.assertEqual(service["currency"], "USD")
        self.assertEqual(service["original_amount"], 6.3)
        self.assertEqual(service["monthly_usd"], 6.3)
        self.assertEqual(service["monthly_twd"], 210)
        self.assertEqual(service["annual_twd"], 2500)
        self.assertEqual(service["annual_budget_override"], 2500)
        self.assertEqual(service["deadline"], "2026-08-23")
        self.assertEqual(service["next_renewal_on"], "2026-08-23")
        self.assertEqual(service["days_remaining"], 3)
        self.assertEqual(service["reminder_days"], [30, 14, 7, 3, 1])
        self.assertEqual(service["created_at"], NOW.isoformat(timespec="seconds"))
        self.assertIn("尚未扣款", service["risk"])
        self.assertIn("期限", service["note"])
        seed_events = [
            row for row in state["finance"]["audit"]
            if row["action"] == "essential_service.create"
            and row["target_id"] == service["id"]
        ]
        self.assertEqual(len(seed_events), 1)
        self.assertEqual(seed_events[0]["created_at"], NOW.isoformat(timespec="seconds"))

    def test_generic_service_derives_annual_budget_and_preserves_legacy_aliases(self):
        state = {"orders": []}

        service = finance_admin.create_essential_service(
            state,
            {
                "vendor": "Example Cloud",
                "name": "yearly backup",
                "category": "backup",
                "billing_cycle": "yearly",
                "currency": "usd",
                "original_amount": "120.00",
                "payment_url": "https://billing.example.test/plan",
                "status": "pending",
                "priority": "required",
                "monthly_twd": "400",
                "deadline": "2026-09-20",
                "next_renewal_on": "2027-09-20",
                "reminder_days": [30, 14, 7, 3, 1],
                "risk": "需要續約",
                "note": "按年計費",
            },
            "finance",
            NOW,
        )

        self.assertEqual(service["category"], "backup")
        self.assertEqual(service["billing_cycle"], "yearly")
        self.assertEqual(service["currency"], "USD")
        self.assertEqual(service["original_amount"], 120)
        self.assertEqual(service["monthly_twd"], 400)
        self.assertEqual(service["annual_twd"], 4800)
        self.assertIsNone(service["annual_budget_override"])
        self.assertEqual(service["next_renewal_on"], "2027-09-20")

    def test_generic_service_rejects_inconsistent_annual_budget_and_blank_numbers(self):
        base = {
            "vendor": "Example Cloud",
            "name": "primary database",
            "category": "database",
            "billing_cycle": "monthly",
            "currency": "USD",
            "original_amount": "12.50",
            "payment_url": "https://billing.example.test/plan",
            "status": "pending",
            "priority": "required",
            "monthly_twd": "400",
            "deadline": "2026-09-20",
            "next_renewal_on": "2026-10-20",
        }
        for changes in (
            {"annual_twd": 4700},
            {"original_amount": ""},
            {"monthly_twd": ""},
        ):
            with self.subTest(changes=changes), self.assertRaises(FinanceValidationError):
                finance_admin.create_essential_service(
                    {"orders": []}, {**base, **changes}, "finance", NOW
                )

    def test_service_rejects_invalid_category_cycle_currency_and_renewal_date(self):
        base = {
            "vendor": "Example Cloud",
            "name": "primary database",
            "category": "database",
            "billing_cycle": "monthly",
            "currency": "USD",
            "original_amount": 12.5,
            "payment_url": "https://billing.example.test/plan",
            "status": "pending",
            "priority": "required",
            "monthly_twd": 400,
            "deadline": "2026-09-20",
            "next_renewal_on": "2026-10-20",
        }
        for field, value in (
            ("category", "not-a-category"),
            ("billing_cycle", "weekly"),
            ("currency", "US12"),
            ("next_renewal_on", "2026-02-30"),
        ):
            with self.subTest(field=field), self.assertRaises(FinanceValidationError):
                finance_admin.create_essential_service(
                    {"orders": []}, {**base, field: value}, "finance", NOW
                )

    def test_legacy_service_payload_is_backfilled_without_changing_existing_contract(self):
        state = {"orders": []}

        service = finance_admin.create_essential_service(
            state,
            {
                "vendor": "Legacy Cloud",
                "name": "legacy database",
                "payment_url": "https://billing.example.test/plan",
                "status": "pending",
                "priority": "required",
                "monthly_usd": 10,
                "monthly_twd": 320,
                "annual_twd": 3840,
                "deadline": "2026-09-20",
                "risk": "舊版資料",
                "note": "仍可建立",
            },
            "finance",
            NOW,
        )

        self.assertEqual(service["category"], "other")
        self.assertEqual(service["billing_cycle"], "monthly")
        self.assertEqual(service["currency"], "USD")
        self.assertEqual(service["original_amount"], 10)
        self.assertEqual(service["next_renewal_on"], "2026-09-20")
        self.assertEqual(service["annual_twd"], 3840)

    def test_reminder_history_represents_each_node_once_and_marks_passed_nodes_missed(self):
        state = {"orders": []}

        service = finance_admin.essential_service_summary(state, NOW)["items"][0]

        self.assertEqual(
            [(row["days_before_deadline"], row["status"]) for row in service["reminder_history"]],
            [(30, "missed"), (14, "missed"), (7, "missed"), (3, "due"), (1, "upcoming")],
        )
        refreshed = finance_admin.essential_service_summary(state, NOW)["items"][0]
        self.assertEqual(refreshed["reminder_history"], service["reminder_history"])
        self.assertEqual(len(refreshed["reminder_history"]), 5)

    def test_paid_service_suppresses_every_reminder_node(self):
        state = {"orders": []}
        seeded = finance_admin.essential_service_summary(state, NOW)["items"][0]

        paid = finance_admin.update_essential_service(
            state, seeded["id"], {"status": "paid"}, "finance", NOW
        )

        self.assertEqual(
            [row["status"] for row in paid["reminder_history"]],
            ["suppressed"] * 5,
        )

    def test_pending_service_budget_is_visible_but_never_realized_as_expense_or_profit(self):
        state = {"orders": []}

        dashboard = finance_dashboard(state, "2026-08", now=NOW)

        self.assertEqual(dashboard["essential_services"]["total_monthly_twd"], 210)
        self.assertEqual(dashboard["expenses"]["gross"], 0)
        self.assertEqual(dashboard["cash"]["profit"], 0)
        self.assertEqual(dashboard["accrual"]["profit"], 0)

    def test_create_normalizes_reminder_nodes_and_records_audit_event(self):
        state = {"orders": []}

        service = finance_admin.create_essential_service(
            state,
            {
                "vendor": "Example Cloud",
                "name": "primary database",
                "payment_url": "https://billing.example.test/plan",
                "status": "pausable",
                "priority": "required",
                "monthly_usd": "12.50",
                "monthly_twd": 400,
                "annual_twd": 4800,
                "deadline": "2026-09-20",
                "reminder_days": [1, "30", 7, 14, 7, 3],
                "risk": "需要在到期前確認方案",
                "note": "可暫停的備援服務",
            },
            "finance",
            NOW,
        )

        self.assertEqual(service["reminder_days"], [30, 14, 7, 3, 1])
        self.assertEqual(service["days_remaining"], 31)
        self.assertEqual(state["finance"]["audit"][-1]["action"], "essential_service.create")
        self.assertEqual(state["finance"]["audit"][-1]["target_id"], service["id"])

    def test_update_validates_service_fields_and_audits_change(self):
        state = {"orders": []}
        seeded = finance_admin.essential_service_summary(state, NOW)["items"][0]

        updated = finance_admin.update_essential_service(
            state,
            seeded["id"],
            {"status": "paid", "priority": "required", "reminder_days": [3, 1, 3]},
            "super_admin",
            NOW,
        )

        self.assertEqual(updated["status"], "paid")
        self.assertEqual(updated["priority"], "required")
        self.assertEqual(updated["reminder_days"], [3, 1])
        self.assertEqual(state["finance"]["audit"][-1]["action"], "essential_service.update")
        with self.assertRaises(FinanceValidationError):
            finance_admin.create_essential_service(
                state,
                {
                    "vendor": "Bad URL",
                    "name": "bad-url",
                    "payment_url": "http://billing.example.test/plan",
                    "status": "pending",
                    "priority": "critical",
                    "monthly_twd": 10,
                    "deadline": "2026-09-01",
                },
                "finance",
                NOW,
            )
        with self.assertRaises(FinanceValidationError):
            finance_admin.update_essential_service(state, seeded["id"], {"status": "unknown"}, "finance", NOW)
        with self.assertRaises(FinanceValidationError):
            finance_admin.update_essential_service(state, seeded["id"], {"reminder_days": [2]}, "finance", NOW)

    def test_update_can_clear_existing_risk_and_note(self):
        state = {"orders": []}
        created = finance_admin.create_essential_service(
            state,
            {
                "vendor": "Example Cloud",
                "name": "clearable service",
                "payment_url": "https://billing.example.test/plan",
                "status": "pending",
                "priority": "required",
                "monthly_twd": 100,
                "deadline": "2026-09-20",
                "risk": "需要注意的風險",
                "note": "既有備註",
            },
            "finance",
            NOW,
        )

        updated = finance_admin.update_essential_service(
            state, created["id"], {"risk": "", "note": ""}, "finance", NOW
        )

        self.assertEqual(updated["risk"], "")
        self.assertEqual(updated["note"], "")

    def test_update_empty_field_support_keeps_risk_and_note_validation(self):
        state = {"orders": []}
        seeded = finance_admin.essential_service_summary(state, NOW)["items"][0]

        for payload in (
            {"risk": "<script>alert(1)</script>"},
            {"risk": "風險\x01內容"},
            {"note": "x" * 501},
        ):
            with self.subTest(payload=payload), self.assertRaises(FinanceValidationError):
                finance_admin.update_essential_service(state, seeded["id"], payload, "finance", NOW)

    def test_create_rejects_https_payment_url_with_embedded_credentials(self):
        with self.assertRaises(FinanceValidationError):
            finance_admin.create_essential_service(
                {"orders": []},
                {
                    "vendor": "Credentialed vendor",
                    "name": "credentialed-service",
                    "payment_url": "https://billing-user:billing-secret@billing.example.test/plan",
                    "status": "pending",
                    "priority": "critical",
                    "monthly_twd": 10,
                    "deadline": "2026-09-01",
                },
                "finance",
                NOW,
            )

    def test_create_normalizes_malformed_payment_url_parse_error_to_validation_error(self):
        try:
            finance_admin.create_essential_service(
                {"orders": []},
                {
                    "vendor": "Malformed URL",
                    "name": "malformed-url-service",
                    "payment_url": "https://[bad",
                    "status": "pending",
                    "priority": "critical",
                    "monthly_twd": 10,
                    "deadline": "2026-09-01",
                },
                "finance",
                NOW,
            )
        except Exception as exc:
            self.assertIsInstance(exc, FinanceValidationError)
            self.assertIn("付款網址", str(exc))
        else:
            self.fail("malformed payment URLs must be rejected")


if __name__ == "__main__":
    unittest.main()
