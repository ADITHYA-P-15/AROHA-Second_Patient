import uuid
from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.clock import now
from app.core.db import SessionLocal
from app.models import CareActivity, Notification
from app.services.care_status import mark_missed
from app.services.workload_balancer import _aware
from tests.helpers import H, account, caretaker, join_as_professional, primary_contact_with_patient

ZONE = ZoneInfo("Asia/Kolkata")


def setup():
    coord, pid = primary_contact_with_patient("Synthetic feed patient")
    main_id, main = caretaker(coord, pid, "Main Caretaker", caps=("MEDICATION_ASSIST", "APPOINTMENT_ESCORT"), day=1)
    assert coord.put(f"/api/v1/patients/{pid}/main-caretaker", headers=H, json={"caregiver_id": main_id}).status_code == 200
    doctor, _, _ = join_as_professional(coord, pid)
    return coord, pid, doctor, main, main_id


def tomorrow():
    return now().astimezone(ZONE).date() + timedelta(days=1)


def doses(client, pid):
    return [a for a in client.get(f"/api/v1/patients/{pid}/activities", params={"limit": 100}).json()["items"] if a["source"] == "PRESCRIPTION"]


def test_prescription_feed_generates_doses_for_the_main_caretaker():
    coord, pid, doctor, main, main_id = setup()
    body = {"medicine": "Metformin", "dose": "500 mg", "instructions": "After food", "times": ["20:00", "08:00"], "start_date": tomorrow().isoformat(), "end_date": (tomorrow() + timedelta(days=1)).isoformat()}
    created = doctor.post(f"/api/v1/patients/{pid}/prescriptions", headers=H, json=body)
    assert created.status_code == 201 and created.json()["doses_created"] == 4 and created.json()["times"] == ["08:00", "20:00"]
    items = doses(coord, pid)
    assert len(items) == 4 and all(a["title"] == "Metformin 500 mg" and a["care_status"] == "PENDING" and a["category"] == "MEDICATION" for a in items)
    assert all([x["caregiver_id"] for x in a["assignments"] if x["status"] == "CONFIRMED"] == [main_id] for a in items)
    first = min(items, key=lambda a: a["scheduled_start"])
    assert _aware_iso(first["due_by"]) - _aware_iso(first["scheduled_start"]) == timedelta(minutes=60)
    # The caretaker sees them in their own plan; routine doses do not use up their single daily task slot.
    assert len(doses(main, pid)) == 4
    balance = coord.get(f"/api/v1/patients/{pid}/workload-balance").json()
    assert next(c for c in balance["caregivers"] if c["caregiver_id"] == main_id)["status"] != "OVERLOADED"
    # Only professionals on the team prescribe; times are validated.
    assert coord.post(f"/api/v1/patients/{pid}/prescriptions", headers=H, json=body).status_code == 403
    assert main.post(f"/api/v1/patients/{pid}/prescriptions", headers=H, json=body).status_code == 403
    assert doctor.post(f"/api/v1/patients/{pid}/prescriptions", headers=H, json={**body, "times": ["8am"]}).status_code == 422
    assert account("PROFESSIONAL")[0].post(f"/api/v1/patients/{pid}/prescriptions", headers=H, json=body).status_code == 403


def test_changing_or_stopping_a_prescription_updates_future_doses():
    coord, pid, doctor, _, _ = setup()
    p = doctor.post(f"/api/v1/patients/{pid}/prescriptions", headers=H, json={"medicine": "Amlodipine", "dose": "5 mg", "times": ["09:00"], "start_date": tomorrow().isoformat(), "end_date": (tomorrow() + timedelta(days=2)).isoformat()}).json()
    changed = doctor.patch(f"/api/v1/prescriptions/{p['id']}", headers=H, json={"times": ["09:00", "21:00"], "dose": "10 mg"})
    assert changed.status_code == 200 and changed.json()["doses_cancelled"] == 3 and changed.json()["doses_created"] == 6
    pending = [a for a in doses(coord, pid) if a["care_status"] == "PENDING"]
    assert len(pending) == 6 and {a["title"] for a in pending} == {"Amlodipine 10 mg"}
    stopped = doctor.post(f"/api/v1/prescriptions/{p['id']}/stop", headers=H, json={"reason": "Blood pressure controlled"})
    assert stopped.status_code == 200 and stopped.json()["status"] == "STOPPED" and stopped.json()["doses_cancelled"] == 6
    assert not [a for a in doses(coord, pid) if a["care_status"] == "PENDING"]
    assert coord.get(f"/api/v1/patients/{pid}/prescriptions").json()["items"] == []
    assert len(coord.get(f"/api/v1/patients/{pid}/prescriptions", params={"status": "all"}).json()["items"]) == 1


def test_status_from_the_clock_missed_then_completed_late():
    coord, pid, doctor, main, _ = setup()
    doctor.post(f"/api/v1/patients/{pid}/prescriptions", headers=H, json={"medicine": "Aspirin", "dose": "75 mg", "times": ["14:00"], "start_date": tomorrow().isoformat(), "end_date": tomorrow().isoformat()})
    [dose] = doses(coord, pid)
    due_by = _aware_iso(dose["due_by"])
    with SessionLocal() as db:
        assert mark_missed(db, due_by - timedelta(minutes=1), patient_id=uuid.UUID(pid)) == 0
        assert mark_missed(db, due_by + timedelta(minutes=1), patient_id=uuid.UUID(pid)) == 1
        db.commit()
        alerts = db.scalars(select(Notification).where(Notification.patient_id == uuid.UUID(pid), Notification.title == "Missed dose: Aspirin 75 mg")).all()
        assert len(alerts) == 2  # the assigned caretaker and the primary contact
        assert mark_missed(db, due_by + timedelta(minutes=5), patient_id=uuid.UUID(pid)) == 0  # idempotent
    after = next(a for a in doses(coord, pid) if a["id"] == dose["id"])
    assert after["care_status"] == "MISSED"
    outsider_caretaker = caretaker(coord, pid, "Other Caretaker", caps=("MEDICATION_ASSIST",))[1]
    assert outsider_caretaker.post(f"/api/v1/activities/{dose['id']}/complete", headers=H, json={}).status_code == 403
    done = main.post(f"/api/v1/activities/{dose['id']}/complete", headers=H, json={})
    assert done.status_code == 200 and done.json() == {"status": "completed", "care_status": "COMPLETED", "completed_late": True}
    adherence = doctor.get(f"/api/v1/patients/{pid}/adherence", params={"days": 7}).json()
    assert adherence["totals"]["due"] == 0  # the dose is due tomorrow, so it is not yet in the past-week window
    assert main.get(f"/api/v1/patients/{pid}/adherence").status_code == 403


def test_appointment_feed_needs_an_escort_and_can_be_cancelled_by_the_hospital():
    coord, pid, doctor, main, main_id = setup()
    start = (now() + timedelta(days=2)).astimezone(ZONE).replace(hour=11, minute=0, second=0, microsecond=0)
    made = doctor.post(f"/api/v1/patients/{pid}/appointments", headers=H, json={"title": "Cardiology review", "start": start.isoformat(), "duration_minutes": 45, "location": "City Hospital, OPD 3", "notes": "Bring the last ECG"})
    assert made.status_code == 201 and made.json()["status"] == "PENDING" and made.json()["needs_escort"] is True
    assert _aware_iso(made.json()["start"]) == start  # serialized with an offset, never as naive local time
    activity = coord.get(f"/api/v1/activities/{made.json()['id']}").json()
    assert activity["category"] == "APPOINTMENT" and activity["buffer_before_min"] == 30 and activity["required_support"] == ["APPOINTMENT_ESCORT"]
    assert [x["caregiver_id"] for x in activity["assignments"] if x["status"] == "CONFIRMED"] == [main_id]
    assert [a["title"] for a in main.get(f"/api/v1/patients/{pid}/appointments").json()["items"]] == ["Cardiology review"]
    assert coord.post(f"/api/v1/patients/{pid}/appointments", headers=H, json={"title": "x", "start": start.isoformat()}).status_code == 403
    assert doctor.post(f"/api/v1/patients/{pid}/appointments", headers=H, json={"title": "Past", "start": (now() - timedelta(hours=1)).isoformat()}).status_code == 422
    cancelled = doctor.post(f"/api/v1/appointments/{made.json()['id']}/cancel", headers=H, json={"reason": "Doctor on leave"})
    assert cancelled.json()["status"] == "CANCELLED"
    assert main.get(f"/api/v1/patients/{pid}/appointments").json()["items"] == []


def test_adherence_counts_on_time_late_and_missed():
    coord, pid, doctor, main, _ = setup()
    doctor.post(f"/api/v1/patients/{pid}/prescriptions", headers=H, json={"medicine": "Vitamin D", "dose": "1 tab", "times": ["07:00", "19:00"], "start_date": tomorrow().isoformat(), "end_date": tomorrow().isoformat()})
    morning, evening = sorted(doses(coord, pid), key=lambda a: a["scheduled_start"])
    with SessionLocal() as db:
        for item, shift in ((morning, -2), (evening, -1)):
            row = db.get(CareActivity, uuid.UUID(item["id"]))
            row.scheduled_start = _aware(row.scheduled_start) + timedelta(days=shift); row.scheduled_end = _aware(row.scheduled_end) + timedelta(days=shift); row.deadline = _aware(row.deadline) + timedelta(days=shift)
        db.commit()
        mark_missed(db); db.commit()
    assert main.post(f"/api/v1/activities/{evening['id']}/complete", headers=H, json={}).json()["completed_late"] is True
    report = coord.get(f"/api/v1/patients/{pid}/adherence", params={"days": 7}).json()
    assert report["totals"] == {"due": 2, "on_time": 0, "late": 1, "missed": 1, "pending": 0} and report["medicines"][0]["medicine"] == "Vitamin D"


def _aware_iso(value):
    from datetime import datetime
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
