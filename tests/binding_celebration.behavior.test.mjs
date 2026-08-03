import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");

test("completed onboarding never renders the five-step invite screen again", () => {
  assert.doesNotMatch(
    html,
    /function showOnboardingCompleteStep\(\)[\s\S]*?再次一鍵邀請分享/,
  );
  assert.match(html, /if \(resumeView === "complete"\)[\s\S]*?modal\.hidden = true/);
});

test("binding celebration is a server-backed one-time voice prompt with check-in and mute", () => {
  assert.match(html, /show_binding_celebration/);
  assert.match(html, /\/api\/onboarding\/binding-celebration\/ack/);
  assert.match(html, /恭喜你完成守護人綁定/);
  assert.match(html, /guardianBindingCelebrateCheckin/);
  assert.match(html, /guardianBindingCelebrateMute/);
  assert.match(html, /speakPeaceHelper/);
});
