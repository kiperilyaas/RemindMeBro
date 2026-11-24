import { BRAND, BrandLogo } from "./Brand";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useSession } from "../state/session";
import { Icon, type IconName } from "./Icon";

export interface NavItem { path: string; label: string; icon: IconName; badge?: number }

function initials(name: string) {
  return name.replace(/^Prof\.?\s+/i, "").split(/\s+/).map((p) => p[0]).slice(0, 2).join("").toUpperCase();
}

function UserMenu({ onNavigate }: { onNavigate: (p: string) => void }) {
  const { user, logout } = useSession();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [open]);
  if (!user) return null;
  return (
    <div className="umenu" ref={ref}>
      <button className="av" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)} aria-label={`Account menu for ${user.full_name}`}>{initials(user.full_name)}</button>
      {open && (
        <div className="umenu-pop" role="menu">
          <div className="umenu-h"><b>{user.full_name}</b><small>{user.email} · {user.role === "professor" ? "Lecturer" : "Student"}</small></div>
          <button role="menuitem" onClick={() => { setOpen(false); onNavigate("account"); }}><Icon name="user" size={18} /> Account & status</button>
          <a role="menuitem" href="/classic"><Icon name="external" size={18} /> Classic interface</a>
          <button role="menuitem" onClick={() => logout()}><Icon name="logout" size={18} /> Log out</button>
        </div>
      )}
    </div>
  );
}

export function Shell({ nav, current, onNavigate, actions, aside, fab, children }: {
  nav: NavItem[]; current: string; onNavigate: (p: string) => void; actions?: ReactNode; aside?: ReactNode; fab?: ReactNode; children: ReactNode;
}) {
  const { offline } = useSession();
  const mainRef = useRef<HTMLElement>(null);
  // Move focus to the new page for screen-reader and keyboard users.
  useEffect(() => { mainRef.current?.focus({ preventScroll: true }); window.scrollTo({ top: 0 }); }, [current]);
  return (
    <div className="app">
      <a className="skip" href="#main" onClick={(e) => { e.preventDefault(); mainRef.current?.focus(); }}>Skip to content</a>
      {offline && <div className="offline" role="alert"><Icon name="alert" size={16} /> Can't reach the server. Keep the Run &amp; Go window open — retrying automatically…</div>}
      <header className="top">
        <button className="brand" onClick={() => onNavigate(nav[0].path)} aria-label="Remind Me Bro, home"><img className="brand-icon" src={BRAND.icon} alt="" /><BrandLogo /></button>
        <nav className="toptabs" aria-label="Main">
          {nav.map((n) => (
            <button key={n.path} aria-current={current === n.path ? "page" : undefined} onClick={() => onNavigate(n.path)}>
              {n.label}{!!n.badge && <span className="badge" aria-label={`${n.badge} new`}>{n.badge}</span>}
            </button>
          ))}
        </nav>
        <div className="top-r">{actions}<UserMenu onNavigate={onNavigate} /></div>
      </header>
      <div className={`layout ${aside ? "with-aside" : ""}`}>
        <main id="main" className="col" ref={mainRef} tabIndex={-1}>{children}</main>
        {aside}
      </div>
      {fab}
      <nav className="bottom" aria-label="Main (mobile)">
        {nav.map((n) => (
          <button key={n.path} aria-current={current === n.path ? "page" : undefined} onClick={() => onNavigate(n.path)}>
            <span className="bi"><Icon name={n.icon} />{!!n.badge && <i className="bdot" aria-hidden />}</span><span>{n.label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}
