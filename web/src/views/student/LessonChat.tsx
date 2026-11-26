import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../../api/client";
import type { ChatSource, LessonChatMessage, LessonNote } from "../../api/types";
import { Icon } from "../../components/Icon";
import { answerLines } from "../../lib/domain";

interface Msg { id: number; who: "me" | "bot" | "err" | "info"; text: string; sources?: ChatSource[] }
const toMsg = (m: LessonChatMessage): Msg => ({ id: m.id, who: m.role === "user" ? "me" : "bot", text: m.content, sources: m.sources });
const SUGGEST = ["Summarise this material in 5 points", "Explain the key terms", "What could come up at the exam?"];

/** Where a source is, in a few characters: "p. 4", "slide 3", "12:30". */
export function shortPlace(label: string): string {
  const m = /^(Page|Slide) (\d+)$/.exec(label);
  if (m) return m[1] === "Page" ? `p. ${m[2]}` : `slide ${m[2]}`;
  return label;
}

/** "[2]" in an answer becomes a small chip with the page (or slide, or minute) it came from. */
function Cited({ text, sources }: { text: string; sources: ChatSource[] }) {
  return <>{text.replace(/\s+(\[\d{1,2}\])/g, "$1").split(/(\[\d{1,2}\])/).map((p, i) => {
    const m = /^\[(\d{1,2})\]$/.exec(p);
    if (!m) return <span key={i}>{p}</span>;
    const src = sources.find((s) => s.n === Number(m[1]));
    const place = src?.label ? shortPlace(src.label) : m[1];
    return <span key={i} className="cite" title={src ? `${src.filename}${src.label ? ` · ${src.label}` : ""}` : undefined}
      aria-label={src ? `source: ${src.filename}${src.label ? `, ${src.label}` : ""}` : `source ${m[1]}`}>{place}</span>;
  })}</>;
}

/** "Intro.pdf, p. 4 and p. 6": one file name, then its places. */
function byFile(sources: ChatSource[]): string {
  const files = new Map<string, string[]>();
  for (const s of sources) {
    const places = files.get(s.filename) ?? [];
    if (s.label && !places.includes(shortPlace(s.label))) places.push(shortPlace(s.label));
    files.set(s.filename, places);
  }
  return [...files].map(([f, p]) => (p.length ? `${f}, ${p.length > 1 ? `${p.slice(0, -1).join(", ")} and ${p[p.length - 1]}` : p[0]}` : f)).join("; ");
}

function Answer({ m }: { m: Msg }) {
  return (
    <>
      {answerLines(m.text).map((l, i) => (
        <p key={i} className={l.bullet ? "li" : undefined}>{l.parts.map((p, k) => (p.bold ? <b key={k}><Cited text={p.text} sources={m.sources ?? []} /></b> : <Cited key={k} text={p.text} sources={m.sources ?? []} />))}</p>
      ))}
      {!!m.sources?.length && (
        <details className="lc-src">
          <summary>See in the material: {byFile(m.sources)}</summary>
          <ul>{m.sources.map((s) => (
            <li key={s.n}><b><span className="cite">{s.label ? shortPlace(s.label) : s.n}</span> {s.filename}{s.label ? ` · ${s.label}` : ""}</b><span>“{s.excerpt}”</span></li>
          ))}</ul>
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
          <option value="">Whole lesson ({note.sources.length === 1 ? "1 file" : `${note.sources.length} files`})</option>
          {note.sources.map((s) => <option key={s.id} value={s.id}>{s.filename}</option>)}
        </select>
        <span className="lc-info" tabIndex={0} role="note" aria-label={`Answers use only ${scopeName}. If something is not in the material, Bro says so. The conversation is saved.`}
          title={`Answers use only ${scopeName}. If something is not in the material, Bro says so. The conversation is saved.`}><Icon name="info" size={18} /></span>
      </div>

      <div className="lc-log" aria-live="polite">
        {loaded && log.length === 0 && <p className="lc-hint">Answers use only {scopeName}, with the page they come from. The conversation is saved.</p>}
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
