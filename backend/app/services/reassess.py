from enum import StrEnum


class TriggerEvent(StrEnum):
    CAREGIVER_UNAVAILABLE = "CAREGIVER_UNAVAILABLE"
    AVAILABILITY_CHANGED = "AVAILABILITY_CHANGED"
    ACTIVITY_ADDED = "ACTIVITY_ADDED"
    ACTIVITY_RESCHEDULED = "ACTIVITY_RESCHEDULED"
    ASSIGNMENT_ADDED = "ASSIGNMENT_ADDED"
    ASSIGNMENT_REMOVED = "ASSIGNMENT_REMOVED"
    ACTIVITIES_OVERLAP = "ACTIVITIES_OVERLAP"
    BACKUP_UNAVAILABLE = "BACKUP_UNAVAILABLE"
    ASSIGNMENT_UNCONFIRMED = "ASSIGNMENT_UNCONFIRMED"
    GAP_RESOLVED_OR_REAPPEARED = "GAP_RESOLVED_OR_REAPPEARED"


def reassess(session, patient_ids, trigger: TriggerEvent, context=None):
    """Phase 2 no-op seam; writes a structured call record in the caller transaction."""
    session.info.setdefault("reassess_calls", []).append({"patient_ids": tuple(patient_ids), "trigger": TriggerEvent(trigger), "context": context or {}})
