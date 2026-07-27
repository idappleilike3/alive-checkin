import ast
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NEW_LIFF_ID = "2010848330-UAiqPPYD"
NEW_CHANNEL_ID = "2010848330"


def load_plan_limits():
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "PLAN_LIMITS" for target in node.targets):
                return ast.literal_eval(node.value)
    raise AssertionError("PLAN_LIMITS not found")


class ProductRulesTests(unittest.TestCase):
    def test_guardian_share_creates_server_invite_and_carries_unique_token(self):
        share_page = (ROOT / "liff" / "share-invite.html").read_text(encoding="utf-8")
        member_page = (ROOT / "index.html").read_text(encoding="utf-8")
        invite_page = (ROOT / "invite.html").read_text(encoding="utf-8")
        self.assertIn('fetch("/api/emergency-contact/invite"', share_page)
        self.assertIn("data.invite_token", share_page)
        self.assertIn("&invite_token=", share_page)
        self.assertIn("body.invite_token = inviteToken", member_page)
        self.assertIn('qs.set("invite_token", inviteToken)', member_page)
        self.assertIn('"invite_from", "from", "invite_token"', member_page)
        self.assertIn('q.set("invite_token", inviteToken)', invite_page)

    def test_no_production_entry_uses_legacy_liff_id(self):
        allowed = {
            ROOT / "liff" / "migrate.html",
            ROOT / "docs" / "superpowers",
            ROOT / ".superpowers",
            ROOT / "tests",
        }
        offenders = []
        for path in ROOT.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".html", ".json", ".yaml", ".md"}:
                continue
            if any(str(path).startswith(str(prefix)) for prefix in allowed):
                continue
            source = path.read_text(encoding="utf-8")
            if path == ROOT / "app.py":
                source = source.replace(
                    'DEFAULT_LEGACY_LIFF_ID = "2010674803-rK98c0lo"',
                    "",
                )
            elif path == ROOT / "render.yaml":
                source = source.replace(
                    "      - key: LEGACY_LIFF_ID\n"
                    "        value: 2010674803-rK98c0lo",
                    "",
                )
            if "2010674803-rK98c0lo" in source:
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_render_uses_new_line_login_provider(self):
        render = (ROOT / "render.yaml").read_text(encoding="utf-8")
        self.assertIn(f"value: {NEW_LIFF_ID}", render)
        self.assertIn(f"value: {NEW_CHANNEL_ID}", render)

    def test_legacy_migration_page_matches_controlled_server_default(self):
        source = (ROOT / "liff" / "migrate.html").read_text(encoding="utf-8")
        match = re.search(r'const LEGACY_LIFF_ID = "([^"]+)";', source)
        self.assertIsNotNone(match)

        import app as alive_app

        self.assertEqual(match.group(1), alive_app.DEFAULT_LEGACY_LIFF_ID)

    def test_paid_plan_limits_match_public_pricing(self):
        plans = load_plan_limits()

        # contact_limit, daily_reminders, trajectory_days, group_limit,
        # core_guardian_alert_limit, emergency_contact_limit
        expected = {
            "paid_199": (6, 1, 0, 0, 2, 4),
            "paid_199_year": (13, 2, 0, 0, 3, 10),
            "paid_399": (20, 2, 0, 0, 5, 15),
            "paid_399_year": (32, 2, 0, 0, 7, 25),
            "paid_799": (45, 3, 0, 1, 10, 35),
            "paid_799_year": (65, 3, 0, 3, 15, 50),
        }
        for plan, values in expected.items():
            contact_limit, reminders, trajectory_days, group_limit, core_limit, emergency_limit = values
            with self.subTest(plan=plan):
                self.assertEqual(plans[plan]["contact_limit"], contact_limit)
                self.assertEqual(plans[plan]["friend_location_limit"], 0)
                self.assertEqual(plans[plan]["daily_reminders"], reminders)
                self.assertEqual(plans[plan]["trajectory_days"], trajectory_days)
                self.assertEqual(plans[plan]["guardian_group_limit"], group_limit)
                self.assertEqual(plans[plan]["core_guardian_alert_limit"], core_limit)
                self.assertEqual(plans[plan]["emergency_contact_limit"], emergency_limit)
                self.assertEqual(plans[plan]["channels"], ["line"])
                self.assertNotIn("sms", plans[plan]["channels"])

    def test_399_and_799_reminder_limits_and_public_copy_match_decision(self):
        plans = load_plan_limits()
        self.assertEqual(plans["paid_399"]["daily_reminders"], 2)
        self.assertEqual(plans["paid_399_year"]["daily_reminders"], 2)
        self.assertEqual(plans["paid_799"]["daily_reminders"], 3)
        self.assertEqual(plans["paid_799_year"]["daily_reminders"], 3)

        pricing = (ROOT / "liff" / "pricing.html").read_text(encoding="utf-8")
        member = (ROOT / "liff" / "member.html").read_text(encoding="utf-8")
        help_page = (ROOT / "help.html").read_text(encoding="utf-8")
        self.assertIn("399 月費／年費：每日可選 1～2 次", pricing)
        self.assertIn("799 月費／年費：每日可選 1～3 次", pricing)
        self.assertIn("預設 12:00、18:00", pricing)
        self.assertIn("完成今日簽到後，當天剩餘提醒自動停止", pricing)
        self.assertNotIn("邀請成功每位 +7 天", pricing)
        self.assertNotIn("方案到期後資料保留 30 天", pricing)
        self.assertIn('class="guardian-row contact-card', member)
        self.assertIn("data-contact-toggle", member)
        self.assertIn('aria-expanded="false"', member)
        self.assertIn("399 月費／年費每日可選 1～2 次", help_page)
        self.assertIn("799 月費／年費每日可選 1～3 次", help_page)
        self.assertIn("當天剩餘提醒就會自動停止", help_page)

    def test_removed_reminder_settings_do_not_hide_guardian_or_location_tools(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="lunarDateText"', page)
        self.assertNotIn('id="calendarReminderBtn"', page)
        self.assertNotIn('aria-label="緊急與提醒設定"', page)
        self.assertNotIn('href="tel:1966"', page)
        self.assertNotIn('data-tab="settings"', page)
        self.assertIn('id="shareContactInviteBtn"', page)
        self.assertIn('id="shareLocationBtn"', page)
        self.assertNotIn('id="shareFriendInviteBtn"', page)
        self.assertNotIn('aria-label="好友地圖"', page)
        self.assertIn('aria-label="安全守護"', page)
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
        self.assertIn("SOS 緊急求助", pricing)
        self.assertNotIn('class="disabled">SOS 緊急求救', pricing)

    def test_pricing_has_one_home_entry_and_correct_line_guardian_limits(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        pricing = (ROOT / "liff" / "pricing.html").read_text(encoding="utf-8")

        self.assertNotIn('id="planToggleBtn"', page)
        self.assertIn('id="pricingPageLink"', page)
        self.assertIn("查看完整方案與價目", page)
        self.assertIn(
            "<tr><td>核心守護人</td><td>1</td><td>2</td><td>3</td><td>5</td><td>7</td><td>10</td><td>15</td></tr>",
            pricing,
        )
        self.assertIn(
            "<tr><td>緊急聯絡人</td><td>2</td><td>4</td><td>10</td><td>15</td><td>25</td><td>35</td><td>50</td></tr>",
            pricing,
        )
        self.assertIn(
            "<tr><td>LINE 私聊預警／日</td><td>1 次</td><td>1 次</td><td>2 次</td><td>1～2 次</td><td>1～2 次</td><td>1～3 次</td><td>1～3 次</td></tr>",
            pricing,
        )
        self.assertNotIn("簡訊預警", pricing)
        self.assertNotIn("稍後開放", pricing)
        self.assertNotIn("免提", pricing)
        self.assertNotIn("好友地圖", pricing)
        self.assertNotIn("軌跡", pricing)
        self.assertNotIn("全管道", pricing)
        self.assertIn("<tr><td>SOS</td><td class=\"yes\">✓</td><td class=\"yes\">✓</td><td class=\"yes\">✓</td><td class=\"yes\">✓</td><td class=\"yes\">✓</td><td class=\"yes\">✓</td><td class=\"yes\">✓</td></tr>", pricing)
        self.assertNotIn("長照專線 1966", pricing)

    def test_free_and_trial_include_sos_and_one_core_guardian(self):
        plans = load_plan_limits()
        for plan in ("free", "trial"):
            with self.subTest(plan=plan):
                self.assertTrue(plans[plan]["sos_enabled"])
                self.assertEqual(plans[plan]["core_guardian_alert_limit"], 1)
                self.assertEqual(plans[plan]["emergency_contact_limit"], 2)
                self.assertEqual(plans[plan]["contact_limit"], 3)
                self.assertEqual(plans[plan]["friend_location_limit"], 0)
        self.assertEqual(plans["paid_799"]["core_guardian_alert_limit"], 10)
        self.assertEqual(plans["paid_799_year"]["core_guardian_alert_limit"], 15)

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
        self.assertIn("function renderSosAccess()", page)
        self.assertNotIn('id="sosConfirmSend"', page)

    def test_sos_plan_access_matches_public_benefits(self):
        plans = load_plan_limits()

        # MVP：緊急求助通知家人開放各方案；過期付費會員仍由後端擋下
        for plan in plans:
            with self.subTest(plan=plan):
                self.assertTrue(plans[plan]["sos_enabled"])
                self.assertEqual(plans[plan]["trajectory_days"], 0)
                self.assertFalse(plans[plan]["realtime_tracking"])

    def test_sos_result_ui_lists_safe_guardian_and_group_names(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn("function formatSosRecipientNames(result)", page)
        self.assertIn("result.guardians", page)
        self.assertIn("result.groups", page)
        self.assertIn("通知明細", page)

    def test_mvp_home_has_exactly_four_primary_actions(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("每日平安", page)
        self.assertIn("每天 10 秒，報個平安", page)
        self.assertIn("平常不打擾，有事才通知守護人", page)
        self.assertNotIn("每成功邀請 1 位守護人", page)
        self.assertNotIn("免費延長 7 天；方案到期後守護人與聯絡人資料保留 30 天", page)
        self.assertIn('id="mvpSafeBtn"', page)
        self.assertIn('id="mvpGuardBtn"', page)
        self.assertIn('name="mvpSafetyGuardDuration"', page)
        self.assertIn("mvpGuardUpgradeHint", page)
        self.assertIn("formatGuardianNotifyMessage", page)
        self.assertIn("getCurrentPositionPromise", page)
        self.assertIn("refreshLocationForSos", page)
        self.assertIn("formatSosResultFeedback", page)
        self.assertIn("正在取得定位…", page)
        self.assertIn("改送不含即時位置的 SOS", page)
        self.assertIn("requireBoundGuardianForSafetyGuard", page)
        self.assertIn("還沒完成綁定守護人，無法使用此功能", page)
        self.assertIn("🟢 安全守護中", page)
        self.assertIn('id="mvpCallBtn"', page)
        self.assertIn('id="mvpSosBtn"', page)
        self.assertIn("今天已完成平安回報", page)
        self.assertNotIn("軌跡回放", page)
        self.assertNotIn("不是 24 小時軌跡", page)

    def test_every_sos_entry_uses_the_same_safe_flow(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        standalone = (ROOT / "liff" / "sos.html").read_text(encoding="utf-8")
        help_page = (ROOT / "help.html").read_text(encoding="utf-8")

        self.assertIn('action === "sos"', page)
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
        self.assertIn("member-contact-tabs", page)
        self.assertIn("setMemberContactTab", page)
        self.assertIn("核心守護人", page)
        self.assertIn("planCoreGuardianLimit", page)
        self.assertIn("planEmergencyLimit", page)
        self.assertNotIn('id="guardianDetailsStatus"', page)
        self.assertNotIn("已完成守護人的必要資料", page)
        self.assertNotIn('id="memberAutoRenew"', page)
        self.assertNotIn("儲存續扣", page)
        self.assertNotIn("有效的 799 守護版會員，可連續按 3 次", page)

    def test_privacy_requests_require_verified_contact_path(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("隱私權申請", page)
        self.assertIn("alivecheckin.tw@gmail.com", page)
        self.assertIn("LINE 身分確認", page)
        self.assertNotIn('id="exportMyDataBtn"', page)
        self.assertNotIn('id="deleteCheckinHistoryBtn"', page)
        self.assertNotIn('id="deleteAccountBtn"', page)

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

    def test_liff_initialization_requires_official_friend_then_explicit_login_before_member_use(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        init_line = page[
            page.index("async function initializeLiff()") : page.index("const LUNAR_DAY_NAMES")
        ]

        self.assertIn("async function initializeLiff()", page)
        self.assertIn(
            'await liff.init({ liffId: FIXED_LIFF_ID });',
            init_line,
        )
        self.assertIn("resolveLineEntryGate", init_line)
        self.assertIn("getFriendship", page)
        self.assertIn('id="lineEntryGate"', page)
        self.assertIn('id="lineEntryAddFriend"', page)
        self.assertIn('id="lineEntryLoginBtn"', page)
        self.assertNotIn("liff.login();", init_line)
        self.assertIn("startLineLogin", page)
        self.assertNotIn("liff.login({ redirectUri })", init_line)
        self.assertIn("liff.login({ redirectUri })", page)
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
        self.assertNotIn("line.me/R/share?text=", page)
        self.assertIn("openGuardianShare", page)
        self.assertNotIn("alive_share_invite_auto_v1", page)
        self.assertNotIn("hasAutoShareTried", page)
        self.assertIn("let autoShareAttempted = false", page)
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
        self.assertIn("await openShare()", init_fn)
        self.assertNotIn("clipboard", page)
        self.assertIn("https://line.me/R/app/${LIFF_ID}?invite_from=", page)
        self.assertIn('const LIFF_ID = "2010848330-UAiqPPYD"', page)
        self.assertIn("W250724ir", page)
        self.assertIn("resolveReturnUrl", page)
        self.assertIn("appPublicOrigin", page)

    def test_share_invite_sdk_failures_use_reopen_message_and_auto_share_is_page_scoped(self):
        """Raw SDK errors and a session-wide latch would respectively confuse users and block later invitations."""
        page = (ROOT / "liff" / "share-invite.html").read_text(encoding="utf-8")
        init_fn = page[page.index("async function initializeLiff()") :]

        self.assertIn('const SHARE_REOPEN_MESSAGE = "請從 LINE App 重新開啟「一鍵邀請守護人」再試一次"', page)
        self.assertIn("alertFail(SHARE_REOPEN_MESSAGE)", init_fn)
        self.assertNotIn("alertFail((error && error.message) ? error.message : error)", init_fn)
        self.assertNotIn("sessionStorage.setItem(AUTO_SHARE_KEY", page)
        self.assertIn("if (autoShareAttempted)", init_fn)
        self.assertIn("autoShareAttempted = true", init_fn)

    def test_guardian_invite_uses_direct_share_target_picker(self):
        """Removing the picker would make the one-tap guardian invite unusable in LINE."""
        page = (ROOT / "liff" / "share-invite.html").read_text(encoding="utf-8")
        home = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn("async function openGuardianShare(inviterId)", page)
        self.assertIn("await liff.shareTargetPicker([", page)
        self.assertNotIn('location.replace("/?open=home")', page)
        self.assertNotIn('params.set("open", hash)', home)
        self.assertIn("請從 LINE App 重新開啟「一鍵邀請守護人」再試一次", page)
        self.assertIn("完成，返回原位置", page)
        self.assertIn('params.get("return")', page)

    def test_liff_links_use_query_params_for_android_compatibility(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        rich_menu = (ROOT / "line-rich-menu-config.json").read_text(encoding="utf-8")
        flex = (ROOT / "guardian_group_flex.py").read_text(encoding="utf-8")

        self.assertIn("url.searchParams.set", page)
        self.assertIn("parseLiffStateParams", page)
        self.assertIn('String(key) === "liff.state"', page)
        self.assertIn("sanitizeLoginContinuationParams", page)
        self.assertIn('read("migration_code")', page)
        self.assertIn("https://alive-checkin.onrender.com/liff/pricing.html", rich_menu)
        base = "https://liff.line.me/2010848330-UAiqPPYD"
        self.assertIn(f"{base}?open=checkin", rich_menu)
        # 一鍵邀請：直連空白 share-invite（自動 R/share），無教學大按鈕文案頁
        self.assertIn(f"{base}/liff/share-invite.html", rich_menu)
        self.assertNotIn(f"{base}/?open=share-invite", rich_menu)
        # 「需要幫忙」統一進永久 LIFF SOS 入口，不再在聊天室分三次確認
        self.assertIn(f"{base}?open=sos", rich_menu)
        self.assertNotIn(f"{base}/?open=sos", rich_menu)
        self.assertNotIn('"type": "message", "label": "需要幫忙"', rich_menu)
        self.assertIn('"label": "需要幫忙"', rich_menu)
        self.assertIn(f"{base}?open=help", rich_menu)
        self.assertNotIn(f"{base}?open=pricing", rich_menu)
        self.assertNotIn(f"{base}/?open=pricing", rich_menu)
        self.assertIn(f"{base}?open=guard", rich_menu)
        self.assertIn('url += "?" + urlencode(params, safe="/")', flex)
        self.assertNotIn('url += "/?" + urlencode(params, safe="/")', flex)
        self.assertIn("line_native_share_url", flex)
        self.assertIn("share_invite_flex", flex)
        self.assertIn("請先加入 LINE 官方帳號「每日平安」", flex)
        self.assertIn("有緊急或我沒報平安時，系統會通知你", flex)
        self.assertNotIn(f"{base}#open=", rich_menu)
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
        self.assertIn("14 天新會員安心體驗", flex)
        self.assertNotIn("完成設定即可享 7 天免費安心體驗", flex)
        self.assertNotIn("永久免費", flex)
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

    def test_welcome_flex_is_left_aligned_large_and_vertical(self):
        import guardian_group_flex as welcome_flex_module

        def walk(node):
            if isinstance(node, dict):
                yield node
                for value in node.values():
                    yield from walk(value)
            elif isinstance(node, list):
                for value in node:
                    yield from walk(value)

        bubble = welcome_flex_module.welcome_flex()
        nodes = list(walk(bubble))
        texts = [node for node in nodes if node.get("type") == "text"]
        blob = " ".join(str(node.get("text") or "") for node in texts)
        self.assertIn("每天 10 秒，報個平安", blob)
        self.assertIn("核心守護人", blob)
        self.assertNotIn("新增 1 位守護人", blob)
        for node in texts:
            self.assertNotEqual(node.get("align"), "end")
            self.assertNotEqual(node.get("align"), "center")
            self.assertTrue(node.get("wrap", False))
            self.assertNotIn("\n", str(node.get("text") or ""))

        def direct_text(box):
            return " ".join(
                str(item.get("text") or "")
                for item in box.get("contents") or []
                if isinstance(item, dict)
            )

        step_boxes = [
            node
            for node in nodes
            if node.get("type") == "box"
            and (
                "① 新增 1 位核心守護人" in direct_text(node)
                or "② 設定每日提醒時間" in direct_text(node)
            )
        ]
        self.assertEqual(len(step_boxes), 2)
        self.assertTrue(all(node.get("layout") == "vertical" for node in step_boxes))

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
        self.assertIn("liff.login({ redirectUri })", page)
        self.assertIn("buildCleanLoginRedirectUri", page)
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
        # Explicit login preserves only validated same-origin continuation state.
        self.assertIn("liff.login({ redirectUri })", page)
        self.assertIn("sanitizeLoginContinuationParams", page)
        self.assertIn('buildPublicAppUrl({ from: safeId }, "/invite")', page)
        self.assertIn('@app.get("/invite")', backend)
        self.assertIn('send_from_directory(app.static_folder, "invite.html")', backend)
        self.assertIn("public_invite_landing_url", backend)
        # LIFF Endpoint `/` must always serve SPA — never 302 invite_from to /invite
        self.assertIn("_should_keep_liff_endpoint_spa", backend)
        self.assertNotIn("_redirect_invite_to_landing", backend)
        self.assertNotIn("bounced = _redirect_invite_to_landing()", backend)
        self.assertIn("請用 LINE 開啟並加入官方 LINE 綁定", landing)
        self.assertIn("line.me/R/app/", landing)
        self.assertIn("liff.line.me/", landing)
        self.assertIn("formatLiffError", page)
        self.assertIn("fromShareReturn", page)
        self.assertIn("formatLiffError(error)", page)
        # Android 雙重確認：綁定成功只 alert 一次，並清掉 invite_from
        self.assertIn("let bindDone = false", page)
        self.assertIn("function clearInviteFromUrl", page)
        self.assertIn("async function completeGuardianBindOnce", page)
        self.assertIn("history.replaceState", page)
        self.assertIn("completeGuardianBindOnce(inviteFrom", page)
        self.assertIn("雙方都已收到「綁定完成」LINE 通知", page)
        self.assertIn("inviter_notified", page)
        init_liff = page[page.index("async function initializeLiff()") : page.index("async function initLine()")]
        self.assertNotIn("apiBindEmergencyContact(inviteFrom)", init_liff)
        self.assertIn("maybeShowInviteAcceptPrompt()", init_liff)

    def test_invite_landing_is_concise_and_links_to_complete_guardian_guide(self):
        landing = (ROOT / "invite.html").read_text(encoding="utf-8")
        guide = (ROOT / "guardian-guide.html").read_text(encoding="utf-8")
        backend = (ROOT / "app.py").read_text(encoding="utf-8")

        self.assertIn("邀請你成為核心守護人", landing)
        self.assertIn('aria-describedby="lineOpenHelp"', landing)
        self.assertIn("font-size: clamp(1.22rem, 4.8vw, 1.42rem)", landing)
        self.assertIn("複製 LINE 連結", landing)
        self.assertIn("若無法開啟", landing)
        self.assertIn('href="/guardian-guide"', landing)
        self.assertIn("查看完整守護說明", landing)
        self.assertNotIn("<details", landing)

        self.assertIn("完整守護說明", guide)
        self.assertIn("逾時未簽到", guide)
        self.assertIn("緊急 SOS", guide)
        self.assertIn("使用者主動分享的位置", guide)
        self.assertIn("解除守護關係", guide)
        self.assertIn("個資與隱私", guide)
        self.assertIn("不會全天偷追蹤", guide)
        self.assertIn("綁定成功後", guide)
        self.assertIn('href="/invite"', guide)
        self.assertIn('@app.get("/guardian-guide")', backend)
        self.assertIn('send_from_directory(app.static_folder, "guardian-guide.html")', backend)

    def test_invite_landing_tells_three_panel_story_and_has_safe_checkin_demo(self):
        landing = (ROOT / "invite.html").read_text(encoding="utf-8")

        self.assertIn("assets/guardian-story-mother-daughter-mobile.webp", landing)
        self.assertIn("女兒忙著工作，心裡還是惦記媽媽", landing)
        self.assertIn("媽媽按下「我平安」", landing)
        self.assertIn("女兒收到消息，放心繼續生活", landing)
        self.assertIn("我每天按一下「我平安」就可以了嗎？", landing)
        self.assertIn("對，10 秒就好，我收到通知就放心了", landing)
        self.assertIn("✅ 我平安", landing)
        self.assertIn("✅ 報平安成功", landing)
        self.assertIn('class="tap-hand"', landing)
        self.assertIn('id="demoCheckinButton"', landing)
        self.assertIn("點一下，體驗報平安", landing)
        self.assertIn("今日已報平安", landing)
        self.assertIn('type="button"', landing)
        self.assertNotIn('fetch("/api/checkin', landing)
        self.assertNotIn('setTimeout(function () { openLine(primaryUrl); }, 350)', landing)

    def test_guardian_group_intro_has_two_readable_ctas(self):
        flex = (ROOT / "guardian_group_flex.py").read_text(encoding="utf-8")

        self.assertIn("def _group_quick_actions", flex)
        self.assertIn("一個群組，一起守護重要的人", flex)
        self.assertIn("逾時未報平安", flex)
        self.assertIn("發出 SOS 緊急求助", flex)
        self.assertIn("今日守護宣言", flex)
        self.assertIn("綁定守護群", flex)
        self.assertIn("查看守護群狀態", flex)
        self.assertIn("自動成為守護群管理員", flex)
        self.assertNotIn('_postback_button("⚙️ 群組設定"', flex)
        self.assertNotIn('_postback_button("🟢 查看守護群"', flex)
        self.assertIn("def guardian_group_member_joined_flex", flex)
        self.assertIn("def guardian_group_setup_nudge_text", flex)
        self.assertIn("已綁定核心守護人", flex)
        self.assertIn("緊急聯絡人", flex)
        self.assertIn("core_guardian_alert_limit", flex)
        self.assertIn('_uri_button("我平安", liff_entry_url(open_action="checkin")', flex)
        self.assertIn('_postback_button("聯絡家人"', flex)
        self.assertIn('_uri_button("需要幫忙", liff_entry_url(open_action="sos")', flex)
        self.assertNotIn('_postback_button("需要幫忙", "需要幫忙"', flex)
        self.assertIn('_postback_button("守護群狀態"', flex)

    def test_all_sos_entry_buttons_share_one_liff_flow(self):
        rich_menu = (ROOT / "line-rich-menu-config.json").read_text(encoding="utf-8")
        group_flex = (ROOT / "guardian_group_flex.py").read_text(encoding="utf-8")
        sos_flow = (ROOT / "sos_flow.py").read_text(encoding="utf-8")
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        uri = "https://liff.line.me/2010848330-UAiqPPYD?open=sos"

        self.assertIn(f'"uri": "{uri}"', rich_menu)
        self.assertIn('_uri_button("需要幫忙", liff_entry_url(open_action="sos")', group_flex)
        self.assertIn('"type": "uri"', sos_flow)
        self.assertIn("function openSosFlow()", page)
        self.assertIn("startSosLocationLookup()", page)
        self.assertIn("if (sosTapCount === 1) startSosLocationLookup()", page)
        self.assertIn("sosLocationDeadlinePromise", page)
        self.assertIn("Promise.race([sosLocationPromise, sosLocationDeadlinePromise])", page)
        refresh_block = page[
            page.index("async function refreshLocationForSos()")
            : page.index("let sosLocationPromise")
        ]
        self.assertNotIn("apiUpdateLocation(", refresh_block)
        route_block = page[
            page.index("function openRequestedPage()")
            : page.index("function clearInviteFromUrl()")
        ]
        self.assertIn('if (action === "sos")', route_block)
        self.assertIn("openSosFlow();", route_block)
        self.assertNotIn('showTab("home");\n        openSosFlow();', route_block)
        bootstrap_sos = page[
            page.index('} else if (openAction === "sos") {')
            : page.index("} else if (isGuardOpen)", page.index('} else if (openAction === "sos") {'))
        ]
        self.assertNotIn('showTab("home")', bootstrap_sos)
        self.assertIn("openSosFlow();", bootstrap_sos)
        bind_block = page[
            page.index("function bindMvpHome()")
            : page.index("function bindTabEvents()")
        ]
        self.assertIn('sosBtn.addEventListener("click", openSosFlow)', bind_block)
        self.assertIn('guardSosBtn.addEventListener("click", openSosFlow)', bind_block)
        self.assertNotIn('addEventListener("click", openSosModal)', bind_block)
        self.assertIn("result.sent_at", page)
        self.assertIn("result.cancel_available", page)
        self.assertIn("發送時間", page)
        self.assertNotIn('"type": "message", "label": "需要幫忙"', rich_menu)

    def test_friend_location_invite_uses_single_share_url(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        # 好友地圖 UI 已下架；若仍保留後端邀請函式，分享網址必須單一且不走剪貼簿備援
        if "async function shareFriendInvite" not in page:
            self.assertNotIn('id="shareFriendInviteBtn"', page)
            self.assertNotIn('aria-label="好友地圖"', page)
            return
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
        self.assertNotIn('id="shareFriendInviteBtn"', page)
        self.assertNotIn('aria-label="好友地圖"', page)

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
        self.assertIn("mutualCoreCheckbox", page)
        self.assertIn("同時互相設為核心守護人", page)
        self.assertIn("apiInviteBindPreview", page)
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

    def test_active_surfaces_use_one_14_day_experience_not_permanent_free(self):
        surfaces = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                ROOT / "index.html",
                ROOT / "admin.html",
                ROOT / "pricing.html",
                ROOT / "liff" / "pricing.html",
                ROOT / "liff" / "onboarding.html",
            )
        )
        for cancelled in (
            "7 天安心體驗",
            "7 天免費安心體驗",
            "7 天試用",
            "免費方案",
            "免費版",
            "NT$0 / 永久",
        ):
            self.assertNotIn(cancelled, surfaces)
        self.assertIn("14 天安心體驗", surfaces)
        self.assertIn("不自動扣款", surfaces)
        self.assertIn("199", surfaces)
        self.assertIn("399", surfaces)
        self.assertIn("799", surfaces)


if __name__ == "__main__":
    unittest.main()
