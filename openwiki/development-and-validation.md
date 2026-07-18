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
| React workspace viewer | frontend test/typecheck/build, committed-output diff, focused GET API tests, real-browser desktop/narrow/keyboard/error checks |
| MCP registry/handler/allowlist | `tools/list` smoke plus focused MCP tests |
| Research memory/artifact quality | create/search/export/source snapshot flow and `tcx quality-check --strict` |
| Dataset/catalog memory | canonical Parquet/id/lineage/withdrawal tests, bounded card/profile/slice tests, SQLite+FTS incremental/corruption/fallback tests, and legacy JSON compatibility |
| Calculation runtime/memory | locked imports/manifest/launcher doctor, prepared and exploratory runner tests, exact reuse/cache-miss lineage, private-input non-persistence, and native fixed-role smoke |
| Generated templates/hooks/prompts/skills | disposable workspace smoke and generated contract inspection |
| Build shell/network policy | hook probes plus disposable native smoke for `apply_patch`, narrow reads/hash/diff/Git inspection, isolated `py_compile`, allowlisted launcher commands, public GET/HEAD/read-only HTTPS Git, and fail-closed interpreter/helper/test/build/POST cases |
| Routing/head-manager/subagents | generated workspace smoke plus Codex-native smoke when available |
| Safety/order/approval/execution/broker | focused pytest, `python manage.py check`, MCP/order smoke, policy/idempotency checks |

## Generated Workspace Smoke

```bash
SOURCE_ROOT="$(pwd)"
SOURCE_PYTHON="$(uvx --refresh --from "$SOURCE_ROOT" python -c 'import sys; print(sys.executable)')"
export PYTHONPATH="$SOURCE_ROOT${PYTHONPATH:+:$PYTHONPATH}"
export TRADINGCODEX_MCP_PACKAGE_SPEC="$SOURCE_ROOT"
unset TRADINGCODEX_PYTHON
SMOKE_ROOT="$(python -c 'import tempfile; print(tempfile.mkdtemp(prefix="tradingcodex-harness-"))')"
export TRADINGCODEX_HOME="$SMOKE_ROOT/home"
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

For Dataset/Calculation changes, also inspect the managed Git ignore entry for
`trading/research/datasets/objects/`, the v3 SQLite catalog status, exact Head
Manager card-only versus calculation-role allowlists, the projected
`tcx-calculation` skill, runtime v2 manifest/lock/launcher hashes, and one
prepared result envelope. Also force one malformed emitter result, record its
safe failure code/message, prepare a corrected script under a new basename/spec,
and record success; an unchanged retry is not valid recovery evidence. Native
E2E should cover provider data → Source
Snapshot → Dataset → slice → Calculation → artifact, exact rerun reuse, a
one-row/parameter/cutoff cache miss, DCF/IRR, statsmodels regression, SciPy
optimizer diagnostics, and private portfolio/risk input non-persistence.

For Build-policy changes, do not treat source-checkout pytest or build commands
as commands the model may run inside an active generated Build turn. The native
smoke must prove the narrow hook-admitted review lane succeeds and that general
interpreters, helper scripts, test runners, build systems, shell composition,
and model-authored POST fail. Broader pytest, Django, frontend, packaging, and
release checks remain maintainer-terminal validation.

## Codex CLI Smoke

When skill text, role TOML, head-manager instructions, hooks, routing, or handoff behavior changes, run this when Codex CLI/auth is available:

Use a dedicated maintainer `CODEX_HOME`, open the disposable workspace in
interactive Codex once, and persistently approve all eight generated project
hooks before the native run. The one-run hook-trust bypass is not valid evidence
for V2 child lifecycle hooks. Resolve the workspace to one physical path and
reuse it throughout; hook trust keys include the source path as well as the
current hash.

```bash
cd "$SOURCE_ROOT"
CANON_WORKSPACE="$(realpath "$SMOKE_ROOT/workspace")"
python tests/codex_cli_contract.py --workspace "$CANON_WORKSPACE" --require-reference --require-hook-trust
CODEX_PROJECT_TRUST="$("$SOURCE_PYTHON" -c 'import json, pathlib, sys; root = str(pathlib.Path(sys.argv[1]).resolve()); print(f"projects={{{json.dumps(root)}={{trust_level=\"trusted\"}}}}")' "$CANON_WORKSPACE")"
codex exec -c "$CODEX_PROJECT_TRUST" -c 'mcp_servers.tradingcodex.required=true' \
  --strict-config \
  -C "$CANON_WORKSPACE" --skip-git-repo-check \
  --json --output-last-message "$SMOKE_ROOT/codex-smoke.txt" \
  'Fixed-role dispatch smoke only. Do not produce investment analysis. For "ACME company facts only. No valuation, portfolio review, order, approval, trading, or execution.", begin a lightweight analysis run, dynamically choose the single smallest useful fixed role, dispatch it with exact agent_type and a compact fork_turns=none message asking it to return only ROLE_READY, wait for that child, and stop in waiting state without synthesis.' \
  > "$SMOKE_ROOT/codex-smoke.jsonl"
```

Confirm the lightweight run binding and MCP tool-call workspace context both
resolve to `$SMOKE_ROOT/workspace`; the caller cwd remains `$SOURCE_ROOT` so
relative MCP binding regressions cannot hide. Confirm every spawn names Head
Manager's dynamically chosen exact `agent_type`, uses compact/no-history
context, and starts the role's projected model. Inspect the spawned child
rollout and require its actual permission profile to be `trading-research`,
including ordinary user-owned writes outside `trading/` and protected
`trading/`/control paths. If exact selection is unavailable, require
`waiting_for_subagent_dispatch` with no generic spawn, role/source emulation, or
empty wait.

For data-source changes, test the entire ordered branch rather than one happy
provider call: reusable Dataset; relevant user MCP/skill success and partial
success; OpenBB success plus auth, entitlement, empty, stale, rate-limit,
timeout, drift, and quarantine outcomes; official-source fallback; and strict
pin no-fallback. Assert one user capability discovery per atomic need, one
OpenBB discovery/activation per session and subcategory, zero exact or semantic
repeats after closed outcomes, and no raw result over 20,000 characters in a
handoff.

Round-trip two same-schema 78-row instruments through
`record_external_data_result`, `get_dataset_rows`, and CSV export. Verify all
156 rows, identity, timezone, currency, venue, adjustment policy, finite OHLC,
duplicate timestamps, cursor selector binding, redistribution gates, atomic
rollback, and absence of secret values in API, MCP, receipt, audit, artifact,
URL, header, or exception text. OpenBB tests use a stubbed upstream runtime;
attach/update and ordinary vanilla analysis must remain healthy when OpenBB is
missing or disabled.

Also assert authenticated DataNeed ownership, exact source pin/provider/query
binding, returned adjustment policy, evidence-grade floor, OpenBB compatibility
receipt hash, proxy-local semantic dedupe, and the 120-row invariant during
receipt replay. A partial result may retain only a derived missing
field/identifier or one exact non-overlapping period; present values cannot be
declared missing. Fault-inject the Dataset manifest write and prove no orphan
payload remains.

For artifact-producing native smokes, inspect observable JSONL and artifact
receipts: the child must load the compact fixed-role base, tool discovery must
use the generated prompt's bounded names-only query with at most 12 returned
names:
`text(ALL_TOOLS.filter(x => x.name.includes("<provider-or-keyword>")).slice(0, 12).map(x => x.name))`.
A supported compound form has one to four literal `name.includes` predicates
joined only by `||`/`&&`, the exact 12-name slice, and a name-only projection.
Safe-but-noncanonical forms are reported separately; description, dynamic,
full-record, or five-plus-predicate scans remain broad failures.
Only an exact name from that prior result may feed at most one anchored schema
lookup:
`const t = ALL_TOOLS.find(x => x.name === "<exact-tool-name>"); text(t ? t.description : "missing")`.
Reject description map/search/filter/regex operations, full
records or catalogs, unselected names, and repeat schema lookups. Each step has
one standard data envelope even when Codex 0.144.4 prepends its transport status
prelude. Review bodies must use bounded Markdown windows and service-returned
continuation offsets, and a deterministic outcome must not be followed by an
unchanged identical call. Producing roles must return the authenticated
`ARTIFACT` receipt line; fixed children have no artifact-list/search tool, and
Head Manager recovery is exact-filtered and card-level; uniqueness requires
`returned_count=1`, `has_more=false`, and exactly one verified run-bound
artifact. Track per-role
tool/error counts, artifact bytes, token/cache counts, latency, and termination
reason across repeated trials; private model reasoning is not an audit surface.

For a reproducible root-plus-child audit, run
`python -m tradingcodex_cli.codex_trace_audit /absolute/root-rollout.jsonl
--candidate`. This maintainer command ignores private reasoning content,
authoritatively joins started-child events to spawn ids and child role metadata,
hashes canonical duplicate values and changed paths, distinguishes aggregate
cumulative token usage from the largest observed session context, and gates
every token event (with reference-version-optional cache-write usage treated as
zero) plus monotonic cumulative usage, consistent turn-context events, compact
child bases, unique spawn task-path/nickname lineage, and the generated prompt's
single/compound bounded names-only resolution plus no more than one exact
selected-schema lookup. Native ordinal display suffixes such as `the 2nd` are
normalized only when parent, role, path, and spawn identity remain exact. It
accepts the transport-owned status prelude but requires exactly one
standard data envelope for each discovery step and rejects description
map/search/filter/regex operations, full records or catalogs, unselected names,
and repeat schema lookups.
Card and explicitly
windowed review artifact reads must also use one exact result envelope; nested
reads are accepted only from authoritative observable MCP results, never
inferred from JavaScript strings or comments. A valid bounded card/review
wrapper is assessed by the artifact contract and counted as an explicit
oversize exemption; web, bulk shell, list, malformed, mismatched, and unbounded
results remain under the generic output gate. Generic wrapper output is bounded,
and deterministic-success repeat gates apply only to read-only/idempotent tools
and stop across successful mutations of the same observed resource id. The auditor
also gates the projected root/child model and managed runtime
profile, structured retryability, deterministic retries, and root progress
cadence: first visible update and maximum visible silence are each at most
60,000 ms when timestamps are observable.
The auditor permits one structured, argument-changing correction to an
immediate external-result recorder call and preserves market-local calendar
dates when matching a date-only official request to an RFC 3339 DataNeed;
successful data still requires exact adjustment-policy agreement.
Run it without `--candidate` when recording a historical
baseline that is expected to fail current acceptance rules.

The reference preflight is pinned to Codex CLI 0.144.4. It verifies strict
config loading, MCP and sandbox configuration, explicit MultiAgent V2
enablement, the `agents` namespace feature posture, the disabled unified-
exec/computer-use surfaces, and persisted trust for every generated project
hook before the expensive native run.

If Codex CLI or authentication is unavailable, record the blocker and still run generated workspace, hook, and starter-prompt checks.

For packaging/platform work, build the wheel and run
`python tests/platform_wheel_smoke.py --wheel-dir dist`. GitHub Actions repeats
that clean-wheel smoke on Ubuntu, native macOS, and native Windows; Windows must
invoke `tcx.cmd`, not Bash `./tcx`. Run real Codex CLI only after all non-Codex
checks, and do not infer a Windows Codex-client result from launcher CI.
The wheel smoke must load `/` and the packaged viewer JavaScript/CSS without
installing Node.
Calculation runtime release checks also resolve the hash-locked wheel set and
run doctor/import/prepared/exploratory smokes on Python 3.11–3.14 across
supported macOS, Linux, and native Windows x86-64 jobs. Missing wheels fail
before workspace mutation; source-build fallback is invalid evidence.

For viewer changes, verify GET-only routes, registered-workspace rejection,
sanitized skill/artifact/Dataset/Calculation detail, absence of raw Dataset
payloads beyond the bounded 20-row profile sample or private inputs, and the
absence of any Codex subprocess or mutation
endpoint. Then run desktop and narrow browser checks.

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
