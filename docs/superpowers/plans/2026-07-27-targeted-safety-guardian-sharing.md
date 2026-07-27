# Targeted Safety Guardian Sharing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let members choose one, multiple, or all bound core guardians for a timed safety-location share, with duration choices enforced by plan.

**Architecture:** The server remains authoritative for eligible durations and guardian targets. The LIFF page renders only bound core guardians, submits selected LINE user IDs with the location start request, and the notification service filters against the server-side contact list before sending.

**Tech Stack:** Python/Flask, JSON persistence, vanilla HTML/CSS/JavaScript, unittest, Node behavior tests.

## Global Constraints

- 199: 15 minutes only.
- 399: 1 or 3 hours.
- 799: 1, 3, 6, or 8 hours.
- All plans can choose one, multiple, or all bound core guardians.
- Never accept a guardian ID that is not an eligible bound core guardian.
- Timed expiry remains server controlled.

---

### Task 1: Server-side duration and target validation

**Files:**
- Modify: `app.py`
- Test: `tests/test_safety_guard.py`

**Interfaces:**
- Consumes: `update_location(data_file, payload, config)`
- Produces: validated `guardian_line_user_ids` targeting and decimal-hour duration support.

- [ ] Write failing tests for 15-minute entitlement and selected-target filtering.
- [ ] Run the tests and confirm failures are caused by missing behavior.
- [ ] Implement minimal duration parsing, target validation, persistence, and notification filtering.
- [ ] Run safety-guard tests and confirm they pass.

### Task 2: LIFF duration and guardian picker

**Files:**
- Modify: `index.html`
- Test: `tests/safety_guard_targeting.behavior.test.mjs`

**Interfaces:**
- Consumes: status `contacts`, `safety_guard_hours`.
- Produces: `guardian_line_user_ids` in the start-location API payload.

- [ ] Write failing UI behavior tests for duration labels and one/many/all target payloads.
- [ ] Run the tests and confirm failures are caused by missing controls.
- [ ] Add accessible target-mode controls and bound-core-guardian checkboxes.
- [ ] Submit selected targets and render notified names/count.
- [ ] Run targeted and existing continuous-location behavior tests.

### Task 3: Verification and publish

**Files:**
- Modify: `docs/superpowers/plans/2026-07-27-targeted-safety-guardian-sharing.md`

**Interfaces:**
- Consumes: completed server and LIFF behavior.
- Produces: verified GitHub branch and deployable pull request.

- [ ] Run focused Python and Node test suites.
- [ ] Run the broader relevant regression suite.
- [ ] Review the diff for unrelated changes and secrets.
- [ ] Commit, push, and open a pull request.
