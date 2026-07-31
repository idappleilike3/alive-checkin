# 管理後台獨立分頁 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將管理後台改為左側三層導覽與右側獨立內容頁，並提升桌機及手機的文字可讀性。

**Architecture:** 保留單一 `admin.html` 與既有 API，以白名單 `page` 查詢參數控制唯一可見的內容群組。導覽使用正常網址換頁；手機使用不改變資料狀態的側欄抽屜。

**Tech Stack:** Flask 靜態頁面、HTML、CSS、原生 JavaScript、Node.js `node:test`、Python `unittest`

## Global Constraints

- 不修改資料庫、管理 Session、CSRF、會員資料或營運 API。
- 保留既有功能元素的 DOM id。
- 導覽最多三層。
- 內文至少 16px、說明文字至少 15px、操作元件最低 48px。
- 未知頁面參數回到 `operations`。

---

### Task 1: 分頁導覽行為

**Files:**
- Modify: `admin.html`
- Create: `tests/admin_independent_pages.behavior.test.mjs`

**Interfaces:**
- Consumes: `URLSearchParams(window.location.search)`
- Produces: `ADMIN_PAGES`, `getAdminPage()`, `applyAdminPage()`, `toggleAdminNav()`

- [ ] **Step 1: Write the failing test**

測試正常連結使用 `?page=`、存在五個第一層分類、頁面白名單與未知參數回退。

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test tests/admin_independent_pages.behavior.test.mjs`
Expected: FAIL，舊版仍使用 `href="#..."`。

- [ ] **Step 3: Write minimal implementation**

將舊橫向錨點導覽換成分層側欄，為各內容區塊加上固定 `data-admin-page`，登入後呼叫 `applyAdminPage()` 只顯示目前群組。

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test tests/admin_independent_pages.behavior.test.mjs`
Expected: PASS。

### Task 2: 可讀性與手機側欄

**Files:**
- Modify: `admin.html`
- Modify: `tests/admin_independent_pages.behavior.test.mjs`

**Interfaces:**
- Consumes: `.admin-layout`, `.admin-sidebar`, `.admin-nav-toggle`, `.admin-nav-backdrop`
- Produces: 桌機固定側欄與手機抽屜

- [ ] **Step 1: Write the failing test**

測試 280px 側欄、16px 內文、15px 說明、48px 控制項、手機抽屜與表格水平捲動規則。

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test tests/admin_independent_pages.behavior.test.mjs`
Expected: FAIL，舊版為 14px 導覽及 42px 控制項。

- [ ] **Step 3: Write minimal implementation**

加入桌機 grid、sticky sidebar、手機 fixed drawer、遮罩、焦點／目前頁標示及放大字級。

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test tests/admin_independent_pages.behavior.test.mjs`
Expected: PASS。

### Task 3: 相容性與完整驗證

**Files:**
- Modify: `admin.html`
- Modify: `tests/admin_auth_ui.test.mjs` only if the real DOM harness needs the new fixed navigation elements

**Interfaces:**
- Consumes: 現有後台登入與資料刷新函式
- Produces: 不改 API 的分頁後台

- [ ] **Step 1: Run focused UI tests**

Run: `node --test tests/admin_independent_pages.behavior.test.mjs tests/admin_auth_ui.test.mjs tests/admin_beta_ui.test.mjs tests/admin_launch_readiness_ui.test.mjs tests/admin_plan_update_feedback.behavior.test.mjs`
Expected: PASS。

- [ ] **Step 2: Run focused Python tests**

Run: `python -m unittest tests.test_admin_business_dashboard tests.test_admin_session_auth tests.test_admin_test_center_ui`
Expected: PASS。

- [ ] **Step 3: Run the project offline suite**

Run: `python tests/run_offline_suite.py`
Expected: PASS，0 failures。

- [ ] **Step 4: Inspect diff**

Run: `git diff --check && git diff --stat && git status --short`
Expected: 無空白錯誤，只有規格、計畫、後台與測試相關檔案。
