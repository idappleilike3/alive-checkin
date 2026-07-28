import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import vm from "node:vm";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function htmlFiles(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    if (entry.name.startsWith(".") || entry.name === "node_modules") return [];
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return htmlFiles(path);
    return entry.name.endsWith(".html") ? [path] : [];
  });
}

test("every inline public-page script parses before its buttons are shown", () => {
  const failures = [];
  for (const file of htmlFiles(root)) {
    const html = readFileSync(file, "utf8");
    const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)]
      .filter((match) => !/type=["'](?:application\/ld\+json|module)["']/i.test(match[0]));
    for (const [index, match] of scripts.entries()) {
      try {
        new vm.Script(match[1], { filename: `${file.slice(root.length + 1)}:${index}` });
      } catch (error) {
        failures.push(`${file.slice(root.length + 1)} script ${index}: ${error.message}`);
      }
    }
  }
  assert.deepEqual(failures, [], `page JavaScript parse failures:\n${failures.join("\n")}`);
});
