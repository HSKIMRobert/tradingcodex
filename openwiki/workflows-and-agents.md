# Workflows And Agents

Use this page before changing `head-manager`, fixed subagents, skills, hooks, routing, handoff quality, optional skills, strategies, or generated role instructions. Human-facing rules live in [docs/roles-skills-and-workflows.md](../docs/roles-skills-and-workflows.md), [docs/harness.md](../docs/harness.md), and [docs/artifact-supervisor-loop-prd.md](../docs/artifact-supervisor-loop-prd.md).

## Fixed Team

TradingCodex uses one root `head-manager` plus ten fixed subagents, including an independent `judgment-reviewer` gate.

| Role | Owns | Never allowed |
| --- | --- | --- |
| `head-manager` | intake, staged workflow plan, dispatch, artifact acceptance, synthesis, validation/audit status | final investment conclusion without accepted role artifacts, raw broker APIs |
| `fundamental-analyst` | business, statements, filings, economics, fundamental risks | orders, approval, execution, secrets |
| `technical-analyst` | price action, trend, momentum, volume, volatility, liquidity setup | orders, execution, standalone investment conclusion |
| `news-analyst` | verified news, disclosures, event chronology, narrative change | unverified rumor claims, execution |
| `macro-analyst` | macro, rates, FX, commodities, liquidity, policy transmission | orders, execution |
| `instrument-analyst` | ETF/index, options, crypto public market structure, instrument mechanics | unsupported execution claims |
| `valuation-analyst` | valuation ranges, scenarios, sensitivity, decision-quality gaps | approval, execution |
| `portfolio-manager` | portfolio fit, sizing, concentration, draft order-ticket readiness | self-approval, execution |
| `risk-manager` | downside, restricted list, policy readiness, approval readiness | order drafting, execution |
| `judgment-reviewer` | independent challenge, source trust, blind prior/review, forecast resolution, blinded model review | production analysis, approval, execution |
| `execution-operator` | approved submit/cancel/status through TradingCodex service boundary | raw broker APIs, secrets, policy change |

## Routing Contract

Natural-language investment requests activate workflow routing. `head-manager` should draft, validate, record, and dispatch from a staged plan before substantive investment analysis. If dispatch is unavailable or role routing is unverified, the workflow waits.

Negated scope is binding. `no order`, `no trading`, and `no valuation` remove those actions or roles from the plan. Broad public-equity prompts such as `Analyze NVDA` default to thesis review unless the user narrows scope first. Narrow fact-only and technical-only prompts stay on the selected producer roles without `judgment-reviewer` unless broader judgment is requested.

Execution-only approved-action lanes use ticket, approval, policy, duplicate-request, connection, and audit gates. They do not dispatch `judgment-reviewer` unless the prompt first routes through research or decision support.

Key files:

- `tradingcodex_service/application/workflow_planner.py`
- `workspace_templates/modules/codex-base/files/.codex/hooks/tradingcodex_hook.py`
- `workspace_templates/modules/codex-base/files/.codex/prompts/base_instructions/head-manager.md`
- `workspace_templates/modules/repo-skills/files/.agents/skills/tcx-workflow/SKILL.md`

## Handoff Contract

Role artifacts should include artifact path, original request, binding constraints, source/as-of or retrieved-at posture, claim discipline, confidence, uncertainty, missing evidence, readiness label, next recipient, blocked actions, and handoff state. After accepted artifacts exist, `head-manager` should save a full synthesis report under `trading/reports/head-manager/` and keep the chat reply brief with the report path and next allowed action; brief chat handoff must not make the saved research report shallow.

Handoff states:

- `accepted`: can move downstream.
- `revise`: stayed in bounds but needs more work before downstream use.
- `blocked`: policy, boundary, stale data, unsupported instrument, or user scope blocks downstream action.
- `waiting`: required upstream role output does not exist yet.

Downstream roles consume accepted upstream artifacts. They do not repair missing upstream analysis outside their own question.

Artifacts may also carry `improvements`. Recorded loop previews and postmortem
review can write `improve` records to `.tradingcodex/mainagent/improve.jsonl`;
`.tradingcodex/mainagent/improve-index.json` keeps compact counts, recent
summaries, and dedupe ids so future runs do not reread the whole ledger. These
records are reusable investment judgment context only and do not apply prompt,
skill, policy, MCP, broker, approval, or execution changes.

## Skill And Projection Boundaries

Keep product capability layers explicit:

| Layer | Workflow meaning |
| --- | --- |
| Core kernel | Quality, evidence, handoff, policy, approval, execution, audit, and provenance requirements that customization cannot replace. |
| Bundled investment capability pack | Fixed roles and built-in investment skills that provide the pristine research, analysis, and forecast baseline. |
| Managed user overlays | Additional instructions, optional role skills, and `strategy-*` skills that add user methods while remaining subject to the kernel. |

Head-manager and strategy skills live under `.agents/skills/*`. Role-owned subagent skills live under `.tradingcodex/subagents/skills/*`. Fixed subagent TOML projects only that role's allowed skill source list.
It does not include root or strategy skill files as disabled subagent entries.

`tradingcodex_service/application/agents.py` owns role metadata, built-in skills, permission profiles, MCP allowlists, forbidden skill tags, and projection behavior. Skill bodies should describe procedures, not grant durable role authority.

Shared subagent quality skills include `forecasting-discipline`,
`thesis-scenario-tree`, `numeric-data-qc`, and `anti-overfit-validation`.
`agent-judgment-review` is role-owned by `judgment-reviewer` so the challenge
gate is independent from producing analysts and downstream reviewers. These are
review procedures, not role authority.

Codex may still discover metadata for globally installed or plugin-provided
host skills. Those capabilities are outside the pristine TradingCodex baseline
and require explicit user opt-in for the current workflow or managed activation
before a workflow relies on them. Role-local projection reduces accidental mixing but is not proof of
hard runtime isolation; require clean-host, populated-host, name-collision, and
invocation smokes before making that claim.

Default user-visible root skills:

- `plan-workflow`
- `tcx-workflow`
- `automate-workflow`
- `tcx-server`
- `tcx-build`
- `strategy-creator`
- `postmortem`

## Method And Evaluation Profiles

Bundled method profiles keep the workflow matched to the investment question:

- `general_evidence_v1`: source-aware evidence synthesis
- `event_research_v1`: event chronology and causal impact analysis
- `quant_signal_v1`: signal generation and validation with costs, leakage, and
  overfitting controls
- `listed_equity_fcff_dcf_v1`: listed-equity FCFF valuation with explicit
  revenue, margin, reinvestment, risk, and sensitivity assumptions

`core_investment_v1` is the bundled pristine evaluation profile. A frozen
corpus may declare additional profiles with its own required tags and
dimensions. A profile makes the method and comparison contract explicit; it is
not proof of investment quality until populated frozen inputs, paired runs,
hard-failure checks, blind review, resolved forecast outcomes, and trusted-runner
provenance support it. Current caller-attested evaluation digests are unverified
and force `hold`. Customized runs retain the same kernel gates so overlays can
be compared with, not substituted for, the pristine baseline.

## Runtime Model Policy

Generated workspaces actively project GPT-5.6 by role: Sol/high for the
head-manager and judgment-heavy roles, Terra/high for routine evidence roles,
and Luna/low for the bounded execution operator. The registry owns these
selectors and MCP allowlists; skills cannot select models or expand authority.
`.tradingcodex/generated/model-policy-manifest.json` records the resolved model,
capability/support posture, prompt/tool revisions, and GPT-5.5 fallback for each
role. `TRADINGCODEX_MODEL_ROLLOUT=rollback` regenerates the whole roster on the
GPT-5.5 control without changing any policy or execution gate.

## Edit Checklist

When changing this area, keep these aligned:

- human docs in `docs/harness.md`, `docs/roles-skills-and-workflows.md`, and related pages
- component registry in `tradingcodex_service/application/components.py`
- role/skill registry in `tradingcodex_service/application/agents.py`
- generated role TOML in `workspace_templates/modules/fixed-subagents/files/.codex/agents/`
- head-manager prompt and hooks in `workspace_templates/modules/codex-base/files/`
- repo skills in `workspace_templates/modules/repo-skills/files/`
- generated workspace and routing tests
- pristine and customized evaluation-profile coverage, including host-skill
  clean-host, populated-host, name-collision, and invocation smokes when
  isolation behavior changes
