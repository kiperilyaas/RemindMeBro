"""UniComms data: one table, the messages the lecturers sent."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from unicomms.db import Base


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(10))            # "outlook" (email) | "teams" (channel post)
    sender: Mapped[str] = mapped_column(String(64))             # lecturer username, e.g. laura.bianchi
    sender_name: Mapped[str] = mapped_column(String(255))       # "Prof. Laura Bianchi"
    sender_email: Mapped[str] = mapped_column(String(255))
    course_code: Mapped[str] = mapped_column(String(32))
    course_name: Mapped[str] = mapped_column(String(255))
    to_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)   # None = every student of the course
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)
