import { useMemo, useState } from "react";
import type { Deadline, ScheduleEvent } from "../../api/types";
import { Icon } from "../../components/Icon";
import { AiTag, CourseChip, Empty, Skeleton, SourceTag } from "../../components/ui";
import { courseColor, effortHours, kindOf, planWeek, shortCode, urgency, type StudyBlock } from "../../lib/domain";
import { addDays, daysBetween, fmtDay, fmtDayMonth, fmtTime, greeting, parse, relative, sameDay, startOfDay, weekdayLong, weekdayShort } from "../../lib/time";
import { useSession } from "../../state/session";
import { useStudent } from "../../state/student";

type Item =
  | { type: "event"; key: string; at: Date; e: ScheduleEvent }
  | { type: "deadline"; key: string; at: Date; d: Deadline }
  | { type: "study"; key: string; at: Date; b: StudyBlock };

const KIND_LABEL = { exam: "Exam", registration: "Registration", assignment: "Deadline" } as const;

function EventCard({ e, now }: { e: ScheduleEvent; now: Date }) {
  const s = parse(e.start_time), en = parse(e.end_time);
  const live = s <= now && en > now;
  const exam = e.kind === "exam";
  // UniSIS timetable entries are called "Lecture", "Seminar"…: show the course as the title
  const generic = !!e.course_name && /^(lecture|seminar|lab|tutorial|class|exercise)s?\b/i.test(e.title);
  return (
    <div className={`fcard ${exam ? "exam" : "class"} ${live ? "live" : ""}`}>
      <div className="ftop">
        <span className="tag">{exam ? "Exam" : e.kind === "event" ? "Event" : "Class"}</span>
        <SourceTag source={e.source === "unisis" ? "unisis" : "moodle"} />
        {live && <span className="now">● Live now</span>}
      </div>
      <b>{generic ? e.course_name : e.title}</b>
      <span className="sub">{e.location && <><Icon name="pin" size={14} /> {e.location} · </>}{fmtTime(s)}–{fmtTime(en)}{generic ? ` · ${e.title}` : e.course_name && e.course_name !== e.title ? ` · ${e.course_name}` : ""}</span>
    </div>
  );
}

function DeadlineCard({ d, now }: { d: Deadline; now: Date }) {
  const { toggleDone } = useStudent();
  const due = parse(d.due_date);
  const kind = kindOf(d);
  const effort = effortHours(d);
  return (
    <div className={`fcard deadline u-${urgency(due, now)} ${d.is_completed ? "done" : ""}`}>
      <div className="ftop">
        <span className="tag">{KIND_LABEL[kind]}</span><SourceTag source={d.source} />{d.extracted_by_ai && <AiTag />}
        <span className="when">{relative(due, now)}</span>
      </div>
      <b>{d.title}</b>
      <span className="sub">{d.course_name ?? "Student Office"}{effort > 0 && ` · about ${effort} h of work`}</span>
      {d.replaces && (
        <p className="moved"><Icon name="sparkle" size={14} /> Moved from <s>{fmtDay(parse(d.replaces.old_due_date))}</s> → <b>{fmtDay(due)} {fmtTime(due)}</b></p>
      )}
      {d.source_message ? <blockquote className="quote">“{d.source_message}”</blockquote> : d.description && <p className="note">{d.description}</p>}
      <button className="done-btn" aria-pressed={d.is_completed} onClick={() => void toggleDone(d)}>
        <Icon name="check" size={16} /> {d.is_completed ? "Done" : "Mark as done"}
      </button>
    </div>
  );
}

function StudyCard({ b }: { b: StudyBlock }) {
  return (
    <div className="fcard study">
      <div className="ftop"><span className="tag">Study block</span><span className="plan-chip"><Icon name="wand" size={12} /> planned for you</span></div>
      <b>Work on: {b.title}</b>
      <span className="sub">{fmtTime(b.start)}–{fmtTime(b.end)} · free time between your classes</span>
    </div>
  );
}

export function Timeline({ onNavigate }: { onNavigate: (p: string) => void }) {
  const { now, user } = useSession();
  const { loading, deadlines, events, inbox, isRead, connection } = useStudent();
  const days = useMemo(() => Array.from({ length: 14 }, (_, i) => addDays(startOfDay(now), i)), [now]);
  const [day, setDay] = useState<Date>(() => startOfDay(now));
  const [course, setCourse] = useState<string | null>(null);
  const [planned, setPlanned] = useState(false);

  const open = useMemo(() => deadlines.filter((d) => !d.is_completed).sort((a, b) => a.due_date.localeCompare(b.due_date)), [deadlines]);
  const upcoming = open.filter((d) => parse(d.due_date) >= now);
  const overdue = open.filter((d) => parse(d.due_date) < startOfDay(now));
  const blocks = useMemo(() => (planned ? planWeek(deadlines, events, now) : []), [planned, deadlines, events, now]);
  const courses = useMemo(() => {
    const m = new Map<string, string>();
    [...events, ...deadlines].forEach((x) => { if (x.course_code) m.set(x.course_code, x.course_name ?? x.course_code); });
    return [...m.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [events, deadlines]);

  const items = useMemo<Item[]>(() => {
    const keep = (code: string | null) => !course || code === course;
    const list: Item[] = [
      ...events.filter((e) => sameDay(parse(e.start_time), day) && keep(e.course_code)).map((e) => ({ type: "event" as const, key: `e${e.id}`, at: parse(e.start_time), e })),
      ...deadlines.filter((d) => sameDay(parse(d.due_date), day) && keep(d.course_code)).map((d) => ({ type: "deadline" as const, key: `d${d.id}`, at: parse(d.due_date), d })),
      ...blocks.filter((b) => sameDay(b.start, day) && keep(b.course_code)).map((b) => ({ type: "study" as const, key: b.id, at: b.start, b })),
    ];
    return list.sort((a, b) => a.at.getTime() - b.at.getTime());
  }, [events, deadlines, blocks, day, course]);

  const aiNew = inbox.filter((m) => m.deadline_id && !isRead(m.id)).length;
  const ul = connection("moodle"), us = connection("unisis");
  const missing = [ul && ul.status !== "connected" ? "UniLearn" : null, us && us.status !== "connected" ? "UniSIS" : null].filter(Boolean) as string[];
  const soon = upcoming.filter((d) => daysBetween(now, parse(d.due_date)) <= 14).length;
  const isToday = sameDay(day, now);

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
                <button key={d.id} className={`next u-${urgency(due, now)}`} onClick={() => { const n = daysBetween(now, due); if (n < 14) setDay(startOfDay(due)); }}>
                  <span>{relative(due, now)}</span><b>{d.title}</b><small>{shortCode(d.course_code) || "UniSIS"}{d.extracted_by_ai ? " · found by AI" : ""}</small>
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
          {overdue.map((d) => <span key={d.id}>{d.title} · {fmtDay(parse(d.due_date))}</span>)}
        </section>
      )}

      <div className="strip-row">
        <div className="strip" role="tablist" aria-label="Choose a day">
          {days.map((x) => {
            const sel = sameDay(x, day);
            const dues = open.filter((d) => sameDay(parse(d.due_date), x)).length;
            const cls = events.filter((e) => sameDay(parse(e.start_time), x)).length;
            return (
              <button key={x.toISOString()} role="tab" aria-selected={sel} className={`dchip ${sel ? "sel" : ""} ${sameDay(x, now) ? "today" : ""}`} onClick={() => setDay(x)}
                aria-label={`${weekdayLong(x)} ${fmtDayMonth(x)}: ${cls} classes, ${dues} deadlines`}>
                <span className="dw">{weekdayShort(x)}</span><span className="dn">{x.getDate()}</span>
                <span className="dots" aria-hidden>{cls > 0 && <i className="c" />}{dues > 0 && <i className="d" />}</span>
              </button>
            );
          })}
        </div>
        <button className={`btn plan-btn ${planned ? "on" : ""}`} aria-pressed={planned} onClick={() => setPlanned((p) => !p)}>
          <Icon name="wand" size={16} /> {planned ? `${blocks.length} study blocks planned` : "Plan my week"}
        </button>
      </div>

      {courses.length > 0 && (
        <div className="filters" role="group" aria-label="Filter by course">
          <button aria-pressed={course === null} onClick={() => setCourse(null)}>All courses</button>
          {courses.map(([code]) => (
            <button key={code} aria-pressed={course === code} onClick={() => setCourse(course === code ? null : code)} style={{ ["--c" as string]: courseColor(code) }}><i />{shortCode(code)}</button>
          ))}
        </div>
      )}

      <h2 className="day-h">{isToday ? "Today" : weekdayLong(day)}<span>{fmtDayMonth(day)}</span></h2>
      {loading ? <Skeleton lines={4} /> : items.length ? (
        <ol className="feed">
          {items.map((it) => {
            const color = it.type === "event" ? courseColor(it.e.course_code) : it.type === "deadline" ? courseColor(it.d.course_code) : courseColor(it.b.course_code);
            const done = it.type === "deadline" && it.d.is_completed;
            return (
              <li key={it.key} className={`fi ${it.type} ${done ? "is-done" : ""}`} style={{ ["--c" as string]: color }}>
                <time dateTime={it.at.toISOString()}>{fmtTime(it.at)}<small>{it.type === "event" ? fmtTime(parse(it.e.end_time)) : it.type === "deadline" ? "due" : fmtTime(it.b.end)}</small></time>
                {it.type === "event" ? <EventCard e={it.e} now={now} /> : it.type === "deadline" ? <DeadlineCard d={it.d} now={now} /> : <StudyCard b={it.b} />}
              </li>
            );
          })}
        </ol>
      ) : (
        <Empty icon="calendar" title={`Nothing ${course ? "for this course " : ""}on this day`}>
          {upcoming[0] ? <>Free time — a good moment to get ahead on <b>{upcoming[0].title}</b> <CourseChip code={upcoming[0].course_code} />.</> : "Enjoy it."}
        </Empty>
      )}
    </>
  );
}
