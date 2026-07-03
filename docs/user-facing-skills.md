# User-Facing Skills

TradingCodex exposes many skills internally, but users should usually start
from four entry skills. Each entry skill maps a user request into the right
plane and keeps unrelated authority out of context.

## Entrypoints

| Skill | Primary use | Main output |
| --- | --- | --- |
| `tcx-workflow` | Investment research, thesis review, Decision Packages, portfolio fit, risk review, or order-readiness workflow planning. | Validated staged workflow plan, selected role team, accepted artifact synthesis, waiting/revise/blocked state, or Decision Package. |
| `strategy-creator` | Create, update, inspect, activate, archive, or delete reusable user strategy skills. | Validated strategy skill with required sections, status, projection metadata, and user approval posture. |
| `tcx-server` | Dashboard/service health, `doctor`, update status, MCP readiness, DB path checks, and startup recovery. | Runtime status, recovery command, dashboard URL, update guidance, or blocker reason. |
| `tcx-build` | Build-mode connector/provider implementation, broker/API scaffolding, capability profile wiring, credential-ref setup, and validation. | Connector scaffold, provider registration metadata, validation output, docs, and generated workspace updates. |

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

## Non-Entrypoint Skills

`postmortem` is user-callable, but it is usually a follow-up after a workflow,
incident, blocked action, rejected artifact, or execution/process failure.

`plan-workflow` and `automate-workflow` are supporting workflow skills. They
should not be presented as the normal starting point for users.

Role-owned subagent skills such as `agent-judgment-review`,
`fundamental-analysis`, `portfolio-review`, or `execute-paper-order` belong to
fixed-role dispatch. Users normally reach them through `tcx-workflow`, not by
calling the role skill directly.
