# 第 7 天 LINE 置頂提醒 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 部署後只對新達到方案第 7 天的會員推播一次 LINE 置頂提醒，並在後台留下可追查紀錄。

**Architecture:** 在既有每分鐘 Cron tick 中加入獨立的 `send_day7_pin_reminders`。它以狀態檔中的功能啟用切點阻止舊會員補發，以資格鍵防止重複，並沿用 LINE retry key、notification logs 與後台中文錯誤顯示。

**Tech Stack:** Python、Flask、JSON/PostgreSQL 狀態持久化、LINE Messaging API、原生 unittest、HTML/JavaScript 後台

## Global Constraints

- 不補發給功能啟用前已達第 7 天的舊會員。
- 14 天體驗、六種正式方案及 B399／B799 免繳封測均適用。
- 同一資格期間只成功發送一次。
- 後台必須顯示當時方案、預定時間、實際時間、成功／失敗與中文錯誤。

---

### Task 1: 排程資格與防補發

**Files:**
- Modify: `app.py`
- Test: `tests/test_day7_pin_reminders.py`

**Interfaces:**
- Produces: `membership_activation_time(profile) -> datetime | None`
- Produces: `send_day7_pin_reminders(config, now=None) -> tuple[dict, int]`

- [ ] 寫入首次執行只建立切點、舊會員不補發、各方案啟用時間判定的失敗測試。
- [ ] 執行 `python -m unittest tests.test_day7_pin_reminders -v`，確認新測試失敗。
- [ ] 實作資格鍵、啟用切點、到期判定與 Cron 接線。
- [ ] 再次執行測試並確認通過。

### Task 2: LINE 文案、紀錄與後台顯示

**Files:**
- Modify: `app.py`
- Modify: `admin.html`
- Test: `tests/test_day7_pin_reminders.py`

**Interfaces:**
- Extends: `append_notification_log(..., metadata=None)`

- [ ] 寫入文案、成功防重、失敗重試、B799 方案快照與後台欄位測試。
- [ ] 執行測試，確認舊程式不能滿足斷言。
- [ ] 實作 Flex 推播、固定 retry key、紀錄 metadata 與後台呈現。
- [ ] 執行相關測試、排程測試與完整測試套件。
- [ ] 檢查差異只含本功能、設計、計畫及測試後提交。

