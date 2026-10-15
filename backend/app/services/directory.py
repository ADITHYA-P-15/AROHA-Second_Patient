"""Caretaker directory: sectors, agencies and caretaker listings a family can browse before inviting someone.

The listing (CaretakerProfile) only describes the person. Capabilities, limits and availability are read from the existing
Caregiver row and engine/availability, so the directory and the care engines can never disagree about what someone can do.
Search is deterministic: SQL narrows by the indexed columns, then JSON-list filters and availability run in Python over
that set (the directory is hundreds of people, not millions; swap in a search index here when that changes).
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.engine.availability import effective_windows
from app.models import (Agency, AvailabilityOverride, CareTeamMember, Caregiver, CaregiverPatientLink, CaregiverWeeklySchedule, CaretakerProfile,
                        Role, Sector, SectorState, User)

CONFIG = Path(__file__).resolve().parents[1] / "seed" / "sector_states.json"
GENDERS = ("FEMALE", "MALE", "NON_BINARY", "UNDISCLOSED")
GENDER_LABELS = {"FEMALE": "Female", "MALE": "Male", "NON_BINARY": "Non-binary", "UNDISCLOSED": "Prefers not to say"}
SORTS = ("name", "experience")
MAX_PAGE = 50
BROWSE_ROLES = (Role.PRIMARY_CONTACT, Role.PATIENT, Role.PROFESSIONAL)


def load_config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def ensure_reference(db: Session) -> None:
    """The four sectors and the state map. Idempotent; runs on every start so a database without migrations still has them."""
    config = load_config()
    sectors = {s.code: s for s in db.scalars(select(Sector))}
    for row in config["sectors"]:
        if row["code"] not in sectors:
            sectors[row["code"]] = Sector(code=row["code"], name=row["name"]); db.add(sectors[row["code"]])
    db.flush()
    mapped = set(db.scalars(select(SectorState.state)))
    for state, code in config["states"].items():
        if state not in mapped: db.add(SectorState(state=state, sector_id=sectors[code].id))
    db.flush()


def known_states(db: Session) -> dict[str, uuid.UUID]:
    return {row.state: row.sector_id for row in db.scalars(select(SectorState))}


def canonical_state(db: Session, value: str) -> tuple[str, uuid.UUID | None]:
    """The configured spelling of a state and its sector. Unknown states raise ValueError; empty means not given."""
    value = (value or "").strip()
    if not value: return "", None
    for state, sector_id in known_states(db).items():
        if state.lower() == value.lower(): return state, sector_id
    raise ValueError("Unknown state")


@dataclass
class Filters:
    sector: str | None = None
    agency: uuid.UUID | None = None
    state: str | None = None
    city: str | None = None
    gender: str | None = None
    language: str | None = None
    capability: str | None = None
    min_experience: int | None = None
    min_agency_rating: float | None = None   # the agency's own 1-5 rating (reputation source); unrated caretakers drop out
    available_on: date | None = None
    sort: str = "name"
    limit: int = 20
    offset: int = 0


def _listed_rows(db: Session, f: Filters):
    stmt = (select(CaretakerProfile, Caregiver, User).join(Caregiver, Caregiver.id == CaretakerProfile.caregiver_id).join(User, User.id == Caregiver.user_id)
            .where(CaretakerProfile.listed.is_(True), Caregiver.is_active.is_(True), Caregiver.kind == "CARETAKER", User.is_active.is_(True), User.role == Role.CARETAKER))
    if f.sector:
        stmt = stmt.join(Sector, Sector.id == CaretakerProfile.sector_id).where(Sector.code == f.sector.upper())
    if f.agency: stmt = stmt.where(CaretakerProfile.agency_id == f.agency)
    if f.state: stmt = stmt.where(func.lower(CaretakerProfile.current_state) == f.state.strip().lower())
    if f.city: stmt = stmt.where(func.lower(CaretakerProfile.current_city) == f.city.strip().lower())
    if f.gender: stmt = stmt.where(CaretakerProfile.gender == f.gender)
    if f.min_experience is not None: stmt = stmt.where(CaretakerProfile.years_experience >= f.min_experience)
    if f.min_agency_rating is not None:
        from app.models import AgencyRating
        stmt = stmt.where(Caregiver.id.in_(select(AgencyRating.caregiver_id).where(AgencyRating.rating >= f.min_agency_rating)))
    return db.execute(stmt).all()


def available_on_day(caregiver_id_rows: dict, overrides: dict, cid: uuid.UUID, day: date) -> bool:
    zone = ZoneInfo(settings.app_timezone)
    start = datetime.combine(day, time.min, zone)
    windows = effective_windows({"schedule": caregiver_id_rows.get(cid, []), "overrides": overrides.get(cid, [])}, start, start + timedelta(days=1), settings.app_timezone)
    return bool(windows)


def search(db: Session, f: Filters) -> tuple[list[tuple], int]:
    rows = _listed_rows(db, f)
    if f.language:
        wanted = f.language.strip().lower()
        rows = [r for r in rows if wanted in {str(x).lower() for x in (r[0].languages or [])}]
    if f.capability:
        rows = [r for r in rows if f.capability in (r[1].capabilities or [])]
    if f.available_on and rows:
        ids = [r[1].id for r in rows]
        schedules: dict = {}
        for s in db.scalars(select(CaregiverWeeklySchedule).where(CaregiverWeeklySchedule.caregiver_id.in_(ids))): schedules.setdefault(s.caregiver_id, []).append(s)
        overrides: dict = {}
        for o in db.scalars(select(AvailabilityOverride).where(AvailabilityOverride.caregiver_id.in_(ids), AvailabilityOverride.cancelled_at.is_(None))): overrides.setdefault(o.caregiver_id, []).append(o)
        rows = [r for r in rows if available_on_day(schedules, overrides, r[1].id, f.available_on)]
    if f.sort == "experience": rows.sort(key=lambda r: (-r[0].years_experience, r[1].name.lower(), str(r[1].id)))
    else: rows.sort(key=lambda r: (r[1].name.lower(), str(r[1].id)))
    return rows[f.offset:f.offset + f.limit], len(rows)


def on_viewer_team(db: Session, viewer: User, caregiver: Caregiver) -> bool:
    """True when a care team the viewer belongs to already includes this caretaker (as a member or a linked care profile)."""
    mine = select(CareTeamMember.patient_id).where(CareTeamMember.user_id == viewer.id)
    if caregiver.user_id and db.scalar(select(CareTeamMember.id).where(CareTeamMember.user_id == caregiver.user_id, CareTeamMember.patient_id.in_(mine)).limit(1)):
        return True
    return db.scalar(select(CaregiverPatientLink.id).where(CaregiverPatientLink.caregiver_id == caregiver.id, CaregiverPatientLink.patient_id.in_(mine)).limit(1)) is not None


def lookups(db: Session) -> tuple[dict, dict]:
    return {s.id: s for s in db.scalars(select(Sector))}, {a.id: a for a in db.scalars(select(Agency))}


def card(profile: CaretakerProfile, caregiver: Caregiver, sectors: dict, agencies: dict) -> dict:
    """The public listing. Never contains phone, notes or anything finer than the city."""
    agency = agencies.get(profile.agency_id) if profile.agency_id else None
    sector = sectors.get(profile.sector_id) if profile.sector_id else None
    return {"id": str(caregiver.id), "name": caregiver.name, "gender": profile.gender, "gender_label": GENDER_LABELS.get(profile.gender, profile.gender),
            "origin_state": profile.origin_state, "origin_city": profile.origin_city, "current_state": profile.current_state, "current_city": profile.current_city,
            "sector": sector.code if sector else None, "agency": {"id": str(agency.id), "name": agency.name} if agency else None,
            "languages": list(profile.languages or []), "capabilities": list(caregiver.capabilities or []), "years_experience": profile.years_experience,
            "is_synthetic": bool(profile.is_synthetic)}


def detail(profile: CaretakerProfile, caregiver: Caregiver, sectors: dict, agencies: dict, *, on_team: bool) -> dict:
    out = {**card(profile, caregiver, sectors, agencies), "bio": profile.bio, "max_activities_per_day": caregiver.max_activities_per_day,
           "max_hours_per_week": caregiver.max_hours_per_week, "on_my_team": on_team}
    # Contact details and the exact area are for care teams that already include this caretaker.
    out["private"] = {"phone": caregiver.phone, "notes": caregiver.notes, "current_district": profile.current_district} if on_team else None
    return out


def own_caregiver(db: Session, user: User) -> Caregiver:
    """A caretaker's care profile, created (without any patient link) if they have none yet. Same defaults as an invitation."""
    from app.services.care_team import DEFAULT_CAPABILITIES, DEFAULT_DAY
    cg = db.scalar(select(Caregiver).where(Caregiver.user_id == user.id))
    if cg is None:
        cg = Caregiver(user_id=user.id, name=user.name, kind="CARETAKER", capabilities=list(DEFAULT_CAPABILITIES), max_activities_per_day=6, max_hours_per_week=40,
                       created_by=user.id, is_synthetic=user.is_synthetic)
        db.add(cg); db.flush()
        db.add_all([CaregiverWeeklySchedule(caregiver_id=cg.id, weekday=d, start_min=DEFAULT_DAY[0], end_min=DEFAULT_DAY[1]) for d in range(7)])
    return cg


def own_view(db: Session, user: User) -> dict:
    cg = db.scalar(select(Caregiver).where(Caregiver.user_id == user.id))
    profile = db.scalar(select(CaretakerProfile).where(CaretakerProfile.caregiver_id == cg.id)) if cg else None
    sectors, agencies = lookups(db)
    if profile is None:
        # Not listed until the caretaker saves their profile and chooses to be listed.
        return {"exists": False, "id": str(cg.id) if cg else None, "name": user.name, "gender": "UNDISCLOSED", "origin_state": "", "origin_city": "", "current_state": "",
                "current_city": "", "current_district": "", "sector": None, "agency": None, "languages": [], "capabilities": list(cg.capabilities or []) if cg else [],
                "years_experience": 0, "bio": "", "listed": False}
    return {**card(profile, cg, sectors, agencies), "exists": True, "bio": profile.bio, "current_district": profile.current_district, "listed": profile.listed}
