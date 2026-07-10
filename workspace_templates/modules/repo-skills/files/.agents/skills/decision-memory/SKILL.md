---
name: decision-memory
description: "Review past investment decisions, run point-in-time historical replays, compare resolved forecasts and forward outcomes, and validate lesson candidates. Use when the user asks what happened before, why a thesis changed, whether a strategy lesson held out of sample, or what prior evidence is relevant to a current decision."
---

# Decision Memory

Use the existing file-native decision packages, research artifacts, source
snapshots, replay manifests, forecast ledger, postmortems, and improve records.
Treat generated summaries, links, and Wiki-style pages as read views, never as
the canonical record.

## Choose The Mode

- **Retrieve**: find relevant prior decisions, forecasts, evidence, outcomes,
  and lessons. Preserve contrary and retired records; do not return only
  successful cases.
- **Replay**: freeze an as-of time and use only source snapshots knowable by
  that cutoff. Record the ResearchSpec and replay manifest before revealing the
  outcome.
- **Review**: compare the frozen decision process with the resolved outcome.
  Assess process quality before revealing P&L or outcome quality, then keep the
  two judgments separate.
- **Validate**: compare a lesson candidate across independent episodes,
  historical holdout periods, regimes, and live forward evidence.

## Procedure

1. Identify the subject, decision or forecast id when known, time cutoff,
   evidence origin, and selected strategy snapshot. Use `no_strategy` when no
   strategy applied. Use `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} decision snapshot
   list` and `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} postmortem list` when the user
   did not supply an id; use `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} workflow
   improve` for the candidate and reviewed lesson ledger.
2. For a current decision, record the independent initial view before retrieving
   similar cases. After retrieval, show what changed and why.
3. For historical replay, reject sources whose `known_at` exceeds the cutoff.
   Preserve data vintage, universe membership, delistings, corporate actions,
   costs, model/prompt/tool hashes, and every attempted hypothesis or parameter
   trial when applicable.
4. Freeze forecasts and invalidation conditions before outcomes are visible.
   Resolve and score forecasts through the append-only forecast lifecycle.
5. Once accepted decision-time artifacts are frozen, record the immutable
   snapshot with `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} decision snapshot record
   <payload.json|->`. The payload must reference the recorded workflow intake;
   never substitute the currently active strategy or investor context.
6. Before any outcome is recorded or revealed, reconstruct intent, evidence,
   alternatives, assumptions, guardrails, and the decision-time process from
   durable artifacts. Lock that first pass with
   `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} postmortem process-review
   <payload.json|->`. Do not invent missing events or include outcome knowledge
   in this artifact.
7. Only after the process review is locked, record and independently resolve the
   outcome. Create the second-pass report with
   `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} postmortem create <payload.json|->`,
   binding `process_review_id`, the sealed DecisionSnapshot, and undisputed
   forecast outcome events. Store any generalization as a lesson candidate,
   not as a durable rule. Separate knowledge-base integrity errors, decision
   process errors, and forecast resolution or calibration errors.
8. Label lesson state as `candidate`, `corroborated`, `validated`, or `retired`.
   Record evidence origin separately as `historical_replay`,
   `historical_holdout`, or `live_forward`.
9. Promote a lesson only after independent contrary-case review and out-of-sample
   evidence appropriate to its scope and regime. Dispatch the registered
   independent review role; its authenticated review principal must call the
   `promote_lesson` MCP tool. There is no direct CLI promotion path, and a
   caller-supplied role is not reviewer authentication. Historical replay
   evidence alone cannot become holdout or live-forward validation.

## Boundaries

- Do not treat LLM confidence, graph connectivity, retrieval frequency, or a
  profitable outcome as proof that a claim is true.
- Do not erase superseded claims or failed cases. Link replacements while
  preserving the earlier record and its decision-time context.
- Do not merge historical replay, historical holdout, and live forward metrics
  into one score.
- Do not silently change a strategy, skill, prompt, role, policy, approval,
  broker, or execution setting. Produce a reviewable change proposal instead.
- Do not draft, approve, or execute an order from memory evidence alone.

Return the relevant artifact paths, the applicable strategy snapshot, the
strongest supporting and contrary episodes, lesson status, evidence tier, and
the next validation needed.
