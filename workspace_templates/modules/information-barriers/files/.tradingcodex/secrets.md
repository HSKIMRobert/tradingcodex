# Secret Wall

Do not store broker API keys, broker API secrets, tokens, or private keys in this workspace.

Agents do not read raw secrets.

`execution-operator` requests approved execution through TradingCodex MCP.

TradingCodex MCP reads secrets from its process environment or a user-managed secret manager when a user-installed live adapter exists.
