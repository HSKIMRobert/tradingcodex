# Roles, Skills, And Workflows

This document owns the fixed role roster, no-overlap role contract,
head-manager dispatch gate, agent handoff contract, skills, workflow routing,
subagent isolation, role-owned artifacts, and module graph.
Roles and workflows participate in both Harness child systems: Guardrails
through role boundaries and information barriers, and Improvement through
workflow quality, skill proposals, and postmortems.

## Fixed Role Roster

TradingCodex always uses `head-manager` as the main agent with nine fixed
subagents.

| Role | Responsibility | Never allowed |
| --- | --- | --- |
| `head-manager` | Workflow dispatch, subagent coordination, synthesis, validation/audit status tracking | Finalize investment conclusions without subagent output, call broker APIs directly |
| `fundamental-analyst` | Business, financial statement, official disclosure, and competitive analysis | order intent, approval, execution, secret read |
| `technical-analyst` | Price action, trend, momentum, volume, volatility | order intent, execution, standalone investment conclusion |
| `news-analyst` | News, disclosure events, macro events, narrative change | assert unverified rumors, execution |
| `macro-analyst` | Macro, rates, FX, commodities, liquidity, policy, cross-asset transmission | order intent, execution, unsupported implementation claims |
| `instrument-analyst` | ETF/index, options/derivatives, crypto public market structure, credit-signal boundary, instrument mechanics | order intent, execution, unsupported instrument execution claims |
| `valuation-analyst` | DCF, reverse DCF, multiples, scenario, expected return | approval, execution, broker API call |
| `portfolio-manager` | Portfolio fit, sizing, draft order intent | self-approval, execution, arbitrary policy changes |
| `risk-manager` | Risk review, policy review, approval readiness, approval receipt | order drafting, execution, arbitrary policy changes |
| `execution-operator` | Submit approved order intents through TradingCodex MCP | raw broker API, secret read, policy change |

## No-Overlap Role Contract

Roles own questions, not broad topics. A role may reference another role's
artifact, but it must not silently redo that role's work, fill missing evidence
for that role, or treat coordinator context as a substitute for an accepted
artifact.

| Role | Owns | Consumes | Must hand off |
| --- | --- | --- | --- |
| `head-manager` | intake, lane selection, role dispatch, artifact acceptance, conflict reconciliation, user synthesis | user request, accepted role artifacts, service status | selected lane/team, compact briefs, accepted artifacts, conflicts, next allowed action |
| `fundamental-analyst` | business model, financial statements, filings, economics, fundamental risks | assigned evidence and source references | evidence-backed fundamental report with source/as-of posture and missing evidence |
| `technical-analyst` | price action, trend, momentum, volume, volatility, liquidity setup | assigned market-data references | technical report with setup observations, data posture, confidence, and invalidation gaps |
| `news-analyst` | verified news, disclosures, event chronology, narrative change, source quality | assigned filings/news/source references | dated event report with factual timeline, source caveats, and unresolved claims |
| `macro-analyst` | macro, rates, FX, commodities, liquidity, policy, cross-asset transmission | assigned macro/source references and relevant role artifacts | macro transmission report with source/as-of posture and regime uncertainty |
| `instrument-analyst` | ETF/index methodology, options/derivatives, crypto public market structure, credit-signal boundary, instrument mechanics | assigned instrument/source references | instrument support report with mechanics, liquidity/support gaps, and no execution implication |
| `valuation-analyst` | valuation range, scenario assumptions, market-implied expectations, sensitivity | accepted research artifacts and user-stated method constraints | valuation report with assumptions, sensitivity, confidence, and readiness for portfolio/risk review |
| `portfolio-manager` | portfolio fit, sizing context, concentration, liquidity, opportunity cost, draft order intent readiness | accepted research/valuation artifacts and portfolio state | portfolio report and, only when allowed, draft order intent readiness or draft artifact |
| `risk-manager` | downside, restricted-list and policy readiness, limits, approval readiness, approval receipt | accepted portfolio/order artifacts, policy state, restricted-list state, audit evidence | risk/policy report, approval readiness state, approval receipt when allowed, or blocked reasons |
| `execution-operator` | approved paper/stub order submission through TradingCodex MCP | approved order intent, approval receipt, policy allow state | execution result, MCP response, audit reference, or rejected/blocked reasons |

Downstream roles handle weak upstream work by returning a revision request or
`blocked` readiness state. They do not repair missing upstream analysis inside
their own artifact unless the missing work is explicitly within their owned
question.

## Handoff Quality Contract

Every role-to-role handoff is a quality artifact, not just a message. A useful
handoff is accepted only when it contains:

- artifact path or durable DB artifact reference
- original request and binding user constraints, when they affect scope
- role-owned findings with material claims marked `[factual]`, `[inference]`,
  or `[assumption]` where useful
- source/as-of/retrieved-at posture, stale-data warnings, and missing coverage
  for market-sensitive evidence
- confidence, uncertainty drivers, and missing evidence
- readiness label or support gap, using conservative labels
- role-boundary conflicts, if the task asks the role to cross its boundary
- next eligible recipient and actions that remain blocked

Handoff state is one of:

| State | Meaning |
| --- | --- |
| `accepted` | The artifact answers the owned role question and can be consumed downstream. |
| `revise` | The role stayed in bounds, but missing evidence or scope mismatch must be fixed before downstream use. |
| `blocked` | Policy, role boundary, unsupported instrument, stale data, or user constraint blocks downstream action. |
| `waiting` | Required role output does not exist yet, so `head-manager` may provide task briefs but no substantive synthesis. |

`head-manager` is responsible for accepting, revising, blocking, or waiting on
handoffs before moving a workflow forward. It must preserve unresolved
conflicts instead of averaging them into false consensus.

## Head-Manager Dispatch Gate

In investment workflows, `head-manager` is a dispatcher, coordinator, and
synthesizer, not the analyst. Security analysis, investment judgment,
valuation, technical analysis, news analysis, portfolio/risk review, order
drafting, approval, and execution requests must pass through the subagent
dispatch gate.

Natural-language investment requests are sufficient workflow activation for
fixed-role dispatch. Explicit subagent, parallel, delegated-agent, and
`$orchestrate-workflow` requests remain supported as manual-control entrypoints,
but they are not required before `head-manager` routes the work.

| Trigger | Handling |
| --- | --- |
| General investment request, such as "Analyze Apple stock" | `UserPromptSubmit` injects auto-dispatch context with lane, selected team, starter prompt, and blocked actions; `head-manager` dispatches or reuses selected subagents before analysis. |
| Explicit `$orchestrate-workflow` request | The representative workflow skill becomes the primary manual-control orchestrator and dispatches selected subagents. |
| Explicit subagent/parallel/delegated request | `UserPromptSubmit` records the explicit activation source; the skill checks existing subagent state before creating/reusing sessions. |
| Non-investment repository, docs, or harness administration request | No investment dispatch is required; `head-manager` follows normal Codex coding-agent behavior while preserving execution and secret guardrails. |
| Same run/role subagent is active | Wait or follow up instead of creating duplicates. |
| Same role artifact has passed quality gates | Reuse the artifact instead of duplicating work. |
| Codex `spawn_agent` schema cannot select exact fixed role | Treat role routing as `routing-unverified`; provide `waiting_for_subagent_dispatch` and task briefs only. |

The selected role team from hook context or the starter prompt is binding for
the current lane. `head-manager` must not add roles outside that team merely
because they might be useful. For `research_only`, do not add valuation,
portfolio, risk, approval, or execution roles unless the user later asks for
valuation, decision support, portfolio fit, sizing, order drafting, approval,
or execution.

Negated scope terms are binding. Phrases such as "no valuation", "no order", or
"no trading" remove those actions or roles from routing instead of triggering
them as positive intent.

Fail closed: if subagent dispatch is unavailable, the workflow waits.
`head-manager` must not fill the gap with direct analysis.

## Head-Manager Operating Style

For repository, CLI, Django, MCP, template, docs, test, and harness maintenance
work, `head-manager` follows the default Codex coding-agent style: concise
preambles before grouped tool work, plans only for meaningful multi-step tasks,
`rg`-first search, `apply_patch` for manual edits, focused validation before
broader checks, respect for dirty worktrees, and concise final handoffs.

This operating style is a working discipline, not an investment permission.
It does not weaken the dispatch gate, role-owned skill boundary, MCP execution
boundary, approval requirements, or information barriers.

## Allowed And Forbidden Head-Manager Responses

| Situation | Allowed response | Forbidden response |
| --- | --- | --- |
| Broad analysis such as "Analyze Apple stock" | auto-dispatch or reuse selected subagents, then wait for outputs before synthesis | Direct business/price/news/recommendation analysis |
| Explicit workflow request such as "$orchestrate-workflow analyze Apple" | Spawn selected team or reuse active/completed roles, wait for outputs, then synthesize | Analyze without dispatch |
| Decision support such as "Should I buy?" | Dispatch analyst/valuation/portfolio/risk team and explain required artifacts/gates | Offer buy/sell opinion without subagent output |
| Dispatch unavailable, role routing unverified, or dispatch failed | Provide `waiting_for_subagent_dispatch` state and task briefs only | Switch to "I will analyze it myself" |
| Subagent artifacts exist | Summarize role outputs, conflicts, confidence/missing evidence, and next allowed action | Override subagent evidence with unsupported certainty |

## Skills And Context

Repo-local skills live under `.agents/skills/*` so they are discoverable at the
workspace level. TradingCodex treats role-owned skills as an ownership contract
and config boundary.

Instruction/skill separation:

| Surface | Owns | Must not own |
| --- | --- | --- |
| `head-manager` base instructions | durable identity, safety invariants, dispatch fail-closed rule, role boundaries, MCP execution boundary, skill routing | workflow templates, scenario tables, long checklists, subagent message bodies |
| Head-manager skills | repeatable workflow procedures, universe maps, scenario gates, subagent briefing/reuse mechanics, synthesis, profile interview, postmortem workflow | role identity, durable routing authority, MCP allowlists, weakening base guardrails, bypassing role-owned skills, approving or executing directly |
| Fixed subagent TOML | standing role identity, role purpose, artifact wall, model/tool config, MCP allowlist, and always-on prohibitions | per-request user intent, workflow lane decisions, source selection, or temporary task-specific context |
| Role-owned skills | capability procedure, artifact expectations, quality checks, and local output rules | role eligibility, work for other roles, self-approval, execution outside MCP |
| Main-to-subagent briefs | request-specific assignment envelope: verbatim user request, explicit constraints, workflow consent posture, lane, artifact path, material context, data-cutoff needs, request-specific out-of-scope items, and return contract | standing role manuals, model/tool config, MCP allowlists, long method checklists, long source-class lists, or repeated guardrail prose |

Repo skill bodies are dependency-light capability references. They should not
declare role ownership, encode role-specific eligibility, or maintain direct
inter-skill call chains. Role-to-skill assignment belongs to `ROLE_SKILL_MAP`,
subagent TOML `skills.config`, CLI/Admin assignment state, and durable
instructions. A skill may mention a concrete principal only when that principal
is part of a policy or artifact contract, such as `created_by` or `approved_by`
validation.

Every repo skill should include `agents/openai.yaml` metadata with a concise
display name, short description, default prompt that names its `$skill`, and an
explicit implicit-invocation policy. Metadata is UI-facing; it must not be the
only place where durable role or safety behavior lives.

The root/head-manager session can inspect and assign role-owned skills, but
must not use analyst, portfolio, risk, approval, or execution skills to fill in
role work directly.

User-visible skill lists are not the same as enabled or installed skills. The
main-agent user surface should show only direct user entrypoints by default:

- `orchestrate-workflow`
- `head-manager-interview`
- `postmortem`

Internal head-manager harness skills such as `investment-workflow-map`,
`scenario-quality-gates`, `manage-subagents`, and `synthesize-decision` remain
enabled for `head-manager`; they are hidden from the default user-facing list,
not disabled.

Head-manager skill responsibilities:

| Skill | Responsibility |
| --- | --- |
| `orchestrate-workflow` | stage sequencing, lane escalation, and movement across research, thesis, portfolio, risk, order, approval, execution, and postmortem |
| `investment-workflow-map` | universe/workflow classification, source/as-of posture, support gaps, hero/support artifacts, and readiness labels |
| `scenario-quality-gates` | scenario selection, minimum useful role-team shape, artifact expectations, blocked actions, and quality gates |
| `external-data-source-gate` | read-only external evidence-source constraints and connector honesty |
| `manage-subagents` | fixed-role dispatch mechanics, runtime state/reuse checks, compact briefs, artifact review, and conflict handling |
| `synthesize-decision` | user-facing decision state after required artifacts or outputs exist |
| `head-manager-interview` | durable investor/operator profile, suitability context, constraints, and tone calibration |
| `postmortem` | audit-backed process review and improvement proposals after failures, thesis changes, rejected orders, or executions |

## Skill Proposal Flow

The built-in role skill map is a bootstrap baseline. Role skill changes move
through workspace proposal files so they can be inspected, validated, and
projected without hidden prompt drift.

Expected flow:

```text
proposal file -> validation -> projection -> generated manifest
```

Codex-visible applied state is file-native: `.codex/agents/*.toml`,
`.agents/skills/*`, `.codex/config.toml`, and
`.tradingcodex/generated/projection-manifest.json`. Django DB does not store
skill proposals, role-skill assignments, or skill application audit state.
CLI and the product web app should both call shared projection helpers for
proposal operations. Django Admin remains focused on DB-backed runtime
operations.

## Subagent Isolation

- Subagent context is intentionally minimized.
- `head-manager` keeps full product and harness context.
- Fixed subagent TOML files supply the standing role-local card: affiliation, coordinator, assigned role, role purpose, own artifact paths, handoff target, and forbidden actions.
- Per-task subagent briefs are assignment envelopes, not role manuals. They should add only the current task, original request, explicit constraints, workflow consent posture, lane, expected artifact path, material context, request-specific stage boundaries, and concise return contract.
- When selecting an exact fixed role with Codex `spawn_agent`, do not combine `agent_type` with full-history forking. Use a compact assignment envelope on the first attempt and no model/reasoning overrides.
- Workflow consent stays separate from explicit user constraints. Consent to orchestrate or use subagents allows dispatch, but it is not itself an analytical constraint.
- Execution roles may additionally receive the workspace MCP boundary because they need it to submit approved actions.
- MCP/tool isolation is configured per role in `.codex/agents/*.toml`.
- Generated fixed-role subagent TOML files pin `model = "gpt-5.5"` and `model_reasoning_effort = "high"`.
- Spawn by fixed role label so the role file supplies runtime defaults.
- If the active Codex schema cannot select the exact fixed role, role routing is `routing-unverified`.

The root `head-manager` MCP allowlist intentionally excludes
`submit_approved_order`, `cancel_approved_order`, and approval creation.
`risk-manager` owns approval receipt creation; `execution-operator` owns
experimental submit/cancel execution tools.

## Hooks Are Guidance

- `UserPromptSubmit` handles prompt classification, secret warnings, direct-answer prevention context, and duplicate marker management.
- Official `UserPromptSubmit` matchers are ignored, so classification happens inside the hook script.
- Hooks use command type only and do not rely on ordering or concurrency between hooks.
- Project-local hooks load only in trusted projects and may be disabled when `features.hooks=false`.
- Hooks are not enforcement. TradingCodex MCP, permissions, and policy validation block actual order/approval/execution actions.

## Investment Workflow Map

TradingCodex does not collapse investment work into generic "stock analysis."
`head-manager` first classifies universe and workflow type, then uses quality
gates to determine lane, role team, artifacts, and blocked actions.

| Workflow type | Typical outputs | Core quality point |
| --- | --- | --- |
| Issuer baseline / tearsheet | factual issuer profile, evidence pack | no recommendation without thesis/valuation/risk handoff |
| Idea triage / watchlist | candidate funnel, research priority, next workflow | research priority is not an investment recommendation |
| Earnings preview / deep dive | expectation bar, thesis change, source posture | freeze time and distinguish reported facts, consensus, assumptions, and PM judgment |
| Catalyst calendar / thesis tracker | dated calendar, monitoring rules, append-only update log | confirmed dates, inferred windows, and action thresholds stay distinct |
| Valuation / model / scenario | valuation report, workbook, sensitivity map | current-price implication and source-backed assumptions are explicit |
| Position sizing / hedge | risk decision report, binding constraint, retained exposure | missing price/liquidity/borrow/options inputs block implementation-ready language |
| Model audit / normalization / QC | audit issue log, normalization pack, circulation memo | support findings affect readiness but do not create a conclusion by themselves |

## Module Graph

The initial default module graph is the baseline harness installed by the
product, not a user-selected operating phase.

| Module | Role |
| --- | --- |
| `codex-base` | base Codex config, head-manager constitution, hooks, rules, workspace scripts |
| `fixed-subagents` | fixed role subagent roster |
| `repo-skills` | repeatable investment workflow skills |
| `guidance-guardrails` | instruction, workflow, hook, and checklist-based guidance |
| `enforcement-guardrails` | schemas, policy, deterministic validation input |
| `information-barriers` | file boundary, policy wall, secret wall, trading folders |
| `audit` | audit directory and append-only event convention |
| `tradingcodex-mcp` | MCP enforcement boundary and approved-action gateway |
| `stub-execution` | fake execution for policy/MCP wiring tests |
| `paper-trading` | simulated portfolio execution without live brokers |
| `postmortem` | audit-backed investment process review |
