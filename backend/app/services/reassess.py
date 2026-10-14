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
    """Record a trigger and refresh deterministic command-center attention in the caller transaction."""
    patient_ids = tuple(dict.fromkeys(patient_ids))
    session.info.setdefault("reassess_calls", []).append({"patient_ids": patient_ids, "trigger": TriggerEvent(trigger), "context": context or {}})
    if not patient_ids:
        return
    session.flush()
    from app.services.backup_matcher import sync_patient
    from app.services.command_center import reconcile_patient
    for patient_id in patient_ids:
        if patient_id is not None:
            # Declines and absences open cover requests in the same transaction as the change that caused them.
            sync_patient(session, patient_id)
            reconcile_patient(session, patient_id)
