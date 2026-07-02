---
name: plan-workflow
description: "Clarify TradingCodex workflow requests before execution or automation by asking focused questions, preserving user constraints, classifying lane/mode, and producing a compact workflow mandate. Use when a user asks to plan, scope, schedule, automate, or stress-test an investment workflow, or when intent, universe, account/profile, approval model, allowed actions, stop conditions, or execution scope are ambiguous."
---

# Plan Workflow

Use this skill to turn a vague or execution-sensitive request into a compact workflow mandate. The mandate feeds `$tcx-workflow` for immediate runs and `$automate-workflow` for recurring runs.

## Procedure

1. Classify the request as research, thesis review, valuation, portfolio review, draft order, paper execution, live assisted, live execution, automation, server, or build.
2. Extract binding constraints: original request, symbols/universe, horizon, strategy/profile/account, allowed actions, blocked actions, negated scope, approval model, stop conditions, and schedule if recurring.
3. Ask only for missing fields that change routing, risk, or automation arming. State safe defaults instead of asking about details that `$tcx-workflow` can resolve.
4. Preserve explicit negations. `no order`, `no trading`, `no execution`, `no approval`, `no recommendation`, and `no valuation` remove those actions or roles from the mandate.
5. Produce a compact `Workflow Mandate` with the fields below, then hand off:
   - immediate investment workflow: `READY_FOR_TCX_WORKFLOW`
   - recurring workflow: `READY_FOR_AUTOMATION_PREFLIGHT`
   - missing material fields: `NEEDS_CLARIFICATION`
   - server/build request: `SERVER_OR_BUILD_HANDOFF`
   - unsafe or unsupported request: `BLOCKED_BY_SCOPE`

## Question Discipline

- Ask at most three focused questions at a time.
- For broad public-equity review, default to thesis review unless the user narrows scope.
- Do not block research-only or thesis-review mandates on broker/account/profile details.
- Require explicit answers for order drafting, paper execution, live execution, account/broker scope, pre-approved mandates, and recurring schedules.
- If automation is requested, require schedule, blocker policy, and expiry or rearm condition before `READY_FOR_AUTOMATION_PREFLIGHT`.

## Mandate Shape

Return this shape in prose or compact YAML:

```yaml
workflow_mandate:
  status: READY_FOR_TCX_WORKFLOW
  original_request: ""
  objective: ""
  mode: thesis-review
  recurring: false
  schedule: ""
  universe: ""
  horizon: ""
  strategy_profile_account: ""
  broker_scope: ""
  allowed_actions: []
  blocked_actions: []
  approval_model: ""
  required_artifacts: []
  advisory_role_candidates: []
  preflight_checks: []
  stop_conditions: []
  ambiguity_log: []
```

`advisory_role_candidates` are planning hints only. `$tcx-workflow` still owns the validated staged plan and selected team.

## Hard Stops

- Do not dispatch subagents, produce investment analysis, approve orders, execute orders, or register automations.
- Do not turn natural language into approval or execution authority.
- Do not ask for raw secrets or direct broker/API access.
- Do not widen a user's mandate while resolving ambiguity.
