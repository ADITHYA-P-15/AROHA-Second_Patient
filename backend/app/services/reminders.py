"""Timely reminders, run by the scheduler every minute. Each one is sent once per person (dedupe key).

- Dose due in 15 minutes: the caretaker who holds it.
- Appointment tomorrow, and again in two hours: the escort, the family and the patient.
- Nobody confirmed yet for something soon: the family, so they can act before it is late.
- A cover offer left unanswered for half an hour: the caretaker it was offered to.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.config import settings
from app.models import CareActivity, CareAssignment, Caregiver, CoverRequest, TeamRole
from app.services.notify import family_ids, notify, team_user_ids

DOSE_LEAD = timedelta(minutes=15)
UNCONFIRMED_DOSE_LEAD = timedelta(hours=3)
UNCONFIRMED_VISIT_LEAD = timedelta(hours=24)
APPOINTMENT_LEADS = (("2h", timedelta(hours=2)), ("24h", timedelta(hours=24)))  # the nearest one that applies wins
OFFER_WAIT = timedelta(minutes=30)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _clock(value: datetime) -> str:
    return _aware(value).astimezone(ZoneInfo(settings.app_timezone)).strftime("%H:%M")


def _day_clock(value: datetime) -> str:
    return _aware(value).astimezone(ZoneInfo(settings.app_timezone)).strftime("%a %d %b, %H:%M")


def run_reminders(db: Session, at: datetime | None = None) -> int:
    at = at or now()
    horizon = at + timedelta(hours=25)
    activities = db.scalars(select(CareActivity).where(CareActivity.lifecycle_status == "SCHEDULED", CareActivity.requires_caregiver.is_(True),
                                                       CareActivity.scheduled_start > at, CareActivity.scheduled_start <= horizon)).all()
    sent = 0
    if activities:
        ids = [a.id for a in activities]
        holders: dict = {}
        for activity_id, user_id in db.execute(select(CareAssignment.activity_id, Caregiver.user_id).join(Caregiver, Caregiver.id == CareAssignment.caregiver_id)
                                               .where(CareAssignment.activity_id.in_(ids), CareAssignment.role == "PRIMARY", CareAssignment.status == "CONFIRMED")):
            holders[activity_id] = user_id
        families: dict = {}
        patients_self: dict = {}

        def family(patient_id):
            if patient_id not in families: families[patient_id] = family_ids(db, patient_id)
            return families[patient_id]

        def patient_self(patient_id):
            if patient_id not in patients_self: patients_self[patient_id] = team_user_ids(db, patient_id, [TeamRole.PATIENT_SELF])
            return patients_self[patient_id]

        for a in activities:
            start, left = _aware(a.scheduled_start), _aware(a.scheduled_start) - at
            holder = holders.get(a.id)
            is_dose = a.source == "PRESCRIPTION"
            if holder is None:
                lead = UNCONFIRMED_DOSE_LEAD if is_dose else UNCONFIRMED_VISIT_LEAD
                if left <= lead:
                    sent += notify(db, family(a.patient_id), a.patient_id, f"No one confirmed yet: {a.title}", f"Due {_day_clock(start)}. Choose a caretaker or ask for cover before it is late.",
                                   kind="REMINDER", severity="HIGH", link=f"/care-plan?patient={a.patient_id}", dedupe_key=f"unconfirmed:{a.id}")
                continue
            if is_dose:
                if left <= DOSE_LEAD:
                    sent += notify(db, [holder], a.patient_id, f"Due at {_clock(start)}: {a.title}", (a.description or "Mark it done in My Day once given."),
                                   kind="REMINDER", severity="MEDIUM", link="/my-day", dedupe_key=f"remind:{a.id}:15m")
            elif a.category == "APPOINTMENT":
                label = next((name for name, lead in APPOINTMENT_LEADS if left <= lead), None)
                if label:
                    when = "In two hours" if label == "2h" else "Within a day"
                    place = f", {a.location_note}" if a.location_note else ""
                    recipients = [holder, *family(a.patient_id), *patient_self(a.patient_id)]
                    sent += notify(db, recipients, a.patient_id, f"{when}: {a.title}", f"{_day_clock(start)}{place}.", kind="REMINDER", severity="MEDIUM",
                                   link=f"/care-plan?patient={a.patient_id}", dedupe_key=f"remind:{a.id}:{label}")

    # An offer nobody has answered yet.
    waiting = db.scalars(select(CoverRequest).where(CoverRequest.status == "OFFERED", CoverRequest.offered_at.is_not(None), CoverRequest.offered_at <= at - OFFER_WAIT)).all()
    for request in waiting:
        user_id = db.scalar(select(Caregiver.user_id).where(Caregiver.id == request.offered_caregiver_id))
        activity = db.get(CareActivity, request.activity_id)
        if user_id and activity is not None:
            sent += notify(db, [user_id], request.patient_id, f"Still waiting for your answer: {activity.title}", f"{_day_clock(activity.scheduled_start)}. Can you cover it?",
                           kind="REMINDER", severity="MEDIUM", link="/cover", dedupe_key=f"offer-wait:{request.id}:{request.offered_caregiver_id}")
    return sent
