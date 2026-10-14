"""Cover request lifecycle: detect declines and absences, rank replacements, offer, accept and measure.

A task counts as covered only when a replacement has accepted and a CONFIRMED primary assignment
exists for them. Detection is idempotent per trigger and runs inside the existing ``reassess`` hook
and the scheduler tick, so it shares the caller's transaction.
"""
from __future__ import annotations

import statistics
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.config import settings
from app.engine.availability import is_available_for
from app.engine.backup_matcher import check_candidate, rank_candidates
from app.engine.workload import buffered_window
from app.models import (ActivityHistory, AvailabilityOverride, CareActivity, CareAssignment, Caregiver, CareTeamMember, CaregiverWeeklySchedule,
                        CoverRequest, CoverRequestEvent, Notification, Patient, TeamRole)
from app.services.workload_balancer import ACTIVE, HANDOFF_STANDBY, _aware, build_snapshot, horizon

OPEN_STATUSES = ("OPEN", "OFFERED")
DETECTION_DAYS = 60
OFFER_TITLE = "Can you cover a care task?"
HISTORY_DAYS = 90


class CoverError(Exception):
    """A request cannot move to the asked-for state; the API maps this to 409."""


def _zone():
    return ZoneInfo(settings.app_timezone)


def _when(activity) -> str:
    return _aware(activity.scheduled_start).astimezone(_zone()).strftime("%a %d %b, %H:%M")


def _event(db, req, kind, *, caregiver_id=None, actor=None, note="", at=None):
    db.add(CoverRequestEvent(request_id=req.id, kind=kind, caregiver_id=caregiver_id, actor_user_id=actor.id if actor else None,
                             note=(note or "")[:300], at=at or now()))


def _history(db, req, actor, event, summary, payload=None):
    db.add(ActivityHistory(actor_user_id=actor.id if actor else None, patient_id=req.patient_id, event_type=event, entity_type="cover_request",
                           entity_id=str(req.id), summary=summary, payload=payload or {}, request_id=""))


def _coordinator_ids(db, patient_id):
    return list(db.scalars(select(CareTeamMember.user_id).where(CareTeamMember.patient_id == patient_id, CareTeamMember.team_role == TeamRole.COORDINATOR)))


def _notify(db, user_ids, patient_id, *, kind, title, body, severity="MEDIUM", requires_ack=False, skip=None):
    for user_id in dict.fromkeys(user_ids):
        if user_id and user_id != skip:
            db.add(Notification(user_id=user_id, patient_id=patient_id, kind=kind, severity=severity, title=title[:160], body=body[:500],
                                requires_ack=requires_ack, channel="INBOX"))


def _caregiver_availability(db, caregiver):
    schedule = [{"weekday": r.weekday, "start_min": r.start_min, "end_min": r.end_min}
                for r in db.scalars(select(CaregiverWeeklySchedule).where(CaregiverWeeklySchedule.caregiver_id == caregiver.id))]
    overrides = list(db.scalars(select(AvailabilityOverride).where(AvailabilityOverride.caregiver_id == caregiver.id, AvailabilityOverride.cancelled_at.is_(None)).order_by(AvailabilityOverride.start_at, AvailabilityOverride.id)))
    return {"schedule": schedule, "overrides": [{"id": o.id, "start_at": _aware(o.start_at), "end_at": _aware(o.end_at), "status": o.status, "reason": o.reason, "cancelled_at": None} for o in overrides]}


def _window(activity):
    return buffered_window({"scheduled_start": _aware(activity.scheduled_start), "scheduled_end": _aware(activity.scheduled_end),
                            "buffer_before_min": activity.buffer_before_min or 0, "buffer_after_min": activity.buffer_after_min or 0})


def snapshot_for(db: Session, activity, at: datetime | None = None) -> tuple[dict, datetime, datetime]:
    """Workload snapshot for the task's local day plus this patient's recent assignment history (continuity)."""
    at = at or now()
    start, end = horizon(_aware(activity.scheduled_start), 1)
    snap = build_snapshot(db, activity.patient_id, start, end)
    since = at - timedelta(days=HISTORY_DAYS)
    rows = db.execute(select(CareAssignment.caregiver_id, CareActivity.series_id, CareActivity.category, CareActivity.id)
                      .join(CareActivity, CareActivity.id == CareAssignment.activity_id)
                      .where(CareActivity.patient_id == activity.patient_id, CareAssignment.role == "PRIMARY",
                             CareAssignment.status.in_(("CONFIRMED", "SUPERSEDED")), CareAssignment.confirmed_at.is_not(None),
                             CareActivity.lifecycle_status != "CANCELLED", CareActivity.scheduled_start >= since,
                             CareActivity.scheduled_start < at, CareActivity.id != activity.id)).all()
    history: dict = {}
    for caregiver_id, series_id, category, _ in rows:
        item = history.setdefault(str(caregiver_id), {"patient_tasks": 0, "same_series": 0, "same_category": 0})
        item["patient_tasks"] += 1
        item["same_series"] += int(series_id is not None and series_id == activity.series_id)
        item["same_category"] += int(category == activity.category)
    snap["history"] = history
    return snap, start, end


def ranking(db: Session, req: CoverRequest, at: datetime | None = None) -> dict:
    activity = db.get(CareActivity, req.activity_id)
    at = at or now()
    snap, start, end = snapshot_for(db, activity, at)
    if not any(str(a["id"]) == str(activity.id) for a in snap["activities"]):
        return {"activity_id": str(activity.id), "eligible_count": 0, "summary": "This task is no longer open for cover.", "best": None, "candidates": []}
    return rank_candidates(snap, at, start, end, activity.id, replaced_caregiver_id=req.replaced_caregiver_id,
                           declined_caregiver_ids=req.declined_caregiver_ids or [], timezone=settings.app_timezone)


def _candidate(db, req, caregiver_id, at):
    activity = db.get(CareActivity, req.activity_id)
    snap, start, end = snapshot_for(db, activity, at)
    if not any(str(a["id"]) == str(activity.id) for a in snap["activities"]):
        raise CoverError("This task is no longer open for cover")
    return check_candidate(snap, at, start, end, activity.id, caregiver_id, replaced_caregiver_id=req.replaced_caregiver_id,
                           declined_caregiver_ids=req.declined_caregiver_ids or [], timezone=settings.app_timezone)


def _clear_prompt(db, req, caregiver_id, activity, at):
    """Acknowledge the "Can you cover…?" prompt a caregiver received for this task."""
    cg = db.get(Caregiver, caregiver_id) if caregiver_id else None
    if not cg or not cg.user_id: return None
    for row in db.scalars(select(Notification).where(Notification.user_id == cg.user_id, Notification.patient_id == req.patient_id,
                                                     Notification.kind == "DECISION", Notification.title == OFFER_TITLE,
                                                     Notification.acked_at.is_(None), Notification.body.startswith(activity.title))):
        row.acked_at = at; row.read_at = row.read_at or at
    return cg


def _withdraw_offer(db, req, activity, at, reason):
    """The request closed or went to someone else: tell the person still holding an offer, once."""
    cg = _clear_prompt(db, req, req.offered_caregiver_id, activity, at)
    if cg:
        _notify(db, [cg.user_id], req.patient_id, kind="STATUS", severity="LOW", title="Cover no longer needed",
                body=f"{activity.title} · {_when(activity)}: {reason}")


def open_request(db: Session, activity, reason: str, *, replaced_caregiver_id=None, note="", trigger_key=None, actor=None, at=None) -> CoverRequest:
    at = at or now()
    existing = db.scalar(select(CoverRequest).where(CoverRequest.activity_id == activity.id, CoverRequest.status.in_(OPEN_STATUSES)))
    if existing: return existing
    req = CoverRequest(id=uuid.uuid4(), patient_id=activity.patient_id, activity_id=activity.id, reason=reason, reason_note=(note or "")[:300],
                       trigger_key=trigger_key, replaced_caregiver_id=replaced_caregiver_id, status="OPEN", declined_caregiver_ids=[],
                       opened_at=at, opened_by=actor.id if actor else None)
    try:
        # A concurrent request (scheduler vs. a user action) may win the one-open-request index; reuse theirs.
        with db.begin_nested():
            db.add(req); db.flush()
    except IntegrityError:
        existing = db.scalar(select(CoverRequest).where(CoverRequest.activity_id == activity.id, CoverRequest.status.in_(OPEN_STATUSES)))
        if existing: return existing
        raise
    _event(db, req, "OPENED", caregiver_id=replaced_caregiver_id, actor=actor, note=note, at=at)
    ranked = ranking(db, req, at)
    if not ranked["eligible_count"]: _event(db, req, "NO_CANDIDATES", note=ranked["summary"], at=at)
    best = ranked["best"]["name"] if ranked["best"] else None
    body = f"{activity.title} · {_when(activity)}. {ranked['summary']}" + (f" Best match: {best}." if best else "")
    _notify(db, _coordinator_ids(db, activity.patient_id), activity.patient_id, kind="DECISION", title="Cover needed", body=body,
            severity="HIGH" if activity.importance in ("HIGH", "CRITICAL") else "MEDIUM", requires_ack=True, skip=actor.id if actor else None)
    _history(db, req, actor, "cover.opened", f"Cover needed for {activity.title}", {"reason": reason, "eligible": ranked["eligible_count"]})
    return req


def offer(db: Session, req: CoverRequest, caregiver_id, *, actor=None, auto_advance=True, at=None, automatic=False) -> dict:
    at = at or now()
    if req.status not in OPEN_STATUSES: raise CoverError("This cover request is closed")
    candidate = _candidate(db, req, caregiver_id, at)
    if not candidate: raise CoverError("This caregiver is not linked to the patient")
    if not candidate["eligible"]: raise CoverError(candidate["headline"])
    caregiver = db.get(Caregiver, uuid.UUID(str(caregiver_id)))
    activity = db.get(CareActivity, req.activity_id)
    req.status, req.offered_caregiver_id, req.offered_at, req.auto_advance = "OFFERED", caregiver.id, at, auto_advance
    req.version += 1
    _event(db, req, "AUTO_ADVANCED" if automatic else "OFFERED", caregiver_id=caregiver.id, actor=actor, note=candidate["headline"], at=at)
    if caregiver.user_id:
        _notify(db, [caregiver.user_id], req.patient_id, kind="DECISION", title=OFFER_TITLE,
                body=f"{activity.title} · {_when(activity)}. Accept or decline in Cover Requests.", requires_ack=True)
    elif automatic:
        # Nobody would see an in-app offer: ask the primary contacts to call, rather than letting it sit unanswered.
        _notify(db, _coordinator_ids(db, req.patient_id), req.patient_id, kind="DECISION", title=f"Please call {caregiver.name}"[:160],
                body=f"{caregiver.name} is the next best match for {activity.title} · {_when(activity)} but does not use the app. Record their answer in Cover Requests.",
                requires_ack=True)
    _history(db, req, actor, "cover.offered", f"Cover offered to {caregiver.name}", {"caregiver_id": str(caregiver.id), "automatic": automatic})
    return candidate


def accept(db: Session, req: CoverRequest, caregiver_id, *, actor, via: str, at=None) -> CareAssignment:
    """Make the replacement the confirmed primary. Only now does the task count as covered."""
    at = at or now()
    if req.status not in OPEN_STATUSES: raise CoverError("This cover request is closed")
    activity = db.get(CareActivity, req.activity_id)
    if _aware(activity.scheduled_start) <= at: raise CoverError("This task has already started")
    candidate = _candidate(db, req, caregiver_id, at)
    if not candidate or not candidate["eligible"]:
        raise CoverError(candidate["headline"] if candidate else "This caregiver is not linked to the patient")
    caregiver = db.get(Caregiver, uuid.UUID(str(caregiver_id)))
    if req.offered_caregiver_id and req.offered_caregiver_id != caregiver.id:
        _withdraw_offer(db, req, activity, at, f"{caregiver.name} is covering it.")
    else:
        _clear_prompt(db, req, caregiver.id, activity, at)
    try:
        with db.begin_nested():
            for row in db.scalars(select(CareAssignment).where(CareAssignment.activity_id == activity.id, CareAssignment.status.in_(ACTIVE)).with_for_update()):
                # Replace the primary, promote the person's own backup slot, and release any Workload Balancer standby.
                if row.role == "PRIMARY" or row.caregiver_id == caregiver.id or (row.role == "BACKUP" and row.confirmed_via == HANDOFF_STANDBY):
                    row.status = "SUPERSEDED"; row.updated_at = at
            db.flush()
            created = CareAssignment(activity_id=activity.id, caregiver_id=caregiver.id, role="PRIMARY", status="CONFIRMED", assigned_by=actor.id,
                                     assigned_at=at, confirmed_at=at, confirmed_by=actor.id, confirmed_via=via)
            db.add(created); db.flush()
    except IntegrityError:
        raise CoverError("Someone else changed this task's assignment just now; refresh and try again") from None
    req.status, req.resolution, req.covered_by_caregiver_id, req.covered_assignment_id, req.closed_at = "COVERED", "MATCHER", caregiver.id, created.id, at
    req.offered_caregiver_id = caregiver.id
    req.version += 1
    _event(db, req, "ACCEPTED", caregiver_id=caregiver.id, actor=actor, at=at)
    _event(db, req, "COVERED", caregiver_id=caregiver.id, actor=actor, note=f"Confirmed via {via.lower()}", at=at)
    body = f"{caregiver.name} will cover {activity.title} · {_when(activity)}."
    _notify(db, _coordinator_ids(db, req.patient_id), req.patient_id, kind="STATUS", severity="LOW", title="Cover confirmed", body=body, skip=actor.id)
    replaced = db.get(Caregiver, req.replaced_caregiver_id) if req.replaced_caregiver_id else None
    if replaced and replaced.user_id:
        _notify(db, [replaced.user_id], req.patient_id, kind="STATUS", severity="LOW", title="Your task is covered", body=body, skip=actor.id)
    _history(db, req, actor, "cover.covered", f"{caregiver.name} confirmed as cover for {activity.title}",
             {"caregiver_id": str(caregiver.id), "via": via, "minutes_to_cover": minutes_between(req.opened_at, at)})
    return created


def decline(db: Session, req: CoverRequest, *, actor, note="", at=None) -> dict | None:
    """The offered person said no (or did not answer in time). Exclude them; optionally offer the next best match."""
    at = at or now()
    if req.status != "OFFERED" or not req.offered_caregiver_id: raise CoverError("No offer is waiting for a response")
    declined_id = req.offered_caregiver_id
    activity = db.get(CareActivity, req.activity_id)
    _clear_prompt(db, req, declined_id, activity, at)
    caregiver = db.get(Caregiver, declined_id)
    req.declined_caregiver_ids = [*(req.declined_caregiver_ids or []), str(declined_id)]
    req.status, req.offered_caregiver_id, req.offered_at = "OPEN", None, None
    req.version += 1
    _event(db, req, "OFFER_DECLINED", caregiver_id=declined_id, actor=actor, note=note, at=at)
    _history(db, req, actor, "cover.offer_declined", f"{caregiver.name if caregiver else 'Caregiver'} cannot cover this task" + (f" ({note})" if note else ""))
    ranked = ranking(db, req, at)
    if req.auto_advance and ranked["best"]:
        return offer(db, req, ranked["best"]["caregiver_id"], actor=None, auto_advance=True, at=at, automatic=True)
    if not ranked["best"]: _event(db, req, "NO_CANDIDATES", note=ranked["summary"], at=at)
    body = f"{caregiver.name if caregiver else 'The caregiver'} cannot cover {activity.title} · {_when(activity)}. {ranked['summary']}"
    _notify(db, _coordinator_ids(db, req.patient_id), req.patient_id, kind="DECISION", title="Cover still needed", body=body, requires_ack=True,
            skip=actor.id if actor else None)
    return None


def close(db: Session, req: CoverRequest, status: str, *, actor=None, note="", resolution=None, at=None):
    at = at or now()
    if req.offered_caregiver_id and status != "COVERED":
        _withdraw_offer(db, req, db.get(CareActivity, req.activity_id), at, note or "the request was closed.")
    req.status, req.closed_at, req.resolution = status, at, resolution
    req.version += 1
    _event(db, req, status if status in ("CANCELLED", "EXPIRED") else "COVERED", actor=actor, note=note, at=at)
    _history(db, req, actor, f"cover.{status.lower()}", f"Cover request {status.lower()}: {note}" if note else f"Cover request {status.lower()}")


def minutes_between(start, end) -> float:
    return round((_aware(end) - _aware(start)).total_seconds() / 60, 1)


def offer_timeout(activity, offered_at) -> timedelta:
    """Unanswered offers time out after min(2 h, half the remaining lead time), but never under 15 minutes."""
    lead = _aware(activity.scheduled_start) - _aware(offered_at)
    return max(timedelta(minutes=15), min(timedelta(hours=2), lead / 2))


def need_for(db: Session, activity):
    """The decline or absence that leaves this task without dependable cover, if any.

    Returns (need, active_primary) where need is (reason, replaced_caregiver_id, trigger_key, note) or None.
    """
    rows = db.scalars(select(CareAssignment).where(CareAssignment.activity_id == activity.id, CareAssignment.role == "PRIMARY")
                      .order_by(CareAssignment.updated_at.desc(), CareAssignment.assigned_at.desc())).all()
    active = next((r for r in rows if r.status in ACTIVE), None)
    if active is None and rows and rows[0].status == "DECLINED":
        decliner = db.get(Caregiver, rows[0].caregiver_id)
        return ("DECLINED", rows[0].caregiver_id, f"decline:{rows[0].id}", f"{decliner.name if decliner else 'Caregiver'} declined: {rows[0].decline_reason or 'no reason given'}"), active
    if active is not None and active.status == "CONFIRMED":
        holder = db.get(Caregiver, active.caregiver_id)
        if holder:
            result = is_available_for(_caregiver_availability(db, holder), _window(activity), settings.app_timezone)
            if not result.available and result.blocking_overrides:
                override = result.blocking_overrides[0]  # overrides are loaded in (start_at, id) order, so this key is stable
                return ("ABSENCE", holder.id, f"absence:{override['id']}:{active.id}", f"{holder.name} reported an absence ({override['reason'].lower()})"), active
    return None, active


def _holder_available(db, active, activity) -> bool:
    holder = db.get(Caregiver, active.caregiver_id) if active else None
    return bool(holder) and is_available_for(_caregiver_availability(db, holder), _window(activity), settings.app_timezone).available


def sync_patient(db: Session, patient_id, at: datetime | None = None) -> int:
    """Open requests for new declines/absences, time out unanswered offers, and close requests whose condition resolved. Idempotent."""
    at = at or now()
    changed = 0
    open_reqs = {r.activity_id: r for r in db.scalars(select(CoverRequest).where(CoverRequest.patient_id == patient_id, CoverRequest.status.in_(OPEN_STATUSES)))}
    upcoming = db.scalars(select(CareActivity).where(CareActivity.patient_id == patient_id, CareActivity.requires_caregiver.is_(True),
                                                     CareActivity.lifecycle_status == "SCHEDULED", CareActivity.scheduled_start > at,
                                                     CareActivity.scheduled_start < at + timedelta(days=DETECTION_DAYS))).all()
    activities = {a.id: a for a in upcoming}
    for activity_id in open_reqs:
        if activity_id not in activities: activities[activity_id] = db.get(CareActivity, activity_id)
    for activity in activities.values():
        if activity is None: continue
        req = open_reqs.get(activity.id)
        if req and activity.lifecycle_status != "SCHEDULED":
            close(db, req, "CANCELLED", note=f"Task {activity.lifecycle_status.lower()}", at=at); changed += 1; continue
        if req and _aware(activity.scheduled_start) <= at:
            close(db, req, "EXPIRED", note="Task started before cover was confirmed", at=at); changed += 1; continue
        need, active = need_for(db, activity)
        if req:
            confirmed_ok = active is not None and active.status == "CONFIRMED" and _holder_available(db, active, activity)
            if confirmed_ok and active.caregiver_id != req.replaced_caregiver_id:
                holder = db.get(Caregiver, active.caregiver_id)
                req.covered_by_caregiver_id, req.covered_assignment_id = holder.id, active.id
                close(db, req, "COVERED", note=f"Covered outside the matcher by {holder.name}", resolution="MANUAL", at=at); changed += 1
            elif confirmed_ok and active.confirmed_at and _aware(active.confirmed_at) > _aware(req.opened_at):
                close(db, req, "CANCELLED", note="The original caregiver confirmed the task", at=at); changed += 1
            elif confirmed_ok and req.reason == "ABSENCE" and need is None:
                close(db, req, "CANCELLED", note="The caregiver is available again", at=at); changed += 1
            elif req.status == "OFFERED" and req.offered_at and at - _aware(req.offered_at) >= offer_timeout(activity, req.offered_at):
                decline(db, req, actor=None, note="No answer in time", at=at); changed += 1
            continue
        if need and not db.scalar(select(CoverRequest.id).where(CoverRequest.trigger_key == need[2])):
            open_request(db, activity, need[0], replaced_caregiver_id=need[1], trigger_key=need[2], note=need[3], at=at); changed += 1
    return changed


def run_cover_tick(db: Session, at: datetime | None = None) -> int:
    at = at or now()
    patient_ids = set(db.scalars(select(Patient.id)))
    return sum(sync_patient(db, pid, at) for pid in patient_ids)


def metrics(db: Session, patient_id, days: int, at: datetime | None = None) -> dict:
    at = at or now()
    rows = db.scalars(select(CoverRequest).where(CoverRequest.patient_id == patient_id, CoverRequest.opened_at >= at - timedelta(days=days))).all()
    covered = [r for r in rows if r.status == "COVERED"]
    via_matcher = [r for r in covered if r.resolution == "MATCHER"]
    minutes = sorted(minutes_between(r.opened_at, r.closed_at) for r in covered if r.closed_at)
    resolved = len(covered) + sum(r.status == "EXPIRED" for r in rows)
    open_now = db.scalar(select(func.count(CoverRequest.id)).where(CoverRequest.patient_id == patient_id, CoverRequest.status.in_(OPEN_STATUSES))) or 0
    return {"days": days, "opened": len(rows), "open": open_now, "covered": len(covered),
            "covered_via_matcher": len(via_matcher), "covered_manually": len(covered) - len(via_matcher),
            "expired": sum(r.status == "EXPIRED" for r in rows), "cancelled": sum(r.status == "CANCELLED" for r in rows),
            "median_minutes_to_cover": statistics.median(minutes) if minutes else None,
            "average_minutes_to_cover": round(sum(minutes) / len(minutes), 1) if minutes else None,
            "resolved_without_manual_search_pct": round(100 * len(via_matcher) / resolved, 1) if resolved else None,
            "definition": "Time to secure = cover request opened (when the decline or absence is detected) to replacement confirmed. Resolved without manual searching = covered through a matcher offer, as a share of requests that ended covered or expired."}
