# Holiday Card Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare a holiday background one day before each known Taiwan holiday and automatically use the special full-card visual on the holiday.

**Architecture:** Extend `holidays_tw.py` with next-day holiday lookup and a stable holiday asset key. Add atomic holiday-asset preparation in `app.py`, invoked by the existing cron tick. `build_daily_checkin_flex` selects the prepared holiday background while retaining dynamic member text and real LINE actions.

**Tech Stack:** Python, Flask, LINE Flex Messages, existing JSON atomic state store, unittest.

## Global Constraints

- Holiday preparation runs one calendar day before the holiday in Asia/Taipei.
- Preparation is idempotent and records status, prompt, URL, and timestamps.
- Holiday-day cards use a portrait 4:5 hero with `aspectMode: fit` and four functional buttons.
- Name, level, streak, blessing, and buttons remain dynamic; generated backgrounds contain no text, Logo, or UI.
- If generation is unavailable, cron records a Chinese failure and ordinary reminders continue safely.

---

### Task 1: Holiday date lookup

**Files:**
- Modify: `holidays_tw.py`
- Test: `tests/test_holiday_card_automation.py`

**Interfaces:**
- Produces: `holiday_on_next_day(day) -> dict | None`

- [ ] Write a failing test proving 2026-08-07 resolves to the 2026-08-08 Father's Day holiday.
- [ ] Run the focused test and verify the expected missing-function failure.
- [ ] Implement next-day lookup using `holiday_for(day + timedelta(days=1))`.
- [ ] Run the focused test and verify it passes.

### Task 2: Idempotent one-day-ahead preparation

**Files:**
- Modify: `app.py`
- Test: `tests/test_holiday_card_automation.py`

**Interfaces:**
- Produces: `prepare_tomorrow_holiday_card(config, now=None) -> (dict, int)`
- Stores: `state["holiday_card_assets"]["YYYY-MM-DD"]`

- [ ] Write failing tests for generation on August 7, idempotent second execution, and safe missing-key failure.
- [ ] Run the focused tests and verify failures are caused by missing preparation behavior.
- [ ] Implement atomic claim, generator call, success/failure persistence, and retry-safe status.
- [ ] Run the focused tests and verify they pass.

### Task 3: Holiday full-card selection

**Files:**
- Modify: `app.py`
- Test: `tests/test_holiday_card_automation.py`

**Interfaces:**
- `build_daily_checkin_flex(now, target_time="", profile=None, holiday_asset_url="")`
- `holiday_asset_url_for_date(state, day) -> str`

- [ ] Write a failing test proving a prepared Father's Day asset becomes a 4:5 `fit` hero while all four LINE actions remain present.
- [ ] Run the focused test and verify the old ordinary hero is selected.
- [ ] Implement holiday asset selection and pass the selected URL from all reminder send paths.
- [ ] Run focused and existing daily-card tests.

### Task 4: Cron integration and regression verification

**Files:**
- Modify: `app.py`
- Test: `tests/test_holiday_card_automation.py`, `tests/test_scheduler_tick.py`

**Interfaces:**
- Adds `holiday_card_preparation` to `run_cron_tick` task results.

- [ ] Write a failing cron test proving August 7 invokes preparation once.
- [ ] Run the test and confirm expected failure.
- [ ] Add preparation to the existing cron task map.
- [ ] Run holiday, daily push, scheduler, and personalized-card tests.
- [ ] Run Python syntax compilation and the relevant regression suite.
- [ ] Commit, push `main`, and verify the deployment build before reporting completion.
