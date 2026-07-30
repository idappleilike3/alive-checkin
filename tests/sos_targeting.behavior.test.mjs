import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const page = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");

test("SOS page ranks up to five guardians and defaults empty selection to the first", () => {
  assert.match(page, /id="sosGuardianTargets"/);
  assert.match(page, /name="sosGuardian"/);
  assert.match(page, /一次最多 5 位/);
  assert.match(page, /function selectedSosGuardianIds\(\)/);
  assert.match(page, /map\(contactPeerLineId\)\.slice\(0, 5\)/);
  assert.match(page, /checked\.length \? checked\.slice\(0, 5\) : eligibleIds\.slice\(0, 1\)/);
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

test("original SOS modal displays the current location before sending", () => {
  assert.match(page, /id="sosLocationStatus"/);
  assert.match(page, /function renderSosCurrentLocation/);
  assert.match(page, /startSosLocationLookup\(\)\.then\(renderSosCurrentLocation\)/);
});
