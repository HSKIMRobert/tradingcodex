---
name: valuation-review
description: "Review valuation after research evidence exists. Use for valuation method selection, assumptions, market-implied expectations, scenario ranges, sensitivity, and valuation risk."
---

# Valuation Review

Use through the configured role skill map. This file describes the valuation work product; it does not grant permission to bypass role, policy, or MCP boundaries.

Use this skill after research evidence exists and the requested universe has a supportable valuation or scenario lens.

Universe method:

- Public equity: choose DCF, comps, reverse DCF, scenario, estimate revision, or event probability methods only when the evidence supports them.
- ETF/index: focus on exposure, constituent/benchmark, factor, flow, and valuation-through-holdings logic when data exists.
- Crypto, macro, FX, rates, commodities, options, and credit-sensitive workflows require instrument-specific methods; if the installed role skills cannot underwrite the method, produce a screen-grade valuation frame or handoff gap rather than a false precision model.
- Always state current price or market anchor source/as-of when the user asks for risk/reward, target, entry, or action.

Expected output:

- Universe and valuation method fit
- Valuation method used
- Key assumptions
- Market-implied expectation check
- Scenario range
- Sensitivity points
- Valuation risk
- What would change the valuation
- Source/as-of posture, unsupported assumptions, and model/readiness label

Quality floor:

- Apply the shared TradingCodex quality floor.
- Tag material narrative claims as `[factual]`, `[inference]`, or `[assumption]`.
- Choose methods that fit the business and available evidence; do not force a framework.
- State why each method is appropriate or limited.
- Include at least downside/base/upside scenario logic when evidence allows.
- Mark scenario inputs, cost assumptions, capacity assumptions, and modeling choices as `[assumption]`.
- Distinguish model output, derived calculation, consensus/provider data, user input, and PM judgment.
- Use `not-decision-ready` when current price, base case, valid probabilities, source dates, or instrument-specific assumptions are missing.
- State parameter sensitivity and lower confidence when the valuation range depends on fragile inputs.
- Separate valuation output from portfolio or execution recommendation.
- State what evidence would most change the range.

Write outputs under `trading/reports/valuation/`.

Do not approve or submit orders.
