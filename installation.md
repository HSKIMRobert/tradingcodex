# TradingCodex Installation

Codex agents setting up TradingCodex for use must not run `git clone`. In an
empty target workspace, run the packaged CLI. On macOS/Linux:

```bash
uvx --refresh --from tradingcodex tcx attach . && ./tcx doctor
```

On native Windows PowerShell:

```powershell
uvx --refresh --from tradingcodex tcx attach .
.\tcx.cmd doctor
```

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

Use the platform command above. In the rest of this guide, `./tcx` means the
POSIX launcher; substitute `.\tcx.cmd` on native Windows.

The target workspace should be empty. A directory with only `.git` already
initialized is fine.

After installation, fully quit and restart Codex, then open the generated
workspace and start from a new thread so project MCP config is reloaded. When
TradingCodex MCP autostarts the local service, the skill-first workbench is available at
`http://127.0.0.1:48267/`.

The PyPI package includes the compiled React workbench. End users and generated
workspaces do not need Node or npm. Starting an analysis from the workbench does
require an installed and authenticated `codex` CLI visible on the Django
service process `PATH`; when it is unavailable, the workbench remains readable
and reports the run-start blocker.

## Install From A Source Reference

Use `--from` when you need a local checkout, archive URL, or PEP 508 source
reference instead of the PyPI package. For example, from a source checkout:

```bash
uvx --refresh --from /path/to/tradingcodex tcx attach . && ./tcx doctor
```

Source checkouts of this repository are for development. Generated
TradingCodex workspaces are separate Codex projects.

Source developers changing the workbench use Node 22 only as a build tool:

```bash
npm ci --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
git diff --exit-code -- tradingcodex_service/static/tradingcodex_web
```

The Vite output is committed and served by Django and WhiteNoise. Do not run a
Node server as part of an installed TradingCodex service.

## Installer Script Equivalent (POSIX Only)

`install.sh` supports macOS/Linux POSIX shells only. It wraps the same `uvx`
flow and can bootstrap `uv` when missing:

```bash
./install.sh .
```

Do not run `install.sh` on native Windows. Use the PowerShell `uvx` commands
above or install the console tool with `uv tool install tradingcodex`, then use
`tcx attach .` and `.\tcx.cmd doctor`.

## Global Runtime Home

Clean installs use these homes:

| Platform | Default home |
| --- | --- |
| macOS | `~/Library/Application Support/TradingCodex` |
| Windows | `%LOCALAPPDATA%\TradingCodex` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/tradingcodex` |

Run `tcx home status --json` to see the selected path/source and
`tcx home check` before changing runtime paths. `TRADINGCODEX_HOME` remains an
explicit override; `TRADINGCODEX_DB_NAME` remains an independent DB override.
If only populated legacy `~/.tradingcodex` state exists it is used with a
`legacy_fallback` warning. If old and new homes are both populated,
TradingCodex fails closed until the operator explicitly chooses a home. No
automatic or built-in offline migration is performed in this release.

The native Windows CI smoke covers the wheel, launcher, generated config,
hooks, MCP pipes, doctor, packaged workbench assets, and local service
lifecycle. It does not claim a real Windows Codex CLI session; that limitation
remains explicit until separately exercised.

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

Generated workspaces project GPT-5.6 Sol/xhigh for root `head-manager`,
Terra/high for every fixed subagent except `execution-operator`, and Terra/low
for that operator.
Inspect `.tradingcodex/generated/model-policy-manifest.json` and
`./tcx doctor --layer guidance` for registry/projection status. There is no
GPT-5.5 runtime fallback or rollback mode. A manifest support status of
`unverified` means no installed-client capability input was supplied; it is not
evidence that a real Codex session accepted the model.
`TRADINGCODEX_CODEX_SUPPORTED_MODELS` may be provided during attach or update;
generation fails when a required selector is absent rather than silently
changing models. Update Codex or restore model access, then rerun `tcx update`.

## Codex MCP And Local Service

Generated `.codex/config.toml` starts TradingCodex MCP with `uvx`, using the
same package spec recorded at bootstrap time. MCP startup also autostarts the
local Django workbench service.

New workspaces start with an isolated paper profile derived from the immutable
workspace id. Run `./tcx profile select shared` only when you intentionally want
the central `default-paper / local-paper / default-strategy` state shared by
other attached workspaces; the workbench warns while that profile is active.

Open the generated workspace in Codex and trust the project. After Codex
connects, these local service surfaces are available:

- `http://127.0.0.1:48267/` for the local React workbench
- `http://127.0.0.1:48267/admin/` for the Django operations console
- `http://127.0.0.1:48267/api/health/live` for process liveness
- `http://127.0.0.1:48267/api/health/ready` for DB, migration, and state-path readiness

For CLI-only use outside Codex, the workbench service can still be started
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
