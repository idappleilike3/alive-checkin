# LINE 半自動實機驗收 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立只關聯封測名單與既有 LINE 紀錄的半自動實機驗收後台。

**Architecture:** 在既有 JSON state 增加驗收案件 ledger，由純函式驗證封測資格、建立遮罩快照並更新人工結果。Flask 管理員 API 使用現有 session/CSRF，`admin.html` 僅呈現案件與人工確認操作，不提供任意發送入口。

**Tech Stack:** Python、Flask、原子 JSON state、原生 HTML/JavaScript、unittest、Node test runner

## Global Constraints

- 不得自動向正式會員或任意 LINE ID 發送。
- 只有目前 21 天封測會員可建立案件。
- 寫入 API 必須通過管理員 session 與 CSRF。
- 所有自動化測試必須在離線護欄下執行。

---

### Task 1: 驗收案件核心

**Files:**
- Modify: `app.py`
- Create: `tests/test_line_acceptance.py`

**Interfaces:**
- Produces: `line_acceptance_snapshot(state, now=None) -> dict`
- Produces: `create_line_acceptance_case(state, payload, now=None) -> dict`
- Produces: `review_line_acceptance_case(state, case_id, payload, now=None) -> dict`

- [ ] 寫入非封測者、未知類型、遮罩與人工狀態測試。
- [ ] 執行 `python -m unittest tests.test_line_acceptance -v`，確認因函式不存在而失敗。
- [ ] 實作固定七類、組別必測項目、案件建立及人工確認。
- [ ] 重跑測試並確認通過。

### Task 2: 受保護管理員 API

**Files:**
- Modify: `app.py`
- Modify: `tests/test_admin_session_auth.py`

**Interfaces:**
- Produces: `GET/POST /api/admin/line-acceptance`
- Produces: `PATCH /api/admin/line-acceptance/<case_id>`

- [ ] 新增未登入與缺 CSRF 會被拒絕的測試。
- [ ] 執行針對性測試並確認失敗原因正確。
- [ ] 接上 `_admin_guard`、原子寫入與管理稽核。
- [ ] 重跑針對性測試並確認通過。

### Task 3: 後台畫面

**Files:**
- Modify: `admin.html`
- Create: `tests/line_acceptance_ui.behavior.test.mjs`

**Interfaces:**
- Consumes: Task 2 API
- Produces: 安全渲染的案件列表、建立案件及通過／失敗操作

- [ ] 新增 XSS 安全、七類顯示與狀態操作測試。
- [ ] 執行 Node 測試並確認尚未有畫面函式而失敗。
- [ ] 實作列表、表單、狀態按鈕與刷新流程。
- [ ] 重跑 Node 測試並確認通過。

### Task 4: 回歸與部署準備

**Files:**
- Modify: `docs/PROJECT_PROGRESS.md`

**Interfaces:**
- Consumes: Tasks 1–3
- Produces: 可部署且不會在測試中外連的版本

- [ ] 執行 `python tests/run_offline_suite.py`。
- [ ] 執行所有 `node --test tests/*.test.mjs`。
- [ ] 執行 `python -m py_compile app.py ecpay.py newebpay.py`。
- [ ] 檢查 Git diff、Render 必要設定與正式服務健康狀態，再進行推送部署。
