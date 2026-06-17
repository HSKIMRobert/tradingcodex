---
name: strategy-creator
description: "Create, update, validate, and activate standalone Codex strategy skills named `strategy-*` when the user wants an agent-readable investment strategy, strategy library entry, entry/exit criteria, sizing rule, evidence standard, or decision-ready procedure."
---

# Strategy Creator

Use this skill to create or update strategy skills. A strategy skill is a standalone Codex-compatible skill whose `name` starts with `strategy-`, stored as a normal project skill under `.agents/skills/strategy-*`. It captures a user-approved investment strategy as an agent-readable operating procedure and should remain usable without importing TradingCodex service code.

Strategy skills guide judgment only. They never approve orders, execute orders, override policy, change MCP allowlists, bypass role boundaries, read secrets, or grant broker authority.

The generated strategy body must be standalone. Do not mention platform names, platform role identifiers, subagent mechanics, MCP, approval gates, execution gates, or handoff mechanics inside the strategy skill. If a section has no user-provided rule, write `not specified` without adding a delegation sentence.

## Workflow

1. Identify whether the request creates a new strategy or updates an existing `strategy-*` skill.
2. Choose a short lowercase hyphen-case `name` with the required `strategy-` prefix.
3. Use `$skill-creator` for generic skill authoring mechanics, then apply the strategy boundaries in this skill.
4. Prefer `tcx strategies create|update|activate|archive|delete` or API actions when available so validation and projection run through the shared service.
5. When repairing manually, create or update `.agents/skills/<strategy-name>/SKILL.md` and `agents/openai.yaml`.
6. Add or refresh the strategy `[[skills.config]]` block in `.codex/config.toml` inside the strategy marker block.
7. Leave fixed subagent TOML files unchanged.
8. Ask for user approval before changing a strategy from draft to active.

## Required Skill Shape

Use this folder shape:

```text
.agents/skills/strategy-<name>/
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
- `## Risk Controls`
- `## Block Conditions`
- `## Change Log`

Use `unknown` or `not specified` for missing user input. Do not invent strategy rules.
For `## Sizing Guidance`, include only strategy-level sizing rules supplied by the user, such as max position size, leverage limits, loss limits, scaling rules, or cash/reserve constraints. If the user did not specify them, write exactly `not specified`.

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
path = "/absolute/path/to/.agents/skills/strategy-<name>/SKILL.md"
enabled = true
# END TradingCodex strategy skills
```

Do not add strategy skills to fixed subagent TOML files. The coordinator may read the selected strategy and pass compact context in assignment briefs, but that orchestration detail must not appear inside the strategy body.

## Validation

Before finishing, confirm:

- The name starts with `strategy-`.
- The frontmatter `name` matches the `.agents/skills/<name>/` directory.
- Required frontmatter is present.
- Required body sections are present.
- `agents/openai.yaml` has a valid default prompt with the exact strategy name.
- Active strategies are listed in the root strategy marker block.
- Fixed subagent TOML files do not reference the strategy.
- The strategy body has no platform coupling terms such as TradingCodex, role names, MCP, approval gates, execution gates, or handoff instructions.
