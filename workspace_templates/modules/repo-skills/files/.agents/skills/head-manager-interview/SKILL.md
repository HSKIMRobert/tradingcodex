---
name: head-manager-interview
description: "Interview the TradingCodex user to build, refresh, and apply a durable investor/operator profile for onboarding, investor profiling, risk tolerance assessment, tone calibration, suitability context, portfolio preference capture, or updates to `.tradingcodex/mainagent/head-manager-interview.md`."
---

# Head Manager Interview

Use this skill to interview the user and maintain the latest operator profile at `.tradingcodex/mainagent/head-manager-interview.md`.

The profile helps future TradingCodex workflows adapt risk framing, portfolio context, suitability checks, and response tone. It is guidance only. It never authorizes an order, approval, execution, policy exception, or broker action.

When calibrating questions or interpreting an incomplete profile, read `references/investor-profile-reference.md`.

## Workflow

1. Read `.tradingcodex/mainagent/head-manager-interview.md` if it exists.
2. Identify missing, stale, or user-updated fields.
3. Ask focused interview questions in small batches. Prefer ranges and summaries for sensitive financial data.
4. Separate confirmed answers from inferred preferences.
5. Update the same Markdown file as the latest summary; do not create dated logs unless the user explicitly asks.
6. Note `last_updated`, `next_review_due`, confidence, unresolved questions, and any sections intentionally skipped.
7. Use the updated profile in later workflow planning, subagent briefs, risk framing, and tone calibration.

Refresh the profile when the user asks, when major circumstances change, or when `next_review_due` has passed. Default review cadence is 12 months.

## Interview Domains

Cover these domains when relevant:

- Investment objectives, target outcomes, time horizon, and liquidity needs
- Detailed financial situation: income stability, assets, debts, emergency liquidity, tax considerations, and near-term obligations
- Investment knowledge, product experience, derivatives/leverage/margin experience, and decision authority
- Risk tolerance and risk capacity, including drawdown, loss, volatility, liquidity, and concentration thresholds
- Current portfolio context, sizing preferences, diversification constraints, and restricted assets or sectors
- Source preferences, markets, instruments, account limits, and operational constraints
- Decision style: how much detail, speed versus caution, uncertainty handling, and preferred recommendation tone
- Communication tone: direct, conservative, Socratic, quantified, narrative, Korean/English preference, and stress-response style

## Update Rules

Maintain the profile as a concise but complete Markdown artifact with these sections:

- Profile metadata
- Investment objectives and horizon
- Financial situation
- Knowledge and experience
- Risk tolerance and risk capacity
- Constraints and restrictions
- Portfolio context and sizing
- Decision style and tone
- Open questions and refresh items
- Change log

When updating, preserve useful prior context unless the user contradicts it. Mark contradictions explicitly before overwriting important fields.

Use `unknown`, `not provided`, or `declined` rather than inventing values. If a field is inferred, label it as an inference.

## Privacy And Safety

- Do not store broker credentials, account numbers, API keys, private keys, tokens, seed phrases, or raw secret material.
- Do not ask for raw broker credentials or authentication secrets.
- Prefer ranges or summarized balances unless the user explicitly provides exact figures.
- Store detailed financial context only when the user provides it voluntarily.
- Treat the profile as suitability context and tone guidance, not as regulated financial advice or a legal suitability determination.
- Never use the profile to bypass TradingCodex research, portfolio, risk, approval, execution, policy, MCP, or audit gates.
- If the user requests a higher-risk action than the profile supports, flag the mismatch and route through the normal TradingCodex workflow.

## Applying The Profile

Before investment workflow synthesis, check the profile for:

- objective and time-horizon fit
- liquidity or emergency-cash constraints
- risk tolerance versus risk capacity mismatch
- product experience gaps
- concentration or leverage limits
- tone and explanation preferences

Include only the profile details needed for the task in subagent briefs. Do not pass detailed financial context to research-only subagents unless it is necessary for their assignment.

If the profile is missing or stale, say so and either ask targeted refresh questions or proceed with conservative assumptions while marking the gap.
