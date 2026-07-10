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

If a user asks to set up, install, attach, or use TradingCodex in a workspace, do not clone this source repository into that workspace. From the target workspace, run:

```bash
uvx --refresh --from tradingcodex tcx attach . && ./tcx doctor
```

On native Windows PowerShell, attach with the same installed command and run
`.\tcx.cmd doctor`. Generated workspaces always contain both `tcx` and
`tcx.cmd`; use only the native launcher for the current platform.

Clone this repository only for source development, inspection, or modification. Source: `README.md`, `AGENTS.md`, `docs/generated-workspaces.md`.

## Core Mental Model

TradingCodex is a local-first investment OS built on Codex. Its harness is the orchestration and runtime subsystem that coordinates research, analysis, scoreable forecast and calibration workflows, and role handoffs. Django owns durable service behavior. TradingCodex owns the executable boundary. Natural-language answers do not become broker actions.

Keep three product layers separate when editing:

- Core kernel: non-replaceable quality, evidence, policy, approval, execution, audit, and provenance contracts.
- Bundled investment capability pack: the fixed team, built-in investment skills, method profiles, and evaluation profiles that must make a pristine workspace useful without customization.
- Managed user overlays: additional instructions, optional role skills, and strategies that extend the baseline without weakening the kernel.

Codex may discover globally installed or plugin-provided skill metadata. Those capabilities are outside the pristine TradingCodex baseline and require explicit user opt-in for the current workflow or managed activation. Current workspace projection is not proof of hard runtime isolation; do not claim that property without clean-host, populated-host, name-collision, and invocation evidence.

The system has three runtime planes:

- Codex control plane: generated prompts, role TOML, skills, hooks, and project MCP config.
- Django service plane: policy, orders, approvals, portfolio, audit, integrations, MCP, API, Admin, web, and research indexing.
- Workspace system plane: generated files, research markdown, source snapshots, policies, audit files, and the `tcx`/`tcx.cmd` launchers.

The service plane decides and records execution-sensitive outcomes. Workspace files keep agent, skill, workflow, and research state readable.

## High-Signal Source Files

| File or directory | Why it matters |
| --- | --- |
| `tradingcodex_cli/__main__.py` | CLI command dispatcher and command surface. |
| `tradingcodex_cli/generator.py` | Workspace module graph, template rendering, generated indexes. |
| `tradingcodex_service/application/components.py` | Harness component registry and maintenance ownership. |
| `tradingcodex_service/application/agents.py` | Fixed roles, built-in skills, permission profiles, MCP allowlists, projection. |
| `tradingcodex_service/application/workflow_planner.py` | Deterministic intake, staged plans, loop-state paths. |
| `tradingcodex_service/application/workflow_contracts.py`, `workflow_state.py` | Typed plan bindings and replayable per-run workflow state. |
| `tradingcodex_service/application/research_specs.py`, `forecasting.py` | Point-in-time research plans, method profiles, experiment runs, and forecast lifecycle. |
| `tradingcodex_service/application/investment_analysis.py`, `evaluation_lab.py` | Method-bound causal valuation plus pristine and corpus-declared paired model-evaluation profiles. |
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
