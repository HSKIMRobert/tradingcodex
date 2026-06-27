---
name: tcx-build
description: Use TradingCodex build mode for self-update, harness/template changes, and broker/API provider scaffold or implementation without submitting live orders.
---

# TCX Build

Use this skill when the user asks to update TradingCodex itself, rewrite harness/templates/skills, or add a broker/API provider for a broker they named.

## Build Gate

Proceed only when both are true:

- Codex permission is full access.
- TradingCodex mode is build and not expired.

If either is false, explain the exact blocker and provide `tcx mode set build --reason <reason>` or the terminal command. Do not perform build work.

## Procedure

1. Confirm the request is product/build work, not an investment recommendation or execution request.
2. For self-update, use the command from `update_status.command` only after an explicit user request; then stop and tell the user to fully restart Codex.
3. For connectors, use provider-first commands: `tcx connectors providers`, `tcx connectors scaffold <broker-id>`, `tcx connectors register --provider <provider-id> --broker-id <id> --credential-ref env:<REF> --environment <env>`, and `tcx connectors validate <broker-id>`.
4. Store only credential references and secret schemas. Never request or persist raw credentials.
5. If the requested provider is not installed, treat the task as provider development or scaffold a provider-development-required connector; do not pretend the broker is already supported.
6. Validate with focused tests, `./tcx doctor`, and generated-workspace smoke checks when harness surfaces changed.

## Hard Stops

- Build mode may create live-capable providers, but never submits live orders.
- Do not call raw broker APIs from shell, hooks, skills, or ad hoc scripts.
- Do not bypass TradingCodex policy, approval, idempotency, connection, or audit gates.
