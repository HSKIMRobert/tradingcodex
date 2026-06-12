---
name: strategy-creator
description: "Create, update, validate, and activate user-approved TradingCodex strategy skills named `strategy-*` when the user wants an agent-readable investment strategy, strategy library entry, entry/exit criteria, sizing rule, evidence standard, or decision-ready procedure."
---

# Strategy Creator

Use this skill to create or update strategy skills. A strategy skill is a Codex-compatible skill whose `name` starts with `strategy-`, stored outside project-scope `.agents/skills` under `.tradingcodex/strategies`. It captures a user-approved investment strategy as an agent-readable operating procedure.

Strategy skills guide judgment only. They never approve orders, execute orders, override policy, change MCP allowlists, bypass role boundaries, read secrets, or grant broker authority.

## Workflow

1. Identify whether the request creates a new strategy or updates an existing `strategy-*` skill.
2. Choose a short lowercase hyphen-case `name` with the required `strategy-` prefix.
3. Use `$skill-creator` for generic skill authoring mechanics, then apply the TradingCodex strategy boundaries in this skill.
4. Prefer `tcx strategies create|update|activate|archive|delete`, Django web, or API actions so validation and projection run through the shared service.
5. When repairing manually, create or update `.tradingcodex/strategies/<strategy-name>/SKILL.md` and `agents/openai.yaml`.
6. Add or refresh the strategy `[[skills.config]]` block in `.codex/config.toml` inside the TradingCodex strategy marker block.
7. Leave fixed subagent TOML files unchanged.
8. Ask for user approval before changing a strategy from draft to active.

## Required Skill Shape

Use this folder shape:

```text
.tradingcodex/strategies/strategy-<name>/
  SKILL.md
  agents/openai.yaml
```

`SKILL.md` frontmatter must include these scalar fields, and `name` must match the strategy directory name:

```yaml
---
name: strategy-<name>
description: "<what this strategy does and when to use it>"
type: strategy
status: draft
language: <BCP-47 language tag or unknown>
managed_by: strategy-creator
owner: user
last_reviewed: unknown
---
```

Set `status: active` only after the user approves the strategy. Use `draft`, `active`, or `archived`.

## Required Body Sections

Keep the body concise and include these headings:

- `# <Strategy Name>`
- `## Thesis`
- `## Eligible Universe`
- `## Preferred Setups`
- `## Entry Criteria`
- `## Exit Criteria`
- `## Evidence Requirements`
- `## Decision-Ready Standard`
- `## Sizing Guidance`
- `## Block Conditions`
- `## Portfolio And Risk Handoff`
- `## Change Log`

Use `unknown` or `not specified` for missing user input. Do not invent strategy rules.

## Metadata

`agents/openai.yaml` must include:

```yaml
interface:
  display_name: "<human strategy name>"
  short_description: "<25-64 character UI description>"
  default_prompt: "Use $strategy-<name> to apply this user-approved strategy."
policy:
  allow_implicit_invocation: true
```

The default prompt must mention the exact `$strategy-<name>` name.

## Root Config Projection

Add active strategy skills to `.codex/config.toml` in this marker block:

```toml
# BEGIN TradingCodex strategy skills
[[skills.config]]
path = "/absolute/path/to/.tradingcodex/strategies/strategy-<name>/SKILL.md"
enabled = true
# END TradingCodex strategy skills
```

Do not add strategy skills to fixed subagent TOML files. The coordinator reads the selected strategy and passes only role-safe `strategy_context` in assignment briefs.

## Validation

Before handoff, confirm:

- The name starts with `strategy-`.
- The frontmatter `name` matches the `.tradingcodex/strategies/<name>/` directory.
- Required frontmatter is present.
- Required body sections are present.
- `agents/openai.yaml` has a valid default prompt with the exact strategy name.
- Active strategies are listed in the root strategy marker block.
- Fixed subagent TOML files do not reference the strategy.
- The strategy states that policy, approval, MCP validation, and execution gates remain higher priority.
