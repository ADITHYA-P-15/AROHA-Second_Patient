"""The demo scenario: one coherent, fictional care circle built relative to the current time, and a reset that rebuilds it.

Ramesh Iyer (primary contacts Anita and Karthik) takes three daily doses prescribed by Dr. Arjun Nair and has two
appointments coming up. Savitha is his main caretaker and does everything; Lakshmi is the trained backup and Suresh a
neighbour who can escort. Sharada Pai (primary contact Meera) has one morning dose from Dr. Divya Menon and an eye
check-up, also with Savitha. Yesterday's doses were all given except one evening dose, which shows as missed.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.core.clock import now, to_utc
from app.core.config import settings
from app.models import (ActionItem, ActivityDependency, ActivityHistory, AppSetting, AvailabilityOverride, CareActivity, CareAssignment, Caregiver,
                        CaregiverPatientLink, CaregiverWeeklySchedule, CareTeamMember, CoverageFinding, CoverRequest, CoverRequestEvent, Incident,
                        IncidentEvent, Notification, Patient, PatientMessage, PatientSupportNeed, Prescription, TeamRole, User, VoiceNote)
from app.services.care_feeds import DOSE_GRACE, DOSE_MINUTES, create_appointment, generate_doses
from app.services.care_team import ensure_care_profile

SCENARIO_KEY = "demo_scenario"
SCENARIO_VERSION = 2
DEMO_CODES = ("CC-RAM354", "CC-SHA746")

# email, relationship, capabilities, daily task limit, weekly hours, daily hours (start_min, end_min), patients
CARETAKERS = [
    ("savitha@secondpatient.demo", "caretaker", ["MEDICATION_ASSIST", "DAILY_ASSIST", "MOBILITY_ASSIST", "APPOINTMENT_ESCORT"], 6, 42, (420, 1290), ["Ramesh Iyer", "Sharada Pai"]),
    ("lakshmi@secondpatient.demo", "backup caretaker", ["MEDICATION_ASSIST", "APPOINTMENT_ESCORT", "DAILY_ASSIST", "TRANSPORT"], 4, 30, (480, 1260), ["Ramesh Iyer"]),
    ("suresh.kamath@secondpatient.demo", "neighbour", ["APPOINTMENT_ESCORT", "TRANSPORT"], 3, 20, (480, 1080), ["Ramesh Iyer"]),
]
EXTRA_TEAM = {"Sharada Pai": [("divya.menon@secondpatient.demo", TeamRole.PROFESSIONAL)]}


def demo_patients(db: Session) -> dict[str, Patient]:
    return {p.name: p for p in db.scalars(select(Patient).where(Patient.care_code.in_(DEMO_CODES), Patient.is_synthetic.is_(True)))}


def _demo_users(db: Session) -> dict[str, User]:
    return {u.email: u for u in db.scalars(select(User).where(User.email.like("%@secondpatient.demo"), User.is_synthetic.is_(True)))}


def wipe(db: Session, patient_ids: list) -> None:
    """Remove everything that happened to the demo patients, and the demo caretakers' profiles. Accounts and teams stay."""
    activities = select(CareActivity.id).where(CareActivity.patient_id.in_(patient_ids))
    requests = select(CoverRequest.id).where(CoverRequest.patient_id.in_(patient_ids))
    incidents = select(Incident.id).where(Incident.patient_id.in_(patient_ids))
    caregivers = select(Caregiver.id).where(Caregiver.user_id.in_(select(User.id).where(User.email.like("%@secondpatient.demo"), User.is_synthetic.is_(True))))
    for statement in (
        delete(CoverRequestEvent).where(or_(CoverRequestEvent.request_id.in_(requests), CoverRequestEvent.caregiver_id.in_(caregivers))),
        delete(CoverRequest).where(or_(CoverRequest.patient_id.in_(patient_ids), CoverRequest.offered_caregiver_id.in_(caregivers))),
        delete(CoverageFinding).where(CoverageFinding.patient_id.in_(patient_ids)),
        delete(ActionItem).where(ActionItem.patient_id.in_(patient_ids)),
        delete(Notification).where(or_(Notification.patient_id.in_(patient_ids), Notification.user_id.in_(select(User.id).where(User.email.like("%@secondpatient.demo"))))),
        delete(VoiceNote).where(VoiceNote.patient_id.in_(patient_ids)),
        delete(PatientMessage).where(PatientMessage.patient_id.in_(patient_ids)),
        delete(IncidentEvent).where(IncidentEvent.incident_id.in_(incidents)),
        delete(Incident).where(Incident.patient_id.in_(patient_ids)),
        delete(CareAssignment).where(or_(CareAssignment.activity_id.in_(activities), CareAssignment.caregiver_id.in_(caregivers))),
        delete(ActivityDependency).where(or_(ActivityDependency.activity_id.in_(activities), ActivityDependency.depends_on_activity_id.in_(activities))),
        delete(CareActivity).where(CareActivity.patient_id.in_(patient_ids)),
        delete(Prescription).where(Prescription.patient_id.in_(patient_ids)),
        delete(ActivityHistory).where(ActivityHistory.patient_id.in_(patient_ids)),
        delete(AvailabilityOverride).where(AvailabilityOverride.caregiver_id.in_(caregivers)),
        delete(CaregiverWeeklySchedule).where(CaregiverWeeklySchedule.caregiver_id.in_(caregivers)),
        delete(CaregiverPatientLink).where(or_(CaregiverPatientLink.patient_id.in_(patient_ids), CaregiverPatientLink.caregiver_id.in_(caregivers))),
        delete(Caregiver).where(Caregiver.id.in_(caregivers)),
    ):
        db.execute(statement.execution_options(synchronize_session=False))
    db.expunge_all()


def _past_dose(db, prescription: Prescription, due: datetime, holder: Caregiver, holder_user: User, missed: bool) -> None:
    """A dose from before the demo started: given on time by the holder, or missed."""
    dose = CareActivity(patient_id=prescription.patient_id, title=f"{prescription.medicine} {prescription.dose}", category="MEDICATION", description=prescription.instructions,
                        scheduled_start=to_utc(due), scheduled_end=to_utc(due + timedelta(minutes=DOSE_MINUTES)), deadline=to_utc(due + DOSE_GRACE), importance="HIGH",
                        requires_caregiver=True, required_support=["MEDICATION_ASSIST"], coverage_status="UNASSESSED", is_synthetic=True, created_by=prescription.prescribed_by,
                        source="PRESCRIPTION", source_id=prescription.id, series_id=prescription.id,
                        lifecycle_status="MISSED" if missed else "COMPLETED", missed_at=to_utc(due + DOSE_GRACE) if missed else None,
                        completed_at=None if missed else to_utc(due + timedelta(minutes=8)), completed_by=None if missed else holder_user.id, completed_late=False)
    db.add(dose); db.flush()
    db.add(CareAssignment(activity_id=dose.id, caregiver_id=holder.id, role="PRIMARY", status="CONFIRMED", assigned_by=prescription.prescribed_by,
                          assigned_at=to_utc(due - timedelta(days=1)), confirmed_at=to_utc(due - timedelta(days=1)), confirmed_by=prescription.prescribed_by, confirmed_via="ROUTINE"))


def _prescribe(db, patient: Patient, doctor: User, holder: Caregiver, holder_user: User, medicine: str, dose: str, instructions: str, times: list[str],
               today: date, zone, missed: set[tuple[int, str]] = frozenset()) -> None:
    p = Prescription(patient_id=patient.id, medicine=medicine, dose=dose, instructions=instructions, times=times, start_date=today - timedelta(days=1),
                     end_date=today + timedelta(days=30), status="ACTIVE", prescribed_by=doctor.id)
    db.add(p); db.flush()
    db.add(ActivityHistory(actor_user_id=doctor.id, patient_id=patient.id, event_type="prescription.created", entity_type="prescription", entity_id=str(p.id),
                           summary=f"{doctor.name} prescribed {medicine} {dose} at {', '.join(times)}", payload={}, request_id="",
                           occurred_at=to_utc(datetime.combine(today - timedelta(days=1), time(7, 0), zone))))
    # Doses already due: yesterday and earlier today. One that is still within its grace hour stays pending for the caretaker.
    for offset in (-1, 0):
        day = today + timedelta(days=offset)
        for hhmm in times:
            due = datetime.combine(day, time.fromisoformat(hhmm), zone)
            if due > now(): continue
            if due + DOSE_GRACE > now():
                continue  # generate_doses skips past due times, so add the current one below as pending
            _past_dose(db, p, due, holder, holder_user, (offset, hhmm) in missed)
    for hhmm in times:
        due = datetime.combine(today, time.fromisoformat(hhmm), zone)
        if due <= now() < due + DOSE_GRACE:
            current = CareActivity(patient_id=patient.id, title=f"{medicine} {dose}", category="MEDICATION", description=instructions, scheduled_start=to_utc(due),
                                   scheduled_end=to_utc(due + timedelta(minutes=DOSE_MINUTES)), deadline=to_utc(due + DOSE_GRACE), importance="HIGH", requires_caregiver=True,
                                   required_support=["MEDICATION_ASSIST"], lifecycle_status="SCHEDULED", coverage_status="UNASSESSED", is_synthetic=True,
                                   created_by=doctor.id, source="PRESCRIPTION", source_id=p.id, series_id=p.id)
            db.add(current); db.flush()
            db.add(CareAssignment(activity_id=current.id, caregiver_id=holder.id, role="PRIMARY", status="CONFIRMED", assigned_by=doctor.id, assigned_at=now(),
                                  confirmed_at=now(), confirmed_by=doctor.id, confirmed_via="ROUTINE"))
    generate_doses(db, p, actor_id=doctor.id)


def build(db: Session) -> bool:
    """Create the scenario for the demo patients. Expects them to have no activities, prescriptions or caretaker profiles."""
    patients, users = demo_patients(db), _demo_users(db)
    ramesh, sharada = patients.get("Ramesh Iyer"), patients.get("Sharada Pai")
    if not ramesh or not sharada: return False
    for name, members in EXTRA_TEAM.items():
        for email, role in members:
            user = users.get(email)
            if user and not db.scalar(select(CareTeamMember.id).where(CareTeamMember.patient_id == patients[name].id, CareTeamMember.user_id == user.id)):
                db.add(CareTeamMember(patient_id=patients[name].id, user_id=user.id, team_role=role))
    ramesh.mobility_level = "NEEDS_AID"
    if not db.scalar(select(PatientSupportNeed.id).where(PatientSupportNeed.patient_id == ramesh.id)):
        db.add_all([PatientSupportNeed(patient_id=ramesh.id, support_code=x, notes="Synthetic demo need") for x in ("MEDICATION_ASSIST", "APPOINTMENT_ESCORT")])
    creator = users["anita.iyer@secondpatient.demo"]
    profiles: dict[str, Caregiver] = {}
    for email, relation, capabilities, daily, weekly, (start, end), names in CARETAKERS:
        user = users.get(email)
        if not user: continue
        for name in names:
            profile = ensure_care_profile(db, user, patients[name].id, created_by=creator.id, relationship=relation)
        profile.capabilities, profile.max_activities_per_day, profile.max_hours_per_week = capabilities, daily, weekly
        db.execute(delete(CaregiverWeeklySchedule).where(CaregiverWeeklySchedule.caregiver_id == profile.id))
        db.add_all([CaregiverWeeklySchedule(caregiver_id=profile.id, weekday=d, start_min=start, end_min=end) for d in range(7)])
        profiles[email] = profile
    db.flush()
    savitha = profiles["savitha@secondpatient.demo"]
    for link in db.scalars(select(CaregiverPatientLink).where(CaregiverPatientLink.patient_id.in_((ramesh.id, sharada.id)))):
        link.is_main_caretaker = link.caregiver_id == savitha.id
    db.flush()

    zone = ZoneInfo(settings.app_timezone)
    today = now().astimezone(zone).date()
    arjun, divya, savitha_user = users["dr.arjun.nair@secondpatient.demo"], users["divya.menon@secondpatient.demo"], users["savitha@secondpatient.demo"]
    _prescribe(db, ramesh, arjun, savitha, savitha_user, "Metformin", "500 mg", "After food", ["08:00", "20:00"], today, zone, missed={(-1, "20:00")})
    _prescribe(db, ramesh, arjun, savitha, savitha_user, "Amlodipine", "5 mg", "Morning, with water", ["09:00"], today, zone)
    _prescribe(db, sharada, divya, savitha, savitha_user, "Levothyroxine", "50 mcg", "Empty stomach, 30 minutes before breakfast", ["07:30"], today, zone)

    def on(days: int, hour: int, minute: int = 0) -> datetime:
        return datetime.combine(today + timedelta(days=days), time(hour, minute), zone)
    create_appointment(db, ramesh, title="Cardiology follow-up", start=on(1, 10, 30), minutes=60, location="City Heart Clinic, OPD 3",
                       notes="Bring the last ECG report and the medicine list.", needs_escort=True, importance="HIGH", actor_id=arjun.id)
    create_appointment(db, ramesh, title="Physiotherapy session", start=on(3, 11), minutes=60, location="Sunrise Rehab Centre",
                       notes="Comfortable clothes; walker needed.", needs_escort=True, importance="MEDIUM", actor_id=arjun.id)
    create_appointment(db, sharada, title="Eye check-up", start=on(2, 16), minutes=45, location="Vision Care Clinic",
                       notes="Bring current glasses.", needs_escort=True, importance="MEDIUM", actor_id=divya.id)
    setting = db.get(AppSetting, SCENARIO_KEY)
    if setting is None: db.add(AppSetting(key=SCENARIO_KEY, value={"version": SCENARIO_VERSION}))
    else: setting.value = {"version": SCENARIO_VERSION}
    db.flush()
    return True


def reset(db: Session) -> bool:
    """Wipe and rebuild the demo scenario. Touches only the synthetic demo patients and demo caretakers."""
    patients = demo_patients(db)
    if not patients: return False
    wipe(db, [p.id for p in patients.values()])
    return build(db)


def ensure(db: Session) -> None:
    """On start-up: build the scenario on a fresh database, or rebuild it once when the scenario version changes."""
    patients = demo_patients(db)
    if not patients: return
    setting = db.get(AppSetting, SCENARIO_KEY)
    has_plan = db.scalar(select(Prescription.id).where(Prescription.patient_id.in_([p.id for p in patients.values()])))
    if setting is None or (setting.value or {}).get("version") != SCENARIO_VERSION or not has_plan:
        reset(db)
