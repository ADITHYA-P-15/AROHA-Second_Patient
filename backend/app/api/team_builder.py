"""Team builder (flag `team_builder`): care preferences, ranked directory matches, and hire requests.

Primary contacts set preferences, see matches and send requests. The caretaker a request is sent to accepts or declines.
Request responses never carry phone, email or notes; after acceptance the existing care-team payloads show them.
"""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.features import feature_required
from app.core.permissions import require_patient_access
from app.models import Caregiver, HireRequest, Role, TeamRole
from app.services import team_builder as svc

router = APIRouter(prefix="/api/v1", tags=["team builder"], dependencies=[Depends(feature_required("team_builder"))])
SUPPORT = {"TRANSPORT", "MEDICATION_ASSIST", "PRESCRIPTION_PICKUP", "DAILY_ASSIST", "MOBILITY_ASSIST", "LAB_ESCORT", "SUPPLIES", "APPOINTMENT_ESCORT"}


def _current_user(request: Request, db: Session = Depends(get_db)):
    from app.main import current_user
    return current_user(request, db)


def _primary_contact(db, user, pid):
    patient, member = require_patient_access(db, user, pid, "patient:read")
    if user.role != Role.PRIMARY_CONTACT or member.team_role != TeamRole.PRIMARY_CONTACT: raise HTTPException(403, "Primary contact permission required")
    return patient


class PreferencesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gender: Literal["FEMALE", "MALE", "NON_BINARY"] | None = None
    gender_mode: Literal["HARD", "SOFT"] = "SOFT"
    languages: list[str] = Field(default_factory=list, max_length=6)
    city: str = Field(default="", max_length=80)
    sector_code: Literal["NORTH", "SOUTH", "EAST", "WEST"] | None = None
    min_rating: float | None = Field(default=None, ge=0, le=100)
    capabilities: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("languages")
    @classmethod
    def _languages(cls, value):
        out = []
        for item in value:
            item = item.strip()
            if not item or len(item) > 40 or not all(ch.isalpha() or ch in " -" for ch in item): raise ValueError("Each language is a word or two of letters")
            if item.lower() not in {x.lower() for x in out}: out.append(item[:1].upper() + item[1:])
        return out

    @field_validator("capabilities")
    @classmethod
    def _caps(cls, value):
        if not set(value) <= SUPPORT: raise ValueError("Unknown capability")
        return sorted(set(value))

    @field_validator("city")
    @classmethod
    def _city(cls, value):
        value = value.strip()
        if value and not all(ch.isalnum() or ch in " .,'()-" for ch in value): raise ValueError("Use letters, numbers and spaces")
        return value


class HireIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    caregiver_id: uuid.UUID
    intended_role: Literal["MAIN", "BACKUP"] = "BACKUP"
    message: str = Field(default="", max_length=300)


class DeclineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="", max_length=300)


def _raise(exc: svc.HireError):
    raise HTTPException(exc.status, str(exc)) from None


@router.get("/patients/{pid}/care-preferences")
def get_preferences(pid: uuid.UUID, user=Depends(_current_user), db: Session = Depends(get_db)):
    _, member = require_patient_access(db, user, pid, "patient:read")
    if member.team_role == TeamRole.CARETAKER: raise HTTPException(403, "Permission denied")
    return svc.preference_dict(svc.preferences(db, pid))


@router.put("/patients/{pid}/care-preferences")
def put_preferences(pid: uuid.UUID, body: PreferencesIn, user=Depends(_current_user), db: Session = Depends(get_db)):
    _primary_contact(db, user, pid)
    values = body.model_dump()
    if values["gender"] is None: values["gender_mode"] = "SOFT"
    svc.save_preferences(db, pid, values, user)
    from app.services.command_center import reconcile_patient
    reconcile_patient(db, pid)
    db.commit()
    return svc.preference_dict(svc.preferences(db, pid))


@router.get("/patients/{pid}/team-matches")
def team_matches(pid: uuid.UUID, limit: int = Query(20, ge=1, le=50), min_agency_rating: float | None = Query(None, ge=1, le=5),
                 user=Depends(_current_user), db: Session = Depends(get_db)):
    _primary_contact(db, user, pid)
    pending = {str(c) for c in db.scalars(select(HireRequest.caregiver_id).where(HireRequest.patient_id == pid, HireRequest.status == "PENDING"))}
    items = svc.matches(db, pid, limit=limit, min_agency_rating=min_agency_rating)
    for m in items: m["request_pending"] = m["caregiver_id"] in pending
    return {"items": items, "preferences": svc.preference_dict(svc.preferences(db, pid))}


@router.post("/patients/{pid}/hire-requests", status_code=201)
def send_request(pid: uuid.UUID, body: HireIn, response: Response, user=Depends(_current_user), db: Session = Depends(get_db),
                 idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=80)):
    _primary_contact(db, user, pid)
    try:
        row, created = svc.create(db, user, pid, body.caregiver_id, role=body.intended_role, message=body.message, idempotency_key=(idempotency_key or "").strip() or None)
        db.commit()
    except svc.HireError as exc:
        db.rollback(); _raise(exc)
    except IntegrityError:
        # A concurrent duplicate (same key or same open pair) won the unique index.
        db.rollback()
        raise HTTPException(409, "A request to this caretaker for this patient is already waiting") from None
    if not created: response.status_code = 200
    return svc.request_dict(db, row, viewer=user)


@router.get("/patients/{pid}/hire-requests")
def patient_requests(pid: uuid.UUID, user=Depends(_current_user), db: Session = Depends(get_db)):
    _primary_contact(db, user, pid)
    rows = db.scalars(select(HireRequest).where(HireRequest.patient_id == pid).order_by(HireRequest.created_at.desc(), HireRequest.id).limit(50)).all()
    return {"items": [svc.request_dict(db, r, viewer=user) for r in rows]}


@router.get("/hire-requests/mine")
def my_requests(user=Depends(_current_user), db: Session = Depends(get_db)):
    if user.role != Role.CARETAKER: raise HTTPException(403, "Only caretakers receive hire requests")
    cg = db.scalar(select(Caregiver).where(Caregiver.user_id == user.id))
    if not cg: return {"items": []}
    rows = db.scalars(select(HireRequest).where(HireRequest.caregiver_id == cg.id).order_by(HireRequest.created_at.desc(), HireRequest.id).limit(50)).all()
    return {"items": [svc.request_dict(db, r, viewer=user) for r in rows]}


def _request(db, rid) -> HireRequest:
    row = db.get(HireRequest, rid)
    if not row: raise HTTPException(404, "Hire request not found")
    return row


@router.post("/hire-requests/{rid}/accept")
def accept(rid: uuid.UUID, user=Depends(_current_user), db: Session = Depends(get_db)):
    row = _request(db, rid)
    try: svc.accept(db, row, user); db.commit()
    except svc.HireError as exc: db.commit() if row.status == "EXPIRED" else db.rollback(); _raise(exc)
    return svc.request_dict(db, row, viewer=user)


@router.post("/hire-requests/{rid}/decline")
def decline(rid: uuid.UUID, body: DeclineIn | None = None, user=Depends(_current_user), db: Session = Depends(get_db)):
    row = _request(db, rid)
    try: svc.decline(db, row, user, body.reason if body else ""); db.commit()
    except svc.HireError as exc: db.rollback(); _raise(exc)
    return svc.request_dict(db, row, viewer=user)


@router.post("/hire-requests/{rid}/withdraw")
def withdraw(rid: uuid.UUID, user=Depends(_current_user), db: Session = Depends(get_db)):
    row = _request(db, rid)
    try: svc.withdraw(db, row, user); db.commit()
    except svc.HireError as exc: db.rollback(); _raise(exc)
    return svc.request_dict(db, row, viewer=user)
