# LINE Foreground Continuous Location Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 LINE LIFF 頁面開啟期間持續更新安全守護的最新位置，並可靠停止及顯示中斷狀態。

**Architecture:** 在 `index.html` 加入一個獨立的前景定位控制器，使用 `watchPosition` 監測位置，以時間與距離門檻節流後呼叫既有 `refresh_only` API。後端維持只保存最新位置，守護人列表以 `updated_at` 判定是否中斷。

**Tech Stack:** Vanilla JavaScript、Geolocation API、Node.js test runner、既有 Flask API

## Global Constraints

- 只在 LINE／瀏覽器頁面開啟期間持續定位
- 不保存完整移動軌跡
- 自動更新不得重複推播守護人
- 停止分享後不得再上傳位置

---

### Task 1: 前景定位控制器

**Files:**
- Modify: `index.html`
- Test: `tests/continuous_location.behavior.test.mjs`

**Interfaces:**
- Consumes: `apiUpdateLocation(position, city, {refreshOnly: true})`
- Produces: `startContinuousLocationTracking(initialPosition)`、`stopContinuousLocationTracking()`、`shouldUploadContinuousLocation(position, now)`

- [ ] **Step 1: Write the failing tests**

測試啟停監測、20 秒／20 公尺節流、60 秒心跳及停止後不再上傳。

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test tests/continuous_location.behavior.test.mjs`
Expected: FAIL because the continuous-location functions do not exist.

- [ ] **Step 3: Write minimal implementation**

加入 `watchPosition` 控制器與狀態，首次安全守護成功後啟動，停止安全守護時清除。

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test tests/continuous_location.behavior.test.mjs`
Expected: PASS.

### Task 2: 守護人中斷狀態

**Files:**
- Modify: `index.html`
- Test: `tests/continuous_location.behavior.test.mjs`

**Interfaces:**
- Consumes: friend `updated_at`
- Produces: `friendLocationFreshness(updatedAt, now)`

- [ ] **Step 1: Write the failing test**

測試更新後 2 分鐘內顯示即時更新中，超過 2 分鐘顯示定位可能中斷。

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test tests/continuous_location.behavior.test.mjs`
Expected: FAIL because freshness rendering is absent.

- [ ] **Step 3: Write minimal implementation**

在守護人位置卡加入最後更新時間與中斷提示。

- [ ] **Step 4: Run focused and regression tests**

Run: `node --test tests/continuous_location.behavior.test.mjs tests/liff_fast_route.behavior.test.mjs && python -m unittest tests.test_safety_guard`
Expected: PASS.

