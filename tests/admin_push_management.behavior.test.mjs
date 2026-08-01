import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";

const html = readFileSync(new URL("../admin.html", import.meta.url), "utf8");

function functionBody(name) {
  const start = html.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `expected ${name} to exist`);
  const brace = html.indexOf("{", start);
  let depth = 0;
  for (let index = brace; index < html.length; index += 1) {
    if (html[index] === "{") depth += 1;
    if (html[index] === "}") depth -= 1;
    if (depth === 0) return html.slice(brace + 1, index);
  }
  assert.fail(`could not parse ${name}`);
}

test("push management is registered under safety and notifications", () => {
  assert.match(html, /href="\/admin\?page=push-management"/);
  assert.match(html, /data-admin-page="push-management"/);
  assert.match(html, /"push-management"/);
  assert.match(html, /推播管理/);
});

test("campaign editor supports approved content, audiences, and explicit members", () => {
  for (const id of [
    "pushCampaignName", "pushContentType", "pushCampaignText",
    "pushTemplateKey", "pushTemplateVariables", "pushExplicitMembers",
    "pushSaveBtn", "pushPrepareBtn", "pushScheduleBtn", "pushCancelBtn",
  ]) assert.match(html, new RegExp(`id="${id}"`));
  assert.match(html, /name="pushAudience"/);
  assert.match(html, /day7_pin_reminder/);
  assert.match(html, /beta_day2_private_note/);
});

test("every lifecycle status has a clear Traditional Chinese label", () => {
  for (const label of ["草稿", "待排程", "已排程", "發送中", "已完成", "部分失敗", "全部失敗", "已取消"]) {
    assert.match(html, new RegExp(label));
  }
});

test("only super admin sees enabled mutation controls", () => {
  const access = functionBody("applyPushManagementAccess");
  assert.match(access, /adminRole === "super_admin"/);
  assert.match(access, /只有最高管理員可以新增、修改、排程或取消推播/);
  assert.match(access, /push-management-mutation/);
});

test("create edit prepare schedule and cancel use the dedicated APIs", () => {
  const save = functionBody("savePushCampaign");
  assert.match(save, /\/api\/admin\/push-campaigns/);
  assert.match(save, /\/edit/);
  const payload = functionBody("pushCampaignPayload");
  assert.match(payload, /plan_audiences/);
  assert.match(payload, /explicit_member_ids/);
  assert.match(functionBody("preparePushCampaign"), /\/prepare/);
  assert.match(functionBody("schedulePushCampaign"), /\/schedule/);
  assert.match(functionBody("cancelPushCampaign"), /\/cancel/);
});

test("versions and permanent delivery filters expose required audit details", () => {
  assert.match(html, /id="pushVersionHistory"/);
  assert.match(html, /修改前/);
  assert.match(html, /修改後/);
  assert.match(html, /id="pushDeliveryFilters"/);
  for (const label of ["會員姓名", "LINE UID", "當時方案", "預定時間", "實際時間", "嘗試次數", "中文原因", "處理建議", "技術訊息"]) {
    assert.match(html, new RegExp(label));
  }
});

test("there is no immediate campaign delivery control or API", () => {
  assert.doesNotMatch(html, /id="pushImmediateSend/);
  assert.doesNotMatch(html, /\/api\/admin\/push-campaigns\/[^`"']+\/send/);
});

test("admin scripts remain valid JavaScript", () => {
  const scripts = Array.from(html.matchAll(/<script>([\s\S]*?)<\/script>/g), (match) => match[1]);
  assert.ok(scripts.length);
  for (const source of scripts) assert.doesNotThrow(() => new Function(source));
});

test("scheduled timestamps round-trip through datetime-local in local time", () => {
  const converter = functionBody("toLocalDateTimeInput");
  assert.match(converter, /new Date\(/);
  assert.match(converter, /getFullYear\(\)/);
  assert.match(converter, /getHours\(\)/);
  const open = functionBody("openPushCampaign");
  assert.match(open, /toLocalDateTimeInput\(campaign\.scheduled_at\)/);
  assert.doesNotMatch(open, /campaign\.scheduled_at\)\.slice\(0, 16\)/);
});
