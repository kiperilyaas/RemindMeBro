"""UniSIS data model."""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from unisis.db import Base


class Programme(Base):
    __tablename__ = "programmes"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    degree: Mapped[str] = mapped_column(String(20))          # e.g. "BSc"
    total_credits: Mapped[int] = mapped_column(Integer)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))             # student | registrar
    password_hash: Mapped[str] = mapped_column(String(200))
    student_number: Mapped[Optional[str]] = mapped_column(String(30), nullable=True, unique=True)
    programme_id: Mapped[Optional[int]] = mapped_column(ForeignKey("programmes.id"), nullable=True)
    year_of_study: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    programme: Mapped[Optional[Programme]] = relationship()


class Term(Base):
    __tablename__ = "terms"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)    # e.g. W2026
    name: Mapped[str] = mapped_column(String(100))                # e.g. Winter term 2026/27
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    registration_opens_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    registration_closes_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    electives_required: Mapped[int] = mapped_column(Integer, default=0)

    courses: Mapped[List["Course"]] = relationship(back_populates="term")


class Course(Base):
    __tablename__ = "courses"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    credits: Mapped[int] = mapped_column(Integer)
    term_id: Mapped[int] = mapped_column(ForeignKey("terms.id"))
    lecturer_name: Mapped[str] = mapped_column(String(200))
    capacity: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))              # core | elective
    year_of_study: Mapped[int] = mapped_column(Integer)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    room: Mapped[str] = mapped_column(String(100), default="")     # main classroom; a weekly class can use another one

    term: Mapped[Term] = relationship(back_populates="courses")
    slots: Mapped[List["TimetableSlot"]] = relationship(back_populates="course", cascade="all, delete-orphan")
    exam_terms: Mapped[List["ExamTerm"]] = relationship(back_populates="course", cascade="all, delete-orphan")
    enrollments: Mapped[List["Enrollment"]] = relationship(back_populates="course", cascade="all, delete-orphan")


class TimetableSlot(Base):
    __tablename__ = "timetable_slots"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    weekday: Mapped[int] = mapped_column(Integer)              # 0 = Monday
    start_time: Mapped[str] = mapped_column(String(5))         # "09:00"
    end_time: Mapped[str] = mapped_column(String(5))
    room: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(30))              # Lecture | Tutorial | Lab

    course: Mapped[Course] = relationship(back_populates="slots")


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("user_id", "course_id", name="uq_enrollment"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    status: Mapped[str] = mapped_column(String(20))            # enrolled | waitlisted | completed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    user: Mapped[User] = relationship()
    course: Mapped[Course] = relationship(back_populates="enrollments")


class ExamTerm(Base):
    __tablename__ = "exam_terms"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    title: Mapped[str] = mapped_column(String(120))            # Written exam, Midterm test...
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    ends_at: Mapped[datetime] = mapped_column(DateTime)
    room: Mapped[str] = mapped_column(String(100))
    capacity: Mapped[int] = mapped_column(Integer)
    registration_opens_at: Mapped[datetime] = mapped_column(DateTime)
    registration_closes_at: Mapped[datetime] = mapped_column(DateTime)
    is_partial: Mapped[bool] = mapped_column(Boolean, default=False)

    course: Mapped[Course] = relationship(back_populates="exam_terms")
    registrations: Mapped[List["ExamRegistration"]] = relationship(back_populates="exam_term", cascade="all, delete-orphan")


class ExamRegistration(Base):
    __tablename__ = "exam_registrations"
    __table_args__ = (UniqueConstraint("exam_term_id", "user_id", name="uq_exam_registration"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    exam_term_id: Mapped[int] = mapped_column(ForeignKey("exam_terms.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    exam_term: Mapped[ExamTerm] = relationship(back_populates="registrations")
    user: Mapped[User] = relationship()


class GradeRecord(Base):
    __tablename__ = "grade_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    exam_term_id: Mapped[Optional[int]] = mapped_column(ForeignKey("exam_terms.id"), nullable=True)
    grade: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)   # Czech scale 1 (best) .. 5 (fail); None = pass/fail
    honours: Mapped[bool] = mapped_column(Boolean, default=False)          # not used with the Czech scale (kept for old databases)
    passed: Mapped[bool] = mapped_column(Boolean, default=True)
    recorded_on: Mapped[date] = mapped_column(Date)

    course: Mapped[Course] = relationship()


# ---------------------------------------------------------------------------
# OAuth 2.0 / API keys
# ---------------------------------------------------------------------------
class OAuthClient(Base):
    __tablename__ = "oauth_clients"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    secret_hash: Mapped[str] = mapped_column(String(64))
    secret_hint: Mapped[str] = mapped_column(String(12))          # last characters, for display
    api_key_hash: Mapped[str] = mapped_column(String(64), index=True)
    api_key_hint: Mapped[str] = mapped_column(String(12))
    redirect_uris: Mapped[str] = mapped_column(Text)              # one per line
    allowed_scopes: Mapped[str] = mapped_column(Text)             # space separated
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    secret_rotated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class AuthorizationCode(Base):
    __tablename__ = "oauth_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("oauth_clients.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    redirect_uri: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(Text)
    code_challenge: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class Token(Base):
    __tablename__ = "oauth_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(10))                 # access | refresh
    client_id: Mapped[int] = mapped_column(ForeignKey("oauth_clients.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    scope: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)

    client: Mapped[OAuthClient] = relationship()
    user: Mapped[User] = relationship()


class Consent(Base):
    __tablename__ = "oauth_consents"
    __table_args__ = (UniqueConstraint("user_id", "client_id", name="uq_consent"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    client_id: Mapped[int] = mapped_column(ForeignKey("oauth_clients.id"))
    scope: Mapped[str] = mapped_column(Text)
    granted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    client: Mapped[OAuthClient] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    client_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(300))
    status_code: Mapped[int] = mapped_column(Integer)
