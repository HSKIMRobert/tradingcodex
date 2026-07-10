import test from "node:test";
import assert from "node:assert/strict";

import { hashForSection, matchesSearch, sectionFromHash } from "./navigation.js";

test("hash navigation stays inside the four workbench sections", () => {
  assert.equal(sectionFromHash("#/skills"), "skills");
  assert.equal(sectionFromHash("#library?artifact=a"), "library");
  assert.equal(sectionFromHash("#/unknown"), "work");
  assert.equal(hashForSection("system"), "#/system");
  assert.equal(hashForSection("admin"), "#/work");
});

test("search matches labels and metadata without case sensitivity", () => {
  assert.equal(matchesSearch(["Evidence Review", "fundamental-analyst"], "FUNDAMENTAL"), true);
  assert.equal(matchesSearch(["Evidence Review"], "forecast"), false);
  assert.equal(matchesSearch([], ""), true);
});
