import { FormEvent, ReactNode, useEffect, useMemo, useRef, useState } from "react";

import { apiErrorText, mutation, requestJSON } from "../api";
import { asRecord, asText, recordsFrom, sectionError, Skill, titleCase } from "../domain";
import { EmptyState, ErrorNotice, LoadingState, Notice, PageHeader, SectionHeader, StatusPill } from "../ui";
import { collectionViewState, sectionData } from "../workbench-data.js";

type SkillsPageProps = {
  state: Record<string, unknown>;
  skills: Skill[];
  error: string;
  selectedSkillId: string;
  loading: boolean;
  refreshState: () => Promise<void>;
  selectForWork: (id: string) => void;
};

export function SkillsPage({ state, skills, error, selectedSkillId, loading, refreshState, selectForWork }: SkillsPageProps) {
  const [view, setView] = useState<"methods" | "extensions">("methods");
  const methodState = collectionViewState({ loading, error, count: skills.length });
  return <section className="page skills-page" aria-labelledby="skills-title">
    <PageHeader eyebrow="Research approaches" title="Methods that sharpen the question." titleId="skills-title" description="Use a method to guide analysis. Head Manager still owns routing, specialist choice, and evidence synthesis." action={<span className="page-count">{skills.length}<small>available</small></span>} />
    <div className="local-tabs" role="tablist" aria-label="Approach views"><button type="button" role="tab" aria-selected={view === "methods"} className={view === "methods" ? "active" : ""} onClick={() => setView("methods")}>Methods</button><button type="button" role="tab" aria-selected={view === "extensions"} className={view === "extensions" ? "active" : ""} onClick={() => setView("extensions")}>Strategies & extensions</button></div>
    {error && <ErrorNotice>{error}</ErrorNotice>}
    {view === "methods" ? methodState === "error" ? null : <MethodCatalog skills={skills} selectedSkillId={selectedSkillId} loading={methodState === "loading"} selectForWork={selectForWork} /> : <ExtensionManager state={state} refreshState={refreshState} />}
  </section>;
}

function MethodCatalog({ skills, selectedSkillId, loading, selectForWork }: { skills: Skill[]; selectedSkillId: string; loading: boolean; selectForWork: (id: string) => void }) {
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState(selectedSkillId);
  const [detailOpen, setDetailOpen] = useState(Boolean(selectedSkillId));
  const [detail, setDetail] = useState<Record<string, unknown>>({});
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const indexRef = useRef<HTMLElement>(null);
  const detailRef = useRef<HTMLElement>(null);
  const filtered = useMemo(() => skills.filter((skill) => [skill.label, skill.id, skill.description, skill.owner, skill.kind].join(" ").toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())), [query, skills]);
  const selected = skills.find((skill) => skill.id === selectedId) || filtered[0] || null;

  useEffect(() => {
    if (!selected?.id) return;
    const controller = new AbortController();
    setDetail({});
    setDetailError("");
    setDetailLoading(true);
    void requestJSON<unknown>(`/api/workbench/skills/${encodeURIComponent(selected.id)}/`, { signal: controller.signal })
      .then((payload) => setDetail(asRecord(payload)))
      .catch((reason) => { if (!controller.signal.aborted) setDetailError(apiErrorText(reason)); })
      .finally(() => { if (!controller.signal.aborted) setDetailLoading(false); });
    return () => controller.abort();
  }, [selected?.id]);

  const choose = (skill: Skill) => {
    setSelectedId(skill.id);
    setDetailOpen(true);
    requestAnimationFrame(() => detailRef.current?.scrollIntoView({ block: "start" }));
  };
  if (loading && !skills.length) return <LoadingState label="Loading research methods…" />;
  if (!skills.length) return <EmptyState title="No methods are available">Check the generated skill projection and refresh the workbench.</EmptyState>;
  const detailHtml = asText(asRecord(detail.preview).html);

  return <div className={`method-layout${detailOpen ? " detail-open" : ""}`}>
    <aside ref={indexRef} className="method-index" aria-label="Research methods"><label><span className="sr-only">Search methods</span><input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search evidence, valuation, risk…" /></label><div className="method-list">{filtered.map((skill) => <button key={skill.id} type="button" className={selected?.id === skill.id ? "method-row selected" : "method-row"} aria-pressed={selected?.id === skill.id} onClick={() => choose(skill)}><span className="method-owner">{titleCase(skill.kind)} · {titleCase(skill.owner)}</span><strong>{skill.label}</strong><p>{skill.description || "A TradingCodex research method."}</p><span className="method-capability">{skill.startable ? "Available in Work" : skill.protectedAction ? "Protected action" : "Native Codex"}</span></button>)}{!filtered.length && <EmptyState title="No matching methods">Try a broader research outcome.</EmptyState>}</div></aside>
    <article ref={detailRef} className="method-detail" aria-busy={detailLoading}><button type="button" className="mobile-back" onClick={() => { setDetailOpen(false); requestAnimationFrame(() => indexRef.current?.scrollIntoView({ block: "start" })); }}>← Back to methods</button>{selected ? <><header><div className="reader-kicker"><span>{titleCase(selected.kind)}</span><StatusPill value={selected.status} /></div><h2>{selected.label}</h2><p className="reader-summary">{selected.description || "A built-in TradingCodex research method."}</p></header><section className="method-answers"><div><span className="eyebrow">Best for</span><p>{bestFor(selected)}</p></div><div><span className="eyebrow">Owned by</span><p>{titleCase(selected.owner)}</p></div><div><span className="eyebrow">Authority boundary</span><p>{selected.boundary}</p></div></section>{detailError && <ErrorNotice>{detailError}</ErrorNotice>}{detailLoading ? <LoadingState label="Loading method guidance…" compact /> : detailHtml && <details className="method-guidance"><summary>Read method guidance</summary><div className="rendered-content compact" dangerouslySetInnerHTML={{ __html: detailHtml }} /></details>}{selected.startable ? <button className="primary-button method-cta" type="button" onClick={() => selectForWork(selected.id)}>Use this method in Work <span aria-hidden="true">→</span></button> : selected.protectedAction ? <Notice title="Protected capability" tone="warn">This method can reach approval, execution, secrets, or another protected boundary, so it cannot start from the analysis workbench.</Notice> : <Notice title="Available in native Codex">Invoke <code>${selected.id}</code> from a Codex task. It is intentionally separate from starting an analysis run here.</Notice>}</> : <EmptyState title="Choose a method">Select a research outcome to see how it is used.</EmptyState>}</article>
  </div>;
}

function bestFor(skill: Skill): string {
  const source = `${skill.id} ${skill.label}`.toLowerCase();
  if (source.includes("evidence") || source.includes("source")) return "Finding, authenticating, and challenging evidence before it enters a decision.";
  if (source.includes("forecast")) return "Expressing uncertainty with horizons, ranges, base rates, and explicit update conditions.";
  if (source.includes("valuation")) return "Testing assumptions and valuation ranges without creating false precision.";
  if (source.includes("risk")) return "Identifying invalidation conditions, exposure, and evidence gaps.";
  if (source.includes("memory")) return "Recording durable decisions and learning from prior judgments.";
  return "Adding a focused analytical discipline to a Head Manager-led research task.";
}

function ExtensionManager({ state, refreshState }: { state: Record<string, unknown>; refreshState: () => Promise<void> }) {
  const [notice, setNotice] = useState<{ tone: "good" | "bad"; text: string } | null>(null);
  const strategies = recordsFrom(sectionData(state, "strategies"));
  const optionalSkills = recordsFrom(sectionData(state, "optional_skills"), "optional_skills");
  const agents = recordsFrom(sectionData(state, "agents"));
  const roles = agents.map((item) => asText(item.role)).filter((role) => role && role !== "head-manager");
  const manage = async (action: () => Promise<unknown>, success: string) => {
    setNotice(null);
    try { await action(); setNotice({ tone: "good", text: success }); await refreshState(); }
    catch (reason) { setNotice({ tone: "bad", text: apiErrorText(reason) }); }
  };
  const createStrategy = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const form = event.currentTarget; const data = new FormData(form);
    void manage(() => mutation("/api/harness/strategies", "POST", { name: String(data.get("name") || ""), description: String(data.get("description") || ""), body: String(data.get("body") || ""), status: "draft" }), "Strategy draft saved. Review it before activation.").then(() => form.reset());
  };
  const createOptional = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const form = event.currentTarget; const data = new FormData(form); const role = String(data.get("role") || "");
    void manage(() => mutation(`/api/subagents/${encodeURIComponent(role)}/optional-skills`, "POST", { name: String(data.get("name") || ""), description: String(data.get("description") || ""), body: String(data.get("body") || ""), status: "active" }), "Optional role skill saved.").then(() => form.reset());
  };
  return <section className="extensions-view" aria-labelledby="extensions-title"><div className="extensions-intro"><div><span className="eyebrow">Workspace overlays</span><h2 id="extensions-title">Adapt the method, never the authority.</h2><p>Strategies and optional role skills can guide analysis. They cannot change agent identity, permissions, policy, approval authority, or execution authority.</p></div><aside><strong>Investment Brain</strong><p>Brain-backed work starts in native Codex. This workbench intentionally does not imitate or override that selection.</p></aside></div>{notice && <Notice title={notice.tone === "good" ? "Change saved" : "Change not saved"} tone={notice.tone}>{notice.text}</Notice>}<div className="extension-columns"><ExtensionList title="Strategies" count={strategies.length} error={sectionError(state, "strategies")} empty="No custom strategies are installed.">{strategies.map((item) => { const name = asText(item.name, asText(item.id)); const status = asText(item.status, "draft"); return <div className="extension-row" key={name}><div><strong>{asText(item.label, titleCase(name))}</strong><span>{asText(item.description, "Workspace strategy overlay")}</span></div><div><StatusPill value={status} /><button type="button" onClick={() => void manage(() => mutation(`/api/harness/strategies/${encodeURIComponent(name)}/${status === "active" ? "archive" : "activate"}`, "POST"), `Strategy ${status === "active" ? "archived" : "activated"}.`)}>{status === "active" ? "Archive" : "Activate"}</button></div></div>; })}<details className="create-extension"><summary>Create a strategy draft</summary><form onSubmit={createStrategy}><label>Name<input name="name" required pattern="strategy-[a-z0-9]+(?:-[a-z0-9]+)*" placeholder="strategy-quality-watch" /></label><label>Description<input name="description" required /></label><label>Instructions<textarea name="body" rows={6} required /></label><button className="primary-button" type="submit">Save draft</button></form></details></ExtensionList><ExtensionList title="Optional role skills" count={optionalSkills.length} error={sectionError(state, "optional_skills")} empty="No optional role skills are installed.">{optionalSkills.map((item, index) => { const name = asText(item.name, `skill-${index}`); const role = asText(item.role); const status = asText(item.status, "draft"); return <div className="extension-row" key={`${role}-${name}`}><div><strong>{titleCase(name)}</strong><span>{titleCase(role)}</span></div><div><StatusPill value={status} />{role && <button type="button" onClick={() => void manage(() => mutation(`/api/subagents/${encodeURIComponent(role)}/optional-skills/${encodeURIComponent(name)}/${status === "active" ? "archive" : "activate"}`, "POST"), `Optional skill ${status === "active" ? "archived" : "activated"}.`)}>{status === "active" ? "Archive" : "Activate"}</button>}</div></div>; })}<details className="create-extension"><summary>Create an optional role skill</summary>{roles.length ? <form onSubmit={createOptional}><label>Role<select name="role">{roles.map((role) => <option key={role}>{role}</option>)}</select></label><label>Name<input name="name" required pattern="[a-z0-9]+(?:-[a-z0-9]+)*" /></label><label>Description<input name="description" required /></label><label>Instructions<textarea name="body" rows={6} required /></label><button className="primary-button" type="submit">Save optional skill</button></form> : <p className="muted">Agent roles are unavailable. Refresh the workbench first.</p>}</details></ExtensionList></div><p className="auth-note">Changes require an authenticated staff session. Sign in through <a href="/admin/login/?next=/">Django Admin</a> if a mutation is denied.</p></section>;
}

function ExtensionList({ title, count, error, empty, children }: { title: string; count: number; error: string; empty: string; children: ReactNode }) {
  return <section className="extension-section"><SectionHeader title={title} aside={<span className="count">{count}</span>} />{error && <ErrorNotice>{error}</ErrorNotice>}<div className="extension-list">{count ? children : !error && <p className="muted">{empty}</p>}</div></section>;
}
