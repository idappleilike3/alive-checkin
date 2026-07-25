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
  const ids = [
    "adminShell", "loginPanel", "loginStatus", "adminLoginForm", "loginBtn",
    "adminPassword", "logoutBtn", "refreshBtn", "contactRemindBtn", "remindBtn",
    "renewalRemindBtn", "birthdayRemindBtn", "createBackupBtn", "richMenuDeployBtn",
    "authStatus", "message"
  ];
  for (const id of ids) {
    elements.set(id, {
      classList: {add() {}, remove() {}},
      disabled: false,
      hidden: id === "adminShell",
      listeners: {},
      textContent: "",
      value: "",
      addEventListener(type, listener) { this.listeners[type] = listener; }
    });
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
      querySelector: () => null,
      visibilityState: "hidden",
      createElement: () => ({click() {}})
    },
    fetch: fetchImpl,
    setInterval() {},
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
  return {elements, scheduled};
}

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

test("login network error restores the button and shows a friendly message", async () => {
  const harness = createHarness((url) => {
    if (url === "/api/admin/login") return Promise.reject(new Error("network unavailable"));
    throw new Error(`unexpected request: ${url}`);
  });

  await harness.elements.get("adminLoginForm").listeners.submit({preventDefault() {}});

  assert.equal(harness.elements.get("loginStatus").textContent, "連線失敗，請稍後再試。");
  assert.equal(harness.elements.get("loginBtn").disabled, false);
});
