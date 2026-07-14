# Interfaces And Data

Use this page before changing Web, Admin, API, MCP, CLI command behavior, model ownership, research or decision memory, investor context, or data flow. Human-facing detail lives in [docs/interfaces-and-surfaces.md](../docs/interfaces-and-surfaces.md), [docs/system-architecture.md](../docs/system-architecture.md), [docs/research-memory-and-artifacts.md](../docs/research-memory-and-artifacts.md), and [docs/decision-memory.md](../docs/decision-memory.md).

## Interface Rule

Every interface is a caller of the service layer. No interface should create a parallel policy, order, approval, execution, portfolio, broker, research, or audit path.

| Surface | Main files | Boundary |
| --- | --- | --- |
| Product web | `frontend/*`, `tradingcodex_service/static/tradingcodex_web/*`, `tradingcodex_service/web.py`, `tradingcodex_service/workbench_api.py`, `tradingcodex_service/application/workbench.py` | Work/Approaches/Research plus lower-emphasis Settings, preserving `#/work`, `#/skills`, `#/library`, and `#/system`. Compose and selected-run modes are exclusive; verified synthesis precedes collapsed diagnostics. Starts or follows one bounded analysis-only Codex run through the same generated head-manager; never directly selects roles or widens approval/execution authority. |
| Django Admin | `apps/*/admin.py` | Local/staff DB inspection. Order/execution ledgers and external MCP router launch configuration are read-only; no custom bypass path. |
| Ninja API | `tradingcodex_service/api.py` | Typed local/staff control endpoints that call services; no final execution mutation route. |
| MCP | `tradingcodex_service/mcp_runtime.py` | Role-scoped research, preparation, approval, status, and proof-protected Build services. Root Head Manager alone also sees `use_order_turn_grant`, which is inert without current hook proof; no raw submit/cancel/refresh mutation, REST mirror, or broker proxy. |
| Root native action hook | `workspace_templates/modules/codex-base/files/.codex/hooks/tradingcodex_hook.py`, `application/execution_gateway.py`, `application/build_gateway.py` | Exact immediate user submit/cancel plus exact-first-line `$tcx-order-allow` and `$tcx-build` admission, revocation, and proof injection. |
| CLI | `tradingcodex_cli/commands/*` | Operator and generated-wrapper interface. Should call services. |

Build customization surfaces live in the same service-layer rule:
`/build/` and `tcx build ...` summarize Codex config discovery, managed MCP
config writes, optional skills, additional instructions, and pending external
MCP permissions without creating a parallel MCP registry.
Codex-originated mutations require an exact `$tcx-build` current-turn grant and
the actual sandbox still decides whether writes are possible. External MCP
consent moved to the explicit operator command `tcx mcp permission`; direct
terminal mutation remains separate operator authority.

Unsafe Ninja requests authenticated by a staff cookie require CSRF. API-key
requests do not, but role-authored mutations use the canonical MCP tool
allowlist, active-principal, capability, schema, and transport-identity checks.
Staff-only overlay administration remains distinct and never grants an agent
role to an arbitrary staff username, including one that collides with a
canonical agent principal id. Role-authored mutations require an API-key-bound
principal.

Workbench API:

- `GET /api/workbench/` returns the canonical `{generated_at, sections}`
  snapshot; each section is exactly `{ok, data}` or `{ok, error}`. Skill,
  artifact, and run detail endpoints return their canonical resource shapes.
- `POST /api/workbench/preview/` returns the same skill-expanded scope used by
  start without persisting an analysis run or launching Codex.
- `POST /api/workbench/runs/` starts one analysis-only `codex exec` process.
- `POST /api/workbench/runs/{run_id}/follow-up/` resumes its stored Codex thread.
- All three mutations accept `prompt` as the sole request-text field, omit empty
  optional selections, and reject unknown fields.
- Preview, start, and follow-up reject all three reserved native execution
  tokens; the action skills are native-only and never startable from Workbench.
- An explicit or session-bound workspace id must resolve to a registered current
  v1 workspace. Invalid selections fail instead of falling back to the default.
- Only those three POSTs have the narrow local-profile exception: valid-CSRF
  loopback may use them without staff/API-key authentication. Remote always
  requires authentication, and every other mutation is unchanged.
- Fixed argv, `shell=False`, vetted attached-workspace cwd, a project-wide
  read-only filesystem sandbox, `approval_policy="never"`, disabled command
  networking and interactive action features, ignored user config, exact
  generated runtime checks, a fail-closed analysis MCP/tool allowlist, stripped
  secret-like environment, and one active process per run are required. The
  same sandbox applies to Head Manager and fixed roles, while authenticated
  service/MCP tools own durable writes. Head Manager interprets the request and
  dynamically chooses/revises exact roles. `begin_analysis_run` stores only
  request hash/size and sealed provenance. Fixed-role producers call
  `create_research_artifact` with the run id and exact consumed
  `input_artifact_ids`; the service owns principal, producer, schema, content,
  and lineage hashes. Each
  process has a fixed 30-minute elapsed timeout; no user-triggered web cancel is
  exposed.
- Children and Head Manager retrieve exact returned bodies by artifact id
  through authenticated `get_research_artifact`. Head Manager synthesis must
  name at least one verified run-local input artifact; shell/glob discovery is
  outside the runtime contract.
- Each run-bound write receives an HMAC-authenticated service receipt that
  binds the workspace id, run record, regular non-symlink artifact file/body,
  authenticated producer, exact input ids/hashes/versions, and sealed
  Brain/Strategy/Investor Context lineage. Synthesis, forecasts, and Decision
  Memory reverify it; caller-authored metadata and plain recomputed hashes are
  not provenance. The global-state signing key is installation-local:
  missing/replaced keys and workspace-only clones fail verification and are
  never silently re-keyed or re-signed. Forecasts derive a Markdown origin's
  recorded run id when the caller omits the redundant argument.
- A run-bound write validates intended bytes and commits its receipt under the
  research lock before atomically replacing the stable pointer. Normal failure
  rolls back the receipt/new archive and leaves stable/index state unchanged;
  a process death can leave only a harmless unpublished future receipt/archive.
- A run-bound append revalidates the current receipt plus recursive inputs and
  source snapshots both before and inside the research lock, then rechecks the
  current full-file hash. Artifact ids stay pinned to their canonical paths:
  append path declarations must match exactly, and create cannot relocate an
  existing id or overwrite a destination occupied by another artifact. These
  checks fail before artifact/index/receipt mutation and repeat under the lock.
  Version archives and ancestors must be symlink-free;
  pre-existing archives must be regular files with exact prior stable bytes.
  Downstream verification uses receipt-sealed input versions to resolve and
  recursively authenticate historical archives after an upstream advances.
- A producing role calls `record_source_snapshot` before artifact storage when
  reproducibility requires one and uses only the exact returned `snapshot_id`;
  invented/missing ids fail closed, while no recorded snapshot means an empty
  `source_snapshot_ids` list plus explicit locator/retrieval/coverage posture.
  Normal agent calls omit service-owned `snapshot_id`, `retrieved_at`, and
  `recorded_at`; the service derives safe receipt times and a bounded ID.
  `known_at` is supplied only when genuinely known and timezone-qualified.
- Persist/return only normalized, redacted, allowlisted events—never raw
  reasoning, tool inputs/outputs, stderr, or raw final output.
- Present only evidence-derived progress phases. The client must not manufacture
  a DAG, percent complete, predefined role team, or assignment rationale absent
  from the public projection. Narrow layouts use list-or-detail navigation for
  Research and Approaches instead of stacking both panes.
- Public run state rejects symlink escapes and projects an allowlisted schema;
  final synthesis also requires sealed run lineage, authenticated artifact
  receipts, complete input and body hashes, accepted handoff readiness, and the
  applicable strict quality gate.

## Research Memory

Research is workspace-file-native. Canonical files:

- `trading/research/*.md`
- `trading/research/*.evidence.md`
- `trading/reports/<role>/*.md`
- `trading/research/source-snapshots/*.json`
- `trading/research/specs/*.json`
- `trading/research/replay-manifests/*.json`
- `trading/research/experiments/*.json`
- `trading/research/analyses/*.json`
- `trading/research/judgment-priors/*.json` and `judgment-reviews/*.json`
- `*.run-card.json` beside research, report, or decision artifacts
- `*.validation-card.json` beside research, report, or decision artifacts
- `trading/forecasts/forecast-ledger.jsonl`
- `trading/decisions/*.md` and `trading/decisions/*.decision-snapshot.json`
- `trading/reports/postmortem/*.postmortem_report.json`
- `trading/evaluations/{corpora,runs,blind-review-assignments,blind-reviews,comparisons}/*.json`

Research service calls may index, validate, search, preview, version, and write
these files, but the markdown, JSON, or JSONL file is the source of truth.
Input markdown staged under `trading/research/.drafts/` is excluded from the
index until `research create` writes a canonical artifact. Indexed markdown
requires explicit `artifact_id`, `artifact_type`, and `universe`; path-based
identity inference is not part of v1. Markdown run/validation cards use their
own validators and are not research-index entries.
Order tickets, approval receipts, order-turn grants, broker orders, fills, and
execution state are central-DB records accessed through canonical services, not
research artifacts. Final submit/cancel enters through either a parser-issued
immediate root-native mandate or a current `$tcx-order-allow` grant reserved and
proven by `PreToolUse`. Public REST and generic CLI expose
read/preparation/status surfaces only; direct MCP calls cannot use the protected
grant consumer without current hook proof.
Forecast resolution is independent from forecast authorship; causal analysis
loads numeric inputs only from a hash-verified replay snapshot; paired model
evaluation remains research-only and cannot promote itself into order or
execution authority. Research MCP calls intentionally skip DB tool-call ledger
rows.

Wiki pages, temporal or claim graphs, similarity links, and dashboards are
rebuildable read projections. Historical replay, historical holdout, and live
forward evidence are distinct. The optional investor suitability file lives at
`.tradingcodex/user/investor-context.md`; internal paper account scope remains
separate and execution-sensitive state stays in the central DB.
Harness/API projections expose it only as `investor_context` and read only the
canonical snake_case keys stored in that file.

ResearchSpec is profile-based: `general_evidence_v1`, `event_research_v1`,
`quant_signal_v1`, and `listed_equity_fcff_dcf_v1` add only method-appropriate
requirements. Evaluation corpora bind `core_investment_v1` or a bounded
corpus-declared profile; paired runs also bind an extension-profile hash and
map reported unregistered extension use to a hard failure. Current run digests
and check outcomes are caller-attested, so comparisons force `hold` until a
trusted evaluation runner verifies provenance. Do not infer a universal quant
or FCFF contract from one profile.

## Central DB Data

Central DB model families:

- policy: `Principal`, `Capability`, `RestrictedSymbol`, `PolicyDecision`
- orders and native grants: `OrderTicket`, `OrderCheckRun`, `ApprovalReceipt`,
  `OrderTurnGrant`, `BuildTurnGrant`, `ExecutionResult`, `OrderEvent`,
  `BrokerOrder`, `Fill`
- portfolio: `PortfolioSnapshot`, `Position`, `CashBalance`, `PortfolioLedgerEvent`, `BrokerSyncRun`, `ReconciliationRun`
- integrations: `AdapterDefinition`, `BrokerConnection`, `BrokerAccount`, `InstrumentMap`
- MCP: tool definitions/calls and external MCP registry/review/call models
- harness: `WorkspaceContext`
- audit: `AuditEvent`

`BrokerConnection` owns the required canonical `provider_id` and transport.
Paper is `paper` / `paper`, External MCP is `external-mcp` / `mcp`, and
registered native providers use their exact lowercase connector-safe provider
id with `api`; mismatched
identity/transport pairs fail closed and no `adapter_type` alias exists.

## Edit Checklist

When changing this area:

- put durable behavior in `tradingcodex_service/application/*`
- update `docs/interfaces-and-surfaces.md` for user/admin/API/MCP/CLI behavior changes
- update `docs/system-architecture.md` for app/model/service ownership changes
- update `docs/research-memory-and-artifacts.md` for research file contracts
- run focused tests plus `python manage.py check` for Django surface changes
- run frontend test/build plus desktop, narrow, keyboard, and error-state browser
  checks for workbench changes
- run MCP smoke for MCP registry, handler, bridge, or role allowlist changes
