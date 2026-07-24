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

    def test_guardian_invite_card_uses_theme_readable_style(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn('♡ 緊急聯絡人', page)
        self.assertIn("background: linear-gradient(135deg, #ecfdf5", page)
        self.assertIn("border: 2px solid #22c55e", page)
        self.assertIn("body.neon .settings[aria-label=\"緊急聯絡人\"] .contact-primary", page)
        self.assertIn("background: linear-gradient(135deg, #67e8f9 0%, #38bdf8 100%)", page)
        self.assertIn("font-size: 20px", page)
        self.assertIn("一鍵邀請守護人", page)

    def test_warm_mobile_ui_and_calendar_expand_rules(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        help_page = (ROOT / "help.html").read_text(encoding="utf-8")
        rich_menu_script = (ROOT / "scripts" / "generate_rich_menu_image.py").read_text(encoding="utf-8")

        self.assertIn("body.neon .mvp-brand", page)
        self.assertIn("body.neon .mvp-welcome-sub", page)
        self.assertIn("color: #d1d5db", page)
        self.assertIn(".day-cell.festival .lunar-mini { color: #dc2626", page)
        self.assertIn('if (tabName === "history") setCalendarExpanded(true);', page)
        self.assertIn("需要幫忙時怎麼做", help_page)
        self.assertIn("對方需要加入「每日平安」官方帳號", help_page)
        self.assertIn("進入「平安紀錄」會直接展開月曆", help_page)
        self.assertIn('id="sos"', help_page)
        self.assertIn('("一鍵邀請", "heart", "邀請守護人")', rich_menu_script)
        self.assertIn('("需要幫忙", "sos", "連按 3 次・防誤觸")', rich_menu_script)
        self.assertIn("typeof liff.scanCodeV2 === \"function\"", page)
        self.assertIn("iPhone 與 Android 都比較穩定", page)

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
        self.assertIn("SOS 緊急求助也不鎖 799", pricing)
        self.assertNotIn('class="disabled">SOS 緊急求救', pricing)

    def test_pricing_has_one_home_entry_and_correct_line_guardian_limits(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        pricing = (ROOT / "liff" / "pricing.html").read_text(encoding="utf-8")

        self.assertNotIn('id="planToggleBtn"', page)
        self.assertIn('id="pricingPageLink"', page)
        self.assertIn("查看完整方案與價目", page)
        self.assertIn(
            "<tr><td>核心守護人 LINE 預警</td><td>1 位</td><td>2 位</td><td>2 位</td><td>2 位</td><td>3 位</td><td>5 位</td><td>5 位</td></tr>",
            pricing,
        )
        self.assertIn("<tr><td>SOS</td><td class=\"yes\">✓</td><td class=\"yes\">✓</td><td class=\"yes\">✓</td><td class=\"yes\">✓</td><td class=\"yes\">✓</td><td class=\"yes\">✓</td><td class=\"yes\">✓</td></tr>", pricing)
        self.assertNotIn("長照專線 1966", pricing)

    def test_free_and_trial_include_sos_and_one_core_guardian(self):
        plans = load_plan_limits()
        for plan in ("free", "trial"):
            with self.subTest(plan=plan):
                self.assertTrue(plans[plan]["sos_enabled"])
                self.assertEqual(plans[plan]["contact_limit"], 1)
                self.assertEqual(plans[plan]["core_guardian_alert_limit"], 1)
        self.assertEqual(plans["paid_799"]["core_guardian_alert_limit"], 5)
        self.assertEqual(plans["paid_799_year"]["core_guardian_alert_limit"], 5)

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

    def test_sos_entry_only_appears_for_active_799_and_requires_triple_tap(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="sosFab" type="button" aria-label="SOS 緊急求助" hidden', page)
        self.assertIn('href="tel:119"', page)
        self.assertIn('href="tel:110"', page)
        self.assertIn('id="sosHoldButton"', page)
        self.assertIn("SOS_HOLD_DURATION_MS = 3000", page)
        self.assertIn("聯絡家人連按3次", page)
        self.assertIn("本服務不是報警系統", page)
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
        self.assertIn("連續按 3 次", help_page)
        self.assertIn("所有會員都可以使用", help_page)
        self.assertNotIn("有效的 799 守護版會員", help_page)

    def test_member_role_intro_explains_guardian_vs_emergency_contact(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        member = (ROOT / "liff" / "member.html").read_text(encoding="utf-8")

        self.assertIn('id="memberRoleIntro"', page)
        self.assertTrue(
            "守護人（Guardian）" in page or "核心守護人" in page,
            "guardian role intro missing",
        )
        self.assertTrue(
            "緊急聯絡人（Emergency Contact）" in page or "緊急聯絡人" in page or "聯絡人" in page,
            "emergency/contact role intro missing",
        )
        self.assertIn("member_role_intro_dismissed", page)
        self.assertTrue(
            "平常每天守護你的人" in page or "平常守護你的人" in page,
            "guardian purpose copy missing",
        )
        self.assertIn('id="memberRoleIntro"', member)
        self.assertIn("免費體驗小教室", member)
        self.assertIn("memberEmergencySection", page)
        self.assertIn("member-role-bind-intro", page)
        self.assertIn("memberAddEmergencyBtn", page)
        self.assertNotIn('id="memberAutoRenew"', page)
        self.assertNotIn("儲存續扣", page)
        self.assertNotIn("有效的 799 守護版會員，可連續按 3 次", page)

    def test_member_unbound_guardian_shows_one_tap_invite(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        member = (ROOT / "liff" / "member.html").read_text(encoding="utf-8")

        self.assertIn("function renderContactManageRows", page)
        self.assertIn("一鍵邀請", page)
        self.assertIn("✓ 已綁定", page)
        self.assertIn("等待 LINE 綁定", page)
        self.assertIn("openShareInviteForContact", page)
        self.assertIn('id="memberEmergencySection"', page)
        self.assertIn('id="memberEmergencyList"', page)
        self.assertIn('id="memberAddEmergencyBtn"', page)
        self.assertIn("contact_role", page)
        self.assertIn("contactsByRole", page)
        self.assertIn("guardian-bind-row", page)
        self.assertIn("one-tap-invite-btn", member)
        self.assertIn("✓ 已綁定", member)
        self.assertIn('id="emergencyList"', member)
        self.assertIn("contact_role", member)

    def test_login_skips_onboarding_when_guardians_exist(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        init_app = page[page.rindex("async function initApp()") : page.index("// ===== D01")]
        self.assertIn("hasGuardians", init_app)
        self.assertIn("homeReady || hasGuardians || setupDone", init_app)
        self.assertIn("await showOnboarding()", init_app)
        # 有守護人時關閉填寫／邀請彈窗
        self.assertIn("onboardingModal.hidden = true", init_app)
        self.assertIn("closeGuardianPrompt()", init_app)

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
            page.index("async function initializeLiff()") : page.index("const LUNAR_DAY_NAMES")
        ]

        self.assertIn("async function initializeLiff()", page)
        self.assertIn("await liff.init({ liffId });", init_line)
        self.assertIn("if (!liff.isLoggedIn())", init_line)
        self.assertIn("liff.login();", init_line)
        self.assertNotIn("liff.login({ redirectUri:", init_line)
        # NEVER gate login behind !isInClient (breaks Android Chrome / OAuth return)
        self.assertNotIn("if (inClient)", init_line)
        self.assertNotIn("withLoginOnExternalBrowser", init_line)
        self.assertIn("invite_from", init_line)
        self.assertIn("LIFF 初始化失敗", init_line)
        self.assertNotIn("location.replace(joinUrl)", page)
        self.assertIn("requireLineMembership", page)
        self.assertIn("clearShareFirstLocalFlags", page)
        self.assertIn("setupDone", page)
        self.assertIn("wantsInviteShare", page)
        self.assertNotIn("setTimeout(() => shareContactInvite()", page)
        init_app = page[page.rindex("async function initApp()") : page.index("// ===== D01")]
        self.assertIn("wantsShareInvite", init_app)
        # 一鍵邀請：改導專用分享頁（可帶 return），禁止首頁後自動 shareTargetPicker
        self.assertTrue(
            'location.replace("/liff/share-invite.html")' in init_app
            or "buildShareInvitePageUrl(" in init_app
        )
        self.assertNotIn("shared = await tryLineShareTargetPicker(text)", init_app)
        self.assertIn('showTab("home")', init_app)
        # 守護人一鍵邀請改導專用分享頁，不再走 SPA 複製連結備援
        self.assertIn("openShareInvitePage", page)
        self.assertIn("buildShareInvitePageUrl", page)
        page_share_fn = page[page.index("async function shareContactInvite()") : page.index("function fillShareInviteSurfaces")]
        self.assertIn("openShareInvitePage", page_share_fn)
        self.assertNotIn("tryWebShareOrClipboard", page_share_fn)
        self.assertNotIn("openShareInviteFallbackModal", page_share_fn)
        self.assertNotIn('id="copyInviteBtn"', page)
        self.assertNotIn('id="shareInviteFallbackCopyBtn"', page)
        self.assertNotIn("複製邀請連結", page)

    def test_share_invite_page_is_stable_click_only(self):
        page = (ROOT / "liff" / "share-invite.html").read_text(encoding="utf-8")
        self.assertIn('await liff.init({ liffId: LIFF_ID })', page)
        self.assertIn("buildSafeRedirectUri", page)
        self.assertIn("liff.login({ redirectUri: buildSafeRedirectUri() })", page)
        self.assertNotIn("redirectUri: window.location.href", page)
        self.assertIn("alertFail", page)
        self.assertIn("line.me/R/share?text=", page)
        self.assertIn("openNativeShare()", page)
        self.assertIn("liff.openWindow", page)
        self.assertIn("alive_share_invite_auto_v1", page)
        self.assertIn("hasAutoShareTried", page)
        self.assertIn("請先加入 LINE 官方帳號「每日平安」", page)
        # 禁止教學中間頁文案
        self.assertNotIn("分享給好友", page)
        self.assertNotIn("請點下面大按鈕", page)
        self.assertNotIn("準備好了，請點大按鈕", page)
        self.assertNotIn("開啟 LINE 好友選擇", page)
        self.assertIn(">再分享一次<", page)
        self.assertIn("完成，返回原位置", page)
        self.assertNotIn("await shareNow()", page)
        self.assertNotIn("autoShareOnce", page)
        init_fn = page[page.index("async function initializeLiff()") :]
        self.assertNotIn("shareTargetPicker", init_fn)
        self.assertIn("openNativeShare()", init_fn)
        self.assertNotIn("clipboard", page)
        self.assertIn("https://line.me/R/app/\" + LIFF_ID + \"?invite_from=", page)
        self.assertIn('const LIFF_ID = "2010674803-rK98c0lo"', page)
        self.assertIn("W250724aw", page)
        self.assertIn("resolveReturnUrl", page)
        self.assertIn("完成，返回原位置", page)
        self.assertIn('params.get("return")', page)

    def test_liff_links_use_query_params_for_android_compatibility(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        rich_menu = (ROOT / "line-rich-menu-config.json").read_text(encoding="utf-8")
        flex = (ROOT / "guardian_group_flex.py").read_text(encoding="utf-8")

        self.assertIn("url.searchParams.set", page)
        self.assertIn("parseLiffStateParams", page)
        self.assertIn('String(key) === "liff.state"', page)
        self.assertIn('"invite_from", "friend_invite", "open"', page)
        self.assertIn("https://alive-checkin.onrender.com/liff/pricing.html", rich_menu)
        self.assertIn("https://liff.line.me/2010674803-rK98c0lo?open=checkin", rich_menu)
        # 一鍵邀請：直連空白 share-invite（自動 R/share），無教學大按鈕文案頁
        self.assertIn("https://liff.line.me/2010674803-rK98c0lo/liff/share-invite.html", rich_menu)
        self.assertNotIn("https://liff.line.me/2010674803-rK98c0lo/?open=share-invite", rich_menu)
        # 「需要幫忙」必須是 LINE message
        self.assertNotIn("https://liff.line.me/2010674803-rK98c0lo?open=sos", rich_menu)
        self.assertNotIn("https://liff.line.me/2010674803-rK98c0lo/?open=sos", rich_menu)
        self.assertIn('"type": "message"', rich_menu)
        self.assertIn('"label": "需要幫忙"', rich_menu)
        self.assertIn('"text": "需要幫忙"', rich_menu)
        self.assertIn("https://liff.line.me/2010674803-rK98c0lo?open=help", rich_menu)
        self.assertNotIn("https://liff.line.me/2010674803-rK98c0lo?open=pricing", rich_menu)
        self.assertNotIn("https://liff.line.me/2010674803-rK98c0lo/?open=pricing", rich_menu)
        self.assertIn("https://liff.line.me/2010674803-rK98c0lo?open=guard", rich_menu)
        self.assertIn('url += "?" + urlencode(params, safe="/")', flex)
        self.assertNotIn('url += "/?" + urlencode(params, safe="/")', flex)
        self.assertIn("line_native_share_url", flex)
        self.assertIn("share_invite_flex", flex)
        self.assertIn("請先加入 LINE 官方帳號「每日平安」", flex)
        self.assertIn("有緊急或我沒報平安時，系統會通知你", flex)
        self.assertNotIn("https://liff.line.me/2010674803-rK98c0lo#open=", rich_menu)
        self.assertNotIn("https://alive-checkin.onrender.com/help.html", rich_menu)
        self.assertNotIn('"type": "message", "label": "SOS 求救"', rich_menu)
        self.assertNotIn('"label": "連按SOS"', rich_menu)

    def test_welcome_help_button_opens_help_and_faq(self):
        flex = (ROOT / "guardian_group_flex.py").read_text(encoding="utf-8")

        self.assertIn('"label": "立即開始設定"', flex)
        self.assertIn('"label": "查看方案"', flex)
        self.assertIn("pricing_direct_url()", flex)
        self.assertIn("open_action=\"onboarding\"", flex)
        self.assertIn("daily-peace-logo.png", flex)
        self.assertIn("歡迎加入「每日平安」", flex)
        self.assertIn("完成設定即可享 7 天免費安心體驗", flex)
        self.assertIn("緊急狀況請直接撥打 119 或 110", flex)
        self.assertNotIn("welcome_version", flex)
        self.assertNotIn("版本 W", flex)
        self.assertNotIn("W250723", flex)
        self.assertNotIn('"label": "立即升級守護"', flex)
        self.assertNotIn('"label": "回到首頁"', flex)
        welcome_fn = flex.split("def welcome_flex", 1)[1].split("\ndef ", 1)[0]
        self.assertNotIn("立即升級守護", welcome_fn)
        self.assertNotIn('"label": "常見問題"', welcome_fn)
        self.assertNotIn('"label": "一鍵邀請守護人"', welcome_fn)
        self.assertNotIn('"label": "需要幫忙"', welcome_fn)
        self.assertIn('"label": "立即開始設定"', welcome_fn)
        self.assertIn('"label": "查看方案"', welcome_fn)
        self.assertIn("pricing_uri", welcome_fn)
        self.assertIn("setup_uri", welcome_fn)
        # Header: logo top-left + greeting text beside (horizontal row)
        self.assertIn('"alignItems": "center"', welcome_fn)
        self.assertIn('"size": "xs"', welcome_fn)
        self.assertNotIn('"justifyContent": "center"', welcome_fn)

    def test_public_liff_actions_redirect_to_standalone_pages(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        backend = (ROOT / "app.py").read_text(encoding="utf-8")
        help_page = (ROOT / "help.html").read_text(encoding="utf-8")
        faq_page = (ROOT / "faq.html").read_text(encoding="utf-8")

        self.assertIn("const publicOpenPages = {", page)
        self.assertIn('help: "help.html"', page)
        self.assertIn('pricing: "liff/pricing.html"', page)
        self.assertIn('faq: "faq.html"', page)
        self.assertIn("wantsShareInvite", page)
        self.assertIn("tryLineShareTargetPicker", page)
        self.assertIn("liff.login()", page)
        self.assertNotIn('liff.login({ redirectUri:', page)
        self.assertIn('@app.get("/faq")', backend)
        self.assertIn('@app.get("/help")', backend)
        self.assertIn('@app.get("/pricing")', backend)
        self.assertIn("立即升級守護", help_page)
        self.assertIn("問與答", help_page)
        self.assertIn("常見問題", faq_page)
        self.assertIn("家人要怎麼先體驗 799 守護版", faq_page)

    def test_line_upgrade_reply_uses_online_liff_link_not_local_file(self):
        backend = (ROOT / "app.py").read_text(encoding="utf-8")

        self.assertIn("可以，升級方案請點這裡", backend)
        self.assertIn("pricing_direct_url()", backend)
        self.assertIn("https://alive-checkin.onrender.com/", backend)
        self.assertNotIn("file:///C:/Users/WIN11", backend)

    def test_guardian_invite_uses_single_line_app_url_plus_invite_landing(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        backend = (ROOT / "app.py").read_text(encoding="utf-8")
        landing = (ROOT / "invite.html").read_text(encoding="utf-8")
        invite_block = page[
            page.index("function buildContactInvite")
            : page.index("async function apiBindEmergencyContact")
        ]

        self.assertIn("function buildPublicAppUrl", page)
        self.assertIn("function buildLineAppOpenUrl", page)
        self.assertIn("function buildShareInviteUrl", page)
        self.assertIn("buildShareInviteUrl(shareParams)", invite_block)
        self.assertIn("return buildLiffPermanentUrl(params);", page)
        self.assertIn("請先加入 LINE 官方帳號「每日平安」", invite_block)
        self.assertIn("有緊急或我沒報平安時，系統會通知你", invite_block)
        self.assertNotIn("備用短連結：", invite_block)
        self.assertIn("canUseShareTargetPicker", page)
        self.assertIn("isApiAvailable(\"shareTargetPicker\")", page)
        self.assertIn("shareInviteFallbackModal", page)
        self.assertIn("改用 LINE 好友分享", page)
        self.assertNotIn('id="shareInviteFallbackCopyBtn"', page)
        self.assertNotIn("請貼到 LINE 給家人", page)
        # login 不帶 redirectUri（Android/iOS 參數才不會丟）
        self.assertIn("liff.login()", page)
        self.assertNotIn("liff.login({ redirectUri:", page)
        self.assertIn('buildPublicAppUrl({ from: safeId }, "/invite")', page)
        self.assertIn('@app.get("/invite")', backend)
        self.assertIn('send_from_directory(app.static_folder, "invite.html")', backend)
        self.assertIn("public_invite_landing_url", backend)
        # LIFF Endpoint `/` must always serve SPA — never 302 invite_from to /invite
        self.assertIn("_should_keep_liff_endpoint_spa", backend)
        self.assertNotIn("_redirect_invite_to_landing", backend)
        self.assertNotIn("bounced = _redirect_invite_to_landing()", backend)
        self.assertIn("請用 LINE 開啟", landing)
        self.assertIn("line.me/R/app/", landing)
        self.assertIn("liff.line.me/", landing)
        self.assertIn("formatLiffError", page)
        self.assertIn("detail: formatLiffError(error)", page)
        # Android 雙重確認：綁定成功只 alert 一次，並清掉 invite_from
        self.assertIn("let bindDone = false", page)
        self.assertIn("function clearInviteFromUrl", page)
        self.assertIn("async function completeGuardianBindOnce", page)
        self.assertIn("history.replaceState", page)
        self.assertIn("completeGuardianBindOnce(inviteFrom)", page)
        init_liff = page[page.index("async function initializeLiff()") : page.index("async function initLine()")]
        self.assertNotIn("apiBindEmergencyContact(inviteFrom)", init_liff)
        self.assertIn("maybeShowInviteAcceptPrompt()", init_liff)

    def test_guardian_group_intro_has_large_four_button_actions(self):
        flex = (ROOT / "guardian_group_flex.py").read_text(encoding="utf-8")

        self.assertIn("def _group_quick_actions", flex)
        self.assertIn("用途", flex)
        self.assertIn("799 守護版：月費可開 1 群，年費可開 3 群", flex)
        self.assertIn("每群最多 50 人", flex)
        self.assertIn("綁定守護群", flex)
        self.assertIn('_uri_button("我平安", liff_entry_url(open_action="checkin")', flex)
        self.assertIn('_postback_button("聯絡家人"', flex)
        self.assertIn('_postback_button("需要幫忙", "需要幫忙"', flex)
        self.assertNotIn('_uri_button("需要幫忙", liff_entry_url(open_action="sos")', flex)
        self.assertIn('_postback_button("守護群狀態"', flex)
        self.assertIn('"label": "我已完成守護群設定"', flex)
        self.assertIn('"text": "守護群狀態"', flex)

    def test_friend_location_invite_uses_single_share_url(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        friend_invite_block = page[
            page.index("async function shareFriendInvite")
            : page.index("function maybePrefillFriendInvite")
        ]

        self.assertIn("buildShareInviteUrl({ friend_invite: inviteCode })", friend_invite_block)
        self.assertIn("請用 LINE 點開下面連結", friend_invite_block)
        self.assertNotIn("備用短連結：", friend_invite_block)
        self.assertIn("tryLineShareTargetPicker", friend_invite_block)
        self.assertNotIn("tryWebShareOrClipboard", friend_invite_block)
        self.assertNotIn("複製連結貼到 LINE", friend_invite_block)
        self.assertNotIn("url: inviteUrl", friend_invite_block)

    def test_calendar_note_modal_scrolls_on_mobile_and_confirms_save(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn("#calendarNoteModal {", page)
        self.assertIn("touch-action: pan-y", page)
        self.assertIn("#calendarNoteModal .guardian-modal", page)
        self.assertIn('showInlineSuccess(contentOverride === "" ? "已清除記事" : "記事已儲存")', page)

    def test_invite_accept_modal_is_above_bottom_nav_for_ios_taps(self):
        """iPhone: 「同意成為守護人」must not sit under bottom-nav/SOS hit targets."""
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        css = page[: page.index("</style>")]

        self.assertIn(".modal-backdrop {", css)
        self.assertIn("z-index: 90", css)
        self.assertIn("#inviteAcceptPrompt", css)
        self.assertIn("z-index: 100", css)
        self.assertIn("body.invite-modal-open .bottom-nav", css)
        self.assertIn("pointer-events: none !important", css)
        self.assertIn('id="acceptGuardianInviteBtn"', page)
        self.assertIn("同意成為守護人", page)
        self.assertIn("invite-modal-open", page)
        self.assertIn("touch-action: manipulation", css)
        # bottom nav / SOS must stay below modal layer
        self.assertIn(".bottom-nav", css)
        self.assertRegex(css, r"\.bottom-nav\s*\{[^}]*z-index:\s*30")
        self.assertRegex(css, r"\.sos-fab\s*\{[^}]*z-index:\s*35")

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
