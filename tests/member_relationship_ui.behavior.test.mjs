import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import vm from "node:vm";

const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const script = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)]
  .map((match) => match[1])
  .find((source) => source.includes("function renderMemberCenter")) || "";

function functionSource(signature, nextSignature) {
  const start = script.indexOf(signature);
  const end = script.indexOf(nextSignature, start);
  if (start < 0 || end < 0) throw new Error(`${signature} source not found`);
  return script.slice(start, end);
}

test("guardian relationship accordion opens and closes one combined panel", () => {
  const button = {
    attrs: {},
    setAttribute(name, value) { this.attrs[name] = value; },
  };
  const panel = {hidden: true};
  const context = {$: (id) => id === "memberContactsToggleBtn" ? button : panel};
  vm.runInNewContext(
    `${functionSource(
      "    function setMemberContactsExpanded",
      "    function setMemberContactTab",
    )}
this.setMemberContactsExpanded = setMemberContactsExpanded;`,
    context,
  );

  context.setMemberContactsExpanded(true);
  assert.equal(button.attrs["aria-expanded"], "true");
  assert.equal(panel.hidden, false);
  context.setMemberContactsExpanded(false);
  assert.equal(button.attrs["aria-expanded"], "false");
  assert.equal(panel.hidden, true);
});

test("emergency contacts are telephone backup and never show LINE invite state", () => {
  const context = {
    escapeHtml: (value) => String(value),
    isContactBound: () => false,
    formatGuardianAddedAt: () => "",
    contactPeerDisplayName: (contact) => contact.name,
    guardianAvatarHtml: () => "",
  };
  vm.runInNewContext(
    `${functionSource(
      "    function renderContactManageRows",
      "    function formatGuardianAddedAt",
    )}
this.renderContactManageRows = renderContactManageRows;`,
    context,
  );
  const rendered = context.renderContactManageRows(
    [{id: "e1", name: "王阿姨", relationship: "鄰居", phone: "0900000000"}],
    "尚未新增緊急聯絡人",
    "emergency",
  );
  assert.match(rendered, /緊急聯絡人/);
  assert.match(rendered, /電話備援資料/);
  assert.doesNotMatch(rendered, /等待 LINE 綁定|一鍵邀請/);
});

test("almanac conversion returns Traditional Chinese terms", () => {
  const context = {};
  vm.runInNewContext(
    `${functionSource(
      "    function toTraditionalAlmanacTerm",
      "    function renderDailyAlmanac",
    )}
this.toTraditionalAlmanacTerm = toTraditionalAlmanacTerm;`,
    context,
  );
  assert.equal(context.toTraditionalAlmanacTerm("开市 动土 启钻 修坟"), "開市 動土 啟鑽 修墳");
  assert.equal(context.toTraditionalAlmanacTerm("诸事不宜 会亲友"), "諸事不宜 會親友");
});
