# Task 2 independent review — Official-friend and LINE-login gate

## Final verdict

- Spec compliance: **PASS**
- Code quality / security: **PASS**
- Critical findings: 0
- Important findings: 0
- Minor findings: 0

Fix commit `5cef17d` resolves both Important findings and the Minor test gap from review commit `70c4c29`. Task 2 is ready to proceed to the next implementation task.

## Resolution of prior findings

### Important 1 — Authenticated friendship precondition: resolved

- `resolveLineEntryGate()` now calls `isLoggedIn()` first and returns the explicit `"login"` state without calling `getFriendship()` for a logged-out user (`index.html:7789-7798`).
- Only an authenticated session performs the fresh `getFriendship()` check.
- Registration, migration redemption, and member bootstrap remain downstream of a verified `friendFlag === true`.
- The new behavior tests exercise:
  - logged out with `getFriendship()` configured to reject `UNAUTHORIZED`, proving it is not called;
  - logged in/non-friend returning the add-friend state;
  - logged in/friend returning the ready state;
  - non-friend recheck proving profile, registration, migration, and member bootstrap do not run.

This matches the LIFF-supported authentication model while keeping `liff.login()` behind the explicit user button.

### Important 2 — Invite and migration continuation: resolved

- `sanitizeLoginContinuationParams()` now constructs a strict allowlist for:
  - a real LINE user ID-shaped `invite_from`;
  - the production 6–8 character friend invite format;
  - known app route actions;
  - a URL-safe, non-LINE-ID-shaped 32–128 character one-time migration code.
- `startLineLogin()` now passes a same-origin `redirectUri` built from only that validated continuation state (`index.html:5055-5083`).
- OAuth parameters, `friendship_status_changed`, token-like route values, arbitrary keys, malformed invite codes, and identity-shaped migration values are excluded.
- The migration format agrees with production generation: `secrets.token_urlsafe(32)` in `app.py`; the friend-invite format agrees with the 6–8 character generated code in `create_friend_invite()`.
- The behavior test invokes the real login-button handler, inspects the redirect URL, proves invitation/migration/route preservation, and proves forbidden values are absent.

The one-time migration code remains confined to the existing same-origin redemption handoff. Existing redemption removes it from the visible URL before awaiting the response.

### Minor 1 — Recheck orchestration coverage: resolved

The new orchestration test exercises `recheckLineEntryGate()` rather than only the resolver. It proves:

- a fresh friendship check gates every downstream operation;
- no profile, registration, migration, or member bootstrap runs for a non-friend;
- concurrent recheck taps share one in-flight operation;
- registration, migration, and member bootstrap each run once;
- stale generic login guidance is cleared after success;
- the gate is removed only after verification;
- execution order is friendship → registration → migration → member bootstrap.

`friendship_status_changed` is not trusted as proof; the returned page and explicit recheck both execute the real friendship query.

## Additional review notes

- Member identity still comes from `liff.getProfile()` only after successful LIFF authentication and friendship verification.
- The continuation sanitizer does not accept arbitrary member IDs, tokens, or redirects.
- Existing invitee flow, account migration handoff, Task 1 guardian readiness, public LIFF routes, and migration UI tests remain green.
- The unrelated modified `assets/daily-peace-hero.png` is not part of `5cef17d` and remains unstaged.

## Fresh verification evidence

```text
node --test tests/*.test.mjs
34 passed, 0 failed

python -m unittest tests.test_product_rules tests.test_liff_fast_route -v
51 passed, 0 failed

python -m unittest tests.test_bind_and_home_gate -v
38 passed, 0 failed

git diff 70c4c29 5cef17d --check
exit 0

git diff --check
exit 0
```

An additional combined run of `tests.test_bind_and_home_gate tests.test_account_migration` produced 11 `TypeError` errors only in migration tests that call Flask test-client-only `json=` or `query_string=` arguments. This environment reports `Flask is not installed` and uses the fallback `MiniClient`; the same known environment limitation was already recorded before `5cef17d`. All 38 binding/home tests passed in that run, and the failing backend files were not changed by Task 2.
