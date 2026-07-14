import { FormEvent, KeyboardEvent, RefObject } from "react";

import {
  activityLabel,
  Artifact,
  asRecord,
  asStringList,
  asText,
  formatDate,
  formatForecastValue,
  normalizeArtifact,
  recordsFrom,
  Run,
  runPhase,
  Skill,
  Strategy,
  TERMINAL_RUN_STATES,
  titleCase,
} from "../domain";
import { EmptyState, ErrorNotice, FieldList, LoadingState, Notice, PageHeader, SectionHeader, StatusPill } from "../ui";

type WorkPageProps = {
  request: string;
  setRequest: (value: string) => void;
  selectedSkillId: string;
  setSelectedSkillId: (value: string) => void;
  skills: Skill[];
  selectedStrategyId: string;
  setSelectedStrategyId: (value: string) => void;
  strategies: Strategy[];
  useInvestorContext: boolean;
  setUseInvestorContext: (value: boolean) => void;
  investorContext: Record<string, unknown>;
  investorContextReady: boolean;
  investorContextError: string;
  preview: Record<string, unknown> | null;
  previewLoading: boolean;
  previewReady: boolean;
  canPreview: boolean;
  canStart: boolean;
  makePreview: () => void;
  startRun: () => void;
  run: Run | null;
  runs: Run[];
  runBusy: boolean;
  workError: string;
  stateLoading: boolean;
  composerRef: RefObject<HTMLTextAreaElement | null>;
  onComposerKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  copyToCodex: () => void;
  copyNotice: string;
  followUp: string;
  setFollowUp: (value: string) => void;
  sendFollowUp: (event: FormEvent) => void;
  newAnalysis: (request?: string) => void;
  openRun: (run: Run) => void;
  refreshRuns: () => void;
  artifactClicked: (id: string) => void;
};

const EXAMPLES = [
  "Compare the bull and bear cases for NVDA over the next 12 months.",
  "What could change the market's current view of this company?",
  "Review this portfolio's biggest evidence gaps. No orders or execution.",
];

export function WorkPage(props: WorkPageProps) {
  const selectedSkill = props.skills.find((skill) => skill.id === props.selectedSkillId);
  const selectedStrategy = props.strategies.find((strategy) => strategy.id === props.selectedStrategyId);
  const hasHistory = props.runs.length > 0;

  return <section className={`page work-page${hasHistory ? " has-history" : ""}`} aria-labelledby="work-title">
    {props.run ? (
      <PageHeader
        eyebrow="Research workspace"
        title={props.run.request || "Selected analysis"}
        titleId="work-title"
        action={<button type="button" className="secondary-button" onClick={() => props.newAnalysis()}>New analysis</button>}
      />
    ) : (
      <PageHeader
        eyebrow="Agent-directed research"
        title="Turn a question into an evidence-backed view."
        titleId="work-title"
        description="Describe the decision or uncertainty. Head Manager chooses the smallest useful specialist team and adapts as evidence arrives."
      />
    )}

    <div className={hasHistory ? "work-layout" : "work-layout work-layout-centered"}>
      {hasHistory && <RunHistory runs={props.runs} selected={props.run} busy={props.runBusy} loading={props.stateLoading} openRun={props.openRun} newAnalysis={() => props.newAnalysis()} refresh={props.refreshRuns} />}
      <div className="work-main">
        {props.workError && <ErrorNotice>{props.workError}</ErrorNotice>}
        {props.investorContextError && <ErrorNotice>{props.investorContextError}</ErrorNotice>}
        {props.run ? (
          <RunWorkspace
            run={props.run}
            busy={props.runBusy}
            copyToCodex={props.copyToCodex}
            copyNotice={props.copyNotice}
            followUp={props.followUp}
            setFollowUp={props.setFollowUp}
            sendFollowUp={props.sendFollowUp}
            rerun={() => props.newAnalysis(props.run?.request)}
            artifactClicked={props.artifactClicked}
          />
        ) : (
          <>
            <ResearchComposer
              request={props.request}
              setRequest={props.setRequest}
              selectedSkillId={props.selectedSkillId}
              setSelectedSkillId={props.setSelectedSkillId}
              skills={props.skills}
              selectedStrategyId={props.selectedStrategyId}
              setSelectedStrategyId={props.setSelectedStrategyId}
              strategies={props.strategies}
              useInvestorContext={props.useInvestorContext}
              setUseInvestorContext={props.setUseInvestorContext}
              investorContext={props.investorContext}
              investorContextReady={props.investorContextReady}
              previewLoading={props.previewLoading}
              previewReady={props.previewReady}
              runBusy={props.runBusy}
              canPreview={props.canPreview}
              canStart={props.canStart}
              makePreview={props.makePreview}
              startRun={props.startRun}
              composerRef={props.composerRef}
              onComposerKeyDown={props.onComposerKeyDown}
            />
            {props.previewLoading && <LoadingState label="Reviewing the request and binding workspace context…" compact />}
            {props.preview && <ScopeReview payload={props.preview} selectedSkill={selectedSkill} selectedStrategy={selectedStrategy} useInvestorContext={props.useInvestorContext} />}
            {!props.preview && <GettingStarted setRequest={props.setRequest} />}
          </>
        )}
      </div>
    </div>
  </section>;
}

function RunHistory({ runs, selected, busy, loading, openRun, newAnalysis, refresh }: {
  runs: Run[];
  selected: Run | null;
  busy: boolean;
  loading: boolean;
  openRun: (run: Run) => void;
  newAnalysis: () => void;
  refresh: () => void;
}) {
  return <aside className="run-history" aria-label="Recent analyses">
    <div className="history-actions"><strong>Recent analyses</strong><button type="button" className="icon-button" onClick={refresh} disabled={loading} aria-label="Refresh recent analyses">↻</button></div>
    <button type="button" className="new-run-button" onClick={newAnalysis}><span aria-hidden="true">＋</span> New analysis</button>
    <div className="run-history-list">
      {runs.map((item) => <button
        key={item.id}
        type="button"
        className={selected?.id === item.id ? "history-item selected" : "history-item"}
        aria-pressed={selected?.id === item.id}
        onClick={() => openRun(item)}
        disabled={busy}
      ><span>{item.request || "Untitled analysis"}</span><span><StatusPill value={item.status} /></span></button>)}
    </div>
    <p className="history-boundary">Research only. Approval and execution remain separate.</p>
  </aside>;
}

function ResearchComposer(props: {
  request: string;
  setRequest: (value: string) => void;
  selectedSkillId: string;
  setSelectedSkillId: (value: string) => void;
  skills: Skill[];
  selectedStrategyId: string;
  setSelectedStrategyId: (value: string) => void;
  strategies: Strategy[];
  useInvestorContext: boolean;
  setUseInvestorContext: (value: boolean) => void;
  investorContext: Record<string, unknown>;
  investorContextReady: boolean;
  previewLoading: boolean;
  previewReady: boolean;
  runBusy: boolean;
  canPreview: boolean;
  canStart: boolean;
  makePreview: () => void;
  startRun: () => void;
  composerRef: RefObject<HTMLTextAreaElement | null>;
  onComposerKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
}) {
  const contextConfigured = props.investorContext.configured === true;
  const primaryDisabled = props.previewReady ? !props.canStart : !props.canPreview;
  const primaryLabel = props.runBusy
    ? "Starting analysis…"
    : props.previewLoading
      ? "Reviewing scope…"
      : props.previewReady
        ? "Start analysis"
        : "Review analysis";
  return <section className="composer-card" aria-labelledby="composer-title" aria-busy={props.previewLoading || props.runBusy}>
    <div className="composer-heading"><div><span className="step-number">01</span><div><h2 id="composer-title">Ask the research question</h2><p>Include the horizon, decision, and what would change your mind. A rough question is fine.</p></div></div><span className="shortcut"><kbd>⌘/Ctrl</kbd><span>+</span><kbd>Enter</kbd></span></div>
    <label className="sr-only" htmlFor="analysis-request">Analysis request</label>
    <textarea
      id="analysis-request"
      ref={props.composerRef}
      value={props.request}
      onChange={(event) => props.setRequest(event.target.value)}
      onKeyDown={props.onComposerKeyDown}
      rows={7}
      aria-describedby="analysis-request-help"
      placeholder="Example: Compare the bull and bear cases for NVDA over the next 12 months. Identify the evidence that would invalidate each case. No orders or execution."
    />
    <div className="setup-grid" id="analysis-request-help">
      <label><span>Method</span><select value={props.selectedSkillId} onChange={(event) => props.setSelectedSkillId(event.target.value)}><option value="">Automatic — Head Manager decides</option>{props.skills.map((skill) => <option key={skill.id} value={skill.id}>{skill.label}</option>)}</select></label>
      <label><span>Strategy</span><select value={props.selectedStrategyId} onChange={(event) => props.setSelectedStrategyId(event.target.value)}><option value="">No strategy overlay</option>{props.strategies.map((strategy) => <option key={strategy.id} value={strategy.id}>{strategy.label}</option>)}</select></label>
      <label className="context-choice"><input type="checkbox" checked={props.useInvestorContext} disabled={!props.investorContextReady || !contextConfigured} onChange={(event) => props.setUseInvestorContext(event.target.checked)} /><span><strong>Investor Context</strong><small>{!props.investorContextReady ? "Loading workspace default…" : contextConfigured ? "Use your saved preferences" : "Not configured"}</small></span></label>
    </div>
    <div className="composer-footer"><p><span aria-hidden="true">⌁</span> Analysis can research and synthesize. It cannot approve or execute trades.</p><button className="primary-button" type="button" onClick={props.previewReady ? props.startRun : props.makePreview} disabled={primaryDisabled}>{primaryLabel}<span aria-hidden="true">→</span></button></div>
  </section>;
}

function GettingStarted({ setRequest }: { setRequest: (value: string) => void }) {
  return <section className="getting-started" aria-labelledby="examples-title"><div><span className="eyebrow">Good starting points</span><h2 id="examples-title">Bring a decision, not a perfect prompt.</h2><p>Head Manager interprets the question directly and revises the workflow as verified evidence arrives.</p></div><div className="example-list">{EXAMPLES.map((example) => <button key={example} type="button" onClick={() => setRequest(example)}><span>{example}</span><span aria-hidden="true">↗</span></button>)}</div></section>;
}

function ScopeReview({ payload, selectedSkill, selectedStrategy, useInvestorContext }: { payload: Record<string, unknown>; selectedSkill?: Skill; selectedStrategy?: Strategy; useInvestorContext: boolean }) {
  const scope = asRecord(payload.scope_review);
  const strategy = asRecord(payload.strategy_binding);
  const context = asRecord(payload.investor_context_binding);
  return <section className="scope-review" aria-labelledby="scope-title">
    <div className="scope-confirm"><span className="scope-check" aria-hidden="true">✓</span><div><span className="eyebrow">Scope reviewed</span><h2 id="scope-title">Ready for dynamic research</h2><p>Head Manager will choose specialists as the evidence develops. No team or stage plan is predetermined.</p></div></div>
    <dl className="scope-summary"><div><dt>Method</dt><dd>{selectedSkill?.label || "Automatic"}</dd></div><div><dt>Strategy</dt><dd>{selectedStrategy?.label || asText(strategy.strategy_id) || "None"}</dd></div><div><dt>Investor Context</dt><dd>{useInvestorContext && context.applied !== false ? "Applied" : "Not applied"}</dd></div><div><dt>Boundary</dt><dd>Analysis only</dd></div></dl>
    <details className="technical-disclosure"><summary>Run configuration</summary><dl><div><dt>Orchestration</dt><dd>{titleCase(asText(scope.orchestration, "codex_native"))}</dd></div><div><dt>Team selection</dt><dd>{titleCase(asText(scope.team_selection, "head_manager_dynamic"))}</dd></div><div><dt>Service scope</dt><dd>{titleCase(asText(scope.service_scope, "persistence_policy_execution"))}</dd></div>{asText(strategy.content_hash) && <div><dt>Strategy digest</dt><dd><code>{asText(strategy.content_hash).slice(0, 12)}</code></dd></div>}</dl></details>
  </section>;
}

function RunWorkspace({ run, busy, copyToCodex, copyNotice, followUp, setFollowUp, sendFollowUp, rerun, artifactClicked }: {
  run: Run;
  busy: boolean;
  copyToCodex: () => void;
  copyNotice: string;
  followUp: string;
  setFollowUp: (value: string) => void;
  sendFollowUp: (event: FormEvent) => void;
  rerun: () => void;
  artifactClicked: (id: string) => void;
}) {
  const raw = run.raw;
  const output = asRecord(raw.final_output);
  const outputText = asText(output.reader_summary);
  const outputHtml = asText(asRecord(output.preview).html);
  const artifacts = recordsFrom(raw.artifacts).map((item, index) => normalizeArtifact(item, index));
  const forecasts = recordsFrom(raw.forecasts);
  const active = !TERMINAL_RUN_STATES.has(run.status);
  const hasVerifiedResult = Boolean(outputText || outputHtml);
  const error = asRecord(raw.error);
  const errorText = asText(error.message);

  return <article className="run-workspace" aria-busy={active}>
    <header className="run-summary-header"><div><span className="eyebrow">Current state</span><div className="run-phase"><span className={active ? "phase-orbit active" : "phase-orbit"} aria-hidden="true"><i /></span><div><h2>{runPhase(raw)}</h2><p>{active ? "The workflow is adapting to accepted evidence." : hasVerifiedResult ? "A verified synthesis is available below." : "The run stopped without a verified synthesis."}</p></div></div></div><StatusPill value={run.status} /></header>

    {errorText && <ErrorNotice>{errorText}</ErrorNotice>}
    <RunStateNotice run={run} hasVerifiedResult={hasVerifiedResult} />

    {hasVerifiedResult ? <ResultBrief output={output} outputText={outputText} outputHtml={outputHtml} forecasts={forecasts} /> : active ? <ActiveResearch agents={recordsFrom(raw.agents)} artifacts={artifacts} /> : !errorText && <EmptyState title="Verified result unavailable">The run ended before an authenticated, accepted synthesis was ready. Review the state below or start a new attempt.</EmptyState>}

    {artifacts.length > 0 && <SupportingArtifacts artifacts={artifacts} onOpen={artifactClicked} />}

    <form className="follow-up-card" onSubmit={sendFollowUp}>
      <div><span className="eyebrow">Continue the same analysis</span><h2>Challenge, narrow, or update the result.</h2><p>The follow-up resumes this run with its sealed context and evidence lineage.</p></div>
      <label htmlFor="follow-up">Follow-up request</label>
      <div className="follow-up-row"><input id="follow-up" value={followUp} onChange={(event) => setFollowUp(event.target.value)} disabled={active || busy} placeholder={active ? "Available when the current attempt stops" : "Ask for contrary evidence, a different horizon, or a tighter conclusion"} /><button className="primary-button" type="submit" disabled={active || busy || !followUp.trim()}>Send follow-up</button></div>
    </form>

    <div className="run-secondary-actions"><button type="button" onClick={rerun} disabled={busy}>Start a new attempt</button><button type="button" onClick={copyToCodex}>Copy native Codex request</button>{copyNotice && <span role="status">{copyNotice}</span>}</div>
    <ResearchActivity raw={raw} />
  </article>;
}

function RunStateNotice({ run, hasVerifiedResult }: { run: Run; hasVerifiedResult: boolean }) {
  const reason = asText(run.raw.stop_reason);
  if (run.status === "blocked") return <Notice title="Research is blocked" tone="bad">{reason || "A required boundary or prerequisite prevented the analysis from continuing."}</Notice>;
  if (run.status === "waiting") return <Notice title={hasVerifiedResult ? "Waiting for your direction" : "Verification is incomplete"} tone="warn">{reason || "Add a focused follow-up or inspect the accepted evidence before continuing."}</Notice>;
  if (run.status === "revise") return <Notice title="Revision requested" tone="warn">{reason || "The evidence did not yet support an accepted synthesis. Refine the question below."}</Notice>;
  if (["failed", "error"].includes(run.status)) return <Notice title="This attempt did not finish" tone="bad">{reason || "Start a new attempt after reviewing the diagnostic details."}</Notice>;
  return null;
}

function ActiveResearch({ agents, artifacts }: { agents: Record<string, unknown>[]; artifacts: Artifact[] }) {
  return <section className="active-research" aria-live="polite"><SectionHeader eyebrow="In progress" title="What is happening now" /><div className="active-grid"><div><span className="metric-value">{agents.length || "—"}</span><span>specialists dispatched</span></div><div><span className="metric-value">{artifacts.length || "—"}</span><span>accepted artifacts</span></div><div className="active-explainer"><strong>Dynamic by design</strong><span>Head Manager decides the next useful role from the request and returned artifacts. No fixed DAG or completion percentage is invented.</span></div></div></section>;
}

function ResultBrief({ output, outputText, outputHtml, forecasts }: { output: Record<string, unknown>; outputText: string; outputHtml: string; forecasts: Record<string, unknown>[] }) {
  const evidence = [
    ["Contrary evidence", asStringList(output.contrary_evidence)],
    ["Missing evidence", asStringList(output.missing_evidence)],
    ["Invalidation conditions", asStringList(output.invalidation_conditions)],
    ["Update triggers", asStringList(output.update_triggers)],
  ] as const;
  const hasEvidencePosture = evidence.some(([, values]) => values.length);
  const blocked = asStringList(output.blocked_actions);
  return <section className="result-brief" aria-labelledby="result-title">
    <div className="result-kicker"><span className="eyebrow">Verified synthesis</span><StatusPill value={asText(output.handoff_state, "accepted")} /></div>
    <h2 id="result-title">{asText(output.title, "Final analysis")}</h2>
    {outputText && <p className="executive-answer">{outputText}</p>}
    <dl className="result-meta"><div><dt>Readiness</dt><dd>{titleCase(asText(output.readiness_label, "accepted"))}</dd></div><div><dt>Confidence</dt><dd>{titleCase(asText(output.confidence, "not stated"))}</dd></div><div><dt>Sources current through</dt><dd>{asText(output.source_as_of, asText(output.knowledge_cutoff, "Not stated"))}</dd></div></dl>
    {asText(output.next_action) && <div className="next-action"><span className="eyebrow">What to do next</span><p>{asText(output.next_action)}</p></div>}
    {hasEvidencePosture && <section className="evidence-posture" aria-labelledby="evidence-posture-title"><SectionHeader eyebrow="Decision quality" title="Evidence posture" /><div className="evidence-grid">{evidence.filter(([, values]) => values.length).map(([label, values]) => <div key={label}><h3>{label}</h3><FieldList values={values} /></div>)}</div></section>}
    {forecasts.map((forecast, index) => <ForecastPanel key={asText(forecast.forecast_id, String(index))} forecast={forecast} />)}
    {blocked.length > 0 && <details className="boundary-disclosure"><summary>Outside this analysis</summary><FieldList values={blocked} /></details>}
    {outputHtml && <section className="full-report" aria-labelledby="full-report-title"><SectionHeader eyebrow="Full report" title="Research detail" titleId="full-report-title" /><div className="rendered-content" dangerouslySetInnerHTML={{ __html: outputHtml }} /></section>}
  </section>;
}

function ForecastPanel({ forecast }: { forecast: Record<string, unknown> }) {
  const probability = formatForecastValue(forecast.probability ?? forecast.probability_range ?? forecast.probabilities ?? forecast.prediction ?? forecast.interval ?? forecast.quantiles);
  const baseRate = asRecord(forecast.base_rate);
  const baseRateSummary = Object.keys(baseRate).length ? [Object.entries(baseRate).map(([key, value]) => `${key}: ${asText(value, "not stated")}`).join(" · ")] : [];
  return <section className="forecast-panel"><div><span className="eyebrow">Structured forecast</span><h3>{asText(forecast.forecast_target, "Forecast discipline")}</h3></div><dl className="forecast-facts"><div><dt>Horizon</dt><dd>{asText(forecast.horizon, "Not stated")}</dd></div><div><dt>Probability or range</dt><dd>{probability || "Not stated"}</dd></div><div><dt>Base rate</dt><dd><FieldList values={baseRateSummary} /></dd></div><div><dt>Resolution rule</dt><dd>{asText(forecast.resolution_rule, "Not stated")}</dd></div></dl><div className="forecast-lists"><div><h4>Update triggers</h4><FieldList values={asStringList(forecast.update_triggers)} /></div><div><h4>Contrary evidence</h4><FieldList values={asStringList(forecast.contrary_evidence)} /></div><div><h4>Invalidation</h4><FieldList values={asStringList(forecast.invalidation_conditions)} /></div></div></section>;
}

function SupportingArtifacts({ artifacts, onOpen }: { artifacts: Artifact[]; onOpen: (id: string) => void }) {
  return <section className="supporting-artifacts" aria-labelledby="supporting-title"><SectionHeader eyebrow="Accepted inputs" title="Supporting research" titleId="supporting-title" aside={<span className="count">{artifacts.length}</span>} /><div className="artifact-card-grid">{artifacts.map((artifact) => <button key={artifact.id} type="button" onClick={() => onOpen(artifact.id)}><span className="artifact-type">{titleCase(artifact.type)}</span><strong>{artifact.title}</strong><span>{artifact.summary || "Open the verified artifact."}</span><span className="artifact-card-meta">{titleCase(artifact.readiness)} <i aria-hidden="true">→</i></span></button>)}</div></section>;
}

function ResearchActivity({ raw }: { raw: Record<string, unknown> }) {
  const agents = recordsFrom(raw.agents);
  const activity = recordsFrom(raw.activity);
  return <details className="research-activity"><summary><span><strong>Research activity</strong><small>Specialists, accepted events, and technical provenance</small></span><span aria-hidden="true">＋</span></summary><div className="activity-content"><section><h3>Specialists</h3>{agents.length ? <div className="agent-list">{agents.map((agent, index) => <div key={`${asText(agent.role)}-${index}`}><div><strong>{titleCase(asText(agent.role, "Specialist"))}</strong><span>{asText(agent.agent_session_id)}</span></div><StatusPill value={asText(agent.status, "selected")} /></div>)}</div> : <p className="muted">No specialist dispatch has been recorded.</p>}</section><section><h3>Allowlisted activity</h3>{activity.length ? <div className="activity-list">{activity.map((item, index) => <div key={`${asText(item.type)}-${index}`}><div><strong>{activityLabel(item)}</strong><span>{[asText(item.item_type), asText(item.tool_name)].filter(Boolean).join(" · ") || "Progress update"}</span></div><div><StatusPill value={asText(item.status, "recorded")} />{asText(item.ts) && <time dateTime={asText(item.ts)}>{formatDate(asText(item.ts))}</time>}</div></div>)}</div> : <p className="muted">No public activity events are available.</p>}</section><section className="technical-id"><h3>Run provenance</h3><code>{asText(raw.workflow_run_id)}</code><p>Private reasoning, tool inputs, raw outputs, and credentials are never displayed here.</p></section></div></details>;
}
