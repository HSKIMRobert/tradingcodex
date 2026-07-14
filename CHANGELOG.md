# Changelog

## Unreleased

- Move all 30 bundled skills into the reserved compact `tcx-` namespace, with
  one suffix word preferred and two allowed only for clarity. User-owned
  `strategy-*`, `investment-brain-*`, and optional role skill namespaces stay
  separate, and unchanged retired generated files migrate on `tcx update`.
- Remove the `execution-operator` fixed role and retired
  `execute-paper-order` skill from generated workspaces.
- Add explicit-only root-native `tcx-order-submit` and
  `tcx-order-cancel` action bundles. Their exact full-prompt grammar is
  parsed by `UserPromptSubmit` and dispatched in-process to the canonical
  service gateway as a workspace-bound `native-user` mandate before any model
  runs.
- Expand `tcx-automate` into the authoring path for all Codex app
  Scheduled Tasks, including simple research, monitoring, recurring analysis,
  portfolio/status review, draft orders, assisted execution, and optional
  turn-authorized execution. Saved prompts run on every scheduled turn and
  invoke the actual work skill rather than `tcx-automate` recursively.
- Retire persistent Build mode. Only an exact root first line `$tcx-build`
  creates a current-turn, workspace/session/turn-bound Build grant; Plan mode
  is rejected and the marker never elevates Codex's filesystem sandbox.
  Generated Build turns use native `apply_patch`, a narrow command lane, and
  hook-owned one-time proofs for canonical connector DB changes.
- Route managed Strategy authoring through the same exact Build-turn skill,
  hook, and lifecycle-service boundary; direct generated skill/projection edits
  are no longer the native Codex UX. General server, Investor Context, and
  unsupported Decision Memory lifecycle commands now return explicit
  user-terminal handoffs instead of attempting a blocked model shell.
- Replace agent-side connector `connect`/write-style scaffold MCP operations
  with read-only, content-addressed scaffold rendering plus native patching.
  External MCP lifecycle/consent and provider-source approval remain
  interactive operator actions protected by one-use service capabilities.
- Add the explicit-only `tcx-order-allow` bundle and `OrderTurnGrant`: only a
  physical first line `$tcx-order-allow --mode paper|validation|live` can admit one
  later submit or cancel in that root turn. Grants bind workspace, session,
  turn, full prompt hash, and mode; expire after one hour; and are revoked on
  `Stop`, the next turn, or consumption.
- Add Head Manager-only `use_order_turn_grant`. `PreToolUse` reserves the grant
  and injects internal proof, so Workbench, subagents, direct MCP, REST, and CLI
  callers gain no execution authority. The service still enforces canonical
  ticket, receipt, policy, mode, live-confirmation, idempotency, adapter, audit,
  reconciliation, and uncertainty gates; free-form prompt scope is not claimed
  as deterministic policy.
- Keep a consumed `authorizing` order effect immutable while its broker result
  is in flight. Stop/new-turn cleanup never resets it, and the same session
  blocks new Build/order-sensitive prompts until terminal while ordinary
  research remains available.
- Increase the bundled core skill count from 29 to 30 without adding an
  execution subagent.
- Remove final submit, cancel, and broker-status-refresh mutations from public
  MCP, REST, generic CLI guidance, and Workbench while preserving the existing
  policy, approval, live-confirmation, idempotency, adapter, audit,
  reconciliation, and uncertain-result gates.
- Reduce the fixed subagent roster to nine and keep Workbench preview, start,
  and follow-up strictly analysis-only by rejecting reserved native action
  tokens before launch.
- Require the canonical TradingCodex MCP for Head Manager and every fixed role,
  make Workbench apply an isolated canonical project-trust override, and fail
  launch instead of silently continuing without service authority. Native
  dispatch audit now records exact role/fork/task plus child-brief hash and
  size, never the brief body.

## 1.0.0 - 2026-07-13

- Establish the first supported TradingCodex public contract across the CLI,
  Django service, MCP gateway, React workbench, and generated workspaces.
- Start from clean v1 workspace, runtime-home, database, migration, policy,
  approval, audit, research, forecast, and execution boundaries.
- Make Codex Head Manager the dynamic research orchestrator, with no semantic
  hook router, server-generated DAG, default analyst team, or Django workflow
  state machine. MultiAgent V2 projects Sol/xhigh for Head Manager and
  Terra/high for analytical roles, with Terra/low for execution.
- Add explicit, workspace-file-native Investment Brain plugins with strict
  local/Git installation, immutable versions, Head Manager-only projection,
  lazy sealed references, rollback, collision checks, and run provenance.
- Add the user-owned `tcx-brain-create` path while keeping Strategy, Investor
  Context, Decision Memory, current evidence, and Core safety as distinct
  authority layers.
- Authenticate run-bound research artifacts and synthesis inputs with
  service-issued receipts, external signing-key custody, source snapshots, and
  exact Brain/Strategy/Context lineage.
- Enforce V2 spawn-field allowlists, source-snapshot knowledge cutoffs,
  no-future artifact time bounds, and strict claim tagging for Head Manager
  synthesis.
- Initialize generated workspaces as local Git worktrees without staging,
  commits, remotes, or publication, and require the private runtime home to
  remain outside the versionable workspace.
- Serve the committed React workbench through content-hashed deterministic
  assets so package updates cannot leave a browser on a stale bundle.
- Ship manual, tag-bound PyPI publishing with one verified wheel and source
  distribution reused across Ubuntu, macOS, Windows, and publication jobs.
- Support forward package, generated-workspace, and Django schema updates within
  the v1 line while rejecting prerelease compatibility and downgrade paths.
