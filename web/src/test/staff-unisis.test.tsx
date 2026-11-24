// The UniSIS staff app start empty and let staff create courses.
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type Route = (url: string, init?: RequestInit) => unknown;
const calls: { url: string; method: string; body: unknown }[] = [];
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });

function mockServer(route: Route) {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const out = route(url, init);
    return out instanceof Response ? out : json(out ?? {});
  }));
}

beforeEach(() => { calls.length = 0; document.body.innerHTML = '<div id="root"></div>'; location.hash = ""; vi.resetModules(); });
afterEach(() => { vi.unstubAllGlobals(); });

describe("UniSIS staff", () => {
  it("asks for a course before an exam, and creates a course with its timetable", async () => {
    const me = { id: 1, username: "registrar", fullname: "Student Office", role: "registrar", hub_url: "http://127.0.0.1:8000/", now: "2026-11-24T10:00" };
    mockServer((url, init) => {
      if (url.endsWith("/staff/api/session")) return { user: me };
      if (url.endsWith("/staff/api/demo-accounts")) return { password: "demo1234", accounts: [] };
      if (url.endsWith("/staff/api/overview")) return { stats: { students: 1, courses: 0, open_windows: 0, api_calls_24h: 0 }, exams: [],
        terms: [{ id: 1, name: "Winter term 2026/27", opens_at: null, closes_at: null, status: "closed", electives_required: 0 }], courses: [] };
      if (url.endsWith("/staff/api/terms")) return [{ id: 1, code: "W2026", name: "Winter term 2026/27", starts_on: "2026-09-21", ends_on: "2027-01-31" }];
      if (url.endsWith("/staff/api/courses") && init?.method === "POST") return json({ id: 5, code: "MICRO-2026", name: "Microeconomics", enrolled: 1, slots: [{}] }, 201);
      if (url.endsWith("/staff/api/courses")) return [];
      if (url.includes("/staff/api/courses/5")) return { id: 5, code: "MICRO-2026", name: "Microeconomics", term: "Winter term 2026/27", kind: "core", credits: 6, lecturer: "Prof. Marco Rossi",
        capacity: 100, enrolled: 1, waitlisted: 0, term_id: 1, year_of_study: 1, description: "", exams: 0,
        slots: [{ id: 1, weekday: 0, day: "Monday", start_time: "09:00", end_time: "11:00", room: "Room 3B", kind: "Lecture" }],
        students: [{ id: 2, name: "Giulia Esposito", student_number: "EF-2026-0142", status: "enrolled" }] };
      if (url.includes("/staff/api/students")) return [];
      return {};
    });
    await act(async () => { await import("../staff/unisis/main"); });
    expect(await screen.findByText("Exams belong to a course. Create a course first.")).toBeInTheDocument();
    expect(screen.getByText("Elective registration not scheduled")).toBeInTheDocument();
    expect(screen.queryByText("Try a case")).toBeNull();
    await act(async () => { fireEvent.click(screen.getByText("Go to Courses")); });
    expect(await screen.findByText("No courses yet. Create the first one above.")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("MICRO-2026"), { target: { value: "MICRO-2026" } });
    fireEvent.change(screen.getByPlaceholderText("Microeconomics"), { target: { value: "Microeconomics" } });
    fireEvent.change(screen.getByPlaceholderText("Prof. Marco Rossi"), { target: { value: "Prof. Marco Rossi" } });
    fireEvent.change(screen.getAllByPlaceholderText("Room")[0], { target: { value: "Room 3B" } });
    await waitFor(() => expect((screen.getByText("Winter term 2026/27") as HTMLOptionElement).selected).toBe(true));
    await act(async () => { fireEvent.click(screen.getByText("Create course")); });
    await waitFor(() => expect(calls.find((c) => c.method === "POST" && c.url.endsWith("/staff/api/courses"))?.body).toMatchObject({
      code: "MICRO-2026", term_id: 1, kind: "elective", slots: [{ weekday: 0, start_time: "09:00", end_time: "11:00", room: "Room 3B", kind: "Lecture" }] }));
    expect(await screen.findByText("Monday · 09:00–11:00")).toBeInTheDocument();
  });
});
