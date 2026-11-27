import { useMemo, useState } from "react";
import { Icon } from "../../components/Icon";
import { Skeleton } from "../../components/ui";
import { courseColor, planWeek, shortCode, urgency } from "../../lib/domain";
import { storage } from "../../lib/storage";
import { daysBetween, greeting, parse, relative, startOfDay } from "../../lib/time";
import { useSession } from "../../state/session";
import { useStudent } from "../../state/student";
import { buildItems, Calendar, type CalView } from "./Calendar";
import { FindExamsButton, FoundDates } from "./FoundDates";

const VIEWS: { id: CalView; label: string }[] = [{ id: "agenda", label: "Agenda" }, { id: "week", label: "Week" }, { id: "month", label: "Month" }];
const VIEW_KEY = "rmb.calendar.view";

export function Timeline({ onNavigate }: { onNavigate: (p: string) => void }) {
  const { now, user } = useSession();
  const { loading, deadlines, events, inbox, isRead, connection } = useStudent();
  const [view, setViewState] = useState<CalView>(() => {
    const v = storage.getJSON<CalView>(VIEW_KEY, "agenda");
    return VIEWS.some((x) => x.id === v) ? v : "agenda";
  });
  const setView = (v: CalView) => { setViewState(v); storage.setJSON(VIEW_KEY, v); };
  const [course, setCourse] = useState<string | null>(null);
  const [planned, setPlanned] = useState(false);
  const [weekOff, setWeekOff] = useState(0);
  const [monthOff, setMonthOff] = useState(0);
  const [selected, setSelected] = useState<Date>(() => startOfDay(now));

  const open = useMemo(() => deadlines.filter((d) => !d.is_completed).sort((a, b) => a.due_date.localeCompare(b.due_date)), [deadlines]);
  const upcoming = open.filter((d) => parse(d.due_date) >= now);
  const overdue = open.filter((d) => parse(d.due_date) < startOfDay(now));
  const blocks = useMemo(() => (planned ? planWeek(deadlines, events, now) : []), [planned, deadlines, events, now]);
  const courses = useMemo(() => {
    const m = new Map<string, string>();
    [...events, ...deadlines].forEach((x) => { if (x.course_code) m.set(x.course_code, x.course_name ?? x.course_code); });
    return [...m.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [events, deadlines]);
  const items = useMemo(() => buildItems(events, deadlines, blocks, course), [events, deadlines, blocks, course]);

  const aiNew = inbox.filter((m) => m.deadline_id && !isRead(m.id)).length;
  const ul = connection("moodle"), us = connection("unisis");
  const missing = [ul && ul.status !== "connected" ? "UniLearn" : null, us && us.status !== "connected" ? "UniSIS" : null].filter(Boolean) as string[];
  const soon = upcoming.filter((d) => daysBetween(now, parse(d.due_date)) <= 14).length;

  const goToday = () => { setWeekOff(0); setMonthOff(0); setSelected(startOfDay(now)); };
  /** Opens the month view on a given day (used by the deadline shortcuts in the header). */
  const showDay = (d: Date) => {
    setMonthOff((d.getFullYear() - now.getFullYear()) * 12 + d.getMonth() - now.getMonth());
    setSelected(startOfDay(d));
    setView("month");
  };

  return (
    <>
      <section className="hero">
        <p className="hello">{greeting(now)}, {(user?.full_name ?? "").split(" ")[0]}</p>
        <h1>{soon === 0 ? "Nothing due in the next two weeks." : soon === 1 ? "1 deadline in the next two weeks" : `${soon} deadlines in the next two weeks`}</h1>
        {upcoming.length > 0 ? (
          <div className="next-row">
            {upcoming.slice(0, 3).map((d) => {
              const due = parse(d.due_date);
              return (
                <button key={d.id} className={`next u-${urgency(due, now)}`} onClick={() => showDay(due)}>
                  <span>{relative(due, now)}</span><b>{d.title}</b><small>{d.course_name ?? (shortCode(d.course_code) || "UniSIS")}{d.extracted_by_ai ? " · found by AI" : ""}</small>
                </button>
              );
            })}
          </div>
        ) : !loading && <p className="hero-sub">Connect your university systems to see assignments and exams here.</p>}
      </section>

      {missing.length > 0 && !loading && (
        <section className="setup" aria-label="Finish setup">
          <Icon name="link" />
          <div><b>Connect {missing.join(" and ")}</b><p>{missing.includes("UniLearn") ? "Your assignments and course events come from UniLearn. " : ""}{missing.includes("UniSIS") ? "Timetable and exam registration come from UniSIS." : ""}</p></div>
          <button className="btn primary" onClick={() => onNavigate("connections")}>Connect</button>
        </section>
      )}
      {aiNew > 0 && (
        <button className="ai-alert" onClick={() => onNavigate("inbox")}>
          <Icon name="sparkle" /><span><b>{aiNew === 1 ? "1 new date" : `${aiNew} new dates`} found in your messages.</b> Review them in the inbox.</span><Icon name="arrow" size={16} />
        </button>
      )}
      {overdue.length > 0 && (
        <section className="overdue" aria-label="Overdue">
          <b><Icon name="alert" size={16} /> Overdue</b>
          {overdue.map((d) => <span key={d.id}>{d.title} · {relative(parse(d.due_date), now)}</span>)}
        </section>
      )}

      {!loading && user?.role === "student" && <FoundDates />}

      <div className="cal-bar">
        <div className="seg cal-views" role="tablist" aria-label="Calendar view">
          {VIEWS.map((v) => (
            <button key={v.id} role="tab" aria-selected={view === v.id} onClick={() => setView(v.id)}>{v.label}</button>
          ))}
        </div>
        <button className="btn" onClick={goToday}>Today</button>
        <button className={`btn plan-btn ${planned ? "on" : ""}`} aria-pressed={planned} onClick={() => setPlanned((p) => !p)}>
          <Icon name="wand" size={16} /> {planned ? `${blocks.length} study blocks planned` : "Plan my week"}
        </button>
        {user?.role === "student" && <FindExamsButton />}
      </div>

      {courses.length > 0 && (
        <div className="filters" role="group" aria-label="Filter by course">
          <button aria-pressed={course === null} onClick={() => setCourse(null)}>All courses</button>
          {courses.map(([code, name]) => (
            <button key={code} aria-pressed={course === code} title={code} onClick={() => setCourse(course === code ? null : code)} style={{ ["--c" as string]: courseColor(code) }}><i />{name}</button>
          ))}
        </div>
      )}

      {loading ? <Skeleton lines={4} /> : (
        <Calendar view={view} items={items} now={now} weekOff={weekOff} setWeekOff={setWeekOff}
          monthOff={monthOff} setMonthOff={setMonthOff} selected={selected} setSelected={setSelected} />
      )}
    </>
  );
}
