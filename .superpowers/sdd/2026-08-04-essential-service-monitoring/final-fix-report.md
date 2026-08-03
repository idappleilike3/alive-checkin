# Essential service monitoring final-fix report

Date: 2026-08-04
Branch: `feature/essential-service-monitoring`
Implementation commit: `53d4aba` (`Fix essential service monitoring review findings`)

## Scope completed

- Added validated, persisted, API-visible, and editable `category`, `billing_cycle`, `currency`, `original_amount`, and `next_renewal_on` fields with legacy alias backfill.
- Made the first dashboard GET atomically persist one timestamped Render seed and exactly one create audit.
- Derived generic annual budgets from `monthly_twd * 12`; retained Render's approved NT$2,500 through `annual_budget_override`.
- Passed `current_app_time(config)` through finance dashboard and mutations, and changed finance UI defaults to browser-local calendar fields.
- Added deterministic one-per-node reminder history with `missed`, `due`, `upcoming`, and paid `suppressed` states; the UI labels passed nodes `已錯過`.

## RED evidence

- `python -m unittest tests.test_finance_admin.EssentialServiceTests -v`
  - 15 tests ran; 6 failures and 5 errors.
  - Expected causes: absent canonical fields, no annual derivation/blank validation, no reminder history, and no seed audit timestamp.
- `python -m unittest tests.test_finance_api.FinancePersistenceHelperTests -v`
  - 2 errors.
  - Expected cause: missing `persisted_finance_dashboard` atomic helper.
- `node --test tests/admin_finance.behavior.test.mjs`
  - 10 tests ran; 4 passed and 6 failed.
  - Expected causes: legacy-only form/renderer, UTC ISO defaults, `Number("")` conversion, and no missed-node labels.

## GREEN evidence

- `python -m unittest tests.test_finance_admin.EssentialServiceTests -v`: 15/15 passed.
- `python -m unittest tests.test_finance_api.FinancePersistenceHelperTests -v`: 2/2 passed with real SQLite persistence.
- Final `python -m unittest tests.test_finance_admin tests.test_finance_api -v`: 29 run, 21 passed, 8 Flask-dependent API tests skipped, 0 failures.
- Final `node --test tests/admin_finance.behavior.test.mjs tests/admin_independent_pages.behavior.test.mjs tests/admin_dark_theme.behavior.test.mjs`: 17/17 passed.
- `python -m py_compile app.py finance_admin.py`: exit 0.
- `git diff --check`: exit 0.

## Files

- `finance_admin.py`
- `app.py`
- `admin.html`
- `tests/test_finance_admin.py`
- `tests/test_finance_api.py`
- `tests/admin_finance.behavior.test.mjs`
- `docs/superpowers/specs/2026-08-04-essential-service-monitoring-design.md`
- `docs/superpowers/plans/2026-08-04-essential-service-monitoring.md`

## Concern

Flask is unavailable in the offline runtime, so 8 route-level tests skip. The non-Flask persistence tests exercise the real atomic SQLite path, timestamp/audit idempotence, and Taiwan-midnight due-date behavior.
