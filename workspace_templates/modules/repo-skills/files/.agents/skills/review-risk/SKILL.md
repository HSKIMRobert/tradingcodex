---
name: review-risk
description: "Review investment and order risk before drafting or approving an order. Use by risk-manager for downside cases, sizing limits, liquidity, volatility, policy constraints, and go/revise/reject decisions."
---

# Review Risk

Role ownership: use by `risk-manager`. `head-manager` must not use this skill for direct risk review; it should assign `risk-manager`.

Use this skill before order intent creation, approval, sizing/hedge decisions, or policy-sensitive escalation.

Universe method:

- Identify asset universe, instrument, intended exposure, unwanted risk, and installed workflow support.
- For public equity and ETF/index, review downside, catalyst risk, liquidity, concentration, factor/sector exposure, and policy constraints.
- For crypto, macro/rates/FX/commodities, options, credit signals, and cross-asset overlays, name instrument-specific risk inputs that are missing, such as funding, roll, duration, basis, venue, custody, borrow, margin, spread, or Greeks.
- If the universe or instrument is not supported by installed skills, data, policy, and adapter boundaries, classify as `not-decision-ready` or `blocked`.

Expected output:

- Universe, instrument, and risk posture
- Downside case
- Thesis break conditions
- Position sizing limit
- Liquidity and volatility risk
- Policy constraints
- Approval readiness concerns
- Go, revise, or reject recommendation
- Source/as-of posture and implementation-readiness gaps

Quality floor:

- Apply the risk, uncertainty, and anti-hallucination floor from `scenario-quality-gates`.
- Tag material narrative claims as `[factual]`, `[inference]`, or `[assumption]`.
- State the largest failure mode first.
- Distinguish investment risk, portfolio risk, policy risk, and execution risk.
- Include support gap, stale data, or missing source status when it changes readiness.
- Include explicit stop/revisit conditions when the user asks for decision support.
- Lower confidence when data quality, sample size, regime coverage, or validation setup is weak.
- Give a clear go, revise, reject, or blocked state with reasons.
- Do not approve from this skill.

Write outputs under `trading/reports/risk/`.

Do not approve or submit orders from this skill. Use `approve-order` for approval receipts.
