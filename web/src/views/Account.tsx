import { useState } from "react";
import { API_BASE, api } from "../api/client";
import { Icon } from "../components/Icon";
import { Checkout, priceLabel, useBilling } from "../components/Paywall";
import { useToast } from "../state/toast";
import { PageHeader } from "../components/ui";
import { fmtLong } from "../lib/time";
import { useSession } from "../state/session";

/** Plan switch: Premium on = Ask Bro + Smart Notes. Turning it on goes through the (simulated) checkout. */
function PlanPanel() {
  const { setPlan } = useSession();
  const toast = useToast();
  const { billing, setBilling, error } = useBilling();
  const [checkout, setCheckout] = useState(false);
  const [busy, setBusy] = useState(false);
  if (error) return <section className="panel"><h2>Plan</h2><p className="form-err">{error}</p></section>;
  if (!billing) return <section className="panel"><h2>Plan</h2><p className="muted">Loading…</p></section>;
  const on = billing.plan === "premium";
  const toggle = async () => {
    if (!on) { setCheckout(true); return; }
    setBusy(true);
    try { const b = await api.setPlan("free"); setBilling(b); setPlan(b.plan); toast("You are on Free", "Ask Bro and Smart Notes are locked. Your notes are kept."); }
    catch (e) { toast("Couldn't change the plan", (e as Error).message, "error"); }
    setBusy(false);
  };
  return (
    <section className="panel plan-panel">
      <h2>Plan</h2>
      <p className="panel-sub">Premium adds Ask Bro and Smart Notes for {priceLabel(billing)}.</p>
      <label className="switch-row">
        <span><b>Premium</b><small>{on ? (billing.since ? `Active since ${new Date(billing.since).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}` : "Active") : "Off: you are on the Free plan"}</small></span>
        <button role="switch" aria-checked={on} aria-label="Premium plan" className={`switch ${on ? "on" : ""}`} onClick={() => void toggle()} disabled={busy}><i /></button>
      </label>
      {billing.simulated && <p className="hint">Prototype: payments are simulated, nothing is charged.</p>}
      {checkout && <Checkout billing={billing} onClose={() => setCheckout(false)} onDone={(b) => { setBilling(b); setCheckout(false); }} />}
    </section>
  );
}

export function Account() {
  const { user, health, offline, now, logout, refreshHealth } = useSession();
  if (!user) return null;
  const o = health?.ollama;
  return (
    <>
      <PageHeader eyebrow="Profile and system status" title="Account" />
      <div className="two-col">
        <section className="panel">
          <h2>Profile</h2>
          <dl className="kv">
            <dt>Name</dt><dd>{user.full_name}</dd>
            <dt>Email</dt><dd>{user.email}</dd>
            <dt>Role</dt><dd>{user.role === "professor" ? "Lecturer" : "Student"}</dd>
          </dl>
          <button className="btn" onClick={() => logout()}><Icon name="logout" size={16} /> Log out</button>
        </section>
        {user.role === "student" && <PlanPanel />}
        <section className="panel">
          <h2>System status</h2>
          <dl className="kv">
            <dt>Server</dt><dd>{offline ? <span className="flag">Not reachable</span> : <span className="okc">Connected</span>} <span className="mono muted">{API_BASE}</span></dd>
            <dt>AI</dt><dd>{o ? (o.model_available ? <span className="okc">{o.label ?? "Local AI"} · {o.model} ready</span> : <span className="flag" title={o.error}>{o.label ?? "Local AI"} · {o.model ?? "llama3.2"} not available</span>) : "—"}
              {o?.fallback && <span className="muted"> · backup: {o.fallback.available ? `local ${o.fallback.model}` : "none"}</span>}</dd>
            <dt>Search index</dt><dd>{health ? `${health.vector_documents} messages indexed` : "—"}</dd>
            <dt>Demo date</dt><dd>{fmtLong(now)}</dd>
            <dt>Version</dt><dd>{health ? `${health.app} ${health.version}` : "—"}</dd>
          </dl>
          <div className="row-gap"><button className="btn" onClick={() => void refreshHealth()}><Icon name="sync" size={16} /> Refresh</button>
            <a className="btn ghost" href="/classic">Classic interface</a><a className="btn ghost" href="/docs" target="_blank" rel="noopener noreferrer">API docs</a></div>
        </section>
      </div>
    </>
  );
}
