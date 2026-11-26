"""
Schemi Pydantic (v2) per request/response delle API.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.database.models import SourceType, UserRole


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: UserRole
    created_at: datetime
    plan: str = "free"


class RegisterRequest(BaseModel):
    email: EmailStr = Field(..., examples=["anna.smith@students.example.edu"])
    password: str = Field(..., min_length=6, examples=["password123"])
    full_name: str = Field(..., min_length=2, max_length=120, examples=["Anna Smith"])
    role: UserRole = Field(UserRole.STUDENT, description="'student' or 'professor' (lecturer)")

    @field_validator("password")
    @classmethod
    def _bcrypt_limit(cls, v: str) -> str:
        # bcrypt considera solo i primi 72 byte: rifiutiamo password più lunghe
        if len(v.encode("utf-8")) > 72:
            raise ValueError("The password cannot be longer than 72 bytes.")
        return v


class LoginRequest(BaseModel):
    email: str = Field(..., examples=["student@demo.it"])
    password: str = Field(..., examples=["demo1234"])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


# ---------------------------------------------------------------------------
# Entità
# ---------------------------------------------------------------------------
class CourseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    professor: str


class DeadlineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: Optional[int]
    course_name: Optional[str] = None
    course_code: Optional[str] = None
    title: str
    description: Optional[str]
    due_date: datetime
    source: SourceType
    is_completed: bool
    extracted_by_ai: bool
    announcement_id: Optional[int] = None
    superseded_by_id: Optional[int] = None
    source_message: Optional[str] = Field(None, description="Text of the announcement the AI extracted the deadline from")
    replaces: Optional[Dict[str, Any]] = Field(None, description="Moodle deadline replaced by this one")

    @classmethod
    def from_orm_deadline(cls, d: Any, replaces: Any = None) -> "DeadlineOut":
        out = cls.model_validate(d)
        out.course_name = d.course.name if d.course else None
        out.course_code = d.course.code if d.course else None
        out.source_message = d.announcement.content if d.announcement else None
        if replaces is not None:
            out.replaces = {"id": replaces.id, "title": replaces.title, "old_due_date": replaces.due_date.isoformat()}
        return out


class AnnouncementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: Optional[int]
    author: str
    content: str
    created_at: datetime
    source: SourceType


class InboxItem(BaseModel):
    """Messaggio normalizzato per la Inbox unificata del frontend."""

    id: int
    source: SourceType
    course_id: Optional[int] = None
    course_code: Optional[str] = None
    course_name: Optional[str] = None
    author: str
    created_at: datetime
    subject: str
    content: str
    ai_summary: str
    important: bool
    deadline_id: Optional[int] = None
    deadline_due: Optional[datetime] = None
    personal: bool = False   # UniComms email sent to this student only (not to the whole course)


class ScheduleEvent(BaseModel):
    id: int
    course_id: Optional[int] = None
    course_code: Optional[str] = None
    course_name: Optional[str] = None
    title: str
    start_time: datetime
    end_time: datetime
    location: Optional[str] = None
    source: str = "moodle"
    kind: str = "class"


class CourseWithStats(CourseOut):
    deadline_count: int = 0
    ai_deadline_count: int = 0
    announcement_count: int = 0
    next_deadline: Optional[DeadlineOut] = None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: Optional[int]
    title: str
    start_time: datetime
    end_time: datetime
    location: Optional[str]


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------
class SyncSummary(BaseModel):
    courses_imported: int
    moodle_deadlines_imported: int
    events_imported: int
    moodle_announcements_indexed: int
    teams_messages_processed: int
    emails_processed: int = 0
    teams_messages_indexed: int
    ai_deadlines_extracted: int
    vector_documents_total: int
    elapsed_seconds: float
    ai_details: List[Dict[str, Any]] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    unisis: Optional[Dict[str, Any]] = Field(None, description="UniSIS import result for the current user (if connected)")
    unilearn: Optional[Dict[str, Any]] = Field(None, description="UniLearn (Moodle web services) import result, if connected")


# ---------------------------------------------------------------------------
# Chat RAG
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    question: str = Field(..., min_length=2, examples=["When is the Microeconomics problem set due?"])
    include_context: bool = Field(False, description="If true, also returns the context sent to the LLM (demo/debug).")


class ChatResponse(BaseModel):
    question: str
    answer: str
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    context_used: Optional[str] = None


# ---------------------------------------------------------------------------
# Simulazione messaggio Teams (demo live)
# ---------------------------------------------------------------------------
class SimulateMessageRequest(BaseModel):
    content: str = Field(
        ...,
        min_length=5,
        examples=["Reminder: the Econometrics lab report is due by Monday 9 November at 12:00."],
    )
    author: str = Field("Lecturer (live demo)", examples=["Prof. Paolo Conti"])
    course_code: Optional[str] = Field(None, description="Course code of the Teams channel (optional).", examples=["ECMT-2026"])
    source: SourceType = SourceType.TEAMS


class ExtractionOut(BaseModel):
    has_deadline: bool
    course_name: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[datetime] = None


class SimulateMessageResponse(BaseModel):
    message_id: str
    announcement_id: int
    indexed_in_vector_db: bool
    extraction: ExtractionOut
    saved_deadline: Optional[DeadlineOut] = None
    matched_course: Optional[str] = None
    updates_existing: Optional[Dict[str, Any]] = None
    raw_llm_output: str
    llm_seconds: float


# ---------------------------------------------------------------------------
# Docente
# ---------------------------------------------------------------------------
class ProfessorAnnouncementRequest(BaseModel):
    course_id: int = Field(..., examples=[1])
    content: str = Field(
        ..., min_length=5, max_length=4000,
        examples=["Hi everyone, the project deadline is moved to 25 October at 18:00."],
    )
    channel: SourceType = Field(SourceType.TEAMS, description="Simulated channel: teams, moodle or email")


class ProfessorAnnouncementResponse(BaseModel):
    announcement: AnnouncementOut
    status: str = Field(..., description="deadline_extracted | no_deadline | llm_unavailable | parsing_error")
    extraction: Optional[ExtractionOut] = None
    saved_deadline: Optional[DeadlineOut] = None
    matched_course: Optional[str] = None
    updates_existing: Optional[Dict[str, Any]] = None
    raw_llm_output: Optional[str] = None
    indexed_in_vector_db: bool = True
    llm_seconds: float = 0.0
    error: Optional[str] = None


class AssignmentCreate(BaseModel):
    course_id: int
    title: str = Field(..., min_length=3, max_length=255, examples=["Final project"])
    description: Optional[str] = Field(None, max_length=4000)
    due_date: datetime = Field(..., examples=["2026-11-30T23:59:00"])


class CourseCreate(BaseModel):
    code: str = Field(..., min_length=2, max_length=32, examples=["BEHAV-2026"])
    name: str = Field(..., min_length=2, max_length=255, examples=["Behavioural Finance"])


class DeadlineUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=2, max_length=255)
    description: Optional[str] = None
    due_date: Optional[datetime] = None


class HealthOut(BaseModel):
    status: str
    app: str
    version: str
    reference_date: datetime
    ollama: Dict[str, Any]
    vector_documents: int
