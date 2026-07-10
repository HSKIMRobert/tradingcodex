# Next Release

This is the active scope for the next TradingCodex release. It is derived from
the current source contracts and replaces the 2026-07-10 improvement assessment
as the release checklist. The older assessment remains available as historical
context in [improvement-proposals.md](./improvement-proposals.md).

The release is not complete until the validation gates below pass.

## Release Contract

### Runtime model policy

Model selection remains registry-owned and cannot change role eligibility,
permissions, MCP allowlists, policy, approval, broker, or execution authority.

| Role group | Model | Reasoning effort |
| --- | --- | --- |
| Root `head-manager` | `gpt-5.6-sol` | `xhigh` |
| All fixed subagents except `execution-operator` | `gpt-5.6-terra` | `high` |
| `execution-operator` | `gpt-5.6-terra` | `low` |

Generated runtime configuration has no GPT-5.5 fallback or rollback mode. If an
operator supplies `TRADINGCODEX_CODEX_SUPPORTED_MODELS`, generation must fail
when a required GPT-5.6 selector is absent instead of silently changing models.
An older model may still appear as an offline evaluation control; that is not a
runtime fallback.

The analysis-only workbench ignores user config and passes the registry-owned
Sol/xhigh selector as explicit Codex CLI arguments for initial and resumed
runs. The managed runner therefore keeps the release policy even when an
operator's personal Codex defaults differ.

`max`, `ultra`, Pro mode, persisted reasoning, Programmatic Tool Calling, and a
second Responses multi-agent layer are not part of this Codex project-TOML
release contract.

### Semantic Head Manager planning

The recorded intake defines the lane, candidate roles, explicit exclusions,
required role floors, quality gates, budgets, and terminal condition. Head
Manager contributes the semantic choice:

- `workflow_run_id`
- `selected_roles`
- optional `planner_rationale`

The server rejects roles outside the intake candidate set and omission of a
required role. It then generates the stage DAG and owns blocked actions, user
constraints, quality and artifact requirements, budgets, stop condition,
routing envelope, and integrity hashes. Head Manager remains the only component
that spawns the validated fixed-role team; Django compiles and validates the
contract but does not directly spawn analysts.

Lane safety floors are absolute rather than an intersection with the candidate
list. Order drafting cannot omit portfolio, risk, or independent judgment
gates, and approved-action routing cannot omit portfolio, risk, or execution
gates. A prompt that negates one of those mandatory gates is downgraded or
blocked; it never produces a smaller high-impact team.

### Coordinated negation safety

Negated scope is parsed as one connected constraint before routing. Forms such
as `no order or trading`, `do not order or trade`, `not asking for an order or
trade`, and `without an order or a trade` remove every named action from the
remaining intent. They cannot activate an execution lane or add
`execution-operator`. Descriptive third-party statements such as `the board
does not recommend the transaction` remain evidence, not user scope commands.
Plural and verb-object forms such as `no forecasts or recommendations` and `do
not execute a trade` use the same constraint vocabulary. If a negated
high-impact clause is still ambiguous, deterministic routing fails closed and
does not infer an approved-action lane; a validated structured intent can
disambiguate it.

### Canonical workbench data contract

`GET /api/workbench/` has one response shape:

```json
{
  "generated_at": "...",
  "sections": {
    "workspace": {"ok": true, "data": {}},
    "skills": {"ok": true, "data": []}
  }
}
```

The frontend reads canonical field names and section envelopes instead of
guessing among generic containers, legacy envelopes, or alternate run ids.
Strategies and optional skills come from the same snapshot and mutations
refresh that snapshot once. Detail and mutation endpoints remain service-layer
callers; no frontend state framework is added.

### Bounded web runs

Every initial or resumed workbench Codex process has a fixed 30-minute elapsed
timeout. On expiry the service terminates and reaps the process, records a
redacted `workbench.timed_out` event, marks the run failed, and exposes the
normalized `process_timeout` error. Timeout and exit events carry the process
attempt, and the lock-owning consumer performs finalization so an older timer
cannot overwrite a resumed attempt. This does not add user-triggered web
cancellation or widen any financial action boundary.

## Simplifications Included

- Remove GPT-5.5 runtime fallback and rollback branches.
- Replace agent-authored DAG and safety fields with a small semantic team draft.
- Use the canonical snapshot as the frontend's single management-data source.
- Use one fixed watchdog instead of introducing a scheduler or job framework.
- Keep security checks, artifact binding, locks, redaction, policy, approval,
  execution, and audit controls intact.

## Release Gate Status (2026-07-11)

- [x] Full Python test suite, `python manage.py check`, and broad compile check pass.
- [x] Frontend tests and production build pass, and committed assets match source.
- [x] Focused planner tests prove allowed subset selection, required-role floors,
      mandatory lane floors, unknown-field rejection, server-owned DAG
      generation, and hash binding.
- [x] Routing tests prove connected natural-language negations stay outside
      execution without treating descriptive market or issuer language as a
      user prohibition.
- [x] Focused workbench tests prove the 30-minute watchdog, terminate/reap path,
      timeout event, failed metadata, lock release, and follow-up behavior.
- [x] Frontend and workbench tests prove the canonical section contract, single
      snapshot refresh, shared-profile warning, and
      empty/loading/failure/blocked/completed states.
- [x] A disposable attached workspace passes every doctor layer and generated
      model-policy, agent, skill, and projection manifests match the registry.
- [x] Real Codex runtime smokes confirm Head Manager loads Sol/xhigh, Terra
      accepts the analytical high and execution low efforts, exact-role
      projection is valid, and no GPT-5.5 runtime fallback occurs.
- [x] MCP `tools/list`, semantic plan recording, artifact-stage gating,
      negated-scope, and analysis-only workbench smokes pass.
- [ ] The frozen model-evaluation corpus has trusted provenance, zero permitted
      hard-safety failures, and the required blind non-inferiority review before
      making a GPT-5.6 quality-promotion claim.
- [x] Clean wheel smoke passes on macOS with the packaged SPA and generated
      POSIX/native-Windows launcher pair present.
- [ ] Native Windows must still run the wheel smoke through `tcx.cmd` before
      release.
- [x] Desktop and narrow-width browser checks cover all four public sections,
      keyboard scope review, responsive overflow, empty scope, and service-error
      feedback without exposing raw reasoning, tool payloads, or stderr.

## Explicit Non-Goals

- A GPT-5.5 runtime compatibility path.
- User-triggered web cancellation or a configurable background job system.
- DB-canonical workflow events, dual-read migration, or a universal outbox/saga.
- A frontend state framework, compatibility-facade API, or additional Node runtime.
- Universal telemetry, speculative large-workspace benchmarks, or localization.
- Persisted reasoning, Programmatic Tool Calling, CSV fan-out, or nested API
  orchestration beneath Codex subagents.
- Any relaxation of role boundaries, live-broker defaults, policy, approval,
  idempotency, secret, audit, or execution gates.
