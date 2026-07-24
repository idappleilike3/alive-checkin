"""Bind persistence fields + home gate helpers."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import app as app_module


ROOT = Path(__file__).resolve().parents[1]


class BindAndHomeGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_file = str(Path(self.tmp.name) / "state.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_bind_writes_line_user_id_and_invite_edge(self):
        result, code = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-inviter",
                "contact_line_user_id": "U-guardian",
                "contact_display_name": "阿媽",
            },
            config={},
        )
        self.assertEqual(code, 200)
        self.assertTrue(result["bound"])
        contact = result["contact"]
        self.assertEqual(contact["line_id"], "U-guardian")
        self.assertEqual(contact["line_user_id"], "U-guardian")
        self.assertEqual(contact["binding_status"], "accepted")
        self.assertEqual(contact["invited_by"], "U-inviter")

        state = app_module.load_state(self.data_file)
        inviter = state["users"]["U-inviter"]
        guardian = state["users"]["U-guardian"]
        self.assertEqual(len(inviter["contacts"]), 1)
        self.assertIn("U-inviter", guardian.get("guarding_for") or [])
        self.assertEqual(guardian.get("invited_by"), "U-inviter")
        self.assertEqual(len(state.get("contact_rewards") or []), 1)

        summary = app_module.admin_summary(self.data_file)
        self.assertEqual(summary["bound_guardian_total"], 1)
        self.assertEqual(len(summary["invite_edges"]), 1)
        self.assertEqual(summary["invite_edges"][0]["inviter_line_user_id"], "U-inviter")
        self.assertEqual(summary["invite_edges"][0]["guardian_line_user_id"], "U-guardian")
        self.assertIn("persistence", summary)

    def test_bind_matches_legacy_line_user_id_field(self):
        state = app_module.load_state(self.data_file)
        inviter = app_module.get_profile(state, "U-inviter")
        inviter["contacts"] = [
            {
                "id": "contact-1",
                "name": "舊格式",
                "relationship": "家人",
                "phone": "0912345678",
                "line_user_id": "U-guardian",
                "binding_status": "unbound",
            }
        ]
        app_module.save_state(self.data_file, state)

        result, code = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-inviter",
                "contact_line_user_id": "U-guardian",
                "contact_display_name": "阿媽",
            },
            config={},
        )
        self.assertEqual(code, 200)
        self.assertTrue(result["already_bound"])
        state2 = app_module.load_state(self.data_file)
        contacts = state2["users"]["U-inviter"]["contacts"]
        self.assertEqual(len(contacts), 1)
        self.assertEqual(contacts[0]["binding_status"], "accepted")
        self.assertEqual(contacts[0]["line_id"], "U-guardian")

    def test_home_gate_helpers_exist_in_spa(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("function hasHomeSetupComplete(", page)
        self.assertIn("function hasLineBoundGuardian(", page)
        self.assertIn("hasHomeSetupComplete(currentGuardianContacts())", page)
        self.assertIn("const homeReady = hasHomeSetupComplete(contactsNow);", page)
        # LINE 綁定即可進首頁（不再要求聯絡人電話）
        gate = page[page.index("function hasHomeSetupComplete(") : page.index("function closeGuardianPrompt(")]
        self.assertIn("return hasLineBoundGuardian(contacts);", gate)
        self.assertNotIn("hasContactProfile", gate)
        # 一般登入不再於 LIFF init 立刻彈守護提示（等 contacts）
        init_line = page[
            page.index("async function initializeLiff()") : page.index("const LUNAR_DAY_NAMES")
        ]
        self.assertNotIn("maybeShowGuardianPrompt();", init_line)
        self.assertIn("maybeShowInviteAcceptPrompt();", init_line)

    def test_admin_summary_exposes_bound_guardians(self):
        app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-inviter",
                "contact_line_user_id": "U-guardian",
                "contact_display_name": "阿媽",
            },
            config={},
        )
        summary = app_module.admin_summary(self.data_file)
        inviter = next(u for u in summary["users"] if u["line_user_id"] == "U-inviter")
        self.assertEqual(inviter["bound_guardian_count"], 1)
        self.assertEqual(inviter["bound_guardians"][0]["line_user_id"], "U-guardian")
        self.assertEqual(summary["bound_guardian_total"], 1)
        self.assertEqual(len(summary["invite_edges"]), 1)

    def test_admin_html_renders_bind_panels(self):
        page = (ROOT / "admin.html").read_text(encoding="utf-8")
        self.assertIn("boundGuardians", page)
        self.assertIn("inviteEdgeList", page)
        self.assertIn("formatBoundGuardiansCell", page)
        self.assertIn("membershipCell", page)
        self.assertIn("已綁定守護人", page)
        self.assertIn("autoRefreshAdmin", page)

    def test_per_user_invite_link_format(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        share = (ROOT / "liff" / "share-invite.html").read_text(encoding="utf-8")
        self.assertIn("invite_from: safeId", page)
        self.assertIn('?invite_from=" + encodeURIComponent(safeId)', share)
        self.assertIn("buildContactInvite", page)

    def test_resolve_data_file_honors_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = str(Path(tmp) / "state.json")
            resolved = app_module.resolve_data_file(target)
            self.assertEqual(resolved, target)


    def test_duplicate_bind_returns_already_bound_not_limit_error(self):
        pushed = []

        def fake_sender(token, line_user_id, message):
            pushed.append((line_user_id, message))
            return {"ok": True, "status": 200}

        first, code1 = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-inviter",
                "contact_line_user_id": "U-guardian",
                "contact_display_name": "寶寶",
            },
            config={"LINE_CHANNEL_ACCESS_TOKEN": "tok", "LINE_PUSH_SENDER": fake_sender},
        )
        self.assertEqual(code1, 200)
        self.assertTrue(first["bound"])
        self.assertFalse(first["already_bound"])
        self.assertEqual(len(pushed), 2)
        self.assertIn("守護人綁定完成", pushed[0][1])
        self.assertIn("你已接受邀請", pushed[1][1])

        second, code2 = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-inviter",
                "contact_line_user_id": "U-guardian",
                "contact_display_name": "寶寶",
            },
            config={"LINE_CHANNEL_ACCESS_TOKEN": "tok", "LINE_PUSH_SENDER": fake_sender},
        )
        self.assertEqual(code2, 200)
        self.assertTrue(second["already_bound"])
        self.assertIn("已經是守護人", second["message"])
        self.assertEqual(len(pushed), 2)  # no second notify storm

    def test_limit_full_without_match_returns_chinese(self):
        state = app_module.load_state(self.data_file)
        inviter = app_module.get_profile(state, "U-inviter")
        inviter["contacts"] = [
            {
                "id": "c1",
                "name": "別人",
                "relationship": "家人",
                "phone": "0911111111",
                "line_id": "U-other",
                "line_user_id": "U-other",
                "binding_status": "accepted",
                "consent_status": "accepted",
                "is_primary": True,
            }
        ]
        app_module.save_state(self.data_file, state)
        result, code = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-inviter",
                "contact_line_user_id": "U-new",
                "contact_display_name": "新人",
            },
            config={},
        )
        self.assertEqual(code, 400)
        self.assertEqual(result.get("code"), "contact_limit")
        self.assertNotIn("exceeded", str(result.get("error") or "").lower())
        self.assertIn("名額", result.get("message") or result.get("error") or "")

    def test_merge_unbound_slot_when_limit_full(self):
        state = app_module.load_state(self.data_file)
        inviter = app_module.get_profile(state, "U-inviter")
        inviter["contacts"] = [
            {
                "id": "c1",
                "name": "寶寶",
                "relationship": "家人",
                "phone": "0912345678",
                "line_id": "",
                "binding_status": "unbound",
                "is_primary": True,
            }
        ]
        app_module.save_state(self.data_file, state)
        result, code = app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-inviter",
                "contact_line_user_id": "U-guardian",
                "contact_display_name": "寶寶LINE",
            },
            config={},
        )
        self.assertEqual(code, 200)
        self.assertTrue(result["bound"])
        state2 = app_module.load_state(self.data_file)
        contacts = state2["users"]["U-inviter"]["contacts"]
        self.assertEqual(len(contacts), 1)
        self.assertEqual(contacts[0]["line_user_id"], "U-guardian")
        self.assertEqual(contacts[0]["binding_status"], "accepted")

    def test_admin_summary_membership_and_core_counts(self):
        app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-inviter",
                "contact_line_user_id": "U-guardian",
                "contact_display_name": "寶寶",
            },
            config={},
        )
        summary = app_module.admin_summary(self.data_file)
        inviter = next(u for u in summary["users"] if u["line_user_id"] == "U-inviter")
        self.assertEqual(inviter["bound_guardian_count"], 1)
        self.assertGreaterEqual(inviter["core_guardian_count"], 1)
        self.assertIn("trial_days_text", inviter)
        self.assertIn("upgrade_status", inviter)
        self.assertIn("membership_label", inviter)

    def test_member_center_list_before_add_markers(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("目前守護人", page)
        self.assertIn("memberGuardianQuotaLine", page)
        self.assertIn("memberGuardianLimitBanner", page)
        self.assertIn("你已經有", page)
        self.assertIn("核心守護人", page)
        self.assertIn("➕ 新增守護人", page)
        self.assertIn("名額已滿", page)
        admin = (ROOT / "admin.html").read_text(encoding="utf-8")
        self.assertIn("membershipCell", admin)
        self.assertIn("免費剩幾天", admin)
        self.assertIn("核心／一般", admin)


if __name__ == "__main__":
    unittest.main()
