# Secret Wall

Do not store broker API keys, broker API secrets, tokens, or private keys in this workspace.

Agents do not read raw secrets.

Only an exact root native execution skill invocation can request approved
execution. The deterministic prompt hook validates it before calling the
service-owned execution boundary.

The TradingCodex service reads secrets from its process environment or a
user-managed secret manager when a user-installed live adapter exists. MCP does
not expose execution mutations.
