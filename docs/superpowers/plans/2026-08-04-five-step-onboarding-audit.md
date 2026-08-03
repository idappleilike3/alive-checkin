# Five-Step Onboarding Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist and expose one authoritative five-step onboarding timeline for every plan and use it to drive non-repetitive LINE reminders.

**Architecture:** Keep the existing user, guardian invite, and notification ledgers as sources of truth. Add a bounded onboarding event ledger and derive each member's five-step snapshot from persisted profile, reminder, invite, and binding facts; admin pages consume that snapshot rather than maintaining a second workflow database.

**Tech Stack:** Python standard library HTTP application, JSON/PostgreSQL-backed state persistence, vanilla JavaScript admin UI, unittest/Node behavior tests.

## Global Constraints

- The canonical flow has exactly five steps: join official LINE, verify LINE identity, save profile and reminder settings, send guardian invite, guardian accepts and binding succeeds.
- 14-day trial and 21-day beta entitlements do not start merely from opening a page; paid plans start from confirmed payment.
- Completed steps are never prompted again.
- All push attempts retain type, content, timestamp, outcome, and Chinese failure explanation.
- Reuse one progress record across 14-day trial, B399/B799 beta, paid 199/399/799, and one-click sharing.

---

### Task 1: Authoritative five-step snapshot and event ledger

**Files:**
- Modify: `app.py`
- Test: `tests/test_five_step_onboarding_audit.py`

**Interfaces:**
- Produces: `onboarding_progress_snapshot(state, profile, now=None) -> dict`
- Produces: `append_onboarding_event(state, line_user_id, event, *, source_page, occurred_at=None, metadata=None) -> dict`

- [ ] Write tests proving all five states and bounded, idempotent event persistence.
- [ ] Run the focused tests and verify they fail because the interfaces do not exist.
- [ ] Implement the smallest derivation and append helpers.
- [ ] Run focused tests and verify they pass.

### Task 2: Record mutations at the actual completion boundaries

**Files:**
- Modify: `app.py`
- Test: `tests/test_five_step_onboarding_audit.py`

**Interfaces:**
- Consumes: Task 1 helpers.
- Produces: persisted events for LINE registration, profile/reminder save, invite creation, and invite acceptance/binding.

- [ ] Add failing endpoint-level tests for each completion boundary.
- [ ] Run tests and confirm the missing events fail.
- [ ] Append events inside the same saved state mutation as each business action.
- [ ] Run focused tests and confirm all boundary events pass.

### Task 3: Admin member progress table

**Files:**
- Modify: `app.py`
- Modify: `admin.html`
- Test: `tests/test_admin_five_step_onboarding.py`
- Test: `tests/admin_five_step_onboarding.behavior.test.mjs`

**Interfaces:**
- Consumes: `onboarding_progress_snapshot`.
- Produces: `user.onboarding_progress` in `/api/admin/summary` and a visible progress/timeline table cell.

- [ ] Write failing API and markup behavior tests.
- [ ] Run them and verify expected failures.
- [ ] Add snapshot to admin users and render current step, completion times, invitee, and latest workflow push.
- [ ] Run focused tests and confirm they pass.

### Task 4: State-driven, low-frequency onboarding reminders

**Files:**
- Modify: `app.py`
- Test: `tests/test_five_step_onboarding_reminders.py`

**Interfaces:**
- Consumes: `onboarding_progress_snapshot` and notification ledger.
- Produces: reminders for step 3 on days 1/3/5/7, step 4 on days 1/3/7 after profile completion, and step 5 on days 2/5/9 after invite.

- [ ] Write failing tests for due days, deduplication, stopping after completion, and excluding normal check-in before binding.
- [ ] Run tests and verify failures.
- [ ] Implement scheduler action and persistent delivery keys.
- [ ] Run focused tests and confirm they pass.

### Task 5: Regression verification

**Files:**
- Test: existing Python and Node onboarding/admin suites.

- [ ] Run focused Python onboarding, invitation, admin, membership, and scheduler suites.
- [ ] Run focused Node onboarding/admin behavior suites.
- [ ] Run syntax checks and inspect `git diff --check`.
- [ ] Report actual verified results and any remaining deployment step.
