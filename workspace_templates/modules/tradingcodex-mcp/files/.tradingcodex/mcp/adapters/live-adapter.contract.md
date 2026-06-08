# Live Adapter Contract

Initial TradingCodex does not ship a live broker adapter.

A user-installed live adapter must:

- run behind TradingCodex MCP
- not expose raw broker request tools
- read credentials only from the MCP process environment or user-managed secret manager
- reject unsupported actions fail-closed
- return structured execution results
- write audit events through TradingCodex MCP

Required adapter function:

```js
export async function submitOrder(order, context) {
  return {
    adapter: "live",
    broker_order_id: "string",
    status: "accepted | filled | rejected",
    submitted_at: new Date().toISOString()
  };
}
```
