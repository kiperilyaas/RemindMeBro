// Hub · lecturer area in the shared minimal staff style (same kit as UniLearn and UniSIS staff apps).
import { BRAND } from "../../components/Brand";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../../api/client";
import type { CourseWithStats, Deadline, PublishResult, Source } from "../../api/types";
import { SOURCES } from "../../lib/domain";
import { useLecturer } from "../../state/lecturer";
import { useSession } from "../../state/session";
import {
  PageHead, Pill, Scenarios, StaffShell, Stat, ToastHost, fmtDate, fmtDateTime, toLocalInput, useToast, type ScenarioView, type SystemInfo,
} from "../../staff/kit";

const SYSTEM: SystemInfo = { name: "Remind Me Bro", area: "Lecturers", mark: "R", accent: "#E4572E", logo: BRAND.icon };
const CHANNELS: Source[] = ["teams", "moodle", "email"];
const STATUS_TEXT: Record<PublishResult["status"], [string, "ok" | "info" | "warn"]> = {
  deadline_extracted: ["Deadline found", "ok"], no_deadline: ["No deadline in this message", "info"],
  llm_unavailable: ["Local AI not running", "warn"], parsing_error: ["AI answer unreadable", "warn"],
};

function ResultCard({ r }: { r: PublishResult }) {
  const [label, tone] = STATUS_TEXT[r.status];
  return (
    <div className="st-card st-pad" aria-live="polite">
      <div className="st-row"><Pill tone={tone}>{label}</Pill><span className="faint" style={{ fontSize: 12.5 }}>AI time {r.llm_seconds.toFixed(1)} s</span></div>
      {r.saved_deadline && (
        <dl className="st-kv" style={{ marginTop: 14 }}>
          <dt>Title</dt><dd>{r.saved_deadline.title}</dd>
          <dt>Due</dt><dd>{fmtDateTime(r.saved_deadline.due_date)}</dd>
          <dt>Course</dt><dd>{r.matched_course ?? r.saved_deadline.course_name ?? "—"}</dd>
          {r.updates_existing?.moodle_title && <><dt>Replaces</dt><dd>“{r.updates_existing.moodle_title}” · {fmtDate(r.updates_existing.old_due_date)} → {fmtDate(r.updates_existing.new_due_date)}</dd></>}
        </dl>
      )}
      {r.error && <p className="muted" style={{ fontSize: 13, marginTop: 10 }}>Note: {r.error}</p>}
      {r.raw_llm_output && <details className="st-details" style={{ marginTop: 12 }}><summary style={{ fontSize: 13 }}>Model output</summary>
        <pre className="st-code" style={{ display: "block", whiteSpace: "pre-wrap", padding: 10, marginTop: 8 }}>{r.raw_llm_output}</pre></details>}
    </div>
  );
}

function Courses({ go }: { go: (p: string) => void }) {
  const toast = useToast();
  const { now } = useSession();
  const { courses, extracted, loading, reload } = useLecturer();
  const [adding, setAdding] = useState<number | null>(null);
  const [title, setTitle] = useState("");
  const [due, setDue] = useState(() => { const d = new Date(now); d.setDate(d.getDate() + 14); d.setHours(23, 59, 0, 0); return toLocalInput(d); });
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const addAssignment = async (e: FormEvent, c: CourseWithStats) => {
    e.preventDefault();
    try { await api.prof.createAssignment({ course_id: c.id, title: title.trim(), due_date: due }); toast("Assignment created", `${title} · ${fmtDateTime(due)}`); setAdding(null); setTitle(""); void reload(); }
    catch (e2) { toast("Couldn't create it", (e2 as Error).message, true); }
  };
  const addCourse = async (e: FormEvent) => {
    e.preventDefault();
    try { await api.prof.createCourse({ code: code.trim().toUpperCase(), name: name.trim() }); toast("Course created", name); setCode(""); setName(""); void reload(); }
    catch (e2) { toast("Couldn't create it", (e2 as Error).message, true); }
  };
  return (
    <>
      <PageHead title="Your courses" intro="Post announcements in plain words: the local AI turns dates into deadlines on your students' timeline."
        actions={<button className="st-btn primary" onClick={() => go("announce")}>Post an announcement</button>} />
      <div className="st-grid st-cols-3" style={{ marginBottom: 32 }}>
        <Stat label="Courses" value={courses.length} />
        <Stat label="Deadlines" value={courses.reduce((a, c) => a + c.deadline_count, 0)} />
        <Stat label="Dates found by AI" value={extracted.length} />
      </div>
      <div className="st-card st-scroll">
        {loading ? <div className="st-empty">Loading…</div> : courses.length === 0 ? <div className="st-empty">No courses yet. Create one below.</div> : (
          <table className="st-table">
            <thead><tr><th>Course</th><th className="r">Deadlines</th><th className="r">By AI</th><th>Next deadline</th><th /></tr></thead>
            <tbody>{courses.map((c) => (
              <tr key={c.id}>
                <td><span className="t">{c.name}</span><span className="s">{c.code}</span></td>
                <td className="r num">{c.deadline_count}</td><td className="r num">{c.ai_deadline_count}</td>
                {adding === c.id ? (
                  <td colSpan={2}><form className="st-row" onSubmit={(e) => void addAssignment(e, c)}>
                    <input className="st-input sm" style={{ width: 220 }} placeholder="Assignment title" value={title} onChange={(e) => setTitle(e.target.value)} required minLength={3} aria-label="Assignment title" />
                    <input type="datetime-local" className="st-input sm" value={due} onChange={(e) => setDue(e.target.value)} aria-label="Due" />
                    <button className="st-btn primary sm">Create</button><button type="button" className="st-btn ghost sm" onClick={() => setAdding(null)}>Cancel</button>
                  </form></td>
                ) : <>
                  <td>{c.next_deadline ? <><span className="t">{c.next_deadline.title}</span><span className="s">{fmtDateTime(c.next_deadline.due_date)}</span></> : <span className="muted">—</span>}</td>
                  <td className="r"><span className="st-row" style={{ justifyContent: "flex-end" }}>
                    <button className="st-btn sm" onClick={() => go(`announce?course=${c.id}`)}>Announce</button>
                    <button className="st-btn ghost sm" onClick={() => setAdding(c.id)}>+ Assignment</button></span></td></>}
              </tr>))}</tbody>
          </table>
        )}
      </div>
      <details className="st-card st-pad st-details" style={{ marginTop: 24 }}>
        <summary>New course</summary>
        <form className="st-row" onSubmit={(e) => void addCourse(e)} style={{ marginTop: 14, alignItems: "flex-end" }}>
          <label className="st-field">Code<input value={code} onChange={(e) => setCode(e.target.value)} required placeholder="BEHAV-2026" /></label>
          <label className="st-field" style={{ flex: 1, minWidth: 200 }}>Name<input value={name} onChange={(e) => setName(e.target.value)} required placeholder="Behavioural Finance" /></label>
          <button className="st-btn">Create course</button>
        </form>
      </details>
    </>
  );
}

function Announce({ preset }: { preset: number | null }) {
  const toast = useToast();
  const { courses, reload } = useLecturer();
  const [courseId, setCourseId] = useState<number | null>(preset);
  const [channel, setChannel] = useState<Source>("teams");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<PublishResult | null>(null);
  useEffect(() => { if (courseId === null && courses[0]) setCourseId(preset ?? courses[0].id); }, [courses, courseId, preset]);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!courseId) return;
    setBusy(true); setResult(null);
    try { setResult(await api.prof.publish({ course_id: courseId, content: text.trim(), channel })); setText(""); void reload(); }
    catch (e2) { toast("Couldn't publish", (e2 as Error).message, true); }
    finally { setBusy(false); }
  };
  return (
    <>
      <PageHead title="Post an announcement" intro="Write as you would in a Teams channel. The local AI reads it and, if there is a date, adds a deadline for your students." />
      <div className="st-split">
        <form className="st-card st-pad st-form" onSubmit={submit}>
          <label className="st-field">Course<select value={courseId ?? ""} onChange={(e) => setCourseId(Number(e.target.value))}>{courses.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
          <div className="st-field">Channel
            <div className="st-seg" role="radiogroup" aria-label="Channel">{CHANNELS.map((ch) => (
              <label key={ch} className={channel === ch ? "on" : ""}><input type="radio" name="ch" checked={channel === ch} onChange={() => setChannel(ch)} />{SOURCES[ch].label}</label>))}</div>
          </div>
          <label className="st-field">Message<textarea rows={6} value={text} onChange={(e) => setText(e.target.value)} required minLength={5} placeholder="e.g. The report is now due next Friday at noon." /></label>
          <div><button className="st-btn primary lg" disabled={busy || text.trim().length < 5}>{busy ? "The AI is reading…" : "Publish"}</button></div>
        </form>
        <div>{result ? <ResultCard r={result} /> : <div className="st-card st-empty">What the AI understood appears here.</div>}</div>
      </div>
    </>
  );
}

function Extracted() {
  const toast = useToast();
  const { extracted, loading, reload } = useLecturer();
  const [edit, setEdit] = useState<{ id: number; title: string; due: string } | null>(null);
  const [confirm, setConfirm] = useState<number | null>(null);
  const save = async () => {
    if (!edit) return;
    try { await api.prof.updateExtracted(edit.id, { title: edit.title, due_date: edit.due }); toast("Saved", "Students see the corrected date."); setEdit(null); void reload(); }
    catch (e) { toast("Couldn't save", (e as Error).message, true); }
  };
  const discard = async (d: Deadline) => {
    try { await api.prof.deleteExtracted(d.id); toast("Discarded", d.replaces ? "The original date is visible again." : "Students no longer see it."); setConfirm(null); void reload(); }
    catch (e) { toast("Couldn't discard", (e as Error).message, true); }
  };
  const list = [...extracted].sort((a, b) => a.due_date.localeCompare(b.due_date));
  return (
    <>
      <PageHead title="Dates found by AI" intro="Every date the AI extracted from your messages. Correct it if it's wrong, or discard it." />
      <div className="st-card st-scroll">
        {loading ? <div className="st-empty">Loading…</div> : list.length === 0 ? <div className="st-empty">Nothing yet. Post an announcement with a date.</div> : (
          <table className="st-table">
            <thead><tr><th>Deadline</th><th>Due</th><th>From</th><th /></tr></thead>
            <tbody>{list.map((d) => (
              <tr key={d.id}>
                {edit?.id === d.id ? (
                  <td colSpan={4}><span className="st-row">
                    <input className="st-input sm" style={{ width: 260 }} value={edit.title} onChange={(e) => setEdit({ ...edit, title: e.target.value })} aria-label="Title" />
                    <input type="datetime-local" className="st-input sm" value={edit.due} onChange={(e) => setEdit({ ...edit, due: e.target.value })} aria-label="Due" />
                    <button className="st-btn primary sm" onClick={() => void save()}>Save</button><button className="st-btn ghost sm" onClick={() => setEdit(null)}>Cancel</button></span></td>
                ) : <>
                  <td><span className="t">{d.title}</span><span className="s">{d.course_name ?? "—"}{d.source_message ? ` · “${d.source_message.slice(0, 80)}${d.source_message.length > 80 ? "…" : ""}”` : ""}</span></td>
                  <td className="num">{fmtDateTime(d.due_date)}{d.replaces && <span className="s">was {fmtDate(d.replaces.old_due_date)}</span>}</td>
                  <td><Pill plain>{SOURCES[d.source].label}</Pill>{d.superseded_by_id && <span className="s">replaced later</span>}</td>
                  <td className="r"><span className="st-row" style={{ justifyContent: "flex-end" }}>
                    <button className="st-btn sm" onClick={() => setEdit({ id: d.id, title: d.title, due: d.due_date.slice(0, 16) })}>Correct</button>
                    {confirm === d.id ? <><button className="st-btn danger solid sm" onClick={() => void discard(d)}>Discard</button><button className="st-btn ghost sm" onClick={() => setConfirm(null)}>Keep</button></>
                      : <button className="st-btn ghost sm" onClick={() => setConfirm(d.id)}>Discard</button>}</span></td></>}
              </tr>))}</tbody>
          </table>
        )}
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Ready-made cases (run through the hub API as the signed-in lecturer)
// ---------------------------------------------------------------------------
interface HubCase { id: string; title: string; what: string; check: string[]; message?: string; run: (c: CourseWithStats, now: Date) => Promise<{ text: string; undo?: () => Promise<void> }> }

/** "Monday 7 December": the Monday two weeks from now, written in words for the AI to read. */
function inTwoWeeks(): string {
  const d = new Date(); d.setDate(d.getDate() + 14 - ((d.getDay() + 6) % 7));
  return d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });
}

const CASES: HubCase[] = [
  { id: "extend", title: "Extend a deadline in a message",
    what: `Publishes on Teams: “Good news: the deadline for the group project is extended to ${inTwoWeeks()} at 18:00.”`,
    check: [`Student hub → Timeline → ${inTwoWeeks()}: the project, “found by AI”`, "If the course had an official date, it shows “Moved from … →”"],
    run: async (c) => {
      const r = await api.prof.publish({ course_id: c.id, channel: "teams", content: `Good news: the deadline for the group project is extended to ${inTwoWeeks()} at 18:00.` });
      const id = r.saved_deadline?.id;
      return { text: r.saved_deadline ? `AI found: ${r.saved_deadline.title}, ${fmtDateTime(r.saved_deadline.due_date)}.` : `AI result: ${STATUS_TEXT[r.status][0]}.`, undo: id ? async () => { await api.prof.deleteExtracted(id); } : undefined };
    } },
  { id: "relative", title: "Use a relative date",
    what: "Publishes by email: “Please upload your reading notes by next Monday at noon.” The AI must work out the real date.",
    check: ["Student hub → Timeline → next Monday, 12:00", "Inbox → the email, marked “date found”"],
    run: async (c) => {
      const r = await api.prof.publish({ course_id: c.id, channel: "email", content: "Please upload your reading notes by next Monday at noon." });
      const id = r.saved_deadline?.id;
      return { text: r.saved_deadline ? `AI found: ${fmtDateTime(r.saved_deadline.due_date)}.` : `AI result: ${STATUS_TEXT[r.status][0]}.`, undo: id ? async () => { await api.prof.deleteExtracted(id); } : undefined };
    } },
  { id: "nodate", title: "Post a message without a date",
    what: "Publishes on Teams: “Great discussion today, thanks everyone! The slides are on UniLearn.” Nothing should be added.",
    check: ["Student hub → Inbox → the message, with no date", "Timeline: nothing new"],
    run: async (c) => {
      const r = await api.prof.publish({ course_id: c.id, channel: "teams", content: "Great discussion today, thanks everyone! The slides are on UniLearn." });
      return { text: `AI result: ${STATUS_TEXT[r.status][0]}.` };
    } },
  { id: "assignment", title: "Create a formal assignment",
    what: "Creates “Short essay · Bank regulation”, due in 5 days at 23:59, without any AI.",
    check: ["Student hub → Timeline → in 5 days: the essay", "Semester → it counts in that week's workload"],
    run: async (c, now) => {
      const due = new Date(now); due.setDate(due.getDate() + 5); due.setHours(23, 59, 0, 0);
      await api.prof.createAssignment({ course_id: c.id, title: "Short essay · Bank regulation", due_date: toLocalInput(due) });
      return { text: `Assignment created, due ${fmtDateTime(toLocalInput(due))}.` };
    } },
];

function Cases() {
  const toast = useToast();
  const { now } = useSession();
  const { courses, reload } = useLecturer();
  const [done, setDone] = useState<Record<string, { undo?: () => Promise<void> }>>({});
  const course = courses[0];
  const items: ScenarioView[] = CASES.map((c) => ({
    id: c.id, title: c.title, actor: course ? `You · ${course.name}` : "You", what: c.what, check: c.check,
    status: !course ? "blocked" : done[c.id] ? "done" : "ready", can_undo: !!done[c.id]?.undo, blocked_reason: "Create a course first.",
  }));
  const run = useCallback(async (id: string) => {
    const c = CASES.find((x) => x.id === id);
    if (!c || !course) return;
    try { const r = await c.run(course, now); setDone((d) => ({ ...d, [id]: { undo: r.undo } })); toast("Case done", r.text); void reload(); }
    catch (e) { toast("Couldn't run the case", (e as Error).message, true); }
  }, [course, now, reload, toast]);
  const undo = useCallback(async (id: string) => {
    try { await done[id]?.undo?.(); setDone((d) => { const n = { ...d }; delete n[id]; return n; }); toast("Undone", "The extracted date was discarded."); void reload(); }
    catch (e) { toast("Couldn't undo", (e as Error).message, true); }
  }, [done, reload, toast]);
  return (
    <>
      <PageHead title="Try a case" intro={`Ready-made announcements for ${course?.name ?? "your course"}. Run one, then open the student hub as Giulia.`} />
      <Scenarios items={items} onRun={run} onUndo={undo} hubUrl={location.origin + "/"} />
    </>
  );
}

export function LecturerArea({ path, query, navigate }: { path: string; query: URLSearchParams; navigate: (p: string) => void }) {
  const { user, logout } = useSession();
  if (!user) return null;
  const nav = [{ id: "", label: "Courses" }, { id: "announce", label: "Announce" }, { id: "extracted", label: "Dates found by AI" }, { id: "cases", label: "Try a case", highlight: true }];
  return (
    <ToastHost>
      <StaffShell system={SYSTEM} nav={nav} current={path} onNavigate={navigate} user={{ fullname: user.full_name, role: "lecturer" }} onLogout={() => logout()}>
        {path === "" && <Courses go={navigate} />}
        {path === "announce" && <Announce key={query.get("course") ?? "x"} preset={Number(query.get("course")) || null} />}
        {path === "extracted" && <Extracted />}
        {path === "cases" && <Cases />}
      </StaffShell>
    </ToastHost>
  );
}
