import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { Studies as StudiesData, StudyExam, StudyOffer } from "../../api/types";
import { Icon } from "../../components/Icon";
import { CourseChip, Empty, PageHeader, Skeleton } from "../../components/ui";
import { courseColor } from "../../lib/domain";
import { fmtDay, fmtTime, monthShort, parse } from "../../lib/time";
import { useStudent } from "../../state/student";
import { useToast } from "../../state/toast";

function Window({ status, opens, closes }: { status: string; opens: string; closes: string }) {
  if (status === "open") return <span className="pill ok">Open until {fmtDay(parse(closes))}</span>;
  if (status === "upcoming") return <span className="pill plan">Opens {fmtDay(parse(opens))} {fmtTime(parse(opens))}</span>;
  return <span className="pill">Closed</span>;
}

function ExamRow({ e, pending, act }: { e: StudyExam; pending: string | null; act: (key: string, fn: () => Promise<unknown>, ok: string) => void }) {
  const at = parse(e.starts_at);
  const key = `exam-${e.id}`;
  let action = null;
  if (e.registered) {
    action = <><span className="pill ok"><Icon name="check" size={13} /> Registered</span>
      {e.can_cancel && <button className="btn sm" disabled={!!pending} onClick={() => act(key, () => api.examCancel(e.id), `Registration for ${e.course_name} cancelled.`)}>{pending === key ? "…" : "Cancel"}</button>}</>;
  } else if (e.can_register) {
    action = <button className="btn primary sm" disabled={!!pending} onClick={() => act(key, () => api.examRegister(e.id), `Registered: ${e.course_name} · ${e.title}, ${fmtDay(at)}.`)}>{pending === key ? "Registering…" : "Register"}</button>;
  } else if (e.registration_status !== "upcoming" && e.reason) {
    action = <span className="why">{e.reason}</span>;
  }
  return (
    <li className="srow" style={{ ["--c" as string]: courseColor(e.course_code) }}>
      <div className="sdate"><b>{at.getDate()}</b><small>{monthShort(at)}</small></div>
      <div className="sinfo">
        <b>{e.course_name} · {e.title}{e.is_partial && <span className="pill tiny">partial</span>}</b>
        <small>{fmtDay(at)} {fmtTime(at)} · {e.room} · {e.registration_status === "open" ? `${e.seats_left} of ${e.capacity} seats left` : `${e.capacity} seats`}</small>
        <Window status={e.registration_status} opens={e.registration_opens_at} closes={e.registration_closes_at} />
      </div>
      <div className="sact">{action}</div>
    </li>
  );
}

function OfferRow({ o, open, pending, act }: { o: StudyOffer; open: boolean; pending: string | null; act: (key: string, fn: () => Promise<unknown>, ok: string) => void }) {
  const key = `course-${o.course_code}`;
  return (
    <li className="srow offer">
      <div className="sinfo">
        <b>{o.course_name} <span className="code">{o.course_code}</span></b>
        <small>{o.lecturer} · {o.credits} ECTS · {o.seats_left > 0 ? `${o.seats_left} of ${o.capacity} seats left` : <span className="flag">Full{o.waitlisted ? ` · ${o.waitlisted} waiting` : ""}</span>}</small>
        {o.description && <small className="desc">{o.description}</small>}
      </div>
      <div className="sact">
        {o.status === "enrolled" && <span className="pill ok">Enrolled</span>}
        {o.status === "waitlisted" && <span className="pill plan">Waiting list #{o.waitlist_position}</span>}
        {open && o.status === "none" && (
          <button className={`btn sm ${o.seats_left > 0 ? "primary" : ""}`} disabled={!!pending}
            onClick={() => act(key, () => api.courseEnroll(o.course_code), o.seats_left > 0 ? `Enrolled in ${o.course_name}.` : `You joined the waiting list for ${o.course_name}.`)}>
            {pending === key ? "…" : o.seats_left > 0 ? "Enroll" : "Join waiting list"}
          </button>
        )}
        {open && o.status !== "none" && (
          <button className="btn sm" disabled={!!pending} onClick={() => act(key, () => api.courseDrop(o.course_code), `You left ${o.course_name}.`)}>
            {pending === key ? "…" : o.status === "enrolled" ? "Drop" : "Leave list"}
          </button>
        )}
      </div>
    </li>
  );
}

export function Studies({ onNavigate }: { onNavigate: (p: string) => void }) {
  const toast = useToast();
  const { connection, reload } = useStudent();
  const [data, setData] = useState<StudiesData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const conn = connection("unisis");

  const load = useCallback(async () => {
    setError(null);
    try { setData(await api.studies()); } catch (e) { setError((e as Error).message); }
  }, []);
  useEffect(() => { void load(); }, [load, conn?.status]);

  const act = useCallback(async (key: string, fn: () => Promise<unknown>, ok: string) => {
    setPending(key);
    try { await fn(); toast("Done in UniSIS", ok, "ok"); }
    catch (e) { toast("UniSIS said no", (e as Error).message, "error"); }
    finally { await Promise.all([load(), reload()]); setPending(null); }
  }, [load, reload, toast]);

  if (error) return <><PageHeader title="Studies" /><Empty icon="alert" title="Couldn't load your student record" action={<button className="btn" onClick={() => void load()}>Try again</button>}>{error}</Empty></>;
  if (!data) return <><PageHeader eyebrow="UniSIS" title="Studies" /><Skeleton lines={6} /></>;

  if (!data.connected) {
    const expired = data.status === "expired";
    return (
      <>
        <PageHeader eyebrow="Your student record" title="Studies" />
        <section className="gate">
          <div>
            <h2>{expired ? "Reconnect your student record" : "Connect your student record"}</h2>
            <p>{expired ? "Access to UniSIS was revoked or expired. Connect again to see exams, courses and credits." : "Link UniSIS to see your exams, course registration, credits and grades — and get reminders when registration windows open."}</p>
            <ol className="steps">
              <li><b>1</b>You sign in on UniSIS, not here: Remind Me Bro never sees your password.</li>
              <li><b>2</b>UniSIS shows exactly what is shared. You allow or deny.</li>
              <li><b>3</b>You can revoke access from UniSIS at any time.</li>
            </ol>
          </div>
          <button className="btn primary" onClick={() => onNavigate("connections")}><Icon name="link" size={16} /> Go to Connections</button>
        </section>
      </>
    );
  }

  const p = data.profile!, cr = p.credits, exams = data.exams ?? [], reg = data.course_registration;
  const partials = exams.filter((e) => e.is_partial), finals = exams.filter((e) => !e.is_partial);
  const current = (data.enrollments ?? []).filter((e) => e.status === "enrolled" && e.kind === "core");
  const pct = Math.min(1, cr.earned / cr.required), pctProg = Math.min(1 - pct, cr.in_progress / cr.required);
  return (
    <>
      <PageHeader eyebrow={<>{p.programme.degree} {p.programme.name} · Year {p.year_of_study} · <span className="mono">{p.student_number}</span></>} title="Studies"
        actions={<><span className="pill ok live-pill">● UniSIS live</span><a className="btn" href={data.portal_url} target="_blank" rel="noopener noreferrer">Open UniSIS <Icon name="external" size={14} /></a></>} />
      <section className="stats">
        <div className="ring" style={{ ["--p" as string]: pct, ["--q" as string]: pct + pctProg }} role="img" aria-label={`${cr.earned} of ${cr.required} credits earned, ${cr.in_progress} in progress`}>
          <b>{cr.earned}</b><small>of {cr.required} ECTS</small>
        </div>
        <div className="stat"><b>{p.weighted_average != null ? p.weighted_average.toFixed(2) : "—"}</b><small>average grade · 1 best, 5 fail</small></div>
        <div className="stat"><b>{exams.filter((e) => e.registered).length}</b><small>exam registrations</small></div>
        <div className="stat"><b>{reg ? `${reg.electives_chosen}/${reg.electives_required}` : "—"}</b><small>electives chosen</small></div>
      </section>
      <div className="two-col studies">
        <div className="stack">
          <section className="panel"><h2>Partial tests</h2><p className="panel-sub">Booked directly in UniSIS, limited seats.</p>
            {partials.length ? <ul className="slist">{partials.map((e) => <ExamRow key={e.id} e={e} pending={pending} act={act} />)}</ul> : <p className="muted">No partial tests.</p>}</section>
          <section className="panel"><h2>Exam registration · winter session</h2><p className="panel-sub">One date per course.</p>
            {finals.length ? <ul className="slist">{finals.map((e) => <ExamRow key={e.id} e={e} pending={pending} act={act} />)}</ul> : <p className="muted">No exam dates published yet.</p>}</section>
          {reg && (
            <section className="panel"><h2>Course registration · {reg.term.name}</h2>
              <p className="panel-sub">{reg.status === "open" ? `Open until ${fmtDay(parse(reg.closes_at))}.` : reg.status === "upcoming" ? `Opens ${fmtDay(parse(reg.opens_at))}.` : "Closed."} {reg.electives_required ? `Choose ${reg.electives_required} electives; ` : "Choose the courses you want to take; "}if a course is full you join the waiting list automatically. Your UniLearn courses follow your choice.</p>
              <ul className="slist">{reg.offers.map((o) => <OfferRow key={o.course_code} o={o} open={reg.status === "open"} pending={pending} act={act} />)}</ul>
            </section>
          )}
        </div>
        <div className="stack">
          <section className="panel"><h2>This term</h2><p className="panel-sub">{current.reduce((a, c) => a + c.credits, 0)} ECTS in progress</p>
            <ul className="plain">{current.map((c) => <li key={c.course_code}><CourseChip code={c.course_code} /><span className="grow">{c.course_name}<small>{c.lecturer}</small></span><span className="mono">{c.credits} ECTS</span></li>)}</ul></section>
          {data.grades && (
            <section className="panel"><h2>Transcript</h2><p className="panel-sub">{data.grades.credits_earned} ECTS earned</p>
              <ul className="plain">{data.grades.records.map((r) => <li key={r.course_name + r.date}><span className="grow">{r.course_name}<small>{r.credits} ECTS · {fmtDay(parse(r.date))}</small></span><span className="grade" title={r.grade_name}>{r.grade}{r.grade_value != null && r.grade_name && <small> {r.grade_name}</small>}</span></li>)}</ul></section>
          )}
        </div>
      </div>
    </>
  );
}
