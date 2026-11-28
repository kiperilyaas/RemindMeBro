// Student calendar (design "A"): Agenda for the next three weeks, Week with a day strip, Month grid + chosen day.
// Classes and exams come from UniSIS/UniLearn events, deadlines from every source, study blocks from "Plan my week".
import { useMemo, useRef, type ReactNode } from "react";
import { api } from "../../api/client";
import type { Deadline, ScheduleEvent } from "../../api/types";
import { Icon } from "../../components/Icon";
import { AiTag, SourceTag } from "../../components/ui";
import { courseColor, effortHours, kindOf, urgency, type StudyBlock } from "../../lib/domain";
import { addDays, fmtDay, fmtDayMonth, fmtTime, isoDate, mondayOf, parse, relative, sameDay, startOfDay, weekdayLong } from "../../lib/time";
import { useStudent } from "../../state/student";

export type CalView = "agenda" | "week" | "month";
export type CalItem =
  | { type: "event"; key: string; at: Date; code: string | null; e: ScheduleEvent }
  | { type: "deadline"; key: string; at: Date; code: string | null; d: Deadline }
  | { type: "study"; key: string; at: Date; code: string | null; b: StudyBlock };

const KIND_LABEL = { exam: "Exam", registration: "Registration", assignment: "Deadline" } as const;
const WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
export const AGENDA_DAYS = 21;

// ---------- cards ----------
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
      {!!e.also_in?.length && <p className="also-in"><Icon name="check" size={13} /> Also in: {e.also_in.join(" · ")}</p>}
    </div>
  );
}

function DeadlineCard({ d, now }: { d: Deadline; now: Date }) {
  const { toggleDone, reload } = useStudent();
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
      <span className="sub">{d.course_name ?? "Student Office"}{d.time_known === false && " · time not stated"}{effort > 0 && ` · about ${effort} h of work`}</span>
      {d.replaces && (
        <p className="moved"><Icon name="sparkle" size={14} /> Moved from <s>{fmtDay(parse(d.replaces.old_due_date))}</s> → <b>{fmtDay(due)} {fmtTime(due)}</b></p>
      )}
      {d.found_in ? <>
        <blockquote className="quote">“{d.description}”</blockquote>
        <p className="found-src"><Icon name="book" size={14} /> Found in {d.found_in}
          <button className="link-btn" onClick={() => void api.removeFoundDate(d.id).then(reload)}>Remove</button></p>
      </> : d.source_message ? <>
        <blockquote className="quote">“{d.source_message}”</blockquote>
        {d.needs_confirmation && d.announcement_id && <p className="found-src"><Icon name="sparkle" size={14} /> Added from a message
          <button className="link-btn" onClick={() => void api.undoMessageDate(d.id).then(reload)}>Remove</button></p>}
      </> : d.description && <p className="note">{d.description}</p>}
      {!!d.also_in?.length && <p className="also-in"><Icon name="check" size={13} /> Also in: {d.also_in.join(" · ")}</p>}
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

/** One day's items as the existing feed; `nowLine` draws the red "now" line between past and future items. */
export function Feed({ items, now, nowLine = false }: { items: CalItem[]; now: Date; nowLine?: boolean }) {
  const cut = nowLine ? items.findIndex((it) => it.at > now) : -1;
  const line = (
    <li key="now" className="now-line" aria-label={`Now, ${fmtTime(now)}`}><span className="nl-dot" /><span className="nl-bar" /><time>{fmtTime(now)}</time></li>
  );
  return (
    <ol className="feed">
      {items.map((it, i) => {
        const done = it.type === "deadline" && it.d.is_completed;
        return [
          nowLine && i === cut ? line : null,
          <li key={it.key} className={`fi ${it.type} ${done ? "is-done" : ""}`} style={{ ["--c" as string]: courseColor(it.code) }}>
            <time dateTime={it.at.toISOString()}>{it.type === "deadline" && it.d.time_known === false ? "—" : fmtTime(it.at)}<small>{it.type === "event" ? fmtTime(parse(it.e.end_time)) : it.type === "deadline" ? (it.d.time_known === false ? "no time" : "due") : fmtTime(it.b.end)}</small></time>
            {it.type === "event" ? <EventCard e={it.e} now={now} /> : it.type === "deadline" ? <DeadlineCard d={it.d} now={now} /> : <StudyCard b={it.b} />}
          </li>,
        ];
      })}
      {nowLine && cut === -1 && line}
    </ol>
  );
}

// ---------- helpers ----------
/** Everything to show, sorted, optionally only one course. */
export function buildItems(events: ScheduleEvent[], deadlines: Deadline[], blocks: StudyBlock[], course: string | null): CalItem[] {
  const keep = (code: string | null) => !course || code === course;
  const list: CalItem[] = [
    ...events.filter((e) => keep(e.course_code)).map((e) => ({ type: "event" as const, key: `e${e.id}`, at: parse(e.start_time), code: e.course_code, e })),
    ...deadlines.filter((d) => keep(d.course_code)).map((d) => ({ type: "deadline" as const, key: `d${d.id}`, at: parse(d.due_date), code: d.course_code, d })),
    ...blocks.filter((b) => keep(b.course_code)).map((b) => ({ type: "study" as const, key: b.id, at: b.start, code: b.course_code, b })),
  ];
  return list.sort((a, b) => a.at.getTime() - b.at.getTime());
}

/** Items grouped by local day (YYYY-MM-DD). */
export function byDay(items: CalItem[]): Map<string, CalItem[]> {
  const m = new Map<string, CalItem[]>();
  for (const it of items) { const k = isoDate(it.at); const l = m.get(k); if (l) l.push(it); else m.set(k, [it]); }
  return m;
}

const isExam = (it: CalItem) => it.type === "event" && it.e.kind === "exam";
const isClass = (it: CalItem) => it.type === "event" && it.e.kind !== "exam";

/** "2 classes · 1 deadline · 1 exam", or "free". */
export function countLabel(list: CalItem[]): string {
  const cl = list.filter(isClass).length, dl = list.filter((i) => i.type === "deadline").length;
  const ex = list.filter(isExam).length, st = list.filter((i) => i.type === "study").length;
  return [cl && `${cl} class${cl > 1 ? "es" : ""}`, dl && `${dl} deadline${dl > 1 ? "s" : ""}`, ex && `${ex} exam${ex > 1 ? "s" : ""}`, st && `${st} study block${st > 1 ? "s" : ""}`]
    .filter(Boolean).join(" · ") || "free";
}

/** Up to three markers: one dot per course with a class, a square for deadlines, a ring for exams. */
function Dots({ list }: { list: CalItem[] }) {
  const out: ReactNode[] = [];
  const codes = [...new Set(list.filter(isClass).map((i) => i.code))];
  codes.forEach((c) => out.push(<i key={`c${c}`} className="cd" style={{ background: courseColor(c) }} />));
  if (list.some((i) => i.type === "deadline" && !i.d.is_completed)) out.push(<i key="d" className="dd" />);
  if (list.some(isExam)) out.push(<i key="x" className="xd" />);
  return <span className="cal-dots" aria-hidden>{out.length > 3 ? [...out.slice(0, 2), out[out.length - 1]] : out}</span>;
}

function isoWeek(monday: Date): number {
  const thursday = addDays(monday, 3);
  const jan1 = new Date(thursday.getFullYear(), 0, 1);
  return Math.floor((thursday.getTime() - jan1.getTime()) / 864e5 / 7) + 1;
}

// ---------- views ----------
function Agenda({ days, now }: { days: Map<string, CalItem[]>; now: Date }) {
  const today = startOfDay(now);
  const rows = [];
  for (let i = 0; i < AGENDA_DAYS; i++) {
    const d = addDays(today, i), list = days.get(isoDate(d)) ?? [];
    if (!list.length && i > 0) continue;
    rows.push(
      <section key={isoDate(d)} className="cal-day" aria-label={i === 0 ? "Today" : weekdayLong(d)}>
        <h2 className="day-h">{i === 0 ? "Today" : i === 1 ? "Tomorrow" : fmtDay(d)}<span>{i < 2 ? `${fmtDayMonth(d)} · ` : ""}{countLabel(list)}</span></h2>
        {list.length ? <Feed items={list} now={now} nowLine={i === 0} /> : <p className="cal-free">Nothing else today.</p>}
      </section>,
    );
  }
  return (
    <div className="cal-agenda">
      {rows}
      <p className="cal-end">That's the next three weeks. Switch to Month to look further.</p>
    </div>
  );
}

function Week({ days, now, offset, onOffset }: { days: Map<string, CalItem[]>; now: Date; offset: number; onOffset: (n: number) => void }) {
  const monday = addDays(mondayOf(now), offset * 7);
  const week = Array.from({ length: 7 }, (_, i) => addDays(monday, i));
  const all = week.flatMap((d) => days.get(isoDate(d)) ?? []);
  const refs = useRef<Record<string, HTMLElement | null>>({});
  const label = `${monday.getDate()} ${monday.toLocaleDateString("en-GB", { month: "short" })} – ${week[6].getDate()} ${week[6].toLocaleDateString("en-GB", { month: "short" })}`;
  return (
    <div className="cal-week">
      <div className="cal-nav">
        <button className="icon-btn" onClick={() => onOffset(offset - 1)} aria-label="Previous week"><Icon name="chev-left" /></button>
        <div><b>Week {isoWeek(monday)} · {label}</b><small>{countLabel(all)}</small></div>
        <button className="icon-btn" onClick={() => onOffset(offset + 1)} aria-label="Next week"><Icon name="chev-right" /></button>
      </div>
      <div className="cal-strip">
        {week.map((d, i) => {
          const list = days.get(isoDate(d)) ?? [];
          return (
            <button key={isoDate(d)} className={`dchip ${sameDay(d, now) ? "today sel" : ""}`} onClick={() => refs.current[isoDate(d)]?.scrollIntoView({ behavior: "smooth", block: "start" })}
              aria-label={`${weekdayLong(d)} ${fmtDayMonth(d)}: ${countLabel(list)}`}>
              <span className="dw">{WD[i]}</span><span className="dn">{d.getDate()}</span><Dots list={list} />
            </button>
          );
        })}
      </div>
      {week.map((d) => {
        const list = days.get(isoDate(d)) ?? [];
        const t = sameDay(d, now);
        return (
          <section key={isoDate(d)} ref={(el) => { refs.current[isoDate(d)] = el; }} className={`cal-day ${t ? "is-today" : ""}`}>
            <h2 className="day-h">{weekdayLong(d)} {d.getDate()}<span>{t ? "today · " : ""}{countLabel(list)}</span></h2>
            {list.length > 0 && <Feed items={list} now={now} nowLine={t} />}
          </section>
        );
      })}
    </div>
  );
}

function Month({ days, now, offset, onOffset, selected, onSelect }: {
  days: Map<string, CalItem[]>; now: Date; offset: number; onOffset: (n: number) => void; selected: Date; onSelect: (d: Date) => void;
}) {
  const first = new Date(now.getFullYear(), now.getMonth() + offset, 1);
  const start = mondayOf(first);
  const cells = Array.from({ length: 42 }, (_, i) => addDays(start, i));
  const sel = days.get(isoDate(selected)) ?? [];
  const title = first.toLocaleDateString("en-GB", { month: "long", year: "numeric" });
  return (
    <div className="cal-month">
      <div className="cal-nav">
        <button className="icon-btn" onClick={() => onOffset(offset - 1)} aria-label="Previous month"><Icon name="chev-left" /></button>
        <div><b>{title}</b></div>
        <button className="icon-btn" onClick={() => onOffset(offset + 1)} aria-label="Next month"><Icon name="chev-right" /></button>
      </div>
      <div className="cal-grid-box">
        <div className="cal-grid cal-wd" aria-hidden>{WD.map((w) => <span key={w}>{w}</span>)}</div>
        <div className="cal-grid" role="grid" aria-label={title}>
          {cells.map((d) => {
            const list = days.get(isoDate(d)) ?? [];
            const out = d.getMonth() !== first.getMonth(), t = sameDay(d, now), s = sameDay(d, selected);
            return (
              <button key={isoDate(d)} className={`cal-cell ${out ? "out" : ""} ${t ? "today" : ""} ${s ? "sel" : ""}`} aria-pressed={s} onClick={() => onSelect(d)}
                aria-label={`${weekdayLong(d)} ${fmtDayMonth(d)}: ${countLabel(list)}`}>
                <span className="cn">{d.getDate()}</span><Dots list={list} />
              </button>
            );
          })}
        </div>
        <div className="cal-legend" aria-hidden><span><i className="cd" />class</span><span><i className="dd" />deadline</span><span><i className="xd" />exam</span></div>
      </div>
      <section className="cal-day">
        <h2 className="day-h">{sameDay(selected, now) ? "Today" : weekdayLong(selected)} {selected.getDate()} {selected.toLocaleDateString("en-GB", { month: "long" })}<span>{countLabel(sel)}</span></h2>
        {sel.length > 0 ? <Feed items={sel} now={now} nowLine={sameDay(selected, now)} /> : <p className="cal-free">Nothing on this day.</p>}
      </section>
    </div>
  );
}

export function Calendar({ view, items, now, weekOff, setWeekOff, monthOff, setMonthOff, selected, setSelected }: {
  view: CalView; items: CalItem[]; now: Date;
  weekOff: number; setWeekOff: (n: number) => void; monthOff: number; setMonthOff: (n: number) => void; selected: Date; setSelected: (d: Date) => void;
}) {
  const days = useMemo(() => byDay(items), [items]);
  if (view === "week") return <Week days={days} now={now} offset={weekOff} onOffset={setWeekOff} />;
  if (view === "month") return <Month days={days} now={now} offset={monthOff} onOffset={setMonthOff} selected={selected} onSelect={setSelected} />;
  return <Agenda days={days} now={now} />;
}
