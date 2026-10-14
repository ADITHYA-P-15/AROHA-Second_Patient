"""Medication and appointment data feeds from healthcare professionals.

A prescription expands into one dose activity per due time for a rolling window, so the caretaker sees each dose
in My Day and the scheduler can mark it missed. An appointment is a single activity that needs an escort. New feed
activities go to the patient's main caretaker when they can do them; otherwise the cover flow takes over.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import now, to_utc
from app.core.config import settings
from app.models import ActivityHistory, CareActivity, CareAssignment, Caregiver, CaregiverPatientLink, Patient, Prescription

DOSE_WINDOW_DAYS = 14
DOSE_MINUTES = 15
DOSE_GRACE = timedelta(minutes=60)  # a dose not recorded within an hour of its due time is missed
APPOINTMENT_TRAVEL_MIN = 30
APPOINTMENT_GRACE = timedelta(minutes=60)  # the escort records it after the visit; missed only if not recorded an hour after it ends
ACTIVE = ("PROPOSED", "AWAITING_CONFIRMATION", "CONFIRMED")


def _zone():
    return ZoneInfo(settings.app_timezone)


def _history(db, patient_id, actor_id, event, entity_id, summary, payload=None):
    db.add(ActivityHistory(actor_user_id=actor_id, patient_id=patient_id, event_type=event, entity_type="care_activity",
                           entity_id=str(entity_id), summary=summary[:500], payload=payload or {}, request_id=""))


def main_caretaker(db: Session, patient_id) -> Caregiver | None:
    return db.scalar(select(Caregiver).join(CaregiverPatientLink, CaregiverPatientLink.caregiver_id == Caregiver.id)
                     .where(CaregiverPatientLink.patient_id == patient_id, CaregiverPatientLink.is_main_caretaker.is_(True), Caregiver.is_active.is_(True)))


def auto_assign(db: Session, activity: CareActivity, actor_id) -> CareAssignment | None:
    """Give a new feed activity to the main caretaker only when they are fully eligible (skill, hours, no clash, limits).

    Otherwise it stays unassigned and the cover flow offers it to someone who is.
    """
    if db.scalar(select(CareAssignment.id).where(CareAssignment.activity_id == activity.id, CareAssignment.role == "PRIMARY", CareAssignment.status.in_(ACTIVE))):
        return None
    caretaker = main_caretaker(db, activity.patient_id)
    if caretaker is None: return None
    from app.services.backup_matcher import candidate_row
    row = candidate_row(db, activity, caretaker.id)
    if not row or not row["eligible"]: return None
    assignment = CareAssignment(activity_id=activity.id, caregiver_id=caretaker.id, role="PRIMARY", status="CONFIRMED", assigned_by=actor_id,
                                assigned_at=now(), confirmed_at=now(), confirmed_by=actor_id, confirmed_via="ROUTINE")
    db.add(assignment); db.flush()
    return assignment


def generate_doses(db: Session, prescription: Prescription, *, through: date | None = None, actor_id=None) -> int:
    """Create missing dose activities from today (or the start date) through the rolling window. Idempotent."""
    if prescription.status != "ACTIVE": return 0
    zone = _zone()
    today = now().astimezone(zone).date()
    first = max(prescription.start_date, today)
    last = min(prescription.end_date or (today + timedelta(days=DOSE_WINDOW_DAYS)), through or (today + timedelta(days=DOSE_WINDOW_DAYS)))
    patient = db.get(Patient, prescription.patient_id)
    # Cancelled doses (e.g. replaced by an edit) do not block regenerating the same due time.
    window_start = to_utc(datetime.combine(first, time.min, zone))
    existing = {_aware_utc(a.scheduled_start) for a in db.scalars(select(CareActivity).where(CareActivity.source == "PRESCRIPTION", CareActivity.source_id == prescription.id,
                                                                                            CareActivity.lifecycle_status != "CANCELLED", CareActivity.scheduled_start >= window_start))}
    created = 0
    day = first
    while day <= last:
        for hhmm in sorted(prescription.times):
            due = datetime.combine(day, time.fromisoformat(hhmm), zone)
            if due <= now() or to_utc(due) in existing: continue
            dose = CareActivity(patient_id=prescription.patient_id, title=f"{prescription.medicine} {prescription.dose}".strip(), category="MEDICATION",
                                description=prescription.instructions, scheduled_start=to_utc(due), scheduled_end=to_utc(due + timedelta(minutes=DOSE_MINUTES)),
                                deadline=to_utc(due + DOSE_GRACE), importance="HIGH", requires_caregiver=True, required_support=["MEDICATION_ASSIST"],
                                lifecycle_status="SCHEDULED", coverage_status="UNASSESSED", is_synthetic=patient.is_synthetic, created_by=prescription.prescribed_by,
                                source="PRESCRIPTION", source_id=prescription.id, series_id=prescription.id)
            db.add(dose); db.flush()
            auto_assign(db, dose, actor_id or prescription.prescribed_by)
            created += 1
        day += timedelta(days=1)
    return created


def cancel_future_doses(db: Session, prescription: Prescription, reason: str) -> int:
    rows = db.scalars(select(CareActivity).where(CareActivity.source == "PRESCRIPTION", CareActivity.source_id == prescription.id,
                                                 CareActivity.lifecycle_status == "SCHEDULED", CareActivity.scheduled_start > now())).all()
    for row in rows:
        cancel_activity(db, row, reason)
    return len(rows)


def cancel_activity(db: Session, activity: CareActivity, reason: str) -> None:
    """Cancel a pending activity and release whoever held or was asked to hold it."""
    activity.lifecycle_status, activity.gap_reason = "CANCELLED", reason[:120]
    for assignment in db.scalars(select(CareAssignment).where(CareAssignment.activity_id == activity.id, CareAssignment.status.in_(ACTIVE))):
        assignment.status, assignment.updated_at = "CANCELLED", now()


def refresh_future_doses(db: Session, prescription: Prescription) -> int:
    """Dose or instructions changed but not the timetable: update pending doses in place, keeping their caretakers."""
    rows = db.scalars(select(CareActivity).where(CareActivity.source == "PRESCRIPTION", CareActivity.source_id == prescription.id,
                                                 CareActivity.lifecycle_status == "SCHEDULED", CareActivity.scheduled_start > now())).all()
    for row in rows:
        row.title, row.description = f"{prescription.medicine} {prescription.dose}".strip(), prescription.instructions
    return len(rows)


def create_appointment(db: Session, patient: Patient, *, title: str, start: datetime, minutes: int, location: str, notes: str,
                       needs_escort: bool, importance: str, actor_id) -> CareActivity:
    appointment = CareActivity(patient_id=patient.id, title=title, category="APPOINTMENT", description=notes, location_note=location,
                               scheduled_start=to_utc(start), scheduled_end=to_utc(start + timedelta(minutes=minutes)), deadline=to_utc(start + timedelta(minutes=minutes) + APPOINTMENT_GRACE),
                               importance=importance, requires_caregiver=needs_escort, required_support=["APPOINTMENT_ESCORT"] if needs_escort else [],
                               buffer_before_min=APPOINTMENT_TRAVEL_MIN if needs_escort else 0, buffer_after_min=APPOINTMENT_TRAVEL_MIN if needs_escort else 0,
                               lifecycle_status="SCHEDULED", coverage_status="UNASSESSED", is_synthetic=patient.is_synthetic, created_by=actor_id,
                               source="APPOINTMENT")
    db.add(appointment); db.flush()
    if needs_escort: auto_assign(db, appointment, actor_id)
    _history(db, patient.id, actor_id, "appointment.scheduled", appointment.id, f"Appointment scheduled: {title}")
    return appointment


def roll_forward(db: Session) -> int:
    """Daily top-up of the rolling dose window for every active prescription."""
    return sum(generate_doses(db, p) for p in db.scalars(select(Prescription).where(Prescription.status == "ACTIVE")).all())


def adherence(db: Session, patient_id, days: int) -> dict:
    """Doses that were due in the last `days` days, per medicine: on time, late, missed."""
    since = now() - timedelta(days=days)
    rows = db.scalars(select(CareActivity).where(CareActivity.patient_id == patient_id, CareActivity.source == "PRESCRIPTION",
                                                 CareActivity.scheduled_start >= since, CareActivity.scheduled_start <= now())).all()
    prescriptions = {p.id: p for p in db.scalars(select(Prescription).where(Prescription.patient_id == patient_id))}
    per: dict = {}
    for row in rows:
        p = prescriptions.get(row.source_id)
        key = str(row.source_id)
        item = per.setdefault(key, {"prescription_id": key, "medicine": p.medicine if p else row.title, "dose": p.dose if p else "",
                                    "due": 0, "on_time": 0, "late": 0, "missed": 0, "pending": 0})
        if row.lifecycle_status == "CANCELLED": continue
        item["due"] += 1
        if row.lifecycle_status == "COMPLETED": item["late" if row.completed_late else "on_time"] += 1
        elif row.lifecycle_status == "MISSED": item["missed"] += 1
        else: item["pending"] += 1
    for item in per.values():
        decided = item["on_time"] + item["late"] + item["missed"]
        item["on_time_pct"] = round(100 * item["on_time"] / decided, 1) if decided else None
    totals = {k: sum(i[k] for i in per.values()) for k in ("due", "on_time", "late", "missed", "pending")}
    decided = totals["on_time"] + totals["late"] + totals["missed"]
    return {"days": days, "medicines": sorted(per.values(), key=lambda i: i["medicine"]), "totals": totals,
            "on_time_pct": round(100 * totals["on_time"] / decided, 1) if decided else None,
            "note": "Records what the care team logged. It is a coordination record, not a clinical assessment."}


def _aware_utc(value):
    from datetime import UTC
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
