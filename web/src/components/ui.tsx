import { Component, type ReactNode } from "react";
import type { Source } from "../api/types";
import { SOURCES, courseColor, shortCode } from "../lib/domain";
import { Icon, type IconName } from "./Icon";

export function SourceTag({ source }: { source: Source }) {
  const s = SOURCES[source];
  return <span className="src" style={{ ["--s" as string]: s.color }}>{s.label}</span>;
}

export function AiTag({ title }: { title?: string }) {
  return <span className="ai" title={title}><Icon name="sparkle" size={12} /> found by AI</span>;
}

/** Course colour dot + code; with showName the course name is shown (the code stays in the tooltip). */
export function CourseChip({ code, name, showName = false }: { code: string | null; name?: string | null; showName?: boolean }) {
  if (!code) return <span className="cchip" style={{ ["--c" as string]: "#64748B" }}>{name ?? "University"}</span>;
  const named = showName && !!name;
  return (
    <span className={`cchip ${named ? "named" : ""}`} title={named ? shortCode(code) : name ?? undefined} style={{ ["--c" as string]: courseColor(code) }}>
      <i aria-hidden />{named ? <span className="cchip-n">{name}</span> : shortCode(code)}
    </span>
  );
}

export function PageHeader({ eyebrow, title, actions }: { eyebrow?: ReactNode; title: string; actions?: ReactNode }) {
  return (
    <header className="page-h">
      <div>{eyebrow && <p className="eyebrow">{eyebrow}</p>}<h1>{title}</h1></div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

export function Empty({ icon = "info", title, children, action }: { icon?: IconName; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <span className="empty-ic"><Icon name={icon} size={26} /></span>
      <p className="empty-t">{title}</p>
      {children && <p className="empty-d">{children}</p>}
      {action}
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return <span className="spinner" role="progressbar" aria-label={label} />;
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return <div className="skeleton" aria-hidden>{Array.from({ length: lines }, (_, i) => <span key={i} style={{ width: `${90 - i * 12}%` }} />)}</div>;
}

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error) { console.error("UI error", error); }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="crash" role="alert">
        <h1>Something went wrong</h1>
        <p>{this.state.error.message}</p>
        <button className="btn primary" onClick={() => this.setState({ error: null })}>Try again</button>
        <a className="btn" href="/classic">Open the classic interface</a>
      </div>
    );
  }
}
