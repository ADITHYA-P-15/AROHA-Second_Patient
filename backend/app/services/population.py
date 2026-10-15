"""A practical-size fictional population around the core demo story: 24 more patients with families, caretakers and
hospital staff, and 30 days of dose and appointment history so a professional's analytics have something to show.

Additive and deterministic: it never touches the core demo patients (Ramesh, Sharada) or their accounts, uses the
`@carecircle.demo` domain so Reset demo data leaves it alone, and builds once per POPULATION_VERSION.
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import now, to_utc
from app.core.config import settings
from app.core.security import hash_password
from app.models import (ActivityHistory, AppSetting, CareActivity, CareAssignment, Caregiver, CaregiverPatientLink, CaregiverWeeklySchedule,
                        CareTeamMember, Incident, Patient, Prescription, Role, TeamRole, User)
from app.services.care_feeds import DOSE_GRACE, DOSE_MINUTES, create_appointment, generate_doses
from app.services.care_team import CODE_ALPHABET, ensure_care_profile

POPULATION_KEY = "demo_population"
POPULATION_VERSION = 1
DOMAIN = "@carecircle.demo"
CORE_DOCTORS = ("dr.arjun.nair@secondpatient.demo", "divya.menon@secondpatient.demo")

# name, role label shown in the app is "Healthcare professional" for both doctors and nurses
PROFESSIONALS = ["Dr. Kavita Rao", "Dr. Imran Shaikh", "Nurse Priya Nair", "Dr. Sandeep Joshi", "Nurse Fatima Khan"]
# name, capabilities, daily task limit, weekly hours, (start_min, end_min, weekdays)
CARETAKERS = [
    ("Anjali Verma", ["MEDICATION_ASSIST", "DAILY_ASSIST", "APPOINTMENT_ESCORT"], 6, 42, (420, 1350, range(7))),
    ("Bhaskar Reddy", ["MEDICATION_ASSIST", "APPOINTMENT_ESCORT", "TRANSPORT", "MOBILITY_ASSIST"], 6, 42, (420, 1350, range(7))),
    ("Charulatha S", ["MEDICATION_ASSIST", "DAILY_ASSIST", "MOBILITY_ASSIST"], 6, 40, (420, 1350, range(7))),
    ("Deepak Menon", ["MEDICATION_ASSIST", "APPOINTMENT_ESCORT", "TRANSPORT"], 5, 38, (420, 1350, range(7))),
    ("Esther Thomas", ["MEDICATION_ASSIST", "DAILY_ASSIST", "APPOINTMENT_ESCORT"], 6, 42, (420, 1350, range(7))),
    ("Farhan Ali", ["MEDICATION_ASSIST", "TRANSPORT", "APPOINTMENT_ESCORT"], 5, 36, (420, 1350, range(7))),
    ("Geeta Kulkarni", ["MEDICATION_ASSIST", "DAILY_ASSIST", "MOBILITY_ASSIST", "APPOINTMENT_ESCORT"], 6, 42, (420, 1350, range(7))),
    ("Harish Gowda", ["MEDICATION_ASSIST", "DAILY_ASSIST"], 5, 36, (420, 1350, range(7))),
    ("Indira Pillai", ["MEDICATION_ASSIST", "APPOINTMENT_ESCORT", "DAILY_ASSIST"], 6, 40, (420, 1350, range(7))),
    ("Kavya Hegde", ["MEDICATION_ASSIST", "DAILY_ASSIST", "APPOINTMENT_ESCORT", "TRANSPORT"], 6, 42, (420, 1350, range(7))),
    ("Lokesh Naik", ["MEDICATION_ASSIST", "APPOINTMENT_ESCORT", "MOBILITY_ASSIST"], 5, 38, (420, 1350, range(7))),
    # Part-time (weekdays 08:00-15:00) and only ever a backup, so cover is asked rather than doses left unassigned.
    ("Jayesh Patel", ["MEDICATION_ASSIST", "APPOINTMENT_ESCORT"], 4, 25, (480, 900, range(5))),
]
MAIN_CARETAKERS = len(CARETAKERS) - 1
# patient, birth year, primary contact, relationship
FAMILIES = [
    ("Lalitha Krishnan", 1944, "Vikram Krishnan", "son"), ("Mohan Das", 1939, "Sunita Das", "daughter"),
    ("Kamala Subramanian", 1947, "Arvind Subramanian", "son"), ("Gopal Nambiar", 1941, "Rekha Nambiar", "daughter"),
    ("Fatima Begum", 1950, "Zoya Khan", "daughter"), ("Ramakrishna Hegde", 1936, "Pooja Hegde", "granddaughter"),
    ("Sarojini Devi", 1945, "Naveen Kumar", "son"), ("Abdul Rahim", 1943, "Salma Rahim", "daughter"),
    ("Janaki Raman", 1949, "Meenakshi Raman", "daughter"), ("Thomas Mathew", 1940, "Susan Mathew", "daughter"),
    ("Parvathi Amma", 1938, "Rajesh Nair", "son"), ("Harbans Singh", 1946, "Gurpreet Singh", "son"),
    ("Leela Shenoy", 1942, "Anand Shenoy", "son"), ("Narasimha Rao", 1948, "Lavanya Rao", "daughter"),
    ("Usha Rani", 1951, "Prakash Babu", "son"), ("Yusuf Sheikh", 1944, "Nadia Sheikh", "daughter"),
    ("Padma Iyengar", 1937, "Srinivas Iyengar", "son"), ("Joseph D'Souza", 1947, "Clara D'Souza", "daughter"),
    ("Bharathi Kulkarni", 1952, "Sameer Kulkarni", "son"), ("Venkatesh Gowda", 1940, "Divakar Gowda", "son"),
    ("Shanti Bai", 1946, "Kiran Patil", "son"), ("Hari Prasad", 1949, "Neha Prasad", "daughter"),
    ("Revathi Menon", 1943, "Arjun Menon", "son"), ("Dilip Chatterjee", 1945, "Ananya Chatterjee", "daughter"),
]
SECOND_CONTACTS = ["Deepa", "Manoj", "Farah", "Rohit", "Sneha"]  # a second family contact for every fifth patient
PATIENT_LOGINS = 8  # the first patients also have their own login
MEDICINES = [("Metformin", "500 mg", "After food", ["08:00", "20:00"]), ("Amlodipine", "5 mg", "Morning, with water", ["09:00"]),
             ("Atorvastatin", "10 mg", "At bedtime", ["21:00"]), ("Levothyroxine", "50 mcg", "Empty stomach", ["07:00"]),
             ("Telmisartan", "40 mg", "Morning", ["08:30"]), ("Losartan", "50 mg", "Evening", ["19:00"]),
             ("Aspirin", "75 mg", "After lunch", ["13:30"]), ("Pantoprazole", "40 mg", "Before breakfast", ["07:30"]),
             ("Glimepiride", "1 mg", "Before breakfast", ["07:30"]), ("Calcium + D3", "500 mg", "After dinner", ["20:30"]),
             ("Donepezil", "5 mg", "At night", ["21:00"]), ("Furosemide", "20 mg", "Morning", ["08:00"])]
VISITS = [("Cardiology review", "City Heart Clinic"), ("Diabetes clinic", "Metro Diabetes Centre"), ("Physiotherapy session", "Sunrise Rehab Centre"),
          ("Eye check-up", "Vision Care Clinic"), ("Blood test", "Central Pathology Lab"), ("Neurology follow-up", "Neuro OPD, Metro Hospital"),
          ("General review", "Metro Hospital OPD"), ("Dental check-up", "Smile Dental Care")]
# How well doses are taken over the last 30 days. "slipping" is fine until ten days ago; "improving" the opposite.
PROFILES = ["good", "excellent", "good", "slipping", "excellent", "good", "excellent", "poor", "good", "improving", "excellent", "good",
            "excellent", "slipping", "good", "poor", "excellent", "good", "excellent", "improving", "good", "excellent", "slipping", "good"]
NOTES = ["Lives with family; walks with support.", "Needs reminders for medicines.", "Independent in the day; help in the evening.",
         "Hearing difficulty; speak clearly.", "Uses a walker; fall risk at night.", "Diabetic diet; family prepares meals."]
MOBILITY = ["INDEPENDENT", "NEEDS_AID", "NEEDS_AID", "WHEELCHAIR", "INDEPENDENT", "NEEDS_AID"]


def _slug(name: str) -> str:
    return "".join(ch if ch.isalnum() else "." for ch in name.lower().replace("dr. ", "").replace("nurse ", "").replace("'", "")).strip(".").replace("..", ".")


def _miss_probability(profile: str, days_ago: int) -> float:
    if profile == "excellent": return 0.015
    if profile == "good": return 0.04
    if profile == "slipping": return 0.03 if days_ago > 10 else 0.4
    if profile == "improving": return 0.35 if days_ago > 14 else 0.04
    return 0.33  # poor


def _terminal_dose(db, prescription, due, caretaker, caretaker_user, status, completed_late=False, delay_min=10):
    dose = CareActivity(patient_id=prescription.patient_id, title=f"{prescription.medicine} {prescription.dose}", category="MEDICATION", description=prescription.instructions,
                        scheduled_start=to_utc(due), scheduled_end=to_utc(due + timedelta(minutes=DOSE_MINUTES)), deadline=to_utc(due + DOSE_GRACE), importance="HIGH",
                        requires_caregiver=True, required_support=["MEDICATION_ASSIST"], coverage_status="UNASSESSED", is_synthetic=True, created_by=prescription.prescribed_by,
                        source="PRESCRIPTION", source_id=prescription.id, series_id=prescription.id, lifecycle_status=status)
    if status == "MISSED":
        dose.missed_at = to_utc(due + DOSE_GRACE)
    else:
        dose.completed_at, dose.completed_by, dose.completed_late = to_utc(due + timedelta(minutes=delay_min)), caretaker_user.id, completed_late
    db.add(dose); db.flush()
    db.add(CareAssignment(activity_id=dose.id, caregiver_id=caretaker.id, role="PRIMARY", status="CONFIRMED", assigned_by=prescription.prescribed_by,
                          assigned_at=to_utc(due - timedelta(days=1)), confirmed_at=to_utc(due - timedelta(days=1)), confirmed_by=prescription.prescribed_by, confirmed_via="ROUTINE"))
    return dose


def _pending_dose(db, prescription, due, caretaker):
    dose = CareActivity(patient_id=prescription.patient_id, title=f"{prescription.medicine} {prescription.dose}", category="MEDICATION", description=prescription.instructions,
                        scheduled_start=to_utc(due), scheduled_end=to_utc(due + timedelta(minutes=DOSE_MINUTES)), deadline=to_utc(due + DOSE_GRACE), importance="HIGH",
                        requires_caregiver=True, required_support=["MEDICATION_ASSIST"], lifecycle_status="SCHEDULED", coverage_status="UNASSESSED", is_synthetic=True,
                        created_by=prescription.prescribed_by, source="PRESCRIPTION", source_id=prescription.id, series_id=prescription.id)
    db.add(dose); db.flush()
    db.add(CareAssignment(activity_id=dose.id, caregiver_id=caretaker.id, role="PRIMARY", status="CONFIRMED", assigned_by=prescription.prescribed_by,
                          assigned_at=now(), confirmed_at=now(), confirmed_by=prescription.prescribed_by, confirmed_via="ROUTINE"))


def build(db: Session) -> dict:
    """Create the population. Returns counts. Run once; `ensure` guards repeats."""
    zone = ZoneInfo(settings.app_timezone)
    at = now()
    today = at.astimezone(zone).date()
    password_hash = hash_password(settings.demo_password)  # one hash for the whole demo population keeps start-up fast
    emails: set[str] = {u for u in db.scalars(select(User.email))}

    def user(name: str, role: Role, email: str | None = None) -> User:
        base = email or f"{_slug(name)}{DOMAIN}"
        address, n = base, 2
        while address in emails:
            address = base.replace(DOMAIN, f"{n}{DOMAIN}"); n += 1
        emails.add(address)
        row = User(email=address, name=name, role=role, is_synthetic=True, password_hash=password_hash)
        db.add(row); db.flush()
        return row

    pros = [user(n, Role.PROFESSIONAL) for n in PROFESSIONALS]
    core_docs = [u for u in db.scalars(select(User).where(User.email.in_(CORE_DOCTORS)))]
    arjun = next((u for u in core_docs if u.email == CORE_DOCTORS[0]), None)
    divya = next((u for u in core_docs if u.email == CORE_DOCTORS[1]), None)
    caretaker_users = [user(name, Role.CARETAKER) for name, *_ in CARETAKERS]
    creator = pros[0]

    # Caretaker profiles are created per patient link; set their skills and hours once.
    profiles: dict[uuid.UUID, Caregiver] = {}
    rng_codes = random.Random(20261015)
    patients: list[tuple[Patient, User, list[User], list[User]]] = []
    used_codes = {c for c in db.scalars(select(Patient.care_code)) if c}
    for i, (name, year, contact_name, relation) in enumerate(FAMILIES):
        contact = user(contact_name, Role.PRIMARY_CONTACT)
        code = ""
        while not code or code in used_codes:
            code = "CC-" + "".join(rng_codes.choice(CODE_ALPHABET) for _ in range(6))
        used_codes.add(code)
        patient = Patient(name=name, birth_year=year, care_code=code, care_notes=NOTES[i % len(NOTES)], clinical_notes="Fictional demo note: routine follow-up plan.",
                          mobility_level=MOBILITY[i % len(MOBILITY)], created_by=contact.id, is_synthetic=True,
                          created_at=to_utc(datetime.combine(today - timedelta(days=45 + i), time(10, 0), zone)))
        db.add(patient); db.flush()
        members = [CareTeamMember(patient_id=patient.id, user_id=contact.id, team_role=TeamRole.PRIMARY_CONTACT, is_primary_coordinator=True)]
        if i % 5 == 0:
            second = user(f"{SECOND_CONTACTS[(i // 5) % len(SECOND_CONTACTS)]} {contact_name.split()[-1]}", Role.PRIMARY_CONTACT)
            members.append(CareTeamMember(patient_id=patient.id, user_id=second.id, team_role=TeamRole.PRIMARY_CONTACT))
        if i < PATIENT_LOGINS:
            login = user(name, Role.PATIENT, f"{_slug(name)}.patient{DOMAIN}")
            members.append(CareTeamMember(patient_id=patient.id, user_id=login.id, team_role=TeamRole.PATIENT_SELF))
        doctors = [pros[i % len(pros)]]
        if i % 3 == 0: doctors.append(pros[(i + 2) % len(pros)])
        if arjun and i % 4 == 1: doctors.append(arjun)
        if divya and i % 4 == 3: doctors.append(divya)
        members += [CareTeamMember(patient_id=patient.id, user_id=d.id, team_role=TeamRole.PROFESSIONAL) for d in doctors]
        main_index = i % MAIN_CARETAKERS
        backups = [(main_index + 3) % len(CARETAKERS)] + ([(main_index + 6) % len(CARETAKERS)] if i % 3 == 0 else [])
        carers = [caretaker_users[main_index]] + [caretaker_users[b] for b in backups]
        members += [CareTeamMember(patient_id=patient.id, user_id=u.id, team_role=TeamRole.CARETAKER) for u in carers]
        db.add_all(members); db.flush()
        for position, carer in enumerate(carers):
            index = caretaker_users.index(carer)
            profile = ensure_care_profile(db, carer, patient.id, created_by=creator.id, relationship="main caretaker" if position == 0 else "backup caretaker")
            if profile.id not in profiles:
                _, capabilities, daily, weekly, (start, end, days) = CARETAKERS[index]
                profile.capabilities, profile.max_activities_per_day, profile.max_hours_per_week = list(capabilities), daily, weekly
                db.query(CaregiverWeeklySchedule).filter(CaregiverWeeklySchedule.caregiver_id == profile.id).delete()
                db.add_all([CaregiverWeeklySchedule(caregiver_id=profile.id, weekday=d, start_min=start, end_min=end) for d in days])
                profiles[profile.id] = profile
            if position == 0:
                for link in db.scalars(select(CaregiverPatientLink).where(CaregiverPatientLink.patient_id == patient.id)):
                    link.is_main_caretaker = link.caregiver_id == profile.id
        db.flush()
        patients.append((patient, contact, doctors, carers))

    slots: dict[uuid.UUID, list[int]] = {}
    counts = {"patients": len(patients), "prescriptions": 0, "doses": 0, "appointments": 0, "requests": 0}
    for i, (patient, contact, doctors, carers) in enumerate(patients):
        rng = random.Random(7000 + i)
        profile_name = PROFILES[i % len(PROFILES)]  # explicit per patient so every professional's list has a realistic mix
        main = db.scalar(select(Caregiver).join(CaregiverPatientLink, CaregiverPatientLink.caregiver_id == Caregiver.id)
                         .where(CaregiverPatientLink.patient_id == patient.id, CaregiverPatientLink.is_main_caretaker.is_(True)))
        main_user = carers[0]
        prescriber = doctors[0]
        picks = [MEDICINES[(i * 2 + k * 5) % len(MEDICINES)] for k in range(2 + (i % 2))]
        seen: set[str] = set()
        for medicine, dose, instructions, base_times in picks:
            if medicine in seen: continue
            seen.add(medicine)
            # Give each dose a free slot in its caretaker's day (20 minutes apart), so routine doses never clash.
            used = slots.setdefault(main.id, [])
            times = []
            for hhmm in base_times:
                minutes = int(hhmm[:2]) * 60 + int(hhmm[3:])
                while any(abs(minutes - u) < 20 for u in used) and minutes < 1320: minutes += 5
                used.append(minutes)
                times.append(f"{minutes // 60:02d}:{minutes % 60:02d}")
            start_day = today - timedelta(days=30)
            rx = Prescription(patient_id=patient.id, medicine=medicine, dose=dose, instructions=instructions, times=times, start_date=start_day,
                              end_date=today + timedelta(days=60), status="ACTIVE", prescribed_by=prescriber.id,
                              created_at=to_utc(datetime.combine(start_day, time(9, 0), zone)))
            db.add(rx); db.flush()
            counts["prescriptions"] += 1
            db.add(ActivityHistory(actor_user_id=prescriber.id, patient_id=patient.id, event_type="prescription.created", entity_type="prescription", entity_id=str(rx.id),
                                   summary=f"{prescriber.name} prescribed {medicine} {dose} at {', '.join(times)}", payload={}, request_id="",
                                   occurred_at=to_utc(datetime.combine(start_day, time(9, 0), zone))))
            for offset in range(-30, 1):
                day = today + timedelta(days=offset)
                for hhmm in times:
                    due = datetime.combine(day, time.fromisoformat(hhmm), zone)
                    if due > at: continue
                    if due + DOSE_GRACE > at:
                        _pending_dose(db, rx, due, main); counts["doses"] += 1
                        continue
                    roll = rng.random()
                    if roll < _miss_probability(profile_name, -offset):
                        _terminal_dose(db, rx, due, main, main_user, "MISSED")
                    elif rng.random() < (0.18 if profile_name in ("slipping", "poor") else 0.08):
                        _terminal_dose(db, rx, due, main, main_user, "COMPLETED", completed_late=True, delay_min=rng.randint(70, 240))
                    else:
                        _terminal_dose(db, rx, due, main, main_user, "COMPLETED", delay_min=rng.randint(2, 40))
                    counts["doses"] += 1
            generate_doses(db, rx, actor_id=prescriber.id)

        # Appointments: one or two done in the past month (one missed for some), one or two coming up.
        for k in range(1 + (i % 2)):
            title, place = VISITS[(i + k * 3) % len(VISITS)]
            day = today - timedelta(days=rng.randint(3, 26))
            begin = datetime.combine(day, time(rng.randint(9, 15), rng.choice((0, 30))), zone)
            missed = profile_name == "poor" and k == 0
            visit = CareActivity(patient_id=patient.id, title=title, category="APPOINTMENT", description="Routine visit.", location_note=place,
                                 scheduled_start=to_utc(begin), scheduled_end=to_utc(begin + timedelta(minutes=45)), deadline=to_utc(begin + timedelta(minutes=105)),
                                 importance="MEDIUM", requires_caregiver=True, required_support=["APPOINTMENT_ESCORT"], buffer_before_min=30, buffer_after_min=30,
                                 lifecycle_status="MISSED" if missed else "COMPLETED", coverage_status="UNASSESSED", is_synthetic=True, created_by=prescriber.id,
                                 source="APPOINTMENT", missed_at=to_utc(begin + timedelta(minutes=105)) if missed else None,
                                 completed_at=None if missed else to_utc(begin + timedelta(minutes=60)), completed_by=None if missed else main_user.id)
            db.add(visit); db.flush()
            db.add(CareAssignment(activity_id=visit.id, caregiver_id=main.id, role="PRIMARY", status="CONFIRMED", assigned_by=prescriber.id, assigned_at=to_utc(begin - timedelta(days=2)),
                                  confirmed_at=to_utc(begin - timedelta(days=2)), confirmed_by=prescriber.id, confirmed_via="ROUTINE"))
            counts["appointments"] += 1
        for k in range(1 + ((i + 1) % 2)):
            title, place = VISITS[(i * 2 + k * 5 + 1) % len(VISITS)]
            begin = datetime.combine(today + timedelta(days=rng.randint(1, 12)), time(rng.randint(9, 16), rng.choice((0, 30))), zone)
            create_appointment(db, patient, title=title, start=begin, minutes=45, location=place, notes="Bring previous reports.", needs_escort=True,
                               importance="MEDIUM", actor_id=prescriber.id)
            counts["appointments"] += 1

        # Past help requests (all handled), so response-time figures have data. Open ones come from live use.
        if profile_name in ("slipping", "poor", "good") and i % 2 == 0:
            made = at - timedelta(days=rng.randint(2, 20), hours=rng.randint(0, 8))
            db.add(Incident(patient_id=patient.id, source="PATIENT_MESSAGE", category="MEDICATION", importance="MEDIUM", initial_level=1, current_level=1, severity="LOW",
                            status="RESOLVED", title="Medicine help request", safe_summary=f"{patient.name} asked for help with medicines",
                            dedupe_key=f"population:{uuid.uuid4()}", classification={"rule_ids": ["medication_missed_once"], "classifier_version": "population-1"},
                            owner_user_id=main_user.id, created_at=made, acknowledged_at=made + timedelta(minutes=rng.randint(3, 25)),
                            resolved_at=made + timedelta(minutes=rng.randint(30, 120)), resolution_code="HANDLED", resolution_note="Taken care of", version=3))
            counts["requests"] += 1
    return counts


def ensure(db: Session) -> dict | None:
    """Build the population once (per version). Safe to call on every start-up."""
    setting = db.get(AppSetting, POPULATION_KEY)
    if setting is not None and (setting.value or {}).get("version") == POPULATION_VERSION: return None
    if db.scalar(select(User.id).where(User.email.like(f"%{DOMAIN}"))) is not None and setting is None:
        # Accounts exist without the marker (e.g. a partial earlier run): do not duplicate people.
        db.add(AppSetting(key=POPULATION_KEY, value={"version": POPULATION_VERSION, "note": "adopted"})); db.flush()
        return None
    counts = build(db)
    if setting is None: db.add(AppSetting(key=POPULATION_KEY, value={"version": POPULATION_VERSION, **counts}))
    else: setting.value = {"version": POPULATION_VERSION, **counts}
    db.flush()
    return counts
