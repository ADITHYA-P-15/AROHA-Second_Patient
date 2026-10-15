"""Ratings and reputation: formulas, policy validation, eligibility, privacy, prompts, snapshots and abuse limits."""
import json
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, inspect, select

from app.core import reputation_policy as rp
from app.core.clock import now
from app.core.config import settings
from app.core.db import SessionLocal
from app.main import app
from app.models import ActionItem, CareActivity, CareAssignment, Notification, ReputationSnapshot, Review
from app.services import reputation as rep
from tests.helpers import H, account, caretaker, join_as_professional, primary_contact_with_patient

BACKEND = Path(__file__).resolve().parents[1]
POL = rp.build("")


def served(pid, cid, n, late=0, missed=0, days_ago=3):
    """Write finished tasks this caretaker held for the patient, as the record would hold them."""
    with SessionLocal() as db:
        at = now()
        for i in range(n + late + missed):
            start = at - timedelta(days=days_ago, hours=i)
            status = "MISSED" if i >= n + late else "COMPLETED"
            a = CareActivity(patient_id=uuid.UUID(pid), title="Fictional task", category="MEDICATION", scheduled_start=start, scheduled_end=start + timedelta(minutes=15),
                             importance="MEDIUM", requires_caregiver=True, lifecycle_status=status, completed_at=start if status == "COMPLETED" else None,
                             completed_late=n <= i < n + late, created_by=_creator(db, pid))
            db.add(a); db.flush()
            db.add(CareAssignment(activity_id=a.id, caregiver_id=uuid.UUID(cid), role="PRIMARY", status="CONFIRMED", assigned_by=a.created_by))
        db.commit()


def _creator(db, pid):
    from app.models import Patient
    return db.get(Patient, uuid.UUID(pid)).created_by


def circle(tasks=5):
    coord, pid = primary_contact_with_patient(patient_account={"email": f"p-{uuid.uuid4().hex}@example.com", "password": "SafePass!123"})
    cid, carer = caretaker(coord, pid, name="Rated caretaker")
    if tasks: served(pid, cid, tasks)
    return coord, pid, cid, carer


def patient_client(coord, pid):
    email = next(m["email"] for m in coord.get(f"/api/v1/patients/{pid}/care-team").json()["items"] if m["team_role"] == "PATIENT_SELF")
    c = TestClient(app)
    assert c.post("/api/v1/auth/login", headers=H, json={"email": email, "password": "SafePass!123"}).status_code == 200
    return c


def age(model, rid, days):
    with SessionLocal() as db:
        row = db.get(model, uuid.UUID(rid)); row.created_at = now() - timedelta(days=days); db.commit()


@pytest.fixture
def policy(monkeypatch):
    def set_policy(**override):
        monkeypatch.setattr(settings, "reputation_policy", json.dumps(override))
    return set_policy


# --- formulas ----------------------------------------------------------------------------------------------------------

def test_star_scale_shrinkage_and_patient_weight():
    assert rep.stars_to_score(1) == 0 and rep.stars_to_score(3) == 50 and rep.stars_to_score(5) == 100
    assert rep.shrink(5.0, 1, 3.0, 3) == pytest.approx(3.5)
    assert rep.shrink(4.0, 0, 3.6, 3) == pytest.approx(3.6)
    mean, n = rep.customer_mean([(5, "PRIMARY_CONTACT"), (1, "PATIENT")], 0.5)
    assert n == 1.5 and mean == pytest.approx((5 + 0.5) / 1.5)
    assert rep.customer_mean([], 0.5) == (None, 0.0)


def test_missing_sources_are_left_out_and_weights_renormalised():
    weights = {"metric": 40, "doctors": 25, "customers": 20, "agency": 15}
    out = rep.combine({"metric": 80.0, "doctors": None, "customers": None, "agency": 50.0}, weights)
    assert out["included"] == ["metric", "agency"] and out["composite"] == pytest.approx((40 * 80 + 15 * 50) / 55, abs=0.05)
    assert out["effective_weights"] == {"metric": pytest.approx(72.7, abs=0.05), "agency": pytest.approx(27.3, abs=0.05)}
    assert rep.combine({s: None for s in weights}, weights) == {"composite": None, "included": [], "effective_weights": {}}


def test_metric_score_components_and_minimum_history():
    c = rep.MetricCounts(decided=10, on_time=7, late=2, missed=1, offers_accepted=3, offers_declined=1)
    m = rep.metric_score(c, POL)
    by = {x["key"]: x for x in m["components"]}
    assert by["on_time_completion"]["value"] == 70.0 and by["no_missed"]["value"] == 90.0 and by["cover_acceptance"]["value"] == 75.0
    assert by["on_time_check_in"]["included"] is False and "not recorded" in by["on_time_check_in"]["detail"]
    assert m["score"] == pytest.approx((45 * 70 + 30 * 90 + 10 * 75) / 85, abs=0.05)
    assert rep.metric_score(rep.MetricCounts(decided=4, on_time=4), POL)["score"] is None
    checked = rep.metric_score(rep.MetricCounts(decided=5, on_time=5, check_ins=4, check_ins_on_time=3), POL)
    assert {x["key"]: x["value"] for x in checked["components"]}["on_time_check_in"] == 75.0


def test_one_review_cannot_rank_anyone_first():
    priors = rep.Priors(doctors=3.6, customers=3.6)
    single = rep.reputation(rep.RatingInputs(customers=[(5, "PRIMARY_CONTACT")]), priors, POL)
    steady = rep.reputation(rep.RatingInputs(customers=[(5, "PRIMARY_CONTACT")] * 8 + [(4, "PRIMARY_CONTACT")] * 4), priors, POL)
    assert single["composite"] < steady["composite"]
    assert single["sources"]["customers"]["adjusted_stars"] == pytest.approx((5 + 3 * 3.6) / 4, abs=0.01)
    assert single["enough_history"] is False and steady["enough_history"] is True
    assert single["included"] == ["customers"]


def test_patient_reviews_count_for_less():
    priors = rep.Priors()
    family_low = rep.reputation(rep.RatingInputs(customers=[(2, "PRIMARY_CONTACT"), (5, "PATIENT")]), priors, POL)
    patient_low = rep.reputation(rep.RatingInputs(customers=[(5, "PRIMARY_CONTACT"), (2, "PATIENT")]), priors, POL)
    assert family_low["sources"]["customers"]["stars"] < patient_low["sources"]["customers"]["stars"]
    assert patient_low["sources"]["customers"]["by_author"]["PATIENT"] == {"count": 1, "stars": 2.0}


# --- policy ------------------------------------------------------------------------------------------------------------

def test_policy_defaults_overrides_and_validation():
    assert POL["weights"] == {"metric": 40, "doctors": 25, "customers": 20, "agency": 15} and POL["patient_review_weight"] == 0.5
    merged = rp.build('{"weights": {"agency": 0}, "min_completed_tasks": 3}')
    assert merged["weights"] == {"metric": 40, "doctors": 25, "customers": 20, "agency": 0} and merged["min_completed_tasks"] == 3
    for bad in ('{"weights": {"metric": -1}}', '{"weights": {"metric": 0, "doctors": 0, "customers": 0, "agency": 0}}', '{"weights": {"popularity": 5}}',
                '{"patient_review_weight": 2}', '{"min_completed_tasks": 0}', '{"surprise": 1}', '[1, 2]', '{not json', '{"edit_window_days": 120}',
                '{"metric_components": {"on_time_completion": "lots"}}', '{"shrinkage_k": true}'):
        with pytest.raises(rp.PolicyError):
            rp.build(bad)


def test_an_invalid_policy_stops_start_up(tmp_path):
    import os, subprocess, sys
    env = {**os.environ, "REPUTATION_POLICY": '{"weights": {"metric": -5}}', "DATABASE_URL": f"sqlite:///{(tmp_path / 'x.db').as_posix()}", "SEED_DEMO": "false"}
    result = subprocess.run([sys.executable, "-c", "import app.main"], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode != 0 and "Invalid REPUTATION_POLICY" in result.stderr


# --- eligibility -------------------------------------------------------------------------------------------------------

def test_reviews_need_a_relationship_and_enough_completed_tasks():
    coord, pid, cid, _ = circle(tasks=4)
    stranger, *_ = account("PRIMARY_CONTACT")
    assert stranger.post(f"/api/v1/caretakers/{cid}/reviews", headers=H, json={"rating": 5}).status_code == 403
    assert coord.post(f"/api/v1/caretakers/{cid}/reviews", headers=H, json={"rating": 5}).status_code == 403  # 4 of 5 tasks
    served(pid, cid, 1)
    made = coord.post(f"/api/v1/caretakers/{cid}/reviews", headers=H, json={"rating": 4, "text": "Fictional: reliable."})
    assert made.status_code == 201, made.text
    assert coord.post(f"/api/v1/caretakers/{cid}/reviews", headers=H, json={"rating": 5}).status_code == 409
    for role in ("CARETAKER", "PROFESSIONAL"):
        other, *_ = account(role)
        assert other.post(f"/api/v1/caretakers/{cid}/reviews", headers=H, json={"rating": 5}).status_code == 403
    assert coord.post(f"/api/v1/caretakers/{cid}/reviews", headers=H, json={"rating": 6}).status_code == 422
    assert coord.post(f"/api/v1/caretakers/{cid}/reviews", headers=H, json={"rating": 3, "text": "x" * 501}).status_code == 422


def test_reviews_are_editable_for_seven_days_by_their_author_only():
    coord, pid, cid, carer = circle()
    rid = coord.post(f"/api/v1/caretakers/{cid}/reviews", headers=H, json={"rating": 3}).json()["id"]
    edited = coord.patch(f"/api/v1/reviews/{rid}", headers=H, json={"rating": 5, "text": "Fictional: much better now."})
    assert edited.status_code == 200 and edited.json()["rating"] == 5
    assert carer.patch(f"/api/v1/reviews/{rid}", headers=H, json={"rating": 1}).status_code == 403
    age(Review, rid, 8)
    assert coord.patch(f"/api/v1/reviews/{rid}", headers=H, json={"rating": 4}).status_code == 409
    age(Review, rid, 91)  # the window has passed: a new review is allowed
    assert coord.post(f"/api/v1/caretakers/{cid}/reviews", headers=H, json={"rating": 4}).status_code == 201


def test_patient_reviews_are_optional_and_weighted_lower():
    coord, pid, cid, _ = circle()
    patient = patient_client(coord, pid)
    assert patient.get("/api/v1/reputation/prompts").json()["items"][0]["caregiver_id"] == cid
    assert patient.post(f"/api/v1/caretakers/{cid}/reviews", headers=H, json={"rating": 1}).status_code == 201
    assert patient.get("/api/v1/reputation/prompts").json()["items"] == []
    coord.post(f"/api/v1/caretakers/{cid}/reviews", headers=H, json={"rating": 5})
    b = coord.get(f"/api/v1/caretakers/{cid}/reputation").json()["sources"]["customers"]
    assert b["by_author"] == {"PRIMARY_CONTACT": {"count": 1, "stars": 5.0}, "PATIENT": {"count": 1, "stars": 1.0}}
    assert b["effective_count"] == 1.5 and b["stars"] == pytest.approx((5 + 0.5) / 1.5, abs=0.01)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Notification).where(Notification.title.like("How is%"), Notification.user_id == uuid.UUID(patient.get("/api/v1/auth/me").json()["id"]))) == 0


def test_doctor_ratings_need_a_patient_the_caretaker_served():
    coord, pid, cid, _ = circle(tasks=1)
    outsider, *_ = account("PROFESSIONAL")
    assert outsider.post(f"/api/v1/caretakers/{cid}/doctor-ratings", headers=H, json={"rating": 4}).status_code == 403
    pro, *_ = join_as_professional(coord, pid)
    made = pro.post(f"/api/v1/caretakers/{cid}/doctor-ratings", headers=H, json={"rating": 4, "note": "Fictional: follows the plan."})
    assert made.status_code == 201, made.text
    assert pro.post(f"/api/v1/caretakers/{cid}/doctor-ratings", headers=H, json={"rating": 5}).status_code == 409
    assert pro.patch(f"/api/v1/doctor-ratings/{made.json()['id']}", headers=H, json={"rating": 5}).json()["rating"] == 5
    assert pro.post(f"/api/v1/caretakers/{cid}/doctor-ratings", headers=H, json={"rating": 4, "note": "x" * 301}).status_code == 422
    assert coord.post(f"/api/v1/caretakers/{cid}/doctor-ratings", headers=H, json={"rating": 4}).status_code == 403
    rows = pro.get(f"/api/v1/patients/{pid}/rateable-caretakers").json()["items"]
    assert rows[0]["kind"] == "doctor" and rows[0]["mine"]["rating"] == 5


# --- privacy -----------------------------------------------------------------------------------------------------------

def test_review_text_is_for_families_and_professionals_and_the_caretaker_never_learns_who():
    coord, pid, cid, carer = circle()
    coord.post(f"/api/v1/caretakers/{cid}/reviews", headers=H, json={"rating": 4, "text": "Fictional secret detail"})
    pro, *_ = join_as_professional(coord, pid)
    other_family, *_ = account("PRIMARY_CONTACT")
    for viewer in (coord, pro, other_family, carer):
        body = viewer.get(f"/api/v1/caretakers/{cid}/reviews").json()
        assert body["items"][0]["text"] == "Fictional secret detail" and "author_user_id" not in body["items"][0]
    assert patient_client(coord, pid).get(f"/api/v1/caretakers/{cid}/reviews").json()["items"][0]["text"] is None
    another_carer, *_ = account("CARETAKER")
    assert another_carer.get(f"/api/v1/caretakers/{cid}/reviews").status_code == 403
    assert another_carer.get(f"/api/v1/caretakers/{cid}/reputation").status_code == 403
    assert carer.get(f"/api/v1/caretakers/{cid}/reputation").status_code == 200
    note = carer.get("/api/v1/notifications").json()["items"]
    received = [n for n in note if n["title"] == "New review on your profile"]
    assert received and "Primary contact" not in received[0]["body"] and coord.get("/api/v1/auth/me").json()["name"] not in received[0]["body"]


def test_reports_go_to_moderation_and_hidden_reviews_never_count():
    coord, pid, cid, carer = circle()
    rid = coord.post(f"/api/v1/caretakers/{cid}/reviews", headers=H, json={"rating": 1, "text": "Fictional unfair review"}).json()["id"]
    assert carer.post(f"/api/v1/reviews/{rid}/report", headers=H, json={"reason": "Not accurate"}).status_code == 201
    assert carer.post(f"/api/v1/reviews/{rid}/report", headers=H, json={"reason": "again"}).status_code == 409
    outsider, *_ = account("CARETAKER")
    assert outsider.post(f"/api/v1/reviews/{rid}/report", headers=H, json={}).status_code == 403
    assert coord.get(f"/api/v1/caretakers/{cid}/reviews").json()["total"] == 1  # a report hides nothing
    assert carer.delete(f"/api/v1/reviews/{rid}", headers=H).status_code == 405  # nobody deletes another's review
    with SessionLocal() as db:
        db.get(Review, uuid.UUID(rid)).hidden = True; db.commit()  # moderators hide at the database level
    assert coord.get(f"/api/v1/caretakers/{cid}/reviews").json()["total"] == 0
    assert coord.get(f"/api/v1/caretakers/{cid}/reputation").json()["sources"]["customers"]["count"] == 0


# --- abuse limits and the flag ---------------------------------------------------------------------------------------

def test_daily_rating_limit(policy):
    policy(max_ratings_per_day=1)
    coord, pid, cid, _ = circle()
    cid2, _ = caretaker(coord, pid, name="Second caretaker")
    served(pid, cid2, 5)
    assert coord.post(f"/api/v1/caretakers/{cid}/reviews", headers=H, json={"rating": 4}).status_code == 201
    assert coord.post(f"/api/v1/caretakers/{cid2}/reviews", headers=H, json={"rating": 4}).status_code == 429


def test_the_ratings_flag_switches_it_off(monkeypatch):
    coord, pid, cid, _ = circle(tasks=0)
    monkeypatch.setattr(settings, "features", "directory")
    assert coord.get(f"/api/v1/caretakers/{cid}/reputation").status_code == 404
    with SessionLocal() as db:
        assert rep.run_reputation_tick(db) == {"prompts": 0, "snapshots": 0}


# --- prompts -----------------------------------------------------------------------------------------------------------

def test_the_rate_prompt_appears_once_and_closes_when_rated():
    coord, pid, cid, _ = circle(tasks=4)
    with SessionLocal() as db:
        rep.run_prompts(db); db.commit()
        assert not db.scalar(select(ActionItem.id).where(ActionItem.dedupe_key == rep.prompt_key(cid)))
    served(pid, cid, 1)
    with SessionLocal() as db:
        rep.run_prompts(db); db.commit()
        rep.run_prompts(db); db.commit()
        items = db.scalars(select(ActionItem).where(ActionItem.patient_id == uuid.UUID(pid), ActionItem.dedupe_key == rep.prompt_key(cid))).all()
        assert len(items) == 1 and items[0].status == "OPEN" and items[0].title == "Rate Rated caretaker" and items[0].suggested_actions[0]["option"] == "RATE_CARETAKER"
    bells = [n for n in coord.get("/api/v1/notifications").json()["items"] if n["title"].startswith("How is")]
    assert len(bells) == 1
    center = coord.get(f"/api/v1/command-center?patient_id={pid}").json()
    assert any(a["kind"] == "RATE_CARETAKER" for a in center["pending_actions"])
    coord.post(f"/api/v1/caretakers/{cid}/reviews", headers=H, json={"rating": 5})
    with SessionLocal() as db:
        assert db.scalar(select(ActionItem.status).where(ActionItem.dedupe_key == rep.prompt_key(cid), ActionItem.patient_id == uuid.UUID(pid))) == "DONE"


def test_a_dismissed_prompt_returns_at_most_once_per_ninety_days():
    coord, pid, cid, _ = circle()
    with SessionLocal() as db:
        rep.run_prompts(db); db.commit()
        item = db.scalar(select(ActionItem).where(ActionItem.dedupe_key == rep.prompt_key(cid), ActionItem.patient_id == uuid.UUID(pid)))
    assert coord.post(f"/api/v1/action-items/{item.id}/dismiss", headers=H, json={"reason": "Not now"}).status_code == 200
    mine = select(func.count()).select_from(ActionItem).where(ActionItem.dedupe_key == rep.prompt_key(cid), ActionItem.patient_id == uuid.UUID(pid))
    with SessionLocal() as db:  # other tests' care circles may get prompts too; only this pair is counted
        rep.run_prompts(db, now() + timedelta(days=30)); db.commit()
        assert db.scalar(mine) == 1
        rep.run_prompts(db, now() + timedelta(days=91)); db.commit()
        assert db.scalar(select(func.count()).select_from(ActionItem).where(ActionItem.dedupe_key == rep.prompt_key(cid), ActionItem.patient_id == uuid.UUID(pid))) == 2


# --- snapshots ---------------------------------------------------------------------------------------------------------

def test_snapshots_are_daily_and_idempotent_across_ticks_and_restarts():
    coord, pid, cid, _ = circle()
    coord.post(f"/api/v1/caretakers/{cid}/reviews", headers=H, json={"rating": 4})
    with SessionLocal() as db:
        first = rep.run_snapshots(db); db.commit()
        assert first >= 1 and rep.run_snapshots(db) == 0
        db.commit()
    with SessionLocal() as db:  # a restart: a new process has no memory, only the database
        assert rep.run_reputation_tick(db)["snapshots"] == 0
        db.commit()
        today = rep.local_day(now())
        row = db.scalar(select(ReputationSnapshot).where(ReputationSnapshot.caregiver_id == uuid.UUID(cid), ReputationSnapshot.day == today))
        assert row is not None and row.breakdown["sources"]["customers"]["count"] == 1 and row.metric_score is not None
        assert db.scalar(select(func.count()).select_from(ReputationSnapshot).where(ReputationSnapshot.caregiver_id == uuid.UUID(cid))) == 1
        assert rep.run_snapshots(db, now() + timedelta(days=1)) >= 1
        db.commit()
        assert db.scalar(select(func.count()).select_from(ReputationSnapshot).where(ReputationSnapshot.caregiver_id == uuid.UUID(cid))) == 2


def test_breakdown_shows_metric_components_from_our_records():
    coord, pid, cid, _ = circle(tasks=0)
    served(pid, cid, 6, late=2, missed=2)
    b = coord.get(f"/api/v1/caretakers/{cid}/reputation").json()
    metric = b["sources"]["metric"]
    assert metric["counts"]["decided"] == 10 and metric["counts"]["missed"] == 2 and metric["counts"]["late"] == 2
    comps = {c["key"]: c["value"] for c in metric["components"]}
    assert comps["on_time_completion"] == 60.0 and comps["no_missed"] == 80.0 and comps["on_time_check_in"] is None
    assert b["included"] == ["metric"] and b["composite"] == metric["score"]


# --- migration ---------------------------------------------------------------------------------------------------------

def test_migration_0017_up_and_down_on_sqlite(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    monkeypatch.setattr(settings, "database_url", url)
    cfg = Config(str(BACKEND / "alembic.ini")); cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    engine = create_engine(url)
    names = {"agency_ratings", "doctor_ratings", "reviews", "review_reports", "reputation_snapshots"}
    command.upgrade(cfg, "head")
    assert names <= set(inspect(engine).get_table_names())
    command.downgrade(cfg, "0016_directory")
    tables = set(inspect(engine).get_table_names())
    assert not (names & tables) and "caretaker_profiles" in tables
    command.upgrade(cfg, "head")
    assert names <= set(inspect(engine).get_table_names())
    engine.dispose()
