"""Deterministic workload balancing: caregiver load, demand peaks, dependency and redistribution advice.

Pure module. Callers pass JSON-like snapshots and an explicit clock; nothing here reads the
database or changes an assignment. Recommendations are advice: the API applies one only after
a coordinator chooses it, and the receiving caregiver still confirms. Loads describe
coordination capacity, never the patient's clinical state.

Snapshot shape (all datetimes timezone-aware):
- ``caregivers``: id, name, kind, capabilities, max_activities_per_day, max_hours_per_week,
  is_active, is_designated_backup, schedule, overrides
- ``activities``: the target patient's scheduled activities in the horizon: id, title, category,
  importance, required_support, scheduled_start, window_start, window_end, requires_caregiver,
  linked_activity_ids
- ``commitments``: active PRIMARY assignments of those caregivers for any patient: assignment_id,
  caregiver_id, activity_id, own_patient, status, scheduled_start, window_start, window_end
- ``confirmed_backups``: {activity_id: [caregiver_id, ...]}
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.engine.availability import Window, effective_windows, is_available_for

PROFESSIONAL_SUPPORT = frozenset({"CLINICAL_VISIT"})
TRAINED_SUPPORT = frozenset({"MEDICATION_ASSIST", "MOBILITY_ASSIST"})
ALL_SUPPORT = frozenset({"TRANSPORT", "MEDICATION_ASSIST", "PRESCRIPTION_PICKUP", "DAILY_ASSIST", "MOBILITY_ASSIST", "LAB_ESCORT", "SUPPLIES", "CLINICAL_VISIT", "APPOINTMENT_ESCORT"})
PROFESSIONAL_KINDS = frozenset({"NURSE"})
DELEGATION_RULES = (
    {"class": "PROFESSIONAL", "label": "Qualified healthcare professional", "supports": sorted(PROFESSIONAL_SUPPORT),
     "description": "Only a caregiver recorded as a healthcare professional (nurse) with the required capability can take this task."},
    {"class": "TRAINED", "label": "Trained caregiver", "supports": sorted(TRAINED_SUPPORT),
     "description": "Delegable to any caregiver whose recorded capabilities include the required support."},
    {"class": "GENERAL", "label": "General caregiver", "supports": sorted(ALL_SUPPORT - PROFESSIONAL_SUPPORT - TRAINED_SUPPORT),
     "description": "Delegable to any available caregiver with the listed capability."},
)
NEAR_RATIO = 0.8
CAPACITY_RATIO = 0.5
DEPENDENCY_SHARE = 0.6
DEPENDENCY_MIN_TASKS = 3
DEPENDENCY_MOVES_PER_CAREGIVER = 2
MIN_LEAD = timedelta(hours=2)
MAX_RECOMMENDATIONS = 20
# Additive, documented receiver score. Hard filters run first; points only rank eligible people.
SCORE_POINTS = {"eligible": 40, "daily_headroom": 25, "weekly_headroom": 15, "designated_backup": 10,
                "confirmed_backup": 15, "spreads_dependency": 5, "professional_on_general": -15}
IMPORTANCE_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
CLASS_ORDER = {"GENERAL": 0, "TRAINED": 1, "PROFESSIONAL": 2}
BASIS_NOTE = ("Based on assignments, recorded availability and each caregiver's configured limits. "
              "Recommendations change nothing until a primary contact applies one and the caregiver confirms.")


def delegation_class(required_support) -> str:
    required = set(required_support or ())
    if required & PROFESSIONAL_SUPPORT: return "PROFESSIONAL"
    if required & TRAINED_SUPPORT: return "TRAINED"
    return "GENERAL"


def _get(row, key, default=None):
    return row.get(key, default) if isinstance(row, dict) else getattr(row, key, default)


def _sid(value) -> str:
    return str(value) if value is not None else ""


def _ratio(value: float, limit: float) -> float:
    if limit <= 0: return 2.0 if value > 0 else 0.0
    return value / limit


def _day_label(day: str) -> str:
    return date.fromisoformat(day).strftime("%a %d %b")


def _hm(value: datetime, zone: ZoneInfo) -> str:
    return value.astimezone(zone).strftime("%H:%M")


def _overlaps(left: Window, right: Window) -> bool:
    return left.start < right.end and right.start < left.end


@dataclass
class _Load:
    day_tasks: dict = field(default_factory=lambda: defaultdict(int))
    day_hours: dict = field(default_factory=lambda: defaultdict(float))
    week_hours: dict = field(default_factory=lambda: defaultdict(float))
    windows: list = field(default_factory=list)  # (Window, activity_id, in_horizon)
    patient_tasks: int = 0
    pending: int = 0

    def add(self, window: Window, activity_id: str, day: str, week: str, in_horizon: bool, own: bool, pending: bool):
        hours = (window.end - window.start).total_seconds() / 3600
        self.week_hours[week] += hours
        self.windows.append((window, activity_id, in_horizon))
        if in_horizon:
            self.day_tasks[day] += 1
            self.day_hours[day] += hours
            self.patient_tasks += int(own)
            self.pending += int(pending)

    def remove(self, activity_id: str, day: str, week: str, hours: float):
        self.week_hours[week] -= hours
        self.day_tasks[day] -= 1
        self.day_hours[day] -= hours
        self.patient_tasks -= 1
        self.windows = [x for x in self.windows if x[1] != activity_id]


class _Context:
    def __init__(self, snapshot: dict, now: datetime, horizon_start: datetime, horizon_end: datetime, timezone: str):
        self.now, self.start, self.end = now, horizon_start, horizon_end
        self.zone = ZoneInfo(timezone)
        self.timezone = timezone
        self.caregivers = {_sid(_get(c, "id")): c for c in snapshot.get("caregivers", ())}
        self.activities = {_sid(_get(a, "id")): a for a in snapshot.get("activities", ())
                           if _get(a, "requires_caregiver", True)}
        self.backups = {_sid(k): {_sid(x) for x in v} for k, v in (snapshot.get("confirmed_backups") or {}).items()}
        self.days = self._horizon_days()
        self.weeks = sorted({self.week_of_day(d) for d in self.days})
        self.loads: dict[str, _Load] = {cid: _Load() for cid in self.caregivers}
        self.holder: dict[str, tuple[str, str, str]] = {}  # activity_id -> (caregiver_id, assignment_id, status)
        for row in snapshot.get("commitments", ()):
            cid = _sid(_get(row, "caregiver_id"))
            if cid not in self.loads: continue
            window = Window(_get(row, "window_start"), _get(row, "window_end"))
            start = _get(row, "scheduled_start")
            own = bool(_get(row, "own_patient"))
            aid = _sid(_get(row, "activity_id"))
            in_horizon = self.start <= start < self.end
            status = _get(row, "status", "CONFIRMED")
            self.loads[cid].add(window, aid, self.day_of(start), self.week_of(start), in_horizon, own, status != "CONFIRMED")
            if own: self.holder[aid] = (cid, _sid(_get(row, "assignment_id")), status)

    def _horizon_days(self) -> list[str]:
        first = self.start.astimezone(self.zone).date()
        last = (self.end - timedelta(microseconds=1)).astimezone(self.zone).date()
        days, cursor = [], first
        while cursor <= last:
            days.append(cursor.isoformat()); cursor += timedelta(days=1)
        return days

    def day_of(self, value: datetime) -> str:
        return value.astimezone(self.zone).date().isoformat()

    def week_of(self, value: datetime) -> str:
        iso = value.astimezone(self.zone).isocalendar()
        return f"{iso.year}-W{iso.week:02d}"

    def week_of_day(self, day: str) -> str:
        iso = date.fromisoformat(day).isocalendar()
        return f"{iso.year}-W{iso.week:02d}"

    def window(self, activity) -> Window:
        return Window(_get(activity, "window_start"), _get(activity, "window_end"))

    def hours(self, activity) -> float:
        w = self.window(activity)
        return (w.end - w.start).total_seconds() / 3600

    def active_ids(self) -> list[str]:
        return sorted((cid for cid, c in self.caregivers.items() if _get(c, "is_active", True)), key=lambda x: (_get(self.caregivers[x], "name", ""), x))

    def availability_input(self, caregiver) -> dict:
        return {"schedule": _get(caregiver, "schedule", []) or [], "overrides": _get(caregiver, "overrides", []) or []}

    def conflict_pairs(self, cid: str) -> list[tuple[str, str]]:
        rows = sorted(self.loads[cid].windows, key=lambda x: x[0].start)
        pairs = []
        for i, (left, left_id, left_in) in enumerate(rows):
            for right, right_id, right_in in rows[i + 1:]:
                if right.start >= left.end: break
                if (left_in or right_in) and left_id != right_id: pairs.append((left_id, right_id))
        return pairs

    def over_day(self, cid: str, day: str) -> bool:
        return self.loads[cid].day_tasks.get(day, 0) > int(_get(self.caregivers[cid], "max_activities_per_day", 0))

    def over_week(self, cid: str, week: str) -> bool:
        return self.loads[cid].week_hours.get(week, 0.0) > float(_get(self.caregivers[cid], "max_hours_per_week", 0)) + 1e-9


# Public name for the shared load model; the Backup Matcher ranks candidates on the same state.
LoadContext = _Context


def _caregiver_report(ctx: _Context, cid: str) -> dict:
    cg, load = ctx.caregivers[cid], ctx.loads[cid]
    day_limit = int(_get(cg, "max_activities_per_day", 0))
    week_limit = float(_get(cg, "max_hours_per_week", 0))
    name = _get(cg, "name", "Caregiver")
    daily = [{"date": d, "tasks": load.day_tasks.get(d, 0), "hours": round(load.day_hours.get(d, 0.0), 2), "limit": day_limit,
              "ratio": round(_ratio(load.day_tasks.get(d, 0), day_limit), 2)} for d in ctx.days]
    weekly = [{"week": w, "hours": round(load.week_hours.get(w, 0.0), 2), "limit_hours": week_limit,
               "ratio": round(_ratio(load.week_hours.get(w, 0.0), week_limit), 2)} for w in ctx.weeks]
    conflicts = ctx.conflict_pairs(cid)
    unavailable = 0
    availability = ctx.availability_input(cg)
    for window, _, in_horizon in load.windows:
        if in_horizon and not is_available_for(availability, window, ctx.timezone).available: unavailable += 1
    flags, reasons = [], []
    for d in daily:
        if d["tasks"] > d["limit"]:
            flags.append({"code": "DAILY_LIMIT_EXCEEDED", "date": d["date"]})
            reasons.append(f"{name} has {d['tasks']} tasks on {_day_label(d['date'])}; the daily limit is {d['limit']}.")
    for w in weekly:
        if w["hours"] > w["limit_hours"] + 1e-9:
            flags.append({"code": "WEEKLY_HOURS_EXCEEDED", "week": w["week"]})
            reasons.append(f"{name} is committed for {w['hours']:.1f} h in {w['week']}; the weekly limit is {w['limit_hours']:g} h.")
    if conflicts:
        flags.append({"code": "OVERLAPPING_COMMITMENTS", "count": len(conflicts)})
        reasons.append(f"{name} has {len(conflicts)} overlapping commitment{'s' if len(conflicts) != 1 else ''}.")
    if unavailable:
        flags.append({"code": "ASSIGNED_OUTSIDE_AVAILABILITY", "count": unavailable})
        reasons.append(f"{unavailable} assigned task{'s fall' if unavailable != 1 else ' falls'} outside {name}'s recorded availability.")
    peak_day = max((d["ratio"] for d in daily), default=0.0)
    peak_week = max((w["ratio"] for w in weekly), default=0.0)
    at_day_limit = any(d["tasks"] and d["tasks"] >= d["limit"] for d in daily)
    if not _get(cg, "is_active", True):
        status = "INACTIVE"
    elif any(f["code"] in {"DAILY_LIMIT_EXCEEDED", "WEEKLY_HOURS_EXCEEDED", "OVERLAPPING_COMMITMENTS"} for f in flags):
        status = "OVERLOADED"
    elif unavailable:
        status = "NEEDS_REVIEW"
    elif at_day_limit or peak_week >= NEAR_RATIO:
        status = "NEAR_LIMIT"
        if at_day_limit: reasons.append(f"{name} is at the daily task limit on at least one day.")
        if peak_week >= NEAR_RATIO: reasons.append(f"{name} is above {int(NEAR_RATIO * 100)}% of the weekly hours limit.")
    elif max(peak_day, peak_week) < CAPACITY_RATIO:
        status = "HAS_CAPACITY"
    else:
        status = "BALANCED"
    other_tasks = sum(load.day_tasks.get(d, 0) for d in ctx.days) - load.patient_tasks
    return {"caregiver_id": cid, "name": name, "kind": _get(cg, "kind", "OTHER"),
            "is_professional": _get(cg, "kind") in PROFESSIONAL_KINDS, "capabilities": sorted(_get(cg, "capabilities", []) or []),
            "is_designated_backup": bool(_get(cg, "is_designated_backup", False)), "status": status,
            "load_score": int(round(100 * max(peak_day, peak_week))), "daily": daily, "weekly": weekly,
            "conflicts": len(conflicts), "assigned_outside_availability": unavailable, "pending_tasks": load.pending,
            "this_patient_tasks": load.patient_tasks, "other_commitments": max(0, other_tasks), "flags": flags, "reasons": reasons}


def _demand(ctx: _Context) -> list[dict]:
    rows = []
    by_day = defaultdict(list)
    for activity in ctx.activities.values():
        start = _get(activity, "scheduled_start")
        if ctx.start <= start < ctx.end: by_day[ctx.day_of(start)].append(activity)
    counts = sorted(len(by_day.get(d, ())) for d in ctx.days)
    median = counts[len(counts) // 2] if counts else 0
    active = ctx.active_ids()
    for day in ctx.days:
        items = by_day.get(day, [])
        local = datetime.combine(date.fromisoformat(day), datetime.min.time(), ctx.zone)
        available, capacity, qualified = [], 0, 0
        for cid in active:
            cg = ctx.caregivers[cid]
            if not effective_windows(ctx.availability_input(cg), local, local + timedelta(days=1), ctx.timezone): continue
            available.append(cid)
            other = ctx.loads[cid].day_tasks.get(day, 0) - sum(1 for a in items if ctx.holder.get(_sid(_get(a, "id")), ("",))[0] == cid)
            capacity += max(0, int(_get(cg, "max_activities_per_day", 0)) - max(0, other))
            if _get(cg, "kind") in PROFESSIONAL_KINDS and PROFESSIONAL_SUPPORT & set(_get(cg, "capabilities", []) or []): qualified += 1
        tasks = len(items)
        professional = sum(1 for a in items if delegation_class(_get(a, "required_support")) == "PROFESSIONAL")
        hours = round(sum(ctx.hours(a) for a in items), 2)
        ratio = _ratio(tasks, capacity)
        reasons = []
        if tasks and capacity == 0:
            level = "HIGH"; reasons.append("No linked caregiver has spare task capacity on this day.")
        elif professional and not qualified:
            level = "HIGH"; reasons.append("A task needs a healthcare professional and none is available that day.")
        elif ratio >= NEAR_RATIO:
            level = "HIGH"; reasons.append(f"{tasks} tasks use {int(round(ratio * 100))}% of the network's remaining task capacity.")
        elif ratio >= 0.6 or (tasks >= 3 and median and tasks >= 2 * median):
            level = "ELEVATED"; reasons.append(f"{tasks} tasks against {capacity} open task slots; busier than a typical day in this view.")
        else:
            level = "NORMAL"
        rows.append({"date": day, "tasks": tasks, "hours": hours, "capacity_slots": capacity, "available_caregivers": len(available),
                     "ratio": round(min(ratio, 9.99), 2), "professional_tasks": professional, "qualified_available": qualified,
                     "level": level, "reasons": reasons})
    return rows


def _dependency(ctx: _Context) -> list[dict]:
    items = []
    held = [aid for aid in ctx.activities if aid in ctx.holder and ctx.start <= _get(ctx.activities[aid], "scheduled_start") < ctx.end]
    active = ctx.active_ids()
    if held and len(active) > 1:
        for cid in active:
            mine = sum(1 for aid in held if ctx.holder[aid][0] == cid)
            share = mine / len(held)
            if mine >= DEPENDENCY_MIN_TASKS and share >= DEPENDENCY_SHARE:
                name = _get(ctx.caregivers[cid], "name", "Caregiver")
                items.append({"kind": "CONCENTRATED_LOAD", "caregiver_id": cid, "name": name, "share": round(share, 2), "tasks": mine,
                              "message": f"{name} holds {mine} of {len(held)} assigned tasks ({int(round(share * 100))}%) in this period."})
    needed = defaultdict(set)
    for aid, activity in ctx.activities.items():
        if ctx.start <= _get(activity, "scheduled_start") < ctx.end:
            for code in _get(activity, "required_support", []) or []: needed[code].add(aid)
    for code in sorted(needed):
        capable = [cid for cid in active if code in set(_get(ctx.caregivers[cid], "capabilities", []) or [])
                   and (code not in PROFESSIONAL_SUPPORT or _get(ctx.caregivers[cid], "kind") in PROFESSIONAL_KINDS)]
        label = code.replace("_", " ").lower()
        if not capable:
            items.append({"kind": "NO_QUALIFIED_CAREGIVER", "support": code, "tasks": len(needed[code]), "caregiver_id": None, "name": None,
                          "message": f"No active linked caregiver is recorded for {label}."})
        elif len(capable) == 1:
            name = _get(ctx.caregivers[capable[0]], "name", "Caregiver")
            items.append({"kind": "SINGLE_QUALIFIED_CAREGIVER", "support": code, "tasks": len(needed[code]), "caregiver_id": capable[0], "name": name,
                          "message": f"Only {name} is recorded for {label}; their absence would leave {len(needed[code])} task{'s' if len(needed[code]) != 1 else ''} without a qualified alternative."})
    return items


def _check(ctx: _Context, activity, receiver_id: str, donor_id: str) -> tuple[bool, list[str], list[dict]]:
    cg = ctx.caregivers.get(receiver_id)
    name = _get(cg, "name", "Caregiver") if cg else "Caregiver"
    if cg is None: return False, ["Caregiver is not linked to this patient."], []
    if receiver_id == donor_id: return False, [f"{name} already holds this task."], []
    reasons = []
    if not _get(cg, "is_active", True): reasons.append(f"{name} is inactive.")
    cls = delegation_class(_get(activity, "required_support"))
    if cls == "PROFESSIONAL" and _get(cg, "kind") not in PROFESSIONAL_KINDS:
        reasons.append("Needs a qualified healthcare professional.")
    missing = sorted(set(_get(activity, "required_support", []) or []) - set(_get(cg, "capabilities", []) or []))
    if missing: reasons.append("Missing capability: " + ", ".join(x.replace("_", " ").lower() for x in missing) + ".")
    window = ctx.window(activity)
    if not is_available_for(ctx.availability_input(cg), window, ctx.timezone).available:
        reasons.append(f"Not available for the full {_hm(window.start, ctx.zone)}–{_hm(window.end, ctx.zone)} window.")
    load = ctx.loads[receiver_id]
    aid = _sid(_get(activity, "id"))
    if any(_overlaps(window, other) for other, other_id, _ in load.windows if other_id != aid):
        reasons.append("Has an overlapping commitment.")
    start = _get(activity, "scheduled_start")
    day, week = ctx.day_of(start), ctx.week_of(start)
    day_limit = int(_get(cg, "max_activities_per_day", 0))
    week_limit = float(_get(cg, "max_hours_per_week", 0))
    day_after = load.day_tasks.get(day, 0) + 1
    week_after = load.week_hours.get(week, 0.0) + ctx.hours(activity)
    if day_after > day_limit: reasons.append(f"Would exceed the daily limit ({day_after}/{day_limit} tasks).")
    if week_after > week_limit + 1e-9: reasons.append(f"Would exceed the weekly limit ({week_after:.1f}/{week_limit:g} h).")
    if reasons: return False, reasons, []
    points = [{"label": "Meets capability, qualification, availability and limit checks", "points": SCORE_POINTS["eligible"]},
              {"label": f"Daily headroom after the move ({day_after}/{day_limit} tasks)", "points": int(round(SCORE_POINTS["daily_headroom"] * max(0.0, 1 - _ratio(day_after, day_limit))))},
              {"label": f"Weekly headroom after the move ({week_after:.1f}/{week_limit:g} h)", "points": int(round(SCORE_POINTS["weekly_headroom"] * max(0.0, 1 - _ratio(week_after, week_limit))))}]
    if receiver_id in ctx.backups.get(aid, set()): points.append({"label": "Already the confirmed backup for this task", "points": SCORE_POINTS["confirmed_backup"]})
    if _get(cg, "is_designated_backup", False): points.append({"label": "Designated backup for this patient", "points": SCORE_POINTS["designated_backup"]})
    if donor_id in ctx.loads and load.patient_tasks < ctx.loads[donor_id].patient_tasks - 1:
        points.append({"label": "Spreads this patient's tasks across more people", "points": SCORE_POINTS["spreads_dependency"]})
    if cls == "GENERAL" and _get(cg, "kind") in PROFESSIONAL_KINDS:
        points.append({"label": "Keeps the healthcare professional free for tasks only they can do", "points": SCORE_POINTS["professional_on_general"]})
    return True, [], points


def _candidates(ctx: _Context, activity, donor_id: str):
    eligible, excluded = [], []
    for cid in ctx.active_ids() + sorted(c for c in ctx.caregivers if c not in ctx.active_ids()):
        if cid == donor_id: continue
        ok, reasons, points = _check(ctx, activity, cid, donor_id)
        name = _get(ctx.caregivers[cid], "name", "Caregiver")
        if ok: eligible.append({"caregiver_id": cid, "name": name, "score": sum(p["points"] for p in points), "score_breakdown": points})
        else: excluded.append({"caregiver_id": cid, "name": name, "reasons": reasons})
    eligible.sort(key=lambda x: (-x["score"], x["name"], x["caregiver_id"]))
    return eligible, excluded


def _activity_view(ctx: _Context, activity) -> dict:
    return {"id": _sid(_get(activity, "id")), "title": _get(activity, "title", "Scheduled task"), "category": _get(activity, "category"),
            "importance": _get(activity, "importance", "MEDIUM"), "required_support": list(_get(activity, "required_support", []) or []),
            "delegation_class": delegation_class(_get(activity, "required_support")), "scheduled_start": _get(activity, "scheduled_start"),
            "window_start": _get(activity, "window_start"), "window_end": _get(activity, "window_end")}


def _move(ctx: _Context, activity, donor_id: str, receiver_id: str):
    aid, start = _sid(_get(activity, "id")), _get(activity, "scheduled_start")
    day, week, hours = ctx.day_of(start), ctx.week_of(start), ctx.hours(activity)
    ctx.loads[donor_id].remove(aid, day, week, hours)
    ctx.loads[receiver_id].add(ctx.window(activity), aid, day, week, True, True, True)
    holder = ctx.holder[aid]
    ctx.holder[aid] = (receiver_id, holder[1], "PROPOSED")


def _recommend(ctx: _Context, kind: str, activity, donor_id: str, trigger: str, priority: str) -> dict | None:
    eligible, excluded = _candidates(ctx, activity, donor_id)
    donor = ctx.caregivers[donor_id]
    donor_name = _get(donor, "name", "Caregiver")
    view = _activity_view(ctx, activity)
    aid = view["id"]
    start = view["scheduled_start"]
    day = ctx.day_of(start)
    cls_rule = next(r for r in DELEGATION_RULES if r["class"] == view["delegation_class"])
    linked = [ctx.activities[x] for x in (_get(activity, "linked_activity_ids", []) or []) if x in ctx.activities]
    base = {"id": f"{kind}:{aid}:{donor_id}", "activity": view, "priority": priority, "trigger": trigger,
            "from": {"caregiver_id": donor_id, "name": donor_name, "assignment_id": ctx.holder[aid][1], "assignment_status": ctx.holder[aid][2]}}
    if not eligible:
        if kind != "REDISTRIBUTE": return None
        return {**base, "kind": "NO_ELIGIBLE_RECEIVER", "to": None, "score": 0, "score_breakdown": [], "alternatives": [], "excluded": excluded,
                "reasons": [trigger, f"{cls_rule['label']} task. {cls_rule['description']}",
                            "No linked caregiver passes every check; add availability, a capability, or another caregiver to the network."],
                "effect": None}
    best = eligible[0]
    receiver = ctx.caregivers[best["caregiver_id"]]
    donor_before = ctx.loads[donor_id].day_tasks.get(day, 0)
    receiver_before = ctx.loads[best["caregiver_id"]].day_tasks.get(day, 0)
    window = ctx.window(activity)
    reasons = [trigger, f"{cls_rule['label']} task. {cls_rule['description']}",
               f"{best['name']} has the needed capability, is available {_hm(window.start, ctx.zone)}–{_hm(window.end, ctx.zone)} and has no overlapping commitment.",
               f"After the move {best['name']} has {receiver_before + 1} of {int(_get(receiver, 'max_activities_per_day', 0))} tasks that day; {donor_name} drops to {donor_before - 1} of {int(_get(donor, 'max_activities_per_day', 0))}."]
    if linked:
        reasons.append("Linked to " + ", ".join(_get(x, "title", "another task") for x in linked) + "; confirm timings with both caregivers.")
    effect = {"date": day, "from": {"tasks_before": donor_before, "tasks_after": donor_before - 1, "limit": int(_get(donor, "max_activities_per_day", 0))},
              "to": {"tasks_before": receiver_before, "tasks_after": receiver_before + 1, "limit": int(_get(receiver, "max_activities_per_day", 0))}}
    result = {**base, "kind": kind, "to": {"caregiver_id": best["caregiver_id"], "name": best["name"]}, "score": best["score"],
              "score_breakdown": best["score_breakdown"], "alternatives": eligible[1:4], "excluded": excluded, "reasons": reasons, "effect": effect}
    _move(ctx, activity, donor_id, best["caregiver_id"])
    return result


def _movable(ctx: _Context, aid: str, donor_id: str) -> bool:
    activity = ctx.activities.get(aid)
    return bool(activity) and ctx.holder.get(aid, ("",))[0] == donor_id and ctx.start <= _get(activity, "scheduled_start") < ctx.end \
        and _get(activity, "scheduled_start") >= ctx.now + MIN_LEAD


def _order(ctx: _Context, aid: str):
    activity = ctx.activities[aid]
    linked = bool(_get(activity, "linked_activity_ids"))
    return (CLASS_ORDER[delegation_class(_get(activity, "required_support"))], IMPORTANCE_ORDER.get(_get(activity, "importance", "MEDIUM"), 1),
            linked, _get(activity, "scheduled_start"), aid)


def _recommendations(ctx: _Context) -> list[dict]:
    results: list[dict] = []
    for donor_id in ctx.active_ids():
        name = _get(ctx.caregivers[donor_id], "name", "Caregiver")
        tried: set[str] = set()
        unresolved: dict[str, dict] = {}  # one "no eligible receiver" card per overloaded day/week, not per task
        while len(results) < MAX_RECOMMENDATIONS:
            conflicts = {x for pair in ctx.conflict_pairs(donor_id) for x in pair}
            pick = None
            for aid in sorted((a for a in ctx.activities if _movable(ctx, a, donor_id) and a not in tried), key=lambda a: _order(ctx, a)):
                start = _get(ctx.activities[aid], "scheduled_start")
                day, week = ctx.day_of(start), ctx.week_of(start)
                if aid in conflicts:
                    pick = (aid, f"{name} is double-booked during {_get(ctx.activities[aid], 'title', 'this task')}.", "HIGH", f"conflict:{aid}"); break
                if ctx.over_day(donor_id, day):
                    count = ctx.loads[donor_id].day_tasks.get(day, 0)
                    limit = int(_get(ctx.caregivers[donor_id], "max_activities_per_day", 0))
                    urgent = start < ctx.now + timedelta(hours=48)
                    pick = (aid, f"{name} has {count} tasks on {_day_label(day)}; the daily limit is {limit}.", "HIGH" if urgent else "MEDIUM", f"day:{day}"); break
                if ctx.over_week(donor_id, week):
                    pick = (aid, f"{name} is over the weekly hours limit in {week}.", "MEDIUM", f"week:{week}"); break
            if pick is None: break
            aid, trigger, priority, bucket = pick
            tried.add(aid)
            rec = _recommend(ctx, "REDISTRIBUTE", ctx.activities[aid], donor_id, trigger, priority)
            if rec is None: continue
            if rec["kind"] == "NO_ELIGIBLE_RECEIVER":
                if bucket in unresolved:
                    unresolved[bucket]["unresolved_tasks"].append(rec["activity"]); continue
                rec["unresolved_tasks"] = [rec["activity"]]
                unresolved[bucket] = rec
            results.append(rec)
        for rec in unresolved.values():
            if len(rec["unresolved_tasks"]) > 1:
                rec["reasons"].append(f"{len(rec['unresolved_tasks'])} tasks in this period have no eligible receiver.")
    for item in _dependency(ctx):
        if item["kind"] != "CONCENTRATED_LOAD": continue
        donor_id, moved = item["caregiver_id"], 0
        held = [a for a in ctx.activities if a in ctx.holder and ctx.start <= _get(ctx.activities[a], "scheduled_start") < ctx.end]
        for aid in sorted((a for a in ctx.activities if _movable(ctx, a, donor_id)), key=lambda a: _order(ctx, a)):
            if moved >= DEPENDENCY_MOVES_PER_CAREGIVER or len(results) >= MAX_RECOMMENDATIONS: break
            activity = ctx.activities[aid]
            if delegation_class(_get(activity, "required_support")) != "GENERAL" or _get(activity, "importance") in {"HIGH", "CRITICAL"}: continue
            mine = sum(1 for a in held if ctx.holder[a][0] == donor_id)
            if mine / len(held) < DEPENDENCY_SHARE: break
            rec = _recommend(ctx, "REDUCE_DEPENDENCY", activity, donor_id, item["message"] + " Sharing routine tasks reduces reliance on one person.", "LOW")
            if rec: results.append(rec); moved += 1
    rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    return sorted(results, key=lambda r: (rank[r["priority"]], r["activity"]["scheduled_start"], r["id"]))


def evaluate_workload(snapshot: dict, now: datetime, horizon_start: datetime, horizon_end: datetime, timezone: str = "Asia/Kolkata") -> dict:
    """Return caregiver loads, demand periods, dependency findings and ranked redistribution advice."""
    if horizon_end <= horizon_start: raise ValueError("horizon must end after it starts")
    ctx = _Context(snapshot, now, horizon_start, horizon_end, timezone)
    caregivers = [_caregiver_report(ctx, cid) for cid in ctx.active_ids() + sorted(c for c in ctx.caregivers if c not in ctx.active_ids())]
    demand = _demand(ctx)
    dependency = _dependency(ctx)
    recommendations = _recommendations(ctx)
    status_rank = {"OVERLOADED": 0, "NEEDS_REVIEW": 1, "NEAR_LIMIT": 2, "BALANCED": 3, "HAS_CAPACITY": 4, "INACTIVE": 5}
    caregivers.sort(key=lambda x: (status_rank[x["status"]], -x["load_score"], x["name"], x["caregiver_id"]))
    classes = defaultdict(int)
    for activity in ctx.activities.values():
        if ctx.start <= _get(activity, "scheduled_start") < ctx.end: classes[delegation_class(_get(activity, "required_support"))] += 1
    summary = {"caregivers": len(caregivers), "overloaded": sum(c["status"] == "OVERLOADED" for c in caregivers),
               "needs_review": sum(c["status"] == "NEEDS_REVIEW" for c in caregivers), "near_limit": sum(c["status"] == "NEAR_LIMIT" for c in caregivers), "has_capacity": sum(c["status"] == "HAS_CAPACITY" for c in caregivers),
               "high_demand_days": sum(d["level"] == "HIGH" for d in demand), "elevated_demand_days": sum(d["level"] == "ELEVATED" for d in demand),
               "recommendations": sum(r["kind"] != "NO_ELIGIBLE_RECEIVER" for r in recommendations),
               "unresolved_overloads": sum(r["kind"] == "NO_ELIGIBLE_RECEIVER" for r in recommendations),
               "dependency_findings": len(dependency), "tasks_by_delegation_class": {k: classes.get(k, 0) for k in ("GENERAL", "TRAINED", "PROFESSIONAL")}}
    return {"summary": summary, "caregivers": caregivers, "demand": demand, "dependency": dependency,
            "recommendations": recommendations, "delegation_rules": list(DELEGATION_RULES), "basis_note": BASIS_NOTE}


def check_receiver(snapshot: dict, now: datetime, horizon_start: datetime, horizon_end: datetime, activity_id: str,
                   donor_id: str, receiver_id: str, timezone: str = "Asia/Kolkata") -> tuple[bool, list[str]]:
    """Re-run the hard eligibility checks against current state before a coordinator applies a move."""
    ctx = _Context(snapshot, now, horizon_start, horizon_end, timezone)
    activity = ctx.activities.get(_sid(activity_id))
    if activity is None: return False, ["This task is not a scheduled caregiver task in the review period."]
    ok, reasons, _ = _check(ctx, activity, _sid(receiver_id), _sid(donor_id))
    return ok, reasons
