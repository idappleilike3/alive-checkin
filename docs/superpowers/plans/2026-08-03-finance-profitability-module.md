# 財務與必要支出完整損益模組 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在每日平安後台新增獨立財務頁，串接訂單與退款並計算現金流、年費月分攤、金流費、營業稅、進項稅、淨利與方案損益平衡。

**Architecture:** 新增純 Python `finance_admin.py` 封裝驗證、計算與狀態異動；`app.py` 只負責管理員授權、CSRF、API 路由與稽核。`admin.html` 以既有獨立頁導覽模式呈現 dashboard、支出表單、費率與稅務設定。

**Tech Stack:** Python 3.11／Flask、JSON state persistence、原生 HTML/CSS/JavaScript、unittest、Node test runner。

## Global Constraints

- 年費同時顯示付款當月實收全額與按 12 個月分攤收入，兩者不得重複加總。
- 金流手續費依每筆訂單的金流商費率與固定費計算，退款同步調整。
- 含稅收入以 `含稅 ÷ 1.05` 拆出未稅收入與銷項稅。
- 有統編發票支出預設拆出 5% 可扣抵進項稅，逐筆可標不可扣抵。
- 僅 `super_admin` 與 `finance` 可修改，所有修改必須稽核；一般營運與唯讀角色不得讀取敏感財務明細。

---

### Task 1: 財務領域計算與驗證

**Files:** Create `finance_admin.py`; Test `tests/test_finance_admin.py`

**Interfaces:** Produces `finance_dashboard(state, month, now)`, `create_expense(state, payload, actor, now)`, `update_finance_settings(state, payload, actor, now)`.

- [ ] 先寫訂單、退款、年費分攤、稅額、進項稅與損益平衡的失敗測試。
- [ ] 執行 `python -m unittest tests.test_finance_admin -v`，確認因模組不存在而失敗。
- [ ] 實作 Decimal 金額計算、欄位白名單、日期／枚舉／範圍驗證與不可變稽核事件。
- [ ] 重跑測試並確認通過。

### Task 2: 受保護財務 API

**Files:** Modify `app.py`; Test `tests/test_finance_api.py`

**Interfaces:** Consumes Task 1 functions; Produces `/api/admin/finance/dashboard`、`/expenses`、`/settings`。

- [ ] 先寫未登入、錯誤角色、缺 CSRF、合法新增及稽核的失敗測試。
- [ ] 執行測試確認正確失敗。
- [ ] 加入角色權限與 API 路由，錯誤回應不得包含堆疊或敏感資料。
- [ ] 重跑測試並確認通過。

### Task 3: 獨立後台財務頁

**Files:** Modify `admin.html`; Test `tests/admin_finance.behavior.test.mjs`

**Interfaces:** Consumes Task 2 JSON API; Produces `page=finance` 導覽、摘要卡、支出表與設定表單。

- [ ] 先寫實際 DOM 行為測試，覆蓋角色隱藏、載入、送出、錯誤與續費警示。
- [ ] 執行 Node 測試確認正確失敗。
- [ ] 實作老人友善字級的獨立財務頁與中文說明。
- [ ] 重跑 Node 測試並確認通過。

### Task 4: 財務回歸與部署門檻

**Files:** Modify `README.md`; Test existing suites.

- [ ] 執行財務 Python／Node 測試、完整 Python／Node 回歸與 `git diff --check`。
- [ ] 用 Flask test client 驗證財務 API 不會修改訂單／退款原始紀錄。
- [ ] 記錄測試結果與部署後非破壞 smoke test 步驟。

