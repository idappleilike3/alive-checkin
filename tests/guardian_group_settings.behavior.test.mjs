import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const html = fs.readFileSync(new URL("../liff/guardian-groups.html", import.meta.url), "utf8");
const scriptMatches = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)];
const behaviorScript = scriptMatches.at(-1)?.[1];
assert.ok(behaviorScript, "guardian groups page should include its behavior script");

const elements = new Map();
function element(id) {
  if (!elements.has(id)) {
    elements.set(id, {
      id,
      hidden: false,
      disabled: false,
      textContent: "",
      innerHTML: "",
      value: "",
      checked: false,
      dataset: {},
      style: {},
      addEventListener() {},
      querySelectorAll() { return []; },
    });
  }
  return elements.get(id);
}

const requests = [];
const context = {
  console,
  URLSearchParams,
  encodeURIComponent,
  setTimeout(fn) { fn(); },
  document: {
    getElementById: element,
    querySelectorAll() { return []; },
  },
  location: { href: "", assign(value) { this.href = value; } },
  liff: {
    async init() {},
    isLoggedIn() { return true; },
    login() {},
    getIDToken() { return "verified-id-token"; },
    async getProfile() { return { userId: "U-owner" }; },
  },
  fetch: async (url, options = {}) => {
    requests.push({ url, options });
    if (String(url).includes("/api/config")) {
      return { ok: true, async json() { return { liff_id: "123-test" }; } };
    }
    if (!options.method || options.method === "GET") {
      return {
        ok: true,
        async json() {
          return {
            guardian_group_limit: 3,
            guardian_group_count: 1,
            groups: [{
              group_id: "C-family",
              group_name: "家人守護群",
              member_count: 4,
              preferences: {
                daily_admin_summary: false,
                daily_summary_time: "21:00",
              },
            }],
          };
        },
      };
    }
    return {
      ok: true,
      async json() {
        return {
          ok: true,
          preferences: {
            daily_admin_summary: true,
            daily_summary_time: "22:30",
          },
        };
      },
    };
  },
};
vm.createContext(context);
vm.runInContext(behaviorScript, context);

await context.init();
assert.match(element("groupCount").textContent, /1\/3/);
assert.match(element("groupList").innerHTML, /家人守護群/);
assert.match(element("groupList").innerHTML, /每日摘要/);
assert.match(html, /id="retryButton"/);

await context.saveGroupPreferences("C-family", true, "22:30");
const saveRequest = requests.find((row) => row.options.method === "POST");
assert.ok(saveRequest, "saving should call the preferences endpoint");
assert.equal(saveRequest.url, "/api/guardian-groups/preferences");
assert.equal(saveRequest.options.headers.Authorization, "Bearer verified-id-token");
assert.deepEqual(
  JSON.parse(saveRequest.options.body),
  {
    line_user_id: "U-owner",
    group_id: "C-family",
    daily_admin_summary: true,
    daily_summary_time: "22:30",
  },
);
assert.match(element("saveStatus").textContent, /已儲存/);

console.log("guardian group settings behavior tests passed");
