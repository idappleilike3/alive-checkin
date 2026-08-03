import unittest

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

    def test_all_evidence_flags_allow_release_status(self):
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
        self.assertTrue(report["public_operation_allowed"])
        self.assertTrue(report["public_test_allowed"])
        self.assertEqual(report["overall"], "ready")


if __name__ == "__main__":
    unittest.main()
