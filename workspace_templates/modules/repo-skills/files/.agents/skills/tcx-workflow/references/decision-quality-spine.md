# Decision Quality Spine

The spine is a cross-lane quality contract, not a workflow lane.

Apply it inside the selected lane and selected team only:

1. Preserve explicit user constraints and negations.
2. Use the selected universe, lane, blocked actions, and quality flags from workflow intake or the recorded workflow plan.
3. Select a question- and instrument-appropriate bundled method profile. General evidence and event research do not inherit quant-only trial fields; FCFF DCF applies only when its listed-equity driver contract fits.
4. Require artifact paths, `reader_summary`, `context_summary`, `handoff_state`, source/as-of posture, `evidence_grade`, `decision_readiness`, `confidence`, `missing_evidence`, `next_recipient`, and `blocked_actions`.
5. For thesis, valuation, portfolio-fit, or risk-review scope, require scenario cases, contrary evidence, update triggers, invalidation conditions, source trust notes, and unresolved conflicts.
6. For prediction, valuation implication, scenario probability, or decision support, require forecast permission fields and either a valid forecast record or `forecast_block_reason`.
7. For backtest, signal, or model-performance scope, require anti-overfit validation.
8. For recommendation, sizing, or portfolio-fit scope, keep investor-context gaps visible until answered.
9. Synthesize only accepted artifacts and return `waiting`, `revise`, or `blocked` when support is weak.

The core floor applies before customization: evidence provenance, point-in-time
correctness, uncertainty, falsifiers, source freshness, forecast discipline,
independent challenge, and safety gates cannot be weakened by a strategy,
optional skill, additional instruction, host-global skill, or plugin.

Artifact handoff states are `accepted`, `revise`, `blocked`, and `waiting`.
They are not terminal workflow actions. Terminal workflow actions are
`synthesize`, `blocked`, `waiting`, or `lane_escalation_proposal`.

Artifacts may include `follow_up_requests` with `trigger`, `suggested_role`,
`question`, `reason`, `materiality`, source artifact provenance, advisory
`suggested_consent_posture`, and blocked actions. Subagents propose these
requests only. Head-manager recalculates lane scope and consent from
`allowed_followup_team`, `escalation_team`, and `loop_policy` before creating
any delta follow-up brief.

Forecast ledger records live under `trading/forecasts/*.jsonl` and are
append-only. Do not create them without accepted role artifacts.

Judgment-review fields make investment conclusions challengeable. They do not
create order, approval, execution, broker, policy, or model-training authority.
