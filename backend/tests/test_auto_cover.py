import uuid
from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.clock import now
from app.core.db import SessionLocal
from app.models import CareAssignment, CoverRequest, Notification
from app.services.auto_cover import run_auto_coordination
from tests.helpers import H, caretaker, join_as_professional, primary_contact_with_patient

ZONE = ZoneInfo("Asia/Kolkata")


def day_at(days, hour):
    return (now().astimezone(ZONE) + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)


def test_leave_triggers_an_automatic_offer_and_the_replacement_accepts():
    coord, pid = primary_contact_with_patient()
    main_id, main = caretaker(coord, pid, "Main Caretaker", caps=("MEDICATION_ASSIST",))
    spare_id, spare = caretaker(coord, pid, "Spare Caretaker", caps=("MEDICATION_ASSIST",))
    coord.put(f"/api/v1/patients/{pid}/main-caretaker", headers=H, json={"caregiver_id": main_id})
    doctor, _, _ = join_as_professional(coord, pid)
    start = day_at(2, 9)
    doctor.post(f"/api/v1/patients/{pid}/prescriptions", headers=H, json={"medicine": "Thyroxine", "dose": "50 mcg", "times": ["09:00"], "start_date": start.date().isoformat(), "end_date": start.date().isoformat()})
    # The caretaker takes leave for that morning: no primary-contact tap is needed for the replacement to be asked.
    leave = main.post(f"/api/v1/caregivers/{main_id}/availability-overrides", headers=H, json={"start_at": day_at(2, 6).isoformat(), "end_at": day_at(2, 12).isoformat(), "status": "UNAVAILABLE", "reason": "PERSONAL", "note": "Leave"})
    assert leave.status_code == 201
    offers = spare.get("/api/v1/cover-offers/mine").json()["items"]
    assert len(offers) == 1 and offers[0]["activity"]["title"] == "Thyroxine 50 mcg"
    titles = [n["title"] for n in coord.get("/api/v1/notifications").json()["items"]]
    assert "Cover needed" not in titles  # the primary contact is not interrupted while someone can take it
    accepted = spare.post(f"/api/v1/cover-requests/{offers[0]['id']}/accept", headers=H, json={})
    assert accepted.status_code == 200 and accepted.json()["status"] == "COVERED"
    activity = coord.get(f"/api/v1/activities/{offers[0]['activity']['id']}").json()
    assert [a["caregiver_id"] for a in activity["assignments"] if a["status"] == "CONFIRMED" and a["role"] == "PRIMARY"] == [spare_id]


def test_unassigned_feed_activity_is_offered_and_primary_contact_hears_only_when_nobody_can():
    coord, pid = primary_contact_with_patient()
    escort_id, escort = caretaker(coord, pid, "Escort", caps=("APPOINTMENT_ESCORT",))
    doctor, _, _ = join_as_professional(coord, pid)  # no main caretaker: appointments start unassigned
    made = doctor.post(f"/api/v1/patients/{pid}/appointments", headers=H, json={"title": "Eye check", "start": day_at(2, 11).isoformat()}).json()
    with SessionLocal() as db:
        assert run_auto_coordination(db) >= 1; db.commit()
        assert run_auto_coordination(db) == 0; db.commit()  # idempotent
    assert [o["activity"]["id"] for o in escort.get("/api/v1/cover-offers/mine").json()["items"]] == [made["id"]]
    # A task nobody can do reaches the primary contact once.
    lonely = doctor.post(f"/api/v1/patients/{pid}/prescriptions", headers=H, json={"medicine": "Insulin", "dose": "10 units", "times": ["21:00"], "start_date": day_at(1, 0).date().isoformat(), "end_date": day_at(1, 0).date().isoformat()})
    assert lonely.status_code == 201
    with SessionLocal() as db:
        run_auto_coordination(db); db.commit()
        alerts = db.scalars(select(Notification).where(Notification.patient_id == uuid.UUID(pid), Notification.title == "Cover needed")).all()
        assert len(alerts) == 1 and "No one in the network can take this" in alerts[0].body
        assert db.scalar(select(CoverRequest.reason).where(CoverRequest.patient_id == uuid.UUID(pid), CoverRequest.status == "OPEN")) == "UNASSIGNED"


def test_overloaded_caretaker_is_relieved_automatically_with_standby():
    coord, pid = primary_contact_with_patient()
    busy_id, _ = caretaker(coord, pid, "Busy Caretaker", caps=("TRANSPORT",), day=1)
    free_id, free = caretaker(coord, pid, "Free Caretaker", caps=("TRANSPORT",))
    for hour in (9, 15):
        start = day_at(2, hour)
        aid = coord.post(f"/api/v1/patients/{pid}/activities", headers=H, json={"title": f"Ride {hour}", "category": "TRANSPORT", "scheduled_start": start.isoformat(), "scheduled_end": (start + timedelta(hours=1)).isoformat(), "required_support": ["TRANSPORT"]}).json()["id"]
        coord.post(f"/api/v1/activities/{aid}/assignments", headers=H, json={"caregiver_id": busy_id, "confirm_now": True})
    with SessionLocal() as db:
        assert run_auto_coordination(db) == 1; db.commit()
        awaiting = db.scalars(select(CareAssignment).where(CareAssignment.caregiver_id == uuid.UUID(free_id), CareAssignment.status == "AWAITING_CONFIRMATION")).all()
        standby = db.scalars(select(CareAssignment).where(CareAssignment.caregiver_id == uuid.UUID(busy_id), CareAssignment.role == "BACKUP", CareAssignment.status == "CONFIRMED")).all()
        assert len(awaiting) == 1 and len(standby) == 1
        assert run_auto_coordination(db) == 0; db.commit()  # overload resolved: nothing more to move
    assert any(n["title"] == "Can you take this care task?" for n in free.get("/api/v1/notifications").json()["items"])
    history = coord.get(f"/api/v1/patients/{pid}/history").json()["items"]
    assert any(h["summary"].startswith("Automatic: task moved from Busy Caretaker to Free Caretaker") for h in history)
