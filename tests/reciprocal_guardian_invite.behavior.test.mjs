import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (name) => fs.readFileSync(path.join(ROOT, name), "utf8");

test("guardian acceptance offers finish and reciprocal invite as separate actions", () => {
  const html = read("index.html");
  assert.match(html, /id="guardianBindFinishBtn"[^>]*>完成，開始守護/);
  assert.match(html, /id="guardianBindReciprocalBtn"[^>]*>我也想讓/);
  assert.match(html, /目前是.*單向關係/);
  assert.match(html, /async function startReciprocalGuardianInvite/);
});

test("reciprocal invite routes active members to sharing and used eligibility to pricing", () => {
  const html = read("index.html");
  assert.match(html, /lastAcceptedGuardianInviterId/);
  assert.match(html, /membership_source/);
  assert.match(html, /free_eligibility_already_used/);
  assert.match(html, /\/liff\/pricing\.html/);
  assert.match(html, /reciprocal_for/);
  assert.match(html, /reciprocal_name/);
});

test("share page explains reciprocal direction and still uses LINE friend picker", () => {
  const html = read("liff/share-invite.html");
  assert.match(html, /reciprocal_for/);
  assert.match(html, /reciprocal_name/);
  assert.match(html, /接受後，才會完成互相守護/);
  assert.match(html, /liff\.shareTargetPicker/);
});
