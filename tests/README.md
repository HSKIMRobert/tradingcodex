# TradingCodex Tests

Primary validation:

```bash
pytest
python manage.py check
python -m compileall tradingcodex_cli tradingcodex_service apps tests
```

The Python migration smoke suite covers:

- workspace generation contract
- attach/init-time central Django DB setup without workspace-local DB creation
- immutable workspace identity, internal paper-account scope, and optional
  workspace investor-context metadata
- ten fixed subagents and twenty-eight core repo skills
- default user-facing skill listing separated from full internal skill inventory
- starter prompt routing for negated execution requests
- starter prompt routing for guardrail-verification wording and earnings/catalyst thesis review
- order ticket validation, approval, and paper execution
- approved-order idempotency so repeated submission is rejected before portfolio mutation
- DB-backed Principal/Capability enforcement before MCP handler dispatch and policy decisions
- restricted symbol and disabled live adapter blocking
- MCP initialize/tools/list/tools/call surfaces
- MCP registry metadata, External MCP Gate lifecycle, role-gated tool calls, JSON-RPC batch handling, and non-research DB tool-call ledger
- service-layer MCP registry helpers creating audit events outside custom Admin actions
- generated `mcp ledger` inspection of central DB tool-call history for non-research tools
- two generated workspaces keeping separate research markdown/source-snapshot files while sharing central non-research runtime state
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
