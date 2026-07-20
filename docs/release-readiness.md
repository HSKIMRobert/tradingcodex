# Release Readiness

This is a reusable release checklist, not a live status page. GitHub Actions,
GitHub Releases, and PyPI own the current state of a particular release.

## Candidate Contract

- `tradingcodex_service/version.py` is the only package-version source.
- `CHANGELOG.md` contains a matching dated release section.
- The release tag is the annotated `v<version>` tag on a commit in `main`.
- One build produces exactly one wheel and one source distribution. Every
  later job downloads those files instead of rebuilding them.

## Required Gates

| Area | Evidence required |
| --- | --- |
| Source and schema | Full Python suite, Django check, migration dry-run, compileall, and whitespace review pass. |
| Frontend | Locked tests and build pass; committed static assets are deterministic. |
| Generated workspace | A disposable development workspace passes doctor, service, launcher, MCP, and affected projection checks. |
| Native Codex | Prompt, role, skill, hook, or orchestration changes pass the observed acceptance route in the validation plan. |
| Distribution | Wheel and source distribution pass metadata checks and the clean-wheel smoke. |
| Platform runtime | The exact wheel passes Python 3.11-3.14 on supported Linux, Apple Silicon macOS, and native Windows runners. |
| Upgrade | The latest preceding stable PyPI release updates to the candidate while preserving user and service identity. |
| Publication | Protected PyPI publishing succeeds before the matching GitHub Release is created or refreshed. |
| Post-publish | A pinned PyPI install passes fresh attach, doctor, metadata, and update checks. |

Use the smallest applicable gates while iterating. Run the complete release
set only for a candidate that is ready to publish.

## Upgrade Gate

The default and only routine cross-version check is:

```text
latest preceding public release -> candidate release
```

`tests/release_upgrade_smoke.py` reads the candidate version from the built
wheel and selects the greatest stable PyPI version below it. It does not replay
every historical release pair. A major-version migration or an explicitly
supported older direct-upgrade path requires its own documented gate.

```bash
python3.11 tests/release_upgrade_smoke.py --wheel-dir dist
```

The smoke verifies preserved workspace identity, paper scope, workspace-native
artifacts, user-owned Brains and Strategies, connector state, runtime home,
database override, service address, and provider approval evidence.

## Publish

After the candidate gates pass:

1. Merge the release commit to `main` and wait for CI.
2. Create and push the annotated `v<version>` tag.
3. In GitHub Actions, dispatch `Manual Release` from that tag with
   `release_version=$RELEASE_VERSION` and `publish_pypi=true`.
4. Approve the protected `pypi` environment.
5. Verify the exact PyPI files and GitHub Release, then run the post-publish
   checks from [Deployment](deployment.md).

Pushing a branch or tag alone does not publish anything.

## Claim Boundary

Software release readiness does not establish investment performance, return
improvement, model superiority, or financial safety. Those claims require
separate evidence and review.
