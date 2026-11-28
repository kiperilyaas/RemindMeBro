// A date the AI found in a message (Outlook, Teams, UniLearn announcement) reaches the calendar only after this confirmation.
import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { InboxItem } from "../../api/types";
import { Icon } from "../../components/Icon";
import { Spinner } from "../../components/ui";
import { SOURCES } from "../../lib/domain";
import { fmtDay, fmtLong, fmtTime, parse } from "../../lib/time";
import { useStudent } from "../../state/student";
import { useToast } from "../../state/toast";

/** "Tuesday 15 December · 9:15", or "… · time not stated" when the message gives only the day (stored as 23:59). */
export function whenLabel(iso: string): string {
  const d = parse(iso);
  const t = fmtTime(d);
  return `${fmtLong(d)} · ${t === "23:59" ? "time not stated" : t}`;
}

export function ConfirmDate({ m, onClose }: { m: InboxItem; onClose: () => void }) {
  const { reload } = useStudent();
  const toast = useToast();
  const [busy, setBusy] = useState<"" | "add" | "no">("");
  const addBtn = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    addBtn.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !busy) onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);
  if (!m.deadline_id || !m.deadline_due) return null;
  const id = m.deadline_id;

  const decide = async (accept: boolean) => {
    setBusy(accept ? "add" : "no");
    try {
      if (accept) { await api.acceptMessageDate(id); toast("Added to your calendar", `${m.deadline_title ?? "Date"} · ${m.course_name ?? ""}`, "ok"); }
      else { await api.rejectMessageDate(id); toast("Left out", "This date stays out of your calendar.", "info"); }
      await reload();
      onClose();
    } catch (e) { toast("Could not save it", (e as Error).message, "error"); setBusy(""); }
  };

  return (
    <div className="modal-wrap">
      <div className="sheet-scrim show" onClick={() => !busy && onClose()} aria-hidden />
      <div className="modal confirm-date" role="dialog" aria-modal="true" aria-labelledby="cd-title">
        <p className="eyebrow"><Icon name="sparkle" size={14} /> Date found in a message</p>
        <h2 id="cd-title">Add to your calendar?</h2>
        <div className="cd-what">
          <b>{m.deadline_title ?? "Deadline"}</b>
          <span>{whenLabel(m.deadline_due)}</span>
          {m.course_name && <span className="muted">{m.course_name}</span>}
        </div>
        <blockquote className="quote">“{m.content.length > 260 ? `${m.content.slice(0, 260).trimEnd()}…` : m.content}”</blockquote>
        <p className="cd-from">{SOURCES[m.source].label} · {m.author}</p>
        {m.deadline_replaces && (
          <p className="cd-replaces"><Icon name="alert" size={14} /> This moves <b>{m.deadline_replaces.title}</b> from {fmtDay(parse(m.deadline_replaces.due_date))}: the old date leaves your calendar.</p>
        )}
        <div className="row-gap">
          <button ref={addBtn} className="btn primary" disabled={!!busy} onClick={() => void decide(true)}>
            {busy === "add" ? <><Spinner label="Adding" /> Adding…</> : <><Icon name="plus" size={16} /> Add to calendar</>}
          </button>
          <button className="btn ghost" disabled={!!busy} onClick={() => void decide(false)}>Not right</button>
          <button className="btn ghost" disabled={!!busy} onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
