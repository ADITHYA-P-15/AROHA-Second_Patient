"""Ratings and reputation (flag `ratings`): reviews, doctor ratings, reports and the explained reputation breakdown.

Who may write: a primary contact or patient whose patient had at least `min_completed_tasks` completed tasks from the
caretaker (reviews), and a professional on the team of a patient the caretaker served (doctor ratings). One per author per
caretaker per `rating_window_days`, editable for `edit_window_days`. Review text is shown to primary contacts and
professionals; a caretaker sees only reviews of themselves; patients see stars without text.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.db import get_db
from app.core.features import feature_required
from app.core.permissions import require_patient_access
from app.core.reputation_policy import policy as current_policy
from app.models import ActivityHistory, CareTeamMember, Caregiver, DoctorRating, Review, ReviewReport, Role, TeamRole, User
from app.services import reputation as rep
from app.services.notify import notify

router = APIRouter(prefix="/api/v1", tags=["reputation"], dependencies=[Depends(feature_required("ratings"))])
TEXT_READERS = (Role.PRIMARY_CONTACT, Role.PROFESSIONAL)


def _current_user(request: Request, db: Session = Depends(get_db)):
    from app.main import current_user
    return current_user(request, db)


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: int = Field(ge=1, le=5)
    text: str = Field(default="", max_length=500)
    patient_id: uuid.UUID | None = None


class ReviewPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: int | None = Field(default=None, ge=1, le=5)
    text: str | None = Field(default=None, max_length=500)


class DoctorRatingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: int = Field(ge=1, le=5)
    note: str = Field(default="", max_length=300)
    patient_id: uuid.UUID | None = None


class DoctorRatingPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: int | None = Field(default=None, ge=1, le=5)
    note: str | None = Field(default=None, max_length=300)


class ReportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="", max_length=300)


def _caretaker(db: Session, cid: uuid.UUID) -> Caregiver:
    cg = db.get(Caregiver, cid)
    if not cg or cg.kind != "CARETAKER": raise HTTPException(404, "Caretaker not found")
    return cg


def _can_view(db: Session, user: User, cg: Caregiver) -> None:
    """Browse roles see any caretaker's reputation; a caretaker sees only their own."""
    if user.role == Role.CARETAKER:
        if cg.user_id != user.id: raise HTTPException(403, "Caretakers can only see their own reputation")
    elif user.role not in (Role.PRIMARY_CONTACT, Role.PATIENT, Role.PROFESSIONAL):
        raise HTTPException(403, "Permission denied")


def _audit(db, user, request, patient_id, event, entity, entity_id, summary):
    db.add(ActivityHistory(actor_user_id=user.id, patient_id=patient_id, event_type=event, entity_type=entity, entity_id=str(entity_id), summary=summary,
                           payload={}, request_id=getattr(request.state, "request_id", "")))


def _limit(db, user, pol):
    if rep.created_today(db, user.id) >= pol["max_ratings_per_day"]:
        raise HTTPException(429, "Too many ratings today; try again tomorrow", headers={"Retry-After": "3600"})


def _editable(row, user, pol):
    if row.author_user_id != user.id: raise HTTPException(403, "Only the author can edit this")
    if rep._aware(row.created_at) < now() - timedelta(days=pol["edit_window_days"]):
        raise HTTPException(409, f"Ratings can be edited for {pol['edit_window_days']} days only")


def review_dict(r: Review, *, with_text: bool, mine: bool = False, pol: dict | None = None, reported: bool = False) -> dict:
    pol = pol or current_policy()
    editable = mine and rep._aware(r.created_at) >= now() - timedelta(days=pol["edit_window_days"])
    return {"id": str(r.id), "caregiver_id": str(r.caregiver_id), "rating": r.rating, "text": r.text if with_text else None, "author_role": r.author_role,
            "created_at": rep._aware(r.created_at).isoformat(), "edited": rep._aware(r.updated_at) > rep._aware(r.created_at) + timedelta(seconds=1),
            "is_mine": mine, "editable": editable, "is_synthetic": r.is_synthetic, "reported": reported}


def doctor_dict(r: DoctorRating, mine: bool, pol: dict) -> dict:
    return {"id": str(r.id), "caregiver_id": str(r.caregiver_id), "rating": r.rating, "note": r.note, "created_at": rep._aware(r.created_at).isoformat(),
            "is_mine": mine, "editable": mine and rep._aware(r.created_at) >= now() - timedelta(days=pol["edit_window_days"])}


# --- reading -----------------------------------------------------------------------------------------------------------

@router.get("/caretakers/{cid}/reputation")
def reputation(cid: uuid.UUID, user=Depends(_current_user), db: Session = Depends(get_db)):
    cg = _caretaker(db, cid)
    _can_view(db, user, cg)
    pol = current_policy()
    b = rep.breakdowns(db, [cg.id], pol=pol)[cg.id]
    return {"caregiver_id": str(cg.id), "name": cg.name, **b,
            "policy": {"patient_review_weight": pol["patient_review_weight"], "shrinkage_k": pol["shrinkage_k"], "metric_window_days": pol["metric_window_days"],
                       "metric_min_tasks": pol["metric_min_tasks"], "min_ratings_for_history": pol["min_ratings_for_history"]}}


@router.get("/caretakers/{cid}/reviews")
def reviews(cid: uuid.UUID, limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0, le=10_000), user=Depends(_current_user), db: Session = Depends(get_db)):
    cg = _caretaker(db, cid)
    _can_view(db, user, cg)
    with_text = user.role in TEXT_READERS or (user.role == Role.CARETAKER and cg.user_id == user.id)
    base = select(Review).where(Review.caregiver_id == cg.id, Review.hidden.is_(False))
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(base.order_by(Review.created_at.desc(), Review.id).offset(offset).limit(limit)).all()
    pol = current_policy()
    flagged = set(db.scalars(select(ReviewReport.review_id).where(ReviewReport.review_id.in_([r.id for r in rows])))) if rows else set()
    return {"items": [review_dict(r, with_text=with_text, mine=r.author_user_id == user.id, pol=pol, reported=r.id in flagged) for r in rows], "can_report": cg.user_id == user.id, "total": total, "limit": limit, "offset": offset,
            "text_visible": with_text}


@router.get("/patients/{pid}/rateable-caretakers")
def rateable(pid: uuid.UUID, user=Depends(_current_user), db: Session = Depends(get_db)):
    """Caretakers on this patient's team, with whether the viewer may rate them now and their own latest rating."""
    _, member = require_patient_access(db, user, pid, "patient:read")
    if member.team_role not in (TeamRole.PRIMARY_CONTACT, TeamRole.PATIENT_SELF, TeamRole.PROFESSIONAL): raise HTTPException(403, "Permission denied")
    pol = current_policy()
    team = select(CareTeamMember.user_id).where(CareTeamMember.patient_id == pid, CareTeamMember.team_role == TeamRole.CARETAKER)
    carers = db.scalars(select(Caregiver).where(Caregiver.user_id.in_(team), Caregiver.kind == "CARETAKER").order_by(Caregiver.name)).all()
    out = []
    for cg in carers:
        done = rep.completed_for(db, cg.id, [pid]).get(pid, 0)
        if member.team_role == TeamRole.PROFESSIONAL:
            mine = rep.recent(db, DoctorRating, user.id, cg.id, pol["rating_window_days"])
            eligible = rep.doctor_patient(db, user, cg.id, pid) is not None
            out.append({"caregiver_id": str(cg.id), "name": cg.name, "completed_tasks": done, "kind": "doctor", "eligible": eligible, "mine": doctor_dict(mine, True, pol) if mine else None})
        else:
            mine = rep.recent(db, Review, user.id, cg.id, pol["rating_window_days"])
            out.append({"caregiver_id": str(cg.id), "name": cg.name, "completed_tasks": done, "kind": "review", "eligible": done >= pol["min_completed_tasks"],
                        "needed_tasks": pol["min_completed_tasks"], "optional": member.team_role == TeamRole.PATIENT_SELF,
                        "mine": review_dict(mine, with_text=True, mine=True, pol=pol) if mine else None})
    return {"items": out, "author_role": member.team_role.value}


@router.get("/reputation/prompts")
def prompts(user=Depends(_current_user), db: Session = Depends(get_db)):
    """The patient's quiet, optional prompt: caretakers they can review and have not reviewed in the window. No notification."""
    if user.role != Role.PATIENT: return {"items": []}
    pol = current_policy()
    items = []
    for pid in rep.patients_as(db, user, TeamRole.PATIENT_SELF):
        team = select(CareTeamMember.user_id).where(CareTeamMember.patient_id == pid, CareTeamMember.team_role == TeamRole.CARETAKER)
        for cg in db.scalars(select(Caregiver).where(Caregiver.user_id.in_(team), Caregiver.kind == "CARETAKER").order_by(Caregiver.name)):
            if rep.completed_for(db, cg.id, [pid]).get(pid, 0) >= pol["min_completed_tasks"] and not rep.recent(db, Review, user.id, cg.id, pol["rating_window_days"]):
                items.append({"caregiver_id": str(cg.id), "name": cg.name, "patient_id": str(pid)})
    return {"items": items}


# --- writing -----------------------------------------------------------------------------------------------------------

@router.post("/caretakers/{cid}/reviews", status_code=201)
def add_review(cid: uuid.UUID, body: ReviewIn, request: Request, user=Depends(_current_user), db: Session = Depends(get_db)):
    cg = _caretaker(db, cid)
    if user.role not in (Role.PRIMARY_CONTACT, Role.PATIENT): raise HTTPException(403, "Only families and patients write reviews")
    pol = current_policy()
    team_role = TeamRole.PRIMARY_CONTACT if user.role == Role.PRIMARY_CONTACT else TeamRole.PATIENT_SELF
    pid = rep.review_patient(db, user, cg.id, team_role, pol, body.patient_id)
    if pid is None: raise HTTPException(403, f"You can review a caretaker after they have completed {pol['min_completed_tasks']} tasks for your patient")
    if rep.recent(db, Review, user.id, cg.id, pol["rating_window_days"]): raise HTTPException(409, f"You already reviewed this caretaker in the last {pol['rating_window_days']} days; edit that review instead")
    _limit(db, user, pol)
    row = Review(caregiver_id=cg.id, author_user_id=user.id, author_role=user.role.value, patient_id=pid, rating=body.rating, text=body.text.strip(), is_synthetic=user.is_synthetic)
    db.add(row); db.flush()
    if user.role == Role.PRIMARY_CONTACT: rep.close_prompts(db, user, cg.id)
    if cg.user_id:  # the caretaker hears that a review arrived and its stars; never who wrote it
        notify(db, [cg.user_id], pid, "New review on your profile", f"You received a {body.rating}-star review.", kind="STATUS", severity="LOW", channel="INBOX", link="/my-profile")
    _audit(db, user, request, pid, "reputation.review_added", "review", row.id, "A caretaker review was added")
    db.commit()
    return review_dict(row, with_text=True, mine=True, pol=pol)


@router.patch("/reviews/{rid}")
def edit_review(rid: uuid.UUID, body: ReviewPatch, request: Request, user=Depends(_current_user), db: Session = Depends(get_db)):
    row = db.get(Review, rid)
    if not row: raise HTTPException(404, "Review not found")
    pol = current_policy()
    _editable(row, user, pol)
    if body.rating is not None: row.rating = body.rating
    if body.text is not None: row.text = body.text.strip()
    row.updated_at = now()
    _audit(db, user, request, row.patient_id, "reputation.review_edited", "review", row.id, "A caretaker review was edited")
    db.commit()
    return review_dict(row, with_text=True, mine=True, pol=pol)


@router.post("/reviews/{rid}/report", status_code=201)
def report_review(rid: uuid.UUID, body: ReportIn, request: Request, user=Depends(_current_user), db: Session = Depends(get_db)):
    """Only the caretaker a review is about may report it. It stays visible, flagged "reported"; only a moderator's hide flag removes it."""
    row = db.get(Review, rid)
    if not row or row.hidden: raise HTTPException(404, "Review not found")
    cg = db.get(Caregiver, row.caregiver_id)
    if not (cg and cg.user_id == user.id): raise HTTPException(403, "Only the caretaker a review is about can report it")
    pol = current_policy()
    if db.scalar(select(ReviewReport.id).where(ReviewReport.review_id == row.id, ReviewReport.reporter_user_id == user.id)): raise HTTPException(409, "You already reported this review")
    if (db.scalar(select(func.count()).select_from(ReviewReport).where(ReviewReport.reporter_user_id == user.id, ReviewReport.created_at >= now() - timedelta(days=1))) or 0) >= pol["max_reports_per_day"]:
        raise HTTPException(429, "Too many reports today", headers={"Retry-After": "3600"})
    report = ReviewReport(review_id=row.id, reporter_user_id=user.id, reason=body.reason.strip())
    db.add(report)
    _audit(db, user, request, row.patient_id, "reputation.review_reported", "review", row.id, "A review was reported for moderation")
    db.commit()
    return {"id": str(report.id), "status": report.status}


@router.post("/caretakers/{cid}/doctor-ratings", status_code=201)
def add_doctor_rating(cid: uuid.UUID, body: DoctorRatingIn, request: Request, user=Depends(_current_user), db: Session = Depends(get_db)):
    cg = _caretaker(db, cid)
    if user.role != Role.PROFESSIONAL: raise HTTPException(403, "Only healthcare professionals give doctor ratings")
    pid = rep.doctor_patient(db, user, cg.id, body.patient_id)
    if pid is None: raise HTTPException(403, "You can rate a caretaker who has served one of your patients")
    pol = current_policy()
    if rep.recent(db, DoctorRating, user.id, cg.id, pol["rating_window_days"]): raise HTTPException(409, f"You already rated this caretaker in the last {pol['rating_window_days']} days; edit that rating instead")
    _limit(db, user, pol)
    row = DoctorRating(caregiver_id=cg.id, author_user_id=user.id, patient_id=pid, rating=body.rating, note=body.note.strip(), is_synthetic=user.is_synthetic)
    db.add(row); db.flush()
    if cg.user_id:
        notify(db, [cg.user_id], pid, "New rating on your profile", f"A healthcare professional gave you {body.rating} stars.", kind="STATUS", severity="LOW", channel="INBOX", link="/my-profile")
    _audit(db, user, request, pid, "reputation.doctor_rating_added", "doctor_rating", row.id, "A doctor rating was added")
    db.commit()
    return doctor_dict(row, True, pol)


@router.patch("/doctor-ratings/{rid}")
def edit_doctor_rating(rid: uuid.UUID, body: DoctorRatingPatch, request: Request, user=Depends(_current_user), db: Session = Depends(get_db)):
    row = db.get(DoctorRating, rid)
    if not row: raise HTTPException(404, "Rating not found")
    pol = current_policy()
    _editable(row, user, pol)
    if body.rating is not None: row.rating = body.rating
    if body.note is not None: row.note = body.note.strip()
    row.updated_at = now()
    _audit(db, user, request, row.patient_id, "reputation.doctor_rating_edited", "doctor_rating", row.id, "A doctor rating was edited")
    db.commit()
    return doctor_dict(row, True, pol)
