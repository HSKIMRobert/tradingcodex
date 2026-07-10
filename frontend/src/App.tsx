import {
  FormEvent,
  KeyboardEvent,
  ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { apiErrorText, mutation, requestJSON } from "./api";
import { hashForSection, matchesSearch, sectionFromHash } from "./navigation.js";
import { isSharedAccountScope, isSkillCatalogVisible, sectionData, snapshotSections, workPreviewKey } from "./workbench-data.js";

type RecordValue = Record<string, unknown>;
type Section = "work" | "skills" | "library" | "system";
type Theme = "auto" | "dark" | "light";

type Skill = {
  id: string;
  label: string;
  description: string;
  owner: string;
  boundary: string;
  kind: string;
  status: string;
  startable: boolean;
  visible: boolean;
  protectedAction: boolean;
  raw: RecordValue;
};

type Strategy = {
  id: string;
  label: string;
  hash: string;
};

type Artifact = {
  id: string;
  title: string;
  type: string;
  sourceAsOf: string;
  confidence: string;
  readiness: string;
  summary: string;
  missingEvidence: string[];
  raw: RecordValue;
};

type Run = {
  id: string;
  status: string;
  request: string;
  raw: RecordValue;
};

const TERMINAL_RUN_STATES = new Set([
  "blocked",
  "cancelled",
  "complete",
  "completed",
  "error",
  "failed",
  "lane_escalation_proposal",
  "revise",
  "revision_required",
  "succeeded",
  "waiting",
]);

const NAV_ITEMS: Array<{ id: Section; label: string; hint: string }> = [
  { id: "work", label: "Work", hint: "Start and review analysis" },
  { id: "skills", label: "Skills", hint: "Methods and extensions" },
  { id: "library", label: "Library", hint: "Evidence and results" },
  { id: "system", label: "System", hint: "Local state and safety" },
];

function asRecord(value: unknown): RecordValue {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as RecordValue : {};
}

function asText(value: unknown, fallback = ""): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

function asStringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => {
      if (typeof item === "string") return item;
      const record = asRecord(item);
      return asText(record.label || record.name || record.title || record.id || record.message);
    }).filter(Boolean);
  }
  return typeof value === "string" && value.trim() ? [value] : [];
}

function firstText(record: RecordValue, keys: string[], fallback = ""): string {
  for (const key of keys) {
    const value = asText(record[key]);
    if (value) return value;
  }
  return fallback;
}

function recordsFrom(value: unknown, key = ""): RecordValue[] {
  const items = Array.isArray(value) ? value : key ? asRecord(value)[key] : [];
  if (Array.isArray(items)) return items.map(asRecord).filter((item) => Object.keys(item).length > 0);
  return [];
}

function sectionError(state: RecordValue, key: string): string {
  const value = asRecord(state[key]);
  if (value.ok !== false) return "";
  const error = asRecord(value.error);
  return firstText(error, ["message", "detail", "code"], firstText(value, ["message", "detail"], "Section unavailable."));
}

function normalizeSkill(value: RecordValue, index: number): Skill {
  const id = asText(value.id, `skill-${index + 1}`);
  const riskTags = asStringList(value.risk_tags);
  return {
    id,
    label: asText(value.label, id.replaceAll("-", " ")),
    description: asText(value.description),
    owner: asStringList(value.owner_roles).join(", ") || "head-manager",
    boundary: "Guides analysis; does not grant role, approval, or execution authority.",
    kind: asText(value.source, "built-in"),
    status: asText(value.status, "active"),
    startable: value.startable === true && !riskTags.some((tag) => ["order", "approval", "execution", "secret"].includes(tag)),
    visible: isSkillCatalogVisible(value),
    protectedAction: riskTags.some((tag) => ["order", "approval", "execution", "secret"].includes(tag)),
    raw: value,
  };
}

function normalizeStrategy(value: RecordValue, index: number): Strategy {
  const id = firstText(value, ["name", "id"], `strategy-${index + 1}`);
  return {
    id,
    label: firstText(value, ["heading", "label", "name"], id.replaceAll("strategy-", "").replaceAll("-", " ")),
    hash: firstText(value, ["source_file_hash", "content_hash"]),
  };
}

function normalizeArtifact(value: RecordValue, index: number): Artifact {
  const id = firstText(value, ["id", "artifact_id", "path"], `artifact-${index + 1}`);
  return {
    id,
    title: firstText(value, ["title", "label", "name"], id),
    type: firstText(value, ["artifact_type", "type", "kind"], "artifact"),
    sourceAsOf: firstText(value, ["source_as_of", "as_of", "data_as_of", "updated_at"]),
    confidence: firstText(value, ["confidence", "confidence_label", "confidence_level"], "not stated"),
    readiness: firstText(value, ["readiness_label", "readiness", "status", "handoff_state"], "waiting"),
    summary: firstText(value, ["reader_summary", "summary", "description", "next_action"]),
    missingEvidence: asStringList(value.missing_evidence || value.gaps || value.blockers),
    raw: value,
  };
}

function normalizeRun(value: unknown): Run | null {
  const record = asRecord(value);
  const id = asText(record.workflow_run_id);
  if (!id) return null;
  return {
    id,
    status: asText(record.status, "queued").toLowerCase(),
    request: asText(record.original_request),
    raw: record,
  };
}

function statusTone(status: string): string {
  const normalized = status.toLowerCase();
  if (["complete", "completed", "succeeded", "accepted", "ready", "active", "valid"].includes(normalized)) return "good";
  if (["blocked", "error", "failed", "denied", "invalid"].includes(normalized)) return "bad";
  if (["waiting", "revise", "revision_required", "needs_review", "pending"].includes(normalized)) return "warn";
  return "neutral";
}

function formatDate(value: string): string {
  if (!value) return "Not stated";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function ErrorNotice({ children }: { children: ReactNode }) {
  return <div className="notice notice-error" role="alert">{children}</div>;
}

function Empty({ title, children }: { title: string; children: ReactNode }) {
  return <div className="empty"><strong>{title}</strong><span>{children}</span></div>;
}

function Status({ value }: { value: string }) {
  return <span className={`status status-${statusTone(value)}`}>{value.replaceAll("_", " ")}</span>;
}

function FieldList({ values, empty = "None reported" }: { values: string[]; empty?: string }) {
  if (!values.length) return <span className="muted">{empty}</span>;
  return <ul className="plain-list">{values.map((value, index) => <li key={`${value}-${index}`}>{value}</li>)}</ul>;
}

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
  const cycle = () => setTheme((current) => current === "auto" ? "dark" : current === "dark" ? "light" : "auto");
  return [theme, cycle];
}

export default function App() {
  const [section, setSection] = useState<Section>(() => sectionFromHash(window.location.hash) as Section);
  const [theme, cycleTheme] = useTheme();
  const [state, setState] = useState<RecordValue>({});
  const [stateLoading, setStateLoading] = useState(true);
  const [stateError, setStateError] = useState("");
  const [request, setRequest] = useState("");
  const [selectedSkillId, setSelectedSkillId] = useState("");
  const [selectedStrategyId, setSelectedStrategyId] = useState("");
  const [useInvestorContext, setUseInvestorContext] = useState<boolean | null>(null);
  const [preview, setPreview] = useState<RecordValue | null>(null);
  const [previewKey, setPreviewKey] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [workError, setWorkError] = useState("");
  const [run, setRun] = useState<Run | null>(null);
  const [runBusy, setRunBusy] = useState(false);
  const [followUp, setFollowUp] = useState("");
  const [copyNotice, setCopyNotice] = useState("");
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const focusComposerOnWorkRef = useRef(false);
  const previewTokenRef = useRef(0);
  const activeRunIdRef = useRef("");

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
    const onHash = () => setSection(sectionFromHash(window.location.hash) as Section);
    window.addEventListener("hashchange", onHash);
    if (!window.location.hash) history.replaceState(null, "", `${window.location.pathname}${window.location.search}${hashForSection("work")}`);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  useEffect(() => { window.scrollTo(0, 0); }, [section]);
  useEffect(() => {
    if (section === "work" && focusComposerOnWorkRef.current) {
      focusComposerOnWorkRef.current = false;
      composerRef.current?.focus();
    }
  }, [section]);
  useEffect(() => {
    const onShortcut = (event: globalThis.KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        focusComposerOnWorkRef.current = true;
        window.location.hash = hashForSection("work");
        requestAnimationFrame(() => {
          if (composerRef.current) {
            focusComposerOnWorkRef.current = false;
            composerRef.current.focus();
          }
        });
      }
    };
    window.addEventListener("keydown", onShortcut);
    return () => window.removeEventListener("keydown", onShortcut);
  }, []);

  const skills = useMemo(() => {
    return recordsFrom(sectionData(state, "skills")).map(normalizeSkill);
  }, [state]);
  const strategies = useMemo(() => {
    return recordsFrom(sectionData(state, "strategies"))
      .filter((item) => asText(item.status) === "active" && asText(item.validation_status, "valid") === "valid")
      .map((item, index) => {
        const strategy = normalizeStrategy(item, index);
        return { ...strategy, label: skills.find((skill) => skill.id === strategy.id)?.label || strategy.label };
      });
  }, [skills, state]);
  const investorContext = asRecord(sectionData(state, "investor_context"));
  const investorContextError = sectionError(state, "investor_context");
  const investorContextConfigured = investorContext.configured === true;
  const investorContextDefault = investorContextConfigured && investorContext.enabled_by_default !== false;
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
  const artifacts = useMemo(() => {
    return recordsFrom(sectionData(state, "artifacts")).map(normalizeArtifact);
  }, [state]);
  const runs = useMemo(() => {
    return recordsFrom(sectionData(state, "runs")).map(normalizeRun).filter((item): item is Run => item !== null);
  }, [state]);

  useEffect(() => {
    if (selectedStrategyId && !strategies.some((strategy) => strategy.id === selectedStrategyId)) {
      setSelectedStrategyId("");
      setPreview(null);
      setPreviewKey("");
    }
  }, [selectedStrategyId, strategies]);
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
    if (run && TERMINAL_RUN_STATES.has(run.status)) void loadState();
  }, [loadState, run?.id, run?.status]);

  const makePreview = async () => {
    const prompt = request.trim();
    if (!prompt) {
      setWorkError("Describe the analysis you want to run.");
      composerRef.current?.focus();
      return;
    }
    setPreviewLoading(true);
    setWorkError("");
    setPreview(null);
    setPreviewKey("");
    const token = ++previewTokenRef.current;
    try {
      const payload = await mutation("/api/workbench/preview/", "POST", {
        request: prompt,
        skill_id: selectedSkillId || null,
        strategy_id: selectedStrategyId || null,
        use_investor_context: investorContextApplied,
      });
      if (token !== previewTokenRef.current) return;
      setPreview(asRecord(payload));
      setPreviewKey(currentPreviewKey);
    } catch (error) {
      if (token === previewTokenRef.current) setWorkError(apiErrorText(error));
    } finally {
      if (token === previewTokenRef.current) setPreviewLoading(false);
    }
  };

  const startRun = async () => {
    const prompt = request.trim();
    const signature = asText(preview?.preview_signature);
    if (!prompt || previewKey !== currentPreviewKey || !signature) {
      await makePreview();
      return;
    }
    setRunBusy(true);
    setWorkError("");
    try {
      const payload = await mutation("/api/workbench/runs/", "POST", {
        request: prompt,
        skill_id: selectedSkillId || null,
        strategy_id: selectedStrategyId || null,
        use_investor_context: investorContextApplied,
        preview_signature: signature,
      });
      const next = normalizeRun(payload);
      if (!next) throw new Error("The service started work but did not return a run identifier.");
      activeRunIdRef.current = next.id;
      setRun(next);
    } catch (error) {
      setWorkError(apiErrorText(error));
    } finally {
      setRunBusy(false);
    }
  };

  const onComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      if (previewKey === currentPreviewKey && asText(preview?.preview_signature)) void startRun();
      else void makePreview();
    }
  };

  const openRun = async (item: Run) => {
    setWorkError("");
    activeRunIdRef.current = item.id;
    setRun(item);
    await pollRun(item.id);
    window.location.hash = hashForSection("work");
  };

  const sendFollowUp = async (event: FormEvent) => {
    event.preventDefault();
    if (!run || !followUp.trim()) return;
    const runId = run.id;
    setRunBusy(true);
    setWorkError("");
    try {
      const payload = await mutation(`/api/workbench/runs/${encodeURIComponent(runId)}/follow-up/`, "POST", { message: followUp.trim() });
      if (activeRunIdRef.current !== runId) return;
      const next = normalizeRun(payload);
      if (next) {
        activeRunIdRef.current = next.id;
        setRun(next);
      }
      else await pollRun(runId);
      setFollowUp("");
    } catch (error) {
      if (activeRunIdRef.current === runId) setWorkError(apiErrorText(error));
    } finally {
      setRunBusy(false);
    }
  };

  const copyToCodex = async () => {
    const text = `$tcx-workflow ${request.trim() || run?.request || "Review the selected analysis run."}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopyNotice("Codex handoff copied.");
    } catch {
      setCopyNotice(text);
    }
    window.setTimeout(() => setCopyNotice(""), 3000);
  };

  const workspaceSection = asRecord(sectionData(state, "workspace"));
  const workspace = asRecord(workspaceSection.context);
  const accountScope = asRecord(workspaceSection.profile);
  const workspaceName = firstText(workspace, ["project_name", "label", "name"], "Local workspace");
  const systemError = ["workspace", "investor_context", "brokers", "permissions", "orders", "portfolio"]
    .map((key) => sectionError(state, key))
    .filter(Boolean)
    .join(" ");

  return (
    <>
      <a className="skip-link" href="#main-content">Skip to content</a>
      <div className="app-shell">
        <header className="topbar">
          <a className="brand" href={hashForSection("work")} aria-label="TradingCodex workbench">
            <span className="brand-mark" aria-hidden="true">TC</span>
            <span><strong>TradingCodex</strong><small>{workspaceName}</small></span>
          </a>
          <nav className="primary-nav" aria-label="Workbench">
            {NAV_ITEMS.map((item) => (
              <a key={item.id} href={hashForSection(item.id)} className={section === item.id ? "active" : ""} title={item.hint}>
                {item.label}
              </a>
            ))}
          </nav>
          <div className="top-actions">
            <span className={`service-dot ${stateError ? "error" : stateLoading ? "loading" : "ready"}`} aria-hidden="true" />
            <button className="quiet-button" type="button" onClick={cycleTheme} aria-label={`Theme: ${theme}. Change theme.`}>{theme}</button>
          </div>
        </header>

        <div className="body-grid">
          <aside className="rail" aria-label="Recent analysis">
            <div className="rail-heading"><span>Recent work</span><button type="button" onClick={() => void loadState()} disabled={stateLoading}>Refresh</button></div>
            <div className="run-list">
              {runs.map((item) => (
                <button key={item.id} type="button" className={run?.id === item.id ? "run-link selected" : "run-link"} onClick={() => void openRun(item)} disabled={runBusy}>
                  <span>{item.request || item.id}</span><Status value={item.status} />
                </button>
              ))}
              {!runs.length && <span className="rail-empty">No analysis runs yet.</span>}
            </div>
            <div className="rail-boundary">
              <strong>Analysis first</strong>
              <span>Approval and execution remain outside this workbench.</span>
            </div>
          </aside>

          <main id="main-content" tabIndex={-1}>
            <div className="sr-status" aria-live="polite">
              {stateLoading ? "Loading workbench" : stateError || (run ? `Run ${run.status}` : "Workbench ready")}
            </div>
            {stateError && <ErrorNotice>{stateError} <button type="button" onClick={() => void loadState()}>Retry</button></ErrorNotice>}
            {isSharedAccountScope(accountScope) && <div className="notice notice-warn" role="status"><strong>Shared account scope active.</strong><span>Portfolio, broker, order, and permission state may be visible to other workspaces using this legacy scope.</span></div>}
            {section === "work" && (
              <WorkSection
                request={request}
                setRequest={(value) => { previewTokenRef.current += 1; setPreviewLoading(false); setRequest(value); setPreview(null); setPreviewKey(""); }}
                selectedSkillId={selectedSkillId}
                setSelectedSkillId={(value) => { previewTokenRef.current += 1; setPreviewLoading(false); setSelectedSkillId(value); setPreview(null); setPreviewKey(""); }}
                skills={skills.filter((skill) => skill.startable && skill.kind !== "strategy")}
                selectedStrategyId={selectedStrategyId}
                setSelectedStrategyId={(value) => { previewTokenRef.current += 1; setPreviewLoading(false); setSelectedStrategyId(value); setPreview(null); setPreviewKey(""); }}
                strategies={strategies}
                useInvestorContext={investorContextApplied}
                setUseInvestorContext={(value) => { previewTokenRef.current += 1; setPreviewLoading(false); setUseInvestorContext(value); setPreview(null); setPreviewKey(""); }}
                investorContext={investorContext}
                investorContextError={investorContextError}
                preview={preview}
                previewLoading={previewLoading}
                previewReady={Boolean(!previewLoading && preview && previewKey === currentPreviewKey && asText(preview.preview_signature))}
                makePreview={() => void makePreview()}
                startRun={() => void startRun()}
                run={run}
                runBusy={runBusy}
                workError={workError}
                composerRef={composerRef}
                onComposerKeyDown={onComposerKeyDown}
                copyToCodex={() => void copyToCodex()}
                copyNotice={copyNotice}
                followUp={followUp}
                setFollowUp={setFollowUp}
                sendFollowUp={sendFollowUp}
                rerun={() => {
                  setRequest(run?.request || request);
                  setPreview(null);
                  setPreviewKey("");
                  activeRunIdRef.current = "";
                  setRun(null);
                  requestAnimationFrame(() => composerRef.current?.focus());
                }}
                artifactClicked={(id) => {
                  sessionStorage.setItem("tcx-selected-artifact", id);
                  window.location.hash = hashForSection("library");
                }}
              />
            )}
            {section === "skills" && (
              <SkillsSection
                state={state}
                skills={skills.filter((skill) => skill.visible)}
                error={sectionError(state, "skills")}
                selectedSkillId={selectedSkillId}
                refreshState={loadState}
                selectForWork={(id) => {
                  previewTokenRef.current += 1;
                  setPreviewLoading(false);
                  const selected = skills.find((skill) => skill.id === id);
                  if (selected?.kind === "strategy") setSelectedStrategyId(id);
                  else setSelectedSkillId(id);
                  setPreview(null);
                  setPreviewKey("");
                  window.location.hash = hashForSection("work");
                  requestAnimationFrame(() => composerRef.current?.focus());
                }}
              />
            )}
            {section === "library" && <LibrarySection artifacts={artifacts} error={sectionError(state, "artifacts") || sectionError(state, "library")} />}
            {section === "system" && <SystemSection state={state} error={systemError} />}
          </main>
        </div>
      </div>
    </>
  );
}

type WorkProps = {
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
  investorContext: RecordValue;
  investorContextError: string;
  preview: RecordValue | null;
  previewLoading: boolean;
  previewReady: boolean;
  makePreview: () => void;
  startRun: () => void;
  run: Run | null;
  runBusy: boolean;
  workError: string;
  composerRef: React.RefObject<HTMLTextAreaElement | null>;
  onComposerKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  copyToCodex: () => void;
  copyNotice: string;
  followUp: string;
  setFollowUp: (value: string) => void;
  sendFollowUp: (event: FormEvent) => void;
  rerun: () => void;
  artifactClicked: (id: string) => void;
};

function WorkSection(props: WorkProps) {
  const selectedSkill = props.skills.find((skill) => skill.id === props.selectedSkillId);
  const selectedStrategy = props.strategies.find((strategy) => strategy.id === props.selectedStrategyId);
  const contextConfigured = props.investorContext.configured === true;
  return (
    <section className="page work-page" aria-labelledby="work-title">
      <div className="page-heading">
        <div><span className="eyebrow">Agent-native analysis</span><h1 id="work-title">What do you want to understand?</h1></div>
        {props.run && <Status value={props.run.status} />}
      </div>

      <div className="composer-block">
        <label htmlFor="analysis-request">Analysis request</label>
        <textarea
          id="analysis-request"
          ref={props.composerRef}
          value={props.request}
          onChange={(event) => props.setRequest(event.target.value)}
          onKeyDown={props.onComposerKeyDown}
          rows={5}
          placeholder="Example: Analyze NVDA's next 12 months. Test the bull and bear cases, identify invalidation conditions, and do not create an order."
        />
        <div className="composer-controls">
          <div className="composer-options">
            <label className="skill-picker">Method
              <select value={props.selectedSkillId} onChange={(event) => props.setSelectedSkillId(event.target.value)}>
                <option value="">Automatic routing</option>
                {props.skills.map((skill) => <option key={skill.id} value={skill.id}>{skill.label}</option>)}
              </select>
            </label>
            <label className="skill-picker">Strategy
              <select value={props.selectedStrategyId} onChange={(event) => props.setSelectedStrategyId(event.target.value)}>
                <option value="">No strategy</option>
                {props.strategies.map((strategy) => <option key={strategy.id} value={strategy.id}>{strategy.label}</option>)}
              </select>
            </label>
            <label className="context-toggle">
              <input type="checkbox" checked={props.useInvestorContext} disabled={!contextConfigured} onChange={(event) => props.setUseInvestorContext(event.target.checked)} />
              <span>Apply investor context<small>{contextConfigured ? "Workspace context" : "Not configured"}</small></span>
            </label>
          </div>
          <div className="composer-actions">
            <span className="key-hint"><kbd>⌘/Ctrl</kbd> + <kbd>Enter</kbd></span>
            <button type="button" onClick={props.makePreview} disabled={props.previewLoading || !props.request.trim()}>
              {props.previewLoading ? "Checking scope…" : "Review scope"}
            </button>
            <button className="primary-button" type="button" onClick={props.startRun} disabled={props.runBusy || !props.previewReady}>
              {props.runBusy ? "Starting…" : "Start analysis"}
            </button>
          </div>
        </div>
        <p className="composer-note">{selectedSkill ? `${selectedSkill.label} is routed through Head Manager. ` : "TradingCodex scopes the eligible team; Head Manager stages the work. "}{selectedStrategy ? `${selectedStrategy.label} is frozen for this run. ` : ""}Analysis does not approve or execute trades.</p>
      </div>

      {props.workError && <ErrorNotice>{props.workError}</ErrorNotice>}
      {props.investorContextError && <ErrorNotice>{props.investorContextError}</ErrorNotice>}
      {props.preview && <ScopePreview payload={props.preview} selectedSkill={selectedSkill} />}
      {!props.preview && !props.run && (
        <div className="first-run">
          <div><strong>Start with a rough question.</strong><span>TradingCodex will make the scope, selected agents, evidence needs, and blocked actions explicit before work begins.</span></div>
          <ul><li>Research with source timestamps</li><li>Contrary evidence and invalidation</li><li>Forecast ranges, not false precision</li></ul>
        </div>
      )}
      {props.run && (
        <RunView
          run={props.run}
          busy={props.runBusy}
          copyToCodex={props.copyToCodex}
          copyNotice={props.copyNotice}
          followUp={props.followUp}
          setFollowUp={props.setFollowUp}
          sendFollowUp={props.sendFollowUp}
          rerun={props.rerun}
          artifactClicked={props.artifactClicked}
        />
      )}
    </section>
  );
}

function ScopePreview({ payload, selectedSkill }: { payload: RecordValue; selectedSkill?: Skill }) {
  const summary = asRecord(payload.intake_summary);
  const strategy = asRecord(payload.strategy_binding);
  const investorContext = asRecord(payload.investor_context_binding);
  const roles = recordsFrom(summary.subagents).map((item) => asText(item.label || item.role)).filter(Boolean);
  const stages = recordsFrom(summary.workflow_stages).map((item) => ({
    label: asText(item.label),
    summary: asText(item.summary),
  }));
  const blocked = recordsFrom(summary.blocked_action_details).map((item) => {
    const label = asText(item.label || item.action);
    const reason = asText(item.reason);
    return [label, reason].filter(Boolean).join(": ");
  }).filter(Boolean);
  const questions = recordsFrom(summary.questions_to_answer).map((item) => asText(item.question)).filter(Boolean);
  return (
    <section className="scope-panel" aria-labelledby="scope-title">
      <div className="section-heading"><div><span className="eyebrow">Scope and constraints</span><h2 id="scope-title">{asText(summary.label, "Workflow preview")}</h2></div><Status value="ready" /></div>
      <div className="scope-grid">
        <div><span className="field-label">Primary question</span><p>{asText(summary.primary_question, "Use the request as the primary question.")}</p></div>
        <div><span className="field-label">Universe</span><p>{asText(summary.investment_universe_label, "To be determined")}</p></div>
        <div><span className="field-label">Selected method</span><p>{selectedSkill?.label || "Automatic routing"}</p></div>
        <div><span className="field-label">Strategy</span><p>{asText(strategy.strategy_id, "No strategy")}{asText(strategy.content_hash) ? ` · ${asText(strategy.content_hash).slice(0, 8)}` : ""}</p></div>
        <div><span className="field-label">Investor context</span><p>{investorContext.applied === true ? `Applied · ${asText(investorContext.content_hash).slice(0, 8)}` : investorContext.configured === true ? "Off for this run" : "Not configured"}</p></div>
        <div><span className="field-label">Selected agents</span><FieldList values={roles} empty="Head Manager only" /></div>
      </div>
      {stages.length > 0 && <ol className="stage-preview">{stages.map((stage, index) => <li key={`${stage.label}-${index}`}><strong>{stage.label}</strong><span>{stage.summary}</span></li>)}</ol>}
      <div className="constraint-grid">
        <div><span className="field-label">Still blocked</span><FieldList values={blocked} /></div>
        <div><span className="field-label">Questions before advice</span><FieldList values={questions} empty="No additional investor-context questions reported" /></div>
      </div>
    </section>
  );
}

function RunView({ run, busy, copyToCodex, copyNotice, followUp, setFollowUp, sendFollowUp, rerun, artifactClicked }: {
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
  const plan = asRecord(raw.plan);
  const state = asRecord(raw.state);
  const pendingTasks = recordsFrom(state.pending_tasks);
  const stages = recordsFrom(plan.stages).map((item, index) => {
    const id = asText(item.stage_id, `stage-${index}`);
    const task = pendingTasks.find((candidate) => asText(candidate.stage_id) === id);
    const gate = asText(task?.stage_gate);
    const fallback = ["complete", "completed", "succeeded"].includes(run.status) ? "completed" : index === 0 ? run.status : "waiting";
    return {
      id,
      label: asText(item.stage_id, `Stage ${index + 1}`).replaceAll("_", " "),
      detail: asText(item.purpose),
      status: gate === "complete" ? "completed" : asText(task?.status || task?.process_status || task?.stage_gate, fallback),
    };
  });
  const agents = recordsFrom(raw.agents).map((item) => ({
    name: asText(item.label || item.role, "Agent"),
    role: asText(item.role),
    status: asText(item.status, "selected"),
  }));
  const activity = recordsFrom(raw.activity).map((item) => ({
    kind: asText(item.item_type || item.type, "update"),
    label: asText(item.tool_name || item.type, "Progress update"),
    status: asText(item.status, "recorded"),
    at: asText(item.ts),
  }));
  const artifacts = recordsFrom(raw.artifacts).map((item, index) => normalizeArtifact(item, index));
  const output = asRecord(raw.final_output);
  const outputText = asText(output.reader_summary);
  const outputHtml = asText(asRecord(output.preview).html);
  const forecasts = recordsFrom(raw.forecasts);
  const runError = asText(asRecord(raw.error).message);
  const active = !TERMINAL_RUN_STATES.has(run.status);
  return (
    <section className="run-view" aria-labelledby="run-title">
      <div className="section-heading run-heading">
        <div><span className="eyebrow">Run {run.id}</span><h2 id="run-title">Analysis progress</h2></div>
        <div className="heading-actions"><Status value={run.status} />{active && <span className="polling">Polling</span>}</div>
      </div>
      {runError && <ErrorNotice>{runError}</ErrorNotice>}
      {["waiting", "revise", "revision_required", "blocked", "lane_escalation_proposal"].includes(run.status) && (
        <div className={`notice ${run.status === "blocked" ? "notice-error" : "notice-warn"}`} role="status">
          <strong>{run.status === "blocked" ? "Work is blocked." : run.status === "lane_escalation_proposal" ? "Scope expansion needs review." : run.status.startsWith("revis") ? "Revision requested." : "Waiting for input or a handoff."}</strong>
          <span>{asText(state.stop_reason || raw.stop_reason, "Review the latest activity and respond with a focused follow-up.")}</span>
        </div>
      )}
      <div className="progress-layout">
        <section className="progress-column" aria-labelledby="stages-title">
          <h3 id="stages-title">Stages</h3>
          {stages.length ? <ol className="run-stages">{stages.map((stage) => <li key={stage.id} data-status={statusTone(stage.status)}><span className="stage-marker" /><div><strong>{stage.label}</strong><span>{stage.detail}</span></div><Status value={stage.status} /></li>)}</ol> : <Empty title="Planning">Stage detail will appear when the run records its plan.</Empty>}
        </section>
        <section className="agent-column" aria-labelledby="agents-title">
          <h3 id="agents-title">Agents</h3>
          <div className="agent-list">{agents.map((agent, index) => <div className="agent-row" key={`${agent.role}-${index}`}><div><strong>{agent.name}</strong><span>{agent.role}</span></div><Status value={agent.status} /></div>)}{!agents.length && <span className="muted">Waiting for dispatch.</span>}</div>
        </section>
      </div>
      <section className="activity-section" aria-labelledby="activity-title">
        <h3 id="activity-title">Tools, sources, and handoffs</h3>
        <div className="activity-stream">
          {activity.map((item, index) => <div className="activity-row" key={`${item.label}-${index}`}><span className="activity-kind">{item.kind}</span><div><strong>{item.label}</strong></div><div><Status value={item.status} /><time>{formatDate(item.at)}</time></div></div>)}
          {!activity.length && <Empty title="No activity recorded yet">Tool names, sources, and intermediate handoffs will be listed here without exposing private reasoning.</Empty>}
        </div>
      </section>
      {artifacts.length > 0 && <section className="artifact-strip" aria-labelledby="run-artifacts"><h3 id="run-artifacts">Intermediate artifacts</h3><div>{artifacts.map((artifact) => <button key={artifact.id} type="button" onClick={() => artifactClicked(artifact.id)}><strong>{artifact.title}</strong><span>{artifact.type} · {artifact.readiness}</span></button>)}</div></section>}
      {(outputHtml || outputText || forecasts.length > 0) && (
        <section className="final-result" aria-labelledby="result-title">
          <div className="section-heading"><div><span className="eyebrow">Synthesis</span><h3 id="result-title">Final analysis</h3></div><Status value={run.status} /></div>
          {outputHtml ? <div className="rendered-content" dangerouslySetInnerHTML={{ __html: outputHtml }} /> : outputText && <div className="plain-output">{outputText}</div>}
          {forecasts.map((forecast, index) => <ForecastView key={firstText(forecast, ["forecast_id", "event_id"], String(index))} forecast={forecast} />)}
        </section>
      )}
      <div className="run-actions">
        <button type="button" onClick={rerun} disabled={busy}>Rerun with changes</button>
        <button type="button" onClick={copyToCodex}>Copy to Codex</button>
        {copyNotice && <span className="copy-notice" role="status">{copyNotice}</span>}
      </div>
      <form className="follow-up" onSubmit={sendFollowUp}>
        <label htmlFor="follow-up">Request a revision or ask a follow-up</label>
        <div><input id="follow-up" value={followUp} onChange={(event) => setFollowUp(event.target.value)} placeholder="Challenge an assumption, narrow the horizon, or request more evidence" /><button className="primary-button" type="submit" disabled={busy || !followUp.trim()}>Send</button></div>
      </form>
    </section>
  );
}

function ForecastView({ forecast }: { forecast: RecordValue }) {
  const probabilityValue = forecast.probability ?? forecast.probability_range ?? forecast.probabilities ?? forecast.prediction ?? forecast.interval ?? forecast.quantiles ?? forecast.range ?? forecast.estimate;
  const probability = formatForecastValue(probabilityValue);
  const baseRate = asRecord(forecast.base_rate);
  const assumptions = asStringList(forecast.assumptions || forecast.premises);
  if (!assumptions.length && Object.keys(baseRate).length) {
    assumptions.push(Object.entries(baseRate).map(([key, value]) => `${key}: ${asText(value, "not stated")}`).join(" · "));
  }
  return <section className="forecast">
    <h4>{firstText(forecast, ["forecast_target"], "Forecast discipline")}</h4>
    <div className="forecast-grid">
      <div><span>Horizon</span><strong>{firstText(forecast, ["horizon", "time_horizon", "period"], "Not stated")}</strong></div>
      <div><span>Probability or range</span><strong>{probability || "Not stated"}</strong></div>
      <div><span>Assumptions / base rate</span><FieldList values={assumptions} /></div>
      <div><span>Key variables / update triggers</span><FieldList values={asStringList(forecast.key_variables || forecast.drivers || forecast.update_triggers)} /></div>
      <div><span>Contrary evidence</span><FieldList values={asStringList(forecast.contrary_evidence || forecast.counterevidence || forecast.bear_case)} /></div>
      <div><span>Invalidation conditions</span><FieldList values={asStringList(forecast.invalidation_conditions || forecast.falsifiers || forecast.invalidation)} /></div>
      <div><span>Knowledge cutoff</span><strong>{firstText(forecast, ["knowledge_cutoff", "source_as_of"], "Not stated")}</strong></div>
      <div><span>Resolution rule</span><strong>{firstText(forecast, ["resolution_rule", "resolution_source"], "Not stated")}</strong></div>
    </div>
  </section>;
}

function formatForecastValue(value: unknown): string {
  if (Array.isArray(value)) return value.map((item) => asText(item)).filter(Boolean).join(" – ");
  if (value !== null && typeof value === "object") {
    const record = asRecord(value);
    const lower = firstText(record, ["lower", "low", "min", "p10", "p05"]);
    const upper = firstText(record, ["upper", "high", "max", "p90", "p95"]);
    if (lower || upper) return [lower, upper].filter(Boolean).join(" – ");
    return Object.entries(record)
      .map(([key, item]) => `${key.replaceAll("_", " ")}: ${asText(item)}`)
      .filter((item) => !item.endsWith(": "))
      .join(" · ");
  }
  return asText(value);
}

function SkillsSection({ state, skills, error, selectedSkillId, refreshState, selectForWork }: { state: RecordValue; skills: Skill[]; error: string; selectedSkillId: string; refreshState: () => Promise<void>; selectForWork: (id: string) => void }) {
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState(selectedSkillId);
  const [detail, setDetail] = useState<RecordValue>({});
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [mutationNotice, setMutationNotice] = useState("");
  const strategies = recordsFrom(sectionData(state, "strategies"));
  const optionalSkills = recordsFrom(sectionData(state, "optional_skills"), "optional_skills");
  const strategyError = sectionError(state, "strategies");
  const optionalError = sectionError(state, "optional_skills");
  const agents = recordsFrom(sectionData(state, "agents"));
  const roles = agents.map((item) => asText(item.role)).filter((role) => role && role !== "head-manager");
  const filtered = skills.filter((skill) => matchesSearch([skill.label, skill.id, skill.description, skill.owner, skill.kind], query));
  const selected = skills.find((skill) => skill.id === selectedId) || filtered[0];

  useEffect(() => {
    if (!selected?.id) return;
    let current = true;
    setDetail({});
    setDetailLoading(true);
    setDetailError("");
    void requestJSON<unknown>(`/api/workbench/skills/${encodeURIComponent(selected.id)}/`)
      .then((payload) => { if (current) setDetail(asRecord(payload)); })
      .catch((reason) => { if (current) setDetailError(apiErrorText(reason)); })
      .finally(() => { if (current) setDetailLoading(false); });
    return () => { current = false; };
  }, [selected?.id]);

  const manage = async (action: () => Promise<unknown>, success: string) => {
    setMutationNotice("");
    try {
      await action();
      setMutationNotice(success);
      await refreshState();
    } catch (reason) {
      setMutationNotice(apiErrorText(reason));
    }
  };
  const createStrategy = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    void manage(() => mutation("/api/harness/strategies", "POST", {
      name: String(data.get("name") || ""),
      description: String(data.get("description") || ""),
      body: String(data.get("body") || ""),
      status: "draft",
    }), "Strategy draft saved. Review it before activation.");
  };
  const createOptional = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const role = String(data.get("role") || "");
    void manage(() => mutation(`/api/subagents/${encodeURIComponent(role)}/optional-skills`, "POST", {
      name: String(data.get("name") || ""),
      description: String(data.get("description") || ""),
      body: String(data.get("body") || ""),
      status: "active",
    }), "Optional skill saved.");
  };

  const detailHtml = asText(asRecord(detail.preview).html);
  return <section className="page skills-page" aria-labelledby="skills-title">
    <div className="page-heading"><div><span className="eyebrow">Method library</span><h1 id="skills-title">Skills</h1><p>Choose work by outcome. Head Manager retains routing and role boundaries.</p></div><span className="count">{skills.length} built in</span></div>
    {error && <ErrorNotice>{error}</ErrorNotice>}
    <div className="skill-layout">
      <aside className="skill-index">
        <label htmlFor="skill-search">Search skills</label><input id="skill-search" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Evidence, valuation, forecast…" />
        <div className="skill-list">{filtered.map((skill) => <button key={skill.id} type="button" className={selected?.id === skill.id ? "selected" : ""} onClick={() => setSelectedId(skill.id)}><strong>{skill.label}</strong><span>{skill.owner} · {skill.kind}</span></button>)}{!filtered.length && <Empty title="No matching skills">Try a broader task or role.</Empty>}</div>
      </aside>
      <article className="skill-detail">
        {selected ? <>
          <div className="section-heading"><div><span className="eyebrow">{selected.kind}</span><h2>{selected.label}</h2></div><Status value={selected.status} /></div>
          <p className="lead">{selected.description || "A built-in TradingCodex analysis method."}</p>
          <dl className="boundary-list"><div><dt>Owner</dt><dd>{selected.owner}</dd></div><div><dt>Invocation</dt><dd>Selected by the user, dispatched through Head Manager</dd></div><div><dt>Boundary</dt><dd>{selected.boundary}</dd></div></dl>
          {detailLoading && <span className="muted">Loading skill details…</span>}
          {detailError && <ErrorNotice>{detailError}</ErrorNotice>}
          {detailHtml && <div className="rendered-content compact" dangerouslySetInnerHTML={{ __html: detailHtml }} />}
          {selected.startable
            ? <button className="primary-button" type="button" onClick={() => selectForWork(selected.id)}>{selected.kind === "strategy" ? "Use as Work strategy" : "Use through Head Manager"}</button>
            : selected.protectedAction
              ? <div className="notice notice-warn"><strong>Protected action.</strong><span>This skill stays outside the analysis workbench because it can reach approval, execution, secrets, or another protected boundary.</span></div>
              : <div className="notice"><strong>Use in Codex.</strong><span>Invoke <code>${selected.id}</code> in Codex. This management skill is intentionally separate from starting an analysis run.</span></div>}
        </> : <Empty title="Select a skill">Choose a task from the library.</Empty>}
      </article>
    </div>

    <section className="extensions" aria-labelledby="extensions-title">
      <div className="section-heading"><div><span className="eyebrow">Managed overlays</span><h2 id="extensions-title">Custom strategies and optional skills</h2></div></div>
      <p className="boundary-copy">Extensions can guide analysis. They cannot change agent identity, permissions, policy, approval authority, or execution authority.</p>
      {mutationNotice && <div className="notice" role="status">{mutationNotice}</div>}
      <div className="extension-grid">
        <div>
          <div className="subheading"><h3>Strategies</h3><span>{strategies.length}</span></div>
          {strategyError && <ErrorNotice>{strategyError}</ErrorNotice>}
          <div className="extension-list">{strategies.map((item) => {
            const name = asText(item.name); const status = asText(item.status, "draft");
            return <div key={name}><div><strong>{asText(item.label, name)}</strong><span>{asText(item.description)}</span></div><div><Status value={status} /><button type="button" onClick={() => void manage(() => mutation(`/api/harness/strategies/${encodeURIComponent(name)}/${status === "active" ? "archive" : "activate"}`, "POST"), `Strategy ${status === "active" ? "archived" : "activated"}.`)}>{status === "active" ? "Archive" : "Activate"}</button></div></div>;
          })}{!strategies.length && !strategyError && <span className="muted">No custom strategies.</span>}</div>
          <details><summary>Create strategy draft</summary><form className="compact-form" onSubmit={createStrategy}><label>Name<input name="name" required pattern="strategy-[a-z0-9]+(?:-[a-z0-9]+)*" placeholder="strategy-quality-watch" /></label><label>Description<input name="description" required /></label><label>Instructions<textarea name="body" rows={5} required /></label><button className="primary-button" type="submit">Save draft</button></form></details>
        </div>
        <div>
          <div className="subheading"><h3>Optional role skills</h3><span>{optionalSkills.length}</span></div>
          {optionalError && <ErrorNotice>{optionalError}</ErrorNotice>}
          <div className="extension-list">{optionalSkills.map((item, index) => {
            const name = asText(item.name, `skill-${index}`); const role = asText(item.role); const status = asText(item.status, "draft");
            return <div key={`${role}-${name}`}><div><strong>{name}</strong><span>{role}</span></div><div><Status value={status} />{role && <button type="button" onClick={() => void manage(() => mutation(`/api/subagents/${encodeURIComponent(role)}/optional-skills/${encodeURIComponent(name)}/${status === "active" ? "archive" : "activate"}`, "POST"), `Optional skill ${status === "active" ? "archived" : "activated"}.`)}>{status === "active" ? "Archive" : "Activate"}</button>}</div></div>;
          })}{!optionalSkills.length && !optionalError && <span className="muted">No optional skills.</span>}</div>
          <details><summary>Create optional skill</summary>{roles.length ? <form className="compact-form" onSubmit={createOptional}><label>Role<select name="role">{roles.map((role) => <option key={role}>{role}</option>)}</select></label><label>Name<input name="name" required pattern="[a-z0-9]+(?:-[a-z0-9]+)*" /></label><label>Description<input name="description" required /></label><label>Instructions<textarea name="body" rows={5} required /></label><button className="primary-button" type="submit">Save optional skill</button></form> : <p className="muted">Agent roles are unavailable; refresh the workbench before creating an optional skill.</p>}</details>
        </div>
      </div>
      <p className="auth-note">Changes require an authenticated staff session. If editing is denied, sign in through <a href="/admin/login/?next=/">Django Admin</a> and retry.</p>
    </section>
  </section>;
}

function LibrarySection({ artifacts, error }: { artifacts: Artifact[]; error: string }) {
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState(() => sessionStorage.getItem("tcx-selected-artifact") || "");
  const [detail, setDetail] = useState<RecordValue>({});
  const [detailError, setDetailError] = useState("");
  const filtered = artifacts.filter((artifact) => matchesSearch([artifact.title, artifact.id, artifact.type, artifact.summary, artifact.readiness], query));
  const selected = artifacts.find((artifact) => artifact.id === selectedId) || null;
  useEffect(() => { if (selectedId) sessionStorage.removeItem("tcx-selected-artifact"); }, [selectedId]);
  useEffect(() => {
    if (!selectedId) return;
    let current = true;
    setDetail({});
    setDetailError("");
    void requestJSON<unknown>(`/api/workbench/artifacts/${encodeURIComponent(selectedId)}/`)
      .then((payload) => { if (current) setDetail(asRecord(payload)); })
      .catch((reason) => { if (current) setDetailError(apiErrorText(reason)); });
    return () => { current = false; };
  }, [selectedId]);
  const preview = asRecord(detail.preview);
  const html = asText(preview.html);
  return <section className="page library-page" aria-labelledby="library-title">
    <div className="page-heading"><div><span className="eyebrow">Workspace evidence</span><h1 id="library-title">Library</h1><p>Review source timing, readiness, uncertainty, and missing evidence before relying on a result.</p></div><span className="count">{artifacts.length} artifacts</span></div>
    {error && <ErrorNotice>{error}</ErrorNotice>}
    <label className="library-search" htmlFor="library-search">Search library<input id="library-search" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Symbol, title, artifact type…" /></label>
    <div className="library-layout">
      <div className="artifact-list">{filtered.map((artifact) => <button key={artifact.id} type="button" className={selected?.id === artifact.id ? "selected" : ""} onClick={() => setSelectedId(artifact.id)}><div><strong>{artifact.title}</strong><span>{artifact.summary}</span></div><div><Status value={artifact.readiness} /><small>{artifact.type}</small><time>{artifact.sourceAsOf ? `as of ${formatDate(artifact.sourceAsOf)}` : "source date missing"}</time></div></button>)}{!filtered.length && <Empty title="No artifacts found">Completed research, evidence cards, and synthesis reports will appear here.</Empty>}</div>
      <article className="artifact-detail">
        {selected ? <>
          <div className="section-heading"><div><span className="eyebrow">{selected.type}</span><h2>{selected.title}</h2></div><Status value={selected.readiness} /></div>
          <dl className="artifact-meta"><div><dt>Source as of</dt><dd>{selected.sourceAsOf ? formatDate(selected.sourceAsOf) : "Missing"}</dd></div><div><dt>Confidence</dt><dd>{selected.confidence}</dd></div><div><dt>Artifact ID</dt><dd><code>{selected.id}</code></dd></div></dl>
          {selected.missingEvidence.length > 0 && <div className="notice notice-warn"><strong>Missing evidence</strong><FieldList values={selected.missingEvidence} /></div>}
          {detailError && <ErrorNotice>{detailError}</ErrorNotice>}
          {html ? <div className="rendered-content" dangerouslySetInnerHTML={{ __html: html }} /> : <p>{selected.summary || "Loading sanitized preview…"}</p>}
        </> : <Empty title="Select an artifact">The preview uses backend-sanitized HTML; raw workspace markdown is not rendered in the browser.</Empty>}
      </article>
    </div>
  </section>;
}

function SystemSection({ state, error }: { state: RecordValue; error: string }) {
  const workspaceSection = asRecord(sectionData(state, "workspace"));
  const workspaceContext = asRecord(workspaceSection.context);
  const options = recordsFrom(workspaceSection.options);
  const accountScope = asRecord(workspaceSection.profile);
  const investorContext = asRecord(sectionData(state, "investor_context"));
  const brokers = recordsFrom(sectionData(state, "brokers"), "connections");
  const permissions = recordsFrom(sectionData(state, "permissions"), "requests");
  const orders = recordsFrom(sectionData(state, "orders"), "tickets");
  const selectWorkspace = (id: string) => {
    if (!id) return;
    const url = new URL(window.location.href);
    url.searchParams.set("workspace", id);
    window.location.assign(`${url.pathname}${url.search}${url.hash || hashForSection("system")}`);
  };
  return <section className="page system-page" aria-labelledby="system-title">
    <div className="page-heading"><div><span className="eyebrow">Local service plane</span><h1 id="system-title">System</h1><p>Workspace context and execution-sensitive state remain owned by Django services.</p></div><a className="button-link" href="/admin/">Open Admin</a></div>
    {error && <ErrorNotice>{error}</ErrorNotice>}
    <section className="system-section"><div className="section-heading"><h2>Workspace</h2><Status value={firstText(workspaceContext, ["status", "status_label"], "local")} /></div><dl className="system-grid"><div><dt>Project</dt><dd>{firstText(workspaceContext, ["project_name", "label", "name"], "Local workspace")}</dd></div><div><dt>Path</dt><dd><code>{firstText(workspaceContext, ["path", "root"], "Not reported")}</code></dd></div><div><dt>Paper account</dt><dd>{firstText(accountScope, ["account_id", "label"], "Workspace paper account")}</dd></div><div><dt>Account scope</dt><dd>{isSharedAccountScope(accountScope) ? "Shared legacy scope" : "This workspace"}</dd></div><div><dt>Base currency</dt><dd>{firstText(accountScope, ["base_currency"], "Not reported")}</dd></div><div><dt>Investor context</dt><dd>{investorContext.configured === true ? investorContext.enabled_by_default === false ? "Configured · off by default" : "Configured · on by default" : "Not configured"}</dd></div></dl>{options.length > 1 && <label className="workspace-switch">Switch workspace<select value={firstText(workspaceContext, ["workspace_id", "id"])} onChange={(event) => selectWorkspace(event.target.value)}>{options.map((item) => { const id = firstText(item, ["workspace_id", "id"]); return <option key={id} value={id}>{firstText(item, ["project_name", "label", "name"], id)}</option>; })}</select></label>}</section>
    <div className="system-columns">
      <section className="system-section"><div className="section-heading"><h2>Broker posture</h2><span className="count">{brokers.length}</span></div><div className="system-list">{brokers.map((item, index) => <div key={firstText(item, ["broker_id", "id"], String(index))}><div><strong>{firstText(item, ["display_name", "label", "broker_id"], "Broker")}</strong><span>{firstText(item, ["environment", "mode", "adapter_type"], "local")}</span></div><Status value={firstText(item, ["status", "last_status", "connection_status"], "unknown")} /></div>)}{!brokers.length && <span className="muted">No broker connections reported.</span>}</div></section>
      <section className="system-section"><div className="section-heading"><h2>Permission requests</h2><span className="count">{permissions.length}</span></div><div className="system-list">{permissions.map((item, index) => {
        const tool = [asText(item.router_name), asText(item.external_name)].filter(Boolean).join(":");
        return <div key={asText(item.id, String(index))}><div><strong>{tool || "Permission request"}</strong><span>{asStringList(item.reasons).join(" · ")}</span></div><Status value={asText(item.status, "pending")} /></div>;
      })}{!permissions.length && <span className="muted">No pending permission requests.</span>}</div></section>
      <section className="system-section"><div className="section-heading"><h2>Order state</h2><span className="count">{orders.length}</span></div><div className="system-list">{orders.slice(0, 8).map((item, index) => <div key={firstText(item, ["ticket_id", "id"], String(index))}><div><strong>{firstText(item, ["symbol", "title", "ticket_id"], "Order ticket")}</strong><span>{[firstText(item, ["side"]), firstText(item, ["quantity"])].filter(Boolean).join(" ")}</span></div><Status value={firstText(item, ["current_state", "status"], "draft")} /></div>)}{!orders.length && <span className="muted">No order tickets in this account scope.</span>}</div></section>
    </div>
    <section className="safety-boundary" aria-labelledby="safety-title"><span className="eyebrow">Non-negotiable boundary</span><h2 id="safety-title">Analysis is not execution</h2><p>This workbench can start analysis, inspect evidence, and request revisions. It does not approve orders, submit trades, reveal credentials, or bypass policy, idempotency, connection, and audit checks.</p><div><span>Live execution</span><Status value="disabled by default" /></div></section>
  </section>;
}
