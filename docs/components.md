# Harness Components

This document owns the component-first maintenance model for TradingCodex.
Components are the implementation and change units. Guardrails and Improvement
remain product taxonomy tags and review lenses over those components.

The canonical registry lives in
`tradingcodex_service.application.components`. Docs, API responses, product web
views, and generated workspace indexes are projections of that Python registry.

## Component Contract

Each component has:

- `id`, `label`, `summary`, and `status`
- taxonomy `tags`, such as `guardrail.guidance`,
  `guardrail.enforcement`, `guardrail.information_barrier`,
  `improvement.workflow_quality`, or `improvement.research_memory`
- `surfaces`, such as instructions, skills, hooks, services, templates,
  models, MCP tools, and tests
- `depends_on`, `owned_capabilities`, and `validation`

Tags do not grant permissions and do not define implementation ownership. They
help humans, the API, and the product web view explain why a component exists.

## Current Components

| Component | Purpose | Primary tags |
| --- | --- | --- |
| `investment-request-routing` | Classifies user intent and activates fixed-role workflows. | `guardrail.guidance`, `improvement.workflow_quality` |
| `fixed-role-dispatch` | Maintains head-manager, fixed subagent routing, and no-overlap handoff boundaries. | `guardrail.guidance`, `guardrail.information_barrier`, `improvement.workflow_quality` |
| `research-memory` | Stores source-aware research artifacts, versions, snapshots, and exports. | `improvement.research_memory` |
| `workflow-quality-gates` | Defines lane selection, handoff acceptance, artifact readiness, claim discipline, and synthesis gates. | `guardrail.guidance`, `improvement.workflow_quality` |
| `external-data-source-gate` | Keeps external evidence read-only and source-aware. | `guardrail.guidance`, `improvement.workflow_quality` |
| `external-mcp-proxy-gate` | Imports external MCP metadata, classifies risk, manages role scopes, and blocks unsafe direct proxy paths. | `guardrail.enforcement`, `guardrail.information_barrier` |
| `secret-wall` | Blocks raw broker secrets from workspace files, prompts, shell paths, and role context. | `guardrail.enforcement`, `guardrail.information_barrier` |
| `policy-and-restricted-list` | Evaluates principals, capabilities, explicit deny rules, restricted symbols, and limits. | `guardrail.enforcement` |
| `approval-gate` | Validates order intents and approval receipts before execution-sensitive action. | `guardrail.enforcement` |
| `execution-boundary` | Keeps execution behind MCP allowlists, approval, idempotency, adapter, and audit checks. | `guardrail.enforcement`, `guardrail.information_barrier` |
| `audit-ledger` | Records policy, MCP, order, approval, execution, and hook events. | `guardrail.enforcement`, `improvement.validation_feedback` |
| `skill-improvement-loop` | Keeps core skills, strategy skills, and role-local optional skill files visible through validation, generated manifests, and read-only status. | `improvement.skill_evolution`, `guardrail.guidance` |
| `postmortem-loop` | Turns rejected orders, process failures, thesis changes, and executions into improvements. | `improvement.postmortems`, `improvement.validation_feedback` |
| `paper-execution` | Provides experimental local paper and stub adapters behind the execution boundary. | `guardrail.enforcement` |

## Runtime Surfaces

The registry is exposed through:

- service helpers: `list_harness_components`, `get_harness_component`, and
  `list_components_by_tag`
- Django Ninja API: `/api/harness/components` and
  `/api/harness/components/{component_id}`
- product web diagnostics: component maintenance map when exposed outside Admin
- generated workspace index:
  `.tradingcodex/generated/component-index.json`

## Change Rule

When a feature changes, update the component that owns the feature. Then update
any affected prompts, skills, hooks, services, templates, tests, and docs listed
in that component's surfaces.

Do not split implementation work by Guardrails or Improvement taxonomy alone.
A single component may intentionally carry multiple tags.
