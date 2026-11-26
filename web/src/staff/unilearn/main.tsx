// UniLearn · Teaching (teachers + site admin). Served by UniLearn at /staff.
import { StrictMode, useCallback, useEffect, useState, type FormEvent } from "react";
import { createRoot } from "react-dom/client";
import {
  PageHead, Pill, StaffErrorBoundary, StaffLogin, StaffShell, ToastHost, fmtDateTime, staffFetch, toLocalInput,
  useHashPath, useStaffSession, useToast, type SystemInfo,
} from "../kit";

const SYSTEM: SystemInfo = { name: "UniLearn", area: "Teaching", mark: "UL", accent: "#B5651D" };
interface Me { fullname: string; role: string; username: string; hub_url: string; now: string }
interface CourseRow { id: number; shortname: string; fullname: string; summary: string; room: string; teachers: string[]; students: number; assignments: number; announcements: number; next_due: { name: string; duedate: string } | null }
interface Person { id: number; fullname: string; username: string }
interface CourseDetail extends CourseRow {
  student_list: Person[]; can_delete: boolean;
  assignment_list: { id: number; name: string; intro: string; duedate: string; submitted: number; students: number }[];
  announcement_list: { id: number; subject: string; message: string; created: string; author: string }[];
  events: { id: number; name: string; timestart: string; minutes: number; location: string }[];
  sections: Section[];
}
interface Section { id: number; name: string; summary: string; position: number; files: { id: number; name: string; filename: string; size: number; mimetype: string; uploaded: string }[] }

const fmtSize = (n: number) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);

function Materials({ courseId, sections, onChange }: { courseId: number; sections: Section[]; onChange: () => void }) {
  const toast = useToast();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState<number | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);
  const addSection = async (e: FormEvent) => {
    e.preventDefault();
    try { await staffFetch(`/staff/api/courses/${courseId}/sections`, { method: "POST", body: { name } }); setName(""); toast("Lesson added", "Now upload slides, documents or the recording."); onChange(); }
    catch (e2) { toast("Couldn't add it", (e2 as Error).message, true); }
  };
  const upload = async (sectionId: number, files: FileList | null) => {
    if (!files?.length) return;
    setBusy(sectionId);
    try {
      for (const f of Array.from(files)) {
        const body = new FormData();
        body.append("file", f);
        const res = await fetch(`/staff/api/sections/${sectionId}/files`, { method: "POST", credentials: "same-origin", headers: { "X-Requested-With": "staff" }, body });
        if (!res.ok) { const d = await res.json().catch(() => null) as { detail?: string } | null; throw new Error(d?.detail ?? `Upload failed (${res.status})`); }
      }
      toast(files.length === 1 ? "File uploaded" : `${files.length} files uploaded`, "Students with Smart Notes get notes after their next sync.");
    } catch (e) { toast("Couldn't upload", (e as Error).message, true); }
    setBusy(null); onChange();
  };
  const del = async (path: string) => {
    try { await staffFetch(path, { method: "DELETE" }); setConfirm(null); toast("Deleted"); onChange(); }
    catch (e) { toast("Couldn't delete", (e as Error).message, true); }
  };
  return (
    <section className="st-section"><h2>Lessons and materials <small>{sections.length}</small></h2>
      <div className="st-card"><ul className="st-list">
        {sections.length === 0 && <li className="st-empty">No lessons yet. Add one below, then upload slides (PDF, PPTX), documents (DOCX, TXT) or the recording (audio or video).</li>}
        {sections.map((sec) => (
          <li key={sec.id} style={{ display: "block" }}>
            <div className="st-row" style={{ justifyContent: "space-between" }}>
              <div className="t">{sec.position}. {sec.name}</div>
              <span className="st-row">
                <label className="st-btn sm" aria-disabled={busy === sec.id}>{busy === sec.id ? "Uploading…" : "Upload files"}
                  <input type="file" multiple hidden disabled={busy !== null} accept=".pdf,.pptx,.docx,.txt,.md,.mp3,.m4a,.wav,.ogg,.flac,.aac,.mp4,.mov,.webm,.mkv"
                    onChange={(e) => { void upload(sec.id, e.target.files); e.target.value = ""; }} /></label>
                {confirm === `s${sec.id}` ? <><button className="st-btn danger solid sm" onClick={() => void del(`/staff/api/sections/${sec.id}`)}>Delete lesson</button><button className="st-btn ghost sm" onClick={() => setConfirm(null)}>Keep</button></>
                  : <button className="st-btn ghost sm" onClick={() => setConfirm(`s${sec.id}`)}>Delete</button>}
              </span>
            </div>
            {sec.files.length === 0 ? <div className="s">No files yet.</div> : (
              <ul className="st-list" style={{ marginTop: 6 }}>{sec.files.map((f) => (
                <li key={f.id}><div className="grow"><div className="t">{f.filename}</div><div className="s">{fmtSize(f.size)} · {fmtDateTime(f.uploaded)}</div></div>
                  {confirm === `f${f.id}` ? <span className="st-row"><button className="st-btn danger solid sm" onClick={() => void del(`/staff/api/files/${f.id}`)}>Delete</button><button className="st-btn ghost sm" onClick={() => setConfirm(null)}>Keep</button></span>
                    : <button className="st-btn ghost sm" onClick={() => setConfirm(`f${f.id}`)} aria-label={`Delete ${f.filename}`}>Delete</button>}</li>))}</ul>)}
          </li>))}
        <li><form className="st-row" style={{ width: "100%" }} onSubmit={addSection}>
          <input className="st-input sm" style={{ flex: 1 }} value={name} onChange={(e) => setName(e.target.value)} required minLength={1} placeholder="Lesson 3 · Agency theory" aria-label="Lesson name" />
          <button className="st-btn sm primary">Add lesson</button></form></li>
      </ul></div>
    </section>
  );
}
interface WS { endpoints: { token: string; rest: string }; functions: string[]; tokens: { id: number; user: string; hint: string; client: string; created: string; lastaccess: string | null }[];
  log: { id: number; at: string; username: string | null; function: string; status: string }[] }

function NewCourse({ admin, onDone }: { admin: boolean; onDone: (id: number) => void }) {
  const toast = useToast();
  const [teachers, setTeachers] = useState<Person[]>([]);
  const [f, setF] = useState({ shortname: "", fullname: "", room: "", summary: "", teacher_id: "", enrol_all_students: false });
  useEffect(() => { if (admin) staffFetch<{ teachers: Person[] }>("/staff/api/people").then((p) => { setTeachers(p.teachers); setF((x) => ({ ...x, teacher_id: x.teacher_id || String(p.teachers[0]?.id ?? "") })); }).catch(() => undefined); }, [admin]);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const c = await staffFetch<CourseRow>("/staff/api/courses", { method: "POST", body: { ...f, teacher_id: admin ? Number(f.teacher_id) : null } });
      toast("Course created", `${c.shortname} · ${c.fullname} · ${c.students} student(s) enrolled`); onDone(c.id);
    } catch (e2) { toast("Couldn't create it", (e2 as Error).message, true); }
  };
  return (
    <details className="st-card st-pad st-details">
      <summary>New course</summary>
      <form className="st-form" onSubmit={submit} style={{ marginTop: 16 }}>
        <div className="st-grid st-cols-3">
          <label className="st-field">Course code<input value={f.shortname} onChange={(e) => setF({ ...f, shortname: e.target.value })} required minLength={2} placeholder="MICRO-2026" /></label>
          <label className="st-field">Course name<input value={f.fullname} onChange={(e) => setF({ ...f, fullname: e.target.value })} required minLength={2} placeholder="Microeconomics" /></label>
          <label className="st-field">Room<input value={f.room} onChange={(e) => setF({ ...f, room: e.target.value })} placeholder="Room 3B" /></label>
          {admin && <label className="st-field">Teacher<select value={f.teacher_id} onChange={(e) => setF({ ...f, teacher_id: e.target.value })}>{teachers.map((t) => <option key={t.id} value={t.id}>{t.fullname}</option>)}</select></label>}
        </div>
        <label className="st-field">Summary<textarea value={f.summary} onChange={(e) => setF({ ...f, summary: e.target.value })} placeholder="What the course is about (optional)" /></label>
        <label className="st-tick"><input type="checkbox" checked={f.enrol_all_students} onChange={(e) => setF({ ...f, enrol_all_students: e.target.checked })} />Enrol every student now (usually students join the courses they choose in UniSIS)</label>
        <div><button className="st-btn primary">Create course</button></div>
      </form>
    </details>
  );
}

function Courses({ go, admin }: { go: (p: string) => void; admin: boolean }) {
  const [rows, setRows] = useState<CourseRow[] | null>(null);
  useEffect(() => { staffFetch<CourseRow[]>("/staff/api/courses").then(setRows).catch(() => setRows([])); }, []);
  return (
    <>
      <PageHead title={admin ? "All courses" : "Your courses"} intro="Create a course, then add assignments, announcements and calendar events. Students see every change in UniLearn and, after a sync, in Remind Me Bro. Use the same course code as in UniSIS and Remind Me Bro, so the three systems treat it as one course." />
      <div style={{ marginBottom: 24 }}><NewCourse admin={admin} onDone={(id) => go(`course/${id}`)} /></div>
      <div className="st-card">
        {!rows ? <div className="st-empty">Loading…</div> : rows.length === 0 ? <div className="st-empty">No courses yet. Create the first one above.</div> : (
          <div className="st-scroll"><table className="st-table">
            <thead><tr><th>Code · Course</th><th className="r">Students</th><th className="r">Assignments</th><th>Next due</th><th /></tr></thead>
            <tbody>{rows.map((c) => (
              <tr key={c.id}>
                <td><span className="t"><span className="mono">{c.shortname}</span> · {c.fullname}</span><span className="s">{c.room ? `${c.room} · ` : ""}{c.teachers.join(", ")}</span></td>
                <td className="r num">{c.students}</td><td className="r num">{c.assignments}</td>
                <td>{c.next_due ? <><span className="t">{c.next_due.name}</span><span className="s">{fmtDateTime(c.next_due.duedate)}</span></> : <span className="muted">—</span>}</td>
                <td className="r"><button className="st-btn sm" onClick={() => go(`course/${c.id}`)}>Open</button></td>
              </tr>))}</tbody>
          </table></div>
        )}
      </div>
    </>
  );
}

function DueEditor({ id, value, onSaved }: { id: number; value: string; onSaved: () => void }) {
  const toast = useToast();
  const [v, setV] = useState(value.slice(0, 16));
  const [open, setOpen] = useState(false);
  const save = async () => {
    try { await staffFetch(`/staff/api/assignments/${id}`, { method: "PATCH", body: { duedate: v } }); toast("Due date changed", fmtDateTime(v)); setOpen(false); onSaved(); }
    catch (e) { toast("Couldn't save", (e as Error).message, true); }
  };
  if (!open) return <button className="st-link" style={{ whiteSpace: "nowrap" }} onClick={() => setOpen(true)} aria-label={`Due ${fmtDateTime(value)}, change`}>{fmtDateTime(value)}</button>;
  return <span className="st-row"><input type="datetime-local" className="st-input sm" value={v} onChange={(e) => setV(e.target.value)} aria-label="New due date" />
    <button className="st-btn primary sm" onClick={() => void save()}>Save</button><button className="st-btn ghost sm" onClick={() => setOpen(false)}>Cancel</button></span>;
}

function CoursePage({ id, go }: { id: number; go: (p: string) => void }) {
  const toast = useToast();
  const [c, setC] = useState<CourseDetail | null>(null);
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [name, setName] = useState("");
  const [due, setDue] = useState(() => { const d = new Date(); d.setDate(d.getDate() + 14); d.setHours(23, 59, 0, 0); return toLocalInput(d); });
  const [confirm, setConfirm] = useState<string | null>(null);
  const [students, setStudents] = useState<Person[]>([]);
  const [pick, setPick] = useState("");
  const [ev, setEv] = useState(() => { const d = new Date(); d.setDate(d.getDate() + 7); d.setHours(9, 0, 0, 0); return { name: "", timestart: toLocalInput(d), minutes: "90", location: "" }; });
  const load = useCallback(() => staffFetch<CourseDetail>(`/staff/api/courses/${id}`).then(setC).catch((e: Error) => toast("Couldn't load the course", e.message, true)), [id, toast]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { staffFetch<{ students: Person[] }>("/staff/api/people").then((p) => setStudents(p.students)).catch(() => undefined); }, []);
  const enrol = async (uid: number, add: boolean) => {
    try { await staffFetch(`/staff/api/courses/${id}/students/${uid}`, { method: add ? "POST" : "DELETE" }); setPick(""); toast(add ? "Student enrolled" : "Student removed"); void load(); }
    catch (e) { toast("Couldn't change it", (e as Error).message, true); }
  };
  const addEvent = async (e: FormEvent) => {
    e.preventDefault();
    try { await staffFetch(`/staff/api/courses/${id}/events`, { method: "POST", body: { ...ev, minutes: Number(ev.minutes) } }); toast("Event added", `${ev.name} · ${fmtDateTime(ev.timestart)}`); setEv({ ...ev, name: "" }); void load(); }
    catch (e2) { toast("Couldn't add it", (e2 as Error).message, true); }
  };
  const [edit, setEdit] = useState<{ shortname: string; fullname: string; room: string; summary: string } | null>(null);
  const saveEdit = async (e: FormEvent) => {
    e.preventDefault();
    if (!edit) return;
    try { await staffFetch(`/staff/api/courses/${id}`, { method: "PATCH", body: edit }); toast("Course saved", `${edit.shortname.toUpperCase()} · ${edit.fullname}${edit.room ? ` · ${edit.room}` : ""}`); setEdit(null); void load(); }
    catch (e2) { toast("Couldn't save", (e2 as Error).message, true); }
  };
  const removeCourse = async () => {
    try { await staffFetch(`/staff/api/courses/${id}`, { method: "DELETE" }); toast("Course deleted"); go(""); }
    catch (e) { toast("Couldn't delete", (e as Error).message, true); }
  };
  const post = async (e: FormEvent) => {
    e.preventDefault();
    try { await staffFetch(`/staff/api/courses/${id}/announcements`, { method: "POST", body: { subject, message } }); setSubject(""); setMessage(""); toast("Announcement posted", c && c.students > 0 ? `Sent to ${c.students} student(s): it reaches their Remind Me Bro Inbox within a minute.` : "Nobody is enrolled in this course, so no student receives it."); void load(); }
    catch (e2) { toast("Couldn't post", (e2 as Error).message, true); }
  };
  const addAssign = async (e: FormEvent) => {
    e.preventDefault();
    try { await staffFetch(`/staff/api/courses/${id}/assignments`, { method: "POST", body: { name, duedate: due } }); setName(""); toast("Assignment added", `Due ${fmtDateTime(due)}`); void load(); }
    catch (e2) { toast("Couldn't add it", (e2 as Error).message, true); }
  };
  const del = async (kind: "assignments" | "announcements" | "events", itemId: number) => {
    try { await staffFetch(`/staff/api/${kind}/${itemId}`, { method: "DELETE" }); setConfirm(null); toast("Deleted"); void load(); }
    catch (e) { toast("Couldn't delete", (e as Error).message, true); }
  };
  if (!c) return <div className="st-card st-empty">Loading…</div>;
  return (
    <>
      <PageHead crumb={<><button onClick={() => go("")}>Courses</button><span>/</span><span>{c.shortname}</span></>} title={`${c.shortname} · ${c.fullname}`}
        intro={`${c.room ? `Room ${c.room} · ` : "No room yet · "}${c.students} student(s) · ${c.teachers.join(", ")}`}
        actions={c.can_delete && (confirm === "course" ? <span className="st-row"><button className="st-btn danger solid sm" onClick={() => void removeCourse()}>Delete course and its content</button><button className="st-btn ghost sm" onClick={() => setConfirm(null)}>Keep</button></span>
          : <button className="st-btn ghost sm" onClick={() => setConfirm("course")}>Delete course</button>)} />
      <div className="st-split">
        <div>
          <Materials courseId={c.id} sections={c.sections ?? []} onChange={() => void load()} />
          <section className="st-section">
            <h2>Assignments <small>click a date to change it</small></h2>
            <div className="st-card st-scroll"><table className="st-table">
              <thead><tr><th>Assignment</th><th>Due</th><th className="r">Submitted</th><th /></tr></thead>
              <tbody>{c.assignment_list.length === 0 ? <tr><td colSpan={4} className="st-empty">No assignments.</td></tr> : c.assignment_list.map((a) => (
                <tr key={a.id}>
                  <td><span className="t">{a.name}</span>{a.intro && <span className="s">{a.intro}</span>}</td>
                  <td><DueEditor id={a.id} value={a.duedate} onSaved={() => void load()} /></td>
                  <td className="r num">{a.submitted}/{a.students}</td>
                  <td className="r">{confirm === `a${a.id}` ? <span className="st-row"><button className="st-btn danger solid sm" onClick={() => void del("assignments", a.id)}>Delete</button><button className="st-btn ghost sm" onClick={() => setConfirm(null)}>Keep</button></span>
                    : <button className="st-btn ghost sm" onClick={() => setConfirm(`a${a.id}`)} aria-label={`Delete ${a.name}`}>Delete</button>}</td>
                </tr>))}</tbody>
            </table></div>
          </section>
          <section className="st-section">
            <h2>Announcements <small>{c.announcement_list.length}</small></h2>
            <div className="st-card"><ul className="st-list">{c.announcement_list.length === 0 ? <li className="st-empty">No announcements yet.</li> : c.announcement_list.map((d) => (
              <li key={d.id}>
                <div className="grow"><div className="t">{d.subject}</div><div className="s">{d.author} · {fmtDateTime(d.created)}</div><p>{d.message}</p></div>
                {confirm === `d${d.id}` ? <span className="st-row"><button className="st-btn danger solid sm" onClick={() => void del("announcements", d.id)}>Delete</button><button className="st-btn ghost sm" onClick={() => setConfirm(null)}>Keep</button></span>
                  : <button className="st-btn ghost sm" onClick={() => setConfirm(`d${d.id}`)}>Delete</button>}
              </li>))}</ul></div>
          </section>
          <section className="st-section"><h2>Calendar <small>{c.events.length}</small></h2>
            <div className="st-card"><ul className="st-list">{c.events.length === 0 ? <li className="st-empty">No events yet.</li> : c.events.map((e) => (
              <li key={e.id}><div className="grow"><div className="t">{e.name}</div><div className="s">{fmtDateTime(e.timestart)} · {e.minutes} min{e.location ? ` · ${e.location}` : ""}</div></div>
                {confirm === `e${e.id}` ? <span className="st-row"><button className="st-btn danger solid sm" onClick={() => void del("events", e.id)}>Delete</button><button className="st-btn ghost sm" onClick={() => setConfirm(null)}>Keep</button></span>
                  : <button className="st-btn ghost sm" onClick={() => setConfirm(`e${e.id}`)}>Delete</button>}</li>))}</ul></div>
          </section>
          <section className="st-section"><h2>Students <small>{c.student_list.length}</small></h2>
            <div className="st-card"><ul className="st-list">
              {c.student_list.length === 0 && <li className="st-empty">Nobody is enrolled yet.</li>}
              {c.student_list.map((st) => (
                <li key={st.id}><div className="grow"><div className="t">{st.fullname}</div><div className="s">{st.username}</div></div>
                  <button className="st-btn ghost sm" onClick={() => void enrol(st.id, false)}>Remove</button></li>))}
              {students.some((st) => !c.student_list.find((x) => x.id === st.id)) && (
                <li><select className="st-input sm" value={pick} onChange={(e) => setPick(e.target.value)} aria-label="Student to enrol">
                  <option value="">Choose a student…</option>
                  {students.filter((st) => !c.student_list.find((x) => x.id === st.id)).map((st) => <option key={st.id} value={st.id}>{st.fullname}</option>)}</select>
                  <button className="st-btn sm" disabled={!pick} onClick={() => void enrol(Number(pick), true)}>Enrol</button></li>)}
            </ul></div>
          </section>
        </div>
        <div className="st-grid">
          {edit ? (
            <form className="st-card st-pad st-form" onSubmit={saveEdit}>
              <h2 style={{ fontSize: 15 }}>Edit course</h2>
              <div className="st-grid st-cols-2">
                <label className="st-field">Course code<input value={edit.shortname} onChange={(e) => setEdit({ ...edit, shortname: e.target.value })} required minLength={2} /></label>
                <label className="st-field">Course name<input value={edit.fullname} onChange={(e) => setEdit({ ...edit, fullname: e.target.value })} required minLength={2} /></label>
              </div>
              <label className="st-field">Room<input value={edit.room} onChange={(e) => setEdit({ ...edit, room: e.target.value })} placeholder="Room 3B" /></label>
              <label className="st-field">Summary<textarea value={edit.summary} onChange={(e) => setEdit({ ...edit, summary: e.target.value })} /></label>
              <p className="muted" style={{ margin: 0, fontSize: 12.5 }}>Upcoming calendar events in the old room move to the new one.</p>
              <span className="st-row"><button className="st-btn primary">Save</button><button type="button" className="st-btn ghost" onClick={() => setEdit(null)}>Cancel</button></span>
            </form>
          ) : (
            <div className="st-card st-pad"><div className="st-row" style={{ justifyContent: "space-between" }}><b>Course details</b>
              <button className="st-btn sm" onClick={() => setEdit({ shortname: c.shortname, fullname: c.fullname, room: c.room, summary: c.summary })}>Edit</button></div>
              <dl className="st-kv" style={{ marginTop: 10 }}><dt>Code</dt><dd className="mono">{c.shortname}</dd><dt>Name</dt><dd>{c.fullname}</dd>
                <dt>Room</dt><dd>{c.room || <span className="muted">not set</span>}</dd></dl></div>
          )}
          <form className="st-card st-pad st-form" onSubmit={post}>
            <h2 style={{ fontSize: 15 }}>Post an announcement</h2>
            {c.students === 0 && <p className="st-warn" role="note">No student is enrolled in this course yet: nobody will receive this announcement. Students join in UniSIS (course registration), or you enrol them in the Students list.</p>}
            <label className="st-field">Subject<input value={subject} onChange={(e) => setSubject(e.target.value)} required minLength={2} /></label>
            <label className="st-field">Message<textarea value={message} onChange={(e) => setMessage(e.target.value)} required placeholder="Dates in plain words are fine: “by next Friday at noon”." /></label>
            <button className="st-btn primary">Post to Announcements</button>
          </form>
          <form className="st-card st-pad st-form" onSubmit={addAssign}>
            <h2 style={{ fontSize: 15 }}>Add an assignment</h2>
            <label className="st-field">Name<input value={name} onChange={(e) => setName(e.target.value)} required minLength={2} placeholder="Problem Set 3" /></label>
            <label className="st-field">Due<input type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} required /></label>
            <button className="st-btn">Add assignment</button>
          </form>
          <form className="st-card st-pad st-form" onSubmit={addEvent}>
            <h2 style={{ fontSize: 15 }}>Add a calendar event</h2>
            <label className="st-field">Name<input value={ev.name} onChange={(e) => setEv({ ...ev, name: e.target.value })} required minLength={2} placeholder="Extra lecture" /></label>
            <label className="st-field">Starts<input type="datetime-local" value={ev.timestart} onChange={(e) => setEv({ ...ev, timestart: e.target.value })} required /></label>
            <div className="st-grid st-cols-2">
              <label className="st-field">Minutes<input type="number" min={5} value={ev.minutes} onChange={(e) => setEv({ ...ev, minutes: e.target.value })} /></label>
              <label className="st-field">Room<input value={ev.location} onChange={(e) => setEv({ ...ev, location: e.target.value })} placeholder={c.room || "Room 3B"} /></label>
            </div>
            <button className="st-btn">Add event</button>
          </form>
        </div>
      </div>
    </>
  );
}

function WebServices() {
  const toast = useToast();
  const [ws, setWs] = useState<WS | null>(null);
  const load = useCallback(() => staffFetch<WS>("/staff/api/webservices").then(setWs).catch((e: Error) => toast("Couldn't load", e.message, true)), [toast]);
  useEffect(() => { void load(); const t = window.setInterval(() => void load(), 5000); return () => clearInterval(t); }, [load]);
  if (!ws) return <div className="st-card st-empty">Loading…</div>;
  return (
    <>
      <PageHead title="Web services" intro="The Moodle-compatible API used by apps like Remind Me Bro. The call log refreshes every 5 seconds." />
      <section className="st-section"><h2>Endpoints</h2>
        <div className="st-card st-pad"><dl className="st-kv">
          <dt>Token</dt><dd><span className="st-code">{ws.endpoints.token}</span></dd>
          <dt>REST</dt><dd><span className="st-code">{ws.endpoints.rest}</span></dd>
          <dt>Functions</dt><dd className="st-tags">{ws.functions.map((f) => <span key={f} className="st-code">{f}</span>)}</dd>
        </dl></div>
      </section>
      <section className="st-section"><h2>Tokens <small>{ws.tokens.length}</small></h2>
        <div className="st-card st-scroll"><table className="st-table">
          <thead><tr><th>User</th><th>App</th><th>Token</th><th>Created</th><th>Last used</th><th /></tr></thead>
          <tbody>{ws.tokens.length === 0 ? <tr><td colSpan={6} className="st-empty">No tokens. Connect UniLearn from the student hub to create one.</td></tr> : ws.tokens.map((t) => (
            <tr key={t.id}><td className="t">{t.user}</td><td>{t.client || "—"}</td><td className="mono">••••{t.hint}</td><td>{fmtDateTime(t.created)}</td><td>{fmtDateTime(t.lastaccess)}</td>
              <td className="r"><button className="st-btn danger sm" onClick={() => void staffFetch(`/staff/api/tokens/${t.id}`, { method: "DELETE" }).then(() => { toast("Token deleted", `${t.client} can no longer read ${t.user}'s data.`); void load(); }).catch((e: Error) => toast("Couldn't delete", e.message, true))}>Delete</button></td></tr>))}</tbody>
        </table></div>
      </section>
      <section className="st-section"><h2>Call log <small>last 60</small></h2>
        <div className="st-card st-scroll"><table className="st-table">
          <thead><tr><th>Time</th><th>User</th><th>Function</th><th>Result</th></tr></thead>
          <tbody>{ws.log.map((r) => <tr key={r.id}><td className="num">{r.at.slice(11, 19)}</td><td>{r.username ?? "—"}</td><td className="mono">{r.function}</td><td>{r.status === "ok" ? <Pill tone="ok">ok</Pill> : <Pill tone="bad">{r.status}</Pill>}</td></tr>)}</tbody>
        </table></div>
      </section>
    </>
  );
}

function App() {
  const { user, booting, demo, login, quickLogin, logout } = useStaffSession<Me>();
  const [path, go] = useHashPath();
  if (booting) return <div className="st"><div className="st-boot">Loading…</div></div>;
  if (!user) return <StaffLogin system={SYSTEM} intro="Teachers and the site admin. Students use the UniLearn dashboard." demo={demo} onLogin={login} onQuick={quickLogin} />;
  const admin = user.role === "admin";
  const nav = [{ id: "", label: "Courses" }, ...(admin ? [{ id: "webservices", label: "Web services" }] : [])];
  const page = path[0] ?? "";
  const current = page === "course" ? "" : page;
  return (
    <StaffShell system={SYSTEM} nav={nav} current={current} onNavigate={go} user={{ fullname: user.fullname, role: admin ? "site admin" : "teacher" }} onLogout={() => void logout()}>
      {page === "" && <Courses go={go} admin={admin} />}
      {page === "course" && <CoursePage key={path[1]} id={Number(path[1])} go={go} />}
      {page === "webservices" && admin && <WebServices />}
    </StaffShell>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><StaffErrorBoundary><ToastHost><App /></ToastHost></StaffErrorBoundary></StrictMode>);
