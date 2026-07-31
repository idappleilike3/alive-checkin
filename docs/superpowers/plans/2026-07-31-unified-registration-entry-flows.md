# Unified Registration Entry Flows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 統一四個入口的註冊資料說明，並確保 14 天、B399、B799 資格不串流。

**Architecture:** 公開頁只建立帶上下文的 LIFF 連結；LIFF 承接頁保留安全參數；主會員頁依參數顯示方案與欄位歸屬；後端維持資格最終驗證。守護電話改為選填，但姓名、關係及親自同意仍必須。

**Tech Stack:** Flask、原生 JavaScript、HTML、Python unittest

## Global Constraints

- `beta_cohort` 僅允許 B399、B799。
- 守護關係保持單向，不自動互綁。
- 電話選填；填寫後邀請人可見。
- 不建立訂單、不自動扣款。

---

### Task 1: 註冊上下文與表單

**Files:**
- Modify: `liff/onboarding.html`
- Modify: `index.html`
- Modify: `trial-14.html`
- Modify: `invite.html`
- Modify: `beta-register.html`
- Test: `tests/test_unified_registration_entry_flows.py`

**Interfaces:**
- Consumes: URL `open`, `beta_cohort`, `invite_from`, `invite_token`
- Produces: 保留上下文的 LINE 註冊與清楚的本人／守護人欄位

- [x] **Step 1: Write the failing tests**
- [x] **Step 2: Run tests and verify the missing parameter, copy and optional phone failures**
- [x] **Step 3: Preserve `beta_cohort` and render the entry plan**
- [x] **Step 4: Clarify field ownership and make phone optional**
- [x] **Step 5: Run focused and related regression tests**

### Task 2: 後端電話選填

**Files:**
- Modify: `app.py`
- Test: `tests/test_unified_registration_entry_flows.py`

**Interfaces:**
- Consumes: `bind_emergency_contact(... contact_phone="")`
- Produces: accepted one-way binding with an empty phone

- [x] **Step 1: Write and verify a failing invitation acceptance test**
- [x] **Step 2: Remove phone from required guardian profile fields**
- [x] **Step 3: Run guardian binding regressions**

### Task 3: 後台獨立封測分享

**Files:**
- Modify: `admin.html`
- Test: `tests/test_unified_registration_entry_flows.py`

**Interfaces:**
- Produces: `/beta/399` and `/beta/799` share actions

- [x] **Step 1: Write and verify the missing-actions test**
- [x] **Step 2: Add native share with clipboard fallback**
- [x] **Step 3: Verify syntax, tests and final diff**
