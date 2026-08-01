# Refund Policy, Reminder, Support, and Guardian Dates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update public policies and support flows, add authenticated refund requests, enforce plan-specific safety-guard quotas, separate 799 reminder defaults from their maximum, keep 399 notes web-only, and show trustworthy invite/review dates in guardian operations.

**Architecture:** Reuse the existing authenticated support-ticket and admin-refund systems instead of creating a second case-management store. Add small policy helpers to `app.py` for refund eligibility, reminder defaults, and guardian-date projection; keep the existing payment provider integration intact while removing provider names from public copy. All behavior changes follow red-green TDD and preserve saved member settings.

**Tech Stack:** Python 3 `unittest`, Flask-compatible API with MiniApp fallback, vanilla HTML/CSS/JavaScript, LINE Messaging API text notifications, JSON/PostgreSQL state abstraction.

## Global Constraints

- Do not modify `main` directly; work only on `codex/refund-policy-reminder-admin-dates`.
- Do not remove existing payment, order, refund, audit, or provider backend code.
- Public pages must not advertise SMS or name a specific payment provider.
- Customer support replies use Email and state a 1–3 business-day response time.
- Refund forms create review tickets only; they never execute a payment refund automatically.
- Existing custom reminder times must not be overwritten.
- Safety-guard usage resets by Asia/Taipei calendar date and cannot be reset by changing device or browser storage.
- Missing historical dates display `舊資料未記錄`; never synthesize dates.
- Do not break check-in, SOS, guardian binding, support tickets, orders, or admin refunds.

---

### Task 1: Public policy, FAQ, pricing footer, and contact copy

**Files:**
- Create: `tests/test_public_policy_refund_ui.py`
- Modify: `faq.html`
- Modify: `privacy.html`
- Modify: `terms.html`
- Modify: `liff/pricing.html`
- Modify: `index.html`
- Modify: `app.py` (`line_auto_reply_text` support/FAQ branches)

**Interfaces:**
- Consumes: existing routes `/faq`, `/privacy`, `/terms`, `/liff/pricing.html`.
- Produces: public Email refund link and LIFF member refund deep link used by Task 2.

- [ ] **Step 1: Write failing public-copy tests**

```python
class PublicPolicyRefundUiTests(unittest.TestCase):
    def test_public_pages_do_not_advertise_sms_or_named_provider(self):
        for path in ("faq.html", "privacy.html", "terms.html", "liff/pricing.html", "index.html"):
            page = Path(path).read_text(encoding="utf-8")
            self.assertNotIn("藍新", page, path)
            self.assertNotIn("簡訊", page, path)

    def test_pricing_footer_has_required_links(self):
        page = Path("liff/pricing.html").read_text(encoding="utf-8")
        self.assertIn("常見問題", page)
        self.assertIn("聯絡我們", page)
        self.assertIn("隱私權政策", page)
        self.assertIn("退款申請", page)
        self.assertIn("mailto:alivecheckin.tw@gmail.com", page)
        self.assertIn("subject=%E9%80%80%E6%AC%BE%E7%94%B3%E8%AB%8B", page)

    def test_refund_and_privacy_copy_is_consistent(self):
        for path in ("faq.html", "privacy.html"):
            page = Path(path).read_text(encoding="utf-8")
            self.assertIn("14 天安心體驗", page)
            self.assertIn("付費訂閱後 7 日內", page)
            self.assertIn("解除關係", page)
            self.assertIn("刪除自己的個人資料", page)
        member = Path("index.html").read_text(encoding="utf-8")
        self.assertNotIn("<h3>隱私權申請</h3>", member)
```

- [ ] **Step 2: Run the new tests and verify RED**

Run: `python -m unittest tests.test_public_policy_refund_ui -v`

Expected: failures for provider/SMS text, missing footer links, missing refund policy, and existing privacy-request section.

- [ ] **Step 3: Implement minimal public copy and links**

Use neutral payment text and this policy copy in both FAQ and privacy pages:

```html
<h2>退款政策</h2>
<p>本服務提供 14 天安心體驗。付費訂閱後 7 日內，若尚未啟用付費服務，可提出全額退款申請。送出申請後，客服會確認訂單、付款時間與使用狀態，申請不代表退款已核准。</p>
<p><a href="mailto:alivecheckin.tw@gmail.com?subject=%E9%80%80%E6%AC%BE%E7%94%B3%E8%AB%8B">寄 Email 申請</a>，或登入會員中心填寫退款表單。</p>
```

Replace LINE-message support copy with:

```text
請到每日平安網頁的「會員中心 → 聯絡客服」填寫問題，或寄信到 alivecheckin.tw@gmail.com。客服會在 1～3 個工作天內以 Email 回覆。
```

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m unittest tests.test_public_policy_refund_ui tests.test_product_rules -v`

Expected: new policy tests pass; update only old assertions that explicitly require removed public copy.

- [ ] **Step 5: Commit Task 1**

```powershell
git add tests/test_public_policy_refund_ui.py faq.html privacy.html terms.html liff/pricing.html index.html app.py
git commit -m "feat: update public policy and support links"
```

### Task 2: Authenticated refund request and Email-first support form

**Files:**
- Create: `tests/test_refund_request.py`
- Modify: `app.py` (`create_support_ticket`, new refund helpers and member routes)
- Modify: `index.html` (support/refund form and ticket rendering)
- Modify: `admin.html` (refund request details and Email delivery state)

**Interfaces:**
- Produces: `member_refundable_orders(data_file, line_user_id, now=None) -> (dict, int)`.
- Produces: `create_member_refund_request(data_file, payload, now=None, config=None) -> (dict, int)`.
- Produces: authenticated `GET /api/refund/eligible-orders` and `POST /api/refund/requests`.
- Consumes: existing `create_support_ticket`, `send_support_email`, `/api/support/tickets`, and admin support-ticket list.

- [ ] **Step 1: Write failing refund-domain tests**

```python
def test_member_sees_only_own_paid_orders_within_seven_days(self):
    result, code = app.member_refundable_orders(self.data_file, "U-owner", now=self.now)
    self.assertEqual(code, 200)
    self.assertEqual([row["order_id"] for row in result["orders"]], ["AC-OWN"])

def test_refund_request_rejects_foreign_expired_and_duplicate_orders(self):
    for order_id, expected in (("AC-OTHER", "refund_order_not_owned"), ("AC-OLD", "refund_window_expired")):
        result, code = app.create_member_refund_request(
            self.data_file,
            {"line_user_id": "U-owner", "order_id": order_id, "email": "owner@example.com", "reason": "未使用"},
            now=self.now,
        )
        self.assertEqual(code, 409)
        self.assertEqual(result["error"], expected)

def test_valid_refund_creates_ticket_but_does_not_refund_order(self):
    result, code = app.create_member_refund_request(
        self.data_file,
        {"line_user_id": "U-owner", "order_id": "AC-OWN", "email": "owner@example.com", "reason": "尚未啟用", "unused_confirmed": True},
        now=self.now,
    )
    self.assertEqual(code, 201)
    self.assertEqual(result["ticket"]["category"], "付款退款")
    self.assertEqual(result["ticket"]["refund_order_id"], "AC-OWN")
    state = app.load_state(self.data_file)
    self.assertEqual(state["orders"][0]["status"], "paid")
    self.assertEqual(state["orders"][0].get("refunds") or [], [])
```

- [ ] **Step 2: Run refund tests and verify RED**

Run: `python -m unittest tests.test_refund_request -v`

Expected: errors because the refund helpers/routes do not exist.

- [ ] **Step 3: Implement refund eligibility and ticket creation**

Implement ownership, `paid_at or updated_at or created_at` age, paid-status, unused confirmation, and open-duplicate checks. Store these ticket fields:

```python
ticket.update({
    "request_type": "refund",
    "refund_order_id": order_id,
    "refund_reason": reason[:1000],
    "unused_confirmed": True,
    "refund_requested_at": now.isoformat(timespec="seconds"),
    "refund_review_status": "pending",
})
```

Send an admin notice using `send_support_email` after the ticket is durably saved. On delivery failure append a failed `delivery_log` row and still return `201` with `admin_email_sent: false`.

- [ ] **Step 4: Add authenticated route tests**

```python
def test_refund_routes_require_verified_line_identity(self):
    self.assertEqual(self.client.get("/api/refund/eligible-orders").status_code, 401)
    self.assertEqual(self.client.post("/api/refund/requests", json={}).status_code, 401)
```

Run: `python -m unittest tests.test_refund_request.RefundRequestRouteTests -v`

Expected: FAIL before routes are added; PASS after routes use `_authenticated_line_user`.

- [ ] **Step 5: Add member support/refund UI**

Change the support form to require Email, category, subject, and message; state `1～3 個工作天內以 Email 回覆`. Add a refund subsection with an owned-order select, reason, unused-service checkbox, Email link, and authenticated form submission to `/api/refund/requests`. Preserve all fields on failure and display the created ticket ID on success.

- [ ] **Step 6: Run support/refund regression tests**

Run: `python -m unittest tests.test_refund_request tests.test_support_api tests.test_support_center -v`

Expected: all pass, zero failures.

- [ ] **Step 7: Commit Task 2**

```powershell
git add tests/test_refund_request.py app.py index.html admin.html
git commit -m "feat: add authenticated refund requests"
```

### Task 3: Plan-specific safety-guard quota and single map link

**Files:**
- Modify: `tests/test_safety_guard.py`
- Modify: `tests/test_sos_rules.py`
- Modify: `app.py` (`update_location`, safety snapshot, SOS message)
- Modify: `index.html` (remaining quota and button state)

**Interfaces:**
- Consumes: `PLAN_LIMITS[*]["safety_guard_daily_limit"]`, `update_location`, `safety_guard_snapshot`.
- Produces: snapshot fields `daily_limit`, `used_today`, `remaining_today`.

- [ ] **Step 1: Write failing quota tests**

```python
def test_plan_daily_limits_are_enforced_on_new_sessions(self):
    expected = {"trial": 2, "paid_199": 2, "paid_399": 3, "paid_799": 5}
    for plan, limit in expected.items():
        profile = self.seed_bound_member(plan)
        for index in range(limit):
            result, code = self.start_then_stop(profile["line_user_id"], minute=index)
            self.assertEqual(code, 200)
        result, code = self.start(profile["line_user_id"], minute=limit)
        self.assertEqual(code, 429)
        self.assertEqual(result["daily_limit"], limit)

def test_refresh_does_not_consume_quota_or_notify_again(self):
    first, first_code = self.start("U-trial")
    refreshed, refresh_code = self.refresh("U-trial")
    self.assertEqual((first_code, refresh_code), (200, 200))
    self.assertEqual(refreshed["safety_guard"]["used_today"], 1)
    self.assertEqual(len(self.sent_messages), 1)
```

- [ ] **Step 2: Run quota tests and verify RED**

Run: `python -m unittest tests.test_safety_guard.SafetyGuardQuotaTests -v`

Expected: snapshot keys and/or repeated-session enforcement assertions fail.

- [ ] **Step 3: Implement quota snapshot and Taiwan-date counting**

Use `current_app_time(config or {})` instead of naive `datetime.now()` for the usage date. Only increment when `not was_active`; keep `refresh_only` free. Return:

```python
snap.update({
    "daily_limit": daily_limit,
    "used_today": usage_count,
    "remaining_today": max(0, daily_limit - usage_count) if daily_limit else 0,
})
```

Disable the start control when `remaining_today == 0` and show `今日剩餘 0 次，明天可再使用`.

- [ ] **Step 4: Write and run SOS map-link test**

```python
def test_sos_message_has_one_standalone_map_url(self):
    message = self.capture_sos_message(latitude=25.033, longitude=121.5654)
    self.assertEqual(message.count("https://www.google.com/maps?q="), 1)
    self.assertIn("\nhttps://www.google.com/maps?q=25.033,121.5654\n", message)
    self.assertNotIn("查看地圖按鈕", message)
```

Run before implementation and expect failure because the URL is attached to label punctuation. Then format the URL on its own line and rerun `tests.test_sos_rules`.

- [ ] **Step 5: Commit Task 3**

```powershell
git add tests/test_safety_guard.py tests/test_sos_rules.py app.py index.html
git commit -m "fix: enforce safety guard quotas and map link"
```

### Task 4: 799 default two reminders, maximum three, and 399 web-only notes

**Files:**
- Modify: `tests/test_reminder_times.py`
- Modify: `tests/test_calendar_notes.py`
- Modify: `app.py` (`PLAN_LIMITS`, reminder default helper, API payloads)
- Modify: `index.html`
- Modify: `liff/member.html`
- Modify: `liff/onboarding.html`

**Interfaces:**
- Produces: `default_daily_reminder_count(profile) -> int`.
- Keeps: `plan_rules(profile)["daily_reminders"]` as maximum count.
- Adds: `PLAN_LIMITS[paid_799|paid_799_year]["default_daily_reminders"] = 2` and B799 entitlement resolution.

- [ ] **Step 1: Write failing reminder-default tests**

```python
def test_799_defaults_to_two_but_accepts_three(self):
    for profile in (
        {"plan": "paid_799"},
        {"plan": "paid_799_year"},
        {"plan": "paid_799", "beta_cohort": "B799"},
    ):
        self.assertEqual(app.plan_rules(profile)["daily_reminders"], 3)
        self.assertEqual(app.default_daily_reminder_count(profile), 2)
        self.assertEqual(app.reminder_times_for_profile(profile), ["12:00", "18:00"])
        self.assertEqual(app.apply_reminder_times_to_profile(profile, times=["08:00", "13:00", "20:00"]), ["08:00", "13:00", "20:00"])

def test_saved_custom_times_are_preserved(self):
    profile = {"plan": "paid_799", "reminder_times": ["09:30", "16:30", "21:30"]}
    self.assertEqual(app.reminder_times_for_profile(profile), ["09:30", "16:30", "21:30"])
```

- [ ] **Step 2: Run reminder tests and verify RED**

Run: `python -m unittest tests.test_reminder_times -v`

Expected: 799 default currently returns three times.

- [ ] **Step 3: Implement separate default count**

```python
def default_daily_reminder_count(profile):
    rules = plan_rules(profile)
    maximum = int(rules.get("daily_reminders") or 1)
    requested = int(rules.get("default_daily_reminders") or maximum)
    return max(1, min(maximum, requested))
```

Use this helper only when there are no saved valid reminder times. API fields `daily_reminders` remain max; add `default_daily_reminders` for UI selection.

- [ ] **Step 4: Write and run 399 web-only reminder tests**

```python
def test_399_calendar_notes_are_web_only(self):
    profile = self.active_profile("paid_399")
    status = app.build_status(profile)
    self.assertTrue(status["calendar_notes_enabled"])
    self.assertFalse(status["smart_reminders_enabled"])
    denied, code = app.save_smart_reminder(self.data_file, {"line_user_id": profile["line_user_id"], "title": "回診"})
    self.assertEqual(code, 403)
```

Verify UI copy contains `399 網頁提醒` and `未登入或關閉網頁時不會主動送達`, while the LINE-reminder button remains hidden for 399.

- [ ] **Step 5: Run reminder/calendar regressions**

Run: `python -m unittest tests.test_reminder_times tests.test_calendar_notes tests.test_checkin_postback_and_smart -v`

Expected: all pass, zero failures.

- [ ] **Step 6: Commit Task 4**

```powershell
git add tests/test_reminder_times.py tests/test_calendar_notes.py app.py index.html liff/member.html liff/onboarding.html
git commit -m "feat: separate reminder defaults from plan limits"
```

### Task 5: Guardian operations invite and review dates

**Files:**
- Create: `tests/test_admin_guardian_operation_dates.py`
- Modify: `app.py` (`bind_emergency_contact`, `admin_summary`)
- Modify: `admin.html` (`rewardList`, `inviteEdgeList`)

**Interfaces:**
- Stores on new rewards: `invited_at`, `accepted_at`.
- Produces on admin `invite_edges` and `contact_rewards`: `invited_at`, `accepted_at` strings or empty strings.

- [ ] **Step 1: Write failing domain and UI tests**

```python
def test_admin_summary_exposes_invited_and_accepted_dates(self):
    summary = app.admin_summary(self.data_file)
    edge = summary["invite_edges"][0]
    reward = summary["contact_rewards"][0]
    self.assertEqual(edge["invited_at"], "2026-08-01T09:00:00+08:00")
    self.assertEqual(edge["accepted_at"], "2026-08-01T10:00:00+08:00")
    self.assertEqual(reward["invited_at"], edge["invited_at"])
    self.assertEqual(reward["accepted_at"], edge["accepted_at"])

def test_admin_ui_labels_both_dates_and_handles_legacy_rows(self):
    page = Path("admin.html").read_text(encoding="utf-8")
    self.assertIn("邀請日期", page)
    self.assertIn("接受／審核日期", page)
    self.assertIn("舊資料未記錄", page)
```

- [ ] **Step 2: Run new tests and verify RED**

Run: `python -m unittest tests.test_admin_guardian_operation_dates -v`

Expected: missing `invited_at` fields and UI labels.

- [ ] **Step 3: Persist and project trustworthy dates**

When a pending invite exists, store its ID and created time on the accepted contact/reward:

```python
if pending_invite:
    bound_contact["accepted_invite_id"] = pending_invite.get("id") or ""
    reward["invited_at"] = pending_invite.get("created_at") or ""
reward["accepted_at"] = accepted_at
```

For old data, match `guardian_invites` only by inviter ID, invitee ID, and accepted status. If no unambiguous match exists, return an empty date and let the UI display `舊資料未記錄`.

- [ ] **Step 4: Render dates safely in admin**

Use `formatDate(value)` only when non-empty:

```javascript
const operationDate = (value) => value ? formatDate(value) : "舊資料未記錄";
```

Render both labels in reward and invite-edge cards with `escapeHtml(operationDate(...))`.

- [ ] **Step 5: Run guardian/admin regressions**

Run: `python -m unittest tests.test_admin_guardian_operation_dates tests.test_bind_and_home_gate tests.test_admin_reset_test_account -v`

Expected: new tests pass; record any unrelated legacy failures separately and run the focused binding/date tests to zero failures.

- [ ] **Step 6: Commit Task 5**

```powershell
git add tests/test_admin_guardian_operation_dates.py app.py admin.html
git commit -m "feat: show guardian invite and review dates"
```

### Task 6: Final verification, PR, deployment, and live acceptance

**Files:**
- Modify only failing files required by the confirmed specification.

**Interfaces:**
- Consumes all outputs from Tasks 1–5.
- Produces a merged PR and verified Render deployment.

- [ ] **Step 1: Run focused zero-failure suite**

```powershell
python -m unittest tests.test_public_policy_refund_ui tests.test_refund_request tests.test_safety_guard tests.test_sos_rules tests.test_reminder_times tests.test_calendar_notes tests.test_admin_guardian_operation_dates tests.test_support_api tests.test_support_center tests.test_admin_reset_test_account
```

Expected: zero failures and zero errors.

- [ ] **Step 2: Run static and browser-script checks**

```powershell
python -m py_compile app.py
git diff --check
node --test tests
```

Expected: commands exit 0. If the repository-wide Node suite contains an unrelated baseline failure, document it and rerun every changed-feature Node file to zero failures.

- [ ] **Step 3: Review public-string scope**

Run: `rg -n "藍新|簡訊|LINE 留言|隱私權申請" faq.html privacy.html terms.html liff/pricing.html index.html`

Expected: no public claims remain; technical backend files are intentionally excluded.

- [ ] **Step 4: Commit any final focused corrections**

```powershell
git add app.py admin.html index.html liff/pricing.html liff/member.html liff/onboarding.html faq.html privacy.html terms.html tests
git commit -m "test: verify refund and guardian operations release"
```

- [ ] **Step 5: Push branch, open PR, and merge only after checks pass**

```powershell
git push -u origin codex/refund-policy-reminder-admin-dates
```

Create a PR targeting `main`, include exact passing counts, review the changed-file list, then squash-merge.

- [ ] **Step 6: Verify Render live deployment**

Check `/health`, `/faq`, `/privacy`, `/liff/pricing.html`, and `/admin.html`. Confirm HTTP 200 and unique new copy markers. Use an authenticated test member to verify refund-order ownership, support Email response copy, safety-guard remaining quota, 399 web-only notes, and admin invite/review dates without executing a real refund.
