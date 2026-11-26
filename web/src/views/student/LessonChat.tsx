import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../../api/client";
import type { ChatSource, LessonChatMessage, LessonNote } from "../../api/types";
import { Icon } from "../../components/Icon";
import { answerLines } from "../../lib/domain";

interface Msg { id: number; who: "me" | "bot" | "err" | "info"; text: string; sources?: ChatSource[] }
const toMsg = (m: LessonChatMessage): Msg => ({ id: m.id, who: m.role === "user" ? "me" : "bot", text: m.content, sources: m.sources });
const SUGGEST = ["Summarise this material in 5 points", "Explain the key terms", "What could come up at the exam?"];

/** "[2]" in an answer becomes a small reference to the excerpt it came from. */
function Cited({ text }: { text: string }) {
  return <>{text.replace(/\s+(\[\d{1,2}\])/g, "$1").split(/(\[\d{1,2}\])/).map((p, i) => {
    const m = /^\[(\d{1,2})\]$/.exec(p);
    return m ? <sup key={i} className="cite" aria-label={`source ${m[1]}`}>{m[1]}</sup> : <span key={i}>{p}</span>;
  })}</>;
}

function Answer({ m }: { m: Msg }) {
  return (
    <>
      {answerLines(m.text).map((l, i) => (
        <p key={i} className={l.bullet ? "li" : undefined}>{l.parts.map((p, k) => (p.bold ? <b key={k}><Cited text={p.text} /></b> : <Cited key={k} text={p.text} />))}</p>
      ))}
      {!!m.sources?.length && (
        <details className="lc-src">
          <summary>{m.sources.length === 1 ? "1 source" : `${m.sources.length} sources`}: {m.sources.map((s) => `${s.filename}${s.label ? ` · ${s.label}` : ""}`).filter((v, i, a) => a.indexOf(v) === i).join(", ")}</summary>
          <ol>{m.sources.map((s) => (
            <li key={s.n} value={s.n}><b>{s.filename}{s.label ? ` · ${s.label}` : ""}</b><span>{s.excerpt}{s.excerpt.length >= 240 ? "…" : ""}</span></li>
          ))}</ol>
        </details>
      )}
    </>
  );
}

/** Chat that answers only from the files of this lesson (or one of them), with the excerpts it used. Saved on the server. */
export function LessonChat({ note }: { note: LessonNote }) {
  const [scope, setScope] = useState<number | null>(null);   // null = every file of the lesson
  const [log, setLog] = useState<Msg[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const seq = useRef(-1);   // local-only messages (errors) get negative ids
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [log, busy]);
  // each file has its own saved conversation, the whole lesson another one
  useEffect(() => {
    let live = true;
    setLoaded(false); setLog([]);
    api.lessonChatHistory(note.id, scope)
      .then((r) => { if (live) setLog(r.messages.map(toMsg)); })
      .catch((e: Error) => { if (live) setLog([{ id: seq.current--, who: "err", text: e.message }]); })
      .finally(() => { if (live) setLoaded(true); });
    return () => { live = false; };
  }, [note.id, scope]);
  const scopeName = scope === null ? (note.sources.length === 1 ? "the file of this lesson" : `the ${note.sources.length} files of this lesson`) : note.sources.find((s) => s.id === scope)?.filename ?? "this file";

  const ask = async (text: string) => {
    const question = text.trim();
    if (!question || busy) return;
    setQ("");
    const tmp = seq.current--;
    setLog((l) => [...l, { id: tmp, who: "me", text: question }]);
    setBusy(true);
    try {
      const r = await api.lessonChat(note.id, question, scope);
      setLog((l) => [...l.filter((m) => m.id !== tmp), ...r.messages.map(toMsg),
        ...(r.skipped.length ? [{ id: seq.current--, who: "info" as const, text: `Not read yet: ${r.skipped.join(", ")}` }] : [])]);
    } catch (e) {
      setLog((l) => [...l, { id: seq.current--, who: "err", text: (e as Error).message }]);
    } finally { setBusy(false); }
  };
  const clear = async () => {
    try { await api.clearLessonChat(note.id, scope); setLog([]); }
    catch (e) { setLog((l) => [...l, { id: seq.current--, who: "err", text: (e as Error).message }]); }
  };
  const submit = (e: FormEvent) => { e.preventDefault(); void ask(q); };
  const saved = log.some((m) => m.id > 0);

  return (
    <section className="lchat" aria-label="Ask about this material">
      <div className="lc-h">
        <label htmlFor="lc-scope">Ask about</label>
        <select id="lc-scope" value={scope ?? ""} onChange={(e) => setScope(e.target.value === "" ? null : Number(e.target.value))}>
          <option value="">The whole lesson ({note.sources.length} files)</option>
          {note.sources.map((s) => <option key={s.id} value={s.id}>{s.filename}</option>)}
        </select>
      </div>
      <p className="lc-note"><Icon name="info" size={15} /> Answers use only {scopeName}. If something is not in the material, Bro says so. The conversation is saved.</p>
      <div className="lc-log" aria-live="polite">
        {loaded && log.length === 0 && <div className="as-suggest">{SUGGEST.map((s) => <button key={s} onClick={() => void ask(s)}>{s}</button>)}</div>}
        {log.map((m) => <div key={m.id} className={`b ${m.who === "info" ? "err" : m.who}`}>{m.who === "bot" ? <Answer m={m} /> : <p>{m.text}</p>}</div>)}
        {busy && <div className="b bot typing" aria-label="Reading the material"><i /><i /><i /></div>}
        <div ref={end} />
      </div>
      {saved && <button className="as-clear" onClick={() => void clear()}>Delete this conversation</button>}
      <form className="as-in" onSubmit={submit}>
        <label className="sr" htmlFor="lc-input">Question about the material</label>
        <input id="lc-input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask about this material…" autoComplete="off" />
        <button aria-label="Send question" disabled={busy || !q.trim()}><Icon name="send" size={18} /></button>
      </form>
    </section>
  );
}
