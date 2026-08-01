# Complete Push Management Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-ready push management center with immutable versions, send-time audience eligibility, scheduled delivery, permanent per-recipient records, Chinese failure reasons, super-admin-only mutations, and the approved membership-date rules.

**Architecture:** Keep Flask routing and existing membership integration in `app.py`, but move campaign validation, immutable state transitions, recipient snapshot creation, delivery leases, retries, and aggregation into a focused `push_management.py` domain module. Persist new collections inside the existing atomically updated state document so SQLite and Render PostgreSQL follow the same transaction path. The scheduler claims work atomically, performs LINE I/O outside the database lock, and settles each result atomically.

**Tech Stack:** Python 3.11, Flask, existing SQLite/PostgreSQL key-value state layer, LINE Messaging API, vanilla HTML/CSS/JavaScript, `unittest`, Node.js built-in test runner.

## Global Constraints

- Do not add an immediate-send button, route, query parameter, or hidden shortcut.
- Only `super_admin` may create, edit, prepare, schedule, or cancel a campaign. Other authenticated admin roles are read-only.
- Every content or audience mutation creates a new immutable version; versions and delivery rows have no update/delete API.
- Editing a scheduled campaign clears its schedule and returns it to `pending_schedule`.
- Recipient eligibility is recalculated at actual send time. Explicit members and plan audiences are unioned and deduplicated by full LINE User ID.
- A missed campaign may start within 24 hours of `scheduled_at`; after that it is cancelled with a permanent Chinese reason.
- Use a stable `X-Line-Retry-Key` per delivery across at most three transient attempts. Do not retry permanent LINE errors.
- Plain text and server-approved Flex templates are allowed; arbitrary Flex JSON is rejected.
- System notifications remain operational and appear in the unified delivery-log view, but they do not become editable campaigns.
- Paid-plan changes begin a complete new 30-day or 365-day entitlement at the successful change time. Beta dates remain unchanged when only beta entitlements are used. G799 uses explicit start/end values.
- Check-in day, streak, history, level, and accumulated data never reset when a plan changes.
- Preserve the known baseline: local Python 3.14 cannot reproduce the pinned Python 3.11 dependency set, and the current main branch already has unrelated failures. All new and directly related tests must pass; final deployment verification must run on Render/Python 3.11.

## File Structure and Interfaces

- Create `push_management.py`
  - Constants: campaign states, mutable states, approved templates, audience codes, retry limit, lease duration, 24-hour late window.
  - Pure state functions: `ensure_push_state`, `create_campaign`, `update_campaign`, `prepare_campaign`, `schedule_campaign`, `cancel_campaign`, `get_campaign_detail`, `list_campaigns`, `list_delivery_records`, `append_system_delivery_record`.
  - Scheduler functions: `claim_due_campaign`, `claim_next_delivery`, `settle_delivery_attempt`, `finalize_campaign`.
  - Validation helpers reject invalid transitions, missing audience/content, arbitrary Flex payloads, non-future schedules, and immutable-row mutation attempts.
- Modify `app.py`
  - Add state defaults and hydration for `push_campaigns`, `push_campaign_versions`, `push_delivery_records`, and `push_campaign_events`.
  - Add paid/gift entitlement-date helpers and convert `admin_update_user_plan` to `mutate_state_atomically`.
  - Add explicit super-admin mutation guard and push-management admin APIs.
  - Add `send_due_push_campaigns(config, now=None)` to the Cron tick.
  - Mirror existing system notification outcomes into permanent unified delivery records.
- Modify `admin.html`
  - Add `安全與通知 → 推播管理` navigation and page registration.
  - Add campaign list/editor, audience selection, prepare/schedule/cancel actions, immutable version viewer, and unified delivery-log filters.
  - Render all mutation controls disabled/hidden unless the session role is `super_admin`.
- Create focused Python and JavaScript test files listed in the tasks below.
- Update `HANDOFF.md` with data collections, deployment order, backup/rollback notes, and Render verification commands.

### Task 1: State schema and immutable campaign lifecycle

**Files:**
- Create: `push_management.py`
- Modify: `app.py:287-320`
- Modify: `app.py:895-940`
- Test: `tests/test_push_campaign_core.py`

- [ ] **Step 1: Write failing tests for state hydration and creation**

```python
def test_create_campaign_starts_as_draft_and_creates_version_one(self):
    state = {"users": {}}
    campaign = create_campaign(
        state,
        {"name": "七日提醒", "content_type": "text", "text": "記得置頂每日平安"},
        actor="super_admin",
        now=datetime(2026, 8, 1, 10, 0),
    )
    self.assertEqual(campaign["status"], "draft")
    self.assertEqual(campaign["current_version"], 1)
    self.assertEqual(len(state["push_campaign_versions"]), 1)

def test_versions_cannot_be_deleted_or_replaced(self):
    state, campaign = campaign_fixture()
    original = copy.deepcopy(state["push_campaign_versions"][0])
    update_campaign(state, campaign["id"], {"text": "新版"}, "super_admin", NOW)
    self.assertEqual(state["push_campaign_versions"][0], original)
    self.assertEqual(len(state["push_campaign_versions"]), 2)
```

- [ ] **Step 2: Run the focused test and confirm it fails**

Run: `python -m unittest tests.test_push_campaign_core -v`

Expected: import failure for `push_management` or missing lifecycle functions.

- [ ] **Step 3: Implement state defaults, validation, IDs, and version creation**

Use UUID strings for campaign/version/event IDs. Store campaign metadata separately from immutable version snapshots. Each snapshot contains the complete sendable definition: name, content type, text/template key/template variables, plan audience, explicit member IDs, creator, and creation time.

```python
def ensure_push_state(state):
    state.setdefault("push_campaigns", [])
    state.setdefault("push_campaign_versions", [])
    state.setdefault("push_delivery_records", [])
    state.setdefault("push_campaign_events", [])
    return state
```

- [ ] **Step 4: Add transition tests and implementation**

Cover `draft → pending_schedule → scheduled → sending → completed/partially_failed/fully_failed`, plus cancellation from draft/pending/scheduled. Reject edits after sending begins. Verify that editing a scheduled campaign creates a new version, clears `scheduled_at`, and sets `pending_schedule`.

- [ ] **Step 5: Run focused tests**

Run: `python -m unittest tests.test_push_campaign_core -v`

Expected: all tests pass.

- [ ] **Step 6: Commit the task**

```powershell
git add push_management.py app.py tests/test_push_campaign_core.py
git commit -m "feat: add immutable push campaign lifecycle"
```

### Task 2: Membership entitlement dates and G799

**Files:**
- Modify: `app.py:11056-11164`
- Modify: `admin.html:1705-1745`
- Test: `tests/test_membership_entitlement_dates.py`
- Test: `tests/admin_membership_dates.behavior.test.mjs`

- [ ] **Step 1: Write failing paid-upgrade tests**

```python
def test_paid_399_to_paid_799_restarts_full_month_without_resetting_checkins(self):
    profile = seeded_profile(
        plan="paid_399",
        paid_until="2026-08-20T10:00:00",
        streak=7,
        checkins=["2026-07-26", "2026-08-01"],
    )
    changed = apply_admin_entitlement_change(
        profile, {"plan": "paid_799"}, effective_at=datetime(2026, 8, 1, 15, 30)
    )
    self.assertEqual(changed["paid_until"], "2026-08-31T15:30:00")
    self.assertEqual(changed["streak"], 7)
    self.assertEqual(changed["checkins"], profile["checkins"])

def test_trial_to_yearly_paid_restarts_365_days(self):
    profile = seeded_profile(plan="trial", trial_started_at="2026-07-20T09:00:00")
    changed = apply_admin_entitlement_change(
        profile, {"plan": "paid_799_year"}, effective_at=datetime(2026, 8, 1, 12, 0)
    )
    self.assertEqual(changed["paid_until"], "2027-08-01T12:00:00")
```

- [ ] **Step 2: Add beta and G799 tests**

Verify B399/B799 retains the original `beta_started_at` and `beta_ends_at` if only its entitlement mapping changes. Verify G799 requires explicit `gift_started_at` and `gift_ends_at`, sets `membership_source="gift"`, and does not create an order.

- [ ] **Step 3: Run tests and confirm failures**

Run: `python -m unittest tests.test_membership_entitlement_dates -v`

Expected: old code keeps an existing future `paid_until`, lacks G799, and uses non-atomic load/save.

- [ ] **Step 4: Implement a single atomic entitlement-change path**

Refactor `admin_update_user_plan` so `effective_at` is captured once, all preserved guardian/check-in fields stay untouched, and the mutation runs through `mutate_state_atomically`. Do not accept client-supplied past timestamps for a normal paid upgrade. Add audit fields `membership_changed_at`, `membership_changed_by`, `previous_plan`, and `expiry_review_required`.

- [ ] **Step 5: Add safe legacy expiry backfill**

When an active paid member lacks `paid_until`, choose the most recent trustworthy paid order timestamp or membership audit timestamp. If none exists, leave the date unset and set `expiry_review_required=True`; never invent a date. Expose this flag in the member row.

- [ ] **Step 6: Update the admin member controls**

Add G799 as a separate gift action requiring start/end inputs. Keep ordinary plan selectors free of G799 ambiguity. After a paid change, show the server-returned new expiry date. Add a JS behavior test proving the request cannot silently reuse the old expiry.

- [ ] **Step 7: Run related tests**

Run: `python -m unittest tests.test_membership_entitlement_dates -v`

Run: `node --test tests/admin_membership_dates.behavior.test.mjs`

Expected: all tests pass.

- [ ] **Step 8: Commit the task**

```powershell
git add app.py admin.html tests/test_membership_entitlement_dates.py tests/admin_membership_dates.behavior.test.mjs
git commit -m "feat: enforce approved membership entitlement dates"
```

### Task 3: Send-time audience resolution and campaign preparation

**Files:**
- Modify: `push_management.py`
- Modify: `app.py:2535-2615`
- Test: `tests/test_push_campaign_audience.py`

- [ ] **Step 1: Write failing audience tests**

Test all audience codes: 14-day trial, paid monthly/yearly 199/399/799, B399, B799, and G799. Verify expired, downgraded, or upgraded members are evaluated from their current profile at send time.

```python
def test_member_upgraded_after_scheduling_uses_current_plan(self):
    state, campaign = prepared_campaign(plan_codes=["paid_799"])
    state["users"]["U123"]["plan"] = "paid_799"
    recipients = resolve_recipients(state, campaign, NOW, classify_membership)
    self.assertEqual([row["line_user_id"] for row in recipients], ["U123"])

def test_explicit_and_plan_targets_are_deduplicated_by_full_uid(self):
    state, campaign = prepared_campaign(plan_codes=["paid_799"], explicit=["U123"])
    recipients = resolve_recipients(state, campaign, NOW, classify_membership)
    self.assertEqual(len(recipients), 1)
```

- [ ] **Step 2: Run the focused test and confirm it fails**

Run: `python -m unittest tests.test_push_campaign_audience -v`

- [ ] **Step 3: Implement canonical membership audience classification**

Return one stable code per profile at a supplied `now`. Prefer active beta/gift classification over mapped paid entitlement. Inactive or review-required memberships are excluded unless explicitly targeted and still LINE-reachable; explicit targeting never bypasses blocked/missing LINE UID validation.

- [ ] **Step 4: Implement preparation preview**

`prepare_campaign` validates the current version and records counts by audience code without freezing the final recipient list. Store the preview timestamp and counts as an event. Actual delivery rows are created only when the scheduler claims the campaign.

- [ ] **Step 5: Run focused tests**

Run: `python -m unittest tests.test_push_campaign_audience -v`

Expected: all tests pass.

- [ ] **Step 6: Commit the task**

```powershell
git add push_management.py app.py tests/test_push_campaign_audience.py
git commit -m "feat: resolve push audience at send time"
```

### Task 4: Scheduler, leases, retries, and Chinese failures

**Files:**
- Modify: `push_management.py`
- Modify: `app.py:17145-17233`
- Test: `tests/test_push_campaign_scheduler.py`

- [ ] **Step 1: Write failing scheduler boundary tests**

Cover exact schedule time, 23:59:59 late, 24:00:01 late, duplicate Cron workers, stale lease recovery, stable retry keys, transient retry count, permanent failure, empty audience, and mixed results.

```python
def test_campaign_more_than_24_hours_late_is_cancelled_without_send(self):
    result = send_due_push_campaigns(config, now=SCHEDULED_AT + timedelta(hours=24, seconds=1))
    self.assertEqual(result[0]["cancelled"], 1)
    self.assertEqual(sender.calls, [])
    self.assertEqual(delivery_event(state)["reason_zh"], "已超過預定發送時間 24 小時，系統自動取消。")

def test_retry_uses_same_line_retry_key_at_most_three_times(self):
    sender.fail_transiently(2)
    send_due_push_campaigns(config, now=SCHEDULED_AT)
    self.assertEqual(len(set(sender.retry_keys)), 1)
    self.assertEqual(len(sender.retry_keys), 3)
```

- [ ] **Step 2: Run the focused test and confirm it fails**

Run: `python -m unittest tests.test_push_campaign_scheduler -v`

- [ ] **Step 3: Implement atomic claim and per-delivery settlement**

Claim one due campaign with a worker UUID and lease expiry inside `mutate_state_atomically`. Create immutable delivery rows containing campaign/version IDs, recipient name, full LINE UID, current audience/plan snapshot, scheduled time, retry key, and `pending` status. Claim and settle each delivery atomically; the LINE request occurs between those transactions.

- [ ] **Step 4: Implement error classification and final states**

Map token/config errors, blocked user, invalid UID, LINE 4xx, LINE 429, LINE 5xx, timeout, and unknown errors to Chinese reason/action fields while retaining a bounded technical detail. Aggregate final state as completed, partially failed, or fully failed.

- [ ] **Step 5: Integrate the job into `run_cron_tick`**

Add `"push_campaigns": send_due_push_campaigns` to `always`. A campaign-level failure must be returned in the task result without preventing safety-critical existing jobs from running. Preserve existing Cron authentication.

- [ ] **Step 6: Run scheduler and Cron tests**

Run: `python -m unittest tests.test_push_campaign_scheduler tests.test_scheduler_tick -v`

Expected: all new tests pass and no additional failures appear in the existing Cron suite.

- [ ] **Step 7: Commit the task**

```powershell
git add push_management.py app.py tests/test_push_campaign_scheduler.py
git commit -m "feat: schedule reliable push campaign delivery"
```

### Task 5: Admin APIs and authorization

**Files:**
- Modify: `app.py:17595-17624`
- Modify: `app.py:20000-20720`
- Test: `tests/test_push_campaign_admin_api.py`

- [ ] **Step 1: Write failing API and role tests**

Test unauthenticated 401, missing CSRF 403, viewer/operations/finance write 403, super-admin write success, and read access for every authenticated role. Test that no route supports immediate sending and that delivery/version DELETE/PATCH calls return 404 or 405.

- [ ] **Step 2: Run the focused test and confirm it fails**

Run: `python -m unittest tests.test_push_campaign_admin_api -v`

- [ ] **Step 3: Add a strict super-admin guard**

```python
def _super_admin_mutation_guard():
    denied = _admin_guard(write=True)
    if denied:
        return denied
    if str(session.get("admin_role") or "viewer") != "super_admin":
        return jsonify({"error": "forbidden", "required_role": "super_admin"}), 403
    return None
```

Record denied and successful mutation events with the existing admin audit mechanism.

- [ ] **Step 4: Add explicit CRUD-like lifecycle routes**

Add read routes for campaign list/detail, versions, delivery records, approved templates, and audience codes. Add mutation routes only for create, edit, prepare, schedule, and cancel. Every mutation response returns the canonical campaign object and current version number.

- [ ] **Step 5: Validate pagination and filters**

Delivery filters support campaign ID, source (`campaign`/`system`), kind, status, plan/audience code, member name, LINE UID, and date range. Use cursor or offset/limit with a documented maximum; never trim stored records.

- [ ] **Step 6: Run focused tests**

Run: `python -m unittest tests.test_push_campaign_admin_api -v`

Expected: all tests pass.

- [ ] **Step 7: Commit the task**

```powershell
git add app.py tests/test_push_campaign_admin_api.py
git commit -m "feat: expose secure push management APIs"
```

### Task 6: Unified permanent system delivery records

**Files:**
- Modify: `push_management.py`
- Modify: `app.py:14857-14918`
- Test: `tests/test_push_campaign_system_logs.py`

- [ ] **Step 1: Write failing system-log mirroring tests**

Verify SOS, binding, check-in, day-7, beta Day 2, and other existing `append_notification_log` calls produce a permanent unified record with recipient, plan snapshot, scheduled/actual time, result, and Chinese reason. Verify the legacy 100-row trim does not trim `push_delivery_records`.

- [ ] **Step 2: Run the focused test and confirm it fails**

Run: `python -m unittest tests.test_push_campaign_system_logs -v`

- [ ] **Step 3: Mirror legacy notifications into the permanent ledger**

Extend `append_notification_log` to call `append_system_delivery_record` with `source="system"` and a stable event ID when supplied. Preserve the current `notification_logs[-100:]` behavior for dashboard compatibility; the new ledger is append-only and excluded from cleanup.

- [ ] **Step 4: Fill membership and recipient snapshots**

At each caller, provide or resolve recipient display name, full LINE UID, current plan, membership source, beta/gift code, scheduled time, actual time, success/failure, Chinese reason/action, and bounded technical detail. Use `unknown` only when old call sites genuinely lack context.

- [ ] **Step 5: Run related notification tests**

Run: `python -m unittest tests.test_push_campaign_system_logs tests.test_day7_pin_reminder tests.test_bind_notify -v`

Expected: all new tests pass; existing related tests gain no new failures.

- [ ] **Step 6: Commit the task**

```powershell
git add push_management.py app.py tests/test_push_campaign_system_logs.py
git commit -m "feat: retain permanent unified push delivery records"
```

### Task 7: Push management admin interface

**Files:**
- Modify: `admin.html:552-599`
- Modify: `admin.html:1091-1165`
- Modify: `admin.html:1165-2550`
- Test: `tests/admin_push_management.behavior.test.mjs`

- [ ] **Step 1: Write failing DOM behavior tests**

Test navigation registration, status labels, super-admin mutation visibility, read-only roles, create/edit payloads, preparation preview, schedule confirmation, cancellation, immutable version display, delivery filters, and absence of an immediate-send control/string/API call.

- [ ] **Step 2: Run the JS test and confirm it fails**

Run: `node --test tests/admin_push_management.behavior.test.mjs`

- [ ] **Step 3: Add navigation and page structure**

Register `push-management` in `ADMIN_PAGES` and `ADMIN_PAGE_TITLES`, add the link under `安全與通知`, and add a dedicated panel containing campaign list, editor drawer/section, status summary, version history, and delivery table.

- [ ] **Step 4: Build the campaign editor**

Fields: name, content type, plain text or approved template selector/variables, plan audiences, explicit member search/selection, and read-only creator/time/version. Buttons: save draft, save changes, prepare schedule, schedule, cancel. There is no send button.

- [ ] **Step 5: Build read-only versions and delivery filters**

Versions show before/after snapshots, editor, and time. Delivery rows show actual recipient name, LINE UID, plan/audience at send time, scheduled/actual time, attempts, success/failure, Chinese reason/action, and collapsible technical detail.

- [ ] **Step 6: Enforce role behavior in UI and server truth**

Use the existing session role payload to set read-only mode. UI controls are a convenience only; API tests remain the authorization guarantee. Show `只有最高管理員可以新增、修改、排程或取消推播。` for non-super-admin roles.

- [ ] **Step 7: Run all admin JavaScript behavior tests**

Run: `node --test tests/*.behavior.test.mjs`

Expected: the new suite passes and no additional existing failures appear.

- [ ] **Step 8: Commit the task**

```powershell
git add admin.html tests/admin_push_management.behavior.test.mjs
git commit -m "feat: add push management admin interface"
```

### Task 8: Migration, integration verification, and deployment handoff

**Files:**
- Modify: `HANDOFF.md`
- Modify if required by existing project convention: `render.yaml`
- Test: all new and directly related tests

- [ ] **Step 1: Add an idempotent state migration test**

Load a pre-feature state document and verify hydration adds empty collections without changing users, orders, check-ins, notification logs, or revision semantics. Run hydration twice and assert identical business data.

- [ ] **Step 2: Document the deployment sequence**

In `HANDOFF.md`, record: database backup, branch/commit, Render Python 3.11 build, state hydration, smoke-test read APIs, super-admin draft creation, version edit, near-future schedule to an allowlisted test member, delivery verification, and rollback procedure. State clearly that rollback code must not delete newly written permanent ledger rows.

- [ ] **Step 3: Run syntax and focused Python verification**

```powershell
python -m py_compile app.py push_management.py
python -m unittest `
  tests.test_membership_entitlement_dates `
  tests.test_push_campaign_core `
  tests.test_push_campaign_audience `
  tests.test_push_campaign_scheduler `
  tests.test_push_campaign_admin_api `
  tests.test_push_campaign_system_logs -v
```

Expected: all listed tests pass.

- [ ] **Step 4: Run focused JavaScript verification**

```powershell
node --test tests/admin_membership_dates.behavior.test.mjs tests/admin_push_management.behavior.test.mjs
```

Expected: all listed tests pass.

- [ ] **Step 5: Compare broad suites against the recorded baseline**

Run the repository's normal Python and JavaScript commands. Record totals and verify there are no new failures beyond the known baseline. Do not claim the entire local baseline is green.

- [ ] **Step 6: Request code review and address findings**

Use `superpowers:requesting-code-review`, inspect every finding, and rerun the relevant focused tests after any change.

- [ ] **Step 7: Perform final verification before claiming completion**

Use `superpowers:verification-before-completion`. Confirm `git diff --check`, working-tree scope, test outputs, absence of immediate-send UI/API, and migration idempotence.

- [ ] **Step 8: Commit documentation and final integration changes**

```powershell
git add HANDOFF.md render.yaml app.py push_management.py admin.html tests
git commit -m "docs: add push management deployment runbook"
```

- [ ] **Step 9: Publish and deploy only after local verification**

Push `codex/push-management-center`, open a ready pull request, merge after checks, and deploy the merged commit through Render. On Render, verify Python 3.11 dependency installation, `/health`, admin read-only access, super-admin mutation authorization, one allowlisted scheduled delivery, immutable version history, and the permanent delivery row. Do not use a production-wide audience for the first smoke test.

## Self-Review Checklist

- [ ] Every approved campaign state has a tested transition and a Traditional Chinese label.
- [ ] Draft/save/edit never sends; no immediate-send surface exists.
- [ ] Content, audience, creator, and timestamps are preserved per immutable version.
- [ ] Recipients are recalculated at actual send time and deduplicated by full LINE UID.
- [ ] B399, B799, and G799 are distinguishable in both eligibility and records.
- [ ] Paid entitlement restarts from upgrade success; beta timing does not.
- [ ] Check-in progression and level data remain unchanged across upgrades.
- [ ] Late-send, lease, retry, cancellation, and mixed-result boundaries are tested.
- [ ] System notifications and campaign deliveries share one permanent read model.
- [ ] Only super-admin can mutate; all authenticated admin roles can read.
- [ ] No new collection is truncated or deleted by cleanup.
- [ ] Render/Python 3.11 verification is required before production completion is claimed.
