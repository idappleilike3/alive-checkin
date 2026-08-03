import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");

function functionBody(name) {
  const start = html.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `expected ${name} to exist`);
  const brace = html.indexOf("{", start);
  let depth = 0;
  for (let index = brace; index < html.length; index += 1) {
    if (html[index] === "{") depth += 1;
    if (html[index] === "}") depth -= 1;
    if (depth === 0) return html.slice(brace + 1, index);
  }
  assert.fail(`could not parse ${name}`);
}

test("799 beta setup keeps reminder controls below profile data", () => {
  const formStart = html.indexOf('id="onboardingGuardianStep"');
  const formEnd = html.indexOf('id="onboardingShareStep"');
  const form = html.slice(formStart, formEnd);

  assert.match(form, /id="onboardingReminderSlots"/);
  assert.match(form, /id="onboardingUseDefaultsBtn"/);
  assert.doesNotMatch(form, /id="onboardingReminderStep"[^>]*hidden/);
});

test("setup provides a separate optional emergency contact", () => {
  assert.match(html, /id="obEmergencyName"/);
  assert.match(html, /id="obEmergencyRelationship"/);
  assert.match(html, /id="obEmergencyPhone"/);
  assert.match(html, /緊急時可快速撥打/);

  const save = functionBody("saveOnboardingGuardian");
  assert.match(save, /contact_role:\s*"emergency"/);
});

test("saving combined setup stores reminders without completing guardian binding, then reveals one-tap invite", () => {
  const save = functionBody("saveOnboardingGuardian");
  assert.match(save, /apiSaveOnboardingReminder/);
  assert.doesNotMatch(save, /apiCompleteOnboarding/);
  assert.match(save, /showOnboardingShareStep\(\)/);
  assert.match(html, /id="onboardingShareBtn"[^>]*>一鍵分享邀請守護人</);
  assert.match(html, /一鍵分享邀請最少 1 位守護人/);
  assert.match(html, /你的方案最多可邀請.*位核心守護人/);
  assert.match(functionBody("showOnboardingShareStep"), /planCoreGuardianLimit/);
  assert.match(html, /請主動聯繫守護人/);
  assert.match(html, /對方.*填寫資料.*親自同意後.*完成綁定/);
});

test("trial beta and one-tap sharing explain the shared first-guardian flow", () => {
  const trial = readFileSync(new URL("../trial-14.html", import.meta.url), "utf8");
  const beta = readFileSync(new URL("../beta-register.html", import.meta.url), "utf8");
  const share = readFileSync(new URL("../liff/share-invite.html", import.meta.url), "utf8");

  assert.match(trial, /open=onboarding/);
  assert.match(beta, /open=onboarding/);
  assert.match(share, /第 1 位/);
  assert.match(share, /主要守護人/);
  assert.match(share, /會員中心.*再新增一位守護人/);
});
