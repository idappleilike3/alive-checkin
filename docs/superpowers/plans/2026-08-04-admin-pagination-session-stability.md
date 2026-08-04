# Admin Pagination and Session Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show push-delivery and member records in 20-row pages with expandable page numbers, while preventing stale admin requests from switching a newly authenticated dashboard back to the login screen.

**Architecture:** Keep push-delivery pagination server-backed through the existing `offset`, `limit`, and `total` API fields. Keep member pagination client-side because `/api/admin/summary` already returns the complete authoritative member list used by other admin controls. Guard every admin request with the authentication generation that existed when it started so an older 401 response cannot override a newer successful login.

**Tech Stack:** Flask/Python, vanilla JavaScript in `admin.html`, Node test runner, Python `unittest`.

## Global Constraints

- Each page contains exactly 20 records except the final page.
- Page controls include previous, numbered pages, and next; page numbers extend with the record count.
- Filtering push records resets to page 1.
- Existing member actions, push filters, B799 state, and admin role permissions remain unchanged.
- Only a current-session 401 may show the login panel.

---

### Task 1: Lock the desired behavior with failing tests

**Files:**
- Create: `tests/admin_pagination_session.behavior.test.mjs`
- Modify: `tests/test_admin_session_auth.py`

- [ ] Add source-level and behavior assertions for 20-row member pagination, server-backed push pagination, page controls, filter reset, and stale-401 suppression.
- [ ] Run the focused Node and Python tests and confirm they fail for missing pagination and stale-request handling.

### Task 2: Implement reusable admin pagination

**Files:**
- Modify: `admin.html`

- [ ] Add pagination containers below the member and push-delivery tables.
- [ ] Add a compact numbered-page renderer with previous/next controls and an accessible record summary.
- [ ] Render members from the current 20-row slice while retaining the full member list for selectors.
- [ ] Request push deliveries with `limit=20` and the selected page offset; render controls from the API `total`.
- [ ] Reset push pagination to page 1 whenever filters are submitted.

### Task 3: Stabilize admin authentication transitions

**Files:**
- Modify: `admin.html`

- [ ] Capture `adminAuthGeneration` when each `adminFetch` begins.
- [ ] Ignore a 401 from a request whose generation is older than the current authenticated generation.
- [ ] Preserve the selected `?page=` route while showing login and restoring the dashboard.

### Task 4: Verify and prepare deployment

**Files:**
- Test: `tests/admin_pagination_session.behavior.test.mjs`
- Test: `tests/admin_auth_ui.test.mjs`
- Test: `tests/admin_push_management.behavior.test.mjs`
- Test: `tests/test_admin_session_auth.py`

- [ ] Run focused tests, full relevant admin tests, and JavaScript/Python syntax checks.
- [ ] Review the diff against `origin/main` for unrelated changes.
- [ ] Commit the verified change as one deployment-ready commit.
