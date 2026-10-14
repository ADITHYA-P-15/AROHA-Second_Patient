"""Care-team membership: CareCircle IDs, caretaker care profiles, and who may join a patient's team."""
from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Caregiver, CaregiverPatientLink, CaregiverWeeklySchedule, Patient, Role, User

# No 0/O/1/I/L so an ID read aloud over the phone is unambiguous.
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
DEFAULT_CAPABILITIES = ["MEDICATION_ASSIST", "APPOINTMENT_ESCORT", "TRANSPORT", "DAILY_ASSIST", "PRESCRIPTION_PICKUP"]
DEFAULT_DAY = (480, 1200)  # 08:00–20:00 every day until the caretaker sets their own hours
CARE_KINDS = {Role.CARETAKER: "CARETAKER", Role.PRIMARY_CONTACT: "PRIMARY_CONTACT"}


def new_care_code(db: Session) -> str:
    while True:
        code = "CC-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        if not db.scalar(select(Patient.id).where(Patient.care_code == code)):
            return code


def normalise_code(value: str) -> str:
    raw = "".join(ch for ch in (value or "").upper() if ch.isalnum())
    raw = raw[2:] if raw.startswith("CC") else raw
    return f"CC-{raw}"


def ensure_care_profile(db: Session, user: User, patient_id, *, created_by, relationship: str = "") -> Caregiver:
    """Give a caretaker (or a primary contact who also helps) a care profile linked to this patient."""
    if user.role not in CARE_KINDS:
        raise ValueError("Only caretakers and primary contacts carry out care activities")
    profile = db.scalar(select(Caregiver).where(Caregiver.user_id == user.id))
    if profile is None:
        profile = Caregiver(user_id=user.id, name=user.name, kind=CARE_KINDS[user.role], capabilities=list(DEFAULT_CAPABILITIES),
                            max_activities_per_day=6, max_hours_per_week=40, created_by=created_by, is_synthetic=user.is_synthetic)
        db.add(profile); db.flush()
        db.add_all([CaregiverWeeklySchedule(caregiver_id=profile.id, weekday=d, start_min=DEFAULT_DAY[0], end_min=DEFAULT_DAY[1]) for d in range(7)])
    if not db.scalar(select(CaregiverPatientLink.id).where(CaregiverPatientLink.caregiver_id == profile.id, CaregiverPatientLink.patient_id == patient_id)):
        db.add(CaregiverPatientLink(caregiver_id=profile.id, patient_id=patient_id, relationship=relationship or CARE_KINDS[user.role].replace("_", " ").lower()))
    db.flush()
    return profile


def unlink_care_profile(db: Session, user_id, patient_id) -> None:
    profile = db.scalar(select(Caregiver).where(Caregiver.user_id == user_id))
    if profile:
        link = db.scalar(select(CaregiverPatientLink).where(CaregiverPatientLink.caregiver_id == profile.id, CaregiverPatientLink.patient_id == patient_id))
        if link: db.delete(link)
