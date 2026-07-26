# Secure Account Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an existing member prove both the legacy and current LINE identities, then move the complete account to the current Provider without losing data, exposing LINE IDs, or leaving a partially migrated account.

**Architecture:** Add a Provider-aware LINE token verifier, a server-side one-time migration ticket, and one atomic state mutation that snapshots, merges, reindexes, aliases, audits, and consumes the ticket together. The legacy LIFF creates the ticket after verifying the old identity; the current LIFF redeems it after verifying the new identity. The existing whole-state PostgreSQL/SQLite persistence remains the storage boundary, but migration writes use a dedicated lock/transaction path so two requests cannot interleave.

**Tech Stack:** Python 3.11, Flask, PostgreSQL/SQLite JSON state, LINE LIFF SDK, vanilla JavaScript, `unittest`, Node.js `node:test`.

## Global Constraints

- Never infer identity from display name, phone, email, picture, browser storage, or a client-supplied LINE user ID.
- Never put an old/new LINE user ID, ID token, access token, or raw migration code into application logs, admin audit metadata, analytics, or error text.
- Store only a SHA-256 HMAC digest of the migration code; the signing key comes from `ACCOUNT_MIGRATION_SECRET`.
- A ticket is valid for 10 minutes and one successful redemption only.
- A failed migration must leave both accounts, all top-level records, aliases, ticket status, and audit indexes unchanged.
- The old account becomes a disabled alias only after the new account has been saved successfully.
- Existing production entry remains on the current LIFF. The legacy LIFF is only a migration start page.
- This plan does not change SOS, pricing, payments, or the full admin security-center UI. Those remain separate deployable plans.
- Use TDD for every task: write the failing test, run it, implement the minimum code, rerun the focused test, then commit.
- Do not deploy until all Python and Node tests pass and the migration security review finds no secret/identifier leakage.

---

## File and Interface Map

### Modify

- `line_auth.py`
  - Add `verify_line_id_token_for_channel(id_token, channel_id, verify_fn=None)`.
  - Keep `resolve_line_user_id()` unchanged for normal current-LIFF requests.
- `app.py`
  - Add migration configuration, storage defaults, merge helpers, atomic mutation, APIs, and minimal admin-safe status.
  - Add:
    - `create_account_migration_ticket(data_file, old_line_user_id, config, now=None)`
    - `redeem_account_migration_ticket(data_file, code, new_line_user_id, config, now=None)`
    - `merge_migration_profiles(old_profile, new_profile, now=None)`
    - `reindex_account_references(state, old_id, new_id, migration_event_id)`
    - `mutate_state_atomically(data_file, mutator)`
  - Add routes:
    - `POST /api/account-migration/start`
    - `POST /api/account-migration/redeem`
    - `GET /api/account-migration/status`
- `liff/migrate.html`
  - Initialize the legacy LIFF, obtain its ID token, create a migration ticket, and open the current LIFF with only `migration_code`.
- `index.html`
  - Detect `migration_code`, verify current LIFF login, redeem once, show a non-sensitive result summary, then remove the code from the visible URL.
- `admin.html`
  - Add a small read-only “帳號搬家” result card using only event ID, status, time, counts, and safe failure category.
- `render.yaml`
  - Document required `LEGACY_LINE_LOGIN_CHANNEL_ID`, `LEGACY_LIFF_ID`, and `ACCOUNT_MIGRATION_SECRET` environment variables without values.
- `README.md`
  - Replace the old “manual reauthorize only” handoff instructions with the verified two-login migration checklist.
- `HANDOFF.md`
  - Add Render variables, LINE console endpoint order, smoke test, rollback, and 30-day legacy-entry retention instructions.

### Create

- `tests/test_account_migration.py`
  - Backend identity, ticket, merge, atomicity, idempotency, reindex, alias, and audit tests.
- `tests/account_migration_ui.behavior.test.mjs`
  - Legacy/current LIFF behavior, code cleanup, loading/error/success UI, and identifier-leak tests.

### State additions

```python
DEFAULT_STATE.update({
    "account_migration_tickets": {},
    "account_migration_aliases": {},
    "account_migration_audit": [],
    "account_migration_snapshots": {},
})
```

Ticket values:

```python
{
    "ticket_id": "amt_<random>",
    "code_digest": "<hmac-sha256>",
    "old_line_user_id": "<server verified only>",
    "created_at": "<ISO-8601>",
    "expires_at": "<ISO-8601>",
    "used_at": "",
    "status": "pending",
}
```

Audit values exposed to admin:

```python
{
    "event_id": "ame_<random>",
    "status": "success|failed",
    "created_at": "<ISO-8601>",
    "failure_category": "",
    "counts": {
        "checkins": 0,
        "contacts": 0,
        "groups": 0,
        "reminders": 0,
        "orders": 0,
        "requests": 0,
    },
}
```

No audit response may contain `old_line_user_id`, `new_line_user_id`, `code_digest`, or a raw code.

---

### Task 1: Provider-aware token verification and configuration

**Files:**

- Modify: `line_auth.py`
- Modify: `app.py`
- Modify: `render.yaml`
- Test: `tests/test_account_migration.py`

- [ ] **Step 1: Write failing tests for strict channel verification**

Add these tests:

- `test_start_rejects_token_verified_for_current_channel`
- `test_redeem_rejects_token_verified_for_legacy_channel`
- `test_migration_endpoints_fail_closed_when_secret_or_channel_missing`

The verifier stub must record the `client_id` it receives. Assert legacy start uses `2010674803` and current redemption uses `2010848330`.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run:

```bash
python -m unittest tests.test_account_migration.ProviderVerificationTests -v
```

Expected: failures because the migration routes/configuration do not exist.

- [ ] **Step 3: Add explicit migration configuration**

In `create_app()` add:

```python
LEGACY_LINE_LOGIN_CHANNEL_ID=os.environ.get(
    "LEGACY_LINE_LOGIN_CHANNEL_ID", "2010674803"
),
LEGACY_LIFF_ID=os.environ.get(
    "LEGACY_LIFF_ID", "2010674803-rK98c0lo"
),
ACCOUNT_MIGRATION_SECRET=os.environ.get("ACCOUNT_MIGRATION_SECRET", ""),
ACCOUNT_MIGRATION_TTL_SECONDS=600,
```

Add a fail-closed helper:

```python
def account_migration_ready(config):
    return all(str(config.get(key) or "").strip() for key in (
        "LEGACY_LINE_LOGIN_CHANNEL_ID",
        "LINE_LOGIN_CHANNEL_ID",
        "ACCOUNT_MIGRATION_SECRET",
    ))
```

- [ ] **Step 4: Add a channel-explicit token verifier**

In `line_auth.py`:

```python
def verify_line_id_token_for_channel(id_token, channel_id, verify_fn=None):
    verifier = verify_fn or verify_line_id_token
    claims = verifier(str(id_token or "").strip(), str(channel_id or "").strip())
    sub = str((claims or {}).get("sub") or "").strip()
    return sub or None
```

The migration endpoints call this helper directly and never accept a client-claimed ID.

- [ ] **Step 5: Document env var names in `render.yaml`**

Add non-secret declarations. `ACCOUNT_MIGRATION_SECRET` must use `generateValue: true`; do not commit a value.

- [ ] **Step 6: Rerun focused tests**

Run:

```bash
python -m unittest tests.test_account_migration.ProviderVerificationTests -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add line_auth.py app.py render.yaml tests/test_account_migration.py
git commit -m "feat: verify both LINE providers for migration"
```

---

### Task 2: One-time migration tickets

**Files:**

- Modify: `app.py`
- Test: `tests/test_account_migration.py`

- [ ] **Step 1: Write failing ticket lifecycle tests**

Add these tests:

- `test_start_returns_random_code_but_stores_only_digest`
- `test_ticket_expires_after_ten_minutes`
- `test_ticket_cannot_be_redeemed_twice`
- `test_ticket_source_must_still_exist`
- `test_raw_code_and_line_ids_are_absent_from_public_status_and_audit`

Also assert two starts for one account create different raw codes and digests.

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
python -m unittest tests.test_account_migration.TicketLifecycleTests -v
```

- [ ] **Step 3: Add digest and comparison helpers**

Use:

```python
def account_migration_code_digest(code, secret):
    return hmac.new(
        secret.encode("utf-8"),
        code.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
```

Use `secrets.token_urlsafe(32)` for the raw code and `secrets.compare_digest()` for matching.

- [ ] **Step 4: Add ticket creation**

`create_account_migration_ticket()` must:

1. Load state.
2. Require an existing, non-aliased old profile.
3. Expire any prior pending tickets for that old identity.
4. Store only the digest and server-verified old ID.
5. Return `{ok, migration_code, expires_in: 600}`.

Do not return the ticket’s old user ID.

- [ ] **Step 5: Add start API**

Request:

```http
POST /api/account-migration/start
Authorization: Bearer <legacy id_token>
Content-Type: application/json

{}
```

Responses:

- `200`: code and expiry only.
- `401`: invalid legacy token.
- `404`: legacy account not found.
- `503`: migration configuration unavailable.

Add `Cache-Control: no-store` to every migration API response.

- [ ] **Step 6: Add safe status serialization**

Expose only:

```python
{
    "ok": True,
    "configured": True,
    "pending": True,
    "expires_in": 420,
}
```

Never accept or return a LINE ID in `GET /api/account-migration/status`.

- [ ] **Step 7: Rerun tests**

Run:

```bash
python -m unittest tests.test_account_migration.TicketLifecycleTests -v
```

- [ ] **Step 8: Commit**

```bash
git add app.py tests/test_account_migration.py
git commit -m "feat: issue single-use account migration tickets"
```

---

### Task 3: Deterministic profile merge and reference reindexing

**Files:**

- Modify: `app.py`
- Test: `tests/test_account_migration.py`

- [ ] **Step 1: Write failing merge tests**

Cover:

- `test_blank_new_profile_is_replaced_by_complete_old_profile`
- `test_nonblank_profiles_merge_without_duplicate_business_ids`
- `test_newer_preferences_win_but_higher_active_entitlement_is_preserved`
- `test_expired_location_is_not_moved`
- `test_all_top_level_owner_references_are_reindexed`
- `test_same_old_and_new_identity_is_rejected`

Fixtures must include:

- `history`, `contacts`, `smart_reminders`, `calendar_notes`, `friends`
- `guardian_group_ids` and top-level `guardian_groups`
- `orders`, `support_tickets`, privacy requests, notification/SOS logs
- active and expired location sessions

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
python -m unittest tests.test_account_migration.ProfileMergeTests -v
```

- [ ] **Step 3: Add stable-key collection merging**

Use explicit keys:

| Record | Deduplication key |
|---|---|
| Check-in history | normalized calendar date |
| Contacts | `id`, then accepted invite ID; never name |
| Smart reminders | `id` |
| Calendar notes | `id` |
| Guardian groups | `group_id` |
| Orders | merchant/order ID |
| Support/privacy | request/ticket ID |
| Notification/SOS logs | event/log ID |

If a legacy record lacks a stable ID, preserve both records and assign a new internal ID; do not guess equivalence.

- [ ] **Step 4: Add entitlement and preference rules**

Implement:

```python
PLAN_RANK = {
    "trial": 0,
    "paid_199": 1,
    "paid_199_year": 1,
    "paid_399": 2,
    "paid_399_year": 2,
    "paid_799": 3,
    "paid_799_year": 3,
}
```

Choose the highest still-active entitlement; when ranks match, keep the later expiry. For preferences with `updated_at`, choose the later record. If neither side has timestamps, legacy profile remains authoritative.

- [ ] **Step 5: Add complete reference reindexing**

`reindex_account_references()` must replace only exact owner/member fields, including:

- guardian group `owner_line_user_id`, admins, and member lists
- contact peer bindings on other profiles
- friend invite owner/acceptor fields
- orders and payment linkage
- support and privacy request ownership
- notification, check-in warning, SOS, and location grant indexes

Append `migration_event_id`; do not rewrite human-readable historical message text.

- [ ] **Step 6: Add disabled alias handling**

Store:

```python
state["account_migration_aliases"][old_id] = {
    "target_line_user_id": new_id,
    "created_at": now_iso,
    "status": "disabled",
}
```

Update profile lookup/registration so an old alias cannot create a new blank user. It must return a safe `account_migrated` result that asks the user to open the current LIFF; never return the target LINE ID.

- [ ] **Step 7: Rerun focused tests**

Run:

```bash
python -m unittest tests.test_account_migration.ProfileMergeTests -v
```

- [ ] **Step 8: Commit**

```bash
git add app.py tests/test_account_migration.py
git commit -m "feat: merge and reindex migrated member data"
```

---

### Task 4: Atomic redemption, rollback snapshot, and safe audit

**Files:**

- Modify: `app.py`
- Test: `tests/test_account_migration.py`

- [ ] **Step 1: Write failing concurrency and rollback tests**

Add:

- `test_redeem_is_atomic_and_marks_ticket_used_in_same_write`
- `test_save_failure_restores_old_and_new_accounts`
- `test_two_parallel_redemptions_produce_exactly_one_success`
- `test_success_snapshot_is_retained_for_thirty_days`
- `test_admin_audit_contains_counts_but_no_identity_or_code`

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
python -m unittest tests.test_account_migration.AtomicRedemptionTests -v
```

- [ ] **Step 3: Add an atomic state mutation boundary**

For PostgreSQL:

```sql
BEGIN;
SELECT value FROM kv_store WHERE key = 'default' FOR UPDATE;
-- run mutator against a deep copy
UPDATE kv_store SET value = %s, updated_at = NOW() WHERE key = 'default';
COMMIT;
```

For SQLite:

```sql
BEGIN IMMEDIATE;
SELECT value FROM kv_store WHERE key = 'default';
-- run mutator against a deep copy
INSERT OR REPLACE INTO kv_store (key, value, updated_at)
VALUES ('default', :payload, datetime('now'));
COMMIT;
```

Rollback on any exception. Do not call `load_state()` followed later by `save_state()` for redemption.

- [ ] **Step 4: Add sanitized rollback snapshots**

Before mutation, store a copy under a random snapshot ID with:

- old profile
- pre-existing new profile, if any
- affected top-level records
- creation and purge-after timestamps

The snapshot stays server-side and is never returned by the public API. Mark successful snapshots for purge after 30 days. A failed transaction must not leave a snapshot record behind.

- [ ] **Step 5: Add redemption logic**

Within one mutator:

1. Locate pending ticket by constant-time digest comparison.
2. Reject expired/used/same-ID/missing-source cases.
3. Generate migration event ID.
4. Create snapshot.
5. Merge profiles.
6. Reindex references.
7. Replace user map key with current ID.
8. Add disabled alias.
9. Mark ticket used.
10. Append sanitized audit.
11. Return only counts and user-facing status.

- [ ] **Step 6: Add redeem API**

Request:

```http
POST /api/account-migration/redeem
Authorization: Bearer <current id_token>
Content-Type: application/json

{"migration_code": "<single-use-code>"}
```

Success response:

```python
{
    "ok": True,
    "status": "migrated",
    "counts": {
        "checkins": 21,
        "contacts": 5,
        "groups": 1,
        "reminders": 3,
        "orders": 1,
        "requests": 0,
    },
}
```

Error responses use fixed categories such as `expired_code`, `used_code`, `source_missing`, and `unsafe_conflict`; no IDs.

- [ ] **Step 7: Add snapshot retention maintenance**

Extend the existing scheduler maintenance task to purge migration snapshots only when `purge_after <= now`. Add a test proving a 29-day snapshot remains and a 31-day snapshot is removed.

- [ ] **Step 8: Rerun focused tests**

Run:

```bash
python -m unittest tests.test_account_migration.AtomicRedemptionTests -v
```

- [ ] **Step 9: Commit**

```bash
git add app.py tests/test_account_migration.py
git commit -m "feat: redeem account migration atomically"
```

---

### Task 5: Legacy and current LIFF user experience

**Files:**

- Modify: `liff/migrate.html`
- Modify: `index.html`
- Create: `tests/account_migration_ui.behavior.test.mjs`
- Modify: `tests/liff_fast_route.behavior.test.mjs`
- Modify: `tests/test_liff_fast_route.py`

- [ ] **Step 1: Write failing legacy-page behavior tests**

Test:

- legacy SDK initializes with `2010674803-rK98c0lo`
- unauthenticated users call `liff.login()` without leaking query parameters
- authenticated users send only the legacy ID token to `/api/account-migration/start`
- next link contains `migration_code` plus the allowlisted destination action
- no old LINE ID or ID token appears in DOM text or link URL
- buttons lock during submission and can retry after a safe error

Run:

```bash
node --test tests/account_migration_ui.behavior.test.mjs
```

- [ ] **Step 2: Replace the legacy handoff page**

Add the official LIFF SDK and a state machine:

```text
準備登入 → 驗證舊帳號 → 產生搬家碼 → 開啟新版 → 安全錯誤／重試
```

Preserve only `open`, `page`, and `friend_invite`. Do not preserve old `invite_from`; legacy guardian invitations must be recreated in the current Provider.

- [ ] **Step 3: Write failing current-LIFF redemption tests**

Test:

- bootstrap detects `migration_code` after current LIFF authentication
- redemption waits for a current `getIDToken()`
- code is removed with `history.replaceState()` immediately after request creation
- success card displays plan/reminder/check-in/contact/group counts only
- expired/used codes show the correct recovery action
- normal users without a migration code follow the existing fast route unchanged

- [ ] **Step 4: Implement current-LIFF redemption**

Add a pre-member-bootstrap migration phase in `index.html`:

```javascript
async function redeemPendingAccountMigration() {
  const code = getAppParam("migration_code");
  if (!code) return { attempted: false };
  const idToken = liff.getIDToken();
  removeMigrationCodeFromVisibleUrl();
  return fetch("/api/account-migration/redeem", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${idToken}`,
    },
    body: JSON.stringify({ migration_code: code }),
  });
}
```

After success, rerun only `loadInitialMemberData()`; do not reload the whole LIFF page.

- [ ] **Step 5: Preserve fast-route behavior**

Run:

```bash
node --test tests/account_migration_ui.behavior.test.mjs tests/liff_fast_route.behavior.test.mjs
python -m unittest tests.test_liff_fast_route -v
```

- [ ] **Step 6: Commit**

```bash
git add liff/migrate.html index.html tests/account_migration_ui.behavior.test.mjs tests/liff_fast_route.behavior.test.mjs tests/test_liff_fast_route.py
git commit -m "feat: guide members through verified LIFF migration"
```

---

### Task 6: Minimal admin visibility and operational handoff

**Files:**

- Modify: `app.py`
- Modify: `admin.html`
- Modify: `tests/test_admin_session_auth.py`
- Modify: `tests/admin_auth_ui.test.mjs`
- Modify: `README.md`
- Modify: `HANDOFF.md`

- [ ] **Step 1: Write failing admin authorization and redaction tests**

Assert:

- unauthenticated reads return `401`
- authenticated reads return only safe audit fields
- no user IDs, token digests, or raw codes appear
- admin UI escapes all server text

- [ ] **Step 2: Add read-only admin migration endpoint**

Add:

```http
GET /api/admin/account-migrations
```

Require `_admin_guard()`. Return total/success/failed/pending counts and the latest sanitized events. Do not add an admin “force merge” endpoint.

- [ ] **Step 3: Add compact admin card**

Display:

- configured/not configured
- successful/failed/pending totals
- last attempt time
- safe failure category
- moved record counts

Do not expose snapshots or aliases.

- [ ] **Step 4: Update operator documents**

`HANDOFF.md` must list:

1. Deploy backend support first.
2. Set `ACCOUNT_MIGRATION_SECRET`.
3. Confirm current and legacy channel IDs.
4. Point legacy LIFF endpoint to `/liff/migrate.html`.
5. Test with one non-production member.
6. Confirm audit counts and old-alias behavior.
7. Keep legacy LIFF for at least 30 days.
8. Roll back by restoring the prior deploy; do not delete migration state.

- [ ] **Step 5: Run focused admin tests**

Run:

```bash
python -m unittest tests.test_admin_session_auth -v
node --test tests/admin_auth_ui.test.mjs
```

- [ ] **Step 6: Commit**

```bash
git add app.py admin.html tests/test_admin_session_auth.py tests/admin_auth_ui.test.mjs README.md HANDOFF.md
git commit -m "feat: expose safe account migration operations status"
```

---

### Task 7: Full verification, security review, and deploy gate

**Files:**

- Review all files changed by Tasks 1–6.

- [ ] **Step 1: Run all automated tests**

Run:

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
node --test tests/*.test.mjs
```

Expected: zero failures and zero errors.

- [ ] **Step 2: Run secret and legacy-ID leak checks**

Run:

```bash
rg -n "migration_code|code_digest|old_line_user_id|new_line_user_id" \
  app.py admin.html index.html liff/migrate.html tests
rg -n "2010674803-rK98c0lo" \
  index.html liff/*.html assets/*.json line-rich-menu-config.json
```

Review every hit. The legacy LIFF ID may appear only in migration configuration/page/tests/docs. Raw codes or LINE IDs may not be logged or serialized into admin/public responses.

- [ ] **Step 3: Verify production persistence prerequisites without mutation**

Before deployment:

```bash
curl -fsS https://alive-checkin.onrender.com/health
```

Require:

```json
{
  "ok": true,
  "persistence": {
    "backend": "postgres",
    "database_url_configured": true,
    "durable": true
  }
}
```

If any value differs, stop deployment.

- [ ] **Step 4: Perform manual two-account staging smoke test**

Use a designated test member:

1. Record old account plan, reminder, check-in, contacts, groups, and order counts.
2. Open legacy LIFF and create a ticket.
3. Open current LIFF and redeem.
4. Confirm displayed counts equal the recorded counts.
5. Confirm current account can check in and open member center.
6. Confirm the legacy LIFF cannot recreate a blank duplicate.
7. Confirm a second redemption reports “already used.”
8. Confirm admin audit shows no IDs or code.

- [ ] **Step 5: Review diff and request code review**

Run:

```bash
git status --short
git diff --check
git log --oneline --decorate -12
```

Use `superpowers:requesting-code-review`. Address all high/critical findings, rerun the full suite, and do not publish while review is unresolved.

- [ ] **Step 6: Create PR without merging**

Push the implementation branch and open a draft PR titled:

```text
feat: add secure cross-Provider account migration
```

The PR description must include:

- migration security model
- data categories moved
- merge/conflict rules
- automated test evidence
- manual staging evidence
- required Render variables
- deployment and rollback order

Do not merge or deploy until the user approves the PR checkpoint.

---

## Self-Review Checklist

- [ ] Every requirement in `docs/superpowers/specs/2026-07-26-liff-provider-migration-design.md` maps to a task or is explicitly deferred.
- [ ] No task uses display name, phone, email, or picture for identity.
- [ ] Start and redeem each verify against the correct LINE channel.
- [ ] Ticket expiry, one-time use, same-ID rejection, and missing-source behavior are tested.
- [ ] Merge keys are explicit for every collection.
- [ ] Paid entitlement preservation and preference timestamp rules are deterministic.
- [ ] Atomicity is real at the database boundary, not only an in-process Python lock.
- [ ] Failed writes leave no alias, consumed ticket, snapshot, audit, or half-moved records.
- [ ] Public/admin responses and logs contain no IDs, raw codes, or token material.
- [ ] Legacy IDs cannot recreate blank accounts after migration.
- [ ] Existing normal LIFF login and fast-route behavior remain covered.
- [ ] No TODO, placeholder implementation, or unhandled test skip remains.
