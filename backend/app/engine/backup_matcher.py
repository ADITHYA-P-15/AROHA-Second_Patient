"""Deterministic, explainable ranking of replacement caregivers for one task.

Pure module built on the Workload Balancer's load model. Every linked caregiver gets a status and a
one-sentence reason ("Karthik can provide transport and is available 09:45–10:30", "Suresh is
already committed at that time"). Eligible people are ranked by suitability and continuity with
additive, documented points. Nothing here assigns anyone: a person must accept and be confirmed
before the task counts as covered.

Snapshot: the Workload Balancer snapshot (caregivers, activities, commitments, confirmed_backups)
plus optional ``history``: {caregiver_id: {"patient_tasks": n, "same_series": n, "same_category": n}}
and optional ``extras`` (team builder): {"profiles": {caregiver_id: {composite, metric, city, sector, languages}},
"preferences": {languages, city, sector_code} | None, "policy": core/matcher_policy values}.
Extras only add points to people who already pass every hard rule; they never filter anyone out. Unrated people get a
neutral, labelled 0.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.engine.availability import Window, is_available_for
from app.engine.workload_balancer import PROFESSIONAL_KINDS, LoadContext, counts_toward_limit, delegation_class

TRAVEL_GAP = timedelta(minutes=30)
STATUS_ORDER = ("ELIGIBLE", "AT_LIMIT", "COMMITTED", "UNAVAILABLE", "MISSING_CAPABILITY", "NOT_QUALIFIED", "DECLINED_REQUEST", "INACTIVE", "REPLACED")
POINTS = {"eligible": 40, "daily_headroom": 15, "weekly_headroom": 10, "confirmed_backup": 25, "designated_backup": 10,
          "same_series": 15, "patient_history_per_task": 2, "patient_history_cap": 10, "same_category": 5,
          "professional_on_general": -15, "tight_connection": -10}
SUPPORT_PHRASES = {"TRANSPORT": "provide transport", "APPOINTMENT_ESCORT": "escort to the appointment", "MEDICATION_ASSIST": "assist with medication",
                   "PRESCRIPTION_PICKUP": "pick up the prescription", "DAILY_ASSIST": "help with daily tasks", "MOBILITY_ASSIST": "assist with mobility",
                   "LAB_ESCORT": "escort to the lab", "SUPPLIES": "fetch supplies", "CLINICAL_VISIT": "do the clinical visit"}


def _get(row, key, default=None):
    return row.get(key, default) if isinstance(row, dict) else getattr(row, key, default)


def _sid(value) -> str:
    return str(value) if value is not None else ""


def _ratio(value: float, limit: float) -> float:
    return (2.0 if value > 0 else 0.0) if limit <= 0 else value / limit


CANNOT_DO_STATUSES = {"MISSING_CAPABILITY", "NOT_QUALIFIED", "COMMITTED", "INACTIVE"}


def holder_cannot_do(row: dict | None) -> bool:
    """Whether the person holding a task cannot do it as recorded.

    Shared by the Coverage Planner and the "only if uncovered" check, so a flagged gap can always be acted on.
    Working outside usual hours is not disqualifying for someone who already said yes; a recorded absence is.
    """
    if row is None: return True
    return row["status"] in CANNOT_DO_STATUSES or (row["status"] == "UNAVAILABLE" and bool(row.get("recorded_absence")))


def support_phrase(required) -> str:
    phrases = [SUPPORT_PHRASES.get(code, code.replace("_", " ").lower()) for code in (required or [])]
    return " and ".join(phrases) if phrases else "take this task"


def _hm(ctx: LoadContext, value: datetime) -> str:
    return value.astimezone(ctx.zone).strftime("%H:%M")


def _scaled(value: float | None, max_points: int) -> int:
    """0-100 around a neutral 50: 100 -> +max, 50 -> 0, 0 -> -max."""
    return 0 if value is None else int(round(max_points * (float(value) - 50.0) / 50.0))


def extra_points(name: str, profile: dict | None, prefs: dict | None, pol: dict) -> list[dict]:
    """Reputation and preference points, each with a plain label. Pure: used by the matcher and documented in BACKUP_MATCHER.md."""
    profile, prefs = profile or {}, prefs or {}
    out = []
    comp, metric = profile.get("composite"), profile.get("metric")
    out.append({"label": f"Reputation {round(comp)}/100" if comp is not None else "Reputation: no rating yet (neutral)", "points": _scaled(comp, pol["reputation_max"])})
    out.append({"label": f"Reliability record {round(metric)}/100" if metric is not None else "Reliability record: not enough history (neutral)", "points": _scaled(metric, pol["reliability_max"])})
    city, sector = (profile.get("city") or "").strip().lower(), profile.get("sector")
    if prefs.get("city") and city and city == prefs["city"].strip().lower():
        out.append({"label": f"Lives in {profile.get('city')}, the patient's city", "points": pol["same_city"]})
    elif prefs.get("sector_code") and sector and sector == prefs["sector_code"]:
        out.append({"label": "Lives in the patient's region", "points": pol["same_sector"]})
    wanted = {x.lower() for x in prefs.get("languages") or []}
    spoken = [x for x in profile.get("languages") or [] if x.lower() in wanted]
    if spoken: out.append({"label": f"Speaks {', '.join(spoken)}", "points": pol["language_match"]})
    return out


def _assess(ctx: LoadContext, activity, cid: str, *, replaced: str, declined: set[str], history: dict, extras: dict | None = None) -> dict:
    cg = ctx.caregivers[cid]
    name = _get(cg, "name", "Caregiver")
    aid = _sid(_get(activity, "id"))
    window = ctx.window(activity)
    span = f"{_hm(ctx, window.start)}–{_hm(ctx, window.end)}"
    required = list(_get(activity, "required_support", []) or [])
    cls = delegation_class(required)
    failures: dict[str, str] = {}
    if cid == replaced:
        failures["REPLACED"] = f"{name} is the caregiver being replaced."
    if not _get(cg, "is_active", True):
        failures["INACTIVE"] = f"{name} is inactive."
    if cid in declined:
        failures["DECLINED_REQUEST"] = f"{name} already said no to this request."
    if cls == "PROFESSIONAL" and _get(cg, "kind") not in PROFESSIONAL_KINDS:
        failures["NOT_QUALIFIED"] = f"{name} is not recorded as a healthcare professional; this task needs one."
    missing = sorted(set(required) - set(_get(cg, "capabilities", []) or []))
    availability = is_available_for(ctx.availability_input(cg), window, ctx.timezone)
    if missing:
        label = ", ".join(x.replace("_", " ").lower() for x in missing)
        failures["MISSING_CAPABILITY"] = f"{name} is available but lacks the {label} capability." if availability.available else f"{name} lacks the {label} capability."
    if not availability.available:
        absence = " (recorded absence)" if availability.blocking_overrides else ""
        failures["UNAVAILABLE"] = f"{name} is not available {span}{absence}."
    load = ctx.loads[cid]
    others = [(w, other) for w, other, _ in load.windows if other != aid]
    if any(w.start < window.end and window.start < w.end for w, _ in others):
        failures["COMMITTED"] = f"{name} is already committed at that time."
    start = _get(activity, "scheduled_start")
    day, week = ctx.day_of(start), ctx.week_of(start)
    day_limit = int(_get(cg, "max_activities_per_day", 0))
    week_limit = float(_get(cg, "max_hours_per_week", 0))
    holds_it = any(other == aid for _, other, _ in load.windows)
    day_after = load.day_tasks.get(day, 0) + (0 if holds_it or not counts_toward_limit(activity) else 1)
    week_after = load.week_hours.get(week, 0.0) + (0 if holds_it else ctx.hours(activity))
    if day_after > day_limit:
        failures["AT_LIMIT"] = f"{name} is available but would exceed their daily limit ({day_after}/{day_limit} tasks)."
    elif week_after > week_limit + 1e-9:
        failures["AT_LIMIT"] = f"{name} is available but would exceed their weekly limit ({week_after:.1f}/{week_limit:g} h)."
    status = next((s for s in reversed(STATUS_ORDER) if s in failures), "ELIGIBLE")
    row = {"caregiver_id": cid, "name": name, "kind": _get(cg, "kind", "OTHER"), "status": status, "eligible": status == "ELIGIBLE",
           "recorded_absence": bool(availability.blocking_overrides),
           "reasons": [failures[s] for s in reversed(STATUS_ORDER) if s in failures], "score": 0, "score_breakdown": [], "tight_connection": None}
    if status != "ELIGIBLE":
        row["headline"] = failures[status]
        return row
    points = [{"label": "Passes capability, availability, commitment and limit checks", "points": POINTS["eligible"]},
              {"label": f"Daily headroom ({day_after}/{day_limit} tasks with this one)", "points": int(round(POINTS["daily_headroom"] * max(0.0, 1 - _ratio(day_after, day_limit))))},
              {"label": f"Weekly headroom ({week_after:.1f}/{week_limit:g} h with this one)", "points": int(round(POINTS["weekly_headroom"] * max(0.0, 1 - _ratio(week_after, week_limit))))}]
    if cid in ctx.backups.get(aid, set()): points.append({"label": "Already the confirmed backup for this task", "points": POINTS["confirmed_backup"]})
    if _get(cg, "is_designated_backup", False): points.append({"label": "Designated backup for this patient", "points": POINTS["designated_backup"]})
    past = history.get(cid, {})
    if past.get("same_series"): points.append({"label": f"Has covered this recurring task before ({past['same_series']}×)", "points": POINTS["same_series"]})
    if past.get("patient_tasks"):
        points.append({"label": f"Supported this patient recently ({past['patient_tasks']} tasks)", "points": min(POINTS["patient_history_cap"], POINTS["patient_history_per_task"] * past["patient_tasks"])})
    if past.get("same_category"): points.append({"label": "Has done this kind of task for this patient", "points": POINTS["same_category"]})
    if extras is not None:
        points += extra_points(name, extras.get("profiles", {}).get(cid), extras.get("preferences"), extras["policy"])
    if cls == "GENERAL" and _get(cg, "kind") in PROFESSIONAL_KINDS:
        points.append({"label": "Keeps the healthcare professional free for tasks only they can do", "points": POINTS["professional_on_general"]})
    near = None
    for w, _ in others:
        gap = window.start - w.end if w.end <= window.start else w.start - window.end if w.start >= window.end else None
        if gap is not None and gap < TRAVEL_GAP and (near is None or gap < near[0]): near = (gap, w)
    reasons = [f"{name} can {support_phrase(required)} and is available {span}."]
    if near:
        minutes = int(near[0].total_seconds() // 60)
        edge = f"another commitment ends at {_hm(ctx, near[1].end)}" if near[1].end <= window.start else f"another commitment starts at {_hm(ctx, near[1].start)}"
        row["tight_connection"] = {"gap_minutes": minutes}
        points.append({"label": f"Tight connection: {edge}", "points": POINTS["tight_connection"]})
        reasons.append(f"Tight connection: {edge} ({minutes} min gap, including travel buffers).")
    continuity = [p["label"] for p in points if p["points"] > 0 and p["label"].startswith(("Already", "Designated", "Has covered", "Supported", "Has done"))]
    if continuity: reasons.append("Continuity: " + "; ".join(x[0].lower() + x[1:] for x in continuity) + ".")
    row.update(headline=reasons[0], reasons=reasons, score=sum(p["points"] for p in points), score_breakdown=points)
    return row


def rank_in_context(ctx: LoadContext, activity_id, *, replaced_caregiver_id=None, declined_caregiver_ids=(), history=None, extras=None) -> dict:
    """Rank on an existing load context (lets the Coverage Planner assess many tasks on one snapshot)."""
    activity = ctx.activities.get(_sid(activity_id))
    if activity is None: raise ValueError("activity is not a scheduled caregiver task in this snapshot")
    history = {_sid(k): v for k, v in (history or {}).items()}
    declined = {_sid(x) for x in declined_caregiver_ids}
    if extras is not None: extras = {**extras, "profiles": {_sid(k): v for k, v in (extras.get("profiles") or {}).items()}}
    rows = [_assess(ctx, activity, cid, replaced=_sid(replaced_caregiver_id), declined=declined, history=history, extras=extras) for cid in ctx.caregivers]
    eligible = sorted((r for r in rows if r["eligible"]), key=lambda r: (-r["score"], r["name"], r["caregiver_id"]))
    others = sorted((r for r in rows if not r["eligible"]), key=lambda r: (STATUS_ORDER.index(r["status"]), r["name"], r["caregiver_id"]))
    for index, row in enumerate(eligible, 1): row["rank"] = index
    considered = [r for r in rows if r["status"] != "REPLACED"]
    summary = (f"{len(eligible)} of {len(considered)} people in the network can take this." if eligible
               else "No one in the network can take this right now.")
    return {"activity_id": _sid(activity_id), "delegation_class": delegation_class(_get(activity, "required_support")),
            "eligible_count": len(eligible), "summary": summary, "best": eligible[0] if eligible else None, "candidates": eligible + others}


def rank_candidates(snapshot: dict, now: datetime, horizon_start: datetime, horizon_end: datetime, activity_id, *,
                    replaced_caregiver_id=None, declined_caregiver_ids=(), timezone: str = "Asia/Kolkata") -> dict:
    """Rank every linked caregiver for one task. Eligible first by score; others grouped by why they cannot."""
    ctx = LoadContext(snapshot, now, horizon_start, horizon_end, timezone)
    return rank_in_context(ctx, activity_id, replaced_caregiver_id=replaced_caregiver_id,
                           declined_caregiver_ids=declined_caregiver_ids, history=snapshot.get("history"), extras=snapshot.get("extras"))


def check_candidate(snapshot: dict, now: datetime, horizon_start: datetime, horizon_end: datetime, activity_id, caregiver_id, *,
                    replaced_caregiver_id=None, declined_caregiver_ids=(), timezone: str = "Asia/Kolkata") -> dict | None:
    """Re-assess one person against current data (used before offering and again on acceptance)."""
    ranked = rank_candidates(snapshot, now, horizon_start, horizon_end, activity_id, replaced_caregiver_id=replaced_caregiver_id,
                             declined_caregiver_ids=declined_caregiver_ids, timezone=timezone)
    return next((c for c in ranked["candidates"] if c["caregiver_id"] == _sid(caregiver_id)), None)
