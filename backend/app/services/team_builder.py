"""Team builder (flag `team_builder`): care preferences, directory matches, hire requests, and what the Backup Matcher
needs to know about reputation and preferences.

Hire requests: PENDING -> ACCEPTED / DECLINED / WITHDRAWN / EXPIRED. Every transition is a compare-and-set on the PENDING
row (UPDATE ... WHERE status = 'PENDING'), so when accept, withdraw and expiry race only one wins. On ACCEPT the caretaker
joins the care team with the existing invite mechanics in the same transaction; only then do care-team payloads show
their phone. Nothing is sent outside the app.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.config import settings
from app.engine.availability import effective_windows
from app.models import (ActivityHistory, AvailabilityOverride, CareActivity, CareAssignment, CareTeamMember, Caregiver, CaregiverPatientLink,
                        CaregiverWeeklySchedule, CaretakerProfile, HireRequest, Patient, PatientCarePreference, Role, Sector, TeamRole, User)

REQUEST_DAYS = 7               # a pending request expires after this
MAX_REQUESTS_PER_DAY = 20      # per primary contact
OPEN, FINAL = "PENDING", ("ACCEPTED", "DECLINED", "WITHDRAWN", "EXPIRED")
STATUS_WORDS = {"PENDING": "Waiting for an answer", "ACCEPTED": "Accepted: on the care team", "DECLINED": "Declined", "WITHDRAWN": "Withdrawn", "EXPIRED": "Expired after 7 days"}


class HireError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message); self.status = status


def _aware(value):
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


# --- preferences -------------------------------------------------------------------------------------------------------

def preferences(db: Session, patient_id) -> PatientCarePreference | None:
    return db.get(PatientCarePreference, patient_id)


def preference_dict(p: PatientCarePreference | None) -> dict:
    if p is None: return {"gender": None, "gender_mode": "SOFT", "languages": [], "city": "", "sector_code": None, "min_rating": None, "capabilities": [], "set": False}
    return {"gender": p.gender, "gender_mode": p.gender_mode, "languages": list(p.languages or []), "city": p.city, "sector_code": p.sector_code,
            "min_rating": p.min_rating, "capabilities": list(p.capabilities or []), "set": True}


def save_preferences(db: Session, patient_id, values: dict, user: User) -> PatientCarePreference:
    p = preferences(db, patient_id)
    if p is None:
        p = PatientCarePreference(patient_id=patient_id, languages=[], capabilities=[]); db.add(p)
    for key, value in values.items(): setattr(p, key, value)
    p.updated_by, p.updated_at = user.id, now()
    db.add(ActivityHistory(actor_user_id=user.id, patient_id=patient_id, event_type="care_preferences.updated", entity_type="patient", entity_id=str(patient_id),
                           summary="Care preferences updated", payload={"fields": sorted(values)}))
    db.flush()
    return p


# --- profiles the matcher and builder read -----------------------------------------------------------------------------

def profiles(db: Session, caregiver_ids: list) -> dict:
    """{caregiver_id: {composite, metric, city, sector, languages, gender}}. Reputation only when the ratings flag is on."""
    if not caregiver_ids: return {}
    sectors = {s.id: s.code for s in db.scalars(select(Sector))}
    out = {cid: {"composite": None, "metric": None, "city": "", "sector": None, "languages": [], "gender": None} for cid in caregiver_ids}
    for p in db.scalars(select(CaretakerProfile).where(CaretakerProfile.caregiver_id.in_(caregiver_ids))):
        out[p.caregiver_id].update(city=p.current_city, sector=sectors.get(p.sector_id), languages=list(p.languages or []), gender=p.gender if p.gender != "UNDISCLOSED" else None)
    if settings.feature("ratings"):
        from app.services import reputation
        for cid, b in reputation.breakdowns(db, list(caregiver_ids)).items():
            out[cid]["composite"], out[cid]["metric"] = b["composite"], b["sources"]["metric"]["score"]
    return out


def matcher_extras(db: Session, patient_id, caregiver_ids: list) -> dict | None:
    """What the Backup Matcher adds for this patient, or None when the team builder is off (the matcher then behaves as before)."""
    if not settings.feature("team_builder"): return None
    from app.core.matcher_policy import policy
    pref = preferences(db, patient_id)
    return {"profiles": {str(k): v for k, v in profiles(db, [uuid.UUID(str(c)) for c in caregiver_ids]).items()},
            "preferences": preference_dict(pref) if pref else None, "policy": policy()}


# --- matches (builder) and suggestions (pool expansion) ----------------------------------------------------------------

def _team_caregiver_ids(db: Session, patient_id) -> set:
    linked = set(db.scalars(select(CaregiverPatientLink.caregiver_id).where(CaregiverPatientLink.patient_id == patient_id)))
    members = select(CareTeamMember.user_id).where(CareTeamMember.patient_id == patient_id)
    return linked | set(db.scalars(select(Caregiver.id).where(Caregiver.user_id.in_(members))))


def capacity_note(db: Session, cg: Caregiver, at: datetime | None = None) -> str | None:
    """Plain warning when a caretaker is at their limits or has no available time in the next 7 days, so nobody is surprised."""
    at = at or now()
    end = at + timedelta(days=7)
    rows = db.execute(select(CareActivity.scheduled_start, CareActivity.scheduled_end).join(CareAssignment, CareAssignment.activity_id == CareActivity.id)
                      .where(CareAssignment.caregiver_id == cg.id, CareAssignment.role == "PRIMARY", CareAssignment.status.in_(("PROPOSED", "AWAITING_CONFIRMATION", "CONFIRMED")),
                             CareActivity.lifecycle_status == "SCHEDULED", CareActivity.scheduled_start >= at, CareActivity.scheduled_start < end)).all()
    zone = ZoneInfo(settings.app_timezone)
    per_day: dict = {}
    hours = 0.0
    for start, finish in rows:
        start, finish = _aware(start), _aware(finish)
        per_day[start.astimezone(zone).date()] = per_day.get(start.astimezone(zone).date(), 0) + 1
        hours += (finish - start).total_seconds() / 3600
    if cg.max_activities_per_day and per_day and max(per_day.values()) >= cg.max_activities_per_day:
        return f"{cg.name} is already at their daily limit of {cg.max_activities_per_day} tasks on at least one day this week."
    if cg.max_hours_per_week and hours >= cg.max_hours_per_week:
        return f"{cg.name} already has {hours:.0f} of their {cg.max_hours_per_week:g} weekly hours booked."
    schedule = list(db.scalars(select(CaregiverWeeklySchedule).where(CaregiverWeeklySchedule.caregiver_id == cg.id)))
    overrides = list(db.scalars(select(AvailabilityOverride).where(AvailabilityOverride.caregiver_id == cg.id, AvailabilityOverride.cancelled_at.is_(None))))
    if not effective_windows({"schedule": schedule, "overrides": overrides}, at, end, settings.app_timezone):
        return f"{cg.name} has no available hours in the next 7 days."
    return None


def matches(db: Session, patient_id, *, limit: int = 20, need: dict | None = None) -> list[dict]:
    """Listed directory caretakers not on the team, hard preferences applied as filters, ranked by documented points with a "why"."""
    from app.core.matcher_policy import policy
    pref = preference_dict(preferences(db, patient_id))
    if need: pref = {**pref, **{k: v for k, v in need.items() if v not in (None, "", [])}}
    team = _team_caregiver_ids(db, patient_id)
    rows = db.execute(select(CaretakerProfile, Caregiver).join(Caregiver, Caregiver.id == CaretakerProfile.caregiver_id).join(User, User.id == Caregiver.user_id)
                      .where(CaretakerProfile.listed.is_(True), Caregiver.is_active.is_(True), Caregiver.kind == "CARETAKER", User.is_active.is_(True), User.role == Role.CARETAKER)).all()
    rows = [(p, cg) for p, cg in rows if cg.id not in team]
    info = profiles(db, [cg.id for _, cg in rows])
    pol = policy()
    from app.engine.backup_matcher import extra_points
    out = []
    for p, cg in rows:
        prof = info[cg.id]
        missing = sorted(set(pref["capabilities"]) - set(cg.capabilities or []))
        if missing: continue
        if pref["gender"] and pref["gender_mode"] == "HARD" and prof["gender"] != pref["gender"]: continue
        below = pref["min_rating"] is not None and prof["composite"] is not None and prof["composite"] < pref["min_rating"]
        if below: continue
        points = extra_points(cg.name, prof, pref, pol)
        why = [x["label"] for x in points if x["points"] > 0]
        if prof["composite"] is None: why.append("No rating yet: shown, not ranked down")
        if pref["capabilities"]: why.append("Has every must-have skill")
        out.append({"caregiver_id": str(cg.id), "name": cg.name, "score": sum(x["points"] for x in points), "points": points, "why": why,
                    "composite": prof["composite"], "metric": prof["metric"], "city": p.current_city, "state": p.current_state, "sector": prof["sector"],
                    "gender": p.gender, "languages": list(p.languages or []), "capabilities": list(cg.capabilities or []), "years_experience": p.years_experience,
                    "unrated": prof["composite"] is None})
    out.sort(key=lambda m: (-m["score"], -(m["composite"] or 50), m["name"].lower(), m["caregiver_id"]))
    return out[:limit]


def suggestions(db: Session, patient_id, required: list[str], limit: int = 3) -> list[dict]:
    """When nobody on the team can take a task: the best directory caretakers in the patient's region, as suggestions to
    send a hire request to. Never added, never offered: only a primary contact's request and the caretaker's acceptance can."""
    if not settings.feature("team_builder"): return []
    pref = preference_dict(preferences(db, patient_id))
    need = {"capabilities": sorted(set(pref["capabilities"]) | set(required or []))}
    found = matches(db, patient_id, limit=50, need=need)
    if pref["sector_code"]: found = [m for m in found if m["sector"] == pref["sector_code"]] or found
    return [{"caregiver_id": m["caregiver_id"], "name": m["name"], "composite": m["composite"], "city": m["city"], "why": m["why"][:3],
             "prompt": f"Send a request to {m['name'].split()[0]}?"} for m in found[:limit]]


# --- hire requests -----------------------------------------------------------------------------------------------------

def request_dict(db: Session, r: HireRequest, *, viewer: User) -> dict:
    """Never includes phone, email or notes: contact details appear through the care team only after acceptance."""
    cg, patient, by = db.get(Caregiver, r.caregiver_id), db.get(Patient, r.patient_id), db.get(User, r.requested_by)
    out = {"id": str(r.id), "patient": {"id": str(patient.id), "name": patient.name}, "caretaker": {"id": str(cg.id), "name": cg.name}, "requested_by": by.name if by else None,
           "intended_role": r.intended_role, "message": r.message, "status": r.status, "status_text": STATUS_WORDS[r.status], "decline_reason": r.decline_reason,
           "created_at": _aware(r.created_at).isoformat(), "expires_at": _aware(r.expires_at).isoformat(), "responded_at": _aware(r.responded_at).isoformat() if r.responded_at else None}
    if r.status == OPEN: out["capacity_note"] = capacity_note(db, cg)
    return out


def create(db: Session, user: User, patient_id, caregiver_id, *, role: str, message: str, idempotency_key: str | None, at: datetime | None = None) -> tuple[HireRequest, bool]:
    """Returns (request, created). The same Idempotency-Key from the same person returns the original request."""
    at = at or now()
    if idempotency_key:
        prior = db.scalar(select(HireRequest).where(HireRequest.requested_by == user.id, HireRequest.idempotency_key == idempotency_key))
        if prior:
            if prior.patient_id != patient_id or prior.caregiver_id != caregiver_id: raise HireError(422, "That Idempotency-Key was used for a different request")
            return prior, False
    cg = db.get(Caregiver, caregiver_id)
    profile = db.scalar(select(CaretakerProfile).where(CaretakerProfile.caregiver_id == caregiver_id)) if cg else None
    if not cg or not profile or not profile.listed or cg.kind != "CARETAKER" or not cg.user_id or not cg.is_active: raise HireError(404, "Caretaker not found in the directory")
    if cg.id in _team_caregiver_ids(db, patient_id): raise HireError(409, f"{cg.name} is already on this care team")
    if db.scalar(select(HireRequest.id).where(HireRequest.patient_id == patient_id, HireRequest.caregiver_id == cg.id, HireRequest.status == OPEN)):
        raise HireError(409, f"A request to {cg.name} for this patient is already waiting")
    sent = db.scalar(select(func.count()).select_from(HireRequest).where(HireRequest.requested_by == user.id, HireRequest.created_at >= at - timedelta(days=1))) or 0
    if sent >= MAX_REQUESTS_PER_DAY: raise HireError(429, "Too many hire requests today; try again tomorrow")
    r = HireRequest(patient_id=patient_id, caregiver_id=cg.id, requested_by=user.id, intended_role=role, message=message.strip()[:300], status=OPEN,
                    idempotency_key=idempotency_key, created_at=at, expires_at=at + timedelta(days=REQUEST_DAYS))
    db.add(r); db.flush()
    patient = db.get(Patient, patient_id)
    from app.services.notify import notify
    notify(db, [cg.user_id], patient_id, "New request to join a care team",
           f"{user.name} asks you to join {patient.name}'s care team as {'main caretaker' if role == 'MAIN' else 'a backup'}. Accept or decline in Hire requests.",
           kind="DECISION", severity="MEDIUM", channel="INBOX", link="/hire-requests", dedupe_key=f"hire:{r.id}")
    db.add(ActivityHistory(actor_user_id=user.id, patient_id=patient_id, event_type="hire_request.sent", entity_type="hire_request", entity_id=str(r.id),
                           summary=f"Hire request sent to {cg.name}", payload={"role": role}))
    return r, True


def _transition(db: Session, r: HireRequest, status: str, at: datetime, **values) -> bool:
    """Compare-and-set from PENDING. True only for the single caller that moved it."""
    done = db.execute(update(HireRequest).where(HireRequest.id == r.id, HireRequest.status == OPEN)
                      .values(status=status, responded_at=at, version=HireRequest.version + 1, **values).execution_options(synchronize_session=False)).rowcount
    db.refresh(r)
    return done == 1


def accept(db: Session, r: HireRequest, caretaker_user: User, at: datetime | None = None) -> HireRequest:
    at = at or now()
    cg = db.get(Caregiver, r.caregiver_id)
    if cg.user_id != caretaker_user.id: raise HireError(403, "Only the caretaker this request was sent to can answer it")
    if r.status == OPEN and _aware(r.expires_at) <= at:
        expire(db, r, at); raise HireError(409, "This request has expired")
    if not _transition(db, r, "ACCEPTED", at): raise HireError(409, f"This request is already {r.status.lower()}")
    # Same transaction: join the team with the invite mechanics, then set the requested role.
    from app.services.care_team import ensure_care_profile
    from app.services.notify import family_ids, notify
    if not db.scalar(select(CareTeamMember.id).where(CareTeamMember.patient_id == r.patient_id, CareTeamMember.user_id == caretaker_user.id)):
        db.add(CareTeamMember(patient_id=r.patient_id, user_id=caretaker_user.id, team_role=TeamRole.CARETAKER)); db.flush()
    ensure_care_profile(db, caretaker_user, r.patient_id, created_by=r.requested_by, relationship="main caretaker" if r.intended_role == "MAIN" else "backup caretaker")
    links = db.scalars(select(CaregiverPatientLink).where(CaregiverPatientLink.patient_id == r.patient_id)).all()
    mine = next(l for l in links if l.caregiver_id == cg.id)
    if r.intended_role == "MAIN":
        for link in links: link.is_main_caretaker = link is mine
    else:
        mine.is_designated_backup = True
    patient = db.get(Patient, r.patient_id)
    notify(db, family_ids(db, r.patient_id), r.patient_id, f"{cg.name} accepted", f"{cg.name} joined {patient.name}'s care team as {'main caretaker' if r.intended_role == 'MAIN' else 'a backup'}. Their contact details are now in Care Team.",
           kind="DECISION", severity="MEDIUM", link=f"/care-team?patient={r.patient_id}")
    db.add(ActivityHistory(actor_user_id=caretaker_user.id, patient_id=r.patient_id, event_type="hire_request.accepted", entity_type="hire_request", entity_id=str(r.id),
                           summary=f"{cg.name} accepted the hire request and joined the care team", payload={"role": r.intended_role}))
    db.flush()
    from app.services.reassess import TriggerEvent, reassess
    reassess(db, [r.patient_id], TriggerEvent.ASSIGNMENT_ADDED, {"caregiver_id": str(cg.id)})
    return r


def decline(db: Session, r: HireRequest, caretaker_user: User, reason: str = "", at: datetime | None = None) -> HireRequest:
    at = at or now()
    cg = db.get(Caregiver, r.caregiver_id)
    if cg.user_id != caretaker_user.id: raise HireError(403, "Only the caretaker this request was sent to can answer it")
    if not _transition(db, r, "DECLINED", at, decline_reason=reason.strip()[:300]): raise HireError(409, f"This request is already {r.status.lower()}")
    from app.services.notify import notify
    notify(db, [r.requested_by], r.patient_id, f"{cg.name} declined", "They declined your request. Nothing was shared. Build care team shows other matches.", kind="STATUS", severity="LOW",
           channel="INBOX", link="/build-team")
    db.add(ActivityHistory(actor_user_id=caretaker_user.id, patient_id=r.patient_id, event_type="hire_request.declined", entity_type="hire_request", entity_id=str(r.id),
                           summary=f"{cg.name} declined the hire request", payload={}))
    return r


def withdraw(db: Session, r: HireRequest, user: User, at: datetime | None = None) -> HireRequest:
    at = at or now()
    member = db.scalar(select(CareTeamMember).where(CareTeamMember.patient_id == r.patient_id, CareTeamMember.user_id == user.id))
    if user.role != Role.PRIMARY_CONTACT or not member or member.team_role != TeamRole.PRIMARY_CONTACT: raise HireError(403, "Only the patient's primary contacts can withdraw this")
    if not _transition(db, r, "WITHDRAWN", at): raise HireError(409, f"This request is already {r.status.lower()}")
    cg = db.get(Caregiver, r.caregiver_id)
    from app.services.notify import notify
    notify(db, [cg.user_id], r.patient_id, "Request withdrawn", "A family withdrew their request to you. No action needed.", kind="STATUS", severity="LOW", channel="INBOX", link="/hire-requests")
    db.add(ActivityHistory(actor_user_id=user.id, patient_id=r.patient_id, event_type="hire_request.withdrawn", entity_type="hire_request", entity_id=str(r.id), summary="Hire request withdrawn", payload={}))
    return r


def expire(db: Session, r: HireRequest, at: datetime | None = None) -> bool:
    at = at or now()
    if not _transition(db, r, "EXPIRED", at): return False
    from app.services.notify import notify
    notify(db, [r.requested_by], r.patient_id, "Hire request expired", f"{db.get(Caregiver, r.caregiver_id).name} did not answer within {REQUEST_DAYS} days. Nothing was shared.",
           kind="STATUS", severity="LOW", channel="INBOX", link="/build-team", dedupe_key=f"hire-expired:{r.id}")
    return True


def run_expiry_tick(db: Session, at: datetime | None = None) -> int:
    """Scheduler heavy pass: expire PENDING requests past their 7 days. Idempotent (compare-and-set)."""
    if not settings.feature("team_builder"): return 0
    at = at or now()
    n = sum(expire(db, r, at) for r in db.scalars(select(HireRequest).where(HireRequest.status == OPEN, HireRequest.expires_at <= at)).all())
    db.flush()
    return n


# --- attention and insights --------------------------------------------------------------------------------------------

def attention_items(db: Session, patient_id, at: datetime) -> list:
    """Extra Command Center items (derived, so they clear themselves): a HIGH/CRITICAL task in the next 72 h with no backup
    at or above the family's minimum rating, and one quiet item for hire requests still waiting for an answer."""
    if not settings.feature("team_builder"): return []
    from app.engine.attention import AttentionItem
    items = []
    waiting = db.scalar(select(func.count()).select_from(HireRequest).where(HireRequest.patient_id == patient_id, HireRequest.status == OPEN)) or 0
    if waiting:
        items.append(AttentionItem(dedupe_key=f"HIRE_REQUESTS_OPEN:{patient_id}", kind="HIRE_REQUESTS_OPEN", severity="LOW", bucket="AT_RISK",
                                   title=f"{waiting} hire request{'s' if waiting != 1 else ''} waiting for an answer",
                                   reason="Caretakers have 7 days to accept or decline. Nothing is shared until they accept.", reasons=()))
    pref = preferences(db, patient_id)
    if pref is None or pref.min_rating is None or not settings.feature("ratings"): return items
    tasks = db.scalars(select(CareActivity).where(CareActivity.patient_id == patient_id, CareActivity.lifecycle_status == "SCHEDULED", CareActivity.requires_caregiver.is_(True),
                                                  CareActivity.importance.in_(("HIGH", "CRITICAL")), CareActivity.scheduled_start >= at,
                                                  CareActivity.scheduled_start < at + timedelta(hours=72)).order_by(CareActivity.scheduled_start, CareActivity.id)).all()
    if not tasks: return items
    backups = db.execute(select(CareAssignment.activity_id, CareAssignment.caregiver_id).where(CareAssignment.activity_id.in_([t.id for t in tasks]),
                                                                                              CareAssignment.role == "BACKUP", CareAssignment.status == "CONFIRMED")).all()
    from app.services import reputation
    scores = {cid: b["composite"] for cid, b in reputation.breakdowns(db, list({c for _, c in backups})).items()} if backups else {}
    good = {aid for aid, cid in backups if scores.get(cid) is not None and scores[cid] >= pref.min_rating}
    short = [t for t in tasks if t.id not in good]
    if short:
        items.append(AttentionItem(dedupe_key=f"BACKUP_BELOW_MIN_RATING:{patient_id}", kind="BACKUP_BELOW_MIN_RATING", severity="MEDIUM", bucket="AT_RISK",
                                   title=f"{len(short)} important task{'s' if len(short) != 1 else ''} without a backup rated {pref.min_rating:g}+",
                                   reason=f"{short[0].title} and others in the next 72 hours have no confirmed backup at or above the family's minimum rating of {pref.min_rating:g}.",
                                   reasons=tuple(f"{t.title}" for t in short[:5]), activity_ids=tuple(str(t.id) for t in short)))
    return items


def team_reputation(db: Session, patient_ids: list) -> dict:
    """Per patient: how many caretakers, their average and lowest composite, and how many are unrated."""
    if not patient_ids or not settings.feature("ratings"): return {}
    rows = db.execute(select(CaregiverPatientLink.patient_id, Caregiver.id).join(Caregiver, Caregiver.id == CaregiverPatientLink.caregiver_id)
                      .where(CaregiverPatientLink.patient_id.in_(patient_ids), Caregiver.kind == "CARETAKER", Caregiver.is_active.is_(True))).all()
    from app.services import reputation
    scores = {cid: b["composite"] for cid, b in reputation.breakdowns(db, list({c for _, c in rows})).items()} if rows else {}
    out: dict = {}
    for pid, cid in rows:
        t = out.setdefault(str(pid), {"caretakers": 0, "rated": [], "unrated": 0})
        t["caretakers"] += 1
        if scores.get(cid) is None: t["unrated"] += 1
        else: t["rated"].append(scores[cid])
    return {pid: {"caretakers": t["caretakers"], "unrated": t["unrated"], "average": round(sum(t["rated"]) / len(t["rated"]), 1) if t["rated"] else None,
                  "lowest": round(min(t["rated"]), 1) if t["rated"] else None} for pid, t in out.items()}
