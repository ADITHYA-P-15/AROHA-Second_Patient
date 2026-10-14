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
from app.engine.brief_builder import build_handover_brief, build_morning_brief
from app.engine.daily_plan import build_daily_plan
from app.engine.workload import buffered_window, overlaps_for, workload
from app.models import (
    ActionItem, ActivityHistory, AvailabilityOverride, BriefAcknowledgement,
    CareActivity, CareAssignment, Caregiver, CaregiverWeeklySchedule,
    CareTeamMember, CommandCenterSetting, DailyBrief, HandoverItem, Incident,
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
    brief_rows = db.scalars(select(DailyBrief).where(DailyBrief.patient_id == patient_id, DailyBrief.for_date >= datetime.combine(day - timedelta(days=1), time.min), DailyBrief.for_date <= datetime.combine(day, time.max), DailyBrief.kind == "HANDOVER")).all()
    brief_ids = [b.id for b in brief_rows]
    acked = db.scalars(select(BriefAcknowledgement.brief_id).where(BriefAcknowledgement.brief_id.in_(brief_ids))).all() if brief_ids else []
    brief_snapshots = [{"id": b.id, "status": b.status, "to_user_id": b.to_user_id, "generated_at": _aware(b.generated_at)} for b in brief_rows]
    return {"patient": patient, "day": day, "activities": activity_snapshots, "assignments": assignment_snapshots, "incidents": incident_snapshots, "briefs": brief_snapshots, "acknowledged_brief_ids": acked, "caregivers": caregivers, "settings": settings_for(db, patient_id)}


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
    brief_day = datetime.combine(snap["day"], time.min)
    handovers = db.scalars(select(DailyBrief).where(DailyBrief.patient_id == patient_id, DailyBrief.kind == "HANDOVER", DailyBrief.for_date == brief_day, DailyBrief.status == "PUBLISHED")).all()
    pending = [x for x in active if x.source == "MANUAL"]
    decisions = [x for x in active if x.kind in {"ASSIGNMENT_UNCONFIRMED", "STALE_DECISION"}]
    needs = [x for x in active if x.severity in {"HIGH", "CRITICAL"} or x.kind.startswith("INCIDENT")]
    risk = [x for x in active if x not in needs and x not in decisions and x not in pending]
    brief_rows = db.scalars(select(DailyBrief).where(DailyBrief.patient_id == patient_id, DailyBrief.for_date == brief_day, DailyBrief.kind == "MORNING").order_by(DailyBrief.version.desc())).all()
    handover = handovers[-1] if handovers else db.scalar(select(DailyBrief).where(DailyBrief.patient_id == patient_id, DailyBrief.for_date == brief_day, DailyBrief.kind == "HANDOVER", DailyBrief.status == "DRAFT").order_by(DailyBrief.version.desc()))
    return {"snapshot": snap, "plan": plan, "active_items": active, "needs_now": needs, "at_risk": risk, "decisions_waiting": decisions, "pending_actions": pending, "handled": [x for x in rows if x.status in {"AUTO_RESOLVED", "DONE"} and _aware(x.resolved_at or x.last_seen_at).date() == snap["day"]], "morning_brief": brief_rows[0] if brief_rows else None, "handover_brief": handover, "accessible_user_ids": accessible}


def brief_snapshot(data):
    snap, plan = data["snapshot"], data["plan"]
    as_item = lambda x: {"title": x.title, "reason": x.reason, "severity": x.severity}
    open_incidents = [i["title"] for i in snap["incidents"]]
    return {"attention": {"needs_now": [as_item(x) for x in data["needs_now"]], "decisions_waiting": [as_item(x) for x in data["decisions_waiting"]], "at_risk": [as_item(x) for x in data["at_risk"]]}, "plan": plan, "counts": {"on_track": max(0, len(plan["handled"]) + sum(len(b.get("activities", [])) for b in plan["blocks"] if b["kind"] == "ROUTINE_BLOCK"))}, "incidents_last_24h": open_incidents, "carry_overs": [x.title for x in data["pending_actions"]]}


def create_brief(db, patient_id, kind, for_date: date, actor_id=None, *, notes="", regenerate=False):
    target_date = datetime.combine(for_date, time.min)
    target_status = "PUBLISHED" if kind == "MORNING" else "DRAFT"
    existing = db.scalar(select(DailyBrief).where(DailyBrief.patient_id == patient_id, DailyBrief.kind == kind, DailyBrief.for_date == target_date, DailyBrief.status == target_status).order_by(DailyBrief.version.desc()))
    if existing and (kind != "MORNING" or not regenerate): return existing
    snapshot = plan_and_attention(db, patient_id, day=for_date)
    if kind == "MORNING":
        built = build_morning_brief(brief_snapshot(snapshot), now=now())
        status = "PUBLISHED"
    else:
        tomorrow_snap = build_snapshot(db, patient_id, day=for_date + timedelta(days=1))
        tomorrow_plan = build_daily_plan(tomorrow_snap["activities"], tomorrow_snap["assignments"], (), now=now(), day=for_date + timedelta(days=1), timezone_name=settings.app_timezone, settings=tomorrow_snap["settings"])
        built = build_handover_brief({
            "done_today": [x["title"] for x in snapshot["plan"]["handled"]],
            "carry_over": [x.title for x in snapshot["pending_actions"]],
            "incidents": [x["title"] for x in snapshot["snapshot"]["incidents"]],
            "pending_actions": [x.title for x in snapshot["pending_actions"]],
            "tomorrow": [x["title"] for x in tomorrow_plan["blocks"]],
        }, now=now(), notes=notes)
        status = "DRAFT"
    version = existing.version + 1 if existing and regenerate else (db.scalar(select(DailyBrief.version).where(DailyBrief.patient_id == patient_id, DailyBrief.kind == kind, DailyBrief.for_date == target_date).order_by(DailyBrief.version.desc())) or 0) + 1
    row = existing if existing and regenerate else DailyBrief(id=uuid.uuid4(), patient_id=patient_id, kind=kind, for_date=target_date, status=status, generated_at=now(), generated_by=actor_id, author_user_id=actor_id, from_user_id=actor_id if kind == "HANDOVER" else None, auto_generated=False, content=built["content"], rendered_text=built["rendered_text"], rendered_html=built["rendered_html"], ai_enhanced=False, version=version)
    if existing and regenerate:
        row.generated_at, row.generated_by = now(), actor_id
        row.content, row.rendered_text, row.rendered_html, row.version = built["content"], built["rendered_text"], built["rendered_html"], version
    else:
        db.add(row)
    if kind == "HANDOVER":
        recipient = db.scalar(select(Caregiver.user_id).join(CareAssignment, CareAssignment.caregiver_id == Caregiver.id).join(CareActivity, CareActivity.id == CareAssignment.activity_id).where(CareActivity.patient_id == patient_id, CareActivity.lifecycle_status == "SCHEDULED", CareActivity.scheduled_start >= now(), CareAssignment.role == "PRIMARY", CareAssignment.status == "CONFIRMED", Caregiver.user_id.is_not(None), Caregiver.user_id != actor_id).order_by(CareActivity.scheduled_start).limit(1))
        recipient = recipient or db.scalar(select(CareTeamMember.user_id).where(CareTeamMember.patient_id == patient_id, CareTeamMember.team_role == TeamRole.COORDINATOR, CareTeamMember.is_primary_coordinator.is_(True)))
        row.to_user_id = recipient
        for item in snapshot["plan"]["handled"]:
            db.add(HandoverItem(brief_id=row.id, activity_id=item["activity_id"], disposition="DONE"))
        for item in snapshot["pending_actions"]:
            db.add(HandoverItem(brief_id=row.id, action_item_id=item.id, disposition="CARRY_OVER"))
    db.add(ActivityHistory(patient_id=patient_id, actor_user_id=actor_id, event_type="BRIEF_GENERATED", entity_type="daily_brief", entity_id=str(row.id), summary=f"{kind.title()} brief generated", payload={}))
    db.flush()
    return row


def run_command_center_tick(db: Session, at: datetime | None = None):
    """Catch up scheduled briefs and handover publication on restarts and scheduler ticks."""
    at = at or now()
    zone = ZoneInfo(settings.app_timezone)
    local = at.astimezone(zone)
    today = local.date()
    outcomes = []
    patients = db.scalars(select(Patient).order_by(Patient.id)).all()
    for patient in patients:
        prefs = settings_for(db, patient.id)
        morning_at = datetime.combine(today, time.fromisoformat(prefs["morning_brief_time"]), zone)
        handover_at = datetime.combine(today, time.fromisoformat(prefs["handover_time"]), zone)
        target = datetime.combine(today, time.min)
        morning = db.scalar(select(DailyBrief).where(DailyBrief.patient_id == patient.id, DailyBrief.kind == "MORNING", DailyBrief.for_date == target, DailyBrief.status == "PUBLISHED"))
        if local >= morning_at and not morning:
            row = create_brief(db, patient.id, "MORNING", today, None)
            row.auto_generated = True
            outcomes.append((str(patient.id), "MORNING"))
        drafts = db.scalars(select(DailyBrief).where(DailyBrief.patient_id == patient.id, DailyBrief.kind == "HANDOVER", DailyBrief.for_date == target)).all()
        if local >= handover_at and not drafts:
            row = create_brief(db, patient.id, "HANDOVER", today, None)
            row.auto_generated = True
            row.rendered_text = "Auto-generated draft — not reviewed.\n\n" + row.rendered_text[:1900]
            outcomes.append((str(patient.id), "HANDOVER_DRAFT"))
            drafts = [row]
        for draft in drafts:
            age = at - _aware(draft.generated_at)
            if draft.status == "DRAFT" and age >= timedelta(minutes=prefs["handover_autopublish_after_min"]):
                draft.status, draft.auto_generated = "PUBLISHED", True
                if not draft.rendered_text.startswith("Auto-generated draft — not reviewed."):
                    draft.rendered_text = "Auto-generated draft — not reviewed.\n\n" + draft.rendered_text[:1900]
                db.add(ActivityHistory(patient_id=patient.id, event_type="BRIEF_PUBLISHED", entity_type="daily_brief", entity_id=str(draft.id), summary="An unreviewed handover draft was auto-published", payload={}))
                if draft.to_user_id:
                    from app.models import Notification
                    db.add(Notification(user_id=draft.to_user_id, patient_id=patient.id, kind="DIGEST", severity="LOW", title="Care handover ready", body="An auto-generated, unreviewed handover is ready for your review.", requires_ack=True, channel="DIGEST"))
                outcomes.append((str(patient.id), "HANDOVER_AUTOPUBLISHED"))
        reconcile_patient(db, patient.id, at)
    db.flush()
    return outcomes


def serialize_action(row: ActionItem, at=None):
    at = at or now()
    age = max(0, int((_aware(at) - _aware(row.first_seen_at)).total_seconds()))
    return {"id": str(row.id), "patient_id": str(row.patient_id), "dedupe_key": row.dedupe_key, "kind": row.kind, "source": row.source, "title": row.title, "reason": row.reason, "reasons": row.reasons or [], "severity": row.severity, "related_activity_ids": row.related_activity_ids or [], "related_incident_id": str(row.related_incident_id) if row.related_incident_id else None, "owner_user_id": str(row.owner_user_id) if row.owner_user_id else None, "assigned_to_user_id": str(row.assigned_to_user_id) if row.assigned_to_user_id else None, "due_at": _aware(row.due_at).isoformat() if row.due_at else None, "status": row.status, "snoozed_until": _aware(row.snoozed_until).isoformat() if row.snoozed_until else None, "age_seconds": age, "resolution_reason": row.resolution_reason, "resolution_note": row.resolution_note, "suggested_actions": row.suggested_actions or [], "reopened_count": row.reopened_count, "version": row.version}


def serialize_brief(row):
    if not row: return None
    return {"id": str(row.id), "patient_id": str(row.patient_id), "kind": row.kind, "for_date": row.for_date.date().isoformat(), "status": row.status, "generated_at": _aware(row.generated_at).isoformat(), "auto_generated": row.auto_generated, "content": row.content, "rendered_text": row.rendered_text, "rendered_html": row.rendered_html, "to_user_id": str(row.to_user_id) if row.to_user_id else None, "ai_enhanced": row.ai_enhanced, "version": row.version}
