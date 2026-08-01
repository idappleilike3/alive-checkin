import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const html = fs.readFileSync(new URL("../admin.html", import.meta.url), "utf8");

test("member management has dedicated 21-day reset panel", () => {
  for (const copy of ["重置 21 天封測帳號", "重置選取帳號", "目前沒有可重置的 21 天封測測試帳號"]) {
    assert.ok(html.includes(copy), copy);
  }
});

test("reset candidates load independently and explain an empty whitelist", () => {
  assert.match(html, /loadBetaResetCandidates\(\)/);
  assert.match(html, /Promise\.allSettled/);
  assert.ok(html.includes("尚未設定測試帳號白名單"));
  assert.ok(html.includes("白名單內目前沒有符合資格的 21 天封測帳號"));
});

test("reset request carries confirmation and candidate version", () => {
  assert.match(html, /account_state_version:\s*version/);
  assert.match(html, /confirm:\s*true/);
  assert.match(html, /重置中…/);
});

test("copy distinguishes reset from permanent delete", () => {
  assert.ok(html.includes("可重新使用 21 天封測連結綁定"));
  assert.ok(html.includes("永久刪除測試帳號"));
});
