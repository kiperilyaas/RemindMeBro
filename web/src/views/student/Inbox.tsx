import { useMemo, useState } from "react";
import type { InboxItem, Source } from "../../api/types";
import { Icon } from "../../components/Icon";
import { CourseChip, Empty, PageHeader, Skeleton, SourceTag } from "../../components/ui";
import { SOURCES } from "../../lib/domain";
import { fmtDay, fmtTime, parse, timeAgo } from "../../lib/time";
import { useSession } from "../../state/session";
import { useStudent } from "../../state/student";

type Filter = "important" | "all" | Source;
const FILTERS: [Filter, string][] = [["important", "Important"], ["all", "All"], ["teams", "Teams"], ["moodle", "UniLearn"], ["email", "Email"]];

function Avatar({ m }: { m: InboxItem }) {
  const letter = m.author.replace(/^Prof\.?\s+/i, "").trim()[0] ?? "?";
  return <span className="mav" style={{ background: SOURCES[m.source].color }} aria-hidden>{letter}</span>;
}

export function Inbox() {
  const { now } = useSession();
  const { loading, inbox, isRead, markRead } = useStudent();
  const [filter, setFilter] = useState<Filter>("important");
  const [openId, setOpenId] = useState<number | null>(null);
  const list = useMemo(() => inbox
    .filter((m) => filter === "all" || (filter === "important" ? m.important || !!m.deadline_id : m.source === filter))
    .sort((a, b) => b.created_at.localeCompare(a.created_at)), [inbox, filter]);
  const unreadHere = list.filter((m) => !isRead(m.id));
  const count = (f: Filter) => inbox.filter((m) => !isRead(m.id) && (f === "all" || (f === "important" ? m.important || !!m.deadline_id : m.source === f))).length;

  return (
    <>
      <PageHeader eyebrow="Teams · UniLearn · Email" title="Inbox"
        actions={unreadHere.length > 0 && <button className="btn" onClick={() => markRead(unreadHere.map((m) => m.id))}><Icon name="check" size={16} /> Mark all as read</button>} />
      <div className="seg scroll" role="tablist" aria-label="Filter messages">
        {FILTERS.map(([f, label]) => (
          <button key={f} role="tab" aria-selected={filter === f} onClick={() => { setFilter(f); setOpenId(null); }}>
            {label}{count(f) > 0 && <span className="seg-n">{count(f)}</span>}
          </button>
        ))}
      </div>
      {loading ? <Skeleton lines={5} /> : list.length === 0 ? (
        <Empty icon="inbox" title={inbox.length ? "No messages here" : "No messages yet"}>
          {inbox.length ? "Try another filter." : "Press Sync: Remind Me Bro reads Teams, UniLearn announcements and email for you."}
        </Empty>
      ) : (
        <ul className="mlist">
          {list.map((m) => {
            const open = openId === m.id;
            const unread = !isRead(m.id);
            const at = parse(m.created_at);
            return (
              <li key={m.id} className={`${unread ? "unread" : ""} ${open ? "open" : ""}`}>
                <button className="mrow" aria-expanded={open} aria-controls={`msg-${m.id}`} onClick={() => { setOpenId(open ? null : m.id); if (unread) markRead([m.id]); }}>
                  <Avatar m={m} />
                  <span className="mtxt">
                    <span className="mline"><b>{m.author}</b><time dateTime={m.created_at} title={`${fmtDay(at)} ${fmtTime(at)}`}>{timeAgo(at, now)}</time></span>
                    <span className="msub">{m.subject}</span>
                    <span className="mmeta"><SourceTag source={m.source} />{m.course_code && <CourseChip code={m.course_code} />}
                      {m.deadline_id && m.deadline_due && <span className="ai"><Icon name="sparkle" size={12} /> date found · {fmtDay(parse(m.deadline_due))}</span>}</span>
                  </span>
                  {unread && <span className="udot" aria-label="Unread" />}
                </button>
                {open && (
                  <div className="mbody" id={`msg-${m.id}`}>
                    <p>{m.content}</p>
                    <div className={`ai-sum ${m.deadline_id ? "hit" : ""}`}><Icon name="sparkle" size={16} /><span><b>AI summary</b> {m.ai_summary}</span></div>
                    <p className="mfoot">{m.course_name ?? "University"} · {fmtDay(at)} {fmtTime(at)}</p>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
