import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const ignoredSchemes = /^(?:https?:|mailto:|tel:|javascript:|data:|#)/i;

function htmlFiles(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    if (entry.name.startsWith(".") || entry.name === "node_modules") return [];
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return htmlFiles(path);
    return entry.name.endsWith(".html") ? [path] : [];
  });
}

function resolvesLocally(sourceFile, rawTarget) {
  if (!rawTarget || ignoredSchemes.test(rawTarget) || rawTarget.includes("${")) return true;
  const target = rawTarget.split("#", 1)[0].split("?", 1)[0];
  if (!target) return true;
  const local = target.startsWith("/")
    ? join(root, target.slice(1))
    : resolve(dirname(sourceFile), target);
  if (existsSync(local)) return true;
  if (!extname(local) && existsSync(`${local}.html`)) return true;
  if (target === "/" && existsSync(join(root, "index.html"))) return true;
  return false;
}

test("every local public-page href and src resolves to a real page or asset", () => {
  const broken = [];
  for (const file of htmlFiles(root)) {
    const html = readFileSync(file, "utf8");
    for (const match of html.matchAll(/\b(?:href|src)=["']([^"']+)["']/gi)) {
      if (!resolvesLocally(file, match[1])) {
        broken.push(`${file.slice(root.length + 1)} -> ${match[1]}`);
      }
    }
  }
  assert.deepEqual(broken, [], `broken local URLs:\n${broken.join("\n")}`);
});
