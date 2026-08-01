# 21 天封測帳號完整重置 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在會員管理提供最高管理員專用、可原子歸零並重新加入正確 21 天封測流程的帳號重置功能，同時阻止一般入口誤開 14 天體驗及舊快取誤顯示。

**Architecture:** 沿用 `app.py` 的單一狀態與 `mutate_state_atomically`，建立候選判定、最小會員殼層及完整重置服務，專用候選 API 與既有會員列共用同一重置 API。前端以 `account_state_version` 驗證快取；後台以候選版本做樂觀鎖與明確確認。

**Tech Stack:** Python 3、Flask/MiniApp、JSON/PostgreSQL 原子狀態、原生 HTML/JavaScript、Python `unittest`、Node.js `node:test`。

## Global Constraints

- 只有 `super_admin` 且具 `member.manage` 權限者可執行。
- LINE UID 必須在 `TEST_LINE_USER_IDS`，後端寫入時重新驗證候選資格。
- 重置保留 LINE UID、付款訂單、退款／交易、既有稽核與法務資料；不得觸發退款、請款或續訂。
- 實際會員資料變更必須在單一 `mutate_state_atomically` 內完成；失敗不得留下成功稽核。
- 完整重置後 `beta_reset_pending=true`、提醒關閉、提醒時間空陣列；一般入口不得啟用 14 天體驗。
- 正式部署後只做唯讀驗證，不實際重置 Jenni 或其他正式帳號。

---

### Task 1: 候選資格、墓碑與原子重置服務

**Files:**
- Modify: `app.py`
- Test: `tests/test_beta_account_full_reset.py`

**Interfaces:**
- Produces: `list_beta_reset_candidates(state, allowed_test_user_ids) -> list[dict]`
- Produces: `admin_reset_test_account(data_file, line_user_id, allowed_test_user_ids, *, expected_version, actor) -> tuple[dict, int]`

- [ ] **Step 1: Write failing tests** covering whitelist/cohort/tombstone/legacy-recreated candidates, paid-member exclusion, UID/order/audit preservation, reverse/global cleanup, empty disabled reminders, new version, pending state, immutable success audit, version conflict and atomic save failure.
- [ ] **Step 2: Run `python -m unittest tests.test_beta_account_full_reset -v`** and confirm failures are caused by missing full-reset behavior.
- [ ] **Step 3: Implement minimal candidate and reset services** using a minimal shell, `test_account_tombstones`, strict eligible states and one atomic mutation.
- [ ] **Step 4: Run `python -m unittest tests.test_beta_account_full_reset -v`** and confirm all Task 1 tests pass.
- [ ] **Step 5: Commit** with `feat: add atomic beta account reset service`.

### Task 2: 最高管理員 API、版本鎖與重新封測入口

**Files:**
- Modify: `app.py`
- Test: `tests/test_beta_account_reset_api.py`

**Interfaces:**
- Consumes: `list_beta_reset_candidates`, `admin_reset_test_account`
- Produces: `GET /api/admin/beta-reset-candidates`
- Produces: upgraded `POST /api/admin/test-accounts/<line_user_id>/reset`

- [ ] **Step 1: Write failing route and registration tests** for 401/403/404/409 contracts, confirmation/version requirements, safe candidate payload, general-entry no-trial behavior, B399/B799 21-day reactivation and A-group conflict.
- [ ] **Step 2: Run `python -m unittest tests.test_beta_account_reset_api -v`** and verify expected failures.
- [ ] **Step 3: Implement routes and pending-aware registration**; clear pending only after valid beta assignment and never construct default reminders for the pending shell.
- [ ] **Step 4: Run Task 2 plus existing reset/onboarding tests** with `python -m unittest tests.test_beta_account_reset_api tests.test_admin_reset_test_account tests.test_bind_and_home_gate -v`.
- [ ] **Step 5: Commit** with `feat: protect beta reset and re-enrollment APIs`.

### Task 3: 首頁權威狀態與版本化快取

**Files:**
- Modify: `app.py`
- Modify: `index.html`
- Test: `tests/beta_account_cache.behavior.test.mjs`
- Test: `tests/test_beta_account_reset_api.py`

**Interfaces:**
- Consumes: status `account_state_version`
- Produces: versioned plan-only cache and `clearAccountStateCache(lineUserId)` behavior.

- [ ] **Step 1: Write failing Node tests** proving cached check-in/reminder is never rendered before server confirmation, version mismatch clears member/check-in/guardian flags, and network failure shows verification error rather than old status.
- [ ] **Step 2: Run `node --test tests/beta_account_cache.behavior.test.mjs`** and verify failure.
- [ ] **Step 3: Return account version from status and update cache logic** to cache only plan summary before confirmation and invalidate all account-state keys on version mismatch.
- [ ] **Step 4: Run Node cache tests and existing fast-route tests**; record unrelated baseline failures separately.
- [ ] **Step 5: Commit** with `fix: invalidate stale member state after beta reset`.

### Task 4: 會員管理專用重置介面

**Files:**
- Modify: `admin.html`
- Test: `tests/admin_beta_account_reset.behavior.test.mjs`

**Interfaces:**
- Consumes: candidate GET and reset POST APIs.
- Produces: `重置 21 天封測帳號` panel, candidate selector, confirmation, loading and success states.

- [ ] **Step 1: Write failing behavior tests** for panel copy, role-disabled controls, empty state, masked candidate option, version in POST, one active request, success refresh and differentiated permanent-delete copy.
- [ ] **Step 2: Run `node --test tests/admin_beta_account_reset.behavior.test.mjs`** and verify failure.
- [ ] **Step 3: Implement the panel and reuse one reset function** for both selector and member-row entry; send `confirm: true` and `account_state_version`.
- [ ] **Step 4: Run new admin tests plus existing admin reset UI tests**.
- [ ] **Step 5: Commit** with `feat: add beta account reset panel`.

### Task 5: 完整驗證與安全部署

**Files:**
- Modify only if verification exposes a regression in this feature.

- [ ] **Step 1: Run targeted Python tests** for Tasks 1–3 and existing account reset/beta registration behavior.
- [ ] **Step 2: Run targeted Node tests** for Tasks 3–4 and existing admin/member fast-route behavior.
- [ ] **Step 3: Run `python -m py_compile app.py` and JavaScript syntax/behavior checks**.
- [ ] **Step 4: Run the full offline suite** and compare failures to the recorded baseline of 793 tests / 133 failures / 24 errors; do not attribute pre-existing failures to this feature.
- [ ] **Step 5: Review `git diff`, confirm no payment/order/audit deletion and no production reset call, then commit any verification-only correction.**
- [ ] **Step 6: Push the feature branch and deploy through the repository's existing deployment path.**
- [ ] **Step 7: Perform read-only production checks** for health, public page load and admin panel presence; do not submit the reset POST endpoint.
