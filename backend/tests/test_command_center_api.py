import uuid
from datetime import timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.core.clock import now
from app.main import app
from tests.helpers import caretaker, join_as_professional, primary_contact_with_patient

H = {"X-Requested-With": "second-patient"}


def make_patient(client):
    suffix = uuid.uuid4().hex
    assert client.post("/api/v1/auth/register", headers=H, json={"name": "Coordinator", "email": f"cc-{suffix}@example.com", "password": "SafePass!123"}).status_code == 201
    response = client.post("/api/v1/patients", headers=H, json={"name": "Synthetic Command Center Patient", "birth_year": 1950})
    assert response.status_code == 201
    return response.json()["id"]


def test_command_center_reminders_and_access():
    client = TestClient(app)
    patient_id = make_patient(client)
    day = now().astimezone(ZoneInfo("Asia/Kolkata")).date()
    center = client.get("/api/v1/command-center", params={"patient_id": patient_id, "date": day.isoformat()})
    assert center.status_code == 200
    assert center.json()["basis_note"] == "Based on confirmed assignments, availability and logged updates. This does not check on the patient's wellbeing."
    assert center.json()["patient"]["is_synthetic"] is True

    created = client.post("/api/v1/action-items", params={"patient_id": patient_id}, headers=H, json={"title": "Call the pharmacy"})
    assert created.status_code == 201
    item_id = created.json()["id"]
    snoozed = client.post(f"/api/v1/action-items/{item_id}/snooze", headers=H, json={"until": (now() + timedelta(minutes=20)).isoformat()})
    assert snoozed.status_code == 200 and snoozed.json()["status"] == "SNOOZED"
    done = client.post(f"/api/v1/action-items/{item_id}/done", headers=H, json={})
    assert done.status_code == 200 and done.json()["status"] == "DONE"

    assert "briefs" not in center.json()  # morning briefs and handovers were cut
    assert client.get(f"/api/v1/patients/{patient_id}/briefs").status_code == 404

    professional, _, _ = join_as_professional(client, patient_id)
    assert professional.get("/api/v1/command-center", params={"patient_id": patient_id}).status_code == 403
    outsider = TestClient(app)
    suffix = uuid.uuid4().hex
    assert outsider.post("/api/v1/auth/register", headers=H, json={"name": "Outsider", "email": f"cc-out-{suffix}@example.com", "password": "SafePass!123"}).status_code == 201
    assert outsider.get("/api/v1/command-center", params={"patient_id": patient_id}).status_code == 403


def test_incident_reconcile_stores_uuid_on_sqlite():
    client = TestClient(app)
    patient_id = make_patient(client)
    sent = client.post(f"/api/v1/patients/{patient_id}/messages", headers=H, json={"body": "I need water", "channel": "TEXT", "on_behalf": True})
    assert sent.status_code == 201
    day = now().astimezone(ZoneInfo("Asia/Kolkata")).date()
    center = client.get("/api/v1/command-center", params={"patient_id": patient_id, "date": day.isoformat()})
    assert center.status_code == 200
    items = center.json()["needs_now"] + center.json()["at_risk"]
    assert any(x["related_incident_id"] == sent.json()["id"] for x in items)


def test_board_is_served_from_cache_until_something_is_written():
    from app.api import command_center as cc
    coord, pid = primary_contact_with_patient()
    first = coord.get(f"/api/v1/command-center?patient_id={pid}").json()
    again = coord.get(f"/api/v1/command-center?patient_id={pid}").json()
    assert again["as_of"] == first["as_of"]  # unchanged data: the stored answer is reused
    caretaker(coord, pid, "Cache Helper")  # any write invalidates it
    fresh = coord.get(f"/api/v1/command-center?patient_id={pid}").json()
    assert fresh["as_of"] != first["as_of"]
    cc._board_cache.clear()
