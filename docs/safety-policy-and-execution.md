# Safety, Policy, And Execution

This document owns executable safety: permission checks, approval rules,
execution lifecycle, bounded workbench process/auth boundaries, adapter
boundary, blocked actions, and secret handling.
Use [guardrails.md](./guardrails.md) for the broader guardrail taxonomy.

## Safety Model

TradingCodex safety is part of the investment OS core kernel and is coordinated
through the harness subsystem. Guidance reduces risky behavior early, but only
deterministic enforcement on the final action path can block execution.
Information barriers limit what roles can see or do, while improvement loops
raise quality without becoming executable authorization.

## Executable Action Rule

Every executable action follows:

```text
requester -> permission -> policy -> payload validation -> approval/duplicate-request check -> connection -> audit
```

This order matters:

1. Requester: identify the caller and workspace provenance.
2. Permission: confirm the action is explicitly allowed for that requester.
3. Policy: check restricted list, limits, role, universe, connection, and live-execution posture.
4. Payload validation: validate the structured order/action payload.
5. Approval and duplicate-request check: prove approval is valid and the order has not already produced an execution result.
6. Connection: call only an enabled connection with an allowed execution posture.
7. `audit`: record request, decision, result, hashes, and errors.

Policy and approval are revalidated immediately before connection use.
Broker/API/MCP connection invocation is always owned by the Django service layer.
Codex may draft, explain, classify, and request checks, but it must not call a
raw broker execution primitive directly.

The requester is transport-bound, not trusted from a request body. A generated
role MCP instance supplies `TRADINGCODEX_MCP_PRINCIPAL`; a payload principal is
accepted only when it matches that immutable binding. HTTP mutations require a
bound API principal/key or authenticated staff session except for two narrowly
defined workbench operations: under the `local` profile, a valid-CSRF loopback
request may start an analysis-only run or follow up that same run. Remote use
always requires staff/API-key authentication, and every other mutation keeps
the existing authenticated rule. Loopback is not generic mutation authority.

## Web-Started Analysis Boundary

The workbench runner invokes the same generated `head-manager` through
`codex exec` in JSONL mode. Django supervises the process; it does not directly
spawn fixed roles or create a parallel workflow authority. Initial and follow-up
requests reject order drafting, approval, execution, cancellation, broker
mutation, and secret handling before launch.

The subprocess contract is fixed argv with `shell=False`, a vetted attached
workspace as cwd, `workspace-write`, `approval_policy="never"`, sandbox command
networking disabled, user config ignored, hooks forced on, unified-exec and
interactive browser/computer/app/image features disabled, and secret-like
environment variables removed. Generated launchers, full project/role config,
core prompts/skills, hooks, and the sole canonical TradingCodex MCP server must
match the installed package; managed optional skills and strategies are the only
dynamic projection entries. PreToolUse fails closed and admits only explicit analysis
tools; structured workflow plans and Artifact Supervisor Loop transitions are
validated and recorded through the head-manager-only `record_workflow_plan` and
`record_artifact_supervisor_loop` MCP services. Only one process may be
active per run, with service-owned lock and resume-thread authority.
Follow-up resumes the stored Codex thread. Every initial or resumed process has
a fixed 30-minute elapsed timeout; expiry terminates and reaps it and records a
redacted failed state. No user-triggered web cancel action is exposed.

Only normalized, redacted, allowlisted events and public workflow projections
may be stored or returned. Workflow, hook, research-root, and verified generated-
runtime paths reject symlinks. Canonical workflow state must replay exactly from
its append-only event log. MCP artifact writes bind `created_by`, `role`, and
`producer_role` to the authenticated fixed role, with synthesis reports reserved
for head-manager; dependent-stage artifacts cannot pass before their gate is
ready. Raw
reasoning, tool inputs/outputs, stderr, and raw final output are discarded, not
written into the workspace. Final output additionally requires a validated plan,
synthesis-ready canonical state, head-manager producer binding, body hash, and
the complete accepted-input hash set. An accepted analysis artifact remains evidence, not
an order, approval, or execution authorization. All role, MCP, policy, approval,
idempotency, connection, and audit boundaries remain unchanged.

## Execution Lifecycle

| Step | Artifact/action | Owner | Required rule |
| --- | --- | --- | --- |
| Evidence collection | evidence pack | analyst roles | Separate sources, dates, facts, and assumptions. |
| Analysis | analyst reports, valuation | role subagents | Maintain each role's information barrier. |
| Portfolio fit | portfolio review | `portfolio-manager` | Check sizing, cash, concentration, liquidity, and portfolio fit. |
| Broker sync | `BrokerSyncRun`, `PortfolioLedgerEvent`, `ReconciliationRun` | service layer | Read-only connection path only; raw credentials are references. |
| Draft order | `OrderTicket` | `portfolio-manager` | No execution before schema, policy, cash/position, broker validation, and risk checks. |
| Risk review | risk/policy report | `risk-manager` | Check restricted list, downside, limits, and approval readiness. |
| Approval | `ApprovalReceipt` | `risk-manager` | Bind approval to exact order payload hash, broker/account, max notional/price, order type, time-in-force, and expiry. |
| Execution | `submit_approved_order` through TradingCodex MCP | `execution-operator` | Resolve only the DB-canonical receipt by id, revalidate it against an `APPROVED` ticket, reserve idempotency and mandatory audit before provider invocation, then finalize or mark `NEEDS_REVIEW`. |
| Audit/postmortem | audit event, execution result, postmortem | MCP/head-manager | Record rejects, approvals, executions, and policy decisions. |

Inline receipt dictionaries and workspace receipt paths are not submission
authority. Submission resolves a central DB `ApprovalReceipt` linked to its
ticket and requires the exact order hash, broker/account scope, order type,
time-in-force, limits, expiry, and unconsumed state to match. Receipt validation,
ticket locking, execution reservation, and the mandatory pre-provider audit are
committed together. An unavailable mandatory audit sink prevents adapter
invocation.

Approved execution is idempotent by order/profile boundary. A repeated
`submit_approved_order` call for an order that already has an
`ExecutionResult` in the same `portfolio_id` / `account_id` / `strategy_id`
must be rejected before any connection is called.
Connection readiness failures, such as missing credentials, disabled live opt-in,
or signed-health errors before a broker submit attempt, must fail before creating
an `ExecutionResult` so the operator can retry after fixing configuration,
credentials, permissions, or IP allowlists. Once a broker submission may have
reached the provider submit boundary, TradingCodex records `NEEDS_REVIEW` /
unknown status and duplicate protection applies until status is reconciled.
Provider correlation data stays on the durable execution record so recovery
does not rely on retrying an uncertain submit.

Order ticket ids are central-DB ids. CLI/API/MCP calls use `ticket_id` or
`order_ticket_id`; if the same id appears with a different payload, validation
must fail closed instead of mutating the existing ticket.

`OrderTicket` state changes must happen through explicit service functions.
Invalid transitions are blocked, and every transition writes `OrderEvent` plus
an audit event. The supported lifecycle is:

```text
DRAFT -> PRECHECKED -> READY_FOR_APPROVAL -> APPROVED -> RESERVED
  -> SUBMITTED -> ACKED -> PARTIALLY_FILLED -> FILLED
```

Terminal or review states are `REJECTED`, `CANCELED`, `EXPIRED`, `FAILED`,
and `NEEDS_REVIEW`. Fills create `Fill`, `BrokerOrder`, `OrderEvent`, portfolio
ledger, snapshots, and reconciliation records. Validation submissions create
broker-order and audit records but no fill when the broker endpoint validates
without sending an order to a matching engine. For validation-only connector
modes, `refresh_broker_order_status` preserves the local validated state when
the broker endpoint intentionally does not create an external order. Live cancel
uses the installed provider cancel path and remains audited.

Signed broker credential failures are execution blockers, not execution
attempts. The connector remains read-only with no enabled trade scopes, exposes
only secret-free diagnostics such as `credential_validation_details`, and
`submit_approved_order` stops before reserving or consuming execution
idempotency.

Draft discard and broker cancellation are distinct operations.
`discard_draft_order` is portfolio-manager-only and applies only to local
`DRAFT` or `PRECHECKED` tickets with no broker order. `cancel_submitted_order`
is execution-operator-only, requires a known submitted broker order, canonical
approval, current policy/connection checks, idempotency and audit, and explicit
live confirmation when the provider is live. The legacy
`cancel_approved_order` name is a compatibility alias for submitted-order
cancellation; it does not discard drafts.

## Money And Paper Portfolio Safety

Order notionals use a typed money contract: native currency and notional,
profile-selected base currency/notional, FX rate, source snapshot id, and FX
as-of time. The base currency is a validated three-letter code and defaults to
the active profile's setting. Values remain `Decimal` through order, policy,
serialization, and paper-portfolio paths. Cross-currency orders fail before
approval when the FX source snapshot is
missing, after the order time, stale, invalid, or currency-mismatched. Policy
limits compare the base notional, while the native amount remains visible.
The internal money ledger keeps six decimal places for every validated
three-letter code instead of guessing a currency's display minor units. Broker
adapters remain responsible for venue tick, lot, and settlement-precision
validation at their boundary. Ambiguous currency symbols and external accounts
without an explicit base currency fail closed.

Paper state is serialized per `(portfolio_id, account_id, strategy_id)` through
a versioned `PaperPortfolioState` row and compare-and-swap update. Cash is held
by currency, position currency must match the order currency, and state,
snapshot, positions, and cash child rows are written transactionally. A
concurrent conflicting update retries or fails explicitly instead of silently
overwriting cash or positions.

Released pre-globalization migrations retain their original field names and
defaults solely so existing databases can upgrade safely. Forward migrations
preserve each existing order's native currency/notional, supersede approvals
whose hash predates the money contract, and preserve legacy paper cash without
re-denominating it. New profiles and current runtime policy do not inherit those
legacy defaults.

## Required Blocks

TradingCodex must block:

- direct live broker requests outside `submit_approved_order` /
  `cancel_submitted_order` (`cancel_approved_order` remains an alias)
- direct raw external MCP proxy for broker, execution, secret, or policy/admin
  tools
- raw broker API variants such as `broker.raw_api`, `broker_api.*`, and generic live execution actions
- generic execution-like actions such as `execute_order` unless they enter the approved TradingCodex MCP lifecycle
- self-issued approvals
- approval creation by roles other than `risk-manager`
- restricted symbol orders
- approval order-payload-hash mismatch after order mutation
- expired approval receipts or expired approval `valid_until`
- orders exceeding approval max notional, max price, order type, or time-in-force scope
- paper/test-sandbox/live provider orders without a valid order ticket plus matching approval receipt
- repeated connection submission for an already executed approved order
- duplicate order ticket ids with different payloads
- global MCP exposure for approval, execution, cancellation, policy mutation, secret, or broker tools
- Any default Admin edit that would bypass service-layer policy for execution-sensitive state
- execution when the principal is inactive or capability is denied
- raw secrets in API, MCP, audit response, generated prompt, generated docs, or shell output
- inline or path-based approval receipts, payload principals that differ from
  the transport identity, and draft discard through an execution cancellation
  operation
- cross-currency order approval without a valid point-in-time FX conversion
- live execution when workspace config, policy, environment opt-in, enabled live adapter, signed health, trading-enabled connection, live scope, approval hash, explicit confirmation, idempotency, sync, or audit gates are missing

## External MCP Gate

External MCP servers are useful for broker account data, market data, research
sources, and future adapter support, but they must enter through the
TradingCodex External MCP Gate rather than direct Codex exposure.

Discovery stores external tool/resource/prompt metadata, schema hash, risk
category, sensitivity, canonical capability, role scope, proxy mode, and
lifecycle status. Default posture is fail-closed:

- unknown tools are disabled until classified
- schema-hash drift disables the tool until reviewed
- secret and policy/admin tools are not proxyable
- execution tools cannot use direct raw proxy and must map to the approved
  service-layer connection path
- account-read tools require explicit role scope and audit because balances,
  positions, orders, and fills expose private strategy/account data
- public market-data/news/filing tools may remain lightweight, but they require
  source/as-of posture, cache/freshness discipline, and source-snapshot or
  research-artifact handling when used in TradingCodex order, risk, approval,
  or portfolio decisions

External MCP permission is not execution authorization. Even if an external
broker order tool is present and reviewed, order submission must still pass the
TradingCodex order-ticket, approval, duplicate-request, connection, and audit lifecycle.

External MCP launch configuration is reference-only. `env` maps child variable
names to `env:SOURCE_NAME` references; `credential_ref` accepts reviewed
environment/keychain-style references. Raw values, URL user-info, and inline
credential arguments are rejected. References are resolved only for child
process launch. Stored requests/results, discovery payloads, audit records,
responses, errors, and stderr logs pass through recursive redaction, and
external-MCP stderr logs rotate with bounded backups. The migration scrub for
legacy rows removes values that predate this contract; operators should rotate
any credential that was previously submitted as a raw value.

The built-in TradingCodex MCP server auto-approves safe enabled tools to avoid
buried subagent prompts for routine research and audit writes. Execution
submission and cancellation are the exception: non-execution roles do not see
those tools, and `execution-operator` can only submit or cancel through
TradingCodex service-layer checks.

Reviewed external MCP calls that expose private account state, write research
state, use workflow prompts, or map to execution require an explicit user
permission request before proxy evaluation returns `allow`. The request is
stored as pending service-layer state and surfaced through Build Center,
`tcx build permission list`, and the coordinator-visible MCP pending-request
list. Subagents must stop at `waiting_for_user_permission` instead of burying a
Codex permission prompt in their transcript.

Codex network access may be enabled for public web, filing, disclosure, news,
and market-data evidence gathering. That access is read-only research support:
it does not authorize direct broker APIs, raw external broker MCP exposure,
secret reads, approval bypass, or execution.

## Broker Safety

Broker connections start disabled or read-only, except the built-in paper
adapter. Core ships only the paper provider by default. Broker-specific
providers are installed or developed on request, then registered by provider
metadata. A registered provider profile with an allowed execution posture
becomes execution-ready only after signed health verifies its credential
reference and the policy/config gates allow that posture. Broker records store
`credential_ref` only; raw credentials must not be stored in repo files,
workspace files, API responses, MCP responses, or audit payloads.

`get_broker_connection_status` is a pure read. It may calculate and return
health but does not persist status, credential validation, drift, or trading
scopes. Execution enablement belongs to an explicit reviewed mutation, never a
GET or read-hinted MCP call.

Broker sync can discover accounts, cash, positions, orders, and fills through
the provider registry. It materializes central DB state through
`BrokerSyncRun`, `PortfolioLedgerEvent`, `PortfolioSnapshot`, and
`ReconciliationRun`. A reviewed validation provider can run broker-native
dry-run/order-test endpoints through the service-layer connection after order
ticket, approval, policy, duplicate-request, and audit checks. A reviewed live
provider can submit only when all live gates pass: `execution.live_enabled:
true`, policy allows the broker id and `live_broker`, environment variable
`TRADINGCODEX_ENABLE_LIVE_EXECUTION=1`, the live `AdapterDefinition` is enabled,
signed health is `ok`, the connection is `trading_enabled`, the exact order hash
has an approval receipt, and `submit_approved_order` includes
`LIVE:<ticket_id>:<broker_id>:<symbol>:<side>:<quantity>`.

## Routing Guardrail

- Connected negations such as `no order or trading`, `do not order or trade`,
  `not asking for an order or trade`, and `without an order or a trade` remove
  every named action and must keep the request out of execution routing.
- Descriptive evidence such as `the board does not recommend the transaction`
  is not a user prohibition merely because it contains negative wording.
- Plural and verb-object forms use the same rule, including `no forecasts or
  recommendations` and `do not execute a trade`. Ambiguous negated
  order/trade/approval/execution wording fails closed instead of activating an
  approved-action lane.
- A negated mandatory portfolio or risk gate downgrades or blocks order-draft
  and approved-action routing; it never removes that gate while preserving the
  high-impact lane.
- Guardrail-verification wording such as "verify blocked order/approval/execution actions" is evidence of a safety check, not a request to execute.
- Secret-only prompts such as requests to save, read, or rotate broker API
  keys, tokens, credentials, passwords, or `.env` files produce secret-wall
  warning context and do not activate investment subagent dispatch unless a
  separate investment, order, approval, or execution request remains after the
  secret terms are removed.
- Public-equity earnings, filing, catalyst, thesis, and valuation requests route to thesis-review style research/valuation support unless the user separately asks for portfolio fit, order drafting, approval, or execution.
- Unsupported universes are downgraded to research-only, screen-grade, not-decision-ready, or blocked.

## Secret Wall

Raw broker API keys, tokens, account credentials, and secrets must not appear in:

- generated workspace files
- `.codex/` or `.agents/` prompts
- shell output
- product web output
- Admin list displays or exported rows
- API responses
- MCP responses
- audit event payloads
- starter prompts
- generated research artifacts
- workbench operational metadata or normalized event projections

Adapters that need secrets must use external environment-backed credential
references and expose only redacted references through TradingCodex.

## HTTP Runtime Boundary

The default `local` service profile is loopback-only. Anonymous loopback
requests may read product and health state. Only the CSRF-protected workbench
scope-preview, run-start, and follow-up POSTs may use local-profile loopback without a bound API
principal or Django staff session, and only for the bounded analysis behavior
above. Every other API/web mutation still requires its existing authenticated
principal. The exception does not make loopback a general mutation or execution
authority.

Non-loopback binding is fail-closed and requires the explicit `remote` profile,
`DEBUG=False`, a non-default Django secret, configured API mutation credentials,
non-wildcard allowed hosts, matching HTTPS CSRF origins, and TLS termination by
a trusted reverse proxy. The proxy must strip untrusted forwarded-protocol
headers before setting `X-Forwarded-Proto: https`; the backend must not be
directly exposed. Raw Django/API credentials remain subject to the Secret Wall
and must not enter repository, workspace, prompt, audit, API, MCP, or log data.

## Policy Inputs

Policy decisions can depend on:

- principal
- role
- capability
- requested action
- symbol/instrument
- universe
- adapter type
- restricted list
- portfolio limits
- order schema validity
- approval receipt validity
- idempotency state
- current live-execution posture
- workspace provenance

Policy output should record the decision, reason codes, material inputs, and
audit reference.

## Admin Risky Changes

Risky Admin changes use:

```text
proposal -> validation -> approval -> apply -> audit
```

Examples:

- enabling or disabling MCP tools
- projecting workspace skill proposal files
- changing principals or capabilities
- toggling restricted symbols
- disabling adapters
- changing universe routing or supported-instrument policy
- applying policy changes

Admin is an operations console, not a bypass.

## Default And Live-Gated Execution

Paper, stub, and reviewed validation execution remain local harness flows.
Live execution is not enabled by bootstrap, workspace generation, connector
scaffold, or connector registration alone. It is available only through an
installed and reviewed provider plus the explicit live gates above.

Every execution still requires:

- structured order ticket
- service-layer validation
- valid approval receipt
- role and capability checks
- idempotency check
- adapter availability check
- audit event
