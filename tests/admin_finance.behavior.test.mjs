import assert from "node:assert/strict";
import test from "node:test";
import vm from "node:vm";
import { readFileSync } from "node:fs";

const html = readFileSync(new URL("../admin.html", import.meta.url), "utf8");
const script = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)?.[1] || "";

class Element {
  constructor(tagName, id = "") {
    this.tagName = tagName.toUpperCase();
    this.id = id;
    this.children = [];
    this.dataset = {};
    this.className = "";
    this.classList = {
      values: new Set(),
      toggle: (name, enabled) => {
        if (enabled) this.classList.values.add(name);
        else this.classList.values.delete(name);
      },
      contains: (name) => this.classList.values.has(name),
    };
    this.hidden = false;
    this.disabled = false;
    this.checked = false;
    this.value = "";
    this._textContent = "";
  }

  get textContent() {
    return this._textContent || this.children.map((child) => child.textContent).join("");
  }

  set textContent(value) {
    this._textContent = String(value);
    this.children = [];
  }

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren(...children) {
    this._textContent = "";
    this.children = [...children];
  }

  reset() {}
  scrollIntoView() {}
}

function createFinanceHarness({permissions = ["finance.manage"], page = "finance", adminFetch, loadFinanceDashboard, DateConstructor = Date} = {}) {
  const elements = new Map();
  const all = [];
  const add = (tagName, id, properties = {}) => {
    const element = new Element(tagName, id);
    Object.assign(element, properties);
    elements.set(id, element);
    all.push(element);
    return element;
  };
  const reminderDays = [30, 14, 7, 3, 1].map((day) => add("input", `reminder-${day}`, {
    name: "financeServiceReminderDay", value: String(day), checked: true,
  }));
  const form = add("form", "financeEssentialServiceForm", {dataset: {financeManage: ""}});
  for (const id of [
    "financeEssentialServiceSummary", "financeEssentialServicesBody", "financeServiceId",
    "financeServiceVendor", "financeServiceName", "financeServicePaymentUrl", "financeServiceStatus",
    "financeServicePriority", "financeServiceCategory", "financeServiceBillingCycle",
    "financeServiceCurrency", "financeServiceOriginalAmount", "financeServiceMonthlyTwd",
    "financeServiceAnnualTwd", "financeServiceDeadline", "financeServiceNextRenewalOn",
    "financeServiceRisk", "financeServiceNote",
    "financeServiceSave", "financeSaveMessage", "membersEssentialServiceWarning",
  ]) add(id === "financeEssentialServicesBody" ? "tbody" : "input", id);
  elements.get("financeServiceSave").textContent = "儲存必要服務";
  elements.get("financeServiceStatus").value = "pending";
  elements.get("financeServicePriority").value = "critical";
  elements.get("financeServiceDeadline").value = "2026-08-23";
  elements.get("financeServiceCategory").value = "database";
  elements.get("financeServiceBillingCycle").value = "monthly";
  elements.get("financeServiceCurrency").value = "USD";
  elements.get("financeServiceOriginalAmount").value = "6.3";
  elements.get("financeServiceMonthlyTwd").value = "210";
  elements.get("financeServiceAnnualTwd").value = "2500";
  elements.get("financeServiceNextRenewalOn").value = "2026-08-23";
  elements.get("financeServiceVendor").value = "Render";
  elements.get("financeServiceName").value = "alive-checkin-state";
  elements.get("financeServicePaymentUrl").value = "https://billing.example.test/plan";

  const descendants = () => {
    const nodes = [];
    const visit = (node) => {
      nodes.push(node);
      node.children.forEach(visit);
    };
    all.forEach((node) => {
      if (!nodes.includes(node)) visit(node);
    });
    return nodes;
  };
  const document = {
    getElementById: (id) => elements.get(id) || null,
    createElement: (tagName) => {
      const element = new Element(tagName);
      all.push(element);
      return element;
    },
    querySelectorAll: (selector) => {
      const nodes = descendants();
      if (selector === "[data-finance-manage]") return nodes.filter((node) => "financeManage" in node.dataset);
      if (selector === "#financeEssentialServicesBody [data-finance-edit]") {
        return nodes.filter((node) => "financeEdit" in node.dataset);
      }
      if (selector.startsWith('input[name="financeServiceReminderDay"]')) {
        const matches = nodes.filter((node) => node.name === "financeServiceReminderDay");
        return selector.endsWith(":checked") ? matches.filter((node) => node.checked) : matches;
      }
      return [];
    },
  };
  const sandbox = {
    URL,
    Map,
    Number,
    Date: DateConstructor,
    document,
    adminPermissions: permissions,
    getAdminPage: () => page,
    adminFetch: adminFetch || (async () => ({ok: true, json: async () => ({})})),
    loadFinanceDashboard: loadFinanceDashboard || (async () => {}),
  };
  sandbox.$ = (id) => document.getElementById(id);
  const accessStart = script.indexOf("function canManageFinance()");
  const accessEnd = script.indexOf("const pushStatusLabels", accessStart);
  const monitorStart = script.indexOf("function financeMoney(value)");
  const monitorEnd = script.indexOf("async function loadFinanceDashboard()", monitorStart);
  assert.ok(accessStart >= 0 && accessEnd > accessStart, "finance access helpers must be available");
  assert.ok(monitorStart >= 0 && monitorEnd > monitorStart, "finance monitor helpers must be available");
  vm.runInNewContext(`${script.slice(accessStart, accessEnd)}\n${script.slice(monitorStart, monitorEnd)}`, sandbox);
  return {sandbox, elements, reminderDays, form};
}

function renderService(overrides = {}) {
  return {
    id: "render-postgresql-alive-checkin-state",
    vendor: "Render",
    name: "alive-checkin-state",
    category: "database",
    billing_cycle: "monthly",
    currency: "USD",
    original_amount: 6.3,
    payment_url: "https://dashboard.render.com/plan",
    status: "pending",
    priority: "critical",
    monthly_usd: 6.3,
    monthly_twd: 210,
    annual_twd: 2500,
    annual_budget_override: 2500,
    deadline: "2026-08-23",
    next_renewal_on: "2026-08-23",
    days_remaining: 19,
    reminder_days: [30, 14, 7, 3, 1],
    risk: "期限前需確認方案",
    note: "目前尚未扣款",
    reminder_history: [
      {days_before_deadline: 30, scheduled_on: "2026-07-24", status: "missed"},
      {days_before_deadline: 14, scheduled_on: "2026-08-09", status: "upcoming"},
      {days_before_deadline: 7, scheduled_on: "2026-08-16", status: "upcoming"},
      {days_before_deadline: 3, scheduled_on: "2026-08-20", status: "upcoming"},
      {days_before_deadline: 1, scheduled_on: "2026-08-22", status: "upcoming"},
    ],
    ...overrides,
  };
}

test("finance is an independent admin page with cash and accrual summaries", () => {
  assert.match(html, /href="\/admin\?page=finance"/);
  assert.match(html, /data-admin-page="finance"/);
  assert.match(html, /本月現金實收/);
  assert.match(html, /年費 12 個月分攤/);
  assert.match(html, /損益平衡會員數/);
});

test("finance controls call protected dashboard expense and settings APIs", () => {
  assert.match(html, /\/api\/admin\/finance\/dashboard/);
  assert.match(html, /\/api\/admin\/finance\/expenses/);
  assert.match(html, /\/api\/admin\/finance\/settings/);
  assert.match(html, /adminPermissions\.includes\("finance\.manage"\)/);
});

test("essential-service renderer formats the Render budget, deadline, note, and secure payment link", () => {
  const {sandbox, elements} = createFinanceHarness();
  sandbox.renderFinanceEssentialServices({
    items: [renderService()], total_monthly_usd: 6.3, total_monthly_twd: 210, total_annual_twd: 2500,
  });
  const row = elements.get("financeEssentialServicesBody").children[0];
  assert.match(row.children[0].textContent, /資料庫/);
  assert.equal(row.children[1].textContent, "US$6.30／月");
  assert.equal(row.children[2].textContent, "NT$210／月");
  assert.equal(row.children[3].textContent, "NT$2,500／年");
  assert.match(row.children[4].textContent, /期限 2026-08-23｜續費 2026-08-23｜19 天/);
  assert.match(row.children[6].textContent, /現在不扣款，接近期限再加值/);
  const link = row.children[8].children[0];
  assert.equal(link.href, "https://dashboard.render.com/plan");
  assert.equal(link.target, "_blank");
  assert.equal(link.rel, "noopener noreferrer");
  assert.equal(sandbox.createSafePaymentLink("javascript:alert(1)"), null);
  assert.equal(sandbox.createSafePaymentLink("https://user:secret@billing.example.test/plan"), null);
});

test("essential-service save guards permission and chooses POST or PUT with the intended payload", async () => {
  const deniedCalls = [];
  const denied = createFinanceHarness({permissions: [], adminFetch: async (...args) => deniedCalls.push(args)});
  await denied.sandbox.saveFinanceEssentialService({preventDefault() {}});
  assert.equal(deniedCalls.length, 0);
  assert.match(denied.elements.get("financeSaveMessage").textContent, /沒有必要服務修改權限/);

  const calls = [];
  const create = createFinanceHarness({adminFetch: async (url, options) => {
    calls.push({url, options});
    return {ok: true, json: async () => ({service: {id: "ESS1"}})};
  }});
  await create.sandbox.saveFinanceEssentialService({preventDefault() {}});
  assert.equal(calls[0].url, "/api/admin/finance/services");
  assert.equal(calls[0].options.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].options.body).reminder_days, [30, 14, 7, 3, 1]);
  assert.equal(JSON.parse(calls[0].options.body).category, "database");
  assert.equal(JSON.parse(calls[0].options.body).billing_cycle, "monthly");
  assert.equal(JSON.parse(calls[0].options.body).currency, "USD");
  assert.equal(JSON.parse(calls[0].options.body).original_amount, "6.3");
  assert.equal(JSON.parse(calls[0].options.body).next_renewal_on, "2026-08-23");
  assert.equal("annual_twd" in JSON.parse(calls[0].options.body), false);

  const update = createFinanceHarness({adminFetch: async (url, options) => {
    calls.push({url, options});
    return {ok: true, json: async () => ({service: {id: "ESS1"}})};
  }});
  update.elements.get("financeServiceId").value = "ESS 1/2";
  update.elements.get("financeServiceRisk").value = "";
  update.elements.get("financeServiceNote").value = "";
  await update.sandbox.saveFinanceEssentialService({preventDefault() {}});
  const request = calls.at(-1);
  assert.equal(request.url, "/api/admin/finance/services/ESS%201%2F2");
  assert.equal(request.options.method, "PUT");
  assert.deepEqual(JSON.parse(request.options.body).risk, "");
  assert.deepEqual(JSON.parse(request.options.body).note, "");
});

test("members warning keeps critical services visible throughout the due window and suppresses paid services", () => {
  const {sandbox, elements} = createFinanceHarness({page: "members"});
  const warning = elements.get("membersEssentialServiceWarning");
  sandbox.renderMembersEssentialServiceWarning({items: [renderService({days_remaining: 31})]});
  assert.equal(warning.hidden, true);
  sandbox.renderMembersEssentialServiceWarning({items: [renderService({days_remaining: 30, reminder_history: [
    {days_before_deadline: 30, scheduled_on: "2026-07-24", status: "due"},
    {days_before_deadline: 14, scheduled_on: "2026-08-09", status: "upcoming"},
  ]})]});
  assert.equal(warning.hidden, false);
  assert.equal(warning.classList.contains("is-critical"), true);
  assert.match(warning.children[2].children[0].textContent, /今天：30 天提醒/);
  sandbox.renderMembersEssentialServiceWarning({items: [renderService({days_remaining: 29, reminder_history: [
    {days_before_deadline: 30, scheduled_on: "2026-07-24", status: "missed"},
    {days_before_deadline: 14, scheduled_on: "2026-08-09", status: "upcoming"},
  ]})]});
  assert.match(warning.children[2].children[0].textContent, /30 天：已錯過｜14 天：未到/);
  sandbox.renderMembersEssentialServiceWarning({items: [renderService({days_remaining: 0, reminder_history: [
    {days_before_deadline: 30, scheduled_on: "2026-07-24", status: "missed"},
    {days_before_deadline: 1, scheduled_on: "2026-08-22", status: "missed"},
  ]})]});
  assert.match(warning.children[2].children[0].textContent, /1 天：已錯過/);
  sandbox.renderMembersEssentialServiceWarning({items: [renderService({status: "paid", days_remaining: -1})]});
  assert.equal(warning.hidden, true);
});

test("blank service numbers remain blank while an explicit zero remains zero", () => {
  const {sandbox, elements} = createFinanceHarness();
  elements.get("financeServiceOriginalAmount").value = "";
  elements.get("financeServiceMonthlyTwd").value = "";
  let payload = sandbox.financeEssentialServicePayload();
  assert.equal(payload.original_amount, "");
  assert.equal(payload.monthly_twd, "");
  elements.get("financeServiceOriginalAmount").value = "0";
  elements.get("financeServiceMonthlyTwd").value = "0";
  payload = sandbox.financeEssentialServicePayload();
  assert.equal(payload.original_amount, "0");
  assert.equal(payload.monthly_twd, "0");
});

test("service date defaults use the browser local calendar instead of UTC ISO", () => {
  class BoundaryDate {
    getFullYear() { return 2026; }
    getMonth() { return 7; }
    getDate() { return 23; }
    toISOString() { return "2026-08-22T16:01:00.000Z"; }
  }
  const {sandbox, elements} = createFinanceHarness({DateConstructor: BoundaryDate});
  sandbox.resetFinanceEssentialServiceForm();
  assert.equal(elements.get("financeServiceDeadline").value, "2026-08-23");
});

test("essential-service save handles network and JSON failures with a stable Chinese error", async () => {
  for (const adminFetch of [
    async () => { throw new Error("offline"); },
    async () => ({ok: true, json: async () => { throw new Error("bad json"); }}),
  ]) {
    const {sandbox, elements} = createFinanceHarness({adminFetch});
    await assert.doesNotReject(() => sandbox.saveFinanceEssentialService({preventDefault() {}}));
    assert.equal(elements.get("financeSaveMessage").textContent, "必要服務儲存失敗，請稍後再試。");
  }
});

test("essential-service save absorbs a post-save refresh failure after persistence", async () => {
  const {sandbox, elements} = createFinanceHarness({
    adminFetch: async () => ({ok: true, json: async () => ({service: {id: "ESS1"}})}),
    loadFinanceDashboard: async () => { throw new Error("refresh offline"); },
  });
  await assert.doesNotReject(() => sandbox.saveFinanceEssentialService({preventDefault() {}}));
  assert.equal(elements.get("financeSaveMessage").textContent, "必要服務已儲存，但重新載入失敗，請稍後再試。");
});

test("admin scripts remain valid JavaScript", () => {
  const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((match) => match[1]);
  for (const source of scripts) new vm.Script(source);
});
