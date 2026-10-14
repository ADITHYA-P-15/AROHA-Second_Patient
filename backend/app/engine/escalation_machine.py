"""Pure, deterministic time-boxed incident progression rules."""
from dataclasses import dataclass
from datetime import datetime, timedelta
import re

DEFAULT_POLICY = {
    "ack_minutes": {"1": 10, "2": 15, "3": 30, "4": 60, "5": 2},
    "resolve_minutes": {"1": 30, "2": 60, "3": 90, "4": 120, "5": 30},
    "family_contact_delay_fraction": 0.5,
    "quiet_hours": {"start": "22:00", "end": "06:00"},
}


def validate_policy(policy: dict) -> None:
    required = {"1", "2", "3", "4", "5"}
    for field in ("ack_minutes", "resolve_minutes"):
        timers = policy.get(field, {})
        if set(timers) != required or any(not isinstance(value, int) or not 1 <= value <= 1440 for value in timers.values()):
            raise ValueError(f"{field} must define levels 1–5 between 1 and 1440 minutes")
    if policy["ack_minutes"]["5"] > 5:
        raise ValueError("Emergency acknowledgement cadence cannot exceed 5 minutes")
    quiet = policy.get("quiet_hours", {})
    if set(quiet) != {"start", "end"} or any(not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value) for value in quiet.values()):
        raise ValueError("Quiet hours must contain start and end in HH:MM format")

@dataclass(frozen=True)
class Action:
    kind: str
    to_level: int
    deadline_kind: str
    delay_minutes: float
    reason: str
    show_emergency_banner: bool = False


def deadline_minutes(policy: dict, level: int, kind: str, severity: str = "MEDIUM", scale: float = 1.0) -> float:
    table = policy["ack_minutes" if kind == "ACK" else "resolve_minutes"]
    value = float(table[str(level)])
    multiplier = 0.5 if severity == "HIGH" else 2.0 if severity == "LOW" else 1.0
    return max(0.01, value * multiplier * scale)


def auto_level_cap(category: str, importance: str = "MEDIUM") -> int:
    if category == "EMERGENCY": return 5
    if category in {"DAILY_HELP", "LOGISTICS", "TASK"}:
        return 4 if importance == "CRITICAL" else 3
    if category in {"HEALTH_CONCERN", "MEDICATION"}:
        return 4
    return 4


def _align_datetime(value: datetime, reference: datetime) -> datetime:
    return value.replace(tzinfo=reference.tzinfo) if value.tzinfo is None else value


def next_action(state: dict, policy: dict, now: datetime, *, scale: float = 1.0) -> Action | None:
    """Return the single due transition; callers persist it then call again for catch-up."""
    if state.get("status") in {"RESOLVED", "CANCELLED"}:
        return None
    deadline = state.get("current_deadline_at")
    if deadline is not None: deadline = _align_datetime(deadline, now)
    if deadline is None or now < deadline:
        return None
    level = int(state["current_level"])
    severity = state.get("severity", "MEDIUM")
    category = state.get("category", "UNCLASSIFIED")
    kind = state.get("deadline_kind", "ACK")
    if level == 5:
        if state.get("acknowledged_at") is None:
            created = state.get("created_at", deadline)
            created = _align_datetime(created, now)
            unacknowledged = not state.get("emergency_unacknowledged") and now >= created + timedelta(minutes=5 * scale)
            return Action("UNACKNOWLEDGED_EMERGENCY" if unacknowledged else "REMINDER_EMERGENCY", 5, "ACK", deadline_minutes(policy, 5, "ACK", severity, scale), "Emergency remains unacknowledged", unacknowledged)
        return Action("REMINDER_EMERGENCY", 5, "RESOLVE", deadline_minutes(policy, 5, "RESOLVE", severity, scale), "Emergency remains unresolved")
    if level == 4:
        return Action("REMINDER_DOCTOR", 4, "ACK" if kind == "ACK" else "RESOLVE", deadline_minutes(policy, 4, kind, severity, scale), "No doctor response — consider contacting the clinic")
    cap = auto_level_cap(category, state.get("importance", "MEDIUM"))
    if level >= cap:
        return Action("REMINDER_CAP", level, kind, deadline_minutes(policy, level, kind, severity, scale), "Incident is unhandled at its category cap")
    new_level = min(level + 1, cap)
    return Action("AUTO_ESCALATED", new_level, "ACK", deadline_minutes(policy, new_level, "ACK", severity, scale), "Acknowledgement deadline expired" if kind == "ACK" else "Acknowledged but unresolved")
