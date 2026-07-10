# Generated Workspaces

This document owns `tcx attach`, `tcx init`, `tcx update`, generated workspace
structure, template behavior, project-scoped MCP config, hook behavior,
workspace provenance, and smoke checks.

## Workspace Contract

`tcx attach`, `tcx init`, and `tcx update` render
`workspace_templates/modules/*/files` into a Codex workspace. After rendering,
they set the Django settings module, apply the central runtime schema, and
record workspace provenance in the central local Django DB.

The template source tree may be refactored for maintainability, but generated
output paths are the `0.2.0` release contract. Module ids, module dependency
resolution, and rendered paths such as `.codex/config.toml`, `.agents/skills/*`,
`.tradingcodex/*`, `trading/*`, and `./tcx` must remain stable unless docs and
tests intentionally change the generated workspace contract.

Template bodies should remain ordinary source files under
`workspace_templates/modules/*/files` whenever the generated artifact is meant
to be read or edited by humans or Codex, such as Markdown, TOML, YAML, JSON,
Python hook scripts, schemas, and wrappers. Python code may own module
registry loading, dependency resolution, rendering, validation, and generated
index writing, but it should not hide durable prompt, skill, policy, hook, or
workspace-contract content inside Python string constants merely for
organization. If a template is generated from structured Python data, the
generated file path and reviewable source-of-truth data must be documented and
covered by contract tests.

The generated workspace is ready for:

- `./tcx doctor`
- `./tcx workspace status`
- `./tcx profile status`
- MCP ledger inspection
- research-memory commands
- local React workbench/Admin service access
- Codex-native role prompts and skills

The generated workspace does not create a workspace-local canonical investment
DB by default.

A generated workspace projects three distinct TradingCodex product layers:

| Layer | Generated-workspace contract |
| --- | --- |
| Core kernel | Non-replaceable workflow-quality, evidence, policy, approval, execution, audit, and provenance contracts. |
| Bundled investment capability pack | The fixed investment team, built-in research and judgment skills, method profiles, and evaluation profiles that define the pristine baseline. |
| Managed user overlays | Additional instructions, optional role skills, and `strategy-*` skills that extend the baseline without replacing core quality or safety requirements. |

The harness is the orchestration and runtime subsystem that projects and
coordinates these layers. It is not the top-level product definition;
TradingCodex is the investment OS.

## Valid Targets

The target may be:

- an empty directory
- a git-initialized directory containing only `.git` plus optional git metadata files

Source checkouts of this repository are development projects, not generated
TradingCodex workspaces.

Codex agents must not run `git clone` when a user asks to install, set up,
attach, or use TradingCodex in a workspace. Run the packaged CLI
from the target workspace instead:

```bash
uvx --refresh --from tradingcodex tcx attach . && ./tcx doctor
```

Agents must also not silently create a default target when a user only asks to
install TradingCodex. The agent rule is: do not invent a
workspace path such as `tradingcodex-workspace`. If no target path is supplied
and the user did not ask to use the current workspace, ask for the target
directory before running setup. If the user is already in an empty target
workspace, install into `.`.

## Generated Files

Generated workspace contract:

- `AGENTS.md`
- `.codex/config.toml`
- `.codex/prompts/base_instructions/head-manager.md`
- `.codex/agents/*.toml`
- `.codex/hooks/tradingcodex_hook.py`
- `.agents/skills/*`
- `.tradingcodex/*`
- `trading/*`
- `./tcx` wrapper

A clean generated workspace must not contain:

- `package.json`
- Node MCP runtime files
- workspace-local canonical investment DB
- broker credentials or raw secrets
- legacy `.tradingcodex/mainagent/head-manager.yaml` or
  `.tradingcodex/mainagent/subagent-registry.yaml` role/skill registry copies
- static `role_owned_skills` roster copies in
  `.tradingcodex/policies/information-barriers.yaml`; role skill sources are
  projected from the agent/skill registry into `.codex/agents/*.toml`

The source repository's React/TypeScript/Vite build does not change this
contract. Compiled workbench assets ship inside the Python package; attach and
update never copy `frontend/`, create `node_modules`, or invoke npm.

## Baseline Generated Contents

Generated workspaces contain a usable pristine investment baseline before the
operator adds a strategy or optional skill. The baseline is expected to support
source-aware research, causal analysis, explicit uncertainty, scoreable
forecast and calibration records, and method-appropriate evaluation. Those are
quality contracts to test, not a claim that every fresh workspace has already
produced enough resolved forecasts or blind reviews to demonstrate calibration.

Generated workspaces contain:

- one root `head-manager`
- ten fixed subagents
- an immutable workspace manifest at `.tradingcodex/workspace.json`
- root `head-manager` identity loaded from `.codex/prompts/base_instructions/head-manager.md` through `.codex/config.toml` `model_instructions_file`
- sectioned Markdown base-instruction format for `head-manager`, including `# How you work`, TradingCodex guardrails, and tool guidelines
- Codex-style operating style in the root `head-manager` prompt: scoped `AGENTS.md` handling, concise preambles, selective planning, `rg`-first search, `apply_patch` edits, focused validation, dirty-worktree respect, concise maintenance handoffs, and brief chat replies that point to saved head-manager synthesis reports once accepted artifacts exist without making the saved research report shallow
- instruction/skill separation: root `head-manager` instructions own identity, durable safety boundaries, fail-closed dispatch, role boundaries, skill routing, optional-skill management, and approved action boundaries; fixed subagent TOML files own standing role identity, MCP/tool config, artifact walls, and always-on prohibitions; repo skills are dependency-light capability procedures for workflow maps, compact assignment-envelope templates, optional skill file management, quality gates, synthesis, and postmortems, without declaring role ownership or direct inter-skill call chains
- no-overlap handoff contract: each role owns its specialist question, downstream roles consume accepted artifacts, and missing/stale/weak upstream work returns `revise`, `blocked`, or `waiting` instead of being silently redone by another role
- validated staged workflow plan: integrity-bound intake fixes routing while `$tcx-workflow`
  drafts, validates, records, and dispatches from a staged plan before
  substantive investment analysis
- negated scope routing: phrases such as "no valuation", "no order", and "no trading" remove those actions or roles from dispatch selection
- broad public-equity prompts such as "Analyze NVDA" default to deep thesis
  review with fundamental, technical, news, and valuation roles unless explicit
  constraints narrow the team first; narrow fact-only and technical-only
  prompts do not add `judgment-reviewer` unless broader judgment is requested
- compact Decision Quality Spine flags in hook context for decision quality,
  forecast contract, profile gate, anti-overfit, and deep thesis default
- no full-history fixed-role spawn: fixed `agent_type` subagents receive compact assignment envelopes without full-history forking on the first attempt
- subagent hook isolation: `UserPromptSubmit` auto-routing is ignored for fixed subagent contexts so subagent briefs cannot overwrite main-agent routing state or create recursive dispatch pressure
- main-to-subagent briefs are assignment envelopes, not role manuals: they carry the current task, original request, explicit constraints, workflow consent posture, artifact language, lane, artifact target, compact context summary, request-specific out-of-scope items, and return contract without repeating long method/source/guardrail checklists or pasting full artifacts
- narrow research-only briefs use an Evidence Quality Floor instead of thesis
  or decision-quality fields
- approved-action briefs stay service-boundary focused by passing ticket, approval, policy, duplicate-request, connection, and audit references instead of research source snapshots or thesis-quality fields
- verification-budget copy is lane-specific: approved-action, connector, and
  strategy lanes verify their own service or validation evidence instead of
  research source-freshness fields
- context-efficient research handoffs: stored markdown frontmatter includes
  `context_summary` so downstream roles can consume artifact paths and summaries
  before opening full markdown; `reader_summary` and `next_action` keep the
  first-read experience clear for non-expert users
- context-budget audit: `./tcx subagents context-audit --strict` inspects the
  latest workflow intake, intake history, compact hook context, subagent
  session state, workflow loop state, and research artifacts after long multi-subagent runs; it
  fails strict mode when handoff artifacts lack `context_summary`, compact gate
  history grows beyond budget, or gate/state/history payloads look like pasted
  markdown artifacts, and warns when reader-first fields are missing
- compact subagent session state: `.tradingcodex/mainagent/subagent-session-state.json`
  keeps total counters plus recent active/completed/event records for Codex
  context; the full event stream remains in
  `trading/audit/subagent-session-events.jsonl`
- compact workflow loop state: `.tradingcodex/mainagent/workflow-loop-state.json`
  is the latest summary and pointer; the canonical state for each routed prompt
  lives under `.tradingcodex/mainagent/workflows/<workflow_run_id>/loop-state.json`
  with `intake.json`, `workflow-plan.json`, and the append-only `events.jsonl`
  beside it. State revisions are serialized through one reducer, event ids are
  idempotent, and replay must reproduce the materialized state. The state records
  validated stages, selected team, allowed follow-up team, loop policy, pending
  tasks, planner decisions, escalation proposals, blocked actions, and stop reason
  without spawning subagents recursively
- web-started run state beside the canonical per-run control files contains only
  bounded operational metadata and normalized, redacted, allowlisted events.
  The web runner does not persist raw reasoning, tool inputs/outputs, stderr, or
  raw final output. A reader-facing head-manager synthesis additionally requires
  validated synthesis-ready plan/state, accepted handoff, producer and body-hash
  binding, and the exact complete set of accepted input hashes
- `improve` ledger records under `.tradingcodex/mainagent/improve.jsonl`,
  plus incremental summaries and dedupe state in
  `.tradingcodex/mainagent/improve-index.json`, fed by artifact
  `improvements`, postmortem review, and selected loop feedback; these records
  are reusable investment-judgment context and never apply prompt, skill,
  policy, MCP, broker, approval, or execution changes
- Codex session/thread routing map:
  `.tradingcodex/mainagent/session-workflow-runs.json` maps a Codex app session
  key to the active `workflow_run_id`, so two app threads in one attached
  workspace can continue different loops without clobbering each other
- a registry-projected GPT-5.6 role policy: Sol/high for head-manager and
  quality-critical judgment roles, Terra/high for routine evidence roles, and
  Luna/low for the bounded execution operator, with GPT-5.5 as an allowlisted
  rollback target for every role
- `.tradingcodex/generated/model-policy-manifest.json` with policy revision,
  resolved and fallback models, reasoning effort, required capabilities,
  prompt/tool-profile revisions, rollout cohort, and `verified`, `unverified`,
  `unsupported_fallback`, or `rollback` support posture
- fixed subagent `nickname_candidates` set to a single item matching the exact role `name`
- fixed subagent identities kept in `.codex/agents/*.toml` `developer_instructions`, as required by Codex custom agent files
- project-local additional agent instructions under `.tradingcodex/agent-instructions/<role>.md`; projection appends them after generated default instructions for `head-manager` and fixed subagents as a managed overlay, without permitting them to replace core role, quality, policy, approval, or execution boundaries
- an immutable core/extension footer projected after project-local additional
  instructions for both `head-manager` and fixed roles
- live built-in Codex web search in `.codex/config.toml` so the pristine
  research baseline has current public-source access without requiring a
  host-installed finance skill; source/as-of and evidence rules still apply
- workspace customization preferences under `.tradingcodex/user/customization.json`, merged over `preferences/customization.json` in the canonical platform home; these files store UX/config metadata and never raw credentials
- twenty-six bundled repo skills across project-scope mainagent skills and subagent skill directories, each with `SKILL.md` frontmatter for document metadata and UI metadata when projected
- decision-quality skill bundles for forecasting discipline, thesis scenario
  trees, numeric data QC, and anti-overfit validation, plus role-owned
  `agent-judgment-review` for the independent `judgment-reviewer` gate
- standalone `strategy-*` skills under `.agents/skills/strategy-*` for user-approved agent-readable investment strategies, created through `strategy-creator`, CLI, authenticated workbench/API, or service-layer flows and exposed to the root `head-manager` through the strategy marker block in `.codex/config.toml`
- file-native agent/skill projection: head-manager and strategy skills live under `.agents/skills/*`, role-owned subagent skills live under `.tradingcodex/subagents/skills/*`, and role TOML embeds the allowed role skill source list; state is expressed in `.codex/agents/*.toml`, `.codex/config.toml`, `.tradingcodex/mainagent/skill-change-proposals/*.yaml`, and `.tradingcodex/generated/*.json`, not Django skill DB tables
- optional subagent skills are created, updated, activated, archived, deleted, and validated through the shared application service used by `head-manager`, CLI, authenticated API, and workbench
- information-barrier policies
- order/approval schemas
- restricted-list policy
- built-in paper provider plus provider-driven validation/live gates
- audit directories
- central local SQLite service access through `state/tradingcodex.sqlite3` in the canonical platform home
- workspace identity through `.tradingcodex/workspace.json`
- workspace provenance through `TRADINGCODEX_WORKSPACE_ROOT`
- an active paper profile reference used as the default portfolio/account/strategy scope
- Python hook scripts callable from Codex hook commands
- generated indexes under `.tradingcodex/generated/`, including
  `module-lock.json`, `capability-index.json`, `component-index.json`,
  `agent-index.json`, `skill-index.json`, `model-policy-manifest.json`, and
  `projection-manifest.json`
- skill and projection indexes that identify each managed skill by id, layer,
  trust scope, implicit-invocation posture, and workspace-relative resolved
  source file; the same
  indexes declare `inventory_scope=tradingcodex_managed_workspace` and
  `runtime_discovery_complete=false` rather than pretending to inventory the
  whole host Codex runtime
- append-only forecast ledger directory at `trading/forecasts/`
- immutable point-in-time research directories for specs, replay manifests,
  experiments, causal analyses, blind judgment priors/reviews, and a
  rebuildable research index under `trading/research/`
- research-only model-evaluation directories under `trading/evaluations/` for
  frozen corpora, control/candidate runs, blind reviews, and comparisons

## Skill Discovery Boundary

The managed workspace baseline consists of the projected core kernel, bundled
investment capability pack, and explicitly activated TradingCodex overlays.
Codex may also discover metadata for skills installed globally or supplied by
host plugins. Those host capabilities are outside the TradingCodex pristine
baseline and must enter a workflow only through explicit user opt-in for that
current workflow or a managed activation path that preserves role, quality,
policy, approval, and execution boundaries.

Workspace projection and role-local skill lists reduce accidental mixing, but
they are not by themselves proof of hard runtime isolation from every
host-discoverable skill. Documentation and release claims must not promise hard
isolation until clean-host, populated-host, name-collision, and invocation
smokes attest it. `doctor --layer improvement` verifies exact enabled managed
skill paths for root and every fixed role and fails on a same-name host-global
collision; a differently named host skill remains outside that finite managed
inventory and must be covered by invocation smokes.

## Method And Evaluation Profiles

The bundled capability pack declares method profiles so one analysis template
does not become a universal answer:

- `general_evidence_v1` for source-aware evidence synthesis
- `event_research_v1` for event chronology and causal impact analysis
- `quant_signal_v1` for signals, validation, costs, leakage, and overfitting
  controls
- `listed_equity_fcff_dcf_v1` for listed-equity FCFF valuation with explicit
  revenue, margin, reinvestment, risk, and sensitivity assumptions

`core_investment_v1` is the bundled pristine evaluation profile. Frozen corpora
may declare additional profiles with their own required tags and dimensions.
Profile declarations make method fit and comparison reproducible; they do not
prove forecast or analysis quality without populated frozen inputs, paired
runs, hard-failure checks, blind review, and resolved outcomes.

Generated `.codex/config.toml` keeps all named roles registered while setting
`agents.max_threads = 6` and `agents.max_depth = 1`. Roster size is not a
scheduler concurrency promise, and no subagent may recursively dispatch another
role. The active routing envelope further bounds concurrency and total tasks per
run.

`TRADINGCODEX_MODEL_ROLLOUT=rollback` selects the GPT-5.5 control during
generation/projection. Operators may provide
`TRADINGCODEX_CODEX_SUPPORTED_MODELS` as a comma-separated capability input; a
missing primary selects its fallback. Without that input the generated policy
is intentionally reported as runtime-unverified, so `doctor` checks projection
consistency but does not claim that a real Codex session has loaded the model.

Workspace template modules are deployment projections. Harness component
ownership comes from the Python component registry and is exported into
`component-index.json` for Codex-readable inspection.
Agent and skill ownership comes from the Python agent registry and is projected
into Codex-readable agent TOML plus generated agent/skill indexes.

User-configured Codex MCP servers are discovered from project and root Codex
config, then imported into TradingCodex External MCP Gate before use. Generated
project config should not expose external broker/data MCP tools directly to
subagents. TradingCodex writes Codex MCP config only inside explicit managed
blocks and leaves user-owned config outside those blocks untouched.

## Attach-First UX

TradingCodex is installed globally once, then attached to the workspace where
the operator wants to ask Codex agents to work.

Recommended agent-facing flow:

```bash
uv tool install tradingcodex
uv tool update-shell
cd <user-selected-workspace>
tcx attach .
codex .
```

`tcx attach .` is the default user-facing CTA for adding the TradingCodex
harness to the current workspace. `tcx init <path>` remains the empty-directory
creation command. Attach preserves an existing TradingCodex `workspace_id` and
active profile when refreshing an existing generated workspace.

## Update UX

`tcx update .` is the explicit release-update command for an existing generated
workspace. It requires `.tradingcodex/workspace.json`,
`.tradingcodex/generated/module-lock.json`, and the legacy-compatible `tcx`
marker to exist before it will overwrite generated paths. The update installs
or refreshes the native `tcx.cmd` launcher when it is absent.

Update behavior:

- preserve immutable `workspace_id`
- preserve active profile selection
- preserve per-run workbench operational metadata, normalized events, and
  accepted artifacts
- re-render generated template paths from the currently running package
- refresh generated indexes under `.tradingcodex/generated/`
- apply central DB migrations through the shared runtime path
- persist the workspace context in the central DB
- run `./tcx doctor` unless `--no-doctor` is passed

Update consumes the frontend build already included in the Python package. It
does not install Node dependencies or run the Vite build.

Package-release updates should prefer a refreshing package invocation so the
latest package is fetched before rendering:

```bash
uvx --refresh --from tradingcodex tcx update .
```

Generated workspaces contain one shared Python launcher at
`.tradingcodex/cli.py`, a POSIX `./tcx` shim, and a native Windows `tcx.cmd`
shim. The Python launcher owns package fallback, hook dispatch, home/service
environment, and update refresh behavior. On update it prefers
`uvx --refresh --from <recorded-package-spec>` when available. Windows users
run `.\tcx.cmd` in PowerShell; native Windows validation never treats the Bash
shim as executable evidence.

Inside a Codex-generated workspace, `head-manager` runs under a workspace
permission profile. It can write workspace files and TradingCodex home state,
but it should not update the generated harness itself: workspace update rewrites
protected `.codex` prompt/config/hook surfaces and generated files that define
the current agent. For already-installed packages, the wrapper supports a
user-terminal workspace-only path:

```bash
./tcx update --skip-refresh
```

`--skip-refresh` uses a Python environment where the package is already
importable or an installed `tcx` command, and avoids the `uvx` refresh step.
If startup health reports `update_status.workspace_update_allowed=true`,
`head-manager` should tell the user to run
`update_status.workspace_update_command` from their terminal. If startup health
reports `update_status.package_update_required_first=true`, including when the
generated workspace and installed wrapper both match an older release, package
refresh is also a user-terminal action, normally:

```bash
uvx --refresh --from tradingcodex tcx update .
```

## Project-Scoped MCP Config

Generated Codex workspaces render a project-scoped
`[mcp_servers.tradingcodex]` entry in `.codex/config.toml`.

The config follows the OpenAI Codex MCP shape:

- stdio `command`
- `args`
- `enabled`
- `env`
- `enabled_tools`
- `default_tools_approval_mode`
- `startup_timeout_sec`
- `tool_timeout_sec`

The built-in `tradingcodex` MCP server defaults safe enabled tools to
`approve` so routine research, audit, status, and reviewed service calls do not
bury Codex permission prompts inside subagent transcripts. Execution-sensitive
tools remain excluded from non-execution roles; `execution-operator` exposes
only the TradingCodex approved-order submit/cancel tools, and the service layer
still revalidates permission, policy, approval, duplicate-request state,
connection, and audit before any adapter call.

Each root or fixed-role MCP instance binds its immutable transport identity in
`TRADINGCODEX_MCP_PRINCIPAL`. A caller-supplied `principal_id` must match that
binding and cannot elevate the role. Direct CLI calls that intentionally act as
a role establish the same transport binding before entering stdio dispatch.
The environment value identifies a role; it is not a secret or a substitute for
the separate API/session authentication required by HTTP mutations.

Project-scoped Codex config applies only when the generated workspace is
trusted by Codex.

The generated TradingCodex MCP command uses:

```text
uvx --refresh --from <package-spec> python -m tradingcodex_cli mcp stdio
```

The package spec is recorded during bootstrap so PyPI and GitHub-source
installs keep the same MCP source without stale source-cache reuse.

Codex resolves an MCP server's `cwd` from the launched project working
directory, not from the directory containing the TOML file. Root and fixed-role
MCP entries therefore use `cwd = "."` together with
`TRADINGCODEX_WORKSPACE_ROOT = "."`, so intake, plan, artifact, and audit paths
remain bound to the attached workspace.

Codex project config should register only the `tradingcodex` MCP server.
Generated permission profiles allow network access for public evidence
gathering, such as filings, disclosures, news, web sources, and market-data
references. They still deny workspace secret paths and do not authorize direct
broker APIs, broker-specific Codex MCP servers, approval bypass, or execution.
Managed external Codex MCP entries written through `tcx build codex-mcp add`
default to `prompt`; import them into the External MCP Gate before use.
Broker APIs are attached through provider-driven TradingCodex connector profiles
using canonical MCP tools such as `list_broker_adapter_providers`,
`scaffold_broker_connector`, `register_broker_connector`,
`validate_broker_connector_build`, `get_broker_capability_profile`,
`get_broker_instrument_constraints`, and `preview_order_translation`.

Generated Codex config declares the resolved canonical TradingCodex home in
`sandbox_workspace_write.writable_roots`. This bounded
writable root is required for the central local DB, migration lock, service
status, and update preference files when the active Codex surface honors
project-scoped sandbox roots. It is narrower than disabling the sandbox, and
generated permission rules continue to deny `.env`, secret, and
broker-credential-shaped paths under both the workspace and TradingCodex home.
If a Codex CLI or app run still reports the selected home outside writable
roots, the user should regenerate the workspace or add the exact path through
user-level Codex config or CLI `--add-dir`
before running service recovery or update-adjacent commands.

Broker/data MCP servers, when explicitly needed for reviewed read-only
discovery, are registered inside TradingCodex External MCP Gate with
`./tcx mcp external ...`, not directly in `.codex/config.toml` or
`.codex/agents/*.toml`.

## MCP Autostart

The generated TradingCodex MCP config sets:

```text
TRADINGCODEX_MCP_AUTOSTART_SERVICE=1
```

This lets Codex MCP startup idempotently start the local Django workbench
service at `127.0.0.1:48267` while keeping MCP stdio stdout clean.

If the port is already open, MCP startup verifies that the existing process is
a TradingCodex service with the same package version and central DB path before
using it.
When the existing process is an older TradingCodex service backed by the same
central DB, MCP autostart may stop it and launch the current package instead.

The autostart path must be:

- idempotent
- silent on MCP stdout except for MCP protocol messages
- not required for direct `./tcx mcp stdio` smoke checks

Generated workspaces also support startup context for Codex sessions.
Bootstrap writes an initial compact diagnostic cache at
`.tradingcodex/mainagent/server-status.json`, and the `SessionStart` hook
refreshes it; neither path starts services, updates workspaces, opens browsers,
or performs package refresh on its own. The emitted context uses marker
`tradingcodex-session-context` and keeps only compact fields for
`mode_status`, `permission_status`, `update_status`, `server_status`,
`allowed_next_actions`, and `routing_status`.

`head-manager` uses `$tcx-server` for service/MCP doctor checks,
`./tcx service status`, `./tcx service stop`, and `./tcx service ensure`. It tells the user that the
local workbench is available at `http://127.0.0.1:48267/` and opens it only
when explicitly asked. If project MCP config was created or changed, the user
must fully quit and restart Codex and start a new thread because Codex may not
hot reload project MCP config.

Startup context preserves incompatible service detail from `./tcx service
status`, including `service_issue`, service/package versions, DB paths, and the
recorded next action. If the issue is `version_mismatch`, `db_mismatch`, or
`port_occupied`, `head-manager` must mention the startup notice in its first
user-facing response and avoid presenting the workbench as ready until the
recovery path is handled.

Startup health may compare the generated workspace version in
`.tradingcodex/generated/module-lock.json` with the installed/running `tcx`
package version and the latest known TradingCodex release. If update is needed
while Codex is running under restricted TradingCodex permissions, `head-manager`
must explain the two supported paths: switch Codex to full access and enable
TradingCodex build mode, or run the recommended `update_status.command` from a
terminal. Self-update is allowed only when Codex full access and explicit
workspace build mode are both active and the user asks for the update. After
self-update, `head-manager` stops and tells the user to restart Codex. If a
same-DB service is already running with a newer TradingCodex version than the
current wrapper, startup health treats that service version as an update hint
and should recommend package/workspace refresh before service stop.

Build mode is per workspace and explicit:

- `./tcx mode status`
- `./tcx mode set build --reason "<reason>"`
- `./tcx mode set operate`

Build mode may update TradingCodex, templates, and broker/API provider
scaffolds, including live-capable provider code. It never submits live orders;
live submission remains behind the service gates. Update recommendations are scoped
to the new-conversation health pass, not every user turn. If the user declines
update prompts, `head-manager` records `preferences/update.json` below the
canonical TradingCodex home with
`suppress_update_recommendation=true`; future new conversations should not
recommend automatic workspace updates unless the user removes or changes that
flag, or explicitly asks for an update.

Connector onboarding is connect-first: `tcx connectors connect <broker>` wraps
provider discovery, scaffold, registration, validation, and plain status output.
Advanced scaffold/register/validate commands remain available. If the requested
provider is not installed, the generated connector profile records
`provider_development_required` instead of pretending the broker is already
supported.

Broker provider build work is separate from the running operate server. A
generated workspace may already have TradingCodex MCP autostarting the Django
service; provider file changes must not be treated as hot-loaded live execution
authority. Connector profiles record provider source hashes, status calls report
`service_restart_required` when source changed after registration, and live
execution remains blocked until the service is restarted and the connector is
revalidated.

## Hooks

Generated hooks are Python scripts. Hook behavior is guidance, not final
enforcement.

`UserPromptSubmit` handles:

- prompt classification
- secret warnings
- natural-language investment workflow intake context and deterministic hints
- direct-answer prevention context
- duplicate marker management
- workflow-intake audit metadata with prompt hash and heuristic lane, without raw
  prompt text in the audit ledger
- compact hook `additionalContext`; full staged workflow contracts are recorded
  by `$tcx-workflow` under `.tradingcodex/mainagent/workflows/<workflow_run_id>/`
- compact Artifact Supervisor Loop metadata in recorded `workflow-plan.json`
  and `loop-state.json`, not as final hook-selected teams
- assisted loop planner previews through `./tcx subagents loop --artifact
  <path>`, with optional `--record` limited to file-native pending tasks,
  planner decisions, escalation proposals, blocked actions, and stop reason
- execution negation routing such as "no order" and "no trading"
- strategy authoring prompts remain in `strategy-creator`/strategy CRUD scope
  instead of auto-dispatching fixed investment subagents
- connector implementation prompts such as "connect this broker"
  route to the `connector_build` lane and `$tcx-build`, not investment
  thesis review; their workflow packages use workflow lifecycle and boundary
  sections rather than thesis lifecycle or portfolio/risk sections
- secret-only routing: credential, token, password, broker-key, or `.env`
  storage/read/rotation prompts create warning context without activating
  investment subagent dispatch unless a separate investment or execution
  request remains
- startup diagnostics: `SessionStart` records compact mode, permission,
  update, service, and routing status for `head-manager`
- update recommendation diagnostics: `SessionStart` records package/workspace
  drift and respects the TradingCodex home update preference file

Hooks load only in trusted projects and may be disabled when
`features.hooks=false`.

## Workspace Provenance

Generated workspace wrappers derive `TRADINGCODEX_WORKSPACE_ROOT` from their
own location instead of recording the attach machine's project path or
incidental source-import path. Generated hook commands use that wrapper, and
Codex skill paths are relative to their declaring project config. MCP `cwd` is
relative to the launched project working directory as described above. The
generated contract does not persist the builder's Python executable. A local
package spec explicitly supplied through `--from` remains recorded as
intentional MCP/update provenance.

The wrapper and project MCP config retain the canonical `TRADINGCODEX_HOME`,
its `TRADINGCODEX_HOME_SOURCE`, and `TRADINGCODEX_SERVICE_ADDR` selected at
attach/update time. `.tradingcodex/generated/module-lock.json` records
`tradingcodex_home`, `home_source`, the rendered DB path, and `db_source`. An
explicit `TRADINGCODEX_DB_NAME` override is retained in the shared Python
launcher and every generated MCP environment instead of falling back to the
home-default ledger. The generated
`.tradingcodex/config.yaml` uses that canonical DB path rather than a tilde
literal. Explicit process environment values still override recorded values;
doctor then validates both home and DB projection and requires update when the
generated ledger contract is stale.

TOML, YAML, JSON, POSIX shell, CMD, and Python values are serialized with
format-specific literals. This is required for macOS paths with spaces and
Windows drive-letter/backslash paths. Generated code/config uses LF line
endings; executable bits are applied only on POSIX. Hooks select `./tcx` on
POSIX and `tcx.cmd` on native Windows. If a workspace is copied between
platforms, run `tcx update` from the installed package on the destination before
opening it in Codex so launcher, hook, writable-root, and MCP projections match.

The workspace-root value helps TradingCodex answer which Codex project called
the service; it must not partition canonical investment state. This keeps
hooks, platform launchers, and MCP calls from silently splitting runtime state.

`.tradingcodex/workspace.json` stores immutable workspace identity:

- `workspace_id`
- project name
- active profile reference
- MCP scope
- execution mode

`path_hash` remains path provenance. It is not the durable workspace identity.

## Profile Scope

The workspace is a Codex workbench, not an investment ledger. Paper portfolio
state is scoped by active profile:

- `profile_id`
- `portfolio_id`
- `account_id`
- `strategy_id`

Newly attached workspaces receive an isolated paper profile derived from their
immutable workspace id. This prevents a fresh workspace from silently opening
another workspace's draft orders or paper portfolio as its default context.

The shared central paper profile remains available only through explicit
selection:

```text
default-paper / local-paper / default-strategy
```

Product web displays a persistent warning while a shared profile is active.
Operators can create and select additional isolated profiles, or explicitly
select the shared profile, with:

```text
./tcx profile create <profile-id>
./tcx profile select <profile-id>
./tcx profile select shared
./tcx profile update --base-currency EUR --objective "medium-term thesis" --horizon "3 to 5 years" --risk-tolerance "moderate drawdown tolerance"
```

Order and portfolio commands use the selected profile when an order does not
provide explicit portfolio/account/strategy ids. Each profile also carries a
validated three-letter base-currency code; native-currency orders require a
point-in-time FX snapshot before policy compares their converted notional with
the profile's base-currency limit. New profiles start with `USD` as an explicit,
changeable bootstrap default rather than a market-specific policy constraint.
Starter-prompt intake and the
Codex `UserPromptSubmit` workflow gate also read the active profile's investor
context, so answered suitability/profile fields are reused and only missing
fields are shown as questions.

Workspace-manifest schema 2 records the base currency explicitly. When an
older manifest and paper snapshot are opened, TradingCodex preserves their
original currency and cash amount as migration compatibility; it does not
silently reseed or relabel that balance with the new-workspace default.

## Optional Global Home MCP

Project-scoped MCP remains the approved action boundary. An optional global Codex MCP
server can be installed with:

```text
./tcx mcp install-global --safe
```

The global server name is `tradingcodex-home`. It is read-only/safe-scope only
and must not expose approval, execution, cancellation, policy mutation, secret,
or broker tools.

## Bootstrap Verification

Codex-native bootstrap verification:

- `./tcx doctor` checks generated project MCP server shape and role allowlists.
- `./tcx update --no-doctor` verifies the generated update path without running
  the full doctor twice in installer smoke tests.
- `./tcx mcp stdio` `tools/list` verifies the TradingCodex MCP bridge and tool annotations.
- `./tcx mcp external list` verifies the External MCP Gate CLI path.
- Generated Codex MCP config starts the stdio MCP bridge through `uvx` and starts the local workbench service when autostart is enabled.
- The installed wheel serves the committed SPA shell and assets without Node;
  workbench-started Codex runs reuse the attached workspace's generated
  `head-manager` contract.
- Direct `./tcx mcp stdio` remains service-free unless `TRADINGCODEX_MCP_AUTOSTART_SERVICE=1` is set.
- `codex exec -C <workspace> --skip-git-repo-check ...` can verify that Codex CLI loads generated project context.

The management command `codex mcp list/get` may show only user/global MCP
servers, even when a session uses project-scoped MCP config after workspace
trust.

## Template Change Rule

Hand-editing a generated workspace in an OS temporary directory is only a
smoke/debug step.
Durable behavior changes belong in `workspace_templates/modules/*`, docs, and
tests. After changing bootstrap behavior, regenerate a clean workspace for
verification.

Template contract tests must cover:

- every `module.json` id matches its directory name
- every declared module dependency exists
- the default module graph resolves
- generated workspaces keep the public output paths and avoid Node runtime
  files, Python bytecode caches, broker secrets, and workspace-local canonical
  investment DBs
