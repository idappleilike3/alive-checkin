import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";

const html = readFileSync(new URL("../admin.html", import.meta.url), "utf8");

function functionBody(name) {
  const start = html.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `expected ${name} to exist`);
  const brace = html.indexOf("{", start);
  let depth = 0;
  for (let i = brace; i < html.length; i += 1) {
    if (html[i] === "{") depth += 1;
    if (html[i] === "}") depth -= 1;
    if (depth === 0) return html.slice(brace + 1, i);
  }
  assert.fail(`could not parse ${name}`);
}

test("admin plan selector keeps a visible success or failure reminder after refresh", () => {
  const update = functionBody("updatePlan");

  assert.match(update, /selectElement\.disabled = true/);
  assert.match(update, /await refresh\(\)/);
  assert.match(update, /方案已更新成功/);
  assert.match(update, /setAttribute\("role", "status"\)/);
  assert.match(update, /catch\s*\(/);
  assert.match(update, /方案更新失敗/);
  assert.match(update, /selectElement\.value = previousPlan/);
  assert.match(update, /finally\s*{/);
  assert.match(update, /selectElement\.disabled = false/);
});

test("member rows use an explicit selector id instead of onchange-only saving", () => {
  assert.match(html, /id="plan-select-[^"]*"/);
  assert.doesNotMatch(html, /onchange="updatePlan\(/);
});

test("every member plan selector has an explicit save button and row-level status", () => {
  assert.match(html, /class="plan-save-button"/);
  assert.match(html, />儲存方案<\/button>/);
  assert.match(html, /savePlanForMember\('[^']*'\)/);
  assert.match(html, /id="plan-status-[^"]*"/);
});
