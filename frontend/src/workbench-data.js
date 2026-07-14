/** @param {unknown} value @returns {Record<string, unknown>} */
function record(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? /** @type {Record<string, unknown>} */ (value)
    : {};
}

/** @param {unknown} value @returns {Record<string, unknown>} */
export function snapshotSections(value) {
  const snapshot = record(value);
  if (snapshot.sections === null || typeof snapshot.sections !== "object" || Array.isArray(snapshot.sections)) {
    throw new TypeError("Workbench snapshot is missing the canonical sections object.");
  }
  return { ...snapshot.sections, generated_at: snapshot.generated_at };
}

/** @param {Record<string, unknown>} sections @param {string} key */
export function sectionData(sections, key) {
  const section = record(sections[key]);
  return section.ok === true ? section.data : undefined;
}

/** @param {unknown} value */
export function isSkillCatalogVisible(value) {
  const skill = record(value);
  return skill.user_visible === true || skill.scope !== "mainagent" || skill.source !== "core";
}

/** @param {{request: string, methodId: string, strategyId: string, strategyHash: string, useInvestorContext: boolean, investorContextHash: string}} value */
export function workPreviewKey(value) {
  return JSON.stringify([
    value.request.trim(),
    value.methodId,
    value.strategyId,
    value.strategyHash,
    value.useInvestorContext,
    value.investorContextHash,
  ]);
}

/** @param {boolean | null} value */
export function investorContextRequest(value) {
  return typeof value === "boolean" ? { use_investor_context: value } : {};
}

/** @param {string} value */
export function workbenchPromptRequest(value) {
  return { prompt: value.trim() };
}

/** @param {string} skillId @param {string} strategyId */
export function workbenchSelectionRequest(skillId, strategyId) {
  return {
    ...(skillId ? { skill_id: skillId } : {}),
    ...(strategyId ? { strategy_id: strategyId } : {}),
  };
}

/** @param {{contextReady: boolean, request: string, previewLoading: boolean, runBusy: boolean, previewReady: boolean}} value */
export function workActionAvailability(value) {
  const canPreview = value.contextReady && Boolean(value.request.trim()) && !value.previewLoading && !value.runBusy;
  return { canPreview, canStart: canPreview && value.previewReady };
}

/** @param {{agentCount: number, artifactCount: number, hasFinalOutput: boolean}} value */
export function researchPhase(value) {
  if (value.hasFinalOutput) return "Analysis ready";
  if (value.artifactCount > 0) return "Reviewing and comparing evidence";
  if (value.agentCount > 0) return "Specialists are gathering evidence";
  return "Preparing the research";
}

/** @param {{type?: unknown, tool_name?: unknown, item_type?: unknown}} value */
export function normalizedActivityLabel(value) {
  const combined = [value.type, value.tool_name, value.item_type]
    .map((item) => String(item ?? "").toLowerCase())
    .join(" ");
  if (combined.includes("begin_analysis_run")) return "Research scope recorded";
  if (combined.includes("artifact") || combined.includes("research_write")) return "Verified research note saved";
  if (combined.includes("search") || combined.includes("web")) return "Public evidence checked";
  if (combined.includes("subagent") || combined.includes("agent")) return "Specialist handoff updated";
  if (combined.includes("final") || combined.includes("synthesis")) return "Synthesis reviewed";
  return "Research activity recorded";
}

/** @param {{loading: boolean, error: string, count: number}} value */
export function collectionViewState(value) {
  if (value.loading && value.count === 0) return "loading";
  if (value.error && value.count === 0) return "error";
  if (value.count === 0) return "empty";
  return "ready";
}
