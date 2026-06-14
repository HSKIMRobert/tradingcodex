---
name: execute-paper-order
description: "Submit an approved paper or stub OrderTicket through the workspace MCP execution boundary when a matching approval receipt already exists."
---

# Execute Paper Order

Use through the configured role skill map. This file describes the execution handoff; it does not grant permission to bypass role, policy, or MCP boundaries.

Use this skill only with an approved OrderTicket and a valid approval receipt
whose exact order payload hash still matches the current ticket payload.

Universe and adapter gate:

- Reconfirm that the approved OrderTicket, approval receipt, policy decision, broker/adapter, and instrument support all match.
- Paper/stub execution can support only the instruments represented by the installed adapter contract.
- If the approved artifact references an unsupported live, account, margin, options, futures, crypto account, FX, commodity, or credit execution path, stop and report the mismatch.

Execution path:

1. Fetch the ticket with `get_order_ticket`.
2. Validate the order ticket payload and approval receipt.
3. Call the workspace MCP execution tool `submit_approved_order` with `ticket_id`.
4. Confirm the ticket timeline records reservation, submit, ack/fill/reject state.
5. Confirm an audit event was written.

Rules:

- Paper execution still goes through the workspace MCP execution boundary.
- Approval receipt should be issued by `risk-manager`, not by the order creator.
- Do not call broker APIs directly.
- Do not read API keys.
- Do not change policy in the same workflow.
- If validation fails, stop and write the rejection reason; do not attempt a workaround.
- If universe/instrument or adapter support fails, stop rather than falling back to a direct broker or shell path.
- Report execution status, adapter, ticket id, broker order/fill state, and audit trail reference.
