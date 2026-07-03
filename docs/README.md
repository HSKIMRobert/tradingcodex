# TradingCodex Documentation

This directory is the human-readable source of truth linked from the public `README.md`. It explains the product model, operating rules, safety boundaries, generated workspace behavior, implementation architecture, validation expectations, release policy, and licensing posture.

Use these docs when you want the deeper "why" behind TradingCodex behavior. Coding agents should use `openwiki/` for fast source navigation, then return here before changing durable product behavior.

## How To Read These Docs

| Reader goal | Start with | Then read |
| --- | --- | --- |
| Understand TradingCodex quickly | [core-concepts-and-rules.md](./core-concepts-and-rules.md) | [product-direction.md](./product-direction.md), [harness.md](./harness.md) |
| Install or update a workspace | [../installation.md](../installation.md) | [generated-workspaces.md](./generated-workspaces.md), [deployment.md](./deployment.md) |
| Understand which user skill to start with | [user-facing-skills.md](./user-facing-skills.md) | [roles-skills-and-workflows.md](./roles-skills-and-workflows.md), [interfaces-and-surfaces.md](./interfaces-and-surfaces.md) |
| Understand the investment workflow | [harness.md](./harness.md) | [roles-skills-and-workflows.md](./roles-skills-and-workflows.md), [research-memory-and-artifacts.md](./research-memory-and-artifacts.md) |
| Understand safety and execution boundaries | [safety-policy-and-execution.md](./safety-policy-and-execution.md) | [guardrails.md](./guardrails.md), [interfaces-and-surfaces.md](./interfaces-and-surfaces.md) |
| Understand implementation architecture | [system-architecture.md](./system-architecture.md) | [interfaces-and-surfaces.md](./interfaces-and-surfaces.md), [components.md](./components.md) |
| Change prompts, skills, hooks, routing, or generated workspaces | [roles-skills-and-workflows.md](./roles-skills-and-workflows.md) | [generated-workspaces.md](./generated-workspaces.md), [validation-and-test-plan.md](./validation-and-test-plan.md) |
| Validate a change before release or handoff | [validation-and-test-plan.md](./validation-and-test-plan.md) | The topic document for the changed area |

## Documentation Layers

| Layer | Audience | Role |
| --- | --- | --- |
| `README.md` | New users and evaluators | Product summary, installation path, feature overview, and links into these docs. |
| `installation.md` | Operators | Setup, update, installer, MCP/service startup, and smoke checks. |
| `docs/` | Humans and maintainers | Durable product source of truth and deeper design rationale. |
| `openwiki/` | Coding agents | Fast repository map and edit/validation routing. |
| `AGENTS.md` | Coding agents | Hard rules, setup guard, coding rules, and validation requirements. |

If these layers disagree, treat `docs/` as the durable product intent and fix the mismatch deliberately. Do not let hidden behavior drift live only in code, tests, prompts, skills, hooks, or generated templates.

## Core Documents

| Document | Owns |
| --- | --- |
| [core-concepts-and-rules.md](./core-concepts-and-rules.md) | Fast operating reference for planes, guardrails, role boundaries, execution lifecycle, research memory, and documentation rules. |
| [product-direction.md](./product-direction.md) | Product thesis, target user posture, goals, non-goals, product language, default runtime, universe scope, and open-core posture. |
| [harness.md](./harness.md) | Top-level harness model: roles, skills, service-layer state, policy, MCP, research memory, approvals, execution adapters, audit, and improvement loops. |
| [components.md](./components.md) | Component-first maintenance registry, taxonomy tags, owned surfaces, dependencies, capabilities, and validation. |

## Workflow And Agent Documents

| Document | Owns |
| --- | --- |
| [user-facing-skills.md](./user-facing-skills.md) | User-facing entry skills, routing posture, and non-entrypoint skill boundaries. |
| [roles-skills-and-workflows.md](./roles-skills-and-workflows.md) | Fixed role roster, no-overlap role contract, head-manager dispatch gate, skills, strategy skills, subagent isolation, workflow routing, and module graph. |
| [research-memory-and-artifacts.md](./research-memory-and-artifacts.md) | File-native research memory, source snapshots, artifact paths, readiness labels, report quality floor, forecast ledger posture, and handoff metadata. |
| [financial-workflow-references.md](./financial-workflow-references.md) | Research-backed finance workflow principles and non-expert UX requirements for workflow intake and handoffs. |
| [artifact-supervisor-loop-prd.md](./artifact-supervisor-loop-prd.md) | Artifact Supervisor Loop PRD, bounded follow-up routing, lane escalation, loop state, and Decision Quality Spine preservation. |

## Safety And Improvement Documents

| Document | Owns |
| --- | --- |
| [guardrails.md](./guardrails.md) | Guardrail taxonomy: guidance, enforcement, and information barriers. |
| [safety-policy-and-execution.md](./safety-policy-and-execution.md) | Permission checks, approval rules, execution lifecycle, adapter boundary, external MCP gate, blocked actions, and secret handling. |
| [improvement-loop.md](./improvement-loop.md) | Workflow quality, research memory, skill evolution, postmortems, validation feedback, and quality-learning loops. |

## Implementation And Operations Documents

| Document | Owns |
| --- | --- |
| [system-architecture.md](./system-architecture.md) | Django modular monolith, central DB ownership, app boundaries, runtime planes, service-layer use cases, and core models. |
| [interfaces-and-surfaces.md](./interfaces-and-surfaces.md) | Product web, Django Admin, Django Ninja API, MCP boundary, CLI, generated wrapper behavior, and external MCP surface. |
| [generated-workspaces.md](./generated-workspaces.md) | `tcx attach`, `tcx init`, `tcx update`, generated files, project-scoped MCP config, hooks, workspace provenance, profile scope, and template rules. |
| [validation-and-test-plan.md](./validation-and-test-plan.md) | Required validation commands, unit/API/generator/smoke coverage, MCP smokes, broker provider smokes, routing scenarios, and release-sensitive checks. |
| [deployment.md](./deployment.md) | PyPI/TestPyPI release process, CI/CD, Trusted Publishing, installer/update policy, versioning, and what is not deployed. |
| [licensing-and-commercialization.md](./licensing-and-commercialization.md) | Apache-2.0 open-core boundary, generated workspace ownership, contributions, trademark posture, and legal review needs. |

## Change-To-Docs Map

| Change type | Update these docs |
| --- | --- |
| Product scope, non-goals, default runtime, product language, or release posture | `product-direction.md`, `core-concepts-and-rules.md` |
| Top-level harness model, component registry, guardrail/improvement taxonomy, or cross-cutting concept language | `harness.md`, `components.md`, `guardrails.md`, `improvement-loop.md`, `core-concepts-and-rules.md` |
| User-facing workflow intake, suitability/profile context, plain-English output, or professional finance framing | `financial-workflow-references.md`, `interfaces-and-surfaces.md`, `roles-skills-and-workflows.md` |
| Role roster, head-manager dispatch, skills, strategy behavior, routing, information barriers, or handoff quality | `roles-skills-and-workflows.md`, `artifact-supervisor-loop-prd.md`, `core-concepts-and-rules.md` |
| Research memory, source snapshots, forecast ledgers, readiness labels, artifact paths, report quality, or markdown preview | `research-memory-and-artifacts.md`, `improvement-loop.md`, `artifact-supervisor-loop-prd.md` |
| Policy, permissions, approvals, idempotency, execution, adapters, broker safety, external MCP gate, or secret handling | `safety-policy-and-execution.md`, `guardrails.md`, `core-concepts-and-rules.md` |
| Django apps, models, service-layer contracts, central DB ownership, or runtime topology | `system-architecture.md` |
| Product web, Admin, REST, MCP, CLI, or generated wrapper behavior | `interfaces-and-surfaces.md` |
| Workspace templates, bootstrap, hooks, project MCP config, generated files, or update behavior | `generated-workspaces.md` |
| Test expectations, smoke flows, validation commands, or regression scenarios | `validation-and-test-plan.md` |
| Packaging, installer, release automation, versioning, or distribution boundary | `deployment.md`, `installation.md` |
| License, contribution, trademark, generated workspace ownership, or commercialization boundary | `licensing-and-commercialization.md` |

## Source-Of-Truth Principles

| Principle | Meaning |
| --- | --- |
| Docs first for product behavior | Durable rules for safety, roles, workflows, execution, generated workspaces, and release posture belong in these docs. |
| Update docs with behavior | Code, templates, prompts, hooks, tests, and generated artifacts that change durable behavior should update the owning doc in the same change. |
| Keep `README.md` concise | The public README should explain the product and route readers here instead of duplicating every rule. |
| Keep OpenWiki agent-focused | `openwiki/` should help agents work efficiently and link back to these docs for durable explanations. |
| Keep product language English | TradingCodex product copy, generated workspace guidance, Admin UI, CLI help, role prompts, durable docs, and examples are written in English unless a reviewed localization layer is being built. |
| Product web is review-first | The `/` web app opens on workflow planning and can preview handoffs; it does not spawn agents, approve orders, or execute orders. |
| Open-core boundary is explicit | Apache-2.0 covers the repository open core; trademarks and official commercial offerings remain separately governed. |
