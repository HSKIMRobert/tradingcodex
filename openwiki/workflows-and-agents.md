# Workflows And Agents

Use this page before changing Head Manager, fixed roles, skills, hooks, handoffs,
artifact lineage, or native dispatch progress. Durable product rules live in
[`docs/roles-skills-and-workflows.md`](../docs/roles-skills-and-workflows.md) and
[`docs/codex-native-orchestration.md`](../docs/codex-native-orchestration.md).

## Runtime Model

Investment orchestration is Codex-native:

```text
user
  -> Head Manager interprets the original language
  -> begin_analysis_run (hash + sealed Brain/Strategy/Context provenance only)
  -> optional one exact explicit Investment Brain inquiry overlay
  -> exact V2 role children, parallel where independent
  -> authenticated role artifacts
  -> Head Manager revises/adds/challenges/stops dynamically
  -> run-local synthesis artifact
```

Django does not classify investment meaning, select a lane or team, compile a
DAG, issue dispatch tasks, or run an artifact supervisor state machine. For
analysis, the hook supplies service health, transport/run binding, exact-role
checks, audit, and tool policy. Separately, it reserves the two literal
immediate root-native action tokens and parses their complete fixed grammar.
It also recognizes only an exact physical-first-line `$tcx-order-allow --mode
paper|validation|live` to issue a bounded `OrderTurnGrant`; none of these
checks is natural-language routing or prose-scope enforcement.
Separately, exact physical-first-line `$tcx-build` issues a DB-canonical
workspace/session/turn/cwd/prompt-bound Build grant and activates deterministic
write/protected-MCP hook gates for that root native turn only. It never elevates
the actual Codex sandbox, and subagents cannot inherit it. The browser viewer
has no Build path.

An Investment Brain is a TradingCodex-managed, Head Manager-level,
platform-neutral inquiry and interpretation overlay. Native analysis selects at
most one with an exact `$investment-brain-*` invocation. Head Manager translates
its hypotheses and questions into dynamic role-owned work; the Brain never owns
roles, tools, workflow, memory, policy, approval, or execution. No Brain is the
pristine baseline, while multiple or unresolved Brains fail closed.

The run also seals the complete projected Brain skill digest. Optional Markdown
references are lazy: the native hook allows only a standalone `cat` below the
selected projection's `references/` directory when the current Codex session
maps to that exact run and the whole projection still matches the sealed
digest. Unbound, stale, changed, unselected, compound, registry/package/source,
index, and role-config reads fail closed.

`$tcx-brain` is the Head Manager-only management entrypoint for source
create/inspect/revise/validate/delete and installed plugin
list/inspect/install/update/activate/deactivate/rollback/remove. Every mutation
requires an exact Build turn. Source mutation stops before lifecycle work;
installation starts inactive in a fresh Build turn and activation remains
explicit. The skill never edits managed/third-party packages directly or
implies Git/publication actions.

## Fixed Team

Head Manager coordinates nine fixed roles: fundamental, technical, news, macro,
instrument, valuation, portfolio, risk, and judgment review. There is no
execution subagent. The first six evidence roles have live web search; Head
Manager and the remaining roles consume authenticated artifacts or service
state.

Every spawn must use exact `agent_type`, compact underscore-only `task_name`,
compact message, and `fork_turns="none"`. Each revision or follow-up is a fresh
child. Generic-role fallback, `followup_task`, full-history fork, role-TOML
emulation, and source-code routing are invalid.

## Skill Namespace

The 31 bundled skills all use `tcx-` plus one suffix word when possible and at
most two words. Folder, frontmatter, registry, projection, UI metadata, and `$`
invocation ids are identical; legacy core aliases are not projected. `tcx-` is
reserved for bundled skills. User-owned `strategy-*`, `investment-brain-*`,
and optional role skills keep separate namespaces.

`tcx-dashboard` is the read-only user overview projected only to Head Manager.
It summarizes canonical workspace state and routes detail to the viewer without
starting an analysis run or mutating state. `tcx-server` remains the separate
diagnostic and recovery entrypoint.

## Durable Boundary

`begin_analysis_run` writes only request hash/size, run id, timestamps, and
sealed optional Investment Brain, Strategy, and Investor Context provenance under
`.tradingcodex/mainagent/runs/<run-id>/run.json`. It stores no raw request,
semantic lane, selected team, plan, task queue, or terminal action.

Producing roles write their own reports through `create_research_artifact`.
The service binds authenticated principal/producer identity, verifies the run,
validates exact run-local `input_artifact_ids`, and derives content/input hashes.
For Brain-bound runs it also derives `investment_brain_id`,
`investment_brain_version`, and `investment_brain_content_digest`. Head Manager
may synthesize only with at least one verified input artifact.

Context authority is typed: Core owns safety and provenance, the mandate owns
scope, Investor Context limits suitability, Strategy owns explicit decision
rules, Brain guides inquiry, methods own bounded procedure, current evidence
controls facts, and Decision Memory remains non-authoritative evidence. New
judgment is blind-first with respect to similar memory, and synthesis states
the Brain influence, conflicts, and post-memory delta.

Execution remains service-owned. Root `tcx-order-submit` and
`tcx-order-cancel` bundles document an explicit-only protocol but contain
no tools. For an exact complete root native user prompt, `UserPromptSubmit`
creates a workspace-bound `native-user` mandate and calls
`application/execution_gateway.py` in-process before analysis begins.

The explicit-only `tcx-order-allow` bundle is the in-workflow alternative. A valid
first line binds one grant to workspace, session, turn, complete prompt hash,
Codex permission mode, and execution mode, then normal role orchestration
continues. Plan mode rejects immediate order effects plus grant issuance and
use. The grant expires after one hour and is revoked after one submit or cancel,
on `Stop`, or on the next user turn. Only root Head Manager can call
`use_order_turn_grant`; `PreToolUse`
reserves the grant for the tool-use id and injects the internal proof. The model,
fixed roles, and direct MCP callers cannot supply it; the browser viewer has no
grant entrypoint.

`tcx-automate` authors Codex app Scheduled Tasks for simple research,
monitoring, analysis, portfolio/status review, draft, assisted, optional
turn-authorized execution, and explicitly delegated turn-authorized Build work.
The saved prompt is submitted each scheduled turn and invokes the actual work
skill, never `tcx-automate` recursively. TradingCodex does not detect an
Automation origin; scheduled and interactive root turns use the same hook path.
Only an execution-capable task includes the exact `$tcx-order-allow` first line;
only recurring Build work includes `$tcx-build`, every run earns a fresh grant,
and the markers are never combined.

Public REST and generic CLI cannot perform submit/cancel, and a direct MCP call
to the protected tool has no authority. The service deterministically enforces
canonical policy, ticket, receipt, action, broker posture, and mode, not
free-form natural-language scope.
Policy, order tickets, approval receipts, idempotency, account/broker state,
submission, cancellation, reconciliation, and audit remain in the service
kernel.

## Key Sources

- `tradingcodex_service/application/analysis_runs.py`
- `tradingcodex_service/application/research.py`
- `tradingcodex_service/mcp_runtime.py`
- `tradingcodex_service/application/viewer.py`
- `tradingcodex_service/application/execution_gateway.py`
- `tradingcodex_service/application/build_gateway.py`
- `workspace_templates/modules/codex-base/files/.codex/hooks/tradingcodex_hook.py`
- `workspace_templates/modules/codex-base/files/.codex/prompts/base_instructions/head-manager.md`
- `workspace_templates/modules/repo-skills/files/.agents/skills/tcx-workflow/SKILL.md`
- `workspace_templates/modules/repo-skills/files/.agents/skills/tcx-workflow/references/context-and-override.md`
- `workspace_templates/modules/fixed-subagents/files/.codex/agents/*.toml`
- `docs/investment-brain-plugins.md`

## Validation

Regenerate a clean workspace. Verify nine fixed roles and all 31 skills,
including the three native execution bundles, with no retired execution
role/skill. MCP `tools/list` must omit raw submit/cancel/refresh mutations,
expose `use_order_turn_grant` only to Head Manager, and omit obsolete
workflow-control tools;
`begin_analysis_run` is Head Manager-only. Hooks must accept only exact root
native actions or first-line order grants, bind/revoke/inject proof correctly,
reject malformed/subagent/direct-MCP forms, and otherwise avoid
language classification or plan/state reads. Also verify exact V2 role dispatch,
artifact lineage, native role progress, Brain selection/failure,
typed conflicts, blind-first memory, and unchanged service execution gates.
