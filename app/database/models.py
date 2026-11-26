"""
Schema relazionale unificato.

Ogni piattaforma esterna (Moodle, Teams, Email) viene normalizzata
in queste entità. I campi `external_id` rendono la sincronizzazione
idempotente (rieseguire /api/sync non crea duplicati).

Entità:
- User          utenti dell'app (studenti e docenti) con autenticazione JWT
- Course        corsi; `professor_id` collega il corso al docente che lo gestisce
- Deadline      scadenze formali (Moodle) o estratte dall'AI (Teams/Email/avvisi docente)
- Announcement  avvisi/messaggi testuali (indicizzati anche in ChromaDB)
- Event         eventi di calendario (lezioni, seminari, prove)
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.db import Base


def _enum_values(e):
    """Salva in DB il valore ('moodle') e non il nome ('MOODLE') dell'enum."""
    return [m.value for m in e]


class SourceType(str, enum.Enum):
    """Piattaforma di provenienza del dato."""

    MOODLE = "moodle"
    TEAMS = "teams"
    EMAIL = "email"
    UNISIS = "unisis"   # student information system (personal data, per user)


class UserRole(str, enum.Enum):
    """Ruoli applicativi."""

    STUDENT = "student"
    PROFESSOR = "professor"


# ---------------------------------------------------------------------------
# Utenti
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, values_callable=_enum_values), default=UserRole.STUDENT)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    courses: Mapped[List["Course"]] = relationship(back_populates="professor_user")
    # Subscription: "free" or "premium". Empty = never chosen: the demo student starts on Premium, everybody else on Free.
    plan_choice: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    plan_changed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    @property
    def is_professor(self) -> bool:
        return self.role == UserRole.PROFESSOR

    @property
    def plan(self) -> str:
        if self.plan_choice in ("free", "premium"):
            return self.plan_choice
        return "premium" if self.email == "student@demo.it" else "free"

    @property
    def is_premium(self) -> bool:
        return self.plan == "premium" or self.is_professor

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.role.value})>"


# ---------------------------------------------------------------------------
# Dominio accademico
# ---------------------------------------------------------------------------
class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    # Nome del docente così come arriva dalla piattaforma (es. Moodle)
    professor: Mapped[str] = mapped_column(String(255))
    # Docente registrato nell'app che gestisce il corso (può essere vuoto)
    professor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)

    professor_user: Mapped[Optional[User]] = relationship(back_populates="courses")
    deadlines: Mapped[List["Deadline"]] = relationship(back_populates="course", cascade="all, delete-orphan")
    announcements: Mapped[List["Announcement"]] = relationship(back_populates="course", cascade="all, delete-orphan")
    events: Mapped[List["Event"]] = relationship(back_populates="course", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Course {self.code} - {self.name}>"


class Announcement(Base):
    __tablename__ = "announcements"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_announcement_source_ext"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    course_id: Mapped[Optional[int]] = mapped_column(ForeignKey("courses.id"), nullable=True, index=True)
    author: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    source: Mapped[SourceType] = mapped_column(Enum(SourceType, values_callable=_enum_values))
    external_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # Docente registrato che ha pubblicato l'avviso dall'app (None per i dati sincronizzati)
    author_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    # Personal message (Outlook email or Teams chat added by a student) visible only to this user; None = shared
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)

    course: Mapped[Optional[Course]] = relationship(back_populates="announcements")
    author_user: Mapped[Optional[User]] = relationship(foreign_keys=[author_id])
    deadlines: Mapped[List["Deadline"]] = relationship(back_populates="announcement")


class Deadline(Base):
    __tablename__ = "deadlines"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_deadline_source_ext"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    course_id: Mapped[Optional[int]] = mapped_column(ForeignKey("courses.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    due_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    source: Mapped[SourceType] = mapped_column(Enum(SourceType, values_callable=_enum_values))
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- Tracciabilità ---
    external_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    extracted_by_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    # Avviso da cui l'AI ha estratto la scadenza
    announcement_id: Mapped[Optional[int]] = mapped_column(ForeignKey("announcements.id"), nullable=True, index=True)
    # Se un avviso successivo sposta questa scadenza, punta alla nuova scadenza
    superseded_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("deadlines.id"), nullable=True)
    # Docente che ha creato il compito dall'app
    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    # Personal deadline (e.g. from UniSIS) visible only to this user; None = shared course data
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    # When the source system (e.g. UniLearn) last changed this deadline: a message older than this can't move it
    source_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    course: Mapped[Optional[Course]] = relationship(back_populates="deadlines")
    announcement: Mapped[Optional[Announcement]] = relationship(back_populates="deadlines")
    superseded_by: Mapped[Optional["Deadline"]] = relationship(remote_side="Deadline.id")


class DeadlineDone(Base):
    """A student ticked a shared course deadline as done (or handed the work in): one row per student."""
    __tablename__ = "deadline_done"
    __table_args__ = (UniqueConstraint("user_id", "deadline_id", name="uq_deadline_done"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    deadline_id: Mapped[int] = mapped_column(ForeignKey("deadlines.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("external_id", name="uq_event_ext"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    course_id: Mapped[Optional[int]] = mapped_column(ForeignKey("courses.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    start_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="moodle")
    # Personal event (timetable/exams from UniSIS) visible only to this user; None = shared
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(20), default="class")   # class | exam | event

    course: Mapped[Optional[Course]] = relationship(back_populates="events")


# ---------------------------------------------------------------------------
# External connections (OAuth 2.0 client side)
# ---------------------------------------------------------------------------
class Connection(Base):
    """A user's link to an external system (e.g. UniSIS). Tokens are stored encrypted."""

    __tablename__ = "connections"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_connection_user_provider"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="connected")   # connected | expired | error
    access_token_enc: Mapped[str] = mapped_column(Text)
    refresh_token_enc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    scope: Mapped[str] = mapped_column(Text, default="")
    external_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    external_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    connected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # JSON summary used by the AI assistant


class OAuthState(Base):
    """Pending authorization request (state + PKCE verifier) while the user is on the provider's consent page."""

    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    provider: Mapped[str] = mapped_column(String(30))
    code_verifier: Mapped[str] = mapped_column(String(200))
    redirect_uri: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


# ---------------------------------------------------------------------------
# Smart Notes (Premium): study notes made from the files lecturers upload to UniLearn/Moodle
# ---------------------------------------------------------------------------
class LessonNote(Base):
    """One page of notes per student and lesson (Moodle course section)."""

    __tablename__ = "lesson_notes"
    __table_args__ = (UniqueConstraint("user_id", "course_code", "section_ext_id", name="uq_note_user_section"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    course_code: Mapped[str] = mapped_column(String(50), index=True)
    course_name: Mapped[str] = mapped_column(String(255))
    section_ext_id: Mapped[int] = mapped_column(Integer)
    lesson_name: Mapped[str] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(Integer, default=0)
    # new (found, not made yet: the student presses "Make notes") | waiting | syncing | transcribing | processing | ready | error
    status: Mapped[str] = mapped_column(String(20), default="new")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    key_points: Mapped[str] = mapped_column(Text, default="[]")      # JSON list of strings
    definitions: Mapped[str] = mapped_column(Text, default="[]")     # JSON list of {term, definition}
    body_md: Mapped[str] = mapped_column(Text, default="")
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    sources_hash: Mapped[str] = mapped_column(String(64), default="")     # files the lesson has now
    generated_hash: Mapped[str] = mapped_column(String(64), default="")   # files the notes were made from
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    sources: Mapped[List["NoteSource"]] = relationship(back_populates="note", cascade="all, delete-orphan", order_by="NoteSource.id")
    chat: Mapped[List["LessonChatMessage"]] = relationship(cascade="all, delete-orphan", order_by="LessonChatMessage.id")


class NoteSource(Base):
    """A file of the lesson (slides, document, recording)."""

    __tablename__ = "note_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    note_id: Mapped[int] = mapped_column(ForeignKey("lesson_notes.id"), index=True)
    resource_ext_id: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(20))           # slides | document | text | audio | video
    contenthash: Mapped[str] = mapped_column(String(64))
    fileurl: Mapped[str] = mapped_column(Text)
    filesize: Mapped[int] = mapped_column(Integer, default=0)

    note: Mapped[LessonNote] = relationship(back_populates="sources")


class ExtractedText(Base):
    """Text read or transcribed from a file, kept by content hash: the same file is processed once for every student."""

    __tablename__ = "extracted_texts"

    contenthash: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class LessonChatMessage(Base):
    """Saved chat "Ask the material": one conversation per lesson (source_id empty) and one per file."""

    __tablename__ = "lesson_chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    note_id: Mapped[int] = mapped_column(ForeignKey("lesson_notes.id"), index=True)
    source_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    role: Mapped[str] = mapped_column(String(10))          # user | assistant
    content: Mapped[str] = mapped_column(Text)
    sources: Mapped[str] = mapped_column(Text, default="[]")   # JSON: excerpts the answer used
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
