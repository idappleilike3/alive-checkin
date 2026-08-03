# Guardian Invite Guided Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every guardian invitation guide the recipient through the story, official LINE friendship, locked inviter identity, required recipient details, one-way acceptance, and an optional reciprocal 14-day trial invitation.

**Architecture:** Keep `invite.html` as the public story and LINE-entry page, preserve the invitation parameters through LIFF login/session recovery, and use the shared acceptance modal in `index.html` for every plan. Enforce the required recipient phone in `bind_emergency_contact` so all invitation sources share one server-side rule.

**Tech Stack:** Static HTML/CSS/JavaScript, LIFF SDK, Python backend, unittest/pytest, Node behavior tests.

## Global Constraints

- Applies to 14-day trial, B399, B799, and paid-member one-click guardian invitations.
- Inviter name is system-provided and locked.
- Recipient name, relationship, and phone are required before acceptance.
- Official LINE friendship must be confirmed before the profile form is available.
- Acceptance creates only one guardian direction; reciprocal protection requires a second explicit invitation and acceptance.
- Existing invitation and onboarding progress must survive the official-account and LIFF return path.

---

### Task 1: Lock the cross-plan invitation contract in tests

**Files:**
- Modify: `tests/test_invite_onboarding_flow.py`
- Modify: `tests/test_invite_emotional_guardian_v2.py`
- Modify: `tests/test_unified_registration_entry_flows.py`

**Interfaces:**
- Consumes: `invite.html`, `index.html`, `bind_emergency_contact(data_file, payload, config)`
- Produces: Regression coverage for shared invitation UI and API validation.

- [ ] Add tests for story-first guidance, official LINE join/return controls, locked inviter identity, wide relationship field, and required phone.
- [ ] Add API tests proving a pending invite without a phone is rejected and a complete profile succeeds.
- [ ] Run the focused tests and confirm they fail for the missing behavior.

### Task 2: Implement the public story and return guidance

**Files:**
- Modify: `invite.html`

**Interfaces:**
- Consumes: `invite_from`, `invite_token`, `inviter_name`, `inviter_relationship` URL parameters.
- Produces: A preserved LIFF continuation URL and explicit official-account return instructions.

- [ ] Make the first action join the official LINE account and explain how to return.
- [ ] Keep a separate “I have joined, continue this invitation” LIFF action carrying all invitation parameters.
- [ ] Update the story steps and required-phone copy.
- [ ] Run focused public-page tests until green.

### Task 3: Implement locked inviter and required recipient profile

**Files:**
- Modify: `index.html`
- Modify: `app.py`

**Interfaces:**
- Consumes: preserved invitation parameters and authenticated LIFF profile.
- Produces: Required `contact_display_name`, `contact_relationship`, and `contact_phone` validated in browser and backend.

- [ ] Show inviter name as a read-only system value in the acceptance modal.
- [ ] Increase relationship selector width and keep “other” relationship support.
- [ ] Mark phone required and block submission when it is empty.
- [ ] Enforce phone on pending invitation acceptance in `bind_emergency_contact`.
- [ ] Run focused API and UI tests until green.

### Task 4: Verify and publish

**Files:**
- Verify only: modified production and test files.

**Interfaces:**
- Consumes: completed implementation.
- Produces: a reviewed commit on the latest `main`, followed by production deployment verification.

- [ ] Run focused tests, JavaScript syntax checks, Python compilation, and relevant regression tests.
- [ ] Review `git diff` to ensure no unrelated changes are included.
- [ ] Commit the verified files and publish by non-force fast-forward to `main`.
- [ ] Confirm Render serves the new invitation markers and returns HTTP 200.
