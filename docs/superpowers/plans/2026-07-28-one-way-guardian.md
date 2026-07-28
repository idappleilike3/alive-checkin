# One-way Guardian Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成單向核心守護、獨立 14 天體驗、首頁與會員中心導引及雙方向各自同意。

**Architecture:** 保留現有 Flask 狀態模型及 LIFF 單頁首頁，以 `guarding_for` 表示免費接收關係，以會員 entitlement 表示主動報平安權益。邀請接受 API 永遠只寫入一個方向，第二方向只能透過新的邀請與同意建立。

**Tech Stack:** Python 3、Flask、原生 HTML/CSS/JavaScript、LINE LIFF、`unittest`

## Global Constraints

- 接受守護邀請不得自動啟用 14 天體驗。
- 一次接受只建立「受邀者守護邀請人」。
- 每一個反向關係都要新的邀請及第二次同意。
- 不得自動扣款或自動互綁。
- 受邀者必須加入官方 LINE、LINE 登入並填寫姓名、關係、手機。

---

### Task 1: 鎖定單向權益

**Files:**
- Modify: `tests/test_invite_onboarding_flow.py`
- Modify: `app.py`

**Interfaces:**
- Consumes: `bind_emergency_contact(data_file, payload, config=None)`
- Produces: 接受邀請後 `reciprocal == False`、`mutual_core_applied == False`，且受邀者不會取得 trial

- [ ] **Step 1: Write the failing test**

新增測試，讓 A 邀請 B 後檢查 B 的 `guarding_for` 包含 A，但 B 沒有 trial entitlement。

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_invite_onboarding_flow -v`

- [ ] **Step 3: Write minimal implementation**

移除接受邀請路徑中的任何隱含 trial 啟用及殘留互綁欄位。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_invite_onboarding_flow -v`

### Task 2: 完成首頁與登入導引

**Files:**
- Modify: `index.html`
- Modify: `liff/share-invite.html`
- Test: `tests/test_invite_onboarding_flow.py`

**Interfaces:**
- Consumes: `rememberPendingGuardianInvite()`、`restorePendingGuardianInvite()`、`completeGuardianBindOnce()`
- Produces: `startMyOwnTrialFromGuardianSuccess()` 與清楚的單向成功視窗

- [ ] **Step 1: Write the failing UI assertions**

檢查邀請四步驟、資料表單、單向說明、「我也要報平安｜免費體驗 14 天」及會員中心雙列表。

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_invite_onboarding_flow -v`

- [ ] **Step 3: Implement minimal UI**

補齊按鈕、登入後邀請還原、綁定成功視窗與試用入口；刪除 `mutual_core` UI 傳遞。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_invite_onboarding_flow -v`

### Task 3: 回歸驗證與發布

**Files:**
- Modify: `tests/test_bind_and_home_gate.py`
- Verify: `tests/test_checkin_demo_cards.py`

**Interfaces:**
- Consumes: 新版單向規則
- Produces: 與新版規格一致的回歸測試及可部署提交

- [ ] **Step 1: Replace obsolete mutual-binding expectations**

將舊「一次互綁」測試改為「兩次獨立邀請與同意」。

- [ ] **Step 2: Run focused suites**

Run: `python -m unittest tests.test_invite_onboarding_flow tests.test_checkin_demo_cards tests.test_bind_and_home_gate -v`

- [ ] **Step 3: Inspect diff and syntax**

Run: `python -m py_compile app.py`

- [ ] **Step 4: Commit and deploy**

只提交本次相關檔案，更新 GitHub `main`，等待 Render 後驗收正式頁面。

