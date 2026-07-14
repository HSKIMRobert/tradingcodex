import { FormEvent, KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { apiErrorText, mutation, requestJSON } from "./api";
import {
  asRecord,
  asText,
  normalizeArtifact,
  normalizeRun,
  normalizeSkill,
  normalizeStrategy,
  recordsFrom,
  Run,
  Section,
  sectionError,
  TERMINAL_RUN_STATES,
  Theme,
} from "./domain";
import { LibraryPage } from "./features/LibraryPage";
import { SkillsPage } from "./features/SkillsPage";
import { SystemPage } from "./features/SystemPage";
import { WorkPage } from "./features/WorkPage";
import { hashForSection, sectionFromHash } from "./navigation.js";
import { ErrorNotice, LoadingState } from "./ui";
import {
  investorContextRequest,
  sectionData,
  snapshotSections,
  workActionAvailability,
  workbenchPromptRequest,
  workbenchSelectionRequest,
  workPreviewKey,
} from "./workbench-data.js";

const PRIMARY_NAV: Array<{ id: Section; label: string }> = [
  { id: "work", label: "Work" },
  { id: "library", label: "Research" },
  { id: "skills", label: "Approaches" },
];

function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    const stored = localStorage.getItem("tcx-theme");
    return stored === "dark" || stored === "light" ? stored : "auto";
  });
  useEffect(() => {
    if (theme === "auto") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;
    localStorage.setItem("tcx-theme", theme);
  }, [theme]);
  return [theme, () => setTheme((current) => current === "auto" ? "dark" : current === "dark" ? "light" : "auto")];
}

export default function App() {
  const [section, setSection] = useState<Section>(() => sectionFromHash(window.location.hash) as Section);
  const [theme, cycleTheme] = useTheme();
  const [state, setState] = useState<Record<string, unknown>>({});
  const [stateLoading, setStateLoading] = useState(true);
  const [stateError, setStateError] = useState("");
  const [request, setRequest] = useState("");
  const [selectedSkillId, setSelectedSkillId] = useState("");
  const [selectedStrategyId, setSelectedStrategyId] = useState("");
  const [useInvestorContext, setUseInvestorContext] = useState<boolean | null>(null);
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [previewKey, setPreviewKey] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [workError, setWorkError] = useState("");
  const [run, setRun] = useState<Run | null>(null);
  const [runBusy, setRunBusy] = useState(false);
  const [followUp, setFollowUp] = useState("");
  const [copyNotice, setCopyNotice] = useState("");
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const mainRef = useRef<HTMLElement>(null);
  const focusMainRef = useRef(false);
  const focusComposerRef = useRef(false);
  const previewTokenRef = useRef(0);
  const previewBusyRef = useRef(0);
  const runBusyRef = useRef(false);
  const activeRunIdRef = useRef("");

  const resetPreview = useCallback(() => {
    previewTokenRef.current += 1;
    previewBusyRef.current = 0;
    setPreviewLoading(false);
    setPreview(null);
    setPreviewKey("");
  }, []);

  const loadState = useCallback(async () => {
    setStateLoading(true);
    setStateError("");
    try {
      const payload = await requestJSON<unknown>("/api/workbench/");
      setState(snapshotSections(payload));
    } catch (error) {
      setStateError(apiErrorText(error));
    } finally {
      setStateLoading(false);
    }
  }, []);

  useEffect(() => { void loadState(); }, [loadState]);
  useEffect(() => {
    const onHash = () => {
      const next = sectionFromHash(window.location.hash) as Section;
      focusMainRef.current = !(focusComposerRef.current && next === "work");
      setSection(next);
    };
    window.addEventListener("hashchange", onHash);
    if (!window.location.hash) history.replaceState(null, "", `${window.location.pathname}${window.location.search}${hashForSection("work")}`);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  useEffect(() => {
    const labels: Record<Section, string> = { work: "Work", library: "Research", skills: "Approaches", system: "Settings" };
    document.title = `${labels[section]} · TradingCodex`;
    window.scrollTo(0, 0);
    if (section === "work" && focusComposerRef.current) {
      requestAnimationFrame(() => {
        if (composerRef.current) {
          composerRef.current.focus();
          focusComposerRef.current = false;
        }
      });
    } else if (focusMainRef.current) {
      focusMainRef.current = false;
      requestAnimationFrame(() => mainRef.current?.focus());
    }
  }, [section]);

  const newAnalysis = useCallback((nextRequest = "") => {
    activeRunIdRef.current = "";
    setRun(null);
    setFollowUp("");
    setWorkError("");
    setRequest(nextRequest);
    resetPreview();
    focusComposerRef.current = true;
    window.location.hash = hashForSection("work");
    requestAnimationFrame(() => {
      if (composerRef.current) {
        composerRef.current.focus();
        focusComposerRef.current = false;
      }
    });
  }, [resetPreview]);

  useEffect(() => {
    const onShortcut = (event: globalThis.KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        newAnalysis();
      }
    };
    window.addEventListener("keydown", onShortcut);
    return () => window.removeEventListener("keydown", onShortcut);
  }, [newAnalysis]);

  const skills = useMemo(() => recordsFrom(sectionData(state, "skills")).map(normalizeSkill), [state]);
  const strategies = useMemo(() => recordsFrom(sectionData(state, "strategies"))
    .filter((item) => asText(item.status) === "active" && asText(item.validation_status, "valid") === "valid")
    .map((item, index) => {
      const strategy = normalizeStrategy(item, index);
      return { ...strategy, label: skills.find((skill) => skill.id === strategy.id)?.label || strategy.label };
    }), [skills, state]);
  const artifacts = useMemo(() => recordsFrom(sectionData(state, "artifacts")).map(normalizeArtifact), [state]);
  const runs = useMemo(() => recordsFrom(sectionData(state, "runs")).map(normalizeRun).filter((item): item is Run => item !== null), [state]);
  const investorContextSection = asRecord(state.investor_context);
  const investorContext = asRecord(sectionData(state, "investor_context"));
  const investorContextError = sectionError(state, "investor_context");
  const investorContextReady = investorContextSection.ok === true;
  const investorContextDefault = investorContext.configured === true && investorContext.enabled_by_default !== false;
  const investorContextApplied = useInvestorContext ?? investorContextDefault;
  const selectedStrategyHash = strategies.find((strategy) => strategy.id === selectedStrategyId)?.hash || "";
  const currentPreviewKey = workPreviewKey({
    request,
    methodId: selectedSkillId,
    strategyId: selectedStrategyId,
    strategyHash: selectedStrategyHash,
    useInvestorContext: investorContextApplied,
    investorContextHash: asText(investorContext.content_hash),
  });
  const previewReady = Boolean(!previewLoading && preview && previewKey === currentPreviewKey && asText(preview.preview_signature));
  const actions = workActionAvailability({ contextReady: investorContextReady, request, previewLoading, runBusy, previewReady });

  useEffect(() => {
    if (selectedStrategyId && !strategies.some((strategy) => strategy.id === selectedStrategyId)) {
      setSelectedStrategyId("");
      resetPreview();
    }
  }, [resetPreview, selectedStrategyId, strategies]);
  useEffect(() => {
    if (preview && previewKey !== currentPreviewKey) {
      setPreview(null);
      setPreviewKey("");
    }
  }, [currentPreviewKey, preview, previewKey]);

  const pollRun = useCallback(async (runId: string) => {
    try {
      const payload = await requestJSON<unknown>(`/api/workbench/runs/${encodeURIComponent(runId)}/`);
      const next = normalizeRun(payload);
      if (next && activeRunIdRef.current === runId) {
        setRun(next);
        setWorkError("");
      }
    } catch (error) {
      if (activeRunIdRef.current === runId) setWorkError(apiErrorText(error));
    }
  }, []);

  useEffect(() => {
    if (!run || TERMINAL_RUN_STATES.has(run.status)) return;
    const timer = window.setInterval(() => { void pollRun(run.id); }, 1500);
    return () => window.clearInterval(timer);
  }, [pollRun, run]);
  useEffect(() => {
    if (!run?.id) return;
    const timer = window.setTimeout(() => {
      window.scrollTo(0, 0);
      mainRef.current?.focus({ preventScroll: true });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [run?.id]);
  useEffect(() => { if (run && TERMINAL_RUN_STATES.has(run.status)) void loadState(); }, [loadState, run?.id, run?.status]);

  const makePreview = async () => {
    const prompt = request.trim();
    if (!prompt) { setWorkError("Describe the analysis you want to run."); composerRef.current?.focus(); return; }
    if (!investorContextReady) { setWorkError(investorContextError || stateError || "Workspace Investor Context is still loading."); return; }
    if (previewBusyRef.current || runBusyRef.current || previewLoading || runBusy) return;
    setPreviewLoading(true); setWorkError(""); setPreview(null); setPreviewKey("");
    const token = ++previewTokenRef.current; previewBusyRef.current = token;
    try {
      const payload = await mutation("/api/workbench/preview/", "POST", { ...workbenchPromptRequest(prompt), ...workbenchSelectionRequest(selectedSkillId, selectedStrategyId), ...investorContextRequest(useInvestorContext) });
      if (token !== previewTokenRef.current) return;
      setPreview(asRecord(payload)); setPreviewKey(currentPreviewKey);
    } catch (error) {
      if (token === previewTokenRef.current) setWorkError(apiErrorText(error));
    } finally {
      if (previewBusyRef.current === token) previewBusyRef.current = 0;
      if (token === previewTokenRef.current) setPreviewLoading(false);
    }
  };

  const startRun = async () => {
    if (previewBusyRef.current || runBusyRef.current || previewLoading || runBusy) return;
    if (!investorContextReady) { setWorkError(investorContextError || stateError || "Workspace Investor Context is still loading."); return; }
    const prompt = request.trim();
    const signature = asText(preview?.preview_signature);
    if (!prompt || previewKey !== currentPreviewKey || !signature) { await makePreview(); return; }
    runBusyRef.current = true; setRunBusy(true); setWorkError("");
    try {
      const payload = await mutation("/api/workbench/runs/", "POST", { ...workbenchPromptRequest(prompt), ...workbenchSelectionRequest(selectedSkillId, selectedStrategyId), ...investorContextRequest(useInvestorContext), preview_signature: signature });
      const next = normalizeRun(payload);
      if (!next) throw new Error("The service started work but did not return a run identifier.");
      activeRunIdRef.current = next.id; setRun(next);
    } catch (error) { setWorkError(apiErrorText(error)); }
    finally { runBusyRef.current = false; setRunBusy(false); }
  };

  const onComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      if (actions.canStart) void startRun(); else if (actions.canPreview) void makePreview();
    }
  };

  const openRun = async (item: Run) => {
    setWorkError(""); setFollowUp(""); activeRunIdRef.current = item.id; setRun(item);
    window.location.hash = hashForSection("work");
    await pollRun(item.id);
  };

  const sendFollowUp = async (event: FormEvent) => {
    event.preventDefault();
    if (!run || !TERMINAL_RUN_STATES.has(run.status) || !followUp.trim() || runBusyRef.current) return;
    const runId = run.id; runBusyRef.current = true; setRunBusy(true); setWorkError("");
    try {
      const payload = await mutation(`/api/workbench/runs/${encodeURIComponent(runId)}/follow-up/`, "POST", workbenchPromptRequest(followUp));
      if (activeRunIdRef.current !== runId) return;
      const next = normalizeRun(payload);
      if (next) { activeRunIdRef.current = next.id; setRun(next); } else await pollRun(runId);
      setFollowUp("");
    } catch (error) { if (activeRunIdRef.current === runId) setWorkError(apiErrorText(error)); }
    finally { runBusyRef.current = false; setRunBusy(false); }
  };

  const copyToCodex = async () => {
    const text = `$tcx-workflow ${run?.request || request.trim() || "Review the selected analysis run."}`;
    try { await navigator.clipboard.writeText(text); setCopyNotice("Native Codex request copied."); }
    catch { setCopyNotice(text); }
    window.setTimeout(() => setCopyNotice(""), 3000);
  };

  const workspaceData = asRecord(sectionData(state, "workspace"));
  const workspace = asRecord(workspaceData.context);
  const workspaceName = asText(workspace.project_name, "Local workspace");
  const hasSnapshot = Object.keys(state).length > 0;

  return <>
    <a className="skip-link" href="#main-content">Skip to content</a>
    <div className="app-shell">
      <header className="global-header">
        <a className="brand" href={hashForSection("work")} aria-label="TradingCodex Work"><span className="brand-mark" aria-hidden="true"><i /><i /><i /></span><span><strong>TradingCodex</strong><small>{workspaceName}</small></span></a>
        <nav className="primary-nav" aria-label="Primary navigation">{PRIMARY_NAV.map((item) => <a key={item.id} href={hashForSection(item.id)} className={section === item.id ? "active" : ""} aria-current={section === item.id ? "page" : undefined}>{item.label}</a>)}</nav>
        <div className="header-tools"><span className={`service-health ${stateError ? "error" : stateLoading ? "loading" : "ready"}`} role="status" aria-label={stateError ? "Service needs attention" : stateLoading ? "Refreshing local service" : "Local service ready"}><i aria-hidden="true" /><span className="health-label">{stateError ? "Attention" : stateLoading ? "Refreshing" : "Local"}</span></span><a className={section === "system" ? "header-link active" : "header-link"} href={hashForSection("system")} aria-current={section === "system" ? "page" : undefined}>Settings</a><button className="theme-button" type="button" onClick={cycleTheme} aria-label={`Theme is ${theme}. Change theme.`}><span aria-hidden="true">◐</span><span className="theme-label">{theme}</span></button></div>
      </header>
      <main id="main-content" ref={mainRef} tabIndex={-1} aria-busy={stateLoading && !hasSnapshot}>
        <div className="sr-status" aria-live="polite">{stateLoading ? "Loading TradingCodex" : stateError || (run ? `Analysis ${run.status}` : "TradingCodex ready")}</div>
        {stateError && <div className="global-notice"><ErrorNotice retry={() => void loadState()}>{stateError}</ErrorNotice></div>}
        {stateLoading && !hasSnapshot ? <div className="initial-loading"><LoadingState label="Opening the local research workspace…" /></div> : stateError && !hasSnapshot ? null : <>
          {section === "work" && <WorkPage request={request} setRequest={(value) => { resetPreview(); setRequest(value); }} selectedSkillId={selectedSkillId} setSelectedSkillId={(value) => { resetPreview(); setSelectedSkillId(value); }} skills={skills.filter((skill) => skill.startable && skill.kind !== "strategy")} selectedStrategyId={selectedStrategyId} setSelectedStrategyId={(value) => { resetPreview(); setSelectedStrategyId(value); }} strategies={strategies} useInvestorContext={investorContextApplied} setUseInvestorContext={(value) => { resetPreview(); setUseInvestorContext(value); }} investorContext={investorContext} investorContextReady={investorContextReady} investorContextError={investorContextError} preview={preview} previewLoading={previewLoading} previewReady={previewReady} canPreview={actions.canPreview} canStart={actions.canStart} makePreview={() => void makePreview()} startRun={() => void startRun()} run={run} runs={runs} runBusy={runBusy} workError={workError} stateLoading={stateLoading} composerRef={composerRef} onComposerKeyDown={onComposerKeyDown} copyToCodex={() => void copyToCodex()} copyNotice={copyNotice} followUp={followUp} setFollowUp={setFollowUp} sendFollowUp={sendFollowUp} newAnalysis={newAnalysis} openRun={(item) => void openRun(item)} refreshRuns={() => void loadState()} artifactClicked={(id) => { sessionStorage.setItem("tcx-selected-artifact", id); window.location.hash = hashForSection("library"); }} />}
          {section === "library" && <LibraryPage artifacts={artifacts} error={sectionError(state, "artifacts")} loading={stateLoading} />}
          {section === "skills" && <SkillsPage state={state} skills={skills.filter((skill) => skill.visible)} error={sectionError(state, "skills")} selectedSkillId={selectedSkillId} loading={stateLoading} refreshState={loadState} selectForWork={(id) => { resetPreview(); const selected = skills.find((skill) => skill.id === id); if (selected?.kind === "strategy") setSelectedStrategyId(id); else setSelectedSkillId(id); newAnalysis(request); }} />}
          {section === "system" && <SystemPage state={state} />}
        </>}
      </main>
    </div>
  </>;
}
