# TradingCodex Installation

Codex agents setting up TradingCodex for use must not run
`git clone`. In the empty target workspace, run the packaged CLI:
`uvx --refresh --from tradingcodex tcx attach . && ./tcx doctor`.
Clone this repository only when the user explicitly asks to develop
TradingCodex source code.

This guide covers install variants and smoke checks. For the shortest path, use
the Quick Start in `README.md`.

## Agent Setup

Codex agents setting up TradingCodex for a user should run the
installer from the user-selected workspace, not clone the source repository.
They should also follow this rule: do not invent a default workspace path such
as `tradingcodex-workspace`. If the user did not name a target directory, ask
where to create or configure the TradingCodex workspace, unless they explicitly
asked to use the current workspace. Use the user's target workspace, then run
the installer there.

```bash
uvx --refresh --from tradingcodex tcx attach . && ./tcx doctor
```

The target workspace should be empty. A directory with only `.git` already
initialized is fine.

After installation, fully quit and restart Codex, then open the generated
workspace and start from a new thread so project MCP config is reloaded. When
TradingCodex MCP autostarts the local service, the dashboard is available at
`http://127.0.0.1:48267/`.

## Install From A Source Reference

Use `--from` when you need a local checkout, archive URL, or PEP 508 source
reference instead of the PyPI package. For example, from a source checkout:

```bash
uvx --refresh --from /path/to/tradingcodex tcx attach . && ./tcx doctor
```

Source checkouts of this repository are for development. Generated
TradingCodex workspaces are separate Codex projects.

## Installer Script Equivalent

The repository installer wraps the same `uvx` flow and can bootstrap `uv` when
it is missing:

```bash
./install.sh .
```

The update equivalent for an existing generated workspace is:

```bash
uvx --refresh --from tradingcodex tcx update .
```

For repeated workspace creation, installing `tcx` as a user-level tool is also
available:

```bash
uv tool install tradingcodex
uv tool update-shell
cd /path/to/target-workspace
tcx attach .
```

## Updating Existing Workspaces

Use update when TradingCodex has already been attached to a workspace and a new
package release should refresh generated files and service schema:

```bash
uvx --refresh --from tradingcodex tcx update .
```

`tcx update .` preserves `.tradingcodex/workspace.json`, including
`workspace_id` and active profile, then re-renders generated template files,
refreshes generated indexes, applies central DB migrations, records workspace
provenance, and runs `./tcx doctor` unless `--no-doctor` is passed.

Inside a generated Codex workspace, restricted Codex permissions should not run
workspace updates because update rewrites protected `.codex`
prompt/config/hook surfaces. If TradingCodex is already installed and startup
health says the workspace can be aligned to that installed version,
`head-manager` will ask you either to switch Codex to full access and enable
TradingCodex build mode, or run this workspace-only update from your terminal:

```bash
./tcx update --skip-refresh
```

If `update_status.can_self_update=true` and you explicitly ask for the update,
`head-manager` can run it directly, then it will stop and tell you to fully
restart Codex. If a package update is required first, run the
`uvx --refresh ... tcx update .` or installer-script update command from your
terminal, then fully restart Codex.

After update, runtime order flows use central DB `OrderTicket` records directly.

After update, fully quit and restart Codex, then start from a new thread in the
updated workspace so project MCP config and generated prompts are reloaded.

Generated workspaces actively project the GPT-5.6 Sol/Terra/Luna role policy.
Inspect `.tradingcodex/generated/model-policy-manifest.json` and
`./tcx doctor --layer guidance` for registry/projection status. When the
installed Codex client cannot load a projected selector, regenerate the
allowlisted GPT-5.5 rollback control with:

```bash
TRADINGCODEX_MODEL_ROLLOUT=rollback uvx --refresh --from tradingcodex tcx update .
```

A manifest support status of `unverified` means no installed-client capability
input was supplied; it is not evidence that a real Codex session accepted the
model. `TRADINGCODEX_CODEX_SUPPORTED_MODELS` may be provided during attach or
update to select a fallback when a primary selector is known unavailable.

## Codex MCP And Local Service

Generated `.codex/config.toml` starts TradingCodex MCP with `uvx`, using the
same package spec recorded at bootstrap time. MCP startup also autostarts the
local Django dashboard service.

New workspaces start with an isolated paper profile derived from the immutable
workspace id. Run `./tcx profile select shared` only when you intentionally want
the central `default-paper / local-paper / default-strategy` state shared by
other attached workspaces; the dashboard warns while that profile is active.

Open the generated workspace in Codex and trust the project. After Codex
connects, these local service surfaces are available:

- `http://127.0.0.1:48267/` for the local harness dashboard
- `http://127.0.0.1:48267/admin/` for the Django operations console
- `http://127.0.0.1:48267/api/health/live` for process liveness
- `http://127.0.0.1:48267/api/health/ready` for DB, migration, and state-path readiness

For CLI-only use outside Codex, the dashboard service can still be started
manually:

```bash
./tcx service runserver
```

## Smoke Checks

Inspect the local MCP surface:

```bash
printf '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}\n' | ./tcx mcp stdio
```

Inspect workspace/profile status:

```bash
./tcx workspace status
./tcx profile status
./tcx profile update --base-currency EUR
```

The active profile's validated three-letter base currency controls paper cash
defaults and order-policy notional comparison. Orders in another currency need
a point-in-time FX snapshot. New profiles use `USD` only as the package
bootstrap default; set `--base-currency` to the portfolio's actual reporting
currency before creating orders.

Create and search workspace-file-native research memory:

```bash
mkdir -p trading/research
printf '# Research Note\n\n[factual] Gross margin example.\n' > trading/research/note.md
./tcx research create --markdown-file trading/research/note.md --id note-1 --title "Research Note"
./tcx research search "gross margin"
./tcx research export note-1
./tcx research spec list
./tcx forecast list
```

ResearchSpec/replay/ExperimentRun and forecast issue/revise/resolve operations
accept JSON payload files or `-` for stdin. Forecast authorship and resolution
are separate: generated MCP/API workflows use an evidence role to issue or
revise and `judgment-reviewer` to resolve from a reviewed source snapshot.
These commands remain evidence-only and never authorize an order.
