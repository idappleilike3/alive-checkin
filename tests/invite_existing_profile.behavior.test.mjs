import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const root = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const onboarding = readFileSync(new URL("../liff/onboarding.html", import.meta.url), "utf8");

test("guardian invite loads the authoritative saved member profile before showing fields", () => {
  assert.match(root, /applyAuthoritativeInviteeProfile\(preview\)/);
  assert.match(root, /preview\?\.invitee_profile/);
  assert.match(root, /你的會員資料已完成/);
});

test("guardian invite only asks an existing member to confirm this invitation relationship", () => {
  assert.match(root, /invitee_profile\.profile_completed/);
  assert.match(root, /showInviteGuardianProfileForm\(\{\s*existingProfile:\s*true/);
});

test("an already-bound pair shows completion instead of another profile form", () => {
  assert.match(root, /preview\?\.already_bound/);
  assert.match(root, /你已完成與.*守護綁定，不需要再次填寫/);
});

test("completed onboarding has no repeat-share action or legacy invite redirect", () => {
  assert.doesNotMatch(onboarding, /再次一鍵邀請分享/);
  assert.doesNotMatch(onboarding, /location\.replace\(`https:\/\/line\.me\/R\/app\/\$\{liffId\}\?invite_from=/);
});

test("canonical onboarding persists the member's chosen name with the other profile fields", () => {
  assert.match(onboarding, /display_name:\s*String\(document\.getElementById\("displayName"\)/);
});
