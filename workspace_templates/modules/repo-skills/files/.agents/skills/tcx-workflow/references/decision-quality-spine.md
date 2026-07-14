# Decision Quality Spine

Use this spine as a quality floor inside Head Manager's dynamic workflow. It is
not a lane, plan, DAG, role roster, or service state machine.

1. Preserve the current mandate, explicit constraints, negations, and blocked
   actions.
2. Select a question- and instrument-appropriate bundled method profile.
   General and event research do not inherit quant-only fields; FCFF DCF
   applies only when its listed-equity driver contract fits.
3. Require authenticated role-owned artifacts with source/as-of posture,
   `reader_summary`, `context_summary`, `handoff_state`, `evidence_grade`,
   `decision_readiness`, `confidence`, `missing_evidence`, `next_recipient`, and
   `blocked_actions` as applicable.
4. For thesis, valuation, portfolio-fit, or risk scope, preserve scenarios,
   contrary evidence, update triggers, invalidation conditions, source-trust
   notes, and unresolved conflicts.
5. For prediction, valuation implication, scenario probability, or decision
   support, require forecast permission fields and either a valid forecast
   record or `forecast_block_reason`.
6. For backtest, signal, or model-performance scope, require anti-overfit
   validation, including leakage, repeated trials, costs, capacity, and
   out-of-sample posture.
7. For recommendation, sizing, or portfolio-fit scope, keep suitability gaps
   visible until Investor Context supports the judgment.
8. Use an independent `judgment-reviewer` for recommendations, material
   conflicts, or high-consequence uncertainty. Shared sources, prompt lineage,
   or model failures do not become independent evidence merely because several
   agents agree.
9. Preserve exact run-local input artifact IDs and hashes. Treat producer
   `accepted`, `revise`, `blocked`, and `waiting` as handoff evidence, not
   service-owned orchestration state.
10. Synthesize only supported artifacts. Return `waiting`, `revise`, or
    `blocked` when evidence is weak.

Quality activation is an explicit artifact contract, not server routing. Set
`forecast_required: true` for prediction or forecast judgment,
`decision_quality_required: true` for thesis, recommendation, or material
decision review, `investor_context_gate_required: true` when suitability or
portfolio fit depends on user context, and `anti_overfit_required: true` plus
complete structured `anti_overfit_checks` for backtest, signal, or
model-performance claims. Pass the applicable fields in the role assignment and
preserve them in synthesis. Never infer a gate from `workflow_type`, a server
lane, artifact body keywords, or the language of the request.

The Core floor cannot be weakened by Strategy, Investment Brain, optional
skill, additional instruction, host-global skill, plugin, or Decision Memory.
Authenticated current evidence controls factual claims. A Brain may change
which hypotheses are tested and how evidence is interpreted, but it cannot
lower provenance, point-in-time, uncertainty, falsifier, forecast, independent
challenge, suitability, policy, approval, execution, or audit requirements.

Forecast ledger records live under `trading/forecasts/*.jsonl` and remain
append-only. Do not issue them without the required authenticated evidence.

Judgment-review fields make conclusions challengeable. They never create
order, approval, execution, broker, policy, workflow, or model-training
authority.
