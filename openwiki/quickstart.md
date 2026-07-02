# TradingCodex Agent Quickstart

OpenWiki is the working map for coding agents in this repository. It is intentionally shorter than `docs/`: use it to decide what to read, where to edit, and how to validate. For product-facing explanations and durable rules, follow [docs/README.md](../docs/README.md).

## Documentation Contract

| Layer | Audience | Purpose |
| --- | --- | --- |
| `README.md` | New users | Product overview, install path, and links into detailed docs. |
| `docs/` | Humans and maintainers | Durable source of truth for product behavior, safety, architecture, workflows, validation, release policy, and commercialization. |
| `openwiki/` | Coding agents | Fast source map, edit routing, and validation routing. |
| `AGENTS.md` | Coding agents | Hard repository rules and required validation expectations. |

When source behavior changes, update the relevant `docs/` page. When the agent working map becomes misleading, update `openwiki/`. Keep the same concept canonical in one place and link to it elsewhere.

## Fast Path

| Task | Start |
| --- | --- |
| Understand the repository shape | [Architecture](architecture.md) |
| Change head-manager, subagents, skills, hooks, routing, or handoff behavior | [Workflows And Agents](workflows-and-agents.md) |
| Change `tcx attach/init/update`, templates, generated files, or projection | [Generated Workspaces](generated-workspaces.md) |
| Change web/API/MCP/CLI behavior, models, or research memory | [Interfaces And Data](interfaces-and-data.md) |
| Change policy, approval, broker, execution, external MCP, or secrets | [Safety And Execution](safety-and-execution.md) |
| Choose validation before handoff | [Development And Validation](development-and-validation.md) |

## Setup Guard

If a user asks to set up, install, attach, or use `monarchjuno/tradingcodex` in a workspace, do not clone this source repository into that workspace. From the target workspace, run:

```bash
uvx --refresh --from tradingcodex tcx attach . && ./tcx doctor
```

Clone this repository only for source development, inspection, or modification. Source: `README.md`, `AGENTS.md`, `docs/generated-workspaces.md`.

## Core Mental Model

TradingCodex is a local-first Python/Django trading harness for Codex-assisted investment workflows. Codex coordinates research and role handoffs. Django owns durable service behavior. TradingCodex owns the executable boundary. Natural-language answers do not become broker actions.

The system has three runtime planes:

- Codex control plane: generated prompts, role TOML, skills, hooks, and project MCP config.
- Django service plane: policy, orders, approvals, portfolio, audit, integrations, MCP, API, Admin, web, and research indexing.
- Workspace system plane: generated files, research markdown, source snapshots, policies, audit files, and `./tcx`.

The service plane decides and records execution-sensitive outcomes. Workspace files keep agent, skill, workflow, and research state readable.

## High-Signal Source Files

| File or directory | Why it matters |
| --- | --- |
| `tradingcodex_cli/__main__.py` | CLI command dispatcher and command surface. |
| `tradingcodex_cli/generator.py` | Workspace module graph, template rendering, generated indexes. |
| `tradingcodex_service/application/components.py` | Harness component registry and maintenance ownership. |
| `tradingcodex_service/application/agents.py` | Fixed roles, built-in skills, permission profiles, MCP allowlists, projection. |
| `tradingcodex_service/application/workflow_planner.py` | Deterministic intake, staged plans, loop-state paths. |
| `tradingcodex_service/api.py` | Local/staff API surface. |
| `tradingcodex_service/web.py` | Product web behavior. |
| `tradingcodex_service/mcp_runtime.py` | MCP tool registry, input validation, role visibility, call ledger behavior. |
| `workspace_templates/modules/*/files` | Source for generated Codex prompts, skills, hooks, policies, and wrappers. |
| `docs/README.md` | Human documentation hub and source-of-truth map. |

## Change Rules

- Do not infer harness behavior from Python alone. Read docs, prompts, skills, hooks, policies, generated templates, services, and tests as one contract.
- All durable service behavior belongs under `tradingcodex_service/application/` and should be reused by Web, Admin, API, MCP, CLI, and generated hooks.
- Research artifacts and source snapshots are workspace-file-native, not Django research DB models.
- Execution-sensitive actions follow `requester -> permission -> policy -> payload validation -> approval/duplicate-request check -> connection -> audit`.
- Generated prompt, skill, hook, policy, and workspace-contract content should remain ordinary template files under `workspace_templates/modules/*/files`.
