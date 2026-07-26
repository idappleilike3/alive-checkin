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
- Review RED: at exactly 48h15m the status was still pre-alert.
- GREEN: the test proves 48h14m is pre-alert, while exactly 48h15m and 48h16m
  are overdue using one supplied clock.

Added
`OverdueAlertTests.test_due_reminders_take_one_clock_sample_for_selection_and_delivery`.

- RED: `send_due_reminders()` called `admin_summary()` before taking its own
  clock sample and did not pass `now`; nested status helpers also sampled time
  independently.
- GREEN: the overdue sender samples once at entry and calls
  `admin_summary(data_file, config, now=now)`. Status reminder and safety-roster
  calculations receive the same explicit timestamp.

Production fix:

- `build_status(profile, state=None, now=None)` uses one app-local clock for
  deadline, calendar day, and today's check-in status.
- `send_due_reminders()` computes the app clock once at entry and explicitly
  passes it through `admin_summary(..., now=now)` to every status calculation.
- The exact boundary is `deadline < now < alert_at` for pre-alert and
  `now >= alert_at` for overdue.

The three existing target assertions were not weakened or removed. Their stale
fixtures now use a last check-in three days earlier so they exercise actual
overdue target collection.

## Verification

Three requested tests, exact boundary, and single-clock test: 5/5 passed.

Notification channel, commercial overdue, scheduler tick, reminder slots,
Task 4 push-delivery policy, and grace-hour suites: 53/53 passed.

Complete Python suite:

- 203 tests run
- 200 passed
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
