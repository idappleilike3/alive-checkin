import unittest
from unittest.mock import patch

import app as alive_app
from security_controls import apply_security_headers, redact_sensitive, security_readiness


class FakeResponse:
    def __init__(self):
        self.headers = {}


class SecurityControlsTests(unittest.TestCase):
    def test_redaction_masks_tokens_contact_and_coordinates_recursively(self):
        value = {
            "token": "secret-token-value",
            "phone": "0912345678",
            "nested": {"line_user_id": "U" + "a" * 32, "latitude": 25.03},
            "safe": "payment failed",
        }
        redacted = redact_sensitive(value)
        self.assertEqual(redacted["token"], "[REDACTED]")
        self.assertEqual(redacted["phone"], "09******78")
        self.assertEqual(redacted["nested"]["line_user_id"], "Ua***aaa")
        self.assertEqual(redacted["nested"]["latitude"], "[REDACTED]")
        self.assertEqual(redacted["safe"], "payment failed")

    def test_security_headers_are_strict_without_blocking_line_or_maps(self):
        response = apply_security_headers(FakeResponse(), is_https=True, path="/")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("max-age=31536000", response.headers["Strict-Transport-Security"])
        self.assertIn("https://static.line-scdn.net", response.headers["Content-Security-Policy"])
        self.assertIn("https://www.google.com", response.headers["Content-Security-Policy"])
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    def test_readiness_cannot_report_public_ready_without_platform_evidence(self):
        report = security_readiness({
            "ADMIN_PASSWORD": "long-admin-password",
            "ADMIN_SESSION_SECRET": "x" * 32,
            "LINE_CHANNEL_SECRET": "x" * 32,
            "CRON_SECRET": "x" * 32,
            "DATABASE_URL": "postgresql://example",
        })
        self.assertEqual(len(report["items"]), 10)
        self.assertEqual(report["overall"], "blocked_public_operation")
        self.assertFalse(report["public_operation_allowed"])
        self.assertFalse(report["public_test_allowed"])
        self.assertNotIn("long-admin-password", str(report))

    def test_legacy_flags_without_dated_sources_cannot_allow_release(self):
        config = {
            "ADMIN_PASSWORD": "long-admin-password",
            "ADMIN_SESSION_SECRET": "x" * 32,
            "LINE_CHANNEL_SECRET": "x" * 32,
            "CRON_SECRET": "x" * 32,
            "DATABASE_URL": "postgresql://example",
            "SECRETS_SCAN_PASSED": "true",
            "DATABASE_LEAST_PRIVILEGE_CONFIRMED": "true",
            "DEPENDENCY_AUDIT_PASSED": "true",
            "BACKUP_RESTORE_TESTED_AT": "2026-08-03",
            "SECURITY_MONITORING_ENABLED": "true",
            "INCIDENT_RUNBOOK_CONFIRMED": "true",
        }
        report = security_readiness(config)
        self.assertFalse(report["public_operation_allowed"])
        self.assertFalse(report["public_test_allowed"])
        self.assertEqual(report["overall"], "blocked_public_operation")
        self.assertTrue(all(item["status"] == "not_checked" for item in report["items"]))

    def test_complete_dated_evidence_can_allow_release(self):
        config = {
            "ADMIN_PASSWORD": "long-admin-password",
            "ADMIN_SESSION_SECRET": "x" * 32,
            "LINE_CHANNEL_SECRET": "x" * 32,
            "CRON_SECRET": "x" * 32,
            "DATABASE_URL": "postgresql://example",
        }
        for number in range(1, 11):
            prefix = f"SECURITY_CHECK_{number:02d}"
            config[f"{prefix}_STATUS"] = "passed"
            config[f"{prefix}_SOURCE"] = "automated_test"
            config[f"{prefix}_CHECKED_AT"] = "2026-08-03T12:00:00+08:00"
            config[f"{prefix}_EVIDENCE"] = f"第 {number} 項驗收通過"

        report = security_readiness(config)

        self.assertTrue(report["public_operation_allowed"])
        self.assertTrue(report["public_test_allowed"])
        self.assertEqual(report["overall"], "ready")
        self.assertEqual(report["items"][0]["evidence_source"], "automated_test")
        self.assertEqual(report["items"][0]["checked_at"], "2026-08-03T12:00:00+08:00")

    def test_explicit_failure_is_distinct_from_not_checked_and_blocks_testing(self):
        config = {}
        for number in range(1, 7):
            prefix = f"SECURITY_CHECK_{number:02d}"
            config[f"{prefix}_STATUS"] = "passed"
            config[f"{prefix}_SOURCE"] = "formal_http_probe"
            config[f"{prefix}_CHECKED_AT"] = "2026-08-03T12:00:00+08:00"
            config[f"{prefix}_EVIDENCE"] = "正式探針通過"
        config.update({
            "ADMIN_PASSWORD": "long-admin-password",
            "ADMIN_SESSION_SECRET": "x" * 32,
            "LINE_CHANNEL_SECRET": "x" * 32,
            "CRON_SECRET": "x" * 32,
            "DATABASE_URL": "postgresql://example",
            "SECURITY_CHECK_07_STATUS": "failed",
            "SECURITY_CHECK_07_SOURCE": "automated_test",
            "SECURITY_CHECK_07_CHECKED_AT": "2026-08-03T12:05:00+08:00",
            "SECURITY_CHECK_07_EVIDENCE": "登入限制負向測試失敗",
        })

        report = security_readiness(config)

        self.assertTrue(report["public_operation_allowed"])
        self.assertFalse(report["public_test_allowed"])
        self.assertEqual(report["overall"], "blocked_public_test")
        self.assertEqual(report["items"][6]["status"], "failed")
        self.assertEqual(report["items"][7]["status"], "not_checked")
        for item in report["items"]:
            self.assertIn("checked_at", item)
            self.assertIn("evidence_source", item)
            self.assertIn("remediation", item)

    def test_create_app_loads_dated_security_evidence_without_exposing_values(self):
        evidence_env = {
            "SECURITY_CHECK_01_STATUS": "passed",
            "SECURITY_CHECK_01_SOURCE": "automated_test",
            "SECURITY_CHECK_01_CHECKED_AT": "2026-08-03T12:00:00+08:00",
            "SECURITY_CHECK_01_EVIDENCE": "掃描通過，未發現機密值",
        }
        with patch.dict("os.environ", evidence_env, clear=False):
            flask_app = alive_app.create_app({"TESTING": True})

        self.assertEqual(flask_app.config["SECURITY_CHECK_01_STATUS"], "passed")
        self.assertEqual(flask_app.config["SECURITY_CHECK_01_SOURCE"], "automated_test")


if __name__ == "__main__":
    unittest.main()
