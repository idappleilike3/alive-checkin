import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app import current_app_time, load_state, save_state, sos_user_facing_error, trigger_sos
import app as app_module


class SosRulesTests(unittest.TestCase):
    def make_data_file(self, profile, extra_state=None):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        data_file = str(Path(temp_dir.name) / "state.json")
        state = {"users": {profile["line_user_id"]: profile}}
        if extra_state:
            state.update(extra_state)
        save_state(data_file, state)
        return data_file

    def test_expired_membership_can_still_send_sos(self):
        """SOS 不依方案／價格：過期付費會員仍可送出（仍受每日上限／冷卻限制）。"""
        messages = []
        profile = {
            "line_user_id": "U-owner",
            "display_name": "測試會員",
            "plan": "paid_799",
            "payment_status": "active",
            "paid_until": (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds"),
            "contacts": [{"line_id": "U-guardian", "priority": 1, "notify_methods": ["line"]}],
        }
        data_file = self.make_data_file(profile)

        result, status = trigger_sos(data_file, {"line_user_id": "U-owner"}, {
            "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
            "LINE_PUSH_SENDER": lambda _token, _target, message: messages.append(message) or {"ok": True},
        })

        self.assertEqual(status, 200)
        self.assertEqual(result["sent"], 1)
        self.assertEqual(len(messages), 1)

    def test_free_plan_can_send_sos(self):
        messages = []
        profile = {
            "line_user_id": "U-free",
            "display_name": "免費會員",
            "plan": "free",
            "contacts": [{"line_id": "U-guardian", "priority": 1, "notify_methods": ["line"]}],
        }
        data_file = self.make_data_file(profile)

        result, status = trigger_sos(data_file, {"line_user_id": "U-free"}, {
            "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
            "LINE_PUSH_SENDER": lambda _token, _target, message: messages.append(message) or {"ok": True},
        })

        self.assertEqual(status, 200)
        self.assertEqual(result["sent"], 1)

    def test_active_799_does_not_attach_stale_location(self):
        messages = []
        profile = {
            "line_user_id": "U-owner",
            "display_name": "小美",
            "plan": "paid_799",
            "payment_status": "active",
            "paid_until": (datetime.now() + timedelta(days=30)).isoformat(timespec="seconds"),
            "contacts": [{"line_id": "U-guardian", "priority": 1, "notify_methods": ["line"]}],
            "location": {"latitude": 25.033, "longitude": 121.5654, "city": "台北市"},
        }
        data_file = self.make_data_file(profile)

        result, status = trigger_sos(data_file, {"line_user_id": "U-owner"}, {
            "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
            "LINE_PUSH_SENDER": lambda _token, _target, message: messages.append(message) or {"ok": True},
        })

        self.assertEqual(status, 200)
        self.assertEqual(result["sent"], 1)
        self.assertFalse(result["location_attached"])
        self.assertIsNone(result["location_updated_at"])
        self.assertNotIn("maps?q=", messages[0])
        self.assertNotIn("取消碼", messages[0])
        self.assertIn("本通知不會自動聯絡警消", messages[0])

    def test_no_guardians_returns_api_error_code(self):
        profile = {
            "line_user_id": "U-alone",
            "display_name": "單身會員",
            "plan": "paid_799",
            "payment_status": "active",
            "contacts": [],
        }
        data_file = self.make_data_file(profile)
        result, status = trigger_sos(data_file, {"line_user_id": "U-alone"}, {
            "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
            "LINE_PUSH_SENDER": lambda *_args: {"ok": True},
        })
        self.assertEqual(status, 400)
        self.assertEqual(result["error"], "no bound LINE guardians")

    def test_guardian_group_only_can_send_sos(self):
        messages = []
        profile = {
            "line_user_id": "U-owner",
            "display_name": "有群沒人",
            "plan": "paid_799",
            "payment_status": "active",
            "paid_until": (datetime.now() + timedelta(days=30)).isoformat(timespec="seconds"),
            "contacts": [],
            "guardian_group_ids": ["C-group"],
        }
        data_file = self.make_data_file(profile, {
            "guardian_groups": {
                "C-group": {
                    "owner_line_user_id": "U-owner",
                    "status": "active",
                    "preferences": {"notify_group_on_overdue": True},
                }
            }
        })
        result, status = trigger_sos(data_file, {"line_user_id": "U-owner"}, {
            "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
            "LINE_PUSH_SENDER": lambda _token, target, message: messages.append((target, message)) or {"ok": True},
        })
        self.assertEqual(status, 200)
        self.assertEqual(result["sent"], 1)
        self.assertEqual(result["group_sent"], 1)
        self.assertEqual(messages[0][0], "C-group")
        group_msg = messages[0][1]
        self.assertIsInstance(group_msg, dict)
        self.assertEqual(group_msg.get("type"), "textV2")
        substitution = group_msg.get("substitution") or {}
        self.assertIn("everyone", substitution)
        self.assertEqual(
            ((substitution.get("everyone") or {}).get("mentionee") or {}).get("type"),
            "all",
        )
        self.assertIn("@全體 緊急SOS", group_msg.get("text") or "")
        self.assertEqual(result["results"][0].get("mention"), "all")

    def test_sos_accepts_inline_coords_and_reports_phone_only(self):
        messages = []
        profile = {
            "line_user_id": "U-owner",
            "display_name": "小美",
            "plan": "paid_399",
            "payment_status": "active",
            "paid_until": (datetime.now() + timedelta(days=30)).isoformat(timespec="seconds"),
            "contacts": [
                {"line_id": "U-guardian", "priority": 1, "notify_methods": ["line"]},
                {"name": "阿爸", "phone": "0912345678", "priority": 2},
            ],
        }
        data_file = self.make_data_file(profile)
        result, status = trigger_sos(
            data_file,
            {
                "line_user_id": "U-owner",
                "latitude": 25.04,
                "longitude": 121.56,
                "city": "台北市",
            },
            {
                "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
                "LINE_PUSH_SENDER": lambda _token, _target, message: messages.append(message) or {"ok": True},
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["sent"], 1)
        self.assertTrue(result["location_attached"])
        self.assertEqual(result["phone_only_count"], 1)
        self.assertEqual(result["phone_contacts"][0]["phone"], "0912345678")
        self.assertIn("maps?q=25.04,121.56", messages[0])
        self.assertTrue(result["sent_at"])
        self.assertTrue(result["location_updated_at"])
        self.assertIn("cancel_available", result)

    def test_inline_sos_coords_preserve_active_location_session(self):
        profile = {
            "line_user_id": "U-owner",
            "display_name": "小美",
            "plan": "free",
            "contacts": [{"line_id": "U-guardian", "priority": 1, "notify_methods": ["line"]}],
            "location": {
                "latitude": 24.0,
                "longitude": 120.0,
                "active": True,
                "sharing": True,
                "mode": "safety_guard",
                "started_at": "2026-07-26T09:00:00",
                "expires_at": "2026-07-26T10:00:00",
            },
        }
        data_file = self.make_data_file(profile)

        result, status = trigger_sos(
            data_file,
            {"line_user_id": "U-owner", "latitude": 25.04, "longitude": 121.56},
            {
                "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
                "LINE_PUSH_SENDER": lambda *_args: {"ok": True},
            },
        )

        stored = load_state(data_file)["users"]["U-owner"]["location"]
        self.assertEqual(status, 200)
        self.assertTrue(result["location_attached"])
        self.assertEqual(stored["latitude"], 25.04)
        self.assertTrue(stored["active"])
        self.assertTrue(stored["sharing"])
        self.assertEqual(stored["mode"], "safety_guard")
        self.assertEqual(stored["started_at"], "2026-07-26T09:00:00")
        self.assertEqual(stored["expires_at"], "2026-07-26T10:00:00")

    def test_sent_at_is_recorded_when_first_push_succeeds(self):
        success_times = []
        profile = {
            "line_user_id": "U-owner",
            "display_name": "小美",
            "plan": "free",
            "contacts": [{"line_id": "U-guardian", "priority": 1, "notify_methods": ["line"]}],
        }
        data_file = self.make_data_file(profile)

        def sender(*_args):
            success_times.append(current_app_time({}).isoformat(timespec="seconds"))
            return {"ok": True}

        result, status = trigger_sos(
            data_file,
            {"line_user_id": "U-owner"},
            {"LINE_CHANNEL_ACCESS_TOKEN": "test-token", "LINE_PUSH_SENDER": sender},
        )

        self.assertEqual(status, 200)
        self.assertEqual(result["sent_at"], success_times[0])

    def test_partial_delivery_reports_each_result_without_false_success(self):
        messages = []
        profile = {
            "line_user_id": "U-owner",
            "display_name": "小美",
            "plan": "paid_399",
            "payment_status": "active",
            "paid_until": (datetime.now() + timedelta(days=30)).isoformat(timespec="seconds"),
            "contacts": [
                {
                    "line_user_id": "U-good",
                    "binding_status": "accepted",
                    "contact_role": "guardian",
                    "is_primary": True,
                    "priority": 1,
                    "notify_methods": ["line"],
                },
                {
                    "line_user_id": "U-failed",
                    "binding_status": "accepted",
                    "contact_role": "guardian",
                    "priority": 2,
                    "notify_methods": ["line"],
                },
            ],
        }
        data_file = self.make_data_file(profile)

        def sender(_token, target, message):
            if target == "U-failed":
                raise RuntimeError("LINE target rejected")
            messages.append((target, message))
            return {"ok": True}

        result, status = trigger_sos(
            data_file,
            {
                "line_user_id": "U-owner",
                "latitude": 25.04,
                "longitude": 121.56,
            },
            {
                "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
                "LINE_PUSH_SENDER": sender,
            },
        )

        self.assertEqual(status, 200)
        self.assertEqual(result["sent"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(messages[0][0], "U-good")
        self.assertTrue(result["sent_at"])
        self.assertTrue(result["location_updated_at"])

    def test_total_delivery_failure_has_no_sent_at(self):
        profile = {
            "line_user_id": "U-owner",
            "display_name": "小美",
            "plan": "free",
            "contacts": [{
                "line_user_id": "U-failed",
                "binding_status": "accepted",
                "contact_role": "guardian",
                "is_primary": True,
                "priority": 1,
                "notify_methods": ["line"],
            }],
        }
        data_file = self.make_data_file(profile)

        result, status = trigger_sos(
            data_file,
            {"line_user_id": "U-owner"},
            {
                "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
                "LINE_PUSH_SENDER": lambda *_args: (_ for _ in ()).throw(
                    RuntimeError("LINE target rejected")
                ),
            },
        )

        self.assertEqual(status, 502)
        self.assertEqual(result["sent"], 0)
        self.assertIsNone(result["sent_at"])

    def test_stale_pending_record_does_not_offer_cancel_for_new_event(self):
        profile = {
            "line_user_id": "U-owner",
            "display_name": "小美",
            "plan": "free",
            "contacts": [{
                "line_user_id": "U-good",
                "binding_status": "accepted",
                "contact_role": "guardian",
                "is_primary": True,
                "priority": 1,
                "notify_methods": ["line"],
            }],
        }
        data_file = self.make_data_file(profile, {
            "sos_pending": {
                "U-owner": {
                    "stage": "sent",
                    "event_id": "old-event",
                    "sent_at": (datetime.now() - timedelta(minutes=30)).isoformat(timespec="seconds"),
                }
            }
        })

        result, status = trigger_sos(
            data_file,
            {"line_user_id": "U-owner"},
            {
                "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
                "LINE_PUSH_SENDER": lambda *_args: {"ok": True},
            },
        )

        self.assertEqual(status, 200)
        self.assertFalse(result["cancel_available"])

    def test_no_line_guardians_still_returns_phone_contacts(self):
        profile = {
            "line_user_id": "U-alone",
            "display_name": "只有電話",
            "plan": "free",
            "contacts": [{"name": "媽媽", "phone": "0987654321", "priority": 1}],
        }
        data_file = self.make_data_file(profile)
        result, status = trigger_sos(
            data_file,
            {"line_user_id": "U-alone"},
            {
                "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
                "LINE_PUSH_SENDER": lambda *_args: {"ok": True},
            },
        )
        self.assertEqual(status, 400)
        self.assertEqual(result["error"], "no bound LINE guardians")
        self.assertEqual(result["phone_only_count"], 1)
        self.assertEqual(result["phone_contacts"][0]["name"], "媽媽")

    def test_bound_guardian_with_line_user_id_can_receive_sos(self):
        """綁定欄位若只寫 line_user_id（無 line_id）仍應可送 SOS，不可誤判邀請家人。"""
        messages = []
        profile = {
            "line_user_id": "U-owner",
            "display_name": "已綁會員",
            "plan": "paid_799",
            "payment_status": "active",
            "paid_until": (datetime.now() + timedelta(days=30)).isoformat(timespec="seconds"),
            "contacts": [{
                "line_user_id": "U-guardian",
                "binding_status": "accepted",
                "consent_status": "accepted",
                "contact_role": "guardian",
                "is_primary": True,
                "priority": 1,
                "notify_methods": ["line"],
            }],
        }
        data_file = self.make_data_file(profile)
        result, status = trigger_sos(data_file, {"line_user_id": "U-owner"}, {
            "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
            "LINE_PUSH_SENDER": lambda _token, _target, message: messages.append(message) or {"ok": True},
        })
        self.assertEqual(status, 200)
        self.assertEqual(result["sent"], 1)
        self.assertEqual(len(messages), 1)

    def test_user_facing_error_hides_english(self):
        msg = sos_user_facing_error("no bound LINE guardians")
        self.assertIn("還沒綁定守護人喔", msg)
        self.assertNotIn("no bound", msg.lower())
        self.assertNotIn("LINE guardians", msg)
        self.assertFalse(msg.endswith("。"))

    def test_profile_completion_reminders_are_private_due_only_and_stop_when_complete(self):
        data_file = self.make_data_file({
            "line_user_id": "U-owner",
            "display_name": "小美",
            "profile_completion_required": True,
            "profile_completion_bound_at": "2026-07-01T09:00:00+08:00",
        })
        sent = []
        config = {
            "DATA_FILE": data_file,
            "LINE_CHANNEL_ACCESS_TOKEN": "token",
            "LINE_PUSH_SENDER": lambda _token, target, message: sent.append((target, message)) or {"ok": True},
            "CRON_NOW": datetime.fromisoformat("2026-07-04T09:00:00"),
        }
        result, code = app_module.send_profile_completion_reminders(config)
        self.assertEqual(code, 200)
        self.assertEqual(result["sent"], 3)  # catch up bind-time, +24h, and day 3 privately.
        self.assertEqual({target for target, _message in sent}, {"U-owner"})
        stored = load_state(data_file)["users"]["U-owner"]
        self.assertEqual(stored["profile_completion_reminder_days"], [0, 1, 3])

        stored["profile_completion_required"] = False
        state = load_state(data_file)
        state["users"]["U-owner"] = stored
        save_state(data_file, state)
        config["CRON_NOW"] = datetime.fromisoformat("2026-07-08T09:00:00")
        stopped, stopped_code = app_module.send_profile_completion_reminders(config)
        self.assertEqual(stopped_code, 200)
        self.assertEqual(stopped["sent"], 0)

    def test_profile_completion_reminder_auto_stops_when_contact_details_are_complete(self):
        data_file = self.make_data_file({
            "line_user_id": "U-owner",
            "display_name": "小美",
            "profile_completion_required": True,
            "profile_completion_bound_at": "2026-07-01T09:00:00+08:00",
            "contacts": [{
                "name": "阿媽",
                "relationship": "母女",
                "phone": "0912345678",
                "line_user_id": "U-guardian",
                "binding_status": "accepted",
            }],
        })
        sent = []
        result, code = app_module.send_profile_completion_reminders({
            "DATA_FILE": data_file,
            "LINE_CHANNEL_ACCESS_TOKEN": "token",
            "LINE_PUSH_SENDER": lambda *_args: sent.append(True) or {"ok": True},
            "CRON_NOW": datetime.fromisoformat("2026-07-04T09:00:00"),
        })
        self.assertEqual(code, 200)
        self.assertEqual(result["sent"], 0)
        self.assertEqual(sent, [])
        stored = load_state(data_file)["users"]["U-owner"]
        self.assertFalse(stored["profile_completion_required"])
        self.assertTrue(stored["profile_completion_completed_at"])


if __name__ == "__main__":
    unittest.main()
