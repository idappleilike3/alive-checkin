import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";

const html = readFileSync(new URL("../admin.html", import.meta.url), "utf8");

function functionBody(name) {
  const start = html.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `expected ${name} to exist`);
  const brace = html.indexOf("{", html.indexOf(")", start));
  let depth = 0;
  for (let index = brace; index < html.length; index += 1) {
    if (html[index] === "{") depth += 1;
    if (html[index] === "}") depth -= 1;
    if (depth === 0) return html.slice(brace + 1, index);
  }
  assert.fail(`could not parse ${name}`);
}

test("member and push delivery tables expose independent pagination controls", () => {
  assert.match(html, /id="memberPagination"/);
  assert.match(html, /id="pushDeliveryPagination"/);
  assert.match(html, /const ADMIN_PAGE_SIZE = 20/);
  assert.match(html, /上一頁/);
  assert.match(html, /下一頁/);
});

test("members render only the current 20-row slice", () => {
  const render = functionBody("renderMemberPage");
  assert.match(render, /slice\(/);
  assert.match(render, /ADMIN_PAGE_SIZE/);
  assert.match(render, /memberPagination/);
});

test("push deliveries request 20 rows at the selected offset", () => {
  const load = functionBody("loadPushDeliveries");
  assert.match(load, /limit: String\(ADMIN_PAGE_SIZE\)/);
  assert.match(load, /offset: String\(\(pushDeliveryPage - 1\) \* ADMIN_PAGE_SIZE\)/);
  assert.match(load, /data\.total/);
  assert.match(load, /pushDeliveryPagination/);
});

test("push filters reset delivery results to the first page", () => {
  assert.match(html, /pushDeliveryPage = 1;\s*await loadPushDeliveries/);
});

test("admin requests record their authentication generation", () => {
  const fetchBody = functionBody("adminFetch");
  assert.match(fetchBody, /const requestGeneration = adminAuthGeneration/);
  assert.match(fetchBody, /requestGeneration === adminAuthGeneration/);
});
