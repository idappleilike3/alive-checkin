# 全站上線資安強化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 對每日平安全站資安 10 項進行可測試的稽核與修正，並在後台顯示不可手動偽造的上線門檻。

**Architecture:** 安全控制集中於 Flask request/response boundary、驗證／授權 helper 與安全事件模組；高風險 API 共用 fail-closed guard。靜態掃描、部署環境檢查、備份還原與事故手冊產生機器可讀證據，再由後台聚合狀態。

**Tech Stack:** Flask、LINE ID token/webhook verification、Python unittest、Node test runner、pip-audit（可用時）、Render HTTPS。

## Global Constraints

- 第 1～6 項任何一項不通過，狀態必須是「禁止正式公開營運」。
- 第 7～10 項未達基本門檻，狀態必須是「禁止公開測試」。
- 不輸出或保存正式 Token、Cookie、電話、地址、座標與完整 LINE UID。
- 不執行破壞性外部滲透測試；正式站驗收只做非破壞檢查。

---

### Task 1: 機密與依賴稽核

**Files:** Create `security_audit.py`, `tests/test_security_audit.py`; Modify `.gitignore`, `.env.example`.

- [ ] 先寫會抓出前端／版本庫機密格式、危險檔名及缺少環境變數的失敗測試。
- [ ] 實作只回報檔案與規則、不回傳機密值的掃描器。
- [ ] 執行依賴弱點掃描；不可用時明確標記「未檢查」，不得偽裝通過。

### Task 2: API 驗證、授權與輸入安全

**Files:** Modify `app.py`, `line_auth.py`; Create `security_controls.py`; Test `tests/test_security_boundaries.py`.

- [ ] 先寫偽造 UID、過期／錯 audience token、CSRF、角色越權、物件越權、XSS、危險轉址與錯誤資訊洩漏測試。
- [ ] 建立 schema 驗證、同源 URL、物件擁有者及高風險操作 guard。
- [ ] 將會員、守護人、SOS、定位、邀請、退款、推播、重綁與財務 API 接上共用 guard。

### Task 3: 瀏覽器與濫用防護

**Files:** Modify `app.py`, `render.yaml`; Test `tests/test_security_headers_and_limits.py`.

- [ ] 先寫 HTTPS、Cookie、CSP、HSTS、CORS、429 與重放的失敗測試。
- [ ] 實作安全標頭、可信代理 HTTPS、每操作／帳號／來源頻率限制與冪等鍵。
- [ ] 確保 LINE LIFF、地圖與金流允許來源不被 CSP 誤擋。

### Task 4: 日誌、備份與事故應變

**Files:** Create `security_operations.py`, `docs/SECURITY_INCIDENT_RUNBOOK.md`; Modify backup functions; Test `tests/test_security_operations.py`.

- [ ] 先寫敏感資料遮罩、備份加密狀態、還原證據與緊急開關測試。
- [ ] 實作安全事件、集中遮罩、備份／還原證據與推播／金流緊急停止開關。
- [ ] 建立不含機密的金鑰輪替、Session 失效、復原與通知手冊。

### Task 5: 後台資安上線狀態與總驗收

**Files:** Modify `admin.html`, `app.py`; Create `tests/test_security_readiness.py`, `tests/admin_security_readiness.behavior.test.mjs`.

- [ ] 先寫 10 項證據狀態與阻擋邏輯測試，確認不能靠手動勾選變成通過。
- [ ] 實作後台狀態頁、證據日期、阻擋原因與唯讀詳細資料。
- [ ] 執行完整 Python／Node 回歸、機密掃描、依賴掃描、`git diff --check` 與正式站非破壞驗收。

