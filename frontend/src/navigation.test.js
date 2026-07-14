import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import { hashForSection, matchesSearch, sectionFromHash } from "./navigation.js";
import {
  collectionViewState,
  investorContextRequest,
  isSkillCatalogVisible,
  normalizedActivityLabel,
  researchPhase,
  sectionData,
  snapshotSections,
  workActionAvailability,
  workbenchPromptRequest,
  workbenchSelectionRequest,
  workPreviewKey,
} from "./workbench-data.js";

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
  assert.equal(isSkillCatalogVisible({ id: "tcx-investor-context", source: "core", scope: "mainagent", user_visible: true }), true);
  assert.equal(isSkillCatalogVisible({ id: "tcx-fundamental", source: "core", scope: "subagent_role", user_visible: false }), true);
});

test("work preview identity binds request, method, strategy, and investor context", () => {
  const base = {
    request: " Analyze NVDA ",
    methodId: "tcx-memory",
    strategyId: "strategy-quality",
    strategyHash: "strategy-hash-a",
    useInvestorContext: true,
    investorContextHash: "context-hash-a",
  };
  assert.equal(workPreviewKey(base), workPreviewKey({ ...base, request: "Analyze NVDA" }));
  for (const changed of [
    { request: "Analyze MSFT" },
    { methodId: "tcx-fundamental" },
    { strategyId: "strategy-catalyst" },
    { strategyHash: "strategy-hash-b" },
    { useInvestorContext: false },
    { investorContextHash: "context-hash-b" },
  ]) {
    assert.notEqual(workPreviewKey(base), workPreviewKey({ ...base, ...changed }));
  }
});

test("work actions wait for context state and preserve the server-owned default", () => {
  assert.deepEqual(investorContextRequest(null), {});
  assert.deepEqual(investorContextRequest(true), { use_investor_context: true });
  assert.deepEqual(investorContextRequest(false), { use_investor_context: false });

  const ready = {
    contextReady: true,
    request: "Analyze NVDA",
    previewLoading: false,
    runBusy: false,
    previewReady: true,
  };
  assert.deepEqual(workActionAvailability(ready), { canPreview: true, canStart: true });
  assert.deepEqual(workActionAvailability({ ...ready, contextReady: false }), { canPreview: false, canStart: false });
  assert.deepEqual(workActionAvailability({ ...ready, runBusy: true }), { canPreview: false, canStart: false });
  assert.deepEqual(workActionAvailability({ ...ready, previewLoading: true }), { canPreview: false, canStart: false });
});

test("workbench mutations use the canonical prompt body and omit empty selections", () => {
  assert.deepEqual(workbenchPromptRequest("  Analyze NVDA  "), { prompt: "Analyze NVDA" });
  assert.deepEqual(workbenchSelectionRequest("", ""), {});
  assert.deepEqual(workbenchSelectionRequest("tcx-fundamental", ""), { skill_id: "tcx-fundamental" });
  assert.deepEqual(workbenchSelectionRequest("", "strategy-quality"), { strategy_id: "strategy-quality" });
});

test("dynamic research phases stay truthful without inventing a DAG", () => {
  assert.equal(researchPhase({ agentCount: 0, artifactCount: 0, hasFinalOutput: false }), "Preparing the research");
  assert.equal(researchPhase({ agentCount: 2, artifactCount: 0, hasFinalOutput: false }), "Specialists are gathering evidence");
  assert.equal(researchPhase({ agentCount: 2, artifactCount: 1, hasFinalOutput: false }), "Reviewing and comparing evidence");
  assert.equal(researchPhase({ agentCount: 0, artifactCount: 0, hasFinalOutput: true }), "Analysis ready");
});

test("technical activity is presented as a restrained reader-facing trail", () => {
  assert.equal(normalizedActivityLabel({ tool_name: "begin_analysis_run" }), "Research scope recorded");
  assert.equal(normalizedActivityLabel({ item_type: "web_search" }), "Public evidence checked");
  assert.equal(normalizedActivityLabel({ tool_name: "research_write_artifact" }), "Verified research note saved");
  assert.equal(normalizedActivityLabel({ type: "subagent-start" }), "Specialist handoff updated");
  assert.equal(normalizedActivityLabel({ type: "unknown" }), "Research activity recorded");
});

test("collection states never present an error as an empty result", () => {
  assert.equal(collectionViewState({ loading: true, error: "", count: 0 }), "loading");
  assert.equal(collectionViewState({ loading: false, error: "unavailable", count: 0 }), "error");
  assert.equal(collectionViewState({ loading: false, error: "", count: 0 }), "empty");
  assert.equal(collectionViewState({ loading: true, error: "", count: 3 }), "ready");
});

test("light theme secondary text keeps normal-text contrast", async () => {
  const css = await readFile(new URL("./styles.css", import.meta.url), "utf8");
  const light = css.match(/:root\[data-theme="light"\][\s\S]*?--ink-3:\s*(#[0-9a-f]{6})/i)?.[1];
  assert.ok(light);
  assert.ok(contrast(light, "#f4f3ee") >= 4.5);
});

test("the rewritten workbench removes implementation-first progress copy", async () => {
  const work = await readFile(new URL("./features/WorkPage.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(work, /Polling|No predefined stages/i);
  assert.match(work, /Verified synthesis/);
  assert.match(work, /Research activity/);
});

function contrast(left, right) {
  const luminance = (color) => {
    const channels = color.match(/[0-9a-f]{2}/gi).map((value) => Number.parseInt(value, 16) / 255);
    const linear = channels.map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
  };
  const [lighter, darker] = [luminance(left), luminance(right)].sort((a, b) => b - a);
  return (lighter + 0.05) / (darker + 0.05);
}
