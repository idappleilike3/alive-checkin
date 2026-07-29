import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import vm from "node:vm";

const memberHtml = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const memberScript = [...memberHtml.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)]
  .map((match) => match[1])
  .find((source) => source.includes("function renderMemberCenter")) || "";
const adminHtml = readFileSync(new URL("../admin.html", import.meta.url), "utf8");
const adminScript = adminHtml.match(/<script>([\s\S]*?)<\/script>/)?.[1] || "";

function functionSource(script, signature, nextSignature) {
  const start = script.indexOf(signature);
  const end = script.indexOf(nextSignature, start);
  if (start < 0 || end < 0) throw new Error(`${signature} source not found`);
  return script.slice(start, end);
}

test("member support submission uses authenticated API and refreshes history", async () => {
  const requests = [];
  let refreshed = 0;
  const context = {
    lineUserId: "U-member",
    authHeaders: async () => ({"Content-Type": "application/json"}),
    fetch: async (url, options) => {
      requests.push({url, options});
      return {ok: true, json: async () => ({ticket: {id: "T-1"}})};
    },
    loadMemberSupportTickets: async () => { refreshed += 1; },
    Error,
  };
  vm.runInNewContext(
    `${functionSource(
      memberScript,
      "    async function apiCreateSupportTicket",
      "    async function apiGetSupportTickets",
    )}
${functionSource(
      memberScript,
      "    async function apiGetSupportTickets",
      "    function renderMemberSupportTickets",
    )}
this.apiCreateSupportTicket = apiCreateSupportTicket;`,
    context,
  );

  await context.apiCreateSupportTicket({
    category: "一般詢問",
    subject: "我要怎麼修改提醒時間？",
    message: "請協助",
    reply_channel: "line",
  });

  assert.equal(requests[0].url, "/api/support/tickets");
  const body = JSON.parse(requests[0].options.body);
  assert.equal(body.line_user_id, "U-member");
  assert.equal(body.reply_channel, "line");
  assert.equal(body.email, undefined);
  assert.equal(refreshed, 1);
});

test("member support history escapes hostile server content", () => {
  const list = {innerHTML: ""};
  const context = {
    document: {getElementById: (id) => id === "memberSupportList" ? list : null},
    escapeHtml: (value) => String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;"),
  };
  vm.runInNewContext(
    `${functionSource(
      memberScript,
      "    function renderMemberSupportTickets",
      "    async function loadMemberSupportTickets",
    )}
this.renderMemberSupportTickets = renderMemberSupportTickets;`,
    context,
  );

  context.renderMemberSupportTickets([{
    id: "T-1",
    category: "其他",
    subject: '<img src=x onerror="globalThis.compromised=true">',
    message: "<script>bad()</script>",
    status: "waiting_user",
    reply: "請補資料",
  }]);

  assert.doesNotMatch(list.innerHTML, /<img|<script|onerror="/);
  assert.match(list.innerHTML, /&lt;img/);
  assert.equal(context.compromised, undefined);
});

test("support UI keeps free-form LINE workflow without email or push reply controls", () => {
  assert.doesNotMatch(memberHtml, /id="memberSupportCategory"/);
  assert.doesNotMatch(memberHtml, /id="memberSupportEmail"/);
  assert.doesNotMatch(memberHtml, /id="memberSupportReplyChannel"/);
  assert.match(memberHtml, /1–3 個工作天內/);
  assert.match(memberHtml, /常見問題與解答/);
  assert.doesNotMatch(adminHtml, /data-support-channel/);
  assert.doesNotMatch(adminHtml, /LINE 私訊（主動推播，計入訊息量）/);
  assert.match(adminHtml, /LINE Official Account Manager/);
});
