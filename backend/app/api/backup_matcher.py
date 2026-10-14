"""Capability-Aware Backup Matcher: cover requests, ranked replacements, offers and confirmation."""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.db import get_db
from app.engine.workload_balancer import delegation_class
from app.models import CareActivity, CareAssignment, Caregiver, CoverRequest, CoverRequestEvent, Patient, Role
from app.services import backup_matcher as svc
from app.services.reassess import TriggerEvent, reassess
from app.services.workload_balancer import ACTIVE, _aware

router = APIRouter(prefix="/api/v1", tags=["backup matcher"])
REASON_LABELS = {"DECLINED": "Declined", "ABSENCE": "Absence", "MANUAL": "Cover requested"}


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OpenIn(Input):
    note: str = Field(default="", max_length=300)
    # Command Center sets this: refuse when the task already has a confirmed, available primary,
    # so a stale card can never start replacing someone who is fine.
    only_if_uncovered: bool = False


class OfferIn(Input):
    caregiver_id: uuid.UUID
    auto_advance: bool = True


class AcceptIn(Input):
    caregiver_id: uuid.UUID | None = None


class NoteIn(Input):
    reason: str = Field(default="", max_length=300)


def _current_user(request: Request, db: Session = Depends(get_db)):
    from app.main import current_user
    return current_user(request, db)


def _scope(db, user, patient_id, *, write=False):
    from app.api.workload import _scope as workload_scope
    try:
        return workload_scope(db, user, patient_id, write=write)
    except HTTPException as exc:
        if exc.status_code != 403: raise
        raise HTTPException(403, "Only the primary contact can manage cover requests" if write else "Cover requests are visible to primary contacts") from None


def _own_caregiver(db, user):
    return db.scalar(select(Caregiver).where(Caregiver.user_id == user.id))


def _request(db, request_id, *, lock=False) -> CoverRequest:
    query = select(CoverRequest).where(CoverRequest.id == request_id)
    req = db.scalar(query.with_for_update() if lock else query)
    if not req: raise HTTPException(404, "Cover request not found")
    return req


def _name(db, caregiver_id):
    cg = db.get(Caregiver, caregiver_id) if caregiver_id else None
    return {"caregiver_id": cg.id, "name": cg.name} if cg else None


def _serialize(db, req: CoverRequest, *, full: bool, at=None) -> dict:
    at = at or now()
    activity = db.get(CareActivity, req.activity_id)
    patient = db.get(Patient, req.patient_id)
    data = {"id": req.id, "patient": {"id": patient.id, "name": patient.name}, "status": req.status, "reason": req.reason,
            "reason_label": REASON_LABELS[req.reason], "reason_note": req.reason_note, "replaced": _name(db, req.replaced_caregiver_id),
            "activity": {"id": activity.id, "title": activity.title, "category": activity.category, "importance": activity.importance,
                         "required_support": list(activity.required_support or []), "delegation_class": delegation_class(activity.required_support),
                         "scheduled_start": _aware(activity.scheduled_start), "scheduled_end": _aware(activity.scheduled_end)},
            "offered": ({**_name(db, req.offered_caregiver_id), "since": _aware(req.offered_at)} if req.offered_caregiver_id else None),
            "auto_advance": req.auto_advance, "opened_at": _aware(req.opened_at), "closed_at": _aware(req.closed_at), "resolution": req.resolution,
            "covered_by": _name(db, req.covered_by_caregiver_id), "declined_count": len(req.declined_caregiver_ids or []),
            "minutes_open": svc.minutes_between(req.opened_at, req.closed_at or at), "version": req.version}
    if full:
        data["ranking"] = svc.ranking(db, req, at) if req.status in svc.OPEN_STATUSES else None
        data["events"] = [{"at": _aware(e.at), "kind": e.kind, "caregiver": _name(db, e.caregiver_id), "note": e.note}
                          for e in db.scalars(select(CoverRequestEvent).where(CoverRequestEvent.request_id == req.id).order_by(CoverRequestEvent.at))]
    return data


def _commit(db, req, trigger=TriggerEvent.ASSIGNMENT_ADDED):
    reassess(db, [req.patient_id], trigger, {"cover_request_id": str(req.id)})
    db.commit(); db.refresh(req)


@router.get("/patients/{patient_id}/cover-requests")
def list_cover_requests(patient_id: uuid.UUID, status: Literal["open", "closed", "all"] = "open", user=Depends(_current_user), db: Session = Depends(get_db)):
    patient, role_view = _scope(db, user, patient_id)
    query = select(CoverRequest).where(CoverRequest.patient_id == patient.id)
    if status == "open": query = query.where(CoverRequest.status.in_(svc.OPEN_STATUSES))
    if status == "closed": query = query.where(CoverRequest.status.not_in(svc.OPEN_STATUSES))
    rows = db.scalars(query.order_by(CoverRequest.opened_at.desc()).limit(100)).all()
    at = now()
    return {"items": [_serialize(db, r, full=status == "open", at=at) for r in rows], "role_view": role_view,
            "permissions": {"can_manage": role_view == "PRIMARY_CONTACT"}}


@router.get("/patients/{patient_id}/cover-requests/metrics")
def cover_metrics(patient_id: uuid.UUID, days: int = Query(30, ge=1, le=365), user=Depends(_current_user), db: Session = Depends(get_db)):
    patient, _ = _scope(db, user, patient_id)
    return svc.metrics(db, patient.id, days)


@router.post("/activities/{activity_id}/cover-requests", status_code=201)
def open_cover_request(activity_id: uuid.UUID, body: OpenIn, user=Depends(_current_user), db: Session = Depends(get_db)):
    activity = db.get(CareActivity, activity_id)
    if not activity: raise HTTPException(404, "Activity not found")
    _scope(db, user, activity.patient_id, write=True)
    if activity.lifecycle_status != "SCHEDULED" or not activity.requires_caregiver or _aware(activity.scheduled_start) <= now():
        raise HTTPException(409, "Only upcoming caregiver tasks can get a cover request")
    holder = db.scalar(select(CareAssignment).where(CareAssignment.activity_id == activity.id, CareAssignment.role == "PRIMARY", CareAssignment.status.in_(ACTIVE)))
    if body.only_if_uncovered:
        need, active = svc.need_for(db, activity)
        open_now = db.scalar(select(CoverRequest.id).where(CoverRequest.activity_id == activity.id, CoverRequest.status.in_(svc.OPEN_STATUSES)))
        if need is None and open_now is None and active is not None and active.status == "CONFIRMED" and svc.holder_can_do(db, activity, active):
            raise HTTPException(409, "This task already has a confirmed caregiver who is available")
    req = svc.open_request(db, activity, "MANUAL", replaced_caregiver_id=holder.caregiver_id if holder else None,
                           note=body.note.strip() or "Primary contact asked for cover", actor=user)
    _commit(db, req)
    return _serialize(db, req, full=True)


@router.get("/cover-requests/{request_id}")
def get_cover_request(request_id: uuid.UUID, user=Depends(_current_user), db: Session = Depends(get_db)):
    req = _request(db, request_id)
    own = _own_caregiver(db, user)
    if own and req.offered_caregiver_id == own.id:
        data = _serialize(db, req, full=False)
        return {**data, "replaced": None, "reason_note": "", "my_offer": True}
    _scope(db, user, req.patient_id)
    return _serialize(db, req, full=True)


@router.post("/cover-requests/{request_id}/offer")
def offer_cover(request_id: uuid.UUID, body: OfferIn, user=Depends(_current_user), db: Session = Depends(get_db)):
    req = _request(db, request_id, lock=True)
    _scope(db, user, req.patient_id, write=True)
    if req.status == "OFFERED" and req.offered_caregiver_id != body.caregiver_id:
        raise HTTPException(409, "An offer is already waiting for a response; record their answer or cancel it first")
    try: svc.offer(db, req, body.caregiver_id, actor=user, auto_advance=body.auto_advance)
    except svc.CoverError as exc: raise HTTPException(409, str(exc)) from None
    _commit(db, req)
    return _serialize(db, req, full=True)


@router.post("/cover-requests/{request_id}/accept")
def accept_cover(request_id: uuid.UUID, body: AcceptIn | None = None, user=Depends(_current_user), db: Session = Depends(get_db)):
    """The offered caregiver accepts, or a primary contact records that someone agreed (e.g. by phone)."""
    req = _request(db, request_id, lock=True)
    own = _own_caregiver(db, user)
    target = (body.caregiver_id if body else None) or req.offered_caregiver_id
    if own and target == own.id and req.offered_caregiver_id == own.id:
        via = "CAREGIVER"
    else:
        _scope(db, user, req.patient_id, write=True)
        via = "COORDINATOR"
    if target is None: raise HTTPException(422, "Choose who is taking the task")
    try: svc.accept(db, req, target, actor=user, via=via)
    except svc.CoverError as exc: raise HTTPException(409, str(exc)) from None
    _commit(db, req)
    data = _serialize(db, req, full=False)
    if via == "CAREGIVER":  # the replacement does not need to know who they replace or why
        data.update(replaced=None, reason_note="")
    return {**data, "message": f"Thank you — you are confirmed for {data['activity']['title']}." if via == "CAREGIVER" else f"{data['covered_by']['name']} is confirmed."}


@router.post("/cover-requests/{request_id}/decline")
def decline_cover(request_id: uuid.UUID, body: NoteIn | None = None, user=Depends(_current_user), db: Session = Depends(get_db)):
    req = _request(db, request_id, lock=True)
    own = _own_caregiver(db, user)
    if not (own and req.offered_caregiver_id == own.id):
        _scope(db, user, req.patient_id, write=True)
    try: svc.decline(db, req, actor=user, note=(body.reason if body else "").strip())
    except svc.CoverError as exc: raise HTTPException(409, str(exc)) from None
    _commit(db, req, TriggerEvent.ASSIGNMENT_UNCONFIRMED)
    if own and req.offered_caregiver_id != own.id and not _is_manager(db, user, req):
        return {"id": req.id, "status": "DECLINED_BY_YOU"}
    return _serialize(db, req, full=True)


@router.post("/cover-requests/{request_id}/cancel")
def cancel_cover(request_id: uuid.UUID, body: NoteIn | None = None, user=Depends(_current_user), db: Session = Depends(get_db)):
    req = _request(db, request_id, lock=True)
    _scope(db, user, req.patient_id, write=True)
    if req.status not in svc.OPEN_STATUSES: raise HTTPException(409, "This cover request is already closed")
    if req.trigger_key is None:
        # Remember the decline/absence present now so closing this request does not immediately reopen one for it.
        need, _ = svc.need_for(db, db.get(CareActivity, req.activity_id))
        if need: req.trigger_key = need[2]
    svc.close(db, req, "CANCELLED", actor=user, note=(body.reason if body else "").strip() or "Closed by primary contact")
    _commit(db, req, TriggerEvent.GAP_RESOLVED_OR_REAPPEARED)
    return _serialize(db, req, full=False)


@router.get("/cover-offers/mine")
def my_cover_offers(user=Depends(_current_user), db: Session = Depends(get_db)):
    own = _own_caregiver(db, user)
    if not own: return {"items": []}
    rows = db.scalars(select(CoverRequest).where(CoverRequest.offered_caregiver_id == own.id, CoverRequest.status == "OFFERED").order_by(CoverRequest.offered_at)).all()
    return {"items": [{**_serialize(db, r, full=False), "replaced": None, "reason_note": ""} for r in rows]}


def _is_manager(db, user, req) -> bool:
    try:
        return _scope(db, user, req.patient_id, write=True) is not None
    except HTTPException:
        return False
