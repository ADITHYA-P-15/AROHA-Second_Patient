"""Fictional caretaker directory: 12 agencies across the four sectors and 60 caretakers, plus listings for the 12 population caretakers.

Everyone here is synthetic and labelled so (is_synthetic, the `@directory.carecircle.demo` domain, "(fictional)" phone numbers
and districts). Deterministic and idempotent: built once per DIRECTORY_VERSION; the population caretakers are attached whenever
they exist, because the population is built in the background after start-up.
"""
from __future__ import annotations

import random

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.models import Agency, AppSetting, Caregiver, CaregiverWeeklySchedule, CaretakerProfile, Role, Sector, User
from app.services import directory

DIRECTORY_KEY = "demo_directory"
DIRECTORY_VERSION = 1
DOMAIN = "@directory.carecircle.demo"
POPULATION_DOMAIN = "@carecircle.demo"

# name, sector, state, city
AGENCIES = [
    ("Yamuna Home Care", "NORTH", "Delhi", "New Delhi"), ("Pink City Caregivers", "NORTH", "Rajasthan", "Jaipur"), ("Awadh Care Partners", "NORTH", "Uttar Pradesh", "Lucknow"),
    ("Deccan Care Circle", "SOUTH", "Karnataka", "Bengaluru"), ("Nilgiri Home Helpers", "SOUTH", "Tamil Nadu", "Chennai"), ("Coastal Care Collective", "SOUTH", "Kerala", "Kochi"),
    ("Hooghly Home Care", "EAST", "West Bengal", "Kolkata"), ("Kalinga Care Partners", "EAST", "Odisha", "Bhubaneswar"), ("Brahmaputra Caregivers", "EAST", "Assam", "Guwahati"),
    ("Sahyadri Caregivers", "WEST", "Maharashtra", "Pune"), ("Sabarmati Home Care", "WEST", "Gujarat", "Ahmedabad"), ("Konkan Care Network", "WEST", "Goa", "Panaji"),
]
# Places caretakers live in, per sector: (state, city, [districts])
PLACES = {
    "NORTH": [("Delhi", "New Delhi", ["Dwarka", "Rohini", "Saket"]), ("Rajasthan", "Jaipur", ["Malviya Nagar", "Vaishali Nagar"]),
              ("Uttar Pradesh", "Lucknow", ["Gomti Nagar", "Aliganj"]), ("Haryana", "Gurugram", ["Sector 14", "Sohna Road"]), ("Punjab", "Ludhiana", ["Model Town"])],
    "SOUTH": [("Karnataka", "Bengaluru", ["Jayanagar", "Indiranagar", "Malleshwaram"]), ("Tamil Nadu", "Chennai", ["Adyar", "Anna Nagar"]),
              ("Kerala", "Kochi", ["Kakkanad", "Edappally"]), ("Telangana", "Hyderabad", ["Kukatpally", "Begumpet"]), ("Karnataka", "Mangaluru", ["Kadri"])],
    "EAST": [("West Bengal", "Kolkata", ["Salt Lake", "Behala", "Garia"]), ("Odisha", "Bhubaneswar", ["Saheed Nagar", "Patia"]),
             ("Assam", "Guwahati", ["Dispur", "Chandmari"]), ("Bihar", "Patna", ["Kankarbagh", "Boring Road"]), ("Jharkhand", "Ranchi", ["Lalpur"])],
    "WEST": [("Maharashtra", "Pune", ["Kothrud", "Baner", "Hadapsar"]), ("Maharashtra", "Mumbai", ["Andheri", "Dadar"]),
             ("Gujarat", "Ahmedabad", ["Navrangpura", "Satellite"]), ("Goa", "Panaji", ["Altinho"]), ("Madhya Pradesh", "Indore", ["Vijay Nagar"])],
}
ORIGINS = [("Kerala", "Thrissur"), ("Tamil Nadu", "Madurai"), ("Karnataka", "Mysuru"), ("Andhra Pradesh", "Vijayawada"), ("Telangana", "Warangal"),
           ("Odisha", "Cuttack"), ("West Bengal", "Siliguri"), ("Bihar", "Gaya"), ("Jharkhand", "Dhanbad"), ("Assam", "Jorhat"), ("Manipur", "Imphal"),
           ("Uttar Pradesh", "Varanasi"), ("Rajasthan", "Udaipur"), ("Punjab", "Amritsar"), ("Himachal Pradesh", "Shimla"), ("Uttarakhand", "Dehradun"),
           ("Maharashtra", "Nagpur"), ("Gujarat", "Surat"), ("Goa", "Margao"), ("Madhya Pradesh", "Bhopal")]
LANGUAGES = {"NORTH": ["Hindi", "Punjabi", "Urdu"], "SOUTH": ["Kannada", "Tamil", "Malayalam", "Telugu"], "EAST": ["Bengali", "Odia", "Assamese"],
             "WEST": ["Marathi", "Gujarati", "Konkani"]}
ORIGIN_LANGUAGE = {"Kerala": "Malayalam", "Tamil Nadu": "Tamil", "Karnataka": "Kannada", "Andhra Pradesh": "Telugu", "Telangana": "Telugu", "Odisha": "Odia",
                   "West Bengal": "Bengali", "Bihar": "Hindi", "Jharkhand": "Hindi", "Assam": "Assamese", "Manipur": "Manipuri", "Uttar Pradesh": "Hindi",
                   "Rajasthan": "Hindi", "Punjab": "Punjabi", "Himachal Pradesh": "Hindi", "Uttarakhand": "Hindi", "Maharashtra": "Marathi", "Gujarat": "Gujarati",
                   "Goa": "Konkani", "Madhya Pradesh": "Hindi"}
FIRST = {"FEMALE": ["Asha", "Bindu", "Chitra", "Deepika", "Gauri", "Hema", "Jyoti", "Kiran", "Leena", "Mala", "Nandini", "Pallavi", "Rashmi", "Shobha", "Tara",
                    "Uma", "Vani", "Yamini", "Ishita", "Mehul", "Ritu", "Sarita", "Anupama", "Babita", "Kusum", "Roshni", "Preeti", "Swati", "Lata", "Meghna"],
         "MALE": ["Ajay", "Bharat", "Chandan", "Dinesh", "Ganesh", "Hemant", "Irfan", "Jatin", "Kishore", "Manish", "Naresh", "Pranav", "Rakesh", "Sunil",
                  "Tarun", "Vinod", "Yogesh", "Arif", "Mohit", "Sachin"],
         "NON_BINARY": ["Ari", "Noor", "Sam"], "UNDISCLOSED": ["Kavi", "Neel", "Ravi"]}
LAST = ["Acharya", "Bhat", "Chauhan", "Dutta", "Ghosh", "Iyer", "Joshi", "Kamble", "Mahapatra", "Nair", "Pandey", "Qureshi", "Rathore", "Saikia", "Shetty",
        "Thakur", "Verma", "Wagh", "Yadav", "Bora", "Desai", "Gill", "Pillai", "Sen", "Rao"]
CAPABILITIES = ["MEDICATION_ASSIST", "APPOINTMENT_ESCORT", "TRANSPORT", "DAILY_ASSIST", "MOBILITY_ASSIST", "PRESCRIPTION_PICKUP", "LAB_ESCORT", "SUPPLIES"]
# (label, weekdays, start_min, end_min)
SHIFTS = [("every day 08:00-20:00", range(7), 480, 1200), ("weekdays 09:00-18:00", range(5), 540, 1080), ("weekends", (5, 6), 0, 1440),
          ("mornings 06:00-12:00", range(7), 360, 720), ("evenings 17:00-21:00", range(7), 1020, 1260)]
GENDER_CYCLE = ["FEMALE", "MALE", "FEMALE", "FEMALE", "MALE", "FEMALE", "MALE", "FEMALE", "FEMALE", "MALE", "FEMALE", "MALE", "NON_BINARY", "FEMALE", "UNDISCLOSED"]
UNLISTED = {14, 44}  # two caretakers who chose not to be listed, so the privacy rule has something to hide
POPULATION_AGENCIES = ["Deccan Care Circle", "Nilgiri Home Helpers", "Coastal Care Collective"]
POPULATION_ORIGINS = [("Karnataka", "Hubballi"), ("Andhra Pradesh", "Guntur"), ("Kerala", "Kozhikode"), ("Kerala", "Kottayam"), ("Kerala", "Kollam"),
                      ("Uttar Pradesh", "Kanpur"), ("Maharashtra", "Kolhapur"), ("Karnataka", "Tumakuru"), ("Kerala", "Palakkad"), ("Karnataka", "Udupi"),
                      ("Goa", "Vasco da Gama"), ("Gujarat", "Vadodara")]
POPULATION_GENDERS = ["FEMALE", "MALE", "FEMALE", "MALE", "FEMALE", "MALE", "FEMALE", "MALE", "FEMALE", "FEMALE", "MALE", "MALE"]


def _slug(name: str) -> str:
    return ".".join(part for part in "".join(ch if ch.isalnum() else " " for ch in name.lower()).split())


def _agencies(db: Session) -> dict[str, Agency]:
    sectors = {s.code: s for s in db.scalars(select(Sector))}
    existing = {(a.name, a.city): a for a in db.scalars(select(Agency))}
    out = {}
    for name, sector, _state, city in AGENCIES:
        agency = existing.get((name, city))
        if agency is None:
            agency = Agency(name=name, sector_id=sectors[sector].id, city=city, is_synthetic=True, is_active=True); db.add(agency)
        out[name] = agency
    db.flush()
    return out


def _caretakers(db: Session, agencies: dict[str, Agency]) -> int:
    rng = random.Random(20261016)
    password_hash = hash_password(settings.demo_password)
    states = directory.known_states(db)
    by_sector: dict[str, list[Agency]] = {}
    for name, sector, *_ in AGENCIES: by_sector.setdefault(sector, []).append(agencies[name])
    emails = set(db.scalars(select(User.email).where(User.email.like(f"%{DOMAIN}"))))
    used_names: set[str] = set()
    created = 0
    for i in range(60):
        sector = ("NORTH", "SOUTH", "EAST", "WEST")[i % 4]
        gender = GENDER_CYCLE[i % len(GENDER_CYCLE)]
        name = ""
        while not name or name in used_names:
            name = f"{rng.choice(FIRST[gender])} {rng.choice(LAST)}"
        used_names.add(name)
        email = f"{_slug(name)}{DOMAIN}"
        if email in emails: continue
        emails.add(email)
        state, city, districts = rng.choice(PLACES[sector])
        origin_state, origin_city = rng.choice(ORIGINS) if rng.random() < 0.6 else (state, city)
        languages = ["English"] if rng.random() < 0.7 else []
        languages += rng.sample(LANGUAGES[sector], k=min(len(LANGUAGES[sector]), rng.choice((1, 1, 2))))
        if ORIGIN_LANGUAGE.get(origin_state) and ORIGIN_LANGUAGE[origin_state] not in languages: languages.append(ORIGIN_LANGUAGE[origin_state])
        if "Hindi" not in languages and rng.random() < 0.5: languages.append("Hindi")
        capabilities = sorted(set(["MEDICATION_ASSIST"] if rng.random() < 0.8 else []) | set(rng.sample(CAPABILITIES, k=rng.randint(1, 4))))
        label, days, start, end = SHIFTS[i % len(SHIFTS)]
        experience = rng.randint(0, 22)
        agency = rng.choice(by_sector[sector]) if rng.random() < 0.85 else None
        user = User(email=email, name=name, role=Role.CARETAKER, is_synthetic=True, password_hash=password_hash)
        db.add(user); db.flush()
        cg = Caregiver(user_id=user.id, name=name, kind="CARETAKER", phone=f"+91 00000 1{i:04d} (fictional)", capabilities=capabilities,
                       max_activities_per_day=rng.choice((4, 5, 6)), max_hours_per_week=float(rng.choice((25, 36, 40, 42))),
                       notes="Fictional directory caretaker; demo data only.", created_by=user.id, is_synthetic=True)
        db.add(cg); db.flush()
        db.add_all([CaregiverWeeklySchedule(caregiver_id=cg.id, weekday=d, start_min=start, end_min=end) for d in days])
        db.add(CaretakerProfile(caregiver_id=cg.id, agency_id=agency.id if agency else None, gender=gender, origin_state=origin_state, origin_city=origin_city,
                                current_state=state, current_city=city, current_district=f"{rng.choice(districts)} (fictional)", sector_id=states[state],
                                languages=languages, years_experience=experience, listed=i not in UNLISTED, is_synthetic=True,
                                bio=f"Fictional caretaker based in {city}. {experience} years of home-care experience; usually available {label}."))
        created += 1
    db.flush()
    return created


def attach_population(db: Session) -> int:
    """List the 12 population caretakers under the southern agencies. Does nothing until the population exists, or once done."""
    from app.services.population import CARETAKERS
    agencies = {a.name: a for a in db.scalars(select(Agency).where(Agency.name.in_(POPULATION_AGENCIES)))}
    if len(agencies) < len(POPULATION_AGENCIES): return 0
    states = directory.known_states(db)
    attached = 0
    for i, (name, *_rest) in enumerate(CARETAKERS):
        cg = db.scalar(select(Caregiver).join(User, User.id == Caregiver.user_id)
                       .where(User.name == name, User.role == Role.CARETAKER, User.is_synthetic.is_(True), User.email.like(f"%{POPULATION_DOMAIN}"), ~User.email.like(f"%{DOMAIN}")))
        if cg is None or db.scalar(select(CaretakerProfile.id).where(CaretakerProfile.caregiver_id == cg.id)): continue
        origin_state, origin_city = POPULATION_ORIGINS[i % len(POPULATION_ORIGINS)]
        experience = 3 + (i * 5) % 15
        db.add(CaretakerProfile(caregiver_id=cg.id, agency_id=agencies[POPULATION_AGENCIES[i % len(POPULATION_AGENCIES)]].id, gender=POPULATION_GENDERS[i],
                                origin_state=origin_state, origin_city=origin_city, current_state="Karnataka", current_city="Bengaluru",
                                current_district=f"{['Jayanagar', 'Indiranagar', 'Malleshwaram', 'Koramangala'][i % 4]} (fictional)", sector_id=states["Karnataka"],
                                languages=["English", "Kannada", "Hindi"] if i % 2 else ["Kannada", "Tamil", "English"], years_experience=experience, listed=True,
                                is_synthetic=True, bio=f"Fictional caretaker in Bengaluru with {experience} years of experience."))
        attached += 1
    db.flush()
    return attached


def ensure(db: Session) -> dict:
    """Reference data always; demo agencies and caretakers once per version; population listings whenever possible."""
    directory.ensure_reference(db)
    counts = {"caretakers": 0, "population_attached": 0}
    setting = db.get(AppSetting, DIRECTORY_KEY)
    if setting is None or (setting.value or {}).get("version") != DIRECTORY_VERSION:
        agencies = _agencies(db)
        counts["caretakers"] = _caretakers(db, agencies)
        value = {"version": DIRECTORY_VERSION, "agencies": len(agencies), "caretakers": counts["caretakers"]}
        if setting is None: db.add(AppSetting(key=DIRECTORY_KEY, value=value))
        else: setting.value = value
        db.flush()
    counts["population_attached"] = attach_population(db)
    return counts
