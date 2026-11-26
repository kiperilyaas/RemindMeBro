// Types mirroring the FastAPI schemas (app/api/schemas.py).
export type Source = "moodle" | "teams" | "email" | "unisis";
export type Role = "student" | "professor";

export type Plan = "free" | "premium";
export interface User { id: number; email: string; full_name: string; role: Role; created_at: string; plan?: Plan }
/** Premium plan (payment is simulated in the prototype). Price comes from app/config.py. */
export interface Billing { plan: Plan; price: string; currency: string; period: string; features: string[]; since: string | null; simulated: boolean }
export type NoteStatus = "waiting" | "syncing" | "transcribing" | "processing" | "ready" | "error";
export type SourceKind = "pdf" | "slides" | "document" | "text" | "audio" | "video";
export interface LessonRow {
  id: number; course_code: string; course_name: string; lesson: string; position: number; status: NoteStatus; error: string | null;
  title: string; summary: string; edited: boolean; new_material: boolean; updated_at: string | null; generated_at: string | null;
  sources: { id: number; filename: string; kind: SourceKind; size: number }[];
}
/** Chat on one lesson or one of its files: answers only from the uploaded material, with the excerpts used. */
export interface LessonChatTurn { role: "user" | "assistant"; content: string }
export interface LessonChatAnswer {
  answer: string; scope: string; skipped: string[];
  sources: { n: number; filename: string; kind: SourceKind; label: string; excerpt: string }[];
}
export interface LessonNote extends LessonRow { body_md: string; key_points: string[]; definitions: { term: string; definition: string }[] }
export interface NotesList { connected: boolean; transcription: boolean; courses: { code: string; name: string; lessons: LessonRow[] }[] }
export interface NotesSync extends NotesList { lessons: number; files: number; queued: number }
export interface TokenResponse { access_token: string; token_type: string; expires_in: number; user: User }
/** Demo accounts: only returned on the computer that runs the demo (never through the public link). */
export interface DemoAccounts { password: string | null; local?: boolean; staff_passwords_file?: string; accounts: { email: string; full_name: string; role: Role; password?: string | null }[] }

export interface Course { id: number; code: string; name: string; professor: string }
export interface Deadline {
  id: number; course_id: number | null; course_name: string | null; course_code: string | null;
  title: string; description: string | null; due_date: string; source: Source;
  is_completed: boolean; extracted_by_ai: boolean; announcement_id: number | null; superseded_by_id: number | null;
  source_message: string | null; replaces: { id: number; title: string; old_due_date: string } | null;
}
export interface InboxItem {
  id: number; source: Source; course_id: number | null; course_code: string | null; course_name: string | null;
  author: string; created_at: string; subject: string; content: string; ai_summary: string; important: boolean;
  deadline_id: number | null; deadline_due: string | null;
}
export interface ScheduleEvent {
  id: number; course_id: number | null; course_code: string | null; course_name: string | null;
  title: string; start_time: string; end_time: string; location: string | null; source: string; kind: string;
}
export interface Announcement { id: number; course_id: number | null; author: string; content: string; created_at: string; source: Source }
export interface Health { status: string; app: string; version: string; reference_date: string; ollama: { reachable?: boolean; model?: string; model_available?: boolean; error?: string }; vector_documents: number }
export interface ChatResponse { question: string; answer: string; sources: Record<string, unknown>[] }
export interface SyncSummary {
  courses_imported: number; moodle_deadlines_imported: number; events_imported: number; moodle_announcements_indexed: number;
  teams_messages_processed: number; emails_processed: number; ai_deadlines_extracted: number; elapsed_seconds: number;
  errors: string[]; unisis: Record<string, unknown> | null; unilearn: Record<string, unknown> | null;
}

export interface Connection {
  provider: "unisis" | "moodle" | "teams" | "email"; name: string; kind: "oauth" | "token" | "demo";
  status: "connected" | "disconnected" | "expired" | "error" | "demo"; portal_url?: string; available?: boolean;
  account?: string | null; account_id?: string | null; scopes?: string[]; connected_at?: string | null; last_sync_at?: string | null; last_error?: string | null;
}

// ---- UniSIS live data (/api/studies) ----
export interface StudyExam {
  id: number; course_code: string; course_name: string; title: string; is_partial: boolean; starts_at: string; room: string;
  capacity: number; seats_left: number; registration_status: "open" | "upcoming" | "closed"; registration_opens_at: string; registration_closes_at: string;
  registered: boolean; can_register: boolean; can_cancel: boolean; reason?: string | null;
}
export interface StudyOffer {
  course_code: string; course_name: string; lecturer: string; credits: number; description?: string; capacity: number; seats_left: number;
  waitlisted: number; status: "none" | "enrolled" | "waitlisted"; waitlist_position?: number | null;
}
export interface Studies {
  connected: boolean; status?: string; portal_url: string; error?: string; last_sync_at?: string | null;
  profile?: {
    student_number: string; year_of_study: number; weighted_average: number | null;
    programme: { degree: string; name: string }; credits: { earned: number; in_progress: number; required: number };
  };
  enrollments?: { course_code: string; course_name: string; lecturer: string; credits: number; status: string; kind: string }[];
  exams?: StudyExam[];
  course_registration?: {
    term: { name: string }; status: "open" | "upcoming" | "closed"; opens_at: string; closes_at: string;
    electives_required: number; electives_chosen: number; offers: StudyOffer[];
  } | null;
  grades?: { credits_earned: number; records: { course_name: string; credits: number; date: string; grade: string; grade_name?: string; grade_value?: number | null }[] };
}

// ---- Lecturer ----
export interface CourseWithStats extends Course { deadline_count: number; ai_deadline_count: number; announcement_count: number; next_deadline: Deadline | null }
export interface Extraction { has_deadline: boolean; course_name: string | null; title: string | null; description: string | null; due_date: string | null }
export interface PublishResult {
  announcement: Announcement; status: "deadline_extracted" | "no_deadline" | "llm_unavailable" | "parsing_error";
  extraction: Extraction | null; saved_deadline: Deadline | null; matched_course: string | null;
  updates_existing: { moodle_title?: string; old_due_date?: string; new_due_date?: string } | null;
  raw_llm_output: string | null; llm_seconds: number; error: string | null;
}
