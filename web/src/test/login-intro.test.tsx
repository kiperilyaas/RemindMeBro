import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { INTRO_LANDSCAPE, INTRO_PORTRAIT, LoginIntro, pickIntro, wantsIntro } from "../components/LoginIntro";

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe("Login intro", () => {
  it("plays the intro video, muted and inline", () => {
    const { container } = render(<LoginIntro onDone={() => undefined} />);
    const video = container.querySelector("video");
    expect(video).not.toBeNull();
    expect([INTRO_PORTRAIT.src, INTRO_LANDSCAPE.src]).toContain(video?.getAttribute("src"));
    expect(video?.muted).toBe(true);
  });

  it("uses the 4:3 video on computers and the 9:16 one on phones", () => {
    expect(pickIntro(1440, 900).src).toBe(INTRO_LANDSCAPE.src);
    expect(pickIntro(390, 844).src).toBe(INTRO_PORTRAIT.src);
  });

  it("Skip closes the intro", () => {
    vi.useFakeTimers();
    const done = vi.fn();
    render(<LoginIntro onDone={done} />);
    fireEvent.click(screen.getByRole("button", { name: /skip intro/i }));
    act(() => { vi.advanceTimersByTime(400); });
    expect(done).toHaveBeenCalledTimes(1);
  });

  it("goes straight to the app when the video cannot start", () => {
    vi.useFakeTimers();
    const done = vi.fn();
    render(<LoginIntro onDone={done} />);
    act(() => { vi.advanceTimersByTime(2000); });
    expect(done).toHaveBeenCalledTimes(1);
  });

  it("is skipped with reduce motion on", () => {
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), media: q }));
    expect(wantsIntro()).toBe(false);
    vi.unstubAllGlobals();
  });
});
