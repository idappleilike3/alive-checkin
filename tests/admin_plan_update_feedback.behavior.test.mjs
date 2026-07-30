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

test("beta assignment accepts a pasted LINE user ID and gives visible selection feedback", () => {
  assert.match(html, /id="betaLineUserIdManual"/);
  assert.match(
    html,
    /const manualLineUserId = \$\("betaLineUserIdManual"\)\.value\.trim\(\)/
  );
  assert.match(html, /line_user_id: manualLineUserId \|\| \$\("betaLineUserId"\)\.value/);
  assert.match(html, /plan: `beta_\$\{\$\("betaCohort"\)\.value\}`/);
  assert.match(html, /已選擇會員：/);
});

test("member rows use an explicit selector id instead of onchange-only saving", () => {
  assert.match(html, /id="plan-select-[^"]*"/);
  assert.doesNotMatch(html, /onchange="updatePlan\(/);
});

test("every member plan selector has an explicit save button and row-level status", () => {
  assert.match(html, /class="plan-save-button"/);
  assert.match(html, />儲存方案<\/button>/);
  assert.match(html, /data-action="save-plan"/);
  assert.doesNotMatch(html, /onclick="savePlanForMember\(/);
  assert.match(html, /usersBody.*addEventListener\("click"/s);
  assert.match(html, /id="plan-status-[^"]*"/);
});

test("member management keeps fifteen columns readable with horizontal scrolling", () => {
  assert.match(html, /class="table-wrap member-table-wrap"/);
  assert.match(html, /class="member-table"/);
  assert.match(html, /\.member-table\s*{\s*min-width:\s*2400px/s);
  assert.match(html, /\.member-plan-cell\s*{\s*min-width:\s*300px/s);
});

test("plan saving shows a fixed global result and records the saved selection", () => {
  const update = functionBody("updatePlan");

  assert.match(html, /id="planSaveToast"/);
  assert.match(update, /selectElement\.dataset\.savedPlan = plan/);
  assert.match(update, /showPlanSaveToast\([^)]*"success"/s);
  assert.match(update, /showPlanSaveToast\([^)]*"error"/s);
});

test("member plan selector can explicitly choose every 21-day beta cohort", () => {
  assert.match(html, /"beta_A"/);
  assert.match(html, /"beta_B399"/);
  assert.match(html, /"beta_B799"/);
  assert.match(html, /21 天封測 A｜799 年費權益/);
  assert.match(html, /21 天封測 B399｜399 年費權益/);
  assert.match(html, /21 天封測 B799｜799 年費權益/);
});
