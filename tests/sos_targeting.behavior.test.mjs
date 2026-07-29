import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const page = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");

test("SOS page shows guardian checkboxes and defaults empty selection to two", () => {
  assert.match(page, /id="sosGuardianTargets"/);
  assert.match(page, /name="sosGuardian"/);
  assert.match(page, /系統仍會預設通知前兩位/);
  assert.match(page, /function selectedSosGuardianIds\(\)/);
  assert.match(page, /checked\.length \? checked : eligibleIds\.slice\(0, 2\)/);
});
test("SOS request sends only the selected guardian ids", () => {
  assert.match(
    page,
    /sosPayload\.guardian_line_user_ids\s*=\s*selectedSosGuardianIds\(\)/,
  );
  assert.match(
    page,
    /\.\.\.sosPayload,\s*guardian_line_user_ids:\s*sosPayload\.guardian_line_user_ids/,
  );
});
