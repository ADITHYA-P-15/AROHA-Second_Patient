"""Task check-ins (flag `checkins`): the caretaker holding a task says "I'm here"; a task with no check-in is searched for cover.

Management by exception: an on-time check-in tells nobody. A missing one (no check-in by start + missing_after_min)
opens one cover request with reason NO_CHECKIN, ranked by the Backup Matcher like any other; the backup must accept.
If the caretaker checks in after all, that request is closed. Rules: core/checkin_policy.py, docs/CHECKIN.md.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.checkin_policy import policy as current_policy, requires_check_in
from app.core.clock import now
from app.core.config import settings
from app.models import ActivityHistory, CareActivity, CareAssignment, Caregiver, CoverRequest, TaskCheckIn, User


class CheckInError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message); self.status = status


def _aware(value):
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


def holder(db: Session, activity_id):
    """(assignment, caregiver) of the confirmed primary for a task, or (None, None)."""
    row = db.execute(select(CareAssignment, Caregiver).join(Caregiver, Caregiver.id == CareAssignment.caregiver_id)
                     .where(CareAssignment.activity_id == activity_id, CareAssignment.role == "PRIMARY", CareAssignment.status == "CONFIRMED")).first()
    return (row[0], row[1]) if row else (None, None)


def status_for(activity, at: datetime, p: dict) -> tuple[str, int]:
    start = _aware(activity.scheduled_start)
    late = max(0, int((at - start).total_seconds() // 60))
    return ("ON_TIME" if at <= start + timedelta(minutes=p["grace_min"]) else "LATE"), (late if at > start + timedelta(minutes=p["grace_min"]) else 0)


def check_in(db: Session, activity: CareActivity, user: User, at: datetime | None = None) -> TaskCheckIn:
    at, p = at or now(), current_policy()
    if not requires_check_in(activity, p): raise CheckInError(422, "This task does not need a check-in")
    if activity.lifecycle_status != "SCHEDULED": raise CheckInError(409, "This task is no longer open")
    _, cg = holder(db, activity.id)
    if cg is None or cg.user_id != user.id: raise CheckInError(403, "Only the caretaker confirmed for this task can check in")
    start, end = _aware(activity.scheduled_start), _aware(activity.scheduled_end)
    if at < start - timedelta(minutes=p["opens_before_min"]): raise CheckInError(409, f"Check-in opens {p['opens_before_min']} minutes before the start")
    if at > end: raise CheckInError(409, "This task has already ended")
    if db.scalar(select(TaskCheckIn.id).where(TaskCheckIn.activity_id == activity.id)): raise CheckInError(409, "Already checked in")
    status, late = status_for(activity, at, p)
    row = TaskCheckIn(activity_id=activity.id, caregiver_id=cg.id, user_id=user.id, checked_in_at=at, status=status, minutes_late=late, is_synthetic=user.is_synthetic)
    db.add(row); db.flush()
    db.add(ActivityHistory(actor_user_id=user.id, patient_id=activity.patient_id, event_type="checkin.recorded", entity_type="care_activity", entity_id=str(activity.id),
                           summary=f"{cg.name} checked in" + (f" {late} min late" if status == "LATE" else ""), payload={"status": status}))
    # They are here after all: a NO_CHECKIN search for this task is no longer needed.
    from app.services import backup_matcher
    for req in db.scalars(select(CoverRequest).where(CoverRequest.activity_id == activity.id, CoverRequest.reason == "NO_CHECKIN", CoverRequest.status.in_(backup_matcher.OPEN_STATUSES))):
        backup_matcher.close(db, req, "CANCELLED", actor=user, note=f"{cg.name} checked in", at=at)
    return row


def run_checkin_tick(db: Session, at: datetime | None = None) -> int:
    """Open one NO_CHECKIN cover request per task whose holder has not checked in by start + missing_after_min. Idempotent."""
    if not settings.feature("checkins"): return 0
    at, p = at or now(), current_policy()
    if not p["categories"]: return 0
    due_before = at - timedelta(minutes=p["missing_after_min"])
    candidates = db.execute(select(CareActivity, CareAssignment).join(CareAssignment, CareAssignment.activity_id == CareActivity.id)
                            .where(CareActivity.lifecycle_status == "SCHEDULED", CareActivity.requires_caregiver.is_(True), CareActivity.category.in_(p["categories"]),
                                   CareActivity.importance.in_(p["importance"]), CareActivity.scheduled_start <= due_before, CareActivity.scheduled_end > at,
                                   CareAssignment.role == "PRIMARY", CareAssignment.status == "CONFIRMED")
                            .order_by(CareActivity.scheduled_start, CareActivity.id)).all()
    from app.services import backup_matcher
    opened = 0
    for activity, assignment in candidates:
        if db.scalar(select(TaskCheckIn.id).where(TaskCheckIn.activity_id == activity.id)): continue
        key = f"nocheckin:{activity.id}:{assignment.id}"
        if db.scalar(select(CoverRequest.id).where(CoverRequest.trigger_key == key)): continue  # once per task and holder, whatever happened since
        if db.scalar(select(CoverRequest.id).where(CoverRequest.activity_id == activity.id, CoverRequest.status.in_(backup_matcher.OPEN_STATUSES))): continue
        cg = db.get(Caregiver, assignment.caregiver_id)
        backup_matcher.open_request(db, activity, "NO_CHECKIN", replaced_caregiver_id=assignment.caregiver_id, trigger_key=key, at=at,
                                    note=f"{cg.name if cg else 'The caretaker'} has not checked in {p['missing_after_min']} minutes after the start.")
        opened += 1
    db.flush()
    return opened


def counts(db: Session, caregiver_ids: list, since: datetime, at: datetime) -> dict:
    """Per caretaker, over tasks they held that needed a check-in and are past the missing point: expected, on time, late.

    Missing = expected - on time - late. A caretaker with no such task has no check-in record at all (None).
    """
    p = current_policy()
    out = {cid: None for cid in caregiver_ids}
    if not caregiver_ids or not p["categories"]: return out
    cutoff = at - timedelta(minutes=p["missing_after_min"])
    rows = db.execute(select(CareAssignment.caregiver_id, CareActivity.id).join(CareActivity, CareActivity.id == CareAssignment.activity_id)
                      .where(CareAssignment.caregiver_id.in_(caregiver_ids), CareAssignment.role == "PRIMARY", CareAssignment.status == "CONFIRMED",
                             CareActivity.requires_caregiver.is_(True), CareActivity.category.in_(p["categories"]), CareActivity.importance.in_(p["importance"]),
                             CareActivity.lifecycle_status != "CANCELLED", CareActivity.scheduled_start >= since, CareActivity.scheduled_start <= cutoff)).all()
    # A task whose holder missed the check-in and was then covered by someone else still counts as a missed check-in for them.
    rows = list(rows) + [(cid, aid) for cid, aid in db.execute(select(CoverRequest.replaced_caregiver_id, CoverRequest.activity_id).join(CareActivity, CareActivity.id == CoverRequest.activity_id)
                                                              .where(CoverRequest.reason == "NO_CHECKIN", CoverRequest.replaced_caregiver_id.in_(caregiver_ids),
                                                                     CareActivity.scheduled_start >= since, CareActivity.scheduled_start <= cutoff))]
    if not rows: return out
    held = {aid: cid for cid, aid in rows}
    seen = {(aid, cid): status for aid, cid, status in db.execute(select(TaskCheckIn.activity_id, TaskCheckIn.caregiver_id, TaskCheckIn.status).where(TaskCheckIn.activity_id.in_(list(held))))}
    for aid, cid in held.items():
        c = out[cid] or {"expected": 0, "on_time": 0, "late": 0}
        c["expected"] += 1
        status = seen.get((aid, cid))
        if status == "ON_TIME": c["on_time"] += 1
        elif status == "LATE": c["late"] += 1
        out[cid] = c
    return out
