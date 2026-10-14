from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import now, to_utc
from app.core.db import get_db
from app.core.permissions import require_patient_access
from app.engine.availability import Window, effective_windows, is_available_for
from app.engine.workload import buffered_window, overlaps_for, workload
from app.models import (ActivityDependency, ActivityHistory, AvailabilityOverride, CareActivity, CareAssignment, Caregiver, CaregiverPatientLink, CaregiverWeeklySchedule, CareTeamMember, Patient, PatientSupportNeed, Role, TeamRole, User, Incident, IncidentEvent)
from app.services.reassess import TriggerEvent, reassess

router = APIRouter(prefix="/api/v1", tags=["core domain"])
SUPPORT = {"TRANSPORT", "MEDICATION_ASSIST", "PRESCRIPTION_PICKUP", "DAILY_ASSIST", "MOBILITY_ASSIST", "LAB_ESCORT", "SUPPLIES", "CLINICAL_VISIT", "APPOINTMENT_ESCORT"}
KINDS = {"FAMILY", "HOUSEHELP", "NURSE", "NEIGHBOUR", "VOLUNTEER", "OTHER"}
CATEGORIES = {"APPOINTMENT", "TRANSPORT", "PRESCRIPTION", "MEDICATION", "FOLLOW_UP", "DAILY_ROUTINE", "MOBILITY", "LAB", "SUPPLIES", "POST_APPOINTMENT", "OTHER"}
TERMINAL = {"DECLINED", "REJECTED", "CANCELLED", "SUPERSEDED"}
ACTIVE = {"PROPOSED", "AWAITING_CONFIRMATION", "CONFIRMED"}


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PatientCorePatch(Input):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    birth_year: int | None = Field(default=None, ge=1900, le=2100)
    care_notes: str | None = Field(default=None, max_length=5000)
    clinical_notes: str | None = Field(default=None, max_length=5000)
    mobility_level: Literal["INDEPENDENT", "NEEDS_AID", "WHEELCHAIR", "BEDBOUND"] | None = None
    language_pref: str | None = Field(default=None, max_length=8)

    @model_validator(mode="after")
    def valid_nulls(self):
        for name in ("name", "care_notes", "clinical_notes", "mobility_level", "language_pref"):
            if name in self.model_fields_set and getattr(self, name) is None: raise ValueError(f"{name} cannot be null")
        return self


class SupportNeedIn(Input):
    support_code: str
    notes: str = Field(default="", max_length=2000)


class CaregiverLinkIn(Input):
    relationship: str = Field(default="", max_length=120)
    is_designated_backup: bool = False


class CancelIn(Input):
    reason: str = Field(default="", max_length=1000)


class DependencyIn(Input):
    depends_on_activity_id: uuid.UUID


class CaregiverIn(Input):
    name: str = Field(min_length=1, max_length=160)
    kind: str
    relationship: str = Field(default="", max_length=120)
    user_id: uuid.UUID | None = None
    phone: str | None = Field(default=None, max_length=40)
    capabilities: list[str] = Field(default_factory=list)
    max_activities_per_day: int = Field(default=3, ge=0, le=30)
    max_hours_per_week: float = Field(default=40, ge=0, le=168)
    notes: str = Field(default="", max_length=3000)
    is_designated_backup: bool = False

    @model_validator(mode="after")
    def valid_codes(self):
        if self.kind not in KINDS or not set(self.capabilities) <= SUPPORT:
            raise ValueError("Unknown caregiver kind or support capability")
        return self


class CaregiverPatch(Input):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    kind: str | None = None
    phone: str | None = Field(default=None, max_length=40)
    capabilities: list[str] | None = None
    max_activities_per_day: int | None = Field(default=None, ge=0, le=30)
    max_hours_per_week: float | None = Field(default=None, ge=0, le=168)
    notes: str | None = Field(default=None, max_length=3000)
    is_active: bool | None = None

    @model_validator(mode="after")
    def valid_fields(self):
        if self.kind is not None and self.kind not in KINDS: raise ValueError("Unknown caregiver kind")
        if self.capabilities is not None and not set(self.capabilities) <= SUPPORT: raise ValueError("Unknown capability")
        for name in ("name", "kind", "capabilities", "max_activities_per_day", "max_hours_per_week", "notes", "is_active"):
            if name in self.model_fields_set and getattr(self, name) is None: raise ValueError(f"{name} cannot be null")
        return self


class ScheduleIn(Input):
    windows: list[dict] = Field(max_length=80)


class OverrideIn(Input):
    start_at: datetime
    end_at: datetime
    status: Literal["UNAVAILABLE", "AVAILABLE"]
    reason: Literal["WORK", "ILLNESS", "TRAVEL", "PERSONAL", "EMERGENCY", "OTHER"]
    note: str = Field(default="", max_length=1000)

    @field_validator("start_at", "end_at")
    @classmethod
    def aware(cls, v):
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("Datetime must include a timezone offset")
        return v


class ActivityIn(Input):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    category: str = "OTHER"
    scheduled_start: datetime
    scheduled_end: datetime
    deadline: datetime | None = None
    importance: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    requires_caregiver: bool = True
    required_support: list[str] = Field(default_factory=list)
    buffer_before_min: int = Field(default=0, ge=0, le=1440)
    buffer_after_min: int = Field(default=0, ge=0, le=1440)
    location_note: str = Field(default="", max_length=1000)

    @field_validator("scheduled_start", "scheduled_end", "deadline")
    @classmethod
    def aware(cls, v):
        if v is not None and (v.tzinfo is None or v.utcoffset() is None):
            raise ValueError("Datetime must include a timezone offset")
        return v

    @model_validator(mode="after")
    def valid_activity(self):
        if self.category not in CATEGORIES or not set(self.required_support) <= SUPPORT:
            raise ValueError("Unknown category or support code")
        if self.scheduled_end <= self.scheduled_start:
            raise ValueError("scheduled_end must be after scheduled_start")
        if self.requires_caregiver and not self.required_support:
            raise ValueError("required_support is required when caregiver support is required")
        if self.deadline and self.deadline < self.scheduled_start:
            raise ValueError("deadline must be at or after scheduled_start")
        return self


class ActivityPatch(Input):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    category: str | None = None
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    deadline: datetime | None = None
    importance: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] | None = None
    requires_caregiver: bool | None = None
    required_support: list[str] | None = None
    buffer_before_min: int | None = Field(default=None, ge=0, le=1440)
    buffer_after_min: int | None = Field(default=None, ge=0, le=1440)
    location_note: str | None = Field(default=None, max_length=1000)

    @field_validator("scheduled_start", "scheduled_end", "deadline")
    @classmethod
    def aware(cls, v):
        if v is not None and (v.tzinfo is None or v.utcoffset() is None): raise ValueError("Datetime must include a timezone offset")
        return v


class AssignmentIn(Input):
    caregiver_id: uuid.UUID
    role: Literal["PRIMARY", "BACKUP"] = "PRIMARY"
    confirm_now: bool = False
    scope: Literal["THIS", "FUTURE_IN_SERIES"] = "THIS"


class SeriesIn(ActivityIn):
    recurrence: Literal["DAILY", "WEEKLY"]
    interval: int = Field(default=1, ge=1, le=52)
    by_weekday: list[int] | None = Field(default=None, max_length=7)
    count: int | None = Field(default=None, ge=1, le=60)
    until: datetime | None = None

    @model_validator(mode="after")
    def bound_series(self):
        if (self.count is None) == (self.until is None):
            raise ValueError("Provide exactly one of count or until")
        if self.until and (self.until.tzinfo is None or self.until - self.scheduled_start > timedelta(days=90)):
            raise ValueError("until must include timezone and be within 90 days")
        if self.by_weekday and any(type(x) is not int or not 0 <= x <= 6 for x in self.by_weekday):
            raise ValueError("by_weekday values must be between 0 and 6")
        return self


class DeclineIn(Input):
    reason: str = Field(min_length=1, max_length=1000)


class ReasonIn(Input):
    reason: str = Field(default="", max_length=1000)


def _member(db, user, pid, write=False):
    patient, member = require_patient_access(db, user, pid, "patient:update" if write else "patient:read")
    if write and user.role != Role.ADMIN and (member is None or member.team_role != TeamRole.COORDINATOR):
        raise HTTPException(403, "Coordinator permission required")
    return patient, member


def _is_coordinator(db, user, pid):
    if user.role == Role.ADMIN: return True
    try:
        member = _member(db, user, pid)[1]
    except HTTPException:
        return False
    return bool(member and member.team_role == TeamRole.COORDINATOR)


def _linked_patient_ids(db, caregiver_id):
    return list(db.scalars(select(CaregiverPatientLink.patient_id).where(CaregiverPatientLink.caregiver_id == caregiver_id)).all())


def _as_aware(value):
    from datetime import UTC
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _can_edit_caregiver(db, user, cg):
    if user.role == Role.ADMIN:
        return True
    if cg.user_id == user.id:
        return True
    return any(_is_coordinator(db, user, pid) for pid in _linked_patient_ids(db, cg.id))


def _caregiver_dict(db, user, cg, pid=None):
    links = db.scalars(select(CaregiverPatientLink).where(CaregiverPatientLink.caregiver_id == cg.id)).all()
    link = next((x for x in links if x.patient_id == pid), None)
    show_phone = user.role == Role.ADMIN or cg.user_id == user.id or (pid is not None and _is_coordinator(db, user, pid))
    return {"id": cg.id, "user_id": cg.user_id, "name": cg.name, "kind": cg.kind, "phone": cg.phone if show_phone else None, "capabilities": cg.capabilities, "max_activities_per_day": cg.max_activities_per_day, "max_hours_per_week": cg.max_hours_per_week, "is_active": cg.is_active, "notes": cg.notes, "relationship": link.relationship if link else "", "is_designated_backup": link.is_designated_backup if link else False, "linked_patient_count": len(links), "is_synthetic": cg.is_synthetic}


def _activity_dict(db, user, a):
    assignments = db.scalars(select(CareAssignment).where(CareAssignment.activity_id == a.id)).all()
    primary_confirmed = any(x.role == "PRIMARY" and x.status == "CONFIRMED" for x in assignments)
    member = db.scalar(select(CareTeamMember).where(CareTeamMember.patient_id == a.patient_id, CareTeamMember.user_id == user.id))
    permissions = ["plan:read"]
    if user.role == Role.ADMIN or (member and member.team_role == TeamRole.COORDINATOR): permissions += ["plan:manage", "assignment:manage"]
    if user.role == Role.DOCTOR: permissions += ["clinical_notes:read"]
    if user.role in (Role.FAMILY, Role.HOUSEHELP, Role.NURSE): permissions += ["availability:edit_own"]
    own_caregiver = db.scalar(select(Caregiver.id).where(Caregiver.user_id == user.id))
    if own_caregiver and any(x.caregiver_id == own_caregiver and x.status in ACTIVE for x in assignments): permissions.append("assignment:respond_own")
    if user.role in (Role.HOUSEHELP, Role.NURSE):
        own_id = db.scalar(select(Caregiver.id).where(Caregiver.user_id == user.id))
        if not own_id or not db.scalar(select(CareAssignment.id).where(CareAssignment.activity_id == a.id, CareAssignment.caregiver_id == own_id, CareAssignment.status.in_(ACTIVE))):
            raise HTTPException(403, "This activity is not assigned to you")
    assignment_rows = []
    for item in assignments:
        caregiver = db.get(Caregiver, item.caregiver_id)
        if user.role in (Role.HOUSEHELP, Role.NURSE) and caregiver.user_id != user.id: continue
        assignment_rows.append({"id": item.id, "caregiver_id": item.caregiver_id, "caregiver_name": caregiver.name, "role": item.role, "status": item.status, "confirmed_at": item.confirmed_at, "is_mine": caregiver.user_id == user.id})
    return {"id": a.id, "patient_id": a.patient_id, "series_id": a.series_id, "title": a.title, "description": a.description, "category": a.category, "scheduled_start": to_utc(_as_aware(a.scheduled_start)), "scheduled_end": to_utc(_as_aware(a.scheduled_end)), "deadline": to_utc(_as_aware(a.deadline)) if a.deadline else None, "importance": a.importance, "requires_caregiver": a.requires_caregiver, "required_support": a.required_support, "buffer_before_min": a.buffer_before_min, "buffer_after_min": a.buffer_after_min, "location_note": a.location_note, "lifecycle_status": a.lifecycle_status, "coverage_status": a.coverage_status, "is_synthetic": a.is_synthetic, "assignments": assignment_rows, "preliminary_support_status": "Support confirmed" if primary_confirmed else "Not confirmed", "preliminary_label": "Preliminary — full coverage analysis arrives with the care-gap engine", "my_permissions": permissions}


def _history(db, user, request, pid, event, entity, entity_id, summary, payload=None):
    db.add(ActivityHistory(actor_user_id=user.id, patient_id=pid, event_type=event, entity_type=entity, entity_id=str(entity_id), summary=summary, payload=payload or {}, request_id=request.state.request_id))


def _warnings(db, activity, caregiver):
    warnings = []
    if not set(activity.required_support or []) <= set(caregiver.capabilities or []):
        warnings.append({"code": "CAPABILITY_MISMATCH", "message": "Caregiver may not have all required capabilities", "details": {"required": activity.required_support, "capabilities": caregiver.capabilities}})
    if not is_available_for(caregiver, buffered_window(activity)).available:
        warnings.append({"code": "CAREGIVER_UNAVAILABLE", "message": "Caregiver is not available for the full activity window", "details": {}})
    rows = db.execute(select(CareAssignment, CareActivity).join(CareActivity).where(CareAssignment.caregiver_id == caregiver.id, CareAssignment.status.in_(ACTIVE), CareAssignment.role == "PRIMARY")).all()
    conflicts = [other for _, other in rows if other.id != activity.id and other.lifecycle_status == "SCHEDULED" and __import__("app.engine.workload", fromlist=["overlap"]).overlap(buffered_window(activity), buffered_window(other))]
    if conflicts:
        warnings.append({"code": "OVERLAPPING_COMMITMENT", "message": "Caregiver has an overlapping commitment", "details": {"count": len(conflicts)}})
    all_assignments = db.execute(select(CareAssignment, CareActivity).join(CareActivity).where(CareAssignment.caregiver_id == caregiver.id)).all()
    load = workload(all_assignments, caregiver.id)
    target = buffered_window(activity)
    day = target.start.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Kolkata")).date().isoformat()
    week_dt = target.start.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Kolkata"))
    week = f"{week_dt.isocalendar().year}-W{week_dt.isocalendar().week:02d}"
    day_data = load["by_day"].get(day, {})
    week_data = load["by_week"].get(week, {})
    if day_data.get("confirmed", 0) + day_data.get("pending", 0) > caregiver.max_activities_per_day:
        warnings.append({"code": "DAILY_LIMIT_EXCEEDED", "message": "Caregiver may exceed their daily activity limit", "details": {"limit": caregiver.max_activities_per_day}})
    if week_data.get("confirmed_hours", 0) + week_data.get("pending_hours", 0) > caregiver.max_hours_per_week:
        warnings.append({"code": "WEEKLY_LIMIT_EXCEEDED", "message": "Caregiver may exceed their weekly hours limit", "details": {"limit_hours": caregiver.max_hours_per_week}})
    if activity.deadline and (_as_aware(activity.deadline) - now()).total_seconds() < 86400:
        warnings.append({"code": "DEADLINE_NEAR", "message": "Activity deadline is less than 24 hours away", "details": {}})
    return warnings


@router.get("/patients/{pid}")
def patient_extended(pid: uuid.UUID, user: User = Depends(__import__("app.main", fromlist=["current_user"]).current_user), db: Session = Depends(get_db)):
    patient, member = _member(db, user, pid)
    show_clinical = user.role == Role.ADMIN or user.role in (Role.DOCTOR, Role.NURSE) or user.role == Role.PATIENT and member and member.team_role == TeamRole.PATIENT_SELF or user.role == Role.FAMILY and member and member.team_role == TeamRole.COORDINATOR
    base = {"id": patient.id, "name": patient.name, "birth_year": patient.birth_year, "care_notes": patient.care_notes, "clinical_notes": patient.clinical_notes if show_clinical else None, "mobility_level": patient.mobility_level, "language_pref": patient.language_pref, "continuity_status": patient.continuity_status}
    base["support_needs"] = [{"id": x.id, "support_code": x.support_code, "notes": x.notes} for x in db.scalars(select(PatientSupportNeed).where(PatientSupportNeed.patient_id == pid))]
    base["my_permissions"] = ["plan:read"] + (["plan:manage", "network:manage"] if user.role == Role.ADMIN or member and member.team_role == TeamRole.COORDINATOR else [])
    return base


@router.patch("/patients/{pid}")
def patient_patch(pid: uuid.UUID, body: PatientCorePatch, request: Request, user: User = Depends(__import__("app.main", fromlist=["current_user"]).current_user), db: Session = Depends(get_db)):
    patient, _ = _member(db, user, pid, True)
    values = body.model_dump(exclude_unset=True)
    for key, value in values.items(): setattr(patient, key, value)
    patient.updated_at = now(); _history(db, user, request, pid, "patient.updated", "patient", pid, "Patient profile updated")
    reassess(db, [pid], TriggerEvent.ACTIVITY_RESCHEDULED, {"entity": "patient"}); db.commit()
    return patient_extended(pid, user, db)


@router.put("/patients/{pid}/support-needs")
def put_support_needs(pid: uuid.UUID, body: list[SupportNeedIn], request: Request, user: User = Depends(__import__("app.main", fromlist=["current_user"]).current_user), db: Session = Depends(get_db)):
    _member(db, user, pid, True)
    if any(x.support_code not in SUPPORT for x in body) or len({x.support_code for x in body}) != len(body): raise HTTPException(422, "Invalid or duplicate support need")
    db.query(PatientSupportNeed).filter_by(patient_id=pid).delete()
    for x in body: db.add(PatientSupportNeed(patient_id=pid, support_code=x.support_code, notes=x.notes))
    _history(db, user, request, pid, "patient.support_needs_updated", "patient", pid, "Support needs updated")
    reassess(db, [pid], TriggerEvent.ACTIVITY_RESCHEDULED, {"entity": "support_needs"}); db.commit()
    return {"items": [x.model_dump() for x in body]}


@router.get("/patients/{pid}/overview")
def overview(pid: uuid.UUID, user: User = Depends(__import__("app.main", fromlist=["current_user"]).current_user), db: Session = Depends(get_db)):
    _member(db, user, pid)
    start = now(); end = start + timedelta(days=7)
    activities = db.scalars(select(CareActivity).where(CareActivity.patient_id == pid, CareActivity.scheduled_start >= start, CareActivity.scheduled_start < end, CareActivity.lifecycle_status == "SCHEDULED").order_by(CareActivity.scheduled_start)).all()
    caregivers = db.scalars(select(Caregiver).join(CaregiverPatientLink).where(CaregiverPatientLink.patient_id == pid, Caregiver.is_active.is_(True))).all()
    events = db.scalars(select(ActivityHistory).where(ActivityHistory.patient_id == pid).order_by(ActivityHistory.occurred_at.desc()).limit(10)).all()
    unconfirmed = 0
    for a in activities:
        if not db.scalar(select(CareAssignment.id).where(CareAssignment.activity_id == a.id, CareAssignment.role == "PRIMARY", CareAssignment.status == "CONFIRMED")): unconfirmed += 1
    return {"upcoming_activities": [_activity_dict(db, user, x) for x in activities], "not_yet_confirmed_count": unconfirmed, "caregivers": [_caregiver_dict(db, user, c, pid) for c in caregivers], "recent_history": [{"event_type": e.event_type, "summary": e.summary, "occurred_at": e.occurred_at} for e in events]}


@router.get("/patients/{pid}/caregivers")
def list_caregivers(pid: uuid.UUID, user: User = Depends(__import__("app.main", fromlist=["current_user"]).current_user), db: Session = Depends(get_db)):
    _member(db, user, pid)
    rows = db.scalars(select(Caregiver).join(CaregiverPatientLink).where(CaregiverPatientLink.patient_id == pid).order_by(Caregiver.name)).all()
    if user.role in (Role.HOUSEHELP, Role.NURSE):
        rows = [cg for cg in rows if cg.user_id == user.id]
    return {"items": [_caregiver_dict(db, user, x, pid) for x in rows]}


@router.post("/patients/{pid}/caregivers", status_code=201)
def create_caregiver(pid: uuid.UUID, body: CaregiverIn, request: Request, user: User = Depends(__import__("app.main", fromlist=["current_user"]).current_user), db: Session = Depends(get_db)):
    _member(db, user, pid, True)
    if body.user_id:
        linked_user = db.get(User, body.user_id)
        if not linked_user: raise HTTPException(404, "Linked user not found")
        expected = {"FAMILY": Role.FAMILY, "HOUSEHELP": Role.HOUSEHELP, "NURSE": Role.NURSE}
        if body.kind in expected and linked_user.role != expected[body.kind]: raise HTTPException(422, "Caregiver kind and linked user role are incompatible")
        if db.scalar(select(Caregiver.id).where(Caregiver.user_id == body.user_id)): raise HTTPException(409, "User already has a caregiver profile")
    cg = Caregiver(user_id=body.user_id, name=body.name.strip(), kind=body.kind, phone=body.phone, capabilities=body.capabilities, max_activities_per_day=body.max_activities_per_day, max_hours_per_week=body.max_hours_per_week, notes=body.notes, created_by=user.id, is_synthetic=True)
    db.add(cg); db.flush(); link = CaregiverPatientLink(caregiver_id=cg.id, patient_id=pid, relationship=body.relationship, is_designated_backup=body.is_designated_backup); db.add(link)
    _history(db, user, request, pid, "caregiver.created", "caregiver", cg.id, "Caregiver added to network")
    reassess(db, [pid], TriggerEvent.ASSIGNMENT_ADDED, {"caregiver_id": str(cg.id)}); db.commit(); db.refresh(cg)
    return _caregiver_dict(db, user, cg, pid)


@router.post("/patients/{pid}/caregivers/{cid}/link", status_code=201)
def link_caregiver(pid: uuid.UUID, cid: uuid.UUID, body: CaregiverLinkIn, request: Request, user: User = Depends(__import__("app.main", fromlist=["current_user"]).current_user), db: Session = Depends(get_db)):
    _member(db, user, pid, True)
    cg = db.get(Caregiver, cid)
    if not cg: raise HTTPException(404, "Caregiver not found")
    if not _can_edit_caregiver(db, user, cg): raise HTTPException(404, "Caregiver not found")
    if db.scalar(select(CaregiverPatientLink).where(CaregiverPatientLink.patient_id == pid, CaregiverPatientLink.caregiver_id == cid)): raise HTTPException(409, "Caregiver already linked")
    link = CaregiverPatientLink(caregiver_id=cid, patient_id=pid, relationship=body.relationship, is_designated_backup=body.is_designated_backup); db.add(link)
    _history(db, user, request, pid, "caregiver.linked", "caregiver", cid, "Caregiver linked to patient")
    reassess(db, [*set(_linked_patient_ids(db, cid) + [pid])], TriggerEvent.ASSIGNMENT_ADDED, {"caregiver_id": str(cid)}); db.commit(); return {"status": "linked"}


@router.delete("/patients/{pid}/caregivers/{cid}/link")
def unlink_caregiver(pid: uuid.UUID, cid: uuid.UUID, request: Request, user: User = Depends(__import__("app.main", fromlist=["current_user"]).current_user), db: Session = Depends(get_db)):
    _member(db, user, pid, True)
    link = db.scalar(select(CaregiverPatientLink).where(CaregiverPatientLink.patient_id == pid, CaregiverPatientLink.caregiver_id == cid))
    if not link: raise HTTPException(404, "Caregiver link not found")
    active = db.execute(select(CareAssignment.id, CareActivity.title).join(CareActivity).where(CareAssignment.caregiver_id == cid, CareActivity.patient_id == pid, CareAssignment.status.in_(ACTIVE))).all()
    if active: raise HTTPException(409, "Caregiver has active assignments", detail={"assignments": [{"id": str(a), "title": t} for a, t in active]})
    affected = list(set(_linked_patient_ids(db, cid))); db.delete(link); _history(db, user, request, pid, "caregiver.unlinked", "caregiver", cid, "Caregiver unlinked")
    reassess(db, affected, TriggerEvent.ASSIGNMENT_REMOVED, {"caregiver_id": str(cid)}); db.commit(); return Response(status_code=204)


@router.get("/caregivers/{cid}")
def get_caregiver(cid: uuid.UUID, user: User = Depends(__import__("app.main", fromlist=["current_user"]).current_user), db: Session = Depends(get_db)):
    cg = db.get(Caregiver, cid)
    if not cg: raise HTTPException(404, "Caregiver not found")
    pids = _linked_patient_ids(db, cid)
    if not (user.role == Role.ADMIN or cg.user_id == user.id or any(_is_coordinator(db, user, p) for p in pids)): raise HTTPException(403, "Caregiver access denied")
    return _caregiver_dict(db, user, cg, next((p for p in pids if (user.role == Role.ADMIN or cg.user_id == user.id or _member(db, user, p)[1].team_role == TeamRole.COORDINATOR)), None))


@router.patch("/caregivers/{cid}")
def patch_caregiver(cid: uuid.UUID, body: CaregiverPatch, request: Request, user: User = Depends(__import__("app.main", fromlist=["current_user"]).current_user), db: Session = Depends(get_db)):
    cg = db.get(Caregiver, cid)
    if not cg: raise HTTPException(404, "Caregiver not found")
    if not _can_edit_caregiver(db, user, cg): raise HTTPException(403, "Permission denied")
    values = body.model_dump(exclude_unset=True)
    if values.get("kind") is not None and values["kind"] not in KINDS: raise HTTPException(422, "Unknown caregiver kind")
    if values.get("capabilities") is not None and not set(values["capabilities"]) <= SUPPORT: raise HTTPException(422, "Unknown capability")
    if values.get("is_active") is False:
        active = db.scalars(select(CareAssignment.id).where(CareAssignment.caregiver_id == cid, CareAssignment.status.in_(ACTIVE))).all()
        if active: raise HTTPException(409, "Caregiver has active assignments", detail={"assignment_ids": [str(x) for x in active]})
    for key, value in values.items(): setattr(cg, key, value)
    pids = _linked_patient_ids(db, cid); _history(db, user, request, pids[0] if pids else None, "caregiver.updated", "caregiver", cid, "Caregiver profile updated")
    reassess(db, pids, TriggerEvent.AVAILABILITY_CHANGED, {"caregiver_id": str(cid)}); db.commit(); return _caregiver_dict(db, user, cg)


@router.get("/caregivers/{cid}/schedule")
def get_schedule(cid: uuid.UUID, user: User = Depends(__import__("app.main", fromlist=["current_user"]).current_user), db: Session = Depends(get_db)):
    cg = db.get(Caregiver, cid)
    if not cg or not _can_edit_caregiver(db, user, cg): raise HTTPException(404, "Caregiver not found")
    rows = db.scalars(select(CaregiverWeeklySchedule).where(CaregiverWeeklySchedule.caregiver_id == cid).order_by(CaregiverWeeklySchedule.weekday, CaregiverWeeklySchedule.start_min)).all()
    return {"windows": [{"weekday": x.weekday, "start_min": x.start_min, "end_min": x.end_min} for x in rows]}


@router.put("/caregivers/{cid}/schedule")
def put_schedule(cid: uuid.UUID, body: ScheduleIn, request: Request, user: User = Depends(__import__("app.main", fromlist=["current_user"]).current_user), db: Session = Depends(get_db)):
    cg = db.get(Caregiver, cid)
    if not cg or not _can_edit_caregiver(db, user, cg): raise HTTPException(403, "Permission denied")
    intervals = []
    for x in body.windows:
        if set(x) != {"weekday", "start_min", "end_min"} or type(x["weekday"]) is not int or type(x["start_min"]) is not int or type(x["end_min"]) is not int or not (0 <= x["weekday"] <= 6 and 0 <= x["start_min"] < x["end_min"] <= 1440): raise HTTPException(422, "Invalid weekly window")
        intervals.append((x["weekday"], x["start_min"], x["end_min"]))
    if len(intervals) != len(set(intervals)) or any(a[0] == b[0] and max(a[1], b[1]) < min(a[2], b[2]) for i, a in enumerate(intervals) for b in intervals[i+1:]): raise HTTPException(422, "Overlapping or duplicate windows")
    db.query(CaregiverWeeklySchedule).filter_by(caregiver_id=cid).delete()
    for day, start, end in intervals: db.add(CaregiverWeeklySchedule(caregiver_id=cid, weekday=day, start_min=start, end_min=end))
    pids = _linked_patient_ids(db, cid); _history(db, user, request, pids[0] if pids else None, "availability.schedule_updated", "caregiver", cid, "Weekly schedule replaced")
    reassess(db, pids, TriggerEvent.AVAILABILITY_CHANGED, {"caregiver_id": str(cid)}); db.commit(); return get_schedule(cid, user, db)


@router.get("/caregivers/{cid}/availability")
def get_availability(cid: uuid.UUID, start: datetime = Query(alias="from"), end: datetime = Query(alias="to"), user: User = Depends(__import__("app.main", fromlist=["current_user"]).current_user), db: Session = Depends(get_db)):
    cg = db.get(Caregiver, cid)
    if not cg or not _can_edit_caregiver(db, user, cg): raise HTTPException(404, "Caregiver not found")
    if start.tzinfo is None or end.tzinfo is None or end <= start or end - start > timedelta(days=90): raise HTTPException(422, "Use offset datetimes and a range up to 90 days")
    cg.schedule = db.scalars(select(CaregiverWeeklySchedule).where(CaregiverWeeklySchedule.caregiver_id == cid)).all()
    cg.overrides = db.scalars(select(AvailabilityOverride).where(AvailabilityOverride.caregiver_id == cid)).all()
    return {"from": start, "to": end, "windows": [{"start": x.start, "end": x.end} for x in effective_windows(cg, start, end)], "overrides": [{"id": o.id, "start_at": to_utc(_as_aware(o.start_at)), "end_at": to_utc(_as_aware(o.end_at)), "status": o.status, "reason": o.reason, "cancelled_at": o.cancelled_at} for o in cg.overrides if not o.cancelled_at and _as_aware(o.end_at) > start and _as_aware(o.start_at) < end]}


@router.post("/caregivers/{cid}/availability-overrides", status_code=201)
def add_override(cid: uuid.UUID, body: OverrideIn, request: Request, user: User = Depends(__import__("app.main", fromlist=["current_user"]).current_user), db: Session = Depends(get_db)):
    cg = db.get(Caregiver, cid)
    if not cg or not _can_edit_caregiver(db, user, cg): raise HTTPException(403, "Permission denied")
    if body.end_at <= body.start_at: raise HTTPException(422, "end_at must be after start_at")
    values = body.model_dump(); values["start_at"] = to_utc(values["start_at"]); values["end_at"] = to_utc(values["end_at"])
    row = AvailabilityOverride(caregiver_id=cid, created_by=user.id, **values); db.add(row)
    pids = _linked_patient_ids(db, cid); _history(db, user, request, pids[0] if pids else None, "availability.override_added", "availability_override", "pending", "Availability override added", {"status": body.status, "reason": body.reason})
    reassess(db, pids, TriggerEvent.CAREGIVER_UNAVAILABLE if body.status == "UNAVAILABLE" else TriggerEvent.AVAILABILITY_CHANGED, {"caregiver_id": str(cid)}); db.commit(); db.refresh(row); return {"id": row.id, "status": row.status, "start_at": row.start_at, "end_at": row.end_at}


@router.post("/caregivers/{cid}/availability-overrides/{oid}/cancel")
def cancel_override(cid: uuid.UUID, oid: uuid.UUID, request: Request, user: User = Depends(__import__("app.main", fromlist=["current_user"]).current_user), db: Session = Depends(get_db)):
    cg = db.get(Caregiver, cid)
    row = db.get(AvailabilityOverride, oid)
    if not cg or not row or row.caregiver_id != cid: raise HTTPException(404, "Availability override not found")
    if not _can_edit_caregiver(db, user, cg): raise HTTPException(403, "Permission denied")
    if row.cancelled_at: raise HTTPException(409, "Override already cancelled")
    row.cancelled_at = now(); pids = _linked_patient_ids(db, cid); _history(db, user, request, pids[0] if pids else None, "availability.override_cancelled", "availability_override", oid, "Availability override cancelled")
    reassess(db, pids, TriggerEvent.AVAILABILITY_CHANGED, {"caregiver_id": str(cid)}); db.commit(); return {"status": "cancelled", "cancelled_at": row.cancelled_at}


@router.get("/patients/{pid}/activities")
def list_activities(pid: uuid.UUID, start: datetime | None = Query(default=None, alias="from"), end: datetime | None = Query(default=None, alias="to"), lifecycle_status: str | None = None, category: str | None = None, caregiver_id: uuid.UUID | None = None, unconfirmed: bool = False, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user: User = Depends(__import__("app.main", fromlist=["current_user"]).current_user), db: Session = Depends(get_db)):
    _, member = _member(db, user, pid)
    stmt = select(CareActivity).where(CareActivity.patient_id == pid)
    if start: stmt = stmt.where(CareActivity.scheduled_start >= start)
    if end: stmt = stmt.where(CareActivity.scheduled_start < end)
    if lifecycle_status: stmt = stmt.where(CareActivity.lifecycle_status == lifecycle_status)
    if category: stmt = stmt.where(CareActivity.category == category)
    rows = db.scalars(stmt.order_by(CareActivity.scheduled_start).offset(offset).limit(limit)).all()
    if user.role in (Role.HOUSEHELP, Role.NURSE):
        own = db.scalar(select(Caregiver.id).where(Caregiver.user_id == user.id))
        rows = [a for a in rows if own and db.scalar(select(CareAssignment.id).where(CareAssignment.activity_id == a.id, CareAssignment.caregiver_id == own, CareAssignment.status.in_(ACTIVE)))]
    if caregiver_id: rows = [a for a in rows if db.scalar(select(CareAssignment.id).where(CareAssignment.activity_id == a.id, CareAssignment.caregiver_id == caregiver_id))]
    if unconfirmed: rows = [a for a in rows if not db.scalar(select(CareAssignment.id).where(CareAssignment.activity_id == a.id, CareAssignment.role == "PRIMARY", CareAssignment.status == "CONFIRMED"))]
    return {"items": [_activity_dict(db, user, x) for x in rows], "total": len(rows), "limit": limit, "offset": offset}


@router.post("/patients/{pid}/activities", status_code=201)
def create_activity(pid: uuid.UUID, body: ActivityIn, request: Request, user: User = Depends(__import__("app.main", fromlist=["current_user"]).current_user), db: Session = Depends(get_db)):
    _member(db, user, pid, True)
    if body.scheduled_start < now() - timedelta(minutes=5): raise HTTPException(422, "Cannot schedule a new activity more than five minutes in the past")
    values = body.model_dump(exclude={"scheduled_start", "scheduled_end", "deadline"})
    a = CareActivity(patient_id=pid, created_by=user.id, scheduled_start=to_utc(body.scheduled_start), scheduled_end=to_utc(body.scheduled_end), deadline=to_utc(body.deadline or body.scheduled_end), **values); db.add(a); db.flush()
    patient_conflicts = overlaps_for(a, db.scalars(select(CareActivity).where(CareActivity.patient_id == pid, CareActivity.lifecycle_status == "SCHEDULED", CareActivity.id != a.id)).all())
    warnings = ([{"code": "PATIENT_OVERLAP", "message": "Patient has another overlapping activity", "details": {"count": len(patient_conflicts)}}] if patient_conflicts else [])
    if a.deadline and (_as_aware(a.deadline)-now()).total_seconds() < 86400: warnings.append({"code":"DEADLINE_NEAR","message":"Activity deadline is less than 24 hours away","details":{}})
    _history(db, user, request, pid, "activity.created", "care_activity", a.id, "Care activity created")
    reassess(db, [pid], TriggerEvent.ACTIVITY_ADDED, {"activity_id": str(a.id)}); db.commit(); db.refresh(a); return {**_activity_dict(db, user, a), "warnings": warnings}


@router.post("/patients/{pid}/activities/series", status_code=201)
def create_activity_series(pid: uuid.UUID, body: SeriesIn, request: Request, user: User = Depends(__import__("app.main", fromlist=["current_user"]).current_user), db: Session = Depends(get_db)):
    _member(db, user, pid, True)
    duration = body.scheduled_end - body.scheduled_start
    starts = []
    if body.recurrence == "DAILY":
        cursor = body.scheduled_start
        while (len(starts) < body.count if body.count else cursor <= body.until):
            starts.append(cursor); cursor += timedelta(days=body.interval)
    elif body.by_weekday:
        base = body.scheduled_start
        cursor = base.date()
        while True:
            days = (cursor - base.date()).days
            item = datetime.combine(cursor, base.timetz()).astimezone(base.tzinfo)
            if days < 90 and days // 7 % body.interval == 0 and cursor.weekday() in body.by_weekday and item >= base and (not body.until or item <= body.until):
                starts.append(item)
            cursor += timedelta(days=1)
            if body.count and len(starts) >= body.count: break
            if body.until and cursor > body.until.date(): break
            if not body.count and not body.until and len(starts) >= 60: break
    else:
        cursor = body.scheduled_start
        while (len(starts) < body.count if body.count else cursor <= body.until):
            starts.append(cursor); cursor += timedelta(weeks=body.interval)
    if not starts or len(starts) > 60 or starts[0] < now() - timedelta(minutes=5): raise HTTPException(422, "Invalid or empty recurrence")
    sid = uuid.uuid4(); created = []
    for start in starts:
        values = body.model_dump(exclude={"recurrence", "interval", "by_weekday", "count", "until", "scheduled_start", "scheduled_end", "deadline"})
        end = start + duration
        activity = CareActivity(patient_id=pid, series_id=sid, scheduled_start=to_utc(start), scheduled_end=to_utc(end), deadline=to_utc(end), created_by=user.id, **values)
        db.add(activity); db.flush(); created.append(activity)
        _history(db, user, request, pid, "activity.series_instance_created", "care_activity", activity.id, "Recurring care activity created", {"series_id": str(sid)})
    reassess(db, [pid], TriggerEvent.ACTIVITY_ADDED, {"series_id": str(sid), "count": len(created)}); db.commit()
    return {"series_id": sid, "items": [{"id": x.id, "scheduled_start": x.scheduled_start, "scheduled_end": x.scheduled_end, "lifecycle_status": x.lifecycle_status} for x in created], "warnings": []}


@router.get("/activities/{aid}")
def get_activity(aid: uuid.UUID, user: User = Depends(__import__("app.main", fromlist=["current_user"]).current_user), db: Session = Depends(get_db)):
    a = db.get(CareActivity, aid)
    if not a: raise HTTPException(404, "Activity not found")
    _member(db, user, a.patient_id)
    return _activity_dict(db, user, a)


@router.patch("/activities/{aid}")
def patch_activity(aid: uuid.UUID, body: ActivityPatch, request: Request, user: User = Depends(__import__("app.main", fromlist=["current_user"]).current_user), db: Session = Depends(get_db)):
    a = db.get(CareActivity, aid)
    if not a: raise HTTPException(404, "Activity not found")
    _member(db, user, a.patient_id, True)
    if a.lifecycle_status != "SCHEDULED": raise HTTPException(409, "Cancelled or completed activities cannot be edited")
    values = body.model_dump(exclude_unset=True)
    start = _as_aware(values.get("scheduled_start", a.scheduled_start)); end = _as_aware(values.get("scheduled_end", a.scheduled_end))
    deadline_value = values.get("deadline", a.deadline or end)
    deadline = _as_aware(deadline_value) if deadline_value else None
    if start < now(): raise HTTPException(422, "Rescheduling cannot move activity into the past")
    if end <= start: raise HTTPException(422, "scheduled_end must be after scheduled_start")
    if deadline and deadline < start: raise HTTPException(422, "deadline must be at or after scheduled_start")
    if values.get("category") is not None and values["category"] not in CATEGORIES: raise HTTPException(422, "Unknown activity category")
    if values.get("required_support") is not None and not set(values["required_support"]) <= SUPPORT: raise HTTPException(422, "Unknown support code")
    if values.get("requires_caregiver", a.requires_caregiver) and not values.get("required_support", a.required_support): raise HTTPException(422, "required_support is required when caregiver support is required")
    for key, value in values.items(): setattr(a, key, to_utc(value) if key in {"scheduled_start", "scheduled_end", "deadline"} and value is not None else value)
    a.updated_at = now(); _history(db, user, request, a.patient_id, "activity.rescheduled", "care_activity", aid, "Care activity updated")
    reassess(db, [a.patient_id], TriggerEvent.ACTIVITY_RESCHEDULED, {"activity_id": str(aid)}); db.commit(); db.refresh(a)
    warnings=[]
    for assigned in db.scalars(select(CareAssignment).where(CareAssignment.activity_id == aid, CareAssignment.status == "CONFIRMED")):
        cg=db.get(Caregiver, assigned.caregiver_id); warnings.extend(_warnings(db,a,cg))
    return {**_activity_dict(db, user, a), "warnings": warnings}


@router.post("/activities/{aid}/cancel")
def cancel_activity(aid: uuid.UUID, request: Request, body: CancelIn | None = None, user: User = Depends(__import__("app.main", fromlist=["current_user"]).current_user), db: Session = Depends(get_db)):
    a = db.get(CareActivity, aid)
    if not a: raise HTTPException(404, "Activity not found")
    _member(db, user, a.patient_id, True)
    if a.lifecycle_status != "SCHEDULED": raise HTTPException(409, "Activity is already terminal")
    a.lifecycle_status = "CANCELLED"
    db.query(CareAssignment).filter(CareAssignment.activity_id == aid, CareAssignment.status.in_(ACTIVE)).update({"status": "CANCELLED", "updated_at": now()})
    _history(db, user, request, a.patient_id, "activity.cancelled", "care_activity", aid, "Care activity cancelled", {"reason": body.reason if body else ""})
    reassess(db, [a.patient_id], TriggerEvent.ASSIGNMENT_REMOVED, {"activity_id": str(aid)}); db.commit(); return {"status": "cancelled"}


@router.post("/activities/{aid}/complete")
def complete_activity(aid: uuid.UUID, request: Request, user: User = Depends(__import__("app.main", fromlist=["current_user"]).current_user), db: Session = Depends(get_db)):
    a = db.get(CareActivity, aid)
    if not a: raise HTTPException(404, "Activity not found")
    _member(db, user, a.patient_id)
    own = db.scalar(select(Caregiver).where(Caregiver.user_id == user.id, Caregiver.id.in_(select(CaregiverPatientLink.caregiver_id).where(CaregiverPatientLink.patient_id == a.patient_id))))
    member = db.scalar(select(CareTeamMember).where(CareTeamMember.patient_id == a.patient_id, CareTeamMember.user_id == user.id))
    coordinator = user.role == Role.ADMIN or (member and member.team_role == TeamRole.COORDINATOR)
    if not coordinator and not (own and db.scalar(select(CareAssignment.id).where(CareAssignment.activity_id == aid, CareAssignment.caregiver_id == own.id, CareAssignment.status == "CONFIRMED"))): raise HTTPException(403, "Only coordinator or assigned caregiver can complete")
    if a.lifecycle_status != "SCHEDULED": raise HTTPException(409, "Activity is already terminal")
    a.lifecycle_status = "COMPLETED"; _history(db, user, request, a.patient_id, "activity.completed", "care_activity", aid, "Care activity completed")
    for incident in db.scalars(select(Incident).where(Incident.related_activity_id == aid, Incident.status.in_(("OPEN", "ACKNOWLEDGED")))):
        incident.status="RESOLVED";incident.resolved_at=now();incident.resolution_code="HANDLED";incident.resolution_note="Activity completed";incident.current_deadline_at=None;incident.deadline_kind=None;incident.version+=1
        db.add(IncidentEvent(incident_id=incident.id,kind="RESOLVED",level=incident.current_level,actor_user_id=user.id,note="Related activity completed"))
    reassess(db, [a.patient_id], TriggerEvent.GAP_RESOLVED_OR_REAPPEARED, {"activity_id": str(aid)}); db.commit(); return {"status": "completed"}


def _dependency_path(db, start, target, seen=None):
    seen = seen or set()
    if start == target: return [start]
    if start in seen: return None
    seen.add(start)
    for child in db.scalars(select(ActivityDependency.depends_on_activity_id).where(ActivityDependency.activity_id == start)).all():
        path = _dependency_path(db, child, target, seen)
        if path: return [start, *path]
    return None


@router.post("/activities/{aid}/dependencies", status_code=201)
def add_dependency(aid: uuid.UUID, body: DependencyIn, request: Request, user: User = Depends(__import__("app.main", fromlist=["current_user"]).current_user), db: Session = Depends(get_db)):
    dep_id = body.depends_on_activity_id
    activity = db.get(CareActivity, aid); dependency = db.get(CareActivity, dep_id)
    if not activity or not dependency: raise HTTPException(404, "Activity not found")
    _member(db, user, activity.patient_id, True)
    if activity.patient_id != dependency.patient_id: raise HTTPException(409, "Dependencies must belong to the same patient")
    if activity.id == dependency.id: raise HTTPException(409, f"Dependency cycle: {aid} -> {aid}")
    path = _dependency_path(db, dep_id, aid)
    if path: raise HTTPException(409, f"Dependency cycle: {' -> '.join(map(str, [aid, *path]))}")
    db.add(ActivityDependency(activity_id=aid, depends_on_activity_id=dep_id)); _history(db, user, request, activity.patient_id, "activity.dependency_added", "care_activity", aid, "Activity dependency added", {"depends_on": str(dep_id)})
    reassess(db, [activity.patient_id], TriggerEvent.ACTIVITY_RESCHEDULED, {"activity_id": str(aid)}); db.commit(); return {"activity_id": aid, "depends_on_activity_id": dep_id}


@router.delete("/activities/{aid}/dependencies")
def delete_dependency(aid: uuid.UUID, depends_on_activity_id: uuid.UUID, request: Request, user: User = Depends(__import__("app.main", fromlist=["current_user"]).current_user), db: Session = Depends(get_db)):
    activity = db.get(CareActivity, aid)
    if not activity: raise HTTPException(404, "Activity not found")
    _member(db, user, activity.patient_id, True)
    link = db.get(ActivityDependency, {"activity_id": aid, "depends_on_activity_id": depends_on_activity_id})
    if not link: raise HTTPException(404, "Dependency not found")
    db.delete(link); _history(db, user, request, activity.patient_id, "activity.dependency_removed", "care_activity", aid, "Activity dependency removed", {"depends_on": str(depends_on_activity_id)})
    reassess(db, [activity.patient_id], TriggerEvent.ACTIVITY_RESCHEDULED, {"activity_id": str(aid)}); db.commit(); return Response(status_code=204)


@router.post("/activities/{aid}/assignments", status_code=201)
def add_assignment(aid: uuid.UUID, body: AssignmentIn, request: Request, user: User = Depends(__import__("app.main", fromlist=["current_user"]).current_user), db: Session = Depends(get_db)):
    a = db.get(CareActivity, aid)
    if not a: raise HTTPException(404, "Activity not found")
    _member(db, user, a.patient_id, True)
    cg = db.get(Caregiver, body.caregiver_id)
    if not cg or not cg.is_active or not db.scalar(select(CaregiverPatientLink.id).where(CaregiverPatientLink.caregiver_id == cg.id, CaregiverPatientLink.patient_id == a.patient_id)): raise HTTPException(409, "Caregiver must be active and linked to this patient")
    if body.scope == "FUTURE_IN_SERIES":
        if not a.series_id: raise HTTPException(422, "FUTURE_IN_SERIES requires an activity series")
        targets = db.scalars(select(CareActivity).where(CareActivity.series_id == a.series_id, CareActivity.scheduled_start >= a.scheduled_start, CareActivity.lifecycle_status == "SCHEDULED").order_by(CareActivity.scheduled_start)).all()
    else:
        targets = [a]
    created = []
    try:
        for target in targets:
            if target.lifecycle_status != "SCHEDULED": raise HTTPException(409, "Cannot assign a cancelled or completed activity")
            if db.scalar(select(CareAssignment.id).where(CareAssignment.activity_id == target.id, CareAssignment.caregiver_id == cg.id, CareAssignment.role != body.role, CareAssignment.status.in_(ACTIVE))): raise HTTPException(409, "Caregiver cannot be both primary and backup on one activity")
            existing = db.scalar(select(CareAssignment).where(CareAssignment.activity_id == target.id, CareAssignment.role == "PRIMARY", CareAssignment.status.in_(ACTIVE))) if body.role == "PRIMARY" else None
            if existing:
                if body.confirm_now and existing.status == "CONFIRMED": existing.status = "SUPERSEDED"; existing.updated_at = now(); db.flush()
                else: raise HTTPException(409, "An active primary assignment already exists")
            status = "CONFIRMED" if body.confirm_now else "PROPOSED"
            assignment = CareAssignment(activity_id=target.id, caregiver_id=cg.id, role=body.role, status=status, assigned_by=user.id, confirmed_at=now() if body.confirm_now else None, confirmed_by=user.id if body.confirm_now else None, confirmed_via="COORDINATOR" if body.confirm_now else None)
            db.add(assignment); db.flush()
            warning_list = _warnings(db, target, cg)
            _history(db, user, request, target.patient_id, "assignment.added", "care_assignment", assignment.id, "Caregiver assigned", {"role": body.role, "status": status})
            created.append({"id": assignment.id, "activity_id": target.id, "caregiver_id": cg.id, "role": assignment.role, "status": assignment.status, "warnings": warning_list})
    except IntegrityError:
        db.rollback(); raise HTTPException(409, "Another coordinator updated the primary assignment; reload and retry") from None
    reassess(db, [a.patient_id], TriggerEvent.ASSIGNMENT_ADDED, {"assignment_ids": [str(x["id"]) for x in created]}); db.commit()
    return created[0] if body.scope == "THIS" else {"items": created}


def _transition(aid, action, body, request, user, db):
    assignment = db.get(CareAssignment, aid)
    if not assignment: raise HTTPException(404, "Assignment not found")
    act = db.get(CareActivity, assignment.activity_id); cg = db.get(Caregiver, assignment.caregiver_id)
    member = db.scalar(select(CareTeamMember).where(CareTeamMember.patient_id == act.patient_id, CareTeamMember.user_id == user.id))
    coordinator = user.role == Role.ADMIN or member and member.team_role == TeamRole.COORDINATOR
    self_user = cg.user_id == user.id
    matrix = {"request-confirmation": {"PROPOSED": "AWAITING_CONFIRMATION"}, "confirm": {"PROPOSED": "CONFIRMED", "AWAITING_CONFIRMATION": "CONFIRMED"}, "decline": {"AWAITING_CONFIRMATION": "DECLINED"}, "reject": {"AWAITING_CONFIRMATION": "REJECTED"}, "cancel": {"PROPOSED": "CANCELLED", "AWAITING_CONFIRMATION": "CANCELLED", "CONFIRMED": "CANCELLED"}}
    if assignment.status not in matrix[action]: raise HTTPException(409, f"Illegal transition from {assignment.status}")
    caregiver_actions = action in {"confirm", "decline"}
    if caregiver_actions and not self_user and not coordinator: raise HTTPException(403, "Only assigned caregiver or coordinator can respond")
    if action == "decline" and not self_user: raise HTTPException(403, "Only the assigned caregiver can decline")
    if action == "confirm" and assignment.status == "PROPOSED" and self_user and not coordinator: raise HTTPException(403, "Ask the coordinator to request confirmation first")
    if action in {"request-confirmation", "reject", "cancel"} and not coordinator: raise HTTPException(403, "Coordinator permission required")
    if action == "decline" and not (body or {}).get("reason", "").strip(): raise HTTPException(422, "Decline reason is required")
    if action == "confirm":
        assignment.confirmed_at = now(); assignment.confirmed_by = user.id; assignment.confirmed_via = "CAREGIVER" if self_user and not coordinator else "COORDINATOR"
        if assignment.role == "PRIMARY":
            db.query(CareAssignment).filter(CareAssignment.activity_id == act.id, CareAssignment.role == "PRIMARY", CareAssignment.status == "CONFIRMED", CareAssignment.id != assignment.id).update({"status": "SUPERSEDED", "updated_at": now()})
    if action == "decline": assignment.decline_reason = (body or {}).get("reason")
    assignment.status = matrix[action][assignment.status]; assignment.updated_at = now()
    _history(db, user, request, act.patient_id, f"assignment.{action.replace('-', '_')}", "care_assignment", aid, f"Assignment {action.replace('-', ' ')}", {"status": assignment.status})
    trigger = TriggerEvent.ASSIGNMENT_UNCONFIRMED if assignment.status == "AWAITING_CONFIRMATION" else TriggerEvent.ASSIGNMENT_REMOVED if assignment.status in TERMINAL else TriggerEvent.GAP_RESOLVED_OR_REAPPEARED
    reassess(db, [act.patient_id], trigger, {"assignment_id": str(aid)}); db.commit()
    return {"id": assignment.id, "status": assignment.status, "confirmed_at": assignment.confirmed_at}


def _make_transition_endpoint(action):
    body_model = DeclineIn if action == "decline" else ReasonIn
    def endpoint(assignment_id: uuid.UUID, request: Request, body: body_model | None = None, user: User = Depends(__import__("app.main", fromlist=["current_user"]).current_user), db: Session = Depends(get_db)):
        return _transition(assignment_id, action, body.model_dump() if body else {}, request, user, db)
    # ``from __future__ import annotations`` stringifies nested annotations,
    # where ``body_model`` is local to this factory. Resolve it before FastAPI
    # inspects the endpoint so OpenAPI generation can build the request schema.
    endpoint.__annotations__["body"] = body_model | None
    endpoint.__name__ = f"assignment_{action.replace('-', '_')}"
    return endpoint


for _action in ("request-confirmation", "confirm", "decline", "reject", "cancel"):
    router.add_api_route(f"/assignments/{{assignment_id}}/{_action}", _make_transition_endpoint(_action), methods=["POST"], name=f"assignment_{_action}")


@router.get("/caregivers/{cid}/assignment-history")
def assignment_history(cid: uuid.UUID, user: User = Depends(__import__("app.main", fromlist=["current_user"]).current_user), db: Session = Depends(get_db)):
    cg = db.get(Caregiver, cid)
    if not cg or not _can_edit_caregiver(db, user, cg): raise HTTPException(404, "Caregiver not found")
    rows = db.execute(select(CareAssignment, CareActivity).join(CareActivity).where(CareAssignment.caregiver_id == cid).order_by(CareAssignment.assigned_at.desc()).limit(100)).all()
    own = cg.user_id == user.id
    visible = {pid for pid in _linked_patient_ids(db, cid) if _is_coordinator(db, user, pid)}
    return {"items": [{"id": x.id, "activity_id": a.id if own or a.patient_id in visible else None, "patient_id": a.patient_id if own or a.patient_id in visible else None, "title": a.title if own or a.patient_id in visible else "Busy — other commitment", "role": x.role, "status": x.status, "assigned_at": x.assigned_at} for x, a in rows]}


@router.get("/patients/{pid}/caregivers/workload")
def caregiver_workloads(pid: uuid.UUID, start: datetime = Query(alias="from"), end: datetime = Query(alias="to"), user: User = Depends(__import__("app.main", fromlist=["current_user"]).current_user), db: Session = Depends(get_db)):
    _member(db, user, pid)
    if start.tzinfo is None or end.tzinfo is None or end <= start or end-start > timedelta(days=90): raise HTTPException(422, "Use offset datetimes and a range up to 90 days")
    caregivers = db.scalars(select(Caregiver).join(CaregiverPatientLink).where(CaregiverPatientLink.patient_id == pid)).all(); result = []
    for cg in caregivers:
        rows = db.execute(select(CareAssignment, CareActivity).join(CareActivity).where(CareAssignment.caregiver_id == cg.id, CareActivity.scheduled_start < end, CareActivity.scheduled_end > start)).all()
        data = workload(rows, cg.id)
        # Do not reveal any other patient's titles or identities; only aggregate busy counts.
        all_rows = db.execute(select(CareAssignment, CareActivity).join(CareActivity).where(CareAssignment.caregiver_id == cg.id, CareActivity.patient_id != pid, CareActivity.scheduled_start < end, CareActivity.scheduled_end > start)).all()
        result.append({"caregiver_id": cg.id, "name": cg.name, **data, "busy_other_commitment_count": len(all_rows)})
    return {"items": result}
