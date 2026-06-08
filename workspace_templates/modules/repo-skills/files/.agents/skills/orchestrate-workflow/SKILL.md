---
name: orchestrate-workflow
description: "Coordinate workspace investment workflows from intake through research, valuation, portfolio, risk, order draft, approval, execution, and postmortem. Use by head-manager for multi-step requests and subagent routing."
---

# Orchestrate Workflow

Use this skill when `head-manager` receives a multi-step investment request, needs to coordinate subagents, or must move work across research, thesis, portfolio, risk, order intent, approval, execution, and postmortem stages.

Purpose:

- Classify the user request into a workflow lane before assigning work.
- Use `investment-workflow-map` for investment workflows before finalizing the scenario lane, role team, source posture, hero artifact, support files, universe boundary, and readiness labels.
- Use `scenario-quality-gates` to identify the request archetype, minimum useful team, artifact plan, and quality gates.
- Treat the risk, uncertainty, and anti-hallucination floor in `scenario-quality-gates` as the shared quality contract for every investment artifact and synthesis.
- Use `external-data-source-gate` before any external MCP, plugin, connector, web source, or imported skill is used for evidence.
- Prevent `head-manager` from doing analyst work directly; it dispatches, waits for role outputs, then synthesizes.
- At the start of a main-agent session, `.tradingcodex/mainagent/session-start.json` prepares the roster plan. Use it only after the user explicitly requests subagents or parallel/delegated agent work.
- Treat explicit `$orchestrate-workflow` invocation as workspace workflow consent. The workflow skill is the primary orchestrator; hooks only nudge the main agent into this skill and prevent direct analysis.
- Choose only the role perspectives needed for the lane.
- Plan subagent capacity with `./tradingcodex subagents plan <agents...>` when more than one subagent may be requested.
- Check existing runtime state with `./tradingcodex subagents state` before creating subagents, and reuse active or completed role work when it matches the same workflow run.
- Spawn each subagent by its exact role name from `.codex/agents/*.toml`; if the runtime UI exposes a label field, keep that label equal to the role name.
- When using a full-history fork, omit `agent_type`, `model`, and `model_reasoning_effort` overrides; otherwise spawn without full-history if explicit role override fields are required.
- For role-specific Codex subagent creation, prefer `spawn_agent(agent_type="<role>", task_name="...", fork_turns="none", message="ROLE CARD: ... TASK: ... DELIVERABLE: ... SCOPE: ... VERIFY: ...")`. `agent_type` selects the role; setting only model or reasoning effort creates a default agent, not the fixed workspace role.
- Give subagents explicit, non-prescriptive briefs and expected artifact paths.
- Preserve the original user request and explicit user constraints in every non-startup subagent brief.
- Keep main-agent assumptions, suggested metrics, or optional frameworks separate from user-explicit requirements.
- Require material narrative claims to be tagged as `[factual]`, `[inference]`, or `[assumption]`; do not paste the full anti-hallucination checklist into every brief because role skills and `scenario-quality-gates` own the detailed quality floor.
- Collect, review, reconcile, and synthesize artifacts before moving to the next stage.
- Use `synthesize-decision` before giving a user-facing decision state.
- Keep execution-sensitive steps behind structured artifacts, validation, approval, and the workspace MCP execution boundary.

Fail-closed dispatch gate:

- Any prompt asking for company/security analysis, 종목 분석, investment judgment, valuation, technical/news analysis, portfolio/risk review, order drafting, approval, or execution requires subagent dispatch before any substantive answer.
- `head-manager` must not use its own market knowledge, shell/web output, or ad hoc reasoning to replace fixed role subagent work.
- Codex only spawns subagents when the user explicitly asks for subagents, parallel agents, delegated agent work, or explicitly invokes `$orchestrate-workflow`. If the user's prompt did not explicitly request one of those, ask for confirmation or provide a starter prompt; do not analyze directly.
- If the user explicitly requested subagents and the runtime can create them, actually create the selected subagents; do not merely describe that they should be used.
- If subagent creation is unavailable or fails, stop with `waiting_for_subagent_dispatch` and provide only the lane, selected team, artifact paths, and task briefs. Do not produce the analysis yourself.
- For "삼성전자 종목 분석해줘" or equivalent broad company analysis without an explicit subagent request, use `research_only`, identify `fundamental-analyst`, `technical-analyst`, and `news-analyst` as the selected team, then stop and ask for subagent workflow confirmation. If the prompt explicitly says to use subagents, dispatch those roles and stop before valuation/order work unless the user asks for it.

Workflow lanes:

1. `research_only`: collect evidence and produce research reports; no order intent.
2. `thesis_review`: research plus valuation or thesis writing; no execution.
3. `portfolio_risk_review`: portfolio fit and downside review before any order draft.
4. `order_intent_draft`: create a draft order intent after required analysis artifacts exist.
5. `approval_execution`: validate, run risk-manager policy/approval review, approve, and route approved execution through the workspace MCP execution boundary.
6. `postmortem`: review audit trail, rejected orders, executions, thesis drift, or process failures.
7. `blocked_request`: refuse or stop unsafe/unavailable actions such as restricted-symbol orders, secret reads, direct broker access, unsupported live execution, or policy changes combined with execution; no order intent artifact.

Operating loop:

1. Startup readiness: read `.tradingcodex/mainagent/session-start.json` when needed. It is a readiness plan, not an automatic spawn request.
2. Intake: identify asset, objective, time horizon, requested action, constraints, and whether execution is in scope.
3. Investment workflow map: use `investment-workflow-map` to identify the investment universe, workflow type, source/as-of posture, hero artifact, support files, support gaps, and conservative readiness label.
4. Scenario quality gate: use `scenario-quality-gates` to classify the scenario, choose the minimum useful role team, artifact plan, and quality gates.
5. User instruction contract: preserve the original request verbatim, explicit constraints, out-of-scope actions, and any main-agent inferences as non-binding context.
6. External data source gate: if the workflow may use OpenBB MCP, Binance public data, official regulator or exchange disclosure sources, web sources, or imported skills, constrain sources before dispatch.
7. Lane: choose one workflow lane and state what is intentionally out of scope.
8. Dispatch gate: if the request needs investment research, analysis, valuation, portfolio, risk, strategy, policy, or execution judgment, assign subagents before making a substantive claim.
9. Explicit subagent request check: if the user did not ask for subagents or parallel/delegated agent work, ask for confirmation or provide a starter prompt; do not analyze directly.
10. Runtime state: run or consult `./tradingcodex subagents state`. If the same run/role is active, wait or send a follow-up instead of creating a duplicate. If a matching artifact already exists and passes quality checks, reuse it.
11. Skill view: run or consult `./tradingcodex subagents skills <role>` before briefing each selected role. The default skill roster is a baseline; applied proposals and user-maintained role skills may change the best skill for the task.
12. Plan: when explicit subagent use is present, select subagents and run `./tradingcodex subagents plan <agents...>` for workflow-specific parallel requests.
13. Spawn: use the exact role name from `.codex/agents/*.toml`; do not add unsupported alias fields to Codex TOML. Prefer `spawn_agent(agent_type="<role>", task_name="...", fork_turns="none", message="ROLE CARD: ... TASK: ... DELIVERABLE: ... SCOPE: ... VERIFY: ...")` for role-specific workers.
14. Brief: use `manage-subagents` to give each subagent the user instruction contract, objective, inputs, output path, user-explicit/policy-required checks only, forbidden actions, method autonomy, external data source constraints when relevant, and handoff recipient. Do not put internal workflow run ids in the subagent-visible message.
15. Collect: verify expected artifacts exist and pass role-specific quality checks.
16. Reconcile: compare outputs, separate facts from judgments, and preserve disagreements.
17. Gate: before order or execution work, require the right artifacts, validation, policy review, approval, and audit trail.
18. Synthesize: use `synthesize-decision` to produce the decision state, open questions, and next allowed action.
19. Respond: summarize decision state, evidence used, open questions, and next allowed action.

Briefing rules:

- Required checks are only checks stated by the user or required by policy/gates.
- Do not turn broad requests into mandatory metric checklists.
- Do not require EV/EBITDA, DCF, RSI, peer comps, moving averages, or other frameworks unless the user requested them, policy requires them, or the subagent role skill itself requires them.
- Let each subagent choose methods from its developer instructions and assigned role skills.
- Do not treat the built-in analysis skill names as exhaustive. For analysis and review roles, user-added or user-updated skills may be more relevant than the default skill for the specific request.
- Keep mandatory skill references only for workflow-critical or safety-critical actions such as external data gating, order-intent creation, approval receipt creation, and execution through the workspace MCP boundary.
- If adding optional examples, label them as non-binding and say the subagent may ignore them.
- If external data is allowed, specify source class, allowed purpose, allowed tools/categories, forbidden actions, and required evidence fields.

Spawn contract:

```text
spawn_agent(
  agent_type="<fixed-role-name>",
  task_name="<role> <asset-or-topic> <lane>",
  fork_turns="none",
  message="ROLE CARD: <affiliation, coordinator, assigned role, own artifacts, handoff>\nTASK: <imperative role assignment>\nDELIVERABLE: <artifact path and summary expectation>\nSCOPE: <original request, explicit constraints, allowed sources, forbidden actions>\nVERIFY: <quality checks, claim tags, and handoff criteria>"
)
```

Rules:

- Every subagent message must be self-contained because `fork_turns="none"` does not carry the full parent context.
- Start every message with `ROLE CARD:` and include `TASK:`, `DELIVERABLE:`, `SCOPE:`, and `VERIFY:`.
- Keep internal workflow run ids in hook/session-state metadata. Do not put run-id tokens in the subagent-visible `message`.
- Keep `task_name` human-readable, for example `news-analyst SK hynix research_only`; hooks can still connect starts/stops through `.tradingcodex/mainagent/latest-user-prompt-gate.json`.
- Keep role briefs compact: include the claim-tag requirement, but reference role skills and `scenario-quality-gates` for the detailed risk/uncertainty checklist.
- Do not create duplicate subagents for the same run/role when `./tradingcodex subagents state` shows an active role.
- If the role is completed and the expected artifact passes quality checks, reuse the artifact; if it failed or closed without usable output, recreate only when the user explicitly invoked the workflow or subagent work.

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
  -> trading/orders/draft/*.order_intent.json
  -> trading/orders/approved/*.order_intent.json
  -> trading/approvals/*.approval_receipt.json
  -> trading/orders/executed/*.execution_result.json
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
- Draft order intents: `trading/orders/draft/<id>.order_intent.json`
- Approved order intents: `trading/orders/approved/<id>.order_intent.json`
- Approval receipts: `trading/approvals/<id>.approval_receipt.json`
- Executed order results: `trading/orders/executed/<id>.execution_result.json`
- Postmortems: `trading/reports/postmortem/<id>.postmortem_report.json`
- Skill change proposals: `.tradingcodex/mainagent/skill-change-proposals/<proposal-id>.yaml`

Minimum gates:

- No head-manager investment conclusion before relevant subagent outputs exist.
- No head-manager company/security analysis before subagent dispatch is complete.
- If dispatch is impossible, respond with waiting/briefing status only.
- No head-manager ad hoc market research when a fixed role subagent owns that perspective.
- No order intent from natural language alone.
- No order intent before research, portfolio, and risk context exist.
- No approval by the order creator.
- No execution without approved order intent and approval receipt.
- No direct broker API calls.
- No raw broker secrets in workspace context.
- No subagent may spawn another subagent.

Example: startup readiness

```text
SessionStart hook writes `.tradingcodex/mainagent/session-start.json` with `spawn_requested: false` and `explicit_user_request_required: true`.
Command: ./tradingcodex subagents plan --all
Subagents:
- fundamental-analyst
- technical-analyst
- news-analyst
- macro-analyst
- instrument-analyst
- valuation-analyst
- portfolio-manager
- risk-manager
- execution-operator
Startup brief:
- initialize role boundary
- use the role name as the runtime label
- wait for head-manager task brief
- do not create order intents, approve, execute, read secrets, or spawn subagents
Do not spawn these roles until the user explicitly asks for a subagent workflow.
```

Example: research-only request

User asks: "Analyze NVDA for me, no trade yet."

```text
Lane: research_only
Head-manager direct answer: forbidden until subagent outputs are collected.
Subagents: fundamental-analyst, technical-analyst, news-analyst
Plan: ./tradingcodex subagents plan fundamental-analyst technical-analyst news-analyst
Original user request (verbatim): "Analyze NVDA for me, no trade yet."
Explicit user constraints: no trade yet.
Required checks: no order intent, no approval, no execution.
Method autonomy: no user-specified metrics; each subagent chooses appropriate methods using its own instructions and assigned role skills.
Artifacts:
- trading/reports/fundamental/NVDA.fundamental.md
- trading/reports/technical/NVDA.technical.md
- trading/reports/news/NVDA.news.md
Synthesis:
- business quality
- technical setup
- recent narrative/events
- missing evidence
Stop before valuation, portfolio, risk, or order intent unless the user asks.
```

Example: "should I buy?"

User asks: "Should I buy 005930?"

```text
Lane: thesis_review, then portfolio_risk_review if the user wants decision support.
Head-manager direct answer: forbidden until analyst, valuation, portfolio, and risk outputs are collected.
Subagents: fundamental-analyst, technical-analyst, news-analyst, valuation-analyst, portfolio-manager, risk-manager
Plan: ./tradingcodex subagents plan fundamental-analyst technical-analyst news-analyst valuation-analyst portfolio-manager risk-manager
Handoff:
- analysts create research artifacts
- valuation-analyst chooses appropriate valuation methods from its role instructions and evidence
- portfolio-manager checks fit and opportunity cost
- risk-manager reviews downside, sizing, and policy constraints
Response:
- no order intent unless the user explicitly asks for an order draft
- state evidence, risks, and open questions
```

Example: draft order intent

User asks: "Create a paper buy order intent for 10 shares of XYZ if the analysis passes."

```text
Lane: order_intent_draft
Required prior artifacts:
- research or thesis artifact
- portfolio review
- risk review
Subagent: portfolio-manager
Output: trading/orders/draft/XYZ.order_intent.json
Validation: ./tradingcodex validate order trading/orders/draft/XYZ.order_intent.json
Stop:
- do not approve
- do not submit
- ask for explicit risk-manager approval workflow if the draft is valid
```

Example: approved paper execution

User asks: "Submit the approved paper order."

```text
Lane: approval_execution
Required artifacts:
- trading/orders/approved/<id>.order_intent.json
- trading/approvals/<id>.approval_receipt.json
Subagent: execution-operator
Path:
- validate order intent
- validate approval receipt
- call the workspace MCP execution tool `submit_approved_order`
- write execution result and audit event
Forbidden:
- direct broker API
- reading raw API keys
- policy changes in the same workflow
```

Example: conflicting subagent outputs

```text
technical-analyst says trend is constructive.
fundamental-analyst says earnings quality is deteriorating.
risk-manager says downside is too wide for the proposed size.

Do not summarize as "mixed but okay." State the conflict:
"The setup is technically constructive, but the fundamental and risk artifacts do not support the proposed size yet."
Next allowed action:
- request a smaller size from risk-manager
- request additional evidence from fundamental-analyst
- stop before order intent
```

Final response template:

```text
Workflow: <lane>
Artifacts reviewed: <paths>
Subagent outputs: <short role-by-role summary>
Decision state: research-only | ready for risk review | ready for draft | blocked | approved | executed
Open questions: <missing evidence or approvals>
Next allowed action: <one or two safe next steps>
```
