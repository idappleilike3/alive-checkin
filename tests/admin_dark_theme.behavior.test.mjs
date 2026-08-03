import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";

const html = readFileSync(new URL("../admin.html", import.meta.url), "utf8");
const css = html.match(/<style>([\s\S]*?)<\/style>/)?.[1] || "";

function variable(name) {
  const match = css.match(new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})`));
  assert.ok(match, `${name} must be a six-digit theme color`);
  return match[1];
}

function luminance(hex) {
  const values = hex.slice(1).match(/../g).map((value) => parseInt(value, 16) / 255)
    .map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
  return 0.2126 * values[0] + 0.7152 * values[1] + 0.0722 * values[2];
}

test("approved eye-comfort palette uses dark surfaces and softened readable text", () => {
  const background = variable("--admin-bg");
  const surface = variable("--admin-surface");
  const elevated = variable("--admin-surface-elevated");
  const input = variable("--admin-input-bg");
  const text = variable("--admin-text");

  assert.ok(luminance(background) < 0.035);
  assert.ok(luminance(surface) < 0.06);
  assert.ok(luminance(elevated) < 0.09);
  assert.ok(luminance(input) < 0.05);
  assert.ok(luminance(text) > 0.7 && luminance(text) < 0.9);
  assert.match(html, /data-admin-theme="eye-comfort-dark"/);
});

test("dark theme covers every admin surface and interactive browser state", () => {
  for (const selector of [
    "body", ".admin-nav", ".panel", ".integration-card", ".stat", ".member-table-wrap",
    "th", "input, select, textarea", ":focus-visible", ":disabled", ":-webkit-autofill",
    ".admin-nav-backdrop", ".plan-save-toast", ".card-editor-shell", ".step-box",
  ]) {
    assert.ok(css.includes(selector), `${selector} must have dark-theme coverage`);
  }
  assert.match(css, /color-scheme:\s*dark/);
  assert.match(css, /\.line-card-preview\s*{[^}]*background:\s*#fff/s);
  assert.match(css, /--admin-success:/);
  assert.match(css, /--admin-warning:/);
  assert.match(css, /--admin-danger:/);
});
