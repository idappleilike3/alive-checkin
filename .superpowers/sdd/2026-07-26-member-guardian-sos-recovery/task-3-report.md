# Task 3 — verified reciprocal guardian binding

## Decision record

- A newly staged guardian invitation is the verification boundary: it stores only the inviter's supplied display name and relationship, expires after seven days, and blocks binding until the recipient sends explicit `recipient_consent`.
- Historical accepted bindings remain readable and bind-compatible so existing deep links and migration state are not invalidated. The new verified path alone creates the second canonical reciprocal contact record.
- The bind route resolves the invitee from authenticated LIFF identity and overwrites request-supplied `contact_line_user_id` in Flask, MiniClient, and fallback HTTP implementations.
- Both profile mutations happen in one loaded-state mutation and a single `save_state` call. Notice delivery happens afterwards; delivery failure is logged per recipient and cannot roll back the persisted reciprocal records.
- Each verified party is marked for private profile-completion reminders. The scheduler retries missed milestones at day 0, day 1, day 3, and day 7, and stops once the profile marks completion not required.

## RED evidence

Added behavior tests before implementation for:

- consent required after a staged invite, with the owner still gated before consent;
- two primary canonical guardian rows after consent;
- independent notification statuses and persistence when the invitee push fails;
- seven-day pending-invite expiry;
- private, due-only completion reminders and stopping after completion.

The required initial focused run was RED because `create_guardian_invite` and `send_profile_completion_reminders` did not exist.

## Changed files

- `app.py`: staged invite state, consent/expiry validation, reciprocal canonical contacts, authenticated bind identity enforcement, per-recipient outcomes, and completion reminder scheduler.
- `index.html`: consent field and complete guardian-purpose/privacy explanation before acceptance.
- `liff/share-invite.html`: share completion guidance now describes the recipient explanation/login/consent path.
- `tests/test_bind_and_home_gate.py`: verified binding regression coverage.
- `tests/test_sos_rules.py`: profile-completion reminder coverage.

## Verification

- `python -m unittest tests.test_bind_and_home_gate.BindAndHomeGateTests.test_verified_pending_invite_needs_consent_then_creates_two_core_records tests.test_bind_and_home_gate.BindAndHomeGateTests.test_verified_bind_keeps_both_records_when_one_notice_fails tests.test_bind_and_home_gate.BindAndHomeGateTests.test_pending_invite_expires_after_seven_days tests.test_sos_rules.SosRulesTests.test_profile_completion_reminders_are_private_due_only_and_stop_when_complete -v` — 4 passed.
- `python -m unittest tests.test_product_rules -v` — 38 passed.
- `python -m unittest tests.test_bind_and_home_gate tests.test_sos_rules -v` — Task 3 tests passed, but six pre-existing SOS tests fail because their fixtures have raw `line_id` contacts without `binding_status=accepted`; Task 1's authoritative readiness gate rejects those as intended.
- `git diff --check` — pending at commit verification.

## Self-review

- Confirmed no change touches `assets/daily-peace-hero.png`.
- Reviewed mutation ordering: contact-capacity rejection happens before `save_state`, so neither side persists on a rejected reciprocal transition.
- The binding completion notices include the private completion CTA text and each LINE attempt is independently logged.
