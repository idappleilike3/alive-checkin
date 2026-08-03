# Admin Full Card Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the admin card preview show the full uploaded image and the approved five-button Daily Peace brand layout.

**Architecture:** Keep the existing card editor and personalized preview data flow. Change the shared preview CSS and markup, then extend the existing template payload and server renderer from four to five approved actions.

**Tech Stack:** Static HTML/CSS/JavaScript, Python card-template renderer, Node behavior tests, Python unittest.

## Global Constraints

- Do not crop uploaded preview images.
- Keep the official Daily Peace logo fixed.
- Use the five approved buttons, icons, order, wording, and colors.
- Do not change unrelated admin pages or push scheduling behavior.

---

### Task 1: Lock the approved preview contract

**Files:**
- Modify: `tests/admin_personalized_card_editor.behavior.test.mjs`
- Modify: `tests/test_admin_personalized_card_editor.py`

- [ ] Add assertions for uncropped image CSS, five approved button labels/icons/colors, and the invite URL.
- [ ] Run both targeted suites and verify they fail because the current implementation crops images and has only four buttons.

### Task 2: Implement the shared five-button preview

**Files:**
- Modify: `admin.html`
- Modify: `app.py`

- [ ] Replace fixed 4:5 cover preview CSS with intrinsic-ratio contain CSS.
- [ ] Add the fifth editor field and approved button markup/icons.
- [ ] Update local preview labels whenever an editor field changes.
- [ ] Update personalized preview rendering to use the same icon classes and button order.
- [ ] Extend card-template normalization and Flex rendering to five buttons and five approved colors.
- [ ] Run targeted tests and verify they pass.

### Task 3: Regression verification and release

**Files:**
- No additional production files.

- [ ] Run admin behavior tests and personalized card Python tests.
- [ ] Inspect the diff for unrelated changes.
- [ ] Commit, push to `main`, and verify the deployment trigger/result available from the configured repository workflow.
