---
name: tradingcodex-operator
description: Compatibility entrypoint for older TradingCodex operator prompts. Prefer use-tradingcodex-server for broker connector management, TradingCodex MCP setup, doctor checks, and safe connector inspection.
---

# TradingCodex Operator

Use `$use-tradingcodex-server` for current TradingCodex Server connector setup, MCP checks, doctor recovery, capability profile review, and broker/API connector troubleshooting.

This compatibility skill remains for one release cycle so older prompts still resolve. It does not grant execution, approval, broker API, or secret authority.

## Required Routing

- Load `.agents/skills/use-tradingcodex-server/SKILL.md`.
- Follow its reference selection rules.
- Use TradingCodex canonical MCP tools only.
- Do not add broker-specific MCP servers or raw broker tools to Codex config.
