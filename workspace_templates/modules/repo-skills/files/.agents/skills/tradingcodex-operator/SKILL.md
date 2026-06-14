---
name: tradingcodex-operator
description: Operate TradingCodex MCP, External MCP Gate, broker/data MCP lifecycle, role TOML projection, doctor checks, and dashboard/service recovery. Use when the primary operator needs to register or inspect external broker/data MCP connections, repair TradingCodex MCP config, run discovery, review read-only tool exposure, or explain why raw broker execution tools must not be attached directly to Codex.
---

# TradingCodex Operator

Use this skill to operate TradingCodex itself. Treat it as a runbook for configuration, lifecycle checks, and recovery. Do not treat it as authorization to bypass service policy.

## Core Boundary

- Keep Codex connected to the `tradingcodex` stdio MCP server only.
- Do not add broker/data MCP servers directly to `.codex/config.toml` or `.codex/agents/*.toml`.
- Register external broker/data MCP connections through TradingCodex External MCP Gate.
- Keep execution-like external tools blocked unless TradingCodex maps them to a service adapter path.
- Never read or store raw broker secrets; use `credential_ref` only.

## Common Operations

Check the TradingCodex workspace:

```bash
./tcx doctor
```

List TradingCodex MCP tools:

```bash
printf '{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n' | ./tcx mcp stdio
```

Register an external stdio MCP connection:

```bash
./tcx mcp external register --name broker-mcp --transport stdio --command "uvx broker-mcp" --enabled
```

Check and discover the connection:

```bash
./tcx mcp external check --name broker-mcp
./tcx mcp external discover --name broker-mcp
```

Review read-only tools only after discovery:

```bash
./tcx mcp external review-tool --tool-id 1 --proxy-mode summary_only --allowed-roles role-a,role-b --enabled
```

Repair projected agent configuration:

```bash
./tcx subagents project
```

## Review Rules

- Account-private read tools such as balances, positions, orders, fills, and buying power require TradingCodex review, role scope, and audit.
- Public market data/news/filings tools may remain lightweight, but when used in order, risk, approval, or portfolio decisions, record a source snapshot or research artifact.
- Execution-like tools such as place order, replace order, cancel order, trade, transfer, withdraw, deposit, or secret/admin tools must not be enabled as direct proxy.
- If schema drift appears, leave the tool disabled until reviewed.

## Handoff

Report:

- the connection name and transport
- whether check/discovery succeeded
- imported tool counts and blocked reasons
- which tools are safe read-only candidates
- which tools require adapter mapping
- whether `./tcx doctor` passes
