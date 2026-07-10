# Safety And Execution

Use this page before changing policy, permissions, approvals, broker connectors, order tickets, execution, workbench process/auth boundaries, external MCP, secret handling, or audit. Human-facing rules live in [docs/safety-policy-and-execution.md](../docs/safety-policy-and-execution.md) and [docs/guardrails.md](../docs/guardrails.md).

## Approved Action Boundary

Every executable action follows:

```text
requester -> transport identity -> permission -> policy -> payload validation
  -> canonical approval -> idempotency/effect reservation -> mandatory intent audit
  -> connection -> mandatory finalized/uncertain audit
```

Policy and approval are revalidated immediately before connection use.
Submission and live cancellation reserve the external effect before provider
invocation. A provider exception or local-finalization failure moves the ticket
to `NEEDS_REVIEW` with correlation metadata and blocks blind retry. Broker/API/MCP
connection invocation is owned by the Django service layer.

## Order And Execution Rules

`OrderTicket` is the canonical workflow root for draft, check, approval, submission, cancellation, refresh, and inspection. CLI, API, and MCP actions address central DB tickets.

Supported lifecycle:

```text
DRAFT -> PRECHECKED -> READY_FOR_APPROVAL -> APPROVED -> RESERVED
  -> SUBMITTED -> ACKED -> PARTIALLY_FILLED -> FILLED
```

Terminal or review states are `REJECTED`, `CANCELED`, `EXPIRED`, `FAILED`, and `NEEDS_REVIEW`.

Approved execution is idempotent by `portfolio_id`, `account_id`, and
`strategy_id`. Native/base currency, point-in-time FX snapshot identity, and
versioned portfolio compare-and-swap state are part of the money contract. The
active profile selects a validated three-letter base currency; policy compares
only converted base notional and requires FX evidence for any different native
currency. Internal service money uses fixed six-decimal precision and requires
explicit currency codes at ambiguous natural-language or external-connector
boundaries. Shipped migration files keep legacy currency labels only for safe
upgrade; forward migrations own current defaults and semantic backfill.
Duplicate approved-order submission or uncertain cancellation retry must fail
before connection use.

## Required Blocks

TradingCodex must block direct live broker requests, raw external broker/execution/secret/policy proxies, self-issued approvals, non-risk-role approvals, restricted-symbol orders, approval hash mismatches, expired approvals, over-scope submissions, duplicate submissions, duplicate order ids with different payloads, global exposure of approval/execution tools, raw secrets in outputs, and live execution when any live gate is missing.

Workbench initial/follow-up requests must also reject order drafting, approval,
execution, cancellation, broker mutation, and secret handling before starting
Codex.

## Broker And External MCP Posture

Core ships paper by default. Broker connections start disabled or read-only except the built-in paper adapter. Provider adapters become execution-ready only after provider metadata, signed health, policy/config gates, approval hash, idempotency, explicit confirmation, sync, and audit gates pass.

External MCP servers enter through TradingCodex's External MCP Gate. Unknown tools are disabled until classified. Secret and policy/admin tools are not proxyable. Execution tools cannot use direct raw proxy and must map to the approved service-layer connection path.

External MCP user-consent prompts become `McpExternalPermissionRequest` rows.
The coordinator should surface `approval_required` as
`waiting_for_user_permission`; subagents do not continue with buried permission
prompts.

## Secret Wall

Raw broker API keys, tokens, account credentials, and secrets must not appear in repository files, generated workspace files, prompts, shell output, product web, Admin exports, API responses, MCP responses, audit payloads, starter prompts, generated docs, or research artifacts.

## Workbench Process Boundary

Only the CSRF-protected scope-preview, run-start, and follow-up POSTs have a
narrow local-profile exception: loopback may use them without staff/API-key authentication. Remote
always requires authentication, and every other mutation is unchanged. This is
bounded analysis-process authority, not generic loopback mutation authority.

The runner uses fixed argv, `shell=False`, a vetted attached-workspace cwd,
workspace-write, `approval_policy="never"`, disabled command networking,
unified-exec, and interactive action features, forced hooks, ignored user config,
an explicit registry-owned Sol/xhigh Head Manager selector, fully verified
generated config/prompts/core skills/runtime,
a fail-closed analysis tool/MCP allowlist, a stripped secret-like environment,
and one active process per run. Django starts the generated `head-manager`, not
fixed roles. Head Manager selects within the intake candidate roles; the service
builds the stage DAG and safety fields and records gated artifact rounds through
the structured `record_workflow_plan` and `record_artifact_supervisor_loop`
services. Persist/return only normalized, redacted,
allowlisted public state—never
raw reasoning, tool inputs/outputs, stderr, or raw final output. Each process has
a fixed 30-minute elapsed timeout that terminates and reaps the process and
records a redacted failure; there is no user-triggered web cancel, and the
timeout does not widen any financial execution gate.
Artifact writes are authenticated-role-bound, stage gates are ordered, research
roots reject symlinks, and terminal state must match append-only event replay.

## Edit Checklist

When changing this area, inspect:

- `docs/safety-policy-and-execution.md`
- `docs/guardrails.md`
- `tradingcodex_service/application/policy.py`
- `tradingcodex_service/application/orders.py`
- `tradingcodex_service/application/brokers.py`
- `tradingcodex_service/mcp_runtime.py`
- order/policy/broker/API/CLI tests
- workbench CSRF/auth, subprocess, redaction, concurrency, and analysis-only
  negative tests
- generated role allowlists and prompts for authority drift
