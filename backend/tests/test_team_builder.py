"""Team builder: privacy of hire requests, the request state machine and its races, reputation-aware matching,
suggestions that are never acted on, removal without stranded tasks, and the Command Center warning."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core import matcher_policy as mp
from app.core.clock import now
from app.core.config import settings
from app.core.db import SessionLocal
from app.engine.backup_matcher import extra_points, rank_candidates
from app.models import CareActivity, CareAssignment, CareTeamMember, Caregiver, CoverRequest, HireRequest, Patient, User
from app.services import team_builder as tb
from tests.helpers import H, account, caretaker, primary_contact_with_patient
from tests.test_backup_matcher_engine import END, NOW, START, act, cg

PHONE = "+91 00000 77777 (fictional)"
POL = mp.build("")


def listed(name="Listed caretaker", gender="FEMALE", city="Pune", state="Maharashtra", languages=("Marathi", "English")):
    """A caretaker account with a directory listing and a (fictional) phone number."""
    client, _, user_id = account("CARETAKER", name)
    r = client.patch("/api/v1/directory/me", headers=H, json={"listed": True, "gender": gender, "current_state": state, "current_city": city, "languages": list(languages)})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        c = db.scalar(select(Caregiver).where(Caregiver.user_id == uuid.UUID(user_id))); c.phone = PHONE; c.notes = "Fictional private note"; db.commit()
        return client, str(c.id)


def send(coord, pid, cid, key=None, role="BACKUP"):
    headers = {**H, **({"Idempotency-Key": key} if key else {})}
    return coord.post(f"/api/v1/patients/{pid}/hire-requests", headers=headers, json={"caregiver_id": cid, "intended_role": role, "message": "Fictional: can you help?"})


# --- privacy -----------------------------------------------------------------------------------------------------------

def test_contact_details_appear_only_after_acceptance_and_only_to_that_team():
    coord, pid = primary_contact_with_patient()
    carer, cid = listed()
    before = [coord.get(f"/api/v1/directory/caretakers/{cid}"), coord.get("/api/v1/directory/caretakers?limit=50"), coord.get(f"/api/v1/patients/{pid}/team-matches"), send(coord, pid, cid)]
    rid = before[-1].json()["id"]
    before += [coord.get(f"/api/v1/patients/{pid}/hire-requests"), carer.get("/api/v1/hire-requests/mine")]
    for r in before:
        assert r.status_code in (200, 201), r.text
        body = r.text
        assert PHONE not in body and "Fictional private note" not in body and carer.email not in body
    assert carer.post(f"/api/v1/hire-requests/{rid}/accept", headers=H).json()["status"] == "ACCEPTED"
    assert PHONE not in coord.get(f"/api/v1/patients/{pid}/hire-requests").text  # the request itself never carries it
    team = coord.get(f"/api/v1/patients/{pid}/caregivers").json()["items"]
    assert next(c for c in team if c["id"] == cid)["phone"] == PHONE
    assert coord.get(f"/api/v1/directory/caretakers/{cid}").json()["private"]["phone"] == PHONE
    assert carer.email in coord.get(f"/api/v1/patients/{pid}/care-team").text
    other, other_pid = primary_contact_with_patient()
    assert other.get(f"/api/v1/directory/caretakers/{cid}").json()["private"] is None
    assert PHONE not in other.get(f"/api/v1/patients/{other_pid}/team-matches").text


# --- state machine -----------------------------------------------------------------------------------------------------

def test_every_transition_and_the_illegal_ones():
    coord, pid = primary_contact_with_patient()
    carer, cid = listed("State caretaker")
    stranger, _ = listed("Someone else")
    rid = send(coord, pid, cid).json()["id"]
    assert send(coord, pid, cid).status_code == 409  # one open request per patient and caretaker
    assert stranger.post(f"/api/v1/hire-requests/{rid}/accept", headers=H).status_code == 403
    assert coord.post(f"/api/v1/hire-requests/{rid}/accept", headers=H).status_code == 403
    assert carer.post(f"/api/v1/hire-requests/{rid}/withdraw", headers=H).status_code == 403
    assert carer.post(f"/api/v1/hire-requests/{rid}/decline", headers=H, json={"reason": "Fictional: fully booked"}).json()["status"] == "DECLINED"
    for verb, who in (("accept", carer), ("decline", carer), ("withdraw", coord)):
        assert who.post(f"/api/v1/hire-requests/{rid}/{verb}", headers=H).status_code == 409
    rid2 = send(coord, pid, cid).json()["id"]  # allowed again after a final state
    assert coord.post(f"/api/v1/hire-requests/{rid2}/withdraw", headers=H).json()["status"] == "WITHDRAWN"
    rid3 = send(coord, pid, cid, role="MAIN").json()["id"]
    assert carer.post(f"/api/v1/hire-requests/{rid3}/accept", headers=H).json()["status"] == "ACCEPTED"
    assert coord.post(f"/api/v1/hire-requests/{rid3}/withdraw", headers=H).status_code == 409
    assert send(coord, pid, cid).status_code == 409  # already on the team
    team = coord.get(f"/api/v1/patients/{pid}/caregivers").json()["items"]
    assert next(c for c in team if c["id"] == cid)["is_main_caretaker"] is True
    caretaker_role, *_ = account("CARETAKER")
    assert caretaker_role.post(f"/api/v1/patients/{pid}/hire-requests", headers=H, json={"caregiver_id": cid}).status_code == 403


def test_expiry_is_idempotent_and_blocks_acceptance():
    coord, pid = primary_contact_with_patient()
    carer, cid = listed("Slow caretaker")
    rid = send(coord, pid, cid).json()["id"]
    with SessionLocal() as db:
        db.get(HireRequest, uuid.UUID(rid)).expires_at = now() - timedelta(minutes=1); db.commit()
        assert tb.run_expiry_tick(db) >= 1; db.commit()
        assert tb.run_expiry_tick(db) == 0
    assert coord.get(f"/api/v1/patients/{pid}/hire-requests").json()["items"][0]["status"] == "EXPIRED"
    assert carer.post(f"/api/v1/hire-requests/{rid}/accept", headers=H).status_code == 409
    rid2 = send(coord, pid, cid).json()["id"]
    with SessionLocal() as db:
        db.get(HireRequest, uuid.UUID(rid2)).expires_at = now() - timedelta(seconds=1); db.commit()
    assert carer.post(f"/api/v1/hire-requests/{rid2}/accept", headers=H).status_code == 409  # past its time even before the tick
    assert coord.get(f"/api/v1/patients/{pid}/hire-requests").json()["items"][0]["status"] == "EXPIRED"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(CareTeamMember).where(CareTeamMember.patient_id == uuid.UUID(pid), CareTeamMember.team_role == "CARETAKER")) == 0


def test_idempotency_key_and_rate_limit(monkeypatch):
    coord, pid = primary_contact_with_patient()
    _, cid = listed("Key caretaker")
    _, cid2 = listed("Second key caretaker")
    first = send(coord, pid, cid, key="k-123")
    again = send(coord, pid, cid, key="k-123")
    assert first.status_code == 201 and again.status_code == 200 and again.json()["id"] == first.json()["id"]
    assert send(coord, pid, cid2, key="k-123").status_code == 422
    monkeypatch.setattr(tb, "MAX_REQUESTS_PER_DAY", 2)
    assert send(coord, pid, cid2).status_code == 201
    _, cid3 = listed("Third caretaker")
    assert send(coord, pid, cid3).status_code == 429


def test_accept_withdraw_and_expire_racing_give_exactly_one_outcome():
    coord, pid = primary_contact_with_patient()
    carer, cid = listed("Racing caretaker")
    rid = uuid.UUID(send(coord, pid, cid).json()["id"])
    with SessionLocal() as db:
        coord_user = db.scalar(select(User).where(User.email == coord.email)); carer_user = db.scalar(select(User).where(User.email == carer.email))
    a, b, c = SessionLocal(), SessionLocal(), SessionLocal()
    try:
        ra, rb, rc = a.get(HireRequest, rid), b.get(HireRequest, rid), c.get(HireRequest, rid)  # all three read it as PENDING
        assert ra.status == rb.status == rc.status == "PENDING"
        tb.accept(a, ra, a.merge(carer_user)); a.commit()
        with pytest.raises(tb.HireError): tb.withdraw(b, rb, b.merge(coord_user))
        b.rollback()
        assert tb.expire(c, rc) is False; c.commit()
    finally:
        a.close(); b.close(); c.close()
    with SessionLocal() as db:
        assert db.get(HireRequest, rid).status == "ACCEPTED"
        assert db.scalar(select(func.count()).select_from(CareTeamMember).where(CareTeamMember.patient_id == uuid.UUID(pid), CareTeamMember.user_id == carer_user.id)) == 1


def test_a_caretaker_at_their_limits_is_shown_that_on_the_request():
    coord, pid = primary_contact_with_patient()
    carer, cid = listed("Busy caretaker")
    with SessionLocal() as db:
        c = db.get(Caregiver, uuid.UUID(cid)); c.max_activities_per_day = 1; creator = db.get(Patient, uuid.UUID(pid)).created_by
        other_pid = uuid.UUID(primary_contact_with_patient()[1])
        start = now() + timedelta(days=1)
        a = CareActivity(patient_id=other_pid, title="Fictional visit", category="APPOINTMENT", scheduled_start=start, scheduled_end=start + timedelta(hours=1), importance="MEDIUM",
                         requires_caregiver=True, created_by=creator)
        db.add(a); db.flush(); db.add(CareAssignment(activity_id=a.id, caregiver_id=c.id, role="PRIMARY", status="CONFIRMED", assigned_by=creator)); db.commit()
    body = send(coord, pid, cid).json()
    assert "daily limit of 1" in body["capacity_note"]
    assert "daily limit of 1" in carer.get("/api/v1/hire-requests/mine").json()["items"][0]["capacity_note"]


# --- matcher -----------------------------------------------------------------------------------------------------------

def snap(caregivers, extras):
    ride = act("ride", 10, support=("TRANSPORT",))
    return rank_candidates({"caregivers": caregivers, "activities": [ride], "commitments": [], "confirmed_backups": {}, "history": {}, "extras": extras}, NOW, START, END, "ride")


def profile(composite=None, metric=None, city="", sector=None, languages=(), gender=None):
    return {"composite": composite, "metric": metric, "city": city, "sector": sector, "languages": list(languages), "gender": gender}


def test_reputation_reorders_but_never_overrides_a_hard_rule():
    extras = {"profiles": {"anna": profile(40), "bala": profile(95), "chitra": profile(100)}, "preferences": None, "policy": POL}
    result = snap([cg("anna"), cg("bala"), cg("chitra", caps=("DAILY_ASSIST",))], extras)
    rows = {c["caregiver_id"]: c for c in result["candidates"]}
    assert result["best"]["caregiver_id"] == "bala"
    assert rows["chitra"]["status"] == "MISSING_CAPABILITY" and not rows["chitra"]["eligible"]  # top reputation cannot buy a missing skill
    labels = {p["label"]: p["points"] for p in rows["bala"]["score_breakdown"]}
    assert labels["Reputation 95/100"] == 9 and {p["label"]: p["points"] for p in rows["anna"]["score_breakdown"]}["Reputation 40/100"] == -2


def test_preferences_only_add_points_and_never_filter_anyone():
    prefs = {"languages": ["Tamil"], "city": "Chennai", "sector_code": "SOUTH"}
    extras = {"profiles": {"anna": profile(languages=["Tamil"], city="Chennai"), "bala": profile(80)}, "preferences": prefs, "policy": POL}
    rows = {c["caregiver_id"]: c for c in snap([cg("anna"), cg("bala")], extras)["candidates"]}
    assert rows["anna"]["eligible"] and rows["bala"]["eligible"]  # no preference-based status any more
    labels = {p["label"] for p in rows["anna"]["score_breakdown"]}
    assert {"Speaks Tamil", "Lives in Chennai, the patient's city"} <= labels
    assert not any("gender" in p["label"].lower() for r in rows.values() for p in r["score_breakdown"])


def test_unrated_is_neutral_and_ties_are_deterministic():
    extras = {"profiles": {"anna": profile(), "bala": profile(50, 50)}, "preferences": None, "policy": POL}
    result = snap([cg("bala"), cg("anna")], extras)
    a = {p["label"]: p["points"] for p in next(c for c in result["candidates"] if c["caregiver_id"] == "anna")["score_breakdown"]}
    assert a["Reputation: no rating yet (neutral)"] == 0 and a["Reliability record: not enough history (neutral)"] == 0
    assert [c["caregiver_id"] for c in result["candidates"]] == ["anna", "bala"]  # equal scores: by name
    assert [c["caregiver_id"] for c in snap([cg("anna"), cg("bala")], extras)["candidates"]] == ["anna", "bala"]


def test_extra_points_are_each_explained():
    labels = [p["label"] for p in extra_points("Asha", profile(90, 70, city="Pune", sector="WEST", languages=["Marathi"]),
                                                {"languages": ["marathi"], "city": "pune", "sector_code": "WEST"}, POL)]
    assert labels == ["Reputation 90/100", "Reliability record 70/100", "Lives in Pune, the patient's city", "Speaks Marathi"]
    assert [p["label"] for p in extra_points("Asha", profile(sector="WEST"), {"sector_code": "WEST"}, POL)][-1] == "Lives in the patient's region"


def test_matcher_policy_validation():
    assert mp.build('{"same_city": 9}')["same_city"] == 9
    for bad in ('{"same_city": -1}', '{"vibes": 3}', '{"reputation_max": 2.5}', '[]', '{bad', '{"soft_gender": 6}'):
        with pytest.raises(mp.PolicyError): mp.build(bad)


def test_the_live_matcher_adds_preference_points_for_cover_without_filtering(monkeypatch):
    monkeypatch.setattr(settings, "auto_coordination", False)
    coord, pid = primary_contact_with_patient()
    holder, _ = caretaker(coord, pid, name="Holder", caps=("TRANSPORT",))
    man_cid, _ = caretaker(coord, pid, name="Arun backup", caps=("TRANSPORT",))
    carer, woman_cid = listed("Bhavna backup", languages=("Konkani",))
    with SessionLocal() as db:
        db.get(Caregiver, uuid.UUID(woman_cid)).capabilities = ["TRANSPORT"]; db.commit()
    rid = send(coord, pid, woman_cid).json()["id"]
    carer.post(f"/api/v1/hire-requests/{rid}/accept", headers=H)
    from app.models import CaregiverWeeklySchedule
    with SessionLocal() as db:
        db.query(CaregiverWeeklySchedule).filter(CaregiverWeeklySchedule.caregiver_id == uuid.UUID(woman_cid)).delete()
        db.add_all([CaregiverWeeklySchedule(caregiver_id=uuid.UUID(woman_cid), weekday=d, start_min=0, end_min=1440) for d in range(7)]); db.commit()
    start = (now() + timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
    made = coord.post(f"/api/v1/patients/{pid}/activities", headers=H, json={"title": "Fictional ride", "category": "TRANSPORT", "scheduled_start": start.isoformat(),
                                                                            "scheduled_end": (start + timedelta(hours=1)).isoformat(), "required_support": ["TRANSPORT"], "importance": "HIGH"})
    assert made.status_code == 201, made.text
    aid = made.json()["id"]
    assert coord.post(f"/api/v1/activities/{aid}/assignments", headers=H, json={"caregiver_id": holder, "role": "PRIMARY", "confirm_now": True}).status_code in (200, 201)
    assert coord.put(f"/api/v1/patients/{pid}/care-preferences", headers=H, json={"languages": ["Konkani"]}).status_code == 200
    req = coord.post(f"/api/v1/activities/{aid}/cover-requests", headers=H, json={"note": "Fictional"}).json()
    ranking = coord.get(f"/api/v1/cover-requests/{req['id']}").json()["ranking"]
    rows = {c["caregiver_id"]: c for c in ranking["candidates"]}
    assert rows[man_cid]["eligible"] and rows[woman_cid]["eligible"]
    labels = [p["label"] for p in rows[woman_cid]["score_breakdown"]]
    assert "Speaks Konkani" in labels and any(l.startswith("Reputation") for l in labels)
    assert ranking["candidates"][0]["caregiver_id"] == woman_cid


# --- suggestions -------------------------------------------------------------------------------------------------------

def test_suggestions_are_listed_but_never_added_or_offered(monkeypatch):
    monkeypatch.setattr(settings, "auto_coordination", True)
    coord, pid = primary_contact_with_patient()
    holder, _ = caretaker(coord, pid, name="Only holder", caps=("TRANSPORT",))
    _, outside = listed("Outside helper", city="Testville", languages=("Konkani",))
    with SessionLocal() as db:
        db.get(Caregiver, uuid.UUID(outside)).capabilities = ["TRANSPORT"]; db.commit()
    coord.put(f"/api/v1/patients/{pid}/care-preferences", headers=H, json={"sector_code": "WEST", "city": "Testville", "languages": ["Konkani"]})
    start = (now() + timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
    aid = coord.post(f"/api/v1/patients/{pid}/activities", headers=H, json={"title": "Fictional ride", "category": "TRANSPORT", "scheduled_start": start.isoformat(),
                                                                           "scheduled_end": (start + timedelta(hours=1)).isoformat(), "required_support": ["TRANSPORT"]}).json()["id"]
    coord.post(f"/api/v1/activities/{aid}/assignments", headers=H, json={"caregiver_id": holder, "role": "PRIMARY", "confirm_now": True})
    req = coord.post(f"/api/v1/activities/{aid}/cover-requests", headers=H, json={"note": "Fictional"}).json()
    ranking = coord.get(f"/api/v1/cover-requests/{req['id']}").json()["ranking"]
    assert ranking["eligible_count"] == 0
    assert ranking["suggestions"]  # the directory has caretakers who could do it
    s = ranking["suggestions"][0]
    outside = s["caregiver_id"]
    assert s["prompt"] == f"Send a request to {s['name'].split()[0]}?" and s["why"]
    assert coord.post(f"/api/v1/cover-requests/{req['id']}/offer", headers=H, json={"caregiver_id": outside}).status_code in (403, 404, 409, 422)
    with SessionLocal() as db:
        assert db.scalar(select(CoverRequest.offered_caregiver_id).where(CoverRequest.id == uuid.UUID(req["id"]))) is None
        assert not db.scalar(select(CareTeamMember.id).join(Caregiver, Caregiver.user_id == CareTeamMember.user_id).where(Caregiver.id == uuid.UUID(outside), CareTeamMember.patient_id == uuid.UUID(pid)))
        assert not db.scalar(select(HireRequest.id).where(HireRequest.caregiver_id == uuid.UUID(outside), HireRequest.patient_id == uuid.UUID(pid)))


# --- removal and Command Center ----------------------------------------------------------------------------------------

def test_removing_a_member_does_not_strand_their_tasks(monkeypatch):
    monkeypatch.setattr(settings, "auto_coordination", False)
    coord, pid = primary_contact_with_patient()
    leaving, _ = caretaker(coord, pid, name="Leaving caretaker", caps=("TRANSPORT",))
    caretaker(coord, pid, name="Staying caretaker", caps=("TRANSPORT",))
    start = (now() + timedelta(days=5)).replace(minute=0, second=0, microsecond=0)
    aid = coord.post(f"/api/v1/patients/{pid}/activities", headers=H, json={"title": "Fictional far ride", "category": "TRANSPORT", "scheduled_start": start.isoformat(),
                                                                           "scheduled_end": (start + timedelta(hours=1)).isoformat(), "required_support": ["TRANSPORT"]}).json()["id"]
    coord.post(f"/api/v1/activities/{aid}/assignments", headers=H, json={"caregiver_id": leaving, "role": "PRIMARY", "confirm_now": True})
    member = next(m for m in coord.get(f"/api/v1/patients/{pid}/care-team").json()["items"] if m["name"] == "Leaving caretaker")
    assert coord.delete(f"/api/v1/patients/{pid}/care-team/{member['id']}", headers=H).status_code == 204
    with SessionLocal() as db:
        req = db.scalar(select(CoverRequest).where(CoverRequest.activity_id == uuid.UUID(aid)))
        assert req is not None and req.status in ("OPEN", "OFFERED") and str(req.replaced_caregiver_id) == leaving


def test_command_center_warns_about_weak_backups_and_clears(monkeypatch):
    coord, pid = primary_contact_with_patient()
    holder, _ = caretaker(coord, pid, name="Main holder", caps=("TRANSPORT",))
    backup, _ = caretaker(coord, pid, name="Unrated backup", caps=("TRANSPORT",))
    start = (now() + timedelta(hours=30)).replace(minute=0, second=0, microsecond=0)
    aid = coord.post(f"/api/v1/patients/{pid}/activities", headers=H, json={"title": "Fictional key visit", "category": "APPOINTMENT", "importance": "HIGH", "scheduled_start": start.isoformat(),
                                                                           "scheduled_end": (start + timedelta(hours=1)).isoformat(), "required_support": ["TRANSPORT"]}).json()["id"]
    coord.post(f"/api/v1/activities/{aid}/assignments", headers=H, json={"caregiver_id": holder, "role": "PRIMARY", "confirm_now": True})
    coord.post(f"/api/v1/activities/{aid}/assignments", headers=H, json={"caregiver_id": backup, "role": "BACKUP", "confirm_now": True})
    coord.put(f"/api/v1/patients/{pid}/care-preferences", headers=H, json={"min_rating": 60})
    def kinds():
        center = coord.get(f"/api/v1/command-center?patient_id={pid}").json()
        return {a["kind"] for s in ("needs_now", "at_risk", "decisions_waiting", "pending_actions") for a in center[s]}
    assert "BACKUP_BELOW_MIN_RATING" in kinds()
    coord.put(f"/api/v1/patients/{pid}/care-preferences", headers=H, json={"min_rating": None})
    assert "BACKUP_BELOW_MIN_RATING" not in kinds()


def test_open_hire_requests_show_as_one_quiet_item():
    coord, pid = primary_contact_with_patient()
    for name in ("Quiet one", "Quiet two"):
        send(coord, pid, listed(name)[1])
    center = coord.get(f"/api/v1/command-center?patient_id={pid}").json()
    items = [a for s in ("needs_now", "at_risk", "decisions_waiting", "pending_actions") for a in center[s] if a["kind"] == "HIRE_REQUESTS_OPEN"]
    assert len(items) == 1 and items[0]["title"] == "2 hire requests waiting for an answer" and items[0]["severity"] == "LOW"


def test_preferences_are_edited_by_the_primary_contact_only():
    coord, pid = primary_contact_with_patient()
    carer_id, carer = caretaker(coord, pid)
    assert carer.put(f"/api/v1/patients/{pid}/care-preferences", headers=H, json={}).status_code == 403
    assert coord.put(f"/api/v1/patients/{pid}/care-preferences", headers=H, json={"capabilities": ["TELEPATHY"]}).status_code == 422
    saved = coord.put(f"/api/v1/patients/{pid}/care-preferences", headers=H, json={"languages": ["tamil", "Tamil"], "min_rating": 70}).json()
    assert saved["languages"] == ["Tamil"] and saved["min_rating"] == 70 and "gender" not in saved
    assert coord.put(f"/api/v1/patients/{pid}/care-preferences", headers=H, json={"gender": "FEMALE"}).status_code == 422  # gender is a filter now


def test_insights_show_a_team_reputation_summary_per_patient():
    from tests.helpers import join_as_professional
    coord, pid = primary_contact_with_patient()
    rated, _ = caretaker(coord, pid, name="Rated member")
    caretaker(coord, pid, name="Unrated member")
    with SessionLocal() as db:
        from app.models import AgencyRating
        db.add(AgencyRating(caregiver_id=uuid.UUID(rated), rating=4.0)); db.commit()
    pro, *_ = join_as_professional(coord, pid)
    row = next(p for p in pro.get("/api/v1/insights/professional?days=30").json()["patients"] if p["id"] == pid)
    assert row["team_reputation"] == {"caretakers": 2, "unrated": 1, "average": 75.0, "lowest": 75.0}


def test_team_matches_carry_the_agency_rating_and_can_filter_by_it():
    from app.models import AgencyRating
    coord, pid = primary_contact_with_patient()
    _, high = listed("Agency star", city="Agencyville")
    _, low = listed("Agency low", city="Agencyville")
    _, none = listed("Independent one", city="Agencyville")
    with SessionLocal() as db:
        db.add_all([AgencyRating(caregiver_id=uuid.UUID(high), rating=4.6), AgencyRating(caregiver_id=uuid.UUID(low), rating=3.2)]); db.commit()
    coord.put(f"/api/v1/patients/{pid}/care-preferences", headers=H, json={"city": "Agencyville"})
    rows = {m["caregiver_id"]: m for m in coord.get(f"/api/v1/patients/{pid}/team-matches?limit=50&city=Agencyville").json()["items"]}
    assert rows[high]["agency_rating"] == 4.6 and rows[low]["agency_rating"] == 3.2 and rows[none]["agency_rating"] is None
    filtered = {m["caregiver_id"] for m in coord.get(f"/api/v1/patients/{pid}/team-matches?limit=50&city=Agencyville&min_agency_rating=4").json()["items"]}
    assert high in filtered and low not in filtered and none not in filtered
    assert coord.get(f"/api/v1/patients/{pid}/team-matches?min_agency_rating=0.5").status_code == 422


def test_the_merged_list_applies_directory_filters_and_ranks_like_a_backup():
    from app.models import AgencyRating, PatientSupportNeed
    coord, pid = primary_contact_with_patient()
    with SessionLocal() as db:
        db.add_all([PatientSupportNeed(patient_id=uuid.UUID(pid), support_code="TRANSPORT"), PatientSupportNeed(patient_id=uuid.UUID(pid), support_code="LAB_ESCORT")]); db.commit()
    _, both = listed("Mergeville both", city="Mergeville", gender="FEMALE")
    _, one = listed("Mergeville one", city="Mergeville", gender="FEMALE")
    _, man = listed("Mergeville man", city="Mergeville", gender="MALE")
    with SessionLocal() as db:
        db.get(Caregiver, uuid.UUID(both)).capabilities = ["TRANSPORT", "LAB_ESCORT"]
        db.get(Caregiver, uuid.UUID(one)).capabilities = ["TRANSPORT"]
        db.get(Caregiver, uuid.UUID(man)).capabilities = ["TRANSPORT", "LAB_ESCORT"]
        db.add(AgencyRating(caregiver_id=uuid.UUID(one), rating=5.0)); db.commit()
    body = coord.get(f"/api/v1/patients/{pid}/team-matches?city=Mergeville&limit=10&must_have=").json()
    ids = [m["caregiver_id"] for m in body["items"]]
    assert set(ids) == {both, one, man} and body["total"] == 3 and body["needs"] == ["LAB_ESCORT", "TRANSPORT"]
    top = body["items"][0]
    assert ids.index(both) < ids.index(one) or body["items"][ids.index(one)]["score"] >= top["score"]  # capability coverage counts
    labels = [p["label"] for p in body["items"][ids.index(both)]["points"]]
    assert any(l.startswith("Can ") and l.endswith("(2 of 2 needs)") for l in labels)
    assert all("phone" not in m and "private" not in m for m in body["items"])
    women = {m["caregiver_id"] for m in coord.get(f"/api/v1/patients/{pid}/team-matches?city=Mergeville&gender=FEMALE&must_have=").json()["items"]}
    assert women == {both, one}
    rated = {m["caregiver_id"] for m in coord.get(f"/api/v1/patients/{pid}/team-matches?city=Mergeville&min_agency_rating=4.5&must_have=").json()["items"]}
    assert rated == {one}
    assert len(coord.get(f"/api/v1/patients/{pid}/team-matches?city=Mergeville&limit=1&must_have=").json()["items"]) == 1
    names = [m["name"] for m in coord.get(f"/api/v1/patients/{pid}/team-matches?city=Mergeville&sort=name&must_have=").json()["items"]]
    assert names == sorted(names, key=str.lower)
    coord.put(f"/api/v1/patients/{pid}/care-preferences", headers=H, json={"capabilities": ["LAB_ESCORT"]})  # must-have skill is a hard rule
    assert {m["caregiver_id"] for m in coord.get(f"/api/v1/patients/{pid}/team-matches?city=Mergeville").json()["items"]} == {both, man}
    assert coord.get(f"/api/v1/patients/{pid}/team-matches?capability=FLYING").status_code == 422


def test_team_matches_take_several_states_cities_languages_and_skills():
    coord, pid = primary_contact_with_patient()
    _, a = listed("Multi A", city="Alphaville", state="Kerala", languages=("Malayalam",))
    _, b = listed("Multi B", city="Betatown", state="Goa", languages=("Konkani",))
    _, c = listed("Multi C", city="Gammaburg", state="Kerala", languages=("Tamil",))
    with SessionLocal() as db:
        db.get(Caregiver, uuid.UUID(a)).capabilities = ["LAB_ESCORT"]; db.get(Caregiver, uuid.UUID(b)).capabilities = ["SUPPLIES"]; db.get(Caregiver, uuid.UUID(c)).capabilities = ["TRANSPORT"]; db.commit()
    get = lambda q: {m["caregiver_id"] for m in coord.get(f"/api/v1/patients/{pid}/team-matches?limit=50&{q}").json()["items"]}
    assert get("city=Alphaville&city=Betatown") == {a, b}
    assert get("city=Alphaville,Betatown,Gammaburg&language=Konkani&language=Tamil") == {b, c}
    assert get("city=Alphaville,Betatown,Gammaburg&capability=LAB_ESCORT,SUPPLIES") == {a, b}
    assert get("state=Kerala&city=Alphaville,Betatown,Gammaburg") == {a, c}


def test_the_patients_must_help_skills_filter_the_list():
    """Regression: the help the patient needs (Patient Profile) and the must-haves ticked on screen only added points."""
    from app.models import PatientSupportNeed
    coord, pid = primary_contact_with_patient()
    _, has = listed("Mustville has", city="Mustville")
    _, lacks = listed("Mustville lacks", city="Mustville")
    with SessionLocal() as db:
        db.get(Caregiver, uuid.UUID(has)).capabilities = ["LAB_ESCORT", "TRANSPORT"]; db.get(Caregiver, uuid.UUID(lacks)).capabilities = ["TRANSPORT"]
        db.add(PatientSupportNeed(patient_id=uuid.UUID(pid), support_code="LAB_ESCORT")); db.commit()
    get = lambda q="": {m["caregiver_id"] for m in coord.get(f"/api/v1/patients/{pid}/team-matches?city=Mustville{q}").json()["items"]}
    assert get() == {has}                                   # the patient's own needs are required
    assert get("&must_have=TRANSPORT") == {has, lacks}      # ticked on screen (not yet saved): exactly these are required
    assert get("&must_have=LAB_ESCORT,TRANSPORT") == {has}  # all of them, not any
    body = coord.get(f"/api/v1/patients/{pid}/team-matches?city=Mustville").json()
    assert body["must_have"] == ["LAB_ESCORT"]
    assert coord.get(f"/api/v1/patients/{pid}/team-matches?must_have=FLYING").status_code == 422
