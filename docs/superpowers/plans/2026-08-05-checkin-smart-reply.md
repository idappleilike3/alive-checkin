# 報平安智慧回覆 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓會員本人收到完整的報平安進度與新聞資訊；核心守護人只收到報平安時間與新聞資訊。

**Architecture:** 在 `app.py` 建立共用的報平安內容 context，沿用 `daily_care.py` 的新聞判定與等級規則，再由本人與守護人兩種 formatter 組成各自訊息。既有 `record_checkin` 與 LINE 發送流程不變，只替換訊息內容來源。

**Tech Stack:** Python 3、unittest、現有 LINE push sender、`daily_care.py`

## Global Constraints

- 時區固定 Asia/Taipei。
- 沒有重大安全新聞時顯示「今日暫無重要安心提醒」。
- 守護人不收到會員祝福語、等級、連續天數或下次提醒時間。
- 同日重複報平安不重複通知守護人。

---

### Task 1: 共用智慧內容與本人回覆

**Files:**
- Modify: `app.py`
- Test: `tests/test_checkin_smart_success_messages.py`

**Interfaces:**
- Consumes: `build_daily_care_context(profile, now)`, `streak_level_context(streak_days, highest_streak_days)`
- Produces: `build_checkin_message_context(profile, now) -> dict`, `build_checkin_success_text(status, now=None, config=None) -> str`

- [ ] 寫入失敗測試，驗證真實日期時間、祝福、等級、連續天數、重大新聞與下次提醒。
- [ ] 執行測試並確認因缺少新內容而失敗。
- [ ] 實作最小共用 context 與本人 formatter。
- [ ] 執行測試並確認通過。

### Task 2: 守護人智慧通知

**Files:**
- Modify: `app.py`
- Test: `tests/test_checkin_smart_success_messages.py`

**Interfaces:**
- Consumes: `build_checkin_message_context(profile, now) -> dict`
- Produces: `build_guardian_checkin_text(profile, now) -> str`

- [ ] 寫入失敗測試，驗證守護人收到完成時間與重大新聞，但沒有祝福、等級、連續天數或下次提醒。
- [ ] 執行測試並確認失敗原因正確。
- [ ] 將 `notify_guardians_of_checkin` 改用共用 formatter。
- [ ] 驗證有新聞顯示、無新聞顯示明確狀態且既有收件人規則不變。

### Task 3: 回歸驗證與部署

**Files:**
- Modify: `.render-deploy-trigger-20260805-checkin-smart-reply.txt`（僅在需要明確觸發部署時）

**Interfaces:**
- Consumes: Task 1、Task 2 的完成程式與測試
- Produces: 可部署的 `main` 提交

- [ ] 執行新增測試、既有報平安與守護人測試。
- [ ] 執行完整 Python 測試與 `python -m py_compile app.py daily_care.py`。
- [ ] 檢查 git diff 僅含本次範圍。
- [ ] 提交、推送 `main`，並核對正式部署狀態。
