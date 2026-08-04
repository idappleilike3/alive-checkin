import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";

const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");

test("member birthday uses explicit year month day selects and saves ISO date", () => {
  assert.match(html, /id="memberProfileBirthdayYear"/);
  assert.match(html, /id="memberProfileBirthdayMonth"/);
  assert.match(html, /id="memberProfileBirthdayDay"/);
  assert.match(html, /function memberProfileBirthdayValue\(\)/);
  assert.match(html, /const birthday = memberProfileBirthdayValue\(\);/);
});
