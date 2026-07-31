import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";

const html = readFileSync(new URL("../admin.html", import.meta.url), "utf8");

test("push log cards show recipient identity and complete Chinese failure guidance", () => {
  assert.match(html, /recipient_display_name/);
  assert.match(html, /recipient_type_label/);
  assert.match(html, /LINE User ID/);
  assert.match(html, /失敗原因/);
  assert.match(html, /處理建議/);
  assert.match(html, /技術訊息/);
  assert.match(html, /latest_failure_reason_zh/);
  assert.match(html, /latest_failure_action_zh/);
});

test("push log output escapes every server supplied detail", () => {
  assert.match(html, /escapeHtml\(log\.recipient_display_name/);
  assert.match(html, /escapeHtml\(log\.line_user_id/);
  assert.match(html, /escapeHtml\(log\.failure_reason_zh/);
  assert.match(html, /escapeHtml\(log\.failure_action_zh/);
  assert.match(html, /escapeHtml\(log\.detail/);
});
