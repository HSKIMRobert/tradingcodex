---
name: create-order-ticket
description: "Create a canonical draft OrderTicket after research, valuation, portfolio, and risk context exist."
---

# Create Order Ticket

Use through the configured role skill map. This file describes draft order
ticket creation; it does not grant permission to bypass role, policy, or MCP
boundaries.

Use this skill only after research, valuation, portfolio, and risk artifacts exist.

Primary output is a canonical `OrderTicket` created through the TradingCodex
service layer, normally via the workspace MCP tool `create_order_ticket`.

Universe and adapter gate:

- Confirm the universe and instrument are supported by the current order ticket schema, policy, broker/adapter path, and user request.
- Default paper/stub support does not imply live broker, options, futures, crypto account, margin, short borrow, FX, commodity, or credit-instrument execution support.
- If the requested instrument cannot be represented by the installed order ticket schema and adapter, write a revise/block reason instead of drafting.
- `screen-grade` and `not-decision-ready` work cannot become draft orders.

Required fields:

- `ticket_id`
- `symbol`
- `side`
- `quantity`
- `limit_price`
- `currency`
- `broker_id` or `broker_connection_id`
- `created_by`

Rules:

- `created_by` must be `portfolio-manager`.
- Default broker is `paper-trading`.
- Live broker adapters are not installed by default.
- Do not fabricate missing prerequisite analysis, prices, quantities, costs, portfolio state, approval state, or user constraints.
- Do not fabricate instrument support, adapter support, borrow/locate, option terms, margin terms, funding rates, or account eligibility.
- In narrative handoffs, tag material claims as `[factual]`, `[inference]`, or `[assumption]`; do not add non-schema claim tags inside the order ticket payload.
- Do not submit the order.
- Do not approve your own order ticket.
- Run the `run_order_checks` MCP tool after creating the ticket.
- Include the ticket id, current state, check results, and unresolved gaps in the handoff.
- Include a note that approval and execution are separate downstream gates.
- If prerequisites are missing, write a revise/block reason instead of drafting.
