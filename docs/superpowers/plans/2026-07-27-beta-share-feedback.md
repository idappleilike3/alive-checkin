# 封測分享與每日回報 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 399／799 封測、14 天體驗與核心守護人入口的母女圖文介紹，並在 21 天封測期間每天 19:00 發送可回報的 LINE 詢問。

**Architecture:** 公開入口以共用母女情境素材與一致的新手文案說明服務，再依封測組別顯示任務。後端以既有 Render 排程、LINE push 與狀態檔模式產生每日 Flex 訊息、去重送出並保存回報，後台沿用既有推播及封測名單資料顯示結果。

**Tech Stack:** Flask、原生 HTML/CSS/JavaScript、LINE Messaging API Flex Message、unittest/pytest。

## Global Constraints

- 台灣時間每天 19:00，每位有效封測者最多主動推播一則封測詢問。
- 399 與 799 顯示不同任務；799 包含家庭群組、多人守護、SOS 與安全守護。
- 回報選項包含：使用正常、發現問題、使用心得、不會操作、稍後提醒。
- 錯誤回報要求截圖、發生時間、操作步驟、手機型號與 LINE 版本。
- 參加前須顯示不刷卡、不自動扣款、一次免費資格、推播頻率及回報規則。
- 核心守護人接受邀請前須看守護用途、通知、定位限制、個資與解除方式。

---

### Task 1: 四類新手入口

**Files:**
- Modify: `beta-register.html`
- Modify: `liff/onboarding.html`
- Modify: `invite.html`
- Create: `guardian-guide.html`
- Test: `tests/test_beta_share_feedback.py`

**Interfaces:**
- Consumes: `/beta/399`、`/beta/799`、LIFF onboarding 與 `/invite`
- Produces: 已閱讀規則後才可繼續的封測入口，以及一致的母女圖文說明

- [ ] 寫入入口行為測試，驗證方案任務、規則同意、母女圖與 LINE 連結。
- [ ] 執行 `python -m unittest tests.test_beta_share_feedback -v`，確認因缺少頁面行為而失敗。
- [ ] 補齊四類入口的最小可用圖文、規則勾選與方案任務。
- [ ] 重跑測試並確認通過。

### Task 2: 每日 19:00 封測詢問與回報

**Files:**
- Modify: `app.py`
- Test: `tests/test_beta_share_feedback.py`

**Interfaces:**
- Produces: `build_beta_feedback_flex(profile, day)`、`send_beta_daily_feedback(config, now)` 與 postback 回報處理

- [ ] 寫入失敗測試，驗證 19:00 時區、有效封測資格、每日去重、方案任務及五種回報。
- [ ] 執行單檔測試，確認功能缺少造成預期失敗。
- [ ] 實作 Flex、排程發送、推播紀錄與回報狀態保存。
- [ ] 重跑單檔測試並確認通過。

### Task 3: 後台回報摘要與發布驗證

**Files:**
- Modify: `admin.html`
- Modify: `render.yaml`
- Test: `tests/test_beta_share_feedback.py`

**Interfaces:**
- Consumes: 會員 `beta_feedback_*` 欄位與既有 `push_logs`
- Produces: 封測名單中的最近回報、回報時間與當日推播狀態

- [ ] 寫入後台顯示與排程路由測試並確認失敗。
- [ ] 補齊後台欄位、受保護 cron 路由及 Render 排程設定。
- [ ] 執行新增測試、相關回歸測試與完整測試。
- [ ] 整合最新 GitHub `main`、再次驗證後發布並檢查正式頁面與健康狀態。
