"""Regressions for the four-role pivot review."""
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.clock import now
from app.core.db import SessionLocal
from app.models import CareAssignment, Notification
from app.services.care_status import mark_missed
from tests.helpers import H, account, caretaker, join_as_professional, primary_contact_with_patient

ZONE = ZoneInfo("Asia/Kolkata")


def iso(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def base():
    coord, pid = primary_contact_with_patient()
    main_id, main = caretaker(coord, pid, "Main", caps=("MEDICATION_ASSIST", "APPOINTMENT_ESCORT"))
    coord.put(f"/api/v1/patients/{pid}/main-caretaker", headers=H, json={"caregiver_id": main_id})
    doctor, _, doctor_user = join_as_professional(coord, pid)
    return coord, pid, main, main_id, doctor, doctor_user


def test_appointment_is_not_missed_while_it_is_happening():
    coord, pid, main, _, doctor, _ = base()
    start = (now() + timedelta(days=1)).astimezone(ZONE).replace(hour=11, minute=0, second=0, microsecond=0)
    made = doctor.post(f"/api/v1/patients/{pid}/appointments", headers=H, json={"title": "Scan", "start": start.isoformat(), "duration_minutes": 45}).json()
    with SessionLocal() as db:
        assert mark_missed(db, start + timedelta(minutes=50), patient_id=uuid.UUID(pid)) == 0
        assert mark_missed(db, start + timedelta(minutes=45 + 61), patient_id=uuid.UUID(pid)) == 1
        db.rollback()
    assert main.post(f"/api/v1/activities/{made['id']}/complete", headers=H, json={}).status_code == 409  # too early: tomorrow


def test_removing_a_caretaker_releases_their_tasks_and_stops_their_alerts():
    coord, pid, main, main_id, doctor, _ = base()
    day = (now() + timedelta(days=1)).astimezone(ZONE).date().isoformat()
    doctor.post(f"/api/v1/patients/{pid}/prescriptions", headers=H, json={"medicine": "Probe", "dose": "1", "times": ["10:00"], "start_date": day, "end_date": day})
    member = next(m for m in coord.get(f"/api/v1/patients/{pid}/care-team").json()["items"] if m["team_role"] == "CARETAKER")
    assert coord.delete(f"/api/v1/patients/{pid}/care-team/{member['id']}", headers=H).status_code == 204
    with SessionLocal() as db:
        assert not db.scalars(select(CareAssignment).where(CareAssignment.caregiver_id == uuid.UUID(main_id), CareAssignment.status == "CONFIRMED")).all()
    history = coord.get(f"/api/v1/patients/{pid}/history").json()["items"]
    assert any("1 upcoming tasks released for cover" in h["summary"] for h in history)


def test_removed_professional_cannot_rejoin_with_the_old_id_and_ids_can_be_regenerated():
    coord, pid, _, _, doctor, doctor_user = base()
    old = coord.get(f"/api/v1/patients/{pid}").json()["care_code"]
    member = next(m for m in coord.get(f"/api/v1/patients/{pid}/care-team").json()["items"] if m["user_id"] == doctor_user)
    assert coord.delete(f"/api/v1/patients/{pid}/care-team/{member['id']}", headers=H).status_code == 204
    new = coord.get(f"/api/v1/patients/{pid}").json()["care_code"]
    assert new != old
    assert doctor.post("/api/v1/patients/join", headers=H, json={"care_code": old, "birth_year": 1950}).status_code == 404
    regenerated = coord.post(f"/api/v1/patients/{pid}/care-code/regenerate", headers=H).json()["care_code"]
    assert regenerated not in (old, new)
    assert doctor.post(f"/api/v1/patients/{pid}/care-code/regenerate", headers=H).status_code == 403


def test_registrant_and_patient_login_cannot_be_removed_by_another_relative():
    coord, pid = primary_contact_with_patient()
    relative, email, _ = account("PRIMARY_CONTACT", "Relative")
    coord.post(f"/api/v1/patients/{pid}/care-team", headers=H, json={"email": email, "team_role": "PRIMARY_CONTACT"})
    registrant = next(m for m in coord.get(f"/api/v1/patients/{pid}/care-team").json()["items"] if m["is_primary_coordinator"])
    blocked = relative.delete(f"/api/v1/patients/{pid}/care-team/{registrant['id']}", headers=H)
    assert blocked.status_code == 409 and "can only leave by themselves" in blocked.json()["error"]["message"]


def test_instruction_only_edit_keeps_doses_and_caretakers_and_cancel_releases_assignments():
    coord, pid, main, main_id, doctor, _ = base()
    day = (now() + timedelta(days=1)).astimezone(ZONE).date().isoformat()
    p = doctor.post(f"/api/v1/patients/{pid}/prescriptions", headers=H, json={"medicine": "Keep", "dose": "1", "times": ["10:00"], "start_date": day, "end_date": day}).json()
    edited = doctor.patch(f"/api/v1/prescriptions/{p['id']}", headers=H, json={"instructions": "With water", "times": ["10:00"]}).json()
    assert edited["doses_cancelled"] == 0 and edited["doses_created"] == 0
    dose = next(a for a in coord.get(f"/api/v1/patients/{pid}/activities").json()["items"] if a["source"] == "PRESCRIPTION")
    assert dose["description"] == "With water" and [a["caregiver_id"] for a in dose["assignments"] if a["status"] == "CONFIRMED"] == [main_id]
    start = (now() + timedelta(days=2)).astimezone(ZONE).replace(hour=11, minute=0, second=0, microsecond=0)
    appt = doctor.post(f"/api/v1/patients/{pid}/appointments", headers=H, json={"title": "Follow-up", "start": start.isoformat()}).json()
    other_id, other = caretaker(coord, pid, "Other caretaker", caps=("APPOINTMENT_ESCORT",))
    assert other.get(f"/api/v1/patients/{pid}/appointments").json()["items"] == []  # not theirs
    assert [a["title"] for a in main.get(f"/api/v1/patients/{pid}/appointments").json()["items"]] == ["Follow-up"]
    doctor.post(f"/api/v1/appointments/{appt['id']}/cancel", headers=H, json={})
    with SessionLocal() as db:
        assert not db.scalars(select(CareAssignment).where(CareAssignment.activity_id == uuid.UUID(appt["id"]), CareAssignment.status == "CONFIRMED")).all()


def test_professionals_cannot_lower_incidents_they_cannot_see_and_level_zero_is_safe():
    coord, pid, _, _, doctor, _ = base()
    low = coord.post(f"/api/v1/patients/{pid}/messages", headers=H, json={"body": "I need water", "channel": "TEXT", "on_behalf": True}).json()
    assert doctor.post(f"/api/v1/incidents/{low['id']}/lower", headers=H, json={"to_level": 0, "reason": "x"}).status_code == 403
    lowered = coord.post(f"/api/v1/incidents/{low['id']}/lower", headers=H, json={"to_level": 0, "reason": "Information only"})
    assert lowered.status_code == 200 and lowered.json()["current_deadline_at"] is None


def test_birth_year_is_required():
    coord, _, _ = account("PRIMARY_CONTACT")
    assert coord.post("/api/v1/patients", headers=H, json={"name": "No year"}).status_code == 422


def test_cover_needed_alerts_are_summarised_not_one_per_dose():
    coord, pid, _, main_id, doctor, _ = base()
    coord.put(f"/api/v1/caregivers/{main_id}/schedule", headers=H, json={"windows": [{"weekday": d, "start_min": 480, "end_min": 1200} for d in range(7)]})
    day = (now() + timedelta(days=1)).astimezone(ZONE).date().isoformat()
    doctor.post(f"/api/v1/patients/{pid}/prescriptions", headers=H, json={"medicine": "Night", "dose": "1", "times": ["22:00", "23:00"], "start_date": day, "end_date": day})
    from app.services.auto_cover import run_auto_coordination
    with SessionLocal() as db:
        run_auto_coordination(db); db.commit()
        alerts = db.scalars(select(Notification).where(Notification.patient_id == uuid.UUID(pid), Notification.title == "Cover needed")).all()
        assert len(alerts) == 1 and "upcoming activities need cover" in alerts[0].body


def test_early_morning_ist_activities_stay_in_their_local_day_on_sqlite():
    from app.services.workload_balancer import build_snapshot, horizon
    coord, pid = primary_contact_with_patient()
    start = (now() + timedelta(days=2)).astimezone(ZONE).replace(hour=0, minute=30, second=0, microsecond=0)  # 19:00 UTC the day before
    made = coord.post(f"/api/v1/patients/{pid}/activities", headers=H, json={"title": "Night dose", "category": "MEDICATION", "scheduled_start": start.isoformat(), "scheduled_end": (start + timedelta(minutes=15)).isoformat(), "required_support": ["MEDICATION_ASSIST"]}).json()
    with SessionLocal() as db:
        day_start, day_end = horizon(start, 1)
        assert made["id"] in {str(a["id"]) for a in build_snapshot(db, uuid.UUID(pid), day_start, day_end)["activities"]}
