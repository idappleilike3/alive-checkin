# Task 2 report — Official-friend and LINE-login gate

## Status

Implemented and corrected the LIFF entry gate after independent review `70c4c29`. Logged-out users now reach an explicit one-tap login step without calling an authenticated friendship API. After login, the app performs a fresh `liff.getFriendship()` check; non-friends stop at the Traditional Chinese add-official-account step, while verified friends continue to account migration, server-authoritative guardian readiness, and the requested deep-link route.

## RED evidence

The original RED established the missing entry gate. Review-fix tests were then added first for:

- logged-out LIFF sessions that must not call `getFriendship()`;
- logged-in friendship verification before registration;
- explicit login redirect/return preserving validated invite, migration, and route state;
- exclusion of OAuth, token-like, identity-like misuse, and arbitrary parameters;
- `friendship_status_changed` recheck orchestration, duplicate-tap suppression, error clearing, registration, migration, and member bootstrap order.

The review-fix RED run failed in all four new behaviors:

```text
Error: UNAUTHORIZED
Expected calls ["login", "friendship"], received ["friendship"]
AssertionError: missing function: sanitizeLoginContinuationParams
Expected one profile call, received two
```

## Implementation

- Added an accessible full-screen entry gate with clear Traditional Chinese add-friend and explicit-login steps.
- Changed `resolveLineEntryGate()` to check `liff.isLoggedIn()` first; only authenticated sessions call profile-scoped `liff.getFriendship()`.
- Removed automatic login from `initializeLiff`; `liff.login()` remains behind explicit click/consent actions through `startLineLogin()`.
- Added a same-origin `redirectUri` containing only validated continuation keys: real LINE inviter ID, short friend invite, allowlisted app route, and token-url-safe one-time migration code.
- OAuth parameters, `friendship_status_changed`, arbitrary keys, invalid actions, malformed invite codes, and LINE-user-ID-shaped migration values are excluded.
- Recheck actions rerun LIFF initialization and actual friendship verification; `friendship_status_changed` is never treated as proof.
- Concurrent recheck taps share one in-flight operation, and a successful recheck clears stale generic login guidance before migration/member bootstrap.
- Delayed migration and member bootstrap until the gate is ready, preserving existing migration handoff, deep links, LIFF failure guidance, and Task 1 guardian readiness.
- Kept friendship/login facts out of frontend member/readiness state; the gate stores only the transient UI step.
- Authorization remains server-side; no backend identity/readiness behavior was weakened.

## GREEN evidence

```text
node --test tests/liff_fast_route.behavior.test.mjs
18 passed, 0 failed

python -m unittest tests.test_product_rules
38 passed, 0 failed

node --test tests/*.test.mjs
34 passed, 0 failed

python -m unittest tests.test_product_rules tests.test_liff_fast_route -v
51 passed, 0 failed

python -m unittest tests.test_bind_and_home_gate -v
38 passed, 0 failed

git diff --check
exit 0
```

## Commit

`fix: honor authenticated LIFF entry and continuation`

## Concerns

- Official LIFF behavior requires login before friendship can be known in an external browser. The safe UX therefore shows explicit login first for an unauthenticated user, then shows add-friend only when the authenticated friendship check returns false.
- The one-time migration code remains in the same-origin login return URL only long enough for existing redemption logic to consume and remove it; it is not copied to logs, analytics, or localStorage.
- `assets/daily-peace-hero.png` was already modified and is intentionally not staged or committed.
