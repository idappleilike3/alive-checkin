import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

test("homepage interactive JavaScript parses before buttons are shown", () => {
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)];
  const executableScripts = scripts.filter(
    (match) => !/type=["']application\/ld\+json["']/i.test(match[0]),
  );

  assert.ok(executableScripts.length > 0, "expected homepage JavaScript");
  for (const [index, match] of executableScripts.entries()) {
    assert.doesNotThrow(
      () => new vm.Script(match[1], { filename: `index-inline-${index}.js` }),
      `homepage script ${index} must parse`,
    );
  }
});
