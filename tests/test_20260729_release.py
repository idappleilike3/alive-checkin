import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import app


ROOT = Path(__file__).resolve().parents[1]


class Release20260729Tests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_file = Path(self.temp_dir.name) / "state.json"

    def test_active_trial_matches_paid_199_monthly_rights(self):
        now = datetime(2026, 7, 29, 12, 0, 0)
        profile = {
            "line_user_id": "U-trial",
            "plan": "trial",
            "membership_source": "public_trial",
            "trial_started_at": now.isoformat(timespec="seconds"),
            "trial_end": (now + timedelta(days=14)).isoformat(timespec="seconds"),
        }
        self.assertEqual(app.effective_entitlement_plan(profile, now), "paid_199")
        trial = app.plan_rules(profile, now)
        paid_199 = app.PLAN_LIMITS["paid_199"]
        for key in (
            "contact_limit",
            "emergency_contact_limit",
            "daily_reminders",
            "core_guardian_alert_limit",
            "location_mode",
            "safety_guard_hours",
            "safety_guard_daily_limit",
        ):
            self.assertEqual(trial[key], paid_199[key], key)
        self.assertEqual(trial["guardian_group_limit"], 0)

    def test_status_never_exposes_general_guardian_label(self):
        status = app.build_status({
            "line_user_id": "U-owner",
            "contacts": [{
                "id": "guardian-1",
                "line_user_id": "U-guardian",
                "binding_status": "accepted",
                "contact_role": "guardian",
                "is_primary": False,
            }],
        })
        self.assertEqual(status["general_guardian_count"], 0)
        self.assertEqual(status["bound_guardians"][0]["role"], "核心守護人")
        self.assertNotIn("一般", str(status["bound_guardians"]))

    def test_repeated_binding_keeps_one_relationship(self):
        app.save_state(self.data_file, {
            "users": {
                "U-owner": {
                    "line_user_id": "U-owner",
                    "display_name": "小美",
                    "plan": "paid_199",
                    "contacts": [],
                }
            }
        })
        payload = {
            "inviter_line_user_id": "U-owner",
            "contact_line_user_id": "U-guardian",
            "contact_display_name": "媽媽",
            "contact_relationship": "母女",
            "contact_phone": "0912345678",
        }
        first, first_code = app.bind_emergency_contact(self.data_file, payload)
        second, second_code = app.bind_emergency_contact(self.data_file, payload)
        self.assertEqual(first_code, 200)
        self.assertEqual(second_code, 200)
        self.assertFalse(first["already_bound"])
        self.assertTrue(second["already_bound"])
        state = app.load_state(self.data_file)
        rows = [
            row for row in state["users"]["U-owner"]["contacts"]
            if app.get_contact_line_id(row) == "U-guardian"
        ]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["is_primary"])

    def test_one_way_accepted_core_guardian_receives_sos(self):
        app.save_state(self.data_file, {
            "users": {
                "U-owner": {
                    "line_user_id": "U-owner",
                    "display_name": "小美",
                    "plan": "paid_199",
                    "contacts": [{
                        "name": "媽媽",
                        "line_user_id": "U-guardian",
                        "binding_status": "accepted",
                        "contact_role": "guardian",
                        "is_primary": True,
                        "notify_methods": ["line"],
                    }],
                },
                # Deliberately no reciprocal contact back to U-owner.
                "U-guardian": {"line_user_id": "U-guardian", "contacts": []},
            }
        })
        targets = []
        result, code = app.trigger_sos(
            self.data_file,
            {"line_user_id": "U-owner"},
            {
                "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
                "LINE_PUSH_SENDER": lambda _token, target, _message: (
                    targets.append(target) or {"ok": True}
                ),
                "CRON_NOW": datetime(2026, 7, 29, 12, 0, 0),
            },
        )
        self.assertEqual(code, 200)
        self.assertEqual(result["sent"], 1)
        self.assertIn("U-guardian", targets)
        self.assertEqual(result["guardians"][0]["status"], "sent")

    def test_disabled_smart_reminder_is_not_sent(self):
        now = datetime(2026, 7, 29, 12, 0, 0)
        app.save_state(self.data_file, {
            "users": {
                "U-799": {
                    "line_user_id": "U-799",
                    "plan": "paid_799",
                    "payment_status": "active",
                    "paid_until": "2099-01-01T00:00:00",
                    "smart_reminders": [{
                        "id": "sr-disabled",
                        "target_name": "媽媽",
                        "category": "checkup",
                        "month": 7,
                        "day": 29,
                        "year": 2026,
                        "remind_time": "09:00",
                        "enabled": False,
                    }],
                }
            }
        })
        sent = []
        result, code = app.send_smart_reminders({
            "DATA_FILE": self.data_file,
            "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
            "LINE_PUSH_SENDER": lambda *_args: sent.append(_args) or {"ok": True},
            "CRON_NOW": now,
            "APP_TIMEZONE": "Asia/Taipei",
        })
        self.assertEqual(code, 200)
        self.assertEqual(result["sent"], 0)
        self.assertEqual(sent, [])

    def test_five_pages_and_native_controls_are_present(self):
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        member = (ROOT / "liff" / "member.html").read_text(encoding="utf-8")
        trial = (ROOT / "trial-14.html").read_text(encoding="utf-8")
        beta = (ROOT / "beta-register.html").read_text(encoding="utf-8")
        share = (ROOT / "liff" / "share-invite.html").read_text(encoding="utf-8")
        self.assertIn("14 天免費體驗｜199 活著版", trial)
        self.assertIn("399 年費安心版｜21 天封測", beta)
        self.assertIn("799 年費守護版｜21 天封測", beta)
        self.assertIn("一鍵分享邀請核心守護人", share)
        self.assertIn('id="calendarNoteQuickCard"', index)
        self.assertIn("先新增日期與備忘，系統才會在指定時間提醒", index)
        self.assertIn("toggleSmartReminder", index)
        self.assertIn('id="guardianDataBlock"', member)
        self.assertIn('id="emergencyDataBlock"', member)
        self.assertNotIn(
            '<script src="/assets/ux-fixes-20260729.js"></script>',
            index + member + trial + beta + share,
        )

    def test_help_has_visual_checkin_dialogue_sop(self):
        page = (ROOT / "help.html").read_text(encoding="utf-8")
        self.assertIn("assets/help-checkin-sop.gif", page)
        self.assertIn("核心守護人會收到", page)
        self.assertIn("不是只有一個打勾", page)
        self.assertIn("open=checkin", page)
        self.assertIn("一鍵邀請守護人", page)

    def test_line_id_token_is_never_added_to_url(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        auth_query = page.split("async function withAuthQuery(url)", 1)[1].split(
            "async function apiGetStatus", 1
        )[0]
        self.assertIn("return url;", auth_query)
        self.assertNotIn("id_token=", auth_query)

    def test_line_in_app_login_is_automatic_with_external_fallback(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('typeof liff.isInClient === "function"', page)
        self.assertIn("&& liff.isInClient()", page)
        self.assertIn("startLineLogin(readSafeDeepLinkParams());", page)
        self.assertIn("只有外部瀏覽器或自動登入失敗時", page)

    def test_member_center_render_does_not_call_missing_date_formatter(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("formatMemberDate(", page)
        self.assertIn(
            'formatGuardianAddedAt({ accepted_at: row?.accepted_at || "" })',
            page,
        )

    def test_responsive_touch_targets_and_hidden_smart_reminder_banner(self):
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        trial = (ROOT / "trial-14.html").read_text(encoding="utf-8")
        beta = (ROOT / "beta-register.html").read_text(encoding="utf-8")
        pricing = (ROOT / "liff" / "pricing.html").read_text(encoding="utf-8")
        self.assertIn(".member-limit-banner[hidden] { display: none !important; }", index)
        self.assertIn("min-height: 48px;", index)
        self.assertIn("min-height:44px", trial)
        self.assertIn("min-height:44px", beta)
        self.assertIn("min-height: 48px;", pricing)

    def test_member_contact_arrows_and_guarding_empty_state_are_clear(self):
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        member = (ROOT / "liff" / "member.html").read_text(encoding="utf-8")
        self.assertIn("member-contact-tab-arrow", index)
        self.assertIn('aria-expanded="false"', index)
        self.assertIn("目前尚未守護其他人", index)
        self.assertIn("一鍵邀請守護人", index)
        self.assertIn("點擊展開", member)
        self.assertIn("點擊收合", member)

    def test_399_and_799_onboarding_fall_back_to_two_default_times(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        onboarding = (ROOT / "liff" / "onboarding.html").read_text(encoding="utf-8")
        profile = {
            "line_user_id": "U-799-default",
            "plan": "paid_799",
            "payment_status": "active",
            "paid_until": "2099-01-01T00:00:00",
        }
        payload, code = app.onboarding_status_payload(
            self.data_file, profile["line_user_id"], allow_missing_profile=True
        )
        # Missing profiles retain the safe one-reminder default.
        self.assertEqual(code, 200)
        self.assertEqual(payload["default_reminder_times"], ["12:00"])

        app.save_state(self.data_file, {"users": {profile["line_user_id"]: profile}})
        payload, code = app.onboarding_status_payload(
            self.data_file, profile["line_user_id"]
        )
        self.assertEqual(code, 200)
        self.assertEqual(payload["daily_reminders"], 3)
        self.assertEqual(payload["default_reminder_times"], ["12:00", "18:00"])
        self.assertIn("onboardingDefaultReminderCount", page)
        self.assertIn("399／799 預設每日 2 次", page)
        self.assertIn("之後可到「我的會員」修改次數與時間", onboarding)


if __name__ == "__main__":
    unittest.main()
