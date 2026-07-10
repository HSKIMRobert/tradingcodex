# Architecture

Use this page to orient source edits. For the human-readable architecture narrative, see [docs/system-architecture.md](../docs/system-architecture.md).

## Investment OS Layers

TradingCodex is the top-level investment OS. The harness is its orchestration
and runtime subsystem, not a synonym for the whole product.

| Layer | Owns |
| --- | --- |
| Core kernel | Non-replaceable evidence, method-fit, quality-gate, policy, approval, execution, audit, and provenance invariants. |
| Bundled investment capability pack | Fixed roles, built-in investment skills, method profiles, evaluation profiles, and the pristine research, analysis, and forecast baseline. |
| Managed user overlays | Additional instructions, optional role skills, and strategies that extend the baseline while remaining subject to the kernel. |
| Harness subsystem | Routing, dispatch, handoffs, projection, service boundaries, persistence, and validation that coordinate the three layers. |

## Runtime Planes

| Plane | Owns | Primary source |
| --- | --- | --- |
| Codex control plane | `head-manager`, fixed subagent TOML, skills, prompts, hooks, project MCP config | `workspace_templates/modules/*/files` |
| Django service plane | policy, orders, approvals, portfolio, audit, broker/integration state, workflows, API, MCP, web, Admin | `tradingcodex_service/application/`, `apps/` |
| Workspace system plane | generated config, research markdown, source snapshots, indexes, `./tcx` wrapper | generated files from `workspace_templates/` |

Control-plane files request or guide work. Service-plane code decides and records durable outcomes. Workspace files make Codex-native state reviewable.

## Source Ownership

| Source | Ownership rule |
| --- | --- |
| `tradingcodex_service/application/*` | Canonical service use cases. Put durable behavior here before wiring surfaces. |
| `apps/*/models.py` | Central DB records for policy, orders, portfolio, audit, MCP, workflows, integrations, and harness provenance. |
| `tradingcodex_cli/commands/*` | CLI interface only. It should call shared services rather than fork behavior. |
| `tradingcodex_service/api.py` | Typed local/staff REST/control API. |
| `tradingcodex_service/web.py` | Product web review and preview flows. |
| `tradingcodex_service/mcp_runtime.py` | Codex MCP boundary, role visibility, schema validation, and MCP ledger behavior. |
| `workspace_templates/modules/*/files` | Generated workspace contract. Human/Codex-readable generated content should stay here as files. |
| `tradingcodex_service/application/components.py` | Component maintenance map exported to generated workspaces. |
| `tradingcodex_service/application/agents.py` | Role/skill registry and projection source. |
| `tradingcodex_service/application/workflow_contracts.py`, `workflow_state.py` | Typed intake/plan bindings and the serialized event/replay reducer. |
| `tradingcodex_service/application/research_specs.py`, `forecasting.py` | Frozen point-in-time research, method profiles, experiment validation, and forecast lifecycles. |
| `tradingcodex_service/application/investment_analysis.py`, `evaluation_lab.py` | Method-bound causal valuation plus pristine and corpus-declared model-evaluation profiles. |

## State Model

The default runtime DB is `~/.tradingcodex/state/tradingcodex.sqlite3`. `TRADINGCODEX_HOME` and `TRADINGCODEX_DB_NAME` can override it. `TRADINGCODEX_WORKSPACE_ROOT` is provenance, not a separate canonical investment ledger.

Central DB state includes policy decisions, order tickets, approvals, execution results, portfolio snapshots, broker connections, non-research MCP call ledgers, workflow runs, and audit rows.

Workspace-file state includes `.codex/`, `.agents/skills/*`,
`.tradingcodex/subagents/skills/*`, `.tradingcodex/generated/*.json`, per-run
workflow intake/plan/state/events, `trading/research/*.md`, source snapshots,
ResearchSpecs, replay manifests, experiment runs, causal analyses, forecast
events, and model-evaluation artifacts. Immutable hashes and replay bindings
make these research/control files reviewable; they do not become execution
authority.

## Django Model Families

Observed model families:

- policy: principals, capabilities, restricted symbols, policy decisions
- orders: order tickets, checks, approval receipts, execution results, broker order timeline, fills, order events
- portfolio: snapshots, positions, cash, versioned paper state, ledger events, sync runs, reconciliation runs
- integrations: adapter definitions, broker connections, accounts, instrument maps
- workflows: workflow runs and artifact references
- MCP: tool definitions, tool calls, external MCP registry/review/call rows
- harness: workspace provenance
- audit: append-only audit events

Research artifacts are intentionally file-native and do not have a Django research model surface.

## Design Constraints

- No Node root, package workspace, React build, or Node MCP runtime in the core package.
- No per-interface policy/order/approval/execution forks.
- No workspace-local canonical investment DB by default.
- No hidden prompt, skill, policy, hook, or generated contract text inside Python string constants when it should be reviewed by humans or Codex.
- No managed overlay may remove or weaken core quality, evidence, policy, approval, execution, audit, or provenance requirements.
- No globally installed or plugin-provided host skill belongs to the pristine baseline without explicit user opt-in for the current workflow or managed activation.
- Do not describe workspace projection as hard runtime skill isolation until clean-host, populated-host, name-collision, and invocation tests attest it.
- Keep method profiles distinct: general evidence, event research, quant-signal validation, and listed-equity FCFF DCF do not share one universal artifact contract.
