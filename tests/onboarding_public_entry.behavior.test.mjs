import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const html = readFileSync(new URL("../liff/onboarding.html", import.meta.url), "utf8");

function functionBody(name) {
  const start = html.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `expected ${name} to exist`);
  const paramsEnd = html.indexOf(") {", start);
  const brace = html.indexOf("{", paramsEnd);
  let depth = 0;
  for (let i = brace; i < html.length; i += 1) {
    if (html[i] === "{") depth += 1;
    if (html[i] === "}") depth -= 1;
    if (depth === 0) return html.slice(brace + 1, i);
  }
  assert.fail(`could not parse ${name}`);
}

test("logged-out visitors see public actions instead of being auto-redirected", () => {
  const init = functionBody("init");
  assert.match(init, /renderPublicEntry\(\{ liffReady: true, liffId \}\)/);
  assert.doesNotMatch(init, /if \(!liff\.isLoggedIn\(\)\) \{\s*liff\.login\(\)/);
});

test("public entry provides a clear opt-in LINE login action", () => {
  const render = functionBody("renderPublicEntry");
  assert.match(render, /開始 14 天免費體驗/);
  assert.match(render, /使用 LINE 安全登入/);
  assert.match(render, /不會讀取你的聊天內容/);
  assert.match(render, /startTrialLoginBtn/);
});

test("public entry remains useful when LIFF initialization fails", () => {
  const init = functionBody("init");
  const render = functionBody("renderPublicEntry");
  assert.match(init, /catch \(err\) \{\s*renderPublicEntry/);
  assert.doesNotMatch(html, /LIFF 初始化失敗/);
  assert.match(render, /https:\/\/liff\.line\.me\//);
});

test("desktop and mobile visitors can navigate without logging in", () => {
  assert.match(html, /href="\/">返回首頁/);
  assert.match(html, /href="\/trial-14\.html">查看體驗與方案/);
  assert.match(html, /href="\/faq\.html">常見問題/);
  assert.match(html, /@media \(max-width: 520px\)/);
  assert.match(html, /\.public-entry-links \{\s*grid-template-columns: 1fr/);
  assert.match(html, /min-height: 54px/);
});
