---
name: investor-context
description: "Interview the user to create, inspect, update, enable, disable, or clear workspace-local investor suitability context. Use when the user explicitly asks to manage the objective, horizon, loss capacity, liquidity needs, holdings or concentration, or tax, account, and jurisdiction constraints applied to future workflows."
---

# Investor Context

Manage `.tradingcodex/user/investor-context.md` through the workspace launcher.
This file is optional, belongs only to the current workspace, and guides
suitability context without granting investment or execution authority.

## Procedure

1. Run `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} investor-context status` before an
   interview or update.
2. Ask only for missing or changed fields, in small batches. Keep confirmed
   answers separate from `unknown`, `not provided`, or `declined` values.
3. Cover only the fields relevant to investment suitability:
   - investment objective
   - time horizon
   - risk tolerance and loss capacity
   - liquidity needs
   - current holdings and concentration not already represented by canonical
     portfolio state
   - tax, account, or jurisdiction constraints
4. Preview the proposed changes and obtain user confirmation before the first
   durable write or before replacing confirmed values.
5. Save confirmed values with
   `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} investor-context update` and the
   corresponding options. Use `enable`, `disable`, or `clear` only when the user
   explicitly asks for that persistent change.
6. Re-run `status` and report configured fields, default application state,
   updated time, and file path without echoing unnecessary sensitive detail.

`enable` and `disable` control the workspace default. Native Codex workflows use
that default when the hook records intake and seal applied context under the
run. Workbench scope review alone provides a one-run apply/ignore override; it
does not mutate the saved default. After native intake exists, do not claim that
chat wording changed its binding. Disabling context permits general research,
but personalized recommendation, portfolio fit, sizing, and order readiness
must remain limited or blocked when required suitability fields are unavailable.

## Privacy And Safety

- Do not store broker credentials, account numbers, tax identifiers, API keys,
  passwords, tokens, seed phrases, private keys, or raw secret material.
- Prefer high-level constraints or ranges over unnecessary personal financial
  detail.
- Do not duplicate canonical cash, positions, orders, or broker account state
  in the context file.
- Do not infer answers from browsing, portfolio performance, or prior agent
  prose. Only user-confirmed legacy fields may be migrated.
- Do not use investor context to weaken evidence, role, policy, approval,
  execution, or audit gates.
- Do not pass the full file to specialist tasks. Apply only the compact fields
  needed for the current workflow; execution receives no suitability narrative.
