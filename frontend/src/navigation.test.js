import test from "node:test";
import assert from "node:assert/strict";

import { hashForSection, matchesSearch, sectionFromHash } from "./navigation.js";
import { isSharedProfile, sectionData, snapshotSections } from "./workbench-data.js";

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

test("workbench data accepts only the current snapshot contract", () => {
  const sections = snapshotSections({
    generated_at: "2026-07-11T00:00:00Z",
    sections: {
      strategies: { ok: true, data: [{ name: "strategy-quality" }] },
      optional_skills: { ok: true, data: { optional_skills: [{ name: "quality-check" }] } },
      failed: { ok: false, error: { message: "unavailable" } },
    },
  });

  assert.deepEqual(sectionData(sections, "strategies"), [{ name: "strategy-quality" }]);
  assert.deepEqual(sectionData(sections, "optional_skills"), { optional_skills: [{ name: "quality-check" }] });
  assert.equal(sectionData(sections, "failed"), undefined);
  assert.throws(
    () => snapshotSections({ state: { strategies: [] } }),
    /canonical sections object/,
  );
  assert.equal(isSharedProfile({ shared: true }), true);
  assert.equal(isSharedProfile({ shared: false }), false);
});
