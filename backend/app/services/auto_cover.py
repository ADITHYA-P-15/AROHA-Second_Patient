"""Automatic coordination: cover unassigned activities and relieve overloaded caretakers without a primary-contact tap.

Every step still needs the replacement caretaker to accept; until then the activity shows as not confirmed and the
previous holder (if any) keeps it. The primary contact is told only when nobody eligible can or will take it.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.config import settings
from app.engine.workload_balancer import MIN_LEAD, evaluate_workload
from app.models import CareActivity, CareAssignment, CareTeamMember, CoverRequest, Patient, TeamRole, User
from app.services import backup_matcher as matcher
from app.services.workload_balancer import ACTIVE, MoveError, _aware, apply_move, build_snapshot, horizon

AUTO_COVER_WINDOW = timedelta(hours=72)
REBALANCE_DAYS = 7
log = logging.getLogger("second_patient")


def cover_unassigned(db: Session, patient_id, at: datetime) -> int:
    """Open (and automatically offer) cover for upcoming activities that nobody holds."""
    opened = 0
    rows = db.scalars(select(CareActivity).where(CareActivity.patient_id == patient_id, CareActivity.lifecycle_status == "SCHEDULED",
                                                 CareActivity.requires_caregiver.is_(True), CareActivity.scheduled_start > at,
                                                 CareActivity.scheduled_start <= at + AUTO_COVER_WINDOW)).all()
    for activity in rows:
        if db.scalar(select(CareAssignment.id).where(CareAssignment.activity_id == activity.id, CareAssignment.role == "PRIMARY", CareAssignment.status.in_(ACTIVE))):
            continue
        key = f"unassigned:{activity.id}"
        if db.scalar(select(CoverRequest.id).where((CoverRequest.trigger_key == key) | ((CoverRequest.activity_id == activity.id) & CoverRequest.status.in_(matcher.OPEN_STATUSES)))):
            continue
        matcher.open_request(db, activity, "UNASSIGNED", note="No caretaker is assigned yet", trigger_key=key, at=at)
        opened += 1
    return opened


def retry_open_requests(db: Session, patient_id, at: datetime) -> int:
    """Requests left OPEN (everyone said no, or nobody qualified) are offered again when someone becomes eligible."""
    offered = 0
    for req in db.scalars(select(CoverRequest).where(CoverRequest.patient_id == patient_id, CoverRequest.status == "OPEN")).all():
        ranked = matcher.ranking(db, req, at)
        if ranked["best"]:
            matcher.offer(db, req, ranked["best"]["caregiver_id"], actor=None, auto_advance=True, at=at)
            offered += 1
    return offered


def relieve_overload(db: Session, patient: Patient, at: datetime) -> int:
    """Apply the Workload Balancer's top suggestion for an overloaded caretaker: one move per patient per run."""
    start, end = horizon(at, REBALANCE_DAYS)
    result = evaluate_workload(build_snapshot(db, patient.id, start, end), at, start, end, settings.app_timezone)
    move = next((r for r in result["recommendations"] if r["kind"] == "REDISTRIBUTE" and r["priority"] in ("HIGH", "MEDIUM")
                 and _aware(r["activity"]["scheduled_start"]) >= at + MIN_LEAD), None)
    if move is None: return 0
    actor = db.scalar(select(User).join(CareTeamMember, CareTeamMember.user_id == User.id).where(
        CareTeamMember.patient_id == patient.id, CareTeamMember.team_role == TeamRole.PRIMARY_CONTACT).order_by(CareTeamMember.is_primary_coordinator.desc()))
    if actor is None: return 0
    try:
        apply_move(db, patient, move["activity"]["id"], move["from"]["caregiver_id"], move["to"]["caregiver_id"], mode="REQUEST_CONFIRMATION",
                   actor=actor, note="Automatic: caretaker over their workload limit", automatic=True)
    except MoveError:
        return 0
    return 1


def run_auto_coordination(db: Session, at: datetime | None = None) -> int:
    if not settings.auto_coordination: return 0
    at = at or now()
    changed = 0
    for patient in db.scalars(select(Patient)).all():
        try:
            with db.begin_nested():
                changed += cover_unassigned(db, patient.id, at) + retry_open_requests(db, patient.id, at) + relieve_overload(db, patient, at)
        except Exception:
            log.exception("automatic coordination failed for patient %s", patient.id)
    return changed
