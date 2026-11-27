// "Find exam dates": search status and dates to review, shared by the button in the top bar and the list on the Timeline.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "../api/client";
import type { FoundDate, FoundDatesStatus } from "../api/types";
import { useStudent } from "./student";
import { useToast } from "./toast";

interface FoundDatesData {
  status: FoundDatesStatus; pending: FoundDate[]; running: boolean; busyId: number | null;
  start: () => Promise<void>; decide: (f: FoundDate, accept: boolean) => Promise<void>;
}
const Ctx = createContext<FoundDatesData | null>(null);

export function FoundDatesProvider({ children }: { children: ReactNode }) {
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
        else if (r.pending.length) toast(r.pending.length === 1 ? "1 date found" : `${r.pending.length} dates found`, "Check each one on the Timeline before adding it to your calendar.", "ok");
        else toast("No new exam dates", "No exam, test, presentation or submission date is written in your course files.", "info");
      }
    } catch { /* offline: the session shows it */ }
  }, [toast]);
  useEffect(() => { void load(); return () => { if (timer.current) clearTimeout(timer.current); }; }, [load]);

  const start = useCallback(async () => {
    try {
      setStatus(await api.scanFoundDates());
      wasRunning.current = true;
      if (timer.current) clearTimeout(timer.current);
      timer.current = window.setTimeout(() => void load(), 1500);
    } catch (e) { toast("Could not start the search", (e as Error).message, "error"); }
  }, [load, toast]);

  const decide = useCallback(async (f: FoundDate, accept: boolean) => {
    setBusyId(f.id);
    try {
      if (accept) { await api.acceptFoundDate(f.id); await reload(); toast("Added to your calendar", `${f.title} · ${f.course_name}`, "ok"); }
      else { await api.rejectFoundDate(f.id); toast("Left out", "This date will not be proposed again.", "info"); }
      setPending((p) => p.filter((x) => x.id !== f.id));
    } catch (e) { toast("Could not save it", (e as Error).message, "error"); }
    setBusyId(null);
  }, [reload, toast]);

  const value = useMemo<FoundDatesData>(() => ({ status, pending, running: status.state === "running", busyId, start, decide }),
    [status, pending, busyId, start, decide]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useFoundDates(): FoundDatesData {
  const v = useContext(Ctx);
  if (!v) throw new Error("useFoundDates outside FoundDatesProvider");
  return v;
}
