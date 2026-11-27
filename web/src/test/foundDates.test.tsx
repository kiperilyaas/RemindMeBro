import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { SessionProvider } from "../state/session";
import { StudentProvider } from "../state/student";
import { ToastProvider } from "../state/toast";
import { FoundDates } from "../views/student/FoundDates";

const json = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
const found = (id: number, title: string, extra = {}) => ({
  id, course_code: "3MA674", course_name: "International Management", kind: "exam", kind_label: "Final exam", title,
  date: "2026-12-16", time: null, room: null, year_written: false, quote: "13 16.12 FINAL EXAM Doc. Pichanič",
  filename: "IB-IM-674_Fall_2026.pdf", page: "Page 1", also_in: [], in_calendar: null, ...extra,
});

beforeEach(() => { api.setToken("t"); localStorage.setItem("rmb.user", JSON.stringify({ id: 1, email: "s@x", full_name: "Giulia", role: "student", created_at: "", plan: "free" })); });
afterEach(() => { vi.restoreAllMocks(); api.setToken(null); localStorage.clear(); });

describe("Exam dates in course files", () => {
  it("searches with the button, shows the sentence of the file, adds a date only when the student accepts it", async () => {
    let state = "idle";
    let pending = [found(1, "FINAL EXAM"), found(2, "Sem Paper Presentations", { kind: "presentation", kind_label: "Presentation", date: "2026-12-02", in_calendar: "Exam: Written exam" })];
    const calls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input), method = init?.method ?? "GET";
      if (url.includes("/found-dates")) calls.push(`${method} ${url.split("/api")[1]}`);
      if (url.endsWith("/health")) return json({ status: "ok", app: "x", version: "1", reference_date: "2026-11-27T12:00:00", ollama: {}, vector_documents: 0 });
      if (url.endsWith("/auth/me")) return json({ id: 1, email: "s@x", full_name: "Giulia", role: "student", created_at: "", plan: "free" });
      if (url.endsWith("/found-dates/scan")) { state = "done"; return json({ state: "running" }); }
      if (url.endsWith("/found-dates/1/accept")) return json({ accepted: true, deadline_id: 9 });
      if (url.endsWith("/found-dates/2/reject")) return json({ rejected: true });
      if (url.endsWith("/found-dates")) return json({ status: { state }, pending: state === "idle" ? [] : pending, accepted: 0 });
      return json([]);
    });
    render(<ToastProvider><SessionProvider><StudentProvider><FoundDates /></StudentProvider></SessionProvider></ToastProvider>);
    fireEvent.click(await screen.findByRole("button", { name: /Find exam dates/ }));
    expect(await screen.findByText("2 dates found in your course files", {}, { timeout: 4000 })).toBeInTheDocument();
    // the sentence of the file, the course by name, the missing year and time said plainly
    expect(screen.getAllByText("“13 16.12 FINAL EXAM Doc. Pichanič”")[0]).toBeInTheDocument();
    expect(screen.getAllByText("International Management")[0]).toBeInTheDocument();
    expect(screen.getAllByText(/time not stated/)[0]).toBeInTheDocument();
    expect(screen.getByText(/already has “Exam: Written exam”/)).toBeInTheDocument();
    expect(calls).not.toContain("POST /found-dates/1/accept");      // nothing reaches the calendar by itself
    fireEvent.click(screen.getAllByRole("button", { name: /Add to calendar/ })[0]);
    expect(await screen.findByText("Added to your calendar")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Not right" }));
    await waitFor(() => expect(calls).toContain("POST /found-dates/2/reject"));
    expect(calls).toContain("POST /found-dates/1/accept");
    pending = [];
  });
});
