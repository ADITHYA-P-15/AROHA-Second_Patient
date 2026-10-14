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
                              "window_start": window_start, "window_end": window_end, "requires_caregiver": True,
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
                                "own_patient": activity.patient_id == patient_id, "status": assignment.status,
                                "scheduled_start": _aware(activity.scheduled_start), "window_start": window_start, "window_end": window_end})
    return {"caregivers": caregivers, "activities": activity_rows, "commitments": commitments, "confirmed_backups": backups,
            "pending_backups": pending_backups}
