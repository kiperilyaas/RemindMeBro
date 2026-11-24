// Date helpers. The backend sends naive ISO strings in the demo's local time.
export const parse = (s: string) => new Date(s);
export const startOfDay = (x: Date) => { const y = new Date(x); y.setHours(0, 0, 0, 0); return y; };
export const addDays = (x: Date, n: number) => { const y = new Date(x); y.setDate(y.getDate() + n); return y; };
/** Calendar days between two dates (DST-safe thanks to rounding). */
export const daysBetween = (from: Date, to: Date) => Math.round((startOfDay(to).getTime() - startOfDay(from).getTime()) / 864e5);
export const sameDay = (a: Date, b: Date) => startOfDay(a).getTime() === startOfDay(b).getTime();
export const isoDate = (x: Date) => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}-${String(x.getDate()).padStart(2, "0")}`;
/** Local "YYYY-MM-DDTHH:MM" for <input type="datetime-local"> and for the API. */
export const isoLocal = (x: Date) => `${isoDate(x)}T${String(x.getHours()).padStart(2, "0")}:${String(x.getMinutes()).padStart(2, "0")}`;
export const mondayOf = (x: Date) => { const y = startOfDay(x); y.setDate(y.getDate() - ((y.getDay() + 6) % 7)); return y; };

const L = "en-GB";
export const fmtTime = (x: Date) => x.toLocaleTimeString(L, { hour: "2-digit", minute: "2-digit" });
export const fmtDay = (x: Date) => x.toLocaleDateString(L, { weekday: "short", day: "numeric", month: "short" });
export const fmtLong = (x: Date) => x.toLocaleDateString(L, { weekday: "long", day: "numeric", month: "long" });
export const fmtDayMonth = (x: Date) => x.toLocaleDateString(L, { day: "numeric", month: "long" });
export const weekdayShort = (x: Date) => x.toLocaleDateString(L, { weekday: "short" });
export const weekdayLong = (x: Date) => x.toLocaleDateString(L, { weekday: "long" });
export const monthShort = (x: Date) => x.toLocaleDateString(L, { month: "short" });

/** "today 23:59", "tomorrow", "in 3 days", "Fri 30 Oct", "2 days ago". */
export function relative(due: Date, now: Date): string {
  const n = daysBetween(now, due);
  if (n < -1) return `${-n} days ago`;
  if (n === -1) return "yesterday";
  if (n === 0) return `today ${fmtTime(due)}`;
  if (n === 1) return `tomorrow ${fmtTime(due)}`;
  if (n < 7) return `in ${n} days`;
  return fmtDay(due);
}

export function timeAgo(at: Date, now: Date): string {
  const min = Math.round((now.getTime() - at.getTime()) / 6e4);
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  const h = Math.round(min / 60);
  if (h < 24) return `${h} h ago`;
  const d = daysBetween(at, now);
  return d === 1 ? "yesterday" : d < 7 ? `${d} days ago` : fmtDay(at);
}

export const greeting = (now: Date) => (now.getHours() < 12 ? "Good morning" : now.getHours() < 18 ? "Good afternoon" : "Good evening");
