import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";

const html = readFileSync(new URL("../admin.html", import.meta.url), "utf8");

test("admin has semi-automatic LINE acceptance controls without arbitrary send action", () => {
  assert.match(html, /id="lineAcceptanceForm"/);
  assert.match(html, /function renderLineAcceptance/);
  assert.match(html, /\/api\/admin\/line-acceptance/);
  assert.match(html, /手機確認通過/);
  assert.match(html, /手機確認失敗/);
  assert.doesNotMatch(html, /id="lineAcceptanceSend"/);
});

test("acceptance rendering escapes values", () => {
  const source = html.match(/function renderLineAcceptance[\s\S]*?async function loadLineAcceptance/)?.[0] || "";
  assert.match(source, /escapeHtml\(row\.display_name/);
  assert.match(source, /escapeHtml\(row\.note/);
  assert.match(source, /escapeHtml\(row\.member_ref/);
});
