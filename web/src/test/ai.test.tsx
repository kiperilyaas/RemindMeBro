import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { Markdown } from "../lib/markdown";
import { SessionProvider } from "../state/session";
import { ToastProvider } from "../state/toast";
import { AI } from "../views/student/AI";

const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
const health = { status: "ok", app: "x", version: "1", reference_date: "2026-11-25T09:30:00", ollama: { model: "llama3.2", model_available: true }, vector_documents: 3 };
const billing = (plan: string) => ({ plan, price: "79", currency: "CZK", period: "month", features: ["Ask Bro", "Smart Notes"], since: null, simulated: true });
const user = (plan: string) => ({ id: 1, email: "student@demo.it", full_name: "Giulia Esposito", role: "student", created_at: "2026-11-01T00:00:00", plan });
const row = (id: number, lesson: string, status: string) => ({
  id, course_code: "2PR515", course_name: "Corporate Governance", lesson, position: id, status, error: null, title: "", summary: status === "ready" ? "Who controls a company." : "",
  edited: false, new_material: false, updated_at: null, generated_at: "2026-11-25T09:00:00", sources: [{ id: 7, filename: "l1.pptx", kind: "slides", size: 10 }, { id: 8, filename: "rec.mp3", kind: "audio", size: 10 }],
});
const route = (q = "") => ({ path: "ai", params: new URLSearchParams(q) });

beforeEach(() => { api.setToken("t"); });
afterEach(() => { vi.restoreAllMocks(); api.setToken(null); localStorage.clear(); });

function mount(plan: string, q = "", extra: (url: string, init?: RequestInit) => Promise<Response> | null = () => null) {
  let current = plan;
  const calls: { url: string; method: string; body?: string }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    calls.push({ url, method: init?.method ?? "GET", body: init?.body as string | undefined });
    const e = extra(url, init);
    if (e) return e;
    if (url.endsWith("/health")) return json(health);
    if (url.endsWith("/demo-accounts")) return json({ password: null, accounts: [] });
    if (url.endsWith("/auth/me")) return json(user(current));
    if (url.endsWith("/billing/plan")) { current = JSON.parse(String(init?.body)).plan; return json(billing(current)); }
    if (url.endsWith("/billing")) return json(billing(current));
    return json({ detail: "not found" }, 404);
  });
  const navigate = vi.fn();
  render(<ToastProvider><SessionProvider><AI route={route(q)} navigate={navigate} /></SessionProvider></ToastProvider>);
  return { calls, navigate };
}

describe("AI section", () => {
  it("Free: shows the plan with the price and activates Premium through the checkout", async () => {
    const { calls } = mount("free");
    const cta = await screen.findByRole("button", { name: /Get Premium · 79 CZK \/ month/ });
    fireEvent.click(cta);
    const dialog = await screen.findByRole("dialog", { name: "Checkout" });
    expect(dialog).toHaveTextContent("nothing is charged");
    fireEvent.click(screen.getByRole("button", { name: "Pay 79 CZK" }));
    await waitFor(() => expect(screen.getByRole("tab", { name: /Smart Notes/ })).toBeInTheDocument(), { timeout: 3000 });
    expect(calls.find((c) => c.url.endsWith("/billing/plan"))?.body).toBe(JSON.stringify({ plan: "premium" }));
  });

  it("Premium: Smart Notes lists lessons with their status and opens a ready one", async () => {
    const list = { connected: true, transcription: true, courses: [{ code: "2PR515", name: "Corporate Governance", lessons: [row(1, "Lesson 1", "ready"), row(2, "Lesson 2", "processing")] }] };
    const { navigate } = mount("premium", "tab=notes", (url) => (url.endsWith("/notes/sync") ? json({ ...list, lessons: 2, files: 2, queued: 0 }) : url.endsWith("/notes") ? json(list) : null));
    expect(await screen.findByRole("button", { name: "Lesson 2, AI processing…" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Lesson 1, Ready" }));
    expect(navigate).toHaveBeenCalledWith("ai?tab=notes&note=1");
  });

  it("Premium: a note is shown as formatted text and can be edited", async () => {
    const note = { ...row(1, "Lesson 1", "ready"), body_md: "# Governance\n\n## Key points\n\n- Boards **monitor** managers\n", key_points: [], definitions: [] };
    const { calls } = mount("premium", "tab=notes&note=1", (url, init) => {
      if (url.endsWith("/notes/1") && init?.method === "PUT") return json({ ...note, body_md: JSON.parse(String(init.body)).body_md, edited: true });
      if (url.endsWith("/notes/1")) return json(note);
      if (url.endsWith("/notes/sync")) return json({ connected: true, transcription: true, courses: [], lessons: 0, files: 0, queued: 0 });
      return null;
    });
    expect(await screen.findByRole("heading", { name: "Governance" })).toBeInTheDocument();
    expect(screen.getByText("monitor").tagName).toBe("B");
    fireEvent.click(screen.getByRole("button", { name: /Edit/ }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "# Mine" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("heading", { name: "Mine" })).toBeInTheDocument();
    expect(calls.some((c) => c.method === "PUT" && c.body === JSON.stringify({ body_md: "# Mine" }))).toBe(true);
  });
});

describe("Ask the material", () => {
  it("asks only about the chosen file and shows the cited excerpts", async () => {
    const note = { ...row(1, "Lesson 1", "ready"), body_md: "# Governance\n", key_points: [], definitions: [] };
    const { calls } = mount("premium", "tab=notes&note=1", (url) => {
      if (url.endsWith("/notes/1/chat")) return json({ answer: "The board **monitors** managers [1].", scope: "rec.mp3", skipped: [],
        sources: [{ n: 1, filename: "rec.mp3", kind: "audio", label: "1:02", excerpt: "The board monitors managers." }] });
      if (url.endsWith("/notes/1")) return json(note);
      if (url.endsWith("/notes/sync")) return json({ connected: true, transcription: true, courses: [], lessons: 0, files: 0, queued: 0 });
      return null;
    });
    fireEvent.click(await screen.findByRole("tab", { name: /Ask the material/ }));
    fireEvent.change(screen.getByLabelText("Ask about"), { target: { value: "8" } });
    expect(screen.getByText(/Answers use only rec\.mp3/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Question about the material"), { target: { value: "Who monitors managers?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send question" }));
    expect(await screen.findByLabelText("source 1")).toBeInTheDocument();
    expect(screen.getByText(/1 source: rec\.mp3 · 1:02/)).toBeInTheDocument();
    const sent = JSON.parse(calls.find((c) => c.url.endsWith("/notes/1/chat"))!.body!);
    expect(sent).toEqual({ question: "Who monitors managers?", source_id: 8, history: [] });
  });
});

describe("Markdown", () => {
  it("renders headings, lists and inline styles without HTML injection", () => {
    render(<Markdown text={"# T\n\nText with *note* and <b>x</b>\n\n1. one\n2. two\n- a"} />);
    expect(screen.getByRole("heading", { name: "T" })).toBeInTheDocument();
    expect(screen.getByText("note").tagName).toBe("EM");
    expect(screen.getByText(/<b>x<\/b>/)).toBeInTheDocument();
    expect(screen.getAllByRole("list")).toHaveLength(2);
  });
});
