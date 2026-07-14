# TradingCodex Tests

Primary validation:

```bash
pytest
python manage.py check
python -m compileall tradingcodex_cli tradingcodex_service apps tests
```

The Python platform smoke suite covers:

- workspace generation contract
- new-workspace attach and current-v1 central Django DB setup without
  workspace-local DB creation
- immutable workspace identity, internal paper-account scope, and optional
  workspace investor-context metadata
- nine fixed subagents and 30 core repo skills, including all three native
  execution bundles
- default user-facing skill listing separated from full internal skill inventory
- starter prompt routing for negated execution requests
- starter prompt routing for guardrail-verification wording and earnings/catalyst thesis review
- order ticket validation, approval, and paper execution
- approved-order idempotency so repeated submission is rejected before portfolio mutation
- exact `$tcx-order-allow` turn-grant binding, proof injection, single use,
  revocation, and direct-caller rejection
- read-only Admin exposure for canonical order-turn grants and execution ledgers
- DB-backed Principal/Capability enforcement before MCP handler dispatch and policy decisions
- restricted symbol and disabled live adapter blocking
- MCP initialize/tools/list/tools/call surfaces
- MCP registry metadata, External MCP Gate lifecycle, role-gated tool calls, JSON-RPC batch handling, and non-research DB tool-call ledger
- service-layer MCP registry helpers creating audit events outside custom Admin actions
- generated `mcp ledger` inspection of central DB tool-call history for non-research tools
- two generated workspaces keeping separate research markdown/source-snapshot
  files and isolated workspace/account scopes in the central runtime DB
- internal account-scope selection controlling paper portfolio separation
- Django Ninja health, harness, subagent, and policy endpoints
- file-native research artifact create/get/search/export through MCP, Ninja, and generated workspace CLI
- Django project checks

For template/bootstrap changes, also create a throwaway workspace and run:

```bash
SMOKE_ROOT="$(python -c 'import tempfile; print(tempfile.mkdtemp(prefix="tradingcodex-smoke-"))')"
mkdir -p "$SMOKE_ROOT/workspace"
cd "$SMOKE_ROOT/workspace"
tcx attach .
tcx workspace status
tcx investor-context status
./tcx doctor
```
