import uuid
from datetime import timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.clock import now
from app.core.db import SessionLocal
from app.main import app
from app.models import CareAssignment, CoverRequest
from tests.helpers import account, caretaker, join_as_professional, primary_contact_with_patient
from app.services.backup_matcher import run_cover_tick, sync_patient
from app.services.workload_balancer import _aware

H = {"X-Requested-With": "second-patient"}
ANYTIME = [{"weekday": d, "start_min": 0, "end_min": 1440} for d in range(7)]


def caregiver(coord, pid, name, caps=("TRANSPORT",), day=3):
    return caretaker(coord, pid, name, caps=caps, day=day)


def task(coord, pid, title, hour, days=2):
    start = (now().astimezone(ZoneInfo("Asia/Kolkata")) + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
    created = coord.post(f"/api/v1/patients/{pid}/activities", headers=H, json={"title": title, "category": "TRANSPORT", "scheduled_start": start.isoformat(), "scheduled_end": (start + timedelta(hours=1)).isoformat(), "required_support": ["TRANSPORT"]})
    assert created.status_code == 201
    return created.json()["id"], start


def setup():
    coord, pid = primary_contact_with_patient("Synthetic cover patient")
    helper_id, helper = caregiver(coord, pid, "Helper Hema")
    people = {"helper": helper_id, "one": caregiver(coord, pid, "Backup One")[0], "two": caregiver(coord, pid, "Backup Two")[0],
              "busy": caregiver(coord, pid, "Busy Bala")[0], "nocar": caregiver(coord, pid, "No Car Nila", ("DAILY_ASSIST",))[0]}
    return coord, pid, helper, people


def open_requests(coord, pid):
    response = coord.get(f"/api/v1/patients/{pid}/cover-requests")
    assert response.status_code == 200
    return response.json()["items"]


def test_decline_opens_request_ranks_people_auto_advances_and_covers():
    coord, pid, helper, people = setup()
    aid, _ = task(coord, pid, "Clinic ride", 10)
    other, _ = task(coord, pid, "Busy errand", 10)
    assert coord.post(f"/api/v1/activities/{other}/assignments", headers=H, json={"caregiver_id": people["busy"], "confirm_now": True}).status_code == 201
    proposed = coord.post(f"/api/v1/activities/{aid}/assignments", headers=H, json={"caregiver_id": people["helper"]}).json()
    assert coord.post(f"/api/v1/assignments/{proposed['id']}/request-confirmation", headers=H, json={}).status_code == 200
    assert helper.post(f"/api/v1/assignments/{proposed['id']}/decline", headers=H, json={"reason": "Family function"}).status_code == 200

    [req] = [r for r in open_requests(coord, pid) if r["activity"]["id"] == aid]
    assert req["reason"] == "DECLINED" and req["reason_note"] == "Helper Hema declined: Family function" and req["replaced"]["caregiver_id"] == people["helper"]
    rows = {c["caregiver_id"]: c for c in req["ranking"]["candidates"]}
    assert rows[people["busy"]]["status"] == "COMMITTED"
    assert rows[people["nocar"]]["headline"].endswith("lacks the transport capability.")
    assert rows[people["helper"]]["status"] == "REPLACED" and req["ranking"]["eligible_count"] == 2

    best = req["ranking"]["best"]["caregiver_id"]
    offered = coord.post(f"/api/v1/cover-requests/{req['id']}/offer", headers=H, json={"caregiver_id": best, "auto_advance": True})
    assert offered.status_code == 200 and offered.json()["status"] == "OFFERED"
    # Recorded "no": the matcher offers the next eligible person without another call.
    declined = coord.post(f"/api/v1/cover-requests/{req['id']}/decline", headers=H, json={"reason": "Travelling"}).json()
    nxt = ({people["one"], people["two"]} - {best}).pop()
    assert declined["status"] == "OFFERED" and declined["offered"]["caregiver_id"] == nxt
    assert {c["caregiver_id"]: c["status"] for c in declined["ranking"]["candidates"]}[best] == "DECLINED_REQUEST"
    assert coord.get(f"/api/v1/activities/{aid}").json()["preliminary_support_status"] == "Not confirmed"

    accepted = coord.post(f"/api/v1/cover-requests/{req['id']}/accept", headers=H, json={})
    assert accepted.status_code == 200 and accepted.json()["status"] == "COVERED" and accepted.json()["resolution"] == "MATCHER"
    plan = coord.get(f"/api/v1/activities/{aid}").json()
    assert plan["preliminary_support_status"] == "Support confirmed" and [a["caregiver_id"] for a in plan["assignments"] if a["status"] == "CONFIRMED"] == [nxt]
    kinds = [e["kind"] for e in coord.get(f"/api/v1/cover-requests/{req['id']}").json()["events"]]
    assert kinds == ["OPENED", "OFFERED", "OFFER_DECLINED", "AUTO_ADVANCED", "ACCEPTED", "COVERED"]
    metrics = coord.get(f"/api/v1/patients/{pid}/cover-requests/metrics").json()
    assert metrics["covered_via_matcher"] == 1 and metrics["resolved_without_manual_search_pct"] == 100.0 and metrics["median_minutes_to_cover"] is not None


def test_absence_offer_is_accepted_by_the_caregiver_and_trigger_is_idempotent():
    coord, pid, helper, people = setup()
    aid, start = task(coord, pid, "Pharmacy run", 11)
    assert coord.post(f"/api/v1/activities/{aid}/assignments", headers=H, json={"caregiver_id": people["one"], "confirm_now": True}).status_code == 201
    absence = coord.post(f"/api/v1/caregivers/{people['one']}/availability-overrides", headers=H, json={"start_at": start.isoformat(), "end_at": (start + timedelta(hours=2)).isoformat(), "status": "UNAVAILABLE", "reason": "ILLNESS"})
    assert absence.status_code == 201
    [req] = [r for r in open_requests(coord, pid) if r["activity"]["id"] == aid]
    assert req["reason"] == "ABSENCE" and "reported an absence (illness)" in req["reason_note"]

    assert coord.post(f"/api/v1/cover-requests/{req['id']}/offer", headers=H, json={"caregiver_id": people["helper"]}).status_code == 200
    mine = helper.get("/api/v1/cover-offers/mine").json()["items"]
    assert [m["id"] for m in mine] == [req["id"]] and mine[0]["replaced"] is None
    own_view = helper.get(f"/api/v1/cover-requests/{req['id']}").json()
    assert own_view["my_offer"] is True and "ranking" not in own_view
    assert helper.get(f"/api/v1/patients/{pid}/cover-requests").status_code == 403
    taken = helper.post(f"/api/v1/cover-requests/{req['id']}/accept", headers=H, json={})
    assert taken.status_code == 200 and taken.json()["status"] == "COVERED"
    with SessionLocal() as db:
        row = db.get(CareAssignment, db.get(CoverRequest, uuid.UUID(req["id"])).covered_assignment_id)
        assert row.confirmed_via == "CAREGIVER" and row.status == "CONFIRMED"
        assert sync_patient(db, uuid.UUID(pid)) == 0  # same absence never opens a second request
        db.commit()


def test_absence_cleared_closes_request_and_manual_cover_is_measured():
    coord, pid, _, people = setup()
    aid, start = task(coord, pid, "Evening ride", 18)
    assert coord.post(f"/api/v1/activities/{aid}/assignments", headers=H, json={"caregiver_id": people["one"], "confirm_now": True}).status_code == 201
    oid = coord.post(f"/api/v1/caregivers/{people['one']}/availability-overrides", headers=H, json={"start_at": start.isoformat(), "end_at": (start + timedelta(hours=1)).isoformat(), "status": "UNAVAILABLE", "reason": "WORK"}).json()["id"]
    assert len([r for r in open_requests(coord, pid) if r["activity"]["id"] == aid]) == 1
    assert coord.post(f"/api/v1/caregivers/{people['one']}/availability-overrides/{oid}/cancel", headers=H, json={}).status_code == 200
    assert not [r for r in open_requests(coord, pid) if r["activity"]["id"] == aid]

    second, _ = task(coord, pid, "Morning ride", 8)
    manual = coord.post(f"/api/v1/activities/{second}/cover-requests", headers=H, json={"note": "Checking options"})
    assert manual.status_code == 201 and manual.json()["reason"] == "MANUAL"
    assert coord.post(f"/api/v1/activities/{second}/assignments", headers=H, json={"caregiver_id": people["two"], "confirm_now": True}).status_code == 201
    closed = coord.get(f"/api/v1/patients/{pid}/cover-requests", params={"status": "closed"}).json()["items"]
    row = next(r for r in closed if r["activity"]["id"] == second)
    assert row["status"] == "COVERED" and row["resolution"] == "MANUAL"
    assert coord.get(f"/api/v1/patients/{pid}/cover-requests/metrics").json()["covered_manually"] >= 1


def test_offer_rechecks_eligibility_expiry_and_access():
    coord, pid, helper, people = setup()
    aid, start = task(coord, pid, "Lab ride", 9)
    req = coord.post(f"/api/v1/activities/{aid}/cover-requests", headers=H, json={}).json()
    bad = coord.post(f"/api/v1/cover-requests/{req['id']}/offer", headers=H, json={"caregiver_id": people["nocar"]})
    assert bad.status_code == 409 and "lacks the transport capability" in bad.json()["error"]["message"]
    professional, _, _ = join_as_professional(coord, pid)
    assert professional.get(f"/api/v1/patients/{pid}/cover-requests").status_code == 403
    assert professional.post(f"/api/v1/cover-requests/{req['id']}/offer", headers=H, json={"caregiver_id": people["one"]}).status_code == 403
    assert helper.post(f"/api/v1/cover-requests/{req['id']}/accept", headers=H, json={"caregiver_id": people["helper"]}).status_code == 403
    outsider, _, _ = account("PRIMARY_CONTACT", "Outsider")
    assert outsider.get(f"/api/v1/cover-requests/{req['id']}").status_code == 403
    with SessionLocal() as db:
        run_cover_tick(db, start + timedelta(minutes=1)); db.commit()
        assert db.scalar(select(CoverRequest.status).where(CoverRequest.id == uuid.UUID(req["id"]))) == "EXPIRED"


def test_review_regressions_privacy_standby_confirmed_holder_and_no_reopen():
    coord, pid, helper, people = setup()
    # 1a: the replacement accepting their own offer does not learn who they replace or why.
    aid, start = task(coord, pid, "Morning pickup", 7)
    assert coord.post(f"/api/v1/activities/{aid}/assignments", headers=H, json={"caregiver_id": people["one"], "confirm_now": True}).status_code == 201
    coord.post(f"/api/v1/caregivers/{people['one']}/availability-overrides", headers=H, json={"start_at": start.isoformat(), "end_at": (start + timedelta(hours=1)).isoformat(), "status": "UNAVAILABLE", "reason": "ILLNESS"})
    [req] = [r for r in open_requests(coord, pid) if r["activity"]["id"] == aid]
    coord.post(f"/api/v1/cover-requests/{req['id']}/offer", headers=H, json={"caregiver_id": people["helper"]})
    taken = helper.post(f"/api/v1/cover-requests/{req['id']}/accept", headers=H, json={}).json()
    assert taken["replaced"] is None and taken["reason_note"] == "" and taken["message"].startswith("Thank you — you are confirmed")
    prompts = [n for n in helper.get("/api/v1/notifications").json()["items"] if n["title"] == "Can you cover a care task?"]
    assert prompts and all(n["read_at"] for n in prompts)

    # 2a: a Workload Balancer standby backup is released when cover is accepted.
    bid, _ = task(coord, pid, "Balanced errand", 12)
    assert coord.post(f"/api/v1/activities/{bid}/assignments", headers=H, json={"caregiver_id": people["two"], "confirm_now": True}).status_code == 201
    moved = coord.post(f"/api/v1/patients/{pid}/workload-balance/apply", headers=H, json={"activity_id": bid, "from_caregiver_id": people["two"], "to_caregiver_id": people["helper"]})
    assert moved.status_code == 200 and moved.json()["standby_backup"] is True
    assignment = moved.json()["assignment"]["id"]
    assert helper.post(f"/api/v1/assignments/{assignment}/decline", headers=H, json={"reason": "Busy"}).status_code == 200
    [cover] = [r for r in open_requests(coord, pid) if r["activity"]["id"] == bid]
    assert coord.post(f"/api/v1/cover-requests/{cover['id']}/accept", headers=H, json={"caregiver_id": people["one"]}).status_code == 200
    with SessionLocal() as db:
        rows = db.scalars(select(CareAssignment).where(CareAssignment.activity_id == uuid.UUID(bid), CareAssignment.status == "CONFIRMED")).all()
        assert [(r.role, str(r.caregiver_id)) for r in rows] == [("PRIMARY", people["one"])]

    # 2b: a manual request closes when the pending holder confirms; it never replaces them afterwards.
    cid, _ = task(coord, pid, "Pending ride", 15)
    pending = coord.post(f"/api/v1/activities/{cid}/assignments", headers=H, json={"caregiver_id": people["helper"]}).json()["id"]
    coord.post(f"/api/v1/assignments/{pending}/request-confirmation", headers=H, json={})
    manual = coord.post(f"/api/v1/activities/{cid}/cover-requests", headers=H, json={}).json()
    assert helper.post(f"/api/v1/assignments/{pending}/confirm", headers=H, json={}).status_code == 200
    closed = coord.get(f"/api/v1/cover-requests/{manual['id']}").json()
    assert closed["status"] == "CANCELLED" and closed["events"][-1]["note"] == "The original caregiver confirmed the task"
    # Command Center path refuses to start replacing a confirmed, available caregiver.
    stale = coord.post(f"/api/v1/activities/{cid}/cover-requests", headers=H, json={"only_if_uncovered": True})
    assert stale.status_code == 409

    # 2e: closing a request does not immediately reopen one for the same decline.
    did, _ = task(coord, pid, "Late ride", 19)
    p2 = coord.post(f"/api/v1/activities/{did}/assignments", headers=H, json={"caregiver_id": people["helper"]}).json()["id"]
    coord.post(f"/api/v1/assignments/{p2}/request-confirmation", headers=H, json={})
    helper.post(f"/api/v1/assignments/{p2}/decline", headers=H, json={"reason": "Away"})
    [declined] = [r for r in open_requests(coord, pid) if r["activity"]["id"] == did]
    assert coord.post(f"/api/v1/cover-requests/{declined['id']}/cancel", headers=H, json={"reason": "Will handle myself"}).status_code == 200
    assert not [r for r in open_requests(coord, pid) if r["activity"]["id"] == did]


def test_auto_advance_and_unanswered_offers_time_out():
    coord, pid, helper, people = setup()
    aid, start = task(coord, pid, "Dialysis ride", 9, days=1)
    req = coord.post(f"/api/v1/activities/{aid}/cover-requests", headers=H, json={}).json()
    assert coord.post(f"/api/v1/cover-requests/{req['id']}/offer", headers=H, json={"caregiver_id": people["helper"], "auto_advance": True}).status_code == 200
    assert helper.post(f"/api/v1/cover-requests/{req['id']}/decline", headers=H, json={"reason": "Exams"}).json() == {"id": req["id"], "status": "DECLINED_BY_YOU"}
    with SessionLocal() as db:
        row = db.get(CoverRequest, uuid.UUID(req["id"]))
        assert row.status == "OFFERED" and str(row.offered_caregiver_id) in (people["one"], people["two"])
        first_offer = row.offered_caregiver_id
        # No answer within the limit: the next person is asked automatically.
        sync_patient(db, uuid.UUID(pid), _aware(row.offered_at) + timedelta(hours=3)); db.commit()
        db.refresh(row)
        assert row.offered_caregiver_id != first_offer and str(first_offer) in row.declined_caregiver_ids
