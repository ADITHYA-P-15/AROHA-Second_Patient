"""Coordination analytics for a healthcare professional's patients: doses taken, missed and late, trends, and what needs follow-up.

Deterministic counts over what the care team recorded. This is a coordination record, not a clinical assessment, and
nothing here is a medical risk score.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.config import settings
from app.models import CareActivity, CareAssignment, CareTeamMember, Incident, Patient, Prescription, TeamRole

RECENT_DAYS = 7
LOW_TAKEN_PCT = 75.0      # below this share of doses recorded as taken, follow-up is suggested
MISSED_RECENT = 3         # this many missed doses in the last 7 days suggests follow-up
MIN_DECIDED = 8           # fewer decided doses than this is "not enough data" for a percentage flag
TREND_DELTA = 8.0         # percentage points between the last 7 days and the 7 before
SPARK_DAYS = 14
NOTE = "Counts what the care team recorded. It is a coordination record, not a clinical assessment or a risk score."


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _pct(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def _tally() -> dict:
    return {"due": 0, "on_time": 0, "late": 0, "missed": 0, "pending": 0}


def _add(tally: dict, row: CareActivity) -> None:
    tally["due"] += 1
    if row.lifecycle_status == "COMPLETED": tally["late" if row.completed_late else "on_time"] += 1
    elif row.lifecycle_status == "MISSED": tally["missed"] += 1
    else: tally["pending"] += 1


def _rates(tally: dict) -> dict:
    decided = tally["on_time"] + tally["late"] + tally["missed"]
    return {**tally, "decided": decided, "taken_pct": _pct(tally["on_time"] + tally["late"], decided), "on_time_pct": _pct(tally["on_time"], decided)}


def _trend(recent: dict, before: dict) -> str:
    r, b = _rates(recent), _rates(before)
    if r["decided"] < 4 or b["decided"] < 4: return "not_enough_data"
    delta = r["taken_pct"] - b["taken_pct"]
    return "improving" if delta >= TREND_DELTA else "slipping" if delta <= -TREND_DELTA else "steady"


def professional_insights(db: Session, user, days: int = 30) -> dict:
    zone = ZoneInfo(settings.app_timezone)
    at = now()
    today = at.astimezone(zone).date()
    since = at - timedelta(days=max(days, 2 * RECENT_DAYS))
    ids = list(db.scalars(select(CareTeamMember.patient_id).where(CareTeamMember.user_id == user.id, CareTeamMember.team_role == TeamRole.PROFESSIONAL)))
    patients = {p.id: p for p in db.scalars(select(Patient).where(Patient.id.in_(ids)))} if ids else {}
    out_patients: list[dict] = []
    totals, medicine_totals = _tally(), defaultdict(lambda: {"due": 0, "on_time": 0, "late": 0, "missed": 0, "pending": 0, "patients": set()})
    daily: dict[str, dict] = defaultdict(_tally)
    if not ids:
        return _payload(at, days, totals, [], [], daily, today, zone, 0, 0, None)

    doses = db.scalars(select(CareActivity).where(CareActivity.patient_id.in_(ids), CareActivity.source == "PRESCRIPTION", CareActivity.lifecycle_status != "CANCELLED",
                                                  CareActivity.scheduled_start >= since, CareActivity.scheduled_start <= at)).all()
    medicine_names = {p.id: (p.medicine, p.dose) for p in db.scalars(select(Prescription).where(Prescription.patient_id.in_(ids)))}
    by_patient: dict = defaultdict(list)
    for row in doses: by_patient[row.patient_id].append(row)

    future = db.scalars(select(CareActivity).where(CareActivity.patient_id.in_(ids), CareActivity.source == "APPOINTMENT", CareActivity.lifecycle_status == "SCHEDULED",
                                                   CareActivity.scheduled_start > at, CareActivity.scheduled_start <= at + timedelta(days=60))
                        .order_by(CareActivity.scheduled_start)).all()
    covered = set(db.scalars(select(CareAssignment.activity_id).where(CareAssignment.activity_id.in_([a.id for a in future] or [None]), CareAssignment.role == "PRIMARY",
                                                                       CareAssignment.status == "CONFIRMED")))
    appts_by_patient: dict = defaultdict(list)
    for a in future: appts_by_patient[a.patient_id].append(a)

    incidents = db.scalars(select(Incident).where(Incident.patient_id.in_(ids), Incident.created_at >= at - timedelta(days=days))).all()
    open_by_patient: dict = defaultdict(int)
    ack_minutes: list[float] = []
    for inc in incidents:
        if inc.status in ("OPEN", "ACKNOWLEDGED"): open_by_patient[inc.patient_id] += 1
        if inc.acknowledged_at is not None: ack_minutes.append((_aware(inc.acknowledged_at) - _aware(inc.created_at)).total_seconds() / 60)

    window_start = at - timedelta(days=days)
    recent_start, before_start = at - timedelta(days=RECENT_DAYS), at - timedelta(days=2 * RECENT_DAYS)
    for pid, patient in patients.items():
        window, recent, before = _tally(), _tally(), _tally()
        meds: dict = defaultdict(_tally)
        spark: dict = defaultdict(_tally)
        for row in by_patient.get(pid, []):
            start = _aware(row.scheduled_start)
            day = start.astimezone(zone).date()
            if start >= window_start:
                _add(window, row); _add(totals, row); _add(daily[day.isoformat()], row)
                name = medicine_names.get(row.source_id, (row.title, ""))
                _add(meds[name], row)
                medicine_totals[name[0]]["patients"].add(pid)
                _add(medicine_totals[name[0]], row)
            if start >= recent_start: _add(recent, row)
            elif start >= before_start: _add(before, row)
            if (today - day).days < SPARK_DAYS: _add(spark[day.isoformat()], row)
        rates, r7 = _rates(window), _rates(recent)
        appts = appts_by_patient.get(pid, [])
        soon = [a for a in appts if _aware(a.scheduled_start) <= at + timedelta(days=7)]
        uncovered = [a for a in soon if a.id not in covered and a.requires_caregiver]
        flags = []
        if r7["missed"] >= MISSED_RECENT: flags.append({"code": "MISSED_RECENT", "text": f"{r7['missed']} doses not recorded as given in the last {RECENT_DAYS} days"})
        if rates["decided"] >= MIN_DECIDED and rates["taken_pct"] is not None and rates["taken_pct"] < LOW_TAKEN_PCT:
            flags.append({"code": "LOW_TAKEN", "text": f"Only {rates['taken_pct']:.0f}% of doses recorded as given over {days} days"})
        needs_follow_up = bool(flags)
        if uncovered: flags.append({"code": "UNCOVERED_APPOINTMENT", "text": f"{len(uncovered)} appointment{'s' if len(uncovered) != 1 else ''} in the next 7 days without a confirmed escort"})
        if open_by_patient.get(pid): flags.append({"code": "OPEN_REQUEST", "text": f"{open_by_patient[pid]} open help request{'s' if open_by_patient[pid] != 1 else ''}"})
        nxt = appts[0] if appts else None
        out_patients.append({
            "id": pid, "name": patient.name, "birth_year": patient.birth_year, "care_code": patient.care_code,
            **rates, "recent": {"due": r7["due"], "missed": r7["missed"], "taken_pct": r7["taken_pct"]},
            "trend": _trend(recent, before), "needs_follow_up": needs_follow_up, "flags": flags,
            "next_appointment": {"id": nxt.id, "title": nxt.title, "start": _aware(nxt.scheduled_start), "covered": nxt.id in covered or not nxt.requires_caregiver} if nxt else None,
            "uncovered_appointments": len(uncovered), "open_requests": open_by_patient.get(pid, 0),
            "medicines": sorted(({"medicine": m, "dose": d, **_rates(t)} for (m, d), t in meds.items()), key=lambda x: (-x["missed"], x["medicine"])),
            "spark": [_rates(spark[(today - timedelta(days=n)).isoformat()])["taken_pct"] for n in range(SPARK_DAYS - 1, -1, -1)],
        })
    out_patients.sort(key=lambda x: (not x["needs_follow_up"], x["taken_pct"] if x["taken_pct"] is not None else 101, x["name"]))
    meds_out = sorted(({"medicine": m, "patients": len(t["patients"]), **_rates({k: v for k, v in t.items() if k != "patients"})} for m, t in medicine_totals.items()),
                      key=lambda x: (-x["missed"], x["medicine"]))[:8]
    upcoming = sum(1 for a in future if _aware(a.scheduled_start) <= at + timedelta(days=7))
    open_total = sum(open_by_patient.values())
    avg_ack = round(sum(ack_minutes) / len(ack_minutes), 1) if ack_minutes else None
    from app.services.team_builder import team_reputation
    teams = team_reputation(db, [uuid.UUID(str(p["id"])) for p in out_patients]) if settings.feature("team_builder") else {}
    for p in out_patients: p["team_reputation"] = teams.get(str(p["id"]))
    payload = _payload(at, days, totals, out_patients, meds_out, daily, today, zone, upcoming, open_total, avg_ack)
    payload["totals"]["requests"] = len(incidents)
    return payload


def _payload(at, days, totals, patients, medicines, daily, today, zone, upcoming, open_total, avg_ack) -> dict:
    rates = _rates(totals)
    series = []
    for n in range(days - 1, -1, -1):
        day = (today - timedelta(days=n)).isoformat()
        r = _rates(daily[day]) if day in daily else {**_tally(), "decided": 0, "taken_pct": None, "on_time_pct": None}
        series.append({"date": day, "due": r["due"], "missed": r["missed"], "decided": r["decided"], "taken_pct": r["taken_pct"]})
    bands = {"on_track": 0, "watch": 0, "follow_up": 0, "no_data": 0}
    for p in patients:
        if p["needs_follow_up"]: bands["follow_up"] += 1
        elif p["decided"] < MIN_DECIDED: bands["no_data"] += 1
        elif p["taken_pct"] < 90: bands["watch"] += 1
        else: bands["on_track"] += 1
    return {"as_of": at, "days": days, "note": NOTE,
            "thresholds": {"low_taken_pct": LOW_TAKEN_PCT, "missed_recent": MISSED_RECENT, "recent_days": RECENT_DAYS},
            "totals": {"patients": len(patients), **rates, "needs_follow_up": sum(1 for p in patients if p["needs_follow_up"]), "appointments_next_7_days": upcoming,
                       "uncovered_appointments": sum(p["uncovered_appointments"] for p in patients), "open_requests": open_total, "avg_ack_minutes": avg_ack},
            "bands": bands, "daily": series, "patients": patients, "medicines": medicines}
