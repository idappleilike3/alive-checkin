import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const html = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");

function functionSource(name) {
  const pattern = new RegExp(`function\\s+${name}\\s*\\(`);
  const match = pattern.exec(html);
  assert.ok(match, `missing function: ${name}`);
  const start = match.index;
  const brace = html.indexOf("{", start);
  let depth = 0;
  for (let index = brace; index < html.length; index += 1) {
    if (html[index] === "{") depth += 1;
    if (html[index] === "}") {
      depth -= 1;
      if (depth === 0) return html.slice(start, index + 1);
    }
  }
  throw new Error(`unterminated function: ${name}`);
}

function expose(name) {
  const context = vm.createContext({});
  new vm.Script(`${functionSource(name)}\nthis.result = ${name};`).runInContext(context);
  return context.result;
}

test("all trial beta and paid plans resume from the same authoritative progress", () => {
  const decide = expose("onboardingResumeView");
  const plans = ["trial", "paid_199", "paid_399", "paid_399_year", "paid_799", "paid_799_year"];

  for (const plan of plans) {
    assert.equal(decide({ok: true, plan, completed_steps: {profile_and_reminder: false}}), "profile");
    assert.equal(decide({ok: true, plan, completed_steps: {profile_and_reminder: true, guardian_invite_sent: false}}), "share");
    assert.equal(decide({ok: true, plan, completed_steps: {profile_and_reminder: true, guardian_invite_sent: true, guardian_bound: false}}), "waiting");
    assert.equal(decide({ok: true, plan, completed_steps: {profile_and_reminder: true, guardian_invite_sent: true, guardian_bound: true}}), "complete");
  }
});

test("a failed progress lookup never falls back to a blank profile form", () => {
  const decide = expose("onboardingResumeView");
  assert.equal(decide({ok: false}), "unavailable");
  assert.equal(decide(null), "unavailable");
});

test("registration copy follows persisted membership after share return loses query params", () => {
  const label = expose("onboardingRegistrationPlanCopy");

  assert.equal(label({plan: "trial", membership_source: "trial"}, ""), "14 天安心體驗");
  assert.equal(label({plan: "paid_399_year", membership_source: "beta", beta_cohort: "B399"}, ""), "399 安心版｜21 天封測");
  assert.equal(label({plan: "paid_799_year", membership_source: "beta", beta_cohort: "B799"}, ""), "799 守護版｜21 天封測");
  assert.equal(label({plan: "paid_799_year", membership_source: "beta", beta_cohort: "A"}, ""), "799 守護版｜21 天封測");
  assert.equal(label({plan: "paid_399", membership_source: "paid"}, ""), "399 安心版｜月費方案");
  assert.equal(label({plan: "paid_799_year", membership_source: "paid"}, ""), "799 家庭守護｜年費方案");
});

test("beta entry query is retained before the server has completed the claim", () => {
  const label = expose("onboardingRegistrationPlanCopy");

  assert.equal(label({plan: "trial", membership_source: "trial"}, "B799"), "799 守護版｜21 天封測");
  assert.equal(label({}, "B399"), "399 安心版｜21 天封測");
});
