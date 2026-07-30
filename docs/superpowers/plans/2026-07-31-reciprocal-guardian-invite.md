# 反向守護邀請 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 接受守護邀請後，讓受邀者依會員／免費資格一鍵送出反向邀請，同時在所有相關頁面清楚說明單向與雙向守護。

**Architecture:** 保留現有單向綁定 API 與邀請 token 安全規則。`index.html` 保存剛完成綁定的邀請人資訊並處理資格分流，再沿用 `liff/share-invite.html` 建立與分享反向邀請；公開頁面只加入一致文案，不另建重複流程。

**Tech Stack:** Flask、原生 JavaScript、LIFF `shareTargetPicker`、Python unittest/pytest、Node 行為測試。

## Global Constraints

- 接受邀請只建立「受邀者守護邀請人」。
- 反向關係必須經第二份邀請及原邀請人親自接受。
- 不自動啟用免費體驗、付費方案或扣款。
- 免費資格每位會員只能使用一次。
- 沿用現有專屬邀請連結、複製連結與 QR Code 備援。

---

### Task 1: 綁定成功與資格分流

**Files:**
- Modify: `index.html`
- Test: `tests/reciprocal_guardian_invite.behavior.test.mjs`

**Interfaces:**
- Consumes: `/api/line/register` 的 `activate_own_trial` 與現有 `currentStatusData`
- Produces: `startReciprocalGuardianInvite()`，將反向邀請導向 `liff/share-invite.html`

- [ ] **Step 1: Write the failing test**

新增測試，斷言成功畫面包含 `完成，開始守護`、`我也想讓 A 守護我`，且第二個按鈕會依 `plan`、`membership_source` 與免費資格結果分流到體驗、方案或反向分享。

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test tests/reciprocal_guardian_invite.behavior.test.mjs`
Expected: FAIL，因反向邀請按鈕與處理函式尚不存在。

- [ ] **Step 3: Write minimal implementation**

保存已接受邀請的 `inviteFrom` 與顯示名稱；新增兩個成功按鈕和 `startReciprocalGuardianInvite()`。有效會員直接進分享；可用免費資格者需明確啟用；資格已用完者導向 `/liff/pricing.html`。

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test tests/reciprocal_guardian_invite.behavior.test.mjs`
Expected: PASS。

### Task 2: 反向邀請分享提示

**Files:**
- Modify: `liff/share-invite.html`
- Test: `tests/reciprocal_guardian_invite.behavior.test.mjs`

**Interfaces:**
- Consumes: `reciprocal_for`、`reciprocal_name` 查詢參數
- Produces: 指向原邀請人的反向邀請提示與既有 LINE 好友選擇器

- [ ] **Step 1: Write the failing test**

斷言分享頁讀取反向邀請參數，顯示「A 接受後才完成互相守護」，且仍呼叫既有 `shareTargetPicker`。

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test tests/reciprocal_guardian_invite.behavior.test.mjs`
Expected: FAIL，因分享頁尚未辨識反向邀請。

- [ ] **Step 3: Write minimal implementation**

在現有分享頁加入反向邀請提示，不改動邀請建立 API、token 或備援分享。

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test tests/reciprocal_guardian_invite.behavior.test.mjs`
Expected: PASS。

### Task 3: 九個頁面統一文案

**Files:**
- Modify: `invite.html`
- Modify: `index.html`
- Modify: `liff/onboarding.html`
- Modify: `liff/share-invite.html`
- Modify: `liff/member.html`
- Modify: `trial-14.html`
- Modify: `liff/pricing.html`
- Modify: `faq.html`
- Modify: `beta-register.html`
- Test: `tests/reciprocal_guardian_copy.test.py`

**Interfaces:**
- Consumes: 已核定的單向／反向邀請產品規則
- Produces: 九個頁面一致的使用者說明

- [ ] **Step 1: Write the failing test**

逐頁斷言包含「不會自動互相綁定」與反向邀請需對方親自接受的等義文案；FAQ 另斷言接受邀請不會自動取得免費體驗或扣款。

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/reciprocal_guardian_copy.test.py -q`
Expected: FAIL，列出缺少統一說明的頁面。

- [ ] **Step 3: Write minimal implementation**

在每個既有相關區塊加入短版說明，不改價格、方案權益與其他流程。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/reciprocal_guardian_copy.test.py -q`
Expected: PASS。

### Task 4: 回歸與發布

**Files:**
- Test: `tests/test_invite_onboarding_flow.py`
- Test: `tests/test_invitee_plan_flow.py`
- Test: `tests/test_story_comic_landing_pages.py`

**Interfaces:**
- Consumes: Tasks 1–3 的完整變更
- Produces: 可安全合併的 GitHub PR

- [ ] **Step 1: Run targeted regression**

Run: `python -m pytest tests/test_invite_onboarding_flow.py tests/test_invitee_plan_flow.py tests/test_story_comic_landing_pages.py tests/reciprocal_guardian_copy.test.py -q && node --test tests/reciprocal_guardian_invite.behavior.test.mjs`
Expected: 全部 PASS。

- [ ] **Step 2: Run syntax and diff checks**

Run: `python -m py_compile app.py && git diff --check`
Expected: 無錯誤。

- [ ] **Step 3: Commit and publish**

提交本次相關檔案至獨立分支，建立 PR，確認差異後合併至 `main`。

- [ ] **Step 4: Verify production**

確認 Render 正式站回傳兩個成功按鈕、反向邀請提示及九頁統一文案；不送出真實邀請。
