import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");

test("completed onboarding closes immediately and never renders five steps", () => {
  assert.match(html, /if \(resumeView === "complete"\)[\s\S]*?modal\.hidden = true;[\s\S]*?return;/);
  assert.doesNotMatch(html, /function showOnboardingCompleteStep\(\)[\s\S]*?再次一鍵邀請分享/);
});

test("incomplete onboarding always has a close button", () => {
  assert.match(html, /async function showOnboarding\(\)[\s\S]*?setOnboardingCloseVisible\(true\)/);
});

test("saved B799 cohort wins over a generic trial entry label", () => {
  assert.match(html, /const activeCohort = \["A", "B399", "B799"\]\.includes\(cohort\)/);
});
