---
name: head-manager-interview
description: "Interview the TradingCodex user to create, refresh, or apply the durable user profile at `.tradingcodex/user/profile.md`, including language, tone, experience, markets, risk posture, autonomy boundaries, hard constraints, approval requirements, and uncertainty preferences."
---

# Head Manager Interview

Use this skill to maintain `.tradingcodex/user/profile.md`. The profile is durable workspace context for language, output style, user constraints, and safe briefing. It is guidance only. It never authorizes an order, approval, execution, policy exception, MCP bypass, broker action, or secret access.

If `.tradingcodex/user/profile.md` is missing, read `.tradingcodex/mainagent/head-manager-interview.md` as a legacy fallback. Write updates only to `.tradingcodex/user/profile.md`.

## Workflow

1. Read the current profile, using the legacy fallback only when the new profile does not exist.
2. Identify missing, stale, or contradicted fields.
3. Ask only the questions needed for the current gap.
4. Keep confirmed answers separate from inferences.
5. Update `.tradingcodex/user/profile.md` as the latest summary.
6. Preserve useful prior context unless the user contradicts it.
7. Mark `unknown`, `not provided`, or `declined` instead of inventing values.

## Essential Questions

Ask from this set in small batches:

- `language`: Which language should default research reports and summaries use?
- `timezone`: Which timezone should dated workflow context use?
- `preferred_tone`: Should responses be concise, detailed, risk-first, table-first, Socratic, or another style?
- `output_format_preference`: Are tables, bullets, memos, or short conclusions preferred?
- `intended_use`: Should TradingCodex support research only, decision support, portfolio review, order drafts, or approved paper execution?
- `experience_level`: What investing experience level should the workspace assume?
- `markets_of_interest`: Which markets, asset classes, or instruments are usually in scope?
- `risk_attitude`: How should volatility, drawdown, concentration, leverage, and uncertainty be framed?
- `agent_autonomy_level`: How far may agents proceed without explicit confirmation?
- `never_do`: Which actions, instruments, markets, or recommendation styles are off limits?
- `approval_required_for`: Which steps always require user confirmation?
- `uncertainty_handling`: Should uncertainty lead to blocked status, more research, conservative framing, or scenario comparison?
- `source_detail_level`: How much source detail should reports include?

## Profile Shape

Keep the Markdown file concise and use these sections:

- Profile metadata
- Language and output preferences
- Intended use and autonomy
- Experience and markets
- Risk posture
- Constraints and hard stops
- Approval requirements
- Uncertainty handling
- Role-safe briefing fields
- Open questions
- Change log

## Role-Safe Use

Use the profile to prepare compact `profile_context` in briefs. Pass only fields needed for the assignment:

- All roles may receive language, timezone, tone, output format, market preference, and source detail level.
- Research roles should receive only non-sensitive formatting and market-scope context.
- Valuation, portfolio, and risk roles may receive relevant horizon, risk, sizing, and constraint context when needed.
- Execution should receive no strategy judgment or sensitive profile detail; use only approved artifacts, policy state, and MCP results.

Do not pass the full profile, account details, broker details, secrets, private financial information, or unrelated suitability context to subagents.

## Safety

- Do not store broker credentials, account numbers, API keys, private keys, tokens, seed phrases, or raw secret material.
- Prefer ranges or summaries for sensitive financial values.
- Do not use the profile to bypass research, portfolio, risk, approval, execution, policy, MCP, or audit gates.
- If a request conflicts with the profile, flag the mismatch and route through the normal workflow.
