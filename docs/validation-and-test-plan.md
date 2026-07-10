# Validation And Test Plan

This document owns required validation commands, unit/API/generator/smoke test
coverage, and release-sensitive verification expectations.

## Default Validation

Run after source or test changes:

```bash
pytest
```

Run after Django settings, model, admin, API, MCP, or service changes:

```bash
python manage.py check
```

Run after broad Python migration, package, or import-structure changes:

```bash
python -m compileall tradingcodex_cli tradingcodex_service apps tests
```

Run after frontend or workbench UI changes:

```bash
npm ci --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
git diff --exit-code -- tradingcodex_service/static/tradingcodex_web
```

Node 22 is a maintainer build dependency only. The committed build must remain
usable from a Python wheel without Node installed.

## Unit Test Expectations

Unit tests should cover:

- policy decisions, restricted list, limits, capability checks
- order ticket checks, JSON order input validation, approval validation, execution preconditions
- order ticket creation, state transitions, check pass/warn/fail recording,
  approval readiness, exact approval-scope hash validation, broker order
  events, and fill deduplication
- approved-order idempotency and duplicate execution blocking
- broker connection defaults, broker account discovery, read-only sync runs,
  portfolio ledger event creation, snapshot materialization, and
  reconciliation summaries
- principal/capability checks before MCP handler dispatch and policy decisions
- universe routing and readiness labels
- adapter registry and disabled live adapter behavior
- audit append behavior and request/result hash generation
- file-native research artifact creation, versioning, search, source snapshot recording, and markdown export
- central DB path resolution through `TRADINGCODEX_HOME` and `TRADINGCODEX_DB_NAME`
- workspace identity/provenance recording without workspace-local DB partitioning
- duplicate research ids fail closed within a workspace unless an explicit append/version path is used
- duplicate order ids fail closed through the central runtime ledger unless an explicit idempotent path is used
- harness component registry uniqueness, dependency validity, taxonomy tag coverage, and tag filtering
- method-profile-specific ResearchSpec validation, including proof that general
  and event research do not require quant or FCFF-only fields
- evaluation-profile isolation, extension-profile pair invariants, and hard
  failure on unregistered extension use
- managed skill-layer metadata, non-implicit strategy/optional metadata,
  exact-path projection checks, immutable post-overlay instruction footers, and
  host-global same-name collision reporting
- workbench request validation rejects order drafting, approval, execution,
  cancellation, broker mutation, and secret handling before process launch
- workbench subprocess construction uses a fixed argv, `shell=False`, a vetted
  attached-workspace cwd, workspace-write, `approval_policy="never"`, disabled
  command networking/unified-exec/browser/computer/app/image features, forced
  hooks, ignored user config, full generated config/prompt/core-skill validation,
  and a stripped secret-like environment
- workbench PreToolUse fails closed, blocks shell/file/external MCP and
  connector/order/execution tools, and allows structured `record_workflow_plan`,
  `record_artifact_supervisor_loop`, and the explicit analysis-only MCP set
- workbench event normalization exposes only allowlisted redacted agent, tool,
  source, artifact, and terminal state; raw reasoning, tool payloads, stderr, and
  raw final output are neither stored nor returned
- one active process per run, stored-thread follow-up resume, missing/failed PID
  recovery, cross-worker claims, service-owned resume authority, child reaping,
  fixed 30-minute initial/resumed-run timeout, timeout event and failed metadata,
  and the documented absence of user-triggered cancellation in this slice
- preview and start use the same skill-expanded prompt, raw workflow files are
  symlink-contained/publicly projected, and final synthesis requires validated
  plan/state, head-manager binding, body hash, the complete accepted-input set,
  and a strict decision-quality pass against the recorded workflow lane
- research allowed roots reject symlinks; MCP artifact identity is transport-
  principal-bound; stage dependencies cannot be skipped; canonical state must
  match append-only event replay
- plan drafts compile against recorded intake-owned envelopes, forged rehashed
  budgets or terminal conditions fail, and concurrent plan writers leave one
  matching plan/state hash pair

## API And Admin Test Expectations

API/Admin tests should cover:

- Ninja endpoints return typed schemas and reject unauthorized calls
- harness component endpoints expose the static component registry and return 404 for unknown component ids
- Django Admin uses default admin templates, default model registration, and no custom TradingCodex admin actions/CSS/dashboard
- service-layer MCP registry, policy, and adapter helpers create audit events when called directly by supported service/API/CLI paths
- agent/skill file projection tests cover proposal files, generated manifest, and blocked risky assignments without writing skill DB or AuditEvent state
- `tcx mcp stdio` handles JSON-RPC `initialize`, `tools/list`, and `tools/call`
- MCP research tools store and retrieve workspace markdown/source-snapshot JSON through the service layer without writing research DB rows, audit rows, or tool-call ledger rows
- non-research MCP tool calls create DB ledger entries with request/result hashes
- generated `./tcx mcp ledger` can inspect the central DB tool-call ledger
- stdio bridge returns valid MCP messages and writes no non-MCP stdout
- Broker Center and order-ticket API endpoints expose read/status/draft/check
  behavior without bypassing approval or approved action gates
- workbench snapshot/detail GETs remain read-only, while only scope-preview,
  run-start, and follow-up POSTs permit valid-CSRF local-profile loopback use without staff/API
  credentials
- remote workbench POSTs still require staff/API credentials, and every other
  anonymous loopback mutation remains denied
- Django Admin continues to use default registration and templates after the
  React cutover

## Generated Workspace Smoke Tests

Run after template/bootstrap behavior changes:

```bash
SMOKE_ROOT="$(python -c 'import tempfile; print(tempfile.mkdtemp(prefix="tradingcodex-smoke-"))')"
python -m tradingcodex_cli attach "$SMOKE_ROOT/workspace"
cd "$SMOKE_ROOT/workspace"
./tcx doctor
./tcx workspace status
./tcx profile status
```

Smoke coverage should verify:

- `tcx attach` and `tcx init` create the workspace contract
- `tcx update` refreshes an existing generated workspace while preserving
  `workspace_id` and active profile
- generated workspace contains `.tradingcodex/workspace.json`
- generated workspace contains `.tradingcodex/generated/component-index.json`
- generated workspace contains no `package.json` or Node MCP/runtime files
- generated workspace contains ten fixed subagents and twenty-six protected
  bundled repo skills
- generated `.codex/config.toml` enables live web search for pristine public
  research without treating a host finance skill as a dependency
- skill/projection manifests identify the finite managed inventory, declare
  runtime discovery incomplete, and resolve exact root/role skill paths
- two generated workspaces have different workspace ids
- two generated workspaces keep separate research markdown/source-snapshot files while sharing non-research MCP ledger rows through the central DB
- profile selection controls paper portfolio separation
- all fixed-role MCP allowlists match `AGENT_SPECS` and runtime tool annotations
- root and fixed-role MCP `cwd` plus `TRADINGCODEX_WORKSPACE_ROOT` resolve from
  the launched project directory to the attached workspace, not a TOML parent
- generated hooks are callable, auto-route plain investment prompts, ignore non-investment prompts, and classify secret-warning cases
- component index matches the Python component registry

## Platform Runtime And Wheel Matrix

Focused source tests are split across `tests/test_runtime_paths.py` and
`tests/test_platform_runtime.py`. They cover macOS/Linux/Windows default-path
selection, env precedence, legacy fallback, split-home conflict, symlink/case
identity, DB override, spaces/backslashes/drive paths, typed config rendering,
both launchers, native lock/atomic behavior, process flags, and external-MCP
pipe reading.

After building a wheel, run:

```bash
python tests/platform_wheel_smoke.py --wheel-dir dist
```

GitHub Actions keeps the complete Python/Django suite on Ubuntu and runs that
same clean-wheel helper on native macOS and Windows. The helper uses
`tempfile`, a space-containing wheel path and workspace, parses root plus all
role TOML and generated YAML/JSON, runs `tcx` on POSIX or `tcx.cmd` on Windows,
executes doctor/DB/hook/MCP/external-MCP smokes, and proves local service
ensure/status/stop. It also loads `/` and the packaged
`/static/tradingcodex_web/app.js` and `app.css` from the clean wheel without
installing or invoking Node. A feature is not described as native-Windows verified until
that runner is green. Real Codex CLI E2E remains a final macOS-host check after
all non-Codex validation; the Windows matrix does not claim a real Codex client
session.

## Research Memory Smoke Tests

Run after research-memory changes:

```bash
./tcx research create
./tcx research append
./tcx research search
./tcx research export
./tcx research run-card
./tcx research validation-card
./tcx workflow improve
```

The smoke flow should confirm:

- workspace markdown artifact creation
- source/as-of metadata preservation
- version and content hash updates
- duplicate create with changed content is rejected within the same workspace
- markdown export path generation
- artifact `improvements` preview or record investment judgment improve records
- `.tradingcodex/mainagent/improve-index.json` updates incrementally alongside
  `.tradingcodex/mainagent/improve.jsonl`
- workspace provenance recording
- no raw secrets in exported output

## MCP Smoke Tests

Run after MCP registry, handler, bridge, or role allowlist changes:

```bash
./tcx mcp stdio
./tcx mcp install-global --safe --print
```

Verify at least:

- `tools/list`
- tool annotations include category, risk, role allowlist, approval requirement, and audit requirement
- research/status tools are visible to `head-manager`
- approval creation is not visible to `head-manager`
- approval creation is visible only to the approved risk role path
- experimental execution tools are visible only to `execution-operator`
- `tradingcodex-home` safe scope exposes only read-only/status/search tools
- `tradingcodex-home` safe scope may expose broker/order read-status tools
  such as `list_broker_connections`, `get_broker_connection_status`,
  `list_order_tickets`, `get_order_ticket`, and `list_reconciliation_runs`,
  but not sync, approval, submit, cancel, mapping mutation, or order-ticket
  mutation tools
- stdio emits no non-MCP logs to stdout
- external MCP discovery classifies market-data, account-read, and
  execution-like tools while keeping raw execution proxy blocked
- `./tcx mcp external list/register/check/discover/review-tool` covers External
  MCP Gate lifecycle operations
- schema drift disables reviewed tools until re-reviewed

## Broker Provider Smoke

Run after connector, broker adapter, order-ticket, approval, execution, or
policy changes. Use a disposable workspace and a disposable runtime DB; keep
credentials in process environment only. Core ships paper only, so a real broker
smoke starts by installing or developing a provider for the requested broker.
For repository validation, use the fake provider integration tests unless a
reviewed provider has been added:

```bash
SMOKE_ROOT="$(python -c 'import tempfile; print(tempfile.mkdtemp(prefix="tradingcodex-provider-"))')"
TRADINGCODEX_HOME="$SMOKE_ROOT/home" python -m tradingcodex_cli attach "$SMOKE_ROOT/workspace"
cd "$SMOKE_ROOT/workspace"
export TRADINGCODEX_HOME="$SMOKE_ROOT/home"
./tcx doctor
./tcx connectors providers
./tcx connectors connect requested-broker --provider requested-broker --credential-ref env:REQUESTED_BROKER --environment live --mode read-only
./tcx connectors scaffold requested-broker --provider requested-broker --credential-ref env:REQUESTED_BROKER --environment live
./tcx connectors validate requested-broker
python -m pytest tests/test_broker_center_prd.py -q
```

`register_broker_connector` should not by itself make a live-capable connector
execution-ready. A validation or live connector starts locked/read-only with
`credential_validation_status: not_checked`; `get_broker_connection_status` or
a successful account sync must prove signed health before validation scopes are
enabled, and live scopes require the separate live gate. If signed health fails,
the connection must remain/read back as locked with no enabled trade scopes, and
order checks or submit preflight must stop before consuming execution
idempotency. Authentication or permission failures must expose a secret-free
diagnostic in `health.details` and `metadata.credential_validation_details`.

Also verify the generated agent contract for broker-validation workflows:

```bash
./tcx doctor --layer codex-native
./tcx doctor --layer improvement
./tcx subagents status
./tcx subagents inspect execution-operator
./tcx subagents inspect risk-manager
./tcx skills list --all
printf '{"prompt":"Configure a reviewed test/sandbox broker connector, validate an approved order path, do not read secrets, and do not call broker APIs directly."}\n' \
  | ./tcx __hook user-prompt-submit
printf '{"prompt":"Configure a reviewed test or sandbox broker connector only. No order, no approval, no execution, do not read secrets."}\n' \
  | ./tcx __hook user-prompt-submit
./tcx subagents prompt "Configure a reviewed test or sandbox broker connector only. No order, no approval, no execution, do not read secrets."
```

Treat the smoke as failed if generated agent instructions hard-code one broker
as the only supported path, if `head-manager` can submit orders, if
`execution-operator` lacks `submit_approved_order`, if raw broker APIs appear in
Codex MCP config, if connector-only work dispatches fixed-role execution
subagents, or if the hook routes a secret-only prompt into execution.

## Harness And Routing Tests

Run targeted scenario tests after harness or workflow routing changes. Inspect
logs/results rather than relying only on static checks.

Scenarios should include:

- broad investment request asks for workflow confirmation or starter prompt
- explicit `$tcx-workflow` routes to the selected role team
- connector build prompts that name a provider route to `connector_build`
  and do not dispatch investment subagents
- negated execution wording such as "no order" stays out of execution routing
- guardrail-verification wording does not trigger execution
- secret-only credential, token, broker-key, password, or `.env` prompts create
  secret-wall warning context without subagent dispatch
- earnings/catalyst/valuation requests route to thesis-review style research
- vague public-equity prompts route to deep thesis review unless narrowed by
  explicit constraints such as "chart only", "company facts only", "no news",
  or "no valuation"
- fact-only and technical-only prompts keep the role team narrow and skip
  independent judgment review unless broader judgment is requested
- backtest, signal, and model-performance prompts require anti-overfit
  validation without implying strategy authoring or execution
- strategy authoring prompts route to `strategy-creator`/strategy CRUD instead
  of investment subagent auto-dispatch
- valuation plus portfolio-fit prompts include valuation before portfolio/risk
  review
- the workbench starts from natural language or a safe built-in analysis skill
  and displays selected agents, normalized tool activity, sources, artifacts,
  waiting/blocked/failed state, and the accepted final analysis
- a fake `codex` executable proves argv/cwd/environment construction, normalized
  JSONL handling, one-active-process enforcement, and stored-thread follow-up
  without network or model dependence
- workbench intake reuses answered active-profile investor context and only asks
  unanswered suitability/profile questions
- starter-prompt next allowed actions distinguish unanswered, partially
  answered, and complete active-profile investor context
- authenticated profile-answer mutations persist answers to the active profile
  and the refreshed workbench snapshot removes those questions
- Codex `UserPromptSubmit` generated hooks keep compact intake hints under
  budget; `$tcx-workflow` reuses answered active-profile investor context when
  selecting the bounded role subset that the server compiles into the
  validated staged plan
- unavailable or unverified subagent routing fails closed
- unavailable or unauthenticated Codex CLI reports a workbench run blocker
  without corrupting workflow state
- workbench requests for orders, approval, execution, cancellation, broker
  mutation, or secrets are rejected before subprocess launch
- completed role artifacts are reused when quality gates pass
- downstream roles return `revise`, `blocked`, or `waiting` instead of filling missing upstream role work
- hook `additionalContext` stays compact and points to persisted workflow
  intake instead of injecting a full starter prompt into every routed turn
- starter prompts and generated guidance expose the no-overlap handoff contract
- starter prompts and generated guidance tell subagents to write reader-facing
  research artifacts in the user's language unless explicitly overridden
- starter prompts and generated guidance tell `head-manager` to keep final chat
  brief while saving full accepted-artifact synthesis as a Markdown report under
  `trading/reports/head-manager/`
- `tcx quality-check <artifact> --strict` fails research markdown that lacks
  source/as-of posture, `context_summary`, material claim tags, handoff state,
  confidence, missing-evidence fields, next-recipient routing, blocked actions,
  or source snapshot metadata
- `tcx quality-check <artifact> --strict` validates
  `trading/forecasts/*.jsonl` forecast records and fails malformed probability
  ranges, missing resolution fields, or invalid open/closed status
- `tcx quality-check <artifact>.run-card.json --strict` validates Evidence Run
  Card config hash, input/source refs, artifact hashes, metrics or validation
  summary, warnings, limitations, timestamp, and evidence-only authority
- `tcx quality-check <artifact>.validation-card.json --strict` validates
  Validation Card evidence-quality labels, anti-overfit evidence metadata,
  artifact hashes, metrics or validation summary, warnings, limitations,
  timestamp, and evidence-only authority
- `tcx quality-check trading/research/source-snapshots/<id>.json` surfaces
  data-boundary warnings for OHLC invariants, non-positive prices, duplicate or
  sparse bars, timezone/as-of ambiguity, adjustment ambiguity, stale sources,
  invalid JSON constants, and missing fallback policy
- generated starter prompts and subagent-management skills include a context
  budget so agents pass artifact paths, context summaries, source snapshot IDs,
  and short deltas instead of full artifacts or repeated role manuals
- multi-round subagent smokes run `tcx subagents context-audit --strict` after
  several workflow intakes, subagent start/stop events, and large research
  artifacts across research-only, thesis, portfolio/risk, order-draft,
  approval/execution, crypto, ETF/index, and options/instrument lanes; the
  audit must show compact hook intake, compact intake history, compact session
  state with total counters plus retained recent events, no pasted markdown artifacts in
  intake/history/state, no research artifacts missing `context_summary`, and
  warnings for artifacts missing reader-first `reader_summary` or `next_action`
- repo skill boundary tests fail when role identifiers leak into generic skills
  outside necessary command principal examples or policy/artifact contracts
- MCP `tools/list` exposes both TradingCodex custom annotations and standard
  MCP hints such as `readOnlyHint`, `destructiveHint`, `idempotentHint`, and
  `openWorldHint`
- authenticated workbench additional-agent-instruction edits are saved as-is, projected
  after generated defaults but before the immutable core/extension footer, and
  removable without leaving stale marker blocks
- clean-host and populated-host Codex smokes compare the same pristine request;
  a host-global sentinel skill must not appear without explicit opt-in, and a
  same-name managed/global collision must fail doctor before quality claims are
  made
- a separate managed-activation smoke proves that a user-approved overlay is
  projected, attributed, non-implicit by default, and applied only when selected
- `tcx doctor --layer task-harness` is rejected; `improvement` is the canonical
  layer name in the `0.2.0` contract

Harness taxonomy checks should confirm:

- product web opens on Work and keeps Skills, Library, and System available with
  readable, sanitized artifact previews
- Guardrails are split into Guidance, Enforcement, and Information barriers
- Improvement is separate from Guardrails
- `tcx doctor --layer improvement` runs the quality/workflow checks

## Browser And Workbench Verification

After the frontend build and focused API/process tests pass, use a real browser
against `127.0.0.1:48267` and verify:

- desktop and narrow responsive layouts without hidden primary actions or
  horizontal content loss
- keyboard-only section navigation, visible focus, labeled controls, and
  logical focus after dialogs/errors
- first-run, empty library, loading, streaming/progress, waiting, blocked,
  missing-data, Codex-unavailable, failed, and completed states
- natural-language and safe built-in-skill starts, live agent/tool/source/artifact
  visibility, final forecast uncertainty, and follow-up resume
- authenticated optional-skill and strategy management plus read-only behavior
  when not authenticated
- no browser console errors, unsanitized workspace HTML, raw reasoning, raw tool
  payloads, stderr, or secrets
- Django Admin still renders and behaves as the default Admin surface

When Codex CLI and authentication are available, run one real workbench-started
analysis smoke in a disposable generated workspace. It must load the generated
`head-manager`, preserve explicit negations, dispatch only the selected team,
surface normalized progress, write accepted artifacts, and stop without an
order, approval, execution, cancellation, broker mutation, or secret action.
Record an unavailable Codex/auth blocker rather than replacing this with a
claim based only on the fake subprocess test.

## Release-Sensitive Validation

Before release or packaging changes, run:

```bash
npm ci --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
git diff --exit-code -- tradingcodex_service/static/tradingcodex_web
python -m pytest
python manage.py check
python manage.py makemigrations --check --dry-run
python -m compileall tradingcodex_cli tradingcodex_service apps tests
python -m build
python -m twine check dist/*
```

Also install the built wheel in a clean environment and run:

```bash
python tests/platform_wheel_smoke.py --wheel-dir dist
```

Detailed release workflow lives in [deployment.md](./deployment.md).
