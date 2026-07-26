# 每日平安封閉測試與會員體驗 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 取消邀請延長與永久免費方案，加入一次性 14 天正式體驗、40 人 21 天封閉測試後台，以及到期暫停與依申請解除／刪除流程。

**Architecture:** 保留內部 `free` 作為相容的未訂閱狀態，以 `membership_source` 區分正式試用、過渡試用、封閉測試、付款與到期。封測沿用現有方案權益，但以獨立欄位與稽核紀錄標示，不建立假訂單。所有時間流程由既有單一 Cron tick 冪等執行。

**Tech Stack:** Python、Flask、現有 JSON/Postgres 狀態儲存、原生 HTML/JavaScript、Python unittest。

## Global Constraints

- 不修改 `main`，只在 `codex/phase2-implementation` 工作。
- 不建立假付款訂單，也不自動扣款。
- 邀請核心守護人不增加體驗天數。
- 新會員正式體驗固定 14 天且只能領取一次。
- 封閉測試固定 21 天；A 10 人、B399 20 人、B799 10 人。
- `free` 只作內部未訂閱相容狀態，UI 不得宣傳永久免費方案。
- 到期後守護關係暫停但不自動刪除；會員或關係人可申請解除／刪除，會員刪除帳號時清除個資，法令或帳務紀錄除外。
- 每個任務先看見測試正確失敗，再做最小修正。

---

### Task 1: 一次性 14 天體驗與取消邀請延長

**Files:**
- Modify: `app.py` defaults and trial helpers
- Modify: `tests/test_invite_reward_retain.py`
- Modify: `tests/test_bind_and_home_gate.py`
- Create: `tests/test_membership_trial_policy.py`

**Interfaces:**
- Produces: `ensure_membership_trial(profile, now=None, source="public_trial") -> bool`
- Produces: `membership_access_active(profile, now=None) -> bool`
- Preserves: `trial_bonus_days(profile) -> int`, but always returns `0`

- [ ] **Step 1: Write failing policy tests**

Add tests proving that a new member receives exactly 14 days once, a second registration does not restart it, existing `free` members receive one transition grant, and first/second guardian invitations keep `trial_bonus_days == 0`.

- [ ] **Step 2: Verify RED**

Run:

```powershell
python -m unittest tests.test_membership_trial_policy tests.test_invite_reward_retain tests.test_bind_and_home_gate -v
```

Expected: failures show the current 7-day base, invite reward accumulation and `free` downgrade behavior.

- [ ] **Step 3: Implement the minimum policy**

Use a versioned one-time grant:

```python
PUBLIC_TRIAL_DAYS = 14
TRIAL_POLICY_VERSION = "2026-07-no-invite-reward-v1"

def ensure_membership_trial(profile, now=None, source="public_trial"):
    now = now or datetime.now()
    if profile.get("trial_policy_version") == TRIAL_POLICY_VERSION:
        return False
    profile["membership_source"] = source
    profile["trial_started_at"] = now.isoformat(timespec="seconds")
    profile["trial_end"] = (now + timedelta(days=PUBLIC_TRIAL_DAYS)).isoformat(timespec="seconds")
    profile["trial_policy_version"] = TRIAL_POLICY_VERSION
    profile["trial_bonus_days"] = 0
    profile["plan"] = "trial"
    return True
```

Remove invite-time mutation of trial dates. Keep returned compatibility fields at zero so older clients do not crash.

- [ ] **Step 4: Verify GREEN and regression**

Run the focused command from Step 2, then:

```powershell
python -m unittest discover -s tests
```

Expected: all invitation/trial tests pass; no new failures.

- [ ] **Step 5: Commit**

```powershell
git add app.py tests/test_membership_trial_policy.py tests/test_invite_reward_retain.py tests/test_bind_and_home_gate.py
git commit -m "feat(membership): add one-time fourteen-day trial"
```

---

### Task 2: 封閉測試資格與人數上限

**Files:**
- Modify: `app.py`
- Create: `tests/test_beta_cohort_admin.py`

**Interfaces:**
- Produces: `BETA_COHORT_LIMITS = {"A": 10, "B399": 20, "B799": 10}`
- Produces: `assign_beta_cohort(state, line_user_id, cohort, now=None) -> dict`
- Produces: `beta_access_active(profile, now=None) -> bool`
- Produces: `POST /api/admin/beta-members`
- Produces: `DELETE /api/admin/beta-members/<line_user_id>`

- [ ] **Step 1: Write failing backend tests**

Cover correct 21-day dates, tier mapping, `membership_source=beta`, no order creation, cohort caps, duplicate idempotency, revoke behavior, admin session/CSRF and audit entries.
另覆蓋第二批釋出節奏：第一天最多啟用 10 人；完成健康檢查後，第二天才可開放其餘 20 人。

- [ ] **Step 2: Verify RED**

```powershell
python -m unittest tests.test_beta_cohort_admin -v
```

Expected: routes and helpers do not exist.

- [ ] **Step 3: Implement cohort assignment**

Map:

```python
BETA_COHORT_PLAN = {
    "A": "paid_799",
    "B399": "paid_399",
    "B799": "paid_799",
}
```

Write `beta_started_at`, `beta_ends_at`, recruitment source and feedback status. Do not append to `orders`.

- [ ] **Step 4: Verify GREEN and security regression**

```powershell
python -m unittest tests.test_beta_cohort_admin tests.test_admin_session_auth -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add app.py tests/test_beta_cohort_admin.py
git commit -m "feat(admin): manage beta cohorts"
```

---

### Task 3: 後台封測名單與進度

**Files:**
- Modify: `admin.html`
- Create: `tests/admin_beta_ui.test.mjs`
- Modify: `tests/test_beta_cohort_admin.py`

**Interfaces:**
- Consumes: Task 2 admin beta APIs
- Produces: cohort counters, filters, assignment form and member progress rows

- [ ] **Step 1: Write failing UI behavior tests**

Execute the production `admin.html` script with Node `vm`. Assert A/B399/B799 counters, limit errors, remaining days, source, assigned tier, guardian count, reminder setup, push result, SOS test and feedback status.

- [ ] **Step 2: Verify RED**

```powershell
node --test tests/admin_beta_ui.test.mjs
```

Expected: beta controls are missing.

- [ ] **Step 3: Implement the admin panel**

Add a protected section titled「21 天封閉測試名單」with:

- A `x/10`
- B399 `x/20`
- B799 `x/10`
- member assignment/removal controls
- source and feedback filters
- start/end/remaining-day display
- explicit「不會建立訂單、不會自動扣款」notice

Use existing `adminFetch()` for every request.

- [ ] **Step 4: Verify GREEN**

```powershell
node --test tests/admin_beta_ui.test.mjs tests/admin_auth_ui.test.mjs
python -m unittest tests.test_beta_cohort_admin tests.test_admin_session_auth -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add admin.html tests/admin_beta_ui.test.mjs tests/test_beta_cohort_admin.py
git commit -m "feat(admin): show beta cohort progress"
```

---

### Task 4: 體驗提醒、到期暫停與隱私權申請

**Files:**
- Modify: `app.py`
- Modify: `liff/index.html`
- Modify: `privacy.html`
- Modify: `tests/test_scheduler_tick.py`
- Modify: `tests/test_invite_reward_retain.py`
- Create: `tests/test_membership_retention_policy.py`

**Interfaces:**
- Produces: `send_trial_milestone_notices(data_file=None, now=None) -> dict`
- Produces: `pause_expired_memberships(data_file=None, now=None) -> dict`
- Produces: `process_verified_privacy_request(data_file, line_user_id, request_type) -> dict`
- Consumes: existing `run_cron_tick()` daily membership slot

- [ ] **Step 1: Write failing timeline tests**

Cover notices at day 7/12/14, no duplicate notice, expiry pausing scheduled check-in/guardian notifications and paid location, basic SOS remaining available, renewal restoring contacts, and no automatic deletion. Cover verified member/guardian/contact deletion or unlink requests, account deletion with accounting-record exceptions, and idempotent processing.

- [ ] **Step 2: Verify RED**

```powershell
python -m unittest tests.test_membership_retention_policy tests.test_scheduler_tick tests.test_invite_reward_retain -v
```

Expected: milestone notices, paused relationship state and long-inactivity cleanup are missing.

- [ ] **Step 3: Implement idempotent timeline processing**

Persist sent milestone keys on each profile. Expiry changes relationships to paused and renewal restores them. Only a verified request, invalid collection, or legal requirement may remove personal data; retain only minimal audit metadata required by law or accounting.

Remove the member-center「我的資料管理」section and its three direct buttons. Show the verified privacy-request contact path instead; do not remove the protected backend capability needed to fulfill legal requests.

- [ ] **Step 4: Verify GREEN and full regression**

```powershell
python -m unittest tests.test_membership_retention_policy tests.test_scheduler_tick tests.test_invite_reward_retain -v
python -m unittest discover -s tests
```

Expected: all new tests pass and the old invite-reward failures are gone under the new no-extension policy.

- [ ] **Step 5: Commit**

```powershell
git add app.py tests/test_membership_retention_policy.py tests/test_scheduler_tick.py tests/test_invite_reward_retain.py
git commit -m "feat(membership): enforce expiry and retention timeline"
```

---

### Task 5: 公開與後台文案同步、完整驗證

**Files:**
- Modify: `admin.html`
- Modify: `liff/pricing.html`
- Modify: `faq.html`
- Modify: `guardian_group_flex.py`
- Modify: `assets/welcome_message.json`
- Modify: product-rule tests that explicitly describe the old public free/invite reward policy
- Modify: `README.md`

**Interfaces:**
- Preserves: 199／399／799 prices
- Replaces: public「免費方案」「邀請 +7 天」copy with「一次 14 天體驗」

- [ ] **Step 1: Add failing copy and flow tests**

Assert that public pages do not advertise a permanent free plan or invite extension; welcome copy says 14 days; expired state displays「未訂閱」; pricing shows no automatic billing.

- [ ] **Step 2: Verify RED**

```powershell
python -m unittest tests.test_product_rules tests.test_bot_keywords -v
```

Expected: old 7-day/free copy still exists.

- [ ] **Step 3: Update production copy and status labels**

Use:

- 「新會員可享一次 14 天安心體驗」
- 「體驗到期不會自動扣款」
- 「到期後可自行選擇 199／399／799」
- 「未訂閱」instead of public-facing「免費方案」

- [ ] **Step 4: Run final verification**

```powershell
python -m py_compile app.py push_delivery.py
python -m unittest discover -s tests
node --test tests/admin_auth_ui.test.mjs tests/admin_beta_ui.test.mjs
git diff --check
```

Expected: zero unexpected failures. Any remaining failure must be listed by exact name and resolved before deployment.

- [ ] **Step 5: Commit**

```powershell
git add admin.html liff/pricing.html faq.html guardian_group_flex.py assets/welcome_message.json README.md tests
git commit -m "docs(membership): publish trial and beta policy"
```

---

### Task 6: 399 體驗權益、一次守護群流程與測試限額

**Files:**
- Modify: `app.py`
- Modify: `guardian_group_flex.py`
- Modify: `liff/index.html`
- Create: `tests/test_trial_entitlements.py`

**Interfaces:**
- Produces: `effective_entitlement_plan(profile, now=None) -> str`
- Produces: `claim_trial_group_test(profile, group_id, now=None) -> dict`
- Produces: `consume_labeled_test_action(profile, action, now=None) -> dict`
- Preserves: real SOS safety behavior

- [ ] **Step 1: Write failing entitlement tests**

Cover active public/transition trial receiving 399 core entitlements, trial not receiving normal 799 rights, one labeled guardian-group test notification, second group-test refusal, and daily/cooldown limits for explicit SOS/location/push test actions.

- [ ] **Step 2: Verify RED**

```powershell
python -m unittest tests.test_trial_entitlements -v
```

Expected: trial still inherits the legacy free entitlement and has no one-time group-test ledger.

- [ ] **Step 3: Implement minimum entitlement overlay**

Keep `plan="trial"` for membership state and return `paid_399` only from `effective_entitlement_plan()` while the trial is active. The one-time 799 flow may bind one test group and send one message beginning with「這是測試通知」; it must not unlock normal 799 schedules or ongoing group notifications.

Explicit test actions use:

- SOS test: at most 2 per day, at least 10 minutes apart.
- Location test: at most 2 per day, at least 10 minutes apart.
- Push test: at most 2 per day, at least 10 minutes apart.

These limits apply only to labeled test actions. Existing real SOS protections and emergency access remain unchanged.

- [ ] **Step 4: Verify GREEN and safety regression**

```powershell
python -m unittest tests.test_trial_entitlements tests.test_sos_rules tests.test_safety_guard -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add app.py guardian_group_flex.py liff/index.html tests/test_trial_entitlements.py
git commit -m "feat(trial): grant bounded 399 experience"
```

---

### Task 7: 上線量化門檻與第二批分段開放

**Files:**
- Modify: `app.py`
- Modify: `admin.html`
- Create: `tests/test_launch_readiness.py`
- Create: `tests/admin_launch_readiness_ui.test.mjs`

**Interfaces:**
- Produces: `launch_readiness_snapshot(state, now=None) -> dict`
- Produces: `beta_release_allowed(state, requested_count, now=None) -> tuple[bool, str]`
- Produces: `GET /api/admin/launch-readiness`

- [ ] **Step 1: Write failing metrics tests**

Create state fixtures for check-in success, expected reminder dispatches, duplicate alerts, SOS test outcomes, guardian binding attempts, payment/cancel/expiry cases and push failure logs. Assert the exact launch thresholds from the spec.

- [ ] **Step 2: Verify RED**

```powershell
python -m unittest tests.test_launch_readiness -v
```

Expected: readiness snapshot and staged-release guard do not exist.

- [ ] **Step 3: Implement metrics and hard gate**

Return at least:

```python
{
    "checkin_success_rate": 0.99,
    "missed_required_reminders": 0,
    "duplicate_alerts": 0,
    "sos_test_success_rate": 1.0,
    "guardian_bind_success_rate": 0.95,
    "payment_flow_passed": True,
    "expiry_flow_passed": True,
    "push_failures": [],
    "critical_notification_miss": False,
    "ready": True,
}
```

The second batch may release only 10 people initially. The remaining 20 require a later calendar day, no critical notification miss, and all current readiness gates passing. A critical miss immediately blocks further activation.

- [ ] **Step 4: Add the protected admin panel**

Display every metric, its target, pass/fail state, the latest push failure reason, and a clear「停止新增測試者」banner when blocked. Use existing session/CSRF protections.

- [ ] **Step 5: Verify backend and UI behavior**

```powershell
python -m unittest tests.test_launch_readiness tests.test_beta_cohort_admin -v
node --test tests/admin_launch_readiness_ui.test.mjs tests/admin_auth_ui.test.mjs
```

Expected: all pass, including a simulated notification miss blocking the next 20 users.

- [ ] **Step 6: Commit**

```powershell
git add app.py admin.html tests/test_launch_readiness.py tests/admin_launch_readiness_ui.test.mjs
git commit -m "feat(admin): gate beta rollout on readiness"
```
