# Harness

TradingCodex is the investment operating system built on Codex. The harness is
its orchestration and runtime subsystem: it coordinates roles, managed skills,
service-layer state, policy, MCP tools, research memory, artifacts, approvals,
execution adapters, audit, and feedback loops without becoming the whole
product definition.

TradingCodex is therefore not just a set of guardrails. Guardrails are one
subsystem of the harness. Improvement is another subsystem.

The TradingCodex runtime is implemented and maintained through harness components.
Guardrails and Improvement are taxonomy views over those components, not
implementation buckets. A component can carry multiple taxonomy tags when it
spans guidance, enforcement, information barriers, workflow quality, research
memory, or validation feedback.

## Top-Level Model

```text
TradingCodex Investment OS
  -> Core kernel
       -> quality, evidence, point-in-time, forecast, role, policy,
          approval, audit, and execution contracts
  -> Bundled investment capability pack
       -> default research, analysis, valuation, forecasting, portfolio,
          risk, and independent-review procedures
  -> Managed user overlays
       -> optional role skills, additional instructions, strategy-* rules,
          and reviewed data/connectivity extensions
  -> Harness orchestration/runtime subsystem
       -> coordinates the core kernel, bundled pack, and managed overlays
       -> Components
            -> investment-request-routing
            -> fixed-role-dispatch
            -> context-efficiency-contract
            -> responsibility-boundary-contract
            -> approval-gate
            -> execution-boundary
            -> research-memory
            -> ...
       -> Guardrails
            -> Guidance guardrails
            -> Enforcement guardrails
            -> Information barriers
       -> Improvement
            -> Workflow quality
            -> Research memory and source freshness
            -> Skill proposals
            -> Postmortems
            -> Validation/test feedback
```

The core kernel is the invariant contract, not one investing philosophy or one
analysis recipe. The bundled capability pack gives a pristine workspace useful
investment capabilities. Managed overlays specialize that baseline but remain
additive: they cannot replace evidence discipline, point-in-time correctness,
method fit, uncertainty, forecast scoring, role boundaries, policy, approval,
audit, or execution safety.

## What The Harness Owns

| Area | Harness responsibility |
| --- | --- |
| Roles | Keep one `head-manager` and ten fixed subagents as the default coordination model, including an independent `judgment-reviewer` gate. |
| Skills | Keep the core contract and bundled role skills locked and file-native, expose direct user entrypoints, support `strategy-*` strategy skills, and let `head-manager` manage additive role-local optional skills through workspace files while Django shows status only. |
| State | Keep execution-sensitive runtime state in the central Django DB, while Codex-native agent, skill, and research handoff state is workspace-file state. |
| Interfaces | Expose Web, Admin, REST, CLI, and MCP as service-layer callers. |
| Guardrails | Reduce, restrict, or block risky actions through guidance, enforcement, and information barriers. |
| Improvement | Raise workflow quality through no-overlap handoff contracts, quality gates, artifact readiness, research memory, improve records, postmortem review, and test feedback. |
| Approved action boundary | Keep executable actions behind policy, approval, duplicate-request, connection, and audit checks. |
| Decision packages | Keep investment ideas Codex-native by packaging workflow plans, artifact paths, source trust notes, thesis lifecycle state, profile gaps, blocked actions, and next allowed actions as workspace markdown. Non-investment workflow packages such as connector build or strategy authoring use workflow lifecycle state instead of thesis lifecycle or portfolio/risk language. |
| Provenance | Record which workspace and role produced or requested work without making workspaces separate ledgers. |
| Profiles | Separate paper portfolio/account/strategy state from workspace identity. |
| Components | Provide the developer-facing maintenance map for implementation surfaces, dependencies, capabilities, tags, and validation. |
| Context efficiency | Keep subagent briefs compact, pass artifact paths and context summaries before full artifacts, audit long runs with `subagents context-audit` over workflow intake history, and avoid repeated role manuals or source dumps. |
| Responsibility boundaries | Keep role identity, MCP allowlists, permission profiles, hooks, policies, skills, schemas, and service behavior in their own authoritative surfaces. |

## Components As Maintenance Units

The canonical component registry lives in
`tradingcodex_service.application.components`. Each component declares:

- stable id, label, summary, and status
- descriptive taxonomy tags such as `guardrail.guidance` or
  `improvement.workflow_quality`
- implementation surfaces such as instructions, skills, hooks, services,
  templates, models, MCP tools, and tests
- dependencies, owned capabilities, and validation expectations

Generated workspace modules remain deployment projections. They are not the
source of conceptual ownership. Generated workspaces receive
`.tradingcodex/generated/component-index.json` from the Python registry.

The component registry describes the harness subsystem and its implementation
surfaces. It does not turn a component, prompt, skill, or generated file into
the top-level product definition, and it does not make a user overlay part of
the core kernel.

When a change crosses surfaces, update the component rather than duplicating
logic. For example, role identity belongs in role TOML and service registries;
skill bodies describe procedures; hooks classify and write guidance context;
information-barrier policy files describe file/tool walls; services enforce
durable behavior.

## Guardrails Under Harness

Guardrails answer: "What should be prevented, reduced, isolated, or blocked?"
They are tags and review lenses applied to components.

- Guidance guardrails shape agent behavior before risky action.
- Enforcement guardrails deterministically block final risky action paths.
- Information barriers limit role knowledge, file access, secrets, and tool surfaces.

Guardrails never replace the need for improvement. A blocked action can still
leave behind a useful improve record, postmortem review, skill proposal, or
validation scenario.

## Improvement Under Harness

Improvement answers: "How does the next workflow become higher quality?"
It is a tag and review lens applied to components.

- Workflow maps route work to the right role team.
- Quality gates define evidence, source/as-of posture, claim discipline, handoff acceptance, and readiness.
- Improve records preserve reusable analysis memory from artifacts,
  postmortem review, and loop feedback without changing prompts, skills, policy,
  broker, approval, or execution authority.
- Handoff contracts keep downstream roles from filling missing upstream work outside their owned question.
- Research memory preserves workspace markdown artifacts, versions, source posture, and source snapshots.
- Skill proposals let the harness evolve without hidden prompt drift.
- Postmortems turn rejected orders, failed checks, and thesis changes into process improvements.
- Validation tests convert recurring mistakes into regression coverage.
- Context efficiency keeps those quality gates usable by passing summaries and
  artifact references first, then opening full evidence only when needed.
- Context-budget audits make long multi-subagent runs inspectable by checking
  compact hook intake, intake history, bounded subagent session state,
  workflow loop state, and `context_summary` coverage across research
  artifacts. Full subagent event history stays in append-only audit JSONL.

Improvement does not authorize execution. A high-quality report still needs the
guardrail path before any draft, approval, or non-live connection use.

The Artifact Supervisor Loop is part of Improvement, not a new monolithic
workflow. It turns accepted, revised, blocked, and waiting artifacts into
bounded follow-up, challenge, escalation, or synthesis decisions. The Decision
Quality Spine remains the cross-lane quality contract inside that loop. Neither
the loop nor the spine widens role authority, MCP access, approval, execution,
broker, or secret boundaries.

## Harness V2 Control Contracts

Harness V2 makes the existing workflow discipline machine-checkable without
turning the workspace projection into execution authority.

- A language-neutral structured intent envelope records requested, forbidden,
  and unresolved actions, classifier provenance, confidence, and whether user
  confirmation is required. The built-in deterministic classifier is reviewed
  for English. Unsupported or low-confidence language falls back to
  research-only/waiting posture and blocks high-impact actions until a reviewed
  classifier or the user resolves the intent.
- A typed routing envelope fixes the lane, eligible/required/forbidden roles,
  blocked actions, required gates, task and concurrency budgets, terminal
  conditions, intake hash, and routing-policy version.
- The plan compiler accepts only a strict subset of that envelope. Unknown
  lanes or fields, forbidden roles, later-stage dependency violations, budget
  excess, or scope widening fail validation.
- Each workflow run has one revisioned state reducer. State transitions are
  serialized, idempotent by event id, atomically projected to the per-run
  `loop-state.json`, and recorded in `events.jsonl`. The latest summary is a
  pointer, not canonical state.
- Process completion and artifact acceptance are separate. `SubagentStop`
  changes process state only; a dependent stage remains closed until the
  required artifact passes the run-bound artifact gate.
- Automatically consumable artifacts bind to `workflow_run_id`, `plan_hash`,
  `stage_id`, `task_id`, producer role, schema version, body hash, accepted
  input artifact hashes, and source snapshot ids. Legacy unbound files remain
  readable but cannot release a stage.
- The ten-role roster is independent from scheduler concurrency. Generated
  workspaces use a six-thread ceiling with `max_depth = 1`; lane budgets and
  dependency readiness determine which roles may run.

The current canonical workflow control store remains the revisioned per-run
workspace projection. Its append-only event stream can be replayed and checked
against the materialized state. A future move to DB-canonical workflow events
would require an explicit dual-read/cutover change; it is not implied by the
current file-native reducer.

## Investment Method And Evaluation Profiles

The core quality contract is method-agnostic. A ResearchSpec selects a bounded
method profile so the harness can require the fields and checks appropriate to
the work instead of projecting one research style across every workflow. The
bundled profiles are `general_evidence_v1`, `event_research_v1`,
`quant_signal_v1`, and `listed_equity_fcff_dcf_v1`. The FCFF DCF profile is one
explicit built-in valuation method, not the definition of listed-equity
analysis; unsupported or method-mismatched cases return a support gap or use a
different profile.

Evaluation is profile-based as well. `core_investment_v1` owns the bundled
cross-cutting case classes and metrics, while corpus-defined profiles may test a
bounded non-quantitative or specialized method with their own declared case
tags and metric dimensions. Profile creation validates evaluation shape; it
does not prove that a model, prompt, built-in capability, or user overlay is
better. Promotion still requires populated frozen evidence, paired runs,
deterministic hard-failure checks, independent blind review, and provenance
verified by a trusted evaluation runner. Caller-attested run digests may be
stored and reviewed, but they cannot produce a `promote` decision.

Pristine quality and customization quality are evaluated separately. The
pristine arm uses only the core kernel and bundled capability pack. A customized
arm may add a managed overlay, but it must retain every core hard gate and may
claim improvement only within the overlay's declared scope.

## Runtime Model Policy

Model selection is registry-owned and projected into generated Codex config;
skills do not select models or alter tool authority. The active role policy is:

| Tier | Current projection | Intended work |
| --- | --- | --- |
| Sol | `gpt-5.6-sol`, `high` | Head-manager synthesis, valuation, portfolio/risk judgment, and independent challenge. |
| Terra | `gpt-5.6-terra`, `high` | Routine evidence and market analysis. |
| Luna | `gpt-5.6-luna`, `low` | Bounded execution-operator tool coordination; deterministic services still decide execution. |

Every role has an allowlisted GPT-5.5 rollback target. Setting
`TRADINGCODEX_MODEL_ROLLOUT=rollback` regenerates the fallback policy. When
`TRADINGCODEX_CODEX_SUPPORTED_MODELS` is supplied, an unsupported primary also
falls back; otherwise the manifest reports runtime support as `unverified`
rather than pretending that generation proved client compatibility. The
generated `.tradingcodex/generated/model-policy-manifest.json` records policy,
prompt, tool-profile, rollout, capability, and fallback metadata, and `doctor`
checks registry-to-projection consistency.

API-only GPT-5.6 features such as Pro/max effort, persisted reasoning,
Programmatic Tool Calling, explicit cache controls, and Responses multi-agent
mode are not Codex project-TOML settings in this harness. They remain deferred
adapter experiments and never change permissions, MCP allowlists, approval, or
execution authority.

Runtime loop inspection is file-native and read-first. `$plan-workflow`
clarifies ambiguous requests into a compact mandate; `UserPromptSubmit`
writes compact intake; `$tcx-workflow` records the validated staged plan and
canonical per-run state under
`.tradingcodex/mainagent/workflows/<workflow_run_id>/`. A compact latest
summary stays at `.tradingcodex/mainagent/workflow-loop-state.json`;
`tcx subagents plan` shows the current staged plan, selected team, pending
tasks, stop reason, and canonical state path.
Codex session/thread ids are mapped through
`.tradingcodex/mainagent/session-workflow-runs.json`, so multiple Codex app
threads in the same workspace can continue different loops without overwriting
each other. `tcx subagents loop --artifact <path>` previews closed planner
actions from artifact handoff state and `follow_up_requests`. `--record` may
append the computed pending tasks and escalation proposals to the loop state and
`trading/audit/workflow-loop-events.jsonl`, but it still does not spawn
subagents, approve orders, or execute.

## Interface Implications

The product web app should make the harness usable through a workflow-planner
first screen, then an agents/skills browser for inspection: users can start from
a plain-language investment request, while head-manager and fixed subagents,
required and optional skills, and markdown bodies remain inspectable without
hand-rolled parsing. Django Admin stays on default model registration for
local/staff DB inspection; richer operations belong in product web, CLI, API, or
MCP service-layer paths. CLI checks should keep separate layers for guidance,
enforcement, information barriers, improvement, MCP, and service status.

Long workspace paths, projection hashes, component maintenance details, and
file internals belong in collapsed diagnostics unless the user opens them.

## Naming Rule

Use "investment OS" for the top-level TradingCodex product. Use "harness" for
the orchestration/runtime subsystem that coordinates Codex, generated workspace
state, service calls, and workflow components. Use "guardrail" only for
safety/restriction systems. Use "improvement" for quality, investment judgment
learning, skill, postmortem, and validation loops.
