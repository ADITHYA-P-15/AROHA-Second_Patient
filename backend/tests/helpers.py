"""Shared builders for API tests: every person is a real CareCircle account in one of the four roles."""
import uuid

from fastapi.testclient import TestClient

from app.main import app

H = {"X-Requested-With": "second-patient"}
ANYTIME = [{"weekday": d, "start_min": 0, "end_min": 1440} for d in range(7)]
PASSWORD = "SafePass!123"


def account(role="PRIMARY_CONTACT", name="Synthetic person"):
    """Sign up a new account and return (logged-in client, email, user_id)."""
    client = TestClient(app)
    email = f"t-{uuid.uuid4().hex}@example.com"
    created = client.post("/api/v1/auth/register", headers=H, json={"name": name, "email": email, "password": PASSWORD, "role": role})
    assert created.status_code == 201, created.text
    client.email, client.user_id = email, created.json()["id"]
    return client, email, created.json()["id"]


def primary_contact_with_patient(name="Synthetic patient", **patient):
    client, email, user_id = account("PRIMARY_CONTACT", "Primary contact")
    created = client.post("/api/v1/patients", headers=H, json={"name": name, "birth_year": 1950, **patient})
    assert created.status_code == 201, created.text
    return client, created.json()["id"]


def caretaker(coord, pid, name="Caretaker", caps=("TRANSPORT",), day=3, week=40.0, windows=ANYTIME):
    """Invite a caretaker account to the patient's team and shape their care profile. Returns (caregiver_id, client)."""
    client, email, user_id = account("CARETAKER", name)
    assert coord.post(f"/api/v1/patients/{pid}/care-team", headers=H, json={"email": email, "team_role": "CARETAKER"}).status_code == 201
    cid = next(c["id"] for c in coord.get(f"/api/v1/patients/{pid}/caregivers").json()["items"] if c["user_id"] == user_id)
    patched = coord.patch(f"/api/v1/caregivers/{cid}", headers=H, json={"capabilities": list(caps), "max_activities_per_day": day, "max_hours_per_week": week})
    assert patched.status_code == 200, patched.text
    assert coord.put(f"/api/v1/caregivers/{cid}/schedule", headers=H, json={"windows": list(windows)}).status_code == 200
    return cid, client


TINY_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 600 + b"\xff\xd9"  # not a real photo; just over the server's minimum size


def give_dose(client, aid, **kwargs):
    """Upload the (demo) proof photo a medicine dose now requires, then record it as done."""
    uploaded = client.put(f"/api/v1/activities/{aid}/proof-photo", headers={**H, "Content-Type": "image/jpeg"}, content=TINY_JPEG)
    assert uploaded.status_code == 201, uploaded.text
    return client.post(f"/api/v1/activities/{aid}/complete", headers=H, json={}, **kwargs)


def join_as_professional(pid_owner, pid):
    """A healthcare professional joins via the CareCircle ID and birth year the family shared."""
    patient = pid_owner.get(f"/api/v1/patients/{pid}").json()
    client, email, user_id = account("PROFESSIONAL", "Healthcare professional")
    joined = client.post("/api/v1/patients/join", headers=H, json={"care_code": patient["care_code"], "birth_year": patient["birth_year"]})
    assert joined.status_code == 201, joined.text
    return client, email, user_id
