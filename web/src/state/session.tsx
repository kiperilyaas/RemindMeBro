import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, ApiError } from "../api/client";
import type { DemoAccounts, Health, User } from "../api/types";
import { storage } from "../lib/storage";

interface Session {
  user: User | null; booting: boolean; offline: boolean; health: Health | null; now: Date; demo: DemoAccounts | null;
  login: (email: string, password: string) => Promise<void>;
  register: (p: { email: string; password: string; full_name: string; role: User["role"] }) => Promise<void>;
  logout: (reason?: string) => void; expiredNotice: string | null; refreshHealth: () => Promise<void>;
}
const Ctx = createContext<Session | null>(null);
const DEFAULT_NOW = new Date();

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() => storage.getJSON<User | null>("rmb.user", null));
  const [booting, setBooting] = useState(true);
  const [offline, setOffline] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [demo, setDemo] = useState<DemoAccounts | null>(null);
  const [expiredNotice, setExpired] = useState<string | null>(null);

  const logout = useCallback((reason?: string) => {
    api.setToken(null); storage.del("rmb.user"); setUser(null); setExpired(reason ?? null);
    // start the next session from its home page
    if (location.hash) { history.replaceState(null, "", location.pathname + location.search); window.dispatchEvent(new HashChangeEvent("hashchange")); }
  }, []);
  const refreshHealth = useCallback(async () => { try { setHealth(await api.health()); } catch { /* offline banner handles it */ } }, []);

  useEffect(() => {
    api.listener = { onOffline: setOffline, onUnauthorized: () => logout("Your session expired. Please sign in again.") };
    let cancelled = false;
    (async () => {
      await refreshHealth();
      api.demoAccounts().then((d) => !cancelled && setDemo(d)).catch(() => undefined);
      if (api.token) {
        try { const me = await api.me(); if (!cancelled) { setUser(me); storage.setJSON("rmb.user", me); } }
        catch (e) { if (!cancelled && e instanceof ApiError && !e.offline) logout(); }
      } else if (!cancelled) setUser(null);
      if (!cancelled) setBooting(false);
    })();
    return () => { cancelled = true; api.listener = {}; };
  }, [logout, refreshHealth]);

  // While offline, retry quietly every 8 s.
  useEffect(() => {
    if (!offline) return;
    const t = window.setInterval(refreshHealth, 8000);
    return () => clearInterval(t);
  }, [offline, refreshHealth]);

  const start = useCallback((r: { access_token: string; user: User }) => {
    api.setToken(r.access_token); storage.setJSON("rmb.user", r.user); setExpired(null); setUser(r.user);
  }, []);
  const login = useCallback(async (email: string, password: string) => start(await api.login(email, password)), [start]);
  const register = useCallback(async (p: Parameters<Session["register"]>[0]) => start(await api.register(p)), [start]);

  const now = useMemo(() => (health ? new Date(health.reference_date) : DEFAULT_NOW), [health]);
  const value = useMemo<Session>(() => ({ user, booting, offline, health, now, demo, login, register, logout, expiredNotice, refreshHealth }),
    [user, booting, offline, health, now, demo, login, register, logout, expiredNotice, refreshHealth]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession(): Session {
  const c = useContext(Ctx);
  if (!c) throw new Error("useSession must be used inside <SessionProvider>");
  return c;
}
