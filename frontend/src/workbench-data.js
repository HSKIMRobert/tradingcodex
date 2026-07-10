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
export function isSharedAccountScope(value) {
  return record(value).shared === true;
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
