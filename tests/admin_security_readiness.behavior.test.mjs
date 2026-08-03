import assert from "node:assert/strict";
import test from "node:test";
import vm from "node:vm";
import { readFileSync } from "node:fs";

const html = readFileSync(new URL("../admin.html", import.meta.url), "utf8");

function functionSource(name, nextName) {
  const start = html.indexOf(`function ${name}(`);
  const normalEnd = html.indexOf(`function ${nextName}(`, start);
  const asyncEnd = html.indexOf(`async function ${nextName}(`, start);
  const candidates = [normalEnd, asyncEnd].filter((index) => index >= 0);
  const end = candidates.length ? Math.min(...candidates) : -1;
  assert.ok(start >= 0 && end > start, `${name} source not found`);
  return html.slice(start, end);
}

test("security readiness is a server-evidenced independent page", () => {
  assert.match(html, /href="\/admin\?page=security"/);
  assert.match(html, /data-admin-page="security"/);
  assert.match(html, /\/api\/admin\/security-readiness/);
  assert.match(html, /禁止正式公開營運/);
  assert.doesNotMatch(html, /type="checkbox"[^>]*security/i);
});

test("admin scripts parse after security page integration", () => {
  for (const match of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) new vm.Script(match[1]);
});

test("security evidence renders passed failed and not-checked as distinct safe states", () => {
  const context = {
    escapeHtml: (value) => String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;"),
  };
  vm.runInNewContext(
    `${functionSource("securityStatusPresentation", "securityItemMarkup")}
${functionSource("securityItemMarkup", "loadSecurityReadiness")}
this.securityItemMarkup = securityItemMarkup;`,
    context,
  );

  const passed = context.securityItemMarkup({number: 1, name: "機密", status: "passed", checked_at: "2026-08-03T12:00:00+08:00", evidence_source: "automated_test", evidence: "掃描通過", remediation: ""});
  const failed = context.securityItemMarkup({number: 2, name: "輸入", status: "failed", checked_at: "2026-08-03T12:01:00+08:00", evidence_source: "automated_test", evidence: "<script>失敗</script>", remediation: "重新執行負向測試"});
  const unchecked = context.securityItemMarkup({number: 3, name: "登入", status: "not_checked", checked_at: null, evidence_source: null, evidence: "尚無證據", remediation: "完成正式驗收"});

  assert.match(passed, />通過</);
  assert.match(passed, /automated_test/);
  assert.match(failed, />未通過</);
  assert.match(failed, /重新執行負向測試/);
  assert.doesNotMatch(failed, /<script>/);
  assert.match(unchecked, />未檢查</);
  assert.match(unchecked, /尚未產生/);
});
