import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Deadline, ScheduleEvent } from "../api/types";
import { buildItems, byDay, Calendar, countLabel } from "../views/student/Calendar";

const NOW = new Date(2026, 10, 24, 10, 12); // Tue 24 Nov 2026
const ev = (id: number, start: string, end: string, code: string, kind = "class", title = "Lecture"): ScheduleEvent => ({
  id, course_id: 1, course_code: code, course_name: `Course ${code}`, title, start_time: start, end_time: end, location: "SB 410", source: "unisis", kind,
});
const dl = (id: number, due: string, code: string): Deadline => ({
  id, course_id: 1, course_name: `Course ${code}`, course_code: code, title: `Task ${id}`, description: null, due_date: due, source: "moodle",
  is_completed: false, extracted_by_ai: false, announcement_id: null, superseded_by_id: null, source_message: null, replaces: null,
});
const events = [
  ev(1, "2026-11-24T09:00:00", "2026-11-24T11:00:00", "2MO522"),
  ev(2, "2026-11-24T14:00:00", "2026-11-24T15:30:00", "3SG712", "class", "Seminar"),
  ev(3, "2026-11-26T09:00:00", "2026-11-26T10:30:00", "2IB468"),
  ev(4, "2026-12-11T09:00:00", "2026-12-11T11:00:00", "2MO522", "exam", "Written exam"),
];

describe("calendar data", () => {
  it("groups by day, filters by course and counts", () => {
    const all = buildItems(events, [dl(9, "2026-11-25T12:00:00", "2IB468")], [], null);
    const days = byDay(all);
    expect(days.get("2026-11-24")?.length).toBe(2);
    expect(countLabel(days.get("2026-11-24") ?? [])).toBe("2 classes");
    expect(countLabel(days.get("2026-12-11") ?? [])).toBe("1 exam");
    expect(countLabel([])).toBe("free");
    expect(buildItems(events, [], [], "2IB468").map((i) => i.key)).toEqual(["e3"]);
  });
});

describe("calendar views", () => {
  const items = buildItems(events, [], [], null);
  const noop = () => undefined;
  it("agenda: today with the now line, then the next days with something on", () => {
    render(<Calendar view="agenda" items={items} now={NOW} weekOff={0} setWeekOff={noop} monthOff={0} setMonthOff={noop} selected={NOW} setSelected={noop} />);
    expect(screen.getByRole("heading", { name: /^Today/ })).toBeInTheDocument();
    expect(screen.getByLabelText("Now, 10:12")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Thu 26 Nov/ })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /Wed 25 Nov/ })).toBeNull();   // empty days are skipped
  });
  it("week: seven days with the ISO week number", () => {
    render(<Calendar view="week" items={items} now={NOW} weekOff={0} setWeekOff={noop} monthOff={0} setMonthOff={noop} selected={NOW} setSelected={noop} />);
    expect(screen.getByText(/Week 48 · 23 Nov – 29 Nov/)).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 2 })).toHaveLength(7);
  });
  it("month: a 6-week grid; picking a day shows it", () => {
    let picked: Date | null = null;
    render(<Calendar view="month" items={items} now={NOW} weekOff={0} setWeekOff={noop} monthOff={1} setMonthOff={noop} selected={new Date(2026, 11, 11)} setSelected={(d) => { picked = d; }} />);
    expect(screen.getByText("December 2026")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /: / })).toHaveLength(42);
    expect(screen.getByRole("heading", { name: /Friday 11 December/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Thursday 24 December/ }));
    expect(picked).not.toBeNull();
  });
});
