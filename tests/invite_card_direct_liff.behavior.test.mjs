import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const sharePage = fs.readFileSync(
  new URL("../liff/share-invite.html", import.meta.url),
  "utf8",
);
const homePage = fs.readFileSync(
  new URL("../index.html", import.meta.url),
  "utf8",
);

test("guardian invitation card opens the story page before LIFF acceptance", () => {
  assert.match(
    sharePage,
    /const inviteUrl = new URL\("\/invite", appPublicOrigin\(\)\)/,
  );
  assert.match(sharePage, /inviteUrl\.searchParams\.set\("invite_from", safeId\)/);
  assert.match(
    sharePage,
    /inviteUrl\.searchParams\.set\("invite_token", inviteToken\)/,
  );
});

test("guardian invitation is handled immediately after LINE identity is ready", () => {
  const lineReadyIndex = homePage.indexOf(
    "const lineReady = lineUserId ? true : await initLine();",
  );
  const earlyPromptIndex = homePage.indexOf(
    "maybeShowInviteAcceptPrompt();",
    lineReadyIndex,
  );
  const memberLoadIndex = homePage.indexOf(
    "const memberReady = await initApp();",
    lineReadyIndex,
  );

  assert.ok(lineReadyIndex >= 0, "LINE initialization should exist");
  assert.ok(earlyPromptIndex > lineReadyIndex, "invite prompt should follow LINE identity");
  assert.ok(
    earlyPromptIndex < memberLoadIndex,
    "invite prompt must not wait for the full member bootstrap",
  );
});

test("successful guardian sharing returns to onboarding instead of closing the LIFF window", () => {
  const openShareStart = sharePage.indexOf("async function openShare()");
  const openShareEnd = sharePage.indexOf("function onRetry", openShareStart);
  const openShare = sharePage.slice(openShareStart, openShareEnd);

  assert.ok(openShareStart >= 0, "openShare should exist");
  assert.match(openShare, /if \(shared\)[\s\S]*goNextStep\(\)/);
  assert.doesNotMatch(openShare, /liff\.closeWindow\(\)/);
});
