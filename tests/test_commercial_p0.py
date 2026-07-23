import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import app as alive_app
import line_auth
import newebpay


class CronSecretTests(unittest.TestCase):
    def test_empty_cron_secret_is_rejected(self):
        self.assertFalse(alive_app.cron_allowed({"CRON_SECRET": ""}, ""))
        self.assertFalse(alive_app.cron_allowed({"CRON_SECRET": ""}, "anything"))

    def test_matching_cron_secret_is_accepted(self):
        self.assertTrue(alive_app.cron_allowed({"CRON_SECRET": "s3cret"}, "s3cret"))
        self.assertFalse(alive_app.cron_allowed({"CRON_SECRET": "s3cret"}, "wrong"))


class LineAuthTests(unittest.TestCase):
    def test_channel_id_from_liff_id(self):
        self.assertEqual(
            line_auth.line_login_channel_id({"LIFF_ID": "2010674803-rK98c0lo"}),
            "2010674803",
        )

    def test_require_auth_rejects_missing_token(self):
        uid, err = line_auth.resolve_line_user_id(
            headers={},
            payload={"line_user_id": "U123"},
            config={"REQUIRE_LIFF_AUTH": "1", "LIFF_ID": "2010674803-rK98c0lo"},
        )
        self.assertIsNone(uid)
        self.assertEqual(err[1], 401)

    def test_verified_token_overrides_claimed_id(self):
        def fake_verify(token, client_id):
            self.assertEqual(token, "tok")
            return {"sub": "U-real"}

        uid, err = line_auth.resolve_line_user_id(
            headers={"Authorization": "Bearer tok"},
            payload={"line_user_id": "U-fake"},
            config={"REQUIRE_LIFF_AUTH": "1", "LIFF_ID": "2010674803-x"},
            verify_fn=fake_verify,
        )
        self.assertIsNone(uid)
        self.assertEqual(err[1], 403)

        uid, err = line_auth.resolve_line_user_id(
            headers={"X-Line-Id-Token": "tok"},
            payload={"line_user_id": "U-real"},
            config={"REQUIRE_LIFF_AUTH": "1", "LIFF_ID": "2010674803-x"},
            verify_fn=fake_verify,
        )
        self.assertEqual(uid, "U-real")
        self.assertIsNone(err)


class ExpiryDowngradeTests(unittest.TestCase):
    def test_expired_paid_plan_downgrades_to_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_file = str(Path(tmp) / "state.json")
            state = alive_app.load_state(data_file)
            state["users"]["U1"] = {
                **alive_app.DEFAULT_PROFILE,
                "line_user_id": "U1",
                "plan": "paid_399",
                "payment_status": "active",
                "paid_until": (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds"),
            }
            alive_app.save_state(data_file, state)
            result, code = alive_app.apply_expired_plan_downgrades(
                {"DATA_FILE": data_file, "CRON_NOW": datetime.now()}
            )
            self.assertEqual(code, 200)
            self.assertEqual(result["downgraded"], 1)
            refreshed = alive_app.load_state(data_file)["users"]["U1"]
            self.assertEqual(refreshed["plan"], "free")
            self.assertEqual(refreshed["payment_status"], "expired")


class OverdueAlertTests(unittest.TestCase):
    def test_overdue_notifies_core_guardians_and_group(self):
        pushes = []

        def fake_sender(token, target, message):
            pushes.append((target, message))
            return {"ok": True}

        with tempfile.TemporaryDirectory() as tmp:
            data_file = str(Path(tmp) / "state.json")
            now = datetime.now()
            state = alive_app.load_state(data_file)
            state["users"]["U-owner"] = {
                **alive_app.DEFAULT_PROFILE,
                "line_user_id": "U-owner",
                "display_name": "阿明",
                "plan": "paid_799",
                "payment_status": "active",
                "paid_until": (now + timedelta(days=10)).isoformat(timespec="seconds"),
                "last_check_in": (now - timedelta(days=2)).isoformat(timespec="seconds"),
                "history": [],
                "reminder_time": "08:00",
                "contacts": [
                    {
                        "id": "c1",
                        "name": "家人",
                        "line_id": "U-g1",
                        "priority": 1,
                        "notify_methods": ["line"],
                        "binding_status": "accepted",
                    }
                ],
                "guardian_group_ids": ["Cgroup1"],
            }
            state["guardian_groups"] = {
                "Cgroup1": {
                    "owner_line_user_id": "U-owner",
                    "status": "active",
                    "created_at": now.isoformat(timespec="seconds"),
                }
            }
            alive_app.save_state(data_file, state)
            result, code = alive_app.send_due_reminders(
                {
                    "DATA_FILE": data_file,
                    "LINE_CHANNEL_ACCESS_TOKEN": "token",
                    "LINE_PUSH_SENDER": fake_sender,
                    "CRON_NOW": now,
                }
            )
            self.assertEqual(code, 200)
            targets = [item[0] for item in pushes]
            self.assertIn("U-owner", targets)
            self.assertIn("U-g1", targets)
            self.assertIn("Cgroup1", targets)
            self.assertGreaterEqual(result["sent"], 3)


class NewebpayScaffoldTests(unittest.TestCase):
    def test_manual_checkout_when_keys_missing(self):
        checkout = newebpay.build_checkout(
            {"order_id": "AC1", "amount": 199, "plan": "paid_199"},
            {},
        )
        self.assertEqual(checkout["mode"], "manual")
        self.assertIsNone(checkout["form"])

    def test_newebpay_urls_match_merchant_console_fields(self):
        source = Path(newebpay.__file__).read_text(encoding="utf-8")
        app_source = Path(alive_app.__file__).read_text(encoding="utf-8")

        self.assertIn("/api/payment/newebpay/notify", source)
        self.assertIn("/webhook/newebpay", app_source)
        self.assertIn("/payment-success", source)
        self.assertIn("/pricing", source)
        self.assertIn('@app.post("/api/payment/newebpay/notify")', app_source)
        self.assertIn('@app.post("/webhook/newebpay")', app_source)
        self.assertIn('methods=["GET", "POST"]', app_source)
        self.assertIn("/payment-success", app_source)


class StatusAutoRegisterTests(unittest.TestCase):
    def test_status_auto_registers_missing_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_file = str(Path(tmp) / "state.json")
            client = alive_app.create_app(
                {
                    "DATA_FILE": data_file,
                    "REQUIRE_LIFF_AUTH": "0",
                    "LIFF_ID": "2010674803-rK98c0lo",
                }
            ).test_client()
            res = client.get("/api/status?line_user_id=U-auto-1")
            self.assertEqual(res.status_code, 200)
            payload = res.get_json()
            self.assertTrue(payload.get("ok"))
            self.assertEqual(payload.get("line_user_id"), "U-auto-1")
            self.assertTrue(payload.get("auto_registered"))
            state = alive_app.load_state(data_file)
            self.assertIn("U-auto-1", state.get("users", {}))

    def test_friendly_error_helper_in_index(self):
        page = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
        self.assertIn("function friendlyApiFailure", page)
        self.assertIn("尚未建立帳號資料", page)


class BearerHeaderTests(unittest.TestCase):
    def test_group_api_uses_bearer_prefix(self):
        source = Path(alive_app.__file__).read_text(encoding="utf-8")
        self.assertNotIn('"Authorization": "***" + token', source)
        self.assertIn('f"Bearer {token}"', source)


class DeployCronTests(unittest.TestCase):
    def test_render_declares_overdue_and_auth(self):
        render = (Path(__file__).resolve().parents[1] / "render.yaml").read_text(encoding="utf-8")
        self.assertIn("alive-checkin-overdue-alerts", render)
        self.assertIn("/api/cron/overdue-alerts", render)
        self.assertIn("alive-checkin-membership-expiry", render)
        self.assertIn("REQUIRE_LIFF_AUTH", render)


if __name__ == "__main__":
    unittest.main()
