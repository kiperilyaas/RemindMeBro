"""
Premium plan: Ask Bro and Smart Notes. Payment is simulated in this prototype (no card, no real charge).

  GET  /api/billing          plan of the signed-in user + price shown in the app
  POST /api/billing/plan     {"plan": "premium" | "free"}  (checkout and the switch in Account)

The price is set in app/config.py (PREMIUM_PRICE, PREMIUM_CURRENCY, PREMIUM_PERIOD).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.config import settings
from app.database.db import get_db
from app.database.models import User

router = APIRouter(prefix="/api", tags=["Premium"])

FEATURES = [
    "Ask Bro: questions about your deadlines, timetable, messages and lesson notes",
    "Smart Notes: notes made from the slides, documents and recordings your lecturers upload",
    "Transcription of lesson recordings on your computer",
    "Edit your notes, copy them or save them as PDF",
]


def require_premium(user: User = Depends(get_current_user)) -> User:
    if not user.is_premium:
        raise HTTPException(status_code=402, detail="Ask Bro and Smart Notes are part of Remind Me Bro Premium.")
    return user


def billing_info(user: User) -> Dict[str, Any]:
    return {
        "plan": user.plan,
        "price": settings.PREMIUM_PRICE,
        "currency": settings.PREMIUM_CURRENCY,
        "period": settings.PREMIUM_PERIOD,
        "features": FEATURES,
        "since": user.plan_changed_at.isoformat(timespec="minutes") if user.plan == "premium" and user.plan_changed_at else None,
        "simulated": True,
    }


class PlanBody(BaseModel):
    plan: Literal["free", "premium"]


@router.get("/billing", summary="Plan and price")
def billing(user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return billing_info(user)


@router.post("/billing/plan", summary="Change plan (simulated payment)")
def change_plan(body: PlanBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Dict[str, Any]:
    if user.is_professor:
        raise HTTPException(400, "Lecturers do not need a plan.")
    if user.plan != body.plan:
        user.plan_choice, user.plan_changed_at = body.plan, datetime.now()
        db.commit()
    return billing_info(user)
