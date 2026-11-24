import { useCallback, useEffect, useState } from "react";

/** Hash routing ("#connections?unisis=connected") — works when the page is served by FastAPI or opened as a file. */
export interface Route { path: string; params: URLSearchParams }
const read = (): Route => {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, query = ""] = raw.split("?");
  return { path: path || "", params: new URLSearchParams(query) };
};

export function useHashRoute(): [Route, (path: string) => void, () => void] {
  const [route, setRoute] = useState<Route>(read);
  useEffect(() => {
    const on = () => setRoute(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const navigate = useCallback((path: string) => {
    if (read().path === path && !location.hash.includes("?")) return;
    location.hash = path;
  }, []);
  /** Drops the query part (e.g. after handling an OAuth return) without adding a history entry. */
  const clearParams = useCallback(() => {
    const r = read();
    history.replaceState(null, "", `${location.pathname}${location.search}#${r.path}`);
    setRoute({ path: r.path, params: new URLSearchParams() });
  }, []);
  return [route, navigate, clearParams];
}
