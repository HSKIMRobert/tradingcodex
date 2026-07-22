---
name: tcx-artifact
description: "Prepare, persist, and repair TradingCodex research artifacts and forecast records when a role must hand off run-bound evidence through MCP tools."
---

# Persist An Artifact

Use the authoritative MCP schema for `create_research_artifact`,
`append_research_artifact_version`, or `issue_forecast`. Never approximate a
tool name or write ledger state directly.

If a named tool is deferred, use one names-only exact-name lookup, then inspect
the selected exact name's schema once. Never print full tool records, scan
descriptions, or repeat a schema lookup.

## Shared artifact quality floor

This skill is the canonical owner of the shared artifact quality floor. Role
skills add only domain-specific checks.

- Answer the exact assigned question and distinguish attributable facts,
  analysis, and assumptions in natural prose where the distinction matters.
- Preserve source/as-of posture, conflicts, uncertainty, confidence, missing
  evidence, next owner/action, blocked actions, and explicit handoff state.
- Use authenticated IDs and service receipts/hashes. Never fabricate evidence,
  fields, identity, paths, times, or readiness to satisfy validation.
- Use `accepted` only when the artifact is ready for Head Manager review;
  otherwise use `revise`, `blocked`, or `waiting` truthfully.

## Write once, then return the receipt

1. Record source snapshots before citing them and use only returned IDs.
2. Pass the assigned `workflow_run_id`; every exact consumed Artifact, Dataset,
   and Snapshot ID in `input_artifact_ids`, `dataset_ids`, and
   `source_snapshot_ids`; and any conclusion-relevant current-run Calculation
   ID. The service derives lineage hashes.
3. Include Markdown, non-empty conservative `readiness_label`, source/as-of
   posture, `context_summary`, `reader_summary`, confidence, missing evidence,
   next action, blocked actions, and explicit handoff state.
4. Keep optional gates truthful and apply the shared quality floor.
5. On terminal success, stop and make the final handoff begin with one compact
   receipt line: `ARTIFACT <artifact_id> <path> <handoff_state>`. Copy all three
   values from the authenticated result; never reconstruct them.

For a follow-up append, keep the target `artifact_id` separate from triggering
cross-role `input_artifact_ids`. Authenticate the target and never append to a
triggering artifact. If the target ID is absent, create a new artifact only
when the brief explicitly requests one; otherwise return `waiting`.

When binding source snapshots or Datasets, set the timezone-qualified
`knowledge_cutoff` at or after the maximum snapshot `known_at` and Dataset
`knowledge_cutoff`. Prefer that exact maximum and never guess a future or
date-only cutoff.

`follow_up_requests[].required_inputs` is an array of strings. Use one
lower/upper `probability_range`, such as `[0.3, 0.4]`; put multiple ranges in
`scenario_cases`. Allowed follow-up triggers are `coverage_gap`,
`freshness_gap`, `contradiction`, `material_driver`, `assumption_change`,
`method_gap`, `scope_boundary`, `forecast_gap`, and
`investor_context_gap`. A valuation sensitivity is an improvement type, not a
follow-up trigger.

## Stop unchanged tool loops

- Treat every documented terminal success, including `stored`, `updated`,
  `existing`, `reused`, and `prepared`, as completion. Never repeat the same
  canonical arguments hoping for another status.
- Permit at most two submissions for one artifact write: the initial call and
  one corrected retry. After a deterministic validation, permission, policy,
  or immutable-conflict error, inspect the returned field guidance and target
  if needed before that single retry; never submit unchanged arguments.
- If the corrected retry fails, stop, lower readiness, and return `waiting`
  with the bounded error and owning next action, even if another correction
  seems possible.

## Set thesis state honestly

When decision quality is required:

- `exploring`: state only.
- `testing`: add evidence references or top-level snapshot/evidence IDs.
- `validated`: add evidence run card, validation card, and reviewer acceptance.
- `rejected`: add an invalidation note.
- `monitoring`: add a monitoring artifact or cadence.

## Issue forecasts only after acceptance

Call `issue_forecast` only when the assignment requires a scoreable forecast
and its supporting artifact is accepted. Use timezone-qualified RFC 3339
`horizon` and `knowledge_cutoff`; normally omit `issued_at`. Bind a base-rate
snapshot at or before the cutoff with cohort, sample size, and selection rule.
Match binary, categorical, or continuous payload fields to `target_type`. If
the evidence cannot support that contract, set `forecast_allowed: false` and a
precise block reason instead of issuing a forecast.
