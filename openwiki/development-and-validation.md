# Development And Validation

Canonical matrix: [Validation And Test Plan](../docs/validation-and-test-plan.md).
Use the smallest check that can fail for the changed behavior, then one
integrated smoke after coupled changes stabilize.

## Route Validation

| Change | Minimum useful check |
| --- | --- |
| Docs, OpenWiki, AGENTS | Local Markdown links/file existence, changed-file review, `git diff --check`. |
| CLI | Focused command tests; generated wrapper smoke when workspace-facing. |
| Django service/model/API/MCP | Focused pytest and `python manage.py check`. |
| MCP registry or role exposure | `tools/list` plus focused handler/visibility tests. |
| Viewer | Focused read API tests; frontend test/build and browser checks only when UI behavior changes. |
| Research object or dataset | Create/read/export or replay the affected object, including provenance and bounds. |
| Prompt, skill, role, hook, projection | Disposable workspace generation and effective-file inspection. |
| Head Manager or delegation | Native Codex smoke with observed agent/tool/context behavior. |
| Policy, approval, broker, order, execution | Focused safety tests, idempotency, audit, secret redaction, and canonical-path smoke. |
| Packaging or release | [Release Readiness](../docs/release-readiness.md). |

## Common Commands

```bash
python -m pytest <focused-test-paths>
python manage.py check
git diff --check
```

Frontend changes additionally use the scripts declared in `frontend/package.json`.
Do not run npm for backend, documentation, attach/update, or generated-workspace
changes.

For guidebook changes:

```bash
python -m pytest tests/test_guidebook_contract.py
python -m http.server 4173 --directory guidebook
git diff --check -- guidebook
```

## Disposable Workspace Smoke

Use `./install.sh --dev` from the source checkout to create an isolated
workspace. In that workspace run:

```bash
./tcx doctor
./tcx service status --json
./tcx skills list --all
./tcx subagents status
```

Inspect the exact generated files affected by the change. For harness behavior,
run Codex CLI with the repository's `tests/codex_cli_contract.py` prerequisites
and observe the native result; do not infer behavior from TOML or unit tests
alone.

## Harness Measures

When prompts, skills, hooks, roles, or orchestration change, compare:

- spawned agent count and whether each added distinct value;
- external and TradingCodex tool-call count, including semantic repeats;
- visible progress cadence and total latency;
- context size and whether raw payloads were replaced by durable IDs;
- artifact count and whether each artifact has reuse or audit value; and
- preservation of order, secret, approval, audit, provenance, and isolation
  boundaries.

A more restrictive rule needs observed failure evidence. Passing unit tests is
not sufficient justification for a larger prompt, hook, registry, or state
machine.

## Delivery

- Preserve unrelated dirty changes.
- State exactly which tests and smokes ran; do not imply broader coverage.
- Update only the owning documentation layer.
- Do not commit, push, deploy, or publish unless the user asks.
