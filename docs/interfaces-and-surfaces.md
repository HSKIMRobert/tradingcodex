# Interfaces And Surfaces

This document owns the behavior of TradingCodex product web, Django Admin,
Django Ninja API, stdio MCP, CLI, and generated workspace wrappers.

## Interface Rule

Every interface is a caller of the service layer. No interface may create a
parallel policy, order, approval, execution, portfolio, research, or audit path.
The v1 public routes and imports use the canonical
`tradingcodex_service/application/` services and
`tradingcodex_cli/commands/` modules directly.

| Surface | Primary role | Must not do |
| --- | --- | --- |
| Product web | Skill-first analysis workbench, bounded Codex-run supervision, artifact/source review, and authenticated customization/operational flows | Directly select or spawn roles, accept arbitrary commands, expose raw reasoning/tool payloads, or bypass policy, approval, and execution gates |
| Django Admin | Local/staff operations console | Bypass service-layer policy or audit |
| Django Ninja | Typed authenticated local/staff REST and operator-managed remote control API | Mirror every MCP tool automatically or bypass execution checks |
| MCP | Agent research, order-preparation, approval, status, one proof-protected current-turn order effect, and proof-protected Build services | Expose raw submit/cancel/refresh mutations, accept protected calls without current hook proof, mirror raw REST endpoints, or proxy raw broker APIs |
| Root native action hook | Exact immediate submit/cancel plus exact-first-line `$tcx-order-allow` and `$tcx-build` current-turn admission and proof injection | Accept free-form intent, run from Workbench/subagents, elevate the Codex sandbox, or bypass service gates |
| CLI | Local operator and generated wrapper interface | Fork durable behavior away from services |

## Product Web App

TradingCodex provides a skill-first React workbench at `/`, not a table-first
Admin replacement. React 19, TypeScript, and Vite 8 source lives under
`frontend/`; the deterministic build is committed under
`tradingcodex_service/static/tradingcodex_web/` and served by Django and
WhiteNoise. Node 22 is a maintainer build dependency only. Installed packages
and generated workspaces do not run a Node server or npm.

The SPA keeps four stable hash sections, with three primary work surfaces and
one lower-emphasis settings surface:

- **Work** has two exclusive modes: compose and scope-review a new analysis, or
  read one selected run. A completed synthesis appears before supporting
  artifacts and collapsed technical activity. Recent analyses appear only in
  Work rather than consuming every product surface.
- **Approaches** (`#/skills`) discovers built-in skills and supports existing authenticated
  optional-skill and `strategy-*` management APIs. Skill selection supplies a
  procedure/input guide; it never grants identity, tools, approval, or execution
  authority.
- **Research** (`#/library`) browses workspace research, reports, sources, forecasts, and other
  accepted artifacts with sanitized previews and source/as-of posture.
- **Settings** (`#/system`) holds workspace, internal paper-account scope, broker/data-source,
  policy, audit, and build diagnostics that should not dominate the analysis
  workflow.

Decision Memory does not add a fifth top-level section. Users start retrieval,
historical replay, postmortem review, and lesson validation as a skill-shaped
Work request; Library exposes the resulting decisions, forecasts, reviews, and
lessons. Investor-context setup is an explicit workspace skill operation rather
than a selectable Profile screen. Add a dedicated Memory surface only after
measured usage shows that Work, Approaches, and Research cannot support the task.

SPA navigation uses hash sections so Django needs only a GET shell at `/`.
`/admin/` remains Django Admin, `/api/` remains Django Ninja, and static paths
remain Django/WhiteNoise assets. Non-root product paths return `404`; browser
navigation stays under the root hash routes.

The product web app is work-first and evidence-readable. It never renders a new
composer above a selected historical result. Active runs show a truthful,
event-derived research phase without a fake DAG, stage percentage, or predefined
team. Completed runs show the verified reader synthesis first; agents, allowlisted
activity, ids, and provenance stay in a closed disclosure. Approaches and Research
use list/detail navigation, with a single-view list-to-reader transition at narrow
widths. Verbose paths, projection hashes, manifest internals, proposal files, and
validation internals belong in Settings or progressively disclosed diagnostics.

Markdown preview rendering uses the shared maintained parser/sanitizer service.
The client must not inject unsanitized workspace HTML.

Workspace selection is web-session local:

- `GET <web route>?workspace=<workspace_id>` stores the selected
  `WorkspaceContext` in the current browser session.
- The Settings selector lists up to 20 recently seen `WorkspaceContext` rows.
- Web and API rendering use the selected workspace path only after its current
  v1 manifest and registered path validate. An explicitly unknown, unavailable,
  or stale selection returns an error and never falls back to another workspace.
  A request with no selection uses `TRADINGCODEX_WORKSPACE_ROOT`.
- Recent activity and role-inspector activity are filtered by the selected
  workspace identity so MCP calls, audit events, and workflow runs from another
  Codex workspace do not appear as current-workspace evidence.
- Opening a workspace requires an existing `.tradingcodex/workspace.json`
  manifest. Creating a new workspace is a separate POST action and uses the
  normal non-forced bootstrap path, so non-empty directory protection is not
  bypassed from the web surface.
- This selector binds Web, workbench, and Django Ninja requests in the browser
  session. It does not change CLI, MCP stdio, or process-level environment
  behavior.

### Workbench Run Model

A Work request launches the same generated `head-manager` that a user would run
from the attached workspace. Django invokes `codex exec` in JSONL mode and
supervises the process; it does not choose the role team or directly spawn fixed
subagents. Project instructions, skills, hooks, role TOML, MCP allowlists, and
service gates remain authoritative.

Head Manager interprets the request directly and dynamically chooses/revises
exact fixed roles. The service creates only a lightweight analysis run with
request hash/size and sealed provenance; it does not classify intent or build a
plan/DAG.

Preview, initial, and follow-up requests use the same skill-expanded prompt and
are analysis-only. Their JSON body uses the single canonical `prompt` field;
empty optional skill/strategy selections are omitted and unknown fields are
rejected. The API rejects order
drafting, approval, execution, cancellation, broker mutation, and secret
requests before process launch. A selected built-in skill is prompt/procedure
context only and cannot widen role or tool authority.

The runner uses a fixed argument vector with `shell=False`, a vetted attached
workspace as cwd, a project-wide `read-only` filesystem sandbox,
`approval_policy="never"`, disabled sandbox command networking, ignored user
config, an explicit session-scoped trust entry
for the already verified generated project config, an explicit registry-owned
orchestrator/xhigh Head Manager selector, forced hooks, and disabled unified-exec and
browser/computer/app/image action features. It verifies full generated
project/role config, prompts, core skills, launchers, hooks, and the canonical
TradingCodex MCP server, removes secret-like environment variables, and permits
only one active process per run. The same read-only sandbox applies to Head
Manager and every spawned fixed role. PreToolUse admits only the explicit
analysis MCP set plus artifact quality checks. Fixed roles store reports only
through authenticated MCP. Artifact creation derives producer identity,
schema, body hash, and exact run-local input hashes. Head Manager synthesis must
name at least one verified input artifact.
Follow-up resumes the stored Codex thread rather than creating an unrelated
workflow. Every initial or resumed process has a fixed 30-minute elapsed
timeout. Expiry terminates and reaps the process, records a redacted
`workbench.timed_out` event, and returns a normalized `process_timeout` failure.
There is no user-triggered web cancellation.

The workbench receives normalized, redacted, allowlisted events for agent, tool,
source, artifact, and terminal state. It never receives or stores raw reasoning,
tool inputs/outputs, stderr, or raw final output. Reader-facing final analysis
comes only from a hash-bound head-manager synthesis whose sealed run lineage,
authenticated artifact receipts, accepted handoff, and applicable quality gate
all verify, and must show forecast horizon,
assumptions, probability or range, key variables, uncertainty, and invalidation
conditions when a forecast is present.

### Product Web Boundary

- `GET /api/workbench/` and workbench skill, artifact, and run detail are
  read-only local/staff surfaces.
- `POST /api/workbench/preview/` computes the same skill-expanded scope used by
  start without persisting an analysis run or launching Codex.
- Workbench strategy selection is structured input, not prompt inference, and
  its Investor Context checkbox is the only one-run apply/ignore override.
  Preview and start resolve the same active strategy/context bindings; start
  seals them under the protected workflow-run directory with content hashes.
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
- Optional-skill, strategy, investor-context, additional-instruction,
  broker/data-source, internal account-scope, policy, order, and build mutations
  continue through their existing
  authenticated APIs and shared application services.
- Optional skills and `strategy-*` rules may be created, updated, activated,
  archived, deleted, inspected, selected for Work, and projected from Skills,
  but cannot mutate
  protected built-ins, role identity, the project-wide analysis sandbox, MCP
  allowlists, policy, or execution authority.
- External MCP discovery and permission review must not expose raw external
  tools directly to Codex or turn user consent into order/execution approval.
- Execution-sensitive actions remain behind TradingCodex role, MCP, policy,
  approval, duplicate-request, connection, and audit checks regardless of
  whether analysis began in Codex or the workbench.

## Django Admin

Django Admin uses Django's default UI. It is a local/staff DB inspection and
bounded emergency edit surface, not a custom TradingCodex operations console.
The order ledger and MCP registry, connection, permission, and call-ledger
models are fail-closed and read-only in Admin: order tickets, approval receipts,
order-turn grants, execution results, broker orders, fills, check runs, order
events, and MCP state must be changed through their canonical services. Admin
exposes:

- policy, restricted symbols, capability allowlists, limits
- MCP tool registry and tool call ledger
- workflow runs, artifact refs, readiness labels
- order tickets, approval receipts, order-turn grants, execution results
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
state. Cookie-authenticated staff mutations require CSRF. Header API keys do not
require CSRF, but their bound identity must be an active canonical principal.
Role-authored mutations call the same registered MCP service tools used by
stdio, including role allowlists, capability checks, input validation, and
transport-principal binding; a staff session does not itself confer an agent
role, even when a staff username collides with an active agent principal id.
Role-authored endpoints require an API-key-bound principal. Administrative
strategy and optional-skill operations remain available to CSRF-protected
staff, while API-key callers need an active canonical
`head-manager` for those administrative paths. The only anonymous
mutation exception is the three CSRF-protected, loopback-local, analysis-only
workbench POSTs documented above:

- `GET /api/health`
- `GET /api/health/live`
- `GET /api/health/ready`
- `GET /api/workbench/` returns one canonical selected-workspace snapshot for
  Work, Approaches, Research, and Settings as `{generated_at, sections}`, where every
  section is either `{ok: true, data}` or `{ok: false, error}`. Strategies and
  optional skills are snapshot sections rather than a second frontend load path.
- `GET /api/workbench/skills/{skill_id}`
- `GET /api/workbench/artifacts/{artifact_id}`
- `GET /api/workbench/runs/{run_id}`
- `POST /api/workbench/preview/` returns the exact skill-expanded scope used by
  start, including structured strategy and one-run Investor Context choices,
  without persisting an analysis run or launching Codex; it rejects reserved
  native execution tokens
- `POST /api/workbench/runs/` starts one bounded analysis-only Codex run
- `POST /api/workbench/runs/{run_id}/follow-up/` resumes its stored Codex thread;
  start and follow-up also reject reserved native execution tokens before launch
- `GET /api/harness/status`
- `GET /api/harness/components`
- `GET /api/harness/components/{component_id}`
- `GET /api/harness/optional-skills`
- `GET|POST /api/harness/strategies`
- `GET|PATCH|DELETE /api/harness/strategies/{name}`
- `POST /api/harness/strategies/{name}/activate|archive`
- `GET /api/harness/subagents/prompt` returns a Codex-native starter instruction
  without classifying meaning or selecting roles
- `GET /api/subagents`
- `GET /api/subagents/{role}/skills`
- `GET|POST /api/subagents/{role}/optional-skills`
- `GET|PATCH|DELETE /api/subagents/{role}/optional-skills/{name}`
- `POST /api/subagents/{role}/optional-skills/{name}/activate|archive`
- `POST /api/workflows` creates a lightweight analysis run
- `GET /api/workflows/{id}` returns that run and its run-local artifacts
- `POST /api/policy/simulate`
- `GET|POST /api/orders/tickets`; list responses are scoped to the active
  profile (`portfolio_id`, `account_id`, `strategy_id`)
- `GET /api/orders/tickets/{ticket_id}`
- `POST /api/orders/tickets/{ticket_id}/checks`
- `POST /api/orders/tickets/{ticket_id}/approval-request` local control only; Codex risk-manager workflows should prefer MCP `request_order_approval`
- `POST /api/approvals`
- `GET /api/audit/events` returns recent audit events for the API process
  workspace identity only
- `GET /api/portfolio/snapshot`
- `GET /api/portfolio/reconciliations`
- `GET /api/brokers`
- `GET /api/brokers/{broker_id}`
- `POST /api/brokers/{broker_id}/sync`

Broker connection responses expose the required exact `provider_id` and
`transport`. They do not expose or accept a parallel adapter-type identity.
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
The HTTP handlers dispatch these role-owned operations through their canonical
MCP tool definitions rather than maintaining a second REST-only role table.
Caller-supplied `created_by`, `role`, producer metadata, or order principal
cannot replace the identity bound by the staff/API-key transport.

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

The canonical approval route is `/api/approvals`. REST exposes no final order
submit, submitted-order cancel, or broker-order status-refresh mutation. Final
effects enter only through an exact immediate root-native action or an exact
first-line `$tcx-order-allow` turn whose protected tool call carries current
hook-injected proof; both converge on the service-owned execution gateway.

OpenAPI docs are staff-protected. REST is for operations, validation,
inspection, and local control. Codex-native workflows should prefer
role-scoped MCP tools so tool annotations, role allowlists, call ledgers, and
workspace provenance stay in the same approved action boundary. Immediate
submit and cancel never enter through MCP. The current-turn path uses only the
Head Manager-scoped `use_order_turn_grant` tool, which is inert without proof
reserved and injected by `PreToolUse` for that exact turn.

## Root Native Final-Action Boundary

Only a root native Codex workspace user turn may request a final submit or
cancel. For identifiers already known when the turn begins, the complete
trimmed prompt must match one of the exact `$tcx-order-submit` or
`$tcx-order-cancel` `--name value` forms in
[Safety, Policy, And Execution](safety-policy-and-execution.md). Those two skill
bundles are explicit-only documentation and carry no tools.

The generated `UserPromptSubmit` hook recognizes the literal reserved token
before allocating an analysis run, deterministically parses the full prompt,
creates a workspace-bound `native-user` mandate, writes redacted audit metadata,
and calls `application/execution_gateway.py` in-process. It invokes no shell,
subprocess, public MCP tool, REST route, or model. Malformed reserved actions,
subagent turns, Workbench preview/start/follow-up, and the retired
`$execute-paper-order` form fail closed. The returned context is an allowlisted
result projection; canonical recovery comes from DB order status, not automatic
retry.

When the workflow must create or select canonical identifiers during the turn,
the physical first line may instead be exactly `$tcx-order-allow --mode
paper|validation|live`, followed by the normal interactive or Codex app
Scheduled Task request. `UserPromptSubmit` requires the root session and turn,
issues one workspace/session/turn/prompt/mode-bound `OrderTurnGrant`, and lets
normal orchestration continue. Root Head Manager alone can select one later
submit or cancel through `use_order_turn_grant`; `PreToolUse` reserves the grant
for the tool-use id and injects internal proof. A direct MCP caller, Workbench,
or subagent cannot supply that proof. Consumption still enters the same
service-owned policy, approval, idempotency, live-confirmation, adapter, audit,
reconciliation, and uncertainty gates.

## Root Native Build Boundary

Mutating Codex Build work begins only when the exact physical first line of a
root native prompt is `$tcx-build` and later lines contain a non-empty concrete
request. `UserPromptSubmit` issues a DB-canonical `BuildTurnGrant` bound to the
workspace, session, turn, cwd, and complete prompt. `PreToolUse` requires the
grant for direct write tools and injects a one-time internal proof for protected
build MCP calls. The grant supports multiple build steps only in the current
turn; each mutating follow-up requires the exact marker again. Workbench and
subagents cannot mint, inherit, or use it.

This is an intent gate, not a sandbox switch. Actual Codex permissions remain
authoritative; `workspace-write` is the preferred least-privilege setting for
ordinary Build work. Codex Plan mode cannot issue or use a grant, and a grant
is bound to its issue-time permission mode. A read-only turn cannot make native
workspace-file edits, though it may render/read and call the specifically
proof-protected canonical DB services. The generated Build command lane is
limited to native `apply_patch`, exact workspace reads/listing, trusted
workspace-launcher subcommands, and isolated provider `py_compile`; general
shell, scripts, interpreters, `pytest`, and build/test runners are blocked.
Full tests and smokes run from an explicit operator or maintainer terminal.

This also applies to Codex app Scheduled Tasks. A recurring Build task works
only when its deliberately saved prompt starts with `$tcx-build`; every run
gets a fresh grant decision. File-mutating runs require a `workspace-write`
Automation runtime. A read-only run is limited to rendering/inspection and
specifically proof-protected canonical DB calls; Plan mode blocks Build
entirely. Prefer an isolated worktree or workspace and retain a reviewable
diff. `$tcx-build` must never be combined with `$tcx-order-allow`.

Persistent `tcx mode` is retired: `tcx mode status` is an inert compatibility
diagnostic, `tcx mode set ...` cannot grant authority, and any old
`.tradingcodex/runtime/mode.json` is ignored. External MCP consent instead uses
the explicit operator command `tcx mcp permission`. External MCP lifecycle and
consent mutations require an interactive user terminal and are rejected from
Head Manager's Build-turn MCP and shell paths. User-terminal CLI mutation is separate
operator authority and does not synthesize a Build turn.

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
- `begin_analysis_run`
- `list_broker_connections`
- `get_broker_connection_status`
- `sync_broker_account`
- `list_reconciliation_runs`
- `create_order_ticket`
- `run_order_checks`
- `request_order_approval`
- `get_order_ticket`
- `list_order_tickets`
- `use_order_turn_grant` (Head Manager only; requires current hook proof)
- `discard_draft_order`
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

The four External MCP lifecycle tools above are present for the explicit
operator service/CLI path but are omitted from the Head Manager allowlist and
rejected on agent stdio transport. `list_external_mcp_connections` remains the
read-only inspection surface.

Every MCP tool definition includes stable name, description, input schema,
category, risk level, role allowlist, approval requirement, audit requirement,
and standard MCP hints for read-only, destructive, idempotent, and open-world
behavior. `tools/list` returns this metadata as tool annotations.
For `record_source_snapshot`, normal agent/API requests omit service-owned
`snapshot_id`, `retrieved_at`, and `recorded_at`. TradingCodex stamps receipt
and storage time and returns a bounded ID. `known_at` is caller-supplied only
when the true knowable time is supported and timezone-qualified; any explicit
timestamp still passes the strict point-in-time ordering checks.
Every later snapshot read recomputes the content-addressed id and envelope
hash. Run-bound artifact writes derive the exact `source_snapshot_hashes`
mapping and include it in the authenticated artifact receipt, so rewriting and
self-rehashing a snapshot under its old id fails closed.
External MCP lifecycle calls identify a connection by `name`; tool review uses
either `tool_id` or `name` plus `external_name`. Numeric router identifiers and
router/tool-name aliases are not v1 inputs. `record_audit_event` accepts exactly
`{"event":{"type":...,"resource":...,"decision":...,"payload":{...}}}`;
`resource` and `decision` may be omitted and then normalize to an empty resource
and `recorded`, while top-level event fields and `action` aliases are rejected.
For a recorded workflow, research artifact write tools accept caller-owned
report/source fields plus the run/task reference. Canonical workflow semantics,
binding, identity, schema, and hashes are service-derived and reject overrides.
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

External MCP lifecycle mutation is available only through the explicit
interactive operator CLI. Product web and Django Admin may inspect managed
connections and lifecycle results, but they cannot register, import, check,
discover, or review them because those surfaces cannot receive the one-use
operator capability. TradingCodex stores connection metadata, imported
`tools/list`, `resources/list`, and `prompts/list` records, schema hashes, risk
categories, canonical capability mappings, role scopes, and proxy decisions in
the central DB.

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
policy simulation, and the proof-protected `use_order_turn_grant` tool, but
excludes approval creation and raw submit/cancel/refresh mutations. The
protected tool rejects every call without the current hook-injected proof. No
fixed-role allowlist or public/global MCP surface exposes a usable final submit,
cancel, or broker-status-refresh mutation. Role-scoped agent TOML files expose
other narrower risky tools only to their owner roles:

- `risk-manager` can create approval receipts.
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

The CLI entrypoint is `tcx`. `python -m tradingcodex_cli --help` is the current
high-level command inventory; use command-specific help for option details. The
workspace-facing surface is grouped as follows:

- workspace setup and health: `tcx attach`, `update`, `doctor`, `service`,
  `home`, and `workspace`
- analysis and durable context: `tcx workflow begin|show`, `tcx decision list|show|export`,
  `tcx decision snapshot list|record|show`, `tcx profile`, and
  `tcx investor-context`
- roles and reusable capability: `tcx subagents
  list|status|inspect|diff|project|state|context-audit|plan|skills|prompt`,
  `skills`, `strategies`, and `investment-brains`
- research and review: `tcx research`, `forecast`, `postmortem`, and
  `evaluation corpus|run|assign-review|review-packet|blind-review|compare`
- service and operator surfaces: `tcx db`, `policy`, `build`, `connectors`,
  and `mcp`

`tcx postmortem list|process-review|create|show` is available from the CLI;
lesson promotion is only available to the authenticated `judgment-reviewer`
through role-scoped MCP. `tcx mcp external import-codex --source
workspace|global|any --name <server>` and the other External MCP lifecycle
commands require an interactive operator terminal. The compatibility commands
`validate`, `risk-check`, `approve`, `quality-check`, and `audit` remain
available for their narrow documented paths but are not general workflow
entrypoints.

`tcx subagents plan <agent...>|--all` is an explicit fixed-roster and thread-
capacity preview. It validates the caller-named roles and shows deterministic
dispatch batches under the configured thread limit. It does not classify a
request, choose roles, create an analysis run, or persist a workflow plan.

Generated workspaces expose the same workspace-scoped command surface through
`./tcx` on POSIX and `tcx.cmd` on native Windows. In addition to the grouped
commands above, the generated launchers expose `./tcx update status [--json]`
and the retired, inert `./tcx mode status` compatibility diagnostic. Connector
setup remains provider-first through `./tcx connectors`; provider approval and
revocation require an interactive operator terminal.

`tcx subagents prompt` accepts an investment request and emits a Codex-native
starter prompt. `tcx subagents plan` accepts only explicit fixed-role ids or
`--all`; it is not a semantic planner. Optional-skill CRUD uses only `--role`.
The proposal commands retain their distinct `--to` target option because they
are a different proposal contract.

Connector setup is provider-first. Core ships the `paper` provider only; a
named broker request routes to `$tcx-build` to install or develop a reviewed
provider, then registration stores only provider metadata and `credential_ref`.
`inspect-provider` is inert and prints the exact source/bundle hashes for
review. Approval and revocation reject piped or automated stdin and are not
available through MCP, API, Admin, Workbench, Build, or Automation. Approval
creates a database-bound immutable snapshot; the running service must be
restarted before that exact snapshot can load.

Default main-agent skill listing is user-facing, not exhaustive. It shows only
direct user entrypoints: `tcx-plan`, `tcx-workflow`, `tcx-memory`,
`tcx-automate`, `tcx-server`, `tcx-build`, `tcx-investor-context`,
`tcx-strategy`, `tcx-brain-create`, and active `strategy-*` skills.
Postmortem review is part of `tcx-memory`. Full inspection is available through
`./tcx skills list --all` and role-specific `./tcx subagents skills <role>`.

Optional-skill and strategy CRUD CLI commands call the same shared application
service used by the authenticated workbench/API and mainagent guidance.
Additional instruction edits are web-first and file-native; they are stored
under `.tradingcodex/agent-instructions/` and reflected in generated projection
indexes.
