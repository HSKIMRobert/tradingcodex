---
name: synthesize-decision
description: "Summarize collected artifacts into a user-facing decision state without creating new specialist analysis or execution artifacts."
---

# Synthesize Decision

Use this skill after required artifacts have been collected or the workflow is
explicitly waiting.

## Boundary

- Covers user-facing synthesis.
- It does not create new research, valuation, technical analysis, portfolio
  sizing, risk approval, order tickets, approvals, or execution.
- If required artifacts are missing, return a waiting state and the next needed
  artifact.

## Inputs

- Relevant artifact paths or DB artifact references
- User objective, time horizon, constraints, and requested action
- Artifact state for each consumed output: `accepted`, `revise`, `blocked`, or
  `waiting`
- Context summaries for accepted artifacts
- Unresolved disagreements
- Source/as-of posture and support gaps
- Active fixed-rule, policy, explicit user constraint, and selected strategy
  context relevant to the decision

## Output

- Workflow lane and scenario archetype
- Artifacts reviewed
- Role-by-role signal summary when role outputs exist
- Artifact states
- Confidence and evidence quality
- Disagreements or missing evidence
- Challenge review: strongest contrary evidence, alternative scenario, rule or
  strategy conflict, stale-source concern, and profile gap that could weaken the
  decision state
- Source/as-of posture, support gaps, source snapshot posture, and readiness label
- Decision state
- Next allowed action

## Rules

- Preserve fact, inference, and assumption distinctions for material claims.
- Lower confidence when data quality, source coverage, sample size, regime
  coverage, parameter sensitivity, or validation setup is weak.
- Do not turn suggestive evidence into a conclusive recommendation.
- Do not fill missing upstream work.
- Preserve conflicts and name the blocking uncertainty.
- Do not self-update strategy, policy, role authority, approval gates, execution
  gates, or rule baselines while synthesizing.
- Before the final decision state, explicitly test the favorable case against
  contrary evidence, base/bear alternatives, stale or missing data, profile
  gaps, and policy or selected-strategy conflicts.
- If the challenge review finds a material unresolved conflict, return `revise`,
  `blocked`, or `waiting` instead of smoothing the conflict into consensus.
- Start from artifact paths and context summaries; inspect full artifacts only
  for load-bearing evidence, disagreement, or stale-source checks.
- Do not convert natural language directly into an order.
