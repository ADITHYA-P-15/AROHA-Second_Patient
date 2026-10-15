from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import settings
from app.core.db import SessionLocal
from app.main import app, seed
from app.models import CareActivity, CareTeamMember, Patient, TeamRole, User
from app.services import population
from tests.helpers import H, account

KAVITA = "kavita.rao@carecircle.demo"


def login(email):
    c = TestClient(app)
    assert c.post("/api/v1/auth/login", headers=H, json={"email": email, "password": settings.demo_password}).status_code == 200
    return c


def build_population():
    seed()
    with SessionLocal() as db:
        first = population.ensure(db); db.commit()
        again = population.ensure(db); db.commit()
    return first, again


def test_population_is_built_once_and_leaves_the_core_story_alone():
    with SessionLocal() as db:
        core_before = {p.name: db.scalar(select(func.count()).select_from(CareActivity).where(CareActivity.patient_id == p.id)) for p in db.scalars(select(Patient).where(Patient.care_code.in_(("CC-RAM354", "CC-SHA746"))))}
    seed()
    first, again = build_population()
    assert again is None and (first is None or first["patients"] == 24)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Patient).where(Patient.name == "Lalitha Krishnan")) == 1
        people = db.scalars(select(User).where(User.email.like("%@carecircle.demo"))).all()
        assert len(people) >= 40 and {u.role.value for u in people} == {"PATIENT", "PRIMARY_CONTACT", "CARETAKER", "PROFESSIONAL"}
        core_after = {p.name: db.scalar(select(func.count()).select_from(CareActivity).where(CareActivity.patient_id == p.id)) for p in db.scalars(select(Patient).where(Patient.care_code.in_(("CC-RAM354", "CC-SHA746"))))}
    assert core_before == {} or core_before == core_after
    savitha = login("savitha@secondpatient.demo")
    assert {p["name"] for p in savitha.get("/api/v1/patients").json()["items"]} == {"Ramesh Iyer", "Sharada Pai"}


def test_professional_insights_cover_only_their_patients_and_add_up():
    build_population()
    kavita = login(KAVITA)
    body = kavita.get("/api/v1/insights/professional?days=30")
    assert body.status_code == 200
    data = body.json()
    mine = {p["id"] for p in kavita.get("/api/v1/patients").json()["items"]}
    assert {p["id"] for p in data["patients"]} == mine and len(mine) >= 5
    assert data["totals"]["due"] == sum(p["due"] for p in data["patients"])
    assert data["totals"]["missed"] == sum(p["missed"] for p in data["patients"])
    assert len(data["daily"]) == 30 and data["totals"]["needs_follow_up"] == sum(p["needs_follow_up"] for p in data["patients"])
    order = [(not p["needs_follow_up"]) for p in data["patients"]]
    assert order == sorted(order)  # follow-up first
    assert data["bands"]["follow_up"] + data["bands"]["watch"] + data["bands"]["on_track"] + data["bands"]["no_data"] == len(data["patients"])
    for p in data["patients"]:
        assert p["decided"] == p["on_time"] + p["late"] + p["missed"] and len(p["spark"]) == 14
        assert all(f["code"] and f["text"] for f in p["flags"])
    assert "not a clinical assessment" in data["note"]


def test_insights_are_limited_to_professionals_and_to_their_own_list():
    build_population()
    assert account("PRIMARY_CONTACT")[0].get("/api/v1/insights/professional").status_code == 403
    assert login("savitha@secondpatient.demo").get("/api/v1/insights/professional").status_code == 403
    assert TestClient(app).get("/api/v1/insights/professional").status_code == 401
    outsider, _, _ = account("PROFESSIONAL")
    empty = outsider.get("/api/v1/insights/professional").json()
    assert empty["patients"] == [] and empty["totals"]["due"] == 0
    imran = login("imran.shaikh@carecircle.demo").get("/api/v1/insights/professional").json()
    kavita = login(KAVITA).get("/api/v1/insights/professional").json()
    assert {p["id"] for p in imran["patients"]} != {p["id"] for p in kavita["patients"]}


def test_reset_keeps_the_population_and_caretakers_only_see_their_own_work():
    build_population()
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(CareTeamMember).where(CareTeamMember.team_role == TeamRole.CARETAKER))
    assert login("anita.iyer@secondpatient.demo").post("/api/v1/demo/reset", headers=H).status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(CareTeamMember).where(CareTeamMember.team_role == TeamRole.CARETAKER)) == before
        assert db.scalar(select(func.count()).select_from(Patient).where(Patient.name == "Mohan Das")) == 1
    anjali = login("anjali.verma@carecircle.demo")
    patients = anjali.get("/api/v1/patients").json()["items"]
    assert len(patients) >= 2
    for patient in patients:
        for item in anjali.get(f"/api/v1/patients/{patient['id']}/activities?limit=100").json()["items"]:
            assert any(a["is_mine"] for a in item["assignments"])


def test_background_build_respects_its_switches_and_is_idempotent(monkeypatch):
    from sqlalchemy import func
    from app.models import AppSetting
    from app.seed.population import build_in_background
    seed()
    monkeypatch.setattr(settings, "demo_population", False)
    build_in_background()  # switched off: nothing happens, nothing breaks
    monkeypatch.setattr(settings, "seed_demo", True); monkeypatch.setattr(settings, "demo_population", True)
    build_in_background(); build_in_background()  # twice: the second is a no-op
    with SessionLocal() as db:
        assert db.get(AppSetting, "demo_population") is not None
        assert db.scalar(select(func.count()).select_from(Patient).where(Patient.name == "Lalitha Krishnan")) == 1


def test_population_caretakers_are_listed_in_the_directory_once_the_population_exists():
    from app.seed import directory as directory_seed
    build_population()
    with SessionLocal() as db:
        directory_seed.ensure(db); db.commit()
        assert directory_seed.attach_population(db) == 0  # already attached, never twice
    pc, *_ = account()
    found = pc.get("/api/v1/directory/caretakers", params={"city": "Bengaluru", "limit": 50}).json()["items"]
    anjali = next(c for c in found if c["name"] == "Anjali Verma")
    assert anjali["agency"]["name"] in directory_seed.POPULATION_AGENCIES and "MEDICATION_ASSIST" in anjali["capabilities"]
