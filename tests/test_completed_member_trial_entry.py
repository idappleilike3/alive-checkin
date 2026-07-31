from pathlib import Path
import unittest


HTML = (
    Path(__file__).resolve().parents[1] / "liff" / "onboarding.html"
).read_text(encoding="utf-8")


class CompletedMemberTrialEntryTests(unittest.TestCase):
    def test_completed_member_stays_in_current_liff_and_sees_clear_actions(self):
        completed_branch = HTML.split(
            "if (state.setupCompleted && state.hasGuardian && state.reminderConfigured) {",
            1,
        )[1].split("// 正式順序", 1)[0]

        self.assertIn("renderCompletedMemberEntry()", completed_branch)
        self.assertNotIn("location.replace", completed_branch)
        self.assertIn("你已是每日平安會員", HTML)
        self.assertIn("進入我的每日平安", HTML)
        self.assertIn("分享 14 天安心體驗給朋友", HTML)
        self.assertIn("前往會員中心", HTML)


if __name__ == "__main__":
    unittest.main()
