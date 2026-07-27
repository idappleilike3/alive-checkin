# SOS Response Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a single shared SOS lifecycle across LINE guardian actions, the member-facing SOS page, automatic escalation, and the protected admin incident center.

**Architecture:** Store response state and an append-only timeline inside each existing `sos_events[event_id]`. Add authenticated member/guardian APIs around one transition function, use LINE postbacks for guardian actions, let the five-minute cron send escalation rounds, and render the same event snapshot in both front and admin UIs.

**Tech Stack:** Python 3.11, Flask, LINE Messaging API, JSON/SQLite/Postgres-backed state adapter, vanilla JavaScript, `unittest`, Node behavior tests.

## Global Constraints

- First guardian choosing `take_over` becomes primary responder; later responders are assistants.
- Any `take_over`, `assist`, or `contacted` response stops all further automatic escalation.
- `contacted` means contact was made and does not close the SOS.
- Only the owner safety confirmation or an authorized administrator closes the SOS.
- Delivery success is not LINE read status and must never be labeled as read.
- Reminder rounds are SOS cost events and do not consume normal member reminder quota.
- Existing cancel, retry, abuse, targeting, and emergency-number behavior must remain compatible.

---

### Task 1: SOS lifecycle domain and APIs

**Files:**
- Modify: `app.py`
- Test: `tests/test_sos_response_workflow.py`

**Interfaces:**
- Produces: `respond_to_sos_event(data_file, payload, config=None) -> (dict, int)`
- Produces: `get_sos_event_status(data_file, requester_id, event_id) -> (dict, int)`
- Produces: `close_sos_as_safe(data_file, payload, config=None) -> (dict, int)`

- [ ] Write failing tests for first-responder ownership, assistant response, contacted state, authorization, and owner-only safety closure.
- [ ] Run `python -m unittest tests.test_sos_response_workflow -v` and confirm the new tests fail because the interfaces are absent.
- [ ] Implement minimal atomic lifecycle transitions, event timeline entries, and authenticated Flask routes.
- [ ] Run the focused tests and existing `tests.test_sos_rules`.

### Task 2: LINE response buttons and escalation

**Files:**
- Modify: `app.py`
- Test: `tests/test_sos_response_workflow.py`
- Test: `tests/test_scheduler_tick.py`

**Interfaces:**
- Consumes: `respond_to_sos_event`
- Produces: guardian LINE message actions `sos:take_over:<event_id>`, `sos:assist:<event_id>`, `sos:contacted:<event_id>`, `sos:unable:<event_id>`
- Produces: `process_sos_escalations(data_file, config=None, now=None) -> dict`

- [ ] Write failing tests that delivered guardian messages contain response actions and cron sends the 3-minute reminder, 5-minute backup round, and 10-minute final warning only when nobody has responded.
- [ ] Run focused tests and confirm failures are caused by missing actions/escalation.
- [ ] Add LINE Flex/postback handling and idempotent escalation ledgers counted as SOS message usage.
- [ ] Run focused tests and scheduler regression tests.

### Task 3: Member-facing live SOS status

**Files:**
- Modify: `index.html`
- Test: `tests/sos_response_ui.behavior.test.mjs`
- Test: `tests/test_product_rules.py`

**Interfaces:**
- Consumes: `GET /api/sos/status?event_id=...`
- Consumes: `POST /api/sos/safe`

- [ ] Write failing DOM/source behavior tests for delivered recipients, primary responder, assistants, contacted status, unresponsive warning, refresh, cancel, and safe closure.
- [ ] Run `node --test tests/sos_response_ui.behavior.test.mjs` and confirm failure.
- [ ] Add an accessible live-status panel to the existing SOS modal and poll only while an event is open.
- [ ] Run UI behavior and product-rule tests.

### Task 4: Admin incident detail and verification

**Files:**
- Modify: `app.py`
- Modify: `admin.html`
- Test: `tests/test_admin_business_dashboard.py`
- Test: `tests/admin_sos_response_ui.test.mjs`

**Interfaces:**
- Consumes: event response snapshot and timeline from `admin_business_dashboard`

- [ ] Write failing tests for responder, response state, reminder rounds, delivery counts, and timeline rendering.
- [ ] Run focused tests and confirm failures.
- [ ] Extend protected admin payload and incident cards without exposing full LINE IDs.
- [ ] Run all Python and Node tests, inspect `git diff --check`, and only then prepare the GitHub branch/PR for deployment.
