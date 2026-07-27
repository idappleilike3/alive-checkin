import tempfile
import base64
import unittest
from pathlib import Path

import app as alive_app


class AdminSessionAuthTests(unittest.TestCase):
    def test_admin_page_uses_session_not_password_query(self):
        page = Path("admin.html").read_text(encoding="utf-8")

        self.assertIn('id="adminLoginForm"', page)
        self.assertIn('id="logoutBtn"', page)
        self.assertIn("async function adminFetch", page)
        self.assertIn('"X-CSRF-Token"', page)
        self.assertNotIn("?password=", page)
        self.assertNotIn("function apiPassword", page)
        self.assertNotIn("免密碼開放後台", page)

    def test_admin_login_ignores_stale_session_restore_and_handles_network_error(self):
        page = Path("admin.html").read_text(encoding="utf-8")

        self.assertIn("let adminAuthGeneration = 0", page)
        self.assertIn("const generation = adminAuthGeneration", page)
        self.assertIn("if (generation !== adminAuthGeneration) return;", page)
        self.assertIn("adminAuthGeneration += 1;", page)
        self.assertIn('showLogin("連線失敗，請稍後再試。");', page)
        self.assertIn('$("loginBtn").disabled = false;', page)

    def make_client(self, **overrides):
        alive_app.ADMIN_LOGIN_ATTEMPTS.clear()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        config = {
            "TESTING": True,
            "DATA_FILE": str(Path(temp.name) / "state.json"),
            "ADMIN_PASSWORD": "very-strong-admin-password",
            "ADMIN_SESSION_SECRET": "test-session-secret-at-least-32-characters",
            "ALLOW_OPEN_ADMIN": "false",
        }
        config.update(overrides)
        return alive_app.create_app(config).test_client(), config["DATA_FILE"]

    def login(self, client, password="very-strong-admin-password"):
        return client.post("/api/admin/login", json={"password": password})

    def test_empty_password_fails_closed(self):
        client, _ = self.make_client(ADMIN_PASSWORD="", ALLOW_OPEN_ADMIN="true")
        response = client.get("/api/admin/summary")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"], "admin_not_configured")

    def test_refund_route_requires_admin_session_and_csrf(self):
        client, data_file = self.make_client(
            NEWEBPAY_MERCHANT_ID="MS123456789",
            NEWEBPAY_HASH_KEY="12345678901234567890123456789012",
            NEWEBPAY_HASH_IV="1234567890123456",
            NEWEBPAY_HTTP_POSTER=lambda _url, _form: (
                "Status=SUCCESS&Message=refund+accepted&Amt=199"
                "&MerchantOrderNo=AC1&TradeNo=T1"
            ),
        )
        state = alive_app.load_state(data_file)
        state["orders"] = [
            {
                "order_id": "AC1",
                "line_user_id": "U-member",
                "status": "paid",
                "amount": 399,
                "transaction_id": "T1",
            }
        ]
        alive_app.save_state(data_file, state)
        payload = {"order_id": "AC1", "amount": 199, "reason": "member request"}

        self.assertEqual(
            client.post("/api/admin/payments/refund", json=payload).status_code,
            401,
        )
        login = self.login(client).get_json()
        self.assertEqual(
            client.post("/api/admin/payments/refund", json=payload).status_code,
            403,
        )
        response = client.post(
            "/api/admin/payments/refund",
            json=payload,
            headers={"X-CSRF-Token": login["csrf_token"]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["refund"]["status"], "accepted")

    def test_summary_requires_session_and_rejects_query_password(self):
        client, _ = self.make_client()
        self.assertEqual(client.get("/api/admin/summary").status_code, 401)
        self.assertEqual(
            client.get("/api/admin/summary?password=very-strong-admin-password").status_code,
            401,
        )

    def test_account_migrations_requires_admin_session(self):
        client, _ = self.make_client()

        self.assertEqual(
            client.get("/api/admin/account-migrations").status_code,
            401,
        )
        self.assertEqual(
            client.get(
                "/api/admin/account-migrations",
                query_string={"password": "very-strong-admin-password"},
            ).status_code,
            401,
        )

    def test_account_migrations_returns_only_sanitized_operational_fields(self):
        client, data_file = self.make_client(
            ACCOUNT_MIGRATION_SECRET="test-only-migration-secret-32bytes",
            LEGACY_LINE_LOGIN_CHANNEL_ID="legacy-channel",
            LINE_LOGIN_CHANNEL_ID="current-channel",
        )
        state = alive_app.load_state(data_file)
        state["account_migration_tickets"] = {
            "ticket-private": {
                "ticket_id": "ticket-private",
                "old_line_user_id": "U-private-old",
                "code_digest": "digest-private",
                "status": "pending",
                "expires_at": "2099-07-26T04:00:00+00:00",
            },
            "ticket-private-expired": {
                "ticket_id": "ticket-private-expired",
                "old_line_user_id": "U-private-expired",
                "code_digest": "digest-private-expired",
                "status": "pending",
                "expires_at": "2020-07-26T04:00:00+00:00",
            }
        }
        state["account_migration_aliases"] = {
            "U-private-old": {
                "target_line_user_id": "U-private-new",
                "status": "disabled",
            }
        }
        state["account_migration_snapshots"] = {
            "snapshot-private": {"old_profile": {"display_name": "Private"}}
        }
        state["account_migration_audit"] = [
            {
                "event_id": "event-private-success",
                "status": "success",
                "created_at": "2026-07-26T02:00:00+00:00",
                "failure_category": "",
                "counts": {
                    "checkins": 2,
                    "contacts": 1,
                    "groups": 1,
                    "reminders": 1,
                    "orders": 1,
                    "requests": 0,
                },
                "profile": {"line_user_id": "U-private-old"},
            },
            {
                "event_id": "event-private-failed",
                "status": "failed",
                "created_at": "2026-07-26T03:00:00+00:00",
                "failure_category": "unsafe_conflict",
                "counts": {"contacts": 0},
                "raw_code": "raw-private-code",
                "token": "token-private",
            },
        ]
        alive_app.save_state(data_file, state)
        self.assertEqual(self.login(client).status_code, 200)

        response = client.get("/api/admin/account-migrations")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                "configured": True,
                "totals": {
                    "total": 3,
                    "success": 1,
                    "failed": 1,
                    "pending": 1,
                },
                "latest_events": [
                    {
                        "status": "failed",
                        "created_at": "2026-07-26T03:00:00+00:00",
                        "failure_category": "unsafe_conflict",
                        "counts": {
                            "checkins": 0,
                            "contacts": 0,
                            "groups": 0,
                            "reminders": 0,
                            "orders": 0,
                            "requests": 0,
                        },
                    },
                    {
                        "status": "success",
                        "created_at": "2026-07-26T02:00:00+00:00",
                        "failure_category": "",
                        "counts": {
                            "checkins": 2,
                            "contacts": 1,
                            "groups": 1,
                            "reminders": 1,
                            "orders": 1,
                            "requests": 0,
                        },
                    },
                ],
            },
        )
        rendered = response.get_data(as_text=True)
        for forbidden in (
            "U-private-old",
            "U-private-new",
            "ticket-private",
            "ticket-private-expired",
            "digest-private",
            "digest-private-expired",
            "snapshot-private",
            "event-private",
            "raw-private-code",
            "token-private",
            "Private",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, rendered)

    def test_bot_admin_routes_require_session_and_reject_legacy_passwords(self):
        client, _ = self.make_client()
        routes = (
            "/api/bot/guardian-groups",
            "/api/bot/sos-pending",
            "/api/bot/recent-events",
        )
        for route in routes:
            with self.subTest(route=route, credential="query"):
                response = client.get(
                    f"{route}?password=very-strong-admin-password"
                )
                self.assertEqual(response.status_code, 401)
            with self.subTest(route=route, credential="header"):
                response = client.get(
                    route,
                    headers={"X-Admin-Password": "very-strong-admin-password"},
                )
                self.assertEqual(response.status_code, 401)
        self.assertEqual(self.login(client).status_code, 200)
        for route in routes:
            with self.subTest(route=route, credential="session"):
                self.assertEqual(client.get(route).status_code, 200)

    def test_login_creates_session_and_logout_invalidates_it(self):
        client, _ = self.make_client()
        login = self.login(client)
        self.assertEqual(login.status_code, 200)
        csrf_token = login.get_json()["csrf_token"]
        self.assertTrue(csrf_token)
        self.assertEqual(client.get("/api/admin/summary").status_code, 200)
        self.assertEqual(client.post("/api/admin/logout").status_code, 403)
        self.assertEqual(client.get("/api/admin/summary").status_code, 200)
        logout = client.post(
            "/api/admin/logout",
            headers={"X-CSRF-Token": csrf_token},
        )
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(client.get("/api/admin/summary").status_code, 401)

    def test_login_cookie_has_secure_session_attributes(self):
        client, _ = self.make_client()
        response = self.login(client)
        cookie = response.headers.get("Set-Cookie", "")
        self.assertIn("Secure", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertIn("Expires=", cookie)

    def test_login_rejects_insecure_external_http(self):
        client, _ = self.make_client(TESTING=False)
        response = client.post(
            "/api/admin/login",
            json={"password": "very-strong-admin-password"},
            environ_overrides={"REMOTE_ADDR": "203.0.113.10"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "https_required")

    def test_login_allows_localhost_http_in_production_mode(self):
        client, _ = self.make_client(TESTING=False)
        response = client.post(
            "/api/admin/login",
            json={"password": "very-strong-admin-password"},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(response.status_code, 200)

    def test_login_accepts_https_from_trusted_render_proxy(self):
        client, _ = self.make_client(TESTING=False, RENDER="true")
        response = client.post(
            "/api/admin/login",
            json={"password": "very-strong-admin-password"},
            headers={"X-Forwarded-Proto": "https"},
            environ_overrides={"REMOTE_ADDR": "203.0.113.10"},
        )
        self.assertEqual(response.status_code, 200)

    def test_untrusted_forwarded_proto_cannot_bypass_https(self):
        client, _ = self.make_client(TESTING=False, RENDER="false")
        response = client.post(
            "/api/admin/login",
            json={"password": "very-strong-admin-password"},
            headers={"X-Forwarded-Proto": "https"},
            environ_overrides={"REMOTE_ADDR": "203.0.113.10"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "https_required")

    def test_string_false_testing_flag_cannot_bypass_https(self):
        client, _ = self.make_client(TESTING="false")
        response = client.post(
            "/api/admin/login",
            json={"password": "very-strong-admin-password"},
            environ_overrides={"REMOTE_ADDR": "203.0.113.10"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "https_required")

    def test_write_route_requires_csrf(self):
        client, _ = self.make_client()
        login = self.login(client).get_json()
        self.assertEqual(client.post("/api/admin/backups").status_code, 403)
        allowed = client.post(
            "/api/admin/backups",
            headers={"X-CSRF-Token": login["csrf_token"]},
        )
        self.assertEqual(allowed.status_code, 200)

    def test_r2_backup_route_requires_csrf_and_uploads_encrypted_object(self):
        uploads = []
        client, _ = self.make_client(
            R2_BUCKET="alive-backups",
            R2_BACKUP_ENCRYPTION_KEY=base64.urlsafe_b64encode(b"k" * 32).decode(),
            R2_UPLOADER=lambda bucket, key, body, content_type, metadata, config: (
                uploads.append((bucket, key, body)) or {"etag": "etag-r2"}
            ),
        )
        login = self.login(client).get_json()

        self.assertEqual(client.post("/api/admin/backups/r2").status_code, 403)
        response = client.post(
            "/api/admin/backups/r2",
            headers={"X-CSRF-Token": login["csrf_token"]},
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(uploads), 1)
        self.assertNotIn(b"users", uploads[0][2])

    def test_wrong_password_is_rejected_without_secret_leak(self):
        client, _ = self.make_client()
        response = self.login(client, "wrong")
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("wrong", response.get_data(as_text=True))
        self.assertNotIn("very-strong", response.get_data(as_text=True))

    def test_sixth_failed_login_is_rate_limited(self):
        client, _ = self.make_client()
        for _ in range(5):
            self.assertEqual(self.login(client, "wrong").status_code, 401)
        self.assertEqual(self.login(client, "wrong").status_code, 429)

    def test_admin_mutation_is_audited_without_credentials(self):
        client, data_file = self.make_client()
        token = self.login(client).get_json()["csrf_token"]
        client.post("/api/admin/backups", headers={"X-CSRF-Token": token})
        state = alive_app.load_state(data_file)
        logs = state.get("admin_audit_logs") or []
        self.assertEqual(logs[-1]["action"], "backup.create")
        self.assertNotIn("password", str(logs[-1]).lower())
        self.assertNotIn("csrf", str(logs[-1]).lower())

    def test_audit_sanitizes_sensitive_metadata_recursively(self):
        _, data_file = self.make_client()
        alive_app.append_admin_audit(
            data_file,
            "security.test",
            "success",
            {
                "http_status": 200,
                "password": "password-value",
                "nested": {
                    "api_token": "token-value",
                    "client_secret": "secret-value",
                    "csrf_token": "csrf-value",
                    "authorization": "Bearer authorization-value",
                    "cookie": "session=cookie-value",
                    "profile": {
                        "line_user_id": "U-personal-id",
                        "display_name": "Personal Name",
                        "email": "person@example.com",
                        "phone": "0912345678",
                        "address": "Personal Address",
                    },
                    "safe_count": 2,
                },
            },
        )
        metadata = alive_app.load_state(data_file)["admin_audit_logs"][-1]["metadata"]
        rendered = str(metadata).lower()
        self.assertEqual(metadata["http_status"], 200)
        self.assertEqual(metadata["nested"]["safe_count"], 2)
        for sensitive_value in (
            "password-value",
            "token-value",
            "secret-value",
            "csrf-value",
            "authorization-value",
            "cookie-value",
            "u-personal-id",
            "personal name",
            "person@example.com",
            "0912345678",
            "personal address",
        ):
            with self.subTest(sensitive_value=sensitive_value):
                self.assertNotIn(sensitive_value, rendered)

    def test_audit_log_is_bounded_to_200_entries(self):
        _, data_file = self.make_client()
        state = alive_app.load_state(data_file)
        state["admin_audit_logs"] = [
            {
                "created_at": "2026-07-26T00:00:00",
                "action": f"old-{index}",
                "status": "success",
                "metadata": {},
            }
            for index in range(205)
        ]
        alive_app.save_state(data_file, state)
        alive_app.append_admin_audit(data_file, "latest", "success")
        logs = alive_app.load_state(data_file)["admin_audit_logs"]
        self.assertEqual(len(logs), 200)
        self.assertEqual(logs[0]["action"], "old-6")
        self.assertEqual(logs[-1]["action"], "latest")
