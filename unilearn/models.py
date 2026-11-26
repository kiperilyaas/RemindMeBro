"""UniLearn data model (a small subset of Moodle's)."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from unilearn.db import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    firstname: Mapped[str] = mapped_column(String(100))
    lastname: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20))            # student | teacher | admin
    password_hash: Mapped[str] = mapped_column(String(200))

    @property
    def fullname(self) -> str:
        return f"{self.firstname} {self.lastname}"


class Course(Base):
    __tablename__ = "courses"
    id: Mapped[int] = mapped_column(primary_key=True)
    shortname: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    fullname: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    room: Mapped[str] = mapped_column(String(100), default="")     # where the lessons take place

    enrolments: Mapped[List["Enrolment"]] = relationship(back_populates="course", cascade="all, delete-orphan")
    assignments: Mapped[List["Assignment"]] = relationship(back_populates="course", cascade="all, delete-orphan", order_by="Assignment.duedate")
    forums: Mapped[List["Forum"]] = relationship(back_populates="course", cascade="all, delete-orphan")
    events: Mapped[List["CalendarEvent"]] = relationship(back_populates="course", cascade="all, delete-orphan", order_by="CalendarEvent.timestart")
    sections: Mapped[List["CourseSection"]] = relationship(back_populates="course", cascade="all, delete-orphan", order_by="CourseSection.position")

    def teachers(self) -> List[User]:
        return [e.user for e in self.enrolments if e.role == "editingteacher"]


class Enrolment(Base):
    __tablename__ = "enrolments"
    __table_args__ = (UniqueConstraint("user_id", "course_id", name="uq_enrolment"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))            # student | editingteacher

    user: Mapped[User] = relationship()
    course: Mapped[Course] = relationship(back_populates="enrolments")


class Assignment(Base):
    __tablename__ = "assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    name: Mapped[str] = mapped_column(String(255))
    intro: Mapped[str] = mapped_column(Text, default="")
    duedate: Mapped[datetime] = mapped_column(DateTime)
    allowsubmissionsfromdate: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    timemodified: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    course: Mapped[Course] = relationship(back_populates="assignments")
    submissions: Mapped[List["Submission"]] = relationship(back_populates="assignment", cascade="all, delete-orphan")


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("assignment_id", "user_id", name="uq_submission"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="submitted")   # submitted
    text: Mapped[str] = mapped_column(Text, default="")
    timemodified: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    assignment: Mapped[Assignment] = relationship(back_populates="submissions")
    user: Mapped[User] = relationship()


class Forum(Base):
    __tablename__ = "forums"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    type: Mapped[str] = mapped_column(String(20), default="news")   # news = "Announcements"
    name: Mapped[str] = mapped_column(String(200), default="Announcements")

    course: Mapped[Course] = relationship(back_populates="forums")
    discussions: Mapped[List["Discussion"]] = relationship(back_populates="forum", cascade="all, delete-orphan", order_by="Discussion.created.desc()")


class Discussion(Base):
    __tablename__ = "discussions"
    id: Mapped[int] = mapped_column(primary_key=True)
    forum_id: Mapped[int] = mapped_column(ForeignKey("forums.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    subject: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    created: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    forum: Mapped[Forum] = relationship(back_populates="discussions")
    user: Mapped[User] = relationship()


class CalendarEvent(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    timestart: Mapped[datetime] = mapped_column(DateTime)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=60)
    location: Mapped[str] = mapped_column(String(200), default="")

    course: Mapped[Course] = relationship(back_populates="events")


class CourseSection(Base):
    """A lesson or module of the course page (Moodle: course_sections)."""
    __tablename__ = "course_sections"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=1)
    timemodified: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    course: Mapped[Course] = relationship(back_populates="sections")
    resources: Mapped[List["Resource"]] = relationship(back_populates="section", cascade="all, delete-orphan", order_by="Resource.id")


class Resource(Base):
    """A file uploaded by the teacher (Moodle: mod_resource + its file in the file pool)."""
    __tablename__ = "resources"
    id: Mapped[int] = mapped_column(primary_key=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("course_sections.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    filename: Mapped[str] = mapped_column(String(255))
    mimetype: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    filesize: Mapped[int] = mapped_column(Integer, default=0)
    contenthash: Mapped[str] = mapped_column(String(64), index=True)       # sha1 of the bytes, like Moodle
    timemodified: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    section: Mapped[CourseSection] = relationship(back_populates="resources")


class ExternalToken(Base):
    """Web-service token (Moodle: external_tokens). Stored hashed; shown once."""
    __tablename__ = "external_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    token_hint: Mapped[str] = mapped_column(String(8))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    service: Mapped[str] = mapped_column(String(50))
    client_name: Mapped[str] = mapped_column(String(120), default="")
    created: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    lastaccess: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship()


class WSLog(Base):
    __tablename__ = "ws_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    function: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(80))           # ok | errorcode
