// "Find exam dates" (Free plan): searches the course files (syllabus, first-lesson slides) for exam dates.
// Found dates are only proposals: each one shows the sentence of the file, and reaches the calendar only with "Add to calendar".
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { FoundDate, FoundDatesStatus } from "../../api/types";
import { Icon } from "../../components/Icon";
import { Spinner } from "../../components/ui";
import { courseColor } from "../../lib/domain";
import { fmtLong, parse } from "../../lib/time";
import { useStudent } from "../../state/student";
import { useToast } from "../../state/toast";

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

/** Button + progress + list of dates to review, shown on the Timeline. */
export function FoundDates() {
  const { reload } = useStudent();
  const toast = useToast();
  const [status, setStatus] = useState<FoundDatesStatus>({ state: "idle" });
  const [pending, setPending] = useState<FoundDate[]>([]);
  const [busyId, setBusyId] = useState<number | null>(null);
  const timer = useRef<number | null>(null);
  const wasRunning = useRef(false);

  const load = useCallback(async () => {
    try {
      const r = await api.foundDates();
      if (!r || !r.status) return;
      setStatus(r.status);
      setPending(r.pending ?? []);
      if (r.status.state === "running") {
        wasRunning.current = true;
        timer.current = window.setTimeout(() => void load(), 2000);
      } else if (wasRunning.current) {
        wasRunning.current = false;
        if (r.status.state === "error") toast("Could not search the course files", r.status.error ?? "", "error");
        else if (r.pending.length) toast(r.pending.length === 1 ? "1 date found" : `${r.pending.length} dates found`, "Check each one before adding it to your calendar.", "ok");
        else toast("No new exam dates", "No exam, test, presentation or submission date is written in your course files.", "info");
      }
    } catch { /* offline: the session shows it */ }
  }, [toast]);
  useEffect(() => { void load(); return () => { if (timer.current) clearTimeout(timer.current); }; }, [load]);

  const start = async () => {
    try { setStatus(await api.scanFoundDates()); wasRunning.current = true; if (timer.current) clearTimeout(timer.current); timer.current = window.setTimeout(() => void load(), 1500); }
    catch (e) { toast("Could not start the search", (e as Error).message, "error"); }
  };
  const decide = async (f: FoundDate, accept: boolean) => {
    setBusyId(f.id);
    try {
      if (accept) { await api.acceptFoundDate(f.id); await reload(); toast("Added to your calendar", `${f.title} · ${f.course_name}`, "ok"); }
      else { await api.rejectFoundDate(f.id); toast("Left out", "This date will not be proposed again.", "info"); }
      setPending((p) => p.filter((x) => x.id !== f.id));
    } catch (e) { toast("Could not save it", (e as Error).message, "error"); }
    setBusyId(null);
  };

  const running = status.state === "running";
  return (
    <section className="found" aria-label="Exam dates in your course files">
      <div className="found-head">
        <Icon name="search" />
        <div>
          <b>{pending.length ? `${pending.length} date${pending.length > 1 ? "s" : ""} found in your course files` : "Exam dates in your course files"}</b>
          <p>{running
            ? `Reading ${Math.min((status.files_done ?? 0) + 1, status.files_total || 1)} of ${status.files_total || "…"} files${status.current ? `: ${status.current}` : ""}`
            : pending.length ? "Only dates written in the files. Check the sentence, then add the ones that are right."
              : "Reads the syllabus and slides of your courses and finds exams, tests, presentations and submissions."}</p>
        </div>
        <button className="btn" onClick={() => void start()} disabled={running}>
          {running ? <><Spinner label="Searching" /> Searching…</> : <><Icon name="search" size={16} /> Find exam dates</>}
        </button>
      </div>
      {pending.length > 0 && (
        <ul className="found-list">
          {pending.map((f) => <FoundCard key={f.id} f={f} busy={busyId === f.id} onAccept={() => void decide(f, true)} onReject={() => void decide(f, false)} />)}
        </ul>
      )}
    </section>
  );
}
