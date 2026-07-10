# Interfaces And Data

Use this page before changing Web, Admin, API, MCP, CLI command behavior, model ownership, research or decision memory, investor context, or data flow. Human-facing detail lives in [docs/interfaces-and-surfaces.md](../docs/interfaces-and-surfaces.md), [docs/system-architecture.md](../docs/system-architecture.md), [docs/research-memory-and-artifacts.md](../docs/research-memory-and-artifacts.md), and [docs/decision-memory.md](../docs/decision-memory.md).

## Interface Rule

Every interface is a caller of the service layer. No interface should create a parallel policy, order, approval, execution, portfolio, broker, research, or audit path.

| Surface | Main files | Boundary |
| --- | --- | --- |
| Product web | `frontend/*`, `tradingcodex_service/static/tradingcodex_web/*`, `tradingcodex_service/web.py`, `tradingcodex_service/workbench_api.py`, `tradingcodex_service/application/workbench.py` | Skill-first Work/Skills/Library/System SPA. Starts or follows one bounded analysis-only Codex run through the same generated head-manager; never directly selects roles or widens approval/execution authority. |
| Django Admin | `apps/*/admin.py` | Local/staff DB inspection. No custom bypass path. |
| Ninja API | `tradingcodex_service/api.py` | Typed local/staff control endpoints that call services. |
| MCP | `tradingcodex_service/mcp_runtime.py` | Role-scoped approved action boundary for agents. No raw REST or broker proxy. |
| CLI | `tradingcodex_cli/commands/*` | Operator and generated-wrapper interface. Should call services. |

Build customization surfaces live in the same service-layer rule:
`/build/` and `tcx build ...` summarize Codex config discovery, managed MCP
config writes, optional skills, additional instructions, and pending external
MCP permissions without creating a parallel MCP registry.

Workbench API:

- `GET /api/workbench/` returns the canonical `{generated_at, sections}`
  snapshot; each section is exactly `{ok, data}` or `{ok, error}`. Skill,
  artifact, and run detail endpoints return their canonical resource shapes.
- `POST /api/workbench/preview/` returns the same skill-expanded scope used by
  start without persisting intake state or launching Codex.
- `POST /api/workbench/runs/` starts one analysis-only `codex exec` process.
- `POST /api/workbench/runs/{run_id}/follow-up/` resumes its stored Codex thread.
- Only those three POSTs have the narrow local-profile exception: valid-CSRF
  loopback may use them without staff/API-key authentication. Remote always
  requires authentication, and every other mutation is unchanged.
- Fixed argv, `shell=False`, vetted attached-workspace cwd, workspace-write,
  `approval_policy="never"`, disabled command networking and interactive action
  features, ignored user config, exact generated runtime checks, a fail-closed
  analysis MCP/tool allowlist, stripped secret-like environment, and one active
  process per run are required. Head Manager submits selected roles; the service
  builds the stage DAG and policy-owned fields through the structured
  `record_workflow_plan` and `record_artifact_supervisor_loop` services. Each
  process has a fixed 30-minute elapsed timeout; no user-triggered web cancel is
  exposed.
- Persist/return only normalized, redacted, allowlisted events—never raw
  reasoning, tool inputs/outputs, stderr, or raw final output.
- Public run state rejects symlink escapes and projects an allowlisted schema;
  final synthesis also requires validated plan/state, complete input hashes, and
  a strict decision-quality pass evaluated against the recorded workflow lane.

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
- `*.run-card.json` beside research, report, decision, order, or approval artifacts
- `*.validation-card.json` beside research, report, decision, order, or approval artifacts
- `trading/forecasts/forecast-ledger.jsonl`
- `trading/decisions/*.md` and `trading/decisions/*.decision-snapshot.json`
- `trading/reports/postmortem/*.postmortem_report.json`
- `trading/evaluations/{corpora,runs,blind-review-assignments,blind-reviews,comparisons}/*.json`

Research service calls may index, validate, search, preview, version, and write
these files, but the markdown, JSON, or JSONL file is the source of truth.
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
- orders: `OrderTicket`, `OrderCheckRun`, `ApprovalReceipt`, `ExecutionResult`, `OrderEvent`, `BrokerOrder`, `Fill`
- portfolio: `PortfolioSnapshot`, `Position`, `CashBalance`, `PortfolioLedgerEvent`, `BrokerSyncRun`, `ReconciliationRun`
- integrations: `AdapterDefinition`, `BrokerConnection`, `BrokerAccount`, `InstrumentMap`
- workflows: `WorkflowRun`, `ArtifactRef`
- MCP: tool definitions/calls and external MCP registry/review/call models
- harness: `WorkspaceContext`
- audit: `AuditEvent`

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
