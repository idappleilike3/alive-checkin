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

test("logged-out visitors continue through the explicit LIFF login flow", () => {
  const init = functionBody("init");
  assert.match(init, /if \(!liff\.isLoggedIn\(\)\) \{\s*liff\.login\(\{ redirectUri: buildOnboardingLoginRedirect\(\) \}\)/);
});

test("public entry provides one clear LINE login action", () => {
  const render = functionBody("renderPublicEntry");
  assert.match(render, /開始 14 天安心體驗/);
  assert.match(render, /liff\.login\(\{ redirectUri: buildOnboardingLoginRedirect\(\) \}\)/);
  assert.match(render, /不會讀取你的聊天內容/);
});

test("LIFF initialization failures return to the same public entry", () => {
  const init = functionBody("init");
  assert.match(init, /catch \(err\) \{\s*renderPublicEntry/);
  assert.doesNotMatch(html, /LIFF 初始化失敗/);
});

test("onboarding retains the three public navigation destinations", () => {
  assert.match(html, /href="\/">返回首頁/);
  assert.match(html, /href="\/pricing\.html">查看體驗與方案/);
  assert.match(html, /href="\/faq\.html">常見問答/);
  assert.match(html, /@media\s*\(max-width:\s*520px\)/);
});
