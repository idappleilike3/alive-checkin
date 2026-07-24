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
        self.assertIn("hasHomeSetupComplete(currentGuardianContacts())", page)
        self.assertIn("const homeReady = hasHomeSetupComplete(contactsNow);", page)
        # 一般登入不再於 LIFF init 立刻彈守護提示（等 contacts）
        init_line = page[
            page.index("async function initializeLiff()") : page.index("const LUNAR_DAY_NAMES")
        ]
        self.assertNotIn("maybeShowGuardianPrompt();", init_line)
        self.assertIn("maybeShowInviteAcceptPrompt();", init_line)

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


if __name__ == "__main__":
    unittest.main()
