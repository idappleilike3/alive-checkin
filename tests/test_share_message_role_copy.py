from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ShareMessageRoleCopyTests(unittest.TestCase):
    def test_guardian_invite_message_asks_recipient_to_guard_sender(self):
        page = (ROOT / "liff" / "share-invite.html").read_text(encoding="utf-8")

        self.assertIn("❤️ 我想邀請你成為我的安心守護人", page)
        self.assertIn("因為你是我信任的人", page)
        self.assertIn("平常不打擾，只有需要時才通知你", page)
        self.assertIn("點開連結，確認是否願意守護我", page)
        self.assertIn("不會自動互相綁定", page)
        self.assertNotIn("14 天免費體驗｜199 活著版", page)

    def test_trial_share_message_invites_recipient_to_start_own_checkins(self):
        share_page = (ROOT / "liff" / "share-trial.html").read_text(encoding="utf-8")
        member_page = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn("想把 14 天安心體驗分享給你", share_page)
        self.assertIn("每天只要 10 秒報平安", share_page)
        self.assertIn("這是你的每日平安體驗", share_page)
        self.assertIn("不會自動扣款", share_page)
        self.assertIn("不會自動互相綁定", share_page)
        self.assertIn("🌿 送你 14 天安心體驗", member_page)
        self.assertIn("需要邀請至少一位親友成為你的守護人", member_page)


if __name__ == "__main__":
    unittest.main()
