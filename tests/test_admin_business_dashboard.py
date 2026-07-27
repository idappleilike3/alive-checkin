import tempfile
import unittest
from pathlib import Path

import app as alive_app


class AdminBusinessDashboardTests(unittest.TestCase):
    def make_state(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        data_file = str(Path(temp.name) / "state.json")
        state = alive_app.load_state(data_file)
        state["users"] = {
            "U-active": {
                "line_user_id": "U-active",
                "display_name": "安心會員",
                "plan": "paid_399",
                "payment_status": "active",
                "contacts": [{"line_user_id": "G1", "is_core": True}],
                "check_ins": ["2026-07-27T01:00:00+00:00"],
            },
            "U-free": {
                "line_user_id": "U-free",
                "display_name": "基本會員",
                "plan": "free",
                "payment_status": "none",
                "contacts": [],
                "check_ins": [],
            },
        }
        state["notification_logs"] = [
            {"status": "sent", "kind": "overdue", "created_at": "2026-07-27T02:00:00+08:00"},
            {"status": "failed", "kind": "sos", "created_at": "2026-07-27T02:10:00+08:00"},
        ]
        state["sos_pending"] = {
            "U-active": {
                "event_id": "sos-open-1",
                "created_at": "2026-07-27T02:20:00+08:00",
                "status": "pending",
            }
        }
        alive_app.save_state(data_file, state)
        return data_file

    def test_dashboard_reports_internal_funnel_and_delivery_health(self):
        data_file = self.make_state()
        dashboard = alive_app.admin_business_dashboard(
            data_file,
            {"GA4_PROPERTY_ID": "", "GA4_SERVICE_ACCOUNT_JSON": "", "LINE_CHANNEL_ACCESS_TOKEN": "secret"},
        )
        self.assertEqual(dashboard["funnel"]["registered_members"], 2)
        self.assertEqual(dashboard["funnel"]["members_with_guardian"], 1)
        self.assertEqual(dashboard["funnel"]["active_paid_members"], 1)
        self.assertEqual(dashboard["delivery"]["total"], 2)
        self.assertEqual(dashboard["delivery"]["success_rate"], 50.0)

    def test_admin_summary_groups_daily_pushes_by_member_with_plan_and_expiry(self):
        data_file = self.make_state()
        state = alive_app.load_state(data_file)
        state["users"]["U-active"]["paid_until"] = "2026-08-15T23:59:59"
        state["notification_logs"] = [
            {
                "status": "sent",
                "kind": "beta_daily_feedback",
                "line_user_id": "U-active",
                "created_at": "2026-07-27T19:00:00+08:00",
            },
            {
                "status": "failed",
                "kind": "overdue",
                "line_user_id": "U-active",
                "created_at": "2026-07-27T20:00:00+08:00",
            },
            {
                "status": "sent",
                "kind": "checkin",
                "line_user_id": "U-free",
                "created_at": "2026-07-26T19:00:00+08:00",
            },
        ]
        alive_app.save_state(data_file, state)

        summary = alive_app.admin_summary(
            data_file,
            now=alive_app.datetime.fromisoformat("2026-07-27T21:00:00+08:00"),
        )

        row = next(
            item
            for item in summary["daily_push_member_stats"]
            if item["line_user_id"] == "U-active"
        )
        self.assertEqual(row["date"], "2026-07-27")
        self.assertEqual(row["display_name"], "安心會員")
        self.assertEqual(row["plan"], "paid_399")
        self.assertEqual(row["expires_at"], "2026-08-15T23:59:59")
        self.assertEqual(row["sent_count"], 1)
        self.assertEqual(row["failed_count"], 1)
        self.assertEqual(row["total_count"], 2)
        self.assertEqual(row["kinds"], ["beta_daily_feedback", "overdue"])

    def test_dashboard_reports_actionable_incidents_and_line_budget(self):
        data_file = self.make_state()
        dashboard = alive_app.admin_business_dashboard(
            data_file,
            {
                "LINE_CHANNEL_ACCESS_TOKEN": "secret",
                "LINE_MONTHLY_MESSAGE_LIMIT": "200",
                "LINE_MESSAGE_WARNING_PERCENT": "80",
            },
            now=alive_app.datetime.fromisoformat("2026-07-27T03:00:00+08:00"),
        )
        self.assertEqual(dashboard["incidents"]["open_sos"], 1)
        self.assertEqual(dashboard["incidents"]["delivery_failures"], 1)
        self.assertEqual(dashboard["incidents"]["total_open"], 2)
        self.assertEqual(dashboard["line_budget"]["used"], 2)
        self.assertEqual(dashboard["line_budget"]["limit"], 200)
        self.assertEqual(dashboard["line_budget"]["remaining"], 198)
        self.assertEqual(dashboard["line_budget"]["status"], "healthy")

    def test_line_budget_warns_without_exposing_configuration_secrets(self):
        data_file = self.make_state()
        state = alive_app.load_state(data_file)
        state["notification_logs"] = [
            {"status": "sent", "kind": "daily", "created_at": "2026-07-01T10:00:00+08:00"}
            for _ in range(8)
        ]
        alive_app.save_state(data_file, state)
        dashboard = alive_app.admin_business_dashboard(
            data_file,
            {
                "LINE_MONTHLY_MESSAGE_LIMIT": "10",
                "LINE_MESSAGE_WARNING_PERCENT": "80",
            },
            now=alive_app.datetime.fromisoformat("2026-07-27T03:00:00+08:00"),
        )
        self.assertEqual(dashboard["line_budget"]["usage_percent"], 80.0)
        self.assertEqual(dashboard["line_budget"]["status"], "warning")

    def test_integration_status_never_exposes_secret_values(self):
        data_file = self.make_state()
        dashboard = alive_app.admin_business_dashboard(
            data_file,
            {
                "GA4_PROPERTY_ID": "properties/123",
                "GA4_SERVICE_ACCOUNT_JSON": '{"private_key":"do-not-leak"}',
                "LINE_CHANNEL_ACCESS_TOKEN": "line-secret",
            },
        )
        serialized = str(dashboard)
        self.assertNotIn("do-not-leak", serialized)
        self.assertNotIn("line-secret", serialized)
        self.assertTrue(dashboard["integrations"]["ga4"]["configured"])
        self.assertTrue(dashboard["integrations"]["line"]["configured"])

    def test_integration_status_distinguishes_tracking_from_report_access(self):
        data_file = self.make_state()
        dashboard = alive_app.admin_business_dashboard(
            data_file,
            {
                "GA4_MEASUREMENT_ID": "G-7LT14XLHFM",
                "GA4_PROPERTY_ID": "547158055",
                "GA4_SERVICE_ACCOUNT_JSON": "",
                "LINE_CHANNEL_ACCESS_TOKEN": "line-token",
                "LINE_CHANNEL_SECRET": "line-secret",
                "LIFF_ID": "2010674803-rK98c0lo",
                "APP_PUBLIC_URL": "https://alive-checkin.onrender.com",
                "WORDPRESS_SITE_URL": "",
                "WORDPRESS_USERNAME": "",
                "WORDPRESS_APPLICATION_PASSWORD": "",
            },
        )
        ga4 = dashboard["integrations"]["ga4"]
        self.assertTrue(ga4["tracking_configured"])
        self.assertFalse(ga4["reporting_configured"])
        self.assertEqual(ga4["measurement_id"], "G-7LT14XLHFM")
        self.assertTrue(dashboard["integrations"]["line"]["configured"])
        self.assertTrue(dashboard["integrations"]["line"]["webhook_configured"])
        self.assertFalse(dashboard["integrations"]["wordpress"]["configured"])
        self.assertNotIn("line-token", str(dashboard))
        self.assertNotIn("line-secret", str(dashboard))

    def test_admin_html_contains_line_and_wordpress_connection_management(self):
        source = Path("admin.html").read_text(encoding="utf-8")
        for text in (
            "LINE Bot 串接",
            "Webhook",
            "WordPress 串接",
            "尚未建立 WordPress 網站",
            "GA4 流量追蹤已安裝",
        ):
            self.assertIn(text, source)
        self.assertIn('id="wordpressStatus"', source)
        self.assertIn('id="lineWebhookStatus"', source)

    def test_admin_html_contains_business_navigation_and_honest_ga4_empty_state(self):
        source = Path("admin.html").read_text(encoding="utf-8")
        for label in ("營運總覽", "會員管理", "守護營運", "流量分析", "SEO 管理", "系統設定"):
            self.assertIn(label, source)
        self.assertIn("GA4 尚未連接", source)
        self.assertIn("/api/admin/business-dashboard", source)
        self.assertIn("緊急事件中心", source)
        self.assertIn("LINE 訊息用量", source)
        self.assertIn("事件處理佇列", source)
        self.assertIn("/api/admin/incidents/resolve", source)
        self.assertIn('id="adminRoleBadge"', source)


if __name__ == "__main__":
    unittest.main()
