# Repository Guidelines

## Documentation Layers

Read documentation in this order:

1. [OpenWiki quickstart](openwiki/quickstart.md) for the fastest agent-facing orientation.
2. This `AGENTS.md` for non-negotiable repository rules and validation expectations.
3. [docs/README.md](docs/README.md) for the human-readable source-of-truth map linked from the public README.

Use `openwiki/` as the working map for coding agents. Use `docs/` as durable product documentation for users, maintainers, and reviewers. If behavior, policy, workflow, generated workspace output, release-facing language, or safety posture changes, update the relevant `docs/` page in the same change.

## Setup Request Guard

If a user asks to set up, install, attach, or use TradingCodex in a workspace, do not run `git clone` and do not turn that workspace into this source checkout. From the target workspace, run:

```bash
uvx --refresh --from tradingcodex tcx attach . && ./tcx doctor
```

On native Windows PowerShell, run:

```powershell
uvx --refresh --from tradingcodex tcx attach .
.\tcx.cmd doctor
```

Generated workspaces contain both launchers; use `./tcx` on POSIX and
`tcx.cmd`/`.\tcx.cmd` on native Windows.

Ask for the target directory if the user did not provide one and did not explicitly ask to use the current workspace. Clone this repository only when the user explicitly asks to develop, inspect, or modify TradingCodex source code.

## Source Map

TradingCodex is a local-first investment OS built on Codex; its Python/Django harness is the orchestration and runtime subsystem.

| Path | Owns |
| --- | --- |
| `tradingcodex_cli/` | Packaged `tcx` CLI. Command implementations live in `tradingcodex_cli/commands/`. |
| `tradingcodex_cli/__main__.py` | CLI command dispatch and top-level command list. |
| `tradingcodex_cli/generator.py` | Generated workspace module graph, rendering, and generated indexes. |
| `tradingcodex_service/` | Django project, workbench/API/MCP surfaces, the SPA shell, committed frontend build, and service entrypoints. |
| `frontend/` | React 19, TypeScript, and Vite 8 source for the skill-first product workbench. Node 22 is a maintainer build dependency only. |
| `tradingcodex_service/application/` | Canonical durable service behavior shared by CLI, Web, Admin, API, MCP, and generated hooks. |
| `tradingcodex_service/application/workbench.py`, `tradingcodex_service/workbench_api.py` | Skill-first snapshot/detail APIs and the bounded analysis-only Codex runner. |
| `tradingcodex_service/application/components.py` | Harness component registry and cross-surface maintenance map. |
| `tradingcodex_service/application/agents.py` | Fixed role registry, built-in skills, MCP allowlists, and projection behavior. |
| `tradingcodex_service/application/investment_brains.py` | Investment Brain bundle validation, immutable version registry, activation, rollback, and Head Manager-only projection. |
| `tradingcodex_service/application/analysis_runs.py` | Lightweight request-hash plus sealed Brain, Strategy, and Investor Context provenance. |
| `tradingcodex_service/application/artifact_bindings.py` | Service-issued receipts that authenticate run-bound artifact identity, hashes, producer, inputs, and sealed Brain/Strategy/Context lineage. |
| `tradingcodex_service/application/workspace_git.py` | Generated-workspace Git membership, privacy ignore contract, and repository diagnostics. |
| `apps/` | Django model/admin apps for policy, orders, portfolio, audit, MCP, integrations, and harness provenance. Analysis runs and research artifacts remain workspace-file-native. |
| `workspace_templates/modules/*/files` | Generated Codex prompts, agents, hooks, skills, policies, wrappers, and workspace contracts. |
| `docs/` | Human-readable product source of truth. |
| `openwiki/` | Agent-facing repository working map. |
| `tests/` | Pytest coverage and scenario contracts. |

The source repository intentionally has one Node build root under `frontend/`.
Do not add a production Node server, package workspace, Node MCP runtime,
frontend state framework, parallel service facade, or Django
`apps/universes` app unless product direction changes in `docs/`. Generated
workspaces remain Node-free, and `tcx attach`/`tcx update` must never run npm.

## Change Routing

| Change area | Read first | Usually validate |
| --- | --- | --- |
| CLI or wrapper behavior | `openwiki/quickstart.md`, `tradingcodex_cli/__main__.py`, relevant `tradingcodex_cli/commands/*` | focused pytest, generated workspace smoke |
| Django service behavior | `openwiki/architecture.md`, relevant `tradingcodex_service/application/*`, `docs/system-architecture.md` | `python -m pytest`, `python manage.py check` |
| Web, frontend, API, or MCP surface | `openwiki/interfaces-and-data.md`, `frontend/`, `tradingcodex_service/web.py`, `tradingcodex_service/api.py`, `tradingcodex_service/mcp_runtime.py` | frontend test/build, focused pytest, `python manage.py check`, browser verification, MCP smoke when touched |
| Agent, workflow, skill, hook, or template behavior | `openwiki/workflows-and-agents.md`, `docs/harness.md`, `docs/roles-skills-and-workflows.md`, `workspace_templates/modules/*/files` | generated workspace smoke, Codex-native smoke when behavior changes |
| Policy, approval, broker, secret, or execution boundary | `openwiki/safety-and-execution.md`, `docs/safety-policy-and-execution.md`, policy/order/broker/MCP services | focused pytest, `python manage.py check`, order/MCP smoke as applicable |
| Research memory or artifact quality | `openwiki/interfaces-and-data.md`, `docs/research-memory-and-artifacts.md`, `tradingcodex_service/application/research.py`, `tradingcodex_service/application/artifact_quality.py` | research create/search/export, strict quality check |
| Package, release, or install flow | `docs/deployment.md`, `installation.md`, `pyproject.toml`, `MANIFEST.in` | packaging/release checks from `docs/deployment.md` |

## Development Commands

- `python -m pytest`: run the repository test suite configured in `pyproject.toml`.
- `python manage.py check`: validate Django settings, models, apps, admin, API, and service wiring.
- `python -m compileall tradingcodex_cli tradingcodex_service apps tests`: catch broad Python syntax/import issues.
- `python manage.py runserver 127.0.0.1:48267`: run the local web, admin, and API service.
- `python tests/platform_wheel_smoke.py --wheel-dir dist`: smoke-test a clean wheel with native temporary paths and launchers.
- `npm ci --prefix frontend && npm test --prefix frontend && npm run build --prefix frontend`: install, test, type-check, and build the React workbench.
- `git diff --exit-code -- tradingcodex_service/static/tradingcodex_web`: verify that the committed Vite output matches frontend source.

## Coding Rules

Target Python `>=3.11,<3.15` and Django `5.2.x`. Use four-space indentation, clear module-level service functions, and type hints where they clarify contracts.

Web, Admin, Django Ninja, MCP, CLI, and generated hooks must call shared application services instead of duplicating policy, approval, research, order, portfolio, audit, harness, or broker logic. Use direct canonical imports.

Research artifacts and source snapshots are workspace-file-native, not Django DB models. Generated workspace template bodies should remain ordinary files under `workspace_templates/modules/*/files`; use Python for registry loading, dependency resolution, rendering, validation, and generated indexes, not to hide durable prompts, skills, policies, hooks, or workspace-contract content inside string constants.

TradingCodex targets global users. Keep repository code, durable docs, generated workspace guidance, prompts, tests, CLI help, UI copy, and examples in the project's default product language and language-neutral. Do not add language-specific literals, keyword lists, escape-hidden localized strings, or examples tied to one natural language unless the change explicitly builds a reviewed localization layer.

Frontend source belongs under `frontend/`; Vite writes deterministic committed
output under `tradingcodex_service/static/tradingcodex_web/`. Do not hand-edit
the compiled JavaScript or CSS. Django and WhiteNoise serve those files; Node is
not an installed-package or generated-workspace runtime dependency. Django
Admin remains the default Django surface and is not part of the React rewrite.

## Harness And Agent Changes

Do not infer agent, workflow, MCP, policy, template, or harness behavior from Python code alone. Treat docs, skill bodies, role TOML, hooks, policies, generated workspace files, service-layer code, and tests as one product contract.

Before changing those surfaces, read the relevant OpenWiki page and source docs, especially:

- `docs/harness.md`
- `docs/roles-skills-and-workflows.md`
- `docs/generated-workspaces.md`
- `docs/safety-policy-and-execution.md`
- `tradingcodex_service/application/components.py`
- `workspace_templates/modules/*/files/.agents/skills/*/SKILL.md`
- `workspace_templates/modules/*/files/.codex/agents/*.toml`
- `workspace_templates/modules/*/files/.codex/prompts/*`
- `workspace_templates/modules/*/files/.codex/hooks/*`
- `workspace_templates/modules/*/files/.tradingcodex/policies/*`

For agent skill authoring, use `$skill-creator` for generic skill discipline before applying TradingCodex-specific projection rules. Treat every skill as a folder bundle: `SKILL.md` is required, `agents/openai.yaml` is required for TradingCodex UI/projection, and `scripts/`, `references/`, or `assets/` should be included when they make the skill more reliable.

Every bundled TradingCodex skill id must use `tcx-` followed by one word when
possible and no more than two hyphen-separated words. The folder name,
`SKILL.md` frontmatter name, registry id, projected path, and
`agents/openai.yaml` invocation must match exactly. Reserve `tcx-` for bundled
core skills; user-owned `strategy-*`, `investment-brain-*`, and optional role
skills remain separate namespaces.

Keep durable role identity, role eligibility, MCP allowlists, analysis-sandbox posture, approval authority, execution authority, and policy boundaries out of skill bodies. Those belong to base instructions, project and role TOML, `ROLE_SKILL_MAP`, service-layer policy, and generated projection indexes.

Do not hand-roll optional or strategy skill state around shared services. For optional subagent skills, use `./tcx skills optional create|update ...` so frontmatter, `agents/openai.yaml`, `agents/tradingcodex.json`, validation, status, and TOML projection stay aligned. For user strategy skills, route authoring through `tcx-strategy`, CLI, API, or the shared service so `strategy-*` naming, required frontmatter, required strategy sections, `agents/openai.yaml`, active/archive status, and root projection are validated.

After agent-skill changes, validate generated shape with `./tcx doctor --layer improvement`, `./tcx skills list --all`, the affected `./tcx subagents skills <role>` or `./tcx strategies inspect <name>`, and generated `.tradingcodex/generated/skill-index.json` plus `.tradingcodex/generated/projection-manifest.json` in a disposable workspace.

After Investment Brain changes, also install a local fixture through
`./tcx investment-brains validate --local <bundle>` before installation, then
`./tcx investment-brains install --local <bundle>`, inspect/list it, verify its
path appears only in Head Manager's root config, bind it with one exact
`$investment-brain-*` native request, and exercise deactivate, update,
rollback, and remove without mutating the source repository.

## Validation Expectations

Use the smallest meaningful validation while iterating, then broaden when scope justifies it.

Run focused pytest for source changes. Run `python manage.py check` after Django settings, model, admin, API, MCP, or service wiring changes. Run `python -m compileall tradingcodex_cli tradingcodex_service apps tests` after broad import, packaging, or migration changes.

Frontend changes must run the frontend test/build command, prove the committed
build is current, and be checked in a real browser at desktop and narrow widths
with keyboard focus plus empty, loading, failure, blocked, and completed states.
Workbench-run changes also need focused tests for fixed subprocess arguments,
workspace validation, CSRF/auth boundaries, environment stripping, event
redaction, concurrency, and follow-up resume behavior.

Harness, agent, workflow, MCP, policy, skill, hook, or template changes need Codex-native validation, not just repository tests:

```bash
SOURCE_ROOT="$(pwd)"
SOURCE_PYTHON="$(uvx --refresh --from "$SOURCE_ROOT" python -c 'import sys; print(sys.executable)')"
export PYTHONPATH="$SOURCE_ROOT${PYTHONPATH:+:$PYTHONPATH}"
export TRADINGCODEX_MCP_PACKAGE_SPEC="$SOURCE_ROOT"
unset TRADINGCODEX_PYTHON
SMOKE_ROOT="$(python -c 'import tempfile; print(tempfile.mkdtemp(prefix="tradingcodex-harness-"))')"
"$SOURCE_PYTHON" -m tradingcodex_cli attach "$SMOKE_ROOT/workspace"
cd "$SMOKE_ROOT/workspace"
./tcx doctor
./tcx doctor --layer codex-native
./tcx doctor --layer improvement
./tcx subagents status
./tcx skills list --all
./tcx subagents prompt "Analyze NVDA. No order, no trading, no valuation."
printf '{"prompt":"Analyze NVDA. No order, no trading, no valuation."}\n' | ./tcx __hook user-prompt-submit
```

When skill text, role TOML, head-manager instructions, hooks, routing, or handoff behavior changes, also run a real Codex CLI smoke from the disposable workspace when available:

```bash
cd "$SOURCE_ROOT"
CODEX_PROJECT_TRUST="$("$SOURCE_PYTHON" -c 'import json, pathlib, sys; root = str(pathlib.Path(sys.argv[1]).resolve()); print(f"projects={{{json.dumps(root)}={{trust_level=\"trusted\"}}}}")' "$SMOKE_ROOT/workspace")"
codex exec --ignore-user-config -c "$CODEX_PROJECT_TRUST" -c 'mcp_servers.tradingcodex.required=true' \
  -C "$SMOKE_ROOT/workspace" --skip-git-repo-check --dangerously-bypass-hook-trust \
  -s read-only --json --output-last-message "$SMOKE_ROOT/codex-smoke.txt" \
  'Fixed-role dispatch smoke only. Do not produce investment analysis. For "ACME company facts only. No valuation, portfolio review, order, approval, trading, or execution.", begin a lightweight analysis run, dynamically choose the single smallest useful fixed role, dispatch it with exact agent_type and a compact fork_turns=none message asking it to return only ROLE_READY, wait for that child, and stop in waiting state without synthesis.' \
  > "$SMOKE_ROOT/codex-smoke.jsonl"
```

Inspect `$SMOKE_ROOT/codex-smoke.txt`, `$SMOKE_ROOT/codex-smoke.jsonl`, the run-specific `.tradingcodex/mainagent/runs/<analysis-run-id>/run.json`, `.tradingcodex/mainagent/subagent-session-state.json` when present, authenticated research artifacts, and `trading/audit/codex-hooks.jsonl`. Require the first investment-workflow action for an unbound native request to load/call `begin_analysis_run` without source, index, CLI, or HTTP discovery. Require each spawn input to contain the exact role as `agent_type`, compact context, the analysis run id, and `fork_turns="none"`; inspect the child rollout and require the same non-default role, its registry-projected model, and an actual `read-only` sandbox. Verify that Head Manager dynamically reassesses roles from returned artifacts without a Django plan, lane, DAG, candidate-role ceiling, or supervisor-loop tool. If exact `agent_type` is unavailable, the only passing outcome is `waiting_for_subagent_dispatch` with no generic fallback, source-code/role-TOML emulation, or empty wait. If Codex CLI or authentication is unavailable, record that blocker and still run generated workspace, hook, and starter-prompt checks.
Confirm the recorded plan and MCP tool-call workspace context both resolve to
`$SMOKE_ROOT/workspace`, even though Codex was launched from `$SOURCE_ROOT`.

Treat a smoke as failed if `head-manager` gives substantive investment analysis before accepted subagent artifacts, expands beyond the selected team, uses a generic/default agent to imitate a fixed role, reads TradingCodex source or role TOML as a dispatch fallback, forks full history, ignores negated scope such as `no order` or `no valuation`, bypasses role/tool boundaries, or cannot state `waiting`, `revise`, `blocked`, or accepted handoff status.

Research-memory changes should verify file-native create, search, source-snapshot, and export flows. MCP changes should verify `tools/list`, role allowlists, and audit behavior when touched:

```bash
printf '{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n' | ./tcx mcp stdio
```

Template or bootstrap changes must regenerate a clean workspace. Hand edits in OS temporary smoke workspaces are debugging only, not durable fixes. Packaging/platform changes must also run `python tests/platform_wheel_smoke.py --wheel-dir dist`; the smoke must load the packaged SPA shell and assets, and native Windows validation uses `tcx.cmd`, never Bash `./tcx`.

## Git, Security, And PRs

Recent history uses short imperative subjects such as `Make agent skill config file-native` and `Tighten TradingCodex handoff routing`. Keep commits focused and avoid trailing periods in subject lines. PRs should summarize behavior changes, list validation commands, link related issues, and call out docs, template, migration, or UI changes. Include screenshots only for visible web UI updates.

Do not store broker API keys, tokens, or secrets in this repository. The default runtime DB is `state/tradingcodex.sqlite3` under the canonical platform home documented in `docs/system-architecture.md`; `TRADINGCODEX_HOME` and `TRADINGCODEX_DB_NAME` are the only explicit path overrides. `TRADINGCODEX_WORKSPACE_ROOT` is provenance only. Live broker adapters remain disabled by default. Execution-sensitive actions must flow through service-layer policy, approval/idempotency, adapter, and audit paths.
