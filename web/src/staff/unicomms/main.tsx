// UniComms · Mail and Teams (lecturers). Served by UniComms at /staff, only on the computer that runs the demo.
import { StrictMode, useCallback, useEffect, useState, type FormEvent } from "react";
import { createRoot } from "react-dom/client";
import {
  PageHead, Pill, StaffErrorBoundary, StaffLogin, StaffShell, ToastHost, fmtDateTime, staffFetch,
  useStaffSession, useToast, type SystemInfo,
} from "../kit";

const SYSTEM: SystemInfo = { name: "UniComms", area: "Mail and Teams", mark: "UC", accent: "#2F69A3" };
interface Me { id: number; username: string; fullname: string; email: string; role: string; hub_url: string; now: string }
interface CatalogCourse { code: string; name: string; mine: boolean }
interface Catalog { courses: CatalogCourse[]; students: { email: string; fullname: string }[] }
type Channel = "outlook" | "teams";
interface Message {
  id: number; channel: Channel; sender: string; sender_name: string; sender_email: string; course_code: string; course_name: string;
  to_email: string | null; subject: string; body: string; created_at: string; mine: boolean;
}
const OTHER = "__other__";

function Compose({ me, catalog, onSent }: { me: Me; catalog: Catalog; onSent: () => void }) {
  const toast = useToast();
  const first = catalog.courses.find((c) => c.mine)?.code ?? catalog.courses[0]?.code ?? OTHER;
  const [channel, setChannel] = useState<Channel>("outlook");
  const [course, setCourse] = useState(first);
  const [otherCode, setOtherCode] = useState("");
  const [otherName, setOtherName] = useState("");
  const [toOne, setToOne] = useState(false);
  const [to, setTo] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const mine = catalog.courses.filter((c) => c.mine), others = catalog.courses.filter((c) => !c.mine);
  const outlook = channel === "outlook";

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      await staffFetch("/staff/api/messages", { method: "POST", body: {
        channel, course_code: course === OTHER ? otherCode : course, course_name: course === OTHER ? otherName : "",
        to_email: outlook && toOne ? to : null, subject: outlook ? subject : "", body,
      } });
      toast(outlook ? "Email sent" : "Posted in Teams", "It reaches the student hub's Inbox within half a minute.");
      setSubject(""); setBody("");
      onSent();
    } catch (e2) { setErr((e2 as Error).message); }
    setBusy(false);
  };

  return (
    <form className="st-card st-pad st-form" onSubmit={(e) => void submit(e)} aria-label="New message">
      <div className="st-seg" role="radiogroup" aria-label="Channel">
        {(["outlook", "teams"] as Channel[]).map((c) => (
          <label key={c} className={channel === c ? "on" : ""}><input type="radio" name="channel" checked={channel === c} onChange={() => setChannel(c)} />{c === "outlook" ? "Outlook email" : "Teams post"}</label>
        ))}
      </div>
      <p className="muted" style={{ margin: 0 }}>From <b>{me.fullname}</b> {outlook ? <>&lt;{me.email}&gt;</> : "· posted in the course channel"}</p>
      <label className="st-field">Course
        <select value={course} onChange={(e) => setCourse(e.target.value)}>
          {mine.length > 0 && <optgroup label="Your courses">{mine.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}</optgroup>}
          {others.length > 0 && <optgroup label="Other courses">{others.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}</optgroup>}
          <option value={OTHER}>A course that is not in the list…</option>
        </select>
      </label>
      {course === OTHER && (
        <div className="st-grid st-cols-2">
          <label className="st-field">Course code<input value={otherCode} onChange={(e) => setOtherCode(e.target.value)} placeholder="e.g. 4IT101" required maxLength={32} /></label>
          <label className="st-field">Course name<input value={otherName} onChange={(e) => setOtherName(e.target.value)} required maxLength={255} /></label>
        </div>
      )}
      {outlook && (
        <fieldset className="st-field" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend style={{ padding: 0, marginBottom: 6 }}>To</legend>
          <div className="st-seg" role="radiogroup" aria-label="Recipients">
            <label className={!toOne ? "on" : ""}><input type="radio" name="to" checked={!toOne} onChange={() => setToOne(false)} />Every student of the course</label>
            <label className={toOne ? "on" : ""}><input type="radio" name="to" checked={toOne} onChange={() => setToOne(true)} />One student</label>
          </div>
          {toOne && <>
            <input aria-label="Student's email" type="email" list="uc-students" value={to} onChange={(e) => setTo(e.target.value)} placeholder="student@demo.it" required style={{ marginTop: 8 }} />
            <datalist id="uc-students">{catalog.students.map((s) => <option key={s.email} value={s.email}>{s.fullname}</option>)}</datalist>
          </>}
        </fieldset>
      )}
      {outlook && <label className="st-field">Subject<input value={subject} onChange={(e) => setSubject(e.target.value)} required maxLength={300} /></label>}
      <label className="st-field">{outlook ? "Message" : "Post"}
        <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={7} required maxLength={20000}
          placeholder={outlook ? "Dear students, …" : "Hi all, quick reminder: …"} />
      </label>
      {err && <p className="st-err" role="alert">{err}</p>}
      <div className="st-row"><button className="st-btn primary" disabled={busy}>{busy ? "Sending…" : outlook ? "Send email" : "Post in Teams"}</button>
        <span className="muted" style={{ fontSize: 13 }}>Dates in the text become deadlines in the hub (the AI reads them).</span></div>
    </form>
  );
}

function Sent({ items, onDelete }: { items: Message[] | null; onDelete: (m: Message) => void }) {
  const [open, setOpen] = useState<number | null>(null);
  if (!items) return <div className="st-card st-empty">Loading…</div>;
  return (
    <div className="st-card"><ul className="st-list">
      {items.length === 0 && <li className="st-empty">Nothing sent yet.</li>}
      {items.map((m) => (
        <li key={m.id} style={{ display: "block" }}>
          <button className="uc-row" aria-expanded={open === m.id} onClick={() => setOpen(open === m.id ? null : m.id)}>
            <span className="st-row" style={{ justifyContent: "space-between" }}>
              <span className="t">{m.channel === "outlook" ? m.subject : m.body.slice(0, 70) + (m.body.length > 70 ? "…" : "")}</span>
              <span className="faint" style={{ fontSize: 12.5 }}>{fmtDateTime(m.created_at)}</span>
            </span>
            <span className="s">
              <Pill tone={m.channel === "outlook" ? "info" : "accent"}>{m.channel === "outlook" ? "Outlook" : "Teams"}</Pill>{" "}
              {m.sender_name} → {m.to_email ?? "all students"} · {m.course_name}
            </span>
          </button>
          {open === m.id && (
            <div className="uc-body">
              <p>{m.body}</p>
              {m.mine && <button className="st-btn danger sm" onClick={() => onDelete(m)}>Delete</button>}
            </div>
          )}
        </li>
      ))}
    </ul></div>
  );
}

function Mail({ me }: { me: Me }) {
  const toast = useToast();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [items, setItems] = useState<Message[] | null>(null);
  const load = useCallback(() => staffFetch<Message[]>("/staff/api/messages").then(setItems).catch((e: Error) => toast("Couldn't load the messages", e.message, true)), [toast]);
  useEffect(() => {
    staffFetch<Catalog>("/staff/api/catalog").then(setCatalog).catch((e: Error) => toast("Couldn't load the courses", e.message, true));
    void load();
  }, [load, toast]);
  const del = async (m: Message) => {
    if (!window.confirm("Delete this message? It disappears from the students' Inbox too, with the deadline found in it.")) return;
    try { await staffFetch(`/staff/api/messages/${m.id}`, { method: "DELETE" }); toast("Deleted", "It leaves the Inbox within half a minute."); void load(); }
    catch (e) { toast("Couldn't delete", (e as Error).message, true); }
  };
  return (
    <>
      <PageHead title="Write to students" intro={<>Emails and Teams posts sent here reach the Remind Me Bro Inbox of the students of the course (<a className="st-link" href={me.hub_url} target="_blank" rel="noopener noreferrer">open the student hub</a>).</>} />
      <div className="st-split">
        <section className="st-section"><h2>New message</h2>{catalog ? <Compose me={me} catalog={catalog} onSent={() => void load()} /> : <div className="st-card st-empty">Loading…</div>}</section>
        <section className="st-section"><h2>Sent <small>{items?.length ?? ""}</small></h2><Sent items={items} onDelete={(m) => void del(m)} /></section>
      </div>
    </>
  );
}

function App() {
  const { user, booting, demo, login, quickLogin, logout } = useStaffSession<Me>();
  if (booting) return <div className="st"><div className="st-boot">Loading…</div></div>;
  if (!user) return <StaffLogin system={SYSTEM} intro="Pick the lecturer who writes. Only on this computer: students never open UniComms." demo={demo} onLogin={login} onQuick={quickLogin} noPassword />;
  return (
    <StaffShell system={SYSTEM} nav={[{ id: "", label: "Write" }]} current="" onNavigate={() => undefined} user={{ fullname: user.fullname, role: "lecturer" }} onLogout={() => void logout()}>
      <Mail me={user} />
    </StaffShell>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><StaffErrorBoundary><ToastHost><App /></ToastHost></StaffErrorBoundary></StrictMode>);
