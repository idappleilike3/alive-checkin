# Task 2 independent review — Official-friend and LINE-login gate

## Verdict

- Spec compliance: **FAIL**
- Code quality / security: **FAIL**
- Critical findings: 0
- Important findings: 2
- Minor findings: 1

Task 2 must not be accepted yet. The focused and regression tests pass, but the new tests model a friendship result as available before login and therefore do not exercise the real logged-out LIFF failure path.

## Findings

### Important 1 — Logged-out external-browser users cannot reliably reach the explicit login step

**Evidence**

- `index.html:7758-7766` calls `sdk.getFriendship()` before `sdk.isLoggedIn()`.
- The LINE LIFF API requires an access token with the `profile` scope to obtain friendship status. A logged-out external-browser LIFF session does not yet have that authenticated access token. Official reference: <https://developers.line.biz/en/reference/liff/#get-friendship>
- When `getFriendship()` rejects, `initializeLiff()` catches it and calls the generic `showLineLoginRequired()` path instead of returning the `"login"` state (`index.html:7841-7845`, `index.html:7880-7897`). The explicit `lineEntryLoginBtn` is therefore not the reliable path for the exact “friend but logged out” case required by the brief.
- `tests/liff_fast_route.behavior.test.mjs:490-505` mocks `getFriendship()` as succeeding while `isLoggedIn()` is false. That is the unsupported state that hides the production failure.

**Impact**

Opening the LIFF URL from Chrome/Safari while logged out can fail before the ordered entry state is resolved. The user sees generic “use LINE to open” recovery rather than the approved one-tap login gate, and neither the non-friend nor friend/logged-out acceptance paths are proven.

**Required fix**

Model the LIFF-supported state machine rather than assuming friendship can be queried without authentication. Add a behavior test where `isLoggedIn() === false` and `getFriendship()` rejects or must not be called until authentication exists. Keep login user-action-only. Once logged in, perform a fresh `getFriendship()` check before registration, migration, or member bootstrap. If product UX must visually present “add friend first,” make that an unverified instruction step and still require the post-login friendship verification before member work.

### Important 2 — The explicit login action does not preserve invitation or migration handoff state

**Evidence**

- The new login button passes `readSafeDeepLinkParams()` to `startLineLogin()` (`index.html:7811-7814`), but `startLineLogin(extraParams)` ignores `extraParams` whenever LIFF is available and calls bare `liff.login()` (`index.html:5039-5053`).
- LINE documents that a bare `liff.login()` defaults its redirect target to the configured Endpoint URL, not the current URL with business query parameters: <https://developers.line.biz/en/reference/liff/#login>
- `readSafeDeepLinkParams()` only retains `invite_from`, `friend_invite`, and `open`; it does not retain the pending `migration_code` that `resumeMemberBootstrapAfterLineEntry()` expects at `index.html:10450-10454`.
- No Task 2 behavior test clicks the login action, simulates the redirect/return, and proves that `invite_from`, `friend_invite`, `open`, and the one-time migration handoff survive. The static product test only checks that `startLineLogin` exists.

**Impact**

A logged-out invitee can return without the guardian invitation, and a logged-out legacy member can return without the one-time migration code. That violates the explicit requirements to preserve invite deep links and account migration handoff and can route users into a blank/new member flow.

**Required fix**

Preserve only the allowlisted business continuation state across the explicit login round trip using a LINE-supported redirect or a short-lived same-tab/session continuation mechanism. Treat `migration_code` as sensitive, single-use data: do not put it into logs, analytics, localStorage, or arbitrary redirects. Add end-to-end behavior coverage proving that login return restores the invitation/migration continuation and that OAuth/token parameters are still excluded.

### Minor 1 — Recheck coverage does not exercise the recheck/bootstrap orchestration

`tests/liff_fast_route.behavior.test.mjs:508-522` calls `resolveLineEntryGate()` twice, but never calls `recheckLineEntryGate()`. It therefore does not prove that:

- `friendship_status_changed` triggers a fresh check rather than being trusted;
- repeated taps cannot start duplicate initialization/member bootstrap;
- the previously rendered generic login error is cleared after a successful recheck;
- no member API runs until the fresh friendship result is true.

Add an orchestration-level test with spies for LIFF init/profile, registration, migration redemption, and `initApp()`.

## Positive observations

- Member registration, migration redemption, and `initApp()` remain after the new entry gate in the main bootstrap path.
- `liff.login()` is no longer called automatically from `initializeLiff()`.
- The UI copy is Traditional Chinese, accessible labels are present, and the gate hides member content while active.
- The unrelated modified `assets/daily-peace-hero.png` is not part of commit `fcebc20`.

## Verification evidence

Fresh review runs:

```text
node --test tests/liff_fast_route.behavior.test.mjs tests/account_migration_ui.behavior.test.mjs
28 passed, 0 failed

node --test tests/*.test.mjs
33 passed, 0 failed

python -m unittest tests.test_product_rules tests.test_liff_fast_route -v
51 passed, 0 failed

python -m unittest tests.test_bind_and_home_gate -v
38 passed, 0 failed

git diff fcebc20^ fcebc20 --check
exit 0

git diff --check
exit 0
```

Passing tests do not clear the Important findings because the tests do not model the authenticated precondition of `getFriendship()` or the login redirect round trip.
