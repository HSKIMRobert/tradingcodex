# Capability Profile

`BrokerCapabilityProfile` is the connector contract behind TradingCodex MCP. It describes what a broker or exchange can do without exposing raw broker API operations to agents.

## Required Shape

```json
{
  "template_id": "alpaca_rest",
  "broker_id": "alpaca-paper",
  "venue": "broker",
  "region": "US",
  "asset_classes": ["equity", "etf", "option"],
  "products": ["spot", "option_single"],
  "environment": "paper",
  "execution_posture": "live_disabled",
  "auth_model": {"type": "api_key", "credential_ref_required": true},
  "account_model": {"multi_account": false, "balances": "cash", "positions": true},
  "instrument_model": {"identity": "symbol", "examples": ["AAPL", "SPY"]},
  "order_model": {"order_types": ["market", "limit"], "time_in_force": ["day", "gtc"]},
  "validation_model": {"preview": true, "dry_run": false},
  "event_model": {"polling": true, "streaming": false},
  "rate_limits": [],
  "blocked_surfaces": ["withdrawal", "transfer", "api_key_admin"]
}
```

## Status Fields

- `execution_posture`: `read_only`, `paper_only`, `live_disabled`, `service_adapter_required`, or `unsupported`.
- `enabled_read_scopes`: coarse DB index for read-only account, position, cash, order, and market-data scopes.
- `enabled_trade_scopes`: empty by default for native connectors; paper adapters may use `order.submit.paper`.
- `blocked_surfaces`: dangerous broker surfaces that must not become MCP tools.
- `drift_status`: `none`, `review_required`, or `schema_changed`.

## Blocked Surface Invariants

The following surfaces must stay blocked even if a broker API documents them:

- `withdrawal`
- `transfer`
- `deposit_address`
- `travel_rule`
- `api_key_admin`
- `account_opening`
- `kyc`
- `subaccount_admin`
- `raw_order_submit`
- `raw_order_cancel`

Use `scripts/validate_connector_profile.py` when a profile JSON payload needs a quick structural and safety check.
