# Task 5 Report — Legacy and current LIFF migration UX

## Result

- Legacy LIFF initializes `2010674803-rK98c0lo` and authenticates without forwarding query data to `liff.login()`.
- The legacy page starts migration with only its LIFF ID token and forwards only a one-time `migration_code` plus `open`, `page`, or `friend_invite`.
- Old Provider user IDs, `invite_from`, identity tokens, and unexpected parameters are not shown or forwarded.
- The current LIFF redeems after current-channel authentication and before member bootstrap.
- The migration code is removed from the visible URL immediately after the redeem request is created.
- Successful migration refreshes only member data through `loadInitialMemberData()`; it does not reload the page.
- Senior-readable working, success, expiry, used-code, and retry states were added without exposing raw server errors or identifiers.
- Existing no-migration fast routes remain unchanged.

## Verification

- `node --test tests/account_migration_ui.behavior.test.mjs tests/liff_fast_route.behavior.test.mjs`
  - 14 passed, 0 failed.
- `/tmp/alive-checkin-venv/bin/python -m unittest tests.test_liff_fast_route -v`
  - 13 passed, 0 failed.
- `git diff --check`
  - passed.

## Notes

- Legacy guardian invitation links are intentionally not migrated across Providers. A new invitation must be shared from the current LIFF.
- No admin, SOS, pricing, payment, or backend migration files were changed in this task.

## Fix round 1 — Route priority, safe destinations, visible recovery, and plan

### Changes

- A pending `migration_code` now defers every destination route, including public
  redirects, until current-LIFF authentication, redemption, and member refresh
  complete.
- The migration status card is a persistent child of the app shell rather than a
  route-hidden `<section>`, so working, failure, and success states remain visible
  on member, guardian, guard, and history destinations.
- Legacy `open` and `page` values are restricted to a fixed action enum.
  `friend_invite` is restricted to the actual 6–8 character alphanumeric invite
  format. LINE IDs, JWT-like strings, token-like arbitrary values, and long values
  are discarded.
- `used_code` recovery stays in the current Provider and opens the current member
  center; normal bootstrap still refreshes current member data.
- The success summary derives a safe, fixed plan label from the refreshed member
  status and displays it with reminder, check-in, contact, and group counts.
- The original `initApp()` signature is preserved. Already refreshed migration
  data is passed through a one-use internal variable, avoiding a second member
  request without breaking existing callers.

### RED evidence

```text
node --test tests/account_migration_ui.behavior.test.mjs \
  tests/liff_fast_route.behavior.test.mjs

tests 18
pass 13
fail 5

Failures:
- success summary did not contain 進階版
- used-code action pointed to legacy LIFF 2010674803-rK98c0lo
- redirecting bootstrap produced [route] instead of [auth, redeem, member, route]
- migration card was inside a route-hidden section
- token-like open value was forwarded to the current LIFF
```

The first full regression also caught the temporary `initApp(options)` signature
change:

```text
/tmp/alive-checkin-venv/bin/python -m unittest discover -s tests

Ran 273 tests
FAILED (errors=5)

All five errors were existing tests unable to find the required
"async function initApp()" contract.
```

### GREEN evidence

Focused behavior:

```text
node --test tests/account_migration_ui.behavior.test.mjs \
  tests/liff_fast_route.behavior.test.mjs

tests 18
pass 18
fail 0
```

LIFF Python suite:

```text
/tmp/alive-checkin-venv/bin/python -m unittest tests.test_liff_fast_route -v

Ran 13 tests
OK
```

Full regression:

```text
node --test tests/*.test.mjs

tests 20
pass 20
fail 0

/tmp/alive-checkin-venv/bin/python -m unittest discover -s tests

Ran 273 tests
OK
```

### Concerns

None within Task 5 scope.

## Fix round 2 — Executed route visibility and no-code comparison

### Changes

- Replaced the source-position-only card assertion with an executed behavior
  test. It runs the real `showAccountMigrationState()`, `showTab()`, and
  `openMvpGuardPanel()` implementations and verifies working, error, and success
  cards stay visible on member, guardians, guard, and history routes.
- Added an executed no-`migration_code` bootstrap comparison. The original route
  is applied first, authentication and the single normal member bootstrap follow,
  and the migration redemption phase is not called.
- Production bootstrap now calls `redeemPendingAccountMigration()` only when a
  migration code was detected. Migration behavior is unchanged; ordinary fast
  routes avoid an unnecessary migration helper call.

### RED evidence

```text
node --test tests/account_migration_ui.behavior.test.mjs

tests 9
pass 8
fail 1

bootstrap without migration keeps the fast route and skips redemption
actual:   [route, auth, redeem, member, calendar, open]
expected: [route, auth, member, calendar, open]
```

The executed card test passed against the implementation and directly exercised
all required states and routes; it replaced the earlier source-position check.

### GREEN evidence

Focused:

```text
node --test tests/account_migration_ui.behavior.test.mjs \
  tests/liff_fast_route.behavior.test.mjs

tests 19
pass 19
fail 0

/tmp/alive-checkin-venv/bin/python -m unittest tests.test_liff_fast_route -v

Ran 13 tests
OK
```

Full regression:

```text
node --test tests/*.test.mjs

tests 21
pass 21
fail 0

/tmp/alive-checkin-venv/bin/python -m unittest discover -s tests

Ran 273 tests
OK
```

### Concerns

None within Task 5 scope.
