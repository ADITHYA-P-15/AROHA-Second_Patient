"""Synthetic core care network and plan, relative to the app clock."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import now, to_utc
from app.models import (ActivityDependency, ActivityHistory, AvailabilityOverride, CareActivity, CareAssignment, Caregiver, CaregiverPatientLink, CaregiverWeeklySchedule, Patient, PatientSupportNeed, User)


def seed_phase2(db: Session) -> None:
    if not db.scalar(select(Patient).where(Patient.name == "Ramesh Iyer")):
        return
    users = {u.email: u for u in db.scalars(select(User)).all()}
    ramesh = db.scalar(select(Patient).where(Patient.name == "Ramesh Iyer"))
    sharada = db.scalar(select(Patient).where(Patient.name == "Sharada Pai"))
    if not ramesh or not sharada:
        return
    ramesh.mobility_level = "NEEDS_AID"
    if not db.scalar(select(PatientSupportNeed.id).where(PatientSupportNeed.patient_id == ramesh.id)):
        db.add_all([PatientSupportNeed(patient_id=ramesh.id, support_code=x, notes="Synthetic demo need") for x in ("TRANSPORT", "MEDICATION_ASSIST", "PRESCRIPTION_PICKUP")])
    zone = ZoneInfo("Asia/Kolkata")
    tomorrow = now().astimezone(zone).date() + timedelta(days=1)
    day3, day4 = tomorrow + timedelta(days=2), tomorrow + timedelta(days=3)

    specs = [
        ("Anita Iyer", "FAMILY", "anita.iyer@secondpatient.demo", ["TRANSPORT", "APPOINTMENT_ESCORT", "MEDICATION_ASSIST", "PRESCRIPTION_PICKUP"], 3, 40),
        ("Karthik Iyer", "FAMILY", "karthik.iyer@secondpatient.demo", ["TRANSPORT", "PRESCRIPTION_PICKUP", "SUPPLIES"], 3, 30),
        ("Suresh Kamath", "NEIGHBOUR", None, ["TRANSPORT", "APPOINTMENT_ESCORT"], 3, 20),
        ("Savitha", "HOUSEHELP", "savitha@secondpatient.demo", ["DAILY_ASSIST", "MEDICATION_ASSIST", "MOBILITY_ASSIST", "PRESCRIPTION_PICKUP"], 4, 35),
        ("Divya Menon", "NURSE", "divya.menon@secondpatient.demo", ["CLINICAL_VISIT", "MEDICATION_ASSIST"], 3, 24),
        ("Meera Pai", "FAMILY", "meera.pai@secondpatient.demo", ["TRANSPORT", "APPOINTMENT_ESCORT", "DAILY_ASSIST"], 3, 25),
    ]
    caregivers = {}
    for name, kind, email, capabilities, daily, weekly in specs:
        linked_user = users.get(email) if email else None
        cg = db.scalar(select(Caregiver).where(Caregiver.user_id == linked_user.id)) if linked_user else db.scalar(select(Caregiver).where(Caregiver.name == name, Caregiver.is_synthetic.is_(True)))
        if not cg:
            cg = Caregiver(name=name, kind=kind, user_id=linked_user.id if linked_user else None, capabilities=capabilities, max_activities_per_day=daily, max_hours_per_week=weekly, created_by=users["admin@secondpatient.demo"].id, is_synthetic=True)
            db.add(cg); db.flush()
        caregivers[name] = cg
        patient_list = [ramesh, sharada] if name == "Savitha" else [sharada] if name == "Meera Pai" else [ramesh]
        for patient in patient_list:
            link = db.scalar(select(CaregiverPatientLink).where(CaregiverPatientLink.caregiver_id == cg.id, CaregiverPatientLink.patient_id == patient.id))
            relation = {"Anita Iyer":"daughter", "Karthik Iyer":"son", "Suresh Kamath":"neighbour", "Savitha":"househelp", "Divya Menon":"nurse", "Meera Pai":"daughter"}[name]
            if not link:
                db.add(CaregiverPatientLink(caregiver_id=cg.id, patient_id=patient.id, relationship=relation, is_designated_backup=(name == "Divya Menon")))
            elif link.relationship == "care network":
                link.relationship = relation

    schedules = {
        "Anita Iyer": [(d, 0, 1440) for d in range(7)],
        "Karthik Iyer": [(d, 420, 1140) for d in range(7)],
        "Suresh Kamath": [(d, 360, 750) for d in range(7)],
        "Savitha": [(d, 360, 900) for d in range(7)],
        "Divya Menon": [(d, 480, 1020) for d in range(5)],
        "Meera Pai": [(d, 480, 1080) for d in range(7)],
    }
    for name, windows in schedules.items():
        cg = caregivers[name]
        if not db.scalar(select(CaregiverWeeklySchedule.id).where(CaregiverWeeklySchedule.caregiver_id == cg.id)):
            db.add_all([CaregiverWeeklySchedule(caregiver_id=cg.id, weekday=day, start_min=start, end_min=end) for day, start, end in windows])
    karthik = caregivers["Karthik Iyer"]
    override_start = to_utc(datetime.combine(tomorrow, time(12, 30), zone))
    if not db.scalar(select(AvailabilityOverride.id).where(AvailabilityOverride.caregiver_id == karthik.id)):
        db.add(AvailabilityOverride(caregiver_id=karthik.id, start_at=override_start, end_at=override_start + timedelta(minutes=90), status="UNAVAILABLE", reason="WORK", note="Synthetic scheduled work conflict", created_by=users["admin@secondpatient.demo"].id))

    def at(day, hour, minute=0):
        return datetime.combine(day, time(hour, minute), zone)

    def ensure_activity(patient, title, category, start, end, support, importance="MEDIUM", caregiver=None, buffer_before=0, buffer_after=0, deadline=None, is_backup=False):
        activity = db.scalar(select(CareActivity).where(CareActivity.patient_id == patient.id, CareActivity.title == title, CareActivity.is_synthetic.is_(True)))
        if not activity:
            activity = CareActivity(patient_id=patient.id, title=title, category=category, scheduled_start=to_utc(start), scheduled_end=to_utc(end), deadline=to_utc(deadline or end), importance=importance, requires_caregiver=True, required_support=support, buffer_before_min=buffer_before, buffer_after_min=buffer_after, lifecycle_status="SCHEDULED", coverage_status="UNASSESSED", is_synthetic=True, created_by=users["admin@secondpatient.demo"].id)
            db.add(activity); db.flush()
            db.add(ActivityHistory(actor_user_id=users["admin@secondpatient.demo"].id, patient_id=patient.id, event_type="activity.seeded", entity_type="care_activity", entity_id=str(activity.id), summary="Synthetic demo care activity added", payload={"is_synthetic": True}))
        elif activity.lifecycle_status == "SCHEDULED":
            activity.scheduled_start = to_utc(start); activity.scheduled_end = to_utc(end); activity.deadline = to_utc(deadline or end)
        if caregiver and not db.scalar(select(CareAssignment.id).where(CareAssignment.activity_id == activity.id, CareAssignment.caregiver_id == caregiver.id)):
            db.add(CareAssignment(activity_id=activity.id, caregiver_id=caregiver.id, role="BACKUP" if is_backup else "PRIMARY", status="CONFIRMED", assigned_by=users["admin@secondpatient.demo"].id, assigned_at=now(), confirmed_at=now(), confirmed_by=users["admin@secondpatient.demo"].id, confirmed_via="COORDINATOR"))
        return activity

    appointment = ensure_activity(ramesh, "Cardiology follow-up", "APPOINTMENT", at(tomorrow, 10, 30), at(tomorrow, 11, 30), ["APPOINTMENT_ESCORT"], "CRITICAL", caregivers["Anita Iyer"])
    outbound = ensure_activity(ramesh, "Transport to hospital", "TRANSPORT", at(tomorrow, 9, 45), at(tomorrow, 10, 30), ["TRANSPORT"], caregiver=caregivers["Anita Iyer"])
    returned = ensure_activity(ramesh, "Return transport from hospital", "TRANSPORT", at(tomorrow, 11, 30), at(tomorrow, 12, 15), ["TRANSPORT"], caregiver=caregivers["Anita Iyer"])
    if not db.get(ActivityDependency, {"activity_id": returned.id, "depends_on_activity_id": appointment.id}): db.add(ActivityDependency(activity_id=returned.id, depends_on_activity_id=appointment.id))
    if not db.get(ActivityDependency, {"activity_id": appointment.id, "depends_on_activity_id": outbound.id}): db.add(ActivityDependency(activity_id=appointment.id, depends_on_activity_id=outbound.id))
    ensure_activity(ramesh, "Prescription pickup", "PRESCRIPTION", at(tomorrow, 12, 30), at(tomorrow, 13, 30), ["PRESCRIPTION_PICKUP"], "HIGH", caregivers["Anita Iyer"], deadline=at(tomorrow, 18))
    for index in range(7):
        day = tomorrow + timedelta(days=index)
        ensure_activity(ramesh, f"Morning medication assistance · day {index+1}", "MEDICATION", at(day, 7), at(day, 7, 20), ["MEDICATION_ASSIST"], caregiver=caregivers["Savitha"], is_backup=False)
        if index == 0:
            med = db.scalar(select(CareActivity).where(CareActivity.patient_id == ramesh.id, CareActivity.title == "Morning medication assistance · day 1"))
            if med and not db.scalar(select(CareAssignment.id).where(CareAssignment.activity_id == med.id, CareAssignment.caregiver_id == caregivers["Divya Menon"].id)):
                db.add(CareAssignment(activity_id=med.id, caregiver_id=caregivers["Divya Menon"].id, role="BACKUP", status="CONFIRMED", assigned_by=users["admin@secondpatient.demo"].id, confirmed_at=now(), confirmed_by=users["admin@secondpatient.demo"].id, confirmed_via="COORDINATOR"))
    ensure_activity(ramesh, "Lab visit", "LAB", at(day3, 9), at(day3, 10), ["TRANSPORT"], caregiver=caregivers["Karthik Iyer"])
    ensure_activity(ramesh, "Post-appointment assistance", "POST_APPOINTMENT", at(tomorrow, 14), at(tomorrow, 14, 30), ["DAILY_ASSIST"], caregiver=caregivers["Savitha"])
    ensure_activity(ramesh, "Medical supplies pickup", "SUPPLIES", at(day4, 15), at(day4, 16), ["SUPPLIES"], importance="LOW", caregiver=None)
    ensure_activity(sharada, "Daily assistance and meal preparation", "DAILY_ROUTINE", at(tomorrow, 8), at(tomorrow, 9), ["DAILY_ASSIST"], caregiver=caregivers["Savitha"])
    ensure_activity(sharada, "Meal preparation", "DAILY_ROUTINE", at(tomorrow, 9), at(tomorrow, 10), ["DAILY_ASSIST"], caregiver=caregivers["Savitha"])
    ensure_activity(sharada, "Doctor visit", "APPOINTMENT", at(day3, 11), at(day3, 12), ["APPOINTMENT_ESCORT"], caregiver=caregivers["Meera Pai"])
    ensure_activity(ramesh, "Weekly nurse visit", "FOLLOW_UP", at(day3, 13), at(day3, 14), ["CLINICAL_VISIT"], caregiver=caregivers["Divya Menon"])


