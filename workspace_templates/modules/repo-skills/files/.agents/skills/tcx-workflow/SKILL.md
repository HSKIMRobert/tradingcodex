---
name: tcx-workflow
description: Coordinate TradingCodex operate-plane investment workflows by turning hook intake hints into validated staged workflow plans, dispatching fixed-role subagents from the recorded plan, evaluating artifacts, and synthesizing only after accepted role outputs.
---

# TCX Workflow

Use this skill when a user asks for investment analysis, decision support, portfolio/risk review, order drafting, approval review, or non-live execution status.

## Procedure

1. Read hook intake from `.tradingcodex/mainagent/latest-workflow-intake.json` or the hook `intake_path`. Treat `heuristic_lane`, `heuristic_roles`, and `deterministic_hint` as suggestions only.
2. Draft a staged workflow plan before dispatch. Compile it as a strict subset of the intake `routing_envelope`; preserve its `intake_hash`, `routing_envelope_hash`, `plan_hash`, lane, roles, blocked actions, and task/supervisor budgets.
3. Each stage must include `stage_id`, `roles`, `depends_on`, `dispatch_mode`, `purpose`, and `exit_criteria`. Use only fixed TradingCodex roles.
4. Validate the plan with `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} workflow validate --plan <path|->`. Fix validation errors instead of dispatching around them.
5. Record the validated plan with `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} workflow record --plan <path|->`. The recorded plan is the run contract; hooks do not choose the final team.
6. Dispatch or reuse only roles in the next ready recorded stage. Pass compact immutable assignment envelopes: original request, constraints, `workflow_run_id`, `plan_hash`, `stage_id`, `task_id`, accepted input paths/hashes, expected artifact type, `context_summary`, and blocked actions.
7. Use the Artifact Supervisor Loop after artifact intake: evaluate artifacts, then choose `revise_same_role`, `follow_up_existing_team`, `challenge_conflict`, `downstream_handoff`, `lane_escalation_proposal`, `blocked`, `waiting`, or `synthesize`.
8. Use `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} subagents loop --run <workflow_run_id> --artifact <path>` to preview closed planner actions from artifacts when helpful. Queue means a compact pending task and delta brief; hooks do not recursively spawn subagents.
9. Treat `SubagentStop` only as process completion. Release dependencies only after the Artifact Gate accepts a run/plan/stage/task/content-hash-bound artifact; each recorded supervisor evaluation consumes one separate supervisor round.
10. Require the Decision Quality Spine fields described in `references/decision-quality-spine.md` when they are in scope.
11. Select a bundled method profile appropriate to the question and instrument: `general_evidence_v1`, `event_research_v1`, `quant_signal_v1`, or `listed_equity_fcff_dcf_v1`. Put it in the ResearchSpec or compact role brief when applicable; report a support gap rather than forcing quant or FCFF fields onto an incompatible task.
12. Use bundled TradingCodex capabilities as the pristine baseline. Treat host-global or plugin skills as explicit user-selected extensions only, and record any selected workspace strategy or optional skill as overlay provenance.
13. Synthesize only accepted artifacts. When synthesis is allowed, save the full synthesis through `create_research_artifact` using the synthesis report path and `artifact_type=synthesis_report` supplied by the starter prompt, then keep the chat reply brief: report path, 1-3 key takeaways, and next allowed action; stop with `waiting`, `revise`, `blocked`, or `lane_escalation_proposal` when quality gates fail.

## Hard Stops

- Do not produce substantive investment analysis before required role outputs exist.
- Do not dispatch before a validated workflow plan is recorded.
- Do not treat hook hints as binding final workflow decisions.
- Do not widen the recorded staged plan without a new user request or validated plan revision.
- Do not treat artifact-proposed lane scope or consent as authoritative; recompute those from routing policy.
- Do not create approval or execution artifacts from natural language alone.
- Do not change TradingCodex build mode, policy, MCP allowlists, or broker execution posture while producing investment judgment.
- Do not implicitly apply host-global or plugin skills, or count them as proof of pristine TradingCodex quality.
- Do not treat one bundled method profile as a universal investment-analysis template.
