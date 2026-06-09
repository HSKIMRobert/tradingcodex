# TradingCodex PRD

## Product Definition

TradingCodex is a local-first trading harness that runs Codex-assisted investment workflows as a Python/Django modular monolith. Codex projects are workspaces and clients; the TradingCodex Django service and central local DB are the investment ledger. Codex, subagents, the local CLI, product web app, Django Admin, Django Ninja API, and Django-hosted MCP all call the same service layer. Executable actions must pass policy, approval, adapter-boundary, and audit checks. Runtime state and research memory are canonical in the Django DB; markdown/json files are human-readable export, cache, and artifact layers for Codex.

Target runtime:

- Python: latest LTS target, currently Python 3.14 line.
- Django: latest LTS target, currently Django 5.2.x.
- Database default: central local SQLite at `~/.tradingcodex/state/tradingcodex.sqlite3`, with `TRADINGCODEX_HOME` and `TRADINGCODEX_DB_NAME` overrides and PostgreSQL-ready model design.
- Deployment default: local-only. The product is not optimized around cloud deployment in the initial scope.
- Product language: English. Durable docs, generated workspace guidance, Admin UI, CLI help, and user-facing product copy are written in English.

TradingCodex is not financial, investment, legal, tax, or regulatory advice. It is research, workflow, and execution-guardrail tooling. Users remain responsible for decisions, broker integrations, compliance, and outcomes.

Licensing baseline: TradingCodex uses an Apache-2.0 open-core strategy. The
repository open core is permissively licensed, while TradingCodex marks,
official hosted services, verified adapters, enterprise policy/compliance
packs, support, and managed deployments may be governed by separate commercial
terms. Generated workspace scaffold files remain under the repository license;
user-created research, portfolio data, order artifacts, configuration secrets,
and other user-provided content remain owned by the user unless separately
licensed or contributed. See `docs/licensing-and-commercialization.md`.

## Product Goals

| Goal | Meaning |
| --- | --- |
| Codex-native workflow | Preserve `.codex/`, `.agents/skills/`, hooks, generated workspace behavior, and role prompts. |
| Durable service plane | Put policy, order, portfolio, audit, harness, integration, and MCP logic behind Django services. |
| DB-first memory | Store mutable runtime state, research markdown, source snapshots, order lifecycle, portfolio state, policy decisions, and audit metadata in Django DB. |
| Visual harness dashboard | Use the product web app at `/` to show the main agent, subagents, skills, MCP tool boundaries, policy gates, research memory, portfolio state, and ledger activity. |
| Deterministic execution boundary | All executable order paths must revalidate principal, capability, policy, schema, approval, idempotency, adapter, and audit. |
| Harness operations console | Use Django Admin to inspect and operate roster, skills, proposals, policy, tools, workflow runs, approvals, executions, and audit events. |
| Typed local APIs | Use Django Ninja for local/staff REST and control APIs. REST is for status, validation, and operations; it is not an execution bypass. |
| Broader investment universe | Public equity is the deepest first sleeve, but TradingCodex also routes ETF/index, public crypto, macro/rates/FX/commodities, options, credit-signal, and cross-asset support workflows. |
| Extensible adapters | Paper and stub execution are shipped first as experimental local harness surfaces. Live broker adapters remain disabled and unimplemented until separately installed behind the same boundary. |

## Non-Goals

- No built-in live broker execution in the initial core.
- Paper/stub execution is included as experimental local harness behavior in this release line, not production trading infrastructure.
- No raw broker credential storage in generated workspaces.
- No trademark grant, official endorsement grant, hosted-service license, or
  verified-adapter/commercial-pack license is implied by the open-core source
  license.
- No promise that research-only workflows are decision-ready.
- No automatic subagent spawning when Codex does not expose explicit delegated workflow capability.
- No SDK-backed agent orchestration from Django in v1. The web app can prepare Codex starter prompts, but Codex-native workflow remains the primary orchestration path.
- No REST endpoint that bypasses MCP/service-layer execution policy.
- No hidden policy drift in templates, hooks, or tests without a matching docs update.

## Architecture

```text
Multiple Codex projects / subagents / local CLI
  -> product web review dashboard, Django-hosted MCP endpoint, or stdio bridge
  -> Django service layer
  -> central Django DB-backed policy, research, orders, portfolio, audit, harness, integrations
  -> paper/stub adapter boundary; future live adapters only after separate installation and policy approval
```

The source tree is organized around the Python product:

```text
pyproject.toml
manage.py
tradingcodex_service/
tradingcodex_cli/
apps/
  audit/
  harness/
  integrations/
  mcp/
  orders/
  policy/
  portfolio/
  research/
  universes/
  workflows/
workspace_templates/
tests/
docs/
```

## Django App Boundaries

| App | Responsibility |
| --- | --- |
| `harness` | subagent roster, role skill map, skill proposals, generated workspace config, workspace provenance |
| `workflows` | workflow lanes, workflow runs, artifact handoffs, readiness labels |
| `policy` | principals, capabilities, restricted list, limits, policy decisions |
| `orders` | order intents, approvals, execution results |
| `portfolio` | cash, positions, exposure snapshots, paper portfolio state |
| `research` | DB-backed markdown research artifacts, artifact versions, evidence packs, report metadata, source/as-of records |
| `audit` | append-only audit events and request/result hashes |
| `mcp` | protocol adapter metadata, tool registry, tool call ledger |
| `integrations` | paper/stub adapters, read-only data adapters, future broker adapters |
| `universes` | public equity, ETF/index, crypto, macro/rates/FX/commodities, options, credit-signal workflow plugins |

The app boundary is modular-monolith ownership, not a distributed-service boundary. Admin, Ninja, MCP, and CLI must call the same application services.

## Service Layer

Executable use cases:

- `create_order_intent`
- `validate_order_intent`
- `create_approval_receipt`
- `submit_approved_order`
- `simulate_policy`
- `record_execution_result`

Read-only use cases:

- `get_harness_topology`
- `get_role_detail`
- `get_harness_health`
- `list_recent_activity`
- `list_policy_overview`
- `list_positions`
- `get_portfolio_snapshot`
- `list_workflow_artifacts`
- `create_research_artifact`
- `get_research_artifact`
- `list_research_artifacts`
- `search_research_artifacts`
- `export_research_artifact_md`
- `record_source_snapshot`
- `inspect_harness_state`

Every executable use case follows:

```text
principal -> capability -> policy -> schema -> approval/idempotency -> adapter -> audit
```

Adapter calls are policy-checked immediately before submission. Admin actions and REST endpoints do not mutate execution state directly.

Workspace roots are provenance, not state partitions. A generated Codex project may export markdown/json artifacts, but canonical research, orders, approvals, executions, portfolio snapshots, policy decisions, MCP calls, and audit events live in the central TradingCodex DB.

## Product Web App

TradingCodex provides a separate user-facing web app at `/`. It is a dashboard and review surface, not a table-first Admin replacement.

Routes:

- `/` visual dashboard
- `/harness/` full harness topology
- `/research/` DB-backed research memory review
- `/portfolio/` central paper portfolio state
- `/orders/` order, approval, and execution lifecycle review
- `/policy/` restricted list and policy decision review
- `/activity/` MCP call ledger, audit events, and workflow activity
- `/workflow/starter-prompt/` Codex starter prompt generator

The product web app uses Django templates, local static HTMX, and local static Alpine. There is no Node, bundler, React, or frontend build step in the baseline.

The visual harness canvas is server-rendered SVG/HTML. It shows:

- center node: `head-manager`
- surrounding nodes: the nine fixed subagents
- edge groups: dispatch, research handoff, portfolio/risk gate, approval gate, execution gate
- role inspector: owned skills, allowed MCP tools, forbidden actions, latest artifacts, latest activity
- MCP execution boundary: principal, policy, schema, approval, adapter, and audit checks

Web boundary rules:

- The product web app does not spawn Codex subagents.
- The product web app does not generate investment analysis.
- The product web app does not approve or execute orders in v1.
- The product web app can generate starter prompts for the user to run in Codex.
- Execution-sensitive actions remain behind TradingCodex MCP and service-layer policy.

SDK policy:

- V1 does not add a direct Codex SDK dependency or OpenAI Agents SDK orchestration mode.
- If an official Python Codex SDK becomes available later, it must be added behind an explicit feature flag and still use TradingCodex MCP/service-layer policy for approvals, execution, audit, and research memory.
- If OpenAI Agents SDK Python is used later, it is a separate experimental orchestration mode because it makes Django own agent orchestration, tool execution, approvals, and state.

## Admin Console

Django Admin is the harness control panel for local/staff operators.

Admin can inspect and manage:

- role roster and role skill assignments
- skill proposals and generated workspace config
- policy, restricted symbols, capability allowlists, limits
- MCP tool registry and tool call ledger
- workflow runs, artifact refs, readiness labels
- order intents, approval receipts, execution results
- research artifacts, markdown versions, source snapshots
- portfolio snapshots, positions, cash balances
- adapter definitions and universe plugins
- audit logs

Risky changes use:

```text
proposal -> validation -> approval -> apply -> audit
```

Admin actions must call the service layer and create audit events.

Admin operations include built-in actions for enabling/disabling MCP tools, syncing the built-in MCP registry, approving/applying/rejecting skill proposals, toggling principals/capabilities/restricted symbols, and disabling live adapters. These actions are harness operations and must create audit records.

## REST API

Django Ninja provides local/staff typed control APIs:

- `GET /api/health`
- `GET /api/harness/status`
- `GET /api/subagents`
- `GET /api/subagents/{role}/skills`
- `GET /api/workflows/{id}`
- `POST /api/workflows/{id}/validate`
- `POST /api/policy/simulate`
- `POST /api/orders/validate-intent`
- `POST /api/approvals`
- `POST /api/executions/submit-approved`
- `GET /api/audit/events`
- `GET /api/portfolio/snapshot`
- `POST /api/research/artifacts`
- `GET /api/research/artifacts`
- `GET /api/research/artifacts/{artifact_id}`
- `POST /api/research/artifacts/{artifact_id}/export`
- `POST /api/research/search`
- `POST /api/research/source-snapshots`

The canonical approval and execution routes are `/api/approvals` and
`/api/executions/submit-approved`. The service may also keep compatibility
aliases under `/api/orders/approvals` and `/api/orders/executions/submit-approved`;
these aliases call the same service-layer functions and do not widen execution
permissions.

OpenAPI docs are staff-protected. REST is for operations, validation, inspection, and local control; it must not bypass MCP/service-layer execution checks.

## MCP Boundary

TradingCodex hosts MCP inside Django as a custom endpoint at `/mcp`, separate from the Ninja API.

MCP design follows the useful FastAPI-MCP pattern of preserving typed schemas, authentication/authorization, and a filtered tool surface, but implements it through the Django service layer instead of exposing raw REST endpoints. Tool definitions live in a Python MCP registry and are synced into `McpToolDefinition` for Admin visibility and enable/disable control.

Minimum MCP surface:

- `initialize`
- `tools/list`
- `tools/call`
- `resources/list`
- `prompts/list`

Minimum MCP tools:

- `validate_order_intent`
- `create_approval_receipt`
- `submit_approved_order`
- `get_positions`
- `get_portfolio_snapshot`
- `simulate_policy`
- `list_workflow_artifacts`
- `create_research_artifact`
- `get_research_artifact`
- `list_research_artifacts`
- `search_research_artifacts`
- `append_research_artifact_version`
- `export_research_artifact_md`
- `record_source_snapshot`
- `record_audit_event`

Every MCP tool definition includes description, input schema, category, risk level, role allowlist, approval requirement, and audit requirement. `tools/list` returns this metadata as tool annotations. `tools/call` records `McpToolCall` rows with principal, status, request/result hashes, error, and duration.

For Codex environments that require stdio MCP, `tcx mcp stdio` runs a bridge that calls the same service layer. The stdio bridge must never write non-MCP logs to stdout.

Generated Codex workspaces also render a project-scoped
`[mcp_servers.tradingcodex]` entry in `.codex/config.toml`. This follows the
OpenAI Codex MCP configuration shape: a stdio `command`, `args`, `enabled`,
`env`, `enabled_tools`, `default_tools_approval_mode`, `startup_timeout_sec`,
and `tool_timeout_sec`. Project-scoped Codex config applies only when the
generated workspace is trusted by Codex. The generated TradingCodex MCP command
uses `uvx --refresh --from <package-spec> python -m tradingcodex_cli mcp stdio`,
where the package spec is recorded during bootstrap so PyPI and GitHub-source
installs keep the same MCP source without stale source-cache reuse. The
TradingCodex MCP config sets
`TRADINGCODEX_MCP_AUTOSTART_SERVICE=1`,
so Codex MCP startup idempotently starts the local Django dashboard service at
`127.0.0.1:8000` while keeping MCP stdio stdout clean. The root `head-manager`
allowlist exposes research, audit,
portfolio/status, and policy simulation tools, but excludes approval creation
and execution submission. Role-scoped agent TOML files expose the narrower risky
tools only to their owner roles: `risk-manager` can create approval receipts,
and `execution-operator` can call the experimental submit/cancel execution
tools.

Local development defaults:

- localhost binding
- Origin/auth validation
- no live broker adapter
- paper/stub adapters only
- secrets excluded from API, MCP, audit, and prompt outputs

## CLI

The CLI entrypoint is `tcx`.

Top-level commands:

- `tcx init <workspace> [--overwrite]`
- `tcx doctor [--layer <name>]`
- `tcx subagents status|list|plan|skills|prompt|state`
- `tcx skills list [--all]|inspect|propose-add|propose-update|apply-proposal`
- `tcx research create|get|list|search|export`
- `tcx policy simulate`
- `tcx db status|path|migrate`
- `tcx mcp call <tool> [tool args]`
- `tcx mcp ledger [--tool <name>] [--principal <id>] [--status ok]`
- `tcx mcp stdio`
- `tcx service runserver` for CLI-only dashboard startup when Codex MCP
  autostart is not in use

Generated workspace wrapper:

- `./tcx doctor`
- `./tcx subagents status`
- `./tcx subagents prompt "<request>"`
- `./tcx validate order <path>`
- `./tcx approve <path>`
- `./tcx db status|path|migrate`
- `./tcx mcp call <tool>`
- `./tcx mcp ledger [--tool <name>]`
- `./tcx research create|get|list|search|export`

Default main-agent skill listing is user-facing, not exhaustive. It shows only direct user entrypoints: `orchestrate-workflow`, `head-manager-interview`, and `postmortem`. Internal head-manager harness skills remain enabled and installed so `head-manager` can use them for workflow mapping, quality gates, subagent management, and synthesis. Full inspection is available through `./tcx skills list --all` and role-specific `./tcx subagents skills <role>`.

Research artifact behavior:

- DB is canonical for markdown body, metadata, version, readiness label, source/as-of posture, and content hash.
- The central DB is shared across generated Codex projects; `workspace_context` records caller provenance.
- Markdown export files under `trading/research/*` and `trading/reports/*` are human-readable cache/export artifacts.
- MCP tools should read/write research through the service layer instead of scraping markdown files when DB access is available.
- Research quality focuses on source/as-of discipline, retrieved-at metadata, stale-data warnings, versioning, and invalidation rather than old-note recall.

## Workspace Generator

`tcx init` renders `workspace_templates/modules/*/files` into a Codex workspace.
After rendering, `init` sets the Django settings module, applies the central runtime schema,
and records workspace provenance in the central local Django DB. This makes a fresh workspace
ready for `./tcx doctor`, MCP ledger inspection, research-memory commands, and the
local web/Admin service without creating a workspace-local DB.

The target may be an empty directory or a git-initialized directory containing
only `.git` plus optional git metadata files. Source checkouts of this
repository are development projects, not generated TradingCodex workspaces.

Generated workspace contract:

- `AGENTS.md`
- `.codex/config.toml`
- `.codex/agents/*.toml`
- `.codex/hooks/tradingcodex_hook.py`
- `.agents/skills/*`
- `.tradingcodex/*`
- `trading/*`
- `./tcx` wrapper

Codex-native bootstrap verification:

- `./tcx doctor` checks the generated project MCP server shape and verifies
  that root, `risk-manager`, and `execution-operator` MCP allowlists match the
  role boundary.
- `./tcx mcp stdio` `tools/list` verifies the TradingCodex MCP bridge and tool
  annotations, including `experimental = true` on execution tools.
- Generated Codex MCP config starts the stdio MCP bridge through `uvx` and
  starts the local dashboard service together; direct `./tcx mcp stdio` remains
  service-free unless `TRADINGCODEX_MCP_AUTOSTART_SERVICE=1` is set.
- `codex exec -C <workspace> --skip-git-repo-check ...` can verify that Codex
  CLI loads the generated project context. The management command
  `codex mcp list/get` may show only user/global MCP servers, even when a
  session uses project-scoped MCP config after workspace trust.

Generated workspaces contain:

- one root `head-manager`
- nine fixed subagents
- fixed subagents configured for `model = "gpt-5.5"` and `model_reasoning_effort = "high"`
- twenty-one repo skills
- information-barrier policies
- order/approval schemas
- restricted-list policy
- stub and paper adapters
- audit directories
- central local SQLite service access through `~/.tradingcodex/state/tradingcodex.sqlite3`
- workspace provenance passed through `TRADINGCODEX_WORKSPACE_ROOT`
- Python hook scripts callable from Codex hook commands

## Investment Universe And Workflow Routing

TradingCodex does not treat public equity as the only investment universe. Public equity is the most developed initial sleeve and contributes the strongest workflow vocabulary:

- owner workflow routing rather than generic company research
- explicit invocation gates for specialized workflows
- source/as-of posture before market-sensitive claims
- hero/support artifact separation
- embedded support layers for source-of-truth, normalization, data cleaning, QC, and style adaptation
- PM/risk handoffs for sizing, hedges, and readiness
- credit-market boundary rules when the next action is a debt, loan, CDS, distressed, covenant, or recovery decision

TradingCodex generalizes those lessons across universes:

| Universe | Initial treatment |
| --- | --- |
| Public equity | full research, valuation, thesis, earnings, catalyst, sizing, risk, paper/stub execution path |
| ETF/index | instrument support, constituent diligence, benchmark-relative research, paper/stub execution only when supported by policy |
| Public crypto | read-only market-structure and risk support; no unsupported execution claims |
| Macro/rates/FX/commodities | macro transmission, liquidity, policy, cross-asset risk input; execution is blocked unless a supported adapter/policy exists |
| Options | instrument analysis, payoff/risk support, hedge context; no execution unless explicitly supported later |
| Credit signals | equity-risk context and warning signals; credit-instrument decisions route to a future credit workflow |

Unsupported or weakly sourced universes receive conservative readiness labels such as `research-only`, `screen-grade`, `not-decision-ready`, or `blocked`.

## Role Roster

The root coordinator is `head-manager`. The fixed subagent roster is:

- `fundamental-analyst`
- `technical-analyst`
- `news-analyst`
- `macro-analyst`
- `instrument-analyst`
- `valuation-analyst`
- `portfolio-manager`
- `risk-manager`
- `execution-operator`

Role skill assignments are managed as a product contract. Changes move through skill proposals and are inspectable in Admin and CLI. Subagents receive role-local context, not the full system background.

Execution role boundary:

- analysts cannot draft orders, approve, execute, read secrets, or call raw broker APIs
- `portfolio-manager` may create draft order intents but cannot approve or execute
- `risk-manager` may validate and approve but cannot draft or execute
- `execution-operator` may submit approved orders through TradingCodex MCP only

## Core Models

- `Principal`
- `Capability`
- `PolicyDecision`
- `RestrictedSymbol`
- `ResearchArtifact`
- `ResearchArtifactVersion`
- `WorkspaceContext`
- `WorkflowRun`
- `ArtifactRef`
- `SkillProposal`
- `RoleSkillAssignment`
- `OrderIntent`
- `ApprovalReceipt`
- `ExecutionResult`
- `PortfolioSnapshot`
- `Position`
- `CashBalance`
- `McpToolDefinition`
- `McpToolCall`
- `AuditEvent`
- `UniversePlugin`
- `AdapterDefinition`
- `SourceSnapshot`

## Safety Requirements

- Direct live broker requests are blocked.
- Direct broker API variants such as `broker.raw_api`, `broker_api.*`, and generic live execution actions are blocked by policy simulation and MCP execution paths.
- Generic execution-like actions such as `execute_order` are denied unless they enter the approved TradingCodex MCP execution lifecycle.
- Self-issued approvals are denied; approval receipt creation is restricted to `risk-manager` through service-layer and MCP role checks.
- Restricted symbol orders are blocked.
- Paper/stub orders require a valid order intent and approval receipt.
- Approved order submission uses a deterministic idempotency key; an existing `ExecutionResult` for the same approved order blocks repeat adapter submission.
- Django Admin cannot bypass approval or policy.
- Principal and Capability rows are executable policy inputs. MCP role allowlists are necessary but not sufficient when a DB capability is denied or the principal is inactive.
- Raw secrets never appear in API, MCP, audit response, generated prompt, or generated workspace docs.
- Research markdown stored in DB must preserve source/as-of posture, content hash, version, role/user provenance, and readiness label.
- Project provenance must be recorded as context, not used as the primary partition for investment state.
- Adapter boundaries are rechecked immediately before execution.
- Crypto, macro, options, credit-signal, and unsupported instrument requests route to research/risk support unless execution support is explicitly installed and allowed.
- “No order” and “no trading” language must not route a request into execution.
- Guardrail-verification wording such as “verify blocked order/approval/execution actions” must not itself route a research or portfolio-risk request into execution.
- Earnings, catalyst, filing, and valuation review requests for listed issuers route to thesis-review style research/valuation support, not directly to execution.

## Test Plan

Unit tests:

- policy decisions, restricted list, limits, capability checks
- order intent validation, approval validation, execution preconditions
- approved-order idempotency and duplicate execution blocking
- principal/capability checks before MCP handler dispatch and policy decisions
- universe routing and readiness labels
- adapter registry and disabled live adapter behavior
- audit append behavior and request/result hash generation
- DB-backed research artifact creation, versioning, search, source snapshot recording, and markdown export
- central DB path resolution through `TRADINGCODEX_HOME` and `TRADINGCODEX_DB_NAME`
- workspace provenance recording without workspace-local DB partitioning

API tests:

- Ninja endpoints return typed schemas and reject unauthorized calls
- Admin actions call service layer and create audit events
- Admin MCP registry, policy, skill, and adapter actions call service-layer helpers and create audit events
- `/mcp` handles JSON-RPC initialize, tools/list, tools/call
- `/mcp` handles JSON-RPC batch requests and returns role/risk tool metadata
- MCP research tools store and retrieve markdown from Django DB
- MCP tool calls create a DB ledger entry with request/result hashes
- generated `./tcx mcp ledger` can inspect the central DB tool-call ledger for local/staff verification
- stdio bridge returns valid MCP messages and writes no non-MCP stdout

Generator/smoke tests:

- `tcx init` creates the workspace contract
- two generated workspaces share research memory, paper portfolio state, and MCP ledger through the central DB
- generated workspace contains nine fixed subagents and twenty-one repo skills
- starter prompts keep negated execution requests out of execution routing
- starter prompts keep guardrail-verification wording out of execution routing and route earnings/catalyst/valuation requests to thesis review
- `doctor` passes for Codex config, information barriers, skills, policy, MCP, and hooks

Primary validation commands:

```bash
pytest
python manage.py check
python -m compileall tradingcodex_cli tradingcodex_service apps tests
```

## Current Defaults

- Central local SQLite database at `~/.tradingcodex/state/tradingcodex.sqlite3`.
- Workspace wrappers set `TRADINGCODEX_WORKSPACE_ROOT` for provenance only; they do not set a workspace-local DB by default.
- Research markdown and source snapshots are DB canonical; markdown files are exports/cache.
- Staff/local-only Admin and OpenAPI docs.
- Live broker adapters disabled and unimplemented.
- Paper and stub execution only.
- Django Ninja for REST/control APIs.
- Custom Django/ASGI endpoint for MCP, backed by a typed tool registry and DB-visible tool ledger.
- Python workspace generator and Python generated hooks.
- Documentation in `docs/` remains the source of truth for product direction, safety rules, role boundaries, and execution policy.
