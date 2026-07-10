# Interfaces And Surfaces

This document owns the behavior of TradingCodex product web, Django Admin,
Django Ninja API, stdio MCP, CLI, and generated workspace wrappers.

## Interface Rule

Every interface is a caller of the service layer. No interface may create a
parallel policy, order, approval, execution, portfolio, research, or audit path.
For the `0.2.0` release contract, public routes and imports should use the
canonical `tradingcodex_service/application/` service modules and
`tradingcodex_cli/commands/` command modules directly rather than preserving
pre-release aliases.

| Surface | Primary role | Must not do |
| --- | --- | --- |
| Product web | Skill-first analysis workbench, bounded Codex-run supervision, artifact/source review, and authenticated customization/operational flows | Directly select or spawn roles, accept arbitrary commands, expose raw reasoning/tool payloads, or bypass policy, approval, and execution gates |
| Django Admin | Local/staff operations console | Bypass service-layer policy or audit |
| Django Ninja | Typed authenticated local/staff REST and operator-managed remote control API | Mirror every MCP tool automatically or bypass execution checks |
| MCP | Agent approved-action boundary | Expose raw REST endpoints or raw broker APIs |
| CLI | Local operator and generated wrapper interface | Fork durable behavior away from services |

## Product Web App

TradingCodex provides a skill-first React workbench at `/`, not a table-first
Admin replacement. React 19, TypeScript, and Vite 8 source lives under
`frontend/`; the deterministic build is committed under
`tradingcodex_service/static/tradingcodex_web/` and served by Django and
WhiteNoise. Node 22 is a maintainer build dependency only. Installed packages
and generated workspaces do not run a Node server or npm.

The SPA has four primary sections:

- **Work** starts analysis from natural language or a safe built-in investment
  skill and shows live agent, tool, source, artifact, waiting, blocked, failed,
  and completed state plus final forecasts and follow-up.
- **Skills** discovers built-in skills and supports existing authenticated
  optional-skill and `strategy-*` management APIs. Skill selection supplies a
  procedure/input guide; it never grants identity, tools, approval, or execution
  authority.
- **Library** browses workspace research, reports, sources, forecasts, and other
  accepted artifacts with sanitized previews and source/as-of posture.
- **System** holds workspace, profile, broker/data-source, policy, audit, and
  build diagnostics that should not dominate the analysis workflow.

SPA navigation uses hash sections so Django needs only a GET shell at `/`.
`/admin/` remains Django Admin, `/api/` remains Django Ninja, and static paths
remain Django/WhiteNoise assets. Legacy product routes may redirect to the SPA
during cutover, but they must not retain separate business behavior after their
templates are removed.

The product web app is work-first and evidence-readable. Runs show current work
and blockers before diagnostics; skill, research, source, and strategy views show
a selectable list before document detail. Verbose paths, projection hashes,
manifest internals, proposal files, and validation internals belong in System or
progressively disclosed diagnostics.

Markdown preview rendering uses the shared maintained parser/sanitizer service.
The client must not inject unsanitized workspace HTML.

Workspace selection is web-session local:

- `GET <web route>?workspace=<workspace_id>` stores the selected
  `WorkspaceContext` in the current browser session.
- The sidebar selector lists up to 20 recently seen `WorkspaceContext` rows.
- Web rendering uses the selected workspace path when it is valid; invalid or
  missing ids fall back to `TRADINGCODEX_WORKSPACE_ROOT`.
- Recent activity and role-inspector activity are filtered by the selected
  workspace identity so MCP calls, audit events, and workflow runs from another
  Codex workspace do not appear as current-workspace evidence.
- Opening a workspace requires an existing `.tradingcodex/workspace.json`
  manifest. Creating a new workspace is a separate POST action and uses the
  normal non-forced bootstrap path, so non-empty directory protection is not
  bypassed from the web surface.
- This selector does not change CLI, MCP, API, or process-level environment
  behavior.

### Workbench Run Model

A Work request launches the same generated `head-manager` that a user would run
from the attached workspace. Django invokes `codex exec` in JSONL mode and
supervises the process; it does not choose the role team or directly spawn fixed
subagents. Project instructions, skills, hooks, role TOML, MCP allowlists, and
service gates remain authoritative.

Preview, initial, and follow-up requests use the same skill-expanded prompt and
are analysis-only. The API rejects order
drafting, approval, execution, cancellation, broker mutation, and secret
requests before process launch. A selected built-in skill is prompt/procedure
context only and cannot widen role or tool authority.

The runner uses a fixed argument vector with `shell=False`, a vetted attached
workspace as cwd, `workspace-write`, `approval_policy="never"`, disabled sandbox
command networking, ignored user config, forced hooks, and disabled unified-exec
and browser/computer/app/image action features. It verifies full generated
project/role config, prompts, core skills, launchers, hooks, and the canonical
TradingCodex MCP server, removes secret-like environment variables, and permits
only one active process per run. PreToolUse admits only the explicit analysis
MCP set plus artifact quality checks; structured `record_workflow_plan` and
`record_artifact_supervisor_loop` calls record the plan and gated artifact
transitions without arbitrary shell or file writes.
Artifact creation binds producer identity to the authenticated role, supervisor
acceptance requires the recorded stage gate to be ready, and terminal state must
match append-only event replay.
Follow-up resumes the stored Codex thread rather than creating an unrelated
workflow. This first slice has no web cancellation or timeout.

The workbench receives normalized, redacted, allowlisted events for agent, tool,
source, artifact, and terminal state. It never receives or stores raw reasoning,
tool inputs/outputs, stderr, or raw final output. Reader-facing final analysis
comes only from a hash-bound head-manager synthesis after a validated recorded
plan reaches synthesis readiness, and must show forecast horizon,
assumptions, probability or range, key variables, uncertainty, and invalidation
conditions when a forecast is present.

### Product Web Boundary

- `GET /api/workbench/` and workbench skill, artifact, and run detail are
  read-only local/staff surfaces.
- `POST /api/workbench/preview/` computes the same skill-expanded scope used by
  start without persisting an intake or launching Codex.
- Only preview, `POST /api/workbench/runs/`, and
  `POST /api/workbench/runs/{run_id}/follow-up/` have a narrow local exception:
  under the `local` service profile, a loopback request with valid CSRF may use
  them without a staff session or API key. Under `remote`, staff/API-key
  authentication is always required. Every other mutation keeps its existing
  authentication rule.
- The exception authorizes only scope preview and bounded analysis process
  start/resume. It is not
  generic loopback mutation authority and exposes no order, approval, execution,
  cancellation, broker, policy, or secret action.
- Optional-skill, strategy, additional-instruction, broker/data-source, profile,
  policy, order, and build mutations continue through their existing
  authenticated APIs and shared application services.
- Optional skills and `strategy-*` rules may be created, updated, activated,
  archived, deleted, inspected, selected for Work, and projected from Skills,
  but cannot mutate
  protected built-ins, role identity, permission profiles, MCP allowlists,
  policy, or execution authority.
- External MCP discovery and permission review must not expose raw external
  tools directly to Codex or turn user consent into order/execution approval.
- Execution-sensitive actions remain behind TradingCodex role, MCP, policy,
  approval, duplicate-request, connection, and audit checks regardless of
  whether analysis began in Codex or the workbench.
- Every workbench section displays a persistent warning when the explicitly
  selected active profile is shared across workspaces.

## Django Admin

Django Admin uses Django's default admin UI and default model registration. It
is a local/staff DB inspection and emergency edit surface, not a custom
TradingCodex operations console. It exposes:

- policy, restricted symbols, capability allowlists, limits
- MCP tool registry and tool call ledger
- workflow runs, artifact refs, readiness labels
- order tickets, approval receipts, execution results
- portfolio snapshots, positions, cash balances
- adapter definitions
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

Django Ninja provides authenticated local/staff and explicitly hardened remote
typed control APIs. Anonymous access is limited to read-only health/product
state; mutations use the bound API principal/key or staff session except for the
three CSRF-protected, loopback-local, analysis-only workbench POSTs documented
above:

- `GET /api/health`
- `GET /api/health/live`
- `GET /api/health/ready`
- `GET /api/workbench/` returns the selected-workspace snapshot for Work,
  Skills, Library, and System
- `GET /api/workbench/skills/{skill_id}`
- `GET /api/workbench/artifacts/{artifact_id}`
- `GET /api/workbench/runs/{run_id}`
- `POST /api/workbench/preview/` returns the exact skill-expanded scope used by
  start without persisting intake or launching Codex
- `POST /api/workbench/runs/` starts one bounded analysis-only Codex run
- `POST /api/workbench/runs/{run_id}/follow-up/` resumes its stored Codex thread
- `GET /api/harness/status`
- `GET /api/harness/components`
- `GET /api/harness/components/{component_id}`
- `GET /api/harness/optional-skills`
- `GET|POST /api/harness/strategies`
- `GET|PATCH|DELETE /api/harness/strategies/{name}`
- `POST /api/harness/strategies/{name}/activate|archive`
- `GET /api/harness/subagents/prompt` returns the starter prompt plus
  `intake_summary` for idea translation, plain-language workflow explanation,
  blocked-action reasons, next allowed actions, stage exit criteria, and direct
  profile questions
- `POST /api/harness/subagents/loop` returns closed Artifact Supervisor Loop
  planner actions for artifact paths and can optionally record file-native
  pending tasks/escalation proposals without spawning agents
- `GET /api/subagents`
- `GET /api/subagents/{role}/skills`
- `GET|POST /api/subagents/{role}/optional-skills`
- `GET|PATCH|DELETE /api/subagents/{role}/optional-skills/{name}`
- `POST /api/subagents/{role}/optional-skills/{name}/activate|archive`
- `GET /api/workflows/{id}`
- `POST /api/workflows/intake` records compact workflow intake hints without raw prompt storage
- `POST /api/workflows/{id}/validate` validates an agent-authored staged workflow plan, or returns a deterministic preview for compatibility
- `POST /api/workflows/record` records a validated staged workflow plan and initializes loop state
- `POST /api/policy/simulate`
- `GET|POST /api/orders/tickets`; list responses are scoped to the active
  profile (`portfolio_id`, `account_id`, `strategy_id`)
- `GET /api/orders/tickets/{ticket_id}`
- `POST /api/orders/tickets/{ticket_id}/checks`
- `POST /api/orders/tickets/{ticket_id}/approval-request` local control only; Codex risk-manager workflows should prefer MCP `request_order_approval`
- `POST /api/approvals`
- `POST /api/executions/submit-approved`
- `GET /api/audit/events` returns recent audit events for the API process
  workspace identity only
- `GET /api/portfolio/snapshot`
- `GET /api/portfolio/reconciliations`
- `GET /api/brokers`
- `GET /api/brokers/{broker_id}`
- `POST /api/brokers/{broker_id}/sync`
- `POST /api/research/artifacts`
- `GET /api/research/artifacts`
- `GET /api/research/artifacts/{artifact_id}`
- `POST /api/research/artifacts/{artifact_id}/export`
- `POST /api/research/search`
- `POST /api/research/source-snapshots`
- `POST|GET /api/research/specs`
- `GET /api/research/specs/{spec_id}`
- `POST /api/research/replay-manifests`
- `POST /api/research/experiments`
- `POST /api/research/causal-equity-analyses`
- `POST /api/research/judgment-priors`
- `POST /api/research/judgment-reviews`
- `POST /api/research/index/rebuild`
- `POST|GET /api/research/forecasts`
- `GET /api/research/forecasts/calibration`
- `GET /api/research/forecasts/{forecast_id}`
- `POST /api/research/forecasts/{forecast_id}/revisions`
- `POST /api/research/forecasts/{forecast_id}/resolution`
- `POST /api/research/forecasts/{forecast_id}/score`
- `POST /api/evaluations/corpora`
- `POST /api/evaluations/runs`
- `POST /api/evaluations/blind-reviews`
- `POST /api/evaluations/comparisons`

ResearchSpec, replay, experiment, causal-analysis, judgment, forecast, and
calibration routes are evidence-only. Causal equity analysis is bound to
`valuation-analyst`; blind priors/reviews and forecast resolution are bound to
`judgment-reviewer`. These routes cannot draft, approve, or execute orders.

`POST /api/research/specs` accepts a bundled `method_profile`. Common evidence
fields apply to every profile; `quant_signal_v1` adds preregistered signal,
trial, cost, capacity, and validation fields, while
`listed_equity_fcff_dcf_v1` adds instrument, driver, base-rate, scenario,
reconciliation, and independent-review plans. Evaluation corpus creation uses
`core_investment_v1` by default and may accept a bounded corpus-defined profile
with explicit required tags and metric dimensions. Evaluation runs bind an
`extension_profile_hash` so pristine and customized arms cannot be conflated.
Those hashes and deterministic check outcomes are currently caller-attested;
comparisons record unverified provenance and force `hold` until a trusted
evaluation runner supplies a verifiable runtime binding.

The canonical approval and execution routes are `/api/approvals` and
`/api/executions/submit-approved`. Approval and execution routes do not have
`/api/orders/*` aliases in the `0.2.0` contract.

OpenAPI docs are staff-protected. REST is for operations, validation,
inspection, and local control. Codex-native workflows should prefer
role-scoped MCP tools so tool annotations, role allowlists, call ledgers, and
workspace provenance stay in the same approved action boundary.

## MCP Boundary

TradingCodex exposes the official Codex MCP path through project-scoped stdio:
`tcx mcp stdio`. MCP is intentionally selected service-layer use cases, not an
automatic REST mirror.

Minimum MCP protocol surface:

- `initialize`
- `tools/list`
- `tools/call`
- `resources/list`
- `prompts/list`

Minimum MCP tools:

- `get_tradingcodex_status`
- `record_workflow_plan`
- `record_artifact_supervisor_loop`
- `list_broker_connections`
- `get_broker_connection_status`
- `sync_broker_account`
- `list_reconciliation_runs`
- `create_order_ticket`
- `run_order_checks`
- `request_order_approval`
- `get_order_ticket`
- `list_order_tickets`
- `submit_approved_order`
- `discard_draft_order`
- `cancel_submitted_order`
- `cancel_approved_order` (compatibility alias for submitted-order cancellation)
- `refresh_broker_order_status`
- `get_order_status`
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
- `create_research_spec`
- `get_research_spec`
- `list_research_specs`
- `create_replay_manifest`
- `record_experiment_run`
- `rebuild_research_index`
- `create_causal_equity_analysis`
- `record_blind_judgment_prior`
- `complete_judgment_review`
- `issue_forecast`
- `revise_forecast`
- `resolve_forecast`
- `score_forecast`
- `get_forecast`
- `list_forecasts`
- `get_forecast_calibration_report`
- `create_evaluation_corpus`
- `record_evaluation_run`
- `record_blind_human_review`
- `compare_evaluation_runs`
- `list_external_mcp_connections`
- `register_external_mcp_connection`
- `check_external_mcp_connection`
- `discover_external_mcp_connection`
- `review_external_mcp_tool`
- `record_audit_event`

Every MCP tool definition includes stable name, description, input schema,
category, risk level, role allowlist, approval requirement, audit requirement,
and standard MCP hints for read-only, destructive, idempotent, and open-world
behavior. `tools/list` returns this metadata as tool annotations.
Research artifact write tools accept the handoff metadata validated by
`tcx quality-check --strict`.
`tools/call` records `McpToolCall` rows with principal, status, request/result
hashes, errors, and duration, except research tools and
evaluation tools plus `list_workflow_artifacts`, which are excluded so
research/evaluation payloads remain only in workspace files.

`tcx mcp stdio` calls the same service layer as CLI, API, and web surfaces. The
stdio bridge must never write non-MCP logs to stdout.

Every stdio instance requires a transport principal. Generated root and role
config bind `TRADINGCODEX_MCP_PRINCIPAL`, and a caller-supplied payload
principal must match it. This prevents one projected role server from invoking
a tool as another role.

The project MCP server is named `tradingcodex` and carries the current
workspace provenance. Optional global safe MCP is named `tradingcodex-home`,
limits the server-side tool surface to read-only/status/search tools, and must
not expose approval, execution, cancellation, policy mutation, secret, broker
sync, broker mapping mutation, or order-ticket mutation tools.

### External MCP Gate

External MCP servers can be registered through product web as managed
connections. Product web can run the same check/discover lifecycle used by CLI
and MCP tools. TradingCodex stores connection metadata, imported `tools/list`,
`resources/list`, and `prompts/list` records, schema hashes, risk categories,
canonical capability mappings, role scopes, and proxy decisions in the central
DB.

External MCP tools are not automatically exposed to Codex. Discovery imports
default to review-required policy. Unknown, secret, policy/admin, and direct
execution tools are disabled until classified; execution-like external tools
must map to a TradingCodex service connection path instead of direct raw proxy.
Broker/account private-read tools such as balances, positions, orders, fills,
and buying power must be managed by External MCP Gate with role scope and audit.
Public market data, news, and filings MCP may remain lightweight, but when used
for order, risk, approval, or portfolio decisions they must be captured through
source snapshots or research artifacts.

## Role-Specific MCP Exposure

The root `head-manager` allowlist exposes research, audit, portfolio/status,
and policy simulation tools, but excludes approval creation and execution
submission. Role-scoped agent TOML files expose narrower risky tools only to
their owner roles:

- `risk-manager` can create approval receipts.
- `execution-operator` can call experimental submit/cancel execution tools.
- forecast authors may issue/revise only as themselves; `judgment-reviewer`
  independently resolves forecasts and cannot resolve its own forecast
- `valuation-analyst` owns deterministic causal equity analysis, while
  `judgment-reviewer` owns the blind prior and second-pass challenge review
- `head-manager` can freeze evaluation corpora, record control/candidate runs,
  and compare them; `judgment-reviewer` records model-identity-hidden human
  reviews. Evaluation authority remains research-only.

MCP registry role allowlists are a second boundary after `.codex/agents/*.toml`.
MCP tool execution also checks active requester identities (`Principal`) and
matching action permissions (`Capability`).

## CLI

The CLI entrypoint is `tcx`.

Top-level commands:

- `tcx attach [workspace] [--overwrite]`
- `tcx init <workspace> [--overwrite]`
- `tcx update [workspace] [--no-doctor]`
- `tcx doctor [--layer <name>]`
- `tcx workspace status|list`
- `tcx profile status|list|create|select|update`
- `tcx subagents status|list|inspect|diff|project|plan|loop|skills|prompt|state`
- `tcx skills list [--all]|inspect|propose-add|propose-update|apply-proposal`
- `tcx research create|append|get|list|search|export|run-card|validation-card`
- `tcx research spec create|get|list`
- `tcx research replay create`
- `tcx research experiment record`
- `tcx research causal-analysis|judgment-prior|judgment-review`
- `tcx research index rebuild`
- `tcx forecast issue|revise|resolve|score ... --principal <role>` for writes;
  `tcx forecast get|list|calibration` for reads
- `tcx evaluation corpus|run|blind-review|compare`
- `tcx policy simulate`
- `tcx db status|path|migrate`
- `tcx build status|codex-mcp|permission`
- `tcx mcp call <tool> [tool args]`
- `tcx mcp ledger [--tool <name>] [--principal <id>] [--status ok]`
- `tcx mcp install-global --safe`
- `tcx mcp stdio`
- `tcx service runserver`
- `tcx service ensure`
- `tcx service stop`
- `tcx service status [--json]`

Generated workspace wrapper commands:

- `./tcx doctor`
- `./tcx update [--no-doctor] [--skip-refresh]`
- `./tcx update status [--json]`
- `./tcx mode status`
- `./tcx mode set build --reason "<reason>"`
- `./tcx build status|codex-mcp|permission`
- `./tcx mode set operate`
- `./tcx connectors status`
- `./tcx connectors providers`
- `./tcx connectors connect <broker> [--provider <provider-id>] [--credential-ref <ref>] [--mode read-only|validation|live-request]`
- `./tcx connectors scaffold <broker-id> [--provider <provider-id>] [--credential-ref <ref>] [--environment <env>]`
- `./tcx connectors register --provider <provider-id> --broker-id <id> --credential-ref <ref> [--environment <env>]`
- `./tcx connectors validate <broker-id>`
- `./tcx workspace status|list`
- `./tcx profile status|list|create|select|update`
- `./tcx subagents status`
- `./tcx subagents prompt [--json|--explain] "<request>"`
- `./tcx subagents loop --request "<request>" --artifact <path> [--record]`
- `./tcx skills optional list|inspect|create|update|activate|archive|delete`

Connector setup is provider-first. Core ships the `paper` provider only; a
named broker request routes to `$tcx-build` to install or develop a reviewed
provider, then registration stores only provider metadata and `credential_ref`.
- `./tcx strategies list|inspect|create|update|activate|archive|delete`
- `./tcx validate order <path>`
- `./tcx approve <path>`
- `./tcx db status|path|migrate`
- `tcx home status|check [--json]` (workspace-independent, no automatic migration)
- `./tcx mcp call <tool>`
- `./tcx mcp ledger [--tool <name>]`
- `./tcx research create|append|get|list|search|export|run-card|validation-card|spec|replay|experiment|causal-analysis|judgment-prior|judgment-review|index`
- `./tcx forecast issue|revise|resolve|score ... --principal <role>` and
  `./tcx forecast get|list|calibration`
- `./tcx evaluation corpus|run|blind-review|compare`

Default main-agent skill listing is user-facing, not exhaustive. It shows only
direct user entrypoints: `plan-workflow`, `tcx-workflow`, `automate-workflow`,
`tcx-server`, `tcx-build`, `strategy-creator`, `postmortem`, and active `strategy-*` skills. Full
inspection is available through
`./tcx skills list --all` and role-specific `./tcx subagents skills <role>`.

Optional-skill and strategy CRUD CLI commands call the same shared application
service used by the authenticated workbench/API and mainagent guidance.
Additional instruction edits are web-first and file-native; they are stored
under `.tradingcodex/agent-instructions/` and reflected in generated projection
indexes.
