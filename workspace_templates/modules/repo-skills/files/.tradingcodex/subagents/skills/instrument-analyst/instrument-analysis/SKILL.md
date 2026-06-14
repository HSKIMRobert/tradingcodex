---
name: instrument-analysis
description: "Analyze instrument mechanics, universe support, liquidity, contract terms, ETF/index methodology, options/derivatives context, crypto market structure, and credit-signal boundaries; never for order drafting or execution."
---

# Instrument Analysis

Use through the configured role skill map. This file describes the instrument mechanics work product; it does not grant permission to bypass role, policy, or MCP boundaries.

Use this skill when the workflow depends on instrument mechanics or support boundaries rather than only issuer fundamentals, price action, news, valuation, portfolio fit, or risk approval.

Universe method:

- Public equity and ETFs: review share class, ADR/ordinary mapping, index/ETF methodology, corporate actions, float, liquidity, borrow/crowding inputs when available, and settlement or market-structure issues.
- Options and derivatives context: review contract terms, expiry, Greeks, implied move, skew, liquidity, exercise/assignment, and margin/readiness gaps when data exists; do not recommend or execute derivatives.
- Crypto public markets: review venue fragmentation, spot/futures distinction, funding, custody/account gaps, liquidity, and public market data limits; no account or trading access.
- Credit signals, convertibles, preferreds, rates, FX, commodities, and other instruments: identify what can be used as research/risk evidence and what requires a dedicated installed workflow.

Expected output:

- Universe, instrument, and support status
- Instrument identifiers, venue/market convention, contract or methodology facts
- Liquidity, borrow/funding/options/settlement/market-structure evidence when relevant
- Unsupported execution or underwriting gaps
- Source/as-of posture and stale or missing inputs
- Readiness label: `factual-baseline`, `screen-grade`, `not-decision-ready`, `ready-for-portfolio-risk`, or `blocked`
- Handoff question for the next configured workflow role

Quality floor:

- Apply the shared TradingCodex quality floor.
- Tag material narrative claims as `[factual]`, `[inference]`, or `[assumption]`.
- Distinguish source-backed instrument facts from analyst assumptions and PM judgment.
- Never infer execution eligibility from research data availability.
- Do not fabricate contract terms, borrow, funding, Greeks, market levels, index weights, credit spreads, settlement terms, or source timestamps.
- If the installed schema, policy, or adapter cannot represent the instrument, label execution as `blocked` or `not-decision-ready`.

Write outputs under `trading/reports/instrument/`.

Never create an order ticket, approve orders, or submit orders.
