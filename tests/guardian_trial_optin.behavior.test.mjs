import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const inviteHtml = fs.readFileSync(new URL("../invite.html", import.meta.url), "utf8");
const mainHtml = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");

function mainFunctionSource(name) {
  const pattern = new RegExp(`function\\s+${name}\\s*\\(`);
  const match = pattern.exec(mainHtml);
  assert.ok(match, `missing function: ${name}`);
  const start = match.index;
  const brace = mainHtml.indexOf("{", start);
  let depth = 0;
  for (let index = brace; index < mainHtml.length; index += 1) {
    if (mainHtml[index] === "{") depth += 1;
    if (mainHtml[index] === "}") {
      depth -= 1;
      if (depth === 0) return mainHtml.slice(start, index + 1);
    }
  }
  throw new Error(`unterminated function: ${name}`);
}

function exposeMainFunctions(names) {
  const context = vm.createContext({});
  const source = names.map(mainFunctionSource).join("\n");
  new vm.Script(`${source}\n${names.map((name) => `this.${name} = ${name};`).join("\n")}`).runInContext(context);
  return context;
}

test("public guardian invite never asks for personal profile fields", () => {
  assert.doesNotMatch(inviteHtml, /id="publicGuardianProfileForm"/);
  assert.doesNotMatch(inviteHtml, /id="publicGuardianName"/);
  assert.doesNotMatch(inviteHtml, /id="publicGuardianRelationship"/);
  assert.doesNotMatch(inviteHtml, /id="publicGuardianPhone"/);
  assert.match(inviteHtml, /加入每日平安官方 LINE/);
  assert.match(inviteHtml, /返回這份邀請/);
});

test("a guardian-only viewer bypasses own-member onboarding but keeps own features locked", () => {
  const sandbox = exposeMainFunctions(["guardianViewerAccessDecision"]);
  assert.equal(sandbox.guardianViewerAccessDecision({
    guardian_required: true,
    plan: "free",
    guarding_for: [{line_user_id: "U-owner"}],
  }), "guardian_viewer");
  assert.equal(sandbox.guardianViewerAccessDecision({
    guardian_required: true,
    plan: "free",
    guarding_for: [],
  }), "onboarding");
  assert.equal(sandbox.guardianViewerAccessDecision({
    guardian_required: false,
    plan: "trial",
    guarding_for: [{line_user_id: "U-owner"}],
  }), "member");
});

test("guardian trial reminder is optional and only offered without active membership", () => {
  const sandbox = exposeMainFunctions(["shouldOfferGuardianTrial"]);
  assert.equal(sandbox.shouldOfferGuardianTrial({
    plan: "free",
    membership_source: "guardian_only",
    guarding_for: [{line_user_id: "U-owner"}],
  }), true);
  assert.equal(sandbox.shouldOfferGuardianTrial({
    plan: "trial",
    guarding_for: [{line_user_id: "U-owner"}],
  }), false);
  assert.equal(sandbox.shouldOfferGuardianTrial({
    plan: "paid_399",
    guarding_for: [{line_user_id: "U-owner"}],
  }), false);
  assert.equal(sandbox.shouldOfferGuardianTrial({plan: "free", guarding_for: []}), false);
});

test("daily peace page has a closable guardian trial reminder", () => {
  assert.match(mainHtml, /id="guardianTrialOfferPrompt"/);
  assert.match(mainHtml, /id="dismissGuardianTrialOfferBtn"/);
  assert.match(mainHtml, /id="startGuardianTrialOfferBtn"/);
  assert.match(mainHtml, /你仍可查看正在守護的人/);
});
