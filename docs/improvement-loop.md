# Improvement Loop

Improvement is the quality subsystem under the top-level TradingCodex workspace orchestration model.
For investment workflows, self-improvement means better investment judgment:
clearer evidence, assumptions, source posture, valuation sensitivity, risk
context, and decision readiness. It is not hidden prompt, skill, policy, broker,
approval, or execution mutation.

The broader harness also supports explicit skill proposals and validation
feedback, but those are deliberate maintenance paths, not automatic investment
workflow self-modification.

Improvement is separate from Guardrails. Improvement can raise confidence and
reduce repeated mistakes, but it never authorizes execution by itself.

Improvement areas are review lenses, not runtime records, registries, folders,
or ownership buckets. Developers change the canonical service, skill, prompt,
or test that owns a behavior and use the taxonomy below to check the outcome.

## Improvement Taxonomy

| Improvement area | Purpose | Examples |
| --- | --- | --- |
| Workflow quality | Route work to the right role team, prevent role overlap, and require useful handoffs. | workflow maps, role briefs, artifact paths, handoff acceptance states, readiness gates |
| Research memory | Preserve source-aware work products for agent handoff and human review. | workspace markdown artifacts, versions, source snapshots, readiness labels |
| Skill evolution | Improve role behavior without hidden prompt drift. | workspace proposal files, validator results, CLI/Web projection, generated manifest |
| Postmortems | Learn from rejected orders, failed checks, thesis changes, and executions. | root cause, guardrail fired, changed assumptions, process improvement |
| Validation feedback | Convert recurring issues into tests and smoke checks. | routing scenarios, MCP smoke tests, generated workspace doctor checks |

## Workflow Quality

Workflow quality starts before analysis. `head-manager` classifies the universe
and workflow type, chooses the role team, sets artifact paths, and waits for
role outputs before synthesis.

Quality gates should preserve:

- source/as-of posture
- source trust notes
- clear distinctions between sourced facts, analysis, and assumptions
- role boundaries
- missing evidence
- uncertainty
- readiness labels
- contrary evidence, update triggers, and invalidation conditions
- thesis lifecycle notes when decision quality is required
- hero/support artifact split
- no-overlap role ownership
- handoff acceptance state: `accepted`, `revise`, `blocked`, or `waiting`

Downstream roles consume accepted upstream artifacts. If an upstream artifact is
missing, stale, weak, or outside scope, the downstream role requests revision or
returns `blocked`; it does not silently perform the upstream role's work. This
keeps the workflow quality loop about improving artifacts and routing, not
blurring specialist responsibilities.

Every role must be justified by the current mandate or accepted evidence.
Adding extra roles can create hidden scope drift, so research-only work remains
with the smallest useful research roles unless the user broadens the mandate or
Head Manager identifies a distinct unresolved question.

## Research Memory

Research memory keeps handoff-ready research in workspace markdown files.
Codex-native research must be visible as files under `trading/research` and
`trading/reports`; the service layer indexes, validates, searches, and previews
those files instead of hiding canonical research only in DB rows.

Good research memory improves later work by preserving:

- source date and retrieved-at time
- version history
- content hashes
- stale-data warnings
- role/user provenance
- workspace provenance
- readiness labels

## Skill Evolution

Skill proposals let TradingCodex change role-owned behavior deliberately.

Expected flow:

```text
proposal -> validation -> approval -> apply -> audit
```

This keeps improvements visible through Admin, CLI, tests, and docs instead of
letting hidden prompt changes become durable product rules.

## Improve Ledger

TradingCodex uses the memory pattern from self-improving agent systems, but the
thing being improved is investment judgment: evidence discipline, source
quality, assumptions, valuation sensitivity, forecast calibration, risk misses,
portfolio-context gaps, contradictions, and decision readiness. It does not let
an agent silently rewrite durable prompts, roles, policy, MCP allowlists, broker
posture, approvals, execution gates, or skills during an investment workflow.

Research artifacts may include `improvements` frontmatter. Postmortem review
and Head Manager artifact review can also record selected feedback such as
blocked artifacts, evidence gaps, and unsuccessful follow-ups. Recorded
improvements are stored under the append-only
`.tradingcodex/mainagent/improve.jsonl` ledger. A small authenticated
`lesson-chain-heads.json` file binds the latest hash and sequence for each
lesson; there is no parallel improve index or workflow-rebuild command.
Each event carries source path, improvement type, materiality, reason, evidence refs,
review state, reuse state, and the fixed authority boundary
`no_policy_skill_or_execution_change`.

The JSONL ledger is the workspace-owned audit trail. Reads verify every event
hash, sequence, prior-event hash, and the authenticated chain-head file before
returning lessons. Only authenticated postmortem and judgment-review service
flows record or promote lessons. Doctor validates the same chain directly;
there is no nonexistent `tcx workflow improve` repair path.

The ledger is inspired by Hermes-style procedural memory and GEPA-style
trace-driven reflection, but TradingCodex keeps the application rule simple:

```text
trace/artifact/postmortem -> improve record -> future judgment review -> audit
```

Improve records are not system changes. They are compact investment-analysis memory for
future workflows. Skill changes still use optional skill CRUD or skill proposal
projection. Policy, role, approval, execution, broker, and secret surfaces still
use their existing service-layer gates.

An improve record is not automatically a validated lesson. Decision Memory
keeps fast episode capture separate from slow semantic consolidation:

```text
candidate -> corroborated -> validated -> retired
```

Evidence origin is recorded separately as `historical_replay`,
`historical_holdout`, or `live_forward`. Promotion requires scoped independent
cases, contrary-case review, correlation checks, and the declared out-of-sample
test. Strategy, skill, prompt, policy, approval, broker, and execution changes
remain explicit review flows even after a lesson is validated.

## Postmortems

Postmortems are not only for executed orders. They also apply to:

- rejected orders
- blocked approval attempts
- failed policy checks
- stale or weak evidence
- thesis changes
- routing failures
- blocked, revised, or escalated Codex-native handoffs evidenced by run-local
  artifacts and `trading/audit/codex-hooks.jsonl`
- process gaps
- successful decisions whose process should be understood without outcome bias

A useful postmortem should include an investment judgment review: original
thesis, what happened, failed assumption, role evidence miss or overstatement,
stale or misleading source, confidence calibration, and future warning pattern.
It should end with concrete `improve` records about investment judgment,
analysis readiness, source quality, assumptions, risk, or evidence gaps.

When a frozen decision-time packet exists, review it in two passes. First hide
the realized outcome and evaluate the knowable evidence, alternatives,
assumptions, probability, invalidation conditions, and handoff process. Lock
that process assessment before revealing P&L, benchmark result, drawdown, or
forecast score. Then evaluate the outcome and calibration separately. A good
process may have a bad outcome and a poor process may be profitable.

Keep three error loops distinct:

- knowledge-base integrity repairs such as stale summaries or broken links;
- decision-process lessons such as missed contrary evidence or a wrong method;
  and
- forecast resolution, dispute, scoring, and calibration corrections.

A postmortem emits lesson candidates and validation work. One episode does not
become a rule, and no postmortem silently rewrites a strategy or another durable
system surface. The full contract is in
[decision-memory.md](./decision-memory.md).

## Validation Feedback

Validation feedback turns improve findings into regression coverage:

- unit tests for policy and execution preconditions
- API tests for Admin/Ninja/MCP boundaries
- generated workspace smoke checks
- strict research artifact quality checks for source/as-of posture,
  handoff state, confidence, missing evidence, next recipient, blocked actions,
  and source snapshots
- research-memory smoke checks
- routing scenario tests
- UI checks for review-only product web behavior

The validation plan is part of improvement because it prevents old mistakes
from returning.
