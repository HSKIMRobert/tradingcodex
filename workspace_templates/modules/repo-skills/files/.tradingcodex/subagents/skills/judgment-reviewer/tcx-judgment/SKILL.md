---
name: tcx-judgment
description: "Challenge accepted investment artifacts before synthesis, portfolio, risk, order, approval, or execution gates. It makes conclusions reviewable, source-aware, and revisitable without granting research, portfolio, approval, execution, or model-training authority."
---

# Agent Judgment Review

Use this procedure after upstream artifacts are accepted or when a
decision-oriented artifact needs independent challenge.

Inputs:

- exact conflict or review question and the downstream decision it can change
- accepted, authenticated Artifact IDs with their service receipts/content
  hashes and handoff states; retrieve artifacts by exact ID
- original user request and explicit constraints
- source/as-of metadata, source trust notes, and forecast fields
- stated missing evidence, blocked actions, and downstream recipient

Treat paths and compact summaries as navigation aids, never substitutes for
authenticated IDs, receipts/hashes, or the exact conflict question. Return
`waiting` when a required accepted input or the conflict question is missing.

Required output fields:

- strongest supporting evidence
- strongest contrary evidence
- weak, stale, missing, or discounted source posture
- overconfidence risk
- assumptions that would change the conclusion
- source trust notes
- update triggers
- invalidation conditions
- owning role for any required revision
- review outcome: `accepted`, `revise`, `blocked`, or `waiting`

Evidence weighting:

- Require official source-of-record evidence when exact issuer, regulator,
  exchange, filing, contractual, or policy status is material.
- Treat management claims as source claims until independently supported.
- Treat market-derived evidence as useful but timestamp-sensitive.
- Treat attributable OpenBB/provider data, credible institutional data, and
  reputable secondary reporting as usable evidence for the claims and periods
  they competently cover. They may support a final conclusion without a primary
  duplicate when attribution, freshness, and coverage are adequate and no
  material conflict remains.
- Discount stale evidence, unsupported assumptions, and sources with missing
  as-of or retrieved-at posture.

Outcome rules:

- Use `accepted` when conclusion-driving claims have fit-for-purpose support
  and contrary evidence, source trust, update triggers, and invalidation
  conditions are explicit enough for downstream use. Do not request revision
  solely because support is non-primary.
- Use `revise` when an owning role can fix weak evidence, missing source
  posture, unsupported assumptions, or unclear forecast/update fields.
- Use `blocked` when the conclusion depends on unavailable evidence, policy
  conflicts, missing profile context, or unsupported downstream authority.
- Use `waiting` when required upstream artifacts or accepted handoff state are
  missing.

Review-specific quality:

- Challenge the artifact; do not produce replacement analyst work.
- Name the best objection instead of averaging conflict into false consensus.
- Lower confidence when source trust, freshness, coverage, or contradiction is
  weak.
- Do not create order tickets, approvals, broker actions, execution requests,
  strategy changes, policy changes, or forecast ledger records from this review
  alone.
