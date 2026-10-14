import uuid
from datetime import timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.clock import now
from app.core.db import SessionLocal
from app.main import app
from app.models import ActivityHistory, CareAssignment, User
from tests.helpers import account, caretaker, join_as_professional, primary_contact_with_patient

H = {"X-Requested-With": "second-patient"}
ANYTIME = [{"weekday": d, "start_min": 0, "end_min": 1440} for d in range(7)]


def caregiver(client, pid, name, kind="CARETAKER", caps=("TRANSPORT",), day=3):
    return caretaker(client, pid, name, caps=caps, day=day)[0]


def task(client, pid, title, hour, cid, support=("TRANSPORT",)):
    start = (now().astimezone(ZoneInfo("Asia/Kolkata")) + timedelta(days=2)).replace(hour=hour, minute=0, second=0, microsecond=0)
    created = client.post(f"/api/v1/patients/{pid}/activities", headers=H, json={"title": title, "category": "TRANSPORT", "scheduled_start": start.isoformat(), "scheduled_end": (start + timedelta(hours=1)).isoformat(), "required_support": list(support)})
    assert created.status_code == 201
    aid = created.json()["id"]
    assert client.post(f"/api/v1/activities/{aid}/assignments", headers=H, json={"caregiver_id": cid, "role": "PRIMARY", "confirm_now": True}).status_code == 201
    return aid


def setup_overload():
    client, pid = primary_contact_with_patient("Synthetic balancer patient")
    busy = caregiver(client, pid, "Busy Daughter", day=1)
    neighbour = caregiver(client, pid, "Kind Neighbour")
    helper = caregiver(client, pid, "Home Helper", caps=("DAILY_ASSIST",))
    first = task(client, pid, "Morning transport", 9, busy)
    second = task(client, pid, "Afternoon transport", 15, busy)
    return client, pid, {"busy": busy, "neighbour": neighbour, "helper": helper}, (first, second)


def test_coordinator_reviews_and_applies_recommendation_with_confirmation_request():
    client, pid, people, _ = setup_overload()
    response = client.get(f"/api/v1/patients/{pid}/workload-balance", params={"days": 7})
    assert response.status_code == 200
    data = response.json()
    assert data["permissions"]["can_apply"] is True and data["basis_note"].startswith("Based on assignments")
    busy = next(c for c in data["caregivers"] if c["caregiver_id"] == people["busy"])
    assert busy["status"] == "OVERLOADED" and busy["load_score"] == 200
    rec = next(r for r in data["recommendations"] if r["kind"] == "REDISTRIBUTE")
    assert rec["to"]["caregiver_id"] == people["neighbour"] and rec["from"]["assignment_id"]
    assert any(x["caregiver_id"] == people["helper"] for x in rec["excluded"])

    payload = {"activity_id": rec["activity"]["id"], "from_caregiver_id": people["busy"], "to_caregiver_id": people["neighbour"]}
    applied = client.post(f"/api/v1/patients/{pid}/workload-balance/apply", headers=H, json=payload)
    assert applied.status_code == 200 and applied.json()["assignment"]["status"] == "AWAITING_CONFIRMATION"
    assert "not confirmed until" in applied.json()["message"]
    assert client.post(f"/api/v1/patients/{pid}/workload-balance/apply", headers=H, json=payload).status_code == 409
    with SessionLocal() as db:
        old = db.get(CareAssignment, uuid.UUID(applied.json()["superseded_assignment_id"]))
        assert old.status == "SUPERSEDED"
        standby = db.scalar(select(CareAssignment).where(CareAssignment.activity_id == uuid.UUID(rec["activity"]["id"]), CareAssignment.role == "BACKUP"))
        assert applied.json()["standby_backup"] is True and standby.caregiver_id == uuid.UUID(people["busy"]) and standby.status == "CONFIRMED"
        event = db.scalar(select(ActivityHistory).where(ActivityHistory.patient_id == uuid.UUID(pid), ActivityHistory.event_type == "workload.rebalanced"))
        assert event and event.payload["mode"] == "REQUEST_CONFIRMATION"
    after = client.get(f"/api/v1/patients/{pid}/workload-balance").json()
    assert after["summary"]["overloaded"] == 0
    # Confirming the new primary releases the standby backup.
    assert client.post(f"/api/v1/assignments/{applied.json()['assignment']['id']}/confirm", headers=H, json={}).status_code == 200
    with SessionLocal() as db:
        assert db.get(CareAssignment, standby.id).status == "SUPERSEDED"


def test_apply_refuses_tasks_inside_two_hour_notice():
    client, pid, people, _ = setup_overload()
    start = now() + timedelta(minutes=50)
    created = client.post(f"/api/v1/patients/{pid}/activities", headers=H, json={"title": "Imminent transport", "category": "TRANSPORT", "scheduled_start": start.isoformat(), "scheduled_end": (start + timedelta(minutes=30)).isoformat(), "required_support": ["TRANSPORT"]})
    aid = created.json()["id"]
    assert client.post(f"/api/v1/activities/{aid}/assignments", headers=H, json={"caregiver_id": people["busy"], "role": "PRIMARY", "confirm_now": True}).status_code == 201
    refused = client.post(f"/api/v1/patients/{pid}/workload-balance/apply", headers=H, json={"activity_id": aid, "from_caregiver_id": people["busy"], "to_caregiver_id": people["neighbour"]})
    assert refused.status_code == 409 and "two hours" in refused.json()["error"]["message"]


def test_apply_rechecks_eligibility_and_supports_confirm_now():
    client, pid, people, (first, _) = setup_overload()
    bad = client.post(f"/api/v1/patients/{pid}/workload-balance/apply", headers=H, json={"activity_id": first, "from_caregiver_id": people["busy"], "to_caregiver_id": people["helper"]})
    assert bad.status_code == 409 and "Missing capability" in bad.json()["error"]["message"]
    wrong_donor = client.post(f"/api/v1/patients/{pid}/workload-balance/apply", headers=H, json={"activity_id": first, "from_caregiver_id": people["neighbour"], "to_caregiver_id": people["helper"]})
    assert wrong_donor.status_code == 409
    extra = client.post(f"/api/v1/patients/{pid}/workload-balance/apply", headers=H, json={"activity_id": first, "from_caregiver_id": people["busy"], "to_caregiver_id": people["neighbour"], "mode": "CONFIRM_NOW", "unexpected": 1})
    assert extra.status_code == 422
    good = client.post(f"/api/v1/patients/{pid}/workload-balance/apply", headers=H, json={"activity_id": first, "from_caregiver_id": people["busy"], "to_caregiver_id": people["neighbour"], "mode": "CONFIRM_NOW"})
    assert good.status_code == 200 and good.json()["assignment"]["status"] == "CONFIRMED"
    plan = client.get(f"/api/v1/activities/{first}").json()
    assert [a["caregiver_id"] for a in plan["assignments"] if a["status"] == "CONFIRMED"] == [people["neighbour"]]


def test_other_patient_details_are_masked_and_counted():
    client, pid, people, _ = setup_overload()
    other = client.post("/api/v1/patients", headers=H, json={"name": "Second synthetic patient", "birth_year": 1950}).json()["id"]
    neighbour_user = next(c["user_id"] for c in client.get(f"/api/v1/patients/{pid}/caregivers").json()["items"] if c["id"] == people["neighbour"])
    with SessionLocal() as db:
        neighbour_email = db.get(User, uuid.UUID(neighbour_user)).email
    assert client.post(f"/api/v1/patients/{other}/care-team", headers=H, json={"email": neighbour_email, "team_role": "CARETAKER"}).status_code == 201
    task(client, other, "Private errand for another patient", 12, people["neighbour"])
    body = client.get(f"/api/v1/patients/{pid}/workload-balance")
    assert "Private errand" not in body.text and "Second synthetic patient" not in body.text
    neighbour = next(c for c in body.json()["caregivers"] if c["caregiver_id"] == people["neighbour"])
    assert neighbour["other_commitments"] == 1


def test_role_access_is_enforced():
    client, pid, _, (first, _) = setup_overload()
    # Another relative added as primary contact has the same oversight rights.
    relative, relative_email, _ = account("PRIMARY_CONTACT", "Second relative")
    assert client.post(f"/api/v1/patients/{pid}/care-team", headers=H, json={"email": relative_email, "team_role": "PRIMARY_CONTACT"}).status_code == 201
    assert relative.get(f"/api/v1/patients/{pid}/workload-balance").json()["permissions"]["can_apply"] is True
    professional, _, _ = join_as_professional(client, pid)
    assert professional.get(f"/api/v1/patients/{pid}/workload-balance").status_code == 403
    assert professional.post(f"/api/v1/patients/{pid}/workload-balance/apply", headers=H, json={"activity_id": first, "from_caregiver_id": str(uuid.uuid4()), "to_caregiver_id": str(uuid.uuid4())}).status_code == 403
    outsider, _, _ = account("PRIMARY_CONTACT", "Outsider")
    assert outsider.get(f"/api/v1/patients/{pid}/workload-balance").status_code == 403
    assert client.get(f"/api/v1/patients/{pid}/workload-balance", params={"days": 60}).status_code == 422
    assert TestClient(app).get(f"/api/v1/patients/{pid}/workload-balance").status_code == 401


def test_caretaker_role_is_excluded_and_linked_receiver_is_notified():
    client, pid, people, (first, _) = setup_overload()
    linked_id, caretaker_client = caretaker(client, pid, "Linked Caretaker", caps=("TRANSPORT",))
    assert caretaker_client.get(f"/api/v1/patients/{pid}/workload-balance").status_code == 403
    applied = client.post(f"/api/v1/patients/{pid}/workload-balance/apply", headers=H, json={"activity_id": first, "from_caregiver_id": people["busy"], "to_caregiver_id": linked_id})
    assert applied.status_code == 200
    inbox = caretaker_client.get("/api/v1/notifications").json()["items"]
    assert any(n["title"] == "Can you take this care task?" and n["requires_ack"] and n["channel"] == "INBOX" for n in inbox)
    # If the new caregiver declines, the previous caregiver is still the confirmed backup, so cover is not silently lost.
    assert caretaker_client.post(f"/api/v1/assignments/{applied.json()['assignment']['id']}/decline", headers=H, json={"reason": "Unavailable"}).status_code == 200
    plan = client.get(f"/api/v1/activities/{first}").json()["assignments"]
    assert any(a["role"] == "BACKUP" and a["status"] == "CONFIRMED" and a["caregiver_id"] == people["busy"] for a in plan)
