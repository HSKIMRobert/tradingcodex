---
name: execute-paper-order
description: "Submit or cancel an approved OrderTicket through the workspace MCP execution boundary when a matching approval receipt and required gates exist."
---

# Execute Approved Order Through Service Boundary

Use this skill only with an approved OrderTicket and a valid approval receipt
whose exact order payload hash still matches the current ticket payload.

Universe and adapter gate:

- Reconfirm that the approved OrderTicket, approval receipt, policy decision, broker/adapter, and instrument support all match.
- Supported default adapters are `paper-trading`, `stub-execution`, and reviewed validation providers with an allowed execution posture.
- Paper/stub execution can support only the instruments represented by the installed adapter contract.
- Live broker providers require all TradingCodex service gates: workspace config, policy, environment opt-in, enabled live AdapterDefinition, signed health, trading-enabled connection, exact approval receipt, explicit `live_confirmation`, idempotency, sync, and audit.
- If the approved artifact references an unsupported account, margin, options, futures, FX, commodity, credit, or live provider path, stop and report the mismatch.

Execution path:

1. Fetch the ticket with `get_order_ticket`.
2. Validate the order ticket payload and approval receipt.
3. Call the workspace MCP execution tool `submit_approved_order` with `ticket_id`; include `live_confirmation` only when the service/provider contract explicitly requires it.
4. Confirm the ticket timeline records reservation, submit, ack/fill/reject state.
5. Confirm an audit event was written.

Rules:

- Execution always goes through the workspace MCP execution boundary.
- If validation fails, stop and write the rejection reason; do not attempt a workaround.
- If universe/instrument or adapter support fails, stop rather than falling back to a direct broker or shell path.
- Report execution status, adapter, ticket id, broker order/fill state, and audit trail reference.
