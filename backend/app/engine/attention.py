"""Deterministic, explainable operational attention for caregiver coordination."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class AttentionItem:
    dedupe_key: str
    kind: str
    severity: str
    bucket: str
    title: str
    reason: str
    reasons: tuple[str, ...]
    activity_ids: tuple[str, ...] = ()
    incident_id: str | None = None
    due_at: datetime | None = None
    suggested_actions: tuple[dict, ...] = ()


def _get(row, key, default=None):
    return row.get(key, default) if isinstance(row, dict) else getattr(row, key, default)


def _iso_id(value):
    return str(value) if value is not None else ""


def _severity(importance: str) -> str:
    return {"CRITICAL": "CRITICAL", "HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW"}.get(importance, "MEDIUM")


def _bucket(severity: str, start: datetime | None, deadline: datetime | None, now: datetime, incident: bool = False) -> str:
    if incident or severity in {"HIGH", "CRITICAL"}:
        return "NEEDS_NOW"
    if any(value is not None and value <= now + timedelta(hours=4) for value in (start, deadline)):
        return "NEEDS_NOW"
    return "AT_RISK"


def evaluate_attention(snapshot: dict, now: datetime, settings: dict | None = None) -> list[AttentionItem]:
    """Evaluate a JSON-like snapshot. Thresholds are deliberately explicit and frozen-clock friendly."""
    settings = settings or {}
    # Reason text is read by people in the app timezone; stored datetimes are UTC.
    zone = ZoneInfo(settings.get("timezone") or "Asia/Kolkata")
    activities = snapshot.get("activities", ())
    assignments = snapshot.get("assignments", ())
    by_activity: dict[str, list] = {}
    for assignment in assignments:
        by_activity.setdefault(_iso_id(_get(assignment, "activity_id")), []).append(assignment)
    items: dict[str, AttentionItem] = {}

    def add(kind, activity, reason, severity=None, *, due_at=None, dedupe_key=None, title=None, suggested=()):
        aid = _iso_id(_get(activity, "id")) if activity is not None else ""
        key = dedupe_key or f"{kind}:{aid}"
        sev = severity or _severity(_get(activity, "importance", "MEDIUM"))
        start = _get(activity, "scheduled_start") if activity is not None else None
        bucket = _bucket(sev, start, due_at or _get(activity, "deadline"), now, kind.startswith("INCIDENT"))
        existing = items.get(key)
        if existing:
            ids = tuple(sorted(set(existing.activity_ids + ((aid,) if aid else ()))))
            reasons = tuple(sorted(set(existing.reasons + (reason,))))
            items[key] = AttentionItem(key, kind, max((existing.severity, sev), key=("LOW", "MEDIUM", "HIGH", "CRITICAL").index), bucket, existing.title, "; ".join(reasons), reasons, ids, existing.incident_id, due_at or existing.due_at, existing.suggested_actions or tuple(suggested))
        else:
            items[key] = AttentionItem(key, kind, sev, bucket, title or (_get(activity, "title", kind.replace("_", " ").title()) if activity else kind.replace("_", " ").title()), reason, (reason,), (aid,) if aid else (), due_at=due_at, suggested_actions=tuple(suggested))

    for activity in activities:
        if _get(activity, "lifecycle_status", "SCHEDULED") in {"COMPLETED", "CANCELLED"}:
            continue
        if _get(activity, "lifecycle_status") == "MISSED":
            missed_at = _get(activity, "missed_at") or _get(activity, "scheduled_start")
            if missed_at and now - missed_at < timedelta(hours=24):
                add("TASK_MISSED", activity, f"{_get(activity, 'title', 'A care activity')} was missed and has not been recorded as done.", severity="HIGH",
                    due_at=_get(activity, "scheduled_start"), suggested=({"option": "MARK_COMPLETE", "activity_id": _iso_id(_get(activity, "id"))},))
            continue
        aid = _iso_id(_get(activity, "id"))
        rows = by_activity.get(aid, [])
        active = [x for x in rows if _get(x, "status") in {"PROPOSED", "AWAITING_CONFIRMATION", "CONFIRMED"} and _get(x, "role", "PRIMARY") == "PRIMARY"]
        confirmed = next((x for x in active if _get(x, "status") == "CONFIRMED"), None)
        start = _get(activity, "scheduled_start")
        deadline = _get(activity, "deadline")
        name = _get(activity, "title", "Scheduled task")
        if _get(activity, "requires_caregiver", True) and not active:
            add("UNASSIGNED_REQUIRED", activity, f"{name} has no active primary caregiver.", dedupe_key=f"UNASSIGNED_REQUIRED:{aid}", suggested=({"option": "ASSIGN_CAREGIVER"},))
        if any(_get(x, "status") == "DECLINED" for x in rows) and not confirmed:
            add("ASSIGNMENT_DECLINED", activity, f"A caregiver declined {name}; no confirmed primary is in place.", dedupe_key=f"ASSIGNMENT_DECLINED:{aid}")
        for assignment in active:
            assigned = _get(assignment, "assigned_at")
            pending_old = assigned is not None and now > assigned + timedelta(hours=4)
            starts_soon = start is not None and now <= start < now + timedelta(hours=12)
            if _get(assignment, "status") in {"PROPOSED", "AWAITING_CONFIRMATION"} and (pending_old or starts_soon):
                add("ASSIGNMENT_UNCONFIRMED", activity, f"{name} is awaiting confirmation" + (" for over 4 hours." if pending_old else " and starts within 12 hours."), dedupe_key=f"ASSIGNMENT_UNCONFIRMED:{aid}", suggested=({"option": "REQUEST_CONFIRMATION", "assignment_id": _iso_id(_get(assignment, "id"))},))
        if confirmed and _get(confirmed, "caregiver_available") is False:
            add("CAREGIVER_UNAVAILABLE", activity, f"The confirmed primary is unavailable during {name}.", dedupe_key=f"CAREGIVER_UNAVAILABLE:{_get(confirmed, 'caregiver_id')}", suggested=({"option": "PICK_BACKUP", "activity_id": aid},))
        if _get(activity, "capability_match") is False and confirmed:
            add("CAPABILITY_MISMATCH", activity, f"The confirmed primary lacks a required capability for {name}.")
        if _get(activity, "overlap_conflict") is True and confirmed:
            add("OVERLAP_CONFLICT", activity, f"The confirmed primary has an overlapping commitment for {name}.")
        if _get(activity, "over_limit") is True and confirmed:
            add("OVER_LIMIT", activity, f"The confirmed primary exceeds a configured workload limit.")
        feed = _get(activity, "source") in {"PRESCRIPTION", "APPOINTMENT"}
        # Management by exception: a task with a confirmed caretaker is on track until it is actually late or missed.
        if deadline and now < deadline < now + timedelta(hours=24) and not confirmed:
            add("DEADLINE_APPROACHING", activity, f"{name} has an unresolved deadline at {deadline.astimezone(zone):%H:%M}.", due_at=deadline)
        if start and start < now and _get(activity, "lifecycle_status", "SCHEDULED") == "SCHEDULED" and not (deadline and now < deadline):
            add("TASK_OVERDUE", activity, f"{name} is past its scheduled start and is not marked complete.", severity="HIGH", due_at=start)
        if confirmed and not feed and start and now <= start < now + timedelta(minutes=30) and not _get(activity, "acknowledged_at"):
            add("TASK_UNACKNOWLEDGED", activity, f"{name} starts within 30 minutes and has no acknowledgement.", due_at=start)

    for incident in snapshot.get("incidents", ()):
        if _get(incident, "status") not in {"OPEN", "ACKNOWLEDGED"}:
            continue
        level = int(_get(incident, "current_level", 1))
        sev = "CRITICAL" if level == 5 and not _get(incident, "acknowledged_at") else "HIGH" if level >= 4 else "MEDIUM" if level >= 2 else "LOW"
        incident_id = _iso_id(_get(incident, "id"))
        kind = "INCIDENT_UNACKED_EMERGENCY" if level == 5 and not _get(incident, "acknowledged_at") else "INCIDENT_OPEN"
        reason = _get(incident, "safe_summary") or _get(incident, "title") or "An operational incident remains open."
        item = AttentionItem(f"{kind}:{incident_id}", kind, sev, "NEEDS_NOW", _get(incident, "title", "Open incident"), reason, (reason,), (_iso_id(_get(incident, "related_activity_id")),) if _get(incident, "related_activity_id") else (), incident_id, _get(incident, "current_deadline_at"), ({"option": "ACKNOWLEDGE_INCIDENT", "incident_id": incident_id},))
        items[item.dedupe_key] = item

    rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    return sorted(items.values(), key=lambda x: (-rank[x.severity], x.due_at or datetime.max.replace(tzinfo=now.tzinfo), x.dedupe_key))
