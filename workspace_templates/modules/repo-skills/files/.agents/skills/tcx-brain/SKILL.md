---
name: tcx-brain
description: "Author and manage TradingCodex Investment Brains. Use when the user wants to create, inspect, revise, validate, install, update, activate, deactivate, roll back, remove, or delete a user-owned `investment-brain-*` source or managed plugin. Durable source or lifecycle changes require an exact `$tcx-build` root turn."
---

# TCX Brain

Manage the complete Investment Brain lifecycle through one user entrypoint. A
Brain shapes Head Manager's inquiry and interpretation; it is not a Strategy,
role roster, workflow, memory store, policy package, or execution extension.

`$tcx-brain` manages Brains. It never selects one for analysis. A native
analysis still requires one exact active `$investment-brain-*` invocation.

Read [bundle-contract.md](references/bundle-contract.md) before creating,
revising, or deleting a user-owned source bundle.

## Action Model

Keep the two managed layers distinct:

- Source actions create, inspect, revise, validate, or explicitly delete a
  user-owned workspace-local bundle below `investment-brains/`.
- Plugin actions list, inspect, install, update, activate, deactivate, roll
  back, or remove registry-managed immutable versions through the canonical
  `investment-brains` service command.

`remove` is the managed delete operation: it removes the Head Manager
projection and marks the plugin removed while retaining immutable versions for
run provenance. It does not delete a user-owned source directory. A source
deletion is a separate, explicitly named action.

## Build Admission

1. Require the original root prompt to begin with the exact physical first line
   `$tcx-build` before creating, revising, deleting, installing, updating,
   activating, deactivating, rolling back, or removing a Brain. Require the
   request to invoke or clearly request `$tcx-brain`.
2. Treat the marker as current-turn intent, not elevated filesystem permission.
   Plan mode is not Build authority. If the active sandbox cannot perform a
   required workspace-local write, report the platform blocker and stop.
3. Do not inherit Build admission in a follow-up or subagent. If reviewed
   confirmation arrives later, return a new root-turn prompt beginning with
   `$tcx-build`.
4. Without Build admission, explain the requested operation or return the exact
   user-terminal `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} investment-brains ...`
   command. Do not attempt a mutation.
5. Read-only `list`, `inspect`, and `validate` do not change registry or
   projection state, but use the trusted launcher from Codex only when the
   current runtime admits that command. Otherwise return it for the user to run.

## Source Procedure

1. For a new Brain, use `investment-brains/<investment-brain-id>` unless the
   user selects another workspace-local directory. Use a new lowercase
   hyphen-case `investment-brain-*` id and version `1.0.0` unless the user chose
   another valid initial version.
2. Revise or delete only a user-owned source directory explicitly identified by
   the user. Never edit or delete `.tradingcodex/investment-brains`, projected
   `.agents/skills/investment-brain-*`, a third-party package, an external
   source, or an upstream repository. Adapt third-party ideas only under a new
   user-owned id with a compatible license and original wording.
3. For create or revise, ask the user to select the exact Decision Memory
   episodes, forecasts, postmortems, validated lessons, and contrary cases. Do
   not sweep all memory or infer consent from relevance.
4. Require counterexamples and scope limits. Perform a privacy review that
   excludes private Investor Context, account or holding details, personal
   constraints, confidential sources, issuer-specific cases, and verbatim
   private prose.
5. Abstract the selected evidence into general hypotheses, inquiry priorities,
   interpretation principles, causal frames, scenarios, falsifiers,
   applicability limits, and abstention heuristics. Do not copy private cases,
   names, tickers, account facts, or memory text into the bundle.
6. Show the proposed abstraction, counterexamples, limitations, excluded private
   material, id, version, publisher, license, destination, and requested source
   action. Obtain confirmation before the first write, revision, or deletion.
7. Write only the strict source bundle described in the reference. Keep its
   content platform-neutral. It must not name roles, tools, models, sandboxes,
   workflow order, artifact paths, memory operations, policy, approval, broker,
   order, or execution authority.
8. For a source deletion, first state that installed immutable versions and
   historical provenance remain. Delete only the exact confirmed user-owned
   source files; do not translate source deletion into managed plugin removal or
   vice versa.
9. After create or revise, run the non-mutating
   `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} investment-brains validate --local
   <source-directory>`. Changed content already represented by an installed
   version requires a version higher than every installed version.
10. Stop after any source create, revise, or delete action. Do not install,
    update, activate, remove, stage, commit, configure a remote, push, publish,
    or open a pull request in the same turn. A reviewed lifecycle action starts
    in a fresh exact Build turn.

## Managed Plugin Procedure

1. Identify exactly one explicit workspace-local source directory or public,
   credential-free HTTPS Git URL and ref. Do not infer a source or search a
   marketplace. Private, authenticated, SSH, file, or external local Git
   sources remain explicit user-terminal workflows.
2. Validate before install or update and inspect the returned id, version,
   source posture, content digest, and skill digest.
3. Install inactive first, then inspect the registry result. Activate only when
   the user explicitly requested that exact validated id and version.
4. Use only these canonical commands; never edit registry, package, projection,
   generated index, or Head Manager config files directly:

   ```text
   {{TRADINGCODEX_WORKSPACE_LAUNCHER}} investment-brains list [--active] [--json]
   {{TRADINGCODEX_WORKSPACE_LAUNCHER}} investment-brains inspect <investment-brain-id>
   {{TRADINGCODEX_WORKSPACE_LAUNCHER}} investment-brains validate --local <source-directory>
   {{TRADINGCODEX_WORKSPACE_LAUNCHER}} investment-brains validate --git <https-url> --ref <ref>
   {{TRADINGCODEX_WORKSPACE_LAUNCHER}} investment-brains install --local <source-directory> --inactive
   {{TRADINGCODEX_WORKSPACE_LAUNCHER}} investment-brains install --git <https-url> --ref <ref> --inactive
   {{TRADINGCODEX_WORKSPACE_LAUNCHER}} investment-brains update <investment-brain-id> [--local <source-directory>|--git <https-url> --ref <ref>]
   {{TRADINGCODEX_WORKSPACE_LAUNCHER}} investment-brains activate <investment-brain-id>
   {{TRADINGCODEX_WORKSPACE_LAUNCHER}} investment-brains deactivate <investment-brain-id>
   {{TRADINGCODEX_WORKSPACE_LAUNCHER}} investment-brains rollback <investment-brain-id> [--version <major.minor.patch>]
   {{TRADINGCODEX_WORKSPACE_LAUNCHER}} investment-brains remove <investment-brain-id>
   ```

5. Update by publishing a higher immutable version. Never rewrite installed
   bytes under an existing version. Rollback selects an already-installed
   version; remove retains all installed versions for provenance.
6. Return the action, Brain id, selected version, status, validation posture,
   source posture, digests, projection posture, and exact next step. Do not
   expose credentials or absolute external local paths.

## Hard Stops

- Do not mutate Decision Memory, Investor Context, a Strategy, or current
  evidence while managing a Brain.
- Do not present a Brain as validated investment truth; current authenticated
  evidence can falsify it.
- Do not stage, commit, configure a remote, push, publish, or open a pull
  request unless the user separately requests that Git or publication action.
- Do not approve orders, grant broker authority, change policy, submit, cancel,
  or execute through this skill.
