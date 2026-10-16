from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import settings
from app.core.db import SessionLocal
from app.main import app, seed
from app.models import AvailabilityOverride, CareActivity, CareAssignment, Caregiver, Prescription
from app.services import demo
from tests.helpers import H, account


def login(email):
    c = TestClient(app)
    assert c.post("/api/v1/auth/login", headers=H, json={"email": email, "password": settings.demo_password}).status_code == 200
    return c


def test_demo_scenario_is_fully_covered_with_one_missed_dose():
    seed()
    anita = login("anita.iyer@secondpatient.demo")
    assert anita.post("/api/v1/demo/reset", headers=H).json() == {"status": "reset"}
    with SessionLocal() as db:
        ids = [p.id for p in demo.demo_patients(db).values()]
        rows = db.scalars(select(CareActivity).where(CareActivity.patient_id.in_(ids))).all()
        assert rows and all(db.scalar(select(CareAssignment.id).where(CareAssignment.activity_id == a.id, CareAssignment.status == "CONFIRMED")) for a in rows)
        assert sum(a.lifecycle_status == "MISSED" for a in rows) == 1
        assert {a.title for a in rows if a.category == "APPOINTMENT"} == {"Cardiology follow-up", "Physiotherapy session", "Eye check-up"}
        assert db.scalar(select(func.count()).select_from(Prescription).where(Prescription.patient_id.in_(ids))) == 3


def test_reset_undoes_demo_changes_and_ensure_is_idempotent():
    seed()
    savitha = login("savitha@secondpatient.demo")
    with SessionLocal() as db:
        cid = db.scalar(select(Caregiver.id).where(Caregiver.name == "Savitha"))
    pid = savitha.get("/api/v1/patients").json()["items"][0]["id"]
    assert savitha.post(f"/api/v1/caregivers/{cid}/availability-overrides", headers=H,
                        json={"start_at": "2030-01-01T00:00:00+05:30", "end_at": "2030-01-02T00:00:00+05:30", "status": "UNAVAILABLE", "reason": "PERSONAL"}).status_code == 201
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(CareActivity))
        demo.ensure(db); db.commit()  # same version and a plan exists: nothing is rebuilt
        assert db.scalar(select(func.count()).select_from(CareActivity)) == before
        assert db.scalar(select(func.count()).select_from(AvailabilityOverride)) >= 1
    assert savitha.post("/api/v1/demo/reset", headers=H).status_code == 403
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(CareActivity)) == before
        assert db.scalar(select(func.count()).select_from(AvailabilityOverride)) >= 1
    assert login("anita.iyer@secondpatient.demo").post("/api/v1/demo/reset", headers=H).status_code == 200
    with SessionLocal() as db:
        new_cid = db.scalar(select(Caregiver.id).where(Caregiver.name == "Savitha"))
        assert db.scalar(select(func.count()).select_from(AvailabilityOverride).where(AvailabilityOverride.caregiver_id == new_cid)) == 0
    assert savitha.get(f"/api/v1/patients/{pid}").status_code == 200  # accounts and teams survive a reset


def test_only_demo_accounts_can_reset():
    seed()
    patient = login("ramesh.iyer@secondpatient.demo")
    caretaker = login("savitha@secondpatient.demo")
    professional = login("dr.arjun.nair@secondpatient.demo")
    assert patient.post("/api/v1/demo/reset", headers=H).status_code == 403
    assert caretaker.post("/api/v1/demo/reset", headers=H).status_code == 403
    assert professional.post("/api/v1/demo/reset", headers=H).status_code == 403
    outsider, _, _ = account("PRIMARY_CONTACT")
    assert outsider.post("/api/v1/demo/reset", headers=H).status_code == 403
    assert TestClient(app).post("/api/v1/demo/reset", headers=H).status_code == 401


def test_demo_reset_endpoint_is_disabled_in_production(monkeypatch):
    seed()
    anita = login("anita.iyer@secondpatient.demo")
    monkeypatch.setattr(settings, "app_env", "production")
    assert anita.post("/api/v1/demo/reset", headers=H).status_code == 403


def test_missed_medicine_message_reaches_caretaker_and_acknowledging_clears_alerts():
    seed()
    login("anita.iyer@secondpatient.demo").post("/api/v1/demo/reset", headers=H)
    ramesh = login("ramesh.iyer@secondpatient.demo")
    pid = ramesh.get("/api/v1/patients").json()["items"][0]["id"]
    sent = ramesh.post(f"/api/v1/patients/{pid}/messages", headers={**H, "Idempotency-Key": "demo-missed-medicine-1"}, json={"body": "I missed my medicine", "channel": "TEXT"}).json()
    assert sent["current_level"] == 1 and sent["title"] == "Medicine help request"
    savitha = login("savitha@secondpatient.demo")
    mine = [n for n in savitha.get("/api/v1/notifications").json()["items"] if n.get("incident_id") == sent["id"]]
    assert [n["title"] for n in mine] == ["Medicine help request"] and mine[0]["read_at"] is None
    assert savitha.post(f"/api/v1/incidents/{sent['id']}/acknowledge", headers=H).status_code == 200
    after = [n for n in savitha.get("/api/v1/notifications").json()["items"] if n.get("incident_id") == sent["id"]]
    assert after and all(n["read_at"] for n in after) and "You are handling this request" not in {n["title"] for n in after}
