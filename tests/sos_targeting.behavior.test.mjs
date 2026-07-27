import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const page = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");

test("SOS page offers one, multiple, or all core guardian targets", () => {
  assert.match(page, /id="sosGuardianTargets"/);
  assert.match(page, /name="sosTargetMode" value="one"/);
  assert.match(page, /name="sosTargetMode" value="many"/);
  assert.match(page, /name="sosTargetMode" value="all"/);
  assert.match(page, /function selectedSosGuardianIds\(\)/);
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
