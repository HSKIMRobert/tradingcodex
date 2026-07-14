# User-Facing Skills

TradingCodex exposes many skills internally, but users usually interact with a
small user-facing set. Primary skills start the main plane. Supporting skills
shape, automate, or review workflows without granting extra authority.

## Naming Contract

All 30 bundled TradingCodex skills use the `tcx-` namespace. Prefer one word
after the prefix and use at most two words when clarity or safety requires it,
as in `tcx-order-submit` or `tcx-investor-context`. Folder names, frontmatter
names, registry ids, projected paths, UI metadata, and explicit `$` invocations
must match exactly. Legacy built-in names are not projected as aliases.

The namespace is reserved for bundled product skills. User-owned
`strategy-*`, `investment-brain-*`, and optional role skills remain separate;
an optional skill cannot claim a `tcx-*` id.

## Primary Entrypoints

| Skill | Primary use | Main output |
| --- | --- | --- |
| `tcx-workflow` | Investment research, thesis review, Decision Packages, portfolio fit, risk review, or order-readiness coordination. | Dynamic exact-role evidence gathering, authenticated artifact synthesis, waiting/revise/blocked state, or Decision Package. |
| `tcx-memory` | Retrieve prior decisions, replay an historical decision with point-in-time evidence, compare outcomes, or validate a lesson. | Source-bound episodes, replay/review artifacts, lesson status, evidence tier, and next validation needed. |
| `tcx-strategy` | Design reusable user strategy skills; durable create, update, activate, archive, or delete runs only in a new exact `$tcx-build` root turn. | Validated strategy skill with required sections, status, projection metadata, and user approval posture. |
| `tcx-brain-create` | Curate a user-owned local Brain from user-selected Decision Memory evidence, counterexamples, validated lessons, or an explicit philosophy. | Privacy-reviewed local source bundle and abstraction summary; no install, activation, or Git/publication action. |
| `tcx-server` | Workbench/service health, `doctor`, update status, MCP readiness, DB path checks, and startup recovery. | Runtime status, recovery command, workbench URL, update guidance, or blocker reason. |
| `tcx-build` | Explicit current-turn workspace refresh, managed optional skill, Strategy, or Investment Brain lifecycle work, workspace MCP configuration, and connector/provider development. | Validated managed state or connector files, provider metadata, focused validation, reviewable diff, or an exact operator-terminal next step. |
| `tcx-order-allow` | Explicitly admit at most one approved submit or cancel later in the current root native Codex turn, including a Codex app Scheduled Task turn. | A mode-bound, single-use `OrderTurnGrant`; no immediate broker effect. |
| `tcx-order-submit` | Explicitly submit one already-approved order from a root native Codex workspace turn. | Redacted accepted, rejected, duplicate, or needs-review service result. |
| `tcx-order-cancel` | Explicitly cancel one known submitted broker order from a root native Codex workspace turn. | Redacted canceled, rejected, duplicate, or needs-review service result. |

## Supporting User Skills

| Skill | Primary use | Main output |
| --- | --- | --- |
| `tcx-plan` | Clarify scope, constraints, action boundaries, and stop conditions before an immediate or recurring task. | Compact user mandate and missing-field or blocked posture; never a server dispatch plan or selected team. |
| `tcx-automate` | Create or update Codex app Scheduled Tasks for simple research, monitoring, recurring analysis, portfolio/status review, order drafting, assisted execution, optional turn-authorized execution, or explicitly delegated turn-authorized Build work. | Schedule plus a durable runtime prompt that invokes the actual work skill, not `tcx-automate` recursively. |
| `tcx-investor-context` | Interview and preview workspace suitability context; persistent status/update/enable/disable/clear is handed to an explicit user-terminal command. | User-confirmed proposed values, exact terminal action, default application state, and remaining gaps. |

## Entrypoint Rules

`tcx-workflow` is the default for investment-facing natural-language prompts.
For ordinary workflow requests, the hook supplies transport/run context only.
`head-manager` interprets the request directly, begins a lightweight run,
dynamically selects/revises the smallest useful fixed-role team, and synthesizes
authenticated artifacts. The separate literal native-action protocol is
described below. Head Manager should not produce substantive investment analysis
before role artifacts exist.

`tcx-strategy` handles strategy authoring as durable user rules, not live
market analysis. A strategy can guide future workflows, but it does not approve
orders, grant broker authority, mutate policy, or execute trades. Durable
create, update, activate, archive, and delete requests start a new root native
turn with exact first line `$tcx-build`; the Build turn stages the standalone
body and calls the managed Strategy lifecycle service. It does not directly
repair generated skill folders, fixed-role TOML, or root projection blocks.

`tcx-brain-create` handles only an explicit user-owned authoring task in a root
native turn whose exact first line is `$tcx-build`. The actual Codex sandbox
must permit the required workspace-local writes. The user selects the exact
memory evidence and counterexamples. The skill performs privacy review, abstracts
general heuristics without copying private cases, and writes a local source
under `investment-brains/<investment-brain-id>` by default. It never edits
managed packages or third-party sources, and it stops before install,
activation, staging, commit, push, publication, or pull request.

Native workflow strategy selection requires exactly one explicit
`$strategy-*` invocation. Plain-language mentions never select a strategy, and
absence records `no_strategy`; Workbench uses its structured strategy selector.
Either path validates and seals the active strategy into the protected run.

`tcx-memory` is an explicit retrieval, replay, review, and lesson-validation
entrypoint. For a current judgment it records the independent initial view
before introducing past cases. Wiki and graph outputs are rebuildable views;
canonical evidence remains in source snapshots, decision packages, forecast
events, and review artifacts. Use structured MCP for supported research,
replay, forecast, and authenticated lesson-review state. A decision snapshot or
postmortem lifecycle action without a projected structured tool is returned as
an exact explicit maintainer/user-terminal command; it is never smuggled
through the general model shell.

`tcx-investor-context` interviews and previews only the optional
workspace-local suitability file in the Codex turn. Persistent status, update,
enable, disable, or clear is performed by the user with the exact interactive
terminal command returned after confirmation; the skill does not bypass the
Build shell gate. Its persistent enable/disable state is separate from skill availability,
strategy rules, and internal paper account scope. It does not run investment
analysis or grant authority. Native run binding follows the saved workspace default;
only Workbench offers a one-run apply/ignore control, and that bound choice does
not rewrite the file.

`tcx-server` handles operations. It can explain service state, local workbench
readiness, update posture, MCP configuration, and recovery steps. It should not
be used to perform investment judgment or connector implementation. It reads
hook startup context and the read-only status/update MCP tools. Service,
`doctor`, update, or recovery commands that require the launcher are returned
as explicit user-terminal steps instead of being run through the model shell.

`tcx-build` handles product/build-plane work. The root native prompt must have
the exact physical first line `$tcx-build`, followed by a non-empty concrete
request. The deterministic hook issues a DB-canonical grant bound to that
workspace, session, turn, cwd, and complete prompt. The grant is multi-use only
within that turn; every mutating follow-up needs the marker again, and Workbench
and subagents cannot create or inherit it. The marker is intent, not permission:
the actual Codex sandbox remains authoritative and a read-only runtime cannot
make native workspace-file edits. It may still render/read and use the
specifically proof-protected canonical DB calls because those writes remain
service-owned. `workspace-write` is the preferred least-privilege setting for
ordinary file-editing Build work. Codex Plan mode cannot issue or use the grant, and a
permission-mode change requires a fresh root turn. Generated Build work uses
native `apply_patch`, exact workspace reads/listing, trusted launcher commands,
and isolated provider `py_compile`; general shell, scripts, interpreters,
`pytest`, and build/test runners are blocked. Full validation belongs in an
explicit operator or maintainer terminal. Generated core harness files, hooks,
templates, fixed-role configuration, and service-owned projection blocks are
not direct Build edit targets. Brain management always uses an explicit
workspace-local source or public credential-free HTTPS Git source and
never implies global config, raw credential access, External MCP lifecycle or consent,
source-repository or Git-publication actions. It may create live-capable
provider code, but the user must approve the exact provider bundle hash in an
interactive terminal before the service may load its immutable snapshot. Live execution still
remains behind service-layer approval, policy, connection, confirmation,
idempotency, sync, and audit gates.

Persistent `tcx mode` is retired. Its compatibility status is inert, old
`.tradingcodex/runtime/mode.json` state is ignored, and `tcx mode set ...`
cannot enable Build. External MCP lifecycle/consent and provider-source approval
are separate interactive user-terminal operator actions; user-terminal CLI
mutations remain separate operator authority.

`tcx-order-submit` and `tcx-order-cancel` are native-only exact
action protocols, not model procedures. Their bundles disable implicit
invocation and carry no MCP authority. The entire root user prompt must match
the documented `--name value` grammar; the deterministic `UserPromptSubmit`
hook parses it and invokes the canonical service gateway before a model runs.
They are unavailable from Plan mode, Workbench, and subagents. Public/raw MCP,
REST, and generic CLI surfaces cannot perform these final mutations; the
separately protected grant consumer is inert without current hook proof.

`tcx-order-allow` is the explicit-only current-turn alternative for workflows that
do not have final ticket identifiers when the prompt begins. The physical first
line must be exactly one of:

```text
$tcx-order-allow --mode paper
$tcx-order-allow --mode validation
$tcx-order-allow --mode live
```

The hook issues an `OrderTurnGrant` bound to workspace, session, turn, complete
prompt hash, Codex permission mode, and execution mode. Plan mode rejects grant
issuance and use. The grant is usable for one submit or cancel, expires after
one hour, and is revoked on `Stop`, the next user turn, or consumption. It
grants no approval and performs no immediate action. Only root Head Manager can
call `use_order_turn_grant`; `PreToolUse` injects the internal proof, so
Workbench, subagents, and direct MCP callers have no authority.
If a consumed grant is still `authorizing`, Stop and new-turn cleanup do not
reset it. The same session blocks a new Build or order-sensitive prompt until
the canonical result is terminal; status inspection and ordinary research may
continue without retrying the effect.

`tcx-automate` authors the Codex app Scheduled Task. The app submits the
saved prompt on each scheduled turn, and TradingCodex treats it like any other
root prompt rather than detecting an Automation origin. Ordinary research,
monitoring, analysis, portfolio/status, draft, and assisted-execution prompts
must omit both authority markers. Only optional final execution uses the exact
`$tcx-order-allow` first line above. Only deliberately delegated recurring
workspace-local Build work uses the exact standalone first line `$tcx-build`,
with the concrete build request below it. Each scheduled run receives a fresh
current-turn grant decision and remains subject to that run's actual Codex
sandbox. File-mutating recurring Build work needs a `workspace-write` runtime;
a read-only run is limited to rendering/inspection and specifically
proof-protected canonical DB calls, while Plan mode blocks Build entirely.
Prefer an isolated worktree or workspace and retain a reviewable diff for
scheduled changes. Never combine `$tcx-build` with `$tcx-order-allow`. The saved prompt
invokes `$tcx-workflow` or the selected work skill; it must not invoke
`$tcx-automate` again.

The exact mode is a ceiling, not deterministic interpretation of the remaining
prose. Canonical policy, ticket, receipt, action, broker state, and mode are
service-enforced. Natural-language symbol, notional, schedule, or strategy
limits are enforceable only after they exist in canonical state.

`tcx-plan`, `tcx-automate`, and `tcx-investor-context` are user-facing
support skills. A `tcx-plan` mandate preserves scope but does not choose
roles; Head Manager still decides and revises the smallest useful team from the
live task and accepted evidence. Decision Memory owns postmortem and lesson-review
requests. None replaces `tcx-workflow` as the normal investment-dispatch
entrypoint.

## Role-Owned Skills

Role-owned subagent skills such as `tcx-judgment`,
`tcx-fundamental`, or `tcx-portfolio` belong to fixed-role dispatch.
Users normally reach them through `tcx-workflow`, not by calling the role skill
directly. The retired `execute-paper-order` role skill has no compatibility
alias; use the exact root-native action above.
