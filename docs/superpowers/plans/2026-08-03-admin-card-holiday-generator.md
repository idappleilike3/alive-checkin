# 後台圖文卡與節日背景生成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓管理員可用簡單三步驟設定、預覽與安全發送個人化 LINE 圖文卡，並從台灣常用大小節日範本產生可修改的背景圖。

**Architecture:** 範本與節日素材資料存入既有狀態儲存層；後端集中驗證 HTTPS 網址、產生會員個人化 Flex 預覽並在明確確認後發送。節日背景生成以內建腳本為基礎，設定 `OPENAI_API_KEY` 時呼叫圖片 API，未設定時回傳中文設定指引且不建立假圖片。

**Tech Stack:** Flask、既有 JSON/PostgreSQL 狀態儲存、原生 JavaScript/CSS、Python unittest、LINE Flex Message、OpenAI Images HTTP API。

## Global Constraints

- 每日平安 Logo 固定使用既有原圖，不可修改、變色、裁切或替換。
- 預覽、儲存與生成腳本不得發送 LINE 訊息。
- 單人發送需一次確認；群發需名單預覽與第二次確認。
- 圖片與按鈕連結只接受 HTTPS。
- 節日背景只包含主視覺，不生成 Logo、會員姓名、祝福文字或假按鈕。
- 不自動排程、不自動群發。

---

### Task 1: 範本資料、安全驗證與會員預覽

**Files:**
- Modify: `app.py`
- Test: `tests/test_admin_personalized_card_editor.py`

**Interfaces:**
- Produces: `list_card_templates(state)`, `save_card_template(data_file, payload)`, `preview_personalized_card(data_file, uid, template_id, now)`。

- [ ] **Step 1: Write the failing test** covering default template, HTTPS rejection, persistence and preview-without-send.
- [ ] **Step 2: Run test to verify it fails** with missing functions.
- [ ] **Step 3: Write minimal implementation** using the existing state store and `build_daily_checkin_flex`.
- [ ] **Step 4: Run test to verify it passes** with all editor tests green.
- [ ] **Step 5: Commit** the tested backend behavior.

### Task 2: 節日目錄、腳本與背景生成邊界

**Files:**
- Modify: `holidays_tw.py`
- Modify: `app.py`
- Test: `tests/test_admin_holiday_background_generator.py`

**Interfaces:**
- Produces: `holiday_template_catalog()`, `build_holiday_image_prompt(payload)`, `generate_holiday_background(config, payload)`。

- [ ] **Step 1: Write the failing test** covering major/minor festivals, lunar display dates, prompt rules and missing-key Chinese error.
- [ ] **Step 2: Run test to verify it fails** because generator interfaces do not exist.
- [ ] **Step 3: Write minimal implementation** with built-in scripts and a dependency-injected image generator boundary.
- [ ] **Step 4: Run test to verify it passes** and confirm no LINE sender is invoked.
- [ ] **Step 5: Commit** the tested holiday backend.

### Task 3: 管理 API 與稽核

**Files:**
- Modify: `app.py`
- Test: `tests/test_admin_personalized_card_api.py`

**Interfaces:**
- Consumes: Task 1 and Task 2 service functions.
- Produces: `/api/admin/card-templates`, `/api/admin/personalized-checkin-push/card-preview`, `/api/admin/holiday-card/*` routes.

- [ ] **Step 1: Write the failing test** for auth, preview non-delivery, save validation and generation error responses.
- [ ] **Step 2: Run test to verify it fails** because routes are absent.
- [ ] **Step 3: Write minimal implementation** and add sanitized admin audit records for writes/generation.
- [ ] **Step 4: Run test to verify it passes** with correct HTTP codes and Chinese messages.
- [ ] **Step 5: Commit** the API layer.

### Task 4: 簡易後台介面

**Files:**
- Modify: `admin.html`
- Test: `tests/admin_personalized_card_editor.behavior.test.mjs`

**Interfaces:**
- Consumes: Task 3 APIs.
- Produces: two-tab editor, three-step member preview/send, isolated two-step group send and holiday generator.

- [ ] **Step 1: Write the failing behavior test** for controls, disabled states, Chinese guidance, mobile layout and preview-only actions.
- [ ] **Step 2: Run test to verify it fails** because the editor is absent.
- [ ] **Step 3: Write minimal HTML/CSS/JS implementation** using the existing blue-green admin design and fixed logo.
- [ ] **Step 4: Run behavior and JavaScript syntax tests** until green.
- [ ] **Step 5: Commit** the UI.

### Task 5: Release verification and deployment

**Files:**
- Modify: `docs/superpowers/specs/2026-08-03-admin-personalized-card-editor-design.md`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: verified `main` deployment without sending LINE messages.

- [ ] **Step 1: Update the spec** with the approved A-mode holiday background generator and festival catalog.
- [ ] **Step 2: Run targeted Python/Node tests and compile checks**; expected zero failures.
- [ ] **Step 3: Run the safe offline regression suite**; record any pre-existing failures separately.
- [ ] **Step 4: Review git diff** for Logo changes, credentials and accidental push calls.
- [ ] **Step 5: Commit and update GitHub `main`**, then verify Render `/health` and the deployed admin assets without clicking send.
