# Reminder Plan And Contact Collapse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 統一 399／799 提醒權益與預設時段，並讓多人聯絡人名單保持可操作。

**Architecture:** 後端 `PLAN_LIMITS` 是提醒次數權威來源，前端依 API 回傳上限產生 1～3 個時段。聯絡人只調整 `liff/member.html` 的呈現與互動，不更動 Task 3 綁定資料模型。

**Tech Stack:** Flask、Python unittest、原生 HTML/CSS/JavaScript、LINE LIFF

## Global Constraints

- 399 月費／年費最多 2 次；799 月費／年費最多 3 次。
- 預設 12:00、18:00；第 3 次 22:00。
- 簽到後停止當日剩餘提醒。
- 不修改 Task 3 安全邀請邏輯，不部署，不覆蓋未提交圖片。

---

### Task 1: 提醒規則與方案同步

**Files:**
- Modify: `app.py`
- Modify: `liff/pricing.html`
- Modify: `README.md`
- Test: `tests/test_product_rules.py`

- [x] 先新增 399／799 月年提醒限制與公開文案測試。
- [x] 執行單項測試並確認 399 年費舊值 3 造成失敗。
- [x] 將 399 年費改為 2，並同步公開方案與比較表。
- [ ] 執行產品規則與提醒回歸測試。

### Task 2: 聯絡人收合卡片

**Files:**
- Modify: `liff/member.html`
- Test: `tests/test_product_rules.py`

- [x] 新增預設收合與 ARIA 結構測試。
- [x] 將摘要與詳細操作拆成收合卡片。
- [x] 加入同名單一次只展開一張的互動。
- [ ] 執行前端靜態規則與行為測試。

### Task 3: 文案與完整驗收

**Files:**
- Modify: `index.html`
- Modify: `liff/onboarding.html`
- Modify: `tests/test_invite_reward_retain.py`
- Modify: `tests/test_checkin_postback_and_smart.py`

- [x] 移除已取消的邀請延長 7 天銷售文案。
- [ ] 執行相關測試模組。
- [ ] 執行完整測試並記錄既有與新增失敗。
- [ ] 檢查 Git diff，確認圖片與 Task 3 安全邏輯未被修改。
