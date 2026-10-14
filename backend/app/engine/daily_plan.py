"""Pure grouping and workload view rules for one caregiver's daily plan."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ROUTINE_CATEGORIES = {"DAILY_ROUTINE", "MEDICATION", "MOBILITY"}
ERRAND_CATEGORIES = {"PRESCRIPTION", "SUPPLIES", "LAB"}


def _get(row, key, default=None):
    return row.get(key, default) if isinstance(row, dict) else getattr(row, key, default)


def _minute(value: str, fallback: str) -> int:
    parsed = time.fromisoformat(value or fallback)
    return parsed.hour * 60 + parsed.minute


def daypart(value: datetime, timezone_name: str = "UTC", boundaries=None) -> str:
    local = value.astimezone(ZoneInfo(timezone_name)) if value.tzinfo else value
    minute = local.hour * 60 + local.minute
    boundaries = boundaries or {}
    early = _minute(boundaries.get("early", "06:00"), "06:00")
    morning = _minute(boundaries.get("morning", "08:00"), "08:00")
    afternoon = _minute(boundaries.get("afternoon", "12:00"), "12:00")
    evening = _minute(boundaries.get("evening", "17:00"), "17:00")
    night = _minute(boundaries.get("night", "21:00"), "21:00")
    if minute < early or minute >= night: return "Night"
    if minute < morning: return "Early"
    if minute < afternoon: return "Morning"
    if minute < evening: return "Afternoon"
    return "Evening"


def _confirmed_primary(activity, assignments):
    return next((x for x in assignments if _get(x, "activity_id") == _get(activity, "id") and _get(x, "role", "PRIMARY") == "PRIMARY" and _get(x, "status") == "CONFIRMED"), None)


def is_routine(activity, assignments, attention_activity_ids=(), now=None, routine_rules=None):
    start = _get(activity, "scheduled_start")
    rules = routine_rules or {}
    maximum = rules.get("max_importance", "MEDIUM")
    rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    return (
        (_get(activity, "series_id") is not None or _get(activity, "category") in set(rules.get("categories", ROUTINE_CATEGORIES)))
        and rank.get(_get(activity, "importance", "MEDIUM"), 1) <= rank.get(maximum, 1)
        and _confirmed_primary(activity, assignments) is not None
        and str(_get(activity, "id")) not in {str(x) for x in attention_activity_ids}
        and not (_get(activity, "lifecycle_status") == "SCHEDULED" and start and now and start < now)
    )


def build_daily_plan(activities, assignments, attention=(), *, now: datetime, day: date | None = None, available_windows=None, timezone_name: str = "UTC", settings=None):
    day = day or (now.astimezone(ZoneInfo(timezone_name)).date() if now.tzinfo else now.date())
    settings = settings or {}
    rules = settings.get("routine_rules", {})
    boundaries = settings.get("daypart_boundaries", {})
    merge_gap = int(rules.get("merge_gap_minutes", 30))
    attention_ids = {str(aid) for item in attention for aid in getattr(item, "activity_ids", ())}
    attention_by_id = {}
    for item in attention:
        for aid in getattr(item, "activity_ids", ()):
            attention_by_id[str(aid)] = item
    rows = []
    handled = []
    for activity in activities:
        start = _get(activity, "scheduled_start")
        local_start = start.astimezone(ZoneInfo(timezone_name)) if start is not None and start.tzinfo else start
        if start is None or local_start.date() != day:
            continue
        status = _get(activity, "lifecycle_status", "SCHEDULED")
        item = {"activity_id": str(_get(activity, "id")), "title": _get(activity, "title", "Task"), "category": _get(activity, "category", "OTHER"), "start": start, "end": _get(activity, "scheduled_end"), "status": status, "importance": _get(activity, "importance", "MEDIUM"), "series_id": str(_get(activity, "series_id")) if _get(activity, "series_id") else None}
        assignment = _confirmed_primary(activity, assignments)
        item["assignee_id"] = str(_get(assignment, "caregiver_id")) if assignment else None
        item["assignee_name"] = _get(assignment, "caregiver_name") if assignment else None
        if status == "COMPLETED":
            handled.append(item)
        elif is_routine(activity, assignments, attention_ids, now, rules):
            rows.append((item, True))
        else:
            rows.append((item, False))
    rows.sort(key=lambda pair: (pair[0]["start"], pair[0]["activity_id"]))
    blocks = []
    for item, routine in rows:
        part = daypart(item["start"], timezone_name, boundaries)
        if routine and blocks and blocks[-1]["kind"] == "ROUTINE_BLOCK" and blocks[-1]["daypart"] == part and blocks[-1]["assignee_id"] == item["assignee_id"] and (item["start"] - blocks[-1]["end"]).total_seconds() <= merge_gap * 60:
            block = blocks[-1]
            block["activities"].append(item)
            block["end"] = max(block["end"], item["end"])
            block["activity_ids"].append(item["activity_id"])
            block["title"] = f"{block['assignee_name'] or 'Care team'} · {part.lower()} routine · {len(block['activities'])} tasks"
        elif routine:
            blocks.append({"kind": "ROUTINE_BLOCK", "daypart": part, "assignee_id": item["assignee_id"], "assignee_name": item["assignee_name"], "start": item["start"], "end": item["end"], "activities": [item], "activity_ids": [item["activity_id"]], "title": f"{item['assignee_name'] or 'Care team'} · {part.lower()} routine · 1 task", "on_track": True})
        else:
            blocks.append({"kind": "ACTIVITY", "daypart": part, **item})

    suggestions = []
    errands = [row for row, _ in rows if row["category"] in ERRAND_CATEGORIES]
    for index, first in enumerate(errands):
        group = [first]
        for other in errands[index + 1:]:
            same_assignee = first["assignee_id"] == other["assignee_id"]
            within = abs((other["start"] - first["start"]).total_seconds()) <= 3 * 3600
            if same_assignee and within: group.append(other)
        if len(group) > 1 and group[0]["activity_id"] == first["activity_id"]:
            suggestions.append({"kind": "BATCH_ERRANDS", "activity_ids": [row["activity_id"] for row in group], "title": f"Combine {len(group)} nearby errands into one trip", "suggested_action": {"option": "BATCH_ASSIGN"}})

    scheduled = [row for row, _ in rows]
    hours = round(sum(max(0, (x["end"] - x["start"]).total_seconds()) for x in scheduled) / 3600, 2)
    free = None
    if available_windows:
        windows = sorted((start, end) for start, end in available_windows if (start.astimezone(ZoneInfo(timezone_name)).date() if start.tzinfo else start.date()) == day)
        best = (0.0, None)
        for window_start, window_end in windows:
            cursor = window_start
            for row in scheduled:
                left, right = max(window_start, row["start"]), min(window_end, row["end"])
                if right <= left: continue
                if left > cursor and (left - cursor).total_seconds() > best[0]: best = ((left - cursor).total_seconds(), (cursor, left))
                cursor = max(cursor, right)
            if window_end > cursor and (window_end - cursor).total_seconds() > best[0]: best = ((window_end - cursor).total_seconds(), (cursor, window_end))
        if best[1]: free = {"start": best[1][0], "end": best[1][1]}
    return {"day": day.isoformat(), "blocks": blocks, "timeline": [block for block in blocks if block["kind"] == "ACTIVITY"], "handled": handled, "batching_suggestions": suggestions, "load_today": {"hours": hours, "tasks": len(scheduled), "next_free_window": free}}
