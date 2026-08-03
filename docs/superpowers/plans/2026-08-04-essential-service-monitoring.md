# 必要服務費用監控 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在既有財務後台加入必要服務、到期風險、費用與付款連結監控，在管理員會員頁顯示到期警示，並預先登記 Render PostgreSQL 待加值項目。

**Architecture:** 在 `finance_admin.py` 的 `finance` 狀態內新增獨立 `essential_services` 集合，不把待付款預算混入既有 `expenses`。既有財務 dashboard API 一併回傳服務摘要，新增受 `finance.manage` 保護的建立與更新 API，`admin.html` 在同一獨立財務頁呈現及編輯。

**Tech Stack:** Python、現有 HTTP app、原生 HTML/CSS/JavaScript、Python unittest、Node test runner。

## Global Constraints

- Render PostgreSQL 不在本次更新中扣款。
- 不建立新資料庫、不修改 `DATABASE_URL`。
- Render 預算為 US$6.30/月、NT$210/月、NT$2,500/年；實際帳單為準。
- Render 最後期限為 2026-08-23，提醒節點為 30／14／7／3／1 天。
- 待付款必要服務不得計入已發生支出或本月損益。
- 付款網址僅允許 HTTPS，且不保存任何付款憑證。

---

### Task 1: 必要服務資料模型與計算

**Files:**
- Modify: `finance_admin.py`
- Test: `tests/test_finance_admin.py`

**Interfaces:**
- Produces: `create_essential_service(state, payload, actor, now=None) -> dict`
- Produces: `update_essential_service(state, service_id, payload, actor, now=None) -> dict`
- Produces: `essential_service_summary(state, now=None) -> dict`
- Extends: `finance_dashboard(...)["essential_services"]`

- [ ] **Step 1: Write failing tests** for idempotent Render seed, US$6.30/NT$210/NT$2,500 values, 2026-08-23 deadline, remaining days, reminder nodes, validation, audit events, and exclusion from `expenses.gross`.
- [ ] **Step 2: Run `python -m unittest tests.test_finance_admin -v`** and verify the new assertions fail because the service functions and dashboard field do not exist.
- [ ] **Step 3: Implement the minimal model** with allowed statuses `pending`, `due_soon`, `paid`, `overdue`, `pausable`, allowed priorities `critical`, `required`, `optional`, HTTPS URL validation, reminder normalization, and one seeded `render-postgresql-alive-checkin-state` record.
- [ ] **Step 4: Re-run `python -m unittest tests.test_finance_admin -v`** and verify all finance model tests pass.

### Task 2: 受保護的必要服務 API

**Files:**
- Modify: `app.py`
- Test: `tests/test_finance_api.py`

**Interfaces:**
- Consumes: `create_essential_service`, `update_essential_service`, `finance_dashboard`
- Produces: `POST /api/admin/finance/services`
- Produces: `PUT /api/admin/finance/services/{service_id}`

- [ ] **Step 1: Write failing API tests** proving unauthenticated access returns 401, read-only roles return 403 on mutation, finance managers can create/update, and invalid URLs return 400.
- [ ] **Step 2: Run `python -m unittest tests.test_finance_api -v`** and verify failures are caused by missing routes.
- [ ] **Step 3: Add the two routes** using the existing admin session, CSRF, permission, JSON error, persistence, and locking patterns already used by finance expenses/settings.
- [ ] **Step 4: Re-run `python -m unittest tests.test_finance_api -v`** and verify all finance API tests pass.

### Task 3: 後台必要服務監控介面

**Files:**
- Modify: `admin.html`
- Test: `tests/admin_finance.behavior.test.mjs`

**Interfaces:**
- Consumes: `GET /api/admin/finance/dashboard`
- Consumes: `POST /api/admin/finance/services`
- Consumes: `PUT /api/admin/finance/services/{service_id}`

- [ ] **Step 1: Write failing Node tests** for the monitoring section, status/priority controls, deadline/reminder display, safe Render payment link, monthly/yearly budget, and protected mutation APIs.
- [ ] **Step 2: Run `node --test tests/admin_finance.behavior.test.mjs`** and verify the tests fail because the interface is absent.
- [ ] **Step 3: Add the minimal UI** to the existing finance page, including red critical warning, table, form, safe `_blank` link with `rel="noopener noreferrer"`, and a note that no charge occurs until Render confirms upgrade.
- [ ] **Step 4: Add the admin-member-page warning banner** using the same dashboard response; show 30／14／7／3／1-day critical alerts only to authenticated administrators and remove the banner after payment.
- [ ] **Step 5: Extend `loadFinanceDashboard` and save handlers** to render services, calculate labels, handle errors in Chinese, and disable mutations without `finance.manage`.
- [ ] **Step 6: Re-run `node --test tests/admin_finance.behavior.test.mjs`** and verify the finance UI and inline JavaScript syntax tests pass.

### Task 4: 回歸驗證與安全合併

**Files:**
- Verify only unless a test exposes an in-scope defect.

**Interfaces:**
- Consumes all prior tasks.

- [ ] **Step 1: Run `python -m unittest tests.test_finance_admin tests.test_finance_api -v`.**
- [ ] **Step 2: Run `node --test tests/admin_finance.behavior.test.mjs tests/admin_independent_pages.behavior.test.mjs tests/admin_dark_theme.behavior.test.mjs`.**
- [ ] **Step 3: Run `git diff --check` and the repository's documented offline suite.** Record unrelated pre-existing failures separately without claiming a fully green suite.
- [ ] **Step 4: Fetch and integrate latest `origin/main` without force pushing.** Re-run Steps 1–3 after resolving any overlap.
- [ ] **Step 5: Commit only the spec, plan, finance model/API/UI, and their tests.** Push to `idappleilike3/alive-checkin` `main` only after verifying local and remote commit ancestry.

### Final-review correction constraints

- [x] 將分類、計費週期、幣別、每期原幣金額與下次續費日納入持久化、API 與可編輯介面，並保留舊欄位相容性。
- [x] dashboard GET 透過既有原子狀態交易建立 Render 種子，第一次寫入時間與唯一建立稽核，後續讀取保持冪等。
- [x] 一般年預算固定由月預算乘 12；Render 的 NT$2,500 使用明確固定覆寫。空白數字不轉為零。
- [x] dashboard、種子與財務寫入使用台灣應用時間；瀏覽器預設日期使用本地日曆欄位而非 UTC ISO。
- [x] 每個提醒節點確定性回傳一次狀態，過期節點標為「已錯過」，持續警示在已付款後停止；不新增 LINE 推播。
