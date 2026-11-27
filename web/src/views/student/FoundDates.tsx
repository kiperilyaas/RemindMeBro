// "Find exam dates" (Free plan): searches the course files (syllabus, first-lesson slides) for exam dates.
// The button sits in the top bar (FindDatesButton); the Timeline shows the progress and the dates to review (FoundDates).
// Found dates are only proposals: each one shows the sentence of the file, and reaches the calendar only with "Add to calendar".
import type { FoundDate } from "../../api/types";
import { Icon } from "../../components/Icon";
import { Spinner } from "../../components/ui";
import { courseColor } from "../../lib/domain";
import { fmtLong, parse } from "../../lib/time";
import { useFoundDates } from "../../state/foundDates";

function FoundCard({ f, busy, onAccept, onReject }: { f: FoundDate; busy: boolean; onAccept: () => void; onReject: () => void }) {
  const day = parse(`${f.date}T00:00:00`);
  return (
    <li className="found-card" style={{ ["--c" as string]: courseColor(f.course_code) }}>
      <div className="ftop">
        <span className="tag">{f.kind_label}</span>
        <span className="found-course" title={f.course_code}>{f.course_name}</span>
      </div>
      <b className="found-when">{fmtLong(day)}{f.year_written ? ` ${day.getFullYear()}` : ""} · {f.time ?? "time not stated"}{f.room ? ` · room ${f.room}` : ""}</b>
      <span className="found-title">{f.title}</span>
      <blockquote className="quote">“{f.quote}”</blockquote>
      <p className="found-src"><Icon name="book" size={14} /> {f.filename}{f.page ? ` · ${f.page.toLowerCase()}` : ""}
        {f.also_in.length > 0 && <> · also in {f.also_in.map((a) => a.filename).join(", ")}</>}</p>
      {!f.year_written && <p className="found-flag">The file does not write the year: {day.getFullYear()} is this academic year.</p>}
      {f.in_calendar && <p className="found-flag ok"><Icon name="check" size={14} /> Your calendar already has “{f.in_calendar}” that day.</p>}
      <div className="row-gap">
        <button className="btn primary sm" disabled={busy} onClick={onAccept}><Icon name="plus" size={14} /> Add to calendar</button>
        <button className="btn ghost sm" disabled={busy} onClick={onReject}>Not right</button>
      </div>
    </li>
  );
}

/** Top-bar button: starts the search (and opens the Timeline); shows how many dates wait for review. */
export function FindDatesButton({ onOpen }: { onOpen: () => void }) {
  const { running, pending, start } = useFoundDates();
  const label = running ? "Searching your course files for exam dates" : pending.length ? `${pending.length} exam dates to review` : "Find exam dates in your course files";
  return (
    <button className={`icon-btn find-btn ${running ? "busy" : ""}`} aria-label={label} title={label}
      onClick={() => { onOpen(); if (!running && !pending.length) void start(); }}>
      <Icon name="search" />
      {pending.length > 0 && !running && <span className="find-n" aria-hidden>{pending.length}</span>}
    </button>
  );
}

/** On the Timeline, only while searching or when dates wait for review: progress and the list. */
export function FoundDates() {
  const { status, pending, running, busyId, start, decide } = useFoundDates();
  if (!running && pending.length === 0) return null;
  return (
    <section className="found" aria-label="Exam dates in your course files">
      <div className="found-head">
        {running ? <Spinner label="Searching" /> : <Icon name="search" />}
        <div>
          <b>{running ? "Looking for exam dates" : `${pending.length} date${pending.length > 1 ? "s" : ""} found in your course files`}</b>
          <p>{running
            ? `Reading ${Math.min((status.files_done ?? 0) + 1, status.files_total || 1)} of ${status.files_total || "…"} files${status.current ? `: ${status.current}` : ""}`
            : "Only dates written in the files. Check the sentence, then add the ones that are right."}</p>
        </div>
        {!running && <button className="btn ghost sm" onClick={() => void start()} title="Search the course files again"><Icon name="sync" size={14} /> Again</button>}
      </div>
      {pending.length > 0 && (
        <ul className="found-list">
          {pending.map((f) => <FoundCard key={f.id} f={f} busy={busyId === f.id} onAccept={() => void decide(f, true)} onReject={() => void decide(f, false)} />)}
        </ul>
      )}
    </section>
  );
}
