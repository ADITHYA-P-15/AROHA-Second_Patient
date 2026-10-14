import uuid
from datetime import timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.clock import now
from app.core.db import SessionLocal
from app.main import app
from app.models import CoverageFinding
from tests.helpers import account, caretaker, join_as_professional, primary_contact_with_patient
from app.services.workload_balancer import _aware
from app.services import coverage_planner as planner

H = {"X-Requested-With": "second-patient"}
ANYTIME = [{"weekday": d, "start_min": 0, "end_min": 1440} for d in range(7)]


def setup():
    coord, pid = primary_contact_with_patient("Synthetic forecast patient")

    def caregiver(name, caps=("TRANSPORT",)):
        return caretaker(coord, pid, name, caps=caps)[0]

    people = {"only": caregiver("Only Driver"), "other": caregiver("Errand Helper", ("SUPPLIES",))}
    return coord, pid, people


def task(coord, pid, title, hours_ahead, importance="HIGH", support=("TRANSPORT",)):
    start = (now() + timedelta(hours=hours_ahead)).astimezone(ZoneInfo("Asia/Kolkata")).replace(second=0, microsecond=0)
    body = {"title": title, "category": "TRANSPORT", "importance": importance, "scheduled_start": start.isoformat(), "scheduled_end": (start + timedelta(hours=1)).isoformat(), "required_support": list(support)}
    created = coord.post(f"/api/v1/patients/{pid}/activities", headers=H, json=body)
    assert created.status_code == 201
    return created.json()["id"], start


def tick(at=None):
    with SessionLocal() as db:
        planner.run_planner_tick(db, at); db.commit()


def rows_for(activity_id):
    with SessionLocal() as db:
        return [(r.kind, r.worst_kind, r.status, r.outcome) for r in db.scalars(select(CoverageFinding).where(CoverageFinding.activity_id == uuid.UUID(activity_id)))]


def test_forecast_flags_single_point_and_gap_then_logs_outcomes():
    coord, pid, people = setup()
    covered, _ = task(coord, pid, "Clinic ride", 60)
    assert coord.post(f"/api/v1/activities/{covered}/assignments", headers=H, json={"caregiver_id": people["only"], "confirm_now": True}).status_code == 201
    gap, gap_start = task(coord, pid, "Supplies run", 30, importance="LOW", support=("SUPPLIES",))

    data = coord.get(f"/api/v1/patients/{pid}/coverage-forecast").json()
    tick()
    kinds = {f["activity"]["id"]: f for f in data["findings"]}
    assert kinds[covered]["kind"] == "SINGLE_POINT" and "Only Driver is the only eligible person" in kinds[covered]["headline"]
    assert kinds[gap]["kind"] == "GAP" and kinds[gap]["eligible_alternatives"] == 1 and kinds[gap]["action"]["option"] == "FIND_COVER"
    assert data["horizons"]["3d"]["gaps"] == 1 and data["horizons"]["3d"]["single_points"] == 1
    assert data["permissions"]["can_act"] is True and kinds[covered]["holder"]["assignment_id"]

    # Securing a confirmed backup clears the single point before its deadline.
    helper = caretaker(coord, pid, "Second Driver")[0]
    backup = coord.post(f"/api/v1/activities/{covered}/assignments", headers=H, json={"caregiver_id": helper, "role": "BACKUP", "confirm_now": True})
    assert backup.status_code == 201
    after = coord.get(f"/api/v1/patients/{pid}/coverage-forecast").json()
    assert covered not in {f["activity"]["id"] for f in after["findings"]}
    tick()
    with SessionLocal() as db:
        row = db.scalar(select(CoverageFinding).where(CoverageFinding.activity_id == uuid.UUID(covered)))
        assert row.status == "RESOLVED" and row.outcome == "BEFORE_DEADLINE"
        # The gap was never fixed: once the task starts it counts as preventable uncovered.
        planner.record(db, uuid.UUID(pid), {"findings": []}, gap_start + timedelta(minutes=5)); db.commit()
        missed = db.scalar(select(CoverageFinding).where(CoverageFinding.activity_id == uuid.UUID(gap)))
        assert missed.status == "MISSED" and missed.outcome == "STARTED_UNCOVERED"
    metrics = coord.get(f"/api/v1/patients/{pid}/coverage-forecast/metrics").json()
    assert metrics["identified"] == 2 and metrics["preventable_uncovered"] == 1 and metrics["resolved_before_deadline"] == 1
    assert metrics["identified_before_deadline"] == 2 and metrics["gaps_prevented_pct"] == 0.0


def test_forecast_log_is_idempotent_and_access_is_scoped():
    coord, pid, people = setup()
    aid, _ = task(coord, pid, "Unassigned ride", 20)
    coord.get(f"/api/v1/patients/{pid}/coverage-forecast")
    assert rows_for(aid) == []  # viewing never writes; the scheduler owns the log
    tick(); tick()
    assert rows_for(aid) == [("GAP", "GAP", "OPEN", None)]
    relative, relative_email, _ = account("PRIMARY_CONTACT", "Second relative")
    assert coord.post(f"/api/v1/patients/{pid}/care-team", headers=H, json={"email": relative_email, "team_role": "PRIMARY_CONTACT"}).status_code == 201
    assert relative.get(f"/api/v1/patients/{pid}/coverage-forecast").json()["permissions"]["can_act"] is True
    nurse, _, _ = join_as_professional(coord, pid)
    denied = nurse.get(f"/api/v1/patients/{pid}/coverage-forecast")
    assert denied.status_code == 403 and "coverage forecast" in denied.json()["error"]["message"]
    outsider = TestClient(app)
    outsider.post("/api/v1/auth/register", headers=H, json={"name": "Outsider", "email": f"cp-out-{uuid.uuid4().hex}@example.com", "password": "SafePass!123"})
    assert outsider.get(f"/api/v1/patients/{pid}/coverage-forecast/metrics").status_code == 403


def test_review_regressions_kind_change_reschedule_and_late_fix():
    coord, pid, people = setup()
    # A gap that becomes "not confirmed" stays one open risk; it is missed if nobody confirms before it starts.
    aid, start = task(coord, pid, "Morning ride", 30, importance="LOW")  # 12 h lead, so it is flagged before its deadline
    tick()
    proposed = coord.post(f"/api/v1/activities/{aid}/assignments", headers=H, json={"caregiver_id": people["only"]}).json()["id"]
    tick()
    assert rows_for(aid) == [("UNCONFIRMED", "GAP", "OPEN", None)]
    tick(start + timedelta(minutes=1))
    assert rows_for(aid) == [("UNCONFIRMED", "GAP", "MISSED", "STARTED_UNCOVERED")]
    # Moving a flagged task beyond 7 days is not a prevented gap.
    far, _ = task(coord, pid, "Far ride", 40)
    tick()
    later = (now() + timedelta(days=10)).astimezone(ZoneInfo("Asia/Kolkata")).replace(second=0, microsecond=0)
    assert coord.patch(f"/api/v1/activities/{far}", headers=H, json={"scheduled_start": later.isoformat(), "scheduled_end": (later + timedelta(hours=1)).isoformat(), "deadline": (later + timedelta(hours=1)).isoformat()}).status_code == 200
    tick()
    assert rows_for(far) == [("GAP", "GAP", "CLOSED", "OUT_OF_SCOPE")]
    metrics = coord.get(f"/api/v1/patients/{pid}/coverage-forecast/metrics").json()
    assert metrics["gaps_closed_before_start"] == 0 and metrics["preventable_uncovered"] == 1 and metrics["out_of_scope"] == 1


def test_review_regressions_actions_lead_somewhere():
    coord, pid, people = setup()
    # A confirmed holder double-booked on two rides: both are gaps and Find cover opens a request (no 409).
    first, start = task(coord, pid, "Ride A", 50)
    second, _ = task(coord, pid, "Ride B", 50)
    for aid in (first, second):
        assert coord.post(f"/api/v1/activities/{aid}/assignments", headers=H, json={"caregiver_id": people["only"], "confirm_now": True}).status_code == 201
    kinds = {f["activity"]["id"]: f["kind"] for f in coord.get(f"/api/v1/patients/{pid}/coverage-forecast").json()["findings"]}
    assert kinds[first] == "GAP" and kinds[second] == "GAP"
    opened = coord.post(f"/api/v1/activities/{first}/cover-requests", headers=H, json={"only_if_uncovered": True})
    assert opened.status_code == 201
    # A confirmed holder working outside usual hours is not flagged as a gap.
    night, _ = task(coord, pid, "Night ride", 50)  # same slot as rides A/B, so Only Driver cannot be the alternative
    narrow = caretaker(coord, pid, "Day Driver", windows=[])[0]
    assert coord.post(f"/api/v1/activities/{night}/assignments", headers=H, json={"caregiver_id": narrow, "confirm_now": True}).status_code == 201
    finding = next(f for f in coord.get(f"/api/v1/patients/{pid}/coverage-forecast").json()["findings"] if f["activity"]["id"] == night)
    assert finding["kind"] == "SINGLE_POINT"  # covered; others are double-booked or lack the skill
    # Asking someone to stand by shows "waiting" and cannot be repeated.
    standby = caretaker(coord, pid, "Weekend Helper", windows=[])[0]
    after = next(f for f in coord.get(f"/api/v1/patients/{pid}/coverage-forecast").json()["findings"] if f["activity"]["id"] == night)
    assert [n["name"] for n in after["near_miss"]] == ["Weekend Helper"]
    asked = coord.post(f"/api/v1/activities/{night}/assignments", headers=H, json={"caregiver_id": standby, "role": "BACKUP"})
    assert asked.status_code == 201
    assert coord.post(f"/api/v1/activities/{night}/assignments", headers=H, json={"caregiver_id": standby, "role": "BACKUP"}).status_code == 409
    waiting = next(f for f in coord.get(f"/api/v1/patients/{pid}/coverage-forecast").json()["findings"] if f["activity"]["id"] == night)
    assert waiting["near_miss"] == [] and waiting["backup_requested"][0]["name"] == "Weekend Helper" and waiting["suggestion"].startswith("Waiting for Weekend Helper")
    coord.post(f"/api/v1/assignments/{asked.json()['id']}/request-confirmation", headers=H, json={})
    assert coord.post(f"/api/v1/assignments/{asked.json()['id']}/confirm", headers=H, json={}).status_code == 200
    assert night not in {f["activity"]["id"] for f in coord.get(f"/api/v1/patients/{pid}/coverage-forecast").json()["findings"]}
