import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../api/client";
import { answerLines } from "../lib/domain";
import { useSession } from "../state/session";
import { Icon } from "./Icon";

interface Msg { id: number; who: "me" | "bot" | "err"; text: string }
const SUGGESTIONS = ["What do I have to submit this week?", "When do I register for exams?", "Summarise the latest messages from my lecturers", "Explain the key points of my last lesson"];

function Answer({ text }: { text: string }) {
  return <>{answerLines(text).map((l, i) => (
    <p key={i} className={l.bullet ? "li" : undefined}>{l.parts.map((p, k) => (p.bold ? <b key={k}>{p.text}</b> : <span key={k}>{p.text}</span>))}</p>
  ))}</>;
}

/**
 * Ask Bro (Premium). Answers come from the RAG endpoint (external AI from data/ai.env, or the local llama3.2).
 * variant "page": inside the AI section; "sheet": overlay opened by a button (kept for reuse and tests).
 */
export function Assistant({ open = true, onClose = () => undefined, variant = "sheet" }: { open?: boolean; onClose?: () => void; variant?: "sheet" | "page" }) {
  const page = variant === "page";
  const { user, health } = useSession();
  const [log, setLog] = useState<Msg[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);
  const end = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const llmOk = health?.ollama?.model_available !== false;

  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [log, busy]);
  useEffect(() => {
    if (!open || page) return;
    input.current?.focus({ preventScroll: true });
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, page]);

  const ask = async (text: string) => {
    const question = text.trim();
    if (!question || busy) return;
    setQ("");
    setLog((l) => [...l, { id: ++seq.current, who: "me", text: question }]);
    setBusy(true);
    try {
      const r = await api.chat(question);
      setLog((l) => [...l, { id: ++seq.current, who: "bot", text: r.answer }]);
    } catch (e) {
      setLog((l) => [...l, { id: ++seq.current, who: "err", text: (e as Error).message }]);
    } finally { setBusy(false); }
  };
  const submit = (e: FormEvent) => { e.preventDefault(); void ask(q); };

  return (
    <>
      {open && !page && <div className="sheet-scrim" onClick={onClose} aria-hidden />}
      <aside className={`assistant ${page ? "page" : open ? "open" : ""}`} aria-label="Ask Bro assistant">
        <div className="as-h">
          <span className="as-logo"><Icon name="sparkle" size={18} /></span>
          <div><b>Ask Bro</b><small>{!llmOk ? "The AI is not available right now" : health?.ollama?.local === false
            ? `${health.ollama.label ?? "AI"} · ${health.ollama.model}` : `Local AI · ${health?.ollama?.model ?? "llama3.2"} · nothing leaves your computer`}</small></div>
          {!page && <button className="icon-btn as-close" onClick={onClose} aria-label="Close assistant"><Icon name="x" /></button>}
        </div>
        <div className="as-log" aria-live="polite">
          {log.length === 0 && (
            <>
              <p className="as-hello">Hi {user?.full_name.split(" ")[0]}! I read your deadlines, timetable, messages and lesson notes. Try one of these:</p>
              <div className="as-suggest">{SUGGESTIONS.map((s) => <button key={s} onClick={() => void ask(s)}>{s}</button>)}</div>
            </>
          )}
          {log.map((m) => (
            <div key={m.id} className={`b ${m.who}`}>{m.who === "bot" ? <Answer text={m.text} /> : <p>{m.text}</p>}</div>
          ))}
          {busy && <div className="b bot typing" aria-label="Ask Bro is thinking"><i /><i /><i /></div>}
          <div ref={end} />
        </div>
        {log.length > 0 && <button className="as-clear" onClick={() => setLog([])}>Clear conversation</button>}
        <form className="as-in" onSubmit={submit}>
          <label className="sr" htmlFor="ask-input">Ask a question</label>
          <input id="ask-input" ref={input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask about your week…" autoComplete="off" />
          <button aria-label="Send question" disabled={busy || !q.trim()}><Icon name="send" size={18} /></button>
        </form>
      </aside>
    </>
  );
}
