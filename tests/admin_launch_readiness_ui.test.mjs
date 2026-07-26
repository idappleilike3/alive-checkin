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
