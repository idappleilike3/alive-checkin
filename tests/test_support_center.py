import tempfile
import unittest
from pathlib import Path

import app as alive_app


class SupportCenterTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_file = Path(self.temp_dir.name) / "state.json"
        state = alive_app.copy.deepcopy(alive_app.DEFAULT_STATE)
        state["users"]["U-member"] = {
            **alive_app.DEFAULT_PROFILE,
            "display_name": "測試會員",
            "contact_email": "member@example.com",
        }
        alive_app.save_state(self.data_file, state)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_email_ticket_defaults_to_email_and_is_visible_to_owner(self):
        result, code = alive_app.create_support_ticket(
            self.data_file,
            {
                "line_user_id": "U-member",
                "category": "付款退款",
                "subject": "退款進度",
                "message": "想查詢退款進度",
                "email": "member@example.com",
                "reply_channel": "email",
            },
        )

        self.assertEqual(code, 201)
        ticket = result["ticket"]
        self.assertEqual(ticket["reply_channel"], "email")
        self.assertEqual(ticket["status"], "submitted")
        self.assertEqual(ticket["category"], "付款退款")
        owner_view, owner_code = alive_app.member_support_tickets(
            self.data_file, "U-member"
        )
        self.assertEqual(owner_code, 200)
        self.assertEqual(owner_view["tickets"][0]["id"], ticket["id"])

    def test_email_reply_uses_email_sender_and_records_delivery(self):
        created, _ = alive_app.create_support_ticket(
            self.data_file,
            {
                "line_user_id": "U-member",
                "message": "請用 Email 回覆",
                "email": "member@example.com",
                "reply_channel": "email",
            },
        )
        sent = []

        def email_sender(to_email, subject, message, config):
            sent.append((to_email, subject, message))
            return {"id": "email-1"}

        result, code = alive_app.admin_reply_support_ticket(
            self.data_file,
            {
                "ticket_id": created["ticket"]["id"],
                "message": "退款已完成",
                "status": "resolved",
            },
            {"SUPPORT_EMAIL_SENDER": email_sender},
        )

        self.assertEqual(code, 200)
        self.assertEqual(sent[0][0], "member@example.com")
        self.assertEqual(result["ticket"]["status"], "resolved")
        self.assertEqual(result["ticket"]["delivery_log"][-1]["channel"], "email")
        self.assertEqual(result["ticket"]["delivery_log"][-1]["status"], "sent")

    def test_line_reply_never_targets_a_group(self):
        created, _ = alive_app.create_support_ticket(
            self.data_file,
            {
                "line_user_id": "C-group-id",
                "message": "群組訊息",
                "reply_channel": "line",
            },
        )
        result, code = alive_app.admin_reply_support_ticket(
            self.data_file,
            {"ticket_id": created["ticket"]["id"], "message": "私人客服回覆"},
            {
                "LINE_CHANNEL_ACCESS_TOKEN": "token",
                "LINE_PUSH_SENDER": lambda *_: {"ok": True},
            },
        )

        self.assertEqual(code, 400)
        self.assertEqual(result["error"], "line_private_reply_required")

    def test_failed_delivery_is_recorded_and_ticket_stays_open(self):
        created, _ = alive_app.create_support_ticket(
            self.data_file,
            {
                "line_user_id": "U-member",
                "message": "請用 Email 回覆",
                "email": "member@example.com",
                "reply_channel": "email",
            },
        )

        def failing_sender(*_):
            raise RuntimeError("provider unavailable")

        result, code = alive_app.admin_reply_support_ticket(
            self.data_file,
            {"ticket_id": created["ticket"]["id"], "message": "測試回覆"},
            {"SUPPORT_EMAIL_SENDER": failing_sender},
        )

        self.assertEqual(code, 502)
        self.assertEqual(result["ticket"]["status"], "submitted")
        self.assertEqual(result["ticket"]["delivery_log"][-1]["status"], "failed")
        self.assertNotIn("provider unavailable", str(result))

    def test_default_email_sender_uses_configured_smtp_with_tls(self):
        events = []

        class FakeSmtp:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return None

            def starttls(self):
                events.append(("tls",))

            def login(self, username, password):
                events.append(("login", username, password))

            def send_message(self, message):
                events.append((
                    "send",
                    message["From"],
                    message["To"],
                    message["Subject"],
                    message.get_content().strip(),
                ))

        result = alive_app.send_support_email(
            "member@example.com",
            "退款進度",
            "退款已完成",
            {
                "SMTP_HOST": "smtp.example.com",
                "SMTP_PORT": 587,
                "SMTP_USERNAME": "service@example.com",
                "SMTP_PASSWORD": "secret",
                "SMTP_USE_TLS": True,
                "SUPPORT_FROM_EMAIL": "service@example.com",
                "SMTP_FACTORY": lambda host, port, timeout: FakeSmtp(),
            },
        )

        self.assertEqual(events[0], ("tls",))
        self.assertEqual(events[1], ("login", "service@example.com", "secret"))
        self.assertEqual(
            events[2],
            (
                "send",
                "service@example.com",
                "member@example.com",
                "退款進度",
                "退款已完成",
            ),
        )
        self.assertTrue(result["sent"])


if __name__ == "__main__":
    unittest.main()
