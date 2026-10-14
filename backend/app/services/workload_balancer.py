"""Snapshot and apply adapter for the pure workload balancer engine."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.engine.workload import buffered_window
from app.models import (ActivityDependency, AvailabilityOverride, CareActivity, CareAssignment, Caregiver,
                        CaregiverPatientLink, CaregiverWeeklySchedule)

ACTIVE = ("PROPOSED", "AWAITING_CONFIRMATION", "CONFIRMED")
# confirmed_via marker on a backup row that keeps the previous caregiver on standby during a handoff.
HANDOFF_STANDBY = "HANDOFF_STANDBY"


def _aware(value):
    if value is None: return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def horizon(at: datetime, days: int) -> tuple[datetime, datetime]:
    zone = ZoneInfo(settings.app_timezone)
    start = datetime.combine(at.astimezone(zone).date(), datetime.min.time(), zone)
    return start, start + timedelta(days=days)


def _week_bounds(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    zone = ZoneInfo(settings.app_timezone)
    first = start.astimezone(zone).date()
    last = (end - timedelta(microseconds=1)).astimezone(zone).date()
    monday = first - timedelta(days=first.weekday())
    after = last + timedelta(days=7 - last.weekday())
    return datetime.combine(monday, datetime.min.time(), zone), datetime.combine(after, datetime.min.time(), zone)


def _windowed(activity) -> tuple[datetime, datetime]:
    # Read-only: never write aware values back onto ORM rows the caller may commit.
    window = buffered_window({"scheduled_start": _aware(activity.scheduled_start), "scheduled_end": _aware(activity.scheduled_end),
                              "buffer_before_min": activity.buffer_before_min or 0, "buffer_after_min": activity.buffer_after_min or 0})
    return window.start, window.end


def build_snapshot(db: Session, patient_id, start: datetime, end: datetime) -> dict:
    links = db.execute(select(CaregiverPatientLink, Caregiver).join(Caregiver, Caregiver.id == CaregiverPatientLink.caregiver_id)
                       .where(CaregiverPatientLink.patient_id == patient_id)).all()
    ids = [cg.id for _, cg in links]
    schedules: dict = {cid: [] for cid in ids}
    overrides: dict = {cid: [] for cid in ids}
    if ids:
        for row in db.scalars(select(CaregiverWeeklySchedule).where(CaregiverWeeklySchedule.caregiver_id.in_(ids))):
            schedules[row.caregiver_id].append({"weekday": row.weekday, "start_min": row.start_min, "end_min": row.end_min})
        for row in db.scalars(select(AvailabilityOverride).where(AvailabilityOverride.caregiver_id.in_(ids), AvailabilityOverride.cancelled_at.is_(None))):
            overrides[row.caregiver_id].append({"start_at": _aware(row.start_at), "end_at": _aware(row.end_at), "status": row.status, "cancelled_at": None})
    caregivers = [{"id": cg.id, "name": cg.name, "kind": cg.kind, "capabilities": list(cg.capabilities or []),
                   "max_activities_per_day": cg.max_activities_per_day, "max_hours_per_week": cg.max_hours_per_week,
                   "is_active": cg.is_active, "is_designated_backup": link.is_designated_backup,
                   "schedule": schedules[cg.id], "overrides": overrides[cg.id]} for link, cg in links]

    activities = db.scalars(select(CareActivity).where(CareActivity.patient_id == patient_id, CareActivity.lifecycle_status == "SCHEDULED",
                                                       CareActivity.requires_caregiver.is_(True), CareActivity.scheduled_start >= start,
                                                       CareActivity.scheduled_start < end).order_by(CareActivity.scheduled_start)).all()
    activity_ids = [a.id for a in activities]
    linked: dict = {a.id: set() for a in activities}
    if activity_ids:
        for dep in db.scalars(select(ActivityDependency).where(or_(ActivityDependency.activity_id.in_(activity_ids), ActivityDependency.depends_on_activity_id.in_(activity_ids)))):
            if dep.activity_id in linked: linked[dep.activity_id].add(str(dep.depends_on_activity_id))
            if dep.depends_on_activity_id in linked: linked[dep.depends_on_activity_id].add(str(dep.activity_id))
    activity_rows = []
    for a in activities:
        window_start, window_end = _windowed(a)
        activity_rows.append({"id": a.id, "title": a.title, "category": a.category, "importance": a.importance,
                              "required_support": list(a.required_support or []), "scheduled_start": _aware(a.scheduled_start),
                              "window_start": window_start, "window_end": window_end, "requires_caregiver": True, "routine": a.source == "PRESCRIPTION",
                              "linked_activity_ids": sorted(linked[a.id])})

    week_start, week_end = _week_bounds(start, end)
    commitments = []
    backups: dict = {}
    pending_backups: dict = {}  # asked to stand by, not yet confirmed
    if ids:
        rows = db.execute(select(CareAssignment, CareActivity).join(CareActivity, CareActivity.id == CareAssignment.activity_id)
                          .where(CareAssignment.caregiver_id.in_(ids), CareAssignment.status.in_(ACTIVE), CareActivity.lifecycle_status == "SCHEDULED",
                                 CareActivity.scheduled_start >= week_start, CareActivity.scheduled_start < week_end)).all()
        for assignment, activity in rows:
            if assignment.role == "BACKUP":
                if activity.patient_id == patient_id:
                    target = backups if assignment.status == "CONFIRMED" else pending_backups
                    target.setdefault(str(activity.id), []).append(str(assignment.caregiver_id))
                continue
            window_start, window_end = _windowed(activity)
            commitments.append({"assignment_id": assignment.id, "caregiver_id": assignment.caregiver_id, "activity_id": activity.id,
                                "own_patient": activity.patient_id == patient_id, "status": assignment.status, "routine": activity.source == "PRESCRIPTION",
                                "scheduled_start": _aware(activity.scheduled_start), "window_start": window_start, "window_end": window_end})
    return {"caregivers": caregivers, "activities": activity_rows, "commitments": commitments, "confirmed_backups": backups,
            "pending_backups": pending_backups}


class MoveError(Exception):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def apply_move(db: Session, patient, activity_id, from_caregiver_id, to_caregiver_id, *, mode: str, actor, note: str = "", request_id: str = "",
               automatic: bool = False) -> dict:
    """Move one task between caregivers after re-checking everything on current data. Shared by the API and the scheduler.

    In REQUEST_CONFIRMATION mode a confirmed previous holder stays on as a confirmed standby backup until the new
    caregiver confirms, so cover is never dropped. The caller commits.
    """
    from sqlalchemy.exc import IntegrityError
    from app.core.clock import now
    from app.engine.workload_balancer import MIN_LEAD, check_receiver
    from app.models import ActivityHistory, Notification
    from app.services.reassess import TriggerEvent, reassess
    import uuid
    activity_id, from_caregiver_id, to_caregiver_id = (uuid.UUID(str(x)) for x in (activity_id, from_caregiver_id, to_caregiver_id))
    activity = db.get(CareActivity, activity_id)
    if not activity or activity.patient_id != patient.id: raise MoveError("Activity not found", 404)
    at = now()
    if activity.lifecycle_status != "SCHEDULED" or not activity.requires_caregiver: raise MoveError("Only scheduled caregiver tasks can be rebalanced")
    if _aware(activity.scheduled_start) < at + MIN_LEAD: raise MoveError("This task starts within two hours; arrange cover directly with the caregivers")
    current = db.scalar(select(CareAssignment).where(CareAssignment.activity_id == activity.id, CareAssignment.role == "PRIMARY",
                                                     CareAssignment.status.in_(ACTIVE)).with_for_update())
    if not current or current.caregiver_id != from_caregiver_id: raise MoveError("This task's assignment changed; refresh the Workload Balancer")
    # Lock the receiver so concurrent moves of different tasks cannot both pass the limit check.
    if db.scalar(select(Caregiver.id).where(Caregiver.id == to_caregiver_id).with_for_update()) is None:
        raise MoveError("Cannot move this task: Caregiver is not linked to this patient.")
    day_start, _ = horizon(_aware(activity.scheduled_start), 1)
    ok, reasons = check_receiver(build_snapshot(db, patient.id, day_start, day_start + timedelta(days=1)), at, day_start, day_start + timedelta(days=1),
                                 str(activity.id), str(from_caregiver_id), str(to_caregiver_id), settings.app_timezone)
    if not ok: raise MoveError("Cannot move this task: " + " ".join(reasons))
    receiver, donor = db.get(Caregiver, to_caregiver_id), db.get(Caregiver, from_caregiver_id)
    confirmed = mode == "CONFIRM_NOW"
    standby = not confirmed and current.status == "CONFIRMED"
    try:
        with db.begin_nested():
            for backup in db.scalars(select(CareAssignment).where(CareAssignment.activity_id == activity.id, CareAssignment.caregiver_id == receiver.id,
                                                                  CareAssignment.role == "BACKUP", CareAssignment.status.in_(ACTIVE))):
                backup.status = "SUPERSEDED"; backup.updated_at = at
            current.status = "SUPERSEDED"; current.updated_at = at
            db.flush()
            created = CareAssignment(activity_id=activity.id, caregiver_id=receiver.id, role="PRIMARY", status="CONFIRMED" if confirmed else "AWAITING_CONFIRMATION",
                                     assigned_by=actor.id, assigned_at=at, confirmed_at=at if confirmed else None, confirmed_by=actor.id if confirmed else None,
                                     confirmed_via="COORDINATOR" if confirmed else None)
            db.add(created)
            if standby:
                db.add(CareAssignment(activity_id=activity.id, caregiver_id=current.caregiver_id, role="BACKUP", status="CONFIRMED", assigned_by=actor.id,
                                      assigned_at=at, confirmed_at=at, confirmed_by=actor.id, confirmed_via=HANDOFF_STANDBY))
            db.flush()
    except IntegrityError:
        raise MoveError("Another change to this task happened just now; refresh and retry") from None
    when = _aware(activity.scheduled_start).astimezone(ZoneInfo(settings.app_timezone)).strftime("%a %d %b, %H:%M")
    if receiver.user_id:
        db.add(Notification(user_id=receiver.user_id, patient_id=patient.id, kind="STATUS" if confirmed else "DECISION", severity="MEDIUM",
                            title="Care task assigned to you" if confirmed else "Can you take this care task?",
                            body=f"{activity.title} · {when}." + ("" if confirmed else " Please confirm or decline in Care Plan."), requires_ack=not confirmed, channel="INBOX"))
    if donor and donor.user_id and donor.user_id != actor.id:
        why = "because your workload is above your limit" if automatic else "to balance workload"
        db.add(Notification(user_id=donor.user_id, patient_id=patient.id, kind="STATUS", severity="LOW", title="A care task was moved off your plan",
                            body=f"{activity.title} · {when} is moving to {receiver.name} {why}." + (f" You stay as backup until {receiver.name} confirms." if standby else ""),
                            requires_ack=False, channel="INBOX"))
    db.add(ActivityHistory(actor_user_id=None if automatic else actor.id, patient_id=patient.id, event_type="workload.rebalanced", entity_type="care_assignment",
                           entity_id=str(created.id), summary=("Automatic: " if automatic else "") + f"task moved from {donor.name if donor else 'caregiver'} to {receiver.name} to balance workload",
                           payload={"activity_id": str(activity.id), "from_caregiver_id": str(from_caregiver_id), "to_caregiver_id": str(receiver.id),
                                    "superseded_assignment_id": str(current.id), "mode": mode, "standby_backup": standby, "automatic": automatic, "note": (note or "").strip()},
                           request_id=request_id))
    reassess(db, [patient.id], TriggerEvent.ASSIGNMENT_ADDED, {"assignment_ids": [str(created.id)], "source": "workload_balancer"})
    message = (f"{activity.title} is now confirmed with {receiver.name}." if confirmed
               else f"{receiver.name} has been asked to confirm {activity.title}. Support shows as not confirmed until they do"
               + (f"; {donor.name if donor else 'the previous caregiver'} stays as confirmed backup meanwhile." if standby else "."))
    return {"activity_id": activity.id, "superseded_assignment_id": current.id, "standby_backup": standby,
            "assignment": {"id": created.id, "caregiver_id": receiver.id, "caregiver_name": receiver.name, "status": created.status}, "message": message}
