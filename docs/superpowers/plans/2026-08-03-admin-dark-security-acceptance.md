# 管理後台護眼暗色與資安實際驗收 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將全管理後台固定改為護眼暗色，並讓資安 10 項依具日期的真實證據呈現三態與阻擋結論。

**Architecture:** `admin.html` 以一組 CSS 自訂屬性統一後台色彩，既有資訊架構與 JavaScript 行為不變；`security_controls.py` 將每項證據標準化為 `passed`、`failed`、`not_checked`，並由伺服器端計算公開營運及公開測試門檻。平台證據只讀取非機密摘要、來源與時間，不接受前端任意寫入。

**Tech Stack:** HTML/CSS/JavaScript、Flask、Python 3.11、Node test runner、Gunicorn、Render。

## Global Constraints

- 後台固定暗色，不增加亮暗切換開關。
- 不更動既有後台功能、資料、權限或 API 路徑。
- `passed` 必須同時具有可接受證據、來源與檢查日期；缺任一欄位即不得通過。
- 第 1～6 項任一未通過或未檢查，禁止正式公開營運。
- 第 7～10 項任一未通過或未檢查，禁止公開測試。
- 不讀取、顯示、提交或記錄正式機密值。
- 正式站僅執行非破壞 HTTP 探針，不發 LINE、不觸發付款、不觸發 SOS。

---

### Task 1: 資安證據三態模型

**Files:**
- Modify: `security_controls.py`
- Modify: `tests/test_security_readiness.py`

**Interfaces:**
- Consumes: Flask config mapping and optional current time.
- Produces: `security_readiness(config, now)` with `status`, `checked_at`, `evidence_source`, `evidence`, `blocking`, and `remediation` on all 10 items.

- [ ] **Step 1: Write failing tests for evidence completeness and failed/not_checked separation**

Add literal fixtures showing that a success flag without evidence time/source is `not_checked`, an explicit failed result is `failed`, and complete evidence is `passed`.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m unittest tests.test_security_readiness -v`
Expected: FAIL because current items omit evidence metadata and cannot emit `failed`.

- [ ] **Step 3: Implement the minimal evidence normalizer**

Add strict ISO timestamp parsing, evidence-source validation, three-state normalization and explicit remediation text. Preserve secret values as presence/length checks only.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `python -m unittest tests.test_security_readiness -v`
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: require evidence for security readiness`

### Task 2: 資安頁三態顯示與唯讀證據

**Files:**
- Modify: `admin.html`
- Modify: `tests/admin_security_readiness.behavior.test.mjs`

**Interfaces:**
- Consumes: `/api/admin/security/readiness` response from Task 1.
- Produces: Chinese status labels, checked time, evidence source, remediation and correct overall blocking copy without a manual pass control.

- [ ] **Step 1: Write failing UI behavior tests**

Exercise the page script with passed, failed and not_checked response fixtures; assert distinct labels and evidence rendering, and assert no writable status request is made.

- [ ] **Step 2: Run the focused Node test and verify RED**

Run: `node --test tests/admin_security_readiness.behavior.test.mjs`
Expected: FAIL because current UI merges failed and not_checked and omits metadata.

- [ ] **Step 3: Implement minimal three-state rendering**

Render status label/class through an allowlisted mapping, escape every server string, show `checked_at` only when present, and display remediation for non-passed items.

- [ ] **Step 4: Run the focused Node test and verify GREEN**

Run: `node --test tests/admin_security_readiness.behavior.test.mjs`
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: show security evidence states in admin`

### Task 3: 全後台護眼暗色

**Files:**
- Modify: `admin.html`
- Create: `tests/admin_dark_theme.behavior.test.mjs`

**Interfaces:**
- Consumes: existing admin markup and component classes.
- Produces: fixed eye-comfort dark theme variables and complete component coverage, while leaving the LINE card content preview unchanged.

- [ ] **Step 1: Write failing dark-theme contract tests**

Parse computed declarations from the actual page CSS and assert dark luminance for body/sidebar/surfaces, non-white controls and dialogs, visible focus, semantic status variables, dark mobile overlay, and an explicit preview exemption.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `node --test tests/admin_dark_theme.behavior.test.mjs`
Expected: FAIL because the current page uses bright backgrounds and lacks the approved theme variables.

- [ ] **Step 3: Implement minimal theme variables and component overrides**

Define a single palette on `:root`; replace or override body, navigation, cards, tables, controls, autofill, disabled, focus-visible, modal, backdrop and status colors. Preserve only the end-user LINE card canvas as a light preview.

- [ ] **Step 4: Run focused and complete frontend tests**

Run: `node --test tests/*.test.mjs`
Expected: all tests pass.

- [ ] **Step 5: Commit**

Commit message: `feat: add eye comfort dark admin theme`

### Task 4: Release verification and deployment

**Files:**
- Modify only if remote `main` requires conflict resolution.

**Interfaces:**
- Consumes: completed Tasks 1–3 and latest `origin/main`.
- Produces: fast-forward-compatible main update and verified Render deployment.

- [ ] **Step 1: Run offline Python security and regression suites**

Run the focused security/admin suites with Python 3.11, then `python tests/run_offline_suite.py`; record pre-existing baseline separately from new failures.

- [ ] **Step 2: Run syntax, frontend, diff and secret checks**

Run Python compilation, `node --test tests/*.test.mjs`, `git diff --check`, tracked-sensitive-file checks and a value-redacting secret scan.

- [ ] **Step 3: Run a local Gunicorn probe**

Use temporary state and no production credentials; verify `/health` and `/admin?page=security` return 200 without external network calls.

- [ ] **Step 4: Synchronize and publish safely**

Fetch `origin/main`, inspect any new commits, merge by preserving both sides, rerun affected tests, then update `main` without force-push.

- [ ] **Step 5: Verify the live deployment**

Verify build/live status, `/health` 200, dark-theme marker, unauthenticated security API 401, HTTPS security headers, and that the readiness payload remains unavailable without `system.manage` authorization.

