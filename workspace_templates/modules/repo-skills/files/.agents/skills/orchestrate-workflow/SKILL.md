---
name: orchestrate-workflow
description: "Coordinate workspace investment workflows from intake through research, valuation, portfolio, risk, order draft, approval, execution, and postmortem."
---

# Orchestrate Workflow

Use this skill for multi-step investment requests that move across research, thesis, portfolio, risk, order ticket drafting, approval, execution, or postmortem stages.

Boundary:

- This skill is the workflow entrypoint. It sequences stages, keeps the lane explicit, and stops unsafe escalation.
- Role eligibility, tool access, and installed skill assignment come from the configured role skill map, subagent files, MCP allowlists, and policy services.
- Keep this file dependency-light: use the workflow fields below instead of importing procedural detail from other repo skills.
- Readiness labels are quality states, not approvals, permissions, or execution authorization.

Purpose:

- Classify the user request into a workflow lane before assigning work.
- Identify the investment universe, workflow type, source/as-of posture, hero artifact, support files, support gaps, and conservative readiness label.
- Identify the request archetype, minimum useful team, artifact plan, and quality gates.
- Apply the shared TradingCodex quality floor to every investment artifact and synthesis.
- Constrain external MCP, plugin, connector, web, or imported-skill evidence before it is used.
- Prevent the coordinator from doing analyst work directly; it dispatches, waits for role outputs, then synthesizes.
- At the start of a main-agent session, `.tradingcodex/mainagent/session-start.json` prepares the roster plan. Use it only after a natural-language investment request, an explicit subagent request, or explicit `$orchestrate-workflow` invocation activates a workflow.
- Treat explicit `$orchestrate-workflow` invocation as optional manual control. Natural-language investment requests can activate this same workflow path through hook-provided auto-dispatch context.
- Choose only the role perspectives needed for the lane.
- Treat the selected team from hook context or the starter prompt as binding for that lane; do not add roles outside that list without explicit lane escalation.
- Use compact assignment envelopes for capacity planning, runtime state checks, reuse, exact fixed-role dispatch mechanics, non-prescriptive briefs, and artifact review.
- Collect, review, reconcile, and synthesize artifacts before moving to the next stage.
- Accept, revise, block, or wait on each role handoff before allowing downstream roles to consume it.
- Produce a user-facing decision state only after the required artifacts or explicit waiting state exists.
- Keep execution-sensitive steps behind structured artifacts, validation, approval, and the workspace MCP execution boundary.

Fail-closed dispatch gate:

- Any prompt asking for company/security analysis, 종목 분석, investment judgment, valuation, technical/news analysis, portfolio/risk review, order drafting, approval, or execution requires subagent dispatch before any substantive answer.
- The coordinator must not use its own market knowledge, shell/web output, or ad hoc reasoning to replace fixed role subagent work.
- Natural-language investment requests are sufficient workflow activation; explicit subagent requests and `$orchestrate-workflow` are optional manual-control entrypoints.
- If an active workflow request exists and the runtime can create selected subagents, actually create the selected subagents; do not merely describe that they should be used.
- When using `spawn_agent` with a fixed `agent_type`, pass the compact assignment envelope as `message` and do not set `fork_context` to true. Use no full-history fork on the first attempt.
- If subagent creation is unavailable, role routing is unverified, or dispatch fails, stop with `waiting_for_subagent_dispatch` and provide only the lane, selected team, artifact paths, and task briefs. Do not produce the analysis yourself.
- For broad company analysis, state the lane and selected team from the configured role map, dispatch or reuse the selected team when available, and stop before valuation/order work unless the user asks for it.
- For `research_only`, dispatch only the selected research roles. Do not add valuation, portfolio, risk, approval, or execution roles as a precaution.

Workflow lanes:

1. `research_only`: collect evidence and produce research reports; no order ticket.
2. `thesis_review`: research plus valuation or thesis writing; no execution.
3. `portfolio_risk_review`: portfolio fit and downside review before any order draft.
4. `order_ticket_draft`: create a draft OrderTicket after required analysis artifacts exist.
5. `approval_execution`: validate, run policy/approval review, approve when allowed, and route approved execution through the workspace MCP execution boundary.
6. postmortem lane: review audit trail, rejected orders, executions, thesis drift, or process failures.
7. `blocked_request`: refuse or stop unsafe/unavailable actions such as restricted-symbol orders, secret reads, direct broker access, unsupported live execution, or policy changes combined with execution; no order ticket artifact.

Operating loop:

1. Startup readiness: read `.tradingcodex/mainagent/session-start.json` when needed. It is a readiness plan, not an automatic spawn request.
2. Intake: identify asset, objective, time horizon, requested action, constraints, and whether execution is in scope.
3. Workflow map: identify the investment universe, workflow type, source/as-of posture, hero artifact, support files, support gaps, and conservative readiness label.
4. Scenario quality gate: classify the scenario, choose the minimum useful role team, artifact plan, and quality gates.
5. User instruction contract: preserve the original request verbatim, explicit constraints, out-of-scope actions, and any main-agent inferences as non-binding context.
6. External data source gate: if the workflow may use Binance public data, official regulator or exchange disclosure sources, web sources, other external market-data tools, or imported skills, constrain sources before dispatch.
7. Lane: choose one workflow lane and state what is intentionally out of scope.
8. Dispatch gate: if the request needs investment research, analysis, valuation, portfolio, risk, strategy, policy, or execution judgment, assign subagents before making a substantive claim.
9. Activation source check: proceed for natural-language investment requests, explicit subagent requests, or explicit `$orchestrate-workflow` requests; ignore non-investment prompts. Treat the selected team for the lane as closed unless the user expands scope.
10. Subagent communication: use runtime state, skill view, capacity plan, exact fixed-role dispatch, compact briefs, artifact review, reuse, and routing-unverified handling.
11. Collect: verify expected artifacts exist, pass role-specific quality checks, and carry `accepted`, `revise`, `blocked`, or `waiting` handoff state.
12. Reconcile: compare outputs, separate facts from judgments, preserve disagreements, and send weak upstream work back to the owning role instead of assigning another role to redo it.
13. Gate: before order or execution work, require the right artifacts, validation, policy review, approval, and audit trail.
14. Synthesize: produce the decision state, open questions, and next allowed action.
15. Respond: summarize decision state, evidence used, open questions, and next allowed action.

Briefing and spawn details:

This orchestration skill states the lane, selected team, required artifacts, and stage gates. Keep exact subagent messages as compact assignment envelopes rather than standing role manuals.

Default artifact flow:

```text
trading/research/*.evidence.md
  -> trading/reports/fundamental/
  -> trading/reports/technical/
  -> trading/reports/news/
  -> trading/reports/macro/
  -> trading/reports/instrument/
  -> trading/reports/valuation/
  -> trading/reports/portfolio/
  -> trading/reports/risk/
  -> central DB OrderTicket
  -> central DB ApprovalReceipt
  -> central DB ExecutionResult, OrderEvent, BrokerOrder, Fill
  -> trading/reports/postmortem/
```

Canonical artifact paths:

- Evidence packs: `trading/research/<symbol>.evidence.md`
- Fundamental reports: `trading/reports/fundamental/<symbol>.fundamental.md`
- Technical reports: `trading/reports/technical/<symbol>.technical.md`
- News reports: `trading/reports/news/<symbol>.news.md`
- Macro reports: `trading/reports/macro/<symbol-or-topic>.macro.md`
- Instrument reports: `trading/reports/instrument/<symbol-or-topic>.instrument.md`
- Valuation reports: `trading/reports/valuation/<symbol>.valuation.md`
- Portfolio reports: `trading/reports/portfolio/<symbol>.portfolio.md`
- Risk reports: `trading/reports/risk/<symbol>.risk.md`
- Policy reports: `trading/reports/policy/<symbol>.policy.md`
- Order tickets: central DB `OrderTicket` records.
- Approval receipts: central DB `ApprovalReceipt` records, with legacy `trading/approvals/<id>.approval_receipt.json` only for compatibility exports.
- Execution results: central DB `ExecutionResult`, `OrderEvent`, `BrokerOrder`, and `Fill` records, with legacy `trading/orders/executed/<id>.execution_result.json` only for compatibility exports.
- Postmortems: `trading/reports/postmortem/<id>.postmortem_report.json`
- Skill change proposals: `.tradingcodex/mainagent/skill-change-proposals/<proposal-id>.yaml`

Minimum gates:

- No coordinator investment conclusion before relevant subagent outputs exist.
- No coordinator company/security analysis before subagent dispatch is complete.
- If dispatch is impossible, respond with waiting/briefing status only.
- No coordinator ad hoc market research when a fixed role subagent owns that perspective.
- No downstream role may fill missing upstream analysis outside its owned question.
- No order ticket from natural language alone.
- No order ticket before research, portfolio, and risk context exist.
- No approval by the order creator.
- No execution without approved order ticket and matching approval receipt.
- No direct broker API calls.
- No raw broker secrets in workspace context.
- No subagent may spawn another subagent.

Output contract:

```text
Workflow: <lane>
Artifacts reviewed: <paths>
Subagent outputs: <short role-by-role summary>
Decision state: research-only | ready for risk review | ready for draft | blocked | approved | executed
Open questions: <missing evidence or approvals>
Next allowed action: <one or two safe next steps>
```
