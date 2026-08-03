import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");

test("member plan label uses persisted beta membership before trial fallback", () => {
  assert.match(html, /function memberPlanLabel\(data\)/);
  assert.match(html, /membership_source\s*===\s*["']beta["']/);
  assert.match(html, /B399[^\n]+399[^\n]+21 天封測/);
  assert.match(html, /B799[^\n]+799[^\n]+21 天封測/);
  assert.match(html, /planStateLabel[^\n]+memberPlanLabel\(data\)/);
  assert.match(html, /memberPlanText[^\n]+memberPlanLabel\(status\)/);
  assert.match(html, /memberBillingPlan[^\n]+memberPlanLabel\(status\)/);
});

test("daily peace helper is accessible, voiced by default, and avoids emergency controls", () => {
  assert.match(html, /id="peaceHelper"/);
  assert.match(html, /id="peaceHelperMute"/);
  assert.match(html, /aria-live="polite"/);
  assert.match(html, /speechSynthesis/);
  assert.match(html, /peace_helper_muted/);
  assert.match(html, /bottom-nav[^}]*~\s*100px|--peace-helper-bottom/);
  assert.match(html, /body\.sos-open[^{]*\.peace-helper/);
  assert.match(html, /peace_helper_position/);
  assert.match(html, /pointerdown/);
  assert.match(html, /pointermove/);
});

test("completed onboarding invites the member to make the first check-in", () => {
  assert.match(html, /恭喜你完成綁定，請點一下「我平安」/);
  assert.match(html, /請把「每日平安」官方 LINE 置頂，並開啟通知/);
  assert.match(html, /announceOnboardingCompletion\(data\)/);
});
