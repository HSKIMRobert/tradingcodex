---
name: tcx-evidence
description: "Collect source-backed investment evidence at the start of analyst workflows. Use for research intake, source lists, fact versus assumption separation, and missing-evidence tracking before analysis."
---

# Collect Evidence

Build the smallest evidence pack that can answer the assigned question.

1. Identify the universe and workflow type. Use only relevant, callable source
   classes; mark missing universe support or unavailable routes as gaps.
2. Apply `tcx-source-gate` before external retrieval and retain its returned
   source IDs and gaps.
3. Distinguish observations, source or management claims, analysis, and
   assumptions in natural prose where ambiguity matters. Prefer opened primary filings, releases,
   and exchange/regulator records over snippets, secondary news, stale data,
   or unsupported assumptions.
4. State the identifier, source list, source-trust notes, market context,
   missing evidence, freshness, decision readiness, confidence, update
   triggers, invalidation conditions, and contrary evidence that matter.
5. Apply the shared artifact quality floor and persist the pack under
   `trading/research/` only through authenticated MCP.

Carry Snapshot, Dataset, and Artifact IDs plus a compact card into calculation
or handoff context. Do not summarize away used Dataset rows or repeat an
unchanged source call.

For `record_source_snapshot`, omit caller-owned `snapshot_id`, `retrieved_at`,
and `recorded_at`. Supply `known_at` only when an exact timezone-aware knowable
time is genuinely supported; never repair validation with a guessed time.
When an artifact cites returned `source_snapshot_ids`, set `knowledge_cutoff`
to a timezone-qualified RFC 3339 time at or after the maximum service-returned
snapshot `known_at`, preferably that exact maximum. Never use end-of-day or another future time, and never send a date-only value. If no exact bound is
available, omit the optional cutoff; if no snapshot exists, use `[]`.

Use `factual-baseline`, `screen-grade`, or `not-decision-ready` when gaps limit
downstream use. Include high/medium/low confidence with one reason. An
`accepted` artifact must pass service quality; correct a rejected payload
instead of weakening its handoff. Use `follow_up_requests=[]` when none apply;
otherwise provide structured objects with `trigger`, `suggested_role`,
`question`, `reason`, and `materiality`.
