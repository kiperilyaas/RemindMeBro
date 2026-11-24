import { useEffect, useRef, useState } from "react";

// The intro videos (frontend/brand, served by the hub at /media/...), 3 s, no audio: 9:16 for phones and
// portrait screens, 4:3 for computers. At WAVE_AT the bell lands on "bro" and sends out a ring; from that
// moment the intro opens with a circular hole that grows from the bell, so the app underneath appears inside the wave.
export const INTRO_PORTRAIT = { src: "/media/intro.mp4", w: 1080, h: 1920, bell: { x: 0.749, y: 0.53 } };
export const INTRO_LANDSCAPE = { src: "/media/intro-4x3.mp4", w: 1440, h: 1080, bell: { x: 0.699, y: 0.557 } };
type IntroClip = typeof INTRO_PORTRAIT;
const WAVE_AT = 1.6;                  // seconds into the video, same in both
const OPEN_MS = 900;                  // how long the hole takes to cover the screen
const START_TIMEOUT_MS = 1500;        // video not playing by then → skip the intro

export function pickIntro(width: number, height: number): IntroClip {
  return width > height ? INTRO_LANDSCAPE : INTRO_PORTRAIT;
}

/** Plays only where it makes sense: not with "reduce motion" on, not in tests. */
export function wantsIntro(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Where the bell sits on screen, with the video drawn like object-fit: cover. */
function bellOnScreen(clip: IntroClip, w: number, h: number) {
  const scale = Math.max(w / clip.w, h / clip.h);
  const offX = (w - clip.w * scale) / 2, offY = (h - clip.h * scale) / 2;
  return { x: offX + clip.bell.x * clip.w * scale, y: offY + clip.bell.y * clip.h * scale };
}

const easeOut = (t: number) => 1 - Math.pow(1 - t, 3);

export function LoginIntro({ onDone }: { onDone: () => void }) {
  const rootRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const ringRef = useRef<HTMLDivElement>(null);
  const [leaving, setLeaving] = useState(false);
  const [clip] = useState(() => pickIntro(window.innerWidth, window.innerHeight));
  const doneRef = useRef(onDone);
  doneRef.current = onDone;

  useEffect(() => {
    const root = rootRef.current, video = videoRef.current, ring = ringRef.current;
    if (!root || !video || !ring) return;
    let raf = 0, openStart = 0, finished = false;

    const finish = () => { if (!finished) { finished = true; cancelAnimationFrame(raf); doneRef.current(); } };
    const fadeOut = () => { if (finished) return; cancelAnimationFrame(raf); setLeaving(true); window.setTimeout(finish, 300); };

    const setHole = (r: number) => {
      const { x, y } = bellOnScreen(clip, root.clientWidth, root.clientHeight);
      const mask = `radial-gradient(circle at ${x}px ${y}px, transparent ${r}px, #000 ${r + 1.5}px)`;
      root.style.setProperty("mask-image", mask);
      root.style.setProperty("-webkit-mask-image", mask);
      ring.style.transform = `translate(${x - r}px, ${y - r}px)`;
      ring.style.width = ring.style.height = `${2 * r}px`;
    };

    const tick = (now: number) => {
      if (!openStart && video.currentTime >= WAVE_AT) openStart = now;
      if (openStart) {
        const w = root.clientWidth, h = root.clientHeight;
        const { x, y } = bellOnScreen(clip, w, h);
        const far = Math.hypot(Math.max(x, w - x), Math.max(y, h - y)) + 40;
        const p = Math.min(1, (now - openStart) / OPEN_MS);
        setHole(easeOut(p) * far);
        ring.style.opacity = String(1 - p * 0.85);
        if (p >= 1) { finish(); return; }
      }
      raf = requestAnimationFrame(tick);
    };

    // muted + playsInline is what lets browsers start a video without a click
    video.muted = true;
    video.defaultMuted = true;
    const noStart = window.setTimeout(() => { if (video.currentTime === 0) fadeOut(); }, START_TIMEOUT_MS);
    const onPlaying = () => { window.clearTimeout(noStart); raf = requestAnimationFrame(tick); };
    video.addEventListener("playing", onPlaying, { once: true });
    video.addEventListener("error", fadeOut);
    video.addEventListener("ended", () => { if (!openStart) fadeOut(); });
    const p = video.play();
    if (p && typeof p.catch === "function") p.catch(fadeOut);

    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") fadeOut(); };
    window.addEventListener("keydown", onKey);
    return () => {
      finished = true;
      cancelAnimationFrame(raf);
      window.clearTimeout(noStart);
      window.removeEventListener("keydown", onKey);
      video.removeEventListener("error", fadeOut);
    };
  }, [clip]);

  return (
    <div className={`intro ${leaving ? "leaving" : ""}`}>
      <div ref={rootRef} className="intro-stage" aria-hidden="true">
        <video ref={videoRef} className="intro-video" src={clip.src} muted playsInline autoPlay preload="auto" />
      </div>
      <div ref={ringRef} className="intro-ring" aria-hidden="true" />
      <button className="intro-skip" onClick={() => { setLeaving(true); window.setTimeout(() => doneRef.current(), 300); }} aria-label="Skip intro">Skip</button>
    </div>
  );
}
