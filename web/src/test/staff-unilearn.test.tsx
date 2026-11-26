// The UniLearn staff app start empty and let staff create courses.
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

describe("UniLearn staff", () => {
  it("shows an empty course list, no 'Try a case', and creates a course", async () => {
    const me = { id: 2, username: "marco.rossi", fullname: "Marco Rossi", role: "teacher", hub_url: "http://127.0.0.1:8000/", now: "2026-11-24T10:00" };
    mockServer((url, init) => {
      if (url.endsWith("/staff/api/session")) return { user: me };
      if (url.endsWith("/staff/api/demo-accounts")) return { password: "demo1234", accounts: [] };
      if (url.endsWith("/staff/api/courses") && init?.method === "POST")
        return json({ id: 1, shortname: "MICRO-2026", fullname: "Microeconomics", teachers: ["Marco Rossi"], students: 1, assignments: 0, announcements: 0, next_due: null }, 201);
      if (url.endsWith("/staff/api/courses")) return [];
      if (url.includes("/staff/api/courses/1")) return { id: 1, shortname: "MICRO-2026", fullname: "Microeconomics", teachers: ["Marco Rossi"], students: 1, assignments: 0,
        announcements: 0, next_due: null, assignment_list: [], announcement_list: [], events: [], student_list: [{ id: 7, fullname: "Giulia Esposito", username: "giulia.esposito" }], can_delete: true };
      if (url.endsWith("/staff/api/people")) return { students: [{ id: 7, fullname: "Giulia Esposito", username: "giulia.esposito" }], teachers: [] };
      return {};
    });
    await act(async () => { await import("../staff/unilearn/main"); });
    expect(await screen.findByText("No courses yet. Create the first one above.")).toBeInTheDocument();
    expect(screen.queryByText("Try a case")).toBeNull();
    fireEvent.change(screen.getByPlaceholderText("MICRO-2026"), { target: { value: "micro-2026" } });
    fireEvent.change(screen.getByPlaceholderText("Microeconomics"), { target: { value: "Microeconomics" } });
    await act(async () => { fireEvent.click(screen.getByText("Create course")); });
    await waitFor(() => expect(calls.find((c) => c.method === "POST" && c.url.endsWith("/staff/api/courses"))?.body)
      .toMatchObject({ shortname: "micro-2026", fullname: "Microeconomics", enrol_all_students: false, teacher_id: null }));
    expect(await screen.findByText("Add a calendar event")).toBeInTheDocument();
    expect(screen.getByText("Giulia Esposito")).toBeInTheDocument();
  });

  it("on this computer the staff accounts sign in with one click", async () => {
    const me = { id: 2, username: "marco.rossi", fullname: "Marco Rossi", role: "teacher", hub_url: "http://127.0.0.1:8000/", now: "2026-11-24T10:00" };
    let signedIn = false;
    mockServer((url, init) => {
      if (url.endsWith("/staff/api/session")) return { user: null };
      if (url.endsWith("/staff/api/demo-accounts")) return { password: null, local: true, accounts: [{ id: 2, username: "marco.rossi", fullname: "Marco Rossi", role: "teacher" }] };
      if (url.endsWith("/staff/api/quick-login") && init?.method === "POST") { signedIn = true; return me; }
      if (url.endsWith("/staff/api/me")) return signedIn ? me : json({ detail: "no" }, 401);
      if (url.endsWith("/staff/api/courses")) return [];
      return {};
    });
    await act(async () => { await import("../staff/unilearn/main"); });
    expect(await screen.findByText(/Quick sign-in · only on this computer/)).toBeInTheDocument();
    await act(async () => { fireEvent.click(screen.getByText("Marco Rossi")); });
    await waitFor(() => expect(calls.find((c) => c.url.endsWith("/staff/api/quick-login"))?.body).toEqual({ uid: 2 }));
    expect(await screen.findByText("No courses yet. Create the first one above.")).toBeInTheDocument();
  });
});
