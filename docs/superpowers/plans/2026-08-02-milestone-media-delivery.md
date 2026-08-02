# Milestone Media Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect milestone Flex cards, web celebration animations, and retry-safe day 100/365 MP4 delivery to the production cron.

**Architecture:** Daily Flex rendering exposes milestone metadata and links to the existing member page with a milestone query parameter. A dedicated cron task scans members for day 100/365, sends the configured LINE video only to the member, and records completion only after the sender returns success; failures remain eligible for the next cron tick.

**Tech Stack:** Python 3.11, Flask, LINE Messaging API message objects, JSON/Postgres-backed state, vanilla HTML/CSS/JavaScript, unittest.

## Global Constraints

- Milestone card days are 1, 7, 30, 60, 100, 180, and 365.
- MP4 is sent only on day 100 and day 365, only to the member, never to guardians.
- A successful MP4 delivery is permanently deduplicated by member UID and milestone day.
- A failed MP4 delivery is not marked complete and is retried by a later cron tick.
- General daily Flex reminders and their four real buttons remain intact.

---

### Task 1: Milestone Flex metadata and animation entry

**Files:**
- Modify: `daily_care.py`
- Modify: `app.py`
- Modify: `index.html`
- Test: `tests/test_daily_care_card.py`

**Interfaces:**
- Produces: `build_daily_care_context(...)["milestone_day"]` and `achievement_url`.
- Consumes: `profile["streak_days"]`.

- [ ] Write tests for all milestone days, the achievement button URI, and ordinary-day compatibility.
- [ ] Run the focused tests and confirm they fail because milestone metadata is missing.
- [ ] Add milestone metadata, Flex button routing, and a query-driven web celebration overlay.
- [ ] Run focused tests and confirm they pass.

### Task 2: Retry-safe day 100/365 MP4 cron delivery

**Files:**
- Modify: `app.py`
- Modify: `render.yaml`
- Test: `tests/test_milestone_media_delivery.py`

**Interfaces:**
- Produces: `send_due_streak_milestone_videos(config) -> (dict, int)`.
- Consumes: `MILESTONE_VIDEO_100_URL`, `MILESTONE_VIDEO_365_URL`, `LINE_PUSH_SENDER`.

- [ ] Write tests proving successful permanent dedupe, failed retry, missing URL skip, and member-only targeting.
- [ ] Run the focused tests and confirm they fail because the cron task does not exist.
- [ ] Implement LINE video messages, success ledger, failure logging, and cron wiring.
- [ ] Run focused and regression tests.

### Task 3: Publish verification

**Files:**
- Verify all changed files only.

- [ ] Run Python compilation and the complete relevant test suite.
- [ ] Inspect the exact diff and confirm no unrelated welcome/member-page changes.
- [ ] Commit, push the isolated branch, create and merge a protected PR to `main`.
- [ ] Confirm the production health endpoint and deployed source/assets.
