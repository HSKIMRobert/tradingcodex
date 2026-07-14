# TradingCodex Harness

This document owns the v1 Codex harness contract: prompts, skills, exact fixed
roles, hooks, MCP boundaries, generated projection, and native validation.

## Architecture

The harness spans three planes:

| Plane | Responsibility |
| --- | --- |
| Codex control plane | Head Manager prompt, fixed-role TOML, skills, dynamic role orchestration, V2 spawn/wait behavior |
| Django service plane | MCP identity/capability checks, artifact/source persistence, policy, orders, approval, broker, execution, audit, bounded Workbench supervision |
| Workspace system plane | Generated config, run records, skill projection, research markdown, source snapshots, audit files, launchers |

Research orchestration is Codex-native. Django is not an analyst scheduler. It
does not classify natural language, select a lane or team, compile a DAG,
allocate role tasks, or run an artifact supervisor loop.

## Fixed Runtime

Head Manager uses `gpt-5.6-sol` with `xhigh` reasoning. Analytical fixed roles
use `gpt-5.6-terra` with `high` reasoning. Final provider effects are not a role
and run through the deterministic service gateway rather than an execution
model. All analysis sessions use the project-wide read-only sandbox.
Evidence roles receive live web search through their role config; Head Manager
does not.

MultiAgent V2 must expose exact `agent_type`. Every TradingCodex spawn uses a
fresh child, compact underscore-only task name, compact assignment, and
`fork_turns="none"`. `followup_task`, full-history fork, generic fallback,
role emulation, and model overrides are invalid.

## Hooks

Hooks own only:

- service/update/build-authorization health context;
- run/thread/session transport binding;
- exact registered-role, `fork_turns`, and task-name checks;
- a strict V2 spawn-field allowlist (`agent_type`, `fork_turns`, `message`, and
  `task_name`) that rejects model, reasoning, sandbox, and other overrides
  before a child is created;
- analysis-only tool policy;
- exact parsing and immediate in-process service dispatch for the two reserved
  action-only submit/cancel prompts;
- exact physical-first-line parsing for `$tcx-order-allow`, bounded turn-grant
  issue/revocation, and protected proof injection into
  `use_order_turn_grant`;
- exact physical-first-line parsing for `$tcx-build`, DB-canonical current-turn
  grant issue/revocation, direct write-tool gating, and protected build MCP
  proof injection; and
- redacted hook and subagent event audit.

Outside the three literal reserved execution tokens and the literal
`$tcx-build` first line, hooks never decide whether text is an investment
request, infer a universe, choose roles, or read a semantic plan. The native
parsers validate fixed syntax, not natural-language intent, negation, symbol
scope, or limits. Korean and other analysis requests therefore do not depend on
a hard-coded keyword classifier.

## Analysis Run

For investment analysis, Head Manager calls `begin_analysis_run`. The service
stores only request hash/size and sealed strategy/Investor Context provenance
at `.tradingcodex/mainagent/runs/<run-id>/run.json`. The record contains no raw
request, lane, selected team, plan, task queue, or terminal action.

Workbench may create this lightweight record before starting Codex because it
already owns the run id and selected overlays. Native Codex creates it through
the Head Manager-only MCP tool.

## Artifacts

Each producing role writes its own report through authenticated
`create_research_artifact`. The service derives principal/producer identity,
validates the run, computes the content hash, and resolves run-local
`input_artifact_ids` to exact hashes. Old `plan_hash`, `stage_id`, and `task_id`
bindings are not accepted.

Head Manager retrieves exact returned artifacts, decides the next wave, and
creates the final `synthesis_report` with every consumed input artifact ID.
Synthesis without at least one verified run-local input is rejected.

## Quality

Artifact handoff states, source/as-of posture, claim tags, context summaries,
method profiles, decision-quality fields, forecasts, and judgment review remain
quality contracts. They guide Codex judgment and deterministic artifact
validation; they do not form a Django workflow state machine.

## Execution Separation

Skills may explain execution procedure but do not themselves grant authority.
Natural language cannot create an order, approval, or broker action. The root
`tcx-order-submit` and `tcx-order-cancel` bundles carry no tool
authority and disable implicit invocation. Only a complete exact root native
prompt can be parsed into a workspace-bound `native-user` mandate. The
`UserPromptSubmit` hook then calls the canonical execution gateway in-process,
before Head Manager or a subagent runs.

The explicit-only `tcx-order-allow` bundle is the separate turn-admission protocol.
Its physical first line must be exact `$tcx-order-allow --mode
paper|validation|live`. The hook binds a single-use grant to workspace,
session, turn, complete prompt hash, Codex permission mode, and execution mode,
then allows the normal workflow to continue. Plan mode rejects immediate order
effects plus grant issuance and use. The grant expires after one hour and is
revoked on one submit or cancel, `Stop`, or the next turn. Only root Head Manager has
`use_order_turn_grant`; `PreToolUse` reserves the grant for the tool-use id and
injects an internal proof that model input and direct MCP callers cannot
supply. Public REST, generic CLI, Workbench, subagents, and direct MCP calls
therefore expose no usable final authority. Policy, payload validation,
restricted lists, approval receipt matching, idempotency, account scope, broker
health, live confirmation, reconciliation, and audit remain canonical service
gates. A consumed grant with `result_status=authorizing` is an in-flight
canonical effect, not reusable authority. Stop/new-turn cleanup leaves it
untouched and a new Build or order-sensitive prompt in that session blocks
until terminal; ordinary research may continue. Native project config explicitly enables hooks and disables unified execution and interactive action
features. `PreToolUse` and `PermissionRequest` cover legacy `Bash` plus current
`exec_command`/`write_stdin` names and admit only exact managed
skill/reference reads, so model-launched Python cannot become a parallel
mandate or adapter path. Codex must trust the attached workspace before that
project config, its MCP server, or its hooks load. Until then native execution
is unavailable and there is no shell, public MCP, REST, generic CLI, or
model-selected fallback.

`tcx-automate` authors Codex app Scheduled Tasks for simple research,
monitoring, recurring analysis, portfolio or status review, draft orders,
assisted execution, optional turn-authorized execution, and explicitly
delegated turn-authorized Build work. The saved prompt is submitted on every
scheduled turn. TradingCodex does not distinguish an Automation-origin turn
from an interactive root turn. Only execution-capable tasks include the exact
`$tcx-order-allow` first line; only recurring Build tasks deliberately start
with `$tcx-build`, and the two markers are never combined. The saved runtime
prompt invokes the actual workflow skill rather than recursively invoking
`$tcx-automate`.

The first-line mode is only an execution ceiling. Hooks and services enforce
canonical mode, ticket, receipt, policy, and action fields; they do not claim
to compile free-form task scope into deterministic policy.

Build authorization is a separate current-turn intent gate. An exact
`$tcx-build` physical first line followed by a non-empty request issues a
workspace/session/turn/cwd/prompt-bound `BuildTurnGrant`. It may support
multiple workspace-local edits and validations during that root native turn,
while each protected MCP call receives a one-time proof. Every mutating
follow-up or scheduled run must earn a fresh grant; Workbench and subagents
cannot mint or inherit one. The grant never elevates the actual Codex sandbox,
authorizes External MCP consent, touches raw credentials or protected
policy/approval/order state, publishes Git changes, or permits execution.
Codex Plan mode cannot issue or use the grant, and a grant cannot cross a
permission-mode change. A read-only turn cannot make native workspace-file
edits, though it may render/read and call the specifically proof-protected
canonical DB services. Generated Build turns admit only native `apply_patch`,
exact workspace reads/listing, a trusted workspace-launcher allowlist, and
isolated provider `py_compile`; general shell, scripts, interpreters, `pytest`,
and build/test runners are blocked. Full tests and native smokes run from an
explicit operator or maintainer terminal.
An unstarted protected-call reservation is released after two minutes so a
lost hook-to-service handoff cannot strand the turn. Once the service has
started, `Stop` or a new turn records deferred revocation and the grant becomes
terminal only after that call finishes. If a completed operation's normal
finalizer fails, an idempotent recovery finalizer never repeats the operation;
it clears the reservation and terminally revokes the grant as
`finished_unfinalized`. Persistent `tcx mode` and old
`mode.json` state are inert compatibility only. External MCP lifecycle and
consent actions require an interactive user-terminal confirmation; this
includes importing a discovered Codex entry with `tcx mcp external
import-codex`. `tcx build codex-mcp import` is a rejected migration path, not a
Build-authorized mutation. Direct terminal mutation remains a separate explicit
authority, and trusted aggregate helpers receive only its sealed service-stage
capability.

Recurring Build Automation follows the same rule on every submitted prompt:
each run needs a fresh exact marker and file-mutating work needs a
`workspace-write` runtime. A read-only run is limited to rendering/inspection
and specifically proof-protected canonical DB calls; Plan mode blocks the Build
grant entirely. Prefer an isolated worktree or workspace with a reviewable diff
for scheduled changes.

## Workbench

Workbench runs the same generated Head Manager with fixed argv, ignored user
config, read-only sandbox, stripped secret-like environment, disabled unsafe
features, and a fail-closed analysis MCP allowlist. Progress is derived from
normalized Codex JSONL events, subagent session events, and real artifacts.
Raw reasoning and tool bodies are not persisted. Preview, start, and follow-up
reject all three reserved native execution tokens and `$tcx-build` before
launching Codex.

## Validation

After harness changes:

1. attach a clean workspace and run all doctor layers;
2. inspect projected models, reasoning, sandbox, skills, and MCP allowlists;
3. verify `tools/list` contains `begin_analysis_run` and the proof-protected
   Head Manager-only `use_order_turn_grant`, excludes raw submit/cancel and
   broker-status-refresh mutations, and omits retired plan or supervisor tools;
4. run hook smokes proving exact immediate actions, all three `$tcx-order-allow`
   modes, binding/revocation/proof injection, Workbench/subagent/direct-MCP
   rejection, ordinary analysis transport behavior, and exact V2 dispatch;
5. run a real Korean request and inspect parent/child JSONL, role model, sandbox, and artifacts;
6. verify Workbench progress and synthesis lineage;
7. run focused pytest, Django check, compile, and the full suite.

See [Codex-Native Orchestration](codex-native-orchestration.md),
[Roles, Skills, And Workflows](roles-skills-and-workflows.md), and
[Safety, Policy, And Execution](safety-policy-and-execution.md).
