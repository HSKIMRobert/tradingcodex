# Investment Decision Quality PRD

Status: draft  
Owner surface: Harness Improvement, role workflow quality, generated workspace templates  
Related docs: `harness.md`, `roles-skills-and-workflows.md`, `research-memory-and-artifacts.md`, `validation-and-test-plan.md`, `generated-workspaces.md`

## Problem

TradingCodex already has strong safety boundaries, fixed-role dispatch, artifact
handoffs, source posture, and approval/execution gates. It is weaker at turning
rough user intent into consistently excellent investment research, forecasting,
and decision support.

Users often begin with vague prompts: look at a ticker, ask whether something
is cheap, ask whether to buy, ask for chart-only review, ask what would change
a thesis, ask whether an idea fits a portfolio, or ask whether a backtest is
usable. The harness must infer the smallest decision-useful workflow lane,
preserve explicit constraints, route to the right role team, require
forecast-quality outputs only when appropriate, and stop with conservative
readiness when evidence is weak.

The solution must improve decision quality without creating a monolithic stock
analysis workflow and without weakening role, MCP, approval, execution, broker,
or secret boundaries.

## Goals

- Make vague investment prompts reliably trigger the correct TradingCodex
  workflow.
- Preserve explicit constraints and negations before applying quality defaults.
- Add a reusable Decision Quality Spine across investment lanes.
- Improve scenario reasoning, probabilistic forecasting discipline, data quality
  checks, and anti-overfit validation.
- Make role artifacts more decision-ready without forcing unsupported precision.
- Add enforceable artifact/readiness validation instead of relying only on
  prompt text.
- Keep generated workspace context compact and file-native.
- Keep durable product language English and language-neutral; broader user input
  requires a reviewed localization or alias layer first.
- Record scoreable forecasts in a file-native ledger so future calibration and
  postmortems can review what was predicted, when, and why.

## Non-Goals

- No monolithic "super analysis" workflow.
- No head-manager direct investment analysis before accepted role artifacts.
- No widening of selected-team binding after routing.
- No weakening of negated-scope handling.
- No order, approval, execution, broker, raw API, or secret authority added to
  decision-quality skills.
- No new execution-sensitive MCP allowlist grants.
- No raw broker secret storage or secret inspection.
- No Node, npm, React, frontend build step, or unrelated runtime dependency.
- No language-specific product docs, prompts, UI copy, durable examples,
  aliases, or tests outside a reviewed localization layer.
- No requirement to compute Brier scores before enough forecasts have resolved.

## Research Basis

This PRD follows a practical evidence posture rather than assuming a larger
prompt alone improves investment judgment.

- Retrieval and source-grounded reasoning reduce memory-only hallucination:
  [RAG](https://arxiv.org/abs/2005.11401),
  [Self-RAG](https://arxiv.org/abs/2310.11511), and
  [ReAct](https://arxiv.org/abs/2210.03629).
- Finance-specific language models and financial agents support domain-aware
  workflows, but still require evidence, tools, and evaluation:
  [FinGPT](https://arxiv.org/abs/2306.06031),
  [BloombergGPT](https://arxiv.org/abs/2303.17564), and
  [FinRobot](https://arxiv.org/abs/2405.14767).
- Financial statement and factor lenses should draw from established research,
  while avoiding data-mined certainty:
  [Piotroski F-score](https://www.jstor.org/stable/2672906),
  [Fama-French five-factor model](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2287202),
  [Jegadeesh-Titman momentum](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.1993.tb04702.x),
  and [Harvey-Liu-Zhu](https://academic.oup.com/rfs/article/29/1/5/1843824).
- Forecasting quality improves when probabilities are horizon-bound,
  updateable, and scored:
  [Brier score](https://journals.ametsoc.org/view/journals/mwre/78/1/1520-0493_1950_078_0001_vofeit_2_0_co_2.xml)
  and [superforecasting research](https://journals.sagepub.com/doi/abs/10.1177/1745691615577794).
- Official read-only data sources should be preferred where possible:
  [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces),
  [FRED API](https://fred.stlouisfed.org/docs/api/fred/), and
  [BEA API](https://www.bea.gov/resources/for-developers).

## Decision Quality Spine

The Decision Quality Spine is a cross-lane quality contract, not a new lane.
It is applied only within the selected lane and selected role team.

```text
user prompt
-> intent normalization
-> universe, lane, constraints, and negations
-> evidence pack and source posture
-> role-separated analysis
-> scenario tree when thesis or valuation is in scope
-> forecast contract when prediction or decision support is in scope
-> challenge review and contradiction log
-> portfolio/risk gate only when requested or implied by decision support
-> synthesis with readiness label, conflicts, missing evidence, and blocked actions
```

### Spine Rules

- Explicit user constraints win over defaults.
- Negated scope removes roles/actions before positive intent is applied.
- The selected team remains binding.
- Broad public-equity prompts use the smallest decision-useful lane, not the
  smallest possible lane.
- Research-only prompts do not add valuation, portfolio, risk, order, approval,
  or execution.
- Broad public-equity ticker/security review defaults to deep thesis review
  with fundamental, technical, news, and valuation roles unless explicit
  constraints narrow scope.
- Thesis/earnings/catalyst review may include valuation unless valuation is
  explicitly negated.
- Decision support routes through valuation, portfolio-manager, and
  risk-manager; order, approval, and execution remain blocked.
- Technical-only prompts stay narrow unless the user explicitly asks for broader
  research or decision support.
- Backtest, signal, and strategy-validation prompts route to validation review,
  not strategy authoring, unless the user asks to create or edit a strategy.
- Synthesis consumes only accepted artifacts and preserves disagreements.
- Weak support returns `waiting`, `revise`, or `blocked`.

## Intent Normalization

### Requirements

Add a small intent-normalization layer in `tradingcodex_service/application/harness.py`.
The layer should produce normalized intent flags used by routing:

- `vague_analysis`
- `broad_thesis_default`
- `factual_profile_only`
- `technical_only`
- `valuation_requested`
- `valuation_negated`
- `news_negated`
- `forecast_requested`
- `forecast_negated`
- `forecast_horizon`
- `decision_support_requested`
- `portfolio_risk_requested`
- `order_negated`
- `trading_negated`
- `approval_execution_requested`
- `backtest_or_signal_validation_requested`
- `strategy_authoring_requested`
- `connector_or_build_requested`

Use a data structure or helper functions, not scattered one-off regex literals.
Do not add language-specific aliases in core routing; add a reviewed
localization layer first if broader input support is needed.

### Routing Semantics

| Intent | Lane | Required role posture |
| --- | --- | --- |
| Vague public-equity ticker/security review | `thesis_review` with `deep_thesis_default` | Fundamental, technical, news, and valuation by default; explicit constraints may narrow scope. |
| Vague non-equity instrument review | Universe-appropriate non-execution review | Use existing universe role defaults. Add valuation/scenario only when the instrument has a supportable valuation lens, the user requests it, or decision support is implied. Never infer execution support from review coverage. |
| Factual/company profile only | `research_only` | Evidence pack only; no valuation or decision language. |
| Technical-only | `research_only` | Technical analyst only, plus instrument analyst when instrument mechanics are essential. |
| Thesis, earnings, catalyst, expectation bar | `thesis_review` | Research roles plus valuation unless valuation is negated. |
| Cheap/expensive/fair value/target | `thesis_review` | Valuation required; portfolio/risk only if decision support or fit is requested. |
| Buy/sell/recommend/add/size/fit | `thesis_review_then_portfolio_risk_review` | Valuation, portfolio, and risk required; order/approval/execution blocked. |
| Portfolio fit, concentration, exposure, drawdown | `portfolio_risk_review` | Portfolio and risk required, plus only relevant evidence roles. |
| Draft order | `order_ticket_draft_gate` | Existing draft prerequisites apply; approval/execution blocked. |
| Approved action | `order_ticket_approval_execution_gate` | Existing approved action path applies; natural-language orders blocked. |
| Backtest/signal validation | Nearest existing non-execution lane with `anti_overfit_required=true` | Anti-overfit validation required; no execution implication. |
| Strategy create/update | `head_manager_strategy_authoring` | Strategy-creator path; no ticker analysis unless separately requested. |
| Connector/build | Existing connector lanes | No investment dispatch. |

### Default Depth Policy

TradingCodex distinguishes the smallest possible lane from the smallest
decision-useful lane.

For broad public-equity prompts such as "Analyze NVDA" or "look at AAPL", the
default decision-useful lane is a deep thesis review: fundamental, technical,
news, and valuation. This default does not
grant portfolio advice, order drafting, approval, execution, broker access, or
secret access.

Explicit constraints narrow the default before role selection:

- "chart only" selects technical-only review.
- "no valuation" removes valuation.
- "no news" removes news review.
- "no order" and "no trading" preserve blocked actions.
- "company facts only" or similar factual-profile language stays
  research-only.

### Deep Thesis Default Is Not A Lane

`deep_thesis_default` is a routing depth flag, not a new workflow lane. It
modifies `thesis_review` role selection for broad public-equity analysis by
including fundamental, technical, news, and valuation roles by default.

It does not grant portfolio advice, order drafting, approval, execution,
broker access, or secret access.

### Intent Conflict Resolution Order

Resolve intent in this order:

1. Secret-only, connector/build, and strategy-authoring separation.
2. Explicit negations and narrowing constraints.
3. Universe detection.
4. Decision-support, portfolio/risk, order, approval, and execution intent.
5. Broad public-equity deep thesis default.
6. Quality flags such as `forecast_contract_required`,
   `profile_gate_required`, and `anti_overfit_required`.

Negations narrow roles or actions; they do not erase the remaining analytical
request. For example, "Should I buy TSLA? no order" remains decision support,
but order-ticket drafting stays blocked.

### Signal Validation Phase 1 Decision

Do not add a first-class `signal_validation` lane in Phase 1. Route backtest,
signal, and model-performance validation to the nearest existing non-execution
lane with `anti_overfit_required=true`.

Backtest/signal validation is not strategy creation. Strategy creation and
update remain in `strategy-creator`. Validation reviews evidence quality,
implementation friction, and overfit risk only; it must not create or activate
`strategy-*` skills unless the user explicitly asks to create or update a
strategy.

A first-class lane may be added later if repeated workflows show that
flag-based routing is insufficient.

## Shared Skill Bundles

Create shared subagent skill bundles under:

```text
workspace_templates/modules/repo-skills/files/.tradingcodex/subagents/skills/shared/
```

Each bundle includes:

```text
<skill-name>/
  SKILL.md
  agents/openai.yaml
  references/*.md  # optional, for longer methodology
  scripts/*        # optional, for deterministic checks or reusable helpers
  assets/*         # optional, for reusable non-context resources
  <other-purpose-built-dir>/*  # optional, when SKILL.md explains its use
```

### `forecasting-discipline`

Purpose: require predictions to be horizon-bound, probability-aware,
evidence-aware, and updateable.

Required coverage:

- forecast horizon
- base rate or missing-base-rate note
- `forecast_required` vs `forecast_allowed`
- forecast block reason when probability should not be produced
- scenario probabilities, probability range, or explicit `not-decision-ready`
- confidence and uncertainty drivers
- update triggers
- invalidation conditions
- resolution source and review date
- factual data vs model output vs assumption vs judgment
- no false precision when evidence is weak

Suggested roles:

- fundamental-analyst
- technical-analyst
- news-analyst
- macro-analyst
- instrument-analyst
- valuation-analyst
- portfolio-manager and risk-manager when decision support or sizing is in scope

For portfolio-manager and risk-manager, `forecasting-discipline` is used to
check forecast readiness, profile fit, sizing implications, and blocked
conditions. It must not turn these roles into issuer forecasters or valuation
analysts.

### Forecast Permission

Forecasts are required only when prediction, valuation implication, scenario
probability, or decision support is in scope. A required forecast is not always
allowed.

Artifacts must distinguish:

- `forecast_required`
- `forecast_allowed`
- `forecast_block_reason`
- `forecast_target`
- `forecast_horizon`
- `probability`
- `probability_range`
- `base_rate`
- `evidence_ids`
- `contrary_evidence`
- `resolution_source`
- `review_date`

When evidence is too weak, the correct output is `forecast_allowed=false`,
`not-decision-ready`, `revise`, or `blocked`, not a precise probability.

If `forecast_required=true` but the role lacks current price, base rate, source
freshness, or a resolvable target, then `forecast_allowed=false` and the
artifact must include `forecast_block_reason`.

If `forecast_negated=true`, roles may still provide scenarios and qualitative
update triggers, but they must not create probability fields or forecast ledger
records unless the user later asks for forecasts.

Use either:

- `probability` for a single calibrated probability, or
- `probability_range` when precision is intentionally coarse.

If both are present, `probability` must fall inside `probability_range`. When
evidence is weak, prefer `probability_range` or `forecast_allowed=false`.

### Forecast Ledger

Forecasts must be represented in both artifact summaries and an append-only
file-native ledger.

- Artifact frontmatter/body: compact handoff fields for synthesis.
- `trading/forecasts/*.jsonl`: scoreable forecast records for later review.

The ledger is file-native and local-first. Initial implementation validates
schema and open/closed status only. Brier scoring and calibration review are
future enhancements after forecasts have resolution data.

Role artifacts may propose forecast records, but the workflow should write or
validate ledger records through the shared research/artifact service path where
possible. Head-manager must not invent forecast records without accepted role artifacts.

Example `trading/forecasts/forecast-ledger.jsonl` record:

```json
{
  "forecast_id": "fcst_20260629_nvda_001",
  "workflow_run_id": "workflow-20260629T000000Z",
  "artifact_id": "valuation_nvda_20260629",
  "role": "valuation-analyst",
  "instrument": "NVDA",
  "forecast_target": "NVDA total return exceeds SPY total return by at least 10 percentage points",
  "horizon": "2026-12-31",
  "probability": 0.35,
  "probability_range": "30-40%",
  "base_rate": {
    "value": 0.22,
    "source": "artifact or source_snapshot id"
  },
  "evidence_ids": ["source_snapshot_1", "artifact_fundamental_1"],
  "contrary_evidence": ["valuation already embeds high growth"],
  "invalidation_conditions": ["gross margin guide-down", "multiple compression"],
  "resolution_source": "total_return_dataset",
  "review_date": "2026-12-31",
  "status": "open"
}
```

When `forecast_allowed=true`, a forecast ledger record must include a
resolvable `forecast_target`, `horizon`, `probability` or
`probability_range`, `evidence_ids`, `contrary_evidence`,
`resolution_source`, `review_date`, and `status`.

### `thesis-scenario-tree`

Purpose: convert vague theses into bull/base/bear or alternative-hypothesis
scenario trees.

Required coverage:

- consensus expectation or expectation bar
- variant perception
- bull/base/bear cases
- key discriminants
- what would change the view
- contrary evidence
- unresolved conflicts

Suggested roles:

- fundamental-analyst
- news-analyst
- macro-analyst
- instrument-analyst
- valuation-analyst

### `numeric-data-qc`

Purpose: prevent stale, inconsistent, or fabricated numbers from driving
financial reasoning.

Required coverage:

- source date and retrieval date
- period alignment
- units, currency, share count, and per-share consistency
- source vs derived vs assumption labels
- current price or market anchor as-of checks
- formula sanity checks
- stale or missing data readiness downgrade

Suggested roles:

- fundamental-analyst
- technical-analyst
- macro-analyst
- valuation-analyst
- portfolio-manager
- risk-manager

### `anti-overfit-validation`

Purpose: keep technical, strategy, backtest, and signal requests from becoming
implementation fantasy.

Required coverage:

- look-ahead leakage
- survivorship bias
- data snooping and multiple testing
- walk-forward or out-of-sample requirement
- transaction costs, slippage, borrow/funding, taxes where relevant
- liquidity and capacity constraints
- regime sensitivity
- signal decay
- paper alpha vs live implementation friction

Suggested roles:

- technical-analyst
- valuation-analyst when expected-return or model-validation claims appear
- portfolio-manager and risk-manager when implementation readiness is in scope

## Existing Skill Upgrades

Update these skill bodies conservatively and move long methods to references:

- shared `collect-evidence`
- `fundamental-analysis`
- `technical-analysis`
- `news-analysis`
- `macro-analysis`
- `instrument-analysis`
- `valuation-review`
- `portfolio-review`
- `review-risk`

Each affected skill should expect this artifact quality shape when applicable:

- `evidence_grade`
- `source_freshness`
- `source_quality`
- `conflict_status`
- `decision_readiness`
- `confidence`
- `missing_evidence`
- `forecast_required`
- `forecast_allowed`
- `forecast_block_reason`
- `forecast_target`
- `forecast_horizon`
- `probability`
- `probability_range`
- `base_rate`
- `evidence_ids`
- `contrary_evidence`
- `resolution_source`
- `review_date`
- `update_triggers`
- `invalidation_conditions`

The shape is an artifact expectation, not role identity. Role authority, MCP
allowlists, approval authority, execution authority, and durable safety
boundaries remain in the registry, TOML, policy, service layer, and generated
instructions.

## Registry And Projection

Update `tradingcodex_service/application/agents.py`:

- Add `SkillSpec` entries for new shared skills.
- Add the new skills to the appropriate `AGENT_SPECS[*].builtin_skills`.
- Preserve current MCP allowlists.
- Preserve risk tags so validation blocks unsafe assignment.
- Update tests that assert the built-in skill count.
- Verify `ROLE_SKILL_MAP`, generated role TOML `skills.config`, skill index,
  and projection manifest include the new skills.

Do not rely on `SkillSpec` alone. Effective skill projection is derived from
`AGENT_SPECS.builtin_skills`, applied proposals, and active optional skills.

Because built-in skill projection is role-static, scope-specific quality skills
may be assigned to a role by default but invoked only when workflow flags
require them. Skill availability is not authority and does not widen role,
MCP, approval, execution, broker, or secret boundaries.

## Workflow Skill Upgrade

Rewrite `tcx-workflow` as a compact orchestration procedure. It should require:

- read latest hook context or latest prompt gate when compact context is not
  enough
- treat lane, selected team, and blocked actions as binding
- convert vague prompts into the smallest decision-useful lane, not the
  smallest possible lane
- respect explicit constraints and negations before defaults
- dispatch or reuse selected fixed-role subagents before substantive analysis
- require Decision Quality Spine fields from role artifacts
- synthesize only accepted artifacts
- preserve disagreements and unresolved conflicts
- stop with `waiting`, `revise`, or `blocked` when quality gates fail
- never create order, approval, or execution artifacts from natural language
  alone

If needed, add:

```text
workspace_templates/modules/repo-skills/files/.agents/skills/tcx-workflow/references/decision-quality-spine.md
```

Keep the main skill body short.

## Starter Prompt And Compact Context

Update `build_subagent_starter_prompt` and compact dispatch context to carry
Decision Quality Spine requirements without bloating hooks.

Starter prompts should include:

- compact Decision Quality Spine requirement
- artifact path requirement
- `reader_summary`
- `context_summary`
- `handoff_state`
- source/as-of posture
- `evidence_grade`
- `decision_readiness`
- `confidence`
- `missing_evidence`
- forecast fields when applicable
- `next_recipient`
- `blocked_actions`

Compact hook context may include booleans such as:

- `decision_quality_required`
- `forecast_contract_required`
- `profile_gate_required`
- `anti_overfit_required`

Do not paste full methods, source lists, role manuals, or long references into
hook `additionalContext`.

## Artifact Validation

Add enforceable validation instead of prompt-only expectations.

Options:

- Add a small lane-aware helper, such as
  `evaluate_decision_quality(workspace_root, artifact_path, workflow_lane,
  strict=True)`.
- Call the helper from existing strict quality-check paths or generated
  workspace smoke tests where workflow lane is known.
- Add schema-like tests for generated artifacts without requiring live data.
- Include `trading/forecasts` in the safe/expected quality-check file roots
  before validating forecast ledger files.

Do not add a new user-facing CLI mode in the first implementation. Add a
separate CLI surface later only if internal checks are useful enough to expose.

Minimum strict checks:

- Decision-support artifacts either include forecast horizon, forecast
  permission, probability/probability range, update triggers, and resolution
  source, or mark forecast as `not-decision-ready` with
  `forecast_block_reason`.
- Forecast ledger records with `forecast_allowed=true` include a resolvable
  target, horizon, evidence IDs, contrary evidence, resolution source, review
  date, and open/closed status.
- If both `probability` and `probability_range` are present, the single
  probability falls inside the stated range.
- If `forecast_negated=true`, no probability fields or forecast ledger records
  are created.
- Valuation artifacts include current price/market anchor source-as-of or mark
  valuation as `not-decision-ready`.
- Technical/backtest artifacts mention anti-overfit validation when backtest,
  signal, or model-performance claims are in scope.
- Portfolio/risk artifacts name investor-profile gaps when recommendation,
  sizing, or portfolio fit is requested.
- Accepted thesis or decision artifacts cannot omit scenario, contrary
  evidence, update trigger, invalidation, and forecast permission fields.
- `revise` and `blocked` artifacts name missing evidence or blocked actions.

## Tests

Add or update tests for:

- vague English prompts
- negated scope
- technical-only scope
- valuation vs decision-support routing
- portfolio/risk profile gaps
- backtest/signal validation routing
- strategy authoring vs strategy validation separation
- generated skill bundle metadata
- `SkillSpec`, `AGENT_SPECS.builtin_skills`, `ROLE_SKILL_MAP`, and projection
- no new broker, approval, execution, raw API, or secret access
- compact hook context budget
- generated workspace skill index and projection manifest

Acceptance expectations:

- Vague public-equity symbol analysis routes to deep thesis review by default.
- "Analyze NVDA." routes to `thesis_review` with `deep_thesis_default` and
  includes fundamental, technical, news, and valuation roles.
- "Analyze NVDA. No valuation." removes valuation but preserves the remaining
  broad thesis roles.
- "Analyze NVDA. Company facts only." routes to `research_only`.
- Vague non-equity analysis triggers the current universe-appropriate
  investment workflow.
- Technical-only prompts keep the role team narrow.
- Valuation negation removes valuation.
- Decision-support prompts route through valuation, portfolio, and risk while
  blocking order, approval, and execution.
- Order negation blocks order-ticket drafting.
- Backtest/signal prompts require anti-overfit validation.
- Strategy authoring remains separate from strategy validation.
- Decision-support artifacts produce either valid forecast ledger records or
  explicit forecast block reasons.
- No path grants raw broker API, approval, execution, or secret access.

## Docs To Update With Implementation

Update these docs in the same implementation change:

- `docs/harness.md`
- `docs/components.md`
- `docs/roles-skills-and-workflows.md`
- `docs/research-memory-and-artifacts.md`
- `docs/generated-workspaces.md`
- `docs/validation-and-test-plan.md`
- `docs/README.md`

Document:

- Decision Quality Spine
- new shared skills
- intent-normalization boundary
- forecast artifact contract
- anti-overfit validation behavior
- vague prompt routing behavior
- negated-scope priority
- why this remains cross-lane quality infrastructure instead of a monolithic
  workflow

## Validation Plan

Run focused checks first:

```bash
python -m pytest tests/test_python_migration.py tests/test_e2e_user_scenarios.py
```

Then broader repository validation:

```bash
python -m pytest
python manage.py check
python -m compileall tradingcodex_cli tradingcodex_service apps tests
```

Then generated workspace smoke:

```bash
rm -rf /tmp/tradingcodex-harness-smoke
python -m tradingcodex_cli attach /tmp/tradingcodex-harness-smoke
cd /tmp/tradingcodex-harness-smoke
./tcx doctor
./tcx doctor --layer codex-native
./tcx doctor --layer improvement
./tcx subagents status
./tcx skills list --all
./tcx subagents prompt "Analyze NVDA. No order, no trading, no valuation."
./tcx subagents prompt "Analyze NVDA."
```

Also call the generated hook with representative vague, technical-only,
decision-support, and strategy-validation prompts.

When Codex CLI is available, run a native smoke that confirms:

- head-manager instructions loaded
- selected team is correct
- negated scope is respected
- no substantive investment analysis appears before subagent artifacts
- output stops at dispatch/waiting when subagent dispatch cannot be verified

## Rollout Plan

### Phase 1: Routing Foundation

- Add intent-normalization helpers.
- Add routing tests.
- Preserve existing connector/build/secret-wall behavior.
- Add strategy-validation vs strategy-authoring separation.

### Phase 2: Skill And Projection Upgrade

- Add shared skill bundles.
- Update `SkillSpec` and `AGENT_SPECS.builtin_skills`.
- Update generated workspace projection tests.
- Update role TOML generated expectations through existing projection paths.

### Phase 3: Artifact Contract

- Add Decision Quality Spine artifact fields to role skill expectations.
- Add append-only `trading/forecasts/*.jsonl` forecast records.
- Add strict validation helpers/tests.
- Keep context summaries compact.

### Phase 4: Docs And Smoke

- Update docs listed above.
- Run repository validation.
- Run generated workspace smoke.
- Run Codex-native smoke when available.

## Success Metrics

Immediate success:

- Listed vague and decision-support prompts route to expected lanes and teams.
- Broad public-equity analysis defaults to deep thesis review unless explicitly
  narrowed.
- `research_only` never self-expands into valuation, portfolio, risk, order,
  approval, or execution.
- Decision-support lanes expose investor-profile gaps and forecast readiness.
- Backtest/signal requests produce anti-overfit requirements.
- Decision-support artifacts create valid forecast ledger records or explicit
  `forecast_block_reason`.
- Malformed forecast records fail schema validation.
- Accepted decision artifacts cannot omit scenario, contrary evidence, update,
  invalidation, and forecast permission fields.
- Generated workspace skill index and projection manifest include new shared
  skills.
- Strict artifact validation fails malformed decision-quality artifacts.
- Hook compact context stays within existing context-budget expectations.
- No new execution-sensitive tool is exposed to head-manager or research roles.

Future success:

- Resolved forecasts can be scored with Brier score.
- Calibration by confidence bucket can be reviewed.
- Postmortems can compare forecast quality across roles and workflows.

## Open Decisions

- Whether the forecast ledger should be one workspace-wide JSONL file or
  sharded by workflow/run under `trading/forecasts/`.
- Whether a first-class `signal_validation` lane is needed after Phase 1
  telemetry shows the flag-based route is insufficient.
- Whether decision-quality checks should become a user-facing CLI mode after
  internal strict validation proves useful.
