"""Patient-scoped Workload Balancer: explainable load review and coordinator-applied redistribution."""
from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.config import settings
from app.core.db import get_db
from app.core.permissions import require_patient_access
from app.engine.workload_balancer import MIN_LEAD, check_receiver, evaluate_workload
from app.models import ActivityHistory, CareActivity, CareAssignment, Caregiver, Notification, Role, TeamRole
from app.services.reassess import TriggerEvent, reassess
from app.services.workload_balancer import MoveError, apply_move, build_snapshot, horizon

router = APIRouter(prefix="/api/v1", tags=["workload balancer"])


class ApplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    activity_id: uuid.UUID
    from_caregiver_id: uuid.UUID
    to_caregiver_id: uuid.UUID
    mode: Literal["REQUEST_CONFIRMATION", "CONFIRM_NOW"] = "REQUEST_CONFIRMATION"
    note: str = Field(default="", max_length=300)


def _current_user(request: Request, db: Session = Depends(get_db)):
    from app.main import current_user
    return current_user(request, db)


def _scope(db: Session, user, patient_id, *, write=False):
    """Oversight screens belong to the patient's primary contacts; caretakers, professionals and patients use their own views."""
    if user.role != Role.PRIMARY_CONTACT:
        raise HTTPException(403, "The Workload Balancer is available to primary contacts")
    patient, member = require_patient_access(db, user, patient_id, "patient:read")
    if member.team_role == TeamRole.PRIMARY_CONTACT:
        return patient, "PRIMARY_CONTACT"
    raise HTTPException(403, "Primary contact permission required")


@router.get("/patients/{patient_id}/workload-balance")
def workload_balance(patient_id: uuid.UUID, days: int = Query(7, ge=1, le=28), user=Depends(_current_user), db: Session = Depends(get_db)):
    patient, role_view = _scope(db, user, patient_id)
    at = now()
    start, end = horizon(at, days)
    result = evaluate_workload(build_snapshot(db, patient.id, start, end), at, start, end, settings.app_timezone)
    can_apply = role_view == "PRIMARY_CONTACT"
    if not can_apply:
        for item in result["recommendations"]: item["from"]["assignment_id"] = None
    return {"patient": {"id": patient.id, "name": patient.name, "is_synthetic": patient.is_synthetic}, "as_of": at,
            "horizon": {"start": start, "end": end, "days": days, "timezone": settings.app_timezone},
            "role_view": role_view, "permissions": {"can_apply": can_apply}, **result}


@router.post("/patients/{patient_id}/workload-balance/apply")
def apply_rebalance(patient_id: uuid.UUID, body: ApplyIn, request: Request, user=Depends(_current_user), db: Session = Depends(get_db)):
    patient, _ = _scope(db, user, patient_id, write=True)
    try:
        result = apply_move(db, patient, body.activity_id, body.from_caregiver_id, body.to_caregiver_id, mode=body.mode, actor=user,
                            note=body.note, request_id=request.state.request_id)
    except MoveError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    db.commit()
    return result
