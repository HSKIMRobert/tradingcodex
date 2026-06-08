# TradingCodex Docs

This directory is the source of truth for TradingCodex product direction, core concepts, operating rules, and policy decisions. The current baseline is a Python/Django modular monolith with a central local Django DB, a user-facing visual web dashboard, Django Admin harness console, Django Ninja control API, Django-hosted MCP boundary, Python workspace generator, and DB-first research memory. Codex projects are clients and provenance sources, not investment-state partitions. When code, templates, or tests disagree with product rules, use these docs to decide the intended behavior and update docs and implementation together.

## Documentation Map

| Document | Role | Update when |
| --- | --- | --- |
| [tradingcodex-prd.md](./tradingcodex-prd.md) | Product definition, goals, non-goals, and scope source of truth | Product direction, scope, core principles, or baseline harness policy changes |
| [core-concepts-and-rules.md](./core-concepts-and-rules.md) | Fast reference for concepts, roles, guardrails, information barriers, and execution rules | Rules, terminology, subagent permissions, execution flow, or documentation standards change |
| [deployment.md](./deployment.md) | PyPI/TestPyPI release process, CI/CD workflow, Trusted Publishing setup, and release smoke checks | Packaging metadata, release automation, versioning policy, or distribution boundaries change |
| [licensing-and-commercialization.md](./licensing-and-commercialization.md) | Open-core licensing, contribution, trademark, generated workspace, and commercialization boundary | Repository license, contribution model, trademark policy, generated workspace ownership, or monetization boundary changes |

## Source-Of-Truth Principles

| Principle | Meaning |
| --- | --- |
| Docs first | Product direction, safety rules, role responsibilities, and execution policy changes start by reading the relevant docs. |
| Update in the same change | Durable rule changes in code, templates, or tests must update the relevant docs in the same change. |
| PRD owns direction | `tradingcodex-prd.md` answers what the product is and why it exists. |
| Core concepts own operations | `core-concepts-and-rules.md` answers how concepts and rules are applied. |
| Implementation verifies docs | Implementation does not replace the docs. If implementation reveals a new durable rule, document it. |
| English product language | TradingCodex product copy, generated workspace guidance, admin UI, and durable docs are written in English. |
| Product web is review-first | The `/` web app visualizes harness state and prepares starter prompts, but does not spawn agents, approve orders, or execute orders. |
| Open-core boundary is explicit | Apache-2.0 covers the repository open core; trademarks and official commercial offerings remain separately governed. |

## Change Checklist

Every TradingCodex product or rule change should check the relevant source-of-truth document.

| Change type | Documents to check |
| --- | --- |
| Product scope, non-goals, or live execution policy | `tradingcodex-prd.md` |
| Guardrails, policy, permission, or MCP boundary | `tradingcodex-prd.md`, `core-concepts-and-rules.md` |
| Product web dashboard, visual harness, or SDK orchestration boundary | `tradingcodex-prd.md`, `core-concepts-and-rules.md` |
| Subagent roster, role responsibilities, or tool surface | `core-concepts-and-rules.md` |
| Artifact paths, schemas, workflows, or task harness | `core-concepts-and-rules.md` |
| Module graph, capabilities, or generated workspace structure | `tradingcodex-prd.md`, `core-concepts-and-rules.md` |
| PyPI/TestPyPI release, CI/CD, or package distribution boundary | `deployment.md`, `tradingcodex-prd.md` |
| License, contribution, trademark, or monetization boundary | `licensing-and-commercialization.md` |
