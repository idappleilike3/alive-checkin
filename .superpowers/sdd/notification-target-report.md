# Notification target repair report

Base: `cbcd331`

## Status

DONE

## Root cause

The three target-selection tests all produced `targets=[]` before target
collection ran because their fixtures were not actually overdue:

- `DEFAULT_GRACE_HOURS` is 48 hours.
- `DEFAULT_WARNING_CANCEL_MINUTES` is 15 minutes.
- The fixtures used `last_check_in = now - 2 days`, which is the start of the
  warning-cancellation window, not the overdue state.

The investigation also found a production clock-propagation bug:
`send_due_reminders()` used `CRON_NOW`, but `admin_summary()` called
`build_status()` and `build_status()` used a separate `datetime.now()` plus a
separate current-day lookup. A scheduler tick could therefore select overdue
users using a different clock from the tick itself.

## TDD evidence

Added
`GraceHoursTests.test_status_uses_supplied_now_and_waits_through_cancel_window`.

- RED: `TypeError: build_status() got an unexpected keyword argument 'now'`.
- GREEN: the test proves 48h14m is pre-alert and 48h16m is overdue using one
  supplied clock.

Production fix:

- `build_status(profile, state=None, now=None)` uses one app-local clock for
  deadline, calendar day, and today's check-in status.
- `admin_summary()` computes the app clock once from its config and passes it
  to every status calculation.

The three existing target assertions were not weakened or removed. Their stale
fixtures now use a last check-in three days earlier so they exercise actual
overdue target collection.

## Verification

Focused requested tests plus the new boundary test: 4/4 passed.

Notification channel, commercial overdue, scheduler tick, reminder slots,
Task 4 push-delivery policy, and grace-hour suites: 52/52 passed.

Complete Python suite:

- 202 tests run
- 199 passed
- 3 failed
- Failure count decreased from 6 to 3; no new failure appeared.

Exact remaining failures:

1. `test_bot_keywords.BotKeywordHandlerTests.test_welcome_flex_new_card_two_ctas`
2. `test_bot_keywords.BotKeywordHandlerTests.test_welcome_flex_omits_placeholder_name`
3. `test_product_rules.ProductRulesTests.test_liff_links_use_query_params_for_android_compatibility`

Additional checks:

- `python -m py_compile app.py push_delivery.py`: passed
- `git diff --check`: passed

## Files changed

- `app.py`
- `tests/test_commercial_p0.py`
- `tests/test_notify_channel_prefs.py`
- `tests/test_grace_hours.py`
- `.superpowers/sdd/notification-target-report.md`
