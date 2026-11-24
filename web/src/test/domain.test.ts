import { describe, expect, it } from "vitest";
import type { Deadline, ScheduleEvent } from "../api/types";
import { answerLines, courseColor, effortHours, kindOf, planWeek, shortCode, urgency } from "../lib/domain";
import { daysBetween, relative } from "../lib/time";

const NOW = new Date("2026-10-20T09:30:00");
const dl = (p: Partial<Deadline>): Deadline => ({
  id: 1, course_id: 1, course_name: "Microeconomics", course_code: "MICRO-2026", title: "Problem Set 2", description: null,
  due_date: "2026-10-30T23:59:00", source: "moodle", is_completed: false, extracted_by_ai: false, announcement_id: null,
  superseded_by_id: null, source_message: null, replaces: null, ...p,
});
const ev = (start: string, end: string): ScheduleEvent => ({ id: 1, course_id: 1, course_code: "MICRO-2026", course_name: "Micro", title: "Micro", start_time: start, end_time: end, location: null, source: "unisis", kind: "class" });

describe("dates", () => {
  it("counts calendar days across the DST change (25 Oct 2026)", () => {
    expect(daysBetween(NOW, new Date("2026-10-30T23:59:00"))).toBe(10);
  });
  it("formats relative due dates", () => {
    expect(relative(new Date("2026-10-20T23:59:00"), NOW)).toBe("today 23:59");
    expect(relative(new Date("2026-10-21T09:00:00"), NOW)).toBe("tomorrow 09:00");
    expect(relative(new Date("2026-10-23T12:00:00"), NOW)).toBe("in 3 days");
    expect(relative(new Date("2026-10-18T12:00:00"), NOW)).toBe("2 days ago");
  });
});

describe("domain rules", () => {
  it("classifies deadlines", () => {
    expect(kindOf(dl({ title: "Midterm test", source: "unisis" }))).toBe("exam");
    expect(kindOf(dl({ title: "Register for 5 exams (winter session)", source: "unisis" }))).toBe("registration");
    expect(kindOf(dl({ title: "Excel lab: NPV and IRR" }))).toBe("assignment");
  });
  it("estimates effort and urgency", () => {
    expect(effortHours(dl({ title: "Group project: bank risk analysis" }))).toBe(8);
    expect(effortHours(dl({ title: "Choose 2 electives", source: "unisis" }))).toBe(0);
    expect(urgency(new Date("2026-10-22T10:00:00"), NOW)).toBe("now");
    expect(urgency(new Date("2026-10-30T10:00:00"), NOW)).toBe("soon");
    expect(urgency(new Date("2026-11-30T10:00:00"), NOW)).toBe("later");
  });
  it("gives stable course colours and short codes", () => {
    expect(courseColor("MICRO-2026")).toBe("#3E6FD8");
    expect(courseColor("NEW-2026")).toBe(courseColor("NEW-2026"));
    expect(shortCode("CORPFIN-2026")).toBe("CORPFIN");
  });
  it("parses bold and bullets from LLM answers", () => {
    const lines = answerLines("Your week:\n- **Problem Set 2**: Friday");
    expect(lines).toHaveLength(2);
    expect(lines[1].bullet).toBe(true);
    expect(lines[1].parts[0]).toEqual({ bold: true, text: "Problem Set 2" });
  });
});

describe("planWeek", () => {
  const classes = [ev("2026-10-20T11:30:00", "2026-10-20T13:30:00"), ev("2026-10-21T09:00:00", "2026-10-21T11:00:00")];
  const blocks = planWeek([dl({ id: 1, due_date: "2026-10-23T23:59:00" }), dl({ id: 2, title: "Group project", due_date: "2026-11-28T18:00:00" })], classes, NOW);

  it("never overlaps classes or other blocks", () => {
    const spans = blocks.map((b) => [b.start.getTime(), b.end.getTime()]);
    for (const [s, e] of spans) {
      for (const c of classes) expect(e <= new Date(c.start_time).getTime() || s >= new Date(c.end_time).getTime()).toBe(true);
    }
    const sorted = [...spans].sort((a, b) => a[0] - b[0]);
    for (let i = 1; i < sorted.length; i++) expect(sorted[i][0]).toBeGreaterThanOrEqual(sorted[i - 1][1]);
  });
  it("plans the earliest deadline first, before it is due, and skips Sundays", () => {
    expect(blocks[0].deadlineId).toBe(1);
    blocks.filter((b) => b.deadlineId === 1).forEach((b) => expect(b.end.getTime()).toBeLessThanOrEqual(new Date("2026-10-23T23:59:00").getTime()));
    blocks.forEach((b) => expect(b.start.getDay()).not.toBe(0));
    expect(blocks.filter((b) => b.deadlineId === 1).reduce((a, b) => a + (b.end.getTime() - b.start.getTime()) / 36e5, 0)).toBe(4);
  });
  it("ignores completed deadlines and registrations", () => {
    expect(planWeek([dl({ is_completed: true }), dl({ id: 3, title: "Register for exams", source: "unisis" })], [], NOW)).toHaveLength(0);
  });
});

describe("planWeek working hours", () => {
  it("keeps every block inside 09:00–19:00 (10:00–13:00 on Saturday)", () => {
    const blocks = planWeek([{ ...({} as Deadline), id: 9, title: "Group project", source: "moodle", extracted_by_ai: false, is_completed: false, due_date: "2026-11-28T18:00:00", course_code: null }], [], new Date("2026-10-20T09:30:00"));
    for (const b of blocks) {
      const sat = b.start.getDay() === 6;
      expect(b.start.getHours()).toBeGreaterThanOrEqual(sat ? 10 : 9);
      expect(b.end.getHours() + b.end.getMinutes() / 60).toBeLessThanOrEqual(sat ? 13 : 19);
    }
  });
});
