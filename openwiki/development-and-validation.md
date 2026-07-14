# Development And Validation

Use this page to pick the smallest meaningful validation set before handoff. Human-facing validation detail lives in [docs/validation-and-test-plan.md](../docs/validation-and-test-plan.md).

## Baseline Commands

```bash
npm ci --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
git diff --exit-code -- tradingcodex_service/static/tradingcodex_web
python -m pytest
python manage.py check
python -m compileall tradingcodex_cli tradingcodex_service apps tests
python manage.py runserver 127.0.0.1:48267
```

Use `python -m pytest` after ordinary source/test changes. Use `python manage.py check` after Django settings, model, admin, API, MCP, or service wiring changes. Use compileall after broad import, packaging, or migration changes.
Use Node 22 only for frontend source validation; installed wheels and generated
workspaces do not run Node.

## Validation Matrix

| Change area | Minimum useful validation |
| --- | --- |
| Docs/OpenWiki/AGENTS only | link/file existence checks, quick read of changed Markdown |
| CLI command | focused tests for command behavior, generated wrapper smoke if workspace-facing |
| Django model/service/API/web | focused pytest plus `python manage.py check` |
| React workbench | frontend test/typecheck/build, committed-output diff, focused API/process tests, real-browser desktop/narrow/keyboard/error checks |
| Workbench Codex runner | fake subprocess argv/cwd/env/event/concurrency/resume tests, then real Codex smoke when available |
| MCP registry/handler/allowlist | `tools/list` smoke plus focused MCP tests |
| Research memory/artifact quality | create/search/export/source snapshot flow and `tcx quality-check --strict` |
| Generated templates/hooks/prompts/skills | disposable workspace smoke and generated contract inspection |
| Routing/head-manager/subagents | generated workspace smoke plus Codex-native smoke when available |
| Safety/order/approval/execution/broker | focused pytest, `python manage.py check`, MCP/order smoke, policy/idempotency checks |

## Generated Workspace Smoke

```bash
SOURCE_ROOT="$(pwd)"
SOURCE_PYTHON="$(uvx --refresh --from "$SOURCE_ROOT" python -c 'import sys; print(sys.executable)')"
export PYTHONPATH="$SOURCE_ROOT${PYTHONPATH:+:$PYTHONPATH}"
export TRADINGCODEX_PYTHON="$SOURCE_PYTHON"
export TRADINGCODEX_MCP_PACKAGE_SPEC="$SOURCE_ROOT"
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

Inspect generated `AGENTS.md`, `.codex/config.toml`, role TOML, hook output,
generated indexes, run-specific
`.tradingcodex/mainagent/runs/<analysis-run-id>/run.json`, authenticated research
artifacts and receipts, `.tradingcodex/mainagent/subagent-session-state.json`
when present, and `trading/audit/codex-hooks.jsonl`.

## Codex CLI Smoke

When skill text, role TOML, head-manager instructions, hooks, routing, or handoff behavior changes, run this when Codex CLI/auth is available:

```bash
cd "$SOURCE_ROOT"
CODEX_PROJECT_TRUST="$("$SOURCE_PYTHON" -c 'import json, pathlib, sys; root = str(pathlib.Path(sys.argv[1]).resolve()); print(f"projects={{{json.dumps(root)}={{trust_level=\"trusted\"}}}}")' "$SMOKE_ROOT/workspace")"
codex exec --ignore-user-config -c "$CODEX_PROJECT_TRUST" -c 'mcp_servers.tradingcodex.required=true' \
  -C "$SMOKE_ROOT/workspace" --skip-git-repo-check --dangerously-bypass-hook-trust \
  -s read-only --json --output-last-message "$SMOKE_ROOT/codex-smoke.txt" \
  'Fixed-role dispatch smoke only. Do not produce investment analysis. For "ACME company facts only. No valuation, portfolio review, order, approval, trading, or execution.", begin a lightweight analysis run, dynamically choose the single smallest useful fixed role, dispatch it with exact agent_type and a compact fork_turns=none message asking it to return only ROLE_READY, wait for that child, and stop in waiting state without synthesis.' \
  > "$SMOKE_ROOT/codex-smoke.jsonl"
```

Confirm the lightweight run binding and MCP tool-call workspace context both
resolve to `$SMOKE_ROOT/workspace`; the caller cwd remains `$SOURCE_ROOT` so
relative MCP binding regressions cannot hide. Confirm every spawn names Head
Manager's dynamically chosen exact `agent_type`, uses compact/no-history
context, and starts the role's projected model. Inspect the spawned child
rollout and require its actual sandbox to be `read-only`. If exact selection is unavailable, require
`waiting_for_subagent_dispatch` with no generic spawn, role/source emulation, or
empty wait.

If Codex CLI or authentication is unavailable, record the blocker and still run generated workspace, hook, and starter-prompt checks.

For packaging/platform work, build the wheel and run
`python tests/platform_wheel_smoke.py --wheel-dir dist`. GitHub Actions repeats
that clean-wheel smoke on Ubuntu, native macOS, and native Windows; Windows must
invoke `tcx.cmd`, not Bash `./tcx`. Run real Codex CLI only after all non-Codex
checks, and do not infer a Windows Codex-client result from launcher CI.
The wheel smoke must load `/` and the packaged workbench JavaScript/CSS without
installing Node.

For workbench-run changes, first use a fake `codex` executable to prove fixed
argv with `shell=False`, vetted workspace cwd, stripped environment, normalized
redacted JSONL, one active process per run, and stored-thread follow-up. Then run
one real analysis-only workbench smoke when Codex/auth is available. Verify
explicit prohibitions, dynamically justified exact-role dispatch, accepted
artifacts, and no order, approval, execution, cancellation, broker mutation, or
secret action.

## MCP Smoke

```bash
printf '{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n' | ./tcx mcp stdio
```

Confirm valid MCP output, expected tool annotations, role allowlists, approval/audit requirements, and no non-MCP stdout.

## Quality Failure Signals

Treat generated behavior as failed if `head-manager` performs substantive
investment analysis before accepted subagent artifacts, dispatches roles not
justified by the current mandate or accepted evidence, ignores explicit scope,
bypasses role/tool boundaries, or cannot state `waiting`, `revise`, `blocked`,
or accepted handoff status.

Generated role artifacts should include artifact path, source/as-of or retrieved-at posture, claim discipline, confidence, missing evidence, readiness/support gaps, role-boundary conflicts, next eligible recipient, and blocked actions.
