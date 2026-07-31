from pathlib import Path
import json
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RichMenuTrialShareTests(unittest.TestCase):
    def test_rich_menu_uses_dedicated_guardian_share_entry(self):
        menu = json.loads((ROOT / "line-rich-menu-config.json").read_text(encoding="utf-8"))
        invite = next(
            area["action"]
            for area in menu["areas"]
            if area["action"].get("label") == "一鍵邀請"
        )

        self.assertEqual(invite["type"], "uri")
        self.assertEqual(
            invite["uri"],
            "https://liff.line.me/2010848330-UAiqPPYD?open=share-invite",
        )
        self.assertIn("share-invite", invite["uri"])

    def test_trial_share_uses_cached_liff_identity_without_profile_round_trip(self):
        page = (ROOT / "liff" / "share-trial.html").read_text(encoding="utf-8")

        self.assertIn("liff.getDecodedIDToken()", page)
        self.assertIn("decoded.sub", page)
        self.assertNotIn("await liff.getProfile()", page)

    def test_trial_share_only_reveals_web_fallback_when_native_picker_cannot_open(self):
        page = (ROOT / "liff" / "share-trial.html").read_text(encoding="utf-8")

        self.assertIn('id="shareFallback"', page)
        self.assertNotIn('id="shareFallback" hidden', page)
        self.assertIn("shareFallback.hidden = false", page)

    def test_trial_share_shows_progress_before_opening_line_picker(self):
        page = (ROOT / "liff" / "share-trial.html").read_text(encoding="utf-8")

        self.assertIn('id="shareSpinner"', page)
        self.assertIn('role="status"', page)
        self.assertIn("正在準備你的專屬分享連結", page)
        self.assertIn("正在開啟 LINE 好友選擇", page)
        self.assertIn("setLoadingState(true", page)
        self.assertIn("setLoadingState(false", page)

    def test_trial_share_uses_a_visual_card_with_clear_relationship_copy(self):
        page = (ROOT / "liff" / "share-trial.html").read_text(encoding="utf-8")

        self.assertIn('class="trial-share-card"', page)
        self.assertIn("想把 14 天安心體驗分享給你", page)
        self.assertIn('"type": "flex"', page)
        self.assertIn('"type": "bubble"', page)
        self.assertIn("開始我的 14 天安心體驗", page)
        self.assertIn("這是你的每日平安體驗", page)
        self.assertIn("不會自動互相綁定", page)
        self.assertIn("不會自動扣款", page)

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


if __name__ == "__main__":
    unittest.main()
