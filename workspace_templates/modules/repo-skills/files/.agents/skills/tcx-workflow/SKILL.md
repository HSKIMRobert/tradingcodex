---
name: tcx-workflow
description: Coordinate TradingCodex operate-plane investment workflows from compact hook context without duplicating role manuals or execution policy.
---

# TCX Workflow

Use this skill when a user asks for investment analysis, decision support, portfolio/risk review, order drafting, approval review, or non-live execution status.

## Procedure

1. Read the latest hook context from `.tradingcodex/mainagent/latest-user-prompt-gate.json` when compact context is insufficient.
2. Treat `routing_status.lane`, `selected_team`, and `blocked_actions` as binding for the current turn.
3. Respect explicit constraints and negations before applying defaults.
4. Dispatch or reuse only the selected fixed-role subagents when role output is required.
5. Pass compact assignment envelopes: original request, constraints, lane, artifact target, expected handoff state, decision-quality flags, and blocked actions.
6. Require the Decision Quality Spine fields described in `references/decision-quality-spine.md` when they are in scope.
7. Synthesize only accepted artifacts; preserve disagreements and stop with `waiting`, `revise`, or `blocked` when quality gates fail.

## Hard Stops

- Do not produce substantive investment analysis before required role outputs exist.
- Do not widen the selected team without a new user request.
- Do not create approval or execution artifacts from natural language alone.
- Do not change TradingCodex build mode, policy, MCP allowlists, or broker execution posture while producing investment judgment.
