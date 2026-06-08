---
name: create-order-intent
description: "Create a structured draft order_intent JSON artifact. Use only for portfolio-manager order drafting after research, valuation, portfolio, and risk context exist; never for approval or execution."
---

# Create Order Intent

Role ownership: use by `portfolio-manager`. `head-manager` must not draft order intents directly; it should assign `portfolio-manager`.

Use this skill only after research, valuation, portfolio, and risk artifacts exist.

Output a structured `*.order_intent.json` file under `trading/orders/draft/`.

Universe and adapter gate:

- Confirm the universe and instrument are supported by the current order schema, policy, broker/adapter path, and user request.
- Default paper/stub support does not imply live broker, options, futures, crypto account, margin, short borrow, FX, commodity, or credit-instrument execution support.
- If the requested instrument cannot be represented by the installed order intent schema and adapter, write a revise/block reason instead of drafting.
- Use support/readiness labels from `investment-workflow-map`; `screen-grade` and `not-decision-ready` cannot become draft orders.

Required fields:

- `id`
- `symbol`
- `side`
- `quantity`
- `limit_price`
- `currency`
- `broker`
- `estimated_notional_krw`
- `created_by`
- `created_at`

Rules:

- `created_by` must be `portfolio-manager`.
- Default `broker` is `paper-trading`.
- Live broker adapters are not installed by default.
- Do not fabricate missing prerequisite analysis, prices, quantities, costs, portfolio state, approval state, or user constraints.
- Do not fabricate instrument support, adapter support, borrow/locate, option terms, margin terms, funding rates, or account eligibility.
- In narrative handoffs, tag material claims as `[factual]`, `[inference]`, or `[assumption]`; do not add non-schema claim tags inside the JSON order intent.
- Do not submit the order.
- Do not approve your own order intent.
- Run `./tradingcodex validate order trading/orders/draft/<file>.order_intent.json` after creating the file.
- Include a note in the handoff that approval and execution are separate gates.
- If prerequisites are missing, write a revise/block reason instead of drafting.
