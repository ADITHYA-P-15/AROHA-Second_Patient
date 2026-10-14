"""Snapshot, findings log and measures for the Predictive Coverage Planner."""
from __future__ import annotations

import logging
import statistics
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.config import settings
from app.engine.coverage_planner import forecast
from app.engine.workload_balancer import evaluate_workload
from app.models import CareActivity, CareAssignment, CoverageFinding, Patient
from app.services.workload_balancer import _aware, build_snapshot, horizon

GAP_KINDS = ("GAP", "UNCONFIRMED")
log = logging.getLogger("second_patient")


def plan(db: Session, patient_id, at: datetime | None = None) -> dict:
    at = at or now()
    day_start, _ = horizon(at, 1)
    day_end = day_start + timedelta(days=9)  # local days touched by the next 7 x 24 hours, plus the week bounds
    snap = build_snapshot(db, patient_id, day_start, day_end)
    demand = evaluate_workload(snap, at, day_start, day_start + timedelta(days=8), settings.app_timezone)["demand"]
    return forecast(snap, at, day_start, day_end, demand=demand, timezone=settings.app_timezone)


WORST = {"GAP": 0, "UNCONFIRMED": 1, "SINGLE_POINT": 2}


def record(db: Session, patient_id, result: dict, at: datetime | None = None) -> int:
    """Keep one open log row per task while it has any finding; close it with an outcome when the risk ends.

    Outcomes are judged per task, not per kind: a gap that becomes "not confirmed" is still the same open risk.
    """
    at = at or now()
    changed = 0
    current = {f["activity"]["id"]: f for f in result["findings"]}
    open_rows = {str(r.activity_id): r for r in db.scalars(select(CoverageFinding).where(
        CoverageFinding.patient_id == patient_id, CoverageFinding.status == "OPEN"))}
    for aid, finding in current.items():
        row = open_rows.get(aid)
        if row:
            row.kind, row.last_seen_at, row.headline = finding["kind"], at, finding["headline"][:500]
            row.secure_by, row.activity_start = finding["secure_by"], finding["activity"]["scheduled_start"]
            if WORST[finding["kind"]] < WORST[row.worst_kind]: row.worst_kind = finding["kind"]
            continue
        row = CoverageFinding(id=uuid.uuid4(), patient_id=patient_id, activity_id=uuid.UUID(aid), kind=finding["kind"], worst_kind=finding["kind"],
                              status="OPEN", headline=finding["headline"][:500], activity_start=finding["activity"]["scheduled_start"],
                              secure_by=finding["secure_by"], first_secure_by=finding["secure_by"], first_detected_at=at, last_seen_at=at)
        try:
            with db.begin_nested():
                db.add(row); db.flush()
            changed += 1
        except IntegrityError:
            pass  # a concurrent tick logged it first
    for aid, row in open_rows.items():
        if aid in current: continue
        _close(db, row, at)
        changed += 1
    return changed


def _close(db: Session, row: CoverageFinding, at: datetime) -> None:
    activity = db.get(CareActivity, row.activity_id)
    start = _aware(activity.scheduled_start) if activity else _aware(row.activity_start)
    row.activity_start, row.resolved_at = start, at
    if activity is None or activity.lifecycle_status == "CANCELLED":
        row.status, row.outcome = "CLOSED", "TASK_CLOSED"
    elif start <= at:
        # The task started. Was it still uncovered the last time the planner looked?
        if row.kind in GAP_KINDS:
            fixed_late = db.scalar(select(CareAssignment.id).where(CareAssignment.activity_id == activity.id, CareAssignment.role == "PRIMARY",
                                                                   CareAssignment.status == "CONFIRMED", CareAssignment.confirmed_at > row.last_seen_at))
            row.status, row.outcome = ("RESOLVED", "AFTER_DEADLINE") if fixed_late else ("MISSED", "STARTED_UNCOVERED")
        else:
            row.status, row.outcome = "CLOSED", "NO_BACKUP_SECURED"
    elif activity.lifecycle_status != "SCHEDULED":
        row.status, row.outcome = "CLOSED", "TASK_CLOSED"
    elif not activity.requires_caregiver or start > at + timedelta(days=7):
        # Moved out of the 7-day window or no longer needs a caregiver: not a prevented gap.
        row.status, row.outcome = "CLOSED", "OUT_OF_SCOPE"
    else:
        row.status = "RESOLVED"
        row.outcome = "BEFORE_DEADLINE" if at <= _aware(row.secure_by) else "AFTER_DEADLINE"


def run_planner_tick(db: Session, at: datetime | None = None) -> int:
    """Log findings for every patient. Each patient is isolated so one failure never undoes the others."""
    at = at or now()
    changed = 0
    for pid in db.scalars(select(Patient.id)).all():
        try:
            with db.begin_nested():
                changed += record(db, pid, plan(db, pid, at), at)
        except Exception:
            log.exception("coverage planner failed for patient %s", pid)
    return changed


def metrics(db: Session, patient_id, days: int, at: datetime | None = None) -> dict:
    at = at or now()
    rows = db.scalars(select(CoverageFinding).where(CoverageFinding.patient_id == patient_id,
                                                    CoverageFinding.first_detected_at >= at - timedelta(days=days))).all()
    # Count tasks, not log rows: keep each task's earliest row.
    first: dict = {}
    for row in sorted(rows, key=lambda r: _aware(r.first_detected_at)):
        first.setdefault(row.activity_id, row)
    tasks = list(first.values())
    early = [r for r in tasks if _aware(r.first_detected_at) <= _aware(r.first_secure_by)]
    leads = sorted(round((_aware(r.activity_start) - _aware(r.first_detected_at)).total_seconds() / 3600, 1) for r in tasks)
    gap_rows = [r for r in rows if r.worst_kind in GAP_KINDS]
    fixed = {r.activity_id for r in gap_rows if r.status == "RESOLVED"}
    missed = {r.activity_id for r in gap_rows if r.status == "MISSED"}
    preventable = {r.activity_id for r in gap_rows if r.status == "MISSED" and _aware(r.first_detected_at) <= _aware(r.first_secure_by)}
    return {"days": days, "identified": len(tasks), "open": sum(r.status == "OPEN" for r in rows),
            "identified_before_deadline": len(early),
            "identified_before_deadline_pct": round(100 * len(early) / len(tasks), 1) if tasks else None,
            "median_lead_hours": statistics.median(leads) if leads else None,
            "resolved_before_deadline": len({r.activity_id for r in rows if r.outcome == "BEFORE_DEADLINE"}),
            "resolved_after_deadline": len({r.activity_id for r in rows if r.outcome == "AFTER_DEADLINE"}),
            "gaps_closed_before_start": len(fixed), "started_uncovered": len(missed), "preventable_uncovered": len(preventable),
            "gaps_prevented_pct": round(100 * len(fixed) / (len(fixed) + len(missed)), 1) if fixed or missed else None,
            "backups_never_secured": len({r.activity_id for r in rows if r.outcome == "NO_BACKUP_SECURED"}),
            "out_of_scope": len({r.activity_id for r in rows if r.outcome == "OUT_OF_SCOPE"}),
            "by_kind": {k: len({r.activity_id for r in rows if r.worst_kind == k}) for k in ("GAP", "UNCONFIRMED", "SINGLE_POINT")},
            "definition": ("Counts tasks. Identified before deadline = first flagged before its secure-by time (as set when first flagged). "
                           "Preventable uncovered = flagged before its deadline but still without a confirmed caregiver when it started. "
                           "Gaps prevented = gap or unconfirmed tasks fixed before start, as a share of those that reached an outcome; "
                           "tasks rescheduled beyond 7 days are excluded.")}
