# TradingCodex 1.0.0 Release Status

Status: working-tree implementation, broad suite, native workflow, browser, and
macOS distribution acceptance validated; exact final-commit artifacts, native
Windows, tag, and publication remain pending
Updated: 2026-07-13

This page records the current `1.0.0` release state. It is not an implementation
roadmap and does not treat source changes as proof that an exact distribution
artifact or public release has passed its gates.

## v1.0.0 Contract

- `tradingcodex_service/version.py` is the single version source for package
  metadata, `tcx --version`, generated workspaces, release input, and tags.
- New installations attach v1 to an empty workspace. Workspace and runtime
  state use one canonical v1 shape.
- Each TradingCodex Django app starts from one `0001_v1_initial` migration.
  Ordinary forward migrations carry later v1 schema changes.
- Django application services own durable behavior shared by Web, Admin, API,
  MCP, CLI, and generated hooks.
- The workspace viewer is read-only and starts no Codex process. Policy,
  approval, idempotency, broker, execution, redaction, and audit boundaries
  stay service-owned and fail closed.
- Paper execution is built in. Live submission remains disabled by default and
  requires an installed provider plus every documented safety gate.
- The React viewer is a committed static build served by Django and
  WhiteNoise; Node remains a maintainer-only build dependency.
- PyPI publication is manual, tag-bound, and reuses one verified sdist and
  wheel across Ubuntu, macOS, Windows, and publication jobs.

## Current Readiness

| Area | Current state | Evidence or remaining gate |
| --- | --- | --- |
| Version identity | Verified in the working tree | `TRADINGCODEX_VERSION` is `1.0.0`; `pyproject.toml` reads it dynamically; `tcx --version` uses the same source. |
| Schema baseline | Verified in the working tree | Project apps contain only `0001_v1_initial`; migration-graph and model-state checks live in `tests/test_v1_migrations.py`. |
| Workspace baseline | Native working-tree acceptance verified | A no-backup clean attach into `vibe_threads` with an external runtime home passed all doctor layers, preserved a local uncommitted/no-remote Git worktree, and completed exact-role research plus synthesis. |
| Interfaces and safety | Verified in the working tree | The full Python suite, Django checks, migration check, compile pass, focused workflow/MCP/hook contracts, and native acceptance pass after the latest runtime fixes. Rerun against the final commit. |
| Frontend | Viewer source tests and build pass; browser acceptance pending rerun | Six focused tests, typecheck/build, content-hashed assets, three-section routing, and read-only source checks pass. Desktop/narrow workspace selection and failure-state browser checks must be rerun. |
| Release automation | Structurally verified | The release contract suite verifies tag and artifact gating; a manual `publish_pypi=false` rehearsal remains required. |
| Distribution artifacts | Fresh working-tree candidate verified on macOS | Fresh `1.0.0` sdist/wheel build, `twine check`, and packaged-wheel smoke pass; rebuild from the final commit and run the same immutable files on native macOS and Windows. |
| Git tag and PyPI | Not performed by this status | Merge/CI, annotated `v1.0.0` tag, protected-environment approval, and manual publication remain release-operator actions. |
| Post-publish verification | Blocked on publication | Exact-version POSIX and native Windows attach/doctor smokes run only after PyPI contains the immutable artifacts. |

Working-tree status describes source shape, not release sign-off. The final
commit and exact built artifacts remain authoritative.

Current working-tree evidence recorded on 2026-07-13 is listed below. None of
this substitutes for rerunning release gates on the final commit and exact
immutable artifacts:

- `python -m pytest`: **364 passed** after the final runtime, artifact-time,
  V2 dispatch, and synthesis-quality hardening.
- `python manage.py check`: no issues.
- `python manage.py makemigrations --check --dry-run`: no changes detected.
- `python -m compileall -q tradingcodex_cli tradingcodex_service apps tests`:
  passed.
- `npm ci --prefix frontend`, `npm test --prefix frontend`, and
  `npm run build --prefix frontend`: passed; the frontend suite reported seven
  passing tests including typecheck/build, and a second build produced the same
  aggregate SHA-256.
- A fresh `1.0.0` sdist/wheel, `twine check`, and
  `python tests/platform_wheel_smoke.py --wheel-dir <fresh-dist>` passed on
  macOS for the working-tree candidate.

### Native Codex acceptance evidence

The previous server-planned DAG/supervisor-loop evidence is retired because it
does not represent the v1 Codex-native architecture. A fresh generated
`vibe_threads` workspace now has working-tree native evidence for:

- `gpt-5.6-sol`/xhigh Head Manager and exact `gpt-5.6-terra`/high
  `fundamental-analyst` and `news-analyst` children;
- an NVDA company-facts/catalyst request interpreted without hook/server
  semantic classification, with the excluded valuation, portfolio, order,
  approval, trading, and execution scope preserved and no execution role
  present;
- a fresh `begin_analysis_run` request hash and sealed explicit Investment
  Brain id, version, content digest, Strategy, and Investor Context posture;
- exactly two V2 spawns (`fundamental-analyst` and `news-analyst`) containing
  only `agent_type`, `fork_turns`, `message`, and `task_name`; compact task
  names, `fork_turns="none"`, no model/reasoning/sandbox override, and real
  read-only child sandboxes;
- two authenticated role artifacts and one Head Manager synthesis whose
  receipt binds the exact two run-local input ids and hashes;
- timezone-aware knowledge cutoffs bounded by service-returned source
  `known_at` and service-owned artifact `recorded_at`, with no date-only,
  future-cutoff, or MCP retry error;
- strict quality and compact-context passes for all three artifacts, including
  material `[factual]`, `[inference]`, and `[assumption]` tags in the synthesis;
- artifact-driven synthesis without a Django plan, lane, DAG, task id, or
  supervisor tool;
- the exact selected Brain loaded directly by Codex and sealed before dispatch;
  its optional Markdown reference remained lazy because the base Brain body was
  sufficient; and
- zero order tickets, approval receipts, execution results, and broker orders.

The final native run used root task
`019f587a-ca9c-7e23-bfbb-98f8fd590575`, run id
`analysis-38146c80549e4f119862957dff9795a9`, and synthesis artifact
`synthesis_report-NVDA-9b06d78f1d26`.

This is working-tree evidence. The release remains not ready to tag until the
same source, wheel, and platform gates pass for the final commit and immutable
artifacts.

### Workspace viewer browser acceptance

Browser acceptance must be rerun after the viewer change at desktop and 390x844.
Verify content-hashed assets, zero console errors, no horizontal overflow,
keyboard focus, Library/Skills detail transitions, registered-workspace
switching, invalid-workspace JSON failure rendering, and the absence of Work or
mutation controls. The SPA shell must still load for an invalid query selection
so it can render the API error.

## Final-Commit Validation

Run the source, frontend, and schema gates from
[deployment.md](./deployment.md):

```bash
npm ci --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
git diff --exit-code -- tradingcodex_service/static/tradingcodex_web
python3.11 -m pytest
python3.11 manage.py check
python3.11 manage.py makemigrations --check --dry-run
python3.11 -m compileall tradingcodex_cli tradingcodex_service apps tests
```

Harness, role, skill, hook, policy, MCP, and generated-template changes also
require the disposable-workspace and real Codex smokes in
[validation-and-test-plan.md](./validation-and-test-plan.md). Those smokes must
prove exact-role dispatch, compact context, accepted artifact binding,
head-manager synthesis, negated-scope handling, and the fail-closed
`waiting_for_subagent_dispatch` path.

The final candidate artifacts then require:

```bash
python3.11 -m build
python3.11 -m twine check dist/*
python3.11 tests/platform_wheel_smoke.py --wheel-dir dist
```

CI and the manual release rehearsal must run the exact uploaded artifact on
Ubuntu, native macOS, and native Windows. The protected `pypi` environment and
Trusted Publisher configuration must be reviewed before publication.

## Tag And Publication State

This document does not assert that the final commit is on `main`, CI is green,
the tag exists, or PyPI contains `1.0.0`. After every final-commit and artifact
gate passes:

1. Merge the release commit to `main` and wait for CI.
2. Create and push the annotated tag `v1.0.0` at that commit.
3. Rehearse the manual workflow with `publish_pypi=false` and
   `release_version=1.0.0`.
4. With protected-environment approval, run the same tag with
   `publish_pypi=true`.
5. Verify the immutable PyPI files, release notes, and exact-version POSIX and
   native Windows attach/doctor flows.

## Claim Boundary

Software release readiness does not establish model superiority, investment
performance, return improvement, or financial safety. Any such claim requires
separated replay, holdout, live-forward, and postmortem evidence; trusted corpus
provenance; zero permitted hard-safety failures; and blind human review.

## Explicit Non-Goals

- A hosted service or production Node runtime.
- Built-in live broker providers or relaxed execution gates.
- A second agent orchestration stack beneath Codex subagents.
- A frontend state framework, universal outbox, graph database, or speculative
  interface facade.
- Investment-performance or model-superiority claims without the required
  evidence and blind review.
