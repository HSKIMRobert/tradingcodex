import { ReactNode } from "react";

import { formatDate, statusTone } from "./domain";

export function ErrorNotice({ children, retry }: { children: ReactNode; retry?: () => void }) {
  return <div className="notice notice-error" role="alert"><div><strong>Something needs attention</strong><span>{children}</span></div>{retry && <button type="button" onClick={retry}>Retry</button>}</div>;
}

export function Notice({ title, children, tone = "neutral" }: { title: string; children: ReactNode; tone?: "neutral" | "warn" | "bad" | "good" }) {
  return <div className={`notice notice-${tone}`} role="status"><div><strong>{title}</strong><span>{children}</span></div></div>;
}

export function EmptyState({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <div className="empty-state"><span className="empty-mark" aria-hidden="true">◇</span><div><strong>{title}</strong><span>{children}</span></div>{action}</div>;
}

export function LoadingState({ label = "Loading…", compact = false }: { label?: string; compact?: boolean }) {
  return <div className={`loading-state${compact ? " loading-compact" : ""}`} role="status" aria-live="polite"><span className="loading-mark" aria-hidden="true" /><span>{label}</span></div>;
}

export function StatusPill({ value }: { value: string }) {
  return <span className={`status-pill status-${statusTone(value)}`}>{value.replaceAll("_", " ")}</span>;
}

export function FieldList({ values, empty = "None reported" }: { values: string[]; empty?: string }) {
  if (!values.length) return <span className="muted">{empty}</span>;
  return <ul className="field-list">{values.map((value, index) => <li key={`${value}-${index}`}>{value}</li>)}</ul>;
}

export function MetaTime({ value, prefix = "" }: { value: string; prefix?: string }) {
  if (!value) return <span>Not stated</span>;
  const date = new Date(value);
  return <time dateTime={Number.isNaN(date.valueOf()) ? undefined : date.toISOString()}>{prefix}{formatDate(value)}</time>;
}

export function PageHeader({ eyebrow, title, titleId, description, action }: { eyebrow: string; title: string; titleId?: string; description?: string; action?: ReactNode }) {
  return <header className="page-header"><div><span className="eyebrow">{eyebrow}</span><h1 id={titleId}>{title}</h1>{description && <p>{description}</p>}</div>{action && <div className="page-header-action">{action}</div>}</header>;
}

export function SectionHeader({ eyebrow, title, titleId, aside }: { eyebrow?: string; title: string; titleId?: string; aside?: ReactNode }) {
  return <header className="section-header"><div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h2 id={titleId}>{title}</h2></div>{aside}</header>;
}
