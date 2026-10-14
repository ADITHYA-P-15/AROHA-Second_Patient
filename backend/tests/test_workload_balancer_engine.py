from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.engine.workload_balancer import check_receiver, delegation_class, evaluate_workload

ZONE = ZoneInfo("Asia/Kolkata")
START = datetime(2026, 10, 12, tzinfo=ZONE)  # Monday
END = START + timedelta(days=7)
NOW = START + timedelta(hours=6)
ANYTIME = [{"weekday": d, "start_min": 0, "end_min": 1440} for d in range(7)]


def cg(cid, kind="FAMILY", caps=("TRANSPORT",), day=3, week=40.0, *, active=True, backup=False, schedule=None, overrides=()):
    return {"id": cid, "name": cid.title(), "kind": kind, "capabilities": list(caps), "max_activities_per_day": day, "max_hours_per_week": week,
            "is_active": active, "is_designated_backup": backup, "schedule": ANYTIME if schedule is None else schedule, "overrides": list(overrides)}


def act(aid, day, hour, support=("TRANSPORT",), importance="MEDIUM", minutes=60, linked=()):
    start = START + timedelta(days=day, hours=hour)
    return {"id": aid, "title": aid.replace("-", " ").title(), "category": "OTHER", "importance": importance, "required_support": list(support),
            "scheduled_start": start, "window_start": start, "window_end": start + timedelta(minutes=minutes), "requires_caregiver": True,
            "linked_activity_ids": list(linked)}


def held(caregiver_id, activity, *, own=True, status="CONFIRMED"):
    return {"assignment_id": f"as-{activity['id']}", "caregiver_id": caregiver_id, "activity_id": activity["id"], "own_patient": own, "status": status,
            "scheduled_start": activity["scheduled_start"], "window_start": activity["window_start"], "window_end": activity["window_end"]}


def run(caregivers, activities, commitments, backups=None, now=NOW):
    return evaluate_workload({"caregivers": caregivers, "activities": activities, "commitments": commitments, "confirmed_backups": backups or {}}, now, START, END)


def test_daily_overload_recommends_capable_available_receiver_with_explanation():
    tasks = [act(f"t{i}", 1, 8 + 2 * i) for i in range(4)]
    result = run([cg("anita"), cg("karthik"), cg("savitha", "HOUSEHELP", ("DAILY_ASSIST",))], tasks, [held("anita", t) for t in tasks])
    anita = next(c for c in result["caregivers"] if c["caregiver_id"] == "anita")
    assert anita["status"] == "OVERLOADED" and anita["load_score"] == 133
    assert "4 tasks on Tue 13 Oct; the daily limit is 3" in anita["reasons"][0]
    recs = [r for r in result["recommendations"] if r["kind"] == "REDISTRIBUTE"]
    assert len(recs) == 1 and recs[0]["priority"] == "HIGH" and recs[0]["to"]["caregiver_id"] == "karthik"
    # Anita still holds 3 of 4 tasks afterwards, so a low-priority dependency move follows the overload fix.
    assert [r["kind"] for r in result["recommendations"]][-1] == "REDUCE_DEPENDENCY"
    assert recs[0]["effect"]["from"] == {"tasks_before": 4, "tasks_after": 3, "limit": 3}
    assert recs[0]["score"] == sum(p["points"] for p in recs[0]["score_breakdown"])
    assert {"caregiver_id": "savitha", "name": "Savitha", "reasons": ["Missing capability: transport."]} in recs[0]["excluded"]
    assert result["summary"]["overloaded"] == 1 and result["summary"]["recommendations"] == 2


def test_professional_tasks_only_move_to_qualified_professionals():
    assert delegation_class(["CLINICAL_VISIT"]) == "PROFESSIONAL"
    assert delegation_class(["MEDICATION_ASSIST"]) == "TRAINED"
    assert delegation_class(["SUPPLIES"]) == "GENERAL"
    visits = [act(f"visit{i}", 2, 9 + 2 * i, ("CLINICAL_VISIT",)) for i in range(2)]
    caregivers = [cg("divya", "NURSE", ("CLINICAL_VISIT",), day=1), cg("family", "FAMILY", ("CLINICAL_VISIT",)), cg("asha", "NURSE", ("CLINICAL_VISIT",))]
    result = run(caregivers, visits, [held("divya", v) for v in visits])
    rec = result["recommendations"][0]
    assert rec["activity"]["delegation_class"] == "PROFESSIONAL" and rec["to"]["caregiver_id"] == "asha"
    assert any(x["caregiver_id"] == "family" and "Needs a qualified healthcare professional." in x["reasons"] for x in rec["excluded"])


def test_general_tasks_prefer_keeping_professionals_free():
    tasks = [act(f"t{i}", 1, 8 + 2 * i) for i in range(2)]
    result = run([cg("anita", day=1), cg("nurse", "NURSE", ("TRANSPORT",)), cg("karthik")], tasks, [held("anita", t) for t in tasks])
    rec = result["recommendations"][0]
    assert rec["to"]["caregiver_id"] == "karthik"
    nurse = next(x for x in rec["alternatives"] if x["caregiver_id"] == "nurse")
    assert any(p["points"] < 0 and "healthcare professional free" in p["label"] for p in nurse["score_breakdown"])


def test_no_eligible_receiver_explains_every_exclusion():
    tasks = [act(f"t{i}", 1, 8 + 2 * i) for i in range(2)]
    busy = act("busy", 1, 8)
    off = cg("off", overrides=[{"start_at": START, "end_at": END, "status": "UNAVAILABLE"}])
    result = run([cg("anita", day=1), cg("booked"), off, cg("full", day=0)], tasks + [busy], [held("anita", t) for t in tasks] + [held("booked", busy, own=False)])
    rec = next(r for r in result["recommendations"] if r["kind"] == "NO_ELIGIBLE_RECEIVER")
    reasons = {x["caregiver_id"]: " ".join(x["reasons"]) for x in rec["excluded"]}
    assert "Not available" in reasons["off"] and "daily limit (1/0" in reasons["full"]
    assert rec["to"] is None and result["summary"]["unresolved_overloads"] >= 1


def test_overlap_weekly_hours_and_lead_time_rules():
    long_tasks = [act(f"long{i}", i, 9, minutes=300) for i in range(3)]
    double = [act("a", 3, 10), act("b", 3, 10, minutes=30)]
    soon = act("soon", 0, 7)  # 07:00 today; NOW is 06:00 -> inside the two-hour lead
    caregivers = [cg("anita", week=10.0, day=5), cg("karthik", week=40.0)]
    result = run(caregivers, long_tasks + double + [soon], [held("anita", t) for t in long_tasks + double + [soon]])
    anita = next(c for c in result["caregivers"] if c["caregiver_id"] == "anita")
    codes = {f["code"] for f in anita["flags"]}
    assert {"WEEKLY_HOURS_EXCEEDED", "OVERLAPPING_COMMITMENTS"} <= codes
    moved = {r["activity"]["id"] for r in result["recommendations"]}
    assert "soon" not in moved and moved & {"a", "b"}
    assert all(r["to"]["caregiver_id"] == "karthik" for r in result["recommendations"] if r["kind"] == "REDISTRIBUTE")


def test_greedy_plan_spreads_work_when_receivers_have_small_limits():
    tasks = [act(f"t{i}", 1, 8 + 2 * i) for i in range(5)]
    result = run([cg("anita", day=3), cg("karthik", day=1), cg("suresh", day=1)], tasks, [held("anita", t) for t in tasks])
    receivers = sorted(r["to"]["caregiver_id"] for r in result["recommendations"])
    assert receivers == ["karthik", "suresh"]


def test_demand_dependency_and_determinism():
    visit = act("visit", 2, 9, ("CLINICAL_VISIT",))
    routine = [act(f"r{i}", i, 9 + i, ("SUPPLIES",)) for i in range(4)]
    weekday_nurse = cg("divya", "NURSE", ("CLINICAL_VISIT",), schedule=[{"weekday": d, "start_min": 480, "end_min": 1020} for d in range(5)])
    caregivers = [weekday_nurse, cg("anita", caps=("SUPPLIES",), day=5), cg("karthik", caps=("SUPPLIES",))]
    commitments = [held("divya", visit)] + [held("anita", r) for r in routine]
    first = run(caregivers, [visit] + routine, commitments)
    assert first == run(caregivers, [visit] + routine, commitments)
    kinds = {d["kind"] for d in first["dependency"]}
    assert {"SINGLE_QUALIFIED_CAREGIVER", "CONCENTRATED_LOAD"} <= kinds
    reduce = [r for r in first["recommendations"] if r["kind"] == "REDUCE_DEPENDENCY"]
    assert reduce and all(r["priority"] == "LOW" and r["to"]["caregiver_id"] == "karthik" for r in reduce)
    weekend = act("weekend-visit", 5, 10, ("CLINICAL_VISIT",))
    second = run(caregivers, [weekend], [held("divya", weekend)])
    saturday = next(d for d in second["demand"] if d["date"] == "2026-10-17")
    assert saturday["level"] == "HIGH" and saturday["qualified_available"] == 0
    assert next(c for c in second["caregivers"] if c["caregiver_id"] == "divya")["status"] == "NEEDS_REVIEW"


def test_check_receiver_rechecks_current_state():
    task = act("t0", 1, 9, ("TRANSPORT",))
    snapshot = {"caregivers": [cg("anita"), cg("karthik"), cg("savitha", "HOUSEHELP", ("DAILY_ASSIST",))], "activities": [task], "commitments": [held("anita", task)], "confirmed_backups": {}}
    assert check_receiver(snapshot, NOW, START, END, "t0", "anita", "karthik") == (True, [])
    ok, reasons = check_receiver(snapshot, NOW, START, END, "t0", "anita", "savitha")
    assert not ok and reasons == ["Missing capability: transport."]
    assert check_receiver(snapshot, NOW, START, END, "t0", "anita", "stranger")[0] is False


def test_unresolved_overload_is_one_card_per_period_not_per_task():
    tasks = [act(f"t{i}", i % 5, 8 + 3 * (i // 5), minutes=60) for i in range(10)]
    result = run([cg("anita", day=5, week=5.0), cg("helper", "HOUSEHELP", ("DAILY_ASSIST",))], tasks, [held("anita", t) for t in tasks])
    unresolved = [r for r in result["recommendations"] if r["kind"] == "NO_ELIGIBLE_RECEIVER"]
    assert len(unresolved) == 1 and result["summary"]["unresolved_overloads"] == 1
    assert len(unresolved[0]["unresolved_tasks"]) > 1 and "have no eligible receiver" in unresolved[0]["reasons"][-1]
