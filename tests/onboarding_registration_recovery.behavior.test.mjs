import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const html = fs.readFileSync(new URL("../liff/onboarding.html", import.meta.url), "utf8");
const mainHtml = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");

function functionSource(name) {
  const pattern = new RegExp(`(?:async\\s+)?function\\s+${name}\\s*\\(`);
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

function expose(names, context = {}) {
  const source = names.map(functionSource).join("\n");
  const sandbox = vm.createContext({Promise, console, ...context});
  new vm.Script(`${source}\n${names.map((name) => `this.${name} = ${name};`).join("\n")}`).runInContext(sandbox);
  return sandbox;
}

test("399 and 799 onboarding use their configured default counts instead of the maximum", () => {
  const sandbox = expose(["onboardingDefaultReminderCount"], {
    state: {dailyReminders: 2, defaultDailyReminders: 1},
  });
  assert.equal(sandbox.onboardingDefaultReminderCount(), 1);

  sandbox.state = {dailyReminders: 3, defaultDailyReminders: 2};
  assert.equal(sandbox.onboardingDefaultReminderCount(), 2);
});

test("an authenticated onboarding save retries registration once after member-not-found", async () => {
  const requests = [];
  const responses = [
    {ok: false, status: 404, json: async () => ({error: "user not registered"})},
    {ok: true, status: 200, json: async () => ({ok: true})},
  ];
  const sandbox = expose(
    ["isMissingMemberResponse", "saveWithRegistrationRecovery"],
    {
      fetch: async (url) => {
        requests.push(url);
        return responses.shift();
      },
      authHeaders: async () => ({"Content-Type": "application/json"}),
      registerCurrentMember: async () => requests.push("register"),
      API_BASE: "",
      state: {lineUserId: "U-test"},
    },
  );

  const response = await sandbox.saveWithRegistrationRecovery("/api/profile/location", {city: "台北市"});
  assert.equal(response.ok, true);
  assert.deepEqual(requests, ["/api/profile/location", "register", "/api/profile/location"]);
});

test("member-not-found is always presented in Chinese", () => {
  const sandbox = expose(["onboardingErrorMessage"]);
  assert.equal(
    sandbox.onboardingErrorMessage({error: "user not registered"}),
    "會員資料仍在建立中，系統會自動重試；若仍未完成，請重新開啟本頁。",
  );
});

test("the canonical LIFF page shows member setup progress while registration is running", () => {
  assert.match(mainHtml, /id="lineEntryLoadingStep"/);
  assert.match(mainHtml, /系統正在建立會員資料/);
  assert.match(mainHtml, /showLineEntryLoadingGate\(\)/);
});

test("canonical onboarding mutations share one registration recovery path", () => {
  assert.match(mainHtml, /async function apiMemberMutationWithRegistrationRecovery/);
  for (const endpoint of ["/api/profile/location", "/api/contacts/add", "/api/onboarding/complete"]) {
    assert.match(mainHtml, new RegExp(`apiMemberMutationWithRegistrationRecovery\\(.[^\\n]*${endpoint.replaceAll("/", "\\/")}`));
  }
});

test("reopening onboarding authenticates the authoritative progress lookup", async () => {
  const requests = [];
  const sandbox = expose(["fetchOnboardingProgress"], {
    API_BASE: "https://example.test",
    state: {lineUserId: "U-test"},
    authHeaders: async () => ({
      "Content-Type": "application/json",
      "Authorization": "Bearer verified-id-token",
    }),
    fetch: async (url, options) => {
      requests.push({url, options});
      return {ok: true, json: async () => ({current_step: 5})};
    },
  });

  const progress = await sandbox.fetchOnboardingProgress();
  assert.equal(progress.current_step, 5);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].options.headers.Authorization, "Bearer verified-id-token");
});

test("an existing member with a pending invite returns to step five", () => {
  const sandbox = expose(["onboardingEntryDecision"]);
  assert.equal(sandbox.onboardingEntryDecision(
    {existing_user: true},
    {home_ready: false, completed_steps: {guardian_invite_sent: true, guardian_bound: false}},
  ), "onboarding");
});

test("only a server-confirmed bound guardian unlocks an existing member", () => {
  const sandbox = expose(["onboardingEntryDecision"]);
  assert.equal(sandbox.onboardingEntryDecision(
    {existing_user: true},
    {home_ready: true, completed_steps: {guardian_invite_sent: true, guardian_bound: true}},
  ), "complete");
});

test("the main app keeps an unbound existing member inside onboarding", () => {
  const sandbox = (() => {
    const sourceHtml = mainHtml;
    function mainFunctionSource(name) {
      const pattern = new RegExp(`function\\s+${name}\\s*\\(`);
      const match = pattern.exec(sourceHtml);
      assert.ok(match, `missing function: ${name}`);
      const start = match.index;
      const brace = sourceHtml.indexOf("{", start);
      let depth = 0;
      for (let index = brace; index < sourceHtml.length; index += 1) {
        if (sourceHtml[index] === "{") depth += 1;
        if (sourceHtml[index] === "}") {
          depth -= 1;
          if (depth === 0) return sourceHtml.slice(start, index + 1);
        }
      }
      throw new Error(`unterminated function: ${name}`);
    }
    const context = vm.createContext({});
    const name = "memberOnboardingGateDecision";
    new vm.Script(`${mainFunctionSource(name)}\nthis.${name} = ${name};`).runInContext(context);
    return context;
  })();
  assert.equal(sandbox.memberOnboardingGateDecision(true, true, false), "onboarding");
  assert.equal(sandbox.memberOnboardingGateDecision(false, true, false), "unlocked");
});
