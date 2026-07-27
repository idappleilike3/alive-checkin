# Member Guardian and SOS Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the migrated member experience, require one genuinely bound LINE core guardian, stop stale group summaries, unify SOS delivery, prevent abusive SOS use without removing emergency access, control LINE message costs, and make smart-reminder state explicit.

**Architecture:** Keep the existing Flask/state-store and single-page LIFF architecture, but centralize server-authoritative readiness and recipient calculations. Frontend routing consumes those explicit states and never treats local flags, unbound contacts, or stale group snapshots as authorization.

**Tech Stack:** Python 3.12, Flask, LINE Messaging API/LIFF SDK, vanilla JavaScript, `unittest`, Node behavior tests.

## Global Constraints

- The authenticated LINE user ID is the only member identity accepted by protected APIs.
- At least one notifiable, bound LINE core guardian is required to unlock the member home flow.
- Emergency contacts and unbound contact records do not satisfy the guardian requirement.
- Guardian-group daily summaries default off and only include currently eligible members.
- SOS is available to every plan but retains the three-tap UI, daily limit, cooldown, fresh-location-only rule, and delivery audit.
- SOS emergency group delivery is independent from optional daily-summary preferences.
- A single false alarm never completely disables emergency help; 110/119 and one primary core-guardian fallback remain available during an abuse restriction.
- Smart reminders default to the member's private LINE chat, allow at most two deliveries per member per day, and merge reminders due in the same time slot.
- A member may select at most one core guardian for a smart reminder; that guardian receives at most one smart-reminder delivery per day. Smart reminders never deliver to guardian groups.
- LINE message usage is recorded by actual recipients and categorized by notification type.
- Do not expose access tokens, ID tokens, migration secrets, or unnecessary full LINE user IDs.
- Do not include the unrelated modified `assets/daily-peace-hero.png` in any task commit.

---

### Task 1: Server-authoritative member readiness

**Files:**
- Modify: `app.py`
- Modify: `index.html`
- Test: `tests/test_bind_and_home_gate.py`
- Test: `tests/liff_fast_route.behavior.test.mjs`

**Interfaces:**
- Consumes: `profile_has_bound_line_guardian(profile) -> bool`
- Produces: `member_access_state(profile) -> dict` with `friend_required`, `login_required`, `migration_pending`, `guardian_required`, and `home_ready`

- [ ] **Step 1: Write failing backend tests**

Add cases proving that an old onboarding flag, an emergency contact, and an unbound guardian profile each produce `guardian_required=True`, while a notifiable bound LINE guardian produces `home_ready=True`.

- [ ] **Step 2: Run the focused backend tests and verify RED**

Run: `python -m unittest tests.test_bind_and_home_gate -v`

Expected: the new cases fail because readiness still accepts stale setup/contact state.

- [ ] **Step 3: Implement minimal readiness helper and API fields**

Add one server-side helper based on `profile_has_bound_line_guardian`. Return its state from onboarding/status endpoints without trusting localStorage or `is_onboarding_completed` alone.

- [ ] **Step 4: Write and run failing frontend route test**

Add a behavior test proving that `guardian_required` always opens onboarding and prevents automatic check-in/home routing.

Run: `node --test tests/liff_fast_route.behavior.test.mjs`

Expected: FAIL because current routing uses `hasAnyGuardianOrContact` and stale setup flags.

- [ ] **Step 5: Update frontend routing minimally**

Use the backend readiness fields as the gate. Preserve invitee flows and account-migration handoff, but prevent home/check-in/SOS from bypassing required guardian setup.

- [ ] **Step 6: Verify focused tests GREEN and commit**

Run:

```bash
python -m unittest tests.test_bind_and_home_gate -v
node --test tests/liff_fast_route.behavior.test.mjs
git add app.py index.html tests/test_bind_and_home_gate.py tests/liff_fast_route.behavior.test.mjs
git commit -m "fix: require a bound core guardian before home"
```

### Task 2: Official-friend and LINE-login gate

**Files:**
- Modify: `index.html`
- Test: `tests/liff_fast_route.behavior.test.mjs`
- Test: `tests/test_product_rules.py`

**Interfaces:**
- Consumes: LIFF `getFriendship()` and `isLoggedIn()`
- Produces: `resolveLineEntryState() -> {friend, loggedIn}` and two ordered onboarding screens

- [ ] **Step 1: Write failing behavior tests**

Cover: not friend shows only add-friend action; friend but logged out shows LINE login; friend and logged in proceeds to migration/readiness; returning with `friendship_status_changed` rechecks friendship.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
node --test tests/liff_fast_route.behavior.test.mjs
python -m unittest tests.test_product_rules -v
```

Expected: FAIL because ordered friendship/login UI is absent.

- [ ] **Step 3: Implement ordered entry states**

Add accessible Traditional Chinese screens and buttons. Call `liff.getFriendship()` only after LIFF init; call `liff.login()` only from the explicit login action. Do not mark friendship complete merely because the add-friend URL was opened.

- [ ] **Step 4: Verify GREEN and commit**

Run the two focused commands above, then:

```bash
git add index.html tests/liff_fast_route.behavior.test.mjs tests/test_product_rules.py
git commit -m "feat: gate onboarding by LINE friendship and login"
```

### Task 3: Verified guardian completion and bilateral notices

**Files:**
- Modify: `app.py`
- Modify: `index.html`
- Modify: `liff/share-invite.html`
- Test: `tests/test_bind_and_home_gate.py`
- Test: `tests/test_sos_rules.py`
- Test: `tests/test_product_rules.py`

**Interfaces:**
- Consumes: `bind_emergency_contact(...)`, authenticated inviter/invitee identities, LINE push sender
- Produces: atomic reciprocal binding outcome with `owner_guardian`, `invitee_guardian`, `owner_notice`, `invitee_notice`, and retryable profile-completion reminders

- [ ] **Step 1: Write failing tests**

Prove that manual contact data cannot finish onboarding before invite consent; the recipient sees the inviter and complete guardian-purpose/privacy explanation before login; consent atomically creates reciprocal core-guardian records; either both records persist or neither does; both parties are notified; one push failure does not undo the completed reciprocal binding; a pending invite expires after seven days; incomplete profiles receive private completion reminders at bind time, 24 hours, day 3 and day 7, then stop after completion.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
python -m unittest tests.test_bind_and_home_gate tests.test_sos_rules -v
```

- [ ] **Step 3: Implement minimal verified binding transition**

Store only the inviter-provided display name/relationship before sharing. After the recipient reads the public explanation, joins the OA, logs in and consents to reciprocal guardianship, create both canonical core-guardian records in one atomic state mutation. Push separate success notices with a profile-completion CTA and append per-recipient delivery logs. LINE notification eligibility begins immediately; phone-based contact remains disabled until the person completes their own details.

- [ ] **Step 4: Update onboarding completion UI**

Show inviter prefill/share, public explanation, add-friend, login, reciprocal-consent, waiting, and completion states. Display both party names and individual notification results. Move full personal-data entry to a private LINE CTA and do not make it a prerequisite for LINE notification delivery.

- [ ] **Step 5: Verify GREEN and commit**

Run the focused suite and:

```bash
git add app.py index.html liff/share-invite.html tests/test_bind_and_home_gate.py tests/test_sos_rules.py tests/test_product_rules.py
git commit -m "feat: verify and notify core guardian binding"
```

### Task 4: Live guardian-group summary membership and schedule

**Files:**
- Modify: `app.py`
- Modify: `index.html`
- Test: `tests/test_guardian_group_join.py`
- Test: `tests/test_push_delivery_policy.py`

**Interfaces:**
- Consumes: active group ownership, current bound relationships, group preferences
- Produces: `eligible_guardian_group_summary_members(...) -> list[dict]` and `daily_summary_time` preference

- [ ] **Step 1: Write failing tests**

Cover default-off behavior, custom time deferral, once-per-day delivery, removal of unbound/deleted members, and skipping a group with no eligible member rows.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
python -m unittest tests.test_guardian_group_join tests.test_push_delivery_policy -v
```

- [ ] **Step 3: Implement live membership and time normalization**

Calculate the roster from current, authorized relationships at send time. Validate `HH:MM`, default to `21:00` only when no custom time exists, and never turn the summary on implicitly.

- [ ] **Step 4: Add member-center controls**

Add per-group enabled switch and time input with a clear save result. Keep the controls separate from SOS emergency delivery.

- [ ] **Step 5: Verify GREEN and commit**

Run the focused suite and:

```bash
git add app.py index.html tests/test_guardian_group_join.py tests/test_push_delivery_policy.py
git commit -m "fix: send group summaries only to live memberships"
```

### Task 5: Unified SOS recipients and direct route

**Files:**
- Modify: `app.py`
- Modify: `index.html`
- Modify: `liff/sos.html`
- Modify: `sos_flow.py`
- Test: `tests/test_sos_rules.py`
- Test: `tests/test_product_rules.py`
- Test: `tests/liff_fast_route.behavior.test.mjs`

**Interfaces:**
- Consumes: all notifiable bound core guardians, active owned groups, authenticated sender
- Produces: structured SOS result with `event_id`, `self`, `guardians`, `groups`, `sent`, `failed`, recipient display names, and retry-safe per-recipient delivery records

- [ ] **Step 1: Write failing backend recipient tests**

Prove all valid core guardians receive the SOS up to the plan limit, emergency contacts are excluded, active groups receive emergency SOS regardless of summary preference, stale groups are excluded, and the sender receives a confirmation push.

- [ ] **Step 2: Run backend tests and verify RED**

Run: `python -m unittest tests.test_sos_rules -v`

- [ ] **Step 3: Implement structured recipient delivery**

Build recipient lists immediately before sending, deliver independently, audit every attempt, and return safe display names/counts without full IDs.

- [ ] **Step 4: Write failing direct-route and three-tap tests**

Prove `open=sos` renders the SOS overlay before home content, both entry points share the same handler, and each tap visibly advances from 1/3 through 3/3. Also prove Rich Menu, home and chat check-in entrances do not create a check-in without a bound core guardian; they show the required-guardian message and invite/explanation actions instead.

- [ ] **Step 5: Run frontend/product tests and verify RED**

Run:

```bash
node --test tests/liff_fast_route.behavior.test.mjs
python -m unittest tests.test_product_rules -v
```

- [ ] **Step 6: Implement direct overlay and result UI**

Do not call `showTab("home")` before opening SOS. Render guardian/group names, sender confirmation, success/failure counts and actionable failure hints. Reuse the authoritative readiness gate for all check-in entrances; “later” may close the prompt but never write a check-in, and post-binding completion offers an explicit check-in action.

- [ ] **Step 7: Write failing false-alarm and abuse-policy tests**

Add cases proving:

- cancelling an SOS notifies only recipients whose original delivery succeeded;
- cancellation never deletes the original event;
- two false alarms in 24 hours create a three-day observation state;
- an observed member must use the long-confirm/reason flow;
- repeated abuse inside seven days restricts normal fan-out for seven days;
- a restricted member still sees 110/119 and may notify exactly one primary core guardian;
- retry sends only to failed original recipients and does not duplicate successful deliveries.

Run:

```bash
python -m unittest tests.test_sos_rules -v
node --test tests/liff_fast_route.behavior.test.mjs
```

Expected: FAIL because cancellation events, observation state, abuse restriction and emergency fallback are not implemented.

- [ ] **Step 8: Implement false-alarm cancellation and graded abuse controls**

Add pure policy helpers:

```python
def sos_abuse_state(profile: dict, now: datetime) -> dict:
    """Return mode: normal | observation | restricted plus expiry and reason."""

def cancel_sos_event(state: dict, actor_line_user_id: str, event_id: str, now: datetime) -> dict:
    """Append cancellation and deliver only to successful original recipients."""

def eligible_sos_retry_recipients(event: dict) -> list[dict]:
    """Return failed recipients only."""
```

Persist observation/restriction expiry, false-alarm timestamps and the audit reason. Do not use humiliating copy such as「亂按」. During restriction return the 110/119 actions and one primary-core-guardian fallback instead of claiming that normal fan-out occurred.

- [ ] **Step 9: Verify GREEN and commit**

Run all three focused suites and:

```bash
git add app.py index.html liff/sos.html sos_flow.py tests/test_sos_rules.py tests/test_product_rules.py tests/liff_fast_route.behavior.test.mjs
git commit -m "fix: unify and protect SOS delivery"
```

### Task 6: Smart-reminder recovery state and mobile form

**Files:**
- Modify: `app.py`
- Modify: `index.html`
- Test: `tests/test_checkin_postback_and_smart.py`
- Test: `tests/test_product_rules.py`

**Interfaces:**
- Consumes: verified plan entitlement and account-migration status
- Produces: smart-reminder UI state `entitled | recovering | upgrade_required`, `smart_reminder_daily_usage(...)`, and an optional single bound-core-guardian target

- [ ] **Step 1: Write failing tests**

Cover: 799 displays all inputs; migration pending displays recovery copy instead of upgrade; non-799 displays upgrade copy; modal save button remains reachable on a short mobile viewport; private delivery is the default; only one currently bound core guardian can be selected; unbound/stale IDs are rejected; same-slot reminders merge; private delivery is capped at two per member per day; the selected guardian is capped at one smart-reminder delivery per day; guardian-group targeting is rejected.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
python -m unittest tests.test_checkin_postback_and_smart tests.test_product_rules -v
```

- [ ] **Step 3: Implement explicit UI state**

Return migration/entitlement state from the API, keep the form markup intact, and distinguish recovery from a real plan restriction. Adjust modal layout so fields and save remain reachable. Add the explicit target choices「只通知自己（預設）」and「通知一位核心守護人」using server-provided bound guardians only. Add a visible `今日智慧提醒已使用 X／2 則` counter, merge reminders due in the same slot into one LINE push, enforce the two/private and one/guardian daily limits server-side, and reject every guardian-group target.

- [ ] **Step 4: Verify GREEN and commit**

Run the focused suite and:

```bash
git add app.py index.html tests/test_checkin_postback_and_smart.py tests/test_product_rules.py
git commit -m "fix: restore smart reminder recovery experience"
```

### Task 7: LINE message-cost ledger and member-facing policy pages

**Files:**
- Modify: `app.py`
- Modify: `admin.html`
- Modify: `help.html`
- Modify: `pricing.html`
- Modify: `index.html`
- Test: `tests/test_push_delivery_policy.py`
- Test: `tests/test_admin_observability.py`
- Test: `tests/test_product_rules.py`

**Interfaces:**
- Consumes: notification delivery logs from binding, check-in, overdue, SOS, SOS cancellation, smart reminders and guardian summaries
- Produces: `record_line_message_usage(...)`, monthly usage aggregation, 70%/90% alerts and member-facing policy copy

- [ ] **Step 1: Write failing usage-ledger tests**

Cover actual-recipient counting, group member counts, failed/non-delivered exclusions, category totals, per-member totals, false-alarm cost, month filtering, projected month-end usage and 70%/90% thresholds.

Run:

```bash
python -m unittest tests.test_push_delivery_policy tests.test_admin_observability -v
```

Expected: FAIL because the normalized message-cost ledger and dashboard aggregate do not exist.

- [ ] **Step 2: Implement normalized usage recording**

Add:

```python
def record_line_message_usage(
    state: dict,
    *,
    category: str,
    owner_line_user_id: str,
    recipient_count: int,
    event_id: str,
    sent_at: datetime,
) -> dict:
    """Idempotently record delivered recipient-count units."""

def monthly_line_message_usage(state: dict, year_month: str, quota: int, now: datetime) -> dict:
    """Return totals, category/member breakdown, projection and alert level."""
```

Use categories `binding`, `checkin`, `overdue`, `sos`, `sos_cancel`, `smart_reminder`, and `guardian_summary`. Never store access tokens or expose full LINE IDs in dashboard responses.

- [ ] **Step 3: Add admin cost and abuse views**

Show monthly used units, projected month-end units, category share, highest-usage members, false-alarm units and active observation/restriction cases. Show warnings at 70% and 90%, with SOS prioritized over smart reminders and daily summaries.

- [ ] **Step 4: Write failing member-copy and navigation tests**

Require `help.html`, `pricing.html` and the member center to explain:

- correct SOS use, three taps, false-alarm cancellation, cooldown, daily limit and graded restrictions;
- 110/119 and primary-guardian fallback during restriction;
- private/core-guardian/group notification differences;
- smart-reminder two-per-day merging and no guardian-group delivery;
- direct plan lookup without returning to home, preserving the member's return route.

Run:

```bash
python -m unittest tests.test_product_rules -v
```

Expected: FAIL until all pages and direct navigation are synchronized.

- [ ] **Step 5: Implement member help, FAQ and plan comparison**

Use senior-readable Traditional Chinese, keep product rules identical across pages, and ensure the basic SOS capability is not removed by plan tier. Add direct member-center links to FAQ and full plan comparison while preserving the safe return route.

- [ ] **Step 6: Verify GREEN and commit**

Run:

```bash
python -m unittest tests.test_push_delivery_policy tests.test_admin_observability tests.test_product_rules -v
git diff --check
git add app.py admin.html help.html pricing.html index.html tests/test_push_delivery_policy.py tests/test_admin_observability.py tests/test_product_rules.py
git commit -m "feat: track LINE message cost and explain notification rules"
```

### Task 8: Full verification, review and deployment gate

**Files:**
- Modify: `.superpowers/sdd/2026-07-26-secure-account-migration/progress.md`
- Modify: `HANDOFF.md` if release configuration changes

**Interfaces:**
- Consumes: Tasks 1–6
- Produces: reviewable branch with evidence; no deployment until every gate passes

- [ ] **Step 1: Run complete automated suites**

Run:

```bash
python -m unittest discover -s tests -v
node --test tests/*.test.mjs
python -m unittest tests.test_product_rules -v
python -m py_compile app.py sos_flow.py
git diff --check
```

- [ ] **Step 2: Run security and secret scan**

Search changed files for tokens, secrets, complete LINE IDs, debug endpoints, unverified identity use and unsafe redirect/query persistence. Resolve every Critical or Important finding with a new failing regression test.

- [ ] **Step 3: Perform independent code review**

Review the complete branch diff against the design, focusing on identity, authorization, stale membership, duplicate notifications, atomic writes and frontend route races.

- [ ] **Step 4: Verify production prerequisites read-only**

Check `/health`, durable PostgreSQL mode, required Render variables, LIFF ID alignment, Messaging API token availability and Rich Menu URI. Do not mutate production data.

- [ ] **Step 5: Execute two-account LINE staging**

Test member and guardian accounts through friend check, login, migration, invite consent, contact completion, bilateral notices, check-in, summary off/on, SOS triple-tap and notification results.

- [ ] **Step 6: Update evidence and publish only after approval**

Commit the test/review evidence, create a draft PR, wait for green checks, merge, deploy, then repeat smoke tests on the deployed commit.
