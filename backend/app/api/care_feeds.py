"""Healthcare professionals' data feeds: prescriptions (medication) and appointments (schedule); adherence; main caretaker."""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.db import get_db
from app.core.permissions import require_patient_access
from app.models import ActivityHistory, CareActivity, CaregiverPatientLink, Prescription, Role, TeamRole
from app.services import care_feeds as feeds
from app.services.care_status import care_status
from app.services.reassess import TriggerEvent, reassess

router = APIRouter(prefix="/api/v1", tags=["care feeds"])
HHMM = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PrescriptionIn(Input):
    medicine: str = Field(min_length=1, max_length=160)
    dose: str = Field(min_length=1, max_length=80)
    instructions: str = Field(default="", max_length=500)
    times: list[str] = Field(min_length=1, max_length=8)
    start_date: date
    end_date: date | None = None

    @field_validator("times")
    @classmethod
    def valid_times(cls, value):
        if any(not HHMM.match(t) for t in value): raise ValueError("Times must be HH:MM (24-hour)")
        if len(set(value)) != len(value): raise ValueError("Times must not repeat")
        return sorted(value)

    @model_validator(mode="after")
    def valid_dates(self):
        if self.end_date and self.end_date < self.start_date: raise ValueError("end_date must be on or after start_date")
        return self


class PrescriptionPatch(Input):
    dose: str | None = Field(default=None, min_length=1, max_length=80)
    instructions: str | None = Field(default=None, max_length=500)
    times: list[str] | None = Field(default=None, min_length=1, max_length=8)
    end_date: date | None = None

    _times = field_validator("times")(lambda cls, v: v if v is None else PrescriptionIn.valid_times(v))


class StopIn(Input):
    reason: str = Field(default="", max_length=300)


class AppointmentIn(Input):
    title: str = Field(min_length=1, max_length=200)
    start: datetime
    duration_minutes: int = Field(default=60, ge=10, le=600)
    location: str = Field(default="", max_length=1000)
    notes: str = Field(default="", max_length=2000)
    needs_escort: bool = True
    importance: Literal["MEDIUM", "HIGH", "CRITICAL"] = "HIGH"

    @field_validator("start")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None: raise ValueError("start must include a timezone offset")
        return value


class MainCaretakerIn(Input):
    caregiver_id: uuid.UUID


def _current_user(request: Request, db: Session = Depends(get_db)):
    from app.main import current_user
    return current_user(request, db)


def _member(db, user, patient_id):
    return require_patient_access(db, user, patient_id, "patient:read")


def _professional(db, user, patient_id):
    patient, member = _member(db, user, patient_id)
    if user.role != Role.PROFESSIONAL or member.team_role != TeamRole.PROFESSIONAL:
        raise HTTPException(403, "Only a healthcare professional on this care team can prescribe or schedule")
    return patient, member


def _history(db, user, patient_id, event, entity_type, entity_id, summary):
    db.add(ActivityHistory(actor_user_id=user.id, patient_id=patient_id, event_type=event, entity_type=entity_type, entity_id=str(entity_id), summary=summary[:500], payload={}, request_id=""))


def _utc(value):
    """Always send UTC with an offset; SQLite returns naive values that browsers would read as local time."""
    if value is None: return None
    from datetime import UTC
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _prescription_dict(db, p: Prescription) -> dict:
    upcoming = db.scalars(select(CareActivity).where(CareActivity.source == "PRESCRIPTION", CareActivity.source_id == p.id, CareActivity.lifecycle_status == "SCHEDULED")
                          .order_by(CareActivity.scheduled_start).limit(1)).first()
    return {"id": p.id, "patient_id": p.patient_id, "medicine": p.medicine, "dose": p.dose, "instructions": p.instructions, "times": p.times,
            "start_date": p.start_date, "end_date": p.end_date, "status": p.status, "prescribed_by": p.prescribed_by, "created_at": _utc(p.created_at),
            "stopped_at": _utc(p.stopped_at), "stop_reason": p.stop_reason, "next_dose_at": _utc(upcoming.scheduled_start) if upcoming else None}


def _appointment_dict(a: CareActivity) -> dict:
    return {"id": a.id, "patient_id": a.patient_id, "title": a.title, "start": _utc(a.scheduled_start), "end": _utc(a.scheduled_end), "location": a.location_note,
            "notes": a.description, "needs_escort": a.requires_caregiver, "importance": a.importance, "status": care_status(a), "created_by": a.created_by}


@router.get("/patients/{patient_id}/prescriptions")
def list_prescriptions(patient_id: uuid.UUID, status: Literal["active", "all"] = "active", user=Depends(_current_user), db: Session = Depends(get_db)):
    patient, _ = _member(db, user, patient_id)
    query = select(Prescription).where(Prescription.patient_id == patient.id)
    if status == "active": query = query.where(Prescription.status == "ACTIVE")
    return {"items": [_prescription_dict(db, p) for p in db.scalars(query.order_by(Prescription.created_at.desc()))]}


@router.post("/patients/{patient_id}/prescriptions", status_code=201)
def create_prescription(patient_id: uuid.UUID, body: PrescriptionIn, user=Depends(_current_user), db: Session = Depends(get_db)):
    patient, _ = _professional(db, user, patient_id)
    p = Prescription(id=uuid.uuid4(), patient_id=patient.id, medicine=body.medicine.strip(), dose=body.dose.strip(), instructions=body.instructions.strip(),
                     times=body.times, start_date=body.start_date, end_date=body.end_date, status="ACTIVE", prescribed_by=user.id)
    db.add(p); db.flush()
    created = feeds.generate_doses(db, p, actor_id=user.id)
    _history(db, user, patient.id, "prescription.created", "prescription", p.id, f"{user.name} prescribed {p.medicine} {p.dose} at {', '.join(p.times)}")
    reassess(db, [patient.id], TriggerEvent.ACTIVITY_ADDED, {"prescription_id": str(p.id)}); db.commit()
    return {**_prescription_dict(db, p), "doses_created": created}


def _own_prescription(db, user, prescription_id) -> Prescription:
    p = db.get(Prescription, prescription_id)
    if not p: raise HTTPException(404, "Prescription not found")
    _professional(db, user, p.patient_id)
    return p


@router.patch("/prescriptions/{prescription_id}")
def update_prescription(prescription_id: uuid.UUID, body: PrescriptionPatch, user=Depends(_current_user), db: Session = Depends(get_db)):
    p = _own_prescription(db, user, prescription_id)
    if p.status != "ACTIVE": raise HTTPException(409, "This prescription was stopped")
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if getattr(p, k) != v}
    if "end_date" in changes and changes["end_date"] is not None and changes["end_date"] < p.start_date: raise HTTPException(422, "end_date must be on or after start_date")
    for key, value in changes.items(): setattr(p, key, value)
    p.updated_at = now()
    if {"times", "end_date"} & set(changes):
        # The timetable changed: replace future doses. Otherwise keep them (and their caretakers) and update in place.
        cancelled = feeds.cancel_future_doses(db, p, "Prescription changed"); db.flush()
        created = feeds.generate_doses(db, p, actor_id=user.id)
    else:
        cancelled, created = 0, 0
        feeds.refresh_future_doses(db, p)
    _history(db, user, p.patient_id, "prescription.updated", "prescription", p.id, f"{user.name} changed {p.medicine}: {', '.join(sorted(changes)) or 'no changes'}")
    reassess(db, [p.patient_id], TriggerEvent.ACTIVITY_RESCHEDULED, {"prescription_id": str(p.id)}); db.commit()
    return {**_prescription_dict(db, p), "doses_cancelled": cancelled, "doses_created": created}


@router.post("/prescriptions/{prescription_id}/stop")
def stop_prescription(prescription_id: uuid.UUID, body: StopIn | None = None, user=Depends(_current_user), db: Session = Depends(get_db)):
    p = _own_prescription(db, user, prescription_id)
    if p.status == "STOPPED": return _prescription_dict(db, p)
    p.status, p.stopped_at, p.stop_reason = "STOPPED", now(), (body.reason if body else "").strip()
    cancelled = feeds.cancel_future_doses(db, p, "Prescription stopped")
    _history(db, user, p.patient_id, "prescription.stopped", "prescription", p.id, f"{user.name} stopped {p.medicine}" + (f": {p.stop_reason}" if p.stop_reason else ""))
    reassess(db, [p.patient_id], TriggerEvent.ACTIVITY_RESCHEDULED, {"prescription_id": str(p.id)}); db.commit()
    return {**_prescription_dict(db, p), "doses_cancelled": cancelled}


@router.get("/patients/{patient_id}/appointments")
def list_appointments(patient_id: uuid.UUID, include_past: bool = False, user=Depends(_current_user), db: Session = Depends(get_db)):
    patient, _ = _member(db, user, patient_id)
    query = select(CareActivity).where(CareActivity.patient_id == patient.id, CareActivity.category == "APPOINTMENT")
    if user.role == Role.CARETAKER:  # like the care plan: caretakers see the appointments they escort
        from app.models import Caregiver, CareAssignment
        own = select(CareAssignment.activity_id).join(Caregiver, Caregiver.id == CareAssignment.caregiver_id).where(Caregiver.user_id == user.id, CareAssignment.status.in_(feeds.ACTIVE))
        query = query.where(CareActivity.id.in_(own))
    if not include_past: query = query.where(CareActivity.scheduled_start >= now(), CareActivity.lifecycle_status == "SCHEDULED")
    return {"items": [_appointment_dict(a) for a in db.scalars(query.order_by(CareActivity.scheduled_start).limit(200))]}


@router.post("/patients/{patient_id}/appointments", status_code=201)
def create_appointment(patient_id: uuid.UUID, body: AppointmentIn, user=Depends(_current_user), db: Session = Depends(get_db)):
    patient, _ = _professional(db, user, patient_id)
    if body.start <= now(): raise HTTPException(422, "Appointments must be in the future")
    a = feeds.create_appointment(db, patient, title=body.title.strip(), start=body.start, minutes=body.duration_minutes, location=body.location.strip(),
                                 notes=body.notes.strip(), needs_escort=body.needs_escort, importance=body.importance, actor_id=user.id)
    reassess(db, [patient.id], TriggerEvent.ACTIVITY_ADDED, {"activity_id": str(a.id)}); db.commit()
    return _appointment_dict(a)


@router.post("/appointments/{activity_id}/cancel")
def cancel_appointment(activity_id: uuid.UUID, body: StopIn | None = None, user=Depends(_current_user), db: Session = Depends(get_db)):
    a = db.get(CareActivity, activity_id)
    if not a or a.category != "APPOINTMENT": raise HTTPException(404, "Appointment not found")
    _professional(db, user, a.patient_id)
    if a.lifecycle_status == "SCHEDULED":
        feeds.cancel_activity(db, a, (body.reason if body else "") or "Cancelled by the hospital")
        _history(db, user, a.patient_id, "appointment.cancelled", "care_activity", a.id, f"{user.name} cancelled {a.title}")
        reassess(db, [a.patient_id], TriggerEvent.ACTIVITY_RESCHEDULED, {"activity_id": str(a.id)}); db.commit()
    return _appointment_dict(a)


@router.get("/patients/{patient_id}/adherence")
def adherence(patient_id: uuid.UUID, days: int = Query(7, ge=1, le=90), user=Depends(_current_user), db: Session = Depends(get_db)):
    patient, member = _member(db, user, patient_id)
    if member.team_role not in (TeamRole.PROFESSIONAL, TeamRole.PRIMARY_CONTACT): raise HTTPException(403, "Adherence is shared with the primary contact and healthcare professionals")
    return feeds.adherence(db, patient.id, days)


@router.put("/patients/{patient_id}/main-caretaker")
def set_main_caretaker(patient_id: uuid.UUID, body: MainCaretakerIn, user=Depends(_current_user), db: Session = Depends(get_db)):
    patient, member = _member(db, user, patient_id)
    if user.role != Role.PRIMARY_CONTACT or member.team_role != TeamRole.PRIMARY_CONTACT: raise HTTPException(403, "Primary contact permission required")
    links = db.scalars(select(CaregiverPatientLink).where(CaregiverPatientLink.patient_id == patient.id)).all()
    target = next((l for l in links if l.caregiver_id == body.caregiver_id), None)
    if not target: raise HTTPException(404, "That caretaker is not on this care team")
    from app.models import Caregiver
    if not db.get(Caregiver, target.caregiver_id).is_active: raise HTTPException(409, "That care profile is inactive")
    for link in links: link.is_main_caretaker = link is target
    db.flush()
    # Hand the main caretaker any upcoming feed activities that nobody holds yet.
    assigned = 0
    for activity in db.scalars(select(CareActivity).where(CareActivity.patient_id == patient.id, CareActivity.lifecycle_status == "SCHEDULED",
                                                          CareActivity.source.in_(("PRESCRIPTION", "APPOINTMENT")), CareActivity.scheduled_start > now())):
        assigned += feeds.auto_assign(db, activity, user.id) is not None
    _history(db, user, patient.id, "care_team.main_caretaker", "caregiver", body.caregiver_id, f"Main caretaker set; {assigned} upcoming activities assigned")
    reassess(db, [patient.id], TriggerEvent.ASSIGNMENT_ADDED, {"main_caretaker": str(body.caregiver_id)}); db.commit()
    return {"caregiver_id": body.caregiver_id, "assigned": assigned}
