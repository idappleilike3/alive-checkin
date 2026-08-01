import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const html = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");

test("does not render cached checkin before authoritative status", () => {
  const startup = html.slice(html.indexOf("function bootstrapIdentity"), html.indexOf("async function init", html.indexOf("function bootstrapIdentity")));
  assert.ok(!startup.includes("renderCachedCheckinStatus(lineUserId)"));
});

test("member cache stores and checks account state version", () => {
  assert.match(html, /account_state_version:\s*status\.account_state_version/);
  assert.match(html, /clearAccountStateCache\(userId\)/);
  assert.match(html, /cachedVersion\s*!==\s*serverVersion/);
});

test("cached checkin renderer is not called during startup", () => {
  const calls = html.match(/renderCachedCheckinStatus\(lineUserId\)/g) || [];
  assert.equal(calls.length, 0);
});
