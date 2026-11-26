import { useRef, useState, type DragEvent, type FormEvent } from "react";
import { api } from "../../api/client";
import type { InboxItem, NewMessage } from "../../api/types";
import { Icon } from "../../components/Icon";
import { Spinner } from "../../components/ui";
import { useStudent } from "../../state/student";
import { useToast } from "../../state/toast";

const EMPTY: NewMessage = { source: "email", author: "", subject: "", content: "", course_code: null, sent_at: null };

/**
 * Adds an Outlook email or a Teams message to the Inbox: the student pastes it, or drops an email saved from Outlook (.eml).
 * Only this student sees it; the AI looks for a deadline in it like in the lecturers' announcements.
 */
export function AddMessage({ onClose, onAdded }: { onClose: () => void; onAdded: (item: InboxItem) => void }) {
  const { courses, reload } = useStudent();
  const toast = useToast();
  const [m, setM] = useState<NewMessage>(EMPTY);
  const [busy, setBusy] = useState<"" | "reading" | "saving">("");
  const [error, setError] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const set = (p: Partial<NewMessage>) => setM((x) => ({ ...x, ...p }));
  const sorted = [...courses].sort((a, b) => a.name.localeCompare(b.name));

  const readFile = async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    if (!/\.eml$/i.test(file.name)) {
      setError("Only emails saved as .eml can be read. In Outlook: open the email → … → Download (or Save as). Or paste the text below.");
      return;
    }
    setBusy("reading");
    try {
      const p = await api.parseEml(await file.text());
      setM((x) => ({ ...x, source: "email", author: p.author || x.author, subject: p.subject, content: p.content, sent_at: p.sent_at }));
      setFileName(file.name);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(""); }
  };
  const onDrop = (e: DragEvent) => { e.preventDefault(); setDrag(false); void readFile(e.dataTransfer.files[0]); };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (m.content.trim().length < 2) { setError("Paste the text of the message."); return; }
    setBusy("saving"); setError(null);
    try {
      const r = await api.addMessage({ ...m, course_code: m.course_code || null });
      await reload();
      if (r.ai_status === "deadline_extracted") toast("Message added", `The AI found a date: ${r.item.ai_summary.replace(/^AI-detected deadline: /, "")}`, "ok");
      else if (r.ai_status === "no_deadline") toast("Message added", "No deadline in it.", "ok");
      else toast("Message added, not read by the AI", r.ai_error ?? "The local AI is not running: no deadline was looked for.", "info");
      onAdded(r.item);
    } catch (err) { setError((err as Error).message); setBusy(""); }
  };

  const outlook = m.source === "email";
  return (
    <div className="modal-wrap">
      <div className="sheet-scrim show" onClick={() => !busy && onClose()} aria-hidden />
      <form className="modal add-msg" role="dialog" aria-modal="true" aria-labelledby="am-title" onSubmit={(e) => void submit(e)}>
        <h2 id="am-title">Add a message</h2>
        <div className="seg" role="radiogroup" aria-label="Where the message comes from">
          <button type="button" role="radio" aria-checked={outlook} onClick={() => set({ source: "email" })}>Outlook</button>
          <button type="button" role="radio" aria-checked={!outlook} onClick={() => { set({ source: "teams", sent_at: null }); setFileName(null); }}>Teams</button>
        </div>
        {outlook && (
          <div className={`drop ${drag ? "over" : ""}`} onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={onDrop}>
            <Icon name="inbox" size={18} />
            <span>{busy === "reading" ? "Reading the email…" : fileName ? <>Loaded <b>{fileName}</b></> : <>Drop an email saved from Outlook (<b>.eml</b>) or</>}</span>
            <button type="button" className="btn sm" onClick={() => fileInput.current?.click()} disabled={!!busy}>Choose file</button>
            <input ref={fileInput} type="file" accept=".eml,message/rfc822" hidden onChange={(e) => { void readFile(e.target.files?.[0]); e.target.value = ""; }} />
          </div>
        )}
        <label className="field">From<input value={m.author} onChange={(e) => set({ author: e.target.value })} placeholder={outlook ? "e.g. Prof. Laura Bianchi" : "e.g. Marco Rossi (Teams)"} maxLength={255} /></label>
        {outlook && <label className="field">Subject<input value={m.subject} onChange={(e) => set({ subject: e.target.value })} maxLength={300} /></label>}
        <label className="field">Course
          <select value={m.course_code ?? ""} onChange={(e) => set({ course_code: e.target.value || null })}>
            <option value="">Let the AI guess</option>
            {sorted.map((c) => <option key={c.id} value={c.code}>{c.name}</option>)}
          </select>
        </label>
        <label className="field">Message<textarea value={m.content} onChange={(e) => set({ content: e.target.value })} rows={6} maxLength={20000}
          placeholder={outlook ? "Paste the text of the email" : "Paste the Teams message (chat or channel post)"} /></label>
        <p className="hint"><Icon name="info" size={14} /> Only you see this message. The AI looks for a deadline in it and puts it in your calendar.</p>
        {error && <p className="form-err" role="alert">{error}</p>}
        <div className="row-gap">
          <button className="btn primary" type="submit" disabled={!!busy}>{busy === "saving" ? <><Spinner label="Adding" /> The AI is reading it…</> : "Add to Inbox"}</button>
          <button className="btn ghost" type="button" onClick={onClose} disabled={busy === "saving"}>Cancel</button>
        </div>
      </form>
    </div>
  );
}
