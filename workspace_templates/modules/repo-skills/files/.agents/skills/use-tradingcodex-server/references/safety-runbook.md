# Safety Runbook

TradingCodex Server connector management is operational work. It never grants investment, approval, or execution authority to head-manager.

## Head-Manager May

- inspect TradingCodex status and MCP configuration
- list connector templates
- register connectors with `credential_ref`
- inspect capability profiles and blocked surfaces
- run health checks, read-only sync, and translation previews
- ask portfolio/risk/execution roles for their owned work

## Head-Manager Must Not

- add raw broker MCP servers to Codex config
- call raw broker APIs or SDKs
- read, print, store, or transform raw secrets
- submit, cancel, replace, transfer, withdraw, or mutate account settings
- create API keys, deposit addresses, accounts, KYC records, or travel-rule requests
- approve its own order or use an execution skill directly

## Approved Action Boundary

All execution-sensitive actions must flow through:

```text
requester -> permission -> policy -> payload validation -> approval/duplicate-request check -> connection -> audit
```

Connector preview, broker dry-run, and order-test endpoints are validation inputs only. They do not replace risk approval or execution-operator submission.
