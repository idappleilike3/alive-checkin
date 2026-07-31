import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const page = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");

function functionSource(name) {
  const pattern = new RegExp(`(?:async\\s+)?function\\s+${name}\\s*\\(`);
  const match = pattern.exec(page);
  assert.ok(match, `missing function: ${name}`);
  const start = match.index;
  const brace = page.indexOf("{", start);
  let depth = 0;
  for (let index = brace; index < page.length; index += 1) {
    if (page[index] === "{") depth += 1;
    if (page[index] === "}") {
      depth -= 1;
      if (depth === 0) return page.slice(start, index + 1);
    }
  }
  throw new Error(`unterminated function: ${name}`);
}

test("opening your own guardian invite explains why it cannot be accepted and returns to member center", () => {
  const events = [];
  const sandbox = vm.createContext({
    alert: (message) => events.push(["alert", message]),
    clearInviteFromUrl: () => events.push(["clear"]),
    clearPendingGuardianInvite: () => events.push(["clear-pending"]),
    closeInviteAcceptPrompt: () => events.push(["close"]),
    showTab: (tab) => events.push(["tab", tab]),
  });
  new vm.Script(
    `${functionSource("handleSelfGuardianInvite")}\n` +
    "this.handleSelfGuardianInvite = handleSelfGuardianInvite;"
  ).runInContext(sandbox);

  const result = sandbox.handleSelfGuardianInvite();

  assert.equal(result.code, "self_invite");
  assert.match(events[0][1], /不能接受自己發出的邀請/);
  assert.deepEqual(
    events.slice(1).map((event) => Array.from(event)),
    [["clear"], ["clear-pending"], ["close"], ["tab", "member"]]
  );
});
