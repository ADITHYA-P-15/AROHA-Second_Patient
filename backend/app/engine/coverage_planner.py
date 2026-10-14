"""Predictive coverage: find tomorrow's problems today, with a deadline to fix each one.

Pure module. For every caregiver task in the next 7 days it decides, from known schedules,
availability, capabilities, commitments and limits (the Backup Matcher's rules), whether the task is

- GAP          no caregiver, or the assigned caregiver cannot actually do it
- UNCONFIRMED  assigned but not confirmed yet
- SINGLE_POINT covered, but the holder is the only eligible person and no backup is ready
- OK           covered with a ready backup or at least one eligible alternative

Each finding gets a "secure by" time (start minus a lead time by importance) and a suggestion.
Days are rated for capacity, and an N-1 view lists what has no alternative if one person is away.
Statements are about coordination coverage only, never about the patient's health.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from app.engine.backup_matcher import holder_cannot_do, rank_in_context
from app.engine.workload_balancer import LoadContext, delegation_class

HORIZONS = (("24h", timedelta(hours=24)), ("3d", timedelta(days=3)), ("7d", timedelta(days=7)))
LEAD_TIME = {"CRITICAL": timedelta(hours=72), "HIGH": timedelta(hours=48), "MEDIUM": timedelta(hours=24), "LOW": timedelta(hours=12)}
NEAR_MISS = {"UNAVAILABLE", "AT_LIMIT"}  # one conversation away from being a backup (a clash is not)
BACKUP_OK = {"AT_LIMIT", "UNAVAILABLE"}  # acceptable for a confirmed standby (no load until used)
SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
KIND_ORDER = {"GAP": 0, "UNCONFIRMED": 1, "SINGLE_POINT": 2}
BASIS_NOTE = ("Forecast from recorded schedules, availability, capabilities, commitments and limits. "
              "It describes coordination coverage only and changes nothing until someone acts.")


def _get(row, key, default=None):
    return row.get(key, default) if isinstance(row, dict) else getattr(row, key, default)


def _sid(value) -> str:
    return str(value) if value is not None else ""


def secure_by(start: datetime, importance: str, now: datetime, zone=None) -> tuple[datetime, bool]:
    """When a backup or replacement should be secured; True when that moment has already passed.

    Deadlines land in waking hours (08:00–20:00 local): one that would fall at night moves to 20:00 the evening before.
    """
    target = start - LEAD_TIME.get(importance, LEAD_TIME["MEDIUM"])
    if zone is not None:
        local = target.astimezone(zone)
        if local.hour >= 20 or local.hour < 8:
            evening = local.replace(hour=20, minute=0, second=0, microsecond=0)
            target = (evening if local.hour >= 20 else evening - timedelta(days=1)).astimezone(target.tzinfo)
    return target, target <= now


def _day_phrase(ctx: LoadContext, start: datetime) -> str:
    local, today = start.astimezone(ctx.zone).date(), ctx.now.astimezone(ctx.zone).date()
    delta = (local - today).days
    return "Today's" if delta == 0 else "Tomorrow's" if delta == 1 else f"{local:%A}'s"


def _when(ctx: LoadContext, value: datetime) -> str:
    return value.astimezone(ctx.zone).strftime("%a %d %b, %H:%M")


def _horizon(start: datetime, now: datetime) -> str:
    # Inclusive edges, matching forecast()'s now < start <= now + 7 days.
    return next((name for name, span in HORIZONS if start <= now + span), HORIZONS[-1][0])


def _severity(kind: str, importance: str, start: datetime, now: datetime) -> str:
    soon = start < now + timedelta(hours=24)
    if kind == "GAP": return "HIGH" if soon or importance in ("HIGH", "CRITICAL") else "MEDIUM"
    if kind == "UNCONFIRMED": return "HIGH" if soon and importance in ("HIGH", "CRITICAL") else "MEDIUM"
    return "MEDIUM" if importance in ("HIGH", "CRITICAL") or soon else "LOW"


def _finding(ctx, activity, kind, *, holder, holder_row, ranked, alternatives, near_miss, importance, now, requested) -> dict:
    start = _get(activity, "scheduled_start")
    title = _get(activity, "title", "Scheduled task")
    target, overdue = secure_by(start, importance, now, ctx.zone)
    deadline = "now" if overdue else f"by {_when(ctx, target)}"
    day = _day_phrase(ctx, start)
    holder_name = _get(ctx.caregivers.get(holder, {}), "name", "the assigned caregiver") if holder else None
    if kind == "GAP":
        if holder is None:
            headline = f"{day} {title} has no caregiver yet."
            reason = "No caregiver is assigned."
        else:
            reason = holder_row["headline"] if holder_row else f"{holder_name} cannot take it."
            headline = f"{day} {title} is assigned to {holder_name}, but as things stand they cannot do it. {reason}"
        suggestion = (f"Find cover {deadline}. {len(alternatives)} eligible {'person' if len(alternatives) == 1 else 'people'} can take it." if alternatives else
                      f"No one in the network can take it as recorded. Line someone up {deadline}.")
        action = {"option": "FIND_COVER"}
    elif kind == "UNCONFIRMED":
        reason = f"{holder_name} has not confirmed yet."
        headline = f"{day} {title} is waiting for {holder_name} to confirm."
        suggestion = f"Get a yes or no {deadline}." + (" If they say no, nobody else can take it." if not alternatives else f" {len(alternatives)} other {'person is' if len(alternatives) == 1 else 'people are'} eligible if they cannot.")
        action = {"option": "REQUEST_CONFIRMATION"}
    else:
        reason = f"{holder_name} is the only eligible person and there is no backup."
        headline = f"{day} {title} is covered, but {holder_name} is the only eligible person. Arrange a backup {'now' if overdue else 'before ' + _when(ctx, target)}."
        suggestion = (("Waiting for " + ", ".join(r["name"] for r in requested) + " to confirm as backup.") if requested else
                      "Ask " + ", ".join(n["name"] for n in near_miss[:2]) + " to stand by as backup." if near_miss
                      else "Nobody else is close: add a caregiver with the needed capability or extend someone's availability.")
        action = {"option": "SECURE_BACKUP"}
    return {"id": f"{kind}:{_sid(_get(activity, 'id'))}", "kind": kind, "severity": _severity(kind, importance, start, now),
            "horizon": _horizon(start, now), "activity": {"id": _sid(_get(activity, "id")), "title": title, "importance": importance,
            "category": _get(activity, "category"), "scheduled_start": start, "required_support": list(_get(activity, "required_support", []) or []),
            "delegation_class": delegation_class(_get(activity, "required_support"))},
            "holder": {"caregiver_id": holder, "name": holder_name, "assignment_id": ctx.holder.get(_sid(_get(activity, "id")), (None, None, None))[1],
                       "status": ctx.holder.get(_sid(_get(activity, "id")), (None, None, None))[2]} if holder else None,
            "headline": headline, "reason": reason, "secure_by": target, "secure_now": overdue, "suggestion": suggestion,
            "alternatives": [{"caregiver_id": a["caregiver_id"], "name": a["name"], "headline": a["headline"]} for a in alternatives[:3]],
            "near_miss": [{"caregiver_id": n["caregiver_id"], "name": n["name"], "status": n["status"], "headline": n["headline"]} for n in near_miss[:3]],
            "backup_requested": requested, "eligible_alternatives": len(alternatives), "action": action}


def forecast(snapshot: dict, now: datetime, day_start: datetime, day_end: datetime, *, demand=None, timezone: str = "Asia/Kolkata") -> dict:
    """Forecast coverage for the next 7 days from ``now``. ``demand`` is the Workload Balancer's per-day demand list."""
    ctx = LoadContext(snapshot, now, day_start, day_end, timezone)
    end = now + HORIZONS[-1][1]
    findings, ok, single_owner = [], [], defaultdict(list)
    pending_backups = {_sid(k): [_sid(x) for x in v] for k, v in (snapshot.get("pending_backups") or {}).items()}
    for aid, activity in sorted(ctx.activities.items(), key=lambda item: (_get(item[1], "scheduled_start"), item[0])):
        start = _get(activity, "scheduled_start")
        if not (now < start <= end): continue
        importance = _get(activity, "importance", "MEDIUM")
        holder, _, status = ctx.holder.get(aid, (None, None, None))
        ranked = rank_in_context(ctx, aid, history=snapshot.get("history"))
        rows = {r["caregiver_id"]: r for r in ranked["candidates"]}
        holder_row = rows.get(holder) if holder else None
        alternatives = [r for r in ranked["candidates"] if r["eligible"] and r["caregiver_id"] != holder]
        # A confirmed backup agreed to stand by: limits and usual hours do not disqualify them, absence or missing skills do.
        backups = [b for b in ctx.backups.get(aid, set()) if b != holder and b in rows and (rows[b]["eligible"] or (
            rows[b]["status"] in BACKUP_OK and not rows[b].get("recorded_absence")))]
        # People one conversation away from being a backup; never someone with a recorded absence.
        requested = [b for b in pending_backups.get(aid, []) if b != holder]
        near_miss = [r for r in ranked["candidates"] if r["status"] in NEAR_MISS and r["caregiver_id"] != holder
                     and not r.get("recorded_absence") and r["caregiver_id"] not in requested]
        common = dict(holder=holder, holder_row=holder_row, ranked=ranked, alternatives=alternatives, near_miss=near_miss, importance=importance, now=now,
                      requested=[{"caregiver_id": b, "name": _get(ctx.caregivers.get(b, {}), "name", "Caregiver")} for b in requested])
        if holder is None or holder_cannot_do(holder_row):
            findings.append(_finding(ctx, activity, "GAP", **common))
            if len(alternatives) == 1: single_owner[alternatives[0]["caregiver_id"]].append(aid)
        elif status != "CONFIRMED":
            findings.append(_finding(ctx, activity, "UNCONFIRMED", **common))
            if not alternatives: single_owner[holder].append(aid)
        elif not backups and not alternatives:
            findings.append(_finding(ctx, activity, "SINGLE_POINT", **common))
            single_owner[holder].append(aid)
        else:
            ok.append({"activity_id": aid, "title": _get(activity, "title"), "scheduled_start": start, "backup_ready": bool(backups), "eligible_alternatives": len(alternatives)})
    findings.sort(key=lambda f: (SEVERITY_ORDER[f["severity"]], f["secure_by"], KIND_ORDER[f["kind"]], f["id"]))

    horizons = {}
    for name, span in HORIZONS:
        inside = [f for f in findings if f["activity"]["scheduled_start"] <= now + span]
        covered = [o for o in ok if o["scheduled_start"] <= now + span]
        horizons[name] = {"tasks": len(inside) + len(covered), "gaps": sum(f["kind"] == "GAP" for f in inside),
                          "unconfirmed": sum(f["kind"] == "UNCONFIRMED" for f in inside), "single_points": sum(f["kind"] == "SINGLE_POINT" for f in inside),
                          "covered_with_backup": len(covered), "secure_now": sum(f["secure_now"] for f in inside)}

    by_day = {d["date"]: d for d in (demand or [])}
    days = []
    for day in ctx.days[:8]:
        day_findings = [f for f in findings if ctx.day_of(f["activity"]["scheduled_start"]) == day]
        day_ok = [o for o in ok if ctx.day_of(o["scheduled_start"]) == day]
        info = by_day.get(day, {})
        unfixable = [f for f in day_findings if f["kind"] == "GAP" and not f["eligible_alternatives"]]
        reasons = list(info.get("reasons", []))
        if unfixable: reasons.insert(0, f"{len(unfixable)} task{'s' if len(unfixable) != 1 else ''} with no eligible caregiver.")
        level = ("INSUFFICIENT" if unfixable or info.get("level") == "HIGH" else
                 "TIGHT" if day_findings or info.get("level") == "ELEVATED" else "OK")
        if not day_findings and not day_ok and not info.get("tasks"): level = "OK"
        days.append({"date": day, "level": level, "tasks": len(day_findings) + len(day_ok), "gaps": sum(f["kind"] == "GAP" for f in day_findings),
                     "single_points": sum(f["kind"] == "SINGLE_POINT" for f in day_findings), "unconfirmed": sum(f["kind"] == "UNCONFIRMED" for f in day_findings),
                     "capacity_slots": info.get("capacity_slots"), "available_caregivers": info.get("available_caregivers"), "reasons": reasons})

    people = []
    for cid, aids in single_owner.items():
        name = _get(ctx.caregivers.get(cid, {}), "name", "Caregiver")
        titles = [_get(ctx.activities[a], "title", "task") for a in aids]
        people.append({"caregiver_id": cid, "name": name, "tasks": len(aids), "activity_ids": aids,
                       "message": f"If {name} is unavailable, {len(aids)} task{'s have' if len(aids) != 1 else ' has'} no alternative: {', '.join(titles[:3])}{'…' if len(titles) > 3 else ''}."})
    people.sort(key=lambda p: (-p["tasks"], p["name"]))
    return {"horizons": horizons, "findings": findings, "days": days, "people": people, "basis_note": BASIS_NOTE,
            "lead_times_hours": {k: int(v.total_seconds() // 3600) for k, v in LEAD_TIME.items()}}
