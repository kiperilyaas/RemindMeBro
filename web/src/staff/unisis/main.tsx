// UniSIS · Student Office (registrar). Served by UniSIS at /staff.
import { StrictMode, useCallback, useEffect, useState, type FormEvent } from "react";
import { createRoot } from "react-dom/client";
import {
  PageHead, Pill, StaffErrorBoundary, StaffLogin, StaffShell, Stat, ToastHost, fmtDate, fmtDateTime, fmtTime, staffFetch,
  toLocalInput, useHashPath, useStaffSession, useToast, type SystemInfo,
} from "../kit";

const SYSTEM: SystemInfo = { name: "UniSIS", area: "Student Office", mark: "US", accent: "#2F855A" };
interface Me { fullname: string; role: string; hub_url: string; now: string }
interface Exam { id: number; course_code: string; course_name: string; title: string; is_partial: boolean; starts_at: string; ends_at: string; room: string;
  capacity: number; registered: number; opens_at: string; closes_at: string; status: "open" | "upcoming" | "closed" }
interface Term { id: number; name: string; opens_at: string; closes_at: string; status: Exam["status"]; electives_required: number }
interface Overview { stats: { students: number; courses: number; open_windows: number; api_calls_24h: number }; exams: Exam[]; terms: Term[]; courses: { id: number; code: string; name: string }[] }
interface CourseRow { id: number; code: string; name: string; term: string; kind: string; credits: number; lecturer: string; room: string; capacity: number; enrolled: number; waitlisted: number }
interface TermRow { id: number; code: string; name: string; starts_on: string; ends_on: string }
interface Slot { id?: number; weekday: number; day?: string; start_time: string; end_time: string; room: string; kind: string }
interface CourseDetail extends CourseRow { term_id: number; year_of_study: number; description: string; slots: Slot[]; exams: number;
  students: { id: number; name: string; student_number: string; status: string }[] }
/** Czech grading scale: 1 is the best, 4 the lowest pass, 5 a fail. */
const GRADES: [string, string][] = [["1", "1 · excellent"], ["2", "2 · very good"], ["3", "3 · good"], ["4", "4 · satisfactory"], ["5", "5 · fail"], ["pass", "Pass (no grade)"]];
const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
interface Student { id: number; name: string; student_number: string; year: number; programme: string; credits: number; average: number | null }
interface Apps { issuer: string; clients: { client_id: string; name: string; description: string; secret_hint: string; api_key_hint: string; redirect_uris: string[]; scopes: string[]; secret_rotated_at: string; students_connected: number }[];
  tokens: { id: number; kind: string; client: string; user: string; scope: string; created: string; expires: string; last_used: string | null }[];
  log: { id: number; at: string; client: string | null; user: string | null; method: string; path: string; status: number }[] }

function WindowPill({ status, opens, closes }: { status: Exam["status"]; opens: string; closes: string }) {
  if (status === "open") return <Pill tone="ok">Open · until {fmtDate(closes)}</Pill>;
  if (status === "upcoming") return <Pill tone="info">Opens {fmtDateTime(opens)}</Pill>;
  return <Pill>Closed</Pill>;
}

function ExamEdit({ ex, onSaved, onCancel }: { ex: Exam; onSaved: () => void; onCancel: () => void }) {
  const toast = useToast();
  const [start, setStart] = useState(ex.starts_at.slice(0, 16));
  const [room, setRoom] = useState(ex.room);
  const [cap, setCap] = useState(String(ex.capacity));
  const save = async (e: FormEvent) => {
    e.preventDefault();
    try { await staffFetch(`/staff/api/exams/${ex.id}`, { method: "PATCH", body: { starts_at: start, room, capacity: Number(cap) } }); toast("Exam updated", `${ex.course_name} · ${fmtDateTime(start)}`); onSaved(); }
    catch (e2) { toast("Couldn't save", (e2 as Error).message, true); }
  };
  return (
    <form className="st-row" onSubmit={save} style={{ gap: 8 }}>
      <input type="datetime-local" className="st-input sm" value={start} onChange={(e) => setStart(e.target.value)} aria-label="Date and time" />
      <input className="st-input sm" style={{ width: 140 }} value={room} onChange={(e) => setRoom(e.target.value)} aria-label="Room" />
      <input type="number" className="st-input sm" style={{ width: 80 }} min={1} value={cap} onChange={(e) => setCap(e.target.value)} aria-label="Seats" />
      <button className="st-btn primary sm">Save</button><button type="button" className="st-btn ghost sm" onClick={onCancel}>Cancel</button>
    </form>
  );
}

function ExamTable({ title, hint, exams, reload, go }: { title: string; hint: string; exams: Exam[]; reload: () => void; go: (p: string) => void }) {
  const toast = useToast();
  const [edit, setEdit] = useState<number | null>(null);
  const window_ = async (ex: Exam, action: "open" | "close") => {
    try { await staffFetch(`/staff/api/exams/${ex.id}/window/${action}`, { method: "POST" }); toast(action === "open" ? "Registration open" : "Registration closed", `${ex.course_name} · ${ex.title}`); reload(); }
    catch (e) { toast("Couldn't change it", (e as Error).message, true); }
  };
  return (
    <section className="st-section">
      <h2>{title} <small>{hint}</small></h2>
      <div className="st-card st-scroll"><table className="st-table">
        <thead><tr><th>Course</th><th>When</th><th className="r">Seats</th><th>Registration</th><th /></tr></thead>
        <tbody>{exams.map((ex) => (
          <tr key={ex.id}>
            <td><span className="t">{ex.course_name}</span><span className="s">{ex.title} · {ex.room}</span></td>
            {edit === ex.id ? <td colSpan={4}><ExamEdit ex={ex} onSaved={() => { setEdit(null); reload(); }} onCancel={() => setEdit(null)} /></td> : <>
              <td className="num">{fmtDate(ex.starts_at)}<span className="s">{fmtTime(ex.starts_at)}–{fmtTime(ex.ends_at)}</span></td>
              <td className={`r num ${ex.registered >= ex.capacity ? "" : ""}`}>{ex.registered}/{ex.capacity}{ex.registered >= ex.capacity && <span className="s" style={{ color: "var(--bad)" }}>full</span>}</td>
              <td><WindowPill status={ex.status} opens={ex.opens_at} closes={ex.closes_at} /></td>
              <td className="r"><span className="st-row" style={{ justifyContent: "flex-end" }}>
                {ex.status === "open" ? <button className="st-btn sm" onClick={() => void window_(ex, "close")}>Close</button> : <button className="st-btn sm" onClick={() => void window_(ex, "open")}>Open now</button>}
                <button className="st-btn ghost sm" onClick={() => setEdit(ex.id)}>Edit</button>
                {!ex.is_partial && <button className="st-btn ghost sm" onClick={() => go(`exam/${ex.id}`)}>Grades</button>}
              </span></td></>}
          </tr>))}</tbody>
      </table></div>
    </section>
  );
}

function NewExam({ courses, onDone, go }: { courses: Overview["courses"]; onDone: () => void; go: (p: string) => void }) {
  const toast = useToast();
  const now = new Date();
  const [f, setF] = useState(() => {
    const start = new Date(now); start.setDate(start.getDate() + 30); start.setHours(9, 0, 0, 0);
    const closes = new Date(now); closes.setDate(closes.getDate() + 14); closes.setHours(23, 59, 0, 0);
    return { course_id: String(courses[0]?.id ?? ""), title: "Written exam", starts_at: toLocalInput(start), minutes: "120", room: "Main Hall", capacity: "100",
      opens_at: toLocalInput(now), closes_at: toLocalInput(closes), is_partial: false };
  });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await staffFetch("/staff/api/exams", { method: "POST", body: { ...f, course_id: Number(f.course_id), minutes: Number(f.minutes), capacity: Number(f.capacity) } });
      toast("Exam date created", `${courses.find((c) => String(c.id) === f.course_id)?.name} · ${fmtDateTime(f.starts_at)}`); onDone();
    } catch (e2) { toast("Couldn't create it", (e2 as Error).message, true); }
  };
  if (courses.length === 0) return (
    <div className="st-card st-pad"><b>New exam date</b><p className="muted" style={{ margin: "6px 0 12px" }}>Exams belong to a course. Create a course first.</p>
      <button className="st-btn" onClick={() => go("courses")}>Go to Courses</button></div>
  );
  return (
    <details className="st-card st-pad st-details">
      <summary>New exam date</summary>
      <form className="st-form" onSubmit={submit} style={{ marginTop: 16 }}>
        <div className="st-grid st-cols-3">
          <label className="st-field">Course<select value={f.course_id} onChange={set("course_id")}>{courses.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
          <label className="st-field">Title<input value={f.title} onChange={set("title")} required /></label>
          <label className="st-field">Starts<input type="datetime-local" value={f.starts_at} onChange={set("starts_at")} required /></label>
          <label className="st-field">Minutes<input type="number" min={15} value={f.minutes} onChange={set("minutes")} /></label>
          <label className="st-field">Room<input value={f.room} onChange={set("room")} required /></label>
          <label className="st-field">Seats<input type="number" min={1} value={f.capacity} onChange={set("capacity")} required /></label>
          <label className="st-field">Registration opens<input type="datetime-local" value={f.opens_at} onChange={set("opens_at")} required /></label>
          <label className="st-field">Registration closes<input type="datetime-local" value={f.closes_at} onChange={set("closes_at")} required /></label>
          <label className="st-field">Type<select value={f.is_partial ? "partial" : "final"} onChange={(e) => setF({ ...f, is_partial: e.target.value === "partial" })}><option value="final">Final exam</option><option value="partial">Partial test</option></select></label>
        </div>
        <div><button className="st-btn primary">Create exam date</button></div>
      </form>
    </details>
  );
}

function Exams({ go }: { go: (p: string) => void }) {
  const toast = useToast();
  const [o, setO] = useState<Overview | null>(null);
  const load = useCallback(() => staffFetch<Overview>("/staff/api/overview").then(setO).catch((e: Error) => toast("Couldn't load", e.message, true)), [toast]);
  useEffect(() => { void load(); }, [load]);
  if (!o) return <div className="st-card st-empty">Loading…</div>;
  const termWindow = async (t: Term, action: "open" | "close") => {
    try { await staffFetch(`/staff/api/terms/${t.id}/window/${action}`, { method: "POST" }); toast(`Course registration ${action === "open" ? "open" : "closed"}`, t.name); void load(); }
    catch (e) { toast("Couldn't change it", (e as Error).message, true); }
  };
  return (
    <>
      <PageHead title="Exams and registration" intro="Open and close registration windows, move exam dates, add seats. Students see changes immediately in UniSIS and after a sync in Remind Me Bro." />
      <div className="st-grid st-cols-4" style={{ marginBottom: 32 }}>
        <Stat label="Students" value={o.stats.students} /><Stat label="Courses" value={o.stats.courses} />
        <Stat label="Open windows" value={o.stats.open_windows} /><Stat label="API calls · 24 h" value={o.stats.api_calls_24h} />
      </div>
      <section className="st-section"><h2>Course registration</h2>
        <div className="st-card"><ul className="st-list">{o.terms.map((t) => (
          <li key={t.id}><div className="grow"><div className="t">{t.name}</div><div className="s">{t.electives_required ? `Students choose ${t.electives_required} electives · ` : ""}{t.opens_at ? `${fmtDateTime(t.opens_at)} – ${fmtDateTime(t.closes_at)}` : "Elective registration not scheduled"}</div></div>
            <WindowPill status={t.status} opens={t.opens_at} closes={t.closes_at} />
            {t.status === "open" ? <button className="st-btn sm" onClick={() => void termWindow(t, "close")}>Close</button> : <button className="st-btn sm" onClick={() => void termWindow(t, "open")}>Open now</button>}
          </li>))}</ul></div>
      </section>
      {o.exams.some((e) => e.is_partial) && <ExamTable title="Partial tests" hint="students book them directly" exams={o.exams.filter((e) => e.is_partial)} reload={() => void load()} go={go} />}
      {o.exams.some((e) => !e.is_partial) && <ExamTable title="Final exams" hint="students register in the window" exams={o.exams.filter((e) => !e.is_partial)} reload={() => void load()} go={go} />}
      {o.exams.length === 0 && <section className="st-section"><h2>Exams</h2><div className="st-card st-empty">No exam dates yet.</div></section>}
      <NewExam courses={o.courses} onDone={() => void load()} go={go} />
    </>
  );
}

function ExamGrades({ id, go }: { id: number; go: (p: string) => void }) {
  const toast = useToast();
  const [ex, setEx] = useState<(Exam & { students: { user_id: number; name: string; student_number: string; grade: string | null; grade_name: string | null }[] }) | null>(null);
  const [grades, setGrades] = useState<Record<string, string>>({});
  const load = useCallback(() => staffFetch<NonNullable<typeof ex>>(`/staff/api/exams/${id}`).then(setEx).catch((e: Error) => toast("Couldn't load", e.message, true)), [id, toast]);
  useEffect(() => { void load(); }, [load]);
  const save = async () => {
    try { const r = await staffFetch<{ saved: number }>(`/staff/api/exams/${id}/grades`, { method: "POST", body: grades }); toast("Grades published", `${r.saved} grade(s) added to transcripts.`); setGrades({}); void load(); }
    catch (e) { toast("Couldn't save", (e as Error).message, true); }
  };
  if (!ex) return <div className="st-card st-empty">Loading…</div>;
  return (
    <>
      <PageHead crumb={<><button onClick={() => go("")}>Exams</button><span>/</span><span>Grades</span></>} title={`${ex.course_name} · ${ex.title}`}
        intro={`${fmtDateTime(ex.starts_at)} · ${ex.room} · ${ex.registered} registered. Czech scale: 1 is the best grade, 4 the lowest pass, 5 is a fail.`}
        actions={<button className="st-btn primary" disabled={!Object.values(grades).some((v) => v.trim())} onClick={() => void save()}>Publish grades</button>} />
      <div className="st-card st-scroll"><table className="st-table">
        <thead><tr><th>Student</th><th>Number</th><th>Grade</th></tr></thead>
        <tbody>{ex.students.length === 0 ? <tr><td colSpan={3} className="st-empty">Nobody registered yet.</td></tr> : ex.students.map((s) => (
          <tr key={s.user_id}><td className="t">{s.name}</td><td className="mono">{s.student_number}</td>
            <td>{s.grade ? <Pill tone={s.grade_name === "fail" ? "bad" : "ok"} plain>{s.grade}{s.grade_name && s.grade !== "Pass" && s.grade !== "Fail" ? ` · ${s.grade_name}` : ""}</Pill>
              : <select className="st-input sm" value={grades[s.user_id] ?? ""} onChange={(e) => setGrades({ ...grades, [s.user_id]: e.target.value })} aria-label={`Grade for ${s.name}`}>
                  <option value="">—</option>{GRADES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select>}</td></tr>))}</tbody>
      </table></div>
    </>
  );
}

function SlotRow({ slot, onChange, onRemove, mainRoom }: { slot: Slot; onChange: (s: Slot) => void; onRemove: () => void; mainRoom?: string }) {
  return (
    <div className="st-row" style={{ gap: 8, flexWrap: "wrap" }}>
      <select className="st-input sm" value={slot.weekday} onChange={(e) => onChange({ ...slot, weekday: Number(e.target.value) })} aria-label="Day">{DAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}</select>
      <input type="time" className="st-input sm" value={slot.start_time} onChange={(e) => onChange({ ...slot, start_time: e.target.value })} aria-label="From" />
      <input type="time" className="st-input sm" value={slot.end_time} onChange={(e) => onChange({ ...slot, end_time: e.target.value })} aria-label="To" />
      <input className="st-input sm" style={{ width: 130 }} value={slot.room} onChange={(e) => onChange({ ...slot, room: e.target.value })} placeholder={mainRoom ? `${mainRoom} (main)` : "Room"} aria-label="Room" />
      <select className="st-input sm" value={slot.kind} onChange={(e) => onChange({ ...slot, kind: e.target.value })} aria-label="Type">{["Lecture", "Tutorial", "Lab", "Seminar"].map((k) => <option key={k}>{k}</option>)}</select>
      <button type="button" className="st-btn ghost sm" onClick={onRemove}>Remove</button>
    </div>
  );
}

const newSlot = (): Slot => ({ weekday: 0, start_time: "09:00", end_time: "11:00", room: "", kind: "Lecture" });

function NewCourse({ onDone }: { onDone: (id: number) => void }) {
  const toast = useToast();
  const [terms, setTerms] = useState<TermRow[]>([]);
  const [f, setF] = useState({ code: "", name: "", credits: "6", term_id: "", lecturer: "", room: "", capacity: "100", kind: "elective", year_of_study: "1", description: "", enrol_all_students: true });
  const [slots, setSlots] = useState<Slot[]>([newSlot()]);
  useEffect(() => { staffFetch<TermRow[]>("/staff/api/terms").then((t) => { setTerms(t); setF((x) => ({ ...x, term_id: x.term_id || String(t[0]?.id ?? "") })); }).catch(() => undefined); }, []);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const c = await staffFetch<CourseDetail>("/staff/api/courses", { method: "POST", body: {
        ...f, credits: Number(f.credits), term_id: Number(f.term_id), capacity: Number(f.capacity), year_of_study: Number(f.year_of_study),
        slots: f.room.trim() ? slots : slots.filter((sl) => sl.room.trim()) } });
      toast("Course created", `${c.name} · ${c.enrolled} student(s) enrolled · ${c.slots.length} weekly class(es)`); onDone(c.id);
    } catch (e2) { toast("Couldn't create it", (e2 as Error).message, true); }
  };
  return (
    <details className="st-card st-pad st-details">
      <summary>New course</summary>
      <form className="st-form" onSubmit={submit} style={{ marginTop: 16 }}>
        <div className="st-grid st-cols-3">
          <label className="st-field">Code<input value={f.code} onChange={set("code")} required minLength={2} placeholder="MICRO-2026" /></label>
          <label className="st-field">Name<input value={f.name} onChange={set("name")} required minLength={2} placeholder="Microeconomics" /></label>
          <label className="st-field">Lecturer<input value={f.lecturer} onChange={set("lecturer")} required minLength={2} placeholder="Prof. Marco Rossi" /></label>
          <label className="st-field">Main room<input value={f.room} onChange={set("room")} placeholder="Room 3B" /></label>
          <label className="st-field">Term<select value={f.term_id} onChange={set("term_id")}>{terms.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select></label>
          <label className="st-field">Type<select value={f.kind} onChange={set("kind")}><option value="elective">Students choose it</option><option value="core">Compulsory (Student Office enrols)</option></select></label>
          <label className="st-field">Credits (ECTS)<input type="number" min={1} max={30} value={f.credits} onChange={set("credits")} /></label>
          <label className="st-field">Seats<input type="number" min={1} value={f.capacity} onChange={set("capacity")} /></label>
          <label className="st-field">Year of study<input type="number" min={1} max={6} value={f.year_of_study} onChange={set("year_of_study")} /></label>
        </div>
        <label className="st-field">Description<textarea value={f.description} onChange={set("description")} placeholder="Shown to students when they choose electives (optional)" /></label>
        <div className="st-field">Weekly timetable <span className="muted" style={{ fontWeight: 400 }}>· {f.room.trim() ? "an empty room means the main room" : "rows without a room are skipped"}</span>
          <div className="st-grid" style={{ gap: 8, marginTop: 6 }}>
            {slots.map((sl, i) => <SlotRow key={i} slot={sl} mainRoom={f.room.trim()} onChange={(n) => setSlots(slots.map((x, j) => (j === i ? n : x)))} onRemove={() => setSlots(slots.filter((_, j) => j !== i))} />)}
            <div><button type="button" className="st-btn sm" onClick={() => setSlots([...slots, newSlot()])}>Add a class</button></div>
          </div>
        </div>
        {f.kind === "core" && <label className="st-tick"><input type="checkbox" checked={f.enrol_all_students} onChange={(e) => setF({ ...f, enrol_all_students: e.target.checked })} />Enrol every student now</label>}
        <div><button className="st-btn primary">Create course</button></div>
      </form>
    </details>
  );
}

function Courses({ go }: { go: (p: string) => void }) {
  const toast = useToast();
  const [rows, setRows] = useState<CourseRow[] | null>(null);
  const [edit, setEdit] = useState<{ id: number; cap: string } | null>(null);
  const load = useCallback(() => staffFetch<CourseRow[]>("/staff/api/courses").then(setRows).catch((e: Error) => toast("Couldn't load", e.message, true)), [toast]);
  useEffect(() => { void load(); }, [load]);
  const save = async () => {
    if (!edit) return;
    try { const r = await staffFetch<CourseRow & { promoted: number }>(`/staff/api/courses/${edit.id}`, { method: "PATCH", body: { capacity: Number(edit.cap) } });
      toast("Capacity saved", r.promoted ? `${r.promoted} student(s) moved from the waiting list.` : `${r.name}: ${r.capacity} seats.`); setEdit(null); void load(); }
    catch (e) { toast("Couldn't save", (e as Error).message, true); }
  };
  return (
    <>
      <PageHead title="Courses" intro="Create courses with their weekly timetable and enrol students. Use the same code as in UniLearn and Remind Me Bro, so the three systems treat it as one course." />
      <div style={{ marginBottom: 24 }}><NewCourse onDone={(id) => go(`course/${id}`)} /></div>
      <div className="st-card st-scroll">{!rows ? <div className="st-empty">Loading…</div> : rows.length === 0 ? <div className="st-empty">No courses yet. Create the first one above.</div> : <table className="st-table">
        <thead><tr><th>Course</th><th>Term</th><th className="r">Enrolled</th><th className="r">Waiting</th><th className="r">Capacity</th><th /></tr></thead>
        <tbody>{rows.map((c) => (
          <tr key={c.id}><td><span className="t">{c.name}</span><span className="s">{c.code} · {c.lecturer}{c.room ? ` · ${c.room}` : ""} · {c.credits} ECTS · {c.kind}</span></td><td>{c.term}</td>
            <td className="r num">{c.enrolled}</td><td className="r num">{c.waitlisted ? <Pill tone="warn" plain>{c.waitlisted}</Pill> : "—"}</td>
            <td className="r">{edit?.id === c.id ? <span className="st-row" style={{ justifyContent: "flex-end" }}><input type="number" min={1} className="st-input sm" style={{ width: 80 }} value={edit.cap} onChange={(e) => setEdit({ id: c.id, cap: e.target.value })} aria-label="Capacity" />
              <button className="st-btn primary sm" onClick={() => void save()}>Save</button><button className="st-btn ghost sm" onClick={() => setEdit(null)}>Cancel</button></span>
              : <button className="st-link num" onClick={() => setEdit({ id: c.id, cap: String(c.capacity) })}>{c.capacity}</button>}</td>
            <td className="r"><button className="st-btn sm" onClick={() => go(`course/${c.id}`)}>Open</button></td></tr>))}</tbody>
      </table>}</div>
    </>
  );
}

function CoursePage({ id, go }: { id: number; go: (p: string) => void }) {
  const toast = useToast();
  const [c, setC] = useState<CourseDetail | null>(null);
  const [all, setAll] = useState<Student[]>([]);
  const [pick, setPick] = useState("");
  const [slot, setSlot] = useState<Slot>(newSlot());
  const [confirm, setConfirm] = useState(false);
  const [edit, setEdit] = useState<{ name: string; lecturer: string; room: string; credits: string; capacity: string; description: string } | null>(null);
  const [roomOf, setRoomOf] = useState<{ id: number; room: string } | null>(null);
  const load = useCallback(() => staffFetch<CourseDetail>(`/staff/api/courses/${id}`).then(setC).catch((e: Error) => toast("Couldn't load", e.message, true)), [id, toast]);
  useEffect(() => { void load(); staffFetch<Student[]>("/staff/api/students").then(setAll).catch(() => undefined); }, [load]);
  const call = async (path: string, method: string, done: string, body?: unknown) => {
    try { await staffFetch(path, { method, body }); toast(done); void load(); return true; } catch (e) { toast("Couldn't do it", (e as Error).message, true); return false; }
  };
  if (!c) return <div className="st-card st-empty">Loading…</div>;
  const free = all.filter((st) => !c.students.find((x) => x.id === st.id));
  return (
    <>
      <PageHead crumb={<><button onClick={() => go("courses")}>Courses</button><span>/</span><span>{c.code}</span></>} title={c.name}
        intro={`${c.term} · ${c.lecturer} · ${c.room ? `Room ${c.room}` : "no main room"} · ${c.credits} ECTS · ${c.kind} · ${c.enrolled}/${c.capacity} enrolled`}
        actions={confirm ? <span className="st-row"><button className="st-btn danger solid sm" onClick={() => void staffFetch(`/staff/api/courses/${id}`, { method: "DELETE" }).then(() => { toast("Course deleted"); go("courses"); }).catch((e: Error) => toast("Couldn't delete", e.message, true))}>Delete course, exams and enrolments</button>
          <button className="st-btn ghost sm" onClick={() => setConfirm(false)}>Keep</button></span> : <button className="st-btn ghost sm" onClick={() => setConfirm(true)}>Delete course</button>} />
      <div className="st-split">
        <div>
          <section className="st-section"><h2>Weekly timetable <small>{c.slots.length}</small></h2>
            <div className="st-card"><ul className="st-list">
              {c.slots.length === 0 && <li className="st-empty">No classes yet.</li>}
              {c.slots.map((sl) => <li key={sl.id}><div className="grow"><div className="t">{sl.day} · {sl.start_time}–{sl.end_time}</div><div className="s">{sl.kind} · {sl.room}</div></div>
                {roomOf?.id === sl.id ? <span className="st-row"><input className="st-input sm" style={{ width: 130 }} value={roomOf?.room ?? ""} onChange={(e) => setRoomOf({ id: sl.id!, room: e.target.value })} aria-label="Room" />
                  <button className="st-btn primary sm" disabled={!(roomOf?.room ?? "").trim()} onClick={() => { void call(`/staff/api/slots/${sl.id}`, "PATCH", "Room changed", { room: roomOf?.room ?? "" }); setRoomOf(null); }}>Save</button>
                  <button className="st-btn ghost sm" onClick={() => setRoomOf(null)}>Cancel</button></span>
                  : <span className="st-row"><button className="st-btn ghost sm" onClick={() => setRoomOf({ id: sl.id!, room: sl.room })}>Change room</button>
                    <button className="st-btn ghost sm" onClick={() => void call(`/staff/api/slots/${sl.id}`, "DELETE", "Class removed")}>Remove</button></span>}</li>)}
            </ul></div>
          </section>
          <section className="st-section"><h2>Students <small>{c.students.length}</small></h2>
            <div className="st-card"><ul className="st-list">
              {c.students.length === 0 && <li className="st-empty">Nobody is enrolled yet.</li>}
              {c.students.map((st) => <li key={st.id}><div className="grow"><div className="t">{st.name}</div><div className="s">{st.student_number} · {st.status}</div></div>
                <button className="st-btn ghost sm" onClick={() => void call(`/staff/api/courses/${id}/students/${st.id}`, "DELETE", "Student removed")}>Remove</button></li>)}
              {free.length > 0 && <li><select className="st-input sm" value={pick} onChange={(e) => setPick(e.target.value)} aria-label="Student to enrol">
                <option value="">Choose a student…</option>{free.map((st) => <option key={st.id} value={st.id}>{st.name}</option>)}</select>
                <button className="st-btn sm" disabled={!pick} onClick={() => { void call(`/staff/api/courses/${id}/students/${pick}`, "POST", "Student enrolled"); setPick(""); }}>Enrol</button></li>}
            </ul></div>
          </section>
        </div>
        <div className="st-grid">
          {edit ? (
            <form className="st-card st-pad st-form" onSubmit={(e) => { e.preventDefault(); void call(`/staff/api/courses/${id}`, "PATCH", "Course saved",
              { ...edit, credits: Number(edit.credits), capacity: Number(edit.capacity) }).then((ok) => { if (ok) setEdit(null); }); }}>
              <h2 style={{ fontSize: 15 }}>Edit course</h2>
              <label className="st-field">Name<input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} required minLength={2} /></label>
              <label className="st-field">Lecturer<input value={edit.lecturer} onChange={(e) => setEdit({ ...edit, lecturer: e.target.value })} required minLength={2} /></label>
              <label className="st-field">Main room<input value={edit.room} onChange={(e) => setEdit({ ...edit, room: e.target.value })} placeholder="Room 3B" /></label>
              <div className="st-grid st-cols-2">
                <label className="st-field">Credits<input type="number" min={1} max={30} value={edit.credits} onChange={(e) => setEdit({ ...edit, credits: e.target.value })} /></label>
                <label className="st-field">Seats<input type="number" min={1} value={edit.capacity} onChange={(e) => setEdit({ ...edit, capacity: e.target.value })} /></label>
              </div>
              <label className="st-field">Description<textarea value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></label>
              <p className="muted" style={{ margin: 0, fontSize: 12.5 }}>Weekly classes in the old main room move to the new one.</p>
              <span className="st-row"><button className="st-btn primary">Save</button><button type="button" className="st-btn ghost" onClick={() => setEdit(null)}>Cancel</button></span>
            </form>
          ) : (
            <div className="st-card st-pad"><div className="st-row" style={{ justifyContent: "space-between" }}><b>Course details</b>
              <button className="st-btn sm" onClick={() => setEdit({ name: c.name, lecturer: c.lecturer, room: c.room, credits: String(c.credits), capacity: String(c.capacity), description: c.description })}>Edit</button></div>
              <dl className="st-kv" style={{ marginTop: 10 }}><dt>Code</dt><dd className="mono">{c.code}</dd><dt>Lecturer</dt><dd>{c.lecturer}</dd>
                <dt>Main room</dt><dd>{c.room || <span className="muted">not set</span>}</dd><dt>Seats</dt><dd>{c.capacity}</dd></dl></div>
          )}
          <form className="st-card st-pad st-form" onSubmit={(e) => { e.preventDefault(); void call(`/staff/api/courses/${id}/slots`, "POST", "Class added", slot); }}>
            <h2 style={{ fontSize: 15 }}>Add a weekly class</h2>
            <SlotRow slot={slot} mainRoom={c.room} onChange={setSlot} onRemove={() => setSlot(newSlot())} />
            <button className="st-btn" disabled={!slot.room.trim() && !c.room}>Add class</button>
          </form>
          <div className="st-card st-pad"><b>Exams</b><p className="muted" style={{ margin: "6px 0 12px" }}>{c.exams} exam date(s). Create them in Exams.</p>
            <button className="st-btn" onClick={() => go("")}>Go to Exams</button></div>
        </div>
      </div>
    </>
  );
}

function Students() {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<Student[] | null>(null);
  useEffect(() => {
    const t = window.setTimeout(() => { staffFetch<Student[]>(`/staff/api/students?q=${encodeURIComponent(q)}`).then(setRows).catch(() => setRows([])); }, 200);
    return () => clearTimeout(t);
  }, [q]);
  return (
    <>
      <PageHead title="Students" actions={<input className="st-input" style={{ width: 260 }} placeholder="Search name or number" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search students" />} />
      <div className="st-card st-scroll">{!rows ? <div className="st-empty">Loading…</div> : <table className="st-table">
        <thead><tr><th>Student</th><th>Number</th><th>Programme</th><th className="r">Credits</th><th className="r">Average <small className="muted">1 best</small></th></tr></thead>
        <tbody>{rows.length === 0 ? <tr><td colSpan={5} className="st-empty">No students found.</td></tr> : rows.map((s) => (
          <tr key={s.id}><td className="t">{s.name}</td><td className="mono">{s.student_number}</td><td>{s.programme} · year {s.year}</td><td className="r num">{s.credits}</td><td className="r num">{s.average ?? "—"}</td></tr>))}</tbody>
      </table>}</div>
    </>
  );
}

function AppsKeys() {
  const toast = useToast();
  const [a, setA] = useState<Apps | null>(null);
  const [reveal, setReveal] = useState<{ label: string; value: string } | null>(null);
  const load = useCallback(() => staffFetch<Apps>("/staff/api/apps").then(setA).catch((e: Error) => toast("Couldn't load", e.message, true)), [toast]);
  useEffect(() => { void load(); const t = window.setInterval(() => void load(), 5000); return () => clearInterval(t); }, [load]);
  const rotate = async (id: string, what: "secret" | "key") => {
    try { setReveal(await staffFetch<{ label: string; value: string }>(`/staff/api/apps/${id}/rotate/${what}`, { method: "POST" })); void load(); }
    catch (e) { toast("Couldn't rotate", (e as Error).message, true); }
  };
  const revoke = async (id: number) => {
    try { await staffFetch(`/staff/api/tokens/${id}/revoke`, { method: "POST" }); toast("Token revoked"); void load(); }
    catch (e) { toast("Couldn't revoke", (e as Error).message, true); }
  };
  if (!a) return <div className="st-card st-empty">Loading…</div>;
  return (
    <>
      <PageHead title="Apps & keys" intro={<>Registered apps use OAuth 2.0 with PKCE. Issuer <span className="st-code">{a.issuer}</span>. The audit log refreshes every 5 seconds.</>} />
      {a.clients.map((c) => (
        <section key={c.client_id} className="st-card st-pad st-section">
          <div className="st-row"><h2 style={{ fontSize: 16 }}>{c.name}</h2><Pill tone="ok">{c.students_connected} student(s) connected</Pill></div>
          <p className="muted" style={{ margin: "4px 0 16px" }}>{c.description}</p>
          <dl className="st-kv">
            <dt>Client ID</dt><dd className="mono">{c.client_id}</dd>
            <dt>Client secret</dt><dd><span className="mono">••••{c.secret_hint}</span> · rotated {fmtDateTime(c.secret_rotated_at)} <button className="st-link" onClick={() => void rotate(c.client_id, "secret")}>Rotate</button></dd>
            <dt>API key</dt><dd><span className="mono">••••{c.api_key_hint}</span> <button className="st-link" onClick={() => void rotate(c.client_id, "key")}>Rotate</button></dd>
            <dt>Redirect URIs</dt><dd className="mono">{c.redirect_uris.join("  ")}</dd>
            <dt>Scopes</dt><dd className="st-tags">{c.scopes.map((s) => <span key={s} className="st-code">{s}</span>)}</dd>
          </dl>
          {reveal && <div className="st-reveal" role="status"><span>{reveal.label}:</span><code>{reveal.value}</code><button className="st-btn sm" onClick={() => setReveal(null)}>Hide</button></div>}
        </section>
      ))}
      <section className="st-section"><h2>Active tokens <small>{a.tokens.length}</small></h2>
        <div className="st-card st-scroll"><table className="st-table">
          <thead><tr><th>Student</th><th>App</th><th>Type</th><th>Expires</th><th>Last used</th><th /></tr></thead>
          <tbody>{a.tokens.length === 0 ? <tr><td colSpan={6} className="st-empty">No active tokens. Connect UniSIS from the student hub to create one.</td></tr> : a.tokens.map((t) => (
            <tr key={t.id}><td className="t">{t.user}</td><td>{t.client}</td><td>{t.kind}</td><td>{fmtDateTime(t.expires)}</td><td>{fmtDateTime(t.last_used)}</td>
              <td className="r"><button className="st-btn danger sm" onClick={() => void revoke(t.id)}>Revoke</button></td></tr>))}</tbody>
        </table></div>
      </section>
      <section className="st-section"><h2>Audit log <small>every API call</small></h2>
        <div className="st-card st-scroll"><table className="st-table">
          <thead><tr><th>Time</th><th>App</th><th>Student</th><th>Request</th><th className="r">Status</th></tr></thead>
          <tbody>{a.log.length === 0 ? <tr><td colSpan={5} className="st-empty">No calls yet.</td></tr> : a.log.map((r) => (
            <tr key={r.id}><td className="num">{r.at.slice(11, 19)}</td><td>{r.client ?? "—"}</td><td>{r.user ?? "—"}</td><td className="mono">{r.method} {r.path}</td>
              <td className="r">{r.status < 400 ? <Pill tone="ok">{r.status}</Pill> : <Pill tone="bad">{r.status}</Pill>}</td></tr>))}</tbody>
        </table></div>
      </section>
    </>
  );
}

function App() {
  const { user, booting, demo, login, logout } = useStaffSession<Me>();
  const [path, go] = useHashPath();
  if (booting) return <div className="st"><div className="st-boot">Loading…</div></div>;
  if (!user) return <StaffLogin system={SYSTEM} intro="Student Office staff. Students sign in to the UniSIS student portal." demo={demo} onLogin={login} />;
  const nav = [{ id: "", label: "Exams" }, { id: "courses", label: "Courses" }, { id: "students", label: "Students" }, { id: "apps", label: "Apps & keys" }];
  const page = path[0] ?? "";
  return (
    <StaffShell system={SYSTEM} nav={nav} current={page === "exam" ? "" : page === "course" ? "courses" : page} onNavigate={go} user={{ fullname: user.fullname, role: "registrar" }} onLogout={() => void logout()}>
      {page === "" && <Exams go={go} />}
      {page === "exam" && <ExamGrades key={path[1]} id={Number(path[1])} go={go} />}
      {page === "courses" && <Courses go={go} />}
      {page === "course" && <CoursePage key={path[1]} id={Number(path[1])} go={go} />}
      {page === "students" && <Students />}
      {page === "apps" && <AppsKeys />}
    </StaffShell>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><StaffErrorBoundary><ToastHost><App /></ToastHost></StaffErrorBoundary></StrictMode>);
