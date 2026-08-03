import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync(new URL("../liff/onboarding.html", import.meta.url), "utf8");

test("B399 onboarding uses 21-day beta copy instead of 14-day trial copy", () => {
  assert.match(html, /B399[\s\S]*399 安心版｜21 天免費封測/);
  assert.match(html, /onboardingPlanPresentation\(selectedBetaCohort\(\)\)/);
  assert.match(html, /planView\.activationTitle/);
  assert.match(html, /planView\.publicEntryTitle/);
});

test("B799 onboarding uses its own 21-day beta copy", () => {
  assert.match(html, /B799[\s\S]*799 守護版｜21 天免費封測/);
});

test("ordinary onboarding keeps the 14-day trial copy", () => {
  assert.match(html, /14 天安心體驗/);
});
