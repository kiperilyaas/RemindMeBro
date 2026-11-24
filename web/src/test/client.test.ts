import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClient, ApiError } from "../api/client";

const reply = (status: number, body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
afterEach(() => vi.restoreAllMocks());

describe("ApiClient", () => {
  it("sends the bearer token", async () => {
    const f = vi.spyOn(globalThis, "fetch").mockImplementation(() => reply(200, []));
    const c = new ApiClient(); c.token = "abc";
    await c.deadlines();
    expect((f.mock.calls[0][1]?.headers as Record<string, string>).Authorization).toBe("Bearer abc");
  });
  it("turns FastAPI errors into readable messages and reports 401", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => reply(401, { detail: "Invalid or expired token." }));
    const c = new ApiClient(); c.token = "abc";
    const onUnauthorized = vi.fn();
    c.listener = { onUnauthorized };
    await expect(c.me()).rejects.toThrow("Invalid or expired token.");
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });
  it("joins validation errors", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => reply(422, { detail: [{ loc: ["body", "password"], msg: "too short" }] }));
    await expect(new ApiClient().login("a@b.c", "x")).rejects.toThrow("password: too short");
  });
  it("flags network failures as offline", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => Promise.reject(new TypeError("Failed to fetch")));
    const c = new ApiClient();
    const onOffline = vi.fn();
    c.listener = { onOffline };
    const err = await c.health().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).offline).toBe(true);
    expect(onOffline).toHaveBeenCalledWith(true);
  });
});
