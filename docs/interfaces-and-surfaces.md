# Interfaces And Surfaces

This document owns the behavior of TradingCodex product web, Django Admin,
Django Ninja API, Django-hosted MCP, CLI, and generated workspace wrappers.

## Interface Rule

Every interface is a caller of the service layer. No interface may create a
parallel policy, order, approval, execution, portfolio, research, or audit path.
Public import and route facades may stay stable for compatibility, but their
durable behavior should delegate to `tradingcodex_service/application/` service
modules and `tradingcodex_cli/commands/` command modules.

| Surface | Primary role | Must not do |
| --- | --- | --- |
| Product web | Visual review and starter prompt preparation | Spawn agents, generate investment analysis, approve orders, execute orders, mutate execution-sensitive state |
| Django Admin | Local/staff operations console | Bypass service-layer policy or audit |
| Django Ninja | Typed local/staff REST and control API | Mirror every MCP tool automatically or bypass execution checks |
| MCP | Agent/tool execution boundary | Expose raw REST endpoints or raw broker APIs |
| CLI | Local operator and generated wrapper interface | Fork durable behavior away from services |

## Product Web App

TradingCodex provides a user-facing web app at `/`. It is an agents-first
review surface, not a table-first Admin replacement. The primary product web
workflow is selecting an agent, inspecting required and optional skills, and
previewing Codex-readable markdown.
For the root `head-manager`, active `strategy-*` skills are also visible as
strategy entries because they are workspace skills, but product web remains a
read-only preview surface.

Routes:

- `/` redirects to `/harness/agents/`
- `/harness/` redirects to `/harness/agents/`
- `/harness/agents/` head-manager and subagent skill browser with markdown preview
- `/harness/agents/<role>/skills/` compatibility route for the same agent skill browser
- `/research/` workspace-native research markdown browser with sanitized markdown preview

Direct diagnostic routes may remain for local operators, but they are not part
of the primary product navigation:

- `/portfolio/` central paper portfolio state
- `/orders/` order, approval, and execution lifecycle review
- `/policy/` restricted list and policy decision review
- `/activity/` MCP call ledger, audit events, and workflow activity
- `/workflow/starter-prompt/` Codex starter prompt generator

The product web app uses Django templates, local static HTMX, and local static
Alpine. There is no Node, bundler, React, or frontend build step in the
baseline. Its visual language follows a compact dark dashboard style inspired
by shadcn `new-york` components, implemented with vanilla CSS over Django
templates rather than React or Tailwind.

The product web app is content-first. Agent and research pages should show the
selectable list first, then a sanitized markdown preview. Verbose paths,
projection hashes, manifest internals, proposal file details, and validation
internals should live in collapsed diagnostics sections unless the route is
explicitly a diagnostic view.

Markdown preview rendering uses a maintained parser/sanitizer library pair.
Do not hand-roll markdown parsing in templates.

Workspace selection is web-session local:

- `GET <web route>?workspace=<workspace_id>` stores the selected
  `WorkspaceContext` in the current browser session.
- The sidebar selector lists up to 20 recently seen `WorkspaceContext` rows.
- Web rendering uses the selected workspace path when it is valid; invalid or
  missing ids fall back to `TRADINGCODEX_WORKSPACE_ROOT`.
- This selector does not change CLI, MCP, API, or process-level environment
  behavior.

### Visual Harness Canvas

The visual harness canvas is an optional diagnostic surface rather than the
primary web entrypoint. When present, it is server-rendered SVG/HTML and shows:

- center node: `head-manager`
- surrounding nodes: the nine fixed subagents
- edge groups: dispatch, research handoff, portfolio/risk gate, approval gate, execution gate
- edge contracts: what the source role must hand off, what the target role may consume, and the quality state expected before moving downstream
- role inspector: owned skills, no-overlap handoff contract, allowed MCP tools, forbidden actions, latest artifacts, latest activity
- MCP execution boundary: principal, policy, schema, approval, adapter, and audit checks

### Product Web Boundary

- The product web app does not spawn Codex subagents.
- The product web app does not generate investment analysis.
- The product web app does not approve or execute orders in v1.
- The product web app can create, update, activate, archive, delete, and project
  optional subagent skills and `strategy-*` skills through the shared
  application service.
- The product web app cannot mutate core/project-scope mainagent skills,
  fixed subagent core skills, permission profiles, MCP allowlists, policy, or
  execution authority.
- The product web app can generate starter prompts for the user to run in Codex.
- Execution-sensitive actions remain behind TradingCodex MCP and service-layer policy.

## Django Admin

Django Admin uses Django's default admin UI and default model registration. It
is a local/staff DB inspection and emergency edit surface, not a custom
TradingCodex operations console. It exposes:

- policy, restricted symbols, capability allowlists, limits
- MCP tool registry and tool call ledger
- workflow runs, artifact refs, readiness labels
- order intents, approval receipts, execution results
- portfolio snapshots, positions, cash balances
- adapter definitions and universe plugins
- audit logs
- workspace provenance

TradingCodex does not add custom Admin dashboards, custom Admin templates,
custom Admin CSS, custom Admin actions, or service-layer shortcut buttons.
Risky changes use product web, CLI, API, or MCP service-layer flows such as:

```text
proposal -> validation -> approval -> apply -> audit
```

Agent, skill, strategy, research artifacts, and source snapshots
are intentionally file-native rather than Admin DB surfaces. Optional skill
CRUD, strategy skill creation, and research handoff edits happen over workspace
files; product web shows workspace research files.

## Django Ninja API

Django Ninja provides local/staff typed control APIs:

- `GET /api/health`
- `GET /api/harness/status`
- `GET /api/harness/components`
- `GET /api/harness/components/{component_id}`
- `GET /api/harness/optional-skills`
- `GET|POST /api/harness/strategies`
- `GET|PATCH|DELETE /api/harness/strategies/{strategy_id}`
- `POST /api/harness/strategies/{strategy_id}/activate|archive`
- `GET /api/subagents`
- `GET /api/subagents/{role}/skills`
- `GET|POST /api/subagents/{role}/optional-skills`
- `GET|PATCH|DELETE /api/subagents/{role}/optional-skills/{skill_id}`
- `POST /api/subagents/{role}/optional-skills/{skill_id}/activate|archive`
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
`/api/executions/submit-approved`. Compatibility aliases may exist under
`/api/orders/approvals` and `/api/orders/executions/submit-approved`; aliases
must call the same service functions and must not widen permissions.

OpenAPI docs are staff-protected. REST is for operations, validation,
inspection, and local control.

## MCP Boundary

TradingCodex hosts MCP inside Django as a custom endpoint at `/mcp`, separate
from the Ninja API. MCP is intentionally selected service-layer use cases, not
an automatic REST mirror.

Minimum MCP protocol surface:

- `initialize`
- `tools/list`
- `tools/call`
- `resources/list`
- `prompts/list`

Minimum MCP tools:

- `get_tradingcodex_status`
- `validate_order_intent`
- `create_approval_receipt`
- `submit_approved_order`
- `cancel_approved_order`
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

Every MCP tool definition includes stable name, description, input schema,
category, risk level, role allowlist, approval requirement, and audit
requirement. `tools/list` returns this metadata as tool annotations.
`tools/call` records `McpToolCall` rows with principal, status, request/result
hashes, errors, and duration, except research tools and
`list_workflow_artifacts`, which are excluded so research payloads remain only
in workspace files.

For Codex environments that require stdio MCP, `tcx mcp stdio` runs a bridge
that calls the same service layer. The stdio bridge must never write non-MCP
logs to stdout.

The project MCP server is named `tradingcodex` and carries the current
workspace provenance. Optional global safe MCP is named `tradingcodex-home`,
limits the server-side tool surface to read-only/status/search tools, and must
not expose approval, execution, cancellation, policy mutation, secret, or broker
tools.

## Role-Specific MCP Exposure

The root `head-manager` allowlist exposes research, audit, portfolio/status,
and policy simulation tools, but excludes approval creation and execution
submission. Role-scoped agent TOML files expose narrower risky tools only to
their owner roles:

- `risk-manager` can create approval receipts.
- `execution-operator` can call experimental submit/cancel execution tools.

MCP registry role allowlists are a second boundary after `.codex/agents/*.toml`.
MCP tool execution also checks active `Principal` rows and matching
`Capability` rows.

## CLI

The CLI entrypoint is `tcx`.

Top-level commands:

- `tcx attach [workspace] [--overwrite]`
- `tcx init <workspace> [--overwrite]`
- `tcx doctor [--layer <name>]`
- `tcx workspace status|list`
- `tcx profile status|list|create|select`
- `tcx subagents status|list|inspect|diff|project|plan|skills|prompt|state`
- `tcx skills list [--all]|inspect|propose-add|propose-update|apply-proposal`
- `tcx research create|append|get|list|search|export`
- `tcx policy simulate`
- `tcx db status|path|migrate`
- `tcx mcp call <tool> [tool args]`
- `tcx mcp ledger [--tool <name>] [--principal <id>] [--status ok]`
- `tcx mcp install-global --safe`
- `tcx mcp stdio`
- `tcx service runserver`

Generated workspace wrapper commands:

- `./tcx doctor`
- `./tcx workspace status|list`
- `./tcx profile status|list|create|select`
- `./tcx subagents status`
- `./tcx subagents prompt "<request>"`
- `./tcx skills optional list|inspect|create|update|activate|archive|delete`
- `./tcx strategies list|inspect|create|update|activate|archive|delete`
- `./tcx validate order <path>`
- `./tcx approve <path>`
- `./tcx db status|path|migrate`
- `./tcx mcp call <tool>`
- `./tcx mcp ledger [--tool <name>]`
- `./tcx research create|append|get|list|search|export`

Default main-agent skill listing is user-facing, not exhaustive. It shows only
direct user entrypoints: `orchestrate-workflow`,
`strategy-creator`, `postmortem`, and active
`strategy-*` skills. Full inspection is available
through `./tcx skills list --all` and role-specific
`./tcx subagents skills <role>`.

Optional-skill and strategy CRUD CLI commands call the same shared application
service used by Django web/API and mainagent guidance.
