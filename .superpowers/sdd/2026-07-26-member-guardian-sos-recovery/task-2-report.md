# Task 2 report — Official-friend and LINE-login gate

## Status

Implemented the ordered LIFF entry gate. The app now checks the actual LIFF friendship status before login or member work. Non-friends see only the Traditional Chinese official-account add-friend step; friends who are logged out see an explicit one-tap LINE login button. Only friends who are already logged in continue to account migration, server-authoritative guardian readiness, and the requested deep-link route.

## RED evidence

Added behavior coverage first in `tests/liff_fast_route.behavior.test.mjs` for:

- friendship before login, including stopping before `isLoggedIn()` for a non-friend;
- all ordered states: non-friend, friend/logged-out, and friend/logged-in;
- a returned add-friend flow that performs a fresh `getFriendship()` check instead of trusting a link-open event.

The first focused run failed as expected because `resolveLineEntryGate` did not yet exist:

```text
AssertionError: missing function: resolveLineEntryGate
```

The combined focused Node/product command stopped after those three Node RED failures, before invoking the product-rule command.

## Implementation

- Added an accessible full-screen entry gate with clear Traditional Chinese add-friend and explicit-login steps.
- Added `resolveLineEntryGate()` to call `liff.getFriendship()` first, then `liff.isLoggedIn()` only for a confirmed friend.
- Removed automatic login from `initializeLiff`; `liff.login()` remains behind explicit click/consent actions through `startLineLogin()`.
- Recheck actions perform fresh LIFF friendship checks; `friendship_status_changed` is never treated as proof by itself.
- Delayed migration and member bootstrap until the gate is ready, preserving existing migration handoff, deep links, LIFF failure guidance, and Task 1 guardian readiness.
- Kept friendship/login facts out of frontend member/readiness state; the gate stores only the transient UI step.

## GREEN evidence

```text
node --test tests/liff_fast_route.behavior.test.mjs
17 passed, 0 failed

python -m unittest tests.test_product_rules
38 passed, 0 failed

node --test tests/*.mjs
33 passed, 0 failed

git diff --check
exit 0
```

## Commit

`feat: gate onboarding by LINE friendship and login`

## Concerns

- `python -m unittest discover -s tests -p 'test_*.py'` is not clean in this environment: Flask is unavailable, so the fallback `MiniClient` lacks `json` and `query_string` arguments. The run produced 25 errors and 15 failures in unrelated backend/admin/SOS tests. This task does not change backend code; the focused product-rule suite passed.
- `assets/daily-peace-hero.png` was already modified and is intentionally not staged or committed.
