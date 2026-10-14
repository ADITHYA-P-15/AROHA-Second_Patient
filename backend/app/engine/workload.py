from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from app.engine.availability import Window


def buffered_window(activity) -> Window:
    start = _aware(_get(activity, "scheduled_start"))
    end = _aware(_get(activity, "scheduled_end"))
    before = int(_get(activity, "buffer_before_min", 0))
    after = int(_get(activity, "buffer_after_min", 0))
    from datetime import timedelta
    return Window(start - timedelta(minutes=before), end + timedelta(minutes=after))


def overlap(left: Window, right: Window) -> bool:
    return left.start < right.end and right.start < left.end


def workload(assignments, caregiver_id, timezone="Asia/Kolkata"):
    """Summarize committed and pending primary work; backups stay on standby."""
    from zoneinfo import ZoneInfo
    zone = ZoneInfo(timezone)
    by_day = defaultdict(lambda: {"confirmed": 0, "pending": 0, "hours_confirmed": 0.0, "hours_pending": 0.0})
    by_week = defaultdict(lambda: {"confirmed_hours": 0.0, "pending_hours": 0.0})
    for assignment, activity in assignments:
        if str(_get(assignment, "caregiver_id")) != str(caregiver_id) or _get(assignment, "role") != "PRIMARY":
            continue
        status = _get(assignment, "status")
        if status not in {"CONFIRMED", "AWAITING_CONFIRMATION", "PROPOSED"}:
            continue
        window = buffered_window(activity)
        local = _get(activity, "scheduled_start").astimezone(zone)
        hours = (window.end - window.start).total_seconds() / 3600
        day = local.date().isoformat()
        week = f"{local.isocalendar().year}-W{local.isocalendar().week:02d}"
        is_confirmed = status == "CONFIRMED"
        if _get(activity, "source", "MANUAL") != "PRESCRIPTION":  # routine doses use time, not a daily task slot
            by_day[day]["confirmed" if is_confirmed else "pending"] += 1
        by_day[day]["hours_confirmed" if is_confirmed else "hours_pending"] += hours
        by_week[week]["confirmed_hours" if is_confirmed else "pending_hours"] += hours
    return {"by_day": dict(by_day), "by_week": dict(by_week)}


def overlaps_for(activity, other_activities):
    target = buffered_window(activity)
    return [other for other in other_activities if str(_get(other, "id")) != str(_get(activity, "id")) and _get(other, "lifecycle_status") == "SCHEDULED" and overlap(target, buffered_window(other))]


def _get(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def _aware(value):
    from datetime import UTC
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value
