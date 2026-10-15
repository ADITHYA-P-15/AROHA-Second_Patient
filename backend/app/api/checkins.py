"""Task check-ins (flag `checkins`): the caretaker holding a task checks in; the care team sees who has."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.checkin_policy import policy as current_policy
from app.core.clock import now, to_utc
from app.core.db import get_db
from app.core.features import feature_required
from app.core.permissions import require_patient_access
from app.models import CareActivity, TaskCheckIn
from app.services import checkins as svc

router = APIRouter(prefix="/api/v1", tags=["check-ins"], dependencies=[Depends(feature_required("checkins"))])


def _current_user(request: Request, db: Session = Depends(get_db)):
    from app.main import current_user
    return current_user(request, db)


def _dict(row: TaskCheckIn) -> dict:
    return {"id": str(row.id), "activity_id": str(row.activity_id), "caregiver_id": str(row.caregiver_id), "status": row.status,
            "minutes_late": row.minutes_late, "checked_in_at": svc._aware(row.checked_in_at).isoformat()}


@router.post("/activities/{aid}/check-in", status_code=201)
def check_in(aid: uuid.UUID, user=Depends(_current_user), db: Session = Depends(get_db)):
    activity = db.get(CareActivity, aid)
    if not activity: raise HTTPException(404, "Activity not found")
    require_patient_access(db, user, activity.patient_id, "patient:read")
    try: row = svc.check_in(db, activity, user)
    except svc.CheckInError as exc: raise HTTPException(exc.status, str(exc)) from None
    db.commit()
    return _dict(row)


@router.get("/check-ins")
def list_check_ins(patient_id: uuid.UUID, start: datetime | None = Query(None, alias="from"), end: datetime | None = Query(None, alias="to"),
                   user=Depends(_current_user), db: Session = Depends(get_db)):
    """Check-ins for a patient's tasks in a window (default: the last and next 24 hours), plus the rules the UI shows."""
    require_patient_access(db, user, patient_id, "patient:read")
    at = now()
    start = to_utc(start) if start and start.tzinfo else at - timedelta(days=1)
    end = to_utc(end) if end and end.tzinfo else at + timedelta(days=1)
    if end <= start or end - start > timedelta(days=31): raise HTTPException(422, "Use a window of up to 31 days")
    rows = db.scalars(select(TaskCheckIn).join(CareActivity, CareActivity.id == TaskCheckIn.activity_id)
                      .where(CareActivity.patient_id == patient_id, CareActivity.scheduled_start >= start, CareActivity.scheduled_start < end)).all()
    p = current_policy()
    return {"items": [_dict(r) for r in rows], "policy": {k: p[k] for k in ("categories", "importance", "opens_before_min", "grace_min", "missing_after_min")}}
