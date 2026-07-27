import fs from "node:fs";
import test from "node:test";
import assert from "node:assert/strict";

const memberPage = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");
const adminPage = fs.readFileSync(new URL("../admin.html", import.meta.url), "utf8");

test("member center exposes recurring status and authenticated cancellation", () => {
  assert.match(memberPage, /id="memberAutoRenewStatus"/);
  assert.match(memberPage, /id="memberAutoRenewRequested"/);
  assert.match(memberPage, /id="memberCancelAutoRenewBtn"/);
  assert.match(memberPage, /\/api\/billing\/preferences/);
  assert.match(memberPage, /\/api\/billing\/cancel/);
});

test("checkout uses a provider-neutral hosted payment descriptor", () => {
  assert.match(memberPage, /checkout\.checkout_url/);
  assert.doesNotMatch(memberPage, /藍新|綠界/);
});

test("admin order table offers audited refund controls", () => {
  assert.match(adminPage, /refundPaymentOrder/);
  assert.match(adminPage, /\/api\/admin\/payments\/refund/);
  assert.match(adminPage, /退款原因/);
  assert.match(adminPage, /可退/);
});
