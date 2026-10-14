"""Persistence and snapshot services for the caregiver Command Center."""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.config import settings
from app.engine.attention import AttentionItem, evaluate_attention
from app.engine.availability import is_available_for
from app.engine.daily_plan import build_daily_plan
from app.engine.workload import buffered_window, overlaps_for, workload
from app.models import (
    ActionItem, ActivityHistory, AvailabilityOverride,
    CareActivity, CareAssignment, Caregiver, CaregiverWeeklySchedule,
    CareTeamMember, CommandCenterSetting, Incident,
    Patient, Role, TeamRole,
)


DEFAULT_SETTINGS = {
    "morning_brief_time": "07:00", "handover_time": "19:30",
    "handover_autopublish_after_min": 60,
    "daypart_boundaries": {"early": "06:00", "morning": "08:00", "afternoon": "12:00", "evening": "17:00", "night": "21:00"},
    "routine_rules": {"categories": ["DAILY_ROUTINE", "MEDICATION", "MOBILITY"], "max_importance": "MEDIUM", "merge_gap_minutes": 30},
    "snooze_max_minutes_by_severity": {"LOW": 1440, "MEDIUM": 720, "HIGH": 60, "CRITICAL": 15},
    "suppress_hours": 12,
}


def _aware(value):
    if value is not None and value.tzinfo is None: return value.replace(tzinfo=UTC)
    return value


def settings_for(db: Session, patient_id):
    row = db.get(CommandCenterSetting, patient_id)
    return dict(DEFAULT_SETTINGS) if row is None else {
        "morning_brief_time": row.morning_brief_time, "handover_time": row.handover_time,
        "handover_autopublish_after_min": row.handover_autopublish_after_min,
        "daypart_boundaries": row.daypart_boundaries or DEFAULT_SETTINGS["daypart_boundaries"],
        "routine_rules": row.routine_rules or DEFAULT_SETTINGS["routine_rules"],
        "snooze_max_minutes_by_severity": row.snooze_max_minutes_by_severity or DEFAULT_SETTINGS["snooze_max_minutes_by_severity"],
        "suppress_hours": row.suppress_hours,
    }


def build_snapshot(db: Session, patient_id, at: datetime | None = None, day: date | None = None):
    at = at or now()
    day = day or at.astimezone(ZoneInfo(settings.app_timezone)).date()
    zone = ZoneInfo(settings.app_timezone)
    start = datetime.combine(day, time.min, zone).astimezone(UTC) - timedelta(days=1)
    end = datetime.combine(day + timedelta(days=8), time.min, zone).astimezone(UTC)
    patient = db.get(Patient, patient_id)
    activities = db.scalars(select(CareActivity).where(CareActivity.patient_id == patient_id, CareActivity.scheduled_start >= start, CareActivity.scheduled_start < end).order_by(CareActivity.scheduled_start)).all()
    activity_ids = [a.id for a in activities]
    assignments = db.scalars(select(CareAssignment).where(CareAssignment.activity_id.in_(activity_ids))).all() if activity_ids else []
    caregiver_ids = {a.caregiver_id for a in assignments}
    caregivers = {c.id: c for c in db.scalars(select(Caregiver).where(Caregiver.id.in_(caregiver_ids))).all()} if caregiver_ids else {}
    if caregiver_ids:
        schedules = db.scalars(select(CaregiverWeeklySchedule).where(CaregiverWeeklySchedule.caregiver_id.in_(caregiver_ids))).all()
        overrides = db.scalars(select(AvailabilityOverride).where(AvailabilityOverride.caregiver_id.in_(caregiver_ids), AvailabilityOverride.end_at > start, AvailabilityOverride.start_at < end)).all()
        for caregiver in caregivers.values():
            caregiver.schedule = [s for s in schedules if s.caregiver_id == caregiver.id]
            caregiver.overrides = [o for o in overrides if o.caregiver_id == caregiver.id]
    assignment_rows = []
    activity_by_id = {a.id: a for a in activities}
    for assignment in assignments:
        activity = activity_by_id.get(assignment.activity_id)
        caregiver = caregivers.get(assignment.caregiver_id)
        assignment_rows.append((assignment, activity))
        if assignment.role == "PRIMARY" and caregiver and activity and assignment.status in {"CONFIRMED", "AWAITING_CONFIRMATION", "PROPOSED"}:
            assignment.caregiver_available = is_available_for(caregiver, buffered_window(activity), settings.app_timezone).available
            assignment.caregiver_name = caregiver.name
    total_work = {cgid: workload(assignment_rows, cgid, settings.app_timezone) for cgid in caregivers}
    activity_snapshots = []
    for activity in activities:
        primary = next((x for x in assignments if x.activity_id == activity.id and x.role == "PRIMARY" and x.status == "CONFIRMED"), None)
        cg = caregivers.get(primary.caregiver_id) if primary else None
        capability_match = None if not (primary and cg and activity.required_support) else set(activity.required_support).issubset(set(cg.capabilities or []))
        others = [other for other in activities if other.id != activity.id]
        overlap_conflict = bool(cg and overlaps_for(activity, [other for other in others if any(x.caregiver_id == cg.id and x.activity_id == other.id and x.role == "PRIMARY" and x.status == "CONFIRMED" for x in assignments)]))
        over_limit = False
        if cg and primary:
            info = total_work[cg.id]
            day_key = activity.scheduled_start.astimezone(zone).date().isoformat()
            week_key = f"{activity.scheduled_start.astimezone(zone).isocalendar().year}-W{activity.scheduled_start.astimezone(zone).isocalendar().week:02d}"
            over_limit = info["by_day"].get(day_key, {}).get("confirmed", 0) > cg.max_activities_per_day or info["by_week"].get(week_key, {}).get("confirmed_hours", 0) > cg.max_hours_per_week
        activity_snapshots.append({"id": activity.id, "patient_id": activity.patient_id, "series_id": activity.series_id, "title": activity.title, "category": activity.category, "scheduled_start": _aware(activity.scheduled_start), "scheduled_end": _aware(activity.scheduled_end), "deadline": _aware(activity.deadline), "importance": activity.importance, "requires_caregiver": activity.requires_caregiver, "required_support": activity.required_support or [], "buffer_before_min": activity.buffer_before_min, "buffer_after_min": activity.buffer_after_min, "lifecycle_status": activity.lifecycle_status, "acknowledged_at": activity.acknowledged_at, "capability_match": capability_match, "overlap_conflict": overlap_conflict, "over_limit": over_limit})
    assignment_snapshots = [{"id": x.id, "activity_id": x.activity_id, "caregiver_id": x.caregiver_id, "caregiver_user_id": caregivers.get(x.caregiver_id).user_id if caregivers.get(x.caregiver_id) else None, "caregiver_name": caregivers.get(x.caregiver_id).name if caregivers.get(x.caregiver_id) else "", "role": x.role, "status": x.status, "assigned_at": _aware(x.assigned_at), "confirmed_at": _aware(x.confirmed_at), "caregiver_available": getattr(x, "caregiver_available", None)} for x in assignments]
    incidents = db.scalars(select(Incident).where(Incident.patient_id == patient_id, Incident.status.in_(("OPEN", "ACKNOWLEDGED")))).all()
    incident_snapshots = [{"id": x.id, "current_level": x.current_level, "status": x.status, "title": x.title, "safe_summary": x.safe_summary, "related_activity_id": x.related_activity_id, "current_deadline_at": _aware(x.current_deadline_at), "acknowledged_at": _aware(x.acknowledged_at)} for x in incidents]
    return {"patient": patient, "day": day, "activities": activity_snapshots, "assignments": assignment_snapshots, "incidents": incident_snapshots, "caregivers": caregivers, "settings": settings_for(db, patient_id)}


def _history(db, patient_id, event, entity_id, summary):
    db.add(ActivityHistory(patient_id=patient_id, event_type=event, entity_type="action_item", entity_id=str(entity_id), summary=summary, payload={}))


def _advisory_lock(db, patient_id):
    if db.bind and db.bind.dialect.name == "postgresql":
        lock_id = int.from_bytes(patient_id.bytes[:8], "big", signed=True)
        db.execute(__import__("sqlalchemy").text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id})


def reconcile_patient(db: Session, patient_id, at: datetime | None = None):
    """Idempotently upsert current derived attention and auto-resolve cleared conditions."""
    at = at or now()
    _advisory_lock(db, patient_id)
    snap = build_snapshot(db, patient_id, at)
    detected = evaluate_attention(snap, at, snap["settings"])
    active_rows = db.scalars(select(ActionItem).where(ActionItem.patient_id == patient_id, ActionItem.status.in_(("OPEN", "SNOOZED")))).all()
    active_by_key = {row.dedupe_key: row for row in active_rows}
    historical = db.scalars(select(ActionItem).where(ActionItem.patient_id == patient_id, ActionItem.status.in_(("DISMISSED", "AUTO_RESOLVED", "DONE")))).all()
    past_by_key = {row.dedupe_key: row for row in historical}
    seen = set()
    for item in detected:
        seen.add(item.dedupe_key)
        row = active_by_key.get(item.dedupe_key)
        if row is None:
            row = past_by_key.get(item.dedupe_key)
            if row and row.status == "DISMISSED" and row.suppressed_until and _aware(row.suppressed_until) > _aware(at):
                row.last_seen_at = at
                continue
            if row and row.status in {"DISMISSED", "AUTO_RESOLVED", "DONE"}:
                row.status, row.resolution_reason, row.resolved_at = "OPEN", None, None
                row.reopened_count += 1
                row.first_seen_at = at
                row.version += 1
            else:
                row = ActionItem(id=uuid.uuid4(), patient_id=patient_id, dedupe_key=item.dedupe_key, kind=item.kind, source="INCIDENT" if item.incident_id else "DERIVED", title=item.title, reason=item.reason, reasons=list(item.reasons), severity=item.severity, related_activity_ids=list(item.activity_ids), related_incident_id=uuid.UUID(item.incident_id) if item.incident_id else None, due_at=item.due_at, suggested_actions=list(item.suggested_actions), first_seen_at=at, last_seen_at=at)
                db.add(row)
                _history(db, patient_id, "ACTION_ITEM_CREATED", row.id, "A coordination item needs review")
        row.kind, row.title, row.reason = item.kind, item.title, item.reason
        row.reasons, row.severity = list(item.reasons), item.severity
        row.related_activity_ids, row.related_incident_id = list(item.activity_ids), uuid.UUID(item.incident_id) if item.incident_id else None
        row.due_at, row.suggested_actions, row.last_seen_at = item.due_at, list(item.suggested_actions), at
        if row.status == "SNOOZED" and row.snoozed_until and _aware(row.snoozed_until) <= _aware(at):
            row.status, row.snoozed_until = "OPEN", None
            row.version += 1
    for row in active_rows:
        if row.source in {"DERIVED", "INCIDENT"} and row.dedupe_key not in seen:
            row.status, row.resolution_reason, row.resolved_at = "AUTO_RESOLVED", "CONDITION_CLEARED", at
            row.resolution_note = "The underlying coordination condition cleared."
            row.version += 1
            _history(db, patient_id, "ACTION_ITEM_RESOLVED", row.id, "A coordination condition cleared")
    db.flush()
    return detected


def plan_and_attention(db: Session, patient_id, at: datetime | None = None, day: date | None = None):
    at = at or now()
    detected = reconcile_patient(db, patient_id, at)
    snap = build_snapshot(db, patient_id, at, day)
    plan = build_daily_plan(snap["activities"], snap["assignments"], detected, now=at, day=snap["day"], timezone_name=settings.app_timezone, settings=snap["settings"])
    rows = db.scalars(select(ActionItem).where(ActionItem.patient_id == patient_id).order_by(ActionItem.first_seen_at.desc())).all()
    active = [x for x in rows if x.status == "OPEN"]
    accessible = {m.user_id for m in db.scalars(select(CareTeamMember).where(CareTeamMember.patient_id == patient_id)).all()}
    pending = [x for x in active if x.source == "MANUAL"]
    decisions = [x for x in active if x.kind in {"ASSIGNMENT_UNCONFIRMED", "STALE_DECISION"}]
    needs = [x for x in active if x.severity in {"HIGH", "CRITICAL"} or x.kind.startswith("INCIDENT")]
    risk = [x for x in active if x not in needs and x not in decisions and x not in pending]
    return {"snapshot": snap, "plan": plan, "active_items": active, "needs_now": needs, "at_risk": risk, "decisions_waiting": decisions, "pending_actions": pending, "handled": [x for x in rows if x.status in {"AUTO_RESOLVED", "DONE"} and _aware(x.resolved_at or x.last_seen_at).date() == snap["day"]], "accessible_user_ids": accessible}


def run_command_center_tick(db: Session, at: datetime | None = None):
    """Re-evaluate time-driven attention (overdue, starting soon, snooze wake-ups) for every patient."""
    at = at or now()
    for patient_id in db.scalars(select(Patient.id).order_by(Patient.id)).all():
        reconcile_patient(db, patient_id, at)
    db.flush()
    return []


def serialize_action(row: ActionItem, at=None):
    at = at or now()
    age = max(0, int((_aware(at) - _aware(row.first_seen_at)).total_seconds()))
    return {"id": str(row.id), "patient_id": str(row.patient_id), "dedupe_key": row.dedupe_key, "kind": row.kind, "source": row.source, "title": row.title, "reason": row.reason, "reasons": row.reasons or [], "severity": row.severity, "related_activity_ids": row.related_activity_ids or [], "related_incident_id": str(row.related_incident_id) if row.related_incident_id else None, "owner_user_id": str(row.owner_user_id) if row.owner_user_id else None, "assigned_to_user_id": str(row.assigned_to_user_id) if row.assigned_to_user_id else None, "due_at": _aware(row.due_at).isoformat() if row.due_at else None, "status": row.status, "snoozed_until": _aware(row.snoozed_until).isoformat() if row.snoozed_until else None, "age_seconds": age, "resolution_reason": row.resolution_reason, "resolution_note": row.resolution_note, "suggested_actions": row.suggested_actions or [], "reopened_count": row.reopened_count, "version": row.version}
