---
name: tcx-build
description: Mark one exact root Codex turn as explicit workspace-local TradingCodex Build intent for workspace refresh, managed optional skill, Strategy, or Investment Brain lifecycle work, managed MCP configuration, and broker/API provider development without elevating filesystem permission or granting order execution.
---

# TCX Build

Use this skill only when the original root user prompt begins with the exact physical first line `$tcx-build`.
The remaining lines describe the requested build work.

## Turn Contract

- Treat the marker as current-turn user intent, not filesystem permission.
- Codex's actual sandbox still decides whether a tool can write. Never claim
  that the skill or hook elevated a read-only filesystem session. A read-only
  turn may still render or inspect data and use the specifically proof-protected
  canonical DB calls because those writes remain service-owned.
- Do not issue or use a Build grant while Codex is in platform Plan mode.
  Start a new root turn in `workspace-write` when the requested work must edit
  files. The grant is bound to the permission mode in which it was issued, so
  switching modes does not carry authority forward.
- Use the grant only in the root native Codex turn. Workbench and subagents
  cannot inherit or use it.
- The grant is multi-use within this turn so editing and validation can finish.
  A follow-up turn that mutates state must begin with `$tcx-build` again.
- For recurring Automation, require the saved prompt to start with the marker
  on every run. File-mutating work also requires `workspace-write`; prefer an
  isolated worktree or workspace and retain a reviewable diff.
- Keep direct edits and commands workspace-local. Use typed TradingCodex
  MCP services for connector state. External MCP lifecycle changes remain a
  separate user-terminal operator workflow.
- Keep local work in the deterministic Build lane: use native `apply_patch`,
  exact workspace `pwd`/`cat`/limited `ls` reads, the trusted workspace
  launcher allowlist, and only `python -I -S -m py_compile` for explicit Python
  files below `trading/connectors/`. Do not run general shell commands, helper
  scripts, interpreters, `pytest`, or build/test runners in the generated Build
  turn.

If the actual Codex permission blocks a required tool, report that platform
blocker and stop. Do not create another TradingCodex permission state.

## Procedure

1. Confirm the request is product/build work, not an investment recommendation or execution request.
2. For self-update, inspect status only after an explicit user request. When `package_refresh_user_terminal_required=true`, do not run the refresh and return `interactive_user_terminal_command`. Otherwise run non-empty `update_status.command` only when it is admitted by the trusted workspace-launcher Build lane; if it is unavailable, return the reported terminal command. After an update, stop and tell the user to fully restart Codex.
3. For an Investment Brain, require one explicit workspace-local directory or a public credential-free HTTPS Git URL/ref. Use `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} investment-brains install --local <bundle> --inactive` or `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} investment-brains install --git <https-url> --ref <ref> --inactive`, inspect the validated id/version/source/digest, and activate only when the user asked to use it. Manage later state with `list`, `inspect`, `update`, `rollback`, `deactivate`, `activate`, and `remove`. Private, authenticated, SSH, file, or local Git sources require an explicit user-terminal workflow. Never infer a source, search a marketplace, edit the source repository, or stage, commit, push, or open a pull request implicitly.
4. For a managed Strategy or optional role skill, author the standalone body with `apply_patch` in a workspace-local staging file, then use the exact `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} strategies ...` or `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} skills optional ...` lifecycle command so validation and projection remain service-owned. Do not directly repair generated skill folders, role TOML, or root projection blocks. Activation still requires the user's explicit request.
5. For Codex config and MCP customization, use `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} build status`, `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} build codex-mcp discover`, and workspace-scoped `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} build codex-mcp add`. Importing a discovered entry into the External MCP Gate is not Build work; stop with the exact interactive user-terminal command `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} mcp external import-codex --source workspace|global|any --name <server>`. Use `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} mcp permission list` only to surface pending external consent requests; only the user may approve or deny them.
6. Never register, probe, discover, or review an External MCP server from Head Manager in a Build turn. Prepare workspace-local config if requested, then stop with the exact user-terminal `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} mcp external ...` next step. Do not expose unmanaged external MCP tools directly to subagents.
7. For broker connectors, inspect providers with the read-only provider-list tool, then call `render_broker_connector_scaffold`. It returns target content plus content-addressed preimage existence/hash/size metadata and performs no workspace write; it never returns existing file content. Verify those preimages and create or update the returned files with `apply_patch`; never ask an MCP scaffold tool to write them. Use only the build-protected DB tools `register_broker_connector`, `validate_broker_connector_build`, and `record_broker_mapping_review` for service state. `connect` and the write-style `scaffold` command remain explicit user-terminal operator flows and are not agent MCP tools; do not invoke their CLI equivalents from the agent shell. Provider implementation files remain workspace-local edits.
8. Store only credential references, env key names, and secret schemas. Never request or persist raw credentials.
9. If an external MCP call needs user consent, stop at `waiting_for_user_permission` and surface the pending request; do not bury the prompt in a subagent transcript.
10. If the requested provider is not installed, treat the task as provider development or scaffold a provider-development-required connector; do not pretend the broker is already supported.
11. A workspace provider bundle is untrusted source until the user approves its exact bundle hash from a terminal. Stop with `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} connectors inspect-provider <provider-id>` and `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} connectors approve-provider <provider-id>`, and require re-approval after every bundle change; never approve provider code from the Build turn. Approval snapshots the reviewed bytes but executes no code. Report `service_restart_required` and stop at validation until the service restarts.
12. In the generated Build turn, validate with the trusted `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} doctor` path and, for connector source only, isolated `python -I -S -m py_compile <explicit-provider-paths>`. Report the exact focused-test and generated-workspace smoke commands for an explicit operator or maintainer terminal. Do not run `pytest`, arbitrary Python, helper scripts, or build runners from the agent shell. Stop after a successful self-update and tell the user to restart Codex.

## Hard Stops

- A Build turn may create live-capable providers, but never submits or cancels an order.
- Do not use Codex Plan mode as Build authority; it blocks the grant entirely.
  In a read-only native or Automation runtime, do not attempt native workspace
  edits. Limit work to rendering/inspection and specifically proof-protected
  canonical DB calls.
- Do not use the grant for global Codex config, raw credential access, External MCP lifecycle or consent decisions, provider-source approval, Git push/publication, or direct edits to hooks, grants, managed `.gitignore`, credential files, runtime DB, audit, approval, policy, or execution state.
- Do not directly edit generated core harness files, hooks, workspace templates,
  fixed-role configuration, or service-owned projection blocks. Use the
  supported workspace refresh or managed lifecycle service instead.
- Do not call raw broker APIs from shell, hooks, skills, or ad hoc scripts.
- Do not bypass TradingCodex policy, approval, idempotency, connection, or audit gates.
- If a protected call reports that the operation completed but grant
  finalization failed, stop and inspect canonical state. The grant is revoked
  fail-closed; never retry the operation blindly.
- Order submission or cancellation belongs outside Build and must enter through
  the exact native execution gateway for its own current root turn. Broker API,
  SDK, or broker-specific MCP calls stay behind reviewed service adapters.
- Do not rewrite user-owned Codex config outside TradingCodex managed blocks.
