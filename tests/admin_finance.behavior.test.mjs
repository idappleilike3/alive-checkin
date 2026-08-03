import assert from "node:assert/strict";
import test from "node:test";
import vm from "node:vm";
import { readFileSync } from "node:fs";

const html = readFileSync(new URL("../admin.html", import.meta.url), "utf8");

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

test("admin scripts remain valid JavaScript", () => {
  const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((match) => match[1]);
  for (const source of scripts) new vm.Script(source);
});
