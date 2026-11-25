import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { LessonNote, LessonRow, NoteStatus, NotesList, SourceKind } from "../../api/types";
import { Icon } from "../../components/Icon";
import { CourseChip, Empty, Skeleton, Spinner } from "../../components/ui";
import { Markdown } from "../../lib/markdown";
import { useToast } from "../../state/toast";
import { LessonChat } from "./LessonChat";

export const STATUS: Record<NoteStatus, { label: string; tone: string; busy: boolean }> = {
  new: { label: "Not made yet", tone: "", busy: false },
  waiting: { label: "Queued", tone: "", busy: true },
  syncing: { label: "Syncing…", tone: "plan", busy: true },
  transcribing: { label: "Transcribing…", tone: "plan", busy: true },
  processing: { label: "AI processing…", tone: "plan", busy: true },
  ready: { label: "Ready", tone: "ok", busy: false },
  error: { label: "Error", tone: "warn", busy: false },
};
const KIND: Record<SourceKind, string> = { pdf: "PDF", slides: "Slides", document: "Document", text: "Text", audio: "Audio", video: "Video" };
const fmtWhen = (s: string | null) => (s ? new Date(s).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "");

export function StatusPill({ status }: { status: NoteStatus }) {
  const s = STATUS[status];
  return <span className={`pill ${s.tone}`} aria-live="polite">{s.busy && status !== "waiting" && <span className="dot-pulse" aria-hidden />}{s.label}</span>;
}

function LessonCard({ l, onOpen, onMake }: { l: LessonRow; onOpen: () => void; onMake: () => void }) {
  const media = l.sources.some((x) => x.kind === "audio" || x.kind === "video");
  return (
    <div className="lesson">
      <button className="lesson-open" onClick={onOpen} disabled={STATUS[l.status].busy} aria-label={`${l.lesson}, ${STATUS[l.status].label}`}>
        <span className="lesson-h"><b>{l.lesson}</b><StatusPill status={l.status} /></span>
        {l.status === "ready" && l.summary && <span className="lesson-s">{l.summary}</span>}
        {l.status === "error" && l.error && <span className="lesson-err">{l.error}</span>}
      </button>
      <span className="lesson-f">
        {l.sources.map((s) => <span key={s.filename} className="kind" title={s.filename}>{KIND[s.kind]}</span>)}
        {l.edited && <span className="kind ed">Edited</span>}
        {l.new_material && <span className="kind new">New material</span>}
        {l.status === "new" && <button className="btn primary sm lesson-make" onClick={onMake} title={media ? "Reads the files and transcribes the recording on this computer" : "Reads the files on this computer"}>
          <Icon name="sparkle" size={15} /> Make notes</button>}
      </span>
    </div>
  );
}

function NoteView({ id, onBack }: { id: number; onBack: () => void }) {
  const toast = useToast();
  const [note, setNote] = useState<LessonNote | null>(null);
  const [draft, setDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState<"notes" | "ask">("notes");
  const load = useCallback(() => api.note(id).then(setNote).catch((e: Error) => toast("Couldn't open the notes", e.message, "error")), [id, toast]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {   // follow a regeneration until it is done
    if (!note || !STATUS[note.status].busy) return;
    const t = window.setTimeout(() => void load(), 3000);
    return () => clearTimeout(t);
  }, [note, load]);

  if (!note) return <Skeleton lines={4} />;
  const save = async () => {
    if (draft === null) return;
    setBusy(true);
    try { setNote(await api.saveNote(note.id, draft)); setDraft(null); toast("Notes saved", undefined, "ok"); }
    catch (e) { toast("Couldn't save", (e as Error).message, "error"); }
    setBusy(false);
  };
  const copy = async () => {
    try { await navigator.clipboard.writeText(note.body_md); toast("Copied", "The notes are on the clipboard as text.", "ok"); }
    catch { toast("Couldn't copy", "Your browser blocked the clipboard. Select the text and copy it by hand.", "error"); }
  };
  const pdf = () => {
    const title = document.title;
    document.title = `${note.course_code} ${note.lesson}`.replace(/[\\/:*?"<>|]+/g, " ");
    document.body.classList.add("printing-note");
    const done = () => { document.body.classList.remove("printing-note"); document.title = title; window.removeEventListener("afterprint", done); };
    window.addEventListener("afterprint", done);
    window.print();
    window.setTimeout(done, 1000);
  };
  const regenerate = async () => {
    setBusy(true);
    const first = note.status === "new";
    try { setNote(await api.regenerateNote(note.id)); setDraft(null); toast(first ? "Making the notes" : "Making the notes again", first ? "The local AI reads the lesson files. You can leave this page." : "The local AI reads the lesson files again."); }
    catch (e) { toast("Couldn't start it", (e as Error).message, "error"); }
    setBusy(false);
  };
  const working = STATUS[note.status].busy;
  return (
    <article className="snote">
      <div className="note-bar">
        <button className="btn ghost sm" onClick={onBack}><Icon name="chev-left" size={16} /> All lessons</button>
        <span className="grow" />
        {view === "ask" ? null : draft === null ? (
          <>
            <button className="btn sm" onClick={() => setDraft(note.body_md)} disabled={note.status !== "ready"}><Icon name="edit" size={16} /> Edit</button>
            <button className="btn sm" onClick={() => void copy()} disabled={note.status !== "ready"}>Copy text</button>
            <button className="btn sm" onClick={pdf} disabled={note.status !== "ready"}>Save as PDF</button>
          </>
        ) : (
          <>
            <button className="btn primary sm" onClick={() => void save()} disabled={busy}>Save</button>
            <button className="btn ghost sm" onClick={() => setDraft(null)} disabled={busy}>Cancel</button>
          </>
        )}
      </div>
      <p className="note-meta"><CourseChip code={note.course_code} name={note.course_name} /> {note.course_name} · {note.lesson}
        {note.generated_at && <> · made {fmtWhen(note.generated_at)}</>}{note.edited && <> · edited by you</>}</p>
      <div className="seg" role="tablist" aria-label="Notes or questions">
        <button role="tab" aria-selected={view === "notes"} onClick={() => setView("notes")}><Icon name="book" size={16} /> Notes</button>
        <button role="tab" aria-selected={view === "ask"} onClick={() => { setDraft(null); setView("ask"); }}><Icon name="chat" size={16} /> Ask the material</button>
      </div>
      {view === "ask" ? <LessonChat note={note} /> : <>
      {note.new_material && (
        <div className="note-alert"><Icon name="info" size={18} /><span>The lecturer added or changed files in this lesson. {note.edited ? "Your edits are kept until you make the notes again." : ""}</span>
          <button className="btn sm" onClick={() => void regenerate()} disabled={busy}>Make notes again</button></div>
      )}
      {note.error && note.status === "ready" && <div className="note-alert warn"><Icon name="alert" size={18} /><span>{note.error}</span></div>}
      {note.status === "new" ? (
        <div className="note-alert"><Icon name="info" size={18} /><span>These notes are not made yet. <b>Make notes</b> reads the slides and documents{note.sources.some((x) => x.kind === "audio" || x.kind === "video") ? " and transcribes the recording" : ""} on this computer. It can take a few minutes.</span>
          <button className="btn primary sm" onClick={() => void regenerate()} disabled={busy}><Icon name="sparkle" size={15} /> Make notes</button></div>
      ) : note.status === "error" ? (
        <div className="note-alert warn"><Icon name="alert" size={18} /><span>{note.error ?? "The notes could not be made."}</span>
          <button className="btn sm" onClick={() => void regenerate()} disabled={busy}>Try again</button></div>
      ) : working ? (
        <div className="note-working"><Spinner label={STATUS[note.status].label} /><span><b>{STATUS[note.status].label}</b> The notes appear here when they are ready.</span></div>
      ) : draft !== null ? (
        <label className="note-edit"><span className="sr">Notes (Markdown)</span>
          <textarea value={draft} onChange={(e) => setDraft(e.target.value)} spellCheck autoFocus />
          <small className="muted"># Heading · ## Section · - point · **bold**</small></label>
      ) : (
        <div className="note-print"><Markdown text={note.body_md} /></div>
      )}
      {note.status === "ready" && draft === null && (
        <p className="note-foot"><button className="as-clear" onClick={() => void regenerate()} disabled={busy}>Make the notes again from the lesson files{note.edited ? " (drops your edits)" : ""}</button></p>
      )}
      </>}
    </article>
  );
}

/** Smart Notes: lessons of the courses the student follows, from the files lecturers upload to UniLearn. */
export function SmartNotes({ noteId, openNote }: { noteId: number | null; openNote: (id: number | null) => void }) {
  const toast = useToast();
  const [data, setData] = useState<NotesList | null>(null);
  const [syncing, setSyncing] = useState(false);
  const first = useRef(true);
  const load = useCallback(() => api.notes().then(setData).catch((e: Error) => toast("Couldn't load Smart Notes", e.message, "error")), [toast]);
  const sync = useCallback(async (quiet = false) => {
    setSyncing(true);
    try {
      const r = await api.syncNotes();
      setData(r);
      if (!quiet) toast("Materials checked", `${r.lessons} lesson(s)${r.not_made ? `, ${r.not_made} without notes yet: press Make notes when you want them` : ""}`, "ok");
    } catch (e) { if (!quiet) toast("Couldn't sync the materials", (e as Error).message, "error"); else void load(); }
    setSyncing(false);
  }, [toast, load]);
  const make = useCallback(async (l: LessonRow) => {
    try {
      await api.regenerateNote(l.id);
      toast("Making the notes", `${l.lesson}: the local AI reads the files. The status updates here.`);
      void load();
    } catch (e) { toast("Couldn't start it", (e as Error).message, "error"); }
  }, [toast, load]);
  // first visit: look for new files right away
  useEffect(() => { if (first.current) { first.current = false; void sync(true); } }, [sync]);
  const busy = !!data?.courses.some((c) => c.lessons.some((l) => STATUS[l.status].busy));
  useEffect(() => {   // refresh while something is being made
    if (!busy || noteId !== null) return;
    const t = window.setInterval(() => void load(), 3000);
    return () => clearInterval(t);
  }, [busy, load, noteId]);

  if (noteId !== null) return <NoteView id={noteId} onBack={() => { openNote(null); void load(); }} />;
  return (
    <section aria-label="Smart Notes">
      <div className="notes-h">
        <p className="panel-sub">Lessons from UniLearn appear here. Press <b>Make notes</b> on a lesson when you want it: the slides, documents and recordings become study notes (summary, key points, definitions). Everything runs on this computer.</p>
        <button className="btn sm" onClick={() => void sync()} disabled={syncing}><Icon name="sync" size={16} /> {syncing ? "Checking…" : "Sync materials"}</button>
      </div>
      {data && !data.transcription && <div className="note-alert warn"><Icon name="alert" size={18} /><span>Speech-to-text is not installed, so recordings are skipped. Start the app with Run &amp; Go to install it.</span></div>}
      {!data ? <Skeleton lines={3} /> : !data.connected ? (
        <Empty icon="link" title="Connect UniLearn first" action={<a className="btn primary" href="#connections">Open Connect</a>}>
          Smart Notes reads the files your lecturers upload to UniLearn (Moodle).
        </Empty>
      ) : data.courses.length === 0 ? (
        <Empty icon="book" title={syncing ? "Looking for lesson materials…" : "No lesson materials yet"}>
          When a lecturer uploads slides, documents or a recording to one of your courses, the notes appear here after the next sync.
        </Empty>
      ) : data.courses.map((c) => (
        <div key={c.code} className="notes-course">
          <h3><CourseChip code={c.code} name={c.name} /> {c.name}</h3>
          <div className="lessons">{c.lessons.map((l) => <LessonCard key={l.id} l={l} onOpen={() => openNote(l.id)} onMake={() => void make(l)} />)}</div>
        </div>
      ))}
    </section>
  );
}
