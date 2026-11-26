import type {
  Billing, LessonChatAnswer, LessonChatMessage, LessonNote, NotesList, NotesSync, Plan,
  ChatResponse, Connection, Course, CourseWithStats, DemoAccounts, Deadline, Health, InboxItem, PublishResult,
  ScheduleEvent, Source, Studies, SyncSummary, TokenResponse, User,
} from "./types";
import { storage } from "../lib/storage";

export class ApiError extends Error {
  constructor(message: string, public status: number, public offline = false) { super(message); }
}

export const API_BASE = (() => {
  const custom = storage.get("rmb.apiBase");
  if (custom) return custom.replace(/\/+$/, "");
  if (typeof location !== "undefined" && /^https?:$/.test(location.protocol)) return location.origin + "/api";
  return "http://localhost:8000/api";
})();

type Listener = { onOffline?: (offline: boolean) => void; onUnauthorized?: () => void };
interface RequestOpts { method?: string; body?: unknown; timeout?: number; auth?: boolean }

/** Thin typed wrapper around fetch: bearer token, timeout, offline + 401 detection, FastAPI error messages. */
export class ApiClient {
  token: string | null = storage.get("rmb.token");
  listener: Listener = {};

  setToken(t: string | null) {
    this.token = t;
    if (t) storage.set("rmb.token", t); else storage.del("rmb.token");
  }

  async request<T>(path: string, { method = "GET", body, timeout = 20000, auth = true }: RequestOpts = {}): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (auth && this.token) headers.Authorization = `Bearer ${this.token}`;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeout);
    let res: Response;
    try {
      res = await fetch(API_BASE + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal: ctrl.signal });
    } catch (err) {
      if ((err as Error).name === "AbortError") throw new ApiError("The server did not answer in time. Please try again.", 0);
      this.listener.onOffline?.(true);
      throw new ApiError("Can't reach the Remind Me Bro server. Is the Run & Go window still open?", 0, true);
    } finally {
      clearTimeout(timer);
    }
    this.listener.onOffline?.(false);
    if (res.status === 204) return null as T;
    const data: unknown = await res.json().catch(() => null);
    if (!res.ok) {
      const detail = (data as { detail?: unknown } | null)?.detail;
      const msg = Array.isArray(detail)
        ? detail.map((d: { loc?: string[]; msg: string }) => (d.loc ? `${d.loc[d.loc.length - 1]}: ` : "") + d.msg).join(" · ")
        : typeof detail === "string" ? detail : `Request failed (${res.status})`;
      if (res.status === 401 && auth && this.token) this.listener.onUnauthorized?.();
      throw new ApiError(msg, res.status);
    }
    return data as T;
  }

  // public
  health = () => this.request<Health>("/health", { auth: false, timeout: 8000 });
  demoAccounts = () => this.request<DemoAccounts>("/demo-accounts", { auth: false, timeout: 8000 });
  // auth
  login = (email: string, password: string) => this.request<TokenResponse>("/auth/login", { method: "POST", body: { email, password }, auth: false });
  register = (p: { email: string; password: string; full_name: string; role: User["role"] }) =>
    this.request<TokenResponse>("/auth/register", { method: "POST", body: p, auth: false });
  me = () => this.request<User>("/auth/me");
  // student
  deadlines = () => this.request<Deadline[]>("/deadlines");
  setDone = (id: number, done: boolean) => this.request<Deadline>(`/deadlines/${id}/complete?completed=${done}`, { method: "PATCH" });
  inbox = () => this.request<InboxItem[]>("/inbox");
  schedule = (start: string, end: string) => this.request<ScheduleEvent[]>(`/schedule?start=${start}&end=${end}`);
  courses = () => this.request<Course[]>("/courses");
  chat = (question: string) => this.request<ChatResponse>("/chat", { method: "POST", body: { question }, timeout: 180000 });
  sync = () => this.request<SyncSummary>("/sync", { method: "POST", timeout: 600000 });
  // Premium (Ask Bro + Smart Notes)
  billing = () => this.request<Billing>("/billing");
  setPlan = (plan: Plan) => this.request<Billing>("/billing/plan", { method: "POST", body: { plan } });
  notes = () => this.request<NotesList>("/notes");
  syncNotes = () => this.request<NotesSync>("/notes/sync", { method: "POST", timeout: 120000 });
  note = (id: number) => this.request<LessonNote>(`/notes/${id}`);
  saveNote = (id: number, body_md: string) => this.request<LessonNote>(`/notes/${id}`, { method: "PUT", body: { body_md } });
  regenerateNote = (id: number) => this.request<LessonNote>(`/notes/${id}/regenerate`, { method: "POST" });
  stopNote = (id: number) => this.request<LessonNote>(`/notes/${id}/stop`, { method: "POST" });
  deleteNote = (id: number) => this.request<{ deleted: boolean }>(`/notes/${id}`, { method: "DELETE" });
  lessonChat = (id: number, question: string, sourceId: number | null) =>
    this.request<LessonChatAnswer>(`/notes/${id}/chat`, { method: "POST", body: { question, source_id: sourceId }, timeout: 1800000 });   // a slow computer can need minutes
  lessonChatHistory = (id: number, sourceId: number | null) =>
    this.request<{ messages: LessonChatMessage[] }>(`/notes/${id}/chat${sourceId === null ? "" : `?source_id=${sourceId}`}`);
  clearLessonChat = (id: number, sourceId: number | null) =>
    this.request<null>(`/notes/${id}/chat${sourceId === null ? "" : `?source_id=${sourceId}`}`, { method: "DELETE" });
  // connections
  connections = () => this.request<Connection[]>("/connections");
  connectUnisis = () => this.request<{ authorize_url: string }>("/connections/unisis/start", { method: "POST" });
  syncUnisis = () => this.request<{ events: number; deadlines: number }>("/connections/unisis/sync", { method: "POST", timeout: 60000 });
  disconnectUnisis = () => this.request<{ disconnected: boolean }>("/connections/unisis", { method: "DELETE" });
  connectMoodle = (username: string, password: string) =>
    this.request<{ account: string; assignments: number; submitted: number; events: number; posts: number }>("/connections/moodle", { method: "POST", body: { username, password }, timeout: 60000 });
  syncMoodle = () => this.request<{ assignments: number; events: number; posts: number; ai_details?: { status?: string }[] }>("/connections/moodle/sync", { method: "POST", timeout: 300000 });
  disconnectMoodle = () => this.request<{ disconnected: boolean }>("/connections/moodle", { method: "DELETE" });
  // studies (UniSIS)
  studies = () => this.request<Studies>("/studies", { timeout: 30000 });
  examRegister = (id: number) => this.request<unknown>(`/studies/exams/${id}/registration`, { method: "POST", timeout: 30000 });
  examCancel = (id: number) => this.request<unknown>(`/studies/exams/${id}/registration`, { method: "DELETE", timeout: 30000 });
  courseEnroll = (code: string) => this.request<unknown>(`/studies/courses/${encodeURIComponent(code)}/enrollment`, { method: "POST", timeout: 30000 });
  courseDrop = (code: string) => this.request<unknown>(`/studies/courses/${encodeURIComponent(code)}/enrollment`, { method: "DELETE", timeout: 30000 });
  // lecturer
  prof = {
    courses: () => this.request<CourseWithStats[]>("/professor/courses"),
    createCourse: (p: { code: string; name: string }) => this.request<Course>("/professor/courses", { method: "POST", body: p }),
    publish: (p: { course_id: number; content: string; channel: Source }) => this.request<PublishResult>("/professor/announcements", { method: "POST", body: p, timeout: 180000 }),
    createAssignment: (p: { course_id: number; title: string; description?: string; due_date: string }) => this.request<Deadline>("/professor/assignments", { method: "POST", body: p }),
    extracted: () => this.request<Deadline[]>("/professor/extracted-deadlines"),
    updateExtracted: (id: number, p: { title?: string; due_date?: string; description?: string }) => this.request<Deadline>(`/professor/extracted-deadlines/${id}`, { method: "PATCH", body: p }),
    deleteExtracted: (id: number) => this.request<null>(`/professor/extracted-deadlines/${id}`, { method: "DELETE" }),
  };
}

export const api = new ApiClient();
