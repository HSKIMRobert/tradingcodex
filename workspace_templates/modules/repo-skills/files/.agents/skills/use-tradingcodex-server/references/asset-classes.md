# Asset Classes

Use this reference to choose the right canonical order fields and support posture.

## Equities And ETFs

- Identity: ticker plus venue/exchange when needed.
- Quantity: shares or notional for fractional-capable brokers.
- Common fields: `symbol`, `side`, `quantity`, `quantity_mode`, `order_type`, `limit_price`, `time_in_force`, `session`.
- Risks: shorting, fractional support, extended-hours routing, locate requirements.

## Options

- Identity: OCC symbol or broker contract id.
- Quantity: contracts.
- Common fields: `legs`, `option_symbol`, `underlying`, `expiration`, `strike`, `put_call`, `ratio`, `order_type`, `time_in_force`.
- Multi-leg spreads require broker preview and product-specific approval gates.

## Futures

- Identity: futures root, expiry, exchange, contract id.
- Quantity: contracts.
- Common fields: `contract`, `side`, `quantity`, `order_type`, `limit_price`, `time_in_force`, `margin_mode`.
- Risks: leverage, session, exchange limits, liquidation and margin calls.

## FX And CFD

- Identity: currency pair or CFD symbol.
- Quantity: units, lots, or notional depending on venue.
- Common fields: `instrument`, `side`, `quantity`, `quantity_mode`, `order_type`, `trigger_condition`, `margin`.
- Risks: dealer execution, leverage, financing, region restrictions.

## Crypto Spot And Derivatives

- Identity: pair such as `BTCUSDT`, `KRW-BTC`, or product id.
- Quantity: base quantity or quote notional.
- Common fields: `base_asset`, `quote_asset`, `quantity_mode`, `quote_notional`, `order_type`, `time_in_force`, `stp_or_smp`.
- Risks: symbol filters, min notional, locked balances, per-account rate limits, withdrawals, travel rule.

## Fixed Income, Funds, And Cash

- Start read-only and profile-first.
- Execution requires product-specific suitability, pricing, settlement, and approval rules before any live adapter work.
