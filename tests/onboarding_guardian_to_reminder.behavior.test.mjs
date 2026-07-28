import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");

function functionBody(name) {
  const start = html.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `expected ${name} to exist`);
  const brace = html.indexOf("{", start);
  let depth = 0;
  for (let i = brace; i < html.length; i += 1) {
    if (html[i] === "{") depth += 1;
    if (html[i] === "}") depth -= 1;
    if (depth === 0) return html.slice(brace + 1, i);
  }
  assert.fail(`could not parse ${name}`);
}

test("required guardian onboarding can save guardian and advance to reminders", () => {
  const saveGuardian = functionBody("saveOnboardingGuardian");
  const interactionLock = functionBody("setMemberInteractionLocked");

  assert.doesNotMatch(
    saveGuardian,
    /requireMemberActionReady/,
    "the onboarding action that satisfies guardianRequired must not be blocked by guardianRequired",
  );
  assert.doesNotMatch(
    interactionLock,
    /"onboardingSaveBtn"/,
    "the required onboarding guardian button must remain clickable while member features are locked",
  );
  assert.match(saveGuardian, /showOnboardingReminderStep\(\)/);
});

test("required guardian onboarding can save reminder settings", () => {
  const saveReminder = functionBody("saveOnboardingReminder");
  const interactionLock = functionBody("setMemberInteractionLocked");

  assert.doesNotMatch(
    saveReminder,
    /requireMemberActionReady/,
    "the required onboarding reminder action must not be blocked by guardianRequired",
  );
  assert.doesNotMatch(
    interactionLock,
    /"onboardingReminderSaveBtn"/,
    "the required onboarding reminder button must remain clickable while member features are locked",
  );
  assert.match(saveReminder, /apiCompleteOnboarding/);
});
