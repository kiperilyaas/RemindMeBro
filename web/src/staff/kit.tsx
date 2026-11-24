// Shared building blocks of the three staff areas (hub lecturer, UniLearn, UniSIS).
import { Component, createContext, useCallback, useContext, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import "./staff.css";

// ---------------------------------------------------------------------------
// Same-origin JSON client for UniLearn / UniSIS staff APIs (session cookie + CSRF header)
// ---------------------------------------------------------------------------
export class StaffError extends Error { constructor(message: string, public status: number) { super(message); } }

export async function staffFetch<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const res = await fetch(path, {
    method: init.method ?? "GET", credentials: "same-origin",
    headers: { Accept: "application/json", "X-Requested-With": "staff", ...(init.body !== undefined ? { "Content-Type": "application/json" } : {}) },
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
  }).catch(() => { throw new StaffError("The server is not reachable. Keep the Run & Go window open.", 0); });
  if (res.status === 204) return null as T;
  const data: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const d = (data as { detail?: unknown } | null)?.detail;
    const msg = Array.isArray(d) ? d.map((x: { loc?: string[]; msg: string }) => `${x.loc?.[x.loc.length - 1] ?? ""}: ${x.msg}`).join(" · ") : typeof d === "string" ? d : `Request failed (${res.status})`;
    throw new StaffError(msg, res.status);
  }
  return data as T;
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------
const L = "en-GB";
export const fmtDate = (s: string | null | undefined) => (s ? new Date(s).toLocaleDateString(L, { weekday: "short", day: "numeric", month: "short" }) : "—");
export const fmtDateTime = (s: string | null | undefined) => (s ? `${fmtDate(s)}, ${new Date(s).toLocaleTimeString(L, { hour: "2-digit", minute: "2-digit" })}` : "—");
export const fmtTime = (s: string) => new Date(s).toLocaleTimeString(L, { hour: "2-digit", minute: "2-digit" });
/** "YYYY-MM-DDTHH:MM" for datetime-local inputs */
export const toLocalInput = (d: Date) => {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
};

// ---------------------------------------------------------------------------
// Toasts
// ---------------------------------------------------------------------------
interface Toast { id: number; title: string; body?: string; bad?: boolean }
const ToastCtx = createContext<(title: string, body?: string, bad?: boolean) => void>(() => undefined);
export const useToast = () => useContext(ToastCtx);

export function ToastHost({ children }: { children: ReactNode }) {
  const [list, setList] = useState<Toast[]>([]);
  const seq = useRef(0);
  const timers = useRef<number[]>([]);
  useEffect(() => { const t = timers.current; return () => t.forEach(clearTimeout); }, []);
  const push = useCallback((title: string, body?: string, bad?: boolean) => {
    const id = ++seq.current;
    setList((l) => [...l.slice(-2), { id, title, body, bad }]);
    timers.current.push(window.setTimeout(() => setList((l) => l.filter((x) => x.id !== id)), bad ? 8000 : 5000));
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="st st-layer"><div className="st-toasts" role="status" aria-live="polite">
        {list.map((t) => (
          <div key={t.id} className={`st-toast ${t.bad ? "bad" : ""}`}>
            <div><b>{t.title}</b>{t.body && <p>{t.body}</p>}</div>
            <button onClick={() => setList((l) => l.filter((x) => x.id !== t.id))} aria-label="Dismiss">×</button>
          </div>
        ))}
      </div></div>
    </ToastCtx.Provider>
  );
}

// ---------------------------------------------------------------------------
// Shell
// ---------------------------------------------------------------------------
export interface SystemInfo { name: string; area: string; mark: string; accent: string; logo?: string }
export interface NavItem { id: string; label: string; highlight?: boolean }

export function StaffShell({ system, nav, current, onNavigate, user, onLogout, children }: {
  system: SystemInfo; nav: NavItem[]; current: string; onNavigate: (id: string) => void; user: { fullname: string; role: string }; onLogout: () => void; children: ReactNode;
}) {
  const main = useRef<HTMLElement>(null);
  useEffect(() => { main.current?.focus({ preventScroll: true }); window.scrollTo({ top: 0 }); }, [current]);
  useEffect(() => { document.title = `${system.name} · ${system.area}`; }, [system]);
  return (
    <div className="st" style={{ ["--accent" as string]: system.accent }}>
      <header className="st-bar">
        <button className="st-brand" onClick={() => onNavigate(nav[0].id)}>{system.logo ? <img className="st-mark img" src={system.logo} alt="" aria-hidden /> : <span className="st-mark" aria-hidden>{system.mark}</span>}{system.name}<small>{system.area}</small></button>
        <nav className="st-nav" aria-label="Main">
          {nav.map((n) => (
            <button key={n.id} className={n.highlight ? "st-try" : undefined} aria-current={current === n.id ? "page" : undefined} onClick={() => onNavigate(n.id)}>{n.label}</button>
          ))}
        </nav>
        <div className="st-user"><span><b>{user.fullname}</b> · {user.role}</span><button className="st-btn sm" onClick={onLogout}>Log out</button></div>
      </header>
      <main className="st-main" ref={main} tabIndex={-1} style={{ outline: "none" }}>{children}</main>
    </div>
  );
}

export function PageHead({ title, intro, crumb, actions }: { title: string; intro?: ReactNode; crumb?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="st-head">
      <div>{crumb && <div className="st-crumb">{crumb}</div>}<h1>{title}</h1>{intro && <p>{intro}</p>}</div>
      {actions && <div className="st-row">{actions}</div>}
    </div>
  );
}

export function Pill({ tone, children, plain }: { tone?: "ok" | "warn" | "bad" | "info" | "accent"; children: ReactNode; plain?: boolean }) {
  return <span className={`st-pill ${tone ?? ""} ${plain ? "plain" : ""}`}>{children}</span>;
}

export function Stat({ label, value }: { label: string; value: ReactNode }) {
  return <div className="st-card st-stat"><span>{label}</span><b>{value}</b></div>;
}

// ---------------------------------------------------------------------------
// Login
// ---------------------------------------------------------------------------
export interface DemoAccount { username: string; fullname: string; role: string }

export function StaffLogin({ system, intro, demo, onLogin }: {
  system: SystemInfo; intro: string; demo: { password: string | null; passwords_file?: string; accounts: DemoAccount[] } | null; onLogin: (u: string, p: string) => Promise<void>;
}) {
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const go = async (user: string, pass: string) => {
    setBusy(true); setErr(null);
    try { await onLogin(user, pass); } catch (e) { setErr((e as Error).message); setBusy(false); }
  };
  const submit = (e: FormEvent) => { e.preventDefault(); void go(u.trim(), p); };
  return (
    <div className="st" style={{ ["--accent" as string]: system.accent }}>
      <div className="st-login">
        <div className="st-login-box">
          <div className="st-brand">{system.logo ? <img className="st-mark img" src={system.logo} alt="" aria-hidden /> : <span className="st-mark" aria-hidden>{system.mark}</span>}{system.name}<small>{system.area}</small></div>
          <h1>Sign in</h1>
          <p>{intro}</p>
          <form className="st-form" onSubmit={submit}>
            <label className="st-field">Username<input value={u} onChange={(e) => setU(e.target.value)} autoComplete="username" required /></label>
            <label className="st-field">Password<input type="password" value={p} onChange={(e) => setP(e.target.value)} autoComplete="current-password" required /></label>
            {err && <p className="st-err" role="alert">{err}</p>}
            <button className="st-btn primary lg block" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
          </form>
          {demo && demo.accounts.length > 0 && (
            <div className="st-demo">
              <p>Staff accounts — passwords in <span className="st-code">{demo.passwords_file ?? "data/STAFF-PASSWORDS.txt"}</span> on this computer</p>
              <div className="st-demo-grid">
                {demo.accounts.map((a) => (
                  <button key={a.username} disabled={busy} onClick={() => (demo.password ? void go(a.username, demo.password) : (setU(a.username), setP(""), setErr(null)))}>
                    <b>{a.fullname}</b><small>{a.role} · {a.username}</small>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Demo scenarios
// ---------------------------------------------------------------------------
export interface ScenarioView {
  id: string; title: string; actor: string; what: string; check: string[];
  status: "ready" | "done" | "blocked"; can_undo: boolean; blocked_reason: string | null;
}

export function Scenarios({ items, onRun, onUndo, hubUrl }: {
  items: ScenarioView[] | null; onRun: (id: string) => Promise<void>; onUndo?: (id: string) => Promise<void>; hubUrl?: string;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const act = async (id: string, fn: (id: string) => Promise<void>) => { setBusy(id); try { await fn(id); } finally { setBusy(null); } };
  return (
    <>
      <div className="st-callout">
        <span aria-hidden>↻</span>
        <div><b>Try the student hub with ready-made cases</b>Each case does one real action in this system. Then open the student hub
          {hubUrl ? <> (<a className="st-link" href={hubUrl} target="_blank" rel="noopener noreferrer">open it</a>, signed in as Giulia)</> : " (signed in as Giulia)"} and follow the steps to see the result. Use Undo to try a case again.</div>
      </div>
      {!items ? <div className="st-card st-empty">Loading cases…</div> : (
        <div className="st-cases">
          {items.map((s) => (
            <article key={s.id} className={`st-case ${s.status === "done" ? "done" : ""}`} aria-label={s.title}>
              <div>
                <h3>{s.title}</h3>
                <div className="who">{s.actor}</div>
                <p className="what">{s.what}</p>
              </div>
              <div className="act">
                {s.status === "ready" && <button className="st-btn primary" disabled={!!busy} onClick={() => void act(s.id, onRun)}>{busy === s.id ? "Running…" : "Run case"}</button>}
                {s.status === "done" && <Pill tone="ok">Done</Pill>}
                {s.status === "blocked" && <Pill tone="warn">Not yet</Pill>}
                {s.can_undo && onUndo && <button className="st-btn ghost sm" disabled={!!busy} onClick={() => void act(s.id, onUndo)}>{busy === s.id ? "…" : "Undo"}</button>}
              </div>
              <div className="st-check">
                <b>{s.status === "blocked" ? "Before you start" : s.status === "done" ? "Now check in the student hub" : "Then check in the student hub"}</b>
                {s.status === "blocked" ? <span>{s.blocked_reason}</span> : <ol>{s.check.map((c) => <li key={c}>{c}</li>)}</ol>}
              </div>
            </article>
          ))}
        </div>
      )}
    </>
  );
}

/** Loads /staff/api/scenarios and wires run / undo with toasts. */
export function useServerScenarios() {
  const toast = useToast();
  const [items, setItems] = useState<ScenarioView[] | null>(null);
  const load = useCallback(async () => { try { setItems(await staffFetch<ScenarioView[]>("/staff/api/scenarios")); } catch (e) { toast("Couldn't load the cases", (e as Error).message, true); } }, [toast]);
  useEffect(() => { void load(); }, [load]);
  const call = useCallback((action: "run" | "undo") => async (id: string) => {
    try {
      const r = await staffFetch<{ message: string; scenario: ScenarioView }>(`/staff/api/scenarios/${id}/${action}`, { method: "POST" });
      setItems((l) => l?.map((s) => (s.id === id ? r.scenario : s)) ?? l);
      toast(action === "run" ? "Case done" : "Undone", r.message);
    } catch (e) { toast("Couldn't run the case", (e as Error).message, true); await load(); }
  }, [load, toast]);
  return { items, run: call("run"), undo: call("undo"), reload: load };
}

/** Session for a staff app: me / login / logout against /staff/api. */
export function useStaffSession<T extends { fullname: string; role: string }>() {
  const [user, setUser] = useState<T | null>(null);
  const [booting, setBooting] = useState(true);
  const [demo, setDemo] = useState<{ password: string | null; passwords_file?: string; accounts: DemoAccount[] } | null>(null);
  useEffect(() => {
    let alive = true;
    staffFetch<{ user: T | null }>("/staff/api/session").then((s) => alive && setUser(s.user)).catch(() => undefined).finally(() => alive && setBooting(false));
    staffFetch<{ password: string | null; passwords_file?: string; accounts: DemoAccount[] }>("/staff/api/demo-accounts").then((d) => alive && setDemo(d)).catch(() => undefined);
    return () => { alive = false; };
  }, []);
  const login = useCallback(async (username: string, password: string) => {
    await staffFetch("/staff/api/login", { method: "POST", body: { username, password } });
    setUser(await staffFetch<T>("/staff/api/me"));
  }, []);
  const logout = useCallback(async () => { await staffFetch("/staff/api/logout", { method: "POST" }).catch(() => undefined); setUser(null); location.hash = ""; }, []);
  return { user, booting, demo, login, logout };
}

/** Tiny hash router: "#course/3" -> ["course", "3"]. */
export function useHashPath(): [string[], (p: string) => void] {
  const read = () => location.hash.replace(/^#\/?/, "").split("?")[0].split("/").filter(Boolean);
  const [path, setPath] = useState<string[]>(read);
  useEffect(() => {
    const on = () => setPath(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return [path, useCallback((p: string) => { location.hash = p; }, [])];
}

export class StaffErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error) { console.error("Staff UI error", error); }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="st"><div className="st-login"><div className="st-login-box" role="alert">
        <h1>Something went wrong</h1><p className="muted">{this.state.error.message}</p>
        <button className="st-btn primary" onClick={() => this.setState({ error: null })}>Try again</button>
      </div></div></div>
    );
  }
}
