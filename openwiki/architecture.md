# Architecture Source Map

Canonical behavior: [Product Direction](../docs/product-direction.md) and
[System Architecture](../docs/system-architecture.md).

## Ownership

| Concern | Primary source |
| --- | --- |
| Durable use cases | `tradingcodex_service/application/` |
| Central ledger models | `apps/*/models.py` |
| Workspace attachment and projection | `tradingcodex_cli/generator.py`, `tradingcodex_cli/runtime.py` |
| MCP tool exposure | `tradingcodex_service/mcp_runtime.py` |
| Local API and viewer | `tradingcodex_service/api.py`, `viewer_api.py`, `application/viewer.py`, `web.py` |
| Agent and skill projection | `tradingcodex_service/application/agents.py` and `workspace_templates/` |
| Sensitive final actions | `application/policy.py`, `orders.py`, `execution_gateway.py`, `brokers.py` |
| File-native research | `application/research.py`, `datasets.py`, `calculations.py` |

## State Placement

Central service state includes portfolio, account, policy, approval, order,
broker, execution, MCP audit, and append-only audit records. Workspace state
includes generated Codex configuration and reviewable research evidence.

Do not create a second authoritative store. Rebuildable indexes and viewer
snapshots are projections; prompts, skills, and hooks are not ledgers.

## Architecture Rules

- Codex owns reasoning, research strategy, tool selection, and delegation.
- Django owns durable records and deterministic sensitive-effect gates.
- Interfaces call application services; they do not fork business logic.
- Workspace research stays readable and provenance-bound.
- The browser viewer remains read-only and starts no Codex process.
- Generated workspaces remain Node-free and isolated from release identities.
- Add abstractions only for current multiple implementations; otherwise keep a
  concrete path.

## Edit Sequence

1. Find the owning application service and every interface caller.
2. Confirm state ownership and trust boundaries in the canonical docs.
3. Make the smallest change at the shared owner.
4. Update schemas/interfaces only when the public contract changes.
5. Run the routed checks in
   [Development And Validation](development-and-validation.md).
