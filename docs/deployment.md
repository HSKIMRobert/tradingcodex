# Deployment

TradingCodex is distributed as a Python package on PyPI. The package name is
`tradingcodex`; the installed command is `tcx`.

TradingCodex is agentic investment workflow software that runs from the user's
workspace and local runtime by default. A PyPI release ships the CLI, Django
service plane, generated workspace templates, Admin/Web templates, static
assets, and MCP gateway code. It does not deploy a hosted service. Core ships
paper execution by default; broker-specific live execution requires installed,
reviewed providers and explicit live gates.

## Runtime Profiles

`local` is the default and supported desktop profile. Its development secret
and `DEBUG=True` default are acceptable only because `tcx service` refuses to
bind this profile outside loopback (`127.0.0.1`, `::1`, or `localhost`). Local
anonymous HTTP access is read-only; API mutations require a bound API
principal/key or an authenticated staff session, and web mutations require an
authenticated staff session.

`remote` is an explicit hardening profile for an operator-managed deployment;
it does not turn the package into a hosted service. Before any non-loopback
bind, all of these environment-backed settings are mandatory:

| Setting | Required contract |
| --- | --- |
| `TRADINGCODEX_SERVICE_PROFILE` | `remote` |
| `TRADINGCODEX_DEBUG` | `0` |
| `TRADINGCODEX_SECRET_KEY` | Non-default, at least 32 characters, supplied outside repository/workspace files |
| `TRADINGCODEX_API_KEY` and `TRADINGCODEX_API_PRINCIPAL` | Distinct API credential and bound mutation principal; the key must be at least 32 characters |
| `TRADINGCODEX_ALLOWED_HOSTS` | Explicit externally served hosts; wildcard `*` is refused |
| `TRADINGCODEX_CSRF_TRUSTED_ORIGINS` | Explicit `https://` origins matching the allowed hosts |
| `TRADINGCODEX_TRANSPORT_SECURITY` | `reverse-proxy` |

The remote profile enables HTTPS redirect, secure session/CSRF cookies, HSTS,
and Django's `X-Forwarded-Proto: https` handling. The TLS-terminating reverse
proxy must remove any client-supplied forwarded-protocol header and set its own,
and the backend bind must be reachable only from that trusted proxy/network.
Keep all keys in an environment-backed secret manager. If any required setting
is absent or insecure, settings initialization or the service binding fails
closed before the listener starts.

## Health And Logs

`GET /api/health/live` answers only whether the TradingCodex process is alive.
`GET /api/health/ready` checks central DB access, pending migrations, and
writeability of the mandatory state directory and returns machine-readable
reason codes. Service autostart, compatibility checks, `tcx service status`,
and `doctor` use readiness; a reachable but unready process is not treated as a
compatible service.

Background service logs rotate at 5 MiB with three backups by default. External
MCP stderr logs rotate separately at 1 MiB with two backups. Both paths redact
environment-known secrets, authorization/bearer values, credential-shaped
fields, and URL user-info before persistence. `tcx service status` exposes log
path/size posture and recent error context without returning raw credentials.

## Release Policy

The `0.3.x` release line is the agentic judgment quality contract for the
Python/Django harness. It keeps investment judgment reviewable, challengeable,
source-aware, and revisitable before portfolio, risk, approval, or execution
steps. Order flows continue to use central DB `OrderTicket` records directly;
pre-release compatibility shims do not remain in the runtime package. The
documented Web, API, CLI, MCP, generated workspace, and application-service
surfaces are the supported contract.

Execution status for this release line:

- paper execution is built in
- validation and live-capable provider code must be installed/reviewed before use
- live submission is disabled by default and requires config, policy, environment, adapter, health, approval, confirmation, idempotency, sync, and audit gates
- execution MCP tools must stay behind policy, approval, duplicate-request,
  connection, and audit checks

Model rollout is independent from package release authority. The default
generated policy actively uses GPT-5.6 Sol/Terra/Luna tiers, but a generated
`support_status=unverified` is not client verification. Set
`TRADINGCODEX_CODEX_SUPPORTED_MODELS` during generation when the deployed Codex
client's selectors are known, and use `TRADINGCODEX_MODEL_ROLLOUT=rollback` to
regenerate the allowlisted GPT-5.5 control. Promotion of a candidate model still
requires a frozen corpus, deterministic checks, hard-safety success, and blind
human non-inferiority; package publication alone is not model promotion.

## Maintainer Prerequisites

Use Python 3.11 for release build verification and keep CI green across the
supported range. The package metadata requires `>=3.11,<3.15`, and CI runs on
Python 3.11, 3.12, 3.13, and 3.14.

Configure Trusted Publishing before the first upload. Do not store long-lived
PyPI API tokens in GitHub repository secrets unless Trusted Publishing is not
available.

Trusted Publisher settings:

| Index | Project | Owner | Repository | Workflow | Environment |
| --- | --- | --- | --- | --- | --- |
| PyPI | `tradingcodex` | repository owner/org | repository name | `release.yml` | `pypi` |

On GitHub, create the `pypi` environment and require manual approval before
deployment.

## Local Build Verification

Run the regular validation suite first:

```bash
python3.11 -m pytest
python3.11 manage.py check
python3.11 manage.py makemigrations --check --dry-run
python3.11 -m compileall tradingcodex_cli tradingcodex_service apps tests
```

Build and check the source distribution and wheel:

```bash
python3.11 -m pip install --upgrade build twine
rm -rf dist build
find . -maxdepth 1 -name '*.egg-info' -type d -exec rm -rf {} +
python3.11 -m build
python3.11 -m twine check dist/*
```

Install and exercise the built wheel in a clean, platform-native temporary
environment with the repository smoke helper:

```bash
python3.11 tests/platform_wheel_smoke.py --wheel-dir dist
```

## CI/CD

CI is defined in `.github/workflows/ci.yml` and appears as
`CI (no deploy)` in GitHub Actions.

It runs on pull requests and pushes to `main` or `develop`:

- installs `tradingcodex` with development extras
- runs `pytest`
- runs `python manage.py check`
- checks that migrations are current
- compiles Python sources

A separate Ubuntu Python 3.11 `package-smoke` job builds once, validates
distribution metadata, installs only the clean wheel into a new environment,
and uploads that exact wheel. A dependent `native-platform-wheel-smoke` matrix
runs the same helper on `macos-latest` and `windows-latest`. It verifies native
home selection, `tcx`/`tcx.cmd`, generated TOML/YAML/JSON, hook dispatch,
doctor/DB status, MCP stdio, external-MCP pipe handling, and local service
ensure/status/stop. Windows invokes `tcx.cmd`; it does not pretend Bash
`./tcx` is native evidence. Treat Windows support for a revision as pending
until this job is green; a macOS local smoke or parsed Windows fixture is not a
substitute for native-runner evidence. The manual release build repeats the
Ubuntu clean-wheel helper before publication.

The CI workflow never uploads to PyPI. Pushes to `main` or `develop` run tests
and packaging checks only.

Release automation is defined in `.github/workflows/release.yml` and appears as
`Manual Release` in GitHub Actions.

The release workflow is manual-only. Branch pushes and tag pushes must not
publish package artifacts to PyPI.

The release workflow has additional guardrails:

- publication requires `workflow_dispatch`
- PyPI publication is allowed only from the `main` branch
- concurrent release runs on the same ref are serialized instead of cancelled

Manual `workflow_dispatch` can publish to PyPI when `publish_pypi=true`.

Keep `publish_pypi=false` when the run should only build and verify
distributions.

The workflow uses PyPI Trusted Publishing. The publish jobs request only an
OIDC token through `id-token: write`; they do not require API-token secrets.

The workflow uses current GitHub artifact actions so release artifact upload
and download do not depend on the deprecated Node.js 20 action runtime.

## Existing Installation Update Notes

`tcx update` applies central DB migrations before the updated workspace is used.
Product flows create, check, approve, and submit `OrderTicket` records directly.

## PyPI Release

Before pushing the release tag:

- verify `tradingcodex_service/version.py` is the intended release version;
  `pyproject.toml` reads this single source dynamically
- verify `README.md` describes execution as service-gated
- verify docs mention that live broker execution requires installed providers and explicit gates
- run local build verification

Then create or update the GitHub release/tag as needed, and run the
`Manual Release` workflow manually with `publish_pypi=true`. Do not rely on tag push for
publication; tag pushes are intentionally non-publishing.

After the PyPI workflow completes, create an OS temporary workspace rather than
assuming a fixed temporary root. For example on POSIX:

```bash
SMOKE_ROOT="$(python3.11 -c 'import tempfile; print(tempfile.mkdtemp(prefix="tcx-pypi-"))')"
python3.11 -m venv "$SMOKE_ROOT/venv"
"$SMOKE_ROOT/venv/bin/pip" install tradingcodex==0.3.6
mkdir "$SMOKE_ROOT/workspace"
cd "$SMOKE_ROOT/workspace"
"$SMOKE_ROOT/venv/bin/tcx" attach .
./tcx doctor
```

Also verify the POSIX-only user-facing installer path:

```bash
SMOKE_ROOT="$(python3.11 -c 'import tempfile; print(tempfile.mkdtemp(prefix="tcx-install-"))')"
sh ./install.sh --no-doctor "$SMOKE_ROOT/workspace"
cd "$SMOKE_ROOT/workspace"
./tcx doctor
```

Verify the user-facing update path against the same workspace:

```bash
cd "$SMOKE_ROOT/workspace"
sh /path/to/tradingcodex/install.sh --update --no-doctor .
./tcx doctor
```

On native Windows, do not use `install.sh`; run `uvx --refresh --from
tradingcodex tcx attach .` as one PowerShell command, then run
`.\tcx.cmd doctor`.

## Update Policy

TradingCodex has two update layers:

- package update: install or run the desired PyPI/GitHub package with
  `uvx --refresh`, `uv tool install --upgrade`, or `install.sh --update`
- workspace update: run `tcx update <workspace>` from that package to refresh
  generated files, generated indexes, project MCP config, hook scripts, and
  central DB schema

Generated workspace `./tcx update` normally refreshes through `uvx` first so
the requested package version, rather than an incidental local Python, rewrites
templates. In restricted Codex
permissions, `head-manager` should not run the update itself because it rewrites
protected `.codex` prompt/config/hook surfaces. When the package is already
installed and Codex startup health reports `workspace_update_allowed=true`,
`head-manager` should tell the user to switch to full access plus TradingCodex
build mode, or run the workspace-only path from a terminal:

```bash
./tcx update --skip-refresh
```

`head-manager` may run the update directly only when
`update_status.can_self_update=true`, which requires Codex full access,
unexpired TradingCodex build mode, and an explicit user request. After a
self-update it must stop and tell the user to fully restart Codex. The terminal
path avoids package-cache or user-tool writes and keeps self-modifying `.codex`
prompt/config/hook updates outside a restricted active Codex agent sandbox.
Generated Codex config declares the resolved platform home as its bounded
writable root so
central DB migrations, lock files, and update preferences can still work
without disabling the sandbox when the active Codex surface honors
project-scoped sandbox roots. If a package update is required first, the user
should run the package-refresh command from a terminal instead.

`tcx update` must preserve `.tradingcodex/workspace.json` identity fields,
including `workspace_id` and active profile. It may overwrite generated paths
owned by `workspace_templates/modules/*/files`, and it must not overwrite
workspace-native user artifacts such as `trading/research/*`,
`trading/reports/*`, `.agents/skills/strategy-*`, or optional role skills
except through their documented service-layer workflows.

After a workspace update, users must fully quit and restart Codex, then start
from a new thread in the updated workspace so project MCP config, prompts,
skills, and hooks are reloaded.

## Versioning

Use PEP 440 versions:

- `0.2.0` for the OrderTicket rewrite contract after install, docs, DB
  migration, generated workspace smoke checks, and release e2e checks are stable
- `0.2.1` for Python `>=3.11,<3.15` support and clone-free setup guidance
- `0.2.2` for dashboard startup behavior fixes after `0.2.1`
- `0.2.3` for workflow-planner UX, fixed strategy authoring, profile-scoped
  ticket isolation, workspace-scoped transition audit, and startup/status fixes
- `0.2.4` for the operate/build/execution plane rewrite, compact startup
  context, build-mode updates, and connector scaffold workflow
- `0.2.5` for packaged web static assets and startup service mismatch notices
  reaching head-manager compact context
- `0.2.6` for provider-driven Broker Center foundations, live-gated provider
  execution paths, runtime surface simplification, and stricter subagent skill
  boundaries after `0.2.5`
- `0.2.7` for Codex-native decision packages and investment decision quality
  spine improvements after `0.2.6`
- `0.2.8` for artifact-supervisor loop concurrency and run-specific workflow
  loop state after `0.2.7`
- `0.2.9` for stale service replacement and web scroll-state fixes after
  `0.2.8`
- `0.2.10` for workflow planning and automation skill updates after `0.2.9`
- `0.3.0` for the independent judgment-review gate, staged workflow routing
  cleanup, Decision Quality Spine hardening, and source-aware thesis lifecycle
  updates after `0.2.10`
- `0.3.1` for compatible evidence-card validation and persisted loop closure
  state fixes after `0.3.0`
- `0.3.2` for brief research chat replies with saved head-manager synthesis
  reports after `0.3.1`
- `0.3.3` for flexible update status across package/workspace drift,
  skipped-version Django migration smoke coverage, and PyPI-only release flow
  after `0.3.2`
- `0.3.4` for Build Center customization, Codex MCP discovery/import, external
  MCP permission approval UX, and head-manager research synthesis depth after
  `0.3.3`
- `0.3.5` for safe built-in TradingCodex MCP auto-approval, execution-tool
  hiding outside `execution-operator`, and service-gated execution UX after
  `0.3.4`
- `0.3.6` for reviewer follow-up loop fixes, duplicate pending-task protection,
  and harness cleanup after `0.3.5`
- later patch releases for compatible fixes after `0.3.6`
- pre-releases such as `0.4.0a1`, `0.4.0b1`, or `0.4.0rc1` when preparing
  the next minor contract

PyPI files are immutable. If a release has a packaging defect, publish the next
version instead of trying to replace the broken artifact.

## What Is Not Deployed

This PyPI release does not deploy:

- a hosted web service
- live broker adapters
- raw broker credential storage
- production execution infrastructure
- official commercial/verified adapter packs

Those surfaces require separate product decisions, separate documentation, and
the same service-layer policy, approval, duplicate-request, connection, and audit
boundary.
