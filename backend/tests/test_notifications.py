import uuid
from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.clock import now
from app.core.db import SessionLocal
from app.models import CareActivity, Notification
from app.services.reminders import run_reminders
from tests.helpers import H, caretaker, join_as_professional, primary_contact_with_patient

ZONE = ZoneInfo("Asia/Kolkata")


def setup(caps=("MEDICATION_ASSIST", "APPOINTMENT_ESCORT")):
    coord, pid = primary_contact_with_patient("Notified patient")
    main_id, main = caretaker(coord, pid, "Main Caretaker", caps=caps, day=1)
    assert coord.put(f"/api/v1/patients/{pid}/main-caretaker", headers=H, json={"caregiver_id": main_id}).status_code == 200
    doctor, _, _ = join_as_professional(coord, pid)
    return coord, pid, doctor, main, main_id


def titles(client, unread_only=False):
    data = client.get("/api/v1/notifications", params={"unread": unread_only}).json()
    return [n["title"] for n in data["items"]]


def tomorrow():
    return now().astimezone(ZONE).date() + timedelta(days=1)


def prescribe(doctor, pid, medicine="Metformin", times=("08:00",)):
    return doctor.post(f"/api/v1/patients/{pid}/prescriptions", headers=H,
                       json={"medicine": medicine, "dose": "500 mg", "instructions": "", "times": list(times), "start_date": tomorrow().isoformat(), "end_date": tomorrow().isoformat()})


def test_a_prescription_alerts_the_family_and_the_caretaker_but_not_the_doctor_who_did_it():
    coord, pid, doctor, main, _ = setup()
    assert prescribe(doctor, pid).status_code == 201
    assert any(t.startswith("New medicine: Metformin") for t in titles(coord))
    assert any(t.startswith("New medicine: Metformin") for t in titles(main))
    assert not any(t.startswith("New medicine") for t in titles(doctor))
    item = next(n for n in coord.get("/api/v1/notifications").json()["items"] if n["title"].startswith("New medicine"))
    assert item["link"] == f"/care-plan?patient={pid}" and item["kind"] == "DECISION" and item["created_at"].endswith("+00:00")


def test_changing_and_stopping_a_medicine_alerts_people():
    coord, pid, doctor, main, _ = setup()
    made = prescribe(doctor, pid).json()
    assert doctor.patch(f"/api/v1/prescriptions/{made['id']}", headers=H, json={"times": ["09:00"]}).status_code == 200
    assert doctor.post(f"/api/v1/prescriptions/{made['id']}/stop", headers=H, json={"reason": "Side effects"}).status_code == 200
    seen = titles(coord)
    assert "Medicine changed: Metformin" in seen and "Medicine stopped: Metformin" in seen


def test_booking_and_cancelling_an_appointment_alerts_the_family_and_the_escort():
    coord, pid, doctor, main, _ = setup()
    start = (now() + timedelta(days=2)).replace(microsecond=0)
    made = doctor.post(f"/api/v1/patients/{pid}/appointments", headers=H, json={"title": "Eye check-up", "start": start.isoformat(), "duration_minutes": 30, "location": "Vision Care", "needs_escort": True})
    assert made.status_code == 201
    assert "Appointment: Eye check-up" in titles(coord) and "You are escorting: Eye check-up" in titles(main)
    assert doctor.post(f"/api/v1/appointments/{made.json()['id']}/cancel", headers=H, json={"reason": "Doctor away"}).status_code == 200
    assert "Appointment cancelled: Eye check-up" in titles(coord) and "Appointment cancelled: Eye check-up" in titles(main)


def test_marking_a_dose_done_and_taking_leave_alert_the_family():
    coord, pid, doctor, main, main_id = setup()
    soon = now().astimezone(ZONE) + timedelta(minutes=45)
    assert doctor.post(f"/api/v1/patients/{pid}/prescriptions", headers=H, json={"medicine": "Aspirin", "dose": "75 mg", "instructions": "", "times": [soon.strftime("%H:%M")],
                                                                              "start_date": soon.date().isoformat(), "end_date": soon.date().isoformat()}).status_code == 201
    dose = next(a for a in main.get(f"/api/v1/patients/{pid}/activities", params={"limit": 100}).json()["items"] if a["title"].startswith("Aspirin"))
    assert main.post(f"/api/v1/activities/{dose['id']}/complete", headers=H, json={}).status_code == 200
    assert "Done: Aspirin 75 mg" in titles(coord) and "Done: Aspirin 75 mg" not in titles(main)
    away_from, away_to = (now() + timedelta(days=5)), (now() + timedelta(days=5, hours=3))
    assert main.post(f"/api/v1/caregivers/{main_id}/availability-overrides", headers=H,
                     json={"start_at": away_from.isoformat(), "end_at": away_to.isoformat(), "status": "UNAVAILABLE", "reason": "PERSONAL"}).status_code == 201
    assert "Main Caretaker is unavailable" in titles(coord)


def test_team_changes_and_a_new_care_code_alert_the_right_people():
    coord, pid = primary_contact_with_patient("Team patient")
    second, _ = primary_contact_with_patient("Someone else's patient")  # a second family account to be invited
    from tests.helpers import account
    helper_client, helper_email, _ = account("CARETAKER", "Invited Helper")
    assert coord.post(f"/api/v1/patients/{pid}/care-team", headers=H, json={"email": helper_email, "team_role": "CARETAKER"}).status_code == 201
    assert any(t.startswith("You were added to") for t in titles(helper_client))
    assert coord.post(f"/api/v1/patients/{pid}/care-code/regenerate", headers=H).status_code == 200
    members = coord.get(f"/api/v1/patients/{pid}/care-team").json()["items"]
    mine = next(m for m in members if m["team_role"] == "CARETAKER")
    assert coord.delete(f"/api/v1/patients/{pid}/care-team/{mine['id']}", headers=H).status_code == 204
    assert any(t.startswith("You were removed from") for t in titles(helper_client))


def test_reminders_arrive_once_and_only_when_they_are_due():
    coord, pid, doctor, main, main_id = setup()
    soon = now().astimezone(ZONE) + timedelta(minutes=40)
    assert doctor.post(f"/api/v1/patients/{pid}/prescriptions", headers=H, json={"medicine": "Remindol", "dose": "1 tab", "instructions": "With water", "times": [soon.strftime("%H:%M")],
                                                                              "start_date": soon.date().isoformat(), "end_date": soon.date().isoformat()}).status_code == 201
    def due_reminders():
        return [n for n in main.get("/api/v1/notifications").json()["items"] if n["title"].startswith("Due at") and "Remindol" in n["title"]]
    with SessionLocal() as db:
        run_reminders(db, now()); db.commit()
    assert due_reminders() == []  # forty minutes away: too early
    with SessionLocal() as db:
        run_reminders(db, now() + timedelta(minutes=30)); db.commit()
        run_reminders(db, now() + timedelta(minutes=31)); db.commit()
    assert len(due_reminders()) == 1  # due now, and sent only once however often the scheduler runs
    reminder = due_reminders()[0]
    assert reminder["kind"] == "REMINDER" and reminder["link"] == "/my-day" and "Remindol" in reminder["title"]


def test_appointment_reminders_and_a_warning_when_nobody_is_confirmed():
    coord, pid, doctor, main, _ = setup()
    start = (now() + timedelta(hours=20)).replace(microsecond=0)
    made = doctor.post(f"/api/v1/patients/{pid}/appointments", headers=H, json={"title": "Review visit", "start": start.isoformat(), "duration_minutes": 30, "location": "Clinic", "needs_escort": True})
    assert made.status_code == 201
    with SessionLocal() as db:
        run_reminders(db, now()); db.commit()
    assert any(t.startswith("Within a day: Review visit") for t in titles(coord)) and any(t.startswith("Within a day: Review visit") for t in titles(main))
    # a visit nobody can escort: the family is warned early enough to act
    other, pid2 = primary_contact_with_patient("Unescorted patient")
    doc2, _, _ = join_as_professional(other, pid2)
    assert doc2.post(f"/api/v1/patients/{pid2}/appointments", headers=H, json={"title": "No escort visit", "start": (now() + timedelta(hours=5)).isoformat(), "duration_minutes": 30, "location": "Clinic", "needs_escort": True}).status_code == 201
    with SessionLocal() as db:
        run_reminders(db, now()); db.commit()
    warned = [n for n in other.get("/api/v1/notifications").json()["items"] if n["title"].startswith("No one confirmed yet")]
    assert warned and warned[0]["severity"] == "HIGH"


def test_marking_everything_read_clears_the_unread_count():
    coord, pid, doctor, main, _ = setup()
    prescribe(doctor, pid)
    assert coord.get("/api/v1/notifications").json()["unread_count"] >= 1
    assert coord.post("/api/v1/notifications/read-all", headers=H).status_code == 200
    assert coord.get("/api/v1/notifications").json()["unread_count"] == 0
