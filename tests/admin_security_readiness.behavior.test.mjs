import assert from "node:assert/strict";
import test from "node:test";
import vm from "node:vm";
import { readFileSync } from "node:fs";

const html = readFileSync(new URL("../admin.html", import.meta.url), "utf8");

test("security readiness is a server-evidenced independent page", () => {
  assert.match(html, /href="\/admin\?page=security"/);
  assert.match(html, /data-admin-page="security"/);
  assert.match(html, /\/api\/admin\/security-readiness/);
  assert.match(html, /禁止正式公開營運/);
  assert.doesNotMatch(html, /type="checkbox"[^>]*security/i);
});

test("admin scripts parse after security page integration", () => {
  for (const match of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) new vm.Script(match[1]);
});
