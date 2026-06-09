# TradingCodex Core Concepts And Rules

This document is the fast reference for TradingCodex concepts and operating rules. Use [tradingcodex-prd.md](./tradingcodex-prd.md) for product background and scope decisions.

## One-Line Product Definition

TradingCodex is a Python/Django-native trading harness that lets an investor use Codex for research, decision support, approvals, and stub/paper execution while ensuring every executable action crosses a deterministic Django service layer and TradingCodex MCP enforcement boundary. Public equity is the first deeply specified sleeve, but the product is designed as a multi-universe investment harness.

## Product Language

TradingCodex is written in English. Durable docs, generated workspace instructions, Admin UI, CLI help, product copy, role prompts, and user-facing examples should use English. Internal classifiers may support broader user input when useful, but generated product guidance should remain English.

## Core Principles

| Principle | Meaning | Implementation rule |
| --- | --- | --- |
| Agents request actions | Agents analyze, review, draft intents, and request validation. | Natural-language answers must not become broker actions. |
| Django service layer is canonical | Product web, Admin, REST, MCP, and CLI call the same application services. | Do not duplicate policy, order, approval, execution, or research logic per interface. |
| Central DB is the investment ledger | Mutable state and research markdown live in the user-level central Django DB. | Codex projects are clients/provenance; markdown/json files are export/cache/artifact layers. |
| TradingCodex MCP owns executable boundary | Broker credentials and executable action boundaries belong to MCP/service-layer paths. | Raw API keys must not appear in workspace files, shell output, agent prompts, API responses, MCP responses, or audit output. |
| Enforcement is deterministic | Blocking decisions are reproducible code/policy decisions. | Final order paths revalidate policy, schema, and approval. |
| Capability is an allowlist | Permission is explicit and narrow. | Allowing one action does not imply policy write, secret read, or cash movement. |
| Information barriers control knowledge flow | Roles receive only the information they need. | Maintain research, execution, policy, and secret walls. |
| Task harness improves work quality | The harness should help produce better investment work, not just block bad actions. | Manage skills, schemas, workflows, checklists, and postmortems together. |
| Claim discipline limits false certainty | Investment outputs separate facts, inferences, and assumptions. | Use `[factual]`, `[inference]`, and `[assumption]` in narrative handoffs where relevant. |
| Workflow mapping improves routing | Classify universe and workflow type before dispatch. | Public equity is the first concrete sleeve, not the only universe. Unsupported universes are downgraded to research-only, screen-grade, not-decision-ready, or blocked. |

## Guardrail Types

| Type | Purpose | Examples | Limit |
| --- | --- | --- | --- |
| Guidance guardrail | Reduce the chance of risky behavior. | `AGENTS.md`, skills, subagent instructions, hooks, checklists, MCP instructions | Guidance is not enforcement unless it deterministically blocks the final action. |
| Enforcement guardrail | Deterministically block risky action completion. | forbidden rules, permissions, approval policy, MCP tool allowlist, TradingCodex MCP enforcer | Must sit on the final execution path. |
| Information barrier | Control knowledge and file-access flow. | `.tradingcodex/capabilities.yaml`, restricted list, role file boundaries, secret wall | Does not guarantee output quality by itself. |
| Task harness | Standardize artifact quality and handoffs. | `.agents/skills/*`, schemas, workflows, quality checklist, postmortem | Separate guardrails still block direct broker/API action. |

## Control Plane, Service Plane, System Plane

| Plane | Responsibility | Key files/config |
| --- | --- | --- |
| Codex control plane | agent behavior, workflow, tool surface, Codex-level guardrails | `.codex/config.toml`, `.codex/agents/*.toml`, `.agents/skills/*`, hooks, rules |
| Django service plane | durable policy/order/portfolio/research/audit/harness/integration logic, product web dashboard, Admin, Ninja API, MCP HTTP endpoint | `tradingcodex_service/`, `apps/*`, `manage.py`, central SQLite/PostgreSQL-ready schema |
| TradingCodex workspace system plane | generated schemas, policy exports, approved-action gateway wrappers, readable exports/cache | `.tradingcodex/schemas/*`, `.tradingcodex/policies/*`, `.tradingcodex/mcp/*`, `trading/*` exports |

The product web app at `/` is the user-facing visual review surface for harness topology, research memory, paper portfolio state, orders, policy, activity, and Codex starter prompts. Django Admin is the local/staff harness operations console. Django Ninja is the typed REST/control API. None of these surfaces is an execution-boundary bypass. Risky changes go through proposal, validation, approval, apply, and audit flows in the service layer.

`tcx init` prepares both the generated workspace files and the central Django runtime DB. It accepts an empty directory or a git-initialized directory containing only `.git` plus optional git metadata files. It sets the Django settings module, applies the central runtime schema, and records workspace provenance while preserving the rule that workspaces do not own canonical investment state.

## Product Web Rule

- The product web app is review-first and visual-first. Its primary surface is the harness canvas showing `head-manager`, the nine fixed subagents, role skill ownership, MCP tool exposure, policy gates, and recent activity.
- Product web routes must not spawn Codex subagents, run investment analysis, create approval receipts, submit approved orders, mutate policy, or read secrets.
- The starter prompt generator prepares text for Codex-native orchestration. It does not make Django the agent runtime.
- HTMX refreshes fragments such as role inspectors and starter prompt previews. Alpine handles local UI state such as selected role, zoom, and edge-group toggles.
- Any future SDK-backed agent orchestration is a separate feature-flagged mode, not the default product web behavior.

## MCP Registry Rule

- MCP tools are declared in a Python registry with stable names, descriptions, input schemas, risk levels, role allowlists, approval requirements, and audit requirements.
- The registry syncs into `McpToolDefinition` so Django Admin can inspect, enable, and disable tool exposure without editing generated config files.
- `McpToolCall` is the central DB-visible call ledger. Tool calls record principal, workspace provenance, status, request hash, result hash, errors, and duration.
- Generated workspaces expose `./tcx mcp ledger` for local/staff operators and harness tests.
- MCP tool execution applies role allowlists before handler dispatch, then calls the same service-layer functions used by Admin, Ninja, and CLI.
- MCP tool execution also checks active `Principal` rows and matching `Capability` rows. Role allowlists do not override an inactive principal or denied capability.
- REST/Ninja endpoints are not automatically MCP tools. A REST endpoint becomes agent-callable only when the MCP registry intentionally exposes the corresponding service-layer use case.

## Research Memory Rule

- `ResearchArtifact` and `ResearchArtifactVersion` are canonical records for markdown body, metadata, source/as-of posture, readiness label, content hash, version, and role/user provenance.
- `WorkspaceContext` records which Codex project called the service. It is provenance, not an investment-state partition key.
- `trading/research/*.md` and `trading/reports/*/*.md` are DB artifact exports/caches.
- Codex and subagents should use MCP tools such as `create_research_artifact`, `get_research_artifact`, `list_research_artifacts`, `search_research_artifacts`, `export_research_artifact_md`, and `record_source_snapshot` when DB access is available.
- If a DB artifact exists, runtime memory exists even when no export file exists. If only a file exists without a DB record, it is not canonical research memory.
- Investment research freshness matters more than old-note recall. Source/as-of posture, retrieved-at metadata, stale-data warnings, versioning, and invalidation are the default quality levers.

## Skills And Context

Repo-local skills live under `.agents/skills/*` so they are discoverable at the workspace level. TradingCodex treats role-owned skills as an ownership contract and config boundary. The root/head-manager session can inspect and assign role-owned skills, but must not use analyst, portfolio, risk, approval, or execution skills to fill in role work directly.

User-visible skill lists are not the same as enabled or installed skills. The main-agent user surface should show only direct user entrypoints by default: `orchestrate-workflow`, `head-manager-interview`, and `postmortem`. Internal head-manager harness skills such as `investment-workflow-map`, `scenario-quality-gates`, `manage-subagents`, and `synthesize-decision` remain enabled for `head-manager`; they are hidden from the default user-facing list, not disabled. Use `./tcx skills list --all` or role-specific skill views for audit and debugging.

The built-in role skill map is a bootstrap baseline. `./tcx subagents skills <role>` shows the current role skill view, including approved/user-maintained skill changes through the skill proposal flow. Analysis and review roles should choose the assigned skill that fits the request instead of being forced into one default analysis skill. Mandatory skills are reserved for workflow-critical or safety-critical boundaries such as external data gating, draft order intent creation, approval receipts, and execution through the workspace MCP boundary.

Subagent context is intentionally minimized. `head-manager` keeps full product and harness context. Subagents receive a role-local card: affiliation, coordinator, assigned role, role purpose, own artifact paths, handoff target, and forbidden actions. Execution roles may additionally receive the workspace MCP boundary because they need it to submit approved actions.

## Fixed Role Roster

TradingCodex always uses `head-manager` as the main agent, with a fixed default subagent roster.

| Role | Responsibility | Never allowed |
| --- | --- | --- |
| `head-manager` | workflow dispatch, subagent coordination, synthesis, validation/audit status tracking | Finalize investment conclusions without subagent output, call broker APIs directly |
| `fundamental-analyst` | business, financial statement, official disclosure, and competitive analysis | order intent, approval, execution, secret read |
| `technical-analyst` | price action, trend, momentum, volume, volatility | order intent, execution, standalone investment conclusion |
| `news-analyst` | news, disclosure events, macro events, narrative change | assert unverified rumors, execution |
| `macro-analyst` | macro, rates, FX, commodities, liquidity, policy, cross-asset transmission | order intent, execution, unsupported implementation claims |
| `instrument-analyst` | ETF/index, options/derivatives, crypto public market structure, credit-signal boundary, instrument mechanics | order intent, execution, unsupported instrument execution claims |
| `valuation-analyst` | DCF, reverse DCF, multiples, scenario, expected return | approval, execution, broker API call |
| `portfolio-manager` | portfolio fit, sizing, draft order intent | self-approval, execution, arbitrary policy changes |
| `risk-manager` | risk review, policy review, approval readiness, approval receipt | order drafting, execution, arbitrary policy changes |
| `execution-operator` | submit approved order intents through TradingCodex MCP | raw broker API, secret read, policy change |

## Head-Manager Dispatch Gate

In investment workflows, `head-manager` is a dispatcher, coordinator, and synthesizer, not the analyst. Security analysis, investment judgment, valuation, technical analysis, news analysis, portfolio/risk review, order drafting, approval, and execution requests must pass through the subagent dispatch gate.

Codex currently spawns subagents only when the user explicitly asks for subagent, parallel agent, or delegated agent work. TradingCodex also treats explicit `$orchestrate-workflow` usage as workflow consent. Do not assume hidden developer instructions or hooks can automatically fan out work.

Hybrid policy:

| Trigger | Handling |
| --- | --- |
| General investment request, such as "Analyze Apple stock" | `UserPromptSubmit` injects `confirmation_required`; `head-manager` asks for `$orchestrate-workflow` confirmation or provides a starter prompt instead of doing analysis directly. |
| Explicit `$orchestrate-workflow` request | The representative workflow skill becomes the primary orchestrator and dispatches selected subagents. |
| Explicit subagent/parallel/delegated request | `UserPromptSubmit` injects `dispatch_allowed`; the skill checks existing subagent state before creating/reusing sessions. |
| Same run/role subagent is active | Wait or follow up instead of creating duplicates. |
| Same role artifact has passed quality gates | Reuse the artifact instead of duplicating work. |

| Situation | Allowed head-manager response | Forbidden head-manager response |
| --- | --- | --- |
| Broad analysis such as "Analyze Apple stock" | research-only lane, selected team, artifact paths, subagent workflow confirmation, or starter prompt | Direct business/price/news/recommendation analysis |
| Explicit workflow request such as "$orchestrate-workflow analyze Apple" | Spawn selected team or reuse active/completed roles, wait for outputs, then synthesize | Analyze without dispatch |
| Decision support such as "Should I buy?" | Dispatch analyst/valuation/portfolio/risk team and explain required artifacts/gates | Offer buy/sell opinion without subagent output |
| Subagent creation is unavailable or failed | Provide `waiting_for_subagent_dispatch` state and task briefs only | Switch to "I will analyze it myself" |
| Subagent artifacts exist | Summarize role outputs, conflicts, confidence/missing evidence, and next allowed action | Override subagent evidence with unsupported certainty |

Fail closed: if subagent dispatch is unavailable, the workflow waits. `head-manager` must not fill the gap with direct analysis.

## Hooks Are Guidance

- `UserPromptSubmit` handles prompt classification, secret warnings, direct-answer prevention context, and duplicate marker management.
- Official `UserPromptSubmit` matchers are ignored, so classification happens inside the hook script.
- Hooks use command type only and do not rely on ordering or concurrency between hooks.
- Project-local hooks load only in trusted projects and may be disabled when `features.hooks=false`.
- Hooks are not enforcement. TradingCodex MCP, permissions, and policy validation block actual order/approval/execution actions.

## Subagent Isolation

- MCP/tool isolation is configured per role in `.codex/agents/*.toml`.
- Generated workspaces configure TradingCodex MCP as a project-scoped Codex
  server in `.codex/config.toml`. Per the OpenAI Codex configuration model,
  project-scoped `.codex/config.toml` layers load only after the project is
  trusted.
- The generated TradingCodex MCP config sets
  `TRADINGCODEX_MCP_AUTOSTART_SERVICE=1`, so trusted Codex sessions start the
  MCP stdio bridge and the local Django dashboard service together. The MCP
  command invokes `python -m tradingcodex_cli mcp stdio` through
  `uvx --refresh --from <package-spec>`, and bootstrap records the package spec
  so GitHub-source installs do not silently fall back to PyPI or reuse stale
  source-cache builds.
  The autostart path must be idempotent, must not write non-MCP output to
  stdout, and must not be required for direct `./tcx mcp stdio` smoke checks.
- Generated fixed-role subagent TOML files pin `model = "gpt-5.5"` and `model_reasoning_effort = "high"`; spawn by fixed role label so the role file supplies these runtime defaults.
- The root `head-manager` MCP allowlist intentionally excludes
  `submit_approved_order`, `cancel_approved_order`, and approval creation.
  `risk-manager` owns approval receipt creation; `execution-operator` owns
  experimental submit/cancel execution tools.
- MCP registry role allowlists are a second boundary after `.codex/agents/*.toml`.
- Secret isolation is stronger than ordinary file guidance because `.codex/config.toml` denies `.env`, `.tradingcodex/secrets.md`, and broker credential paths through the TradingCodex permissions profile.
- Role file walls are documented in `.tradingcodex/policies/information-barriers.yaml`, repeated in subagent instructions, and mapped to role-specific `default_permissions` profiles in `.codex/config.toml`.
- TradingCodex MCP still revalidates executable actions, so a file-wall miss must not become an order, approval bypass, secret read, or broker action.
- Policy simulation denies self-approval, direct broker API variants, generic `execute_order`-style actions, and live execution resources unless a documented adapter path is installed behind the TradingCodex MCP lifecycle.

## Execution Lifecycle

| Step | Artifact/action | Owner | Required rule |
| --- | --- | --- | --- |
| Evidence collection | evidence pack | analysts | separate sources, dates, facts, and assumptions |
| Analysis | analyst reports, valuation | role subagents | maintain each role's information barrier |
| Portfolio fit | portfolio review | `portfolio-manager` | check sizing, cash, concentration, and fit |
| Draft order | `trading/orders/draft/*.order_intent.json` | `portfolio-manager` | no execution before schema and policy validation |
| Risk review | risk/policy report | `risk-manager` | check restricted list, downside, limits, and approval readiness |
| Approval | `trading/approvals/*.approval_receipt.json` | `risk-manager` or approved flow | no self-approval, no forged receipts |
| Execution | `submit_approved_order` through TradingCodex MCP | `execution-operator` | revalidate order intent and approval receipt in MCP |
| Audit/postmortem | audit event, execution result, postmortem | MCP/head-manager | record rejects, approvals, executions, and policy decisions |

Approved execution is idempotent by order boundary. A repeated `submit_approved_order` call for an order that already has an `ExecutionResult` must be rejected before any adapter is called.

Paper/stub execution remains experimental in the current release line. Keep the
code and guardrails available for local harness validation, but do not present
it as production trading infrastructure or live broker support.

## Routing Guardrail

- `no order`, `no trading`, `do not place trades`, and equivalent negations must keep a request out of execution routing.
- Guardrail-verification wording such as "verify blocked order/approval/execution actions" or "blocked action wording like execute/submit/approve/order" is evidence of a safety check, not a request to execute.
- Public-equity earnings, filing, catalyst, thesis, and valuation requests route to thesis-review style research/valuation support unless the user separately asks for portfolio fit, order drafting, approval, or execution.

## Quality Harness Floor

TradingCodex investment reports, role handoffs, and final syntheses share the `investment-workflow-map` and `scenario-quality-gates` quality floor.

| Rule | Application |
| --- | --- |
| Claim tags | Mark material narrative claims as `[factual]`, `[inference]`, or `[assumption]` in handoff narrative where useful. |
| `[factual]` | Use only for verified data, cited source content, existing artifact content, or directly observed command/tool output. |
| `[inference]` | Use for analytical conclusions, risk judgments, and thesis-change judgments derived from evidence. |
| `[assumption]` | Use for scenario inputs, transaction cost, capacity, correlation, liquidity, sizing, and modeling choices. |
| Anti-fabrication | Do not invent metrics, factor loadings, transaction costs, validation results, source dates, market prices, filings, approvals, executions, or artifact content. |
| Uncertainty disclosure | Disclose small samples, thin regime coverage, high parameter sensitivity, and weak source coverage. |
| Suggestive vs conclusive | If evidence is suggestive, say so instead of turning it into a conclusion. |
| Empirical vs economic | Separate empirical stability from economic plausibility. |
| Paper vs live | State when paper alpha may disappear under live implementation friction. |
| Confidence | Lower confidence when data quality, source coverage, sample size, regime coverage, or validation setup is weak. |
| Source/as-of posture | For market-sensitive inputs, record source date, as-of, retrieved-at, provider/tool, and missing/stale warnings. |
| Hero/support artifact split | Choose the user-facing report, tracker, workbook, or synthesis first; keep CSV/JSON/run log/source indexes as support/audit layers. |
| Conservative readiness | Use conservative labels such as `factual-baseline`, `screen-grade`, `not-decision-ready`, `ready-for-portfolio-risk`, `ready-for-draft`, or `blocked`. |

## Investment Workflow Map

TradingCodex does not collapse investment work into generic "stock analysis." `head-manager` first classifies universe and workflow type, then uses `scenario-quality-gates` to determine lane, role team, artifacts, and blocked actions. Public equity is the first concrete sleeve. Crypto public markets, macro/rates/FX/commodities, ETF/index, cross-asset overlays, and credit signals are treated as research or risk inputs within installed role skills, read-only sources, and policy boundaries.

| Workflow type | Typical outputs | Core quality point |
| --- | --- | --- |
| Issuer baseline / tearsheet | factual issuer profile, evidence pack | no recommendation without thesis/valuation/risk handoff |
| Idea triage / watchlist | candidate funnel, research priority, next workflow | research priority is not an investment recommendation |
| Earnings preview / deep dive | expectation bar, thesis change, source posture | freeze time and distinguish reported facts, consensus, assumptions, and PM judgment |
| Catalyst calendar / thesis tracker | dated calendar, monitoring rules, append-only update log | confirmed dates, inferred windows, and action thresholds stay distinct |
| Valuation / model / scenario | valuation report, workbook, sensitivity map | current-price implication and source-backed assumptions are explicit |
| Position sizing / hedge | risk decision report, binding constraint, retained exposure | missing price/liquidity/borrow/options inputs block implementation-ready language |
| Model audit / normalization / QC | audit issue log, normalization pack, circulation memo | support findings affect readiness but do not create a conclusion by themselves |

## Artifact Export Paths

TradingCodex canonical research/order/portfolio runtime state lives in the central Django DB. The paths below are readable export/cache/artifact paths for Codex and humans. Execution-sensitive state is updated by the MCP/service layer, while policy decisions remain service-layer decisions.

| Artifact | Path |
| --- | --- |
| Evidence packs | `trading/research/*.evidence.md` |
| Fundamental reports | `trading/reports/fundamental/` |
| Technical reports | `trading/reports/technical/` |
| News reports | `trading/reports/news/` |
| Macro reports | `trading/reports/macro/` |
| Instrument reports | `trading/reports/instrument/` |
| Valuation reports | `trading/reports/valuation/` |
| Portfolio reports | `trading/reports/portfolio/` |
| Risk/policy reports | `trading/reports/risk/`, `trading/reports/policy/` |
| Draft orders | `trading/orders/draft/*.order_intent.json` |
| Approved orders | `trading/orders/approved/*.order_intent.json` |
| Approval receipts | `trading/approvals/*.approval_receipt.json` |
| Executed orders | `trading/orders/executed/*.execution_result.json` |
| Postmortems | `trading/reports/postmortem/*.postmortem_report.json` |
| Skill change proposals | `.tradingcodex/mainagent/skill-change-proposals/*.yaml` |

## Module Graph

The initial default module graph is the baseline harness installed by the product, not a user-selected operating phase. Source templates live under `workspace_templates/modules/*`; runtime allow/deny decisions belong to the Django service layer and TradingCodex MCP.

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

## Documentation Rules

| Rule | Application |
| --- | --- |
| Durable rule change requires docs update | Product direction, safety rules, role responsibilities, execution boundary, or artifact contracts require docs updates. |
| Docs are source of truth | PRD and this document record intent above implementation. If implementation differs, decide explicitly which side changes. |
| Avoid hidden policy drift | Do not hide durable rules only in templates, tests, MCP, or skills. Document durable rules here. |
| Keep docs concise | Keep implementation logs in code; keep durable concepts, rules, and decision criteria in docs. |
| Keep product language English | Do not add non-English durable copy to docs, generated workspace guidance, Admin UI, CLI help, role prompts, or examples. |
