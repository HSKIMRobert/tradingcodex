# User-Facing Skills

TradingCodex exposes many skills internally, but users usually interact with a
small user-facing set. Primary skills start the main plane. Supporting skills
shape, automate, or review workflows without granting extra authority.

## Primary Entrypoints

| Skill | Primary use | Main output |
| --- | --- | --- |
| `tcx-workflow` | Investment research, thesis review, Decision Packages, portfolio fit, risk review, or order-readiness workflow planning. | Validated staged workflow plan, selected role team, accepted artifact synthesis, waiting/revise/blocked state, or Decision Package. |
| `strategy-creator` | Create, update, inspect, activate, archive, or delete reusable user strategy skills. | Validated strategy skill with required sections, status, projection metadata, and user approval posture. |
| `tcx-server` | Dashboard/service health, `doctor`, update status, MCP readiness, DB path checks, and startup recovery. | Runtime status, recovery command, dashboard URL, update guidance, or blocker reason. |
| `tcx-build` | Build-mode connector/provider implementation, broker/API scaffolding, capability profile wiring, credential-ref setup, and validation. | Connector scaffold, provider registration metadata, validation output, docs, and generated workspace updates. |

## Supporting User Skills

| Skill | Primary use | Main output |
| --- | --- | --- |
| `plan-workflow` | Draft, inspect, or revise a bounded workflow plan before dispatch or implementation. | Plan with selected stages, eligible roles, required gates, handoff expectations, and waiting/revise/blocked posture. |
| `automate-workflow` | Define repeatable workflow automation while keeping approvals, execution, and policy gates separate. | Automation recipe, trigger scope, guardrails, review requirements, and blocked actions. |
| `postmortem` | Review a workflow, decision, blocked artifact, rejected action, or execution/process failure after the fact. | What happened, failed assumptions, role/source-quality findings, confidence calibration, and `improve` records. |

## Routing Rules

`tcx-workflow` is the default for investment-facing natural-language prompts.
The hook records compact workflow intake, then `head-manager` drafts,
validates, and records a staged plan before dispatching fixed roles. It should
not produce substantive investment analysis before accepted role artifacts
exist.

`strategy-creator` handles strategy authoring as durable user rules, not live
market analysis. A strategy can guide future workflows, but it does not approve
orders, grant broker authority, mutate policy, or execute trades.

`tcx-server` handles operations. It can explain service state, local dashboard
readiness, update posture, MCP configuration, and recovery steps. It should not
be used to perform investment judgment or connector implementation.

`tcx-build` handles product/build-plane work. It requires the build gate and
full-access posture before editing generated harness, template, connector, or
provider surfaces. It may create live-capable provider code, but live execution
still remains behind service-layer approval, policy, connection, confirmation,
idempotency, sync, and audit gates.

`plan-workflow`, `automate-workflow`, and `postmortem` are user-facing support
skills. They shape or review workflows, but they do not replace
`tcx-workflow` as the normal investment-dispatch entrypoint.

## Role-Owned Skills

Role-owned subagent skills such as `agent-judgment-review`,
`fundamental-analysis`, `portfolio-review`, or `execute-paper-order` belong to
fixed-role dispatch. Users normally reach them through `tcx-workflow`, not by
calling the role skill directly.
