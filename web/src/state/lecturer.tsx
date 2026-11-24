import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, ApiError } from "../api/client";
import type { CourseWithStats, Deadline } from "../api/types";
import { useToast } from "./toast";

interface LecturerData { loading: boolean; courses: CourseWithStats[]; extracted: Deadline[]; reload: () => Promise<void> }
const Ctx = createContext<LecturerData | null>(null);

export function LecturerProvider({ children }: { children: ReactNode }) {
  const toast = useToast();
  const [loading, setLoading] = useState(true);
  const [courses, setCourses] = useState<CourseWithStats[]>([]);
  const [extracted, setExtracted] = useState<Deadline[]>([]);
  const reload = useCallback(async () => {
    const [c, x] = await Promise.allSettled([api.prof.courses(), api.prof.extracted()]);
    if (c.status === "fulfilled") setCourses(c.value);
    if (x.status === "fulfilled") setExtracted(x.value);
    const failed = [c, x].find((r): r is PromiseRejectedResult => r.status === "rejected" && !(r.reason as ApiError).offline);
    if (failed) toast("Some data could not be loaded", (failed.reason as Error).message, "error");
    setLoading(false);
  }, [toast]);
  useEffect(() => { void reload(); }, [reload]);
  const value = useMemo(() => ({ loading, courses, extracted, reload }), [loading, courses, extracted, reload]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useLecturer(): LecturerData {
  const c = useContext(Ctx);
  if (!c) throw new Error("useLecturer must be used inside <LecturerProvider>");
  return c;
}
