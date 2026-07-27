import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const page = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");

function targetingSource() {
  const start = page.indexOf("function safetyGuardTargetCandidates");
  const end = page.indexOf("function formatSafetyGuardStatus", start);
  assert.notEqual(start, -1, "safety guardian target controller is missing");
  assert.notEqual(end, -1, "safety guardian target controller end marker is missing");
  return page.slice(start, end);
}

function controller(contacts, checkedIds = []) {
  const sandbox = vm.createContext({
    currentGuardianContacts: () => contacts,
    contactRoleOf: (contact) => contact.contact_role || "guardian",
    isContactBound: (contact) => contact.binding_status === "accepted",
    contactPeerLineId: (contact) => contact.line_user_id || "",
    document: {
      getElementById: () => null,
      querySelectorAll: () => checkedIds.map((value) => ({value})),
      querySelector: () => ({value: "many"}),
    },
  });
  new vm.Script(
    `${targetingSource()}
     this.candidates = safetyGuardTargetCandidates;
     this.selectedIds = selectedSafetyGuardGuardianIds;`,
  ).runInContext(sandbox);
  return sandbox;
}

test("target candidates contain only bound core guardians", () => {
  const sandbox = controller([
    {line_user_id: "U_mom", contact_role: "guardian", binding_status: "accepted", is_primary: true},
    {line_user_id: "U_friend", contact_role: "guardian", binding_status: "accepted", is_primary: false},
    {line_user_id: "U_phone", contact_role: "emergency", binding_status: "accepted", is_primary: true},
  ]);
  assert.deepEqual(
    Array.from(sandbox.candidates(), (item) => item.line_user_id),
    ["U_mom"],
  );
});

test("one or multiple checked guardians become the API target list", () => {
  const contacts = [
    {line_user_id: "U_mom", binding_status: "accepted", is_primary: true},
    {line_user_id: "U_sister", binding_status: "accepted", is_primary: true},
  ];
  const sandbox = controller(contacts, ["U_sister", "U_mom"]);
  assert.deepEqual(Array.from(sandbox.selectedIds()), ["U_sister", "U_mom"]);
});

test("199 duration is rendered as fifteen minutes", () => {
  assert.match(page, /value="0\.25"[^>]*>\s*15 分鐘/);
  assert.match(page, /199 方案：15 分鐘/);
});
