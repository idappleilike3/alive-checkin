import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import vm from "node:vm";

const html = fs.readFileSync(new URL("../invite.html", import.meta.url), "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)?.[1];

function makeElement() {
  return {
    hidden: false,
    href: "",
    textContent: "",
    dataset: {},
    addEventListener() {},
    querySelector() { return makeElement(); },
  };
}

test("LINE 內開啟守護邀請時保留介紹頁，直到受邀者親自按繼續", async () => {
  assert.ok(script, "invite page script should exist");
  const redirects = [];
  const elements = new Map();
  const context = {
    URLSearchParams,
    navigator: { userAgent: "Mozilla/5.0 Line/14.0" },
    location: {
      search: "?invite_from=Uabc&inviter_name=%E6%9F%94%E6%9F%94",
      href: "https://alive-checkin.onrender.com/invite?invite_from=Uabc",
      replace(url) { redirects.push(url); },
    },
    document: {
      visibilityState: "visible",
      getElementById(id) {
        if (!elements.has(id)) elements.set(id, makeElement());
        return elements.get(id);
      },
      createElement() { return makeElement(); },
      body: { appendChild() {} },
    },
    window: {
      addEventListener() {},
      __INVITE_LIFF_ID__: "2010848330-UAiqPPYD",
    },
    fetch: async () => ({ ok: true, json: async () => ({ liff_id: "2010848330-UAiqPPYD" }) }),
    setTimeout() { return 1; },
    clearTimeout() {},
  };
  context.window.window = context.window;
  vm.runInNewContext(script, context);
  for (let index = 0; index < 8; index += 1) await Promise.resolve();

  assert.deepEqual(redirects, []);
  assert.match(elements.get("continueGuardianCta").textContent, /柔柔/);
  assert.match(elements.get("continueGuardianCta").href, /invite_from=Uabc/);
});
