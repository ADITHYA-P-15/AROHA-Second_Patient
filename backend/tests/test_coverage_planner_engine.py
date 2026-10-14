from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.engine.coverage_planner import forecast, secure_by

ZONE = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 14, 9, 0, tzinfo=ZONE)  # Wednesday morning
DAY0 = datetime(2026, 10, 14, tzinfo=ZONE)
ANYTIME = [{"weekday": d, "start_min": 0, "end_min": 1440} for d in range(7)]


def cg(cid, kind="FAMILY", caps=("APPOINTMENT_ESCORT",), day=3, *, overrides=(), schedule=None):
    return {"id": cid, "name": cid.title(), "kind": kind, "capabilities": list(caps), "max_activities_per_day": day, "max_hours_per_week": 40.0,
            "is_active": True, "is_designated_backup": False, "schedule": ANYTIME if schedule is None else schedule, "overrides": list(overrides)}


def act(aid, days, hour, support=("APPOINTMENT_ESCORT",), importance="HIGH", title=None):
    start = DAY0 + timedelta(days=days, hours=hour)
    return {"id": aid, "title": title or aid.title(), "category": "APPOINTMENT", "importance": importance, "required_support": list(support),
            "scheduled_start": start, "window_start": start, "window_end": start + timedelta(hours=1), "requires_caregiver": True, "linked_activity_ids": []}


def held(cid, activity, status="CONFIRMED"):
    return {"assignment_id": f"as-{activity['id']}", "caregiver_id": cid, "activity_id": activity["id"], "own_patient": True, "status": status,
            "scheduled_start": activity["scheduled_start"], "window_start": activity["window_start"], "window_end": activity["window_end"]}


def run(caregivers, activities, commitments, backups=None, demand=None):
    snapshot = {"caregivers": caregivers, "activities": activities, "commitments": commitments, "confirmed_backups": backups or {}}
    return forecast(snapshot, NOW, DAY0, DAY0 + timedelta(days=9), demand=demand)


def finding(result, aid):
    return next(f for f in result["findings"] if f["activity"]["id"] == aid)


def test_covered_but_only_eligible_person_is_a_single_point_with_backup_deadline():
    # Monday 19 Oct appointment; Savitha is the only one with the capability. Ravi has it but is at his limit.
    appt = act("appt", 5, 10, title="Appointment")
    busy = [act(f"r{i}", 5, 13 + i, title=f"Errand {i}") for i in range(1)]
    result = run([cg("savitha"), cg("ravi", day=1), cg("meena", caps=("SUPPLIES",))], [appt] + busy, [held("savitha", appt), held("ravi", busy[0])])
    item = finding(result, "appt")
    assert item["kind"] == "SINGLE_POINT"
    assert item["headline"] == "Monday's Appointment is covered, but Savitha is the only eligible person. Arrange a backup before Sat 17 Oct, 10:00."
    assert [n["name"] for n in item["near_miss"]] == ["Ravi"] and item["suggestion"] == "Ask Ravi to stand by as backup."
    assert item["secure_now"] is False and result["people"][0]["message"].startswith("If Savitha is unavailable, 1 task has no alternative")


def test_gaps_unconfirmed_and_ok_with_confirmed_standby_backup():
    open_task = act("open", 1, 10)
    absent_task = act("absent", 2, 10)
    pending = act("pending", 0, 15)
    backed = act("backed", 3, 10)
    away = cg("away", overrides=[{"start_at": absent_task["window_start"], "end_at": absent_task["window_end"], "status": "UNAVAILABLE"}])
    full = cg("standby", day=0)  # at its limit, but a confirmed standby backup still counts as ready
    result = run([cg("anil"), away, full], [open_task, absent_task, pending, backed],
                 [held("away", absent_task), held("anil", pending, "AWAITING_CONFIRMATION"), held("anil", backed)], backups={"backed": ["standby"]})
    assert finding(result, "open")["kind"] == "GAP" and finding(result, "open")["headline"].endswith("has no caregiver yet.")
    gap = finding(result, "absent")
    assert gap["kind"] == "GAP" and "(recorded absence)" in gap["reason"] and gap["action"]["option"] == "FIND_COVER"
    assert finding(result, "pending")["kind"] == "UNCONFIRMED" and finding(result, "pending")["severity"] == "HIGH"
    assert all(f["activity"]["id"] != "backed" for f in result["findings"])
    assert result["horizons"]["24h"] == {"tasks": 1, "gaps": 0, "unconfirmed": 1, "single_points": 0, "covered_with_backup": 0, "secure_now": 1}
    assert result["horizons"]["7d"]["tasks"] == 4 and result["horizons"]["7d"]["covered_with_backup"] == 1


def test_secure_by_lead_times_and_waking_hours():
    start = datetime(2026, 10, 20, 10, 0, tzinfo=ZONE)
    assert secure_by(start, "CRITICAL", NOW, ZONE)[0] == datetime(2026, 10, 17, 10, 0, tzinfo=ZONE)
    assert secure_by(start, "LOW", NOW, ZONE)[0] == datetime(2026, 10, 19, 20, 0, tzinfo=ZONE)  # 22:00 moves to 20:00
    early = datetime(2026, 10, 20, 7, 0, tzinfo=ZONE)
    assert secure_by(early, "MEDIUM", NOW, ZONE)[0] == datetime(2026, 10, 18, 20, 0, tzinfo=ZONE)  # 07:00 the day before moves to the previous evening
    assert secure_by(datetime(2026, 10, 14, 12, 0, tzinfo=ZONE), "HIGH", NOW, ZONE)[1] is True


def test_days_flag_insufficient_capacity_and_absent_people_are_not_suggested():
    visit = act("visit", 1, 11, support=("CLINICAL_VISIT",), title="Nurse visit")
    absent = cg("karthik", overrides=[{"start_at": visit["window_start"], "end_at": visit["window_end"], "status": "UNAVAILABLE"}])
    result = run([cg("anita"), absent], [visit], [], demand=[{"date": "2026-10-16", "level": "ELEVATED", "tasks": 4, "reasons": ["Busy day"]}])
    day = next(d for d in result["days"] if d["date"] == "2026-10-15")
    assert day["level"] == "INSUFFICIENT" and day["reasons"][0] == "1 task with no eligible caregiver."
    assert next(d for d in result["days"] if d["date"] == "2026-10-16")["level"] == "TIGHT"
    appt = act("appt", 2, 10)
    single = run([cg("anita"), cg("karthik", overrides=[{"start_at": appt["window_start"], "end_at": appt["window_end"], "status": "UNAVAILABLE"}])], [appt], [held("anita", appt)])
    assert finding(single, "appt")["near_miss"] == []
