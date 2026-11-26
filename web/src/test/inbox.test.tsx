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

  it("adds a Teams message: only the student sees it, the AI date is shown, and it can be deleted", async () => {
    let inbox: Record<string, unknown>[] = [];
    const posted: unknown[] = [];
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/health")) return json({ status: "ok", app: "x", version: "1", reference_date: "2026-11-25T12:00:00", ollama: { model: "llama3.2", model_available: true }, vector_documents: 0 });
      if (url.endsWith("/demo-accounts")) return json({ password: null, accounts: [] });
      if (url.endsWith("/auth/me")) return json({ id: 1, email: "s@x", full_name: "Giulia", role: "student", created_at: "", plan: "premium" });
      if (url.endsWith("/courses")) return json([{ id: 1, code: "3SG712", name: "Growth strategies", professor: "Prof. Marco Rossi" }]);
      if (url.endsWith("/inbox/messages") && init?.method === "POST") {
        posted.push(JSON.parse(String(init.body)));
        const item = { ...msg(3, "Essay due Friday"), id: 30, source: "teams", author: "Marco Rossi", personal: true, deadline_id: 7, deadline_due: "2026-12-04T23:59:00",
          ai_summary: "AI-detected deadline: Essay — Fri 4 Dec, 23:59." };
        inbox = [item];
        return json({ item, ai_status: "deadline_extracted", ai_error: null });
      }
      if (url.endsWith("/inbox/messages/30") && init?.method === "DELETE") { inbox = []; return json({ deleted: true }); }
      if (url.endsWith("/inbox")) return json(inbox);
      return json([]);
    });
    render(<ToastProvider><SessionProvider><StudentProvider><Inbox /></StudentProvider></SessionProvider></ToastProvider>);
    fireEvent.click(await screen.findByRole("button", { name: /Add message/ }));
    fireEvent.click(screen.getByRole("radio", { name: "Teams" }));
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "Marco Rossi" } });
    fireEvent.change(screen.getByLabelText("Course"), { target: { value: "3SG712" } });
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Essay due Friday at 23:59" } });
    fireEvent.click(screen.getByRole("button", { name: "Add to Inbox" }));
    expect(await screen.findByText(/The AI found a date/)).toBeInTheDocument();
    expect(posted[0]).toMatchObject({ source: "teams", author: "Marco Rossi", course_code: "3SG712", content: "Essay due Friday at 23:59" });
    // the new message opens, says only the student sees it, and can be deleted
    expect(screen.getByText(/only you see it/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(await screen.findByText("Message deleted")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("Essay due Friday", { selector: ".msub" })).toBeNull());
  });
});
