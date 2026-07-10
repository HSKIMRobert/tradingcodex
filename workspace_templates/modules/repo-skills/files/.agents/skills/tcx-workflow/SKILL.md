---
name: tcx-workflow
description: Coordinate TradingCodex operate-plane investment workflows by selecting the smallest sufficient fixed-role team from recorded intake candidates, recording the server-compiled plan, evaluating artifacts, and synthesizing only after accepted role outputs.
---

# TCX Workflow

Use this skill when a user asks for investment analysis, decision support, portfolio/risk review, order drafting, approval review, or non-live execution status.

## Procedure

1. Read hook intake from `.tradingcodex/mainagent/latest-workflow-intake.json` or the hook `intake_path`. Its integrity-bound `deterministic_hint` fixes the lane, candidate-role ceiling, blocked-action floor, and quality requirements.
2. Choose the smallest sufficient subset of candidate roles. Preserve every required judgment, portfolio/risk, valuation, or execution role reported by validation. Roles outside the candidates require a new intake or lane-escalation proposal.
3. Submit only `workflow_run_id`, `selected_roles`, optional `schema_version: 1`, and optional `planner_rationale` to `record_workflow_plan`. The server builds the stage DAG and owns constraints, quality and artifact requirements, budgets, stop condition, routing envelope, and hashes. Fix validation errors instead of dispatching around them. When MCP is unavailable, use `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} workflow validate --plan <path|->` followed by `workflow record`.
4. Treat the recorded plan as the run contract and dispatch or reuse only roles in the next ready recorded stage. Pass compact immutable assignment envelopes: original request, constraints, `workflow_run_id`, `plan_hash`, `stage_id`, `task_id`, accepted input paths/hashes, expected artifact type, `context_summary`, and blocked actions.
5. Run the Artifact Supervisor Loop after each artifact intake by calling `record_artifact_supervisor_loop` with the recorded `workflow_run_id` and exact artifact paths. Follow its closed result: `revise_same_role`, `follow_up_existing_team`, `challenge_conflict`, `downstream_handoff`, `lane_escalation_proposal`, `blocked`, `waiting`, or `synthesize`.
6. Outside restricted web runs, `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} subagents loop --run <workflow_run_id> --artifact <path>` may preview the same closed planner actions. Queue means a compact pending task and delta brief; hooks do not recursively spawn subagents.
7. Treat `SubagentStop` only as process completion. Release dependencies only after the Artifact Gate accepts a run/plan/stage/task/content-hash-bound artifact; each recorded supervisor evaluation consumes one separate supervisor round.
8. Require the Decision Quality Spine fields described in `references/decision-quality-spine.md` when they are in scope.
9. Select a bundled method profile appropriate to the question and instrument: `general_evidence_v1`, `event_research_v1`, `quant_signal_v1`, or `listed_equity_fcff_dcf_v1`. Put it in the ResearchSpec or compact role brief when applicable; report a support gap rather than forcing quant or FCFF fields onto an incompatible task.
10. Use bundled TradingCodex capabilities as the pristine baseline. Treat host-global or plugin skills as explicit user-selected extensions only, and record any selected workspace strategy or optional skill as overlay provenance.
11. Synthesize only accepted artifacts. When synthesis is allowed, save the full synthesis through `create_research_artifact` using the synthesis report path and `artifact_type=synthesis_report` supplied by the starter prompt, then keep the chat reply brief: report path, 1-3 key takeaways, and next allowed action; stop with `waiting`, `revise`, `blocked`, or `lane_escalation_proposal` when quality gates fail.

## Hard Stops

- Do not produce substantive investment analysis before required role outputs exist.
- Do not dispatch before a validated workflow plan is recorded.
- Do not dispatch from raw hook context; submit the team-selection draft for server compilation and validation first.
- Do not widen the recorded staged plan without a new user request or validated plan revision.
- Do not treat artifact-proposed lane scope or consent as authoritative; recompute those from routing policy.
- Do not create approval or execution artifacts from natural language alone.
- Do not change TradingCodex build mode, policy, MCP allowlists, or broker execution posture while producing investment judgment.
- Do not implicitly apply host-global or plugin skills, or count them as proof of pristine TradingCodex quality.
- Do not treat one bundled method profile as a universal investment-analysis template.
