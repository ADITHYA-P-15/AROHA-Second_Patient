"""Task check-ins: who may check in, on time vs late, the NO_CHECKIN cover search, the reliability metric, and the migration chain."""
import json
import os
import subprocess
import sys
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, inspect, select

from app.core import checkin_policy as cp
from app.core.clock import now
from app.core.config import settings
from app.core.db import SessionLocal
from app.models import CareActivity, CareAssignment, CoverRequest, Patient, ReputationSnapshot, TaskCheckIn
from app.services import checkins, reputation
from tests.helpers import H, account, caretaker, primary_contact_with_patient

BACKEND = Path(__file__).resolve().parents[1]


def task(pid, cid, start_in_min, category="APPOINTMENT", minutes=60, status="SCHEDULED", importance="HIGH"):
    with SessionLocal() as db:
        creator = db.get(Patient, uuid.UUID(pid)).created_by
        start = now() + timedelta(minutes=start_in_min)
        a = CareActivity(patient_id=uuid.UUID(pid), title=f"Fictional {category.lower()}", category=category, scheduled_start=start, scheduled_end=start + timedelta(minutes=minutes),
                         importance=importance, requires_caregiver=True, lifecycle_status=status, completed_at=start if status == "COMPLETED" else None, created_by=creator)
        db.add(a); db.flush()
        db.add(CareAssignment(activity_id=a.id, caregiver_id=uuid.UUID(cid), role="PRIMARY", status="CONFIRMED", assigned_by=creator))
        db.commit()
        return str(a.id)


def team():
    coord, pid = primary_contact_with_patient()
    cid, carer = caretaker(coord, pid, name="Checking caretaker", caps=("APPOINTMENT_ESCORT", "TRANSPORT"))
    return coord, pid, cid, carer


def record(aid, cid, minutes_after_start, status):
    with SessionLocal() as db:
        a = db.get(CareActivity, uuid.UUID(aid))
        db.add(TaskCheckIn(activity_id=a.id, caregiver_id=uuid.UUID(cid), checked_in_at=a.scheduled_start + timedelta(minutes=minutes_after_start), status=status,
                           minutes_late=max(0, minutes_after_start) if status == "LATE" else 0))
        db.commit()


# --- policy ------------------------------------------------------------------------------------------------------------

def test_policy_defaults_and_validation():
    p = cp.build("")
    assert p["grace_min"] == 15 and p["missing_after_min"] == 20 and "APPOINTMENT" in p["categories"] and "MEDICATION" not in p["categories"]
    assert cp.build('{"grace_min": 5}')["grace_min"] == 5
    for bad in ('{"grace_min": -1}', '{"categories": ["NAPS"]}', '{"grace_min": 30, "missing_after_min": 10}', '{"surprise": 1}', '{oops', '[1]', '{"grace_min": true}'):
        with pytest.raises(cp.PolicyError): cp.build(bad)


def test_an_invalid_checkin_policy_stops_start_up(tmp_path):
    env = {**os.environ, "CHECKIN_POLICY": '{"grace_min": "soon"}', "DATABASE_URL": f"sqlite:///{(tmp_path / 'c.db').as_posix()}", "SEED_DEMO": "false"}
    out = subprocess.run([sys.executable, "-c", "import app.main"], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode != 0 and "Invalid CHECKIN_POLICY" in out.stderr


# --- checking in -------------------------------------------------------------------------------------------------------

def test_only_the_confirmed_caretaker_checks_in_within_the_window():
    coord, pid, cid, carer = team()
    other_cid, other = caretaker(coord, pid, name="Other caretaker")
    early = task(pid, cid, 120)
    assert carer.post(f"/api/v1/activities/{early}/check-in", headers=H).status_code == 409  # opens 60 min before
    soon = task(pid, cid, 30)
    assert other.post(f"/api/v1/activities/{soon}/check-in", headers=H).status_code == 403
    assert coord.post(f"/api/v1/activities/{soon}/check-in", headers=H).status_code == 403
    outsider, *_ = account("CARETAKER")
    assert outsider.post(f"/api/v1/activities/{soon}/check-in", headers=H).status_code == 403
    made = carer.post(f"/api/v1/activities/{soon}/check-in", headers=H)
    assert made.status_code == 201 and made.json()["status"] == "ON_TIME" and made.json()["minutes_late"] == 0
    assert carer.post(f"/api/v1/activities/{soon}/check-in", headers=H).status_code == 409
    late = task(pid, cid, -25)
    body = carer.post(f"/api/v1/activities/{late}/check-in", headers=H).json()
    assert body["status"] == "LATE" and body["minutes_late"] >= 24
    dose = task(pid, cid, 5, category="MEDICATION")
    assert carer.post(f"/api/v1/activities/{dose}/check-in", headers=H).status_code == 422
    listed = coord.get(f"/api/v1/check-ins?patient_id={pid}").json()
    assert {i["activity_id"] for i in listed["items"]} >= {soon, late} and listed["policy"]["grace_min"] == 15


def test_a_missing_check_in_opens_one_no_checkin_search_that_closes_when_they_arrive(monkeypatch):
    monkeypatch.setattr(settings, "auto_coordination", False)
    coord, pid, cid, carer = team()
    caretaker(coord, pid, name="Ready backup", caps=("APPOINTMENT_ESCORT", "TRANSPORT"))
    not_yet = task(pid, cid, -10)  # inside the 20-minute allowance
    missing = task(pid, cid, -25)
    with SessionLocal() as db:
        checkins.run_checkin_tick(db); db.commit()
        checkins.run_checkin_tick(db); db.commit()  # idempotent across ticks
        reqs = db.scalars(select(CoverRequest).where(CoverRequest.activity_id.in_([uuid.UUID(not_yet), uuid.UUID(missing)]))).all()
        assert [(str(r.activity_id), r.reason, r.status) for r in reqs] == [(missing, "NO_CHECKIN", "OPEN")]
        assert str(reqs[0].replaced_caregiver_id) == cid
    board = coord.get(f"/api/v1/patients/{pid}/cover-requests").json()
    assert next(r for r in board["items"] if str(r["activity"]["id"]) == missing)["reason_label"] == "No check-in"
    assert carer.post(f"/api/v1/activities/{missing}/check-in", headers=H).json()["status"] == "LATE"
    with SessionLocal() as db:
        assert db.scalar(select(CoverRequest.status).where(CoverRequest.activity_id == uuid.UUID(missing))) == "CANCELLED"
        checkins.run_checkin_tick(db); db.commit()  # does not reopen for the same holder
        assert db.scalar(select(func.count()).select_from(CoverRequest).where(CoverRequest.activity_id == uuid.UUID(missing))) == 1


def test_the_checkins_flag_switches_it_off(monkeypatch):
    coord, pid, cid, carer = team()
    aid = task(pid, cid, -25)
    monkeypatch.setattr(settings, "features", "directory")
    assert carer.post(f"/api/v1/activities/{aid}/check-in", headers=H).status_code == 404
    with SessionLocal() as db:
        assert checkins.run_checkin_tick(db) == 0


# --- reliability metric --------------------------------------------------------------------------------------------------

def test_metric_counts_on_time_late_and_missing_check_ins():
    coord, pid, cid, carer = team()
    for minutes, status in ((-5, "ON_TIME"), (5, "ON_TIME"), (30, "LATE")):
        record(task(pid, cid, -24 * 60, status="COMPLETED"), cid, minutes, status)
    task(pid, cid, -24 * 60, status="COMPLETED")  # no check-in: missing
    task(pid, cid, 120)  # future: not counted yet
    b = coord.get(f"/api/v1/caretakers/{cid}/reputation").json()
    comp = {c["key"]: c for c in b["sources"]["metric"]["components"]}["on_time_check_in"]
    assert comp["value"] == 50.0 and comp["included"] and comp["detail"] == "2 of 4 on time, 1 late, 1 missing"
    assert b["sources"]["metric"]["counts"]["check_ins"] == 4 and b["sources"]["metric"]["counts"]["check_ins_late"] == 1


def test_no_check_in_record_means_not_recorded_yet():
    coord, pid, cid, _ = team()
    for _ in range(5): task(pid, cid, -24 * 60, category="MEDICATION", status="COMPLETED")  # doses do not need check-ins
    comp = {c["key"]: c for c in coord.get(f"/api/v1/caretakers/{cid}/reputation").json()["sources"]["metric"]["components"]}["on_time_check_in"]
    assert comp["value"] is None and comp["included"] is False and comp["detail"] == "Check-ins are not recorded yet"


def test_a_missed_check_in_counts_against_the_holder_even_after_cover_took_over(monkeypatch):
    monkeypatch.setattr(settings, "auto_coordination", False)
    coord, pid, cid, _ = team()
    aid = task(pid, cid, -25)
    with SessionLocal() as db:
        checkins.run_checkin_tick(db); db.commit()
        db.execute(CareAssignment.__table__.update().where(CareAssignment.activity_id == uuid.UUID(aid)).values(status="SUPERSEDED")); db.commit()
        got = checkins.counts(db, [uuid.UUID(cid)], now() - timedelta(days=1), now())[uuid.UUID(cid)]
    assert got == {"expected": 1, "on_time": 0, "late": 0}


def test_snapshots_stay_idempotent_with_check_ins_across_ticks():
    coord, pid, cid, _ = team()
    record(task(pid, cid, -24 * 60, status="COMPLETED"), cid, 0, "ON_TIME")
    with SessionLocal() as db:
        reputation.run_snapshots(db); db.commit()
        assert reputation.run_snapshots(db) == 0
        db.commit()
    with SessionLocal() as db:
        rows = db.scalars(select(ReputationSnapshot).where(ReputationSnapshot.caregiver_id == uuid.UUID(cid))).all()
        assert len(rows) == 1 and rows[0].breakdown["sources"]["metric"]["counts"]["check_ins"] == 1


# --- migrations: one chain, one head -----------------------------------------------------------------------------------

def _cfg():
    from alembic.config import Config
    cfg = Config(str(BACKEND / "alembic.ini")); cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


def test_the_migration_chain_has_one_head_in_order():
    from alembic.script import ScriptDirectory
    script = ScriptDirectory.from_config(_cfg())
    assert len(script.get_heads()) == 1
    chain = [r.revision for r in script.walk_revisions("base", "heads")]
    assert chain[chain.index("0017_reputation"):chain.index("0014_wellbeing_check_ins") + 1] == ["0017_reputation", "0016_directory", "0015_task_check_ins", "0014_wellbeing_check_ins"]


def _upgrade_paths(url, monkeypatch):
    from alembic import command
    monkeypatch.setattr(settings, "database_url", url)
    cfg, engine = _cfg(), create_engine(url)
    command.upgrade(cfg, "0014_wellbeing_check_ins")  # a database as deployed before these phases
    command.upgrade(cfg, "head")
    tables = set(inspect(engine).get_table_names())
    assert {"task_check_ins", "caretaker_profiles", "reviews", "patient_care_preferences", "hire_requests"} <= tables
    checks = {c["name"]: c["sqltext"] for c in inspect(engine).get_check_constraints("cover_requests")}
    assert "NO_CHECKIN" in checks["ck_cover_request_reason"]
    command.downgrade(cfg, "-2")  # -1 is the no-op RLS lock-down step; -2 actually drops hire_requests
    assert "hire_requests" not in inspect(engine).get_table_names() and "reviews" in inspect(engine).get_table_names()
    command.downgrade(cfg, "0014_wellbeing_check_ins")
    tables = set(inspect(engine).get_table_names())
    assert "task_check_ins" not in tables and "NO_CHECKIN" not in {c["name"]: c["sqltext"] for c in inspect(engine).get_check_constraints("cover_requests")}["ck_cover_request_reason"]
    command.upgrade(cfg, "head")
    engine.dispose()


def test_migrations_from_empty_and_from_0014_on_sqlite(tmp_path, monkeypatch):
    from alembic import command
    url = f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}"
    monkeypatch.setattr(settings, "database_url", url)
    command.upgrade(_cfg(), "head")  # from empty
    assert "task_check_ins" in inspect(create_engine(url)).get_table_names()
    _upgrade_paths(f"sqlite:///{(tmp_path / 'from14.db').as_posix()}", monkeypatch)


@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="set TEST_POSTGRES_URL to an empty Postgres database to run")
def test_migrations_from_0014_on_postgres(monkeypatch):
    _upgrade_paths(os.environ["TEST_POSTGRES_URL"], monkeypatch)
