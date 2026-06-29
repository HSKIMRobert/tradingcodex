---
name: anti-overfit-validation
description: "Review backtests, signals, and model-performance claims for leakage, data snooping, costs, capacity, and live friction."
---

# Anti-Overfit Validation

Use this procedure when a workflow reviews a backtest, signal, model result,
technical rule, or paper-alpha claim.

Required output shape:

- look-ahead leakage
- survivorship bias
- data snooping and multiple testing
- walk-forward or out-of-sample coverage
- transaction costs, slippage, borrow, funding, and taxes where relevant
- liquidity and capacity constraints
- regime sensitivity
- signal decay
- paper alpha versus live implementation friction

Quality floor:

- Treat validation as review, not strategy creation.
- Mark unsupported performance claims `not-decision-ready`, `revise`, or
  `blocked`.
- Do not imply execution readiness from a chart, backtest, or signal alone.
- Separate empirical performance from economic plausibility.

Write the anti-overfit result into the artifact whenever signal or model
performance claims are in scope.
