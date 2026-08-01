import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";

const html = readFileSync(new URL("../admin.html", import.meta.url), "utf8");

function functionBody(name) {
  const start = html.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `expected ${name} to exist`);
  const brace = html.indexOf("{", start);
  let depth = 0;
  for (let index = brace; index < html.length; index += 1) {
    if (html[index] === "{") depth += 1;
    if (html[index] === "}") depth -= 1;
    if (depth === 0) return html.slice(brace + 1, index);
  }
  assert.fail(`could not parse ${name}`);
}

test("ordinary paid plan change never sends the old expiry back to server", () => {
  const update = functionBody("updatePlan");
  assert.match(update, /line_user_id:\s*lineUserId/);
  assert.match(update, /payment_status:\s*plan\.startsWith\("paid"\)/);
  assert.doesNotMatch(update, /paid_until\s*:/);
  assert.match(update, /data\.paid_until/);
  assert.match(update, /新到期日/);
});

test("G799 is an independent gift action with explicit start and end", () => {
  assert.doesNotMatch(
    html,
    /\["trial",\s*"free"[^\]]*"G799"/s,
    "G799 must not be mixed into the ordinary plan selector"
  );
  assert.match(html, /data-action="grant-g799"/);
  assert.match(html, /id="gift-start-/);
  assert.match(html, /id="gift-end-/);
  assert.match(html, />設定 G799 贈送資格</);

  const grant = functionBody("grantG799");
  assert.match(grant, /plan:\s*"G799"/);
  assert.match(grant, /gift_started_at:\s*giftStart/);
  assert.match(grant, /gift_ends_at:\s*giftEnd/);
  assert.match(grant, /贈送到期日/);
});

test("member row reports expiry records that require manual review", () => {
  assert.match(html, /expiry_review_required/);
  assert.match(html, /缺少可靠付款或異動時間，請人工確認到期日/);
});
