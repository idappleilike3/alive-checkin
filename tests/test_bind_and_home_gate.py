"""Bind persistence fields + home gate helpers."""
from __future__ import annotations

import os
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
        self.assertIn("function hasAnyGuardianOrContact(", page)
        self.assertIn("function syncInviteUiForBoundState(", page)
        self.assertIn("hasHomeSetupComplete(currentGuardianContacts())", page)
        self.assertIn("const homeReady = hasHomeSetupComplete(contactsNow);", page)
        self.assertIn("hasAnyGuardianOrContact(contactsNow)", page)
        self.assertIn("mvpRewardInviteCard", page)
        self.assertIn("mvpGuardInviteCard", page)
        self.assertIn("isCheckinOpen", page)
        self.assertIn("isGuardOpen", page)
        self.assertIn('openAction === "checkin" && (homeReady || hasGuardians)', page)
        self.assertNotIn("if (isCheckinOpen || isGuardOpen || forceOnboarding)", page)
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
        init_app = page[page.rindex("async function initApp()") : page.index("// ===== D01")]
        self.assertIn("homeReady || hasGuardians || setupDone", init_app)
        self.assertIn("syncInviteUiForBoundState(homeReady || hasGuardians)", init_app)
        # 報平安／安全守護不得被 wantsInviteShare 帶走；一鍵邀請才進分享頁
        self.assertTrue(
            'location.replace("/liff/share-invite.html")' in init_app
            or "buildShareInvitePageUrl(" in init_app
        )
        self.assertIn("僅「一鍵邀請」", init_app)

    def test_form_add_does_not_copy_owner_line_id(self):
        state = app_module.load_state(self.data_file)
        app_module.get_profile(state, "U-owner")
        app_module.save_state(self.data_file, state)
        result, code = app_module.add_single_contact(
            self.data_file,
            "U-owner",
            {
                "line_user_id": "U-owner",  # auth field — must NOT become guardian LINE id
                "name": "寶寶",
                "relationship": "家人",
                "phone": "0912345678",
            },
        )
        self.assertEqual(code, 200)
        contact = result["contact"]
        self.assertEqual(contact.get("line_user_id") or "", "")
        self.assertEqual(contact.get("line_id") or "", "")
        self.assertEqual(contact.get("binding_status"), "unbound")
        self.assertFalse(app_module.contact_is_bound_guardian(contact, "U-owner"))
        status = app_module.build_status(app_module.load_state(self.data_file)["users"]["U-owner"])
        self.assertEqual(status["bound_guardian_count"], 0)
        self.assertEqual(status["contact_count"], 1)

    def test_scrub_self_line_id_fake_bind(self):
        state = app_module.load_state(self.data_file)
        user = app_module.get_profile(state, "U-jennie")
        user["contacts"] = [
            {
                "id": "contact-1",
                "name": "假綁定",
                "relationship": "家人",
                "phone": "0926568873",
                "line_user_id": "U-jennie",
                "binding_status": "unbound",
            }
        ]
        app_module.save_state(self.data_file, state)
        contacts = app_module.get_contacts(self.data_file, "U-jennie")
        self.assertEqual(contacts["contacts"][0].get("line_user_id") or "", "")
        status = app_module.build_status(app_module.load_state(self.data_file)["users"]["U-jennie"])
        self.assertEqual(status["bound_guardian_count"], 0)
        self.assertEqual(status["contact_count"], 1)

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

    def test_persistence_info_marks_postgres_durable(self):
        old = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = "postgresql://user:pass@localhost/db"
        try:
            info = app_module.persistence_info("/opt/render/project/src/data/state.json")
            self.assertTrue(info["durable"])
            self.assertEqual(info["backend"], "postgres")
            self.assertEqual(info["ephemeral_warning"], "")
        finally:
            if old is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = old

    def test_bind_writes_guarding_details_on_invitee(self):
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
        state = app_module.load_state(self.data_file)
        guardian = state["users"]["U-guardian"]
        self.assertEqual(guardian.get("invited_by"), "U-inviter")
        details = guardian.get("guarding_details") or []
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]["line_user_id"], "U-inviter")
        status = app_module.build_status(guardian)
        self.assertEqual(status["guarding_details"][0]["line_user_id"], "U-inviter")
        contact = result["contact"]
        self.assertEqual(contact.get("contact_role"), "guardian")
        self.assertEqual(contact.get("relationship"), "守護人")


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
        # 模擬真實暱稱寫入
        state = app_module.load_state(self.data_file)
        state["users"]["U-inviter"]["display_name"] = "小美"
        app_module.save_state(self.data_file, state)
        summary = app_module.admin_summary(self.data_file)
        inviter = next(u for u in summary["users"] if u["line_user_id"] == "U-inviter")
        self.assertEqual(inviter["bound_guardian_count"], 1)
        self.assertGreaterEqual(inviter["core_guardian_count"], 1)
        self.assertIn("trial_days_text", inviter)
        self.assertIn("upgrade_status", inviter)
        self.assertIn("membership_label", inviter)
        self.assertEqual(inviter["display_name"], "小美")
        self.assertIn("plan_expires_text", inviter)
        self.assertIn("到期", inviter["plan_expires_text"])
        self.assertFalse(inviter.get("display_name_missing"))

    def test_admin_placeholder_name_marked(self):
        state = app_module.load_state(self.data_file)
        user = app_module.get_profile(state, "U-anon")
        user["display_name"] = "LINE 使用者"
        app_module.save_state(self.data_file, state)
        summary = app_module.admin_summary(self.data_file)
        anon = next(u for u in summary["users"] if u["line_user_id"] == "U-anon")
        self.assertTrue(anon.get("display_name_missing"))
        self.assertNotEqual(anon.get("display_name"), "LINE 使用者")
        self.assertIn("未取得暱稱", anon.get("display_name"))
        page = (ROOT / "admin.html").read_text(encoding="utf-8")
        self.assertIn("memberNameCell", page)
        self.assertIn("plan_expires_text", page)
        self.assertIn("方案到期（試用／訂閱）", page)

    def test_reregister_preserves_trial_and_bindings(self):
        """Re-login must NOT restart trial clock or wipe contacts."""
        first, code1 = app_module.register_line_user(
            self.data_file,
            {"line_user_id": "U-persist", "display_name": "小孟"},
        )
        self.assertEqual(code1, 200)
        started = first.get("trial_started_at")
        self.assertTrue(started)

        # Bind a guardian then re-register as if LIFF reopened.
        app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-persist",
                "contact_line_user_id": "U-guard-1",
                "contact_display_name": "阿爸",
            },
            config={},
        )
        # Simulate clock advancing: mutate stored trial to a fixed past value.
        state = app_module.load_state(self.data_file)
        state["users"]["U-persist"]["trial_started_at"] = "2026-07-20T10:00:00"
        state["users"]["U-persist"]["history"] = ["2026-07-21", "2026-07-22"]
        app_module.save_state(self.data_file, state)

        second, code2 = app_module.register_line_user(
            self.data_file,
            {"line_user_id": "U-persist", "display_name": "小孟"},
        )
        self.assertEqual(code2, 200)
        self.assertTrue(second.get("existing_user"))
        self.assertEqual(second.get("trial_started_at"), "2026-07-20T10:00:00")
        self.assertEqual(second.get("trial_days_left"), app_module.trial_days_left(
            {"trial_started_at": "2026-07-20T10:00:00", "plan": "trial"}
        ))
        contacts = second.get("contacts") or []
        self.assertEqual(len(contacts), 1)
        self.assertEqual(app_module.get_contact_line_id(contacts[0]), "U-guard-1")
        self.assertIn("2026-07-21", second.get("history") or [])

    def test_save_contacts_merges_binding_fields(self):
        app_module.register_line_user(
            self.data_file, {"line_user_id": "U-owner", "display_name": "主人"}
        )
        app_module.bind_emergency_contact(
            self.data_file,
            {
                "inviter_line_user_id": "U-owner",
                "contact_line_user_id": "U-g1",
                "contact_display_name": "阿媽",
            },
            config={},
        )
        state = app_module.load_state(self.data_file)
        contact = state["users"]["U-owner"]["contacts"][0]
        contact_id = contact["id"]

        # Client payload omits LINE bind fields (common after form edit).
        result, code = app_module.save_contacts(
            self.data_file,
            {
                "line_user_id": "U-owner",
                "contacts": [
                    {
                        "id": contact_id,
                        "name": "阿媽改名",
                        "relationship": "媽媽",
                        "phone": "0911111111",
                        "contact_role": "guardian",
                    }
                ],
            },
        )
        self.assertEqual(code, 200)
        saved = result["contacts"][0]
        self.assertEqual(saved["name"], "阿媽改名")
        self.assertEqual(app_module.get_contact_line_id(saved), "U-g1")
        self.assertEqual(saved.get("binding_status"), "accepted")


    def test_member_center_list_before_add_markers(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertTrue(
            "守護人（Guardian）" in page or "核心守護人" in page,
            "guardian section title missing",
        )
        self.assertIn("memberGuardianQuotaLine", page)
        self.assertIn("memberGuardianLimitBanner", page)
        self.assertIn("memberEmergencySection", page)
        self.assertIn("你已經有", page)
        self.assertIn("ensureSyncedContactData", page)
        self.assertIn("contact_role", page)
        # 不可再用 role（核心／一般）當成 contact_role
        self.assertIn("不可讀 role", page)
        self.assertIn("memberAddGuardianBtn", page)
        self.assertTrue(
            "➕ 新增核心守護人" in page or "➕ 新增守護人" in page,
            "member add guardian button missing",
        )
        self.assertTrue(
            "➕ 新增聯絡人" in page or "➕ 新增緊急聯絡人" in page,
            "member add contact button missing",
        )
        self.assertIn("名額已滿", page)
        share = (ROOT / "liff" / "share-invite.html").read_text(encoding="utf-8")
        self.assertIn("goNextStep", share)
        self.assertTrue(
            "完成，返回原位置" in share or "完成，回首頁" in share,
            "share done CTA missing",
        )
        admin = (ROOT / "admin.html").read_text(encoding="utf-8")
        self.assertIn("membershipCell", admin)
        self.assertIn("免費剩幾天", admin)
        self.assertIn("核心／一般", admin)
        self.assertIn("資料可能因重啟遺失請掛磁碟", admin)

    def test_contact_role_ignores_core_general_role_field(self):
        """根因：role=核心／一般 被誤當 contact_role → 列表被濾空。"""
        self.assertEqual(
            app_module.resolve_contact_role({"role": "一般", "name": "阿媽"}),
            "guardian",
        )
        self.assertEqual(
            app_module.resolve_contact_role({"role": "核心", "name": "阿爸"}),
            "guardian",
        )
        self.assertEqual(
            app_module.resolve_contact_role({"contact_role": "emergency", "role": "核心"}),
            "emergency",
        )
        normalized = app_module.normalize_contact(
            {"name": "阿媽", "relationship": "媽媽", "phone": "0912345678", "role": "一般"},
            0,
        )
        self.assertEqual(normalized["contact_role"], "guardian")
        self.assertNotIn("role", normalized)


if __name__ == "__main__":
    unittest.main()
