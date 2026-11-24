// Domain rules shared by the views (pure functions, unit-tested).
import type { Deadline, ScheduleEvent, Source } from "../api/types";
import { addDays, daysBetween, parse, startOfDay } from "./time";

export const SOURCES: Record<Source, { label: string; color: string }> = {
  moodle: { label: "UniLearn", color: "#B5651D" },
  unisis: { label: "UniSIS", color: "#2F855A" },
  teams: { label: "Teams", color: "#5B5FC7" },
  email: { label: "Email", color: "#2F69A3" },
};

const KNOWN: Record<string, string> = {
  "MICRO-2026": "#3E6FD8", "CORPFIN-2026": "#0E9384", "FINACC-2026": "#C4730B", "FINMKT-2026": "#B83280", "ECMT-2026": "#6E56CF",
};
const PALETTE = ["#3E6FD8", "#0E9384", "#C4730B", "#B83280", "#6E56CF", "#D9480F", "#2F855A", "#0369A1"];
/** Stable colour per course code. */
export function courseColor(code: string | null | undefined): string {
  if (!code) return "#64748B";
  if (KNOWN[code]) return KNOWN[code];
  let h = 0;
  for (const ch of code) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}
/** "MICRO-2026" -> "MICRO". */
export const shortCode = (code: string | null | undefined) => (code ? code.replace(/-\d{4}$/, "") : "");

export type Kind = "exam" | "registration" | "assignment";
export function kindOf(d: Pick<Deadline, "title" | "source">): Kind {
  const t = d.title.toLowerCase();
  if (/\b(exam|midterm|test|quiz)\b/.test(t) && !/register|registration/.test(t)) return "exam";
  if (d.source === "unisis" || /register|registration|choose|elective|enrol/.test(t)) return "registration";
  return "assignment";
}

/** Rough effort estimate in hours, used by "Plan my week". */
export function effortHours(d: Pick<Deadline, "title" | "source" | "extracted_by_ai">): number {
  const k = kindOf(d);
  if (k === "registration") return 0;
  if (k === "exam") return 6;
  const t = d.title.toLowerCase();
  if (/project/.test(t)) return 8;
  if (/one-page|report|reading/.test(t) && d.extracted_by_ai) return 2;
  return 4;
}

export type Urgency = "now" | "soon" | "later" | "past";
export function urgency(due: Date, now: Date): Urgency {
  const n = daysBetween(now, due);
  if (n < 0) return "past";
  return n <= 3 ? "now" : n <= 10 ? "soon" : "later";
}

export interface StudyBlock { id: string; deadlineId: number; title: string; course_code: string | null; start: Date; end: Date }

/**
 * Spreads study time for open deadlines over the free hours of the next `days` days.
 * Rules: weekdays 09:00–19:00, Saturday 10:00–13:00, no Sunday; never during classes;
 * blocks of 1–2 h; every block must end before the deadline; earliest deadline first.
 */
export function planWeek(deadlines: Deadline[], events: ScheduleEvent[], now: Date, days = 7): StudyBlock[] {
  const busy = events.map((e) => [parse(e.start_time).getTime(), parse(e.end_time).getTime()] as const);
  const isFree = (s: number, e: number) => busy.every(([bs, be]) => e <= bs || s >= be);
  const taken: [number, number][] = [];
  const blocks: StudyBlock[] = [];
  const todo = deadlines
    .filter((d) => !d.is_completed && effortHours(d) > 0 && parse(d.due_date) > now)
    .sort((a, b) => a.due_date.localeCompare(b.due_date));

  // candidate hourly slots
  const slots: { s: number; dayEnd: number }[] = [];
  for (let i = 0; i < days; i++) {
    const day = addDays(startOfDay(now), i);
    const dow = day.getDay();
    if (dow === 0) continue;
    const [from, to] = dow === 6 ? [10, 13] : [9, 19];
    for (let h = from; h < to; h++) {
      const s = new Date(day); s.setHours(h, 0, 0, 0);
      const dayEnd = new Date(day); dayEnd.setHours(to, 0, 0, 0);
      if (s.getTime() >= now.getTime() + 30 * 6e4) slots.push({ s: s.getTime(), dayEnd: dayEnd.getTime() });
    }
  }
  for (const d of todo) {
    let left = Math.min(effortHours(d), 6); // at most 6 h planned per deadline this week
    const due = parse(d.due_date).getTime();
    for (const { s, dayEnd } of slots) {
      if (left <= 0) break;
      const len = Math.min(2, left);
      const e = s + len * 36e5;
      if (e > due || e > dayEnd || !isFree(s, e) || !taken.every(([ts, te]) => e <= ts || s >= te)) continue;
      // keep at least one block-free hour per day for breathing room: max 3 blocks per day
      const sameDayBlocks = blocks.filter((b) => startOfDay(b.start).getTime() === startOfDay(new Date(s)).getTime()).length;
      if (sameDayBlocks >= 3) continue;
      taken.push([s, e]);
      blocks.push({ id: `plan-${d.id}-${s}`, deadlineId: d.id, title: d.title, course_code: d.course_code, start: new Date(s), end: new Date(e) });
      left -= len;
    }
  }
  return blocks.sort((a, b) => a.start.getTime() - b.start.getTime());
}

/** Simple inline formatting for LLM answers: **bold**, line breaks and "- " bullets. Returns safe segments. */
export function answerLines(text: string): { bullet: boolean; parts: { bold: boolean; text: string }[] }[] {
  return text.split(/\n+/).filter((l) => l.trim()).map((line) => {
    const bullet = /^\s*[-*•]\s+/.test(line);
    const clean = line.replace(/^\s*[-*•]\s+/, "");
    const parts = clean.split(/(\*\*[^*]+\*\*)/).filter(Boolean).map((p) => (p.startsWith("**") && p.endsWith("**") ? { bold: true, text: p.slice(2, -2) } : { bold: false, text: p }));
    return { bullet, parts };
  });
}
