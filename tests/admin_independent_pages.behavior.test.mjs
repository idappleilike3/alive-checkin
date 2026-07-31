import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";

const html = readFileSync(new URL("../admin.html", import.meta.url), "utf8");

test("admin navigation uses independent page URLs instead of same-page anchors", () => {
  for (const page of [
    "operations",
    "members",
    "guardian-operations",
    "incidents",
    "beta-program",
    "orders",
    "support",
    "analytics",
    "line-cost",
    "test-center",
    "seo",
    "system",
  ]) {
    assert.match(html, new RegExp(`href="/admin\\?page=${page}"`));
  }
  assert.doesNotMatch(html, /class="admin-nav"[\s\S]*?href="#operations"/);
});

test("admin navigation groups related pages into no more than three levels", () => {
  for (const group of [
    "營運管理",
    "會員與守護",
    "安全與通知",
    "商業營運",
    "客服與系統",
  ]) {
    assert.match(html, new RegExp(`<summary[^>]*>[\\s\\S]*?${group}`));
  }
  assert.match(html, /class="admin-subnav"/);
  assert.doesNotMatch(html, /class="admin-fourth-level"/);
});

test("admin page selection is allowlisted and falls back to operations", () => {
  assert.match(html, /const ADMIN_PAGES = new Set\(\[/);
  assert.match(html, /ADMIN_PAGES\.has\(requestedPage\) \? requestedPage : "operations"/);
  assert.match(html, /data-admin-page=/);
  assert.match(html, /aria-current/);
});

test("admin typography and controls remain readable", () => {
  assert.match(html, /--admin-body-size:\s*16px/);
  assert.match(html, /--admin-note-size:\s*15px/);
  assert.match(html, /--admin-control-height:\s*48px/);
  assert.match(html, /grid-template-columns:\s*280px minmax\(0,\s*1fr\)/);
  assert.match(html, /\.table-wrap\s*\{[^}]*overflow-x:\s*auto/s);
});

test("mobile admin uses a menu button, drawer, and backdrop", () => {
  assert.match(html, /id="adminNavToggle"/);
  assert.match(html, /aria-controls="adminSidebar"/);
  assert.match(html, /id="adminSidebar"/);
  assert.match(html, /id="adminNavBackdrop"/);
  assert.match(html, /@media \(max-width:\s*900px\)/);
  assert.match(html, /classList\.toggle\("is-open"/);
});
