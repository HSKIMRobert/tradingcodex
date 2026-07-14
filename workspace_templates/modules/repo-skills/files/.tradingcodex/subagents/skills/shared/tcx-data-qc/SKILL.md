---
name: tcx-data-qc
description: "Check dates, units, currency, market anchors, formulas, and stale-data gaps before numbers drive investment reasoning."
---

# Numeric Data QC

Use this procedure when numeric data, valuation inputs, market anchors,
portfolio exposure, or risk limits affect readiness.

Required output shape:

- source date and retrieval date
- period alignment
- units and currency
- share count and per-share consistency when relevant
- source versus derived versus assumption labels
- current price or market anchor with as-of posture when relevant
- formula sanity checks
- stale or missing data readiness downgrade

Quality floor:

- Do not mix periods, units, currencies, or share bases silently.
- Label derived calculations and assumptions.
- Do not fabricate prices, metrics, formulas, or retrieval timestamps.
- Downgrade readiness when market anchors, source dates, or key numeric inputs
  are missing or stale.

Put the data-quality result near the top of the artifact so synthesis can see
whether numeric claims are decision-ready.
