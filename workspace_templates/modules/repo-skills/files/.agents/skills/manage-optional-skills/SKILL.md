---
name: manage-optional-skills
description: "Create, update, archive, delete, activate, and validate role-local optional skills for fixed TradingCodex subagents through the shared workspace skill service, CLI, API, or Django web surface while keeping core skills, role identity, MCP allowlists, permission profiles, and guardrails locked."
---

# Manage Optional Skills

Use this skill when the user asks to customize a fixed subagent with an optional role-local procedure.

Use $skill-creator for concise `SKILL.md` instructions and metadata. Prefer the shared TradingCodex mutation service through `tcx skills optional ...`, API, or Django web actions instead of hand-editing files. Direct edits are allowed only when repairing a broken workspace, and must preserve the same paths and metadata.

Boundary:

- Optional skills are workspace files, not Django DB rows.
- Django web, API, CLI, and mainagent actions all use the same application service.
- Do not edit core skill folders when creating optional skills.
- Do not change role identity, model settings, permission profiles, MCP allowlists, information barriers, approval authority, execution authority, secret access, or live broker posture.
- Keep optional skills as work style, checklist, output-shape, or evidence-quality procedures inside the target role boundary.

Files:

```text
.tradingcodex/subagents/skills/<role>/<skill-name>/SKILL.md
.tradingcodex/subagents/skills/<role>/<skill-name>/agents/openai.yaml
.tradingcodex/subagents/skills/<role>/<skill-name>/agents/tradingcodex.json
.codex/agents/<role>.toml
```

Skill name rules:

- Use lowercase hyphen-case.
- Keep the name short and specific.
- Do not reuse a core skill name.
- Prefer names that describe the procedure, such as `filing-red-flag-review` or `liquidity-checklist`.
- Keep `name` and `description` in `SKILL.md` frontmatter; the sidecar JSON is lifecycle metadata only.

Create flow:

1. Identify the target fixed subagent role from the user's request.
2. Choose a new optional skill name.
3. Use `tcx skills optional create <skill-name> --role <role> ...` or the Django/API equivalent so validation and projection run together.
4. Ask before changing a draft to active when the rule changes role behavior materially.
5. Validate the boundary before final response.

Update flow:

1. Read the existing optional skill files and status JSON.
2. Preserve the skill name unless the user explicitly asks for a rename.
3. Use `tcx skills optional update <skill-name> --role <role> ...` or the Django/API equivalent.
4. Confirm the target role TOML still references the skill only when active.
5. Validate the boundary before final response.

Archive flow:

1. Use `tcx skills optional archive <skill-name> --role <role>` or the Django/API equivalent.
2. The service removes the active TOML projection while leaving the skill folder.
3. Do not remove core skills.

Delete flow:

1. Draft or archived optional skills may be hard-deleted.
2. Deleting an active optional skill archives and reprojects first unless the user explicitly confirms force deletion.

Status JSON shape:

```json
{
  "role": "<target-role>",
  "name": "<skill-name>",
  "scope": "role",
  "status": "active",
  "created_by": "main-agent",
  "created_at": "<ISO-8601>",
  "updated_by": "main-agent",
  "updated_at": "<ISO-8601>"
}
```

TOML block shape:

```toml
[[skills.config]]
path = "/absolute/path/to/.tradingcodex/subagents/skills/<role>/<skill-name>/SKILL.md"
enabled = true
```

New TOML projections must point to `.tradingcodex/subagents/skills/<role>/<skill-name>/SKILL.md`, not `.agents/skills`.

Validation checklist:

- The optional skill stays within the target role's existing responsibility.
- The skill does not mention approval, execution, order submission, broker access, secrets, or policy changes unless those are already core responsibilities of the target role.
- The skill does not create new authorities, new tools, new MCP allowlists, or new permission profiles.
- The skill does not weaken source/as-of honesty, handoff states, information barriers, or no-overlap role boundaries.
- The sidecar JSON and TOML projection agree.
- Django status pages can discover and mutate the skill through the shared service.

Final response:

- State the skill name, target role, status, changed files, and validation result.
- If blocked, explain which boundary blocked the change and leave existing files unchanged.
