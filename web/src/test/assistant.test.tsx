import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Assistant } from "../components/Assistant";
import { SessionProvider } from "../state/session";

afterEach(() => vi.restoreAllMocks());
const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));

describe("Ask Bro", () => {
  it("sends a suggested question and renders the answer with bold text", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/health")) return json({ status: "ok", app: "x", version: "1", reference_date: "2026-10-20T09:30:00", ollama: { model: "llama3.2", model_available: true }, vector_documents: 3 });
      if (url.endsWith("/demo-accounts")) return json({ password: null, accounts: [] });
      if (url.endsWith("/chat")) return json({ question: "q", answer: "Due **Friday 30 October**.", sources: [] });
      return json({}, 404);
    });
    render(<SessionProvider><Assistant open onClose={() => undefined} /></SessionProvider>);
    const suggestion = await screen.findByRole("button", { name: /submit this week/i });
    suggestion.click();
    await waitFor(() => expect(screen.getByText("Friday 30 October").tagName).toBe("B"));
    expect(screen.getByText("What do I have to submit this week?")).toBeInTheDocument();
  });
});
