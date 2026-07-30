from pathlib import Path
import json
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RichMenuTrialShareTests(unittest.TestCase):
    def test_rich_menu_uses_dedicated_trial_share_entry(self):
        menu = json.loads((ROOT / "line-rich-menu-config.json").read_text(encoding="utf-8"))
        invite = next(
            area["action"]
            for area in menu["areas"]
            if area["action"].get("label") == "一鍵邀請"
        )

        self.assertEqual(invite["type"], "uri")
        self.assertEqual(
            invite["uri"],
            "https://alive-checkin.onrender.com/liff/share-trial.html",
        )
        self.assertNotIn("share-invite", invite["uri"])

    def test_trial_share_page_does_not_create_guardian_invite(self):
        page = (ROOT / "liff" / "share-trial.html").read_text(encoding="utf-8")

        self.assertIn("liff.shareTargetPicker", page)
        self.assertIn("/api/member/exists", page)
        self.assertIn("/trial-14.html", page)
        self.assertIn("alive_member_status_v1:", page)
        self.assertNotIn("/api/emergency-contact/invite", page)
        self.assertNotIn("invite_token", page)
        self.assertNotIn("invite_from", page)

    def test_backend_serves_trial_share_and_checks_membership_without_registering(self):
        backend = (ROOT / "app.py").read_text(encoding="utf-8")

        self.assertIn('@app.get("/liff/share-trial.html")', backend)
        self.assertIn('@app.get("/api/member/exists")', backend)
        exists_flow = backend.split(
            '@app.get("/api/member/exists")', 1
        )[1].split('@app.', 1)[0]
        self.assertIn('"registered": bool(profile)', exists_flow)
        self.assertNotIn("register_line_user", exists_flow)
        self.assertNotIn("status_for_user", exists_flow)

    def test_render_startup_syncs_rich_menu_only_when_outdated(self):
        backend = (ROOT / "app.py").read_text(encoding="utf-8")

        self.assertIn("def sync_default_rich_menu_if_needed", backend)
        flow = backend.split(
            "def sync_default_rich_menu_if_needed", 1
        )[1].split("\\ndef ", 1)[0]
        self.assertIn("inspect_default_rich_menu", flow)
        self.assertIn('current.get("invite_uri_ok")', flow)
        self.assertIn("deploy_default_rich_menu", flow)
        self.assertIn("threading.Thread(", backend)
        self.assertIn('app.config.get("TESTING") is True', backend)


if __name__ == "__main__":
    unittest.main()
