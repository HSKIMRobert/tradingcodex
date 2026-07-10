# Decision Memory

This document owns TradingCodex's durable design for learning from investment
decisions without turning past outcomes into hidden rules. It covers historical
replay, live forward review, postmortems, lesson promotion, strategy binding,
workspace investor context, and the user-facing skill model.

The short version is:

> The ledger is the memory. Wiki pages, graphs, dashboards, and summaries are
> rebuildable views over it.

Decision Memory is an evidence and judgment subsystem. It does not authorize a
recommendation, order, approval, execution, broker action, policy change, or
automatic self-modification.

## Product Model

Keep four concepts separate:

| Concept | Question it answers | Durable posture |
| --- | --- | --- |
| Skill | What procedure should run now? | A concise Codex procedure subject to the kernel and role boundaries. |
| Strategy | By which user-approved rules should judgment be formed? | A standalone `strategy-*` skill whose content hash is frozen for each run. |
| Decision Memory | What was known, decided, predicted, observed, and later learned? | Append-only or immutable workspace artifacts with point-in-time provenance. |
| Investor Context | Which workspace-local suitability facts and constraints should apply? | An optional, user-confirmed Markdown file with an explicit application toggle. |

They work together but are not interchangeable. A strategy is not evidence, a
memory is not a rule, investor context is not an account, and a skill grants no
authority.

## Canonical Architecture

```text
raw source snapshots
        |
immutable ResearchSpec + replay manifest
        |
frozen decision package + forecast events
        |
separately observed outcome + proper score
        |
two-pass postmortem
        |
lesson candidate
        |
independent cases + holdout + live forward validation
        |
corroborated or validated lesson
        |
Wiki / temporal graph / search / calibration views
```

### Canonical records

The source of truth is the existing file-native record:

- content-addressed source snapshots;
- immutable ResearchSpecs and replay manifests;
- experiment runs that bind code, data, config, model, prompt, tool, and trial
  provenance;
- planned Decision Packages, immutable accepted decision snapshots, and
  accepted role artifacts;
- append-only forecast issue, revision, resolution, dispute, and score events;
- audit-backed postmortems and append-only improve records; and
- strategy and investor-context hashes bound into the workflow that used them.

Existing events are not edited to make history look cleaner. Corrections,
revisions, supersession, disputes, and retirement are new records.

### Time contract

Decision Memory needs more than a document `updated_at`. Records should
preserve the applicable time fields already used by source snapshots:

- `valid_at` or `effective_at`: when the fact applied in the world;
- `published_at`: when a source published it;
- `known_at`: when it became knowable to the workflow;
- `recorded_at`: when TradingCodex stored it; and
- `knowledge_cutoff`: the latest knowable time allowed for the decision.

A replay rejects evidence whose `known_at` is later than its cutoff. Later
restatements, revised macro releases, adjusted prices, delisted securities, and
changed index membership must not leak backward into the original decision.

### Claim and argument view

A useful investment relationship is not merely an entity edge. When claim-level
memory is introduced, the smallest durable record should express:

```text
claim
  statement
  type: fact | hypothesis | causal_hypothesis | procedure
  supports / attacks / qualifies / depends_on / supersedes
  evidence and counterevidence refs
  assumptions and warrant
  scope and regime
  valid_at / known_at
  status: active | contested | superseded | retired
  provenance
```

This is a logical projection over canonical artifacts, not a reason to install
a graph database. A graph arrow does not establish causality, and provenance
does not establish truth.

### Wiki and graph posture

LLM-maintained Markdown is useful for navigation, synthesis, and progressive
disclosure. It is unsuitable as the only investment memory because free-form
pages do not reliably preserve observation time, contradicted claims, abandoned
hypotheses, trial counts, forecast calibration, or outcome-blind process
reviews.

TradingCodex may therefore generate:

- issuer, theme, supply-chain, and strategy pages;
- temporal claim and counterclaim views;
- similar-decision episode lists;
- forecast and calibration dashboards; and
- stale, contradicted, unsupported, or orphaned-record diagnostics.

Every view must link to canonical artifact ids and hashes and remain safely
rebuildable. A view may not silently become the belief store.

## Memory Types

The architecture separates fast episode capture from slow generalization:

| Memory type | TradingCodex representation | Update speed |
| --- | --- | --- |
| Working | Current run context and compact role briefs | Temporary |
| Episodic | One frozen decision, replay, outcome, and postmortem | Fast, append-only |
| Semantic | Corroborated claims and lessons across independent episodes | Slow, reviewed |
| Procedural | Strategies, skills, prompts, policies, and tests | Deliberate user or maintainer change only |

One postmortem may create an episodic record immediately. It must not become a
semantic rule or procedural change immediately.

## Historical Replay And Forward Evidence

Historical data is required for rapid learning, but it is not equivalent to
live evidence.

### Walk-forward sequence

```text
training/history window
  -> freeze cutoff and knowable snapshots
  -> issue decision and forecast
  -> reveal next period
  -> resolve, score, and review
  -> propose lesson candidate
  -> test in an untouched later window
  -> test in live forward operation
```

Use chronological walk-forward or expanding windows. Random train/test splits
are generally inappropriate for market chronology and regime change.

### Evidence origin

Record evidence origin independently of lesson status:

- `historical_replay`: an episode reconstructed from an allowed historical
  window;
- `historical_holdout`: an untouched later historical window; and
- `live_forward`: a decision frozen before the real-world outcome.

Never collapse these into one win rate or performance score. A lesson can be
historically corroborated without being live-forward validated.

### Leakage and overfit controls

Historical replay must preserve or explicitly flag:

- point-in-time universe membership and delistings;
- first-release financial and macro data vintages;
- corporate actions and adjusted versus unadjusted price policy;
- source publication, retrieval, and known-at chronology;
- benchmark, trading costs, slippage, capacity, and liquidity;
- every generated, tried, discarded, or revised hypothesis and parameter set;
- prompt, model, tool, code, data, and configuration hashes;
- repeated exposure to the same holdout window; and
- shared upstream sources or model errors that make cases correlated rather
  than independent.

Recent data is not automatically relevant data. Regime, valuation, liquidity,
positioning, market structure, and applicable causal assumptions matter more
than an arbitrary recent-month cutoff.

## Current-Decision Use

Past cases can improve retrieval while also anchoring the next decision. For a
new decision-quality workflow, use this order:

```text
independent initial view
  -> freeze the view and probability
  -> retrieve relevant prior cases and lessons
  -> compare support, conflict, and regime fit
  -> keep or revise the view with an explicit delta
```

Direct lookup requests such as "show the last three decisions" do not need an
artificial blind view. The blind-first rule applies when memory can influence a
new judgment.

Multi-agent agreement is not independent evidence when agents share the same
source, retrieval result, prompt lineage, or model failure. Record common
upstream provenance and preserve independent priors where the workflow requires
them.

## Postmortem Contract

Postmortems cover successful and failed decisions, thesis changes, blocked or
revised artifacts, rejected actions, stale evidence, forecast misses, routing
failures, and paper executions. Reviewing only failures creates another form of
selection bias.

### Two-pass review

1. Build a frozen process packet from decision-time artifacts.
2. Hide outcome and P&L where possible.
3. Assess evidence quality, alternatives, base rate, assumptions, forecast,
   invalidation conditions, role handoffs, and process discipline.
4. Lock the process review.
5. Reveal the outcome, benchmark, drawdown, and forecast score.
6. Assess outcome quality and calibration separately.
7. Generate several candidate explanations with supporting, contrary, and
   alternative explanations.
8. Emit lesson candidates and validation work, not automatic rules.

A good process can have a bad outcome, and a poor process can have a profitable
outcome. Outcome knowledge must not rewrite what was reasonably knowable.

The skill seals accepted decision-time state with `./tcx decision snapshot
record`, locks the outcome-blind first pass with `./tcx postmortem
process-review`, and only then creates the outcome-attached report with `./tcx
postmortem create`. These commands accept a JSON payload file or `-` for stdin;
they validate recorded workflow, artifact, forecast, strategy, and
investor-context hashes instead of trusting free-form Markdown. Lesson
promotion has no direct or generic CLI path: an authenticated
`judgment-reviewer` performs it through the role-scoped `promote_lesson` MCP
tool.

### Separate error loops

Do not combine every failure into one Error Book:

| Error domain | Examples | Appropriate response |
| --- | --- | --- |
| Knowledge-base integrity | Dangling link, unsupported summary, stale page, bad extraction | Rebuild or repair the read projection. |
| Decision process | Missed contrary evidence, hidden assumption, wrong method, routing or source-trust failure | Record an episode and judgment improvement. |
| Forecast resolution and calibration | Bad resolution source, disputed outcome, overconfidence, poor probability calibration | Correct through forecast events and scoring. |

A knowledge-base repair is not evidence that an investment hypothesis improved.

## Lesson Lifecycle

Use a small lifecycle:

```text
candidate -> corroborated -> validated -> retired
```

- `candidate`: proposed by one or more episodes, with scope and contrary cases
  still open.
- `corroborated`: repeated across genuinely independent evidence, with obvious
  alternatives and duplicate cases removed.
- `validated`: passed its declared out-of-sample requirement. The evidence
  origin still states whether validation is historical holdout or live forward.
- `retired`: no longer reliable, superseded, or outside its valid regime. Keep
  the record and reason.

Promotion requires:

- explicit scope, horizon, universe, and regime;
- supporting and contrary episode references;
- source and model provenance;
- independence or correlation assessment;
- a declared validation plan and threshold;
- no unreported reuse of the holdout; and
- independent review when decision impact is material.

Confidence is not a free-form LLM number. Keep empirical forecast probability,
evidence quality, uncertainty, decision utility, and realized P&L separate.
Use proper scores and calibration only when the eligible sample is large enough
under the existing forecast contract.

## Strategy Relationship

Strategy remains a separate user-approved procedure.

Every applicable workflow records:

- selected strategy name, or `no_strategy`;
- strategy status and content hash;
- the exact protected snapshot used by the run; and
- the selector that made the choice.

Native Codex intake recognizes a strategy only through one exact explicit
`$strategy-*` invocation. A prompt that merely names or describes a strategy
does not select it, and no invocation records `no_strategy`. Workbench uses its
structured strategy selector instead. Both paths validate that the selected
managed strategy is active and valid, then seal its source bytes under the
run-owned workflow directory and bind the snapshot path and hash.

Later strategy edits never rewrite an earlier decision or replay. A postmortem
or lesson may propose a strategy diff, but the proposal must show the old rule,
new rule, reason, scope, supporting and contrary cases, and validation status.
The active strategy changes only after user review and approval.

Strategy results remain separated by historical replay, historical holdout, and
live forward evidence. Do not market a strategy using one blended success rate.

## Workspace Investor Context

Investor suitability context is not a selectable product profile. Workspaces
already provide the user-facing boundary, while the runtime retains an internal
paper account scope for portfolio, order, broker, and currency isolation.

### File contract

The optional file is created only after user confirmation:

```text
.tradingcodex/user/investor-context.md
```

Its YAML frontmatter uses schema version 1 and stores:

- `enabled_by_default`;
- updated time and actor;
- investment objective;
- time horizon;
- risk tolerance and loss capacity;
- liquidity needs;
- current holdings and concentration not already represented by canonical
  portfolio state; and
- tax, account, or jurisdiction constraints.

The Markdown body may contain concise user-confirmed notes. It must not contain
broker credentials, account numbers, tax identifiers, tokens, passwords,
private keys, seed phrases, or unnecessary personal financial detail.

### Interview and application

The user invokes the investor-context skill to interview, show, update, enable,
disable, or clear the file. Ask only missing or changed questions in small
batches and preview durable changes before writing.

- `enable` or `disable` changes the workspace default.
- Native Codex intake follows that saved workspace default. When enabled, it
  seals the applied file under the run-owned workflow directory and binds its
  snapshot path and hash.
- Workbench alone offers an explicit one-run apply/ignore control. That override
  is sealed into the run without changing the saved default. Wording a native
  chat request as an override does not mutate an intake already recorded by the
  hook.
- The workflow records whether context was configured and applied plus its
  content hash. It receives compact applicable fields, not the full file.
- General research and historical replay can proceed without personal context.
- Personalized recommendation, portfolio fit, sizing, and order readiness stay
  limited or blocked when required suitability context is disabled or missing.
- Execution receives no suitability narrative.

Legacy `active_profile.investor_profile` values may be read as a compatibility
fallback, but new writes go to the workspace file. The user-facing Profile
concept is removed; internal `portfolio_id`, `account_id`, `strategy_id`, and
base currency remain as paper account scope because execution-sensitive state
still requires deterministic isolation.

## Skill-First UX

Do not add a separate Memory application area initially. Reuse the existing
product surfaces:

| Surface | Decision Memory behavior |
| --- | --- |
| Work | Start a normal memory-focused request for replay, review, retrieval, or validation and show a one-line scope preview before execution. Native Codex app users may invoke `$decision-memory` explicitly. |
| Skills | Expose Decision Memory, Strategy Creator, and Investor Context as distinct outcomes. Hide the legacy Postmortem entry from the default list while preserving compatibility. |
| Library | Browse source-backed research artifacts. The Decision Memory skill lists sealed decisions and reviews through their workspace commands and returns their paths. |
| System | Show workspace and internal paper account posture without presenting a separate investor Profile product. |

Default result disclosure should be compact:

1. What was known
2. Decision or forecast
3. What happened
4. Lesson and validation status

Source chronology, strategy/context hashes, claim links, calibration detail,
and replay manifests belong behind progressive disclosure.

Example requests:

- "Replay this NVDA thesis as of 2020-01-01 without future data."
- "Why did the previous decision fail, and was the process still reasonable?"
- "Find similar rate-shock decisions and include contrary cases."
- "Has this lesson survived a historical holdout or live forward test?"
- "Interview me for this workspace's investor context, then leave it disabled."

## Evaluation Contract

The architecture is useful only if it improves out-of-sample judgment without
increasing leakage, confirmation bias, or source laundering.

Compare at least:

1. current file search baseline;
2. vector retrieval baseline;
3. generated Markdown Wiki retrieval; and
4. episode plus claim/argument retrieval.

Use frozen paired cases and measure:

- point-in-time leakage and invalid source admission;
- relevant and contrary episode retrieval;
- unsupported claim and source-laundering rate;
- forecast Brier/log score, calibration, and resolution;
- historical-holdout and live-forward performance separately;
- process-review quality under outcome blinding;
- strategy/context snapshot reproducibility;
- abstention and missing-evidence behavior;
- latency, context tokens, compilation cost, and maintenance effort; and
- clean-host, populated-host, same-name skill collision, and explicit skill
  invocation behavior.

Do not claim that Decision Memory improves investment returns until populated,
time-separated, independently reviewed evidence supports that statement.

## Non-Goals

The initial implementation does not require:

- a graph database, RDF stack, or comprehensive ontology;
- an editable Wiki as the canonical memory;
- a whole-market Bayesian network or causal graph;
- model-weight editing or automatic fine-tuning;
- automatic prompt, skill, strategy, policy, approval, or execution changes;
- a new frontend state framework, production Node runtime, or Memory tab;
- storing research memory in Django models; or
- combining replay, holdout, live forward, evidence quality, forecast accuracy,
  and P&L into one confidence score.

Add a richer graph or dedicated UI only after a measured retrieval or usability
gap survives the simpler file-native design.

## Research Basis

The design is informed by complementary fast episodic and slow semantic
learning, case-based reasoning, event sourcing and bitemporal data, provenance,
argument representation, proper scoring rules, postmortem/debrief research, and
financial data-snooping controls. Useful starting references include:

- McClelland, McNaughton, and O'Reilly,
  [Complementary Learning Systems](https://web.stanford.edu/~jlmcc/papers/McCMcNaughtonOReilly95.pdf)
- Aamodt and Plaza,
  [Case-Based Reasoning](https://doi.org/10.3233/AIC-1994-7104)
- W3C, [PROV-O](https://www.w3.org/TR/prov-o/)
- Clark et al.,
  [Micropublications](https://pubmed.ncbi.nlm.nih.gov/26261718/)
- Tannenbaum and Cerasoli,
  [Do Team and Individual Debriefs Enhance Performance?](https://pubmed.ncbi.nlm.nih.gov/23516804/)
- Baron and Hershey,
  [Outcome Bias in Decision Evaluation](https://pubmed.ncbi.nlm.nih.gov/3367280/)
- Gneiting and Raftery,
  [Strictly Proper Scoring Rules](https://sites.stat.washington.edu/people/raftery/Research/PDF/Gneiting2007jasa.pdf)
- White,
  [A Reality Check for Data Snooping](https://doi.org/10.1111/1468-0262.00152)
- Bailey et al.,
  [The Probability of Backtest Overfitting](https://escholarship.org/uc/item/4w1110bb)
- Edge et al., [GraphRAG](https://arxiv.org/abs/2404.16130)
- Tencent AI Lab, [Retrieval as Reasoning: LLM-Wiki](https://arxiv.org/abs/2605.25480)

These sources motivate components of the architecture. They do not establish
that the combined TradingCodex system improves investment performance; that
claim remains an empirical product evaluation question.
