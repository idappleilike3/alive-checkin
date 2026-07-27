import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import vm from "node:vm";

const html = readFileSync(new URL("../admin.html", import.meta.url), "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)?.[1] || "";

function functionSource(name, nextName) {
  const start = script.indexOf(`    function ${name}`);
  const end = script.indexOf(`    ${nextName}`, start);
  if (start < 0 || end < 0) throw new Error(`${name} source not found`);
  return script.slice(start, end);
}

test("beta roster renders counters, remaining days and hostile values safely", () => {
  const elements = new Map([
    ["betaCountA", {textContent: ""}],
    ["betaCountB399", {textContent: ""}],
    ["betaCountB799", {textContent: ""}],
    ["betaMembersBody", {innerHTML: ""}],
  ]);
  const context = {
    document: {
      getElementById: (id) => elements.get(id),
      querySelectorAll: () => [],
    },
  };
  vm.runInNewContext(
    `const $ = (id) => document.getElementById(id);
${functionSource("escapeHtml", "function renderBetaMembers")}
${functionSource("renderBetaMembers", "async function loadBetaMembers")}`,
    context,
  );
  const hostile = '<img src=x onerror="globalThis.compromised=true">';
  context.renderBetaMembers({
    counts: {A: 1, B399: 2, B799: 3},
    limits: {A: 10, B399: 20, B799: 10},
    members: [{
      display_name: hostile,
      line_user_id: '" onmouseover="alert(1)',
      source: hostile,
      cohort: "A",
      plan: "paid_799",
      remaining_days: 7,
      current_day: 15,
      milestones: {day_1: true, day_7: true, day_14: true, day_21: false},
    }],
  });

  assert.equal(elements.get("betaCountA").textContent, "1／10");
  assert.equal(elements.get("betaCountB399").textContent, "2／20");
  assert.equal(elements.get("betaCountB799").textContent, "3／10");
  assert.doesNotMatch(elements.get("betaMembersBody").innerHTML, /<img|onerror="/);
  assert.match(elements.get("betaMembersBody").innerHTML, /&lt;img/);
  assert.match(elements.get("betaMembersBody").innerHTML, /Day 15/);
  assert.match(elements.get("betaMembersBody").innerHTML, /D1 ✓・D7 ✓・D14 ✓・D21 —/);
  assert.match(elements.get("betaMembersBody").innerHTML, /剩 7 天/);
  assert.equal(context.compromised, undefined);
});
