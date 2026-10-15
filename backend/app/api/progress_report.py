"""Progress report drafts for a healthcare professional, and the optional wellbeing check-ins the report can quote."""
from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.db import get_db
from app.core.features import feature_required
from app.core.permissions import require_patient_access
from app.models import ActivityHistory, Role, TeamRole, WellbeingCheckIn
from app.services.progress_report import report

router = APIRouter(prefix="/api/v1", tags=["progress report"], dependencies=[Depends(feature_required("progress_report"))])
DRAFT_LIMIT, DRAFT_WINDOW = 10, 600  # AI drafts per person per ten minutes: they call quota-limited services
draft_attempts: dict[str, deque[float]] = defaultdict(deque)


class DraftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: int = Field(default=30, ge=7, le=90)


class CheckInIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pain: int | None = Field(default=None, ge=0, le=10)
    mood: int | None = Field(default=None, ge=1, le=5)
    note: str = Field(default="", max_length=300)


def _current_user(request: Request, db: Session = Depends(get_db)):
    from app.main import current_user
    return current_user(request, db)


def _professional_patient(db, user, pid):
    if user.role != Role.PROFESSIONAL: raise HTTPException(403, "Only healthcare professionals can view progress reports")
    patient, _ = require_patient_access(db, user, pid, "patient:read")
    return patient


def _json(value):
    value["patient_id"] = str(value["patient_id"])
    return value


@router.get("/patients/{pid}/progress-report")
def facts_only(pid: uuid.UUID, days: int = Query(30, ge=7, le=90), user=Depends(_current_user), db: Session = Depends(get_db)):
    """The recorded facts and their plain sentences. No AI is called."""
    return _json(report(db, _professional_patient(db, user, pid), days, with_ai=False))


@router.post("/patients/{pid}/progress-report/draft")
async def draft(pid: uuid.UUID, body: DraftIn, user=Depends(_current_user), db: Session = Depends(get_db)):
    """The same facts, phrased by the AI model and checked sentence by sentence against them. Always a draft."""
    patient = _professional_patient(db, user, pid)
    attempts = draft_attempts[str(user.id)]
    cutoff = time.monotonic() - DRAFT_WINDOW
    while attempts and attempts[0] < cutoff: attempts.popleft()
    if len(attempts) >= DRAFT_LIMIT: raise HTTPException(429, "Too many drafts; wait a few minutes", headers={"Retry-After": "60"})
    attempts.append(time.monotonic())
    result = await run_in_threadpool(report, db, patient, body.days, with_ai=True)
    return _json(result)


@router.post("/patients/{pid}/check-ins", status_code=201)
def add_check_in(pid: uuid.UUID, body: CheckInIn, user=Depends(_current_user), db: Session = Depends(get_db)):
    """A short optional self-report. The patient, or a family member or caretaker on their behalf."""
    if body.pain is None and body.mood is None and not body.note.strip(): raise HTTPException(422, "Add a pain level, a mood or a note")
    _, member = require_patient_access(db, user, pid, "patient:read")
    if member.team_role == TeamRole.PROFESSIONAL: raise HTTPException(403, "Check-ins are recorded by the patient or their family and caretakers")
    row = WellbeingCheckIn(patient_id=pid, recorded_by=user.id, pain=body.pain, mood=body.mood, note=body.note.strip())
    db.add(row)
    db.add(ActivityHistory(actor_user_id=user.id, patient_id=pid, event_type="checkin.recorded", entity_type="wellbeing_check_in", entity_id=str(row.id),
                           summary="A wellbeing check-in was recorded", payload={}))
    db.commit()
    return {"id": str(row.id), "pain": row.pain, "mood": row.mood, "note": row.note, "created_at": row.created_at}


@router.get("/patients/{pid}/check-ins")
def list_check_ins(pid: uuid.UUID, limit: int = Query(10, ge=1, le=50), user=Depends(_current_user), db: Session = Depends(get_db)):
    require_patient_access(db, user, pid, "patient:read")
    rows = db.scalars(select(WellbeingCheckIn).where(WellbeingCheckIn.patient_id == pid).order_by(WellbeingCheckIn.created_at.desc()).limit(limit)).all()
    return {"items": [{"id": str(r.id), "pain": r.pain, "mood": r.mood, "note": r.note, "created_at": r.created_at} for r in rows]}
