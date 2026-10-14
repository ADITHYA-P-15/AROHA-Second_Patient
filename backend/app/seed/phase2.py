"""Synthetic care network and plan, relative to the app clock. Idempotent: safe to run on an existing demo database."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import now, to_utc
from app.models import (ActivityDependency, ActivityHistory, AvailabilityOverride, CareActivity, CareAssignment, Caregiver, CaregiverPatientLink,
                        CaregiverWeeklySchedule, CareTeamMember, Patient, PatientSupportNeed, Prescription, TeamRole, User)
from app.services.care_feeds import generate_doses
from app.services.care_team import ensure_care_profile

# name, email, capabilities, daily task limit, weekly hours, weekly windows (weekday, start_min, end_min), patients, relationship
NETWORK = [
    ("Anita Iyer", "anita.iyer@secondpatient.demo", ["TRANSPORT", "APPOINTMENT_ESCORT", "MEDICATION_ASSIST", "PRESCRIPTION_PICKUP"], 3, 40,
     [(d, 0, 1440) for d in range(7)], ["Ramesh Iyer"], "daughter"),
    ("Karthik Iyer", "karthik.iyer@secondpatient.demo", ["TRANSPORT", "PRESCRIPTION_PICKUP", "SUPPLIES"], 3, 30,
     [(d, 420, 1140) for d in range(7)], ["Ramesh Iyer"], "son"),
    ("Savitha", "savitha@secondpatient.demo", ["DAILY_ASSIST", "MEDICATION_ASSIST", "MOBILITY_ASSIST", "PRESCRIPTION_PICKUP"], 4, 35,
     [(d, 360, 900) for d in range(7)], ["Ramesh Iyer", "Sharada Pai"], "caretaker"),
    ("Lakshmi Rao", "lakshmi@secondpatient.demo", ["MEDICATION_ASSIST", "DAILY_ASSIST", "APPOINTMENT_ESCORT", "TRANSPORT"], 4, 30,
     [(d, 420, 1080) for d in range(5)], ["Ramesh Iyer"], "caretaker"),
    ("Suresh Kamath", "suresh.kamath@secondpatient.demo", ["TRANSPORT", "APPOINTMENT_ESCORT"], 3, 20,
     [(d, 360, 750) for d in range(7)], ["Ramesh Iyer"], "caretaker (neighbour)"),
    ("Meera Pai", "meera.pai@secondpatient.demo", ["TRANSPORT", "APPOINTMENT_ESCORT", "DAILY_ASSIST"], 3, 25,
     [(d, 480, 1080) for d in range(7)], ["Sharada Pai"], "daughter"),
]
TEAM = {"Ramesh Iyer": [("lakshmi@secondpatient.demo", TeamRole.CARETAKER), ("suresh.kamath@secondpatient.demo", TeamRole.CARETAKER)]}


def seed_phase2(db: Session) -> None:
    ramesh = db.scalar(select(Patient).where(Patient.name == "Ramesh Iyer"))
    sharada = db.scalar(select(Patient).where(Patient.name == "Sharada Pai"))
    if not ramesh or not sharada:
        return
    users = {u.email: u for u in db.scalars(select(User)).all()}
    patients = {"Ramesh Iyer": ramesh, "Sharada Pai": sharada}
    # Documented demo IDs, also on databases upgraded from before CareCircle IDs existed.
    for patient, code in ((ramesh, "CC-RAM354"), (sharada, "CC-SHA746")):
        if patient.is_synthetic and patient.care_code != code and not db.scalar(select(Patient.id).where(Patient.care_code == code)):
            patient.care_code = code
    creator = users["anita.iyer@secondpatient.demo"]
    # Older demo databases predate these caretakers: add them to the team.
    for patient_name, members in TEAM.items():
        for email, team_role in members:
            user = users.get(email)
            if user and not db.scalar(select(CareTeamMember.id).where(CareTeamMember.patient_id == patients[patient_name].id, CareTeamMember.user_id == user.id)):
                db.add(CareTeamMember(patient_id=patients[patient_name].id, user_id=user.id, team_role=team_role))
    db.flush()

    ramesh.mobility_level = "NEEDS_AID"
    if not db.scalar(select(PatientSupportNeed.id).where(PatientSupportNeed.patient_id == ramesh.id)):
        db.add_all([PatientSupportNeed(patient_id=ramesh.id, support_code=x, notes="Synthetic demo need") for x in ("TRANSPORT", "MEDICATION_ASSIST", "APPOINTMENT_ESCORT")])

    caregivers = {}
    for name, email, capabilities, daily, weekly, windows, patient_names, relation in NETWORK:
        user = users.get(email)
        if not user: continue
        fresh = db.scalar(select(Caregiver).where(Caregiver.user_id == user.id)) is None
        for patient_name in patient_names:
            profile = ensure_care_profile(db, user, patients[patient_name].id, created_by=creator.id, relationship=relation)
        if fresh:
            profile.capabilities, profile.max_activities_per_day, profile.max_hours_per_week = capabilities, daily, weekly
            db.query(CaregiverWeeklySchedule).filter(CaregiverWeeklySchedule.caregiver_id == profile.id).delete()
            db.add_all([CaregiverWeeklySchedule(caregiver_id=profile.id, weekday=d, start_min=a, end_min=b) for d, a, b in windows])
        caregivers[name] = profile
    db.flush()

    zone = ZoneInfo("Asia/Kolkata")
    tomorrow = now().astimezone(zone).date() + timedelta(days=1)
    day3, day4 = tomorrow + timedelta(days=2), tomorrow + timedelta(days=3)
    karthik = caregivers.get("Karthik Iyer")
    override_start = to_utc(datetime.combine(tomorrow, time(12, 30), zone))
    if karthik and not db.scalar(select(AvailabilityOverride.id).where(AvailabilityOverride.caregiver_id == karthik.id)):
        db.add(AvailabilityOverride(caregiver_id=karthik.id, start_at=override_start, end_at=override_start + timedelta(minutes=90), status="UNAVAILABLE", reason="WORK", note="Synthetic scheduled work conflict", created_by=creator.id))

    def at(day, hour, minute=0):
        return datetime.combine(day, time(hour, minute), zone)

    def ensure_activity(patient, title, category, start, end, support, importance="MEDIUM", caregiver=None, deadline=None, before=0, after=0):
        activity = db.scalar(select(CareActivity).where(CareActivity.patient_id == patient.id, CareActivity.title == title, CareActivity.is_synthetic.is_(True)))
        if not activity:
            activity = CareActivity(patient_id=patient.id, title=title, category=category, scheduled_start=to_utc(start), scheduled_end=to_utc(end), deadline=to_utc(deadline or end),
                                    importance=importance, requires_caregiver=True, required_support=support, buffer_before_min=before, buffer_after_min=after,
                                    lifecycle_status="SCHEDULED", coverage_status="UNASSESSED", is_synthetic=True, created_by=creator.id)
            db.add(activity); db.flush()
            db.add(ActivityHistory(actor_user_id=creator.id, patient_id=patient.id, event_type="activity.seeded", entity_type="care_activity", entity_id=str(activity.id), summary="Synthetic demo care activity added", payload={"is_synthetic": True}))
        elif activity.lifecycle_status == "SCHEDULED":
            activity.scheduled_start, activity.scheduled_end, activity.deadline = to_utc(start), to_utc(end), to_utc(deadline or end)
        if caregiver and not db.scalar(select(CareAssignment.id).where(CareAssignment.activity_id == activity.id, CareAssignment.caregiver_id == caregiver.id)):
            db.add(CareAssignment(activity_id=activity.id, caregiver_id=caregiver.id, role="PRIMARY", status="CONFIRMED", assigned_by=creator.id, assigned_at=now(), confirmed_at=now(), confirmed_by=creator.id, confirmed_via="COORDINATOR"))
        return activity

    anita, savitha, lakshmi, suresh = caregivers["Anita Iyer"], caregivers["Savitha"], caregivers["Lakshmi Rao"], caregivers["Suresh Kamath"]
    appointment = ensure_activity(ramesh, "Cardiology follow-up", "APPOINTMENT", at(tomorrow, 10, 30), at(tomorrow, 11, 30), ["APPOINTMENT_ESCORT"], "CRITICAL", anita, before=30, after=30)
    outbound = ensure_activity(ramesh, "Transport to hospital", "TRANSPORT", at(tomorrow, 9, 45), at(tomorrow, 10, 0), ["TRANSPORT"], caregiver=anita)
    returned = ensure_activity(ramesh, "Return transport from hospital", "TRANSPORT", at(tomorrow, 12, 0), at(tomorrow, 12, 15), ["TRANSPORT"], caregiver=anita)
    if not db.get(ActivityDependency, {"activity_id": returned.id, "depends_on_activity_id": appointment.id}): db.add(ActivityDependency(activity_id=returned.id, depends_on_activity_id=appointment.id))
    if not db.get(ActivityDependency, {"activity_id": appointment.id, "depends_on_activity_id": outbound.id}): db.add(ActivityDependency(activity_id=appointment.id, depends_on_activity_id=outbound.id))
    ensure_activity(ramesh, "Prescription pickup", "PRESCRIPTION", at(tomorrow, 12, 30), at(tomorrow, 13, 30), ["PRESCRIPTION_PICKUP"], "HIGH", anita, deadline=at(tomorrow, 18))
    ensure_activity(ramesh, "Physiotherapy appointment", "APPOINTMENT", at(day3, 11), at(day3, 12), ["APPOINTMENT_ESCORT"], "HIGH", lakshmi, before=30, after=30)
    ensure_activity(ramesh, "Lab visit", "LAB", at(day3, 9), at(day3, 9, 30), ["TRANSPORT"], caregiver=karthik)
    ensure_activity(ramesh, "Post-appointment assistance", "POST_APPOINTMENT", at(tomorrow, 14), at(tomorrow, 14, 30), ["DAILY_ASSIST"], caregiver=savitha)
    ensure_activity(ramesh, "Medical supplies pickup", "SUPPLIES", at(day4, 15), at(day4, 16), ["SUPPLIES"], importance="LOW")
    ensure_activity(sharada, "Daily assistance and meal preparation", "DAILY_ROUTINE", at(tomorrow, 8), at(tomorrow, 9), ["DAILY_ASSIST"], caregiver=savitha)
    ensure_activity(sharada, "Meal preparation", "DAILY_ROUTINE", at(tomorrow, 9), at(tomorrow, 10), ["DAILY_ASSIST"], caregiver=savitha)
    ensure_activity(sharada, "Doctor visit", "APPOINTMENT", at(day3, 11), at(day3, 12), ["APPOINTMENT_ESCORT"], caregiver=caregivers.get("Meera Pai"))
    _ = suresh  # Suresh is the spare driver the Backup Matcher and planner can draw on.

    # Older demo data had hand-made medication tasks and a clinical visit; doses now come from prescriptions.
    for legacy in db.scalars(select(CareActivity).where(CareActivity.is_synthetic.is_(True), CareActivity.lifecycle_status == "SCHEDULED", CareActivity.source == "MANUAL",
                                                        (CareActivity.title.like("Morning medication assistance%")) | (CareActivity.title == "Weekly nurse visit"))):
        legacy.lifecycle_status, legacy.gap_reason = "CANCELLED", "Replaced by prescription doses"

    # Data feeds: Savitha is Ramesh's main caretaker; Dr. Arjun's prescriptions expand into doses assigned to her when she can do them.
    for link in db.scalars(select(CaregiverPatientLink).where(CaregiverPatientLink.patient_id == ramesh.id)):
        link.is_main_caretaker = link.caregiver_id == savitha.id
    for activity in db.scalars(select(CareActivity).where(CareActivity.category == "APPOINTMENT", CareActivity.source == "MANUAL", CareActivity.is_synthetic.is_(True))):
        activity.source = "APPOINTMENT"
    doctor = users.get("dr.arjun.nair@secondpatient.demo")
    if doctor and not db.scalar(select(Prescription.id).where(Prescription.patient_id == ramesh.id)):
        today = now().astimezone(zone).date()
        for medicine, dose, instructions, times in (("Metformin", "500 mg", "After food", ["08:00", "20:00"]), ("Amlodipine", "5 mg", "Morning, with water", ["09:00"])):
            prescription = Prescription(patient_id=ramesh.id, medicine=medicine, dose=dose, instructions=instructions, times=times, start_date=today,
                                        end_date=today + timedelta(days=30), status="ACTIVE", prescribed_by=doctor.id)
            db.add(prescription); db.flush()
            generate_doses(db, prescription, through=today + timedelta(days=7), actor_id=doctor.id)
