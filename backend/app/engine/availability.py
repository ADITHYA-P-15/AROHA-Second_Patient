from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime

    def __post_init__(self):
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("availability windows require timezone-aware datetimes")
        if self.end <= self.start:
            raise ValueError("window end must be after start")


@dataclass(frozen=True)
class AvailabilityResult:
    available: bool
    uncovered_segments: tuple[Window, ...]
    blocking_overrides: tuple[object, ...]


def merge(windows: list[Window] | tuple[Window, ...]) -> list[Window]:
    result: list[Window] = []
    for window in sorted(windows, key=lambda x: x.start):
        if result and window.start <= result[-1].end:
            result[-1] = Window(result[-1].start, max(result[-1].end, window.end))
        else:
            result.append(window)
    return result


def effective_windows(caregiver, start: datetime, end: datetime, timezone: str = "Asia/Kolkata") -> list[Window]:
    """Expand recurring rows, apply unavailable before available overrides, then return intervals."""
    if start.tzinfo is None or end.tzinfo is None or end <= start:
        raise ValueError("from/to must be timezone-aware and to must be after from")
    zone = ZoneInfo(timezone)
    schedules = _get(caregiver, "schedule", _get(caregiver, "weekly_schedule", [])) or []
    overrides = _get(caregiver, "overrides", _get(caregiver, "availability_overrides", [])) or []
    local_start, local_end = start.astimezone(zone), end.astimezone(zone)
    baseline: list[Window] = []
    if schedules:
        date = local_start.date()
        while date <= local_end.date():
            for row in schedules:
                if int(_get(row, "weekday")) != date.weekday():
                    continue
                left = datetime.combine(date, datetime.min.time(), zone) + timedelta(minutes=int(_get(row, "start_min")))
                right = datetime.combine(date, datetime.min.time(), zone) + timedelta(minutes=int(_get(row, "end_min")))
                clipped = Window(max(left, local_start), min(right, local_end)) if min(right, local_end) > max(left, local_start) else None
                if clipped:
                    baseline.append(clipped)
            date += timedelta(days=1)
    active = [(o, _window(o)) for o in overrides if not _get(o, "cancelled_at") and _window(o).end > start and _window(o).start < end]
    unavailable = [w for o, w in active if _get(o, "status") == "UNAVAILABLE"]
    available = [w for o, w in active if _get(o, "status") == "AVAILABLE"]
    base = merge(baseline)
    # AVAILABLE overrides add time regardless of baseline; UNAVAILABLE always subtracts.
    combined = merge(base + [Window(max(w.start, start), min(w.end, end)) for w in available if min(w.end, end) > max(w.start, start)])
    return _subtract(combined, unavailable)


def is_available_for(caregiver, window: Window | tuple[datetime, datetime], timezone: str = "Asia/Kolkata") -> AvailabilityResult:
    required = window if isinstance(window, Window) else Window(*window)
    effective = effective_windows(caregiver, required.start, required.end, timezone)
    uncovered = _subtract([required], effective)
    overrides = _get(caregiver, "overrides", _get(caregiver, "availability_overrides", [])) or []
    blockers = tuple(o for o in overrides if _get(o, "status") == "UNAVAILABLE" and not _get(o, "cancelled_at") and _window(o).start < required.end and _window(o).end > required.start)
    return AvailabilityResult(not uncovered, tuple(uncovered), blockers)


def _window(obj):
    start, end = _get(obj, "start_at"), _get(obj, "end_at")
    from datetime import UTC
    if start.tzinfo is None: start = start.replace(tzinfo=UTC)
    if end.tzinfo is None: end = end.replace(tzinfo=UTC)
    return Window(start, end)


def _get(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def _subtract(windows: list[Window], cuts: list[Window]) -> list[Window]:
    result = merge(windows)
    for cut in cuts:
        next_result = []
        for item in result:
            if cut.end <= item.start or cut.start >= item.end:
                next_result.append(item)
            else:
                if cut.start > item.start:
                    next_result.append(Window(item.start, cut.start))
                if cut.end < item.end:
                    next_result.append(Window(cut.end, item.end))
        result = next_result
    return result
