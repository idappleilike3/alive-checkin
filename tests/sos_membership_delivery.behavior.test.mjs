import fs from "node:fs";
import test from "node:test";
import assert from "node:assert/strict";

const page = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");

test("SOS area explains free-member web-only alerts", () => {
  assert.match(page, /免費會員的 SOS 警報將顯示於守護人的網頁內；如需即時推播通知，請升級為付費方案。/);
});

test("web-only SOS response displays the backend membership message", () => {
  assert.match(page, /result\s*&&\s*result\.delivery_mode\s*===\s*["']web_only["']/);
  assert.match(page, /result\.message/);
});

test("guardian center displays pending SOS message and created time", () => {
  assert.match(page, /latest_sos_message/);
  assert.match(page, /latest_sos_created_at/);
  assert.match(page, /待處理警報/);
});
