import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import vm from "node:vm";

const html = readFileSync(new URL("../admin.html", import.meta.url), "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)?.[1];

if (!script) throw new Error("admin.html script not found");

function response({ok = true, status = 200, data = {}} = {}) {
  return {ok, status, json: async () => data};
}

function createHarness(fetchImpl) {
  const elements = new Map();
  const scheduled = [];
  const intervals = [];
  let querySelectorResult = null;
  const ids = [
    "adminShell", "loginPanel", "loginStatus", "adminLoginForm", "loginBtn",
    "adminPassword", "logoutBtn", "refreshBtn", "contactRemindBtn", "remindBtn",
    "renewalRemindBtn", "birthdayRemindBtn", "createBackupBtn", "richMenuDeployBtn",
    "authStatus", "message", "usersBody", "migrationConfigured", "migrationTotals",
    "migrationLastAttempt", "migrationFailure", "migrationCounts", "pushCampaignId",
    "pushCampaignName", "pushContentType", "pushCampaignText", "pushTemplateKey",
    "pushTemplateVariables", "pushExplicitMembers", "pushScheduledAt", "pushEditorTitle",
    "pushCampaignMeta", "pushVersionHistory", "betaResetButton", "betaResetCandidate",
    "betaResetStatus", "betaResetEmpty"
  ];
  for (const id of ids) {
    const element = {
      classList: {add() {}, remove() {}},
      disabled: false,
      hidden: id === "adminShell",
      listeners: {},
      innerHTML: "",
      textContent: "",
      value: "",
      addEventListener(type, listener) { this.listeners[type] = listener; }
    };
    if (id.startsWith("migration")) {
      Object.defineProperty(element, "innerHTML", {
        set() { throw new Error("migration server text must not use innerHTML"); }
      });
    }
    elements.set(id, element);
  }
  const context = {
    Blob,
    Headers,
    URL,
    alert() {},
    confirm: () => true,
    console,
    document: {
      getElementById: (id) => elements.get(id),
      querySelector: () => querySelectorResult,
      querySelectorAll: () => [],
      visibilityState: "hidden",
      createElement: () => ({click() {}})
    },
    fetch: fetchImpl,
    setInterval(callback) { intervals.push(callback); return intervals.length; },
    setTimeout(callback) { scheduled.push(callback); return scheduled.length; }
  };
  let source = script;
  if (process.env.ADMIN_AUTH_UI_DISABLE_GUARD === "1") {
    source = source.replace(
      '        if (generation !== adminAuthGeneration) return;\n        if (!response.ok || !data.authenticated) return showLogin("");',
      '        if (!response.ok || !data.authenticated) return showLogin("");'
    );
  }
  vm.runInNewContext(source, context, {filename: "admin.html"});
  return {
    context,
    elements,
    scheduled,
    intervals,
    setQuerySelectorResult(value) { querySelectorResult = value; }
  };
}

test("admin auto refresh pauses while a member plan selection is unsaved", async () => {
  let fetchCalls = 0;
  const harness = createHarness(() => {
    fetchCalls += 1;
    throw new Error("refresh must not run while a plan selection is unsaved");
  });
  harness.elements.get("adminShell").hidden = false;
  harness.context.document.visibilityState = "visible";
  harness.setQuerySelectorResult({dataset: {dirty: "true"}});

  await harness.intervals.at(-1)();

  assert.equal(fetchCalls, 0);
});

test("stale session restore cannot hide dashboard after successful login", async () => {
  let resolveSession;
  const sessionPromise = new Promise((resolve) => { resolveSession = resolve; });
  const harness = createHarness((url) => {
    if (url === "/api/admin/session") return sessionPromise;
    if (url === "/api/admin/login") return Promise.resolve(response({data: {csrf_token: "csrf"}}));
    if (url === "/api/admin/summary") return Promise.resolve(response({ok: false, status: 500}));
    throw new Error(`unexpected request: ${url}`);
  });

  const restorePromise = harness.scheduled[0]();
  await harness.elements.get("adminLoginForm").listeners.submit({preventDefault() {}});
  resolveSession(response({ok: false, status: 401}));
  await restorePromise;

  assert.equal(harness.elements.get("adminShell").hidden, false);
  assert.equal(harness.elements.get("loginPanel").hidden, true);
});

test("a stale 401 response cannot hide a dashboard opened by a newer login", async () => {
  let resolveOldRequest;
  const oldRequest = new Promise((resolve) => { resolveOldRequest = resolve; });
  const harness = createHarness((url) => {
    if (url === "/api/admin/old-request") return oldRequest;
    if (url === "/api/admin/login") return Promise.resolve(response({data: {csrf_token: "csrf"}}));
    if (url === "/api/admin/summary") return Promise.resolve(response({ok: false, status: 500}));
    throw new Error(`unexpected request: ${url}`);
  });

  const staleFetch = harness.context.adminFetch("/api/admin/old-request").catch(() => {});
  await harness.elements.get("adminLoginForm").listeners.submit({preventDefault() {}});
  resolveOldRequest(response({ok: false, status: 401}));
  await staleFetch;

  assert.equal(harness.elements.get("adminShell").hidden, false);
  assert.equal(harness.elements.get("loginPanel").hidden, true);
});

test("login network error restores the button and shows a friendly message", async () => {
  const harness = createHarness((url) => {
    if (url === "/api/admin/login") return Promise.reject(new Error("network unavailable"));
    throw new Error(`unexpected request: ${url}`);
  });

  await harness.elements.get("adminLoginForm").listeners.submit({preventDefault() {}});

  assert.equal(harness.elements.get("loginStatus").textContent, "連線失敗，請稍後再試。");
  assert.equal(harness.elements.get("loginBtn").disabled, false);
});

test("migration card renders server text through textContent only", () => {
  const harness = createHarness(() => {
    throw new Error("fetch is not expected");
  });
  const hostile = '<img src=x onerror="globalThis.compromised=true">';

  harness.context.renderAccountMigrations({
    configured: true,
    totals: {total: 2, success: 1, failed: 1, pending: 0},
    latest_events: [{
      status: "failed",
      created_at: hostile,
      failure_category: hostile,
      counts: {
        checkins: 2,
        contacts: 1,
        groups: 0,
        reminders: 3,
        orders: 1,
        requests: 0
      }
    }]
  });

  assert.equal(harness.elements.get("migrationLastAttempt").textContent, hostile);
  assert.equal(harness.elements.get("migrationFailure").textContent, hostile);
  assert.equal(harness.context.compromised, undefined);
  assert.equal(
    harness.elements.get("migrationCounts").textContent,
    "簽到 2、聯絡人 1、群組 0、提醒 3、訂單 1、申請 0"
  );
});

test("migration card distinguishes HTTP and network failures from unconfigured", async () => {
  for (const fetchImpl of [
    () => Promise.resolve(response({ok: false, status: 500})),
    () => Promise.reject(new Error("network unavailable"))
  ]) {
    const harness = createHarness(fetchImpl);

    await harness.context.refreshAccountMigrations();

    assert.equal(
      harness.elements.get("migrationConfigured").textContent,
      "暫時無法取得"
    );
    assert.equal(
      harness.elements.get("migrationTotals").textContent,
      "暫時無法取得"
    );
  }
});

test("migration 401 keeps the existing expired-session flow", async () => {
  const harness = createHarness(() => Promise.resolve(
    response({ok: false, status: 401})
  ));

  await assert.rejects(
    harness.context.refreshAccountMigrations(),
    /admin_session_expired/
  );

  assert.equal(harness.elements.get("adminShell").hidden, true);
  assert.equal(harness.elements.get("loginPanel").hidden, false);
  assert.equal(
    harness.elements.get("loginStatus").textContent,
    "登入已失效，請重新登入。"
  );
});
