# Daily Peace Card Rotation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rotate distinct warm illustrations for morning, afternoon, and evening LINE check-in cards while preserving real Flex buttons and the missing-guardian invitation card.

**Architecture:** Store two new approved-style WebP illustrations per time period and select one deterministically from the local calendar date. Keep all text, weather, and actions in LINE Flex so images never contain fake data or non-clickable buttons.

**Tech Stack:** Python, Flask, LINE Flex Message JSON, unittest, WebP assets.

## Global Constraints

- Morning, afternoon, and evening must use different scene pools.
- Consecutive local dates must rotate to a different image within the same time period.
- Images contain no weather, buttons, URLs, or embedded copy.
- The four LINE Flex actions remain genuinely clickable.
- Day 100 and day 365 milestone content remains unchanged.
- The missing-guardian card keeps its working LIFF invitation button.

---

### Task 1: Deterministic daily rotation

**Files:**
- Modify: `daily_care.py`
- Test: `tests/test_daily_care_card.py`

**Interfaces:**
- Consumes: `build_daily_care_context(profile: dict, now: datetime)`
- Produces: `hero_url` selected from a period-specific tuple using the local date ordinal.

- [ ] Write tests proving consecutive dates rotate and all periods use separate pools.
- [ ] Run the focused tests and confirm they fail against the fixed-image implementation.
- [ ] Add the smallest deterministic selector needed to pass.
- [ ] Run the focused tests and confirm they pass.

### Task 2: New warm illustration assets

**Files:**
- Create: `assets/daily-care/morning-01.webp`
- Create: `assets/daily-care/morning-02.webp`
- Create: `assets/daily-care/afternoon-01.webp`
- Create: `assets/daily-care/afternoon-02.webp`
- Create: `assets/daily-care/evening-01.webp`
- Create: `assets/daily-care/evening-02.webp`
- Test: `tests/test_daily_care_card.py`

**Interfaces:**
- Consumes: period asset filenames from `daily_care.py`.
- Produces: 16:9 WebP hero images with no embedded UI text.

- [ ] Generate six distinct warm daily-life illustrations in one coherent brand style.
- [ ] Inspect each source image for scene, time-of-day, cropping safety, and absence of fake UI.
- [ ] Convert to optimized 16:9 WebP assets.
- [ ] Run asset existence and image-dimension tests.

### Task 3: Full regression and release

**Files:**
- Test: `tests/test_daily_care_card.py`
- Test: `tests/test_missing_guardian_flex.py`

**Interfaces:**
- Consumes: existing Flex builders and the new rotation context.
- Produces: a release commit containing only rotation code, tests, assets, and this plan.

- [ ] Verify four clickable daily actions and the missing-guardian LIFF button.
- [ ] Verify day 100 and day 365 still replace ordinary care content.
- [ ] Run focused tests, Python compile checks, and diff checks.
- [ ] Commit, push a feature branch, compare remote changes, merge to `main`, and verify deployment health and asset availability.
