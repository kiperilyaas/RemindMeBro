import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { SessionProvider } from "../state/session";
import { StudentProvider } from "../state/student";
import { ToastProvider } from "../state/toast";
import { Inbox } from "../views/student/Inbox";

const json = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
const msg = (id: number, subject: string, important = false) => ({
  id, source: "moodle", course_id: 1, course_code: "3SG712", course_name: "Growth strategies", author: "Marco Rossi",
  created_at: `2026-11-25T1${id}:00:00`, subject, content: subject, ai_summary: "Informational message.", important, deadline_id: null, deadline_due: null,
});

beforeEach(() => { document.title = "Remind Me Bro"; api.setToken("t"); localStorage.setItem("rmb.user", JSON.stringify({ id: 1, email: "s@x", full_name: "Giulia", role: "student", created_at: "", plan: "premium" })); });
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); api.setToken(null); localStorage.clear(); });

describe("Inbox: new messages", () => {
  it("says when unread messages are hidden by the filter, and marks messages that arrive live as New", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let inbox = [msg(1, "workhome")];
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/health")) return json({ status: "ok", app: "x", version: "1", reference_date: "2026-11-25T12:00:00", ollama: { model: "llama3.2", model_available: true }, vector_documents: 0 });
      if (url.endsWith("/demo-accounts")) return json({ password: null, accounts: [] });
      if (url.endsWith("/auth/me")) return json({ id: 1, email: "s@x", full_name: "Giulia", role: "student", created_at: "", plan: "premium" });
      if (url.endsWith("/inbox")) return json(inbox);
      return json([]);
    });
    render(<ToastProvider><SessionProvider><StudentProvider><Inbox /></StudentProvider></SessionProvider></ToastProvider>);
    // (the Inbox mounts while the data is loading, so it starts on Important here)
    // a plain announcement is not "Important": the banner says so and Show all reveals it
    expect(await screen.findByText(/1 not shown in Important/)).toBeInTheDocument();
    await waitFor(() => expect(document.title).toMatch(/^\(1\) /));
    fireEvent.click(screen.getByRole("button", { name: "Show all" }));
    expect(screen.getByText("workhome", { selector: ".msub" })).toBeInTheDocument();
    // the course is shown by name, the code stays in the tooltip
    expect(screen.getByText("Growth strategies", { selector: ".cchip-n" }).closest(".cchip")).toHaveAttribute("title", "3SG712");
    expect(screen.queryByText("3SG712")).toBeNull();
    // a lecturer posts: the next check (30 s) brings it in, marked New, with a notification
    inbox = [msg(2, "Room change"), ...inbox];
    await act(async () => { await vi.advanceTimersByTimeAsync(31000); });
    expect(await screen.findByText("1 new message just arrived")).toBeInTheDocument();
    expect(screen.getByText("New")).toBeInTheDocument();
    expect(screen.getByText(/New message in your Inbox/)).toBeInTheDocument();
    await waitFor(() => expect(document.title).toMatch(/^\(2\) /));
  });
});
