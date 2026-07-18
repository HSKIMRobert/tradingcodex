# Safety And Execution Source Map

Canonical behavior: [Safety, Policy, And Execution](../docs/safety-policy-and-execution.md)
and [Guardrails](../docs/guardrails.md).

## Primary Sources

| Concern | Source |
| --- | --- |
| Policy and restricted actions | `tradingcodex_service/application/policy.py` |
| Order lifecycle and idempotency | `tradingcodex_service/application/orders.py` |
| Explicit final-action admission | `tradingcodex_service/application/execution_gateway.py` |
| Broker connections and provider effects | `tradingcodex_service/application/brokers.py` |
| Approval and execution models | `apps/orders/`, `apps/integrations/`, `apps/audit/` |
| Hook pre/post-use enforcement | `workspace_templates/modules/codex-base/files/.codex/hooks/tradingcodex_hook.py` |
| MCP visibility and protected calls | `tradingcodex_service/mcp_runtime.py` |
| Read-only viewer boundary | `tradingcodex_service/web.py`, `viewer_api.py`, `application/viewer.py` |

## Non-Negotiable Boundary

Analysis prose never becomes a broker effect. Final submit or cancel requires
explicit user authority and the canonical service path:

```text
explicit authority
  -> identity and permission
  -> current policy and payload checks
  -> canonical approval
  -> idempotency/effect reservation
  -> broker connection
  -> result and audit finalization
```

An uncertain external effect is never blindly retried. Secrets never appear in
files, prompts, shell output, APIs, MCP, artifacts, viewer data, or audit
payloads. The viewer remains read-only.

## Simplification Boundary

Native Codex permissions should handle ordinary workspace, shell, Git, web,
skill, plugin, and MCP activity. TradingCodex-specific hooks and grants are
justified only for secrets, protected ledger state, broker access, approvals,
and final effects. Remove command-language mini-runtimes and duplicate policy
checks when the native permission system or canonical service already owns the
boundary.

Paper is the concrete default provider. Do not build a generic live-provider
platform until a real supported provider needs the shared abstraction.
User-installed Codex capabilities remain user-managed and cannot mint
TradingCodex identities, approvals, or execution proof.

## Edit Checklist

- Trace every final-effect caller to the canonical service function.
- Verify permission, approval, idempotency, uncertain-effect, and audit behavior
  before reducing a safety path.
- Keep credential values outside process output and persisted records.
- Confirm role, API, MCP, CLI, and viewer surfaces cannot bypass the boundary.
- Prefer one explicit execution path over several equivalent prompt grammars.

## Validation

Run focused policy/order/broker tests, `python manage.py check` when Django
wiring changes, MCP visibility checks, malformed/unauthorized call tests,
idempotency and uncertain-effect tests, secret-redaction checks, and a viewer
no-mutation check.
