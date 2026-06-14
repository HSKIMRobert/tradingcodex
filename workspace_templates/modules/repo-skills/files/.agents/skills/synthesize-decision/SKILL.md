---
name: synthesize-decision
description: "Synthesize collected artifacts into a user-facing decision state after research, valuation, portfolio, risk, policy, order, approval, execution, or postmortem artifacts exist."
---

# Synthesize Decision

Use this skill after the required artifacts have been collected and a user-facing decision state or next-step recommendation is needed.

Boundary:

- This skill covers user-facing synthesis after required artifacts or outputs exist.
- It does not create new investment research, valuation, technical analysis, news analysis, portfolio sizing, risk approval, order tickets, approvals, or execution.
- If required artifacts are missing, return a waiting state and the exact next role/artifact needed.

Before writing the synthesis, apply the scenario's synthesis gate and readiness language.

Inputs:

- Relevant research, valuation, portfolio, risk, policy, order, approval, execution, or postmortem artifact paths
- The user's stated objective, time horizon, constraints, and requested action
- Any unresolved disagreements between subagents
- Handoff state for each consumed role artifact: `accepted`, `revise`, `blocked`, or `waiting`

Output:

- Universe and workflow type when relevant
- Workflow lane
- Scenario archetype
- Artifacts reviewed
- Role-by-role signal summary
- Handoff acceptance state by role
- Confidence and evidence quality
- Disagreements or missing evidence
- Source/as-of posture, support gaps, and readiness label
- Decision state: `research-only`, `ready-for-portfolio-risk`, `ready-for-draft`, `ready-for-approval`, `approved`, `executed`, `blocked`, or `revise`
- Next allowed action

Rules:

- Apply the shared TradingCodex quality floor.
- Preserve `[factual]`, `[inference]`, and `[assumption]` distinctions for material claims, especially when they affect confidence or the next action.
- Lower confidence when data quality, source coverage, sample size, regime coverage, parameter sensitivity, or validation setup is weak.
- Do not turn suggestive evidence into a conclusive recommendation.
- Do not create new market research inside this skill.
- Do not fill missing upstream role work inside this skill.
- Do not hide conflicting subagent outputs behind a vague summary.
- Do not present a single conclusion when role outputs conflict; state the conflict and the blocking uncertainty.
- Do not omit source dates, stale-data warnings, or missing-evidence warnings when they materially affect quality.
- Do not convert natural language directly into an order.
- Do not approve or submit orders.
- If order drafting is next, hand off to the configured drafting principal.
- If approval is next, hand off to the configured approval principal.
- If execution is next, require an approved order ticket and approval receipt before assigning the configured execution principal.
