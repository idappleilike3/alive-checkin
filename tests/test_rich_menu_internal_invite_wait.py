import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RichMenuInternalInviteWaitTests(unittest.TestCase):
    def test_rich_menu_opens_guardian_invite_liff(self):
        menu = json.loads(
            (ROOT / "line-rich-menu-config.json").read_text(encoding="utf-8")
        )
        invite = next(
            area["action"]
            for area in menu["areas"]
            if area["action"]["label"] == "一鍵邀請"
        )
        self.assertEqual(
            invite["uri"],
            "https://liff.line.me/2010848330-UAiqPPYD?open=share-invite",
        )

    def test_internal_invite_waits_visibly_until_liff_is_ready(self):
        page = (ROOT / "liff/share-invite.html").read_text(encoding="utf-8")
        self.assertIn('id="shareSpinner"', page)
        self.assertIn("LINE 開啟可能需要 5–10 秒，請不要關閉頁面", page)
        self.assertIn('id="startShare" type="button" disabled', page)
        self.assertIn("startShareBtn.disabled = false", page)
        self.assertNotIn("if (isInsideLine() && !shareAttempted)", page)

    def test_guardian_and_trial_share_remain_separate(self):
        guardian = (ROOT / "liff/share-invite.html").read_text(encoding="utf-8")
        trial = (ROOT / "liff/share-trial.html").read_text(encoding="utf-8")
        self.assertIn("我想邀請你成為我的安心守護人", guardian)
        self.assertIn("這次只會由你守護我，不會自動互相綁定", guardian)
        self.assertIn("送你 14 天安心體驗", trial)
        self.assertNotIn("送你 14 天安心體驗", guardian)


if __name__ == "__main__":
    unittest.main()
