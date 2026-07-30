import tempfile
import unittest
from pathlib import Path

from app import (
    close_sos_as_safe,
    get_sos_event_status,
    load_state,
    process_sos_recipient_reminders,
    respond_to_sos_event,
    save_state,
)


class SosResponseWorkflowTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.data_file = str(Path(temp_dir.name) / "state.json")
        save_state(self.data_file, {
            "users": {
                "U-owner": {"line_user_id": "U-owner", "display_name": "小美"},
                "U-mom": {"line_user_id": "U-mom", "display_name": "媽媽"},
                "U-sister": {"line_user_id": "U-sister", "display_name": "姊姊"},
                "U-third": {"line_user_id": "U-third", "display_name": "哥哥"},
                "U-outsider": {"line_user_id": "U-outsider", "display_name": "陌生人"},
            },
            "sos_events": {
                "sos-1": {
                    "event_id": "sos-1",
                    "owner_line_user_id": "U-owner",
                    "owner_display_name": "小美",
                    "status": "sent",
                    "created_at": "2026-07-27T22:00:00",
                    "sent_at": "2026-07-27T22:00:00",
                    "deliveries": [
                        {"kind": "guardian", "target": "U-mom", "display_name": "媽媽", "status": "sent"},
                        {"kind": "guardian", "target": "U-sister", "display_name": "姊姊", "status": "sent"},
                    ],
                    "escalation_guardians": [
                        {"target": "U-third", "display_name": "哥哥"},
                    ],
                    "timeline": [],
                }
            },
        })

    def test_first_responder_is_primary_and_second_is_assistant(self):
        first, first_status = respond_to_sos_event(self.data_file, {
            "event_id": "sos-1", "line_user_id": "U-mom", "action": "take_over",
        })
        second, second_status = respond_to_sos_event(self.data_file, {
            "event_id": "sos-1", "line_user_id": "U-sister", "action": "take_over",
        })

        self.assertEqual(first_status, 200)
        self.assertEqual(first["role"], "primary")
        self.assertEqual(second_status, 200)
        self.assertEqual(second["role"], "assistant")
        event = load_state(self.data_file)["sos_events"]["sos-1"]
        self.assertEqual(event["primary_responder_id"], "U-mom")
        self.assertEqual(event["assistant_responder_ids"], ["U-sister"])
        self.assertTrue(event["escalation_stopped"])

    def test_only_delivered_guardian_can_respond(self):
        result, status = respond_to_sos_event(self.data_file, {
            "event_id": "sos-1", "line_user_id": "U-outsider", "action": "take_over",
        })
        self.assertEqual(status, 403)
        self.assertEqual(result["error"], "not_sos_recipient")

    def test_contacted_does_not_close_event(self):
        result, status = respond_to_sos_event(self.data_file, {
            "event_id": "sos-1", "line_user_id": "U-mom", "action": "contacted",
        })
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "contacted")
        event = load_state(self.data_file)["sos_events"]["sos-1"]
        self.assertEqual(event["status"], "contacted")
        self.assertIsNone(event.get("closed_at"))

    def test_owner_status_hides_line_ids_and_owner_can_close_safe(self):
        snapshot, status = get_sos_event_status(self.data_file, "U-owner", "sos-1")
        self.assertEqual(status, 200)
        self.assertEqual([row["name"] for row in snapshot["recipients"]], ["媽媽", "姊姊"])
        self.assertNotIn("U-mom", str(snapshot))

        denied, denied_status = close_sos_as_safe(self.data_file, {
            "event_id": "sos-1", "line_user_id": "U-mom",
        })
        self.assertEqual(denied_status, 403)
        self.assertEqual(denied["error"], "not_sos_owner")

        closed, closed_status = close_sos_as_safe(self.data_file, {
            "event_id": "sos-1", "line_user_id": "U-owner",
        })
        self.assertEqual(closed_status, 200)
        self.assertEqual(closed["status"], "safe_closed")

    def test_three_minute_reminder_only_repeats_original_recipients(self):
        pushes = []
        result = process_sos_recipient_reminders(
            self.data_file,
            {
                "LINE_CHANNEL_ACCESS_TOKEN": "token",
                "LINE_PUSH_SENDER": lambda _token, target, message: pushes.append((target, message)) or {"ok": True},
            },
            now=__import__("datetime").datetime.fromisoformat("2026-07-27T22:03:30"),
        )
        self.assertEqual(result["sent"], 2)
        self.assertEqual(
            [target for target, _ in pushes],
            ["U-mom", "U-sister"],
        )
        self.assertNotIn("U-third", {target for target, _ in pushes})
        event = load_state(self.data_file)["sos_events"]["sos-1"]
        self.assertEqual(event["reminder_round"], 1)
        self.assertEqual(
            [row["target"] for row in event["deliveries"]],
            ["U-mom", "U-sister"],
        )

        respond_to_sos_event(self.data_file, {
            "event_id": "sos-1", "line_user_id": "U-mom", "action": "take_over",
        })
        again = process_sos_recipient_reminders(
            self.data_file,
            {
                "LINE_CHANNEL_ACCESS_TOKEN": "token",
                "LINE_PUSH_SENDER": lambda *_args: self.fail("must stop after response"),
            },
            now=__import__("datetime").datetime.fromisoformat("2026-07-27T22:10:30"),
        )
        self.assertEqual(again["sent"], 0)

    def test_three_minute_reminder_never_adds_unselected_guardians(self):
        state = load_state(self.data_file)
        event = state["sos_events"]["sos-1"]
        event["escalation_guardians"] = [
            {"target": f"U-backup-{idx}", "display_name": f"備援 {idx}"}
            for idx in range(3, 8)
        ]
        save_state(self.data_file, state)
        pushes = []
        config = {
            "LINE_CHANNEL_ACCESS_TOKEN": "token",
            "LINE_PUSH_SENDER": (
                lambda _token, target, message:
                pushes.append((target, message)) or {"ok": True}
            ),
        }

        first = process_sos_recipient_reminders(
            self.data_file, config,
            now=__import__("datetime").datetime.fromisoformat("2026-07-27T22:03:30"),
        )

        self.assertEqual(first["sent"], 2)
        self.assertEqual(
            [target for target, _message in pushes],
            ["U-mom", "U-sister"],
        )
        event = load_state(self.data_file)["sos_events"]["sos-1"]
        self.assertEqual(event["reminder_round"], 1)
        self.assertEqual(
            [row["target"] for row in event["deliveries"]],
            ["U-mom", "U-sister"],
        )

    def test_front_admin_and_rich_menu_expose_shared_sos_workflow(self):
        root = Path(__file__).resolve().parents[1]
        front = (root / "index.html").read_text(encoding="utf-8")
        admin = (root / "admin.html").read_text(encoding="utf-8")
        menu = (root / "line-rich-menu-config.json").read_text(encoding="utf-8")
        self.assertIn('id="sosLiveStatus"', front)
        self.assertIn("/api/sos/status", front)
        self.assertIn("/api/sos/safe", front)
        self.assertIn("接手：", admin)
        self.assertIn(
            "https://liff.line.me/2010848330-UAiqPPYD?open=sos",
            menu,
        )


if __name__ == "__main__":
    unittest.main()
