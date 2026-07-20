# TradingCodex 1.2.0 Release Status

Status: candidate. Local, native-Codex, distribution, hosted CI, publication,
and post-publish gates are recorded separately below.

Updated: 2026-07-20

This page records the `1.2.0` candidate. A version bump, source commit, or
local wheel does not prove that the exact public artifacts have passed their
gates. Public `1.0.2` remains the upgrade-smoke baseline until `1.2.0` is
published; unpublished `1.1.x` tags are not treated as a public baseline.

## Version And Scope

- `tradingcodex_service/version.py` is the only package-version source for
  package metadata, `tcx --version`, generated workspaces, release input, and
  the `v1.2.0` tag.
- `1.2.0` is the next v1 minor release. Its durable release notes are in
  [`CHANGELOG.md`](../CHANGELOG.md); product behavior remains owned by the
  relevant pages in [`docs/`](./README.md).
- The release workflow must build one wheel and one source distribution from
  the tag, verify those exact files, and publish those downloaded artifacts
  without rebuilding.

## Upgrade Contract From 1.0.2

Operators pin both the package runner and workspace update to the exact
candidate:

```bash
uvx --refresh --from "tradingcodex==1.2.0" \
  tcx update . --from "tradingcodex==1.2.0"
./tcx doctor
```

The update must preserve the workspace id, paper scope, workspace-native
research and source snapshots, user-owned Brains and Strategies, connector
state, recorded runtime home, explicit DB override, and custom service address.
Generated paths owned by TradingCodex are refreshed in place. After updating,
the operator fully restarts Codex, opens a new task, and reviews changed
project hooks when prompted.

For a pre-1.2 workspace, the updater recovers a raw Markdown export only when
it is byte-identical to the receipt-proven canonical artifact, including its
identity, version, and content hash. The signed receipt may establish an
original under either `trading/research/` or `trading/reports/`; directory
placement alone is never used as provenance. If the source has since advanced,
the matching immutable version archive must prove the historical bytes. A
missing, invalid, or ambiguous receipt or archive stops the update before it
writes a sidecar, and altered or
independently authored duplicates remain fail-closed for manual resolution.
Current exports are suppressed from canonical lookup only by a
service-authenticated sidecar bound to that workspace's resolved root and
central provenance. A copied, replayed, or root-rebound sidecar is treated as a
duplicate instead. All run-bound receipt reads, including compact review and
card projections, require that same central workspace binding.

The exact cross-version gate starts from the public `1.0.2` package, attaches a
workspace, installs the built `1.2.0` wheel, runs `tcx update`, and verifies the
preserved identity and user-owned state alongside the refreshed generated
contract:

```bash
python3.11 tests/release_upgrade_smoke.py \
  --wheel-dir dist \
  --from-version 1.0.2
```

## Required Evidence

| Area | Candidate state | Required evidence |
| --- | --- | --- |
| Version identity | Passed locally | Source and editable metadata report `1.2.0`; wheel/sdist filename verification remains part of the distribution-artifact gate. |
| Source and schema | Passed locally | The full Python suite exits successfully; Django check, migration dry-run, compileall, and whitespace review pass. |
| Frontend and guide | Passed locally | Locked frontend tests and build pass; generated static assets are deterministic; guide contracts and changed Markdown are reviewed. |
| Generated workspace | Passed locally | A disposable development workspace passes doctor, service, launcher, MCP, and projection checks. |
| Native Codex acceptance | Passed locally | The exact reference client completed run `analysis-6dc34abea89b4f0ba45139ca99497771`: persisted trusted hooks; sequential fundamental and news child artifacts plus a run-bound accepted synthesis; strict quality checks passed; the workspace-filtered ledger contains only `begin_analysis_run`. |
| Distribution artifacts | Passed locally | Fresh `1.2.0` wheel and sdist pass `twine check`, the packaged-wheel smoke, and the public `1.0.2` upgrade smoke. |
| Candidate CI | Pending | The final commit is on `origin/main` and required GitHub checks are green. |
| Tag and PyPI | Pending | Annotated `v1.2.0` points at that commit; the protected tag-bound release workflow publishes the verified artifacts. |
| Post-publish verification | Pending | Exact-version fresh attach, doctor, installer, metadata, and update smokes pass from PyPI. |

## Final-Commit Validation

Run the source and package gates in
[Deployment](./deployment.md) and
[Validation And Test Plan](./validation-and-test-plan.md):

```bash
npm ci --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
git diff --exit-code -- tradingcodex_service/static/tradingcodex_web
python3.11 -m pytest
python3.11 manage.py check
python3.11 manage.py makemigrations --check --dry-run
python3.11 -m compileall tradingcodex_cli tradingcodex_service apps tests
python3.11 -m build
python3.11 -m twine check dist/*
python3.11 tests/platform_wheel_smoke.py --wheel-dir dist
python3.11 tests/release_upgrade_smoke.py --wheel-dir dist --from-version 1.0.2
```

The release workflow additionally verifies the hash-locked calculation runtime
on supported Python 3.11–3.14 x86-64 Linux, Intel macOS, and native Windows.
Any missing wheel or source-build fallback is a blocker.

## Native Codex E2E

Generated-template, role, hook, and workflow changes require an observed
native-Codex acceptance in a disposable workspace. Use the exact reference
client, persist trust for all generated project hooks, and retain both the
emitted JSON event stream and the corresponding persisted root and child
rollout records with the candidate evidence.

Before marking this gate passed, retain the exact client version and persisted
hook-trust result, the `codex exec --json` event stream plus the persisted root
and child rollout records (the emitted stream alone can be incomplete),
accepted artifact paths plus strict quality-check output, the lifecycle
assertion output, and the workspace-scoped before/after MCP ledger result. Unit
and subprocess contract tests do not substitute for this observed execution.

The run must show a Head Manager analysis run, an exact fixed-role child spawn,
one follow-up to that live child, a sequential second child, accepted
role-produced research artifact(s), and a Head Manager synthesis that consumes
the returned run-local artifact identity. From the workspace root, validate
each saved artifact using its workspace-relative path, for example
`./tcx quality-check trading/research/<artifact>.evidence.md --strict`.
The development MCP ledger is shared, so compare its before/after rows filtered
to the disposable workspace's `workspace_context.path` (or workspace id). The
only permitted non-research row is `begin_analysis_run`; reject any order,
approval, broker, execution, or secret effect. A one-run hook-trust bypass is
not sufficient for fixed-role lifecycle acceptance.

## Tag And Publication

After every final-commit gate passes:

1. Commit the release evidence, push `main`, and wait for required CI.
2. Create and push annotated tag `v1.2.0` at the green commit.
3. Dispatch `Manual Release` from that tag with
   `release_version=1.2.0`. Use `publish_pypi=false` for an optional hosted
   rehearsal, then `publish_pypi=true` after protected-environment approval.
4. Verify immutable PyPI files and metadata, then run the exact-version
   fresh-install and cross-version update smokes.

## Claim Boundary

Software release readiness does not establish investment performance, return
improvement, model superiority, or financial safety. Those claims require
separate evidence and review.
