import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Billing } from "../api/types";
import { useSession } from "../state/session";
import { useToast } from "../state/toast";
import { Icon } from "./Icon";
import { Spinner } from "./ui";

export const priceLabel = (b: Pick<Billing, "price" | "currency" | "period">) => `${b.price} ${b.currency} / ${b.period}`;

/** Loads the plan and the price (set in app/config.py on the server). */
export function useBilling() {
  const [billing, setBilling] = useState<Billing | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.billing().then(setBilling).catch((e: Error) => setError(e.message)); }, []);
  return { billing, setBilling, error };
}

/** Simulated checkout: no card, nothing is charged. Activates Premium on the server. */
export function Checkout({ billing, onClose, onDone }: { billing: Billing; onClose: () => void; onDone: (b: Billing) => void }) {
  const { setPlan } = useSession();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !busy) onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);
  const pay = async () => {
    setBusy(true);
    try {
      await new Promise((r) => setTimeout(r, 900));   // looks like a payment provider answering
      const b = await api.setPlan("premium");
      setPlan(b.plan);
      toast("Premium is active", "Ask Bro and Smart Notes are unlocked.", "ok");
      onDone(b);
    } catch (e) { toast("Payment failed", (e as Error).message, "error"); setBusy(false); }
  };
  return (
    <div className="modal-wrap">
      <div className="sheet-scrim show" onClick={() => !busy && onClose()} aria-hidden />
      <div className="modal checkout" role="dialog" aria-modal="true" aria-labelledby="co-title">
        <h2 id="co-title">Checkout</h2>
        <div className="co-line"><span><b>Remind Me Bro Premium</b><small>Ask Bro + Smart Notes · cancel any time</small></span><b>{priceLabel(billing)}</b></div>
        <div className="co-line total"><span>Today you pay</span><b>{billing.price} {billing.currency}</b></div>
        {billing.simulated && <p className="co-note"><Icon name="info" size={16} /> Prototype: the payment is simulated. No card is asked for and nothing is charged.</p>}
        <div className="row-gap">
          <button className="btn primary" onClick={() => void pay()} disabled={busy}>{busy ? <><Spinner label="Paying" /> Paying…</> : `Pay ${billing.price} ${billing.currency}`}</button>
          <button className="btn ghost" onClick={onClose} disabled={busy}>Cancel</button>
        </div>
      </div>
    </div>
  );
}

/** What a Free user sees in the AI section. */
export function Paywall() {
  const { billing, setBilling, error } = useBilling();
  const [checkout, setCheckout] = useState(false);
  if (error) return <p className="form-err">{error}</p>;
  if (!billing) return <Spinner label="Loading the plans" />;
  return (
    <section className="paywall" aria-labelledby="pw-title">
      <div className="pw-hero">
        <span className="as-logo"><Icon name="sparkle" size={20} /></span>
        <div>
          <p className="eyebrow">Remind Me Bro Premium</p>
          <h2 id="pw-title">Your AI study assistant</h2>
          <p className="pw-price"><b>{billing.price} {billing.currency}</b> / {billing.period}</p>
        </div>
      </div>
      <ul className="pw-features">{billing.features.map((f) => <li key={f}><Icon name="check" size={18} />{f}</li>)}</ul>
      <div className="pw-preview" aria-hidden>
        <div className="pw-card">
          <b><Icon name="chat" size={16} /> Ask Bro</b>
          <div className="b me">What do I have to submit this week?</div>
          <div className="b bot">Problem Set 3 for Microeconomics is due <b>Friday at 23:59</b>…</div>
        </div>
        <div className="pw-card">
          <b><Icon name="book" size={16} /> Smart Notes</b>
          <p className="pw-line w90" /><p className="pw-line w70" /><p className="pw-line w80" />
          <span className="pill ok">Ready</span>
        </div>
      </div>
      <button className="btn primary pw-cta" onClick={() => setCheckout(true)}><Icon name="sparkle" size={18} /> Get Premium · {priceLabel(billing)}</button>
      {checkout && <Checkout billing={billing} onClose={() => setCheckout(false)} onDone={(b) => { setBilling(b); setCheckout(false); }} />}
    </section>
  );
}
