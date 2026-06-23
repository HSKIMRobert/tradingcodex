---
name: investment-workflow-map
description: "Map investment requests across asset universes into workflow context, source posture, hero artifacts, support gaps, and conservative readiness labels."
---

# Investment Workflow Map

Use this skill to describe what kind of investment work the request implies
before scenario selection.

## Boundary

- Covers universe classification, workflow context, source/as-of
  posture, hero/support artifact choice, support gaps, and readiness labels.
- Scenario selection, role team, blocked actions, dispatch mechanics, and final
  synthesis belong to later workflow steps.
- Readiness labels are quality states, not permissions or execution authority.

## Universe Boundary

- Public equities, ADRs, ETFs, indices, and listed options.
- Public crypto market research and non-live validation workflows when no account access
  or trading API is exposed.
- Macro, rates, FX, commodities, and cross-asset overlays as research, thesis,
  or portfolio-risk inputs.
- Credit, convertibles, preferreds, and capital-structure signals only when
  support exists; otherwise mark support gaps.
- Private markets, funds, tax, legal, and regulated advice are out of scope
  unless explicit skills and policies are installed.

## Source Posture

For market-sensitive work, identify:

- source categories and unavailable sources
- freeze time, source date, or retrieved-at time
- issuer claims, reported facts, provider data, user inputs, derived
  calculations, and assumptions
- stale, missing, conflicting, delayed, or credential-gated evidence

Never imply access to a provider, account, internal system, or live feed that is
not callable in the current runtime.

## Hero And Support Artifacts

- Research-heavy work: report, memo, thesis update, catalyst calendar, or
  evidence pack.
- Model-heavy work: workbook or model artifact with a visible decision summary.
- Support work: source indexes, normalized CSVs, run logs, manifests, issue
  logs, and raw JSON unless the user asks for them directly.

## Readiness Labels

- `factual-baseline`: source-backed context only.
- `screen-grade`: useful for prioritization, but missing load-bearing evidence.
- `not-decision-ready`: missing current price, source dates, base case,
  probabilities, portfolio context, instrument support, or implementation
  inputs required for the user's decision.
- `ready-for-portfolio-risk`: enough research, valuation, or market context
  exists for sizing, fit, or risk review.
- `ready-for-draft`: portfolio and risk prerequisites exist and the user asks
  for a draft order ticket.
- `blocked`: restricted list, secrets, direct broker access, unsupported live
  execution, unsupported instrument execution, policy-change-plus-execution, or
  missing required approval path.

## Output

```text
Universe: <asset/universe>
Workflow context: <research / thesis / portfolio-risk / order-path / postmortem / administration>
Source posture: <as-of, source classes, gaps>
Hero artifact: <reader-facing artifact>
Support files: <support artifacts or none>
Support gaps: <missing coverage>
Readiness: <label>
```
