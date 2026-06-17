---
name: use-tradingcodex-server
description: Operate TradingCodex Server broker connectors and MCP setup. Use when the head-manager needs to attach, register, inspect, validate, troubleshoot, or explain native broker/API connectors across equities, ETFs, options, futures, FX/CFD, crypto, fixed income, funds, or cash without granting execution authority.
---

# Use TradingCodex Server

## Overview

Use this skill to manage TradingCodex itself: project MCP setup, native broker connector registration, capability profile review, read-only account sync, order translation preview, and doctor recovery. This skill does not authorize analysis, approval, execution, cancellation, secret access, or direct broker API calls.

## Load References

- For connector/profile JSON shape, read `references/capability-profile.md`.
- For asset-class order fields and support boundaries, read `references/asset-classes.md`.
- For broker family templates, read `references/connector-templates.md`.
- For permission, secret, approval, and execution boundaries, read `references/safety-runbook.md`.
- For failed checks, stale profile, credential, rate-limit, or preview issues, read `references/troubleshooting.md`.

Load only the reference needed for the current task.

## Safe Workflow

1. Inspect TradingCodex status and current connector state.
2. List connector templates before registering anything new.
3. Register connectors with `credential_ref` only; never request, read, echo, or store raw keys.
4. Inspect the resulting capability profile and blocked surfaces.
5. Validate profile JSON with `scripts/validate_connector_profile.py` when a profile payload is available.
6. Run health checks and read-only sync before using account, position, or order-read data.
7. Use `preview_order_translation` and `run_order_checks` for readiness; treat preview output as validation only.
8. Route approval work to `risk-manager` and execution work to `execution-operator`.

## Useful Commands

```bash
./tcx doctor
./tcx mcp call list_broker_connector_templates --principal head-manager
./tcx mcp call register_broker_connector --principal head-manager --template alpaca_rest --broker-id alpaca-paper --credential-ref env:ALPACA_PAPER --environment paper
./tcx mcp call get_broker_capability_profile --principal head-manager --broker-id alpaca-paper
./tcx mcp call get_broker_instrument_constraints --principal head-manager --broker-id alpaca-paper --symbol AAPL
./tcx mcp call preview_order_translation --principal head-manager '{"broker_id":"alpaca-paper","symbol":"AAPL","side":"buy","quantity":1,"order_type":"limit","limit_price":180,"time_in_force":"day"}'
```

## Hard Stops

Stop and report blocked reasons if the user asks head-manager to:

- add broker MCP servers directly to `.codex/config.toml` or `.codex/agents/*.toml`
- call raw broker APIs or SDKs from shell, hooks, scripts, or ad hoc code
- submit, cancel, replace, transfer, withdraw, create deposit addresses, mutate API keys, perform KYC/account-opening, or handle travel-rule actions
- read or save raw broker credentials, tokens, passwords, seed phrases, or `.env` secrets
- bypass TradingCodex policy, approval, idempotency, adapter, or audit checks
