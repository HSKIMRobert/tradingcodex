# Generated Workspaces

Use this page before changing `tcx attach`, `tcx init`, `tcx update`, template modules, generated files, hooks, project MCP config, projection indexes, or the generated launchers. Human-facing rules live in [docs/generated-workspaces.md](../docs/generated-workspaces.md).

## Attach Model

TradingCodex is installed globally or invoked through `uvx`, then attached to the workspace where Codex should work:

```bash
uvx --refresh --from tradingcodex tcx attach . && ./tcx doctor
```

Valid targets are empty directories or git-initialized directories containing only `.git` plus optional git metadata files. A source checkout of this repository is not a generated workspace.

## Generator Flow

`tradingcodex_cli/generator.py`:

1. loads `workspace_templates/modules/*/module.json`
2. resolves module dependencies and conflicts
3. resolves the canonical global home and fails before writes on split-home conflict
4. takes the native bootstrap lock and renders typed template values
5. ensures `.tradingcodex/workspace.json`
6. calls `project_agent_configuration()`
7. writes generated indexes, with `module-lock.json` as the completion marker
8. writes the startup status snapshot

Default modules include `codex-base`, `fixed-subagents`, `repo-skills`, guardrails, information barriers, audit, MCP, stub/paper execution, and postmortem.

## Generated Contract

Generated workspaces should contain:

- `AGENTS.md`
- `.codex/config.toml`
- `.codex/prompts/base_instructions/head-manager.md`
- `.codex/agents/*.toml`
- `.codex/hooks/tradingcodex_hook.py`
- `.agents/skills/*`
- `.tradingcodex/*`
- `trading/*`
- `./tcx`
- `tcx.cmd`
- `.tradingcodex/user/customization.json` when the user saves workspace-local customization preferences

Clean generated workspaces must not contain `package.json`, Node MCP runtime files, workspace-local canonical investment DBs, broker credentials, raw secrets, legacy `.tradingcodex/mainagent/*.yaml` role registries, or policy-local `role_owned_skills` roster copies. Role skill sources are projected from `tradingcodex_service/application/agents.py` into `.codex/agents/*.toml`.

The source repository's React/TypeScript/Vite tooling does not alter this rule.
Compiled workbench assets ship in the Python package; attach/update never copy
`frontend/`, create `node_modules`, or invoke npm. Web-started analysis may add
bounded operational metadata and normalized redacted events beside a per-run
workflow, but never raw reasoning, tool payloads, stderr, or raw final output.

Project/root Codex MCP servers should be discovered or written through
`tcx build codex-mcp ...` and imported into the External MCP Gate before use;
generated subagents should not get direct unmanaged external MCP allowlists.
The built-in TradingCodex MCP defaults safe enabled tools to Codex `approve`;
execution submit/cancel stays disabled outside `execution-operator` and service-gated there.
Root and fixed-role MCP entries use `cwd = "."` and
`TRADINGCODEX_WORKSPACE_ROOT = "."`; Codex resolves MCP `cwd` from the launched
project working directory, so these values bind file-native workflow state to
the attached workspace rather than to a TOML file's parent.

## Projection Outputs

Generated indexes under `.tradingcodex/generated/` include module, capability, component, agent, skill, and projection metadata. Component data comes from `tradingcodex_service/application/components.py`. Agent and skill projection comes from `tradingcodex_service/application/agents.py`.

Skill/projection indexes cover only the TradingCodex-managed workspace. They
record each skill's layer, trust scope, implicit-invocation posture, and exact
workspace-relative resolved source file. Codex TOML entries are relative to
their declaring config and TradingCodex resolves them for exact-path checks.
The indexes set `runtime_discovery_complete=false` and report
same-name host-global collisions without importing host skill bodies.
`doctor --layer improvement` compares exact root/role paths. This is drift and
collision detection, not proof that the host Codex runtime cannot discover a
differently named global or plugin skill.

Generated project config enables live Codex web search for the pristine public
research baseline. Project-local additional instructions and managed skills are
overlays; projection places an immutable core/extension footer after additional
instructions so they cannot redefine the documented kernel contract.

When generated agent behavior changes, inspect generated output, not just template source.

## Update Rules

`tcx update .` refreshes generated paths while preserving immutable
`workspace_id` and active profile. `.tradingcodex/cli.py` is the common Python
launcher behind POSIX `./tcx` and Windows `tcx.cmd`; hooks select the native
shim. Generator values use format-specific TOML/YAML/JSON/shell/CMD literals.
Module lock records canonical `tradingcodex_home`, `home_source`, DB path, and
`db_source`; Codex writable roots and MCP env use the same resolved path. An
explicit DB override is also projected through the shared launcher and every
MCP environment so the home-default DB cannot be selected accidentally. A destination-OS
update is required after moving a workspace across platforms. Package specs
remain intentional provenance. Update refreshes through the package unless the
caller passes `--skip-refresh`; `head-manager` must direct protected harness
updates to the appropriate terminal command.
Per-run workbench metadata, normalized events, and accepted artifacts are
workspace state and remain preserved. Update consumes the frontend build already
inside the package and does not run npm.

## Edit Checklist

When changing this area:

- update `docs/generated-workspaces.md` for durable contract changes
- keep human-readable generated content under `workspace_templates/modules/*/files`
- update generator tests for module graph, rendered paths, and generated indexes
- run a clean generated workspace smoke
- inspect `.tradingcodex/generated/*.json`
