import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_plan_limits():
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "PLAN_LIMITS" for target in node.targets):
                return ast.literal_eval(node.value)
    raise AssertionError("PLAN_LIMITS not found")


class ProductRulesTests(unittest.TestCase):
    def test_paid_plan_limits_match_public_pricing(self):
        plans = load_plan_limits()

        expected = {
            "paid_199": (4, 2, 0, 0),
            "paid_199_year": (6, 2, 0, 0),
            "paid_399": (15, 2, 0, 0),
            "paid_399_year": (25, 2, 0, 0),
            "paid_799": (25, 3, 0, 1),
            "paid_799_year": (50, 3, 0, 3),
        }
        for plan, values in expected.items():
            contact_limit, reminders, trajectory_days, group_limit = values
            with self.subTest(plan=plan):
                self.assertEqual(plans[plan]["contact_limit"], contact_limit)
                self.assertEqual(plans[plan]["friend_location_limit"], contact_limit)
                self.assertEqual(plans[plan]["daily_reminders"], reminders)
                self.assertEqual(plans[plan]["trajectory_days"], trajectory_days)
                self.assertEqual(plans[plan]["guardian_group_limit"], group_limit)

    def test_removed_reminder_settings_do_not_hide_guardian_or_location_tools(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="lunarDateText"', page)
        self.assertNotIn('id="calendarReminderBtn"', page)
        self.assertNotIn('aria-label="緊急與提醒設定"', page)
        self.assertNotIn('href="tel:1966"', page)
        self.assertNotIn('data-tab="settings"', page)
        self.assertIn('id="shareContactInviteBtn"', page)
        self.assertIn('id="shareFriendInviteBtn"', page)
        self.assertIn('id="shareLocationBtn"', page)
        self.assertIn("place-items: start center;", page)
        self.assertIn(".check-btn.danger {", page)
        self.assertIn("color: #fff !important;", page)

    def test_today_status_stays_open_with_checkin_at_top(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertNotIn('id="reloadBtn"', page)
        self.assertNotIn('id="statusToggleBtn"', page)
        self.assertIn('<div class="status-details" id="statusDetails">', page)
        self.assertIn('id="mvpHome"', page)
        self.assertIn('class="check-wrap"', page)
        self.assertLess(
            page.index('id="mvpHome"'),
            page.index('id="countdownDisplay"'),
        )
        self.assertLess(
            page.index('id="countdownDisplay"'),
            page.index('<section class="status-box" aria-label="簽到狀態">'),
        )

    def test_trial_summary_is_merged_and_bottom_navigation_is_visible(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertNotIn('id="planName"', page)
        self.assertIn('grid-template-columns: repeat(2, minmax(0, 1fr));', page)
        self.assertNotIn('id="bottomNav" aria-label="主導覽" style="display:none;"', page)
        app_init = page[page.rindex("async function initApp()") : page.index("// ===== D01")]
        self.assertLess(app_init.index("bindTabEvents();"), app_init.index("if (!lineUserId) {"))

    def test_pricing_does_not_sell_basic_privacy_rights(self):
        pricing = (ROOT / "liff" / "pricing.html").read_text(encoding="utf-8")

        self.assertNotIn("個資全自主管理", pricing)
        self.assertIn("守護群最多 1 群", pricing)
        self.assertIn("守護群最多 3 群", pricing)

    def test_pricing_has_one_home_entry_and_correct_line_guardian_limits(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        pricing = (ROOT / "liff" / "pricing.html").read_text(encoding="utf-8")

        self.assertNotIn('id="planToggleBtn"', page)
        self.assertIn('id="pricingPageLink"', page)
        self.assertIn("查看完整方案與價目", page)
        self.assertIn(
            "<tr><td>核心守護人 LINE 預警</td><td>2 位</td><td>2 位</td><td>2 位</td><td>3 位</td><td>3 位</td><td>5 位</td></tr>",
            pricing,
        )
        self.assertNotIn("長照專線 1966", pricing)

    def test_guardian_group_navigation_opens_line_setup_guide(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        backend = (ROOT / "app.py").read_text(encoding="utf-8")

        self.assertIn('<span class="nav-label">守護群教學</span>', page)
        self.assertIn('aria-label="守護群設定教學"', page)
        self.assertIn("建立 LINE 群組", page)
        self.assertIn("邀請官方帳號", page)
        self.assertIn("輸入「綁定守護群」", page)
        self.assertIn("799 月費最多 1 群，799 年費最多 3 群", page)
        self.assertIn('guardians: ["守護群設定教學"', page)
        self.assertNotIn("守護群限有效的 799 年費會員建立", backend)

    def test_sos_entry_only_appears_for_active_799_and_requires_long_press(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="sosFab" type="button" aria-label="SOS 緊急求助" hidden', page)
        self.assertIn('href="tel:119"', page)
        self.assertIn('href="tel:110"', page)
        self.assertIn('id="sosHoldButton"', page)
        self.assertIn("SOS_HOLD_DURATION_MS = 3000", page)
        self.assertIn("長按 3 秒", page)
        self.assertIn("本服務不是報警或救援系統", page)
        self.assertIn('id="mvpSosBtn"', page)
        self.assertIn("openSosModal", page)
        self.assertIn('sosSection.hidden = !enabled;', page)
        self.assertNotIn('id="sosConfirmSend"', page)

    def test_sos_plan_access_matches_public_benefits(self):
        plans = load_plan_limits()

        # MVP：緊急求助通知家人開放各方案；過期付費會員仍由後端擋下
        for plan in plans:
            with self.subTest(plan=plan):
                self.assertTrue(plans[plan]["sos_enabled"])
                self.assertEqual(plans[plan]["trajectory_days"], 0)
                self.assertFalse(plans[plan]["realtime_tracking"])

    def test_mvp_home_has_exactly_four_primary_actions(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("每日平安", page)
        self.assertIn("每天 10 秒，報個平安", page)
        self.assertIn("平常不打擾，有事才通知守護人", page)
        self.assertIn("完成綁定一位，二選一獎勵", page)
        self.assertIn('id="mvpSafeBtn"', page)
        self.assertIn('id="mvpGuardBtn"', page)
        self.assertIn('id="mvpCallBtn"', page)
        self.assertIn('id="mvpSosBtn"', page)
        self.assertIn("今天已完成平安回報", page)
        self.assertNotIn("軌跡回放", page)
        self.assertNotIn("不是 24 小時軌跡", page)

    def test_every_sos_entry_uses_the_same_safe_flow(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        standalone = (ROOT / "liff" / "sos.html").read_text(encoding="utf-8")
        help_page = (ROOT / "help.html").read_text(encoding="utf-8")

        self.assertIn('page === "sos"', page)
        self.assertIn("?page=sos", standalone)
        self.assertNotIn("startCountdown()", standalone)
        self.assertNotIn("秒後自動發出", standalone)
        self.assertIn("長按 3 秒", help_page)
        self.assertIn("有效的 799 守護版會員", help_page)
        self.assertNotIn("所有會員都能使用 119／110 快捷入口", help_page)


    def test_line_login_finishes_before_checkin_is_enabled(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="checkBtn" type="button" disabled', page)
        self.assertIn('async function bootstrapApp()', page)
        bootstrap = page[
            page.index("async function bootstrapApp()") : page.index("bootstrapApp();")
        ]
        self.assertLess(bootstrap.index("await initLine()"), bootstrap.index("await initApp()"))
        self.assertIn("const lineReady = lineUserId ? true : await initLine()", bootstrap)
        self.assertIn("showLineLoginRequired", bootstrap)
        self.assertNotIn("\n    initApp();\n", page)
        refresh_contacts = page[
            page.index("async function refreshContacts()") : page.index("function addContact()")
        ]
        self.assertIn("apiGetContacts(lineUserId)", refresh_contacts)

    def test_liff_initialization_requires_line_login_before_member_use(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        init_line = page[
            page.index("async function initLine()") : page.index("const LUNAR_DAY_NAMES")
        ]

        self.assertIn("withLoginOnExternalBrowser: false", init_line)
        self.assertIn("if (!liff.isLoggedIn())", init_line)
        self.assertIn("liff.login(", init_line)
        self.assertIn("liff.isInClient && liff.isInClient()", init_line)
        self.assertNotIn("location.replace(joinUrl)", page)
        self.assertIn("requireLineMembership", page)
        # Returning users must not auto-share on page load
        self.assertIn("clearShareFirstLocalFlags", page)
        self.assertIn("setupDone", page)
        init_app = page[page.rindex("async function initApp()") : page.index("// ===== D01")]
        gate_start = init_app.index("if (setupDone) {")
        gate_end = init_app.index("} else {", gate_start)
        gate = init_app[gate_start:gate_end]
        self.assertNotIn("shareContactInvite", gate)
        self.assertIn('showTab("home")', gate)

    def test_onboarding_guardian_form_is_senior_friendly_and_traditional_chinese(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        onboarding = page[
            page.index('id="onboardingModal"') : page.index(
                '<section class="status-box" aria-label="簽到狀態">'
            )
        ]

        self.assertIn('class="guardian-modal onboarding-modal"', onboarding)
        self.assertIn("歡迎使用「每日平安」", onboarding)
        self.assertIn('for="obName">姓名', onboarding)
        self.assertIn('id="obRelationship"', onboarding)
        self.assertIn('<select id="obRelationship"', onboarding)
        self.assertIn('<option value="爸爸">爸爸</option>', onboarding)
        self.assertIn('<option value="媽媽">媽媽</option>', onboarding)
        self.assertIn('<option value="阿公">阿公</option>', onboarding)
        self.assertIn('<option value="阿嬤">阿嬤</option>', onboarding)
        self.assertIn('id="obRelationshipOther"', onboarding)
        self.assertIn('for="obPhone">手機號碼', onboarding)
        self.assertIn('id="obPhone"', onboarding)
        self.assertIn("required", onboarding)
        self.assertIn('for="obEmail">電子信箱（選填）', onboarding)
        self.assertIn("新增守護人，下一步設定提醒", onboarding)
        self.assertIn('id="onboardingReminderStep"', onboarding)
        self.assertIn('id="onboardingReminderSlots"', onboarding)
        self.assertIn("使用方案預設時間", onboarding)
        self.assertIn("完成設定並進入首頁", onboarding)
        self.assertIn('id="onboardingCloseBtn"', onboarding)
        self.assertIn("onboarding-form[hidden]", page)
        self.assertNotIn("欢迎", onboarding)
        self.assertNotIn("关系", onboarding)
        self.assertIn(".onboarding-submit", page)


if __name__ == "__main__":
    unittest.main()
