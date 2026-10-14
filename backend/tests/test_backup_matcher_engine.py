from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.engine.backup_matcher import rank_candidates, support_phrase

ZONE = ZoneInfo("Asia/Kolkata")
START = datetime(2026, 10, 12, tzinfo=ZONE)  # Monday
END = START + timedelta(days=1)
NOW = START - timedelta(hours=12)
ANYTIME = [{"weekday": d, "start_min": 0, "end_min": 1440} for d in range(7)]


def cg(cid, kind="FAMILY", caps=("TRANSPORT",), day=3, week=40.0, *, backup=False, schedule=None, overrides=()):
    return {"id": cid, "name": cid.title(), "kind": kind, "capabilities": list(caps), "max_activities_per_day": day, "max_hours_per_week": week,
            "is_active": True, "is_designated_backup": backup, "schedule": ANYTIME if schedule is None else schedule, "overrides": list(overrides)}


def act(aid, hour, minute=0, support=("TRANSPORT",), minutes=60):
    start = START + timedelta(hours=hour, minutes=minute)
    return {"id": aid, "title": aid.title(), "category": "TRANSPORT", "importance": "MEDIUM", "required_support": list(support), "scheduled_start": start,
            "window_start": start, "window_end": start + timedelta(minutes=minutes), "requires_caregiver": True, "linked_activity_ids": []}


def held(cid, activity, own=True):
    return {"assignment_id": f"as-{activity['id']}-{cid}", "caregiver_id": cid, "activity_id": activity["id"], "own_patient": own, "status": "CONFIRMED",
            "scheduled_start": activity["scheduled_start"], "window_start": activity["window_start"], "window_end": activity["window_end"]}


def rank(caregivers, activities, commitments, target="ride", **kwargs):
    snapshot = {"caregivers": caregivers, "activities": activities, "commitments": commitments, "confirmed_backups": kwargs.pop("backups", {}),
                "history": kwargs.pop("history", {})}
    return rank_candidates(snapshot, NOW, START, END, target, **kwargs)


def by_id(result):
    return {c["caregiver_id"]: c for c in result["candidates"]}


def test_example_available_committed_and_missing_capability_are_explained():
    ride, other = act("ride", 10), act("errand", 10, 30)
    result = rank([cg("anna"), cg("bala"), cg("chitra", "HOUSEHELP", ("DAILY_ASSIST",))], [ride], [held("bala", other, own=False)])
    rows = by_id(result)
    assert rows["anna"]["headline"] == "Anna can provide transport and is available 10:00–11:00."
    assert rows["bala"]["status"] == "COMMITTED" and rows["bala"]["headline"] == "Bala is already committed at that time."
    assert rows["chitra"]["status"] == "MISSING_CAPABILITY" and rows["chitra"]["headline"] == "Chitra is available but lacks the transport capability."
    assert result["summary"] == "1 of 3 people in the network can take this." and result["best"]["caregiver_id"] == "anna"
    assert [c["caregiver_id"] for c in result["candidates"]] == ["anna", "bala", "chitra"]


def test_professional_tasks_need_qualified_caregivers():
    visit = act("visit", 9, support=("CLINICAL_VISIT",))
    rows = by_id(rank([cg("nurse", "NURSE", ("CLINICAL_VISIT",)), cg("family", "FAMILY", ("CLINICAL_VISIT",))], [visit], [], target="visit"))
    assert rows["nurse"]["eligible"] and rows["family"]["status"] == "NOT_QUALIFIED"


def test_continuity_outranks_slightly_more_headroom():
    ride = act("ride", 10)
    caregivers = [cg("fresh", day=5), cg("regular", day=3, backup=True)]
    result = rank(caregivers, [ride], [], backups={"ride": ["regular"]}, history={"regular": {"patient_tasks": 4, "same_series": 2, "same_category": 3}})
    best = result["best"]
    assert best["caregiver_id"] == "regular"
    labels = " ".join(p["label"] for p in best["score_breakdown"])
    assert "confirmed backup" in labels and "recurring task before (2×)" in labels and "Supported this patient recently (4 tasks)" in labels
    assert any(r.startswith("Continuity:") for r in best["reasons"])


def test_tight_travel_connection_is_penalised_and_explained():
    ride = act("ride", 10)
    earlier = act("school-run", 8, 45, minutes=60)  # ends 09:45, 15 minutes before the buffered window
    rows = by_id(rank([cg("tight"), cg("clear")], [ride], [held("tight", earlier, own=False)]))
    assert rows["tight"]["eligible"] and rows["tight"]["tight_connection"] == {"gap_minutes": 15}
    assert any("Tight connection: another commitment ends at 09:45" in r for r in rows["tight"]["reasons"])
    assert rows["clear"]["score"] > rows["tight"]["score"]


def test_replaced_declined_absent_and_limit_rules():
    ride = act("ride", 10)
    away = cg("away", overrides=[{"start_at": START, "end_at": END, "status": "UNAVAILABLE"}])
    full = cg("full", day=1)
    first = act("first", 7)
    rows = by_id(rank([cg("holder"), cg("refused"), away, full, cg("ok")], [ride], [held("holder", ride), held("full", first, own=False)],
                      replaced_caregiver_id="holder", declined_caregiver_ids=["refused"]))
    assert rows["holder"]["status"] == "REPLACED" and rows["refused"]["status"] == "DECLINED_REQUEST"
    assert rows["away"]["status"] == "UNAVAILABLE" and "recorded absence" in rows["away"]["headline"]
    assert rows["full"]["status"] == "AT_LIMIT" and "daily limit (2/1" in rows["full"]["headline"]
    assert [c["caregiver_id"] for c in rank([cg("holder"), cg("ok")], [ride], [held("holder", ride)], replaced_caregiver_id="holder")["candidates"]][0] == "ok"


def test_ranking_is_deterministic_and_phrases_cover_all_support():
    ride = act("ride", 10)
    caregivers = [cg("b"), cg("a"), cg("c", day=2)]
    assert rank(caregivers, [ride], []) == rank(caregivers, [ride], [])
    assert support_phrase(["TRANSPORT", "APPOINTMENT_ESCORT"]) == "provide transport and escort to the appointment"
    assert support_phrase([]) == "take this task"
