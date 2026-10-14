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
from app.services.workload_balancer import ACTIVE, HANDOFF_STANDBY, _aware, build_snapshot, horizon

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
    """Coordinators and administrators manage; family contacts read; caregivers, patients and doctors are excluded."""
    if user.role not in {Role.ADMIN, Role.FAMILY}:
        raise HTTPException(403, "The Workload Balancer is available to primary contacts")
    patient, member = require_patient_access(db, user, patient_id, "patient:read")
    if user.role == Role.ADMIN or member.team_role == TeamRole.COORDINATOR:
        return patient, "COORDINATOR" if user.role != Role.ADMIN else "ADMIN"
    if member.team_role == TeamRole.FAMILY and not write:
        return patient, "FAMILY"
    raise HTTPException(403, "Coordinator permission required" if write else "Workload Balancer access denied")


@router.get("/patients/{patient_id}/workload-balance")
def workload_balance(patient_id: uuid.UUID, days: int = Query(7, ge=1, le=28), user=Depends(_current_user), db: Session = Depends(get_db)):
    patient, role_view = _scope(db, user, patient_id)
    at = now()
    start, end = horizon(at, days)
    result = evaluate_workload(build_snapshot(db, patient.id, start, end), at, start, end, settings.app_timezone)
    can_apply = role_view in {"COORDINATOR", "ADMIN"}
    if not can_apply:
        for item in result["recommendations"]: item["from"]["assignment_id"] = None
    return {"patient": {"id": patient.id, "name": patient.name, "is_synthetic": patient.is_synthetic}, "as_of": at,
            "horizon": {"start": start, "end": end, "days": days, "timezone": settings.app_timezone},
            "role_view": role_view, "permissions": {"can_apply": can_apply}, **result}


@router.post("/patients/{patient_id}/workload-balance/apply")
def apply_rebalance(patient_id: uuid.UUID, body: ApplyIn, request: Request, user=Depends(_current_user), db: Session = Depends(get_db)):
    patient, _ = _scope(db, user, patient_id, write=True)
    activity = db.get(CareActivity, body.activity_id)
    if not activity or activity.patient_id != patient.id: raise HTTPException(404, "Activity not found")
    at = now()
    if activity.lifecycle_status != "SCHEDULED" or not activity.requires_caregiver: raise HTTPException(409, "Only scheduled caregiver tasks can be rebalanced")
    if _aware(activity.scheduled_start) < at + MIN_LEAD: raise HTTPException(409, "This task starts within two hours; arrange cover directly with the caregivers")
    current = db.scalar(select(CareAssignment).where(CareAssignment.activity_id == activity.id, CareAssignment.role == "PRIMARY",
                                                     CareAssignment.status.in_(ACTIVE)).with_for_update())
    if not current or current.caregiver_id != body.from_caregiver_id:
        raise HTTPException(409, "This task's assignment changed; refresh the Workload Balancer")
    # Lock the receiver so concurrent moves of different tasks cannot both pass the limit check.
    if db.scalar(select(Caregiver.id).where(Caregiver.id == body.to_caregiver_id).with_for_update()) is None:
        raise HTTPException(409, "Cannot move this task: Caregiver is not linked to this patient.")
    zone = ZoneInfo(settings.app_timezone)
    day_start, _ = horizon(_aware(activity.scheduled_start), 1)
    ok, reasons = check_receiver(build_snapshot(db, patient.id, day_start, day_start + timedelta(days=1)), at, day_start,
                                 day_start + timedelta(days=1), str(activity.id), str(body.from_caregiver_id), str(body.to_caregiver_id), settings.app_timezone)
    if not ok: raise HTTPException(409, "Cannot move this task: " + " ".join(reasons))
    receiver = db.get(Caregiver, body.to_caregiver_id)
    donor = db.get(Caregiver, body.from_caregiver_id)
    confirmed = body.mode == "CONFIRM_NOW"
    # Never drop confirmed cover on a request: the previous caregiver stays as a confirmed standby backup
    # until the new caregiver confirms (the assignment confirm path then releases the standby).
    standby = not confirmed and current.status == "CONFIRMED"
    try:
        for backup in db.scalars(select(CareAssignment).where(CareAssignment.activity_id == activity.id, CareAssignment.caregiver_id == receiver.id,
                                                              CareAssignment.role == "BACKUP", CareAssignment.status.in_(ACTIVE))):
            backup.status = "SUPERSEDED"; backup.updated_at = at
        current.status = "SUPERSEDED"; current.updated_at = at
        db.flush()
        created = CareAssignment(activity_id=activity.id, caregiver_id=receiver.id, role="PRIMARY",
                                 status="CONFIRMED" if confirmed else "AWAITING_CONFIRMATION", assigned_by=user.id, assigned_at=at,
                                 confirmed_at=at if confirmed else None, confirmed_by=user.id if confirmed else None,
                                 confirmed_via="COORDINATOR" if confirmed else None)
        db.add(created)
        if standby:
            db.add(CareAssignment(activity_id=activity.id, caregiver_id=current.caregiver_id, role="BACKUP", status="CONFIRMED", assigned_by=user.id,
                                  assigned_at=at, confirmed_at=at, confirmed_by=user.id, confirmed_via=HANDOFF_STANDBY))
        db.flush()
    except IntegrityError:
        db.rollback(); raise HTTPException(409, "Another coordinator updated this task; refresh and retry") from None
    when = _aware(activity.scheduled_start).astimezone(zone).strftime("%a %d %b, %H:%M")
    if receiver.user_id:
        db.add(Notification(user_id=receiver.user_id, patient_id=patient.id, kind="STATUS" if confirmed else "DECISION", severity="MEDIUM",
                            title="Care task assigned to you" if confirmed else "Can you take this care task?",
                            body=f"{activity.title} · {when}." + ("" if confirmed else " Please confirm or decline in Care Plan."),
                            requires_ack=not confirmed, channel="INBOX"))
    if donor and donor.user_id and donor.user_id != user.id:
        db.add(Notification(user_id=donor.user_id, patient_id=patient.id, kind="STATUS", severity="LOW", title="A care task was moved off your plan",
                            body=f"{activity.title} · {when} is moving to {receiver.name} to balance workload."
                                 + (f" You stay as backup until {receiver.name} confirms." if standby else ""), requires_ack=False, channel="INBOX"))
    db.add(ActivityHistory(actor_user_id=user.id, patient_id=patient.id, event_type="workload.rebalanced", entity_type="care_assignment",
                           entity_id=str(created.id), summary=f"Task moved from {donor.name if donor else 'caregiver'} to {receiver.name} to balance workload",
                           payload={"activity_id": str(activity.id), "from_caregiver_id": str(body.from_caregiver_id), "to_caregiver_id": str(receiver.id),
                                    "superseded_assignment_id": str(current.id), "mode": body.mode, "standby_backup": standby, "note": body.note.strip()},
                           request_id=request.state.request_id))
    reassess(db, [patient.id], TriggerEvent.ASSIGNMENT_ADDED, {"assignment_ids": [str(created.id)], "source": "workload_balancer"})
    db.commit()
    message = (f"{activity.title} is now confirmed with {receiver.name}." if confirmed
               else f"{receiver.name} has been asked to confirm {activity.title}. Support shows as not confirmed until they do"
               + (f"; {donor.name if donor else 'the previous caregiver'} stays as confirmed backup meanwhile." if standby else "."))
    return {"activity_id": activity.id, "superseded_assignment_id": current.id,
            "standby_backup": standby, "assignment": {"id": created.id, "caregiver_id": receiver.id, "caregiver_name": receiver.name, "status": created.status},
            "message": message}
