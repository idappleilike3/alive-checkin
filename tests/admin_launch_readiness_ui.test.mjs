import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";

const html = readFileSync(new URL("../admin.html", import.meta.url), "utf8");

test("admin exposes every quantified launch gate and stop state", () => {
  for (const id of [
    "launchCheckinRate",
    "launchMissed",
    "launchDuplicates",
    "launchSosRate",
    "launchBindRate",
    "launchPayment",
    "launchExpiry",
    "launchGateBanner",
    "launchFailures",
  ]) {
    assert.match(html, new RegExp(`id="${id}"`));
  }
  assert.match(html, /停止新增測試者/);
  assert.match(html, /\/api\/admin\/launch-readiness/);
});

test("beta roster shows caps and uses the protected admin API", () => {
  assert.match(html, /id="betaCountA">0／10/);
  assert.match(html, /id="betaCountB399">0／20/);
  assert.match(html, /id="betaCountB799">0／10/);
  assert.match(html, /\/api\/admin\/beta-members/);
  assert.match(html, /const betaAssignForm = \$\("betaAssignForm"\)/);
});

test("admin has one canonical beta management flow", () => {
  for (const obsoleteId of [
    "betaMemberSelect",
    "betaCohortSelect",
    "betaAssignBtn",
    "betaMemberList",
  ]) {
    assert.doesNotMatch(html, new RegExp(`id="${obsoleteId}"`));
  }
  assert.doesNotMatch(html, /\/api\/admin\/beta-program\/assign/);
  assert.doesNotMatch(html, /function assignBetaMember\(/);
  assert.match(html, /<select id="betaLineUserId">/);
  assert.match(html, /<input id="betaLineUserIdManual"/);
  assert.match(html, /\$\("betaLineUserId"\)\.innerHTML/);
  assert.match(html, /if \(!manualLineUserId && !selectedLineUserId\)/);
});

test("daily member push summary exposes the latest LINE failure reason", () => {
  assert.match(html, /row\.latest_failure_detail/);
  assert.match(html, /最近失敗/);
});


test("LINE push failures are translated to clear Traditional Chinese", () => {
  assert.match(html, /function linePushFailureText\(detail\)/);
  assert.match(html, /收件人的 LINE ID 無效或已失效/);
  assert.match(html, /LINE 無法將訊息傳送給收件人/);
  assert.match(html, /LINE 推播額度或發送頻率已達限制/);
  assert.match(html, /linePushFailureText\(row\.latest_failure_detail\)/);
  assert.doesNotMatch(
    html,
    /最近失敗：\$\{escapeHtml\(row\.latest_failure_detail\)\}/,
  );
});
