from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def page():
    return (ROOT / "invite.html").read_text(encoding="utf-8")


class InviteEmotionalGuardianV2Tests(unittest.TestCase):
    def test_invite_leads_with_a_warm_trust_based_message(self):
        html = page()
        self.assertIn("我在乎的人，邀請你成為我的安心守護者", html)
        self.assertIn("因為你是我最信任的人", html)
        self.assertIn("這不是責任，而是一個讓彼此都安心的默契", html)
        self.assertIn("你的存在，就是最好的守護", html)

    def test_invite_reveals_the_real_inviter_name_and_relationship(self):
        html = page()
        self.assertIn('id="inviterName"', html)
        self.assertIn('id="inviterRelationship"', html)
        self.assertIn('params.get("inviter_name")', html)
        self.assertIn('params.get("inviter_relationship")', html)
        self.assertIn("開啟 LINE 後確認", html)

    def test_invite_has_the_four_step安心_journey_and_primary_consent(self):
        html = page()
        for text in (
            "開啟安心頻道",
            "確認你的身分",
            "讓他知道是你",
            "完成守護約定",
            "點我，開啟守護連線 💚",
            "我願意守護 ❤️",
        ):
            self.assertIn(text, html)
        self.assertIn("請填寫你希望被稱呼的名字", html)
        self.assertIn("邀請人是你的...？", html)
        self.assertIn("留下聯絡電話（以備萬一，讓我們能緊急找到你）", html)

    def test_invite_keeps_own_trial_secondary_and_removes_distracting_demo(self):
        html = page()
        self.assertIn("完成守護後，如果你也希望有人關心你的每日平安", html)
        self.assertIn("開始你的 14 天免費體驗", html)
        self.assertIn('class="trial-link"', html)
        self.assertNotIn("真實使用情境", html)
        self.assertNotIn("點一下，體驗報平安", html)
        self.assertNotIn('id="demoCheckinButton"', html)

    def test_invite_preserves_guardian_binding_parameters_and_fallbacks(self):
        html = page()
        self.assertIn('q.set("invite_from", inviteFrom)', html)
        self.assertIn('q.set("invite_token", inviteToken)', html)
        self.assertIn('q.set("inviter_name", inviterName)', html)
        self.assertIn('q.set("return_to", "guardian_binding")', html)
        self.assertIn("複製 LINE 連結", html)
        self.assertIn("查看完整守護說明", html)

    def test_logged_in_invite_relationship_is_a_ranked_select_with_other_input(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        form = html.split('id="inviteAcceptPrompt"', 1)[1].split('id="guardianBindSuccessPrompt"', 1)[0]
        self.assertIn("您的邀請人關係（必填）", form)
        self.assertIn('<select id="inviteGuardianRelationship"', form)
        expected = ["爸爸", "媽媽", "哥哥", "姐姐", "弟弟", "妹妹", "老公", "老婆", "兒子", "女兒", "其他"]
        positions = [form.index(f'value="{relationship}"') for relationship in expected]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('id="inviteGuardianRelationshipOther"', form)
        self.assertIn("選擇「其他」後請自行填寫", form)
        self.assertIn('["inviteGuardianRelationship", "inviteGuardianRelationshipOther"]', html)
        self.assertIn(
            'readRelationship("inviteGuardianRelationship", "inviteGuardianRelationshipOther")',
            html,
        )

    def test_shared_entry_pages_show_immediate_waiting_feedback(self):
        invite = page()
        trial = (ROOT / "trial-14.html").read_text(encoding="utf-8")
        self.assertIn('id="entryLoading"', invite)
        self.assertIn("正在載入你的專屬守護邀請", invite)
        self.assertIn("LINE 開啟可能需要 5–10 秒，請不要關閉頁面", invite)
        self.assertIn('id="entryLoading"', trial)
        self.assertIn("正在準備 14 天安心體驗", trial)
        self.assertIn("LINE 開啟可能需要 5–10 秒，請不要關閉頁面", trial)
        for html in (invite, trial):
            self.assertIn("entry-loading-spinner", html)
            self.assertIn('document.getElementById("entryLoading")', html)


if __name__ == "__main__":
    unittest.main()
