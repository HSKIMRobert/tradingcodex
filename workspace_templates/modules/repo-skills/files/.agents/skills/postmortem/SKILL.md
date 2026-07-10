---
name: postmortem
description: "Create a TradingCodex postmortem after executed orders, rejected orders, thesis changes, or process failures. Use for audit review and improve records."
---

# Postmortem

Use this skill after thesis changes, rejected orders, executed paper orders, or process failures.

When a frozen pre-outcome decision packet exists, evaluate the decision process
without P&L or outcome first and lock that review before evaluating the outcome.
Keep a good process with a bad outcome distinct from a bad process with a good
outcome. Review successful and failed episodes; do not train memory only on
failures.

Expected output:

- A locked outcome-blind process review named
  `trading/reports/postmortem/<id>.process-review.json`
- A structured JSON postmortem report named `trading/reports/postmortem/<id>.postmortem_report.json`
- `id`, `created_by`, `created_at`, and `trigger`
- `findings` entries covering what was intended, what happened, artifacts used, guardrails fired, changed assumptions, root cause, and process improvement
- `investment_judgment_review` covering original thesis, what happened,
  failed assumption, role evidence miss or overstatement, stale or misleading
  source, confidence calibration, and future warning pattern
- `next_actions`, including the next allowed review or blocked state
- `lesson_candidates` with supporting and contrary episode references, stated
  scope/regime, and the next historical-holdout or live-forward test
- Universe/instrument support gap if the process failed because the requested asset class, instrument, adapter, source, or workflow was not installed

Quality floor:

- Apply the shared artifact quality floor.
- Tag material narrative claims as `[factual]`, `[inference]`, or `[assumption]`.
- Use a short timeline.
- Separate root cause, contributing factors, and symptoms.
- Separate knowledge-base integrity errors, decision-process errors, and
  forecast resolution or calibration errors.
- Preserve improve records separately from execution, approval, or policy
  outcomes.
- State whether the failure was user-input, analysis, policy, approval, execution, or harness related.
- State whether the failure was universe-support, source-readiness, hero/support artifact, or readiness-label related.
- Do not fabricate audit events, artifacts, command output, approvals, executions, or timestamps.
- Do not promote one episode directly into a reusable rule or silently update a
  strategy, skill, prompt, policy, approval, broker, or execution setting.
- End with one or more concrete investment-judgment improvements.

Write outputs under `trading/reports/postmortem/` through the service; do not
write around it. Before any outcome is recorded or revealed, lock the first
pass with `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} postmortem process-review
<payload.json|->`. Only afterward resolve the outcome and create the sealed
second-pass report with `{{TRADINGCODEX_WORKSPACE_LAUNCHER}} postmortem create
<payload.json|->`, binding its `process_review_id`.

Lesson promotion is separate from report creation. Dispatch the registered
independent review role; only its authenticated review principal may call the
`promote_lesson` MCP tool. Direct `postmortem promote-lesson` CLI promotion is
unavailable.

Postmortem is a skill, not a subagent role.
