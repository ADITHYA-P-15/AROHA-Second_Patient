"""Caretaker directory (flag `directory`): browse caretakers by sector and agency, see a profile, edit your own listing.

Families, patients and professionals browse. Caretakers see and edit only their own listing. Adding someone from the
directory to a care team is a later phase; invite-by-email is unchanged.
"""
from __future__ import annotations

import re
import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.features import feature_required
from app.core.permissions import require_role
from app.models import ActivityHistory, Agency, Caregiver, CaretakerProfile, Role, Sector, SectorState
from app.services import directory as svc

router = APIRouter(prefix="/api/v1/directory", tags=["directory"], dependencies=[Depends(feature_required("directory"))])
SUPPORT = {"TRANSPORT", "MEDICATION_ASSIST", "PRESCRIPTION_PICKUP", "DAILY_ASSIST", "MOBILITY_ASSIST", "LAB_ESCORT", "SUPPLIES", "APPOINTMENT_ESCORT"}
PLACE = re.compile(r"^[\w .,'()-]*$", re.UNICODE)
LANGUAGE = re.compile(r"^[^\W\d_]+(?:[ -][^\W\d_]+)*$", re.UNICODE)


def _current_user(request: Request, db: Session = Depends(get_db)):
    from app.main import current_user
    return current_user(request, db)


def _browser(user=Depends(_current_user)):
    return require_role(user, *svc.BROWSE_ROLES)


def _caretaker(user=Depends(_current_user)):
    return require_role(user, Role.CARETAKER)


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=160)
    gender: Literal["FEMALE", "MALE", "NON_BINARY", "UNDISCLOSED"] | None = None
    origin_state: str | None = Field(default=None, max_length=60)
    origin_city: str | None = Field(default=None, max_length=80)
    current_state: str | None = Field(default=None, max_length=60)
    current_city: str | None = Field(default=None, max_length=80)
    current_district: str | None = Field(default=None, max_length=80)
    languages: list[str] | None = Field(default=None, max_length=10)
    bio: str | None = Field(default=None, max_length=500)
    listed: bool | None = None

    @field_validator("name", "origin_state", "origin_city", "current_state", "current_city", "current_district", "bio")
    @classmethod
    def _strip(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("origin_city", "current_city", "current_district")
    @classmethod
    def _place(cls, value):
        if value is not None and not PLACE.fullmatch(value): raise ValueError("Use letters, numbers, spaces and simple punctuation")
        return value

    @field_validator("languages")
    @classmethod
    def _languages(cls, value):
        if value is None: return value
        seen: list[str] = []
        for item in value:
            item = item.strip()
            if not item or len(item) > 40 or not LANGUAGE.fullmatch(item): raise ValueError("Each language is a word or two of letters")
            if item.lower() not in {s.lower() for s in seen}: seen.append(item[:1].upper() + item[1:])
        return seen


@router.get("/sectors")
def sectors(user=Depends(_current_user), db: Session = Depends(get_db)):
    """Reference data for any signed-in person: the caretaker's own form needs the state list too."""
    rows = db.scalars(select(Sector).order_by(Sector.code)).all()
    states = db.scalars(select(SectorState).order_by(SectorState.state)).all()
    order = {"NORTH": 0, "SOUTH": 1, "EAST": 2, "WEST": 3}
    return {"items": [{"id": str(s.id), "code": s.code, "name": s.name, "states": [st.state for st in states if st.sector_id == s.id]}
                      for s in sorted(rows, key=lambda s: order.get(s.code, 9))]}


@router.get("/agencies")
def agencies(sector: Literal["NORTH", "SOUTH", "EAST", "WEST"] | None = None, user=Depends(_browser), db: Session = Depends(get_db)):
    stmt = select(Agency, Sector).join(Sector, Sector.id == Agency.sector_id).where(Agency.is_active.is_(True))
    if sector: stmt = stmt.where(Sector.code == sector)
    rows = db.execute(stmt.order_by(Agency.name)).all()
    return {"items": [{"id": str(a.id), "name": a.name, "city": a.city, "sector": s.code, "is_synthetic": a.is_synthetic} for a, s in rows]}


def multi(values: list[str] | None, max_len: int, allowed: set[str] | None = None) -> list[str]:
    """Repeated (?city=A&city=B) or comma-separated (?city=A,B) values, validated server-side."""
    items = svc.many(values)
    if len(items) > 30: raise HTTPException(422, "Choose at most 30 values per filter")
    for item in items:
        if len(item) > max_len: raise HTTPException(422, "A filter value is too long")
        if allowed is not None and item not in allowed: raise HTTPException(422, "Unknown capability")
    return items


@router.get("/sector-summary")
def sector_summary(user=Depends(_browser), db: Session = Depends(get_db)):
    """For the India map: per sector, listed caretakers (total and per state) and the top three agencies."""
    return {"items": svc.sector_summary(db)}


@router.get("/options")
def filter_options(user=Depends(_current_user), db: Session = Depends(get_db)):
    """Dropdown values that exist among listed caretakers: states, cities (with state), languages, skills."""
    return svc.options(db)


@router.get("/caretakers")
def caretakers(sector: Literal["NORTH", "SOUTH", "EAST", "WEST"] | None = None, agency: uuid.UUID | None = None,
               state: list[str] | None = Query(None), city: list[str] | None = Query(None),
               gender: Literal["FEMALE", "MALE", "NON_BINARY", "UNDISCLOSED"] | None = None, language: list[str] | None = Query(None),
               capability: list[str] | None = Query(None), min_experience: int | None = Query(None, ge=0, le=60), min_agency_rating: float | None = Query(None, ge=1, le=5), available_on: date | None = None,
               sort: Literal["name", "experience"] = "name", limit: int = Query(20, ge=1, le=svc.MAX_PAGE), offset: int = Query(0, ge=0, le=100_000),
               user=Depends(_browser), db: Session = Depends(get_db)):
    state, city, language, capability = multi(state, 60), multi(city, 80), multi(language, 40), multi(capability, 40, SUPPORT)
    f = svc.Filters(sector=sector, agency=agency, state=state, city=city, gender=gender, language=language, capability=capability,
                    min_experience=min_experience, min_agency_rating=min_agency_rating, available_on=available_on, sort=sort, limit=limit, offset=offset)
    rows, total = svc.search(db, f)
    sectors_by_id, agencies_by_id = svc.lookups(db)
    items = [svc.card(p, cg, sectors_by_id, agencies_by_id) for p, cg, _ in rows]
    _with_reputation(db, items)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def _with_reputation(db: Session, items: list[dict]) -> None:
    """With the `ratings` flag on, each card carries its composite reputation (computed now, same as the profile)."""
    from app.core.config import settings
    if not settings.feature("ratings") or not items: return
    from app.services import reputation
    found = reputation.breakdowns(db, [uuid.UUID(i["id"]) for i in items])
    for i in items:
        b = found[uuid.UUID(i["id"])]
        i["reputation"] = reputation.summary(b)
        i["agency_rating"] = b["sources"]["agency"]["stars"]


@router.get("/caretakers/{cid}")
def caretaker(cid: uuid.UUID, user=Depends(_browser), db: Session = Depends(get_db)):
    cg = db.get(Caregiver, cid)
    profile = db.scalar(select(CaretakerProfile).where(CaretakerProfile.caregiver_id == cid)) if cg else None
    if not cg or not profile or cg.kind != "CARETAKER" or not cg.is_active: raise HTTPException(404, "Caretaker not found")
    on_team = svc.on_viewer_team(db, user, cg)
    # Unlisted caretakers are hidden from everyone except care teams they already work with.
    if not profile.listed and not on_team: raise HTTPException(404, "Caretaker not found")
    sectors_by_id, agencies_by_id = svc.lookups(db)
    out = svc.detail(profile, cg, sectors_by_id, agencies_by_id, on_team=on_team)
    _with_reputation(db, [out])
    return out


@router.get("/me")
def my_profile(user=Depends(_caretaker), db: Session = Depends(get_db)):
    return svc.own_view(db, user)


@router.patch("/me")
def edit_my_profile(body: ProfilePatch, request: Request, user=Depends(_caretaker), db: Session = Depends(get_db)):
    values = body.model_dump(exclude_unset=True)
    for key in ("name", "gender", "listed", "languages"):
        if key in values and values[key] is None: raise HTTPException(422, f"{key} cannot be empty")
    cg = svc.own_caregiver(db, user)
    profile = db.scalar(select(CaretakerProfile).where(CaretakerProfile.caregiver_id == cg.id))
    if profile is None:
        profile = CaretakerProfile(caregiver_id=cg.id, listed=False, languages=[], is_synthetic=user.is_synthetic); db.add(profile)
    for key in ("origin_state", "current_state"):
        if key in values:
            try: values[key], sector_id = svc.canonical_state(db, values[key] or "")
            except ValueError: raise HTTPException(422, f"Unknown state for {key.replace('_', ' ')}") from None
            if key == "current_state": profile.sector_id = sector_id
    if "name" in values:
        user.name = cg.name = values.pop("name")
    for key, value in values.items():
        setattr(profile, key, "" if value is None else value)
    db.add(ActivityHistory(actor_user_id=user.id, patient_id=None, event_type="directory.profile_updated", entity_type="caretaker_profile", entity_id=str(cg.id),
                           summary="Directory profile updated", payload={"fields": sorted(body.model_fields_set)}, request_id=getattr(request.state, "request_id", "")))
    db.commit()
    return svc.own_view(db, user)
