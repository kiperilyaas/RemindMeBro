import { useMemo, useState } from "react";
import { Icon } from "../../components/Icon";
import { Empty, PageHeader, SourceTag } from "../../components/ui";
import { courseColor, effortHours, kindOf, shortCode, type Kind } from "../../lib/domain";
import { addDays, daysBetween, fmtDay, fmtDayMonth, fmtTime, mondayOf, monthShort, parse } from "../../lib/time";
import { useSession } from "../../state/session";
import { useStudent } from "../../state/student";
import type { Source } from "../../api/types";

interface Mark { key: string; title: string; at: Date; kind: Kind; course: string | null; courseName: string | null; source: Source; hours: number; done: boolean; ai: boolean }
const KINDS: { k: Kind; label: string }[] = [{ k: "assignment", label: "Assignments" }, { k: "exam", label: "Exams & tests" }, { k: "registration", label: "Registrations" }];

/** Semester at a glance: a workload curve per week plus one lane per course, aligned on the same week grid. */
export function Semester() {
  const { now } = useSession();
  const { deadlines, events } = useStudent();
  const [off, setOff] = useState<Kind[]>([]);
  const [picked, setSel] = useState<number | null>(null);
  const start = mondayOf(now);

  const marks = useMemo<Mark[]>(() => {
    const list: Mark[] = deadlines.map((d) => ({
      key: `d${d.id}`, title: d.title, at: parse(d.due_date), kind: kindOf(d), course: d.course_code, courseName: d.course_name,
      source: d.source, hours: effortHours(d), done: d.is_completed, ai: d.extracted_by_ai,
    }));
    // registered exams from the timetable (UniSIS) that are not already deadlines
    events.filter((e) => e.kind === "exam").forEach((e) => {
      const at = parse(e.start_time);
      if (!list.some((m) => m.kind === "exam" && m.course === e.course_code && daysBetween(m.at, at) === 0))
        list.push({ key: `e${e.id}`, title: e.title.replace(/^Exam:\s*/, ""), at, kind: "exam", course: e.course_code, courseName: e.course_name, source: "unisis", hours: 6, done: false, ai: false });
    });
    return list.filter((m) => m.at >= start).sort((a, b) => a.at.getTime() - b.at.getTime());
  }, [deadlines, events, start]);

  const visible = marks.filter((m) => !off.includes(m.kind));
  const lastWeek = Math.max(11, ...visible.map((m) => Math.floor(daysBetween(start, m.at) / 7)));
  const weeks = Array.from({ length: Math.min(lastWeek + 1, 20) }, (_, i) => addDays(start, i * 7));
  const weekOf = (d: Date) => Math.floor(daysBetween(start, d) / 7);
  const load = weeks.map((_, i) => visible.filter((m) => weekOf(m.at) === i && !m.done).reduce((a, m) => a + Math.max(m.hours, 1), 0));
  const maxLoad = Math.max(8, ...load);
  const busiest = load.indexOf(Math.max(...load));

  const lanes = useMemo(() => {
    const m = new Map<string, { code: string | null; name: string }>();
    visible.forEach((x) => m.set(x.course ?? "_", { code: x.course, name: x.courseName ?? "Student Office · UniSIS" }));
    return [...m.values()].sort((a, b) => (a.code ? a.name.localeCompare(b.name) : 1));
  }, [visible]);

  // until the student picks a week, show the first week that has something open
  const firstBusy = load.findIndex((h) => h > 0);
  const sel = picked ?? Math.max(0, firstBusy);
  const inWeek = visible.filter((m) => weekOf(m.at) === sel);
  const cols = { gridTemplateColumns: `minmax(120px, 170px) repeat(${weeks.length}, minmax(44px, 1fr))` };

  if (!marks.length) return <><PageHeader eyebrow="Winter term" title="Semester" /><Empty icon="map" title="No dates yet">Connect UniLearn and UniSIS, then press Sync to see your whole semester.</Empty></>;

  return (
    <>
      <PageHeader eyebrow={`${fmtDayMonth(weeks[0])} – ${fmtDayMonth(addDays(weeks[weeks.length - 1], 6))}`} title="Semester" />
      <div className="sem-summary">
        <div><b>{visible.filter((m) => !m.done).length}</b><small>open dates</small></div>
        <div><b>{visible.filter((m) => m.kind === "exam").length}</b><small>exams & tests</small></div>
        <div className="hot"><b>Week of {fmtDayMonth(weeks[busiest])}</b><small>busiest week · about {load[busiest]} h of work</small></div>
      </div>
      <div className="filters" role="group" aria-label="Show types">
        {KINDS.map(({ k, label }) => (
          <button key={k} aria-pressed={!off.includes(k)} onClick={() => setOff((o) => (o.includes(k) ? o.filter((x) => x !== k) : [...o, k]))}>
            <span className={`mk ${k}`} aria-hidden />{label}
          </button>
        ))}
      </div>

      <section className="sem panel" aria-label="Semester map">
        <div className="sem-scroll">
          <div className="sem-grid" style={cols}>
            <div className="sem-corner">Workload</div>
            {weeks.map((w, i) => (
              <button key={w.toISOString()} className={`wk ${i === sel ? "sel" : ""} ${i === 0 ? "now" : ""}`} onClick={() => setSel(i)}
                aria-pressed={i === sel} aria-label={`Week of ${fmtDayMonth(w)}: about ${load[i]} hours of work`}>
                <span className="bar-wrap"><span className="bar" style={{ height: `${Math.max(4, (load[i] / maxLoad) * 100)}%`, opacity: load[i] ? 1 : 0.25 }} /></span>
                <span className="wk-l">{w.getDate() <= 7 || i === 0 ? monthShort(w) : ""}<b>{w.getDate()}</b></span>
              </button>
            ))}
            {lanes.map((lane) => (
              <div className="lane" key={lane.code ?? "_"} style={{ display: "contents" }}>
                <div className="lane-h" style={{ ["--c" as string]: courseColor(lane.code) }}><i aria-hidden /><span>{lane.code ? shortCode(lane.code) : "UniSIS"}<small>{lane.name}</small></span></div>
                {weeks.map((_, i) => {
                  const here = visible.filter((m) => (m.course ?? null) === lane.code && weekOf(m.at) === i);
                  return (
                    <div key={i} className={`cell ${i === sel ? "sel" : ""}`} onClick={() => setSel(i)}>
                      {here.map((m) => (
                        <span key={m.key} className={`mk ${m.kind} ${m.done ? "done" : ""}`} style={{ ["--c" as string]: courseColor(m.course) }} title={`${m.title} · ${fmtDay(m.at)}`} />
                      ))}
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="panel week-detail" aria-live="polite">
        <div className="wd-h">
          <button className="icon-btn flip" disabled={sel === 0} onClick={() => setSel(sel - 1)} aria-label="Previous week"><Icon name="arrow" size={16} /></button>
          <h2>Week of {fmtDayMonth(weeks[sel])}{sel === 0 && <span className="pill plan">this week</span>}</h2>
          <button className="icon-btn" disabled={sel === weeks.length - 1} onClick={() => setSel(sel + 1)} aria-label="Next week"><Icon name="arrow" size={16} /></button>
        </div>
        {inWeek.length ? (
          <ul className="wd-list">{inWeek.map((m) => (
            <li key={m.key} className={m.done ? "done" : ""} style={{ ["--c" as string]: courseColor(m.course) }}>
              <span className={`mk ${m.kind}`} aria-hidden />
              <span className="grow"><b>{m.title}</b><small>{m.courseName ?? "Student Office"} · {fmtDay(m.at)} {fmtTime(m.at)}{m.hours ? ` · ~${m.hours} h` : ""}{m.ai ? " · found by AI" : ""}</small></span>
              <SourceTag source={m.source} />
            </li>))}</ul>
        ) : <p className="muted">Nothing due this week.</p>}
      </section>
    </>
  );
}
