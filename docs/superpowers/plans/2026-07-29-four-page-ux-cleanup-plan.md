# Four-Page UX Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify the four primary user-facing pages so each screen clearly shows the current task, one main action, and the result, while preserving 199 trial rules, guardian consistency, reminders, and SOS behavior.

**Architecture:** Keep existing Flask and LIFF routes. Add shared copy and UI rules through small reusable helpers, but do not restructure the large legacy pages. All guardian status, onboarding completion, SOS recipients, and notification views must consume the same accepted guardian relationship data.

**Tech Stack:** Flask, vanilla HTML/CSS/JavaScript, LINE LIFF, Python unittest/pytest, Node test runner.

## Global Constraints

- Public 14-day trial must match the 199 plan.
- Remove the label 「一般」 from all user-facing views.
- The same inviter and guardian LINE user IDs may have only one active relationship.
- Details and long explanations must be collapsed by default.
- Every page must have one visually dominant primary action.
- SOS third click must create and send the event to accepted core guardians.

---

### Task 1: Simplify the public/home page

**Files:**
- Modify: `index.html`
- Test: `tests/test_homepage_interactions.mjs`

- [ ] Add a failing test asserting the homepage contains one primary CTA, a three-step summary, and collapsed details.
- [ ] Run the test and confirm failure.
- [ ] Replace repeated explanatory blocks with: one headline, one sentence, three short steps, one CTA, and `<details>` sections.
- [ ] Add the compact guardian summary: 「誰在守護我」 and 「我正在守護誰」.
- [ ] Run frontend tests.
- [ ] Commit.

### Task 2: Simplify 14-day onboarding and enforce 199 trial

**Files:**
- Modify: `liff/onboarding.html`
- Modify: `app.py`
- Test: `tests/test_onboarding_trial.py`

- [ ] Add failing tests for 199-equivalent trial limits and accepted-guardian-only completion.
- [ ] Run tests and confirm failure.
- [ ] Set trial limits to the 199 plan values.
- [ ] Reorder onboarding to: LINE login → reminder time → invite guardian → guardian accepted → complete.
- [ ] Hide onboarding after one accepted core guardian exists.
- [ ] Replace long copy with a single instruction and one primary button per step.
- [ ] Run tests.
- [ ] Commit.

### Task 3: Fix invitation, duplicate binding, and role labels

**Files:**
- Modify: `liff/share-invite.html`
- Modify: `index.html`
- Modify: `app.py`
- Test: `tests/test_guardian_relationship_uniqueness.py`

- [ ] Add failing tests for unique inviter/guardian pairs and no 「一般」 label.
- [ ] Run tests and confirm failure.
- [ ] Upsert existing relationships instead of inserting duplicates.
- [ ] Allow only the labels 核心守護人、緊急聯絡人、正在守護的人.
- [ ] Show the member reminder time on the acceptance screen.
- [ ] Add collapsible lists for core guardians and emergency contacts.
- [ ] Run tests.
- [ ] Commit.

### Task 4: Fix smart reminders and 799 calendar reminder placement

**Files:**
- Modify: `index.html`
- Modify: `app.py`
- Test: `tests/test_smart_reminders.py`

- [ ] Add failing tests for create, edit, enable, disable, and delete reminder actions.
- [ ] Run tests and confirm failure.
- [ ] Add functional controls for title, date, time, recurrence, note, and notification targets.
- [ ] For 799 plans, place the date reminder card above 平安紀錄.
- [ ] Show the empty-state prompt 「先新增日期與備忘，系統才會在指定時間提醒」.
- [ ] Keep long reminder explanations inside a collapsed details section.
- [ ] Run tests.
- [ ] Commit.

### Task 5: Fix SOS recipient lookup and bilateral notification status

**Files:**
- Modify: `index.html`
- Modify: `app.py`
- Test: `tests/test_sos_guardian_delivery.py`

- [ ] Add a failing test where an accepted core guardian receives the third-click SOS.
- [ ] Run tests and confirm failure.
- [ ] Make SOS recipient lookup use the accepted guardian relationship source.
- [ ] Show per-recipient send status to the member.
- [ ] Add member and guardian notification views for sent, delivered, accepted, contacted, failed, and safe states.
- [ ] Run Python and frontend tests.
- [ ] Commit.

### Task 6: Four-page end-to-end verification

**Files:**
- Test: `tests/test_four_page_user_journey.py`

- [ ] Test public page → onboarding → reminder → guardian acceptance → check-in.
- [ ] Test duplicate invitation does not create another relationship.
- [ ] Test 799 reminder creation above check-in history.
- [ ] Test SOS third click reaches the guardian and both sides see status.
- [ ] Run all Python and Node tests.
- [ ] Verify every URL and every visible button manually.
- [ ] Commit verification updates.
