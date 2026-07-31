# Theme Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the neon theme and unify cute-theme surfaces and primary controls around the pink palette.

**Architecture:** Keep theme behavior in the existing `index.html`. Restrict the theme setter to an allowlist so legacy local storage values migrate safely, remove unused neon CSS, and add narrowly scoped cute overrides while preserving warning and SOS colors.

**Tech Stack:** Static HTML, CSS, browser JavaScript, Python unittest.

## Global Constraints

- Only `classic` and `cute` remain selectable.
- Legacy `neon` or unknown preferences become `classic`.
- Warning remains yellow and SOS/danger remains red.
- No member data, LINE, invitation, check-in, or SOS behavior changes.

---

### Task 1: Theme options and migration

**Files:**
- Modify: `index.html`
- Create: `tests/test_theme_options.py`
- Modify: `tests/test_product_rules.py`

**Interfaces:**
- Consumes: `localStorage.preferred_theme`
- Produces: `setTheme(theme)` limited to `classic | cute`

- [x] **Step 1: Write failing tests for two options, legacy fallback, and no neon CSS**
- [x] **Step 2: Run `python -m unittest tests.test_theme_options -v` and confirm all three tests fail**
- [x] **Step 3: Remove neon markup/styles and add the supported-theme allowlist**
- [x] **Step 4: Update outdated assertions that require neon styles**
- [x] **Step 5: Run theme and product-rule tests**

### Task 2: Cute palette consistency

**Files:**
- Modify: `index.html`
- Modify: `tests/test_theme_options.py`

**Interfaces:**
- Consumes: `body.cute`
- Produces: pink cute-theme overrides for normal primary surfaces and controls

- [x] **Step 1: Add failing assertions for pink cute surfaces and controls**
- [x] **Step 2: Run the focused test and confirm the new assertions fail**
- [x] **Step 3: Add pink overrides without changing warning or danger selectors**
- [x] **Step 4: Run focused tests, JavaScript syntax validation, and relevant regressions**
- [x] **Step 5: Review the diff and commit only theme-related files**
