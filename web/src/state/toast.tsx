import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

export interface Toast { id: number; title: string; body?: string; tone: "info" | "ok" | "error" }
type Push = (title: string, body?: string, tone?: Toast["tone"]) => void;
const ToastCtx = createContext<Push>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const seq = useRef(0);
  const timers = useRef(new Map<number, number>());
  const dismiss = useCallback((id: number) => {
    setToasts((t) => t.filter((x) => x.id !== id));
    const tm = timers.current.get(id);
    if (tm) { clearTimeout(tm); timers.current.delete(id); }
  }, []);
  const push = useCallback<Push>((title, body, tone = "info") => {
    const id = ++seq.current;
    setToasts((t) => [...t.slice(-2), { id, title, body, tone }]);
    timers.current.set(id, window.setTimeout(() => dismiss(id), tone === "error" ? 9000 : 6000));
  }, [dismiss]);
  useEffect(() => { const map = timers.current; return () => map.forEach((tm) => clearTimeout(tm)); }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast t-${t.tone}`}>
            <div><b>{t.title}</b>{t.body && <p>{t.body}</p>}</div>
            <button className="toast-x" onClick={() => dismiss(t.id)} aria-label="Dismiss notification">×</button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);
