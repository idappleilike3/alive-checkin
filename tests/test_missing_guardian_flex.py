import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta

import app


class MissingGuardianFlexTests(unittest.TestCase):
    def test_card_is_warm_and_invite_button_opens_guardian_liff(self):
        flex = app.build_missing_guardian_flex({"display_name": "Jennie"})

        self.assertEqual(flex["type"], "flex")
        self.assertIn("守護人", flex["altText"])
        bubble = flex["contents"]
        self.assertEqual(
            bubble["hero"]["url"],
            "https://alive-checkin.onrender.com/assets/guardian-story-mother-daughter.webp",
        )
        self.assertEqual(bubble["hero"]["aspectMode"], "cover")
        self.assertEqual(bubble["header"]["backgroundColor"], "#EAF7EE")
        body_text = json.dumps(bubble["body"], ensure_ascii=False)
        self.assertIn("Jennie", body_text)
        self.assertIn("不是打擾，而是替彼此多留一份安心", body_text)
        invite = bubble["footer"]["contents"][0]
        self.assertEqual(invite["action"]["label"], "💚 一鍵邀請守護人")
        self.assertEqual(
            invite["action"]["uri"],
            "https://liff.line.me/2010848330-UAiqPPYD/liff/share-invite.html",
        )

    def test_zero_contact_reminder_sends_flex_instead_of_plain_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_file = os.path.join(tmp, "state.json")
            now = datetime(2026, 8, 2, 10, 0, 0)
            profile = {
                "line_user_id": "U-jennie",
                "display_name": "Jennie",
                "plan": "paid_399_year",
                "payment_status": "active",
                "paid_until": (now + timedelta(days=365)).isoformat(),
                "contacts": [],
            }
            app.save_state(data_file, {"users": {"U-jennie": profile}})
            sent = []

            result, status = app.send_missing_contact_reminders(
                {
                    "DATA_FILE": data_file,
                    "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
                    "LINE_PUSH_SENDER": lambda token, target, message: sent.append(
                        (target, message)
                    ) or {"ok": True},
                    "CRON_NOW": now,
                    "APP_TIMEZONE": "Asia/Taipei",
                }
            )

            self.assertEqual(status, 200)
            self.assertEqual(result["sent"], 1)
            self.assertEqual(sent[0][0], "U-jennie")
            self.assertEqual(sent[0][1]["type"], "flex")
            self.assertIn("守護人", sent[0][1]["altText"])


if __name__ == "__main__":
    unittest.main()
