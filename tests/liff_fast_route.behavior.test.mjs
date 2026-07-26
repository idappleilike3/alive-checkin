import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const page = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");

function section(start, end) {
  const from = page.indexOf(start);
  const to = page.indexOf(end, from);
  assert.notEqual(from, -1, `missing start marker: ${start}`);
  assert.notEqual(to, -1, `missing end marker: ${end}`);
  return page.slice(from, to);
}

function functionSource(name) {
  const pattern = new RegExp(`(?:async\\s+)?function\\s+${name}\\s*\\(`);
  const match = pattern.exec(page);
  assert.ok(match, `missing function: ${name}`);
  const start = match.index;
  const brace = page.indexOf("{", start);
  let depth = 0;
  for (let index = brace; index < page.length; index += 1) {
    if (page[index] === "{") depth += 1;
    if (page[index] === "}") {
      depth -= 1;
      if (depth === 0) return page.slice(start, index + 1);
    }
  }
  throw new Error(`unterminated function: ${name}`);
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function expose(source, names, context = {}) {
  const sandbox = vm.createContext({ Promise, console, ...context });
  const exports = names.map((name) => `this.${name} = ${name};`).join("\n");
  new vm.Script(`${source}\n${exports}`).runInContext(sandbox);
  return sandbox;
}

test("first status renders without waiting for contacts or onboarding", async () => {
  const contacts = deferred();
  const onboarding = deferred();
  const events = [];
  const elements = {
    mvpSafeBtn: { disabled: true },
    mvpGuardStartBtn: { disabled: true },
  };
  const sandbox = expose(
    section("async function loadInitialMemberData()", "// 整合到 initApp"),
    ["loadInitialMemberData"],
    {
      apiGetStatus: async () => ({ is_today_checked: false, contacts: [] }),
      apiGetContacts: () => contacts.promise,
      fetchOnboardingState: () => onboarding.promise,
      renderStatus: () => events.push("status"),
      syncCheckBtn: () => events.push("sync"),
      renderSosAccess: () => events.push("sos"),
      renderGuardians: () => events.push("contacts"),
      renderMemberCenter: () => events.push("member"),
      friendlyApiFailure: () => "bad status",
      contactData: [],
      currentContactLimit: 1,
      lineUserId: "U123",
      memberBootstrapState: {
        statusReady: false,
        dataReady: false,
        inFlight: null,
        error: null,
      },
      setMemberInteractionLocked() {},
      $: (id) => elements[id] || null,
      document: { body: { removeAttribute() {} } },
    },
  );

  const result = sandbox.loadInitialMemberData();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(events.slice(0, 3), ["status", "sync", "sos"]);

  contacts.resolve({ status: 200, data: { contacts: [], contact_limit: 1 } });
  onboarding.resolve({ done: true, hasGuardian: true, data: {} });
  await result;
});

test("canonical action keeps page and open aliases on the requested screen", () => {
  const parserSource = section(
    "function requestedAppAction()",
    "function setInitialRouteLoading",
  );
  const routeSource = section("function openRequestedPage()", "function openUpgradePlans()");
  const params = {};
  const tabs = [];
  const sandbox = expose(
    `${parserSource}\n${routeSource}`,
    ["requestedAppAction", "openRequestedPage"],
    {
      getAppParam: (key) => params[key] || "",
      showTab: (tab) => tabs.push(tab),
      openMvpGuardPanel: () => tabs.push("guard"),
      openSosModal: () => tabs.push("sos"),
      setCalendarExpanded() {},
      setMemberCenterExpanded() {},
      document: { querySelector: () => null },
      window: { location: { href: "" } },
    },
  );

  for (const [query, expected] of [
    [{ page: "member" }, "member"],
    [{ page: "guardians" }, "guardians"],
    [{ open: "profile" }, "member"],
    [{ open: "member" }, "member"],
    [{ open: "safety" }, "guard"],
  ]) {
    Object.keys(params).forEach((key) => delete params[key]);
    Object.assign(params, query);
    tabs.length = 0;
    sandbox.openRequestedPage();
    assert.equal(tabs.at(-1), expected);
  }
});

test("shared member gate blocks status and full-data actions until ready", () => {
  const gateSource = section(
    "function requireMemberActionReady(",
    "function showMemberBootstrapError(",
  );
  const notices = [];
  const sandbox = expose(gateSource, ["requireMemberActionReady"], {
    useLocalMode: false,
    lineUserId: "",
    memberBootstrapState: { statusReady: false, dataReady: false },
    showMemberBootstrapPending: (message) => notices.push(message),
    showLineLoginRequired: () => notices.push("login"),
    readSafeDeepLinkParams: () => ({}),
  });

  assert.equal(sandbox.requireMemberActionReady("status"), false);
  sandbox.lineUserId = "U123";
  assert.equal(sandbox.requireMemberActionReady("status"), false);
  sandbox.memberBootstrapState.statusReady = true;
  assert.equal(sandbox.requireMemberActionReady("status"), true);
  assert.equal(sandbox.requireMemberActionReady("data"), false);
  sandbox.memberBootstrapState.dataReady = true;
  assert.equal(sandbox.requireMemberActionReady("data"), true);
  assert.ok(notices.length >= 2);
});

test("retry reruns only member bootstrap and unlocks after success", async () => {
  const retrySource = section(
    "async function retryMemberBootstrap()",
    "async function loadInitialMemberData()",
  );
  let calls = 0;
  const sandbox = expose(retrySource, ["retryMemberBootstrap"], {
    memberBootstrapState: {
      statusReady: false,
      dataReady: false,
      inFlight: null,
    },
    initApp: async () => {
      calls += 1;
      sandbox.memberBootstrapState.statusReady = true;
      sandbox.memberBootstrapState.dataReady = true;
      return true;
    },
    setMemberInteractionLocked() {},
    hideInlineError() {},
  });

  const result = await sandbox.retryMemberBootstrap();
  assert.equal(result, true);
  assert.equal(calls, 1);
  assert.equal(sandbox.memberBootstrapState.statusReady, true);
  assert.equal(sandbox.memberBootstrapState.dataReady, true);
  assert.equal(page.includes("location.reload()"), false);
});

test("member mutations execute the shared gate before any operation", async () => {
  const names = [
    "doCheckin",
    "submitSmartReminderEditor",
    "deleteSmartReminder",
    "saveMemberDailyReminder",
    "shareMyLocation",
    "refreshSafetyGuardLocation",
    "stopLocationSharing",
    "deleteCheckinHistory",
    "deleteAccountAndData",
    "openAddGuardianFromMember",
    "sendSosAlert",
    "saveGuardian",
    "executeDeleteGuardian",
    "saveOnboardingGuardian",
    "saveOnboardingReminder",
    "saveMvpContact",
    "saveContacts",
    "saveSelectedCalendarNote",
    "unbindGuardianGroup",
  ];
  const calls = [];
  const sandbox = expose(
    names.map(functionSource).join("\n"),
    names,
    {
      requireMemberActionReady: (scope) => {
        calls.push(scope);
        return false;
      },
    },
  );

  for (const name of names) {
    const result = await sandbox[name]();
    assert.equal(result, false, `${name} must stop when gate is closed`);
  }
  assert.equal(calls.length, names.length);
  assert.ok(calls.includes("status"));
  assert.ok(calls.includes("data"));
});

test("status error renders senior-readable retry without page reload", () => {
  const listeners = {};
  const errorBox = {
    classList: { remove() {} },
    hidden: true,
    innerHTML: "",
  };
  const retryButton = {
    addEventListener: (type, handler) => {
      listeners[type] = handler;
    },
  };
  let retries = 0;
  const sandbox = expose(
    functionSource("showMemberBootstrapError"),
    ["showMemberBootstrapError"],
    {
      memberBootstrapState: {
        statusReady: true,
        dataReady: true,
        error: null,
      },
      setMemberInteractionLocked() {},
      retryMemberBootstrap: () => {
        retries += 1;
      },
      $: (id) => ({
        inlineError: errorBox,
        retryMemberBootstrapBtn: retryButton,
      })[id] || null,
    },
  );

  sandbox.showMemberBootstrapError(new Error("network"));
  assert.match(errorBox.innerHTML, /暫時讀不到會員資料/);
  assert.match(errorBox.innerHTML, /重新載入資料/);
  assert.equal(errorBox.hidden, false);
  listeners.click();
  assert.equal(retries, 1);
  assert.equal(page.includes("location.reload()"), false);
});
