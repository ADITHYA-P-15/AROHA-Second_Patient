"""One place to tell people about decisions and to remind them in time.

Every notification is stored for the bell and also pushed to the person's open screens (toast, sound, browser alert) by the
front end, which polls for new ones. `dedupe_key` makes reminders and repeated events arrive once per person.
"""
from __future__ import annotations

from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Caregiver, CareAssignment, CareTeamMember, Notification, TeamRole, User


def team_user_ids(db: Session, patient_id, roles: Iterable[TeamRole] | None = None) -> list:
    query = select(CareTeamMember.user_id).where(CareTeamMember.patient_id == patient_id)
    if roles: query = query.where(CareTeamMember.team_role.in_(list(roles)))
    return list(dict.fromkeys(db.scalars(query)))


def family_ids(db: Session, patient_id) -> list:
    return team_user_ids(db, patient_id, [TeamRole.PRIMARY_CONTACT])


def holder_user_id(db: Session, activity_id):
    """The caretaker currently confirmed for an activity, if any."""
    return db.scalar(select(Caregiver.user_id).join(CareAssignment, CareAssignment.caregiver_id == Caregiver.id)
                     .where(CareAssignment.activity_id == activity_id, CareAssignment.role == "PRIMARY", CareAssignment.status == "CONFIRMED"))


def caregiver_user_id(db: Session, caregiver_id):
    return db.scalar(select(Caregiver.user_id).where(Caregiver.id == caregiver_id))


def notify(db: Session, user_ids: Iterable, patient_id, title: str, body: str = "", *, kind: str = "STATUS", severity: str = "LOW", incident_id=None,
           dedupe_key: str | None = None, link: str | None = None, requires_ack: bool = False, channel: str = "ALERT", exclude: Iterable = ()) -> int:
    """Tell each person once. People in `exclude` (usually the actor, who just did it) are skipped. Returns how many were created."""
    skip = {x for x in exclude if x}
    created = 0
    for user_id in dict.fromkeys(u for u in user_ids if u):
        if user_id in skip: continue
        if dedupe_key and db.scalar(select(Notification.id).where(Notification.user_id == user_id, Notification.dedupe_key == dedupe_key).limit(1)):
            continue
        db.add(Notification(user_id=user_id, patient_id=patient_id, incident_id=incident_id, kind=kind, severity=severity, title=title[:160], body=(body or "")[:500],
                            requires_ack=requires_ack, channel=channel, dedupe_key=dedupe_key, link=link))
        created += 1
    return created


def name_of(db: Session, user_id) -> str:
    user = db.get(User, user_id) if user_id else None
    return user.name if user else "Someone"
