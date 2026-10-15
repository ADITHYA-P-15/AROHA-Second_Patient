"""Caretaker directory: migration 0016, filters, privacy, pagination and the fictional seed."""
import os
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, inspect, select

from app.core.clock import now, to_utc
from app.core.config import settings
from app.core.db import SessionLocal
from app.main import app
from app.models import AppSetting, AvailabilityOverride, Caregiver, CaretakerProfile, Sector, SectorState, User
from app.seed import directory as directory_seed
from tests.helpers import H, account, caretaker, primary_contact_with_patient

BACKEND = Path(__file__).resolve().parents[1]
DIRECTORY_TABLES = {"sectors", "sector_states", "agencies", "caretaker_profiles"}


@pytest.fixture(scope="module", autouse=True)
def seeded():
    with SessionLocal() as db:
        directory_seed.ensure(db); db.commit()


def browse(path="/api/v1/directory/caretakers", role="PRIMARY_CONTACT", **params):
    client, *_ = account(role)
    return client.get(path, params=params)


def everyone(client, **params):
    items, offset = [], 0
    while True:
        page = client.get("/api/v1/directory/caretakers", params={**params, "limit": 50, "offset": offset}).json()
        items += page["items"]; offset += 50
        if offset >= page["total"]: return items


def login(email):
    c = TestClient(app)
    assert c.post("/api/v1/auth/login", headers=H, json={"email": email, "password": settings.demo_password}).status_code == 200
    return c


# --- migration ---------------------------------------------------------------------------------------------------------

def _migrate(url, monkeypatch):
    from alembic import command
    from alembic.config import Config
    monkeypatch.setattr(settings, "database_url", url)
    cfg = Config(str(BACKEND / "alembic.ini")); cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    engine = create_engine(url)
    command.upgrade(cfg, "head")
    tables = set(inspect(engine).get_table_names())
    assert DIRECTORY_TABLES <= tables
    with engine.connect() as conn:
        assert {r[0] for r in conn.exec_driver_sql("SELECT code FROM sectors")} == {"NORTH", "SOUTH", "EAST", "WEST"}
        assert conn.exec_driver_sql("SELECT count(*) FROM sector_states").scalar() >= 30
    command.upgrade(cfg, "head")  # guarded: running again changes nothing
    command.downgrade(cfg, "0014_wellbeing_check_ins")
    tables = set(inspect(engine).get_table_names())
    assert not (DIRECTORY_TABLES & tables) and "caregivers" in tables and "wellbeing_check_ins" in tables
    command.upgrade(cfg, "head")
    assert DIRECTORY_TABLES <= set(inspect(engine).get_table_names())
    engine.dispose()


def test_migration_0016_up_and_down_on_sqlite(tmp_path, monkeypatch):
    _migrate(f"sqlite:///{(tmp_path / 'migrate.db').as_posix()}", monkeypatch)


@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="set TEST_POSTGRES_URL to an empty Postgres database to run")
def test_migration_0016_up_and_down_on_postgres(monkeypatch):
    _migrate(os.environ["TEST_POSTGRES_URL"], monkeypatch)


# --- seed --------------------------------------------------------------------------------------------------------------

def test_seed_is_idempotent_and_entirely_synthetic():
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(CaretakerProfile))
        again = directory_seed.ensure(db); db.commit()
        assert again["caretakers"] == 0 and db.scalar(select(func.count()).select_from(CaretakerProfile)) == before
        assert db.get(AppSetting, directory_seed.DIRECTORY_KEY).value["caretakers"] == 60
        people = db.scalars(select(User).where(User.email.like(f"%{directory_seed.DOMAIN}"))).all()
        assert len(people) == 60 and all(u.is_synthetic for u in people)
        profiles = db.scalars(select(CaretakerProfile)).all()
        assert all(p.is_synthetic for p in profiles if p.current_district.endswith("(fictional)"))
        assert {s.code for s in db.scalars(select(Sector))} == {"NORTH", "SOUTH", "EAST", "WEST"}
        assert db.scalar(select(func.count()).select_from(SectorState)) >= 30
    pc, *_ = account()
    assert len(pc.get("/api/v1/directory/agencies").json()["items"]) == 12
    sectors = {c["sector"] for c in everyone(pc)}
    assert sectors >= {"NORTH", "SOUTH", "EAST", "WEST"}


# --- filters -----------------------------------------------------------------------------------------------------------

def test_each_filter_narrows_and_combined_filters_intersect():
    pc, *_ = account()
    all_items = everyone(pc)
    assert all_items
    north = everyone(pc, sector="NORTH")
    assert north and all(c["sector"] == "NORTH" for c in north) and len(north) < len(all_items)
    agency = pc.get("/api/v1/directory/agencies", params={"sector": "EAST"}).json()["items"][0]
    assert all(a["sector"] == "EAST" for a in pc.get("/api/v1/directory/agencies", params={"sector": "EAST"}).json()["items"])
    at_agency = everyone(pc, agency=agency["id"])
    assert all(c["agency"]["id"] == agency["id"] for c in at_agency)
    assert all(c["current_state"] == "Delhi" for c in everyone(pc, state="delhi"))
    assert all(c["current_city"] == "Pune" for c in everyone(pc, city="Pune"))
    women = everyone(pc, gender="FEMALE")
    assert women and all(c["gender"] == "FEMALE" for c in women)
    tamil = everyone(pc, language="tamil")
    assert tamil and all("Tamil" in c["languages"] for c in tamil)
    escorts = everyone(pc, capability="LAB_ESCORT")
    assert escorts and all("LAB_ESCORT" in c["capabilities"] for c in escorts)
    seasoned = everyone(pc, min_experience=15)
    assert seasoned and all(c["years_experience"] >= 15 for c in seasoned)
    combined = everyone(pc, sector="SOUTH", gender="FEMALE", min_experience=5)
    expected = {c["id"] for c in everyone(pc, sector="SOUTH")} & {c["id"] for c in women} & {c["id"] for c in everyone(pc, min_experience=5)}
    assert {c["id"] for c in combined} == expected
    by_experience = everyone(pc, sort="experience")
    assert [c["years_experience"] for c in by_experience] == sorted((c["years_experience"] for c in by_experience), reverse=True)
    names = [c["name"].lower() for c in all_items]
    assert names == sorted(names)
    assert pc.get("/api/v1/directory/caretakers", params={"capability": "BRAIN_SURGERY"}).status_code == 422
    assert pc.get("/api/v1/directory/caretakers", params={"sector": "CENTRAL"}).status_code == 422


def test_available_on_reuses_the_weekly_schedule_and_leave():
    pc, *_ = account()
    day = (now() + timedelta(days=1)).date()
    while day.weekday() != 5: day += timedelta(days=1)  # a Saturday: weekday-only caretakers are not available
    saturday = {c["id"] for c in everyone(pc, available_on=day.isoformat())}
    weekday = day + timedelta(days=2)
    monday = {c["id"] for c in everyone(pc, available_on=weekday.isoformat())}
    assert saturday and monday and saturday != monday
    some = next(iter(saturday))
    with SessionLocal() as db:
        from datetime import datetime, time
        from zoneinfo import ZoneInfo
        zone = ZoneInfo(settings.app_timezone)
        cg = db.get(Caregiver, uuid.UUID(some))
        db.add(AvailabilityOverride(caregiver_id=cg.id, start_at=to_utc(datetime.combine(day, time.min, zone)), end_at=to_utc(datetime.combine(day + timedelta(days=1), time.min, zone)),
                                    status="UNAVAILABLE", reason="PERSONAL", created_by=cg.user_id))
        db.commit()
    assert some not in {c["id"] for c in everyone(pc, available_on=day.isoformat())}


# --- pagination --------------------------------------------------------------------------------------------------------

def test_pagination_is_bounded_and_stable():
    pc, *_ = account()
    first = pc.get("/api/v1/directory/caretakers", params={"limit": 10}).json()
    second = pc.get("/api/v1/directory/caretakers", params={"limit": 10, "offset": 10}).json()
    assert len(first["items"]) == 10 and first["total"] >= 58 and first["limit"] == 10
    assert not ({c["id"] for c in first["items"]} & {c["id"] for c in second["items"]})
    assert pc.get("/api/v1/directory/caretakers", params={"limit": 51}).status_code == 422
    assert pc.get("/api/v1/directory/caretakers", params={"limit": 0}).status_code == 422
    assert pc.get("/api/v1/directory/caretakers", params={"offset": -1}).status_code == 422
    assert pc.get("/api/v1/directory/caretakers", params={"offset": 5000}).json()["items"] == []
    assert len(pc.get("/api/v1/directory/caretakers").json()["items"]) == 20


# --- privacy and roles -------------------------------------------------------------------------------------------------

def test_cards_and_profiles_hide_contact_details_until_the_caretaker_is_on_the_viewers_team():
    pc, *_ = account()
    listed = pc.get("/api/v1/directory/caretakers", params={"limit": 5}).json()["items"]
    for c in listed: assert not {"phone", "notes", "current_district", "private"} & set(c)
    profile = pc.get(f"/api/v1/directory/caretakers/{listed[0]['id']}").json()
    assert profile["private"] is None and profile["on_my_team"] is False and "phone" not in profile and profile["bio"]

    coord, pid = primary_contact_with_patient()
    cid, carer = caretaker(coord, pid, name="Team caretaker")
    patched = carer.patch("/api/v1/directory/me", headers=H, json={"listed": True, "current_state": "karnataka", "current_city": "Mysuru", "current_district": "Fictional Ward 3"})
    assert patched.status_code == 200, patched.text
    assert patched.json()["current_state"] == "Karnataka" and patched.json()["sector"] == "SOUTH"
    on_team = coord.get(f"/api/v1/directory/caretakers/{cid}").json()
    assert on_team["on_my_team"] is True and on_team["private"]["current_district"] == "Fictional Ward 3" and "phone" in on_team["private"]
    stranger = pc.get(f"/api/v1/directory/caretakers/{cid}").json()
    assert stranger["private"] is None and stranger["on_my_team"] is False


def test_unlisted_caretakers_are_hidden_from_browsing():
    pc, *_ = account()
    with SessionLocal() as db:
        hidden = [str(p.caregiver_id) for p in db.scalars(select(CaretakerProfile).where(CaretakerProfile.listed.is_(False)))]
    assert hidden
    shown = {c["id"] for c in everyone(pc)}
    assert not (set(hidden) & shown)
    assert pc.get(f"/api/v1/directory/caretakers/{hidden[0]}").status_code == 404
    assert pc.get(f"/api/v1/directory/caretakers/{uuid.uuid4()}").status_code == 404


def test_a_new_caretaker_is_unlisted_until_they_choose_to_be_listed():
    carer, _, user_id = account("CARETAKER", "New caretaker")
    mine = carer.get("/api/v1/directory/me").json()
    assert mine["exists"] is False and mine["listed"] is False
    saved = carer.patch("/api/v1/directory/me", headers=H, json={"name": "Renamed caretaker", "gender": "FEMALE", "languages": ["tamil", "English", "Tamil"], "bio": "Fictional bio."}).json()
    assert saved["exists"] is True and saved["listed"] is False and saved["name"] == "Renamed caretaker" and saved["languages"] == ["Tamil", "English"]
    pc, *_ = account()
    assert saved["id"] not in {c["id"] for c in everyone(pc)}
    carer.patch("/api/v1/directory/me", headers=H, json={"listed": True})
    assert saved["id"] in {c["id"] for c in everyone(pc)}
    assert carer.get("/api/v1/auth/me").json()["name"] == "Renamed caretaker"


def test_caretakers_edit_only_their_own_profile_and_input_is_validated():
    carer, *_ = account("CARETAKER")
    other_id = account("PRIMARY_CONTACT")[0].get("/api/v1/directory/caretakers", params={"limit": 1}).json()["items"][0]["id"]
    assert carer.patch(f"/api/v1/directory/caretakers/{other_id}", headers=H, json={"bio": "x"}).status_code == 405
    assert carer.patch("/api/v1/directory/me", headers=H, json={"caregiver_id": other_id}).status_code == 422
    assert carer.patch("/api/v1/directory/me", headers=H, json={"current_state": "Atlantis"}).status_code == 422
    assert carer.patch("/api/v1/directory/me", headers=H, json={"bio": "x" * 501}).status_code == 422
    assert carer.patch("/api/v1/directory/me", headers=H, json={"gender": "ROBOT"}).status_code == 422
    assert carer.patch("/api/v1/directory/me", headers=H, json={"listed": None}).status_code == 422
    assert carer.patch("/api/v1/directory/me", headers=H, json={"languages": ["<script>"]}).status_code == 422
    assert carer.patch("/api/v1/directory/me", json={"bio": "no csrf header"}).status_code == 403
    for role in ("PRIMARY_CONTACT", "PROFESSIONAL"):
        client, *_ = account(role)
        assert client.patch("/api/v1/directory/me", headers=H, json={"bio": "x"}).status_code == 403
        assert client.get("/api/v1/directory/me").status_code == 403


def test_only_families_patients_and_professionals_may_browse():
    for role in ("PRIMARY_CONTACT", "PROFESSIONAL"):
        assert browse(role=role).status_code == 200
    coord, pid = primary_contact_with_patient(patient_account={"email": f"p-{uuid.uuid4().hex}@example.com", "password": "SafePass!123"})
    patient = TestClient(app)
    team = coord.get(f"/api/v1/patients/{pid}/care-team").json()["items"]
    email = next(m["email"] for m in team if m["team_role"] == "PATIENT_SELF")
    assert patient.post("/api/v1/auth/login", headers=H, json={"email": email, "password": "SafePass!123"}).status_code == 200
    assert patient.get("/api/v1/directory/caretakers").status_code == 200
    carer, *_ = account("CARETAKER")
    some = coord.get("/api/v1/directory/caretakers", params={"limit": 1}).json()["items"][0]["id"]
    for path in ("/api/v1/directory/caretakers", f"/api/v1/directory/caretakers/{some}", "/api/v1/directory/agencies"):
        assert carer.get(path).status_code == 403
    assert carer.get("/api/v1/directory/sectors").status_code == 200
    anonymous = TestClient(app)
    for path in ("/api/v1/directory/caretakers", "/api/v1/directory/sectors", "/api/v1/directory/agencies", "/api/v1/directory/me"):
        assert anonymous.get(path).status_code == 401


def test_the_directory_flag_switches_it_off(monkeypatch):
    pc, *_ = account()
    monkeypatch.setattr(settings, "features", "voice_notes")
    assert pc.get("/api/v1/directory/caretakers").status_code == 404
    monkeypatch.setattr(settings, "features", "voice_notes,directory")
    assert pc.get("/api/v1/directory/caretakers").status_code == 200


def test_invite_by_email_still_works_alongside_the_directory():
    coord, pid = primary_contact_with_patient()
    cid, _ = caretaker(coord, pid, name="Invited caretaker")
    assert any(c["id"] == cid for c in coord.get(f"/api/v1/patients/{pid}/caregivers").json()["items"])


def test_minimum_agency_rating_filter(monkeypatch):
    from app.models import AgencyRating
    from app.seed import reputation as reputation_seed
    with SessionLocal() as db:
        reputation_seed.agency_ratings(db); db.commit()
        stars = dict(db.execute(select(AgencyRating.caregiver_id, AgencyRating.rating)).all())
    pc, *_ = account()
    top = everyone(pc, min_agency_rating=4)
    assert top and all(stars.get(uuid.UUID(c["id"]), 0) >= 4 for c in top)
    assert all(c["agency_rating"] >= 4 for c in top if "agency_rating" in c)
    assert len(top) < len(everyone(pc)) and len(everyone(pc, min_agency_rating=4.5)) <= len(top)
    combined = everyone(pc, min_agency_rating=4, sector="SOUTH")
    assert {c["id"] for c in combined} == {c["id"] for c in top} & {c["id"] for c in everyone(pc, sector="SOUTH")}
    for bad in (0, 6, "x"):
        assert pc.get("/api/v1/directory/caretakers", params={"min_agency_rating": bad}).status_code == 422


def test_several_values_per_filter_match_any_and_fields_combine():
    pc, *_ = account()
    delhi, pune = everyone(pc, state="Delhi"), everyone(pc, city="Pune")
    both = everyone(pc, state=["Delhi", "Maharashtra"])
    assert {c["id"] for c in delhi} < {c["id"] for c in both} and all(c["current_state"] in ("Delhi", "Maharashtra") for c in both)
    assert {c["id"] for c in everyone(pc, state="Delhi,Maharashtra")} == {c["id"] for c in both}  # comma form
    cities = everyone(pc, city=["Pune", "Kolkata"])
    assert {c["current_city"] for c in cities} == {"Pune", "Kolkata"} and {c["id"] for c in pune} < {c["id"] for c in cities}
    langs = everyone(pc, language=["Tamil", "bengali"])
    assert langs and all({"Tamil", "Bengali"} & set(c["languages"]) for c in langs)
    caps = everyone(pc, capability=["LAB_ESCORT", "SUPPLIES"])
    assert caps and all({"LAB_ESCORT", "SUPPLIES"} & set(c["capabilities"]) for c in caps)
    combined = everyone(pc, state=["Delhi", "Maharashtra"], language=["Hindi", "Marathi"])
    assert {c["id"] for c in combined} == {c["id"] for c in both} & {c["id"] for c in everyone(pc, language="Hindi,Marathi")}
    assert pc.get("/api/v1/directory/caretakers", params={"capability": ["LAB_ESCORT", "FLYING"]}).status_code == 422
    assert pc.get("/api/v1/directory/caretakers", params={"city": [f"c{i}" for i in range(31)]}).status_code == 422


def test_filter_options_come_from_listed_caretakers():
    pc, *_ = account()
    opts = pc.get("/api/v1/directory/options").json()
    assert {"Delhi", "Karnataka", "Maharashtra"} <= set(opts["states"]) and "Atlantis" not in opts["states"]
    assert {"city": "Pune", "state": "Maharashtra"} in opts["cities"] and "Tamil" in opts["languages"] and "TRANSPORT" in opts["capabilities"]
    assert len(opts["languages"]) == len({l.lower() for l in opts["languages"]})  # no case duplicates
    for city in opts["cities"][:3]:
        assert everyone(pc, city=city["city"])
    assert TestClient(app).get("/api/v1/directory/options").status_code == 401


def test_sector_summary_counts_listed_caretakers_and_ranks_agencies():
    from app.seed import reputation as reputation_seed
    with SessionLocal() as db:
        reputation_seed.agency_ratings(db); db.commit()
    pc, *_ = account()
    items = pc.get("/api/v1/directory/sector-summary").json()["items"]
    assert [s["code"] for s in items] == ["NORTH", "SOUTH", "EAST", "WEST"]
    for s in items:
        listed = everyone(pc, sector=s["code"])
        assert s["caretakers"] == len(listed) and sum(s["states"].values()) == len(listed)
        assert len(s["top_agencies"]) <= 3 and s["agency_count"] >= len(s["top_agencies"])
        ratings = [a["average_rating"] or 0 for a in s["top_agencies"]]
        assert ratings == sorted(ratings, reverse=True)
        for a in s["top_agencies"]:
            assert a["caretakers"] == len([c for c in listed if c["agency"] and c["agency"]["id"] == a["id"]])
    carer, *_ = account("CARETAKER")
    assert carer.get("/api/v1/directory/sector-summary").status_code == 403
