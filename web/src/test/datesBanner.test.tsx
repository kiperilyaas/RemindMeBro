import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { FoundDatesProvider } from "../state/foundDates";
import { SessionProvider } from "../state/session";
import { StudentProvider, useStudent } from "../state/student";
import { ToastProvider } from "../state/toast";
import { Timeline } from "../views/student/Timeline";

const json = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
const dated = (id: number) => ({
  id, source: "email", course_id: 1, course_code: "2MO522", course_name: "Financial Strategies", author: "Prof. Laura Bianchi",
  created_at: "2026-11-28T10:00:00", subject: `Message ${id}`, content: "…", ai_summary: "…", important: true,
  deadline_id: 100 + id, deadline_due: "2026-12-15T23:59:00", deadline_title: `Date ${id}`, deadline_status: "pending",
});

let reloadNow: () => Promise<void> = async () => undefined;
function Grab() { reloadNow = useStudent().reload; return null; }

beforeEach(() => { api.setToken("t"); localStorage.setItem("rmb.user", JSON.stringify({ id: 1, email: "s@x", full_name: "Giulia", role: "student", created_at: "", plan: "free" })); });
afterEach(() => { vi.restoreAllMocks(); api.setToken(null); localStorage.clear(); });

describe("Timeline: notice of dates found in messages", () => {
  it("closes with the ×, stays closed for the same dates, comes back only for a new one", async () => {
    let inbox = [dated(1), dated(2)];
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/health")) return json({ status: "ok", app: "x", version: "1", reference_date: "2026-11-28T12:00:00", ollama: {}, vector_documents: 0 });
      if (url.endsWith("/auth/me")) return json({ id: 1, email: "s@x", full_name: "Giulia", role: "student", created_at: "", plan: "free" });
      if (url.endsWith("/inbox")) return json(inbox);
      if (url.endsWith("/found-dates")) return json({ status: { state: "idle" }, pending: [], accepted: 0 });
      return json([]);
    });
    const ui = () => <ToastProvider><SessionProvider><StudentProvider><FoundDatesProvider><Grab /><Timeline onNavigate={() => undefined} /></FoundDatesProvider></StudentProvider></SessionProvider></ToastProvider>;
    const { unmount } = render(ui());
    expect(await screen.findByText("2 new dates found in your messages.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close this notice" }));
    expect(screen.queryByText(/found in your messages/)).toBeNull();
    // opening the app again: still closed for the same two dates
    unmount();
    render(ui());
    await screen.findByText("Agenda");
    expect(screen.queryByText(/found in your messages/)).toBeNull();
    // the AI finds a new date: the notice comes back, counting only the new one
    inbox = [dated(3), ...inbox];
    await act(async () => { await reloadNow(); });
    expect(await screen.findByText("1 new date found in your messages.")).toBeInTheDocument();
  });
});
