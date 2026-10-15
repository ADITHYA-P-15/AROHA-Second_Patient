"""Caretaker reputation: four sources, each shown and explained, combined by fixed weights. Deterministic backend logic only.

Sources (each turned into 0-100):
  agency     the agency's seeded 1-5 rating
  doctors    mean of professionals' 1-5 ratings, shrunk toward the sector mean
  customers  weighted mean of reviews (primary contact 1.0, patient `patient_review_weight`), shrunk toward the sector mean
  metric     our own records over a rolling window: on-time completion, no missed tasks, on-time check-ins, cover acceptance
Composite = sum(weight * score) / sum(weight) over the sources that exist. Formulas and defaults: docs/REPUTATION.md.

The pure functions at the top take plain numbers so they can be tested without a database. AI is never involved.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.config import settings
from app.core.reputation_policy import COMPONENTS, SOURCES, policy as current_policy
from app.models import (ActionItem, AgencyRating, CareActivity, CareAssignment, CareTeamMember, Caregiver, CaregiverPatientLink, CaretakerProfile,
                        CoverRequestEvent, DoctorRating, Patient, ReputationSnapshot, Review, TeamRole, User)

SOURCE_LABELS = {"metric": "Reliability record", "doctors": "Doctor ratings", "customers": "Family reviews", "agency": "Agency rating"}
COMPONENT_LABELS = {"on_time_completion": "Tasks completed on time", "no_missed": "Tasks not missed", "on_time_check_in": "On-time check-ins",
                    "cover_acceptance": "Cover offers accepted"}
NEUTRAL_STARS = 3.0  # prior when a sector has no ratings of that kind at all


# --- pure functions ----------------------------------------------------------------------------------------------------

def stars_to_score(stars: float) -> float:
    """1 star -> 0, 3 stars -> 50, 5 stars -> 100."""
    return round((min(5.0, max(1.0, stars)) - 1.0) / 4.0 * 100.0, 1)


def shrink(mean: float, n: float, prior: float, k: float) -> float:
    """Bayesian average: n ratings with this mean, plus k imaginary ratings at the prior (the sector mean)."""
    return (n * mean + k * prior) / (n + k)


def customer_mean(ratings: list[tuple[int, str]], patient_weight: float) -> tuple[float | None, float]:
    """(weighted mean stars, effective count). ratings are (stars, author_role); patients count `patient_weight` each."""
    weights = [(stars, 1.0 if role == "PRIMARY_CONTACT" else patient_weight) for stars, role in ratings]
    total = sum(w for _, w in weights)
    if total <= 0: return None, 0.0
    return sum(s * w for s, w in weights) / total, total


@dataclass
class MetricCounts:
    decided: int = 0          # tasks this caretaker held (confirmed primary) that finished in the window: completed or missed
    on_time: int = 0
    late: int = 0
    missed: int = 0
    check_ins: int | None = None       # tasks that needed a check-in; None: this caretaker has no such task on record
    check_ins_on_time: int | None = None
    check_ins_late: int | None = None
    offers_accepted: int = 0
    offers_declined: int = 0


def metric_score(c: MetricCounts, pol: dict) -> dict:
    """Score 0-100 from the components that have data. None (with the components) when there are too few tasks."""
    values = {
        "on_time_completion": (c.on_time / c.decided) if c.decided else None,
        "no_missed": (1 - c.missed / c.decided) if c.decided else None,
        "on_time_check_in": (c.check_ins_on_time / c.check_ins) if c.check_ins else None,
        "cover_acceptance": (c.offers_accepted / (c.offers_accepted + c.offers_declined)) if (c.offers_accepted + c.offers_declined) else None,
    }
    details = {
        "on_time_completion": f"{c.on_time} of {c.decided} on time" + (f", {c.late} late" if c.late else ""),
        "no_missed": f"{c.missed} missed of {c.decided}",
        "on_time_check_in": ("Check-ins are not recorded yet" if not c.check_ins else
                             f"{c.check_ins_on_time} of {c.check_ins} on time, {c.check_ins_late or 0} late, {c.check_ins - (c.check_ins_on_time or 0) - (c.check_ins_late or 0)} missing"),
        "cover_acceptance": f"{c.offers_accepted} accepted, {c.offers_declined} declined" if (c.offers_accepted + c.offers_declined) else "No cover offers yet",
    }
    weights = pol["metric_components"]
    components = [{"key": k, "label": COMPONENT_LABELS[k], "value": None if values[k] is None else round(values[k] * 100, 1), "weight": weights[k],
                   "detail": details[k], "included": values[k] is not None and weights[k] > 0} for k in COMPONENTS]
    used = [(weights[k], values[k]) for k in COMPONENTS if values[k] is not None and weights[k] > 0]
    enough = c.decided >= pol["metric_min_tasks"]
    score = round(100 * sum(w * v for w, v in used) / sum(w for w, _ in used), 1) if enough and used else None
    return {"score": score, "enough_history": enough, "tasks": c.decided, "components": components,
            "counts": {"decided": c.decided, "on_time": c.on_time, "late": c.late, "missed": c.missed, "offers_accepted": c.offers_accepted, "offers_declined": c.offers_declined,
                       "check_ins": c.check_ins, "check_ins_on_time": c.check_ins_on_time, "check_ins_late": c.check_ins_late}}


def combine(scores: dict[str, float | None], weights: dict[str, float]) -> dict:
    """Weighted mean of the sources that have a score; missing ones are left out and the weights renormalised."""
    included = [s for s in SOURCES if scores.get(s) is not None and weights.get(s, 0) > 0]
    total = sum(weights[s] for s in included)
    composite = round(sum(weights[s] * scores[s] for s in included) / total, 1) if total else None
    return {"composite": composite, "included": included, "effective_weights": {s: round(weights[s] / total * 100, 1) for s in included} if total else {}}


@dataclass
class RatingInputs:
    agency: float | None = None
    doctors: list[int] = field(default_factory=list)
    customers: list[tuple[int, str]] = field(default_factory=list)
    metric: MetricCounts = field(default_factory=MetricCounts)


@dataclass
class Priors:
    doctors: float = NEUTRAL_STARS
    customers: float = NEUTRAL_STARS


def reputation(inputs: RatingInputs, priors: Priors, pol: dict) -> dict:
    """The full, explained breakdown for one caretaker."""
    k = pol["shrinkage_k"]
    sources: dict[str, dict] = {}
    sources["agency"] = {"stars": inputs.agency, "score": stars_to_score(inputs.agency) if inputs.agency is not None else None, "count": 1 if inputs.agency is not None else 0}
    if inputs.doctors:
        mean = sum(inputs.doctors) / len(inputs.doctors)
        adjusted = shrink(mean, len(inputs.doctors), priors.doctors, k)
        sources["doctors"] = {"stars": round(mean, 2), "adjusted_stars": round(adjusted, 2), "score": stars_to_score(adjusted), "count": len(inputs.doctors), "prior": round(priors.doctors, 2)}
    else:
        sources["doctors"] = {"stars": None, "score": None, "count": 0, "prior": round(priors.doctors, 2)}
    mean, effective = customer_mean(inputs.customers, pol["patient_review_weight"])
    by_role = {"PRIMARY_CONTACT": [s for s, r in inputs.customers if r == "PRIMARY_CONTACT"], "PATIENT": [s for s, r in inputs.customers if r == "PATIENT"]}
    split = {role: {"count": len(v), "stars": round(sum(v) / len(v), 2) if v else None} for role, v in by_role.items()}
    if mean is not None:
        adjusted = shrink(mean, effective, priors.customers, k)
        sources["customers"] = {"stars": round(mean, 2), "adjusted_stars": round(adjusted, 2), "score": stars_to_score(adjusted), "count": len(inputs.customers),
                                "effective_count": round(effective, 2), "prior": round(priors.customers, 2), "by_author": split}
    else:
        sources["customers"] = {"stars": None, "score": None, "count": len(inputs.customers), "prior": round(priors.customers, 2), "by_author": split}
    metric = metric_score(inputs.metric, pol)
    sources["metric"] = {**metric, "count": metric["tasks"]}
    for s in SOURCES: sources[s]["label"] = SOURCE_LABELS[s]
    combined = combine({s: sources[s]["score"] for s in SOURCES}, pol["weights"])
    rating_count = len(inputs.doctors) + len(inputs.customers)
    return {**combined, "sources": sources, "weights": dict(pol["weights"]), "rating_count": rating_count,
            "enough_history": combined["composite"] is not None and (rating_count >= pol["min_ratings_for_history"] or metric["enough_history"])}


# --- database layer ----------------------------------------------------------------------------------------------------

def _aware(value):
    from datetime import UTC
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


def metric_counts(db: Session, caregiver_ids: list, at: datetime, pol: dict) -> dict:
    since = at - timedelta(days=pol["metric_window_days"])
    counts = {cid: MetricCounts() for cid in caregiver_ids}
    if not caregiver_ids: return counts
    rows = db.execute(select(CareAssignment.caregiver_id, CareActivity.lifecycle_status, CareActivity.completed_late, func.count())
                      .join(CareActivity, CareActivity.id == CareAssignment.activity_id)
                      .where(CareAssignment.caregiver_id.in_(caregiver_ids), CareAssignment.role == "PRIMARY", CareAssignment.status == "CONFIRMED",
                             CareActivity.lifecycle_status.in_(("COMPLETED", "MISSED")), CareActivity.scheduled_start >= since, CareActivity.scheduled_start <= at)
                      .group_by(CareAssignment.caregiver_id, CareActivity.lifecycle_status, CareActivity.completed_late)).all()
    for cid, status, late, n in rows:
        c = counts[cid]
        c.decided += n
        if status == "MISSED": c.missed += n
        elif late: c.late += n
        else: c.on_time += n
    events = db.execute(select(CoverRequestEvent.caregiver_id, CoverRequestEvent.kind, func.count())
                        .where(CoverRequestEvent.caregiver_id.in_(caregiver_ids), CoverRequestEvent.kind.in_(("ACCEPTED", "OFFER_DECLINED")), CoverRequestEvent.at >= since)
                        .group_by(CoverRequestEvent.caregiver_id, CoverRequestEvent.kind)).all()
    for cid, kind, n in events:
        if kind == "ACCEPTED": counts[cid].offers_accepted += n
        else: counts[cid].offers_declined += n
    # On-time check-ins (tasks that needed one, past the missing point). A caretaker with none keeps None: "not recorded yet".
    from app.services import checkins
    for cid, ci in checkins.counts(db, caregiver_ids, since, at).items():
        if ci: counts[cid].check_ins, counts[cid].check_ins_on_time, counts[cid].check_ins_late = ci["expected"], ci["on_time"], ci["late"]
    return counts


def _inputs(db: Session, caregiver_ids: list, at: datetime, pol: dict) -> dict:
    inputs = {cid: RatingInputs() for cid in caregiver_ids}
    if not caregiver_ids: return inputs
    for cid, rating in db.execute(select(AgencyRating.caregiver_id, AgencyRating.rating).where(AgencyRating.caregiver_id.in_(caregiver_ids))):
        inputs[cid].agency = float(rating)
    for cid, rating in db.execute(select(DoctorRating.caregiver_id, DoctorRating.rating).where(DoctorRating.caregiver_id.in_(caregiver_ids))):
        inputs[cid].doctors.append(int(rating))
    for cid, rating, role in db.execute(select(Review.caregiver_id, Review.rating, Review.author_role).where(Review.caregiver_id.in_(caregiver_ids), Review.hidden.is_(False))):
        inputs[cid].customers.append((int(rating), role))
    for cid, counts in metric_counts(db, caregiver_ids, at, pol).items(): inputs[cid].metric = counts
    return inputs


def sector_priors(db: Session, pol: dict) -> dict:
    """Per sector: the mean (over caretakers) of each caretaker's raw doctor mean and customer mean. Falls back to all sectors, then 3 stars."""
    sector_of = dict(db.execute(select(CaretakerProfile.caregiver_id, CaretakerProfile.sector_id)).all())
    doc: dict = {}
    for cid, rating in db.execute(select(DoctorRating.caregiver_id, DoctorRating.rating)): doc.setdefault(cid, []).append(rating)
    cust: dict = {}
    for cid, rating, role in db.execute(select(Review.caregiver_id, Review.rating, Review.author_role).where(Review.hidden.is_(False))): cust.setdefault(cid, []).append((rating, role))
    def per_sector(means: dict) -> tuple[dict, float]:
        groups: dict = {}
        for cid, m in means.items(): groups.setdefault(sector_of.get(cid), []).append(m)
        overall = [m for ms in groups.values() for m in ms]
        return {sid: sum(ms) / len(ms) for sid, ms in groups.items()}, (sum(overall) / len(overall) if overall else NEUTRAL_STARS)
    doc_means, doc_all = per_sector({cid: sum(v) / len(v) for cid, v in doc.items()})
    cust_means, cust_all = per_sector({cid: m for cid, v in cust.items() if (m := customer_mean(v, pol["patient_review_weight"])[0]) is not None})
    return {"sector_of": sector_of, "doctors": doc_means, "customers": cust_means, "doctors_all": doc_all, "customers_all": cust_all}


def _priors_for(table: dict, cid) -> Priors:
    sid = table["sector_of"].get(cid)
    return Priors(doctors=table["doctors"].get(sid, table["doctors_all"]), customers=table["customers"].get(sid, table["customers_all"]))


def breakdowns(db: Session, caregiver_ids: list, at: datetime | None = None, pol: dict | None = None, priors: dict | None = None) -> dict:
    at, pol = at or now(), pol or current_policy()
    priors = priors or sector_priors(db, pol)
    return {cid: reputation(inp, _priors_for(priors, cid), pol) for cid, inp in _inputs(db, list(caregiver_ids), at, pol).items()}


def summary(b: dict) -> dict:
    """What a result card shows."""
    return {"composite": b["composite"], "enough_history": b["enough_history"], "rating_count": b["rating_count"], "included": b["included"]}


# --- eligibility -------------------------------------------------------------------------------------------------------

def completed_for(db: Session, caregiver_id, patient_ids: list) -> dict:
    """Completed tasks this caretaker held (confirmed primary) per patient."""
    if not patient_ids: return {}
    rows = db.execute(select(CareActivity.patient_id, func.count()).join(CareAssignment, CareAssignment.activity_id == CareActivity.id)
                      .where(CareAssignment.caregiver_id == caregiver_id, CareAssignment.role == "PRIMARY", CareAssignment.status == "CONFIRMED",
                             CareActivity.lifecycle_status == "COMPLETED", CareActivity.patient_id.in_(patient_ids)).group_by(CareActivity.patient_id)).all()
    return dict(rows)


def patients_as(db: Session, user: User, team_role: TeamRole) -> list:
    return list(db.scalars(select(CareTeamMember.patient_id).where(CareTeamMember.user_id == user.id, CareTeamMember.team_role == team_role)))


def review_patient(db: Session, user: User, caregiver_id, team_role: TeamRole, pol: dict, patient_id=None):
    """The patient through which this person may review the caretaker, or None. Needs `min_completed_tasks` completed tasks."""
    mine = patients_as(db, user, team_role)
    if patient_id is not None: mine = [p for p in mine if p == patient_id]
    done = completed_for(db, caregiver_id, mine)
    eligible = [p for p in mine if done.get(p, 0) >= pol["min_completed_tasks"]]
    return eligible[0] if eligible else None


def doctor_patient(db: Session, user: User, caregiver_id, patient_id=None):
    """A patient of this professional the caretaker served (linked to, or completed a task for)."""
    mine = patients_as(db, user, TeamRole.PROFESSIONAL)
    if patient_id is not None: mine = [p for p in mine if p == patient_id]
    if not mine: return None
    linked = set(db.scalars(select(CaregiverPatientLink.patient_id).where(CaregiverPatientLink.caregiver_id == caregiver_id, CaregiverPatientLink.patient_id.in_(mine))))
    done = completed_for(db, caregiver_id, mine)
    for p in mine:
        if p in linked or done.get(p, 0) > 0: return p
    return None


def recent(db: Session, model, author_id, caregiver_id, days: int, at: datetime | None = None):
    at = at or now()
    return db.scalar(select(model).where(model.author_user_id == author_id, model.caregiver_id == caregiver_id, model.created_at >= at - timedelta(days=days))
                     .order_by(model.created_at.desc()).limit(1))


def created_today(db: Session, author_id, at: datetime | None = None) -> int:
    at = at or now()
    since = at - timedelta(days=1)
    return (db.scalar(select(func.count()).select_from(Review).where(Review.author_user_id == author_id, Review.created_at >= since)) or 0) + \
           (db.scalar(select(func.count()).select_from(DoctorRating).where(DoctorRating.author_user_id == author_id, DoctorRating.created_at >= since)) or 0)


# --- prompts and snapshots (scheduler heavy pass) ----------------------------------------------------------------------

def prompt_key(caregiver_id) -> str:
    return f"RATE:{caregiver_id}"


def _coordinator(db: Session, patient_id):
    rows = db.execute(select(CareTeamMember.user_id, CareTeamMember.is_primary_coordinator).where(CareTeamMember.patient_id == patient_id, CareTeamMember.team_role == TeamRole.PRIMARY_CONTACT)
                      .order_by(CareTeamMember.is_primary_coordinator.desc(), CareTeamMember.created_at)).all()
    return rows[0][0] if rows else None


def run_prompts(db: Session, at: datetime | None = None, pol: dict | None = None) -> int:
    """One "Rate <caretaker>" item (and one notification) per patient and caretaker once they reach the task threshold.

    Not again while an earlier one is younger than `prompt_repeat_days`, whatever happened to it, and not when the primary
    contact already reviewed this caretaker in the rating window.
    """
    from app.services.notify import notify
    at, pol = at or now(), pol or current_policy()
    pairs = db.execute(select(CareActivity.patient_id, CareAssignment.caregiver_id, func.count()).join(CareAssignment, CareAssignment.activity_id == CareActivity.id)
                       .join(Caregiver, Caregiver.id == CareAssignment.caregiver_id)
                       .where(CareAssignment.role == "PRIMARY", CareAssignment.status == "CONFIRMED", CareActivity.lifecycle_status == "COMPLETED", Caregiver.kind == "CARETAKER")
                       .group_by(CareActivity.patient_id, CareAssignment.caregiver_id).having(func.count() >= pol["min_completed_tasks"])).all()
    if not pairs: return 0
    since = at - timedelta(days=pol["prompt_repeat_days"])
    recent_items = {(p, k) for p, k in db.execute(select(ActionItem.patient_id, ActionItem.dedupe_key).where(ActionItem.kind == "RATE_CARETAKER", ActionItem.first_seen_at >= since))}
    created = 0
    for patient_id, caregiver_id, done in pairs:
        if (patient_id, prompt_key(caregiver_id)) in recent_items: continue
        coordinator = _coordinator(db, patient_id)
        if coordinator is None: continue
        if recent(db, Review, coordinator, caregiver_id, pol["rating_window_days"], at): continue
        if db.scalar(select(ActionItem.id).where(ActionItem.patient_id == patient_id, ActionItem.dedupe_key == prompt_key(caregiver_id), ActionItem.status.in_(("OPEN", "SNOOZED")))): continue
        caregiver, patient = db.get(Caregiver, caregiver_id), db.get(Patient, patient_id)
        item = ActionItem(id=uuid.uuid4(), patient_id=patient_id, dedupe_key=prompt_key(caregiver_id), kind="RATE_CARETAKER", source="MANUAL", title=f"Rate {caregiver.name}",
                          reason=f"{caregiver.name} has completed {done} tasks for {patient.name}. A quick rating helps other families. It is optional.",
                          reasons=[], severity="LOW", related_activity_ids=[], owner_user_id=None, assigned_to_user_id=coordinator,
                          suggested_actions=[{"option": "RATE_CARETAKER", "caregiver_id": str(caregiver_id)}], first_seen_at=at, last_seen_at=at)
        db.add(item); db.flush()
        notify(db, [coordinator], patient_id, f"How is {caregiver.name} doing?", f"{caregiver.name} has completed {done} tasks for {patient.name}. Rate them in one tap if you like.",
               kind="STATUS", severity="LOW", channel="INBOX", dedupe_key=f"rate-prompt:{item.id}", link="/command-center")
        created += 1
    db.flush()
    return created


def close_prompts(db: Session, author: User, caregiver_id) -> None:
    """The primary contact rated the caretaker: their open "Rate" items for that caretaker are done."""
    mine = patients_as(db, author, TeamRole.PRIMARY_CONTACT)
    for item in db.scalars(select(ActionItem).where(ActionItem.patient_id.in_(mine), ActionItem.dedupe_key == prompt_key(caregiver_id), ActionItem.status.in_(("OPEN", "SNOOZED")))):
        item.status, item.resolution_reason, item.resolved_at, item.resolved_by = "DONE", "RATED", now(), author.id
        item.version += 1


def local_day(at: datetime):
    return at.astimezone(ZoneInfo(settings.app_timezone)).date()


def run_snapshots(db: Session, at: datetime | None = None, pol: dict | None = None) -> int:
    """One snapshot per active caretaker per local day. Idempotent: a caretaker that already has today's row is skipped."""
    at, pol = at or now(), pol or current_policy()
    day = local_day(at)
    wanted = set(db.scalars(select(Caregiver.id).where(Caregiver.kind == "CARETAKER", Caregiver.is_active.is_(True))))
    done = set(db.scalars(select(ReputationSnapshot.caregiver_id).where(ReputationSnapshot.day == day)))
    todo = sorted(wanted - done, key=str)
    if not todo: return 0
    for cid, b in breakdowns(db, todo, at, pol).items():
        db.add(ReputationSnapshot(caregiver_id=cid, day=day, metric_score=b["sources"]["metric"]["score"], composite=b["composite"], breakdown=b, computed_at=at))
    db.flush()
    return len(todo)


def run_reputation_tick(db: Session, at: datetime | None = None) -> dict:
    if not settings.feature("ratings"): return {"prompts": 0, "snapshots": 0}
    at = at or now()
    pol = current_policy()
    return {"prompts": run_prompts(db, at, pol), "snapshots": run_snapshots(db, at, pol)}
