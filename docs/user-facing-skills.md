# User-Facing Skills

TradingCodex exposes many skills internally, but users usually interact with a
small user-facing set. Primary skills start the main plane. Supporting skills
shape, automate, or review workflows without granting extra authority.

## Primary Entrypoints

| Skill | Primary use | Main output |
| --- | --- | --- |
| `tcx-workflow` | Investment research, thesis review, Decision Packages, portfolio fit, risk review, or order-readiness workflow planning. | Validated staged workflow plan, selected role team, accepted artifact synthesis, waiting/revise/blocked state, or Decision Package. |
| `decision-memory` | Retrieve prior decisions, replay an historical decision with point-in-time evidence, compare outcomes, or validate a lesson. | Source-bound episodes, replay/review artifacts, lesson status, evidence tier, and next validation needed. |
| `strategy-creator` | Create, update, inspect, activate, archive, or delete reusable user strategy skills. | Validated strategy skill with required sections, status, projection metadata, and user approval posture. |
| `tcx-server` | Workbench/service health, `doctor`, update status, MCP readiness, DB path checks, and startup recovery. | Runtime status, recovery command, workbench URL, update guidance, or blocker reason. |
| `tcx-build` | Build-mode connector/provider implementation, broker/API scaffolding, capability profile wiring, credential-ref setup, and validation. | Connector scaffold, provider registration metadata, validation output, docs, and generated workspace updates. |

## Supporting User Skills

| Skill | Primary use | Main output |
| --- | --- | --- |
| `plan-workflow` | Draft, inspect, or revise a bounded workflow plan before dispatch or implementation. | Plan with selected stages, eligible roles, required gates, handoff expectations, and waiting/revise/blocked posture. |
| `automate-workflow` | Define repeatable workflow automation while keeping approvals, execution, and policy gates separate. | Automation recipe, trigger scope, guardrails, review requirements, and blocked actions. |
| `investor-context` | Interview, inspect, update, enable, disable, or clear the current workspace's suitability context. | User-confirmed workspace file, default application state, content hash, and remaining gaps. |

## Routing Rules

`tcx-workflow` is the default for investment-facing natural-language prompts.
The hook records compact workflow intake, then `head-manager` selects the
smallest sufficient candidate-role subset. Shared services validate that team,
compile and record the staged plan, and retain every safety-owned field before
`head-manager` dispatches fixed roles. It should not produce substantive
investment analysis before accepted role artifacts exist.

`strategy-creator` handles strategy authoring as durable user rules, not live
market analysis. A strategy can guide future workflows, but it does not approve
orders, grant broker authority, mutate policy, or execute trades.

Native workflow strategy selection requires exactly one explicit
`$strategy-*` invocation. Plain-language mentions never select a strategy, and
absence records `no_strategy`; Workbench uses its structured strategy selector.
Either path validates and seals the active strategy into the protected run.

`decision-memory` is an explicit retrieval, replay, review, and lesson-validation
entrypoint. For a current judgment it records the independent initial view
before introducing past cases. Wiki and graph outputs are rebuildable views;
canonical evidence remains in source snapshots, decision packages, forecast
events, and review artifacts.

`investor-context` manages only the optional workspace-local suitability file.
Its persistent enable/disable state is separate from skill availability,
strategy rules, and internal paper account scope. It does not run investment
analysis or grant authority. Native intake follows the saved workspace default;
only Workbench offers a one-run apply/ignore control, and that bound choice does
not rewrite the file.

`tcx-server` handles operations. It can explain service state, local workbench
readiness, update posture, MCP configuration, and recovery steps. It should not
be used to perform investment judgment or connector implementation.

`tcx-build` handles product/build-plane work. It requires the build gate and
full-access posture before editing generated harness, template, connector, or
provider surfaces. It may create live-capable provider code, but live execution
still remains behind service-layer approval, policy, connection, confirmation,
idempotency, sync, and audit gates.

`plan-workflow`, `automate-workflow`, and `investor-context` are user-facing
support skills. `postmortem` remains installed as a compatibility entrypoint,
while Decision Memory is the default user-facing review surface. None replaces
`tcx-workflow` as the normal investment-dispatch entrypoint.

## Role-Owned Skills

Role-owned subagent skills such as `agent-judgment-review`,
`fundamental-analysis`, `portfolio-review`, or `execute-paper-order` belong to
fixed-role dispatch. Users normally reach them through `tcx-workflow`, not by
calling the role skill directly.
