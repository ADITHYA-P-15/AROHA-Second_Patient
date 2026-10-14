"""Care-activity status from the clock: PENDING -> COMPLETED or MISSED.

Stored lifecycle values: SCHEDULED (shown as PENDING), COMPLETED, MISSED, CANCELLED. Every transition to MISSED goes
through `_on_missed`, which is the single place to add the planned SMS to the caretaker and primary contact.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.config import settings
from app.models import ActivityHistory, CareActivity, CareAssignment, Caregiver, CareTeamMember, Notification, TeamRole

LATE_WINDOW = timedelta(hours=24)
EARLY_WINDOW = timedelta(hours=2)  # cannot be recorded as done more than two hours before it starts  # a missed activity can still be recorded as done (late) for a day
DISPLAY = {"SCHEDULED": "PENDING", "COMPLETED": "COMPLETED", "MISSED": "MISSED", "CANCELLED": "CANCELLED"}


class StatusError(Exception):
    pass


def _aware(value):
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


def due_by(activity: CareActivity) -> datetime:
    """The moment an undone activity becomes missed: its deadline, else its scheduled end."""
    return _aware(activity.deadline or activity.scheduled_end)


def care_status(activity: CareActivity) -> str:
    return DISPLAY.get(activity.lifecycle_status, activity.lifecycle_status)


def _holder_user_id(db: Session, activity: CareActivity):
    return db.scalar(select(Caregiver.user_id).join(CareAssignment, CareAssignment.caregiver_id == Caregiver.id)
                     .where(CareAssignment.activity_id == activity.id, CareAssignment.role == "PRIMARY", CareAssignment.status == "CONFIRMED"))


def _on_missed(db: Session, activity: CareActivity, at: datetime) -> None:
    """Tell the assigned caretaker and the primary contacts. Future: also send an SMS to both (see docs/PRODUCT_SPEC.md)."""
    when = _aware(activity.scheduled_start).astimezone(ZoneInfo(settings.app_timezone)).strftime("%a %d %b, %H:%M")
    what = "dose" if activity.source == "PRESCRIPTION" else "appointment" if activity.category == "APPOINTMENT" else "care activity"
    recipients = set(db.scalars(select(CareTeamMember.user_id).where(CareTeamMember.patient_id == activity.patient_id, CareTeamMember.team_role == TeamRole.PRIMARY_CONTACT)))
    holder = _holder_user_id(db, activity)
    if holder: recipients.add(holder)
    for user_id in recipients:
        db.add(Notification(user_id=user_id, patient_id=activity.patient_id, kind="REMINDER", severity="HIGH", title=f"Missed {what}: {activity.title}"[:160],
                            body=f"{activity.title} was due {when} and has not been recorded as done. If it was done, record it in My Day or Care Plan.",
                            requires_ack=True, channel="ALERT"))


def mark_missed(db: Session, at: datetime | None = None, patient_id=None) -> int:
    """Move every pending activity whose deadline has passed to MISSED. Idempotent; run by the scheduler."""
    at = at or now()
    query = select(CareActivity).where(CareActivity.lifecycle_status == "SCHEDULED", CareActivity.requires_caregiver.is_(True),
                                       or_(CareActivity.deadline <= at, (CareActivity.deadline.is_(None)) & (CareActivity.scheduled_end <= at)))
    if patient_id is not None: query = query.where(CareActivity.patient_id == patient_id)
    changed = 0
    for activity in db.scalars(query).all():
        if due_by(activity) > at: continue  # timezone-naive rows from SQLite: re-check in Python
        activity.lifecycle_status, activity.missed_at = "MISSED", at
        db.add(ActivityHistory(actor_user_id=None, patient_id=activity.patient_id, event_type="activity.missed", entity_type="care_activity",
                               entity_id=str(activity.id), summary=f"{activity.title} was missed", payload={"due_by": due_by(activity).isoformat()}, request_id=""))
        # Only alert for recent misses: a backlog (e.g. the first run after an upgrade) is marked quietly.
        if at - due_by(activity) <= LATE_WINDOW:
            _on_missed(db, activity, at)
        changed += 1
    return changed


def complete(db: Session, activity: CareActivity, user_id, at: datetime | None = None) -> CareActivity:
    """Record an activity as done. A missed one can still be recorded within a day, and is kept as completed late."""
    at = at or now()
    if activity.lifecycle_status == "COMPLETED": return activity
    if activity.lifecycle_status == "CANCELLED": raise StatusError("This activity was cancelled")
    if activity.lifecycle_status == "SCHEDULED" and _aware(activity.scheduled_start) - at > EARLY_WINDOW: raise StatusError("Too early: record it as done on the day, once it is done")
    if activity.lifecycle_status == "MISSED" and at - due_by(activity) > LATE_WINDOW: raise StatusError("Too late to record this activity as done")
    late = activity.lifecycle_status == "MISSED" or at > due_by(activity)
    activity.lifecycle_status, activity.completed_at, activity.completed_by, activity.completed_late = "COMPLETED", at, user_id, late
    return activity
