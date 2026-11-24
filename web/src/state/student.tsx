import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "../api/client";
import type { Connection, Course, Deadline, InboxItem, ScheduleEvent, SyncSummary } from "../api/types";
import { storage } from "../lib/storage";
import { addDays, isoDate, mondayOf } from "../lib/time";
import { useSession } from "./session";
import { useToast } from "./toast";

interface StudentData {
  loading: boolean; courses: Course[]; deadlines: Deadline[]; inbox: InboxItem[]; events: ScheduleEvent[]; connections: Connection[];
  unread: number; isRead: (id: number) => boolean; markRead: (ids: number[]) => void;
  reload: () => Promise<void>; toggleDone: (d: Deadline) => Promise<void>;
  syncing: boolean; runSync: () => Promise<SyncSummary | null>;
  connection: (p: Connection["provider"]) => Connection | undefined;
}
const Ctx = createContext<StudentData | null>(null);

export function StudentProvider({ children }: { children: ReactNode }) {
  const { user, now } = useSession();
  const toast = useToast();
  const [loading, setLoading] = useState(true);
  const [courses, setCourses] = useState<Course[]>([]);
  const [deadlines, setDeadlines] = useState<Deadline[]>([]);
  const [inbox, setInbox] = useState<InboxItem[]>([]);
  const [events, setEvents] = useState<ScheduleEvent[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [syncing, setSyncing] = useState(false);
  const readKey = `rmb.read.${user?.id ?? 0}`;
  const [read, setRead] = useState<Set<number>>(() => new Set(storage.getJSON<number[]>(readKey, [])));
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  const reload = useCallback(async () => {
    // Range: from the Monday of the week holding the 1st of this month (the calendar's month grid) to ~4 months ahead.
    const from = mondayOf(new Date(now.getFullYear(), now.getMonth(), 1)), to = addDays(now, 120);
    const [c, d, i, s, cn] = await Promise.allSettled([
      api.courses(), api.deadlines(), api.inbox(), api.schedule(isoDate(from), isoDate(to)), api.connections(),
    ]);
    if (!alive.current) return;
    if (c.status === "fulfilled") setCourses(c.value);
    if (d.status === "fulfilled") setDeadlines(d.value);
    if (i.status === "fulfilled") setInbox(i.value);
    if (s.status === "fulfilled") setEvents(s.value);
    if (cn.status === "fulfilled") setConnections(cn.value);
    const failed = [c, d, i, s, cn].find((r): r is PromiseRejectedResult => r.status === "rejected" && !(r.reason as ApiError).offline);
    if (failed) toast("Some data could not be loaded", (failed.reason as Error).message, "error");
    setLoading(false);
  }, [now, toast]);

  useEffect(() => { void reload(); }, [reload]);

  const toggleDone = useCallback(async (d: Deadline) => {
    const next = !d.is_completed;
    setDeadlines((all) => all.map((x) => (x.id === d.id ? { ...x, is_completed: next } : x)));
    try { await api.setDone(d.id, next); }
    catch (e) {
      setDeadlines((all) => all.map((x) => (x.id === d.id ? { ...x, is_completed: !next } : x)));
      toast("Could not save", (e as Error).message, "error");
    }
  }, [toast]);

  const markRead = useCallback((ids: number[]) => {
    setRead((prev) => { const s = new Set(prev); ids.forEach((id) => s.add(id)); storage.setJSON(readKey, [...s]); return s; });
  }, [readKey]);
  const isRead = useCallback((id: number) => read.has(id), [read]);

  const runSync = useCallback(async () => {
    setSyncing(true);
    toast("Sync started", "Reading UniLearn, UniSIS, Teams and email. The local AI looks for hidden dates, this can take a minute.");
    try {
      const s = await api.sync();
      await reload();
      const parts = [
        s.unilearn ? `${s.moodle_deadlines_imported} UniLearn assignments` : "UniLearn not connected",
        `${s.teams_messages_processed + (s.emails_processed || 0)} messages read`,
        `${s.ai_deadlines_extracted} dates found by AI`,
      ];
      toast("Everything is up to date", parts.join(" · ") + (s.errors.length ? ` · ${s.errors.length} warning(s)` : ""), "ok");
      return s;
    } catch (e) { toast("Sync failed", (e as Error).message, "error"); return null; }
    finally { if (alive.current) setSyncing(false); }
  }, [reload, toast]);

  const connection = useCallback((p: Connection["provider"]) => connections.find((c) => c.provider === p), [connections]);
  const unread = useMemo(() => inbox.filter((m) => !read.has(m.id)).length, [inbox, read]);
  const value = useMemo<StudentData>(() => ({ loading, courses, deadlines, inbox, events, connections, unread, isRead, markRead, reload, toggleDone, syncing, runSync, connection }),
    [loading, courses, deadlines, inbox, events, connections, unread, isRead, markRead, reload, toggleDone, syncing, runSync, connection]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStudent(): StudentData {
  const c = useContext(Ctx);
  if (!c) throw new Error("useStudent must be used inside <StudentProvider>");
  return c;
}
