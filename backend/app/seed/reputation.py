"""Fictional ratings so the demo shows varied reputations: agency ratings for every agency caretaker, and reviews and doctor
ratings written by the fictional population's families and professionals.

Deterministic and idempotent. Agency ratings are added for any agency caretaker without one. The reviews need the
population (built in the background after start-up), so they are written once, the first time the population exists.
"""
from __future__ import annotations

import random
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import now
from app.models import (AgencyRating, AppSetting, CareTeamMember, Caregiver, CaregiverPatientLink, CaretakerProfile, DoctorRating, Review, Role, TeamRole, User)

REPUTATION_KEY = "demo_reputation"
REPUTATION_VERSION = 1
POPULATION_DOMAIN = "@carecircle.demo"
AGENCY_STARS = [2.5, 3.0, 3.4, 3.8, 4.0, 4.2, 4.4, 4.6, 4.8, 5.0]
GOOD = ["Always on time with the medicines and kind with my mother.", "Calm, careful and keeps us informed.", "Very reliable; we never had to chase.",
        "Handled the hospital visit smoothly and explained everything.", "Patient and respectful. Highly recommended."]
MIDDLE = ["Good care overall, but sometimes late in the evening.", "Kind, though we had to remind them about appointments.", "Fine for daily help; less confident with transport."]
POOR = ["Missed two evening doses in one week.", "Often late and hard to reach.", "Not a good fit for us; communication was difficult."]
DOCTOR = ["Follows the medication plan carefully.", "Good escort for appointments; notes are clear.", "Reliable with timings.", "Needs to report changes sooner.", ""]


def _stars(rng: random.Random, base: float) -> int:
    return max(1, min(5, round(rng.gauss(base, 0.7))))


def _text(rng: random.Random, stars: int) -> str:
    pool = GOOD if stars >= 4 else MIDDLE if stars == 3 else POOR
    return rng.choice(pool) + " (fictional review)"


def agency_ratings(db: Session) -> int:
    rng = random.Random(20261017)
    have = set(db.scalars(select(AgencyRating.caregiver_id)))
    added = 0
    for profile in db.scalars(select(CaretakerProfile).where(CaretakerProfile.agency_id.is_not(None)).order_by(CaretakerProfile.caregiver_id)):
        stars = rng.choice(AGENCY_STARS)  # drawn for every profile so the sequence is stable whichever rows already exist
        if profile.caregiver_id in have: continue
        db.add(AgencyRating(caregiver_id=profile.caregiver_id, agency_id=profile.agency_id, rating=stars, is_synthetic=True)); added += 1
    db.flush()
    return added


def _population(db: Session):
    """(family contacts with their patients, patient logins with their patient, professionals), all from the fictional population."""
    families, patients, pros = [], [], []
    rows = db.execute(select(User, CareTeamMember.patient_id, CareTeamMember.team_role).join(CareTeamMember, CareTeamMember.user_id == User.id)
                      .where(User.email.like(f"%{POPULATION_DOMAIN}"), User.is_synthetic.is_(True)).order_by(User.email)).all()
    for user, pid, role in rows:
        if role == TeamRole.PRIMARY_CONTACT: families.append((user, pid))
        elif role == TeamRole.PATIENT_SELF: patients.append((user, pid))
        elif role == TeamRole.PROFESSIONAL and (user, pid) not in pros: pros.append((user, pid))
    return families, patients, pros


def reviews(db: Session) -> int:
    families, patient_logins, pros = _population(db)
    if not families: return 0
    rng = random.Random(20261018)
    at = now()
    written = 0
    # Directory caretakers: a spread from no history at all to well-reviewed, plus a few weak records.
    directory = db.scalars(select(Caregiver).join(User, User.id == Caregiver.user_id).where(User.email.like("%@directory.carecircle.demo")).order_by(User.email)).all()
    for i, cg in enumerate(directory):
        base = rng.choice([2.3, 3.0, 3.6, 4.0, 4.3, 4.6, 4.8])
        n_reviews = rng.choice([0, 0, 1, 2, 3, 4, 6, 9])
        for j, (author, pid) in enumerate(rng.sample(families, k=min(n_reviews, len(families)))):
            stars = _stars(rng, base)
            when = at - timedelta(days=rng.randint(100, 330))  # older than the rating window, so demo accounts can still review today
            db.add(Review(caregiver_id=cg.id, author_user_id=author.id, author_role="PRIMARY_CONTACT", patient_id=pid, rating=stars, text=_text(rng, stars),
                          is_synthetic=True, created_at=when, updated_at=when, hidden=(i == 7 and j == 0)))  # one moderated (hidden) review
            written += 1
        if n_reviews >= 3 and patient_logins:
            author, pid = rng.choice(patient_logins)
            stars = _stars(rng, base)
            when = at - timedelta(days=rng.randint(100, 300))
            db.add(Review(caregiver_id=cg.id, author_user_id=author.id, author_role="PATIENT", patient_id=pid, rating=stars, text="", is_synthetic=True, created_at=when, updated_at=when))
            written += 1
        for author, pid in rng.sample(pros, k=min(rng.choice([0, 0, 1, 2, 3]), len(pros))):
            when = at - timedelta(days=rng.randint(100, 300))
            db.add(DoctorRating(caregiver_id=cg.id, author_user_id=author.id, patient_id=pid, rating=_stars(rng, base + 0.2), note=rng.choice(DOCTOR),
                                is_synthetic=True, created_at=when, updated_at=when))
            written += 1
    # Population caretakers: about half of the families reviewed their main caretaker recently; the rest will get a "Rate" prompt.
    for k, (author, pid) in enumerate(families):
        if k % 2: continue
        main = db.scalar(select(Caregiver).join(CaregiverPatientLink, CaregiverPatientLink.caregiver_id == Caregiver.id)
                         .where(CaregiverPatientLink.patient_id == pid, CaregiverPatientLink.is_main_caretaker.is_(True), Caregiver.kind == "CARETAKER"))
        if main is None: continue
        stars = _stars(rng, 4.1)
        when = at - timedelta(days=rng.randint(10, 60))
        db.add(Review(caregiver_id=main.id, author_user_id=author.id, author_role="PRIMARY_CONTACT", patient_id=pid, rating=stars, text=_text(rng, stars),
                      is_synthetic=True, created_at=when, updated_at=when))
        written += 1
    for author, pid in pros[::3]:
        main = db.scalar(select(Caregiver).join(CaregiverPatientLink, CaregiverPatientLink.caregiver_id == Caregiver.id)
                         .where(CaregiverPatientLink.patient_id == pid, CaregiverPatientLink.is_main_caretaker.is_(True), Caregiver.kind == "CARETAKER"))
        if main is None or db.scalar(select(DoctorRating.id).where(DoctorRating.author_user_id == author.id, DoctorRating.caregiver_id == main.id)): continue
        when = at - timedelta(days=rng.randint(10, 80))
        db.add(DoctorRating(caregiver_id=main.id, author_user_id=author.id, patient_id=pid, rating=_stars(rng, 4.0), note=rng.choice(DOCTOR), is_synthetic=True, created_at=when, updated_at=when))
        written += 1
    db.flush()
    return written


def ensure(db: Session) -> dict:
    counts = {"agency_ratings": agency_ratings(db), "reviews": 0}
    setting = db.get(AppSetting, REPUTATION_KEY)
    if setting is None or (setting.value or {}).get("version") != REPUTATION_VERSION:
        written = reviews(db)
        if written:  # only mark done once the population existed and the reviews were written
            counts["reviews"] = written
            value = {"version": REPUTATION_VERSION, "reviews": written}
            if setting is None: db.add(AppSetting(key=REPUTATION_KEY, value=value))
            else: setting.value = value
            db.flush()
    return counts if (counts["agency_ratings"] or counts["reviews"]) else {}
