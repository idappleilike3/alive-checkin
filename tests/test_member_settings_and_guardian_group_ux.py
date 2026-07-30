from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MemberSettingsAndGuardianGroupUxTests(unittest.TestCase):
    def test_member_reminder_controls_are_selectable_and_authenticated(self):
        page = (ROOT / "liff" / "member.html").read_text(encoding="utf-8")

        self.assertIn("我的設定", page)
        self.assertIn("每日提醒設定", page)
        for count in (1, 2, 3):
            self.assertIn(f'name="reminderCount" value="{count}"', page)
        self.assertIn("使用方案預設時間", page)
        self.assertIn("儲存設定", page)
        self.assertIn("aria-live=\"polite\"", page)
        self.assertIn('headers: lineAuthHeaders({ "Content-Type": "application/json" })', page)
        self.assertIn("✅ 已儲存：", page)
        self.assertIn("❌ 儲存失敗：", page)

    def test_guardian_group_copy_is_plain_and_has_explicit_save(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn("未報平安時，也通知這個 LINE 群", page)
        self.assertIn("每天傳送一次群內平安摘要", page)
        self.assertIn("摘要中的詳細姓名只讓管理員查看", page)
        self.assertIn("生日、回診與生活備忘只會私訊本人", page)
        self.assertIn("儲存守護群設定", page)
        self.assertIn("guardian-group-save", page)
        self.assertNotIn("群組提醒（選用）", page)
        self.assertNotIn("群組每日已報／未報摘要（選用）", page)

    def test_unbound_guardian_group_shows_setup_prompt_without_active_preferences(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn("<strong>尚未建立守護群</strong>", page)
        self.assertIn(
            "建立守護群後，才能設定群組通知、每日摘要與查看群組成員狀態。",
            page,
        )
        self.assertIn("建立／綁定守護群", page)
        self.assertNotIn('data-group-id="__default__"', page)

    def test_home_names_core_guardian_status_without_guardian_circle_jargon(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn("<strong>核心守護人</strong>", page)
        self.assertIn("已接受邀請", page)
        self.assertNotIn("守護圈狀態", page)
        self.assertNotIn("簽到紀錄、守護圈與下次提醒", page)

    def test_frontend_replaces_smart_reminder_jargon_with_date_reminders(self):
        for relative_path in (
            "index.html",
            "liff/member.html",
            "faq.html",
            "liff/pricing.html",
        ):
            page = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("智能提醒", page)
            self.assertNotIn("智慧提醒", page)
            self.assertIn("日期提醒", page)

        home = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("我的設定 → 每日提醒設定", home)
        self.assertIn("799 才能設定 LINE 推播提醒", home)

    def test_home_member_history_has_memo_entry(self):
        home = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn("<strong>我的平安紀錄</strong>", home)
        self.assertIn("399／799 月費與年費可新增網頁備忘", home)
        self.assertIn('href="#history"', home)
        self.assertIn("＋ 新增備忘錄", home)


if __name__ == "__main__":
    unittest.main()
