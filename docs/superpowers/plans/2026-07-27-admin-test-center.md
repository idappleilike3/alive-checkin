# Admin Test Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a safe admin test center for LINE lifecycle messages and external integration checks.

**Architecture:** Add focused test-center helpers and authenticated JSON routes to the existing Flask application, then add one responsive section to the existing admin page. Test executions use an explicit environment whitelist and append sanitized audit records to state without mutating plans, billing, or production push quotas.

**Tech Stack:** Python, Flask, JSON state storage, vanilla HTML/CSS/JavaScript, unittest.

## Global Constraints

- Only `TEST_LINE_USER_IDS` recipients may receive test messages.
- POST actions require admin session and CSRF.
- Test actions never charge, change membership, or consume production quota.
- All results are visibly marked as test mode and audited without secrets.

---

### Task 1: Test-center API and safety boundary

**Files:**
- Modify: `app.py`
- Create: `tests/test_admin_test_center.py`

**Interfaces:**
- Produces: `admin_test_center_status(data_file, config)` and `run_admin_test(data_file, config, payload)`.

- [ ] Write failing tests for authentication, CSRF, recipient whitelist, safe simulation, LINE test delivery, integration status, and sanitized audit history.
- [ ] Run `python -m unittest tests.test_admin_test_center -v` and verify failures describe missing routes.
- [ ] Implement minimal helpers and `GET /api/admin/test-center`, `POST /api/admin/test-center/run`.
- [ ] Re-run the focused tests and verify all pass.

### Task 2: Admin test-center user interface

**Files:**
- Modify: `admin.html`
- Create: `tests/test_admin_test_center_ui.py`

**Interfaces:**
- Consumes: the two JSON endpoints from Task 1.

- [ ] Write failing UI source tests for test-account selection, integration status, ten test actions, confirmation, and audit results.
- [ ] Run `python -m unittest tests.test_admin_test_center_ui -v` and verify expected failures.
- [ ] Add the responsive test-center section and JavaScript handlers using `adminFetch`.
- [ ] Re-run focused UI tests and verify all pass.

### Task 3: Full verification and release safety

**Files:**
- Modify only files required by failed regressions attributable to this feature.

- [ ] Run the complete Python and JavaScript test suites.
- [ ] Inspect `git diff --check`, `git status`, and the exact changed-file list.
- [ ] Verify the existing permanent-retention changes remain intact and do not mix unrelated files.
- [ ] Publish only after all automated tests pass, then verify `/health`, `/admin`, and authenticated test-center API behavior on the deployed site.
