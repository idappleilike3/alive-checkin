import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");

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

test("member reminder save gives feedback beside the button for the full request", () => {
  const save = functionBody("saveMemberDailyReminder");

  assert.match(html, /id="memberDailyReminderSaveFeedback"[^>]*aria-live="polite"/);
  assert.match(save, /saveButton\.disabled = true/);
  assert.match(save, /saveButton\.textContent = "儲存中…"/);
  assert.match(save, /setMemberReminderSaveFeedback\("saving"/);
  assert.match(save, /setMemberReminderSaveFeedback\("success"/);
  assert.match(save, /setMemberReminderSaveFeedback\("error"/);
  assert.match(save, /finally\s*{/);
  assert.match(save, /saveButton\.disabled = false/);
  assert.match(save, /saveButton\.textContent = originalLabel/);
});

test("using plan default reminder times persists them and confirms success", () => {
  const applyDefaults = functionBody("applyAndSaveMemberReminderDefaults");

  assert.match(applyDefaults, /defaultTimesForDailyCount\(count\)/);
  assert.match(applyDefaults, /await saveMemberDailyReminder/);
  assert.match(
    applyDefaults,
    /已套用方案預設時間並儲存成功/,
    "the user must see an explicit confirmation only after the save succeeds",
  );
  assert.match(
    html,
    /dailyDefaultsBtn\.addEventListener\("click", applyAndSaveMemberReminderDefaults\)/,
  );
});
