---
name: policy-review
description: "Review workspace policy readiness before approval, including restricted lists, adapter eligibility, notional limits, approval readiness, information barriers, and audit gaps."
---

# Policy Review

Use through the configured role skill map. This file describes the policy review work product; it does not grant permission to bypass role, policy, or MCP boundaries.

Use this skill to evaluate restricted list, approval readiness, policy constraints, universe/instrument support, adapter eligibility, and information barriers.

Universe and policy posture:

- Identify the asset universe, instrument, order path, broker/adapter, and whether that path is installed and enabled.
- Treat unsupported universes or instruments as `revise`, `deny`, or `blocked`; do not infer permission from research-only support.
- Confirm that external data tools, imported skills, or connector availability do not widen execution permissions.
- Live execution remains disabled unless a user-installed adapter and policy explicitly enable it.

Expected output:

- Policy decision: allow, revise, or deny
- Reasons
- Required approvals
- Restricted list result
- Universe/instrument support result
- Adapter eligibility result
- Barrier concerns
- Audit notes

Quality floor:

- Apply the shared TradingCodex quality floor for narrative policy memos.
- Tag material narrative claims as `[factual]`, `[inference]`, or `[assumption]`.
- Name the exact policy, restricted-list, approval, or adapter gate that matters.
- Distinguish a policy deny from an incomplete-evidence revise state.
- State safe next action, blocked actions, and whether the request is research-only, paper/stub eligible, or unsupported.
- Do not fabricate policy state, restricted-list entries, approval receipts, or adapter availability.
- State the safe next action and blocked actions.
- Do not change policy in the same workflow as order execution.

Write outputs under `trading/reports/policy/`.

Do not approve or submit orders from this skill. Approval receipts are a separate approval step.
