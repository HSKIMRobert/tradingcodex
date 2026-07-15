# Context And Override Contract

Use these typed layers when analysis applies an Investment Brain, Strategy,
Investor Context, Decision Memory, or conflicting current evidence. Do not
collapse them into one flat priority list.

| Layer | Owns | Never owns |
| --- | --- | --- |
| TradingCodex Core | provenance, point-in-time discipline, roles, tools, policy, approval, execution, audit, run integrity | investment doctrine |
| Current user mandate | outcome, scope, prohibitions, explicit overlay choices | safety or execution bypass |
| Investor Context | horizon, liquidity, loss capacity, concentration, suitability constraints | doctrine or factual claims |
| Strategy | explicit eligibility, entry/exit, sizing, and risk decision rules | roles, factual authority, or safety override |
| Investment Brain | hypotheses, inquiry priorities, causal frames, scenarios, falsifiers, interpretation, abstention | roles, tools, workflow, persistence, memory, policy, execution |
| Method skills | bounded analytical procedures | mandate, suitability, or action authority |
| Current-run evidence | authenticated facts, source/as-of posture, conflicts, uncertainty | approval or execution |
| Decision Memory | prior decisions, forecasts, outcomes, postmortems, validated lessons | automatic override, Brain mutation, publication |

## Selection And Sealing

- Select at most one Primary Brain through one exact explicit
  `$investment-brain-*` id, either as a plain token or a Markdown link whose
  label and target match the projected workspace skill. Deduplicate repeated
  references to the same id and reject distinct multiple ids. Apply the same
  rule to `$strategy-*` selection. Never infer selection from prose or
  resemblance.
- Let `begin_analysis_run` resolve the active validated TradingCodex plugin and
  seal `investment_brain_binding.brain_id`, `version`, `content_digest`,
  `source`, `manifest_path`, `source_file`, and `projected_skill_path`.
- Use the pristine TradingCodex baseline when no Brain is selected.
- Stop before analysis when more than one Brain is invoked or a selected Brain
  is unresolved, inactive, invalid, or unavailable in the task context.
- Keep one Brain and one Strategy immutable for a run. Start a new run to
  change either; never blend doctrines by editing sealed provenance.
- Use only service-derived artifact lineage:
  `investment_brain_id`, `investment_brain_version`, and
  `investment_brain_content_digest`.

## Brain Application

Apply a Brain with high freedom inside its domain heuristics. Use it to decide
which hypotheses deserve attention, what causal links to test, which evidence
would change the view, how to form scenarios and falsifiers, and when to
abstain.

Keep platform translation with Head Manager. Translate Brain questions into
the smallest useful fixed-role assignments based on current needs. Do not let a
Brain name roles, dispatch agents, prescribe task order or parallelism, call
tools, select models or sandbox, set artifact paths, read secrets, retrieve or
modify memory, or grant policy, approval, broker, order, or execution authority.
Send a child the derived domain question and run binding, not the Brain body.

## Resolve Conflicts

| Conflict | Required response |
| --- | --- |
| Brain or Strategy vs Core | Keep the Core boundary and reject the conflicting instruction. |
| User mandate vs Core safety | Keep safety blocking and explain the boundary. |
| Strategy vs Investor Context | Keep suitability blocked until the user explicitly resolves the mismatch. |
| Brain vs Strategy | Apply the Strategy's decision rule; use the Brain only to explain or challenge it. |
| Brain or Strategy vs current evidence | Let evidence control factual claims; preserve and disclose the conflict. |
| Decision Memory vs current evidence | Compare chronology, common provenance, and regime fit; preserve both. |
| Brain vs Decision Memory | Treat memory as support or counterexample, never an automatic Brain update. |
| Mid-run Brain or Strategy change | Start a new analysis run. |

Do not let a later-listed layer win merely because it is more specific. Resolve
the type of authority involved: safety by Core, task scope by mandate,
suitability by Investor Context, explicit decision rules by Strategy, inquiry
heuristics by Brain, facts by authenticated evidence, and historical comparison
by non-authoritative memory.

## Use Memory Blind-First

When prior cases may influence a new judgment:

```text
independent current evidence view
  -> preserve the view and probability
  -> retrieve relevant Decision Memory
  -> compare chronology, common provenance, regime fit, support, and conflict
  -> keep or revise with an explicit delta
```

Do not create an artificial blind step for a direct request to list, search, or
replay memory. Multi-agent agreement is not independent evidence when agents
share sources, retrieval, prompt lineage, or model failure.

## Synthesize Transparently

State which Brain was bound and how it materially changed inquiry or
interpretation. Expose conflicts among Brain, Strategy, evidence, and memory.
When memory was consulted, retain the pre-memory view and state the post-memory
delta. Preserve uncertainty and abstention; do not manufacture agreement to
make an overlay appear useful.
